"""
moonglade/gen_cli.py
====================
The command-line create runners: `run_generate`, `run_generate_video`, `run_reference_video`,
`run_edit_image` and `run_upload`, the helpers only they read (`_maybe_dump_params`,
`_outputs_or_raise`, `_print_gate_receipt`, `_i2v_cli_unsent_notes`, `_resolve_refs`), and the
task recovery they and the road's `collect_generation` use (`_download_video_task`,
`_download_image_task` and their readers). Moved verbatim out of moonglade/backup.py in the 3.22
split (phase 5).

It reaches the split modules as `_gen_road.X`, `_gen_params.X`, `_cards.X`, `_models.X`,
`_task_reads.X`, `_mirror.X` and `_media_tools.X`, the way the engine did once they moved out.
The names it reads from the engine (the READ_ONLY gate `_check_read_only`, `_make_session`, the
catalog and file helpers, the downloaders, the error classes) are imported from
moonglade.backup inside each function that uses them, at call time, so a test's patch of
backup's binding still reaches them and importing this module never imports the engine.
"""
import json
from pathlib import Path

from moonglade import cards as _cards
from moonglade import gen_params as _gen_params
from moonglade import gen_road as _gen_road
from moonglade import media_tools as _media_tools
from moonglade import mirror as _mirror
from moonglade import models as _models
from moonglade import task_reads as _task_reads


def _maybe_dump_params(args, result):
    """If --dump-params is set, print the task's full submit `parameters` (the exact
    shape PixAI received). Handy for banking a param shape off a recovered --task-id
    without a live browser capture. Read-only; prints nothing otherwise.

    Also prints the task's own status. Found needed 2026-07-21: recovering a task is
    almost always done BECAUSE something looked wrong, and the params alone can't say
    whether PixAI ever actually ran it -- this used to print only what was submitted,
    never what happened to it, so the one moment you most want to know the outcome was
    exactly when this told you nothing about it."""
    if not getattr(args, "dump_params", False):
        return
    params = (result or {}).get("parameters")
    print("=== task parameters (full submit shape) ===")
    print(json.dumps(params if params is not None else result, indent=2, ensure_ascii=False))
    print("=== end parameters ===")
    status = (result or {}).get("status")
    if status:
        print("task status: {}".format(status))


def _outputs_or_raise(result, found, empty_message):
    """Common tail for every 'download a completed task's outputs' function: raise
    EmptyOutputsError when there is nothing to download, with a message that matches
    what actually happened rather than always claiming the task 'completed'.

    Found 2026-07-21 chasing a real report of edit jobs that looked like they'd never
    reached PixAI. They had: a real task id was issued (the spend already happened),
    but PixAI's own status for the task was 'failed' -- and every one of the four call
    sites below said 'task completed but no media ids found' regardless, because none
    of them looked at `result["status"]` before writing the message. For a task PixAI
    itself marked failed, 'completed' is not almost-right, it's the opposite of what
    happened, and it is exactly the kind of thing that reads as a tool bug instead of
    a PixAI-side rejection.

    `empty_message` is the ORIGINAL message, used verbatim for the case it was always
    right about -- a task that is genuinely done with empty outputs (e.g. silently
    content-filtered). Only the newly-distinguished failed/cancelled/rejected case gets
    different text; nothing about the genuinely-empty case changes.

    Issue #8 (2026-08-13) added the third case the same lesson demanded: a task whose
    status is NON-terminal (queued/running) is not missing anything -- it simply hasn't
    produced output YET, and 'no media found' there reads as a lost paid generation and
    sends real debugging effort at a task that is fine. Wait vs. investigate are
    opposite responses; the message now says which one applies."""
    from moonglade.backup import EmptyOutputsError
    if found:
        return
    raw = str((result or {}).get("status") or "").lower()
    if raw in _task_reads._GEN_FAIL:
        raise EmptyOutputsError(
            "PixAI reported this task as '{}' -- it did not complete, so there is "
            "nothing to recover. Check pixai.art for why, or resubmit.".format(raw))
    if raw and raw not in _task_reads._GEN_DONE:
        raise EmptyOutputsError(
            "this task is still '{}' on PixAI -- nothing to collect YET. It hasn't "
            "finished (or failed); try again once it completes.".format(raw))
    raise EmptyOutputsError(empty_message)


def _print_gate_receipt(adjusted, gated=True):
    """The CLI's half of the SCOPE_2026-09-26 receipt: what the per-model gate changed,
    printed under the parameters (used None = not sent, printed "off"). A long value -- a
    negative prompt the model does not take -- is shortened to its first characters.
    `gated=False` is a preview that could not reach the model's rules (offline / no key)."""
    if not gated:
        print("(Not checked against this model's own rules -- offline or no key. A --confirm "
              "run checks them before it submits.)")
        return

    def _short(v):
        s = "off" if v is None else str(v)
        return s if len(s) <= 40 else s[:39] + "…"
    for a in adjusted or []:
        why = a.get("why")
        print("  adjusted: {} {} -> {}{}".format(
            a.get("field"), _short(a.get("asked")), _short(a.get("used")),
            " ({})".format(why) if why else ""))


def _card_sent(params):
    """True when the send carried a free card (the card step wrote kaisuukenId into it), for
    the poll's terminal card check (DESIGN_3.22 2.4 rule 7)."""
    return bool(isinstance(params, dict) and params.get("kaisuukenId"))


