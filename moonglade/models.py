"""
moonglade/models.py
===================
PixAI's models: the model searches (the GraphQL connection, the /v2 REST search, the Market
query and its filter tables, bookmarks, the workflow catalog), version resolution and its meta
(`resolve_version_meta`, `list_model_versions`, `resolve_latest_version`), LoRA compatibility,
the model-version document and its readers (`_model_version_gql`, `model_name_gql`,
`resolve_model_base_id`), the inference profiles (`_model_profiles`, `_profile_listing`), the
per-model image gate (banner through `_refuse_lost_upscale`) and `generation_model_brief`. Moved
verbatim out of moonglade/backup.py in the 3.22 split (phase 5).

The names it reads from the engine (gql_adhoc, _rest_get, PixAIError, vlog, _GEN_MODEL_Q, and
the Unlimited Mode and LoRA-weight names the gate reads) are imported from moonglade.backup, or
from the split module that holds them now, inside each function that uses them, at call time,
so a test's patch of backup's binding still reaches them and importing this module never imports
the engine.
"""
import datetime
import time


def model_search_gql(session, keyword="", limit=15, base_only=False, lora_only=False):
    """Search PixAI generation models by keyword via the `generationModels`
    connection. Returns a list of {title, type, model_id, version_id}.

    IMPORTANT: createGenerationTask's `modelId` wants the *version* id, not the
    model id. The search node's `id` is the MODEL id (which generation rejects);
    `latestVersion.id` is the generatable version id. So we surface version_id as
    the value to feed into --generate.

    base_only=True drops LoRA / video types -- a LoRA can't be the BASE model
    (generation fails), so the base-model picker filters them out. LoRAs belong in
    the separate LoRA picker."""
    from moonglade.backup import gql_adhoc
    q = ("query($k:String,$n:Int){ generationModels(keyword:$k, first:$n){ "
         "edges { node { id title type isNsfw likedCount latestVersion { id } "
         "media { id urls { url } } } } } }")
    data = gql_adhoc(session, q, {"k": keyword, "n": limit})
    out = []
    for e in (data.get("generationModels") or {}).get("edges") or []:
        n = e.get("node") or {}
        mtype = (n.get("type") or "").upper()
        if base_only and ("LORA" in mtype or "VIDEO" in mtype):
            continue
        if lora_only and "LORA" not in mtype:
            continue
        out.append({
            "title": n.get("title") or "",
            "type": n.get("type") or "",
            "is_nsfw": bool(n.get("isNsfw")),
            "liked_count": int(n.get("likedCount") or 0),
            "model_id": str(n.get("id") or ""),
            "version_id": str((n.get("latestVersion") or {}).get("id") or ""),
            "preview_url": _model_preview_url(n.get("media")),
        })
    return out


def _model_preview_url(media):
    """Pick a directly-displayable cover thumbnail from a generationModels node's
    `media.urls`. The CDN list is [orig, thumb, stillThumb]; the `thumb` variant is
    the right size for a picker and needs no auth. Falls back to the first url."""
    urls = [u.get("url") for u in ((media or {}).get("urls") or []) if u.get("url")]
    return next((u for u in urls if "/thumb/" in u), urls[0] if urls else "")


def _row_should_blur(node):
    """Whether the picker must blur this model's cover -- ONE rule for BOTH row sources.

    model_search_rest (REST /generation-model/search) and _market_row (the GraphQL
    `generationModels` node, serving Market + Bookmarks) are documented as producing the
    SAME interchangeable row shape, and the picker renders them in one grid -- but they
    disagreed on this field: REST read the API's own `flag.shouldBlur`, GraphQL read the raw
    `isNsfw` content flag. So the same model blurred on one tab and not the other, and a
    keyword search and a Market browse of one grid gave different answers about identical
    content (M02, 2026-07-27).

    The rule, in order:

    1. The API's own `shouldBlur`, wherever the payload carries it (`flag.shouldBlur` on a
       REST row, a node-level `shouldBlur` on a GraphQL one). It is the authoritative answer
       because it is the only one computed against the VIEWER's content settings -- an
       account that has opted into seeing this content gets False here for a model whose
       `isNsfw` is perfectly true.
    2. Failing that, `isNsfw` -- the raw content flag, which knows nothing about the viewer.

    PREFERRING a field is worthless unless a query SELECTS it: the first pass at this bug
    added the preference while both GraphQL documents still asked only for `isNsfw`, so every
    real Market/Bookmarks row took branch 2 and the behaviour was byte-for-byte what the
    finding described (M02 round 2, 2026-07-27). `_model_conn_query` now asks for the field;
    branch 2 is the honest fallback for the row shapes that genuinely cannot carry it -- if
    their schema turns out not to expose the field at all, the degraded Market/Bookmarks
    projection that helper falls back to.

    Ambiguity resolves toward blurring, never away from it: a row that carries neither key
    reads False, but a row flagged NSFW with no viewer-scoped answer blurs -- including on
    the REST path, where `flag.shouldBlur` used to be read with a bare `.get()` so a row that
    simply omitted it showed an NSFW cover unblurred. That direction has a cost and it is
    chosen, not overlooked: if PixAI ever stops sending the flag on a row, an opted-in viewer
    gets blur they did not ask for and can clear with one click, where the other direction
    puts an NSFW cover on the screen of someone who never opted in at all."""
    node = node or {}
    flag = node.get("flag") if isinstance(node.get("flag"), dict) else {}
    for src in (flag, node):
        v = src.get("shouldBlur")
        if v is not None:
            return bool(v)
    return bool(node.get("isNsfw") or flag.get("isNsfw"))


def model_search_rest(session, keyword="", usage="MODEL", size=24, offset=0):
    """Search models/LoRAs via the oRPC GET /v2/generation-model/search endpoint. Unlike
    the GraphQL `generationModels` connection (which conflates base models + LoRAs), this
    cleanly separates them by `usageType` (MODEL vs LORA) and returns cover thumbnails.
    Returns {results:[{title, type, model_id, liked_count, should_blur, preview_url,
    has_version}], has_more}. Read-only (no spend). NOTE: `model_id` is the MODEL id --
    resolve the generatable version id with resolve_latest_version() on selection."""
    from moonglade.backup import _rest_get
    params = {"usageType": (usage or "MODEL").upper(),
              "size": max(1, min(int(size), 50)), "offset": max(0, int(offset))}
    kw = (keyword or "").strip()
    if kw:
        params["keyword"] = kw
    data = _rest_get(session, "/generation-model/search", params=params) or {}
    out = [rest_model_row(m) for m in data.get("data") or [] if isinstance(m, dict)]
    return {"results": out, "has_more": bool(data.get("hasMore"))}


def rest_model_row(m):
    """One model object as /v2 REST hands it (the /generation-model/search row, and the `model`
    of a model collection's item -- the same object, probe 2026-10-03) -> the picker's row.
    Shared so the Saved tab's cards and the search's cards can never drift apart."""
    med = m.get("media") or {}
    # Real field names (probed 2026-07-04): the rich description lives under
    # `modelDescription`, base-model family under `category`, and an official
    # badge under `curations` (e.g. ["inhouse"]). See ../moonglade-internal/private/GENERATOR_SURFACE.md.
    cur = m.get("curations") or []
    return {
        "title": m.get("title") or "",
        "type": m.get("type") or "",
        "model_id": str(m.get("id") or ""),
        "liked_count": int(m.get("likedCount") or 0),
        # Shared with _market_row so both paths blur the same model the same way --
        # this row keeps its authoritative flag.shouldBlur, and a row that somehow
        # arrives without one now falls back to isNsfw instead of silently not blurring.
        "should_blur": _row_should_blur(m),
        # publicUrl preferred (matches cover_url below): PixAI's own thumbnailUrl is a
        # small, often blurry auto-thumb -- fine as a last-resort fallback, poor as the
        # grid card's main image. loading="lazy" on the <img> bounds the cost to what's
        # actually on screen.
        "preview_url": med.get("publicUrl") or med.get("thumbnailUrl") or "",
        "has_version": bool(m.get("hasLatestAvailableVersion")),
        # Rich surface for the preview pop-out card.
        "description": (m.get("modelDescription") or "")[:600],
        "base_model": m.get("category") or "",
        "curations": [c for c in cur if isinstance(c, str)],
        "official": any((c or "").lower() == "inhouse" for c in cur if isinstance(c, str)),
        "comment_count": int(m.get("commentCount") or 0),
        "ref_count": int(m.get("refCount") or 0),
        "author_id": str(m.get("authorId") or ""),
        "cover_url": med.get("publicUrl") or med.get("thumbnailUrl") or "",
        # GraphQL-only per-viewer state absent here -> False, the mirror of
        # model_search_market_gql's "REST-only rich fields absent here -> empty so the
        # card hides them". This endpoint carries no bookmarked/liked equivalent at all,
        # so False means "this path can't tell you", NOT "confirmed not bookmarked" --
        # exactly like `official: False` on a GraphQL row. Present-and-falsy (rather than
        # missing) so a consumer can read the key off either path's rows.
        "bookmarked": False, "liked": False,
    }


# Model-Market categories the GraphQL `generationModels` connection actually honors (probed
# 2026-07-04). NOTE 'concept' is NOT a real server value (returns empty) -- excluded.
# PixAI's own nine, in their own order. Confirmed 2026-07-26 from the training page, where
# their category dropdown is currently rendering RAW i18n keys
# ("market:lora-categories.animal.label", ...) -- a bug on their side that handed over the
# canonical list. We were short two: **animal** and **realistic**. `detail` is their
# "Detail Enhancement".
MARKET_CATEGORIES = ("character", "animal", "style", "realistic", "pose", "clothing",
                    "background", "detail", "other")

# GenerationModelType enum members this app is willing to put INTO a query document, for
# generationModels(loraBaseModelTypes:[...]) -- see model_search_market_gql's lora_base_type
# argument. Only these five: the architectures confirmed to exist as a LoRA's BASE family.
# (MULTI_LORA is a LoRA's OWN type and VIDEO_MODEL is not an image base, so neither is ever a
# legitimate value here and both are deliberately absent.)
#
# This MUST stay a fixed whitelist. A GraphQL enum is a bare token, not a string -- it cannot
# be bound as a $variable, so the value is interpolated into the query text, exactly like
# MARKET_CATEGORIES above and for exactly the same reason: caller-supplied text must never
# reach a query document. Anything not listed here is silently ignored and the search runs
# UNFILTERED -- fail-open, the same way a non-whitelisted `category` is dropped. An unknown or
# newly-added architecture must degrade to "no server-side filter" (the per-row
# annotate_lora_compat badge still tells the truth), never to a rejected query that would
# break LoRA browsing outright.
LORA_BASE_MODEL_TYPES = ("SDXL_MODEL", "SD_V1_MODEL", "SD3_MEDIUM_MODEL",
                         "DIT7_MODEL", "DIT7A_MODEL", "DIT7B_MODEL", "DIT7C_MODEL",
                         "DIT7D_MODEL", "DIT9_MODEL",
                         "MMDIT26A_MODEL", "MMDIT26B_MODEL", "USER_DIT26A_MODEL",
                         # A user-TRAINED DiT.3 (Tsubaki.3 architecture). Read from PixAI's
                         # bundle 2026-09-26 (ModelFilter.helper's `userdit26` group), not a
                         # live request -- SCOPE_2026-09-26 G8.
                         "USER_DIT26B_MODEL",
                         "Z_IMAGE_V1_MODEL")

# Their Model Type filter, as a label -> enum mapping. The first four rows are MEASURED off live
# requests (drove their base-model picker 2026-07-26 and read what it sent); the last two are
# inferred from the naming and are marked as such rather than presented as fact.
#
# Two behaviours of their filter worth copying, both observed rather than assumed:
#   * "All" sends types:["ANY_MODEL"] -- it does not omit the argument.
#   * It is MULTI-SELECT. Choosing DiT.3 then DiT.1 sent types:["MMDIT26B_MODEL","DIT7_MODEL"].
#     A single-value control here would silently be the wrong shape.
# PixAI's four market sorts, every value captured off a live request 2026-07-26. `feed` selects
# the backend ranking and `orderBy` the field within it; Trending needs no orderBy because the
# trending feed IS the ordering.
#
# `markInfo.refCount` is the "uses" figure printed on their cards -- the same field identified
# earlier as the number on a card -- so Most Used is genuinely most-used, not most-liked again.
#
# One difference deliberately NOT copied: their trending and latest feeds page BACKWARD
# (`last`/`before`) while meilisearch pages forward (`first`/`after`). This app pages forward
# everywhere, which the connection accepts for all four, and switching direction per sort would
# mean two cursor conventions in one picker for no user-visible gain.
#
# `relevance` is the fifth pair and NOT one of the four the picker offers: it is where a
# KEYWORD search under Trending or Latest goes instead (owner walk 2026-09-07, "searching for a
# known LoRA fails"). meilisearch with an EMPTY orderBy is PixAI's relevance ranking; see
# model_search_market_gql's keyword handling for the measurements that establish it.
MARKET_SORTS = {
    "trending":   ("trending", ""),
    "liked":      ("meilisearch", "-markInfo.likedCount"),
    "used":       ("meilisearch", "-markInfo.refCount"),
    "newest":     ("latest", "-createdAt"),
    "relevance":  ("meilisearch", ""),
}
# What the old two-button UI sent, kept working so an older client or a bookmarked URL does not
# silently lose its sort.
MARKET_SORT_ALIASES = {"popular": "trending", "latest": "newest", "": "trending"}


def market_sort(name):
    """(feed, orderBy) for a sort name, falling back to Trending for anything unrecognised."""
    key = (name or "").strip().lower()
    key = MARKET_SORT_ALIASES.get(key, key)
    return MARKET_SORTS.get(key, MARKET_SORTS["trending"])


