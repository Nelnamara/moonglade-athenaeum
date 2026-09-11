"""The coded goods tree's standing rules, as ruled by the owner on 2026-09-10
and refined 2026-09-11.

1. THE SCAN IS WIDE, ADOPTION IS NARROW. Any readable image in ANY subfolder
   under the coded root, at any depth to the walk cap, raises the
   branding_custom_file telemetry flag -- as long as this install's BASELINE
   does not already account for it. Only the four adopt folders (the three
   banner slots + marks) ever consume a file; everywhere else the sweep is
   strictly read-only -- never unlink, rename, re-encode, move or register.
2. A DEFAULT IS NOT A FIND, AND THE BASELINE IS WHAT SAYS SO. The first scan an
   install ever runs records what is already on disk (coded rel + size + a hash
   of the first 64 KiB) and reports nothing. From then on a file counts when its
   rel is new, or when the bytes at a recorded rel changed -- which is the
   owner's own loose-wins override. The container is not consulted in either
   direction: as a negative it fails OPEN on a pack-less install and CLOSED on
   that override, so behaviour must be identical with a pack and without one.
3. THE ROOT IS INERT. The rendered banner flats moved OUT of the tree into the
   app cache (g.banner_cache_dir(), the badge-thumb precedent), so the coded
   root holds nothing the app wrote. A file parked there is neither counted nor
   served, and startup MOVES (never deletes) an existing root render into the
   cache.
4. A RENDER CARRIES ITS PROVENANCE. Every flat in the cache has a sidecar record
   naming its source -- 'slot' (a pick + transform), 'earned' (sealed bytes) or
   'migrated' (moved in from an old root). Only a 'slot' render whose pick moved
   is ever regenerated, only at startup or on an explicit user action, and never
   on the public request path.

Every on-disk seed below is BUILT from the ROLE_CODE map via g._role_dir() /
g._role_rel() -- never a retyped hex literal, the rule tests/test_goods_map.py
already established. All hermetic: conftest's _isolated_branding redirects
branding_root() into tmp_path, and the banner cache derives from out_dir
(tmp_path) exactly as badge_cache_dir() does."""
import io
import json
import os
import time

import pytest

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


def _no_container(tmp_path):
    """Strip the moonglade.dat conftest seeds for the sealed roster, so the test
    runs against an install that genuinely has no pack. Behaviour must be
    identical either way -- that is the point of the baseline."""
    try:
        g._container_path().unlink()
    except OSError:
        pass
    g._container_cache.update(path=None, mtime=None, box=None)
    assert g._get_container() is None


def _age(root, seconds=60):
    """Push every file under `root` far enough into the past to clear the scan's
    settle window (g._BASELINE_SETTLE_NS).

    A file written moments ago is deliberately NEVER memoised as clean: Windows'
    file-time clock ticks about every 15 ms, so a file overwritten within the
    same tick as the one that was hashed can carry an identical size and mtime.
    Anything asserting on the memo therefore has to age its fixtures first --
    which is the rule itself, stated in a test's own terms."""
    old = time.time() - seconds
    for p in root.rglob("*"):
        if p.is_file():
            os.utime(p, (old, old))


def _settle(tmp_path):
    """Let this install take its baseline the way its first real scan does, and
    assert nothing was earned doing it.

    Every "a drop counts" test below calls this FIRST, because that ordering IS
    the rule: art already on disk when the baseline is taken is part of the
    baseline, so an install that upgrades into this build can never self-earn
    off what an older build left behind. Art that arrives afterwards is a
    genuine difference and counts."""
    assert g.sweep_branding_drops(tmp_path) is False
    assert not _flag(tmp_path), "the baseline pass must earn nothing"


# ---------------------------------------------------------------------------
# 1. Wide, read-only scanning
# ---------------------------------------------------------------------------

def test_a_drop_in_the_mascots_folder_raises_the_flag_and_is_untouched(tmp_path):
    """mascots/ is the folder the 2026-08-05 near-miss was about: it holds
    role-bound files real code reads by exact filename, so the sweep must never
    consume one. It is now READ, and reading is not adopting."""
    _settle(tmp_path)
    d = _mkdir(g._role_dir("mascots"))
    raw = _png_bytes()
    (d / "my_nel.png").write_bytes(raw)

    assert g.sweep_branding_drops(tmp_path) is False, "nothing outside the four folders adopts"
    assert _flag(tmp_path) == 1
    # byte-for-byte, same name, and no manifest conjured alongside it
    assert (d / "my_nel.png").read_bytes() == raw
    assert sorted(p.name for p in d.iterdir()) == ["my_nel.png"]


