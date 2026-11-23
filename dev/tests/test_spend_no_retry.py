"""A credit-spending mutation must be submitted EXACTLY ONCE.

`gql_adhoc` retries on a RequestException and on a 429/5xx. For a QUERY that is correct
and free. For `createGenerationTask` it is a double-spend: a lost RESPONSE is
indistinguishable from a lost REQUEST, so a read timeout, a dropped connection, or a
proxy's 502 arriving after PixAI already created and CHARGED for the task makes the retry
submit -- and pay for -- a second generation.

`delete_batch_media_gql` already recognised this and passed `retries=0` by hand
(dev/tests/test_poll.py::test_delete_batch_media_never_retries). Every spending path was
missed, because passing the argument by hand is exactly the kind of thing a new call site
forgets. The fix is structural rather than per-call-site, and this file pins both halves
of it:

  1. `gql_mutate()` -- the helper every spending path now calls. It hard-codes `retries=0`
     and takes NO retries argument at all, so the unsafe value cannot be asked for.
  2. `gql_adhoc()`'s mutation-aware DEFAULT -- `retries=None` resolves to 0 for a mutation
     document and 3 for a query. This is the backstop for a future call site that reaches
     past `gql_mutate`; the point of the design is that a spending path cannot inherit the
     retrying default by accident.

Nothing here spends anything: every test asserts on the recorded call arguments or on the
POST count against a mock session. No generation is ever run.
"""
import ast
import inspect
import re
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from moonglade import backup as core
from moonglade import cards as cards_mod
from moonglade import gen_cli as gen_cli_mod
from moonglade import gen_road as gen_road_mod
from moonglade import pixai_client as pixai_client_mod
from moonglade import mirror as mirror_mod
from moonglade import task_reads as task_reads_mod
from moonglade import cloud_delete as cloud_delete_mod
from moonglade import training as training_mod
from moonglade import account_api as account_api_mod


# Every function that fires a credit-spending or account-mutating GraphQL call. When a new
# spend path ships, add it here -- test_no_spend_path_calls_gql_adhoc_directly is what
# makes forgetting loud instead of silent.
SPEND_PATHS = ("submit_generation", "run_generate", "run_generate_video",
               "run_reference_video", "run_edit_image", "upload_media",
               "delete_batch_media_gql",
               # the per-image delete since 3.22 S3-delete: POST /v2/task/{id}/media/{mid}/delete
               "delete_task_media",
               # The per-image delete's router (2026-09-06): it fires one of the two
               # delete mutations after reading the live task, so it is an
               # account-mutating path in its own right.
               "delete_image_routed",
               # The whole-task delete (#92): POST /v2/task/{id}/delete through rest_post.
               # Not GraphQL at all now, so it must never grow a gql_adhoc call either.
               "delete_task",
               # LoRA training: spends real credits once the free-training quota is
               # gone, and a re-POST would start a SECOND training (2026-08-06).
               "submit_training",
               # Session J's two GraphQL writers (waves 2+3 review, F5): the advanced
               # draft (createTrainingTask -- a re-POST would make a second draft) and
               # making a LoRA public (upsertGenerationModel -- irreversible).
               "create_advanced_training_draft", "make_model_public",
               # The advanced training REST spend paths (3.22 S3-training, DESIGN_3.22 2.10):
               # start, retry, describe and publish a run, each one rest_post on the API key.
               "submit_advanced_training", "retry_training", "start_training_captions",
               "publish_training",
               # Artwork mutations: no credits, but they change the public account and
               # a retry would publish twice / delete something already gone.
               "publish_artwork_from_task", "update_artwork", "delete_artwork",
               # Session M's run sender (2026-09-29): up to 24 generations, one after
               # another, each through submit() -> submit_generation(exact=True).
               "send_run")

# Where each spend path lives: backup, or the split module it moved to (3.22, phases 4-5).
_HOMES = (core, cloud_delete_mod, gen_road_mod, gen_cli_mod, training_mod, account_api_mod)


def _spend_path(name):
    return next((getattr(m, name) for m in _HOMES if hasattr(m, name)), None)


# A real call, not a mention: the comments in these functions name gql_adhoc on purpose
# ("gql_mutate, never gql_adhoc") and must not trip the check.
_CALLS_GQL_ADHOC = re.compile(r"\bgql_adhoc\s*\(")


