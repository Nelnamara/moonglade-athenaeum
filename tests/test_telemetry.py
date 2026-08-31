"""The achievement telemetry layer: the persisted counter store (telemetry.json),
its flattening into the metric namespace, the roster compute post-passes, the
hidden-feat masking on /api/achievements, and the /api/ach-event beacon. All
local + fail-soft -- a telemetry hiccup must never break a page or a backup."""
import json

import datetime as _dt
from pathlib import Path
from unittest import mock

import pytest

import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_client, _SEALED_DONOR

# The roster is sealed in the container (built from the private donor), not in source.
# Gate ONLY the tests that assert sealed roster/skin/criteria CONTENT -- NOT the whole
# module: the persisted-store, SQL-metric, time-capsule and badge-thumb tests below are
# donor-independent and must keep running in public CI, or a fail-soft regression merges
# behind a green-but-quietly-reduced check (finding #3).
needs_donor = pytest.mark.skipif(not _SEALED_DONOR.is_file(),
                                 reason="sealed-definitions donor (private repo) not present")


class _FixedNoon(_dt.datetime):
    """Freeze the wall clock at noon so /api/achievements never flags the 2-4am
    Night Owl feat (session_hour) mid-test. That real-time side effect made the
    hidden-feat masking assertions flaky whenever the suite ran overnight."""
    @classmethod
    def now(cls, tz=None):
        return cls(2025, 6, 15, 12, 0, 0)


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


# ---- the persisted store ----------------------------------------------------

def test_store_roundtrip(tmp_path):
    g.telem_bump("edits", out_dir=tmp_path)
    g.telem_bump("edits", out_dir=tmp_path)
    g.telem_bump("culled", 40, out_dir=tmp_path)
    g.telem_max("lora_stacked", 2, out_dir=tmp_path)
    g.telem_max("lora_stacked", 1, out_dir=tmp_path)      # max keeps 2
    g.telem_set_add("tools", "edit", out_dir=tmp_path)
    g.telem_set_add("tools", "edit", out_dir=tmp_path)    # set dedupes
    g.telem_set_add("tools", "fix", out_dir=tmp_path)
    g.telem_flag("konami_triggered", out_dir=tmp_path)
    g.telem_mark_day(out_dir=tmp_path)
    g.telem_mark_day(out_dir=tmp_path)                    # same day counts once
    m = g.telemetry_metrics(tmp_path)
    assert m["edits"] == 2 and m["culled"] == 40
    assert m["lora_stacked"] == 2
    assert m["tools_used"] == 2
    assert m["konami_triggered"] == 1
    assert m["days_used"] == 1


def test_store_corrupt_and_unset_fail_soft(tmp_path):
    (tmp_path / "telemetry.json").write_text("{not json", encoding="utf-8")
    assert g.telemetry_metrics(tmp_path)["days_used"] == 0   # never raises
    g.telem_bump("edits", out_dir=tmp_path)                  # overwrites the wreck
    assert g.telemetry_metrics(tmp_path)["edits"] == 1
    # valid JSON with hostile inner types must not len()-crash a page
    (tmp_path / "telemetry.json").write_text(
        json.dumps({"counters": {"edits": "x"}, "sets": {"tools": 1},
                    "flags": {}, "maxima": {}, "days": []}), encoding="utf-8")
    m = g.telemetry_metrics(tmp_path)
    assert m["tools_used"] == 0 and m["edits"] == 0
    # bare bumps no-op (not crash) when no out_dir was ever set
    old = g._TELEM_OUT
    try:
        g.set_telemetry_out(None)
        g.telem_bump("edits")
    finally:
        g.set_telemetry_out(old)


# ---- the roster + compute post-passes ------------------------------------

