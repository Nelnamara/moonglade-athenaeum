"""Sessions R + Y (lane R, 2026-10-03): PixAI's inbox behind the gift box, its unread count,
and the current event. The design is `Inbox and Event Handoff.dc.html`
(moonglade-internal/design/handoff-2026-09-04/), notes/inbox-event/NOTES.md, drift 123-133.

No network: PixAI is the `pixai` fixture's FakePixAI (it answers only what a test registered),
and the public banner read (`moonglade_inbox._public_get`) is blocked by conftest unless a test
swaps in its own answer."""
import pytest

import moonglade_backup as core
import moonglade_inbox as inbox
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog
from tests.conftest import login_test_client

ART = "1788621522581677948"
ART2 = "1788621522581677999"
STRANGER_WORDS = "the hair light is unreal, which LoRA?"


def _like(nid, art=ART, unread=True, at="2026-10-03T10:00:00Z", users=("Aster",)):
    return {"id": nid, "type": "LIKE", "kind": "ACTOR_ARTWORK", "unread": unread,
            "createdAt": at, "updatedAt": at,
            "relatedUsers": [{"id": "u" + n, "displayName": n, "activeDecorationIds": []}
                             for n in users],
            "artwork": {"id": art, "title": "Moonwell Vigil"}, "refType": "ARTWORK",
            "refId": art, "refMedia": {"id": "m1", "thumbnailUrl": "https://x.test/t.jpg"}}


def _comment(nid, art=ART, unread=True, at="2026-10-03T11:00:00Z", text=STRANGER_WORDS):
    d = _like(nid, art=art, unread=unread, at=at, users=("kurone",))
    d.update(type="COMMENT", content=text)
    return d


def _follow(nid, at="2026-10-02T09:00:00Z", name="Ilya"):
    return {"id": nid, "type": "FOLLOW", "kind": "ACTOR", "unread": True, "createdAt": at,
            "updatedAt": at, "relatedUsers": [{"id": "u" + name, "displayName": name,
                                               "activeDecorationIds": []}],
            "relatedUserIds": ["u" + name]}


def _task(nid, task_id="2062832974899841293", at="2026-10-03T09:00:00Z"):
    return {"id": nid, "type": "GENERATION_TASK_COMPLETED", "kind": "REF_ITEM", "unread": True,
            "createdAt": at, "updatedAt": at, "refType": "TASK", "refId": task_id,
            "refTitle": "a quiet library", "relatedUsers": []}


def _page(rows, start="c-old", more=True):
    return {"data": rows, "pageInfo": {"startCursor": start, "endCursor": "c-new",
                                       "hasNextPage": False, "hasPreviousPage": more}}


@pytest.fixture(autouse=True)
def _fresh():
    inbox.clear_caches()
    yield
    inbox.clear_caches()


# ---------------------------------------------------------------------------
# The read: newest first, TASK never listed
# ---------------------------------------------------------------------------

def test_the_first_page_asks_for_the_newest_rows_never_the_oldest(pixai):
    """The probe's paging trap: first=N answers the 2023 rows. The panel reads last=20."""
    pixai.on("/user/me/notifications/", _page([_like("n1"), _comment("n2")]))
    out = inbox.list_notifications(pixai)
    call = pixai.calls_for("/user/me/notifications/")[0]
    assert call.params == {"last": 20}
    assert [i["id"] for i in out["items"]] == ["n2", "n1"]          # newest first
    assert out["cursor"] == "c-old" and out["has_more"] is True


def test_an_older_page_pages_backward_from_the_cursor(pixai):
    pixai.on("/user/me/notifications/", _page([], more=False))
    out = inbox.list_notifications(pixai, before="c-old")
    assert pixai.calls_for("/user/me/notifications/")[0].params == {"last": 20, "before": "c-old"}
    assert out["has_more"] is False


def test_task_rows_never_reach_the_list(pixai):
    pixai.on("/user/me/notifications/", _page([_task("n9"), _like("n1")]))
    out = inbox.list_notifications(pixai)
    assert [i["id"] for i in out["items"]] == ["n1"]
    assert [t["id"] for t in out["tasks"]] == ["n9"]


