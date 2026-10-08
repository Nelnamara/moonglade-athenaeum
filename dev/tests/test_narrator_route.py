"""POST /api/narrator/poke: the route that carries the narrator's poke ladder.

The pure ladder is dev/tests/test_narrator_ladder.py. What is pinned here is everything around it:
that the SERVER keeps the count and the clocks (per account, where the account cannot write
them), that the reply tells the page a line and nothing else, that a poke that does not count
answers like one that does, that the metric the feat reads follows the count, that the final
straw earns the feat through the ordinary achievement path, and that nothing else is written.

Every roster and every line here is SYNTHETIC (dev/tests/synthetic_feats.py): the real pack's
lines are not test material. Nothing needs the private donor except the one scan at the
bottom, which is gated on it.
"""
import json
import random

import pytest

from moonglade import gallery as g
from moonglade import narrator as nar
from moonglade.gallery import CATALOG_FIELDS, save_catalog

from tests import synthetic_feats as sf
from tests.conftest import _SEALED_DONOR, login_client, login_test_client

URL = "/api/narrator/poke"
LINES = {
    "stages": {"oblivious": ["test line one", "test line two"], "irritated": ["test irritated"]},
    "spam": ["test spam line"], "walked_off": ["test walked-off line"],
    "walk_off": ["test walk-off line"],
}


class Clock:
    """The route's clock seam, driven by the test: `g._narrator_clock` answers this."""
    def __init__(self, t=9 * 3600.0):
        self.t = t

    def __call__(self):
        return self.t, "day-%d" % int(self.t // 86400)

    def advance(self, s):
        self.t += s

    def next_day(self):
        self.t = (int(self.t // 86400) + 1) * 86400 + 9 * 3600.0


@pytest.fixture()
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(g, "_narrator_clock", c)
    yield c


@pytest.fixture(autouse=True)
def _fresh_earned_cache():
    g._earned_ids_cache.update(t=0.0, ids=frozenset())
    yield
    g._earned_ids_cache.update(t=0.0, ids=frozenset())


def _client(tmp_path, poke_lines=LINES, **seed_kw):
    """A logged-in client on an install whose sealed pack is the synthetic one."""
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "1", "filename": "a_1.png", "created_at": "2025-01-01T00:00:00"}])
    sf.seed(g._container_path(), poke_lines=poke_lines, **seed_kw)
    return login_client(tmp_path)


def _token(cli):
    return cli.get("/api/account/prefs").get_json()["csrf"]


def _poke(cli, csrf=None):
    return cli.post(URL, json={"csrf": _token(cli) if csrf is None else csrf})


def _state_dir(tmp_path, user="tester"):
    """The login's server-only state file (accounts/<key>/state.json): "nothing was
    written" means it does not exist."""
    return g.account_state_path(tmp_path, user)


def _ladder(tmp_path, user="tester"):
    p = g.account_state_path(tmp_path, user)
    return g.account_state_read(p).get("ladder")


def _count(tmp_path, user="tester"):
    return (_ladder(tmp_path, user) or {}).get("count", 0)


# ---- who may poke, and what a refusal writes --------------------------------------------------

def test_a_poke_needs_a_signed_in_session(tmp_path):
    app = g.create_app(tmp_path)
    r = app.test_client().post(URL, json={"csrf": "x"})
    assert r.status_code in (302, 401, 403)
    assert not _state_dir(tmp_path).exists()


@pytest.mark.parametrize("body", [{}, {"csrf": ""}, {"csrf": "not-the-token"}])
def test_a_poke_without_the_session_token_is_refused_and_writes_nothing(tmp_path, clock, body):
    cli = _client(tmp_path)
    r = cli.post(URL, json=body)
    assert r.status_code == 400 and "session expired" in r.get_json()["error"]
    assert not _state_dir(tmp_path).exists()
    assert "narrator_pokes" not in g.telemetry_metrics(tmp_path)


def test_a_body_that_is_not_an_object_is_refused(tmp_path, clock):
    cli = _client(tmp_path)
    assert cli.post(URL, json=[1, 2]).status_code == 400
    assert cli.post(URL, data="nope", content_type="text/plain").status_code == 400
    assert not _state_dir(tmp_path).exists()


# ---- what the page is told ---------------------------------------------------------------------

