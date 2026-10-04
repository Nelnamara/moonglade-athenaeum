"""moonglade_inbox.py -- Sessions R + Y (2026-10-03): PixAI's inbox, a published work's
comment thread and the owner's replies to it, PixAI's gifts, the free cards about to expire
and the event PixAI is running now.

The design is the committed Design Handoff, `Inbox and Event Handoff.dc.html` (picks R1a ·
R2c · R3b · R4b · R5b · R6c · R9c · Y1c · Y2a · Y3a · RYPc), with its notes
(design/notes/inbox-event/NOTES.md) and drift items 123-133. The contract facts come from the
2026-10-02 probe (PROBE_2026-10-02_bridge-live-inbox-studio.md, task 3) and the site's own
contract, read statically. Nothing here was learned by calling PixAI from a test.

THE CREDENTIAL. Every read and every write in this module rides `pixai_session()`: the app's own
API key, the session the probe proved can read the inbox and post, reply to and delete
comments. Change it there and every caller moves with it. The one exception is the banner
list, which PixAI answers with a 404 when ANY key is attached, so `_public_get` sends no
credential at all.

STRANGERS' WORDS ARE NEVER ARCHIVED. A comment, a reply or an inbox item's text is another
person's words. It is read live, kept for five minutes in this process's memory (the thread
cache below) and handed to the browser. It is never written to the catalog, to a file or to a
log line, and no error message here carries one.

THE FOUR WRITES -- mark read (`mark_read`, `mark_all_read`), a reply (`post_reply`), deleting
the owner's own reply (`delete_reply`) and claiming a gift (`claim_gift`). Each is its own
function and each keeps the same four rules (brief §0, RY_COMMON rule 9):
  1. `core._check_read_only(...)` is the first thing it does, before any network call;
  2. ONE attempt: `core._rest_post` / `core._rest_put` / this module's `_rest_delete` have no
     retry loop (tests/test_spend_no_retry.py pins all three);
  3. a READ-BACK decides what the user is told -- "done" only when the read-back shows it, and
     an unclear answer (a timeout, a dropped connection, a 5xx) is never reported as success;
  4. nothing calls one when a panel opens, a list scrolls or a push arrives: only a press.
Each returns a plain dict, {"state": ..., "message": ...}, where state is one of
  "done"      -- the read-back shows it happened;
  "refused"   -- PixAI said no (a 4xx), in plain words; nothing changed;
  "unclear"   -- no clear answer, and the read-back could not show it happened;
  "read_only" -- READ_ONLY is on, so nothing was sent.
"""
import datetime as _dt
import re
import threading
import time
from urllib.parse import urlparse

import requests

import moonglade_backup as core

# ---------------------------------------------------------------------------------------
# The credential
# ---------------------------------------------------------------------------------------


def pixai_session():
    """The ONE authenticated session the inbox, the comments, the replies, mark-read and the
    gift claim ride: the app's own API key (PROBE_2026-10-02 task 3 proved it reads the inbox
    and posts, replies to and deletes comments). If PixAI ever needs another credential for any
    of these, this is the one line that changes."""
    return core._make_session(None)


def _user_id(session):
    """The account's own PixAI user id: who "you" is in a thread."""
    uid = str(getattr(core._client_of(session), "user_id", "") or "")
    if not uid:
        uid = str(core.resolve_user_id(session) or "")
    return uid


_me_cache = {"name": None, "at": 0.0}


def display_name(session):
    """The account's public display name -- what a reply posts under, named in the question
    before Send. Cached for the process; "" when PixAI would not say (the question then says
    "your PixAI name" rather than guessing)."""
    if _me_cache["name"] is not None and time.time() - _me_cache["at"] < 3600:
        return _me_cache["name"]
    try:
        d = core.gql_adhoc(session, "query{ me{ id displayName } }") or {}
        name = str(((d.get("me") or {}).get("displayName")) or "")
    except Exception:                                        # noqa: BLE001 -- fails soft
        name = ""
    if name:
        _me_cache.update(name=name, at=time.time())
    return name


# ---------------------------------------------------------------------------------------
# The inbox (R1a, R2c): reads
# ---------------------------------------------------------------------------------------

PAGE = 20                       # the panel's first read: last=20 (first=N returns the OLDEST)

