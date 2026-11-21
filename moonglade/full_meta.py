"""
moonglade/full_meta.py
======================
A task's full metadata and the catalog rows built from it: the full-meta field lists,
`media_file_gql` and `video_outputs`, `extract_full_meta` (with the generation surface, the
batch position and the model preset and LoRA readers), the row builders (`known_catalog_rows`,
`carry_local_fields`, `build_catalog_row`), the `--list-models` and `--convert-existing`
runners. Moved verbatim out of moonglade/backup.py in the 3.22 split (phase 4). `gql_adhoc`,
`gql_mutate` and `resolve_user_id` stay in the engine.

The names it reads from the engine (PixAIError, _make_session, gql_adhoc, _parallel_map and
source_media_of_task) are imported from moonglade.backup inside each function that uses them,
at call time, so a test's patch of backup's binding still reaches them and importing this
module never imports the engine.
"""
import json
import sqlite3
import sys
import time

from moonglade import cloud_delete as _cloud_delete
from moonglade import gen_params as _gen_params
from moonglade import media_fetch as _media_fetch
from moonglade import models as _models
from moonglade import task_reads as _task_reads
from moonglade.catalog import CATALOG_FIELDS
from moonglade.catalog_verbs import rows_for_media_ids


# ---------------------------------------------------------------------------
# Full-meta API (task detail + model name)
# ---------------------------------------------------------------------------
_FULL_META_FIELDS = (
    "prompt_full", "natural_prompt", "seed", "steps",
    "sampler", "cfg_scale", "model_id", "model_name", "loras",
    "negative_prompt", "clip_skip", "paid_credit",
    "source_media_id", "derive_kind",
    # Full generation surface (issue #18) -- so --backfill-full-meta fills these on existing
    # rows too. MUST stay in sync with _GEN_SURFACE_FIELDS (both are static; a mismatch just
    # means a field the row-builders write but the backfill wouldn't, or vice-versa).
    "inference_profile", "quality_tag", "prompt_helper", "control_nets", "lora_parameters",
    "priority", "render_seconds", "backend", "started_at", "ended_at", "updated_at",
    "retry_count", "moderation", "video_mode", "video_model",
    "output_format", "frame_count", "frame_duration_ms",
    # Batch identity (issue #33): PixAI's own 0-based output number + batch size from
    # getTaskById outputs.batch. Per-ROW, unlike everything else here -- extract_full_meta
    # leaves both blank at task level (fm is cached once per task) and each row resolves
    # its own via _with_batch_position before _merge_full / the backfill apply carry them.
    "batch_index", "batch_size",
    # Per-ROW too (2026-09-06): the deletedAt stamp on this image's own outputs.batch entry,
    # so a backfill marks the row of an image deleted from PixAI's website rather than
    # leaving it looking live. Blank for every live output and every non-batch task.
    "cloud_deleted_at",
)


def _paid_credit_str(task):
    """Catalog-string form of a task dict's server-reported `paidCredit` (the ACTUAL
    credit cost, known once the task ran). '' when the field is absent/null (unknown)
    -- never coerce that to '0', because '0' is a real, meaningful value (a free card
    or daily-free gen). Task-level: callers stamp it on each of the task's media rows."""
    v = (task or {}).get("paidCredit")
    return "" if v is None else str(v)


def media_file_gql(session, media_id):
    """Resolve a VIDEO media's actual file URL. The REST /v1/media endpoint
    returns an empty urls[] for videos; the GraphQL `media` object carries the
    real mp4 in `fileUrl`. Returns {'fileUrl','type','duration'} or {}."""
    from moonglade.backup import gql_adhoc, PixAIError
    query = ("query($id:String!){ media(id:$id){ id type duration fileUrl "
             "hlsUrl size } }")
    try:
        return (gql_adhoc(session, query, {"id": str(media_id)}) or {}).get("media") or {}
    except PixAIError:
        return {}


