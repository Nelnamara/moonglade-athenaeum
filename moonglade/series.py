"""
moonglade/series.py
===================
The dial-in series engine (issue #34): clusters a run of tasks into the session that produced
them. Moved verbatim out of moonglade/gallery.py in the 3.21.0 split (phase 1).

Imports the gallery only inside the functions that need its catalog.
"""
import re
import sqlite3
import threading
import time


# ---------------------------------------------------------------------------
# The dial-in series engine (issue #34) -- clustering a run of tasks into the
# session that produced them: same model, gap <= 8h, clause-Jaccard >= 0.5,
# chained over tasks in id order. The rule is OWNER-VALIDATED on the Series
# Review Board (10/10 samples accurate, near-misses correctly apart), so this
# code's job is to REPLICATE the validated JS exactly, not to improve on it.
# Series are computed, never stored: the catalog stays the single source of
# truth and a recompute after any edit/delete is honest about what exists.
# ---------------------------------------------------------------------------

def _series_text(row):
    """The EXACT text the owner validated the clustering rule on (#34, engine
    requirement comment): the library API's `prompt` field, which is
    `(prompt_full or prompt_preview or "")[:1200]` (see /api/library's item
    builder). Same fallback order, same 1200-char cap -- Mio-era prose runs ~2k
    chars, and an uncapped read yields DIFFERENT clause sets than the validated
    board. Pinned by the >1200-char test in dev/tests/test_series_engine.py."""
    return (row["prompt_full"] or row["prompt_preview"] or "")[:1200]


def _series_clause_list(text):
    """Ordered, de-duplicated clause list for a prompt -- the exact tokenization
    the owner validated (#34): strip `<...>` tokens (lora/character markup is not
    prose), turn `.` `;` and newlines into commas, split on commas, trim,
    lowercase, keep only clauses longer than 3 chars. Order is prompt order --
    the delta differ uses it so "+ added clause" labels surface the clause the
    way the owner typed it, not alphabetically."""
    t = re.sub(r"<[^>]*>", "", str(text or ""))
    t = t.replace(".", ",").replace(";", ",").replace("\r", ",").replace("\n", ",")
    out, seen = [], set()
    for part in t.split(","):
        c = part.strip().lower()
        if len(c) > 3 and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _series_ts(created_at):
    """Epoch seconds for a stored created_at, or None. Same tolerance as the
    History feed's _history_ts (which lives inside create_app and can't be
    shared from module level): PixAI's 24-char `...T06:14:10.545Z`, the 20-char
    no-millis `...Z`, and the 19-char naive legacy rows -- all UTC (#34 review:
    timestamps are UTC ISO strings, hour math needs no zone care).

    TWO SHAPES ADDED 2026-09-03, because this now also measures CONTEST dates, which do
    not come from the same place catalog rows do:
      * DATE-ONLY ("2026-09-20") returned None, so a contest whose end date carried no
        time component read as having no date at all -- no countdown, and the sweep
        recency window silently skipped it;
      * a real UTC OFFSET was TRUNCATED and the time read as UTC, quietly wrong by up to
        a day either way. A deadline is the one thing on that surface that must not be
        approximately right."""
    from datetime import datetime, timedelta, timezone
    s = str(created_at or "").strip()
    if not s:
        return None
    if s[-1:] in ("Z", "z"):
        s = s[:-1]
    # A trailing offset, scanned backwards from the end and never past the "T" -- the
    # date's own hyphens are not offsets, and an offset only ever follows the time.
    off = timedelta(0)
    tpos = s.find("T")
    if tpos > 0:
        for i in range(len(s) - 1, tpos, -1):
            ch = s[i]
            if ch == "+" or ch == "-":
                tail = s[i + 1:].replace(":", "")
                if tail.isdigit() and len(tail) in (2, 4):
                    hh = int(tail[:2])
                    mm = int(tail[2:]) if len(tail) == 4 else 0
                    off = timedelta(hours=hh, minutes=mm)
                    if ch == "+":
                        off = -off       # +09:00 is AHEAD of UTC: subtract to reach UTC
                    s = s[:i]
                break
    try:
        base = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        try:                             # date-only: midnight UTC on that day
            base = datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
        return (base + off).timestamp()
    frac = s[19:]
    ms = 0.0
    if frac.startswith(".") and frac[1:].isdigit():
        ms = float("0" + frac)
    return (base + off).timestamp() + ms


