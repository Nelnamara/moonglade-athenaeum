"""Branding: the banner-mark + animation system and the launcher-shortcut writer.
All hermetic -- fake mark assets are written into tmp, subprocess is mocked, and
nothing touches a real Desktop or PowerShell."""
import json
import pathlib
import re

import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_test_client

# Captured at IMPORT time -- collection runs before any autouse fixture, so this is the genuine
# resolver rather than the tmp_path-redirected one conftest._isolated_branding installs. Needed
# because that fixture is what lets every other test in this file keep its old semantics, and it
# would otherwise hide the production behaviour completely.
_REAL_BRANDING_ROOT = g.branding_root


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
    html = cli.get("/classic").get_data(as_text=True)
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
    html = cli.get("/classic").get_data(as_text=True)
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
    import moonglade_backup as core
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
    assert cli.get("/classic").status_code == 200
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
    assert 'class="bannered"' not in cli.get("/classic").get_data(as_text=True)
    bdir = tmp_path / "branding"
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "banner.png").write_bytes(b"\x89PNG fake")
    assert 'class="bannered"' in cli.get("/classic").get_data(as_text=True)


def test_shortcut_requires_cut_ico(tmp_path, monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise AssertionError("PowerShell must not run without an .ico")
    monkeypatch.setattr(subprocess, "run", boom)
    cli = _client(tmp_path)      # no marks cut at all
    r = cli.post("/api/branding/shortcut", json={"mark": "mark_4"})
    assert r.status_code == 400 and "ico" in r.get_json()["error"].lower()


def test_branding_root_is_the_app_folder_not_the_library(tmp_path):
    """Branding resolves from the APP directory, and is unaffected by the library folder.

    This is the regression that prompted the move. It used to be `out_dir / "branding"`, and
    out_dir comes from resolve_library_dir() -- so once the library folder became a setting
    (2026-07-25), pointing the app at a different library made every mark, mascot and banner
    disappear from its view. The files stayed on disk in the old library; the app simply stopped
    looking. Nobody hit it because only one library has ever existed, which is exactly why it
    needs a test rather than a memory.

    Deliberately calls the CAPTURED resolver: conftest redirects the module attribute to tmp_path
    for every other test, so asserting through the module here would only re-test the fixture."""
    root = _REAL_BRANDING_ROOT()
    app_dir = pathlib.Path(g.__file__).resolve().parent

    assert root == app_dir / "branding"
    # The point of the move: it does NOT live under any library, including this test's.
    assert tmp_path not in root.parents and root != tmp_path / "branding"
    # It takes no arguments at all, so there is no library value that could steer it.
    assert _REAL_BRANDING_ROOT.__code__.co_argcount == 0


def test_branding_json_sits_beside_the_art_directory():
    """branding.json is a SIBLING of branding/, preserving the arrangement it had inside the
    library. Someone moving an existing setup keeps both entries in the same relationship, and
    .gitignore covers the pair. Guards the `.parent` derivation in _branding_path() -- if that
    ever changes to nest the file inside branding/, an existing install's selections go missing
    silently and the app just renders defaults.

    Asserts the RELATIONSHIP rather than an absolute path, resolving both sides through the module
    so it holds wherever branding_root() points -- the app root in production, tmp_path under
    conftest's fixture. test_branding_root_is_the_app_folder_not_the_library above is what pins
    the absolute location; mixing the two concerns here just re-tested the fixture."""
    cfg = g._branding_path(pathlib.Path("/some/unrelated/library"))

    assert cfg == g.branding_root().parent / "branding.json"
    assert cfg.parent == g.branding_root().parent      # siblings, not nested
    assert "library" not in str(cfg)                   # the argument is genuinely ignored


def test_login_mascot_takes_webp_or_png_like_the_achievement_mascots(tmp_path):
    """The per-achievement mascots have had an animated-or-still contract since 2026-07-12:
    `ach/<id>.webp` -> `ach/<id>.png` -> `present_<tier>.png`. That is why dropping
    `first-light.webp` in beside the stills simply animated that one achievement.

    The login screen was built later and never carried that context: it hardcoded ONE path
    with ONE fallback (`mascots/login_nel.png`), so the owner's real art -- `login_nel.webp`
    at the branding ROOT -- rendered nothing at all, being in the wrong folder AND the wrong
    format. Owner: "It was my understanding we wired things so I could use webp animated and
    png for the mascots... but the login screen was made later and likely did not carry that
    context."

    Pins the whole ladder so a later edit cannot quietly collapse it back to one path.
    """
    html = _app(tmp_path).test_client().get("/login").get_data(as_text=True)
    assert "/branding/login_nel.webp" in html, "webp must be tried FIRST -- animated wins"
    for later in ("/branding/login_nel.png",
                  "/branding/mascots/login_nel.webp",
                  "/branding/mascots/login_nel.png",
                  "/branding/mascots/gen_nel.png"):
        assert later in html, later + " is missing from the fallback ladder"
    # It must still END by removing the element: a broken-image icon would keep the
    # :has(img) rule from restoring the mock's sparkle placeholder on a bare install.
    assert "this.remove()" in html
