"""Sessions R + Y (lane R): a published work's comment thread in Details, the owner's reply and
"Delete my reply" (R5b, R6c; drift 127-128). The two writes keep brief §0's rules: READ_ONLY
first, one attempt, a read-back that decides what is said, refusals in plain words.

No network: PixAI is the `pixai` fixture's FakePixAI, and the module's own DELETE
(`moonglade_inbox._rest_delete`) is blocked by conftest unless a test swaps in its own."""
import pytest

from moonglade import backup as core
from moonglade import inbox
from moonglade.gallery import CATALOG_FIELDS, create_app, save_catalog
from tests.conftest import login_test_client

ART = "1788621522581677948"
ME = "u-test"                         # FakePixAI's own user id
WORDS = "the moon behind her, chef's kiss"


def _msg(mid, author="u-kurone", name="kurone", reply_to=None, content=WORDS, topic=ART,
         flags=None, at="2026-10-03T10:00:00Z", reactions=None, sticker=None):
    return {"id": mid, "topicId": topic, "authorId": author,
            "author": {"id": author, "username": name, "displayName": name,
                       "avatarUrl": "https://x.test/a.png", "activeDecorationIds": []},
            "createdAt": at, "updatedAt": at, "type": "TEXT", "content": content,
            "contentFlags": flags or [], "replyToMessageId": reply_to,
            "reactions": reactions or [], "sticker": sticker}


def _thread(*msgs, total=None):
    return {"data": list(msgs), "page": 1, "pageSize": 50, "totalPage": 1,
            "totalCount": len(msgs) if total is None else total}


@pytest.fixture(autouse=True)
def _fresh():
    inbox.clear_caches()
    yield
    inbox.clear_caches()


# ---------------------------------------------------------------------------
# The thread (R5b): newest first, 50 a page, five minutes in memory
# ---------------------------------------------------------------------------

def test_the_thread_reads_fifty_a_page_on_the_works_topic(pixai):
    pixai.on("/messages/", _thread(_msg("1001"), _msg("1002", author=ME, name="Nel", reply_to="1001")))
    out = inbox.read_thread(pixai, ART)
    call = pixai.calls_for("/messages/")[0]
    assert call.params == {"topicId": ART, "page": 1, "pageSize": 50}
    assert [m["id"] for m in out["items"]] == ["1001", "1002"]
    assert out["items"][1]["you"] is True and out["items"][0]["you"] is False
    assert out["items"][1]["reply_to"] == "1001" and out["total"] == 2 and out["me"] == ME


def test_flagged_comments_are_marked_reactions_counted_stickers_kept(pixai):
    pixai.on("/messages/", _thread(
        _msg("1001", flags=["NSFW"]),
        _msg("1002", reactions=[{"emoji": "♥", "count": 2}, {"emoji": "✨", "count": 1}]),
        _msg("1003", content="", sticker={"id": "s1", "url": "https://x.test/s.png"})))
    items = {m["id"]: m for m in inbox.read_thread(pixai, ART)["items"]}
    assert items["1001"]["flagged"] is True
    assert items["1002"]["reactions"] == 3
    assert items["1003"]["sticker"] == "https://x.test/s.png"


def test_the_thread_is_cached_five_minutes_in_memory(pixai, monkeypatch):
    pixai.on("/messages/", _thread(_msg("1001")))
    now = [1000.0]
    monkeypatch.setattr(inbox.time, "time", lambda: now[0])
    inbox.read_thread(pixai, ART)
    inbox.read_thread(pixai, ART)
    assert len(pixai.calls_for("/messages/")) == 1
    now[0] += inbox.THREAD_TTL + 1
    inbox.read_thread(pixai, ART)
    assert len(pixai.calls_for("/messages/")) == 2


def test_an_expired_thread_is_swept_out_of_memory_on_the_next_insert(pixai, monkeypatch):
    """Review item 5: strangers' words must not outlive the five minutes, even for a work
    nobody opens again."""
    pixai.on("/messages/", lambda call: _thread(_msg("1001")) if call.params["topicId"] == ART
             else _thread(_msg("1002", content="another work's words")))
    now = [1000.0]
    monkeypatch.setattr(inbox.time, "time", lambda: now[0])
    inbox.read_thread(pixai, ART)
    now[0] += inbox.THREAD_TTL + 1
    inbox.read_thread(pixai, "1788621522581677000")
    assert (ART, 1) not in inbox._thread_cache
    assert WORDS not in repr(inbox._thread_cache)


