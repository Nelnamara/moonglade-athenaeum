"""
moonglade/pricing.py
====================
What a task would cost, asked of PixAI without creating anything: the task-price query and its
two field lists (`_PRICE_SCALARS`, `_PRICE_NESTED`, `_task_price_query`, `price_task`), the Fix
quote (`_FIXER_PRICE_PATH` with its import-time tripwire, `price_fixer`) and the queue wait
estimate (`queue_wait_estimate`). Moved verbatim out of moonglade/backup.py in the 3.22 split
(phase 5).

It reaches the per-model gate as `_models._gate_params_for_model`, the way the engine did once
the models moved out. The names it reads from the engine (_rest_get, _rest_post, PixAIError,
and build_fixer_body until the builders move) are imported inside each function that uses them,
at call time, so a test's patch of backup's binding still reaches them and importing this
module never imports the engine.
"""
import json
import sys

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")

from moonglade import models as _models


# PixAI's own Fix PRICE route. Its input is the exact body the Fix submit sends, and it
# answers {actualPrice, originalPrice} without creating anything (measured 2026-10-28, issue
# #93). It sits one path segment away from the SPEND route, "/task/fixer" -- so it is a
# named constant, never assembled from that string. The check below pins the FULL path (an
# inequality with "/task/fixer" would let "/task/fixer/" or "/task//fixer" through), and it
# is an `if`, not an `assert`, so `python -O` cannot strip it; dev/tests/test_fix.py pins the
# same string.
_FIXER_PRICE_PATH = "/task/fixer/price"
if _FIXER_PRICE_PATH != "/task/fixer/price":      # pragma: no cover - an edit-time tripwire
    raise ImportError("_FIXER_PRICE_PATH must be exactly /task/fixer/price (the Fix QUOTE route)")


# PixAI's own ENHANCE price route (3.22 S3-enhance, DESIGN_3.22 2.3): the same input as the
# enhance submit, one segment from the SPEND route "/task/enhance" -- so a named constant, never
# assembled, pinned whole by an `if` that `python -O` cannot strip.
_ENHANCE_PRICE_PATH = "/task/enhance/price"
if _ENHANCE_PRICE_PATH != "/task/enhance/price":    # pragma: no cover - an edit-time tripwire
    raise ImportError("_ENHANCE_PRICE_PATH must be exactly /task/enhance/price (a QUOTE route)")
_enhance_quote_seen = {"logged": False}


def enhance_quote_session():
    """The session an enhance is QUOTED on (DESIGN_3.22 2.5): the Mirror's STORED sign-in, only
    while the Mirror is armed and the token usable -- the identity that runs the job. Built
    directly from the stored token, never through make_mirror_session: a quote renews nothing.
    None otherwise (the badge then says it couldn't verify the cost)."""
    from moonglade import mirror as _mirror
    try:
        if not _mirror.mirror_enabled():
            return None
        jwt = _mirror.load_mirror_state().get("jwt") or ""
        return _mirror._mirror_session_from(jwt) if _mirror._jwt_usable(jwt) else None
    except Exception:                                       # noqa: BLE001 -- fail soft
        return None


def price_enhance(session, body):
    """PixAI's price for an enhance of exactly `body` (build_enhance_body's dict), from POST
    /v2/task/enhance/price -> int credits, or None. A QUOTE: no _check_read_only, single attempt
    (rest_post), fails soft. The route has no contract description (P4), so the answer's shape
    is logged on the first read, and a number is answered only when it parses as
    {actualPrice: int}; anything else is None ("couldn't verify the cost"). `session` None (no
    armed Mirror) is None without a call."""
    from moonglade.backup import PixAIError, _rest_post
    from moonglade.gen_params import build_enhance_body
    if session is None or not isinstance(body, dict):
        return None
    try:
        sent = build_enhance_body(body.get("mediaId"), body.get("enhanceType"), body.get("prompt"))
    except PixAIError:
        return None
    try:
        data = _rest_post(session, _ENHANCE_PRICE_PATH, sent)
    except (PixAIError, requests.RequestException, ValueError):
        return None
    if not _enhance_quote_seen["logged"]:
        _enhance_quote_seen["logged"] = True
        try:
            import logging
            shape = ({k: type(v).__name__ for k, v in data.items()} if isinstance(data, dict)
                     else type(data).__name__)
            logging.getLogger("moonglade.pricing").info(
                "enhance quote: first answer's shape %s", shape)
        except Exception:                                   # noqa: BLE001
            pass
    ap = data.get("actualPrice") if isinstance(data, dict) else None
    if isinstance(ap, int) and not isinstance(ap, bool):
        return ap
    return None


