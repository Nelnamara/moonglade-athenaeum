"""
moonglade/catalog_verbs.py
==========================
The catalog verbs: the questions the web routes, the engine and the MCP server ask of the
catalog, each named for what the domain calls it, taking a db_path and returning plain data
(task media, the delete targets and preview rows, My Art and its snapshots, lineage and
siblings, the history feed, backup coverage, the Loom's send record, the list and group reads,
find_image_file). Moved verbatim out of moonglade/gallery.py in the 3.22 split (phase 4).

It reads the catalog, the search and the curation layer through their modules; the one name it
reads from the trash panel's caps is imported inside the function that uses it, so importing
this module never imports the gallery.
"""
import math
import sqlite3
from pathlib import Path

from moonglade import catalog as _catalog
from moonglade import catalog_search as _catalog_search
from moonglade import curation as _curation
from moonglade import scan as _scan


# ---------------------------------------------------------------------------
# CATALOG VERBS -- the questions the web routes ask of the catalog
#
# Every one of these was raw SQL inside a route handler in create_app until
# 2026-08-23: eleven handlers and inner functions opened their own connection and
# wrote their own SELECT/UPDATE against `catalog`, which is exactly what
# architecture.md's "all I/O goes through helpers -- never raw SQL elsewhere" said
# did not happen. A verb is named for what the DOMAIN calls the question, takes a
# db_path, and returns PLAIN DATA (dicts, lists, ints) -- never a Row, never a live
# connection, never a Response. Shaping that data into a payload, and the URLs in
# it, stays at the handler; the SQL stays here.
#
# The SQL below is the SAME SQL those handlers held -- same columns, same WHERE,
# same ORDER BY, same LIMITs. This move was a relocation, not a rewrite.
# ---------------------------------------------------------------------------

def task_media(db_path, task_id):
    """Every catalog row belonging to one generation task: what the task produced,
    locally. Three callers needed exactly this and each had its own copy of the
    query -- the live-mirror's "a concurrent collect already finished, read the
    result back" path, /api/import-task's already-catalogued precheck, and the bulk
    delete's per-task local purge -- so they share one verb and one column list.
    Empty list for a task this library never downloaded.

    `cloud_deleted_at` rides along for the third caller: a row carrying it is one
    whose local copy is the only copy left anywhere, so the bulk purge has to know
    which rows to walk around before it takes the rest. `artwork_id` (2026-09-26) is the
    per-image delete dialog's catalog fallback for "is this generation published"."""
    with _catalog.catalog(db_path) as con:
        rows = con.execute(
            "SELECT media_id, is_video, filename, cloud_deleted_at, artwork_id "
            "FROM catalog WHERE task_id=?",
            (str(task_id),)).fetchall()
        return [dict(r) for r in rows]


def media_dims(db_path, media_ids):
    """{media_id: (width, height)} for the given ids this catalog knows a positive size for,
    as ints; an id with no row, or a blank / zero / unreadable size, is simply absent. The
    LoRA-training image rule (core.check_training_images) reads it and lists an absent id as
    not checked. Chunked for SQLite's bound-parameter cap."""
    ids = [str(m) for m in (media_ids or []) if str(m).strip()]
    out = {}
    with _catalog.catalog(db_path) as con:
        for i in range(0, len(ids), _TASK_CHUNK):
            chunk = ids[i:i + _TASK_CHUNK]
            for r in con.execute(
                    "SELECT media_id, width, height FROM catalog WHERE media_id IN ({})"
                    .format(",".join("?" * len(chunk))), chunk):
                try:
                    w, h = int(float(r["width"] or 0)), int(float(r["height"] or 0))
                except (TypeError, ValueError):
                    continue
                if w > 0 and h > 0:
                    out[str(r["media_id"])] = (w, h)
    return out


def published_delete_note(published, unchecked=False, tasks=1, unchecked_tasks=None):
    """The delete dialogs' sentence about published artwork (SCOPE_2026-09-26 E5), or "".

    PixAI's own contract says its task delete also deletes the task's linked artwork. Whether
    the GraphQL delete this app sends does the same is unconfirmed, hence "may". `published`
    counts artworks the dialog knows of; a blank catalog artwork_id is "not known", so this
    never says that none are published -- when publication could not be looked up at all
    (`unchecked`) it says exactly that instead.

    PART-CHECKED. When only some of the tasks could not be checked (`unchecked_tasks` of
    `tasks`), or a count was just given, "whether any of these are published was not checked"
    would contradict what the dialog does know -- so it says how many tasks went unchecked.

    The per-image dialog words it here; the bulk dialog (ActionsMenu.jsx) words the same
    sentences from the preview's counts, and a guard on each side pins the wording."""
    parts = []
    n = int(published or 0)
    if n > 0:
        parts.append("{} of these {} published on PixAI. Deleting the {} may remove the "
                     "published artwork too.".format(n, "is" if n == 1 else "are",
                                                     "task" if tasks == 1 else "tasks"))
    if unchecked:
        k = int(unchecked_tasks or 0)
        if n > 0 or 0 < k < tasks:
            parts.append("{} not checked for published artwork{}".format(
                ("{} of the {} tasks {}".format(k, tasks, "was" if k == 1 else "were")
                 if k > 0 else "Some of the tasks were"),
                "." if n > 0 else " — deleting a task may remove its published artwork too."))
        else:
            parts.append("Whether any of these are published on PixAI was not checked "
                         "— deleting a task may remove its published artwork too.")
    return " ".join(parts)


def mark_cloud_deleted(db_path, media_id, when):
    """Record that PixAI no longer has THIS image: the `deletedAt` stamp its entry in the
    task's outputs.batch carries.

    Per-ROW and permanent, which is why it is not `deleted_remote` -- that one is a
    task-level advisory --reconcile-deleted rewrites on every run. Nothing local is removed
    by this: a row carrying the stamp is one whose local copy is now the only copy anywhere.
    Fails soft to 0 written; a marker that could break the delete dialog would be worse than
    a marker that is late."""
    mid = str(media_id or "").strip()
    stamp = str(when or "").strip()
    if not mid or not stamp:
        return 0
    try:
        with _catalog.catalog(db_path) as con:
            n = con.execute("UPDATE catalog SET cloud_deleted_at=? WHERE media_id=?",
                            (stamp, mid)).rowcount
            con.commit()
            return n
    except sqlite3.Error:
        return 0


