"""
moonglade/web_devices.py
========================
Remembered devices: a browser signed in with "Remember this device", and a paired TV (owner
ruling 2026-11-22, Direction C; spec scopes/SPEC_2026-11-23_remember-device-and-pairing.md).

Each one is a record in local/remembered_devices.json:
    {id, user, kind: "browser"|"tv", label, created, last_seen, expires, epoch, sid?, token_hash?}
`epoch` is the account's session epoch when the record was made; the request gate honours a record
only while that is still the account's epoch and `expires` (created + REMEMBER_DEVICE_LIFETIME_S)
has not passed (is_live). A browser record holds its session's `sid`, so ending the record also
records that sid as signed out (moonglade.web_sessions) until the record would have expired: a
build that ignores remembered devices still refuses the cookie. A TV record holds the SHA-256 of
its bearer token, never the token. No record holds an address.

How it is kept (the pattern of moonglade.web_sessions, with the review's changes, R7 and R15):
  * Reads are cached on (path, mtime_ns, size), so the gate's per-request check is one stat.
  * Every write is a fresh read, a change, and an atomic replace through
    secure_files.write_private (owner-only before a byte is written), under a thread lock AND an
    OS lock on a sidecar (remembered_devices.json.lock), so the command line's --remove-web-user,
    in another process, cannot lose a change against the server.
  * A file that exists but cannot be read or parsed is never treated as empty: reads raise
    DevicesUnreadable, a write is abandoned, and the gate answers 503 rather than signing a
    device out (a TV unpairs on a 401).
  * Writes drop expired records only. A record from an older epoch is refused by the gate and
    deleted by the account writes that change the epoch (moonglade.web_accounts); it is never
    pruned on a guess.
  * touch() and every update change only a record found in the fresh read, and never recreate one.

Lock order: moonglade.web_accounts calls in here while it holds the accounts lock. Nothing here
takes that lock, so the order is always accounts lock, then this module's own.
"""
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time

from moonglade import paths as _paths
from moonglade import secure_files as _secure_files
from moonglade import web_sessions as _web_sessions

_log = logging.getLogger(__name__)
_lock = threading.Lock()
_cache = {"key": None, "records": {}}

KINDS = ("browser", "tv")
TOUCH_EVERY_S = 3600          # last_seen is written at most once an hour per device
LABEL_MAX = 40
TV_DEFAULT_LABEL = "Apple TV"
LOCK_WAIT_S = 10.0


class DevicesUnavailable(OSError):
    """The remembered-devices file could not be used just now. Nothing was changed."""


class DevicesUnreadable(DevicesUnavailable):
    """The file exists but could not be read or parsed. It is left exactly as it is."""


class DevicesBusy(DevicesUnavailable):
    """Another process held the file's lock past the wait, or the write itself failed."""


def _lifetime_s():
    from moonglade.web_policy import REMEMBER_DEVICE_LIFETIME_S
    return REMEMBER_DEVICE_LIFETIME_S


def _path():
    return _paths.local_path(_paths.REMEMBERED_DEVICES_NAME)


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _valid(r):
    return (isinstance(r, dict) and isinstance(r.get("id"), str) and r["id"]
            and isinstance(r.get("user"), str) and r["user"] and r.get("kind") in KINDS
            and all(_num(r.get(k)) for k in ("created", "last_seen", "expires", "epoch")))


def _read(p, fresh=False):
    """{id: record} from the file. An absent file is {}; one that exists but cannot be read or
    parsed raises DevicesUnreadable. A single malformed record is skipped."""
    try:
        st = p.stat()
    except FileNotFoundError:
        _cache.update(key=(str(p), None), records={})
        return {}
    except OSError as e:
        raise DevicesUnreadable("the remembered-devices file can't be read ({})".format(
            type(e).__name__)) from None
    key = (str(p), st.st_mtime_ns, st.st_size)
    if not fresh and _cache["key"] == key:
        return _cache["records"]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        devices = doc["devices"]
        if not isinstance(devices, dict):
            raise TypeError("devices is not an object")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        raise DevicesUnreadable("the remembered-devices file can't be read ({})".format(
            type(e).__name__)) from None
    records = {str(k): r for k, r in devices.items() if _valid(r) and r["id"] == str(k)}
    _cache.update(key=key, records=records)
    return records


# ---- the cross-process lock (the accounts lock's pattern, backup._AccountsLock) -------------
def _lock_fd(fd):
    import errno
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError as e:
            if e.errno in (errno.EACCES, errno.EDEADLK):
                return False
            raise
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    except PermissionError as e:
        if e.errno in (errno.EACCES, errno.EAGAIN):
            return False
        raise


