"""moonglade.curation_io -- the curation sidecar: export the owner's own layer, import it back.

Everything the owner authored lives only in catalog.db: ratings and hand-picked collections on
the catalog rows, and three tables beside them -- personal_meta (tags, keeper/reject, a note),
smart_collections (saved searches) and collection_order (a hand-picked collection's manual
order). The CSV export carries the first two and has no import. This file is the round trip: a
small JSON keyed by media id, so a catalog rebuilt from a fresh re-pull gets its curation back.

    python -m moonglade --export-curation [FILE]
    python -m moonglade --import-curation FILE                           # dry run: the plan
    python -m moonglade --import-curation FILE --apply                   # fill-only
    python -m moonglade --import-curation FILE --apply --curation-overwrite

The gallery's Control Panel offers the same export as a download (GET /export-curation).

THE DOCUMENT (format "moonglade-curation", version 1):

    {"format", "version", "exported_at",
     "items": [{media_id, rating, collections: [...], tags: [...], mark, note}],
     "collection_order": {name: [media_id, ...]},
     "smart_collections": [{name, query}]}

Library-level data only (scope item 4, owner question 1 option a): the per-account files
(view presets, snippets, Toolbox presets, prefs) are keyed by a hash of a login name, so they
do not map onto another install's accounts; they are not in it. Deterministic: items by media
id, collections and names A-Z without regard to case, tags in the order the picture holds them
-- so export, import into a fresh catalog, export again gives the same bytes (dumps()).

IMPORT RULES
  * Validated whole before anything is written: the format and version, then every value
    through the catalog's own cleaners (_clean_rating/_mark/_note/_tag, the tag cap,
    CURATE_MAX_IDS). One bad value refuses the document in plain words; nothing changes.
  * Dry run unless `apply`. The dry run reads and reports exactly what an apply would change.
  * Fill-only unless `overwrite`: a rating, mark or note the catalog already has is kept; tags
    and collections are unioned; a collection that already has a manual order keeps it.
    `overwrite` makes the document win, for the pictures it lists: their rating, mark, note,
    tags and hand-picked collections become the document's (a label it does not list is
    taken off that picture -- a label, never a file), and its manual orders replace the
    catalog's.
  * Media ids this catalog does not have are counted and listed ("import again after a sync"),
    never invented (owner question 2, option a).
  * A smart collection whose name is taken by a different collection is skipped and reported.
  * Before an apply writes anything, the current state is exported to
    curation_pre_import_<stamp>.json among the library's decisions (_moonglade/decisions/) --
    including an empty entry for every
    picture the import is about to touch -- so an import can itself be undone with this same
    importer (--import-curation that file --apply --curation-overwrite). That puts back every
    touched picture's rating, mark, note, tags and collections; a smart collection or a
    manual order the import created stays (nothing here ever deletes one).
  * Writes go only through the existing catalog verbs (curate_restore, add_to_collection,
    remove_from_collection, save_smart_collection, set_collection_order). Local only: nothing
    here reaches PixAI.
"""
import json
import time
from pathlib import Path

from moonglade import paths as _paths

FORMAT = "moonglade-curation"
VERSION = 1
SNAPSHOT_PREFIX = "curation_pre_import_"


class CurationIOError(ValueError):
    """A curation document refused, in words the owner can act on."""


def _utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _fold(s):
    return str(s).casefold()


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_curation(db_path, now=None):
    """The library's curation as a deterministic dict (see the module docstring)."""
    from moonglade import gallery as g
    raw = g.curation_rows(db_path)
    items = {}

    def item(mid):
        return items.setdefault(mid, {"media_id": mid, "rating": 0, "collections": [],
                                      "tags": [], "mark": "", "note": ""})

    members = {}                                     # collection name -> set of media ids
    for r in raw["catalog"]:
        mid = str(r["media_id"])
        rs = str(r["rating"] or "")
        rating = min(5, int(rs)) if rs.isdigit() else 0
        cols = sorted(set(g._split_collections(r["collections"])), key=_fold)
        if rating or cols:
            it = item(mid)
            it["rating"] = rating
            it["collections"] = cols
        for c in cols:
            members.setdefault(c, set()).add(mid)
    for r in raw["personal"]:
        tags = g._split_tags(r["tags"])
        if tags or r["mark"] or r["note"]:
            it = item(str(r["media_id"]))
            it["tags"] = tags
            it["mark"] = r["mark"] or ""
            it["note"] = r["note"] or ""
    order = {}
    for r in raw["order"]:                           # already by name, then position
        name, mid = str(r["name"]), str(r["media_id"])
        if mid in members.get(name, ()):             # a picture that left keeps no position
            order.setdefault(name, []).append(mid)
    return {
        "format": FORMAT,
        "version": VERSION,
        "exported_at": now or _utc_now(),
        "items": [items[m] for m in sorted(items)],
        "collection_order": {n: order[n] for n in sorted(order, key=_fold)},
        "smart_collections": sorted(({"name": str(s["name"]), "query": str(s["query"])}
                                     for s in raw["smart"]), key=lambda s: _fold(s["name"])),
    }


