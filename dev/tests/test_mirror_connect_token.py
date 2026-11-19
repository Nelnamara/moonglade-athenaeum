"""Connect from PixAI, and the Mirror's renewal surviving a closed spell (2026-11-18).

PixAI moved its sign-in where no outside program can read it, so the old Connect (the server
reading this machine's browser store) finds nothing. The Control Panel now offers a bookmark
the user clicks on a signed-in pixai.art tab; it opens /mirror/connect here, which posts the
tab's sign-in to POST /api/mirror/connect-token. That route is login-gated, CSRF-checked and
same-origin only, refuses under READ_ONLY, and stores the token only when it is a PixAI JWT,
unexpired, and for the SAME PixAI account the API key resolves to (invariant #7). It never
echoes the token, in a response or in the log.

The renewal regression: with a 3-day cushion, a token renewed on 2 Nov was not due until
6 Nov; the server went down ten hours before that and was not started again until 11 Nov, by
when the token had expired and could not renew itself. The test replays that timeline.

Offline throughout: the API-key account lookup and the renewal POST are stubbed."""
import base64
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from moonglade import backup as mj
from moonglade import mirror as mirror_mod
from tests.conftest import login_client, with_csrf

DAY = 86400
ME = "1600000000000000001"
ROUTE = "/api/mirror/connect-token"


def _b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")


def _jwt(exp, sub=ME, iss="pixai", salt=""):
    claims = {"exp": int(exp), "sub": sub, "iss": iss}
    if salt:
        claims["jti"] = salt
    return _b64({"alg": "HS256", "typ": "JWT"}) + "." + _b64(claims) + ".c2ln"


def _in(days, **k):
    import time
    return _jwt(time.time() + days * DAY, **k)


@pytest.fixture
def armed(tmp_path, monkeypatch):
    """A stored-state file in tmp, READ_ONLY off, and an API key that resolves to ME."""
    p = tmp_path / "mirror_session.json"
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: p)
    monkeypatch.setattr(mj, "READ_ONLY", False)
    monkeypatch.setattr(mj, "_read_only_now", lambda: False)
    looked = []
    monkeypatch.setattr(mj, "_make_session", lambda *a, **k: SimpleNamespace(user_id=""))
    monkeypatch.setattr(mj, "resolve_user_id", lambda s: looked.append(1) or ME)
    return SimpleNamespace(path=p, looked=looked)


def _post(cli, token, **extra):
    return cli.post(ROUTE, json=with_csrf(cli, dict({"token": token}, **extra)))


# ---- the route accepts the right sign-in ------------------------------------------------

def test_a_same_account_sign_in_is_stored_and_the_backoff_cleared(tmp_path, armed, caplog):
    caplog.set_level(logging.DEBUG)
    cli = login_client(tmp_path)
    mirror_mod._mirror_renewal.update(fails=4, next_try=9e12, failed_exp=123, last_reason="http_401")
    tok = _in(7)
    r = _post(cli, tok)
    assert r.status_code == 200
    d = r.get_json()
    assert d == {"ok": True, "days_left": 6}
    assert mirror_mod.load_mirror_state() == {"jwt": tok}            # JWT-only, no minted_at
    rr = mirror_mod._mirror_renewal
    assert (rr["fails"], rr["next_try"], rr["failed_exp"], rr["last_reason"]) == (0, 0.0, None, "")
    assert tok not in r.get_data(as_text=True)
    assert tok not in caplog.text and ME not in r.get_data(as_text=True)


# ---- ...and refuses everything else, storing nothing -----------------------------------