# Ported from gallery/src/gen/headline.js's SCAFFOLD set -- KEEP THE TWO IN SYNC
# (that file is the origin; a tag added there belongs here too). Used only to
# skip non-descriptive clauses when a series has no character token to name
# itself after (#34: "else the head descriptive clause -- the headline excerpt
# rule already in gen/headline.js").
_SERIES_SCAFFOLD = frozenset({
    "masterpiece", "best quality", "amazing quality", "high quality", "highres",
    "absurdres", "very awa", "newest", "1girl", "1boy", "2girls", "2boys", "solo",
    "looking at viewer", "detailed background", "ultra detailed", "highly detailed",
    "8k", "4k", "score_9", "score_8_up", "score_7_up", "rating_safe",
    "rating_explicit", "rating_questionable",
})


def _series_is_scaffold(clause):
    """Python twin of headline.js's isScaffold(), over an already-lowercased
    clause: the SCAFFOLD set, tag namespaces, leftover `<...>` tokens, pony
    scores/ratings, and weighted quality openers."""
    c = clause
    if c in _SERIES_SCAFFOLD:
        return True
    if re.match(r"^(artist|character|copyright|lora|source):", c):
        return True
    if re.match(r"^<[^>]*>$", c):
        return True
    if re.match(r"^score_\d", c) or re.match(r"^rating_", c):
        return True
    if re.match(r"^\(?(masterpiece|best quality)", c):
        return True
    return False


def _series_cap_first(s):
    """headline.js's capFirst: first character up, rest untouched."""
    return (s[:1].upper() + s[1:]) if s else s


def _series_title(text):
    """A series' display name, from the FIRST task's prompt (#34: 'character
    name when a character token resolves, else the head descriptive clause').
    Character sources, in order:
      * a clause starting `character:` (booru tag namespace);
      * a `<token>` in the ORIGINAL text -- captured BEFORE _series_clause_list
        strips them -- whose text is not a lora-weight form (`lora:...` /
        trailing `:0.8` weights are model plumbing, not a name).
    Normalization: drop the `character:` prefix, dashes to spaces, title-case
    the first word. Fallback: the first non-scaffold clause (the headline
    excerpt rule -- see _SERIES_SCAFFOLD). Everything trims to 40 chars; ''
    when the prompt has nothing descriptive to say."""
    raw = str(text or "")
    cand = ""
    for c in _series_clause_list(raw):
        if c.startswith("character:"):
            cand = c
            break
    if not cand:
        for tok in re.findall(r"<([^>]*)>", raw):
            t = tok.strip()
            if not t:
                continue
            if re.match(r"^(lora|lyco|hypernet)\b", t, re.IGNORECASE):
                continue
            if re.search(r":\d+(\.\d+)?$", t):
                continue
            cand = t
            break
    if cand:
        cand = re.sub(r"^character:\s*", "", cand, flags=re.IGNORECASE)
        cand = " ".join(cand.replace("-", " ").split())
        return _series_cap_first(cand)[:40]
    for c in _series_clause_list(raw):
        if not _series_is_scaffold(c):
            return _series_cap_first(c)[:40]
    return ""


def _series_delta_label(prev_task, cur_task):
    """The short step label for a NON-reroll member vs the previous task in its
    series (#34): added = clauses in cur not in prev, removed = prev not in cur
    (sets, so pure reorderings vanish); up to 2 added ('+ ...') then 1 removed
    ('− ...'), each clause trimmed to 34 chars, joined ' · ', whole
    label capped at ~80. Clause order is prompt order (see _series_clause_list)
    so the label reads the way the owner typed the change."""
    added = [c for c in cur_task["clause_list"] if c not in prev_task["clauses"]]
    removed = [c for c in prev_task["clause_list"] if c not in cur_task["clauses"]]
    parts = ["+ " + c[:34] for c in added[:2]]
    if removed:
        parts.append("− " + removed[0][:34])
    label = " · ".join(parts)
    if len(label) > 80:
        label = label[:79].rstrip() + "…"
    return label