def price_fixer(session, body):
    """PixAI's price for a Fix of exactly `body` (build_fixer_body's dict), from POST
    /v2/task/fixer/price -> {"cost": int, "original": int|None}, or None.

    A QUOTE, not a spend: it creates nothing, so it does not call _check_read_only (the same
    footing as the read-only POST to /kaisuuken/check), and it rides the API-key session the
    caller hands it -- never _session_for_create. The path is the module constant, never
    taken from a caller. Single attempt (rest_post has no retry loop) and fails soft like
    price_task: every way the call can fail is None, which the badge renders as its red
    couldn't-verify state -- never a guessed price.

    The body is put through build_fixer_body once more before it goes out: for a dict that
    builder made it is the same body (cleaning is idempotent), and a hand-built one that is
    empty or carries two kinds is refused here, before any network call."""
    from moonglade.backup import PixAIError, _rest_post
    from moonglade.gen_params import build_fixer_body
    try:
        sent = build_fixer_body((body or {}).get("mediaId") or "", (body or {}).get("boxes"))
    except (PixAIError, AttributeError, TypeError):
        return None
    if not sent["mediaId"]:
        return None
    try:
        data = _rest_post(session, _FIXER_PRICE_PATH, sent)
    except (PixAIError, requests.RequestException, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        ap = data.get("actualPrice")
        if ap is None:
            return None
        op = data.get("originalPrice")
        return {"cost": int(ap), "original": int(op) if op is not None else None}
    except (TypeError, ValueError):
        return None




# GET /v2/task-price computes a generation's credit cost WITHOUT creating it (mirrors the
# GraphQL pricingTask). Scalar params go as query params; the nested blocks below go as
# URL-encoded JSON. Field set = the endpoint's input schema (`Ou` in the app contract) --
# anything else (prompts, seed, cfgScale, channel, kaisuukenId, …) is not priced, so skip it.
_PRICE_SCALARS = frozenset((
    "width", "height", "samplingSteps", "inferenceProfile", "upscaleDenoisingSteps",
    "upscaleDenoisingStrength", "upscale", "samplingMethod", "priority", "strength",
    "batchSize", "enableTile", "enlarge", "mediaId", "modelId", "enableADetailer",
    "lightning", "vaeModelId", "workflowName", "sceneId", "watermark"))
_PRICE_NESTED = frozenset((
    "controlNets", "ipAdapter", "animateDiff", "workflow", "i2vPro", "referenceVideo",
    "t2i2v", "inputs", "chat", "inpaint", "loraParameters",
    # SCOPE_2026-09-26 G3: the task-price schema takes contextImages as URL-encoded JSON, and
    # it moves the price (live quote 2026-09-26: 5,100 for one image, 6,000 for two at
    # 1632x912 pro). Landed in the SAME commit as the gate that sends it, so the badge never
    # quotes a context-image job without its surcharge.
    "contextImages",
    # Lane w2-recipes: the contract's /task-price description lists recipeIds among the
    # nested parameters "passed as URL-encoded JSON". Landed in the SAME commit as the build
    # step that sends it, so the badge never quotes a recipe request without its recipes.
    "recipeIds"))
# The upscale keys above are why the cost badge tracks an upscale at all -- the two methods
# differ by roughly 3x at their maximum ratio. Deliberately NOT listed: enlargeModel,
# upscaleSampler and qualityTag. They are real submit params, but they are not in this
# endpoint's input schema and none of them changes the price (the cost is the same whichever
# upscaler network runs), and an off-schema query param risks a 400 that would make
# price_task fail soft and blank the badge. Add one only with a measurement showing it priced.


def _task_price_query(session, params):
    """THE /v2/task-price query for `params`: the backstop gate (so the quote prices the
    shape that will be sent), then the allowlists above. {} when there is nothing to price,
    None when the gate refuses. Shared by price_task and moonglade.recipes.price_refusal, so
    the second read that asks WHY a recipe quote failed cannot ask about a different
    request than the one that failed."""
    from moonglade.backup import PixAIError
    if not params:
        return None
    try:
        params = _models._gate_params_for_model(session, params)
    except PixAIError:
        return None
    q = {}
    for k, v in params.items():
        if v is None:
            continue
        if k in _PRICE_NESTED:
            q[k] = json.dumps(v)          # requests URL-encodes the JSON string
        elif k in _PRICE_SCALARS:
            q[k] = v
    return q


def price_task(session, params):
    """Compute a generation's credit cost via GET /v2/task-price WITHOUT creating it.
    Returns actualPrice (int credits) or None. READ-ONLY -- spends nothing, fails soft."""
    from moonglade.backup import PixAIError, _rest_get
    if not params:
        return None
    # Same architecture gate the submit applies, so the badge prices the shape that will be
    # sent (quote == charge for DiT/SDXL). Local reassignment only -- the caller's params
    # object is left untouched. Since 2026-09-26 this is a BACKSTOP: the road hands in a dict
    # already gated at build, for which the gate returns the SAME object. Its one refusal (a
    # reference plus LoRAs on an MMDIT26B model) is "no price", never a raise -- this
    # function fails soft.
    q = _task_price_query(session, params)
    if not q:
        return None
    try:
        data = _rest_get(session, "/task-price", params=q) or {}
    except (PixAIError, requests.RequestException, ValueError):
        # "Fails soft" has to mean EVERY way this call can fail (list_kaisuukens' own rule):
        # _rest_get only converts a non-2xx into a PixAIError; a ConnectionError / ReadTimeout
        # comes straight out of the raw session.get. This is called from _apply_kaisuuken's
        # SHORT branch, INSIDE the spend path, purely to put a number in a sentence -- a network
        # blip there used to escape and abort a confirmed submit with a raw traceback.
        return None
    ap = data.get("actualPrice")
    return int(ap) if ap is not None else None


def queue_wait_estimate(session, priority, model_version_id):
    """PixAI's own queue-wait estimate for a (priority, model) pair, in whole seconds, or
    None. GET /v2/task/wait-time -- the number their site puts beside Generate ("Est. wait
    ~9 seconds"). READ-ONLY: creates nothing, prices nothing, spends nothing.

    The parameter shape was probed, not guessed, because the route gives up nothing on its
    own: with no parameters it 400s `expected number, received NaN` on path ["priority"];
    with a priority alone it 400s "modelVersionId or generationModelId must be provided";
    `generationModelId` then 404s "Generation model not found" for the very id our submits
    carry in their `modelId` field, while `modelVersionId` with that same id answers 200. So
    as far as this route is concerned, a submit's `modelId` IS a model version id. `priority`
    is a validated enum rather than a free number -- 1 comes back "invalid priority" -- and
    the two values this app ever submits (500 normal, 1000 --high-priority) both answer.

    Response: {waitDurationSeconds, displayBucket, displaySeconds, displayMinutes}.
    Measured 2026-07-25: Tsubaki.2 v1 at priority 500 -> 25.4s and at 1000 -> 4.4s;
    Reference Pro at 500 -> 50.1s; the same pair re-asked minutes later -> 26.7s. So it is
    per-model AND per-priority, and it tracks real queue depth.

    This is a QUEUE-DEPTH estimate for a submission -- NOT a per-task ETA, and emphatically
    not progress. PixAI exposes no progress on a task at all (probed against a live control:
    none of progress/percent/percentage/step/steps/currentStep/eta/estimatedTime/
    queuePosition/position/waitTime exist on the task object). A caller must present this as
    the estimate it is, never as a countdown that ticks down.
    """
    from moonglade.backup import PixAIError, _rest_get
    if not model_version_id:
        return None                      # the route 400s without one; don't spend the call
    try:
        pri = int(priority)
    except (TypeError, ValueError):
        pri = 500                        # this app's own submit default (see build params)
    try:
        data = _rest_get(session, "/task/wait-time",
                         params={"priority": pri,
                                 "modelVersionId": str(model_version_id)}) or {}
    except (PixAIError, ValueError):
        return None                      # an estimate is a nicety; never raise for it
    secs = data.get("waitDurationSeconds")
    if secs is None:
        secs = data.get("displaySeconds")
    try:
        return max(0, int(round(float(secs))))
    except (TypeError, ValueError):
        return None
