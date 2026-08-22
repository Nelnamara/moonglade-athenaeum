"""The bundle's unlock split, enforced at the serving layer (docs/DECISIONS.md
2026-07-27 "The bundle's unlock split" + the 2026-08-06 mascots correction):
achievement-bound art -- badge masters, the mascot ach poses, the rewards tree,
the Konami Starfall assets -- seals to the achievement that earns it; system
chrome (narrator, tracker art, present_* fallbacks, banners) stays open. Plus
the mark_12 (Gem Tome) tombstone (owner ruling 2026-07-23) and the Branding-slot
boundary (banners only -- mascots/rewards are not slots).

Bundle-v2 (SCOPE_bundle-v2-contract.md): the on-disk tree is CODED, so every
seed below lands at its coded rel -- built with g._role_rel/_role_dir, NEVER a
hardcoded hex literal (retyped prefixes are exactly the scatter the map
removed) -- while every GET keeps the UNCHANGED public role-named /branding/
URL; the serve route translates once at the boundary.

All hermetic: conftest's _isolated_branding redirects branding_root() to
tmp_path, so every fake asset below lives and dies with its test."""
import datetime as _dt
import json
from unittest import mock

import pytest

import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, save_catalog

from tests.conftest import login_client


class _FixedNoon(_dt.datetime):
    """Same freeze as test_telemetry's: never trip Night Owl mid-test."""
    @classmethod
    def now(cls, tz=None):
        return cls(2025, 6, 15, 12, 0, 0)


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


def _client(tmp_path, n_images=1):
    rows = [_row(media_id=str(i), filename="a_%d.png" % i,
                 created_at="2025-01-01T00:00:00") for i in range(1, n_images + 1)]
    save_catalog(tmp_path / "catalog.db", rows)
    return login_client(tmp_path)


def _seed(tmp_path, coded_rel, data=b"\x89PNG fake"):
    """Seed a loose file at its CODED on-disk rel (build the rel with
    g._role_rel -- the public GET URL it answers stays role-named)."""
    p = tmp_path / "branding" / coded_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


# ---- the seal: deny / earned / open ----------------------------------------

def test_sealed_paths_deny_while_unearned(tmp_path):
    cli = _client(tmp_path)
    # loremaster needs 25k images; the-konami-code needs the beacon -- neither is
    # earned with a 1-image catalog and no flags. Each pair: (public GET rel,
    # coded seed rel) -- the URL vocabulary never changed, only where files live.
    crumb = g._role_rel("breadcrumb", "README.txt")
    pairs = [
        ("badges/loremaster.png",      g._role_rel("badges", "loremaster.png")),
        ("mascots/ach/loremaster.png", g._role_rel("mascots_ach", "loremaster.png")),
        ("rewards/ach/loremaster.png", g._role_rel("rewards", "ach/loremaster.png")),
        ("_thumbs/loremaster.png",     "_thumbs/loremaster.png"),  # literal, never coded
        ("ee_nelstarfall.png",         g._role_rel("starfall", "ee_nelstarfall.png")),
        ("ee_starfall_cast.ogg",       g._role_rel("starfall", "ee_starfall_cast.ogg")),
        ("ee_starfall_loop.ogg",       g._role_rel("starfall", "ee_starfall_loop.ogg")),
        # a probe that GUESSES the coded GONK breadcrumb path passes through
        # translation unchanged and faces the same starfall-prefix seal
        (crumb,                        crumb),
    ]
    for public, coded in pairs:
        _seed(tmp_path, coded)
        r = cli.get("/branding/" + public)
        assert r.status_code == 404, public   # sealed == indistinguishable from absent
    # unknown files in the sealed buckets stay sealed too
    _seed(tmp_path, g._role_rel("badges", "not-an-achievement.png"))
    assert cli.get("/branding/badges/not-an-achievement.png").status_code == 404


def test_reward_ui_icons_open_rest_of_rewards_sealed(tmp_path):
    """The D8 exception: claim.png + gift.png are the claim toast/modal's UI
    chrome (notify.css fetches them by public URL), so they stay OPEN -- while
    every other file in the rewards bucket stays sealed shut."""
    cli = _client(tmp_path)
    rdir = g._role_dir("rewards")
    rdir.mkdir(parents=True, exist_ok=True)
    for name in ("claim.png", "gift.png"):
        (rdir / name).write_bytes(b"\x89PNG fake")
        assert cli.get("/branding/rewards/" + name).status_code == 200, name
    (rdir / "trophy.png").write_bytes(b"\x89PNG fake")
    assert cli.get("/branding/rewards/trophy.png").status_code == 404