# Every type PixAI's markReadByTypes accepts (the contract's notification-type enum). Mark all
# read only ever sends types from this list, so a type PixAI does not know can't 400 the call.
NOTIFICATION_TYPES = (
    "LIKE", "FOLLOW", "COMMENT", "COMMENT_REPLY", "MESSAGE_REACTION", "REPLY_THEME",
    "ITEM_LIKE", "NEW_SUPPORTER", "WORLD_NEW_CHARACTER", "MODEL_CLAIM",
    "MODEL_CLAIMED_BY_OTHERS", "MODEL_COVER_NSFW", "APPEAL_ACCEPTED", "APPEAL_REJECTED",
    "USER_AVATAR_NSFW", "USER_COVER_NSFW", "DAILY_RANKING", "WEEKLY_RANKING",
    "MONTHLY_RANKING", "NEWBIES_RANKING", "CONTEST_REWARD", "CONTEST_STARTING_SOON",
    "CONTEST_ENDING_SOON", "CONTEST_RESULT_PUBLISHED", "CONTEST_WON",
    "CONTEST_REWARD_RECEIVED", "CONTEST_APPROVED", "CONTEST_REJECTED", "CONTEST_CANCELLED",
    "CONTEST_AUTOSELECT_DONE", "CONTEST_CREDIT_REFUNDED", "CONTEST_FOLLOWING_HOSTED",
    "CONTEST_ONGOING_DAILY", "TRAINING_TASK_COMPLETED", "PRIVILEGE", "PAYMENT_FAILED", "NEWS",
    "NEWS_DRAFT", "DAILY_CLAIM", "GENERATION_TASK_COMPLETED", "MEMBERSHIP_GIFTED",
    "MEMBERSHIP_EXPIRED", "MEMBERSHIP_RENEWED", "MEMBERSHIP_RENEWAL_FAILED",
    "TACK_NOMINATION_APPROVED", "TACK_NOMINATION_MERGED", "SYSTEM")

# TASK is never listed: the app's own Activity already tells a job (R2c). These are the
# finished-job types; they never reach the panel or the badge.
TASK_TYPES = frozenset(("GENERATION_TASK_COMPLETED", "TRAINING_TASK_COMPLETED"))

_CATEGORY = {"LIKE": "like", "ITEM_LIKE": "like",
             "COMMENT": "comment", "COMMENT_REPLY": "comment", "MESSAGE_REACTION": "comment",
             "REPLY_THEME": "comment",
             "FOLLOW": "follow", "NEW_SUPPORTER": "follow"}

# The kind tabs (R1a): which categories each one shows. "gifts" is the official-DM thread,
# not a notification category; "pixai" holds CONTEST and NEWS (and PixAI's other notices).
TABS = {"all": ("like", "comment", "follow", "contest", "news"),
        "comments": ("comment",), "likes": ("like",), "follows": ("follow",),
        "pixai": ("contest", "news")}


def category_of(ntype):
    """like · comment · follow · contest · news · task, for one notification type."""
    t = str(ntype or "").upper()
    if t in TASK_TYPES:
        return "task"
    if t in _CATEGORY:
        return _CATEGORY[t]
    if t.startswith("CONTEST"):
        return "contest"
    return "news"


def _person(u):
    u = u or {}
    return {"id": str(u.get("id") or ""),
            "name": str(u.get("displayName") or u.get("username") or "someone")}


def _media_thumb(media):
    """A small picture URL from a PixAI media object, or ""."""
    m = media or {}
    if not isinstance(m, dict):
        return ""
    if m.get("thumbnailUrl"):
        return str(m["thumbnailUrl"])
    urls = m.get("urls") or []
    by = {str(u.get("variant") or ""): str(u.get("url") or "") for u in urls if isinstance(u, dict)}
    return by.get("THUMBNAIL") or by.get("STILL_THUMBNAIL") or by.get("PUBLIC") or ""


def _localized(v, lang="en"):
    """A per-language PixAI value ({"en": ..., "ja": ...}) or a plain string, as a string."""
    if isinstance(v, dict):
        return str(v.get(lang) or v.get("en") or next((x for x in v.values() if x), "") or "")
    return str(v or "")


