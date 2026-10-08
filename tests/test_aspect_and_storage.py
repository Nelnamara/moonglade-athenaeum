"""Session N (Curation), N6 and N7: the `ar:` search operator and Collection Health's three
storage bars.

WHERE THE WORK IS DONE. Both are answered by the SERVER, from the catalog and the folder, and
that is deliberate. The library is paginated, so a client-side `ar:` filter (what the design
page's stand-in does over its 24 sample pictures) would only ever see the page it holds; and the
bars' segments must each say how much the gallery will show when clicked, which only a query the
server itself runs can promise. These tests pin the two agreeing.

  * `ar:` reads the width and height already on every catalog row. Nothing is added to the
    catalog: no column, no table, no migration.
  * The Storage bars read bytes off the health walk's own stats. Nothing on this surface writes
    (the catalog file is byte-identical after a health read) or reaches the network.
"""
import hashlib
import json
import socket
from urllib.parse import quote

import pytest

from moonglade import paths as _paths
from moonglade import backup as core
from moonglade import gallery as g
from moonglade.gallery import (
    CATALOG_FIELDS, collection_health, loom_render_ids, query_catalog, save_catalog,
    storage_breakdown,
)
from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _ids(db, q, **kw):
    return sorted(r["media_id"] for r in query_catalog(db, q=q, page_size=None, **kw)[0])


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("the storage bars / ar: reached for the network")
    monkeypatch.setattr(socket.socket, "connect", _boom)
    for name in ("gql", "gql_adhoc", "gql_mutate", "_make_session"):
        if hasattr(core, name):
            monkeypatch.setattr(core, name, _boom)


# ---------------------------------------------------------------------------------------------
# N7: ar:
# ---------------------------------------------------------------------------------------------

SHAPES = {          # media_id -> (width, height): every named shape and the boundary cases
    "sq":    ("1024", "1024"),      # 1.000
    "sq2":   ("1000", "1028"),      # 0.973  (inside square)
    "sq3":   ("1000", "1040"),      # 0.962  (just outside square)
    "por":   ("832", "1216"),       # 0.684  portrait
    "lan":   ("1216", "832"),       # 1.462  landscape
    "t916":  ("576", "1024"),       # 0.5625 exactly 9:16
    "t1792": ("1024", "1792"),      # 0.5714 (inside tall's 0.005 of spare)
    "tall2": ("512", "1536"),       # 0.333  taller than 9:16
    "w169":  ("1920", "1080"),      # 1.778  exactly 16:9
    "wide2": ("2048", "1072"),      # 1.910
    "w32":   ("1536", "1024"),      # 1.5    exactly 3:2
    "w54":   ("1250", "1000"),      # 1.25   5:4
    "blank": ("", ""),              # an old import with no size
    "zeroh": ("800", "0"),          # a divide-by-zero waiting to happen
}


@pytest.fixture
def shapes(tmp_path):
    p = tmp_path / "catalog.db"
    save_catalog(p, [
        _row(media_id=mid, filename=mid + ".png", width=w, height=h,
             created_at="2026-07-%02dT12:00:00" % (i + 1))
        for i, (mid, (w, h)) in enumerate(SHAPES.items())
    ])
    return p


def test_square_portrait_landscape(shapes):
    assert _ids(shapes, "ar:square") == ["sq", "sq2"]
    # portrait is simply "below 1" (the page's own rule), so a hair under square counts
    assert _ids(shapes, "ar:portrait") == sorted(["por", "sq2", "sq3", "t916", "t1792", "tall2"])
    assert _ids(shapes, "ar:landscape") == sorted(["lan", "w169", "wide2", "w32", "w54"])


def test_tall_and_wide_carry_the_pages_small_allowance(shapes):
    # 9:16 or taller, with the page's 0.005 to spare: 9:16 itself and 512x1536. 1024x1792
    # (0.571) is a little wider than 9:16 and past the allowance: near 9:16 by ar:9:16, not tall
    assert _ids(shapes, "ar:tall") == sorted(["t916", "tall2"])
    # 16:9 or wider, with 0.01 to spare
    assert _ids(shapes, "ar:wide") == sorted(["w169", "wide2"])


def test_w_h_is_within_three_percent(shapes):
    # 1216x832 is 1.4615: 2.6% under 3:2, inside the 3%; 1250x1000 is 16.7% off
    assert _ids(shapes, "ar:3:2") == ["lan", "w32"]
    assert _ids(shapes, "ar:1:1") == ["sq", "sq2"]          # 0.973 is 2.7% off; 0.962 is 3.8%
    assert _ids(shapes, "ar:9:16") == sorted(["t916", "t1792"])
    assert _ids(shapes, "ar:5:4") == ["w54"]
    assert _ids(shapes, "ar:1.5:1") == ["lan", "w32"]       # decimals are fine on either side