@needs_donor
def test_roster_shape():
    roster = g._roster()
    # self-computed shape invariants -- no magic roster/feat/banner counts.
    assert roster and len(roster) == len({a["id"] for a in roster})   # non-empty, ids unique
    assert {a["id"] for a in roster} == set(g._ach_ids())
    feats = [a for a in roster if a["tier"] == "feat"]
    assert feats and all(a.get("hidden") for a in feats)              # every feat-tier is hidden
    banners = sum(1 for a in roster if a.get("banner_reward"))
    assert 0 < banners < len(roster)                                  # a real, non-empty subset
    assert all(a["threshold"] >= 1 for a in roster)
    assert all(a.get("roast") and a.get("roast_nsfw") for a in roster)


@needs_donor
def test_skin_changer_counts_unlocked_skins():
    out = g.compute_achievements({}, [])
    sc = [a for a in out["achievements"] if a["id"] == "skin-changer"][0]
    free_n = sum(1 for s in g._skins() if s.get("free"))
    assert sc["current"] == free_n and not sc["earned"]   # only the free skins to start
    # meet every earnable skin's own grant (metric->threshold, self-computed from the
    # roster) -> every skin unlocked -> Skin-Changer's current == the full skin count.
    m = {}
    for a in g._roster():
        if a.get("skin"):
            m[a["metric"]] = max(m.get(a["metric"], 0), a["threshold"])
    sc = [a for a in g.compute_achievements(m, [])["achievements"]
          if a["id"] == "skin-changer"][0]
    assert sc["current"] == len(g._skins()) and sc["earned"]


@needs_donor
def test_completionist_requires_every_non_feat():
    # every non-feat, non-banner achievement satisfied -> completionist earns
    full = {a["metric"]: 10 ** 9 for a in g._roster()}
    out = g.compute_achievements(full, [])
    by = {a["id"]: a for a in out["achievements"]}
    assert by["completionist"]["earned"]
    # drop one ladder metric below its crown -> completionist un-earns
    partial = dict(full, images=49999)                    # great-library is banner-
    out2 = g.compute_achievements(partial, [])            # exempt, loremaster isn't
    by2 = {a["id"]: a for a in out2["achievements"]}
    assert by2["loremaster"]["earned"] and not by2["the-great-library"]["earned"]
    assert by2["completionist"]["earned"]                 # banner crown NOT required
    out3 = g.compute_achievements(dict(full, images=24999), [])
    assert not [a for a in out3["achievements"]
                if a["id"] == "completionist"][0]["earned"]


# ---- the API: masking, telemetry merge, beacon -------------------------------

def _client(tmp_path, rows):
    save_catalog(tmp_path / "catalog.db", rows)
    return login_client(tmp_path), tmp_path


@needs_donor
def test_api_masks_hidden_feats_and_cloaks_tab(tmp_path):
    cli, out = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                       created_at="2025-01-01T00:00:00")])
    with mock.patch("datetime.datetime", _FixedNoon):   # never trip Night Owl mid-test
        d = cli.get("/api/achievements").get_json()
    # every hidden feat is unearned here, and they COLLAPSE to one placeholder
    # (2026-08-13): the payload must not reveal how many remain undiscovered --
    # previously the array carried one hidden-feat-N entry per secret, so its
    # length counted them for anyone reading devtools
    n_hidden = sum(1 for a in g._roster() if a.get("hidden"))
    assert n_hidden > 1                     # the collapse is genuinely collapsing
    assert len(d["achievements"]) == len(g._roster()) - n_hidden + 1
    hidden = [a for a in d["achievements"] if a["tier"] == "feat" and not a["earned"]]
    assert len(hidden) == 1 and hidden[0]["name"] == "???"
    # devtools must not spoil the secrets: no real id/metric on the masked card,
    # and the metrics echo drops every still-hidden feat's counter
    assert hidden[0]["id"] == "hidden-feat" and hidden[0]["metric"] == ""
    assert hidden[0]["roast"] == "" and hidden[0]["roast_nsfw"] == ""
    # Self-computed: a metric used ONLY by hidden achievements (all unearned here) must be
    # stripped from the echo; a metric shared with any visible achievement must survive.
    by_metric = {}
    for a in g._roster():
        by_metric.setdefault(a["metric"], []).append(a)
    hidden_only = {mtr for mtr, rows in by_metric.items() if all(r.get("hidden") for r in rows)}
    assert hidden_only                        # the roster really does have hidden-only metrics
    for secret in hidden_only:
        assert secret not in d["metrics"], secret
    assert "days_used" in d["metrics"]        # shared with the visible Vigil ladder
    # roasts only ride EARNED achievements; nsfw stays locked pre-Triggered
    fl = [a for a in d["achievements"] if a["id"] == "first-light"][0]
    assert fl["earned"] and fl["roast"] and fl["roast_nsfw"] == ""
    assert d["unleash_available"] is False
    # the day visit was marked (The Vigil)
    assert g.telemetry_metrics(out)["days_used"] == 1


