"""Achievements & skins: milestone computation from local catalog stats + the
persisted cosmetic state + the /api/achievements and /api/skin routes. All local,
read-only catalog data (no network, no spend)."""
import pixai_gallery as g
from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


# ---- pure compute -----------------------------------------------------------

def test_compute_earns_by_threshold_and_flags_newly():
    m = {"images": 1200, "videos": 0, "collections": 0,
         "models": 0, "published": 0, "tagged": 0}
    out = g.compute_achievements(m, seen=[])
    by = {a["id"]: a for a in out["achievements"]}
    assert by["first-light"]["earned"] is True         # >= 1
    assert by["archivist"]["earned"] is True           # >= 1000
    assert by["hoardsmith"]["earned"] is False          # needs 10000
    assert by["archivist"]["current"] == 1200
    # both earned feats are newly-unlocked (nothing seen yet)
    assert set(out["newly"]) == {"first-light", "archivist"}
    # seen suppresses the toast flag but not the earned state
    out2 = g.compute_achievements(m, seen=["first-light", "archivist"])
    assert out2["newly"] == [] and by["archivist"]["earned"] is True


def test_ladder_achievements_carry_track_rung_and_rungs_total():
    """The Folio of Honors' ladder carousel/grid groups achievements by track and
    orders them by rung -- added 2026-07-22 for the redesign. Non-ladder
    achievements (milestone/mastery/feat) must NOT carry these fields at all,
    not just leave them empty, so the frontend can use their presence as the
    'this is a ladder tier' signal."""
    out = g.compute_achievements({}, [])
    by = {a["id"]: a for a in out["achievements"]}
    fl = by["first-light"]
    assert fl["bucket"] == "ladder"
    assert fl["track"] == "archive" and fl["rung"] == 1 and fl["rungs_total"] == 5
    non_ladder = next(a for a in out["achievements"] if a["bucket"] != "ladder")
    assert "track" not in non_ladder and "rung" not in non_ladder and "rungs_total" not in non_ladder


def test_ladders_list_matches_every_ladder_achievements_track():
    """The top-level 'ladders' list is the source of truth for track display
    names -- every ladder achievement's 'track' id must resolve to one of
    them, and every track must have at least one achievement (an orphaned
    track, or a track id typo on an achievement, would silently break the
    carousel for that ladder)."""
    out = g.compute_achievements({}, [])
    ladder_ids = {t["id"] for t in out["ladders"]}
    assert len(ladder_ids) == 10
    achievement_tracks = {a["track"] for a in out["achievements"] if a["bucket"] == "ladder"}
    assert achievement_tracks == ladder_ids


def test_ladder_rungs_are_contiguous_within_each_track():
    """Each track's rungs must run 1..rungs_total with no gaps or duplicates --
    the carousel's tier-pip navigation assumes a dense, correctly-ordered
    sequence, not sparse/scrambled rung numbers."""
    out = g.compute_achievements({}, [])
    by_track = {}
    for a in out["achievements"]:
        if a["bucket"] == "ladder":
            by_track.setdefault(a["track"], []).append(a)
    for track, rows in by_track.items():
        rungs = sorted(r["rung"] for r in rows)
        assert rungs == list(range(1, len(rows) + 1)), track
        assert all(r["rungs_total"] == len(rows) for r in rows), track


def test_epic_feats_unlock_skins():
    free = {s["id"] for s in g.compute_achievements({}, [])["skins"] if s["earned"]}
    assert free == {"moonglade", "nightfallen"}          # the two free skins
    # 50 videos earns Reel Director -> ember; 25 models earns Menagerie -> verdant
    m = {"videos": 50, "models": 25, "images": 0, "collections": 0,
         "published": 0, "tagged": 0}
    skins = {s["id"]: s["earned"] for s in g.compute_achievements(m, [])["skins"]}
    assert skins["ember"] is True and skins["verdant"] is True
    assert skins["moonlit"] is False                     # needs 10k images


# ---- metrics from a real catalog -------------------------------------------

