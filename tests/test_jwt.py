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


def test_mirror_session_presents_web_client_identity(tmp_path, monkeypatch):
    """The mirror files as the WEB client so PixAI applies the website content policy, not the
    stricter mobile-app one. The returned session must carry a desktop-browser User-Agent and
    the pixai.art Origin/Referer (the API-tool UA reads as a non-web client and gets 403s)."""
    p = tmp_path / "m.json"
    monkeypatch.setattr(mj, "_mirror_state_path", lambda: p)
    monkeypatch.setattr(mj, "_make_session", _fake_make_session)
    mj.save_mirror_state({"jwt": _jwt_in(27), "cookies": {"_udt": "u"}})
    s = mj.make_mirror_session()
    assert s.headers["User-Agent"] == mj.MIRROR_WEB_USER_AGENT
    assert "Mozilla/5.0" in s.headers["User-Agent"] and "Chrome/" in s.headers["User-Agent"]
    assert s.headers["Origin"] == "https://pixai.art"
    assert s.headers["Referer"].startswith("https://pixai.art")
    assert "pixai-personal-backup" not in s.headers["User-Agent"]   # not the API-tool UA


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


def test_make_mirror_session_refuses_expired_jwt(tmp_path, monkeypatch):
    """An already-EXPIRED JWT whose refresh also fails must refuse (return None), not build a
    dead session that makes Connect falsely report success then 401 at submit time."""
    p = tmp_path / "m.json"
    monkeypatch.setattr(mj, "_mirror_state_path", lambda: p)
    mj.save_mirror_state({"jwt": _jwt_in(-1), "cookies": {"_udt": "u"}})   # expired yesterday
    monkeypatch.setattr(mj, "refresh_jwt", lambda *a, **k: None)           # refresh fails
    monkeypatch.setattr(mj, "_make_session", lambda tok: (_ for _ in ()).throw(
        AssertionError("must not build a session around an expired JWT")))
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
    monkeypatch.setattr(mj, "read_browser_jwt", lambda *a, **k: "")   # no localStorage JWT either
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


# ---- the Control Panel mirror routes (status / enable / connect) ----
def test_api_mirror_status_reports_days_left_never_the_token(tmp_path, monkeypatch):
    from tests.conftest import login_client
    monkeypatch.setattr(mj, "_mirror_state_path", lambda: tmp_path / "m.json")
    mj.save_mirror_state({"jwt": _jwt_in(20), "cookies": {"_udt": "u"}})
    monkeypatch.setattr(mj, "mirror_enabled", lambda: True)
    d = login_client(tmp_path).get("/api/mirror/status").get_json()
    assert d["enabled"] is True and d["connected"] is True and d["days_left"] >= 18
    import json as _json
    assert "eyJ" not in _json.dumps(d)                         # never the token


def test_api_mirror_enable_writes_the_flag_only(tmp_path, monkeypatch):
    from tests.conftest import login_client
    cli = login_client(tmp_path)                                # real login (real config read = auth intact)
    captured = {}
    # capture ONLY the flag off the write (never persist, never retain the real config/key)
    monkeypatch.setattr(mj, "_save_config",
                        lambda cfg: captured.__setitem__("flag", cfg.get("MIRROR_TO_PIXAI")))
    d = cli.post("/api/mirror/enable", json={"enabled": True}).get_json()
    assert d["enabled"] is True and captured.get("flag") is True


def test_api_mirror_connect_degrades_without_a_browser(tmp_path, monkeypatch):
    from tests.conftest import login_client
    monkeypatch.setattr(mj, "make_mirror_session", lambda **k: None)
    d = login_client(tmp_path).post("/api/mirror/connect", json={}).get_json()
    assert d["ok"] is False and d.get("error")