def test_the_thread_cache_holds_a_bounded_number_of_pages_oldest_out(pixai, monkeypatch):
    pixai.on("/messages/", _thread(_msg("1001")))
    now = [1000.0]
    monkeypatch.setattr(inbox.time, "time", lambda: now[0])
    for i in range(inbox.THREAD_CACHE_MAX + 5):
        now[0] += 1
        inbox.read_thread(pixai, str(1788621522581677000 + i))
    assert len(inbox._thread_cache) == inbox.THREAD_CACHE_MAX
    assert (str(1788621522581677000), 1) not in inbox._thread_cache          # the oldest went first


@pytest.mark.parametrize("page,sent", [(10 ** 9, None), (0, 1), (-3, 1), ("abc", 1), (None, 1)])
def test_the_page_is_bounded(pixai, page, sent):
    pixai.on("/messages/", _thread(_msg("1001")))
    inbox.read_thread(pixai, ART, page=page)
    asked = pixai.calls_for("/messages/")[0].params["page"]
    assert asked == (inbox.THREAD_MAX_PAGE if sent is None else sent)


# ---------------------------------------------------------------------------
# The reply (R6c)
# ---------------------------------------------------------------------------

def _target_ok(pixai, mid="1001", topic=ART):
    pixai.on("/messages/" + mid, _msg(mid, topic=topic))


def _posts(pixai):
    return [c for c in pixai.calls if c.verb == "rest_post"]


def test_read_only_posts_nothing_and_asks_nothing(pixai, monkeypatch):
    monkeypatch.setattr(core, "READ_ONLY", True)
    out = inbox.post_reply(pixai, ART, "1001", "thanks!")
    assert out["state"] == "read_only" and "Read-only mode is on" in out["message"]
    assert pixai.calls == []


@pytest.mark.parametrize("text,words", [
    ("", "Write something first"),
    ("   ", "Write something first"),
    ("x" * 4096, "Too long by 1"),
    ("🌙" * 2048, "Too long by 1"),              # counted the way PixAI counts: UTF-16 units
])
def test_length_is_checked_before_anything_is_sent(pixai, text, words):
    out = inbox.post_reply(pixai, ART, "1001", text)
    assert out["state"] == "refused" and words in out["message"]
    assert pixai.calls == []


def test_exactly_the_limit_is_allowed(pixai):
    _target_ok(pixai)
    pixai.on("/messages/", {"id": "2001", **_msg("2001", author=ME, reply_to="1001", content="x" * 4095)})
    pixai.on("/messages/2001", _msg("2001", author=ME, reply_to="1001", content="x" * 4095))
    assert inbox.post_reply(pixai, ART, "1001", "x" * 4095)["state"] == "done"


def test_a_comment_on_another_work_is_never_replied_to(pixai):
    _target_ok(pixai, topic="999")
    out = inbox.post_reply(pixai, ART, "1001", "thanks!")
    assert out["state"] == "refused" and not _posts(pixai)


def test_a_reply_is_one_post_with_the_exact_text_then_a_read_back(pixai):
    _target_ok(pixai)
    pixai.on("/messages/", _msg("2001", author=ME, reply_to="1001", content="Moonwell v3 at 0.6."))
    pixai.on("/messages/2001", _msg("2001", author=ME, reply_to="1001", content="Moonwell v3 at 0.6."))
    out = inbox.post_reply(pixai, ART, "1001", "Moonwell v3 at 0.6.")
    assert out["state"] == "done" and out["message"] == "Posted · found in the thread."
    assert out["comment"]["id"] == "2001" and out["comment"]["you"] is True
    posts = _posts(pixai)
    assert len(posts) == 1 and posts[0].path == "/messages/"
    assert posts[0].body == {"topicId": ART, "topicRefType": "ARTWORK",
                             "content": "Moonwell v3 at 0.6.", "replyToMessageId": "1001"}
    assert pixai.calls[-1].path == "/messages/2001"           # the read-back comes last


def test_an_unclear_send_that_reads_back_nothing_is_never_success(pixai):
    _target_ok(pixai)

    def post_or_list(call):
        if call.verb == "rest_post":
            raise core.requests.ReadTimeout("no answer")
        return _thread(_msg("1001"))
    pixai.on("/messages/", post_or_list)
    out = inbox.post_reply(pixai, ART, "1001", "thanks!")
    assert out["state"] == "unclear"
    assert out["message"] == ("No clear answer from PixAI. Read the thread back: not found. "
                              "Check on PixAI before trying again.")
    assert len(_posts(pixai)) == 1                          # never a retry