def test_the_reply_is_a_line_and_nothing_else(tmp_path, clock):
    """No count, no stage, no clock, no hint of whether it counted: the page cannot learn
    how far along it is from anything the route sends."""
    cli = _client(tmp_path)
    counted = _poke(cli).get_json()
    clock.advance(0.5)
    refused = _poke(cli).get_json()                      # inside the two seconds
    for d in (counted, refused):
        assert set(d) == {"ok", "line"}, sorted(d)
        assert d["ok"] is True and isinstance(d["line"], str) and d["line"]
    assert counted["line"] in ("test line one", "test line two")
    assert refused["line"] == "test spam line"
    body = json.dumps([counted, refused])
    assert '"count"' not in body and "stage" not in body and "counted" not in body


def test_a_poke_that_does_not_count_still_gets_a_line_and_never_advances(tmp_path, clock):
    cli = _client(tmp_path)
    _poke(cli)
    assert _count(tmp_path) == 1
    for _i in range(5):
        clock.advance(0.3)
        d = _poke(cli).get_json()
        assert d["line"] == "test spam line"
    assert _count(tmp_path) == 1
    clock.advance(1.0)
    _poke(cli)
    assert _count(tmp_path) == 2


def test_a_pack_with_no_lines_answers_a_bare_ellipsis(tmp_path, clock):
    cli = _client(tmp_path, poke_lines=None)
    assert _poke(cli).get_json()["line"] == "…"
    clock.advance(0.1)
    assert _poke(cli).get_json()["line"] == "…"
    assert _count(tmp_path) == 1, "with no lines the poke still counted"


@pytest.mark.parametrize("field", [{"stages": "nope", "spam": 7}, "not an object", 7, [1, 2]])
def test_a_malformed_pack_field_degrades_to_the_ellipsis_not_an_error(tmp_path, clock, field):
    cli = _client(tmp_path, poke_lines=field)
    r = _poke(cli)
    assert r.status_code == 200 and r.get_json()["line"] == "…"


# ---- where the state lives, and who can move it ------------------------------------------------

def test_the_count_is_kept_per_account(tmp_path, clock):
    _client(tmp_path)                                    # seeds the pack + the first account
    app = g.create_app(tmp_path)
    a = login_test_client(app)
    b = login_test_client(app, username="other", password="a-real-test-password-2")
    for _i in range(3):
        _poke(a)
        clock.advance(3)
    _poke(b)
    assert _count(tmp_path, "tester") == 3 and _count(tmp_path, "other") == 1


def test_the_installs_metric_is_the_highest_account_not_the_sum(tmp_path, clock):
    _client(tmp_path)
    app = g.create_app(tmp_path)
    a = login_test_client(app)
    b = login_test_client(app, username="other", password="a-real-test-password-2")
    for _i in range(3):
        _poke(a)
        clock.advance(3)
    assert g.telemetry_metrics(tmp_path)["narrator_pokes"] == 3
    for _i in range(2):
        _poke(b)
        clock.advance(3)
    assert g.telemetry_metrics(tmp_path)["narrator_pokes"] == 3, "two accounts never pool"
    for _i in range(2):
        _poke(b)
        clock.advance(3)
    assert g.telemetry_metrics(tmp_path)["narrator_pokes"] == 4


def test_only_a_counted_poke_moves_the_metric(tmp_path, clock):
    cli = _client(tmp_path)
    _poke(cli)
    clock.advance(0.5)
    _poke(cli)                                           # spam: not counted
    assert g.telemetry_metrics(tmp_path)["narrator_pokes"] == 1


def test_the_browser_cannot_write_or_read_the_ladder_through_the_prefs_store(tmp_path, clock):
    cli = _client(tmp_path)
    tok = _token(cli)
    for _i in range(2):
        _poke(cli)
        clock.advance(3)
    prefs = cli.get("/api/account/prefs").get_json()["prefs"]
    assert prefs == {}, "the ladder is not in the account's own document"
    # a forged 'ladder' in the account document changes nothing about the real count
    r = cli.post("/api/account/prefs", json={"csrf": tok, "set": {
        "ladder": {"count": 99}, "narrator": {"count": 99}}})
    assert r.status_code == 200
    clock.advance(3)
    d = _poke(cli).get_json()
    assert _count(tmp_path) == 3 and d["line"] in ("test line one", "test line two")