def task_media_count(db_path, task_id):
    """How many catalog rows share a task id -- is this picture one of a batch, or
    the only thing its task made? A COUNT rather than task_media() because the
    single delete-image dialog asks nothing else about them. Fails soft to 0: a
    number on a confirm dialog must never be able to break the dialog."""
    tid = str(task_id or "").strip()
    if not tid:
        return 0
    try:
        with _catalog.catalog(db_path) as con:
            return int(con.execute(
                "SELECT COUNT(*) FROM catalog WHERE task_id = ?", (tid,)).fetchone()[0])
    except sqlite3.Error:
        return 0


# sqlite's default host-parameter ceiling is 999, and this is well inside it while
# still cutting a big selection to a handful of passes.
_TASK_CHUNK = 400


def _delete_targets(con, media_ids):
    """The shared selection -> (task ids, local-only rows) resolution behind BOTH
    /api/delete-preview and the bulk delete. Shared rather than copied so the preview
    cannot drift from the action it previews: a dialog that lists a different blast
    radius than the delete then takes is worse than showing nothing at all.

    Returns (sel_rows, task_ids, local_only) where task_ids is sorted+deduped (one
    cloud delete per task no matter how many of its images were selected) and
    local_only holds the rows with no task id at all -- imports, which have nothing
    on PixAI to delete and are purged locally only.

    Takes a connection, not a db_path: delete_targets() and delete_preview_rows()
    both need this answer plus more from the SAME open connection."""
    sel_rows = [con.execute(
        "SELECT media_id, task_id, filename FROM catalog WHERE media_id=?", (m,)
    ).fetchone() for m in media_ids]
    sel_rows = [dict(r) for r in sel_rows if r]
    task_ids = sorted({(r.get("task_id") or "").strip()
                       for r in sel_rows if (r.get("task_id") or "").strip()})
    local_only = [r for r in sel_rows if not (r.get("task_id") or "").strip()]
    return sel_rows, task_ids, local_only


def _members_of_tasks(con, task_ids):
    """{task_id: [row, ...]} for every media in the given tasks, in ONE chunked pass
    instead of a query per task.

    Rows come back grouped and sorted here rather than relying on the query's order,
    because one statement now returns several tasks interleaved. (The chunked IN also
    predates the idx_task_id index: measured on a 36,000-row catalog, 800 per-task
    scans cost 8.6s inside the request /api/delete-preview's dialog was waiting on,
    against 38ms chunked.)"""
    out = {}
    for i in range(0, len(task_ids), _TASK_CHUNK):
        chunk = task_ids[i:i + _TASK_CHUNK]
        rows = con.execute(
            # cloud_deleted_at rides along (2026-09-07) for the delete preview's live
            # check: it is one of the two sources _rows_the_bulk_purge_must_keep keeps
            # rows back from, and reading it here costs nothing -- same statement, one
            # more column, so the chunked-pass guarantee above is untouched.
            # artwork_id rides along the same way (2026-09-26, SCOPE_2026-09-26 E5): the
            # preview's published-artwork count falls back to it for a task the live check
            # did not read (over its 40-task cap, or unanswered).
            "SELECT media_id, task_id, is_video, poster_media_id, cloud_deleted_at, artwork_id "
            "FROM catalog WHERE task_id IN ({})".format(",".join("?" * len(chunk))), chunk)
        for r in rows:
            out.setdefault(r["task_id"], []).append(dict(r))
    for members in out.values():
        members.sort(key=lambda r: r["media_id"])
    return out


def delete_targets(db_path, media_ids):
    """What a selection of media_ids actually resolves to for a delete:
    (sel_rows, task_ids, local_only). See _delete_targets for the shape."""
    with _catalog.catalog(db_path) as con:
        return _delete_targets(con, media_ids)


def delete_preview_rows(db_path, media_ids, task_cap=None):
    """Everything "Delete from PixAI" needs to describe its own blast radius before
    anything fires, in ONE connection: the selection resolved to tasks, each task
    expanded to its FULL catalog membership (deleting on PixAI is task-level, so
    picking one image of a batch takes all four), and the display-capped rows for the
    task-less imports the same button purges locally.

    Returns {sel_rows, task_ids, local_only, members_by_task, local_rows}. The caps
    are DISPLAY bounds on `local_rows` only -- task_ids and local_only always describe
    the entire selection, because the totals are what the user reads to decide."""
    from moonglade.trash import DELETE_PREVIEW_TASK_CAP
    cap = DELETE_PREVIEW_TASK_CAP if task_cap is None else task_cap
    with _catalog.catalog(db_path) as con:
        sel_rows, task_ids, local_only = _delete_targets(con, media_ids)
        members_by_task = _members_of_tasks(con, task_ids)
        shown = [con.execute(
            "SELECT media_id, is_video, poster_media_id FROM catalog WHERE media_id=?",
            (r["media_id"],)).fetchone() for r in local_only[:cap]]
        local_rows = [dict(r) for r in shown if r]
    return {"sel_rows": sel_rows, "task_ids": task_ids, "local_only": local_only,
            "members_by_task": members_by_task, "local_rows": local_rows}


