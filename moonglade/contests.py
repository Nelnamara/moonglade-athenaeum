"""
moonglade/contests.py
=====================
PixAI's contests: the board read (`list_contests`, its paging, `_contest_title`,
`_contest_rule`, `_contest_rows`), `--contests` (`run_contests`), and the per-contest reads and
the entry (`contest_my_entries`, `contest_winners`, `contest_artworks`, `contest_enter`). Moved
verbatim out of moonglade/backup.py in the 3.22 split (phase 5).

The names it reads from the engine (the READ_ONLY gate `_check_read_only`, the `_rest_*`
delegates, _make_session, PixAIError) are imported from moonglade.backup inside each function
that uses them, at call time, so a test's patch of backup's binding still reaches them and
importing this module never imports the engine.
"""
import sys
import time



# --- Contests (community + official) --------------------------------------------
# PixAI's live contest board lives at REST `GET /v2/contest/list?page=N&pageSize=M`
# (NOT the GraphQL `contests` connection, which is a stale official-only archive).
# "Active" is the server-computed `runtimeStatus == "running"` -- no client date math.
# Read-only: browsing contests never spends. See ../moonglade-internal/private/APP_OPERATIONS_FULL.md.
_CONTEST_PAGE_SIZE = 50
# The contest board's page CEILING and pace (SCOPE_2026-09-26 E4). list_contests stops at the
# board's own `totalPage`; this ceiling only bounds a board that keeps growing -- it was a bare
# 6, and the 2026-09-26 board already answered totalPage 7 at 50 a page (330 contests), so the
# oldest page silently fell off. Pages are read 0.35 s apart, the contest sweep's own pace
# (moonglade.contest_sync._CONTEST_SYNC_PAUSE): the board is a public read and CLAUDE.md asks for
# paced requests.
_CONTEST_MAX_PAGES = 100   # 3.22: 5,000 rows, about two years at the current rate
_CONTEST_PAGE_PAUSE = 0.35


def _contest_title(t):
    """Contest title/description come as {en, zh, ja, ko, ...} (or occasionally a bare
    string). Prefer English, fall back to the first non-empty value."""
    if isinstance(t, dict):
        return t.get("en") or next((v for v in t.values() if v), "") or ""
    return t or ""


def _contest_rule(rule):
    """One contest rule, with every `*_ids` list turned into strings. A 19-digit id that
    arrives as a bare JSON number would be ROUNDED by the browser's JSON.parse above 2^53
    and link the wrong recipe or model; str() here keeps every digit (null entries dropped)."""
    out = dict(rule)
    for k, v in rule.items():
        if isinstance(k, str) and k.endswith("_ids") and isinstance(v, list):
            out[k] = [str(i) for i in v if i is not None]
    return out


