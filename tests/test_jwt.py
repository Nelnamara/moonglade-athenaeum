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
