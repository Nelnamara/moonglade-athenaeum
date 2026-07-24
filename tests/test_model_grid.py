"""Model/LoRA grid backend: /v2 search (MODEL vs LORA) + version resolution. Mocked --
conftest blocks live /v2; no network, no spend."""
from types import SimpleNamespace

import pixai_gallery
import pixai_gallery_backup as core

_SEARCH = {"data": [
    {"id": "1982880136609467518", "title": "Tsubaki.2", "type": "MMDIT26A_MODEL",
     "likedCount": 10151, "flag": {"shouldBlur": False},
     "media": {"thumbnailUrl": "https://cdn/thumb/x", "publicUrl": "https://cdn/pub/x"},
     "hasLatestAvailableVersion": True},
    {"id": "999", "title": "Spicy LoRA", "type": "MULTI_LORA", "likedCount": 7,
     "flag": {"shouldBlur": True}, "media": {"thumbnailUrl": None, "publicUrl": "https://cdn/pub/y"},
     "hasLatestAvailableVersion": True},
], "hasMore": True}


def test_model_search_rest_shapes_rows(monkeypatch):
    seen = {}
    def fake_get(s, path, params=None, **k):
        seen["path"] = path
        seen["params"] = params
        return _SEARCH
    monkeypatch.setattr(core, "_rest_get", fake_get)
    out = core.model_search_rest(object(), keyword="tsu", usage="MODEL", size=10, offset=0)
    assert seen["path"] == "/generation-model/search"
    assert seen["params"]["usageType"] == "MODEL" and seen["params"]["keyword"] == "tsu"
    assert out["has_more"] is True and len(out["results"]) == 2
    a, b = out["results"]
    assert a["title"] == "Tsubaki.2" and a["model_id"] == "1982880136609467518"
    assert a["liked_count"] == 10151 and a["preview_url"] == "https://cdn/pub/x"   # full-res preferred (poor thumbnailUrl quality)
    assert b["should_blur"] is True and b["preview_url"] == "https://cdn/pub/y"   # falls back to publicUrl


def test_model_search_rest_preview_card_fields(monkeypatch):
    """Enrichment for the model-preview pop-out. Uses the REAL /v2 search field names
    (probed 2026-07-04): modelDescription, category (base family), curations (official
    badge), commentCount, refCount, authorId. See private/GENERATOR_SURFACE.md."""
    rich = {"data": [
        {"id": "1", "title": "Rich", "type": "SDXL_MODEL", "likedCount": 3,
         "flag": {}, "media": {"thumbnailUrl": "t", "publicUrl": "p"},
         "modelDescription": "d" * 700, "category": "uploaded-sdxl",
         "curations": ["inhouse"], "commentCount": 42, "refCount": 999, "authorId": "77"},
    ], "hasMore": False}
    monkeypatch.setattr(core, "_rest_get", lambda *a, **k: rich)
    m = core.model_search_rest(object())["results"][0]
    assert len(m["description"]) == 600                 # truncated at 600
    assert m["base_model"] == "uploaded-sdxl"           # base-model family chip
    assert m["official"] is True and m["curations"] == ["inhouse"]
    assert m["comment_count"] == 42 and m["ref_count"] == 999 and m["author_id"] == "77"
    assert m["cover_url"] == "p"                        # full-res preferred for the card

    monkeypatch.setattr(core, "_rest_get", lambda *a, **k: _SEARCH)
    m = core.model_search_rest(object())["results"][0]  # fields absent in response
    assert m["description"] == "" and m["base_model"] == "" and m["official"] is False
    assert m["comment_count"] == 0 and m["cover_url"] == "https://cdn/pub/x"


def test_model_search_rest_omits_empty_keyword(monkeypatch):
    seen = {}
    monkeypatch.setattr(core, "_rest_get",
                        lambda s, path, params=None, **k: seen.update(params=params) or {"data": []})
    core.model_search_rest(object(), keyword="", usage="lora", size=5)
    assert "keyword" not in seen["params"] and seen["params"]["usageType"] == "LORA"


def test_resolve_latest_version_picks_first(monkeypatch):
    monkeypatch.setattr(core, "_rest_get",
                        lambda s, path, **k: [{"id": "1983308862240288769", "modelId": "1982880136609467518"}])
    assert core.resolve_latest_version(object(), "1982880136609467518") == "1983308862240288769"