def _unlock_fd(fd):
    if os.name == "nt":
        import msvcrt
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(fd, fcntl.LOCK_UN)


def _take_file_lock(p):
    lock_path = p.with_name(p.name + ".lock")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        raise DevicesBusy("the remembered-devices lock can't be opened") from None
    try:
        deadline = time.monotonic() + LOCK_WAIT_S
        delay = 0.01
        while not _lock_fd(fd):
            if time.monotonic() >= deadline:
                raise DevicesBusy("another Moonglade process is changing the remembered devices")
            time.sleep(delay)
            delay = min(delay * 2, 0.1)
    except BaseException:
        os.close(fd)
        raise
    return fd


class _Locked:
    """This module's thread lock, then the sidecar's OS lock; released in reverse."""

    def __enter__(self):
        _lock.acquire()
        try:
            self._fd = _take_file_lock(_path())
        except BaseException:
            _lock.release()
            raise
        return self

    def __exit__(self, *exc):
        try:
            try:
                _unlock_fd(self._fd)
            finally:
                os.close(self._fd)
        finally:
            _lock.release()
        return False


def _write(p, records):
    """Swap the whole file in, owner-only from its first byte. Raises DevicesBusy on failure."""
    data = json.dumps({"devices": records})
    tmp = p.with_name(p.name + ".tmp-{}-{}".format(os.getpid(), threading.get_ident()))
    try:
        _secure_files.write_private(tmp, data)
        for attempt in range(5):
            try:
                os.replace(tmp, p)
                break
            except PermissionError:
                if attempt == 4:                 # an AV scanner holding the target, on Windows
                    raise
                time.sleep(0.05 * (2 ** attempt))
        _secure_files.restrict_to_owner(p)
    except OSError as e:
        _log.warning("couldn't save the remembered devices (%s); nothing was changed",
                     type(e).__name__)
        raise DevicesBusy("the remembered devices couldn't be saved") from None
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        _cache.update(key=None)


def _prune(records, now):
    """Drop records whose `expires` has passed (R7: expiry only, never a guessed epoch)."""
    return {k: r for k, r in records.items() if r["expires"] > now}


def _end_cookie(rec):
    """R14: a deleted browser record's session id is recorded as signed out until the record
    would have expired, so a build that does not read records still refuses that cookie."""
    if rec.get("kind") == "browser" and rec.get("sid"):
        _web_sessions.sign_out(rec["sid"], rec["created"], rec["expires"] - rec["created"])


def _hash(token):
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


# ---- labels --------------------------------------------------------------------------------
def label_from_user_agent(ua):
    """A coarse name for a browser: "iPhone · Safari", "Mac · Chrome", "Windows · Edge". Unknown
    parts are left off; nothing known at all is "Browser". Never a version, never an address."""
    s = str(ua or "")
    if "iPhone" in s:
        device = "iPhone"
    elif "iPad" in s:
        device = "iPad"
    elif "Android" in s:
        device = "Android"
    elif "CrOS" in s:
        device = "Chromebook"
    elif "Macintosh" in s or "Mac OS X" in s:
        device = "Mac"
    elif "Windows" in s:
        device = "Windows"
    elif "Linux" in s:
        device = "Linux"
    else:
        device = ""
    if "Edg/" in s or "EdgA/" in s or "EdgiOS/" in s:
        browser = "Edge"
    elif "Firefox/" in s or "FxiOS/" in s:
        browser = "Firefox"
    elif "OPR/" in s:
        browser = "Opera"
    elif "Chrome/" in s or "CriOS/" in s:
        browser = "Chrome"
    elif "Safari/" in s:
        browser = "Safari"
    else:
        browser = ""
    return " · ".join(x for x in (device, browser) if x) or "Browser"


def clean_label(label, kind="tv"):
    """A label as stored: printable characters only, whitespace collapsed, at most LABEL_MAX;
    empty becomes the kind's default."""
    text = " ".join("".join(c if c.isprintable() else " " for c in str(label or "")).split())
    text = text[:LABEL_MAX].strip()
    return text or (TV_DEFAULT_LABEL if kind == "tv" else "Browser")