# ---- localStorage JWT reader (Connect on a modern-Chrome/v20-cookie machine) --------
# The pixai.art JWT lives in Local Storage/leveldb, which is NOT app-bound(v20)-encrypted
# the way modern Chrome cookies are. An established profile compacts to .ldb SSTables with
# PREFIX-COMPRESSED keys and SNAPPY-COMPRESSED blocks, so the reader parses leveldb for
# real (SSTable + Snappy + WAL) and validates the token's issuer is "pixai". These build
# genuine leveldb structures to prove the parsers, the iss guard, and freshest-wins.
# (The end-to-end read against a real browser store self-verifies on the owner's machine.)
import struct


def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | 0x80 if n else b)
        if not n:
            return bytes(out)


def _jwt_iss(exp, iss="pixai", alg="EdDSA", sig_len=86):
    """A JWT with a given issuer/alg and a signature of `sig_len` base64url chars (pixai's
    real token is EdDSA / iss='pixai' / 86-char sig). The reader trusts a token only when
    iss == 'pixai'."""
    h = base64.urlsafe_b64encode(json.dumps({"alg": alg, "typ": "JWT"}).encode()).rstrip(b"=").decode()
    p = base64.urlsafe_b64encode(json.dumps({"exp": exp, "iss": iss, "sub": "u"}).encode()).rstrip(b"=").decode()
    return "%s.%s.%s" % (h, p, "A" * sig_len)


_LS_KEY = b"_https://pixai.art\x00\x01" + mj.LOCALSTORAGE_JWT_KEY   # full leveldb key


def _ls_value(jwt):
    return b"\x01" + jwt.encode("ascii")                # encoding byte 0x01 (Latin-1) + JWT


def _snappy_literal(data):
    """A valid all-literal Snappy stream for `data` (no back-references) -- enough to feed a
    snappy-compressed SSTable block through the real _snappy_decompress path."""
    out = bytearray(_varint(len(data)))                 # preamble: uncompressed length
    if data:
        lm1 = len(data) - 1
        if lm1 < 60:
            out.append(lm1 << 2)
        else:
            nbytes = (lm1.bit_length() + 7) // 8
            out.append(((59 + nbytes) << 2))
            for i in range(nbytes):
                out.append((lm1 >> (8 * i)) & 0xFF)
        out += data
    return bytes(out)


def _lvldb_block(pairs):
    """A leveldb block (no prefix compression: shared=0 for every entry) + a 1-restart
    trailer, matching what _lvldb_block_pairs decodes."""
    body = bytearray()
    for k, v in pairs:
        body += _varint(0) + _varint(len(k)) + _varint(len(v)) + k + v
    body += struct.pack("<I", 0)                         # one restart at offset 0
    body += struct.pack("<I", 1)                         # num_restarts = 1
    return bytes(body)


def _lvldb_sstable(data_pairs, compress=False):
    """A minimal but real leveldb .ldb SSTable: one data block, one index entry, a footer.
    Optionally snappy-compresses the data block (comp type 1)."""
    dblock = _lvldb_block(data_pairs)
    stored = _snappy_literal(dblock) if compress else dblock
    comp = b"\x01" if compress else b"\x00"
    data_region = stored + comp + b"\x00\x00\x00\x00"    # + 4-byte CRC (unchecked)
    data_handle = _varint(0) + _varint(len(stored))      # BlockHandle(offset=0, size=stored)
    iblock = _lvldb_block([(b"\xff" * 4, data_handle)])  # index: one entry -> the data block
    idx_off = len(data_region)
    index_region = iblock + b"\x00" + b"\x00\x00\x00\x00"
    handles = _varint(0) + _varint(0) + _varint(idx_off) + _varint(len(iblock))
    footer = handles + b"\x00" * (40 - len(handles)) + struct.pack("<Q", mj._LVLDB_SSTABLE_MAGIC)
    return data_region + index_region + footer


def _internal_key(user_key, seq, is_del=False):
    """A leveldb SSTable internal key: user_key + 8-byte trailer (seq<<8 | type), LE."""
    trailer = (seq << 8) | (0 if is_del else 1)
    return user_key + trailer.to_bytes(8, "little")