def test_a_drop_in_the_rewards_folder_raises_the_flag_and_is_untouched(tmp_path):
    """rewards/ is the other half of that near-miss, and it is achievement data
    rather than a customization bucket -- so it gets its own pin rather than
    riding on mascots'."""
    _settle(tmp_path)
    d = _mkdir(g._role_dir("rewards"))
    raw = _png_bytes((20, 20, 200))
    (d / "my_prize.png").write_bytes(raw)

    assert g.sweep_branding_drops(tmp_path) is False
    assert _flag(tmp_path) == 1
    assert (d / "my_prize.png").read_bytes() == raw
    assert sorted(p.name for p in d.iterdir()) == ["my_prize.png"]


def test_a_drop_in_a_user_made_nested_folder_raises_the_flag_and_is_untouched(tmp_path):
    """The walk is general, not a list of known folders: a tinkerer who invents
    their own nesting is exactly the person this is for."""
    _settle(tmp_path)
    d = _mkdir(g.branding_root() / "my stuff" / "deeper")
    raw = _png_bytes((10, 200, 10))
    (d / "art.png").write_bytes(raw)

    assert g.sweep_branding_drops(tmp_path) is False
    assert _flag(tmp_path) == 1
    assert (d / "art.png").read_bytes() == raw


def test_the_walk_cap_bounds_the_scan_in_both_directions(tmp_path):
    """The depth cap is a real boundary, and it has to be the SAME boundary for
    the baseline and the scan -- a file the scan can reach but the baseline
    never recorded would count as new forever.

    Depth is counted in folder segments below the coded root: a file at the cap
    is inside, one folder deeper is outside and is invisible to both halves."""
    cap = g._BRANDING_WALK_MAX_DEPTH
    at_cap = _mkdir(g.branding_root().joinpath(*["d%d" % i for i in range(cap)]))
    beyond = _mkdir(at_cap / "toodeep")
    (beyond / "hidden.png").write_bytes(_png_bytes((5, 5, 5)))

    _settle(tmp_path)
    assert g._branding_tree_has_new_art(tmp_path) is False, \
        "a file past the cap is outside the tree's vocabulary, not a find"

    (at_cap / "found.png").write_bytes(_png_bytes((250, 5, 5)))
    assert g._branding_tree_has_new_art(tmp_path) is True, \
        "a file AT the cap is inside it"


def test_a_text_file_anywhere_does_not_raise_the_flag(tmp_path):
    """_is_readable_image is the gate. A note-to-self written into the tree
    AFTER the baseline is a real difference and still must not count -- the rule
    is "a readable image", not "anything new"."""
    _settle(tmp_path)
    _mkdir(g._role_dir("rewards"))
    (g._role_dir("rewards") / "notes.txt").write_text("todo: draw something", encoding="utf-8")
    _mkdir(g.branding_root() / "scratch")
    (g.branding_root() / "scratch" / "plan.txt").write_text("later", encoding="utf-8")
    _mkdir(g._role_dir("breadcrumb"))
    (g._role_dir("breadcrumb") / "README.txt").write_text("hint", encoding="utf-8")

    assert g.sweep_branding_drops(tmp_path) is False
    assert not _flag(tmp_path)
    # ...and a .txt whose bytes later change at a path the baseline DOES hold is
    # still not an image, so the override rule cannot smuggle one in either.
    _settle(tmp_path)
    (g._role_dir("rewards") / "notes.txt").write_text("todo: draw two things",
                                                     encoding="utf-8")
    assert g._branding_tree_has_new_art(tmp_path) is False


def test_a_file_at_the_coded_root_is_neither_counted_nor_served(tmp_path):
    """The FOLDERS are the mechanic. The root holds nothing the app wrote, so a
    file parked at its top level is not counted and not an asset."""
    cli = _public_client(tmp_path)
    _settle(tmp_path)
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
# Every regression this has ever had is the same one: something that was always
# on disk gets counted as somebody's own drop. Scanning the whole tree widens
# that risk to every file the app or an older build ever put there, and the
# baseline is the single answer to all of it -- so the pins below are written
# against the SHAPES that used to break it, not against a list of excluded
# paths.
# ---------------------------------------------------------------------------

def test_a_tombstoned_shipped_mark_left_loose_is_not_a_find(tmp_path):
    """mark_12 (Gem Tome, delisted 2026-07-23) and mark_74 (renamed by
    bundle-v2) sit loose on every install that predates their delisting. The
    adopt path has treated a tombstoned stem as KNOWN since the 2026-08-13 live
    incident on the owner's own machine; the scan has to hold the same line, or
    delisting a default silently earns for everyone who upgrades."""
    mdir = _mkdir(g._role_dir("marks"))
    for stem in sorted(g._MARK_TOMBSTONES):
        (mdir / (stem + ".png")).write_bytes(_png_bytes())

    assert g.sweep_branding_drops(tmp_path) is False
    assert g.sweep_branding_drops(tmp_path) is False   # past the baseline pass
    assert not _flag(tmp_path), "a delisted shipped default earned the flag"
    for stem in sorted(g._MARK_TOMBSTONES):
        assert (mdir / (stem + ".png")).is_file()


