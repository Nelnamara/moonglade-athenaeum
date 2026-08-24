"""FakePixAI -- the second adapter behind the PixAI transport seam.

`moonglade_backup.PixAIClient` is the one road to PixAI. This is the other implementation
of that same road: same five verbs, same credential choice, same identity attributes, but
answering from responses a test registered instead of from a socket. It carries the
`_is_pixai_client` marker, so `_client_of()` hands it through untouched and every module
primitive (`gql`, `gql_adhoc`, `gql_mutate`, `_rest_get`, `_rest_post`) lands on it.

WHY THIS EXISTS. The suite used to substitute PixAI only by patching private names --
`core._make_session`, `core.gql_adhoc`, `core._rest_get`, `core._rest_post` -- a few
hundred times, each test hand-rolling its own stub. Offline-ness was a habit maintained by
those patches: a new test that forgot one, or a code path that reached for a helper nobody
thought to stub, would try the real network. Here it is structural. A FakePixAI answers
only what a test registered and refuses everything else BY NAME, so the failure mode is a
readable "nobody registered `createGenerationTask`" instead of a live request.

REGISTERING.

    fake.on("me", {"me": {"id": "42"}})                   # a GraphQL operation
    fake.on("me", lambda call: {...})                     # ...computed from the call
    fake.on("/kaisuuken/summary", {"kaisuukens": []})     # a REST path (leading slash)
    fake.fail("me", core.PixAIError("401 Unauthorized"))  # raise instead of answer

A callable answer is handed the recorded call itself -- `.verb`, `.op`, `.document`,
`.variables`, `.path`, `.params`, `.body` -- one rule for both roads. It is the whole call
rather than just the variables because three of this app account queries are anonymous
documents that all key to `me` (the account read, the free/paid credit split, the quota
log), and telling them apart means reading the document.

READING BACK.

    fake.calls                     # every call, in order: .verb .op .variables .body ...
    fake.calls_for("me")           # just that operation's
    fake.mutations("createGenerationTask")   # how many times it was MUTATED -- the count
                                             # that makes a double-spend visible

OPERATION NAMES. Keyed off the document: `mutation createGenerationTask(...)` is
`createGenerationTask`. Plenty of this app's documents are anonymous (`query{ me{ id } }`,
`mutation($id: ID!, $input: ...) { updateGenerationTask(...) }`), so an anonymous document
is keyed by its first ROOT FIELD -- `me`, `updateGenerationTask` -- which is the name a
reader would use for it anyway. `persisted()` is keyed by the operation name it is given.
"""
import re
from types import SimpleNamespace


class UnregisteredOperation(AssertionError):
    """A test asked the fake for something nobody registered.

    An AssertionError rather than a bespoke exception on purpose: reaching an unregistered
    operation is a test-authoring mistake (or a code path that just grew a new call), and
    it should read as a failed test, not as an error the code under test might catch. Note
    the app catches `PixAIError` in a lot of fail-soft places -- if this inherited from
    that, a missing registration would silently become an empty result."""


_OP_HEAD = re.compile(r"^\s*(query|mutation|subscription)\s*([A-Za-z_][A-Za-z0-9_]*)?",
                      re.IGNORECASE)
_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def operation_name(document):
    """The name this fake keys `document` by.

    A named operation gives its own name. An anonymous one is keyed by its first root
    field, because that IS how this codebase refers to those documents (`me`, `task`,
    `updateGenerationTask`). Returns "" for anything that is not a GraphQL document."""
    text = str(document or "")
    head = _OP_HEAD.match(text)
    if not head:
        return ""
    if head.group(2):
        return head.group(2)
    brace = text.find("{", head.end())
    if brace < 0:
        return ""
    field = _FIELD.search(text, brace + 1)
    return field.group(0) if field else ""


