"""Session P (BUILD-w5-p §3.2 and its adversarial review F2, F3, F8, F13, F15, F16, N3, N5):
the guard order on /api/loom/generate, the Loom submit journal, submit-status and
submit-abandon, and the board store's revisions.

NO network: PixAI is never reached. The session factory is replaced by a recorder, the free
card step by a stub, and submit_generation by a fake that reports "sent" through the real
on_send hook exactly where the real one would -- so the route's classification of what went
out is exercised through the real core.submit (READ_ONLY -> card -> before_send -> the one
mutation)."""
import json
import threading
import time

import pytest

import moonglade_backup as core
from moonglade_gallery import _account_key, create_app
from tests.conftest import _TEST_PASSWORD, _TEST_USERNAME, _do_login, login_test_client

MID = "733917871331404290"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """A logged-in client with the PixAI edges replaced by recorders."""
    rec = {"sessions": 0, "submits": [], "uploads": [], "built": []}

    def _session(*a, **k):
        rec["sessions"] += 1
        return object()

    def _upload(session, path, **k):
        rec["uploads"].append(str(path))
        return "999000111222"

    real_build = core.build_request

    def _build(payload, *a, **k):
        rec["built"].append(dict(payload))
        return real_build(payload, *a, **k)

    def _submit_gen(session, params, on_send=None, exact=False):
        if on_send:
            on_send(params)
        rec["submits"].append(dict(params))
        behaviour = rec.get("behaviour")
        if behaviour:
            return behaviour(params)
        return "task-%d" % len(rec["submits"])

    monkeypatch.setattr(core, "_make_session", _session)
    monkeypatch.setattr(core, "upload_media", _upload)
    monkeypatch.setattr(core, "build_request", _build)
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "submit_generation", _submit_gen)
    app = create_app(tmp_path)
    cli = login_test_client(app)
    rec["cli"], rec["app"], rec["tmp"] = cli, app, tmp_path
    return rec


def _body(submit_id="s1", card="c1", board="b1", **extra):
    b = {"mode": "I2V", "prompt": "x", "images": [MID], "duration": 5, "origin": "loom-shot"}
    if submit_id is not None:
        b["submit_id"] = submit_id
    if card is not None:
        b["loom_target"] = {"board_id": board, "card_id": card}
    b.update(extra)
    return b


def _another_tab(app):
    """A second signed-in client for the SAME account. Not login_test_client: re-registering
    the account revokes the sessions it already has."""
    return _do_login(app.test_client(), _TEST_USERNAME, _TEST_PASSWORD)


def _csrf(cli):
    return cli.get("/api/account/prefs").get_json()["csrf"]


# ---- the guard order ----------------------------------------------------------------------

def test_read_only_refuses_before_the_session_or_any_upload(rig, monkeypatch):
    """N3: READ_ONLY runs before _gen_session (which resolves USER_ID over the network) and
    before resolve_img uploads a data: thumbnail."""
    monkeypatch.setattr(core, "READ_ONLY", True)
    r = rig["cli"].post("/api/loom/generate", json=_body(images=["data:image/png;base64,iVBORw0KGgo="]))
    assert "READ_ONLY" in r.get_json()["error"]
    assert rig["sessions"] == 0
    assert rig["uploads"] == []
    assert rig["submits"] == []


def test_the_loom_keys_never_reach_build_request(rig):
    r = rig["cli"].post("/api/loom/generate", json=_body(expect_free=False))
    assert r.get_json()["task_id"] == "task-1"
    built = rig["built"][0]
    for k in ("loom_target", "submit_id", "expect_free"):
        assert k not in built


def test_a_body_without_the_keys_is_todays_request(rig):
    r = rig["cli"].post("/api/loom/generate", json=_body(submit_id=None, card=None))
    assert r.get_json()["task_id"] == "task-1"
    assert not (rig["tmp"] / "loom" / "_submits").exists() or not any(
        (rig["tmp"] / "loom" / "_submits").iterdir()), "nothing is journalled"


