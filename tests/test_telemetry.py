"""The achievement telemetry layer: the persisted counter store (telemetry.json),
its flattening into the metric namespace, the 57-roster compute post-passes, the
hidden-feat masking on /api/achievements, and the /api/ach-event beacon. All
local + fail-soft -- a telemetry hiccup must never break a page or a backup."""
import json

import datetime as _dt
from unittest import mock

import pixai_gallery as g
from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog


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


# ---- the 57 roster + compute post-passes ------------------------------------

def test_roster_shape():
    assert len(g.ACHIEVEMENTS) == 57
    feats = [a for a in g.ACHIEVEMENTS if a["tier"] == "feat"]
    assert len(feats) == 11 and all(a.get("hidden") for a in feats)
    assert sum(1 for a in g.ACHIEVEMENTS if a.get("banner_reward")) == 1
    assert all(a["threshold"] >= 1 for a in g.ACHIEVEMENTS)
    assert all(a.get("roast") and a.get("roast_nsfw") for a in g.ACHIEVEMENTS)


def test_skin_changer_counts_unlocked_skins():
    out = g.compute_achievements({}, [])
    sc = [a for a in out["achievements"] if a["id"] == "skin-changer"][0]
    assert sc["current"] == 2 and not sc["earned"]        # the two free skins
    # 10k images + 50 videos + 25 models unlock all three earnable skins -> 5
    m = {"images": 10000, "videos": 50, "models": 25}
    sc = [a for a in g.compute_achievements(m, [])["achievements"]
          if a["id"] == "skin-changer"][0]
    assert sc["current"] == 5 and sc["earned"]


def test_completionist_requires_every_non_feat():
    # every non-feat, non-banner achievement satisfied -> completionist earns
    full = {a["metric"]: 10 ** 9 for a in g.ACHIEVEMENTS}
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
    return create_app(tmp_path).test_client(), tmp_path


def test_api_masks_hidden_feats_and_cloaks_tab(tmp_path):
    cli, out = _client(tmp_path, [_row(media_id="1", filename="a_1.png",
                                       created_at="2025-01-01T00:00:00")])
    with mock.patch("datetime.datetime", _FixedNoon):   # never trip Night Owl mid-test
        d = cli.get("/api/achievements").get_json()
    assert len(d["achievements"]) == 57
    hidden = [a for a in d["achievements"] if a["tier"] == "feat" and not a["earned"]]
    assert hidden and all(a["name"] == "???" for a in hidden)
    assert all(a["roast"] == "" and a["roast_nsfw"] == "" for a in hidden)
    # devtools must not spoil the secrets: no real id/metric on masked cards,
    # and the metrics echo drops every still-hidden feat's counter
    assert all(a["id"].startswith("hidden-feat-") for a in hidden)
    assert all(a["metric"] == "" for a in hidden)
    for secret in ("konami_triggered", "narrator_pokes", "session_hour",
                   "docs_opened", "old_piece_backed_up"):
        assert secret not in d["metrics"]
    assert "days_used" in d["metrics"]        # shared with the visible Vigil ladder
    # roasts only ride EARNED achievements; nsfw stays locked pre-Triggered
    fl = [a for a in d["achievements"] if a["id"] == "first-light"][0]
    assert fl["earned"] and fl["roast"] and fl["roast_nsfw"] == ""
    assert d["unleash_available"] is False
    # the day visit was marked (The Vigil)
    assert g.telemetry_metrics(out)["days_used"] == 1


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
    import pixai_gallery_backup as core
    core._check_time_capsule("2020-01-01T00:00:00", tmp_path)
    assert g.telemetry_metrics(tmp_path)["old_piece_backed_up"] == 1
    (tmp_path / "telemetry.json").unlink()
    core._check_time_capsule("2099-01-01T00:00:00", tmp_path)   # young: no fire
    core._check_time_capsule("", tmp_path)                       # blank: no crash
    assert g.telemetry_metrics(tmp_path).get("old_piece_backed_up", 0) == 0