def myart_items(db_path):
    """Every catalog row that exists as a PixAI ARTWORK (artwork_id set by
    --sync-artworks), public AND private -- the My Art gallery's whole population,
    newest first. Pure catalog read: title/likes/comments/tags/nsfw all arrive via
    --sync-artworks, so nothing here touches the network. `likes` and `comments` come
    back as ints (the columns are TEXT and blank means zero).

    `views` joins them as of 2026-09-06 and is the reason My Art can now draw a real
    number on EVERY card rather than a summed twelve. It keeps its raw text alongside
    (`views_raw`) precisely because blank and zero are different answers here: '' is "this
    library has never been swept", 0 is "swept, and nobody has looked at it". A card must
    be able to say the first without drawing the second."""
    with _catalog.catalog(db_path) as con:
        rows = con.execute(
            "SELECT media_id, artwork_id, title, prompt_preview, is_video, is_nsfw,"
            " is_sensitive, created_at, art_tags, is_published,"
            " CAST(COALESCE(NULLIF(liked_count,''),'0') AS INTEGER) AS likes,"
            " CAST(COALESCE(NULLIF(comment_count,''),'0') AS INTEGER) AS comments,"
            " CAST(COALESCE(NULLIF(views,''),'0') AS INTEGER) AS views,"
            " views AS views_raw"
            " FROM catalog WHERE COALESCE(artwork_id,'') != '' AND media_id != ''"
            " ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


SNAPSHOT_KEEP_DAYS = 120
MYART_WINDOW_DAYS = 30


def _local_day(today=None):
    import datetime as _dt
    return (today or _dt.date.today()).strftime("%Y-%m-%d")


def record_artwork_snapshots(db_path, today=None):
    """Write today's reading of every published artwork into artwork_snapshots -- the
    history My Art's 30-day switch is computed from.

    One row per artwork per local day; a second call the same day REPLACES the row with the
    freshest numbers, so the sweep's fifteen-minute cadence costs nothing but a rewrite. The
    numbers are the catalog's own current ones (likes/comments from the meta sweep, views from
    the views sweep), so this reads nothing from PixAI. `views` stays NULL while the catalog's
    views are blank -- never swept is not zero. An animation's poster row and its mp4 row share
    one artwork_id; the larger reading of the two wins. Prunes past SNAPSHOT_KEEP_DAYS.

    Called after apply_artwork_meta and apply_artwork_views. Fails soft: history is a
    nicety and must never break a sweep. Returns the number of rows written."""
    import datetime as _dt
    day = _local_day(today)
    try:
        with _catalog.catalog(db_path) as con:
            cur = con.execute(
                "INSERT OR REPLACE INTO artwork_snapshots (artwork_id, day, views, likes, comments)"
                " SELECT artwork_id, ?,"
                " MAX(CASE WHEN COALESCE(views,'') = '' THEN NULL"
                "          ELSE CAST(views AS INTEGER) END),"
                " MAX(CAST(COALESCE(NULLIF(liked_count,''),'0') AS INTEGER)),"
                " MAX(CAST(COALESCE(NULLIF(comment_count,''),'0') AS INTEGER))"
                " FROM catalog WHERE COALESCE(artwork_id,'') != ''"
                " GROUP BY artwork_id", (day,))
            n = cur.rowcount or 0
            cutoff = ((today or _dt.date.today())
                      - _dt.timedelta(days=SNAPSHOT_KEEP_DAYS)).strftime("%Y-%m-%d")
            con.execute("DELETE FROM artwork_snapshots WHERE day < ?", (cutoff,))
            con.commit()
            return n
    except sqlite3.Error:
        return 0


def myart_window(db_path, today=None, days=MYART_WINDOW_DAYS):
    """The last-`days` views and likes of each published artwork, from artwork_snapshots.

    Returns (per_artwork, window):
      per_artwork = {artwork_id: {"views": int|None, "likes": int}} -- the gain since the
                    baseline snapshot. views is None when this artwork's views were never swept.
      window      = {"days": N, "since": "YYYY-MM-DD", "full": bool, "seen": bool (any history)}

    THE BASELINE, and what is honest about it: the newest snapshot taken on or before
    (today - days) when the history reaches that far back -- then `full` is true and the number
    really is a 30-day figure. Until it does, the baseline is the artwork's OLDEST snapshot, the
    number is "since that day", and `full` is false so the surface says "since <date>" instead
    of "30 days". `since` is the oldest snapshot day anywhere (today when there is none yet). A
    gain never goes below zero (a work PixAI removed likes from reads as no change, not as a
    negative). Pure catalog read."""
    import datetime as _dt
    t = today or _dt.date.today()
    today_s = _local_day(t)
    edge = (t - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        with _catalog.catalog(db_path) as con:
            snaps = con.execute(
                "SELECT artwork_id, day, views, likes FROM artwork_snapshots"
                " ORDER BY artwork_id, day").fetchall()
            cur_rows = con.execute(
                "SELECT artwork_id,"
                " MAX(CASE WHEN COALESCE(views,'') = '' THEN NULL ELSE CAST(views AS INTEGER) END) AS views,"
                " MAX(CAST(COALESCE(NULLIF(liked_count,''),'0') AS INTEGER)) AS likes"
                " FROM catalog WHERE COALESCE(artwork_id,'') != '' GROUP BY artwork_id").fetchall()
    except sqlite3.Error:
        return {}, {"days": days, "since": today_s, "full": False, "seen": False}
    by_art = {}
    for r in snaps:
        by_art.setdefault(r["artwork_id"], []).append(r)
    since = min((r["day"] for r in snaps), default=today_s)
    out = {}
    for c in cur_rows:
        hist = by_art.get(c["artwork_id"]) or []
        base = None
        for r in hist:                       # newest snapshot on or before the edge
            if r["day"] <= edge:
                base = r
        if base is None and hist:
            base = hist[0]                   # not 30 days of history yet: the oldest we have
        if base is None:
            out[c["artwork_id"]] = {"views": None if c["views"] is None else 0, "likes": 0}
            continue
        v = None
        if c["views"] is not None:
            # the baseline's own views may be NULL (swept later); the first swept reading is it
            bv = base["views"]
            if bv is None:
                bv = next((h["views"] for h in hist if h["views"] is not None), c["views"])
            v = max(0, int(c["views"]) - int(bv))
        out[c["artwork_id"]] = {"views": v, "likes": max(0, int(c["likes"] or 0) - int(base["likes"] or 0))}
    return out, {"days": days, "since": since, "full": since <= edge, "seen": bool(snaps)}


def myart_coverage(db_path):
    """WHY My Art is empty, when it is (#42) -- the two counts that tell "you have
    published nothing" apart from "--sync-artworks has never run on this library".

    `artworks` is the population myart_items() returns: catalog rows carrying an
    artwork_id. `media` is the whole catalog. artwork_id and is_published are written
    EXCLUSIVELY by --sync-artworks (moonglade/backup.py's run_sync_artworks), so a
    catalog holding media with zero artworks has simply never been synced -- a state the
    rows alone cannot distinguish from a genuinely unpublished library, which is exactly
    the silence the empty state used to answer with.

    Two counts and not one because the pair is what makes the claim honest: `media` alone
    would have the surface blame a sync on an empty library, and `artworks` alone cannot
    tell an unsynced library from an unpopulated one. Fails soft to zeros -- an empty
    state that cannot explain itself is only the state it already had."""
    with _catalog.catalog(db_path) as con:
        try:
            r = con.execute(
                "SELECT COUNT(*) AS media,"
                " COALESCE(SUM(CASE WHEN COALESCE(artwork_id,'') != '' THEN 1 ELSE 0 END),0)"
                " AS artworks FROM catalog").fetchone()
            return {"media": int(r["media"] or 0), "artworks": int(r["artworks"] or 0)}
        except sqlite3.Error:
            return {"media": 0, "artworks": 0}


def artwork_media_ids(db_path, artwork_ids):
    """{artwork_id: media_id} for the ids the catalog knows, skipping the ones it does
    not. Cheap by construction: --sync-artworks writes artwork_id onto the SAME row as
    the media_id it belongs to, so this is a lookup rather than any kind of join -- and
    since 2026-09-03 it is genuinely indexed (idx_artwork_id), which this docstring
    claimed for a while before the index existed. It is what lets an entries listing show real thumbnails (/thumbs/<media_id>)
    for artworks the local library already holds -- an entry made from another device
    simply has no local media and gets no thumb, which is the honest answer.

    Chunked because SQLite caps the number of bound parameters in one statement."""
    ids = [str(a).strip() for a in (artwork_ids or []) if str(a or "").strip()]
    if not ids:
        return {}
    out = {}
    with _catalog.catalog(db_path) as con:
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            rows = con.execute(
                "SELECT artwork_id, media_id FROM catalog WHERE artwork_id IN (%s)"
                % ",".join("?" * len(chunk)), chunk).fetchall()
            for r in rows:
                aid, mid = str(r["artwork_id"] or ""), str(r["media_id"] or "")
                if aid and mid:
                    out[aid] = mid
    return out


def artwork_row(db_path, media_id):
    """The publish-relevant catalog row behind one media_id (artwork_id / task_id /
    title / art_tags / is_published), or None. What every My Art card action resolves
    its target through before it will talk to PixAI at all."""
    with _catalog.catalog(db_path) as con:
        r = con.execute(
            "SELECT media_id, artwork_id, task_id, title, art_tags, is_published"
            " FROM catalog WHERE media_id = ? LIMIT 1", (str(media_id),)).fetchone()
    return dict(r) if r else None


def publish_state(db_path, media_id, artwork_id=None, published=None,
                  art_tags=None, title=None):
    """Mirror a completed PixAI publish/unpublish/re-tag/delete back into the catalog
    so the grid reflects it without a full --sync-artworks. Every field is optional and
    None means LEAVE IT ALONE -- an artwork whose visibility changed must not have its
    title or tags rewritten as a side effect.

    `published` is a bool (stored as the catalog's '1'/'0' TEXT), `art_tags` an
    already-formatted comma string. Unpublishing on PixAI is expressed here as
    artwork_id='' plus published=False: the local row survives, it just no longer
    claims an artwork. Returns the number of columns written."""
    sets, params = [], []
    if artwork_id is not None:
        sets.append("artwork_id=?"); params.append(str(artwork_id))
    if published is not None:
        sets.append("is_published=?"); params.append("1" if published else "0")
    if art_tags is not None:
        sets.append("art_tags=?"); params.append(str(art_tags))
    if title is not None:
        sets.append("title=?"); params.append(str(title))
    if not sets:
        return 0
    params.append(str(media_id))
    with _catalog.catalog(db_path) as con:
        con.execute("UPDATE catalog SET {} WHERE media_id=?".format(", ".join(sets)),
                    params)
        con.commit()
    return len(sets)


# The eleven columns extract_artwork_meta() fills. Named here, once, because
# apply_artwork_meta below writes a column list into SQL and a typo'd or drifting
# name would either raise or -- worse -- silently stop writing a field. Every one is
# owned by PixAI (it is what listArtworks says about the work), so overwriting them
# from a sweep is a refresh, never a loss: nothing locally-authored lives in here.
ARTWORK_META_FIELDS = ("artwork_id", "title", "is_published", "is_nsfw", "is_sensitive",
                       "liked_count", "comment_count", "aes_score", "art_tags",
                       "blurhash", "nsfw_scores")


def apply_artwork_meta(db_path, metas):
    """Merge extract_artwork_meta() dicts onto existing catalog rows, one narrow UPDATE
    each, keyed by the media_id already on the dict.

    The row-level twin of --sync-artworks' merge step, and the reason the periodic
    living-library sweep is cheap enough to run every fifteen minutes: run_sync_artworks
    reads the WHOLE catalog into memory, edits the matched rows and upserts every row
    back (`load_catalog` -> `save_catalog`, moonglade/backup.py). That is correct but it
    rewrites ~36k rows to touch a handful. This writes only the rows the sweep actually
    saw, only the eleven PixAI-owned columns above, and never invents a row: a media_id
    with no catalog row (an artwork whose image was never downloaded) simply matches
    nothing, exactly as the full sync's own "unmatched artworks are skipped" does.

    `metas` may key the SAME artwork under two media_ids -- an animation's poster id and
    its mp4's id (see run_sync_artworks' by_video_mid, issue #20) -- and that is fine:
    they are two real catalog rows and both want the metadata.

    Returns the number of rows actually changed."""
    metas = [m for m in (metas or []) if m and m.get("media_id")]
    if not metas:
        return 0
    sql = "UPDATE catalog SET {} WHERE media_id=?".format(
        ", ".join("{}=?".format(f) for f in ARTWORK_META_FIELDS))
    changed = 0
    with _catalog.catalog(db_path) as con:
        for m in metas:
            cur = con.execute(sql, [str(m.get(f, "") or "") for f in ARTWORK_META_FIELDS]
                              + [str(m["media_id"])])
            changed += cur.rowcount or 0
        con.commit()
    if changed:
        record_artwork_snapshots(db_path)   # My Art's 30-day history (2026-11-19)
    return changed


# The four view columns (views, views_prev, views_at, views_prev_at) are folded by their own
# verb rather than by ARTWORK_META_FIELDS. Deliberately NOT part of the meta list: the meta
# fields ride the fifteen-minute living-library sweep, and reading a view count on PixAI ADDS
# one to it (PROBE_2026-09-06 measured it: a page that selects `views` moves every row it
# returns by +1). So views are read ONCE per deliberate --sync-artworks and never on the
# sweep's cadence -- a rule that only holds while the two writes stay two separate statements.
def apply_artwork_views(db_path, views_by_artwork_id, now_iso):
    """Fold a bulk views sweep onto the catalog rows it names, one narrow UPDATE each,
    keyed by artwork_id (the id the sweep returns; media_id is what the row is keyed by).

    The row-level twin of apply_artwork_meta for the four view columns, and it exists for
    the same reason: run_sync_artworks used to fold views inside a whole-catalog
    `load_catalog -> save_catalog` round trip, which reverted every write that landed
    while the walk was running. This touches only the rows the sweep actually saw and only
    the four columns above, in ONE transaction, so nothing else in the table can be
    reached.

    The per-row rule, and the whole of it: a reading only slides
    down into `views_prev` when a genuinely new one arrives to replace it, so `views_prev`
    always holds THE PREVIOUS SWEEP's number and the spike rule's window keeps its meaning.
    A row whose `views` is still blank has nothing to slide, and keeps its (blank) baseline.
    Rows the sweep missed are not in the map and are not written at all, so a partial sweep
    leaves the last reading anyone actually took.

    Returns the number of rows actually changed."""
    fresh_by_aid = {}
    for aid, fresh in (views_by_artwork_id or {}).items():
        aid = str(aid or "")
        if aid and fresh is not None:
            fresh_by_aid[aid] = fresh
    if not fresh_by_aid:
        return 0
    ids = list(fresh_by_aid)
    changed = 0
    with _catalog.catalog(db_path) as con:
        # Chunked so a library-sized sweep cannot walk into SQLite's bound-parameter
        # limit; idx_artwork_id makes each chunk an index lookup, never a table scan.
        for start in range(0, len(ids), 400):
            chunk = ids[start:start + 400]
            rows = con.execute(
                "SELECT media_id, artwork_id, views, views_at, views_prev, views_prev_at "
                "FROM catalog WHERE artwork_id IN ({})".format(
                    ", ".join("?" for _ in chunk)), chunk).fetchall()
            for r in rows:
                fresh = fresh_by_aid.get(str(r["artwork_id"] or ""))
                if fresh is None:
                    continue
                cur = str(r["views"] or "")
                prev = str(r["views_prev"] or "")
                prev_at = str(r["views_prev_at"] or "")
                if cur != "":
                    prev = cur
                    prev_at = str(r["views_at"] or "")
                upd = con.execute(
                    "UPDATE catalog SET views=?, views_prev=?, views_at=?,"
                    " views_prev_at=? WHERE media_id=?",
                    (str(int(fresh)), prev, now_iso, prev_at, str(r["media_id"])))
                changed += upd.rowcount or 0
        con.commit()
    if changed:
        record_artwork_snapshots(db_path)   # My Art's 30-day history (2026-11-19)
    return changed


def lineage(db_path, media_id):
    """The family tree of one image, as rows:
      * siblings -- the other outputs of the SAME generation task (share task_id).
      * parent   -- the SOURCE image this one was derived from (source_media_id),
                    carrying `kind`, the derivation (edit/upscale/video).
      * children -- every image derived FROM this one, each with its own `kind`.
    Returns {row, siblings, parent, children}, or None for a media_id the catalog does
    not know -- "unknown image" is the caller's refusal to make, not this verb's. Any
    dimension can be empty: an original txt2img with a batch of 1 and no derivatives
    has an empty tree. Pure catalog read, no network."""
    mid = str(media_id or "").strip()
    cols = "media_id, is_video, title, prompt_preview"
    with _catalog.catalog(db_path) as con:
        me = con.execute(
            "SELECT media_id, task_id, source_media_id, derive_kind FROM catalog"
            " WHERE media_id = ? LIMIT 1", (mid,)).fetchone()
        if not me:
            return None
        siblings = []
        if me["task_id"]:
            siblings = [dict(r) for r in con.execute(
                "SELECT %s FROM catalog WHERE task_id = ? AND media_id != ?"
                " ORDER BY media_id" % cols, (me["task_id"], mid)).fetchall()]
        parent = None
        if me["source_media_id"]:
            pr = con.execute("SELECT %s FROM catalog WHERE media_id = ? LIMIT 1" % cols,
                             (me["source_media_id"],)).fetchone()
            if pr:
                parent = dict(pr, kind=me["derive_kind"] or "derived")
        children = [dict(r, kind=(r["derive_kind"] or "derived"))
                    for r in con.execute(
                        "SELECT %s, derive_kind FROM catalog WHERE source_media_id = ?"
                        " ORDER BY created_at" % cols, (mid,)).fetchall()]
    return {"row": dict(me), "siblings": siblings, "parent": parent,
            "children": children}


def sibling_media(db_path, task_ids):
    """Every output of each requested task, in ONE query, ordered by (task_id,
    media_id) -- the page-batched form of lineage()'s siblings, for the card
    placard's Sibling Strip. Includes each task's own members entire (the caller
    lights "self" by media_id).

    An EMPTY task_id is never queried: every import shares '', and one giant
    pseudo-batch of unrelated images is not a sibling strip."""
    ids = [str(t) for t in (task_ids or []) if str(t).strip()]
    if not ids:
        return []
    with _catalog.catalog(db_path) as con:
        rows = con.execute(
            "SELECT task_id, media_id, is_video, batch_index FROM catalog"
            " WHERE task_id IN (%s) AND task_id != ''"
            " ORDER BY task_id, media_id" % ",".join("?" * len(ids)), ids).fetchall()
        return [dict(r) for r in rows]


def recent_train_task_page(db_path, limit=18, before=None, q=""):
    """Generations grouped by TASK, newest task first, for the Train dataset pickers (the
    phone's tiles are tasks; desktop's "Grouped" view) -- each entry is one generation and its
    real image count, never a fixed batch size (real batches are 1-4). Videos, task-less
    imports and rows with no file are excluded: a training set is made of images that exist on
    disk.

    PAGED BY TASK (issue #56: the phone stopped at the 18 newest). A task is ordered by its
    newest image; `before` is the previous page's `next_before` cursor -- that newest
    created_at and the task id, the tie-breaker -- and the page holds the next `limit` tasks
    strictly older than it. Every image of a task on the page comes with it, whatever its own
    timestamp, so a task is never split across two pages.

    `q` is the library's own search (_build_where: prompt words, field operators, a pasted
    id); a task is on the page when any of its images matches, and then all of its images come.

    Returns (tasks, next_before): tasks = [{task_id, media_ids, count, newest}], newest image
    first within a task; next_before is None when there is nothing older."""
    limit = max(1, int(limit))
    where = ("task_id != '' AND COALESCE(is_video,'') != '1' AND filename != ''")
    head_where, head_params = where, []
    if (q or "").strip():
        qw, qp = _catalog_search._build_where(q.strip(), "", "", "", media_type="image")
        head_where, head_params = where + " AND " + qw, qp
    params = []
    having = ""
    if before and before.get("at") is not None:
        having = " HAVING (newest < ? OR (newest = ? AND task_id < ?))"
        params = [before["at"], before["at"], str(before.get("task") or "")]
    with _catalog.catalog(db_path) as con:
        heads = con.execute(
            "SELECT task_id, MAX(created_at) AS newest FROM catalog WHERE " + head_where +
            " GROUP BY task_id" + having +
            " ORDER BY newest DESC, task_id DESC LIMIT ?",
            head_params + params + [limit + 1]).fetchall()
        more = len(heads) > limit
        heads = heads[:limit]
        ids = [h["task_id"] for h in heads]
        rows = con.execute(
            "SELECT media_id, task_id FROM catalog WHERE " + where +
            " AND task_id IN (%s) ORDER BY created_at DESC, media_id" % ",".join("?" * len(ids)),
            ids).fetchall() if ids else []
    groups = {tid: [] for tid in ids}
    for r in rows:
        groups[r["task_id"]].append(r["media_id"])
    tasks = [{"task_id": h["task_id"], "media_ids": groups[h["task_id"]],
              "count": len(groups[h["task_id"]]), "newest": h["newest"]} for h in heads]
    nxt = ({"at": heads[-1]["newest"], "task": heads[-1]["task_id"]} if more and heads else None)
    return tasks, nxt


def history_page(db_path, since_utc, until_utc, media="", source=""):
    """One window of the history feed: every catalog row created in
    [since_utc, until_utc), newest first, plus the cursor for the page below it.

    ONE indexed range query (`created_at >= ? AND created_at < ?`, no functions on the
    column) and one seek. The window is passed in already resolved to UTC strings
    because the DAY boundaries are the caller's business -- they depend on the viewer's
    timezone, and computing them at the route is what makes them deterministic and
    testable. `media`/`source` are _build_where's own idiom.

    Returns {rows, older_created_at}: `older_created_at` is the created_at of the
    NEWEST row older than this window (None if there is nothing older), so the caller
    can open the next page on a day that has runs instead of a run of empty days."""
    where, params = _catalog_search._build_where("", "", "", "", media_type=media, source=source)
    with _catalog.catalog(db_path) as con:
        rows = con.execute(
            "SELECT media_id, task_id, is_video, created_at, width, height, model_id, "
            "COALESCE(NULLIF(model_name,''), NULLIF(video_model,''), model_id, '') AS model, "
            "SUBSTR(COALESCE(NULLIF(prompt_full,''), prompt_preview, ''), 1, 300) AS prompt, "
            "video_duration, paid_credit, source "
            "FROM catalog WHERE {} AND created_at >= ? AND created_at < ? "
            "ORDER BY created_at DESC, media_id DESC".format(where),
            params + [since_utc, until_utc]).fetchall()
        older = con.execute(
            "SELECT created_at FROM catalog WHERE {} AND created_at < ? "
            "ORDER BY created_at DESC LIMIT 1".format(where),
            params + [since_utc]).fetchone()
    return {"rows": [dict(r) for r in rows],
            "older_created_at": older[0] if older else None}


def history_created_ats(db_path, since_utc, until_utc, media="", source=""):
    """Just the created_at values in a window, for counting how many LOCAL days of
    the next page actually have runs ("Load N older days"). Values, not days: which
    local day a UTC timestamp falls in depends on the viewer's timezone, so the
    bucketing is the caller's to do."""
    where, params = _catalog_search._build_where("", "", "", "", media_type=media, source=source)
    with _catalog.catalog(db_path) as con:
        rows = con.execute(
            "SELECT created_at FROM catalog WHERE {} AND created_at >= ? "
            "AND created_at < ?".format(where),
            params + [since_utc, until_utc]).fetchall()
    return [r[0] for r in rows]


def distinct_task_count(db_path):
    """How many distinct generation TASKS the local catalog holds. This is the apples-to-apples
    counterpart to the server's `me.tasks.totalCount` (also tasks, not images) -> backup coverage
    = local/server. Counts distinct non-empty task_id. Fails soft to 0."""
    with _catalog.catalog(db_path) as con:
        try:
            return int(con.execute(
                "SELECT COUNT(DISTINCT task_id) FROM catalog WHERE COALESCE(task_id,'') != ''"
            ).fetchone()[0] or 0)
        except sqlite3.Error:
            return 0


def backup_coverage(db_path, out_dir, server_tasks):
    """The header's Backed up pill: {pct, note, local, server, no_picture, missing, deleted}.

    WHAT IT USED TO COUNT, and why it never reached 100% (owner, 2026-11-18: "I have asked this
    question myself and you once told me to just run sync again. I gave up caring."): every
    distinct task in the catalog over PixAI's `me.tasks.totalCount`. Two things were wrong at
    once. The bottom counted every task PixAI lists, failed and cancelled ones too -- and
    those never made a picture, so no sync can ever fetch them. And the top counted tasks
    already deleted on PixAI (deleted_remote), which PixAI no longer counts, so they hid part
    of that gap. Now the top is the tasks here that PixAI still has, the bottom leaves out the
    ones with no picture (counted by the last full walk of the feed -- the deleted-on-PixAI
    check every Sync ends with -- and kept in reconcile_stamp.json), and the note says in plain
    words what is left and what fixes it. Rounded DOWN, so 100% means nothing is missing.
    `server_tasks` None (PixAI unreachable) -> pct None, as before."""
    import math
    with _catalog.catalog(db_path) as con:
        try:
            local = int(con.execute(
                "SELECT COUNT(DISTINCT task_id) FROM catalog WHERE COALESCE(task_id,'') != '' "
                "AND COALESCE(deleted_remote,'') != '1'").fetchone()[0] or 0)
            deleted = int(con.execute(
                "SELECT COUNT(DISTINCT task_id) FROM catalog WHERE COALESCE(task_id,'') != '' "
                "AND COALESCE(deleted_remote,'') = '1'").fetchone()[0] or 0)
        except sqlite3.Error:
            local = deleted = 0
    from moonglade import library_runs as _library_runs
    stamp = _library_runs.read_reconcile_stamp(out_dir)
    walked = "no_picture" in stamp
    try:
        no_picture = max(0, int(stamp.get("no_picture") or 0))
        missing = max(0, int(stamp.get("missing") or 0))
    except (TypeError, ValueError):
        no_picture, missing, walked = 0, 0, False
    out = {"pct": None, "note": "", "local": local, "server": server_tasks,
           "no_picture": no_picture, "missing": missing, "deleted": deleted}
    if not server_tasks:
        return out
    bottom = max(1, int(server_tasks) - no_picture)
    out["pct"] = min(100.0, math.floor(local / bottom * 1000) / 10)
    fmt = "{:,}".format
    words = ["{} of the {} picture-making generations PixAI has for you are here.".format(
        fmt(min(local, bottom)), fmt(bottom))]
    if walked and no_picture:
        words.append("{} more failed or were cancelled on PixAI and never made a picture, "
                     "so there is nothing to back up and nothing can fix that; they are not "
                     "counted.".format(fmt(no_picture)))
    short = max(0, bottom - local)
    if short:
        words.append("{} {} not here yet: Sync now fetches {}.".format(
            fmt(short), "is" if short == 1 else "are", "it" if short == 1 else "them"))
    if deleted:
        words.append("{} you deleted on PixAI {} kept here and not counted.".format(
            fmt(deleted), "is" if deleted == 1 else "are"))
    if not walked:
        words.append("Failed and cancelled generations are counted until the next Sync "
                     "checks your whole PixAI history.")
    out["note"] = " ".join(words)
    return out


def rows_for_media_ids(db_path, ids):
    """Fetch catalog rows for a specific list of media_ids, preserving the given order.
    Used by the contact-sheet print view. Chunked to stay under SQLite's variable cap."""
    ids = [str(i) for i in (ids or []) if str(i).strip()]
    if not ids:
        return []
    with _catalog.catalog(db_path) as con:
        found = {}
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            ph = ",".join("?" * len(chunk))
            for r in con.execute(
                "SELECT * FROM catalog WHERE media_id IN ({})".format(ph), chunk
            ).fetchall():
                found[str(r["media_id"])] = dict(r)
        return [found[i] for i in ids if i in found]


def paid_credit_for_tasks(db_path, task_ids):
    """{task_id: paid_credit text} from the catalog for these task ids: PixAI's own charge
    for the task, task-level on every row it made ('' when a row exists with no charge
    reported). A task with no row is absent. Chunked like rows_for_media_ids."""
    ids = sorted({str(t).strip() for t in (task_ids or []) if str(t or "").strip()})
    out = {}
    if not ids or not Path(db_path).exists():
        return out
    with _catalog.catalog(db_path) as con:
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            ph = ",".join("?" * len(chunk))
            for r in con.execute(
                "SELECT task_id, paid_credit FROM catalog WHERE task_id IN ({})".format(ph), chunk
            ).fetchall():
                tid, pc = str(r["task_id"]), str(r["paid_credit"] or "").strip()
                if pc or tid not in out:          # a row that reports a charge wins
                    out[tid] = pc
    return out


def loom_cost(text):
    """A charge read off the catalog: an int, or None when nothing usable was reported. A
    blank, junk or non-finite value is unknown, never 0 -- 0 means a settled free render."""
    s = str(text if text is not None else "").strip()
    if not s:
        return None
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    try:
        return int(v)
    except (OverflowError, ValueError):
        return None


# ---- THE LOOM'S SEND RECORD (2026-11-18): the one source of a board's "spent" figure --------
# One append-only file per account (_moonglade/loom/_sends/<account>.jsonl). A line is written
# when a render is SENT from a board -- the moment the journal records its task id -- never
# when a picture lands on a shot. So a clip linked, imported, remixed or seeded onto a card is
# not a send and never counts; a re-render is its own send and adds its own charge.
#
# Line kinds, folded by loom_sends_fold:
#   a send      {board, card, task_id|null, submit_id|null, kind, cost|null, at}
#               kind "render" (sent from the Loom) or "backfill" (found on a board saved
#               before this record existed); cost 0 when a free card was attached, else the
#               catalog's paid_credit once known, null until then (shown as unknown)
#   a cost      {task_id, cost}         the charge, read off the catalog once it is there
#   a void      {submit_id, void: true} an unclear send the owner released: nothing was made
#   a marker    {board, backfilled: at} that board's one backfill has run

def loom_send_key(rec):
    tid = str(rec.get("task_id") or "")
    return ("t:" + tid) if tid else ("s:" + str(rec.get("submit_id") or ""))


def loom_sends_fold(lines):
    """{"sends": {key: send}, "backfilled": {board ids}} from the record's lines. The first
    line for a task owns its board and card, so a task is one board's send, once."""
    sends, by_submit, backfilled = {}, {}, set()
    for rec in lines:
        if not isinstance(rec, dict):
            continue
        if rec.get("backfilled") and rec.get("board"):
            backfilled.add(str(rec["board"]))
        elif rec.get("void") and rec.get("submit_id"):
            k = by_submit.get(str(rec["submit_id"]))
            if k and k in sends and not sends[k].get("task_id"):
                sends[k]["void"] = True
        elif rec.get("board") and rec.get("kind"):
            k = loom_send_key(rec)
            if k in ("t:", "s:") or k in sends:
                continue
            sends[k] = dict(rec)
            if rec.get("submit_id"):
                by_submit[str(rec["submit_id"])] = k
        elif rec.get("task_id") and "cost" in rec:
            k = "t:" + str(rec["task_id"])
            if k in sends and sends[k].get("cost") is None and isinstance(rec["cost"], int):
                sends[k]["cost"] = rec["cost"]
    return {"sends": sends, "backfilled": backfilled}


def loom_backfill_sends(board, board_id, known_task_ids, journal_entries, at=0.0):
    """The one-time backfill of a board saved before the send record existed. A send is a
    real task id the board or the journal kept for a render of this board: a stored take
    with source "render" that is not imported, a superseded render's task, a render still
    pending, or a journal entry for this board that reached PixAI. A take with no task id
    is NOT a send -- a seeded, linked, imported or remixed clip -- and nothing is ever
    priced from a quote: cost stays null here and is read off the catalog afterwards.
    `known_task_ids` (every task already recorded, on any board) keeps it idempotent and a
    task one board's alone. Pure: returns the new send lines, writes nothing."""
    seen = {str(t) for t in (known_task_ids or ())}
    out = []

    def add(tid, card):
        tid = str(tid or "").strip()
        if not tid or tid in seen:
            return
        seen.add(tid)
        out.append({"board": board_id, "card": str(card or ""), "task_id": tid,
                    "submit_id": None, "kind": "backfill", "cost": None, "at": at})

    for act in ((board or {}).get("acts") or []):
        for c in ((act or {}).get("cards") or []):
            if not isinstance(c, dict):
                continue
            cid = c.get("id")
            for t in (c.get("takes") or []):
                if isinstance(t, dict) and t.get("source") == "render" and not t.get("imported"):
                    add(t.get("taskId"), cid)
            for tid in (c.get("supersededTasks") or []):
                add(tid, cid)
            add(c.get("pendingTaskId"), cid)
    for e in (journal_entries or ()):
        if isinstance(e, dict) and str(e.get("board") or "") == board_id \
                and e.get("task_id") and e.get("state") == "submitted":
            add(e.get("task_id"), e.get("card"))
    return out


def integrity_rows(db_path):
    """Every catalog row, narrowed to what the integrity pass (moonglade/integrity.py)
    needs: the file it claims, whether it is a video, and the two archive-only flags.
    Plain dicts, catalog order."""
    with _catalog.catalog(db_path) as con:
        return [dict(r) for r in con.execute(
            "SELECT media_id, filename, is_video, deleted_remote, cloud_deleted_at "
            "FROM catalog WHERE COALESCE(media_id, '') != '' ORDER BY rowid").fetchall()]


def list_media_ids(db_path, q="", model="", date_from="", date_to="", sort="newest",
                   batch="", rating_min=0, published_only=False, art_tag="", lora="",
                   media_type="", source="", collection="", series=""):
    """Return ordered list of media_ids matching the filter (no row data).

    `series` narrows the walk to one dial-in series' members, exactly as query_catalog's
    does (_narrow_to_series), so the picture page opened from an opened stack counts and
    steps inside that stack. Empty = no narrowing, the walk is what it always was."""
    q, collection = _curation._expand_smart(db_path, q, collection)
    where, params = _catalog_search._build_where(q, model, date_from, date_to, batch, rating_min,
                                 published_only, art_tag, lora, media_type, source,
                                 collection)
    where, params = _curation._narrow_to_series(db_path, series, where, params)
    order, order_params = _catalog._order_sql(sort, collection)
    with _catalog.catalog(db_path) as con:
        rows = con.execute(
            "SELECT media_id FROM catalog WHERE {} ORDER BY {}".format(where, order),
            list(params) + order_params
        ).fetchall()
        return [r[0] for r in rows]


def list_group_rows(db_path, q="", model="", date_from="", date_to="", sort="newest",
                    batch="", rating_min=0, published_only=False, art_tag="", lora="",
                    media_type="", source="", collection=""):
    """The minimal per-row columns needed to fold a filtered result set into dial-in
    series UNITS (#34 direction B's grouped listing): (media_id, task_id, created_at,
    is_video) for EVERY matching row in the active sort order, WITHOUT a page LIMIT.

    Same WHERE + ORDER as query_catalog / list_media_ids -- the grouped listing has
    to see the whole filtered set, because a series spans many rows across pages (up
    to 801 images) and a client-side collapse of one page would only ever group the
    fraction that landed on it. It needs just these four columns, though: task_id to
    map a row to its series, created_at + is_video to pick each unit's cover (newest
    surviving image), and media_id to fetch that one cover's full row afterwards.
    Bounded work -- ids-only over the catalog (~36k rows max); measured in
    dev/tests/test_series_grouping.py. No `series=` param here on purpose: grouping is
    the alternative to a single-series view, never combined with it."""
    q, collection = _curation._expand_smart(db_path, q, collection)
    where, params = _catalog_search._build_where(q, model, date_from, date_to, batch, rating_min,
                                 published_only, art_tag, lora, media_type, source,
                                 collection)
    order, order_params = _catalog._order_sql(sort, collection)
    with _catalog.catalog(db_path) as con:
        rows = con.execute(
            "SELECT media_id, task_id, created_at, is_video FROM catalog "
            "WHERE {} ORDER BY {}".format(where, order), list(params) + order_params
        ).fetchall()
        return [dict(r) for r in rows]


def unique_models(db_path):
    """Return sorted list of distinct non-empty model names in the catalog."""
    with _catalog.catalog(db_path) as con:
        rows = con.execute(
            "SELECT DISTINCT model_name FROM catalog WHERE model_name != '' ORDER BY model_name"
        ).fetchall()
        return [r[0] for r in rows]


def backfill_batches(out_dir, db_path):
    """Scan batches/ on disk and populate the batch column for already-organized images.

    Safe to re-run — only updates rows where batch is currently empty.
    Returns number of rows updated.

    Rides the shared scan (`include=("batches",)` = walk only that subtree, no
    exclusions inside it) rather than its own iterdir+rglob pair, and takes the
    media_id from the scan instead of re-typing `stem.split("_")[-1]` inline --
    that inline copy was one of the two INVARIANT-1 re-implementations.
    """
    updates = {}  # media_id -> batch_name
    for e in _scan.scan_library(out_dir, kinds=("image",), include=("batches",), exclude=()):
        if len(e.rel.parts) < 3:
            continue          # a loose file sitting directly in batches/ has no batch dir
        updates[e.media_id] = e.rel.parts[1]
    if not updates:
        return 0
    with _catalog.catalog(db_path) as con:
        updated = 0
        for mid, batch_name in updates.items():
            cur = con.execute(
                "UPDATE catalog SET batch=? WHERE media_id=? AND (batch='' OR batch IS NULL)",
                (batch_name, mid),
            )
            updated += cur.rowcount
        con.commit()
        return updated


def catalog_years(db_path):
    """Descending list of years (ints) present in catalog created_at, for the
    date-filter dropdowns. Empty if the catalog has no dated rows."""
    with _catalog.catalog(db_path) as con:
        rows = con.execute(
            "SELECT DISTINCT SUBSTR(created_at,1,4) AS y FROM catalog "
            "WHERE created_at != '' AND y != '' ORDER BY y DESC"
        ).fetchall()
        return [int(r[0]) for r in rows if str(r[0]).isdigit()]


def find_image_file(out_dir, media_id, filename):
    """Locate an image file: try catalog filename first, then media-id fallback.

    Excludes out_dir/gallery/ so thumbnails are never returned as full-res images.
    """
    gallery_dir = out_dir / "gallery"
    deleted_dir = out_dir / _scan.DELETED_DIRNAME
    records_dir = out_dir / _scan.RECORDS_DIRNAME
    if filename:
        for candidate in out_dir.rglob(filename):
            # The fallback below (find_files_for_media_id) already skips zero-byte
            # files -- this fast path found candidate rglob before that fallback ever
            # runs, so it needs the same size check or a catalog row still pointing at
            # its original filename gets a truncated/interrupted download served back
            # as if it were the real image (audit 2026-07-21, invariant 3/6).
            try:
                if (candidate.is_file() and candidate.stat().st_size > 0
                        and not _scan._is_under(candidate, gallery_dir)
                        and not _scan._is_under(candidate, deleted_dir)
                        and not _scan._is_under(candidate, records_dir)):
                    return candidate
            except OSError:
                continue
    matches = _scan.find_files_for_media_id(out_dir, media_id)
    return matches[0] if matches else None
