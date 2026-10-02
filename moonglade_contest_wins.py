"""moonglade_contest_wins.py -- Session L, item L3: contest wins, VERIFIED.

A win is a fact PixAI states, never one the app takes on trust. This is the pure half of the
feature: what counts as a win, when the automatic check is due, how a pasted link is read and
how a miss is worded. It has no I/O, reads no clock (every function that needs "now" takes
it), and imports nothing from the app, so a test can walk a whole simulated fortnight without
sleeping a second. The store it edits (a plain dict inside telemetry.json), the network read,
the scheduler tick and the routes live in moonglade_gallery.py.

WHAT THE PROBE ESTABLISHED (moonglade-internal/probes/PROBE_2026-09-29_contest-results-l3.md,
and its read-only addendum): `GET /v2/contest/{slug}/winners` answers ONE unpaged list. Each
row is a winning artwork whose `contest.entry` is `{rank, prizeAmount, source, submittedAt}`;
`rank` is the prize TIER (1/2/3, shared by every winner in that tier), never a 1-to-65 place.
The list is EMPTY until the contest's result time, so an empty list means "not decided yet",
never "lost". A non-winning entry has `rank: null`. The contest's `rewardStatus` reads
"distributed" once the prizes are paid.

THE RULES, in one place:

  * A row is a WIN only when its artwork id is in the winners list, its `entry.rank` is an
    INTEGER, and its author is the account's. Nothing else is a win: not a name that looks
    right, not a rank that is a numeric string, not a row whose rank is null.
  * An EMPTY list is UNDECIDED. A list that is not empty and does not carry the entry is a
    miss, and only then.
  * The automatic check runs at the contest's result time, then once a day, for at most
    CHECK_WINDOW_DAYS after that. It stops early when the contest's rewardStatus is
    "distributed" AND the entries are settled (each one is either a verified win or plainly
    absent from a non-empty list). A failed read is retried an hour later, never in a loop.
  * The pasted-link fallback verifies by exactly the same rule; the link is kept as the
    RECEIPT. Only pixai.art's own pages are accepted.
  * Placement is worded as a TIER plus the prize ("Tier 2, 200,000 credits"), never as a
    numbered place.
  * A verified win is never retracted: the store only grows, which is what the metric (and
    the earn behind it) expects of it.
"""
import datetime as _dt
import re
from urllib.parse import unquote, urlparse

# ---- the mechanics ------------------------------------------------------------------------
CHECK_WINDOW_DAYS = 14                       # after the result time, the check gives up
CHECK_WINDOW_S = CHECK_WINDOW_DAYS * 86400.0
CHECK_EVERY_S = 86400.0                      # once a day
RETRY_AFTER_ERROR_S = 3600.0                 # a failed read waits an hour, once
MANUAL_COOLDOWN_S = 20.0                     # the Check button, per contest

PENDING, SETTLED, EXPIRED = "pending", "settled", "expired"

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_HOST_ROOT = "pixai.art"
MAX_RECEIPT = 300


def parse_ts(v):
    """An ISO instant (or a bare date) -> epoch seconds, or None. UTC when no zone is given."""
    if not v:
        return None
    try:
        s = str(v).strip().replace("Z", "+00:00")
        d = _dt.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.timestamp()


def int_rank(v):
    """The rank iff it is a real integer. A bool is not one and a numeric string is not one:
    "is this an integer rank" is the whole question, and it is answered literally."""
    return v if (isinstance(v, int) and not isinstance(v, bool)) else None


def _to_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ---- what counts as a win ------------------------------------------------------------------

def entry_of(row):
    """The row's placement block as `{rank, prize, source}`, or None when the row has none.
    Reads the mapped `entry` (moonglade_backup._contest_rows keeps `contest.entry` there);
    `rank` comes back as an int or None, never coerced."""
    ent = (row or {}).get("entry")
    if not isinstance(ent, dict):
        return None
    return {"rank": int_rank(ent.get("rank")), "prize": max(0, _to_int(ent.get("prizeAmount"))),
            "source": str(ent.get("source") or "")}