def test_an_imported_picture_is_refused_before_anything_is_sent(rig):
    """F16: resolve_img turned a local_ id into "" and the render went out without it."""
    r = rig["cli"].post("/api/loom/generate", json=_body(images=["local_0123456789ab"]))
    assert "imported picture" in r.get_json()["error"]
    assert rig["submits"] == [] and rig["sessions"] == 0
    st = rig["cli"].get("/api/loom/submit-status?submit_id=s1").get_json()
    assert st["state"] == "not_sent"


# ---- one render, however it is asked for ----------------------------------------------------

def test_the_same_submit_id_twice_submits_once(rig):
    a = rig["cli"].post("/api/loom/generate", json=_body()).get_json()
    b = rig["cli"].post("/api/loom/generate", json=_body()).get_json()
    assert a["task_id"] == b["task_id"] == "task-1"
    assert b.get("replay") is True
    assert len(rig["submits"]) == 1


def test_a_second_render_of_the_same_shot_is_refused_until_the_first_finishes(rig):
    rig["cli"].post("/api/loom/generate", json=_body(submit_id="s1"))
    r = rig["cli"].post("/api/loom/generate", json=_body(submit_id="s2"))
    assert r.status_code == 409
    assert "already rendering" in r.get_json()["error"]
    assert "task_id" not in r.get_json(), "the busy answer never looks like an accepted task"
    assert len(rig["submits"]) == 1
    ok = rig["cli"].post("/api/loom/generate", json=_body(submit_id="s3", card="c2"))
    assert ok.get_json()["task_id"], "another shot is fine"


def test_two_racing_posts_for_one_shot_submit_exactly_once(rig):
    """F2: the replay check, the one-render-per-shot check and the 'sending' append are one
    critical section. Two threads, the same card, a slow submit: one send."""
    gate = threading.Event()

    def _slow(params):
        gate.wait(5)
        return "task-slow"
    rig["behaviour"] = _slow
    app = rig["app"]
    clients = [_another_tab(app), _another_tab(app)]
    out = []

    def _go(cli, sid):
        out.append(cli.post("/api/loom/generate", json=_body(submit_id=sid)))
    ts = [threading.Thread(target=_go, args=(clients[0], "sA")),
          threading.Thread(target=_go, args=(clients[1], "sB"))]
    for t in ts:
        t.start()
    deadline = time.time() + 5
    while len(rig["submits"]) < 1 and time.time() < deadline:
        time.sleep(0.01)
    time.sleep(0.2)
    gate.set()
    for t in ts:
        t.join(10)
    assert len(rig["submits"]) == 1
    codes = sorted(r.status_code for r in out)
    assert codes == [200, 409]


def test_a_replay_of_a_send_in_flight_is_unclear_and_never_sent(rig):
    gate = threading.Event()
    rig["behaviour"] = lambda params: (gate.wait(5), "task-x")[1]
    app = rig["app"]
    first = []
    t = threading.Thread(target=lambda: first.append(
        _another_tab(app).post("/api/loom/generate", json=_body(submit_id="sX"))))
    t.start()
    deadline = time.time() + 5
    while not rig["submits"] and time.time() < deadline:
        time.sleep(0.01)
    again = rig["cli"].post("/api/loom/generate", json=_body(submit_id="sX"))
    assert again.status_code == 409 and again.get_json()["state"] == "sending"
    gate.set()
    t.join(10)
    assert len(rig["submits"]) == 1


# ---- what a failure is recorded as (F3) ------------------------------------------------------