@needs_donor
def test_points_rung_scaled_feats_zero_and_aggregates():
    from moonglade_gallery import compute_achievements, achievement_points, _roster
    by_id = {a["id"]: a for a in _roster()}
    # the Archive (images) ladder reproduces the owner's locked example exactly
    seq = ["first-light", "archivist", "hoardsmith", "loremaster", "the-great-library"]
    assert [achievement_points(by_id[i]) for i in seq] == [5, 15, 35, 65, 70]
    # every feat scores 0 (pure flair; keeps the points total from hinting at hidden feats)
    assert all(achievement_points(a) == 0 for a in _roster() if a["tier"] == "feat")
    # a single-step milestone/mastery = flat tier base (rung 1)
    assert achievement_points(by_id["master-of-the-loom"]) == 25   # epic
    assert achievement_points(by_id["keeper-of-order"]) == 10       # rare
    # compute emits per-achievement points + self-consistent aggregates
    r = compute_achievements({}, seen=())
    assert all("points" in a for a in r["achievements"])
    # possible_points is the roster sum (self-computed -- no magic total), and feats never
    # add to it (they score 0), so it can never hint at how many hidden feats exist.
    assert r["possible_points"] == sum(achievement_points(a) for a in _roster())
    assert r["earned_points"] == sum(a["points"] for a in r["achievements"] if a["earned"])


@needs_donor
def test_api_masked_feats_leak_no_points(tmp_path):
    cli, out = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                       created_at="2025-01-01T00:00:00")])
    with mock.patch("datetime.datetime", _FixedNoon):
        d = cli.get("/api/achievements").get_json()
    assert "earned_points" in d and "possible_points" in d
    masked = [a for a in d["achievements"] if a["name"] == "???"]
    assert masked and all(a["points"] == 0 for a in masked)


@needs_donor
def test_earn_dates_stamped_persisted_and_no_leak(tmp_path):
    cli, out = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                       created_at="2025-01-01T00:00:00")])
    g.telem_flag("first_sync_done", out_dir=out)   # past first sync -> achievements recognize
    with mock.patch("datetime.datetime", _FixedNoon):
        d = cli.get("/api/achievements?mark=1").get_json()
    assert "earned_at" in d
    earned_ids = {a["id"] for a in d["achievements"] if a["earned"]}
    assert earned_ids and all(i in d["earned_at"] for i in earned_ids)   # every earned gets a date
    masked = [a for a in d["achievements"] if a["name"] == "???"]        # hidden feats never leak a date
    assert all(a["id"] not in d["earned_at"] for a in masked)
    st = g.load_ach_state(out)                                           # persisted to disk
    assert st["earned_at"] and all(i in st["earned_at"] for i in earned_ids)


