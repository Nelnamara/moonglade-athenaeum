"""The bundle-v2 "goods" rewire: the ROLE_CODE map, the one-shot public->coded
translation (_public_rel_to_coded), the seal table judged on CODED rels, the
flat-default fallback, the legacy-root migration, the gated earned-banner pick,
and the GONK breadcrumb (SCOPE_bundle-v2-contract.md).

Every on-disk seed / container key below is BUILT from the map via
g._role_rel()/g._role_dir() -- never a retyped hex literal. A hardcoded coded
prefix in a test recreates exactly the scatter the map exists to remove, and
(worse) would keep passing if the map and a test drifted apart together.

All hermetic: conftest's _isolated_branding redirects branding_root() to
tmp_path, so every fake asset and container lives and dies with its test. The
migration tests re-point branding_root() themselves -- under the conftest
redirect the legacy root (branding_root().parent/"branding") would otherwise
COINCIDE with the coded root."""
import io
import json

import pytest

import moonglade_container as mc
import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, save_catalog

from tests.conftest import login_client

# A real (tiny) PNG so PIL-facing paths get decodable bytes.
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082")


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


@pytest.fixture(autouse=True)
def _fresh_seal_cache():
    """The earned-ids seal cache is module-global (one install per real process);
    the suite runs MANY installs per process, and a previous test's earns must
    not leak an allow into this one's fresh tmp_path."""
    g._earned_ids_cache.update(t=0.0, ids=frozenset())
    yield
    g._earned_ids_cache.update(t=0.0, ids=frozenset())


