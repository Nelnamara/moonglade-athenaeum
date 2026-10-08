"""Sessions R + Y (lane R): gifts in the gift box (R9c, drift 129). A REWARD official DM that is
PENDING can be claimed here: preview, one write, a status read-back, 409/410 in plain words.
Credit-pack bonuses open PixAI and send nothing.

Contract (probe 2026-10-03): the prefix is /v2/user/me/official-dm; the claim is
POST .../messages/{id}/claim with no body. No network: the `pixai` fixture's FakePixAI."""
import pytest

from moonglade import backup as core
from moonglade import inbox
from moonglade.gallery import create_app
from tests.conftest import login_test_client

GIFT = "01a0ef92-5e73-7a47-8c83-8ed07d723f66"      # official-DM ids are UUIDs (contract: q())
CLAIM = "/user/me/official-dm/messages/%s/claim" % GIFT


def _reward(mid=GIFT, status="PENDING", expires="2026-10-09T00:00:00Z", claimed=None,
            at="2026-10-03T08:00:00Z"):
    return {"id": mid, "senderType": "OFFICIAL", "content": "Thanks for celebrating with us",
            "media": [], "unread": True, "createdAt": at, "kind": "REWARD",
            "rewardTitle": "Anniversary gift", "rewardStatus": status,
            "rewardExpiresAt": expires, "claimedAt": claimed,
            "reward": {"decorations": [], "credits": 500,
                       "kaisuukens": [{"template": {"templateName": "Tsubaki.3",
                                                    "categoryName": "Model Card"}, "count": 3}]}}


def _thread(*msgs, thread=True):
    return {"thread": {"id": "t1", "lastMessageAt": "2026-10-03T08:00:00Z", "terminatedAt": None,
                       "createdAt": "2026-09-01T00:00:00Z"} if thread else None,
            "messages": list(msgs), "hasMore": False}


def _text(mid="01a0ef92-5e73-7a47-8c83-8ed07d723f02"):
    return {"id": mid, "senderType": "OFFICIAL", "content": "hello", "media": [], "unread": False,
            "createdAt": "2026-10-01T00:00:00Z", "kind": "TEXT"}


def test_no_thread_is_the_real_empty_state(pixai):
    """The owner's account has no official-DM thread today (probe 2026-10-03): thread null."""
    pixai.on("/user/me/official-dm/", _thread(thread=False))
    out = inbox.list_gifts(pixai)
    assert out == {"gifts": [], "has_thread": False}


def test_reward_messages_become_gift_rows_and_text_does_not(pixai):
    pixai.on("/user/me/official-dm/", _thread(_reward(), _text()))
    out = inbox.list_gifts(pixai)
    g = out["gifts"][0]
    assert [x["id"] for x in out["gifts"]] == [GIFT]
    assert g["status"] == "PENDING" and g["expires_at"] == "2026-10-09T00:00:00Z"
    assert g["what"] == "3 Tsubaki.3 cards · 500 credits"
    assert pixai.calls_for("/user/me/official-dm/")[0].params == {"take": 50}


def test_done_gifts_drop_out_after_seven_days(pixai):
    now = inbox._dt.datetime(2026, 10, 20, tzinfo=inbox._dt.timezone.utc)
    pixai.on("/user/me/official-dm/", _thread(
        _reward("01a0ef92-0000-7a47-8c83-000000003001", status="CLAIMED", claimed="2026-10-10T00:00:00Z"),
        _reward("01a0ef92-0000-7a47-8c83-000000003003", status="CLAIMED", claimed="2026-10-16T00:00:00Z"),
        _reward("01a0ef92-0000-7a47-8c83-000000003004", status="EXPIRED", expires="2026-10-05T00:00:00Z"),
        _reward("01a0ef92-0000-7a47-8c83-000000003005", status="PENDING", expires="2026-12-01T00:00:00Z")))
    out = inbox.list_gifts(pixai, now=now)
    assert [g["id"] for g in out["gifts"]] == ["01a0ef92-0000-7a47-8c83-000000003003", "01a0ef92-0000-7a47-8c83-000000003005"]


# ---------------------------------------------------------------------------
# The claim: READ_ONLY first, one write, a status read-back
# ---------------------------------------------------------------------------

def _posts(pixai):
    return [c for c in pixai.calls if c.verb == "rest_post"]


@pytest.mark.parametrize("bad", ["3001", "", "not-a-uuid", GIFT + "x", "../" + GIFT,
                                 "01a0ef92-5e73-7a47-8c83-8ed07d723f6"])
def test_a_gift_id_that_is_not_a_uuid_is_refused_before_pixai(pixai, bad):
    out = inbox.claim_gift(pixai, bad)
    assert out["state"] == "refused" and pixai.calls == []