def video_outputs(task):
    """Extract image-to-video outputs from a getTaskById result. Returns a list of
    {video_media_id, poster_media_id, seed} plus the shared prompt/duration."""
    if not task:
        return [], {}
    params = task.get("parameters") or {}
    # A video task carries ONE of two blocks: `referenceVideo` for a multi-reference
    # generation, `i2vPro` for an ordinary image-to-video. Reading only the first meant every
    # plain i2v -- the common Video-tab case, and everything --sync-videos backfills -- was
    # cataloged with a blank prompt and duration, with nothing to show it had been dropped.
    # The two blocks do NOT agree on the key: referenceVideo carries `prompt`, i2vPro carries
    # `prompts` (see build_video_parameters), so both spellings are read.
    src = params.get("referenceVideo") or params.get("i2vPro") or {}
    shared = {
        "prompt": src.get("prompt") or src.get("prompts") or "",
        "duration": src.get("duration", ""),
        "i2v_model": src.get("model", ""),
        # A video's negative prompt lives INSIDE this block, never at params top level, so
        # extract_full_meta's neg (which reads params.negativePrompts) always came back blank
        # for video and --sync-videos dropped it. Surfaced here so both video row-builders read
        # one source (audit 2026-08-15); _download_video_task already read the same key directly.
        "negative_prompt": src.get("negativePrompts") or "",
    }
    outs = []
    for v in ((task.get("outputs") or {}).get("videos") or []):
        vmid = v.get("mediaId")
        if vmid:
            outs.append({
                "video_media_id": str(vmid),
                "poster_media_id": str(v.get("thumbnailMediaId") or ""),
                "seed": str(v.get("seed") or ""),
            })
    return outs, shared


def run_list_models(args):
    """CLI: search PixAI models and print name / type / generatable version id."""
    from moonglade.backup import _make_session
    session = _make_session(getattr(args, "token", None))
    kw = getattr(args, "list_models", "") or ""
    results = _models.model_search_gql(session, kw, limit=getattr(args, "max", 0) or 25)
    if not results:
        print("No models found for '{}'.".format(kw))
        return
    enc = (sys.stdout.encoding or "utf-8")

    def _safe(t):                       # Windows consoles are often cp1252
        return t.encode(enc, "replace").decode(enc, "replace")
    print("{:<40} {:<14} version id (use as --model)".format("model", "type"))
    for m in results:
        tag = " [NSFW]" if m["is_nsfw"] else ""
        print("{:<40} {:<14} {}{}".format(
            _safe(m["title"][:40]), m["type"][:14], m["version_id"], tag))


# The full-generation-surface columns (issue #18) extract_full_meta resolves and every
# row-builder must persist. One list so a new surface field is wired in exactly one place.
_GEN_SURFACE_FIELDS = (
    "inference_profile", "quality_tag", "prompt_helper", "control_nets", "lora_parameters",
    "priority", "render_seconds", "backend", "started_at", "ended_at", "updated_at",
    "retry_count", "moderation", "video_mode", "video_model",
    # Edit Pro's output format and a GIF's frames (3.22 S5, DESIGN_3.22 5.3).
    "output_format", "frame_count", "frame_duration_ms",
)
# What EVERY create-time row-builder copies from extract_full_meta: the surface fields PLUS
# lineage (source_media_id/derive_kind). The builders used to spread only _GEN_SURFACE_FIELDS,
# so a freshly captured DERIVED image/video landed with a blank lineage panel until a separate
# --backfill-lineage ran (audit 2026-08-15). extract_full_meta already resolves both.
_TASK_ROW_FIELDS = _GEN_SURFACE_FIELDS + ("source_media_id", "derive_kind")


def _prompt_helper_label(params, task):
    """Fold promptHelper.enable + PixAI's detect verdict into one readable label:
    'on' / 'off' / 'off (reason)'. '' when the task carries neither."""
    ph = params.get("promptHelper") if isinstance(params.get("promptHelper"), dict) else {}
    det = task.get("detectPromptHelperResult") if isinstance(task.get("detectPromptHelperResult"), dict) else {}
    reason = (det.get("enableReasonCode") or "").strip()
    if "enable" not in ph and not reason:
        return ""
    base = "on" if ph.get("enable") else "off"
    return "{} ({})".format(base, reason) if reason else base


_RECORDED_OUTPUT_FORMATS = ("svg", "gif")


def _output_format_of(outputs, model_config):
    """"svg" / "gif" for an Edit Pro output, else "" (3.22 S5): the task's outputs.outputFormat
    (what PixAI made) first, then the request's chat.modelConfig.outputFormat. Pure."""
    for v in ((outputs or {}).get("outputFormat"), (model_config or {}).get("outputFormat")):
        v = str(v or "").strip().lower()
        if v:
            return v if v in _RECORDED_OUTPUT_FORMATS else ""
    return ""


def _mc_int_str(model_config, key):
    """A whole-number modelConfig value as a catalog string, '' when absent or not a whole
    number (a bool included). Pure."""
    v = (model_config or {}).get(key)
    return str(v) if isinstance(v, int) and not isinstance(v, bool) else ""


