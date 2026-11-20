"""
moonglade/cards.py
==================
Free cards (kaisuuken): the summary, logs and type catalog reads, the coupons and the credit
log, the spend-time card check (`match_kaisuuken`) and its notes (`card_covers`,
`card_short_note`), the sign-in refusal it can meet, the auto-apply on a submit
(`_apply_kaisuuken`), the preview's card line (`_preview_card_note`) and the use count
(`_bump_card_use`). Moved verbatim out of moonglade/backup.py in the 3.22 split (phase 5), with
the section's notes on the two /v2 routes. The `_rest_*` delegates they ride stay in the engine.

It reaches the mirror as `_mirror.X` and the price as `_pricing.price_task`. The names it reads
from the engine (the `_rest_*` delegates, gql_adhoc, _make_session, the error classes, and the
Unlimited Mode names until the road moves) are imported inside each function that uses them,
at call time, so a test's patch of backup's binding still reaches them and importing this
module never imports the engine.
"""
import re
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")

from moonglade import mirror as _mirror
from moonglade import pricing as _pricing


def _bump_card_use(params):
    """Thrifty Archivist: count the free card only once its task ACTUALLY submitted
    (a card attached to a rejected submit was never spent). Fail-soft no-op."""
    if isinstance(params, dict) and params.get("kaisuukenId"):
        try:
            from moonglade.telemetry import telem_bump
            telem_bump("free_cards_applied")
        except Exception:
            pass


# --- Free "cards" (kaisuuken / 回数券) -------------------------------------------
# PixAI grants free-generation tickets ("kaisuuken", model-locked) via membership/events.
# These live on the oRPC /v2 REST API, NOT GraphQL (verified 2026-07-03 from the app's
# own contract). Two ops matter:
#   GET  /v2/kaisuuken/summary  -> {kaisuukens:[{count, expiryCounts, templateId, taskTypes,
#                                    routeToNative, templateName, ...}]}  (one row per template)
#   POST /v2/kaisuuken/check    -> given a generation's params, returns the matching cards +
#                                  individual TICKET ids: {matches:[{templateId,
#                                  kaisuukens:[{id, expiresAt}] (<=3, nearest first), total}]}
# On pixai.art the web client calls `check` and attaches the ticket id for you; we do the
# same via _apply_kaisuuken (attach `kaisuukenId` -> server consumes the card -> 0 credits).
# The `check` call is READ-ONLY: it never consumes a card; consumption happens only when a
# task is actually submitted with the attached id. Both helpers fail soft.


def _normalize_kaisuuken(raw):
    """Normalize one kaisuuken TEMPLATE row from /v2/kaisuuken/summary. Each row is a
    template with a held `count` (not per-id ids -- those come from `check`). The model
    it's locked to lives in routeToNative (pixai://...?modelVersionId=NNN)."""
    raw = raw or {}
    m = re.search(r"modelVersionId=(\d+)", raw.get("routeToNative") or "")
    return {
        "name": raw.get("templateName") or raw.get("templateCode") or "card",
        "count": raw.get("count"),
        "category": raw.get("categoryName") or raw.get("categoryCode") or "",
        "task_types": raw.get("taskTypes") or [],
        "model_version_id": m.group(1) if m else "",
        "template_code": raw.get("templateCode") or "",
        "template_id": raw.get("templateId") or "",
        "expires": raw.get("soonestExpireAt") or "",
        # Every expiry date the type holds, with how many expire then (Session Y, #69): the
        # credits chip's "N <kind> expire <date>" lines. A dateless or unreadable entry is
        # dropped -- it can never expire soon.
        "expiry_counts": _expiry_counts(raw.get("expiryCounts")),
    }


def _expiry_counts(rows):
    out = []
    for e in rows or []:
        if not isinstance(e, dict) or not e.get("expiresAt"):
            continue
        try:
            n = int(e.get("count") or 0)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.append({"expires_at": str(e["expiresAt"]), "count": n})
    return out


def list_kaisuukens(session):
    """Read the account's free-generation cards via GET /v2/kaisuuken/summary. Read-only;
    fails soft (returns []) on error. One row per template, with the held `count`, the
    model it's locked to, and soonest expiry."""
    from moonglade.backup import PixAIError, _rest_get
    try:
        data = _rest_get(session, "/kaisuuken/summary") or {}
    except (PixAIError, requests.RequestException, ValueError):
        # "Fails soft" has to mean every way this call can fail, not just the tidy one.
        # _rest_get only converts a non-2xx into a PixAIError -- a ConnectionError or a
        # read timeout comes straight out of the raw session.get, and a malformed 200 body
        # out of r.json() as a ValueError. Both used to escape, and the caller that felt it
        # is match_kaisuuken(enrich=True): its own try/except covers the /kaisuuken/check
        # POST but not this cross-reference, so an escape there broke the fail-soft /
        # raise_on_error contract every enrich caller relies on -- including the one inside
        # _apply_kaisuuken, mid --confirm, whose except only catches (PixAIError, ValueError).
        # An unreadable summary costs the card's model preference and its display name,
        # exactly as it already did when the failure happened to be a PixAIError.
        return []
    rows = data.get("kaisuukens")
    if rows is None:
        return []
    return [_normalize_kaisuuken(k) for k in rows]


