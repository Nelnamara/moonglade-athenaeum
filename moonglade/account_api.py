"""
moonglade/account_api.py
========================
The account on PixAI: --probe and --count, the published-artwork list and views, the artwork
writes (`publish_artwork_from_task`, `update_artwork`, `delete_artwork`) and tack ids, the LoRA
rebates, a task's source media and media index, the account reads (`account_info`,
`account_is_member`, `credit_balance`, the LoRA cap and --account), suggest-prompt and tag
search, the claims (`list_claims`, `claim_reward`, --claims) and the cards, coupons and
credit-log runners. Moved verbatim out of moonglade/backup.py in the 3.22 split (phase 4).

The names it reads from the engine (the transport -- _make_session, gql_adhoc, gql_mutate and
the /v2 REST verbs -- _check_read_only, the error classes, MEDIA_BASE, _TRUSTSTORE_ACTIVE,
upload_media and _format_size, which tests patch there) are
imported from moonglade.backup inside each function that uses them, at call time, so a test's
patch of backup's binding still reaches them and importing this module never imports the
engine. The catalog's load_catalog comes from moonglade.catalog.
"""
import datetime
import json
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")

from moonglade import cards as _cards
from moonglade import full_meta as _full_meta
from moonglade import gen_cli as _gen_cli
from moonglade import gen_params as _gen_params
from moonglade import history as _history
from moonglade import library_runs as _library_runs
from moonglade import media_fetch as _media_fetch
from moonglade import paths as _paths
from moonglade import pixai_client as _pixai_client
from moonglade import task_reads as _task_reads
from moonglade.scan import DELETED_DIRNAME, _VIDEO_EXTS


def run_probe(args):
    """Test API connection and resolve full-res media URL for the newest task."""
    from moonglade.backup import _make_session, _TRUSTSTORE_ACTIVE
    session = _make_session(getattr(args, "token", None))
    print("SSL trust store via truststore: {}".format(
        "on" if _TRUSTSTORE_ACTIVE else "off (requests default)"))
    print("Fetching newest page...\n")
    conn = _history.find_connection(_history.gql(session, _media_fetch.page_variables(
        args.page_size, _pixai_client._client_of(session).user_id)))
    if not conn:
        print("No connection found.")
        return
    edges = conn.get("edges", [])
    pi = conn.get("pageInfo", {})
    print("OK -- {} items. hasPreviousPage={}".format(
        len(edges), pi.get("hasPreviousPage")))
    node = edges[0].get("node", edges[0]) if edges else {}
    meta = _history.extract_meta(node)
    mids = _history.media_ids_for(node)
    print("First task: id={} media_ids={}".format(meta["task_id"], mids))
    print("Prompt preview:", meta["prompt_preview"][:80])
    if mids:
        url, info = _media_fetch.resolve_media(session, mids[0])
        print("\nResolved full-res URL:", url or "(none!)")
        print("Dimensions: {}x{}".format(info.get("width"), info.get("height")))
        if url:
            print("\nLooks right? Run a download to back up everything.")
        else:
            print("\nCouldn't find a URL in the media object -- paste this back.")


def run_count(args):
    """Tally total tasks and images in the library without downloading."""
    from moonglade.backup import _format_size, _make_session
    session = _make_session(getattr(args, "token", None))
    count_size = getattr(args, "count_page_size", _history.COUNT_PAGE_SIZE)
    print("Counting your whole library (page size {})...".format(count_size))
    before = None
    tasks = images = page = 0
    batched_tasks = 0
    while True:
        page += 1
        conn = _history.find_connection(_history.gql(session, _media_fetch.page_variables(
            count_size, _pixai_client._client_of(session).user_id, before)))
        if not conn:
            break
        edges = conn.get("edges", [])
        if not edges:
            break
        for edge in edges:
            node = edge.get("node", edge)
            tasks += 1
            n = len(_history.media_ids_for(node))
            images += n
            if n > 1:
                batched_tasks += 1
        pi = conn.get("pageInfo", {})
        more = pi.get("hasPreviousPage")
        print("  page {}: {} tasks so far, {} images so far{}".format(
            page, tasks, images, "" if more else "  (reached the end)"))
        if not more:
            break
        before = pi.get("startCursor")
        time.sleep(args.delay)
    print("\n================ LIBRARY TOTALS ================")
    print("Total tasks (generations) : {}".format(tasks))
    print("Total images              : {}  (mediaId + batchMediaIds)".format(images))
    print("Tasks that are batches    : {}  (>1 image each)".format(batched_tasks))
    print("Fetched in {} request(s).".format(page))
    out = Path(args.out)
    counts = _library_runs._count_backup_images(out) if out.exists() else _library_runs.DiskCounts(0, 0, 0)
    disk_count, disk_bytes, thumb_count = counts
    print("\n--- On disk ({}) ---".format(args.out))
    print("Image files on disk       : {}".format(disk_count))
    if thumb_count:
        print("  + preview thumbnails    : {}".format(thumb_count))
    if counts.trashed:
        print("  + soft-deleted (trash)  : {}  ({}, in {}/)".format(
            counts.trashed, _format_size(counts.trashed_bytes), DELETED_DIRNAME))
    print("Total collection size     : {}".format(
        _format_size(disk_bytes) if disk_bytes else "0 B (folder empty or not found)"))
    if images > tasks:
        print("\nNote: image count exceeds task count because some older tasks\n"
              "produced batches of several images -- all of them get downloaded.")


# The owner's published artworks as a full query document. The selection is exactly what
# the two readers use (extract_artwork_meta, the sweep's page test and run_sync_artworks'
# video pass) and nothing else. It NEVER selects `views`: reading a view count counts as a
# view on every work the query returns (see artwork_views_bulk), and this read runs every
# fifteen minutes. Pages walk BACKWARD from the newest end (last / before), so the first
# page holds the newest works and `hasPreviousPage` / `startCursor` lead to the older ones.
_ARTWORK_LIST_DOC = (
    "query($a: ID!, $n: Int, $before: String, $lang: String) {"
    " artworks(authorId: $a, last: $n, before: $before) {"
    " edges { node { id mediaId videoMediaId title visibility isNsfw isSensitive"
    " likedCount commentCount aesScore tacks { codeName displayName(language: $lang) }"
    " extra } }"
    " pageInfo { hasPreviousPage startCursor } } }")


def _artwork_list_reason(exc):
    """Why an artwork-list read failed, in plain words: the kind of failure and PixAI's own
    message. A GraphQL refusal gives PixAI's error code and message; anything else gives the
    exception's class and text. Capped, and left unredacted: the caller that logs it knows
    which folders to hide."""
    errors = getattr(exc, "graphql_errors", None)
    said = []
    if isinstance(errors, list):
        for err in errors[:3]:
            if not isinstance(err, dict):
                continue
            ext = err.get("extensions") if isinstance(err.get("extensions"), dict) else {}
            kind = str(ext.get("code") or "").strip()
            msg = str(err.get("message") or "").strip()
            if kind or msg:
                said.append("{}: {}".format(kind, msg) if kind and msg else (kind or msg))
    if said:
        return "PixAI refused the request ({})".format("; ".join(said))[:300]
    text = str(exc).strip()
    return "{}{}".format(type(exc).__name__, ": " + text if text else "")[:300]


