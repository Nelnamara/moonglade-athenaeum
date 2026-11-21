"""
moonglade/curation.py
=====================
Curation (Session N): smart collections, the collections manager (rename, merge, delete, the
manual order), the personal layer (tags, a keeper|reject mark, a note) under
`_CURATION_LOCK`, `CurationError`, and the library's two big reads, `query_catalog` and
`catalog_counts`, with the series narrowing and batch ordering they use. Nothing here deletes a
picture. Moved verbatim out of moonglade/gallery.py in the 3.22 split (phase 4).

It reads the catalog through moonglade.catalog and the search through moonglade.catalog_search,
and nothing from the gallery or the engine.
"""
import re
import sqlite3
import threading
import time

from moonglade import catalog as _catalog
from moonglade import catalog_search as _catalog_search
from moonglade import series as _series


# ---------------------------------------------------------------------------
# CURATION (Session N, 2026-09-29): smart collections, the collections manager, and the
# personal layer (tags, a keeper|reject mark, a note).
#
# WHERE THINGS LIVE, and the fact the whole session hangs on: the app's "collections" are
# LOCAL. A collection is nothing but a label in the comma-joined `catalog.collections`
# column (moonglade.gallery.add_to_collection above); PixAI has no part in it and nothing in
# this block reaches the network. Hand-picked membership stays there, unchanged. Two new
# tables (see _MIGRATIONS) hold the rest:
#   smart_collections  a saved SEARCH -- the query is stored, the membership never is; it is
#                      computed from the query every time the collection is opened
#   personal_meta      the owner's tags / mark / note, keyed by media_id
# Both are additive: an existing library gains two empty tables and keeps every row.
#
# NOTHING HERE DELETES A PICTURE. Deleting or merging a collection rewrites LABELS on rows;
# it never removes a row, a file or a thumbnail (dev/tests/test_curation.py counts them).
# ---------------------------------------------------------------------------

class CurationError(ValueError):
    """A curation request refused for a reason the owner can read (a taken name, a smart
    collection used as a hand-picked one, an over-long tag). The routes answer it as a 400
    carrying str(e)."""


PERSONAL_MARKS = ("keeper", "reject")
PERSONAL_TAG_MAX_LEN = 32      # characters in one tag
PERSONAL_TAGS_MAX = 32         # tags on one picture (the handoff page's own cap, N3)
PERSONAL_NOTE_MAX = 500        # characters in a note
CURATE_MAX_IDS = 5000          # pictures one bulk request may touch

_TAG_SPACE_RE = re.compile(r"[\s_]+")
_TAG_STRIP_RE = re.compile(r"[^\w-]", re.UNICODE)
_TAG_DASHES_RE = re.compile(r"-{2,}")


def normalize_tag(raw):
    """A personal tag in its stored form: lowercase, hyphenated, letters/digits/hyphens only
    (any script). "Pose Study!" -> "pose-study". Returns "" when nothing is left. The length
    cap is the caller's to enforce (it wants to say so, not silently truncate)."""
    t = _TAG_SPACE_RE.sub("-", str(raw or "").strip().lower())
    t = _TAG_STRIP_RE.sub("", t)
    return _TAG_DASHES_RE.sub("-", t).strip("-")


def _split_tags(s):
    return [t for t in (s or "").split(",") if t]


_CURATION_LOCK = threading.Lock()


def _now_stamp():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _clean_collection_name(name):
    """A collection name as stored: commas become spaces (the column is comma-joined), runs of
    whitespace collapse, ends are trimmed."""
    return re.sub(r"\s+", " ", str(name or "").replace(",", " ")).strip()


def _all_collection_names(con):
    """(hand_picked, smart) name lists, from one open connection."""
    hand = set()
    for (s,) in con.execute("SELECT collections FROM catalog WHERE COALESCE(collections,'') != ''"):
        hand.update(_catalog._split_collections(s))
    smart = [r[0] for r in con.execute("SELECT name FROM smart_collections")]
    return sorted(hand, key=str.lower), sorted(smart, key=str.lower)


def _is_smart_name(db_path, name):
    """Does `name` belong to a smart collection (compared without regard to case, since
    names are unique that way)? A hand-picked label may not take a smart collection's name."""
    low = str(name or "").strip().lower()
    if not low:
        return False
    with _catalog.catalog(db_path) as con:
        return any(r[0].lower() == low for r in con.execute("SELECT name FROM smart_collections"))


