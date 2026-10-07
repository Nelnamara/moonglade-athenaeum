"""moonglade_paths: the one place an app-root path is derived (Wave 4 groundwork, 3.19.0).

Three claims, each with its own test:
  * every helper, and every app function that asks one, resolves to the exact path the table
    below names: where it was before the helpers existed, except the pack manifest, which
    3.20 moved into moonglade/ with the code, and the machine files, which live in local/
    since 3.20 (with the old places a start brings them across from);
  * the machine files and the art tree are separate concepts: the pack, branding.json,
    branding_slots.json and the icon cache follow local_path(), never the art tree's parent;
  * no first-party module but moonglade_paths derives an app-root path from `__file__`.

conftest pins `config_path`, `local_path` and `branding_root()` to each test's own folder,
so the real resolvers are captured here at import, before any fixture runs. Calling them
only builds paths; nothing here reads or writes the checkout's own files.
"""
import ast
from pathlib import Path

import pytest

from moonglade import assets as ma
from moonglade import backup as core
from moonglade import gallery as g
from moonglade import paths
from tests.conftest import first_party_sources

_REPO = Path(__file__).resolve().parents[1]

# The real resolvers, captured before conftest's per-test pins exist.
_REAL_CONFIG_PATH = paths.config_path
_REAL_LOCAL_PATH = paths.local_path
_REAL_LOCAL_DIR = paths.local_dir
_REAL_OLD_LOCAL_PATH = paths.old_local_path
_REAL_CORE_CONFIG_PATH = core._config_path
_REAL_BRANDING_ROOT = g.branding_root
_REAL_MANIFEST_PATH = ma.manifest_path


@pytest.fixture
def real_paths(monkeypatch):
    """Undo conftest's pins for one test, so the app's own resolvers answer. Path
    arithmetic only: no test that uses this may touch a file. The old places a machine file
    is read from until a start brings it across point at a folder that does not exist, so
    the answer is the same on every machine (the owner's checkout still HAS its old files)."""
    monkeypatch.setattr(paths, "config_path", _REAL_CONFIG_PATH)
    monkeypatch.setattr(paths, "local_path", _REAL_LOCAL_PATH)
    monkeypatch.setattr(paths, "local_dir", _REAL_LOCAL_DIR)
    monkeypatch.setattr(paths, "old_local_path",
                        lambda name: _REPO / "no-such-folder-before-3.20" / name)
    monkeypatch.setattr(core, "_config_path", _REAL_CORE_CONFIG_PATH)
    monkeypatch.setattr(g, "branding_root", _REAL_BRANDING_ROOT)
    monkeypatch.setattr(ma, "manifest_path", _REAL_MANIFEST_PATH)
    monkeypatch.chdir(_REPO)        # every entry point runs from the app's folder


def test_app_root_is_the_folder_holding_the_launcher():
    assert paths.APP_ROOT == _REPO
    assert (paths.APP_ROOT / "Moonglade Launcher.pyw").is_file()


_LOCAL = _REPO / "local"