def test_resolve_latest_version_empty(monkeypatch):
    monkeypatch.setattr(core, "_rest_get", lambda *a, **k: [])
    assert core.resolve_latest_version(object(), "x") == ""


def test_resolve_version_meta_full_shape(monkeypatch):
    """The enriched resolver keeps the version metadata resolve_latest_version threw away:
    model_type + lora_base_model_type (for compat) and extra.triggerWords + tuned preset."""
    lora_row = [{"id": "V1", "modelType": "MULTI_LORA", "loraBaseModelType": "SDXL_MODEL",
                 "extra": {"triggerWords": "Eris_Adult, <lora:ErisV14:1>",
                           "previewArtworkIds": ["9"]}}]
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: lora_row)
    m = core.resolve_version_meta(object(), "L1")
    assert m["version_id"] == "V1" and m["model_type"] == "MULTI_LORA"
    assert m["lora_base_model_type"] == "SDXL_MODEL"          # the base family the LoRA needs
    assert m["trigger_words"] == "Eris_Adult, <lora:ErisV14:1>"

    base_row = [{"id": "V2", "modelType": "SDXL_MODEL", "loraBaseModelType": None,
                 "extra": {"negativePrompts": "nsfw, worst quality", "samplingMethod": "Euler a",
                           "samplingSteps": 28, "cfgScale": 5,
                           "capabilities": ["better-hands", 7]}}]  # non-str filtered
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: base_row)
    b = core.resolve_version_meta(object(), "B1")
    assert b["model_type"] == "SDXL_MODEL" and b["lora_base_model_type"] == ""  # null -> ""
    assert b["trigger_words"] == "" and b["negative_prompt"] == "nsfw, worst quality"
    assert b["sampling_method"] == "Euler a" and b["sampling_steps"] == 28 and b["cfg_scale"] == 5
    assert b["capabilities"] == ["better-hands"]

    monkeypatch.setattr(core, "_rest_get", lambda *a, **k: [])   # no versions -> empty shape
    e = core.resolve_version_meta(object(), "x")
    assert e["version_id"] == "" and e["model_type"] == "" and e["capabilities"] == []


def test_is_lora_compatible_exact_equality_fails_open():
    # exact enum equality
    assert core.is_lora_compatible("SDXL_MODEL", "SDXL_MODEL") is True
    assert core.is_lora_compatible("DIT7B_MODEL", "SDXL_MODEL") is False   # architecture mismatch
    assert core.is_lora_compatible("sdxl_model", "SDXL_MODEL") is True     # case-insensitive
    # fails OPEN on unknown/empty -> never block a submit on missing data
    assert core.is_lora_compatible("", "SDXL_MODEL") is True
    assert core.is_lora_compatible("SDXL_MODEL", "") is True
    assert core.is_lora_compatible(None, None) is True


def test_list_model_versions_full_shape_and_labels(monkeypatch):
    """Problem 4 (docs/AUDIT_2026-07-21.md's tracked O12/O13 remainder): exposes EVERY
    published version -- not just resolve_version_meta's rows[0] -- through the SAME
    per-row shape, plus a human `label` + `is_latest` for the picker UI."""
    rows = [
        {"id": "V3", "modelType": "SDXL_MODEL", "loraBaseModelType": None,
         "createdAt": "2026-07-20T00:00:00Z",
         "extra": {"negativePrompts": "nsfw", "samplingMethod": "Euler a",
                   "samplingSteps": 28, "cfgScale": 5}},
        {"id": "V2", "modelType": "SDXL_MODEL", "loraBaseModelType": None,
         "createdAt": "2026-06-01T00:00:00Z", "extra": {}},
        {"id": "V1", "modelType": "SDXL_MODEL", "loraBaseModelType": None,
         "createdAt": "", "extra": {}},
    ]
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: rows)
    out = core.list_model_versions(object(), "M1")
    assert [v["version_id"] for v in out] == ["V3", "V2", "V1"]     # server order preserved
    assert out[0]["label"] == "Latest · 2026-07-20" and out[0]["is_latest"] is True
    assert out[1]["label"] == "v2 · 2026-06-01" and out[1]["is_latest"] is False
    assert out[2]["label"] == "v1" and out[2]["is_latest"] is False   # no createdAt -> no date
    # full per-row meta, not just an id -- the whole point of exposing the list
    assert out[0]["sampling_method"] == "Euler a" and out[0]["cfg_scale"] == 5
    assert out[0]["negative_prompt"] == "nsfw"