def artwork_list_gql(session, before=None, last=50, retries=None):
    """One page of the owner's own published artworks, read as a full query document
    (`_ARTWORK_LIST_DOC`) over the ad-hoc road. Returns the Relay connection dict (`edges`
    of `node`s, and `pageInfo` with `hasPreviousPage` / `startCursor`); `before` is the
    previous page's `startCursor`, and None starts at the newest end.

    A read that cannot be completed RAISES `ArtworkListRefused` carrying the reason in plain
    words (`_artwork_list_reason`): PixAI's refusal, a network failure, or an answer with no
    artwork list in it. It used to hand back None and swallow the reason, which left a
    failing fifteen-minute sweep logging a bare "page 1 fetch failed" with nothing to go on.
    Read-only (a query, never a mutation) and costs nothing; re-reading a page changes no
    number on PixAI's side. `retries` is gql_adhoc's: None keeps the default query retries
    (--sync-artworks, run by hand), and the fifteen-minute sweep passes 0 so a stalled PixAI
    costs it one attempt, not minutes -- the next sweep is the retry."""
    from moonglade.backup import ArtworkListRefused, gql_adhoc, PixAIError
    author = str(_pixai_client._client_of(session).user_id or "")
    if not author:
        raise ArtworkListRefused("the app has no PixAI account id to read artworks for")
    variables = {"a": author, "n": last, "lang": "en"}
    if before:
        variables["before"] = before
    try:
        data = gql_adhoc(session, _ARTWORK_LIST_DOC, variables, retries=retries)
    except (requests.RequestException, PixAIError, ValueError, TypeError) as e:
        raise ArtworkListRefused(_artwork_list_reason(e)) from e
    conn = _history.find_connection(data or {})
    if conn is None:
        raise ArtworkListRefused("PixAI answered, but with no list of artworks in it")
    return conn


def artwork_views_bulk(session, page_size=40, delay=0.4, max_pages=60):
    """{artwork_id: views} for the owner's whole published library, in paced bulk pages.
    Returns (views, complete) -- `complete` False means a page failed and the map is a
    partial answer, never a total to present as whole.

    WHY THIS EXISTS AT ALL. Views are the one engagement number the artwork listing
    (artwork_list_gql) deliberately does not select, because reading one counts as a view and
    the listing is read every fifteen minutes. Fetching them one-artwork-at-a-time, live,
    is what made the My Art panel slow and its totals a subtotal. PROBE_2026-09-06 settled
    the open question: the AD-HOC bulk form `artworks(authorId, first:N)` -- already proven
    for field-probing by PROBE_2026-08-24 -- accepts `views`. A hundred works cost three
    calls here instead of a hundred, and they are paid once per sync rather than once per
    open.

    READING A VIEW COUNT COSTS A VIEW. The same probe measured it directly: a page that
    selects `views` increments the counter for EVERY artwork it returns (40 rows read, all
    40 up by one, repeatedly); a page that does not select `views` costs nothing. There is
    no way to observe this number without perturbing it, so the design goal is to observe
    it RARELY AND PREDICTABLY -- once per deliberate --sync-artworks -- rather than on
    every idle glance at a panel. views_spike() subtracts the sweep's own read before
    calling anything a spike; do not remove that subtraction on the theory that it is a
    rounding error, it is the difference between "nobody looked" and "+1 forever".

    SINGLE ATTEMPT, and that is not a style choice. Because the read PERTURBS the thing it
    reads, this is the same class of call `gql_mutate` exists for even though it is
    technically a query: a lost RESPONSE looks exactly like a lost REQUEST (a read timeout,
    a proxy's 502 arriving after PixAI already answered and already bumped the counters),
    so a retry re-reads -- and re-increments -- the same forty artworks inside one sweep.
    Those rows then carry +2 of the sweep's own making while views_spike subtracts exactly
    SPIKE_SELF_READ = 1, which permanently inflates their stored count and can push a
    borderline work over the floor into a false "is taking off" note. `retries=0` is
    therefore passed by hand here, the same way delete_batch_media_gql does for its own
    non-idempotent call; a page that fails falls into the except below and reports the
    sweep incomplete, which is the honest answer.

    Read-only in the sense that matters for the account: a query, never a mutation, and
    nothing here spends credits."""
    from moonglade.backup import gql_adhoc, PixAIError
    try:
        author = str(_pixai_client._client_of(session).user_id or "")
    except AttributeError:
        return {}, False
    if not author:
        return {}, False
    doc = ('query($a: ID!, $n: Int, $after: String) {'
           ' artworks(authorId: $a, first: $n, after: $after) {'
           ' edges { node { id views } } pageInfo { hasNextPage endCursor } } }')
    views, cursor, pages = {}, None, 0
    while pages < max_pages:
        pages += 1
        try:
            data = gql_adhoc(session, doc,
                             {"a": author, "n": int(page_size), "after": cursor}, retries=0)
        except (requests.RequestException, PixAIError, ValueError, TypeError):
            return views, False
        conn = ((data or {}).get("artworks")) or {}
        edges = conn.get("edges") or []
        for e in edges:
            n = (e or {}).get("node") or {}
            aid = str(n.get("id") or "")
            if aid and n.get("views") is not None:
                try:
                    views[aid] = int(n["views"])
                except (TypeError, ValueError):
                    pass
        pi = conn.get("pageInfo") or {}
        if not edges or not pi.get("hasNextPage"):
            return views, True
        cursor = pi.get("endCursor")
        if not cursor:
            return views, True
        time.sleep(delay)
    return views, False               # ran out of pages: partial, and says so


