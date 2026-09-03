"""Achievements & skins: milestone computation from local catalog stats + the
persisted cosmetic state + the /api/achievements and /api/skin routes. All local,
read-only catalog data (no network, no spend)."""
import datetime as _dt
from pathlib import Path
from unittest import mock

import pytest

import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_client, _SEALED_DONOR

# The roster is sealed in the container (built from the private donor), not in source.
# Gate ONLY the tests that assert sealed roster/skin CONTENT -- NOT the whole module: the
# store/SQL/badge tests here are donor-independent and must keep running in public CI, or a
# fail-soft regression merges behind a green-but-quietly-reduced check (finding #3).
needs_donor = pytest.mark.skipif(not _SEALED_DONOR.is_file(),
                                 reason="sealed-definitions donor (private repo) not present")


class _FixedNoon(_dt.datetime):
    """Freeze the wall clock at noon around /api/achievements calls whose `newly`
    is asserted exactly. The route has a real-time side effect -- between 02:00
    and 03:59 local it sets the `session_hour` telemetry flag, which earns the
    hidden Night Owl feat and puts 'night-owl' into `newly` (issue #16: the
    first-sync-gate backfill test failed only when the suite ran in that window).
    Same idiom as tests/test_telemetry.py / tests/test_unlock_split.py."""
    @classmethod
    def now(cls, tz=None):
        return cls(2025, 6, 15, 12, 0, 0)


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


# ---- pure compute -----------------------------------------------------------

@needs_donor
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


@needs_donor
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


@needs_donor
def test_ladders_list_matches_every_ladder_achievements_track():
    """The top-level 'ladders' list is the source of truth for track display
    names -- every ladder achievement's 'track' id must resolve to one of
    them, and every track must have at least one achievement (an orphaned
    track, or a track id typo on an achievement, would silently break the
    carousel for that ladder)."""
    out = g.compute_achievements({}, [])
    ladder_ids = {t["id"] for t in out["ladders"]}
    # The payload's ladder list used to be compared to _ladder_tracks() -- which is the
    # thing it is copied FROM, so it could never fail and asserted nothing. What actually
    # matters is that the two SIDES agree: every track names achievements that exist, and
    # every ladder achievement names a track that exists. Either half breaking is a
    # silently empty carousel.
    roster_ids = {a["id"] for a in g._roster()}
    for t in g._ladder_tracks():
        tiers = [a for a in g._roster()
                 if a.get("bucket") == "ladder" and a.get("track") == t["id"]]
        assert tiers, "ladder track %r has no achievements" % t["id"]
        for a in tiers:
            assert a["id"] in roster_ids
    achievement_tracks = {a["track"] for a in out["achievements"] if a["bucket"] == "ladder"}
    assert achievement_tracks == ladder_ids
    assert ladder_ids, "the roster really does define ladder tracks"


@needs_donor
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


@needs_donor
def test_epic_feats_unlock_skins():
    free = {s["id"] for s in g.compute_achievements({}, [])["skins"] if s["earned"]}
    assert free == {s["id"] for s in g._skins() if s.get("free")}   # the free skins, self-computed
    # Derive each earnable skin's grant (the roster achievement whose `skin` == that skin,
    # with its metric + threshold) -- no hardcoded threshold. Meet ember + verdant's grants
    # while leaving moonlit's own metric at 0.
    grant = {a["skin"]: (a["metric"], a["threshold"]) for a in g._roster() if a.get("skin")}
    m = {grant["ember"][0]: grant["ember"][1], grant["verdant"][0]: grant["verdant"][1]}
    m.setdefault(grant["moonlit"][0], 0)                 # explicitly below moonlit's threshold
    skins = {s["id"]: s["earned"] for s in g.compute_achievements(m, [])["skins"]}
    assert skins["ember"] is True and skins["verdant"] is True
    assert skins["moonlit"] is False                     # moonlit's own metric left at 0


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

@needs_donor
def test_state_roundtrip_and_soft_fail(tmp_path):
    assert g.load_ach_state(tmp_path) == {"seen": [], "skin": "moonglade", "earned_at": {}}
    g.save_ach_state(tmp_path, {"seen": ["a", "a", "b"], "skin": "ember",
                                "earned_at": {"a": "2026-07-13"}})
    st = g.load_ach_state(tmp_path)
    assert st["seen"] == ["a", "b"] and st["skin"] == "ember"      # deduped + sorted
    assert st["earned_at"] == {"a": "2026-07-13"}                  # earn-dates round-trip
    # a stored skin id is PRESERVED on read, even if it isn't in the current
    # _skin_ids() -- read is trust, the /api/skin write gate is what rejects a
    # bogus/locked skin. (Coercing here would wipe an earned skin during an
    # undressed window and persist the reset -- adversarial M1, 2026-08-22.) An
    # id with no CSS rule just renders the default tokens, harmlessly.
    g.save_ach_state(tmp_path, {"seen": [], "skin": "not-a-skin"})
    assert g.load_ach_state(tmp_path)["skin"] == "not-a-skin"
    # missing / non-string / empty -> default
    g.save_ach_state(tmp_path, {"seen": [], "skin": ""})
    assert g.load_ach_state(tmp_path)["skin"] == "moonglade"
    # corrupt file -> default, never raises
    (tmp_path / "achievements.json").write_text("{not json", encoding="utf-8")
    assert g.load_ach_state(tmp_path)["skin"] == "moonglade"