def test_list_model_versions_skips_rows_with_no_id(monkeypatch):
    rows = [{"id": "", "modelType": "SDXL_MODEL"}, {"id": "V1", "modelType": "SDXL_MODEL"}]
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: rows)
    out = core.list_model_versions(object(), "M1")
    assert [v["version_id"] for v in out] == ["V1"]
    assert out[0]["is_latest"] is False    # it was rows[1] by ORIGINAL position, not rows[0]


def test_list_model_versions_empty_and_network_error(monkeypatch):
    monkeypatch.setattr(core, "_rest_get", lambda *a, **k: [])
    assert core.list_model_versions(object(), "x") == []

    def boom(*a, **k):
        raise core.PixAIError("nope")
    monkeypatch.setattr(core, "_rest_get", boom)
    assert core.list_model_versions(object(), "x") == []


def test_resolve_version_meta_and_list_model_versions_agree_on_rows0(monkeypatch):
    """The two must never drift on what rows[0] means -- resolve_version_meta's fast path
    and list_model_versions' first entry are the SAME row through the SAME mapping."""
    rows = [{"id": "V2", "modelType": "MULTI_LORA", "loraBaseModelType": "SDXL_MODEL",
             "extra": {"triggerWords": "trig"}},
            {"id": "V1", "modelType": "MULTI_LORA", "loraBaseModelType": "SDXL_MODEL", "extra": {}}]
    monkeypatch.setattr(core, "_rest_get", lambda s, path, **k: rows)
    single = core.resolve_version_meta(object(), "M1")
    listed = core.list_model_versions(object(), "M1")
    assert listed[0]["version_id"] == single["version_id"] == "V2"
    assert listed[0]["trigger_words"] == single["trigger_words"] == "trig"
    assert listed[0]["model_type"] == single["model_type"]


# ---- annotate_lora_compat (problem 3: architecture-aware LoRA sort/badge) -----------------
# Mock rows use the CONFIRMED-live shape: `lora_base_model_type`, sourced from GraphQL's
# latestVersion.loraBaseModelType (model_search_market_gql) -- e.g. real rows come back as
# modelType:"MULTI_LORA", loraBaseModelType:"SD_V1_MODEL" -- NEVER `base_model` (PixAI's
# content category, confirmed NOT architecture; see the function's own docstring).

def test_annotate_lora_compat_sorts_compatible_first_and_tags_every_row():
    rows = [
        {"model_id": "1", "title": "Mismatch LoRA", "lora_base_model_type": "SD_V1_MODEL"},
        {"model_id": "2", "title": "Match LoRA", "lora_base_model_type": "MMDIT26A_MODEL"},
        {"model_id": "3", "title": "Unknown-arch LoRA", "lora_base_model_type": ""},
        {"model_id": "4", "title": "Another match", "lora_base_model_type": "MMDIT26A_MODEL"},
    ]
    out = core.annotate_lora_compat(rows, "MMDIT26A_MODEL")
    # SOFT sort: compatible + unknown float to the front (fail-open, same rule as
    # is_lora_compatible), a CONFIRMED mismatch sinks to the back -- nothing is ever hidden,
    # and each group keeps its original relative order (stable partition).
    assert [r["model_id"] for r in out] == ["2", "3", "4", "1"]
    assert {r["model_id"]: r["compat"] for r in out} == {"1": "no", "2": "yes", "3": "unknown", "4": "yes"}


def test_annotate_lora_compat_case_insensitive_like_is_lora_compatible():
    rows = [{"model_id": "1", "lora_base_model_type": "sdxl_model"}]
    assert core.annotate_lora_compat(rows, "SDXL_MODEL")[0]["compat"] == "yes"


def test_annotate_lora_compat_passthrough_when_no_base_selected():
    """Browsing LoRAs before picking a base must be completely untouched -- no sort, no tag."""
    rows = [{"model_id": "1", "lora_base_model_type": "SDXL_MODEL"}]
    out = core.annotate_lora_compat(rows, "")
    assert out is rows and "compat" not in out[0]
    assert core.annotate_lora_compat(rows, None) is rows


