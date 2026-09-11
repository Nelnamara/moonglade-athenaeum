"""Branding: the banner-mark + animation system and the launcher-shortcut writer.
All hermetic -- fake mark assets are written into tmp, subprocess is mocked, and
nothing touches a real Desktop or PowerShell."""
import json
import pathlib

import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_existing_client, login_test_client

# Captured at IMPORT time -- collection runs before any autouse fixture, so this is the genuine
# resolver rather than the tmp_path-redirected one conftest._isolated_branding installs. Needed
# because that fixture is what lets every other test in this file keep its old semantics, and it
# would otherwise hide the production behaviour completely.
_REAL_BRANDING_ROOT = g.branding_root


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _app(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    return create_app(tmp_path)


def _client(tmp_path):
    """Authenticated version of _app() -- for the plain functionality tests below that
    don't care about the auth boundary itself (see test_shortcut_refuses_authenticated_lan_session
    for the one that deliberately logs in its own separate account instead of using this, and
    needs _app()'s bare, unauthenticated app to start from)."""
    return login_test_client(_app(tmp_path))


def _cut_fake_marks(tmp_path, ids=("mark_4", "mark_7"), ico=True):
    # Seeds land in the CODED marks dir (bundle-v2 rewire): on-disk paths come
    # from the ROLE_CODE map via g._role_dir, never a retyped hex literal --
    # retyping the codes in tests would recreate the exact scatter the map
    # removed. (branding_root() is tmp_path/branding under conftest's
    # _isolated_branding, so this stays fully hermetic.)
    mdir = g._role_dir("marks")
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
    # (the classic header render of the legacy logo died with BASE_HTML/INDEX_HTML
    # in the 2026-08-08 classic cut; the React gallery reads /api/branding, whose
    # defaults are what the assertions above pin)


def test_branding_save_and_render(tmp_path):
    _cut_fake_marks(tmp_path)
    cli = _client(tmp_path)
    d = cli.get("/api/branding").get_json()
    assert {m["id"] for m in d["marks"]} == {"mark_4", "mark_7"}
    assert d["mark"] == "mark_4"          # default mark once assets exist
    r = cli.post("/api/branding", json={"mark": "mark_7", "anim": "eclipse"})
    # The echo carries the animation TUNING alongside the pick since the 2026-08-31
    # marks build (speed/scale/glow), so this asserts the two fields it is about
    # rather than the whole payload -- the tuning's own round-trip is pinned in
    # tests/test_marks_build.py.
    saved = r.get_json()
    assert (saved["mark"], saved["anim"]) == ("mark_7", "eclipse")
    assert json.loads((tmp_path / "branding.json").read_text())["anim"] == "eclipse"
    # the saved choice reads back through the same API the React header consumes
    # (the classic BASE_HTML mark-span render died in the 2026-08-08 classic cut)
    d = cli.get("/api/branding").get_json()
    assert d["mark"] == "mark_7" and d["anim"] == "eclipse"


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
    _cut_fake_marks(tmp_path)

    class R:
        returncode = 0
        stderr = ""
        stdout = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: R())
    cli = _app(tmp_path).test_client()
    LAN = "203.0.113.5"
    # a real account, logged in the one way that exists since the classic cut
    # (GET /login for the MG_BOOT csrf, then POST /api/login)
    login_existing_client(cli, "alice", "hunter2")
    # Prove the session really is authenticated (it can reach an ordinary
    # authorized-LAN route) before proving it still can't reach this one.
    assert cli.get("/api/jobs", environ_overrides={"REMOTE_ADDR": LAN}).status_code == 200
    r = cli.post("/api/branding/shortcut", json={"mark": "mark_4"},
                 environ_overrides={"REMOTE_ADDR": LAN})
    assert r.status_code == 403