def test_greater_than_and_less_than_read_the_ratio(shapes):
    assert _ids(shapes, "ar:>1.7") == sorted(["w169", "wide2"])
    assert _ids(shapes, "ar:>2") == []
    assert _ids(shapes, "ar:<0.5") == ["tall2"]
    assert _ids(shapes, "ar:<0.6") == sorted(["t916", "t1792", "tall2"])


def test_an_unmeasured_picture_matches_no_shape_but_survives_a_negation(shapes):
    for shape in ("square", "portrait", "landscape", "tall", "wide", "3:2", ">1", "<1"):
        got = _ids(shapes, "ar:" + shape)
        assert "blank" not in got and "zeroh" not in got, shape
    # the unknown is not "tall": it is still there when tall is left out
    left = _ids(shapes, "-ar:tall")
    assert "blank" in left and "zeroh" in left
    assert "t916" not in left


def test_ar_combines_with_the_rest_of_the_search(shapes):
    assert _ids(shapes, "ar:landscape ar:>1.7") == sorted(["w169", "wide2"])
    assert _ids(shapes, "ar:landscape -ar:wide") == sorted(["lan", "w32", "w54"])


def test_a_malformed_value_degrades_to_a_plain_search_never_an_error(shapes):
    for bad in ("ar:", "ar:banana", "ar:0:0", "ar:3:", "ar:>", "ar:>x", "ar:1:0"):
        assert _ids(shapes, bad) == []          # searched as prompt text: nothing says it
    where, params = g._build_where("ar:banana", "", "", "")
    assert "banana" not in where.lower() or "?" in where       # the word is a bound parameter


def test_the_aspect_alias_and_the_case_of_the_value(shapes):
    assert _ids(shapes, "aspect:tall") == _ids(shapes, "ar:TALL") == _ids(shapes, "ar:tall")


def test_a_hostile_value_is_bound_never_interpolated(shapes):
    where, params = g._build_where('ar:3:2") OR 1=1 --', "", "", "")
    assert "OR 1=1" not in where
    assert _ids(shapes, 'ar:3:2") OR 1=1 --') == []
    where, _ = g._build_where("ar:>1;DROP TABLE catalog", "", "", "")
    assert "DROP" not in where


def test_ar_changes_no_schema(shapes):
    import sqlite3
    con = sqlite3.connect(str(shapes))
    before = [r[1] for r in con.execute("PRAGMA table_info(catalog)")]
    con.close()
    _ids(shapes, "ar:tall")
    con = sqlite3.connect(str(shapes))
    assert [r[1] for r in con.execute("PRAGMA table_info(catalog)")] == before
    con.close()


# ---------------------------------------------------------------------------------------------
# N6: type:, the Loom's renders, and the storage breakdown
# ---------------------------------------------------------------------------------------------

def _board(cards, imported=()):
    return {"acts": [{"cards": [
        {"resultMid": mid, "attempts": [{"media_id": a} for a in attempts]}
        for mid, attempts in cards
    ] + [{"resultMid": mid, "imported": True} for mid in imported]}]}


def _write_board(out_dir, project, key="storyboard:v2:proj:p1", account=None, as_string=True):
    d = _paths.loom_root(out_dir) / "kv"
    if account:
        d = d / account
    d.mkdir(parents=True, exist_ok=True)
    body = json.dumps(project)
    (d / (quote(key, safe="") + ".json")).write_text(
        json.dumps(body) if as_string else body, encoding="utf-8")


def test_the_loom_render_ids_are_results_and_kept_attempts_not_imported_footage(tmp_path):
    _write_board(tmp_path, _board([("m1", ["m1a", "m1b"]), ("m2", [])], imported=["m9"]))
    _write_board(tmp_path, _board([("m3", [])]), key="storyboard:v2:proj:p2", account="ab12")
    _write_board(tmp_path, _board([("mX", [])]), key="storyboard:v2:active")         # not a board
    _write_board(tmp_path, _board([("m4", [])]), key="storyboard:v2:proj:p3", as_string=False)
    assert loom_render_ids(tmp_path) == frozenset({"m1", "m1a", "m1b", "m2", "m3", "m4"})


def test_no_loom_folder_is_simply_no_renders(tmp_path):
    assert loom_render_ids(tmp_path) == frozenset()
    (_paths.loom_root(tmp_path) / "kv").mkdir(parents=True)
    (_paths.loom_root(tmp_path) / "kv" / "storyboard%3Av2%3Aproj%3Abad.json").write_text("{not json")
    assert loom_render_ids(tmp_path) == frozenset()


