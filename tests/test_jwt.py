"""Website-mirror JWT — offline logic for the zero-paste mirror (the JWT bridge).
Lives in moonglade_backup.py alongside _make_session/gql_mutate/the persisted hashes.

Pure/mocked only: JWT expiry decode, the refresh-decision cushion, and refresh_jwt's
header-first/scalar-fallback parsing against a fake session. No browser, no network, no
account — the live "read the real browser + call refreshToken" step self-verifies on the
owner's machine (an agent sandbox can't reach the browser)."""
import base64
import json

import moonglade_backup as mj


def _b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")


def _jwt(exp):
    """A structurally-real JWT with the given exp (signature is a dummy — we only ever
    decode the payload, never verify)."""
    return _b64({"alg": "HS256", "typ": "JWT"}) + "." + _b64({"exp": exp, "sub": "u"}) + ".sig"


NOW = 1_800_000_000  # fixed clock


def test_jwt_expiry_and_days_left():
    tok = _jwt(NOW + 27 * 86400)
    assert mj.jwt_expiry(tok) == NOW + 27 * 86400
    assert mj.jwt_days_left(tok, now=NOW) == 27
    assert mj.jwt_claims("garbage") == {}
    assert mj.jwt_expiry("a.b") is None            # not 3 segments
    assert mj.jwt_days_left("nope", now=NOW) is None


def test_needs_refresh_cushion():
    assert mj.mirror_needs_refresh(_jwt(NOW + 20 * 86400), now=NOW) is False   # plenty
    assert mj.mirror_needs_refresh(_jwt(NOW + 5 * 86400), now=NOW) is True     # at cushion
    assert mj.mirror_needs_refresh(_jwt(NOW - 3600), now=NOW) is True          # expired
    assert mj.mirror_needs_refresh(None, now=NOW) is True                       # no token
    assert mj.mirror_needs_refresh("garbage", now=NOW) is True                  # unparseable


class _Resp:
    def __init__(self, headers=None, jd=None, raise_json=False):
        self.headers = headers or {}
        self._jd, self._rj = jd, raise_json

    def json(self):
        if self._rj:
            raise ValueError("bad json")
        return self._jd


class _Session:
    def __init__(self, resp=None, raise_post=False):
        self._resp, self._rp, self.last = resp, raise_post, None

    def post(self, url, json=None, headers=None, timeout=None):
        self.last = {"url": url, "json": json, "headers": headers}
        if self._rp:
            raise ConnectionError("network down")
        return self._resp


def test_refresh_prefers_the_token_header():
    fresh = _jwt(NOW + 27 * 86400)
    s = _Session(_Resp(headers={"token": fresh}))
    assert mj.refresh_jwt(s, current_jwt="old") == fresh
    # sent the persisted refreshToken op + the bearer we had
    assert s.last["json"]["operationName"] == "refreshToken"
    assert s.last["json"]["extensions"]["persistedQuery"]["sha256Hash"] == mj.REFRESH_TOKEN_HASH
    assert s.last["headers"]["Authorization"] == "Bearer old"


def test_refresh_falls_back_to_scalar_return():
    fresh = _jwt(NOW + 27 * 86400)
    s = _Session(_Resp(headers={}, jd={"data": {"refreshToken": fresh}}))
    assert mj.refresh_jwt(s) == fresh


def test_refresh_returns_none_when_nothing_usable():
    assert mj.refresh_jwt(_Session(_Resp(headers={}, jd={"data": {}}))) is None
    # a token header that isn't a real jwt is not trusted
    assert mj.refresh_jwt(_Session(_Resp(headers={"token": "not-a-jwt"}, jd={"data": {}}))) is None
    # network failure -> None, never a raise (caller keeps the current jwt)
    assert mj.refresh_jwt(_Session(raise_post=True)) is None
    # unparseable body + no header -> None
    assert mj.refresh_jwt(_Session(_Resp(headers={}, raise_json=True))) is None


