"""
moonglade/mirror.py
===================
The website mirror: the JWT helpers, the localStorage (LevelDB) reader that bootstraps it, the
session renewal and its record, the stored mirror state, the web-identity session, the
create-session choke (`_session_for_create`) and `--mirror-check`. Moved verbatim out of
moonglade/backup.py in the 3.21.0 split (phase 3), with the mirror constants that sat with the
engine's other endpoints (a default argument and WEB_IDENTITY_HEADERS read them at import
time) and the MIRROR-SUBMIT INVARIANTS block that describes this code.

The names it reads from the engine (READ_ONLY and _read_only_now, the config readers, the REST
base, the operation name, PixAIError) are imported from moonglade.backup inside each function
that uses them, at call time, so a test's patch of backup's binding still reaches them and
importing this module never imports the engine.
"""
import base64
import json
import os
import secrets
import sys
import threading
import time

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")

from moonglade import paths as _paths
from moonglade import secure_files as _secure
# The Mirror renews its website session the way pixai.art does: POST /v2/auth/refresh-token, no body
# (the GET recorded on 2026-08-17 answers 404 today). PixAI's contract (09-26 bundle): "Requires an
# existing session (bearer token or session cookie). The token is returned in the body and also written
# to the `token` response header and the session cookie." Credentials: the mirror JWT as Bearer, and
# nothing else -- never the API key, never a cookie (MIRROR-SUBMIT INVARIANTS #7, below).
# The mirror helpers are below, in this module (before 3.21.0, just after backup's _make_session).
MIRROR_REFRESH_PATH = "/auth/refresh-token"
# A renewal mints a token that expires 7 days after the renewal (PROBE 2026-10-02: the site's
# own renewal and the app's old GraphQL renewal alike; the ~27 days measured in August no longer
# holds). Renew once fewer than this many days are left -- measured in the token's real
# seconds, not floored whole days.
#
# Six, not three (2026-11-18). The renewal only runs while the server runs, so this number is
# also the shortest time the app can be closed without the token lapsing. At three, a token
# renewed on 2 Nov did not come due until 6 Nov; the server went down ten hours before that
# and was not started again until 11 Nov, two days after
# the token expired -- the whole three-day window fell inside one closed spell, and an expired
# token cannot renew itself. At six, a token is renewed on any day the app runs once it is a
# day old, so it always carries six to seven days, a week-long closed spell is survivable, and
# the 6 h success floor (MIRROR_RENEW_FLOOR_S) still caps renewals at four a day. pixai.art
# itself renews about hourly. (#71)
MIRROR_REFRESH_WHEN_DAYS_LEFT = 6
# What one renewal grants. Only the Control Panel's ring reads it: a token the app did not mint
# itself (one Connect stored, or one stored before #71) has no known start, so its ring
# is drawn out of max(seconds left, this) -- see mirror_token_span.
MIRROR_TOKEN_LIFE_S = 7 * 86400
# The localStorage key the pixai.art frontend keeps the live JWT under (confirmed on a
# logged-in tab 2026-08-15). localStorage is NOT app-bound(v20)-encrypted the way modern
# Chrome cookies are, so reading THIS is how the mirror bootstraps on a current Chrome
# where the cookie store can't be decrypted. Note the trailing ":token" is exact -- the
# sibling ":intercom-user-jwt" key must never be mistaken for it.
LOCALSTORAGE_JWT_KEY = b"https://api.pixai.art:token"
# The mirror must file generations as the WEB client so PixAI applies the website's content
# policy, not the stricter mobile-app (Apple-compliance) one. Confirmed 2026-08-15: the same
# account + prompt succeeds on pixai.art (task 2045416767743558052) but 403s "against PixAI's
# policy" through the mirror. The tell is the HTTP identity -- our non-browser User-Agent and missing Origin/Referer.
# So the mirror session presents a desktop-browser identity. A stable modern Chrome UA is
# enough: PixAI classifies the client FAMILY (browser vs app), not the version.
MIRROR_WEB_USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")
MIRROR_WEB_ORIGIN = "https://pixai.art"


# ===========================================================================
# Website-mirror JWT: zero-paste acquisition + self-renewal.
#
# The API key files a generation under the account but does NOT make it appear in
# the pixai.art web LIBRARY -- only a browser-session submission does. The Control
# Panel "Mirror to PixAI" toggle uses the helpers below to hold a live browser
# session with NO manual pastes, the way the site keeps itself logged in.
#
# Mechanism (confirmed from a live getMyInfo capture 2026-08-14):
#   - The session rides short cookies on .pixai.art that the server rolls forward
#     on every response: _bsid (~30m) + _udt (~60m; _udt IS the u3t value) + .sig
#     pairs (cache-control:no-store, vary:Origin,Authorization).
#   - The JWT rides as Authorization: Bearer (7 days since 2026-10-02).
#   - Renewal is POST /v2/auth/refresh-token with no body (MIRROR_REFRESH_PATH, #92), the
#     route pixai.art itself calls: the fresh token comes back in the response body and in
#     the `token` response header.
# So: get the live JWT ONCE, then the renewal rolls it -- zero paste. Since PixAI stopped
# keeping the token where an outside program can read it (~10 Nov 2026), the way in is the
# Control Panel's "Connect from PixAI" bookmark: clicked on a signed-in pixai.art tab, it hands
# the tab's own sign-in to this server's /mirror/connect page, which checks it with
# accept_site_token before storing it. The one-click Connect (POST /api/mirror/connect) is the
# other way in: it reads the sign-in from this PC's Chrome/Edge/Brave (read_browser_jwt) and
# stores it through the same accept_site_token, so it too is held to the API key's account.
#
# SAFETY: only touched when the mirror toggle is ON (pure API-key mode never calls
# these). The credential never leaves this machine and is never printed, logged, or
# committed (same rule as PIXAI_API_KEY); diagnostics report only non-secret
# derivatives (expiry date, days-left, ok/None). The live "read the real browser +
# first renewal" step self-verifies at runtime on the owner's machine.
# ===========================================================================
def _b64url_decode(seg):
    """Decode one base64url JWT segment, tolerant of missing padding."""
    seg = seg + "=" * (-len(seg) % 4)
    return base64.urlsafe_b64decode(seg.encode("ascii"))


def jwt_claims(token):
    """The JWT payload claims as a dict, or {} if unparseable. Decodes the payload
    ONLY (never verifies the signature -- we don't hold the key and don't need to;
    PixAI validates it, we just read `exp`). Never raises."""
    try:
        parts = str(token or "").split(".")
        if len(parts) != 3:
            return {}
        claims = json.loads(_b64url_decode(parts[1]))
        return claims if isinstance(claims, dict) else {}   # a non-object payload is not claims
    except Exception:
        return {}


def jwt_expiry(token):
    """Unix `exp` (seconds) or None. Offline."""
    exp = jwt_claims(token).get("exp")
    return int(exp) if isinstance(exp, (int, float)) else None


