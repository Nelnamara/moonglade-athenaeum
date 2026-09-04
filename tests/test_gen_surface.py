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


def _function_body(src, fn):
    """The whole body of `fn`, found by DEDENT rather than a fixed character window: a
    window silently starts testing less of the function every time a line is added above
    the thing under test, and did (a comment added 2026-09-03 pushed the call out of a
    3200-char slice and failed a guard here for no real reason)."""
    i = src.index(fn)
    indent = len(src[:i].rsplit("\n", 1)[-1])
    lines, body = src[i:].split("\n"), []
    for n, line in enumerate(lines):
        if n and line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        body.append(line)
    return "\n".join(body)


def test_every_capture_path_builds_its_row_through_the_shared_builder():
    """Regression guard (2026-08-15 adversarial review, kept through issue #19's refactor):
    the surface fields must reach EVERY capture path, or -- notably for the two video
    builders -- rows ship with video_mode/video_model blank, and --backfill can't repair
    _download_video_task's (its row carries model_id, so _needs() skips it forever).

    Since issue #19 the spread lives in build_catalog_row and happens once, so the guard is
    now two halves: the builder spreads _TASK_ROW_FIELDS, and every capture site routes
    through the builder AND hands it `fm`. Source-level because these functions do real
    downloads; tests/test_build_catalog_row.py drives each one end-to-end against a frozen
    copy of its pre-refactor output."""
    import pathlib
    src = pathlib.Path(core.__file__).read_text(encoding="utf-8")

    builder = _function_body(src, "def build_catalog_row")
    assert "for k in _TASK_ROW_FIELDS" in builder, \
        "build_catalog_row must spread _TASK_ROW_FIELDS (issue #18 + lineage)"

    # Every create-time capture path in this module, video paths included.
    for fn in ("def _download_video_task", "def _do_task", "def _download_image_task",
               "def run_generate", "def run_edit_image"):
        body = _function_body(src, fn)
        assert "build_catalog_row(" in body, \
            fn + " must build its catalog row through build_catalog_row (issue #19)"
        assert "fm=" in body, \
            fn + " must hand build_catalog_row its extract_full_meta result"
        assert '{f: "" for f in CATALOG_FIELDS}' not in body, \
            fn + " must not hand-assemble a row from the blank template any more"


def test_the_local_import_paths_also_use_the_shared_builder():
    """run_import_local has no task and no surface, but it writes the same catalog row --
    so it goes through the same builder. The builder is not the whole carry, though: it
    merges over the `known` map its CALLER passes, so a site that reaches it without
    `known=` still writes a blanking row. The gallery's Loom bundle import did exactly
    that -- its file-resolution guard does not prove the media_id is uncataloged, because
    a row outlives its file (dedup quarantine, manual deletion) -- so this guard asserts
    the argument is actually there, not merely that the builder is called."""
    import pathlib
    src = pathlib.Path(core.__file__).read_text(encoding="utf-8")
    body = _function_body(src, "def run_import_local")
    assert "build_catalog_row(" in body and '{f: "" for f in CATALOG_FIELDS}' not in body

    import moonglade_gallery
    gsrc = pathlib.Path(moonglade_gallery.__file__).read_text(encoding="utf-8")
    loom = gsrc[gsrc.index("def api_loom_import_bundle"):]
    loom = loom[:loom.index("media_added")]
    assert "build_catalog_row(" in loom and '{k: "" for k in CATALOG_FIELDS}' not in loom
    assert "known_catalog_rows(" in loom, \
        "the Loom bundle import must build its carry map (known_catalog_rows)"
    assert "known=known" in loom, \
        "the Loom bundle import must hand build_catalog_row that carry map (known=)"


def test_task_row_fields_carry_lineage():
    """Create-time row-builders spread _TASK_ROW_FIELDS, not the bare surface list, so a freshly
    captured derived image/video lands with source_media_id/derive_kind already filled (audit
    2026-08-15) instead of waiting on a separate --backfill-lineage pass."""
    assert core._TASK_ROW_FIELDS[:len(core._GEN_SURFACE_FIELDS)] == core._GEN_SURFACE_FIELDS
    for f in ("source_media_id", "derive_kind"):
        assert f in core._TASK_ROW_FIELDS, f + " missing from _TASK_ROW_FIELDS"
        assert f in CATALOG_FIELDS, f + " missing from CATALOG_FIELDS"