@pytest.mark.parametrize("with_container", [True, False])
def test_shipped_art_the_legacy_migration_left_loose_is_not_a_find(tmp_path, with_container):
    """_migrate_legacy_branding_root() moves a pre-coded-tree install's whole
    role tree into the coded dirs -- marks, mascots, rewards, the system chrome.
    Every one of those files is the APP's, and every one lands at depth>0 where
    the walk looks.

    Run BOTH ways on purpose. The previous mechanism dismissed a candidate by
    asking the shipped pack "did you ship this?", which answers nothing at all
    on an install that has no pack -- so a legacy install with no moonglade.dat
    self-earned off art it had been carrying for months. The baseline asks a
    question the pack is not party to, so the two runs must agree exactly."""
    manifest = json.dumps(
        {"marks": [{"id": "mark_4", "label": "Crescent", "kind": "tile"}]}).encode()
    loose = {
        # marks.json travels with the art: the legacy migration moves the whole
        # role folder, so a mark the old tree listed is still listed after it.
        # (Without it mark_4.png is an unknown stem in an ADOPT folder and the
        # sweep consumes it -- a different rule, pinned by its own tests.)
        g._role_rel("marks", "marks.json"): manifest,
        g._role_rel("marks", "mark_4.png"): _png_bytes(),
        g._role_rel("mascots", "nel_narrator.png"): _png_bytes((9, 9, 9)),
        g._role_rel("rewards", "reward_1.png"): _png_bytes((8, 8, 8)),
        g._role_rel("badges", "first-light.png"): _png_bytes((7, 7, 7)),
    }
    if with_container:
        _build_box(tmp_path, dict(loose))
    else:
        _no_container(tmp_path)
    for rel, raw in loose.items():
        p = g.branding_root() / rel
        _mkdir(p.parent)
        p.write_bytes(raw)

    assert g.sweep_branding_drops(tmp_path) is False
    assert g.sweep_branding_drops(tmp_path) is False   # past the baseline pass
    assert not _flag(tmp_path), "the app's own shipped art earned the flag"

    # ...and the owner's actual drop, right beside it, still does.
    (g._role_dir("mascots") / "my_own_nel.png").write_bytes(_png_bytes((1, 250, 1)))
    assert g.sweep_branding_drops(tmp_path) is False
    assert _flag(tmp_path) == 1


@pytest.mark.parametrize("with_container", [True, False])
def test_the_owners_override_of_a_shipped_asset_counts(tmp_path, with_container):
    """The loose-wins override: the owner drops HIS art under a shipped asset's
    exact filename, so the tree now serves his bytes instead of the pack's. That
    is a customization and it counts -- which is the half the old
    "does the pack ship this name?" test got backwards, since the name is still
    the pack's. Only the BYTES can tell the two apart, which is why the baseline
    fingerprints them."""
    rel = g._role_rel("mascots", "nel_narrator.png")
    shipped = _png_bytes((9, 9, 9))
    if with_container:
        _build_box(tmp_path, {rel: shipped})
    else:
        _no_container(tmp_path)
    p = g.branding_root() / rel
    _mkdir(p.parent)
    p.write_bytes(shipped)

    _settle(tmp_path)

    mine = _png_bytes((250, 250, 1), w=81, h=21)     # his own art, same filename
    assert mine != shipped
    p.write_bytes(mine)
    assert g.sweep_branding_drops(tmp_path) is False
    assert _flag(tmp_path) == 1, "the owner's own override read as a shipped default"
    assert p.read_bytes() == mine, "and it is left exactly as he wrote it"


def _same_size_pngs():
    """Two DIFFERENT PNGs of identical byte length. compress_level=0 stores the
    pixel data raw, so the encoded length depends only on the dimensions -- the
    only way to be sure this fixture keeps exercising the same-size case rather
    than passing because zlib happened to agree."""
    from PIL import Image
    out = []
    for color in ((10, 10, 10), (240, 10, 10)):
        buf = io.BytesIO()
        Image.new("RGB", (64, 16), color).save(buf, format="PNG", compress_level=0)
        out.append(buf.getvalue())
    return out


def test_a_same_size_override_still_counts(tmp_path):
    """...including when the replacement happens to be the same length. A size
    compare alone would call this unchanged, which is why the fingerprint hashes
    the head of the file as well."""
    rel = g._role_rel("rewards", "reward_1.png")
    a, b = _same_size_pngs()
    assert len(a) == len(b) and a != b, "fixture no longer exercises the same-size case"
    p = g.branding_root() / rel
    _mkdir(p.parent)
    p.write_bytes(a)

    _settle(tmp_path)
    p.write_bytes(b)
    assert g._branding_tree_has_new_art(tmp_path) is True


