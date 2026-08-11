"""The asset container: format round-trip, opacity, corruption handling, and the
loose-then-container resolution layer (moonglade_container.py + the
_branding_bytes/_branding_exists/_seed_loose_manifest family in
moonglade_gallery.py). Decision record: docs/DECISIONS.md "The asset container,
re-scoped from scratch" (2026-08-10).

The conftest's autouse _isolated_branding fixture points branding_root() at each
test's tmp_path, so _container_path() (a SIBLING of branding_root()) lands in
tmp_path too -- every test here builds its own container, none can see the
developer's real moonglade.dat. That isolation is asserted, not assumed."""
import json

import pytest

import moonglade_container as mc
import moonglade_gallery as g

from tests.conftest import login_client

# A real (tiny) PNG so PIL-facing paths get decodable bytes.
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082")


def _build(tmp_path, assets=None, payloads=None):
    """A container in the isolated app root (branding_root().parent)."""
    box_path = g._container_path()
    default_assets = {
        "marks/marks.json": json.dumps(
            {"marks": [{"id": "mark_4", "label": "Crescent", "kind": "tile"},
                       {"id": "mark_12", "label": "Tile Twelve", "kind": "tile"}]}).encode(),
        "marks/mark_4.png": PNG_1PX,
        "marks/mark_12.png": PNG_1PX,
        "banner.png": PNG_1PX,
        "badges/first-light.png": PNG_1PX,
        "banner_main/manifest.json": json.dumps(
            {"items": [{"id": "deadbeef", "zoom": 100, "cropX": 50, "cropY": 50}]}).encode(),
        "banner_main/deadbeef.png": PNG_1PX,
    }
    mc.write_container(box_path,
                       assets if assets is not None else default_assets,
                       payloads or {})
    return box_path


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------
def test_round_trip_every_asset_and_payload(tmp_path):
    assets = {"a/b.bin": b"\x00\x01\x02" * 999, "top.txt": b"hello moonglade"}
    payloads = {"achievements": json.dumps([{"id": "x"}]).encode()}
    path = tmp_path / "c.dat"
    n_a, n_p = mc.write_container(path, assets, payloads)
    assert (n_a, n_p) == (2, 1)
    box = mc.open_container(path)
    assert box is not None
    assert box.paths() == ["a/b.bin", "top.txt"]
    for rel, raw in assets.items():
        assert box.get(rel) == raw
    assert box.payload("achievements") == payloads["achievements"]
    assert box.get("missing.png") is None and box.payload("nope") is None


def test_on_disk_bytes_are_opaque(tmp_path):
    """The MPQ bar, measured: neither file CONTENT nor file NAMES are readable
    in the raw container bytes. A plain zip/SQLite fails exactly this."""
    secret_name = "marks/very-secret-mark.png"
    path = tmp_path / "c.dat"
    mc.write_container(path, {secret_name: PNG_1PX, "b.json": b'{"marks": []}'})
    blob = path.read_bytes()
    assert PNG_1PX[:8] not in blob, "PNG magic readable -- blobs are not obfuscated"
    assert b"very-secret-mark" not in blob, "asset names readable -- TOC is not obfuscated"
    assert b'{"marks"' not in blob, "JSON content readable in the raw file"


def test_corruption_degrades_to_absent_never_garbage(tmp_path):
    path = tmp_path / "c.dat"
    mc.write_container(path, {"a.bin": b"A" * 4096})
    # Flip a byte in the blob body: that asset must vanish (checksum), not corrupt.
    raw = bytearray(path.read_bytes())
    raw[mc.HEADER_SIZE + 100] ^= 0xFF
    path.write_bytes(bytes(raw))
    box = mc.open_container(path)
    assert box is not None and box.get("a.bin") is None
    # Truncate mid-TOC: the whole container must open as None, not raise.
    mc.write_container(path, {"a.bin": b"A" * 4096})
    path.write_bytes(path.read_bytes()[:-10])
    assert mc.open_container(path) is None
    # Foreign / empty files: None, not an exception.
    path.write_bytes(b"not a container at all")
    assert mc.open_container(path) is None
    path.write_bytes(b"")
    assert mc.open_container(path) is None


def test_deterministic_build(tmp_path):
    assets = {"z.bin": b"zz", "a.bin": b"aa"}
    p1, p2 = tmp_path / "1.dat", tmp_path / "2.dat"
    mc.write_container(p1, assets)
    mc.write_container(p2, dict(reversed(list(assets.items()))))
    assert p1.read_bytes() == p2.read_bytes()


# ---------------------------------------------------------------------------
# Resolution layer
# ---------------------------------------------------------------------------
def test_container_answers_when_no_loose_file_exists(tmp_path):
    _build(tmp_path)
    assert not (g.branding_root() / "marks" / "mark_4.png").exists()
    assert g._branding_exists("marks/mark_4.png")
    assert g._branding_bytes("marks/mark_4.png") == PNG_1PX


def test_loose_file_always_wins(tmp_path):
    _build(tmp_path)
    loose = g.branding_root() / "marks" / "mark_4.png"
    loose.parent.mkdir(parents=True, exist_ok=True)
    loose.write_bytes(b"LOOSE WINS")
    assert g._branding_bytes("marks/mark_4.png") == b"LOOSE WINS"