def test_branding_survives_corrupt_manifests(tmp_path):
    """A hand-edited/corrupt marks.json or branding.json must degrade to the
    logo.png defaults -- never 500 every page via the context processor
    (_inject_branding still runs brand_context() on every rendered template;
    the React shell at / is the surviving page that proves it)."""
    mdir = g._role_dir("marks")
    mdir.mkdir(parents=True)
    (mdir / "marks.json").write_text('{"marks": ["not-a-dict", 42]}', encoding="utf-8")
    (tmp_path / "branding.json").write_text('["not", "an", "object"]', encoding="utf-8")
    cli = _client(tmp_path)
    assert cli.get("/").status_code == 200
    d = cli.get("/api/branding").get_json()
    assert d["marks"] == [] and d["mark"] == "logo" and d["anim"] == "classic"


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

    Since the bundle-v2 rewire the folder itself carries the coded goods name
    (g._GOODS_ROOT_NAME, asserted through the module so the test can never
    drift from the map) -- but the LOCATION contract this test pins is
    unchanged: the app dir, never the library.

    Deliberately calls the CAPTURED resolver: conftest redirects the module attribute to tmp_path
    for every other test, so asserting through the module here would only re-test the fixture."""
    root = _REAL_BRANDING_ROOT()
    app_dir = pathlib.Path(g.__file__).resolve().parent

    assert root == app_dir / g._GOODS_ROOT_NAME
    # The point of the move: it does NOT live under any library, including this test's.
    assert tmp_path not in root.parents and root != tmp_path / g._GOODS_ROOT_NAME
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


def _png_bytes(color=(200, 30, 30)):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, format="PNG")
    return buf.getvalue()


def io_bytes(b):
    import io
    return io.BytesIO(b)


def test_branding_slots_empty_on_fresh_install(tmp_path):
    """The Branding slots are the three banners ONLY (the 2026-08-13
    unlock-split enforcement -- mascots/rewards are achievement-adjacent and
    not slots; see tests/test_unlock_split.py for that boundary)."""
    cli = _client(tmp_path)
    d = cli.get("/api/branding").get_json()
    assert set(d["slots"].keys()) == {"banner_main", "banner_login", "banner_loom"}
    for slot in d["slots"].values():
        assert slot == {"assets": [], "active": None}


def test_branding_slot_upload_becomes_active(tmp_path):
    cli = _client(tmp_path)
    r = cli.post("/api/branding/slot", data={"slot": "banner_main",
                 "file": (io_bytes(_png_bytes()), "banner.jpg")},
                 content_type="multipart/form-data")
    d = r.get_json()
    assert r.status_code == 200
    item = d["item"]
    # uploads start at the neutral transform (the DC's own slider defaults)
    assert (item["zoom"], item["cropX"], item["cropY"]) == (100, 50, 50)
    # the PUBLIC URL keeps the role vocabulary (bundle-v2: the /branding/ route
    # translates to the coded tree internally, the browser never sees a code)
    assert item["png"] == "/branding/banner_main/%s.png" % item["id"]
    assert d["assets"] == [item]
    # really on disk as a real PNG, re-encoded through Pillow regardless of the
    # upload's own (wrong) extension/content-type -- stored in the CODED slot dir
    from PIL import Image
    png_path = g._role_dir("banner_main") / (item["id"] + ".png")
    assert png_path.exists()
    with Image.open(png_path) as im:
        assert im.format == "PNG"
    slots = cli.get("/api/branding").get_json()["slots"]
    assert slots["banner_main"] == {"assets": [item], "active": item["id"]}


def test_branding_slot_second_upload_stays_available_and_becomes_active(tmp_path):
    """Uploading a second asset into the same slot does NOT delete the first --
    both exist, matching list_marks()'s own "many stored" shape, so a later
    rotating-source pass has more than one real candidate to pick from."""
    cli = _client(tmp_path)
    first = cli.post("/api/branding/slot", data={"slot": "banner_loom",
                     "file": (io_bytes(_png_bytes((10, 10, 10))), "a.png")},
                     content_type="multipart/form-data").get_json()["item"]
    second = cli.post("/api/branding/slot", data={"slot": "banner_loom",
                      "file": (io_bytes(_png_bytes((20, 20, 20))), "b.png")},
                      content_type="multipart/form-data").get_json()["item"]
    slot = cli.get("/api/branding").get_json()["slots"]["banner_loom"]
    assert {a["id"] for a in slot["assets"]} == {first["id"], second["id"]}
    assert slot["active"] == second["id"]       # the most recent upload wins


def test_branding_slot_upload_rejects_unknown_slot_and_bad_image(tmp_path):
    cli = _client(tmp_path)
    r = cli.post("/api/branding/slot", data={"slot": "not-a-real-slot",
                 "file": (io_bytes(_png_bytes()), "x.png")},
                 content_type="multipart/form-data")
    assert r.status_code == 400
    r = cli.post("/api/branding/slot", data={"slot": "banner_main",
                 "file": (io_bytes(b"not an image"), "x.png")},
                 content_type="multipart/form-data")
    assert r.status_code == 400 and "image" in r.get_json()["error"].lower()
    r = cli.post("/api/branding/slot", data={"slot": "banner_main"},
                 content_type="multipart/form-data")
    assert r.status_code == 400


def test_branding_slot_crop_and_active_endpoints(tmp_path):
    cli = _client(tmp_path)
    first = cli.post("/api/branding/slot", data={"slot": "banner_login",
                     "file": (io_bytes(_png_bytes()), "x.png")},
                     content_type="multipart/form-data").get_json()["item"]
    second = cli.post("/api/branding/slot", data={"slot": "banner_login",
                      "file": (io_bytes(_png_bytes((1, 2, 3))), "y.png")},
                      content_type="multipart/form-data").get_json()["item"]
    # the second upload auto-became active -- prove /active can select back to the first
    assert cli.get("/api/branding").get_json()["slots"]["banner_login"]["active"] == second["id"]

    # the three-slider transform (Control Panel.dc.html:326-339) is the primary surface
    r = cli.post("/api/branding/slot/crop",
                 json={"slot": "banner_login", "id": first["id"], "zoom": 180, "cropX": 25, "cropY": 70})
    assert r.status_code == 200
    a = next(a for a in r.get_json()["assets"] if a["id"] == first["id"])
    assert (a["zoom"], a["cropX"], a["cropY"]) == (180, 25, 70)
    # partial update keeps the untouched fields
    r = cli.post("/api/branding/slot/crop", json={"slot": "banner_login", "id": first["id"], "cropX": 90})
    a = next(a for a in r.get_json()["assets"] if a["id"] == first["id"])
    assert (a["zoom"], a["cropX"], a["cropY"]) == (180, 90, 70)
    # out-of-range values clamp to the sliders' own bounds, never error
    r = cli.post("/api/branding/slot/crop",
                 json={"slot": "banner_login", "id": first["id"], "zoom": 900, "cropX": -5, "cropY": 400})
    a = next(a for a in r.get_json()["assets"] if a["id"] == first["id"])
    assert (a["zoom"], a["cropX"], a["cropY"]) == (250, 0, 100)
    # legacy left/center/right still accepted (pre-2026-08-06 callers) -> a cropX pan
    r = cli.post("/api/branding/slot/crop", json={"slot": "banner_login", "id": first["id"], "crop": "right"})
    a = next(a for a in r.get_json()["assets"] if a["id"] == first["id"])
    assert a["cropX"] == 100
    assert cli.post("/api/branding/slot/crop", json={"slot": "banner_login", "id": first["id"], "crop": "diagonal"}).status_code == 400
    assert cli.post("/api/branding/slot/crop", json={"slot": "banner_login", "id": "nope", "crop": "left"}).status_code == 400

    assert cli.post("/api/branding/slot/active", json={"slot": "banner_login", "id": "nope"}).status_code == 400
    assert cli.post("/api/branding/slot/active", json={"slot": "banner_login", "id": None}).status_code == 400
    r = cli.post("/api/branding/slot/active", json={"slot": "banner_login", "id": first["id"]})
    assert r.get_json()["slots"]["banner_login"]["active"] == first["id"]


def test_branding_slots_survive_corrupt_manifest(tmp_path):
    """A hand-edited/corrupt <slot>/manifest.json or branding_slots.json must
    degrade to empty/None, never a 500 -- the same contract
    test_branding_survives_corrupt_manifests already pins for marks.json."""
    sdir = g._role_dir("banner_main")
    sdir.mkdir(parents=True)
    (sdir / "manifest.json").write_text('{"items": ["not-a-dict", 42]}', encoding="utf-8")
    (tmp_path / "branding_slots.json").write_text('["not", "an", "object"]', encoding="utf-8")
    cli = _client(tmp_path)
    d = cli.get("/api/branding").get_json()
    assert d["slots"]["banner_main"] == {"assets": [], "active": None}


# ---------------------------------------------------------------------------
# "Under the Hood" real trigger (docs/DECISIONS.md "Under the Hood intended
# flow", 2026-07-26, owner-confirmed 2026-08-05): a raw file dropped by hand
# into an empty branding/<slot>/ folder gets adopted automatically, and THAT
# is what fires the achievement -- not the authenticated upload API above,
# which sits behind the very unlock this earns.
# ---------------------------------------------------------------------------

def test_discovery_tree_creates_empty_slot_folders_and_one_readme(tmp_path, monkeypatch):
    cli = _client(tmp_path)          # create_app() calls ensure_branding_discovery_tree()
    # The scaffold is the CODED tree now (bundle-v2): the same six discovery
    # roles as before, their folders derived from the ROLE_CODE map -- a
    # tinkerer finds codes on disk, never role names.
    for slot in ("banner_main", "banner_login", "banner_loom",
                 "mascots", "rewards", "marks"):
        d = g._role_dir(slot)
        assert d.is_dir()
        assert list(d.iterdir()) == []   # empty -- nothing to find yet
    # The one breadcrumb now lives at the GONK spot inside the coded tree...
    crumb = tmp_path / "branding" / g._role_rel("breadcrumb", "README.txt")
    assert crumb.is_file()
    # ...and the old root-level README is NO LONGER written.
    assert not (tmp_path / "branding" / "README.txt").exists()
    # Container-less install: the breadcrumb text degrades to the public
    # one-liner (the real cryptic content is a sealed asset -- spoiler hygiene
    # keeps it out of source, so the fallback is the only text pin possible).
    monkeypatch.setattr(g, "branding_root", lambda: tmp_path / "fresh" / "branding")
    g.ensure_branding_discovery_tree()
    crumb2 = tmp_path / "fresh" / "branding" / g._role_rel("breadcrumb", "README.txt")
    assert crumb2.read_text(encoding="utf-8") == g._BRANDING_README


def test_discovery_tree_never_overwrites_real_content(tmp_path):
    """Idempotent: a real install's existing README/art must survive every
    server start, not just the first one."""
    mdir = g._role_dir("marks")
    mdir.mkdir(parents=True)
    crumb = tmp_path / "branding" / g._role_rel("breadcrumb", "README.txt")
    crumb.parent.mkdir(parents=True)
    crumb.write_text("owner's own note", encoding="utf-8")
    (mdir / "mark_4.png").write_bytes(_png_bytes())
    g.ensure_branding_discovery_tree()
    assert crumb.read_text(encoding="utf-8") == "owner's own note"
    assert (mdir / "mark_4.png").exists()


def test_dropped_file_in_a_new_slot_is_adopted_and_earns_the_achievement(tmp_path, sealed_donor_present):
    cli = _client(tmp_path)
    # The drop lands in the CODED slot folder -- that's the tree a tinkerer
    # actually finds on disk now, and the tree the sweep scans.
    (g._role_dir("banner_login") / "my_art.png").write_bytes(_png_bytes())

    d = cli.get("/api/achievements").get_json()
    uth = next(a for a in d["achievements"] if a["id"] == "under-the-hood")
    assert uth["earned"] is True

    slot = cli.get("/api/branding").get_json()["slots"]["banner_login"]
    assert len(slot["assets"]) == 1
    assert slot["active"] == slot["assets"][0]["id"]
    # the raw drop is consumed, not left sitting alongside the adopted copy
    assert not (g._role_dir("banner_login") / "my_art.png").exists()
    assert (g._role_dir("banner_login") / (slot["assets"][0]["id"] + ".png")).exists()


def test_dropped_jpeg_is_re_encoded_to_real_png(tmp_path):
    """The design says PNG/JPEG explicitly -- a raw .jpg drop must adopt too,
    not just .png, the same as a real photo someone actually has lying around."""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (5, 5, 5)).save(buf, format="JPEG")
    cli = _client(tmp_path)
    (g._role_dir("banner_main") / "photo.jpg").write_bytes(buf.getvalue())
    d = cli.get("/api/branding").get_json()["slots"]["banner_main"]
    assert len(d["assets"]) == 1
    with Image.open(g._role_dir("banner_main") / (d["assets"][0]["id"] + ".png")) as im:
        assert im.format == "PNG"


# ---------------------------------------------------------------------------
# Regression guard for a real near-miss (2026-08-05): mascots/ and rewards/
# already hold a family of specifically-named, role-bound files real shipped
# code reads by exact filename (narrator/login/power-modal mascots, the claim
# icon). The FIRST version of the sweep had no awareness of that and would
# have adopted-then-DELETED every one of them on any install that actually
# has them. Caught before it ever ran against real assets -- this pins it so
# it can't come back quietly.
#
# 2026-09-10 (owner ruling): the never-TOUCHED half is what this guards, and it
# is unchanged. What flipped is the flag -- mascots/rewards are now READ for
# detection, so a drop there earns the feat while the file stays exactly as it
# was. See tests/test_branding_tree_rules.py for the detection half in full.
# ---------------------------------------------------------------------------

def test_sweep_never_touches_mascots_or_rewards(tmp_path):
    cli = _client(tmp_path)
    # The real role-bound files live in the CODED mascots/rewards dirs now --
    # the never-swept property has to hold exactly where the sweep would look.
    real_mascot = g._role_dir("mascots") / "gen_nel.png"
    real_reward = g._role_dir("rewards") / "claim.png"
    real_mascot.write_bytes(_png_bytes())
    real_reward.write_bytes(_png_bytes())
    before = (real_mascot.read_bytes(), real_reward.read_bytes())

    for _ in range(3):
        cli.get("/api/achievements")
        cli.get("/api/branding")
        cli.get("/api/panel/summary")

    # untouched: still sitting under their OWN real names, same bytes --
    # not adopted, not renamed, not re-encoded
    assert real_mascot.exists() and real_reward.exists()
    assert (real_mascot.read_bytes(), real_reward.read_bytes()) == before
    # and since the 2026-08-13 unlock-split enforcement they aren't slots at
    # all -- the payload doesn't even list them
    slots = cli.get("/api/branding").get_json()["slots"]
    assert "mascots" not in slots and "rewards" not in slots
    # ...and nothing was adopted INTO them either: the folders hold exactly the
    # two files the test put there, with no manifest.json alongside.
    assert sorted(p.name for p in g._role_dir("mascots").iterdir()) == ["gen_nel.png"]
    assert sorted(p.name for p in g._role_dir("rewards").iterdir()) == ["claim.png"]


def test_dropped_file_in_marks_registers_a_real_mark_and_activates_it(tmp_path):
    cli = _client(tmp_path)
    (g._role_dir("marks") / "my_custom_mark.png").write_bytes(_png_bytes())
    d = cli.get("/api/branding").get_json()
    assert d["mark"] == "my_custom_mark"       # underscores pass the sanitizer unchanged
    assert {m["id"] for m in d["marks"]} == {"my_custom_mark"}
    assert (g._role_dir("marks") / "my_custom_mark.png").exists()


def test_dropped_mark_id_collision_gets_a_random_suffix(tmp_path):
    _cut_fake_marks(tmp_path, ids=("logo",))   # a real mark already using the id "logo"
    cli = _client(tmp_path)
    # A DIFFERENT raw filename that sanitizes to the SAME id ("logo") --
    # exercises _adopt_mark()'s own disambiguation. NOT a same-case-insensitive
    # variant ("Logo.png"): Windows/NTFS treats that as the SAME on-disk file as
    # the existing marks/logo.png and silently overwrites it before the sweep
    # ever runs, which would test a filesystem quirk instead of the code.
    (g._role_dir("marks") / "logo!!.png").write_bytes(_png_bytes())
    marks = cli.get("/api/branding").get_json()["marks"]
    ids = {m["id"] for m in marks}
    assert "logo" in ids            # the original, untouched
    assert len(ids) == 2            # plus the new one under a disambiguated id


def test_non_image_drop_is_left_alone_not_crashed_on_or_adopted(tmp_path):
    cli = _client(tmp_path)
    (g._role_dir("banner_main") / "notes.txt").write_text("todo: draw something", encoding="utf-8")
    r = cli.get("/api/achievements")
    assert r.status_code == 200      # a garbage drop must never 500 the achievements fetch
    assert (g._role_dir("banner_main") / "notes.txt").exists()  # left alone, not eaten
    slot = cli.get("/api/branding").get_json()["slots"]["banner_main"]
    assert slot["assets"] == []


def test_repeated_sweeps_do_not_re_adopt(tmp_path):
    cli = _client(tmp_path)
    (g._role_dir("banner_main") / "a.png").write_bytes(_png_bytes())
    cli.get("/api/achievements")
    cli.get("/api/achievements")
    cli.get("/api/achievements")
    assert len(cli.get("/api/branding").get_json()["slots"]["banner_main"]["assets"]) == 1


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

    The React Login page (2026-08-02) ported this ladder into LoginPage.jsx's
    onMascotError -- the <img> only exists in client-rendered DOM, not the raw
    server HTML GET /login now returns (see moonglade_gallery.py's login()
    route), so this checks the JSX source directly. Same "source-presence
    assertion" pattern loom/test/loom-image-job-register.test.js already
    established for JSX this suite has no browser harness to render."""
    import pathlib
    src = pathlib.Path("gallery/src/components/LoginPage.jsx").read_text(encoding="utf-8")
    assert '"/branding/login_nel.webp"' in src, "webp must be tried FIRST -- animated wins"
    for later in ("/branding/login_nel.png",
                  "/branding/mascots/login_nel.webp",
                  "/branding/mascots/login_nel.png",
                  "/branding/mascots/nel_narrator.png"):
        assert later in src, later + " is missing from the fallback ladder"
    # It must still END by hiding the element: a broken-image icon is the one
    # thing worse than no mascot at all.
    assert 'img.style.display = "none"' in src


