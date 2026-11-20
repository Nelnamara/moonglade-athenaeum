"""
moonglade/gen_road.py
=====================
The generation road: the creates (`submit_generation`, `submit_fixer`, `submit_scene` and the
scene list read), the spend mark, Tsubaki.3 Unlimited Mode, the priority downgrade, the one
payload road (`GenerationRequest`, `RequestResolver`, `build_request`, `price`, `submit`,
`send_run`), `collect_generation`, and the outcome classification (the PixAI code tables,
`classify_outcome`, `definite_refusal`, `send_outcome`, the CLI's send-once helpers). Moved
verbatim out of moonglade/backup.py in the 3.22 split (phase 5).

It reaches the split modules it builds on as `_cards.X`, `_gen_params.X`, `_models.X`,
`_pricing.X`, `_mirror.X` and `_media_tools.X`, the way the engine did once they moved out. The
names it reads from the engine (the READ_ONLY gate `_check_read_only`, the transport, the error
classes, the catalog readers, `_turbo_refused`, and the task downloaders until the CLI runners
move) are imported from moonglade.backup inside each function that uses them, at call time, so
a test's patch of backup's binding (and the engine's own state) still reaches them and importing
this module never imports the engine.
"""
import copy
import datetime
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from moonglade import cards as _cards
from moonglade import gen_params as _gen_params
from moonglade import media_tools as _media_tools
from moonglade import mirror as _mirror
from moonglade import models as _models
from moonglade import pricing as _pricing


_GEN_MUTATION = ("mutation createGenerationTask($parameters: JSONObject!) {"
                 " createGenerationTask(parameters: $parameters) { id } }")
def priority_for_submit(params):
    """Downgrade a Turbo request to Low once PixAI has told us this account can't use it.

    Mirrors the downgrade half of PixAI's own normaliser. Returns the params unchanged
    when there is nothing to correct."""
    from moonglade.backup import _turbo_refused
    if _turbo_refused["seen"] and params.get("priority") == _gen_params.PRIORITY_TURBO:
        params = dict(params)
        params["priority"] = _gen_params.PRIORITY_LOW
    return params


def _is_turbo_refusal(err):
    """True for PixAI's members-only refusal (REQUIRE_MEMBERSHIP), read by its CODE only
    (DESIGN_3.22 2.7; S3_MESSAGE_TESTS item 1): on REST the oRPC body's `code`, on GraphQL any
    error whose code graphql_error_code reads as REQUIRE_MEMBERSHIP (the numeric 40300047 maps
    there). Never the message text. Consulted only after a definite refusal."""
    from moonglade.backup import PixAIRestError
    if isinstance(err, PixAIRestError):
        return err.code == "REQUIRE_MEMBERSHIP"
    errors = getattr(err, "graphql_errors", None)
    return isinstance(errors, list) and any(
        graphql_error_code(e) == "REQUIRE_MEMBERSHIP" for e in errors)


def _names_inference_profile(err):
    """True when a refusal's STRUCTURED data names `inferenceProfile` (DESIGN_3.22 2.7; S3_
    MESSAGE_TESTS item 2): a REST BAD_REQUEST or INVALID_PARAMETERS_COMPATIBILITY whose
    `data.issues[].path` holds it. PixAI's `data.compatibility` enum (lora, controlnet,
    styleMix, lowPriority) never names it. A GraphQL error carries no field that names the
    profile, and no GraphQL create carries one once image rides the door, so it is False there.
    An issue's message is never read."""
    from moonglade.backup import PixAIRestError
    if not isinstance(err, PixAIRestError) or err.code not in (
            "BAD_REQUEST", "INVALID_PARAMETERS_COMPATIBILITY"):
        return False
    for issue in err.data.get("issues") or []:
        path = issue.get("path") if isinstance(issue, dict) else None
        if isinstance(path, list) and "inferenceProfile" in path:
            return True
    return False


# The Bridge §4/§5 -- "AI Tools" = PixAI "chat editing scenes". A DIFFERENT surface from the
# panelplugin Enhance presets above: browse via listChatEditingScenes (read-only), generate via
# createChatEditingSceneTask (mutation). Captured + dispatch-proven live 2026-08-18 -- all 28
# scenes run on the mirror JWT. Browse UI: AiToolsModal.jsx; generate UI: the gen drawer's scene
# generator (§5). The submit shape was read from PixAI's own /ai-tools/<slug> page:
#   CreateChatEditingSceneTaskInput = {sceneId, mediaIds[], preset ("random" | <preset key> |
#     "custom"), custom?, selectorValues:[{id, value}]}
# with a client-side guard mediaIds.length >= (refImages.minCount or 1) -- every scene transforms
# at least one source image; dual-character needs exactly two. Like the panelplugin Enhance path,
# this is web-only: a scene task submitted on the API key is accepted, CHARGED, then reaped
# unstarted at ~60min -- it must ride the browser JWT, so the /api/scene route mirror-gates it
# and passes make_mirror_session() straight in (no _session_for_create -- that helper is for the
# createGenerationTask path; scenes always use the JWT session the caller hands them).
_SCENE_LIST_Q = """query listChatEditingScenes {
  chatEditingScenes {
    sceneId modelId title name description tutorial tags
    presets { name key i18nKey }
    custom { label description placeholder }
    images { background demo }
    permission { membershipTier }
    refImages { minCount maxCount slotLabels presetMediaIds }
    selectors { id label options { key label icon } defaultKey }
    overrideParameters
  }
}"""
# The GraphQL scene create, no longer sent since 3.22 S3-scene (the create door's
# /task/chat-editing-scene takes the same input); kept as the record of the old road.
_SCENE_SUBMIT_M = ("mutation createChatEditingSceneTask($input: CreateChatEditingSceneTaskInput!)"
                   " { createChatEditingSceneTask(input: $input) { id } }")


def chat_editing_scenes(session):
    """List PixAI's AI-Tools 'chat editing scenes' -- the browse half of the Bridge AI-Tools
    tier. Read-only: returns the raw scene configs (each carries sceneId, modelId, presets,
    selectors, custom, refImages, permission.membershipTier). The gen drawer reads each scene's
    control schema from here to render its form.

    Which credential: the scene LIST answers on the API key too (all 34 scenes, 2026-09-26
    probe). The app still browses only behind the armed Bridge, by decision (DECISIONS
    2026-08-18, "the AI-Tools tier splits by FUNCTION") -- /api/scenes passes
    make_mirror_session() -- and the SUBMIT (submit_scene) stays JWT-only: a scene submitted
    on the API key reaped unstarted when that was tried (DECISIONS 2026-08-18; not
    re-tested by the 2026-09-26 probe)."""
    from moonglade.backup import gql_adhoc
    d = gql_adhoc(session, _SCENE_LIST_Q, {}) or {}
    return d.get("chatEditingScenes") or []


def submit_scene(session, scene_id, media_ids, preset="random", custom=None, selector_values=None,
                 on_send=None):
    """Submit a chat-editing scene task (POST /v2/task/chat-editing-scene, through the create
    door since 3.22) -> task id. The generate half of the Bridge AI-Tools tier. SPENDS, so it
    goes through the door (SINGLE attempt, no retry -- a re-POST after a lost response pays
    twice) and MUST run on the mirror JWT (the door refuses any other identity); the
    caller passes _check_read_only first at the route choke, exactly like /api/enhance ->
    submit_generation. `preset` is a preset key, "random", or "custom" (with `custom` text);
    `selector_values` is [{id, value}] for the scene's selectors (e.g. aspect-ratio).
    `on_send(input)` is called immediately before the mutation (observation only)."""
    from moonglade import backup as _core
    _core._check_read_only("submit chat-editing scene")
    inp = {"sceneId": str(scene_id),
           "mediaIds": [str(m) for m in (media_ids or []) if m],
           "preset": str(preset or "random")}
    if custom is not None and str(custom).strip():
        inp["custom"] = str(custom)
    if selector_values:
        inp["selectorValues"] = [{"id": str(s["id"]), "value": s["value"]}
                                 for s in selector_values if s.get("id")]
    _observe_send(on_send, inp)
    # THE create door (3.22 S3-scene): POST /v2/task/chat-editing-scene, the same input object
    # GraphQL took. The door refuses it on any client but the Mirror's web sign-in (2.5), and an
    # answer with no task id is CreateOutcomeUnknown -- the task may exist -- never a None id.
    answer = _core._create(session, "scene", inp)
    _observe_created("scene", inp, answer)
    return str(answer["id"])


# =============================================================================
# Tsubaki.3 Unlimited Mode (SCOPE_2026-09-26_unlimited-mode, §8 amendments binding)
# =============================================================================
# A lane request is an ordinary Tsubaki.3 image submit carrying `parameters.lane =
# "infinite"`; PixAI runs it free while the account holds the entitlement, and stamps its own
# priority (300) on it. The app never claims the entitlement -- that is an account action the
# owner takes on PixAI's site -- and only ever READS its status.
#
# Four rules hold on every road (§2, §8.2-3):
#   - refuse, never silently drop: a lane request that breaks a rule is refused at build with
#     one plain sentence, before any spend;
#   - a lane request never touches a card (no /v2/kaisuuken/check, no kaisuukenId), keyed on
#     the params' own `lane`, whatever road built them;
#   - a lane request is never resubmitted as anything else (neither of submit_generation's
#     automatic resubmits fires on it);
#   - the entitlement is read live (cached briefly), never assumed.

UNLIMITED_LANE = "infinite"
# The versions the lane is offered on: PixAI's own site asks the status for Tsubaki.3's id and
# no other (§8.4). Not "any MMDIT26B" -- Flash is MMDIT26B too and has no lane.
UNLIMITED_VERSIONS = frozenset(("2024383379556065549",))
# Session H (decision 2 / T3a): a Tsubaki edit runs on Tsubaki.3. It is offered on every still
# picture -- the "Edit with Tsubaki" menu item and the Lightbox edit bar alike (owner ruling,
# 2026-09-28), whatever model made it. gallery/src/gen/tsubakiCore.js carries the same ids
# (dev/tests/test_tsubaki3_generate.py pins the copies together).
TSUBAKI3_MODEL_ID = "2024383378759147749"
TSUBAKI3_VERSION_ID = "2024383379556065549"
# The status is cached RAW, keyed by (version, the identity that creates), and the expiry is
# compared with the clock at every check (§8.8): an hour's success TTL is too long for a grant
# that ends on a fixed date, so success keeps 5 minutes and a failure the gate's own minute.
_UNLIMITED_CACHE_TTL = 300.0
_UNLIMITED_FAIL_TTL = 60.0
_unlimited_cache = {}                       # (version_id, identity) -> (fetched_at, raw|None)

UNLIMITED_BUSY = "An Unlimited Mode picture is still being made"
_UNLIMITED_REFUSED = "PixAI refused this as an Unlimited Mode task, so nothing was spent"
_UNLIMITED_NO_CARD = "Unlimited Mode never uses a free card — remove the card from this request"
_UNLIMITED_UNWIRED = "Unlimited Mode can't be checked on this road, so nothing was sent"
_UNLIMITED_T3_ONLY = "Unlimited Mode runs on Tsubaki.3 only"
_UNLIMITED_IMAGE_ONLY = "Unlimited Mode is for Tsubaki.3 image generation only"
_UNLIMITED_UNREAD = ("Couldn't read this model's settings from PixAI, so Unlimited Mode can't "
                     "be checked — try again in a minute")
_UNLIMITED_UNCONFIRMED = ("Couldn't confirm your Unlimited Mode with PixAI, so nothing was "
                          "sent — try again in a minute")
_UNLIMITED_ENDED = "Your Unlimited Mode has ended"
_UNLIMITED_NOT_HELD = "Unlimited Mode isn't active on this account"


def asks_unlimited(payload):
    """True when a web payload asks for the lane (the drawer's `unlimited: true`)."""
    return isinstance(payload, dict) and payload.get("unlimited") in (True, "1", "true", "on")


def is_lane_request(params):
    """True for ANY createGenerationTask params carrying a `lane` -- the web road's, a CLI
    --params-json, a banked --dump-params shape. The spend choke keys on this (§8.3)."""
    return isinstance(params, dict) and bool(params.get("lane"))


def _unlimited_identity():
    """The identity that will CREATE: the browser JWT when Mirror to PixAI is on, else the
    API key. The entitlement is read, and cached, under that identity (§8.8)."""
    return "mirror" if _mirror.mirror_enabled() else "key"


def _unlimited_session(session, identity):
    """The session the status is read on: the caller's for the API key; for the mirror, the
    stored browser JWT when it is usable, else None (the read then fails soft). Built
    directly, never through make_mirror_session: a read must not roll the token forward."""
    if identity != "mirror":
        return session
    jwt = _mirror.load_mirror_state().get("jwt") or ""
    return _mirror._mirror_session_from(jwt) if _mirror._jwt_usable(jwt) else None


def _unlimited_raw(session, version_id):
    """GET /v2/generation-model-version/<version>/infinite-mode, RAW, cached (see
    _unlimited_cache). A body is kept only when it carries a boolean `owned`; anything else
    -- an exception, a non-2xx, a strange body, an unusable mirror session -- is a failure,
    cached for _UNLIMITED_FAIL_TTL, and returns None. Read-only."""
    from moonglade.backup import _rest_get
    vid = str(version_id or "").strip()
    if not vid:
        return None
    identity = _unlimited_identity()
    key = (vid, identity)
    now = time.monotonic()
    hit = _unlimited_cache.get(key)
    if hit is not None:
        ttl = _UNLIMITED_CACHE_TTL if hit[1] is not None else _UNLIMITED_FAIL_TTL
        if (now - hit[0]) < ttl:
            return hit[1]
    raw = None
    try:
        s = _unlimited_session(session, identity)
        if s is not None:
            data = _rest_get(s, "/generation-model-version/" + vid + "/infinite-mode",
                             timeout=_models._GATE_READ_TIMEOUT)
            if isinstance(data, dict) and isinstance(data.get("owned"), bool):
                raw = data
    except Exception:
        raw = None
    _unlimited_cache[key] = (now, raw)
    return raw