def list_smart_collections(db_path):
    """[{name, query}] for every smart collection, A-Z without regard to case."""
    with _catalog.catalog(db_path) as con:
        rows = con.execute("SELECT name, query FROM smart_collections").fetchall()
    return sorted(({"name": r["name"], "query": r["query"]} for r in rows),
                  key=lambda d: d["name"].lower())


def smart_collection_query(db_path, name):
    """The saved query of the smart collection called exactly `name`, or None."""
    if not name:
        return None
    with _catalog.catalog(db_path) as con:
        r = con.execute("SELECT query FROM smart_collections WHERE name=?", (str(name),)).fetchone()
    return r["query"] if r else None


def _expand_smart(db_path, q, collection):
    """(q, collection) with a smart collection folded into the search. Opening a smart
    collection IS running its saved query, ANDed with whatever the search field holds: its
    tokens are prepended to `q` and the collection filter drops away. A hand-picked name (or
    none) passes through untouched, so this costs one indexed lookup and only when a
    collection is named."""
    if not collection:
        return q, collection
    saved = smart_collection_query(db_path, collection)
    if saved is None:
        return q, collection
    return ((saved + " " + q).strip() if q else saved), ""


def _auto_smart_name(query):
    """The name a smart collection gets when the owner did not type one: the query with its
    operator punctuation softened, 28 characters at most (the handoff page's own rule)."""
    n = re.sub(r"\s+", " ", re.sub("[★:\"]", " ", str(query or ""))).strip()[:28].strip()
    return n or "Smart collection"


def save_smart_collection(db_path, query, name="", replace=""):
    """Create a smart collection from a search, or (with `replace`) save a new query over an
    existing one. Only the QUERY is stored. Returns {name, query, created}.

    A typed `name` that is taken raises CurationError; an unnamed one takes the query's own
    words and, when that is taken too, the next free "… 2", "… 3"."""
    q = " ".join(str(query or "").split())
    if not q:
        raise CurationError("Type a search first, then save it.")
    with _catalog.catalog(db_path) as con:
        with _CURATION_LOCK:
            if replace:
                if not con.execute("SELECT 1 FROM smart_collections WHERE name=?",
                                   (replace,)).fetchone():
                    raise CurationError("There is no smart collection called “{}”.".format(replace))
                con.execute("UPDATE smart_collections SET query=?, updated_at=? WHERE name=?",
                            (q, _now_stamp(), replace))
                con.commit()
                return {"name": replace, "query": q, "created": False}
            hand, smart = _all_collection_names(con)
            taken = {n.lower() for n in hand + smart}
            typed = _clean_collection_name(name)
            base = typed or _auto_smart_name(q)
            if typed and base.lower() in taken:
                raise CurationError("A collection called “{}” already exists.".format(base))
            final, n = base, 2
            while final.lower() in taken:
                final = "{} {}".format(base, n)
                n += 1
            now = _now_stamp()
            con.execute("INSERT INTO smart_collections (name, query, created_at, updated_at) "
                        "VALUES (?,?,?,?)", (final, q, now, now))
            con.commit()
            return {"name": final, "query": q, "created": True}


def _rows_with_label(con, name):
    """(media_id, collections) of every catalog row carrying exactly the label `name`."""
    return con.execute(
        "SELECT media_id, collections FROM catalog WHERE (',' || COALESCE(collections,'') || ',') "
        "LIKE ? ESCAPE '\\'", ("%," + _catalog._like_escape(name) + ",%",)).fetchall()


def rename_collection(db_path, old, new):
    """Rename a collection, hand-picked or smart. The new name is trimmed and must be unique
    (case-insensitively) among ALL collections; renaming only the case of its own name is
    allowed. Every picture keeps its membership: a hand-picked rename rewrites the label on
    the rows that carry it, a smart rename changes one row of smart_collections."""
    old = str(old or "").strip()
    new = _clean_collection_name(new)
    if not old:
        raise CurationError("Say which collection to rename.")
    if not new:
        raise CurationError("A collection needs a name.")
    with _catalog.catalog(db_path) as con:
        with _CURATION_LOCK, _catalog._COLLECTIONS_LOCK:
            hand, smart = _all_collection_names(con)
            if old not in smart and old not in hand:
                raise CurationError("There is no collection called “{}”.".format(old))
            if new.lower() in {n.lower() for n in hand + smart if n != old}:
                raise CurationError("A collection called “{}” already exists.".format(new))
            if new == old:
                return {"name": new, "kind": "smart" if old in smart else "hand", "changed": 0}
            if old in smart:
                con.execute("UPDATE smart_collections SET name=?, updated_at=? WHERE name=?",
                            (new, _now_stamp(), old))
                con.commit()
                return {"name": new, "kind": "smart", "changed": 1}
            changed = 0
            # P6: the manual order follows the rename (any stale rows under the new name go
            # first, so the move cannot collide on the primary key).
            con.execute("DELETE FROM collection_order WHERE name=?", (new,))
            con.execute("UPDATE collection_order SET name=? WHERE name=?", (new, old))
            for r in _rows_with_label(con, old):
                cols = [new if c == old else c for c in _catalog._split_collections(r["collections"])]
                seen, out = set(), []
                for c in cols:            # a row can never end up holding the label twice
                    if c not in seen:
                        seen.add(c)
                        out.append(c)
                con.execute("UPDATE catalog SET collections=? WHERE media_id=?",
                            (",".join(out), r["media_id"]))
                changed += 1
            con.commit()
            return {"name": new, "kind": "hand", "changed": changed}


