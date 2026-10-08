"""The Folio for completionists, server side (Session O, O1; Small Calls L2's Marks row).

  * achievement_progress(): the "N to go" numbers for ONE unearned honor, and the cases that must
    say nothing -- a feat of any kind, an earned honor, an unmeasured metric.
  * /api/achievements: `progress` rides an unearned non-feat entry whose metric the server
    measures, and NEVER a feat, an earned entry or an unmeasured metric; no hidden feat is in the
    payload in any form; `relics.marks` lists earned, awarded marks only.

Every roster here is SYNTHETIC (invented ids, names and metrics), so nothing asserts on a real
honor and these run in public CI. The two tests that read the sealed roster's shape carry the
sealed_donor_present gate.
"""
import json
from pathlib import Path

import pytest

from moonglade import container as _mc
from moonglade import gallery as g
from moonglade.gallery import CATALOG_FIELDS, save_catalog

from tests import synthetic_feats as sf
from tests.conftest import clear_sealed_caches, login_client

HIDDEN_ID = "synth-hidden-feat"
HIDDEN_NAME = "Synthetic Hidden Feat"
HIDDEN_METRIC = "synth_hidden_metric"
HIDDEN_THRESHOLD = 7331


def _ach(aid, name, tier, bucket, metric, threshold, **kw):
    e = {"id": aid, "name": name, "icon": "X", "desc": "Synthetic " + name,
         "tier": tier, "bucket": bucket, "metric": metric, "threshold": threshold,
         "roast": "", "roast_nsfw": ""}
    e.update(kw)
    return e


def _roster():
    return [
        _ach("syn-img-1", "Synthetic Rung One", "common", "ladder", "images", 1,
             track="syn-images", rung=1, rungs_total=3),
        _ach("syn-img-2", "Synthetic Rung Two", "rare", "ladder", "images", 400,
             track="syn-images", rung=2, rungs_total=3),
        _ach("syn-img-3", "Synthetic Rung Three", "epic", "ladder", "images", 4000,
             track="syn-images", rung=3, rungs_total=3),
        # a counter nothing has bumped yet: measured, and still zero
        _ach("syn-claims", "Synthetic Claims", "common", "milestone", "claims", 4),
        # a metric nobody counts
        _ach("syn-mystery", "Synthetic Mystery", "rare", "mastery", "synth_unmeasured_metric", 3),
        # a hidden feat that SHARES a measured metric with a visible ladder
        _ach(HIDDEN_ID, HIDDEN_NAME, "feat", "feat", HIDDEN_METRIC, HIDDEN_THRESHOLD,
             hidden=True, riddle="test riddle"),
        _ach("syn-feat-shown", "Synthetic Shown Feat", "feat", "feat", "images", 40000,
             hidden=True, riddle="test riddle two"),
        # a feat-tier meta that is NOT hidden: it rides the array unearned, and must still
        # carry no count
        _ach("syn-meta", "Synthetic Glory", "feat", "meta", "synth_meta_metric", 2,
             requires=["syn-img-3"]),
    ]


def _seed(tmp_path):
    defs = {"roster": _roster(), "skins": [], "skin_unlock": {}, "ach_criteria": {},
            "ladder_tracks": [{"id": "syn-images", "name": "Synthetic Images", "metric": "images"}]}
    _mc.write_container(g._container_path(), {"_seed.txt": b"x"},
                        {"achievements": json.dumps(defs).encode("utf-8")})
    clear_sealed_caches()


def _marks(bindings):
    """marks.json + art for {mark_id: awarding achievement id or ''}. Written BEFORE the app
    is built (create_app sweeps the tree), the way dev/tests/test_branding.py does."""
    mdir = g._role_dir("marks")
    mdir.mkdir(parents=True, exist_ok=True)
    entries = []
    for mid, unlock in bindings.items():
        (mdir / (mid + ".png")).write_bytes(b"\x89PNG fake")
        e = {"id": mid, "label": "Label " + mid, "kind": "tile"}
        if unlock:
            e["unlock"] = unlock
        entries.append(e)
    (mdir / "marks.json").write_text(json.dumps({"marks": entries}), encoding="utf-8")


