"""POST /api/loom/spend -- a Loom board's "spent" figure, read from its SEND RECORD (2026-11-18).

The figure used to be every media id the board's cards pointed at, joined to the catalog. That
billed whatever was attached to a shot -- a linked or imported video, a remix, a split's twin,
a seeded example card -- so each one needed its own fence and the number kept breaking (the
owner's C: board read "~97,500 cr (+1 unk)" with the "+1" a July dev seed). Now a render is
recorded when it is SENT (the journalled /api/loom/generate path, with its task id; cost 0
when a free card was attached, else PixAI's charge off the catalog once known), and the
route answers that record and nothing else. A board saved before the record existed is
backfilled once, from the real task ids its takes and the journal kept.

No network anywhere: the PixAI edges are recorders (the rig), the catalog is a temp file.
The client's sum (tallySends) is pinned under node --test in loom/test/loom-spend-ledger.test.js
and loom/test/loom-spend-recorded-board.test.js."""
import json
from urllib.parse import quote

import pytest

from moonglade import backup as core
from moonglade import cards as cards_mod
from moonglade import gen_road as gen_road_mod
from moonglade import paths as _paths
from moonglade.account_prefs import _account_key
from moonglade.gallery import create_app
from moonglade.catalog_verbs import loom_backfill_sends
from moonglade.catalog import CATALOG_FIELDS, save_catalog
from tests.conftest import login_test_client