def row_artwork_id(row):
    """A winners row IS an artwork, so its `id` is the artwork id; an `artworkId` lifted from a
    nested artwork object (an entries row) is honoured first."""
    r = row or {}
    return str(r.get("artworkId") or r.get("id") or "")


def verify(rows, account_id, entry_ids=None):
    """Judge one winners list for one account.

    `entry_ids` is the set of artwork ids to look for (the account's own recorded entries in
    this contest, or the single id a pasted link names); None means "any artwork this account
    authored", which is the rule for a contest the app holds no entry record of.

    Returns {"decided", "wins", "outcome", "unsettled"}:
      decided   the list is not empty (an empty list is UNDECIDED, never "lost")
      wins      [{artwork_id, tier, prize, source}] for every entry that is a WIN
      outcome   "undecided" | "won" | "not_found" | "no_placement" | "not_yours"
                (the reason a miss is worded from; "won" when there is at least one win)
      unsettled True when an entry sits in the list without an integer rank: it is neither a
                win nor plainly absent, so the entries are not settled yet."""
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    if not rows:
        return {"decided": False, "wins": [], "outcome": "undecided", "unsettled": False}
    uid = str(account_id or "")
    want = None if entry_ids is None else {str(x) for x in entry_ids if str(x)}
    wins, no_place, not_mine = [], False, False
    for r in rows:
        aid = row_artwork_id(r)
        if not aid:
            continue
        author = str(r.get("authorId") or "")
        if want is None:
            if not (uid and author == uid):
                continue
        elif aid not in want:
            continue
        ent = entry_of(r)
        if ent is None or ent["rank"] is None:
            no_place = True
            continue
        if not (uid and author == uid):
            not_mine = True
            continue
        wins.append({"artwork_id": aid, "tier": ent["rank"], "prize": ent["prize"],
                     "source": ent["source"]})
    if wins:
        return {"decided": True, "wins": wins, "outcome": "won", "unsettled": no_place}
    if no_place:
        outcome = "no_placement"
    elif not_mine:
        outcome = "not_yours"
    else:
        outcome = "not_found"
    return {"decided": True, "wins": [], "outcome": outcome, "unsettled": no_place}


# ---- wording -------------------------------------------------------------------------------

def _num(n):
    return "{:,}".format(_to_int(n))


def tier_label(tier, prize=0):
    """"Tier 2, 200,000 credits" -- a TIER plus the prize, never a numbered place. The prize is
    left out when the list did not carry one."""
    t = _to_int(tier)
    base = "Tier %d" % t if t > 0 else "Tier"
    p = _to_int(prize)
    return "%s, %s credits" % (base, _num(p)) if p > 0 else base


def entry_short(artwork_id):
    """An artwork id trimmed for a sentence: "2061…302" (the design's own shape)."""
    s = str(artwork_id or "")
    return s if len(s) <= 9 else "%s…%s" % (s[:4], s[-3:])


MESSAGES = {
    "verified": "Verified.",
    "undecided": "That contest hasn't published its winners yet. The app re-checks daily.",
    "not_found": "Found the contest's winners, but not your entry {entry} among them. "
                 "Is it the right contest?",
    "no_placement": "Your entry {entry} is listed, but with no placement, so nothing was recorded.",
    "not_yours": "Entry {entry} is a winner, but it isn't from your account, so nothing was recorded.",
    "not_pixai": "Only PixAI's own pages count. Paste a link that starts with pixai.art.",
    "no_link": "Paste the link to your entry or to the contest.",
    "no_contest": "Couldn't tell which contest that link belongs to. Pick the contest, or paste "
                  "the contest's own link.",
    "failed": "Couldn't reach PixAI just now. Nothing was recorded; try again in a bit.",
    "cooldown": "Checked a moment ago. Give it a minute.",
}