def _expiry_epoch(value):
    """PixAI's expiresAt as epoch seconds, or None. ISO 8601 is what the route answers (the
    site reads it with `new Date(...)`); epoch seconds or milliseconds are tolerated."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) / 1000.0 if value > 1e12 else float(value)
    try:
        d = datetime.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.timestamp()


def infinite_mode_status(session, version_id, now=None):
    """The account's Unlimited Mode on a version -> {owned, expires_at, days_left}, or None
    when the status could not be read. S1, as amended (§8.8).

    `owned` is True only when PixAI says owned AND expiresAt is still in the future, compared
    with the clock on EVERY call (the raw answer is cached, the verdict never is), so nothing
    goes out as a lane request after the grant ends. `days_left` is whole days remaining,
    rounded up -- the site's own count (29 on 2026-09-26 for a 2026-10-25 grant); 0 when not
    owned. Read-only: never the claim route."""
    import math
    raw = _unlimited_raw(session, version_id)
    if raw is None:
        return None
    exp = _expiry_epoch(raw.get("expiresAt"))
    t = time.time() if now is None else now
    owned = raw.get("owned") is True and exp is not None and exp > t
    return {"owned": owned,
            "expires_at": raw.get("expiresAt") if exp is not None else None,
            "days_left": int(math.ceil((exp - t) / 86400.0)) if owned else 0}


def _lane_size_rule(ranges, step):
    """The lane's size limit off a version's /size-config ranges, or None without them: the
    site's own rule -- the area fits the SMALLEST range's max area and the size lies inside a
    range. `max_side` is the largest square on the model's step inside that area (Tsubaki.3:
    1800 x 1800 is the area, and 1800 is off the 16 px grid, so 1792 x 1792 -- §8.5)."""
    import math
    if not ranges:
        return None
    step = max(1, int(step or 1))
    max_area = min(r[1] * r[3] for r in ranges)
    return {"max_area": max_area, "max_side": math.isqrt(max_area) // step * step,
            "ranges": [list(r) for r in ranges]}


def _lane_size_ok(width, height, rule):
    """True when (width, height) passes _lane_size_rule's limit."""
    return (width * height <= rule["max_area"]
            and any(r[0] <= width <= r[1] and r[2] <= height <= r[3] for r in rule["ranges"]))


def _unlimited_check(session, params, version_id):
    """The lane's eligibility, on the GATED dict (S3, §8.4-5): refuse with one sentence, or
    return a COPY carrying `lane` with `priority` removed (PixAI stamps its own 300 on a lane
    task; the site's build sends none -- §8.2). The caller's dict is never mutated.

    Order: the version pin (no read) -> the gated shape (the gate's three cached reads must all
    have answered, or the gate passed an unsnapped, unconverted dict) -> the entitlement ->
    the site's own rules: Pro mode, batch 1, no reference, no workflow or recipe, no card, no
    High priority, and the size actually sent (after the 16 px snap)."""
    from moonglade.backup import PixAIError
    vid = str(version_id or "").strip()
    if vid not in UNLIMITED_VERSIONS:
        raise PixAIError(_UNLIMITED_T3_ONLY)
    feats = _models._model_features(session, vid)
    profiles = _models._model_profiles(session, vid)
    ranges = _models._model_size_config(session, vid)
    if not feats or not profiles or not ranges:
        raise PixAIError(_UNLIMITED_UNREAD)
    if feats["model_type"] != "MMDIT26B_MODEL":
        raise PixAIError(_UNLIMITED_T3_ONLY)
    status = infinite_mode_status(session, vid)
    if status is None:
        raise PixAIError(_UNLIMITED_UNCONFIRMED)
    if not status["owned"]:
        raise PixAIError(_UNLIMITED_ENDED if status["expires_at"] else _UNLIMITED_NOT_HELD)
    p = params
    if str(p.get("inferenceProfile") or "").strip().lower() != "pro":
        raise PixAIError("Unlimited Mode runs on Pro mode — pick Pro")
    try:
        batch = int(p.get("batchSize") or 1)
    except (TypeError, ValueError):
        batch = 0
    if batch != 1:
        raise PixAIError("Unlimited Mode makes one picture at a time — set the count to 1")
    if p.get("mediaId") or p.get("contextImages"):
        raise PixAIError("Unlimited Mode can't use a reference picture — remove it")
    if p.get("workflowId") or p.get("recipeIds"):
        raise PixAIError("Unlimited Mode can't use a workflow or a recipe")
    if p.get("kaisuukenId"):
        raise PixAIError(_UNLIMITED_NO_CARD)
    if p.get("priority") in (_gen_params.PRIORITY_HIGH, _gen_params.PRIORITY_XHIGH):
        raise PixAIError("Unlimited Mode can't use High priority — turn it off")
    rule = _lane_size_rule(ranges, _models._size_rule(feats["model_type"], ranges)["step"])
    try:
        w, h = int(p.get("width")), int(p.get("height"))
    except (TypeError, ValueError):
        w = h = 0
    if not (w > 0 and h > 0 and _lane_size_ok(w, h, rule)):
        raise PixAIError("Unlimited Mode: this size is too large — up to {0} × {0}".format(
            rule["max_side"]))
    out = dict(p)
    out["lane"] = UNLIMITED_LANE
    out.pop("priority", None)
    return out


def unlimited_resolver(session):
    """The build-time lane check for RequestResolver.unlimited: (params, version_id) -> the
    lane params, or a PixAIError. The SAME function for a quote and a spend (the gallery's
    _price_resolver and _submit_resolver), like gate_resolver. A resolver WITHOUT it refuses a
    lane request (§8.10) -- a road that cannot read the entitlement never sends one."""
    def _check(params, version_id):
        return _unlimited_check(session, params, version_id)
    return _check


def _graphql_reason(err):
    """PixAI's own words out of a gql_mutate refusal ("GraphQL error: [{message, extensions:
    {code}}]"): the messages, each with its code when it has one. The raw text otherwise."""
    s = str(err)
    head = "GraphQL error: "
    if s.startswith(head):
        try:
            errs = json.loads(s[len(head):])
            bits = []
            for e in errs if isinstance(errs, list) else []:
                if isinstance(e, dict):
                    code = (e.get("extensions") or {}).get("code") \
                        if isinstance(e.get("extensions"), dict) else None
                    msg = str(e.get("message") or "").strip()
                    bits.append(msg + (" ({})".format(code) if code else ""))
            if any(bits):
                return "; ".join(b for b in bits if b)
        except ValueError:
            pass
    return s


def submit_generation(session, params, *, on_send=None, exact=False, kind="image",
                      on_created=None):
    """Submit one generation and return the task id immediately -- no wait, no download. The
    card (if any) must already be attached to `params`. Raises on no id.

    THE ROAD (3.22, DESIGN_3.22 2.11): `kind` ("image", "edit", "video"; the caller's own mode,
    never read off the parameters) picks CREATE_ROAD's road. On "rest" the one send is the
    create door (core._create), and its answer goes through the observation step
    (_observe_created, fail-soft) and to `on_created(answer)`; on "graphql" it is
    createGenerationTask through gql_mutate, as before. Both resubmits below are keyed on
    PixAI's CODES (_names_inference_profile, _is_turbo_refusal), never on message text, and
    fire only after a definite refusal.

    Session M (BUILD-w5-m s3.4): `on_send(variables)` is called immediately before each
    mutation with a deep COPY of what is about to go out -- observation only: its return is
    ignored and an exception inside it is swallowed, so a recorder can never block or alter a
    spend. It is how the Inspector learns the exact request PixAI got and how a run knows the
    mutation was reached. `exact=True` (a run's jobs, review F6) turns off BOTH refusal-only
    resubmits below: a job goes out once, exactly as it was quoted and confirmed, and PixAI's
    refusal comes back as it came. Both default to today's behaviour, byte for byte.

    inferenceProfile (the Mode quality setting) is MODEL-TYPE-SPECIFIC on PixAI's side --
    some model types only accept lite/standard, others pro/ultra, and an unsupported value
    gets the whole submit REJECTED with a raw GraphQL error. A rejected submit costs no
    credits, so on that specific rejection this drops inferenceProfile and retries once on
    the model's default instead of failing the call outright. This used to be a one-off
    try/except living only inside the CLI's run_generate; moved here 2026-07-24 so every
    caller gets it for free -- the web /api/generate, /api/edit and /api/loom/generate
    routes, and run_generate itself, which now just calls through here (see its own
    comment). Only params built by _gen_parameters ever carry inferenceProfile, so this
    is a silent no-op for every other caller (edit/enhance/video params never set it).

    The submit goes through `gql_mutate`, NOT `gql_adhoc`: a createGenerationTask that is
    transparently re-POSTed after a lost response is a second generation and a second
    charge. The inferenceProfile re-submit below is a different thing and is safe -- it
    only fires on a PixAIError, which means PixAI answered with a GraphQL error and
    REJECTED the task, so there is nothing created and nothing charged to duplicate.

    An Unlimited Mode request (ANY params carrying `lane`, whatever road built them --
    SCOPE_2026-09-26_unlimited-mode §8.2-3) is exempt from BOTH resubmits: dropping its
    profile or its Turbo would send a different task than the lane request that was asked
    for, and the Turbo fallback would also flip the process-wide _turbo_refused. It goes out
    once; PixAI's refusal comes back in plain words. It never carries a card."""
    from moonglade.backup import _check_read_only, gql_mutate, PixAIError, _turbo_refused
    _check_read_only("submit a generation (spends credits)")
    _gen_params.check_params_retired(params)             # before any network call: no spend, no round-trip
    lane = is_lane_request(params)
    if lane and params.get("kaisuukenId"):
        raise PixAIError(_UNLIMITED_NO_CARD)
    # Mirror routing (review F4/F5): after the READ_ONLY gate, the create rides the browser
    # JWT session when the toggle is on (else this is a pass-through, unchanged). submit_
    # generation is create-only -- it returns the task id and never polls/collects -- so
    # rebinding the whole session here is safe; the CALLER keeps its API-key session for
    # download (F6).
    session = _mirror._session_for_create(session)
    # Gate the field set on the model's architecture (DiT profile vs SDXL steps/cfg) BEFORE
    # the mutation, with the SAME helper price_task uses, so the submitted shape equals the
    # priced shape. Fail-soft: an undetermined profile set returns params unchanged (today's
    # behavior).
    params = _models._gate_params_for_model(session, params)
    # Lane w2-recipes: the dict about to go out may not carry recipes beside context images
    # (a reference the backstop gate just converted), a lane or an upscale. No network.
    from moonglade import recipes as _recipes
    _recipes.check_params(params)
    if not exact:
        # Already known to be turbo-refused? use Low. A run job (exact) never: the run applied
        # this at build, so it was quoted and digested, and what is sent must equal what was
        # quoted (review N1) -- a flag flipped since then would send an unquoted priority.
        params = priority_for_submit(params)
    # Session H (BUILD-w2-gen §8, review S1): decided BEFORE the mutation, off the gate's own
    # cached profile read -- is the profile asked for one this version LISTS? A listed profile
    # PixAI refuses is an entitlement refusal (a non-member's Ultra), not "unsupported", so the
    # drop-and-resubmit below must not turn it into a Pro job the quote never described; and
    # a REQUIRE_MEMBERSHIP answer on a listed members-only profile is ambiguous between Ultra
    # and Turbo, so the Turbo fallback stands down too. An unreadable list keeps today's
    # self-heal (pinned since 2026-07-24).
    listed, members_only = _models._profile_listing(session, params)

    road = CREATE_ROAD.get(kind, "graphql")

    def _send(p):
        _mark_spend_reached()                                # 3.21.2: this thread's spend mark
        if on_send is not None:
            try:
                on_send(copy.deepcopy(p))
            except Exception:                                # noqa: BLE001
                pass                                         # a recorder never blocks a spend
        if road == "rest":
            # THE create door: one POST, checked on its final bytes. Its unknown outcomes
            # (CreateOutcomeUnknown) are not PixAIErrors, so nothing below can resubmit them.
            from moonglade import backup as _core
            answer = _core._create(session, kind, p)
            _observe_created(kind, p, answer, on_created)
            return str(answer["id"])
        created = gql_mutate(session, _GEN_MUTATION, {"parameters": p})
        tid = ((created or {}).get("createGenerationTask") or {}).get("id")
        if not tid:
            # Raised inside the send, so it reads "may have started" and is never resubmitted
            # (definite_refusal is False for it).
            raise PixAIError("no task id returned: " + json.dumps(created)[:200])
        return str(tid)
    try:
        task_id = _send(params)
    except PixAIError as e:
        if _recipes.refusal_from(e):
            # PixAI refused a recipe: nothing was created. Re-raised BEFORE the two resubmits
            # below can read its words -- a recipe refusal is never retried as anything else.
            raise
        if lane:
            # Never retried as anything else (§8.2). A definite refusal (classify_outcome: a
            # coded GraphQL error with no data, or a REST oRPC code in the table) means nothing
            # exists and nothing was spent; anything else -- a partial success, a timeout, a
            # local refusal -- is passed on as it came. Keyed on the type and the structured
            # fields, never on the message text (DESIGN_3.22 2.6, L2).
            if classify_outcome(e) == "refused":
                refused = PixAIError(_UNLIMITED_REFUSED + ": " + outcome_reason(e))
                refused.graphql_data = getattr(e, "graphql_data", None)
                refused.refused = True       # a definite refusal, for a run's job state
                raise refused
            raise
        if exact:
            # A run job (review F6): never resubmitted on another profile or priority -- that
            # would be a request nobody quoted, sent after the run's budget check. PixAI's
            # answer comes back as it came; definite_refusal() reads it.
            raise
        if classify_outcome(e) != "refused":
            # Both resubmits below are safe ONLY because a refusal by PixAI means nothing was
            # made. A partial success, a timeout, a dropped connection, a bare 4xx or a code
            # outside DEFINITE_CODES is passed on unchanged; so is a local refusal (nothing
            # reached PixAI, so there is no PixAI answer to correct).
            raise
        if _names_inference_profile(e) and "inferenceProfile" in params and listed:
            refused = PixAIError("PixAI refused the {} profile for this account, so nothing "
                                 "was made: {}".format(params.get("inferenceProfile"),
                                                       outcome_reason(e)))
            refused.refused = True
            raise refused
        if _names_inference_profile(e) and "inferenceProfile" in params:
            dropped = params.pop("inferenceProfile")
            print("  mode '{}' not supported by this model; retrying on the "
                  "model's default...".format(dropped))
            task_id = _send(params)
        elif _is_turbo_refusal(e) and params.get("priority") == _gen_params.PRIORITY_TURBO \
                and not members_only:
            # Turbo (500) is members-only and this app asked for it on EVERY submit, so
            # the day a membership lapses every generate/edit/video/fix/upscale starts
            # failing at once. Safe to re-submit for the same reason the inferenceProfile
            # case above is: PixAI refused the task with a definite code -- nothing exists and
            # nothing was charged. Falls back to the tier their own client would have picked
            # for a non-member.
            params = dict(params, priority=_gen_params.PRIORITY_LOW)
            _turbo_refused["seen"] = True
            print("  turbo is members-only on this account; resubmitting at standard "
                  "speed (no extra cost).")
            task_id = _send(params)
        else:
            raise
    _cards._bump_card_use(params)
    return str(task_id)