@pytest.mark.parametrize("why, token, says", [
    ("another account", lambda: _in(7, sub="1600000000000000999"), "different PixAI account"),
    ("not PixAI's", lambda: _in(7, iss="intercom"), "wasn't issued by PixAI"),
    ("expired", lambda: _in(-0.01), "already expired"),
    ("not a JWT", lambda: "hello there", "isn't a PixAI sign-in"),
    ("two segments", lambda: "eyJhIjoxfQ.eyJiIjoyfQ", "isn't a PixAI sign-in"),
    ("not a string", lambda: {"token": "x"}, "isn't a PixAI sign-in"),
    ("missing", lambda: None, "isn't a PixAI sign-in"),
])
def test_a_bad_sign_in_is_refused_and_nothing_is_stored(tmp_path, armed, caplog, why, token, says):
    caplog.set_level(logging.DEBUG)
    cli = login_client(tmp_path)
    before = _in(3, salt="before")
    mirror_mod.save_mirror_state({"jwt": before})
    tok = token()
    d = _post(cli, tok).get_json()
    assert d["ok"] is False and says in d["error"], why
    assert mirror_mod.load_mirror_state()["jwt"] == before, why          # untouched
    if isinstance(tok, str):
        assert tok not in json.dumps(d) and tok not in caplog.text, why


def test_offline_refusals_never_look_the_account_up(tmp_path, armed):
    """A junk or foreign-issuer token is turned away before the API key is asked anything."""
    cli = login_client(tmp_path)
    _post(cli, "not.a.jwt!")
    _post(cli, _in(7, iss="intercom"))
    _post(cli, _in(-1))
    assert armed.looked == []


def test_the_api_key_itself_is_refused(tmp_path, armed, monkeypatch):
    key = _in(30)                                    # a JWT-shaped key, iss pixai, our sub
    monkeypatch.setitem(mj._cfg, "PIXAI_API_KEY", key)
    cli = login_client(tmp_path)
    d = _post(cli, key).get_json()
    assert d["ok"] is False and "isn't a PixAI sign-in" in d["error"]
    assert mirror_mod.load_mirror_state() == {}


def test_an_account_that_cannot_be_confirmed_refuses(tmp_path, armed, monkeypatch):
    """A real key problem (none set up, or PixAI refusing it) says to check the key."""
    def _no_key(*a, **k):
        raise mj.PixAIError("No API key found.")
    monkeypatch.setattr(mj, "_make_session", _no_key)
    cli = login_client(tmp_path)
    d = _post(cli, _in(7)).get_json()
    assert d["ok"] is False and "Check that the API key is set up" in d["error"]
    monkeypatch.setattr(mj, "_make_session", lambda *a, **k: SimpleNamespace(user_id=""))
    monkeypatch.setattr(mj, "resolve_user_id", lambda s: (_ for _ in ()).throw(
        mj.PixAIError("401 Unauthorized -- API key missing/expired.")))
    d = _post(cli, _in(7)).get_json()
    assert d["ok"] is False and "Check that the API key is set up" in d["error"]
    assert mirror_mod.load_mirror_state() == {}


def test_a_refused_key_checks_against_the_stored_signins_account(tmp_path, armed, monkeypatch):
    """PixAI refusing the key (2026-11-19, a lapsed membership) must not lock the owner out of
    reconnecting: the account the STORED sign-in names -- confirmed against this key when it
    was connected -- answers instead, even once that sign-in has expired. Another account's
    token is still refused, and with nothing stored the account cannot be confirmed at all."""
    monkeypatch.setattr(mj, "resolve_user_id", lambda s: (_ for _ in ()).throw(
        mj.PixAIAuthError("401 Unauthorized -- API key missing/expired.")))
    cli = login_client(tmp_path)
    d = _post(cli, _in(7)).get_json()
    assert d["ok"] is False and "Check that the API key is set up" in d["error"]
    mirror_mod.save_mirror_state({"jwt": _in(-2)})                        # expired, ours
    d = _post(cli, _in(7, sub="1600000000000000999")).get_json()
    assert d["ok"] is False and "different PixAI account" in d["error"]
    tok = _in(7)
    assert _post(cli, tok).get_json()["ok"] is True
    assert mirror_mod.load_mirror_state()["jwt"] == tok