def extract_artwork_meta(node):
    """Pull the published-artwork fields we store from a node of the artwork list.
    Keyed by media_id so it merges onto the existing catalog row.

    The list's node already carries an `extra` block (no extra request), from which we
    also lift a compact BlurHash (instant gallery placeholders) + PixAI's per-category NSFW
    classifier scores (a finer signal than the binary is_nsfw). Published rows only."""
    tacks = node.get("tacks") or []
    tags = [t.get("displayName") or t.get("codeName") for t in tacks
            if (t.get("displayName") or t.get("codeName"))]
    extra = node.get("extra") if isinstance(node.get("extra"), dict) else {}
    scores = extra.get("nsfwPredict")
    nsfw_scores = ""
    if isinstance(scores, dict):
        # keep it small + deterministic: round each category to 3 decimals
        try:
            nsfw_scores = json.dumps({k: round(float(v), 3) for k, v in scores.items()
                                      if isinstance(v, (int, float))}, separators=(",", ":"))
        except (TypeError, ValueError):
            nsfw_scores = ""
    return {
        "media_id":      str(node.get("mediaId") or ""),
        "artwork_id":    str(node.get("id") or ""),
        "title":         node.get("title") or "",
        "is_published":  "1" if (node.get("visibility") == "PUBLIC") else "0",
        "is_nsfw":       "1" if node.get("isNsfw") else "0",
        "liked_count":   str(node.get("likedCount") or 0),
        "comment_count": str(node.get("commentCount") or 0),
        "aes_score":     str(node.get("aesScore") or ""),
        "art_tags":      ", ".join(tags),
        "blurhash":      str(extra.get("imageBlurHash") or ""),
        "nsfw_scores":   nsfw_scores,
        # PixAI's own moderation flag, distinct from the binary is_nsfw (a work can be
        # sensitive without being nsfw) -- already in the artwork list's answer, the app just
        # never read it (#20). Powers the "Sensitive" badge in My Art.
        "is_sensitive":  "1" if node.get("isSensitive") else "0",
    }


# Read-only account dashboard. Ad-hoc query (no persisted hash) -- the selection
# below mirrors what the site's getMyQuota + getMyMembership return. READ ONLY:
# this only reports your credit balance / plan. It never moves money. Buying
# credits or changing your subscription is deliberately NOT implemented -- do that
# in the browser.
# `roles` (2026-07-24) is the account's own role list -- the owner's carries BETA_TO_INVITE,
# the flag behind PixAI's early-access programs (the Tsubaki.3 / DiT.3 invite). One extra leaf
# field on the query the header chip, --account and /api/account already run: no extra call,
# no spend. Only the field NAME was probed, not its exact shape, so every consumer must
# normalize rather than assume a list (see /api/account).
_ACCOUNT_QUERY = """
query {
  me {
    id
    quotaAmount
    tasks { totalCount }
    followerCount
    followingCount
    referralCode { code }
    membership { membershipId tier privilege }
    subscription { planId provider interval status startAt endAt cancelAtPeriodEnd }
  }
}
"""


def artwork_views(session, artwork_id):
    """Live view count for one of the owner's published artworks (ad-hoc `artwork(id){views}`,
    no persisted hash). Views dwarf likes and aren't stored locally -> the 'Your Art' panel's
    headline signal. Read-only; 0 on any failure."""
    from moonglade.backup import gql_adhoc, PixAIError
    if not artwork_id:
        return 0
    try:
        d = gql_adhoc(session, "query($id:ID!){ artwork(id:$id){ views } }",
                      {"id": str(artwork_id)})
        return int(((d or {}).get("artwork") or {}).get("views") or 0)
    except (PixAIError, TypeError, ValueError):
        return 0


_UPSERT_ARTWORK = (
    "mutation upsertArtwork($input: UpsertArtworkInput!, $id: ID) {"
    " upsertArtwork(input: $input, id: $id) { id mediaId title visibility hidePrompts } }")
_PUBLISH_FROM_TASK = (
    "mutation createArtworkFromTaskV2($taskId: ID!, $input: CreateArtworkFromTaskInput!) {"
    " createArtworkFromTaskV2(taskId: $taskId, input: $input)"
    " { id mediaId title visibility hidePrompts } }")
_DELETE_ARTWORK = "mutation deleteArtwork($id: ID!) { deleteArtwork(id: $id) }"
_LIST_TACKS = (
    "query listTacks($q: String, $first: Int) { tacks(q: $q, first: $first) {"
    " edges { node { id codeName defaultName } } } }")


def resolve_tack_ids(session, tags):
    """Map plain tag strings to PixAI 'tack' ids (their tag objects). The publish form
    sends `tackIds`, not free text -- `tags` is always [] in the real payload -- so a tag
    that has no tack simply cannot be attached, and is reported back to the caller rather
    than silently dropped. Read-only. Returns (ids, unmatched)."""
    from moonglade.backup import gql_adhoc, PixAIError
    ids, unmatched = [], []
    for t in tags or []:
        name = str(t).lstrip("#").strip()
        if not name:
            continue
        try:
            d = gql_adhoc(session, _LIST_TACKS, {"q": name, "first": 8}) or {}
            edges = ((d.get("tacks") or {}).get("edges")) or []
        except PixAIError:
            edges = []
        hit = None
        for e in edges:
            n = (e or {}).get("node") or {}
            if str(n.get("codeName") or "").lower() == name.lower() \
                    or str(n.get("defaultName") or "").lower() == name.lower():
                hit = n
                break
        # NO fuzzy fallback to edges[0] here -- that used to silently attach whatever
        # ranked first in PixAI's search (e.g. typing "moon" attaching "moonlight") with
        # no signal in the preview, contradicting this function's own contract below.
        # Found by ultrareview 2026-08-06: a real, unreported substitution onto a public
        # artwork. Only an EXACT codeName/defaultName match counts as resolved now;
        # anything else is reported in `unmatched`, exactly as promised.
        if hit and hit.get("id"):
            ids.append(str(hit["id"]))
        else:
            unmatched.append(name)
    return ids, unmatched


def lora_rebate_eligibility(session, model_id):
    """PixAI's rebate check for one of your LoRAs: {offered, joined, can_join}. Read-only;
    a failed read answers not offered."""
    from moonglade.backup import PixAIError, _rest_get
    try:
        d = _rest_get(session, "/generation-model/%s/lora-rebate-eligibility"
                      % str(model_id).strip()) or {}
    except (PixAIError, requests.RequestException):
        return {"offered": False, "joined": False, "can_join": False}
    offered = d.get("featureStatus") == "enabled"
    joined = offered and d.get("eligibility") == "accept"
    allowed = d.get("allowedTargetEligibilities") or []
    return {"offered": offered, "joined": joined,
            "can_join": offered and not joined and "accept" in allowed}


_THUMB_VARIANTS = ("STILL_THUMBNAIL", "THUMBNAIL", "PUBLIC", "ORIGINAL")


def media_thumbnail_url(session, media_id):
    """A small picture URL for one PixAI media id -- for training-set images this library has
    no thumbnail of (an upload, or an image imported from an earlier set). Reads the media
    object (GET /v1/media/<id>, read-only) and prefers a thumbnail variant. None on failure."""
    from moonglade.backup import MEDIA_BASE
    mid = str(media_id or "").strip()
    if not mid.isdigit():
        return None
    try:
        r = session.get(MEDIA_BASE.format(id=mid), timeout=20)
        r.raise_for_status()
        obj = r.json()
    except (requests.RequestException, ValueError):
        return None
    by = {str(u.get("variant", "")).upper(): u.get("url") for u in (obj.get("urls") or [])
          if isinstance(u, dict) and u.get("url")}
    for v in _THUMB_VARIANTS:
        if by.get(v):
            return by[v]
    return next(iter(by.values()), None)


