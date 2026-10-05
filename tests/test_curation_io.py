"""The curation sidecar (moonglade_curation_io.py; scope item 4): everything the owner authored
-- ratings, hand-picked collections and their manual order, smart collections, and the personal
layer (tags, keeper/reject, notes) -- exported as one small JSON keyed by media id, and
imported back into a catalog rebuilt from a fresh re-pull.

Library-level data only (owner question 1, option a): the per-account files (view presets,
snippets, Toolbox presets, prefs) are keyed by a hash of a login name and are not part of it.

Import is dry-run by default, fill-only by default (never overwrites a rating, mark or note the
catalog already has; tags and collections are unioned), writes only through the existing
curation verbs, refuses a malformed or foreign document before writing anything, reports media
ids this catalog does not have instead of inventing rows (option a), and saves an export of the
current state first so an import can itself be undone.
"""
import hashlib
import json
import sqlite3
import sys

import pytest

from moonglade import backup as core
from moonglade import curation_io as cio
from moonglade import gallery as g
from moonglade.gallery import CATALOG_FIELDS, save_catalog

from tests.conftest import login_client

NOW = "2026-10-02T12:00:00Z"
IDS = ["m1", "m2", "m3", "m4", "m5"]


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _fresh(path, ids=IDS):
    """A catalog holding these pictures and no curation at all -- a fresh re-pull."""
    path.parent.mkdir(parents=True, exist_ok=True)
    save_catalog(path, [_row(media_id=m, filename="p_t_{}.png".format(m),
                             created_at="2024-01-0{}".format(i + 1)) for i, m in enumerate(ids)])
    return path


def _curated(path):
    db = _fresh(path)
    g.update_rating(db, "m1", 5)
    g.update_rating(db, "m2", 3)
    g.add_to_collection(db, ["m1", "m3"], "Night Sky")
    g.add_to_collection(db, ["m1"], "Best Of")
    g.curate_apply(db, ["m2"], {"add_tag": "pose-study"})
    g.curate_apply(db, ["m2"], {"add_tag": "blue"})
    g.curate_apply(db, ["m2"], {"mark": "keeper"})
    g.curate_apply(db, ["m2"], {"note": "the one"})
    g.curate_apply(db, ["m3"], {"mark": "reject"})
    g.save_smart_collection(db, "cat ★4+", name="Cats")
    g.set_collection_order(db, "Night Sky", ["m3", "m1"])
    return db


def _tables_hash(db):
    con = sqlite3.connect(str(db))
    try:
        h = hashlib.sha256()
        for t in ("catalog", "personal_meta", "smart_collections", "collection_order"):
            for r in con.execute("SELECT * FROM {} ORDER BY 1, 2".format(t)):
                h.update(repr(tuple(r)).encode())
        return h.hexdigest()
    finally:
        con.close()


def test_the_export_holds_the_owners_layer_and_nothing_else(tmp_path):
    doc = cio.export_curation(_curated(tmp_path / "a" / "catalog.db"), now=NOW)
    assert doc["format"] == "moonglade-curation" and doc["version"] == 1
    assert doc["exported_at"] == NOW
    items = {it["media_id"]: it for it in doc["items"]}
    assert set(items) == {"m1", "m2", "m3"}                      # m4/m5 carry nothing
    assert items["m1"] == {"media_id": "m1", "rating": 5, "collections": ["Best Of", "Night Sky"],
                           "tags": [], "mark": "", "note": ""}
    assert items["m2"]["tags"] == ["pose-study", "blue"]
    assert items["m2"]["mark"] == "keeper" and items["m2"]["note"] == "the one"
    assert doc["collection_order"] == {"Night Sky": ["m3", "m1"]}
    assert doc["smart_collections"] == [{"name": "Cats", "query": "cat ★4+"}]


def test_export_import_export_is_byte_identical(tmp_path):
    doc = cio.export_curation(_curated(tmp_path / "a" / "catalog.db"), now=NOW)
    first = cio.dumps(doc)
    fresh = _fresh(tmp_path / "b" / "catalog.db")
    rep = cio.import_curation(fresh, json.loads(first), apply=True)
    assert rep["unknown"] == []
    assert cio.dumps(cio.export_curation(fresh, now=NOW)) == first


def test_a_dry_run_changes_nothing_and_says_what_it_would_do(tmp_path):
    doc = cio.export_curation(_curated(tmp_path / "a" / "catalog.db"), now=NOW)
    fresh = _fresh(tmp_path / "b" / "catalog.db")
    before = _tables_hash(fresh)
    rep = cio.import_curation(fresh, doc)
    assert rep["apply"] is False
    assert _tables_hash(fresh) == before
    assert rep["ratings"] == 2 and rep["marks"] == 2 and rep["notes"] == 1
    assert rep["tags_added"] == 2 and rep["collection_labels"] == 3
    assert rep["smart_created"] == ["Cats"] and rep["orders_set"] == ["Night Sky"]
    assert rep["snapshot"] is None
    assert list((tmp_path / "b").glob("curation_pre_import_*.json")) == []