@pytest.mark.parametrize("err", [
    requests.ConnectionError("no route to host"),
    requests.Timeout("read timed out"),
    requests.HTTPError("503 Server Error"),
])
def test_pixai_out_of_reach_says_so(tmp_path, armed, monkeypatch, err):
    """No connection, a timeout or a 5xx while asking which account the key is: the words
    say PixAI couldn't be reached, not that the key is wrong."""
    monkeypatch.setattr(mj, "resolve_user_id", lambda s: (_ for _ in ()).throw(err))
    cli = login_client(tmp_path)
    d = _post(cli, _in(7)).get_json()
    assert d == {"ok": False, "error": "Couldn't reach PixAI to check which account this is. "
                                       "Try again in a minute."}
    assert mirror_mod.load_mirror_state() == {}


def test_a_pinned_user_id_does_not_decide_the_account(tmp_path, armed, monkeypatch):
    """USER_ID pinned in config.json names another account than the key really is: a token
    for the PINNED id is refused, because the check asks PixAI, not the config."""
    pinned = "1600000000000000777"
    monkeypatch.setattr(mj, "USER_ID", pinned)
    monkeypatch.setattr(mj, "_make_session",
                        lambda *a, **k: SimpleNamespace(user_id=pinned))   # what the pin feeds
    cli = login_client(tmp_path)
    d = _post(cli, _in(7, sub=pinned)).get_json()
    assert d["ok"] is False and "different PixAI account" in d["error"]
    assert mirror_mod.load_mirror_state() == {} and armed.looked == [1]
    assert _post(cli, _in(7)).get_json()["ok"] is True                  # the real account is


def test_a_token_claiming_too_long_a_life_is_refused(tmp_path, armed):
    cli = login_client(tmp_path)
    d = _post(cli, _in(29)).get_json()
    assert d["ok"] is False and "longer than any PixAI sign-in" in d["error"]
    assert mirror_mod.load_mirror_state() == {} and armed.looked == []
    assert _post(cli, _in(27.5)).get_json()["ok"] is True               # within the ceiling


def test_an_older_token_never_replaces_a_later_one_for_the_same_account(tmp_path, armed):
    cli = login_client(tmp_path)
    stored = _in(6.8, salt="stored")
    mirror_mod.save_mirror_state({"jwt": stored})
    mirror_mod._mirror_renewal.update(fails=2, failed_exp=1, next_try=9e12)
    d = _post(cli, _in(6.0, salt="older")).get_json()
    assert d == {"ok": True, "days_left": 6}                           # the stored one's days
    assert mirror_mod.load_mirror_state()["jwt"] == stored
    assert mirror_mod._mirror_renewal["fails"] == 0
    newer = _in(6.95, salt="newer")
    assert _post(cli, newer).get_json()["ok"] is True
    assert mirror_mod.load_mirror_state()["jwt"] == newer             # a later one does replace
    # a later-expiring token for ANOTHER account is never kept over this account's
    mirror_mod.save_mirror_state({"jwt": _in(20, sub="1600000000000000999")})
    mine = _in(6.9, salt="mine")
    assert _post(cli, mine).get_json()["ok"] is True
    assert mirror_mod.load_mirror_state()["jwt"] == mine


def test_read_only_refuses_before_anything(tmp_path, armed, monkeypatch):
    monkeypatch.setattr(mj, "_read_only_now", lambda: True)
    cli = login_client(tmp_path)
    d = _post(cli, _in(7)).get_json()
    assert d["ok"] is False and "READ_ONLY" in d["error"]
    assert mirror_mod.load_mirror_state() == {} and armed.looked == []


# ---- the request protections -----------------------------------------------------------

def test_signed_out_is_refused(tmp_path, armed):
    from moonglade.gallery import create_app
    cli = create_app(tmp_path).test_client()
    r = cli.post(ROUTE, json={"token": _in(7)})
    assert r.status_code == 401
    assert mirror_mod.load_mirror_state() == {} and armed.looked == []


def test_no_csrf_token_is_refused(tmp_path, armed):
    cli = login_client(tmp_path)
    r = cli.post(ROUTE, json={"token": _in(7)})
    assert r.status_code == 400 and "session expired" in r.get_json()["error"]
    r = cli.post(ROUTE, json={"token": _in(7), "csrf": "guess"})
    assert r.status_code == 400
    assert mirror_mod.load_mirror_state() == {}