# ALL SEVEN MEASURED off live requests (2026-07-26) -- none is inferred from its name.
#
# One exception, dated: "Community DiT" maps to a PAIR since 2026-09-26 (SCOPE_2026-09-26 G8).
# USER_DIT26A_MODEL is the 2026-07-26 measurement; USER_DIT26B_MODEL (a user-trained DiT.3)
# was read from PixAI's BUNDLE, not a live request -- ModelFilter.helper groups the two as
# `userdit26: ["USER_DIT26A_MODEL", "USER_DIT26B_MODEL"]` and its one Community DiT option
# sends both. No new chip, no new label: the existing option expands to the pair.
MODEL_TYPE_FILTERS = (
    ("All", "ANY_MODEL"),
    ("DiT.3", "MMDIT26B_MODEL"),
    ("DiT.2", "MMDIT26A_MODEL"),
    ("DiT.1", "DIT7_MODEL"),
    ("Community DiT", ("USER_DIT26A_MODEL", "USER_DIT26B_MODEL")),
    ("SDXL", "SDXL_MODEL"),
    ("SD 1.5", "SD_V1_MODEL"),
)
# HOW THESE WERE CAPTURED, because the technique is reusable and three attempts failed first.
# Apollo's cache is IN-MEMORY, so a full page reload empties it; selecting a filter as the very
# FIRST action on a fresh load therefore has to hit the network. Earlier tries kept selecting
# other options first, and the cache could always answer.
#
# "Community DiT" was the last unknown and the one worth not guessing: USER_DIT26A_MODEL turned
# out to be right, but DIT9_MODEL was equally plausible, and a wrong enum member here fails
# SILENTLY -- the wrong rows, or none, reading as an empty result rather than an error.
#
# The filter is MULTI-SELECT: successive clicks sent ["USER_DIT26A_MODEL"], then
# [..., "SDXL_MODEL"], then [..., "SD_V1_MODEL"], which is also what settled the last two.
#
# The full 46-member GenerationModelType enum is not copied here on purpose. It is
# recoverable at any time, and stays current, via the harvester (moved 2026-09-06 to
# ../moonglade-internal/tools/harvest_api_surface.py) -- their
# own contract chunk carries it verbatim. A hand-copied list would just rot.

# Their "Source" filter (All / PixAI / External) is NOT a separate argument -- it is expressed
# through `types`. Read straight out of their ModelFilter chunk, which maps the UI value to an
# enum member and back:
#     .with({type:"lora", source:"pixai"},    () => [AnyUserLora])
#     .with({type:"lora", source:"external"}, () => [AnyNonUserLora])
# and the tokens themselves are in the bundle: ANY_LORA / ANY_USER_LORA / ANY_NON_USER_LORA
# (ANY_SDXL_LORA and ANY_NON_SDXL_LORA also exist, unused here).
#
# A LoRA the OWNER trained carries type USER_MULTI_LORA -- seen on his own rows -- which is why
# "PixAI" means user-trained and "External" means uploaded from elsewhere.
LORA_SOURCE_TYPES = {
    "": "",                          # All -- send no `types` at all, preserving today's behaviour
    "pixai": "ANY_USER_LORA",
    "external": "ANY_NON_USER_LORA",
}

# Their License Type filter has exactly ONE meaningful value. Their handler is literally
#     onChange: r => a("permittedUse", r === "COMMERCIAL" ? "COMMERCIAL" : undefined)
# so it is COMMERCIAL or the argument is omitted. PermittedUse:COMMERCIAL was also observed on a
# real row. The data behind it is extra.permissions{personalUses, commercialUses,
# shareImagesOnline, shouldCreditAuthor}.
PERMITTED_USES = ("COMMERCIAL",)

# Their "Posted at" options, and the offset each one means. Captured from the live request: the
# UI sends a DateRange of {"gt": "<ISO instant>"} and nothing else -- no upper bound, no `lt`.
POSTED_AT_DAYS = {"yesterday": 1, "7d": 7, "30d": 30}