def test_badge_thumb_cache(tmp_path):
    from PIL import Image
    # bundle-v2: badge masters live at the CODED badges dir (built via
    # g._role_dir, never a hardcoded hex literal)
    bdir = g._role_dir("badges"); bdir.mkdir(parents=True)
    Image.new("RGBA", (2000, 2000), (10, 20, 30, 255)).save(bdir / "loremaster.png")
    p = g._badge_thumb(tmp_path, "loremaster", size=256)
    assert p and Path(p).exists() and max(Image.open(p).size) <= 256
    assert g._badge_thumb(tmp_path, "loremaster") == p     # cached copy reused
    assert g._badge_thumb(tmp_path, "does-not-exist") is None
    # The cache lives OUTSIDE the coded branding tree (SCOPE_bundle-v2-branding
    # constraint 3: the tree must keep reading as the empty scaffold), under
    # out_dir/gallery/cache/_badges/ -- gallery/ being what every walker skips.
    assert Path(p) == g.badge_cache_dir(tmp_path) / "loremaster.png"
    assert Path(p).parent == tmp_path / "gallery" / "cache" / "_badges"
    assert g.branding_root() not in Path(p).parents
    assert not (g.branding_root() / "_thumbs").exists()


@needs_donor
def test_api_ach_event_beacon(tmp_path):
    cli, out = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                       created_at="2025-01-01T00:00:00")])
    assert cli.post("/api/ach-event", json={"event": "konami"}).status_code == 200
    assert g.telemetry_metrics(out)["konami_triggered"] == 1
    cli.post("/api/ach-event", json={"event": "docs"})
    assert g.telemetry_metrics(out)["docs_opened"] == 1
    # narrator pokes count up and snap at 5 (Triggered)
    for i in range(1, 5):
        r = cli.post("/api/ach-event", json={"event": "narrator"}).get_json()
        assert r["pokes"] == i and r["snapped"] is False
    r = cli.post("/api/ach-event", json={"event": "narrator"}).get_json()
    assert r["pokes"] == 5 and r["snapped"] is True
    d = cli.get("/api/achievements").get_json()
    trg = [a for a in d["achievements"] if a["id"] == "triggered"][0]
    assert trg["earned"] and trg["name"] == "Triggered"
    assert d["feats_revealed"] is True and d["unleash_available"] is True
    # unknown events are rejected
    assert cli.post("/api/ach-event", json={"event": "nope"}).status_code == 400


@needs_donor
def test_api_skin_change_bumps_interior_decorator(tmp_path):
    cli, out = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                       created_at="2025-01-01T00:00:00")])
    cli.post("/api/skin", json={"skin": "nightfallen"})
    assert g.telemetry_metrics(out)["skin_changed_runs"] == 1
    cli.post("/api/skin", json={"skin": "nightfallen"})   # same skin: no re-bump
    assert g.telemetry_metrics(out)["skin_changed_runs"] == 1


def test_new_sql_metrics(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", source="api",
             created_at="2026-01-01T10:00:00", art_tags="night,elf"),
        _row(media_id="2", filename="b_2.png", source="api",
             created_at="2026-01-01T11:00:00", art_tags="Night, moon"),
        _row(media_id="3", filename="c_3.png", source="local",
             created_at="2026-01-02T09:00:00"),
        _row(media_id="4", filename="d_4.png",              # site gen: not local
             created_at="2026-01-01T12:00:00"),
    ])
    m = g.achievement_metrics(tmp_path / "catalog.db")
    assert m["local_gens"] == 3                # api + local, NOT the site gen
    assert m["gens_in_a_day"] == 2             # two on 2026-01-01
    assert m["distinct_keywords"] == 3         # night, elf, moon (case-folded)


def test_time_capsule_only_fires_on_old_insert(tmp_path):
    import moonglade_backup as core
    core._check_time_capsule("2020-01-01T00:00:00", tmp_path)
    assert g.telemetry_metrics(tmp_path)["old_piece_backed_up"] == 1
    (tmp_path / "telemetry.json").unlink()
    core._check_time_capsule("2099-01-01T00:00:00", tmp_path)   # young: no fire
    core._check_time_capsule("", tmp_path)                       # blank: no crash
    assert g.telemetry_metrics(tmp_path).get("old_piece_backed_up", 0) == 0


