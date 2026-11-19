"""Website-mirror JWT — offline logic for the zero-paste mirror (the JWT bridge).
Lives in moonglade_backup.py alongside _make_session/gql_mutate.

Pure/mocked only: JWT expiry decode, the refresh-decision cushion, and refresh_jwt's
body-first/header-fallback parsing of POST /v2/auth/refresh-token (#92) against a fake
session. No browser, no network, no account. A sign-in gets in only through Connect from
PixAI (test_mirror_connect_token.py); the old browser read is gone, and the tests below pin
that. The full credential matrix for the renewal is in test_rest_delete_and_renewal.py."""
import base64
import json
import sys

import pytest

from moonglade import backup as mj
from moonglade import mirror as mirror_mod

def _b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")


def _jwt(exp):
    """A structurally-real JWT with the given exp (signature is a dummy — we only ever
    decode the payload, never verify)."""
    return (_b64({"alg": "HS256", "typ": "JWT"}) + "."
            + _b64({"exp": exp, "sub": "u", "iss": "pixai"}) + ".sig")


NOW = 1_800_000_000  # fixed clock


def test_jwt_expiry_and_days_left():
    tok = _jwt(NOW + 27 * 86400)
    assert mirror_mod.jwt_expiry(tok) == NOW + 27 * 86400
    assert mirror_mod.jwt_days_left(tok, now=NOW) == 27
    assert mirror_mod.jwt_claims("garbage") == {}
    assert mirror_mod.jwt_expiry("a.b") is None            # not 3 segments
    assert mirror_mod.jwt_days_left("nope", now=NOW) is None


def test_needs_refresh_cushion():
    """#71: a renewal mints a 7-day token (PROBE 2026-10-02). The cushion is 6 days (2026-11-18:
    at 3 the whole renewal window fit inside one closed spell of the app -- see
    test_mirror_connect_token.py's regression), measured on the token's real seconds left, not
    on floored whole days."""
    assert mirror_mod.MIRROR_REFRESH_WHEN_DAYS_LEFT == 6
    assert mirror_mod.mirror_needs_refresh(_jwt(NOW + 20 * 86400), now=NOW) is False   # plenty
    assert mirror_mod.mirror_needs_refresh(_jwt(NOW + 7 * 86400), now=NOW) is False    # just renewed
    assert mirror_mod.mirror_needs_refresh(_jwt(NOW + 6 * 86400 + 60), now=NOW) is False
    assert mirror_mod.mirror_needs_refresh(_jwt(NOW + 6 * 86400), now=NOW) is True     # at cushion
    assert mirror_mod.mirror_needs_refresh(_jwt(NOW + 5 * 86400), now=NOW) is True     # a day old
    assert mirror_mod.mirror_needs_refresh(_jwt(NOW - 3600), now=NOW) is True          # expired
    assert mirror_mod.mirror_needs_refresh(None, now=NOW) is True                       # no token
    assert mirror_mod.mirror_needs_refresh("garbage", now=NOW) is True                  # unparseable


class _Resp:
    def __init__(self, headers=None, jd=None, raise_json=False, status_code=200):
        self.headers = headers or {}
        self.status_code = status_code
        self._jd, self._rj = jd, raise_json

    def json(self):
        if self._rj:
            raise ValueError("bad json")
        return self._jd


class _Session:
    """Records the one renewal POST. `post` takes only what a body-less REST POST sends:
    no `json`, no `data` (#92) -- a call that tried to send a body would raise TypeError."""

    def __init__(self, resp=None, raise_post=False):
        self._resp, self._rp, self.last, self.posts = resp, raise_post, None, 0

    def post(self, url, headers=None, timeout=None, allow_redirects=True):
        self.posts += 1
        self.last = {"url": url, "headers": headers, "allow_redirects": allow_redirects}
        if self._rp:
            raise ConnectionError("network down")
        return self._resp


# Every direct refresh_jwt call below passes now=NOW: the tokens are minted off the fixed
# clock, and "is the token we send still live" is judged at `now` (#92 review F2).

def test_refresh_rides_the_rest_route_with_the_bearer():
    """#92: POST /v2/auth/refresh-token with no body, the Bearer we hold, nothing else, and
    no redirect followed."""
    cur, fresh = _jwt(NOW + 2 * 86400), _jwt(NOW + 7 * 86400)
    s = _Session(_Resp(jd={"token": fresh}))
    assert mirror_mod.refresh_jwt(s, current_jwt=cur, now=NOW) == fresh
    assert s.last["url"] == mj.REST_API_BASE + "/auth/refresh-token"
    assert s.last["headers"] == {"Authorization": "Bearer " + cur}
    assert s.last["allow_redirects"] is False