def test_a_lost_answer_after_the_send_is_unclear_and_keeps_the_shot_blocked(rig):
    def _lost(params):
        raise ConnectionError("Read timed out")
    rig["behaviour"] = _lost
    r = rig["cli"].post("/api/loom/generate", json=_body(submit_id="s1")).get_json()
    assert r.get("unclear") is True and r["state"] == "may_have_started"
    assert rig["cli"].get("/api/loom/submit-status?submit_id=s1").get_json()["state"] == "may_have_started"
    rig["behaviour"] = None
    again = rig["cli"].post("/api/loom/generate", json=_body(submit_id="s2"))
    assert again.status_code == 409, "no second paid render while the first may exist"
    assert len(rig["submits"]) == 1


def test_a_definite_refusal_is_refused_and_frees_the_shot(rig):
    def _refuse(params):
        raise core.PixAIError("GraphQL error: INSUFFICIENT_BALANCE")
    rig["behaviour"] = _refuse
    r = rig["cli"].post("/api/loom/generate", json=_body(submit_id="s1")).get_json()
    assert r["state"] == "refused" and not r.get("unclear")
    rig["behaviour"] = None
    assert rig["cli"].post("/api/loom/generate", json=_body(submit_id="s2")).get_json()["task_id"]


def test_the_invalid_media_id_fallback_is_journalled(rig):
    """Open call 5 (kept, owner-confirmed): after a synchronous invalid_media_id GraphQL refusal
    the route submits ONE more time. A refusal creates nothing, so that is not a re-send of a
    render that may exist -- but it is a second attempt, and the journal must say so."""
    calls = []

    def _refuse_once(params):
        calls.append(1)
        if len(calls) == 1:
            raise core.PixAIError("GraphQL error: invalid_media_id")
        return "task-after-fallback"
    rig["behaviour"] = _refuse_once
    r = rig["cli"].post("/api/loom/generate", json=_body(submit_id="sF")).get_json()
    assert r["task_id"] == "task-after-fallback"
    assert len(rig["submits"]) == 2, "exactly two submits: the refused passthrough and the fallback"
    st = rig["cli"].get("/api/loom/submit-status?submit_id=sF").get_json()
    assert st == {"state": "submitted", "task_id": "task-after-fallback"}
    jf = rig["tmp"] / "loom" / "_submits" / (_account_key(_TEST_USERNAME) + ".jsonl")
    entry = {}
    for ln in jf.read_text(encoding="utf-8").splitlines():
        rec = json.loads(ln)
        if rec.get("submit_id") == "sF":
            entry.update({k: v for k, v in rec.items() if v is not None})
    assert entry.get("fallback") == "invalid_media_id", "the journal entry carries the fallback mark"
    assert entry.get("state") == "submitted"
    # A refusal that is NOT an invalid media id is never retried.
    rig["submits"].clear()
    rig["behaviour"] = lambda params: (_ for _ in ()).throw(core.PixAIError("GraphQL error: INSUFFICIENT_BALANCE"))
    r2 = rig["cli"].post("/api/loom/generate", json=_body(submit_id="sG", card="c2")).get_json()
    assert r2["state"] == "refused" and len(rig["submits"]) == 1