def test_fill_only_keeps_what_the_catalog_already_has(tmp_path):
    doc = cio.export_curation(_curated(tmp_path / "a" / "catalog.db"), now=NOW)
    b = _fresh(tmp_path / "b" / "catalog.db")
    g.update_rating(b, "m2", 1)
    g.curate_apply(b, ["m2"], {"note": "mine"})
    g.curate_apply(b, ["m2"], {"add_tag": "red"})
    cio.import_curation(b, doc, apply=True)
    st = g.personal_get(b, ["m2"])["m2"]
    assert g.get_row(b, "m2")["rating"] == "1"                  # kept
    assert st["note"] == "mine"                                 # kept
    assert st["mark"] == "keeper"                               # was empty: filled
    assert st["tags"] == ["red", "pose-study", "blue"]          # unioned


def test_overwrite_makes_the_document_win_for_the_pictures_it_lists(tmp_path):
    doc = cio.export_curation(_curated(tmp_path / "a" / "catalog.db"), now=NOW)
    b = _fresh(tmp_path / "b" / "catalog.db")
    g.update_rating(b, "m2", 1)
    g.curate_apply(b, ["m2"], {"note": "mine"})
    g.curate_apply(b, ["m2"], {"add_tag": "red"})
    g.add_to_collection(b, ["m2", "m4"], "Mine")
    rep = cio.import_curation(b, doc, apply=True, overwrite=True)
    st = g.personal_get(b, ["m2"])["m2"]
    assert g.get_row(b, "m2")["rating"] == "3"
    assert st["note"] == "the one" and st["tags"] == ["pose-study", "blue"]
    assert g.get_row(b, "m2")["collections"] == ""              # the file lists none for m2
    assert g.get_row(b, "m4")["collections"] == "Mine"          # m4 is not in the file
    assert rep["collection_labels_removed"] == 1
    assert len(g.load_catalog(b)) == len(IDS)                   # a label, never a picture


def test_unknown_media_ids_are_reported_not_invented(tmp_path):
    doc = cio.export_curation(_curated(tmp_path / "a" / "catalog.db"), now=NOW)
    doc["items"].append({"media_id": "ghost", "rating": 4, "collections": ["Night Sky"],
                         "tags": ["x"], "mark": "", "note": ""})
    doc["collection_order"]["Night Sky"].append("ghost")
    b = _fresh(tmp_path / "b" / "catalog.db")
    rep = cio.import_curation(b, doc, apply=True)
    assert rep["unknown"] == ["ghost"]
    assert g.get_row(b, "ghost") is None
    assert g.personal_get(b, ["ghost"]) == {}
    assert g.ordered_members(b, "Night Sky")["media_ids"][:2] == ["m3", "m1"]


def test_the_tag_cap_holds(tmp_path):
    b = _fresh(tmp_path / "b" / "catalog.db")
    for i in range(g.PERSONAL_TAGS_MAX - 1):
        g.curate_apply(b, ["m1"], {"add_tag": "t{}".format(i)})
    doc = {"format": "moonglade-curation", "version": 1, "exported_at": NOW,
           "items": [{"media_id": "m1", "rating": 0, "collections": [], "tags": ["new-a", "new-b"],
                      "mark": "", "note": ""}],
           "collection_order": {}, "smart_collections": []}
    rep = cio.import_curation(b, doc, apply=True)
    assert rep["tags_refused"] == 1
    tags = g.personal_get(b, ["m1"])["m1"]["tags"]
    assert len(tags) == g.PERSONAL_TAGS_MAX and "new-a" in tags and "new-b" not in tags


def test_a_smart_collection_name_clash_is_skipped_and_reported(tmp_path):
    doc = cio.export_curation(_curated(tmp_path / "a" / "catalog.db"), now=NOW)
    b = _fresh(tmp_path / "b" / "catalog.db")
    g.save_smart_collection(b, "dog", name="Cats")              # same name, another search
    rep = cio.import_curation(b, doc, apply=True)
    assert rep["smart_skipped"] == ["Cats"]
    assert g.smart_collection_query(b, "Cats") == "dog"         # left alone