def _contest_row(r):
    """One raw board row -> the normalized dict every consumer reads. The mapper is the same
    one list_contests always had; the only addition is that a row carrying `descriptionForApp`
    and no `description` (a byte-identical copy of it upstream) reads the former."""
    status = (r.get("runtimeStatus") or "").lower()
    mid = str(r.get("mediaId") or "")
    slug = r.get("slug") or ""
    return {
        "id": str(r.get("id") or ""),
        "title": _contest_title(r.get("title")),
        "slug": slug,
        "type": (r.get("type") or "").lower(),          # 'official' | 'community'
        "status": status,                                # 'running' | 'ended'
        "active": status == "running",
        "vote_type": r.get("voteType") or "",            # creator_pick | user_vote
        "prize_amount": int(r.get("prizeAmount") or 0),
        "prize_distribution": [p for p in (r.get("prizeDistribution") or [])
                               if isinstance(p, dict)],
        "cover_url": ("https://api.pixai.art/v1/media/%s/thumbnail" % mid) if mid else "",
        "start_at": r.get("startAt") or "",
        "end_at": r.get("endAt") or "",
        "result_at": r.get("resultAt") or "",
        "url": ("https://pixai.art/en/contest/%s" % slug) if slug else "",
        # WHOLE, never truncated. It used to be sliced to 600 chars, which was
        # safe only while nothing rendered it. The brief is MARKDOWN upstream, so
        # a mid-token cut can sever a **bold** run or a [link](url) and leave the
        # renderer holding half a construct -- and the detail view now renders it.
        "description": _contest_title(r.get("description") or r.get("descriptionForApp")),
        # The entry requirements, straight through (contest detail view):
        #   rules  -- [{type: 'required_model_ids', model_ids: [...]} | {type: 'required_lora_ids', lora_ids: [...]} | {type: 'required_recipe_ids', recipe_ids: [...]}]; [] = no restriction
        #   tack_name -- the tag an entry must carry (PixAI calls a tag a "tack")
        #   desc_url / result_url -- the contest's own rules + results documents,
        #     both frequently absent (null upstream -> "" here)
        "rules": [_contest_rule(x) for x in (r.get("rules") or [])
                  if isinstance(x, dict)],
        "tack_name": r.get("proposedTackName") or "",
        "desc_url": r.get("descUrl") or "",
        "result_url": r.get("resultUrl") or "",
        # Settlement (L3, PROBE 2026-09-29): `rewardStatus` reads "distributed" once
        # the prizes have been paid out, which is the signal the win check uses to stop
        # re-reading a contest early. Absent upstream -> "" (unknown, never a guess).
        "reward_status": str(r.get("rewardStatus") or "").lower(),
        "reward_distributed_at": r.get("rewardDistributedAt") or "",
    }


# --- The settled-row cache (3.22, design 6) ----------------------------------------
# A contest that has ended and paid out cannot change, so re-reading it every walk is waste:
# the whole board is about 2.8 MB on the wire. Mapped rows are kept in
# local/cache/contest_board.json (written atomically, only ever rebuildable), and ONLY a
# settled row is ever served from it. The route takes no field selection, so the fix is to stop
# re-reading what cannot change, and only that.
CONTEST_CACHE_NAME = "contest_board.json"
CONTEST_FULL_WALK_S = 24 * 3600        # a full walk at least this often (and on Refresh)
CONTEST_RESEEN_S = 7 * 24 * 3600       # a cached row not seen for this long is re-read
_CONTEST_CACHE_VERSION = 1


def contest_cache_path():
    """local/cache/contest_board.json, through moonglade.paths."""
    from moonglade import paths as _paths
    return _paths.cache_dir() / CONTEST_CACHE_NAME


def _raw_settled(r):
    """Settled = ended with `rewardStatus` "distributed", or `lifecycleStatus` "cancelled".
    "pending_distribute" (seen by probe P6) is unsettled."""
    if str(r.get("lifecycleStatus") or "").lower() == "cancelled":
        return True
    return (str(r.get("runtimeStatus") or "").lower() == "ended"
            and str(r.get("rewardStatus") or "").lower() == "distributed")


def _load_contest_cache(path):
    """The cache dict, or None when absent, unreadable or from another version."""
    import json
    try:
        with open(path, "r", encoding="utf-8") as f:
            c = json.load(f)
        if (isinstance(c, dict) and c.get("v") == _CONTEST_CACHE_VERSION
                and isinstance(c.get("rows"), dict)):
            return c
    except (OSError, ValueError):
        pass
    return None


def _save_contest_cache(path, cache):
    """Atomic: a same-directory temp file, then os.replace, so a reader (or a crash) sees the
    whole old file or the whole new one. A failed write is logged and never fails the read."""
    import json
    import os
    try:
        os.makedirs(os.path.dirname(str(path)), exist_ok=True)
        tmp = "{}.tmp-{}".format(path, os.getpid())
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, separators=(",", ":"))
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:            # Windows: a scanner can hold the target a moment
                if attempt == 4:
                    raise
                time.sleep(0.05 * (2 ** attempt))
    except Exception as e:                     # noqa: BLE001 -- a cache write must not fail the read
        from moonglade import logs as moonglade_logging
        moonglade_logging.get_logger().warning(
            "contest board: could not write the cache (%s: %s)", type(e).__name__, str(e)[:120])


def _board_page(session, page):
    from moonglade.backup import _rest_get
    return _rest_get(session, "/contest/list",
                     params={"page": page, "pageSize": _CONTEST_PAGE_SIZE}) or {}