# THE SPEND MARK (3.21.2, L1). A caller that must tell "never reached the send" from "sent,
# answer unclear" -- a web single send, a CLI runner -- takes a fresh mark for its thread with
# spend_watch(); each create marks it immediately before its one spend request
# (_mark_spend_reached: submit_generation's send, submit_fixer, submit_scene). Thread-local,
# because a request's send runs on the request's own thread; observation only, it changes
# nothing that is sent.
_SPEND_WATCH = threading.local()


class _SpendMark:
    __slots__ = ("v",)

    def __init__(self):
        self.v = False


def spend_watch():
    """A fresh spend mark for this thread: `.v` turns True once a create in this thread
    reaches its spend request. Replaces any earlier mark of the thread."""
    mark = _SpendMark()
    _SPEND_WATCH.mark = mark
    return mark


def _mark_spend_reached():
    mark = getattr(_SPEND_WATCH, "mark", None)
    if mark is not None:
        mark.v = True


def _observe_send(on_send, payload):
    """Mark this thread's spend as reached, and tell an `on_send` observer what is about to go
    out (a deep copy). Observation only: an exception inside the observer is swallowed, so a
    recorder can never block or alter a spend."""
    _mark_spend_reached()
    if on_send is None:
        return
    try:
        on_send(copy.deepcopy(payload))
    except Exception:                                        # noqa: BLE001
        pass


#: DESIGN_3.22 2.4 rule 7 / 7.3 R8: whether a card-covered create through the door has once
#: been PROVEN free on PixAI's REST route (the terminal read showed paidQuota 0 and the card
#: count dropped). Until then a run counts a card job as charged whenever PixAI's answer shows
#: a charge (send_run). Flipped only by a commit that cites R8's record.
CARD_PROOF_ON_REST = False

#: The stored-parameters keys the observation step compares (2.4 rule 6).
_OBSERVED_KEYS = ("modelId", "priority", "kaisuukenId", "channel", "lane")


def _observe_created(kind, sent, answer, on_created=None):
    """THE OBSERVATION STEP after a successful door create (DESIGN_3.22 2.4 rule 6, T-F11):
    compare the answer's stored `parameters` with what was sent (modelId, priority,
    kaisuukenId, channel, lane, chat.modelId, chat.modelConfig.*) and read `paidQuota`. A
    difference, or a `paidQuota > 0` on a card send, is a LOUD warning in the log. Returns the
    warnings. Observation only and fail-soft: nothing it raises can turn a created task into an
    error, and it never sends anything. `on_created(answer)` is told after it (a run reads the
    charge from there, rule 7)."""
    warnings = []
    try:
        stored = answer.get("parameters") if isinstance(answer, dict) else None
        if isinstance(stored, dict) and isinstance(sent, dict):
            for k in _OBSERVED_KEYS:
                if k in sent and stored.get(k) != sent.get(k):
                    warnings.append("{} sent {!r}, stored {!r}".format(k, sent.get(k),
                                                                       stored.get(k)))
            sc, tc = sent.get("chat"), stored.get("chat")
            if isinstance(sc, dict) and isinstance(tc, dict):
                if "modelId" in sc and tc.get("modelId") != sc.get("modelId"):
                    warnings.append("chat.modelId sent {!r}, stored {!r}".format(
                        sc.get("modelId"), tc.get("modelId")))
                smc, tmc = sc.get("modelConfig") or {}, tc.get("modelConfig") or {}
                if isinstance(smc, dict) and isinstance(tmc, dict):
                    for k, v in smc.items():
                        if tmc.get(k) != v:
                            warnings.append("chat.modelConfig.{} sent {!r}, stored {!r}".format(
                                k, v, tmc.get(k)))
        paid = answer.get("paidQuota") if isinstance(answer, dict) else None
        if isinstance(paid, (int, float)) and not isinstance(paid, bool) and paid > 0 \
                and isinstance(sent, dict) and sent.get("kaisuukenId"):
            warnings.append("a free card was sent and PixAI's answer shows paidQuota {}: the "
                            "card may not have been used".format(paid))
        if warnings:
            import logging
            logging.getLogger("moonglade.create").warning(
                "create %s task %s: PixAI's stored request differs from what was sent: %s",
                kind, answer.get("id") if isinstance(answer, dict) else "?",
                "; ".join(warnings))
    except Exception:                                        # noqa: BLE001 -- observation only
        pass
    if on_created is not None:
        try:
            on_created(copy.deepcopy(answer))
        except Exception:                                    # noqa: BLE001
            pass
    return warnings


def submit_enhance(session, body, on_send=None):
    """Submit one AI-preset enhance (POST /v2/task/enhance, through the create door) -> task
    id. 3.22 S3-enhance. READ_ONLY first; then the identity: for_create(require="web-jwt") --
    the API-key panelplugin reaped unstarted (DECISIONS 2026-08-18), so an enhance never rides
    the key, and the door refuses it there too. The body is rebuilt by build_enhance_body (a
    hand-built one is refused before any network call). No card, ever. One POST; an id-less or
    lost answer is CreateOutcomeUnknown. `on_send(body)` is told just before it."""
    from moonglade import backup as _core
    from moonglade import pixai_client as _pixai_client
    _core._check_read_only("submit an AI preset (spends credits)")
    sent = _gen_params.build_enhance_body((body or {}).get("mediaId"),
                                          (body or {}).get("enhanceType"),
                                          (body or {}).get("prompt"))
    client = _pixai_client._client_of(session).for_create(require="web-jwt")
    _observe_send(on_send, sent)
    answer = _core._create(client, "enhance", sent)
    _observe_created("enhance", sent, answer)
    return str(answer["id"])


def submit_fixer(session, media_id, boxes, on_send=None):
    """Submit a hand/face fixer task via POST /v2/task/fixer -> task id (poll it like any
    generation). `boxes` = [{x, y, width, height, tag}] in ORIGINAL-image pixel coords, tag
    'hand' | 'face' (<=20), all ONE kind. Builds a mask from the boxes and repairs those
    regions. Raises.

    READ_ONLY first, then build_fixer_body -- so a body with no usable box, or with two kinds
    PixAI would refuse, is refused here before any network call. Never sends cusPrompts.
    `on_send(body)` is called immediately before the one POST (observation only)."""
    from moonglade import backup as _core
    _core._check_read_only("submit a hand/face fix (spends credits)")
    body = _gen_params.build_fixer_body(media_id, boxes)
    # The fixer IS a credit-spending create, so it rides the mirror JWT session when the
    # toggle is on (review F1: the choke belongs at "a create", not only at gql_mutate sites).
    # Create-only -- the caller polls/collects on its own API-key session (F6); pass-through
    # when the mirror is off; refuses before spend if the mirror is on but unavailable (F5).
    create_session = _mirror._session_for_create(session)
    _observe_send(on_send, body)
    # THE create door (3.22 S3-fix): one POST to /v2/task/fixer, checked on its final bytes.
    # An id-less or lost answer is CreateOutcomeUnknown, never a success with no id.
    answer = _core._create(create_session, "fix", body)
    _observe_created("fix", body, answer)
    return str(answer["id"])

# =============================================================================
# ONE PAYLOAD ROAD -- price and submit build the same dict
# =============================================================================
# Every create surface used to reach a PixAI `parameters` dict by a road of its
# own: /api/price through the gallery's `_params_and_nocard`, and each create
# route through its own builder call, its own `_apply_kaisuuken`, its own
# mutation. Two roads to one number is how a cost badge comes to quote a job
# that is not the one about to be paid for -- the hazard already written down at
# /api/generate ("the badge must quote the shape that will actually submit").
#
# The interface is three names, and they sit here, right behind the builders,
# because that is the only place both a quote and a spend can see the same dict:
#
#   build_request(payload, ...) -> GenerationRequest    the ONLY producer
#   price(session, req)  -> dict                        READ-ONLY, spends nothing
#   submit(session, req) -> dict                        the ONE spend choke
#
# `price` and `submit` both read `req.parameters` and neither ever rebuilds it,
# so a quote and a spend inside one request describe the same job by
# construction, not by two pieces of code agreeing. A caller cannot submit a
# shape that was never quotable, because `build_request` is the only place a
# shape comes from and the mode dispatch lives there exactly once.
#
# It is also the one place READ_ONLY and the free card are decided. Before this,
# each web route called `_apply_kaisuuken` (a real network call) and only THEN
# reached `submit_generation`'s READ_ONLY guard -- the same fail-open ordering
# the four CLI runners were fixed for on 2026-07-21, still live on the web side.
# `submit` checks first and matches nothing else.
#
# The CLI runners (`run_generate`, `run_generate_video`, `run_edit_image`, ...)
# deliberately keep their own flow for now: they carry preview/--confirm/--dump-
# params behaviour that is not a web payload's, and folding them in is its own
# increment.


@dataclass
class GenerationRequest:
    """One create request: the exact dict PixAI will receive, plus the few
    route-level facts the payload carries that a submit needs.

    `parameters` is THE object -- price() reads it, submit() sends it, nothing
    rebuilds it in between. `None` means the payload was not enough to build a
    shape, and `note` says what is missing in the cost badge's own voice.

    mode              "image" | "edit" | "fix" | "video" | "enhance"
    parameters        createGenerationTask `parameters`, or None (see `note`)
    no_card           skip the free-card match (forced True for a Fix)
    note              why `parameters` is None -- rendered by the badge
    price_note        set when the shape is REAL but must not be priced: an
                      enhance/panelplugin task is priced by its workflow id,
                      which is deliberately not in _PRICE_SCALARS, so pricing
                      the workflow-less shape that survives the allowlist
                      returns a confident WRONG number. No number is the honest
                      answer until that is measured live.
    media_id / boxes  the Fix's inputs: submit_fixer rebuilds its POST
                      /v2/task/fixer body from these with build_fixer_body, the
                      builder that made `parameters` (which, for a Fix, IS that
                      {mediaId, boxes} body, priced on /v2/task/fixer/price).
    model_version_id  the RESOLVED model version an image gen will submit --
                      the one fact a route needs to tell "no model picked" from
                      "the builder refused something".
    lora_version_ids  the LoRAs actually going out, for the per-account cap and
                      the LoRA telemetry.
    adjusted          the clamp receipt: [{field, asked, used}] for every clamp
                      that FIRED. Clamping is substitution on a paid path, so
                      the route hands it back in the response rather than
                      charging for a different generation in silence.
    unlimited         an Unlimited Mode request that passed _unlimited_check
                      (`parameters` carries lane "infinite"). price() answers it
                      free without a card check and submit() never runs one --
                      and no `no_card` a caller passes can put the card back.
    """
    mode: str = "image"
    parameters: dict = None
    no_card: bool = False
    note: str = None
    price_note: str = None
    media_id: str = ""
    boxes: list = field(default_factory=list)
    model_version_id: str = ""
    lora_version_ids: list = field(default_factory=list)
    adjusted: list = field(default_factory=list)
    unlimited: bool = False


@dataclass
class RequestResolver:
    """The lookups `build_request` cannot do on its own, supplied by the caller.

    model_version(model_id, client_version_id) -> the chosen version ROW (the
                          list_model_versions meta dict: version_id, quality_tag, ...)
                          or a bare version id                  -- needs a session
    preset(user, name) -> banked Toolbox preset dict or None   -- per-account store
    media_id(value)    -> an id PixAI accepts as an INPUT      -- uploads; SUBMIT only
    gate(params)       -> (params, adjusted)                   -- the per-model gate,
                          applied ONCE at build so the quoted, card-matched and
                          submitted dict is one object; `adjusted` is receipt entries
                          [{field, asked, used, why}] (see gate_resolver)
    video_duration(media_id) -> seconds or None                -- a reference video's
                          real length, for referenceVideo.inputVideoDurations
    unlimited(params, version_id) -> lane params               -- the Unlimited Mode
                          check (see unlimited_resolver); absent = a lane request
                          is refused on this road
    features(version_id) -> parsed /features or None           -- Session H: the
                          architecture the creativity shape is decided on, the gate's
                          own cached read (features_resolver); absent = the web
                          payload's `creativity` is not honoured (legacy helper only)

    `media_id` is deliberately absent when pricing. /api/price fires on every
    keystroke in the drawer, and resolving there would upload the same file once
    per character; a quote needs the SHAPE, not an upload-kind id. `gate` and
    `video_duration` are supplied IDENTICALLY to a quote and a spend -- they change
    the shape, so a quote without them would price something the submit never sends.
    """
    model_version: object = None
    preset: object = None
    media_id: object = None
    gate: object = None
    video_duration: object = None
    unlimited: object = None
    features: object = None


def model_version_resolver(session):
    """The ONE model_id -> version_id rule, so a quote and a spend can never
    resolve a picked model differently.

    A client version_id is honored IF it names one of model_id's own real
    versions (PixAI's model cards offer a version picker and so does ours);
    otherwise -- absent, stale from a fast model switch, or belonging to a
    DIFFERENT model entirely -- it falls back to the newest. A raw client
    version_id is never trusted blind: that is what once landed generations on
    PixAI as 'Unknown model'. With no model_id at all the client's version_id
    stands unchanged (back-compat), and a model that resolves to nothing leaves
    it untouched rather than inventing one.

    /api/price used to run a DIFFERENT, weaker resolve of its own (rows[0] via
    resolve_version_meta, and only when the payload carried no version_id and no
    mode at all), which is precisely a badge quoting one model while the submit
    sent another.

    Returns the chosen version ROW (the list_model_versions meta dict, with `version_id`)
    whenever it read the rows, and the plain version-id string otherwise (no model_id, or a
    model that listed nothing). SCOPE_2026-09-26 G4: build_request reads the version's own
    quality tag off that row, so the rule costs no new GET. build_request accepts either
    form, so a resolver that returns a bare id (older callers, test stubs) still works.
    """
    def _resolve(model_id, client_version_id=""):
        mid = str(model_id or "").strip()
        vid = str(client_version_id or "").strip()
        if not mid:
            return vid
        versions = _models.list_model_versions(session, mid)
        chosen = next((v for v in versions if v.get("version_id") == vid),
                      None) if vid else None
        if chosen:
            return chosen
        if versions:
            return versions[0]
        return vid
    return _resolve