def _client(tmp_path, marks=None, rows=3):
    save_catalog(tmp_path / "catalog.db", [
        {f: "" for f in CATALOG_FIELDS} | {
            "media_id": str(i + 1), "filename": "a_%d.png" % (i + 1),
            "created_at": "2025-01-01T00:00:00"} for i in range(rows)])
    _seed(tmp_path)
    if marks:
        _marks(marks)
    return login_client(tmp_path)


def _get(cli):
    return cli.get("/api/achievements").get_json()


def _by_id(d):
    return {a["id"]: a for a in d["achievements"]}


# ---- the pure function ----------------------------------------------------------------

def _entry(**kw):
    e = {"id": "x", "tier": "common", "bucket": "ladder", "metric": "images",
         "threshold": 10, "current": 4, "earned": False}
    e.update(kw)
    return e


def test_progress_is_threshold_minus_current_and_the_true_fraction():
    p = g.achievement_progress(_entry(), {"images": 4})
    assert p == {"current": 4, "threshold": 10, "left": 6, "fraction": 0.4}


def test_progress_never_goes_negative_or_past_a_full_moon():
    p = g.achievement_progress(_entry(current=12), {"images": 12})
    assert p["left"] == 0 and p["fraction"] == 1.0


@pytest.mark.parametrize("entry", [
    _entry(tier="feat", bucket="feat"),
    _entry(tier="feat", bucket="ladder"),
    _entry(tier="common", bucket="feat"),
    _entry(tier="feat", bucket="meta"),
    _entry(bucket="meta"),
])
def test_a_feat_of_any_kind_has_no_progress_even_on_a_measured_metric(entry):
    assert g.achievement_progress(entry, {"images": 4}) is None


def test_an_earned_entry_has_no_progress():
    assert g.achievement_progress(_entry(earned=True), {"images": 400}) is None


def test_an_unmeasured_metric_has_no_progress():
    assert g.achievement_progress(_entry(metric="nobody_counts_this"), {"images": 4}) is None
    assert g.achievement_progress(_entry(metric="images"), {}) is None
    assert g.achievement_progress(_entry(), None) is None


def test_a_measured_counter_nothing_has_bumped_yet_is_a_true_zero():
    p = g.achievement_progress(_entry(metric="claims", threshold=4, current=0), {"images": 4})
    assert p == {"current": 0, "threshold": 4, "left": 4, "fraction": 0.0}


@pytest.mark.parametrize("bad", [0, -3, None, "many", ""])
def test_a_threshold_that_is_not_a_positive_number_has_no_progress(bad):
    assert g.achievement_progress(_entry(threshold=bad), {"images": 4}) is None


def test_the_measured_set_names_no_feat_metric(sealed_donor_present):
    # Feats are refused before this set is ever read; it must not name one either, so the
    # public source never lists a hidden feat's metric. Donor-gated: the feats' metrics live
    # only in the sealed roster. "Feat-only", because a feat may share its metric with a
    # visible ladder, and that metric is public already. The failure gives a count, never a
    # name.
    for k in g._MEASURED_METRICS:
        assert isinstance(k, str) and k

    def is_feat(a):
        return a.get("tier") == "feat" or a.get("bucket") in ("feat", "meta")
    feat_metrics = {a.get("metric") for a in g._roster() if is_feat(a)}
    nonfeat_metrics = {a.get("metric") for a in g._roster() if not is_feat(a)}
    feat_only = feat_metrics - nonfeat_metrics
    leaked = len(feat_only & set(g._MEASURED_METRICS))
    assert leaked == 0, "%d feat-only metric(s) named in _MEASURED_METRICS" % leaked


# ---- the route --------------------------------------------------------------------------

def test_progress_rides_only_unearned_measured_non_feat_entries(tmp_path):
    cli = _client(tmp_path)
    d = _get(cli)
    imgs = d["metrics"]["images"]
    a = _by_id(d)
    assert a["syn-img-1"]["earned"] is True and "progress" not in a["syn-img-1"]
    p = a["syn-img-2"]["progress"]
    assert p["current"] == imgs and p["threshold"] == 400
    assert p["left"] == 400 - imgs and p["fraction"] == pytest.approx(imgs / 400)
    assert a["syn-claims"]["progress"] == {"current": 0, "threshold": 4, "left": 4, "fraction": 0.0}
    assert "progress" not in a["syn-mystery"]