def test_an_unreadable_inbox_raises_rather_than_reading_empty(pixai):
    pixai.fail("/user/me/notifications/", core.PixAIError("REST GET -> 500"))
    with pytest.raises(core.PixAIError):
        inbox.list_notifications(pixai)


@pytest.mark.parametrize("ntype,cat", [
    ("LIKE", "like"), ("COMMENT", "comment"), ("COMMENT_REPLY", "comment"),
    ("FOLLOW", "follow"), ("CONTEST_RESULT_PUBLISHED", "contest"), ("NEWS", "news"),
    ("MEMBERSHIP_RENEWED", "news"), ("GENERATION_TASK_COMPLETED", "task"),
    ("TRAINING_TASK_COMPLETED", "task")])
def test_every_kind_has_a_category(ntype, cat):
    assert inbox.category_of(ntype) == cat


def test_a_comment_item_carries_its_artwork_and_words():
    n = inbox.normalize_notification(_comment("n2"))
    assert n["cat"] == "comment" and n["unread"] is True
    assert n["artwork"]["id"] == ART and n["artwork"]["title"] == "Moonwell Vigil"
    assert n["artwork"]["thumb"] == "https://x.test/t.jpg"
    assert n["users"] == [{"id": "ukurone", "name": "kurone"}]
    assert n["content"] == STRANGER_WORDS


# ---------------------------------------------------------------------------
# The badge: PixAI's unread count plus pending gifts; TASK never counts
# ---------------------------------------------------------------------------

def test_the_badge_is_unread_plus_pending_gifts_without_task(pixai):
    pixai.on("/user/me/notifications/unread-counts",
             [{"type": "LIKE", "count": 3}, {"type": "COMMENT", "count": 2},
              {"type": "GENERATION_TASK_COMPLETED", "count": 7}])
    pixai.on("/user/me/official-dm/unread-summary",
             {"unreadMessages": 1, "unclaimedRewards": 1, "hasMessages": True,
              "terminated": False})
    assert inbox.unread_total(pixai) == {"total": 6, "unread": 5, "gifts": 1}


def test_a_count_pixai_would_not_give_is_none_never_zero(pixai):
    pixai.fail("/user/me/notifications/unread-counts", core.PixAIError("REST GET -> 503"))
    pixai.fail("/user/me/official-dm/unread-summary", core.PixAIError("REST GET -> 503"))
    assert inbox.unread_total(pixai) == {"total": None, "unread": None, "gifts": None}


# ---------------------------------------------------------------------------
# The current event: public banners, events only, no credential, cached an hour
# ---------------------------------------------------------------------------

BANNERS = {"items": [
    {"label": "zeta", "link": {"en": "/en/event/zeta"}, "imageUrl": {"en": "https://cdn.test/z.webp"},
     "mobileImageUrl": None, "title": None, "blank": False, "endTime": None},
    {"label": "4th-anniversary", "link": {"en": "https://pixai.art/event/4th-anniversary"},
     "imageUrl": {"en": "https://cdn.test/a.webp"}, "mobileImageUrl": None, "title": None,
     "blank": False, "endTime": None},
    {"label": "tsubaki.3", "link": {"en": "/model/1"}, "imageUrl": {"en": ""}, "title": None,
     "blank": False, "endTime": None},
    {"label": "music-jam", "link": {"en": "https://www.youtube.com/watch?v=x"},
     "imageUrl": {"en": ""}, "title": None, "blank": True, "endTime": None},
    {"label": "old-event", "link": {"en": "/event/old"}, "imageUrl": {"en": ""}, "title": None,
     "blank": False, "endTime": "2026-01-01T00:00:00Z"},
]}


def test_only_live_banners_under_event_are_events(monkeypatch):
    seen = []
    monkeypatch.setattr(inbox, "_public_get", lambda path, **k: seen.append(path) or BANNERS)
    evs = inbox.current_events()
    assert [e["label"] for e in evs] == ["zeta", "4th-anniversary"]
    assert evs[0]["link"] == "https://pixai.art/en/event/zeta"
    assert evs[0]["title"] == "Zeta" and evs[1]["title"] == "4th anniversary"
    assert evs[0]["image"] == "https://cdn.test/z.webp"
    assert seen == ["/banners/"]