def compute_series(db_path):
    """One linear pass applying the owner-validated dial-in rule (#34): over
    tasks in task_id order, a task JOINS the current series iff
        same model key  AND  gap <= 8h  AND  clause-Jaccard >= 0.5
    vs the PREVIOUS task. Returns (by_task, by_sid):
        by_task -- {task_id: (sid, v)} for every member of a multi-task series;
        by_sid  -- {sid: series struct} (the /api/series/<sid> payload).

    The decisions this encodes (design review 2026-08-23, folded into #34):
      * model key = model_id if non-empty else model_name -- display names
        collide ("Unknown or removed model") and renames drift; ids only ever
        SPLIT relative to the validated name-keyed clusters, never merge, so
        the owner's validation stands as the looser bound.
      * sid = the FIRST task's id -- deterministic, so `?series=<sid>` URLs and
        B's navigation survive a recompute. Series are computed, not stored.
      * missing/blank created_at => gap = infinity (starts a new series); a
        task AFTER one with no timestamp can't measure its gap either, so it
        starts fresh too. Jaccard of two EMPTY clause sets = 1 -- identical
        empties chain, matching the validated board.
      * only series with >= 2 tasks are kept: singletons (85% of tasks) cost
        nothing and produce no API rows.
      * member media_ids are ordered the way /api/siblings orders them (#33):
        by batch_index when EVERY member has one, else media_id -- so
        first_media_id is the task's true first output when the order is known.
      * v-numbers are 1-based positions and MAY renumber when a member is
        deleted -- honest (they describe what exists), explicitly UNLIKE #33's
        batch index (PixAI's permanent fact, never renumbered).
    """
    from moonglade.catalog import catalog
    with catalog(db_path) as con:
        rows = con.execute(
            "SELECT task_id, model_id, model_name, created_at, prompt_full,"
            " prompt_preview, media_id, batch_index FROM catalog"
            " WHERE task_id != '' ORDER BY task_id, media_id").fetchall()

    # Aggregate rows into tasks (first row's text/model/timestamp; every row a
    # member). batch_index rides along purely for the #33 member ordering.
    tasks, by_id = [], {}
    for r in rows:
        tid = str(r["task_id"])
        t = by_id.get(tid)
        if t is None:
            text = _series_text(r)
            clause_list = _series_clause_list(text)
            t = {
                "task_id": tid,
                "text": text,
                "clause_list": clause_list,
                "clauses": set(clause_list),
                "model_key": str(r["model_id"] or "") or str(r["model_name"] or ""),
                "model_label": str(r["model_name"] or "") or str(r["model_id"] or ""),
                "created_at": str(r["created_at"] or ""),
                "ts": _series_ts(r["created_at"]),
                "members": [],
            }
            by_id[tid] = t
            tasks.append(t)
        try:
            bi = int(str(r["batch_index"] or "").strip())
        except ValueError:
            bi = None
        t["members"].append((str(r["media_id"] or ""), bi))
    for t in tasks:
        if t["members"] and all(bi is not None for _, bi in t["members"]):
            t["members"].sort(key=lambda m: m[1])

    # The linear chain. `tasks` is already task_id-ascending (SQL ORDER BY).
    chains, cur, prev = [], None, None
    for t in tasks:
        joins = False
        if prev is not None and t["model_key"] == prev["model_key"]:
            if t["ts"] is None or prev["ts"] is None:
                gap = float("inf")
            else:
                gap = abs(t["ts"] - prev["ts"])
            if gap <= 8 * 3600.0:
                a, b = t["clauses"], prev["clauses"]
                union = len(a | b)
                jaccard = (len(a & b) / union) if union else 1.0
                joins = jaccard >= 0.5
        if joins:
            cur.append(t)
        else:
            cur = [t]
            chains.append(cur)
        prev = t

    by_task, by_sid = {}, {}
    for chain in chains:
        if len(chain) < 2:
            continue
        sid = chain[0]["task_id"]
        steps, count_images, prev_t = [], 0, None
        for i, t in enumerate(chain):
            v = i + 1
            reroll = prev_t is not None and t["clauses"] == prev_t["clauses"]
            if prev_t is None:
                label = "series start"
            elif reroll:
                label = "seed-only reroll"
            else:
                label = _series_delta_label(prev_t, t)
            n = len(t["members"])
            count_images += n
            steps.append({
                "task_id": t["task_id"], "v": v, "reroll": bool(reroll),
                "label": label,
                "first_media_id": t["members"][0][0] if t["members"] else "",
                "n": n,
            })
            by_task[t["task_id"]] = (sid, v)
            prev_t = t
        by_sid[sid] = {
            "sid": sid,
            "title": _series_title(chain[0]["text"]),
            "model": chain[0]["model_label"],
            "count_tasks": len(chain),
            "count_images": count_images,
            "span": [chain[0]["created_at"], chain[-1]["created_at"]],
            "steps": steps,
        }
    return by_task, by_sid


# The series cache (#34 review item 3). Keyed by db_path so tests' tmp catalogs
# never collide; each entry stores the cheap invalidation key, the compute time,
# and both indexes. The cheap key is `(COUNT(*), MAX(media_id))` -- journal_mode
# is `delete` (no WAL) so file mtime would also work, but the query is robust
# either way. The 30s floor exists because the live mirror WRITES DURING a sync:
# every saved page would otherwise trigger a full recompute (a linear pass over
# ~21k tasks) per gallery request. Staleness is bounded and honest -- the next
# request after the floor picks the new rows up.
_SERIES_CACHE = {}
_SERIES_CACHE_LOCK = threading.Lock()
_SERIES_RECOMPUTE_FLOOR_S = 30.0