def message(state, entry_id=""):
    """The sentence for one check state (see MESSAGES). `entry_id` fills {entry}."""
    txt = MESSAGES.get(state, MESSAGES["failed"])
    return txt.format(entry="#" + entry_short(entry_id) if entry_id else "")


# ---- the pasted link (E4, "Check") ---------------------------------------------------------

def clean_slug(text):
    """A contest slug typed or pasted on its own, or "" when it is not shaped like one. The
    shape is enforced because the slug goes into a request path."""
    s = str(text or "").strip()
    return s if _SLUG_RE.match(s) else ""


def parse_evidence(text):
    """Read a pasted link.

    Returns {ok, reason, receipt, artwork_id, slug}. `ok` is False with `reason` "no_link"
    (nothing pasted) or "not_pixai" (not a pixai.art page: the scheme may be left off, but the
    host must be pixai.art or one of its subdomains, with no credentials and no port).
    `artwork_id` is the id after an `/artwork/` segment and `slug` the one after a `/contest/`
    segment; either may be absent. `receipt` is the link normalised to scheme + host + path
    (no query, no fragment), which is what gets kept on the win."""
    raw = str(text or "").strip()
    out = {"ok": False, "reason": "no_link", "receipt": "", "artwork_id": "", "slug": ""}
    if not raw:
        return out
    probe = raw if "://" in raw else "https://" + raw
    try:
        u = urlparse(probe)
        host = (u.hostname or "").lower()
        port = u.port
    except ValueError:
        out["reason"] = "not_pixai"
        return out
    if (u.scheme not in ("http", "https") or u.username is not None or u.password is not None
            or port is not None
            or not (host == _HOST_ROOT or host.endswith("." + _HOST_ROOT))):
        out["reason"] = "not_pixai"
        return out
    segs = [unquote(s) for s in u.path.split("/") if s]
    for i, seg in enumerate(segs[:-1]):
        nxt = segs[i + 1]
        if seg == "artwork" and not out["artwork_id"] and _ID_RE.match(nxt):
            out["artwork_id"] = nxt
        elif seg == "contest" and not out["slug"] and _SLUG_RE.match(nxt):
            out["slug"] = nxt
    out.update(ok=True, reason="", receipt=("https://%s%s" % (host, u.path))[:MAX_RECEIPT])
    return out


def artwork_url(artwork_id):
    """The public page of an artwork (the receipt an AUTOMATIC win keeps)."""
    return "https://pixai.art/en/artwork/%s" % artwork_id if str(artwork_id or "") else ""


# ---- the entry record ----------------------------------------------------------------------

def entries_by_contest(keys):
    """The app's own entry record ("{contest_id}:{artwork_id}" keys) -> {contest_id: [artwork
    ids]}, in first-seen order and without repeats."""
    out = {}
    for k in (keys if isinstance(keys, (list, tuple, set)) else []):
        cid, _, aid = str(k).partition(":")
        if cid and aid and aid not in out.setdefault(cid, []):
            out[cid].append(aid)
    return out


def contest_of_artwork(entries, artwork_id):
    """The contest id the app recorded `artwork_id` as entered in, or "" (or "" too when the
    same artwork sits in more than one contest, which is not a question a link can answer)."""
    hits = [cid for cid, aids in (entries or {}).items() if str(artwork_id) in aids]
    return hits[0] if len(hits) == 1 else ""