def jwt_days_left(token, now=None):
    """Whole days until the JWT expires, or None. Offline -- what the Panel countdown
    ('PixAI mirror: N days left') renders, decoded at startup with no network call."""
    exp = jwt_expiry(token)
    if exp is None:
        return None
    now = time.time() if now is None else now
    return int((exp - now) // 86400)


def mirror_needs_refresh(token, now=None, threshold_days=MIRROR_REFRESH_WHEN_DAYS_LEFT):
    """True when the JWT is missing, unparseable, expired, or has `threshold_days` or fewer
    left -- i.e. the Mirror should renew its session. Measured on the token's real seconds
    left (exp - now), not on jwt_days_left's floored whole days: the floor made the old 5-day
    rule renew with up to 6 days left. Pure; the scheduler's decision."""
    exp = jwt_expiry(token)
    if exp is None:
        return True
    now = time.time() if now is None else now
    return exp - now <= threshold_days * 86400


# --- localStorage JWT reader ------------------------------------------------------
# Modern Chrome (>=127) wraps the cookie store in app-bound "v20" encryption a normal
# user process can't decrypt, so a cookie read comes back empty there (the app no longer
# reads cookies at all). The pixai.art frontend keeps the live JWT in localStorage, and
# localStorage's on-disk store (Local Storage/leveldb) is NOT app-bound-encrypted -- so we
# read the JWT straight out of it. That's the whole reason "Connect" can work on a current
# Chrome without a paste. The Bearer JWT alone authenticates the mirror (create rides
# Authorization: Bearer; the renewal, POST /v2/auth/refresh-token, renews off the Bearer),
# so no cookie is needed.
#
# We parse leveldb properly (a minimal pure-Python reader -- no C dep, no third-party
# library). A raw byte-scan is NOT enough: an established profile compacts its writes into
# .ldb SSTables whose keys are PREFIX-COMPRESSED (the literal "https://api.pixai.art:token"
# never appears contiguously) and whose data blocks are usually SNAPPY-COMPRESSED (the JWT
# bytes aren't even there in the clear). So we reconstruct real key->value pairs from both
# the .ldb SSTables and the .log write-ahead log, match the exact localStorage key, and
# validate the decoded token's issuer is "pixai" before trusting it. The freshest (max
# `exp`) wins across every file/profile. Read-only; NEVER raises, NEVER logs a value.
def _read_file_shared(path):
    """Read a file Chrome may hold open. Direct read first (Chromium opens leveldb files
    share-read on Windows); on failure, copy to temp and read the copy. b'' on failure,
    never raises."""
    import shutil
    import tempfile
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        pass
    tmp = os.path.join(tempfile.gettempdir(),
                       "mg_ls_%d_%s_%s" % (os.getpid(), secrets.token_hex(4),
                                           os.path.basename(path)))
    try:
        shutil.copy2(path, tmp)
        with open(tmp, "rb") as f:
            return f.read()
    except OSError:
        return b""
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _lvarint(buf, pos):
    """Decode a leveldb base-128 varint at buf[pos:]. Returns (value, next_pos). Raises
    IndexError if it runs off the end (callers treat that as a malformed block)."""
    result = 0
    shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint too long")


def _snappy_decompress(data):
    """Pure-Python Snappy block decompression (the codec leveldb uses for SSTable blocks).
    Returns the decompressed bytes, or None on malformed input. No dependency."""
    try:
        expect, pos = _lvarint(data, 0)
        out = bytearray()
        n = len(data)
        while pos < n:
            tag = data[pos]
            pos += 1
            kind = tag & 0x03
            if kind == 0:                       # literal
                length = tag >> 2
                if length >= 60:
                    nbytes = length - 59        # 60->1 .. 63->4 extra length bytes
                    length = 0
                    for i in range(nbytes):
                        length |= data[pos + i] << (8 * i)
                    pos += nbytes
                length += 1
                out += data[pos:pos + length]
                pos += length
            else:
                if kind == 1:                   # copy, 1-byte offset
                    length = 4 + ((tag >> 2) & 0x07)
                    offset = ((tag >> 5) << 8) | data[pos]
                    pos += 1
                elif kind == 2:                 # copy, 2-byte offset
                    length = 1 + (tag >> 2)
                    offset = data[pos] | (data[pos + 1] << 8)
                    pos += 2
                else:                           # kind == 3, copy, 4-byte offset
                    length = 1 + (tag >> 2)
                    offset = (data[pos] | (data[pos + 1] << 8)
                              | (data[pos + 2] << 16) | (data[pos + 3] << 24))
                    pos += 4
                if offset <= 0 or offset > len(out):
                    return None
                start = len(out) - offset
                for i in range(length):         # byte-by-byte: copies may overlap
                    out.append(out[start + i])
        return bytes(out) if len(out) == expect else None
    except (IndexError, ValueError):
        return None


def _lvldb_decompress_block(data, offset, size):
    """The block at [offset, offset+size), decompressed per its 1-byte compression-type
    trailer (0 none, 1 snappy, 2 zlib, 4 zstd). None if unreadable/unknown."""
    if offset < 0 or offset + size + 1 > len(data):
        return None
    raw = data[offset:offset + size]
    comp = data[offset + size]
    if comp == 0:
        return raw
    if comp == 1:
        return _snappy_decompress(raw)
    if comp == 2:
        try:
            import zlib
            return zlib.decompress(raw)
        except Exception:
            return None
    if comp == 4:
        try:
            from compression import zstd        # Python 3.14+ stdlib
            return zstd.decompress(raw)
        except Exception:
            try:
                import zstandard                 # optional third-party fallback
                return zstandard.ZstdDecompressor().decompress(raw)
            except Exception:
                return None
    return None


def _lvldb_block_pairs(block):
    """Yield (key, value) from one decompressed leveldb block, undoing prefix compression.
    The block ends with a restart array: [restart offsets...][num_restarts as uint32 LE].
    A malformed block yields nothing rather than raising."""
    n = len(block)
    if n < 4:
        return
    try:
        num_restarts = int.from_bytes(block[n - 4:n], "little")
        entries_end = n - 4 - num_restarts * 4
        if entries_end < 0:
            return
        pos = 0
        last_key = b""
        while pos < entries_end:
            shared, pos = _lvarint(block, pos)
            non_shared, pos = _lvarint(block, pos)
            value_len, pos = _lvarint(block, pos)
            key = last_key[:shared] + block[pos:pos + non_shared]
            pos += non_shared
            value = block[pos:pos + value_len]
            pos += value_len
            last_key = key
            yield key, value
    except (IndexError, ValueError):
        return


_LVLDB_SSTABLE_MAGIC = 0xDB4775248B80FB57


def _lvldb_sstable_entries(data):
    """Yield (user_key, value, seq, is_deletion) from a leveldb .ldb SSTable. Reads the footer
    -> index block -> each data block (decompressing as needed) -> prefix-decoded entries. The
    8-byte internal-key trailer encodes (seq<<8 | type) little-endian; type 0 is a deletion
    tombstone. Yields nothing on any structural surprise (never raises)."""
    n = len(data)
    if n < 48:
        return
    try:
        footer = data[n - 48:n]
        if int.from_bytes(footer[40:48], "little") != _LVLDB_SSTABLE_MAGIC:
            return
        p = 0
        _, p = _lvarint(footer, p)                # metaindex handle offset (skip)
        _, p = _lvarint(footer, p)                # metaindex handle size   (skip)
        idx_off, p = _lvarint(footer, p)
        idx_size, p = _lvarint(footer, p)
    except (IndexError, ValueError):
        return
    index_block = _lvldb_decompress_block(data, idx_off, idx_size)
    if index_block is None:
        return
    for _sep, handle in _lvldb_block_pairs(index_block):
        try:
            b_off, hp = _lvarint(handle, 0)
            b_size, _hp = _lvarint(handle, hp)
        except (IndexError, ValueError):
            continue
        blk = _lvldb_decompress_block(data, b_off, b_size)
        if blk is None:
            continue
        for key, value in _lvldb_block_pairs(blk):
            if len(key) >= 8:                    # internal-key trailer = seq<<8 | type
                trailer = int.from_bytes(key[-8:], "little")
                yield key[:-8], value, trailer >> 8, (trailer & 0xFF) == 0


def _lvldb_log_entries(data):
    """Yield (key, value, seq, is_deletion) from a leveldb .log write-ahead log. Each
    WriteBatch header carries the sequence number of its first entry; entry i has seq = base+i.
    Reassembles physical record fragments across 32 KiB blocks. Deletions are yielded as
    tombstones (empty value, is_deletion=True) so a later logout can suppress an earlier PUT.
    Yields nothing on malformed input (never raises)."""
    BLOCK = 32768
    n = len(data)
    pos = 0
    frag = b""
    try:
        while pos + 7 <= n:
            block_left = BLOCK - (pos % BLOCK)
            if block_left < 7:                   # zero-padded block trailer -> next block
                pos += block_left
                continue
            length = data[pos + 4] | (data[pos + 5] << 8)
            rtype = data[pos + 6]
            pos += 7
            chunk = data[pos:pos + length]
            pos += length                        # ALWAYS consume the payload, even for a
            if rtype == 0 or length == 0:        # zero/padding record -- else a kZeroType
                continue                         # record with a payload desyncs every record
            if rtype == 1:                       # FULL
                rec = chunk
            elif rtype == 2:                     # FIRST
                frag = chunk
                continue
            elif rtype == 3:                     # MIDDLE
                frag += chunk
                continue
            elif rtype == 4:                     # LAST
                rec = frag + chunk
                frag = b""
            else:
                frag = b""
                continue
            # WriteBatch: header seq(8)+count(4)=12, then entries; entry i has seq base+i
            if len(rec) < 12:
                continue
            base_seq = int.from_bytes(rec[0:8], "little")
            rp = 12
            rn = len(rec)
            idx = 0
            while rp < rn:
                tag = rec[rp]
                rp += 1
                if tag == 1:                     # kTypeValue: key, value
                    klen, rp = _lvarint(rec, rp)
                    key = rec[rp:rp + klen]
                    rp += klen
                    vlen, rp = _lvarint(rec, rp)
                    value = rec[rp:rp + vlen]
                    rp += vlen
                    yield key, value, base_seq + idx, False
                    idx += 1
                elif tag == 0:                   # kTypeDeletion: key only
                    klen, rp = _lvarint(rec, rp)
                    key = rec[rp:rp + klen]
                    rp += klen
                    yield key, b"", base_seq + idx, True
                    idx += 1
                else:
                    break                        # unknown tag -> stop this batch
    except (IndexError, ValueError):
        return


def _lvldb_value_to_jwt(value):
    """A Chromium localStorage value (encoding byte + payload) -> JWT string, or ''. 0x00 is
    UTF-16LE, 0x01 is Latin-1 (a JWT is ASCII, so ours is 0x01)."""
    if not value:
        return ""
    enc, body = value[0], value[1:]
    try:
        if enc == 0:
            s = body.decode("utf-16-le", "ignore")
        elif enc == 1:
            s = body.decode("latin-1", "ignore")
        else:
            s = value.decode("latin-1", "ignore")
    except Exception:
        return ""
    s = s.strip()
    return s if s.startswith("eyJ") and s.count(".") == 2 else ""


def _pick_pixai_token(entries):
    """THE pixai.art auth token from ONE profile's leveldb entries, honoring leveldb's own
    last-writer-wins-by-sequence semantics. `entries` are (user_key, value, seq, is_deletion)
    tuples from that profile's .ldb + .log (which share one sequence space). Among entries for
    the token key (ends with LOCALSTORAGE_JWT_KEY, contains 'pixai'), the HIGHEST sequence
    number is the live state: if it's a deletion tombstone (logout) -> '' (not a stale token);
    otherwise decode it and require iss=='pixai' (the definitive guard -- the Local Storage
    store is shared across every origin, so unrelated JWTs live beside it). Returns '' if none.
    Sequence numbers are unique per write, so ties are effectively impossible; if two values
    tie (bottom-level seq-zeroing), the later `exp` wins, and any tombstone at the top wins."""
    best_seq = -1
    deleted_at_top = False
    values_at_top = []                           # (exp, jwt) for value entries at best_seq
    for key, value, seq, is_del in entries:
        if b"pixai" not in key or not key.endswith(LOCALSTORAGE_JWT_KEY):
            continue
        if seq > best_seq:
            best_seq = seq
            deleted_at_top = False
            values_at_top = []
        if seq == best_seq:
            if is_del:
                deleted_at_top = True
            else:
                jwt = _lvldb_value_to_jwt(value)
                if jwt and jwt_claims(jwt).get("iss") == "pixai":
                    exp = jwt_expiry(jwt)
                    values_at_top.append((exp if exp is not None else -1, jwt))
    if best_seq < 0 or deleted_at_top or not values_at_top:
        return ""
    values_at_top.sort()
    return values_at_top[-1][1]                   # freshest value at the top sequence


def read_browser_jwt(browsers=("chrome", "edge", "brave")):
    """The live pixai.art JWT read from a local browser's localStorage, across ALL profiles
    (Default, Profile N, ...) of the given Chromium browsers. Each profile is resolved on its
    own sequence space (a logout tombstone there suppresses that profile's older token); the
    freshest LIVE token (max `exp`) across profiles wins. Returns '' if none. This is what lets
    'Connect' bootstrap the mirror on a current Chrome whose cookie store is
    app-bound-encrypted. NEVER raises, NEVER logs the value."""
    la = os.environ.get("LOCALAPPDATA", "")
    roots = {
        "chrome": os.path.join(la, r"Google\Chrome\User Data"),
        "edge": os.path.join(la, r"Microsoft\Edge\User Data"),
        "brave": os.path.join(la, r"BraveSoftware\Brave-Browser\User Data"),
    }

    def _profile_entries(ldb):
        try:
            files = os.listdir(ldb)
        except OSError:
            return
        for fn in files:
            path = os.path.join(ldb, fn)
            if fn.endswith(".ldb"):
                blob = _read_file_shared(path)
                if blob:
                    yield from _lvldb_sstable_entries(blob)
            elif fn.endswith(".log"):
                blob = _read_file_shared(path)
                if blob:
                    yield from _lvldb_log_entries(blob)

    candidates = []
    for name in browsers:
        udir = roots.get(name)
        if not udir or not os.path.isdir(udir):
            continue
        try:
            profiles = os.listdir(udir)
        except OSError:
            continue
        for prof in profiles:
            ldb = os.path.join(udir, prof, "Local Storage", "leveldb")
            if not os.path.isdir(ldb):
                continue
            tok = _pick_pixai_token(_profile_entries(ldb))   # per-profile, tombstone-aware
            if tok:
                candidates.append(tok)

    best, best_exp = "", -1                       # freshest live token across profiles
    for j in candidates:
        e = jwt_expiry(j)
        if e is not None and e > best_exp:
            best, best_exp = j, e
    return best


def _is_api_key(token):
    """True when `token` is the configured PIXAI_API_KEY (the import-time snapshot or the live
    file). Compared in memory only; the key is never logged, returned or kept."""
    from moonglade.backup import _cfg, _load_config
    if not token:
        return False
    try:
        live = (_load_config() or {}).get("PIXAI_API_KEY")
    except Exception:                              # noqa: BLE001 -- an unreadable file is "no key"
        live = None
    for key in (_cfg.get("PIXAI_API_KEY"), live):
        if isinstance(key, str) and key.strip() and token == key.strip():
            return True
    return False


def _renewal_headers(cur, now=None):
    """The credential headers for ONE renewal POST, or None when there is nothing safe to send.

    JWT-only (Invariant #7): `Authorization: Bearer <cur>` when `cur` is present, unexpired
    and not the API key; otherwise None (the caller sends nothing). A per-call dict, so the
    credential never lands on a session's defaults and always wins over them. A same-session
    cookie road, if it is ever built (the 2026-08-17 ruling's read_browser_session), would add
    its `Cookie` header HERE and only here -- see refresh_jwt."""
    now = time.time() if now is None else now
    if not cur or _is_api_key(cur):
        return None
    exp = jwt_expiry(cur)
    if exp is None or exp - now <= 0:
        return None                                   # an expired Bearer cannot renew itself
    return {"Authorization": "Bearer " + cur}


def _fresh_pixai_token(tok, cur):
    """A token that counts as a renewal: a str that differs from the one sent, has a parseable
    `exp`, and was issued by PixAI (`iss == "pixai"`). The gateway rolls the SAME token back on
    ordinary authenticated responses, so an unchanged token is not a renewal."""
    return (isinstance(tok, str) and tok and tok != cur and jwt_expiry(tok) is not None
            and jwt_claims(tok).get("iss") == "pixai")


def refresh_jwt(session, current_jwt=None, expected_sub=None, now=None):
    """Renew the Mirror's website session and return a genuinely FRESH JWT, or None.

    The road (#92) is the one pixai.art itself uses: `POST /v2/auth/refresh-token`
    (MIRROR_REFRESH_PATH) with NO body. PixAI's contract: "Requires an existing session (bearer
    token or session cookie). The token is returned in the body and also written to the
    `token` response header and the session cookie." It replaces the saved GraphQL renewal the
    site stopped sending. Renews our own token only -- it does not spend. Returns None (never
    raises) on any failure, so the caller keeps the current jwt until it truly expires.

    CREDENTIAL. The stored mirror JWT as Bearer, sent only when it is present and unexpired,
    and NEVER the API key: this route issues a session token for whatever bearer it is handed,
    so a `current_jwt` equal to the configured PIXAI_API_KEY is refused before anything is
    sent. With nothing safe to send, no request is made. "Unexpired" is judged at `now`
    (default: the clock), which the scheduler passes down so its own clock decides. The header
    is per call, so it wins over any Authorization the session carries by default. No cookie
    is sent (Invariant #7, JWT-only), and a redirect is never followed: a 3xx is `http_3xx`.

    FRESHNESS (the review-proven guard). Status 200, then the body's `token` (the route's
    declared output) first and the `token` response header as the fallback; the winner must be
    a str that differs from the one sent, with a parseable `exp` and `iss == "pixai"`. When
    `expected_sub` is given, the fresh token's `sub` must equal it, or it is discarded: a
    renewal can never switch the Mirror to another account.

    CLEANUP. `session`'s cookie jar is emptied before the POST (so nothing it held rides the
    request) and again in `finally`, on success and failure alike, so whatever PixAI writes
    back (its session cookie among them) is held by no session.

    Why it returned None lands in `_refresh_last["reason"]`: network | http_<code> | unchanged |
    no_credential | identity_mismatch, for the Control Panel's "couldn't renew" line (#71). A
    fixed word, never a header, body, cookie or token; nothing here logs. A side channel rather
    than a second return value, so every caller and every test fake keeps the one-value
    contract.

    Where a same-session cookie road would slot in (the 2026-08-17 ruling; not built, see
    Invariant #7): a `cookies=` dict read with the JWT from ONE browser profile, turned into a
    `Cookie` header by _renewal_headers for this one request, with the Bearer dropped when that
    profile's JWT has lapsed; _mirror_try_renew would pick that road ("session") before the
    JWT-only one ("jwt")."""
    from moonglade.backup import REST_API_BASE
    _refresh_last["reason"] = ""
    cur = str(current_jwt or "")
    headers = _renewal_headers(cur, now)
    if headers is None:
        _refresh_last["reason"] = "no_credential"
        return None
    try:
        _drop_cookies(session)              # JWT-only: nothing a jar holds rides this request
        try:
            # Never follow a redirect (#92 review F1): requests would merge a 3xx's Set-Cookie
            # into the next hop, sending a cookie with the JWT. A 3xx is http_3xx below.
            r = session.post(REST_API_BASE + MIRROR_REFRESH_PATH, headers=headers, timeout=30,
                             allow_redirects=False)
        except Exception:                                    # noqa: BLE001 -- never raises
            _refresh_last["reason"] = "network"
            return None
        if r.status_code != 200:
            _refresh_last["reason"] = "http_{}".format(r.status_code)
            return None
        try:
            payload = r.json()
        except Exception:                                    # noqa: BLE001 -- not JSON
            payload = None
        body_tok = payload.get("token") if isinstance(payload, dict) else None
        try:
            header_tok = r.headers.get("token")
        except Exception:                                    # noqa: BLE001
            header_tok = None
        fresh = None
        if _fresh_pixai_token(body_tok, cur):
            fresh = body_tok
        elif _fresh_pixai_token(header_tok, cur):
            fresh = header_tok
        if fresh is None:
            _refresh_last["reason"] = "unchanged"
            return None
        got_sub = jwt_claims(fresh).get("sub")
        if expected_sub is not None and (got_sub is None or str(got_sub) != str(expected_sub)):
            _refresh_last["reason"] = "identity_mismatch"
            return None
        return fresh
    finally:
        _drop_cookies(session)              # what PixAI wrote back is held by no session
        headers = None


def _drop_cookies(session):
    """Empty `session`'s cookie jar (getattr-guarded; never raises)."""
    jar = getattr(session, "cookies", None)
    if jar is not None:
        try:
            jar.clear()
        except Exception:                                    # noqa: BLE001
            pass


_refresh_last = {"reason": ""}


# --- Mirror session state: a dedicated git-ignored store (NOT config.json) --------
# Single-flight lock: serializes the refresh->persist critical section so two threads can't
# both fire the renewal and race their writes. The SLOW work (the leveldb/localStorage
# browser read and the no-network fast path) runs OUTSIDE the lock so a Connect can't block
# every Generate -- an earlier version held the lock across a ~12 s scan plus a 30 s POST
# (adversarial review 2026-08-15). The gallery serves threaded=True.
_mirror_lock = threading.Lock()
# THE RENEWAL RECORD (#71) -- one home for everything about renewing, shared by the create
# path (make_mirror_session), a press of Connect, and the background tick (mirror_renew_tick):
#   fails / next_try   a failing renewal backs off _MIRROR_REFRESH_COOLDOWN, doubling, capped
#                      at MIRROR_RENEW_BACKOFF_CAP_S -- for the token that failed (failed_exp);
#                      a different token is not held behind another token's failures;
#   failed_exp         the exp of the token the last failure was against: the Panel reports
#                      "couldn't renew" only while THAT token is still the stored one and due;
#   last_ok_at         the last successful renewal; none again within MIRROR_RENEW_FLOOR_S, so
#                      a token PixAI mints already inside the cushion can never loop;
#   last_attempt_at, last_reason   for the status line; tick_at   the tick's own cadence;
#   last_road          which road the last successful renewal rode, a fixed word: "jwt" (the
#                      Bearer-only renewal, the only road built) -- "" until one succeeds (#92).
# Module state: dev/tests/conftest.py resets it around every test (_mirror_renewal_reset).
_MIRROR_REFRESH_COOLDOWN = 600      # the first backoff step after a failed renewal (seconds)
MIRROR_RENEW_BACKOFF_CAP_S = 7200   # the longest step: a failing renewal retries every 2 h
MIRROR_RENEW_FLOOR_S = 6 * 3600     # at most one successful renewal per 6 h, whatever is due
MIRROR_RENEW_TICK_S = 900           # the background tick looks at the token every 15 minutes
_mirror_renewal = {}


def _mirror_renewal_reset():
    """Back to "never tried": no failures, no backoff, no recent success, tick due now."""
    _mirror_renewal.clear()
    _mirror_renewal.update(fails=0, next_try=0.0, failed_exp=None, last_ok_at=None,
                           last_attempt_at=None, last_reason="", tick_at=None, last_road="")


_mirror_renewal_reset()


def _mirror_state_path():
    """Where the rotating mirror session (JWT + cookie jar) lives: a dedicated git-ignored
    machine file, local/mirror_session.json (moonglade.paths.local_path()). Deliberately NOT
    config.json -- the JWT
    rotates on every refresh, and a write there must never risk clobbering the API key (a
    test once overwrote the real PIXAI_API_KEY; a separate file can't)."""
    return _paths.local_path(_paths.MIRROR_SESSION_NAME)


def load_mirror_state():
    """The stored mirror session {jwt[, minted_at]} or {} if none. (A legacy `cookies` key from
    older builds is ignored -- the mirror is JWT-only now.) Never raises, never logs a value."""
    p = _mirror_state_path()
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (ValueError, OSError):
        return {}


def save_mirror_state(state):
    """Atomically persist {jwt[, minted_at]} to the git-ignored mirror file. Best-effort:
    True/False, never raises, never logs a value. JWT-only: cookies are no longer stored -- the
    Bearer JWT authenticates both the create and the refresh; the short session cookies died
    ~1 h after issue (so they never survived to a day-22 refresh anyway), and pairing a
    Default-profile cookie jar with an any-profile JWT risked a cross-identity submit (review).

    `minted_at` (#71) is a timestamp, not a credential: the moment the APP's own renewal minted
    this token, set ONLY by a successful renewal. It is what the Control Panel's ring measures
    the token's life from, because `iat` never moves off the original sign-in. Saving the SAME
    token without one keeps the stored one (run_mirror_check re-saves an unchanged token on a
    failed renewal); saving a DIFFERENT token without one -- a browser read -- drops it."""
    jwt = state.get("jwt", "")
    minted = state.get("minted_at")
    if minted is None:
        prev = load_mirror_state()
        if jwt and prev.get("jwt") == jwt:
            minted = prev.get("minted_at")
    record = {"jwt": jwt}
    if isinstance(minted, (int, float)) and not isinstance(minted, bool):
        record["minted_at"] = minted
    p = _mirror_state_path()
    # Per-WRITE-unique temp (pid + random), not per-process: the gallery is threaded, so a
    # per-pid temp name lets two concurrent savers interleave into one file then both
    # os.replace -> corrupt JSON -> load returns {} -> mirror "lost" (review F5). A unique
    # temp per write + atomic replace makes concurrent saves last-writer-wins, never corrupt.
    tmp = p.with_name(p.name + ".tmp-{}-{}".format(os.getpid(), secrets.token_hex(6)))
    try:
        # Secrets at rest (review 2026-11-19, #5): owner-only while empty, then written.
        _secure.write_private(tmp, json.dumps(record, indent=2))
        os.replace(tmp, p)
        _secure.restrict_to_owner(p)
        return True
    except OSError:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        return False


def disconnect_mirror():
    """Forget the stored PixAI sign-in (the Mirror tile's Disconnect, app security review
    2026-11-19 finding 7): delete local/mirror_session.json and clear the renewal state, so
    nothing renews it again. Under _mirror_lock, the lock every renewal and every Connect saves
    under, so a renewal in flight either finishes first (and its fresh token is then deleted)
    or finds no token. Returns True when no stored sign-in is left. Never raises, never logs a
    value. PixAI itself still honours the sign-in until it expires or is ended on PixAI's own
    sessions page; this only makes Moonglade let go of it."""
    with _mirror_lock:
        p = _mirror_state_path()
        try:
            p.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        _mirror_renewal_reset()
    return True


def mirror_enabled():
    """Is the Control Panel 'Mirror to PixAI website' toggle on? settings.json's
    mirror_to_pixai (moonglade.settings), read once per change of the file. Default OFF = pure
    API-key mode. When ON, the create POST rides the browser JWT (see _session_for_create) so
    the generation lands in the pixai.art web library."""
    from moonglade import settings as _settings
    return _settings.mirror_to_pixai()


def _jwt_usable(jwt):
    """True only when the JWT is present, parseable, and not expired (days_left >= 0). This
    is the gate for 'can the mirror actually submit with this' -- distinct from merely
    'a JWT string exists', which is what let an expired stored token block a browser re-read."""
    if not jwt:
        return False
    left = jwt_days_left(jwt)
    return left is not None and left >= 0


def _mirror_session_from(jwt):
    """A requests.Session authed as the browser JWT (Bearer) and presenting the WEB client
    identity -- used for BOTH the renewal and the mirrored create. Built directly,
    NOT via _make_session, so it never enforces the API-key/U3T precondition the mirror
    doesn't need and never resolves USER_ID over the browser token (review). JWT-only, no
    cookies. The web identity makes PixAI apply the website content policy, not the stricter
    mobile-app one; x-apollo-operation-name is present for Apollo CSRF (value need only be
    present, not correct)."""
    from moonglade.backup import OPERATION_NAME
    session = requests.Session()
    if jwt:
        session.headers["Authorization"] = "Bearer " + jwt
    session.headers.update({
        "Accept": "application/json",
        "apollo-require-preflight": "true",
        "x-apollo-operation-name": OPERATION_NAME,
        "User-Agent": MIRROR_WEB_USER_AGENT,
        "Origin": MIRROR_WEB_ORIGIN,
        "Referer": MIRROR_WEB_ORIGIN + "/",
        "Sec-Fetch-Site": "same-site",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    })
    return session


# PixAI applies its CONTENT POLICY by the client it believes it is talking to, not by the
# credential. Measured 2026-09-07, owner's walk (a LoRA search for "cum" that fills pages on
# the site came back "No LoRAs match" in the app): the same API key and the same meilisearch
# query returned 0 rows presenting as `pixai-personal-backup/1.0`, and 24 rows -- identical to
# the browser-token session's -- presenting the website's identity. The strict tier is the
# mobile-app one _mirror_session_from already describes. So a read that browses the market on
# the owner's behalf presents as the website, which is exactly what his own browser does with
# the same account. The credential is not in this set: Authorization is left as built.
WEB_IDENTITY_HEADERS = {
    "User-Agent": MIRROR_WEB_USER_AGENT,
    "Origin": MIRROR_WEB_ORIGIN,
    "Referer": MIRROR_WEB_ORIGIN + "/",
}


def present_as_web(session):
    """`session`, now presenting the website's client identity (WEB_IDENTITY_HEADERS), so
    PixAI applies the website content policy to what it returns. Mutates and returns the SAME
    object -- a PixAIClient delegates `headers` to the Session it holds -- and leaves a stand-in
    without headers (tests) untouched. Only the identity changes; the credential does not."""
    headers = getattr(session, "headers", None)
    if headers is not None:
        try:
            headers.update(WEB_IDENTITY_HEADERS)
        except Exception:
            pass
    return session


def mirror_token_span(state, now=None):
    """(seconds left, seconds in the token's life) for the Control Panel's ring, or
    (None, None) with no parseable token. Offline; neither number reveals the token.

    The life is exp - minted_at for a token the app renewed itself. A token read from the
    browser on Connect (or stored before #71) has no known start -- `iat` stays at the original
    sign-in through every renewal (PROBE 2026-10-02), so exp - iat grows without bound -- and
    is drawn out of max(left, MIRROR_TOKEN_LIFE_S). Never shorter than what is left, so the ring
    never draws past full."""
    exp = jwt_expiry((state or {}).get("jwt") or "")
    if exp is None:
        return None, None
    now = time.time() if now is None else now
    left = exp - now
    minted = (state or {}).get("minted_at")
    if isinstance(minted, (int, float)) and not isinstance(minted, bool) and minted < exp:
        span = exp - minted
    else:
        span = max(left, MIRROR_TOKEN_LIFE_S)
    return left, max(span, left)


def _mirror_try_renew(*, user_initiated=False, fallback="", now=None):
    """THE one renewal (#71): every path that renews -- a create (make_mirror_session), a press
    of Connect, the background tick -- comes through here. Returns (jwt, outcome); outcome is
    renewed | failed | not_due | read_only | backoff | floor | no_session.

    Runs entirely inside _mirror_lock and re-reads the stored token there, so two renewals
    racing (the tick and a Connect, or two creates) make ONE renewal call: the second sees
    the fresh token and finds nothing due. READ_ONLY is re-checked here, immediately before the
    POST, because it can flip between a caller's own check and this lock. A failure backs off
    (see _mirror_renewal) unless this is a press of Connect, which always tries once; and no
    renewal follows a successful one within MIRROR_RENEW_FLOOR_S.

    The renewal is JWT-only (road "jwt", #92): refresh_jwt on a fresh Bearer session of the
    stored token, with the stored token's `sub` as the identity the fresh one must carry. A
    same-session cookie road (road "session"), if it is ever built, would be tried here first,
    from a browser read made by the caller OUTSIDE this lock, and fall through to this one."""
    from moonglade.backup import READ_ONLY, _read_only_now
    now = time.time() if now is None else now
    r = _mirror_renewal
    with _mirror_lock:
        cur = load_mirror_state().get("jwt") or fallback or ""
        if not cur:
            return cur, "no_session"
        if READ_ONLY or _read_only_now():
            return cur, "read_only"
        if not mirror_needs_refresh(cur, now=now):
            return cur, "not_due"
        exp = jwt_expiry(cur)
        if not user_initiated and r["failed_exp"] == exp and now < r["next_try"]:
            return cur, "backoff"
        if r["last_ok_at"] is not None and now - r["last_ok_at"] < MIRROR_RENEW_FLOOR_S:
            return cur, "floor"
        r["last_attempt_at"] = now
        road = "jwt"
        fresh = refresh_jwt(_mirror_session_from(cur), current_jwt=cur,
                            expected_sub=jwt_claims(cur).get("sub"), now=now)
        if fresh:
            save_mirror_state({"jwt": fresh, "minted_at": now})
            r.update(fails=0, next_try=0.0, failed_exp=None, last_ok_at=now, last_reason="",
                     last_road=road)
            return fresh, "renewed"
        fails = (r["fails"] if r["failed_exp"] == exp else 0) + 1
        r.update(fails=fails, failed_exp=exp,
                 next_try=now + min(_MIRROR_REFRESH_COOLDOWN * 2 ** (fails - 1),
                                    MIRROR_RENEW_BACKOFF_CAP_S),
                 last_reason=_refresh_last.get("reason") or "failed")
        return cur, "failed"


def make_mirror_session(user_initiated=False):
    """The mirror submit/refresh session: a requests.Session authed with the stored website JWT
    (Bearer) presenting the WEB client identity. Returns None -- NEVER raises -- when there is
    no USABLE (present, parseable, unexpired) JWT even after a refresh; callers must then
    refuse and spend nothing, never an API-key fallback (review F5).

    JWT-only, and built via _mirror_session_from (NOT _make_session): the API-key path's
    precondition/USER_ID-resolution must not run over the website token (review).

    It never reads a browser. A sign-in gets in only through accept_site_token -- Connect from
    PixAI, and the one-click Connect's browser read (POST /api/mirror/connect) -- which checks
    it is the API key's own account first (invariant #7). The 3.20 browser read in here saved
    a token with no such check, so it is not restored (security review, 2026-11-19).

    `user_initiated`: its renewal tries once even inside a failure backoff (#71).

    Lock scope: only the refresh->persist critical section (_mirror_try_renew) takes the lock."""
    from moonglade.backup import READ_ONLY, _read_only_now
    jwt = load_mirror_state().get("jwt") or ""
    # Roll the JWT forward when inside the refresh cushion -- but never under READ_ONLY
    # (the renewal is account-mutating; _mirror_try_renew checks again inside its lock).
    if jwt and mirror_needs_refresh(jwt) and not (READ_ONLY or _read_only_now()):
        jwt, _outcome = _mirror_try_renew(user_initiated=user_initiated, fallback=jwt)
    if not _jwt_usable(jwt):
        return None                        # absent/expired -> refuse, never API-key (F5)
    return _mirror_session_from(jwt)


# --- Connect from PixAI: a sign-in handed over by the user's own pixai.art tab ---------------
# The bookmark posts the tab's sign-in to /mirror/connect, which sends it here. Everything is
# checked before anything is stored, and every refusal is a fixed plain sentence: never the
# token, a claim, or the account id.
_SITE_TOKEN_MAX = 8192                       # a real one is well under 1 KB
_B64URL = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
SITE_TOKEN_NOT_A_SIGNIN = ("That isn't a PixAI sign-in, so nothing was saved. Click the "
                           "Connect from PixAI bookmark on a pixai.art tab.")
SITE_TOKEN_NOT_PIXAI = ("That sign-in wasn't issued by PixAI, so nothing was saved.")
SITE_TOKEN_EXPIRED = ("That PixAI sign-in has already expired, so nothing was saved. Reload "
                      "pixai.art, sign in, and click the bookmark again.")
SITE_TOKEN_NO_ACCOUNT = ("Moonglade couldn't confirm which PixAI account your API key belongs "
                         "to, so nothing was saved. Check that the API key is set up, then try "
                         "again.")
SITE_TOKEN_OTHER_ACCOUNT = ("That pixai.art tab is signed in to a different PixAI account "
                            "than your API key, so nothing was saved. Sign in to pixai.art as "
                            "the same account, then click the bookmark again.")
SITE_TOKEN_NOT_SAVED = "Moonglade couldn't save the sign-in. Try again."
SITE_TOKEN_PIXAI_UNREACHABLE = ("Couldn't reach PixAI to check which account this is. Try "
                                "again in a minute.")
SITE_TOKEN_TOO_LONG = ("That sign-in claims to last longer than any PixAI sign-in does, so "
                       "nothing was saved. Click the bookmark again on a pixai.art tab.")
SITE_TOKEN_NOT_HOME = ("Connect from PixAI only works from this computer or your home "
                       "network, so nothing was saved.")
# One-click Connect's own refusal (the Mirror tile's Connect, not the bookmark above).
CONNECT_NOT_HOME = ("Connect only works from this computer or your home network, so nothing "
                    "was read or saved.")
# The longest life a real PixAI sign-in has had, plus a day of slack: ~27 days, measured on
# the browser's own token in August 2026 (renewals mint 7 days today, MIRROR_TOKEN_LIFE_S).
# A token claiming more was not issued by PixAI as we know it -- and, kept by the "keep the
# later-expiring one" rule below, a far-future one would pin itself in place.
SITE_TOKEN_MAX_LIFE_S = (27 + 1) * 86400


def home_network_address(addr):
    """True when `addr` (the request's remote address) is this machine or a private home
    network: IPv4 10/8, 172.16/12, 192.168/16, 169.254/16 and loopback; IPv6 ::1, fc00::/7,
    fe80::/10; and the IPv4-mapped forms of the IPv4 ranges. Anything else -- including an
    empty or unparseable address -- is False (fails closed). Pure."""
    import ipaddress
    a = str(addr or "").strip()
    if a == "localhost":
        return True
    a = a.split("%", 1)[0].strip("[]")                 # an IPv6 zone id / brackets
    try:
        ip = ipaddress.ip_address(a)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if isinstance(ip, ipaddress.IPv4Address):
        nets = ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                "169.254.0.0/16")
    else:
        nets = ("::1/128", "fc00::/7", "fe80::/10")
    return any(ip in ipaddress.ip_network(n) for n in nets)


