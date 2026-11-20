"""The Loom's Image, Edit, Reference and Fix sends are its board's spend too (2026-11-18), and
the AI-preset price cache cannot be repopulated by a read that began before a send.

A tab's send carries `loom_target` {board_id, card_id}; the route pops it, and once PixAI
answers with a task the send goes into that board's send record -- the one source of the
board's "spent" figure -- with 0 when a free card was attached, else the catalog's charge once
known. The run road (the Image tab's x2-4 and template prompts) records each job it sent. No
backfill is possible for these: a board keeps no task id for an Image/Edit/Reference result
(only the media id routed into a frame or the cast, which a library pick also writes), and a
media id is not a send.

No network: the `pixai` fake and test_generate_runs' counting rig."""
import threading

from moonglade import backup as core
from moonglade import cards as cards_mod
from moonglade import pricing as pricing_mod
from moonglade.gallery import save_catalog, CATALOG_FIELDS
from tests.conftest import _TEST_PASSWORD, _TEST_USERNAME, _do_login
from tests.test_generate_runs import CARD as RUN_CARD
from tests.test_generate_runs import cli, rig, run  # noqa: F401  (fixtures + helper)
from tests.test_single_send_quoted_free import (  # noqa: F401  (fixture + helpers)
    _CARD, _NO_CARD, _Req, _body, gen)

TARGET = {"board_id": "b1", "card_id": "c1"}


def _sends(c, board="b1"):
    r = c.post("/api/loom/spend", json={"board_id": board})
    assert r.status_code == 200, r.data
    return r.get_json()["sends"]


def test_an_image_tab_send_covered_by_a_card_is_the_boards_and_costs_zero(gen):
    gen["pixai"].on("/kaisuuken/check", _CARD)
    d = gen["cli"].post("/api/generate", json=dict(_body(), loom_target=TARGET)).get_json()
    assert d.get("task_id") == "task-1", d
    assert _sends(gen["cli"]) == [{"task_id": "task-1", "card": "c1", "kind": "image", "cost": 0}]
    sent = gen["pixai"].calls_for("createGenerationTask")[0].variables["parameters"]
    assert "loom_target" not in sent, "the board's key never reaches PixAI"


def test_an_edit_tab_send_reads_its_charge_off_the_catalog(gen, monkeypatch, tmp_path):
    gen["pixai"].on("/kaisuuken/check", _NO_CARD)
    monkeypatch.setattr(core, "build_request", lambda payload, *a, **k: _Req("edit"))
    d = gen["cli"].post("/api/edit", json={"source": "1", "instruction": "night",
                                           "loom_target": TARGET}).get_json()
    assert d.get("task_id") == "task-1", d
    assert _sends(gen["cli"])[0]["cost"] is None, "unknown until PixAI's charge is collected"
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS}
                                           | dict(media_id="9", filename="9.png",
                                                  task_id="task-1", paid_credit="1200")])
    assert _sends(gen["cli"]) == [{"task_id": "task-1", "card": "c1", "kind": "edit", "cost": 1200}]


def test_a_fix_from_the_loom_is_the_boards_spend(gen, monkeypatch):
    req = _Req("fix")
    req.media_id, req.boxes = "1", [{"tag": "face", "x": 1, "y": 1, "w": 5, "h": 5}]
    monkeypatch.setattr(core, "build_request", lambda payload, *a, **k: req)
    monkeypatch.setattr(core, "submit_fixer", lambda session, media_id, boxes: "task-f")
    d = gen["cli"].post("/api/fix", json={"source": "1", "boxes": req.boxes,
                                          "loom_target": TARGET}).get_json()
    assert d.get("task_id") == "task-f", d
    assert _sends(gen["cli"]) == [{"task_id": "task-f", "card": "c1", "kind": "fix", "cost": None}]


def test_a_send_with_no_board_is_not_recorded(gen):
    gen["pixai"].on("/kaisuuken/check", _CARD)
    assert gen["cli"].post("/api/generate", json=_body()).get_json().get("task_id") == "task-1"
    assert _sends(gen["cli"]) == []


def test_a_task_belongs_to_the_first_board_that_sent_it(gen):
    gen["pixai"].on("/kaisuuken/check", _CARD)
    gen["cli"].post("/api/generate", json=dict(_body(), loom_target=TARGET))
    # The fake answers every create with "task-1": a second board naming the same task does
    # not get it, and the first board still counts it once.
    gen["cli"].post("/api/generate", json=dict(_body(), loom_target={"board_id": "b2",
                                                                     "card_id": "c9"}))
    assert [s["task_id"] for s in _sends(gen["cli"])] == ["task-1"]
    assert _sends(gen["cli"], "b2") == []


def test_a_run_from_the_image_tab_records_each_job(cli, rig):
    rig.card_default = RUN_CARD
    d = run(cli, prompt="{solo|} glade", var_mode="matrix", loom_target=TARGET).get_json()
    assert d["status"] == "sent" and len(rig.mutations) == 1
    assert "loom_target" not in rig.mutations[0]
    got = _sends(cli)
    assert len(got) == 1 and got[0]["card"] == "c1" and got[0]["kind"] == "image"
    assert got[0]["cost"] == 0, "the job's card was attached"


# ---- AI presets: a read that began before a send cannot re-cache the old "free" ------------

def _armed(monkeypatch, fake):
    from moonglade import mirror as _mirror
    monkeypatch.setattr(_mirror, "mirror_enabled", lambda: True)
    monkeypatch.setattr(_mirror, "make_mirror_session", lambda *a, **k: fake)
    monkeypatch.setattr(_mirror, "_session_for_create", lambda s: fake)
    monkeypatch.setattr(core, "build_request", lambda payload, *a, **k: _Req("enhance"))


def test_a_presets_read_overtaken_by_a_send_is_not_cached(gen, monkeypatch):
    _armed(monkeypatch, gen["pixai"])
    gen["pixai"].on("/kaisuuken/check", _CARD)
    other = _do_login(gen["cli"].application.test_client(), _TEST_USERNAME, _TEST_PASSWORD)
    fired, lock = {"n": 0}, threading.Lock()

    def _price(s, params):
        # While the first presets read is pricing, a send lands from another tab.
        with lock:
            if fired["n"] == 0:
                fired["n"] = 1
                r = other.post("/api/enhance", json={"source": "1", "workflow_id": "42"})
                assert r.get_json().get("task_id"), r.get_json()
        return 1500
    monkeypatch.setattr(pricing_mod, "price_task", _price)
    first = gen["cli"].get("/api/enhance/presets").get_json()["presets"]
    assert all(r["free_card"] for r in first), "the read answers what it saw"
    # The card is gone now; the overtaken answer must not have been cached.
    gen["pixai"].on("/kaisuuken/check", _NO_CARD)
    again = gen["cli"].get("/api/enhance/presets").get_json()["presets"]
    assert not any(r["free_card"] for r in again)


def test_presets_check_cards_the_way_the_send_does(gen, monkeypatch):
    _armed(monkeypatch, gen["pixai"])
    monkeypatch.setattr(pricing_mod, "price_task", lambda s, params: 1500)
    seen = []
    real = cards_mod.match_kaisuuken

    def _match(session, params, *a, **k):
        seen.append(k.get("enrich"))
        return real(session, params, *a, **k)
    monkeypatch.setattr(cards_mod, "match_kaisuuken", _match)
    gen["pixai"].on("/kaisuuken/check", _CARD)
    gen["cli"].get("/api/enhance/presets")
    assert seen and all(e is True for e in seen)
