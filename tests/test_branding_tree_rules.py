"""The coded goods tree's three standing rules, as ruled by the owner on
2026-09-10.

1. DETECTION IS WIDE, ADOPTION IS NARROW. Any readable image in ANY subfolder
   under the coded root, at any depth, earns the hidden discovery feat -- as
   long as the APP did not put it there (a default is not a find: shipped art
   the legacy migration left loose, a tombstoned mark, an upload the Branding
   tab registered). Only the four adopt folders (the three banner slots +
   marks) ever consume a file; everywhere else the sweep is strictly read-only
   -- never unlink, rename, re-encode, move or register.
2. THE ROOT IS INERT. The rendered banner flats moved OUT of the tree into the
   app cache (g.banner_cache_dir(), the badge-thumb precedent), so the coded
   root holds nothing the app wrote. A file parked there is neither counted nor
   served, and startup MOVES (never deletes) an existing root render into the
   cache.
3. A MARK'S ART IS .png OR .webp. The once-a-day backstop counts either, the
   same set the sweep adopts and list_marks() resolves.

Every on-disk seed below is BUILT from the ROLE_CODE map via g._role_dir() /
g._role_rel() -- never a retyped hex literal, the rule tests/test_goods_map.py
already established. All hermetic: conftest's _isolated_branding redirects
branding_root() into tmp_path, and the banner cache derives from out_dir
(tmp_path) exactly as badge_cache_dir() does."""
import io
import json

import moonglade_container as mc
import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _seed_catalog(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])


def _client(tmp_path):
    """Authenticated client over a real install."""
    _seed_catalog(tmp_path)
    return login_client(tmp_path)


def _public_client(tmp_path):
    """/branding/<f> is PUBLIC tier, so the serving tests need no login -- and
    deliberately don't take one, since an anonymous GET is what a header <img>
    actually issues."""
    _seed_catalog(tmp_path)
    return create_app(tmp_path).test_client()