def test_the_beacon_is_not_a_second_road_to_the_count(tmp_path, clock):
    from tests.conftest import ach_event
    cli = _client(tmp_path)
    assert ach_event(cli, "narrator").status_code == 400
    assert "narrator_pokes" not in g.telemetry_metrics(tmp_path)
    assert not _state_dir(tmp_path).exists()


def test_the_state_file_holds_no_line_text_and_survives_a_restart(tmp_path, clock):
    cli = _client(tmp_path)
    _poke(cli)
    raw = g.account_state_path(tmp_path, "tester").read_text(encoding="utf-8")
    assert "test line" not in raw and "test spam" not in raw, "ids, never the words"
    # a fresh app on the same library keeps the count
    cli2 = login_test_client(g.create_app(tmp_path))
    clock.advance(3)
    _poke(cli2)
    assert _count(tmp_path) == 2


def test_a_torn_state_file_reads_as_fresh_and_the_poke_still_works(tmp_path, clock):
    cli = _client(tmp_path)
    _poke(cli)
    p = g.account_state_path(tmp_path, "tester")
    p.write_text("{not json", encoding="utf-8")
    clock.advance(3)
    r = _poke(cli)
    assert r.status_code == 200
    assert _count(tmp_path) == 1


def test_nothing_else_is_written(tmp_path, clock):
    cli = _client(tmp_path)
    before = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    _poke(cli)
    after = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    new = sorted(after - before)
    key = g._account_key("tester")
    # the library's app folder: the login's own folder, and the records
    assert set(new) <= {"_moonglade/accounts/%s/state.json" % key,
                        "_moonglade/records/telemetry.json",
                        "_moonglade/records/achievements.json"}, new
    assert "_moonglade/accounts/%s/state.json" % key in new
    assert not [n for n in after if n.endswith((".lock", ".tmp")) or ".tmp-" in n], "leftover"


def test_the_day_is_the_servers_local_day_the_app_uses_elsewhere():
    import datetime
    t, day = g._narrator_clock()
    assert day == datetime.date.today().isoformat()
    assert abs(t - datetime.datetime.now().timestamp()) < 5


# ---- the ladder through the route: walk-off, days ---------------------------------------------

def test_the_walk_off_and_the_next_day_through_the_route(tmp_path, clock):
    cli = _client(tmp_path)
    for _i in range(nar.WALK_OFF_AT):
        _poke(cli)
        clock.advance(3)
    assert _count(tmp_path) == nar.WALK_OFF_AT
    d = _poke(cli).get_json()
    assert d["line"] == "test walked-off line" and _count(tmp_path) == nar.WALK_OFF_AT
    clock.next_day()
    _poke(cli)
    assert _count(tmp_path) == nar.WALK_OFF_AT + 1


def test_many_pokes_at_one_instant_count_once(tmp_path, clock):
    cli = _client(tmp_path)
    tok = _token(cli)
    for _i in range(60):
        assert _poke(cli, csrf=tok).status_code == 200
    assert _count(tmp_path) == 1 and g.telemetry_metrics(tmp_path)["narrator_pokes"] == 1


# ---- the final straw --------------------------------------------------------------------------

def _at_the_edge(tmp_path, cli, clock, user="tester"):
    """Put the account one counted poke from the end, as the ladder itself would have."""
    st = dict(nar.new_state(), count=nar.FINAL - 1, last_at=clock.t - 10 ** 6, day="day-0")
    g.account_state_write(g.account_state_path(tmp_path, user), {"ladder": st})
    g.telem_max("narrator_pokes", nar.FINAL - 1, out_dir=tmp_path)


def test_the_last_poke_earns_the_feat_through_the_achievement_path(tmp_path, clock):
    cli = _client(tmp_path, ladder_feat=True)
    first = cli.get("/api/achievements").get_json()
    assert first["unleash_available"] is False
    _at_the_edge(tmp_path, cli, clock)
    assert cli.get("/api/achievements").get_json()["unleash_available"] is False, (
        "one short of the end earns nothing")
    d = _poke(cli).get_json()
    assert d["final"] == {"id": sf.TRIGGER_ID, "clean": "synthetic clean roast trig",
                          "unleashed": "synthetic unleashed roast trig"}
    assert d["line"] == "synthetic clean roast trig", "the ORIGINAL snap line, the feat's own"
    after = cli.get("/api/achievements").get_json()
    assert after["unleash_available"] is True
    trg = [a for a in after["achievements"] if a["id"] == sf.TRIGGER_ID][0]
    assert trg["earned"] and trg["roast_nsfw"] == "synthetic unleashed roast trig"
    assert _count(tmp_path) == nar.FINAL


