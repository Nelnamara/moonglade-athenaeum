"""The catalog road and the catalog verbs.

Two things used to be one. `_connect()` opened catalog.db AND ran all 41 statements
of `_MIGRATIONS` on every single call, at ~39 call sites; and eleven route handlers
inside `create_app` bypassed the helper set entirely, opening their own connection
and writing their own SQL against `catalog`. This file pins the shape that replaced
both:

  * `catalog(db_path)` opens, hands out a Row connection, closes. NO DDL.
  * `migrate(db_path)` runs `_MIGRATIONS`, idempotently, once per process per path.
  * lazy safety survives: the FIRST `catalog()` for a path migrates it, so no entry
    point (web app, CLI, MCP server, a test calling a helper straight at a fresh tmp
    db) has to remember to.
  * every question the routes ask of the catalog is a named verb returning plain
    data, and `create_app` holds no SQL at all -- the last test here walks the AST
    and says so.

Each verb test seeds a REAL tmp catalog.db through save_catalog and asserts the rows
and fields its route used to produce -- several of them by asking the live route for
the same thing and comparing.
"""
import ast
import re
import sqlite3
from pathlib import Path

import pytest

import moonglade_gallery as g
from moonglade_gallery import (CATALOG_FIELDS, catalog, migrate, save_catalog,
                               init_db, task_media, task_media_count,
                               delete_targets, delete_preview_rows, myart_items,
                               artwork_row, publish_state, lineage, sibling_media,
                               recent_train_tasks, history_page,
                               history_created_ats)

from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _seed(tmp_path, rows):
    save_catalog(tmp_path / "catalog.db", rows)
    return tmp_path / "catalog.db"


# The columns catalog.db was born with (cc2aeb1, 2026-06-13). Everything added since
# reaches an EXISTING install only through _MIGRATIONS, which is what makes a db built
# from just these the honest stand-in for "an install from before the last release".
_ORIGINAL_FIELDS = [
    "task_id", "media_id", "filename", "url", "width", "height",
    "prompt_preview", "status", "created_at", "prompt_full", "natural_prompt",
    "seed", "steps", "sampler", "cfg_scale", "model_id", "model_name", "rating",
]


def _ancient_db(path, rows=()):
    """A catalog.db as an old install would have it: original columns only, no
    migrations applied, optionally holding real rows."""
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE catalog ({})".format(", ".join(
        ("media_id TEXT PRIMARY KEY" if f == "media_id" else "{} TEXT".format(f))
        for f in _ORIGINAL_FIELDS)))
    for r in rows:
        cols = [f for f in _ORIGINAL_FIELDS if f in r]
        con.execute("INSERT INTO catalog ({}) VALUES ({})".format(
            ", ".join(cols), ", ".join("?" * len(cols))), [r[f] for f in cols])
    con.commit()
    con.close()
    return path


@pytest.fixture
def traced(monkeypatch):
    """Every statement executed on every sqlite connection opened while this is
    active, in order. Attaches a trace callback at sqlite3.connect, so it sees the
    connections migrate() opens for itself as well as the one catalog() yields."""
    statements = []
    real_connect = sqlite3.connect

    def _connect(*a, **k):
        con = real_connect(*a, **k)
        con.set_trace_callback(statements.append)
        return con

    monkeypatch.setattr(sqlite3, "connect", _connect)
    return statements


def _ddl(statements):
    return [s for s in statements
            if s.strip().upper().startswith(("ALTER ", "CREATE INDEX", "CREATE TABLE"))]


# --------------------------------------------------------------- the road