def run_generate(args):
    """Create images via PixAI (createGenerationTask), poll to completion, download
    the results into the backup, and catalog them as source='api'. GUARDED: without
    --confirm it only prints a preview (spends no credits). Submits through
    submit_generation() (and so through gql_mutate) + the shared session/download/
    catalog plumbing.

    A task recovered by --task-id that turns out to have VIDEO outputs is collected as
    video, through the same _download_video_task the video commands use -- never dragged
    through the image path. See the comment at the outputs split below for why."""
    from moonglade.backup import (_check_read_only, init_db, _make_session, _resolved_loras,
                                  _resolved_model_name, save_catalog_over_snapshot)
    from moonglade.full_meta import (build_catalog_row, _created_at_utc, extract_full_meta,
                                     _fill_preset_defaults, known_catalog_rows, _paid_credit_str,
                                     video_outputs)
    from moonglade.media_fetch import download, resolve_media
    from moonglade.history import build_stem_name
    out = Path(args.out)
    params = _gen_params._gen_parameters(args)
    existing_task = (getattr(args, "task_id", "") or "").strip()
    if not existing_task and isinstance(params, dict):
        # 3.22 S5: an SVG or a GIF is never a base (a --params-json reference or context
        # image) -- by the catalog under --out, then the extension, before anything is sent.
        _gen_params.refuse_unusable_sources(
            [params.get("mediaId")] + list(params.get("contextImages") or []), "base",
            _gen_params.catalog_source_format(out))

    # SCOPE_2026-09-26 G7: gate ONCE, right after the build, and use that one dict for the
    # preview print, _preview_card_note, _apply_kaisuuken and submit_generation -- so the card
    # is matched against the shape that is sent (the backstop gates inside price_task and
    # submit_generation return this same object). The gate needs a session for its
    # read-only lookups; a PREVIEW that cannot make one (offline, no key) prints the ungated
    # build and says so, exactly as its card note already fails soft. A --confirm run makes
    # its session here and fails as it always did when it cannot. A --task-id recovery
    # submits nothing, so it is not gated.
    session = None
    adjusted = []
    if not existing_task:
        if getattr(args, "confirm", False):
            # READ_ONLY refuses a --confirm run BEFORE the gate's read-only PixAI lookups
            # (/inference-profiles, /features, /size-config) and before any gate refusal, so
            # a READ_ONLY install never calls PixAI on a spend path and always reads the
            # READ_ONLY message (review R8). An EXTRA, earlier call: the existing guard below,
            # ahead of _apply_kaisuuken, stays exactly where it is.
            _check_read_only("submit a generation (spends credits)")
        try:
            session = _make_session(getattr(args, "token", None))
        except Exception:
            if getattr(args, "confirm", False):
                raise
            session = None
        if session is not None:
            params, adjusted = _models._gate_image_params(session, params)
            _models._refuse_lost_upscale(args, params)
        # V12 (DESIGN_3.22 2.3): the road-aware wire step BEFORE the preview and the card
        # check, so the CLI quotes and card-checks the shape the create door sends.
        params = _gen_params.to_wire("image", params)

    if not existing_task and not getattr(args, "confirm", False):
        # 3.22 review F10: the door's own wire guard, so the preview refuses what --confirm
        # would (an old --dump-params shape's top-level naturalPrompts) instead of showing it.
        _gen_params.preview_wire("image", params)
        print("=== PixAI task.createTask, POST /v2/task/create (PREVIEW -- no credits spent) ===")
        print(json.dumps({"parameters": params}, indent=2))
        _print_gate_receipt(adjusted, gated=session is not None)
        _cards._preview_card_note(args, params)
        print("\nThis would SPEND PixAI credits (unless free above). Re-run with --confirm to submit.")
        return {"submitted": False}

    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    init_db(db_path)                  # generation can seed a fresh backup
    if session is None:
        session = _make_session(getattr(args, "token", None))
    _print_gate_receipt(adjusted, gated=True)
    thumb_dir = out / "gallery" / "thumbs"
    from moonglade.thumbs import make_thumbnail

    if existing_task:
        # Recover an already-created generation by id (no new credits). Tool/API
        # generations don't enter listUserTaskSummaries, so --update can't fetch
        # them -- this is how you reclaim a stranded paid generation.
        task_id = existing_task
        print("Fetching existing task (no credits):", task_id)
    else:
        # submit_generation() now owns both the actual mutation and the inferenceProfile
        # retry (2026-07-24 -- shared with every other caller, including the web
        # /api/generate route), so this CLI runner just calls through it instead of
        # duplicating that logic. It still needs its OWN _check_read_only call here
        # though, before _apply_kaisuuken's free-card check: that's a real network call
        # that fires BEFORE submit_generation() is even reached below, so relying only on
        # the guard inside submit_generation() would let it through first under
        # READ_ONLY -- the exact bug _check_read_only's own docstring and
        # dev/tests/test_read_only_cli_paths.py describe finding.
        _check_read_only("submit a generation (spends credits)")
        print("Submitting generation task...")
        # V8 (DESIGN_3.22 2.5): the creating identity is chosen ONCE, after READ_ONLY; the card
        # check and the create door both ride it. Poll and download stay on `session` (F6).
        from moonglade import pixai_client as _pixai_client
        create_client = _pixai_client._client_of(session).for_create()
        _cards._apply_kaisuuken(create_client, params, args)
        # 3.21.2 (L1): an answer that cannot show whether the task was made says so in plain
        # words and exits non-zero -- never a raw transport error that reads like "nothing
        # happened, try again". `reached` is submit_generation's own mark just before the send.
        reached = _gen_road.spend_watch()
        task_id = _gen_road._cli_send_once(
            lambda: _gen_road.submit_generation(create_client, params, kind="image"),
            reached=lambda: reached.v)
        print("  task id:", task_id)

        _task_reads._poll_task_status(session, task_id, getattr(args, "poll_timeout", 300),
                          interval=3, label="generate", fail_noun="generation",
                          card_sent=_card_sent(params))

    # The Task type exposes its media under `outputs` (mediaId / batchMediaIds /
    # videos), NOT at the top level. getTaskById returns that whole object and is
    # already proven, so reuse it for the result rather than guessing an ad-hoc
    # selection set.
    result = _task_reads.task_detail_gql(session, task_id) or {}
    _maybe_dump_params(args, result)
    outputs = result.get("outputs") or {}
    # _task_image_media prefers outputs.batch[] (the real individual images) over
    # outputs.mediaId (the composite grid PixAI returns for any batchSize>1 task) --
    # reading mediaId/batchMediaIds directly here used to save only the grid and
    # silently drop every individual image on a multi-image generation (audit:
    # fail-open/unfiled-workflow-findings, 2026-07-21).
    media = _task_image_media(outputs)
    seeds = dict(media)
    mids = list(dict.fromkeys(mid for mid, _ in media))
    # outputs.videos USED TO BE APPENDED TO `mids` and walked by the image loop below, which
    # downloaded the mp4 into images/ and wrote it a catalog row off `{f: "" for f in
    # CATALOG_FIELDS}` -- so is_video stayed blank. The gallery lists images with
    # `COALESCE(is_video,'') != '1'`, so the clip was served as an image: an <img> pointed at
    # an mp4 (broken tile), no poster thumbnail, and no faststart remux, none of which the
    # image path knows how to do (M16, 2026-07-27). Reachable simply by handing
    # `--generate --task-id` an i2v or reference-video id -- a mispaste, or a script looping
    # over a mixed list of ids.
    #
    # So videos go to the code that actually handles videos. Collecting rather than refusing
    # is what collect_generation (the /watch and web routes) already does off the same
    # outputs.videos tell, and refusing would strand the outputs of a task the user has
    # ALREADY paid for behind a second command.
    #
    # What is recovered, honestly: the FILE, its is_video flag, its poster and its faststart
    # remux -- always. The prompt/duration/model on the row are best-effort. `params` here is
    # the image-gen submit block, so _download_video_task's `sent` lookup finds neither
    # i2vPro nor referenceVideo in it and falls back to `video_outputs`' shared block -- and
    # that reads `parameters.referenceVideo` ONLY. A reference-video task therefore recovers
    # its prompt and duration; a pure i2v (i2vPro) task lands with those three columns blank
    # and needs a --backfill-full-meta pass to fill them. Blank-but-filed beats an mp4 served
    # through an <img> tag, which is what this branch replaced, but do not read the comment
    # above as a promise that the metadata always survives -- it does not.
    vouts, _vshared = video_outputs(result)
    _outputs_or_raise(result, mids or vouts, "task completed but no media ids found")

    # Prefer the task's actual metadata (authoritative, and the only source when recovering by
    # --task-id); fall back to the params we submitted -- EXCEPT the sampling fields, see below.
    fm = extract_full_meta(result)
    # steps/sampler/cfg_scale follow the MODEL, not the submit. A task that recorded none ran on
    # the model's baked defaults, so the VERSION preset is their truth -- and where the model
    # genuinely has no sampler/CFG (AuraFlow, e.g. Tsubaki.2) the honest answer is a blank, not
    # the samplingSteps/cfgScale we happened to send and the model ignored. So these three read
    # from `fm` below (task-echoed -> preset -> blank) and NEVER fall back to the submitted value
    # (owner ruling 2026-08-15). _fill_preset_defaults populates fm's blanks from the preset; it
    # used to sit here and let the preset preempt _pick's submitted fallback for `steps` only,
    # while `cfg` still leaked the submitted 7.0 -- an inconsistency this removes. Matches
    # _download_image_task, the sibling downloader, which already reads these straight from fm.
    _fill_preset_defaults(session, fm, result)   # issue #18: model-preset steps/sampler/cfg

    def _pick(fm_key, *param_keys):
        if fm.get(fm_key):
            return str(fm[fm_key])
        for pk in param_keys:
            if params.get(pk):
                return str(params[pk])
        return ""

    img_dir = out / "images"
    rows, saved = [], []
    # The pre-download snapshot build_catalog_row carries forward -- see its step 3 and
    # _download_image_task's fuller note. Recovering a task by --task-id can perfectly
    # well land on media that is already catalogued, rated and published.
    known = known_catalog_rows(db_path, mids)
    for mid in mids:
        url, info = resolve_media(session, mid)
        if not url:
            print("  no url for media", mid)
            continue
        prompt = fm.get("prompt_full") or params.get("prompts", "")
        stem = img_dir / build_stem_name(prompt, task_id, mid,
                                         getattr(args, "name_length", 60),
                                         getattr(args, "name_sep", "_"))
        status, path = download(session, url, stem)
        if status not in ("ok", "skip") or not path:
            continue
        full = build_catalog_row(
            mid, fm=fm, known=known,   # fm spread: issue #18 + lineage
            task_id=str(task_id),
            filename=str(path.relative_to(out)).replace("\\", "/"),
            url=url, source="api", status="completed",
            created_at=_created_at_utc(result.get("createdAt")),
            prompt_full=prompt,        # prompt_preview derives from it
            negative_prompt=_pick("negative_prompt", "negativePrompts"),
            seed=seeds.get(mid) or _pick("seed", "seed"),   # per-image seed on a batch
            # Model's truth, not the submit: fm holds task-echoed -> preset -> blank. No
            # _pick here on purpose -- a submitted samplingSteps/cfgScale the model ignored
            # must not stand in for the model's real behavior (owner ruling; see above).
            steps=fm.get("steps", ""),
            cfg_scale=fm.get("cfg_scale", ""),
            model_id=_pick("model_id", "modelId"),
            # Resolved here, not just in the backfill. extract_full_meta only fills
            # model_name for a CHAT task (from the local EDIT_MODELS table); every ordinary
            # generation left it blank, so every freshly captured image showed a raw
            # 19-digit model id on its detail page until a later --backfill-full-meta
            # happened to come past. model_name_gql is process-cached, so this is one call
            # per distinct model for the whole run, not one per image.
            model_name=_resolved_model_name(session, fm, _pick("model_id", "modelId")),
            # Four fields extract_full_meta hands over that this row used to drop, so they
            # arrived blank on every live capture and only appeared once a
            # --backfill-full-meta came past -- which is the manual step the whole
            # capture-it-as-it-happens path exists to remove. `loras` in particular is
            # always "" out of extract_full_meta by design: it documents that the CALLER
            # resolves it, the backfill did, and this did not.
            sampler=fm.get("sampler", ""),
            natural_prompt=fm.get("natural_prompt", ""),
            clip_skip=fm.get("clip_skip", ""),
            loras=_resolved_loras(session, result),
            paid_credit=_paid_credit_str(result),   # actual cost, task-level
            width=str((info or {}).get("width") or params.get("width") or ""),
            height=str((info or {}).get("height") or params.get("height") or ""))
        rows.append(full)
        make_thumbnail(path, thumb_dir / "{}.jpg".format(mid))
        saved.append(str(path))

    if rows:
        save_catalog_over_snapshot(db_path, rows, known)

    videos = []
    if vouts:
        print("This task has {} VIDEO output(s) -- collecting them as video (videos/, "
              "is_video=1, poster thumbnail, faststart), not as images.".format(len(vouts)))
        if not mids:
            print("  (a video task: `--generate-video --task-id {}` is the direct route)"
                  .format(task_id))
        try:
            videos = _download_video_task(session, result, task_id, out, args, params)
        except Exception as e:                # noqa: BLE001 -- see below; images are already safe
            # FAIL SOFT, like the image loop above. That loop walks past an image it cannot
            # resolve or download with a `continue`; this block had no equivalent, so one
            # media-CDN TLS failure or a dropped connection inside download() -- which
            # answers an SSLError with `raise PixAIError(_ssl_help())` -- escaped through
            # main's handler. The images were already downloaded AND already in the catalog
            # two lines up, but the user got a traceback-shaped exit instead of the summary
            # listing them, and run_generate's return dict never happened (M16, 2026-07-27).
            #
            # Broad on purpose, and safe to be: everything the image half of this command
            # promised is durable before we get here, the clip is still on PixAI (already
            # paid for, recoverable for free), and the message below names the command that
            # fetches it. KeyboardInterrupt is not an Exception, so Ctrl-C still stops the run.
            print("  video collection FAILED ({}) -- {}".format(
                str(e)[:200],
                "the {} image(s) below are saved and cataloged.".format(len(saved))
                if saved else "this task had no image outputs, so nothing was collected."))
            print("  The clip is still on PixAI and costs nothing to re-fetch: "
                  "`--generate-video --task-id {}`".format(task_id))

    # A hidden recovery feat: a stranded task pulled back by id. Counted once per RECOVERY, whatever
    # kind of output it turned out to hold -- this used to live inside `if rows:`, so a
    # video-only task (rows is empty by construction for one) recovered nothing as far as the
    # ledger was concerned, and the achievement that exists to reward exactly that rescue
    # never moved (M16, 2026-07-27).
    if existing_task and (rows or videos):
        try:
            from moonglade.telemetry import telem_bump
            telem_bump("recover_events", out_dir=out)
        except Exception:
            pass

    print("Generated + cataloged {} image(s):".format(len(saved)))
    for s in saved:
        print("  " + s)
    if videos:
        print("Generated + cataloged {} video(s):".format(len(videos)))
        for s in videos:
            print("  " + s)
    return {"submitted": True, "task_id": task_id, "images": len(saved),
            "videos": len(videos)}