# ---- the API --------------------------------------------------------------------------------
def create(user, kind, label, epoch, token=None, now=None, sid=None):
    """Make a record for `user` and return it (a copy). `epoch` is the account's session epoch now
    (the caller reads it; this takes no accounts lock). A TV needs its `token`, stored hashed; a
    browser passes its session's `sid`. Raises DevicesUnavailable when nothing could be saved."""
    if kind not in KINDS:
        raise ValueError("unknown device kind {!r}".format(kind))
    if kind == "tv" and not token:
        raise ValueError("a TV record needs its token")
    now = time.time() if now is None else now
    rec = {"id": secrets.token_urlsafe(18), "user": str(user), "kind": kind,
           "label": clean_label(label, kind), "created": int(now), "last_seen": int(now),
           "expires": int(now + _lifetime_s()), "epoch": int(epoch)}
    if kind == "tv":
        rec["token_hash"] = _hash(token)
    elif sid:
        rec["sid"] = str(sid)
    p = _path()
    with _Locked():
        records = _prune(dict(_read(p, fresh=True)), now)
        records[rec["id"]] = rec
        _write(p, records)
    return dict(rec)


def get(device_id):
    """The record with this id (a copy), or None. Raises DevicesUnreadable."""
    rec = _read(_path()).get(str(device_id or ""))
    return dict(rec) if rec else None


def find_by_token(token):
    """The TV record this bearer token belongs to (a copy), or None. Raises DevicesUnreadable."""
    if not token:
        return None
    want = _hash(token)
    found = None
    for rec in _read(_path()).values():
        have = rec.get("token_hash")
        if rec["kind"] == "tv" and isinstance(have, str) and hmac.compare_digest(have, want):
            found = rec
    return dict(found) if found else None


def list_for(user):
    """`user`'s records, oldest first (copies). Raises DevicesUnreadable."""
    return sorted((dict(r) for r in _read(_path()).values() if r["user"] == user),
                  key=lambda r: (r["created"], r["id"]))


def list_all():
    """Every record, oldest first (copies). Raises DevicesUnreadable."""
    return sorted((dict(r) for r in _read(_path()).values()),
                  key=lambda r: (r["created"], r["id"]))


def delete(device_id, now=None):
    """Delete one record; returns it, or None when there was none. Raises DevicesUnavailable."""
    now = time.time() if now is None else now
    p = _path()
    if str(device_id or "") not in _read(p):
        return None
    with _Locked():
        records = dict(_read(p, fresh=True))
        rec = records.pop(str(device_id or ""), None)
        if rec is None:
            return None
        _write(p, _prune(records, now))
    _end_cookie(rec)
    return dict(rec)


def delete_for_user(user, keep=None, restamp=None, now=None):
    """Delete every record of `user` except `keep` (an id); `restamp` (an epoch) is written onto
    the kept one (R10: changing your own password keeps this device). Returns the deleted
    records. Raises DevicesUnavailable."""
    now = time.time() if now is None else now
    p = _path()
    if not any(r["user"] == user for r in _read(p).values()):
        return []                       # nothing of theirs: no lock, no write, no lock file
    with _Locked():
        records = dict(_read(p, fresh=True))
        gone = [r for k, r in records.items() if r["user"] == user and k != keep]
        changed = bool(gone)
        for r in gone:
            records.pop(r["id"], None)
        kept = records.get(keep) if keep else None
        if kept is not None and kept["user"] == user and restamp is not None \
                and kept["epoch"] != int(restamp):
            records[keep] = dict(kept, epoch=int(restamp))
            changed = True
        if changed:
            _write(p, _prune(records, now))
    for r in gone:
        _end_cookie(r)
    return [dict(r) for r in gone]


def touch(device_id, now=None):
    """Note that a device was just seen: writes only when its last_seen is an hour old or more,
    and only to a record found in a fresh read under the lock. Never raises; True when written."""
    now = time.time() if now is None else now
    try:
        rec = _read(_path()).get(str(device_id or ""))
        if rec is None or now - rec["last_seen"] < TOUCH_EVERY_S:
            return False
        p = _path()
        with _Locked():
            records = dict(_read(p, fresh=True))
            cur = records.get(str(device_id))
            if cur is None or now - cur["last_seen"] < TOUCH_EVERY_S:
                return False
            records[cur["id"]] = dict(cur, last_seen=int(now))
            _write(p, _prune(records, now))
        return True
    except DevicesUnavailable:
        return False


def is_live(record, current_epoch, now=None):
    """The gate's rule: the record exists, has not expired, and was made under the account's
    current session epoch (None -- no such account -- is never live)."""
    if not record or current_epoch is None:
        return False
    now = time.time() if now is None else now
    try:
        return now < record["expires"] and int(record["epoch"]) == int(current_epoch)
    except (KeyError, TypeError, ValueError):
        return False


def public_view(record, this_device_id=None):
    """What /api/devices shows of a record: never a token, hash, sid or epoch."""
    return {"id": record["id"], "kind": record["kind"], "label": record["label"],
            "created": int(record["created"]), "last_seen": int(record["last_seen"]),
            "expires": int(record["expires"]),
            "this_device": bool(this_device_id) and record["id"] == this_device_id}