def test_catalog_runs_no_ddl_once_the_path_is_migrated(tmp_path, traced):
    """The whole point of the split: an ordinary read opens the catalog and reads.
    The FIRST open of a path pays for the schema upgrade (that is lazy safety, and
    it is asserted here so this test cannot pass by simply never migrating); every
    open after it executes not one DDL statement -- where the old _connect ran all
    41 of them, every time, at every one of its ~39 call sites."""
    db = _ancient_db(tmp_path / "catalog.db")

    del traced[:]
    with catalog(db) as con:
        con.execute("SELECT COUNT(*) FROM catalog").fetchone()
    first = _ddl(traced)
    assert len(first) == len(g._MIGRATIONS), (
        "the first open of a path must run the migrations lazily")

    del traced[:]
    with catalog(db) as con:
        con.execute("SELECT COUNT(*) FROM catalog").fetchone()
    assert _ddl(traced) == [], (
        "opening an already-migrated catalog executed DDL: {}".format(_ddl(traced)))


def test_catalog_alone_migrates_a_fresh_db(tmp_path):
    """LAZY SAFETY. Every entry point that touches the catalog -- the gallery, the
    CLI through _ensure_db, moonglade_mcp.py, moonglade_similar.py, save_catalog, a
    test calling a helper straight at a tmp db -- used to be migrated implicitly by
    _connect. Nothing may now depend on someone REMEMBERING to call migrate(): one
    catalog() open, with no init_db and no migrate() call anywhere, has to leave an
    old install holding every current column."""
    db = _ancient_db(tmp_path / "catalog.db",
                     [{"media_id": "m1", "task_id": "t1", "filename": "keep.png",
                       "rating": "5"}])
    with catalog(db) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(catalog)").fetchall()}
        kept = dict(con.execute("SELECT * FROM catalog WHERE media_id='m1'").fetchone())
    missing = [f for f in CATALOG_FIELDS if f not in cols]
    assert not missing, "a catalog() open left an old db without {}".format(missing)
    assert kept["filename"] == "keep.png" and kept["rating"] == "5"   # no data loss


def test_catalog_yields_row_objects_and_closes_the_connection(tmp_path):
    db = _seed(tmp_path, [_row(media_id="m1", filename="a.png")])
    with catalog(db) as con:
        row = con.execute("SELECT media_id, filename FROM catalog").fetchone()
        assert row["media_id"] == "m1" and row["filename"] == "a.png"   # Row, not tuple
    with pytest.raises(sqlite3.ProgrammingError):
        con.execute("SELECT 1")          # the block closed it


def test_catalog_closes_the_connection_even_when_the_body_raises(tmp_path):
    db = _seed(tmp_path, [_row(media_id="m1")])
    with pytest.raises(ValueError):
        with catalog(db) as con:
            raise ValueError("boom")
    with pytest.raises(sqlite3.ProgrammingError):
        con.execute("SELECT 1")


def test_migrate_runs_once_per_process_per_path(tmp_path, monkeypatch):
    """Idempotent AND memoized. A probe statement with a visible side effect rides
    along in _MIGRATIONS: if migrate() ran twice, the probe row would land twice.
    force=True is the escape hatch that proves the DDL itself is genuinely re-runnable
    rather than merely skipped."""
    db = tmp_path / "catalog.db"
    init_db(db)
    monkeypatch.setattr(g, "_MIGRATIONS", list(g._MIGRATIONS) + [
        "CREATE TABLE IF NOT EXISTS migrate_probe (n TEXT)",
        "INSERT INTO migrate_probe (n) VALUES ('ran')"])

    migrate(db)
    migrate(db)
    migrate(db)
    with catalog(db) as con:             # the lazy path is memoized by the same key
        assert con.execute("SELECT COUNT(*) FROM migrate_probe").fetchone()[0] == 1

    migrate(db, force=True)              # re-running is harmless, just not free
    with catalog(db) as con:
        assert con.execute("SELECT COUNT(*) FROM migrate_probe").fetchone()[0] == 2


def test_migrate_memo_is_keyed_per_path_not_globally(tmp_path):
    """One migrated catalog must not convince the memo that a DIFFERENT one is done
    -- an install with two backup folders would otherwise get exactly one of them
    upgraded."""
    first = _ancient_db(tmp_path / "one.db")
    second = _ancient_db(tmp_path / "two.db")
    migrate(first)
    with catalog(second) as con:
        cols = {r[1] for r in con.execute("PRAGMA table_info(catalog)").fetchall()}
    assert not [f for f in CATALOG_FIELDS if f not in cols]