def _video_row_model(session, result, params, sent, fm):
    """(model_id, model_name) for a video row being catalogued live (PROBE_2026-09-26 V09,
    owner ruling 3 of 2026-09-26).

    THE STORED TASK WINS. The engine is the task's own video block (fm.video_model), and the
    submitted block (`sent`) only fills in when the task has none. model_id is the TASK's
    numeric top-level `modelId` (what PixAI stamped on the stored task, from getTaskById);
    the submitted params' modelId counts only when it is this engine's own id. On the
    `--generate-video --task-id` recovery road `params` is rebuilt from the CLI args, not
    read from the task (engine defaulting to v4.0.1), so trusting it filed a recovered
    Tsubaki or V3.0 Flash clip under V4.0 Lite's id and title (review f-V-F1).

    An engine VIDEO_MODELS knows takes only ITS OWN id (video_model_id). Real v2.7 and
    v3.0.1 tasks carry modelId 1648918127446573124, an IMAGE checkpoint (see
    build_video_parameters' docstring); titling that id would file an image model's name on
    a video row, so such a row keeps the engine name, as the repair migration leaves v2.7 /
    v3.0.1 rows (review f-V-F2 / V-R2; the owner can widen this). An engine the roster does
    not know yet takes any numeric id. Otherwise the engine NAME, so a row is never left
    with '' when the engine is known. It used to be the engine name unconditionally, which
    split one model across two ids (--sync-videos writes the number) and handed "tbkv1.0.1"
    to the version lookup as if it were a version id.

    model_name is the version's own title from model_name_gql for a numeric id ("Tsubaki
    Video v1.0"), falling back to the VIDEO_MODELS label for the engine. Video model names
    are dynamic now (ruling 3, reversing 2026-08-15's "a video row's model_name stays
    blank"): the Tsubaki engines are the first to carry a name rather than a version string.
    A lookup failure costs the label, never the row."""
    from moonglade.backup import _resolved_model_name
    engine = str((fm or {}).get("video_model") or (sent or {}).get("model") or "").strip()
    task_params = (result or {}).get("parameters")
    task_params = task_params if isinstance(task_params, dict) else {}
    mid = ""
    for cand in ((fm or {}).get("model_id"), task_params.get("modelId")):
        c = str(cand or "").strip()
        if c.isdigit():
            mid = c
            break
    if not mid and isinstance(params, dict):
        c = str(params.get("modelId") or "").strip()
        if c and c == _gen_params.video_model_id(engine):
            mid = c
    if mid and not _gen_params._video_model_id_fits(engine, mid):
        mid = ""
    name = ""
    if mid:
        got = _resolved_model_name(session, {}, mid)
        if got and got != mid and not str(got).isdigit():
            name = str(got)
    if not name:
        name = (_gen_params.VIDEO_MODELS.get(engine) or {}).get("label", "")
    return (mid or engine), name