def test_a_cross_origin_request_is_refused_even_with_the_token(tmp_path, armed):
    """A page on another site cannot read the CSRF token; even if it had it, an Origin naming
    another site is refused. The page's own same-origin POST passes."""
    cli = login_client(tmp_path)
    tok = _in(7)
    r = cli.post(ROUTE, json=with_csrf(cli, {"token": tok}),
                 headers={"Origin": "https://pixai.art"})
    assert r.status_code == 403 and mirror_mod.load_mirror_state() == {}
    r = cli.post(ROUTE, data="token=" + tok, content_type="application/x-www-form-urlencoded",
                 headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and mirror_mod.load_mirror_state() == {}
    r = cli.post(ROUTE, json=with_csrf(cli, {"token": tok}), headers={"Origin": "http://localhost"})
    assert r.get_json()["ok"] is True                                  # the test client's own host


@pytest.mark.parametrize("addr, home", [
    ("127.0.0.1", True), ("::1", True), ("localhost", True), ("10.0.0.68", True),
    ("172.16.0.1", True), ("172.31.255.254", True), ("192.168.1.20", True),
    ("169.254.10.10", True), ("fd12:3456::1", True), ("fe80::1%eth0", True),
    ("::ffff:192.168.1.20", True), ("::ffff:10.0.0.5", True),
    ("172.32.0.1", False), ("8.8.8.8", False), ("203.0.113.5", False), ("100.64.0.1", False),
    ("2001:db8::1", False), ("2606:4700::1111", False), ("::ffff:8.8.8.8", False),
    ("", False), (None, False), ("not-an-address", False),
])
def test_home_network_addresses(addr, home):
    assert mirror_mod.home_network_address(addr) is home


@pytest.mark.parametrize("addr, ok", [
    ("192.168.1.20", True), ("10.0.0.68", True), ("::ffff:192.168.1.20", True),
    ("203.0.113.5", False), ("::ffff:8.8.8.8", False), ("2001:db8::1", False),
])
def test_the_route_takes_a_sign_in_only_from_the_home_network(tmp_path, armed, addr, ok):
    """Over HTTPS (another device's only road since 2026-11-19, below), the address decides."""
    cli = login_client(tmp_path)
    tok = _in(7)
    r = cli.post(ROUTE, json=with_csrf(cli, {"token": tok}),
                 environ_base={"REMOTE_ADDR": addr, "wsgi.url_scheme": "https"},
                 base_url="https://localhost")
    if ok:
        assert r.get_json()["ok"] is True
    else:
        assert r.status_code == 403 and "home network" in r.get_json()["error"]
        assert mirror_mod.load_mirror_state() == {} and armed.looked == []


@pytest.mark.parametrize("addr", ["192.168.1.20", "10.0.0.68", "::ffff:192.168.1.20",
                                  "fd12:3456::1"])
def test_another_device_over_plain_http_is_refused_before_anything(tmp_path, armed, addr):
    """App security review 2026-11-19, finding 1: a sign-in posted over plain http:// from
    another device crosses the network in clear, so it is refused -- before the body is read,
    the account looked up or anything stored -- with a sentence naming the https:// address."""
    cli = login_client(tmp_path)
    r = cli.post(ROUTE, json=with_csrf(cli, {"token": _in(7)}),
                 environ_base={"REMOTE_ADDR": addr})
    assert r.status_code == 403
    err = r.get_json()["error"]
    assert "https://" in err and "encrypted" in err
    assert mirror_mod.load_mirror_state() == {} and armed.looked == []


def test_this_pc_may_connect_over_plain_http(tmp_path, armed):
    """The loopback never leaves the PC: plain HTTP from 127.0.0.1 still connects."""
    cli = login_client(tmp_path)
    r = cli.post(ROUTE, json=with_csrf(cli, {"token": _in(7)}),
                 environ_base={"REMOTE_ADDR": "127.0.0.1"})
    assert r.get_json()["ok"] is True


# ---- the page the bookmark opens -------------------------------------------------------

def test_the_connect_page_is_login_gated(tmp_path):
    from moonglade.gallery import create_app
    r = create_app(tmp_path).test_client().get("/mirror/connect")
    assert r.status_code in (301, 302) and "/login" in r.headers["Location"]


def test_the_connect_page_talks_only_to_pixai_and_carries_the_session_token(tmp_path):
    from tests.conftest import session_csrf
    cli = login_client(tmp_path)
    r = cli.get("/mirror/connect")
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store"
    html = r.get_data(as_text=True)
    assert json.dumps(session_csrf(cli)) in html                     # the token it POSTs with
    assert 'var PIXAI = "https://pixai.art";' in html
    assert "e.origin !== PIXAI || e.source !== opener" in html       # taken only from the opener
    assert 'postMessage({ type: "moonglade-mirror-ready" }, PIXAI)' in html
    assert "'*'" not in html and '"*"' not in html                   # never a wildcard target
    assert ROUTE in html and "lgn-card" in html                      # the login card, reused


def test_the_bookmark_checks_where_it_runs_and_names_its_target():
    js = (Path(__file__).resolve().parents[2] / "gallery" / "src" / "lib"
          / "mirrorBookmarklet.js").read_text(encoding="utf-8")
    js = js[js.index("const BODY = `"):js.index("`;")]            # the code, not its comment
    assert 'location.origin!==P' in js and 'P="https://pixai.art"' in js
    assert 'e.source!==w||e.origin!==M' in js
    assert 'w.postMessage({type:"moonglade-mirror-token",token:t},M)' in js
    assert '"*"' not in js and "'*'" not in js
    assert 'credentials:"include"' in js
    assert "if(!w||w.closed){alert(" in js                          # a blocked window stops
    assert "},600000);" in js                                       # ten minutes, not three


# ---- the renewal regression ------------------------------------------------------------

def test_a_token_survives_the_app_being_closed_for_five_days(tmp_path, monkeypatch):
    """The 2-11 Nov timeline. A token minted at T0 lives 7 days. The server runs, ticking every
    15 minutes, for 3.6 days, then is closed for 5.3 days. With the old 3-day cushion nothing
    came due while it ran, so it reopened on an expired token ("expired": an expired Bearer
    cannot renew itself). It must instead have renewed while it ran, reopen on a live token,
    and renew again on the first tick."""
    p = tmp_path / "mirror_session.json"
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: p)
    monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: True)
    monkeypatch.setattr(mj, "READ_ONLY", False)
    monkeypatch.setattr(mj, "_read_only_now", lambda: False)
    T0 = 1_800_000_000
    mirror_mod.save_mirror_state({"jwt": _jwt(T0 + 7 * DAY, salt="t0"), "minted_at": T0})
    clock = {"now": T0}
    minted = []

    def _renew(session, current_jwt=None, expected_sub=None, now=None):
        minted.append(now)
        return _jwt(now + 7 * DAY, salt=str(now))
    monkeypatch.setattr(mirror_mod, "refresh_jwt", _renew)

    step = mirror_mod.MIRROR_RENEW_TICK_S
    t = T0
    while t < T0 + 3.6 * DAY:                        # the server running
        mirror_mod.mirror_renew_tick(now=t)
        t += step
    assert minted, "the token was never renewed in 3.6 days of the server running"
    reopen = T0 + 8.9 * DAY                          # closed for 5.3 days, then started again
    assert mirror_mod.jwt_expiry(mirror_mod.load_mirror_state()["jwt"]) > reopen
    assert mirror_mod.mirror_renew_tick(now=reopen) == "renewed"
    assert mirror_mod.jwt_expiry(mirror_mod.load_mirror_state()["jwt"]) == reopen + 7 * DAY
    # and it is still bounded: at most one renewal a day while it runs, never a loop
    assert len(minted) <= 5
