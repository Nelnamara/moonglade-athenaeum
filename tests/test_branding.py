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
    # (the classic header render of the legacy logo died with BASE_HTML/INDEX_HTML
    # in the 2026-08-08 classic cut; the React gallery reads /api/branding, whose
    # defaults are what the assertions above pin)


def test_branding_save_and_render(tmp_path):
    _cut_fake_marks(tmp_path)
    cli = _client(tmp_path)
    d = cli.get("/api/branding").get_json()
    assert {m["id"] for m in d["marks"]} == {"mark_4", "mark_12"}
    assert d["mark"] == "mark_4"          # default mark once assets exist
    r = cli.post("/api/branding", json={"mark": "mark_12", "anim": "eclipse"})
    assert r.get_json() == {"mark": "mark_12", "anim": "eclipse"}
    assert json.loads((tmp_path / "branding.json").read_text())["anim"] == "eclipse"
    # the saved choice reads back through the same API the React header consumes
    # (the classic BASE_HTML mark-span render died in the 2026-08-08 classic cut)
    d = cli.get("/api/branding").get_json()
    assert d["mark"] == "mark_12" and d["anim"] == "eclipse"


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
    the React shell at /next is the surviving page that proves it)."""
    mdir = tmp_path / "branding" / "marks"
    mdir.mkdir(parents=True)
    (mdir / "marks.json").write_text('{"marks": ["not-a-dict", 42]}', encoding="utf-8")
    (tmp_path / "branding.json").write_text('["not", "an", "object"]', encoding="utf-8")
    cli = _client(tmp_path)
    assert cli.get("/next").status_code == 200
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
    """The 4 Control Panel Branding slots (banner_main/banner_login/mascots/
    rewards) added 2026-08-05 -- no backend existed for them before this."""
    cli = _client(tmp_path)
    d = cli.get("/api/branding").get_json()
    assert set(d["slots"].keys()) == {"banner_main", "banner_login", "mascots", "rewards", "banner_loom"}
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
    assert item["png"] == "/branding/banner_main/%s.png" % item["id"]
    assert d["assets"] == [item]
    # really on disk as a real PNG, re-encoded through Pillow regardless of the
    # upload's own (wrong) extension/content-type
    from PIL import Image
    png_path = tmp_path / "branding" / "banner_main" / (item["id"] + ".png")
    assert png_path.exists()
    with Image.open(png_path) as im:
        assert im.format == "PNG"
    slots = cli.get("/api/branding").get_json()["slots"]
    assert slots["banner_main"] == {"assets": [item], "active": item["id"]}


def test_branding_slot_non_banner_defaults_neutral_transform(tmp_path):
    cli = _client(tmp_path)
    r = cli.post("/api/branding/slot", data={"slot": "mascots",
                 "file": (io_bytes(_png_bytes()), "m.png")},
                 content_type="multipart/form-data")
    it = r.get_json()["item"]
    assert (it["zoom"], it["cropX"], it["cropY"]) == (100, 50, 50)


def test_branding_slot_second_upload_stays_available_and_becomes_active(tmp_path):
    """Uploading a second asset into the same slot does NOT delete the first --
    both exist, matching list_marks()'s own "many stored" shape, so a later
    rotating-source pass has more than one real candidate to pick from."""
    cli = _client(tmp_path)
    first = cli.post("/api/branding/slot", data={"slot": "rewards",
                     "file": (io_bytes(_png_bytes((10, 10, 10))), "a.png")},
                     content_type="multipart/form-data").get_json()["item"]
    second = cli.post("/api/branding/slot", data={"slot": "rewards",
                      "file": (io_bytes(_png_bytes((20, 20, 20))), "b.png")},
                      content_type="multipart/form-data").get_json()["item"]
    slot = cli.get("/api/branding").get_json()["slots"]["rewards"]
    assert {a["id"] for a in slot["assets"]} == {first["id"], second["id"]}
    assert slot["active"] == second["id"]       # the most recent upload wins


def test_branding_slot_upload_rejects_unknown_slot_and_bad_image(tmp_path):
    cli = _client(tmp_path)
    r = cli.post("/api/branding/slot", data={"slot": "not-a-real-slot",
                 "file": (io_bytes(_png_bytes()), "x.png")},
                 content_type="multipart/form-data")
    assert r.status_code == 400
    r = cli.post("/api/branding/slot", data={"slot": "mascots",
                 "file": (io_bytes(b"not an image"), "x.png")},
                 content_type="multipart/form-data")
    assert r.status_code == 400 and "image" in r.get_json()["error"].lower()
    r = cli.post("/api/branding/slot", data={"slot": "mascots"},
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
    sdir = tmp_path / "branding" / "mascots"
    sdir.mkdir(parents=True)
    (sdir / "manifest.json").write_text('{"items": ["not-a-dict", 42]}', encoding="utf-8")
    (tmp_path / "branding_slots.json").write_text('["not", "an", "object"]', encoding="utf-8")
    cli = _client(tmp_path)
    d = cli.get("/api/branding").get_json()
    assert d["slots"]["mascots"] == {"assets": [], "active": None}


# ---------------------------------------------------------------------------
# "Under the Hood" real trigger (docs/DECISIONS.md "Under the Hood intended
# flow", 2026-07-26, owner-confirmed 2026-08-05): a raw file dropped by hand
# into an empty branding/<slot>/ folder gets adopted automatically, and THAT
# is what fires the achievement -- not the authenticated upload API above,
# which sits behind the very unlock this earns.
# ---------------------------------------------------------------------------

def test_discovery_tree_creates_empty_slot_folders_and_one_readme(tmp_path):
    cli = _client(tmp_path)          # create_app() calls ensure_branding_discovery_tree()
    root = tmp_path / "branding"
    for slot in ("banner_main", "banner_login", "mascots", "rewards", "marks"):
        assert (root / slot).is_dir()
        assert list((root / slot).iterdir()) == []   # empty -- nothing to find yet
    assert (root / "README.txt").read_text(encoding="utf-8") == g._BRANDING_README


def test_discovery_tree_never_overwrites_real_content(tmp_path):
    """Idempotent: a real install's existing README/art must survive every
    server start, not just the first one."""
    root = tmp_path / "branding" / "marks"
    root.mkdir(parents=True)
    (tmp_path / "branding" / "README.txt").write_text("owner's own note", encoding="utf-8")
    (root / "mark_4.png").write_bytes(_png_bytes())
    g.ensure_branding_discovery_tree()
    assert (tmp_path / "branding" / "README.txt").read_text(encoding="utf-8") == "owner's own note"
    assert (root / "mark_4.png").exists()


def test_dropped_file_in_a_new_slot_is_adopted_and_earns_the_achievement(tmp_path):
    cli = _client(tmp_path)
    (tmp_path / "branding" / "banner_login" / "my_art.png").write_bytes(_png_bytes())

    d = cli.get("/api/achievements").get_json()
    uth = next(a for a in d["achievements"] if a["id"] == "under-the-hood")
    assert uth["earned"] is True

    slot = cli.get("/api/branding").get_json()["slots"]["banner_login"]
    assert len(slot["assets"]) == 1
    assert slot["active"] == slot["assets"][0]["id"]
    # the raw drop is consumed, not left sitting alongside the adopted copy
    assert not (tmp_path / "branding" / "banner_login" / "my_art.png").exists()
    assert (tmp_path / "branding" / "banner_login" / (slot["assets"][0]["id"] + ".png")).exists()


def test_dropped_jpeg_is_re_encoded_to_real_png(tmp_path):
    """The design says PNG/JPEG explicitly -- a raw .jpg drop must adopt too,
    not just .png, the same as a real photo someone actually has lying around."""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (5, 5, 5)).save(buf, format="JPEG")
    cli = _client(tmp_path)
    (tmp_path / "branding" / "banner_main" / "photo.jpg").write_bytes(buf.getvalue())
    d = cli.get("/api/branding").get_json()["slots"]["banner_main"]
    assert len(d["assets"]) == 1
    with Image.open(tmp_path / "branding" / "banner_main" / (d["assets"][0]["id"] + ".png")) as im:
        assert im.format == "PNG"


# ---------------------------------------------------------------------------
# Regression guard for a real near-miss (2026-08-05): mascots/ and rewards/
# already hold a family of specifically-named, role-bound files real shipped
# code reads by exact filename (narrator/login/power-modal mascots, the claim
# icon). The FIRST version of the sweep had no awareness of that and would
# have adopted-then-DELETED every one of them on any install that actually
# has them. Caught before it ever ran against real assets -- this pins it so
# it can't come back quietly.
# ---------------------------------------------------------------------------

def test_sweep_never_touches_mascots_or_rewards(tmp_path):
    cli = _client(tmp_path)
    real_mascot = tmp_path / "branding" / "mascots" / "gen_nel.png"
    real_reward = tmp_path / "branding" / "rewards" / "claim.png"
    real_mascot.write_bytes(_png_bytes())
    real_reward.write_bytes(_png_bytes())

    for _ in range(3):
        cli.get("/api/achievements")
        cli.get("/api/branding")
        cli.get("/api/panel/summary")

    # untouched: still sitting under their OWN real names, not adopted/renamed
    assert real_mascot.exists()
    assert real_reward.exists()
    slots = cli.get("/api/branding").get_json()["slots"]
    assert slots["mascots"] == {"assets": [], "active": None}
    assert slots["rewards"] == {"assets": [], "active": None}
    # and the achievement must NOT fire off a file that was never adopted --
    # unearned hidden feats are masked to a fake id, so "no real id present"
    # IS the not-earned assertion (see /api/achievements' own docstring).
    d = cli.get("/api/achievements").get_json()
    assert not any(a["id"] == "under-the-hood" for a in d["achievements"])


def test_dropped_file_in_marks_registers_a_real_mark_and_activates_it(tmp_path):
    cli = _client(tmp_path)
    (tmp_path / "branding" / "marks" / "my_custom_mark.png").write_bytes(_png_bytes())
    d = cli.get("/api/branding").get_json()
    assert d["mark"] == "my_custom_mark"       # underscores pass the sanitizer unchanged
    assert {m["id"] for m in d["marks"]} == {"my_custom_mark"}
    assert (tmp_path / "branding" / "marks" / "my_custom_mark.png").exists()


def test_dropped_mark_id_collision_gets_a_random_suffix(tmp_path):
    _cut_fake_marks(tmp_path, ids=("logo",))   # a real mark already using the id "logo"
    cli = _client(tmp_path)
    # A DIFFERENT raw filename that sanitizes to the SAME id ("logo") --
    # exercises _adopt_mark()'s own disambiguation. NOT a same-case-insensitive
    # variant ("Logo.png"): Windows/NTFS treats that as the SAME on-disk file as
    # the existing marks/logo.png and silently overwrites it before the sweep
    # ever runs, which would test a filesystem quirk instead of the code.
    (tmp_path / "branding" / "marks" / "logo!!.png").write_bytes(_png_bytes())
    marks = cli.get("/api/branding").get_json()["marks"]
    ids = {m["id"] for m in marks}
    assert "logo" in ids            # the original, untouched
    assert len(ids) == 2            # plus the new one under a disambiguated id


def test_non_image_drop_is_left_alone_not_crashed_on_or_adopted(tmp_path):
    cli = _client(tmp_path)
    (tmp_path / "branding" / "banner_main" / "notes.txt").write_text("todo: draw something", encoding="utf-8")
    r = cli.get("/api/achievements")
    assert r.status_code == 200      # a garbage drop must never 500 the achievements fetch
    assert (tmp_path / "branding" / "banner_main" / "notes.txt").exists()  # left alone, not eaten
    slot = cli.get("/api/branding").get_json()["slots"]["banner_main"]
    assert slot["assets"] == []


def test_repeated_sweeps_do_not_re_adopt(tmp_path):
    cli = _client(tmp_path)
    (tmp_path / "branding" / "banner_main" / "a.png").write_bytes(_png_bytes())
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
                  "/branding/mascots/gen_nel.png"):
        assert later in src, later + " is missing from the fallback ladder"
    # It must still END by hiding the element: a broken-image icon is the one
    # thing worse than no mascot at all.
    assert 'img.style.display = "none"' in src


# ---- Banner write-through (2026-08-06, owner: "Yes, seems obvious") -------------------
# The slot system stores many assets; branding/banner.png and login-banner.png are the
# ONE file the header/login templates actually read. Every path that changes which asset
# displays must re-render its slot's flat -- before this, picking a banner saved a choice
# that displayed nowhere.

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
    flat = tmp_path / "branding" / "banner.png"
    assert not flat.exists()
    cli.post("/api/branding/slot", data={"slot": "banner_main",
             "file": (io_bytes(_wide_png_bytes()), "b.png")},
             content_type="multipart/form-data")
    assert flat.exists(), "an active banner must land in branding/banner.png"
    with Image.open(flat) as im:
        w, h = im.size
        assert w == h * 4, "the flat is cropped to the 4:1 banner canvas"


def test_banner_login_slot_writes_its_own_flat(tmp_path):
    cli = _client(tmp_path)
    cli.post("/api/branding/slot", data={"slot": "banner_login",
             "file": (io_bytes(_wide_png_bytes()), "b.png")},
             content_type="multipart/form-data")
    assert (tmp_path / "branding" / "login-banner.png").exists()
    assert not (tmp_path / "branding" / "banner.png").exists(), \
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
    flat = tmp_path / "branding" / "banner.png"
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
    flat = tmp_path / "branding" / "banner-loom.png"
    assert flat.exists()
    with Image.open(flat) as im:
        assert im.size == (1920, 160)
    assert not (tmp_path / "branding" / "banner.png").exists()
    assert not (tmp_path / "branding" / "login-banner.png").exists()


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
    assert (tmp_path / "branding" / "banner_main" / (item["id"] + ".png")).exists()
    assert (tmp_path / "branding" / "banner.png").exists()   # write-through fired too
    r = cli.post("/api/branding/slot", data={"slot": "banner_main", "media_id": "nope404"},
                 content_type="multipart/form-data")
    assert r.status_code == 400


def test_legacy_crop_manifest_migrates_to_transform(tmp_path):
    """A manifest written under the OLD left/center/right model (pre 2026-08-06)
    surfaces as the equivalent zoom/cropX/cropY -- an existing install's banners
    keep displaying unchanged until re-tuned."""
    import json as _json
    import moonglade_gallery as g
    sdir = tmp_path / "branding" / "banner_main"
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
    flat = tmp_path / "branding" / "banner.png"
    from PIL import Image
    with Image.open(flat) as im:
        px = im.convert("RGB").getpixel((0, 0))
    assert px == (10, 200, 10), "the flat shows the re-picked FIRST upload"


def test_non_banner_slots_never_write_a_flat(tmp_path):
    cli = _client(tmp_path)
    cli.post("/api/branding/slot", data={"slot": "mascots",
             "file": (io_bytes(_png_bytes()), "m.png")},
             content_type="multipart/form-data")
    assert not (tmp_path / "branding" / "banner.png").exists()
    assert not (tmp_path / "branding" / "login-banner.png").exists()