def test_earned_skin_survives_an_undressed_window(tmp_path, monkeypatch):
    """M1 (adversarial, 2026-08-22): while the sealed pack is downloading or briefly
    unreadable, _skin_ids() collapses to the free skins. An earned skin the user
    picked must NOT be coerced to the default and persisted -- that was permanent
    loss of a cosmetic choice the art container has nothing to do with."""
    import moonglade_gallery as g
    monkeypatch.setattr(g, "_skin_ids", lambda: {"moonglade", "nightfallen"})  # undressed
    g.save_ach_state(tmp_path, {"seen": [], "skin": "ember"})   # an earned skin, now unvalidatable
    assert g.load_ach_state(tmp_path)["skin"] == "ember"        # preserved, not reset
    # and a save triggered while undressed (e.g. the mark path) must not rewrite it
    st = g.load_ach_state(tmp_path)
    g.save_ach_state(tmp_path, st)
    assert g.load_ach_state(tmp_path)["skin"] == "ember"        # still ember after the pack returns


# ---- routes -----------------------------------------------------------------

def _client(tmp_path, rows):
    save_catalog(tmp_path / "catalog.db", rows)
    return login_client(tmp_path), tmp_path


# RETIRED 2026-08-08 (React port): test_ach_grid_stacks_its_sections_instead_of_tiling_them
# read static/mg-notify.js for the '.ach-grid{display:flex;flex-direction:column' CSS. That
# file is deleted, and the #ach-modal Trophy Hall machinery it styled (open/close/tab/search/
# render*/card/carousel) was deliberately dropped as dead code in the React notify port --
# no served page has the #ach-modal skeleton anymore. The React Folio (FolioOverlay.jsx)
# owns its own section layout, so there is no '.ach-grid' auto-fill grid left to regress.
# The original test guarded a real 2026-07-22 live-install regression (auto-fill grid tiling
# full-width sections into narrow scrambled columns); that history stays in git.


def test_the_hall_was_renamed_the_folio_of_honors():
    """2026-07-22 owner decision, off the STATE.md rename shortlist. The classic
    page's modal skeleton is gone with the classic UI; the Folio now ships in the
    React bundle -- guard the rename there so a straggler 'Trophy Hall' reference
    can't creep back into the user-visible shell. (Source-file comments citing the
    classic Trophy Hall as provenance are fine; the built bundle strips them.)"""
    bundle = (Path(__file__).resolve().parent.parent / "gallery" / "dist" / "app.js").read_text(encoding="utf-8")
    assert "The Folio of Honors" in bundle
    assert "Trophy Hall" not in bundle


@needs_donor
def test_api_achievements_marks_seen_once(tmp_path):
    cli, out = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                       created_at="2025-01-01T00:00:00")])
    g.telem_flag("first_sync_done", out_dir=out)   # a normal install past its first sync;
    # the first-sync gate (celebrations withheld until the first --sync finishes) has its
    # own coverage in test_first_sync_gate_* below.
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


@needs_donor
def test_first_sync_gate_withholds_celebrations_until_complete(tmp_path):
    """first-light is images>=1, so without a gate it pops seconds into a fresh install's
    first sync (as images climb from 0). While the first sync is still running -- no
    first_sync_done flag, no prior recognition -- /api/achievements must WITHHOLD `newly`
    and leave `seen` untouched, so the rungs earned during it fire together once --sync sets
    the flag, not mid-sync."""
    cli, out = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                       created_at="2025-01-01T00:00:00")])
    d1 = cli.get("/api/achievements?mark=1").get_json()
    assert any(a["id"] == "first-light" and a["earned"] for a in d1["achievements"])  # earned still computes
    assert d1["newly"] == []                                    # but no celebration mid-first-sync
    assert not g.load_ach_state(out).get("seen")                # and nothing marked seen (not lost)
    g.telem_flag("first_sync_done", out_dir=out)                # the first --sync completes
    d2 = cli.get("/api/achievements").get_json()
    assert "first-light" in d2["newly"]                         # now the earned rung fires


@needs_donor
def test_first_sync_gate_backfills_for_preexisting_install(tmp_path):
    """A pre-existing install (an achievement already recognized) is never gated: the flag
    backfills off prior `seen`/`earned_at`, so an established library neither suppresses nor
    re-fires. Keyed on recognition, NOT images>0 -- an images-based backfill would flip the
    flag mid-first-sync and reintroduce the bug."""
    cli, out = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                       created_at="2025-01-01T00:00:00")])
    st = g.load_ach_state(out)
    st["seen"] = ["first-light"]
    g.save_ach_state(out, st)
    with mock.patch("datetime.datetime", _FixedNoon):   # never trip Night Owl mid-test (issue #16)
        d = cli.get("/api/achievements").get_json()
    assert d["newly"] == []                                      # already seen -> nothing new
    assert g.load_telemetry(out)["flags"].get("first_sync_done")  # gate backfilled to done