def _jwt_shaped(tok):
    """True for three non-empty base64url segments of sane total length. Offline, no decode."""
    if not isinstance(tok, str) or not tok or len(tok) > _SITE_TOKEN_MAX:
        return False
    parts = tok.split(".")
    return len(parts) == 3 and all(p and set(p) <= _B64URL for p in parts)


def accept_site_token(token, account_id, now=None):
    """Store a PixAI sign-in the user's own pixai.art tab handed over ("Connect from PixAI").

    Returns {"ok": True, "days_left": N} or {"ok": False, "error": <fixed sentence>}; never
    raises for a bad token, never logs, never returns or echoes the token or any claim.

    Checks, cheapest first, all before anything is stored: a JWT's shape; not the API key;
    `iss == "pixai"`; an `exp` still in the future and no further out than
    SITE_TOKEN_MAX_LIFE_S; and -- the cross-identity guard (invariant #7) -- its `sub` equals
    the PixAI account the configured API key resolves to. `account_id` is that id, or a
    no-argument callable returning it, called only once the offline checks pass (the route's
    callable asks PixAI, ignoring any USER_ID pinned in config.json). An empty id refuses: an
    account that cannot be confirmed is never assumed. A lookup that raised
    requests.RequestException (no connection, a timeout, a 5xx) says PixAI could not be
    reached; any other failure says to check the API key.

    Then, under _mirror_lock: when the stored token is still usable, for the same account, and
    expires LATER than this one, it is kept and its days are answered (a replayed older token
    never shortens a good one); otherwise save_mirror_state({"jwt": token}) (JWT-only, no
    minted_at -- the app did not mint it). Either way the renewal backoff is cleared, so the
    background tick starts clean. READ_ONLY, the client's address and the Mirror switch are the
    caller's to check (the route refuses under READ_ONLY, as Connect always has, and off the
    home network; storing a sign-in is allowed with the Mirror off, as Connect always has,
    since arming needs one)."""
    now = time.time() if now is None else now
    tok = token.strip() if isinstance(token, str) else ""
    if not _jwt_shaped(tok) or _is_api_key(tok):
        return {"ok": False, "error": SITE_TOKEN_NOT_A_SIGNIN}
    claims = jwt_claims(tok)
    if not claims:
        return {"ok": False, "error": SITE_TOKEN_NOT_A_SIGNIN}
    if claims.get("iss") != "pixai":
        return {"ok": False, "error": SITE_TOKEN_NOT_PIXAI}
    exp = jwt_expiry(tok)
    if exp is None or exp - now <= 0:
        return {"ok": False, "error": SITE_TOKEN_EXPIRED}
    if exp - now > SITE_TOKEN_MAX_LIFE_S:
        return {"ok": False, "error": SITE_TOKEN_TOO_LONG}
    try:
        acct = account_id() if callable(account_id) else account_id
    except requests.RequestException:                  # no connection / timeout / 5xx
        return {"ok": False, "error": SITE_TOKEN_PIXAI_UNREACHABLE}
    except Exception:                                  # noqa: BLE001 -- a failed lookup refuses
        acct = ""
    acct = str(acct or "").strip()
    if not acct:
        return {"ok": False, "error": SITE_TOKEN_NO_ACCOUNT}
    sub = claims.get("sub")
    if sub is None or str(sub) != acct:
        return {"ok": False, "error": SITE_TOKEN_OTHER_ACCOUNT}
    with _mirror_lock:
        kept = load_mirror_state().get("jwt") or ""
        kept_exp = jwt_expiry(kept)
        # exp is already in the future, so a kept_exp beyond it is a still-valid token.
        if (kept_exp is not None and kept_exp > exp
                and str(jwt_claims(kept).get("sub")) == acct):
            winner = kept                              # the stored one outlives this one
        else:
            if not save_mirror_state({"jwt": tok}):
                return {"ok": False, "error": SITE_TOKEN_NOT_SAVED}
            winner = tok
        _mirror_renewal.update(fails=0, next_try=0.0, failed_exp=None, last_reason="")
    return {"ok": True, "days_left": jwt_days_left(winner, now=now)}


