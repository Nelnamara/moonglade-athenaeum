"""moonglade/routes_generate.py -- the gallery's create routes: the quote (/api/price), the
Generate drawer's sends (/api/generate, the run and its plan, /api/edit, /api/enhance, /api/scene,
/api/fix), the drawer's catalogs (palette and enhance presets, emotions, scenes, workflows), the task
poll (/api/task-status) and the job log (/api/jobs), with the spend state they share: the repeat-hold
wrappers over gen_road's record, the FREE-quote aliases, the free-card sent set, the run lock and the
pending enhance and scene telemetry.

Split out of gallery.create_app (split phase 4, 2026-11-20), verbatim: create_app calls
register(app, ctx) once. Names the block reads from code still inside create_app come in through
ctx (the bound-from-ctx lines below), and the names inline code reads back go out through ctx (the
provided-to-ctx lines at the end), so every closure on both sides holds the one same object.
gallery's own names are imported inside the function that reads them, at call time, so a test's
patch of moonglade.gallery still reaches the route.
"""
import re
import secrets
import threading
import time
from pathlib import Path

from flask import jsonify, request, session

from moonglade import account_prefs as _account_prefs
from moonglade import branding as _branding
from moonglade import cards as _cards
from moonglade import gen_cli as _gen_cli
from moonglade import gen_params as _gen_params
from moonglade import gen_road as _gen_road
from moonglade import jobs as _jobs
from moonglade import media_tools as _media_tools
from moonglade import mirror as _mirror
from moonglade import models as _models
from moonglade import pricing as _pricing
from moonglade import task_reads as _task_reads
from moonglade import telemetry as _telemetry
from moonglade import updater as _updater