def join_lora_rebates(session, model_id):
    """IRREVERSIBLE: join one of your public LoRAs to the rebate programme (PATCH
    lora-rebate-eligibility {eligibility: accept}, the site's call). Single attempt."""
    from moonglade.backup import _check_read_only, _rest_patch
    _check_read_only("join a LoRA to rebates")
    return _rest_patch(session, "/generation-model/%s/lora-rebate-eligibility"
                       % str(model_id).strip(), {"eligibility": "accept"}) or {}


def source_media_of_task(task):
    """The SOURCE image a derived generation was made FROM, plus what kind of derivation
    it was -- returns (source_media_id, kind) or (None, None) for an original generation.

    This is the data behind Image Details' LINEAGE panel. Every derive path already puts
    its input image's mediaId in the submit parameters, and PixAI persists it on the task,
    so it is readable back from getTaskById for history as well as recordable going
    forward. The four real shapes (see build_video_parameters / build_chat_edit_parameters
    / build_panelplugin_parameters / the upscale block):
      * img2video       -> parameters.i2vPro.mediaId        (kind "video"; legacy tasks: i2v)
      * edit/reference  -> parameters.chat.mediaId          (kind "edit")
      * enhance/plugin  -> parameters.inputs.image.media_id (kind "enhance")
      * upscale/hires   -> parameters.mediaId + upscale|enlarge ratio  (kind "upscale")
      * context image   -> parameters.contextImages[0]      (kind "derived")
    A plain txt2img has no input image and returns (None, None).

    Context images (SCOPE_2026-09-26 E3): a Tsubaki.3 / Flash generation made from a
    reference carries its source ONLY in `contextImages` -- no top-level mediaId, no chat
    block (the owner's seven 2026-09-23 runs) -- and a site Edit-dialog instruction edit of
    a Tsubaki picture has the same shape, so the two cannot be told apart from parameters
    and both file as "derived", the img2img kind. With two or more context images the FIRST
    is the source; which one "counts" beyond that is a design call not made here."""
    params = ((task or {}).get("parameters") or {})
    if not isinstance(params, dict):
        return (None, None)
    # i2vPro is the current image-to-video submit shape; `i2v` is the legacy key older
    # tasks carry. Reading only `i2v` meant EVERY modern i2v task returned (None,None), so
    # video lineage was never captured -- create-time OR --backfill-lineage (audit 2026-08-15).
    i2v = params.get("i2vPro") or params.get("i2v")
    if isinstance(i2v, dict) and i2v.get("mediaId"):
        return (str(i2v["mediaId"]), "video")
    chat = params.get("chat")
    if isinstance(chat, dict) and chat.get("mediaId"):
        return (str(chat["mediaId"]), "edit")
    # Enhance (panelplugin workflow -- handfix / bg-remove / line-art / sketch-coloring / ...):
    # the source image is nested at inputs.image.media_id in the b93ce1e submit shape
    # (build_panelplugin_parameters). This MUST be checked BEFORE the top-level `mediaId`
    # branch below: a Bridge result carries no top-level mediaId, so without this branch it
    # files as an ORIGINAL generation with no source (catalog lineage correctness, not polish).
    # VERIFIED 2026-08-18 against a real completed panelplugin task (bg-remove, task
    # 2046466559401368536): getTaskById reads the source back as inputs.image.media_id in
    # snake_case -- PixAI does NOT camelCase it to mediaId on persist. So `media_id` is the
    # live read-back shape and the `mediaId` fallback below is defensive-only (kept in case a
    # future submit/persist shape change flips it).
    inputs = params.get("inputs")
    if isinstance(inputs, dict):
        img = inputs.get("image")
        if isinstance(img, dict):
            emid = img.get("media_id") or img.get("mediaId")
            if emid:
                return (str(emid), "enhance")
    mid = params.get("mediaId")
    if mid:
        ratio = params.get("upscale") or params.get("enlarge")
        return (str(mid), "upscale" if ratio else "derived")
    ctx = params.get("contextImages")
    if isinstance(ctx, list) and ctx and ctx[0] and str(ctx[0]).strip():
        return (str(ctx[0]).strip(), "derived")
    return (None, None)


def task_media_index(session, task_id, media_id):
    """Which image of a task a given media_id IS -- the `mediaIndex` the publish mutation
    needs. Never guessed from a filename: a batchSize>1 task stores its individuals under
    outputs.batch[] and their ORDER is the index PixAI means.

    It is PixAI's OWN output number -- the RAW position in that array, counted with deleted
    members still occupying their slots, the same number `batch_position` reports and the
    same <n> the site's own from-PixAI-<taskId>-<n> download names use. Counting only the
    members PixAI still has (`_task_image_media`, which skips them, is the right enumeration
    for DOWNLOADING and the wrong one here) shifts every image after a deletion down one
    slot: on a batch whose first picture was deleted, publishing the third would send index
    1, which is the second picture's slot, and the wrong picture would go to the owner's
    public profile with nothing saying so.

    Read-only. Returns the int index, or None -- publish nothing -- when the task can't be
    read, when the batch does not list this image at all (a stale row, or the batch's
    combined preview picture), or when PixAI has already deleted this image: a member with a
    `deletedAt` is no longer one of the task's outputs, so it has no number to publish at.
    A task with no batch array (a single-image generation, an edit, an upscale) resolves
    from its own ordered outputs instead, where the lone image is index 0. The caller decides
    whether None is fatal (it is, for publishing: publishing the wrong image of a batch is
    not a recoverable mistake)."""
    from moonglade.backup import PixAIError
    if not task_id or not media_id:
        return None
    try:
        task = _task_reads.task_detail_gql(session, str(task_id))
    except PixAIError:
        return None
    if not task:
        return None
    outputs = task.get("outputs") or {}
    batch = outputs.get("batch")
    if isinstance(batch, list) and batch:
        # batch_position answers blank for BOTH "not one of this task's outputs" and "PixAI
        # deleted this one", and neither may be published -- so both land on None here.
        bi, _size = _full_meta.batch_position(batch, media_id)
        return int(bi) if bi != "" else None
    for i, (mid, _seed) in enumerate(_gen_cli._task_image_media(outputs)):
        if str(mid) == str(media_id):
            return i
    return None