def _task_for_full_meta(session, task_id):
    """The task read for the readers of `parameters` alone -- collect's `--full-meta` and the
    full-meta backfill (DESIGN_3.22 2.8). GraphQL first; if `task(id)` cannot be read, the REST
    record with its stored parameters instead of nothing (`rest_fallback=True`). That record is
    degraded (no per-image seeds, no tombstones, no video outputs) and `extract_full_meta`
    leaves what it cannot know blank. Deletes, video sync, lineage and the publish index do NOT
    use this: they keep `task_detail_gql`'s None."""
    return _task_reads.task_detail_gql(session, task_id, rest_fallback=True)


def extract_full_meta(task):
    """Pull the extended fields out of a getTaskById task dict."""
    from moonglade.account_api import source_media_of_task
    if not task:
        return {}
    params = task.get("parameters") or {}
    outputs = task.get("outputs") or {}
    detail = outputs.get("detailParameters") or {}
    extra = params.get("extra") or {}
    # Full generation surface (issue #18): everything the task record carries that the row used
    # to drop. All pure reads from the task dict; steps/sampler/cfg get a model-preset fallback
    # in the caller (needs the network), the rest resolve here.
    i2v = params.get("i2vPro") if isinstance(params.get("i2vPro"), dict) else {}
    # A video task carries ONE of two blocks, and both name the engine and the quality
    # tier the same way (`model`, `mode`). Reading only i2vPro left every reference-video
    # row's video_model / video_mode blank on every capture road (PROBE_2026-09-26 V09).
    vblock = i2v or (params.get("referenceVideo")
                     if isinstance(params.get("referenceVideo"), dict) else {})
    ii = outputs.get("inferenceInfo") if isinstance(outputs.get("inferenceInfo"), dict) else {}
    stages = ii.get("stages") if isinstance(ii.get("stages"), dict) else {}
    qtag = params.get("qualityTag") if isinstance(params.get("qualityTag"), dict) else {}
    _chat = params.get("chat") if isinstance(params.get("chat"), dict) else {}
    chat_mc = _chat.get("modelConfig") if isinstance(_chat.get("modelConfig"), dict) else {}
    cnets = params.get("controlNets") or []
    lparams = params.get("loraParameters") or []
    run_s = stages.get("pipeline_run_s")
    retry = task.get("retryCount")
    # negativePrompts may live under a few keys depending on PixAI's flow; many
    # newer "structured prompt" tasks have none at all.
    neg = (params.get("negativePrompts") or detail.get("negativePrompts")
           or extra.get("negativePrompts") or params.get("negativePrompt") or "")
    clip = detail.get("clipSkip", params.get("clipSkip", ""))
    # A taskKind=chat task -- an instruct Edit, or a hand/face Fix -- keeps its model inside
    # the `chat` block, and build_chat_edit_parameters sets NO top-level modelId at all, so
    # without this fallback a chat task's Model rendered as an em-dash on the detail page.
    # NOTHING ELSE about a chat task is recoverable here, deliberately: it has no seed, no
    # sampler, no steps and no cfg scale (outputs.detailParameters is absent entirely), and
    # those stay empty rather than borrowing a plausible-looking number the task never had.
    chat = params.get("chat") if isinstance(params.get("chat"), dict) else {}
    model_id = str(params.get("modelId") or chat.get("modelId") or "")
    # PixAI's two CHAT models are the ones this app already names (EDIT_MODELS), so the label
    # resolves locally: a Fix's Model reads "Reference Pro" rather than a 19-digit id, with no
    # extra network round trip. Callers that also run model_name_gql still overwrite it.
    chat_label = (_gen_params.edit_model_by_id(model_id) or {}).get("label", "") if chat else ""
    # LINEAGE: the source image + derivation kind, if this task derived from another image.
    # Filled here so both the forward sync and --backfill-full-meta populate it for free.
    src_mid, derive_kind = source_media_of_task(task)
    return {
        "source_media_id": src_mid or "",
        "derive_kind":     derive_kind or "",
        "prompt_full":    params.get("prompts", ""),
        "natural_prompt": extra.get("naturalPrompts", ""),
        "seed":           str(outputs.get("seed") or ""),
        "steps":          str(detail.get("steps") or ""),
        "sampler":        detail.get("sampler", ""),
        "cfg_scale":      str(detail.get("cfg_scale") or ""),
        "model_id":       model_id,
        "model_name":     chat_label,  # otherwise filled in by caller after model_name_gql
        "loras":          "",  # filled in by caller via resolve_loras()
        "negative_prompt": neg,
        "clip_skip":      str(clip) if clip != "" else "",
        # getTaskById returns paidCredit top-level even for historical tasks (verified
        # against a real captured task, 2026-07-04) -- so full-meta/backfill passes
        # recover spend history, not just fresh generations.
        "paid_credit":    _paid_credit_str(task),
        # Full generation surface (issue #18):
        "inference_profile": str(params.get("inferenceProfile") or ""),
        "quality_tag":       str(qtag.get("prefix") or ""),
        "prompt_helper":     _prompt_helper_label(params, task),
        "control_nets":      json.dumps(cnets) if cnets else "",
        "lora_parameters":   json.dumps(lparams) if lparams else "",
        "priority":          str(params.get("priority") or ""),
        "render_seconds":    ("{:.1f}".format(run_s) if isinstance(run_s, (int, float)) else ""),
        "backend":           str(ii.get("backend") or ""),
        "started_at":        str(task.get("startedAt") or ""),
        "ended_at":          str(task.get("endAt") or ""),
        "updated_at":        str(task.get("updatedAt") or ""),
        "retry_count":       ("" if retry is None else str(retry)),
        "moderation":        str((task.get("moderationAction") or {}).get("promptsModerationAction") or ""),
        "video_mode":        str(vblock.get("mode") or ""),
        "video_model":       str(vblock.get("model") or ""),
        # Edit Pro's output (3.22 S5, DESIGN_3.22 5.3): what PixAI says it made (the task's
        # outputs.outputFormat), else what the request asked for; a GIF's frames from the
        # request. Only the two non-default formats are recorded, so a png edit and every
        # ordinary picture stay blank.
        "output_format":     _output_format_of(outputs, chat_mc),
        "frame_count":       _mc_int_str(chat_mc, "frameCount"),
        "frame_duration_ms": _mc_int_str(chat_mc, "frameDurationMs"),
        # BATCH IDENTITY (issue #33): blank at TASK level on purpose -- outputs.batch is an
        # ordered array with one entry per output, so the index is a per-ROW fact. The raw
        # list is parked under _batch (private, never persisted: _merge_full and the backfill
        # apply iterate _FULL_META_FIELDS only) and each row resolves its own index/size via
        # _with_batch_position. A task with no batch array (edit/upscale/video/chat) parks
        # None and every row of it stays blank -- "not a batch output", never inferred.
        "batch_index": "",
        "batch_size":  "",
        # Per-ROW for the same reason (2026-09-06): PixAI deletes one output at a time, so
        # "does PixAI still have this one" cannot be a task-level answer.
        "cloud_deleted_at": "",
        # A REST-fallback record's batch lists only the LIVE members, so a position read off
        # it would renumber the survivors (issue #33: PixAI's index is permanent). Not parked.
        "_batch":      (outputs.get("batch") if isinstance(outputs.get("batch"), list)
                        and not task.get("_rest_fallback") else None),
    }


