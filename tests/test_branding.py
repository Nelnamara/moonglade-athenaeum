"""Branding: the banner-mark + animation system and the launcher-shortcut writer.
All hermetic -- fake mark assets are written into tmp, subprocess is mocked, and
nothing touches a real Desktop or PowerShell."""
import json

import pixai_gallery as g
from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _app(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    return create_app(tmp_path)


def _cut_fake_marks(tmp_path, ids=("mark_4", "mark_12"), ico=True):
    mdir = tmp_path / "branding" / "marks"
    mdir.mkdir(parents=True)
    for i in ids:
        (mdir / (i + ".png")).write_bytes(b"\x89PNG fake")
        if ico:
            (mdir / (i + ".ico")).write_bytes(b"\x00\x00icofake")
    (mdir / "marks.json").write_text(json.dumps(
        {"marks": [{"id": i, "label": i.replace("_", " "), "kind": "tile"}
                   for i in ids]}), encoding="utf-8")


def test_branding_defaults_when_no_assets(tmp_path):
    cli = _app(tmp_path).test_client()
    d = cli.get("/api/branding").get_json()
    assert d["anim"] == "classic" and d["marks"] == []
    assert d["mark"] == "logo"            # legacy drop-in logo.png fallback
    assert "eclipse" in d["anims"] and "classic" in d["anims"]
    # the header renders the legacy logo + classic animation class
    html = cli.get("/").get_data(as_text=True)
    assert "anim-classic" in html and "/branding/logo.png" in html


def test_branding_save_and_render(tmp_path):
    _cut_fake_marks(tmp_path)
    cli = _app(tmp_path).test_client()
    d = cli.get("/api/branding").get_json()
    assert {m["id"] for m in d["marks"]} == {"mark_4", "mark_12"}
    assert d["mark"] == "mark_4"          # default mark once assets exist
    r = cli.post("/api/branding", json={"mark": "mark_12", "anim": "eclipse"})
    assert r.get_json() == {"mark": "mark_12", "anim": "eclipse"}
    assert json.loads((tmp_path / "branding.json").read_text())["anim"] == "eclipse"
    html = cli.get("/").get_data(as_text=True)
    assert "anim-eclipse" in html and "/branding/marks/mark_12.png" in html
    assert "mk-tile" in html              # tile marks get the rounded-corner class


def test_branding_validation_and_lan_gate(tmp_path):
    _cut_fake_marks(tmp_path)
    cli = _app(tmp_path).test_client()
    assert cli.post("/api/branding", json={"anim": "sparklebomb"}).status_code == 400
    assert cli.post("/api/branding", json={"mark": "mark_99"}).status_code == 400
    r = cli.post("/api/branding", json={"anim": "glow"},
                 environ_overrides={"REMOTE_ADDR": "192.168.1.9"})
    assert r.status_code == 403           # LAN can't restyle the owner's gallery


def test_shortcut_writes_lnk_via_powershell(tmp_path, monkeypatch):
    import subprocess
    _cut_fake_marks(tmp_path)
    captured = {}

    class R:
        returncode = 0
        stderr = ""
        stdout = ""
    def fake_run(argv, **k):
        captured["argv"] = argv
        return R()
    monkeypatch.setattr(subprocess, "run", fake_run)
    cli = _app(tmp_path).test_client()
    d = cli.post("/api/branding/shortcut", json={"mark": "mark_4"}).get_json()
    assert d.get("ok") is True and d["lnk"].endswith("Moonglade Athenaeum.lnk")
    argv = captured["argv"]
    assert argv[0] == "powershell"
    assert "CreateShortcut" in argv[-1] and "mark_4.ico" in argv[-1]
    assert "Serve Gallery.pyw" in argv[-1]
    # LAN can't write shortcuts onto the owner's Desktop
    r = cli.post("/api/branding/shortcut", json={"mark": "mark_4"},
                 environ_overrides={"REMOTE_ADDR": "192.168.1.9"})
    assert r.status_code == 403


def test_shortcut_requires_cut_ico(tmp_path, monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise AssertionError("PowerShell must not run without an .ico")
    monkeypatch.setattr(subprocess, "run", boom)
    cli = _app(tmp_path).test_client()      # no marks cut at all
    r = cli.post("/api/branding/shortcut", json={"mark": "mark_4"})
    assert r.status_code == 400 and "ico" in r.get_json()["error"].lower()