def test_sealed_paths_serve_once_earned(tmp_path):
    cli = _client(tmp_path)   # 1 image -> first-light IS earned
    _seed(tmp_path, g._role_rel("badges", "first-light.png"))
    _seed(tmp_path, g._role_rel("mascots_ach", "first-light.png"))
    assert cli.get("/branding/badges/first-light.png").status_code == 200
    assert cli.get("/branding/mascots/ach/first-light.png").status_code == 200
    # the Konami earn is the beacon; the egg's asset fetch follows it (App.jsx
    # awaits the beacon), so the very first trigger must already serve -- the
    # art, BOTH audio files, and the GONK breadcrumb: the whole starfall
    # prefix unseals together
    _seed(tmp_path, g._role_rel("starfall", "ee_nelstarfall.png"))
    _seed(tmp_path, g._role_rel("starfall", "ee_starfall_cast.ogg"))
    _seed(tmp_path, g._role_rel("starfall", "ee_starfall_loop.ogg"))
    assert cli.get("/branding/ee_nelstarfall.png").status_code == 404
    assert cli.post("/api/ach-event", json={"event": "konami"}).status_code == 200
    assert cli.get("/branding/ee_nelstarfall.png").status_code == 200
    assert cli.get("/branding/ee_starfall_cast.ogg").status_code == 200
    assert cli.get("/branding/ee_starfall_loop.ogg").status_code == 200
    # the breadcrumb README (materialized by the discovery scaffold at startup)
    crumb = g._role_rel("breadcrumb", "README.txt")
    assert cli.get("/branding/" + crumb).status_code == 200


def test_earned_banner_gated_and_void_banner_never_serves(tmp_path):
    """great_library.png (the earned-banner reward art) denies until
    the-great-library is earned, then serves at the UNCHANGED public role URL;
    void_banner.png is an UNWIRED future reward (achievements #57-60) and
    NEVER serves, no matter how much is earned."""
    cli = _client(tmp_path)   # 1 image: the-great-library (50k crown) unearned
    _seed(tmp_path, g._role_rel("earned_banners", "great_library.png"))
    _seed(tmp_path, g._role_rel("earned_banners", "void_banner.png"))
    assert cli.get("/branding/earned_banners/great_library.png").status_code == 404
    assert cli.get("/branding/earned_banners/void_banner.png").status_code == 404
    # earn it for real: 50k catalog rows crosses the crown (the seal's denied-
    # `need` recompute picks the change up without waiting out the 5s cache)
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id=str(i), filename="a_%d.png" % i,
                       created_at="2025-01-01T00:00:00") for i in range(1, 50001)])
    cli.post("/api/ach-event", json={"event": "konami"})   # pile on more earns
    assert cli.get("/branding/earned_banners/great_library.png").status_code == 200
    assert cli.get("/branding/earned_banners/void_banner.png").status_code == 404


def test_system_chrome_stays_open(tmp_path):
    """The seal is for earned surprises -- the app's default dress (narrator,
    tracker art, celebration present_* fallbacks, banners) serves ungated."""
    cli = _client(tmp_path)
    pairs = [
        ("mascots/nel_narrator.png", g._role_rel("mascots", "nel_narrator.png")),
        ("mascots/trk_done.png",     g._role_rel("mascots", "trk_done.png")),
        ("mascots/present_1.png",    g._role_rel("mascots", "present_1.png")),
        ("banner.png",               "banner.png"),   # flat: loose-only at the coded root
        ("marks/mark_4.png",         g._role_rel("marks", "mark_4.png")),
    ]
    for public, coded in pairs:
        _seed(tmp_path, coded)
        assert cli.get("/branding/" + public).status_code == 200, public


def test_badge_thumb_hidden_gate(tmp_path):
    """Hidden feats' ids sit in this public source, so /badge-thumb/ must not
    serve an UNEARNED hidden feat's art by id -- while visible-but-unearned
    achievements keep their thumbs (the Folio's locked tiles show art)."""
    from PIL import Image
    cli = _client(tmp_path)
    bdir = g._role_dir("badges")
    bdir.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (64, 64), (10, 20, 30, 255)).save(bdir / "the-konami-code.png")
    Image.new("RGBA", (64, 64), (10, 20, 30, 255)).save(bdir / "loremaster.png")
    assert cli.get("/badge-thumb/the-konami-code.png").status_code == 404
    assert cli.get("/badge-thumb/loremaster.png").status_code == 200
    cli.post("/api/ach-event", json={"event": "konami"})
    assert cli.get("/badge-thumb/the-konami-code.png").status_code == 200



def test_badge_thumb_hidden_gate_is_case_insensitive(tmp_path):
    """A case-variant URL must not skip the hidden-feat gate: the resolve is on a
    case-insensitive FS, so UNDER-THE-HOOD.png would read the real sealed master
    while the lowercase id-set membership missed it (fail-open). Regression for
    the 2026-08-22 badge_thumb casefold (mirrors _seal_rule's own casefold)."""
    from PIL import Image
    cli = _client(tmp_path)
    hid = "under-the-hood" if "under-the-hood" in g._ach_hidden() else sorted(g._ach_hidden())[0]
    bdir = g._role_dir("badges"); bdir.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (64, 64), (7, 22, 30, 255)).save(bdir / (hid + ".png"))
    assert cli.get("/badge-thumb/" + hid + ".png").status_code == 404
    assert cli.get("/badge-thumb/" + hid.upper() + ".png").status_code == 404
    assert cli.get("/badge-thumb/" + hid.title() + ".png").status_code == 404


