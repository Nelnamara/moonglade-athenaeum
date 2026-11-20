"""A refused API key: READS ride the stored Mirror sign-in, writes never do (2026-11-19).

PixAI answered this account's API key 401 from 10:16 on 2026-11-19 (membership lapsed) while
the same account's website sign-in kept working; the app showed zero credits, lost the Backed
up pill and could not list contests. moonglade.pixai_client now asks a refused READ once more
on the stored Mirror sign-in. These pin both halves: the read comes back, and nothing that
spends or changes the account ever switches credential."""
import pytest

from moonglade import backup as core
from moonglade import mirror as mirror_mod
from moonglade import pixai_client as pc
from tests.test_pixai_client import FakeResponse, RecordingSession

ACCOUNT = "1234567890"


@pytest.fixture(autouse=True)
def _fresh_hold(monkeypatch):
    monkeypatch.setitem(pc._key_refused, "until", 0.0)
    monkeypatch.setattr(core.time, "sleep", lambda s: None)


@pytest.fixture
def mirror_signin(monkeypatch):
    """A usable stored sign-in for ACCOUNT; the session built from it is a RecordingSession
    the test can read back (`.box[0]`)."""
    box = []

    def build(jwt):
        s = RecordingSession(FakeResponse({"data": {"me": {"id": ACCOUNT}}}))
        s.jwt = jwt
        box.append(s)
        return s
    monkeypatch.setattr(mirror_mod, "load_mirror_state", lambda: {"jwt": "stored.jwt.token"})
    monkeypatch.setattr(mirror_mod, "_jwt_usable", lambda jwt: jwt == "stored.jwt.token")
    monkeypatch.setattr(mirror_mod, "jwt_claims", lambda jwt: {"sub": ACCOUNT})
    monkeypatch.setattr(mirror_mod, "_mirror_session_from", build)
    return box


def _key_client(*answers, user_id=ACCOUNT):
    return pc.PixAIClient(RecordingSession(*answers), auth_kind="api-key", user_id=user_id,
                          read_fallback=True)


def test_a_refused_query_is_answered_on_the_mirror_signin(mirror_signin):
    c = _key_client(FakeResponse(status_code=401, text=""))
    assert c.query("query{ me{ id } }") == {"me": {"id": ACCOUNT}}
    assert len(c.session.calls) == 1                  # the key was asked once
    assert len(mirror_signin[0].calls) == 1           # and the sign-in once


def test_after_a_refusal_reads_go_straight_to_the_signin(mirror_signin):
    c = _key_client(FakeResponse(status_code=401, text=""))
    c.query("query{ me{ id } }")
    c.query("query{ me{ id } }")
    assert len(c.session.calls) == 1                  # not refused a second time first


def test_a_mutation_never_switches_credential(mirror_signin):
    c = _key_client(FakeResponse(status_code=401, text=""))
    with pytest.raises(core.PixAIAuthError):
        c.mutate("mutation{ doThing{ id } }")
    with pytest.raises(core.PixAIAuthError):
        c.query("mutation{ doThing{ id } }")        # a mutation document through query, too
    assert mirror_signin == []                        # no sign-in session was even built


def test_rest_writes_never_switch_credential(mirror_signin, monkeypatch):
    c = _key_client(FakeResponse(status_code=401, text=""))
    for verb in ("rest_post", "rest_put", "rest_patch"):
        monkeypatch.setattr(c.session, verb.split("_")[1], c.session.post, raising=False)
        with pytest.raises(Exception):
            getattr(c, verb)("/task/x/delete", {})
    assert mirror_signin == []


def test_a_refused_rest_get_is_answered_on_the_signin(mirror_signin):
    c = _key_client(FakeResponse(status_code=401, text=""))
    mirror_signin.clear()

    def build(jwt):
        s = RecordingSession(FakeResponse({"contests": []}))
        mirror_signin.append(s)
        return s
    mirror_mod._mirror_session_from = build
    assert c.rest_get("/contest/list") == {"contests": []}


def test_a_signin_for_another_account_is_never_used(mirror_signin, monkeypatch):
    monkeypatch.setattr(mirror_mod, "jwt_claims", lambda jwt: {"sub": "someone-else"})
    c = _key_client(FakeResponse(status_code=401, text=""))
    with pytest.raises(core.PixAIAuthError):
        c.query("query{ me{ id } }")
    assert mirror_signin == []


def test_no_usable_signin_keeps_the_plain_refusal(monkeypatch):
    monkeypatch.setattr(mirror_mod, "load_mirror_state", lambda: {})
    c = _key_client(FakeResponse(status_code=401, text=""))
    with pytest.raises(core.PixAIAuthError):
        c.query("query{ me{ id } }")


def test_a_hand_built_client_never_falls_back(mirror_signin):
    """The pasted-key check (/api/setup/save-key) wraps its own Session: a garbage key must
    fail, never verify on the stored sign-in."""
    c = pc._client_of(RecordingSession(FakeResponse(status_code=401, text="")))
    with pytest.raises(core.PixAIAuthError):
        c.query("query{ me{ id } }")
    assert mirror_signin == []


def test_a_raw_get_off_pixais_api_never_carries_the_signin(mirror_signin):
    c = _key_client(FakeResponse(status_code=401, text=""))
    r = c.get("https://images-ng.pixai.art/images/x")
    assert r.status_code == 401
    assert mirror_signin == []


def test_a_raw_api_get_is_answered_on_the_signin(mirror_signin):
    c = _key_client(FakeResponse(status_code=401, text=""))
    r = c.get("https://api.pixai.art/v1/media/123")
    assert r.status_code == 200
    assert len(mirror_signin) == 1