def list_kaisuuken_logs(session, first=50, after=None):
    """Read the account's benefit-card USAGE history via GET /v2/kaisuuken/logs -- the
    per-redemption ledger, distinct from the held-count summary /v2/kaisuukens/summary gives
    (that one only has a live `count`; this one is the paper trail of every time a card was
    actually spent). Verified live 2026-08-02 against the account's own history.

    Each row: {record_id, template_name, category, task_type, task_id, action, credit_cost,
    created_at}. `action` is one of the four actions PixAI's contract allows: "consumed",
    "refunded", "expired" or "revoked". PixAI hands a card back (a NEW record, same
    kaisuukenId, action=refunded) when the task it was attached to failed or was refused; a
    single card can cycle consumed->refunded->consumed again across different tasks, so
    record_id is not 1:1 with "one use". "expired" is a card that ran out unused and "revoked"
    one PixAI took back: neither was attached to a task, so those rows come with no task id
    (task_id "") and no credit cost (None). The first expiry row on the owner's log is dated
    2026-09-18 (PROBE_2026-10-02_site, #68); cards that ran out before then left no row.
    `credit_cost` is what the redemption would have cost in credits had no card covered it --
    useful for a "cards have saved you N credits" total, never an actual charge (the whole
    point of the card is that it wasn't charged).

    Cursor-paginated (Relay style): pass a previous call's `end_cursor` as `after` to page
    forward; `has_next` says whether more exist. Read-only; fails soft on error (matching
    list_kaisuukens()'s contract) since a glitched read should never block a display."""
    from moonglade.backup import PixAIError, _rest_get
    try:
        params = {"first": int(first)}
        if after:
            params["after"] = str(after)
        data = _rest_get(session, "/kaisuuken/logs", params=params) or {}
    except (PixAIError, requests.RequestException, ValueError):
        return {"logs": [], "has_next": False, "end_cursor": None}
    rows = data.get("data")
    if rows is None:
        return {"logs": [], "has_next": False, "end_cursor": None}
    page = data.get("pageInfo") or {}
    logs = [{
        "record_id": r.get("id") or "",
        "template_name": r.get("templateName") or "",
        "category": r.get("categoryCode") or "",
        "task_type": r.get("taskType") or "",
        "task_id": str(r.get("taskId") or ""),
        "action": r.get("action") or "",
        "credit_cost": r.get("creditCost"),
        "created_at": r.get("createdAt") or "",
    } for r in rows]
    return {"logs": logs, "has_next": bool(page.get("hasNextPage")), "end_cursor": page.get("endCursor")}


def kaisuuken_type_catalog(session, max_pages=25):
    """Page ALL the way back through list_kaisuuken_logs() to build a lifetime roster of
    every benefit-card TEMPLATE this account has ever redeemed or been refunded -- the "what
    types have I ever held" answer /v2/kaisuuken/summary can't give once a card type fully
    expires out of current holdings (verified 2026-08-02: Reference Pro Only and Edit Pro
    Only both fully cycled out of live holdings but still show up here going back ~a month).

    Each template counts all four actions the log carries -- consumed, refunded, expired and
    revoked (#68) -- so a card type that only ever ran out still has its row, with its expiries
    counted rather than dropped.

    Caveat: the log's first expiry row is dated 2026-09-18, so a card type that expired
    untouched before then left no trace here (verified 2026-08-02); the roster is a lower
    bound on "every card type ever granted", not an exact one.

    Capped at `max_pages` pages of 100 rows each as a politeness/safety bound -- an old
    account could otherwise page indefinitely. Returns what it found plus whether the cap
    was hit before the log ran out, so a caller can tell "that's everything" from "there's
    more, ask for more pages"."""
    catalog = {}
    cursor, pages, hit_cap = None, 0, False
    while pages < max_pages:
        page = list_kaisuuken_logs(session, first=100, after=cursor)
        for row in page["logs"]:
            name = row["template_name"] or "(unknown)"
            entry = catalog.setdefault(name, {
                "category": row["category"], "task_type": row["task_type"],
                "consumed": 0, "refunded": 0, "expired": 0, "revoked": 0,
                "first_seen": row["created_at"], "last_seen": row["created_at"]})
            if row["action"] in ("consumed", "refunded", "expired", "revoked"):
                entry[row["action"]] += 1
            ts = row["created_at"]
            if ts and (not entry["first_seen"] or ts < entry["first_seen"]):
                entry["first_seen"] = ts
            if ts and (not entry["last_seen"] or ts > entry["last_seen"]):
                entry["last_seen"] = ts
        pages += 1
        if not page["has_next"] or not page["logs"]:
            break
        cursor = page["end_cursor"]
    else:
        hit_cap = True
    return {"templates": catalog, "pages_read": pages, "hit_page_cap": hit_cap}