def _download_video_task(session, result, task_id, out, args, params):
    """Download + catalog the video output(s) of a completed task. Shared by i2v (i2vPro)
    and reference-video (referenceVideo) -- reads outputs.videos + the submitted block
    generically. Returns the list of saved file paths."""
    from moonglade.backup import save_catalog_over_snapshot
    from moonglade.full_meta import (build_catalog_row, _created_at_utc, extract_full_meta,
                                     known_catalog_rows, media_file_gql, _paid_credit_str,
                                     video_outputs)
    from moonglade.media_fetch import download, resolve_media
    from moonglade.history import build_stem_name
    outs, shared = video_outputs(result)
    _outputs_or_raise(result, outs, "video task completed but no video outputs found")
    detail = ((result or {}).get("outputs") or {}).get("detailParameters") or {}
    fm = extract_full_meta(result)   # issue #18: the full generation surface for the video row
    sent = (params.get("i2vPro") or params.get("referenceVideo") or {}) if isinstance(params, dict) else {}
    prompt = shared.get("prompt") or sent.get("prompts") or sent.get("prompt") or ""
    model_id, model_name = _video_row_model(session, result, params, sent, fm)

    from moonglade.thumbs import make_thumbnail
    thumb_dir = out / "gallery" / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    vdir = out / "videos"
    vdir.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    rows, saved = [], []
    # The same pre-download snapshot the image path takes, and for the same reason: the
    # row is rebuilt from a blank template, so without the carry a re-collect blanks the
    # video's rating, collections, title and published state. build_catalog_row applies it.
    known = known_catalog_rows(db_path, [o.get("video_media_id") for o in outs])
    for o in outs:
        vmid = o["video_media_id"]
        url = media_file_gql(session, vmid).get("fileUrl")
        if not url:
            print("  no file url for video", vmid)
            continue
        stem = vdir / build_stem_name(prompt, task_id, vmid, getattr(args, "name_length", 60), "_")
        status, path = download(session, url, stem)
        if status not in ("ok", "skip") or not path:
            continue
        full = build_catalog_row(
            vmid, fm=fm, known=known,   # fm: issue #18 (no preset fill: video)
            task_id=str(task_id),
            filename=str(path.relative_to(out)).replace("\\", "/"),
            url=url, source="api", status="completed", is_video="1",
            created_at=_created_at_utc(result.get("createdAt")),
            prompt_full=prompt,        # prompt_preview derives from it
            negative_prompt=sent.get("negativePrompts", ""),
            seed=str(o.get("seed") or ""),
            poster_media_id=o.get("poster_media_id", ""),
            paid_credit=_paid_credit_str(result),   # actual cost, task-level
            video_duration=str(shared.get("duration") or sent.get("duration") or ""),
            model_id=model_id, model_name=model_name,
            width=str(detail.get("width") or ""),
            height=str(detail.get("height") or ""))
        # Poster thumbnail is COSMETIC -- it must never block cataloging the finished video.
        # A transient Windows lock on the poster's temp file (WinError 32) used to raise from
        # download() right here, before rows.append below, so the clip was pulled to videos/
        # but never saved and the panel never showed it. A missing/failed thumb self-heals on
        # the next --rebuild-thumbs / --sync.
        pm = o.get("poster_media_id")
        thumb_path = thumb_dir / "{}.jpg".format(vmid)
        try:
            if pm:
                purl, _pi = resolve_media(session, pm)
                if purl:
                    ptmp = out / "gallery" / "_postertmp"
                    ptmp.mkdir(parents=True, exist_ok=True)
                    st, pp = download(session, purl, ptmp / str(pm))
                    if st in ("ok", "skip") and pp:
                        make_thumbnail(pp, thumb_path)
                        try:
                            pp.unlink()              # don't leave poster temps to accumulate / be re-locked
                        except OSError:
                            pass
            # Poster-less (or poster fetch failed): ffmpeg the mp4's first frame, so the
            # gallery never shows a blank tile waiting on a later sync. Matches _do_task /
            # run_import_local; no-op if ffmpeg isn't on PATH.
            if not thumb_path.exists():
                _media_tools.video_poster_thumb(path, thumb_path)
        except Exception as e:                       # noqa: BLE001 -- poster is cosmetic, never abort the catalog
            print("  poster thumbnail failed for {} ({}); video still cataloged".format(vmid, e))
        _media_tools.video_faststart(path)                        # iOS needs moov at the front to stream
        rows.append(full)
        saved.append(str(path))
    if rows:
        save_catalog_over_snapshot(db_path, rows, known)
    return saved


def _task_image_media(outputs):
    """The REAL output images of a completed image task as [(media_id, seed)], newest logic:
    a batchSize>1 task stores a 2x2 COMPOSITE GRID under outputs.mediaId and the INDIVIDUAL
    images under outputs.batch[] -- so we take the individuals (the actual generations), never
    the grid. batchSize==1 / legacy tasks fall back to outputs.mediaId (+ legacy batchMediaIds).
    Per-image seed comes from batch[].seed, else the shared outputs.seed. Deduped, order-kept.

    This is why batch generations were previously under-captured: the old path read
    outputs.batchMediaIds (which is null on modern tasks) and saved only the grid.

    A member PixAI has DELETED keeps its place in the array and gains a `deletedAt`
    (2026-09-06). It is not one of the task's images any more, so it is skipped here --
    otherwise every re-sync would list it and download the deleted image straight back in.
    A batch whose members are ALL deleted therefore yields nothing, and deliberately does
    not fall back to outputs.mediaId: on a batch task that is the combined preview picture,
    never one of the images."""
    outputs = outputs or {}
    batch = outputs.get("batch") or []
    shared_seed = str(outputs.get("seed") or "")
    pairs = []
    if batch:                                        # modern batch: save the individuals
        for b in batch:
            mid = str((b or {}).get("mediaId") or "")
            if mid and not (b or {}).get("deletedAt"):
                pairs.append((mid, str((b or {}).get("seed") or shared_seed)))
    else:                                            # single image (or legacy shape)
        if outputs.get("mediaId"):
            pairs.append((str(outputs["mediaId"]), shared_seed))
        for m in outputs.get("batchMediaIds") or []:
            pairs.append((str(m), shared_seed))
    seen, uniq = set(), []
    for mid, sd in pairs:
        if mid and mid not in seen:
            seen.add(mid)
            uniq.append((mid, sd))
    return uniq


def _task_detail_query(session, task_id):
    """The task read collect_generation (the --task-id / --dump-params recovery path) and the
    gallery's queue estimate make: `task_detail_gql`, the full document (#91). Its narrower
    ad-hoc fallback went with the saved request it stood in for."""
    return _task_reads.task_detail_gql(session, task_id)