def _png_bytes(color=(200, 30, 30), w=80, h=20):
    """A real, decodable PNG wide enough for the 4:1 banner window math to have
    pixels to crop (a 1px fixture produces an empty box and fails soft)."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def _build_box(tmp_path, assets):
    """(Re)build this install's moonglade.dat and drop the read cache so the new
    content is seen immediately (the cache keys on mtime, which can collide with
    conftest's own seed within the filesystem's resolution)."""
    mc.write_container(g._container_path(), assets, {})
    g._container_cache.update(path=None, mtime=None, box=None)


def _flag(tmp_path):
    return (g.load_telemetry(tmp_path).get("flags") or {}).get("branding_custom_file")


def _mkdir(p):
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# 1. Wide, read-only detection
# ---------------------------------------------------------------------------

def test_a_drop_in_the_mascots_folder_raises_the_flag_and_is_untouched(tmp_path):
    """mascots/ is the folder the 2026-08-05 near-miss was about: it holds
    role-bound files real code reads by exact filename, so the sweep must never
    consume one. It is now READ, and reading is not adopting."""
    d = _mkdir(g._role_dir("mascots"))
    raw = _png_bytes()
    (d / "my_nel.png").write_bytes(raw)

    assert g.sweep_branding_drops(tmp_path) is False, "nothing outside the four folders adopts"
    assert _flag(tmp_path) == 1
    # byte-for-byte, same name, and no manifest conjured alongside it
    assert (d / "my_nel.png").read_bytes() == raw
    assert sorted(p.name for p in d.iterdir()) == ["my_nel.png"]


def test_a_drop_in_a_user_made_nested_folder_raises_the_flag_and_is_untouched(tmp_path):
    """The walk is general, not a list of known folders: a tinkerer who invents
    their own nesting is exactly the person this feat is for."""
    d = _mkdir(g.branding_root() / "my stuff" / "deeper")
    raw = _png_bytes((10, 200, 10))
    (d / "art.png").write_bytes(raw)

    assert g.sweep_branding_drops(tmp_path) is False
    assert _flag(tmp_path) == 1
    assert (d / "art.png").read_bytes() == raw


def test_a_text_file_anywhere_does_not_raise_the_flag(tmp_path):
    """_is_readable_image is the gate. A note-to-self in the tree is not a find,
    and neither is the breadcrumb README the scaffold itself writes."""
    _mkdir(g._role_dir("rewards"))
    (g._role_dir("rewards") / "notes.txt").write_text("todo: draw something", encoding="utf-8")
    _mkdir(g.branding_root() / "scratch")
    (g.branding_root() / "scratch" / "plan.txt").write_text("later", encoding="utf-8")
    _mkdir(g._role_dir("breadcrumb"))
    (g._role_dir("breadcrumb") / "README.txt").write_text("hint", encoding="utf-8")

    assert g.sweep_branding_drops(tmp_path) is False
    assert not _flag(tmp_path)


def test_a_file_at_the_coded_root_is_neither_counted_nor_served(tmp_path):
    """The FOLDERS are the mechanic. The root holds nothing the app wrote, so a
    file parked at its top level is not a find and not an asset."""
    cli = _public_client(tmp_path)
    root = _mkdir(g.branding_root())
    raw = _png_bytes()
    (root / "parked.png").write_bytes(raw)

    assert g.sweep_branding_drops(tmp_path) is False
    assert not _flag(tmp_path)
    assert cli.get("/branding/parked.png").status_code == 404
    assert (root / "parked.png").read_bytes() == raw, "and it is left exactly where it was"


def test_the_four_adopt_folders_still_adopt(tmp_path):
    """The regression pin: widening DETECTION must not have narrowed ADOPTION.
    All four -- the three banner slots and marks -- consume a hand-drop exactly
    as before."""
    _seed_catalog(tmp_path)
    for slot in g._SWEEPABLE_SLOTS:
        _mkdir(g._role_dir(slot))
        (g._role_dir(slot) / ("drop_" + slot + ".png")).write_bytes(_png_bytes())
    mdir = _mkdir(g._role_dir("marks"))
    (mdir / "hand_drop.png").write_bytes(_png_bytes())

    assert g.sweep_branding_drops(tmp_path) is True
    assert _flag(tmp_path) == 1
    for slot in g._SWEEPABLE_SLOTS:
        assert not (g._role_dir(slot) / ("drop_" + slot + ".png")).exists(), \
            "the raw drop is consumed, not left beside the adopted copy"
        assets = g.list_slot_assets(tmp_path, slot)
        assert len(assets) == 1
        assert (g._role_dir(slot) / (assets[0]["id"] + ".png")).is_file()
    # marks adopt under a stem-derived id, so the adopted art legitimately lands
    # back on the raw drop's own filename -- the registration is what says it was
    # adopted rather than merely left alone.
    assert "hand_drop" in {m["id"] for m in g.list_marks(tmp_path)}
    assert (mdir / "hand_drop.png").is_file()
    assert g.load_branding(tmp_path)["mark"] == "hand_drop"


# ---------------------------------------------------------------------------
# 1b. ...and a DEFAULT is not a find
#
# Every regression this mechanic has ever had is the same one: something that
# was always on disk gets counted as the owner's own drop. Widening detection
# to the whole tree widens that risk to every file the app itself ever put
# there, so each of the three ways it does that gets a pin.
# ---------------------------------------------------------------------------

def test_a_tombstoned_shipped_mark_left_loose_is_not_a_find(tmp_path):
    """mark_12 (Gem Tome, delisted 2026-07-23) and mark_74 (renamed by
    bundle-v2) sit loose on every install that predates their delisting. The
    adopt path has treated a tombstoned stem as KNOWN since the 2026-08-13 live
    incident on the owner's own machine; detection has to hold the same line, or
    delisting a default silently earns the feat for everyone who upgrades."""
    mdir = _mkdir(g._role_dir("marks"))
    for stem in sorted(g._MARK_TOMBSTONES):
        (mdir / (stem + ".png")).write_bytes(_png_bytes())

    assert g.sweep_branding_drops(tmp_path) is False
    assert not _flag(tmp_path), "a delisted shipped default earned the feat"
    for stem in sorted(g._MARK_TOMBSTONES):
        assert (mdir / (stem + ".png")).is_file()


def test_shipped_art_the_legacy_migration_left_loose_is_not_a_find(tmp_path):
    """_migrate_legacy_branding_root() moves a pre-coded-tree install's whole
    role tree into the coded dirs -- marks, mascots, rewards, the system chrome.
    Every one of those files is the APP's, and every one of them lands at
    depth>0 where the walk looks. The container that ships them is what names
    them."""
    loose = {
        g._role_rel("marks", "mark_4.png"): _png_bytes(),
        g._role_rel("mascots", "nel_narrator.png"): _png_bytes((9, 9, 9)),
        g._role_rel("rewards", "reward_1.png"): _png_bytes((8, 8, 8)),
        g._role_rel("badges", "first-light.png"): _png_bytes((7, 7, 7)),
    }
    _build_box(tmp_path, dict(loose, **{
        g._role_rel("marks", "marks.json"): json.dumps(
            {"marks": [{"id": "mark_4", "label": "Crescent", "kind": "tile"}]}).encode()}))
    for rel, raw in loose.items():
        p = g.branding_root() / rel
        _mkdir(p.parent)
        p.write_bytes(raw)

    assert g.sweep_branding_drops(tmp_path) is False
    assert not _flag(tmp_path), "the app's own shipped art earned the discovery feat"

    # ...and the owner's actual drop, right beside it, still does.
    (g._role_dir("mascots") / "my_own_nel.png").write_bytes(_png_bytes((1, 250, 1)))
    assert g.sweep_branding_drops(tmp_path) is False
    assert _flag(tmp_path) == 1


def test_system_chrome_is_not_a_find_even_with_no_container(tmp_path):
    """A bare install has no moonglade.dat to ask, so the app's chrome is named
    directly: the bare-name system files the translation's rule 2 owns, and the
    ee_* starfall art rule 3 owns."""
    try:                                 # conftest seeds one for the sealed roster
        g._container_path().unlink()
    except OSError:
        pass
    g._container_cache.update(path=None, mtime=None, box=None)

    sysd = _mkdir(g._role_dir("system"))
    for name in sorted(g._SYSTEM_TOP_FILES):
        if name.endswith(".ico"):
            continue                     # not an image Pillow reads; nothing to pin
        (sysd / name).write_bytes(_png_bytes())
    (_mkdir(g._role_dir("starfall")) / "ee_nelstarfall.png").write_bytes(_png_bytes())

    assert g._get_container() is None, "this install genuinely has no pack"
    assert g.sweep_branding_drops(tmp_path) is False
    assert not _flag(tmp_path)


def test_an_upload_through_the_branding_tab_is_not_a_find(tmp_path):
    """add_slot_asset() writes `<id>.png` straight into a slot folder the walk
    reads. Using the Branding tab exactly as designed is the opposite of finding
    an undocumented folder -- it must not earn the feat."""
    _seed_catalog(tmp_path)
    asset = g.add_slot_asset(tmp_path, "banner_main", _png_bytes())
    assert asset and (g._role_dir("banner_main") / (asset["id"] + ".png")).is_file()

    assert g.sweep_branding_drops(tmp_path) is False, "a registered id is not a fresh drop"
    assert not _flag(tmp_path)
    assert g._has_custom_branding_art(tmp_path) is False


# ---------------------------------------------------------------------------
# 2. The renders live in the cache; the root is inert
# ---------------------------------------------------------------------------

def test_the_render_lands_in_the_cache_and_the_root_stays_empty(tmp_path):
    cli = _client(tmp_path)
    r = cli.post("/api/branding/slot",
                 data={"slot": "banner_main", "file": (io.BytesIO(_png_bytes()), "b.png")},
                 content_type="multipart/form-data")
    assert r.status_code == 200

    from PIL import Image
    flat = g.banner_cache_dir(tmp_path) / "banner.png"
    assert flat.is_file(), "the render belongs in the app cache, beside the badge thumbs"
    with Image.open(flat) as im:
        assert im.size == (1920, 480)
    assert [p.name for p in g.branding_root().iterdir() if p.is_file()] == [], \
        "the coded root must hold nothing the app wrote"


def test_building_the_app_never_moves_anything_in_the_tree(tmp_path):
    """create_app() is what every test in this suite builds, several of them
    from module-scoped fixtures that conftest's per-test branding isolation
    cannot reach. Its only write into the coded tree is the additive scaffold --
    so a plain pytest run can never relocate a real install's dressed banner.
    The destructive migration belongs to main()."""
    _seed_catalog(tmp_path)
    root = _mkdir(g.branding_root())
    raw = _png_bytes((7, 8, 9))
    (root / "banner.png").write_bytes(raw)

    create_app(tmp_path)

    assert (root / "banner.png").read_bytes() == raw, \
        "app construction moved a file out of the coded tree"
    assert not (g.banner_cache_dir(tmp_path) / "banner.png").exists()


def test_startup_migration_moves_a_pre_existing_root_flat_into_the_cache(tmp_path):
    """MOVE, never delete: that flat is the banner the install is currently
    WEARING, and re-rendering it needs an active asset that may only exist in
    the container."""
    _seed_catalog(tmp_path)
    root = _mkdir(g.branding_root())
    raw = _png_bytes((7, 8, 9))
    (root / "banner.png").write_bytes(raw)

    g._migrate_root_banner_flats(tmp_path)     # what a real start (main()) runs

    dst = g.banner_cache_dir(tmp_path) / "banner.png"
    assert not (root / "banner.png").exists()
    assert dst.read_bytes() == raw, "moved, not re-rendered and not dropped"

    g._migrate_root_banner_flats(tmp_path)     # idempotent: a no-op second time
    assert dst.read_bytes() == raw

    # A cache render already in place is the newer truth. A stale root leftover
    # never overwrites it, and is left where it is rather than deleted.
    (root / "banner.png").write_bytes(_png_bytes((1, 2, 3)))
    g._migrate_root_banner_flats(tmp_path)
    assert dst.read_bytes() == raw
    assert (root / "banner.png").is_file()


def test_serving_prefers_the_cache_render_then_the_sealed_default(tmp_path):
    cli = _public_client(tmp_path)
    _build_box(tmp_path, {g._role_rel("banner_main", "banner_main.png"): b"SHIPPED MAIN"})

    r = cli.get("/branding/banner.png")
    assert r.status_code == 200 and r.data == b"SHIPPED MAIN", \
        "nothing rendered yet -> the slot's shipped sealed default (rule 8)"

    cdir = _mkdir(g.banner_cache_dir(tmp_path))
    (cdir / "banner.png").write_bytes(b"MY RENDER")
    assert cli.get("/branding/banner.png").data == b"MY RENDER"

    # ...and the coded root is never consulted for a flat, in either state.
    _mkdir(g.branding_root())
    (g.branding_root() / "banner.png").write_bytes(b"PARKED AT ROOT")
    assert cli.get("/branding/banner.png").data == b"MY RENDER"
    (cdir / "banner.png").unlink()
    assert cli.get("/branding/banner.png").data == b"SHIPPED MAIN"


# ---------------------------------------------------------------------------
# 3. A mark's art is .png OR .webp
# ---------------------------------------------------------------------------

def test_has_loose_marks_sees_a_webp_only_mark(tmp_path):
    """The webp lane exists for ANIMATED marks the owner authors himself. The
    once-a-day backstop counted .png only until 2026-09-10, so such a mark
    registered, displayed, and was then invisible to it.

    _has_loose_marks is filesystem-only by contract (a container-aware check
    defeated this feat once before, 2026-08-09), so these are plain bytes on
    disk -- presence is the whole question it asks."""
    mdir = _mkdir(g._role_dir("marks"))
    (mdir / "marks.json").write_text(json.dumps(
        {"marks": [{"id": "animated", "label": "animated", "kind": "tile"}]}),
        encoding="utf-8")
    assert g._has_loose_marks() is False, "a manifest entry with no art is not a mark"

    (mdir / "animated.webp").write_bytes(b"RIFF....WEBPVP8 ")
    assert g._has_loose_marks() is True

    g.sweep_telemetry(tmp_path)
    assert _flag(tmp_path) == 1, "and the backstop fires off it end to end"