def gate_resolver(session):
    """The build-time gate for RequestResolver.gate: params -> (params, adjusted).

    SCOPE_2026-09-26_tsubaki3-parity-fixes: the per-model image gate (_gate_image_params --
    the size grid, the feature strips, a reference as a context image, the MMDIT26B prompt
    helper, the LoRA weight range), bound to `session`, returning the gated dict and one
    receipt entry per change. The SAME function for a quote and a spend: the gallery's
    _price_resolver and _submit_resolver both hand it their session, so the dict /api/price
    prices and card-matches is the dict the submit sends. A refusal raises PixAIError, which
    build_request's callers already render (the badge as its note)."""
    def _gate(params):
        return _models._gate_image_params(session, params)
    return _gate


def _gen_args_from_web_payload(p):
    """Turn the Generate drawer's JSON into the SAME argparse-like namespace the CLI
    feeds to _gen_parameters -- so web + CLI build identical params (one source
    of truth). Clamped to safe ranges, and every clamp that actually fired is listed on
    the returned namespace as `.clamped` = [{field, asked, used}] so the route can tell
    the caller its request was rewritten instead of charging for the difference."""
    from moonglade.backup import PixAIError
    from types import SimpleNamespace
    p = p or {}
    def num(k, d, cast=int):
        try:
            return cast(p.get(k, d))
        except (TypeError, ValueError):
            return d
    # "Clamped to safe ranges" was, until this existed, true of `count` alone: width,
    # height, steps and cfg went through num() with no ceiling and straight into a real
    # paid submit, because _gen_parameters only FLOORS width/height to 64 (via
    # _dim) and caps nothing at all. /api/generate is LOGIN-tier on purpose -- any
    # signed-in LAN device may spend -- so the drawer's own HTML min/max attributes are
    # the only bound a well-behaved client honours and a hand-rolled POST honours none:
    # {"width": 999999999, "steps": 999999} reached PixAI, priced at whatever that
    # produces. Clamp here, where the docstring promises it.
    #
    # The ceilings are read off the drawer's OWN controls, not invented:
    #   width/height  64..4096  -- #gen-cw / #gen-ch (min=64 max=4096 step=8), and the
    #                              drawer's d8() already clamps to exactly that before
    #                              it POSTs, so this is the same number twice
    #   steps         1..150    -- #gen-steps, and gateField()'s defMin/defMax
    #   cfg           1..30     -- #gen-cfg, and gateField()'s defMin/defMax
    # Same idiom _gen_parameters uses for the Hires knobs ("bounds read off the
    # live dialog's own controls: strength 0.01-0.99, steps 1-50").
    #
    # These are NOT provably the widest the UI can emit, and an earlier draft of this
    # comment claimed they were ("a model publishing tighter `restrictions` narrows the
    # browser field further"). gateField() REPLACES the field's min/max with whatever
    # `restrictions` carries rather than clipping them, and `restrictions` is live PixAI
    # data -- so a model publishing samplingSteps.max = 200 would widen the drawer's own
    # control and the drawer would legitimately POST 200.
    #
    # Which is exactly why a clamp that FIRES is recorded instead of applied in silence.
    # Clamping is substitution on a paid path: the caller asked for one generation and
    # is charged for a different one, and doing that without a word is a worse failure
    # than the absurd value the clamp exists to refuse -- the money is gone either way,
    # and only the version that says so tells you what it bought. `adjusted` is that
    # receipt; /api/generate hands it back in the response (see api_generate). No
    # price/charge split comes of it either way: /api/price builds its params through
    # this same function, so the badge already quotes the clamped request.
    adjusted = []

    def clamp(field, v, lo, hi):
        c = max(lo, min(hi, v))
        if c != v:
            adjusted.append({"field": field, "asked": v, "used": c})
        return c
    loras = []
    for lo in (p.get("loras") or []):
        vid = str((lo or {}).get("version_id") or "").strip()
        if vid:
            loras.append((vid, (lo or {}).get("weight", 0.7)))
    seed_raw = str(p.get("seed") or "").strip()
    hp = p.get("high_priority") in (True, "1", "true", "on")
    # Session H (BUILD-w2-gen §1): the drawer's context images, in slot order (slot N is the
    # prompt's @imageN), and its creativity stop. Refused, never repaired: a malformed list or
    # a repeated picture would change the count and the price.
    ctx_raw = p.get("context_images")
    context_images = []
    if ctx_raw not in (None, "", []):
        if not isinstance(ctx_raw, list):
            raise PixAIError("context images must be a list of picture ids")
        for x in ctx_raw:
            v = str(x if x is not None else "").strip()
            if not v.isdigit():
                raise PixAIError("context images must be a list of picture ids")
            context_images.append(v)
        if len(set(context_images)) != len(context_images):
            raise PixAIError("The same picture is in two context slots — remove one")
    creativity = p.get("creativity")
    if creativity in (None, ""):
        creativity = None
    elif creativity not in _models._CREATIVITY_LEVELS:
        raise PixAIError("creativity must be off, low or medium")
    return SimpleNamespace(
        context_images=context_images, creativity=creativity,
        params_json="", prompt=(p.get("prompt") or "").strip(),
        negative=(p.get("negative") or "").strip(),
        model=(p.get("version_id") or "").strip(),
        width=clamp("width", num("width", 512), 64, 4096),
        height=clamp("height", num("height", 512), 64, 4096),
        steps=clamp("steps", num("steps", 25), 1, 150),
        cfg=clamp("cfg", num("cfg", 7, float), 1.0, 30.0),
        count=clamp("count", num("count", 1), 1, 4),
        # Ticked = High (1000, costs extra). Unticked = Turbo (500, free but
        # members-only); core's submit downgrades that to Low on its own if PixAI
        # says this account isn't entitled, so an expired membership no longer
        # breaks every generate/edit/upscale at once.
        priority=(_gen_params.PRIORITY_HIGH if hp else _gen_params.PRIORITY_TURBO),
        mode=(p.get("mode") or "auto"),
        seed=(int(seed_raw) if seed_raw.lstrip("-").isdigit() else None),
        lora=loras,
        # .lower() matters: a JSON `false` arrives as Python False, and
        # str(False) is "False" -- which did NOT match the lowercase tuple, so
        # every explicitly-disabled prompt helper was submitted as ENABLED.
        # Found 2026-07-29 reviewing the pilot's port; it bit the classic
        # drawer's unchecked box identically.
        prompt_helper=(str(p.get("prompt_helper", "1")).lower()
                       not in ("0", "false", "off", "none")),
        ref_media_id=str(p.get("ref_media_id") or "").strip(),
        ref_strength=num("ref_strength", 0.55, float),
        # Upscale + boosters. num() returns its default for a missing/blank value, so
        # None here means "the drawer's Upscale control is Off" and the builder omits
        # every one of these keys -- an absent control must not change the submit.
        enlarge=num("enlarge", None, float),
        enlarge_model=str(p.get("enlarge_model") or "").strip(),
        upscale=num("upscale", None, float),
        upscale_denoising_strength=num("upscale_denoise", None, float),
        upscale_denoising_steps=num("upscale_denoise_steps", None, int),
        face_fix=(p.get("face_fix") in (True, "1", "true", "on")),
        quality_tag=str(p.get("quality_tag") or "").strip(),
        # The Generate drawer's colour palette (Session H 4): cleaned or REFUSED here, before
        # any network call -- a refusal is the badge's note and costs nothing. The gate
        # decides whether it may go out (see _gate_image_params' palette rule).
        color_palette=_gen_params.clean_color_palette(p.get("color_palette")),
        kaisuuken_id="", no_card=bool(p.get("no_card")),
        # _gen_parameters reads named attributes only, so carrying the receipt on
        # the namespace costs the submit shape nothing and keeps it beside the values it
        # describes -- a caller cannot pick up the args and lose the record of what was
        # changed to make them.
        clamped=adjusted)


def _edit_parameters_from_payload(p, user, resolve):
    """Build the instruct-edit `chat` params from the Edit tab's JSON. Source is a
    catalog media_id (the image being edited). A `preset` name swaps in a locally
    banked Toolbox preset (canned prompt + sceneId + its modelId), looked up from
    `user`'s own per-account presets through the caller's `resolve.preset`.
    Returns None if no source (or a preset name that isn't banked).

    `resolve.media_id` is present on a real submit and deliberately absent when
    pricing. With it, every source id is run through the caller's resolver -- a
    catalog id is a generation OUTPUT and PixAI refuses it as an input. Without
    it, ids are left alone: /api/price only needs the SHAPE to compute a cost,
    and uploading on every cost check would upload the same file repeatedly
    while the user types."""
    p = p or {}
    src = str(p.get("source") or "").strip()
    if not src:
        return None
    instruction = (p.get("instruction") or "").strip()
    scene_id, model_id = "", ""
    preset_name = str(p.get("preset") or "").strip()
    if preset_name:
        pre = resolve.preset(user, preset_name) if resolve.preset else None
        if not pre:
            return None
        instruction = pre.get("prompt") or instruction
        scene_id = pre.get("scene_id") or ""
        model_id = pre.get("model_id") or ""
    # A preset pins its own model; otherwise resolve from the Edit-card model picker.
    if not model_id:
        model_id = _gen_params.edit_model_id(p.get("edit_model") or "") or _gen_params.EDIT_PRO_MODEL_ID
    # quality: omitted (passed "") for models with no quality option (Reference Pro);
    # default medium only when the client sent no quality key at all.
    q = p.get("quality")
    if q is None:
        q = "medium"
    # never send an invalid knob; a payload with no aspect takes the model's own default
    # (Edit Pro 3:5, Reference Pro auto) -- SCOPE_2026-09-26 E1.
    res, q, asp = _gen_params.clamp_edit_config(model_id, (p.get("resolution") or "1K"), q,
                                    (p.get("aspect") or _gen_params.edit_default_aspect(model_id)))
    kwargs = dict(resolution=res, aspect_ratio=asp, quality=q, scene_id=scene_id,
                  model_id=model_id)
    # multi-image: sources[] (primary + extra refs) if the client sent them, else [source];
    # capped to the resolved row's OWN reference limit (Edit Pro v1.0 4; Edit Pro V2.0, Edit
    # v4.0 and Reference Pro 10) -- two versions of one model can differ, so never a fixed cap.
    media = p.get("sources")
    media = [str(m).strip() for m in media if str(m).strip()] if isinstance(media, list) else []
    if not media:
        media = [src]
    spec = _gen_params.edit_model_by_id(model_id)
    if spec:
        media = media[:spec["max_refs"]] or [src]
    if resolve.media_id is not None:       # real submit -- see the docstring
        media = [resolve.media_id(m) for m in media]
    return _gen_params.build_chat_edit_parameters(instruction, media, **kwargs)


# What the badge says when PixAI's enhance quote (POST /v2/task/enhance/price, 3.22) gave no
# number it could read, or there is no armed Mirror to ask on.
_ENHANCE_PRICE_NOTE = "couldn't verify the cost of an AI preset yet"

# The READ_ONLY refusal wording per road -- the same sentences submit_generation and
# submit_fixer raise, so moving the guard earlier did not change what a user reads.
_SUBMIT_ACTIONS = {"fix": "submit a hand/face fix (spends credits)"}
_SUBMIT_ACTION_DEFAULT = "submit a generation (spends credits)"