def merge_collections(db_path, names):
    """Merge two or more HAND-PICKED collections into the first name given: every picture in
    any of them ends up in the first (once, however many it was in), and the others cease to
    exist. A smart collection cannot merge (it holds no pictures to move). Returns
    {target, merged, pictures, changed}. No picture is removed from the library."""
    order = []
    for n in names or []:
        n = str(n or "").strip()
        if n and n not in order:
            order.append(n)
    if len(order) < 2:
        raise CurationError("Pick two or more hand-picked collections to merge.")
    with _catalog.catalog(db_path) as con:
        with _CURATION_LOCK, _catalog._COLLECTIONS_LOCK:
            hand, smart = _all_collection_names(con)
            for n in order:
                if n in smart:
                    raise CurationError("“{}” is a smart collection and can’t merge. "
                                        "Edit its query instead.".format(n))
                if n not in hand:
                    raise CurationError("There is no hand-picked collection called “{}”.".format(n))
            target, others = order[0], set(order[1:])
            changed = 0
            # P6: the target keeps its manual order; the merged-in pictures have no position
            # there, so they follow it, oldest first. The merged collections' orders go.
            con.executemany("DELETE FROM collection_order WHERE name=?", [(n,) for n in sorted(others)])
            for r in con.execute("SELECT media_id, collections FROM catalog "
                                 "WHERE COALESCE(collections,'') != ''").fetchall():
                cols = _catalog._split_collections(r["collections"])
                if not any(c in others for c in cols):
                    continue
                out = []
                for c in cols:
                    c = target if c in others else c
                    if c not in out:
                        out.append(c)
                con.execute("UPDATE catalog SET collections=? WHERE media_id=?",
                            (",".join(out), r["media_id"]))
                changed += 1
            con.commit()
            pictures = len(_rows_with_label(con, target))
    return {"target": target, "merged": order[1:], "pictures": pictures, "changed": changed}


def delete_collection(db_path, name):
    """Delete a collection: a hand-picked one loses its label from every picture, a smart one
    loses its saved query. THE PICTURES STAY, always; `kept` says how many were in it (for a
    smart collection, how many matched a moment ago). Returns {name, kind, kept}."""
    name = str(name or "").strip()
    if not name:
        raise CurationError("Say which collection to delete.")
    with _catalog.catalog(db_path) as con:
        with _CURATION_LOCK, _catalog._COLLECTIONS_LOCK:
            hand, smart = _all_collection_names(con)
            if name in smart:
                kind = "smart"
            elif name in hand:
                kind = "hand"
            else:
                raise CurationError("There is no collection called “{}”.".format(name))
    if kind == "smart":
        _, kept = query_catalog(db_path, collection=name, page=1, page_size=1)
        with _catalog.catalog(db_path) as con:
            with _CURATION_LOCK:
                con.execute("DELETE FROM smart_collections WHERE name=?", (name,))
                con.commit()
        return {"name": name, "kind": "smart", "kept": kept}
    with _catalog.catalog(db_path) as con:
        with _CURATION_LOCK, _catalog._COLLECTIONS_LOCK:
            kept = 0
            con.execute("DELETE FROM collection_order WHERE name=?", (name,))   # P6: its order goes too
            for r in _rows_with_label(con, name):
                con.execute("UPDATE catalog SET collections=? WHERE media_id=?",
                            (",".join(c for c in _catalog._split_collections(r["collections"]) if c != name),
                             r["media_id"]))
                kept += 1
            con.commit()
    return {"name": name, "kind": "hand", "kept": kept}