def plan_manual(parsed, chosen_cid, chosen_slug, entries, slug_of, cid_of=None):
    """Decide what a Check press should ask PixAI. Pure: it returns the plan, the caller reads.

    `parsed` is parse_evidence's answer, `chosen_cid` / `chosen_slug` what the row picked (a
    contest from the account's own entries, or a slug typed in), `entries` the entry record
    (entries_by_contest), `slug_of(cid)` the app's own slug for a contest id ("" if unknown),
    `cid_of(slug)` the reverse (optional).

    The artwork's own read does NOT carry its contest (see the app's read functions), so the
    contest comes from, in order: the picked contest, a contest link's slug, a typed slug, the
    contest the app recorded the linked artwork in. Returns
      {"ok": True, "cid", "slug", "entry_ids"}   entry_ids is a list, or None (= any artwork
                                                 this account authored)
      {"ok": False, "reason"}"""
    cid = str(chosen_cid or "")
    slug = ""
    if cid:
        slug = slug_of(cid) or ""
    if not slug:
        slug = clean_slug(chosen_slug) or (parsed or {}).get("slug") or ""
    art = (parsed or {}).get("artwork_id") or ""
    if not slug and art:
        cid = contest_of_artwork(entries, art)
        slug = slug_of(cid) if cid else ""
    if not slug:
        return {"ok": False, "reason": "no_contest"}
    if not cid and cid_of is not None:
        cid = cid_of(slug) or ""
    if art:
        ids = [art]
    else:
        ids = list((entries or {}).get(cid) or []) or None
    return {"ok": True, "cid": cid, "slug": slug, "entry_ids": ids}


# ---- the schedule --------------------------------------------------------------------------

def new_state(slug, anchor, now, cid_known=True, legacy=False):
    """A fresh schedule row for one contest. `anchor` is the contest's result time (epoch), or
    None when the board did not know it -- then the first sight (`now`) stands in, so a contest
    that fell off the board cannot be re-read for ever. The first check is due AT the anchor."""
    a = anchor if anchor is not None else now
    st = {"slug": str(slug or ""), "anchor": float(a), "next_at": float(a), "last_at": 0.0,
          "checks": 0, "errors": 0, "status": PENDING, "decided": False,
          "legacy": bool(legacy), "reward": ""}
    expire(st, now)                       # a contest whose fourteen days are already over
    return st


def deadline(state):
    return float(state.get("anchor") or 0.0) + CHECK_WINDOW_S


def is_due(state, now):
    """Pending, its next check has arrived, and the fourteen days are not over."""
    if not isinstance(state, dict) or state.get("status") != PENDING:
        return False
    return float(state.get("next_at") or 0.0) <= now <= deadline(state)


def effective_status(state, now):
    """The row's status as of `now`: a pending row whose window is over reads EXPIRED even if
    nothing has written that down yet. "none" when there is no row."""
    if not isinstance(state, dict):
        return "none"
    if state.get("status") == PENDING and now > deadline(state):
        return EXPIRED
    return str(state.get("status") or PENDING)


def expire(state, now):
    """Mark a pending row EXPIRED once its window is over. Returns whether it changed."""
    if isinstance(state, dict) and state.get("status") == PENDING and now > deadline(state):
        state["status"] = EXPIRED
        return True
    return False


def after_read(state, now, result, reward_status):
    """Fold one SUCCESSFUL read of the winners list into the schedule row (edited in place).

    `result` is verify()'s answer, `reward_status` the contest's own ("distributed" ends it).
    The row settles when the prizes are distributed AND the entries are settled (the list is
    not empty and no entry sits in it without a rank). Otherwise the next check is a day away,
    and once the window is over the row expires."""
    state["last_at"] = float(now)
    state["checks"] = int(state.get("checks") or 0) + 1
    state["errors"] = 0
    state["decided"] = bool(result.get("decided"))
    state["reward"] = str(reward_status or "")
    settled = (state["decided"] and not result.get("unsettled")
               and str(reward_status or "").lower() == "distributed")
    if settled:
        state["status"] = SETTLED
        state["next_at"] = 0.0
        return state
    state["next_at"] = now + CHECK_EVERY_S
    expire_after = now + CHECK_EVERY_S > deadline(state)
    if expire_after:
        state["status"] = EXPIRED
    return state


def after_error(state, now):
    """Fold one FAILED read into the schedule row: the next try is an hour away, once. A row
    that has run out of window expires instead."""
    state["errors"] = int(state.get("errors") or 0) + 1
    state["next_at"] = now + RETRY_AFTER_ERROR_S
    expire(state, now + RETRY_AFTER_ERROR_S)
    return state