def series_index(db_path):
    """The cached (by_task, by_sid) pair for a catalog. Recomputes only when the
    cheap key CHANGED and the last compute is at least _SERIES_RECOMPUTE_FLOOR_S
    old (both conditions -- see the cache note above). The lock covers the whole
    check-and-compute so concurrent requests during a sync can't stampede into
    parallel recomputes. Fails soft to empty indexes (no cache write) on a
    missing/broken catalog, like catalog_counts does."""
    from moonglade.catalog import catalog
    try:
        with catalog(db_path) as con:
            cheap = tuple(con.execute(
                "SELECT COUNT(*), MAX(media_id) FROM catalog").fetchone())
        now = time.time()
        with _SERIES_CACHE_LOCK:
            ent = _SERIES_CACHE.get(str(db_path))
            if ent is not None and (
                    ent["key"] == cheap
                    or (now - ent["computed_at"]) < _SERIES_RECOMPUTE_FLOOR_S):
                return ent["by_task"], ent["by_sid"]
            by_task, by_sid = compute_series(db_path)
            _SERIES_CACHE[str(db_path)] = {
                "key": cheap, "computed_at": time.time(),
                "by_task": by_task, "by_sid": by_sid,
            }
            return by_task, by_sid
    except sqlite3.Error:
        return {}, {}


# --- direction B: the grouped listing (series-as-units) --------------------------------
# Folding a filtered, sorted row set into dial-in series UNITS for /api/library
# ?group=series. Kept as module-level pure functions so the fold + cover choice are
# unit-testable without a request (dev/tests/test_series_grouping.py). The route supplies
# the rows (list_group_rows) and the series index (series_index); these decide only
# unit membership, order, and which surviving member is the cover.

def _series_cover_row(member_rows):
    """The cover among a series unit's SURVIVING members (#34 direction B review
    item 4): the newest by created_at, PREFERRING an image over a video poster --
    the newest image when the unit has any image at all, else the newest member
    overall. Deterministic on ties (created_at, then media_id)."""
    images = [m for m in member_rows if str(m.get("is_video") or "") != "1"]
    pool = images or member_rows
    return max(pool, key=lambda m: (_series_ts(m.get("created_at")) or float("-inf"),
                                    str(m.get("media_id") or "")))


def fold_series_units(rows_min, by_task):
    """Fold a filtered, sorted row list into grid UNITS for the grouped listing
    (#34 direction B). `rows_min` is the FULL filtered set in the active sort order
    (list_group_rows shape: dicts with media_id/task_id/created_at/is_video);
    `by_task` is series_index()[0] -- task_id -> (sid, v) for members of MULTI-task
    series only.

    A UNIT is a generation event shown as ONE card, keyed:
      * ("series", sid)   -- a MULTI-task dial-in series: every image of every task
                             in it folds into this one unit (up to 801 images);
      * ("task", task_id) -- any other task: its sibling images (a batch) collapse
                             to one unit -- one generation, one card, exactly the
                             count the grouped grid pages over (a lone image is just
                             a one-member task unit);
      * ("row", media_id) -- a row with a BLANK task_id: its own per-row unit, since
                             imports all share task_id '' and must never weld into
                             one giant unit (the series-engine / siblings rule).

    Returns (unit_order, members):
      * unit_order -- the unit KEYS in first-appearance order. A unit takes the
        POSITION of its FIRST matching member (first occurrence in the sorted set);
        every later member folds in rather than opening a new unit.
      * members -- {key: [surviving member rows]}, for cover selection and a cheap
        surviving-member count.

    The whole point is server-side grouping: a series can span many pages, so the
    fold must see the entire filtered set, not one page. `total` = len(unit_order)."""
    unit_order, members, seen = [], {}, set()
    for r in rows_min:
        # No media_id -> no card, exactly as the ungrouped path skips it. Guards
        # against blank-media_id rows welding into one ("row","") unit and against a
        # blank cover that rows_for_media_ids would later drop, leaving total > items.
        if not str(r.get("media_id") or "").strip():
            continue
        tid = str(r.get("task_id") or "")
        hit = by_task.get(tid) if tid else None
        if hit:
            key = ("series", hit[0])
        elif tid:
            key = ("task", tid)
        else:
            key = ("row", str(r.get("media_id") or ""))
        members.setdefault(key, []).append(r)
        if key not in seen:
            seen.add(key)
            unit_order.append(key)
    return unit_order, members