# --- Coupons ("Credit Boost", extra-package-boosts) ---------------------------
# A reward type entirely SEPARATE from kaisuuken benefit cards, verified live 2026-08-02
# (owner: "coupons are for monthly events, one is live now"). A coupon is a percentage
# bonus applied to an "Extra Package" (credit-pack) purchase, not a free generation -- the
# naming of its own endpoint (extra-package-boosts) confirms the mechanic. Lives on the
# same oRPC /v2 REST surface as kaisuuken, but is its own resource, not a kaisuuken variant.

#: The site's own "My Coupons" top list (what you currently HOLD) vs its "View coupon
#: history" accordion (what's past) are the SAME endpoint, told apart only by `statuses` --
#: both CONFIRMED via live network capture 2026-08-02, resolving what the first pass here
#: left as an unconfirmed guess.
COUPON_STATUSES_ON_HAND = ("available", "locked")
COUPON_STATUSES_HISTORY = ("redeemed", "expired")


def list_extra_package_boosts(session, statuses=COUPON_STATUSES_ON_HAND, first=50, after=None):
    """Read the account's "Credit Boost" coupons via GET /v2/extra-package-boosts. Defaults
    to what you currently HOLD (COUPON_STATUSES_ON_HAND) -- the primary ask ("list what we
    have on hand", not just a spend history). Pass `statuses=COUPON_STATUSES_HISTORY` for
    the past (redeemed + expired) view instead; both share this one endpoint.

    Each row: {code, boost_percent, status, issued_by, note, locked_for_order_id,
    available_since, available_until, created_at}. `locked_for_order_id` ties a redeemed
    coupon to the specific purchase order it boosted -- the same link behind the credit log's
    "Extra Package" rows carrying a matching reason tag (see the credit-ledger work).
    Cursor-paginated (Relay style, same shape as list_kaisuuken_logs); read-only, fails soft
    on error."""
    from moonglade.backup import PixAIError, _rest_get
    try:
        params = {"first": int(first)}
        for i, s in enumerate(statuses):
            params["status[{}]".format(i)] = s
        if after:
            params["after"] = str(after)
        data = _rest_get(session, "/extra-package-boosts", params=params) or {}
    except (PixAIError, requests.RequestException, ValueError):
        return {"coupons": [], "has_next": False, "end_cursor": None}
    rows = data.get("data")
    if rows is None:
        return {"coupons": [], "has_next": False, "end_cursor": None}
    page = data.get("pageInfo") or {}
    coupons = [{
        "code": r.get("code") or "",
        "boost_percent": r.get("boostRatePercentage"),
        "status": r.get("status") or "",
        "issued_by": r.get("issuedBy") or "",
        "note": r.get("note") or "",
        "locked_for_order_id": r.get("lockedForOrderId") or "",
        "available_since": r.get("availableSince") or "",
        "available_until": r.get("availableUntil") or "",
        "created_at": r.get("createdAt") or "",
    } for r in rows]
    return {"coupons": coupons, "has_next": bool(page.get("hasNextPage")),
            "end_cursor": page.get("endCursor")}


# --- Credit Ledger (full spend/purchase/gift history) -------------------------
# The REAL "spend history" behind the site's Membership & Credits -> Credit log table --
# a much bigger surface than either kaisuuken_logs or extra_package_boosts, and NOT the
# same endpoint as either: rides ad-hoc GraphQL `me.quotaLogs`, not the /v2 REST surface.
#
# ** 2026-08-07 fix: query `me`, NOT `user(id: $userId)`. ** The original used
# `user(id).quotaLogs` and always came back EMPTY -- quotaLogs is private financial data
# that PixAI exposes ONLY on `me`, never on the public `user(id)` type, even for your own
# id (no error, just an empty connection -- which is why the "verified live 2026-08-02"
# claim slipped through). Confirmed live against the real account 2026-08-07: `me.quotaLogs`
# returns the real ledger (daily claims, event gifts, spend...) with working backward
# pagination; `user(id).quotaLogs` returns nothing. The `reason`/`logReason` server-side
# filter is dropped -- it isn't offered on the `me` connection and nothing in the app sends
# it (the modal has no reason filter); re-add via a probed arg name if a filter UI is built.
_QUOTA_LOG_QUERY = """
query($last: Int!, $before: String) {
  me {
    id
    quotaLogs(last: $last, before: $before) {
      pageInfo { hasNextPage hasPreviousPage startCursor endCursor }
      edges {
        cursor
        node { refId userId amount type extra createdAt updatedAt }
      }
    }
  }
}
"""

