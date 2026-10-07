"""The machine files move into `local/` (3.20.0, "the move", item 1).

The art pack and its .version marker, branding.json, branding_slots.json, mirror_session.json,
serve.txt, serve.log and the icon cache now live in the app folder's `local/`. A real start
(moonglade.gallery's main(), and the launcher for its own two files) brings an install's old
layout across, once, through moonglade.migrate:

  * MOVED (os.replace, same volume): the pack + .version (a pack still under its pre-v7 name
    goes through 3.18's rename first) and mirror_session.json (a rotating login token: two
    copies would diverge);
  * COPIED, the old copy left for one release so 3.19 still works: branding.json,
    branding_slots.json, serve.txt -- and the icon cache (_container_cache/ -> local/cache/),
    whose old copy also stays because a Desktop shortcut made before 3.20 takes its icon
    from it;
  * serve.log starts fresh in local/; the old serve.log (+ .1-.3) stays where it was;
  * config.json stays at the root and is never touched.

What moved is written down in local/MOVED.json. A reader asks the new place and falls back
to the old one only while the file is missing there and the migration has not recorded it.

Every test here builds its own app folder in tmp_path and points moonglade.paths.APP_ROOT at
it; nothing reads or writes the checkout's own files.
"""
import ast
import json
import logging
import os
from pathlib import Path

import pytest

from moonglade import assets as ma
from moonglade import backup as core
from moonglade import gallery as g
from moonglade import migrate as mig
from moonglade import paths
from tests.conftest import REPO_ROOT

# The real resolvers, captured before conftest's per-test pins exist.
_REAL_LOCAL_PATH = paths.local_path
_REAL_LOCAL_DIR = paths.local_dir
_REAL_OLD_LOCAL_PATH = paths.old_local_path

PACK = "moonglade.mgpack"
MARKER = PACK + ".version"
_OLD_NAME = ma.LEGACY_NAME          # the pack's pre-v7 name, never spelled here


@pytest.fixture
def app(tmp_path, monkeypatch):
    """An app folder of this test's own, with the real resolvers answering for it."""
    root = tmp_path / "app"
    root.mkdir()
    monkeypatch.setattr(paths, "APP_ROOT", root)
    monkeypatch.setattr(paths, "local_path", _REAL_LOCAL_PATH)
    monkeypatch.setattr(paths, "local_dir", _REAL_LOCAL_DIR)
    monkeypatch.setattr(paths, "old_local_path", _REAL_OLD_LOCAL_PATH)
    monkeypatch.setattr(paths, "config_path", lambda: root / "config.json")
    monkeypatch.setattr(core, "_config_path", lambda: root / "config.json")
    return root