MID = "733917871331404290"


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A signed-in client whose Loom renders reach recorders, never PixAI."""
    rec = {"submits": [], "card": None}

    def _apply(session, params, args):
        if rec["card"]:
            params["kaisuukenId"] = rec["card"]

    def _submit_gen(session, params, on_send=None, exact=False, **_kw):
        if on_send:
            on_send(params)
        rec["submits"].append(dict(params))
        if rec.get("behaviour"):
            return rec["behaviour"](params)
        return "task-%d" % len(rec["submits"])

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "upload_media", lambda *a, **k: "999000111222")
    monkeypatch.setattr(cards_mod, "_apply_kaisuuken", _apply)
    monkeypatch.setattr(gen_road_mod, "submit_generation", _submit_gen)
    app = create_app(tmp_path)
    rec.update(cli=login_test_client(app), app=app, tmp=tmp_path)
    return rec


def _catalog(tmp, *rows):
    save_catalog(tmp / "catalog.db", [_row(**r) for r in rows])


def _board(tmp, board_id, board):
    """Save a board the way the Loom does: its JSON text, as the kv value."""
    d = _paths.loom_root(tmp) / "kv" / _account_key("tester")
    d.mkdir(parents=True, exist_ok=True)
    (d / (quote("storyboard:v2:proj:" + board_id, safe="") + ".json")).write_text(
        json.dumps(json.dumps(board)), encoding="utf-8")


def _spend(cli, board_id):
    r = cli.post("/api/loom/spend", json={"board_id": board_id})
    assert r.status_code == 200, r.data
    return r.get_json()["sends"]


def _render(rig, board="b1", card="c1", sid="s1"):
    return rig["cli"].post("/api/loom/generate", json={
        "mode": "I2V", "prompt": "x", "images": [MID], "duration": 5, "origin": "loom-shot",
        "submit_id": sid, "loom_target": {"board_id": board, "card_id": card}}).get_json()


def _record_lines(tmp):
    p = _paths.loom_root(tmp) / "_sends" / (_account_key("tester") + ".jsonl")
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


# The owner's C: board o1362bb as saved (ids replaced, prompts dropped).
RECORDED = {"acts": [
    {"name": "Act 1 — Setup", "cards": [
        {"id": "ex", "status": "done", "resultMid": "999888777"}]},
    {"name": "Act 5", "cards": [
        {"id": "e1", "status": "done", "resultMid": "700000000000000001", "selectedTake": 1,
         "takes": [{"id": "t1", "n": 1, "mid": "700000000000000001",
                    "taskId": "800000000000000001", "source": "render", "imported": False,
                    "quoted": {"cost": 70000, "free": False}}]},
        {"id": "e2", "status": "done", "resultMid": "700000000000000002", "selectedTake": 1,
         "takes": [{"id": "t1", "n": 1, "mid": "700000000000000002",
                    "taskId": "800000000000000002", "source": "render", "imported": False,
                    "quoted": {"cost": 27500, "free": False}}]},
    ]},
]}


def test_the_recorded_board_reads_its_two_renders_and_not_the_seed(rig):
    _board(rig["tmp"], "o1362bb", RECORDED)
    _catalog(rig["tmp"],
             dict(media_id="700000000000000001", filename="a.mp4", task_id="800000000000000001",
                  paid_credit="70000"),
             dict(media_id="700000000000000002", filename="b.mp4", task_id="800000000000000002",
                  paid_credit="27500"))
    sends = _spend(rig["cli"], "o1362bb")
    assert sorted((s["card"], s["cost"], s["kind"]) for s in sends) == [
        ("e1", 70000, "backfill"), ("e2", 27500, "backfill")]
    assert sum(s["cost"] for s in sends) == 97500
    assert all(s["card"] != "ex" for s in sends), "the seed was never sent"


def test_a_linked_imported_or_remixed_take_is_not_a_send(rig):
    """Only a take the Loom landed from its own render (source "render", not imported) with a
    real task id is backfilled. Attached clips, legacy result ids and attempts are not."""
    _board(rig["tmp"], "b1", {"acts": [{"name": "A", "cards": [
        {"id": "imp", "resultMid": "m1", "imported": True,
         "takes": [{"n": 1, "mid": "m1", "taskId": "t-imp", "source": "render", "imported": True}]},
        {"id": "lnk", "takes": [{"n": 1, "mid": "m2", "taskId": "t-lnk", "source": "link"}]},
        {"id": "rmx", "takes": [{"n": 1, "mid": "m3", "taskId": "t-rmx", "source": "remix"}]},
        {"id": "leg", "resultMid": "m4", "attempts": [{"media_id": "m5"}]},
        {"id": "notask", "takes": [{"n": 1, "mid": "m6", "source": "render"}]},
    ]}]})
    _catalog(rig["tmp"], *[dict(media_id=m, filename=m + ".mp4", task_id="t-" + m,
                                paid_credit="999") for m in ("m1", "m2", "m3", "m4", "m5", "m6")])
    assert _spend(rig["cli"], "b1") == []


def test_a_free_card_render_adds_zero(rig):
    rig["card"] = "card-1"
    assert _render(rig)["task_id"] == "task-1"
    # Even a catalog row claiming a charge does not overrule the card the send carried.
    _catalog(rig["tmp"], dict(media_id="1", filename="1.mp4", task_id="task-1", paid_credit="5000"))
    assert _spend(rig["cli"], "b1") == [
        {"task_id": "task-1", "card": "c1", "kind": "render", "cost": 0}]


def test_a_re_render_adds_its_own_charge(rig, monkeypatch):
    assert _render(rig, sid="s1")["task_id"] == "task-1"
    # The shot is held for one render at a time (the poll ceiling); past it, a second render
    # of the same shot goes out -- a new send with its own task and its own charge.
    import time as _time
    later = _time.time() + 7 * 3600
    monkeypatch.setattr(_time, "time", lambda: later)
    assert _render(rig, sid="s2")["task_id"] == "task-2"
    _catalog(rig["tmp"],
             dict(media_id="1", filename="1.mp4", task_id="task-1", paid_credit="300"),
             dict(media_id="2", filename="2.mp4", task_id="task-2", paid_credit="450"))
    sends = _spend(rig["cli"], "b1")
    assert [(s["task_id"], s["card"], s["cost"]) for s in sends] == [
        ("task-1", "c1", 300), ("task-2", "c1", 450)]


def test_a_paid_charge_is_unknown_until_the_catalog_has_it_then_kept(rig):
    assert _render(rig)["task_id"] == "task-1"
    assert _spend(rig["cli"], "b1")[0]["cost"] is None
    _catalog(rig["tmp"], dict(media_id="1", filename="1.mp4", task_id="task-1", paid_credit="300"))
    assert _spend(rig["cli"], "b1")[0]["cost"] == 300
    # Written into the record: a later loss of the catalog row does not lose the charge.
    (rig["tmp"] / "catalog.db").unlink()
    assert _spend(rig["cli"], "b1")[0]["cost"] == 300


def test_an_unclear_send_is_unknown_and_releasing_it_removes_it(rig):
    def _lost(params):
        raise RuntimeError("read timed out")
    rig["behaviour"] = _lost
    r = _render(rig)
    assert r.get("unclear") and r["state"] == "may_have_started"
    assert _spend(rig["cli"], "b1") == [
        {"task_id": None, "card": "c1", "kind": "render", "cost": None}]
    csrf = rig["cli"].get("/api/account/prefs").get_json()["csrf"]
    assert rig["cli"].post("/api/loom/submit-abandon",
                           json={"submit_id": "s1", "csrf": csrf}).get_json() == {"ok": True}
    assert _spend(rig["cli"], "b1") == []


def test_backfill_runs_twice_with_the_same_result(rig):
    first = loom_backfill_sends(RECORDED, "o1362bb", (), [], at=1.0)
    assert [s["task_id"] for s in first] == ["800000000000000001", "800000000000000002"]
    again = loom_backfill_sends(RECORDED, "o1362bb", [s["task_id"] for s in first], [], at=2.0)
    assert again == []
    # Through the route: the second read writes nothing new and answers the same.
    _board(rig["tmp"], "o1362bb", RECORDED)
    a = _spend(rig["cli"], "o1362bb")
    n = len(_record_lines(rig["tmp"]))
    assert _spend(rig["cli"], "o1362bb") == a
    assert len(_record_lines(rig["tmp"])) == n


def test_a_send_is_one_boards_and_a_copied_board_does_not_count_it_again(rig):
    assert _render(rig, board="b1", card="c1")["task_id"] == "task-1"
    copy = {"acts": [{"name": "A", "cards": [
        {"id": "c1", "takes": [{"n": 1, "mid": "1", "taskId": "task-1", "source": "render"}]}]}]}
    _board(rig["tmp"], "b2", copy)
    assert _spend(rig["cli"], "b2") == []
    assert [s["task_id"] for s in _spend(rig["cli"], "b1")] == ["task-1"]


def test_a_draft_render_counts_on_the_board_it_names(rig):
    r = rig["cli"].post("/api/loom/generate", json={
        "mode": "I2V", "prompt": "x", "images": [MID], "duration": 5,
        "submit_id": "d1", "loom_board": "b1"}).get_json()
    assert r["task_id"] == "task-1"
    assert _spend(rig["cli"], "b1") == [
        {"task_id": "task-1", "card": "", "kind": "render", "cost": None}]


def test_the_gallery_video_tab_is_not_a_board_send(rig):
    r = rig["cli"].post("/api/loom/generate", json={
        "mode": "I2V", "prompt": "x", "images": [MID], "duration": 5}).get_json()
    assert r["task_id"]
    assert _record_lines(rig["tmp"]) == []


def test_a_board_id_is_required(rig):
    for body in ({}, {"board_id": ""}, {"board_id": "../x"}, {"media_ids": ["1"]}):
        assert rig["cli"].post("/api/loom/spend", json=body).status_code == 400