# `type` enum values CONFIRMED against real account data 2026-08-02 (one entry each,
# sampled from a mixed page -- NOT exhaustive). PixAI's own filter dropdown offers ~25
# distinct labels across 5 categories (Credits Spending / Purchased Credits / Earned
# Rewards / Grants & Refunds / Special Rewards); only these four have a confirmed enum so
# far. An unmapped type still comes through list_credit_log() (label falls back to the raw
# enum string) -- this dict is a display nicety, not a gate.
CREDIT_LOG_REASONS = {
    "task_cost": "Generation Task",
    "daily": "Daily Claim",
    "event_gift": "Event Gift",
    "extra_package": "Extra Package",
}


def list_credit_log(session, last=50, before=None):
    """Read the account's full credit transaction ledger via ad-hoc GraphQL
    `user(id).quotaLogs` -- every credit gain AND loss (purchases, daily claims, event
    gifts, generation spend, refunds, ...), not just generation cost. Distinct from
    list_kaisuuken_logs()/list_extra_package_boosts(), which are their own narrower REST
    endpoints for card/coupon-specific history.

    Each row: {ref_id, amount, type, label, extra, created_at, updated_at}. `amount` is
    signed (negative = spend, positive = gain). `type` is the raw enum (see
    CREDIT_LOG_REASONS for the ones confirmed so far); `label` is the friendly name when
    known, else the raw enum. `extra` is an opaque per-type payload -- e.g. the coupon-boost
    "🎫 +15%" reason tag seen on an extra_package row in the site's own UI must live in
    here, but no populated sample was captured to confirm its structure, so it is passed
    through raw rather than parsed.

    Backward-paginated (last/before over hasPreviousPage/startCursor), matching this
    codebase's OWN established connection style for history listings (see
    page_variables()) -- the opposite direction from kaisuuken/coupons' forward
    first/after. Pass a previous call's `next_cursor` as `before` to page further into the
    past. There is no type filter: the `me` connection takes no such argument. Read-only;
    fails soft on error, matching every other reader in this module."""
    from moonglade.backup import gql_adhoc, PixAIError
    try:
        variables = {"last": int(last)}
        if before:
            variables["before"] = str(before)
        data = gql_adhoc(session, _QUOTA_LOG_QUERY, variables) or {}
    except (PixAIError, requests.RequestException, ValueError):
        return {"entries": [], "has_more": False, "next_cursor": None}
    quota_logs = (data.get("me") or {}).get("quotaLogs") or {}
    edges = quota_logs.get("edges")
    if edges is None:
        return {"entries": [], "has_more": False, "next_cursor": None}
    page = quota_logs.get("pageInfo") or {}
    entries = []
    for e in edges:
        n = e.get("node") or {}
        t = n.get("type") or ""
        entries.append({
            "ref_id": n.get("refId") or "",
            "amount": n.get("amount"),
            "type": t,
            "label": CREDIT_LOG_REASONS.get(t, t),
            "extra": n.get("extra"),
            "created_at": n.get("createdAt") or "",
            "updated_at": n.get("updatedAt") or "",
        })
    return {"entries": entries, "has_more": bool(page.get("hasPreviousPage")),
            "next_cursor": page.get("startCursor")}


def _target_model_id(parameters):
    """The model id a generation targets, wherever it lives: top-level `modelId` for
    plain gen + video, or `chat.modelId` for an instruct edit. Empty string if none."""
    if not isinstance(parameters, dict):
        return ""
    return str(parameters.get("modelId")
               or (parameters.get("chat") or {}).get("modelId") or "").strip()


# The /kaisuuken/check protocol version the site sends. 1 (or omitted) = single-ticket-only
# matcher; 2 = multi-ticket, returns consumeAmount. Named so a future bump is one edit.
_KAISUUKEN_CHECK_VERSION = 2