def test_the_banner_read_is_cached_for_an_hour_and_a_failure_is_not(monkeypatch):
    calls = []

    def answer(path, **k):
        calls.append(path)
        if len(calls) == 1:
            raise core.PixAIError("REST GET /banners/ -> 503")
        return BANNERS
    monkeypatch.setattr(inbox, "_public_get", answer)
    assert inbox.current_events() == []              # the failure answers nothing...
    assert len(inbox.current_events()) == 2          # ...and is not remembered
    inbox.current_events()
    assert len(calls) == 2                           # the success is


def test_the_banner_read_sends_no_credential(monkeypatch):
    """With the API key attached /v2/banners/ answers 404, so the read is a bare GET."""
    sent = {}

    class R:
        ok = True

        def json(self):
            return {"items": []}

    def fake_get(url, **kw):
        sent.update(url=url, **kw)
        return R()
    monkeypatch.setattr(inbox.requests, "get", fake_get)
    from tests.conftest import _REAL_INBOX_PUBLIC_GET   # conftest blocks the live one
    assert _REAL_INBOX_PUBLIC_GET("/banners/") == {"items": []}
    assert sent["url"].endswith("/v2/banners/")
    assert "Authorization" not in (sent.get("headers") or {})
    assert "auth" not in sent and "cookies" not in sent


# ---------------------------------------------------------------------------
# The routes: login only, one read on open, nothing written, nothing archived
# ---------------------------------------------------------------------------

def _app_with_work(tmp_path):
    rows = [{k: "" for k in CATALOG_FIELDS}]
    rows[0].update(media_id="m-local", artwork_id=ART, is_published="1", title="Moonwell Vigil")
    save_catalog(tmp_path / "catalog.db", rows)
    return create_app(tmp_path)


def test_the_inbox_route_reads_one_page_and_writes_nothing(tmp_path, pixai):
    pixai.on("/user/me/notifications/", _page([_comment("n2"), _like("n1", art=ART2),
                                                _follow("n3")]))
    cli = login_test_client(_app_with_work(tmp_path))
    d = cli.get("/api/inbox").get_json()
    assert [i["id"] for i in d["items"]] == ["n2", "n1", "n3"]
    by = {i["id"]: i for i in d["items"]}
    assert by["n2"]["artwork"]["media_id"] == "m-local"     # a work in the library opens Details
    assert by["n1"]["artwork"]["media_id"] == ""            # one that isn't opens PixAI
    assert d["csrf"] and d["read_only"] is False
    verbs = {c.verb for c in pixai.calls}
    assert verbs == {"rest_get"}, "opening the inbox wrote to PixAI"


def test_strangers_words_never_reach_the_disk(tmp_path, pixai):
    """Comments are live, in memory only: nothing the inbox read writes to the library folder
    carries a word of them."""
    pixai.on("/user/me/notifications/", _page([_comment("n2")]))
    cli = login_test_client(_app_with_work(tmp_path))
    assert STRANGER_WORDS in cli.get("/api/inbox").get_data(as_text=True)
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert STRANGER_WORDS.encode() not in p.read_bytes(), p


def test_an_unreadable_inbox_answers_an_error_not_an_empty_list(tmp_path, pixai):
    pixai.fail("/user/me/notifications/", core.PixAIError("REST GET -> 500"))
    cli = login_test_client(_app_with_work(tmp_path))
    d = cli.get("/api/inbox").get_json()
    assert d["error"] and d["items"] == []


def test_the_count_route_answers_the_badge(tmp_path, pixai):
    pixai.on("/user/me/notifications/unread-counts", [{"type": "COMMENT", "count": 4}])
    pixai.on("/user/me/official-dm/unread-summary", {"unreadMessages": 0, "unclaimedRewards": 2,
                                                     "hasMessages": True, "terminated": False})
    cli = login_test_client(_app_with_work(tmp_path))
    assert cli.get("/api/inbox/count").get_json()["total"] == 6


def test_the_events_route_answers_the_live_events(tmp_path, monkeypatch, pixai):
    monkeypatch.setattr(inbox, "_public_get", lambda path, **k: BANNERS)
    cli = login_test_client(_app_with_work(tmp_path))
    d = cli.get("/api/inbox/events").get_json()
    assert [e["label"] for e in d["events"]] == ["zeta", "4th-anniversary"]
