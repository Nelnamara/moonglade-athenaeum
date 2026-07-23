"""Branding: the banner-mark + animation system and the launcher-shortcut writer.
All hermetic -- fake mark assets are written into tmp, subprocess is mocked, and
nothing touches a real Desktop or PowerShell."""
import json
import re

import pixai_gallery as g
from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_test_client


def _csrf(html):
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "login page did not render a csrf hidden field"
    return m.group(1)


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _app(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    return create_app(tmp_path)


def _client(tmp_path):
    """Authenticated version of _app() -- for the plain functionality tests below that
    don't care about the auth boundary itself (see test_shortcut_refuses_authenticated_lan_session
    for the one that deliberately hand-rolls its own login instead of using this, and needs
    _app()'s bare, unauthenticated app to start from)."""
    return login_test_client(_app(tmp_path))


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
    cli = _client(tmp_path)
    d = cli.get("/api/branding").get_json()
    assert d["anim"] == "classic" and d["marks"] == []
    assert d["mark"] == "logo"            # legacy drop-in logo.png fallback
    assert "eclipse" in d["anims"] and "classic" in d["anims"]
    # the header renders the legacy logo + classic animation class
    html = cli.get("/").get_data(as_text=True)
    assert "anim-classic" in html and "/branding/logo.png" in html


def test_branding_save_and_render(tmp_path):
    _cut_fake_marks(tmp_path)
    cli = _client(tmp_path)
    d = cli.get("/api/branding").get_json()
    assert {m["id"] for m in d["marks"]} == {"mark_4", "mark_12"}
    assert d["mark"] == "mark_4"          # default mark once assets exist
    r = cli.post("/api/branding", json={"mark": "mark_12", "anim": "eclipse"})
    assert r.get_json() == {"mark": "mark_12", "anim": "eclipse"}
    assert json.loads((tmp_path / "branding.json").read_text())["anim"] == "eclipse"
    html = cli.get("/").get_data(as_text=True)
    # The rendered mark span's OWN class attribute, not a bare substring -- BASE_HTML's
    # shared stylesheet permanently contains ".mark:not(.anim-classic)..." and every
    # anim-*/mk-tile class name as CSS selector text on every page, so a bare "anim-eclipse
    # in html" / "mk-tile in html" check passed even on a default, unbranded page.
    assert 'class="mark anim-eclipse mk-tile"' in html
    assert "/branding/marks/mark_12.png" in html


def test_branding_validation_and_lan_gate(tmp_path):
    """The 401/400s here are ordinary input validation, not an auth boundary -- the LAN
    call below is a logged-in session (via _client()), which api_branding()'s own
    docstring says IS trusted the same as the owner for this route (unlike
    /api/branding/shortcut, which adds its own extra _is_local_request() check).
    An anonymous LAN request being refused is covered separately by
    tests/test_web_auth.py; this test is about validation, not the gate."""
    _cut_fake_marks(tmp_path)
    cli = _client(tmp_path)
    assert cli.post("/api/branding", json={"anim": "sparklebomb"}).status_code == 400
    assert cli.post("/api/branding", json={"mark": "mark_99"}).status_code == 400
    r = cli.post("/api/branding", json={"anim": "glow"},
                 environ_overrides={"REMOTE_ADDR": "192.168.1.9"})
    assert r.status_code == 200           # a logged-in LAN session is trusted like the owner here


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
    cli = _client(tmp_path)
    d = cli.post("/api/branding/shortcut", json={"mark": "mark_4"}).get_json()
    assert d.get("ok") is True and d["lnk"].endswith("Moonglade Athenaeum.lnk")
    argv = captured["argv"]
    assert argv[0] == "powershell"
    assert "CreateShortcut" in argv[-1] and "mark_4.ico" in argv[-1]
    assert "Serve Gallery.pyw" in argv[-1]
    # LAN can't write shortcuts onto the owner's Desktop even for THIS already-logged-in
    # session -- it passes the global front door (real session) but is then refused by
    # the route's OWN, stricter _is_local_request() re-check (403), same property
    # test_shortcut_refuses_authenticated_lan_session below exercises end-to-end.
    r = cli.post("/api/branding/shortcut", json={"mark": "mark_4"},
                 environ_overrides={"REMOTE_ADDR": "192.168.1.9"})
    assert r.status_code == 403


def test_shortcut_refuses_authenticated_lan_session(tmp_path, monkeypatch):
    """A logged-in LAN account must NOT be able to trigger the Desktop-shortcut
    writer -- unlike ordinary app-data writes (POST /api/branding above), this
    shells out to PowerShell/WScript.Shell COM on the SERVER's own machine
    (make_launcher_shortcut's docstring: "caller must gate to localhost"). A
    LAN login is meant to unlock spend-the-owner's-credits generation features,
    not host-machine execution -- a materially different trust boundary.
    Regression test: the LAN-auth conversion pass had broadened this route's
    gate from _is_local_request() to the wider _is_authorized_request(),
    flagged and reverted 2026-07-19."""
    import subprocess
    import pixai_gallery_backup as core
    _cut_fake_marks(tmp_path)

    class R:
        returncode = 0
        stderr = ""
        stdout = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    core.add_or_update_web_user("alice", "hunter2")
    cli = _app(tmp_path).test_client()
    LAN = "203.0.113.5"
    html = cli.get("/login").get_data(as_text=True)
    cli.post("/login", data={"username": "alice", "password": "hunter2", "csrf": _csrf(html)})
    # Prove the session really is authenticated (it can reach an ordinary
    # authorized-LAN route) before proving it still can't reach this one.
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200
    r = cli.post("/api/branding/shortcut", json={"mark": "mark_4"},
                 environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 403


def test_branding_survives_corrupt_manifests(tmp_path):
    """A hand-edited/corrupt marks.json or branding.json must degrade to the
    logo.png defaults -- never 500 every page via the context processor."""
    mdir = tmp_path / "branding" / "marks"
    mdir.mkdir(parents=True)
    (mdir / "marks.json").write_text('{"marks": ["not-a-dict", 42]}', encoding="utf-8")
    (tmp_path / "branding.json").write_text('["not", "an", "object"]', encoding="utf-8")
    cli = _client(tmp_path)
    assert cli.get("/").status_code == 200
    d = cli.get("/api/branding").get_json()
    assert d["marks"] == [] and d["mark"] == "logo" and d["anim"] == "classic"


def test_subpage_headers_carry_anim_class(tmp_path):
    """Health/Panel headers must render the same anim-* class as the gallery, so
    the classic animation isn't muted there and a chosen anim applies everywhere."""
    cli = _client(tmp_path)
    for path in ("/health", "/panel"):
        html = cli.get(path).get_data(as_text=True)
        # The rendered mark span's own class, not a bare substring -- the shared
        # stylesheet's ".mark:not(.anim-classic)" selector puts "anim-classic" on
        # every page regardless of what the header's actual mark element carries.
        assert 'class="mark anim-classic"' in html, path


def test_banner_band_class(tmp_path):
    """With no branding/banner.png the header is the classic slim bar; once the
    file exists the header renders class="bannered" (the visible banner band)."""
    cli = _client(tmp_path)
    assert 'class="bannered"' not in cli.get("/").get_data(as_text=True)
    bdir = tmp_path / "branding"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "banner.png").write_bytes(b"\x89PNG fake")
    assert 'class="bannered"' in cli.get("/").get_data(as_text=True)


def test_shortcut_requires_cut_ico(tmp_path, monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise AssertionError("PowerShell must not run without an .ico")
    monkeypatch.setattr(subprocess, "run", boom)
    cli = _client(tmp_path)      # no marks cut at all
    r = cli.post("/api/branding/shortcut", json={"mark": "mark_4"})
    assert r.status_code == 400 and "ico" in r.get_json()["error"].lower()