def test_a_second_app_folder_against_the_same_library_is_not_a_find(tmp_path, monkeypatch):
    """The snapshot lives in the LIBRARY; the tree it describes does not.

    branding_root() is the app folder beside the launcher, out_dir is whatever
    library the app was pointed at, and the two move independently -- that split
    is the whole reason branding_root() left out_dir in 2026-07-26. So a
    snapshot stored under one shared key would describe whichever app folder
    happened to look first: launch a second checkout (the D: run-copy, a
    worktree, a branch being tried live) against the same library and every file
    in ITS tree is absent from that record, every file reads as new, and the
    flag fires on the first fetch with nobody having touched anything. The key
    carries the pairing, so a tree is only ever compared against a snapshot of
    itself."""
    _seed_catalog(tmp_path)
    shipped = _png_bytes((9, 9, 9))
    first = _mkdir(g._role_dir("mascots"))
    (first / "nel_narrator.png").write_bytes(shipped)
    _settle(tmp_path)                               # app folder A takes its snapshot

    second = tmp_path / "second_checkout"
    monkeypatch.setattr(g, "branding_root", lambda: second / "branding")
    other = _mkdir(g._role_dir("mascots"))
    (other / "nel_narrator.png").write_bytes(shipped)
    (other / "nel_dressed.png").write_bytes(_png_bytes((8, 8, 8)))

    assert g.sweep_branding_drops(tmp_path) is False
    assert not _flag(tmp_path), \
        "a second app folder's own shipped art self-earned the feat off the first's snapshot"

    # ...and the second folder has a real baseline of its OWN, so a real drop
    # into it still counts.
    (other / "mine.png").write_bytes(_png_bytes((1, 250, 1)))
    assert g.sweep_branding_drops(tmp_path) is False
    assert _flag(tmp_path) == 1, "the second app folder's baseline swallowed a genuine drop"


def test_a_settled_tree_is_not_rehashed_on_every_fetch(tmp_path, monkeypatch):
    """What the scan COSTS, pinned, because it runs on every /api/achievements
    fetch until the flag is set.

    Deciding "same path, same bytes" needs the bytes, and an untouched baseline
    file is same-size by definition -- so a full comparison reads and hashes a
    head of every file in the tree, and an install that upgraded through the
    bundle-v2 move carries a whole legacy _thumbs cache of them. Once a file has
    been compared and found to be a default, a later scan that finds the same
    (rel, size, mtime) skips it: the first scan of a process pays the reads, the
    rest pay the walk's own stats."""
    _seed_catalog(tmp_path)
    mdir = _mkdir(g._role_dir("mascots"))
    for n in range(3):
        (mdir / ("shipped_%d.png" % n)).write_bytes(_png_bytes((10, 200, 10), w=80 + n))
    _age(g.branding_root())
    _settle(tmp_path)                               # the snapshot pass
    assert g.sweep_branding_drops(tmp_path) is False  # the first real comparison: reads

    reads = []
    real = g._file_fingerprint
    monkeypatch.setattr(g, "_file_fingerprint",
                        lambda p: (reads.append(str(p)), real(p))[1])
    assert g.sweep_branding_drops(tmp_path) is False
    assert reads == [], "a settled tree was read and hashed again on a later fetch"

    # ...and the memo is not a blindfold: a drop still counts on the next fetch.
    (mdir / "mine.png").write_bytes(_png_bytes((1, 250, 1)))
    assert g.sweep_branding_drops(tmp_path) is False
    assert _flag(tmp_path) == 1, "the memo hid a genuine drop"


def test_a_freshly_written_file_is_compared_again_rather_than_memoised(tmp_path, monkeypatch):
    """The memo trusts an mtime, so it refuses a fresh one.

    Windows' file-time clock ticks about every 15 ms; two writes inside one tick
    can share an mtime to the nanosecond, so a same-size overwrite of a file
    hashed moments earlier would otherwise be waved through as "already
    compared". Anything written within the settle window is left out of the memo
    and compared again -- which is what keeps the override case (same name, same
    length, different bytes) counting no matter how fast it follows the scan."""
    a, b = _same_size_pngs()
    assert len(a) == len(b) and a != b, "fixture no longer exercises the same-size case"
    p = g.branding_root() / g._role_rel("rewards", "reward_1.png")
    _mkdir(p.parent)
    p.write_bytes(a)

    _settle(tmp_path)
    assert g._branding_tree_has_new_art(tmp_path) is False   # the first real comparison

    reads = []
    real = g._file_fingerprint
    monkeypatch.setattr(g, "_file_fingerprint",
                        lambda q: (reads.append(str(q)), real(q))[1])
    assert g._branding_tree_has_new_art(tmp_path) is False
    assert reads, "a file written moments ago was memoised on its mtime"

    p.write_bytes(b)                                # same name, same length, his bytes
    assert g._branding_tree_has_new_art(tmp_path) is True