def test_migrate_is_free_after_the_first_call(tmp_path, traced):
    db = _ancient_db(tmp_path / "catalog.db")
    migrate(db)
    del traced[:]
    migrate(db)
    assert traced == [], "a memoized migrate() opened a connection anyway"


# --------------------------------------------------------------- the verbs

def test_task_media_returns_a_tasks_whole_output(tmp_path):
    """One task's media, as the live-mirror's collect read-back, /api/import-task's
    already-catalogued precheck and the bulk delete's local purge all need it."""
    db = _seed(tmp_path, [
        _row(media_id="a1", task_id="T1", filename="a1.png"),
        _row(media_id="a2", task_id="T1", filename="a2.png", is_video="1"),
        _row(media_id="b1", task_id="T2", filename="b1.png"),
    ])
    got = task_media(db, "T1")
    assert {r["media_id"] for r in got} == {"a1", "a2"}
    assert {r["media_id"]: r["filename"] for r in got} == {"a1": "a1.png", "a2": "a2.png"}
    assert any(r["is_video"] == "1" for r in got)
    assert task_media(db, "T2")[0]["media_id"] == "b1"
    assert task_media(db, "nope") == []


def test_task_media_count_counts_the_batch(tmp_path):
    db = _seed(tmp_path, [
        _row(media_id="a1", task_id="T1"), _row(media_id="a2", task_id="T1"),
        _row(media_id="b1", task_id="T2"),
    ])
    assert task_media_count(db, "T1") == 2
    assert task_media_count(db, "T2") == 1
    assert task_media_count(db, "") == 0        # an import has no task at all
    assert task_media_count(db, None) == 0


def test_task_media_count_fails_soft_on_a_broken_catalog(tmp_path):
    """A number on a confirm dialog must never be able to break the dialog."""
    db = tmp_path / "catalog.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE not_the_catalog (x TEXT)")
    con.commit(); con.close()
    assert task_media_count(db, "T1") == 0


def test_delete_targets_resolves_tasks_and_leaves_imports_local(tmp_path):
    """The selection a delete really acts on: one cloud delete per TASK however many
    of its images were picked, and the task-less imports kept apart."""
    db = _seed(tmp_path, [
        _row(media_id="a1", task_id="T1", filename="a1.png"),
        _row(media_id="a2", task_id="T1", filename="a2.png"),
        _row(media_id="c1", task_id="T2", filename="c1.png"),
        _row(media_id="imp", task_id="", filename="imp.png"),
    ])
    sel, task_ids, local_only = delete_targets(db, ["a1", "a2", "c1", "imp", "ghost"])
    assert [r["media_id"] for r in sel] == ["a1", "a2", "c1", "imp"]   # ghost dropped
    assert task_ids == ["T1", "T2"]                                    # deduped, sorted
    assert [r["media_id"] for r in local_only] == ["imp"]
    assert local_only[0]["filename"] == "imp.png"


def test_delete_preview_rows_expands_each_task_to_its_whole_batch(tmp_path):
    """Deleting on PixAI is TASK-level: picking one image of a batch takes all four.
    The preview has to show that, so it expands the selection to full membership."""
    db = _seed(tmp_path, [
        _row(media_id="a1", task_id="T1", filename="a1.png"),
        _row(media_id="a2", task_id="T1", filename="a2.png"),
        _row(media_id="a3", task_id="T1", filename="a3.png", is_video="1",
             poster_media_id="a1"),
        _row(media_id="imp", task_id="", filename="imp.png"),
    ])
    blast = delete_preview_rows(db, ["a1", "imp"])
    assert blast["task_ids"] == ["T1"]
    members = blast["members_by_task"]["T1"]
    assert [m["media_id"] for m in members] == ["a1", "a2", "a3"]      # sorted, all three
    assert members[2]["poster_media_id"] == "a1"                       # the poster survives
    assert [r["media_id"] for r in blast["local_only"]] == ["imp"]
    assert [r["media_id"] for r in blast["local_rows"]] == ["imp"]
    assert [r["media_id"] for r in blast["sel_rows"]] == ["a1", "imp"]