def _fix_source_label(task, out):
    """The readable half of a Fix output's filename: the prompt of the SOURCE image the Fix
    ran on, looked up in this backup's own catalog by media_id, falling back to that
    media_id when the source isn't ours (a fresh upload) and to '' when the task names no
    source at all. Naming a Fix after the image it repaired is what makes a folder of them
    browsable, and it lands the two files next to each other in a sorted listing.

    Fails soft: an unreadable catalog costs the name its readable half, never the download."""
    from moonglade.backup import load_catalog
    params = (task or {}).get("parameters") or {}
    chat = params.get("chat") if isinstance(params.get("chat"), dict) else {}
    src = str(chat.get("mediaId") or params.get("mediaId") or "")
    if not src:
        return ""
    try:
        row = next((r for r in load_catalog(Path(out) / "catalog.db")
                    if r.get("media_id") == src), None)
    except Exception:                      # noqa: BLE001 -- a naming nicety, never a blocker
        row = None
    label = ((row or {}).get("prompt_preview") or (row or {}).get("prompt_full") or "").strip()
    return label or src


def _download_image_task(session, result, task_id, out, args, prompt="", model_name=""):
    """Download + catalog the image output(s) of a completed task. Saves the individual batch
    images (not the composite grid) via _task_image_media, storing each image's own seed.
    resolve_media -> download -> catalog as source='api'. Returns the saved file paths."""
    from moonglade.backup import _resolved_loras, _resolved_model_name, save_catalog_over_snapshot
    from moonglade.full_meta import (build_catalog_row, _created_at_utc, extract_full_meta,
                                     _fill_preset_defaults, known_catalog_rows, _paid_credit_str)
    from moonglade.media_fetch import download, resolve_media
    from moonglade.history import build_fix_stem_name, build_stem_name, fixer_block
    outputs = result.get("outputs") or {}
    media = _task_image_media(outputs)
    _outputs_or_raise(result, media, "task completed but no media ids found")
    from moonglade.thumbs import make_thumbnail
    thumb_dir = out / "gallery" / "thumbs"
    img_dir = out / "images"
    db_path = out / "catalog.db"
    # A hand/face Fix is the one task family whose `prompts` is PixAI's own fixed template,
    # so build_stem_name would give every Fix ever collected the same unreadable name --
    # build_fix_stem_name names it from the source image + a fix-face/fix-hand marker
    # instead. Detected here rather than at the call sites so recovering a Fix by --task-id
    # names it the same way the web collect does. NEW OUTPUT ONLY: nothing renames a file
    # already on disk.
    fx = fixer_block(result)
    fix_label = _fix_source_label(result, out) if fx is not None else ""
    fm = extract_full_meta(result)
    _fill_preset_defaults(session, fm, result)   # issue #18: model-preset steps/sampler/cfg
    rows, saved = [], []
    # THE PRE-DOWNLOAD SNAPSHOT. Every row below is rebuilt from a blank CATALOG_FIELDS
    # template, which knows only API/file fields -- so upserting it raw BLANKS everything
    # locally owned: artwork_id, is_published, title, rating, collections, art_tags,
    # aes_score, blurhash. Collecting a task a second time therefore erased the work of
    # having published, rated and filed the picture. (Owner, live, 2026-09-03: a published
    # piece lost its artwork_id after a relaunch re-polled a finished task.) Keyed to this
    # task's media only, so it stays a lookup rather than a whole-catalog read.
    # build_catalog_row applies it -- which is what makes this structural rather than
    # something each of the capture paths has to remember (issue #19).
    known = known_catalog_rows(db_path, [m for m, _ in media])
    for mid, seed in media:
        url, info = resolve_media(session, mid)
        if not url:
            print("  no url for media", mid)
            continue
        name_len = getattr(args, "name_length", 60)
        name_sep = getattr(args, "name_sep", "_")
        if fx is not None:
            # A Fix made since PixAI's Hand/Face Fix launch may carry `passes` (each with
            # its own tag) instead of, or beside, `boxes`; fix_marker reads `tag` off both.
            fix_parts = list(fx.get("boxes") or []) + list(fx.get("passes") or [])
            stem = img_dir / build_fix_stem_name(fix_label, fix_parts, task_id, mid,
                                                 name_len, name_sep)
        else:
            stem = img_dir / build_stem_name(prompt, task_id, mid, name_len, name_sep)
        status, path = download(session, url, stem)
        if status not in ("ok", "skip") or not path:
            continue
        full = build_catalog_row(
            mid, fm=fm, known=known,   # fm spread: issue #18 + lineage
            task_id=str(task_id), seed=seed,
            filename=str(path.relative_to(out)).replace("\\", "/"),
            url=url, source="api", status="completed",
            created_at=_created_at_utc(result.get("createdAt")),
            prompt_full=prompt,        # prompt_preview derives from it
            # Everything extract_full_meta resolved from the task. This row used to write
            # only the model id, so a generation captured as it happened landed with an
            # em-dash for Steps, Sampler, CFG, LoRAs and the rest -- not because PixAI never
            # recorded them, but because they were never written down, and only a later
            # --backfill-full-meta filled them in. That backfill is the manual step
            # capturing-as-it-happens exists to remove.
            #
            # An em-dash remains the honest answer where the task genuinely recorded
            # nothing: a CHAT task (Edit/Fix) has no detailParameters at all, so these
            # resolve to "" and render as before. An explicit model_name from the caller
            # still wins over the looked-up one.
            model_id=fm.get("model_id", ""),
            model_name=model_name or _resolved_model_name(session, fm,
                                                          fm.get("model_id", "")),
            steps=fm.get("steps", ""),
            sampler=fm.get("sampler", ""),
            cfg_scale=fm.get("cfg_scale", ""),
            negative_prompt=fm.get("negative_prompt", ""),
            natural_prompt=fm.get("natural_prompt", ""),
            clip_skip=fm.get("clip_skip", ""),
            loras=_resolved_loras(session, result),
            paid_credit=_paid_credit_str(result),   # actual cost, task-level
            width=str((info or {}).get("width") or ""),
            height=str((info or {}).get("height") or ""))
        rows.append(full)
        make_thumbnail(path, thumb_dir / "{}.jpg".format(mid))
        saved.append(str(path))
    if rows:
        save_catalog_over_snapshot(db_path, rows, known)
    return saved




def _i2v_cli_unsent_notes(args):
    """The receipts for what --generate-video was asked for and does not send (the CLI's half
    of the receipts rule; build_request records the web road's). A Tsubaki engine has no
    negative prompt and no camera move (VIDEO_NO_NEGATIVE_MODELS / VIDEO_NO_CAMERA_MODELS --
    build_video_parameters drops both), and --video-ratio belongs to --reference-video.
    --params-json is sent exactly as given, so only the ratio note applies to it."""
    notes = []
    if (getattr(args, "video_ratio", "") or "").strip():
        notes.append("--video-ratio applies to --reference-video only (not sent).")
    if getattr(args, "params_json", ""):
        return notes
    model = str(getattr(args, "video_model", "") or getattr(args, "model", "")
                or _gen_params.DEFAULT_VIDEO_MODEL).strip()
    label = (_gen_params.VIDEO_MODELS.get(model) or {}).get("label") or model
    if (getattr(args, "negative", "") or "").strip() and model in _gen_params.VIDEO_NO_NEGATIVE_MODELS:
        notes.append("negative prompt not used by {} (not sent).".format(label))
    cam = (getattr(args, "camera_movement", "") or "").strip()
    if cam and cam != "unset" and model in _gen_params.VIDEO_NO_CAMERA_MODELS:
        notes.append("camera not used by {} (not sent).".format(label))
    return notes