def _before_and_after(pixai, before, after, post_error):
    """/messages/ answers `before` until the POST, `post_error` for the POST, `after` once
    it has been sent -- the thread as PixAI would show it either side of an unclear send."""
    sent = []

    def answer(call):
        if call.verb == "rest_post":
            sent.append(1)
            raise post_error
        if isinstance(before, Exception) and not sent:
            raise before
        return after if sent else before
    pixai.on("/messages/", answer)


def test_an_unclear_send_that_reads_back_the_reply_is_posted(pixai):
    _target_ok(pixai)
    _before_and_after(pixai, _thread(_msg("1001")),
                      _thread(_msg("2001", author=ME, reply_to="1001", content="thanks!"), _msg("1001")),
                      core.PixAIRestError("REST POST /messages/ -> 502", status=502))
    out = inbox.post_reply(pixai, ART, "1001", "thanks!")
    assert out["state"] == "done" and out["comment"]["id"] == "2001"
    assert len(_posts(pixai)) == 1


def test_an_old_identical_reply_never_reads_as_posted(pixai):
    """Review item 4: the same words to the same comment, posted earlier, were on the thread
    before this send. Finding them again after an unclear answer proves nothing."""
    _target_ok(pixai)
    old = _msg("1999", author=ME, reply_to="1001", content="thanks!", at="2026-10-01T10:00:00Z")
    _before_and_after(pixai, _thread(old, _msg("1001")), _thread(old, _msg("1001")),
                      core.requests.ReadTimeout("no answer"))
    out = inbox.post_reply(pixai, ART, "1001", "thanks!")
    assert out["state"] == "unclear" and len(_posts(pixai)) == 1


def test_without_a_snapshot_only_a_reply_made_after_the_send_counts(pixai):
    _target_ok(pixai)
    old = _msg("1999", author=ME, reply_to="1001", content="thanks!", at="2020-01-01T00:00:00Z")
    _before_and_after(pixai, core.PixAIRestError("REST GET -> 503", status=503),
                      _thread(old, _msg("1001")), core.requests.ReadTimeout("no answer"))
    assert inbox.post_reply(pixai, ART, "1001", "thanks!")["state"] == "unclear"


def test_without_a_snapshot_a_reply_made_after_the_send_is_posted(pixai):
    _target_ok(pixai)
    new = _msg("2001", author=ME, reply_to="1001", content="thanks!", at="2099-01-01T00:00:00Z")
    _before_and_after(pixai, core.PixAIRestError("REST GET -> 503", status=503),
                      _thread(new, _msg("1001")), core.requests.ReadTimeout("no answer"))
    out = inbox.post_reply(pixai, ART, "1001", "thanks!")
    assert out["state"] == "done" and out["comment"]["id"] == "2001"


@pytest.mark.parametrize("code,status,words", [
    ("EMAIL_NOT_VERIFIED", 403, "email verified"),
    ("USER_BLOCKED", 403, "blocked"),
    ("FORBIDDEN", 403, "isn't eligible"),
    ("SPAMMING_RESTRICTED", 403, "restricted"),
    ("TOO_MANY_REQUESTS", 429, "Nothing was posted. Try again in a few minutes."),
])
def test_refusals_are_plain_words_and_nothing_is_retried(pixai, code, status, words):
    _target_ok(pixai)
    pixai.fail("/messages/", core.PixAIRestError("REST POST -> %d" % status, status=status,
                                                 body={"code": code}))
    out = inbox.post_reply(pixai, ART, "1001", "thanks!")
    assert out["state"] == "refused" and words in out["message"]
    assert "Nothing was posted" in out["message"]
    assert len(_posts(pixai)) == 1


# ---------------------------------------------------------------------------
# Delete my reply: the same rules
# ---------------------------------------------------------------------------

class _Deletes:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, session, path, params=None, timeout=30):
        self.calls.append((path, params))
        if self.fail:
            raise self.fail
        return {"success": True}


def _gone_after_delete(pixai, dels, mid="2001", author=ME):
    def get(call):
        if dels.calls:
            raise core.PixAIRestError("REST GET -> 404", status=404, body={"code": "NOT_FOUND"})
        return _msg(mid, author=author, reply_to="1001")
    pixai.on("/messages/" + mid, get)


def test_deleting_my_reply_is_one_delete_then_a_read_back(pixai, monkeypatch):
    dels = _Deletes()
    monkeypatch.setattr(inbox, "_rest_delete", dels)
    _gone_after_delete(pixai, dels)
    out = inbox.delete_reply(pixai, ART, "2001")
    assert out["state"] == "done"
    assert dels.calls == [("/messages/2001", {"topicRefType": "ARTWORK"})]