def test_delete_preview_rows_caps_displayed_imports_only(tmp_path):
    """The cap is a DISPLAY bound: local_rows stops, local_only keeps counting,
    because the totals are what the user reads to decide."""
    db = _seed(tmp_path, [_row(media_id="i{}".format(i), task_id="", filename="i.png")
                          for i in range(5)])
    blast = delete_preview_rows(db, ["i{}".format(i) for i in range(5)], task_cap=2)
    assert len(blast["local_only"]) == 5
    assert len(blast["local_rows"]) == 2


def test_delete_preview_verb_and_route_agree(tmp_path):
    """The verb is what /api/delete-preview now answers from -- prove the route's
    payload is still built out of exactly these rows."""
    db = _seed(tmp_path, [
        _row(media_id="a1", task_id="T1", filename="a1.png"),
        _row(media_id="a2", task_id="T1", filename="a2.png"),
        _row(media_id="imp", task_id="", filename="imp.png"),
    ])
    body = login_client(tmp_path).post(
        "/api/delete-preview", json={"media_ids": ["a1", "imp"]}).get_json()
    blast = delete_preview_rows(db, ["a1", "imp"])
    assert [t["task_id"] for t in body["tasks"]] == blast["task_ids"]
    assert ([m["media_id"] for m in body["tasks"][0]["media"]]
            == [m["media_id"] for m in blast["members_by_task"]["T1"]])
    assert body["totals"]["media"] == 3            # both siblings + the import
    assert body["totals"]["selected"] == 2
    assert body["totals"]["local_only"] == 1


def test_myart_items_is_every_artwork_public_and_private_newest_first(tmp_path):
    """My Art's whole population: every row with an artwork_id, published or held
    back. likes/comments come back as ints even though the columns are TEXT."""
    db = _seed(tmp_path, [
        _row(media_id="m1", artwork_id="A1", title="One", is_published="1",
             created_at="2026-01-01T00:00:00Z", liked_count="7", comment_count=""),
        _row(media_id="m2", artwork_id="A2", title="Two", is_published="0",
             created_at="2026-02-01T00:00:00Z", liked_count="", is_video="1"),
        _row(media_id="m3", artwork_id="", title="Not an artwork",
             created_at="2026-03-01T00:00:00Z"),
    ])
    items = myart_items(db)
    assert [r["media_id"] for r in items] == ["m2", "m1"]        # newest first
    assert items[1]["likes"] == 7 and items[1]["comments"] == 0  # blank TEXT -> 0
    assert items[0]["likes"] == 0
    assert items[0]["is_published"] == "0" and items[0]["is_video"] == "1"


def test_myart_items_verb_and_route_agree(tmp_path):
    db = _seed(tmp_path, [
        _row(media_id="m1", artwork_id="A1", title="", prompt_preview="a moonlit owl",
             is_published="1", created_at="2026-01-01T00:00:00Z", liked_count="7",
             art_tags="owl, night"),
    ])
    body = login_client(tmp_path).get("/api/myart/items").get_json()
    verb = myart_items(db)
    assert [i["media_id"] for i in body["items"]] == [r["media_id"] for r in verb]
    assert body["items"][0]["title"] == "a moonlit owl"       # falls back to the prompt
    assert body["items"][0]["likes"] == verb[0]["likes"] == 7
    assert body["items"][0]["tags"] == ["owl", "night"]


def test_artwork_row_is_the_publish_targets_identity(tmp_path):
    db = _seed(tmp_path, [_row(media_id="m1", artwork_id="A1", task_id="T1",
                               title="One", art_tags="owl", is_published="1")])
    row = artwork_row(db, "m1")
    assert row == {"media_id": "m1", "artwork_id": "A1", "task_id": "T1",
                   "title": "One", "art_tags": "owl", "is_published": "1"}
    assert artwork_row(db, "nope") is None