# ---- per-criterion checklists (closed-universe set masteries) ----------------

@needs_donor
def test_achievement_criteria_pure():
    from moonglade_gallery import achievement_criteria
    c = achievement_criteria({"tools": ["edit", "fix"], "video_modes": ["i2v"]})
    assert {x["key"]: x["done"] for x in c["full-toolbox"]} == {
        "edit": True, "enhance": False, "fix": True}
    assert {x["key"]: x["done"] for x in c["master-of-the-loom"]} == {
        "i2v": True, "flf": False, "r2v": False}
    # a missing set + a hostile non-list set both read as nothing-done, never raise
    assert all(not x["done"] for x in achievement_criteria({"tools": 7})["full-toolbox"])
    assert all(not x["done"] for x in achievement_criteria({})["master-of-the-loom"])
    # labels are carried for the UI, order preserved
    assert [x["label"] for x in c["full-toolbox"]] == ["Edit", "Enhance", "Fix"]


@needs_donor
def test_compute_attaches_criteria_only_with_sets():
    from moonglade_gallery import compute_achievements
    r = compute_achievements({"tools_used": 2}, sets={"tools": ["edit", "enhance"]})
    by = {a["id"]: a for a in r["achievements"]}
    assert {x["key"]: x["done"] for x in by["full-toolbox"]["criteria"]} == {
        "edit": True, "enhance": True, "fix": False}
    # a non-checklist achievement never grows the key
    assert "criteria" not in by["first-light"]
    # back-compat: metrics-only callers (no sets) get no criteria anywhere
    assert all("criteria" not in a for a in compute_achievements({"tools_used": 3})["achievements"])


@needs_donor
def test_api_criteria_on_set_masteries(tmp_path):
    g.telem_set_add("tools", "edit", out_dir=tmp_path)
    g.telem_set_add("tools", "fix", out_dir=tmp_path)
    cli, out = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                       created_at="2025-01-01T00:00:00")])
    with mock.patch("datetime.datetime", _FixedNoon):
        d = cli.get("/api/achievements").get_json()
    ft = [a for a in d["achievements"] if a["id"] == "full-toolbox"][0]
    assert {x["key"]: x["done"] for x in ft["criteria"]} == {
        "edit": True, "enhance": False, "fix": True}


# ---- Folio expansion (Phase 2): new metrics, meta-loop, streaks, seal, route hooks -------

def test_folio_catalog_metrics(tmp_path):
    """The new catalog-derived Folio metrics -- rated / loras_distinct / palindrome_seeds /
    top_word_uses -- are all COUNT-only: the bundle carries integers, never a rating value,
    LoRA name, seed value, or prompt word. Donor-independent (builds its own catalog)."""
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", rating="4", loras="styleA:0.8, charB:1",
             seed="12321", prompt_preview="a knight in a castle knight"),
        _row(media_id="2", filename="b_2.png", rating="0", loras="styleA:0.5",
             seed="45654", prompt_preview="knight on a horse"),
        _row(media_id="3", filename="c_3.png", rating="", loras="charB:0.7, newC",
             seed="-98789", prompt_preview="dragon"),
        _row(media_id="4", filename="d_4.png", rating="5", loras="",
             seed="123", prompt_preview="knight"),        # seed too short (3 digits)
    ])
    m = g.achievement_metrics(tmp_path / "catalog.db")
    assert m["rated"] == 2               # media 1 (4) + 4 (5); "0" and "" don't count (health-identical)
    assert m["loras_distinct"] == 3      # styleA, charB, newC -- weights dropped, deduped
    assert m["palindrome_seeds"] == 3    # 12321, 45654, 98789 (after lstrip '-'); 123 is <5 digits
    assert m["top_word_uses"] == 4       # "knight" x4 across the four previews (the word never leaves)
    # an empty catalog degrades to 0s, never KeyErrors
    save_catalog(tmp_path / "empty.db", [])
    z = g.achievement_metrics(tmp_path / "empty.db")
    for k in ("rated", "loras_distinct", "palindrome_seeds", "top_word_uses"):
        assert z[k] == 0


