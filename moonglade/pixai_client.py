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


#: How long, after PixAI refuses the API key on a read, reads go straight to the Mirror
#: sign-in before the key is tried again (so a renewed membership is noticed within this).
KEY_REFUSED_HOLD_S = 600
_key_refused = {"until": 0.0}

#: The only host a Mirror sign-in is ever sent to by the read fallback.
_PIXAI_API_PREFIX = "https://api.pixai.art/"


# ---------------------------------------------------------------------------
# THE CREATE DOOR's tables (DESIGN_3.22 2.2). A closed map of kind -> route: a path is never
# built from caller text. `image` and `edit` share PixAI's task.createTask route, whose body is
# {"parameters": P}; the other three take their body as given. Video and reference video are
# not here: they stay on GraphQL createGenerationTask through mutate() (gen_road.CREATE_ROAD).
# ---------------------------------------------------------------------------
CREATE_PATHS = {
    "image": "/task/create",
    "edit": "/task/create",
    "scene": "/task/chat-editing-scene",
    "enhance": "/task/enhance",
    "fix": "/task/fixer",
}
#: The kinds the door wraps as {"parameters": P} (PixAI's `ys` wrapper).
CREATE_WRAPPED_KINDS = frozenset(("image", "edit"))
#: The kinds that run only on the Mirror's website sign-in: an API-key scene or panelplugin
#: task was accepted, charged and reaped unstarted (DECISIONS 2026-08-18).
CREATE_WEB_JWT_KINDS = frozenset(("scene", "enhance"))
#: PixAI's QUOTE routes. Each sits one segment from a spend route, so none may ever be a door
#: path. The check below is an `if`, not an `assert`, so `python -O` cannot strip it, and it
#: pins every door path to its exact literal.
CREATE_QUOTE_PATHS = frozenset(("/task/fixer/price", "/task/enhance/price", "/task-price"))
if (set(CREATE_PATHS.values()) & CREATE_QUOTE_PATHS
        or sorted(set(CREATE_PATHS.values())) != ["/task/chat-editing-scene", "/task/create",
                                                  "/task/enhance", "/task/fixer"]):
    raise ImportError("CREATE_PATHS must be exactly the four create routes, and no quote route")
