"""
moonglade/pixai_client.py
=========================
The ONE PixAI transport seam: PixAIClient (the six verbs, the credential choice for a create)
and _client_of, the adapter every road asks for. Moved verbatim out of moonglade/backup.py in
the 3.21.0 split (phase 2).

The module state it reads (USER_ID, API_URL, REST_API_BASE), the errors and the redirect and
REST-error helpers stay in moonglade.backup, and the create-session choke (`_session_for_create`)
lives in moonglade.mirror (since 3.21.0's phase 3). Each is imported inside the method that uses
it, at call time, so a test's patch of that module's binding still reaches it and importing
this module never imports the engine.
"""
import json
import sys
import time

try:
    import requests
except ImportError:
    sys.exit("Missing dependency. Run:  pip install requests")


# ===========================================================================
# pixai_client -- the ONE PixAI transport seam
# ===========================================================================
# Every byte this app exchanges with PixAI leaves through a PixAIClient. Before
# this section existed there was no transport MODULE at all: a bare
# requests.Session was threaded through seventy-odd functions as a positional
# argument, and the five primitives that actually spoke to PixAI --
# gql/gql_adhoc/gql_mutate/_rest_get/_rest_post -- were module functions that
# each re-derived the rules from that Session. The rules that matter are not
# stylistic:
#
#   * the retry policy, and the ONE place the spend rule lives. `mutate()` has
#     no `retries` parameter -- not defaulted to 0, ABSENT -- so a spending call
#     site cannot ask for the unsafe value. `query()`'s `retries=None` is
#     document-aware (3 for a query, 0 for a mutation) as the backstop for a
#     call site that reaches past `mutate()`. A lost RESPONSE is
#     indistinguishable from a lost REQUEST, and re-POSTing createGenerationTask
#     after PixAI already created and CHARGED for the task pays twice.
#   * the two roads to PixAI -- the ad-hoc GraphQL POST (`query()`/`mutate()`),
#     which sends a full document and is everything the API key can ask for over
#     GraphQL, and the oRPC `/v2` REST road (`rest_get()`/`rest_post()`/`rest_put()`/
#     `rest_patch()`). No saved (hash-only) request remains (#88, #89, #91, #92).
#   * WHICH credential a create rides (`for_create()`): the browser-JWT mirror
#     session when the Mirror toggle is on, the API key otherwise, and a refusal
#     rather than a silent fall-back to the key when the mirror is unavailable.
#
# There is a second adapter: `dev/tests/fake_pixai.py`'s FakePixAI answers the same
# interface from registered responses and refuses any operation nobody
# registered, so "the suite never touches the network" is structural instead of
# a habit maintained by 300-odd private monkeypatches.
#
# TRANSITION SURFACE. `get`/`post`/`headers`/`cookies` on the client delegate
# straight to the inner requests.Session, because a handful of call sites still
# reach for the Session themselves rather than through a verb: refresh_jwt's
# mirror POST (which must not ride rest_post: _rest_error would carry r.text, and the
# renewal's body is the token), resolve_media and download
# (which are not GraphQL at all -- a media object and a file body), and run_watch
# reading the Authorization header off to hand to the WebSocket. `.session` is the escape
# hatch those will eventually stop needing; it exists for the transition, not
# forever.
#
# NOT everything gets a client. A pasted API key is validated by hand-building a
# Session with that key as the sole credential (moonglade.gallery's
# /api/setup/save-key) precisely BECAUSE the normal path prefers the cached
# config -- a garbage key once verified because the real cached key answered.
# `_client_of()` therefore wraps whatever Session it is handed without reading
# config, resolving a user id, or touching a credential, so that route keeps its
# guarantee while still reaching account_info through the same verb.
# ===========================================================================


def _is_mutation_document(query):
    """True when `query` is a GraphQL MUTATION document rather than a query.

    Deliberately a dumb leading-keyword check: every document in this module is a plain
    string literal that starts with its operation type. Anything it cannot classify falls
    back to False (treated as a query), which is the behaviour that existed before it."""
    return str(query or "").lstrip().lower().startswith("mutation")