def test_best_day_streak_and_keyed_daylists(tmp_path):
    """The keyed day-list ledger (day_lists) + _best_day_streak feed the streak/long-watch
    metrics. telem_mark_day(keys=...) writes per-key lists WITHOUT touching the legacy flat
    `days`, and the streak is a high-water mark a later gap never un-earns."""
    assert g._best_day_streak([]) == 0
    assert g._best_day_streak(["2026-01-01", "2026-01-02", "2026-01-03"]) == 3
    assert g._best_day_streak(["2026-01-01", "2026-01-03", "2026-01-04"]) == 2   # gap resets the run
    assert g._best_day_streak(["2026-01-05", "2026-01-02", "2026-01-01"]) == 2   # order-independent
    assert g._best_day_streak(["nonsense", "2026-01-01"]) == 1                    # bad dates skipped
    # keyed mark writes only the named lists; the legacy flat ledger stays empty + idempotent
    g.telem_mark_day(out_dir=tmp_path, keys=("gen_days", "active_days"))
    g.telem_mark_day(out_dir=tmp_path, keys=("gen_days", "active_days"))          # same day once
    t = g.load_telemetry(tmp_path)
    assert len(t["day_lists"]["gen_days"]) == 1 and len(t["day_lists"]["active_days"]) == 1
    assert t["days"] == []                                                        # legacy Vigil untouched
    # a synthetic multi-day store proves the metric wiring end to end
    (tmp_path / "telemetry.json").write_text(json.dumps({
        "counters": {}, "maxima": {}, "sets": {}, "flags": {}, "days": [],
        "day_lists": {"gen_days": ["2026-02-01", "2026-02-02", "2026-02-03"],
                      "curation_days": ["2026-03-01", "2026-03-03"],
                      "active_days": ["2026-02-01", "2026-02-02", "2026-03-01"]}}), encoding="utf-8")
    m = g.telemetry_metrics(tmp_path)
    assert m["gen_streak"] == 3 and m["curation_streak"] == 1
    assert m["distinct_active_days"] == 3


@needs_donor
def test_requires_meta_earns_when_prereqs_earned():
    """The generic `requires` meta-loop (the Glories + The Way Is Shut): a meta earns exactly
    when every prereq id is earned. Self-computed from the roster's own `requires` lists; the
    prereq list itself never reaches the payload (compute builds entries without copying it)."""
    roster = g._roster()
    by_id_r = {a["id"]: a for a in roster}
    metas = [a for a in roster if a.get("requires")]
    assert metas                                             # the roster really has requires-metas
    # the built entries must NOT carry a `requires` field (it is a seal -- never leaks)
    built = {a["id"]: a for a in g.compute_achievements({}, [])["achievements"]}
    assert all("requires" not in built[m["id"]] for m in metas)
    for meta in metas:
        reqs = meta["requires"]
        full = {a["metric"]: 10 ** 9 for a in roster}        # meet every prereq's own threshold
        by = {a["id"]: a for a in g.compute_achievements(full, [])["achievements"]}
        assert by[meta["id"]]["earned"] and by[meta["id"]]["current"] == len(reqs), meta["id"]
        # drop one threshold-driven prereq below its bar -> the meta un-earns
        drop = next(r for r in reqs if not by_id_r[r].get("requires"))
        partial = dict(full, **{by_id_r[drop]["metric"]: 0})
        by2 = {a["id"]: a for a in g.compute_achievements(partial, [])["achievements"]}
        assert not by2[meta["id"]]["earned"], meta["id"]