def test_achievement_metrics_counts(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", model_name="Tsubaki",
             is_published="1", art_tags="night,elf", created_at="2025-01-01T00:00:00"),
        _row(media_id="2", filename="b_2.png", model_name="Haruka",
             art_tags="moon", created_at="2025-01-02T00:00:00"),
        _row(media_id="3", filename="c_3.png", model_name="Tsubaki",
             created_at="2025-01-03T00:00:00"),               # dup model, no tags
        _row(media_id="9", filename="v_9.mp4", is_video="1",
             created_at="2025-02-01T00:00:00"),
    ])
    m = g.achievement_metrics(tmp_path / "catalog.db")
    assert m["images"] == 3 and m["videos"] == 1
    assert m["models"] == 2                    # Tsubaki + Haruka (distinct)
    assert m["published"] == 1 and m["tagged"] == 2


# ---- persisted state --------------------------------------------------------

def test_state_roundtrip_and_soft_fail(tmp_path):
    assert g.load_ach_state(tmp_path) == {"seen": [], "skin": "moonglade", "earned_at": {}}
    g.save_ach_state(tmp_path, {"seen": ["a", "a", "b"], "skin": "ember",
                                "earned_at": {"a": "2026-07-13"}})
    st = g.load_ach_state(tmp_path)
    assert st["seen"] == ["a", "b"] and st["skin"] == "ember"      # deduped + sorted
    assert st["earned_at"] == {"a": "2026-07-13"}                  # earn-dates round-trip
    # an unknown skin id falls back to the default on read
    g.save_ach_state(tmp_path, {"seen": [], "skin": "not-a-skin"})
    assert g.load_ach_state(tmp_path)["skin"] == "moonglade"
    # corrupt file -> default, never raises
    (tmp_path / "achievements.json").write_text("{not json", encoding="utf-8")
    assert g.load_ach_state(tmp_path)["skin"] == "moonglade"


# ---- routes -----------------------------------------------------------------

def _client(tmp_path, rows):
    save_catalog(tmp_path / "catalog.db", rows)
    return login_client(tmp_path), tmp_path


def test_the_hall_was_renamed_the_folio_of_honors(tmp_path):
    """2026-07-22 owner decision, off the STATE.md rename shortlist -- guards against a
    straggler reference surviving a future edit to the modal skeleton in pixai_gallery.py."""
    cli, _ = _client(tmp_path, [])
    html = cli.get("/").get_data(as_text=True)
    assert "The Folio of Honors" in html
    assert "Trophy Hall" not in html


def test_api_achievements_marks_seen_once(tmp_path):
    cli, out = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                       created_at="2025-01-01T00:00:00")])
    d1 = cli.get("/api/achievements").get_json()
    assert any(a["id"] == "first-light" and a["earned"] for a in d1["achievements"])
    assert "first-light" in d1["newly"]                 # not yet marked
    assert d1["skin"] == "moonglade" and "metrics" in d1
    # ?mark=1 records it; a subsequent read no longer flags it newly
    d2 = cli.get("/api/achievements?mark=1").get_json()
    assert "first-light" in d2["newly"]
    d3 = cli.get("/api/achievements").get_json()
    assert d3["newly"] == []
    assert "first-light" in g.load_ach_state(out)["seen"]


def test_api_skin_rejects_locked_accepts_earned(tmp_path):
    cli, out = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                       created_at="2025-01-01T00:00:00")])
    # ember is locked (no videos) -> 403, active skin unchanged
    r = cli.post("/api/skin", json={"skin": "ember"})
    assert r.status_code == 403 and g.load_ach_state(out)["skin"] == "moonglade"
    # nightfallen is free -> accepted + persisted
    r2 = cli.post("/api/skin", json={"skin": "nightfallen"})
    assert r2.status_code == 200 and r2.get_json()["skin"] == "nightfallen"
    assert g.load_ach_state(out)["skin"] == "nightfallen"
    # unknown skin id -> 400
    assert cli.post("/api/skin", json={"skin": "bogus"}).status_code == 400