def _walk_all(session, max_pages, meta):
    """The full walk: page 1 to the board's own `totalPage`, never past `max_pages`, paced.
    Returns [(page, raw_row), ...] in board order and fills `meta`."""
    reads = []
    page = 1
    while True:
        if page > 1:
            time.sleep(_CONTEST_PAGE_PAUSE)
        d = _board_page(session, page)
        reads.extend((page, r) for r in (d.get("data") or []))
        total_page = int(d.get("totalPage") or 1)
        total_count = int(d.get("totalCount") or 0)
        if page >= total_page:
            if meta is not None:
                meta.update(pages_read=page, total_page=total_page, total_count=total_count,
                            limit=page * _CONTEST_PAGE_SIZE, truncated=False)
            break
        if page >= max_pages:
            if meta is not None:
                meta.update(pages_read=page, total_page=total_page, total_count=total_count,
                            limit=page * _CONTEST_PAGE_SIZE, truncated=True)
            from moonglade import logs as moonglade_logging
            moonglade_logging.get_logger().warning(
                "contest board: stopped at the %d-page ceiling; the board reports %d pages, "
                "so its oldest %d page(s) were not read", max_pages, total_page,
                total_page - page)
            break
        page += 1
    return reads


def _walk_newest_first(session, cache, max_pages, meta, now):
    """The incremental walk (design 6 item 2). Reads newest-first and may skip ahead once a
    page is all settled, cached and unchanged, using the cache's page map -- a HINT, never a
    proof: new contests shift rows down. Before it ends, every unsettled cached id must have
    been seen in THIS walk's own reads, and it keeps reading the next unread pages until it
    is. An id still missing once every page is read is gone upstream and drops off the board.
    Returns [(page, raw_row), ...] for the pages it actually read."""
    entries = cache["rows"]
    unsettled = {i for i, e in entries.items() if not e.get("settled")}
    stale = {i for i, e in entries.items() if now - float(e.get("seen_at") or 0) >= CONTEST_RESEEN_S}
    page_map = {}
    for i, e in entries.items():
        page_map.setdefault(int(e.get("page") or 0), set()).add(i)
    must_read = {p for p, ids in page_map.items() if ids & (unsettled | stale)}
    known_max = max(page_map) if page_map else 0
    read = {}                                   # page -> raw rows
    seen = set()
    state = {"total": 1, "count": 0, "first": True}

    def fetch(p):
        if not state["first"]:
            time.sleep(_CONTEST_PAGE_PAUSE)
        state["first"] = False
        d = _board_page(session, p)
        state["total"] = int(d.get("totalPage") or 1)
        state["count"] = int(d.get("totalCount") or 0)
        rows = d.get("data") or []
        read[p] = rows
        seen.update(str(r.get("id") or "") for r in rows)
        return rows

    def clean(rows):
        for r in rows:
            e = entries.get(str(r.get("id") or ""))
            if not (e and e.get("settled") and _raw_settled(r)
                    and e.get("updated_at") == (r.get("updatedAt") or "")):
                return False
        return bool(rows)

    p = 1
    while True:
        rows = fetch(p)
        limit = min(state["total"], max_pages)
        nxt = p + 1
        if clean(rows):
            # Every row here is settled and unchanged: jump to the next page the cache says
            # holds something that can still change (or that it has never mapped).
            cand = [q for q in range(p + 1, limit + 1) if q in must_read or q > known_max]
            nxt = cand[0] if cand else limit + 1
        if nxt > limit:
            break
        p = nxt
    limit = min(state["total"], max_pages)
    missing = unsettled - seen
    for q in range(1, limit + 1):
        if not missing:
            break
        if q in read:
            continue
        fetch(q)
        missing -= seen
    if meta is not None:
        meta.update(pages_read=len(read), total_page=state["total"],
                    total_count=state["count"], limit=limit * _CONTEST_PAGE_SIZE,
                    truncated=state["total"] > max_pages)
    if state["total"] > max_pages:
        from moonglade import logs as moonglade_logging
        moonglade_logging.get_logger().warning(
            "contest board: stopped at the %d-page ceiling; the board reports %d pages, "
            "so its oldest %d page(s) were not read", max_pages, state["total"],
            state["total"] - max_pages)
    return [(p, r) for p in sorted(read) for r in read[p]]