def run_generate_video(args):
    """Create an image-to-video clip via PixAI (createGenerationTask + i2vPro params),
    poll to completion, download the mp4 into videos/, and catalog it (source='api',
    is_video='1'). GUARDED: without --confirm it only PREVIEWS (spends nothing). Video
    is expensive (~27.5k credits for a 5s V4.0 clip), so the preview shouts the cost.
    Reuses the same submit/poll as images and the same video download as --sync-videos."""
    from moonglade.backup import _check_read_only, init_db, _make_session, PixAIError
    out = Path(args.out)
    existing_task = (getattr(args, "task_id", "") or "").strip()
    if not existing_task and not (getattr(args, "image", "") or "").strip():
        raise PixAIError("--generate-video needs --image <media_id> (a catalog image to animate).")
    if not existing_task:
        # 3.22 S5: an SVG or a GIF is never a video frame -- before the preview or any send.
        _gen_params.refuse_unusable_sources(
            [getattr(args, "image", ""), getattr(args, "tail", "")], "video",
            _gen_params.catalog_source_format(out))
    params = _gen_params._gen_video_parameters(args)
    if not existing_task:
        _gen_params.check_params_retired(params)      # a raw --params-json skips the builder's check
    # 3.22 S3-video-wire (DESIGN_3.22 2.4 rule 2, V12): the road-aware wire step before the
    # preview and the card check. Video stays on GraphQL (owner, 2026-11-19), where it returns
    # the params unchanged, byte for byte.
    params = _gen_params.to_wire("video", params)

    if not existing_task and not getattr(args, "confirm", False):
        i2v = params.get("i2vPro") or {}
        print("=== PixAI createGenerationTask -- VIDEO (PREVIEW, no credits spent) ===")
        print(json.dumps({"parameters": params}, indent=2))
        print("\n*** VIDEO GENERATION IS EXPENSIVE ***")
        print("  model={}  mode={}  duration={}s{}{}".format(
            i2v.get("model"), i2v.get("mode"), i2v.get("duration"),
            "  +audio" if i2v.get("generateAudio") else "",
            "  (first/last-frame)" if i2v.get("tailMediaId") else ""))
        for n in _i2v_cli_unsent_notes(args):
            print("  note: " + n)
        # No hardcoded reference price here: the line below prints THIS clip's real cost from
        # /task-price (and the card verdict for it). A fixed "a 5s clip costs ~27,500" used to
        # sit right above the true "~82,500" for a 15s clip -- two numbers on one screen for
        # one spend (found running the preview live, 2026-08-16).
        print("  Re-run with --confirm to submit.")
        _cards._preview_card_note(args, params)
        return {"submitted": False}

    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    init_db(db_path)
    session = _make_session(getattr(args, "token", None))
    vdir = out / "videos"
    vdir.mkdir(parents=True, exist_ok=True)

    if existing_task:
        task_id = existing_task
        print("Fetching existing video task (no credits):", task_id)
    else:
        _check_read_only("submit a video generation (spends credits)")
        for n in _i2v_cli_unsent_notes(args):
            print("  note: " + n)
        print("Submitting VIDEO generation task (this spends credits)...")
        # V8 (DESIGN_3.22 2.5): the creating identity chosen ONCE, after READ_ONLY, for the
        # card check and the create; download below stays on the API-key `session` (F6).
        from moonglade import pixai_client as _pixai_client
        create_client = _pixai_client._client_of(session).for_create()
        _cards._apply_kaisuuken(create_client, params, args)
        # gql_mutate, never gql_adhoc: a re-POSTed createGenerationTask is a second
        # (expensive) video and a second charge -- see gql_mutate's docstring.
        task_id = _gen_road._cli_create_once(create_client, params)
        print("  task id:", task_id)
        _cards._bump_card_use(params)
        _task_reads._poll_task_status(session, task_id, getattr(args, "poll_timeout", 600),
                          interval=5, label="video", fail_noun="video generation",
                          card_sent=_card_sent(params))

    # Result: getTaskById -> outputs.videos -> fileUrl -> download mp4 (same as --sync-videos).
    result = _task_reads.task_detail_gql(session, task_id) or {}
    _maybe_dump_params(args, result)
    # A recovered task is filed from ITS OWN parameters, as collect_generation does. `params`
    # here was rebuilt from this run's CLI args (engine defaulting to v4.0.1), not read from
    # the task, so handing it over filed a recovered clip under another engine's model, and
    # its prompt / negative / duration fallbacks read the args too (review f-V-F1).
    saved = _download_video_task(session, result, task_id, out, args,
                                 (result.get("parameters") or {}) if existing_task else params)
    print("Generated + cataloged {} video(s):".format(len(saved)))
    for s in saved:
        print("  " + s)
    return {"submitted": True, "task_id": task_id, "videos": len(saved)}


def _resolve_refs(session, items, media_type="IMAGE"):
    """Resolve reference sources (media_id or local file) to media_ids, uploading any
    local files. Used by reference-video on --confirm.

    `media_type` is the PixAI MediaType to register an uploaded local file under.
    Live-probed 2026-07-24: MediaType is a real GraphQL enum with exactly two members,
    IMAGE and VIDEO. Pass media_type=None for a ref kind that has no valid upload type
    (audio) -- a local file is then refused rather than mislabelled as an image.
    Existing media_ids pass through untouched regardless."""
    from moonglade.backup import PixAIError, upload_media
    ids = []
    for s in items:
        if _gen_params._is_local_source(s):
            if media_type is None:
                raise PixAIError(
                    "--ref-audio only takes a media id that already exists on PixAI, not a "
                    "local file ({}). PixAI's uploader accepts images and videos only, so "
                    "there is no way to upload a bare audio file. Workaround: put the audio "
                    "into a video (even a still image with the audio track) and pass that "
                    "with --ref-video instead.".format(s))
            print("Uploading local reference:", s)
            ids.append(upload_media(session, s, media_type))
        else:
            ids.append(str(s))
    return ids