_STUB_PAYLOAD = {"createGenerationTask": {"id": "T1"},
                 "updateGenerationTask": {"id": "T1"},
                 "uploadMedia": {"uploadUrl": "https://s3.example/put",
                                 "externalId": "E1", "mediaId": "M1"}}


@pytest.fixture
def gql_calls(monkeypatch):
    """Record every ad-hoc GraphQL POST the code under test makes -- the VERB it came
    through and the retry count the loop was actually handed -- and answer it with a
    plausible payload so the caller keeps going.

    Recorded at `PixAIClient._graphql_post`, the single function that owns the retry loop,
    with `query`/`mutate` wrapped only to tag which verb reached it. That is deliberately
    lower than the old recorder (which stood in for `gql_adhoc` and read `retries=None` as
    "took the default"): `retries` here is the resolved integer the loop will count with,
    so `mutate()`'s hard-coded 0 is OBSERVED rather than inferred, and `verb` makes
    "reached the loop through the road that offers no retries knob" checkable on its own.
    Both real methods still run, so the document-aware default is exercised, not bypassed.
    """
    calls = []
    real_query = pixai_client_mod.PixAIClient.query
    real_mutate = pixai_client_mod.PixAIClient.mutate
    box = {"verb": None}

    def _query(self, document, variables=None, retries=None, timeout=120):
        box["verb"] = "query"
        try:
            return real_query(self, document, variables, retries, timeout)
        finally:
            box["verb"] = None

    def _mutate(self, document, variables=None):
        box["verb"] = "mutate"
        try:
            return real_mutate(self, document, variables)
        finally:
            box["verb"] = None

    def _recorder(self, document, variables, retries, timeout=120):
        calls.append(SimpleNamespace(query=document, variables=variables,
                                     retries=retries, verb=box["verb"]))
        return _STUB_PAYLOAD

    monkeypatch.setattr(pixai_client_mod.PixAIClient, "query", _query)
    monkeypatch.setattr(pixai_client_mod.PixAIClient, "mutate", _mutate)
    monkeypatch.setattr(pixai_client_mod.PixAIClient, "_graphql_post", _recorder)
    return calls


@pytest.fixture
def door_calls(monkeypatch):
    """Record every create that reached THE create door (PixAIClient.create, 3.22), through
    the real core._create delegate (conftest blocks it), and answer each with a task id. The
    door itself -- one POST, no retries argument, no loop -- is pinned in
    test_create_door.py; this records that a spend path reached it once per job."""
    from tests.conftest import _REAL_CREATE
    calls = []

    def _create(self, kind, body):
        calls.append(SimpleNamespace(kind=kind, body=body))
        return {"id": "T{}".format(len(calls))}
    monkeypatch.setattr(core, "_create", _REAL_CREATE)
    monkeypatch.setattr(pixai_client_mod.PixAIClient, "create", _create)
    return calls