def _id_key(row):
    i = str(row.get("id") or "")
    return int(i) if i.isdigit() else -1


def list_contests(session, active_only=False, max_pages=_CONTEST_MAX_PAGES, meta=None,
                  cache_path=None, full=False):
    """Return the PixAI contest board as normalized dicts, newest-first. `active_only`
    keeps just the currently-running ones (runtimeStatus=='running'), filtered LOCALLY: the
    list route ignores `runtimeStatus`, and `/list/ongoing` is a capped rotating sample, not
    the running set (probe P6). Pages through /v2/contest/list until the board's own
    `totalPage`, never past `max_pages` (_CONTEST_MAX_PAGES), pausing _CONTEST_PAGE_PAUSE
    between pages; when the ceiling rather than `totalPage` ends the walk, the log says so.
    Read-only, no spend.

    With `cache_path` the settled-row cache is used: a FULL walk once a day and when `full`
    is True (the board's Refresh), the newest-first walk otherwise (see _walk_newest_first).
    Without it, every call is a full walk and nothing is written.

    `meta`, when given, is an out-dict the caller reads afterwards (the return value stays a
    plain list): pages_read, total_page, total_count, limit (rows the walk could read) and
    `truncated` -- True only when the ceiling, not the board's own `totalPage`, ended it."""
    now = time.time()
    cache = _load_contest_cache(cache_path) if cache_path else None
    do_full = (cache_path is None or full or cache is None
               or now - float(cache.get("full_at") or 0) >= CONTEST_FULL_WALK_S)
    if do_full:
        reads = _walk_all(session, max_pages, meta)
        base = {}
    else:
        reads = _walk_newest_first(session, cache, max_pages, meta, now)
        base = cache["rows"]
    fresh = [(p, r, _contest_row(r)) for p, r in reads]
    if cache_path:
        rows = {}
        for i, e in base.items():
            if e.get("settled"):               # an unsettled row is only ever a FRESH read
                rows[i] = e
        for p, r, m in fresh:
            rows[m["id"]] = {"row": m, "updated_at": r.get("updatedAt") or "", "page": p,
                             "seen_at": now, "settled": _raw_settled(r)}
        _save_contest_cache(cache_path, {
            "v": _CONTEST_CACHE_VERSION, "saved_at": now,
            "full_at": now if do_full else float(cache.get("full_at") or 0),
            "rows": rows})
        if do_full:
            out = [m for _p, _r, m in fresh]
        else:
            fresh_ids = {m["id"] for _p, _r, m in fresh}
            out = [m for _p, _r, m in fresh] + [
                e["row"] for i, e in rows.items() if i not in fresh_ids]
            out.sort(key=_id_key, reverse=True)
        if meta is not None:
            meta["mode"] = "full" if do_full else "newest-first"
    else:
        out = [m for _p, _r, m in fresh]
    if active_only:
        out = [m for m in out if m["active"]]
    return out


def run_contests(args):
    """CLI: list PixAI contests (default: only the currently-running ones). Read-only.
    --all-contests includes ended ones. Encourages community engagement -- see what's live."""
    from moonglade.backup import _make_session, PixAIError
    session = _make_session(getattr(args, "token", None))
    active_only = not getattr(args, "all_contests", False)
    try:
        contests = list_contests(session, active_only=active_only)
    except PixAIError as e:
        print("Could not fetch contests: {}".format(str(e)[:160]))
        return
    if not contests:
        print("No {}contests found.".format("active " if active_only else ""))
        return
    enc = (sys.stdout.encoding or "utf-8")

    def _safe(t):
        return str(t).encode(enc, "replace").decode(enc, "replace")
    official = [c for c in contests if c["type"] == "official"]
    community = [c for c in contests if c["type"] != "official"]
    label = "active" if active_only else "all"
    print("PixAI contests ({}): {} official, {} community\n".format(
        label, len(official), len(community)))
    for group, name in ((official, "OFFICIAL"), (community, "COMMUNITY")):
        if not group:
            continue
        print("-- {} --".format(name))
        for c in group:
            flag = "" if c["active"] else " (ended)"
            prize = "  {:,} cr".format(c["prize_amount"]) if c["prize_amount"] else ""
            print("  {}{}{}".format(_safe(c["title"])[:52], prize, flag))
            print("    {} -> {}   {}".format(
                (c["start_at"] or "")[:10], (c["end_at"] or "")[:10], c["url"]))
        print("")
    print("(Read-only. Enter a contest from the PixAI website.)")