def run_reference_video(args):
    """Create a REFERENCE video (multi-image/video/audio reference) via createGenerationTask
    + a `referenceVideo` block. Refs (--ref-image/--ref-video/--ref-audio) are catalog
    media_ids OR local files (auto-uploaded on --confirm); reference them in --prompt as
    @image1/@video1/@audio1. Preview-only unless --confirm. Downloads + catalogs the mp4.
    --task-id recovers an existing reference-video task for free."""
    from moonglade.backup import _check_read_only, init_db, _make_session, PixAIError
    out = Path(args.out)
    existing_task = (getattr(args, "task_id", "") or "").strip()
    imgs = [s for s in (getattr(args, "ref_image", None) or []) if s and str(s).strip()]
    vids = [s for s in (getattr(args, "ref_video", None) or []) if s and str(s).strip()]
    auds = [s for s in (getattr(args, "ref_audio", None) or []) if s and str(s).strip()]
    override = getattr(args, "params_json", "") or ""
    prompt = getattr(args, "prompt", "") or ""

    if not existing_task and not (imgs or vids or auds) and not override:
        raise PixAIError("--reference-video needs at least one --ref-image/--ref-video/"
                         "--ref-audio (a media_id or local file), or --task-id to recover.")
    if not existing_task and override:
        _gen_params.check_params_retired(json.loads(override))   # sent as given: no builder checks it
    if not existing_task:
        # 3.22 S5: an SVG or a GIF is never a reference-video picture -- before any upload.
        _gen_params.refuse_unusable_sources(imgs, "video", _gen_params.catalog_source_format(out))

    is_private = (getattr(args, "vchannel", "private") == "private")
    vmodel = (getattr(args, "video_model", "") or "v4.0.1")
    ratio = (getattr(args, "video_ratio", "") or "").strip()
    if not existing_task and not override:
        # Before any upload: an engine that takes no video references refuses them here,
        # not after _resolve_refs has already uploaded the local files.
        _gen_params._check_video_ref_caps(vmodel, vids)

    # Each --ref-video's real length (SCOPE_2026-09-26 V5), read ONCE from the SOURCES --
    # a local file is measured directly, a media id through the same lookup the gallery's
    # quote and spend carry, against --out -- so the preview and the submit (whose ids are
    # upload ids by then) send the identical list. All or nothing, as on the web road.
    _lookup = [None]

    def _vid_len(src):
        if _gen_params._is_local_source(src):
            return _media_tools.duration(str(src))
        if _lookup[0] is None:
            _lookup[0] = _gen_params.make_video_duration_lookup(out)
        return _lookup[0](src)
    in_durs, in_unknown = _gen_params.input_video_durations(vids, _vid_len) if not override else ([], False)

    def _build(img_ids, vid_ids, aud_ids):
        # Duration: default 5 (matches the argparse flag + the i2v sibling -- was 15 here,
        # a real 3x cost divergence, B10), snapped to PixAI's allowed lengths before use
        # for either preview or submit, same as the i2v CLI path (B9). No model_id: the
        # builder sends THIS engine's own id (it used to send v4.0.1's for every engine).
        # 3.22 S3-video-wire: the road-aware wire step on every build, so the preview, the
        # card check and the send see one shape (GraphQL road: returned unchanged, byte for byte).
        return _gen_params.to_wire("refvideo", _gen_params.build_reference_video_parameters(
            prompt, image_media_ids=img_ids, video_media_ids=vid_ids, audio_media_ids=aud_ids,
            model=vmodel,
            duration=_gen_params._snap_video_duration(getattr(args, "duration", 5) or 5, vmodel),
            mode=getattr(args, "vmode", None) or "professional",
            generate_audio=bool(getattr(args, "audio", False)),
            audio_language=getattr(args, "audio_language", None) or "english",
            is_private=is_private, kaisuuken_id=getattr(args, "kaisuuken_id", "") or "",
            ratio=ratio, input_video_durations=in_durs))

    def _notes():
        if in_unknown:
            print("  note: " + _gen_params.INPUT_VIDEO_UNKNOWN_WHY + " (inputVideoDurations sent as []).")
        if ratio and vmodel not in _gen_params.VIDEO_RATIO_MODELS:
            print("  note: --video-ratio is only sent to the Tsubaki video engines ({}); "
                  "not sent for {}.".format(", ".join(_gen_params.VIDEO_RATIO_MODELS), vmodel))

    # PREVIEW: no upload, no submit. Local files shown as placeholders.
    if not existing_task and not getattr(args, "confirm", False):
        print("=== PixAI createGenerationTask -- REFERENCE VIDEO (PREVIEW, no credits spent) ===")
        if override:
            print(json.dumps({"parameters": json.loads(override)}, indent=2))
        else:
            ph = lambda lst: [("<upload:{}>".format(s) if _gen_params._is_local_source(s) else s) for s in lst]
            prev = _build(ph(imgs), ph(vids), ph(auds))
            print(json.dumps({"parameters": prev}, indent=2))
            _notes()
            _cards._preview_card_note(args, prev)
        print("\n*** REFERENCE VIDEO IS EXPENSIVE *** (a 15s clip uses 3 V4.0 cards). "
              "Re-run with --confirm to submit.")
        return {"submitted": False}

    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    init_db(db_path)
    session = _make_session(getattr(args, "token", None))

    params = {}
    if existing_task:
        task_id = existing_task
        print("Fetching existing reference-video task (no credits):", task_id)
    else:
        # Checked before _resolve_refs, not just before the mutation: _resolve_refs
        # uploads any local ref files (upload_media -> a real gql_adhoc mutation) before
        # this function ever reaches the createGenerationTask call.
        _check_read_only("submit a reference video generation (spends credits)")
        if override:
            params = _gen_params.to_wire("refvideo", json.loads(override))
        else:
            params = _build(_resolve_refs(session, imgs, "IMAGE"),
                            _resolve_refs(session, vids, "VIDEO"),
                            _resolve_refs(session, auds, None))
            _notes()
        print("Submitting REFERENCE VIDEO task (spends credits unless a free card applies)...")
        # V8 (DESIGN_3.22 2.5): the creating identity chosen ONCE, after READ_ONLY, for the
        # card check and the create; download stays on the API key (F6).
        from moonglade import pixai_client as _pixai_client
        create_client = _pixai_client._client_of(session).for_create()
        _cards._apply_kaisuuken(create_client, params, args)
        # gql_mutate, never gql_adhoc -- a re-POST here is a second charge.
        task_id = _gen_road._cli_create_once(create_client, params)
        print("  task id:", task_id)
        _cards._bump_card_use(params)
        _task_reads._poll_task_status(session, task_id, getattr(args, "poll_timeout", 600), interval=5,
                          label="reference video", fail_noun="reference video generation",
                          card_sent=_card_sent(params))

    result = _task_reads.task_detail_gql(session, task_id) or {}
    _maybe_dump_params(args, result)
    saved = _download_video_task(session, result, task_id, out, args, params)
    print("Generated + cataloged {} video(s):".format(len(saved)))
    for s in saved:
        print("  " + s)
    return {"submitted": True, "task_id": task_id, "videos": len(saved)}


def run_upload(args):
    """Upload a local image to PixAI and print its media_id (the reusable primitive
    behind --edit-src file support). Free; spends nothing."""
    from moonglade.backup import _make_session, upload_media
    session = _make_session(getattr(args, "token", None))
    mid = upload_media(session, args.upload_file)
    print("Uploaded media_id:", mid)
    return {"media_id": mid}


def _edit_preview_model_line(args, params, override):
    """The edit preview's first line: the model the shape names. With no --edit-model (and no
    --params-json) the default is used, so the line says that, with PixAI's read-only quote
    for this shape, or "couldn't verify the cost" when it cannot be read."""
    from moonglade.backup import _make_session
    chat = params.get("chat") if isinstance(params, dict) else None
    mid = str((chat or {}).get("modelId") or "") if isinstance(chat, dict) else ""
    label = (_gen_params.edit_model_by_id(mid) or {}).get("label") or "model {}".format(
        mid or "(none named)")
    if override or str(getattr(args, "edit_model", "") or "").strip():
        return "Edit model: {} ({}).".format(label, mid or "none named")
    try:
        from moonglade import pricing as _pricing
        price = _pricing.price_task(_make_session(getattr(args, "token", None)), params)
    except Exception:
        price = None
    cost = "~{:,} credits".format(price) if price is not None else "couldn't verify the cost"
    return "No --edit-model given: using {} ({}), {}.".format(label, mid, cost)


