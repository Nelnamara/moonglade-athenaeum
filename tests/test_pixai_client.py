"""The PixAI transport seam: `PixAIClient`, the one way this app talks to PixAI.

These tests drive the client against a recording stand-in for `requests.Session` --
nothing here opens a socket, and no test in this file can spend anything: the only
"mutation" documents used are invented ones, answered by a local object.

What is pinned:

  * each verb makes the HTTP call it claims to (`query`/`mutate` -> POST /graphql,
    `persisted` -> GET /graphql with the Apollo persisted-query params, `rest_get` /
    `rest_post` -> the oRPC `/v2` base);
  * `mutate` retries EXACTLY 0 times and has no `retries` parameter to ask with -- the
    spend rule at the one place it now lives (tests/test_spend_no_retry.py pins the same
    property from the spending paths' side);
  * `query` still retries 3 times on a retryable failure, so the no-retry rule did not
    leak into reads;
  * `for_create()` picks the mirror (web-JWT) client vs the API-key one by the existing
    rule, and refuses rather than falling back;
  * the five module-level primitives are thin delegates, and a raw Session and a client
    are interchangeable at every one of them.
"""
import inspect
import json

import pytest
import requests

import moonglade_backup as core
from tests.fake_pixai import FakePixAI, UnregisteredOperation, operation_name


class FakeResponse:
    """The parts of a requests.Response the transport reads."""
    def __init__(self, payload=None, status_code=200, text="", content=b""):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.content = content or (json.dumps(payload).encode() if payload else b"")

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("HTTP {}".format(self.status_code))