def _contest_rows(payload):
    """Flatten one contest-artwork payload into a list of plain dicts.

    Two shapes are accepted on purpose. The sibling `/contest/list` answers with a
    `{data:[...]}` envelope, while the per-user / winners routes are documented as bare
    JSON arrays and only the array form was seen live -- so guessing one shape would put
    an unverified assumption between the caller and the data. A dict payload yields its
    `data` list, a list payload is itself, anything else yields nothing.

    Each row is reduced to its SCALAR fields: the four the app actually uses (`id`,
    `authorId`, `mediaId`, `title`) plus whatever else came flat -- a winner's rank field,
    whose upstream name is unverified, therefore rides along untouched rather than being
    guessed at by name. Nested envelopes (the echoed `contest{}` object) are dropped, except
    its `entry`: the placement (kept as one small dict, see below)."""
    if isinstance(payload, dict):
        rows = payload.get("data") or []
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        flat = {str(k): v for k, v in r.items()
                if v is None or isinstance(v, (str, int, float, bool))}
        # ONE exception to the scalars-only rule, and it is an identity question rather
        # than a tidiness one. An entry row can carry its artwork as a nested object
        # (`{"id": <entry id>, "artwork": {"id": <artwork id>}}`), and dropping that
        # leaves only the ENTRY id -- a different value from the artwork id every other
        # path keys on. The dedupe set is grow-only, so one real entry then lands under
        # two keys and counts twice, forever. Lift the artwork id out to the flat name
        # the rest of the app already reads.
        if not flat.get("artworkId"):
            art = r.get("artwork")
            if isinstance(art, dict) and art.get("id"):
                flat["artworkId"] = str(art["id"])
        # L3 (PROBE 2026-09-29): the echoed `contest{}` block is NOT noise on these rows -- its
        # nested `entry` carries the placement. `contest.entry = {rank, prizeAmount, source,
        # submittedAt}`: `rank` is the PRIZE TIER (1/2/3, shared by every winner in that tier,
        # null on a non-winner's entry), `prizeAmount` what that tier paid, `source` "manual"
        # for a hand-picked winner and "tack" for an ordinary entry. Dropping it (the old
        # scalars-only rule) is what made the app show list positions 1..65 and a prize of 0.
        # Kept ADDITIVELY, and only when upstream sent it, so a row without the block maps
        # exactly as it always did. `rank` stays an int or None -- a numeric string is NOT
        # coerced, because "is this an integer rank" is the win check's whole question.
        blk = r.get("contest")
        ent = blk.get("entry") if isinstance(blk, dict) else None
        if not isinstance(ent, dict):
            ent = r.get("entry") if isinstance(r.get("entry"), dict) else None
        if isinstance(ent, dict):
            rank = ent.get("rank")
            prize = ent.get("prizeAmount")
            flat["entry"] = {
                "rank": rank if (isinstance(rank, int) and not isinstance(rank, bool)) else None,
                "prizeAmount": prize if (isinstance(prize, (int, float))
                                         and not isinstance(prize, bool)) else 0,
                "source": ent.get("source") if isinstance(ent.get("source"), str) else "",
                "submittedAt": (ent.get("submittedAt")
                                if isinstance(ent.get("submittedAt"), str) else ""),
            }
        out.append(flat)
    return out