# (what, how to ask it, the path it resolves to)
_TABLE = [
    ("config.json", lambda: paths.config_path(), lambda: _REPO / "config.json"),
    ("config.json via the backup", lambda: core._config_path(), lambda: _REPO / "config.json"),
    ("token.txt", lambda: paths.token_paths(),
     lambda: (_REPO / "token.txt", Path("token.txt"))),
    ("the machine files' folder", lambda: paths.local_dir(), lambda: _LOCAL),
    ("the pack", lambda: g._container_path(), lambda: _LOCAL / "moonglade.mgpack"),
    ("the pack's marker", lambda: ma._version_marker_path(g._container_path()),
     lambda: _LOCAL / "moonglade.mgpack.version"),
    ("branding.json", lambda: g._branding_path(Path("/any/library")),
     lambda: _LOCAL / "branding.json"),
    ("branding_slots.json", lambda: g._slot_active_path(Path("/any/library")),
     lambda: _LOCAL / "branding_slots.json"),
    ("mirror_session.json", lambda: core._mirror_state_path(),
     lambda: _LOCAL / "mirror_session.json"),
    ("serve.txt", lambda: paths.local_path("serve.txt"), lambda: _LOCAL / "serve.txt"),
    # a fresh one in local/ whenever local/ exists; beside the launcher when it could not be
    # made (that old place is pointed at an empty folder by real_paths)
    ("serve.log", lambda: paths.local_path("serve.log"),
     lambda: (_LOCAL if _LOCAL.is_dir() else _REPO / "no-such-folder-before-3.20") / "serve.log"),
    ("the icon cache", lambda: paths.icon_cache_dir(), lambda: _LOCAL / "cache" / "marks"),
    ("what moved, recorded", lambda: paths.local_dir() / paths.MOVED_NAME,
     lambda: _LOCAL / "MOVED.json"),
    # where 3.19 kept them: what a start brings across from
    ("the pack before 3.20", lambda: _REAL_OLD_LOCAL_PATH("moonglade.mgpack"),
     lambda: _REPO / "moonglade.mgpack"),
    ("branding.json before 3.20", lambda: _REAL_OLD_LOCAL_PATH("branding.json"),
     lambda: _REPO / "branding.json"),
    ("serve.txt before 3.20", lambda: _REAL_OLD_LOCAL_PATH("serve.txt"),
     lambda: _REPO / "serve.txt"),
    ("the icon cache before 3.20", lambda: _REAL_OLD_LOCAL_PATH("cache"),
     lambda: _REPO / "_container_cache"),
    ("mirror_session.json before 3.20", lambda: _REAL_OLD_LOCAL_PATH("mirror_session.json"),
     lambda: _REPO / "mirror_session.json"),
    ("the art tree", lambda: g.branding_root(), lambda: _REPO / "0x676F6F6473"),
    ("the art tree, helper", lambda: paths.art_root(), lambda: _REPO / g._GOODS_ROOT_NAME),
    ("the legacy art folder", lambda: g.branding_root().parent / "branding",
     lambda: _REPO / "branding"),
    # The one location that moved in 3.20: the manifest is committed with the code.
    ("the pack manifest", lambda: ma.manifest_path(),
     lambda: _REPO / "moonglade" / "manifest.json"),
    ("wiki/", lambda: g.wiki_dir(), lambda: _REPO / "wiki"),
    ("CHANGELOG.md", lambda: g.changelog_path(), lambda: _REPO / "CHANGELOG.md"),
    ("gallery/dist", lambda: paths.gallery_dist(), lambda: _REPO / "gallery" / "dist"),
    ("loom/", lambda: paths.loom_dir(), lambda: _REPO / "loom"),
    ("loom/dist", lambda: paths.loom_dist(), lambda: _REPO / "loom" / "dist"),
    ("loom/vendor", lambda: paths.loom_vendor(), lambda: _REPO / "loom" / "vendor"),
    ("static/", lambda: paths.static_dir(), lambda: _REPO / "static"),
    ("requirements.txt", lambda: paths.requirements_path(), lambda: _REPO / "requirements.txt"),
    ("the launcher", lambda: paths.launcher_path(), lambda: _REPO / "Moonglade Launcher.pyw"),
    # The two old entry scripts: since 3.20 the root stand-ins, kept for one release.
    ("the server script", lambda: paths.gallery_script_path(),
     lambda: _REPO / "moonglade_gallery.py"),
    ("the CLI script", lambda: paths.backup_script_path(),
     lambda: _REPO / "moonglade_backup.py"),
    ("the MCP server's default library", lambda: paths.default_library_path(),
     lambda: _REPO / "pixai_backup"),
    ("the default library (relative)", lambda: g.DEFAULT_LIBRARY_DIR, lambda: "pixai_backup"),
    ("the working directory", lambda: paths.run_dir(), lambda: _REPO),
]


@pytest.mark.parametrize("what,ask,before", _TABLE, ids=[t[0] for t in _TABLE])
def test_every_path_resolves_where_it_did_before(real_paths, what, ask, before):
    assert ask() == before()


def test_the_shipped_files_are_really_there(real_paths):
    """The table's tracked entries name files a checkout has, so a typo in a helper cannot
    hide behind a path that merely looks right."""
    for p in (ma.manifest_path(), g.wiki_dir(), g.changelog_path(), paths.loom_dir(),
              paths.static_dir(), paths.requirements_path(), paths.launcher_path(),
              paths.gallery_script_path(), paths.backup_script_path()):
        assert p.exists(), p


def test_flask_serves_static_from_the_app_folder():
    """create_app() names Flask's static folder from the helper (Flask's default is a folder
    beside the MODULE). Read off the source: building an app here would start one more
    scheduler thread that nothing stops (issue #77) to learn the same thing."""
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(g.create_app)))
    flask = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "Flask"]
    assert len(flask) == 1
    kw = {k.arg: ast.unparse(k.value) for k in flask[0].keywords}
    assert kw.get("static_folder") == "str(_paths.static_dir())"
    assert "static_url_path" not in kw          # Flask derives "/static" from the folder name
    assert paths.static_dir().name == "static"


def test_config_path_keeps_its_rule(monkeypatch, tmp_path):
    """Beside the app first, then the working directory; neither -> beside the app."""
    monkeypatch.setattr(paths, "config_path", _REAL_CONFIG_PATH)
    app, cwd = tmp_path / "app", tmp_path / "cwd"
    app.mkdir()
    cwd.mkdir()
    monkeypatch.setattr(paths, "APP_ROOT", app)
    monkeypatch.chdir(cwd)
    assert paths.config_path() == app / "config.json"           # neither exists
    (cwd / "config.json").write_text("{}", encoding="utf-8")
    assert paths.config_path() == Path("config.json")           # only the cwd one
    (app / "config.json").write_text("{}", encoding="utf-8")
    assert paths.config_path() == app / "config.json"           # beside the app wins