def build_request(payload, *, mode=None, user=None, is_member=None, resolve=None):
    """Turn a web payload into the ONE GenerationRequest that both /api/price and the
    create routes ride. The mode dispatch lives here and nowhere else.

    `mode` pins the road when the CALLER knows it -- a create route is single-purpose,
    and /api/generate must build an image gen whatever the payload says. It matters on a
    spend path: `mode` is overloaded in the payload itself (the image road reads it as
    the inferenceProfile quality setting, "auto"/"lite"/"pro"/...), so an unpinned
    {"mode": "I2V"} POSTed at /api/generate would otherwise build and pay for a VIDEO.
    Omit it and the road is read off the payload -- that is /api/price, the one caller
    that legitimately serves every road.

    `is_member` is the same entitlement the submit applies, so a badge cannot quote a
    price for a members-only option that will be stripped before it is sent. `resolve`
    carries the lookups this cannot do itself (see RequestResolver).

    Raises PixAIError when a BUILDER refuses (asking for both upscale methods at once, an
    unknown video mode): that is a real refusal with a real message, and each caller
    already renders one -- the badge as its note, a create route as its logged failure.
    A payload that is merely INCOMPLETE is not an error: it comes back with `note` set and
    `parameters` None."""
    from moonglade.backup import PixAIError
    p = payload or {}
    rs = resolve if resolve is not None else RequestResolver()
    road = str(mode or p.get("mode") or "").strip()
    no_card = bool(p.get("no_card"))
    # Unlimited Mode is a Tsubaki.3 IMAGE lane. Asked for on any other road it is refused,
    # never quietly ignored into a paid job (SCOPE_2026-09-26_unlimited-mode §2).
    lane = asks_unlimited(p)
    if lane and road in ("edit", "fix", "video", "I2V", "FLF", "R2V", "enhance"):
        raise PixAIError(_UNLIMITED_IMAGE_ONLY)

    if road == "edit":
        params = _edit_parameters_from_payload(p, user, rs)
        if params is not None:
            params = _gen_params.to_wire("edit", params)     # 2.4 rule 2, the last step
        return GenerationRequest(mode="edit", parameters=params, no_card=no_card,
                                 note=None if params else "pick an image to edit")

    if road == "fix":
        # A hand/face Fix is submitted over POST /v2/task/fixer with a body of {mediaId,
        # boxes}, and PixAI prices that very body on POST /v2/task/fixer/price (#93). So
        # `parameters` IS the submit body, from build_fixer_body: price() hands it to
        # price_fixer, and submit() -> submit_fixer rebuilds the same dict from `media_id` +
        # `boxes` with the same builder. A body the builder refuses (no usable box, or face
        # and hand together, which PixAI's server refuses) is a note with no parameters --
        # nothing to price -- and submit_fixer refuses it again, before any network call.
        # (Within ONE request the quote and the spend share the body. The gallery builds two
        # -- /api/price with no media resolver, /api/fix with the uploading one -- so there
        # the boxes are identical and the media id is not: see build_fixer_body.)
        src = str(p.get("source") or "").strip()
        if src and rs.media_id is not None:
            src = str(rs.media_id(src) or src)
        boxes = list(p.get("boxes") or [])
        # no_card is forced True here and is NOT read off the payload: /v2/task/fixer
        # takes only mediaId + boxes, with no kaisuukenId field anywhere on it, so a free
        # card can never be spent on a Fix, and price() never runs the card check for one.
        # Letting it run would paint the badge emerald "FREE -- a card covers this" over an
        # action about to charge full credits.
        if not src:
            return GenerationRequest(mode="fix", no_card=True, boxes=boxes,
                                     note="pick an image to fix")
        try:
            params = _gen_params.build_fixer_body(src, boxes)
        except PixAIError as e:
            note = _gen_params.FIX_ONE_KIND if str(e) == _gen_params.FIX_ONE_KIND else "drag a box over a hand or face"
            return GenerationRequest(mode="fix", parameters=None, no_card=True, media_id=src,
                                     boxes=boxes, note=note)
        return GenerationRequest(mode="fix", parameters=params, no_card=True,
                                 media_id=src, boxes=boxes)

    if road == "video" or road in ("I2V", "FLF", "R2V"):
        shot = str(p.get("mode") or "").strip().upper()
        if shot not in ("I2V", "FLF", "R2V"):
            shot = "R2V"                   # the Loom's own default for an unnamed shot
        imgs = [str(i) for i in (p.get("images") or []) if str(i).strip()]
        # .isdigit() on the video/audio refs is the SUBMIT's filter, and pricing uses it
        # too now: a non-numeric ref was priced and then dropped before the mutation,
        # which is a quote for a different job than the spend.
        vids = [str(v) for v in (p.get("video_refs") or []) if str(v).strip().isdigit()]
        auds = [str(a) for a in (p.get("audio_refs") or []) if str(a).strip().isdigit()]
        # I2V/FLF are image-anchored (source frame / start+end frame); R2V accepts
        # ANY reference kind alone (e.g. a video-only Multi-ref) -- gating all three
        # modes on `imgs` alone silently mispriced a video/audio-only R2V request as
        # "pick a source image", found 2026-07-18 while wiring the ref-slot expansion.
        has_ref = imgs or (shot == "R2V" and (vids or auds))
        if not has_ref:
            return GenerationRequest(mode="video", no_card=no_card,
                                     note="pick a source image")
        vmodel = (p.get("video_model") or "").strip() or _gen_params.DEFAULT_VIDEO_MODEL
        negative = (p.get("negative") or "").strip()
        camera = (p.get("camera_movement") or "")
        adjusted = []
        # Which submit shape build_shot_video_params will take: i2vPro for a framed I2V/FLF,
        # referenceVideo for everything else carrying refs. Only the latter reads the input
        # video lengths, and only the former could have carried a negative or a camera move.
        i2v_road = (shot == "I2V" and imgs) or (shot == "FLF" and len(imgs) >= 2)
        # A length this engine does not take is snapped by build_shot_video_params (6 -> 5 on
        # a Tsubaki engine, 15 -> 10 on a 10 s engine); say so rather than change it silently.
        # The drawer snaps on the client first (applyModelGating), so this is the receipt for
        # a Remix-built or hand-rolled payload (review f-V-F5).
        asked_dur = p.get("duration") or 5
        used_dur = _gen_params._snap_video_duration(asked_dur, vmodel)
        try:
            dur_moved = float(asked_dur) != used_dur
        except (TypeError, ValueError):
            dur_moved = True
        if dur_moved:
            takes = [d for d in _gen_params.video_model_durations(vmodel)
                     if d != 15 or vmodel in _gen_params.VIDEO_15S_MODELS]
            adjusted.append({"field": "duration", "asked": asked_dur, "used": used_dur,
                             "why": "this engine takes {} s".format(
                                 "/".join(str(d) for d in takes))})
        durations = []
        if not i2v_road and vids:
            # V5: each reference video's real length, through the SAME lookup the quote and
            # the spend both carry (RequestResolver.video_duration) -- all or nothing.
            durations, unknown = _gen_params.input_video_durations(vids, rs.video_duration)
            if unknown:
                adjusted.append({"field": "inputVideoDurations", "asked": "measured lengths",
                                 "used": [], "why": _gen_params.INPUT_VIDEO_UNKNOWN_WHY})
        # The Tsubaki Multi-Reference aspect ratio (lane w2-small, 2026-09-28). It rides only the
        # referenceVideo road of a Tsubaki engine (VIDEO_RATIO_MODELS) -- keyed on the ROAD, not
        # the shot mode, since an FLF with one frame goes out as a reference video (spend review
        # N6). Asked for anywhere else it is dropped with a receipt; the drawer never asks there.
        # "adaptive" is PixAI's default and is never sent, so it needs no receipt.
        ratio = str(p.get("ratio") or "").strip()
        if ratio and ratio != "adaptive" and (i2v_road or vmodel not in _gen_params.VIDEO_RATIO_MODELS):
            adjusted.append({"field": "ratio", "asked": ratio, "used": None,
                             "why": "only Tsubaki Video's Multi-Reference takes an aspect ratio"})
            ratio = ""
        if i2v_road:
            # V6: the builder drops both on an engine whose panel has neither; say so.
            if negative and vmodel in _gen_params.VIDEO_NO_NEGATIVE_MODELS:
                adjusted.append({"field": "negativePrompts", "asked": negative, "used": None,
                                 "why": "negative prompt not used by this engine"})
            if camera and camera != "unset" and vmodel in _gen_params.VIDEO_NO_CAMERA_MODELS:
                adjusted.append({"field": "cameraMovement", "asked": camera, "used": None,
                                 "why": "camera not used by this engine"})
        params = _gen_params.build_shot_video_params(
            shot, (p.get("prompt") or "").strip(), image_ids=imgs,
            video_ids=vids, audio_ids=auds,
            duration=p.get("duration") or 5,
            generate_audio=bool(p.get("generate_audio") or p.get("audio")),
            model=(p.get("video_model") or ""),
            camera_movement=camera,
            quality=(p.get("quality") or "professional"),
            audio_language=(p.get("audio_language") or "english"),
            negative=negative,
            is_private=bool(p.get("is_private")),
            use_prompt_helper=bool(p.get("prompt_helper")),
            input_video_durations=durations,
            ratio=ratio)
        # The road-aware wire step (3.22 S3-video-wire): video stays on GraphQL, so this
        # returns the very same object, byte for byte (DESIGN_3.22 2.11, T-F7).
        params = _gen_params.to_wire("video", params)
        return GenerationRequest(mode="video", parameters=params, no_card=no_card,
                                 adjusted=adjusted)

    if road == "enhance":
        src = str(p.get("source") or "").strip()
        if src and rs.media_id is not None:
            src = str(rs.media_id(src) or src)
        wid = str(p.get("workflow_id") or "").strip()
        wname = str(p.get("workflow_name") or "").strip()
        # An enhance never takes a card (3.22, V9/T-F4): no_card is forced True, never read
        # off the payload, and no card check ever runs for one.
        if not src:
            return GenerationRequest(mode="enhance", no_card=True,
                                     note="pick an image first")
        if not (wid or wname):
            return GenerationRequest(mode="enhance", no_card=True, media_id=src,
                                     note="pick an AI preset")
        # 3.22 S3-enhance: the REST route takes {enhanceType, mediaId, prompt?}. The type is
        # the live imageEnhancementPlugins key whose workflowName matches the preset's, as
        # PixAI's site maps it (gen_params.enhance_type_for). A preset addressed only by a
        # numeric workflow id, or one the live config does not list, cannot be mapped: it is
        # a note with no parameters, and nothing is sent (the conservative reading).
        etype = _gen_params.enhance_type_for(wname) if wname else None
        if etype is None:
            return GenerationRequest(mode="enhance", no_card=True, media_id=src,
                                     note=_gen_params.ENHANCE_UNMAPPED)
        # Change Emotion carries a control: the picked expression, translated key -> the
        # danbooru TAG STRING emotionlab wants (unknown key falls back to itself), rides in
        # `prompt` -- and ONLY for the emotion preset.
        emotion_key = str(p.get("emotion") or "").strip()
        emotion_tag = _gen_params.ENHANCE_EMOTION_PROMPTS.get(emotion_key, emotion_key)
        prompt = emotion_tag if emotion_tag and etype == "emotion" else None
        try:
            params = _gen_params.build_enhance_body(src, etype, prompt)
        except PixAIError as e:
            return GenerationRequest(mode="enhance", no_card=True, media_id=src, note=str(e))
        return GenerationRequest(mode="enhance", parameters=params, no_card=True,
                                 media_id=src)

    # --- the image road (the payload's own `mode` is the inferenceProfile here) --------
    args = _gen_args_from_web_payload(p)
    # Session H (BUILD-w2-gen §2): what a context-image request may not carry, refused at build.
    if args.context_images:
        if args.ref_media_id:
            raise PixAIError("Send context images or a reference picture, not both")
        if _gen_params._upscale_ratio(args.enlarge) or _gen_params._upscale_ratio(args.upscale):
            raise PixAIError("An upscale can't carry context images")
        bad = [n for n in _image_refs(args.prompt)
               if n < 1 or n > len(args.context_images)]
        if bad:
            raise PixAIError("The prompt names @image{}, but only {} context image{} {} set"
                             .format(bad[0], len(args.context_images),
                                     "" if len(args.context_images) == 1 else "s",
                                     "is" if len(args.context_images) == 1 else "are"))
    row = None
    if rs.model_version is not None:
        got = rs.model_version(p.get("model_id") or "", args.model)
        if isinstance(got, dict):          # the chosen version ROW (model_version_resolver)
            row = got
            args.model = str(got.get("version_id") or "")
        else:
            args.model = got
    lora_ids = [vid for vid, _w in (args.lora or [])]
    if not args.model:
        return GenerationRequest(mode="image", no_card=args.no_card, note="pick a model",
                                 lora_version_ids=lora_ids, adjusted=args.clamped)
    # Same entitlement the submit applies, so the badge cannot quote a price for a
    # members-only option that will be stripped before it is sent.
    args.is_member = is_member
    # SCOPE_2026-09-26 G4 -- the Quality Tag booster sends the chosen VERSION's own tag, at
    # build time and never in the gate (the gate's version-keyed routes carry no `extra`).
    # Row read with a non-empty half -> that {prefix, suffix}. Row read with none (Tsubaki.3,
    # Flash, Tsubaki.2, some SDXL) -> no qualityTag, as PixAI's own site sends, with a receipt
    # entry because the booster was asked for. No row (no model_id, nothing listed) -> today's
    # literal prefix. The drawer reads the chip disabled for the no-tag case.
    if args.quality_tag and row is not None and "quality_tag" in row:
        qt = row.get("quality_tag")
        if isinstance(qt, dict):
            args.quality_tag_obj = qt
        else:
            args.clamped.append({"field": "qualityTag", "asked": args.quality_tag,
                                 "used": None,
                                 "why": "this model version publishes no quality tag"})
            args.quality_tag = ""
    params = _gen_params._gen_parameters(args)
    adjusted = args.clamped
    # Recipes, step 1 (lanes w2-recipes x w2-gen): the payload's `recipeIds`, validated by
    # moonglade.recipes.recipe_ids_from, onto the BUILT params HERE -- before the creativity
    # step-down below reads them (w2-gen review S3) and before the gate. Refuses a malformed
    # list, a gateless road, and recipes beside context images or on the Upscale road.
    # Returns `params` itself when the payload names none. Design:
    # design/notes/recipes/BUILD-w2-recipes.md.
    from moonglade import recipes as _recipes
    params = _recipes.attach_to_built(params, p, gated=rs.gate is not None)
    # Session H decision 5 -- the creativity stop, shaped at BUILD on the architecture the
    # gate itself reads (rs.features, the same cached /features; review B3). The gate's G6 then
    # relocates naturalPrompts and forces medium beside context images, idempotently.
    if args.creativity is not None:
        _shape_creativity(params, args.creativity, rs, args.model, adjusted)
    # G7 -- ONE gate, applied ONCE, here. The gated dict IS req.parameters: price() prices and
    # card-matches it, submit() attaches the card to it and sends it, and the backstop gates
    # inside price_task/submit_generation return this same object. A gate refusal raises
    # PixAIError like any builder refusal (the badge's note; nothing is spent).
    if rs.gate is not None:
        try:
            params, gate_adjusted = rs.gate(params)
        except PixAIError:
            # A lane request on another version is told so in the lane's own words, not in a
            # gate refusal about its profile (Session H added the gate's unlisted-profile
            # refusal, which a lane request on Flash -- "pro" is not Flash's -- reaches first).
            if lane and rs.unlimited is not None \
                    and str(args.model or "").strip() not in UNLIMITED_VERSIONS:
                raise PixAIError(_UNLIMITED_T3_ONLY)
            raise
        adjusted = list(adjusted) + list(gate_adjusted or [])
        _models._refuse_lost_upscale(args, params)   # an Upscale is never billed as a new generation
    # Recipes, step 2: every forbidden combination checked AGAIN on the dict the gate returned
    # (it can turn a reference into a context image), before the lane check so Unlimited Mode
    # still refuses a recipe. Returns `params` itself when the payload names none, or when
    # step 1's ids rode through the gate as sent.
    params = _recipes.apply_to_params(params, p, gated=rs.gate is not None)
    # Unlimited Mode (SCOPE_2026-09-26_unlimited-mode S3): checked AFTER the one gate and its
    # profile fill, on the dict that will be quoted and sent. A road without the entitlement
    # lookup, or without the gate, cannot vouch for the lane and refuses it (§8.4, §8.10).
    if lane:
        if rs.unlimited is None or rs.gate is None:
            raise PixAIError(_UNLIMITED_UNWIRED)
        params = rs.unlimited(params, args.model)
    # THE SMART REFERENCE SUBMIT, AS PIXAI'S OWN SITE SENDS IT (captured live 2026-10-03, the
    # owner's walk): a context-image edit carries `controlNets: []` and, for one picture, no
    # batchSize. The quote prices this same dict (req.parameters), so the two cannot differ.
    # The source picture's own size is the drawer's (genCore.tsubakiEditState); the gate above
    # already put it on the model's size rule.
    if params.get("contextImages"):
        params.setdefault("controlNets", [])
        if params.get("batchSize") == 1:
            params.pop("batchSize")
    # The road-aware wire step, LAST (DESIGN_3.22 2.4 rule 2): the badge, the card check and
    # the send all see the shape the door sends. On a GraphQL road it returns params itself.
    params = _gen_params.to_wire("image", params)
    return GenerationRequest(mode="image", parameters=params,
                             no_card=args.no_card or lane, model_version_id=args.model,
                             lora_version_ids=lora_ids, adjusted=adjusted, unlimited=lane)


_IMAGE_REF_RE = re.compile(r"@image(\d+)")


def _image_refs(prompt):
    """The @imageN numbers a prompt names, in order (Session H decision 2). The same rule as
    the drawer's tsubakiCore.AT_REF_RE -- dev/tests/test_tsubaki3_generate.py pins the two."""
    return [int(m.group(1)) for m in _IMAGE_REF_RE.finditer(str(prompt or ""))]


