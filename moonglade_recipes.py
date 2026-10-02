"""moonglade_recipes.py -- PixAI recipes: the market, a recipe's page, Mine, Sets, the
creator's writes, and the one step that adds `recipeIds` to a generation.

A recipe is PixAI's saved bundle of generation inputs (prompt fragments, LoRAs, images, a
legacy style code) bound to one model type, published to a market or kept private, and
applied to a generation by id -- up to ten `recipeIds` per task. Styles became recipes on
2026-09-26 (DECISIONS 2026-09-28, H3). Everything here rides PixAI's oRPC /v2 REST surface
through moonglade_backup's transport (`_rest_get` / `_rest_post`), so the suite's offline
guards cover it; the schemas are the site's own (see the design note named below).

THE SPEND PATH. `attach_to_built` and `apply_to_params` are what a generation sees from this
module: the image road in `moonglade_backup.build_request` attaches the ids right after
building the params (before the creativity step-down reads them and before the gate), and
checks them again after the per-model gate and before the Unlimited Mode check.
`refusal_from` turns PixAI's 422 RECIPE_UNAVAILABLE /
RECIPE_INCOMPATIBLE into a structured answer the client can read, and `price_refusal` asks
/v2/task-price why a quote with recipes failed. The design, its guard order and its
adversarial review: moonglade-internal/design/notes/recipes/BUILD-w2-recipes.md.

THE WRITES. Publishing, editing, archiving and the recipe Sets are deliberate user actions.
Every write here calls `core._check_read_only` before its first network call and is single
attempt. Nothing writes when a surface opens (DECISIONS 2026-09-28, "Nothing writes on
open"), and `GET /v2/recipes/draft` is never called -- it CREATES a draft. Drafts are the
app's own until the user publishes.
"""
import json
import re
import threading
import time

import moonglade_backup as core

MAX_RECIPES = 10                 # recipeIds per task (the site's .slice(0, 10), stepUp qr)
MAX_SLOTS = 8                    # payload.slots
TITLE_MAX = 200
DESCRIPTION_MAX = 2000
SHOWCASE_MIN, SHOWCASE_MAX = 3, 8
STYLE_CODE_MAX = 100
TRIGGER_WORDS_MAX = 512

# The seven categories (GET /v2/recipes/categories answers the live list; this is the
# order the handoff draws and the fallback when that read fails).
CATEGORIES = ("character", "style", "pose", "panel", "effect", "outfit", "scene")
MODEL_TYPES = ("MMDIT26B_MODEL", "MMDIT26A_MODEL", "SDXL_MODEL")
SLOT_TYPES = ("promptFragment", "contextImages", "baseImage", "referenceVideos",
              "referenceImages", "styleCode", "lora")
STATUSES = ("draft", "test", "published", "archived")
# What the update route's presetType takes (stepUp $r). `unlisted` is a state PixAI sets; the
# site's own form leaves presetType out when a recipe reads unlisted.
PRESET_TYPES_WRITABLE = ("public", "follow_to_use", "private")
SORTS = {"trending": "/recipes/trending", "most-liked": "/recipes/most-liked",
         "most-used": "/recipes/most-used", "latest": "/recipes/latest"}
USER_SORTS = ("latest", "oldest", "most-liked", "most-used", "liked")

# ---------------------------------------------------------------------------------------
# The generation step (the ONE call build_request makes)
# ---------------------------------------------------------------------------------------

_ID_RE = re.compile(r"^[1-9][0-9]{0,19}$")
HELD_WITH_CONTEXT = ("Recipes are held while context images are on — switch back to "
                     "LoRAs to send them")
NOT_WITH_UPSCALE = "Recipes don't apply to an upscale"
NOT_ON_LANE = "Unlimited Mode can't use a workflow or a recipe"
UNGATED = ("This road can't check a recipe against the model, so it won't send one — "
           "use the Generate dock")


def recipe_ids_from(payload):
    """The payload's `recipeIds`, validated, in the order sent: a list of digit strings, or
    [] when the payload names none. Raises core.PixAIError rather than dropping, trimming or
    deduplicating anything: each of those would send a different request than the one the
    user built and was quoted for."""
    raw = (payload or {}).get("recipeIds")
    if raw is None or raw == []:
        return []
    if not isinstance(raw, list):
        raise core.PixAIError("Recipes must be a list of recipe ids")
    ids = []
    for v in raw:
        # Strings only: an 18-19 digit id held as a JS number arrives ROUNDED and would name a
        # different recipe; a bool is an int in Python. No leading zero, so "0123" and "123"
        # cannot pass the duplicate check as two recipes (review finding 5).
        s = v.strip() if isinstance(v, str) else ""
        if not _ID_RE.match(s):
            raise core.PixAIError("That isn't a recipe id")
        if s in ids:
            raise core.PixAIError("The same recipe is in the row twice — remove one")
        ids.append(s)
    if len(ids) > MAX_RECIPES:
        extra = len(ids) - MAX_RECIPES
        raise core.PixAIError("Up to {} recipes — remove {}".format(MAX_RECIPES, extra))
    return ids


def _combination_problem(params):
    """Why `params` must not carry recipes, or None: context images (H decision 1: recipes
    are held, never sent with them), an Unlimited Mode lane, or the Upscale road."""
    if params.get("contextImages"):
        return HELD_WITH_CONTEXT
    if params.get("lane"):
        return NOT_ON_LANE
    if params.get("mediaId") and (params.get("enlarge") or params.get("upscale")):
        return NOT_WITH_UPSCALE
    return None