def test_a_failure_before_the_mutation_is_not_sent(rig, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("no key")
    monkeypatch.setattr(core, "_make_session", _boom)
    r = rig["cli"].post("/api/loom/generate", json=_body(submit_id="s1")).get_json()
    assert r["state"] == "not_sent"
    assert rig["submits"] == []


def test_a_free_quote_whose_card_is_gone_refuses_and_sends_nothing(rig):
    """F13: the confirm was skipped because the shot priced FREE; the card match comes back
    empty at send time, so the route refuses rather than charge credits."""
    r = rig["cli"].post("/api/loom/generate", json=_body(expect_free=True)).get_json()
    assert "free card" in r["error"] and r["state"] == "not_sent"
    assert rig["submits"] == []


def test_a_free_quote_with_its_card_attached_sends(rig, monkeypatch):
    monkeypatch.setattr(core, "_apply_kaisuuken",
                        lambda session, params, args: params.update(kaisuukenId="card-1"))
    r = rig["cli"].post("/api/loom/generate", json=_body(expect_free=True)).get_json()
    assert r["task_id"] and rig["submits"][0]["kaisuukenId"] == "card-1"


# ---- the journal, submit-status, abandon (F8) -----------------------------------------------

def test_the_journal_survives_a_recreated_app(rig):
    rig["cli"].post("/api/loom/generate", json=_body(submit_id="s1"))
    cli2 = login_test_client(create_app(rig["tmp"]))
    st = cli2.get("/api/loom/submit-status?submit_id=s1").get_json()
    assert st == {"state": "submitted", "task_id": "task-1"}
    assert cli2.post("/api/loom/generate", json=_body(submit_id="s2")).status_code == 409
    assert cli2.get("/api/loom/submit-status?submit_id=nope").get_json() == {"state": "unknown"}


def test_task_status_marks_a_journalled_task_finished(rig, monkeypatch):
    rig["cli"].post("/api/loom/generate", json=_body(submit_id="s1"))
    monkeypatch.setattr(core, "generation_status",
                        lambda session, tid: {"phase": "failed", "status": "failed", "reason": ""})
    rig["cli"].get("/api/task-status?task_id=task-1")
    assert rig["cli"].get("/api/loom/submit-status?submit_id=s1").get_json().get("finished") is True
    assert rig["cli"].post("/api/loom/generate", json=_body(submit_id="s2")).get_json()["task_id"]


def test_release_an_unclear_send_then_render_again_never_resends_the_old_one(rig):
    def _lost(params):
        raise ConnectionError("Read timed out")
    rig["behaviour"] = _lost
    rig["cli"].post("/api/loom/generate", json=_body(submit_id="s1"))
    rig["behaviour"] = None
    csrf = _csrf(rig["cli"])
    assert rig["cli"].post("/api/loom/submit-abandon", json={"submit_id": "s1"}).status_code == 403
    assert rig["cli"].post("/api/loom/submit-abandon", json={"csrf": csrf, "submit_id": "s1"}).get_json()["ok"]
    assert rig["cli"].post("/api/loom/generate", json=_body(submit_id="s2")).get_json()["task_id"]
    old = rig["cli"].post("/api/loom/generate", json=_body(submit_id="s1")).get_json()
    assert old["state"] == "abandoned"
    assert len(rig["submits"]) == 2, "one lost send, one new render; s1 is never sent again"


def test_a_send_still_in_flight_cannot_be_released_or_rendered_twice(rig):
    """Spend review B1. PixAI is slow; the owner reloads, the card reads submit-status
    ("sending") and offers the release; the owner releases. The request is still inside
    core.submit, so releasing it would free the shot for a second paid render while the first
    completes. The release must be refused while the request runs, and exactly one submit may
    happen."""
    gate = threading.Event()
    rig["behaviour"] = lambda params: (gate.wait(5), "task-slow")[1]
    app = rig["app"]
    first = []
    t = threading.Thread(target=lambda: first.append(
        _another_tab(app).post("/api/loom/generate", json=_body(submit_id="sSlow"))))
    t.start()
    try:
        deadline = time.time() + 5
        while not rig["submits"] and time.time() < deadline:
            time.sleep(0.01)
        assert rig["submits"], "the first render reached the mutation"
        assert rig["cli"].get("/api/loom/submit-status?submit_id=sSlow").get_json()["state"] == "sending"
        rel = rig["cli"].post("/api/loom/submit-abandon", json={"csrf": _csrf(rig["cli"]), "submit_id": "sSlow"})
        assert rel.status_code == 409 and rel.get_json().get("sending") is True
        again = rig["cli"].post("/api/loom/generate", json=_body(submit_id="sNew"))
        assert again.status_code == 409 and "already rendering" in again.get_json()["error"]
    finally:
        gate.set()
        t.join(10)
    assert first and first[0].get_json()["task_id"] == "task-slow"
    assert len(rig["submits"]) == 1, "one shot, one paid render"
    st = rig["cli"].get("/api/loom/submit-status?submit_id=sSlow").get_json()
    assert st == {"state": "submitted", "task_id": "task-slow"}, "the release never landed"
    # The request is over: the ordinary rule applies again (a sent render is adopted, not released).
    done = rig["cli"].post("/api/loom/submit-abandon", json={"csrf": _csrf(rig["cli"]), "submit_id": "sSlow"})
    assert done.status_code == 409 and done.get_json()["task_id"] == "task-slow"


def test_a_send_that_died_with_an_earlier_process_can_still_be_released(tmp_path):
    """B1's other half (F8 kept): the in-flight set is per process, so a journal line that
    says "sending" for a request no running process owns (a crash mid-send) can be released."""
    d = tmp_path / "loom" / "_submits"
    d.mkdir(parents=True, exist_ok=True)
    now = time.time()
    (d / (_account_key(_TEST_USERNAME) + ".jsonl")).write_text(json.dumps(
        {"submit_id": "sDead", "board": "b1", "card": "c1", "state": "sending", "at": now,
         "first_at": now}) + "\n", encoding="utf-8")
    cli = login_test_client(create_app(tmp_path))
    assert cli.post("/api/loom/generate", json=_body(submit_id="sAfter")).status_code == 409, \
        "the dead send still holds the shot until it is released"
    r = cli.post("/api/loom/submit-abandon", json={"csrf": _csrf(cli), "submit_id": "sDead"})
    assert r.status_code == 200 and r.get_json()["ok"]
    assert cli.get("/api/loom/submit-status?submit_id=sDead").get_json()["state"] == "abandoned"


def test_a_sent_render_cannot_be_released(rig):
    rig["cli"].post("/api/loom/generate", json=_body(submit_id="s1"))
    r = rig["cli"].post("/api/loom/submit-abandon", json={"csrf": _csrf(rig["cli"]), "submit_id": "s1"})
    assert r.status_code == 409 and r.get_json()["task_id"] == "task-1"


def test_an_unknown_submit_id_after_a_prune_can_be_released(rig):
    r = rig["cli"].post("/api/loom/submit-abandon", json={"csrf": _csrf(rig["cli"]), "submit_id": "gone"})
    assert r.get_json()["ok"]


def test_old_journal_lines_are_pruned_on_first_read(tmp_path, monkeypatch):
    app = create_app(tmp_path)
    cli = login_test_client(app)
    d = tmp_path / "loom" / "_submits"
    d.mkdir(parents=True, exist_ok=True)
    f = d / (_account_key("tester") + ".jsonl")
    old = time.time() - 15 * 24 * 3600
    f.write_text(json.dumps({"submit_id": "old", "state": "submitted", "task_id": "t", "at": old, "first_at": old})
                 + "\n" + json.dumps({"submit_id": "new", "state": "sending", "at": time.time(),
                                      "first_at": time.time()}) + "\n", encoding="utf-8")
    assert cli.get("/api/loom/submit-status?submit_id=old").get_json()["state"] == "unknown"
    assert cli.get("/api/loom/submit-status?submit_id=new").get_json()["state"] == "sending"
    assert "old" not in f.read_text(encoding="utf-8")


# ---- the free routes never spend -------------------------------------------------------------

def test_the_new_routes_and_the_handoff_never_reach_a_submit(rig, monkeypatch):
    def _no(*a, **k):
        raise AssertionError("a spend function was called")
    for name in ("submit", "submit_generation", "build_request", "gql_mutate"):
        monkeypatch.setattr(core, name, _no)
    rig["cli"].get("/api/loom/submit-status?submit_id=s1")
    rig["cli"].post("/api/loom/submit-abandon", json={"csrf": _csrf(rig["cli"]), "submit_id": "s1"})
    r = rig["cli"].post("/api/loom/handoff", json={"video_media_id": MID, "trim_out": 3.0})
    assert r.status_code == 200    # "clip not downloaded yet" -- and no submit on the way


def test_the_handoff_source_names_no_spend_call():
    import ast
    import inspect
    import moonglade_gallery
    src = inspect.getsource(moonglade_gallery)
    for fn in ("def loom_handoff", "def loom_submit_status", "def loom_submit_abandon"):
        i = src.index(fn)
        body = src[i:src.index("\n    @app.route", i)]
        for bad in ("core.submit(", "submit_generation(", "build_request(", "gql_mutate(", "gql_adhoc("):
            assert bad not in body, "%s reaches %s" % (fn, bad)
    ast.parse(src)


# ---- the board store: revisions, compare-and-swap, unreadable (F15, N5) ----------------------

def _kv(tmp_path, user="tester"):
    return tmp_path / "loom" / "kv" / _account_key(user)


def test_get_hands_back_a_rev_and_a_stale_base_rev_is_refused(rig):
    cli = rig["cli"]
    key = "storyboard:v2:proj:A"
    first = cli.get("/api/loom/get?key=" + key).get_json()
    assert first == {"value": None, "missing": True, "rev": "missing"}
    w = cli.post("/api/loom/set", json={"key": key, "value": "{\"v\":1}", "base_rev": "missing"}).get_json()
    assert w["ok"] and w["rev"] != "missing"
    got = cli.get("/api/loom/get?key=" + key).get_json()
    assert got["rev"] == w["rev"] and got["value"] == "{\"v\":1}"
    stale = cli.post("/api/loom/set", json={"key": key, "value": "{\"v\":2}", "base_rev": "missing"})
    assert stale.status_code == 409
    body = stale.get_json()
    assert body["conflict"] and body["value"] == "{\"v\":1}" and body["rev"] == w["rev"]
    assert cli.get("/api/loom/get?key=" + key).get_json()["value"] == "{\"v\":1}", "the file is unchanged"
    ok = cli.post("/api/loom/set", json={"key": key, "value": "{\"v\":2}", "base_rev": w["rev"]}).get_json()
    assert ok["ok"]
    plain = cli.post("/api/loom/set", json={"key": key, "value": "{\"v\":3}"}).get_json()
    assert plain["ok"], "without base_rev: today's last-writer-wins"


def test_a_corrupt_own_board_is_unreadable_never_missing(rig):
    cli = rig["cli"]
    cli.post("/api/loom/set", json={"key": "k", "value": "x"})
    (_kv(rig["tmp"]) / "k.json").write_text("{not json", encoding="utf-8")
    r = cli.get("/api/loom/get?key=k")
    assert r.status_code == 500 and r.get_json()["error"] == "unreadable"


def test_a_corrupt_legacy_board_is_unreadable_too(rig):
    """F15b: the legacy fallback returned None for a corrupt file, so the client seeded a
    blank board into the account's own key and shadowed the legacy board forever."""
    leg = rig["tmp"] / "loom" / "kv"
    leg.mkdir(parents=True, exist_ok=True)
    (leg / "legacykey.json").write_text("{nope", encoding="utf-8")
    r = rig["cli"].get("/api/loom/get?key=legacykey")
    assert r.status_code == 500


def test_the_first_save_of_a_board_inherited_from_the_legacy_layer(rig):
    """N5: the rev follows the read's own resolution, so a legacy board saves on its rev."""
    leg = rig["tmp"] / "loom" / "kv"
    leg.mkdir(parents=True, exist_ok=True)
    (leg / "inherited.json").write_text(json.dumps("{\"old\":1}"), encoding="utf-8")
    got = rig["cli"].get("/api/loom/get?key=inherited").get_json()
    assert got["value"] == "{\"old\":1}" and got["rev"] not in ("missing", None)
    w = rig["cli"].post("/api/loom/set", json={"key": "inherited", "value": "{\"new\":1}",
                                               "base_rev": got["rev"]})
    assert w.status_code == 200 and w.get_json()["ok"]