def test_an_existing_manual_order_is_kept_unless_overwriting(tmp_path):
    doc = cio.export_curation(_curated(tmp_path / "a" / "catalog.db"), now=NOW)
    b = _fresh(tmp_path / "b" / "catalog.db")
    g.add_to_collection(b, ["m1", "m3"], "Night Sky")
    g.set_collection_order(b, "Night Sky", ["m1", "m3"])
    rep = cio.import_curation(b, doc, apply=True)
    assert rep["orders_kept"] == ["Night Sky"]
    assert g.ordered_members(b, "Night Sky")["media_ids"] == ["m1", "m3"]
    cio.import_curation(b, doc, apply=True, overwrite=True)
    assert g.ordered_members(b, "Night Sky")["media_ids"] == ["m3", "m1"]


@pytest.mark.parametrize("mutate, words", [
    (lambda d: d.update(version=2), "version"),
    (lambda d: d.update(format="something-else"), "not a Moonglade curation file"),
    (lambda d: d.update(items="nope"), "items"),
    (lambda d: d["items"][0].update(rating=7), "rating"),
    (lambda d: d["items"][0].update(mark="maybe"), "mark"),
    (lambda d: d["items"][0].update(note="x" * (g.PERSONAL_NOTE_MAX + 1)), "note"),
    (lambda d: d["items"][0].update(tags=["t{}".format(i) for i in range(g.PERSONAL_TAGS_MAX + 1)]), "tags"),
    (lambda d: d["items"][0].update(media_id=""), "media id"),
    (lambda d: d.update(smart_collections=[{"name": "x"}]), "smart collection"),
])
def test_a_malformed_document_is_refused_in_plain_words(tmp_path, mutate, words):
    doc = cio.export_curation(_curated(tmp_path / "a" / "catalog.db"), now=NOW)
    mutate(doc)
    b = _fresh(tmp_path / "b" / "catalog.db")
    before = _tables_hash(b)
    with pytest.raises(cio.CurationIOError) as e:
        cio.import_curation(b, doc, apply=True)
    assert words.lower() in str(e.value).lower()
    assert _tables_hash(b) == before
    assert list((tmp_path / "b").glob("curation_pre_import_*.json")) == []


def test_not_json_at_all_is_refused(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(cio.CurationIOError):
        cio.load(p)


def test_apply_saves_the_current_state_first_and_that_undoes_the_import(tmp_path):
    doc = cio.export_curation(_curated(tmp_path / "a" / "catalog.db"), now=NOW)
    b = _fresh(tmp_path / "b" / "catalog.db")
    g.update_rating(b, "m4", 2)
    g.add_to_collection(b, ["m2"], "Mine")
    before = cio.export_curation(b, now=NOW)["items"]
    rep = cio.import_curation(b, doc, apply=True)
    snap = tmp_path / "b" / rep["snapshot"]
    assert snap.name.startswith("curation_pre_import_") and snap.exists()
    assert cio.export_curation(b, now=NOW)["items"] != before
    # the snapshot, imported with overwrite, puts every touched picture back
    cio.import_curation(b, cio.load(snap), apply=True, overwrite=True)
    assert cio.export_curation(b, now=NOW)["items"] == before


# ---------------------------------------------------------------------------
# The download route and the CLI
# ---------------------------------------------------------------------------

def test_the_download_route(tmp_path):
    _curated(tmp_path / "catalog.db")
    r = login_client(tmp_path).get("/export-curation")
    assert r.status_code == 200
    assert "attachment" in r.headers["Content-Disposition"]
    assert "moonglade-curation-" in r.headers["Content-Disposition"]
    doc = json.loads(r.get_data(as_text=True))
    assert doc["format"] == "moonglade-curation"
    assert {it["media_id"] for it in doc["items"]} == {"m1", "m2", "m3"}


def test_the_cli_round_trip(tmp_path, monkeypatch, capsys):
    a = tmp_path / "a"
    _curated(a / "catalog.db")
    target = tmp_path / "curation.json"
    monkeypatch.setattr(sys, "argv", ["prog", "--export-curation", str(target), "--out", str(a)])
    core.main()
    assert cio.load(target)["format"] == "moonglade-curation"

    b = tmp_path / "b"
    _fresh(b / "catalog.db")
    before = _tables_hash(b / "catalog.db")
    monkeypatch.setattr(sys, "argv", ["prog", "--import-curation", str(target), "--out", str(b)])
    core.main()
    assert "dry run" in capsys.readouterr().out.lower()
    assert _tables_hash(b / "catalog.db") == before

    monkeypatch.setattr(sys, "argv", ["prog", "--import-curation", str(target), "--apply",
                                      "--out", str(b)])
    core.main()
    assert g.get_row(b / "catalog.db", "m1")["rating"] == "5"