def test_with_surface_gate_readmits_pre18_rows(monkeypatch, tmp_path, pixai):
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


def test_backfill_checkpoints_incrementally_not_only_at_the_end(monkeypatch, tmp_path, pixai):
    """A big backfill (a 36k-image catalog is tens of thousands of getTaskById calls) must
    persist AS IT GOES, so a Ctrl-C or dropped connection partway keeps its progress instead of
    writing nothing. With the checkpoint interval forced to 1, each fetched task flushes its own
    save -- provable by counting save_catalog calls (a single end-save would be exactly one)."""
    db = tmp_path / "catalog.db"
    rows = []
    for i in range(3):
        r = {f: "" for f in CATALOG_FIELDS}
        r.update({"media_id": "m%d" % i, "task_id": "t%d" % i, "filename": "f%d.png" % i,
                  "prompt_full": "p", "model_id": "V1"})   # pre-#18: detailed but no surface
        rows.append(r)
    save_catalog(db, rows)

    def detail(session, tid):
        return {"parameters": {"modelId": "V1", "inferenceProfile": "lite", "prompts": "a cat"},
                "outputs": {}, "updatedAt": "2026-08-1" + tid[-1]}

    monkeypatch.setattr(core, "TASK_DETAIL_HASH", "hash")
    monkeypatch.setattr(core, "task_detail_gql", detail)
    monkeypatch.setattr(core, "model_name_gql", lambda s, mid: "M")
    monkeypatch.setattr(core, "resolve_loras", lambda s, t: "")
    monkeypatch.setattr(core, "_fill_preset_defaults", lambda s, fm, t: fm)
    monkeypatch.setattr(core, "_BACKFILL_CHECKPOINT_TASKS", 1)     # flush after every task

    saves = {"n": 0}
    real_save = core.save_catalog

    def counting_save(dbp, rws):
        saves["n"] += 1
        return real_save(dbp, rws)

    monkeypatch.setattr(core, "save_catalog", counting_save)

    args = types.SimpleNamespace(out=str(tmp_path), token=None, workers=1, delay=0.0,
                                 progress=None, with_loras=False, with_credit=False,
                                 with_surface=True)
    core.run_backfill_full_meta(args)

    assert saves["n"] >= 3, "each task should checkpoint its own save, not batch to one end-save"
    got = {r["task_id"]: r for r in load_catalog(db)}
    for t in ("t0", "t1", "t2"):
        assert got[t]["updated_at"] and got[t]["inference_profile"] == "lite", \
            t + " must be filled and persisted"


def test_run_generate_reads_sampling_fields_from_the_model_not_the_submit():
    """Owner ruling 2026-08-15: for the sampling fields (steps/sampler/cfg_scale), the MODEL's
    truth wins over what we submitted. A task that recorded none ran on the model's baked
    defaults, so the row must read them from fm (task-echoed -> preset -> blank), never fall
    back to the submitted samplingSteps/cfgScale (which an AuraFlow model like Tsubaki.2
    ignores -- its honest CFG is a blank, not the 7.0 we sent). _pick's submitted fallback used
    to preempt this for `steps` and leak the submitted value for `cfg`; source-level because the
    run_generate builder does real downloads no unit test drives."""
    import pathlib
    src = pathlib.Path(core.__file__).read_text(encoding="utf-8")
    region = src[src.index("def run_generate("):src.index("def _download_video_task(")]
    for f in ("steps", "cfg_scale", "sampler"):
        assert '{0}=fm.get("{0}"'.format(f) in region, \
            f + " must be read from the model surface (fm), not _pick's submitted fallback"
        assert '_pick("{}"'.format(f) not in region, \
            f + " must NOT fall back to the submitted value (owner ruling)"


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