def _write(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        p.write_text(data, encoding="utf-8")
    else:
        p.write_bytes(data)
    return p


@pytest.fixture
def old_layout(app):
    """A 3.19 install's machine files, all at the app root (the D: shape, small)."""
    _write(app / "config.json", '{"PIXAI_API_KEY": "not-a-real-key"}')
    _write(app / PACK, b"PACK" * 64)
    _write(app / MARKER, '{"version": "7", "sha256": "ab"}')
    _write(app / "branding.json", '{"mark": "mark_4"}')
    _write(app / "branding_slots.json", '{"A02": "x"}')
    _write(app / "serve.txt", "--host 0.0.0.0 --port 5757")
    _write(app / "serve.log", "an old console line\n")
    _write(app / "serve.log.1", "an older one\n")
    _write(app / "mirror_session.json", '{"jwt": "not-a-real-token"}')
    _write(app / "_container_cache" / "marks" / "mark_4.ico", b"\x00\x00\x01\x00ico")
    return app


def _moved_doc(app):
    return json.loads((app / "local" / "MOVED.json").read_text(encoding="utf-8"))


# ---- where things are -------------------------------------------------------------------

def test_the_machine_files_folder_is_local_under_the_app_folder(app):
    assert paths.local_dir() == app / "local"
    for name in (PACK, MARKER, "branding.json", "branding_slots.json", "serve.txt",
                 "mirror_session.json"):
        assert paths.local_path(name) == app / "local" / name, name
    # the launcher's log goes to local/ as soon as there is a local/ (the launcher's own tidy
    # makes it), and beside the launcher on an install that could not make one
    assert paths.local_path("serve.log") == app / "serve.log"
    (app / "local").mkdir()
    assert paths.local_path("serve.log") == app / "local" / "serve.log"


def test_the_icon_cache_is_local_cache(app):
    assert paths.icon_cache_dir() == app / "local" / "cache" / "marks"


def test_the_old_places_are_the_app_root(app):
    """Where 3.19 kept each one -- the migration's source and the reader's fallback."""
    assert paths.old_local_path("branding.json") == app / "branding.json"
    assert paths.old_local_path(PACK) == app / PACK
    assert paths.old_local_path("cache") == app / "_container_cache"
    # 3.19's mirror rule: beside wherever config.json was found
    assert paths.old_local_path("mirror_session.json") == app / "mirror_session.json"


def test_the_app_asks_local_path(app):
    assert g._container_path() == app / "local" / PACK
    assert g._branding_path(Path("/any/library")) == app / "local" / "branding.json"
    assert g._slot_active_path(Path("/any/library")) == app / "local" / "branding_slots.json"
    assert core._mirror_state_path() == app / "local" / "mirror_session.json"


# ---- the migration -----------------------------------------------------------------------

def test_the_old_layout_moves_into_local(old_layout):
    app = old_layout
    out = mig.migrate_local()
    loc = app / "local"
    # moved: gone from the old place, whole in the new
    assert (loc / PACK).read_bytes() == b"PACK" * 64 and not (app / PACK).exists()
    assert (loc / MARKER).is_file() and not (app / MARKER).exists()
    assert (loc / "mirror_session.json").is_file() and not (app / "mirror_session.json").exists()
    # copied: in both places, same bytes -- the icon cache too, which an old Desktop shortcut
    # may still take its icon from
    assert (loc / "cache" / "marks" / "mark_4.ico").read_bytes() == b"\x00\x00\x01\x00ico"
    assert (app / "_container_cache" / "marks" / "mark_4.ico").is_file()
    for name in ("branding.json", "branding_slots.json", "serve.txt"):
        assert (loc / name).read_bytes() == (app / name).read_bytes(), name
    # serve.log starts fresh: nothing copied, the old ones left
    assert not (loc / "serve.log").exists()
    assert (app / "serve.log").is_file() and (app / "serve.log.1").is_file()
    # config.json never moves
    assert (app / "config.json").is_file() and not (loc / "config.json").exists()
    assert not out.failed


def test_the_manifest_records_what_moved(old_layout):
    mig.migrate_local()
    doc = _moved_doc(old_layout)
    by = {e["name"]: e for e in doc["entries"]}
    assert {n: by[n]["action"] for n in by} == {
        PACK: "moved", MARKER: "moved", "mirror_session.json": "moved", "cache": "copied",
        "branding.json": "copied", "branding_slots.json": "copied", "serve.txt": "copied"}
    # (serve.log is recorded once the new launcher's own log exists:
    # test_serve_log_is_recorded_only_once_the_new_one_is_real)
    pack = by[PACK]
    assert pack["source"] == PACK and pack["dest"] == "local/" + PACK
    assert pack["size"] == 256
    assert pack["time"].endswith("Z")
    assert by["cache"]["source"] == "_container_cache" and by["cache"]["dest"] == "local/cache"


def test_a_second_run_is_a_no_op(old_layout):
    mig.migrate_local()
    manifest = old_layout / "local" / "MOVED.json"
    before = (manifest.read_bytes(), manifest.stat().st_mtime_ns)
    snapshot = sorted(str(p.relative_to(old_layout)) for p in old_layout.rglob("*"))
    again = mig.migrate_local()
    assert not again.done and not again.failed
    assert (manifest.read_bytes(), manifest.stat().st_mtime_ns) == before
    assert sorted(str(p.relative_to(old_layout)) for p in old_layout.rglob("*")) == snapshot


def test_a_fresh_install_has_nothing_to_bring(app):
    out = mig.migrate_local()
    assert not out.done and not out.failed
    assert (app / "local").is_dir()


def test_downgrade_safety_what_3_19_reads_is_still_there(old_layout):
    """Going back to 3.19 still finds every copied file where it always was; only the moved
    ones (the pack and its marker, the mirror token) are not."""
    app = old_layout
    mig.migrate_local()
    for name in ("config.json", "branding.json", "branding_slots.json", "serve.txt",
                 "serve.log"):
        assert (app / name).is_file(), name
    assert (app / "_container_cache" / "marks" / "mark_4.ico").is_file()


# ---- readers -----------------------------------------------------------------------------

def test_a_reader_with_an_unmigrated_tree_still_works(old_layout):
    app = old_layout
    assert paths.local_path("branding.json") == app / "branding.json"
    assert paths.local_path("serve.txt") == app / "serve.txt"
    assert g._container_path() == app / PACK
    assert ma._version_marker_path(g._container_path()) == app / MARKER
    assert core._mirror_state_path() == app / "mirror_session.json"
    assert core.load_mirror_state() == {"jwt": "not-a-real-token"}
    assert paths.icon_cache_dir() == app / "_container_cache" / "marks"


def test_after_the_migration_readers_use_local(old_layout):
    app = old_layout
    mig.migrate_local()
    for name in (PACK, MARKER, "branding.json", "branding_slots.json", "serve.txt",
                 "mirror_session.json"):
        assert paths.local_path(name) == app / "local" / name, name
    assert paths.local_path("serve.log") == app / "local" / "serve.log"      # fresh
    assert core.load_mirror_state() == {"jwt": "not-a-real-token"}


def test_a_deleted_new_copy_never_brings_the_old_one_back(old_layout):
    """Once the migration has recorded a file, the old copy is a leftover: deleting the new
    one (to reset a choice) must not resurrect the stale old one."""
    app = old_layout
    mig.migrate_local()
    (app / "local" / "branding.json").unlink()
    assert paths.local_path("branding.json") == app / "local" / "branding.json"


def test_both_present_the_new_one_wins(app):
    _write(app / "branding.json", '{"mark": "old"}')
    _write(app / "local" / "branding.json", '{"mark": "new"}')
    mig.migrate_local()
    assert paths.local_path("branding.json") == app / "local" / "branding.json"
    assert json.loads((app / "local" / "branding.json").read_text())["mark"] == "new"
    assert (app / "branding.json").is_file()                 # never deleted: a leftover


# ---- the pack's pre-v7 name --------------------------------------------------------------

def test_a_pack_under_its_old_name_is_renamed_then_moved(app):
    _write(app / _OLD_NAME, b"OLDPACK")
    _write(app / (_OLD_NAME + ".version"), '{"version": "6", "sha256": "cd"}')
    mig.migrate_local()
    assert (app / "local" / PACK).read_bytes() == b"OLDPACK"
    assert json.loads((app / "local" / MARKER).read_text())["version"] == "6"
    assert not (app / _OLD_NAME).exists() and not (app / PACK).exists()


def test_both_pack_names_leave_the_old_one_and_move_the_new(app):
    _write(app / _OLD_NAME, b"OLDPACK")
    _write(app / PACK, b"NEWPACK")
    out = mig.migrate_local()
    assert (app / "local" / PACK).read_bytes() == b"NEWPACK"
    assert (app / _OLD_NAME).read_bytes() == b"OLDPACK"     # never deleted
    assert any(_OLD_NAME in n for n in out.notes)


# ---- failure never stops a start ---------------------------------------------------------

def _refuse_replace_of(monkeypatch, *names):
    real = os.replace

    def replace(src, dst):
        if Path(src).name in names:
            raise PermissionError("in use: %s" % src)
        return real(src, dst)
    monkeypatch.setattr(os, "replace", replace)


def test_a_locked_pack_stays_put_and_is_still_read(old_layout, monkeypatch):
    app = old_layout
    real_replace = os.replace
    _refuse_replace_of(monkeypatch, PACK)
    out = mig.migrate_local()
    assert [f[0] for f in out.failed] == [PACK]
    assert (app / PACK).is_file() and not (app / "local" / PACK).exists()
    assert (app / MARKER).is_file()                    # the marker stays with its pack
    assert g._container_path() == app / PACK            # read where it still is
    # ...and the next start tries again
    monkeypatch.setattr(os, "replace", real_replace)
    again = mig.migrate_local()
    assert {e["name"] for e in again.done} == {PACK, MARKER}
    assert g._container_path() == app / "local" / PACK


def test_a_read_only_app_folder_logs_once_and_the_start_carries_on(old_layout, monkeypatch,
                                                                    caplog):
    app = old_layout
    real_mkdir = Path.mkdir

    def mkdir(self, *a, **k):
        if self.name == "local":
            raise PermissionError("read-only")
        return real_mkdir(self, *a, **k)
    monkeypatch.setattr(Path, "mkdir", mkdir)
    with caplog.at_level(logging.DEBUG, logger="moonglade"):
        out = mig.tidy_app_folder()            # main()'s call: never raises
    assert out.failed
    mine = [r for r in caplog.records if r.name == mig.LOGGER_NAME]
    assert len(mine) == 1 and mine[0].levelno == logging.WARNING
    assert paths.local_path("branding.json") == app / "branding.json"   # still read
    assert g._container_path() == app / PACK


def test_the_tidy_logs_under_the_apps_own_logger(old_layout, caplog):
    """moonglade.logs lets the `moonglade` logger through to the file at every level; a
    logger outside it stops at WARNING, so the line saying what moved would never reach the
    file (3.18's lesson)."""
    assert mig.LOGGER_NAME.startswith("moonglade.")
    with caplog.at_level(logging.DEBUG, logger="moonglade"):
        mig.tidy_app_folder()
    mine = [r for r in caplog.records if r.name == mig.LOGGER_NAME]
    assert len(mine) == 1 and mine[0].levelno == logging.INFO
    assert PACK in mine[0].getMessage()


def test_tidy_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(mig, "migrate_local", boom)
    out = mig.tidy_app_folder()
    assert out.failed


# ---- the launcher's own two files --------------------------------------------------------

def test_the_launchers_tidy_brings_only_its_own_files(old_layout):
    app = old_layout
    out = mig.tidy_launcher_files()
    assert {e["name"] for e in out.done} == {"serve.txt"}     # its new serve.log comes next
    assert (app / "local" / "serve.txt").read_text() == "--host 0.0.0.0 --port 5757"
    assert (app / PACK).is_file()                      # the pack waits for main()
    assert paths.local_path("serve.txt") == app / "local" / "serve.txt"
    assert paths.local_path("serve.log") == app / "local" / "serve.log"


def _launcher():
    src = (REPO_ROOT / "Moonglade Launcher.pyw").read_text(encoding="utf-8")
    return src, ast.parse(src)


def _first_top_level(tree, pred):
    for i, node in enumerate(tree.body):
        if any(pred(n) for n in ast.walk(node)):
            return i
    return None


def test_the_launcher_tidies_its_files_before_it_reads_serve_txt():
    src, tree = _launcher()
    tidy = _first_top_level(tree, lambda n: isinstance(n, ast.Attribute)
                            and n.attr == "tidy_launcher_files")
    reads = _first_top_level(tree, lambda n: isinstance(n, ast.Constant)
                             and n.value == "serve.txt")
    assert tidy is not None and reads is not None and tidy < reads
    # inside a try: a tidy that fails can never stop the launcher
    assert isinstance(tree.body[tidy], ast.Try)
    assert 'local_path("serve.txt")' in src and 'local_path("serve.log")' in src


def test_the_launcher_reads_local_serve_txt_falling_back_to_the_root(old_layout):
    """What the launcher asks, before and after its tidy."""
    app = old_layout
    assert paths.local_path("serve.txt") == app / "serve.txt"
    mig.tidy_launcher_files()
    assert paths.local_path("serve.txt") == app / "local" / "serve.txt"


# ---- main() ------------------------------------------------------------------------------

def test_main_tidies_after_the_port_check_and_before_anything_reads_the_files():
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(g.main)))
    order = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            order.append((node.lineno, name))
    order.sort()
    names = [n for _, n in order]
    assert "tidy_app_folder" in names, "main() does not bring the machine files across"
    at = names.index("tidy_app_folder")
    assert names.index("port_owner") < at, "a refused start must not move the pack"
    for later in ("ensure_branding_discovery_tree", "_record_slot_resolution",
                  "register_pack_file_type", "create_app"):
        assert at < names.index(later), later
    assert "migrate_legacy_name" not in names     # 3.18's rename runs inside the tidy now