def test_the_loom_ids_follow_a_board_that_changes(tmp_path):
    _write_board(tmp_path, _board([("m1", [])]))
    assert loom_render_ids(tmp_path) == frozenset({"m1"})
    _write_board(tmp_path, _board([("m1", []), ("m2", [])]))
    assert loom_render_ids(tmp_path) == frozenset({"m1", "m2"})


def _files(out_dir, spec):
    """spec: {filename: bytes}"""
    for name, n in spec.items():
        (out_dir / name).write_bytes(b"x" * n)


@pytest.fixture
def lib(tmp_path):
    """A small library on disk: images, two videos (one a Loom render), a Loom still, three
    models, and collections that overlap."""
    spec = {"a.png": 1000, "b.png": 2000, "c.png": 3000, "d.png": 4000, "e.png": 500,
            "v1.mp4": 50000, "v2.mp4": 70000, "loomstill.png": 9000, "gone.png": 0}
    _files(tmp_path, {k: v for k, v in spec.items() if k != "gone.png"})
    _write_board(tmp_path, _board([("v2", []), ("loomstill", [])]))
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="a", filename="a.png", model_name="Tsubaki.3", collections="Druid,Faves",
             created_at="2026-07-01T00:00:00"),
        _row(media_id="b", filename="b.png", model_name="Tsubaki.3", collections="Druid",
             created_at="2026-07-02T00:00:00"),
        _row(media_id="c", filename="c.png", model_name="Lucent Mix", collections="Faves",
             created_at="2026-07-03T00:00:00"),
        _row(media_id="d", filename="d.png", model_name="", created_at="2026-07-04T00:00:00"),
        _row(media_id="e", filename="e.png", model_name="Tsubaki.2", collections="Contest",
             created_at="2026-07-05T00:00:00"),
        _row(media_id="v1", filename="v1.mp4", is_video="1", model_name="Seedance",
             created_at="2026-07-06T00:00:00"),
        _row(media_id="v2", filename="v2.mp4", is_video="1", model_name="Seedance",
             collections="Loom stills", created_at="2026-07-07T00:00:00"),
        _row(media_id="loomstill", filename="loomstill.png", model_name="Tsubaki.3",
             created_at="2026-07-08T00:00:00"),
        # a catalog row whose file is not on disk takes no space we can measure
        _row(media_id="gone", filename="gone.png", model_name="Tsubaki.3",
             created_at="2026-07-09T00:00:00"),
    ])
    return tmp_path, db


def test_type_partitions_the_library(lib):
    out, db = lib
    assert _ids(db, "type:image") == ["a", "b", "c", "d", "e", "gone"]
    assert _ids(db, "type:video") == ["v1"]              # v2 is a Loom render, so it is a loom
    assert _ids(db, "type:loom") == ["loomstill", "v2"]
    every = set(_ids(db, "type:image")) | set(_ids(db, "type:video")) | set(_ids(db, "type:loom"))
    assert every == set(_ids(db, ""))
    assert _ids(db, "-type:loom type:video") == ["v1"]
    assert _ids(db, "type:banana") == []                  # malformed: searched as text


def test_a_search_reads_the_looms_boards_once_not_once_per_row(lib, monkeypatch):
    out, db = lib
    calls = []
    real = g.loom_render_ids
    monkeypatch.setattr(g, "loom_render_ids", lambda d: (calls.append(1), real(d))[1])
    assert _ids(db, "type:image")                       # a handful of rows, each asking
    assert len(calls) == 1


def test_the_type_operator_needs_no_loom_folder(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [_row(media_id="1", filename="1.png"),
                      _row(media_id="2", filename="2.mp4", is_video="1")])
    assert _ids(db, "type:loom") == []
    assert _ids(db, "type:image") == ["1"] and _ids(db, "type:video") == ["2"]


def test_the_breakdown_measures_bytes_on_disk(lib):
    out, db = lib
    st = collection_health(out, db)["storage"]
    assert st["files"] == 8                                  # "gone" has no file
    assert st["total_bytes"] == 1000 + 2000 + 3000 + 4000 + 500 + 50000 + 70000 + 9000
    t = {s["key"]: s for s in st["by_type"]}
    assert (t["image"]["bytes"], t["image"]["count"]) == (10500, 5)
    assert (t["video"]["bytes"], t["video"]["count"]) == (50000, 1)
    assert (t["loom"]["bytes"], t["loom"]["count"]) == (79000, 2)
    assert sum(s["bytes"] for s in st["by_type"]) == st["total_bytes"]