def test_no_feat_ever_carries_progress_and_no_hidden_feat_is_in_the_payload(tmp_path):
    cli = _client(tmp_path)
    d = _get(cli)
    assert "syn-meta" in _by_id(d)                          # an unearned, un-hidden feat is listed
    sf.earn(tmp_path, "syn-feat-shown")                     # an earned hidden feat shows up...
    d = _get(cli)
    assert "syn-feat-shown" in _by_id(d)
    text = json.dumps(d)
    for a in d["achievements"]:
        if a["tier"] == "feat" or a["bucket"] in ("feat", "meta"):
            assert "progress" not in a, "a feat carries a count"
    # ...but the still-hidden one is nowhere: not its id, name, metric or distinctive number.
    assert HIDDEN_ID not in text and HIDDEN_NAME not in text
    assert HIDDEN_METRIC not in text and str(HIDDEN_THRESHOLD) not in text


def test_the_payload_before_any_feat_is_earned_says_nothing_about_them(tmp_path):
    cli = _client(tmp_path)
    d = _get(cli)
    text = json.dumps(d)
    for needle in (HIDDEN_ID, HIDDEN_NAME, HIDDEN_METRIC, "syn-feat-shown",
                   "Synthetic Shown Feat"):
        assert needle not in text, needle


def test_opening_the_route_writes_no_progress_anywhere(tmp_path):
    """Nothing writes on open: the achievement state file gains nothing from a plain read
    (no ?mark=1), so the count is computed, never stored."""
    cli = _client(tmp_path)
    before = g.load_ach_state(tmp_path)
    _get(cli)
    assert g.load_ach_state(tmp_path) == before


# ---- L2: the Marks row ---------------------------------------------------------------------

def test_relics_marks_are_earned_and_awarded_only(tmp_path):
    cli = _client(tmp_path, marks={
        "mk_free": "",                     # free: everyone has it, not a relic
        "mk_won": "syn-img-1",             # awarded and earned
        "mk_locked": "syn-img-3",          # awarded, not earned
        "mk_hidden": HIDDEN_ID,            # awarded by a hidden feat, not earned
    })
    d = _get(cli)
    ids = [m["id"] for m in d["relics"]["marks"]]
    assert ids == ["mk_won"]
    m = d["relics"]["marks"][0]
    assert m["unlock"] == "syn-img-1" and m["png"].startswith("/branding/marks/mk_won")
    text = json.dumps(d)
    assert "mk_locked" not in text and "mk_hidden" not in text and "mk_free" not in text
    assert HIDDEN_ID not in text


def test_a_mark_from_a_hidden_feat_joins_the_row_once_the_feat_is_earned(tmp_path):
    cli = _client(tmp_path, marks={"mk_hidden": HIDDEN_ID})
    assert _get(cli)["relics"]["marks"] == []
    sf.earn(tmp_path, HIDDEN_ID)
    d = _get(cli)
    assert [m["id"] for m in d["relics"]["marks"]] == ["mk_hidden"]


def test_no_marks_at_all_is_an_empty_row_not_an_error(tmp_path):
    cli = _client(tmp_path)
    assert _get(cli)["relics"] == {"marks": []}


# ---- the sealed roster's shape (donor-gated) --------------------------------------------------

def test_every_non_feat_metric_in_the_sealed_roster_is_measured(tmp_path, sealed_donor_present):
    """A new honor added to the pack without its metric being declared would silently lose its
    "N to go". Every non-feat entry must yield a count from a FRESH install's metric bundle,
    except the one self-referential metric (Completionist: its own pool, not a counter). The
    assertion is on metric NAMES of non-feat honors; it never prints a feat."""
    # The real recipe on an empty library: the catalog's metrics, then telemetry's -- the
    # merge every gate uses -- rather than a hand list that drifts when a metric moves.
    g.save_catalog(tmp_path / "catalog.db", [])
    fresh = g.achievement_metrics(tmp_path / "catalog.db", use_cache=False)
    fresh.update(g.telemetry_metrics(tmp_path))
    unmeasured = sorted({
        a["metric"] for a in g._roster()
        if a.get("tier") != "feat" and a.get("bucket") not in ("feat", "meta")
        and a["metric"] != "all_non_feat_earned"
        and g.achievement_progress(
            {"tier": a["tier"], "bucket": a.get("bucket", "ladder"), "metric": a["metric"],
             "threshold": a["threshold"], "current": 0, "earned": False}, fresh) is None})
    assert unmeasured == [], "non-feat metrics with no count: %r" % (unmeasured,)