def test_read_browser_session_degrades_to_empty(monkeypatch):
    """No browser_cookie3 and no native read available -> {} (caller then uses the stored
    session or the break-glass paste), never a crash."""
    import builtins
    real_import = builtins.__import__

    def no_bc3(name, *a, **k):
        if name == "browser_cookie3":
            raise ImportError("absent")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_bc3)
    monkeypatch.setattr(mj, "_read_chromium_cookies_windows", lambda: {})
    assert mj.read_browser_session() == {}


# ---- mirror session: persistence, session build, refresh, and the check command ----
import time as _time
from types import SimpleNamespace


def _jwt_in(days):
    """A JWT expiring `days` from the REAL clock (make_mirror_session uses time.time())."""
    return _jwt(int(_time.time()) + int(days * 86400))


def test_mirror_state_roundtrip(tmp_path, monkeypatch):
    p = tmp_path / "mirror_session.json"
    monkeypatch.setattr(mj, "_mirror_state_path", lambda: p)
    assert mj.load_mirror_state() == {}                       # absent -> {}
    assert mj.save_mirror_state({"jwt": "J", "cookies": {"_udt": "x"}}) is True
    got = mj.load_mirror_state()
    assert got["jwt"] == "J" and got["cookies"] == {"_udt": "x"}


def test_make_mirror_session_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(mj, "_mirror_state_path", lambda: tmp_path / "none.json")
    assert mj.make_mirror_session() is None                   # no state, no bootstrap


def _fake_make_session(tok):
    """Stand-in for the app's _make_session -- a JWT-authed Session, offline (the real one
    validates config + network-resolves USER_ID). The mirror build attaches cookies after."""
    import requests
    s = requests.Session()
    s.headers["Authorization"] = "Bearer " + tok
    return s