def attach_to_built(params, payload, gated=True):
    """The FIRST of the image road's two recipe steps (moonglade_backup.build_request): the
    payload's ids, validated by recipe_ids_from, onto the freshly BUILT params -- right after
    _gen_parameters and BEFORE _shape_creativity, whose recipe step-down (medium -> low,
    low -> off, PixAI's own rule) reads the built params' `recipeIds` and must see them (lane
    w2-gen review S3, this lane's review finding 6). Returns `params` ITSELF when the payload
    names no recipe, else a copy carrying `recipeIds`. Refuses what it can already see: a
    malformed list, a road with no gate, and the combinations visible before the gate
    (context images the drawer built, the Upscale road). The gate may still change the dict
    (a reference becoming a context image), so apply_to_params checks again after it."""
    ids = recipe_ids_from(payload)
    if not ids or not isinstance(params, dict):
        return params
    if not gated:
        raise core.PixAIError(UNGATED)
    why = _combination_problem(params)
    if why:
        raise core.PixAIError(why)
    out = dict(params)
    out["recipeIds"] = ids
    return out


def apply_to_params(params, payload, gated=True):
    """The SECOND recipe step (moonglade_backup.build_request), on the dict the gate
    returned. Returns `params` ITSELF when the payload names no recipe -- so every payload
    without recipes builds the byte-identical dict it always did -- and ITSELF when the ids
    attach_to_built put there are still there, as sent; else a copy carrying `recipeIds`.
    Refuses (raises core.PixAIError; nothing is priced, matched or sent) on a malformed list,
    on a road with no per-model gate (`gated` False: it cannot vouch for the combination, the
    rule the lane follows), on context images and on the Upscale road. Runs AFTER the gate,
    so it sees the dict that goes out, and BEFORE the Unlimited Mode check, which refuses any
    recipe on the lane."""
    ids = recipe_ids_from(payload)
    if not ids or not isinstance(params, dict):
        return params
    if not gated:
        raise core.PixAIError(UNGATED)
    why = _combination_problem(params)
    if why:
        raise core.PixAIError(why)
    if params.get("recipeIds") == ids:
        return params
    out = dict(params)
    out["recipeIds"] = ids
    return out


def check_params(params):
    """The send's backstop (moonglade_backup.submit_generation, after its own gate pass):
    a dict carrying `recipeIds` must carry a well-formed list and none of the combinations
    above. The build already refused all of these; this catches what the backstop gate
    changes late -- a reference it converts into `contextImages` once a /features read that
    failed at build answers at submit -- and a CLI --params-json that never met the build
    (review finding 1). Raises core.PixAIError; returns None."""
    if not isinstance(params, dict) or "recipeIds" not in params:
        return None
    recipe_ids_from({"recipeIds": params.get("recipeIds")})
    why = _combination_problem(params)
    if why:
        raise core.PixAIError(why)
    return None


CARD_NOTE = ("a free card matched this request; whether it also covers a recipe's own LoRAs "
             "is PixAI's call")


def price_verdict(session, params, cost):
    """The price answer's recipe rule (moonglade_backup._price_answer), for a quote whose
    parameters carry `recipeIds`: None when the price was read (the card check runs as
    usual), else the whole answer -- PixAI's own refusal when /v2/task-price says RECIPE_*,
    or "couldn't verify". Either way the card check is SKIPPED: a recipe quote nobody could
    price must never read FREE (review finding 2)."""
    if cost is not None:
        return None
    refusal = price_refusal(session, params)
    if refusal:
        return {"cost": None, "free": False, "note": refusal["copy"],
                "recipe_error": refusal}
    return {"cost": None, "free": False,
            "note": "couldn't verify the price with these recipes"}


# ---------------------------------------------------------------------------------------
# PixAI's refusals, structured
# ---------------------------------------------------------------------------------------

REFUSAL_CODES = ("RECIPE_UNAVAILABLE", "RECIPE_INCOMPATIBLE")
# RECIPE_UNAVAILABLE's reasons (stepUp Fa); RECIPE_INCOMPATIBLE's 22 (stepUp ue), in H
# decision 10's six groups.
UNAVAILABLE_REASONS = ("not_found", "draft", "test_not_author", "not_public",
                       "follow_required", "violating", "apply_disabled", "invalid_id",
                       "lora_disabled")
REASON_GROUPS = {
    "model": ("target_model_unknown", "model_mismatch", "lora_model_mismatch"),
    "images": ("multiple_base_image", "model_rejects_base_image",
               "context_images_unsupported", "context_image_too_large",
               "context_image_budget", "reference_image_budget", "user_media_conflict"),
    "video": ("not_a_reference_video_task", "reference_video_budget",
              "reference_video_duration"),
    "clashes": ("multiple_style_code", "user_style_conflict", "mutually_exclusive_feature",
                "slot_rule_violation"),
    "prompt": ("prompt_length_budget", "merged_prompt_violating"),
    "loras": ("lora_budget", "lora_unavailable", "lora_unsupported"),
}
# (tag on a tile, the sentence, the fix) per reason; the group's own words come from the
# options page (Session H Top-up, T2 "the 22 reasons in six plain groups").
_REASON_COPY = {
    "target_model_unknown": ("Wrong model", "is made for a different model", "Switch model"),
    "model_mismatch": ("Wrong model", "is made for a different model", "Switch model"),
    "lora_model_mismatch": ("Wrong model", "has a LoRA made for a different model",
                            "Switch model"),
    "multiple_base_image": ("Image clash", "brings a base image and so does another",
                            "Remove one"),
    "model_rejects_base_image": ("Image clash", "has a base image this model can't take",
                                 "Remove it"),
    "context_images_unsupported": ("Image clash", "has context images this model can't take",
                                   "Remove it"),
    "context_image_too_large": ("Image too large", "has a context image that is too large",
                                "Remove it"),
    "context_image_budget": ("Too many images", "brings too many images", "Remove one"),
    "reference_image_budget": ("Too many images", "brings too many images", "Remove one"),
    "user_media_conflict": ("Image clash", "can't go with your context images",
                            "Remove it"),
    "not_a_reference_video_task": ("Needs video", "needs a video task", "Remove it"),
    "reference_video_budget": ("Too many videos", "brings too many or too long videos",
                               "Remove it"),
    "reference_video_duration": ("Video too long", "brings too many or too long videos",
                                 "Remove it"),
    "multiple_style_code": ("Clashes", "clashes with another recipe", "Remove one"),
    "user_style_conflict": ("Clashes", "clashes with your palette or style", "Remove it"),
    "mutually_exclusive_feature": ("Clashes", "clashes with another recipe or your palette",
                                   "Remove it"),
    "slot_rule_violation": ("Clashes", "clashes with another recipe", "Remove it"),
    "prompt_length_budget": ("Prompt too long", "would make the prompt too long",
                             "Shorten the prompt"),
    "merged_prompt_violating": ("Not allowed", "makes a prompt PixAI doesn't allow",
                                "Remove it"),
    "lora_budget": ("Too many LoRAs", "brings too many LoRAs", "Remove a LoRA"),
    "lora_unavailable": ("LoRA gone", "needs a LoRA that is gone", "Remove it"),
    "lora_unsupported": ("LoRA gone", "needs a LoRA this model can't use", "Remove it"),
}