def register(app, ctx):
    from moonglade.web_tiers import LOGIN, tier
    # -- bound from ctx (split_move) --
    _LOOM_ID_RE = ctx._LOOM_ID_RE
    _account_is_member = ctx._account_is_member
    _check_csrf = ctx._check_csrf
    _collect_single_flight = ctx._collect_single_flight
    _entitlements = ctx._entitlements
    _gen_session = ctx._gen_session
    _input_media_id = ctx._input_media_id
    _is_local_request = ctx._is_local_request
    _load_presets = ctx._load_presets
    _log_job = ctx._log_job
    _loom_complete_clip = ctx._loom_complete_clip
    _loom_journal_finish_task = ctx._loom_journal_finish_task
    _loom_send_note = ctx._loom_send_note
    _reconcile_orphan_jobs = ctx._reconcile_orphan_jobs
    _redact_host_paths = ctx._redact_host_paths
    _task_stream = ctx._task_stream
    db_path = ctx.db_path
    out_dir = ctx.out_dir
    # -- end --

    # Bridge/enhance telemetry is DEFERRED to terminal success (see /api/enhance and
    # /api/task-status): submit_generation returns at createGenerationTask ACCEPTANCE, before a
    # panelplugin job starts, and such a job can be accepted-then-reaped. So /api/enhance records
    # {task_id -> workflow identity submitted} here, and the poll's done-branch fires the three
    # producers exactly once and drops the entry. Process-lifetime, tiny, bounded by in-flight
    # enhance tasks (dropped on done OR failed). A lost entry on restart just skips one bump.
    _enhance_pending = {}
    _enhance_pending_lock = threading.Lock()

    # Scene (AI-Tools) telemetry is DEFERRED to terminal success exactly like enhance above
    # (a scene task on the API key is accepted-charged-then-reaped), so /api/scene records
    # {task_id -> scene_id} here and the poll's done-branch fires _fire_scene_telemetry once
    # and drops the entry. Process-lifetime, tiny, bounded by in-flight scene tasks.
    _scene_pending = {}
    _scene_pending_lock = threading.Lock()

    # The 6 Bridge-Enhance presets, mapped workflow_name -> preset key, computed once at
    # app-creation (core is imported per-handler, not module-wide, so alias it locally here).
    # _fire_enhance_telemetry uses this at TERMINAL success to record WHICH enhance tool was
    # exercised (enhance_tools) -- never at submit, so a reaped/failed enhance never counts. Only
    # the six known presets map; a non-preset enhance resolves to nothing and records no tool.
    from moonglade import backup as _mb_bridge
    _BRIDGE_PRESET_KEY_BY_NAME = {
        n: k for n, k in (
            (str(pp.get("workflow_name") or "").strip(), str(pp.get("key") or "").strip())
            for pp in getattr(_gen_params, "BRIDGE_ENHANCE_PRESETS", ()))
        if n and k}

    # --- the gallery's end of the one payload road ---------------------------------
    # core.build_request is the only place a PixAI `parameters` dict is built for the web
    # (see its section in moonglade/backup.py). These two supply the lookups it cannot do
    # on its own, and they differ in EXACTLY one field, deliberately: a quote never
    # resolves a source image.

    def _price_resolver(core, gsession):
        """For a QUOTE. Same model resolution and same per-account preset lookup as the
        submit, and NO media resolver: _input_media_id uploads, and /api/price fires on
        every keystroke in the drawer -- resolving here would upload the same file once
        per character. A quote needs the SHAPE, not an upload-kind id."""
        return _gen_road.RequestResolver(
            model_version=_gen_road.model_version_resolver(gsession),
            preset=lambda u, name: _load_presets(u).get(name),
            gate=_gen_road.gate_resolver(gsession),
            video_duration=_video_duration_lookup,
            unlimited=_gen_road.unlimited_resolver(gsession),
            features=_models.features_resolver(gsession),
            edit_caps=_models.edit_caps_resolver(gsession),
            source_format=_source_format_lookup)

    def _submit_resolver(core, gsession):
        """For a SPEND. The price resolver plus the input resolver: a catalog media_id is
        a generation OUTPUT, and PixAI refuses one as an input on the Edit and Fix paths
        (the Loom's video routes resolve their own frames -- see loom_generate). The gate,
        the video-length lookup and the Unlimited Mode check are the SAME ones the quote
        uses."""
        return _gen_road.RequestResolver(
            model_version=_gen_road.model_version_resolver(gsession),
            preset=lambda u, name: _load_presets(u).get(name),
            media_id=lambda v: _input_media_id(core, gsession, v),
            gate=_gen_road.gate_resolver(gsession),
            video_duration=_video_duration_lookup,
            unlimited=_gen_road.unlimited_resolver(gsession),
            features=_models.features_resolver(gsession),
            edit_caps=_models.edit_caps_resolver(gsession),
            source_format=_source_format_lookup)

    def _lane_job_running(core):
        """True while the app's own job log holds an Unlimited Mode task that has not
        finished. PixAI's site allows one lane task at a time; the log (not a drawer's React
        state -- two useGenerate hooks, lost on reload) is the one record that survives
        (SCOPE_2026-09-26_unlimited-mode §8.6). A lane task started on PixAI's own site is
        not in it; PixAI's refusal covers that case, and nothing is spent."""
        try:
            return any(j.get("lane") == _gen_road.UNLIMITED_LANE
                       and j.get("status") not in _jobs._JOBS_TERMINAL
                       for j in _jobs.read_jobs(out_dir))
        except Exception:
            return False

    def _source_format_lookup(value):
        """A create source's format, "svg" / "gif" / "" (RequestResolver.source_format, 3.22
        S5): a catalog id by its row's recorded output_format, then its file's extension;
        anything else (a data: picture, a name) by its own text. Local, no network."""
        from moonglade.gallery import get_row
        s = str(value or "").strip()
        row = None
        if s.isdigit():
            try:
                row = get_row(db_path, s)
            except Exception:                                # noqa: BLE001 -- no row
                row = None
        return _gen_params.source_format(s, row)

    _video_len_cache = []   # the one cached lookup for this app (built on first use)

    def _video_duration_lookup(media_id):
        """A reference video's real length in seconds, or None, for
        referenceVideo.inputVideoDurations (RequestResolver.video_duration): the local
        file's measured length (media_tools.duration on what _find_local_video_file's rule
        finds), else the catalog's video_duration, else None -- core.make_video_duration_lookup,
        the same helper the CLI's --reference-video uses against --out. A pure local read,
        cached per media id for this app's life: /api/price runs it on every keystroke, and
        the quote, the drawer's spend and the Loom's spend all read one cached answer."""
        from moonglade import backup as core
        if not _video_len_cache:
            _video_len_cache.append(_gen_params.make_video_duration_lookup(out_dir, db_path))
        return _video_len_cache[0](media_id)

    def _log_gen_failure(where, exc, params=None):
        """Record a failed spend attempt in the server log. Returns the redacted message so a
        caller can both log and return it in one line.

        This did not exist, and its absence is what made a 2026-07-26 video decline
        undiagnosable: the route handed the raw error to the browser, the browser's
        friendlyGenErr() replaced it with a guess ("PixAI's content filter blocked this"), and
        the actual text was written down nowhere. There was no way to tell a content block from
        a rejected parameter after the fact -- and those want opposite fixes, so the guess sent
        the owner off to rewrite a prompt that was fine.

        Logs the PARAMS too, because the shape is the diagnosis for this class of failure -- which
        model, which quality mode, what duration. No credential is involved: the API key travels
        in the session headers, never in `parameters`. Prompts do appear, which is correct -- a
        moderation decline is unreadable without the prompt -- and this log is local to the
        owner's own machine, the same file that already records every request.

        Never raises: a diagnostic that can break the error path it reports on is worse than
        no diagnostic."""
        msg = _redact_host_paths(str(exc))
        try:
            import json as _json
            import logging as _logging
            shape = ""
            if params:
                # A miswired caller that hands us a bare str/id instead of a params dict must
                # still LOG, not silently skip: dict("<a-string>") raises ValueError, which the
                # outer `except: pass` below would swallow -- taking the logging.error() with it,
                # since it sits after this block in the same try. That is exactly how the
                # /api/scene handler was blinded (adversarial review 2026-08-18). Coerce first so
                # the diagnostic this function exists to guarantee can never be killed by its arg.
                if not isinstance(params, dict):
                    params = {"value": params}
                # Truncate the PROMPT separately, then serialise. A flat [:700] on the whole
                # dict let a long prompt consume the entire budget and cut off isPrivate,
                # modelId, duration and mode -- the structural fields that ARE the diagnosis.
                # Hit immediately: the first real failure this logged (2026-07-26) lost exactly
                # those, and the shape had to be reconstructed from PixAI's site instead.
                slim = dict(params)
                for _blk in ("i2vPro", "referenceVideo"):
                    if isinstance(slim.get(_blk), dict):
                        inner = dict(slim[_blk])
                        for _k in ("prompts", "negativePrompts"):
                            if isinstance(inner.get(_k), str) and len(inner[_k]) > 120:
                                inner[_k] = inner[_k][:120] + "...<truncated {} chars>".format(
                                    len(slim[_blk][_k]) - 120)
                        slim[_blk] = inner
                for _k in ("prompts", "negativePrompts"):
                    if isinstance(slim.get(_k), str) and len(slim[_k]) > 120:
                        slim[_k] = slim[_k][:120] + "...<truncated>"
                shape = " params=" + _json.dumps(slim, ensure_ascii=False, default=str)[:900]
            _logging.getLogger(__name__).error(
                "%s failed: %s: %s%s", where, type(exc).__name__, msg[:400], shape)
        except Exception:
            pass
        return msg

    # THE SINGLE SENDS' HALF OF THE LOOM'S F13 GUARD (2026-11-18). A gallery send whose cost
    # badge said FREE carries `expect_free`. The card is matched again at send time
    # (_apply_kaisuuken), and if the card the quote found is gone by then -- used elsewhere,
    # expired, now short -- sending would charge a price nobody was shown, with only a server
    # console line to say so. So that case is refused before anything goes out, in words the
    # drawer shows. A send whose badge showed a PRICE carries nothing and goes out exactly as
    # before (issue #15: a card that covers only part still spends, the full price stated).
    # Since 3.22 (DESIGN_3.22 3.4) the rule itself lives in gen_road; these names call it.
    _QUOTED_FREE_GONE = _gen_road.QUOTED_FREE_GONE
    _pop_expect_free = _gen_road.pop_expect_free

    def _pop_loom_target(body):
        """The Loom's {board_id, card_id} on a send from one of its tabs (Image, Edit,
        Reference, Fix), popped so it never reaches the builder or PixAI. (board, card) or
        None; a card id that is not one is kept as "" (the board still owns the send)."""
        t = body.pop("loom_target", None) if isinstance(body, dict) else None
        if not isinstance(t, dict):
            return None
        b, c = str(t.get("board_id") or ""), str(t.get("card_id") or "")
        if not _LOOM_ID_RE.match(b):
            return None
        return (b, c if _LOOM_ID_RE.match(c) else "")

    def _record_loom_send(target, task_id, params, kind):
        """A Loom tab's send into its board's send record (the one source of the board's
        "spent" figure): the task, 0 when a free card was attached, else the catalog's charge
        once known. Fail-soft, and a no-op for any send that did not come from a board."""
        if not target or not task_id:
            return
        _loom_send_note(str(session.get("user") or ""), board=target[0], card=target[1],
                        task_id=str(task_id), submit_id=None, kind=kind,
                        cost=0 if (params or {}).get("kaisuukenId") else None)

    def _quoted_free_hooks(core, req, expect_free):
        """submit's before_send for a send quoted FREE: gen_road.quoted_free_hooks (3.22)."""
        return _gen_road.quoted_free_hooks(req, expect_free)

    # THE SINGLE SENDS' REPEAT HOLD (3.21.2, DESIGN_3.22 "Live in master today" L1 and 2.12).
    # Every single send -- /api/generate, /api/edit, /api/enhance, /api/scene, /api/fix and the
    # gallery's own Video tab on /api/loom/generate -- claims a record for (signed-in user, kind,
    # the request as sent) BEFORE anything goes out, and an identical send while it stands is
    # refused before any network call: a double tap, a second tab, a stale bundle or a client
    # retry after a lost answer must not pay twice. The record is KEPT when the send succeeded
    # (SEND_REPEAT_S, Fix's double-tap window since #93) or its outcome is unknown -- a
    # timeout, a dropped connection, a 5xx, a 408/499, a bare 4xx, an answer with no task id
    # (SEND_UNCLEAR_S, the design's 60 s): the retry it invites is exactly a second spend. It is
    # DROPPED only when the send is known to have cost nothing: never reached (refused here, or
    # by a read before it), or refused by PixAI in a way that proves no task exists
    # (core.send_outcome). The Loom's journalled render keeps its own journal and is not held
    # here; a run (/api/generate/run) has its own run id and states. Since 3.22 (DESIGN_3.22
    # 3.4) the record and its windows live in gen_road (repeat_claim / repeat_settle); these
    # closures turn its answer into the route's JSON and keep their wording.
    SEND_REPEAT_S = _gen_road.REPEAT_SENT_S
    SEND_UNCLEAR_S = _gen_road.REPEAT_UNCLEAR_S
    _UNCLEAR_SEND =("PixAI may have started this. It was not sent again; check the Activity "
                     "tray (or pixai.art) before sending it again.")
    _UNCLEAR_HELD = ("The last one may still be starting, so this was not sent. Check the "
                     "Activity tray (or pixai.art) before sending it again.")
    _REPEAT_HELD = ("The same request was asked for a few seconds ago; wait a moment before "
                    "sending it again.")
    def _send_key(kind, body):
        """(user, kind, the request as sent, canonical JSON): gen_road.repeat_key."""
        return _gen_road.repeat_key(session.get("user") or "", kind, body)

    def _send_claim(key, repeat_msg=None, claim=True):
        """The refusal (a JSON response) for a send that matches a standing record, or None
        -- with the record now claimed when `claim` (gen_road.repeat_claim). A route checks
        with claim=False before its first network call, and claims immediately before the
        send itself. Local, no network."""
        held = _gen_road.repeat_claim(key, claim=claim)
        if held is None:
            return None
        if held == "unclear":
            return jsonify({"error": _UNCLEAR_HELD, "state": "may_have_started",
                            "unclear": True, "held": True}), 409
        return jsonify({"error": repeat_msg or _REPEAT_HELD, "held": True}), 409

    def _send_settle(key, state):
        """Settle a claimed record by the send's state (gen_road.repeat_settle)."""
        _gen_road.repeat_settle(key, state)

    def _Reached():
        """This request thread's spend mark (core.spend_watch): `.v` turns True once the one
        spend request is reached. Observation only; nothing extra is passed to the send."""
        from moonglade import backup as core
        return _gen_road.spend_watch()

    def _send_failed(where, exc, reached, params, key, task_id=None):
        """A failed single send's answer. An unknown outcome is said plainly, with PixAI's own
        reason as `detail`, and held (SEND_UNCLEAR_S); anything else carries `state`
        (not_sent | refused), the record is dropped, and the caller's own refusal shape is
        returned as before. (response, msg, state): response is None unless the outcome is
        unknown -- or the send had already SUCCEEDED (`task_id`) and only the bookkeeping
        after it failed: then the failure is logged and the task id answered as the success
        it is, so the job is registered and the record stays "sent"."""
        from moonglade import backup as core
        if task_id:
            try:
                import logging as _logging
                _logging.getLogger(__name__).error(
                    "%s: task %s was created; recording it afterwards failed: %s: %s", where,
                    task_id, type(exc).__name__, _redact_host_paths(str(exc))[:300])
            except Exception:                                # noqa: BLE001
                pass
            return (jsonify({"task_id": task_id}), 200), "", "sent"
        msg = _log_gen_failure(where, exc, params)[:300]
        state = _gen_road.repeat_settle_failure(key, exc, reached)
        if state == "may_have_started":
            try:
                detail = _redact_host_paths(_gen_road.outcome_reason(exc))[:300]
            except Exception:                                # noqa: BLE001
                detail = msg
            return (jsonify({"error": _UNCLEAR_SEND, "detail": detail, "state": state,
                             "unclear": True}), 200), msg, state
        return None, msg, state

    @app.route("/api/price", methods=["POST"])
    @tier(LOGIN)
    def api_price():
        """Live cost + free-card check for the drawer's current settings (generate, edit,
        fix, video or an AI preset). Read-only (no spend). Login required (any session,
        local or LAN).

        This route and every create route build their shape through the SAME
        gen_road.build_request, so the badge quotes the request that will actually submit --
        it is not a second, price-flavoured road that happens to agree. /api/price is the
        one caller that does NOT pin a mode: it serves every road, so the payload's own
        `mode` picks one.

        The answer carries `adjusted` (SCOPE_2026-09-26) whenever the build rewrote the
        request -- a clamp, or the per-model gate's size snap / strip / context-image
        conversion -- so the badge says so BEFORE a spend, not only in /api/generate's
        response after it. The gate is _price_resolver's, the same one the submit uses."""
        try:
            user = str(session.get("user") or "")
            # NOT `core, session = _gen_session()` -- session is assigned that way further
            # down in this same function, which (Python whole-function scoping) makes the
            # bare name `session` local for the ENTIRE function, so the read above would
            # raise UnboundLocalError instead of reading Flask's session. gsession names
            # the PixAI API session distinctly, the same fix already applied in api_presets.
            core, gsession = _gen_session()
            body = request.get_json(silent=True) or {}
            try:
                req = _gen_road.build_request(body, user=user,
                                         is_member=_account_is_member(core, gsession),
                                         resolve=_price_resolver(core, gsession))
            except core.PixAIError as e:
                # A builder refusal (both upscale methods at once, an unknown video mode)
                # becomes the badge's own note, not a 500 and not a number.
                return jsonify({"cost": None, "free": False,
                                "note": _redact_host_paths(str(e))[:140]})
            # The card check reads under the identity the send will create on (the Mirror's
            # sign-in when it is on), so the badge and the send's card step agree (2026-11-18).
            # A Mirror that cannot be reached falls back to the API key: that send is refused
            # before anything goes out anyway, for the Mirror, not for a card.
            try:
                card_session = _card_session(core, gsession)
            except Exception:                              # noqa: BLE001
                card_session = gsession
            return jsonify(_gen_road.price(gsession, req, card_session=card_session))
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "cost": None, "free": False}), 200

    @app.route("/api/generate", methods=["POST"])
    @tier(LOGIN)
    def api_generate():
        """Submit a generation from the drawer, wait, and catalog it into THIS gallery's
        backup. Login required -- any session, local or LAN, deliberately: spending from a
        signed-in tablet is the point of the login. A matching free card is
        auto-applied unless no_card is set. Returns {task_id, media_ids, paid_credit}.

        The shape comes from core.build_request -- the same call /api/price makes -- and
        goes out through core.submit, which is where READ_ONLY and the free card are
        decided for every create route at once. What is left here is what only a route
        knows: the entitlement read, the LoRA cap, telemetry, and the clamp receipt."""
        held_key = None
        reached = _Reached()
        try:
            body = request.get_json(silent=True) or {}
            expect_free = _pop_expect_free(body)
            loom_target = _pop_loom_target(body)
            # 3.21.2 (L1): an identical send whose last one is still standing is refused
            # here, before the session is made or anything is read.
            send_key = _send_key("image", body)
            held = _send_claim(send_key, claim=False)
            if held:
                return held
            core, session = _gen_session()
            # Session M (BUILD-w5-m review F2): this route is a SINGLE send. More than one
            # generation goes through the confirm (/api/generate/plan -> /run), so a count
            # other than 1 is refused here -- never clamped -- whoever sent it (a stale
            # bundle, a hand-rolled POST). And a prompt in the template syntax is refused
            # too: sent from here its braces would reach PixAI literally, a different prompt
            # from the one the dock's expander sends for the same text. Both local, before
            # any network call. The Upscale road is exempt from the template check only: it
            # re-sends the source picture's own stored prompt, which is never a template.
            refusal = _single_send_refusal(body)
            if refusal:
                return jsonify({"error": refusal}), 400
            # Unlimited Mode (SCOPE_2026-09-26_unlimited-mode §8.6/§8.9): READ_ONLY refuses
            # FIRST, before the entitlement read and the gate's reads below, as run_generate
            # does -- then one lane task at a time, off the app's own job log.
            lane = _gen_road.asks_unlimited(body)
            if lane:
                core._check_read_only(_gen_road._SUBMIT_ACTION_DEFAULT)
                if _lane_job_running(core):
                    return jsonify({"error": _gen_road.UNLIMITED_BUSY}), 400
            # Members-only options are dropped for an account PixAI reports as non-member.
            # Handed to the builder (not decided inside it) so the CLI keeps its own path
            # and /api/price passes the identical flag -- the badge must quote the shape
            # that will actually submit.
            _ent = _entitlements(core, session)
            # mode="image" pins the road: `mode` in THIS payload is the inferenceProfile
            # quality setting ("auto"/"lite"/"pro"/...), not a road name, so an
            # unpinned {"mode": "I2V"} POST here would otherwise build and pay for a video.
            # `params` is bound for the failure log below, which reads it through
            # locals().get() -- see _log_gen_failure.
            req = _gen_road.build_request(body, mode="image", is_member=_ent["is_member"],
                                     resolve=_submit_resolver(core, session))
            params = req.parameters
            # Authoritative model resolution happened inside build_request (see
            # core.model_version_resolver): the client's version_id is honored only when
            # it names one of model_id's own real versions, else the newest, and it is
            # never submitted un-validated -- which is what originally stopped gens
            # landing as "Unknown model" + missing the feed.
            if not req.model_version_id:
                return jsonify({"error": "pick a model first"}), 400
            if not (body.get("prompt") or "").strip():
                return jsonify({"error": "enter a prompt"}), 400
            # The per-generation LoRA cap was CLIENT-ONLY until 2026-07-28: both the gallery
            # drawer and the Loom disable their own submit button over the cap, and nothing
            # checked it here -- so any path that is not one of those two buttons (a stale
            # page, the Loom before /api/account resolves, a hand-rolled POST) reached PixAI
            # and came back LORA_NUM_EXCEEDED / 40300027. Reproduced by the owner with six
            # LoRAs against a cap of three. Refuse rather than silently trim: dropping a LoRA
            # changes the picture he asked for, and a refusal costs nothing because no task
            # is created either way. Fails OPEN on an unknown cap.
            _cap = _ent["lora_cap"]
            if _cap is not None and len(req.lora_version_ids) > _cap:
                return jsonify({"error": "Your account allows {} LoRA{} per generation — "
                                         "remove {} to continue.".format(
                                             _cap, "" if _cap == 1 else "s",
                                             len(req.lora_version_ids) - _cap)}), 400
            held = _send_claim(send_key)
            if held:
                return held
            held_key = send_key
            task_id = _gen_road.submit(session, req,
                                  **_quoted_free_hooks(core, req, expect_free))["task_id"]
            _send_settle(held_key, "sent")
            _record_loom_send(loom_target, task_id, req.parameters, "image")
            if req.unlimited:
                # The lane mark on the job, written by the server rather than trusted from the
                # client's own registration, so the one-at-a-time rule above can read it.
                _log_job(task_id, status="running", type="generate", lane=_gen_road.UNLIMITED_LANE,
                         source="web")
            # Session M (NOTES 3/7): the single send's request as built and card-attached (the
            # card step writes kaisuukenId into req.parameters), so Inspect can show it. The
            # submit itself is called exactly as before. Fail-soft -- a record that cannot be
            # written never affects the spend.
            _record_single_send(body, task_id, req.parameters, req)
            # (No LoRA counters here since 2026-10-02: the three LoRA honors are counted from
            # the catalog rows this generation produces -- achievement_metrics.)
            out = {"task_id": task_id}
            if req.adjusted:
                # A clamp fired: this submit is NOT the one that was asked for, and the
                # caller has just been charged for it. Say so in the response rather than
                # letting the substitution pass unremarked -- the whole hazard M20's clamp
                # introduced is that it can quietly bill a different generation than the
                # one configured. Both kinds of caller can land here: a hand-rolled POST
                # (the finding's own threat model) and the drawer itself, whose steps/cfg
                # controls adopt a model's published `restrictions` verbatim and so can
                # legitimately offer a number this clamp then rewrites.
                out["adjusted"] = req.adjusted
            return jsonify(out)
        except Exception as e:
            unclear, msg, state = _send_failed("/api/generate", e, reached.v,
                                               locals().get("params"), held_key,
                                               task_id=locals().get("task_id"))
            if unclear:
                return unclear
            # Lane w2-recipes: PixAI's RECIPE_UNAVAILABLE / RECIPE_INCOMPATIBLE, structured
            # (which recipes, why, in plain words) so the dock can mark the chip. Nothing
            # was created; the raw text is in the log above. Only ever read once the outcome
            # is known to be a refusal (3.21.2: the words never decide the outcome).
            from moonglade import recipes as _recipes
            refusal = _recipes.refusal_from(e)
            if refusal:
                return jsonify({"error": refusal["copy"], "recipe_error": refusal,
                                "state": state}), 200
            return jsonify({"error": msg, "state": state}), 200

    # ---- Session M: runs -- every send of more than one generation -----------------------
    # The design, its guard order and the adversarial review it answers:
    # moonglade-internal/design/notes/generate-power-tools/BUILD-w5-m.md. The dock expands a
    # template only to draw it; the server re-parses, re-expands, re-counts, re-caps,
    # re-builds and re-quotes everything here and checks the confirm's acknowledgement
    # against that fresh plan. Sends go one at a time through core.send_run (the spend choke).
    _RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
    _run_lock = threading.Lock()
    # ONE run in flight for the whole install (review F10): every gallery login spends the
    # same PixAI wallet, free cards and Unlimited lane, so this is keyed on the install, not on
    # session["user"]. {run_id, account, done, total} while a run is planned or sent.
    _run_inflight = {}
    _SINGLE_COUNT_WORDS = "Send more than one through the confirm — nothing was sent."
    _TEMPLATE_WORDS = ("This prompt uses the template syntax ({a|b} or __list__) — "
                       "send it from the Generate dock, which expands it first. Nothing was "
                       "sent.")
    _RUN_PAYLOAD_DROP = ("csrf", "run_id", "ack", "var_mode", "run_seed")

    def _single_send_refusal(body):
        """Why /api/generate refuses this body (review F2), or None. Local, no network."""
        from moonglade import runs
        raw = body.get("count")
        if runs.strict_int(1 if raw is None else raw, 1, 1) is None:
            return _SINGLE_COUNT_WORDS
        upscale_road = bool(str(body.get("ref_media_id") or "").strip()) and any(
            body.get(k) not in (None, "", 0) for k in ("enlarge", "upscale"))
        if not upscale_road and runs.has_syntax(body.get("prompt") or ""):
            return _TEMPLATE_WORDS
        return None

    def _strip_request(params):
        from moonglade import runs
        if params is None:
            return None
        return runs.strip_secrets(params, redact=_redact_host_paths)

    def _record_single_send(body, task_id, sent, req):
        """A single send's record in the Runs store (NOTES 3/7): its exact request, for
        Inspect. Fail-soft: nothing here can touch the spend that already happened."""
        try:
            import uuid
            from moonglade import runs
            user = str(session.get("user") or "")
            if not user or not task_id:
                return
            store = runs.RunsStore(out_dir)
            rid = uuid.uuid4().hex
            prompt = str(body.get("prompt") or "")
            payload = {k: v for k, v in body.items() if k not in _RUN_PAYLOAD_DROP}
            if not store.reserve(rid, user, status="sent", mode="single", template=prompt,
                                 count=1, jobs_n=1, payload=payload,
                                 dock_seed=str(body.get("seed") or "")):
                return
            store.put_jobs(rid, [{
                "cell": 0, "task_id": str(task_id), "prompt": prompt, "vars": [],
                "seed": (sent or {}).get("seed"), "batch": 1,
                "no_card": int(bool(req.no_card)),
                "card": int(bool((sent or {}).get("kaisuukenId"))),
                "state": "sent", "request": _strip_request(sent)}])
        except Exception:                                    # noqa: BLE001
            pass

    class _RunRefused(Exception):
        """A run refused before anything was sent; str() is the plain sentence."""

        def __init__(self, msg, **extra):
            super().__init__(msg)
            self.extra = extra

    def _prompt_limit(model_type):
        """The prompt budget a model gives -- recipesCore.promptLimit's rule (the site's jr())."""
        return 10000 if re.fullmatch(r"(USER_)?(MM)?DIT26[AB]_MODEL",
                                     str(model_type or "")) else 4096

    def _cell_label(plan, job):
        if plan["mode"] not in ("random", "matrix"):
            return ""
        vals = " · ".join(v["value"] for v in job["vars"])
        return "Cell {} ({}): ".format(job["cell"] + 1, vals) if vals else \
            "Cell {}: ".format(job["cell"] + 1)

    def _card_session(core, gsession):
        """The identity the free-card check must read under: the one the create will use
        (review F14, _apply_kaisuuken's rule). Under READ_ONLY nothing can be sent, so the
        mirror session (whose read may refresh a token) is not reached for a quote."""
        if core.READ_ONLY or core._read_only_now():
            return gsession
        return _mirror._session_for_create(gsession)

    def _recipe_budget_check(core, gsession, built, plan):
        """Review F7: with recipes, a prompt a cell's value made too long would only be
        refused by PixAI at SEND, partway through a run. Every resolved prompt is checked
        against the recipes' own prompt length before anything goes out (the dock's rule,
        recipesCore.recipeFit, on the longest prompt). One read-only recipe lookup."""
        ids = (built[0]["req"].parameters or {}).get("recipeIds")
        if not ids:
            return
        from moonglade import recipes as rec
        try:
            cards = rec.batch(gsession, ids)
        except Exception:                                    # noqa: BLE001
            raise _RunRefused("Couldn't read the recipes' prompt length from PixAI, so "
                              "nothing was sent — try again in a moment.")
        add = sum(int(c.get("prompt_len") or 0) for c in cards)
        if not add:
            return
        try:
            feats = _models.features_resolver(gsession)(built[0]["req"].model_version_id)
        except Exception:                                    # noqa: BLE001
            feats = None
        limit = _prompt_limit((feats or {}).get("model_type"))
        for b in built:
            n = len(str((b["req"].parameters or {}).get("prompts") or "")) + add
            if n > limit:
                raise _RunRefused(_cell_label(plan, b["job"]) + "a recipe would make the "
                                  "prompt too long ({:,} / {:,}) — shorten the prompt."
                                  .format(n, limit))

    def _run_expand(body, user):
        """Step 5, local and without a network call: var_mode, count, the run seed, and the
        template expanded against the account's own lists (never lists from the request).
        Returns (plan, run_seed, dock_seed); raises _RunRefused."""
        from moonglade import runs
        vm = body.get("var_mode")
        if vm not in ("random", "matrix"):
            raise _RunRefused("Pick Random or Matrix for this run.")
        raw = body.get("count")
        count = runs.strict_int(1 if raw is None else raw, 1,
                                1 if vm == "matrix" else runs.MAX_COUNT)
        if count is None:
            raise _RunRefused("A matrix sends one image per cell." if vm == "matrix"
                              else "Pick 1 to 4 images.")
        # The run seed (review F13f): the dock's seed field when it holds digits, else the
        # dock's roll; a run seed that disagrees with a set seed field is refused.
        seed_raw = str(body.get("seed") if body.get("seed") is not None else "").strip()
        dock_seed = seed_raw if re.fullmatch(r"-?\d{1,12}", seed_raw) else ""
        rs_raw = body.get("run_seed")
        client_rs = None
        if rs_raw not in (None, ""):
            client_rs = runs.strict_int(rs_raw, 0, runs.RUN_SEED_MAX)
            if client_rs is None:
                raise _RunRefused("That run seed isn't one this app makes — reload the "
                                  "page and try again.")
        run_seed = None
        if dock_seed:
            n = int(dock_seed)
            if 0 <= n <= runs.RUN_SEED_MAX:
                run_seed = n
            if client_rs is not None and client_rs != run_seed:
                raise _RunRefused("The run seed doesn't match the seed field — nothing "
                                  "was sent.")
        else:
            run_seed = client_rs
        lists = runs.lists_from_prefs(_account_prefs.account_prefs_get(out_dir, user))
        plan = runs.plan_jobs(body.get("prompt") or "", lists, vm, count, run_seed)
        if plan.get("error"):
            raise _RunRefused(plan["error"])
        # Review N4: with the seed field set, every matrix cell carries that one seed, so two
        # cells that resolve to the same prompt are the same picture paid for twice.
        same = runs.same_prompt_cells(plan) if dock_seed else None
        if same:
            raise _RunRefused("Cells {} and {} would send the same prompt with the same seed "
                              "— that pays twice for one picture. Clear the seed or change a "
                              "value.".format(*same))
        if plan["mode"] == "random" and run_seed is None:
            if dock_seed:
                raise _RunRefused("A Random run's seed must be between 0 and "
                                  "{:,} — or leave the seed blank.".format(
                                      runs.RUN_SEED_MAX))
            raise _RunRefused("This run has no seed to draw from — reload the page and "
                              "try again.")
        return plan, run_seed, dock_seed

    def _run_plan(core, gsession, body, user, *, resolver, quote):
        """Steps 5-10's work, shared by /plan and /run: the expansion (above), the mode
        rules, entitlements, one build per job through THE ONE road, the per-route checks,
        the recipes' prompt budget, and -- with `quote` -- the price and the free cards.
        Raises _RunRefused; writes nothing."""
        from moonglade import runs
        from moonglade import recipes as rec
        plan, run_seed, dock_seed = _run_expand(body, user)
        # Settled 2: never a card on a queued matrix cell -- a matrix of 2+ cells. A one-cell
        # matrix is an ordinary single send and its card applies as for any single send
        # (review B1: forcing it there charged a send the dock's badge showed as free).
        no_card = runs.forces_no_card(plan)
        ent = _entitlements(core, gsession)
        rs = resolver(core, gsession)
        base = {k: v for k, v in body.items() if k not in _RUN_PAYLOAD_DROP}
        built = []
        for job in plan["jobs"]:
            jp = dict(base, prompt=job["prompt"], count=job["batch"])
            if job["seed"] is not None:
                jp["seed"] = job["seed"]
            if no_card:
                jp["no_card"] = True
            label = _cell_label(plan, job)
            try:
                req = _gen_road.build_request(jp, mode="image", is_member=ent["is_member"],
                                         resolve=rs)
            except core.PixAIError as e:
                refusal = rec.refusal_from(e)
                raise _RunRefused(label + (refusal["copy"] if refusal
                                           else _redact_host_paths(str(e))[:200]),
                                  **({"recipe_error": refusal} if refusal else {}))
            if not req.model_version_id:
                raise _RunRefused("pick a model first")
            if req.parameters is None:
                raise _RunRefused(label + (req.note or "nothing to send"))
            cap = ent["lora_cap"]
            if cap is not None and len(req.lora_version_ids) > cap:
                raise _RunRefused("Your account allows {} LoRA{} per generation — "
                                  "remove {} to continue.".format(
                                      cap, "" if cap == 1 else "s",
                                      len(req.lora_version_ids) - cap))
            # Review N1: the Turbo -> Low downgrade (priority_for_submit, once PixAI has said
            # this account can't use Turbo) is applied HERE, at build, so it is quoted and
            # digested; a run job's submit (exact=True) never applies it again, so what is
            # sent is what was quoted.
            req.parameters = _gen_road.priority_for_submit(req.parameters)
            built.append({"cell": job["cell"], "job": job, "req": req,
                          "no_card": True if no_card else None})
        if any(b["req"].unlimited for b in built) and len(built) > 1:
            raise _RunRefused("Unlimited Mode makes one picture at a time — switch it "
                              "off to send a run.")
        _recipe_budget_check(core, gsession, built, plan)
        out = {"mode": plan["mode"], "count": plan["images"], "jobs": len(built),
               "built": built, "plan": plan, "run_seed": run_seed, "dock_seed": dock_seed}
        adjusted = list(built[0]["req"].adjusted or [])
        if adjusted:
            out["adjusted"] = adjusted
        if not quote:
            return out
        # --- the quote (step 9): one price group, a read price, the free cards ---
        queries = []
        for b in built:
            q = _pricing._task_price_query(gsession, b["req"].parameters)
            if not q:
                raise _RunRefused(_cell_label(plan, b["job"]) + "this request can't be "
                                  "priced, so nothing was sent.")
            queries.append(runs.canonical(q))
        if len(set(queries)) > 1:
            raise _RunRefused("These cells don't all cost the same, so one confirm can't "
                              "describe them — nothing was sent.")
        first = built[0]["req"]
        card, card_note = None, None
        if first.unlimited:
            each, covered = 0, len(built)
            out["unlimited"] = True
        else:
            cost = _pricing.price_task(gsession, first.parameters)
            if cost is None:
                if first.parameters.get("recipeIds"):
                    v = rec.price_verdict(gsession, first.parameters, None) or {}
                    raise _RunRefused(v.get("note") or "couldn't verify the price with "
                                      "these recipes",
                                      **({"recipe_error": v["recipe_error"]}
                                         if v.get("recipe_error") else {}))
                raise _RunRefused("Couldn't read the price from PixAI, so nothing was sent "
                                  "— try again in a moment.")
            each = int(cost)
            covered = 0
            if no_card:
                card_note = "Free cards don’t cover queued matrix runs."
            elif not first.no_card:
                try:
                    best = _cards.match_kaisuuken(_card_session(core, gsession),
                                                first.parameters, enrich=True,
                                                raise_on_error=True)
                except Exception:                            # noqa: BLE001
                    raise _RunRefused("The free-card check didn't answer, so nothing was "
                                      "sent — try again in a moment.")
                if best:
                    need = max(1, int(best.get("consumeAmount") or 1))
                    held = best.get("total")
                    if _cards.card_covers(best):
                        if len(built) == 1 or held is None:
                            covered = 1
                        else:
                            covered = min(len(built), int(held) // need)
                    card = {"name": best.get("name") or "", "held": held, "needed": need,
                            "left_after": (int(held) - covered * need) if held is not None
                            else None,
                            "short": not _cards.card_covers(best)}
                    if covered and first.parameters.get("recipeIds"):
                        card_note = rec.CARD_NOTE
        out.update(each=each, covered=covered, total=each * (len(built) - covered),
                   card=card,
                   digest=runs.run_digest([(b["req"].parameters, b["no_card"]) for b in built],
                                          queries[0]))
        if card_note:
            out["card_note"] = card_note
        return out

    def _plan_public(core, planned, cells=False):
        """The plan as the dock reads it (no GenerationRequest objects)."""
        from moonglade import runs
        keys = ("mode", "count", "jobs", "each", "covered", "total", "card", "card_note",
                "unlimited", "digest", "adjusted")
        out = {k: planned[k] for k in keys if k in planned}
        out["read_only"] = bool(core.READ_ONLY or core._read_only_now())
        plan = planned["plan"]
        if plan.get("axes"):
            out["axes"] = plan["axes"]
        if planned.get("run_seed") is not None:
            out["run_seed"] = planned["run_seed"]
        if cells:
            out["cells"] = []
            for b in planned["built"]:
                req = _strip_request(b["req"].parameters)
                out["cells"].append({
                    "cell": b["cell"], "prompt": b["job"]["prompt"], "vars": b["job"]["vars"],
                    "seed": b["req"].parameters.get("seed"), "count": b["job"]["batch"],
                    "no_card": bool(b["no_card"]),
                    "request": _gen_road.request_record("image", req),
                    "cli": runs.cli_command(core, req, no_card=bool(b["no_card"]))})
        return out

    @app.route("/api/generate/plan", methods=["POST"])
    @tier(LOGIN)
    def api_generate_plan():
        """The confirm's numbers (BUILD-w5-m s3.1): count, total credits, the free cards that
        cover it, each job's request and command line. READ-ONLY: it writes nothing -- no
        Runs store row, no job event, no prefs -- and its only PixAI calls are the reads
        /api/price already makes (plus a recipe lookup when recipes ride along). No READ_ONLY
        refusal (a quote spends nothing); the answer says `read_only` so the confirm can."""
        user = str(session.get("user") or "")
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "Expected a JSON object."}), 400
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 403
        try:
            core, gsession = _gen_session()
            planned = _run_plan(core, gsession, body, user, resolver=_price_resolver,
                                quote=True)
            return jsonify(_plan_public(core, planned, cells=True))
        except _RunRefused as e:
            return jsonify(dict({"error": str(e)}, **e.extra)), 200
        except Exception as e:                               # noqa: BLE001
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200

    def _run_refused(store, run_id, msg, **extra):
        try:
            store.update_run(run_id, status="refused", reason=str(msg)[:300])
        except Exception:                                    # noqa: BLE001
            pass
        return jsonify(dict({"error": str(msg), "run_id": run_id, "status": "refused"},
                            **extra)), 200

    @app.route("/api/generate/run", methods=["POST"])
    @tier(LOGIN)
    def api_generate_run():
        """Send a run (BUILD-w5-m s3.2-s4). The guard order, exactly: LOGIN -> CSRF ->
        READ_ONLY (before ANY PixAI read) -> local refusals and the reservation of run_id
        under one lock (a run_id already seen answers with that run, never a second send;
        another run in flight anywhere on this install is refused) -> parse, expand, count,
        cap -> the mode rules -> entitlements -> one build per job -> the quote -> the
        acknowledgement against that fresh quote -> every job row written -> the sends, one
        at a time, the first failure stopping the rest. A count of 1 needs no
        acknowledgement: it is a single send (no quote, the card auto-applies, review F11)."""
        from moonglade import runs
        user = str(session.get("user") or "")
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({"error": "Expected a JSON object."}), 400
        if not _check_csrf(body):
            return jsonify({"error": "Your session expired. Reload the page and try again."}), 403
        # A single send through this road (a template prompt) carries what its badge showed,
        # as /api/generate does (2026-11-18): popped here, before anything reads the body.
        expect_free = _pop_expect_free(body)
        loom_target = _pop_loom_target(body)
        from moonglade import backup as core
        try:
            core._check_read_only(_gen_road._SUBMIT_ACTION_DEFAULT)
        except core.PixAIError as e:
            return jsonify({"error": str(e), "read_only": True}), 200
        run_id = str(body.get("run_id") or "")
        if not _RUN_ID_RE.match(run_id):
            return jsonify({"error": "This run has no id — reload the page and try "
                                     "again. Nothing was sent."}), 400
        store = runs.RunsStore(out_dir)
        with _run_lock:
            try:
                existing = store.get(run_id)
            except Exception:                                # noqa: BLE001
                # Review N7: a store that can't be read is not "no such run" -- the run id
                # might be one already sent, so nothing goes out.
                return jsonify({"error": "Couldn't read the run store, so nothing was "
                                         "sent."}), 200
            if existing is not None:
                if existing.get("account") != user:
                    return jsonify({"error": "That run id is taken — nothing was "
                                             "sent."}), 200
                live = _run_inflight.get("run_id") == run_id
                return jsonify(dict(runs.run_view(existing, live=live), replay=True)), 200
            if _run_inflight:
                return jsonify({"error": "A run is still being sent ({} of {}) — wait "
                                         "for it to finish.".format(
                                             _run_inflight.get("done", 0),
                                             _run_inflight.get("total") or "?")}), 200
            try:
                ok = store.reserve(run_id, user, status="planning",
                                   template=str(body.get("prompt") or ""),
                                   var_mode=str(body.get("var_mode") or ""),
                                   dock_seed=str(body.get("seed") or ""),
                                   payload={k: v for k, v in body.items()
                                            if k not in _RUN_PAYLOAD_DROP})
            except Exception:                                # noqa: BLE001
                ok = None
            if ok is None:
                return jsonify({"error": "Couldn't record the run, so nothing was sent."}), 200
            if not ok:
                return jsonify({"error": "That run id is taken — nothing was sent."}), 200
            _run_inflight.update(run_id=run_id, account=user, done=0, total=0)
        try:
            return _run_send(core, store, run_id, body, user, expect_free=expect_free,
                             loom_target=loom_target)
        finally:
            with _run_lock:
                _run_inflight.clear()

    def _run_send(core, store, run_id, body, user, expect_free=False, loom_target=None):
        from moonglade import runs
        try:
            # Step 5, local: expand and count before any network call.
            plan, _rs, _ds = _run_expand(body, user)
            multi = plan["images"] > 1
            ack = body.get("ack")
            if multi and not isinstance(ack, dict):
                raise _RunRefused("Confirm the {} generations first — nothing was sent."
                                  .format(plan["images"]))
            # Review N6: the acknowledgement's count and jobs against this local expansion,
            # right here -- before the entitlement read, the builds and the quote (all checked
            # again, with every other field, at step 10).
            bad = runs.ack_count_problem(ack, plan) if multi else None
            if bad:
                raise _RunRefused("What would be sent changed since you confirmed — nothing "
                                  "was sent.", changed=bad)
            # Step 6, the lane rule read off the app's own job log: one lane task at a time.
            if _gen_road.asks_unlimited(body) and _lane_job_running(core):
                raise _RunRefused(_gen_road.UNLIMITED_BUSY)
            # Steps 7-9: entitlements, one build per job, the quote (a single send has none).
            gcore, gsession = _gen_session()
            planned = _run_plan(gcore, gsession, body, user, resolver=_submit_resolver,
                                quote=multi)
            if multi:
                # Step 10: the acknowledgement against the FRESH plan, field by field.
                bad = runs.ack_problem(ack, planned)
                if bad:
                    words = ("The price moved since you confirmed — nothing was sent."
                             if bad in ("each", "covered", "total") else
                             "What would be sent changed since you confirmed — nothing "
                             "was sent.")
                    raise _RunRefused(words, plan=_plan_public(core, planned),
                                      changed=bad)
        except _RunRefused as e:
            return _run_refused(store, run_id, str(e), **e.extra)
        except Exception as e:                               # noqa: BLE001
            return _run_refused(store, run_id, _redact_host_paths(str(e))[:200])
        built = planned["built"]
        mode = planned["mode"]
        each = planned.get("each")
        covered = planned.get("covered") or 0
        jobs_rows = []
        for i, b in enumerate(built):
            if not multi:
                expected = None
            elif b["no_card"]:
                expected = each
            else:
                expected = 0 if i < covered else each
            b["expected"] = expected
            jobs_rows.append({"cell": b["cell"], "prompt": b["job"]["prompt"],
                              "vars": b["job"]["vars"],
                              "seed": b["req"].parameters.get("seed"),
                              "batch": b["job"]["batch"], "no_card": int(bool(b["no_card"])),
                              "expected": expected, "state": "pending"})
        try:
            store.put_jobs(run_id, jobs_rows)
            store.update_run(run_id, status="sending", mode=mode, count=planned["count"],
                             jobs_n=len(built), run_seed=planned.get("run_seed"),
                             axes=planned["plan"].get("axes"), each_cost=each,
                             covered=covered, ack_total=planned.get("total"))
        except Exception:                                    # noqa: BLE001
            return _run_refused(store, run_id, "Couldn't record the run's jobs, so nothing "
                                               "was sent.")
        with _run_lock:
            _run_inflight["total"] = len(built)
        by_cell = {b["cell"]: b for b in built}
        label_kind = {"matrix": "Matrix", "random": "Random", "batch": "Batch",
                      "single": "Run"}.get(mode, "Run")

        class _Hooks(object):
            def sending(self, cell):
                store.set_job(run_id, cell, state="sending")

            def sent(self, cell, task_id, request_, card, card_unused=False):
                b = by_cell[cell]
                with _run_lock:
                    _run_inflight["done"] = _run_inflight.get("done", 0) + 1
                # The job event first: the Activity tray and the reel see every task even if
                # the store write below fails or the tab closed (review F5). `card_unused`
                # (2.4 rule 7): the create answer already showed a charge on a card job.
                _log_job(task_id, status="running", type="generate",
                         label="{} {}/{}".format(label_kind, cell + 1, len(built))
                         if len(built) > 1 else "Generated",
                         count=b["job"]["batch"], run=run_id, cell=cell, run_mode=mode,
                         lane=_gen_road.UNLIMITED_LANE if b["req"].unlimited else None,
                         source="web", card_unused=True if card_unused else None)
                store.set_job(run_id, cell, state="sent", task_id=task_id,
                              request=_strip_request(request_), card=int(bool(card)))
                # A run sent from a Loom board is that board's spend, job by job.
                _record_loom_send(loom_target, task_id,
                                  {"kaisuukenId": "card"} if card else {}, "image")

            def failed(self, cell, state, error, request_):
                store.set_job(run_id, cell, state=state, error=error,
                              request=_strip_request(request_))

            def card_unused(self, cell, task_id):
                # 2.4 rule 7: the card job's terminal read showed a charge. The Activity row's
                # data (the job event); the store's row reads it from card + paid (job_view).
                _log_job(task_id, card_unused=True)

        budget = {"each": each, "total": planned["total"]} if multi else None
        if not multi and expect_free and built and not built[0]["req"].unlimited:
            # A single send its badge called FREE: a confirmed total of 0, so the job is refused
            # before its create if the card step attaches no card -- in a single send's words.
            budget = {"each": 1, "total": 0, "note": _QUOTED_FREE_GONE}
        res = _gen_road.send_run(gsession, [{"cell": b["cell"], "req": b["req"],
                                        "no_card": b["no_card"]} for b in built],
                            hooks=_Hooks(), budget=budget)
        for j in res["jobs"]:
            if j["state"] == "not_sent":
                try:
                    store.set_job(run_id, j["cell"], state="not_sent")
                except Exception:                            # noqa: BLE001
                    pass
        try:
            store.update_run(run_id, status=res["status"], reason=res.get("reason"))
        except Exception:                                    # noqa: BLE001
            pass
        for j in res["jobs"]:
            b = by_cell.get(j["cell"])
            if b is not None:
                j["prompt"] = b["job"]["prompt"]
                j["vars"] = b["job"]["vars"]
                if b.get("expected") is not None:
                    j["expected"] = b["expected"]
        out = {"run_id": run_id, "status": res["status"], "mode": mode,
               "count": planned["count"], "jobs": res["jobs"],
               "sent": sum(1 for j in res["jobs"] if j["state"] == "sent"),
               "not_sent": sum(1 for j in res["jobs"] if j["state"] == "not_sent")}
        if res.get("reason"):
            out["reason"] = res["reason"]
        if planned["plan"].get("axes"):
            out["axes"] = planned["plan"]["axes"]
        if planned.get("adjusted"):
            out["adjusted"] = planned["adjusted"]
        return jsonify(out), 200

    @app.route("/api/generate/runs/<run_id>")
    @tier(LOGIN)
    def api_generate_run_get(run_id):
        """A run's recorded state, for the dock whose POST answer was lost (review F4): 404
        while this server has not received it (or it is another account's), else the run --
        'planning' / 'sending' while it goes, then sent / stopped / refused."""
        from moonglade import runs
        user = str(session.get("user") or "")
        rid = str(run_id or "")
        if not _RUN_ID_RE.match(rid):
            return jsonify({"error": "not found"}), 404
        try:
            run = runs.RunsStore(out_dir).get(rid)
        except runs.RunsUnreadable:
            # Review N7: unreadable is not "not found" -- the dock's read-back counts this
            # toward its lost window, never as "not received yet".
            return jsonify({"error": runs.RUN_UNREADABLE_WORDS}), 503
        if run is None or run.get("account") != user:
            return jsonify({"error": "not found"}), 404
        live = _run_inflight.get("run_id") == rid
        return jsonify(runs.run_view(run, live=live))

    @app.route("/api/generate/request/<task_id>")
    @tier(LOGIN)
    def api_generate_request(task_id):
        """Inspect (NOTES 7): the exact request a task was sent with, secrets stripped, with
        its template, its drawn values and its command line. The Runs store's record when the
        caller's own account made it; for a task this library holds with no record anywhere,
        PixAI's stored task (source "pixai"). Another account's record is never served, and
        never falls back to PixAI either (review F9). Writes nothing."""
        from moonglade.gallery import get_row_by_task
        from moonglade import runs
        user = str(session.get("user") or "")
        tid = str(task_id or "").strip()
        if not tid.isdigit():
            return jsonify({"error": "not found"}), 404
        try:
            found = runs.RunsStore(out_dir).find_task(tid)
        except runs.RunsUnreadable:
            # Review N7: the record may be another account's; with the store unreadable,
            # nothing is served and PixAI is not asked (review F9).
            return jsonify({"error": runs.RUN_UNREADABLE_WORDS}), 503
        from moonglade import backup as core
        if found is not None:
            run, job = found
            if run.get("account") != user:
                return jsonify({"error": "not found"}), 404
            params = job.get("request")
            out = {"source": "local", "task_id": tid, "run_id": run.get("run_id"),
                   "mode": run.get("mode"), "cell": job.get("cell"),
                   "template": run.get("template") or "", "vars": job.get("vars") or [],
                   "prompt": job.get("prompt") or "", "state": job.get("state")}
            if isinstance(params, dict):
                out["request"] = _gen_road.request_record("image", params)
                out["cli"] = runs.cli_command(core, params, no_card=bool(job.get("no_card")))
            return jsonify(out)
        if not get_row_by_task(db_path, tid):
            return jsonify({"error": "not found"}), 404
        try:
            core, gsession = _gen_session()
            task = _task_reads.task_detail_gql(gsession, tid, retries=1)
        except Exception as e:                               # noqa: BLE001
            return jsonify({"error": _redact_host_paths(str(e))[:200]}), 200
        if not task:
            return jsonify({"error": "couldn't read the task from PixAI"}), 200
        params = _strip_request(task.get("parameters") or {})
        return jsonify({"source": "pixai", "task_id": tid,
                        "request": _gen_road.request_record(
                            "edit" if "chat" in params else "video" if (
                                "i2vPro" in params or "referenceVideo" in params) else "image",
                            params),
                        "cli": runs.cli_command(core, params)})

    def _run_note_paid(tid, paid):
        """Review F14: a run job's charged credits beside what the confirm expected. Returns
        the expected figure (None when it is not a run job with one). Fail-soft."""
        try:
            from moonglade import runs
            store = runs.RunsStore(out_dir)
            found = store.find_task(tid)
            if not found:
                return None
            run, job = found
            if paid is not None:
                store.set_job(run["run_id"], job["cell"], paid=int(paid))
            return job.get("expected")
        except Exception:                                    # noqa: BLE001
            return None

    # Task ids sent with a free card on a road the Runs store does not record (an edit, a Loom
    # send). The store's own `card` column covers /api/generate's single sends and every run.
    # For the others the note is the task's own job event (`card_sent`), written by the server
    # at the send the way the Unlimited lane mark is, so it survives a server restart (3.22
    # review F2 follow-up); the set is this process's copy of it. Read by the terminal check.
    _card_sent_tasks = set()

    def _note_card_sent(task_id, params):
        if task_id and isinstance(params, dict) and params.get("kaisuukenId"):
            _card_sent_tasks.add(str(task_id))
            _log_job(str(task_id), status="running", type="generate", card_sent=True,
                     source="web")

    def _card_was_sent(tid):
        """True when the send behind task `tid` carried a free card (2.4 rule 7): this
        process's note, the task's job event (`card_sent`, written at the send), else the Runs
        store's row. Fail-soft: unknown is False."""
        if str(tid) in _card_sent_tasks:
            return True
        try:
            jobs_by_id, _order, _n = _jobs._reconstruct_jobs(out_dir)
            if (jobs_by_id.get(str(tid)) or {}).get("card_sent"):
                return True
        except Exception:                                    # noqa: BLE001
            pass
        try:
            from moonglade import runs
            found = runs.RunsStore(out_dir).find_task(tid)
            return bool(found and found[1].get("card"))
        except Exception:                                    # noqa: BLE001
            return False

    @app.route("/api/edit", methods=["POST"])
    @tier(LOGIN)
    def api_edit():
        """Instruct-edit an existing gallery image ('make it night'). Login required;
        auto-applies an Edit-Pro card unless no_card. Catalogs the result into this
        backup, same as /api/generate. Returns {task_id, media_ids, paid_credit}.

        Same road as the badge: core.build_request builds the `chat` shape /api/price
        quoted, core.submit is the one READ_ONLY + free-card choke."""
        held_key = None
        reached = _Reached()
        try:
            user = str(session.get("user") or "")
            p = request.get_json(silent=True) or {}
            expect_free = _pop_expect_free(p)
            loom_target = _pop_loom_target(p)
            send_key = _send_key("edit", p)
            held = _send_claim(send_key, claim=False)        # 3.21.2 (L1): before any network
            if held:
                return held
            # gsession, not `core, session = _gen_session()` -- see api_price's identical
            # comment: session is Flask's, reassigning it here would make every reference
            # to the bare name `session` in this function a local (UnboundLocalError on
            # the read above), not a read of Flask's session.
            core, gsession = _gen_session()
            req = _gen_road.build_request(p, mode="edit", user=user,
                                     resolve=_submit_resolver(core, gsession))
            params = req.parameters          # bound for _log_gen_failure's locals().get()
            if params is None:
                return jsonify({"error": "pick an image to edit (and a valid preset if set)"}), 400
            if not (p.get("preset") or "").strip() and not (p.get("instruction") or "").strip():
                return jsonify({"error": "describe the edit"}), 400
            held = _send_claim(send_key)
            if held:
                return held
            held_key = send_key
            task_id = _gen_road.submit(gsession, req,
                                  **_quoted_free_hooks(core, req, expect_free))["task_id"]
            _send_settle(held_key, "sent")
            _note_card_sent(task_id, req.parameters)         # 2.4 rule 7's terminal check
            _record_loom_send(loom_target, task_id, req.parameters, "edit")
            # (edits is counted from the catalog's edit rows since 2026-10-02.)
            _telemetry.telem_set_add("tools", "edit", out_dir=out_dir)
            return jsonify({"task_id": task_id})
        except Exception as e:
            unclear, msg, state = _send_failed("/api/edit", e, reached.v,
                                               locals().get("params"), held_key,
                                               task_id=locals().get("task_id"))
            return unclear or (jsonify({"error": msg, "state": state}), 200)

    # PixAI's official colour palettes change rarely (26 on 2026-09-26); one read an hour is
    # plenty, and a failed read is not cached so the next open tries again.
    _pal_presets_cache = {"at": 0.0, "palettes": None}
    _PAL_PRESETS_TTL = 3600.0

    @app.route("/api/palettes/presets")
    @tier(LOGIN)
    def api_palette_presets():
        """The Generate drawer's colour palette Library tab: PixAI's official palettes
        (core.color_palette_presets -> GET /v2/color-palettes/presets), READ-ONLY, spends
        nothing. LOGIN tier like every other drawer read. Each cover goes through this app's
        own CDN proxy (/api/pixai-cdn/thumb, SSRF-guarded to images-ng.pixai.art), because the
        browser cannot load PixAI's CDN cross-origin from here; any other host gets no cover.
        Fails soft: {"palettes": [], "error"} on a failed read, and the Library says so."""
        import urllib.parse as _up
        now = time.time()
        cached = _pal_presets_cache["palettes"]
        if cached is not None and (now - _pal_presets_cache["at"]) < _PAL_PRESETS_TTL:
            return jsonify({"palettes": cached})
        try:
            core, gsession = _gen_session()
            rows = _gen_params.color_palette_presets(gsession)
        except Exception as e:
            return jsonify({"palettes": [], "error": _redact_host_paths(str(e))[:200]})
        for r in rows:
            cover = r.get("cover_url") or ""
            try:
                ok = _up.urlparse(cover).scheme == "https" and \
                    _up.urlparse(cover).netloc == "images-ng.pixai.art"
            except ValueError:
                ok = False
            r["cover_url"] = ("/api/pixai-cdn/thumb?u=" + _up.quote(cover, safe="")) if ok else ""
        _pal_presets_cache["palettes"] = rows
        _pal_presets_cache["at"] = now
        return jsonify({"palettes": rows})

    # Process cache for the Bridge preset prices: they are flat per workflow and account-
    # stable (source- AND priority-independent, verified live 2026-08-18), so a slab mount
    # need not be a dozen live REST calls. Only a REAL (mirror-reached) result is cached; a
    # null-priced result is not, so it retries once the mirror is back. TTL in seconds.
    _enh_price_cache = {"at": 0.0, "presets": None, "gen": 0}
    _ENH_PRICE_TTL = 3600.0

    @app.route("/api/enhance/presets")
    @tier(LOGIN)
    def api_enhance_presets():
        """The six Bridge Enhance presets + LIVE per-preset cost (price + free-card), so the
        drawer's cost chips are honest rather than baked (the same 'fetch, don't bake' rule Fix
        follows). Cost comes from PixAI's own /v2/task-price + /v2/kaisuuken/check through the
        MIRROR session -- the identity that actually runs an enhance -- priced against a
        PLACEHOLDER media id (task-price prices the request SHAPE, not a specific owned image;
        verified 2026-08-18). No free card covers any panelplugin task on this account, so
        free_card comes back False across the board unless PixAI ever adds such a card, in which
        case this reports it truthfully. Fails soft: price=null when the mirror can't be reached
        (the slab only renders armed, but a price probe must never 500). LOGIN tier; read-only,
        spends nothing."""
        from moonglade import backup as core
        now = time.time()
        cached = _enh_price_cache["presets"]
        if cached is not None and (now - _enh_price_cache["at"]) < _ENH_PRICE_TTL:
            return jsonify({"presets": cached})
        # The cache's generation when this read began: a send or refusal that lands while it
        # runs bumps it, and this read's (older) answer is then never cached.
        gen0 = _enh_price_cache["gen"]
        # 3.22 S3-enhance (T-F4, V9): the Mirror's STORED sign-in, only while the Mirror is ON
        # (pricing.enhance_quote_session: never make_mirror_session, so a quote renews
        # nothing, #71), and PixAI's own enhance quote, POST /v2/task/enhance/price -- the
        # same price the badge reads. An enhance never takes a card: no card check runs and
        # free_card is always False.
        s = _pricing.enhance_quote_session()

        def _row(pr):
            row = {"key": pr.get("key"), "label": pr.get("label"),
                   "workflow_id": pr.get("workflow_id", ""),
                   "workflow_name": pr.get("workflow_name", ""),
                   "has_control": bool(pr.get("has_control")), "price": None, "free_card": False}
            if s is not None:
                try:
                    # A placeholder source: the quote prices the request SHAPE (verified for
                    # task-price 2026-08-18). A preset with a control (Change Emotion) needs
                    # its prompt to be quoted at all, so it has no price until one is picked.
                    etype = _gen_params.enhance_type_for(row["workflow_name"])
                    if etype is not None and not row["has_control"]:
                        row["price"] = _pricing.price_enhance(
                            s, _gen_params.build_enhance_body("1", etype))
                except Exception:
                    row["price"] = None
            return row

        # Price the six presets CONCURRENTLY. Each is two sequential PixAI round-trips (task-price
        # + kaisuuken-check), so done serially they stacked to ~5s and blocked the drawer's Enhance
        # slab from rendering at all (owner-reported). A small thread pool collapses that to about
        # one round-trip's latency; the result is cached (TTL above), so every later open -- and
        # every other user -- is instant. requests.Session is fine under concurrent GET/POST here
        # (it mutates no shared session state), and this is one small burst per cache-miss.
        if s is not None:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=len(_gen_params.BRIDGE_ENHANCE_PRESETS)) as ex:
                out = list(ex.map(_row, _gen_params.BRIDGE_ENHANCE_PRESETS))
        else:
            out = [_row(pr) for pr in _gen_params.BRIDGE_ENHANCE_PRESETS]
        if s is not None and all(r["price"] is not None for r in out if not r["has_control"]) \
                and _enh_price_cache["gen"] == gen0:     # cache only a fully-real, current result
            _enh_price_cache["presets"] = out
            _enh_price_cache["at"] = now
        return jsonify({"presets": out})

    @app.route("/api/enhance", methods=["POST"])
    @tier(LOGIN)
    def api_enhance():
        """One-click AI preset (PixAI panelplugin workflow) on the Edit tab's source image --
        the mirror-gated Bridge tier (drift §44 / SCOPE §3). Accepts `workflow_id` OR
        `workflow_name`. Login required. Returns {task_id}; telemetry is DEFERRED to terminal
        success (see /api/task-status), never fired at submit-acceptance.

        A panelplugin task submitted on the API KEY is accepted, queued, CHARGED, then reaped
        unstarted at ~60 min -- so this route REFUSES unless the PixAI mirror is armed and has a
        live browser session, the only credential that dispatches one. The gate is the FIRST
        thing here, before any input upload / card check / builder / submit, so a mirror-off
        request creates nothing and spends nothing."""
        from moonglade import backup as core
        # [BLOCKER] Backend mirror gate, before _input_media_id / build_panelplugin_parameters /
        # _apply_kaisuuken / submit_generation. Do NOT lean on submit_generation's own
        # _session_for_create gate: its mirror-OFF branch intentionally falls back to the API-key
        # session (the paid-panelplugin-reaped-at-60-min bug this surface was deleted for, plus an
        # invariant-#7 cross-identity violation). mirror_enabled() catches OFF; make_mirror_session()
        # is None catches ON-but-no-usable-session. make_mirror_session is READ_ONLY-guarded and
        # never raises, so it is safe to call as a gate.
        if not _mirror.mirror_enabled() or _mirror.make_mirror_session() is None:
            return jsonify({"error": "Mirror to PixAI must be armed to run AI presets — "
                                     "nothing was submitted, no credits spent"}), 409
        held_key = None
        reached = _Reached()
        try:
            p = request.get_json(silent=True) or {}
            expect_free = _pop_expect_free(p)
            send_key = _send_key("enhance", p)
            held = _send_claim(send_key, claim=False)        # 3.21.2 (L1): before any network
            if held:
                return held
            core, session = _gen_session()
            # Same road as every other create: build_request resolves the source image,
            # translates the Change-Emotion control and calls build_panelplugin_parameters;
            # gen_road.submit is the READ_ONLY + free-card choke. A panelplugin task can never
            # be covered by a card (measured 2026-08-18) -- the check simply returns no
            # match -- but it costs nothing to ride the same choke and it is one fewer
            # spend path with a guard of its own to get wrong.
            req = _gen_road.build_request(p, mode="enhance",
                                     resolve=_submit_resolver(core, session))
            params = req.parameters          # bound for _log_gen_failure's locals().get()
            if params is None:
                return jsonify({"error": req.note}), 400
            # A send uses a card, and a refusal means the cached "free" was wrong: either way
            # the presets' cached verdicts are dropped, so the tab's next read asks PixAI
            # again instead of offering "free" for an hour (2026-11-18).
            _enh_price_cache["presets"] = None
            _enh_price_cache["gen"] += 1
            held = _send_claim(send_key)
            if held:
                return held
            held_key = send_key
            task_id = _gen_road.submit(session, req,
                                  **_quoted_free_hooks(core, req, expect_free))["task_id"]
            _send_settle(held_key, "sent")
            # [BLOCKER] Telemetry is DEFERRED, not fired here: submit_generation returns the id at
            # createGenerationTask ACCEPTANCE (before start/completion), and a panelplugin job can
            # be accepted then reaped. Record the identity ACTUALLY submitted (workflowName when a
            # name preset, else the numeric id) so telem_set_add -- which skips falsy values --
            # counts a workflowName preset too. When THIS submit is the Change-Emotion workflow,
            # also carry the picked emotion key (the client's `emotion` field, the option stem --
            # the same value build_request translates to the danbooru tag) so the terminal can
            # record which of the emotion universe was used; gated on the emotion workflow exactly
            # as build_request gates the arg, so a stray `emotion` on another preset carries nothing.
            # The producers fire from /api/task-status's terminal-success branch via
            # _fire_enhance_telemetry.
            _wname = str(p.get("workflow_name") or "").strip()
            _identity = _wname or str(p.get("workflow_id") or "").strip()
            _emo = str(p.get("emotion") or "").strip()
            _emo_key = _emo if (_emo and _wname == _gen_params.ENHANCE_EMOTION_WORKFLOW) else None
            with _enhance_pending_lock:
                _enhance_pending[str(task_id)] = (_identity, _emo_key)
            # enhance_tools (Blades of Gondolin) + Speak-Friend (bridge_gens) are DEFERRED to
            # terminal success in _fire_enhance_telemetry, gated on the bridge-preset identity --
            # see there. A submit that is later reaped/failed must NOT count (parity with
            # enhance_workflows).
            return jsonify({"task_id": task_id})
        except Exception as e:
            unclear, msg, state = _send_failed("/api/enhance", e, reached.v,
                                               locals().get("params"), held_key,
                                               task_id=locals().get("task_id"))
            return unclear or (jsonify({"error": msg, "state": state}), 200)

    @app.route("/api/enhance/emotions")
    @tier(LOGIN)
    def api_enhance_emotions():
        """The staged Change-Emotion options: each emotion-role <key>.<img>
        (loose OR packed in the container), keyed by filename stem. The picker self-populates
        from whatever art is staged -- adding an emotion is dropping an image, no code change.
        Each option is flagged `membership` when PixAI gates it behind a paid tier.
        LOGIN tier; read-only, spends nothing. Disk/container scans are CODED;
        the emitted URLs keep the PUBLIC /branding/bridge/emotion/ form the
        front-end knows (the /branding/ route translates them back)."""
        from moonglade import backup as core
        exts = (".webp", ".png", ".jpg", ".jpeg")
        emo_prefix = (_branding._role_rel("emotion") + "/").lower()
        found = {}
        box = _branding._get_container()
        if box is not None:
            for rel in box.paths():
                low = rel.lower()
                if low.startswith(emo_prefix) and low.endswith(exts):
                    found.setdefault(Path(rel).stem,
                                     "/branding/bridge/emotion/" + Path(rel).name)
        edir = _branding._role_dir("emotion")
        if edir.is_dir():
            for p in sorted(edir.iterdir()):
                if p.is_file() and p.suffix.lower() in exts:
                    found[p.stem] = "/branding/bridge/emotion/" + p.name   # loose overrides packed
        gated = getattr(_gen_params, "ENHANCE_EMOTION_MEMBERSHIP", frozenset())
        emotions = [{"key": k, "label": k.replace("-", " ").replace("_", " ").strip().title(),
                     "img": v, "membership": k in gated} for k, v in sorted(found.items())]
        return jsonify({"emotions": emotions})

    @app.route("/api/scenes")
    @tier(LOGIN)
    def api_scenes():
        """The AI-Tools scene catalog: every live scene, its TILE fields (label, shape chip,
        detail line, catalog thumbnail, membership tier) and its CONTROL schema (presets,
        selectors, custom text, how many sources it needs). The nav modal browses the first
        half, the gen drawer's scene generator renders the second, and both share one
        memoized upstream read (scene_catalog).

        'Fetch, don't bake': the list is pulled LIVE from listChatEditingScenes through the
        mirror session (the identity that runs a scene) and cleaned to what the UI needs, so
        a scene PixAI adds appears with no code change -- the modal used to draw a hardcoded
        28 and could not see daily-fortune, daily-setlog or mini-mart-ad at all (issue #36).
        Mirror-gated exactly like /api/enhance -- the AI-Tools tier only exists when the
        Bridge is armed. LOGIN tier; read-only, spends nothing."""
        from moonglade.gallery import scene_catalog, scene_local_art, scene_row
        from moonglade import backup as core
        if not _mirror.mirror_enabled() or _mirror.make_mirror_session() is None:
            return jsonify({"error": "Mirror to PixAI must be armed to browse AI Tools"}), 409
        try:
            raw = scene_catalog(core, _mirror.make_mirror_session())
        except Exception as e:
            return jsonify({"error": _log_gen_failure("/api/scenes", e, None)[:200]}), 200
        rows = [scene_row(sc) for sc in raw if sc.get("sceneId")]
        for r in rows:
            r["local_art"] = scene_local_art(r["sceneId"])
        return jsonify({"scenes": rows})

    @app.route("/api/scene", methods=["POST"])
    @tier(LOGIN)
    def api_scene():
        """Generate one AI-Tools scene (createChatEditingSceneTask) on the picked source
        image(s). Mirror-gated FIRST, before any upload/build/submit: a scene task submitted on
        the API key is accepted, CHARGED, then reaped unstarted at ~60min (same reap as the
        panelplugin presets), so this refuses unless the mirror is armed with a live session and
        routes the submit through the JWT. Body: {scene_id, media_ids[], preset, custom?,
        selector_values?}. Login required; returns {task_id}."""
        from moonglade import backup as core
        if not _mirror.mirror_enabled() or _mirror.make_mirror_session() is None:
            return jsonify({"error": "Mirror to PixAI must be armed to run AI Tools — "
                                     "nothing was submitted, no credits spent"}), 409
        held_key = None
        reached = _Reached()
        try:
            p = request.get_json(silent=True) or {}
            # V9 (3.22): a scene never takes a card, so a send claiming a FREE quote is refused
            # before anything else, with nothing sent.
            if _pop_expect_free(p):
                return jsonify({"error": _gen_road.CARDLESS_FREE, "state": "not_sent"}), 400
            send_key = _send_key("scene", p)
            held = _send_claim(send_key, claim=False)        # 3.21.2 (L1): before any network
            if held:
                return held
            # 3.22 S5: an AI tool takes no SVG or GIF (PixAI's rule) -- before any upload.
            for m in (p.get("media_ids") or p.get("mediaIds") or []):
                why = _gen_params.source_refusal(_source_format_lookup(m), "tool")
                if why:
                    return jsonify({"error": why, "state": "not_sent"}), 400
            core, session = _gen_session()
            scene_id = str(p.get("scene_id") or p.get("sceneId") or "").strip()
            media = [_input_media_id(core, session, str(m).strip())
                     for m in (p.get("media_ids") or p.get("mediaIds") or []) if str(m).strip()]
            media = [m for m in media if m]
            if not scene_id:
                return jsonify({"error": "pick an AI tool"}), 400
            if not media:
                return jsonify({"error": "pick a source image"}), 400
            held = _send_claim(send_key)
            if held:
                return held
            held_key = send_key
            # submit_scene raises when PixAI's answer carries no task id (3.21.2): that is
            # "may have started", never a success with a null id. Its client is the marked
            # web-jwt one (3.22, DESIGN_3.22 2.5): for_create(require="web-jwt") refuses,
            # with nothing sent, unless the Mirror is armed and usable, and the door refuses a
            # scene on any other identity.
            from moonglade import pixai_client as _pixai_client
            task_id = _gen_road.submit_scene(
                _pixai_client._client_of(session).for_create(require="web-jwt"),
                scene_id, media,
                preset=str(p.get("preset") or "random"), custom=p.get("custom"),
                selector_values=(p.get("selector_values") or p.get("selectorValues") or []))
            if not task_id:
                raise core.PixAIError("scene: no task id returned")
            _send_settle(held_key, "sent")
            # Doorwarden telemetry is DEFERRED to terminal success (see _fire_scene_telemetry),
            # mirroring the enhance path: record the submitted scene id keyed by task id. The
            # scene id is stored only to be counted (scenes_used = len) -- it never leaves.
            with _scene_pending_lock:
                _scene_pending[str(task_id)] = scene_id
            return jsonify({"task_id": task_id})
        except Exception as e:
            # Pass the submit SHAPE as a dict (not the bare scene_id str) so _log_gen_failure
            # records the diagnosis -- the /api/enhance sibling passes locals().get("params")
            # the same way. submit_scene has no single builder-params dict at this site, so name
            # the shape explicitly (scene, preset, source count).
            unclear, msg, state = _send_failed(
                "/api/scene", e, reached.v,
                {"scene_id": locals().get("scene_id"),
                 "preset": (p.get("preset") if "p" in locals() else None),
                 "media_ct": len(locals().get("media") or [])}, held_key,
                task_id=locals().get("task_id"))
            return unclear or (jsonify({"error": msg, "state": state}), 200)

    # One Fix at a time (#93 review F4). Every Fix spends, and the clients' own gates (one in
    # flight per shot) cannot see a second tab, a stale bundle or a hand-rolled POST. So an
    # IDENTICAL Fix -- same signed-in user, same source as sent, same cleaned boxes -- inside
    # this many seconds of the last one this app accepted is refused before any network call.
    # The record is KEPT when that first submit's outcome is unknown or may have been charged
    # (it succeeded, a transport error or timeout, a 5xx after the send, no task id back):
    # the retry it invites is exactly a second spend. It is DROPPED when the first one is known
    # to have cost nothing -- refused before anything was sent (the mirror refusing, a body
    # the builder refuses) or refused by PixAI with a 4xx (insufficient balance and the like:
    # nothing created) -- so a fixed-up retry goes straight through (#93 review 2, F2).
    # Since 3.21.2 this is the single sends' repeat hold (_send_claim, above) keyed on the
    # cleaned fixer body: SEND_REPEAT_S after an accepted Fix, SEND_UNCLEAR_S after an unknown
    # outcome, dropped only when the Fix is known to have cost nothing (gen_road.send_outcome: never
    # reached, or a definite refusal -- the classifier's rule, so a 408, a 499 or a bare 4xx
    # keeps it, L2).
    _FIX_REPEAT_MSG = ("The same Fix was asked for a few seconds ago; wait a moment before "
                       "sending it again.")

    def _fix_repeat_refusal(core, p):
        """(refusal, key): the refusal (a JSON response) for a repeat of a recent identical
        Fix (key None), or (None, key) with this Fix now claimed under `key` -- which the
        route settles once the submit's outcome is known. A body build_fixer_body refuses is
        never recorded (None, None): it cannot spend, and its own refusal is the answer the
        caller should see."""
        try:
            body = _gen_params.build_fixer_body(str(p.get("source") or "").strip(), p.get("boxes"))
        except Exception:                  # noqa: BLE001 -- the build refuses it properly below
            return None, None
        key = _send_key("fix", body)
        held = _send_claim(key, repeat_msg=_FIX_REPEAT_MSG)
        if held:
            return held, None
        return None, key

    def _fix_forget(key):
        _send_settle(key, "not_sent")

    @app.route("/api/fix", methods=["POST"])
    @tier(LOGIN)
    def api_fix():
        """Submit a hand/face fixer task from the Edit-tab canvas. `boxes` are original-image
        pixel coords. Login required; returns {task_id} for the async poller.

        The Fix rides REST, not createGenerationTask: /v2/task/fixer takes {mediaId, boxes},
        built by gen_params.build_fixer_body -- the builder /api/price's quote uses too, so the
        badge and the spend carry the SAME boxes (kind, count, coordinates). The media id is
        the one deliberate difference: this route's resolver uploads the local file first and
        sends the upload-kind id (PixAI refuses an output id as an input here), while the quote
        names the catalog id (no upload per keystroke); PixAI's Fix price does not move with
        the picture. Face and hand boxes together are refused before any network call (PixAI's
        server refuses them; a Fix is one kind).

        One Fix at a time: an identical submit (same user, picture and boxes) inside
        SEND_REPEAT_S seconds of the last one is refused before any network call -- a
        double tap, or a client retry after a lost response, must not pay twice -- unless
        that last one is known to have cost nothing (gen_road.send_outcome)."""
        fix_key = None
        reached = _Reached()
        try:
            core, session = _gen_session()
            p = request.get_json(silent=True) or {}
            loom_target = _pop_loom_target(p)
            # V9 (3.22): no card ever covers a Fix, so a send claiming a FREE quote is refused
            # before anything else, with nothing sent.
            if _pop_expect_free(p):
                return jsonify({"error": _gen_road.CARDLESS_FREE, "state": "not_sent"}), 400
            # READ_ONLY first: the submit resolver below uploads the local file (a network
            # call), so the refusal has to come before it, not only inside submit_fixer.
            core._check_read_only(_gen_road._SUBMIT_ACTIONS["fix"])
            repeat, fix_key = _fix_repeat_refusal(core, p)
            if repeat:
                return repeat
            req = _gen_road.build_request(p, mode="fix",
                                     resolve=_submit_resolver(core, session))
            if not req.media_id:
                _fix_forget(fix_key)
                return jsonify({"error": "pick an image first"}), 400
            if not req.boxes:
                _fix_forget(fix_key)
                return jsonify({"error": "draw a box over a hand or face"}), 400
            # The exact body submit_fixer POSTs to /v2/task/fixer, named here so the failure
            # log below has the REQUEST SHAPE to report, the same way /api/generate and
            # /api/edit hand it their `params`. Built from the request's own inputs rather
            # than re-running clean_fix_boxes(), so nothing on the error path can itself
            # raise; a box the cleaner would have dropped is still worth seeing, because
            # "which boxes did we actually ask about" is half the diagnosis.
            fix_params = {"mediaId": req.media_id, "boxes": req.boxes}
            task_id = _gen_road.submit(session, req)["task_id"]
            _send_settle(fix_key, "sent")
            _record_loom_send(loom_target, task_id, req.parameters, "fix")
            _telemetry.telem_set_add("tools", "fix", out_dir=out_dir)   # Full Toolbox
            return jsonify({"task_id": task_id})
        except Exception as e:
            # Fix is the ONE drawer action that always spends -- no free card ever covers a
            # fixer task -- so an unlogged failure here is money gone with nothing written
            # down. This route was the last holdout after _log_gen_failure was added for the
            # 2026-07-26 undiagnosable decline: it returned the redacted text to the browser,
            # friendlyGenErr() replaced it with a guess, and the real error was recorded
            # nowhere at all. _send_failed logs it, settles the repeat record by the
            # classifier (kept unless the Fix is known to have cost nothing) and answers an
            # unknown outcome as "may have started" (3.21.2, L1/L2).
            unclear, msg, state = _send_failed("/api/fix", e, reached.v,
                                               locals().get("fix_params"), fix_key,
                                               task_id=locals().get("task_id"))
            return unclear or (jsonify({"error": msg, "state": state}), 200)

    # ---- queue-vs-render phase, recorded for the Activity tray -----------------------
    # Maps a task id to the `started` value already written to the job log for it. The tray
    # (gallery/src/notify/ActivityTray.jsx) renders from /api/jobs, never from api_task_status()'s response,
    # so `started` has to be written DOWN to reach it -- and writing it here is what makes
    # the signal identical on both hosts, because the gallery's Jobs.poll(), the Loom's
    # pollShot/pollTaskWithCeiling and the video drawer's own poll (gen/submitTask.js) all
    # hit this one route and none of them has to know the field exists.
    #
    # De-duped rather than written per poll for two concrete reasons: four pollers ask every
    # 3s per job, so a task PixAI sits on for its whole ~60-minute reap window would add
    # 1,200+ lines to jobs.jsonl; and each write refreshes that job's `ts`, which is the
    # clock JOBS_ORPHAN_SWEEP_AGE is measured against -- a heartbeat every 3s would mean the
    # ongoing orphan-reconciliation sweep never sees a job age in at all. At most two lines
    # per job survive this (queued, then started), and the entry is dropped the moment the
    # job reaches a terminal phase so the map stays bounded by tasks IN FLIGHT, not by uptime.
    _gen_phase_seen = {}
    _gen_phase_lock = threading.Lock()

    def _queue_estimate(core, session, tid):
        """PixAI's own queue-wait estimate for the model THIS task was submitted with, in
        seconds, or None. Two read-only calls (the task's stored submit parameters, then
        /v2/task/wait-time -- see core.queue_wait_estimate); fails soft, because an estimate
        must never turn a status poll into an error."""
        try:
            params = (_gen_cli._task_detail_query(session, tid) or {}).get("parameters") or {}
            if not isinstance(params, dict):
                return None
            return _pricing.queue_wait_estimate(session, params.get("priority"),
                                            params.get("modelId"))
        except Exception:                          # noqa: BLE001 -- a nicety, never fatal
            return None

    def _note_gen_phase(core, session, tid, started):
        """Write a generate job's queued/rendering phase to the job log, once per change.

        On the FIRST sighting of a job PixAI has accepted but not started, also record its
        queue estimate. Fetched here rather than per poll: a generation a worker picks up
        before its first poll costs zero extra calls, and one that really is queued costs
        two, once. The number is stored as the estimate PixAI gave when the job was seen
        queued and is rendered that way -- nothing recomputes it as the wait grows, and it
        is never presented as a countdown.

        Those two calls ride ONE poll of an already-queued job, which is why they are done
        inline rather than off-thread: the poll interval is 3s and this route already makes an
        un-timed PixAI call of its own on every single poll, so a second pair on one poll of
        one job is not the thing worth adding a thread for.
        """
        with _gen_phase_lock:
            if _gen_phase_seen.get(tid) == started:
                return
            first = tid not in _gen_phase_seen
            _gen_phase_seen[tid] = started
        fields = {"status": "running", "started": started}
        if first and not started:
            eta = _queue_estimate(core, session, tid)
            if eta is not None:
                fields["eta_seconds"] = eta
            # RE-CHECK before writing. The estimate above is two network calls long, and a
            # worker can pick the job up while we are inside it -- in which case a later poll
            # has already claimed and written the newer 'rendering' phase. Writing our
            # pre-fetch 'queued' on top of that would be permanent: the seen-map already
            # holds the newer value, so every subsequent poll returns early at the dedupe
            # check above and nothing ever corrects it. The job would render to completion
            # still displaying QUEUED. Dropping a stale write costs nothing; the newer phase
            # is already in the log.
            with _gen_phase_lock:
                if _gen_phase_seen.get(tid) != started:
                    return
        _log_job(tid, **fields)
        # Chaotic Creationist (jobs_concurrent): the high-water count of LIVE (non-terminal) jobs,
        # read from the authoritative job log so a task that later logs done/failed self-heals out
        # of the count -- abandoned polls and done-but-empty terminals never inflate the peak (the
        # in-memory _gen_phase_seen set leaks on both). telem_max keeps the peak. Silent-soft.
        try:
            # ...and only real GENERATIONS count. The log also carries panel jobs, imports,
            # deletes and CLI runs, and counting those made the peak a measure of "rows in
            # the log" rather than of generating several things at once -- one sync beside
            # one import could satisfy a rung nobody had actually earned.
            # ...and only jobs PIXAI has reported running to this server (the phase map this
            # function keeps): POST /api/jobs lets any signed-in page register a running row,
            # and fifty registered rows plus one real phase used to read as fifty-one.
            with _gen_phase_lock:
                _confirmed = set(_gen_phase_seen)
            _live = sum(1 for j in _jobs.read_jobs(out_dir)
                        if j.get("status") not in _jobs._JOBS_TERMINAL
                        and (j.get("type") or "generate") == "generate"
                        and str(j.get("job_id") or "") in _confirmed)
            _telemetry.telem_max("jobs_concurrent", _live, out_dir=out_dir)
        except Exception:
            pass

    def _forget_gen_phase(tid):
        with _gen_phase_lock:
            _gen_phase_seen.pop(tid, None)

    def _fire_enhance_telemetry(tid):
        """Fire the three enhance-achievement producers exactly once, on TERMINAL SUCCESS (a
        done phase WITH output) of an enhance task THIS server submitted. Deferred from
        /api/enhance -- which only sees createGenerationTask ACCEPTANCE -- so a task that is
        accepted, charged, then reaped unstarted (or fails) never counts. A no-op for any
        task id that was not a pending enhance (normal generate/edit/video collect here too).

        Swallows EVERY failure: by the time this runs the credit has already been spent and the
        result collected, so a telemetry error must not propagate into api_task_status's except
        handler -- that would report a false 'failed'/'running' and, worse, prompt a re-poll
        that re-collects. Mirrors api_generate's LoRA-telemetry try/except."""
        with _enhance_pending_lock:
            pend = _enhance_pending.pop(str(tid), None)
        if pend is None:
            return
        identity, emotion_key = pend
        try:
            _telemetry.telem_bump("enhances", out_dir=out_dir)                        # first-enhance milestone
            _telemetry.telem_set_add("tools", "enhance", out_dir=out_dir)             # Full Toolbox
            _telemetry.telem_set_add("enhance_workflows", identity, out_dir=out_dir)  # Enhance Adept: distinct rituals
            _telemetry.telem_set_add("bridge_gen_tasks", str(tid), out_dir=out_dir)   # Speak, Friend: any enhance is a bridge gen (distinct task, re-poll-safe)
            key = _BRIDGE_PRESET_KEY_BY_NAME.get(identity)                 # only the six known presets map; a non-preset enhance -> nothing
            if key:
                _telemetry.telem_set_add("enhance_tools", key, out_dir=out_dir)       # a gen-drawer enhance tool exercised (Blades of Gondolin)
            if emotion_key:                                                # Change-Emotion carried the picked expression
                _telemetry.telem_set_add("enhance_emotions", emotion_key, out_dir=out_dir)  # one of the emotion universe used
        except Exception:                                                  # noqa: BLE001
            pass

    def _drop_enhance_pending(tid):
        """Forget a pending enhance without firing telemetry -- for a terminal FAILURE (reaped,
        cancelled, or done-but-empty). Keeps the map from leaking and guarantees a failed run
        never bumps a counter."""
        with _enhance_pending_lock:
            _enhance_pending.pop(str(tid), None)

    def _fire_scene_telemetry(tid):
        """Fire the AI-Tools scene producer once, on TERMINAL SUCCESS of a scene task THIS
        server submitted. Deferred from /api/scene (which sees only createChatEditingSceneTask
        ACCEPTANCE), so a scene that is accepted, charged, then reaped (or fails) never counts.
        Records the scene id into the `scenes` set (Doorwarden); scenes_used exposes only its
        length -- the scene id never leaves the store. A no-op for any non-scene task. Swallows
        EVERY failure (by the time this runs the credit is spent + result collected)."""
        with _scene_pending_lock:
            scene_id = _scene_pending.pop(str(tid), None)
        if not scene_id:
            return
        try:
            _telemetry.telem_set_add("scenes", scene_id, out_dir=out_dir)   # Doorwarden: distinct scenes run
            _telemetry.telem_set_add("bridge_gen_tasks", str(tid), out_dir=out_dir)   # Speak, Friend: a scene is a bridge gen (distinct task, re-poll-safe)
        except Exception:                                        # noqa: BLE001
            pass

    def _drop_scene_pending(tid):
        """Forget a pending scene without firing -- for a terminal FAILURE (reaped, cancelled,
        done-but-empty). Keeps the map from leaking and guarantees a failed run never counts."""
        with _scene_pending_lock:
            _scene_pending.pop(str(tid), None)

    def _measured_clip_length(media_ids):
        """GitHub #63: a finished video whose length came back blank -- the task was already
        collected, so the catalog answered (it records no length), or ffprobe could not run in
        the collect -- is measured once from the downloaded file (2 dp, as the collect does), so
        the Loom's landTake records the clip's true length. None when no complete file is here
        or ffprobe cannot read it. Local only: never PixAI. It never raises: the task IS done,
        and a measurement that went wrong must not turn that answer into a failure or a retry."""
        from moonglade import backup as core
        try:
            for mid in media_ids or []:
                vid = _loom_complete_clip(str(mid))
                if vid is None:
                    continue
                d = _media_tools.duration(str(vid))
                return round(d, 2) if d is not None and d > 0 else None
        except Exception:                                      # noqa: BLE001
            return None
        return None

    @app.route("/api/task-status")
    @tier(LOGIN)
    def api_task_status():
        """Poll a submitted task: {phase: running|done|failed}. On 'done' it downloads +
        catalogs the result into this backup and returns media_ids + paid_credit. Read-only
        until done; login required."""
        # Bound HERE, not inside the try: the except clause below names this module,
        # and an except expression is evaluated while handling the exception -- so if
        # _gen_session() were the thing that raised, a try-scoped name would turn a
        # handled error into a NameError.
        from moonglade import backup as _core
        tid = (request.args.get("task_id") or "").strip()
        if not tid:
            return jsonify({"phase": "failed", "error": "task_id required"}), 400
        try:
            core, session = _gen_session()
            st = _task_reads.generation_status(session, tid)
            if st["phase"] == "done":
                _forget_gen_phase(tid)
                got = _collect_single_flight(core, session, tid)
                # authoritative done event -- written server-side so the Jobs card gets the
                # outcome even if the browser tab that submitted it has since closed.
                # paid_credit is PixAI's server-authoritative actual cost. Logged, not just
                # returned to the browser: it is the one number that cannot be
                # reconstructed later without re-querying PixAI per task, and it is what
                # makes an unexpected spend visible in the Activity tray afterwards. Passed
                # through even when 0 -- a card-covered generation really is free, and
                # "free" must stay distinguishable from "unknown".
                # 2.4 rule 7 (V3): THE terminal card check -- a send that carried a free card
                # and completed with a charge is a loud warning (logged inside card_unused) and
                # rides the done event, the Activity row's data, as card_unused.
                unused = _task_reads.card_unused(tid, st.get("paid_credit"),
                                                 _card_was_sent(tid), st.get("phase"))
                _log_job(tid, status="done", media_ids=got["media_ids"],
                         is_video=got.get("is_video", False),
                         paid_credit=st.get("paid_credit"),
                         card_unused=True if unused else None)
                # TERMINAL SUCCESS with output: the ONLY point an enhance is allowed to count
                # (deferred from /api/enhance's submit-acceptance). No-op for non-enhance tasks;
                # swallows its own errors so a post-charge telemetry blip can't fail this poll.
                _fire_enhance_telemetry(tid)
                _fire_scene_telemetry(tid)   # Doorwarden: same terminal-success gate as enhance
                _loom_journal_finish_task(tid)   # Session P: the shot may render again
                dur = got.get("duration")
                if got.get("is_video") and dur in (None, ""):
                    dur = _measured_clip_length(got.get("media_ids"))
                done = {"phase": "done", "media_ids": got["media_ids"],
                        "is_video": got.get("is_video", False),
                        "duration": dur,
                        "paid_credit": st["paid_credit"]}
                if unused:
                    done["card_unused"] = True
                # Session M (review F14): a run job's charge beside what its confirm expected,
                # so the dock can mark a mismatch peach. Absent for everything else.
                expected = _run_note_paid(tid, st.get("paid_credit"))
                if expected is not None:
                    done["expected_credit"] = expected
                return jsonify(done)
            if st["phase"] == "failed":
                _forget_gen_phase(tid)
                _drop_enhance_pending(tid)   # a reaped/cancelled enhance must NOT count
                _drop_scene_pending(tid)     # nor a reaped/cancelled scene
                # Carry PixAI's OWN reason (outputs.reason, e.g. "waiting timeout") into
                # both the job log and the response. This branch already fired correctly
                # for the owner's five reaped enhances -- it just logged the bare status,
                # so the tracker and the CLI could say no more than "cancelled", which
                # reads as though HE cancelled a job that in fact never started.
                reason = (st.get("reason") or "").strip()
                detail = _task_reads.describe_failure(st.get("status"), reason,
                                               started=bool(st.get("started")))
                _log_job(tid, status="failed", error=detail)
                _loom_journal_finish_task(tid)
                return jsonify({"phase": "failed", "status": st["status"],
                                "reason": reason, "error": detail})
            # `started` distinguishes "queued, no worker has taken it" from real work --
            # both are phase=running over the wire, and without it a task PixAI never
            # dispatches is an indefinite spinner for the ~60 min until it is reaped.
            # Recorded in the job log as well as returned, because the Activity tray reads
            # the log (see _note_gen_phase); the response alone only reaches whoever polled.
            started = bool(st.get("started"))
            _note_gen_phase(core, session, tid, started)
            return jsonify({"phase": "running", "status": st["status"],
                            "started": started})
        except _core.EmptyOutputsError as e:
            # TERMINAL, unlike the transient case below: PixAI already told us the
            # task reached 'done', and collect then found its outputs empty. The task
            # produced nothing and never will, so this MUST write an authoritative
            # 'failed' -- without it the job spins on 'running' in the Jobs card
            # forever. (Observed: an enhance submitted with an unusable input media id
            # sat at 'running' indefinitely while PixAI considered it long finished.)
            _drop_enhance_pending(tid)   # done-but-empty is a failure: it must NOT count
            _drop_scene_pending(tid)     # nor a done-but-empty scene
            _log_job(tid, status="failed", error=_redact_host_paths(str(e))[:200])
            _loom_journal_finish_task(tid)
            return jsonify({"phase": "failed", "error": _redact_host_paths(str(e))[:200]}), 200
        except (TypeError, AttributeError, NameError, KeyError, IndexError) as e:
            # A defect in THIS code, not a PixAI blip. The broad handler below deliberately
            # answers 'running' so a flaky network keeps getting retried -- but retrying a
            # TypeError just repeats it, so a genuinely broken poll used to present as a job
            # that was merely slow, for the full 6h polling ceiling, with nothing anywhere
            # saying otherwise. These are the errors that cannot come good on a retry, so
            # they get the authoritative 'failed' the paragraph below is right to withhold
            # from everything else.
            import logging as _logging          # module-local, as everywhere else in this file
            _log_job(tid, status="failed", error=_redact_host_paths(str(e))[:200])
            # The traceback is the whole point for this class: it names the line to fix, and
            # moonglade.logs keeps a rotating file log regardless of -v.
            _logging.getLogger(__name__).exception("task-status poll failed for %s", tid)
            return jsonify({"phase": "failed",
                            "error": "Moonglade hit an internal error checking this job "
                                     "({}). The generation itself may be fine -- check the "
                                     "Activity card.".format(_redact_host_paths(str(e))[:120])}), 200
        except Exception as e:
            # A transient PixAI blip (5xx/429/timeout) raises here even though the task may
            # still be running -- or already finished. Do NOT write an authoritative 'failed'
            # job event: that would brick the card with a sticky false failure + a red toast
            # for a task that likely succeeded. Leave the job at its last-known state (it ages
            # out, or the live-mirror watcher collects the real result). Only a genuine
            # st["phase"] == "failed" above logs a terminal failure.
            #
            # The RESPONSE used to say phase:'failed' too, which defeated the whole point of
            # the paragraph above: the Jobs poller (gallery/src/notify/jobs.js) treats phase==='failed'
            # as terminal and stops polling right there (it only reschedules on anything
            # else), so even with the job log correctly left alone, THIS live poll would
            # still brick the card with a false failure. Report it as non-terminal instead --
            # poll() falls into its 'running' branch on anything but 'done'/'failed' and just
            # tries again in 3s, up to its own 6h ceiling either way (audit fail-open fix).
            return jsonify({"phase": "running",
                            "status": "checking… ({})".format(_redact_host_paths(str(e))[:160])}), 200

    @app.route("/api/jobs")
    @tier(LOGIN)
    def api_jobs():
        """Reconstructed job list for the Jobs card (newest-first) -- the paper trail that
        survives a reload. The card polls this. Login required, like the creation suite.

        Also runs the ongoing orphan-reconciliation sweep (_reconcile_orphan_jobs,
        min_age=JOBS_ORPHAN_SWEEP_AGE) before reading -- the same "runs opportunistically
        off an existing poll" shape as maybe_compact_jobs just below it. This is what
        catches a job that gets orphaned WHILE the server keeps running (the watcher's own
        sweep only fires once, at startup) -- e.g. the browser tab polling
        /api/task-status was closed, or the live-mirror watcher missed the WS event, and
        the task finished on PixAI's side with nothing here ever the wiser. Fails soft
        (see _reconcile_orphan_jobs); a reconciliation problem must never break the card.

        `update` rides along: the standing release announcement (update_notice), or null.
        This poll is the app's ONE always-running server-truth channel -- every open tab
        runs it, on every screen, and gallery/src/notify/jobsStore.js already turns a
        transition in this payload into a toast. So the background release check announces
        through it rather than opening a loop of its own, which is the same rule the web
        surfaces follow for jobs. It costs GitHub nothing: update_notice only REPORTS what
        the hourly tick already found, and never fetches. Announce-only -- a client reading
        it can light the version stamp and say so, and applying is still the Panel's
        Update button and its confirm."""
        from moonglade.gallery import server_notice
        from moonglade import backup as core
        try:
            _reconcile_orphan_jobs(min_age=_jobs.JOBS_ORPHAN_SWEEP_AGE)
            jobs = _jobs.read_jobs(out_dir)
            _jobs.maybe_compact_jobs(out_dir)   # keep the append-only log bounded
        except Exception:
            jobs = []
        # Sessions R + Y: the gift box's live count (R4b) rides this same poll, and a job this
        # log holds as failed or stalled that PixAI's inbox says finished carries the note
        # (R2c). Both read process memory only -- this poll never asks PixAI for them.
        inbox_live = None
        try:
            from moonglade import inbox as moonglade_inbox
            inbox_live = moonglade_inbox.live_state()
            for j in jobs:
                says = moonglade_inbox.pixai_says(j.get("job_id"))
                if says and j.get("status") in ("failed", "stale"):
                    j["pixai_says"] = says
        except Exception:                                  # noqa: BLE001
            pass
        # `notice`: a sentence the server asks every open tab to say once per start
        # (server_notice), or null. Its Fix button carries this session's CSRF token: the
        # fix route checks it.
        notice = server_notice(local=_is_local_request())
        if notice and notice.get("fix"):
            notice["fix"]["csrf"] = session.setdefault("csrf", secrets.token_hex(16))
        return jsonify({"jobs": jobs, "update": _updater.update_notice(), "inbox": inbox_live,
                        "notice": notice})

    @app.route("/api/jobs", methods=["POST"])
    @tier(LOGIN)
    def api_jobs_register():
        """Register/update a job in the log. The Jobs card calls this the moment a gen is
        submitted (status=running) so it shows immediately; the authoritative done/failed
        events are written server-side by /api/task-status. Login required (any session, local or LAN)."""
        body = request.get_json(silent=True) or {}
        jid = str(body.get("job_id") or "").strip()
        if not jid:
            return jsonify({"ok": False, "error": "job_id required"}), 400
        # count: how many images this task was submitted to render (image-gen only --
        # absent on edit/fix/video/Loom registrations). Clamped to the same 1-4 range
        # /api/generate enforces; anything else is a caller bug or a stale client, not
        # data worth trusting into the log. Lets the React dock's Runs reel render a
        # real "N requested" placeholder for a running batch instead of one generic
        # tile (2026-08-02, closes the verify-flagged gap in the reel rebuild).
        _count = body.get("count")
        try:
            _count = int(_count)
            if not (1 <= _count <= 4):
                _count = None
        except (TypeError, ValueError):
            _count = None
        # Session M: the run a job belongs to and its cell (the reel's matrix grid), passed
        # through only when well-formed. The server writes both itself when it sends a run;
        # this keeps a client registration from ever carrying anything else.
        _run = str(body.get("run") or "")
        _run = _run if re.fullmatch(r"[0-9a-f]{1,36}", _run) else None
        try:
            _cell = int(body.get("cell")) if not isinstance(body.get("cell"), bool) else None
            if _cell is not None and not (0 <= _cell <= 23):
                _cell = None
        except (TypeError, ValueError):
            _cell = None
        _log_job(jid, status=(body.get("status") or "running"),
                 type=body.get("type"), label=body.get("label"),
                 done=body.get("done"), total=body.get("total"), count=_count,
                 run=_run, cell=_cell if _run else None,
                 source=body.get("source") or "web")
        if (body.get("status") or "running") == "running":
            # The app just sent a create: an idle task stream reopens to watch it.
            _task_stream.request_reopen("create")
        return jsonify({"ok": True})

    @app.route("/api/jobs/dismiss", methods=["POST"])
    @tier(LOGIN)
    def api_jobs_dismiss():
        """Dismiss one job (job_id) or every finished job (finished:true) from the card --
        this is how a sticky failure gets cleared. Login required (any session, local or LAN)."""
        from moonglade import backup as core
        body = request.get_json(silent=True) or {}
        if body.get("finished"):
            try:
                for j in _jobs.read_jobs(out_dir):
                    if j.get("status") in _jobs._JOBS_TERMINAL:
                        _log_job(j.get("job_id"), dismissed=True)
            except Exception:
                pass
        else:
            jid = str(body.get("job_id") or "").strip()
            if not jid:
                return jsonify({"ok": False, "error": "job_id required"}), 400
            _log_job(jid, dismissed=True)
        return jsonify({"ok": True})

    @app.route("/api/workflows")
    @tier(LOGIN)
    def api_workflows():
        """Live enhance-workflow catalog (id + name + type) for the Bridge picker. Read-only;
        login required (uses the owner's key). Restored 2026-08-18 for parity -- NOTE: this
        connection returns ZERO entries on our credential (probed 2026-08-16/17), so the six
        Bridge Enhance presets are hardcoded in the drawer, not sourced from here. Kept so the
        picker self-updates the day PixAI opens the connection to us."""
        try:
            core, session = _gen_session()
            return jsonify({"workflows": _models.workflow_catalog(session)})
        except Exception as e:
            return jsonify({"error": _redact_host_paths(str(e))[:200], "workflows": []}), 200

    # -- provided to ctx (split_move) --
    ctx._QUOTED_FREE_GONE = _QUOTED_FREE_GONE
    ctx._Reached = _Reached
    ctx._log_gen_failure = _log_gen_failure
    ctx._note_card_sent = _note_card_sent
    ctx._send_claim = _send_claim
    ctx._send_failed = _send_failed
    ctx._send_key = _send_key
    ctx._send_settle = _send_settle
    ctx._source_format_lookup = _source_format_lookup
    ctx._video_duration_lookup = _video_duration_lookup
    # -- end --