def test_make_mirror_session_builds_on_make_session_and_skips_refresh_when_fresh(tmp_path, monkeypatch):
    p = tmp_path / "m.json"
    monkeypatch.setattr(mj, "_mirror_state_path", lambda: p)
    monkeypatch.setattr(mj, "_make_session", _fake_make_session)
    fresh = _jwt_in(27)
    mj.save_mirror_state({"jwt": fresh, "cookies": {"_udt": "u", "_bsid": "b"}})
    monkeypatch.setattr(mj, "refresh_jwt", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not refresh a fresh jwt")))
    s = mj.make_mirror_session()
    assert s.headers["Authorization"] == "Bearer " + fresh    # built via _make_session(jwt)
    assert {c.name for c in s.cookies} >= {"_udt", "_bsid"}    # cookie jar attached


def test_make_mirror_session_refreshes_when_stale(tmp_path, monkeypatch):
    p = tmp_path / "m.json"
    monkeypatch.setattr(mj, "_mirror_state_path", lambda: p)
    monkeypatch.setattr(mj, "_make_session", _fake_make_session)
    mj.save_mirror_state({"jwt": _jwt_in(2), "cookies": {"_udt": "u"}})   # within cushion
    fresh = _jwt_in(27)
    monkeypatch.setattr(mj, "refresh_jwt", lambda session, current_jwt=None: fresh)
    s = mj.make_mirror_session()
    assert s.headers["Authorization"] == "Bearer " + fresh
    assert mj.load_mirror_state()["jwt"] == fresh              # persisted the fresh one


def test_make_mirror_session_refuses_when_no_jwt_never_api_key(tmp_path, monkeypatch):
    """Review F5: with cookies but no usable JWT even after a failed refresh, refuse
    (return None) -- NEVER build an API-key session as a fallback while mirroring."""
    p = tmp_path / "m.json"
    monkeypatch.setattr(mj, "_mirror_state_path", lambda: p)
    mj.save_mirror_state({"jwt": "", "cookies": {"_udt": "u"}})
    monkeypatch.setattr(mj, "refresh_jwt", lambda *a, **k: None)          # refresh fails
    monkeypatch.setattr(mj, "_make_session", lambda tok: (_ for _ in ()).throw(
        AssertionError("must not build a session without a JWT (F5)")))
    assert mj.make_mirror_session() is None


def test_run_mirror_check_never_prints_the_token(tmp_path, monkeypatch, capsys):
    p = tmp_path / "m.json"
    monkeypatch.setattr(mj, "_mirror_state_path", lambda: p)
    old, fresh = _jwt_in(2), _jwt_in(27)
    mj.save_mirror_state({"jwt": old, "cookies": {"_udt": "u"}})
    monkeypatch.setattr(mj, "refresh_jwt", lambda session, current_jwt=None: fresh)
    res = mj.run_mirror_check(SimpleNamespace())
    out = capsys.readouterr().out
    assert res["ok"] is True and res["renewed"] is True
    assert old not in out and fresh not in out                # NEVER the token
    assert "Mirror OK" in out and "days left" in out


def test_run_mirror_check_no_session(tmp_path, monkeypatch):
    monkeypatch.setattr(mj, "_mirror_state_path", lambda: tmp_path / "none.json")
    monkeypatch.setattr(mj, "read_browser_session", lambda *a, **k: {})
    res = mj.run_mirror_check(SimpleNamespace())
    assert res["ok"] is False and res["source"] == "none"


def test_mirror_enabled_reads_flag(monkeypatch):
    monkeypatch.setattr(mj, "_load_config", lambda: {"MIRROR_TO_PIXAI": True})
    assert mj.mirror_enabled() is True
    monkeypatch.setattr(mj, "_load_config", lambda: {})
    assert mj.mirror_enabled() is False


def test_save_mirror_state_atomic_under_concurrency(tmp_path, monkeypatch):
    """Review F5: a per-PROCESS temp name let concurrent savers interleave into one temp
    and both os.replace -> corrupt JSON -> load returns {} (mirror 'lost'). With a
    per-WRITE-unique temp + atomic replace, concurrent saves are last-writer-wins and the
    loaded record is always ONE complete write (jwt+cookie from the same save)."""
    import threading as _t
    p = tmp_path / "mirror_session.json"
    monkeypatch.setattr(mj, "_mirror_state_path", lambda: p)
    threads = [_t.Thread(target=lambda i=i: mj.save_mirror_state(
        {"jwt": str(i), "cookies": {"_udt": str(i)}})) for i in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    got = mj.load_mirror_state()
    assert got != {}                                             # never lost to corruption
    assert got.get("jwt") == list(got["cookies"].values())[0]    # one atomic write, not merged
    assert not list(tmp_path.glob("mirror_session.json.tmp*"))   # no stray temp left behind


def test_gitignore_covers_credential_temp_files():
    """Review F6: a crashed save can leave mirror_session.json.tmp-<pid> (JWT+cookies) or
    config.json.tmp-<pid> (+ PIXAI_API_KEY) untracked; a git add would commit a live
    credential. The .gitignore must cover the temp variants, not just the exact names."""
    import pathlib
    gi = (pathlib.Path(mj.__file__).resolve().parent / ".gitignore").read_text(encoding="utf-8")
    assert "mirror_session.json.*" in gi and "config.json.*" in gi


def test_session_for_create_routing(monkeypatch):
    """The single create-routing choke (review F4/F5/F6): OFF is a pure passthrough (no
    change to existing spend paths); ON returns the mirror session; ON-but-unavailable
    REFUSES (raises) rather than falling back to the API-key session."""
    import pytest
    api, mir = object(), object()
    monkeypatch.setattr(mj, "mirror_enabled", lambda: False)
    assert mj._session_for_create(api) is api                 # OFF -> passthrough
    monkeypatch.setattr(mj, "mirror_enabled", lambda: True)
    monkeypatch.setattr(mj, "make_mirror_session", lambda: mir)
    assert mj._session_for_create(api) is mir                 # ON -> the mirror session
    monkeypatch.setattr(mj, "make_mirror_session", lambda: None)
    with pytest.raises(mj.PixAIError):                         # ON + unavailable -> refuse (F5)
        mj._session_for_create(api)
