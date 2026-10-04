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
    with _thread_lock:
        _thread_cache.clear()


# ---------------------------------------------------------------------------------------
# The writes' shared answers
# ---------------------------------------------------------------------------------------

def _answer(state, message, **extra):
    out = {"state": state, "message": message}
    out.update(extra)
    return out


def _read_only_answer(what):
    return _answer("read_only", "Read-only mode is on (READ_ONLY in config.json), so "
                   + what + ".")


def _code_of(exc):
    """PixAI's error code for a refused /v2 call ("" when there is none)."""
    code = getattr(exc, "code", "") or ""
    if not code:
        m = re.search(r'"code"\s*:\s*"([A-Z_]+)"', str(exc))
        code = m.group(1) if m else ""
    return str(code)


def _status_of(exc):
    try:
        return int(getattr(exc, "status", None) or 0)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------------------
# Write 1 of 4: mark read (R3b)
# ---------------------------------------------------------------------------------------

MARK_MAX = 200                   # PixAI's markRead takes 1 to 200 ids per call
NOT_MARKED = ("Couldn't confirm it was marked read. It stays unread here; nothing was "
              "sent twice.")


def _clean_ids(ids, cap):
    out, seen = [], set()
    for i in ids or []:
        if not isinstance(i, str):
            continue
        i = i.strip()
        if i and i not in seen and len(i) <= 64:
            seen.add(i)
            out.append(i)
    return out[:cap]


def _still_unread(session, ids):
    """The read-back for a mark-read: which of `ids` PixAI still calls unread, read off the
    newest 50 rows. None when the read failed or none of the ids are on that page -- the
    caller then has only the write's own answer to go on."""
    try:
        page = list_notifications(session, page=50)
    except Exception:                                        # noqa: BLE001
        return None
    rows = {i["id"]: i for i in page["items"] + page["tasks"]}
    seen = [i for i in ids if i in rows]
    if not seen:
        return None
    return [i for i in seen if rows[i]["unread"]]


def _mark_refusal(e):
    if _status_of(e) == 401:
        return "PixAI didn't accept this account's key, so nothing was marked read."
    if _status_of(e) == 429:
        return "PixAI said too many requests, so nothing was marked read. Try again in a minute."
    return "PixAI refused it, so nothing was marked read."


def mark_read(session, ids):
    """Opening a row or a work card marks the notifications it gathers as read on PixAI: ONE
    POST /v2/user/me/notifications/read {"ids": [...]} (PixAI takes 1-200 and is idempotent),
    then a read-back of the newest rows. Never called on panel open, scroll or push.

    READ_ONLY first (nothing is asked of PixAI at all); one attempt; "done" only when the
    read-back shows the rows read, or -- when they are too old to be on the read-back page --
    when PixAI's own answer was a clear success. An unclear answer that reads back unread stays
    unread, with the peach line."""
    try:
        core._check_read_only("mark notifications read on PixAI")
    except core.PixAIError:
        return _read_only_answer("this stays unread on PixAI")
    ids = _clean_ids(ids, MARK_MAX)
    if not ids:
        return _answer("refused", "Nothing to mark read.")
    answered = False
    try:
        r = core._rest_post(session, "/user/me/notifications/read", {"ids": ids})
        answered = isinstance(r, dict) and r.get("success") is True
    except Exception as e:                                   # noqa: BLE001
        if core.definite_refusal(e):
            return _answer("refused", _mark_refusal(e))
    still = _still_unread(session, ids)
    if still is None:
        return _answer("done", "Marked read on PixAI.") if answered else \
            _answer("unclear", NOT_MARKED)
    if still:
        return _answer("unclear", NOT_MARKED, still_unread=still)
    return _answer("done", "Marked read on PixAI.")