def test_annotate_lora_compat_does_not_mutate_input_rows():
    rows = [{"model_id": "1", "lora_base_model_type": "SDXL_MODEL"}]
    core.annotate_lora_compat(rows, "SDXL_MODEL")
    assert "compat" not in rows[0]   # a fresh copy is returned -- the caller's own list/dicts are untouched


def test_annotate_lora_compat_all_incompatible_still_returns_everything():
    """A hard filter would empty the grid here -- the soft-sort contract must not drop rows,
    only reorder + tag them, even when NOTHING matches."""
    rows = [{"model_id": "1", "lora_base_model_type": "SD_V1_MODEL"},
            {"model_id": "2", "lora_base_model_type": "SD3_MODEL"}]
    out = core.annotate_lora_compat(rows, "MMDIT26A_MODEL")
    assert len(out) == 2 and all(r["compat"] == "no" for r in out)


def test_web_generate_pipeline(monkeypatch, tmp_path):
    # web_generate = submit -> poll -> task detail -> download/catalog; all reused parts
    # mocked so no network / no spend. Verifies it threads the pieces + returns media_ids.
    monkeypatch.setattr(core, "gql_adhoc", lambda s, q, v=None: {"createGenerationTask": {"id": "T1"}})
    monkeypatch.setattr(core, "_poll_task_status", lambda *a, **k: 0)
    monkeypatch.setattr(core, "task_detail_gql",
                        lambda s, t: {"outputs": {"mediaId": "M1", "batchMediaIds": ["M2"]}})
    monkeypatch.setattr(core, "_download_image_task", lambda *a, **k: ["/p/M1.webp", "/p/M2.webp"])
    res = core.web_generate(object(), {"prompts": "x", "modelId": "v"}, str(tmp_path))
    assert res["task_id"] == "T1" and res["media_ids"] == ["M1", "M2"]
    assert res["saved"] == 2 and res["paid_credit"] == 0


def test_web_generate_raises_without_task_id(monkeypatch, tmp_path):
    import pytest
    monkeypatch.setattr(core, "gql_adhoc", lambda s, q, v=None: {"createGenerationTask": {}})
    with pytest.raises(core.PixAIError):
        core.web_generate(object(), {"prompts": "x", "modelId": "v"}, str(tmp_path))


def test_model_search_market_gql(monkeypatch):
    """Market browse via GraphQL: honors category + Newest sort (which REST silently ignores),
    returns the SAME row shape as model_search_rest (REST-only fields empty) + tags/created_at,
    and splits base vs LoRA by node type."""
    captured = {}
    def fake_gql(session, query, vars=None):
        captured["query"] = query
        captured["vars"] = vars
        return {"generationModels": {"pageInfo": {"hasNextPage": True}, "edges": [
            {"node": {"id": "1", "title": "Style A", "type": "SDXL_MODEL", "isNsfw": False,
                      "likedCount": 9, "latestVersion": {"id": "v1"},
                      "media": {"urls": [{"url": "https://cdn/orig"}, {"url": "https://cdn/thumb/x"}]},
                      "tags": [{"name": "anime"}, {"name": "night"}], "author": {"displayName": "Nel"},
                      "createdAt": "2026-07-04T00:00:00Z"}},
            {"node": {"id": "2", "title": "A LoRA", "type": "MULTI_LORA", "isNsfw": True,
                      "likedCount": 3, "latestVersion": {"id": "v2"}, "media": {"urls": []},
                      "tags": [], "author": {}, "createdAt": ""}},
        ]}}
    monkeypatch.setattr(core, "gql_adhoc", fake_gql)

    # base + category + newest -> category/orderBy interpolated, keyword bound as a variable
    r = core.model_search_market_gql(object(), keyword="anime", category="style",
                                     sort="newest", usage="MODEL", limit=24)
    assert 'category:"style"' in captured["query"] and 'orderBy:"-createdAt"' in captured["query"]
    assert captured["vars"]["k"] == "anime"           # keyword stays a bound var (no injection)
    assert [m["model_id"] for m in r["results"]] == ["1"]   # LoRA dropped for MODEL usage
    m0 = r["results"][0]
    assert m0["preview_url"] == "https://cdn/thumb/x" and m0["has_version"] is True
    assert m0["tags"] == ["anime", "night"] and m0["author"] == "Nel"
    assert m0["description"] == "" and m0["ref_count"] == 0 and m0["official"] is False  # REST-only empty
    assert r["has_more"] is True

    # LoRA usage keeps only LoRA rows; a bad category is ignored (no category arg emitted)
    r2 = core.model_search_market_gql(object(), category="concept", usage="LORA")
    assert 'category:' not in captured["query"]          # 'concept' not whitelisted
    assert [m["model_id"] for m in r2["results"]] == ["2"] and r2["results"][0]["should_blur"] is True