def publish_artwork_from_task(session, task_id, media_index=0, title="", description="",
                              tack_ids=None, private=False, hide_prompts=False,
                              challenge=None, extra=None):
    """Publish one image of a generation task as a PixAI ARTWORK
    (`createArtworkFromTaskV2`). Account-mutating (it puts work on your public profile),
    so it goes through gql_mutate -- single attempt, no retry: a lost response after the
    server already created the artwork would otherwise publish a duplicate. Costs no
    credits. Input shape mirrors the site's own publish form exactly (title/description/
    visibility/isPrivate/hidePrompts/tags=[]/tackIds/mediaIndex, challenge inside extra).
    Returns the created artwork dict; raises PixAIError on failure.

    `challenge` DOES NOT ENTER A CONTEST -- verified live 2026-09-01, after a publish made
    with one attached produced no entry. It is artwork METADATA: the contest back-link that
    listArtworks hands back on node.extra (../moonglade-internal/private/API_OPERATIONS.md). Entering is a
    separate REST call, `contest_enter` -> POST /v2/contest/{slug}/artwork, and a caller
    that wants publish-and-enter has to make both (see api_myart_publish, which does)."""
    from moonglade.backup import _check_read_only, gql_mutate
    _check_read_only("publish an artwork to your PixAI account")
    vis = "PRIVATE" if private else "PUBLIC"
    ex = dict(extra or {})
    if challenge:
        ex["challenge"] = challenge
    if description:
        ex["description"] = description
    inp = {
        "title": title or "",
        "description": description or "",
        "tags": [],                       # always empty on the wire; tackIds carries tags
        "tackIds": list(tack_ids or []),
        "visibility": vis,
        "isPrivate": bool(private),
        "hidePrompts": bool(hide_prompts),
        "mediaIndex": int(media_index or 0),
        "extra": ex,
    }
    d = gql_mutate(session, _PUBLISH_FROM_TASK,
                   {"taskId": str(task_id), "input": inp}) or {}
    return d.get("createArtworkFromTaskV2") or {}


def update_artwork(session, artwork_id, media_id=None, title=None, description=None,
                   tack_ids=None, private=None, hide_prompts=None, extra=None):
    """Edit an EXISTING artwork (`upsertArtwork` with an id) -- retitle, re-tag, or flip
    visibility (the My Art publish-toggle / edit-tags actions). Account-mutating ->
    gql_mutate. Only the fields you pass are sent, so a tag edit can't silently reset a
    title. Returns the updated artwork dict; raises PixAIError on failure."""
    from moonglade.backup import _check_read_only, gql_mutate, PixAIError
    _check_read_only("edit an artwork on your PixAI account")
    inp = {}
    if media_id is not None:
        inp["mediaId"] = str(media_id)
    if title is not None:
        inp["title"] = title
    if tack_ids is not None:
        inp["tags"] = []
        inp["tackIds"] = list(tack_ids)
    if private is not None:
        inp["visibility"] = "PRIVATE" if private else "PUBLIC"
        inp["isPrivate"] = bool(private)
    if hide_prompts is not None:
        inp["hidePrompts"] = bool(hide_prompts)
    ex = dict(extra or {})
    if description is not None:
        ex["description"] = description
    if ex:
        inp["extra"] = ex
    if not inp:
        raise PixAIError("update_artwork: nothing to change")
    d = gql_mutate(session, _UPSERT_ARTWORK,
                   {"id": str(artwork_id), "input": inp}) or {}
    return d.get("upsertArtwork") or {}


def delete_artwork(session, artwork_id):
    """Unpublish/delete one artwork from your PixAI account (`deleteArtwork`).
    IRREVERSIBLE on their side; your local files and catalog row are untouched.
    Single attempt (gql_mutate) so a flaky network can never delete twice. A void
    mutation: success is the ABSENCE of an error, not the payload."""
    from moonglade.backup import _check_read_only, gql_mutate
    _check_read_only("delete an artwork from your PixAI account")
    gql_mutate(session, _DELETE_ARTWORK, {"id": str(artwork_id)})
    return True


def account_info(session, raise_on_error=False):
    """Fetch credits + membership/subscription via ad-hoc GraphQL. Returns the `me` dict.
    Fails soft to {} by default (the web header chip relies on that); pass raise_on_error=True
    to let the real PixAIError propagate so a caller can report WHY (auth vs transient).
    Read-only. Note gql_adhoc already retries network/429/5xx 3x with backoff, so an error
    here means a sustained outage or a real auth/GraphQL problem, not a one-off blip."""
    from moonglade.backup import gql_adhoc, PixAIError
    try:
        return (gql_adhoc(session, _ACCOUNT_QUERY) or {}).get("me") or {}
    except PixAIError:
        if raise_on_error:
            raise
        return {}


def account_is_member(me):
    """Is there an ACTIVE PixAI membership on this account? True / False / None=unknown.

    MEASURED 2026-07-28 against the owner's deliberately-lapsed account: `membership` comes
    back as **null** the moment it expires, while `subscription` lingers as a historical
    record -- status "inactive", a past endAt, cancelAtPeriodEnd true. So membership's
    PRESENCE is the signal and subscription is not: reading `subscription.planId` would call
    a lapsed account premium forever. An active account carries membership{membershipId,
    tier, privilege} (tier 3 on the 2026-07-06 probe).

    Returns None when `me` is empty -- i.e. the account could not be read at all. Callers
    MUST fail OPEN on None: a network blip or a transient GraphQL error must never silently
    strip a paying member's entitlements mid-session. Only an explicit False gates anything,
    the same convention as the model-capability gate."""
    if not me:
        return None
    return bool(me.get("membership"))


_CREDIT_BALANCE_QUERY = """
query {
  me {
    id
    total: quotaAmount
    free: quotaAmount(currency: "free")
    paid: quotaAmount(currency: "paid")
  }
}
"""


def credit_balance(session):
    """Read the account's credit balance split Paid vs Free -- the same three numbers the
    site's own Membership & Credits page shows, where account_info()'s `quotaAmount` only
    ever surfaces the lump total. Returns {"total", "free", "paid"} (ints, or None on error).

    ** The mechanism, learned the hard way (2026-08-07): the split is `me { quotaAmount,
    quotaAmount(currency: "free"), quotaAmount(currency: "paid") }` -- aliased fields on
    `me`, with the currency codes being the bare strings "free"/"paid". The ORIGINAL query
    `user(id).{total,free,paid}` was invalid (PixAI: "Cannot query field total on type
    User") and always failed; a long probe missed the codes because `freeCredit`/`paidCredit`
    etc. all return null and introspection is disabled. The exact query was finally recovered
    from the site's own bundled operation AST (owner-supplied currency dump). Verified live:
    free 219,951 + paid 3,533,040 = total 3,752,991. ** Read-only; fails soft to all-None."""
    from moonglade.backup import gql_adhoc, PixAIError
    try:
        data = gql_adhoc(session, _CREDIT_BALANCE_QUERY, {}) or {}
    except (PixAIError, requests.RequestException, ValueError):
        return {"total": None, "free": None, "paid": None}
    me = data.get("me") or {}
    return {"total": me.get("total"), "free": me.get("free"), "paid": me.get("paid")}


# PixAI's free-tier LoRAs-per-generation allowance. Their own generate panel prints it
# verbatim beside the LoRA section as "Free: 0/3   Max: 15 (crowned)", measured 2026-07-28
# on a lapsed account, and the owner independently confirmed 3 is his live cap. It is a
# CONSTANT here because `membership.privilege` -- where the paid cap lives -- is null for a
# non-member, so there is no field to read it from. If PixAI ever moves it, the symptom is a
# refused submit (LORA_NUM_EXCEEDED), not a silent overspend.
FREE_LORA_CAP = 3


