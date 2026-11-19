"""
moonglade/web_sessions.py
=========================
Sessions that Log Out ended, so a copy of a signed-out cookie stops working (app security review
2026-11-19, finding 6).

A Moonglade session is a signed cookie the browser holds. Each one carries its own random id
(`sid`) and the moment it was made (`born`), both written once at sign-in by the gallery's
_establish_session. Log Out on a device records that device's `sid` here, in
local/signed_out_sessions.json; the request gate refuses any cookie whose `sid` is listed. An
entry is kept until the cookie it names would have aged out anyway (`born` plus the absolute
lifetime the gate enforces), then dropped, so the file stays small.

"Sign out all devices" is not this file: it bumps the account's session epoch in config.json,
which ends every cookie for the account at once.

Reads are cached against the file's modification time and path, so the gate's per-request check
is one stat. Writes are atomic (temp file, then replace) under one lock. Never raises to the
caller: a file that cannot be read counts as empty, and a write that fails is logged.
"""
import json
import logging
import os
import threading
import time

from moonglade import paths as _paths

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_cache = {"key": None, "ids": {}}


def _path():
    return _paths.local_path(_paths.SIGNED_OUT_SESSIONS_NAME)


def _read(p):
    try:
        st = p.stat()
    except OSError:
        _cache.update(key=(str(p), None), ids={})
        return {}
    key = (str(p), st.st_mtime_ns, st.st_size)
    if _cache["key"] == key:
        return _cache["ids"]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        ids = {str(k): float(v) for k, v in (doc.get("signed_out") or {}).items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)}
    except (OSError, ValueError, AttributeError, TypeError):
        ids = {}
    _cache.update(key=key, ids=ids)
    return ids


def is_signed_out(sid):
    """True when Log Out has ended the session with this id."""
    if not sid:
        return False
    return str(sid) in _read(_path())


def sign_out(sid, born, lifetime_s, now=None):
    """Record session `sid` (made at `born`) as signed out until born + lifetime_s, dropping
    entries whose cookies have aged out. Returns True when it was written."""
    if not sid:
        return False
    now = time.time() if now is None else now
    p = _path()
    with _lock:
        ids = dict(_read(p))
        try:
            expires = float(born) + float(lifetime_s)
        except (TypeError, ValueError):
            expires = now + float(lifetime_s)
        ids[str(sid)] = expires              # past already? then its cookie is refused by age
        ids = {k: v for k, v in ids.items() if v > now}
        tmp = p.with_name(p.name + ".tmp-{}-{}".format(os.getpid(), threading.get_ident()))
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"signed_out": ids}, f)
            os.replace(tmp, p)
        except OSError as e:
            _log.warning("couldn't record a sign-out (%s); that cookie stays valid until it "
                         "ages out", e)
            try:
                tmp.unlink()
            except OSError:
                pass
            return False
        _cache.update(key=None)
    return True