def test_model_search_market_gql_requests_and_surfaces_architecture_fields(monkeypatch):
    """picker-parity-round2 (problem 3): the query gained latestVersion{modelType
    loraBaseModelType} -- confirmed live against the owner's real account (real rows come
    back e.g. modelType:"MULTI_LORA", loraBaseModelType:"SD_V1_MODEL") -- surfaced as
    model_type/lora_base_model_type on every row, the SAME key names resolve_version_meta
    already uses, so annotate_lora_compat doesn't care which search path produced a row."""
    captured = {}

    def fake_gql(session, query, vars=None):
        captured["query"] = query
        return {"generationModels": {"pageInfo": {"hasNextPage": False}, "edges": [
            {"node": {"id": "9", "title": "Eris LoRA", "type": "MULTI_LORA", "isNsfw": False,
                      "likedCount": 1, "latestVersion": {"id": "v9", "modelType": "MULTI_LORA",
                                                          "loraBaseModelType": "SD_V1_MODEL"},
                      "media": {"urls": []}, "tags": [], "author": {}, "createdAt": ""}},
            {"node": {"id": "10", "title": "No version yet", "type": "MULTI_LORA", "isNsfw": False,
                      "likedCount": 0, "latestVersion": {}, "media": {"urls": []},
                      "tags": [], "author": {}, "createdAt": ""}},
        ]}}
    monkeypatch.setattr(core, "gql_adhoc", fake_gql)
    r = core.model_search_market_gql(object(), usage="LORA")
    assert "modelType loraBaseModelType" in captured["query"]
    assert r["results"][0]["model_type"] == "MULTI_LORA"
    assert r["results"][0]["lora_base_model_type"] == "SD_V1_MODEL"
    assert r["results"][1]["model_type"] == "" and r["results"][1]["lora_base_model_type"] == ""


def test_task_image_media_prefers_batch_over_grid():
    """A batchSize>1 task stores a composite GRID under outputs.mediaId and the individual
    images under outputs.batch[] -- we must save the individuals (with per-image seeds), never
    the grid. This is the batch-under-capture fix."""
    outputs = {"mediaId": "GRID", "seed": "111", "batch": [
        {"mediaId": "A", "seed": "111"}, {"mediaId": "B", "seed": "222"},
        {"mediaId": "C"},                                   # missing seed -> shared
        {"mediaId": ""},                                     # empty -> skipped
    ]}
    media = core._task_image_media(outputs)
    assert [m for m, _ in media] == ["A", "B", "C"]          # the reals, NOT "GRID"
    assert dict(media) == {"A": "111", "B": "222", "C": "111"}  # per-image seed, shared fallback


def test_task_image_media_single_and_legacy():
    # single image: no batch -> use mediaId
    assert core._task_image_media({"mediaId": "X", "seed": "9"}) == [("X", "9")]
    # legacy shape (batchMediaIds, no batch) still works, deduped
    m = core._task_image_media({"mediaId": "X", "seed": "9", "batchMediaIds": ["X", "Y"]})
    assert [mid for mid, _ in m] == ["X", "Y"]
    assert core._task_image_media({}) == []


def _stub_generate_network(monkeypatch, outputs):
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: "")
    monkeypatch.setattr(core, "gql_adhoc", lambda s, q, v=None: {"createGenerationTask": {"id": "T1"}})
    monkeypatch.setattr(core, "_poll_task_status", lambda *a, **k: None)
    monkeypatch.setattr(core, "task_detail_gql",
                        lambda s, t: {"createdAt": "2026-07-22T00:00:00Z", "outputs": outputs})
    seen_mids = []
    def fake_resolve(s, mid):
        seen_mids.append(mid)
        return "https://cdn/" + mid, {"width": 512, "height": 512}
    monkeypatch.setattr(core, "resolve_media", fake_resolve)
    monkeypatch.setattr(core, "download", lambda s, url, stem, **k: ("ok", stem.with_suffix(".png")))
    monkeypatch.setattr(pixai_gallery, "make_thumbnail", lambda *a, **k: None)
    return seen_mids