# ---- review round: a round trip to 3.19 and back -----------------------------------------

def test_the_moved_files_survive_a_round_trip_to_3_19(old_layout):
    """The rollback note moves the pack, its marker and the Mirror's sign-in back for 3.19,
    which keeps using them. Back on 3.20 they are read where they are, moved again, and never
    listed on About as safe to delete -- whatever MOVED.json already says."""
    app = old_layout
    mig.migrate_local()                                              # 3.20
    for name in (PACK, MARKER, "mirror_session.json"):              # the rollback
        os.replace(app / "local" / name, app / name)
    (app / "mirror_session.json").write_text('{"jwt": "renewed-on-3.19"}', encoding="utf-8")
    # back on 3.20, before the start's tidy: read where they are
    assert g._container_path() == app / PACK
    assert core.load_mirror_state() == {"jwt": "renewed-on-3.19"}
    assert not [n for _, n in mig.leftovers() if n in (PACK, MARKER, "mirror_session.json")]
    mig.migrate_local()                                              # 3.20's next start
    for name in (PACK, MARKER, "mirror_session.json"):
        assert (app / "local" / name).is_file() and not (app / name).exists(), name
    assert core.load_mirror_state() == {"jwt": "renewed-on-3.19"}
    assert g._container_path() == app / "local" / PACK


