"""Full generation-surface capture (issue #18): the getTaskById fields the catalog used to
drop, plus the model-preset fallback for steps/sampler/cfg on models (e.g. Tsubaki.2/AuraFlow)
whose task omits detailParameters. Pure/mocked -- no network, no account."""
import json
import tempfile
import types

import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, save_catalog, load_catalog


_SURFACE = ["inference_profile", "quality_tag", "prompt_helper", "control_nets", "lora_parameters",
            "priority", "render_seconds", "backend", "started_at", "ended_at", "updated_at",
            "retry_count", "moderation", "video_mode", "video_model"]


def test_every_surface_field_is_a_catalog_column():
    for f in _SURFACE:
        assert f in CATALOG_FIELDS, f + " missing from CATALOG_FIELDS"
    # and the backfill copy-list must carry them too, or --backfill-full-meta silently skips them
    for f in _SURFACE:
        assert f in core._FULL_META_FIELDS, f + " missing from _FULL_META_FIELDS (backfill)"


def test_extract_full_meta_pulls_the_surface_fields():
    task = {
        "parameters": {"modelId": "V1", "inferenceProfile": "lite", "priority": 1500,
                       "qualityTag": {"prefix": "Masterpiece"}, "promptHelper": {"enable": False},
                       "controlNets": [], "loraParameters": [{"versionId": "L1", "weight": 0.7}],
                       "prompts": "p"},
        "outputs": {"seed": 123, "inferenceInfo": {"backend": "pdr",
                    "stages": {"pipeline_run_s": 457.2}}},
        "startedAt": "S", "endAt": "E", "updatedAt": "U", "retryCount": 0,
        "moderationAction": {"promptsModerationAction": "PASS"},
        "detectPromptHelperResult": {"enableReasonCode": "user-want-to-enable"},
    }
    fm = core.extract_full_meta(task)
    assert fm["inference_profile"] == "lite"
    assert fm["quality_tag"] == "Masterpiece"
    assert fm["prompt_helper"] == "off (user-want-to-enable)"
    assert fm["control_nets"] == ""                                  # empty list -> ''
    assert json.loads(fm["lora_parameters"]) == [{"versionId": "L1", "weight": 0.7}]
    assert fm["priority"] == "1500"
    assert fm["render_seconds"] == "457.2"
    assert fm["backend"] == "pdr"
    assert (fm["started_at"], fm["ended_at"], fm["updated_at"]) == ("S", "E", "U")
    assert fm["retry_count"] == "0"                                  # 0 is a real value, not blank
    assert fm["moderation"] == "PASS"
    assert fm["video_mode"] == "" and fm["video_model"] == ""        # not a video task


def test_prompt_helper_label():
    assert core._prompt_helper_label({"promptHelper": {"enable": True}}, {}) == "on"
    assert core._prompt_helper_label({"promptHelper": {"enable": False}}, {}) == "off"
    assert core._prompt_helper_label({}, {}) == ""                   # neither present -> ''
    assert core._prompt_helper_label(
        {"promptHelper": {"enable": False}},
        {"detectPromptHelperResult": {"enableReasonCode": "x"}}) == "off (x)"


def test_video_task_surface_fields():
    task = {"parameters": {"i2vPro": {"mode": "professional", "model": "v3.0.2", "duration": 10}}}
    fm = core.extract_full_meta(task)
    assert fm["video_mode"] == "professional" and fm["video_model"] == "v3.0.2"


def test_preset_fill_is_self_limiting(monkeypatch):
    """Tsubaki.2/AuraFlow: preset exposes samplingSteps only -> fill steps, leave sampler/cfg
    blank (that model genuinely has no sampler/cfg; an em-dash there is honest, not a hole)."""
    monkeypatch.setattr(core, "_resolve_model_preset",
                        lambda s, vid: {"steps": "16", "sampler": "", "cfg_scale": ""})
    fm = {"model_id": "V1", "steps": "", "sampler": "", "cfg_scale": ""}
    core._fill_preset_defaults(object(), fm, {"parameters": {"modelId": "V1"}})
    assert fm["steps"] == "16" and fm["sampler"] == "" and fm["cfg_scale"] == ""


def test_preset_fill_never_overwrites_a_recorded_value(monkeypatch):
    monkeypatch.setattr(core, "_resolve_model_preset",
                        lambda s, vid: {"steps": "16", "sampler": "Euler a", "cfg_scale": "5"})
    fm = {"model_id": "V1", "steps": "30", "sampler": "", "cfg_scale": ""}   # steps already set
    core._fill_preset_defaults(object(), fm, {"parameters": {"modelId": "V1"}})
    assert fm["steps"] == "30"                                       # kept, not overwritten
    assert fm["sampler"] == "Euler a" and fm["cfg_scale"] == "5"     # blanks filled