def _group_of(code, reason):
    if code == "RECIPE_UNAVAILABLE":
        return "follow" if reason == "follow_required" else "unavailable"
    for g, reasons in REASON_GROUPS.items():
        if reason in reasons:
            return g
    return "clashes"


def refusal_dict(code, reason, recipe_ids):
    """The structured refusal the client reads: {code, reason, recipe_ids, group, tag,
    copy, fix}. `copy` is one plain sentence about the recipe(s) named."""
    code = str(code or "")
    reason = str(reason or "")
    ids = [str(i) for i in (recipe_ids or []) if str(i).strip()]
    group = _group_of(code, reason)
    if group == "follow":
        tag, copy, fix = ("Followers only", "Follow the author to use it",
                          "Follow the author")
    elif group == "unavailable":
        tag, copy, fix = ("Unavailable", "This recipe isn't available any more", "Remove")
    else:
        tag, what, fix = _REASON_COPY.get(
            reason, ("Doesn't fit", "doesn't fit this request", "Remove it"))
        copy = ("A recipe " if len(ids) <= 1 else "{} recipes ".format(len(ids))) + what
        if len(ids) > 1:
            copy = copy.replace(" is ", " are ", 1).replace(" has ", " have ", 1) \
                       .replace(" brings ", " bring ", 1).replace(" needs ", " need ", 1) \
                       .replace(" makes ", " make ", 1).replace(" clashes ", " clash ", 1)
    return {"code": code, "reason": reason, "recipe_ids": ids, "group": group,
            "tag": tag, "copy": copy, "fix": fix}


def _exception_record(obj):
    """{name, recipeIds, reason} from one GraphQL error dict, or None."""
    if not isinstance(obj, dict):
        return None
    ext = obj.get("extensions") if isinstance(obj.get("extensions"), dict) else {}
    exc = ext.get("exception") if isinstance(ext.get("exception"), dict) else {}
    name = exc.get("name") or ext.get("code") or obj.get("code") or ""
    if name not in REFUSAL_CODES:
        return None
    data = exc.get("data") if isinstance(exc.get("data"), dict) else {}
    return {"name": name,
            "recipeIds": exc.get("recipeIds") or data.get("recipeIds") or [],
            "reason": exc.get("reason") or data.get("reason") or ""}


def _body_record(body):
    """{name, recipeIds, reason} from an oRPC error body, or None."""
    if not isinstance(body, dict):
        return None
    name = body.get("code") or body.get("name") or ""
    if name not in REFUSAL_CODES:
        return None
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    return {"name": name, "recipeIds": data.get("recipeIds") or body.get("recipeIds") or [],
            "reason": data.get("reason") or body.get("reason") or ""}


_TEXT_NAME = re.compile(r'"(?:name|code)"\s*:\s*"(RECIPE_(?:UNAVAILABLE|INCOMPATIBLE))"')
_TEXT_REASON = re.compile(r'"reason"\s*:\s*"([a-z_]+)"')
_TEXT_IDS = re.compile(r'"recipeIds"\s*:\s*\[([^\]]*)')


def refusal_from(exc):
    """PixAI's RECIPE_UNAVAILABLE / RECIPE_INCOMPATIBLE refusal inside `exc`, as
    refusal_dict(), or None for any other failure. Reads, in order: the full GraphQL
    `errors` list the transport attaches (`graphql_errors`), an oRPC REST body (`body`),
    then the message text itself (a truncated or wrapped error still names its code)."""
    if exc is None:
        return None
    rec = None
    for e in (getattr(exc, "graphql_errors", None) or []):
        rec = _exception_record(e)
        if rec:
            break
    if rec is None:
        rec = _body_record(getattr(exc, "body", None))
    if rec is None:
        text = str(exc)
        m = _TEXT_NAME.search(text)
        if not m:
            return None
        r = _TEXT_REASON.search(text)
        ids = _TEXT_IDS.search(text)
        rec = {"name": m.group(1), "reason": r.group(1) if r else "",
               "recipeIds": re.findall(r'"?(\d+)"?', ids.group(1)) if ids else []}
    return refusal_dict(rec["name"], rec["reason"], rec["recipeIds"])


def price_refusal(session, params):
    """Why a quote carrying recipes failed: the refusal_dict when /v2/task-price answers a
    RECIPE_* 422 for this exact query, else None. READ-ONLY. Called by the price answer only
    after price_task answered None, so it costs one extra GET on a failed quote with recipes
    and nothing otherwise. The query comes from core._task_price_query, the one builder
    price_task itself uses, so this cannot ask about a different request."""
    if not isinstance(params, dict) or not params.get("recipeIds"):
        return None
    q = core._task_price_query(session, params)
    if not q:
        return None
    try:
        core._rest_get(session, "/task-price", params=q)
    except Exception as e:                                   # noqa: BLE001
        return refusal_from(e)
    return None