_BATCH_OUTPUTS = {"mediaId": "GRID", "seed": "1",
                  "batch": [{"mediaId": "A", "seed": "11"}, {"mediaId": "B", "seed": "22"}]}


def test_run_generate_saves_batch_individuals_not_the_grid(monkeypatch, tmp_path):
    """A batchSize>1 --generate run used to build its saved-media list straight off
    outputs.mediaId/batchMediaIds -- the composite GRID id, plus a batchMediaIds field
    that's null on modern tasks -- so only the grid got downloaded and catalogued and
    the individual images were silently lost (audit: unfiled-workflow-findings,
    2026-07-21). Fixed: run_generate now goes through _task_image_media, the same
    helper _download_image_task already used, which prefers outputs.batch[] over the
    grid and carries each image's own seed."""
    seen_mids = _stub_generate_network(monkeypatch, _BATCH_OUTPUTS)
    args = SimpleNamespace(out=str(tmp_path), params_json='{"prompts": "x", "modelId": "v"}',
                           confirm=True, task_id="", token=None)
    res = core.run_generate(args)
    assert seen_mids == ["A", "B"]        # the real individuals downloaded, never "GRID"
    assert res["images"] == 2


def test_run_generate_still_self_heals_after_delegating_to_submit_generation(monkeypatch, tmp_path):
    """run_generate's own inferenceProfile try/except was consolidated into
    submit_generation() 2026-07-24 (run_generate now just calls through it) -- this
    proves that consolidation didn't lose the CLI's original retry-and-succeed
    behavior: a --generate run with an unsupported Mode still completes instead of
    raising, end to end through the real run_generate() entry point."""
    seen_mids = _stub_generate_network(monkeypatch, _BATCH_OUTPUTS)
    calls = []

    def fake_gql(s, q, v=None):
        params = v["parameters"]
        calls.append(dict(params))
        if "inferenceProfile" in params:
            raise core.PixAIError(
                'GraphQL error: [{"message": "unknown inferenceProfile \\"ultra\\" '
                'for model type \\"SDXL_MODEL\\""}]')
        return {"createGenerationTask": {"id": "T1"}}

    monkeypatch.setattr(core, "gql_adhoc", fake_gql)
    args = SimpleNamespace(
        out=str(tmp_path),
        params_json='{"prompts": "x", "modelId": "v", "inferenceProfile": "ultra"}',
        confirm=True, task_id="", token=None)
    res = core.run_generate(args)
    assert len(calls) == 2                       # rejected once, retried once
    assert "inferenceProfile" not in calls[1]     # retry dropped it
    assert seen_mids == ["A", "B"]
    assert res["images"] == 2


def test_run_edit_image_saves_batch_individuals_not_the_grid(monkeypatch, tmp_path):
    """Same fix, same bug, for --edit-image: a batchSize>1 edit used to save only the
    composite grid too."""
    seen_mids = _stub_generate_network(monkeypatch, _BATCH_OUTPUTS)
    args = SimpleNamespace(out=str(tmp_path), params_json='{"chat": {"modelId": "v"}}',
                           confirm=True, task_id="", edit_src=[], prompt="x", token=None)
    res = core.run_edit_image(args)
    assert seen_mids == ["A", "B"]
    assert res["images"] == 2


def test_task_detail_query_adhoc_fallback(monkeypatch):
    """When TASK_DETAIL_HASH is missing, _task_detail_query uses the ad-hoc task(id:) query
    (no persisted hash) -- unblocking --full-meta. When present, it uses task_detail_gql."""
    monkeypatch.setattr(core, "TASK_DETAIL_HASH", "")
    monkeypatch.setattr(core, "gql_adhoc",
                        lambda s, q, v=None: {"task": {"id": v["id"], "status": "completed"}})
    t = core._task_detail_query(object(), "T7")
    assert t["id"] == "T7" and t["status"] == "completed"
    # with a hash present it delegates to the persisted getTaskById
    monkeypatch.setattr(core, "TASK_DETAIL_HASH", "deadbeef")
    monkeypatch.setattr(core, "task_detail_gql", lambda s, tid: {"id": tid, "via": "persisted"})
    assert core._task_detail_query(object(), "T8") == {"id": "T8", "via": "persisted"}