def run_edit_image(args):
    """Instruct-edit an image via PixAI (createGenerationTask with a `chat` block):
    describe the change in --prompt and pass source(s) via --edit-src (a catalog
    media_id OR a local file, uploaded automatically; repeatable for multi-image
    reference). Poll -> download the result image(s) -> catalog as source='api'.
    GUARDED: without --confirm it only PREVIEWS (uploads nothing, spends nothing).
    --task-id recovers an already-created edit for free. Mirrors run_generate."""
    from moonglade.backup import (_check_read_only, _edit_model_label, init_db, _make_session,
                                  PixAIError, save_catalog_over_snapshot, upload_media)
    from moonglade.full_meta import (build_catalog_row, _created_at_utc, extract_full_meta,
                                     _fill_preset_defaults, known_catalog_rows, _paid_credit_str)
    from moonglade.media_fetch import download, resolve_media
    from moonglade.history import build_stem_name
    out = Path(args.out)
    existing_task = (getattr(args, "task_id", "") or "").strip()
    srcs = [s for s in (getattr(args, "edit_src", None) or []) if s and str(s).strip()]
    override = getattr(args, "params_json", "") or ""
    prompt = getattr(args, "prompt", "") or ""
    cfg = _gen_params._edit_config_from_args(args)

    if not existing_task and not srcs and not override:
        raise PixAIError("--edit-image needs --edit-src <media_id|file> (repeatable), "
                         "or --task-id to recover an existing edit.")
    if not existing_task:
        # 3.22 S5: an SVG or a GIF is never an edit source (PixAI's rule) -- by the catalog
        # under --out, then the file's extension, before any preview, upload or send.
        fmt_of = _gen_params.catalog_source_format(out)
        _gen_params.refuse_unusable_sources(srcs, "edit", fmt_of)
        if override:
            _chat = json.loads(override).get("chat") or {}
            _gen_params.refuse_unusable_sources(
                list(_chat.get("mediaIds") or []) + [_chat.get("mediaId")], "edit", fmt_of)
    if not existing_task and override:
        _gen_params.check_params_retired(json.loads(override))   # sent as given: no builder checks it
        # Edit Pro's new outputs (3.22 S5): a hand-written shape meets the builder's rules on the
        # baked capability lists here, before anything is uploaded or sent; a --confirm run
        # checks again on the model's live record once it has a session.
        _gen_params.check_edit_outputs(json.loads(override))

    # PREVIEW: no upload, no submit, no credits. Local files shown as placeholders.
    if not existing_task and not getattr(args, "confirm", False):
        if override:
            params = json.loads(override)
        else:
            preview_ids = [("<upload:{}>".format(s) if _gen_params._is_local_source(s) else s)
                           for s in srcs] or ["<source>"]
            params = _gen_params.build_chat_edit_parameters(
                prompt, preview_ids, model_id=cfg["model_id"],
                resolution=cfg["resolution"], aspect_ratio=cfg["aspect_ratio"],
                quality=cfg["quality"], kaisuuken_id=cfg["kaisuuken_id"])
        # V12 (DESIGN_3.22 2.3): the wire step before the preview and the card check.
        params = _gen_params.to_wire("edit", params)
        _gen_params.preview_wire("edit", params)         # 3.22 review F10: as the door checks
        # 3.22 review: the first line names the model, and says so plainly (with its price)
        # when no --edit-model was given and the default -- the gallery Edit tab's, Edit Pro --
        # is the one this would send.
        print(_edit_preview_model_line(args, params, bool(override)))
        print("=== PixAI task.createTask, POST /v2/task/create -- EDIT (PREVIEW, no credits "
              "spent) ===")
        print(json.dumps({"parameters": params}, indent=2))
        _cards._preview_card_note(args, params)
        print("\nThis would SPEND PixAI credits (unless free above). "
              "Re-run with --confirm to submit.")
        return {"submitted": False}

    out.mkdir(parents=True, exist_ok=True)
    db_path = out / "catalog.db"
    init_db(db_path)
    session = _make_session(getattr(args, "token", None))
    thumb_dir = out / "gallery" / "thumbs"
    from moonglade.thumbs import make_thumbnail

    params = {}
    if existing_task:
        task_id = existing_task
        print("Fetching existing edit task (no credits):", task_id)
    else:
        # Checked before the upload loop, not just before the mutation -- see
        # run_reference_video.
        _check_read_only("submit an edit (spends credits unless a card applies)")
        if override:
            params = json.loads(override)
            chat = params.get("chat") if isinstance(params, dict) else None
            _gen_params.check_edit_outputs(params, _models.edit_output_caps_live(
                session, chat.get("modelId") if isinstance(chat, dict) else ""))
        else:
            media_ids = []
            for s in srcs:
                if _gen_params._is_local_source(s):
                    print("Uploading local image:", s)
                    media_ids.append(upload_media(session, s))
                else:
                    media_ids.append(str(s))
            params = _gen_params.build_chat_edit_parameters(
                prompt, media_ids, model_id=cfg["model_id"],
                resolution=cfg["resolution"], aspect_ratio=cfg["aspect_ratio"],
                quality=cfg["quality"], kaisuuken_id=cfg["kaisuuken_id"])
        print("Submitting EDIT task (spends credits unless a free card applies)...")
        # V12: the wire step before the card check, so the card is matched on the sent shape.
        params = _gen_params.to_wire("edit", params)
        # V8 (DESIGN_3.22 2.5): the creating identity chosen ONCE, after READ_ONLY; the card
        # check and the create door both ride it. Download stays on the API key (F6).
        from moonglade import pixai_client as _pixai_client
        create_client = _pixai_client._client_of(session).for_create()
        _cards._apply_kaisuuken(create_client, params, args)
        # THE create door (3.22 S3-edit): one POST, never retried, its unknown outcome said
        # plainly (SendOutcomeUnclear).
        task_id = _gen_road._cli_door_once(create_client, "edit", params)
        print("  task id:", task_id)
        _cards._bump_card_use(params)
        _task_reads._poll_task_status(session, task_id, getattr(args, "poll_timeout", 300),
                          interval=3, label="edit", fail_noun="edit",
                          card_sent=_card_sent(params))

    result = _task_reads.task_detail_gql(session, task_id) or {}
    _maybe_dump_params(args, result)
    outputs = result.get("outputs") or {}
    # Same fix as run_generate: outputs.batch[] holds the real individual images on
    # a batchSize>1 edit; outputs.mediaId alone is the composite grid.
    media = _task_image_media(outputs)
    seeds = dict(media)
    mids = [mid for mid, _ in media]
    _outputs_or_raise(result, mids, "edit task completed but no media ids found")

    fm = extract_full_meta(result)
    _fill_preset_defaults(session, fm, result)   # issue #18: model-preset steps/sampler/cfg
    chat = (params.get("chat") or {}) if isinstance(params, dict) else {}
    prompt_used = fm.get("prompt_full") or prompt or chat.get("prompts", "")
    # Resolved ONCE for the task, not per output image: the model is a property of the task,
    # and _resolved_model_name can reach the network for an edit model this app doesn't know
    # locally (model_name_gql is process-cached, so this is at most one call either way).
    edit_model_id_used = str(chat.get("modelId") or fm.get("model_id") or "")
    edit_model_name = _edit_model_label(session, fm, edit_model_id_used)
    img_dir = out / "images"
    rows, saved = [], []
    # See build_catalog_row step 3: an edit recovered by --edit-task-id can land on media
    # the user has already rated, filed or published.
    known = known_catalog_rows(db_path, mids)
    for mid in mids:
        url, info = resolve_media(session, mid)
        if not url:
            print("  no url for media", mid)
            continue
        stem = img_dir / build_stem_name(prompt_used, task_id, mid,
                                         getattr(args, "name_length", 60),
                                         getattr(args, "name_sep", "_"))
        status, path = download(session, url, stem)
        if status not in ("ok", "skip") or not path:
            continue
        full = build_catalog_row(
            mid, fm=fm, known=known,   # fm spread: issue #18 + lineage
            task_id=str(task_id), seed=seeds.get(mid, ""),
            filename=str(path.relative_to(out)).replace("\\", "/"),
            url=url, source="api", status="completed",
            created_at=_created_at_utc(result.get("createdAt")),
            prompt_full=prompt_used,   # prompt_preview derives from it
            model_id=edit_model_id_used,
            model_name=edit_model_name,
            paid_credit=_paid_credit_str(result),   # actual cost, task-level
            width=str((info or {}).get("width") or ""),
            height=str((info or {}).get("height") or ""))
        rows.append(full)
        make_thumbnail(path, thumb_dir / "{}.jpg".format(mid))
        saved.append(str(path))

    if rows:
        save_catalog_over_snapshot(db_path, rows, known)
    print("Edited + cataloged {} image(s):".format(len(saved)))
    for s in saved:
        print("  " + s)
    return {"submitted": True, "task_id": task_id, "images": len(saved)}