def match_kaisuuken(session, parameters, enrich=False, raise_on_error=False, *,
                    training_base_model_id=""):
    """POST /v2/kaisuuken/check (protocol version 2, see _KAISUUKEN_CHECK_VERSION) with a
    generation's `parameters` and return the best matching TICKET as
      {id, expiresAt, templateId, total, consumeAmount, covered, balance_unknown, name?}
    -- or None when no card matches. `total` = tickets HELD on that template (int, or None
    when the balance could not be read); `consumeAmount` = tickets this job COSTS (>=1);
    `covered` = the ONE coverage verdict every caller reads via card_covers(); `balance_unknown`
    tells a not-covered result apart from a genuinely short one so surfaces word it honestly.
    Selection is coverage-first, then model preference (enrich), then nearest expiry.
    READ-ONLY: this only *checks*; the card is consumed later, when the task is submitted with
    the returned id attached. Fails soft (returns None) by default -- fine for every
    read-only/preview/display caller, where a glitched check should not block the UI.

    `raise_on_error=True` re-raises instead of swallowing the failure into None. The one
    caller that needs this is `_apply_kaisuuken`'s spend-time check: there, a transient
    check failure and "genuinely no card matches" must NOT collapse into the same outcome,
    because that outcome is "proceed and spend real credits."

    `enrich=True` cross-references /kaisuuken/summary to (a) PREFER the card locked to this
    generation's own model when more than one template is eligible -- so an Edit gen spends
    an Edit card, not a same-expiry Reference card that merely also matched -- and (b) attach
    the card's human `name` for honest UI ("Edit Pro Only covers this", not a guess). The
    default (False) keeps the original single-call behavior for every existing caller.

    `training_base_model_id` switches the body to PixAI's TRAINING check (the site's
    useKaisuukenMatch, owner ruling 4, 2026-09-26): {type: "training-task", baseModelId:
    <the base VERSION id>, version: 2}, with no `parameters` at all. The answer is read with
    exactly the same rules. match_training_kaisuuken is the named way in."""
    from moonglade.backup import PixAIError, _rest_post
    training_base = str(training_base_model_id or "").strip()
    if not parameters and not training_base:
        return None
    if training_base:
        body = {"type": "training-task", "baseModelId": training_base,
                "version": _KAISUUKEN_CHECK_VERSION}
    else:
        body = {"type": "generation-task", "parameters": parameters,
                "version": _KAISUUKEN_CHECK_VERSION}
    try:
        # `version: 2` is load-bearing (issue #15, live-verified 2026-08-16). Without it PixAI
        # runs its v1 matcher, which knows only single-ticket cards and answers `matches: []`
        # for any i2vPro duration >= 10 -- so every >5s video went out card-less at full price
        # for as long as this app existed. v2 (the site's own useKaisuukenMatch shape) returns
        # the multi-ticket match plus `consumeAmount` = tickets this job COSTS. NOTE the server
        # does NOT filter by balance: a 15s job comes back matched even when held < needed, so
        # coverage is decided HERE (see `covered` below), the one place every caller reads it.
        data = _rest_post(session, "/kaisuuken/check", body) or {}
    except (PixAIError, ValueError):
        if raise_on_error:
            raise
        return None
    matches = data.get("matches") or []
    if not matches:
        return None
    by_tid = {c.get("template_id"): c for c in list_kaisuukens(session)} if enrich else {}
    # Per-template need/held/covered, computed ONCE per template (not re-derived per ticket
    # inside the expiry loop) and parsed defensively: a null/0/"2" consumeAmount must never
    # collapse into "costs nothing" (0 -> always covered) or a TypeError inside the spend
    # path. Absent consumeAmount is the v1 semantic: one job, one ticket.
    #
    # `held` comes from the match's OWN `total`, else (when enriched) the summary count for
    # that template, else None = UNKNOWN. It deliberately does NOT fall back to the response's
    # top-level `total`: that scalar is the SUM across all matched templates (the repo's own
    # _TWO_CARDS fixture: 17 + 5 = 22), so using it credited every template with the whole
    # pool, let a 5-held template read as covering a 6-ticket job, and -- because both then
    # landed in covered_pool -- let nearest-expiry pick the SHORT one over the 17-held one,
    # defeating the coverage-first ordering below (review 2026-08-16, reproduced).
    def _facts(mt):
        try:
            need = int(mt.get("consumeAmount") or 1)
        except (TypeError, ValueError):
            need = 1
        need = max(need, 1)
        held = None
        raw_held = mt.get("total")
        if raw_held is None and enrich:               # summary count as a second opinion
            raw_held = (by_tid.get(mt.get("templateId")) or {}).get("count")
        if raw_held is not None:
            try:
                held = int(raw_held)
            except (TypeError, ValueError):
                held = None
        # Unknown balance is a distinct state, not "short": for a 1-ticket job assume covered
        # (not attaching when actually covered loses real credits, and 1 ticket is the v1
        # world that always worked). For ANY multi-ticket job fail CLOSED -- the general rule,
        # not a video special-case, so a future multi-ticket non-video card gets the same
        # protection. Being wrong here costs the full clip price either way; fail-closed is
        # chosen over an unverified under-funded attach, and callers word it as UNKNOWN
        # ("couldn't read your balance"), never as "not enough" (which asserts an unread fact).
        unknown = held is None
        covered = (need <= 1) if unknown else (held >= need)
        return need, held, covered, unknown

    facts = {id(mt): _facts(mt) for mt in matches}
    # (A0) Coverage FIRST, then preference, then nearest expiry: a short template (2 held,
    # needs 3) must never shadow one that covers (9 held) just because it expires sooner --
    # the old order (nearest-expiry across the whole pool) did exactly that. If NO template
    # covers, fall back to the full pool so the honest short message can still name a card.
    covered_pool = [mt for mt in matches if facts[id(mt)][2]]
    pool = covered_pool or matches
    # (A) When several cards are eligible, prefer the one whose model IS this generation's
    # model; fall back to the full set if none match (or we didn't enrich).
    want = training_base or _target_model_id(parameters)
    if enrich and want and len(pool) > 1:
        preferred = [mt for mt in pool
                     if str((by_tid.get(mt.get("templateId")) or {}).get("model_version_id") or "") == want]
        if preferred:
            pool = preferred
    best = None
    for mt in pool:
        for k in (mt.get("kaisuukens") or []):
            kid = k.get("id")
            if not kid:
                continue
            # ISO8601 sorts chronologically; treat never-expire (null) as far future.
            exp = k.get("expiresAt") or "9999-12-31"
            if best is None or exp < best["_exp"]:
                need, held, covered, unknown = facts[id(mt)]
                best = {"id": kid, "expiresAt": k.get("expiresAt"),
                        "templateId": mt.get("templateId"), "total": held,
                        "consumeAmount": need, "covered": covered,
                        "balance_unknown": unknown,
                        "_exp": exp}
    if best:
        best.pop("_exp", None)
        if enrich:                                     # (B) name the card for honest UI
            best["name"] = (by_tid.get(best["templateId"]) or {}).get("name")
    return best