def mirror_renew_tick(now=None):
    """THE BACKGROUND RENEWAL (#71), asked every minute by the gallery's scheduler heartbeat
    and deciding every MIRROR_RENEW_TICK_S. Without it the token was renewed only when a
    generation or a Connect asked, so a week of not generating let it lapse.

    Returns what it did: cadence | mirror_off | read_only | no_session | expired | fresh |
    backoff | floor | not_due | renewed | failed. Everything before the renewal is offline (two
    small file reads); the renewal itself is _mirror_try_renew, one renewal POST at most. An
    expired token is left for Connect -- the tick does not try it. Never raises, never logs or
    returns the token."""
    now = time.time() if now is None else now
    r = _mirror_renewal
    if r["tick_at"] is not None and now - r["tick_at"] < MIRROR_RENEW_TICK_S:
        return "cadence"
    r["tick_at"] = now
    try:
        from moonglade.backup import READ_ONLY, _read_only_now
        if not mirror_enabled():
            return "mirror_off"
        if READ_ONLY or _read_only_now():
            return "read_only"
        jwt = load_mirror_state().get("jwt") or ""
        exp = jwt_expiry(jwt)
        if exp is None:
            return "no_session"
        if exp - now <= 0:
            return "expired"
        if not mirror_needs_refresh(jwt, now=now):
            return "fresh"
        return _mirror_try_renew(now=now)[1]
    except Exception:                                  # noqa: BLE001 -- a tick never raises
        return "failed"