def account_lora_cap(me):
    """LoRAs-per-generation this account may use. int, or None when genuinely unknown.

    Three cases, and the middle one is the bug this exists to fix:
      * `me` empty            -> None. The account could not be read; callers fail OPEN.
      * membership present    -> privilege.lora, else privilege.freeUserLora.
      * membership NULL       -> FREE_LORA_CAP. A non-member is not "unknown", it is the
                                 free tier -- and returning None here is what silently
                                 disabled the cap guard the moment the owner's membership
                                 lapsed, letting six LoRAs reach PixAI against a cap of
                                 three (LORA_NUM_EXCEEDED, reproduced 2026-07-28)."""
    if not me:
        return None
    priv = ((me.get("membership") or {}).get("privilege")) or {}
    cap = priv.get("lora")
    if cap is None:
        cap = priv.get("freeUserLora")
    if cap is None:
        return FREE_LORA_CAP if not me.get("membership") else None
    try:
        return int(cap)
    except (TypeError, ValueError):
        return None


def run_account_info(args):
    """Print a read-only account dashboard: credit balance, membership, and
    subscription status. Never initiates payment -- buy credits in the browser."""
    from moonglade.backup import _make_session, PixAIError
    session = _make_session(getattr(args, "token", None))
    try:
        me = account_info(session, raise_on_error=True)
    except PixAIError as e:
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg:
            print("Account read failed: your API key is missing or expired -- check config.json.")
        else:
            # gql_adhoc already retried; this is a sustained network/API hiccup, not your key.
            print("Account read failed (temporary API/connection issue) -- try again in a moment.")
            print("  detail: {}".format(msg[:160]))
        return {}
    if not me:
        print("Account read returned no data -- try again in a moment.")
        return {}
    mem = me.get("membership") or {}
    sub = me.get("subscription") or {}
    priv = mem.get("privilege") or {}
    try:
        credits = "{:,}".format(int(me.get("quotaAmount") or 0))
    except (TypeError, ValueError):
        credits = str(me.get("quotaAmount"))
    print("Account ID       : {}".format(me.get("id") or _pixai_client._client_of(session).user_id))
    print("Credits (balance): {}".format(credits))
    balance = credit_balance(session)
    if balance["free"] is not None or balance["paid"] is not None:
        print("  of which free  : {:,}".format(int(balance["free"] or 0)))
        print("  of which paid  : {:,}".format(int(balance["paid"] or 0)))
    server_tasks = ((me.get("tasks") or {}).get("totalCount"))
    if server_tasks is not None:
        print("Lifetime tasks   : {:,}  (server's count of every generation you've made)".format(
            int(server_tasks)))
    if me.get("followerCount") is not None:
        print("Followers        : {:,}  (following {:,})".format(
            int(me.get("followerCount") or 0), int(me.get("followingCount") or 0)))
    if me.get("referralCode"):
        print("Referral code    : {}".format((me.get("referralCode") or {}).get("code", "-")))
    if mem:
        print("Membership       : {} (tier {})".format(
            mem.get("membershipId", "-"), mem.get("tier", "-")))
        if priv.get("dailyClaimAdded"):
            print("Daily free claim : {:,}".format(int(priv["dailyClaimAdded"])))
        if priv.get("professionalMode"):
            print("Professional mode: on")
        # The rest of the membership entitlements (were fetched, never shown).
        if priv.get("paidCredit"):
            print("Credit ceiling   : {:,}".format(int(priv["paidCredit"])))
        slots = []
        if priv.get("lora") is not None:
            slots.append("{} LoRA".format(priv["lora"]))
        if priv.get("freeUserLora") is not None:
            slots.append("{} free-user LoRA".format(priv["freeUserLora"]))
        if priv.get("privateModel") is not None:
            slots.append("{} private-model".format(priv["privateModel"]))
        if slots:
            print("Slots            : {}".format(", ".join(slots)))
        if priv.get("extraPackageValue"):
            print("Extra package    : {:,}".format(int(priv["extraPackageValue"])))
    if sub:
        renew = "cancels at period end" if sub.get("cancelAtPeriodEnd") else "renews"
        print("Subscription     : {} {} via {} ({}); {} {}".format(
            sub.get("planId", "-"), (sub.get("interval") or "").lower(),
            sub.get("provider", "-"), sub.get("status", "-"),
            renew, (sub.get("endAt") or "")[:10]))
    print("\n(Read-only. To buy credits or change your plan, use the browser.)")
    return {"quota": me.get("quotaAmount"), "membership": mem.get("membershipId"),
            "free_credits": balance["free"], "paid_credits": balance["paid"]}


def suggest_prompt(session, media_id):
    """Reverse a prompt out of an image (PixAI's "Image to prompt"): GET
    /v2/tag/suggest-prompt/{mediaId} -> a list of suggested prompt strings (a Danbooru-
    style tag list + a natural-language description variant). FREE, read-only. Raises."""
    from moonglade.backup import _rest_get
    data = _rest_get(session, "/tag/suggest-prompt/" + str(media_id)) or {}
    return data.get("output") or []


def tag_search_gql(session, prefix, first=8):
    """Tag autocomplete for the prompt writer -- the site's "Tag Suggestions" dropdown.
    GraphQL `tags(q:$prefix, first:$n)` (field-probed 2026-07-04; node has name/
    category/id/weight, no usage count -- the site's counts are client-side). Returns
    a list of tag names. FREE, read-only. Raises on GraphQL error."""
    from moonglade.backup import gql_adhoc
    q = "query($k:String!,$n:Int){ tags(q:$k, first:$n){ edges{ node{ name } } } }"
    d = gql_adhoc(session, q, {"k": str(prefix), "n": int(first)}) or {}
    out = []
    for e in (d.get("tags") or {}).get("edges") or []:
        name = (e.get("node") or {}).get("name")
        if name:
            out.append(name)
    return out