@needs_donor
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


# ---- robustness: a malformed sealed roster must degrade, never 500 -----------

def test_malformed_sealed_roster_degrades_not_500(tmp_path):
    """A checksum-valid but MALFORMED achievements payload (valid JSON that clears the
    dict/"roster" gate but whose roster is not a list of well-shaped entries) must NOT 500
    the Folio -- it degrades to the empty free-skins fallback, exactly like a missing
    container. Donor-INDEPENDENT: it packs its own bad container, so CI runs it. (Guards
    finding: build_container validates only top-level keys, so a bad donor could ship a
    container that opens fine but derives badly, and _sealed_defs only wrapped json.loads.)"""
    import json as _json
    import moonglade_container as mc
    cpath = g._container_path()          # tmp_path/moonglade.dat via _isolated_branding
    # "roster" is a string -> `a["id"] for a in roster` iterates characters -> TypeError.
    for bad in (_json.dumps({"roster": "not-a-list"}).encode(),
                _json.dumps({"roster": [{"name": "x"}]}).encode()):     # entry lacks "id"
        mc.write_container(cpath, {"seed.txt": b"x"}, {"achievements": bad})
        g._sealed_cache.update(path=None, mtime=None, defs=None)
        g._container_cache.update(path=None, mtime=None, box=None)
        defs = g._sealed_defs()                     # must fall back, not raise
        assert defs["roster"] == [] and defs["_ach_ids"] == frozenset()
    # and the live route serves 200 on the degraded roster, never a 500
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    cli = login_client(tmp_path)
    assert cli.get("/api/achievements").status_code == 200


# ---- pin-once (#37) + the skin-gate parity (#38) ----------------------------

@needs_donor
def test_pinned_achievement_stays_earned_when_the_metric_drops():
    """#37 (owner: "a Failure -- Colossal"): catalog-count metrics are snapshots, so
    the web Duplicate Review's last-copy delete (or any real bulk delete) could drop
    `images` back below an already-celebrated threshold and visibly UN-earn the badge.
    An id stamped in earned_at now stays earned regardless of the live metric."""
    out = g.compute_achievements({"images": 0}, earned_at={"first-light": "2026-01-01"})
    fl = next(a for a in out["achievements"] if a["id"] == "first-light")
    assert fl["earned"], "a stamped achievement un-earned when its metric dropped"
    # and the same input WITHOUT the stamp keeps the live-threshold behavior
    out2 = g.compute_achievements({"images": 0})
    assert not next(a for a in out2["achievements"] if a["id"] == "first-light")["earned"]


@needs_donor
def test_pinned_achievements_keep_their_skin_unlocked():
    """The pin flows through to skins: a stamped skin-granting achievement keeps its
    palette unlocked even after the backing count shrinks (menagerie -> verdant)."""
    out = g.compute_achievements({"models": 0}, earned_at={"menagerie": "2026-01-01"})
    skins = {s["id"]: s["earned"] for s in out["skins"]}
    assert skins.get("verdant") is True


@needs_donor
def test_skin_gate_honors_a_pinned_unlock(tmp_path):
    """#37 x #38: /api/skin used to compute from achievement_metrics() ALONE -- no
    telemetry merge, no earned_at -- its own private, weaker notion of "earned".
    With an empty catalog and menagerie stamped in earned_at, the Folio shows the
    verdant palette unlocked; equipping it must succeed too (403 before the fix)."""
    client = login_client(tmp_path)
    g.save_ach_state(tmp_path, {"seen": ["menagerie"], "skin": "moonglade",
                                "earned_at": {"menagerie": "2026-01-01"}})
    r = client.post("/api/skin", json={"skin": "verdant"})
    assert r.status_code == 200, r.get_json()
    assert g.load_ach_state(tmp_path)["skin"] == "verdant"


@needs_donor
def test_skin_gate_reads_telemetry_metrics_like_every_other_gate(tmp_path):
    """#38's telemetry half, proven end-to-end with a synthetic roster: an
    achievement whose metric lives in telemetry.json (not the catalog) grants a
    skin; the equip gate must see it. Before the fix the gate merged no telemetry,
    so this exact flow showed earned in the Folio and 403'd on equip. No current
    sealed skin-achievement is telemetry-backed -- which is precisely why the
    latent bug survived every review -- so the roster is patched for the test."""
    client = login_client(tmp_path)
    fake = [dict(a) for a in g._roster()]
    for a in fake:
        if a["id"] == "menagerie":
            a["metric"], a["threshold"] = "edits", 1   # telemetry counter, not catalog
    g.telem_bump("edits", out_dir=tmp_path)
    with mock.patch.object(g, "_roster", return_value=fake):
        r = client.post("/api/skin", json={"skin": "verdant"})
    assert r.status_code == 200, r.get_json()


@needs_donor
def test_locked_skin_is_still_refused(tmp_path):
    """The gate stayed a gate: nothing pinned, nothing earned -> verdant still 403s."""
    client = login_client(tmp_path)
    r = client.post("/api/skin", json={"skin": "verdant"})
    assert r.status_code == 403