def test_refresh_falls_back_to_the_token_header():
    cur, fresh = _jwt(NOW + 2 * 86400), _jwt(NOW + 7 * 86400)
    s = _Session(_Resp(headers={"token": fresh}, jd={}))
    assert mirror_mod.refresh_jwt(s, current_jwt=cur, now=NOW) == fresh


def test_refresh_returns_none_when_nothing_usable():
    cur = _jwt(NOW + 2 * 86400)

    def _none(sess, why, **k):
        assert mirror_mod.refresh_jwt(sess, current_jwt=k.get("cur", cur), now=NOW) is None
        assert mirror_mod._refresh_last["reason"] == why

    _none(_Session(_Resp(jd={})), "unchanged")
    # a token that isn't a real jwt is not trusted
    _none(_Session(_Resp(headers={"token": "not-a-jwt"}, jd={"token": "x"})), "unchanged")
    # network failure -> None, never a raise (caller keeps the current jwt)
    _none(_Session(raise_post=True), "network")
    # unparseable body + no header -> None
    _none(_Session(_Resp(raise_json=True)), "unchanged")
    fresh = _jwt(NOW + 7 * 86400)
    # (review) non-200 -> None even with a fresh token
    _none(_Session(_Resp(headers={"token": fresh}, jd={"token": fresh}, status_code=400)),
          "http_400")
    # (review) the gateway echoes the SAME token we sent -> not a renewal
    _none(_Session(_Resp(headers={"token": cur}, jd={"token": cur})), "unchanged")
    # no credential -> no request at all
    s = _Session(_Resp(jd={"token": fresh}))
    assert mirror_mod.refresh_jwt(s, now=NOW) is None and s.posts == 0
    # a token that is live by the real clock but expired at `now` is not sent either
    s = _Session(_Resp(jd={"token": fresh}))
    assert mirror_mod.refresh_jwt(s, current_jwt=cur, now=NOW + 3 * 86400) is None and s.posts == 0
    assert mirror_mod._refresh_last["reason"] == "no_credential"


# ---- mirror session: persistence, session build, refresh, and the check command ----
import time as _time
from types import SimpleNamespace


def _jwt_in(days):
    """A JWT expiring `days` from the REAL clock (make_mirror_session uses time.time())."""
    return _jwt(int(_time.time()) + int(days * 86400))


def test_mirror_state_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "mirror_session.json"
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: p)
    assert mirror_mod.load_mirror_state() == {}                       # absent -> {}
    assert mirror_mod.save_mirror_state({"jwt": "J", "cookies": {"_udt": "x"}}) is True
    got = mirror_mod.load_mirror_state()
    assert got["jwt"] == "J" and "cookies" not in got         # JWT-only: cookies never stored


def test_make_mirror_session_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: tmp_path / "none.json")
    assert mirror_mod.make_mirror_session() is None                   # no state, no bootstrap


def _fake_make_session(tok):
    """Stand-in for the app's _make_session -- a JWT-authed Session, offline (the real one
    validates config + network-resolves USER_ID). The mirror build attaches cookies after."""
    import requests
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + tok
    return s


def test_make_mirror_session_jwt_only_and_skips_refresh_when_fresh(tmp_path, monkeypatch):
    """A fresh (~27d) JWT is used directly: no refresh, no cookies, and the session is built
    from the JWT via _mirror_session_from -- NEVER _make_session (which would enforce the
    API-key precondition and resolve USER_ID over the browser token; review)."""
    p = tmp_path / "m.json"
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: p)
    monkeypatch.setattr(mj, "_make_session", lambda tok: (_ for _ in ()).throw(
        AssertionError("mirror must not build via _make_session")))
    fresh = _jwt_in(27)
    mirror_mod.save_mirror_state({"jwt": fresh})
    monkeypatch.setattr(mirror_mod, "refresh_jwt", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not refresh a fresh jwt")))
    s = mirror_mod.make_mirror_session()
    assert s.headers["Authorization"] == "Bearer " + fresh
    assert s.headers["User-Agent"] == mirror_mod.MIRROR_WEB_USER_AGENT   # web identity
    assert len(s.cookies) == 0                                   # JWT-only, no cookie jar


def test_mirror_session_presents_web_client_identity(tmp_path, monkeypatch):
    """The mirror files as the WEB client so PixAI applies the website content policy, not the
    stricter mobile-app one. The returned session must carry a desktop-browser User-Agent and
    the pixai.art Origin/Referer (the API-tool UA reads as a non-web client and gets 403s)."""
    p = tmp_path / "m.json"
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: p)
    monkeypatch.setattr(mj, "_make_session", _fake_make_session)
    mirror_mod.save_mirror_state({"jwt": _jwt_in(27), "cookies": {"_udt": "u"}})
    s = mirror_mod.make_mirror_session()
    assert s.headers["User-Agent"] == mirror_mod.MIRROR_WEB_USER_AGENT
    assert "Mozilla/5.0" in s.headers["User-Agent"] and "Chrome/" in s.headers["User-Agent"]
    assert s.headers["Origin"] == "https://pixai.art"
    assert s.headers["Referer"].startswith("https://pixai.art")
    assert "pixai-personal-backup" not in s.headers["User-Agent"]   # not the API-tool UA