def batch_position(batch, media_id):
    """PixAI's own output number for one media of a task (issue #33): the position of
    `media_id` in the task's ORDERED outputs.batch array -- the same <n> the site's own
    download names use (from-PixAI-<taskId>-<n>, verified against real downloads).
    Returns ('<index>', '<size>') as 0-based catalog strings, or ('', '') when there is
    no batch array (edits, upscales, videos, imports) or the media id is not in it --
    blank means "not a batch output", NEVER a guess from media_id order (which can swap
    outputs; probe 2026-08-23). The index is PixAI's permanent fact: a sibling deleted
    later keeps its gap, nothing is ever renumbered.

    A member PixAI has deleted (its entry carries `deletedAt`) reports blank: it is no
    longer one of the task's outputs, so it has no live output number. Its SURVIVING
    siblings are untouched -- they keep the numbers and the batch size PixAI gave them,
    because the deleted entry stays in the array and the site's own
    from-PixAI-<taskId>-<n> download names never shift either."""
    if not isinstance(batch, list) or not batch:
        return "", ""
    mid = str(media_id or "")
    if not mid:
        return "", ""
    for i, entry in enumerate(batch):
        if isinstance(entry, dict) and str(entry.get("mediaId") or "") == mid:
            if entry.get("deletedAt"):
                return "", ""
            return str(i), str(len(batch))
    return "", ""