# ---------------------------------------------------------------------------------------
# Reads: normalising PixAI's shapes into what the client draws
# ---------------------------------------------------------------------------------------

THUMB_URL = "https://api.pixai.art/v1/media/{}/thumbnail"


def media_url(media, media_id=None, full=False):
    """A URL for a PixAI media object ({urls: [{variant, url}], thumbnailUrl, fileUrl} or
    the artwork shape {thumbnailUrl, publicUrl}), preferring the thumbnail unless `full`;
    the /v1/media/<id>/thumbnail road when all it has is an id."""
    m = media if isinstance(media, dict) else {}
    urls = {}
    for u in m.get("urls") or []:
        if isinstance(u, dict) and u.get("variant") and u.get("url"):
            urls[u["variant"]] = u["url"]
    order = (["PUBLIC", "THUMBNAIL", "STILL_THUMBNAIL"] if full
             else ["THUMBNAIL", "STILL_THUMBNAIL", "PUBLIC"])
    for v in order:
        if urls.get(v):
            return urls[v]
    for k in (("publicUrl", "fileUrl", "thumbnailUrl") if full
              else ("thumbnailUrl", "publicUrl", "fileUrl")):
        if m.get(k):
            return m[k]
    mid = str(media_id or m.get("id") or m.get("mediaId") or "").strip()
    return THUMB_URL.format(mid) if mid else ""


_KIND_LABEL = {"promptFragment": "Prompt", "lora": "LoRA", "baseImage": "Base image",
               "referenceImages": "Reference", "contextImages": "Context image",
               "styleCode": "Style code", "referenceVideos": "Video"}


def kinds_of(slot_types, slot_specs=None, slots=None):
    """[{type, label, count}] -- what a recipe adds, by kind, never its content: the
    public view carries slotSpecs (kind + size/length) instead of the slots. `count` is
    the number of items of that kind (LoRAs in a LoRA slot, images in an image slot)."""
    types = [str(t) for t in (slot_types or []) if t]
    by_index = {}
    for s in slot_specs or []:
        if isinstance(s, dict):
            by_index.setdefault(s.get("slotIndex"), []).append(s)
    counts, order = {}, []
    for i, t in enumerate(types):
        n = 1
        if isinstance(slots, list) and i < len(slots) and isinstance(slots[i], dict):
            sl = slots[i]
            for key in ("images", "videos", "loras"):
                if isinstance(sl.get(key), list):
                    n = max(1, len(sl[key]))
        elif by_index.get(i):
            specs = [s for s in by_index[i] if s.get("kind") in ("image", "video", "lora")]
            n = max(1, len(specs)) if specs else 1
        if t not in counts:
            order.append(t)
        counts[t] = counts.get(t, 0) + n
    return [{"type": t, "label": _KIND_LABEL.get(t, t), "count": counts[t]} for t in order]


def prompt_length_of(slot_specs=None, slots=None):
    """How many prompt characters a recipe adds: its promptFragment texts (owner view) or
    the text specs' lengths (public view)."""
    total = 0
    if isinstance(slots, list):
        for sl in slots:
            if isinstance(sl, dict) and sl.get("type") == "promptFragment":
                total += len(str(sl.get("text") or ""))
        return total
    for s in slot_specs or []:
        if isinstance(s, dict) and s.get("kind") == "text":
            try:
                total += int(s.get("length") or 0)
            except (TypeError, ValueError):
                pass
    return total