# ---- the machine files are not the art tree's siblings any more ---------------------------

def test_machine_files_follow_local_path_not_the_art_tree(monkeypatch, tmp_path):
    """The art tree and the machine files are separate concepts: the art tree sits at the app
    root and the machine files in local/, and either can move without the other."""
    art, local = tmp_path / "elsewhere" / "art", tmp_path / "local"
    monkeypatch.setattr(g, "branding_root", lambda: art)
    monkeypatch.setattr(paths, "local_path", lambda name: local / name)
    assert g._container_path() == local / "moonglade.mgpack"
    assert g._branding_path(tmp_path) == local / "branding.json"
    assert g._slot_active_path(tmp_path) == local / "branding_slots.json"
    assert paths.icon_cache_dir() == local / "cache" / "marks"
    # ...and the art tree itself still follows branding_root().
    assert g._role_dir("marks").is_relative_to(art)


def test_the_icon_cache_is_written_under_local_path(monkeypatch, tmp_path):
    """A pack-shipped .ico is materialized under local_path(), not beside the art tree."""
    from moonglade import container as mc
    art, local = tmp_path / "elsewhere" / "art", tmp_path / "local"
    local.mkdir()
    monkeypatch.setattr(g, "branding_root", lambda: art)
    monkeypatch.setattr(paths, "local_path", lambda name: local / name)
    mc.write_container(g._container_path(), {
        g._role_rel("marks", "mark_4.ico"): b"\x00\x00\x01\x00ico"}, {})
    g._container_cache.update(path=None, mtime=None, box=None)
    try:
        ico = g._mark_ico_path("mark_4")
    finally:
        g._container_cache.update(path=None, mtime=None, box=None)
    assert ico == local / "cache" / "marks" / "mark_4.ico"
    assert ico.read_bytes() == b"\x00\x00\x01\x00ico"
    assert not (art.parent / "_container_cache").exists()


# ---- the lint: no module but moonglade_paths derives an app-root path from __file__ ------

# A module that genuinely needs its own __file__, with the reason. Everything else asks
# moonglade_paths.
_FILE_ALLOWED = {
    "moonglade/paths.py": "it IS the app-root definition",
    "Moonglade Launcher.pyw": "its own folder, by os.path.abspath, is APP_ROOT unresolved: it goes "
                         "on sys.path so the moonglade package imports however the launcher "
                         "was started, and it is the cwd the server runs from (`-m "
                         "moonglade.gallery` finds the package through it), byte-for-byte as "
                         "in 3.18 on a mapped or subst drive (resolve() would turn those into "
                         "their targets). Every other path comes from the helpers",
}


def _first_party_modules():
    return first_party_sources()          # the root, and the moonglade/ code folder


def _rel(path):
    """A module's path from the repo root, as _FILE_ALLOWED names it ("moonglade/paths.py")."""
    return path.relative_to(_REPO).as_posix()


def _file_uses_in(text, filename="<src>"):
    """(line, source line) for every `__file__` the source reads, as a name or an attribute
    (`core.__file__`), and every `sys.argv[0]` (the running script's own path: the other
    way to find the app's folder)."""
    lines = text.splitlines()
    hits = []
    for node in ast.walk(ast.parse(text, filename=filename)):
        if (isinstance(node, ast.Name) and node.id == "__file__") or \
                (isinstance(node, ast.Attribute) and node.attr == "__file__") or \
                (isinstance(node, ast.Subscript) and ast.unparse(node.value) == "sys.argv"
                 and ast.unparse(node.slice) == "0"):
            hits.append((node.lineno, lines[node.lineno - 1].strip()))
    return hits


def _file_uses(path):
    return _file_uses_in(path.read_text(encoding="utf-8"), str(path))


def test_no_module_but_moonglade_paths_derives_an_app_root_path_from_its_file():
    modules = _first_party_modules()
    assert any(_rel(p) == "moonglade/gallery.py" for p in modules), "found no modules to check"
    stray = []
    for path in modules:
        if _rel(path) in _FILE_ALLOWED:
            continue
        stray += ["%s:%d  %s" % (path.name, n, line) for n, line in _file_uses(path)]
    assert not stray, ("derive app-root paths through moonglade_paths, not __file__:\n  "
                       + "\n  ".join(stray))