def test_workflow_catalog(monkeypatch):
    monkeypatch.setattr(core, "gql_adhoc", lambda s, q, v=None: {"workflows": {"edges": [
        {"node": {"id": "1794855217667308480", "name": "Image Upscale",
                  "type": "UPSCALE", "coverMediaId": "9"}},
        {"node": {"id": "", "name": "no-id skipped"}},
    ]}})
    out = core.workflow_catalog(object())
    assert len(out) == 1 and out[0]["id"] == "1794855217667308480"
    assert out[0]["name"] == "Image Upscale" and out[0]["cover_media_id"] == "9"


def test_submit_generation(monkeypatch):
    monkeypatch.setattr(core, "gql_adhoc", lambda s, q, v=None: {"createGenerationTask": {"id": "T9"}})
    assert core.submit_generation(object(), {"x": 1}) == "T9"


def test_submit_generation_raises(monkeypatch):
    import pytest
    monkeypatch.setattr(core, "gql_adhoc", lambda s, q, v=None: {"createGenerationTask": {}})
    with pytest.raises(core.PixAIError):
        core.submit_generation(object(), {})


def test_submit_generation_retries_on_inferenceprofile_rejection(monkeypatch):
    """inferenceProfile (the Mode quality setting) is model-type-specific -- PixAI
    rejects an unsupported value outright, with a raw GraphQL error. Found live
    2026-07-24: the CLI's run_generate had always self-healed this with its own one-off
    try/except, but submit_generation() -- the choke point the web /api/generate route
    (and every other current/future caller) actually goes through -- had no such
    protection, so a web user hitting an unsupported Mode just got the raw rejection.
    This is the fail-first proof the retry now lives in submit_generation() itself, so
    every caller gets it for free. Matches run_generate's pre-existing retry-once
    behavior: drop inferenceProfile, resubmit on the model's default."""
    calls = []

    def fake_gql(s, q, v=None):
        calls.append(dict(v["parameters"]))
        if "inferenceProfile" in v["parameters"]:
            raise core.PixAIError(
                'GraphQL error: [{"message": "unknown inferenceProfile \\"ultra\\" '
                'for model type \\"SDXL_MODEL\\""}]')
        return {"createGenerationTask": {"id": "T10"}}

    monkeypatch.setattr(core, "gql_adhoc", fake_gql)
    params = {"prompts": "x", "modelId": "v", "inferenceProfile": "ultra"}
    assert core.submit_generation(object(), params) == "T10"
    assert len(calls) == 2                              # rejected once, retried once
    assert calls[0]["inferenceProfile"] == "ultra"       # first attempt: as chosen
    assert "inferenceProfile" not in calls[1]            # retry: dropped, not just changed
    assert "inferenceProfile" not in params              # popped in place (mutates the caller's dict)


def test_submit_generation_does_not_retry_unrelated_errors(monkeypatch):
    """The retry is scoped to the inferenceProfile rejection specifically -- a genuinely
    different rejection (bad prompt, moderation, whatever) must propagate on the first
    try, not silently eat inferenceProfile and retry for an unrelated reason."""
    import pytest

    def fake_gql(s, q, v=None):
        raise core.PixAIError("GraphQL error: something else entirely")

    monkeypatch.setattr(core, "gql_adhoc", fake_gql)
    with pytest.raises(core.PixAIError, match="something else entirely"):
        core.submit_generation(object(), {"prompts": "x", "inferenceProfile": "ultra"})


def test_submit_generation_no_retry_when_param_absent(monkeypatch):
    """A rejection that happens to mention 'inferenceProfile' in its text but where the
    submitted params never set the key at all must not loop forever -- the second half of
    the retry's guard ("inferenceProfile" in params) is what stops that."""
    import pytest
    calls = []

    def fake_gql(s, q, v=None):
        calls.append(1)
        raise core.PixAIError("GraphQL error: inferenceProfile is unsupported here")

    monkeypatch.setattr(core, "gql_adhoc", fake_gql)
    with pytest.raises(core.PixAIError):
        core.submit_generation(object(), {"prompts": "x"})   # no inferenceProfile key
    assert len(calls) == 1                               # never retried