def card_covers(best):
    """THE coverage predicate every caller reads -- CLI preview, _apply_kaisuuken, /api/price.
    True iff a card matched AND it covers the whole job (held >= consumeAmount). Defaults to
    covered when the result predates the field (older test stubs / v1 responses), which is the
    v1 one-job-one-ticket semantic. One home so the three surfaces can never disagree -- the
    CLI preview said FREE while the apply path charged full price precisely because each
    derived 'free' on its own (issue #15)."""
    return bool(best) and bool(best.get("covered", True))


def _card_uses_note(best):
    """The ONE 'uses N of H cards; ' phrase for a COVERED multi-ticket job (empty string for a
    1-ticket job, so an ordinary image reads 'covers this' on every surface exactly as before).
    Shared by the CLI preview and the spend log so they can't drift (they did)."""
    b = best or {}
    try:
        need = int(b.get("consumeAmount") or 1)
    except (TypeError, ValueError):
        need = 1
    if need <= 1:
        return ""
    held = b.get("total")
    return "uses {} of {} cards; ".format(need, held if held is not None else "?")


def card_short_note(best, cost=None):
    """The one honest sentence for the NOT-COVERED-but-matched case. Wording is deliberate:
    nothing is attached and the FULL price is charged, so it must never read as partial
    application ('covers 2 of 3, the rest costs N' was rejected in review for exactly that).
    Two sub-cases, told apart honestly (review 2026-08-16):
      SHORT   -- the balance was read and it is < needed: "you hold 2 of the 3 ... not enough".
      UNKNOWN -- the balance could NOT be read (no per-template total, no summary count) and the
                 job needs >1 ticket, so we fail closed. This must NOT say "not enough" -- that
                 asserts a fact nobody read; a user holding 9 tickets would be told they hold
                 too few. It says the balance couldn't be read and no card will be attached.
    `cost` = the full credit price if known."""
    b = best or {}
    need = int(b.get("consumeAmount") or 1)
    held = b.get("total")
    name = b.get("name") or "card"
    tail = (" -- this costs the full ~{:,} credits".format(int(cost)) if cost is not None
            else " -- this costs the full credit price")
    if b.get("balance_unknown") or held is None:
        return ("couldn't read how many {} tickets you hold (this needs {}), so no card will "
                "be attached".format(name, need) + tail)
    return ("you hold {} of the {} {} tickets this needs -- not enough, so no card is used"
            .format(held, need, name) + tail)




# The spend-time free-card check came back 401: PixAI no longer accepts the sign-in this
# create rides, so the words depend on WHICH sign-in that was (_session_for_create: the
# website session when Mirror to PixAI is on, the API key otherwise). Both end with the raw
# error in parentheses, like the "Lost to the Void" message beside them.
_SIGNIN_REFUSED_MIRROR = (
    "PixAI no longer accepts this app's website sign-in, so nothing was submitted and "
    "nothing was spent. Sign in to pixai.art, click your Connect from PixAI bookmark on "
    "that tab (it is on the Mirror to PixAI tile in the Control Panel), and try again. "
    "({})")