def mark_all_read(session, tab="all"):
    """⋯ Mark all read: ONE PUT /v2/user/me/notifications/read-marks {"types": [...]} --
    PixAI's watermark, "everything of these types up to now counts as read" -- for the types
    the tab shows that PixAI counts unread right now (never TASK, never a type PixAI's enum
    lacks), then a read-back of the count. Nothing unread means nothing is sent."""
    try:
        core._check_read_only("mark everything read on PixAI")
    except core.PixAIError:
        return _read_only_answer("nothing is marked read on PixAI")
    cats = TABS.get(str(tab or "all"), TABS["all"])
    try:
        counts = unread_counts(session)
    except Exception:                                        # noqa: BLE001
        return _answer("refused", "Couldn't read what's unread on PixAI, so nothing was sent.")
    types = sorted(t for t, n in counts.items()
                   if n > 0 and t in NOTIFICATION_TYPES and t not in TASK_TYPES
                   and category_of(t) in cats)
    if not types:
        return _answer("done", "Nothing unread.")
    answered = False
    try:
        r = core._rest_put(session, "/user/me/notifications/read-marks", {"types": types})
        answered = isinstance(r, dict) and r.get("success") is True
    except Exception as e:                                   # noqa: BLE001
        if core.definite_refusal(e):
            return _answer("refused", _mark_refusal(e))
    try:
        after = unread_counts(session)
    except Exception:                                        # noqa: BLE001
        return _answer("done", "Marked read on PixAI.") if answered else \
            _answer("unclear", "Couldn't confirm everything was marked read. Nothing was sent "
                               "twice; check on PixAI.")
    left = sum(after.get(t, 0) for t in types)
    if left:
        return _answer("unclear", "Couldn't confirm everything was marked read: {} still "
                                  "unread on PixAI. Nothing was sent twice.".format(left))
    return _answer("done", "Marked read on PixAI.")


# ---------------------------------------------------------------------------------------
# A work's comment thread (R5b): live, newest first, 50 a page, five minutes in memory
# ---------------------------------------------------------------------------------------

THREAD_TTL = 300.0
THREAD_PAGE = 50
_thread_cache = {}               # (artwork_id, page) -> (at, payload); this process only
_thread_lock = threading.Lock()
_ID = re.compile(r"^[0-9]{1,24}$")


def _checked_id(v, what="id"):
    v = str(v or "").strip()
    if not _ID.match(v):
        raise core.PixAIError("That isn't a PixAI {}".format(what))
    return v


def _reaction_count(reactions):
    n = 0
    for r in reactions or []:
        if isinstance(r, dict):
            try:
                n += max(1, int(r.get("count") or 1))
            except (TypeError, ValueError):
                n += 1
        else:
            n += 1
    return n


def _sticker_url(s):
    if isinstance(s, dict):
        return str(s.get("url") or s.get("imageUrl") or s.get("mediaUrl") or "")
    return str(s) if isinstance(s, str) and s.startswith("https://") else ""


def comment_of(raw, me):
    """One message, in the shape the thread draws. `you` marks the account's own."""
    raw = raw or {}
    a = raw.get("author") or {}
    author_id = str(raw.get("authorId") or a.get("id") or "")
    return {"id": str(raw.get("id") or ""),
            "topic_id": str(raw.get("topicId") or ""),
            "author": {"id": author_id,
                       "name": str(a.get("displayName") or a.get("username") or "someone"),
                       "avatar": str(a.get("avatarUrl") or "")},
            "you": bool(me) and author_id == str(me),
            "created_at": str(raw.get("createdAt") or ""),
            "content": str(raw.get("content") or ""),
            "reply_to": str(raw.get("replyToMessageId") or ""),
            "reactions": _reaction_count(raw.get("reactions")),
            "sticker": _sticker_url(raw.get("sticker")),
            "flagged": bool(raw.get("contentFlags"))}


def _drop_thread(artwork_id):
    with _thread_lock:
        for k in [k for k in _thread_cache if k[0] == artwork_id]:
            _thread_cache.pop(k, None)


def _fetch_thread(session, artwork_id, page):
    data = core._rest_get(session, "/messages/", params={
        "topicId": artwork_id, "page": int(page), "pageSize": THREAD_PAGE}) or {}
    rows = data.get("data")
    if not isinstance(rows, list):
        raise core.PixAIError("PixAI's comments answered without a list")
    return data, rows