def test_preset_fill_skips_chat_and_video(monkeypatch):
    monkeypatch.setattr(core, "_resolve_model_preset",
                        lambda s, vid: {"steps": "16", "sampler": "x", "cfg_scale": "5"})
    for params in ({"chat": {"modelId": "V1"}}, {"i2vPro": {"mode": "pro"}}):
        fm = {"model_id": "V1", "steps": "", "sampler": "", "cfg_scale": ""}
        core._fill_preset_defaults(object(), fm, {"parameters": params})
        assert fm["steps"] == "" and fm["sampler"] == "" and fm["cfg_scale"] == ""


def test_video_row_builders_apply_the_surface_fields():
    """Regression guard (2026-08-15 adversarial review): the TWO video row-builders must persist
    the surface fields, or every video row ships them blank -- notably video_mode/video_model,
    the columns added FOR video, which --backfill can't repair for _download_video_task (its row
    carries model_id, so _needs() skips it forever). Source-level because these functions do real
    downloads that no unit test drives."""
    import pathlib
    src = pathlib.Path(core.__file__).read_text(encoding="utf-8")
    for fn in ("def _download_video_task", "def _do_task"):
        i = src.index(fn)
        body = src[i:i + 3200]
        assert "for k in _TASK_ROW_FIELDS" in body, \
            fn + " must apply _TASK_ROW_FIELDS to the video row (issue #18 + lineage)"


def test_task_row_fields_carry_lineage():
    """Create-time row-builders spread _TASK_ROW_FIELDS, not the bare surface list, so a freshly
    captured derived image/video lands with source_media_id/derive_kind already filled (audit
    2026-08-15) instead of waiting on a separate --backfill-lineage pass."""
    assert core._TASK_ROW_FIELDS[:len(core._GEN_SURFACE_FIELDS)] == core._GEN_SURFACE_FIELDS
    for f in ("source_media_id", "derive_kind"):
        assert f in core._TASK_ROW_FIELDS, f + " missing from _TASK_ROW_FIELDS"
        assert f in CATALOG_FIELDS, f + " missing from CATALOG_FIELDS"


def test_with_surface_gate_readmits_pre18_rows(monkeypatch, tmp_path):
    """--with-surface is the ONLY way a pre-#18 row -- one that already reached detail (it has
    prompt_full + a model_id, so every core _needs() gate passes) but carries none of the 15
    surface columns -- gets re-fetched to gain them. Without the flag such a row is skipped
    forever; with it, the blank-updated_at sentinel re-admits it, and once filled it is skipped
    again (idempotent). This is the highest-leverage audit fix (2026-08-15)."""
    db = tmp_path / "catalog.db"
    row = {f: "" for f in CATALOG_FIELDS}
    row.update({"media_id": "m0", "task_id": "t0", "filename": "f0.png",
                "prompt_full": "a cat", "model_id": "V1"})   # detailed, but no surface data
    save_catalog(db, [row])

    fetched = []

    def detail(session, tid):
        fetched.append(tid)
        return {"parameters": {"modelId": "V1", "inferenceProfile": "lite"},
                "outputs": {}, "updatedAt": "2026-08-01T00:00:00Z",
                "moderationAction": {"promptsModerationAction": "PASS"}}

    monkeypatch.setattr(core, "TASK_DETAIL_HASH", "hash")            # gate guard: must be truthy
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "task_detail_gql", detail)
    monkeypatch.setattr(core, "model_name_gql", lambda s, mid: "My Model")
    monkeypatch.setattr(core, "resolve_loras", lambda s, t: "")
    monkeypatch.setattr(core, "_fill_preset_defaults", lambda s, fm, t: fm)

    args = types.SimpleNamespace(out=str(tmp_path), token=None, workers=1, delay=0.0,
                                 progress=None, with_loras=False, with_credit=False,
                                 with_surface=False)

    # 1) WITHOUT the flag: the row passes every core gate, so nothing is fetched or changed.
    core.run_backfill_full_meta(args)
    assert fetched == []
    assert not {r["task_id"]: r for r in load_catalog(db)}["t0"].get("updated_at")

    # 2) WITH the flag: re-admitted, fetched once, and the surface columns land.
    args.with_surface = True
    core.run_backfill_full_meta(args)
    assert fetched == ["t0"]
    got = {r["task_id"]: r for r in load_catalog(db)}["t0"]
    assert got["updated_at"] == "2026-08-01T00:00:00Z"
    assert got["inference_profile"] == "lite"
    assert got["moderation"] == "PASS"

    # 3) Re-run WITH the flag: updated_at is now set, so the sentinel no longer matches -> skip.
    fetched.clear()
    core.run_backfill_full_meta(args)
    assert fetched == []


def test_new_columns_round_trip_through_the_catalog(tmp_path):
    db = str(tmp_path / "catalog.db")
    row = {f: "" for f in CATALOG_FIELDS}
    row.update({"media_id": "M1", "task_id": "T1", "inference_profile": "lite",
                "quality_tag": "Masterpiece", "steps": "16", "moderation": "PASS",
                "render_seconds": "457.2", "priority": "1500"})
    save_catalog(db, [row])
    got = load_catalog(db)[0]
    assert got["inference_profile"] == "lite" and got["quality_tag"] == "Masterpiece"
    assert got["steps"] == "16" and got["moderation"] == "PASS" and got["priority"] == "1500"