def _lvldb_log(entries, base_seq=1):
    """A leveldb .log holding one WriteBatch as a single FULL record. `entries` are
    (key, value, is_del); a deletion is written as kTypeDeletion (tag 0, key only). The
    batch header carries base_seq; entry i is seq base_seq+i."""
    batch = bytearray(int(base_seq).to_bytes(8, "little") + struct.pack("<I", len(entries)))
    for k, v, is_del in entries:
        if is_del:
            batch += b"\x00" + _varint(len(k)) + k                       # kTypeDeletion
        else:
            batch += b"\x01" + _varint(len(k)) + k + _varint(len(v)) + v  # kTypeValue
    crc = b"\x00\x00\x00\x00"
    header = crc + struct.pack("<H", len(batch)) + b"\x01"              # len(2) + type FULL(1)
    return bytes(header + batch)


def test_snappy_decompress_literal_and_copy():
    assert mj._snappy_decompress(_snappy_literal(b"hello world" * 40)) == b"hello world" * 40
    # a back-reference: literal "ABC" then copy(len=3, offset=3) -> "ABCABC"
    # copy tag (2-byte offset, kind=2): (length-1)<<2 | 2, then offset as uint16 LE
    stream = _varint(6) + bytes([(3 - 1) << 2]) + b"ABC" + bytes([((3 - 1) << 2) | 2]) + b"\x03\x00"
    assert mj._snappy_decompress(stream) == b"ABCABC"
    assert mj._snappy_decompress(b"\x05\x00") is None          # claims 5 bytes, delivers 0


def test_lvldb_sstable_uncompressed_and_snappy_roundtrip():
    tok = _jwt_iss(NOW + 20 * 86400)
    for compress in (False, True):
        blob = _lvldb_sstable([(_internal_key(_LS_KEY, 100), _ls_value(tok))], compress=compress)
        entries = list(mj._lvldb_sstable_entries(blob))
        assert (_LS_KEY, _ls_value(tok), 100, False) in entries   # key/value/seq/type recovered
        assert mj._pick_pixai_token(entries) == tok


def test_lvldb_log_roundtrip_values_and_seq():
    tok = _jwt_iss(NOW + 20 * 86400)
    blob = _lvldb_log([(_LS_KEY, _ls_value(tok), False)], base_seq=5)
    assert (_LS_KEY, _ls_value(tok), 5, False) in list(mj._lvldb_log_entries(blob))


def test_pick_pixai_token_iss_guard_and_newest_seq_wins():
    older = _jwt_iss(NOW + 30 * 86400)                         # higher exp but LOWER seq
    newer = _jwt_iss(NOW + 3 * 86400)                          # the live write (highest seq)
    other = _jwt_iss(NOW + 99 * 86400, iss="intercom")         # later exp, WRONG issuer
    intercom_key = b"_https://pixai.art\x00\x01https://api.pixai.art:intercom-user-jwt"
    entries = [
        (_LS_KEY, _ls_value(older), 100, False),
        (_LS_KEY, _ls_value(newer), 200, False),              # newest write -> wins by SEQ, not exp
        (intercom_key, _ls_value(other), 300, False),         # right origin, wrong key + iss
        (b"_https://evil.example\x00\x01ev:token", _ls_value(_jwt_iss(NOW + 999 * 86400)), 999, False),
    ]
    assert mj._pick_pixai_token(entries) == newer


def test_pick_pixai_token_logout_tombstone_and_relogin():
    tok = _jwt_iss(NOW + 30 * 86400)
    # PUT then a later DELETE (logout) -> the newest op is a tombstone -> no token
    assert mj._pick_pixai_token([
        (_LS_KEY, _ls_value(tok), 100, False),
        (_LS_KEY, b"", 200, True),
    ]) == ""
    # logout then re-login -> the newest PUT wins over the earlier tombstone
    fresh = _jwt_iss(NOW + 40 * 86400)
    assert mj._pick_pixai_token([
        (_LS_KEY, _ls_value(_jwt_iss(NOW + 3 * 86400)), 100, False),
        (_LS_KEY, b"", 200, True),
        (_LS_KEY, _ls_value(fresh), 300, False),
    ]) == fresh