_SIGNIN_REFUSED_API_KEY = (
    "PixAI no longer accepts this app's API key, so nothing was submitted and nothing was "
    "spent. Make a new key on PixAI and put it in config.json as PIXAI_API_KEY (the Setup "
    "page in the wiki shows where), then try again. ({})")


def _is_signin_refusal(err):
    """True when `err` is a REST answer of HTTP 401 (PixAIRestError.status). Read off the
    status the transport already carries, never by matching the message text."""
    from moonglade.backup import PixAIRestError
    return isinstance(err, PixAIRestError) and err.status == 401


def _apply_kaisuuken(session, params, args):
    """Attach a free-card ticket id (`kaisuukenId`) to `params` in place, mirroring the
    web client. Precedence: explicit --kaisuuken-id > --no-card (skip) > auto-match via
    /v2/kaisuuken/check. Returns the attached id ('' if none). The card is only consumed
    when the task is actually submitted; this just picks the id. Logs what it did.
    A card is attached ONLY when `card_covers(best)` -- a match that is SHORT (multi-ticket
    video, held < consumeAmount) attaches nothing, prints `card_short_note`, and spends the
    full price, exactly as the site does (owner ruling, issue #15).

    The auto-match check retries once on failure, then ABORTS (raises PixAIError) rather
    than falling through to "no card -> pay credits". match_kaisuuken's normal fail-soft
    contract is right for read-only/preview callers, but wrong here: this is the last
    check before real money moves, and a transient glitch is not the same fact as "no
    free card exists" -- treating them the same silently spends credits on a generation
    that may have just been shown as free. Aborting surfaces the problem instead of
    guessing with the user's money (audit: `fail-open`, 2026-07-21).

    An Unlimited Mode request (params carrying `lane`, from ANY road -- a CLI --params-json
    or a banked --dump-params shape included) never touches a card: no check runs and no id
    is attached, and a card asked for beside the lane is refused rather than dropped
    (SCOPE_2026-09-26_unlimited-mode §8.3)."""
    from moonglade.backup import PixAIError
    from moonglade.gen_road import is_lane_request, _UNLIMITED_NO_CARD
    explicit = (getattr(args, "kaisuuken_id", "") or "").strip()
    if is_lane_request(params):
        if explicit or params.get("kaisuukenId"):
            raise PixAIError(_UNLIMITED_NO_CARD)
        print("  Unlimited Mode: no free card is checked or attached.")
        return ""
    if explicit:
        params["kaisuukenId"] = explicit
        print("  attaching your --kaisuuken-id (free card): {}".format(explicit))
        return explicit
    if getattr(args, "no_card", False):
        print("  --no-card: not using a free card (this WILL spend credits).")
        return ""
    # The auto-match /v2/kaisuuken/check must run under the SAME identity that will create.
    # A card reserved on the API-key session does not necessarily apply to a mirror (web-JWT)
    # create, so a generation previewed as FREE could be billed in real credits (review F2/F8).
    # _session_for_create is a pass-through when the mirror is off, and refuses (raises) before
    # any spend when the mirror is on but unavailable (F5).
    session = _mirror._session_for_create(session)
    best = None
    check_err = None
    for attempt in range(2):
        try:
            best = match_kaisuuken(session, params, enrich=True, raise_on_error=True)
            check_err = None
            break
        except (PixAIError, ValueError) as e:
            check_err = e
            # A 401 is PixAI refusing the sign-in itself: waiting and asking again cannot
            # change that answer, so it is not retried (no second call, no sleep). The status
            # rides on the PixAIRestError that _rest_error built, through match_kaisuuken's
            # re-raise, so it is read from there and never from the message text.
            if _is_signin_refusal(e):
                break
            if attempt == 0:
                time.sleep(1.5)
    if check_err is not None:
        if _is_signin_refusal(check_err):
            raise PixAIError((_SIGNIN_REFUSED_MIRROR if _mirror.mirror_enabled()
                              else _SIGNIN_REFUSED_API_KEY).format(check_err))
        # On-theme wording: mirrors the "job lost"
        # message PixAI's own site shows on a similar random failure, rather than a raw
        # technical error -- still refuses to guess and silently spend credits, just
        # says so in the app's own voice instead of engineer-speak.
        raise PixAIError(
            "Lost to the Void -- the free-card check didn't come back before submitting, "
            "so nothing was spent. Wait a moment and try again. ({})".format(check_err))
    if best and best.get("id") and card_covers(best):
        # ONE singular kaisuukenId, even for a multi-ticket job (site-verified): the server
        # debits consumeAmount tickets off that one template itself. Never a list.
        params["kaisuukenId"] = best["id"]
        print("  free card matches ({}) -> attaching it; {}this costs 0 credits "
              "(card expires {}).".format(best.get("name") or "card", _card_uses_note(best),
                                          (best.get("expiresAt") or "never")[:10]))
        return best["id"]
    if best and best.get("id"):
        # SHORT: matched, but held < needed. Owner ruling (issue #15): SPEND, matching the
        # site -- attach nothing, say plainly that the FULL price is charged, then proceed.
        # No refusal here; the honesty is the obligation. The cost lookup is diagnostic only
        # -- it exists to put a number in the sentence -- so it is wrapped so that NOTHING it
        # can raise ever aborts the submit it describes (price_task fails soft too, but this
        # is the one place a cosmetic lookup sits inside the spend path, so it gets its own
        # belt; review 2026-08-16). A missing number just drops from the wording.
        try:
            cost = _pricing.price_task(session, params)
        except Exception:                                  # noqa: BLE001 -- diagnostic, never fatal
            cost = None
        print("  " + card_short_note(best, cost) + ".")
        return ""
    print("  no matching free card -> this will spend credits.")
    return ""