def test_publish_state_writes_only_the_fields_it_is_given(tmp_path):
    """None means LEAVE IT ALONE: flipping visibility must not rewrite the title or
    the tags as a side effect."""
    db = _seed(tmp_path, [_row(media_id="m1", artwork_id="A1", title="Original",
                               art_tags="owl", is_published="1")])
    assert publish_state(db, "m1", published=False) == 1
    row = artwork_row(db, "m1")
    assert row["is_published"] == "0"
    assert row["title"] == "Original" and row["art_tags"] == "owl"

    publish_state(db, "m1", title="Renamed", art_tags="owl, night")
    row = artwork_row(db, "m1")
    assert row["title"] == "Renamed" and row["art_tags"] == "owl, night"
    assert row["is_published"] == "0"            # untouched


def test_publish_state_publish_and_unpublish(tmp_path):
    db = _seed(tmp_path, [_row(media_id="m1", task_id="T1")])
    publish_state(db, "m1", artwork_id="A9", published=True)
    assert artwork_row(db, "m1") == {"media_id": "m1", "artwork_id": "A9",
                                     "task_id": "T1", "title": "",
                                     "art_tags": "", "is_published": "1"}
    # deleting the artwork on PixAI: the local row survives, it just stops claiming one
    publish_state(db, "m1", artwork_id="", published=False)
    row = artwork_row(db, "m1")
    assert row["artwork_id"] == "" and row["is_published"] == "0"
    assert row["task_id"] == "T1"


def test_publish_state_with_nothing_to_write_is_a_no_op(tmp_path):
    db = _seed(tmp_path, [_row(media_id="m1", title="Original")])
    assert publish_state(db, "m1") == 0
    assert artwork_row(db, "m1")["title"] == "Original"


def test_publish_state_empty_title_is_a_real_value(tmp_path):
    """An intentionally CLEARED title publishes empty. `or`-style fallbacks treat ""
    as absent, which is exactly the bug that once shipped a stale title."""
    db = _seed(tmp_path, [_row(media_id="m1", title="Original")])
    publish_state(db, "m1", title="")
    assert artwork_row(db, "m1")["title"] == ""


def test_lineage_gives_siblings_parent_and_children(tmp_path):
    db = _seed(tmp_path, [
        _row(media_id="p1", task_id="T1", title="Parent"),
        _row(media_id="s1", task_id="T1", title="Sibling"),
        _row(media_id="c1", task_id="T2", source_media_id="p1", derive_kind="upscale",
             created_at="2026-01-01T00:00:00Z"),
        _row(media_id="c2", task_id="T3", source_media_id="p1", derive_kind="",
             created_at="2026-02-01T00:00:00Z", is_video="1"),
    ])
    tree = lineage(db, "p1")
    assert [r["media_id"] for r in tree["siblings"]] == ["s1"]
    assert tree["parent"] is None
    assert [r["media_id"] for r in tree["children"]] == ["c1", "c2"]   # by created_at
    assert [r["kind"] for r in tree["children"]] == ["upscale", "derived"]

    child = lineage(db, "c1")
    assert child["parent"]["media_id"] == "p1" and child["parent"]["kind"] == "upscale"
    assert child["siblings"] == [] and child["children"] == []
    assert lineage(db, "ghost") is None


def test_lineage_verb_and_route_agree(tmp_path):
    db = _seed(tmp_path, [
        _row(media_id="p1", task_id="T1", title="Parent"),
        _row(media_id="s1", task_id="T1", prompt_preview="a very long prompt " * 6),
        _row(media_id="c1", task_id="T2", source_media_id="p1", derive_kind="edit"),
    ])
    cli = login_client(tmp_path)
    body = cli.get("/api/lineage/p1").get_json()
    tree = lineage(db, "p1")
    assert [s["media_id"] for s in body["siblings"]] == [r["media_id"] for r in tree["siblings"]]
    assert body["siblings"][0]["thumb"] == "/thumbs/s1.jpg"
    assert len(body["siblings"][0]["title"]) == 48        # the card's own truncation
    assert body["children"][0]["kind"] == "edit"
    assert body["parent"] is None
    assert cli.get("/api/lineage/ghost").status_code == 404