@needs_donor
def test_contest_metrics_default_to_zero(tmp_path):
    """Come on Down / Plinko / ... / Laureate: contest_entries AND contest_wins have no catalog
    or telemetry source yet, so both must default to 0 -- the flatten never invents them and
    the contest ladder + Laureate stay locked until a real signal lands."""
    tm = g.telemetry_metrics(tmp_path)                        # fresh store
    assert tm.get("contest_entries", 0) == 0 and tm.get("contest_wins", 0) == 0
    out = g.compute_achievements({}, [])                      # no contest signal at all
    by = {a["id"]: a for a in out["achievements"]}
    contest_ids = [a["id"] for a in g._roster()
                   if a["metric"] in ("contest_entries", "contest_wins")]
    assert contest_ids                                        # both metrics are really in the roster
    assert {"contest_entries", "contest_wins"} == {a["metric"] for a in g._roster()
                                                   if a["metric"] in ("contest_entries", "contest_wins")}
    for aid in contest_ids:
        assert by[aid]["current"] == 0 and not by[aid]["earned"], aid


@needs_donor
def test_api_masks_every_hidden_only_metric(tmp_path):
    """The general seal behind the ??? collapse: a metric used ONLY by hidden achievements must
    never appear in /api/achievements' metric echo while those achievements are unearned. Self-
    computed from the roster, so a NEW hidden-only metric (palindrome_seeds, contest_wins, the
    metas' `meta`) can never slip into `still_visible`."""
    cli, out = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                       created_at="2025-01-01T00:00:00")])
    with mock.patch("datetime.datetime", _FixedNoon):
        d = cli.get("/api/achievements").get_json()
    by_metric = {}
    for a in g._roster():
        by_metric.setdefault(a["metric"], []).append(a)
    hidden_only = {mtr for mtr, rows in by_metric.items()
                   if mtr and all(r.get("hidden") for r in rows)}
    assert hidden_only                                        # the roster really has hidden-only metrics
    assert {"palindrome_seeds", "contest_wins", "meta"} <= hidden_only
    leaked = hidden_only & set(d.get("metrics", {}))
    assert not leaked, leaked                                 # not one hidden-only metric echoed