def normalize_notification(raw):
    """One inbox item, in the shape the panel draws. Carries the item's own words only as far
    as the browser: nothing here is stored."""
    raw = raw or {}
    ntype = str(raw.get("type") or "")
    art = raw.get("artwork") if isinstance(raw.get("artwork"), dict) else None
    contest = raw.get("contest") if isinstance(raw.get("contest"), dict) else None
    out = {
        "id": str(raw.get("id") or ""),
        "type": ntype,
        "kind": str(raw.get("kind") or ""),
        "cat": category_of(ntype),
        "unread": bool(raw.get("unread")),
        "created_at": str(raw.get("createdAt") or ""),
        "users": [_person(u) for u in (raw.get("relatedUsers") or []) if isinstance(u, dict)],
        "content": str(raw.get("content") or "")[:600],
        "emoji": str(raw.get("emoji") or ""),
        "ref_id": str(raw.get("refId") or ""),
        "ref_title": _localized(raw.get("refTitle")),
        "link": str(raw.get("link") or ""),
        "artwork": None,
        "contest": None,
    }
    if art and art.get("id"):
        out["artwork"] = {"id": str(art.get("id")), "title": _localized(art.get("title")),
                          "thumb": _media_thumb(raw.get("refMedia")) or _media_thumb(art.get("media")),
                          "media_id": ""}
    if contest:
        out["contest"] = {"slug": str(contest.get("slug") or raw.get("refSlug") or ""),
                          "title": _localized(contest.get("title"))}
    elif out["cat"] == "contest" and raw.get("refSlug"):
        out["contest"] = {"slug": str(raw.get("refSlug")), "title": out["ref_title"]}
    if not out["link"] and isinstance(raw.get("locales"), dict):
        loc = raw["locales"].get("en") or next(iter(raw["locales"].values()), None)
        if isinstance(loc, dict):
            out["link"] = str(loc.get("link") or loc.get("url") or "")
            if not out["content"]:
                out["content"] = str(loc.get("title") or loc.get("content") or "")[:600]
    return out


def _sort_key(item):
    return item.get("created_at") or ""


def list_notifications(session, before=None, page=PAGE):
    """One page of the inbox, NEWEST first: `last=N` (the probe's paging trap -- `first=N`
    answers the account's oldest rows from 2023), then `before=<cursor>` for older pages.

    Returns {items, tasks, cursor, has_more}. `items` excludes TASK; `tasks` carries those
    rows separately for the Activity cross-check (R2c). Raises on a failed read -- the route
    turns that into its {error} answer, so an unreadable inbox is never shown as empty."""
    params = {"last": int(page)}
    if before:
        params["before"] = str(before)
    data = core._rest_get(session, "/user/me/notifications/", params=params) or {}
    rows = data.get("data")
    if not isinstance(rows, list):
        raise core.PixAIError("PixAI's inbox answered without a list")
    page_info = data.get("pageInfo") or {}
    items, tasks = [], []
    for r in rows:
        if not isinstance(r, dict):
            continue
        n = normalize_notification(r)
        (tasks if n["cat"] == "task" else items).append(n)
    items.sort(key=_sort_key, reverse=True)
    return {"items": items, "tasks": tasks,
            "cursor": page_info.get("startCursor") or None,
            "has_more": bool(page_info.get("hasPreviousPage"))}


def unread_counts(session):
    """{type: count} from PixAI's unread counts. Raises on a failed read."""
    data = core._rest_get(session, "/user/me/notifications/unread-counts")
    if not isinstance(data, list):
        raise core.PixAIError("PixAI's unread counts answered without a list")
    out = {}
    for r in data:
        if isinstance(r, dict) and r.get("type"):
            try:
                out[str(r["type"])] = out.get(str(r["type"]), 0) + max(0, int(r.get("count") or 0))
            except (TypeError, ValueError):
                continue
    return out


def gift_summary(session):
    """{unread_messages, unclaimed_rewards} from PixAI's official-DM summary. Raises on a
    failed read."""
    d = core._rest_get(session, "/user/me/official-dm/unread-summary") or {}
    if not isinstance(d, dict):
        raise core.PixAIError("PixAI's gift summary answered without an object")

    def n(k):
        try:
            return max(0, int(d.get(k) or 0))
        except (TypeError, ValueError):
            return 0
    return {"unread_messages": n("unreadMessages"), "unclaimed_rewards": n("unclaimedRewards"),
            "has_messages": bool(d.get("hasMessages"))}