#: (connect, read) seconds: one POST, and a lost answer is "may have started", never a resend.
CREATE_TIMEOUT = (10, 120)
#: The READ_ONLY refusal wording per kind (the same sentences the creates raised before).
_CREATE_ACTIONS = {"fix": "submit a hand/face fix (spends credits)"}
_CREATE_ACTION_DEFAULT = "submit a generation (spends credits)"


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

    def __init__(self, session, auth_kind="api-key", user_id=None, read_fallback=False):
        self._session = session
        self._auth_kind = auth_kind
        self._user_id = user_id
        # Only _make_session's client sets this. A hand-built client (the pasted-key check
        # in /api/setup/save-key) must never answer with anything but the key it was handed.
        self._read_fallback = bool(read_fallback)

    # -- a refused key: READS ride the Mirror sign-in (2026-11-19) -----------
    # PixAI began answering this account's API key 401 on 2026-11-19 ("This API key needs an
    # active PixAI membership") while the same account's website sign-in kept working. A READ
    # the key is refused on is asked once more on the stored Mirror sign-in -- the one the
    # user's own pixai.art tab handed over through Connect from PixAI, already checked then to
    # be this same account. Never a write: mutate, rest_post/put/patch and a mutation document
    # keep the key alone, so nothing that spends or changes the account switches credential.
    # The token is used as stored and never renewed here (a read must not roll it forward).
    def _read_fallback_session(self):
        """A Bearer session on the stored Mirror sign-in, for a READ the API key was refused
        on -- or None (not this client's to do, no usable sign-in, or a sign-in for another
        account than this client's). Never raises."""
        if not getattr(self, "_read_fallback", False):
            return None
        try:
            from moonglade import mirror as _mirror
            jwt = _mirror.load_mirror_state().get("jwt") or ""
            if not _mirror._jwt_usable(jwt):
                return None
            sub = str(_mirror.jwt_claims(jwt).get("sub") or "")
            mine = str(self.user_id or "")
            if not sub or (mine and mine != sub):
                return None
            return _mirror._mirror_session_from(jwt)
        except Exception:                                   # noqa: BLE001 -- None, never raise
            return None

    def _first_reader(self):
        """The session a READ tries first: the Mirror sign-in while the key was refused in
        the last KEY_REFUSED_HOLD_S (so every read does not pay a refusal first), else the
        key's own session."""
        if getattr(self, "_read_fallback", False) and time.monotonic() < _key_refused["until"]:
            fb = self._read_fallback_session()
            if fb is not None:
                return fb
        return self._session

    def _after_key_refused(self):
        """The key's session was just refused (401) on a read: note it and return the
        Mirror session to ask once more on, or None."""
        fb = self._read_fallback_session()
        if fb is not None:
            _key_refused["until"] = time.monotonic() + KEY_REFUSED_HOLD_S
        return fb

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
        """A raw GET (the /v1/media reads and file bodies). One the key is refused on, to
        PixAI's API host only, is asked once more on the Mirror sign-in (see above)."""
        url = args[0] if args else kwargs.get("url", "")
        on_api = isinstance(url, str) and url.startswith(_PIXAI_API_PREFIX)
        sess = self._first_reader() if on_api else self._session
        r = sess.get(*args, **kwargs)
        if on_api and sess is self._session and getattr(r, "status_code", None) == 401:
            fb = self._after_key_refused()
            if fb is not None:
                r = fb.get(*args, **kwargs)
        return r

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
        from moonglade.backup import (API_URL, _is_redirect_status, PixAIError, PixAIAuthError,
                                      _ssl_help, graphql_error)
        body = {"query": document, "variables": variables or {}}
        follow_redirects = not _is_mutation_document(document)
        send = {} if follow_redirects else {"allow_redirects": False}
        delay = 2.0
        # A query may ride the Mirror sign-in when the key is refused; a mutation never.
        sess = self._first_reader() if follow_redirects else self._session
        for attempt in range(retries + 1):
            try:
                r = sess.post(API_URL, json=body, timeout=timeout, **send)
                if r.status_code == 401 and follow_redirects and sess is self._session:
                    fb = self._after_key_refused()
                    if fb is not None:
                        sess = fb
                        r = sess.post(API_URL, json=body, timeout=timeout, **send)
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
                raise PixAIAuthError("401 Unauthorized -- API key missing/expired.")
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
                # The WHOLE list rides on the error (`graphql_errors`): the message keeps 500
                # characters, and a structured refusal (a recipe's RECIPE_* with its ids and
                # reason) can be longer. Reading it changes nothing about what was sent or
                # retried. A GraphQL answer may carry `errors` AND `data` at once: a partial
                # success, where the root field DID resolve (a run created and charged) and
                # something beneath it failed. The data rides on the error (`graphql_data`) so
                # a spend guard can tell that apart from a refusal (classify_outcome; waves 2+3
                # review, F2). A non-list `errors` is carried as a one-item list.
                errs = data["errors"]
                err = graphql_error(errs if isinstance(errs, list) else [errs], data.get("data"))
                raise err
            return data.get("data") or {}
        raise RuntimeError("unreachable")

    # -- the oRPC /v2 REST road ----------------------------------------------
    def rest_get(self, path, params=None, timeout=30):
        """GET a /v2 oRPC REST route. Returns parsed JSON. Raises PixAIError on non-2xx.

        Single-attempt by construction, like `rest_post` -- see its note."""
        from moonglade.backup import REST_API_BASE, _rest_error
        sess = self._first_reader()
        r = sess.get(REST_API_BASE + path, params=params, timeout=timeout)
        if r.status_code == 401 and sess is self._session:
            fb = self._after_key_refused()
            if fb is not None:
                r = fb.get(REST_API_BASE + path, params=params, timeout=timeout)
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

    # -- THE CREATE DOOR (DESIGN_3.22 2.2-2.5) ---------------------------------
    def create(self, kind, body):
        """THE one way a generation, an edit, an AI-Tools scene, an enhance or a Fix is sent:
        ONE POST to the route `kind` names in CREATE_PATHS, and PixAI's answer back (a dict
        carrying a non-empty string `id`). There is no `retries` parameter and no loop: a lost
        answer is indistinguishable from a lost request, and a second POST pays twice.

        In order, and nothing reaches the network until every step has passed:
          1. the kind is one of the table's (the path is the table's, never caller text);
          2. READ_ONLY (`_check_read_only`);
          3. the shape agrees with the kind (V10): a video block (`i2vPro`,
             `referenceVideo`) never rides `image` or `edit`, `chat` means `edit`, and an
             `edit` without `chat` is refused -- the kind comes from the caller's own mode,
             never sniffed from the parameters;
          4. the identity (2.5): `scene` and `enhance` only on a `web-jwt` client;
          5. the final wire step (2.4): the REST known-drop rule (gen_params.rest_wire), the
             {"parameters": P} wrapper on /task/create, serialised ONCE; the recursive
             allowlist (gen_params.check_wire) then reads those very bytes back and refuses
             on any key PixAI would drop, at any depth. The bytes checked are the bytes sent.
        Every refusal is a LocalRefusal: nothing was sent.

        The send is `allow_redirects=False` with a (10, 120) s timeout. The answer:
          - a 2xx JSON object with a non-empty string `id` -> returned (the evidence per
            kind is in DESIGN_3.22 2.2; scene and enhance await R6/R7, so a wrong guess makes
            a success read unclear, the fail-safe direction);
          - any other status -> PixAIRestError (status, code, body), which
            gen_road.classify_outcome reads;
          - a timeout, a dropped connection, a 3xx, a non-JSON or id-less 2xx ->
            CreateOutcomeUnknown, which is outside the PixAIError tree on purpose.

        The log line names the kind, the path, the true identity, a short digest of the body
        and whether a card is attached -- never the prompt, never the credential."""
        from moonglade.backup import (REST_API_BASE, _check_read_only, _is_redirect_status,
                                      _rest_error, _ssl_help, LocalRefusal,
                                      CreateOutcomeUnknown)
        from moonglade import gen_params as _gen_params
        path = CREATE_PATHS.get(kind) if isinstance(kind, str) else None
        if path is None:
            raise LocalRefusal("Moonglade has no create route named {!r}, so nothing was "
                               "sent.".format(str(kind)[:40]))
        try:
            _check_read_only(_CREATE_ACTIONS.get(kind, _CREATE_ACTION_DEFAULT))
        except LocalRefusal:
            raise
        except Exception as e:                              # noqa: BLE001 -- nothing was sent
            raise LocalRefusal(str(e)) from e
        if not isinstance(body, dict):
            raise LocalRefusal("This request has no body to send, so nothing was sent.")
        if kind in CREATE_WRAPPED_KINDS:
            if "i2vPro" in body or "referenceVideo" in body:
                raise LocalRefusal("A video request can't be sent as an {}, so nothing was "
                                   "sent.".format("edit" if kind == "edit" else "image"))
            if kind == "edit" and "chat" not in body:
                raise LocalRefusal("An edit request carries no edit block, so nothing was "
                                   "sent.")
            if kind == "image" and "chat" in body:
                raise LocalRefusal("An edit request can't be sent as an image, so nothing "
                                   "was sent.")
        if kind in CREATE_WEB_JWT_KINDS and self.auth_kind != "web-jwt":
            raise LocalRefusal("This runs only on your PixAI website sign-in (Mirror to "
                               "PixAI), so nothing was sent.")
        inner = _gen_params.rest_wire(kind, body)
        final = {"parameters": inner} if kind in CREATE_WRAPPED_KINDS else inner
        try:
            blob = json.dumps(final, separators=(",", ":"), ensure_ascii=False,
                              allow_nan=False).encode("utf-8")
        except (TypeError, ValueError):
            raise LocalRefusal("This request holds a value that can't be sent as JSON, so "
                               "nothing was sent.")
        _gen_params.check_wire(kind, json.loads(blob.decode("utf-8")))
        _log_create(kind, path, self.auth_kind, blob,
                    bool(isinstance(inner, dict) and inner.get("kaisuukenId")))
        try:
            r = self._session.post(REST_API_BASE + path, data=blob,
                                   headers={"Content-Type": "application/json"},
                                   timeout=CREATE_TIMEOUT, allow_redirects=False)
        except requests.exceptions.SSLError as e:
            raise CreateOutcomeUnknown(_ssl_help(), kind=kind) from e
        except requests.RequestException as e:
            raise CreateOutcomeUnknown("POST {} -> no answer ({}): PixAI may have started "
                                       "this.".format(path, type(e).__name__), kind=kind) from e
        status = getattr(r, "status_code", None)
        if _is_redirect_status(r):
            raise CreateOutcomeUnknown("POST {} -> {}: PixAI redirected this request; nothing "
                                       "was re-sent.".format(path, status), kind=kind,
                                       status=status)
        if not (isinstance(status, int) and 200 <= status < 300):
            raise _rest_error("POST", path, r)
        try:
            answer = r.json()
        except ValueError:
            raise CreateOutcomeUnknown("POST {} -> {} that is not JSON: PixAI may have started "
                                       "this.".format(path, status), kind=kind, status=status)
        tid = answer.get("id") if isinstance(answer, dict) else None
        if not (isinstance(tid, str) and tid.strip()):
            raise CreateOutcomeUnknown("POST {} -> {} with no task id: PixAI may have started "
                                       "this.".format(path, status), kind=kind, status=status)
        return answer

    # -- which credential a create rides -------------------------------------
    #: True on a client for_create() chose for one send. _session_for_create hands such a
    #: client straight back, so the identity is chosen ONCE per send (V8): the card check and
    #: the door see the same client even if the Mirror toggle moves in between.
    _create_chosen = False

    def for_create(self, require=None):
        """The client a CREATE must POST through: the browser-JWT mirror when the 'Mirror
        to PixAI' toggle is on (so the generation lands in the pixai.art web library),
        this same credential otherwise. Refuses (raises) rather than falling back to the API
        key when the mirror is armed but unavailable. Callers must have already passed
        `_check_read_only` -- building the mirror session may make a renewal call.

        The answer is a MARKED client (`_create_chosen`, DESIGN_3.22 2.5): `auth_kind` is the
        identity it truly rides ("web-jwt" for the Mirror), and asking a marked client again
        returns it unchanged, so one send never chooses twice. `require="web-jwt"` (scene,
        enhance) refuses, with nothing sent, unless the Mirror is armed and usable."""
        from moonglade.backup import LocalRefusal
        if getattr(self, "_create_chosen", False) is True:
            chosen = self
        else:
            from moonglade.mirror import _session_for_create
            got = _session_for_create(self)
            if got is self:
                chosen = PixAIClient(self._session, auth_kind=self._auth_kind,
                                     user_id=self._user_id)
                chosen._create_chosen = True
            elif getattr(got, "_is_pixai_client", False) is True:
                chosen = got
            else:
                chosen = PixAIClient(got, auth_kind="web-jwt")
                chosen._create_chosen = True
        if require is not None and getattr(chosen, "auth_kind", None) != require:
            raise LocalRefusal("This runs only on your PixAI website sign-in: switch Mirror to "
                               "PixAI on and connect it. Nothing was sent.")
        return chosen


def _log_create(kind, path, identity, blob, card):
    """The door's one log line: kind, route, identity, a 12-hex digest of the exact body and
    whether a card rides it. Never the body itself (it holds the prompt), never a credential.
    Fail-soft: logging never stops or changes a send."""
    try:
        import hashlib
        import logging
        logging.getLogger("moonglade.create").info(
            "create %s -> POST %s as %s; body %s; card %s", kind, path, identity,
            hashlib.sha256(blob).hexdigest()[:12], "attached" if card else "none")
    except Exception:                                       # noqa: BLE001
        pass


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