def _client(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    return login_client(tmp_path)


def _seed(rel, data=b"\x89PNG fake"):
    """A loose file at a branding_root()-relative rel (coded or not -- the
    caller decides; that decision is the thing under test here)."""
    p = g.branding_root() / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def _build_box(assets):
    """(Re)build the isolated install's moonglade.dat and drop the read cache
    so the new content is seen immediately (the cache keys on mtime, which can
    collide with the conftest seed's within the filesystem's resolution)."""
    mc.write_container(g._container_path(), assets, {})
    g._container_cache.update(path=None, mtime=None, box=None)


def _banner_png(w=400, h=100):
    """A realistically-shaped 4:1 source: the banner window math needs real
    pixels to crop (a 1px fixture produces an empty crop box and fails soft)."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (90, 60, 140)).save(buf, format="PNG")
    return buf.getvalue()


# ---- the translation, rule by rule (contract section 2) ---------------------

def test_translation_flats_pass_through():
    """Rule 1: the three banner flats stay top-level at the coded root."""
    for flat in ("banner.png", "login-banner.png", "banner-loom.png"):
        assert g._public_rel_to_coded(flat) == flat, flat


def test_translation_system_files():
    """Rule 2: the bare top-level chrome names land in the system role."""
    for name in ("logo.png", "favicon.png", "favicon.ico", "nel_spinner.png",
                 "login_nel.webp", "login_nel.png"):
        assert g._public_rel_to_coded(name) == g._role_rel("system", name), name


def test_translation_ee_prefix_is_top_level_only():
    """Rule 3: bare ee_* -> starfall; a NESTED ee_* is not this rule's business
    (an unknown-dir one falls through unmatched)."""
    assert (g._public_rel_to_coded("ee_nelstarfall.png")
            == g._role_rel("starfall", "ee_nelstarfall.png"))
    assert g._public_rel_to_coded("not_a_dir/ee_x.png") == "not_a_dir/ee_x.png"


def test_translation_bridge_family():
    """Rule 4: emotion/ peels off, preset_* files land in enhance, the rest is
    plain bridge -- the front-end asks for presets FLAT under bridge/."""
    assert (g._public_rel_to_coded("bridge/emotion/happy.png")
            == g._role_rel("emotion", "happy.png"))
    assert (g._public_rel_to_coded("bridge/preset_soft.png")
            == g._role_rel("enhance", "preset_soft.png"))
    assert (g._public_rel_to_coded("bridge/six.png")
            == g._role_rel("bridge", "six.png"))


def test_translation_mascots_split():
    """Rule 5: mascots/ach/ is its own role; the rest of mascots/ is plain."""
    assert (g._public_rel_to_coded("mascots/ach/first-light.png")
            == g._role_rel("mascots_ach", "first-light.png"))
    assert (g._public_rel_to_coded("mascots/nel_narrator.png")
            == g._role_rel("mascots", "nel_narrator.png"))


def test_translation_single_segment_roles():
    """Rule 6: each single-segment role prefix maps to its coded folder, with
    the remainder (nested or not) carried through verbatim."""
    for role in ("marks", "badges", "rewards", "mystery", "banner_main",
                 "banner_login", "banner_loom", "earned_banners"):
        assert (g._public_rel_to_coded(role + "/f.png")
                == g._role_rel(role, "f.png")), role
    assert g._public_rel_to_coded("marks/sub/f.png") == g._role_rel("marks", "sub/f.png")


def test_translation_unmatched_pass_through():
    """Rule 7: _thumbs/, sfx/ (no shipped sfx role) and anything unknown come
    back untouched."""
    for rel in ("_thumbs/x.png", "sfx/chime.mp3", "whatever.png",
                "unknown_dir/f.png"):
        assert g._public_rel_to_coded(rel) == rel, rel


def test_translation_raw_coded_paths_pass_through_and_stay_judged(monkeypatch):
    """A probe that guesses a CODED path passes through translation unchanged --
    and therefore faces the exact same seal verdict the public form would.
    Translation must never be the thing standing between a guesser and sealed
    art."""
    monkeypatch.setattr(g, "_ach_ids", lambda: frozenset({"first-light"}))
    for coded, verdict in (
            (g._role_rel("badges", "first-light.png"), ("earned", "first-light")),
            (g._role_rel("rewards", "secret.png"), ("deny", None)),
            (g._role_rel("starfall", "ee_nelstarfall.png"),
             ("earned", "the-konami-code"))):
        assert g._public_rel_to_coded(coded) == coded, coded
        assert g._seal_rule(g._public_rel_to_coded(coded)) == verdict, coded


def test_route_judges_direct_coded_probes(tmp_path, monkeypatch):
    """The live route, probed with raw CODED rels: deny stays 404 even when the
    loose file really exists, the D8 open pair serves, and sealed starfall art
    serves once (and only once) its achievement is earned -- the load-bearing
    half of the seal."""
    cli = _client(tmp_path)
    _seed(g._role_rel("rewards", "secret.png"))
    assert cli.get("/branding/" + g._role_rel("rewards", "secret.png")).status_code == 404
    _seed(g._role_rel("rewards", "claim.png"), b"CLAIM ICON")
    r = cli.get("/branding/" + g._role_rel("rewards", "claim.png"))
    assert r.status_code == 200 and r.data == b"CLAIM ICON"
    _seed(g._role_rel("starfall", "ee_nelstarfall.png"), b"STARFALL BYTES")
    monkeypatch.setattr(g, "_earned_achievement_ids", lambda *a, **k: frozenset())
    assert cli.get("/branding/" + g._role_rel("starfall", "ee_nelstarfall.png")).status_code == 404
    monkeypatch.setattr(g, "_earned_achievement_ids",
                        lambda *a, **k: frozenset({"the-konami-code"}))
    r = cli.get("/branding/" + g._role_rel("starfall", "ee_nelstarfall.png"))
    assert r.status_code == 200 and r.data == b"STARFALL BYTES"


# ---- the seal table, row by row (contract section 3) -------------------------

def test_seal_table_round_trip(monkeypatch):
    """Every row of the contract's seal table, with every prefix DERIVED from
    ROLE_CODE -- a retyped prefix is how a seal silently fails open."""
    monkeypatch.setattr(g, "_ach_ids", lambda: frozenset({"first-light"}))
    rr = g._role_rel
    cases = [
        # the D8 exception: the two reward UI icons stay open
        (rr("rewards", "claim.png"), ("open", None)),
        (rr("rewards", "gift.png"), ("open", None)),
        # ...while the rest of rewards/ (and the folder itself) denies
        (rr("rewards", "anything-else.png"), ("deny", None)),
        (g.ROLE_CODE["rewards"], ("deny", None)),
        # _thumbs is the badge-thumb cache: never served here
        ("_thumbs/x.png", ("deny", None)),
        ("_thumbs", ("deny", None)),
        # badges: known id -> earned; unknown files stay sealed
        (rr("badges", "first-light.png"), ("earned", "first-light")),
        (rr("badges", "not-an-achievement.png"), ("deny", None)),
        # mascots/ach poses: id from any extension; unknown denies
        (rr("mascots_ach", "first-light.png"), ("earned", "first-light")),
        (rr("mascots_ach", "first-light.webp"), ("earned", "first-light")),
        (rr("mascots_ach", "unknown.png"), ("deny", None)),
        # the whole starfall bucket (art, audio, AND the nested GONK crumb)
        (rr("starfall", "ee_nelstarfall.png"), ("earned", "the-konami-code")),
        (rr("starfall", "ee_chime.mp3"), ("earned", "the-konami-code")),
        (rr("breadcrumb", "README.txt"), ("earned", "the-konami-code")),
        # earned banners: great_library gated, the rest (void_banner) sealed shut
        (rr("earned_banners", "great_library.png"), ("earned", "the-great-library")),
        (rr("earned_banners", "void_banner.png"), ("deny", None)),
        (g.ROLE_CODE["earned_banners"], ("deny", None)),
        # everything else is the app's default dress: open
        (rr("mystery", "mask.png"), ("open", None)),
        (rr("system", "logo.png"), ("open", None)),
        (rr("bridge", "six.png"), ("open", None)),
        (rr("enhance", "preset_soft.png"), ("open", None)),
        (rr("emotion", "happy.png"), ("open", None)),
        (rr("marks", "mark_4.png"), ("open", None)),
        (rr("banner_main", "deadbeef.png"), ("open", None)),
        ("banner.png", ("open", None)),
    ]
    for rel, want in cases:
        assert g._seal_rule(rel) == want, rel


def test_seal_is_case_insensitive_no_leak(monkeypatch):
    """HIGH regression (adversarial review 2026-08-21): the guarded filesystem is
    case-INSENSITIVE on Windows, so the seal must be too. A case-variant of a
    sealed path must NEVER fall through to the fail-open ('open', None). The
    reported hole: GET /branding/mascots/ACH/<id> translated to A02/ACH/... and
    dodged a case-sensitive A02/ach/ prefix check, and the FS served it anyway."""
    monkeypatch.setattr(g, "_ach_ids", lambda: frozenset({"first-light"}))
    rr = g._role_rel

    # (a) the exact reported vector, end to end: public mascots/<case>/id -> seal
    for pub in ("mascots/ach/first-light.webp", "mascots/ACH/first-light.webp",
                "mascots/Ach/first-light.webp"):
        assert g._seal_rule(g._public_rel_to_coded(pub)) == ("earned", "first-light"), pub

    # (b) case-variants applied straight to the coded rel, for every sealed bucket:
    # upper-case the folder segments (mimicking a request the FS would still
    # resolve) -- none may return open.
    def upper_head(rel):
        head, _, tail = rel.rpartition("/")
        return head.upper() + "/" + tail

    sealed = [
        (rr("mascots_ach", "first-light.webp"), ("earned", "first-light")),
        (rr("badges", "first-light.png"), ("earned", "first-light")),
        (rr("rewards", "secret.png"), ("deny", None)),
        (rr("earned_banners", "great_library.png"), ("earned", "the-great-library")),
        (rr("earned_banners", "void_banner.png"), ("deny", None)),
        (rr("starfall", "ee_nelstarfall.png"), ("earned", "the-konami-code")),
    ]
    for rel, want in sealed:
        assert g._seal_rule(rel) == want, rel                     # canonical
        assert g._seal_rule(upper_head(rel)) == want, rel         # mixed-case folders
        assert g._seal_rule(rel.upper()) != ("open", None), rel   # never leaks fully-cased


# ---- the flat-default fallback (translation rule 8, a SERVING rule) ---------

def test_flats_fall_back_to_the_shipped_slot_defaults(tmp_path):
    """No loose flat rendered yet + the container carrying the slot defaults ->
    each public flat URL serves its sealed default (banner_loom's shipped
    filename is HYPHENATED -- the one the contract calls out by name)."""
    cli = _client(tmp_path)
    _build_box({
        g._role_rel("banner_main", "banner_main.png"): b"SHIPPED MAIN",
        g._role_rel("banner_login", "banner_login.png"): b"SHIPPED LOGIN",
        g._role_rel("banner_loom", "banner-loom.png"): b"SHIPPED LOOM",
    })
    for url, want in (("banner.png", b"SHIPPED MAIN"),
                      ("login-banner.png", b"SHIPPED LOGIN"),
                      ("banner-loom.png", b"SHIPPED LOOM")):
        r = cli.get("/branding/" + url)
        assert r.status_code == 200 and r.data == want, url


def test_loose_flat_wins_over_the_shipped_default(tmp_path):
    cli = _client(tmp_path)
    _build_box({g._role_rel("banner_main", "banner_main.png"): b"SHIPPED MAIN"})
    _seed("banner.png", b"LOOSE FLAT")
    r = cli.get("/branding/banner.png")
    assert r.status_code == 200 and r.data == b"LOOSE FLAT"


def test_flat_404s_when_neither_loose_nor_default_exists(tmp_path):
    cli = _client(tmp_path)
    _build_box({"unrelated.bin": b"x"})     # a container, but no slot defaults
    assert cli.get("/branding/banner.png").status_code == 404


# ---- the one-time legacy migration (contract section 5) ----------------------
#
# These re-point branding_root() at their own coded root: under conftest's
# tmp_path/"branding" redirect the LEGACY root (branding_root().parent /
# "branding") would coincide with the coded root and there'd be nothing to
# migrate FROM.

def test_migration_moves_role_dirs_and_top_level_files(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "branding_root", lambda: tmp_path / "goodsroot")
    old = tmp_path / "branding"
    seeds = {
        "banner_main/upload.png": b"MAIN UPLOAD",
        "banner_login/login.png": b"LOGIN UPLOAD",
        "marks/marks.json": b'{"marks": []}',
        "marks/custom-x.png": b"CUSTOM MARK",
        "mascots/nel_narrator.png": b"NARRATOR",
        "mascots/ach/first-light.png": b"POSE",       # the old nesting
        "rewards/claim.png": b"CLAIM",
        "banner.png": b"FLAT",                        # flat -> coded root top level
        "logo.png": b"LOGO",                          # system file -> coded home
        "ee_star.png": b"STAR",                       # konami art -> starfall
        "README.txt": b"old breadcrumb",              # unrecognized: stays put
    }
    for rel, data in seeds.items():
        p = old / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    g._migrate_legacy_branding_root()
    # every recognized file landed in its coded home, bytes intact
    assert (g._role_dir("banner_main") / "upload.png").read_bytes() == b"MAIN UPLOAD"
    assert (g._role_dir("banner_login") / "login.png").read_bytes() == b"LOGIN UPLOAD"
    assert (g._role_dir("marks") / "marks.json").read_bytes() == b'{"marks": []}'
    assert (g._role_dir("marks") / "custom-x.png").read_bytes() == b"CUSTOM MARK"
    assert (g._role_dir("mascots") / "nel_narrator.png").read_bytes() == b"NARRATOR"
    # the recursive mascots move lands the old ach/ nesting under the coded
    # ach folder (mascots_ach nests inside mascots in the map itself)
    assert (g._role_dir("mascots_ach") / "first-light.png").read_bytes() == b"POSE"
    assert (g._role_dir("rewards") / "claim.png").read_bytes() == b"CLAIM"
    assert (g.branding_root() / "banner.png").read_bytes() == b"FLAT"
    assert (g._role_dir("system") / "logo.png").read_bytes() == b"LOGO"
    assert (g._role_dir("starfall") / "ee_star.png").read_bytes() == b"STAR"
    # unrecognized stays exactly where it was; nothing was deleted anywhere
    assert (old / "README.txt").read_bytes() == b"old breadcrumb"
    all_files = [p for p in tmp_path.rglob("*") if p.is_file()
                 and p.name != "moonglade.dat"]     # the conftest roster seed
    assert sorted(p.read_bytes() for p in all_files) == sorted(seeds.values())
    # emptied role dirs are swept; the old root survives (README kept it)
    assert not (old / "banner_main").exists()
    assert not (old / "mascots").exists()
    assert old.is_dir()


def test_migration_collision_skips_source_intact_and_second_run_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "branding_root", lambda: tmp_path / "goodsroot")
    old = tmp_path / "branding"
    (old / "marks").mkdir(parents=True)
    (old / "marks" / "custom-x.png").write_bytes(b"SOURCE")
    dst = g._role_dir("marks") / "custom-x.png"
    dst.parent.mkdir(parents=True)
    dst.write_bytes(b"ALREADY THERE")
    g._migrate_legacy_branding_root()
    # destination never overwritten; the source stays put (nothing deleted)
    assert dst.read_bytes() == b"ALREADY THERE"
    assert (old / "marks" / "custom-x.png").read_bytes() == b"SOURCE"
    # a second run changes NOTHING -- same skip, same tree
    snapshot = sorted((p.relative_to(tmp_path).as_posix(), p.read_bytes())
                      for p in tmp_path.rglob("*") if p.is_file())
    g._migrate_legacy_branding_root()
    assert sorted((p.relative_to(tmp_path).as_posix(), p.read_bytes())
                  for p in tmp_path.rglob("*") if p.is_file()) == snapshot


def test_migration_is_a_noop_on_fresh_installs(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "branding_root", lambda: tmp_path / "goodsroot")
    g._migrate_legacy_branding_root()      # no old root at all: must not raise
    assert not (tmp_path / "branding").exists()
    assert not (tmp_path / "goodsroot").exists()   # doesn't invent the coded root either


# ---- the gated earned-banner pick (contract section 6) -----------------------

def test_earned_banner_pick_is_server_gated(tmp_path, monkeypatch):
    cli = _client(tmp_path)
    _build_box({g._role_rel("earned_banners", "great_library.png"): _banner_png()})
    monkeypatch.setattr(g, "_mark_earned", lambda *a, **k: False)
    # the list: one entry (void_banner deliberately absent), public role URL
    d = cli.get("/api/branding/banners/earned").get_json()
    assert d == {"banners": [{"id": "great_library",
                              "label": "The Great Library",
                              "earned": False,
                              "png": "/branding/earned_banners/great_library.png"}]}
    # locked -> 403, and no flat gets written
    r = cli.post("/api/branding/banner/earned", json={"id": "great_library"})
    assert r.status_code == 403
    assert not (g.branding_root() / "banner.png").exists()
    # unknown ids (void_banner included -- it is NOT wired) -> 400
    assert cli.post("/api/branding/banner/earned",
                    json={"id": "void_banner"}).status_code == 400
    assert cli.post("/api/branding/banner/earned", json={}).status_code == 400
    # earned -> the sealed bytes go through the real banner pipeline
    monkeypatch.setattr(g, "_mark_earned", lambda *a, **k: True)
    d = cli.get("/api/branding/banners/earned").get_json()
    assert d["banners"][0]["earned"] is True
    r = cli.post("/api/branding/banner/earned", json={"id": "great_library"})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    flat = g.branding_root() / "banner.png"
    assert flat.is_file()
    from PIL import Image
    assert Image.open(flat).size == (1920, 480)    # banner_main's canonical cut


def test_earned_banner_public_url_is_seal_gated(tmp_path, monkeypatch):
    """The png URL the list hands out is itself sealed: 404 until earned, the
    real bytes after -- and void_banner never serves either way."""
    cli = _client(tmp_path)
    _build_box({g._role_rel("earned_banners", "great_library.png"): b"GL ART",
                g._role_rel("earned_banners", "void_banner.png"): b"VOID ART"})
    monkeypatch.setattr(g, "_earned_achievement_ids", lambda *a, **k: frozenset())
    assert cli.get("/branding/earned_banners/great_library.png").status_code == 404
    assert cli.get("/branding/earned_banners/void_banner.png").status_code == 404
    monkeypatch.setattr(g, "_earned_achievement_ids",
                        lambda *a, **k: frozenset({"the-great-library"}))
    r = cli.get("/branding/earned_banners/great_library.png")
    assert r.status_code == 200 and r.data == b"GL ART"
    assert cli.get("/branding/earned_banners/void_banner.png").status_code == 404


# ---- the discovery scaffold + GONK breadcrumb (contract section 4) -----------

def test_breadcrumb_materialized_from_the_sealed_asset(tmp_path):
    """The README content ships SEALED (spoiler hygiene keeps the Nel ASCII out
    of public source): with a container carrying it, the loose crumb is that
    exact content -- and the coded empties for all six discovery roles exist,
    while the old root-level README is no longer written."""
    crumb = b"cryptic nel ascii art\nMaybe something goes in here.\n"
    _build_box({g._role_rel("breadcrumb", "README.txt"): crumb})
    g.ensure_branding_discovery_tree()
    assert (g._role_dir("breadcrumb") / "README.txt").read_bytes() == crumb
    for slot in ("banner_main", "banner_login", "banner_loom",
                 "mascots", "rewards", "marks"):
        assert g._role_dir(slot).is_dir(), slot
    assert not (g.branding_root() / "README.txt").exists()


def test_breadcrumb_falls_back_to_plain_text_without_the_asset(tmp_path):
    """A container-less (or crumb-less) install still gets a breadcrumb -- the
    unspoilery one-liner."""
    g.ensure_branding_discovery_tree()
    readme = g._role_dir("breadcrumb") / "README.txt"
    assert readme.read_text(encoding="utf-8") == g._BRANDING_README