class RecordingSession:
    """A requests.Session that records instead of sending.

    `answers` is a list of FakeResponse (or exceptions to raise), consumed in order; the
    last one repeats, so one answer stands for "every attempt gets this". Every call lands
    in `.calls` as (verb, url, kwargs) -- which is how "exactly one POST" is asserted."""
    def __init__(self, *answers):
        self.answers = list(answers) or [FakeResponse({"data": {}})]
        self.calls = []
        self.headers = {}
        self.cookies = {}

    def _answer(self, verb, url, kwargs):
        self.calls.append((verb, url, kwargs))
        a = self.answers[min(len(self.calls) - 1, len(self.answers) - 1)]
        if isinstance(a, Exception):
            raise a
        return a

    def get(self, url, **kwargs):
        return self._answer("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._answer("POST", url, kwargs)


# Captured at import, BEFORE conftest's autouse `_no_live_card_network` swaps them for a
# raising stub. That fixture is what makes the whole suite offline by default; this file is
# the one place that must exercise the real REST helpers, and it does so against a
# RecordingSession, so nothing leaves the machine either way.
_REAL_REST_GET = core._rest_get
_REAL_REST_POST = core._rest_post


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    """Retries are counted, never waited for."""
    monkeypatch.setattr(core.time, "sleep", lambda s: None)


@pytest.fixture
def real_rest(monkeypatch):
    """Put the real `_rest_get`/`_rest_post` back for a test that is ABOUT them."""
    monkeypatch.setattr(core, "_rest_get", _REAL_REST_GET)
    monkeypatch.setattr(core, "_rest_post", _REAL_REST_POST)


# ---------------------------------------------------------------------------
# Each verb delegates with the right HTTP shape
# ---------------------------------------------------------------------------

class TestVerbsMakeTheRightCall:
    def test_query_posts_the_document_to_graphql(self):
        s = RecordingSession(FakeResponse({"data": {"me": {"id": "7"}}}))
        c = core.PixAIClient(s)
        assert c.query("query{ me{ id } }") == {"me": {"id": "7"}}
        (verb, url, kwargs), = s.calls
        assert verb == "POST" and url == core.API_URL
        assert kwargs["json"] == {"query": "query{ me{ id } }", "variables": {}}

    def test_mutate_posts_the_document_to_graphql(self):
        s = RecordingSession(FakeResponse({"data": {"doThing": {"id": "1"}}}))
        c = core.PixAIClient(s)
        assert c.mutate("mutation{ doThing{ id } }", {"a": 1}) == {"doThing": {"id": "1"}}
        (verb, url, kwargs), = s.calls
        assert verb == "POST" and url == core.API_URL
        assert kwargs["json"]["variables"] == {"a": 1}

    def test_graphql_errors_become_pixaierror(self):
        s = RecordingSession(FakeResponse({"errors": [{"message": "nope"}]}))
        with pytest.raises(core.PixAIError, match="GraphQL error"):
            core.PixAIClient(s).query("query{ bad }")

    def test_a_401_says_so_plainly(self):
        s = RecordingSession(FakeResponse(status_code=401, text=""))
        with pytest.raises(core.PixAIError, match="401 Unauthorized"):
            core.PixAIClient(s).query("query{ me{ id } }")

    def test_persisted_gets_graphql_with_the_apollo_persisted_params(self):
        s = RecordingSession(FakeResponse({"data": {"page": 1}}))
        c = core.PixAIClient(s)
        assert c.persisted(core.OPERATION_NAME, {"last": 5}) == {"page": 1}
        (verb, url, kwargs), = s.calls
        assert verb == "GET" and url == core.API_URL
        p = kwargs["params"]
        assert p["operation"] == core.OPERATION_NAME
        assert p["operationName"] == core.OPERATION_NAME
        assert json.loads(p["variables"]) == {"last": 5}
        ext = json.loads(p["extensions"])
        assert ext["persistedQuery"] == {"version": 1,
                                         "sha256Hash": core.PERSISTED_QUERY_HASH}

    def test_persisted_refuses_an_operation_with_no_known_hash(self):
        c = core.PixAIClient(RecordingSession())
        with pytest.raises(core.PixAIError, match="no persisted hash"):
            c.persisted("someOperationNobodyCaptured", {})

    def test_persisted_names_the_recapture_step_on_a_stale_hash(self):
        s = RecordingSession(FakeResponse({"errors": [{"message": "PersistedQueryNotFound"}]}))
        with pytest.raises(core.PixAIError, match="Recapture"):
            core.PixAIClient(s).persisted(core.OPERATION_NAME, {})

    def test_rest_get_hits_the_v2_base(self):
        s = RecordingSession(FakeResponse({"kaisuukens": []}))
        c = core.PixAIClient(s)
        assert c.rest_get("/kaisuuken/summary", params={"a": 1}) == {"kaisuukens": []}
        (verb, url, kwargs), = s.calls
        assert verb == "GET" and url == core.REST_API_BASE + "/kaisuuken/summary"
        assert kwargs["params"] == {"a": 1}

    def test_rest_post_hits_the_v2_base(self):
        s = RecordingSession(FakeResponse({"id": "T1"}))
        c = core.PixAIClient(s)
        assert c.rest_post("/task/fixer", {"mediaId": "M1"}) == {"id": "T1"}
        (verb, url, kwargs), = s.calls
        assert verb == "POST" and url == core.REST_API_BASE + "/task/fixer"
        assert kwargs["json"] == {"mediaId": "M1"}

    def test_rest_raises_pixaierror_on_non_2xx(self):
        c = core.PixAIClient(RecordingSession(FakeResponse(status_code=500, text="nope")))
        with pytest.raises(core.PixAIError, match="REST GET"):
            c.rest_get("/claim")


class TestThePrimitivesAreThinDelegates:
    """The five module-level primitives keep their names and their `session`-first
    signatures -- seventy-odd functions still call them that way -- but the road itself
    lives on the client rather than being re-implemented beside it."""
    @pytest.mark.parametrize("name", ["gql", "gql_adhoc", "gql_mutate",
                                      "_rest_get", "_rest_post"])
    def test_it_routes_through_the_client(self, name, real_rest):
        src = inspect.getsource(getattr(core, name))
        assert "_client_of(" in src, "{} no longer routes through the client".format(name)
        assert "session.post(" not in src and "session.get(" not in src, \
            "{} speaks HTTP itself again -- it must delegate".format(name)

    def test_gql_delegates_to_persisted(self):
        s = RecordingSession(FakeResponse({"data": {"page": 1}}))
        assert core.gql(s, {"last": 3}) == {"page": 1}
        assert s.calls[0][0] == "GET"

    def test_gql_adhoc_takes_a_raw_session(self):
        s = RecordingSession(FakeResponse({"data": {"me": {"id": "1"}}}))
        assert core.gql_adhoc(s, "query{ me{ id } }") == {"me": {"id": "1"}}

    def test_gql_adhoc_takes_a_client(self):
        s = RecordingSession(FakeResponse({"data": {"me": {"id": "1"}}}))
        assert core.gql_adhoc(core.PixAIClient(s), "query{ me{ id } }") == {"me": {"id": "1"}}

    def test_rest_helpers_take_either_shape(self, real_rest):
        s = RecordingSession(FakeResponse({"ok": 1}))
        assert core._rest_get(s, "/claim") == {"ok": 1}
        assert core._rest_post(core.PixAIClient(s), "/claim/1", {}) == {"ok": 1}

    def test_client_of_is_identity_for_a_client(self):
        c = core.PixAIClient(RecordingSession())
        assert core._client_of(c) is c

    def test_wrapping_reads_no_config_and_resolves_no_credential(self, monkeypatch):
        """The pasted-API-key route hand-builds a Session with the submitted key as its
        sole credential and reaches account_info with it, precisely BECAUSE the normal
        path prefers the module-cached config (a garbage key once verified because the
        real cached key answered). Wrapping must therefore be inert."""
        monkeypatch.setattr(core, "_load_config",
                            lambda *a, **k: pytest.fail("wrapping read config.json"))
        monkeypatch.setattr(core, "resolve_user_id",
                            lambda *a, **k: pytest.fail("wrapping resolved a user id"))
        s = RecordingSession(FakeResponse({"data": {"me": {"id": "1"}}}))
        assert core._client_of(s).session is s
        assert core.account_info(s) == {"id": "1"}

    def test_make_session_hands_back_a_client(self, monkeypatch, tmp_path):
        """`_make_session` is the app's one entry to PixAI and now returns the seam
        itself, so every `session` threaded through the module is a client in production
        while still accepting a bare Session anywhere."""
        monkeypatch.setattr(core, "_load_config", lambda *a, **k: {"PIXAI_API_KEY": "k"})
        monkeypatch.setattr(core, "load_token", lambda v: "k")
        monkeypatch.setattr(core, "USER_ID", "u-1")
        c = core._make_session(None)
        assert isinstance(c, core.PixAIClient)
        assert c.auth_kind == "api-key" and c.user_id == "u-1"
        assert c.headers["Authorization"] == "Bearer k"


class TestTheTransitionSurface:
    """resolve_media, download, delete_task_gql, refresh_jwt and run_watch still reach for
    the Session themselves (delete_task_gql POSTs a persisted mutation, which Apollo blocks
    over GET, so it does not ride `persisted()`). Those calls have to keep working when what
    they hold is a client. The six persisted GETs no longer belong on this list -- they ride
    `persisted()` now; see TestTheSixPersistedGetsRideTheClient below."""
    def test_get_post_headers_cookies_delegate_to_the_session(self):
        s = RecordingSession(FakeResponse({"ok": 1}))
        s.headers["Authorization"] = "Bearer k"
        c = core.PixAIClient(s)
        assert c.headers["Authorization"] == "Bearer k"     # run_watch reads this
        assert c.cookies is s.cookies
        assert c.session is s
        c.get("https://example/x", timeout=1)               # resolve_media / download
        c.post("https://example/y", json={"a": 1})          # delete_task_gql / refresh_jwt
        assert [v for v, _u, _k in s.calls] == ["GET", "POST"]


class TestTheSixPersistedGetsRideTheClient:
    """The last six hand-rolled persisted GETs now ride `PixAIClient.persisted()` like every
    other PixAI call. Two things are pinned: they no longer build params or call the Session
    themselves (they delegate through `_client_of`), and the wire they put on the socket is
    BYTE-IDENTICAL to what they sent before -- same operationName, same captured
    `sha256Hash`, same `variables` JSON -- which is the whole safety case for the change.
    The hashes asserted here are the module constants, and those are unchanged from
    origin/master, so matching them is matching master's wire."""

    SIX = ["task_detail_gql", "_bookmarks_persisted", "model_name_gql",
           "resolve_model_base_id", "_resolve_model_preset", "artwork_list_gql"]

    @pytest.mark.parametrize("name", SIX)
    def test_it_delegates_through_the_client_and_speaks_no_http_itself(self, name):
        src = inspect.getsource(getattr(core, name))
        assert "_client_of(" in src, "{} no longer routes through the client".format(name)
        assert ".persisted(" in src, "{} does not ride persisted()".format(name)
        assert "session.get(" not in src and "session.post(" not in src, \
            "{} speaks HTTP itself again -- it must delegate".format(name)

    # -- the wire each one puts on the socket is byte-identical to master -----------------
    def _get(self, driver, data):
        """Drive `driver(client)` against a RecordingSession answering `{"data": data}`,
        and return (params, headers) of the single GET it made."""
        s = RecordingSession(FakeResponse({"data": data}))
        driver(core.PixAIClient(s))
        (verb, url, kwargs) = s.calls[0]
        assert verb == "GET" and url == core.API_URL
        return kwargs["params"], kwargs.get("headers")

    def test_task_detail_gql_wire(self):
        p, _ = self._get(lambda c: core.task_detail_gql(c, "T7"), {"task": {"id": "T7"}})
        assert p["operationName"] == "getTaskById"
        assert json.loads(p["variables"]) == {"id": "T7"}
        ext = json.loads(p["extensions"])
        assert ext["persistedQuery"] == {"version": 1, "sha256Hash": core.TASK_DETAIL_HASH}

    def test_bookmarks_persisted_wire(self):
        p, _ = self._get(
            lambda c: core._bookmarks_persisted(c, {}, False, "", "", "", 24),
            {"me": {"bookmarkedGenerationModels": {}}})
        assert p["operationName"] == core.BOOKMARKED_MODELS_OP == "listMyBookmarkedGenerationModels"
        assert json.loads(p["variables"]) == {"first": 24}
        ext = json.loads(p["extensions"])
        assert ext["persistedQuery"]["sha256Hash"] == core.BOOKMARKED_MODELS_HASH

    def test_model_name_gql_wire(self):
        p, _ = self._get(
            lambda c: core.model_name_gql(c, "wire-model-id-0001"),
            {"generationModelVersion": {"name": "v1", "model": {"title": "T"}}})
        assert p["operationName"] == "getGenerationModelByVersionId"
        assert json.loads(p["variables"]) == {"id": "wire-model-id-0001"}
        ext = json.loads(p["extensions"])
        assert ext["persistedQuery"]["sha256Hash"] == core.MODEL_DETAIL_HASH

    def test_resolve_model_base_id_wire(self):
        p, _ = self._get(
            lambda c: core.resolve_model_base_id(c, "V-wire-1"),
            {"generationModelVersion": {"model": {"id": "B1"}}})
        assert p["operationName"] == "getGenerationModelByVersionId"
        assert json.loads(p["variables"]) == {"id": "V-wire-1"}
        ext = json.loads(p["extensions"])
        assert ext["persistedQuery"]["sha256Hash"] == core.MODEL_DETAIL_HASH

    def test_resolve_model_preset_wire(self):
        p, _ = self._get(
            lambda c: core._resolve_model_preset(c, "V-preset-wire-1"),
            {"generationModelVersion": {"extra": {}}})
        assert p["operationName"] == "getGenerationModelByVersionId"
        assert json.loads(p["variables"]) == {"id": "V-preset-wire-1"}
        ext = json.loads(p["extensions"])
        assert ext["persistedQuery"]["sha256Hash"] == core.MODEL_DETAIL_HASH

    def test_artwork_list_gql_wire(self):
        """The one outlier: it sends its OWN clientLibrary block and an x-apollo-operation-name
        CSRF header. Both must survive the move onto the shared seam byte-for-byte."""
        p, headers = self._get(lambda c: core.artwork_list_gql(c, last=50),
                               {"artworks": {"edges": [], "pageInfo": {}}})
        assert p["operationName"] == "listArtworks"
        assert json.loads(p["variables"]) == {"authorId": str(core.USER_ID), "last": 50,
                                              "tackLanguage": "en"}
        ext = json.loads(p["extensions"])
        assert ext["persistedQuery"]["sha256Hash"] == core.ARTWORK_LIST_HASH
        assert ext["clientLibrary"] == core.CLIENT_LIBRARY_ARTWORK
        assert headers == {"x-apollo-operation-name": "listArtworks"}

    # -- FakePixAI is the second adapter on this same road -------------------------------
    def test_fake_pixai_answers_a_registered_persisted_op(self):
        fake = FakePixAI().on("getTaskById", {"task": {"id": "T9"}})
        assert core.task_detail_gql(fake, "T9") == {"id": "T9"}
        assert fake.calls_for("getTaskById")[0].variables == {"id": "T9"}

    def test_fake_pixai_refuses_an_unregistered_persisted_op(self):
        """Offline-by-default: an op nobody registered is refused BY NAME, and the refusal is
        an AssertionError -- not a PixAIError -- so task_detail_gql's fail-soft catch cannot
        quietly swallow it into a None."""
        fake = FakePixAI()
        with pytest.raises(UnregisteredOperation, match="getTaskById"):
            core.task_detail_gql(fake, "T9")

    def test_fake_pixai_records_the_artwork_client_library_and_header(self):
        fake = FakePixAI().on("listArtworks", {"artworks": {"edges": [], "pageInfo": {}}})
        core.artwork_list_gql(fake, last=50)
        call = fake.calls_for("listArtworks")[0]
        assert call.headers == {"x-apollo-operation-name": "listArtworks"}
        assert call.client_library == core.CLIENT_LIBRARY_ARTWORK


# ---------------------------------------------------------------------------
# The spend rule, at the seam
# ---------------------------------------------------------------------------

class TestRetryPolicy:
    def test_mutate_has_no_retries_parameter_at_all(self):
        assert "retries" not in inspect.signature(core.PixAIClient.mutate).parameters
        with pytest.raises(TypeError):
            core.PixAIClient(RecordingSession()).mutate("mutation{ x }", None, retries=1)

    def test_mutate_posts_exactly_once_on_a_retryable_failure(self):
        """A lost RESPONSE is indistinguishable from a lost REQUEST: re-POSTing
        createGenerationTask after PixAI already created and CHARGED for the task pays
        twice. One attempt, always."""
        s = RecordingSession(requests.ConnectionError("connection dropped"))
        with pytest.raises(requests.RequestException):
            core.PixAIClient(s).mutate("mutation{ doThing{ id } }")
        assert len(s.calls) == 1

    def test_mutate_posts_exactly_once_on_a_5xx(self):
        """The ambiguous one: a proxy's 502 can arrive after the backend already ran."""
        s = RecordingSession(FakeResponse(status_code=502, text="bad gateway"))
        with pytest.raises(requests.HTTPError):
            core.PixAIClient(s).mutate("mutation{ doThing{ id } }")
        assert len(s.calls) == 1

    def test_query_retries_three_times_on_a_retryable_failure(self):
        """The other half: this is not a blanket no-retry policy. Reads are idempotent and
        a flaky network must not fail them on the first blip."""
        s = RecordingSession(requests.ConnectionError("connection dropped"))
        with pytest.raises(requests.RequestException):
            core.PixAIClient(s).query("query{ me{ id } }")
        assert len(s.calls) == 4                      # the original + 3 retries

    def test_query_retries_three_times_on_a_429(self):
        s = RecordingSession(FakeResponse(status_code=429, text="slow down"))
        with pytest.raises(requests.HTTPError):
            core.PixAIClient(s).query("query{ me{ id } }")
        assert len(s.calls) == 4

    def test_query_of_a_mutation_document_still_does_not_retry(self):
        """The backstop for a call site that reaches past `mutate()`."""
        s = RecordingSession(requests.ConnectionError("connection dropped"))
        with pytest.raises(requests.RequestException):
            core.PixAIClient(s).query("mutation{ doThing{ id } }")
        assert len(s.calls) == 1

    def test_an_explicit_count_still_wins_on_query(self):
        s = RecordingSession(requests.ConnectionError("connection dropped"))
        with pytest.raises(requests.RequestException):
            core.PixAIClient(s).query("query{ me{ id } }", retries=0)
        assert len(s.calls) == 1

    def test_persisted_retries_four_times_by_default(self):
        s = RecordingSession(requests.ConnectionError("connection dropped"))
        with pytest.raises(requests.RequestException):
            core.PixAIClient(s).persisted(core.OPERATION_NAME, {})
        assert len(s.calls) == 5                      # the original + 4 retries

    def test_rest_post_makes_exactly_one_attempt(self):
        """submit_fixer and claim_reward ride this. No loop, by construction."""
        s = RecordingSession(FakeResponse(status_code=502, text="bad gateway"))
        with pytest.raises(core.PixAIError):
            core.PixAIClient(s).rest_post("/task/fixer", {})
        assert len(s.calls) == 1


# ---------------------------------------------------------------------------
# for_create(): which credential a create rides
# ---------------------------------------------------------------------------

class TestForCreate:
    def test_mirror_off_is_the_same_client(self, monkeypatch):
        monkeypatch.setattr(core, "mirror_enabled", lambda: False)
        c = core.PixAIClient(RecordingSession())
        assert c.for_create() is c
        assert c.for_create().auth_kind == "api-key"

    def test_mirror_on_returns_a_web_jwt_client_over_the_mirror_session(self, monkeypatch):
        mirror = RecordingSession()
        monkeypatch.setattr(core, "mirror_enabled", lambda: True)
        monkeypatch.setattr(core, "make_mirror_session", lambda: mirror)
        c = core.PixAIClient(RecordingSession())
        made = c.for_create()
        assert made is not c
        assert made.session is mirror
        assert made.auth_kind == "web-jwt"

    def test_mirror_on_but_unavailable_refuses_and_never_falls_back(self, monkeypatch):
        """F5: if the mirror session is unavailable, refuse and spend nothing -- never
        quietly file the generation under the API key instead."""
        monkeypatch.setattr(core, "mirror_enabled", lambda: True)
        monkeypatch.setattr(core, "make_mirror_session", lambda: None)
        c = core.PixAIClient(RecordingSession())
        with pytest.raises(core.PixAIError, match="Mirror to PixAI is ON"):
            c.for_create()

    def test_it_is_the_same_rule_the_module_choke_uses(self, monkeypatch):
        """`_session_for_create` stays the one place the rule is written; `for_create()`
        is its face on the client, not a second copy of the decision."""
        monkeypatch.setattr(core, "mirror_enabled", lambda: False)
        c = core.PixAIClient(RecordingSession())
        assert core._session_for_create(c) is c
        assert c.for_create() is core._session_for_create(c)


# ---------------------------------------------------------------------------
# The second adapter
# ---------------------------------------------------------------------------

class TestFakePixAISatisfiesTheSameInterface:
    VERBS = ("query", "mutate", "persisted", "rest_get", "rest_post", "for_create")

    @pytest.mark.parametrize("verb", VERBS)
    def test_the_fake_offers_the_same_verb_with_the_same_signature(self, verb):
        """Same interface, verb for verb -- otherwise a test could pass against the fake
        and fail against the real client, or the reverse."""
        real = inspect.signature(getattr(core.PixAIClient, verb)).parameters
        fake = inspect.signature(getattr(FakePixAI, verb)).parameters
        assert list(fake) == list(real), \
            "FakePixAI.{} has a different shape from PixAIClient.{}".format(verb, verb)

    def test_mutate_on_the_fake_offers_no_retries_either(self):
        """The spend rule has to hold on BOTH adapters, or a test could pass against a
        fake that allows what the real client forbids."""
        assert "retries" not in inspect.signature(FakePixAI.mutate).parameters

    def test_the_fake_is_recognised_as_a_client_and_never_wrapped(self):
        fake = FakePixAI()
        assert core._client_of(fake) is fake

    def test_a_magicmock_is_still_wrapped_not_mistaken_for_a_client(self, mock_session):
        """The marker is checked with `is True` precisely because a MagicMock answers every
        attribute truthily. A mock standing in for a Session must keep receiving `.post`."""
        assert core._client_of(mock_session) is not mock_session
        assert core._client_of(mock_session).session is mock_session

    @pytest.mark.parametrize("document, expected", [
        ("mutation createGenerationTask($parameters: JSONObject!) { x }",
         "createGenerationTask"),
        ("query listChatEditingScenes { scenes { id } }", "listChatEditingScenes"),
        ("query{ me{ id } }", "me"),
        ("query($id: ID!) { task(id: $id) { id } }", "task"),
        ("\n  mutation($id: ID!, $input: UpdateGenerationTaskInput!) {\n"
         "    updateGenerationTask(id: $id, input: $input) { id }\n  }\n",
         "updateGenerationTask"),
        ("", ""),
        (None, ""),
    ])
    def test_operation_names_come_off_the_document(self, document, expected):
        """Named operations give their name; this codebase's anonymous ones are keyed by
        their first root field, which is what a reader calls them anyway."""
        assert operation_name(document) == expected

    def test_an_unregistered_operation_is_refused_by_name(self):
        fake = FakePixAI()
        with pytest.raises(UnregisteredOperation, match="createGenerationTask"):
            fake.mutate("mutation createGenerationTask($p: JSONObject!) { id }", {"p": {}})

    def test_an_unregistered_rest_path_is_refused_by_path(self):
        fake = FakePixAI()
        with pytest.raises(UnregisteredOperation, match="/kaisuuken/summary"):
            fake.rest_get("/kaisuuken/summary")

    def test_the_refusal_is_not_a_pixaierror(self):
        """A lot of this app fails SOFT on PixAIError. If a missing registration raised
        one, it would be swallowed into an empty result and the test would pass on a
        pretend answer instead of telling the author what to register."""
        fake = FakePixAI()
        with pytest.raises(UnregisteredOperation) as e:
            fake.query("query me { id }")
        assert not isinstance(e.value, core.PixAIError)

    def test_a_registered_response_is_returned_and_the_call_recorded(self):
        fake = FakePixAI()
        fake.on("me", {"me": {"id": "42"}})
        assert fake.query("query me { id }") == {"me": {"id": "42"}}
        assert [c.op for c in fake.calls] == ["me"]
        assert fake.calls[0].verb == "query"

    def test_a_response_can_be_computed_from_the_variables(self):
        fake = FakePixAI()
        fake.on("task", lambda call: {"task": {"id": call.variables["id"],
                                               "status": "completed"}})
        got = fake.query("query($id: ID!) { task(id: $id) { id } }", {"id": "T7"})
        assert got["task"]["id"] == "T7"

    def test_a_registered_error_is_raised(self):
        fake = FakePixAI()
        fake.fail("me", core.PixAIError("401 Unauthorized -- API key missing/expired."))
        with pytest.raises(core.PixAIError, match="401"):
            fake.query("query me { id }")

    def test_registering_a_response_clears_a_previous_failure(self):
        fake = FakePixAI()
        fake.fail("me", core.PixAIError("boom"))
        fake.on("me", {"me": {"id": "1"}})
        assert fake.query("query me { id }") == {"me": {"id": "1"}}

    def test_mutate_counts_its_calls_so_a_double_spend_is_visible(self):
        """The fake's half of the spend rule: a test asserts the mutation was submitted
        exactly once, by COUNT at the seam, with no retry argument in the assertion."""
        fake = FakePixAI()
        fake.on("createGenerationTask", {"createGenerationTask": {"id": "T1"}})
        doc = "mutation createGenerationTask($p: JSONObject!) { id }"
        fake.mutate(doc, {"p": {}})
        assert fake.mutations("createGenerationTask") == 1
        fake.mutate(doc, {"p": {}})
        assert fake.mutations("createGenerationTask") == 2
        assert fake.mutations() == 2

    def test_a_query_is_not_counted_as_a_mutation(self):
        fake = FakePixAI()
        fake.on("me", {"me": {}})
        fake.query("query me { id }")
        assert fake.mutations() == 0

    def test_for_create_answers_a_client_shaped_thing(self):
        fake = FakePixAI()
        assert fake.for_create() is fake

    def test_the_fake_exposes_the_identity_attributes(self):
        fake = FakePixAI(user_id="u-1")
        assert fake.user_id == "u-1"
        assert fake.auth_kind == "api-key"

    def test_reaching_for_the_raw_session_says_why_it_is_not_there(self):
        """Offline-by-default is structural here: there is no Session to fall through to,
        and the message names the call sites that still speak HTTP themselves."""
        fake = FakePixAI()
        with pytest.raises(UnregisteredOperation, match="no requests.Session"):
            fake.session
        with pytest.raises(UnregisteredOperation, match="answers verbs, not URLs"):
            fake.get("https://api.pixai.art/v1/media/M1")


class TestTheFixtureIsWhatTheAppIsHanded:
    def test_make_session_returns_the_fake(self, pixai):
        """`_gen_session()` is `(core, core._make_session(None))` and is how all 36 gallery
        call sites reach PixAI, so pinning `_make_session` pins both."""
        assert core._make_session(None) is pixai
        assert core._make_session("some-token") is pixai

    def test_gen_session_hands_the_gallery_the_fake(self, pixai, tmp_path):
        """Through the real route, not the closure: /api/account is a `_gen_session()`
        caller, and with the fixture installed its account read lands on the fake."""
        from tests.conftest import login_client
        pixai.on("me", {"me": {"id": "u-test", "quotaAmount": 500}})
        pixai.on("/kaisuuken/summary", {"kaisuukens": []})
        pixai.on("/claim", {"claims": []})
        d = login_client(tmp_path).get("/api/account").get_json()
        assert d["credits"] == 500
        # All three roads through the fake in one route: the ad-hoc GraphQL read, and two
        # /v2 REST reads. Nothing was registered for the credit-split call, which the route
        # guards separately -- so the split comes back unknown rather than breaking it.
        assert "me" in [c.op for c in pixai.calls]
        assert "/kaisuuken/summary" in [c.op for c in pixai.calls]
        assert "/claim" in [c.op for c in pixai.calls]
        assert d["credits_free"] is None and d["credits_paid"] is None

    def test_every_primitive_routes_to_the_fake(self, pixai):
        pixai.on("me", {"me": {"id": "9"}})
        pixai.on("listUserTaskSummaries", {"edges": []})
        pixai.on("/claim", {"claims": []})
        pixai.on("/claim/1", {"ok": True})
        assert core.gql_adhoc(pixai, "query me { id }") == {"me": {"id": "9"}}
        assert core.gql(pixai, {"last": 1}) == {"edges": []}
        assert core._rest_get(pixai, "/claim") == {"claims": []}
        assert core._rest_post(pixai, "/claim/1", {}) == {"ok": True}
        assert [c.verb for c in pixai.calls] == ["query", "persisted", "rest_get",
                                                 "rest_post"]

    def test_an_unstubbed_call_fails_loudly_instead_of_going_to_the_network(self, pixai):
        """The whole point: nothing registered, nothing answered, and the message names
        what to register."""
        with pytest.raises(UnregisteredOperation, match="me"):
            core.account_info(pixai, raise_on_error=True)