def dumps(doc):
    """The canonical bytes of a document (as text): sorted keys, two-space indent."""
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def load(path):
    """Read a curation file. Refuses anything that is not JSON in plain words."""
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise CurationIOError("Could not read {}: {}".format(Path(path).name, e.strerror or e))
    except ValueError:
        raise CurationIOError("{} is not a curation file: it is not valid JSON.".format(Path(path).name))


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def _validate(doc):
    """The document, cleaned through the catalog's own rules, or CurationIOError."""
    from moonglade import gallery as g
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise CurationIOError("This is not a Moonglade curation file.")
    if doc.get("version") != VERSION:
        raise CurationIOError("This curation file is version {}; this app reads version {}."
                              .format(doc.get("version"), VERSION))
    items = doc.get("items")
    if not isinstance(items, list):
        raise CurationIOError("The file's items are not a list.")
    order = doc.get("collection_order", {})
    smart = doc.get("smart_collections", [])
    if not isinstance(order, dict):
        raise CurationIOError("The file's collection order is not a table of names.")
    if not isinstance(smart, list):
        raise CurationIOError("The file's smart collections are not a list.")

    clean, seen = [], set()
    for n, it in enumerate(items, 1):
        where = "Item {}".format(n)
        if not isinstance(it, dict):
            raise CurationIOError("{} is not a picture entry.".format(where))
        mid = str(it.get("media_id") or "").strip()
        if not mid:
            raise CurationIOError("{} has no media id.".format(where))
        if mid in seen:
            raise CurationIOError("Media id {} appears twice.".format(mid))
        seen.add(mid)
        where = "Picture {}".format(mid)
        try:
            rating = g._clean_rating(it.get("rating", 0) or 0)
            mark = g._clean_mark(it.get("mark"))
            note = g._clean_note(it.get("note"))
            raw_tags = it.get("tags") or []
            if not isinstance(raw_tags, list):
                raise g.CurationError("Its tags are not a list.")
            tags = []
            for t in raw_tags:
                t = g._clean_tag(t)
                if t not in tags:
                    tags.append(t)
            if len(tags) > g.PERSONAL_TAGS_MAX:
                raise g.CurationError("It has more than {} tags.".format(g.PERSONAL_TAGS_MAX))
            raw_cols = it.get("collections") or []
            if not isinstance(raw_cols, list):
                raise g.CurationError("Its collections are not a list.")
        except g.CurationError as e:
            raise CurationIOError("{}: {} ({})".format(where, e, _field_hint(str(e))))
        cols = []
        for c in raw_cols:
            c = g._clean_collection_name(c)
            if c and c not in cols:
                cols.append(c)
        clean.append({"media_id": mid, "rating": rating, "mark": mark, "note": note,
                      "tags": tags, "collections": cols})

    clean_order = {}
    for name, ids in order.items():
        cname = g._clean_collection_name(name)
        if not cname or not isinstance(ids, list):
            raise CurationIOError("The manual order for “{}” is not a list of pictures.".format(name))
        ids = [str(m).strip() for m in ids if str(m).strip()]
        if len(ids) > g.CURATE_MAX_IDS or len(set(ids)) != len(ids):
            raise CurationIOError("The manual order for “{}” repeats a picture or is too long."
                                  .format(cname))
        clean_order[cname] = ids

    clean_smart = []
    for s in smart:
        if (not isinstance(s, dict) or not str(s.get("name") or "").strip()
                or not " ".join(str(s.get("query") or "").split())):
            raise CurationIOError("A smart collection needs both a name and a search.")
        clean_smart.append({"name": g._clean_collection_name(s["name"]),
                            "query": " ".join(str(s["query"]).split())})
    return clean, clean_order, clean_smart


def _field_hint(msg):
    m = msg.lower()
    for word in ("rating", "mark", "note", "tag"):
        if word in m:
            return "its " + ("tags" if word == "tag" else word)
    return "a value"