def test_a_stale_legacy_badge_thumb_cache_is_not_a_find(tmp_path):
    """The badge-thumb cache lived INSIDE the tree (`_thumbs/<aid>.png`) until
    bundle-v2 moved it to badge_cache_dir(), and nothing deletes the old one --
    so every install that upgraded through that move carries a folder of
    app-rendered PNGs exactly where the wide walk looks. The container can never
    name them (tools/build_container.py excludes `_thumbs` at ANY depth), so it
    was no help; the baseline needs no special case for them at all, dressed or
    bare."""
    top = _mkdir(g.branding_root() / g._LEGACY_THUMB_DIR)
    (top / "first-light.png").write_bytes(_png_bytes())
    nested = _mkdir(g._role_dir("marks") / g._LEGACY_THUMB_DIR)
    (nested / "mark_4.png").write_bytes(_png_bytes((3, 3, 3)))

    _settle(tmp_path)
    assert g._branding_tree_has_new_art(tmp_path) is False
    assert not _flag(tmp_path), "the app's own regenerable badge cache earned the flag"
    # ...still so with no pack at all to ask.
    _no_container(tmp_path)
    assert g._branding_tree_has_new_art(tmp_path) is False
    # ...and a later drop in a folder of the owner's own still counts.
    d = _mkdir(g.branding_root() / "_thumbsketches")
    (d / "mine.png").write_bytes(_png_bytes((250, 1, 1)))
    assert g._branding_tree_has_new_art(tmp_path) is True


def test_system_chrome_is_not_a_find_even_with_no_container(tmp_path):
    """A bare install has no moonglade.dat to ask about anything, and the app's
    chrome (the bare-name system files the translation's rule 2 owns, the ee_*
    starfall art rule 3 owns) sits loose on any install the legacy migration
    ran against. It was on disk before anyone looked, so it is a default."""
    _no_container(tmp_path)

    sysd = _mkdir(g._role_dir("system"))
    for name in sorted(g._SYSTEM_TOP_FILES):
        if name.endswith(".ico"):
            continue                     # not an image Pillow reads; nothing to pin
        (sysd / name).write_bytes(_png_bytes())
    (_mkdir(g._role_dir("starfall")) / "ee_nelstarfall.png").write_bytes(_png_bytes())

    assert g._get_container() is None, "this install genuinely has no pack"
    assert g.sweep_branding_drops(tmp_path) is False
    assert g.sweep_branding_drops(tmp_path) is False   # past the baseline pass
    assert not _flag(tmp_path)


def test_an_upload_through_the_branding_tab_is_not_a_find(tmp_path):
    """add_slot_asset() writes `<id>.png` straight into a slot folder the walk
    reads, and it does it long AFTER the baseline was taken -- so the writer has
    to fold its own write into the baseline as it goes
    (_baseline_note_app_write). Using the Branding tab exactly as designed is
    the opposite of finding an undocumented folder."""
    _seed_catalog(tmp_path)
    _settle(tmp_path)

    asset = g.add_slot_asset(tmp_path, "banner_main", _png_bytes())
    assert asset and (g._role_dir("banner_main") / (asset["id"] + ".png")).is_file()

    assert g._branding_tree_has_new_art(tmp_path) is False, \
        "the app's own registered upload read back as somebody's find"
    assert g.sweep_branding_drops(tmp_path) is False, "a registered id is not a fresh drop"
    assert not _flag(tmp_path)


def test_a_custom_mark_upload_is_not_a_find(tmp_path):
    """add_custom_mark() writes the art AND cuts a launcher .ico beside it, both
    into the marks folder the walk reads. Pillow opens an .ico perfectly well,
    so an unrecorded one would read back as a find on the very next scan."""
    _seed_catalog(tmp_path)
    _settle(tmp_path)

    mark = g.add_custom_mark(tmp_path, _png_bytes(), label="My mark")
    assert (g._role_dir("marks") / (mark["id"] + ".png")).is_file()

    assert g._branding_tree_has_new_art(tmp_path) is False
    assert not _flag(tmp_path)


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
    # ...and it names the pick it came from, which is what everything in the
    # provenance section below hangs off.
    slot = cli.get("/api/branding").get_json()["slots"]["banner_main"]
    assert g._read_banner_record(tmp_path, "banner.png") == {
        "kind": "slot", "asset_id": slot["active"],
        "transform": {"zoom": 100, "cropX": 50, "cropY": 50}}