def _preview_card_note(args, params):
    """In a PREVIEW, tell the user the real credit cost and whether a free card covers it --
    read-only /v2/kaisuuken/check + /v2/task-price (no spend, no upload). Fails soft (stays
    silent) if offline or unauthenticated, so previews still work with no network."""
    from moonglade.backup import _make_session
    from moonglade.gen_road import is_lane_request
    def _fmt(n):
        return "~{:,} credits".format(n) if n is not None else "credits"
    if is_lane_request(params):
        # A lane request never touches a card, at quote or at submit (SCOPE_2026-09-26_
        # unlimited-mode §2) -- so no /v2/kaisuuken/check here either.
        print("Unlimited Mode request: no free card is checked or attached. PixAI runs it "
              "free on an active Unlimited Mode, or refuses it.")
        return
    if getattr(args, "no_card", False):
        try:
            session = _make_session(getattr(args, "token", None))
            price = _pricing.price_task(session, params)
        except Exception:
            price = None
        print("--no-card set: this WILL spend {} on --confirm even if a card matches.".format(_fmt(price)))
        return
    explicit = (getattr(args, "kaisuuken_id", "") or "").strip()
    if explicit:
        # An explicit id is FORCED: it is attached as given, with no coverage check on its
        # template (review 2026-08-16 -- this used to promise "-> 0 credits" unconditionally,
        # which for a multi-ticket clip on an under-funded template is a paid clip shown as
        # free). Say plainly what is and isn't guaranteed.
        print("A free card (--kaisuuken-id) will be attached on --confirm as given. Coverage "
              "is NOT checked for a forced id: if that card's template holds fewer tickets "
              "than this job needs, PixAI charges the full credit price (or refuses). Drop "
              "--kaisuuken-id to let the auto-match pick a card that covers.")
        return
    try:
        session = _make_session(getattr(args, "token", None))
        # enrich=True, same as _apply_kaisuuken: the preview must name the SAME template
        # the spend will pick (model preference only applies when enriched), or the two
        # could disagree about which card -- and whether it covers.
        best = match_kaisuuken(session, params, enrich=True)
        price = _pricing.price_task(session, params)
    except Exception:
        # Offline / no key: the preview is still valid, but a spend page must not go SILENT
        # about cost (the web badge's "couldn't verify" rule). This used to just return,
        # which -- once the stale hardcoded reference price above it was removed -- would
        # have left a video preview with no cost line at all.
        print("Couldn't verify the cost or free-card match right now (offline or no key) -- "
              "with --confirm this MAY spend credits.")
        return
    # Three honest branches off the ONE predicate (card_covers). Before issue #15 this said
    # FREE on any match -- with version:2 a short 15s clip now matches, and that would have
    # promised FREE right before --confirm spent the full price.
    if card_covers(best) and best.get("id"):
        saved = " (saves {})".format(_fmt(price)) if price else ""
        # "uses N of H cards" only when the job costs MORE than one ticket -- the same gate the
        # web badge applies, so a 1-ticket image reads the same everywhere ("covers this",
        # not "uses 1 of 16 cards"; review: CLI/badge wording drift).
        uses = _card_uses_note(best)
        print("FREE: {} covers this -- {}with --confirm it costs 0 credits{} "
              "(card expires {}).".format(best.get("name") or "a matching card", uses, saved,
                                          (best.get("expiresAt") or "never")[:10]))
    elif best and best.get("id"):
        print("NOT free -- " + card_short_note(best, price) + " with --confirm.")
    else:
        print("NO FREE CARD matches -- with --confirm this will cost {}.".format(_fmt(price)))