# ---- manual order (Session P, P6) --------------------------------------------

def _collection_kind(con, name):
    """"smart" | "hand" | None for a collection name, from one open connection."""
    hand, smart = _all_collection_names(con)
    if name in smart:
        return "smart"
    if name in hand:
        return "hand"
    return None


def ordered_members(db_path, name):
    """The members of collection `name`, in its order: {name, kind, media_ids, manual}.

    Hand-picked: the labelled pictures (those the collection's own view shows, a file on
    disk) -- the ones with a position first, by position; then the ones without (added since
    the order was saved) OLDEST first (ruling 9). A position whose picture has left the
    collection is ignored. `manual` says whether any position is in force.
    Smart: its query's current matches, oldest first; never manual (membership is live).
    Unknown name: kind None, no ids. Read-only."""
    name = str(name or "").strip()
    if not name:
        return {"name": "", "kind": None, "media_ids": [], "manual": False}
    with _catalog.catalog(db_path) as con:
        kind = _collection_kind(con, name)
        if kind == "hand":
            rows = con.execute(
                "SELECT c.media_id, o.position FROM catalog c LEFT JOIN collection_order o "
                "ON o.name = ? AND o.media_id = c.media_id "
                "WHERE c.filename != '' AND (',' || COALESCE(c.collections,'') || ',') LIKE ? ESCAPE '\\' "
                "ORDER BY (o.position IS NULL), o.position, c.created_at ASC, c.media_id ASC",
                (name, "%," + _catalog._like_escape(name) + ",%")).fetchall()
            return {"name": name, "kind": "hand", "media_ids": [str(r[0]) for r in rows],
                    "manual": any(r[1] is not None for r in rows)}
    if kind == "smart":
        rows, _ = query_catalog(db_path, collection=name, sort="oldest", page_size=None)
        return {"name": name, "kind": "smart", "media_ids": [str(r["media_id"]) for r in rows],
                "manual": False}
    return {"name": name, "kind": None, "media_ids": [], "manual": False}


def set_collection_order(db_path, name, media_ids):
    """Save a hand-picked collection's manual order: positions 0..n-1 for `media_ids`, in ONE
    transaction, replacing the collection's old positions (which also prunes the rows of
    pictures no longer in it). Refuses a smart collection (its membership is live), an unknown
    one, a repeated id and any id that is not a member. Returns ordered_members() after."""
    name = str(name or "").strip()
    ids = [str(m).strip() for m in (media_ids or [])]
    if not name:
        raise CurationError("Say which collection to order.")
    if len(ids) > CURATE_MAX_IDS:
        raise CurationError("A collection order holds at most {} pictures.".format(CURATE_MAX_IDS))
    if len(set(ids)) != len(ids) or any(not m for m in ids):
        raise CurationError("Each picture appears once in an order.")
    with _catalog.catalog(db_path) as con:
        with _CURATION_LOCK, _catalog._COLLECTIONS_LOCK:
            kind = _collection_kind(con, name)
            if kind == "smart":
                raise CurationError("“{}” is a smart collection. Its pictures are the search's "
                                    "matches, so it can’t be ordered by hand.".format(name))
            if kind != "hand":
                raise CurationError("There is no hand-picked collection called “{}”.".format(name))
            members = {str(r["media_id"]) for r in _rows_with_label(con, name)}
            stray = [m for m in ids if m not in members]
            if stray:
                raise CurationError("{} of those {} not in “{}”.".format(
                    len(stray), "is" if len(stray) == 1 else "are", name))
            con.execute("DELETE FROM collection_order WHERE name=?", (name,))
            con.executemany("INSERT INTO collection_order (name, media_id, position) VALUES (?,?,?)",
                            [(name, m, i) for i, m in enumerate(ids)])
            con.commit()
    return ordered_members(db_path, name)