def test_sibling_media_is_ordered_and_never_groups_the_task_less(tmp_path):
    """Every import shares task_id '' -- querying it would make one giant
    pseudo-batch of unrelated images."""
    db = _seed(tmp_path, [
        _row(media_id="b2", task_id="T1"), _row(media_id="b1", task_id="T1"),
        _row(media_id="z1", task_id="T2"),
        _row(media_id="imp", task_id=""),
    ])
    got = sibling_media(db, ["T2", "T1", ""])
    assert [(r["task_id"], r["media_id"]) for r in got] == [
        ("T1", "b1"), ("T1", "b2"), ("T2", "z1")]
    assert sibling_media(db, []) == []
    assert sibling_media(db, ["", "  "]) == []


def test_recent_train_tasks_groups_by_task_with_real_counts(tmp_path):
    """The mobile picker's tiles are TASKS, and each carries its REAL image count --
    real batches are 1-4, never the mock's fixed 4. Videos, imports and rows with no
    file are not training material."""
    db = _seed(tmp_path, [
        _row(media_id="a1", task_id="T1", filename="a1.png", created_at="2026-03-02T00:00:00Z"),
        _row(media_id="a2", task_id="T1", filename="a2.png", created_at="2026-03-01T00:00:00Z"),
        _row(media_id="b1", task_id="T2", filename="b1.png", created_at="2026-02-01T00:00:00Z"),
        _row(media_id="v1", task_id="T3", filename="v1.mp4", is_video="1",
             created_at="2026-04-01T00:00:00Z"),
        _row(media_id="n1", task_id="T4", filename="", created_at="2026-05-01T00:00:00Z"),
        _row(media_id="imp", task_id="", filename="imp.png", created_at="2026-06-01T00:00:00Z"),
    ])
    tasks = recent_train_tasks(db)
    assert [t["task_id"] for t in tasks] == ["T1", "T2"]      # newest task first
    assert tasks[0]["count"] == 2 and tasks[0]["media_ids"] == ["a1", "a2"]
    assert tasks[1]["count"] == 1
    assert [t["task_id"] for t in recent_train_tasks(db, limit=1)] == ["T1"]


def test_recent_train_tasks_verb_and_route_agree(tmp_path):
    db = _seed(tmp_path, [
        _row(media_id="a1", task_id="T1", filename="a1.png", created_at="2026-03-02T00:00:00Z"),
        _row(media_id="a2", task_id="T1", filename="a2.png", created_at="2026-03-01T00:00:00Z"),
    ])
    body = login_client(tmp_path).get("/api/train/recent-tasks").get_json()
    verb = recent_train_tasks(db, 18)
    assert [t["task_id"] for t in body["tasks"]] == [t["task_id"] for t in verb]
    assert body["tasks"][0]["count"] == 2
    assert body["tasks"][0]["thumb"] == "/thumbs/a1.jpg"      # the route adds the URL


def test_history_page_is_a_half_open_window_newest_first(tmp_path):
    db = _seed(tmp_path, [
        _row(media_id="m1", filename="a.png", created_at="2026-08-11T00:00:00.000Z"),
        _row(media_id="m2", filename="b.png", created_at="2026-08-12T00:00:00.000Z"),
        _row(media_id="old", filename="c.png", created_at="2026-08-01T00:00:00.000Z"),
        _row(media_id="new", filename="d.png", created_at="2026-08-20T00:00:00.000Z"),
    ])
    page = history_page(db, "2026-08-11T00:00:00.000Z", "2026-08-13T00:00:00.000Z")
    assert [r["media_id"] for r in page["rows"]] == ["m2", "m1"]   # newest first
    assert page["older_created_at"] == "2026-08-01T00:00:00.000Z"  # the paging cursor