def _arm_mirror_bridge(monkeypatch, core):
    """Mirror ARMED + every spend/collect entry point stubbed -- no network, no spend."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "mirror_enabled", lambda: True)
    monkeypatch.setattr(core, "make_mirror_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "submit_generation", lambda *a, **k: "T-ENH-9")


def test_bridge_enhance_defers_to_terminal_and_counts_only_presets(tmp_path, monkeypatch):
    """Step 6b (corrected): a bridge-preset enhance joins the `bridge_enhance` set and bumps
    bridge_gens ONLY at terminal success -- parity with enhance_workflows, so a submit that is
    later reaped/failed never counts. Nothing is recorded at submit. A non-preset enhance never
    touches the bridge set even at terminal. bridge_enhance_distinct = len(the set)."""
    import moonglade_backup as core
    _arm_mirror_bridge(monkeypatch, core)
    save_catalog(tmp_path / "catalog.db", [])
    cli = login_client(tmp_path)
    preset = core.BRIDGE_ENHANCE_PRESETS[0]["workflow_name"]
    r = cli.post("/api/enhance", json={"source": "srcABC", "workflow_name": preset})
    assert r.status_code == 200
    tid = r.get_json()["task_id"]
    assert g.telemetry_metrics(tmp_path)["bridge_enhance_distinct"] == 0   # DEFERRED: nothing at submit
    # drive terminal success -> _fire_enhance_telemetry fires the bridge-gated set-add + bump
    monkeypatch.setattr(core, "generation_status", lambda s, t: {"phase": "done", "paid_credit": 0})
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, t, out, **k: {"media_ids": ["OUT1"], "saved": 1, "is_video": False})
    cli.get("/api/task-status", query_string={"task_id": tid})
    assert g.telemetry_metrics(tmp_path)["bridge_enhance_distinct"] == 1
    assert g.load_telemetry(tmp_path)["sets"]["bridge_enhance"] == [preset]
    assert g.telemetry_metrics(tmp_path).get("bridge_gens", 0) == 1        # Speak, Friend: bridge-only
    # a second poll of the finished task must not double-count
    cli.get("/api/task-status", query_string={"task_id": tid})
    assert g.telemetry_metrics(tmp_path)["bridge_enhance_distinct"] == 1
    # a NON-preset enhance, even at terminal, never joins the bridge set (distinct task id)
    monkeypatch.setattr(core, "submit_generation", lambda *a, **k: "T-ENH-OTHER")
    r2 = cli.post("/api/enhance", json={"source": "srcDEF", "workflow_id": "1793447160259872021"})
    cli.get("/api/task-status", query_string={"task_id": r2.get_json()["task_id"]})
    assert g.telemetry_metrics(tmp_path)["bridge_enhance_distinct"] == 1   # unchanged (non-preset)


def test_scene_and_gen_daymark_hooks_fire_on_terminal_success(tmp_path, monkeypatch):
    """Doorwarden (scenes_used) defers to terminal success exactly like enhance, and the collect
    choke marks gen_days + active_days (Seven Candles / Long Vigil). Nothing counts at submit or
    on a failure."""
    import moonglade_backup as core
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "mirror_enabled", lambda: True)
    monkeypatch.setattr(core, "make_mirror_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "submit_scene", lambda *a, **k: "T-SCENE-1")
    save_catalog(tmp_path / "catalog.db", [])
    cli = login_client(tmp_path)
    r = cli.post("/api/scene", json={"scene_id": "the-sun", "media_ids": ["srcABC"]})
    assert r.get_json().get("task_id") == "T-SCENE-1"
    assert g.telemetry_metrics(tmp_path)["scenes_used"] == 0          # deferred: nothing at submit
    monkeypatch.setattr(core, "generation_status",
                        lambda s, tid: {"phase": "done", "paid_credit": 0})
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: {"media_ids": ["OUT1"], "saved": 1, "is_video": False})
    cli.get("/api/task-status", query_string={"task_id": "T-SCENE-1"})
    assert g.telemetry_metrics(tmp_path)["scenes_used"] == 1
    assert g.load_telemetry(tmp_path)["sets"]["scenes"] == ["the-sun"]
    tel = g.load_telemetry(tmp_path)                                   # collect choke marked today
    assert tel["day_lists"]["gen_days"] and tel["day_lists"]["active_days"]
    # a second poll of the same finished task must not double-count
    cli.get("/api/task-status", query_string={"task_id": "T-SCENE-1"})
    assert g.telemetry_metrics(tmp_path)["scenes_used"] == 1


def test_train_submit_hook_bumps_loras_trained(tmp_path, monkeypatch):
    """The Academy (loras_trained): a confirmed, free LoRA training submit bumps the counter
    once. Uses the same CSRF + validate/quota/submit stubbing shape test_panel already uses."""
    import moonglade_backup as core
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "validate_training", lambda *a, **k: "nel druid")
    monkeypatch.setattr(core, "training_free_quota", lambda s: 9)
    monkeypatch.setattr(core, "training_price_for_version", lambda v: None)
    monkeypatch.setattr(core, "submit_training", lambda *a, **k: {"id": "trn1", "refId": "model9"})
    save_catalog(tmp_path / "catalog.db", [])
    cli = login_client(tmp_path)
    csrf = cli.get("/api/panel/summary").get_json()["csrf"]
    body = {"base_model_id": "bm1", "media_ids": [str(i) for i in range(12)],
            "title": "Nel", "trigger_words": "nel druid", "category": "character",
            "confirm": True, "csrf": csrf}
    assert g.telemetry_metrics(tmp_path).get("loras_trained", 0) == 0
    d = cli.post("/api/train/submit", json=body).get_json()
    assert d.get("submitted") is True
    assert g.telemetry_metrics(tmp_path)["loras_trained"] == 1
