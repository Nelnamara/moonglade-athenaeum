"""config.json goes through ONE helper (Wave 4 groundwork, 3.19.0).

Every reader and writer asks core._config_path(), which is moonglade_paths.config_path(). Two
routes used to rebuild the path by hand from the backup module's own folder -- the Setup
Wizard's key save and the mirror toggle -- so a test that redirected only the helper could
still have them write the real file (it happened, 2026-08-02), and after the code moves into
a package folder they would have written a config.json nobody reads. mirror_session.json is a
machine file now: local_path(), no longer config.json's sibling by derivation. The Mirror
switch is an app-written setting: settings.json, never config.json.

Each test points the helper at one folder and the backup module's own folder at a DECOY, so
a writer that still derives the path by hand lands in the decoy and fails here.
"""
import ast
import json
from pathlib import Path

import pytest

from moonglade import backup as core
from moonglade import paths
from moonglade import settings as msettings
from tests.conftest import first_party_sources, login_client

_REPO = Path(__file__).resolve().parents[2]
_REAL_CORE_CONFIG_PATH = core._config_path
_REAL_PATHS_CONFIG_PATH = paths.config_path


@pytest.fixture
def routed(tmp_path, monkeypatch):
    """The helper answers tmp/routed/config.json; the module's own folder is tmp/decoy, which
    holds a config.json of its own that no writer may read or write."""
    routed, decoy = tmp_path / "routed", tmp_path / "decoy"
    routed.mkdir()
    decoy.mkdir()
    cfg = routed / "config.json"
    cfg.write_text(json.dumps({"USER_ID": "kept"}), encoding="utf-8")
    (decoy / "config.json").write_text(json.dumps({"DECOY": True}), encoding="utf-8")
    monkeypatch.setattr(core, "_config_path", lambda: cfg)
    monkeypatch.setattr(paths, "config_path", lambda: cfg)
    monkeypatch.setattr(core, "__file__", str(decoy / "moonglade" / "backup.py"))
    return cfg


def _decoy_untouched(cfg):
    decoy = cfg.parent.parent / "decoy" / "config.json"
    assert json.loads(decoy.read_text(encoding="utf-8")) == {"DECOY": True}


def test_the_setup_wizard_key_save_writes_through_the_helper(routed, tmp_path, monkeypatch):
    monkeypatch.setattr(core, "account_info",
                        lambda session, raise_on_error=False: {"quotaAmount": 7})
    cli = login_client(tmp_path)
    r = cli.post("/api/setup/save-key", data=json.dumps({"api_key": "sk-routed"}),
                 content_type="application/json")
    assert r.get_json() == {"ok": True, "credits": 7}
    cfg = json.loads(routed.read_text(encoding="utf-8"))
    assert cfg["PIXAI_API_KEY"] == "sk-routed"
    assert cfg["USER_ID"] == "kept" and cfg.get("AUTH_USERS"), "the rest of the file survives"
    _decoy_untouched(routed)


def test_the_mirror_toggle_writes_settings_json_never_config_json(routed, tmp_path,
                                                                   monkeypatch):
    """The switch is app-written, so it is settings.json's mirror_to_pixai; config.json (the
    hand-edited file with the auth block) is never rewritten by it."""
    monkeypatch.setattr(core, "_jwt_usable", lambda jwt: True)
    cli = login_client(tmp_path)
    before = routed.read_text(encoding="utf-8")
    d = cli.post("/api/mirror/enable", json={"enabled": True}).get_json()
    assert d == {"enabled": True}
    assert msettings.read()["mirror_to_pixai"] is True and core.mirror_enabled() is True
    assert routed.read_text(encoding="utf-8") == before
    assert "MIRROR_TO_PIXAI" not in json.loads(routed.read_text(encoding="utf-8"))
    _decoy_untouched(routed)


def test_the_backup_writer_lands_on_the_helper(routed):
    core._save_config({"USER_ID": "rewritten"})
    assert json.loads(routed.read_text(encoding="utf-8")) == {"USER_ID": "rewritten"}
    _decoy_untouched(routed)


def test_the_backup_reader_reads_through_the_helper(routed):
    assert core._load_config() == {"USER_ID": "kept"}


def test_core_config_path_is_the_paths_rule(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "_config_path", _REAL_CORE_CONFIG_PATH)
    monkeypatch.setattr(paths, "config_path", lambda: tmp_path / "x" / "config.json")
    assert core._config_path() == tmp_path / "x" / "config.json"


# ---- mirror_session.json is a machine file: local/ (3.20) --------------------------------

def test_mirror_session_is_a_machine_file(routed, tmp_path, monkeypatch):
    """It goes through local_path() like the other machine files, not config.json's folder."""
    monkeypatch.setattr(paths, "local_path", lambda name: tmp_path / "local" / name)
    assert core._mirror_state_path() == tmp_path / "local" / "mirror_session.json"


def test_the_move_brings_the_mirror_session_from_beside_config_json(tmp_path, monkeypatch):
    """Where 3.19 kept it -- beside wherever config_path() found config.json -- is where the
    move brings it from (here config.json's folder is made a separate one from local/)."""
    from moonglade import setup as msetup
    old, local = tmp_path / "old-app", tmp_path / "local"
    old.mkdir()
    (old / "mirror_session.json").write_text('{"jwt": "t"}', encoding="utf-8")
    monkeypatch.setattr(paths, "config_path", lambda: old / "config.json")
    monkeypatch.setattr(paths, "local_dir", lambda: local)
    monkeypatch.setattr(paths, "local_path", lambda name: local / name)
    msetup.prepare("cli", explicit_out=str(tmp_path / "no-library"))
    assert json.loads((local / "mirror_session.json").read_text(encoding="utf-8")) ==         {"jwt": "t"}
    assert not (old / "mirror_session.json").exists()


# ---- the lint: nobody spells config.json's path but the helper ----------------------------

def _hand_built_config_paths(path):
    """Lines that build a path ending in "config.json" by hand: `x / "config.json"` or
    `Path("config.json")`."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    hits = []
    for node in ast.walk(ast.parse(text, filename=str(path))):
        named = None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            named = node.right
        elif isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Path" \
                and node.args:
            named = node.args[-1]
        if isinstance(named, ast.Constant) and named.value == "config.json":
            hits.append("%s:%d  %s" % (path.name, node.lineno, lines[node.lineno - 1].strip()))
    return hits


def test_no_module_but_moonglade_paths_builds_the_config_json_path():
    modules = first_party_sources()       # the root, and the moonglade/ code folder
    assert any(p.relative_to(_REPO).as_posix() == "moonglade/gallery.py" for p in modules)
    stray = [h for p in modules if p.relative_to(_REPO).as_posix() != "moonglade/paths.py"
             for h in _hand_built_config_paths(p)]
    assert not stray, "ask core._config_path() for config.json:\n  " + "\n  ".join(stray)