def _with_batch_position(fm, media_id):
    """Per-ROW view of a task-level full-meta dict (issue #33): fm is fetched and cached
    once per task, but batch_index/batch_size differ per output, so each row resolves its
    own from the raw outputs.batch list extract_full_meta parked under fm['_batch'].
    Returns fm itself when there is nothing to resolve (no batch array, or the media id
    is not one of its outputs -- both fields stay ''), else a shallow copy with both set,
    leaving the shared cached dict untouched.

    `cloud_deleted_at` is the third per-row field and rides here for the same reason
    (2026-09-06): whether PixAI still has THIS image is a per-output fact the task-level
    meta cannot hold.

    WHEN THE MARKER IS ACTUALLY SET -- this path is the quieter of its two writers, and on
    a settled catalog it never fires at all. --backfill-full-meta re-fetches a row only when
    that row is missing its prompt or all of model/steps/sampler/CFG (or when --with-loras /
    --with-credit / --with-surface widen the net), so a row that already carries its detail
    is never revisited and never reaches this line. The writer that does the work in the
    ordinary case is the DELETE path: whenever the app reads a task back from PixAI for a
    delete -- the confirm dialog's question, the delete itself, and the Actions dropdown's
    bulk delete -- it stamps the row of every batch member that answer reports deleted
    (moonglade.gallery's /api/delete-image, and _rows_the_bulk_purge_must_keep).

    IT IS NOT ONLY HAND-RUN ANY MORE (2026-09-06, the living library). --backfill-full-meta
    is a STEP OF --sync (see the CLI's --sync handler: run_download, then this backfill,
    then fix-models), and --sync is one of LIVING_JOBS -- every six hours, enabled by
    default -- so this line is reachable unattended, on whatever rows that run was
    re-fetching anyway. The gate is unchanged and is what keeps it quiet: a row already
    carrying its detail is never revisited. --reconcile-deleted still writes only the
    task-level `deleted_remote` advisory and never looks inside a batch, and the
    fifteen-minute artworks_sweep and the weekly view-count job never touch this column."""
    batch = (fm or {}).get("_batch")
    bi, bs = batch_position(batch, media_id)
    gone = str((_cloud_delete.batch_entry(batch, media_id) or {}).get("deletedAt") or "")
    if not bi and not gone:
        return fm
    fm = dict(fm)
    if bi:
        fm["batch_index"], fm["batch_size"] = bi, bs
    if gone:
        fm["cloud_deleted_at"] = gone
    return fm


def _resolve_model_preset(session, version_id, _cache={}):
    """The model VERSION's default sampling params from its `extra` (`_model_version_gql`)
    -> {steps, sampler, cfg_scale}, each '' when the version exposes no default for it.
    VERSION-accurate (keyed on the exact version the gen used, so no latest-version drift), and
    cached per version id. Never raises.

    Crucially self-limiting: a flow/DiT model like Tsubaki.2 (AuraFlow) exposes samplingSteps
    but NO samplingMethod / cfgScale, so those come back '' and an em-dash there stays the
    honest answer (that model genuinely has no sampler or CFG) -- only a value the model really
    defaults to is ever filled (issue #18)."""
    vid = str(version_id or "")
    if not vid:
        return {}
    if vid in _cache:
        return _cache[vid]
    preset = {}
    try:
        # retries=0 (`_model_version_gql`: a single read, as before). Never raises out: a
        # refusal is caught here and the preset stays {} -- an em-dash is the honest answer
        # when a model genuinely exposes no default for a field.
        data = _models._model_version_gql(session, vid)
        mv = (data.get("generationModelVersion") if isinstance(data, dict) else None) or {}
        ex = mv.get("extra") or {}
        steps, sampler, cfg = ex.get("samplingSteps"), ex.get("samplingMethod"), ex.get("cfgScale")
        preset = {
            "steps":     ("" if steps is None else str(steps)),
            "sampler":   (str(sampler) if sampler else ""),
            "cfg_scale": ("" if cfg is None else str(cfg)),
        }
    except Exception:
        preset = {}
    _cache[vid] = preset
    return preset


def _fill_preset_defaults(session, fm, task):
    """Backfill fm's steps/sampler/cfg_scale from the model VERSION preset when the task itself
    omitted them (issue #18: Tsubaki.2's detailParameters is absent, so the gen ran on the
    model's baked defaults recorded nowhere in the task). Mutates + returns fm.

    Gated to plain IMAGE diffusion gens: a chat/edit task or an i2v video task carries no image
    sampling params, so it is skipped and its em-dashes stay. Only fills a field that is blank
    AND has a non-null preset value -- never overwrites a task-recorded value, never invents one
    the model has no default for."""
    if not isinstance(fm, dict):
        return fm
    params = (task or {}).get("parameters") or {}
    if params.get("chat") or params.get("i2vPro"):     # not a plain image diffusion gen
        return fm
    if (fm.get("steps") or "").strip() and (fm.get("sampler") or "").strip() and (fm.get("cfg_scale") or "").strip():
        return fm                                        # nothing missing -> no lookup
    preset = _resolve_model_preset(session, fm.get("model_id", ""))
    for k in ("steps", "sampler", "cfg_scale"):
        if not (fm.get(k) or "").strip() and preset.get(k):
            fm[k] = preset[k]
    return fm