def contest_my_entries(session, slug, user_id):
    """One account's OWN entries in one contest, as plain dicts.

    `GET /v2/contest/{slug}/artwork/{userId}` -- the "have I entered, and how many times"
    read, without paging the contest's whole entry list. Read-only: browsing entries never
    spends and never changes the account, so no `_check_read_only` here.

    Raises PixAIError upward on a non-2xx (and ValueError on a malformed 200 body); every
    caller of this is a poll that fails soft at its own layer, which keeps the failure
    handling where the "what should a poll do about it" decision actually lives."""
    from moonglade.backup import _rest_get
    return _contest_rows(_rest_get(
        session, "/contest/%s/artwork/%s" % (slug, user_id)))


def contest_winners(session, slug):
    """The winners of one contest, as plain dicts. `GET /v2/contest/{slug}/winners`.

    Verified live: a still-running contest answers with an EMPTY JSON array rather than an
    error, and the list populates at the contest's `resultAt` -- so an empty result means
    "not decided yet", never "call failed". ONE unpaged list; each row is a winning artwork
    (`id` is the artwork id, `authorId` its author) and its `entry` is the placement:
    `entry.rank` is the prize TIER (1/2/3, shared by every winner in that tier) and
    `entry.prizeAmount` what the tier paid (PROBE 2026-09-29; see _contest_rows). Read-only,
    a GET and nothing else, no spend."""
    from moonglade.backup import _rest_get
    return _contest_rows(_rest_get(session, "/contest/%s/winners" % slug))


def contest_artworks(session, slug, page=1):
    """One page of a contest's PUBLIC entries -- everyone's, not just this account's.
    `GET /v2/contest/{slug}/artwork` with `{"page": N, "sort": "newest"}` (page size is
    the server's, ~20). Read-only; feeds the detail view's entries preview, where the
    full browse is a link-out to pixai.art rather than a paging UI here.

    Returns the envelope shape `{data, totalCount, page, totalPage}` with `data`
    normalized by _contest_rows. A bare-array answer is tolerated the same way the
    per-user route's is (only the sibling /contest/list envelope was verified live): the
    rows are the array and the counts fall back to what was actually returned, so a
    caller never reads an invented total. Raises PixAIError upward on a non-2xx."""
    from moonglade.backup import _rest_get
    d = _rest_get(session, "/contest/%s/artwork" % slug,
                  params={"page": int(page or 1), "sort": "newest"})
    rows = _contest_rows(d)
    env = d if isinstance(d, dict) else {}

    def _int(key, fallback):
        try:
            return int(env.get(key) or fallback)
        except (TypeError, ValueError):
            return fallback
    return {"data": rows, "totalCount": _int("totalCount", len(rows)),
            "page": _int("page", int(page or 1)), "totalPage": _int("totalPage", 1)}


def contest_enter(session, slug, artwork_id):
    """Enter one ALREADY-PUBLISHED artwork into a contest. **ACCOUNT-MUTATING.**

    This is account-visible in the strongest sense: it puts the artwork into a PUBLIC
    contest under the owner's name, where everyone can see it, and the contract exposes no
    un-enter route. So it is gated by `_check_read_only` before the network call fires,
    exactly like submit_generation / submit_fixer / delete_task / claim_reward, and it
    rides the single-attempt `_rest_post` with NO retry loop of its own -- a re-POST after
    a lost response would submit a second entry.

    `POST /v2/contest/{slug}/artwork` with `{"artworkId": ...}` -> the parsed response
    dict (`{"success": true}` upstream). Upstream refusals arrive as a PixAIError carrying
    the status and body: NOT_ELIGIBLE (e.g. the artwork was published before the contest
    opened), UNAUTHORIZED, INVALID_INPUT.

    THE ENTRY FEE IS UNMEASURED. The contract also declares an INSUFFICIENT_CREDITS error,
    so entering MAY cost credits -- but no entry has ever been submitted from here to find
    out, and the capture scope deliberately stopped short of firing one. Callers must
    present the cost as UNKNOWN; do not tell a user this is free."""
    from moonglade.backup import _check_read_only, _rest_post
    _check_read_only("enter a PixAI contest")
    return _rest_post(session, "/contest/%s/artwork" % slug,
                      {"artworkId": str(artwork_id)})