def collection_summaries(db_path):
    """Every collection with what the manager and the list show: {name, kind, count, cover,
    query?}. Hand-picked counts are pictures that still have a file (the count a search
    would give); a smart collection's count is its query run right now. `cover` is the
    newest member's media_id. A-Z without regard to case, hand-picked and smart together.
    Read-only."""
    hand = {}
    with _catalog.catalog(db_path) as con:
        for r in con.execute(
                "SELECT media_id, filename, collections FROM catalog "
                "WHERE COALESCE(collections,'') != '' ORDER BY created_at DESC"):
            for n in _catalog._split_collections(r["collections"]):
                h = hand.setdefault(n, {"count": 0, "cover": ""})
                if (r["filename"] or "") != "":
                    h["count"] += 1
                    if not h["cover"]:
                        h["cover"] = str(r["media_id"])
    out = [{"name": n, "kind": "hand", "count": h["count"], "cover": h["cover"]}
           for n, h in hand.items()]
    for s in list_smart_collections(db_path):
        rows, total = query_catalog(db_path, collection=s["name"], page=1, page_size=1)
        out.append({"name": s["name"], "kind": "smart", "count": total, "query": s["query"],
                    "cover": str(rows[0]["media_id"]) if rows else ""})
    return sorted(out, key=lambda d: d["name"].lower())


# ---- the personal layer -----------------------------------------------------

def personal_get(db_path, media_ids):
    """{media_id: {tags: [...], mark, note}} for the given pictures. Only pictures that have
    something are present -- a picture with no personal layer is simply absent, and the
    caller treats it as tags [] / mark "" / note ""."""
    ids = [str(m) for m in (media_ids or []) if str(m)]
    out = {}
    if not ids:
        return out
    with _catalog.catalog(db_path) as con:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            for r in con.execute(
                    "SELECT media_id, tags, mark, note FROM personal_meta WHERE media_id IN ({})"
                    .format(",".join("?" * len(chunk))), chunk):
                out[r["media_id"]] = {"tags": _split_tags(r["tags"]),
                                      "mark": r["mark"] or "", "note": r["note"] or ""}
    return out


def _curation_state(con, mid):
    """One picture's curation state -- {rating, mark, tags, note} -- or None when it is not in
    the catalog. `rating` is the ordinary catalog rating (the stars on every card); the rest
    is the personal layer."""
    row = con.execute("SELECT rating FROM catalog WHERE media_id=?", (mid,)).fetchone()
    if row is None:
        return None
    rs = str(row[0] or "")
    p = con.execute("SELECT tags, mark, note FROM personal_meta WHERE media_id=?", (mid,)).fetchone()
    return {"rating": min(5, int(rs)) if rs.isdigit() else 0,
            "mark": (p["mark"] if p else "") or "",
            "tags": _split_tags(p["tags"]) if p else [],
            "note": (p["note"] if p else "") or ""}


def _write_curation_state(con, mid, new, old):
    """Write `new` where it differs from `old`. The personal row is created, updated, or -- when
    all three fields are empty -- deleted, so the table only ever holds pictures that have
    something to say."""
    if new["rating"] != old["rating"]:
        con.execute("UPDATE catalog SET rating=? WHERE media_id=?",
                    (str(new["rating"]) if new["rating"] else "", mid))
    if (new["mark"], new["tags"], new["note"]) != (old["mark"], old["tags"], old["note"]):
        if not (new["mark"] or new["tags"] or new["note"]):
            con.execute("DELETE FROM personal_meta WHERE media_id=?", (mid,))
        else:
            con.execute("INSERT OR REPLACE INTO personal_meta (media_id, tags, mark, note, updated_at) "
                        "VALUES (?,?,?,?,?)",
                        (mid, ",".join(new["tags"]), new["mark"], new["note"], _now_stamp()))


def _clean_tag(raw):
    t = normalize_tag(raw)
    if not t:
        raise CurationError("A tag needs a letter or a number in it.")
    if len(t) > PERSONAL_TAG_MAX_LEN:
        raise CurationError("A tag is up to {} characters.".format(PERSONAL_TAG_MAX_LEN))
    return t


def _clean_note(raw):
    note = str(raw if raw is not None else "").strip()
    if len(note) > PERSONAL_NOTE_MAX:
        raise CurationError("A note is up to {} characters.".format(PERSONAL_NOTE_MAX))
    return note


def _clean_mark(raw):
    m = str(raw if raw is not None else "").strip().lower()
    if m in ("", "none", "null"):
        return ""
    if m not in PERSONAL_MARKS:
        raise CurationError("A mark is keeper, reject or none.")
    return m


def _clean_rating(raw):
    if isinstance(raw, bool):
        raise CurationError("A rating is a whole number from 0 to 5.")
    try:
        n = int(raw)
    except (TypeError, ValueError):
        raise CurationError("A rating is a whole number from 0 to 5.")
    if not 0 <= n <= 5:
        raise CurationError("A rating is a whole number from 0 to 5.")
    return n


