"""moonglade/web_loom_store.py -- the Loom's server-side store: the per-key board files and their
migration from the old single store.json, the render journal (which render each shot has in flight,
and the set of renders whose send is still running), the sends ledger, the music beds' folder and
its temp sweep, and the one-object locks around each.

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once. Names the block reads from code still inside create_app come in through
ctx (the bound-from-ctx lines below), and the names other code reads back go out through ctx (the
provided-to-ctx lines at the end), so every closure on both sides holds the one same object.
gallery's own names are imported inside the function that reads them, at call time, so a test's
patch of moonglade.gallery still reaches the store.
"""
import hashlib
import json
import os
import re
import threading
import time

from flask import jsonify, session

from moonglade import account_prefs as _account_prefs
from moonglade import paths as _paths
from moonglade import scan as _scan


def register(app, ctx):
    from moonglade.loom_files import LOOM_BED_TEMP_SWEEP_AGE_S
    # -- bound from ctx (split_move) --
    out_dir = ctx.out_dir
    # -- end --

    # --- The Loom (Seedance storyboard) -------------------------------------
    # Storage is a small key->value store the Loom's window.storage shim reads via
    # /api/loom/*. Each key is now its OWN file, written atomically (tmp + os.replace,
    # the _save_telemetry idiom), so a crash mid-save corrupts at most the single key
    # being written -- one torn project can never take down every other storyboard.
    # The legacy single store.json (all boards + inline thumbs in one non-atomic write)
    # is migrated into per-key files on first touch and preserved as store.json.migrated.
    _loom_lock = threading.Lock()

    def _legacy_loom_kv_dir():
        """The pre-D-7 flat, install-wide store -- every account used to read and write
        the same files here. Now the shared, read-only fallback layer every account's
        _loom_kv_read falls through to until it saves its own copy of a given key."""
        d = _paths.loom_root(out_dir) / "kv"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _legacy_loom_kv_path(key):
        from urllib.parse import quote
        return _legacy_loom_kv_dir() / (quote(str(key), safe="") + ".json")

    def _loom_kv_dir(user):
        # _account_key (B14 residual): a case-safe key for the per-account SUBDIRECTORY
        # -- same fix as _view_presets_path/_snips_path/_presets_path. The KEY portion
        # of a board's filename (_loom_kv_path below) is a separate concern (per-board
        # name collisions within one account's own dir, not account identity) and still
        # uses quote() unchanged.
        d = _paths.loom_root(out_dir) / "kv" / _account_prefs._account_key(user)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _loom_kv_path(user, key):
        from urllib.parse import quote
        return _loom_kv_dir(user) / (quote(str(key), safe="") + ".json")

    def _loom_tomb_path(user, key):
        """Marks a legacy key this account has DELETED.

        Deleting only ever unlinked the account's own copy, and a board it had merely
        inherited from the legacy shared layer had no own copy to unlink -- so the delete
        reported success, the read fell straight back through to the legacy file, and the
        board came back. Every board predating the per-account split behaved that way:
        undeletable, with a fresh one deleting perfectly, which is what made it look like
        the list was showing the same board twice.

        A tombstone rather than deleting the legacy file itself, because that layer is
        shared and read-only to every account by design -- one account tidying its own
        board list must not remove a board out from under another. `.deleted` cannot
        collide with a real key: `quote(safe="")` percent-encodes any dot in a key name.
        """
        from urllib.parse import quote
        return _loom_kv_dir(user) / (quote(str(key), safe="") + ".deleted")

    def _loom_kv_write(user, key, value):
        """Atomically persist one key's value into the ACCOUNT'S OWN dir (tmp +
        os.replace). Never writes the legacy shared dir -- that stays exactly as
        _loom_migrate() left it, a read-only fallback."""
        p = _loom_kv_path(user, key)
        tmp = p.with_name(p.name + ".tmp-%d" % os.getpid())
        tmp.write_text(json.dumps(value), encoding="utf-8")
        os.replace(tmp, p)
        # Writing a key un-buries it: an own copy now exists, so the tombstone has nothing
        # left to suppress, and leaving one behind would hide a board that was deliberately
        # re-created under the same key.
        try:
            _loom_tomb_path(user, key).unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def _loom_kv_read(user, key):
        """This account's value for `key`, falling back read-only to the legacy shared
        store if the account has never saved its own copy of this key -- same pattern as
        _load_view_presets/_load_snippets (D-7: storyboards were install-wide before this,
        so any signed-in account could read AND overwrite every other account's boards)."""
        own = _loom_kv_path(user, key)
        if own.exists():
            try:
                return json.loads(own.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                return None
        if _loom_tomb_path(user, key).exists():
            return None      # this account deleted it; don't resurrect it from the legacy layer
        try:
            return json.loads(_legacy_loom_kv_path(key).read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return None

    def _loom_migrate():
        """One-time split of the legacy single store.json into per-key files, in the
        LEGACY flat dir (unaffected by the D-7 per-account split -- it keeps writing the
        shared fallback layer every account now reads through). Idempotent + crash-safe:
        re-runs from the intact store.json until the final rename lands (a partial
        migration can't lose keys), then no-ops once store.json is gone."""
        legacy = _paths.loom_root(out_dir) / "store.json"
        if not legacy.exists():
            return
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            data = None
        if isinstance(data, dict):
            for k, v in data.items():
                try:
                    p = _legacy_loom_kv_path(k)
                    tmp = p.with_name(p.name + ".tmp-%d" % os.getpid())
                    tmp.write_text(json.dumps(v), encoding="utf-8")
                    os.replace(tmp, p)
                except OSError:
                    return                      # leave store.json for the next touch to retry
        try:
            legacy.replace(legacy.with_name("store.json.migrated"))
        except OSError:
            pass

    # ---- Board revisions (Session P, BUILD-w5-p §3.5, review N5) ------------------------
    # rev = sha1 of the stored JSON text, resolved EXACTLY as _loom_kv_read resolves the value:
    # the account's own file, else (not tombstoned) the legacy shared file, else missing. A
    # board inherited from the legacy layer therefore has a real rev on its first save, and a
    # missing key has one fixed sentinel. Unreadable (a file that exists but will not read or
    # parse, in EITHER layer) is its own answer, never "missing": the client must not seed a
    # blank board over a key it merely failed to read (review F15b).
    _LOOM_REV_MISSING = "missing"

    class _LoomUnreadable(Exception):
        """The key(s) whose file exists but will not read or parse (`keys`, in order)."""
        def __init__(self, *keys):
            super().__init__(*keys)
            self.keys = [str(k) for k in keys]

    def _loom_kv_text(user, key):
        """(text, layer) for this account's view of `key`: layer "own" | "legacy" | None.
        Raises _LoomUnreadable when the file that decides the answer exists but cannot be
        read. Parse errors are checked here too, so a corrupt file is never served."""
        own = _loom_kv_path(user, key)
        if own.exists():
            try:
                t = own.read_text(encoding="utf-8")
                json.loads(t)
                return t, "own"
            except (ValueError, OSError):
                raise _LoomUnreadable(key)
        if _loom_tomb_path(user, key).exists():
            return None, None
        leg = _legacy_loom_kv_path(key)
        if not leg.exists():
            return None, None
        try:
            t = leg.read_text(encoding="utf-8")
            json.loads(t)
            return t, "legacy"
        except (ValueError, OSError):
            raise _LoomUnreadable(key)

    def _loom_rev_of(text):
        return _LOOM_REV_MISSING if text is None else hashlib.sha1(text.encode("utf-8")).hexdigest()

    # ---- The Loom submit journal (Session P, BUILD-w5-p §3.2, review F2/F3/F8) ------------
    # One append-only JSONL per account: out_dir/_moonglade/loom/_submits/<account key>.jsonl. Every state
    # change of one Loom render is a line: sending -> submitted | refused | not_sent |
    # may_have_started, then finished (reported by /api/task-status) or abandoned (the owner
    # released an unclear send). It is what makes a double POST, a second tab, a lost answer
    # and a server restart unable to send one shot twice. Local only, never PixAI.
    _loom_journal_lock = threading.Lock()
    _loom_journal = {}          # account key -> {"subs": {submit_id: entry}, "tasks": {task_id: submit_id}}
    _LOOM_JOURNAL_KEEP_S = 14 * 24 * 3600
    _LOOM_BLOCK_S = 6 * 3600    # the poll ceiling: one render per shot for this long
    _LOOM_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
    # (account key, submit_id) of every render whose loom_generate request is still running
    # in THIS process (spend review B1). Added when "sending" is journalled, removed in the
    # handler's finally; guarded by _loom_journal_lock. It is what tells a live send from a
    # crashed one: the journal alone says "sending" for both. submit-abandon refuses a live
    # one, so a slow PixAI answer can never be released and rendered a second time while the
    # first request is still inside core.submit. After a restart the set is empty, so a send
    # that truly died with the old process can still be released (review F8).
    _loom_sending_now = set()

    def _loom_journal_path(user):
        d = _paths.loom_root(out_dir) / "_submits"
        d.mkdir(parents=True, exist_ok=True)
        return d / (_account_prefs._account_key(user) + ".jsonl")

    def _loom_journal_load(user):
        """The account's index, read once (callers hold _loom_journal_lock). Entries older
        than 14 days are dropped and the file rewritten, on this first read only."""
        k = _account_prefs._account_key(user)
        if k in _loom_journal:
            return _loom_journal[k]
        idx = {"subs": {}, "tasks": {}}
        path = _loom_journal_path(user)
        now = time.time()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for ln in lines:
            try:
                rec = json.loads(ln)
            except ValueError:
                continue
            if not isinstance(rec, dict):
                continue
            sid = str(rec.get("submit_id") or "")
            if not sid:
                continue
            cur = idx["subs"].setdefault(sid, {})
            cur.update({k2: v for k2, v in rec.items() if v is not None})
        for sid in list(idx["subs"]):
            e = idx["subs"][sid]
            if now - float(e.get("first_at") or e.get("at") or now) > _LOOM_JOURNAL_KEEP_S:
                del idx["subs"][sid]
        for sid, e in idx["subs"].items():
            if e.get("task_id"):
                idx["tasks"][str(e["task_id"])] = sid
        if lines:
            try:
                tmp = path.with_name(path.name + ".tmp-%d" % os.getpid())
                tmp.write_text("".join(json.dumps(e) + "\n" for e in idx["subs"].values()),
                               encoding="utf-8")
                os.replace(tmp, path)
            except OSError:
                pass
        _loom_journal[k] = idx
        return idx

    def _loom_journal_note(user, submit_id, **fields):
        """Append one state line and fold it into the index (callers hold the lock)."""
        idx = _loom_journal_load(user)
        e = idx["subs"].setdefault(submit_id, {"submit_id": submit_id, "first_at": time.time()})
        rec = {"submit_id": submit_id, "at": time.time(), "first_at": e["first_at"]}
        rec.update({k2: v for k2, v in fields.items() if v is not None})
        e.update(rec)
        if e.get("task_id"):
            idx["tasks"][str(e["task_id"])] = submit_id
        try:
            with open(_loom_journal_path(user), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
        except OSError:
            pass
        return e

    # The send record (see loom_sends_fold): its own lock, never taken while the journal's is
    # held by the same code path that then waits on the journal -- the spend read copies the
    # journal first, under the journal lock, and only then takes this one.
    _loom_sends_lock = threading.Lock()

    def _loom_sends_path(user):
        d = _paths.loom_root(out_dir) / "_sends"
        d.mkdir(parents=True, exist_ok=True)
        return d / (_account_prefs._account_key(user) + ".jsonl")

    def _loom_sends_lines(user):
        try:
            text = _loom_sends_path(user).read_text(encoding="utf-8")
        except OSError:
            return []
        out = []
        for ln in text.splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
        return out

    def _loom_sends_append(user, recs):
        if not recs:
            return
        try:
            with open(_loom_sends_path(user), "a", encoding="utf-8") as fh:
                fh.write("".join(json.dumps(r) + "\n" for r in recs))
        except OSError:
            pass

    def _loom_send_note(user, **rec):
        """Record one render sent from a board. Fail-soft: the record can never affect the
        spend it describes."""
        rec.setdefault("at", time.time())
        rec.setdefault("kind", "render")
        try:
            with _loom_sends_lock:
                _loom_sends_append(user, [rec])
        except Exception:                                  # noqa: BLE001
            pass

    def _loom_board_saved(user, board_id):
        """The board as saved (the kv value may be the board's JSON text), or None."""
        v = _loom_kv_read(user, "storyboard:v2:proj:" + board_id)
        for _ in range(3):
            if not isinstance(v, str):
                break
            try:
                v = json.loads(v)
            except ValueError:
                return None
        return v if isinstance(v, dict) else None

    def _loom_journal_live_for(user, board, card):
        """The entry that still owns (board, card): sent or maybe sent, not finished, not
        released, younger than the poll ceiling."""
        idx = _loom_journal_load(user)
        now = time.time()
        for e in idx["subs"].values():
            if e.get("board") != board or e.get("card") != card:
                continue
            if e.get("finished") or e.get("state") not in ("sending", "submitted", "may_have_started"):
                continue
            if now - float(e.get("first_at") or e.get("at") or 0) > _LOOM_BLOCK_S:
                continue
            return e
        return None

    # ---- The music bed's store (Session P, P3; rulings 8 and 15; review F18/F19) -------------
    # out_dir/_moonglade/loom/_beds/<account key>/<sha1>.<ext>. Every read and write resolves a name that
    # has already matched LOOM_BED_FILE_RE and then checks _is_under the CALLER's own folder, so
    # neither a crafted name nor another account's bed can be reached.
    def _loom_beds_dir(user):
        return _paths.loom_root(out_dir) / "_beds" / _account_prefs._account_key(user)

    # Spend review N5: an upload or a bundle import killed mid-write leaves its temp file in the
    # account's bed folder, invisible to the unused list and the sweep (they match finished
    # names only). Swept here, at start, once an hour old -- as the EDL exports are. Only files
    # of exactly the two temp shapes, directly inside _beds/<account>/, are ever touched.
    _LOOM_BED_TEMP_RE = re.compile(r"^\.(upload|import)-[^/\\]*\.part$")
    try:
        _beds_root = _paths.loom_root(out_dir) / "_beds"
        for _acct in (_beds_root.iterdir() if _beds_root.is_dir() else []):
            if not _acct.is_dir():
                continue
            for _tmp in _acct.iterdir():
                try:
                    if (_LOOM_BED_TEMP_RE.match(_tmp.name) and _tmp.is_file()
                            and time.time() - _tmp.stat().st_mtime > LOOM_BED_TEMP_SWEEP_AGE_S):
                        _tmp.unlink()
                except OSError:
                    pass
    except OSError:
        pass

    def _loom_bed_path(user, name):
        """The caller's bed file for `name`, or None (bad name, outside the folder, absent)."""
        from moonglade.loom_files import LOOM_BED_FILE_RE
        name = str(name or "")
        if not LOOM_BED_FILE_RE.match(name):
            return None
        d = _loom_beds_dir(user)
        p = d / name
        try:
            if not _scan._is_under(p.resolve(), d.resolve()) or not p.is_file():
                return None
        except OSError:
            return None
        return p

    def _loom_store_bed(user, src_path, ext):
        """Move a finished temp file into the caller's bed folder under the sha1 of its bytes.
        An identical bed already there is not rewritten (the temp file is dropped). -> name."""
        h = hashlib.sha1()
        with open(src_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        name = h.hexdigest() + "." + ext
        d = _loom_beds_dir(user)
        d.mkdir(parents=True, exist_ok=True)
        dest = d / name
        if dest.is_file():
            try:
                os.unlink(src_path)
            except OSError:
                pass
        else:
            os.replace(src_path, dest)
        return name

    def _loom_account_projects(user):
        """Every board this account can open (its own keys and the legacy keys it has not
        buried -- loom_list's set), parsed. Read-only. Raises _LoomUnreadable when any board's
        file exists but does not read: an unreadable board is not a missing one, so a caller
        deciding what is UNUSED must refuse rather than treat that board's bed as free (red
        team 2026-10-01: the sweep deleted the bed of a truncated board). It reads every board
        before it raises, so the refusal names ALL the unreadable ones (GitHub #57)."""
        from urllib.parse import unquote
        with _loom_lock:
            own = {unquote(f.stem) for f in _loom_kv_dir(user).glob("*.json")}
            legacy = {unquote(f.stem) for f in _legacy_loom_kv_dir().glob("*.json")}
            buried = {unquote(f.stem) for f in _loom_kv_dir(user).glob("*.deleted")}
            keys = sorted((own | legacy) - buried)
            out, bad = [], []
            for k in keys:
                if not (k.startswith("storyboard:v2:proj:") or k == "storyboard:v2:project"):
                    continue
                try:
                    text, _layer = _loom_kv_text(user, k)
                except _LoomUnreadable:
                    bad.append(k)
                    continue
                if text is None:
                    continue
                v = json.loads(text)
                if isinstance(v, str):
                    try:
                        v = json.loads(v)
                    except ValueError:
                        bad.append(k)
                        continue
                if isinstance(v, dict):
                    out.append(v)
        if bad:
            raise _LoomUnreadable(*bad)
        return out

    def _loom_unreadable_boards(user, keys):
        """What the owner needs to find each board that will not read (GitHub #57), and nothing
        else from it: {board: its id, name: best-effort (loom_board_name_salvage), saved: the
        file's time (UTC ISO), where: the file relative to the library -- never a host path}.
        The file is the one that decides the answer, as _loom_kv_text resolves it."""
        from moonglade.loom_files import loom_board_name_salvage
        from datetime import datetime, timezone
        rows = []
        for k in keys:
            p = _loom_kv_path(user, k)
            if not p.exists():
                p = _legacy_loom_kv_path(k)
            try:
                where = p.resolve().relative_to(out_dir.resolve()).as_posix()
            except (OSError, ValueError):
                where = p.name
            saved, name = "", ""
            try:
                saved = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                with open(p, "rb") as fh:
                    name = loom_board_name_salvage(fh.read(4096).decode("utf-8", "replace"))
            except OSError:
                pass
            board = k[len("storyboard:v2:proj:"):] if k.startswith("storyboard:v2:proj:") else k
            rows.append({"board": board, "name": name, "saved": saved, "where": where})
        return rows

    def _loom_beds_unreadable_answer(user, exc):
        """The 409 both bed routes answer while a board will not read: a sentence naming each
        board and its file, ending "Nothing was swept.", plus the rows for the Loom's own line."""
        rows = _loom_unreadable_boards(user, exc.keys)
        named = ", ".join('"{}" ({})'.format(r["name"] or r["board"], r["where"]) for r in rows)
        head = ("A storyboard didn't read" if len(rows) == 1 else "{} storyboards didn't read".format(len(rows)))
        msg = ("{}, so no music bed can be called unused: {}. Restore {} from a backup or delete {}. "
               "Nothing was swept.").format(head, named, "its file" if len(rows) == 1 else "their files",
                                             "it" if len(rows) == 1 else "them")
        return jsonify({"error": msg, "unreadable": rows}), 409

    def _loom_unused_beds(user):
        """[(name, bytes)] of the caller's beds no board of the account references, oldest
        first, leaving out any bed added in the last LOOM_BED_UNUSED_GRACE_S (its board's save
        may not have landed). Read-only."""
        from moonglade.loom_files import LOOM_BED_FILE_RE, LOOM_BED_UNUSED_GRACE_S, loom_board_beds
        d = _loom_beds_dir(user)
        if not d.is_dir():
            return []
        used = loom_board_beds(_loom_account_projects(user))
        now = time.time()
        out = []
        for f in d.iterdir():
            if not LOOM_BED_FILE_RE.match(f.name) or f.name in used:
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            if now - st.st_mtime < LOOM_BED_UNUSED_GRACE_S:
                continue
            out.append((st.st_mtime, f.name, st.st_size))
        return [(n, b) for (_m, n, b) in sorted(out)]

    def _loom_journal_finish_task(task_id):
        """/api/task-status reported a journalled task done or failed: mark it finished, so
        its shot may render again at once. A dict lookup; nothing for other tasks."""
        tid = str(task_id or "")
        user = str(session.get("user") or "")
        if not tid or not user:
            return
        with _loom_journal_lock:
            idx = _loom_journal_load(user)
            sid = idx["tasks"].get(tid)
            if sid and not idx["subs"].get(sid, {}).get("finished"):
                _loom_journal_note(user, sid, finished=True)

    # -- provided to ctx (split_move) --
    ctx._LOOM_ID_RE = _LOOM_ID_RE
    ctx._LOOM_REV_MISSING = _LOOM_REV_MISSING
    ctx._LoomUnreadable = _LoomUnreadable
    ctx._legacy_loom_kv_dir = _legacy_loom_kv_dir
    ctx._legacy_loom_kv_path = _legacy_loom_kv_path
    ctx._loom_bed_path = _loom_bed_path
    ctx._loom_beds_dir = _loom_beds_dir
    ctx._loom_beds_unreadable_answer = _loom_beds_unreadable_answer
    ctx._loom_board_saved = _loom_board_saved
    ctx._loom_journal_finish_task = _loom_journal_finish_task
    ctx._loom_journal_live_for = _loom_journal_live_for
    ctx._loom_journal_load = _loom_journal_load
    ctx._loom_journal_lock = _loom_journal_lock
    ctx._loom_journal_note = _loom_journal_note
    ctx._loom_kv_dir = _loom_kv_dir
    ctx._loom_kv_path = _loom_kv_path
    ctx._loom_kv_text = _loom_kv_text
    ctx._loom_kv_write = _loom_kv_write
    ctx._loom_lock = _loom_lock
    ctx._loom_migrate = _loom_migrate
    ctx._loom_rev_of = _loom_rev_of
    ctx._loom_send_note = _loom_send_note
    ctx._loom_sending_now = _loom_sending_now
    ctx._loom_sends_append = _loom_sends_append
    ctx._loom_sends_lines = _loom_sends_lines
    ctx._loom_sends_lock = _loom_sends_lock
    ctx._loom_store_bed = _loom_store_bed
    ctx._loom_tomb_path = _loom_tomb_path
    ctx._loom_unused_beds = _loom_unused_beds
    # -- end --