def run_suggest_prompt(args):
    """--suggest-prompt <media_id|file>: print PixAI's suggested prompt(s) for an image
    (the site's "Image to prompt"). A local file is uploaded first (free); a catalog
    media_id is used directly. FREE and read-only -- spends no credits, no --confirm.

    PixAI's suggest-prompt endpoint is image-only and 500s on a video; the web gallery
    already hides the "Suggest prompt" button for a video row (`row.is_video != '1'`
    in moonglade/gallery.py). Mirror that same gate here (B18 residual) so the CLI refuses
    early with a clear message instead of surfacing that raw 500."""
    from moonglade.backup import _make_session, PixAIError, upload_media
    from moonglade.catalog import load_catalog
    src = (getattr(args, "suggest_prompt", "") or "").strip()
    if not src:
        raise PixAIError("--suggest-prompt needs a catalog media_id or a local image file.")
    is_local = _gen_params._is_local_source(src)
    # 3.22 S5: PixAI reads no prompt from an SVG (a GIF it does) -- by the catalog under --out,
    # then the extension, before any upload or request.
    _gen_params.refuse_unusable_source(_gen_params.catalog_source_format(
        getattr(args, "out", "") or _paths.DEFAULT_LIBRARY_DIR)(src), "prompt")
    if is_local:
        if Path(src).suffix.lower() in _VIDEO_EXTS:
            raise PixAIError(
                "--suggest-prompt only works on images, not video -- {} looks like a "
                "video file (PixAI's image-to-prompt endpoint doesn't support "
                "video).".format(src))
    else:
        out = getattr(args, "out", "") or _paths.DEFAULT_LIBRARY_DIR
        row = next((r for r in load_catalog(Path(out) / "catalog.db")
                    if r.get("media_id") == src), None)
        if row and row.get("is_video") == "1":
            raise PixAIError(
                "--suggest-prompt only works on images, not video -- media {} is a video "
                "in your catalog (PixAI's image-to-prompt endpoint doesn't support video; "
                "the web gallery hides this button for videos for the same reason).".format(src))
    session = _make_session(getattr(args, "token", None))
    if is_local:
        print("Uploading image (free):", src)
        media_id = upload_media(session, src)
    else:
        media_id = src
    outs = suggest_prompt(session, media_id)
    if not outs:
        print("No prompt suggestion returned for media", media_id)
        return {"suggestions": 0, "media_id": media_id}
    print("=== suggested prompt(s) for media {} ===".format(media_id))
    for i, o in enumerate(outs, 1):
        print("\n[{}] {}".format(i, o))
    return {"suggestions": len(outs), "media_id": media_id}


# --- Claimable rewards (daily credits, agent stamina) -- oRPC /v2/claim ----------
class ClaimsResult(list):
    """A claim list that also carries WHY it is empty, when it is empty for a bad reason.

    `list_claims` fails soft to an empty list on purpose and must keep doing so: the
    gallery's account panels call it on every render and must not 500 because PixAI
    hiccuped. But "the fetch failed" and "you have nothing to claim" are different facts,
    and `run_claims` printed "No claimable rewards found" for both -- so a transient 5xx
    left a REAL, ready daily-credit reward unclaimed while telling the user, in so many
    words, that there was nothing there (M05, 2026-07-27).

    A list subclass rather than a (rows, error) tuple because every existing call site --
    `for c in core.list_claims(session)` in two gallery routes, `if not rewards`, and
    `list_claims(...) == []` in the tests -- keeps working byte-for-byte unchanged, and a
    caller that substitutes a plain list (as the run_claims tests do) simply reports no
    error. Read `.error` via getattr with a default for exactly that reason."""

    def __init__(self, rows=(), error=""):
        super().__init__(rows)
        self.error = error


def list_claims(session):
    """Read the account's claimable rewards via GET /v2/claim (daily credits, agent
    stamina). Read-only; fails soft (returns an empty ClaimsResult). Each row: {id, amount,
    canClaim, claimedAt, nextClaimableTime}.

    The empty-on-failure return carries `.error` so a caller reporting to a human can say
    "the fetch failed" instead of "you have nothing to claim" -- see ClaimsResult."""
    from moonglade.backup import PixAIError, _rest_get
    try:
        data = _rest_get(session, "/claim")
    except PixAIError as e:
        return ClaimsResult((), str(e))
    return ClaimsResult(data if isinstance(data, list) else ())


def claim_reward(session, claim_id):
    """Claim a reward by id via POST /v2/claim/{id}. State-changing: grants the reward to
    YOUR OWN account (a routine daily entitlement, no money moves). Returns the updated
    claim record. Raises PixAIError on error."""
    from moonglade.backup import _check_read_only, _rest_post
    _check_read_only("claim a reward")  # still a real account mutation, even a beneficial one
    return _rest_post(session, "/claim/" + str(claim_id), {})


def _fmt_epoch_ms(ms):
    if not ms:
        return "-"
    try:
        return datetime.datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OverflowError, OSError):
        return str(ms)


def run_claims(args):
    """--claims: list your claimable rewards (read-only). --claim <id|all>: claim one or
    all ready rewards -- GATED behind --confirm (grants free credits/stamina to your own
    account). Never claims anything without --confirm."""
    from moonglade.backup import _make_session, PixAIError
    session = _make_session(getattr(args, "token", None))
    claim_id = (getattr(args, "claim", "") or "").strip()
    rewards = list_claims(session)
    # An empty list from a FAILED fetch is not the same fact as an empty list from an
    # account with nothing to claim, and this is the one place a human reads the answer.
    # Reporting both as "No claimable rewards found" is how a ready reward went unclaimed
    # after a transient 5xx, with nothing on screen to suggest retrying (M05, 2026-07-27).
    # getattr with a default: a caller/test may hand back a plain list, which carries none.
    err = getattr(rewards, "error", "") or ""
    if err:
        print("Could NOT read your claimable rewards: {}".format(err[:200]))
        print("This is a failed request, not an empty account -- a ready reward may still "
              "be waiting. Nothing was claimed; re-run --claims in a minute.")
        return {"rewards": 0, "error": err[:200]}
    if not rewards:
        print("No claimable rewards found (read-only; nothing changed).")
        return {"rewards": 0}

    if not claim_id:                                   # LIST (read-only)
        print("Claimable rewards (read-only):\n")
        for r in rewards:
            state = "READY now" if r.get("canClaim") else \
                    "next: " + _fmt_epoch_ms(r.get("nextClaimableTime"))
            print("  {:<24} {:>8}   {}".format(r.get("id"), r.get("amount"), state))
        ready = [r["id"] for r in rewards if r.get("canClaim")]
        if ready:
            print("\nReady: {}\nClaim with:  --claim <id>  (or --claim all)  --confirm".format(
                ", ".join(ready)))
        else:
            print("\nNothing ready to claim right now.")
        return {"rewards": len(rewards), "ready": len(ready)}

    # CLAIM (--claim <id|all>) -- guarded by --confirm
    targets = ([r for r in rewards if r.get("canClaim")] if claim_id == "all"
               else [r for r in rewards if r.get("id") == claim_id])
    if not targets:
        print("Nothing to claim for '{}' (unknown id, or not currently claimable).".format(claim_id))
        return {"claimed": 0}
    if not any(t.get("canClaim") for t in targets):
        print("'{}' is not claimable yet (next: {}).".format(
            claim_id, _fmt_epoch_ms(targets[0].get("nextClaimableTime"))))
        return {"claimed": 0}
    if not getattr(args, "confirm", False):
        print("Would claim (re-run with --confirm):")
        for r in targets:
            if r.get("canClaim"):
                print("  {} (+{})".format(r.get("id"), r.get("amount")))
        return {"claimed": 0, "preview": True}
    claimed = 0
    for r in targets:
        if not r.get("canClaim"):
            continue
        try:
            claim_reward(session, r["id"])
            print("Claimed {} (+{}).".format(r["id"], r.get("amount")))
            claimed += 1
        except PixAIError as e:
            print("Failed to claim {}: {}".format(r["id"], str(e)[:150]))
    if claimed:
        try:      # Claimant: the Void pays a small stipend
            from moonglade.telemetry import telem_bump
            telem_bump("claims", claimed)
        except Exception:
            pass
    return {"claimed": claimed}