def test_the_model_bar_is_the_top_four_then_other(lib):
    out, db = lib
    st = collection_health(out, db)["storage"]
    names = [s["name"] for s in st["by_model"]]
    # Seedance 120000, Tsubaki.3 12000 (a+b+loomstill), Tsubaki.2 500, Lucent Mix 3000, none 4000
    assert names[:4] == ["Seedance", "Tsubaki.3", "Lucent Mix", "Tsubaki.2"]
    assert names[4] == "Other" and st["by_model"][4]["other"] is True
    assert st["by_model"][4]["bytes"] == 4000                # the picture with no model
    assert sum(s["bytes"] for s in st["by_model"]) == st["total_bytes"]


def test_the_collection_bar_can_overlap_and_says_how(lib):
    out, db = lib
    coll = collection_health(out, db)["storage"]["by_collection"]
    got = {s["name"]: s["bytes"] for s in coll["segments"]}
    assert got["Druid"] == 1000 + 2000
    assert got["Faves"] == 1000 + 3000                        # a is in Druid AND Faves
    assert got["Loom stills"] == 70000
    assert got["Contest"] == 500
    assert coll["sum_bytes"] == sum(got.values()) > 0
    assert sum(got.values()) > 1000 + 2000 + 3000 + 500 + 70000 - 1     # a counted twice


def test_more_than_four_collections_fold_into_other():
    rows = [{"media_id": str(i), "filename": "f%d.png" % i, "is_video": "", "model_name": "M",
             "collections": "C%d" % i} for i in range(7)]
    sizes = {"f%d.png" % i: 100 * (i + 1) for i in range(7)}
    seg = storage_breakdown(rows, sizes, frozenset())["by_collection"]["segments"]
    assert [s["name"] for s in seg] == ["C6", "C5", "C4", "C3", "Other"]
    assert seg[-1]["bytes"] == 100 + 200 + 300 and seg[-1]["other"] is True


def test_a_segment_says_what_the_gallery_will_show_when_it_is_clicked(lib):
    """The point of doing this on the server: a segment's count is the count of the search its
    click opens."""
    out, db = lib
    st = collection_health(out, db)["storage"]
    for s in st["by_type"]:
        opened = [r for r in query_catalog(db, q="type:" + s["key"], page_size=None)[0]
                  if (out / r["filename"]).exists()]
        assert len(opened) == s["count"], s["key"]
    for s in st["by_model"]:
        if s["other"]:
            continue
        opened = [r for r in query_catalog(db, q='model:"%s"' % s["name"], page_size=None)[0]
                  if (out / r["filename"]).exists()]
        assert len(opened) == s["count"], s["name"]
    for s in st["by_collection"]["segments"]:
        if s["other"]:
            continue
        opened = [r for r in query_catalog(db, collection=s["name"], page_size=None)[0]
                  if (out / r["filename"]).exists()]
        assert len(opened) == s["count"], s["name"]


def test_an_empty_library_has_empty_bars(tmp_path):
    db = tmp_path / "catalog.db"
    save_catalog(db, [])
    st = collection_health(tmp_path, db)["storage"]
    assert st["total_bytes"] == 0 and st["files"] == 0
    assert all(s["bytes"] == 0 for s in st["by_type"])
    assert st["by_model"] == [] and st["by_collection"]["segments"] == []


def test_a_backslash_filename_still_finds_its_file():
    rows = [{"media_id": "1", "filename": "2026-07\\a.png", "is_video": "", "model_name": "M",
             "collections": ""}]
    assert storage_breakdown(rows, {"2026-07/a.png": 7}, frozenset())["total_bytes"] == 7