def test_history_page_carries_the_feeds_derived_columns(tmp_path):
    """model falls back model_name -> video_model -> model_id, and prompt prefers
    prompt_full over prompt_preview, capped at 300 characters."""
    db = _seed(tmp_path, [
        _row(media_id="m1", filename="a.png", created_at="2026-08-11T00:00:00.000Z",
             model_id="42", video_model="wan-2.2", prompt_preview="short",
             prompt_full="x" * 400, paid_credit="250", width="512", height="768"),
    ])
    r = history_page(db, "2026-08-11T00:00:00.000Z", "2026-08-12T00:00:00.000Z")["rows"][0]
    assert r["model"] == "wan-2.2"          # no model_name, so the video model wins
    assert r["prompt"] == "x" * 300         # SUBSTR cap
    assert r["paid_credit"] == "250" and r["width"] == "512"


def test_history_page_filters_by_media_and_source(tmp_path):
    db = _seed(tmp_path, [
        _row(media_id="i1", filename="a.png", created_at="2026-08-11T00:00:00.000Z",
             source="api"),
        _row(media_id="v1", filename="b.mp4", created_at="2026-08-11T01:00:00.000Z",
             is_video="1", source="online"),
    ])
    win = ("2026-08-11T00:00:00.000Z", "2026-08-12T00:00:00.000Z")
    assert [r["media_id"] for r in history_page(db, *win, media="video")["rows"]] == ["v1"]
    assert [r["media_id"] for r in history_page(db, *win, media="image")["rows"]] == ["i1"]
    assert [r["media_id"] for r in history_page(db, *win, source="api")["rows"]] == ["i1"]


def test_history_page_with_nothing_older_has_no_cursor(tmp_path):
    db = _seed(tmp_path, [_row(media_id="m1", filename="a.png",
                               created_at="2026-08-11T00:00:00.000Z")])
    page = history_page(db, "2026-08-11T00:00:00.000Z", "2026-08-12T00:00:00.000Z")
    assert page["older_created_at"] is None


def test_history_created_ats_returns_values_not_days(tmp_path):
    """Which LOCAL day a UTC timestamp falls in depends on the viewer's timezone, so
    the verb hands back the raw values and the route does the bucketing."""
    db = _seed(tmp_path, [
        _row(media_id="m1", filename="a.png", created_at="2026-08-11T00:00:00.000Z"),
        _row(media_id="m2", filename="b.png", created_at="2026-08-11T23:00:00.000Z"),
        _row(media_id="out", filename="c.png", created_at="2026-08-20T00:00:00.000Z"),
    ])
    got = history_created_ats(db, "2026-08-11T00:00:00.000Z", "2026-08-12T00:00:00.000Z")
    assert sorted(got) == ["2026-08-11T00:00:00.000Z", "2026-08-11T23:00:00.000Z"]


def test_history_verb_and_route_agree(tmp_path):
    db = _seed(tmp_path, [
        _row(media_id="m1", filename="a.png", created_at="2026-08-17T10:00:00.000Z",
             task_id="T1", model_name="anything", paid_credit="120"),
    ])
    body = login_client(tmp_path).get(
        "/api/next/history?days=7&tz=-420&before=2026-08-18").get_json()
    rows = [r for day in body["days"] for r in day["rows"]]
    verb = history_page(db, "2026-08-11T07:00:00.000Z", "2026-08-18T07:00:00.000Z")["rows"]
    assert [r["media_id"] for r in rows] == [r["media_id"] for r in verb]
    assert rows[0]["model"] == "anything" and rows[0]["paid_credit"] == 120
    assert rows[0]["thumb"] == "/thumbs/m1.jpg"      # the route adds the URLs


# --------------------------------------------------- the structural invariant

# Names a handler is never allowed to touch: the sqlite module itself, the deprecated
# connect alias, and the connection road. A route asks a VERB; opening the catalog is
# not a route's job.
_FORBIDDEN_NAMES = {"sqlite3", "_connect", "catalog"}

# A real statement, not prose. "Delete from PixAI" in a docstring is English; docstrings
# are skipped outright below, and this still wants FROM/INTO/SET before it will fire.
_SQL = re.compile(r"(?is)\b(SELECT\b.+\bFROM\b|INSERT\s+INTO\b|UPDATE\s+\w+\s+SET\b"
                  r"|DELETE\s+FROM\b)")