def run_cards(args):
    """Print the account's free-generation cards (kaisuuken) via GET /v2/kaisuuken/summary.
    Read-only. Cards ARE auto-applied by this tool now: on --confirm we call
    /v2/kaisuuken/check for the matching ticket id and attach it (0 credits), exactly like
    the website. Pass --no-card to force paying credits, or --kaisuuken-id to force one."""
    from moonglade.backup import _make_session
    session = _make_session(getattr(args, "token", None))
    cards = _cards.list_kaisuukens(session)
    if not cards:
        print("No free cards found (read-only; nothing was spent).")
        return {"cards": 0}
    print("Free-generation cards (kaisuuken) -- model-locked. Auto-applied on --confirm; a\n"
          "matching card makes that generation cost 0 credits (use --no-card to opt out).\n"
          "Videos can need MORE THAN ONE ticket (a 15s clip needs 3): if you hold fewer than\n"
          "the job needs, no card is used and it costs the FULL credit price.\n")
    total = 0
    for c in cards:
        total += int(c.get("count") or 0)
        model = c["model_version_id"] or ("/".join(c["task_types"]) or "-")
        print("  {:>3}x  {:<22} {:<13} model={:<20} exp {}".format(
            c.get("count") or 0, c.get("name"), "[" + c["category"] + "]",
            model, str(c["expires"])[:10]))
    # "tickets", not "generations": a video ticket is one per 5 seconds, so 16 video tickets
    # is 5 fifteen-second clips, not 16 (the header above says so; this line used to contradict it).
    print("\n{} tickets total (one image or 5s of video each). The matching card is attached\n"
          "automatically when you generate on its model (nearest-expiry first):".format(total))
    print("  Tsubaki.2 card  -> --generate         (default model already matches)")
    print("  Edit Pro card   -> --edit-image       (default model already matches)")
    print("  Reference Pro   -> --edit-image --edit-model 1948514378441961474")
    return {"cards": len(cards), "total": total}


def run_card_history(args):
    """Print the account's benefit-card usage history (list_kaisuuken_logs) -- the paper
    trail /v2/kaisuuken/summary can't show: every past redemption/refund, the task it was
    attached to, and when. Read-only. Pass --card-history-all to page all the way back and
    print the lifetime card-type catalog instead (kaisuuken_type_catalog) -- slower, several
    requests, but answers "what card types have I ever held" once a type cycles out of
    current holdings."""
    from moonglade.backup import _make_session
    session = _make_session(getattr(args, "token", None))
    if getattr(args, "card_history_all", False):
        result = _cards.kaisuuken_type_catalog(session)
        templates = result["templates"]
        if not templates:
            print("No benefit-card history found (read-only; nothing was spent).")
            return {"templates": 0}
        print("Every benefit-card TYPE this account has ever used, across {} page(s){}:\n".format(
            result["pages_read"],
            " (stopped at the page cap -- there may be more)" if result["hit_page_cap"] else ""))
        for name, info in sorted(templates.items(), key=lambda kv: kv[1]["last_seen"], reverse=True):
            print("  {:<22} [{:<11}] consumed={:<3} refunded={:<3} last used {}".format(
                name, info["category"] or "-", info["consumed"], info["refunded"],
                str(info["last_seen"])[:10]))
        return {"templates": len(templates)}
    page = _cards.list_kaisuuken_logs(session, first=int(getattr(args, "card_history_count", 0) or 20))
    logs = page["logs"]
    if not logs:
        print("No benefit-card history found (read-only; nothing was spent).")
        return {"logs": 0}
    print("Recent benefit-card usage (most recent first):\n")
    for row in logs:
        print("  {:<22} {:<9} task {:<20} {}".format(
            row["template_name"], row["action"], row["task_id"],
            str(row["created_at"])[:19].replace("T", " ")))
    if page["has_next"]:
        print("\n...more exist -- pass --card-history-all to page through the full history.")
    return {"logs": len(logs)}


def run_coupons(args):
    """Print the account's "Credit Boost" coupons (list_extra_package_boosts) -- a reward
    type separate from benefit cards: a percentage bonus on an Extra Package (credit-pack)
    purchase, tied to promotional events. Defaults to what you currently HOLD (the primary
    ask -- on-hand inventory, not just a spend history); pass --coupons-history for the past
    (redeemed + expired) view instead. Read-only."""
    from moonglade.backup import _make_session
    session = _make_session(getattr(args, "token", None))
    history = getattr(args, "coupons_history", False)
    statuses = _cards.COUPON_STATUSES_HISTORY if history else _cards.COUPON_STATUSES_ON_HAND
    page = _cards.list_extra_package_boosts(session, statuses=statuses)
    coupons = page["coupons"]
    if not coupons:
        print("No {} coupons found (read-only; nothing was spent).".format(
            "past" if history else "currently-held"))
        return {"coupons": 0}
    print("Credit Boost coupons ({}):\n".format(
        "redeemed + expired history" if history else "currently held"))
    for c in coupons:
        print("  +{}%  {:<10} issued by {:<8} available {} -> {}".format(
            c["boost_percent"], c["status"], c["issued_by"],
            str(c["available_since"])[:10], str(c["available_until"])[:10]))
    if page["has_next"]:
        print("\n...more exist than shown here.")
    return {"coupons": len(coupons)}


def run_credit_log(args):
    """Print the account's full credit transaction ledger (list_credit_log) -- the real
    spend/purchase/gift history behind Membership & Credits -> Credit log, not just
    generation cost. Read-only. Pass --credit-log-before <cursor> to page further into the
    past."""
    from moonglade.backup import _make_session
    session = _make_session(getattr(args, "token", None))
    page = _cards.list_credit_log(session, last=int(getattr(args, "credit_log_count", 0) or 30),
                            before=getattr(args, "credit_log_before", "") or None)
    entries = page["entries"]
    if not entries:
        print("No credit log entries found (read-only; nothing was spent).")
        return {"entries": 0}
    print("Credit log (most recent first):\n")
    for e in entries:
        amount = e["amount"] or 0
        sign = "+" if amount >= 0 else ""
        print("  {}{:<10,} {:<20} {}".format(
            sign, amount, e["label"], str(e["created_at"])[:19].replace("T", " ")))
    if page["has_more"]:
        print("\n...more exist further back -- pass --credit-log-before {} to page.".format(
            page["next_cursor"]))
    return {"entries": len(entries)}