def _chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def import_curation(db_path, doc, apply=False, overwrite=False):
    """Apply (or, by default, plan) a curation document against this catalog. Returns the
    report: what would change / changed, the unknown media ids, what was skipped and why,
    and the pre-import snapshot's file name (apply only)."""
    from moonglade import gallery as g
    items, order, smart = _validate(doc)
    db_path = Path(db_path)

    ids = [it["media_id"] for it in items]
    known = {str(r["media_id"]): r for r in g.rows_for_media_ids(db_path, ids)}
    order_ids = [m for v in order.values() for m in v]
    known_order = {str(r["media_id"]) for r in g.rows_for_media_ids(db_path, order_ids)}
    unknown = sorted({m for m in ids if m not in known}
                     | {m for m in order_ids if m not in known_order and m not in known})
    personal = g.personal_get(db_path, list(known))

    # --- the personal layer and the rating: one full state per picture ------------
    states, ratings, marks, notes, tags_added, tags_refused = {}, 0, 0, 0, 0, 0
    for it in items:
        mid = it["media_id"]
        if mid not in known:
            continue
        rs = str(known[mid].get("rating") or "")
        cur = {"rating": min(5, int(rs)) if rs.isdigit() else 0}
        p = personal.get(mid) or {}
        cur.update(mark=p.get("mark", ""), note=p.get("note", ""), tags=list(p.get("tags", [])))
        new = dict(cur, tags=list(cur["tags"]))
        for key in ("rating", "mark", "note"):
            if overwrite or not cur[key]:
                if it[key] or overwrite:
                    new[key] = it[key]
        if overwrite:
            new["tags"] = list(it["tags"])
        else:
            for t in it["tags"]:
                if t in new["tags"]:
                    continue
                if len(new["tags"]) >= g.PERSONAL_TAGS_MAX:
                    tags_refused += 1
                    continue
                new["tags"].append(t)
        if new == cur:
            continue
        ratings += new["rating"] != cur["rating"]
        marks += new["mark"] != cur["mark"]
        notes += new["note"] != cur["note"]
        tags_added += len([t for t in new["tags"] if t not in cur["tags"]])
        states[mid] = new

    # --- collections: unioned; under overwrite, the document's list exactly ----------
    hand_now = set(g.unique_collections(db_path))
    smart_now = {s["name"].casefold(): s for s in g.list_smart_collections(db_path)}
    labels, unlabels, label_skipped = {}, {}, []
    for it in items:
        mid = it["media_id"]
        if mid not in known:
            continue
        have = g._split_collections(known[mid].get("collections"))
        want = []
        for c in it["collections"]:
            if c.casefold() in smart_now:
                if c not in label_skipped:
                    label_skipped.append(c)
                continue
            want.append(c)
            if c not in have:
                labels.setdefault(c, []).append(mid)
        if overwrite:
            for c in have:
                if c not in want:
                    unlabels.setdefault(c, []).append(mid)
    label_count = sum(len(v) for v in labels.values())
    unlabel_count = sum(len(v) for v in unlabels.values())

    # --- smart collections -------------------------------------------------------
    taken = {n.casefold() for n in hand_now | set(labels)}
    smart_created, smart_same, smart_skipped = [], [], []
    for s in smart:
        low = s["name"].casefold()
        if low in smart_now:
            (smart_same if smart_now[low]["query"] == s["query"] else smart_skipped).append(s["name"])
        elif low in taken:
            smart_skipped.append(s["name"])
        else:
            smart_created.append(s["name"])

    # --- manual orders -------------------------------------------------------------
    orders_set, orders_kept, orders_skipped = [], [], []
    plan_orders = {}
    for name, oids in order.items():
        oids = [m for m in oids if m in known_order or m in known]
        is_hand_after = name in hand_now or name in labels
        if not oids or name.casefold() in smart_now or not is_hand_after:
            orders_skipped.append(name)
            continue
        if name in hand_now and g.ordered_members(db_path, name)["manual"] and not overwrite:
            orders_kept.append(name)
            continue
        plan_orders[name] = oids
        orders_set.append(name)

    report = {
        "apply": bool(apply), "overwrite": bool(overwrite),
        "items": len(items), "unknown": unknown,
        "ratings": ratings, "marks": marks, "notes": notes,
        "tags_added": tags_added, "tags_refused": tags_refused,
        "collection_labels": label_count, "collection_labels_removed": unlabel_count,
        "labels_skipped": label_skipped,
        "smart_created": smart_created, "smart_unchanged": smart_same,
        "smart_skipped": smart_skipped,
        "orders_set": orders_set, "orders_kept": orders_kept, "orders_skipped": orders_skipped,
        "snapshot": None,
    }
    if not apply:
        return report

    # --- apply: snapshot first, then the existing verbs ---------------------------
    # The snapshot is the import's undo file: an owner decision that cannot be made again
    # (like the organize undo list), so it goes with the decisions (decisions_path()).
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    library = Path(db_path).parent
    snap = _paths.decisions_path(library, "{}{}.json".format(SNAPSHOT_PREFIX, stamp))
    n = 2
    while snap.exists():
        snap = _paths.decisions_path(library, "{}{}-{}.json".format(SNAPSHOT_PREFIX, stamp, n))
        n += 1
    before = export_curation(db_path)
    touched = (set(states) | {m for v in labels.values() for m in v}
               | {m for v in unlabels.values() for m in v})
    listed = {it["media_id"] for it in before["items"]}
    before["items"] = sorted(
        before["items"] + [{"media_id": m, "rating": 0, "collections": [], "tags": [],
                            "mark": "", "note": ""} for m in touched - listed],
        key=lambda it: it["media_id"])
    snap.write_text(dumps(before), encoding="utf-8")
    report["snapshot"] = snap.name

    for chunk in _chunks(states.items(), g.CURATE_MAX_IDS):
        g.curate_restore(db_path, dict(chunk))
    for name, mids in labels.items():
        for chunk in _chunks(mids, g.CURATE_MAX_IDS):
            g.add_to_collection(db_path, chunk, name)
    for name, mids in unlabels.items():
        for chunk in _chunks(mids, g.CURATE_MAX_IDS):
            g.remove_from_collection(db_path, chunk, name)
    for s in smart:
        if s["name"] in smart_created:
            try:
                g.save_smart_collection(db_path, s["query"], name=s["name"])
            except g.CurationError:
                smart_created.remove(s["name"])
                smart_skipped.append(s["name"])
    for name, oids in plan_orders.items():
        members = {str(r["media_id"]) for r in g.rows_for_media_ids(db_path, oids)
                   if name in g._split_collections(r.get("collections"))}
        try:
            g.set_collection_order(db_path, name, [m for m in oids if m in members])
        except g.CurationError:
            orders_set.remove(name)
            orders_skipped.append(name)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run_export_cli(out_dir, db_path, target=""):
    out = Path(out_dir)
    path = Path(target) if target else out / "curation_{}.json".format(
        time.strftime("%Y%m%d-%H%M%S", time.gmtime()))
    doc = export_curation(db_path)
    path.write_text(dumps(doc), encoding="utf-8")
    print("Curation exported -> {}".format(path))
    print("  {} pictures with a rating, collection, tag, mark or note; {} manual orders; "
          "{} smart collections".format(len(doc["items"]), len(doc["collection_order"]),
                                        len(doc["smart_collections"])))
    return path