def mirror_renewal_status(now=None):
    """The Control Panel's renewal line (#71): {state, reason, last_ok_at, next_try_at}.

    state: off (the Mirror is disarmed) | none (no parseable token) | expired (no seconds left)
    | paused (due, but READ_ONLY forbids the renewal) | failed (due, and the last renewal failed
    against THIS stored token -- a token saved since, by Connect or a renewal, clears it) | ok.
    Offline, never the token or any of its claims."""
    from moonglade.backup import READ_ONLY, _read_only_now
    now = time.time() if now is None else now
    r = _mirror_renewal
    out = {"state": "ok", "reason": "", "last_ok_at": r["last_ok_at"], "next_try_at": None}
    jwt = load_mirror_state().get("jwt") or ""
    exp = jwt_expiry(jwt)
    if not mirror_enabled():
        out["state"] = "off"
    elif exp is None:
        out["state"] = "none"
    elif exp - now <= 0:
        out["state"] = "expired"
    elif mirror_needs_refresh(jwt, now=now):
        if READ_ONLY or _read_only_now():
            out["state"] = "paused"
        elif r["fails"] and r["failed_exp"] == exp:
            out.update(state="failed", reason=r["last_reason"], next_try_at=r["next_try"])
    return out


def _session_for_create(api_session):
    """The session the CREATE POST must use: the browser JWT (mirror) when the 'Mirror to
    PixAI' toggle is on, so the generation lands in the pixai.art web library; else the
    API-key api_session, exactly as today. The single choke every create site routes
    through (review F4) -- swap ONLY the create's session, never the poll/collect/media
    calls (F6), and NEVER fall back to the API key when mirroring: if the mirror session
    is unavailable, refuse and spend nothing (F5).

    Callers must have already passed _check_read_only, since make_mirror_session may make a
    renewal network call (review F12). free-card (/v2/kaisuuken/check) still runs on the
    API-key session at the call site -- only the create rides the JWT.

    3.22 (DESIGN_3.22 2.5): the Mirror's answer is a MARKED client, PixAIClient(...,
    auth_kind="web-jwt"), so the door and every log line know the identity it truly rides;
    and a client PixAIClient.for_create already chose for this send (`_create_chosen`) is
    handed straight back, so one send never chooses its identity twice (V8)."""
    from moonglade.backup import PixAIError
    if getattr(api_session, "_create_chosen", False) is True:
        return api_session
    if not mirror_enabled():
        return api_session
    m = make_mirror_session()
    if m is None:
        raise PixAIError(
            "Mirror to PixAI is ON but its website sign-in is expired or unavailable -- "
            "click your Connect from PixAI bookmark on a signed-in pixai.art tab (it is on "
            "the Mirror to PixAI tile in the Control Panel). Nothing was submitted and no "
            "credits were spent.")
    if getattr(m, "_is_pixai_client", False) is True:
        return m
    from moonglade.pixai_client import PixAIClient
    client = PixAIClient(m, auth_kind="web-jwt")
    client._create_chosen = True
    return client