def _clean_ids(media_ids):
    if not isinstance(media_ids, (list, tuple)):
        raise CurationError("No pictures given.")
    seen, out = set(), []
    for m in media_ids:
        m = str(m).strip()
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    if not out:
        raise CurationError("No pictures given.")
    if len(out) > CURATE_MAX_IDS:
        raise CurationError("That is more than {} pictures at once.".format(CURATE_MAX_IDS))
    return out


def curate_apply(db_path, media_ids, op):
    """Apply one change -- rating, mark, add_tag, remove_tag or note -- to every given picture.

    Returns {changed, prev, after, skipped, refused}. `prev` and `after` hold the full
    {rating, mark, tags, note} state of exactly the pictures that CHANGED, so the caller can
    put each picture back the way IT was (curate_restore) rather than resetting them all to
    one value, and so the count it shows is what really changed: setting a rating a picture
    already has is a no-op, not a change. `skipped` counts ids not in the catalog; `refused`
    counts pictures already at the tag cap. Local catalog only -- nothing here is sent to PixAI."""
    if not isinstance(op, dict) or not op:
        raise CurationError("Nothing to change.")
    clean = {}
    if "rating" in op:
        clean["rating"] = _clean_rating(op["rating"])
    if "mark" in op:
        clean["mark"] = _clean_mark(op["mark"])
    if "add_tag" in op:
        clean["add_tag"] = _clean_tag(op["add_tag"])
    if "remove_tag" in op:
        clean["remove_tag"] = normalize_tag(op["remove_tag"])
    if "note" in op:
        clean["note"] = _clean_note(op["note"])
    if not clean:
        raise CurationError("Nothing to change.")
    ids = _clean_ids(media_ids)
    prev, after, skipped, refused = {}, {}, 0, 0
    with _catalog.catalog(db_path) as con:
        with _CURATION_LOCK:
            for mid in ids:
                cur = _curation_state(con, mid)
                if cur is None:
                    skipped += 1
                    continue
                new = {"rating": cur["rating"], "mark": cur["mark"],
                       "tags": list(cur["tags"]), "note": cur["note"]}
                if "rating" in clean:
                    new["rating"] = clean["rating"]
                if "mark" in clean:
                    new["mark"] = clean["mark"]
                if "add_tag" in clean and clean["add_tag"] not in new["tags"]:
                    if len(new["tags"]) >= PERSONAL_TAGS_MAX:
                        refused += 1
                    else:
                        new["tags"].append(clean["add_tag"])
                if "remove_tag" in clean:
                    new["tags"] = [t for t in new["tags"] if t != clean["remove_tag"]]
                if "note" in clean:
                    new["note"] = clean["note"]
                if new == cur:
                    continue
                _write_curation_state(con, mid, new, cur)
                prev[mid], after[mid] = cur, new
            con.commit()
    return {"changed": len(after), "prev": prev, "after": after,
            "skipped": skipped, "refused": refused}


def curation_rows(db_path):
    """The owner's whole curation layer as plain rows, for the curation sidecar export
    (moonglade/curation_io.py): {catalog: rows carrying a rating or a collection label,
    personal: every personal_meta row, smart: every smart collection, order: every manual
    position by name then position}. Read-only."""
    with _catalog.catalog(db_path) as con:
        return {
            "catalog": [dict(r) for r in con.execute(
                "SELECT media_id, rating, collections FROM catalog "
                "WHERE COALESCE(media_id,'') != '' AND (COALESCE(NULLIF(rating,''),'0') != '0' "
                "OR COALESCE(collections,'') != '') ORDER BY media_id")],
            "personal": [dict(r) for r in con.execute(
                "SELECT media_id, tags, mark, note FROM personal_meta ORDER BY media_id")],
            "smart": [dict(r) for r in con.execute(
                "SELECT name, query FROM smart_collections ORDER BY name")],
            "order": [dict(r) for r in con.execute(
                "SELECT name, media_id, position FROM collection_order "
                "ORDER BY name, position")],
        }