def test_make_mirror_session_refreshes_when_stale(tmp_path, monkeypatch):
    p = tmp_path / "m.json"
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: p)
    monkeypatch.setattr(mj, "_make_session", _fake_make_session)
    mirror_mod.save_mirror_state({"jwt": _jwt_in(2), "cookies": {"_udt": "u"}})   # within cushion
    fresh = _jwt_in(27)
    monkeypatch.setattr(mirror_mod, "refresh_jwt", lambda session, current_jwt=None, **k: fresh)
    s = mirror_mod.make_mirror_session()
    assert s.headers["Authorization"] == "Bearer " + fresh
    assert mirror_mod.load_mirror_state()["jwt"] == fresh              # persisted the fresh one


def test_make_mirror_session_refuses_when_no_jwt_never_api_key(tmp_path, monkeypatch):
    """Review F5: with cookies but no usable JWT even after a failed refresh, refuse
    (return None) -- NEVER build an API-key session as a fallback while mirroring."""
    p = tmp_path / "m.json"
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: p)
    mirror_mod.save_mirror_state({"jwt": "", "cookies": {"_udt": "u"}})
    monkeypatch.setattr(mirror_mod, "refresh_jwt", lambda *a, **k: None)          # refresh fails
    monkeypatch.setattr(mj, "_make_session", lambda tok: (_ for _ in ()).throw(
        AssertionError("must not build a session without a JWT (F5)")))
    assert mirror_mod.make_mirror_session() is None


def test_make_mirror_session_refuses_expired_jwt(tmp_path, monkeypatch):
    """An already-EXPIRED JWT whose refresh also fails must refuse (return None), not build a
    dead session that makes Connect falsely report success then 401 at submit time."""
    p = tmp_path / "m.json"
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: p)
    mirror_mod.save_mirror_state({"jwt": _jwt_in(-1), "cookies": {"_udt": "u"}})   # expired yesterday
    monkeypatch.setattr(mirror_mod, "refresh_jwt", lambda *a, **k: None)           # refresh fails
    monkeypatch.setattr(mj, "_make_session", lambda tok: (_ for _ in ()).throw(
        AssertionError("must not build a session around an expired JWT")))
    assert mirror_mod.make_mirror_session() is None


def test_run_mirror_check_never_prints_the_token(tmp_path, monkeypatch, capsys):
    p = tmp_path / "m.json"
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: p)
    old, fresh = _jwt_in(2), _jwt_in(27)
    mirror_mod.save_mirror_state({"jwt": old, "cookies": {"_udt": "u"}})
    monkeypatch.setattr(mirror_mod, "refresh_jwt", lambda session, current_jwt=None, **k: fresh)
    res = mirror_mod.run_mirror_check(SimpleNamespace())
    out = capsys.readouterr().out
    assert res["ok"] is True and res["renewed"] is True
    assert old not in out and fresh not in out                # NEVER the token
    assert "Mirror OK" in out and "days left" in out


def test_run_mirror_check_no_session(tmp_path, monkeypatch, capsys):
    """No stored sign-in: --mirror-check says how to connect, sends nothing, stores nothing."""
    p = tmp_path / "none.json"
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: p)
    monkeypatch.setattr(mirror_mod, "refresh_jwt", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("nothing stored, so nothing to renew")))
    res = mirror_mod.run_mirror_check(SimpleNamespace())
    assert res["ok"] is False and res["source"] == "none"
    assert "Connect from PixAI" in capsys.readouterr().out
    assert not p.exists()


def test_mirror_enabled_reads_flag(tmp_path):
    """settings.json's mirror_to_pixai (an app-written setting, never config.json)."""
    from moonglade import settings
    settings.set_values(mirror_to_pixai=True)
    assert mirror_mod.mirror_enabled() is True
    settings.set_values(mirror_to_pixai=None)
    assert mirror_mod.mirror_enabled() is False