def test_building_the_app_never_moves_a_render_out_of_the_tree(tmp_path):
    """create_app() is what every test in this suite builds, several of them
    from module-scoped fixtures that conftest's per-test branding isolation
    cannot reach -- so a plain pytest run must never relocate a real install's
    dressed banner into a pytest tmp dir. The destructive flat migration belongs
    to main().

    Narrowly about the RENDER, because create_app() is not move-free in general:
    the scaffold it runs also runs _migrate_legacy_branding_root(), which folds a
    pre-coded-tree install's own role-named `branding/` tree into the coded dirs
    (a move, never a delete -- tests/test_goods_map.py owns that contract). That
    is the one known exception, it predates this rule, and it stays because an
    install carrying the old tree is unusable until it runs."""
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
    assert g._read_banner_record(tmp_path, "banner.png") == {"kind": "migrated"}

    g._migrate_root_banner_flats(tmp_path)     # idempotent: a no-op second time
    assert dst.read_bytes() == raw

    # A cache render already in place is the newer truth. A stale root leftover
    # never overwrites it, and is left where it is rather than deleted.
    (root / "banner.png").write_bytes(_png_bytes((1, 2, 3)))
    g._migrate_root_banner_flats(tmp_path)
    assert dst.read_bytes() == raw
    assert (root / "banner.png").is_file()


def test_a_migrated_flat_survives_the_startup_ensure_pass(tmp_path):
    """The move is only half the fix. main() migrates and then builds the app,
    whose ensure pass looks at every slot -- so without provenance the arriving
    flat reads as "a render exists, is it current?", the slot's pick wins, and
    the banner the install is actually WEARING is re-rendered away on the very
    first start after the upgrade. 'migrated' is never regenerated."""
    _seed_catalog(tmp_path)
    # A real recorded pick, so there IS something the ensure pass could render.
    g.add_slot_asset(tmp_path, "banner_main", _png_bytes((10, 200, 10)))
    dst = g.banner_cache_dir(tmp_path) / "banner.png"
    dst.unlink()
    g._banner_record_path(tmp_path, "banner.png").unlink()

    root = _mkdir(g.branding_root())
    worn = _png_bytes((7, 8, 9))
    (root / "banner.png").write_bytes(worn)
    g._migrate_root_banner_flats(tmp_path)     # what main() runs, before create_app

    create_app(tmp_path)
    assert dst.read_bytes() == worn, \
        "app startup re-rendered the slot's pick over the migrated banner"