def _recipes_in(params):
    """True when the built params carry recipes, read by the recipe lane's one parser."""
    from moonglade import recipes as _recipes
    return bool(_recipes.recipe_ids_from(params))


def _shape_creativity(params, level, rs, version_id, adjusted):
    """Session H decision 5: the web payload's creativity stop onto the params, in place.

    Only on MMDIT26B, decided by the gate's own /features read (review B3). /features
    unreadable -> refuse (a creativity shape PixAI's site would never send beside an unchecked
    architecture). Another architecture -> the legacy on/off shape the builder already made
    stays, with a receipt entry. On MMDIT26B the level is the one asked, EXCEPT: context images
    run it at medium, and recipes run it one step lower (medium -> low, low -> off), as PixAI's
    own builder does (task-*.js). Both are receipt entries. The recipe step lives HERE, at
    build, because the gate must stay idempotent; it reads the BUILT params' recipeIds, so it
    fires only when recipes are really sent (review S3). build_request attaches them before
    this runs (moonglade.recipes.attach_to_built), and they are read here through the same
    parser, moonglade.recipes.recipe_ids_from (recipes review finding 6)."""
    from moonglade.backup import PixAIError
    if rs.features is None:
        return
    feats = rs.features(version_id)
    if feats is None:
        raise PixAIError("Couldn't read this model's settings from PixAI, so its creativity "
                         "can't be set — try again in a minute")
    if feats.get("model_type") != "MMDIT26B_MODEL":
        adjusted.append({"field": "creativity", "asked": level, "used": None,
                         "why": "this model's prompt helper is on or off"})
        return
    used = level
    if params.get("contextImages"):
        used = "medium"
        if level != "medium":
            adjusted.append({"field": "promptHelper", "asked": level, "used": "medium",
                             "why": "a context image runs the prompt helper at medium, as "
                                    "PixAI's own site does"})
    elif level in ("medium", "low") and _recipes_in(params):
        used = "low" if level == "medium" else "off"
        adjusted.append({"field": "promptHelper", "asked": level, "used": used,
                         "why": "recipes run the prompt helper one step lower, as PixAI's "
                                "own site does"})
    params["promptHelper"] = {"creativity": used, "forcePromptHelperDetectionSide": "server"}


def price(session, req, *, card_session=None):
    """The live cost + free-card verdict for a request. READ-ONLY -- it creates nothing
    and spends nothing, and the object it prices is the very `req.parameters` a submit
    would send, which is the whole point of this road.

    Fails CLOSED in both directions: an unbuildable payload is `cost: None` with the note,
    never a `free` a caller could act on; and `free` is card_covers(best), NOT bool(best)
    -- a multi-ticket video can MATCH a card the account holds too few tickets of (issue
    #15), and that case is paid at the full price because the site attaches nothing. One
    predicate shared with the CLI preview and _apply_kaisuuken, so this can never say FREE
    while the submit charges.

    `cards` is the HELD count (kept under its old name for the badge's "(N left)"); the
    job's ticket cost is `cards_needed`, and `card_short` is the honest flag the badge
    renders as "not enough -- costs the full price".

    `adjusted` (SCOPE_2026-09-26 receipts) rides beside the cost whenever the build rewrote
    anything -- a clamp, or the per-model gate's snap/strip/conversion -- so the drawer's and
    the Loom's badges can say so BEFORE a spend. Absent when nothing was changed, the same
    rule /api/generate's response follows (a key on every answer is a key clients ignore).
    The object priced and card-matched here is req.parameters, already gated at build.

    `card_session` (2026-11-18) is the identity the free-card check reads under -- the one the
    send will create on (_apply_kaisuuken checks there, through _session_for_create), so the
    quote and the send cannot disagree about a card. Defaults to `session`, as before."""
    out = _price_answer(session, req, card_session=card_session)
    if req.adjusted:
        out["adjusted"] = list(req.adjusted)
    # The breakdown notes ride a PAID quote only: on a card-covered one "+X" would read as a
    # charge (review N1), and the extra reads would buy nothing.
    if req.mode == "image" and req.parameters is not None and not req.unlimited \
            and out.get("cost") is not None and not out.get("free"):
        out.update(_price_breakdown(session, req.parameters, out["cost"]))
    return out


def _price_breakdown(session, params, cost):
    """Session H: what the badge's one note line says (BUILD-w2-gen "Price"): the context
    images' charge ("N context images +X") and a non-default profile's ("profile Ultra +X"),
    each the difference between this request's price and the same request without it. The
    variant dicts are PRICED only -- never card-checked, never submitted, never cached where a
    submit reads. A read that fails leaves its figure out; nothing here can fail the quote."""
    out = {}
    ctx = params.get("contextImages")
    if isinstance(ctx, list) and ctx:
        out["context_images"] = len(ctx)
        base = _pricing.price_task(session, {k: v for k, v in params.items() if k != "contextImages"})
        if base is not None and cost - base >= 0:
            out["context_charge"] = cost - base
    prof = str(params.get("inferenceProfile") or "").strip()
    if prof:
        try:
            rows = _models._model_profiles(session, params.get("modelId")) or []
        except Exception:
            rows = []
        default = next((str(r.get("profileName") or "").strip() for r in rows
                        if isinstance(r, dict) and r.get("profileFlag") == "default"), "")
        mine = next((r for r in rows if isinstance(r, dict)
                     and str(r.get("profileName") or "").strip() == prof), None)
        if default and mine is not None and prof != default:
            out["profile"] = str(mine.get("title") or prof)[:40]
            alt = _pricing.price_task(session, dict(params, inferenceProfile=default))
            if alt is not None and cost - alt >= 0:
                out["profile_extra"] = cost - alt
    return out


def _price_answer(session, req, card_session=None):
    """price()'s verdict, minus the receipt (see price)."""
    if req.parameters is None:
        return {"cost": None, "free": False, "note": req.note}
    if req.price_note:
        return {"cost": None, "free": False, "note": req.price_note}
    if req.mode == "enhance":
        # 3.22 S3-enhance (T-F4, V9): PixAI's own enhance quote on the identity that runs the
        # job (the Mirror's stored sign-in, no renewal), never a card check, never FREE. A
        # failed or unrecognised quote is no number, in the badge's own words.
        cost = _pricing.price_enhance(_pricing.enhance_quote_session(), req.parameters)
        out = {"cost": cost, "free": False, "cards": None, "cards_held": None,
               "cards_needed": None, "card_short": False, "card_name": None,
               "card_template": None, "card_expires": None}
        if cost is None:
            out["note"] = _ENHANCE_PRICE_NOTE
        return out
    if req.mode == "fix":
        # #93: a Fix is priced by PixAI's own Fix price route off the exact submit body
        # (req.parameters IS that body). Never a card check -- no card can cover a Fix --
        # and a failed quote is cost None with no number from anywhere else.
        q = _pricing.price_fixer(session, req.parameters)
        boxes = req.parameters.get("boxes") or []
        out = {"cost": q["cost"] if q else None, "free": False,
               "cards": None, "cards_held": None, "cards_needed": None, "card_short": False,
               "card_name": None, "card_template": None, "card_expires": None,
               "fix_pass": boxes[0]["tag"] if boxes else None, "fix_boxes": len(boxes)}
        if q and q.get("original") is not None and q["original"] > q["cost"]:
            out["original_cost"] = q["original"]
        return out
    if req.unlimited:
        # S4: free by the entitlement, never by a card -- no /v2/kaisuuken/check at all. The
        # list price rides along as `list_cost` when /v2/task-price answers (what PixAI's
        # price route says of a lane request is unobserved; the verdict does not depend on it).
        out = {"cost": 0, "free": True, "unlimited": True}
        listed = _pricing.price_task(session, req.parameters)
        if listed is not None:
            out["list_cost"] = listed
        return out
    cost = _pricing.price_task(session, req.parameters)
    recipes = bool(req.parameters.get("recipeIds"))
    if recipes:
        # Lane w2-recipes: a failed quote with recipes is PixAI's refusal (RECIPE_*) or
        # "couldn't verify" -- and the card check is skipped, so FREE needs a read price.
        from moonglade import recipes as _recipes
        verdict = _recipes.price_verdict(session, req.parameters, cost)
        if verdict is not None:
            return verdict
    best = None if req.no_card else _cards.match_kaisuuken(card_session or session, req.parameters,
                                                    enrich=True)
    covered = _cards.card_covers(best)
    out = {"cost": cost, "free": covered,
           "cards": (best or {}).get("total"),
           "cards_held": (best or {}).get("total"),
           "cards_needed": (best or {}).get("consumeAmount"),
           "card_short": bool(best) and not covered,
           "card_name": (best or {}).get("name"),
           # The Loom's batch tally keys its per-template ticket pool on this (falls
           # back to card_name when absent) -- see loom-core.js tallyPricesDetailed.
           "card_template": (best or {}).get("templateId"),
           "card_expires": (best or {}).get("expiresAt")}
    if recipes and covered:
        out["card_note"] = _recipes.CARD_NOTE    # a card over a recipe's LoRAs: unobserved
    return out


def submit(session, req, *, no_card=None, before_send=None, on_send=None, exact=False,
           on_created=None):
    """Spend: READ_ONLY guard -> free card -> the one mutation this road's mode uses.
    Returns {"task_id": ...}.

    Session M (BUILD-w5-m s3.4): `before_send(params)` runs after the card step and before
    submit_generation on EVERY branch that reaches it (the lane branch too, review F13b); it
    may raise to stop, and nothing has been sent when it does -- a run's budget check lives
    there. `on_send` and `exact` are handed to submit_generation (see it). All three default
    to today's behaviour, byte for byte.

    The READ_ONLY check is FIRST, ahead of the card match, and that ordering is the point
    of putting it here. `_apply_kaisuuken` calls /v2/kaisuuken/check -- a real network
    call on the account -- and every web create route used to make it before reaching
    submit_generation's own guard, so a READ_ONLY install still talked to PixAI before
    refusing. That is the identical fail-open the four CLI runners were fixed for on
    2026-07-21; the web side kept it until this became one choke.

    `no_card` overrides the request's own flag for a caller with a reason to (the
    request's flag is what the payload asked for). A Fix ignores both: POST /v2/task/fixer
    has no kaisuukenId field at all, so no card can ever cover one, and this never runs
    the check that would tell a user otherwise."""
    from moonglade.backup import _check_read_only, PixAIError
    _check_read_only(_SUBMIT_ACTIONS.get(req.mode, _SUBMIT_ACTION_DEFAULT))
    if req.mode == "fix":
        # A Fix's `parameters` are the submit body build_fixer_body made for the price.
        # submit_fixer rebuilds the same body from `media_id` + `boxes` with that same
        # builder, after its own READ_ONLY check, and is the real guard: a body the builder
        # refuses (no usable box, two kinds) raises there before any network call. What
        # this cannot do without is the two inputs that body is built from.
        if not req.media_id or not req.boxes:
            raise PixAIError(req.note or "nothing to submit")
        # `on_send` (a run's) is told just before the one POST, as on the generation road, so
        # a caller knows whether the spend was reached (3.21.2, L1). Observation only; passed
        # only when asked for, so a default Fix calls submit_fixer exactly as before.
        return {"task_id": submit_fixer(session, req.media_id, req.boxes,
                                        **({"on_send": on_send} if on_send is not None else {}))}
    if req.parameters is None:
        raise PixAIError(req.note or "nothing to submit")
    if req.mode == "enhance":
        # 3.22 S3-enhance (T-F4): no card step at all -- no /kaisuuken/check, no card -- and
        # the send only on the Mirror's web sign-in (submit_enhance). before_send still runs
        # last before the send, as on every other branch.
        if before_send is not None:
            before_send(req.parameters)
        return {"task_id": submit_enhance(session, req.parameters,
                                          **({"on_send": on_send} if on_send is not None
                                             else {}))}
    kind = _REQUEST_KINDS.get(req.mode, req.mode)
    # V8 (DESIGN_3.22 2.5): the identity is chosen ONCE, here, after READ_ONLY; the card check,
    # before_send's card test and the send all see this one client. A Mirror toggle moved after
    # this line changes nothing in this send.
    from moonglade import pixai_client as _pixai_client
    session = _pixai_client._client_of(session).for_create()
    if req.unlimited:
        # S5: the card step is skipped outright for a lane request -- keyed on req.unlimited,
        # which the `no_card` argument cannot override (§8.10). submit_generation guards the
        # params' own `lane` too, for every road that reaches it (§8.3).
        if before_send is not None:
            before_send(req.parameters)
        return {"task_id": submit_generation(session, req.parameters,
                                             **_send_kwargs(on_send, exact, kind, on_created))}
    from types import SimpleNamespace
    skip = req.no_card if no_card is None else bool(no_card)
    # Passing the flag through rather than branching around the call keeps
    # _apply_kaisuuken's own precedence (explicit id > no_card > auto-match) and its
    # spend log ("--no-card: this WILL spend credits") the single source of both.
    _cards._apply_kaisuuken(session, req.parameters,
                     SimpleNamespace(kaisuuken_id="", no_card=skip))
    if before_send is not None:
        before_send(req.parameters)
    return {"task_id": submit_generation(session, req.parameters,
                                         **_send_kwargs(on_send, exact, kind, on_created))}


#: GenerationRequest.mode -> the door/road kind (CREATE_ROAD's key). The kind always comes
#: from the request's own mode, never from its parameters (V10).
_REQUEST_KINDS = {"image": "image", "edit": "edit", "video": "video", "enhance": "enhance"}


def _send_kwargs(on_send, exact, kind="image", on_created=None):
    """submit_generation's keywords, each passed only when it differs from the default: a
    default image submit calls it exactly as it always did."""
    kw = {}
    if on_send is not None:
        kw["on_send"] = on_send
    if exact:
        kw["exact"] = True
    if kind != "image":
        kw["kind"] = kind
    if on_created is not None:
        kw["on_created"] = on_created
    return kw


# Session M: the pause between one answered mutation and the next in a run ("be polite to
# their servers"; the Loom's batch staggers 2.2 s). Nothing waits for a task to FINISH.
RUN_SEND_GAP_S = 1.5


def _run_budget_note(sent):
    return ("The free card expected for image {} was used elsewhere, so it would cost more "
            "than you confirmed. {} {} sent; the rest were not.".format(
                sent + 1, sent, "was" if sent == 1 else "were"))