class PixAIClient:
    """The transport seam: everything this app asks PixAI, asked here.

    Six verbs (`query`, `mutate`, `rest_get`, `rest_post`, `rest_put`, `rest_patch`), one
    credential
    choice (`for_create`), and the underlying requests.Session on `.session` for the call
    sites still mid-transition. `auth_kind` is `"api-key"` or `"web-jwt"`; `user_id` is the
    resolved account id.

    The class holds no PixAI knowledge that the module does not already own -- endpoints,
    documents and the Apollo headers stay module-level -- so a client can be built around ANY
    session (a hand-built one, a test double) without that session inheriting the config
    cache."""

    #: Marks an object as a PixAI transport adapter, so `_client_of` hands it straight
    #: back instead of wrapping it. Checked with `is True` on purpose: a MagicMock answers
    #: every attribute with a truthy mock, and a mock standing in for a *Session* must
    #: still be wrapped or its `.post` would never be reached. This is what lets
    #: dev/tests/fake_pixai.py's FakePixAI be a real second adapter rather than a subclass --
    #: it satisfies the interface, it does not inherit the implementation.
    _is_pixai_client = True

    def __init__(self, session, auth_kind="api-key", user_id=None):
        self._session = session
        self._auth_kind = auth_kind
        self._user_id = user_id

    # -- identity ----------------------------------------------------------
    @property
    def session(self):
        """The underlying requests.Session. For the transition only -- prefer a verb."""
        return self._session

    @property
    def auth_kind(self):
        """`"api-key"` (the official credential) or `"web-jwt"` (the website mirror)."""
        return self._auth_kind

    @property
    def user_id(self):
        """The authenticated account's PixAI id."""
        from moonglade.backup import USER_ID
        return self._user_id or USER_ID

    def __repr__(self):
        return "<PixAIClient {} user={}>".format(self._auth_kind, self.user_id or "?")

    # -- the transition surface: the raw Session, delegated ------------------
    def get(self, *args, **kwargs):
        return self._session.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        return self._session.post(*args, **kwargs)

    @property
    def headers(self):
        return self._session.headers

    @property
    def cookies(self):
        return self._session.cookies

    # -- ad-hoc GraphQL POST -------------------------------------------------
    def query(self, document, variables=None, retries=None, timeout=120):
        """Run an ad-hoc (non-persisted) GraphQL operation by POSTing the full document.

        `retries=None` (the default) means "the safe default for THIS document": **3 for a
        query, 0 for a mutation**. A retry re-POSTs on a RequestException or a 429/5xx, and
        that is only free when the operation is idempotent. An explicit integer wins, so a
        caller can still ask for anything on purpose. `timeout` is the per-ATTEMPT socket
        timeout in seconds (120, this road's long-standing value, unless a caller says
        otherwise): a caller under a wall-clock ceiling of its own passes the time it has left
        -- the delete preview's live check does, through `task_detail_gql`. Returns the `data`
        dict; raises PixAIError on GraphQL/HTTP error."""
        if retries is None:
            retries = 0 if _is_mutation_document(document) else 3
        return self._graphql_post(document, variables, retries, timeout)

    def mutate(self, document, variables=None):
        """`query()` for a mutation that MUST NOT fire twice: SINGLE ATTEMPT, always, and it
        NEVER FOLLOWS A REDIRECT (a 307/308 would re-send the mutation to a URL the answering
        server chose; #92 review F1) -- a 3xx raises with nothing re-sent.

        It takes **no `retries` argument on purpose** -- there is no correct value above 0
        for a spending path, so the knob is not offered rather than offered with a safe
        default a call site can override by accident. Pinned by
        dev/tests/test_pixai_client.py and dev/tests/test_spend_no_retry.py."""
        return self._graphql_post(document, variables, 0)

    def _graphql_post(self, document, variables, retries, timeout=120):
        """The one ad-hoc POST loop. `retries` is already resolved to an integer by the
        verb that called in -- this function never chooses it, which is what keeps the
        spend rule readable in exactly two places above. `timeout` is each attempt's socket
        timeout: whatever `query` was handed, and always 120 for `mutate`.

        A MUTATION document (`_is_mutation_document`, whichever verb sent it -- `mutate`, or
        `query` as the backstop) never follows a redirect (#92 review F1): it is sent with
        `allow_redirects=False`, and a 3xx raises before its body is read, with nothing
        re-sent. A query document keeps requests' default."""
        from moonglade.backup import API_URL, _is_redirect_status, PixAIError, _ssl_help
        body = {"query": document, "variables": variables or {}}
        follow_redirects = not _is_mutation_document(document)
        send = {} if follow_redirects else {"allow_redirects": False}
        delay = 2.0
        for attempt in range(retries + 1):
            try:
                r = self._session.post(API_URL, json=body, timeout=timeout, **send)
            except requests.exceptions.SSLError:
                raise PixAIError(_ssl_help())
            except requests.RequestException:
                if attempt == retries:
                    raise
                time.sleep(delay); delay *= 2; continue
            if not follow_redirects and _is_redirect_status(r):
                raise PixAIError("HTTP {} -- PixAI redirected this request; nothing was "
                                 "re-sent.".format(r.status_code))
            if r.status_code == 401:
                raise PixAIError("401 Unauthorized -- API key missing/expired.")
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == retries:
                    r.raise_for_status()
                time.sleep(delay); delay *= 2; continue
            try:
                data = r.json()
            except ValueError:
                raise PixAIError("HTTP {} non-JSON response:\n{}".format(
                    r.status_code, r.text[:400]))
            if data.get("errors"):
                err = PixAIError("GraphQL error: " + json.dumps(data["errors"])[:500])
                # The WHOLE list rides on the error: the message keeps 500 characters, and a
                # structured refusal (a recipe's RECIPE_* with its ids and reason) can be
                # longer. Reading it changes nothing about what was sent or retried.
                err.graphql_errors = data["errors"]
                # A GraphQL answer may carry `errors` AND `data` at once: a partial success,
                # where the root field DID resolve (a run created and charged) and something
                # beneath it failed. The data rides on the error so a spend guard can tell
                # that apart from a refusal (definite_refusal; waves 2+3 review, F2).
                err.graphql_data = data.get("data")
                raise err
            return data.get("data") or {}
        raise RuntimeError("unreachable")

    # -- the oRPC /v2 REST road ----------------------------------------------
    def rest_get(self, path, params=None, timeout=30):
        """GET a /v2 oRPC REST route. Returns parsed JSON. Raises PixAIError on non-2xx.

        Single-attempt by construction, like `rest_post` -- see its note."""
        from moonglade.backup import REST_API_BASE, _rest_error
        r = self._session.get(REST_API_BASE + path, params=params, timeout=timeout)
        if not r.ok:
            raise _rest_error("GET", path, r)
        return r.json()

    def rest_post(self, path, body=None, timeout=60):
        """POST JSON to a /v2 oRPC REST route. Returns parsed JSON. Raises on non-2xx.

        NO retry loop, deliberately: `submit_fixer`, `claim_reward` and `delete_task` ride
        this, and the session mounts no urllib3 Retry adapter (requests' default HTTPAdapter
        is max_retries=0), so all are single-attempt. Pinned by
        dev/tests/test_spend_no_retry.py::test_rest_post_has_no_retry_loop.

        NEVER FOLLOWS A REDIRECT (#92 review F1; the same on every write verb): requests would
        re-send a 307/308 -- body, API-key Bearer and all -- to a URL the answering server
        chose, and turn a 301/302/303 into a GET whose answer then decides "it worked". So
        redirects are off, and a 3xx raises (`_refuse_redirect`) before anything reads its
        body."""
        from moonglade.backup import _refuse_redirect, REST_API_BASE, _rest_error
        r = self._session.post(REST_API_BASE + path, json=body, timeout=timeout,
                               allow_redirects=False)
        _refuse_redirect("POST", path, r)
        if not r.ok:
            raise _rest_error("POST", path, r)
        return r.json()

    def rest_patch(self, path, body=None, timeout=60):
        """PATCH JSON to a /v2 oRPC REST route. Single attempt, like rest_post / rest_put:
        its one caller (joining a LoRA to the rebate programme) cannot be undone. Never
        follows a redirect, like rest_post."""
        from moonglade.backup import _refuse_redirect, REST_API_BASE, _rest_error
        r = self._session.patch(REST_API_BASE + path, json=body, timeout=timeout,
                                allow_redirects=False)
        _refuse_redirect("PATCH", path, r)
        if not r.ok:
            raise _rest_error("PATCH", path, r)
        return r.json()

    def rest_put(self, path, body=None, timeout=60):
        """PUT JSON to a /v2 oRPC REST route. Returns parsed JSON. Raises on non-2xx.

        Single-attempt like `rest_post`, and by the same reasoning: the training routes that
        ride it (a dataset replace, a description save) change the account, and a re-send
        after a lost response can land on a task that has already moved on. Pinned alongside
        rest_post by dev/tests/test_spend_no_retry.py. Never follows a redirect, like
        rest_post."""
        from moonglade.backup import _refuse_redirect, REST_API_BASE, _rest_error
        r = self._session.put(REST_API_BASE + path, json=body, timeout=timeout,
                              allow_redirects=False)
        _refuse_redirect("PUT", path, r)
        if not r.ok:
            raise _rest_error("PUT", path, r)
        return r.json()

    # -- which credential a create rides -------------------------------------
    def for_create(self):
        """The client a CREATE must POST through: the browser-JWT mirror when the 'Mirror
        to PixAI' toggle is on (so the generation lands in the pixai.art web library),
        this same client otherwise. Refuses (raises) rather than falling back to the API
        key when the mirror is armed but unavailable. Callers must have already passed
        `_check_read_only` -- building the mirror session may make a renewal call."""
        from moonglade.mirror import _session_for_create
        chosen = _session_for_create(self)
        if chosen is self:
            return self
        return PixAIClient(chosen, auth_kind="web-jwt")


def _client_of(session):
    """The transport adapter for `session`: itself when it already is one, a thin
    PixAIClient wrapper around it otherwise.

    "Already is one" is the `_is_pixai_client is True` marker rather than an isinstance
    check, so a second adapter (dev/tests/fake_pixai.py's FakePixAI) passes through without
    inheriting this class's implementation.

    Wrapping reads NO config and resolves NO credential -- that is what lets the pasted-
    API-key validation route hand its own hand-built Session to account_info and still
    get the guarantee it was built for."""
    if getattr(session, "_is_pixai_client", False) is True:
        return session
    return PixAIClient(session)


# --- end pixai_client ------------------------------------------------------