@pytest.fixture
def real_layout(tmp_path):
    """The library as it really sits on disk (owner walk 2026-09-29: the bars counted 263 of
    37,535 pictures). Older rows hold the BARE file name while the file sits in images/;
    newer ones hold a path relative to the library (videos/..., images/..., imported/...). One
    picture also has a second copy in a month folder, and one file on disk has no row."""
    for rel, n in {
        "images/night_elf_druid_1674_111.webp": 1000,      # row holds the bare name
        "images/moonlit_library_1675_222.webp": 2000,      # row holds the bare name
        "images/newer_row_1676_333.webp": 3000,            # row holds images/<name>
        "2026-07/night_elf_druid_1674_111.webp": 400,      # a smaller second copy of 111
        "videos/a_walk_in_the_glade_1677_900.mp4": 50000,  # row holds videos/<name>
        "imported/749_mg_moonglade_local_ab12.png": 700,   # a local import, row holds imported/<name>
        "images/stray_1678_999.webp": 99,                  # on disk, never catalogued
    }.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * n)
    db = tmp_path / "catalog.db"
    save_catalog(db, [
        _row(media_id="111", filename="night_elf_druid_1674_111.webp", model_name="Tsubaki.3",
             collections="Druid", created_at="2026-07-01T00:00:00"),
        _row(media_id="222", filename="moonlit_library_1675_222.webp", model_name="Lucent Mix",
             created_at="2026-07-02T00:00:00"),
        _row(media_id="333", filename="images/newer_row_1676_333.webp", model_name="Tsubaki.3",
             source="api", created_at="2026-07-03T00:00:00"),
        _row(media_id="900", filename="videos/a_walk_in_the_glade_1677_900.mp4", is_video="1",
             model_name="Seedance", created_at="2026-07-04T00:00:00"),
        _row(media_id="local_ab12", filename="imported/749_mg_moonglade_local_ab12.png",
             source="local", created_at="2026-07-05T00:00:00"),
        _row(media_id="gone", filename="gone_1679_gone.webp", created_at="2026-07-06T00:00:00"),
    ])
    return tmp_path, db


def test_a_bare_filename_row_is_measured_through_its_media_id(real_layout):
    """The 263-picture bug: only rows whose `filename` was a relative path were measured."""
    out, db = real_layout
    h = collection_health(out, db)
    st = h["storage"]
    t = {s["key"]: s for s in st["by_type"]}
    # every catalogued image with a file: 111 (at its larger copy), 222, 333 and the import
    assert (t["image"]["count"], t["image"]["bytes"]) == (4, 1000 + 2000 + 3000 + 700)
    assert (t["video"]["count"], t["video"]["bytes"]) == (1, 50000)
    assert st["files"] == 5 and st["total_bytes"] == 56700
    # and it agrees with "Images on disk": every image file, less the second copy of 111
    # (Duplicates) and the one file no row names
    assert t["image"]["count"] == h["total_files"] - h["dup_redundant"] - 1
    models = {s["name"]: s["bytes"] for s in st["by_model"]}
    assert models["Tsubaki.3"] == 1000 + 3000 and models["Lucent Mix"] == 2000
    assert {s["name"]: s["bytes"] for s in st["by_collection"]["segments"]} == {"Druid": 1000}


def test_a_media_id_match_stays_in_its_own_kind():
    """A video row never takes an image's bytes (or the reverse) just because the ids agree."""
    rows = [{"media_id": "5", "filename": "clip_5.mp4", "is_video": "1", "model_name": "",
             "collections": ""},
            {"media_id": "6", "filename": "pic_6.webp", "is_video": "", "model_name": "",
             "collections": ""}]
    st = storage_breakdown(rows, {}, frozenset(), {("image", "5"): 10, ("video", "6"): 20})
    assert st["files"] == 0 and st["total_bytes"] == 0
    st = storage_breakdown(rows, {}, frozenset(), {("video", "5"): 10, ("image", "6"): 20})
    assert st["files"] == 2 and st["total_bytes"] == 30


def test_the_relative_path_wins_over_the_media_id():
    rows = [{"media_id": "7", "filename": "images/p_7.webp", "is_video": "", "model_name": "M",
             "collections": ""}]
    st = storage_breakdown(rows, {"images/p_7.webp": 5}, frozenset(), {("image", "7"): 900})
    assert st["total_bytes"] == 5


def test_reading_health_writes_nothing(lib):
    out, db = lib
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    files = sorted(p.name for p in out.rglob("*") if p.is_file())
    collection_health(out, db)
    query_catalog(db, q="type:loom ar:tall", page_size=None)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in out.rglob("*") if p.is_file()) == files


def test_the_health_route_carries_the_storage_block(lib):
    out, db = lib
    client = login_client(out)
    d = client.get("/api/health?fresh=1").get_json()
    assert d["storage"]["total_bytes"] == 139500
    assert {s["key"] for s in d["storage"]["by_type"]} == {"image", "video", "loom"}
    # the old single number is still served for anything that reads it
    assert "total_size_h" in d


def test_the_library_route_filters_by_ar_and_type(lib):
    out, db = lib
    client = login_client(out)
    r = client.get("/api/library?q=type:loom&page_size=50").get_json()
    assert sorted(i["media_id"] for i in r["items"]) == ["loomstill", "v2"]
    r = client.get("/api/library?q=ar:tall&page_size=50").get_json()
    assert r["items"] == []                                 # none of these rows has a size