def run_mirror_check(args):
    """--mirror-check: prove the mirror's renewal WITHOUT ever printing the token. Renews the
    STORED session once (POST /v2/auth/refresh-token, the JWT-only road); reports only
    days-left, the road, ok/fail and the fixed reason word, and persists the fresh session.
    It spends nothing, and it never reads a browser: a sign-in gets in only through Connect
    from PixAI, which checks it is the API key's account. Refused under READ_ONLY (renewing
    the session changes your account)."""
    from moonglade.backup import READ_ONLY, _read_only_now
    if READ_ONLY or _read_only_now():
        print("Mirror: READ_ONLY is set in config.json -- refusing to renew the mirror "
              "session (renewing the session changes your account). Clear READ_ONLY to run "
              "this.")
        return {"ok": False, "source": "read_only"}
    jwt = load_mirror_state().get("jwt") or ""
    src = "stored"
    if not jwt:
        print("Mirror: no session saved. Click your Connect from PixAI bookmark on a signed-in "
              "pixai.art tab (it is on the Mirror to PixAI tile in the Control Panel), then "
              "retry.")
        return {"ok": False, "source": "none"}
    before = jwt_days_left(jwt)
    road = "jwt"
    fresh = refresh_jwt(_mirror_session_from(jwt), current_jwt=jwt,
                        expected_sub=jwt_claims(jwt).get("sub"))
    reason = _refresh_last.get("reason") or "failed"
    # A fixed phrase per reason word. no_credential means nothing was sent, so PixAI was not
    # asked and must not be quoted as answering.
    why = ("no saved website session to renew (nothing was sent)"
           if reason == "no_credential" else "PixAI answered: {}".format(reason))
    if not fresh:
        # A still-valid JWT whose renewal merely failed (a transient 5xx, a refusal) is
        # reported distinctly from a truly-dead one, and it is kept.
        if _jwt_usable(jwt):
            save_mirror_state({"jwt": jwt})
            print("Mirror ({}): the stored JWT is still valid ({} days left) but PixAI did NOT "
                  "renew the session -- renewal may be temporarily unavailable. It keeps "
                  "working until it nears expiry; re-run then. ({})".format(
                      src, before, why))
            return {"ok": True, "source": src, "renewed": False, "days_left": before,
                    "reason": reason}
        print("Mirror ({}): the JWT is expired and the session was not renewed. Click your "
              "Connect from PixAI bookmark on a signed-in pixai.art tab, then retry. "
              "({})".format(src, why))
        return {"ok": False, "source": src, "renewed": False, "reason": reason}
    after = jwt_days_left(fresh)
    # The app's own renewal: stamp when it minted the token (the ring's span, #71) and record
    # the success and its road, so the background tick's 6 h floor counts it.
    minted = time.time()
    saved = save_mirror_state({"jwt": fresh, "minted_at": minted})
    _mirror_renewal.update(fails=0, next_try=0.0, failed_exp=None, last_ok_at=minted,
                           last_reason="", last_road=road)
    print("Mirror OK (source: {}, renewed via {}). PixAI renewed the session -> {} days "
          "left{}. {}".format(
              src, road, after, "" if before is None else " (was {})".format(before),
              "Stored." if saved else "WARNING: could not persist mirror_session.json."))
    return {"ok": True, "source": src, "renewed": True, "days_left": after, "road": road}