def _paid_quota(answer):
    """PixAI's charge on a task answer (REST `paidQuota`, GraphQL `paidCredit`), or 0."""
    if not isinstance(answer, dict):
        return 0
    for k in ("paidQuota", "paidCredit", "paid_credit"):
        v = answer.get(k)
        try:
            if v is not None and not isinstance(v, bool):
                return float(v)
        except (TypeError, ValueError):
            continue
    return 0


def _card_unproven(req):
    """True while a card on this request's road is not yet proven free (2.4 rule 7): the
    request rides the create door and R8 has not passed."""
    kind = _REQUEST_KINDS.get(getattr(req, "mode", ""), getattr(req, "mode", ""))
    return CREATE_ROAD.get(kind) == "rest" and not CARD_PROOF_ON_REST


def _card_job_was_charged(session, task_id):
    """One read of a card job's task before the next job goes (2.4 rule 7): True only when
    PixAI shows a charge on it. Read-only and fail-soft (a failed read is False)."""
    try:
        from moonglade import task_reads as _task_reads
        st = _task_reads.generation_status(session, task_id) or {}
        return _paid_quota({"paidCredit": st.get("paid_credit")}) > 0
    except Exception:                                        # noqa: BLE001
        return False


def send_run(session, jobs, *, hooks, budget=None, gap_s=None, sleep=None):
    """THE run sender (Session M, BUILD-w5-m s4): a run's jobs, strictly one after another,
    each through submit() -- READ_ONLY first, the card step, the budget check, then
    submit_generation(exact=True), whose one gql_mutate is the only mutation a job can make.
    The FIRST failure stops the rest; nothing is retried or resent.

    `jobs`   [{"cell": int, "req": GenerationRequest, "no_card": True | None}] -- the very
             objects the run quoted; nothing is rebuilt here.
    `budget` {"each": credits per job, "total": the confirmed total} or None. Before each
             job without a card: charged-so-far + each > total stops the run before that
             job (a card spent in another tab, a card that expired). None = a single send,
             which has no confirmed total (review F11): no check, the card auto-applies.
    `hooks`  the Runs store's side, each call guarded here:
               sending(cell)                        committed BEFORE the job's submit; if it
                                                    raises, the run stops, nothing more sent
               sent(cell, task_id, request, card)   after the mutation; a raise is swallowed
                                                    (the task exists; the answer carries it)
               failed(cell, state, error, request)  a job that did not go out cleanly
    Returns {"status": "sent"|"stopped", "reason"?, "jobs": [{cell, state, task_id?, card,
             error?, recipe_error?}]} with state sent | refused | may_have_started | not_sent.

    State after a failure (s4.4): an exception before on_send fired means the mutation was
    never reached -> not_sent; after it, a definite refusal (a GraphQL error, a 401, a local
    refusal) -> refused; anything else (a timeout, a dropped connection, a 5xx, no task id)
    -> may_have_started, never resent and never counted as refused."""
    from moonglade.backup import LocalRefusal
    from moonglade import recipes as _recipes
    gap = RUN_SEND_GAP_S if gap_s is None else gap_s
    pause = sleep if sleep is not None else time.sleep
    out = []
    state = {"charged": 0, "sent": 0, "stop": None, "card_pending": None,
             "card_ignored": False}

    for idx, job in enumerate(jobs):
        cell = job["cell"]
        if state["stop"] is not None:
            out.append({"cell": cell, "state": "not_sent", "card": False})
            continue
        if idx and gap:
            pause(gap)
        try:
            hooks.sending(cell)
        except Exception:                                    # noqa: BLE001
            state["stop"] = ("Couldn't record cell {} before sending it, so it and the rest "
                             "were not sent.".format(cell + 1))
            out.append({"cell": cell, "state": "not_sent", "card": False})
            continue
        seen = {"request": None, "answer": None}

        def _on_send(variables):
            seen["request"] = variables

        def _on_created(answer):
            seen["answer"] = answer

        def _before(params):
            # A card job skips the check -- unless a card in this run was already shown not to
            # apply (2.4 rule 7): from then on every job is held to the confirmed total.
            if budget is None or (params.get("kaisuukenId") and not state["card_ignored"]):
                return
            if state["charged"] + int(budget["each"]) > int(budget["total"]):
                raise LocalRefusal(budget.get("note") or _run_budget_note(state["sent"]))

        if budget is not None and state["card_pending"] is not None:
            # 2.4 rule 7 (V3), before the next job: the last card job's task read once more,
            # and counted as charged when PixAI now shows a charge on it. Fail-soft: a failed
            # read proves nothing either way and counts nothing.
            if _card_job_was_charged(session, state["card_pending"]):
                state["charged"] += int(budget["each"])
                state["card_ignored"] = True
            state["card_pending"] = None
        try:
            task_id = submit(session, job["req"], no_card=job.get("no_card"),
                             before_send=_before, on_send=_on_send, exact=True,
                             on_created=_on_created)["task_id"]
        except Exception as e:                               # noqa: BLE001
            reached = seen["request"] is not None
            if not reached:
                st = "not_sent"
            elif getattr(e, "refused", False) or definite_refusal(e):
                st = "refused"
            else:
                st = "may_have_started"
            refusal = _recipes.refusal_from(e) if reached else None
            msg = refusal["copy"] if refusal else _graphql_reason(e)
            rec = {"cell": cell, "state": st, "card": False, "error": str(msg)[:300]}
            if refusal:
                rec["recipe_error"] = refusal
            out.append(rec)
            try:
                hooks.failed(cell, st, rec["error"], seen["request"])
            except Exception:                                # noqa: BLE001
                pass
            state["stop"] = rec["error"]
            continue
        card = bool((seen["request"] or {}).get("kaisuukenId"))
        if not card and budget is not None:
            state["charged"] += int(budget["each"])
        elif card and budget is not None and _card_unproven(job["req"]):
            # 2.4 rule 7 (V3): until R8 has proven a card free on the REST create, a card job
            # whose create answer shows a charge counts as charged at its quoted full price, so
            # a run can never pay past its confirmed total because PixAI ignored a card.
            if _paid_quota(seen["answer"]) > 0:
                state["charged"] += int(budget["each"])
                state["card_ignored"] = True
            else:
                state["card_pending"] = str(task_id)
        state["sent"] += 1
        out.append({"cell": cell, "state": "sent", "task_id": str(task_id), "card": card})
        try:
            hooks.sent(cell, str(task_id), seen["request"], card)
        except Exception:                                    # noqa: BLE001
            pass
    res = {"status": "stopped" if state["stop"] is not None else "sent", "jobs": out}
    if state["stop"] is not None:
        res["reason"] = state["stop"]
    return res


# =============================================================================
# end of the one payload road
# =============================================================================


def collect_generation(session, task_id, out_dir, *, name_length=60, name_sep="_"):
    """Download + catalog a COMPLETED task's output(s) into out_dir -> {media_ids, saved,
    is_video}. Auto-detects video (outputs.videos) vs image and uses the matching shared
    downloader. Call only once status is 'done'."""
    from moonglade.backup import extract_full_meta, _fill_preset_defaults, init_db, video_outputs
    from moonglade.gen_cli import (_download_image_task, _download_video_task, _task_detail_query,
                                   _task_image_media)
    from types import SimpleNamespace
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    init_db(out / "catalog.db")
    result = _task_detail_query(session, task_id) or {}
    a = SimpleNamespace(name_length=name_length, name_sep=name_sep)
    vouts, _shared = video_outputs(result)
    if vouts:
        # Hand the downloader the task's OWN submitted parameters, the way the submit paths
        # hand it theirs. video_outputs reads only the referenceVideo block, so with an empty
        # dict here a plain image-to-video (i2vPro) had nothing to read: every clip collected
        # through this path -- the ordinary Video tab case -- was cataloged with a blank
        # prompt, negative prompt, duration and model.
        saved = _download_video_task(session, result, task_id, out, a,
                                     result.get("parameters") or {})
        mids = [str(o["video_media_id"]) for o in vouts if o.get("video_media_id")]
        # Real clip length for the reel. media_tools.duration answers at full precision;
        # the 2dp are this call site's own display choice (the catalog's video_duration
        # column is read back as a label, not re-measured).
        _dur = _media_tools.duration(saved[0]) if saved else None
        dur = round(_dur, 2) if _dur is not None else None
        return {"media_ids": mids, "saved": len(saved), "is_video": True, "duration": dur}
    fm = extract_full_meta(result)
    _fill_preset_defaults(session, fm, result)   # issue #18: model-preset steps/sampler/cfg
    saved = _download_image_task(session, result, task_id, out, a, prompt=fm.get("prompt_full", ""))
    # the real images (batch individuals, not the composite grid)
    mids = [mid for mid, _seed in _task_image_media(result.get("outputs") or {})]
    return {"media_ids": mids, "saved": len(saved), "is_video": False}




# PixAI's own "rejected" list: the 20 codes its site's create flow (useHeldTaskPrice `ye`)
# treats as "no task was made" (DESIGN_3.22 1.3). Every other code it may answer is, to the
# site as to this app, an UNKNOWN outcome.
PIXAI_REJECTED_CODES = frozenset({
    "FORBIDDEN", "BAD_REQUEST", "INVALID_INPUT", "MODEL_DEPRECATED", "TOO_MANY_REQUESTS",
    "INVALID_PARAMETERS_COMPATIBILITY", "NO_PERMISSION_FOR_GENERATION", "REQUIRE_T_2_MEMBERSHIP",
    "INSUFFICIENT_BALANCE", "WAITING_NUM_EXCEEDED", "WATERMARK_NOT_AVAILABLE",
    "NSFW_PROMPTS_DETECTED", "NSFW_PROMPTS_DETECTED_ADULT_NOT_SET", "NO_PERMISSION_FOR_PREVIEW",
    "NO_PERMISSION_FOR_EARLY_ACCESS", "KAISUUKEN_NOT_AVAILABLE", "KAISUUKEN_NOT_ALLOWED",
    "RECIPE_UNAVAILABLE", "RECIPE_INCOMPATIBLE", "REQUIRE_MEMBERSHIP",
})
# The codes a spend reads as "refused, nothing made" (DESIGN_3.22 2.6): PixAI's list above, and
# three the create route answers before any task exists -- the credential is checked before the
# handler runs (UNAUTHORIZED), the schema before it (VALIDATION_ERROR), and the site's own form
# checks the lane entitlement before it submits (INFINITE_MODE_NOT_ELIGIBLE). Promoting another
# code needs evidence and a design note: "unknown" costs a held button, never money.
DEFINITE_CODES = PIXAI_REJECTED_CODES | {"UNAUTHORIZED", "VALIDATION_ERROR",
                                         "INFINITE_MODE_NOT_ELIGIBLE"}
# The training routes' family (DESIGN_3.22 2.6, V5): PixAI's list plus every code the training
# routes declare in their error maps (harvest 938fb68efeea `trainingTask-DTATiVlJ.js`). Each
# refuses the request against the task's current state, so no new run exists after it -- a clear
# training refusal never holds Start, Describe or Retry. Never used for a create.
TRAINING_CODES = PIXAI_REJECTED_CODES | {
    "BAD_REQUEST", "INVALID_INPUT", "UNAUTHORIZED",                 # request and auth
    "NOT_FOUND", "FORBIDDEN", "CONFLICT",                           # the task
    "TRAINING_IMAGE_REJECTED", "TRAINING_DATASET_TOO_SMALL",         # the dataset
    "MODEL_PUBLISH_CONFLICT", "LORA_REBATE_REQUIRES_PUBLIC",         # publishing
    "INSUFFICIENT_BALANCE",                                          # credits
}
# `codes=ANY_PIXAI_CODE`: any code in PixAI's oRPC error body is a refusal -- for a non-spend
# write whose route answers its own codes before it acts and whose caller reads the outcome
# back (the inbox: mark read, reply, delete a reply, claim a gift). A spend never uses it.
ANY_PIXAI_CODE = None
# A REST timeout (408) or a closed-request (499) answer is never a refusal, whatever its body
# says: PixAI, or an edge in front of it, may have accepted the request before it said so.
_UNKNOWN_OUTCOME_STATUSES = frozenset({408, 499})
# The definite-code table per route family (DESIGN_3.22 2.6, V5): `classify_outcome(e, family)`
# takes the family of the route that answered. The fixer route's own error map is stripped from
# PixAI's contract and its site sorts the Fix's refusals with the same `ye` list, so `fixer`
# reads DEFINITE_CODES; training reads its own table, and never the create one.
OUTCOME_FAMILIES = {"create": DEFINITE_CODES, "fixer": DEFINITE_CODES,
                    "training": TRAINING_CODES}

# ONE ROAD PER KIND (DESIGN_3.22 2.11): which road each create kind is sent on, in this build.
#   "graphql"    createGenerationTask (image, edit, video, reference video) or
#                createChatEditingSceneTask (scene) through gql_mutate
#   "rest"       THE create door, PixAIClient.create (core._create)
#   "rest_post"  the Fix's own POST /v2/task/fixer through rest_post, until the door takes it
# Each kind moves in its own commit, its web and CLI senders together (V6); a test pins one
# reachable sender per kind. There is no fallback between roads and no setting: rolling back
# means installing the previous release. Video and reference video stay on GraphQL (owner,
# 2026-11-19); enhance cannot use /task/create, so it moves regardless.
CREATE_ROAD = {
    "image": "rest",
    "edit": "rest",
    "scene": "rest",
    "enhance": "rest",
    "fix": "rest",
    "video": "graphql",
    "refvideo": "graphql",
}