def test_an_uppercase_uuid_is_a_gift_id_too(pixai):
    """UUIDs are case-insensitive: the claim and its read-back use one spelling."""
    pixai.on(CLAIM, {"rewards": {}, "message": {}})
    pixai.on("/user/me/official-dm/", _thread(_reward(status="CLAIMED", claimed="2026-10-03T09:00:00Z")))
    assert inbox.claim_gift(pixai, GIFT.upper())["state"] == "done"


def test_read_only_claims_nothing_and_asks_nothing(pixai, monkeypatch):
    monkeypatch.setattr(core, "READ_ONLY", True)
    out = inbox.claim_gift(pixai, GIFT)
    assert out["state"] == "read_only" and pixai.calls == []


def test_a_claim_is_one_post_with_no_body_then_a_status_read_back(pixai):
    pixai.on(CLAIM, {"rewards": {}, "message": _reward(status="CLAIMED")})
    pixai.on("/user/me/official-dm/", _thread(_reward(status="CLAIMED",
                                                      claimed="2026-10-03T09:00:00Z")))
    out = inbox.claim_gift(pixai, GIFT)
    assert out["state"] == "done" and out["message"] == "Claimed: 3 Tsubaki.3 cards · 500 credits."
    posts = _posts(pixai)
    assert len(posts) == 1 and posts[0].path == CLAIM and posts[0].body is None
    assert pixai.calls[-1].path == "/user/me/official-dm/"


@pytest.mark.parametrize("status,code,words", [
    (409, "ALREADY_CLAIMED", "Already claimed. Nothing changed."),
    (410, "REWARD_EXPIRED", "This gift expired. Nothing changed."),
    (404, "MESSAGE_NOT_FOUND", "PixAI can't find that gift. Nothing changed."),
])
def test_refusals_are_plain_peach_words(pixai, status, code, words):
    pixai.fail(CLAIM, core.PixAIRestError("REST POST -> %d" % status, status=status,
                                          body={"code": code}))
    out = inbox.claim_gift(pixai, GIFT)
    assert out["state"] == "refused" and out["message"] == words
    assert len(_posts(pixai)) == 1


def test_an_unclear_claim_that_reads_back_pending_is_never_success(pixai):
    pixai.fail(CLAIM, core.requests.ReadTimeout("no answer"))
    pixai.on("/user/me/official-dm/", _thread(_reward(status="PENDING")))
    out = inbox.claim_gift(pixai, GIFT)
    assert out["state"] == "unclear" and len(_posts(pixai)) == 1


def test_an_unclear_claim_that_reads_back_claimed_is_done(pixai):
    pixai.fail(CLAIM, core.PixAIRestError("REST POST -> 502", status=502))
    pixai.on("/user/me/official-dm/", _thread(_reward(status="CLAIMED",
                                                      claimed="2026-10-03T09:00:00Z")))
    assert inbox.claim_gift(pixai, GIFT)["state"] == "done"


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

def test_the_gifts_route_reads_the_thread_and_the_bonuses_and_writes_nothing(tmp_path, pixai):
    pixai.on("/user/me/official-dm/", _thread(_reward()))
    pixai.on("/extra-package-boosts", {"data": [
        {"code": "ZETA-2026", "boostRatePercentage": 20, "status": "available",
         "availableUntil": "2026-10-14T00:00:00Z"}], "pageInfo": {}})
    pixai.on("me", {"me": {"id": "u-test", "displayName": "Nelnamara"}})
    cli = login_test_client(create_app(tmp_path))
    d = cli.get("/api/inbox/gifts").get_json()
    assert [g["id"] for g in d["gifts"]] == [GIFT] and d["csrf"]
    assert d["bonuses"] == [{"code": "ZETA-2026", "percent": 20, "until": "2026-10-14T00:00:00Z"}]
    assert d["my_name"] == "Nelnamara"               # the claim preview names the account
    assert {c.verb for c in pixai.calls} <= {"rest_get", "query"}, "opening the gifts wrote"


def test_the_claim_route_needs_the_session_token(tmp_path, pixai):
    cli = login_test_client(create_app(tmp_path))
    r = cli.post("/api/inbox/gifts/claim", json={"csrf": "wrong", "id": GIFT})
    assert r.status_code == 400 and pixai.calls == []


def test_the_claim_route_answers_the_write(tmp_path, pixai):
    pixai.on("/user/me/official-dm/", _thread(_reward(status="CLAIMED",
                                                      claimed="2026-10-03T09:00:00Z")))
    pixai.on("/extra-package-boosts", {"data": [], "pageInfo": {}})
    pixai.on(CLAIM, {"rewards": {}, "message": _reward(status="CLAIMED")})
    cli = login_test_client(create_app(tmp_path))
    csrf = cli.get("/api/inbox/gifts").get_json()["csrf"]
    d = cli.post("/api/inbox/gifts/claim", json={"csrf": csrf, "id": GIFT}).get_json()
    assert d["state"] == "done"