def run_import_cli(out_dir, db_path, source, apply=False, overwrite=False):
    doc = load(source)
    rep = import_curation(db_path, doc, apply=apply, overwrite=overwrite)
    head = "Imported" if apply else "Dry run -- nothing changed. An --apply would import"
    print("{} curation from {} ({}):".format(
        head, Path(source).name, "overwrite" if overwrite else "fill-only"))
    print("  ratings {}, marks {}, notes {}, tags added {}, collection labels added {}{}".format(
        rep["ratings"], rep["marks"], rep["notes"], rep["tags_added"], rep["collection_labels"],
        ", removed {}".format(rep["collection_labels_removed"]) if overwrite else ""))
    if rep["tags_refused"]:
        print("  {} tags not added: those pictures already hold the most tags allowed".format(
            rep["tags_refused"]))
    for key, words in (("smart_created", "smart collections created"),
                       ("smart_skipped", "smart collections skipped (the name is taken)"),
                       ("labels_skipped", "collection names skipped (a smart collection has it)"),
                       ("orders_set", "manual orders set"),
                       ("orders_kept", "manual orders kept as they are (add --curation-overwrite)"),
                       ("orders_skipped", "manual orders skipped")):
        if rep[key]:
            print("  {}: {}".format(words, ", ".join(rep[key])))
    if rep["unknown"]:
        print("  {} pictures are not in this catalog -- import again after a sync: {}".format(
            len(rep["unknown"]), ", ".join(rep["unknown"][:20])
            + (" ..." if len(rep["unknown"]) > 20 else "")))
    if rep["snapshot"]:
        print("  The state before this import was saved to {} (import it with "
              "--curation-overwrite to undo).".format(rep["snapshot"]))
    return rep