def test_save_mirror_state_atomic_under_concurrency(tmp_path, monkeypatch):
    """Review F5: a per-PROCESS temp name let concurrent savers interleave into one temp
    and both os.replace -> corrupt JSON -> load returns {} (mirror 'lost'). With a
    per-WRITE-unique temp + atomic replace, concurrent saves are last-writer-wins and the
    loaded record is always ONE complete write, never corrupt."""
    import threading as _t
    p = tmp_path / "mirror_session.json"
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: p)
    threads = [_t.Thread(target=lambda i=i: mirror_mod.save_mirror_state({"jwt": str(i)}))
               for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    got = mirror_mod.load_mirror_state()
    assert got != {}                                             # never lost to corruption
    assert got.get("jwt") in {str(i) for i in range(16)}         # one complete write
    assert "cookies" not in got                                  # JWT-only
    assert set(got) <= {"jwt", "minted_at"}                      # #71: and nothing else
    assert not list(tmp_path.glob("mirror_session.json.tmp*"))   # no stray temp left behind


def test_gitignore_covers_credential_temp_files():
    """Review F6: a crashed save can leave mirror_session.json.tmp-<pid> (JWT+cookies) or
    config.json.tmp-<pid> (+ PIXAI_API_KEY) untracked; a git add would commit a live
    credential. The .gitignore must cover the temp variants, not just the exact names."""
    import pathlib
    gi = (pathlib.Path(mj.__file__).resolve().parents[1] / ".gitignore").read_text(encoding="utf-8")
    assert "mirror_session.json.*" in gi and "config.json.*" in gi


def test_session_for_create_routing(monkeypatch):
    """The single create-routing choke (review F4/F5/F6): OFF is a pure passthrough (no
    change to existing spend paths); ON returns the mirror session; ON-but-unavailable
    REFUSES (raises) rather than falling back to the API-key session."""
    import pytest
    api, mir = object(), object()
    monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: False)
    assert mirror_mod._session_for_create(api) is api                 # OFF -> passthrough
    monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: True)
    monkeypatch.setattr(mirror_mod, "make_mirror_session", lambda: mir)
    assert mirror_mod._session_for_create(api) is mir                 # ON -> the mirror session
    monkeypatch.setattr(mirror_mod, "make_mirror_session", lambda: None)
    with pytest.raises(mj.PixAIError):                         # ON + unavailable -> refuse (F5)
        mirror_mod._session_for_create(api)


# ---- the Control Panel mirror routes (status / enable / connect) ----
def test_api_mirror_status_reports_days_left_never_the_token(tmp_path, monkeypatch):
    from tests.conftest import login_client
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: tmp_path / "m.json")
    mirror_mod.save_mirror_state({"jwt": _jwt_in(20), "cookies": {"_udt": "u"}})
    monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: True)
    d = login_client(tmp_path).get("/api/mirror/status").get_json()
    assert d["enabled"] is True and d["connected"] is True and d["days_left"] >= 18
    import json as _json
    assert "eyJ" not in _json.dumps(d)                         # never the token


def test_api_mirror_enable_arms_only_with_a_usable_jwt(tmp_path, monkeypatch):
    """/api/mirror/enable writes ONLY settings.json's mirror_to_pixai (config.json, with the
    auth block, is never rewritten). [MAJOR, Bridge change #6] It ARMS (true-write) only when a
    usable browser JWT
    exists: arming with no live session would leave every Bridge/enhance submit hitting the
    mirror gate and refusing -- an armed toggle that can run nothing. DISARM is always allowed."""
    from tests.conftest import login_client
    cli = login_client(tmp_path)                                # real login (real config read = auth intact)
    from moonglade import settings
    captured = {}
    real_set = settings.set_values

    def _spy(**kw):
        captured["flag"] = kw.get("mirror_to_pixai")
        return real_set(**kw)
    monkeypatch.setattr(settings, "set_values", _spy)
    monkeypatch.setattr(mj, "_save_config", lambda cfg: (_ for _ in ()).throw(
        AssertionError("the Mirror switch rewrote config.json")))

    # ARM with a usable JWT -> the flag is written True. (_jwt_usable is mocked so the gate is
    # deterministic and never depends on a real mirror_session.json on the test machine.)
    monkeypatch.setattr(mirror_mod, "_jwt_usable", lambda jwt: True)
    d = cli.post("/api/mirror/enable", json={"enabled": True}).get_json()
    assert d["enabled"] is True and captured.get("flag") is True

    # ARM with NO usable JWT -> refused, and the flag is NOT written.
    captured.clear()
    monkeypatch.setattr(mirror_mod, "_jwt_usable", lambda jwt: False)
    d = cli.post("/api/mirror/enable", json={"enabled": True}).get_json()
    assert d.get("enabled") is False
    assert "Connect the mirror first" in (d.get("error") or "")
    assert "flag" not in captured, "armed with no usable JWT still wrote the flag"

    # DISARM is ALWAYS allowed, even with no usable JWT -> writes False (the false-write is
    # never gated, so the owner can always turn the mirror back off).
    captured.clear()
    d = cli.post("/api/mirror/enable", json={"enabled": False}).get_json()
    assert d["enabled"] is False and captured.get("flag") is False