# ===========================================================================
# MIRROR-SUBMIT INVARIANTS (upheld by the code above; from the 2026-08-14 adversarial review
# and the 2026-08-15 ultrareview). This is a SPEND + CREDENTIAL path -- keep all of these:
#  1. Single submit: exactly one createGenerationTask per create; the create session is
#     swapped ONLY at the _session_for_create choke, and every credit-spending create routes
#     through it (image/edit/video/reference-video via submit_generation, AND the /v2 fixer).
#  2. No gql_adhoc for spend: createGenerationTask goes through gql_mutate (retries=0).
#  3. READ_ONLY fires before any mirror network call: the renewal (POST
#     /v2/auth/refresh-token: make_mirror_session, run_mirror_check, mirror_renew_tick --
#     and again inside _mirror_try_renew's lock) and the create (submit_generation/
#     submit_fixer). /api/mirror/connect-token (Connect from PixAI) refuses under READ_ONLY
#     too, before it stores anything.
#  4. No credential emission: the JWT is never printed/logged/returned; diagnostics report
#     only days-left + ok/None + a fixed reason word; the credential travels only in a POST
#     body/Authorization. The renewal's response body carries the fresh token and is read
#     for that only -- never logged, never put in a message. The renewal never carries the
#     API key (refresh_jwt refuses one before sending anything). Connect from PixAI carries
#     the user's own sign-in from their pixai.art tab to THIS server only: the bookmark posts it
#     to the one Moonglade address baked into it, the page takes it only from
#     https://pixai.art, and accept_site_token's refusals are fixed sentences.
#  5. No silent API-key fallback: make_mirror_session decides refuse-vs-allow OFFLINE from a
#     usable-JWT check and returns None on failure; _session_for_create raises rather than
#     using the API key when the mirror is ON.
#  6. Collect stays on the API-key session: only the create POST rides the mirror JWT;
#     poll / collect_generation / GET /v1/media do NOT.
#  7. JWT-only: no cookies are stored, sent or paired (they died ~1 h after issue and pairing
#     them across browser profiles risked a cross-identity submit); the fresh token's `sub`
#     must match the stored one's, the renewal never follows a redirect (a 3xx's Set-Cookie
#     would ride the next hop), and any cookie PixAI writes back is cleared off the session
#     after the renewal. A sign-in handed over by Connect from PixAI is the token alone (the
#     tab's cookies never leave the browser), and accept_site_token stores it only when its
#     `sub` is the account the API key resolves to -- a tab signed in as anyone else is
#     refused, so the bookmark can never move the Mirror to a second identity. The one-click
#     Connect (the browser read, POST /api/mirror/connect) is held to the same check: its token
#     goes through accept_site_token, never a direct save. --mirror-check renews the stored
#     token only, and never reads a browser.
#     Every renewal is held to the stored token's `sub`. The
#     same-session cookie read the 2026-08-17 ruling allows is not built: #92's B0 check (2026-10-28) found no installed profile's pixai.art cookies
#     readable -- the running browser holds the Cookies file locked (Chrome and Edge Default;
#     Brave not installed), and current Chrome encrypts cookie values with app-bound "v20"
#     anyway -- so the ruling's own clause applies and the renewal is JWT-only.
# ===========================================================================