def curate_restore(db_path, prev):
    """Undo for curate_apply: put each picture back to the state `prev` holds for it. Every
    entry is validated before anything is written, so a bad request changes nothing. Returns
    {restored, after}."""
    if not isinstance(prev, dict) or not prev:
        raise CurationError("Nothing to restore.")
    if len(prev) > CURATE_MAX_IDS:
        raise CurationError("That is more than {} pictures at once.".format(CURATE_MAX_IDS))
    wanted = {}
    for mid, st in prev.items():
        if not isinstance(st, dict):
            raise CurationError("A saved state is missing its values.")
        tags = []
        for t in st.get("tags") or []:
            t = _clean_tag(t)
            if t not in tags:
                tags.append(t)
        if len(tags) > PERSONAL_TAGS_MAX:
            raise CurationError("A picture holds at most {} tags.".format(PERSONAL_TAGS_MAX))
        wanted[str(mid)] = {"rating": _clean_rating(st.get("rating", 0)),
                            "mark": _clean_mark(st.get("mark")), "tags": tags,
                            "note": _clean_note(st.get("note"))}
    after = {}
    with _catalog.catalog(db_path) as con:
        with _CURATION_LOCK:
            for mid, new in wanted.items():
                cur = _curation_state(con, mid)
                if cur is None or new == cur:
                    continue
                _write_curation_state(con, mid, new, cur)
                after[mid] = new
            con.commit()
    return {"restored": len(after), "after": after}


def query_catalog(db_path, q="", model="", date_from="", date_to="",
                  sort="newest", page=1, page_size=100, batch="", rating_min=0,
                  published_only=False, art_tag="", lora="", media_type="", source="",
                  collection="", series="", no_svg=False):
    """Return (rows, total) with filtering, sorting and pagination done in SQL. `no_svg`
    leaves SVG rows out (see _build_where).

    `series` constrains the result to one dial-in series' members (#34 direction
    B, the ?series=<sid> "open a stack" view): the sid resolves through the series
    cache to its member task_ids and the WHERE gains a parameterized
    `task_id IN (...)` over exactly that (naturally size-capped) list. An UNKNOWN
    sid resolves to no members, which becomes an always-false clause -- an empty
    result, never an error, and never a bare `IN ()` (a SQL syntax error). The ids
    are bound as placeholders, like /api/siblings, so a sid can't inject SQL.

    `page_size=None` means UNPAGINATED: one statement returns every matching row and
    `total` is simply how many came back. That is not a convenience shorthand for "a very
    large page" -- it closes a real hole. The paginated path answers COUNT(*) and the page
    itself in two SEPARATE statements, i.e. two separate SQLite read snapshots with no
    transaction across them, so a write landing between the two makes them disagree. A grid
    page can absorb that (worst case a paginator is off by one for one refresh), but a
    caller that sizes its LIMIT off the count cannot: /export-csv did exactly that, and a
    "Sync now" Panel job inserting rows for minutes while the owner browsed meant the CSV
    silently shipped the OLD match count out of the new, larger match set, with nothing in
    the downloaded file admitting it was short. One statement has nothing to disagree with.
    """
    q, collection = _expand_smart(db_path, q, collection)
    where, params = _catalog_search._build_where(q, model, date_from, date_to, batch, rating_min,
                                 published_only, art_tag, lora, media_type, source,
                                 collection, no_svg=no_svg)
    where, params = _narrow_to_series(db_path, series, where, params)
    order, order_params = _catalog._order_sql(sort, collection)
    with _catalog.catalog(db_path) as con:
        if page_size is None:
            rows = con.execute(
                "SELECT * FROM catalog WHERE {} ORDER BY {}".format(where, order),
                list(params) + order_params,
            ).fetchall()
            # No second COUNT on purpose -- taking one here would reintroduce exactly the
            # two-snapshot disagreement this branch exists to avoid, and a total that can
            # differ from len(rows) is precisely what misled the export.
            return [dict(r) for r in rows], len(rows)
        total = con.execute(
            "SELECT COUNT(*) FROM catalog WHERE {}".format(where), params
        ).fetchone()[0]
        rows = con.execute(
            "SELECT * FROM catalog WHERE {} ORDER BY {} LIMIT ? OFFSET ?".format(where, order),
            list(params) + order_params + [page_size, (max(1, page) - 1) * page_size],
        ).fetchall()
        return [dict(r) for r in rows], total


def _narrow_to_series(db_path, series, where, params):
    """(where, params) narrowed to one dial-in series' members when `series` is set, else
    returned untouched. The ONE place the ?series=<sid> clause is built, so the paged
    listing (query_catalog) and the ordered id walk behind the picture page
    (list_media_ids) cannot drift apart: an UNKNOWN sid becomes an always-false clause
    (an empty result, never a bare `IN ()`), and the member task_ids are bound as
    placeholders."""
    if not series:
        return where, params
    member_ids = _series_member_task_ids(db_path, series)
    if member_ids:
        where += " AND task_id IN ({})".format(",".join("?" * len(member_ids)))
        return where, list(params) + member_ids
    return where + " AND 1=0", params   # unknown sid -> empty result, not an error