def test_a_real_start_runs_the_root_flat_migration(tmp_path):
    """The migration's ONLY production call site is main(), and every other test
    here asserts where it must NOT run (create_app) or what it does when called
    directly. Without this, deleting the call would leave the feature dead and
    the whole file green.

    Read off main()'s own source rather than by running it -- main() parses
    argv, binds a port and blocks -- so what is pinned is the call site itself:
    present, and after the scaffold that gives a legacy install's flats a chance
    to reach the coded root within the SAME start."""
    import ast
    import inspect

    body = ast.parse(inspect.getsource(g.main))
    calls = [n.func.id for n in ast.walk(body)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "_migrate_root_banner_flats" in calls, \
        "main() no longer moves a root render into the cache -- the feature is dead"
    assert "ensure_branding_discovery_tree" in calls
    assert calls.index("ensure_branding_discovery_tree") < \
        calls.index("_migrate_root_banner_flats"), \
        "the legacy tree must be folded in BEFORE the flats are looked for"
    assert "create_app" in calls
    assert calls.index("_migrate_root_banner_flats") < calls.index("create_app"), \
        ("the migration must run BEFORE the app is built: create_app's ensure pass "
         "finds an empty cache, renders the slot pick and stamps 'slot' over it, "
         "and the migration then refuses to overwrite what is already there -- "
         "stranding the banner the upgrading install is actually wearing at the "
         "now-inert coded root")


def test_an_absent_cache_render_is_rebuilt_at_startup_not_defaulted(tmp_path):
    """banner_cache_dir() hangs off out_dir (the LIBRARY) while the pick that
    produces a render hangs off the app folder (branding_slots.json), so an
    absent render has to be rebuilt from the pick or pointing the app at a
    second library would wear the shipped default while the owner's real pick
    sat recorded -- the coupling branding_root() left out_dir to kill.

    The rebuild happens at STARTUP, not on the request path: /branding/<flat> is
    PUBLIC tier, and an anonymous GET must not be able to schedule a Pillow
    decode-crop-resize-save."""
    cli = _client(tmp_path)
    r = cli.post("/api/branding/slot",
                 data={"slot": "banner_main", "file": (io.BytesIO(_png_bytes()), "b.png")},
                 content_type="multipart/form-data")
    assert r.status_code == 200
    flat = g.banner_cache_dir(tmp_path) / "banner.png"
    mine = flat.read_bytes()

    _build_box(tmp_path, {g._role_rel("banner_main", "banner_main.png"): b"SHIPPED MAIN"})
    flat.unlink()                                   # a library this install never rendered into
    g._banner_record_path(tmp_path, "banner.png").unlink()

    create_app(tmp_path)                            # the next start
    assert flat.is_file(), "startup did not rebuild an absent render from the pick"
    assert flat.read_bytes() == mine, \
        "an absent render fell back to the shipped default instead of rebuilding the pick"


def test_the_public_flat_route_only_serves(tmp_path):
    """The route is a lookup, in both directions: it must not render an absent
    flat, and it must not write anything into the cache."""
    cli = _public_client(tmp_path)
    _build_box(tmp_path, {g._role_rel("banner_main", "banner_main.png"): b"SHIPPED MAIN"})
    # A real recorded pick with NO render in the cache: the only thing that
    # could produce one here is the request itself.
    g.add_slot_asset(tmp_path, "banner_main", _png_bytes())
    cdir = g.banner_cache_dir(tmp_path)
    (cdir / "banner.png").unlink()
    g._banner_record_path(tmp_path, "banner.png").unlink()

    r = cli.get("/branding/banner.png")
    assert r.status_code == 200 and r.data == b"SHIPPED MAIN", \
        "the request path rendered instead of falling through to rule 8"
    assert not (cdir / "banner.png").exists(), "a public GET wrote into the render cache"


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
# 2b. A render carries its provenance
#
# The cache used to decide staleness by MTIME against the SHARED
# branding_slots.json, which is not a provenance at all: any slot's change made
# every slot's flat look stale, and an applied earned banner was silently
# re-rendered back to banner_main's slot pick on the next request. The record
# beside each render is what replaced that.
# ---------------------------------------------------------------------------

def test_one_slots_change_does_not_regenerate_another_slots_render(tmp_path):
    """branding_slots.json holds all three picks, so its mtime says nothing
    about WHICH slot moved. The record does: only the slot whose own pick or
    transform changed is re-rendered."""
    _seed_catalog(tmp_path)
    g.add_slot_asset(tmp_path, "banner_main", _png_bytes((10, 200, 10)))
    g.add_slot_asset(tmp_path, "banner_login", _png_bytes((200, 10, 10)))
    login_flat = g.banner_cache_dir(tmp_path) / "login-banner.png"
    before = login_flat.read_bytes()
    before_mtime = login_flat.stat().st_mtime_ns

    # A second banner_main upload rewrites the shared pick file...
    g.add_slot_asset(tmp_path, "banner_main", _png_bytes((10, 10, 200)))
    create_app(tmp_path)                            # ...and a start after it

    assert login_flat.read_bytes() == before
    assert login_flat.stat().st_mtime_ns == before_mtime, \
        "banner_login's render was rewritten because ANOTHER slot's pick moved"


def test_an_applied_earned_banner_is_never_reverted_by_the_ensure_pass(tmp_path):
    """The earned banner is rendered from sealed bytes with no slot pick behind
    it. Startup must leave it alone however many slot picks are recorded, or
    applying one is undone by the next restart."""
    _seed_catalog(tmp_path)
    g.add_slot_asset(tmp_path, "banner_main", _png_bytes((10, 200, 10)))
    flat = g.banner_cache_dir(tmp_path) / "banner.png"

    assert g._render_banner_flat(tmp_path, "banner_main", _png_bytes((1, 1, 250)),
                                 record={"kind": "earned",
                                         "banner_id": "great_library"}) is True
    applied = flat.read_bytes()

    create_app(tmp_path)
    g._ensure_banner_renders(tmp_path)              # and again, directly
    assert flat.read_bytes() == applied, "the ensure pass reverted an applied earned banner"
    assert g._read_banner_record(tmp_path, "banner.png")["kind"] == "earned"


@pytest.mark.parametrize("record", [
    {"kind": "earned", "banner_id": "great_library"},
    {"kind": "migrated"},
])
def test_a_render_that_goes_missing_never_costs_its_provenance(tmp_path, record):
    """A render and its record can part company -- a selective cache cleanup, a
    png quarantined by a virus scanner, a library copied while it was being
    written. Reading the record only when the png is PRESENT makes that a silent
    revert: the ensure pass sees "no render", calls the slot renderer, and the
    renderer stamps its own {"kind": "slot"} over the record on the way past. An
    applied earned banner would come back as the slot pick on the next restart,
    and a migrated flat -- which may have nothing left to re-render from -- would
    lose the only thing saying so.

    So the record is read first, and 'earned'/'migrated' is left alone whether
    its bytes are there or not. A missing render is reported missing and the
    route falls through to the container copy and the sealed default, which the
    owner can undo; an overwritten record he cannot."""
    _seed_catalog(tmp_path)
    pick = g.add_slot_asset(tmp_path, "banner_main", _png_bytes((10, 200, 10)))
    flat = g.banner_cache_dir(tmp_path) / "banner.png"
    assert g._render_banner_flat(tmp_path, "banner_main", _png_bytes((1, 1, 250)),
                                 record=dict(record)) is True

    flat.unlink()                                   # the png alone goes missing
    assert g._banner_record_path(tmp_path, "banner.png").is_file()

    assert g._ensure_banner_flat(tmp_path, "banner_main") is None
    create_app(tmp_path)                            # and a whole start over it

    assert g._read_banner_record(tmp_path, "banner.png") == record, \
        "the slot renderer overwrote a record it does not own"
    assert not flat.exists(), \
        "the ensure pass rendered the slot pick into a flat that was not its own"
    assert pick["id"]                               # there WAS a pick to render, and it did not


def test_a_slot_render_regenerates_when_its_own_pick_moves(tmp_path):
    """...and the other direction: 'slot' is the ONE kind the ensure pass does
    redo, so a pick recorded while the render could not be written still catches
    up on the next start."""
    _seed_catalog(tmp_path)
    first = g.add_slot_asset(tmp_path, "banner_main", _png_bytes((10, 200, 10)))
    second = g.add_slot_asset(tmp_path, "banner_main", _png_bytes((200, 10, 10)))
    flat = g.banner_cache_dir(tmp_path) / "banner.png"

    # Rewind the cache to the FIRST pick while the recorded pick is the second:
    # exactly the state a failed render leaves behind.
    assert g._render_banner_flat(
        tmp_path, "banner_main", _png_bytes((10, 200, 10)),
        record={"kind": "slot", "asset_id": first["id"],
                "transform": {"zoom": 100, "cropX": 50, "cropY": 50}}) is True

    create_app(tmp_path)
    rec = g._read_banner_record(tmp_path, "banner.png")
    assert rec["asset_id"] == second["id"], "a stale slot render was not brought up to date"
    from PIL import Image
    with Image.open(flat) as im:
        assert im.convert("RGB").getpixel((0, 0)) == (200, 10, 10)


def test_a_render_with_no_record_is_left_alone(tmp_path):
    """A render this build cannot account for -- an older build's cache, a
    record that failed to write -- is opaque, and opaque means untouched. The
    file is what the install is wearing; nothing here knows better."""
    _seed_catalog(tmp_path)
    g.add_slot_asset(tmp_path, "banner_main", _png_bytes((10, 200, 10)))
    flat = g.banner_cache_dir(tmp_path) / "banner.png"
    g._banner_record_path(tmp_path, "banner.png").unlink()
    flat.write_bytes(b"SOMETHING OLDER")

    create_app(tmp_path)
    assert flat.read_bytes() == b"SOMETHING OLDER"


# ---------------------------------------------------------------------------
# 3. The once-a-day backstop asks the same question
# ---------------------------------------------------------------------------

def test_the_daily_backstop_uses_the_same_baseline_scan(tmp_path):
    """sweep_telemetry() is a BACKSTOP, not a second opinion. It used to apply a
    narrower rule of its own (a loose marks.json entry with loose art), which
    could contradict the wide scan in both directions -- blind to a drop outside
    the marks folder, and firing on a registered mark the scan had already
    accepted as a default. One function, two callers.

    Also pins the .webp lane end to end: a mark the owner authors as an animated
    .webp is art like any other, and the backstop sees it."""
    mdir = _mkdir(g._role_dir("marks"))
    (mdir / "marks.json").write_text(json.dumps(
        {"marks": [{"id": "animated", "label": "animated", "kind": "tile"}]}),
        encoding="utf-8")
    g.sweep_telemetry(tmp_path)                     # the baseline pass
    assert not _flag(tmp_path), "a manifest entry with no art is not art"

    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), (200, 30, 30)).save(buf, format="WEBP")
    (mdir / "animated.webp").write_bytes(buf.getvalue())
    g.sweep_telemetry(tmp_path)
    assert _flag(tmp_path) == 1, "the backstop missed a .webp mark"


def test_the_daily_backstop_sees_a_drop_outside_the_marks_folder(tmp_path):
    """The half the old narrow rule could not see at all."""
    _mkdir(g._role_dir("mascots"))
    g.sweep_telemetry(tmp_path)                     # the baseline pass
    assert not _flag(tmp_path)

    (g._role_dir("mascots") / "mine.png").write_bytes(_png_bytes((1, 250, 1)))
    g.sweep_telemetry(tmp_path)
    assert _flag(tmp_path) == 1