# ---- the Branding-slot boundary ---------------------------------------------

def test_branding_slots_are_banners_only(tmp_path):
    cli = _client(tmp_path)
    with mock.patch("datetime.datetime", _FixedNoon):
        d = cli.get("/api/branding").get_json()
    assert set(d["slots"]) == {"banner_main", "banner_login", "banner_loom"}


def test_slot_routes_refuse_mascots_and_rewards(tmp_path):
    cli = _client(tmp_path)
    for slot in ("mascots", "rewards"):
        r = cli.post("/api/branding/slot", data={"slot": slot})
        assert r.status_code == 400 and r.get_json()["error"] == "unknown slot"


def test_discovery_tree_keeps_breadcrumb_folders(tmp_path):
    """Removing mascots/rewards from BRANDING_SLOTS must not shrink the
    tinkerer-discovery landscape: the empty folders still go down -- at their
    CODED names (bundle-v2: role names never appear on disk), plus the GONK
    breadcrumb README the scaffold materializes."""
    g.ensure_branding_discovery_tree()
    root = tmp_path / "branding"
    for slot in ("banner_main", "banner_login", "banner_loom",
                 "mascots", "rewards", "marks"):
        assert g._role_dir(slot).is_dir(), slot
        assert not (root / slot).exists(), slot   # no role-named folder anywhere
    assert (g._role_dir("breadcrumb") / "README.txt").is_file()


# ---- the mark_12 tombstone ---------------------------------------------------

def _cut_marks(tmp_path, ids):
    mdir = g._role_dir("marks")
    mdir.mkdir(parents=True, exist_ok=True)
    for i in ids:
        (mdir / (i + ".png")).write_bytes(b"\x89PNG fake")
    (mdir / "marks.json").write_text(json.dumps(
        {"marks": [{"id": i, "label": i, "kind": "tile"} for i in ids]}),
        encoding="utf-8")


def test_mark_12_never_lists_even_from_a_seeded_manifest(tmp_path):
    """The Gem Tome removal (owner ruling 2026-07-23) has to hold on installs
    whose loose marks.json still carries it -- loose wins over any rebuilt
    container, so the tombstone filter is the only thing that can reach them."""
    cli = _client(tmp_path)
    _cut_marks(tmp_path, ["mark_4", "mark_12"])
    d = cli.get("/api/branding").get_json()
    assert {m["id"] for m in d["marks"]} == {"mark_4"}
    # POSTing the tombstoned id is refused like any unknown mark
    r = cli.post("/api/branding", json={"mark": "mark_12"})
    assert r.status_code == 400


def test_active_mark_12_falls_back_to_default(tmp_path):
    cli = _client(tmp_path)
    _cut_marks(tmp_path, ["mark_4", "mark_12"])
    (tmp_path / "branding.json").write_text(
        json.dumps({"mark": "mark_12", "anim": "classic"}), encoding="utf-8")
    d = cli.get("/api/branding").get_json()
    assert d["mark"] != "mark_12"


def test_sweep_never_adopts_a_tombstoned_marks_file(tmp_path):
    """Caught LIVE on the owner's install, 2026-08-13, minutes after the
    tombstone landed: delisting mark_12 removed it from the sweep's `known`
    set, so the still-on-disk loose mark_12.png read as a fresh hand-drop and
    got adopted -- the original deleted, a re-encoded copy registered under a
    suffixed id and made ACTIVE. The 2026-08-05 near-miss, back through a new
    door. A tombstoned stem must read as known: untouched file, no adoption,
    no achievement fire."""
    cli = _client(tmp_path)
    mdir = g._role_dir("marks")
    mdir.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(mdir / "mark_12.png")
    _cut_marks_manifest_only = {"marks": [{"id": "mark_12", "label": "Gem Tome",
                                           "kind": "tile"}]}
    (mdir / "marks.json").write_text(json.dumps(_cut_marks_manifest_only),
                                     encoding="utf-8")
    assert g.sweep_branding_drops(tmp_path) is False
    assert (mdir / "mark_12.png").exists()          # not eaten
    data = json.loads((mdir / "marks.json").read_text(encoding="utf-8"))
    assert [m["id"] for m in data["marks"]] == ["mark_12"]   # nothing adopted
    assert g.telemetry_metrics(tmp_path).get("branding_custom_file", 0) == 0


def test_adopt_never_reuses_a_tombstoned_id(tmp_path):
    """A hand-dropped marks/mark_12.png must adopt under a DIFFERENT id --
    adopting as mark_12 itself would register a mark list_marks() refuses to
    show, a silent black hole for the user's own file."""
    _client(tmp_path)   # builds the app tree
    _cut_marks(tmp_path, ["mark_4"])
    g._adopt_mark(tmp_path, "mark_12", b"\x89PNG fake bytes")
    data = json.loads((g._role_dir("marks") / "marks.json")
                      .read_text(encoding="utf-8"))
    ids = {m["id"] for m in data["marks"]}
    assert "mark_12" not in ids
    assert any(i.startswith("mark_12-") for i in ids)   # adopted, under a fresh id