def _num(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def card(raw):
    """One recipe as the client draws it (market cards, the pane, Mine rows, chips). Works
    for every recipe shape PixAI sends (market card, public or owner view); fields a shape
    lacks come back empty."""
    r = raw if isinstance(raw, dict) else {}
    rid = str(r.get("id") or "")
    model = r.get("model") if isinstance(r.get("model"), dict) else {}
    latest = model.get("latestAvailableVersion") if isinstance(
        model.get("latestAvailableVersion"), dict) else {}
    author = r.get("author") if isinstance(r.get("author"), dict) else {}
    stats = r.get("stats") if isinstance(r.get("stats"), dict) else {}
    payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
    slots = payload.get("slots") if isinstance(payload.get("slots"), list) else None
    cats = [str(c) for c in (r.get("categories") or []) if c]
    official = str(r.get("source") or "") == "official"
    preset = str(r.get("presetType") or "")
    out = {
        "id": rid,
        "title": str(r.get("title") or ""),
        "description": str(r.get("description") or ""),
        "category": cats[0] if cats else "",
        "categories": cats,
        "cover_media_id": str(r.get("coverMediaId") or ""),
        "cover": media_url(r.get("coverMedia"), r.get("coverMediaId")),
        "model_type": str(r.get("modelType") or model.get("type") or ""),
        "model_id": str(r.get("modelId") or model.get("id") or ""),
        "model_title": str(model.get("title") or ""),
        "model_version_id": str(latest.get("id") or model.get("latestAvailableVersionId") or ""),
        "slot_types": [str(t) for t in (r.get("slotTypes") or []) if t],
        "kinds": kinds_of(r.get("slotTypes"), r.get("slotSpecs"), slots),
        "prompt_len": prompt_length_of(r.get("slotSpecs"), slots),
        "source": str(r.get("source") or ""),
        "official": official,
        "author": {"id": str(author.get("id") or ""),
                   "name": "PixAI Official" if official else
                   str(author.get("displayName") or author.get("username") or ""),
                   "username": str(author.get("username") or "")},
        "uses": _num(stats.get("taskCount")),
        "likes": _num(stats.get("likedCount")),
        "artworks": _num(stats.get("artworkCount")),
        "preset_type": preset,
        "followers_only": preset == "follow_to_use",
        "status": str(r.get("status") or ""),
        "visibility": str(r.get("visibility") or ""),
        "usability": str(r.get("usability") or ""),
        "published_at": str(r.get("publishedAt") or ""),
    }
    if r.get("version") is not None:
        out["version"] = r.get("version")          # the owner's view: Edit's stale-check
    if "selfCollectionStatus" in r:
        out["in_set"] = str(r.get("selfCollectionStatus") or "") not in ("", "not-collected")
    if isinstance(r.get("showcases"), list):
        out["showcases"] = [{"media_id": str((m or {}).get("id") or ""),
                             "url": media_url(m), "full": media_url(m, full=True)}
                            for m in r["showcases"] if isinstance(m, dict)]
    if isinstance(r.get("showcaseMediaIds"), list):
        out["showcase_media_ids"] = [str(x) for x in r["showcaseMediaIds"]]
    if slots is not None:
        out["slots"] = slots          # the OWNER's view only: PixAI sends payload to its author
    return out


def page_of(data, key="data"):
    """{items, page, total_page, total} from a paged PixAI list of recipes."""
    d = data if isinstance(data, dict) else {}
    return {"items": [card(x) for x in (d.get(key) or []) if isinstance(x, dict)],
            "page": _num(d.get("page")) or 1,
            "total_page": _num(d.get("totalPage")),
            "total": _num(d.get("totalCount"))}


def artwork(raw):
    a = raw if isinstance(raw, dict) else {}
    media = a.get("media") if isinstance(a.get("media"), dict) else {}
    return {"id": str(a.get("id") or ""), "media_id": str(a.get("mediaId") or ""),
            "title": str(a.get("title") or ""), "author": str(a.get("authorName") or ""),
            "thumb": media_url(media, a.get("mediaId")),
            "likes": _num(a.get("likedCount")),
            "blur": bool(((a.get("flag") or {}) if isinstance(a.get("flag"), dict) else {})
                         .get("shouldBlur")),
            "width": media.get("width"), "height": media.get("height")}


def task_row(raw):
    t = raw if isinstance(raw, dict) else {}
    outs = t.get("outputs") if isinstance(t.get("outputs"), dict) else {}
    mids = [str(m) for m in (outs.get("mediaIds") or []) if m]
    urls = [u for u in (outs.get("mediaUrls") or [])]
    return {"id": str(t.get("id") or ""), "status": str(t.get("status") or ""),
            "created_at": str(t.get("createdAt") or ""),
            "media": [{"media_id": m, "thumb": (urls[i] if i < len(urls) and urls[i]
                                                else THUMB_URL.format(m))}
                      for i, m in enumerate(mids)]}


def collection(raw):
    c = raw if isinstance(raw, dict) else {}
    covers = [str(x) for x in (c.get("resolvedCoverMediaIds") or c.get("coverMediaIds")
                               or []) if x]
    out = {"id": str(c.get("id") or ""), "title": str(c.get("title") or ""),
           "count": _num(c.get("itemCount")), "visibility": str(c.get("visibility") or ""),
           "reserved": bool(c.get("reservedType")),
           "covers": [THUMB_URL.format(m) for m in covers[:4]]}
    if "containsItem" in c:
        out["contains"] = bool(c.get("containsItem"))
        out["item_id"] = str(c.get("itemId") or "")
    return out


# ---------------------------------------------------------------------------------------
# Read routes (all GETs; the reachability table in PROBE_2026-09-27 lists the recipe ones)
# ---------------------------------------------------------------------------------------

_cache = {}
_cache_lock = threading.Lock()
_STATIC_TTL = 3600.0         # categories, model types, a model's capability
_LIST_TTL = 60.0             # market pages: a picker reopened within a minute costs nothing


def _cached(key, ttl, fetch):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    val = fetch()
    with _cache_lock:
        _cache[key] = (now, val)
    return val


def clear_cache():
    with _cache_lock:
        _cache.clear()


def categories(session):
    def fetch():
        d = core._rest_get(session, "/recipes/categories") or {}
        cats = [str(c) for c in (d.get("categories") or []) if c]
        return cats or list(CATEGORIES)
    try:
        return _cached(("categories",), _STATIC_TTL, fetch)
    except Exception:                                        # noqa: BLE001
        return list(CATEGORIES)


def model_types(session):
    def fetch():
        d = core._rest_get(session, "/recipes/model-types") or {}
        types = [str(t) for t in (d.get("modelTypes") or []) if t]
        return types or list(MODEL_TYPES)
    try:
        return _cached(("model-types",), _STATIC_TTL, fetch)
    except Exception:                                        # noqa: BLE001
        return list(MODEL_TYPES)


def capability(session, model_type="", model_id=""):
    """{slots: [{type, max}]} for a model (by id or type). Raises on a failed read -- a
    creator must not guess what a model takes."""
    mt, mid = str(model_type or "").strip(), str(model_id or "").strip()
    if not (mt or mid):
        raise core.PixAIError("pick a model first")
    params = {"modelId": mid} if mid else {"modelType": mt}

    def fetch():
        d = core._rest_get(session, "/recipes/model-capability", params=params) or {}
        return {"slots": [{"type": str(s.get("type")), "max": _num(s.get("maxCount"))}
                          for s in (d.get("slots") or []) if isinstance(s, dict)]}
    return _cached(("cap",) + tuple(sorted(params.items())), _STATIC_TTL, fetch)


def _filters(category="", model_type="", model_id=""):
    q = {}
    if category:
        q["categories[0]"] = str(category)
    if model_id:
        q["modelId"] = str(model_id)
    elif model_type:
        q["modelType"] = str(model_type)
    return q


def market(session, sort="trending", page=1, page_size=24, category="", model_type="",
           model_id="", query=""):
    """One market page. `query` switches to /recipes/search (newest first; the sort does
    not apply there, as on PixAI)."""
    page = max(1, min(20, _num(page) or 1))            # the contract caps page at 20
    page_size = max(1, min(100, _num(page_size) or 24))
    q = {"page": page, "pageSize": page_size}
    q.update(_filters(category, model_type, model_id))
    query = str(query or "").strip()[:100]
    if query:
        q["q"] = query
        path = "/recipes/search"
    else:
        path = SORTS.get(str(sort or ""), SORTS["trending"])

    def fetch():
        return page_of(core._rest_get(session, path, params=q))
    return _cached(("market", path) + tuple(sorted(q.items())), _LIST_TTL, fetch)


def detail(session, recipe_id):
    rid = _checked_id(recipe_id)
    return card(core._rest_get(session, "/recipes/" + rid) or {})


def batch(session, ids):
    ids = [_checked_id(i) for i in (ids or [])][:20]
    if not ids:
        return []
    d = core._rest_get(session, "/recipes/batch", params={"ids": ",".join(ids)}) or {}
    return [card(x) for x in (d.get("data") or []) if isinstance(x, dict)]


def artworks(session, recipe_id, sort="latest", page=1, page_size=12):
    rid = _checked_id(recipe_id)
    path = "/recipes/{}/artworks/{}".format(rid, "most-liked" if sort == "most-liked"
                                            else "latest")
    d = core._rest_get(session, path, params={"page": max(1, min(20, _num(page) or 1)),
                                              "pageSize": max(1, min(100, _num(page_size)
                                                                     or 12))}) or {}
    return {"items": [artwork(a) for a in (d.get("data") or [])],
            "page": _num(d.get("page")) or 1, "total_page": _num(d.get("totalPage")),
            "total": _num(d.get("totalCount"))}


def tasks(session, recipe_id, usage="", page=1, page_size=12):
    rid = _checked_id(recipe_id)
    q = {"page": max(1, min(20, _num(page) or 1)),
         "pageSize": max(1, min(100, _num(page_size) or 12))}
    if usage in ("test", "normal"):
        q["usageType"] = usage
    d = core._rest_get(session, "/recipes/{}/tasks".format(rid), params=q) or {}
    return {"items": [task_row(t) for t in (d.get("data") or [])],
            "total": _num(d.get("totalCount")), "page": _num(d.get("page")) or 1,
            "total_page": _num(d.get("totalPage"))}


def recently_used(session, limit=30, model_type=""):
    q = {"limit": max(1, min(100, _num(limit) or 30))}
    if model_type:
        q["modelType"] = str(model_type)
    d = core._rest_get(session, "/recipes/recently-used", params=q) or {}
    return [card(x) for x in (d.get("data") or []) if isinstance(x, dict)]


def user_recipes(session, user_id, sort="latest", cursor="", limit=30, model_type=""):
    """The user's recipes (the author sees private, archived and in-review ones too;
    PixAI never lists drafts). Cursor paging, as the route requires."""
    uid = _checked_id(user_id)
    path = "/user/{}/recipes/{}".format(uid, sort if sort in USER_SORTS else "latest")
    q = {"limit": max(1, min(50, _num(limit) or 30))}
    if cursor:
        q["cursor"] = str(cursor)
    if model_type:
        q["modelType"] = str(model_type)
    d = core._rest_get(session, path, params=q) or {}
    return {"items": [card(x) for x in (d.get("data") or []) if isinstance(x, dict)],
            "next_cursor": d.get("nextCursor") or ""}


def by_style_code(session, code, model_version_id=""):
    """The recipe a legacy style code became, or None ("No recipe replaces this code").
    The route needs the model VERSION the code would be used with."""
    code = str(code or "").strip()
    if not code or len(code) > STYLE_CODE_MAX:
        raise core.PixAIError("Paste a style code (up to {} characters)".format(STYLE_CODE_MAX))
    vid = _checked_id(model_version_id) if model_version_id else ""
    if not vid:
        raise core.PixAIError("pick a model first")
    d = core._rest_get(session, "/recipes/by-style-code",
                       params={"refId": code, "modelVersionId": vid}) or {}
    rid = str(d.get("recipeId") or "")
    if not rid:
        return None
    return detail(session, rid)


def _checked_id(v):
    s = str(v or "").strip()
    if not _ID_RE.match(s):
        raise core.PixAIError("That isn't a valid id")
    return s


# ---------------------------------------------------------------------------------------
# Sets (PixAI's collections, contentType "recipe") -- reads
# ---------------------------------------------------------------------------------------

def sets_list(session, owner_id, cursor="", limit=50):
    uid = _checked_id(owner_id)
    q = {"contentType": "recipe", "limit": max(1, min(50, _num(limit) or 50))}
    if cursor:
        q["cursor"] = str(cursor)
    d = core._rest_get(session, "/collection/list/" + uid, params=q) or {}
    return {"sets": [collection(c) for c in (d.get("data") or []) if isinstance(c, dict)],
            "next_cursor": d.get("nextCursor") or ""}


def sets_for(session, recipe_id):
    """The user's recipe sets with whether each holds `recipe_id` (the selector route)."""
    rid = _checked_id(recipe_id)
    d = core._rest_get(session, "/collection/selector",
                       params={"refType": "recipe", "refId": rid, "limit": 50}) or {}
    seen, out = set(), []
    for c in list(d.get("recent") or []) + list(d.get("data") or []):
        if isinstance(c, dict) and str(c.get("id")) not in seen:
            seen.add(str(c.get("id")))
            out.append(collection(c))
    return out


def set_items(session, set_id, cursor=""):
    sid = _checked_id(set_id)
    q = {"limit": 24}
    if cursor:
        q["cursor"] = str(cursor)
    d = core._rest_get(session, "/collection/{}/items".format(sid), params=q) or {}
    items = []
    for it in d.get("data") or []:
        if isinstance(it, dict) and isinstance(it.get("recipe"), dict):
            c = card(it["recipe"])
            c["item_id"] = str(it.get("id") or "")
            items.append(c)
    return {"items": items, "next_cursor": d.get("nextCursor") or ""}


# ---------------------------------------------------------------------------------------
# Writes -- deliberate user actions only; READ_ONLY first, single attempt
# ---------------------------------------------------------------------------------------

def _rest_delete(session, path, timeout=30):
    """DELETE a /v2 route. Single attempt; raises core.PixAIError on non-2xx with the same
    `http_status` / `body` attributes the transport's GET and POST attach."""
    client = core._client_of(session)
    r = client.session.delete(core.REST_API_BASE + path, timeout=timeout)
    if not r.ok:
        raise core._rest_error("DELETE", path, r)
    try:
        return r.json()
    except ValueError:
        return {}


def slots_problem(slots):
    """A plain sentence saying why `slots` cannot be saved, or None. Mirrors PixAI's own
    creator checks (the site's errors-*.js) so the refusal is ours, before any write."""
    if not isinstance(slots, list) or not slots:
        return "Add at least one ingredient"
    if len(slots) > MAX_SLOTS:
        return "Up to {} ingredients".format(MAX_SLOTS)
    types = set()
    for s in slots:
        if not isinstance(s, dict) or s.get("type") not in SLOT_TYPES:
            return "An ingredient isn't one PixAI knows"
        types.add(s["type"])
        t = s["type"]
        if t == "promptFragment" and not str(s.get("text") or "").strip():
            return "A prompt ingredient is empty"
        if t == "styleCode" and not str(s.get("styleCode") or "").strip():
            return "A style code ingredient is empty"
        if t == "lora":
            loras = s.get("loras")
            if not isinstance(loras, list) or not loras:
                return "A LoRA ingredient has no LoRA"
            seen = set()
            for lo in loras:
                vid = str((lo or {}).get("versionId") or "")
                if not _ID_RE.match(vid):
                    return "A LoRA ingredient has no LoRA"
                if vid in seen:
                    return "The same LoRA is in a recipe twice"
                seen.add(vid)
        if t in ("contextImages", "referenceImages") and not (s.get("images") or []):
            return "An image ingredient has no image"
        if t == "baseImage" and not ((s.get("image") or {}).get("mediaId")):
            return "The base image ingredient has no image"
    if "contextImages" in types and "baseImage" in types:
        return "Context images and a base image can't go in one recipe"
    if "contextImages" in types and "lora" in types:
        return "Context images and a LoRA can't go in one recipe"
    return None


def update_body(recipe_id, draft):
    """The full-replace body POST /v2/recipes/{id} takes (the site's recipeFormMapping),
    built from the app's draft. Raises core.PixAIError on anything PixAI would refuse."""
    d = draft if isinstance(draft, dict) else {}
    cats = [str(c) for c in (d.get("categories") or []) if c][:1]
    if not cats:
        raise core.PixAIError("Still needed: a category")
    model_type = str(d.get("modelType") or "")
    model_id = str(d.get("modelId") or "")
    if not model_type or not _ID_RE.match(model_id):
        raise core.PixAIError("Still needed: a model")
    title = str(d.get("title") or "").strip()
    if not title:
        raise core.PixAIError("Still needed: a title")
    if len(title) > TITLE_MAX:
        raise core.PixAIError("The title is longer than {} characters".format(TITLE_MAX))
    desc = str(d.get("description") or "")
    if len(desc) > DESCRIPTION_MAX:
        raise core.PixAIError("The description is longer than {:,} characters".format(
            DESCRIPTION_MAX))
    showcase = [str(m) for m in (d.get("showcaseMediaIds") or []) if str(m).strip()]
    if len(showcase) > SHOWCASE_MAX:
        raise core.PixAIError("Up to {} showcase images".format(SHOWCASE_MAX))
    slots = d.get("slots")
    prob = slots_problem(slots)
    if prob:
        raise core.PixAIError(prob)
    preset = str(d.get("presetType") or "public")
    body = {"id": str(recipe_id), "categories": cats, "title": title,
            "description": desc or None,
            "coverMediaId": str(d.get("coverMediaId") or (showcase[0] if showcase else "")) or None,
            "showcaseMediaIds": showcase, "modelType": model_type, "modelId": model_id,
            "slots": slots}
    if preset in PRESET_TYPES_WRITABLE:
        body["presetType"] = preset
    elif preset != "unlisted":
        raise core.PixAIError("Pick who can use it")
    return body


def _write_problem(e):
    """A plain sentence for a refused recipe write."""
    code = ""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        code = str(body.get("code") or "")
    if not code:
        m = re.search(r'"code"\s*:\s*"([A-Z_]+)"', str(e))
        code = m.group(1) if m else ""
    words = {
        "RECIPE_INCOMPLETE": "PixAI says the recipe isn't finished yet",
        "RECIPE_INVALID_TRANSITION": "PixAI didn't allow that status change",
        "RECIPE_IMMUTABLE": "PixAI doesn't allow changing this recipe now",
        "RECIPE_VISIBILITY_LOCKED": "PixAI has locked who can use this recipe",
        "RECIPE_SLOT_RULE_VIOLATION": "PixAI refused this mix of ingredients",
        "RECIPE_INVALID_CATEGORY": "PixAI doesn't know that category",
        "RECIPE_STYLE_CODE_NOT_FOUND": "PixAI doesn't know that style code",
        "RECIPE_LORA_NOT_USABLE": "A LoRA in it can't be used in a recipe",
        "RECIPE_DRAFT_LIMIT_EXCEEDED": "PixAI's limit on unfinished recipes was reached",
        "RECIPE_SHOWCASE_INELIGIBLE": "PixAI didn't accept a showcase picture",
        "UNAUTHORIZED": "PixAI didn't accept this account's key",
        "NOT_FOUND": "PixAI couldn't find that recipe",
    }
    return words.get(code) or ("PixAI refused it: " + str(e)[:160]), code


class RecipeWriteError(core.PixAIError):
    """A refused recipe write, in plain words, with PixAI's code and -- when a publish got as
    far as creating the recipe -- its id, so the next attempt updates it."""
    def __init__(self, message, code="", recipe_id=""):
        super().__init__(message)
        self.code = code
        self.recipe_id = recipe_id


def _post(session, path, body):
    try:
        return core._rest_post(session, path, body) or {}
    except core.PixAIError as e:
        msg, code = _write_problem(e)
        raise RecipeWriteError(msg, code)


def publish(session, draft, recipe_id=""):
    """Create (when there is no recipe yet), save, and publish a recipe: POST /recipes/ ->
    POST /recipes/{id} -> transition test -> transition published. Returns card() of the
    result. READ_ONLY refuses before the first call; each step is a single attempt. A step
    that fails after the create raises RecipeWriteError carrying the new id."""
    core._check_read_only("publish a recipe to PixAI")
    rid = str(recipe_id or "").strip()
    if rid:
        _checked_id(rid)
    body = update_body(rid or "0", draft)            # every local check before any write
    showcase = body["showcaseMediaIds"]
    if len(showcase) < SHOWCASE_MIN:
        raise core.PixAIError("Still needed: {} more showcase image{}".format(
            SHOWCASE_MIN - len(showcase), "" if SHOWCASE_MIN - len(showcase) == 1 else "s"))
    if rid:
        # A resume (an earlier publish created this recipe, then a later step failed or its
        # answer was lost): read it and carry on from its LIVE status, never backwards --
        # re-sending the save and "to test" on a recipe that already went out would pull a
        # published recipe back into test (review finding 3).
        live = core._rest_get(session, "/recipes/" + rid) or {}
        status = str(live.get("status") or "")
        if status == "published":
            return card(live)
        if status == "archived":
            raise RecipeWriteError("This recipe is archived on PixAI — unarchive it in Mine",
                                   "RECIPE_ARCHIVED", rid)
        if status not in ("draft", "test"):
            raise RecipeWriteError("PixAI didn't say where this recipe stands; nothing was "
                                   "sent", "", rid)
    else:
        created = _post(session, "/recipes/", {})
        rid = str(created.get("id") or "")
        if not rid:
            raise RecipeWriteError("PixAI didn't return the new recipe's id")
        status = str(created.get("status") or "draft")
    body["id"] = rid
    try:
        saved = _post(session, "/recipes/" + rid, _without_id(body))
        status = str(saved.get("status") or status)
        if status == "draft":
            saved = _post(session, "/recipes/{}/transition".format(rid), {"to": "test"})
            status = str(saved.get("status") or "")
        if status == "test":
            saved = _post(session, "/recipes/{}/transition".format(rid),
                          {"to": "published", "showcaseMediaIds": showcase})
    except RecipeWriteError as e:
        e.recipe_id = rid
        raise
    return card(saved)


def _without_id(body):
    """The update body minus `id`: the path carries it (the site's oRPC client does the
    same with a path parameter)."""
    return {k: v for k, v in body.items() if k != "id"}


def update(session, recipe_id, draft, version=None):
    """Save changes to an existing recipe (full replace), then read it back: a published
    recipe PixAI sends back to review reads status `test`. `version` is the recipe's
    version when the creator opened it; a recipe changed since (on PixAI's own site) is
    refused rather than overwritten (review finding 9)."""
    core._check_read_only("change a recipe on PixAI")
    rid = _checked_id(recipe_id)
    body = update_body(rid, draft)
    if version is not None:
        live = core._rest_get(session, "/recipes/" + rid) or {}
        if live.get("version") is not None and str(live.get("version")) != str(version):
            raise RecipeWriteError("This recipe changed on PixAI since you opened it — "
                                   "reopen it from Mine to see the new version",
                                   "RECIPE_VERSION_MOVED")
    _post(session, "/recipes/" + rid, _without_id(body))
    try:
        return detail(session, rid)
    except Exception:                                        # noqa: BLE001
        return {"id": rid, "status": ""}


def transition(session, recipe_id, to):
    """Archive or unarchive a recipe (the two status changes Mine offers)."""
    if to not in ("archived", "published"):
        raise core.PixAIError("Only archive and unarchive are offered")
    core._check_read_only("change a recipe's status on PixAI")
    rid = _checked_id(recipe_id)
    return card(_post(session, "/recipes/{}/transition".format(rid), {"to": to}))


def set_create(session, title):
    title = str(title or "").strip()
    if not title:
        raise core.PixAIError("Name the set")
    if len(title) > 100:
        raise core.PixAIError("A set's name is up to 100 characters")
    core._check_read_only("create a recipe set on PixAI")
    try:
        c = core._rest_post(session, "/collection/", {
            "title": title, "description": "", "contentType": "recipe",
            "visibility": "private", "coverMode": "single"}) or {}
    except core.PixAIError as e:
        raise core.PixAIError("PixAI didn't make the set: " + str(e)[:160])
    return collection(c)


def set_toggle(session, set_id, recipe_id, on, item_id=""):
    """Put a recipe in a set or take it out. Returns {contains, item_id}."""
    sid = _checked_id(set_id)
    rid = _checked_id(recipe_id)
    core._check_read_only("change a recipe set on PixAI")
    try:
        if on:
            d = core._rest_post(session, "/collection/{}/items".format(sid),
                                {"refType": "recipe", "refId": rid}) or {}
            return {"contains": bool(d.get("saved", True)), "item_id": str(d.get("itemId") or "")}
        iid = _checked_id(item_id)
        d = _rest_delete(session, "/collection/{}/items/{}".format(sid, iid)) or {}
        return {"contains": bool(d.get("saved", False)), "item_id": ""}
    except core.PixAIError as e:
        raise core.PixAIError("PixAI didn't change the set: " + str(e)[:160])