def test_the_old_browser_read_connect_is_gone(tmp_path):
    """The old Connect stored whatever pixai.art sign-in a browser profile on this machine held,
    with no check that it was the API key's account (red team, 2026-11-18). Its route, its
    reader and make_mirror_session's browser switch are removed; Connect from PixAI is the one
    way in."""
    import inspect
    from tests.conftest import login_client
    r = login_client(tmp_path).post("/api/mirror/connect", json={})
    assert r.status_code in (404, 405)
    for name in ("read_browser_jwt", "_pick_pixai_token", "_lvldb_sstable_entries",
                 "_lvldb_log_entries", "_snappy_decompress", "LOCALSTORAGE_JWT_KEY"):
        assert not hasattr(mirror_mod, name), name
    assert "bootstrap_from_browser" not in inspect.signature(mirror_mod.make_mirror_session).parameters


def test_mirror_check_command_never_reads_a_browser(tmp_path, monkeypatch, capsys):
    """The `--mirror-check` command line, end to end through main(): with no stored session it
    stores nothing and reads no browser (an installed browser_cookie3 is never asked for);
    with one, it renews THAT token. Nothing is printed of the token, and nothing leaves the
    test: the renewal is stubbed."""
    p = tmp_path / "mirror.json"
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: p)
    fresh = _jwt_in(7)
    monkeypatch.setattr(mirror_mod, "refresh_jwt", lambda session, current_jwt=None, **k: fresh)
    monkeypatch.setitem(sys.modules, "browser_cookie3", None)   # an import of it would raise
    monkeypatch.setattr(sys, "argv", ["prog", "--mirror-check", "--out", str(tmp_path)])
    mj.main()
    assert "no session saved" in capsys.readouterr().out
    assert not p.exists()                                        # nothing was stored
    stored = _jwt_in(5)
    mirror_mod.save_mirror_state({"jwt": stored})
    mj.main()
    out = capsys.readouterr().out
    assert "Mirror OK (source: stored, renewed via jwt)" in out
    assert stored not in out and fresh not in out
    assert mirror_mod.load_mirror_state()["jwt"] == fresh               # the renewed token is kept


# ---- ultrareview fixes (2026-08-15) ---------------------------------------------------
def test_jwt_claims_non_object_payload_never_raises():
    """Review: a JWT whose payload decodes to a non-object made jwt_expiry raise
    AttributeError, breaking its 'never raises' contract."""
    tok = "eyJhIjoxfQ.MQ.sig"                    # payload segment "MQ" decodes to the integer 1
    assert mirror_mod.jwt_claims(tok) == {}
    assert mirror_mod.jwt_expiry(tok) is None            # must NOT raise
    assert mirror_mod.jwt_days_left(tok, now=NOW) is None