def classify_outcome(exc, codes=DEFINITE_CODES):
    """What a failed send's exception proves: "local" (refused HERE, nothing sent), "refused"
    (PixAI answered no, so nothing was created or charged) or "unknown" (it may exist and may be
    charged: a spend guard reads it as "may have started").

    It reads the exception's TYPE and structured fields only, never its message text
    (DESIGN_3.22 2.6; the 3.21.2 fix L2):
      - LocalRefusal: local.
      - PixAIRestError: refused only when the status is a 4xx other than 408 and 499 AND the
        body is PixAI's oRPC error (a JSON object with a string `code`) whose code is in
        `codes`. A bare 4xx (an edge's page, no PixAI body), a 3xx, a 5xx and any other code:
        unknown. `codes=None` accepts any PixAI code -- for a route whose own codes are all
        answered before it acts and whose outcome the caller reads back (the inbox's).
      - PixAIAuthError (the GraphQL road's 401): refused.
      - a GraphQL error (the transport hangs the `errors` list on it as `graphql_errors`):
        refused only when its `data` resolved nothing. A root field that came back non-null
        beside `errors` is a PARTIAL SUCCESS -- the task exists and may be charged (waves 2+3
        review, F2) -- so it is unknown.
      - CreateOutcomeUnknown (the create door's answer that proves nothing): unknown.
      - anything else (a timeout, a dropped connection, a non-JSON or id-less answer): unknown.

    `codes` is a code table, None (any PixAI code), or a route family's name from
    OUTCOME_FAMILIES ("create", "fixer", "training")."""
    from moonglade.backup import (LocalRefusal, PixAIAuthError, PixAIError, PixAIRestError,
                                  PixAIOutcomeError)
    if isinstance(codes, str):
        codes = OUTCOME_FAMILIES[codes]
    if isinstance(exc, PixAIOutcomeError):
        return "unknown"
    if isinstance(exc, LocalRefusal):
        return "local"
    if isinstance(exc, PixAIRestError):
        try:
            status = int(exc.status)
        except (TypeError, ValueError):
            return "unknown"
        if not 400 <= status < 500 or status in _UNKNOWN_OUTCOME_STATUSES:
            return "unknown"
        body = exc.body
        code = body.get("code") if isinstance(body, dict) else None
        if not isinstance(code, str) or not code:
            return "unknown"
        return "refused" if (codes is None or code in codes) else "unknown"
    if isinstance(exc, PixAIAuthError):
        return "refused"
    if isinstance(exc, PixAIError):
        errors = getattr(exc, "graphql_errors", None)
        if isinstance(errors, list) and errors:
            partial = getattr(exc, "graphql_data", None)
            if isinstance(partial, dict) and any(v is not None for v in partial.values()):
                return "unknown"
            # 3.21.2 review: an `errors` answer with no data is a refusal ONLY when every error
            # names a definite code. An INTERNAL_SERVER_ERROR, an "upstream request timeout"
            # with no code, or any code outside the table may sit in front of a task PixAI made.
            for err in errors:
                code = graphql_error_code(err)
                if code is None or (codes is not None and code not in codes):
                    return "unknown"
            return "refused"
    return "unknown"


# A numeric GraphQL code with a known name. Evidence: 40300047 is PixAI's members-only refusal
# (private/CLASS4_PROBE_2026-07-28.md section 6, live 403s; the Turbo resubmit has keyed on it
# since 2026-07, DESIGN_3.22 2.7). Other numbers seen (40300027 LORA_NUM_EXCEEDED, 40300032
# NSFW_DETECTED) name codes outside the definite tables, so they are left unknown.
_GRAPHQL_NUMERIC_CODES = {40300047: "REQUIRE_MEMBERSHIP"}


def graphql_error_code(err):
    """One GraphQL error's code name, or None. Read where PixAI's own site reads it
    (errorUtil `c`: `errors[i].extensions.exception.name`), then `extensions.code`, then a
    top-level `code`; a known numeric code is mapped to its name. Never the message."""
    if not isinstance(err, dict):
        return None
    ext = err.get("extensions") if isinstance(err.get("extensions"), dict) else {}
    exc = ext.get("exception") if isinstance(ext.get("exception"), dict) else {}
    for raw in (exc.get("name"), exc.get("code"), ext.get("code"), err.get("code")):
        if isinstance(raw, str) and raw:
            return raw
        if isinstance(raw, int) and not isinstance(raw, bool) and raw in _GRAPHQL_NUMERIC_CODES:
            return _GRAPHQL_NUMERIC_CODES[raw]
    return None


def outcome_reason(exc):
    """PixAI's own reason for a failed send, in a short line for the user beside "may have
    started" (an NSFW_DETECTED or INPUT_IMAGE_TOO_LARGE that is not a definite refusal, an
    expired sign-in's 401): the oRPC code and message, the GraphQL errors' messages and codes,
    else the exception's text. Display only -- never an input to classify_outcome."""
    from moonglade.backup import PixAIError, PixAIRestError
    if isinstance(exc, PixAIRestError):
        f = exc.fields
        code = f.get("code") if isinstance(f.get("code"), str) else ""
        text = f.get("message") if isinstance(f.get("message"), str) else ""
        head = "HTTP {}".format(exc.status) if exc.status is not None else "PixAI"
        if code or text:
            return "{}: {}".format(head, " -- ".join(x for x in (code, text.strip()) if x))
        return "{}: {}".format(head, str(exc).split(": ", 1)[-1][:200])
    errors = getattr(exc, "graphql_errors", None)
    if isinstance(errors, list) and errors:
        bits = []
        for e in errors:
            if isinstance(e, dict):
                code = graphql_error_code(e)
                msg = str(e.get("message") or "").strip()
                bits.append(msg + (" ({})".format(code) if code else ""))
        if any(bits):
            return "; ".join(b for b in bits if b)
    return "{}: {}".format(type(exc).__name__, str(exc)) if not isinstance(exc, PixAIError) \
        else str(exc)


def definite_refusal(exc, codes=DEFINITE_CODES):
    """True when nothing was created or charged: refused here before the network call
    (LocalRefusal: READ_ONLY, the request's own validation) or refused by PixAI in a way that
    proves no task exists. False for anything that may have reached PixAI and succeeded,
    which a spend guard must treat as "may have started". The rule is classify_outcome's."""
    return classify_outcome(exc, codes) in ("local", "refused")


def send_outcome(exc, reached):
    """A single send's state after `exc`: "not_sent" when the one spend request was never
    reached (`reached` False: everything before it is local or a read), else "refused" when
    the answer proves nothing was made (definite_refusal, or a refusal this app re-raised with
    `refused = True` after that same check), else "may_have_started"."""
    if not reached:
        return "not_sent"
    if getattr(exc, "refused", False) is True or definite_refusal(exc):
        return "refused"
    return "may_have_started"


# What a command-line single send prints when its answer cannot show whether a task was made
# (DESIGN_3.22 2.12). No catch-up runs for a CLI user, so it never promises one.
CLI_UNCLEAR = ("PixAI may have started this (task not confirmed). Check pixai.art or run "
               "--sync before running this again.")


class SendOutcomeUnclear(Exception):
    """A command-line single send that reached PixAI and got no answer that proves either
    way: the task may exist and may be charged. The message is CLI_UNCLEAR and the cause is
    chained. Deliberately NOT a PixAIError (DESIGN_3.22 2.2), so no guard that reads "a plain
    PixAIError was raised before the send" can ever mistake it for nothing-sent; main() exits
    non-zero on it."""


def _cli_send_once(send, reached=lambda: True):
    """Run a CLI runner's ONE send. A refusal comes back as it came (PixAI's words); an
    unknown outcome after the send was reached raises SendOutcomeUnclear. Never re-sends."""
    try:
        return send()
    except Exception as e:                                   # noqa: BLE001 -- re-raised below
        if send_outcome(e, reached()) != "may_have_started":
            raise
        detail = "{}: {}".format(type(e).__name__, str(e)[:200]).strip()
        raise SendOutcomeUnclear(CLI_UNCLEAR + "\n  PixAI's answer: " + detail) from e


def _cli_create_once(create_session, params):
    """The video, reference-video and edit runners' ONE createGenerationTask, through
    gql_mutate (single attempt, never a redirect). Returns the task id. An answer with no id
    is as unclear as a lost one, so it is raised inside the send and reads unclear too."""
    from moonglade.backup import gql_mutate, PixAIError
    def _send():
        created = gql_mutate(create_session, _GEN_MUTATION, {"parameters": params})
        task_id = (created.get("createGenerationTask") or {}).get("id")
        if not task_id:
            raise PixAIError("no task id returned: " + json.dumps(created)[:300])
        return task_id
    return _cli_send_once(_send)


def _cli_door_once(create_client, kind, params):
    """A CLI runner's ONE create through THE create door (3.22): core._create(kind, params)
    on the client for_create chose, the observation step on its answer, and the task id back.
    An unknown outcome after the send was reached raises SendOutcomeUnclear; a refusal comes
    back as it came. Never re-sends."""
    from moonglade import backup as _core
    mark = spend_watch()

    def _send():
        _mark_spend_reached()
        answer = _core._create(create_client, kind, params)
        _observe_created(kind, params, answer)
        return str(answer["id"])
    return _cli_send_once(_send, reached=lambda: mark.v)


# =============================================================================
# THE GALLERY'S SPEND RULES, as plain functions (DESIGN_3.22 3.4, step S2b)
# =============================================================================
# These lived inside create_app's route closures. They are spend rules, so they live here,
# beside the road they guard, and the later Phase 4 route moves can be pure moves with no
# second spend review. The routes keep their wording and call these.

# --- the FREE-quote rule (2026-11-18) ----------------------------------------
# A gallery send whose cost badge said FREE carries `expect_free`. The card is matched again
# at send time (_apply_kaisuuken); if the card the quote found is gone by then, sending would
# charge a price nobody was shown, so that case is refused before anything goes out. A send
# whose badge showed a PRICE carries nothing and goes out exactly as before.
QUOTED_FREE_GONE = ("The free card this was priced with is gone (used elsewhere or "
                    "expired), so sending it would spend credits. Nothing was sent. "
                    "Check the price again before you send.")


def pop_expect_free(body):
    """The client's 'my badge said FREE' flag, popped so it never reaches build_request, the
    single-send record or PixAI."""
    return bool(body.pop("expect_free", False)) if isinstance(body, dict) else False


def refuse_if_quoted_free_gone(params, message=QUOTED_FREE_GONE):
    """The rule itself: a send quoted FREE goes out only with a card attached. Raises
    LocalRefusal(`message`) -- nothing sent -- when `params` carries no kaisuukenId."""
    from moonglade.backup import LocalRefusal
    if not (params or {}).get("kaisuukenId"):
        raise LocalRefusal(message)


def quoted_free_hooks(req, expect_free):
    """submit()'s before_send for a send quoted FREE: runs after the card step and before the
    one send, and refuses when no card was attached. An Unlimited Mode request is free by the
    entitlement, never by a card, so it is never held to this. {} when there is nothing to
    hold the send to."""
    if not expect_free or req.unlimited:
        return {}
    if req.mode in CARDLESS_MODES:
        # V9 (DESIGN_3.22 2.3): a kind that never takes a card can never have been quoted FREE,
        # so a send that says it was is refused here, with nothing sent.
        from moonglade.backup import LocalRefusal
        raise LocalRefusal(CARDLESS_FREE)

    def _before_send(params):
        refuse_if_quoted_free_gone(params)
    return {"before_send": _before_send}


#: The kinds no free card ever covers: their routes run no card check (V9).
CARDLESS_MODES = frozenset(("enhance", "scene", "fix"))
CARDLESS_FREE = ("This kind of send never uses a free card, so it can't have been priced FREE. "
                 "Nothing was sent. Check the price again before you send.")


# --- the repeat hold (3.21.2, DESIGN_3.22 2.12 and V1) -------------------------
# Every single send claims a record for (signed-in user, kind, the request as sent) BEFORE
# anything goes out, and an identical send while it stands is refused before any network call:
# a double tap, a second tab, a stale bundle or a client retry after a lost answer must not
# pay twice. The record is KEPT REPEAT_SENT_S after a success (Fix's double-tap window since
# #93) and REPEAT_UNCLEAR_S after an unknown outcome; it is DROPPED only when the send is known
# to have cost nothing -- never reached, or refused in a way classify_outcome proves
# (send_outcome). Nothing links an unclear send to a task id, so no poll or catch-up result
# clears a record early.
REPEAT_SENT_S = 10.0
REPEAT_UNCLEAR_S = 60.0
_repeat_records = {}                    # key -> (until, state): "sending" | "sent" | "unclear"
_repeat_lock = threading.Lock()


def repeat_key(user, kind, body):
    """(user, kind, the request as sent, canonical JSON) -- the record's key. Never raises."""
    try:
        blob = json.dumps(body, sort_keys=True, default=str)
    except Exception:                                        # noqa: BLE001
        blob = repr(body)
    return (str(user or ""), str(kind), blob)


def repeat_claim(key, claim=True):
    """The standing record's state for `key` -- "sending", "sent" or "unclear" -- when one
    stands (the send must be refused), else None, with the record now claimed as "sending"
    when `claim` (it holds REPEAT_UNCLEAR_S if the request never settles it). A route checks
    with claim=False before its first network call and claims, atomically (two racing
    requests cannot both pass), immediately before the send itself. Local, no network."""
    now = time.monotonic()
    with _repeat_lock:
        for k in [k for k, (until, _s) in _repeat_records.items() if now >= until]:
            del _repeat_records[k]
        held = _repeat_records.get(key)
        if held is None:
            if claim:
                _repeat_records[key] = (now + REPEAT_UNCLEAR_S, "sending")
            return None
        return held[1]


def repeat_settle(key, state):
    """Settle a claimed record by the send's state: "sent" keeps it REPEAT_SENT_S,
    "may_have_started" keeps it REPEAT_UNCLEAR_S, "not_sent" / "refused" (nothing was made)
    drop it. Any other state keeps it as unclear: only a proven no-cost outcome frees a send."""
    if key is None:
        return
    now = time.monotonic()
    with _repeat_lock:
        if state == "sent":
            _repeat_records[key] = (now + REPEAT_SENT_S, "sent")
        elif state in ("not_sent", "refused"):
            _repeat_records.pop(key, None)
        else:
            _repeat_records[key] = (now + REPEAT_UNCLEAR_S, "unclear")


def repeat_settle_failure(key, exc, reached):
    """Settle a claimed record after a failed send, by the classifier (send_outcome), and
    return the state. A classifier that raises reads "may_have_started" when the send was
    reached -- never "refused"."""
    try:
        state = send_outcome(exc, bool(reached))
    except Exception:                                        # noqa: BLE001 -- never "refused"
        state = "may_have_started" if reached else "not_sent"
    repeat_settle(key, state)
    return state


# --- the Inspector's request record (DESIGN_3.22 3.4) ---------------------------
def request_record(kind, params):
    """What the Inspector shows a request was sent as. On a kind CREATE_ROAD sends through the
    create door, PixAI's REST operation (`task.createTask`, its route) with the wire step's
    drops named; on a GraphQL kind, createGenerationTask as before. `variables.parameters`
    stays the parameters either way (the Inspector's reader keys on it). Pure."""
    rec = {"operation": "createGenerationTask", "variables": {"parameters": params}}
    if CREATE_ROAD.get(kind) == "rest" and kind in ("image", "edit"):
        from moonglade.pixai_client import CREATE_PATHS
        rec["operation"] = "task.createTask"
        rec["route"] = "POST /v2" + CREATE_PATHS[kind]
        rec["dropped"] = _gen_params.wire_drops(kind, params)
    return rec