class FakePixAI:
    """A PixAI transport adapter that answers from a registry and records every call.

    Interface-compatible with `moonglade_backup.PixAIClient`: `query`, `mutate`,
    `persisted`, `rest_get`, `rest_post`, `for_create`, plus `user_id` / `auth_kind`.
    `mutate` takes no `retries` argument here EITHER -- the rule has to hold on both
    adapters, or a test could pass against a fake that allows what the real client
    forbids."""
    _is_pixai_client = True

    def __init__(self, user_id="u-test", auth_kind="api-key"):
        self.user_id = user_id
        self.auth_kind = auth_kind
        self.calls = []
        self._answers = {}
        self._errors = {}
        # The Authorization header run_watch reads off the session before subscribing.
        # A recognisable non-credential; nothing here ever authenticates anything.
        self.headers = {"Authorization": "Bearer fake-pixai-test-key",
                        "Accept": "application/json"}
        self.cookies = {}

    def __repr__(self):
        return "<FakePixAI {} calls, {} registered>".format(len(self.calls),
                                                            len(self._answers))

    # -- registering ---------------------------------------------------------
    def on(self, key, response):
        """Answer `key` with `response`. `key` is a GraphQL operation name, or a REST path
        (anything starting with "/"). `response` is a value, or a callable handed the
        recorded call (`.document`, `.variables`, `.params`, `.body`, ...). Returns self, so
        registrations chain."""
        self._answers[key] = response
        self._errors.pop(key, None)
        return self

    def fail(self, key, error):
        """Raise `error` when `key` is asked for -- the road for testing what the app does
        with a refusal (a PixAIError, a requests exception, anything)."""
        self._errors[key] = error
        self._answers.pop(key, None)
        return self

    def _resolve(self, key, kind, call):
        if key in self._errors:
            raise self._errors[key]
        if key not in self._answers:
            known = ", ".join(sorted(self._answers) + sorted(self._errors)) or "nothing"
            raise UnregisteredOperation(
                "FakePixAI was asked for the {} {!r}, which no test registered. "
                "Register it with fake.on({!r}, <response>) (or fake.fail(...) to make it "
                "refuse). Currently registered: {}.".format(kind, key, key, known))
        answer = self._answers[key]
        return answer(call) if callable(answer) else answer

    def _record(self, **kw):
        fields = dict(verb=None, op="", document=None, variables=None, retries=0,
                      path=None, params=None, body=None, client_library=None, headers=None)
        fields.update(kw)
        call = SimpleNamespace(**fields)
        self.calls.append(call)
        return call

    # -- the verbs -----------------------------------------------------------
    def query(self, document, variables=None, retries=None):
        return self._graphql("query", document, variables, retries)

    def mutate(self, document, variables=None):
        """No `retries` parameter, exactly as on the real client. `fake.mutations(op)`
        counts how many times a document was submitted, which is how a test asserts a
        spend fired ONCE without inspecting a retry argument at all."""
        return self._graphql("mutate", document, variables, 0)

    def _graphql(self, verb, document, variables, retries):
        op = operation_name(document)
        call = self._record(verb=verb, op=op, document=document, variables=variables,
                            retries=retries)
        return self._resolve(op, "GraphQL operation", call)

    def persisted(self, op_name, variables=None, sha256=None, retries=4,
                  client_library=None, headers=None):
        """Keyed by `op_name`, the whole point of the seam-level road: a test registers a
        canned answer with `fake.on(op_name, ...)` and it is returned here, or refuses by name
        if nobody did. `client_library` and `headers` mirror the real client's signature (the
        listArtworks GET passes both) and are recorded on the call so a test can assert the
        `x-apollo-operation-name` header rode along, exactly as it does on the wire."""
        call = self._record(verb="persisted", op=op_name, variables=variables,
                            retries=retries, client_library=client_library, headers=headers)
        return self._resolve(op_name, "persisted operation", call)

    def rest_get(self, path, params=None, timeout=30):
        call = self._record(verb="rest_get", op=path, path=path, params=params)
        return self._resolve(path, "REST GET path", call)

    def rest_post(self, path, body=None, timeout=60):
        call = self._record(verb="rest_post", op=path, path=path, body=body)
        return self._resolve(path, "REST POST path", call)

    def for_create(self):
        """The fake IS the create adapter. The mirror-vs-key choice is the real client's
        rule and is tested there (tests/test_pixai_client.py::TestForCreate); a test that
        wants to exercise it drives `core._session_for_create` / `PixAIClient.for_create`
        directly rather than through this."""
        return self

    # -- the transition surface ---------------------------------------------
    @property
    def session(self):
        raise UnregisteredOperation(
            "FakePixAI has no requests.Session -- that is the point. A path that reaches "
            "for `.session` (or calls `.get`/`.post` on the client) is one of the call "
            "sites still speaking HTTP itself: resolve_media, download, delete_task_gql, "
            "refresh_jwt. (The six persisted GETs -- task_detail_gql, _bookmarks_persisted, "
            "model_name_gql, resolve_model_base_id, _resolve_model_preset, artwork_list_gql "
            "-- ride persisted() now, so register them with fake.on(<operationName>, ...).) "
            "Stub the HTTP call directly instead of routing it through the fake.")

    def get(self, url, **kwargs):
        raise UnregisteredOperation(
            "FakePixAI was asked to GET {!r} directly. It answers verbs, not URLs -- see "
            "the note on `.session`.".format(url))

    def post(self, url, **kwargs):
        raise UnregisteredOperation(
            "FakePixAI was asked to POST {!r} directly. It answers verbs, not URLs -- see "
            "the note on `.session`.".format(url))

    # -- reading the recording ----------------------------------------------
    def calls_for(self, key):
        """Every recorded call against one operation name or REST path."""
        return [c for c in self.calls if c.op == key]

    def mutations(self, key=None):
        """How many MUTATE calls were made -- for `key`, or in total.

        This is the fake's half of the spend rule: `assert fake.mutations(
        "createGenerationTask") == 1` says the generation was submitted once, measured at
        the seam, with no retry argument anywhere in the assertion."""
        return len([c for c in self.calls
                    if c.verb == "mutate" and (key is None or c.op == key)])
