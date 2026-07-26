"""The library folder is settable again -- the capability that left with the desktop GUI.

Three pieces have to agree for this to work, and each one has its own way of silently
breaking the other two, so each is pinned here:

  * resolve_library_dir()'s ORDER: explicit --out, then config.json's LIBRARY_DIR, then the
    default. Explicit has to win so a one-off run, a scheduled job or a second install can
    point somewhere without touching (or being overridden by) the shared setting.
  * the launcher must NOT pass --out itself. It used to pass the literal default, which made
    the stored setting permanently unreachable no matter what was in it -- the setting would
    have looked saved and done nothing.
  * the route writes only after the folder is known good, and never moves anything.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pixai_gallery_backup as core  # noqa: E402
from pixai_gallery import (CATALOG_FIELDS, DEFAULT_LIBRARY_DIR, LIBRARY_DIR_KEY,  # noqa: E402
                           resolve_library_dir, save_catalog)

from tests.conftest import login_client  # noqa: E402


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _authed_client(tmp_path, rows):
    save_catalog(tmp_path / "catalog.db", rows)
    return login_client(tmp_path)

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_resolution_order_explicit_beats_stored_beats_default(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(core, "_config_path", lambda: cfg)

    cfg.write_text("{}", encoding="utf-8")
    assert resolve_library_dir(None) == DEFAULT_LIBRARY_DIR
    assert resolve_library_dir(r"D:\one-off") == r"D:\one-off"

    cfg.write_text(json.dumps({LIBRARY_DIR_KEY: r"D:\Moonglade Library"}), encoding="utf-8")
    assert resolve_library_dir(None) == r"D:\Moonglade Library"
    # An explicit flag must still win, or a scheduled job pointed elsewhere would be
    # silently redirected into the shared setting's folder.
    assert resolve_library_dir(r"E:\scratch") == r"E:\scratch"

    # A blank or whitespace value is not a setting -- it must fall through, not resolve to
    # the filesystem root or the current directory.
    cfg.write_text(json.dumps({LIBRARY_DIR_KEY: "   "}), encoding="utf-8")
    assert resolve_library_dir(None) == DEFAULT_LIBRARY_DIR


def test_a_broken_config_does_not_stop_the_server_starting(tmp_path, monkeypatch):
    """resolve_library_dir runs before anything else on startup. A corrupt config.json must
    fall back to the default rather than take the whole server down with it."""
    cfg = tmp_path / "config.json"
    cfg.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(core, "_config_path", lambda: cfg)
    assert resolve_library_dir(None) == DEFAULT_LIBRARY_DIR


def test_the_launcher_does_not_hardcode_the_folder():
    """It used to pass `--out pixai_backup` on every start. An always-present flag beats the
    stored setting by the resolution order above, so the Panel's field would have saved
    correctly and then changed nothing at all -- the worst kind of broken."""
    launcher = (ROOT / "Serve Gallery.pyw").read_text(encoding="utf-8")
    body = launcher[launcher.index("SERVE_ARGS ="):]
    body = body[:body.index("serve.txt")]
    assert "--out" not in body, "the launcher pins the folder and the setting cannot win"
    # serve.txt must still be able to override -- that is the documented machine-local escape
    # hatch, and an explicit --out there is a deliberate pin.
    assert "SERVE_ARGS +=" in launcher


def test_setting_the_folder_writes_it_and_creates_nothing_by_accident(tmp_path):
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="1", filename="a.png", created_at="2025-01-01T00:00:00")])
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a.png",
                                         created_at="2025-01-01T00:00:00")])
    target = tmp_path / "elsewhere"

    # A folder that does not exist is NOT created silently -- it asks first, because a typo
    # would otherwise quietly make an empty library and look like the real one vanished.
    d = cli.post("/api/library-path", json={"path": str(target)}).get_json()
    assert d.get("needs_create") is True and not target.exists()

    d = cli.post("/api/library-path", json={"path": str(target), "create": True}).get_json()
    assert d.get("ok") is True and target.is_dir()
    assert d["has_catalog"] is False, "a fresh folder has no catalog and must say so"

    stored = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert stored[LIBRARY_DIR_KEY] == str(target.resolve())


def test_a_file_is_refused_and_nothing_is_written(tmp_path):
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a.png",
                                         created_at="2025-01-01T00:00:00")])
    afile = tmp_path / "notafolder.txt"
    afile.write_text("x", encoding="utf-8")
    d = cli.post("/api/library-path", json={"path": str(afile)}).get_json()
    assert "folder" in (d.get("error") or "").lower()
    cfg = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert LIBRARY_DIR_KEY not in cfg, "a rejected path must not be written"

    d = cli.post("/api/library-path", json={"path": "   "}).get_json()
    assert d.get("error")


def test_the_folder_setting_never_offers_to_move_anything(tmp_path):
    """The one hard promise: changing this points the app somewhere else and leaves the old
    folder untouched. There is deliberately no migrate/copy option to get wrong, and the
    Panel says so in as many words."""
    cli = _authed_client(tmp_path, [_row(media_id="1", filename="a.png",
                                         created_at="2025-01-01T00:00:00")])
    html = cli.get("/panel").get_data(as_text=True)
    assert "nothing is moved" in html.lower()
    src = (ROOT / "pixai_gallery.py").read_text(encoding="utf-8")
    body = src[src.index("def api_library_path("):]
    body = body[:body.index("@app.route(\"/api/server/restart\"")]
    for danger in ("shutil.move", "shutil.copytree", "os.rename", "os.replace", ".unlink("):
        assert danger not in body, "the folder setting must never touch files: " + danger