# Strings inside create_app that LOOK like SQL but are not catalog SQL. Empty on
# purpose: nothing has needed an exemption. Anything added here needs a reason in the
# comment beside it, and "it was easier than moving the query" is not one.
_EXEMPT_STRINGS = set()


def _create_app_node():
    src = Path(g.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    return next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "create_app")


def _docstring_nodes(root):
    """The Constant node of every docstring under `root`, so prose is not mistaken
    for code. Comments never reach the AST at all."""
    out = set()
    for n in ast.walk(root):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            first = n.body[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                out.add(id(first.value))
    return out


def test_no_catalog_sql_lives_inside_create_app():
    """THE INVARIANT. Every route handler and inner function of create_app asks the
    catalog a QUESTION -- a named verb in the helper set -- and jsonifies what comes
    back. None of them writes SQL, opens a connection, or so much as mentions sqlite3.

    Until 2026-08-23 eleven of them did, which is why architecture.md's "all I/O goes
    through helpers in moonglade_gallery.py -- never raw SQL elsewhere" was a
    description of an intention rather than of the code. This test is what makes it
    a fact: a handler that grows its own SELECT fails the suite."""
    ca = _create_app_node()
    docs = _docstring_nodes(ca)
    offenders = []
    for n in ast.walk(ca):
        if isinstance(n, ast.Name) and n.id in _FORBIDDEN_NAMES:
            offenders.append("line {}: names `{}`".format(n.lineno, n.id))
        elif (isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docs and n.value not in _EXEMPT_STRINGS
                and _SQL.search(n.value)):
            offenders.append("line {}: SQL string {!r}".format(
                n.lineno, n.value.replace("\n", " ")[:80]))
    assert not offenders, (
        "create_app holds catalog SQL again -- move it to a named verb beside the "
        "other catalog helpers:\n  " + "\n  ".join(sorted(set(offenders))))


def test_the_structural_check_can_actually_fail():
    """A guard that cannot fail guards nothing. Feed the same walk a function that
    does exactly what the eleven handlers used to do, and it must object."""
    bad = ast.parse(
        'def create_app(out_dir):\n'
        '    """A docstring mentioning Delete from PixAI is fine."""\n'
        '    def api_thing():\n'
        '        con = _connect(db_path)\n'
        '        return con.execute("SELECT media_id FROM catalog").fetchall()\n'
    ).body[0]
    docs = _docstring_nodes(bad)
    found = []
    for n in ast.walk(bad):
        if isinstance(n, ast.Name) and n.id in _FORBIDDEN_NAMES:
            found.append(n.id)
        elif (isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docs and _SQL.search(n.value)):
            found.append(n.value)
    assert "_connect" in found
    assert any("SELECT media_id FROM catalog" == f for f in found)
    assert not any("Delete from PixAI" in f for f in found)   # prose stays prose


def test_every_catalog_verb_returns_plain_data(tmp_path):
    """A verb hands back dicts and lists -- never a sqlite3.Row, never a live
    connection. A Row leaking out is how SQL creeps back into a handler: it is only
    ordinary-looking until someone indexes it by position."""
    db = _seed(tmp_path, [
        _row(media_id="m1", task_id="T1", filename="a.png", artwork_id="A1",
             created_at="2026-08-11T00:00:00.000Z"),
    ])
    samples = [
        task_media(db, "T1"),
        delete_targets(db, ["m1"])[0],
        delete_preview_rows(db, ["m1"])["members_by_task"]["T1"],
        myart_items(db),
        [artwork_row(db, "m1")],
        [lineage(db, "m1")["row"]],
        sibling_media(db, ["T1"]),
        recent_train_tasks(db),
        history_page(db, "2026-08-11T00:00:00.000Z", "2026-08-12T00:00:00.000Z")["rows"],
    ]
    for rows in samples:
        for r in rows:
            assert isinstance(r, dict) and not isinstance(r, sqlite3.Row)