def resolve_loras(session, task):
    """Read parameters.lora ({loraVersionId: weight}) from a getTaskById task and
    return a readable "Name:0.7, Name2:0.5" string, resolving each LoRA id to a
    name via model_name_gql (cached). Unresolvable ids keep the number. Empty string
    if the task used no LoRAs."""
    params = (task or {}).get("parameters") or {}
    lora = params.get("lora") or {}
    if not isinstance(lora, dict) or not lora:
        return ""
    parts = []
    for vid, weight in lora.items():
        name = _models.model_name_gql(session, vid)
        if not name or str(name) == str(vid) or str(name).isdigit():
            name = "lora {}".format(vid)
        try:
            w = "{:g}".format(float(weight))
        except (TypeError, ValueError):
            w = str(weight)
        parts.append("{}:{}".format(name, w))
    return ", ".join(parts)


def _merge_full(fm, kr):
    """Merge full-meta fields: prefer fresh fm, fall back to known-row kr."""
    return {f: (fm.get(f) or kr.get(f, "")) for f in _FULL_META_FIELDS}


def known_catalog_rows(db_path, ids):
    """The pre-download snapshot carry_local_fields needs: media_id -> existing row.

    Keyed to just this task's media, so it is a lookup rather than a whole-catalog read.
    A catalog that does not exist yet -- the first collect into a fresh output folder,
    before save_catalog creates the table -- means there is nothing local to carry, which
    is an empty map and not an error.
    """
    try:
        rows = rows_for_media_ids(db_path, ids)
    except sqlite3.OperationalError:
        return {}
    return {r["media_id"]: r for r in rows if r.get("media_id")}


def carry_local_fields(row, known):
    """Merge a freshly-rebuilt download row OVER its existing catalog row so LOCAL
    curation survives a re-pull. A download pass only knows API/file fields
    (task_id, filename, url, prompt, seed, model, ...); WITHOUT this merge, every
    re-processed media_id has its locally-owned fields -- collections, rating,
    art_tags, is_published, title, aes_score, blurhash, and any future local
    column -- silently blanked by the full-row upsert. This was a real data-loss
    bug: a --update/--full-meta pass wiped collection tags.

    `known` maps media_id -> the existing catalog row (a pre-download snapshot).
    An empty fresh value never clobbers an existing one, so a missing download
    keeps the old filename. New media_ids (absent from `known`) pass through
    unchanged. Applied at save time, it covers every row-builder path at once.

    APPLIED AT, since issue #19 closed the gap, in TWO places and no others:

      * `build_catalog_row` -- so EVERY create-time capture path builds its row in one
        place: run_sync_videos, run_import_local, run_generate, _download_video_task,
        _download_image_task, run_edit_image, and the gallery's /api/loom/import-bundle.
        The builder applies the merge, but only over the `known` map its CALLER hands it,
        so a site that omits `known` still writes a blanking row -- the shared builder
        removes the drift, not the need to pass the snapshot. (The Loom bundle import
        shipped omitting it, on a comment claiming its file-resolution guard proved the
        media_id was uncataloged; a catalog row outlives its file by design, so it did
        not.) The two collect writers
        (_download_image_task / _download_video_task) are the per-task path every
        create route funnels through -- run_generate, run_edit_image,
        run_generate_video, collect_generation, the watch mirror, CLI --task-id
        recovery -- and until 2026-09-03 they were missing it, so RE-collecting a task
        wiped exactly the fields listed above; a finished generation polled twice was
        enough to do it. Four of the seven builders still had no carry at all until the
        helper gave them one.
      * run_download's page saves, which build their rows from the feed rather than
        through build_catalog_row; `save_catalog_over_snapshot` applies the same rule.

    `known` is a snapshot, so it goes stale while a writer works: every writer that
    carries saves through `save_catalog_over_snapshot`, which merges over the rows as they
    are at write time and never writes back a row deleted meanwhile (2026-11-19: a Sync
    undid ratings, collections and deletes made in the gallery while it ran).
    """
    base = dict(known.get(row.get("media_id", ""), {}))
    for k, v in row.items():
        if v not in ("", None):
            base[k] = v
        else:
            base.setdefault(k, "")
    return base


