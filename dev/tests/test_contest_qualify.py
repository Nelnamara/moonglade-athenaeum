"""Contest cards say whether you have used what a contest requires (2026-11-18):
moonglade/contest_qualify.py and /api/contests/qualify. A rule's model/LoRA counts as used
when a picture here was made with it -- the rule id itself, or any of the model's versions --
and anything that could not be checked (a recipe, a failed version read) is unknown, never
"not used". Nothing here touches the network: the version read is a stub."""
import json

from moonglade import backup as core
from moonglade import contest_qualify as cq
from moonglade.gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_test_client


def _catalog(tmp_path):
    rows = [
        {"media_id": "1", "task_id": "t1", "model_id": "VER-A", "filename": "a_1.png"},
        {"media_id": "2", "task_id": "t2", "model_id": "VER-B", "filename": "a_2.png",
         "lora_parameters": json.dumps([{"versionId": "LORA-V1", "weight": 0.7}])},
        {"media_id": "3", "task_id": "t3", "model_id": "", "filename": "a_3.png",
         "lora_parameters": "not json"},
    ]
    save_catalog(tmp_path / "catalog.db",
                 [{f: "" for f in CATALOG_FIELDS} | {"status": "completed",
                                                     "created_at": "2025-01-01T00:00:00"} | r
                  for r in rows])
    return tmp_path / "catalog.db"


def test_used_version_ids_reads_models_and_loras(tmp_path):
    assert cq.used_version_ids(_catalog(tmp_path)) == {"VER-A", "VER-B", "LORA-V1"}


def test_rule_status_counts_used_versions_and_never_guesses():
    used = {"VER-A", "LORA-V1"}
    versions = {"MODEL-A": {"VER-A", "VER-A2"}, "LORA-M": {"LORA-V1"}, "OTHER": {"X"}}
    of = lambda mid: versions.get(mid)              # None = could not be read
    assert cq.rule_status({"type": "required_model_ids", "model_ids": ["MODEL-A"]}, used, of) == \
        {"kind": "model", "need": 1, "used": 1, "unknown": 0}
    assert cq.rule_status({"type": "required_lora_ids", "lora_ids": ["LORA-M", "OTHER"]}, used, of) == \
        {"kind": "LoRA", "need": 2, "used": 1, "unknown": 0}
    # a rule id that is itself a version id here counts without a read
    assert cq.rule_status({"type": "required_model_ids", "model_ids": ["VER-A"]}, used,
                          lambda m: (_ for _ in ()).throw(AssertionError("read"))) == \
        {"kind": "model", "need": 1, "used": 1, "unknown": 0}
    # unreadable -> unknown, a recipe -> unknown
    assert cq.rule_status({"type": "required_lora_ids", "lora_ids": ["GONE"]}, used, of)["unknown"] == 1
    assert cq.rule_status({"type": "required_recipe_ids", "recipe_ids": ["r1"]}, used, of) == \
        {"kind": "recipe", "need": 1, "used": 0, "unknown": 1}


def test_board_qualify_caps_and_paces_the_version_reads(tmp_path, monkeypatch):
    db = _catalog(tmp_path)
    cq._cache.clear()
    asked, slept = [], []
    monkeypatch.setattr(cq, "model_version_ids",
                        lambda core_, s, mid: asked.append(mid) or ({"VER-A"} if mid == "M0" else set()))
    monkeypatch.setattr(cq, "MAX_LOOKUPS", 3)
    contests = [{"id": "c%d" % i, "rules": [{"type": "required_lora_ids", "lora_ids": ["M%d" % i]}]}
                for i in range(5)] + [{"id": "free", "rules": []}]
    out = cq.board_qualify(None, None, contests, db, sleep=slept.append, now=1000.0)
    assert asked == ["M0", "M1", "M2"] and len(slept) == 2
    assert out["c0"][0]["used"] == 1 and out["c1"][0] == {"kind": "LoRA", "need": 1, "used": 0,
                                                          "unknown": 0}
    assert out["c4"][0]["unknown"] == 1, "past the cap is unknown, never 'not used'"
    assert "free" not in out
    # kept a day: a second answer reads nothing
    asked.clear()
    cq.board_qualify(None, None, contests[:3], db, sleep=slept.append, now=2000.0)
    assert asked == []


def test_a_failed_version_read_is_unknown(tmp_path, monkeypatch):
    db = _catalog(tmp_path)
    cq._cache.clear()

    def boom(*a):
        raise core.PixAIError("offline")
    monkeypatch.setattr(cq, "model_version_ids", boom)
    out = cq.board_qualify(None, None, [{"id": "c", "rules": [
        {"type": "required_model_ids", "model_ids": ["M"]}]}], db, sleep=lambda s: None)
    assert out["c"][0]["unknown"] == 1 and out["c"][0]["used"] == 0
    assert cq.cached_versions("M") is None, "a failure is not remembered"


def test_the_route_answers_per_running_contest(tmp_path, monkeypatch, pixai):
    _catalog(tmp_path)
    cq._cache.clear()
    from moonglade import contest_sync
    monkeypatch.setattr(contest_sync, "contest_board", lambda core_, s, force=False: [
        {"id": "run", "active": True, "rules": [{"type": "required_model_ids", "model_ids": ["VER-B"]}]},
        {"id": "over", "active": False, "rules": [{"type": "required_model_ids", "model_ids": ["X"]}]}])
    cli = login_test_client(create_app(tmp_path))
    d = cli.get("/api/contests/qualify").get_json()
    assert d["contests"] == {"run": [{"kind": "model", "need": 1, "used": 1, "unknown": 0}]}