def _series_member_task_ids(db_path, sid):
    """Sanitized member task_ids for a dial-in series id, or [] for an unknown sid
    (#34 direction B, the ?series= filter). Resolved through the series cache; the
    list is exactly the series' own tasks -- so it is naturally capped at the
    series' real size -- each coerced to a non-empty, de-duplicated string, ready
    for safe parameterized IN-clause binding (query_catalog does the binding)."""
    _, by_sid = _series.series_index(db_path)
    s = by_sid.get(str(sid or "").strip())
    if not s:
        return []
    out, seen = [], set()
    for step in s.get("steps", []):
        tid = str(step.get("task_id") or "").strip()
        if tid and tid not in seen:
            seen.add(tid)
            out.append(tid)
    return out


def batch_member_order(rows):
    """One task's surviving catalog rows in #33's BATCH order -- PixAI's own output
    number (`batch_index`) when EVERY row carries one, else media_id ascending.

    The all-or-nothing rule is compute_series' own (see its "member media_ids are
    ordered the way /api/siblings orders them" note): a partly-numbered task would
    otherwise interleave numbered and unnumbered rows into an order nothing else in
    the app agrees with. Keeping the rule here means a BATCH stack lists a task's
    pictures in exactly the order its sibling strip and its series run already do.
    Pure -- no db, so dev/tests/test_batch_stack.py drives it directly."""
    def _bi(r):
        try:
            return int(str(r.get("batch_index") or "").strip())
        except ValueError:
            return None
    if rows and all(_bi(r) is not None for r in rows):
        return sorted(rows, key=lambda r: (_bi(r), str(r.get("media_id") or "")))
    return sorted(rows, key=lambda r: str(r.get("media_id") or ""))


def _filters_from_args(args):
    """Pull the gallery grid's filter set out of a request query string, keyed by
    query_catalog()'s own parameter names (the index route reads exactly these args --
    see its body, including the Year+Month dropdown pair a date filter arrives as).

    Only filters actually PRESENT come back, so an empty dict means "no filtering at
    all" and a caller can take the whole catalog instead. Values are validated the same
    way index() validates them, since they reach SQL."""
    def _ym(prefix, month_default):
        y = args.get(prefix + "_year", "")
        m = args.get(prefix + "_month", "")
        return "{}-{}".format(y, m or month_default) if y else ""

    try:
        rating_min = max(0, min(5, int(args.get("rating_min", 0))))
    except ValueError:
        rating_min = 0
    media_type = args.get("media", "")
    source = args.get("source", "")
    found = {
        "q":              args.get("q", ""),
        "model":          args.get("model", ""),
        "batch":          args.get("batch", ""),
        "date_from":      _ym("from", "01"),
        "date_to":        _ym("to", "12"),
        "rating_min":     rating_min,
        "published_only": args.get("published") == "1",
        "art_tag":        args.get("tag", ""),
        "lora":           args.get("lora", ""),
        "media_type":     media_type if media_type in ("image", "video") else "",
        "source":         source if source in ("online", "api", "local", "deleted") else "",
        "collection":     args.get("collection", ""),
        # #34 direction B: a ?series= drill-down is a real filter query_catalog honours
        # (like batch above), so /export-csv must carry it too -- otherwise exporting an
        # open series stack drops the constraint and dumps the whole filtered library.
        "series":         args.get("series", ""),
    }
    # Every default here is falsy (""/0/False), so dropping falsy values is exactly
    # "drop the filters the user didn't set".
    return {k: v for k, v in found.items() if v}


def catalog_counts(db_path):
    """At-a-glance header stats: image count, video count, distinct collections.
    Cheap COUNTs over the catalog. Fails soft to zeros."""
    with _catalog.catalog(db_path) as con:
        try:
            images = con.execute(
                "SELECT COUNT(*) FROM catalog WHERE filename != '' "
                "AND COALESCE(is_video,'') != '1'").fetchone()[0]
            videos = con.execute(
                "SELECT COUNT(*) FROM catalog WHERE is_video = '1'").fetchone()[0]
            names = set()
            for (s,) in con.execute(
                    "SELECT collections FROM catalog WHERE COALESCE(collections,'') != ''"):
                names.update(_catalog._split_collections(s))
            return {"images": images, "videos": videos, "collections": len(names)}
        except sqlite3.Error:
            return {"images": 0, "videos": 0, "collections": 0}