def _created_at_utc(value=""):
    """A capture's `created_at`: PixAI's own `createdAt` when the task carries one, else
    NOW as UTC + 'Z'.

    The Z matters. `created_at` is sorted as a plain STRING (`_SORT_SQL` does no
    `datetime()` wrapping), so a naive LOCAL-time stamp reads as hours "older" than a
    same-moment UTC one west of Greenwich -- a local save at 23:0X PDT sorted behind rows
    PixAI timestamped 06:05 UTC the "next" day, an hour earlier in real time. Found via
    run_import_local, which had the same defect; the four task-capture paths each carried
    their own copy of this rule AND of the paragraph explaining it, which is why it now
    lives in exactly one place."""
    return value or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def build_catalog_row(media_id, *, fm=None, known=None,
                      task_id="", filename="", url="", source="", status="",
                      created_at="", prompt_full="", prompt_preview=None,
                      natural_prompt="", negative_prompt="", seed="",
                      steps="", sampler="", cfg_scale="", clip_skip="",
                      model_id="", model_name="", loras="", paid_credit="",
                      width="", height="",
                      is_video="", poster_media_id="", video_duration=""):
    """THE create-time catalog row. Every capture path -- download, generate, edit, video,
    local import -- builds its row here, so they all write the same surface and none of them
    can clobber what the user owns (issue #19 item 4).

    Three things happen, in this order, for every caller:

      1. Start from the blank `CATALOG_FIELDS` template, so a row always carries every
         column and a newly added column is blank rather than absent.
      2. Set the API/file fields below, then spread `_TASK_ROW_FIELDS` from `fm`
         (`extract_full_meta`'s output) UNIFORMLY -- the 15 generation-surface columns of
         issue #18 plus lineage (`source_media_id`/`derive_kind`). A caller with no task
         (a local import) passes no `fm` and those stay blank.
      3. Merge the result over `known` via `carry_local_fields`, so LOCAL curation --
         artwork_id, is_published, title, rating, collections, art_tags, aes_score,
         blurhash -- survives a re-capture of a media_id already in the catalog.

    Step 3 is the point. Before this helper, six call sites hand-assembled the same row and
    only two of them remembered the carry; re-collecting an already-collected generation
    rebuilt its row from the blank template and erased the user's work (owner, live,
    2026-09-03: a published piece lost its artwork_id when a relaunch re-polled a finished
    task). `known` maps media_id -> the pre-capture catalog row; pass
    `known_catalog_rows(db_path, ids)`. Omitting it is only correct where the caller has
    already established that the media_id is NOT in the catalog.

    They also DRIFT, which is the other half of why this exists: the 2026-08-15 audit found
    lineage missing from every site at once, and the video paths dropping fields the image
    paths kept. A field added here now reaches every capture path in one edit.

    WHO SETS WHAT (7 call sites; blank at any site not listed):

      field              set by                                source
      -----------------  ------------------------------------  --------------------------
      media_id           all                                   the output's media id
      task_id            SV, GEN, VID, IMG, EDIT               the task's id
      filename           all                                   path relative to out/, '/'-joined
      url                GEN, VID, IMG, EDIT                   resolve_media / media_file_gql
      source             IMP='local'; GEN,VID,IMG,EDIT,LOOM='api'  provenance (SV leaves '')
      status             SV,GEN,VID,IMG,EDIT='completed'; IMP,LOOM='imported'
      created_at         all                                   _created_at_utc(task.createdAt)
                                                               at GEN/VID/IMG/EDIT; the node's
                                                               own createdAt at SV (no
                                                               fallback); file mtime as UTC+Z
                                                               at IMP
      prompt_full        SV, GEN, VID, IMG, EDIT               task prompt / submitted prompt
      prompt_preview     defaults to prompt_full[:100]         SV passes promptsPreview,
                                                               IMP/LOOM the file stem
      negative_prompt    SV, GEN, VID, IMG                     video shared block (SV/VID),
                                                               fm->submitted (GEN), fm (IMG)
      natural_prompt     GEN, IMG                              fm
      seed               SV, GEN, VID, IMG, EDIT               the per-output seed
      steps/sampler/     GEN, IMG                              fm ONLY -- task-echoed ->
        cfg_scale                                              model preset -> blank; never
                                                               the submitted value (owner
                                                               ruling 2026-08-15)
      clip_skip          GEN, IMG                              fm
      model_id           SV, GEN, VID, IMG, EDIT               parameters.modelId / the
                                                               task's numeric modelId, else
                                                               the engine name (VID,
                                                               _video_row_model) / fm /
                                                               chat.modelId
      model_name         GEN, IMG, EDIT, VID                   _resolved_model_name /
                                                               _edit_model_label /
                                                               _video_row_model
      loras              GEN, IMG                              _resolved_loras (resolved
                                                               names+weights, not fm)
      paid_credit        SV, GEN, VID, IMG, EDIT               _paid_credit_str -- TASK-level,
                                                               repeated on each media row
      width/height       SV, GEN, VID, IMG, EDIT               media info -> detailParameters
                                                               -> submitted dims
      is_video           SV, VID='1'; IMP, LOOM per extension
      poster_media_id    SV, VID                               the still-frame media id
      video_duration     SV, VID                               shared/submitted duration
      _TASK_ROW_FIELDS   every site, uniformly                 fm (blank when there is no task)

    Sites: SV=run_sync_videos, IMP=run_import_local, GEN=run_generate,
    VID=_download_video_task, IMG=_download_image_task, EDIT=run_edit_image,
    LOOM=moonglade.gallery's /api/loom/import-bundle."""
    row = {f: "" for f in CATALOG_FIELDS}
    row.update({
        "task_id": task_id, "media_id": media_id, "filename": filename, "url": url,
        "source": source, "status": status, "created_at": created_at,
        "prompt_full": prompt_full,
        "prompt_preview": (prompt_full or "")[:100] if prompt_preview is None else prompt_preview,
        "natural_prompt": natural_prompt, "negative_prompt": negative_prompt,
        "seed": seed, "steps": steps, "sampler": sampler, "cfg_scale": cfg_scale,
        "clip_skip": clip_skip, "model_id": model_id, "model_name": model_name,
        "loras": loras, "paid_credit": paid_credit, "width": width, "height": height,
        "is_video": is_video, "poster_media_id": poster_media_id,
        "video_duration": video_duration,
    })
    # issue #18 + lineage, spread for EVERY caller instead of once per site.
    row.update({k: (fm or {}).get(k, "") for k in _TASK_ROW_FIELDS})
    return carry_local_fields(row, known or {})