def test_no_container_no_loose_means_absent(tmp_path):
    assert g._branding_bytes("marks/mark_4.png") is None
    assert not g._branding_exists("marks/mark_4.png")


def test_container_swap_is_picked_up_without_restart(tmp_path):
    """The reader cache keys on (path, mtime): replacing moonglade.dat -- the
    downloader's atomic swap -- must serve the NEW content on the next call."""
    import os
    path = _build(tmp_path)
    assert g._branding_bytes("banner.png") == PNG_1PX
    mc.write_container(path, {"banner.png": b"NEW CONTENT"})
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 5))
    assert g._branding_bytes("banner.png") == b"NEW CONTENT"


def test_list_marks_reads_from_the_container(tmp_path):
    _build(tmp_path)
    marks = {m["id"]: m for m in g.list_marks(tmp_path)}
    assert set(marks) == {"mark_4", "mark_12"}
    assert marks["mark_4"]["png"] == "/branding/marks/mark_4.png"


def test_list_slot_assets_reads_from_the_container(tmp_path):
    _build(tmp_path)
    items = g.list_slot_assets(tmp_path, "banner_main")
    assert [i["id"] for i in items] == ["deadbeef"]


def test_seed_promotes_shipped_manifest_before_first_write(tmp_path):
    """add_custom_mark on a container-dressed install must NOT shadow the
    shipped defaults out of the picker: the container manifest is promoted
    loose first, then the upload appends to it."""
    _build(tmp_path)
    added = g.add_custom_mark(tmp_path, PNG_1PX, "My Mark")
    ids = {m["id"] for m in g.list_marks(tmp_path)}
    assert added["id"] in ids
    assert {"mark_4", "mark_12"} <= ids, (
        "shipped defaults vanished after a custom upload -- the loose manifest "
        "was not seeded from the container before the read-modify-write")


def test_write_banner_flat_renders_a_container_sourced_active_asset(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    import io
    # A realistically-shaped source: the 4:1 banner window math needs real
    # pixels to crop (a 1px fixture produces an empty crop box and fails soft).
    buf = io.BytesIO()
    Image.new("RGB", (400, 100), (90, 60, 140)).save(buf, format="PNG")
    _build(tmp_path, assets={
        "banner_main/manifest.json": json.dumps(
            {"items": [{"id": "deadbeef", "zoom": 100, "cropX": 50, "cropY": 50}]}).encode(),
        "banner_main/deadbeef.png": buf.getvalue(),
    })
    assert g._write_banner_flat(tmp_path, "banner_main") is True
    assert (g.branding_root() / "banner.png").is_file(), (
        "the rendered flat must be a REAL loose file (derived per-install state)")


# ---------------------------------------------------------------------------
# The discovery mechanic must not false-fire off shipped defaults
# ---------------------------------------------------------------------------
def test_container_alone_never_earns_the_discovery_flag(tmp_path):
    """A fresh install with ONLY the container (zero loose marks) must not set
    branding_custom_file -- the exact regression adversarial review caught in
    the previous attempt, now guarded from day one."""
    _build(tmp_path)
    g.set_telemetry_out(tmp_path)
    g.sweep_telemetry(tmp_path)
    t = g.load_telemetry(tmp_path)
    assert not (t.get("flags") or {}).get("branding_custom_file"), (
        "the sealed container alone earned the discovery flag with zero user action")


def test_a_real_loose_mark_still_earns_the_discovery_flag(tmp_path):
    """...and the guard must not overcorrect: an actual on-disk mark (manifest
    entry + loose png) still fires the flag exactly as before."""
    _build(tmp_path)
    mdir = g.branding_root() / "marks"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "marks.json").write_text(json.dumps(
        {"marks": [{"id": "dropped", "label": "dropped", "kind": "tile"}]}))
    (mdir / "dropped.png").write_bytes(PNG_1PX)
    g.set_telemetry_out(tmp_path)
    g.sweep_telemetry(tmp_path)
    t = g.load_telemetry(tmp_path)
    assert (t.get("flags") or {}).get("branding_custom_file"), (
        "a genuine loose mark no longer earns the flag -- the guard overcorrected")


# ---------------------------------------------------------------------------
# Live route, WSGI client
# ---------------------------------------------------------------------------
def test_branding_route_serves_container_assets(tmp_path):
    _build(tmp_path)
    client = login_client(tmp_path)
    r = client.get("/branding/marks/mark_4.png")
    assert r.status_code == 200
    assert r.data == PNG_1PX
    assert r.mimetype == "image/png"
    assert client.get("/branding/definitely-missing.png").status_code == 404


def test_branding_route_loose_still_wins_over_container(tmp_path):
    _build(tmp_path)
    loose = g.branding_root() / "banner.png"
    loose.parent.mkdir(parents=True, exist_ok=True)
    loose.write_bytes(b"LOOSE BANNER")
    client = login_client(tmp_path)
    r = client.get("/branding/banner.png")
    assert r.status_code == 200 and r.data == b"LOOSE BANNER"


def test_branding_route_traversal_still_rejected(tmp_path):
    _build(tmp_path)
    client = login_client(tmp_path)
    r = client.get("/branding/..%2fconfig.json")
    assert r.status_code in (404, 400)