# ---- review round: the pack's marker only follows its own pack ---------------------------

def test_a_marker_never_moves_beside_a_pack_from_somewhere_else(old_layout):
    """local/ already holds a pack from another source (a download, a copy by hand). The old
    pack's marker describes the OLD pack: it must not move beside the other one and vouch
    for bytes it never saw."""
    app = old_layout
    _write(app / "local" / PACK, b"ANOTHER PACK")
    mig.migrate_local()
    assert not (app / "local" / MARKER).exists()
    assert (app / MARKER).is_file() and (app / PACK).is_file()      # nothing deleted
    assert (app / "local" / PACK).read_bytes() == b"ANOTHER PACK"


def test_a_marker_left_behind_follows_its_own_pack_next_start(old_layout, monkeypatch):
    app = old_layout
    real = os.replace
    _refuse_replace_of(monkeypatch, MARKER)
    mig.migrate_local()
    assert (app / "local" / PACK).is_file() and (app / MARKER).is_file()
    monkeypatch.setattr(os, "replace", real)
    mig.migrate_local()                       # the record moved this same pack: it follows
    assert (app / "local" / MARKER).is_file() and not (app / MARKER).exists()


def test_a_marker_left_behind_stays_when_the_pack_was_replaced_since(old_layout, monkeypatch):
    app = old_layout
    real = os.replace
    _refuse_replace_of(monkeypatch, MARKER)
    mig.migrate_local()
    monkeypatch.setattr(os, "replace", real)
    (app / "local" / PACK).write_bytes(b"A NEWER DOWNLOAD")          # not the pack it described
    mig.migrate_local()
    assert not (app / "local" / MARKER).exists() and (app / MARKER).is_file()