def read_thread(session, artwork_id, page=1):
    """One page of a work's comments: GET /v2/messages/?topicId=<artwork id>&page&pageSize=50,
    newest first. Kept five minutes in THIS process's memory and nowhere else -- never the
    catalog, a file or a log. Raises on a failed read (the thread then says so; it is never
    drawn as "no comments")."""
    artwork_id = _checked_id(artwork_id, "work")
    page = max(1, int(page or 1))
    key = (artwork_id, page)
    with _thread_lock:
        hit = _thread_cache.get(key)
        if hit and time.time() - hit[0] < THREAD_TTL:
            return hit[1]
    me = _user_id(session)
    data, rows = _fetch_thread(session, artwork_id, page)
    try:
        total = int(data.get("totalCount"))
    except (TypeError, ValueError):
        total = None
    try:
        pages = int(data.get("totalPage") or 1)
    except (TypeError, ValueError):
        pages = 1
    out = {"items": [comment_of(r, me) for r in rows if isinstance(r, dict)],
           "page": page, "total": total, "has_more": page < pages, "me": me}
    with _thread_lock:
        _thread_cache[key] = (time.time(), out)
    return out


# ---------------------------------------------------------------------------------------
# Write 2 of 4: a reply (R6c)
# ---------------------------------------------------------------------------------------

REPLY_MAX = 4095                 # PixAI's limit, counted as JavaScript counts: UTF-16 units
REPLY_NOT_FOUND = ("No clear answer from PixAI. Read the thread back: not found. Check on "
                   "PixAI before trying again.")
_REPLY_REFUSALS = {
    "EMAIL_NOT_VERIFIED": "PixAI needs your email verified before you can reply. Nothing was "
                          "posted.",
    "USER_BLOCKED": "PixAI says one of you has blocked the other. Nothing was posted.",
    "FORBIDDEN": "PixAI says this account isn't eligible to comment. Nothing was posted.",
    "SPAMMING_RESTRICTED": "PixAI has restricted commenting on this account for now. Nothing "
                           "was posted.",
    "TOO_MANY_REQUESTS": "Nothing was posted. Try again in a few minutes.",
}


def utf16_length(text):
    """The length PixAI checks: JavaScript's String.length, which counts UTF-16 units."""
    return len(str(text or "").encode("utf-16-le")) // 2


def _reply_refusal(e):
    code = _code_of(e)
    if code in _REPLY_REFUSALS:
        return _REPLY_REFUSALS[code]
    status = _status_of(e)
    if status == 429:
        return _REPLY_REFUSALS["TOO_MANY_REQUESTS"]
    if status == 401:
        return "PixAI didn't accept this account's key. Nothing was posted."
    return "PixAI refused the reply. Nothing was posted."


def _read_message(session, message_id):
    """("found", raw) / ("gone", None) on a 404 / ("unread", None) when the read failed."""
    try:
        raw = core._rest_get(session, "/messages/" + message_id)
    except core.PixAIRestError as e:
        if _status_of(e) == 404:
            return "gone", None
        return "unread", None
    except Exception:                                        # noqa: BLE001
        return "unread", None
    return ("found", raw) if isinstance(raw, dict) and raw.get("id") else ("unread", None)


def _find_reply(session, artwork_id, posted_id, me, reply_to, text):
    """The reply's read-back: ("found", raw) / ("absent", None) / ("unread", None). With an id
    from PixAI's answer it reads that message; without one (an unclear send) it reads the
    thread's newest page fresh -- never the cache -- for the account's own reply to that
    comment with exactly that text."""
    if posted_id:
        state, raw = _read_message(session, posted_id)
        if state == "found" and str(raw.get("topicId") or "") == artwork_id:
            return "found", raw
        return ("absent", None) if state in ("found", "gone") else ("unread", None)
    try:
        _data, rows = _fetch_thread(session, artwork_id, 1)
    except Exception:                                        # noqa: BLE001
        return "unread", None
    for r in rows:
        if (isinstance(r, dict) and str(r.get("authorId") or "") == str(me)
                and str(r.get("replyToMessageId") or "") == reply_to
                and str(r.get("content") or "") == text):
            return "found", r
    return "absent", None