def cmd_convert_existing(args, out):
    """Convert all .webp files in the backup tree to the target format in-place."""
    from moonglade.backup import _parallel_map, PixAIError
    target = (args.convert or "png").lower()
    out_ext = ".jpg" if target in ("jpg", "jpeg") else ".png"

    webp_files = sorted(p for p in out.rglob("*.webp")
                        if not p.name.endswith(".part") and p.stat().st_size > 0)
    if not webp_files:
        print("No .webp files found under {}.".format(out))
        return

    print("Found {} .webp file(s); converting to {}.".format(len(webp_files), target))
    if args.keep_webp:
        print("--keep-webp: originals kept alongside converted files.")

    if args.dry_run:
        for p in webp_files[:10]:
            print("  {} -> {}".format(p.name, p.with_suffix(out_ext).name))
        if len(webp_files) > 10:
            print("  ... and {} more".format(len(webp_files) - 10))
        print("\nDry run -- nothing converted. Re-run without --dry-run to apply.")
        return

    ok = failed = 0
    total = len(webp_files)
    workers = max(1, getattr(args, "workers", 1) or 1)
    if workers > 1:
        print("Converting with {} parallel workers.".format(workers))
    _prog = getattr(args, "progress", None)
    pillow_missing = False
    for p, res in _parallel_map(
            webp_files,
            lambda f: _media_fetch.convert_image(f, target, args.jpeg_quality, args.jpeg_bg,
                                    keep_original=args.keep_webp),
            workers, _prog):
        note = res[1] if res else "error"
        if note == "pillow-missing":
            pillow_missing = True
            break
        if note == "ok":
            ok += 1
        else:
            print("  FAILED {}: {}".format(p.name, note))
            failed += 1
        if not _prog and workers <= 1:
            sys.stdout.write("\r  {:,}/{:,}  ok {:,}  failed {:,}  ".format(
                ok + failed, total, ok, failed))
            sys.stdout.flush()
    if pillow_missing:
        raise PixAIError("--convert-existing needs Pillow:  pip install pillow")

    print("\nConverted: {}, failed: {}.".format(ok, failed))
    if failed:
        print("Failed files left as .webp -- re-run to retry.")