def test_the_final_carries_the_packs_choice_words_and_only_those(tmp_path, clock):
    words = {"title": "test choice title", "keep": "test keep", "unleash": "test unleash",
             "foot": "test foot", "extra": "test never sent"}
    cli = _client(tmp_path, ladder_feat=True, poke_lines=dict(LINES, choice=words))
    _at_the_edge(tmp_path, cli, clock)
    d = _poke(cli).get_json()
    assert d["final"]["choice"] == {"title": "test choice title", "keep": "test keep",
                                    "unleash": "test unleash", "foot": "test foot"}
    cli2 = _client(tmp_path, ladder_feat=True)            # a pack with no choice words
    clock.advance(nar.SLOW_GAP_S)
    st = dict(nar.new_state(), count=nar.FINAL - 1, last_at=clock.t - 10 ** 6, day="d")
    g.account_state_write(g.account_state_path(tmp_path, "tester"), {"ladder": st})
    assert "choice" not in _poke(cli2).get_json()["final"]


def test_no_poke_before_the_last_carries_a_final_or_the_unleashed_line(tmp_path, clock):
    cli = _client(tmp_path, ladder_feat=True)
    for _i in range(6):
        d = _poke(cli).get_json()
        assert "final" not in d and "unleashed" not in json.dumps(d)
        clock.advance(3)


def test_after_the_end_a_poke_answers_and_counts_nothing_more(tmp_path, clock):
    cli = _client(tmp_path, ladder_feat=True, poke_lines={"done": ["test after line"]})
    _at_the_edge(tmp_path, cli, clock)
    assert "final" in _poke(cli).get_json()
    clock.advance(nar.SLOW_GAP_S)
    d = _poke(cli).get_json()
    assert d == {"ok": True, "line": "test after line"}
    assert _count(tmp_path) == nar.FINAL


def test_a_pack_whose_feat_is_not_wired_to_the_ladder_still_ends_cleanly(tmp_path, clock):
    """No roster entry reads the ladder's metric (an old pack): the last poke answers a
    bare final with no lines and no id, and earns nothing -- it never invents copy."""
    cli = _client(tmp_path, ladder_feat=False)
    _at_the_edge(tmp_path, cli, clock)
    d = _poke(cli).get_json()
    assert d["final"] == {} and d["line"] == "…"
    assert cli.get("/api/achievements").get_json()["unleash_available"] is False


def test_the_metric_is_repaired_by_a_later_poke_if_the_first_write_was_lost(tmp_path, clock):
    cli = _client(tmp_path, ladder_feat=True)
    st = dict(nar.new_state(), count=nar.FINAL, last_at=clock.t - 10 ** 6, day="day-0")
    g.account_state_write(g.account_state_path(tmp_path, "tester"), {"ladder": st})
    assert "narrator_pokes" not in g.telemetry_metrics(tmp_path)
    _poke(cli)
    assert g.telemetry_metrics(tmp_path)["narrator_pokes"] == nar.FINAL


# ---- the sealed pack's lines never reach public source ---------------------------------------

def test_sealed_poke_lines_never_appear_in_public_files(sealed_donor_present):
    """When the private donor carries the ladder's lines, no one of them may sit in any
    committed public file, built bundle or doc (the same scan the roasts get). A donor that
    does not carry them yet has nothing to leak: the test says so and stops."""
    from pathlib import Path
    donor = json.loads(_SEALED_DONOR.read_text(encoding="utf-8"))
    pools = nar.clean_pools(donor.get("poke_lines"))
    needles = sorted({e[0][:40] for ents in pools.values() for e in ents if len(e[0]) >= 12})
    if not needles:
        pytest.skip("the donor carries no poke lines yet")
    from tests.test_no_spoiler_leak import _files_to_scan
    repo = Path(__file__).resolve().parents[2]
    leaks = set()
    for path in _files_to_scan():
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(n in text for n in needles):
            leaks.add(str(path.relative_to(repo)))
    assert not leaks, "sealed poke lines found in public files: %s" % sorted(leaks)