def posted_at_range(token):
    """One of POSTED_AT_DAYS -> the DateRange dict PixAI expects, or None for "All Time".

    Measured, not guessed: selecting Past 7 Days on 2026-07-26 sent
    {"gt": "2026-07-19T07:00:00.000Z"}. Note what that value is NOT -- it is not
    now-minus-168-hours. 07:00:00.000Z is local MIDNIGHT at UTC-7, so the boundary is the start
    of the day N days back, in the viewer's own timezone. Matching that matters for more than
    tidiness: a start-of-day boundary is a stable cache key, whereas a rolling
    now-minus-N-seconds mints a fresh one on every keystroke and would defeat their caching (and
    ours) for no benefit.

    Milliseconds and a literal Z, matching JSON.stringify(new Date()) in their client. An
    unrecognised token returns None, so the filter is simply absent and the search runs
    unfiltered -- the same fail-open contract as every other filter here."""
    days = POSTED_AT_DAYS.get((token or "").strip().lower())
    if not days:
        return None
    local_midnight = (datetime.datetime.now().astimezone()
                      .replace(hour=0, minute=0, second=0, microsecond=0)
                      - datetime.timedelta(days=days))
    utc = local_midnight.astimezone(datetime.timezone.utc)
    return {"gt": utc.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(utc.microsecond // 1000)}

# CORRECTION, 2026-07-26. Comments in this file state that "an enum cannot be a $variable", which
# is why `loraBaseModelTypes` is interpolated behind a whitelist. That claim is WRONG: PixAI's own
# query documents declare `$types: [GenerationModelType]`, `$permittedUse: PermittedUse` and
# `$loraBaseModelTypes: [GenerationModelType!]` and bind them normally. Verified by reading their
# documents (../moonglade-internal/tools/harvest_api_surface.py).
#
# So the filters added below are BOUND VARIABLES, never interpolated -- caller text cannot reach
# the query document at all, which is strictly safer than interpolating it after a whitelist
# check. The whitelists stay, for a different reason worth keeping: an unrecognised value is
# DROPPED so the search runs unfiltered (fail-open), rather than binding a bad enum and having the
# server reject the whole query. That is the behaviour the existing filters promise and the picker
# depends on. The older interpolated path is left alone deliberately -- it works, it is guarded,
# and rewriting it is a separate change with its own risk.


def _market_row(n):
    """One `generationModels`-shaped node -> the picker's row dict.

    Extracted 2026-07-26 so the BOOKMARK tab returns rows that are IDENTICAL to MARKET's, field
    for field. Two near-copies of a 20-field dict is how a picker ends up rendering a card that
    silently loses its architecture badge on one tab only."""
    lv = n.get("latestVersion") or {}
    return {
        "title": n.get("title") or "",
        "type": n.get("type") or "",
        "model_id": str(n.get("id") or ""),
        "liked_count": int(n.get("likedCount") or 0),
        # Was `bool(n.get("isNsfw"))` -- the REST sibling read the API's own shouldBlur, so
        # one model blurred on Search and not on Market/Bookmarks. Both documents that feed
        # this function now SELECT the viewer-scoped flag (see _MODEL_BLUR_FIELD), and both
        # rows go through the one rule.
        "should_blur": _row_should_blur(n),
        "preview_url": _model_preview_url(n.get("media")),
        "has_version": bool(lv.get("id")),
        # REST-only rich fields absent here -> empty so the card hides them.
        "description": "", "base_model": "", "curations": [], "official": False,
        "comment_count": 0, "ref_count": 0, "author_id": "",
        "cover_url": _model_preview_url(n.get("media")),
        # GraphQL-only extras.
        "tags": [t.get("name") for t in (n.get("tags") or []) if t.get("name")][:8],
        "author": (n.get("author") or {}).get("displayName") or "",
        "created_at": n.get("createdAt") or "",
        # Architecture, for LoRA compat sort/badging (annotate_lora_compat) -- '' when
        # the connection has no version yet, same empty-string convention as everywhere
        # else in this file (never None, so a naive .strip()/comparison never explodes).
        "model_type": lv.get("modelType") or "",
        "lora_base_model_type": lv.get("loraBaseModelType") or "",
        # Per-viewer state (GraphQL-only). Always a real bool -- a node that omits the
        # field yields False, never None, same never-None rule as the two fields above.
        "bookmarked": bool(n.get("bookmarked")),
        "liked": bool(n.get("liked")),
    }


# The viewer-scoped blur flag, as a GraphQL leaf on a generationModels node. Requested by
# both model-connection documents through _model_conn_query below.
#
# UNPROBED, and treated as such. `flag.shouldBlur` is confirmed on the REST search row
# (2026-07-04); the same name on the GraphQL node is an inference from PixAI's own REST/GQL
# naming, not something read off a live reply. A field the schema does not have is a REJECTED
# QUERY -- the whole page, not just that leaf -- and this file's standing rule (see the
# un-guessed DateRange shape above) is that the picker must never break on a field we guessed.
# Hence: ask once per process, and if the enriched document is refused, re-run the SAME search
# without the field and remember the answer. Cost if the guess is wrong is one extra request
# per process and the pre-existing isNsfw behaviour; cost of not asking at all is that
# _row_should_blur's preference can never fire on a live row, which is the bug itself.
_MODEL_BLUR_FIELD = "shouldBlur"
# None = not asked yet this process, True = PixAI answered it, False = refused, stop asking.
_model_blur_supported = None
# A refusal has to REPEAT before it is believed. `gql_adhoc` raises PixAIError for a 200
# carrying an `errors` array -- which is the shape of PixAI's transient "Internal server
# error" as well as of a rejected field -- so a single refusal is not evidence about the
# schema at all. Latching on one blip permanently demoted Market/Bookmarks back to `isNsfw`
# for the life of a long-running gallery process, silently reopening the very disagreement
# this field was added to close. A genuinely absent field is refused EVERY time; a blip is
# not, so two consecutive refusals separate them without matching on error wording.
_model_blur_refusals = 0
_MODEL_BLUR_REFUSALS_BEFORE_GIVING_UP = 2


def _model_conn_query(session, build, variables):
    """Run a model-connection document that ASKS for `_MODEL_BLUR_FIELD`, degrading once.

    `build(leaf)` returns the query text with `leaf` spliced into the node projection ("" for
    the original, field-less document).

    The degrade is deliberately NOT keyed on the wording of PixAI's error -- an error string
    match is a guess about a guess, and the failure it would miss is a dead Market tab. It is
    keyed on evidence instead: if the enriched document is refused and the identical document
    WITHOUT the field then succeeds, the field is the LIKELY culprit -- but only likely, since
    a transient 200-with-errors looks identical and would pass on the retry by then having
    cleared. So one such observation is not acted on; the latch goes off (and every later call
    in this process skips the field) only once refusals repeat CONSECUTIVELY, which a missing
    field does every time and a blip does not. If the plain document fails
    too, this was a real outage/auth failure -- that exception propagates untouched (one extra
    request on that path, deliberately) and the latch is left alone, so the next process asks
    again.

    No lock, unlike `_warn_media_tls_once`'s latch next door: two gallery threads racing here
    cost one duplicate probe and then agree, whereas two threads racing that one would print
    the same twenty-line TLS paragraph twice."""
    from moonglade.backup import gql_adhoc, PixAIError, vlog
    global _model_blur_supported, _model_blur_refusals
    if _model_blur_supported is False:
        return gql_adhoc(session, build(""), variables)
    try:
        data = gql_adhoc(session, build(_MODEL_BLUR_FIELD + " "), variables)
    except PixAIError as e:
        plain = gql_adhoc(session, build(""), variables)
        _model_blur_refusals += 1
        if _model_blur_refusals >= _MODEL_BLUR_REFUSALS_BEFORE_GIVING_UP:
            _model_blur_supported = False
            vlog("model connection refused `{}` {} times ({}); retried without it -- blur "
                 "falls back to isNsfw for the rest of this run".format(
                     _MODEL_BLUR_FIELD, _model_blur_refusals, str(e)[:160]))
        else:
            vlog("model connection refused `{}` ({}); retried without it and will ask again "
                 "-- one refusal is as likely to be a transient error as a missing field"
                 .format(_MODEL_BLUR_FIELD, str(e)[:160]))
        return plain
    _model_blur_supported = True
    _model_blur_refusals = 0        # a success clears the tally: only CONSECUTIVE refusals count
    return data


def model_search_market_gql(session, keyword="", category="", sort="", usage="MODEL", limit=24,
                            after=None, lora_base_type="", author_id="",
                            source="", permitted_use="", time_range=None,
                            model_types=()):
    """Market-style model browse via the GraphQL `generationModels` connection, which -- unlike
    the REST /search -- actually HONORS `category` and a date `orderBy`. Use this for category
    chips + a Newest sort; the REST path (model_search_rest) stays the default for keyword/Popular
    because its rows are richer (description/refCount/official). Returns the SAME row shape as
    model_search_rest so the picker renders both interchangeably (REST-only fields come back
    empty and the card hides them), plus GraphQL-only extras: tags + created_at + author.

    category: one of MARKET_CATEGORIES (ignored if not). sort: 'newest' -> orderBy -createdAt;
    anything else -> the connection's default order. A non-empty `keyword` re-points a RANKING
    feed (trending/latest) at the relevance one -- see the feed selection below for why and for
    the 2026-09-07 measurements. usage MODEL/LORA splits base vs LoRA rows (the connection
    conflates them). Read-only, no spend.

    `latestVersion` also requests modelType/loraBaseModelType (picker-parity-round2,
    2026-07-24) -- confirmed live: real rows come back e.g. modelType:"MULTI_LORA",
    loraBaseModelType:"SD_V1_MODEL". Costs nothing extra (same request, no additional
    round trip) and is what lets api_model_search's LoRA path do architecture-aware
    sort/badging (see annotate_lora_compat) through this GraphQL connection, which -- unlike
    REST's oRPC search -- actually carries this per-row. Surfaced as `model_type` /
    `lora_base_model_type`, the SAME key names model_search_rest's sibling
    resolve_version_meta() already uses, so callers don't care which path produced a row.

    `bookmarked` + `liked` (2026-07-24) are VIEWER-SCOPED booleans GenerationModel carries on
    every connection that returns one -- probed live: bookmarked:true on 50/50 rows of the
    owner's own bookmark connection, false on 3/3 plain market rows. Genuinely free (two more
    leaf fields on a request the picker already makes, no extra round trip). REST's oRPC
    /search has NO equivalent, so model_search_rest defaults both to False and callers must
    read False as "this path can't tell you" rather than "confirmed not bookmarked" -- the
    same convention as `official` in the other direction. Nothing renders them yet; the picker
    tab that consumes them is separate, later work.

    after=<cursor> (owner report 2026-07-24: the picker "scrolls a few rows and stops"):
    forward Relay-cursor paging -- standard `edges`/`pageInfo` connection shape, the same
    spec this app already relies on elsewhere (page_variables' before/last cursor pagination
    for task history, just the other direction). has_more was ALREADY computed correctly
    from pageInfo.hasNextPage; the real gap was that the query never requested endCursor and
    never accepted an after: argument, so a client had no way to actually ask for the next
    page even knowing one existed. Omitted entirely (not sent as an empty string) when
    absent -- a present-but-empty $a may not mean the same thing to PixAI's resolver as no
    $a at all, and this is the first page of a fresh search either way. next_cursor in the
    return is '' whenever has_more is false, even if the server's own endCursor is
    non-empty -- never hand a caller a cursor that would page forever on an exhausted list.

    lora_base_type=<GenerationModelType> (2026-07-24): SERVER-SIDE architecture filtering for
    LoRA search, via an argument this connection has accepted all along and this app never
    used -- generationModels(loraBaseModelTypes:[MMDIT26A_MODEL], ...). Ignored unless
    usage=LORA (nothing to filter a base-model list by) and unless the value is in
    LORA_BASE_MODEL_TYPES; see that tuple for why the whitelist is mandatory rather than
    defensive. Measured live: [MMDIT26A_MODEL] returned 23 of 24 rows compatible with a
    DiT.2 base, against 24-of-24 SD_V1 with no filter at all -- which is the wall that made
    LoRA browsing useless for anything but SD 1.5.

    GOTCHA, and it cost real time once already: the values are UNQUOTED GraphQL ENUM tokens.
    An earlier probe sent them as JSON strings (["MMDIT26A_MODEL"]), got a type error back,
    and the error was misread as "this argument doesn't exist" -- so the whole capability sat
    unused for weeks. Enums also cannot be bound as $variables, which is why this one value
    is interpolated while `keyword` stays a bound variable.

    The filter is APPROXIMATE, not strict: [DIT7B_MODEL] measured back 12 DiT7B rows, 10
    MMDIT26A and 2 SDXL. A search row's `loraBaseModelTypes` is a coarse browse hint (a union
    over the model's releases), not the resolved version's singular `loraBaseModelType`. So
    this narrows the candidate pool cheaply and annotate_lora_compat() remains the precise
    per-row layer on top -- do not treat the filter as a substitute for the badge."""
    cat = (category or "").strip().lower()
    # category/orderBy come from a fixed whitelist -> safe to interpolate; keyword stays a
    # bound $variable (never interpolate user text into a query).
    args = ["keyword:$k", "first:$n"]
    if cat in MARKET_CATEGORIES:
        args.append('category:"%s"' % cat)
    # Sort is a FEED plus an orderBy, both from a fixed table -- safe to interpolate, and an
    # unrecognised name falls back to Trending rather than producing a broken query.
    feed, order_by = market_sort(sort)
    # A KEYWORD goes to a search index, never to a ranking feed (owner walk 2026-09-07:
    # "searching for a known LoRA fails" / "it's always the SAME LoRA"). `trending` and `latest`
    # are RANKINGS: the connection accepts `keyword` alongside them and returns the ranking
    # anyway, so every term produced the same head row -- which is exactly what "always the same
    # LoRA" is. Measured live 2026-09-07 under lora_base_type=MMDIT26A_MODEL: on the trending
    # feed "Perfect Hands" -> "Extremely detailed...", "Large Bust"; "eyes" -> "Extremely
    # detailed..." again; and "qwxzv nonsense" -- a term nothing can match -- still returned
    # eight rows. On the meilisearch feed with an EMPTY orderBy (relevance), the same three:
    # "Perfect Hands" -> "JP Anime Perfect Hands", "perfect hand..."; "eyes" -> "beautiful eyes",
    # "miyako eyes"; "qwxzv nonsense" -> nothing. So a keyword under Trending or Latest is served
    # by MARKET_SORTS["relevance"] instead. `liked`/`used` are already meilisearch and keep their
    # orderBy -- they were measured returning exact matches first ("Perfect Hands SDXL") -- and a
    # search with no keyword is untouched, so plain browsing still gets the ranking feeds. The
    # base-type filter is orthogonal and stays on either way; its rows measured correct.
    if (keyword or "").strip() and feed in ("trending", "latest"):
        feed, order_by = MARKET_SORTS["relevance"]
    args.append('feed:"%s"' % feed)
    if order_by:
        args.append('orderBy:"%s"' % order_by)
    # Server-side architecture filter -- LoRA searches only (there is nothing to filter a
    # base-model list by). The value is a BARE ENUM TOKEN, unquoted: [MMDIT26A_MODEL], never
    # ["MMDIT26A_MODEL"]. Passing them as strings is a type error the server rejects, and
    # since an enum cannot be a $variable either, this is interpolated -- hence the
    # LORA_BASE_MODEL_TYPES whitelist gate, which also makes an unrecognized architecture
    # fall through to an unfiltered search rather than a rejected query.
    want_lora = (usage or "MODEL").upper() == "LORA"
    lbt = (lora_base_type or "").strip().upper()
    if want_lora and lbt in LORA_BASE_MODEL_TYPES:
        args.append("loraBaseModelTypes:[%s]" % lbt)
    after = (after or "").strip()
    var_decl = "$k:String,$n:Int"
    variables = {"k": keyword or "", "n": int(limit)}
    if after:
        args.append("after:$a")
        var_decl += ",$a:String"
        variables["a"] = after

    # --- picker-parity round 3 (2026-07-26). All BOUND variables, all fail-open: an
    # unrecognised value is dropped and the search runs unfiltered rather than being rejected.
    #
    # authorId is the whole "MY LORA" tab -- their own MY LORA is this same connection filtered
    # by the signed-in user's id, not a separate operation.
    au = str(author_id or "").strip()
    if au:
        args.append("authorId:$au")
        var_decl += ",$au:ID"
        variables["au"] = au

    # `types` is ALWAYS sent, which is what their own pickers do -- LoRA tabs send ANY_LORA even
    # with Source set to All, and the base-model tab sends ANY_MODEL. Both were read off live
    # requests.
    #
    # This is a fix, not just parity. We used to send no `types` at all and filter by row type in
    # Python after the fetch, so asking for 24 could yield a mixed page and hand the grid far
    # fewer once the wrong kind was discarded -- short pages, almost certainly the "scrolls a few
    # rows and stops" report. Filtering server-side means a full page of the kind actually wanted.
    #
    # An explicit Source (PixAI-trained / external) narrows further and replaces ANY_LORA; their
    # own MY LORA request pairs ANY_LORA with authorId exactly as this does.
    src = str(source or "").strip().lower()
    src_enum = LORA_SOURCE_TYPES.get(src, "") if want_lora else ""

    # A base search can also narrow to specific ARCHITECTURES -- their Model Type filter, which is
    # MULTI-SELECT (choosing DiT.3 then DiT.1 sends both tokens, observed on a live request). Only
    # whitelisted members survive, so an unknown value is dropped and the search stays unfiltered
    # rather than being refused: the same fail-open contract as every other filter here.
    chosen = [t for t in (str(x).strip().upper() for x in (model_types or []))
              if t in LORA_BASE_MODEL_TYPES]
    args.append("types:$ty")
    var_decl += ",$ty:[GenerationModelType]"
    if chosen and not want_lora:
        variables["ty"] = chosen
    else:
        variables["ty"] = [src_enum or ("ANY_LORA" if want_lora else "ANY_MODEL")]

    pu = str(permitted_use or "").strip().upper()
    if pu in PERMITTED_USES:
        args.append("permittedUse:$pu")
        var_decl += ",$pu:PermittedUse"
        variables["pu"] = pu

    # timeRange takes a DateRange input object. Its FIELD NAMES are not yet captured -- they are
    # not in any query document (input types never are) and the one promising bundle hit turned
    # out to be an unrelated error payload. So this passes the caller's dict straight through and
    # omits the argument entirely when there is nothing to send. Nothing constructs a DateRange
    # here on a guess: a wrong shape would be a rejected query, and the picker must never break
    # on a filter. Capture the shape from one live request (set Posted at -> Past 7 Days with the
    # network tab open and read `timeRange`), then the only change needed is in the caller.
    if isinstance(time_range, dict) and time_range:
        args.append("timeRange:$tr")
        var_decl += ",$tr:DateRange"
        variables["tr"] = time_range
    # `blur` is the viewer-scoped flag, spliced in by _model_conn_query so a schema that does
    # not carry it degrades to this same document without it rather than to a broken tab.
    def _q(blur):
        return ("query(" + var_decl + "){ generationModels(" + ", ".join(args) + "){ "
                "pageInfo{ hasNextPage endCursor } edges { node { id title type isNsfw "
                + blur + "likedCount bookmarked liked "
                "latestVersion { id modelType loraBaseModelType } media { id urls { url } } "
                "tags { name } author { displayName } createdAt } } } }")
    data = (_model_conn_query(session, _q, variables) or {}).get("generationModels") or {}
    out = []
    for e in data.get("edges") or []:
        n = e.get("node") or {}
        mtype = (n.get("type") or "").upper()
        is_lora = "LORA" in mtype
        if want_lora and not is_lora:
            continue
        if not want_lora and (is_lora or "VIDEO" in mtype):
            continue
        out.append(_market_row(n))
    page_info = data.get("pageInfo") or {}
    has_more = bool(page_info.get("hasNextPage"))
    return {"results": out, "has_more": has_more,
            "next_cursor": (page_info.get("endCursor") or "") if has_more else ""}


def _bookmark_node_fields(blur=""):
    """The bookmark node projection -- the same leaves the Market document asks for, so both
    tabs produce identical rows. `blur` is the viewer-scoped flag, spliced in (or not) by
    _model_conn_query; see _MODEL_BLUR_FIELD for why it is asked for conditionally."""
    return ("id title type isNsfw " + blur + "likedCount bookmarked liked "
            "latestVersion { id modelType loraBaseModelType } media { id urls { url } } "
            "tags { name } author { displayName } createdAt")


def model_bookmarks_gql(session, keyword="", usage="MODEL", limit=24, after=None,
                        lora_base_type=""):
    """The owner's BOOKMARKED models/LoRAs, in the SAME row shape as model_search_market_gql.
    Read-only, spends nothing.

    `listMyBookmarkedGenerationModels` is an operation NAME, not a field: its document queries
    `me { bookmarkedGenerationModels(...) }`. An earlier probe asked whether the operation name
    existed on type Query, got "Cannot query field ... on type Query", and that was recorded as
    "reachable ONLY through the persisted-query path". It does not follow -- the name was never a
    field, and `me` is plainly reachable ad-hoc (resolve_user_id uses `query{ me{ id } }`).

    So this reads AD-HOC with our own projection, and only that: the document cannot rot when
    PixAI redeploys, and it asks for exactly the fields a row needs. A refusal raises PixAIError
    (#92 retired the saved-request fallback, which rode the same key and the same `me`, so it
    could only ever succeed from a cache PixAI is retiring).

    The field accepts the same filters MARKET does -- keyword, modelTypes, loraBaseModelTypes,
    loraBaseModelIds -- plus full before/after/first/last paging, so the bookmark tab is not a
    stripped-down list. Note their own UI hides its Filters button on this tab while keeping the
    architecture filter live, which is consistent with what the arguments allow."""
    want_lora = (usage or "MODEL").upper() == "LORA"
    kw = (keyword or "").strip()
    after = (after or "").strip()
    lbt = (lora_base_type or "").strip().upper()

    args = ["first:$n"]
    var_decl = "$n:Int"
    variables = {"n": int(limit)}
    if kw:
        args.append("keyword:$k")
        var_decl += ",$k:String"
        variables["k"] = kw
    if after:
        args.append("after:$a")
        var_decl += ",$a:String"
        variables["a"] = after
    # Same reasoning as the market path: ask for the kind we want rather than discarding the
    # wrong kind afterwards, so a bookmark page arrives full. ANY_LORA is what their own bookmark
    # request sends for the LoRA tab; ANY_MODEL mirrors their base-model tab.
    args.append("modelTypes:$mt")
    var_decl += ",$mt:[GenerationModelType]"
    variables["mt"] = ["ANY_LORA" if want_lora else "ANY_MODEL"]
    if want_lora and lbt in LORA_BASE_MODEL_TYPES:
        args.append("loraBaseModelTypes:$lb")
        var_decl += ",$lb:[GenerationModelType!]"
        variables["lb"] = [lbt]

    def _q(blur):
        return ("query(" + var_decl + "){ me { id bookmarkedGenerationModels(" + ", ".join(args)
                + "){ totalCount pageInfo{ hasNextPage endCursor } edges { node { "
                + _bookmark_node_fields(blur) + " } } } } }")

    # Through _model_conn_query, not gql_adhoc directly: a refusal of the blur leaf is answered
    # by re-asking without it. Any other refusal propagates as the PixAIError it is (#92): the
    # route and the cached walk both report it, so the tab shows an error, not an empty list.
    data = _model_conn_query(session, _q, variables) or {}
    conn = ((data.get("me") or {}).get("bookmarkedGenerationModels")) or {}

    out = []
    for e in conn.get("edges") or []:
        n = e.get("node") or {}
        mtype = (n.get("type") or "").upper()
        is_lora = "LORA" in mtype
        # A bookmark list mixes base models and LoRAs exactly as the market connection does, so
        # the same split applies -- otherwise the LoRA tab shows base models and vice versa.
        if want_lora and not is_lora:
            continue
        if not want_lora and (is_lora or "VIDEO" in mtype):
            continue
        out.append(_market_row(n))

    page_info = conn.get("pageInfo") or {}
    has_more = bool(page_info.get("hasNextPage"))
    return {"results": out, "has_more": has_more,
            "next_cursor": (page_info.get("endCursor") or "") if has_more else "",
            "total": conn.get("totalCount")}


def workflow_catalog(session, first=80):
    """List PixAI enhance/panelplugin WORKFLOWS via the `workflows` GraphQL connection ->
    [{id, name, type, cover_media_id}]. `id` is the numeric workflowId that
    build_panelplugin_parameters wants. Covers upscale / remove-background / line-art /
    sketch-colorizer / inpaint / outpaint / style converters / etc. Read-only.

    Restored 2026-08-18 for the Bridge tier (drift §44). NOTE: a live probe (2026-08-16/17)
    found this connection returns ZERO entries on our credential, so the six mirror-gated
    Enhance presets do NOT self-populate from it -- they are addressed by hardcoded workflow
    ids/names in the /api/enhance caller. This is kept for /api/workflows parity and so the
    picker self-updates the day PixAI opens the connection to us."""
    from moonglade.backup import gql_adhoc
    q = "query($n:Int){ workflows(first:$n){ edges { node { id name type coverMediaId } } } }"
    d = gql_adhoc(session, q, {"n": int(first)}) or {}
    out = []
    for e in (d.get("workflows") or {}).get("edges") or []:
        n = e.get("node") or {}
        if not n.get("id"):
            continue
        out.append({"id": str(n["id"]), "name": n.get("name") or "",
                    "type": n.get("type") or "", "cover_media_id": str(n.get("coverMediaId") or "")})
    return out


def _empty_version_meta():
    return {"version_id": "", "model_type": "", "lora_base_model_type": "",
            "trigger_words": "", "negative_prompt": "", "sampling_method": "",
            "sampling_steps": None, "cfg_scale": None, "capabilities": [],
            "compatibility": {}, "restrictions": {}, "profiles": None,
            "quality_tag": None, "size_rule": None, "context_images": None,
            "color_palette": None, "unlimited": None, "profile_rows": None,
            "size_tiers": None, "context_max": None, "creativity": False}


def _version_quality_tag(extra):
    """The version's own Quality Tag booster value: extra.qualityTags[0] as {prefix, suffix}
    when either half is non-empty, else None (SCOPE_2026-09-26 G4, T3-07).

    PixAI's site takes the tag per version (modelParams `d=Array.isArray(u)&&u.length>0?
    {...u[0],...}:void 0`): SDXL/DiT.1 versions carry real tags, Tsubaki.3 publishes one
    with both halves empty, and Flash / Tsubaki.2 / some SDXL versions publish none. None
    therefore means "this version has no quality tag to add" -- the chip reads disabled and
    nothing is sent -- NOT "unknown"; an unreadable row never reaches this function."""
    tags = extra.get("qualityTags") if isinstance(extra, dict) else None
    if not isinstance(tags, list) or not tags or not isinstance(tags[0], dict):
        return None
    pre = tags[0].get("prefix")
    suf = tags[0].get("suffix")
    pre = pre if isinstance(pre, str) else ""
    suf = suf if isinstance(suf, str) else ""
    if not (pre.strip() or suf.strip()):
        return None
    return {"prefix": pre, "suffix": suf}


def _routed_default_negative(routed):
    """extra.routedNegativePrompts.default when the block parses as PixAI's own schema does
    it -- {default: string <= 4096, contextImage: string <= 4096}, BOTH keys (modelParams
    `pe`/`Q`) -- else None (SCOPE_2026-09-26 G5, T3-09)."""
    if not isinstance(routed, dict):
        return None
    d, c = routed.get("default"), routed.get("contextImage")
    if not (isinstance(d, str) and isinstance(c, str)):
        return None
    if len(d) > 4096 or len(c) > 4096:
        return None
    return d


def _version_row_to_meta(r):
    """One row of GET /v2/generation-model/{id}/versions -> the picker-facing meta shape.
    Split out of resolve_version_meta (picker-parity-round2, 2026-07-24) so
    list_model_versions can map EVERY row through the IDENTICAL logic instead of a second
    hand-copy -- resolve_version_meta (rows[0] only) and list_model_versions (all rows)
    must never drift apart on what a 'version' means.

    - model_type: this version's architecture enum (SDXL_MODEL / DIT7B_MODEL / MULTI_LORA / ...).
    - lora_base_model_type: for a LoRA, the base-model family it REQUIRES (null for base models).
      A LoRA runs on a base iff lora_base_model_type == the base's model_type (see is_lora_compatible).
    - trigger_words: the LoRA's activation tokens (extra.triggerWords|trainedWords); '' if none.
    - the rest: the author's tuned generation preset (extra.*), for prefilling the drawer.
    - compatibility: which Advanced-panel params this model actually HONORS (e.g.
      {cfgScale:false, samplingSteps:false, negativePrompt:true, ...}, probed live
      2026-07-06 -- memory pixai-model-capability-schema). A control the model ignores
      should be hidden/disabled in the drawer, not just always shown as if it did
      something. Empty dict (not missing) when absent -- callers treat "no entry for this
      key" as "unknown, don't restrict" (fail open), same convention as capabilities above.
    - restrictions: real min/max bounds for the params above (e.g.
      {samplingSteps:{min:16,max:50}}) -- clamp the drawer's own hardcoded bounds to these
      when present instead of a one-size-fits-all guess.
    - profiles: PLACEHOLDER ONLY here (always None). The allowed inference-profile set is
      NOT in this row -- it comes from a second, version-keyed route, so the CALLERS fill it
      via _attach_profiles (see below). Kept in the shape so every row a caller hands out
      has the same keys whether or not that caller ran the second read.
    - quality_tag: the version's own Quality Tag ({prefix, suffix}) or None -- see
      _version_quality_tag (SCOPE_2026-09-26 G4).
    - size_rule / context_images / color_palette: PLACEHOLDERS (None) like `profiles`,
      filled by _attach_features on the opt-in path that already pays the profile read.
    - unlimited: PLACEHOLDER (None), filled by _attach_unlimited on that same path for a
      version in UNLIMITED_VERSIONS (SCOPE_2026-09-26_unlimited-mode S2).
    - negative_prompt on an MMDIT26B version (Tsubaki.3) is routedNegativePrompts.default
      when that block parses, the route PixAI's own site pre-fills from; otherwise the
      legacy extra.negativePrompts (SCOPE_2026-09-26 G5)."""
    extra = r.get("extra") if isinstance(r.get("extra"), dict) else {}
    caps = extra.get("capabilities")
    compat = extra.get("compatibility")
    restrictions = extra.get("restrictions")
    model_type = (r.get("modelType") or "").strip()
    negative = (extra.get("negativePrompts") or "").strip()
    if model_type.upper() == "MMDIT26B_MODEL":
        routed = _routed_default_negative(extra.get("routedNegativePrompts"))
        if routed is not None:
            negative = routed.strip()
    return {
        "version_id": str(r.get("id") or ""),
        "model_type": model_type,
        "lora_base_model_type": (r.get("loraBaseModelType") or "").strip() if r.get("loraBaseModelType") else "",
        "trigger_words": (extra.get("triggerWords") or extra.get("trainedWords") or "").strip(),
        "negative_prompt": negative,
        "sampling_method": (extra.get("samplingMethod") or "").strip(),
        "sampling_steps": extra.get("samplingSteps"),
        "cfg_scale": extra.get("cfgScale"),
        "capabilities": [c for c in caps if isinstance(c, str)] if isinstance(caps, list) else [],
        "compatibility": compat if isinstance(compat, dict) else {},
        "restrictions": restrictions if isinstance(restrictions, dict) else {},
        "profiles": None,
        "quality_tag": _version_quality_tag(extra),
        "size_rule": None,
        "context_images": None,
        "color_palette": None,
        "unlimited": None,
        "profile_rows": None,
        "size_tiers": None,
        "context_max": None,
        "creativity": False,
    }


def _attach_profiles(session, meta):
    """Fill a version meta's `profiles` -- the profileName list the model VERSION actually
    offers -- and return the same dict (mutated in place).

    SCOPE §4b, 2026-08-17 (per-model inference profiles), captured 2026-08-25: the allowed
    set is per VERSION, not fixed -- Tsubaki.2 offers lite/standard/pro/ultra while
    Tsubaki.3 offers only pro/ultra. The drawer's five mode bars were always all clickable,
    so a mode the model rejects could be quoted and then silently retried on the model's
    own default (submit_generation's drop-and-retry), which is the quote-vs-charge
    divergence this closes at the source.

    The read is _model_profiles: the SAME version-keyed GET the price/submit gate already
    uses, so this shares its cache (one call per version per hour, not one per pick) and
    its fail-soft contract.

    FAIL SOFT -> None. No version id, a failed read, or a body we could not parse all leave
    `profiles = None`, which the drawer reads as "unknown -- dim nothing". An empty list
    `[]` is a real answer (SDXL: definitively no profiles) and is NOT None; the drawer
    leaves the bars alone for it too, because an SDXL model's modes are handled by the
    submit gate, not by this display gate. A `membershipOnly` profile IS listed: the site's
    own rejection path handles membership, and hiding it here would be a second, weaker
    copy of that rule."""
    vid = str(meta.get("version_id") or "")
    if not vid:
        meta["profiles"] = None
        return meta
    rows = _model_profiles(session, vid)
    if not isinstance(rows, list):
        meta["profiles"] = None
        return meta
    # A `hidden` profile is not offered in the drawer (SCOPE_2026-09-26 G9, T3-18b). Filtered
    # HERE ONLY -- the drawer's list. _model_profiles and the gate keep the full list, so the
    # gate's default-profile fill cannot change, and a hidden profile a CLI or Remix submits
    # is not refused (fail open). PixAI's own picker does not filter hidden profiles either;
    # this just keeps the drawer from offering one. No captured profile is hidden today.
    meta["profiles"] = [str(p.get("profileName")).strip() for p in rows
                        if isinstance(p, dict) and p.get("profileName")
                        and p.get("profileFlag") != "hidden"]
    # Session H T1a: the same rows as the Pro / Ultra rows under the model -- name, PixAI's
    # title and description, the live base price (the rows' "+N" is its difference from the
    # default row's) and the membership flags. Hidden rows are left out exactly as above.
    meta["profile_rows"] = [_profile_row(p) for p in rows
                            if isinstance(p, dict) and p.get("profileName")
                            and p.get("profileFlag") != "hidden"]
    return meta


def _profile_row(p):
    """One /inference-profiles row -> the drawer's profile row (Session H T1a)."""
    def _num(v):
        try:
            return int(v) if v is not None and not isinstance(v, bool) else None
        except (TypeError, ValueError):
            return None
    return {"name": str(p.get("profileName")).strip(),
            "title": str(p.get("title") or p.get("profileName") or "").strip()[:40],
            "desc": str(p.get("desc") or "").strip()[:200],
            "base_price": _num(p.get("basePrice")),
            "flag": str(p.get("profileFlag") or ""),
            "required_tier": _num(p.get("requiredMembershipTier")) or 0}


def _attach_features(session, meta):
    """Fill what the Generate drawer needs from the version-keyed /features and /size-config
    reads, and return the same dict (mutated in place). SCOPE_2026-09-26 G1/G2/G3.

    Runs ONLY beside _attach_profiles -- the opt-in reads that already pay a second GET for
    the drawer's applied row -- and never on resolve_version_meta's default path (the LoRA /
    Remix resolves read none of this; red team 2026-09-07). Both reads share the price/submit
    gate's cache (_model_features / _model_size_config), so this adds no GET per keystroke.

    - compatibility: merges only FALSE values -- every /features entry whose status is
      literally "off", plus enableADetailer and upscale off for MMDIT26A/B and USER_DIT26A/B
      (the site's tracker `be`/`Te`, which never sends either there). It never overwrites a
      key extra.compatibility already sets and never adds `true`, so the drawer's existing
      compat_* gates (cget: absent = unknown = fail open) just pick the new falses up.
    - context_images: True only when /features answered with modelType MMDIT26B_MODEL and
      contextImages "on" -- the exact condition under which the gate sends a reference as a
      context image. None when /features could not be read.
    - color_palette: True only when /features lists colorPalette "on" -- the one condition
      under which the gate lets a colour palette through (it fails closed, unlike the strip
      rules). False when /features answered without it, None when it could not be read.
    - size_rule: {step, lo, hi}, the rule the gate snaps a size to (see _size_rule), or None
      when /features could not be read. The drawer's dims() applies the identical snap, so
      its "-> W x H px" line is what is sent.

    The architecture comes from /features ONLY, never the version row's own modelType: the
    model-type rule applies "only when /features supplied it" and G1's step takes its
    modelType "from /features" (SCOPE G1/G2), which is exactly when the gate applies them.
    With /features down the gate changes nothing, so the drawer merges nothing and keeps
    today's size rule (size_rule None) -- what it shows stays what is sent."""
    vid = str(meta.get("version_id") or "")
    if not vid:
        return meta
    feats = _model_features(session, vid)
    mtype = feats["model_type"] if feats else ""
    compat = dict(meta.get("compatibility") or {})
    if feats:
        for name, status in feats["status"].items():
            if status == "off" and name not in compat:
                compat[name] = False
    if mtype in NO_HIRES_FACEFIX_TYPES:
        for name in ("enableADetailer", "upscale"):
            if name not in compat:
                compat[name] = False
    meta["compatibility"] = compat
    meta["context_images"] = None if feats is None else _context_images_on(feats)
    meta["color_palette"] = None if feats is None else feats["status"].get("colorPalette") == "on"
    ranges = _model_size_config(session, vid) if mtype in DIT_SIZE_STEP_TYPES else None
    # The gate runs G1 whenever /features answered (an empty modelType included, on the
    # step-8 rule), so the drawer carries a rule exactly then.
    meta["size_rule"] = (_size_rule(mtype, ranges, meta.get("restrictions"))
                         if feats is not None else None)
    # Session H: the named tiers off the SAME cached /size-config read (decision 6), the live
    # context-image max (decision 1), and whether the prompt helper is a creativity level
    # (decision 5 -- MMDIT26B, the same /features answer the build and the gate read).
    meta["size_tiers"] = [dict(t) for t in getattr(ranges, "tiers", ())] or None
    meta["context_max"] = (_model_context_max(session, vid) or CONTEXT_IMAGES_FALLBACK_MAX) \
        if meta["context_images"] else None
    meta["creativity"] = mtype == "MMDIT26B_MODEL"
    return meta


def _attach_unlimited(session, meta):
    """Fill `unlimited` -- the drawer's Unlimited Mode toggle -- and return the same dict
    (mutated in place). SCOPE_2026-09-26_unlimited-mode S2, as amended (§8.4).

    Runs beside _attach_features on the same opt-in path, and reads ONLY for a version in
    UNLIMITED_VERSIONS (the site asks the status for Tsubaki.3's id alone); every other
    version stays None without a GET. The answer is infinite_mode_status's
    {owned, expires_at, days_left} plus `size`: the lane's size limit (_lane_size_rule) off
    the gate's own cached /size-config read, so the drawer locks exactly the sizes the build
    refuses. None when the status read failed -- the drawer offers nothing."""
    from moonglade.gen_road import infinite_mode_status, _lane_size_rule, UNLIMITED_VERSIONS
    vid = str(meta.get("version_id") or "")
    meta["unlimited"] = None
    if vid not in UNLIMITED_VERSIONS:
        return meta
    status = infinite_mode_status(session, vid)
    if status is None:
        return meta
    rule = meta.get("size_rule") or {}
    meta["unlimited"] = dict(status, size=_lane_size_rule(
        _model_size_config(session, vid), int(rule.get("step") or 16)))
    return meta


def resolve_version_meta(session, model_id, with_profiles=False):
    """Resolve a model's latest generatable version AND the metadata we were throwing away.
    One GET /v2/generation-model/{id}/versions call returns everything below; the earlier
    resolve_latest_version() kept only the id. Read-only.

    Returns {version_id, model_type, lora_base_model_type, trigger_words, negative_prompt,
    sampling_method, sampling_steps, cfg_scale, capabilities, compatibility, restrictions}.
    All keys always present (empty/None when the model has no version or the field is
    absent).

    NOTE: `/generation-model/{id}/versions` returns MULTIPLE rows per model -- confirmed on
    PixAI's own site, which lists them as separate releases/iterations, all on the SAME
    fixed architecture (a LoRA is NOT multi-architecture; loraBaseModelType is consistent
    across a given LoRA's rows -- an earlier draft of this fix assumed otherwise and was
    reverted). This function still always takes rows[0] (presumed latest) -- it's the
    fast path used right after a pick, where "latest" is the right default. To offer a
    real choice among the other rows, see list_model_versions() below (picker-parity-round2,
    2026-07-24), which maps the FULL list through the same per-row shape.

    `with_profiles=True` adds the SECOND, version-keyed read that fills `profiles` (SCOPE
    2026-08-17 §4b). It is OPT-IN and OFF by default, because `profiles` is only ever
    LOOKED AT by a caller that renders the drawer's mode bar. The first cut attached it here
    unconditionally, which quietly charged every other caller of this shared resolver a
    second PixAI GET for a field it never reads: /api/task-params' Remix loop resolves one
    LoRA base per unique LoRA and reads only lora_base_model_type/model_type, so a four-LoRA
    remix went from four reads to eight (red team 2026-09-07). `profiles` is still always
    PRESENT in the returned shape; without the flag it is None, which the drawer reads as
    "unknown -- dim nothing"."""
    from moonglade.backup import PixAIError, _rest_get
    try:
        data = _rest_get(session, "/generation-model/" + str(model_id) + "/versions")
    except PixAIError:
        return _empty_version_meta()
    rows = data if isinstance(data, list) else (data or {}).get("data") or []
    if not rows:
        return _empty_version_meta()
    meta = _version_row_to_meta(rows[0])
    # SECOND read (SCOPE 2026-08-17 §4b): the resolved version's allowed inference
    # profiles, so the drawer can dim a mode this model does not offer. Fails soft to None.
    # ONLY for a caller that asked -- see the docstring: the LoRA/remix resolves never read
    # `profiles`, and paying a PixAI GET for them was pure cost (red team 2026-09-07).
    # The features/size-config reads ride the same opt-in (SCOPE_2026-09-26 G1/G2), and so
    # does the Unlimited Mode status (SCOPE_2026-09-26_unlimited-mode S2).
    if not with_profiles:
        return meta
    return _attach_unlimited(session, _attach_features(session, _attach_profiles(session, meta)))


def list_model_versions(session, model_id):
    """Every published version/release row for a model/LoRA -- not just resolve_version_meta's
    rows[0]. PixAI's own site offers a version selector on model/LoRA cards; this is what
    lets our picker do the same instead of always silently resolving the latest
    (the 2026-07-21 audit's tracked O12/O13 remainder, closed picker-parity-round2,
    2026-07-24). Same ONE GET as resolve_version_meta (no new network surface, no N+1) --
    each row mapped through the identical _version_row_to_meta shape, so a chosen
    version_id carries real model_type/lora_base_model_type/tuned-preset data, not a
    stripped-down id-only listing.

    Adds two UI-facing fields per row: `label` (a human position tag -- 'Latest' for the
    first/presumed-newest row, matching resolve_version_meta's own long-standing rows[0]
    assumption, else 'vN' counting back from it, with the row's own createdAt date appended
    when present) and `is_latest` (True only for that first row) -- so a picker can render
    a real choice without inventing version numbers PixAI doesn't actually provide. Rows
    with no id are skipped (nothing to select). Read-only."""
    from moonglade.backup import PixAIError, _rest_get
    try:
        data = _rest_get(session, "/generation-model/" + str(model_id) + "/versions")
    except PixAIError:
        return []
    rows = data if isinstance(data, list) else (data or {}).get("data") or []
    out = []
    n = len(rows)
    for i, r in enumerate(rows):
        meta = _version_row_to_meta(r)
        if not meta["version_id"]:
            continue
        created = (r.get("createdAt") or "").strip()
        tag = "Latest" if i == 0 else "v{}".format(n - i)
        meta["label"] = tag + (" · " + created[:10] if created else "")
        meta["is_latest"] = (i == 0)
        # SCOPE 2026-08-17 §4b: ONE second read, for the row the drawer actually applies
        # (applyModelRow takes is_latest, useGenerate.js:97). Every other row keeps
        # profiles=None -- "unknown, dim nothing" -- deliberately, because a read per row
        # would be exactly the N+1 this function's own contract above rules out.
        if meta["is_latest"]:
            _attach_profiles(session, meta)
            _attach_features(session, meta)     # same row, same opt-in (SCOPE_2026-09-26)
            _attach_unlimited(session, meta)    # ...and the Unlimited Mode status (S2)
        out.append(meta)
    return out


def resolve_latest_version(session, model_id):
    """Resolve a model's latest generatable VERSION id (what createGenerationTask's
    `modelId` actually wants) from its MODEL id. Thin wrapper over resolve_version_meta.
    Returns '' when the model has no version. Read-only."""
    return resolve_version_meta(session, model_id)["version_id"]


def is_lora_compatible(base_model_type, lora_base_model_type):
    """True if a LoRA can run on a base model. The rule is EXACT enum equality: the LoRA's
    `loraBaseModelType` must equal the base version's `modelType` (both drawn from the same
    GenerationModelType enum). Mismatched families are rejected server-side -> a wasted
    generation / burned free card, which this gate prevents pre-submit.

    IMPORTANT: this is FAMILY-level only. Pony / Illustrious / NoobAI / vanilla-SDXL all
    collapse into SDXL_MODEL, so passing this check is NOT a quality guarantee -- only a hard
    block on architecture mismatch. Fails OPEN: if either type is unknown/empty we return True
    (never block a submit on missing data)."""
    b = (base_model_type or "").strip().upper()
    lo = (lora_base_model_type or "").strip().upper()
    if not b or not lo:
        return True
    return b == lo


def annotate_lora_compat(results, base_model_type):
    """Soft-sort + tag a LoRA search-results list by architecture compatibility with a
    selected base model (the 2026-07-21 audit's LoRA-arch-filter item; the root-caused
    mechanism confirmed live: a row's real architecture is `lora_base_model_type`, sourced
    from GraphQL's `latestVersion.loraBaseModelType` via model_search_market_gql -- NEVER
    the `base_model` field, which is PixAI's content CATEGORY, not architecture).

    Pure reorder + tag over ALREADY-fetched rows -- makes no network call itself, so it
    behaves identically (and is independently testable) no matter which search path
    produced `results`. `base_model_type`: the caller's already-resolved selected base
    model's `model_type` (the exact value the post-selection is_lora_compatible() gate
    already uses) -- '' / None means "no base picked yet", and `results` is returned
    completely unmodified (browsing before picking a base must not be touched).

    SOFT SORT, deliberately not a hard filter (see CHANGELOG.md for the full reasoning):
    stable-partitions rows into "compatible-or-unknown" first, "confirmed incompatible"
    last -- the SAME fail-open rule as is_lora_compatible() itself, so this can never hide
    a LoRA the picker doesn't have enough data to judge. Each row gains a `compat` tag --
    'yes' | 'no' | 'unknown' -- so the client can badge precisely: an 'unknown' row SORTS
    with the compatible group (fail-open) but is NOT badged as confirmed-compatible, which
    would overclaim data this function doesn't have."""
    bt = (base_model_type or "").strip()
    if not bt:
        return results
    tagged = []
    for row in results:
        lbt = (row.get("lora_base_model_type") or "").strip()
        if not lbt:
            compat = "unknown"
        else:
            compat = "yes" if is_lora_compatible(bt, lbt) else "no"
        row = dict(row)
        row["compat"] = compat
        tagged.append(row)
    head = [r for r in tagged if r["compat"] != "no"]
    tail = [r for r in tagged if r["compat"] == "no"]
    return head + tail


# Sentinel parked in model_name_gql's memo cache when the LOOKUP ITSELF failed -- a network
# error, a timeout, a 5xx, an unparseable body, OR a perfectly-well-formed HTTP 200 whose
# payload is a GraphQL `errors` array rather than an answer. It is not a name and must never
# be written to a catalog row -- see model_name_gql's docstring.
_MODEL_LOOKUP_FAILED = object()

# Model detail as a full document: one generation model VERSION, selecting what its three
# readers use -- `name` and `model { title }` (model_name_gql), `model { id }` (the Runs-reel
# reuse, resolve_model_base_id) and `extra`'s sampling defaults (_resolve_model_preset;
# `extra` is a JSON scalar, so it rides whole). It needs no saved copy on PixAI's side. The
# one it replaced (getGenerationModelByVersionId's hash) never matched a document PixAI's
# site sends, and its servers were answering it from a cache that refused it now and then
# (#91; PROBE_2026-10-26_task-model-detail). An unknown version answers
# `generationModelVersion: null` with no errors, so the removed-vs-failure line
# model_name_gql draws (M18) survives. Named, so the fake PixAI keys it by its own name.
_MODEL_VERSION_DOC = (
    "query ModelVersion($id: ID!) { generationModelVersion(id: $id) { id name modelType "
    "status extra model { id title type } } }")


def _model_version_gql(session, model_version_id):
    """One model version read: `_MODEL_VERSION_DOC` POSTed through `gql_adhoc`, SINGLE
    ATTEMPT (retries=0, as every reader of it always was). Returns the raw `data` dict and
    raises whatever `gql_adhoc` raises, so each reader keeps its own checks and its own
    failure semantics: model_name_gql's M18 matrix, the reuse reader's '' and the preset's
    {}."""
    from moonglade.backup import gql_adhoc
    return gql_adhoc(session, _MODEL_VERSION_DOC, {"id": str(model_version_id)}, retries=0)


def model_name_gql(session, model_version_id, _cache={}, strict=False):
    """A model version's display name ("<model title> <version name>"), read through
    `_model_version_gql`; result cached by ID (few unique models).

    Returns the id itself when the name cannot be resolved, which the callers that just want
    a label are written against. That conflated two facts with very different consequences:
    "PixAI answered, and this version has no name / no longer exists" and "the request never
    got an answer". `--fix-models --relabel-removed` acts on the first by permanently writing
    "Unknown or removed model" over the row, and `_needs_model_fix` then considers the row
    resolved -- so a single timeout mid-run mislabelled every row of a still-perfectly-valid
    model, forever, with no re-run able to repair it (M18, 2026-07-27).

    `strict=True` therefore raises PixAIError instead of returning the id when the LOOKUP
    failed. What counts as a failure is decided the way `gql()` decides it, and for the same
    reason: **PixAI answers a refused GraphQL request with HTTP 200 and an `errors` array**.
    `raise_for_status()` is blind to that shape, so an exception-only guard closed the
    network half of this bug and left the half that hurts more -- a refused document or
    an auth failure surfaced as a resolver error refuses EVERY id in the run, so one
    `--fix-models --relabel-removed` would stamp "Unknown or removed model" over the model
    provenance of the whole catalog at once (M18 round 2, 2026-07-27). So this mirrors the one
    ordering decision that matters in `gql()` -- the `errors` array is read BEFORE the status
    is trusted at all -- and then rejects, in turn, a bad status, a body that is not a GraphQL
    reply, and a reply that simply never carried the `generationModelVersion` field we asked
    for. None of those is an answer about the model. (It does not copy `gql()`'s 401/429/5xx
    pre-checks: those exist there to drive a backoff-and-retry loop this lookup does not have,
    and every one of them ends up a failure here anyway.)

    One thing it deliberately does NOT treat as a failure, because it is the real "PixAI has
    no name for this" answer: a response that carries `generationModelVersion` explicitly
    NULL or title-less -- that is the genuinely-removed model `--relabel-removed` exists for.
    (An unknown version id answers exactly that through the document: null, HTTP 200, no
    errors.)

    A failure is memoised as `_MODEL_LOOKUP_FAILED`, never as a name. Caching the id would
    make the failure indistinguishable from an answer for the rest of the process -- which
    matters most in `--sync`, where the full-meta pass and `--fix-models` share this cache in
    one run, so a blip during the former would otherwise be laundered into a "resolved to its
    own id" verdict for the latter. Caching the *verdict* still spares the repeat calls."""
    from moonglade.backup import PixAIError
    if not model_version_id:
        return ""
    mid = str(model_version_id)
    if mid in _cache:
        hit = _cache[mid]
        if hit is _MODEL_LOOKUP_FAILED:
            if strict:
                raise PixAIError(
                    "model {} lookup failed earlier this run; not retried".format(mid))
            return mid
        return hit
    try:
        # SINGLE-ATTEMPT (`_model_version_gql` passes retries=0: a name lookup drives no
        # backoff loop, exactly as before). The ad-hoc road already enforces the M18 ordering
        # this function was hardened around: it reads the `errors` array BEFORE trusting the
        # status (a refused PixAI query is a 200 carrying `errors`) and raises on a 401, a 429
        # or a 5xx -- each of which the `except` below records as a FAILURE, never as a name.
        # A body that is not GraphQL at all comes back from it as {}, and the field check
        # below fails that too. What must stay HERE is the one distinction the road cannot
        # draw for us: a reply whose `data` is missing the `generationModelVersion` field
        # answered NOTHING (fail), whereas that field present but null is the genuine "model
        # is gone" answer that --relabel-removed exists for.
        data = _model_version_gql(session, mid)
        if not isinstance(data, dict) or "generationModelVersion" not in data:
            raise PixAIError("reply carried no generationModelVersion field: {}".format(
                str(data)[:200]))
        mv = data["generationModelVersion"] or {}
        title = (mv.get("model") or {}).get("title", "")
        version = mv.get("name", "")
        name = "{} {}".format(title, version).strip() if title else mid
    except Exception as e:                  # noqa: BLE001 -- a name lookup must not end a run
        # The lookup never landed. Record THAT, not the id: the id is what a successful
        # "no such model" answer also looks like, and --relabel-removed acts irreversibly
        # on the difference.
        _cache[mid] = _MODEL_LOOKUP_FAILED
        if strict:
            raise PixAIError("model {} lookup failed: {}".format(mid, str(e)[:200]))
        return mid
    _cache[mid] = name
    return name


def resolve_model_base_id(session, model_version_id):
    """The base MODEL id a generation VERSION id belongs to -- what
    `/generation-model/<id>/versions` (list_model_versions, and so the base-model picker's
    own re-resolve flow) actually wants, distinct from the VERSION id a submitted task uses
    and so the catalog's `model_id` column stores (api_generate resolves `args.model` to a
    VERSION id before submit; every catalog write path follows the same convention -- see
    moonglade/gallery.py's api_generate and this module's own catalog-row builders).

    Needed by the gallery's Runs-reel reuse-prefill (2026-08-02): it only has a run's
    catalog row, so it must ask PixAI 'what model is this a version of' before it can feed
    the picker's normal base-model-id flow -- feeding it the version id directly returns an
    empty version list (a real, verify-flagged bug: 'Model lookup failed' on every reuse
    click, old or new gens alike, since it's a catalog-wide convention).

    Same read as model_name_gql (`_model_version_gql`), deliberately its OWN request rather
    than a refactor of that function's cache: model_name_gql's failure semantics are
    hardened against two real production incidents (see its docstring, M18),
    and this is a rare, one-off, user-triggered lookup (a single reuse click), not a hot
    backfill loop -- the extra request is cheap and the isolation is worth it.

    Fails soft: '' on anything short of a clean answer (network error, GraphQL error,
    missing/null model) -- this is a "nice to restore" path, never a reason to block or
    mislead the caller. The caller leaves the composer's model untouched on '' rather than
    repeating today's wrong-id failure toast for a case that isn't the user's mistake."""
    if not model_version_id:
        return ""
    try:
        # retries=0 (`_model_version_gql`: this one-off reuse-click lookup drove no retry
        # before). Fails SOFT to '' on anything short of a clean answer: the ad-hoc road
        # raises on a GraphQL error or a bad status, a non-GraphQL body comes back as {} with
        # no model in it, and the `except` below turns every raise back into ''.
        data = _model_version_gql(session, model_version_id)
        mv = (data.get("generationModelVersion") if isinstance(data, dict) else None) or {}
        return str((mv.get("model") or {}).get("id") or "")
    except Exception:                        # noqa: BLE001 -- a soft-fail restore, never fatal
        return ""


# Per-VERSION inference-profile cache for the submit/price gate below. Keyed by version_id
# ALONE (not the session): /api/price builds a FRESH session per keystroke (gallery
# _gen_session -> _make_session(None)), so an id(session) memo never hit across price calls and
# every keystroke re-fetched /inference-profiles over the network -- the drawer's "price
# reloading" lag (2026-08-26). The profile set is per-VERSION architecture data, identical
# across accounts/sessions, so version-keyed caching is correct and turns the per-keystroke GET
# into one-per-model-per-TTL. Entries carry a monotonic timestamp; the TTL bounds staleness so a
# model whose profiles PixAI later changes is picked up within the hour (a restart clears it
# too). conftest clears it between tests so no model's profiles leak across them.
_PROFILE_CACHE_TTL = 3600.0                  # seconds; inference profiles change very rarely
# A FAILED read is cached too, on a much shorter clock (red team 2026-09-07, refining the
# original "only a SUCCESSFUL result is cached" rule in _model_profiles below). Caching
# nothing meant a version whose /inference-profiles route does not answer 200 re-fired that
# GET on EVERY call -- every /api/price keystroke, every drawer open -- for as long as the
# failure lasted. Sixty seconds keeps a transient failure transient while bounding the
# repeat to once a minute.
_PROFILE_FAIL_TTL = 60.0
_profile_cache = {}                          # version_id -> (fetched_at_monotonic, profiles_list|None)


def _model_profiles(session, version_id):
    """The inference-profile set for a model VERSION, via the VERSION-keyed endpoint
    GET /v2/generation-model/<version_id>/inference-profiles.

    This is the ONLY endpoint the gate consults, and the ONLY one that answers on a submit's
    `modelId` (which is a VERSION id): the model-keyed /versions route 404s on a version id,
    which is why an earlier resolve_version_meta-based gate was inert (adversarial review /
    live GETs, 2026-08-26). The real body is `{"profiles": [...]}` (NOT `data`).

    Returns the list on HTTP 200 -- which may be `[]` (SDXL answers `{"profiles": []}`). This
    distinguishes 'SDXL, definitively no profiles' from 'could not determine': ANY failure
    (exception / non-2xx / a body that is not a dict with a `profiles` list) returns None so
    the gate can fail soft and leave the submit exactly as it is today. Read-only.

    CACHED per version_id across ALL sessions (see _profile_cache) with a TTL, because
    /api/price runs this on every keystroke on a FRESH session (gallery _gen_session) -- a
    session-keyed memo re-hit the network each time. A FAILURE is cached too, but only for
    _PROFILE_FAIL_TTL (red team 2026-09-07, refining the original "only a SUCCESSFUL result
    is cached" rule): caching nothing at all meant a version PixAI will not answer for
    re-fired the GET on every single call for as long as that lasted. A minute is short
    enough that a transient failure is still transient -- the next call after it tries again,
    and a recovered route is picked up then -- and long enough that the repeat is bounded.
    The fail-soft contract is unchanged: a cached failure returns the SAME None a fresh one
    does, so every caller behaves exactly as it did."""
    from moonglade.backup import _rest_get
    vid = str(version_id)
    now = time.monotonic()
    hit = _profile_cache.get(vid)
    if hit is not None:
        ttl = _PROFILE_CACHE_TTL if hit[1] is not None else _PROFILE_FAIL_TTL
        if (now - hit[0]) < ttl:
            return hit[1]
    try:
        data = _rest_get(session, "/generation-model/" + vid + "/inference-profiles")
    except Exception:
        _profile_cache[vid] = (now, None)
        return None
    if not isinstance(data, dict):
        _profile_cache[vid] = (now, None)
        return None
    profiles = data.get("profiles")
    if not isinstance(profiles, list):
        _profile_cache[vid] = (now, None)
        return None
    _profile_cache[vid] = (now, profiles)
    return profiles


# =============================================================================
# The per-model image gate (SCOPE_2026-09-26_tsubaki3-parity-fixes, lane G)
# =============================================================================
# One gate, applied ONCE at build (build_request's image road via RequestResolver.gate, and
# the CLI run_generate right after _gen_parameters), so the dict that is quoted, card-matched
# and submitted is one object. The calls inside price_task and submit_generation stay as
# BACKSTOPS for callers off the road and return the SAME object for already-gated input
# (every rule below copies only when a field actually changes).
#
# What it reads, all version-keyed (the model-keyed /versions route 404s on the version id a
# submit carries), cached with the _model_profiles discipline (an hour on success, 60 s on a
# failure, short timeout, fail soft to today's shape):
#   /inference-profiles  -- the 2026-08-25 profile branch, unchanged
#   /features            -- {modelType, features:[{featureName, status, ...}]}
#   /size-config         -- {ranges:[{minWidth, maxWidth, minHeight, maxHeight, step, ...}]}
#                           read only for the DiT families
#
# Every change the NEW rules make is one receipt entry {field, asked, used, why}
# (used: None = not sent), handed back beside the dict so /api/price, /api/generate and the
# CLI preview can say what was changed BEFORE a spend. The profile branch predates the
# receipt and is left exactly as it was, silent included (it fires on every DiT submit the
# drawer makes -- steps/cfg the drawer already shows as not applying).

# Every DiT family snaps sizes to 16, everything else to 8: PixAI's own model-*.js
# `function Se(e){return e&&W(e)?16:8}` (W = these six).
DIT_SIZE_STEP_TYPES = frozenset((
    "DIT7_MODEL", "DIT7B_MODEL", "MMDIT26A_MODEL", "MMDIT26B_MODEL",
    "USER_DIT26A_MODEL", "USER_DIT26B_MODEL"))
# Never Hires, never Face Fix: the site's tracker `be` (MMDIT26A|B) and `Te` (USER_DIT26A|B),
# whatever /features says -- applied only when /features supplied the modelType.
NO_HIRES_FACEFIX_TYPES = frozenset((
    "MMDIT26A_MODEL", "MMDIT26B_MODEL", "USER_DIT26A_MODEL", "USER_DIT26B_MODEL"))
_HIRES_FIELDS = ("upscale", "upscaleDenoisingStrength", "upscaleDenoisingSteps",
                 "upscaleSampler")
# A /features entry strips its fields only on a LITERAL status "off"; a feature absent from
# the list counts as on (the site's `Ce()` / `u(i, X, !0)` default). `enlarge` and
# `enlargeModel` are never stripped (the site keeps them on every model). samplingSteps,
# cfgScale, samplingMethod and clipSkip stay owned by the profile branch alone -- they drive
# the SDXL price, so /features is never a second authority over them. refImage is G3's.
_FEATURE_STRIP_FIELDS = (
    ("negativePrompt", ("negativePrompts",), "this model takes no negative prompt"),
    ("upscale", _HIRES_FIELDS, "this model takes no Enhance Details (Hires) pass"),
    ("enableADetailer", ("enableADetailer",), "this model takes no Face Fix"),
)
_GATE_READ_TIMEOUT = 10                     # seconds; short -- /api/price runs this per keystroke
_SIZE_FALLBACK_RANGE = (64, 4096)           # today's web clamp (_gen_args_from_web_payload)
_features_cache = {}                        # version_id -> (fetched_at_monotonic, parsed|None)
_size_config_cache = {}                     # version_id -> (fetched_at_monotonic, ranges|None)
_CONTEXT_REF_LORA_REFUSAL = ("Tsubaki.3 can't combine a reference image with LoRAs "
                             "— remove one")
_CONTEXT_LORA_REFUSAL = ("Tsubaki.3 can't combine context images with LoRAs — switch to "
                         "LoRAs or remove them")


def _cached_version_read(cache, session, version_id, suffix, parse):
    """One version-keyed GET /v2/generation-model/<version><suffix>, parsed, with the
    _model_profiles cache discipline: a parsed answer is kept for _PROFILE_CACHE_TTL, a
    failure (any exception, or a body `parse` refuses as None) for _PROFILE_FAIL_TTL, and
    every failure returns None -- the caller's "unknown, change nothing". Read-only."""
    from moonglade.backup import _rest_get
    vid = str(version_id or "").strip()
    if not vid:
        return None
    now = time.monotonic()
    hit = cache.get(vid)
    if hit is not None:
        ttl = _PROFILE_CACHE_TTL if hit[1] is not None else _PROFILE_FAIL_TTL
        if (now - hit[0]) < ttl:
            return hit[1]
    try:
        value = parse(_rest_get(session, "/generation-model/" + vid + suffix,
                                timeout=_GATE_READ_TIMEOUT))
    except Exception:
        value = None
    cache[vid] = (now, value)
    return value


_edit_caps_cache = {}                       # edit version_id -> (fetched_at_monotonic, caps|None)


def edit_output_caps_live(session, model_id):
    """An edit model VERSION's output capabilities from its live record (DESIGN_3.22 5.1):
    {"output_formats": [...], "backgrounds": [...]} from extra.chatEditing's
    supportedOutputFormatOptions and supportedBackgroundOptions, or None when it cannot be
    read -- the caller then uses the baked EDIT_MODELS lists (gen_params.edit_output_caps).

    The record is a row of GET /v2/generation-model/<MODEL id>/versions (the route the
    2026-10-26 and 11-18 probes read these lists from), found by the version id an edit sends
    as chat.modelId; the model id is the table's `base_model_id`. A version the table does not
    know is None. A record that IS read but lists neither key offers neither (png only): what
    the record says wins. Cached with the gate's discipline (an hour on an answer, 60 s on a
    failure, short timeout, fail soft). Read-only."""
    from moonglade.backup import _rest_get
    from moonglade.gen_params import edit_model_by_id
    vid = str(model_id or "").strip()
    base = str((edit_model_by_id(vid) or {}).get("base_model_id") or "")
    if not vid or not base.isdigit():
        return None
    now = time.monotonic()
    hit = _edit_caps_cache.get(vid)
    if hit is not None:
        ttl = _PROFILE_CACHE_TTL if hit[1] is not None else _PROFILE_FAIL_TTL
        if (now - hit[0]) < ttl:
            return hit[1]
    value = None
    try:
        data = _rest_get(session, "/generation-model/" + base + "/versions",
                         timeout=_GATE_READ_TIMEOUT)
        rows = data if isinstance(data, list) else (data or {}).get("data") or []
        row = next((r for r in rows if isinstance(r, dict) and str(r.get("id") or "") == vid),
                   None)
        extra = row.get("extra") if isinstance(row, dict) else None
        ce = extra.get("chatEditing") if isinstance(extra, dict) else None
        if isinstance(ce, dict):
            def _names(v):
                return [str(x) for x in v if isinstance(x, str)] if isinstance(v, list) else []
            value = {"output_formats": _names(ce.get("supportedOutputFormatOptions")),
                     "backgrounds": _names(ce.get("supportedBackgroundOptions"))}
    except Exception:                                        # noqa: BLE001 -- fail soft
        value = None
    _edit_caps_cache[vid] = (now, value)
    return value


def edit_caps_resolver(session):
    """RequestResolver.edit_caps for one session: model_id -> the live capability read (or
    None). The quote and the spend carry the same one, so they apply the same rules."""
    return lambda model_id: edit_output_caps_live(session, model_id)


def _parse_features(data):
    """/features body -> {"model_type": "MMDIT26B_MODEL", "status": {featureName: status}},
    or None for a body without a `features` list. Status strings are kept LITERAL: a strip
    fires on exactly "off" (captured 2026-09-26: auth/T3v_features.json, Flashv_features)."""
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        return None
    status = {}
    for f in data["features"]:
        if isinstance(f, dict) and isinstance(f.get("featureName"), str) and f["featureName"]:
            status[f["featureName"]] = f.get("status")
    return {"model_type": str(data.get("modelType") or "").strip().upper(), "status": status}


class _SizeRanges(list):
    """The gate's /size-config answer: a plain list of (minWidth, maxWidth, minHeight,
    maxHeight) tuples -- everything that reads ranges sees exactly that -- carrying the same
    body's named tiers on `.tiers` for the drawer (Session H decision 6, _size_tiers_meta), so
    the one cached GET feeds both and the drawer's tier row costs no second read."""
    tiers = ()


def _parse_size_config(data):
    """/size-config body -> [(minWidth, maxWidth, minHeight, maxHeight), ...], or None for a
    body without a `ranges` list. [] is a real answer (a CHAT model has no ranges). The list
    is a _SizeRanges whose `.tiers` keeps each named range with its presets (Session H)."""
    if not isinstance(data, dict) or not isinstance(data.get("ranges"), list):
        return None
    out = _SizeRanges()
    tiers = []
    for r in data["ranges"]:
        if not isinstance(r, dict):
            continue
        try:
            rng = (int(r["minWidth"]), int(r["maxWidth"]),
                   int(r["minHeight"]), int(r["maxHeight"]))
        except (KeyError, TypeError, ValueError):
            continue
        out.append(rng)
        tier = _size_tier_row(r, rng)
        if tier is not None:
            tiers.append(tier)
    out.tiers = tuple(tiers)
    return out


def _size_tier_row(r, rng):
    """One /size-config range -> the drawer's tier row, or None when it is not a named range
    with a usable default preset. Presets keep PixAI's portrait labels ("3:5", "9:16", ...)."""
    name = str(r.get("name") or "").strip()
    if not name or len(name) > 8:
        return None
    try:
        step = int(r.get("step") or 16)
    except (TypeError, ValueError):
        step = 16
    presets = []
    default = None
    for pr in r.get("presets") or []:
        if not isinstance(pr, dict):
            continue
        try:
            w, h = int(pr["width"]), int(pr["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        row = {"ratio": str(pr.get("ratioLabel") or "").strip(), "width": w, "height": h}
        presets.append(row)
        if pr.get("id") and pr.get("id") == r.get("defaultPresetId"):
            default = [w, h]
    if default is None and presets:
        default = [presets[0]["width"], presets[0]["height"]]
    if default is None:
        return None
    try:
        required = int(r.get("requiredMembershipTier") or 0)
    except (TypeError, ValueError):
        required = 0
    return {"name": name, "min": min(rng[0], rng[2]), "max": max(rng[1], rng[3]),
            "step": step if step > 0 else 16, "required_tier": required,
            "access": str(r.get("accessStatus") or ""), "default": default,
            "presets": presets}


def _model_features(session, version_id):
    """The version's /features, parsed (see _parse_features), or None. Cached, fail soft."""
    return _cached_version_read(_features_cache, session, version_id, "/features",
                                _parse_features)


def _model_size_config(session, version_id):
    """The version's /size-config ranges (see _parse_size_config), or None. Cached, fail
    soft. No /v2/model-config read in this branch: its top-level 512-2048 is overridden by
    its own per-range rules, and its projected XL range equals /size-config's."""
    return _cached_version_read(_size_config_cache, session, version_id, "/size-config",
                                _parse_size_config)


_model_config_cache = {}                    # version_id -> (fetched_at_monotonic, parsed|None)


def _parse_model_config_context_max(data):
    """/v2/model-config/<version>?source=pixai-app -> contextImages.media.maxCount (int >= 1),
    or None when the body does not carry it."""
    try:
        cfg = data["configs"]["pixai-app"]["params"]["contextImages"]["media"]["maxCount"]
        n = int(cfg)
    except (KeyError, TypeError, ValueError):
        return None
    return n if n >= 1 else None


def _model_context_max(session, version_id):
    """The live context-image max for a version (Session H decision 1: "up to 3 slots, live
    max"), read from GET /v2/model-config/<version>?source=pixai-app with the gate's cache
    discipline (an hour on success, a minute on failure, short timeout, fail soft to None --
    the caller then uses CONTEXT_IMAGES_FALLBACK_MAX). Read-only."""
    from moonglade.backup import _rest_get
    vid = str(version_id or "").strip()
    if not vid:
        return None
    now = time.monotonic()
    hit = _model_config_cache.get(vid)
    if hit is not None:
        ttl = _PROFILE_CACHE_TTL if hit[1] is not None else _PROFILE_FAIL_TTL
        if (now - hit[0]) < ttl:
            return hit[1]
    try:
        value = _parse_model_config_context_max(
            _rest_get(session, "/model-config/" + vid, params={"source": "pixai-app"},
                      timeout=_GATE_READ_TIMEOUT))
    except Exception:
        value = None
    _model_config_cache[vid] = (now, value)
    return value


def features_resolver(session):
    """RequestResolver.features: version_id -> the gate's own cached /features read (see
    _parse_features), or None. Session H: build_request decides the creativity shape from the
    SAME architecture the gate reads (review B3), never from the version row's own type."""
    def _feats(version_id):
        return _model_features(session, version_id)
    return _feats


def _context_images_on(feats):
    """True when /features says a reference goes out as a context image: modelType
    MMDIT26B_MODEL and contextImages status "on". ABSENT counts as OFF for this one feature
    (the site's `M()` default), unlike every strip rule."""
    return bool(feats) and feats.get("model_type") == "MMDIT26B_MODEL" \
        and feats["status"].get("contextImages") == "on"


def _size_rule(model_type, ranges=None, restrictions=None):
    """{step, lo, hi} for a version (SCOPE_2026-09-26 G1, T3-02/03/04 as corrected).

    step  -- extra.restrictions.width.step (else height.step) when the version publishes one
             (the site's modelParams `Ce()`); else 16 for the six DiT families, else 8. The
             gate cannot see `restrictions` (the version-keyed routes carry no `extra`), so it
             always takes the model-type step; the drawer's rule honours a published step. No
             captured version publishes one today.
    lo/hi -- the UNION of the version's /size-config ranges, step-aligned inward:
             lo = ceil(min/step)*step, hi = floor(max/step)*step (Tsubaki.3 and Flash today:
             512-2496). No ranges -> today's 64-4096 clamp, on the step."""
    step = 0
    if isinstance(restrictions, dict):
        for side in ("width", "height"):
            r = restrictions.get(side)
            if isinstance(r, dict):
                try:
                    step = int(r.get("step") or 0)
                except (TypeError, ValueError):
                    step = 0
                if step > 0:
                    break
    if step <= 0:
        step = 16 if str(model_type or "").strip().upper() in DIT_SIZE_STEP_TYPES else 8
    lo_raw, hi_raw = _SIZE_FALLBACK_RANGE
    if ranges:
        lo_raw = min(min(r[0], r[2]) for r in ranges)
        hi_raw = max(max(r[1], r[3]) for r in ranges)
    lo, hi = -(-lo_raw // step) * step, hi_raw // step * step
    if lo > hi:
        lo = -(-_SIZE_FALLBACK_RANGE[0] // step) * step
        hi = _SIZE_FALLBACK_RANGE[1] // step * step
    return {"step": step, "lo": lo, "hi": hi}


def _snap_size(width, height, rule):
    """Snap (width, height) onto a size rule -- the APP'S OWN rule, not the site's (its
    nearest paths are sizeConfigRuleValues `at()`, useHeldTaskPrice `R()` and `dt()`).

    A size already on the step and inside [lo, hi] passes UNTOUCHED (2048x1152, 816x2448 and
    1088x1824 never move). A failing size is scaled proportionally -- the long side down to
    hi if over, then the short side up to lo if under, the long side winning when both cannot
    hold -- then each side rounds HALF-UP with floor(x/step + 0.5)*step (never Python's
    half-to-even round(), so this agrees with genCore.js's snapSize, which is the same
    arithmetic in JS) and is clamped into [lo, hi]. 768x432 on Tsubaki.3 -> 912x512."""
    import math
    step, lo, hi = rule["step"], rule["lo"], rule["hi"]
    w, h = width, height
    if w % step == 0 and h % step == 0 and lo <= w <= hi and lo <= h <= hi:
        return w, h
    long_side, short_side = max(w, h), min(w, h)
    s = 1.0
    if long_side > hi:
        s = hi / long_side
    if short_side > 0 and short_side * s < lo:
        s = lo / short_side
    if long_side * s > hi:
        s = hi / long_side

    def _r(x):
        return int(math.floor(x / step + 0.5)) * step
    return min(hi, max(lo, _r(w * s))), min(hi, max(lo, _r(h * s)))


def _lora_out_of_range(weight, lo, hi):
    """The clamped weight when `weight` is a number outside [lo, hi], else None (in range,
    or not a number -- left exactly as it is)."""
    if isinstance(weight, bool):
        return None
    try:
        w = float(weight)
    except (TypeError, ValueError):
        return None
    if lo <= w <= hi:
        return None
    return max(lo, min(hi, w))


_CREATIVITY_LEVELS = ("off", "low", "medium")
# Tsubaki.3's live context-image max is model-config's contextImages.media.maxCount; this is the
# value every capture shows, used only when that read fails (BUILD-w2-gen §5).
CONTEXT_IMAGES_FALLBACK_MAX = 3
_CONTEXT_UNREAD = ("Couldn't read this model's settings from PixAI, so context images can't be "
                   "checked — try again in a minute")
_CONTEXT_NOT_TAKEN = "This model doesn't take context images"


def _check_context_images(session, p):
    """Session H (BUILD-w2-gen §5, review S2/S4): refuse a dict carrying `contextImages` that
    PixAI's own site would never send. Raises PixAIError; returns nothing. Order: the shape of
    the list, then the model (/features must answer MMDIT26B with contextImages on), then the
    combinations the feature excludes, then the live max."""
    from moonglade.backup import PixAIError
    from moonglade.gen_road import UNLIMITED_VERSIONS
    ids = p.get("contextImages")
    if not isinstance(ids, list) or not ids \
            or not all(isinstance(x, str) and x.strip() for x in ids):
        raise PixAIError("context images must be a list of picture ids")
    if len(set(ids)) != len(ids):
        raise PixAIError("The same picture is in two context slots — remove one")
    if "chat" in p or p.get("enlarge") or p.get("upscale"):
        raise PixAIError("An edit or an upscale can't carry context images")
    if p.get("mediaId") or "strength" in p:
        raise PixAIError("Send context images or a reference picture, not both")
    lmap, lpar = p.get("lora"), p.get("loraParameters")
    if (isinstance(lmap, dict) and lmap) or (isinstance(lpar, list) and lpar):
        raise PixAIError(_CONTEXT_LORA_REFUSAL)
    if p.get("recipeIds"):
        # ONE wording for this refusal wherever it fires (the build, this gate, the send's
        # backstop): the recipe lane's, which tells the user how to send them.
        from moonglade import recipes as _recipes
        raise PixAIError(_recipes.HELD_WITH_CONTEXT)
    if p.get("modelStyle"):
        raise PixAIError("A style can't ride with context images — PixAI would drop the images")
    if p.get("lane"):
        raise PixAIError("Unlimited Mode can't use a reference picture — remove it")
    feats = _model_features(session, p.get("modelId"))
    if feats is None:
        raise PixAIError(_CONTEXT_UNREAD)
    if not _context_images_on(feats):
        raise PixAIError(_CONTEXT_NOT_TAKEN)
    mx = _model_context_max(session, p.get("modelId")) or CONTEXT_IMAGES_FALLBACK_MAX
    if len(ids) > mx:
        raise PixAIError("{} takes up to {} context images — remove {}".format(
            "Tsubaki.3" if str(p.get("modelId")) in UNLIMITED_VERSIONS else "This model",
            mx, len(ids) - mx))


def _gate_image_params(session, params):
    """THE per-model image gate: params -> (params, adjusted). See the section comment.

    Order: the 2026-08-25 profile branch (unchanged) -> the colour palette (fails closed,
    so before the exits) -> the Upscale road exits -> /features
    (unknown -> exit, today's shape) -> G3 context image -> G2 strips -> G6 prompt helper ->
    G10 LoRA weights -> G1 size. Returns the ORIGINAL object when nothing changes and a
    shallow copy otherwise; nested dicts it changes (promptHelper, extra, lora,
    loraParameters) are replaced, never mutated, so the caller's dict is never touched.
    Raises PixAIError for the one refusal (a reference plus LoRAs on an MMDIT26B model) --
    at build time that is the badge's note and costs nothing."""
    from moonglade.backup import PixAIError
    from moonglade.gen_params import lora_weight_range
    adjusted = []
    if not isinstance(params, dict) or not params.get("modelId"):
        return params, adjusted
    # Video (i2vPro/referenceVideo) is the only non-image submit carrying a TOP-LEVEL
    # modelId; instruct-edit (chat.modelId) and enhance (workflowName) have none, so the
    # modelId guard already skips them. Skip video explicitly.
    if "i2vPro" in params or "referenceVideo" in params:
        return params, adjusted
    p = params

    def _own():
        nonlocal p
        if p is params:
            p = dict(params)
        return p

    # --- the profile branch (2026-08-25), behaviour unchanged ---------------------------
    # NON-EMPTY profiles -> DiT: the site sends inferenceProfile and omits samplingSteps /
    # cfgScale / samplingMethod / clipSkip, so fill the DEFAULT-flagged profile when the user
    # left it on auto (none flagged -> leave it ABSENT so the server picks; never synthesize)
    # and drop the four. EMPTY [] -> SDXL (a definitive 200): steps/cfg drive the cost; strip
    # a profile SDXL would reject. None -> could not determine: today's shape.
    try:
        profiles = _model_profiles(session, params["modelId"])
    except Exception:
        profiles = None
    if profiles:
        if not p.get("inferenceProfile"):
            default = ""
            for r in profiles:
                if isinstance(r, dict) and r.get("profileFlag") == "default":
                    default = str(r.get("profileName") or "").strip()
                    break
            if default:
                _own()["inferenceProfile"] = default
        else:
            # Session H (BUILD-w2-gen, review S1b): a profile the version does not LIST is
            # refused here, at build, rather than quoted and then rejected and re-run on the
            # default by submit_generation's fallback -- a quote for one job and a charge for
            # another. The FULL list is the authority (hidden profiles included), so nothing
            # the site itself would send is refused. An unreadable list (None) never refuses.
            asked = str(p.get("inferenceProfile") or "").strip().lower()
            names = {str(r.get("profileName") or "").strip().lower()
                     for r in profiles if isinstance(r, dict)}
            if asked and names and asked not in names:
                raise PixAIError("This model doesn't offer the {} profile — pick one it "
                                 "lists".format(p.get("inferenceProfile")))
        for k in ("samplingSteps", "cfgScale", "samplingMethod", "clipSkip"):
            if k in p:
                _own().pop(k)
    elif profiles is not None:
        if "inferenceProfile" in p:
            _own().pop("inferenceProfile")

    # --- Session H: a request that already carries context images (BUILD-w2-gen, review S2) --
    # Checked BEFORE the chat / Upscale / unknown-/features exits below, so no road -- the
    # drawer, the Lightbox edit bar, a CLI --params-json -- sends a context-image dict that
    # was not checked here. Every rule is a refusal that costs nothing.
    if "contextImages" in p:
        _check_context_images(session, p)

    # --- SCOPE_2026-09-26 rules --------------------------------------------------------
    # A chat-kind shape (the Fix's synthesized price shape carries a top-level modelId) is
    # not text-to-image; none of the rules below describe it.
    if "chat" in p:
        return p, adjusted
    # Colour palette (Session H 4; lane w2-small 2026-09-28, spend review B1). This rule FAILS
    # CLOSED, unlike every strip rule below, and so runs BEFORE the two early exits: a palette
    # goes out only on a version whose /features lists colorPalette "on" -- PixAI's own client
    # never sends one otherwise (its feature tracker reads an unread list as off) -- and never
    # beside a context image (the site drops it there), on the Upscale road, or when /features
    # could not be read. Each strip is a receipt. The price cannot move: /v2/task-price takes
    # no colorPalette.
    if "colorPalette" in p:
        cpal = p.get("colorPalette")
        cf = _model_features(session, params["modelId"])
        why = None
        upscale_road = bool(p.get("mediaId") and (p.get("enlarge") or p.get("upscale")))
        if p.get("contextImages") or (p.get("mediaId") and not upscale_road
                                      and _context_images_on(cf)):
            why = "a context image takes no colour palette"
        elif upscale_road:
            why = "an upscale takes no colour palette"
        elif cf is None:
            why = "couldn't confirm this model takes a colour palette"
        elif cf["status"].get("colorPalette") != "on":
            why = "this model takes no colour palette"
        if why:
            adjusted.append({"field": "colorPalette",
                             "asked": cpal.get("name") if isinstance(cpal, dict) else cpal,
                             "used": None, "why": why})
            _own().pop("colorPalette")
    # The UPSCALE road: a top-level mediaId together with enlarge or upscale is an Upscale
    # panel request, and it passes the new rules untouched -- no size snap, no strip, never a
    # context image. What PixAI does with an upscale of a Tsubaki picture is unobserved; the
    # site upscales on a fixed version, the app on the source's own (DECISIONS 2026-07-27 /
    # 2026-08-23), and changing that is the owner's call. The profile branch above still
    # applies, exactly as it has since 2026-08-25.
    if p.get("mediaId") and (p.get("enlarge") or p.get("upscale")):
        return p, adjusted
    feats = _model_features(session, params["modelId"])
    if feats is None:
        return p, adjusted              # /features unobserved -> today's shape, unchanged
    mtype = feats["model_type"]
    status = feats["status"]

    # G3 -- a reference on MMDIT26B becomes a context image (T3-14/15, EDIT-5). The site's
    # only reference path there is contextImages (it hard-excludes mediaId+strength on
    # MMDIT26B). ONE id -- the drawer has one slot. The catalog id goes as-is, never through
    # the upload resolver. With a LoRA the site silently DROPS the context image; this
    # REFUSES instead (the LoRA-cap precedent: dropping either changes the picture asked
    # for, and a refusal costs nothing).
    # The refusal covers every MMDIT26B version, whatever its contextImages status ("Reference
    # AND a non-empty lora on MMDIT26B -> refuse"): where contextImages is off the reference
    # would go out as img2img, a shape the site hard-excludes there. A LoRA counts in either
    # form -- the `lora` map or `loraParameters` (a --params-json or hand-built dict can carry
    # only the list) -- and a reference counts as a mediaId or an already-built contextImages
    # list, which PixAI would silently drop beside the LoRA while the quote kept its surcharge.
    # The Upscale road has already exited above, so an Upscale is never refused here.
    if mtype == "MMDIT26B_MODEL" and (p.get("mediaId") or p.get("contextImages")):
        lmap, lpar = p.get("lora"), p.get("loraParameters")
        if (isinstance(lmap, dict) and lmap) or (isinstance(lpar, list) and lpar):
            raise PixAIError(_CONTEXT_REF_LORA_REFUSAL)
    if _context_images_on(feats) and p.get("mediaId") and "contextImages" not in p:
        q = _own()
        ref = str(q.pop("mediaId"))
        q["contextImages"] = [ref]
        # A context image carries no strength. Dropping it is a receipt like any other gate
        # change: the drawer's latest row already shows the slider disabled, but the phone
        # Create screen, the CLI's --ref-strength, Remix and an older version picked in the
        # version selector do not (review F6/R1, 2026-09-26).
        if "strength" in q:
            adjusted.append({"field": "strength", "asked": q.pop("strength"), "used": None,
                             "why": "a context image carries no strength"})
    # Whichever road the context images came by (a converted reference above, or Session H's
    # drawer building them itself), what the feature excludes is not sent -- each a receipt.
    if p.get("contextImages"):
        for fld, why in (("negativePrompts", "a context image takes no negative prompt "
                                             "(PixAI drops it there too)"),
                         ("colorPalette", "a context image takes no colour palette")):
            if fld in p:
                adjusted.append({"field": fld, "asked": p[fld], "used": None, "why": why})
                _own().pop(fld)

    # G2 -- strip what the model does not take (T3-05/06/08/10/15).
    stripped = set()

    def _strip(fld, why):
        if fld in p and fld not in stripped:
            stripped.add(fld)
            adjusted.append({"field": fld, "asked": p[fld], "used": None, "why": why})
            _own().pop(fld)
    for feature, fields, why in _FEATURE_STRIP_FIELDS:
        if status.get(feature) == "off":
            for fld in fields:
                _strip(fld, why)
    if mtype in NO_HIRES_FACEFIX_TYPES:
        for fld in _HIRES_FIELDS + ("enableADetailer",):
            _strip(fld, "PixAI never sends Hires or Face Fix to this model type")

    # G6 -- the prompt helper on MMDIT26B is a creativity level (T3-11). The legacy shape
    # maps on -> medium, off -> off (the site's own legacy converter, task-*.js G()/z());
    # effective context images force medium. Never withStage / enable / userWantToEnable on
    # MMDIT26B. naturalPrompts moves under `extra` (merged into any existing extra) and is
    # sent only when the level is not off. Idempotent: a promptHelper that already carries
    # `creativity` is left alone. The pure shape change is not a receipt (the user's on/off
    # is kept); a context image forcing an OFF helper to medium is.
    if mtype == "MMDIT26B_MODEL":
        ph = p.get("promptHelper")
        extra_ok = "extra" not in p or isinstance(p.get("extra"), dict)
        ctx = bool(p.get("contextImages"))
        asked = "off"
        # A shape with NO promptHelper at all (--params-json, a hand-built dict; the app's
        # own builder always emits one) still gets medium when context images are sent --
        # "when context images are sent: ... creativity medium", a receipt entry like the
        # off -> medium case (review F3). Without context images it is left absent.
        if "promptHelper" not in p and ctx and extra_ok:
            ph, asked = {}, None
        if isinstance(ph, dict) and extra_ok:
            if "creativity" in ph:
                # Session H: the drawer builds the creativity shape itself (decision 5's stops,
                # build_request); a creativity already here is honoured as asked.
                level = ph.get("creativity")
                asked = level
                if level not in _CREATIVITY_LEVELS:
                    level = "medium"
                    if not ctx:
                        adjusted.append({"field": "promptHelper", "asked": asked,
                                         "used": "medium",
                                         "why": "the prompt helper runs off, low or medium"})
            else:
                on = bool(ph.get("userWantToEnable",
                                 ph.get("withStage", ph.get("enable", False))))
                level = "medium" if on else "off"
                if asked is not None:
                    asked = level
            if ctx and level != "medium":
                adjusted.append({"field": "promptHelper", "asked": asked, "used": "medium",
                                 "why": "a context image runs the prompt helper at medium, "
                                        "as PixAI's own site does"})
                level = "medium"
            if "creativity" in ph:
                # A creativity shape is kept as it came (a stored or --params-json one may
                # carry the server's own `enable`); only the level can change, and only when
                # context images force it or the value is not a level at all.
                new_ph = dict(ph)
                new_ph["creativity"] = level
            else:
                new_ph = {k: v for k, v in ph.items()
                          if k not in ("withStage", "enable", "userWantToEnable")}
                new_ph["creativity"] = level
                new_ph["forcePromptHelperDetectionSide"] = "server"
            natural = p.get("naturalPrompts")
            extra = dict(p["extra"]) if isinstance(p.get("extra"), dict) else {}
            if level == "off":
                extra.pop("naturalPrompts", None)
            elif natural:
                extra["naturalPrompts"] = natural
            # Copy ONLY on a real difference (review S5): an already-gated dict re-gates to the
            # SAME object, which the backstops in price_task and submit_generation rely on.
            if new_ph != ph or "naturalPrompts" in p \
                    or (extra or None) != (p.get("extra") if isinstance(p.get("extra"), dict)
                                            and p.get("extra") else None):
                q = _own()
                q["promptHelper"] = new_ph
                q.pop("naturalPrompts", None)
                if extra:
                    q["extra"] = extra
                else:
                    q.pop("extra", None)

    # G10 -- LoRA weights held to the architecture's range (T3-19 correction). Only when
    # /features supplied the modelType; lora_weight_range() gives the union -2..2 (today's
    # bound) for anything it does not list. One receipt entry per LoRA.
    wlo, whi = lora_weight_range(mtype)
    clamped = {}
    lmap = p.get("lora")
    if isinstance(lmap, dict):
        new_map, changed = {}, False
        for lvid, w in lmap.items():
            c = _lora_out_of_range(w, wlo, whi)
            if c is None:
                new_map[lvid] = w
            else:
                new_map[lvid] = c
                changed = True
                clamped.setdefault(str(lvid), (w, c))
        if changed:
            _own()["lora"] = new_map
    llist = p.get("loraParameters")
    if isinstance(llist, list):
        new_list, changed = [], False
        for e in llist:
            c = _lora_out_of_range(e.get("weight"), wlo, whi) if isinstance(e, dict) else None
            if c is None:
                new_list.append(e)
            else:
                new_list.append(dict(e, weight=c))
                changed = True
                clamped.setdefault(str(e.get("versionId")), (e.get("weight"), c))
        if changed:
            _own()["loraParameters"] = new_list
    for lvid, (asked, used) in clamped.items():
        adjusted.append({"field": "lora " + lvid, "asked": asked, "used": used,
                         "why": "LoRA weights on this model type run {:g} to {:g}".format(
                             wlo, whi)})

    # G1 -- the size grid and range (T3-02/03/04 as corrected). Lives HERE, not in
    # _gen_parameters._dim, so the CLI's plain build stays byte-identical.
    try:
        w, h = int(p.get("width")), int(p.get("height"))
    except (TypeError, ValueError):
        w = h = 0
    if w > 0 and h > 0:
        ranges = (_model_size_config(session, params["modelId"])
                  if mtype in DIT_SIZE_STEP_TYPES else None)
        rule = _size_rule(mtype, ranges)
        w2, h2 = _snap_size(w, h, rule)
        why = "this model takes sizes on a {} px grid from {} to {}".format(
            rule["step"], rule["lo"], rule["hi"])
        if w2 != w:
            adjusted.append({"field": "width", "asked": w, "used": w2, "why": why})
            _own()["width"] = w2
        if h2 != h:
            adjusted.append({"field": "height", "asked": h, "used": h2, "why": why})
            _own()["height"] = h2
    return p, adjusted


def _gate_params_for_model(session, params):
    """Gate a plain-image createGenerationTask's field set on the model, so the shape we
    PRICE and the shape we SUBMIT agree with what the model actually honors. Called from BOTH
    submit_generation and price_task with the IDENTICAL helper, so the cost badge cannot
    diverge from the real charge.

    Since 2026-09-26 this is the BACKSTOP form of _gate_image_params (the dict only, no
    receipt): the web road and the CLI gate once at build and hand an already-gated dict in,
    for which this returns the SAME object. For a caller off the road it applies the whole
    gate. The 2026-08-25 architecture branch it grew from is unchanged inside it:
    - NON-EMPTY inference profiles -> DiT. Fill the DEFAULT-flagged profile on auto (none
      flagged -> leave it ABSENT so the server picks; never synthesize) and drop
      samplingSteps/cfgScale/samplingMethod/clipSkip.
    - EMPTY `[]` -> SDXL (a definitive 200). Keep steps/cfg; strip inferenceProfile.

    BEST-EFFORT + FAIL-SOFT: no `modelId`, a non-image submit (video/edit/enhance flow through
    submit_generation too and must pass untouched), or a lookup that cannot be determined all
    leave the params as they are -- a failed lookup never breaks a submit or changes its spend
    outcome versus today. Non-mutating: returns the ORIGINAL object on every no-op path (so
    submit_generation's own in-place inferenceProfile drop-and-retry still mutates the
    caller's dict), and a shallow COPY only when a field actually changes. Raises PixAIError
    on the gate's one refusal (see _gate_image_params); price_task turns that into None."""
    return _gate_image_params(session, params)[0]


_LOST_UPSCALE_REFUSAL = ("No upscale is possible at this size -- the picture is already at "
                         "PixAI's upscale ceiling")


def _refuse_lost_upscale(args, params):
    """Refuse an Upscale that the build turned into a new context-image generation.

    The gate recognises the Upscale road on the BUILT dict (a top-level mediaId with enlarge
    or upscale), and _gen_parameters drops the ratio when it rounds to 1.0 or the source is
    already at PixAI's output ceiling. On a context-image model the gate then reads what is
    left as a new generation and sends the reference as a context image -- an Upscale click
    billed as a new Tsubaki.3 generation, the hazard SCOPE_2026-09-26 v2 names (review
    F7/R4). The intent is read off the caller's args: a reference plus an enlarge or upscale
    ratio above 1.0. A refusal costs nothing.

    Narrow on purpose: it fires only when the gate CONVERTED the reference. Anywhere else the
    dropped ratio leaves a same-size img2img plus its clamp receipt, exactly as before this
    branch -- the drawer's own img2img with Enhance Details past the Hires ceiling reaches
    that same built shape on SDXL, and refusing it would change a non-DiT generation. The
    Upscale panel never sends such a ratio (its goReady refuses <= 1 and the ceiling), so
    only a hand-made POST or the CLI reaches this."""
    from moonglade.backup import PixAIError
    def _asked(raw):
        try:
            return float(raw) > 1.0
        except (TypeError, ValueError):
            return False
    if not isinstance(params, dict) or not params.get("contextImages"):
        return
    if params.get("enlarge") or params.get("upscale"):
        return
    if not str(getattr(args, "ref_media_id", "") or "").strip():
        return
    if _asked(getattr(args, "enlarge", None)) or _asked(getattr(args, "upscale", None)):
        raise PixAIError(_LOST_UPSCALE_REFUSAL)


def _profile_listing(session, params):
    """(listed, members_only) for the params' inferenceProfile, off _model_profiles (the
    gate's cached read). (False, False) when there is no profile or the list is unreadable."""
    prof = str((params or {}).get("inferenceProfile") or "").strip().lower()
    if not prof or not (params or {}).get("modelId"):
        return False, False
    try:
        rows = _model_profiles(session, params["modelId"])
    except Exception:
        rows = None
    if not rows:
        return False, False
    for r in rows:
        if isinstance(r, dict) and str(r.get("profileName") or "").strip().lower() == prof:
            try:
                tier = int(r.get("requiredMembershipTier") or 0)
            except (TypeError, ValueError):
                tier = 0
            return True, (r.get("profileFlag") == "membershipOnly" or tier > 0)
    return False, False




def generation_model_brief(session, model_id):
    """{id, author_id, title, type, is_private, visibility} for one model. Read-only."""
    from moonglade.backup import _GEN_MODEL_Q, gql_adhoc, PixAIError
    d = (gql_adhoc(session, _GEN_MODEL_Q, {"id": str(model_id)}) or {}).get("generationModel")
    if not isinstance(d, dict):
        raise PixAIError("model %s not found" % model_id)
    return {"id": str(d.get("id") or ""), "author_id": str(d.get("authorId") or ""),
            "title": str(d.get("title") or ""), "type": str(d.get("type") or ""),
            "is_private": bool(d.get("isPrivate")),
            "visibility": str(d.get("visibilityType") or "")}
