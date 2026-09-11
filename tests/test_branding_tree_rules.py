"""The coded goods tree's three standing rules, as ruled by the owner on
2026-09-10.

1. DETECTION IS WIDE, ADOPTION IS NARROW. Any readable image in ANY subfolder
   under the coded root, at any depth, earns the hidden discovery feat. Only the
   four adopt folders (the three banner slots + marks) ever consume a file;
   everywhere else the sweep is strictly read-only -- never unlink, rename,
   re-encode, move or register.
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


def test_startup_migration_moves_a_pre_existing_root_flat_into_the_cache(tmp_path):
    """MOVE, never delete: that flat is the banner the install is currently
    WEARING, and re-rendering it needs an active asset that may only exist in
    the container."""
    _seed_catalog(tmp_path)
    root = _mkdir(g.branding_root())
    raw = _png_bytes((7, 8, 9))
    (root / "banner.png").write_bytes(raw)

    create_app(tmp_path)                       # startup runs the migration

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