def test_read_browser_jwt_reads_real_sstable_across_profiles(tmp_path, monkeypatch):
    base = int(_time.time())
    old = _jwt_iss(base + 3 * 86400)
    new = _jwt_iss(base + 40 * 86400)                          # furthest exp -> chosen ACROSS profiles
    root = tmp_path / "Google" / "Chrome" / "User Data"
    for prof, tok, compress in (("Default", old, False), ("Profile 1", new, True)):
        d = root / prof / "Local Storage" / "leveldb"
        d.mkdir(parents=True)
        (d / "000005.ldb").write_bytes(
            _lvldb_sstable([(_internal_key(_LS_KEY, 100), _ls_value(tok))], compress=compress))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert mj.read_browser_jwt(browsers=("chrome",)) == new    # freshest live token, incl. a snappy block
    assert mj.read_browser_jwt(browsers=()) == ""              # no browsers -> '' (no raise)


def test_read_browser_jwt_logout_tombstone_across_ldb_and_log(tmp_path, monkeypatch):
    """Within one profile the .ldb + .log share a sequence space: a value in a compacted
    SSTable, then a later logout DELETE in the .log, must resolve to '' -- never resurface the
    logged-out token. (This is the adversarial-review finding the fix closes.)"""
    tok = _jwt_iss(int(_time.time()) + 20 * 86400)
    d = tmp_path / "Google" / "Chrome" / "User Data" / "Default" / "Local Storage" / "leveldb"
    d.mkdir(parents=True)
    (d / "000005.ldb").write_bytes(
        _lvldb_sstable([(_internal_key(_LS_KEY, 100), _ls_value(tok))]))       # PUT seq 100
    (d / "000007.log").write_bytes(_lvldb_log([(_LS_KEY, b"", True)], base_seq=200))  # DELETE seq 200
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert mj.read_browser_jwt(browsers=("chrome",)) == ""     # logged out -> no token


def test_make_mirror_session_bootstraps_from_localstorage_jwt_without_cookies(tmp_path, monkeypatch):
    """The v20-cookie case: cookies can't be decrypted (read_browser_session -> {}), but the
    JWT reads from localStorage -> a JWT-only mirror session is built AND persisted, so a
    later call needs no browser. This is exactly what Connect does on a current Chrome."""
    p = tmp_path / "m.json"
    monkeypatch.setattr(mj, "_mirror_state_path", lambda: p)
    monkeypatch.setattr(mj, "_make_session", _fake_make_session)
    fresh = _jwt_in(27)
    monkeypatch.setattr(mj, "read_browser_jwt", lambda *a, **k: fresh)
    monkeypatch.setattr(mj, "read_browser_session", lambda *a, **k: {})   # v20: no cookies
    monkeypatch.setattr(mj, "refresh_jwt", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("a fresh ~27d jwt must not trigger refresh")))
    s = mj.make_mirror_session(bootstrap_from_browser=True)
    assert s is not None and s.headers["Authorization"] == "Bearer " + fresh
    assert mj.load_mirror_state()["jwt"] == fresh                # persisted for next time


def test_run_mirror_check_uses_localstorage_jwt(tmp_path, monkeypatch, capsys):
    """--mirror-check with no stored session and no readable cookies still connects off the
    localStorage JWT, and still never prints the token."""
    monkeypatch.setattr(mj, "_mirror_state_path", lambda: tmp_path / "none.json")
    browser_jwt = _jwt_in(27)
    fresh = _jwt_in(27)
    monkeypatch.setattr(mj, "read_browser_jwt", lambda *a, **k: browser_jwt)
    monkeypatch.setattr(mj, "read_browser_session", lambda *a, **k: {})
    monkeypatch.setattr(mj, "refresh_jwt", lambda session, current_jwt=None: fresh)
    res = mj.run_mirror_check(SimpleNamespace())
    out = capsys.readouterr().out
    assert res["ok"] is True and res["source"] == "browser"
    assert browser_jwt not in out and fresh not in out