def test_a_pack_renamed_in_the_same_pass_is_recorded_from_its_old_name(app):
    _write(app / _OLD_NAME, b"OLDPACK")
    _write(app / (_OLD_NAME + ".version"), '{"version": "6", "sha256": "cd"}')
    mig.migrate_local()
    by = {e["name"]: e for e in _moved_doc(app)["entries"]}
    assert by[PACK]["source"] == _OLD_NAME
    assert by[MARKER]["source"] == _OLD_NAME + ".version"
    assert by[PACK]["dest"] == "local/" + PACK


# ---- review round: serve.log belongs to whichever launcher is writing it -----------------

def test_serve_log_is_recorded_only_once_the_new_one_is_real(old_layout):
    """The launcher opens local/serve.log AFTER its tidy. Until that file exists the old
    serve.log is still the live log, so nothing records it as left behind."""
    app = old_layout
    mig.migrate_local()
    assert "serve.log" not in paths.moved_names(app / "local" / "MOVED.json")
    assert paths.local_path("serve.log") == app / "local" / "serve.log"   # where it will go
    _write(app / "local" / "serve.log", "the new launcher's first line\n")
    mig.migrate_local()
    entries = paths.moved_entries(app / "local" / "MOVED.json")
    assert entries["serve.log"]["action"] == "fresh"
    assert entries["serve.log.1"]["action"] == "fresh"


def test_serve_log_is_never_recorded_while_an_old_launcher_is_in_charge(old_layout,
                                                                         monkeypatch):
    app = old_layout
    monkeypatch.setenv("MOONGLADE_VIA_STANDIN", "1")
    _write(app / "local" / "serve.log", "")
    mig.migrate_local()
    assert "serve.log" not in paths.moved_names(app / "local" / "MOVED.json")


def test_the_launcher_writes_local_serve_log_from_its_first_start(old_layout):
    app = old_layout
    mig.tidy_launcher_files()
    assert paths.local_path("serve.log") == app / "local" / "serve.log"


def test_the_app_folder_is_tidied_by_one_start_at_a_time(old_layout, monkeypatch):
    app = old_layout
    (app / "local").mkdir()
    (app / "local" / ".migrating").write_text("4242", encoding="utf-8")
    monkeypatch.setattr(mig, "LOCK_WAIT_S", 0.2)
    out = mig.tidy_app_folder()                                     # never raises
    assert out.failed and not out.done
    assert (app / PACK).is_file() and not (app / "local" / PACK).exists()
    (app / "local" / ".migrating").unlink()
    out = mig.migrate_local()
    assert out.done and not (app / "local" / ".migrating").exists()