def test_make_mirror_session_skips_refresh_under_read_only(tmp_path, monkeypatch):
    """Review F3: the renewal is account-mutating -- it must not fire under READ_ONLY. A
    still-valid stored JWT is used as-is (no network) rather than refused."""
    p = tmp_path / "m.json"
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: p)
    monkeypatch.setattr(mj, "READ_ONLY", False)
    monkeypatch.setattr(mj, "_read_only_now", lambda: True)
    jwt = _jwt_in(2)                                              # within cushion -> would refresh
    mirror_mod.save_mirror_state({"jwt": jwt})
    monkeypatch.setattr(mirror_mod, "refresh_jwt", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not fire the renewal under READ_ONLY")))
    s = mirror_mod.make_mirror_session()
    assert s is not None and s.headers["Authorization"] == "Bearer " + jwt


def test_run_mirror_check_refused_under_read_only(monkeypatch):
    monkeypatch.setattr(mj, "READ_ONLY", False)
    monkeypatch.setattr(mj, "_read_only_now", lambda: True)
    monkeypatch.setattr(mirror_mod, "refresh_jwt", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not refresh under READ_ONLY")))
    res = mirror_mod.run_mirror_check(SimpleNamespace())
    assert res["ok"] is False and res["source"] == "read_only"



# ---- #71: background renewal, and the ring drawn against the token's own life ------------
# PROBE 2026-10-02 (bridge-live-inbox-studio, task 1): every renewal mints a token that
# expires 7 days later, `iat` never moves off the original sign-in, and nothing renewed the
# token unless a generation or a Connect asked. All on a fixed clock (NOW) unless a test says
# otherwise; refresh_jwt is always faked, so nothing here reaches PixAI.

DAY = 86400


def _armed(tmp_path, monkeypatch, *, jwt, minted_at=None, enabled=True, read_only=False):
    p = tmp_path / "mirror_session.json"
    monkeypatch.setattr(mirror_mod, "_mirror_state_path", lambda: p)
    monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: enabled)
    monkeypatch.setattr(mj, "READ_ONLY", False)
    monkeypatch.setattr(mj, "_read_only_now", lambda: read_only)
    st = {"jwt": jwt}
    if minted_at is not None:
        st["minted_at"] = minted_at
    mirror_mod.save_mirror_state(st)
    return p


def _refresh_spy(monkeypatch, result):
    calls = []

    def _fake(session, current_jwt=None, **k):
        calls.append(current_jwt)
        return result(len(calls)) if callable(result) else result
    monkeypatch.setattr(mirror_mod, "refresh_jwt", _fake)
    return calls


def test_the_renew_tick_matrix(tmp_path, monkeypatch):
    """Off, READ_ONLY, no session, expired and fresh all return before any network; a due
    token is renewed ONCE, stored, and stamped with the moment the app minted it."""
    tick = mirror_mod.mirror_renew_tick
    step = mirror_mod.MIRROR_RENEW_TICK_S
    fresh = _jwt(NOW + 7 * DAY)
    calls = _refresh_spy(monkeypatch, fresh)
    due = _jwt(NOW + 2 * DAY)

    _armed(tmp_path, monkeypatch, jwt=due, enabled=False)
    assert tick(now=NOW) == "mirror_off"
    _armed(tmp_path, monkeypatch, jwt=due, read_only=True)
    assert tick(now=NOW + step) == "read_only"
    _armed(tmp_path, monkeypatch, jwt="")
    assert tick(now=NOW + 2 * step) == "no_session"
    _armed(tmp_path, monkeypatch, jwt=_jwt(NOW - 60))
    assert tick(now=NOW + 3 * step) == "expired"
    _armed(tmp_path, monkeypatch, jwt=_jwt(NOW + 6.5 * DAY))
    assert tick(now=NOW + 4 * step) == "fresh"
    assert calls == []

    _armed(tmp_path, monkeypatch, jwt=due)
    assert tick(now=NOW + 5 * step) == "renewed"
    assert calls == [due]
    st = mirror_mod.load_mirror_state()
    assert st["jwt"] == fresh and st["minted_at"] == NOW + 5 * step


def test_the_tick_keeps_its_own_fifteen_minute_cadence(tmp_path, monkeypatch):
    """The scheduler's heartbeat is every minute; the tick looks at the token every fifteen."""
    _armed(tmp_path, monkeypatch, jwt=_jwt(NOW + 6.5 * DAY))
    reads = []
    real = mirror_mod.load_mirror_state
    monkeypatch.setattr(mirror_mod, "load_mirror_state", lambda: reads.append(1) or real())
    assert mirror_mod.mirror_renew_tick(now=NOW) == "fresh"
    n = len(reads)
    assert mirror_mod.mirror_renew_tick(now=NOW + 60) == "cadence" and len(reads) == n
    assert mirror_mod.mirror_renew_tick(now=NOW + mirror_mod.MIRROR_RENEW_TICK_S) == "fresh"


def test_a_failing_renewal_backs_off_and_a_connect_still_tries(tmp_path, monkeypatch):
    """10, 20, 40, 80 min, then every 2 h (the tick's own 15-minute cadence rounds the first
    steps up); a tick inside the backoff makes no call; a press of Connect (user-initiated)
    tries once anyway; a success resets everything."""
    due = _jwt(NOW + 2 * DAY)
    _armed(tmp_path, monkeypatch, jwt=due)
    calls = _refresh_spy(monkeypatch, None)
    r = mirror_mod._mirror_renewal
    t = NOW
    gaps = []
    for _ in range(6):
        assert mirror_mod._mirror_try_renew(now=t)[1] == "failed"
        gaps.append(r["next_try"] - t)
        t = r["next_try"]
    assert gaps == [600, 1200, 2400, 4800, 7200, 7200]
    assert len(calls) == 6
    assert mirror_mod.mirror_renew_tick(now=t - 1) == "backoff" and len(calls) == 6
    assert mirror_mod._mirror_try_renew(user_initiated=True, now=t - 1)[1] == "failed"
    assert len(calls) == 7                                  # the press tried, inside backoff
    fresh = _jwt(NOW + 9 * DAY)
    _refresh_spy(monkeypatch, fresh)
    jwt, outcome = mirror_mod._mirror_try_renew(user_initiated=True, now=t)
    assert outcome == "renewed" and jwt == fresh
    assert r["fails"] == 0 and r["next_try"] == 0 and r["failed_exp"] is None


def test_a_renewal_never_loops_on_a_short_token(tmp_path, monkeypatch):
    """If PixAI ever mints a token already inside the cushion, the 6 h success floor stops the
    tick renewing it every fifteen minutes; after the floor it renews again."""
    _armed(tmp_path, monkeypatch, jwt=_jwt(NOW + 2 * DAY))
    calls = _refresh_spy(monkeypatch, lambda n: _jwt(NOW + DAY + n))
    assert mirror_mod.mirror_renew_tick(now=NOW) == "renewed"
    t = NOW
    for _ in range(int(mirror_mod.MIRROR_RENEW_FLOOR_S // mirror_mod.MIRROR_RENEW_TICK_S) - 1):
        t += mirror_mod.MIRROR_RENEW_TICK_S
        assert mirror_mod.mirror_renew_tick(now=t) == "floor"
    assert len(calls) == 1
    assert mirror_mod.mirror_renew_tick(now=NOW + mirror_mod.MIRROR_RENEW_FLOOR_S) == "renewed"
    assert len(calls) == 2


def test_read_only_turning_on_between_the_check_and_the_lock_stops_the_post(tmp_path, monkeypatch):
    _armed(tmp_path, monkeypatch, jwt=_jwt(NOW + 2 * DAY))
    answers = iter([False, True, True, True])
    monkeypatch.setattr(mj, "_read_only_now", lambda: next(answers))
    calls = _refresh_spy(monkeypatch, _jwt(NOW + 7 * DAY))
    assert mirror_mod.mirror_renew_tick(now=NOW) == "read_only"
    assert calls == []


def test_the_tick_and_a_create_renew_once_between_them(tmp_path, monkeypatch):
    """Both go through _mirror_try_renew under _mirror_lock and re-read the stored token
    inside it, so whichever comes second sees the fresh token and makes no call. Real clock
    here, because make_mirror_session (what a create calls) reads it."""
    import threading
    import time as _t
    stale, fresh = _jwt_in(2), _jwt_in(7)
    _armed(tmp_path, monkeypatch, jwt=stale)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def _slow_refresh(session, current_jwt=None, **k):
        calls.append(current_jwt)
        entered.set()
        release.wait(5)
        return fresh
    monkeypatch.setattr(mirror_mod, "refresh_jwt", _slow_refresh)
    out = {}
    a = threading.Thread(target=lambda: out.update(tick=mirror_mod.mirror_renew_tick()))
    b = threading.Thread(target=lambda: out.update(s=mirror_mod.make_mirror_session(
        user_initiated=True)))
    a.start()
    assert entered.wait(5)
    b.start()
    _t.sleep(0.2)                               # let the create reach the lock
    release.set()
    a.join(5)
    b.join(5)
    assert calls == [stale]                     # ONE renewal between them
    assert out["tick"] == "renewed"
    assert mirror_mod.load_mirror_state()["jwt"] == fresh
    assert out["s"].headers["Authorization"] == "Bearer " + fresh


def test_a_renewal_while_offline_fails_quietly_and_says_why(tmp_path, monkeypatch):
    """No network: refresh_jwt swallows the exception, the tick records a `network` failure,
    nothing escapes, and the token stays as it was."""
    import requests
    due = _jwt(NOW + 2 * DAY)
    _armed(tmp_path, monkeypatch, jwt=due)

    class _Offline:
        def post(self, *a, **k):
            raise requests.ConnectionError("no route to host")
    monkeypatch.setattr(mirror_mod, "_mirror_session_from", lambda jwt: _Offline())
    assert mirror_mod.mirror_renew_tick(now=NOW) == "failed"
    assert mirror_mod.load_mirror_state()["jwt"] == due
    st = mirror_mod.mirror_renewal_status(now=NOW)
    assert st["state"] == "failed" and st["reason"] == "network"
    assert st["next_try_at"] == NOW + 600


def test_the_span_is_the_tokens_own_life_never_iat(tmp_path, monkeypatch):
    """`iat` stays at the original sign-in through every renewal, so exp - iat grows without
    bound. The span is exp - minted_at for a token the app renewed itself, and
    max(left, 7 days) for one Connect from PixAI stored (or stored before #71)."""
    _armed(tmp_path, monkeypatch, jwt=_jwt(NOW + 7 * DAY), minted_at=NOW)
    left, span = mirror_mod.mirror_token_span(mirror_mod.load_mirror_state(), now=NOW + DAY)
    assert (left, span) == (6 * DAY, 7 * DAY)
    handed = _jwt(NOW + 4 * DAY)
    mirror_mod.save_mirror_state({"jwt": handed})           # a different token, no minted_at: dropped
    assert "minted_at" not in mirror_mod.load_mirror_state()
    assert mirror_mod.mirror_token_span(mirror_mod.load_mirror_state(), now=NOW) == (4 * DAY, 7 * DAY)
    legacy = _jwt(NOW + 20 * DAY)
    mirror_mod.save_mirror_state({"jwt": legacy})
    assert mirror_mod.mirror_token_span(mirror_mod.load_mirror_state(), now=NOW) == (20 * DAY, 20 * DAY)
    # run_mirror_check's failure path re-saves the SAME token: its minted_at survives
    mirror_mod.save_mirror_state({"jwt": legacy, "minted_at": NOW - DAY})
    mirror_mod.save_mirror_state({"jwt": legacy})
    assert mirror_mod.load_mirror_state()["minted_at"] == NOW - DAY
    assert mirror_mod.mirror_token_span({}, now=NOW) == (None, None)


def test_failed_is_reported_only_for_the_token_that_failed(tmp_path, monkeypatch):
    """`failed` must not go stale: it is reported only while the CURRENT stored token is due
    and the last failure was against that same token (its exp). A Connect that saves a fresh
    token clears it."""
    due = _jwt(NOW + 2 * DAY)
    _armed(tmp_path, monkeypatch, jwt=due)
    _refresh_spy(monkeypatch, None)
    assert mirror_mod.mirror_renew_tick(now=NOW) == "failed"
    assert mirror_mod.mirror_renewal_status(now=NOW)["state"] == "failed"
    mirror_mod.save_mirror_state({"jwt": _jwt(NOW + 7 * DAY)})     # what Connect saves
    assert mirror_mod.mirror_renewal_status(now=NOW)["state"] == "ok"
    mirror_mod.save_mirror_state({"jwt": _jwt(NOW + 2 * DAY + 5)})  # another due token, never tried
    assert mirror_mod.mirror_renewal_status(now=NOW)["state"] == "ok"


def test_status_states_paused_off_and_expired_from_seconds(tmp_path, monkeypatch):
    """`expired` comes from the token's real seconds left, not the floored day count: ten hours
    left floors to 0 days and is NOT expired."""
    _armed(tmp_path, monkeypatch, jwt=_jwt(NOW + 10 * 3600))
    assert mirror_mod.jwt_days_left(mirror_mod.load_mirror_state()["jwt"], now=NOW) == 0
    assert mirror_mod.mirror_renewal_status(now=NOW)["state"] == "ok"
    _armed(tmp_path, monkeypatch, jwt=_jwt(NOW - 1))
    assert mirror_mod.mirror_renewal_status(now=NOW)["state"] == "expired"
    _armed(tmp_path, monkeypatch, jwt=_jwt(NOW + 2 * DAY), read_only=True)
    assert mirror_mod.mirror_renewal_status(now=NOW)["state"] == "paused"
    _armed(tmp_path, monkeypatch, jwt=_jwt(NOW + 6.5 * DAY), read_only=True)
    assert mirror_mod.mirror_renewal_status(now=NOW)["state"] == "ok"   # READ_ONLY, but nothing due
    _armed(tmp_path, monkeypatch, jwt=_jwt(NOW + 2 * DAY), enabled=False)
    assert mirror_mod.mirror_renewal_status(now=NOW)["state"] == "off"


def test_api_mirror_status_carries_the_span_and_the_renewal_state(tmp_path, monkeypatch):
    from tests.conftest import login_client
    import json as _json
    _armed(tmp_path, monkeypatch, jwt=_jwt_in(6.5))
    d = login_client(tmp_path).get("/api/mirror/status").get_json()
    assert d["enabled"] is True and d["days_left"] == 6
    assert 6 * DAY < d["left_s"] <= 6.5 * DAY and d["span_s"] == 7 * DAY
    assert d["renewal"]["state"] == "ok"
    text = _json.dumps(d)
    assert "eyJ" not in text and "iat" not in text                 # never the token or a claim


def test_the_price_probe_never_touches_the_mirror_while_it_is_off(tmp_path, monkeypatch):
    """The Bridge price probe used the mirror session whether or not the Mirror was on, so it
    could renew the token as a side effect while the owner had it switched off."""
    from tests.conftest import login_client
    monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: False)
    monkeypatch.setattr(mirror_mod, "make_mirror_session", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("the price probe must not reach the mirror while it is off")))
    d = login_client(tmp_path).get("/api/enhance/presets").get_json()
    assert d["presets"] and all(r["price"] is None for r in d["presets"])


def test_the_renew_tick_does_nothing_without_the_background_gate(tmp_path, monkeypatch):
    """The suite's conftest turns the background gate off (MOONGLADE_DISABLE_WATCH), exactly as
    for the release check and the contest sweep: the tick must then never reach the core."""
    from moonglade import gallery as g
    monkeypatch.setattr(mirror_mod, "mirror_renew_tick", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("the renew tick ran with the background gate off")))
    app = g.create_app(tmp_path)
    app.extensions["mg_mirror_renew_tick"]()


def test_the_renew_tick_rides_the_scheduler_heartbeat_and_adds_no_thread():
    """No timer thread of its own: it joins the one sixty-second heartbeat, outside the
    standing order's try/continue chain, gated like _update_check_tick and _contest_win_tick."""
    import inspect
    from moonglade import gallery as g
    src = inspect.getsource(g.create_app)
    loop = src[src.index("def _scheduler_loop():"):]
    body = loop[:loop.index("threading.Thread(target=_scheduler_loop")]
    assert "\n            _mirror_renew_tick()" in body
    assert body.index("_mirror_renew_tick()") < body.index("            try:")
    tick = src[src.index("def _mirror_renew_tick():"):]
    tick = tick[:tick.index("\n    def ", 10)]
    assert "if not _bg_release_check:" in tick and "mirror_renew_tick(" in tick