# ---- Banner write-through (2026-08-06, owner: "Yes, seems obvious") -------------------
# The slot system stores many assets; banner.png and login-banner.png are the ONE file
# the header/login templates actually read. Every path that changes which asset displays
# must re-render its slot's flat -- before this, picking a banner saved a choice that
# displayed nowhere.
#
# 2026-09-10 (owner ruling): the render moved OUT of the coded tree into the app cache
# (g.banner_cache_dir(out_dir), the badge-thumb precedent), so these assertions moved with
# it. The path is asked for, never retyped -- same rule the coded dirs follow via _role_dir.

def _wide_png_bytes(w=80, h=10):
    """Wider than 4:1, with a red left half and blue right half -- so the left/right
    crop anchors produce DIFFERENT pixels and the test can tell which window won."""
    import io
    from PIL import Image
    im = Image.new("RGB", (w, h), (0, 0, 255))
    im.paste((255, 0, 0), (0, 0, w // 2, h))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def test_banner_upload_writes_the_flat_file_the_header_reads(tmp_path):
    from PIL import Image
    cli = _client(tmp_path)
    flat = g.banner_cache_dir(tmp_path) / "banner.png"
    assert not flat.exists()
    cli.post("/api/branding/slot", data={"slot": "banner_main",
             "file": (io_bytes(_wide_png_bytes()), "b.png")},
             content_type="multipart/form-data")
    assert flat.exists(), "an active banner must land in the banner cache"
    with Image.open(flat) as im:
        w, h = im.size
        assert w == h * 4, "the flat is cropped to the 4:1 banner canvas"


def test_banner_login_slot_writes_its_own_flat(tmp_path):
    cli = _client(tmp_path)
    cli.post("/api/branding/slot", data={"slot": "banner_login",
             "file": (io_bytes(_wide_png_bytes()), "b.png")},
             content_type="multipart/form-data")
    assert (g.banner_cache_dir(tmp_path) / "login-banner.png").exists()
    assert not (g.banner_cache_dir(tmp_path) / "banner.png").exists(), \
        "the two banner slots must never write each other's flat"


def test_banner_crop_change_rerenders_the_flat(tmp_path):
    """The transform sliders are REAL: zoom/cropX select different pixels of a
    wider-than-4:1 source (red left half, blue right half), and changing the active
    asset's transform rewrites the flat. Mirrors Control Panel.dc.html:953's preview
    math -- the flat must match what the sliders showed."""
    from PIL import Image
    cli = _client(tmp_path)
    d = cli.post("/api/branding/slot", data={"slot": "banner_main",
                 "file": (io_bytes(_wide_png_bytes()), "b.png")},
                 content_type="multipart/form-data").get_json()
    item = d["item"]                       # neutral default: centered window
    flat = g.banner_cache_dir(tmp_path) / "banner.png"
    with Image.open(flat) as im:
        w = im.size[0]
        assert im.size == (1920, 480), "flat is normalized to the DC's 1920x480 canvas"
        rgb = im.convert("RGB")
        assert rgb.getpixel((0, 0)) == (255, 0, 0), "centered window starts in the red half"
        assert rgb.getpixel((w - 1, 0)) == (0, 0, 255), "and ends in the blue half"
    # pan hard left -> all red
    cli.post("/api/branding/slot/crop", json={"slot": "banner_main",
             "id": item["id"], "cropX": 0})
    with Image.open(flat) as im:
        rgb = im.convert("RGB")
        assert rgb.getpixel((0, 0)) == (255, 0, 0)
        assert rgb.getpixel((im.size[0] - 1, 0)) == (255, 0, 0), "cropX 0 shows only the red window"
    # pan hard right -> all blue
    cli.post("/api/branding/slot/crop", json={"slot": "banner_main",
             "id": item["id"], "cropX": 100})
    with Image.open(flat) as im:
        rgb = im.convert("RGB")
        assert rgb.getpixel((0, 0)) == (0, 0, 255)
        assert rgb.getpixel((im.size[0] - 1, 0)) == (0, 0, 255), "cropX 100 shows only the blue window"
    # zoom 200 at cropX 0 halves the window: still all red, from an even tighter slice
    cli.post("/api/branding/slot/crop", json={"slot": "banner_main",
             "id": item["id"], "zoom": 200, "cropX": 0})
    with Image.open(flat) as im:
        rgb = im.convert("RGB")
        assert rgb.getpixel((im.size[0] - 1, 0)) == (255, 0, 0), "zoomed-in left window stays red"


def test_loom_banner_slot_writes_its_own_12to1_flat(tmp_path):
    """banner_loom is a real written-through slot: an upload renders
    branding/banner-loom.png at the DC's 1920x160 (12:1) canvas, and never
    touches the other two banner flats."""
    from PIL import Image
    cli = _client(tmp_path)
    r = cli.post("/api/branding/slot", data={"slot": "banner_loom",
                 "file": (io_bytes(_wide_png_bytes()), "strip.png")},
                 content_type="multipart/form-data")
    assert r.status_code == 200
    flat = g.banner_cache_dir(tmp_path) / "banner-loom.png"
    assert flat.exists()
    with Image.open(flat) as im:
        assert im.size == (1920, 160)
    assert not (g.banner_cache_dir(tmp_path) / "banner.png").exists()
    assert not (g.banner_cache_dir(tmp_path) / "login-banner.png").exists()


def test_branding_slot_from_gallery_sources_by_media_id(tmp_path):
    """The 'From the gallery...' chip (Control Panel.dc.html:342): POSTing a media_id
    instead of a file sources the asset from the user's own library via the shared
    media_id->file resolver, re-encoded through Pillow exactly like an upload."""
    lib = tmp_path / "images"
    lib.mkdir(parents=True)
    (lib / "prompt_task_m123abc.png").write_bytes(_png_bytes((7, 8, 9)))
    cli = _client(tmp_path)
    r = cli.post("/api/branding/slot", data={"slot": "banner_main", "media_id": "m123abc"},
                 content_type="multipart/form-data")
    assert r.status_code == 200
    item = r.get_json()["item"]
    assert (g._role_dir("banner_main") / (item["id"] + ".png")).exists()
    # the write-through flat is a real render in the app cache, outside the tree
    assert (g.banner_cache_dir(tmp_path) / "banner.png").exists()
    r = cli.post("/api/branding/slot", data={"slot": "banner_main", "media_id": "nope404"},
                 content_type="multipart/form-data")
    assert r.status_code == 400


def test_legacy_crop_manifest_migrates_to_transform(tmp_path):
    """A manifest written under the OLD left/center/right model (pre 2026-08-06)
    surfaces as the equivalent zoom/cropX/cropY -- an existing install's banners
    keep displaying unchanged until re-tuned."""
    import json as _json
    import moonglade_gallery as g
    sdir = g._role_dir("banner_main")
    sdir.mkdir(parents=True)
    (sdir / "abcd1234.png").write_bytes(_png_bytes())
    (sdir / "manifest.json").write_text(
        _json.dumps({"items": [{"id": "abcd1234", "crop": "left"}]}), encoding="utf-8")
    assets = g.list_slot_assets(tmp_path, "banner_main")
    assert (assets[0]["zoom"], assets[0]["cropX"], assets[0]["cropY"]) == (100, 0, 50)


def test_banner_pick_active_rerenders_the_flat(tmp_path):
    """Switching the active asset re-renders the flat to the newly-picked one."""
    from PIL import Image
    cli = _client(tmp_path)
    cli.post("/api/branding/slot", data={"slot": "banner_main",
             "file": (io_bytes(_png_bytes((10, 200, 10))), "a.png")},
             content_type="multipart/form-data")
    d2 = cli.post("/api/branding/slot", data={"slot": "banner_main",
                  "file": (io_bytes(_png_bytes((200, 30, 30))), "b.png")},
                  content_type="multipart/form-data").get_json()
    first_id = [a for a in d2["assets"] if a["id"] != d2["item"]["id"]][0]["id"]
    cli.post("/api/branding/slot/active", json={"slot": "banner_main", "id": first_id})
    flat = g.banner_cache_dir(tmp_path) / "banner.png"
    from PIL import Image
    with Image.open(flat) as im:
        px = im.convert("RGB").getpixel((0, 0))
    assert px == (10, 200, 10), "the flat shows the re-picked FIRST upload"


def test_non_banner_slots_never_write_a_flat(tmp_path):
    cli = _client(tmp_path)
    cli.post("/api/branding/slot", data={"slot": "mascots",
             "file": (io_bytes(_png_bytes()), "m.png")},
             content_type="multipart/form-data")
    assert not (g.banner_cache_dir(tmp_path) / "banner.png").exists()
    assert not (g.banner_cache_dir(tmp_path) / "login-banner.png").exists()


# ---- Custom Mark (handoff-2026-08-09-branding-integration.md's 6th marks tile,
# gated to the-great-library) -----------------------------------------------

def test_add_custom_mark_writes_manifest_and_becomes_active(tmp_path):
    mark = g.add_custom_mark(tmp_path, _png_bytes(), label="My mark")
    assert mark["kind"] == "upload" and mark["label"] == "My mark"
    from PIL import Image
    png = g._role_dir("marks") / (mark["id"] + ".png")
    assert png.exists()
    with Image.open(png) as im:
        assert im.format == "PNG"
    d = g.load_branding(tmp_path)
    assert d["mark"] == mark["id"]
    assert {m["id"] for m in g.list_marks(tmp_path)} == {mark["id"]}


def test_add_custom_mark_replaces_not_accumulates(tmp_path):
    """Only one custom-mark slot exists -- a second upload replaces the first
    rather than leaving an orphaned entry the picker would need to hide."""
    first = g.add_custom_mark(tmp_path, _png_bytes((1, 1, 1)))
    second = g.add_custom_mark(tmp_path, _png_bytes((2, 2, 2)))
    marks = g.list_marks(tmp_path)
    assert {m["id"] for m in marks} == {second["id"]}
    assert not (g._role_dir("marks") / (first["id"] + ".png")).exists()
    assert g.load_branding(tmp_path)["mark"] == second["id"]


def test_remove_custom_mark_reverts_active_mark_to_logo(tmp_path):
    mark = g.add_custom_mark(tmp_path, _png_bytes())
    assert g.remove_custom_mark(tmp_path, mark["id"]) is True
    assert g.list_marks(tmp_path) == []
    assert not (g._role_dir("marks") / (mark["id"] + ".png")).exists()
    assert g.load_branding(tmp_path)["mark"] == "logo"


def test_remove_custom_mark_refuses_a_built_in_tile_mark(tmp_path):
    """The Replace/Remove chips only ever sit next to the uploaded mark -- this
    guard makes that true at the data layer too, not just the UI not rendering
    the chips next to a built-in tile."""
    _cut_fake_marks(tmp_path, ids=("mark_4",))
    assert g.remove_custom_mark(tmp_path, "mark_4") is False
    assert {m["id"] for m in g.list_marks(tmp_path)} == {"mark_4"}


def test_custom_mark_route_requires_the_great_library(tmp_path, monkeypatch):
    cli = _client(tmp_path)
    monkeypatch.setattr(g, "_mark_earned", lambda *a, **k: False)
    r = cli.post("/api/branding/mark/custom",
                 data={"file": (io_bytes(_png_bytes()), "m.png")},
                 content_type="multipart/form-data")
    assert r.status_code == 403
    assert g.list_marks(tmp_path) == []

    monkeypatch.setattr(g, "_mark_earned", lambda *a, **k: True)
    r = cli.post("/api/branding/mark/custom",
                 data={"file": (io_bytes(_png_bytes()), "m.png")},
                 content_type="multipart/form-data")
    d = r.get_json()
    assert r.status_code == 200
    assert d["mark"] == d["marks"][0]["id"] and d["marks"][0]["kind"] == "upload"
    assert cli.get("/api/branding").get_json()["mark"] == d["mark"]


def test_custom_mark_route_rejects_bad_image(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "_mark_earned", lambda *a, **k: True)
    cli = _client(tmp_path)
    r = cli.post("/api/branding/mark/custom",
                 data={"file": (io_bytes(b"not an image"), "x.png")},
                 content_type="multipart/form-data")
    assert r.status_code == 400
    r = cli.post("/api/branding/mark/custom", data={}, content_type="multipart/form-data")
    assert r.status_code == 400


def test_custom_mark_remove_route(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "_mark_earned", lambda *a, **k: True)
    cli = _client(tmp_path)
    mark_id = cli.post("/api/branding/mark/custom",
                        data={"file": (io_bytes(_png_bytes()), "m.png")},
                        content_type="multipart/form-data").get_json()["mark"]
    r = cli.post("/api/branding/mark/custom/remove", json={"id": mark_id})
    assert r.status_code == 200
    assert r.get_json()["marks"] == []
    assert cli.get("/api/branding").get_json()["mark"] == "logo"
    assert cli.post("/api/branding/mark/custom/remove", json={"id": "nope"}).status_code == 400


# ---- A custom mark can become the launcher's icon (2026-09-07) ---------------
# The Desktop .lnk IS the app's icon (a .pyw can carry none) and it reads a mark's .ico off
# disk. Shipped tile marks arrive with one cut; an upload never had one, so add_custom_mark
# always returned ico:False and POST /api/branding/shortcut refused a custom mark outright.
# The cut now happens at upload time.

def test_custom_mark_upload_cuts_an_ico(tmp_path):
    from PIL import Image
    mark = g.add_custom_mark(tmp_path, _png_bytes(), label="My mark")
    assert mark["ico"] is True
    ico = g._role_dir("marks") / (mark["id"] + ".ico")
    assert ico.exists()
    with Image.open(ico) as im:
        assert im.format == "ICO"
        # every size the cut promises is really in the file -- a 4x4 source is scaled up
        # rather than letting Pillow drop the sizes larger than it
        assert {s for s in im.info["sizes"]} >= {(s, s) for s in g.ICO_SIZES}
    # and the listing agrees, because it exists-checks the same file
    assert [m["ico"] for m in g.list_marks(tmp_path)] == [True]


def test_the_ico_is_square_padded_not_stretched(tmp_path):
    """An icon is square. A wide mark is centred on transparency rather than distorted."""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", (400, 100), (200, 30, 30, 255)).save(buf, format="PNG")
    mark = g.add_custom_mark(tmp_path, buf.getvalue())
    assert mark["ico"] is True
    with Image.open(g._role_dir("marks") / (mark["id"] + ".ico")) as im:
        im.size = (256, 256)
        frame = im.convert("RGBA")
    assert frame.width == frame.height
    assert frame.getpixel((128, 128))[3] > 0          # the art is in the middle
    assert frame.getpixel((128, 4))[3] == 0           # and the padding is transparent


def test_a_failed_ico_cut_still_saves_the_mark(tmp_path, monkeypatch):
    """Best effort: losing the icon is never a reason to lose the mark the owner just
    uploaded (the same failure a machine with no Pillow would produce)."""
    monkeypatch.setattr(g, "_cut_mark_ico", lambda *a, **k: False)
    mark = g.add_custom_mark(tmp_path, _png_bytes())
    assert mark["ico"] is False
    assert (g._role_dir("marks") / (mark["id"] + ".png")).exists()
    assert not (g._role_dir("marks") / (mark["id"] + ".ico")).exists()
    assert g.load_branding(tmp_path)["mark"] == mark["id"]


def test_cut_mark_ico_returns_false_on_art_it_cannot_read(tmp_path):
    mdir = g._role_dir("marks")
    mdir.mkdir(parents=True, exist_ok=True)
    assert g._cut_mark_ico(mdir, "x", b"not an image at all") is False
    assert not (mdir / "x.ico").exists()


def test_replacing_and_removing_a_custom_mark_take_the_ico_with_them(tmp_path):
    """A stale .ico is an icon path pointing at a mark that no longer exists -- and
    list_marks would go on reporting ico:True for it."""
    first = g.add_custom_mark(tmp_path, _png_bytes((1, 1, 1)))
    second = g.add_custom_mark(tmp_path, _png_bytes((2, 2, 2)))
    assert not (g._role_dir("marks") / (first["id"] + ".ico")).exists()
    assert (g._role_dir("marks") / (second["id"] + ".ico")).exists()

    assert g.remove_custom_mark(tmp_path, second["id"]) is True
    assert not (g._role_dir("marks") / (second["id"] + ".ico")).exists()


def test_the_shortcut_route_accepts_an_uploaded_custom_mark(tmp_path, monkeypatch):
    """The whole point: before the cut, this route answered 400 'no .ico cut for it' for
    every custom mark. subprocess.run is stubbed exactly as the shipped shortcut test
    stubs it -- no real Desktop shortcut is written."""
    import subprocess
    monkeypatch.setattr(g, "_mark_earned", lambda *a, **k: True)
    captured = {}

    class R:
        returncode = 0
        stderr = ""
        stdout = ""

    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **k: (captured.__setitem__("argv", argv), R())[1])
    cli = _client(tmp_path)
    mark_id = cli.post("/api/branding/mark/custom",
                       data={"file": (io_bytes(_png_bytes()), "m.png")},
                       content_type="multipart/form-data").get_json()["mark"]

    r = cli.post("/api/branding/shortcut", json={"mark": mark_id})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert mark_id + ".ico" in captured["argv"][-1]


# ---- mark reward gate (2026-09-08): a mark bound to an achievement is pickable only once
# earned, the marks half of the same gate /api/skin gives skins. Mirrors the skin tests. ----
def _cut_bound_marks(tmp_path):
    """A free mark (mark_4) and one bound to `archivist` (mark_ms), both with art."""
    mdir = g._role_dir("marks"); mdir.mkdir(parents=True)
    for i in ("mark_4", "mark_ms"):
        (mdir / (i + ".png")).write_bytes(b"\x89PNG fake")
        (mdir / (i + ".ico")).write_bytes(b"\x00\x00icofake")
    (mdir / "marks.json").write_text(json.dumps({"marks": [
        {"id": "mark_4", "label": "Void Sentinel", "kind": "tile"},
        {"id": "mark_ms", "label": "Moonlit Stacks", "kind": "tile", "unlock": "archivist"},
    ]}), encoding="utf-8")


def test_list_marks_annotates_unlock_and_earned(tmp_path, sealed_donor_present):
    _cut_bound_marks(tmp_path)
    # no earned set -> everything earned:True (the pre-gate callers: upload response, launcher)
    by = {m["id"]: m for m in g.list_marks(tmp_path)}
    assert by["mark_4"]["earned"] is True and by["mark_ms"]["earned"] is True
    assert by["mark_4"]["unlock"] == "" and by["mark_ms"]["unlock"] == "archivist"
    # with an earned set that lacks archivist, the bound mark is locked, the free one is not
    by = {m["id"]: m for m in g.list_marks(tmp_path, earned_ids=set())}
    assert by["mark_4"]["earned"] is True          # free: always earned
    assert by["mark_ms"]["earned"] is False        # bound + not earned -> locked
    assert by["mark_ms"]["unlock_name"]            # a needle string, name or id fallback
    by = {m["id"]: m for m in g.list_marks(tmp_path, earned_ids={"archivist"})}
    assert by["mark_ms"]["earned"] is True         # bound + earned -> unlocked
    # _ach_name falls back to the id when the unlock id is not in the roster
    # (a hermetic install has no sealed roster), so the needle is never empty.
    assert by["mark_ms"]["unlock_name"] in (g._ach_name("archivist"), "archivist")
    assert g._ach_name("no-such-achievement") == "no-such-achievement"
    assert g._ach_name("") == ""


def test_branding_get_reports_locked_bound_mark(tmp_path, monkeypatch, sealed_donor_present):
    _cut_bound_marks(tmp_path)
    monkeypatch.setattr(g, "_earned_achievement_ids", lambda *a, **k: set())
    cli = _client(tmp_path)
    marks = {m["id"]: m for m in cli.get("/api/branding").get_json()["marks"]}
    assert marks["mark_4"]["earned"] is True
    assert marks["mark_ms"]["earned"] is False and marks["mark_ms"]["unlock"] == "archivist"


def test_set_locked_mark_is_refused_403(tmp_path, monkeypatch):
    _cut_bound_marks(tmp_path)
    monkeypatch.setattr(g, "_earned_achievement_ids", lambda *a, **k: set())   # archivist NOT earned
    cli = _client(tmp_path)
    before = cli.get("/api/branding").get_json()["mark"]
    r = cli.post("/api/branding", json={"mark": "mark_ms"})
    assert r.status_code == 403
    assert r.get_json()["error"] == "mark locked"
    # the active mark is EXACTLY what it was -- not merely "not the locked one"
    assert cli.get("/api/branding").get_json()["mark"] == before


def test_set_bound_mark_allowed_once_earned(tmp_path, monkeypatch):
    _cut_bound_marks(tmp_path)
    monkeypatch.setattr(g, "_earned_achievement_ids", lambda *a, **k: {"archivist"})
    cli = _client(tmp_path)
    r = cli.post("/api/branding", json={"mark": "mark_ms"})
    assert r.status_code == 200
    assert cli.get("/api/branding").get_json()["mark"] == "mark_ms"


def test_free_mark_and_logo_never_gated(tmp_path, monkeypatch):
    _cut_bound_marks(tmp_path)
    monkeypatch.setattr(g, "_earned_achievement_ids", lambda *a, **k: set())   # nothing earned
    cli = _client(tmp_path)
    assert cli.post("/api/branding", json={"mark": "mark_4"}).status_code == 200   # free
    assert cli.post("/api/branding", json={"mark": "logo"}).status_code == 200     # legacy


# ---- red team 2026-09-08: the two gate leaks the review found ----
def test_panel_summary_marks_carry_earned_so_the_lock_renders(tmp_path, monkeypatch, sealed_donor_present):
    # The Control Panel reads its marks from /api/panel/summary, NOT GET /api/branding.
    # If that payload doesn't gate, the two grids never lock a bound-unearned mark.
    _cut_bound_marks(tmp_path)
    monkeypatch.setattr(g, "_earned_achievement_ids", lambda *a, **k: set())
    cli = _client(tmp_path)
    marks = {m["id"]: m for m in cli.get("/api/panel/summary").get_json()["branding"]["marks"]}
    assert marks["mark_4"]["earned"] is True
    assert marks["mark_ms"]["earned"] is False and marks["mark_ms"]["unlock"] == "archivist"


def test_shortcut_route_refuses_a_locked_mark(tmp_path, monkeypatch):
    # The Desktop .lnk icon IS the app's real icon, so a locked reward mark's art
    # must not become it -- the same 403 the active-mark POST gives.
    _cut_bound_marks(tmp_path)
    monkeypatch.setattr(g, "_earned_achievement_ids", lambda *a, **k: set())   # archivist NOT earned
    cli = _client(tmp_path)
    r = cli.post("/api/branding/shortcut", json={"mark": "mark_ms"})
    assert r.status_code == 403 and r.get_json()["error"] == "mark locked"
    # a free mark still works (subprocess is mocked so make_launcher_shortcut can run)
    import subprocess
    class _R:
        returncode = 0
        stderr = ""
        stdout = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
    monkeypatch.setattr(g, "_earned_achievement_ids", lambda *a, **k: {"archivist"})
    assert cli.post("/api/branding/shortcut", json={"mark": "mark_ms"}).status_code == 200


# ---- spoiler seal (feat/mark-gating review 2026-09-08): a mark bound to a HIDDEN feat must
# not announce that feat's name to a user who hasn't earned it -- leak class HIGH #2 (owner
# 2026-08-21), the same rule /api/achievements enforces by masking the feat to "???". ----
def _a_hidden_achievement():
    for a in g._roster():
        if isinstance(a, dict) and a.get("hidden") and (a.get("name") or "").strip():
            return a["id"], a["name"].strip()
    return None, None


def _cut_mark_bound_to(aid):
    mdir = g._role_dir("marks"); mdir.mkdir(parents=True)
    (mdir / "mark_h.png").write_bytes(b"\x89PNG fake")
    (mdir / "marks.json").write_text(json.dumps({"marks": [
        {"id": "mark_h", "label": "Bound Mark", "kind": "tile", "unlock": aid},
    ]}), encoding="utf-8")


def test_list_marks_masks_an_unearned_hidden_feats_name(tmp_path, sealed_donor_present):
    aid, name = _a_hidden_achievement()
    assert aid, "the sealed roster should carry at least one named hidden feat"
    _cut_mark_bound_to(aid)
    # locked (not earned): the needle must NOT carry the hidden feat's name
    m = {x["id"]: x for x in g.list_marks(tmp_path, earned_ids=set())}["mark_h"]
    assert m["earned"] is False
    assert name not in (m["unlock_name"] or ""), "hidden feat named to an unearned user"
    assert m["unlock_name"] == ""                       # blank -> JSX shows "an achievement"
    # the RAW id is masked on the same gate -- it used to leak (e.g. "under-the-hood")
    assert m["unlock"] == "" and aid not in json.dumps(m), "hidden feat id leaked in the payload"
    # earned_ids=None ("earned unknown / not gating") is still silent for a hidden feat
    m = {x["id"]: x for x in g.list_marks(tmp_path)}["mark_h"]
    assert m["unlock_name"] == "" and m["unlock"] == ""
    # genuinely earned: naming it is no longer a spoiler
    m = {x["id"]: x for x in g.list_marks(tmp_path, earned_ids={aid})}["mark_h"]
    assert m["earned"] is True and m["unlock_name"] == name and m["unlock"] == aid


def test_panel_summary_masks_an_unearned_hidden_feats_name(tmp_path, monkeypatch, sealed_donor_present):
    aid, name = _a_hidden_achievement()
    assert aid
    _cut_mark_bound_to(aid)
    monkeypatch.setattr(g, "_earned_achievement_ids", lambda *a, **k: set())   # nothing earned
    cli = _client(tmp_path)
    blob = json.dumps(cli.get("/api/panel/summary").get_json()["branding"]["marks"])
    assert name not in blob and aid not in blob, "the Control Panel's marks payload leaks an unearned hidden feat (name or id)"


def test_locked_hidden_feat_mark_403_does_not_leak_the_feat(tmp_path, sealed_donor_present):
    """The mark-locked 403 must not name (or id) an unearned HIDDEN feat. The
    fallback used to be `unlock_name or unlock`, and unlock_name is masked to ""
    for a hidden feat -> it leaked the raw id (spoiler audit 2026-09-08)."""
    aid, name = _a_hidden_achievement()
    assert aid
    _cut_mark_bound_to(aid)
    cli = _client(tmp_path)                 # a fresh install earns no hidden feat
    r = cli.post("/api/branding", json={"mark": "mark_h"})
    assert r.status_code == 403
    body = r.get_data(as_text=True)
    assert aid not in body and name not in body, "the 403 leaks the hidden feat: %s" % body
    assert r.get_json().get("unlock") == ""


def test_list_marks_fails_closed_when_the_roster_is_unavailable(tmp_path, monkeypatch,
                                                                sealed_donor_present):
    """No/invalid/stale container -> _ach_hidden() is EMPTY, so a hidden-feat test alone
    passes for every mark and _ach_name falls back to the id itself. Proven to publish
    'the-konami-code' before the _ach_ids() guard (adversarial 2026-09-08; same fail-open
    the badge-thumb route closed on 2026-08-22). The roster must gate it."""
    aid, name = _a_hidden_achievement()
    assert aid
    _cut_mark_bound_to(aid)
    monkeypatch.setattr(g, "_sealed_defs", lambda: g._derive_sealed({"roster": []}))
    assert not g._ach_hidden() and not g._ach_ids()      # the state under test
    for earned in (set(), None, {aid}):
        m = {x["id"]: x for x in g.list_marks(tmp_path, earned_ids=earned)}["mark_h"]
        assert m["unlock_name"] == "", (
            "roster unavailable: published %r for a hidden feat" % m["unlock_name"])
        assert aid not in (m["unlock_name"] or "")


# ---- the gap the deeper review named: every gate test mocked the earned set.
# These run the REAL _earned_achievement_ids against a real catalog, and prove the
# ART is sealed server-side, not just hidden in CSS. ----
def _cut_marks_bound_to(tmp_path, bindings):
    """marks.json + art for {mark_id: unlock_ach_id-or-empty}."""
    mdir = g._role_dir("marks"); mdir.mkdir(parents=True)
    entries = []
    for mid, unlock in bindings.items():
        (mdir / (mid + ".png")).write_bytes(_png_bytes())
        (mdir / (mid + ".ico")).write_bytes(b"\x00\x00icofake")
        e = {"id": mid, "label": mid, "kind": "tile"}
        if unlock:
            e["unlock"] = unlock
        entries.append(e)
    (mdir / "marks.json").write_text(json.dumps({"marks": entries}), encoding="utf-8")


def test_gate_agrees_with_the_real_earned_computation(tmp_path, sealed_donor_present):
    # first-light earns off the 1-row catalog _app() saves; archivist (1000 imgs)
    # does NOT. No monkeypatch on the earned set -- the real recipe runs.
    _cut_marks_bound_to(tmp_path, {"mk_free": "", "mk_first": "first-light", "mk_arch": "archivist"})
    cli = _client(tmp_path)
    earned = g._earned_achievement_ids(tmp_path, tmp_path / "catalog.db")
    assert "first-light" in earned and "archivist" not in earned, "harness earned-set unexpected: %r" % (earned,)
    marks = {m["id"]: m for m in cli.get("/api/branding").get_json()["marks"]}
    assert marks["mk_free"]["earned"] is True
    assert marks["mk_first"]["earned"] is True    # its achievement is really earned
    assert marks["mk_arch"]["earned"] is False     # really not earned
    # the write gate agrees with the real computation, no mock
    assert cli.post("/api/branding", json={"mark": "mk_arch"}).status_code == 403
    assert cli.post("/api/branding", json={"mark": "mk_first"}).status_code == 200


def test_locked_mark_art_is_sealed_server_side(tmp_path, monkeypatch):
    # /branding/marks/<id>.png must 404 for a bound-unearned mark, not hand over
    # the full-res art -- the CSS lock is bypassable, the seal is the real gate.
    _cut_marks_bound_to(tmp_path, {"mk_free": "", "mk_arch": "archivist"})
    cli = _client(tmp_path)
    monkeypatch.setattr(g, "_earned_achievement_ids", lambda *a, **k: frozenset())
    assert cli.get("/branding/marks/mk_free.png").status_code == 200      # free art serves
    assert cli.get("/branding/marks/mk_arch.png").status_code == 404      # locked art sealed
    assert cli.get("/branding/marks/mk_arch.ico").status_code == 404      # and its icon
    assert cli.get("/branding/marks/marks.json").status_code == 200       # the manifest stays open
    monkeypatch.setattr(g, "_earned_achievement_ids", lambda *a, **k: frozenset({"archivist"}))
    assert cli.get("/branding/marks/mk_arch.png").status_code == 200      # earned -> art serves