def test_the_launcher_finds_its_own_folder_once_and_byte_for_byte():
    """One read of its own file, by os.path.abspath (as in 3.18, never resolve()), and that
    folder is what goes on sys.path, what it changes into and the folder the server runs from
    (since 3.20 as `-m moonglade.gallery`, which finds the package through the working
    directory). tests/test_launcher_runs_the_package.py runs the launcher for the rest."""
    src = (_REPO / "Moonglade Launcher.pyw").read_text(encoding="utf-8")
    uses = _file_uses(_REPO / "Moonglade Launcher.pyw")
    assert [u[1] for u in uses] == ["here = os.path.dirname(os.path.abspath(__file__))"], uses
    assert "sys.path.insert(0, here)" in src
    assert "os.chdir(here)" in src
    assert 'cmd = [sys.executable, "-m", "moonglade.gallery"] + SERVE_ARGS' in src
    assert "cwd=here" in src


def test_the_lints_catch_the_other_spellings():
    """The cheap dodges: the script's own path through sys.argv[0], and getcwd imported by
    name. (Exotic ones -- getattr, importlib -- are not chased.)"""
    assert [n for n, _ in _file_uses_in("import sys\nhere = sys.argv[0]\n")] == [2]
    assert [n for n, _ in _file_uses_in("import sys\nx = sys.argv[1]\n")] == []
    src = "from os import getcwd\nfrom os import getcwd as g\nimport os\nx = os.getcwd()\n"
    assert [h.split()[0] for h in _cwd_reads_in(src, "m.py")] == ["m.py:1", "m.py:2", "m.py:4"]


def _cwd_reads_in(text, name):
    """`os.getcwd()` / `Path.cwd()` calls and `from os import getcwd`: the working
    directory, read directly."""
    lines = text.splitlines()
    hits = []
    for n in ast.walk(ast.parse(text, filename=name)):
        if (isinstance(n, ast.Call) and getattr(n.func, "attr", None) in ("getcwd", "cwd")) \
                or (isinstance(n, ast.ImportFrom) and n.module == "os"
                    and any(a.name in ("getcwd", "getcwdb") for a in n.names)):
            hits.append((n.lineno, "%s:%d  %s" % (name, n.lineno, lines[n.lineno - 1].strip())))
    return [h for _, h in sorted(hits)]


def _cwd_reads(path):
    return _cwd_reads_in(path.read_text(encoding="utf-8"), path.name)


def test_no_module_but_moonglade_paths_reads_the_working_directory():
    """The cwd-relative anchors name their dependence: paths.run_dir()."""
    stray = [h for p in _first_party_modules() if _rel(p) != "moonglade/paths.py"
             for h in _cwd_reads(p)]
    assert not stray, "ask moonglade_paths.run_dir():\n  " + "\n  ".join(stray)


# ---- Flask resolves a relative library against the app folder, not the module's ---------

def test_a_relative_library_serves_from_the_app_folder(tmp_path, monkeypatch):
    """send_from_directory() and send_file() join a RELATIVE path onto Flask's root_path,
    which defaults to the folder of the module that made the app. The default library
    (`pixai_backup`) is relative, so a thumbnail and a video must come from APP_ROOT/<library>
    -- not from wherever moonglade_gallery.py sits, which stops being the app folder when
    the code moves. Here the app folder is a tmp one and the module is not in it."""
    from moonglade.gallery import CATALOG_FIELDS, save_catalog
    from tests.conftest import login_client
    app_root = tmp_path / "app"
    lib = app_root / "lib"
    (lib / "gallery" / "thumbs").mkdir(parents=True)
    (lib / "videos").mkdir()
    (lib / "gallery" / "thumbs" / "m1.jpg").write_bytes(b"\xff\xd8\xff\xe0THUMB")
    (lib / "videos" / "clip_V1.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42CLIP")
    row = {f: "" for f in CATALOG_FIELDS}
    save_catalog(lib / "catalog.db", [
        row | {"media_id": "m1", "filename": "a_m1.png", "created_at": "2025-01-01T00:00:00"},
        row | {"media_id": "V1", "filename": "videos/clip_V1.mp4", "is_video": "1",
               "created_at": "2025-01-02T00:00:00"}])
    monkeypatch.setattr(paths, "APP_ROOT", app_root)
    monkeypatch.chdir(app_root)                   # as every entry point runs
    assert Path(g.__file__).resolve().parent != app_root
    cli = login_client(Path("lib"))
    thumb = cli.get("/thumbs/m1.jpg")
    assert thumb.status_code == 200 and thumb.data.endswith(b"THUMB")
    video = cli.get("/video-file/V1")
    assert video.status_code == 200 and video.data.endswith(b"CLIP")


def test_flask_root_path_is_the_app_folder():
    """Read off the source, for the same reason as the static folder above."""
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(g.create_app)))
    flask = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "Flask"]
    kw = {k.arg: ast.unparse(k.value) for k in flask[0].keywords}
    assert kw.get("root_path") == "str(_paths.APP_ROOT)"