def test_generation_status_phases(monkeypatch):
    for raw, phase in [("completed", "done"), ("succeeded", "done"), ("failed", "failed"),
                       ("cancelled", "failed"), ("running", "running"), ("pending", "running")]:
        monkeypatch.setattr(core, "gql_adhoc",
                            lambda s, q, v=None, _r=raw: {"task": {"status": _r, "paidCredit": 7}})
        st = core.generation_status(object(), "T")
        assert st["phase"] == phase and st["paid_credit"] == 7


def test_collect_generation(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "task_detail_gql", lambda s, t: {"outputs": {"mediaId": "M1"}})
    monkeypatch.setattr(core, "extract_full_meta", lambda r: {"prompt_full": "p"})
    monkeypatch.setattr(core, "_download_image_task", lambda *a, **k: ["/M1.webp"])
    got = core.collect_generation(object(), "T", str(tmp_path))
    assert got["media_ids"] == ["M1"] and got["saved"] == 1


def test_submit_fixer_filters_and_submits(monkeypatch):
    seen = {}
    def fake_post(s, path, body, **k):
        seen["path"] = path
        seen["body"] = body
        return {"id": "F1"}
    monkeypatch.setattr(core, "_rest_post", fake_post)
    tid = core.submit_fixer(object(), "M", [
        {"x": 10, "y": 20, "width": 30, "height": 40, "tag": "FACE"},  # kept (tag lowercased)
        {"x": 1, "y": 1, "width": 0, "height": 5, "tag": "hand"},      # dropped (w == 0)
        {"x": 1, "y": 1, "width": 5, "height": 5, "tag": "nope"},      # dropped (bad tag)
    ])
    assert tid == "F1" and seen["path"] == "/task/fixer" and seen["body"]["mediaId"] == "M"
    assert seen["body"]["boxes"] == [{"x": 10, "y": 20, "width": 30, "height": 40, "tag": "face"}]


def test_submit_fixer_needs_a_box(monkeypatch):
    import pytest
    monkeypatch.setattr(core, "_rest_post", lambda *a, **k: {"id": "x"})
    with pytest.raises(core.PixAIError):
        core.submit_fixer(object(), "M", [])


def test_run_generate_persists_paid_credit(monkeypatch, tmp_path):
    """The catalog write is where paidCredit stops being throwaway poll output: a
    --generate run must store the task's server-reported actual cost (getTaskById's
    top-level paidCredit) on every row it catalogs -- it's a TASK-level value,
    repeated on each of the task's media rows."""
    _stub_generate_network(monkeypatch, _BATCH_OUTPUTS)
    monkeypatch.setattr(core, "task_detail_gql",
                        lambda s, t: {"createdAt": "2026-07-23T00:00:00Z",
                                      "outputs": _BATCH_OUTPUTS, "paidCredit": 2750})
    args = SimpleNamespace(out=str(tmp_path), params_json='{"prompts": "x", "modelId": "v"}',
                           confirm=True, task_id="", token=None)
    core.run_generate(args)
    rows = pixai_gallery.load_catalog(tmp_path / "catalog.db")
    assert {r["media_id"]: r.get("paid_credit") for r in rows} == {"A": "2750", "B": "2750"}


def test_collect_generation_persists_paid_credit_zero_not_blank(monkeypatch, tmp_path):
    """collect_generation is the shared collect for the web async poll (/api/task-status)
    and the --watch-backup live mirror. paidCredit 0 is a REAL value (a free card /
    daily-free gen) and must be stored as '0' -- never collapsed into '' (unknown)."""
    monkeypatch.setattr(core, "task_detail_gql",
                        lambda s, t: {"createdAt": "2026-07-23T00:00:00Z",
                                      "outputs": {"mediaId": "M1", "seed": "9"},
                                      "paidCredit": 0})
    monkeypatch.setattr(core, "resolve_media",
                        lambda s, m: ("https://cdn/" + m, {"width": 8, "height": 8}))
    monkeypatch.setattr(core, "download",
                        lambda s, url, stem, **k: ("ok", stem.with_suffix(".png")))
    monkeypatch.setattr(pixai_gallery, "make_thumbnail", lambda *a, **k: None)
    got = core.collect_generation(object(), "T1", str(tmp_path))
    assert got["media_ids"] == ["M1"]
    rows = pixai_gallery.load_catalog(tmp_path / "catalog.db")
    assert rows[0].get("paid_credit") == "0"