def test_only_my_own_reply_can_be_deleted(pixai, monkeypatch):
    dels = _Deletes()
    monkeypatch.setattr(inbox, "_rest_delete", dels)
    pixai.on("/messages/1001", _msg("1001"))
    out = inbox.delete_reply(pixai, ART, "1001")
    assert out["state"] == "refused" and dels.calls == []


def test_a_delete_that_reads_back_still_there_is_never_success(pixai, monkeypatch):
    dels = _Deletes(fail=core.requests.ConnectionError("dropped"))
    monkeypatch.setattr(inbox, "_rest_delete", dels)
    pixai.on("/messages/2001", _msg("2001", author=ME, reply_to="1001"))
    out = inbox.delete_reply(pixai, ART, "2001")
    assert out["state"] == "unclear" and len(dels.calls) == 1


def test_read_only_deletes_nothing(pixai, monkeypatch):
    monkeypatch.setattr(core, "READ_ONLY", True)
    dels = _Deletes()
    monkeypatch.setattr(inbox, "_rest_delete", dels)
    assert inbox.delete_reply(pixai, ART, "2001")["state"] == "read_only"
    assert pixai.calls == [] and dels.calls == []


def test_the_delete_verb_has_no_retry_loop():
    import ast
    import inspect
    src = inspect.getsource(inbox)
    fn = next(n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == "_rest_delete")
    body = ast.get_source_segment(src, fn)
    assert body.count(".delete(") == 1
    assert "for " not in body and "while " not in body


# ---------------------------------------------------------------------------
# The routes: own works only, CSRF on the writes, nothing written to disk
# ---------------------------------------------------------------------------

def _app(tmp_path):
    rows = [{k: "" for k in CATALOG_FIELDS}]
    rows[0].update(media_id="m-local", artwork_id=ART, is_published="1", title="Moonwell Vigil")
    save_catalog(tmp_path / "catalog.db", rows)
    return create_app(tmp_path)


def test_the_thread_route_reads_only_works_in_the_library(tmp_path, pixai):
    pixai.on("/messages/", _thread(_msg("1001")))
    cli = login_test_client(_app(tmp_path))
    d = cli.get("/api/comments/" + ART).get_json()
    assert [m["id"] for m in d["items"]] == ["1001"] and d["csrf"]
    other = cli.get("/api/comments/2000000000000000001").get_json()
    assert other["error"] and len(pixai.calls_for("/messages/")) == 1


def test_a_thread_never_reaches_the_disk(tmp_path, pixai):
    pixai.on("/messages/", _thread(_msg("1001")))
    cli = login_test_client(_app(tmp_path))
    assert WORDS in cli.get("/api/comments/" + ART).get_data(as_text=True)
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert WORDS.encode() not in p.read_bytes(), p


@pytest.mark.parametrize("path", ["/reply", "/delete"])
def test_the_comment_writes_need_the_session_token(tmp_path, pixai, path):
    cli = login_test_client(_app(tmp_path))
    r = cli.post("/api/comments/" + ART + path, json={"csrf": "wrong", "reply_to": "1001",
                                                       "content": "hi", "message_id": "2001"})
    assert r.status_code == 400 and pixai.calls == []


def test_a_reply_on_a_work_outside_the_library_is_refused_before_pixai(tmp_path, pixai):
    pixai.on("/messages/", _thread())
    cli = login_test_client(_app(tmp_path))
    csrf = cli.get("/api/comments/" + ART).get_json()["csrf"]
    pixai.calls.clear()
    d = cli.post("/api/comments/2000000000000000001/reply",
                 json={"csrf": csrf, "reply_to": "1001", "content": "hi"}).get_json()
    assert d["state"] == "refused" and pixai.calls == []


def test_the_reply_route_answers_the_write(tmp_path, pixai):
    pixai.on("/messages/1001", _msg("1001"))
    pixai.on("/messages/2001", _msg("2001", author=ME, reply_to="1001", content="hi"))

    def thread_or_post(call):
        if call.verb == "rest_post":
            return _msg("2001", author=ME, reply_to="1001", content="hi")
        return _thread(_msg("1001"))
    pixai.on("/messages/", thread_or_post)
    cli = login_test_client(_app(tmp_path))
    csrf = cli.get("/api/comments/" + ART).get_json()["csrf"]
    d = cli.post("/api/comments/" + ART + "/reply",
                 json={"csrf": csrf, "reply_to": "1001", "content": "hi"}).get_json()
    assert d["state"] == "done" and d["comment"]["you"] is True