def unread_total(session):
    """The gift box's badge (R1a): PixAI's unread count over every LISTED type (TASK is never
    listed, so it never counts) plus the PENDING gifts. Returns {total, unread, gifts}; any
    part PixAI would not answer is None, and the total is None only when neither answered --
    "we could not ask" is never drawn as zero."""
    try:
        counts = unread_counts(session)
        unread = sum(c for t, c in counts.items() if t not in TASK_TYPES)
    except Exception:                                        # noqa: BLE001
        unread = None
    try:
        gifts = gift_summary(session)["unclaimed_rewards"]
    except Exception:                                        # noqa: BLE001
        gifts = None
    total = None if unread is None and gifts is None else (unread or 0) + (gifts or 0)
    return {"total": total, "unread": unread, "gifts": gifts}


# ---------------------------------------------------------------------------------------
# The current event (Y3a): GET /v2/banners/ -- public, NO credential, cached 1 h
# ---------------------------------------------------------------------------------------

EVENT_TTL = 3600.0
_events_cache = {"at": 0.0, "items": None}
_events_lock = threading.Lock()
_EVENT_PATH = re.compile(r"^/(?:[a-z]{2}(?:-[A-Za-z]{2,4})?/)?event/[^/?#]", re.I)


def _public_get(path, timeout=15):
    """GET a public /v2 route with NO credential attached. The banner list answers 404 when the
    API key rides along (PROBE_2026-10-02_site), so this is deliberately not the session: a
    plain requests.get, HTTPS verification on, one attempt. Blocked in tests by conftest."""
    r = requests.get(core.REST_API_BASE + path, timeout=timeout,
                     headers={"Accept": "application/json"})
    if not r.ok:
        raise core._rest_error("GET", path, r)
    return r.json()


def _absolute(link):
    link = str(link or "").strip()
    if not link:
        return ""
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        return "https://pixai.art" + link
    return link


def event_from_banner(b, lang="en", now=None):
    """A banner as an event card, or None when it is not an event: its link must be under
    /event/ (or /<lang>/event/) on pixai.art, and an endTime in the past drops it. Promos --
    a model page, YouTube, a press release -- are not events."""
    if not isinstance(b, dict):
        return None
    link = _absolute(_localized(b.get("link"), lang))
    u = urlparse(link)
    if u.scheme != "https" or not (u.hostname or "").endswith("pixai.art"):
        return None
    if not _EVENT_PATH.match(u.path or ""):
        return None
    end = str(b.get("endTime") or "")
    if end:
        now = now if now is not None else _dt.datetime.now(_dt.timezone.utc)
        try:
            when = _dt.datetime.fromisoformat(end.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=_dt.timezone.utc)
            if when <= now:
                return None
        except ValueError:
            pass
    label = str(b.get("label") or "")
    title = _localized(b.get("title"), lang)
    if not title:
        words = re.sub(r"[-_.]+", " ", label).strip()
        title = words[:1].upper() + words[1:] if words else "Event"
    image = _absolute(_localized(b.get("imageUrl"), lang))
    return {"label": label, "title": title, "link": link,
            "image": image if image.startswith("https://") else "", "end": end}


def current_events(lang="en", now=None):
    """PixAI's live events, for ON PIXAI NOW. Read once an hour at most; a failed read is NOT
    cached (the next panel open asks again) and answers [] -- with nothing live the section is
    simply absent."""
    with _events_lock:
        if _events_cache["items"] is not None and time.time() - _events_cache["at"] < EVENT_TTL:
            raw = _events_cache["items"]
        else:
            raw = None
    if raw is None:
        try:
            data = _public_get("/banners/") or {}
            raw = data.get("items") if isinstance(data, dict) else data
            if not isinstance(raw, list):
                raw = []
        except Exception:                                    # noqa: BLE001 -- fails soft
            return []
        with _events_lock:
            _events_cache.update(at=time.time(), items=raw)
    out = []
    for b in raw:
        ev = event_from_banner(b, lang=lang, now=now)
        if ev:
            out.append(ev)
    return out


def clear_caches():
    """Every module-level memo, for tests and a fresh account."""
    with _events_lock:
        _events_cache.update(at=0.0, items=None)
    _me_cache.update(name=None, at=0.0)