def refresh_state(state, contest_result_ts, slug, now):
    """Follow a contest whose result time moved, while nothing has been read yet. A row that
    has been checked keeps its anchor: the window is counted from the result time the checks
    ran against. Returns whether the row changed."""
    if not isinstance(state, dict) or state.get("status") != PENDING:
        return False
    changed = False
    if slug and state.get("slug") != slug:
        state["slug"] = slug
        changed = True
    if (contest_result_ts is not None and int(state.get("checks") or 0) == 0
            and not state.get("legacy")
            and abs(float(state.get("anchor") or 0.0) - contest_result_ts) > 1.0):
        state["anchor"] = float(contest_result_ts)
        state["next_at"] = float(contest_result_ts)
        changed = True
    return changed


def plan_pass(entries, legacy_wins, wins, checks, now):
    """What one automatic pass has to do, decided from the local record alone (no network).

    Returns {"seed": [cid...], "legacy": [cid...], "due": [cid...]}:
      seed    contests the account entered that have no schedule row yet
      legacy  contests an OLD sweep recorded as won (by author alone, with no artwork id and
              no tier) that are not verified: each gets ONE re-verification, its window
              counted from the first re-check rather than from a result time that may be long
              past. They are also in `seed` when they hold no row.
      due     contests whose row is due now
    A contest with nothing recorded as entered is never planned: there is nothing to verify."""
    entries = entries or {}
    wins = wins or {}
    checks = checks or {}
    seed, legacy, due = [], [], []
    for cid in entries:
        if cid in checks:
            continue
        seed.append(cid)
    for cid in (legacy_wins if isinstance(legacy_wins, (list, tuple, set)) else []):
        cid = str(cid)
        if cid and not wins.get(cid) and cid not in checks and cid not in legacy:
            legacy.append(cid)
    for cid, st in checks.items():
        if (cid in entries or st.get("legacy")) and is_due(st, now):
            due.append(cid)
    return {"seed": seed, "legacy": legacy, "due": due}


# ---- the record (what the metric counts) ---------------------------------------------------

def record_win(wins, cid, win, how, now, receipt=""):
    """Add one verified win to the record (`wins` is {contest_id: {artwork_id: record}}, edited
    in place). Returns True when this is NEW. A win already on the record is not replaced (the
    store only grows); a receipt it lacks is filled in."""
    per = wins.setdefault(str(cid), {})
    aid = str(win["artwork_id"])
    cur = per.get(aid)
    if isinstance(cur, dict):
        if receipt and not cur.get("receipt"):
            cur["receipt"] = receipt
        return False
    per[aid] = {"tier": int(win["tier"]), "prize": int(win.get("prize") or 0),
                "how": how, "at": float(now), "receipt": receipt or ""}
    return True


def verified_count(wins):
    """How many contests hold a verified win. THIS is what the contest-win metric counts,
    and it counts nothing else: a win an older sweep recorded without verification is not in
    this record, so it does not count until a check verifies it."""
    if not isinstance(wins, dict):
        return 0
    return sum(1 for per in wins.values() if isinstance(per, dict) and per)


def wins_for(wins, cid):
    """The verified wins of one contest, best tier first, as plain dicts with their labels."""
    per = (wins or {}).get(str(cid))
    out = []
    if isinstance(per, dict):
        for aid, r in per.items():
            if not isinstance(r, dict):
                continue
            out.append({"artwork_id": str(aid), "tier": _to_int(r.get("tier")),
                        "prize_amount": _to_int(r.get("prize")),
                        "label": tier_label(r.get("tier"), r.get("prize")),
                        "how": str(r.get("how") or ""), "verified_at": float(r.get("at") or 0.0),
                        "receipt_url": str(r.get("receipt") or "")})
    out.sort(key=lambda w: (w["tier"] or 99, w["artwork_id"]))
    return out