@pytest.fixture
def cli_stubs(mock_session, monkeypatch):
    """The minimum needed to drive a CLI runner as far as its submit: a session, no free
    card (the spend-time check is a live REST call), and no polling."""
    monkeypatch.setattr(core, "_make_session", lambda token: mock_session)
    monkeypatch.setattr(cards_mod, "match_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(task_reads_mod, "_poll_task_status", lambda *a, **k: None)
    monkeypatch.setattr(task_reads_mod, "task_detail_gql", lambda *a, **k: {})
    monkeypatch.setattr(gen_cli_mod, "_maybe_dump_params", lambda *a, **k: None)
    monkeypatch.setattr(gen_cli_mod, "_download_video_task", lambda *a, **k: [])
    return mock_session


def _cli_args(tmp_path, **extra):
    """--params-json reaches the actual-submit branch with the fewest required args: every
    param-builder checks it first and returns it untouched (same trick
    dev/tests/test_read_only_cli_paths.py uses)."""
    base = dict(out=str(tmp_path), params_json='{"prompts": "test"}', confirm=True,
                task_id="", token=None, prompt="")
    base.update(extra)
    return SimpleNamespace(**base)


def _drive(fn, args):
    """Run a CLI runner far enough to submit.

    What happens AFTER the mutation -- polling, resolving media, downloading, cataloging --
    needs the whole collection stack and is not what this file is about, so a failure past
    the submit is ignored. That cannot make a test pass vacuously: `_assert_single_attempt`
    fails on an empty call list, and each caller asserts the createGenerationTask document
    itself was the thing recorded.
    """
    try:
        fn(args)
    except Exception:                                  # noqa: BLE001 -- see docstring
        pass


def _assert_single_attempt(calls, document=None):
    assert calls, "nothing was submitted -- the test never reached the mutation"
    if document is not None:
        assert any(c.query == document for c in calls), \
            "the expected mutation document was never submitted"
    for c in calls:
        assert c.retries == 0, (
            "a spending/account-mutating call was made with retries={!r} -- it must go "
            "through gql_mutate(), which hard-codes 0. A retry re-POSTs the mutation "
            "after a lost response and charges twice.".format(c.retries))
        assert c.verb == "mutate", (
            "a spending/account-mutating call reached the retry loop through "
            "PixAIClient.{}() -- it must ride gql_mutate()/client.mutate(), the road that "
            "offers no retries argument at all. The count was 0 here only because the "
            "document-aware default caught it.".format(c.verb))


# ---------------------------------------------------------------------------
# The helper itself
# ---------------------------------------------------------------------------

class TestGqlMutate:
    def test_hardcodes_no_retries(self, mock_session, gql_calls):
        core.gql_mutate(mock_session, "mutation { doThing { id } }", {"a": 1})
        assert [c.retries for c in gql_calls] == [0]

    def test_offers_no_way_to_ask_for_a_retry(self):
        """The knob is not merely defaulted safely -- it is not offered. A call site
        physically cannot opt back into the retrying behaviour through this helper."""
        assert "retries" not in inspect.signature(core.gql_mutate).parameters
        with pytest.raises(TypeError):
            core.gql_mutate(None, "mutation { x }", None, retries=3)

    def test_the_client_verb_underneath_offers_no_retries_either(self):
        """`gql_mutate` is a thin delegate onto `PixAIClient.mutate`, so the absence of the
        knob has to hold at the verb too -- otherwise the rule would live in the delegate
        and a caller reaching the client directly (the gallery, the fake, a future call
        site) could ask for the unsafe value after all."""
        assert "retries" not in inspect.signature(pixai_client_mod.PixAIClient.mutate).parameters
        with pytest.raises(TypeError):
            pixai_client_mod.PixAIClient(None).mutate("mutation { x }", None, retries=3)


class TestGqlAdhocDefault:
    """The backstop: even a call site that reaches past gql_mutate cannot inherit a retry
    for a mutation. Asserted at the network level -- the property is the number of POSTs,
    not the value of an argument."""

    def test_a_mutation_document_is_never_re_posted(self, mock_session, monkeypatch):
        monkeypatch.setattr(core.time, "sleep", lambda s: None)
        mock_session.post.side_effect = requests.ConnectionError("connection dropped")
        with pytest.raises(requests.RequestException):
            core.gql_adhoc(mock_session, gen_road_mod._GEN_MUTATION, {"parameters": {}})
        assert mock_session.post.call_count == 1, \
            "a createGenerationTask was POSTed more than once -- that is a second charge"

    def test_a_query_document_still_retries(self, mock_session, monkeypatch):
        """The other half: this must not turn into a blanket no-retry policy. Reads are
        idempotent and a flaky network should not fail them on the first blip."""
        monkeypatch.setattr(core.time, "sleep", lambda s: None)
        mock_session.post.side_effect = requests.ConnectionError("connection dropped")
        with pytest.raises(requests.RequestException):
            core.gql_adhoc(mock_session, "query { me { id } }")
        assert mock_session.post.call_count == 4          # the original + 3 retries

    def test_an_explicit_count_still_wins(self, mock_session, monkeypatch):
        monkeypatch.setattr(core.time, "sleep", lambda s: None)
        mock_session.post.side_effect = requests.ConnectionError("connection dropped")
        with pytest.raises(requests.RequestException):
            core.gql_adhoc(mock_session, "query { me { id } }", retries=0)
        assert mock_session.post.call_count == 1

    @pytest.mark.parametrize("document, is_mutation", [
        ("mutation createGenerationTask($p: JSONObject!) { x }", True),
        ("\n  mutation($id: ID!) { updateGenerationTask(id: $id) { id } }\n", True),
        ("MUTATION { x }", True),
        ("query { me { id } }", False),
        ("query($id:ID!){ artwork(id:$id){ views } }", False),
        ("", False),
        (None, False),
    ])
    def test_document_classification(self, document, is_mutation):
        assert pixai_client_mod._is_mutation_document(document) is is_mutation


# ---------------------------------------------------------------------------
# The spending paths
# ---------------------------------------------------------------------------

class TestSpendingPathsAreSingleAttempt:
    def test_submit_generation(self, mock_session, gql_calls, door_calls):
        """An image create rides the create door since 3.22 S3-image: one call, no GraphQL
        mutation at all."""
        gen_road_mod.submit_generation(mock_session, {"prompts": "a cat"})
        assert [c.kind for c in door_calls] == ["image"]
        assert not [c for c in gql_calls if c.verb == "mutate"]

    def test_send_run(self, mock_session, gql_calls, door_calls, monkeypatch):
        """Session M's run sender: N jobs, N creates, each through the one door that offers no
        retries (submit -> submit_generation(exact=True) -> core._create, 3.22)."""
        monkeypatch.setattr(cards_mod, "match_kaisuuken", lambda *a, **k: None)
        hooks = SimpleNamespace(sending=lambda cell: None, sent=lambda *a: None,
                                failed=lambda *a: None)
        jobs = [{"cell": k, "req": gen_road_mod.GenerationRequest(mode="image",
                                                          parameters={"prompts": p}),
                 "no_card": None} for k, p in enumerate(("a cat", "a dog"))]
        res = gen_road_mod.send_run(mock_session, jobs, hooks=hooks, gap_s=0)
        assert res["status"] == "sent"
        assert [c.kind for c in door_calls] == ["image", "image"]
        assert not [c for c in gql_calls if c.verb == "mutate"]

    def test_run_generate(self, tmp_path, cli_stubs, gql_calls, door_calls):
        _drive(gen_cli_mod.run_generate, _cli_args(tmp_path))
        assert [c.kind for c in door_calls] == ["image"]
        assert not [c for c in gql_calls if c.verb == "mutate"]

    def test_run_generate_video(self, tmp_path, cli_stubs, gql_calls):
        _drive(gen_cli_mod.run_generate_video, _cli_args(tmp_path, image="mid1"))
        _assert_single_attempt(gql_calls, gen_road_mod._GEN_MUTATION)

    def test_run_reference_video(self, tmp_path, cli_stubs, gql_calls):
        _drive(gen_cli_mod.run_reference_video, _cli_args(tmp_path, ref_image=["mid1"]))
        _assert_single_attempt(gql_calls, gen_road_mod._GEN_MUTATION)

    def test_run_edit_image(self, tmp_path, cli_stubs, gql_calls, door_calls):
        """The edit runner rides the create door since 3.22 S3-edit: one create, no GraphQL
        mutation."""
        _drive(gen_cli_mod.run_edit_image, _cli_args(
            tmp_path, edit_src=["mid1"], params_json='{"chat": {"prompts": "x", "mediaId": "1"}}'))
        assert [c.kind for c in door_calls] == ["edit"]
        assert not [c for c in gql_calls if c.verb == "mutate"]

    def test_upload_media(self, tmp_path, mock_session, gql_calls, monkeypatch):
        """An upload costs no credits, but it still mutates the account: re-registering
        the same externalId after a lost response can leave a second media object."""
        src = tmp_path / "ref.png"
        src.write_bytes(b"\x89PNG\r\n")
        put = SimpleNamespace(status_code=200, text="")
        monkeypatch.setattr(core.requests, "put", lambda *a, **k: put)
        assert core.upload_media(mock_session, str(src)) == "M1"
        _assert_single_attempt(gql_calls, core._UPLOAD_MEDIA_MUT)
        assert len(gql_calls) == 2                        # presign + register, both single

    def test_delete_batch_media(self, mock_session, gql_calls):
        """Already single-attempt before this pass -- pinned here too so the whole rule
        lives in one place, not split across two files."""
        cloud_delete_mod.delete_batch_media_gql(mock_session, "T1", "M1")
        _assert_single_attempt(gql_calls, cloud_delete_mod._DELETE_BATCH_MEDIA_MUT)

    def test_submit_training(self, mock_session, gql_calls, monkeypatch):
        """LoRA training spends real credits once the free-training quota is gone; a re-POST
        after a lost response would start (and pay for) a SECOND training. validate_training
        is stubbed so the test exercises the submit, not the (separately-tested) form rules."""
        monkeypatch.setattr(training_mod, "validate_training", lambda *a, **k: ["trigger"])
        training_mod.submit_training(mock_session, "base1", ["m1"], "Title", "trig", "style")
        _assert_single_attempt(gql_calls, training_mod._CREATE_TRAINING)

    def test_publish_artwork_from_task(self, mock_session, gql_calls):
        """No credits, but a re-POST after a lost response publishes the artwork twice."""
        account_api_mod.publish_artwork_from_task(mock_session, "task1")
        _assert_single_attempt(gql_calls, account_api_mod._PUBLISH_FROM_TASK)

    def test_update_artwork(self, mock_session, gql_calls):
        account_api_mod.update_artwork(mock_session, "art1", title="new title")
        _assert_single_attempt(gql_calls, account_api_mod._UPSERT_ARTWORK)

    def test_delete_artwork(self, mock_session, gql_calls):
        """A void mutation: success is the ABSENCE of an error, and a retry could delete
        something already gone."""
        account_api_mod.delete_artwork(mock_session, "art1")
        _assert_single_attempt(gql_calls, account_api_mod._DELETE_ARTWORK)


class TestNoSpendPathReachesPastTheHelper:
    """The structural half. The dynamic tests above only cover the paths someone thought
    to drive; this one reads the source of every declared spend path and fails if it POSTs
    a mutation through `gql_adhoc` instead of `gql_mutate` -- including through a branch no
    test happens to exercise (the inferenceProfile re-submit inside submit_generation is
    exactly such a branch)."""

    @pytest.mark.parametrize("name", SPEND_PATHS)
    def test_no_spend_path_calls_gql_adhoc_directly(self, name):
        src = inspect.getsource(_spend_path(name))
        assert not _CALLS_GQL_ADHOC.search(src), (
            "{}() calls gql_adhoc() directly -- a spending path must call gql_mutate(), "
            "which cannot be given a retry count. gql_adhoc's mutation-aware default "
            "would catch it, but the explicit helper is what makes the intent "
            "reviewable.".format(name))

    def test_every_declared_spend_path_exists(self):
        """A renamed-away entry in SPEND_PATHS would silently stop guarding anything."""
        for name in SPEND_PATHS:
            assert callable(_spend_path(name)), \
                "SPEND_PATHS names {}, which no longer exists".format(name)


class TestRestSpendPathsAreSingleAttempt:
    """The account-mutating paths that are NOT GraphQL. They all ride `_rest_post`, which is
    one bare `session.post` with no retry loop, and the session mounts no urllib3 Retry
    adapter (requests' default HTTPAdapter is max_retries=0) -- so they are single-attempt
    by construction. Pinned rather than assumed: a retry loop added to `_rest_post` later
    would silently make a Fix submit, a claim, and a contest entry double-fire. (The contest
    entry's single POST is pinned in dev/tests/test_contest.py::TestContestEnterIsGuarded.)"""

    def test_submit_fixer_posts_once(self, mock_session, door_calls, monkeypatch):
        """The Fix rides the create door since 3.22 S3-fix: one create, kind "fix"."""
        monkeypatch.setattr(core, "_rest_post", lambda *a, **k: pytest.fail("rest_post spend"))
        boxes = [{"x": 0, "y": 0, "width": 10, "height": 10, "tag": "hand"}]
        assert gen_road_mod.submit_fixer(mock_session, "mid1", boxes) == "T1"
        assert [c.kind for c in door_calls] == ["fix"]

    def test_the_routed_image_delete_has_no_retry_loop(self):
        """The per-image delete's WHOLE-TASK branch calls delete_task, which makes one
        rest_post (POST /v2/task/{id}/delete, #92) rather than riding gql_mutate -- so the
        no-retry rule cannot be inherited from the helper there. Read as structure, the same
        way _rest_post is below: neither the router nor the function it calls may put a loop
        around the post, and delete_task sends exactly one.

        Parsed rather than string-scanned, so prose in the docstrings ("for it", "wait for")
        cannot make this pass or fail by accident."""
        for fn, name in ((cloud_delete_mod.delete_image_routed, "delete_image_routed"),
                         (cloud_delete_mod.delete_task, "delete_task")):
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            loops = [n for n in ast.walk(tree)
                     if isinstance(n, (ast.For, ast.AsyncFor, ast.While))]
            assert not loops, (
                "{} grew a loop around a destructive delete -- a re-sent task delete "
                "can fire again against a task that already changed".format(name))
            # A comprehension or generator expression is a loop too: it can wrap the delete
            # call without any For/While statement.
            comps = [n for n in ast.walk(tree)
                     if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp,
                                       ast.GeneratorExp))]
            assert not comps, (
                "{} grew a loop around a destructive delete -- it must fire once".format(name))
        # ONE send in delete_task: a single rest_post call, and no raw session verb at all.
        # (`answer.get("success")` reads the parsed reply; it is not a send.)
        tree = ast.parse(textwrap.dedent(inspect.getsource(cloud_delete_mod.delete_task)))
        sends = [n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                 and n.func.attr in ("rest_post", "post", "get", "put", "patch", "delete",
                                     "request", "mutate", "query")
                 and not (isinstance(n.func.value, ast.Name) and n.func.value.id == "answer")]
        assert sends == ["rest_post"], sends

    @staticmethod
    def _real_function(module, name, cls=None):
        """The FunctionDef for `name` (a method of `cls` when given) parsed from `module`'s
        FILE on disk. Not inspect.getsource of the live object: dev/tests/conftest.py's
        autouse `_no_live_card_network` swaps core._rest_post/_rest_put/_rest_patch for a
        stub in every test, so getsource would read the stub, and getsource re-reads the
        file at the live object's old line numbers, so an edit mid-run could misread."""
        path = Path(module.__file__)
        scope = ast.parse(path.read_text(encoding="utf-8"), filename=str(path)).body
        if cls is not None:
            owner = next((n for n in scope if isinstance(n, ast.ClassDef) and n.name == cls),
                         None)
            assert owner is not None, "no class {} in {}".format(cls, path)
            scope = owner.body
        fn = next((n for n in scope if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n.name == name), None)
        assert fn is not None, "no function {} in {}".format(
            name if cls is None else cls + "." + name, path)
        return fn

    @pytest.mark.parametrize("verb", ["rest_post", "rest_put", "rest_patch"])
    def test_rest_post_has_no_retry_loop(self, verb):
        """Read the IMPLEMENTATION, not the delegate. `core._rest_post` (and _put, _patch) is
        one line that forwards to `PixAIClient.rest_post`, so scanning it alone would pass even
        if the real road grew a loop. Both are checked, from the module files on disk: the
        delegate must stay a delegate (one return of one forwarded call) and neither may hold
        a loop. The PUT carries the training routes' dataset/description saves, the PATCH the
        rebate join.

        Parsed rather than string-scanned, so prose in a docstring cannot make this pass or
        fail by accident, and a comprehension or generator expression counts as a loop too."""
        loop_kinds = (ast.For, ast.AsyncFor, ast.While,
                      ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        delegate = self._real_function(core, "_" + verb)
        real = self._real_function(pixai_client_mod, verb, cls="PixAIClient")
        for fn, name in ((delegate, "_" + verb), (real, "PixAIClient." + verb)):
            loops = [type(n).__name__ for n in ast.walk(fn) if isinstance(n, loop_kinds)]
            assert not loops, (
                "{} grew a retry loop ({}) -- submit_fixer and claim_reward would "
                "double-fire".format(name, loops))
        # The delegate: after its docstring, exactly `return <client>.<verb>(...)`, where
        # <client> is `_pixai_client._client_of(session)` -- one forwarded send, nothing else.
        body = delegate.body
        if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            body = body[1:]
        assert len(body) == 1 and isinstance(body[0], ast.Return), (
            "_{} is no longer a one-line delegate onto PixAIClient.{}".format(verb, verb))
        call = body[0].value
        assert (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                and call.func.attr == verb), ast.dump(call)
        client = call.func.value
        assert (isinstance(client, ast.Call) and isinstance(client.func, ast.Attribute)
                and client.func.attr == "_client_of"
                and isinstance(client.func.value, ast.Name)
                and client.func.value.id == "_pixai_client"), ast.dump(client)
        sends = [n for n in ast.walk(delegate) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr.startswith("rest_")]
        assert len(sends) == 1, "_{} forwards more than once".format(verb)

    def test_the_recipe_delete_verb_has_no_retry_loop(self):
        """Wave 2's recipe writes add the one /v2 DELETE (taking a recipe out of a set). It is
        its own verb in moonglade_recipes, not a PixAIClient method, so it is pinned here beside
        the others: one bare session.delete, no loop. Read from the module's source, because
        dev/tests/conftest.py blocks the live function for every test."""
        from moonglade import recipes as rec
        fn = next(n for n in ast.parse(inspect.getsource(rec)).body
                  if isinstance(n, ast.FunctionDef) and n.name == "_rest_delete")
        src = ast.get_source_segment(inspect.getsource(rec), fn)
        assert src.count(".delete(") == 1
        assert "for " not in src and "while " not in src, (
            "moonglade.recipes._rest_delete grew a retry loop")


class _Answer:
    def __init__(self, status=200, body=None):
        self.status_code, self._body = status, body if body is not None else {"data": {}}
        self.text, self.headers = "", {}

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class _Kw:
    """A session stand-in recording each verb's kwargs."""

    def __init__(self, status=200, body=None):
        self.calls, self._a = [], _Answer(status, body)
        self.headers, self.cookies = {}, requests.cookies.RequestsCookieJar()

    def _rec(self, verb, url, kw):
        self.calls.append((verb, url, kw))
        return self._a

    def post(self, url, **kw):
        return self._rec("POST", url, kw)

    def put(self, url, **kw):
        return self._rec("PUT", url, kw)

    def patch(self, url, **kw):
        return self._rec("PATCH", url, kw)

    def get(self, url, **kw):
        return self._rec("GET", url, kw)


class TestWritesNeverFollowRedirects:
    """#92 review F1, decided for every write: a write verb passes allow_redirects=False and
    a 3xx is an error with nothing re-sent. Following one would re-send a 307/308 -- body,
    Bearer and all -- to a URL the answering server chose, and turn a 301/302/303 into a GET
    whose answer then reads as success. Reads (rest_get, a query document) are unchanged."""

    @pytest.mark.parametrize("verb", ["rest_post", "rest_put", "rest_patch"])
    def test_each_rest_write_verb_refuses_to_follow(self, verb):
        s = _Kw(body={"ok": 1})
        assert getattr(pixai_client_mod.PixAIClient(s), verb)("/x", {}) == {"ok": 1}
        (_v, _u, kw), = s.calls
        assert kw["allow_redirects"] is False, verb

    @pytest.mark.parametrize("verb", ["rest_post", "rest_put", "rest_patch"])
    @pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
    def test_a_3xx_on_a_rest_write_is_an_error_after_one_call(self, verb, status):
        s = _Kw(status=status, body={"success": True})
        with pytest.raises(core.PixAIRestError) as ei:
            getattr(pixai_client_mod.PixAIClient(s), verb)("/x", {})
        assert ei.value.status == status and "nothing was re-sent" in str(ei.value)
        assert len(s.calls) == 1

    def test_the_mutation_road_refuses_to_follow(self):
        s = _Kw(body={"data": {"x": {"id": "1"}}})
        core.gql_mutate(s, "mutation { x { id } }")
        pixai_client_mod.PixAIClient(s).query("mutation { x { id } }")      # the backstop road too
        assert [kw["allow_redirects"] for _v, _u, kw in s.calls] == [False, False]

    @pytest.mark.parametrize("status", [302, 307])
    def test_a_3xx_on_a_mutation_is_an_error_after_one_post(self, status):
        s = _Kw(status=status, body={"data": {"createGenerationTask": {"id": "T1"}}})
        with pytest.raises(core.PixAIError, match="nothing was re-sent"):
            core.gql_mutate(s, gen_road_mod._GEN_MUTATION, {"parameters": {}})
        assert len(s.calls) == 1

    def test_the_renewal_refuses_to_follow(self):
        import base64
        import json as _json
        import time as _time

        def _b(d):
            return base64.urlsafe_b64encode(_json.dumps(d).encode()).decode().rstrip("=")
        cur = _b({"alg": "none"}) + "." + _b({"exp": int(_time.time()) + 86400,
                                              "iss": "pixai", "sub": "s"}) + ".x"
        s = _Kw(status=307)
        assert mirror_mod.refresh_jwt(s, current_jwt=cur) is None
        assert mirror_mod._refresh_last["reason"] == "http_307"
        (_v, _u, kw), = s.calls
        assert kw["allow_redirects"] is False

    def test_reads_are_unchanged(self):
        s = _Kw(body={"data": {"me": {"id": "1"}}})
        pixai_client_mod.PixAIClient(s).query("query { me { id } }")
        pixai_client_mod.PixAIClient(s).rest_get("/claim")
        assert ["allow_redirects" in kw for _v, _u, kw in s.calls] == [False, False]