def post_reply(session, artwork_id, reply_to, content):
    """Post the owner's reply to a comment on one of their own works: ONE
    POST /v2/messages/ {topicId, topicRefType: "ARTWORK", content, replyToMessageId}, then a
    read-back that decides what is said.

    Order: READ_ONLY (nothing is asked of PixAI) -> the text's own checks (empty, over 4,095)
    -> the comment being answered must be on this work -> the one POST -> the read-back. The
    caller (the route) has already checked the work is in the owner's library. "done" only
    when the read-back finds the reply; an unclear send that reads back nothing is the peach
    "not found, check on PixAI", and the client keeps Send off until the text changes."""
    try:
        core._check_read_only("post a reply on PixAI")
    except core.PixAIError:
        return _read_only_answer("replies are off")
    text = str(content or "").strip()
    if not text:
        return _answer("refused", "Write something first. Nothing was posted.")
    over = utf16_length(text) - REPLY_MAX
    if over > 0:
        return _answer("refused", "Too long by {:,}. Nothing was posted.".format(over))
    try:
        artwork_id = _checked_id(artwork_id, "work")
        reply_to = _checked_id(reply_to, "comment")
    except core.PixAIError as e:
        return _answer("refused", str(e) + ". Nothing was posted.")
    state, target = _read_message(session, reply_to)
    if state == "gone":
        return _answer("refused", "That comment is gone from PixAI. Nothing was posted.")
    if state != "found":
        return _answer("refused", "Couldn't check the comment you're replying to, so nothing "
                                  "was posted.")
    if str(target.get("topicId") or "") != artwork_id:
        return _answer("refused", "That comment isn't on this work. Nothing was posted.")
    me = _user_id(session)
    body = {"topicId": artwork_id, "topicRefType": "ARTWORK", "content": text,
            "replyToMessageId": reply_to}
    posted_id = ""
    try:
        r = core._rest_post(session, "/messages/", body)
        posted_id = str((r or {}).get("id") or "") if isinstance(r, dict) else ""
    except Exception as e:                                   # noqa: BLE001
        if core.definite_refusal(e):
            return _answer("refused", _reply_refusal(e))
    _drop_thread(artwork_id)
    found, raw = _find_reply(session, artwork_id, posted_id, me, reply_to, text)
    if found == "found":
        return _answer("done", "Posted · found in the thread.", comment=comment_of(raw, me))
    if found == "unread" and posted_id:
        return _answer("unclear", "PixAI said it posted, but reading the thread back failed. "
                                  "Check on PixAI before trying again.")
    return _answer("unclear", REPLY_NOT_FOUND)


# ---------------------------------------------------------------------------------------
# Write 3 of 4: delete the owner's own reply (there is no edit on PixAI)
# ---------------------------------------------------------------------------------------

def _rest_delete(session, path, params=None, timeout=30):
    """DELETE a /v2 route. Single attempt (no loop; pinned by
    tests/test_inbox_comments.py); raises like the transport's other verbs on a non-2xx.
    Blocked in tests by conftest."""
    client = core._client_of(session)
    r = client.session.delete(core.REST_API_BASE + path, params=params, timeout=timeout)
    if not r.ok:
        raise core._rest_error("DELETE", path, r)
    try:
        return r.json()
    except ValueError:
        return {}


def delete_reply(session, artwork_id, message_id):
    """"Delete my reply": ONE DELETE /v2/messages/{id}?topicRefType=ARTWORK, then a read-back of
    that message. READ_ONLY first; only the account's own reply on this work; "done" only when
    the read-back finds it gone (a 404). It can't be undone -- the client asks first."""
    try:
        core._check_read_only("delete a reply on PixAI")
    except core.PixAIError:
        return _read_only_answer("nothing was deleted")
    try:
        artwork_id = _checked_id(artwork_id, "work")
        message_id = _checked_id(message_id, "reply")
    except core.PixAIError as e:
        return _answer("refused", str(e) + ". Nothing was deleted.")
    state, raw = _read_message(session, message_id)
    if state == "gone":
        _drop_thread(artwork_id)
        return _answer("done", "Deleted from PixAI.")
    if state != "found":
        return _answer("refused", "Couldn't check the reply, so nothing was deleted.")
    me = _user_id(session)
    if str(raw.get("authorId") or "") != me or str(raw.get("topicId") or "") != artwork_id:
        return _answer("refused", "Only your own replies on this work can be deleted here. "
                                  "Nothing was deleted.")
    try:
        _rest_delete(session, "/messages/" + message_id, params={"topicRefType": "ARTWORK"})
    except Exception as e:                                   # noqa: BLE001
        if core.definite_refusal(e):
            return _answer("refused", "PixAI refused it. Nothing was deleted.")
    _drop_thread(artwork_id)
    after, _raw = _read_message(session, message_id)
    if after == "gone":
        return _answer("done", "Deleted from PixAI.")
    if after == "found":
        return _answer("unclear", "It's still on PixAI: it wasn't deleted. Check on PixAI.")
    return _answer("unclear", "No clear answer from PixAI. Check on PixAI before trying again.")
