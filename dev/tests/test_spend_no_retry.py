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
from types import SimpleNamespace

import pytest
import requests

from moonglade import backup as core


# Every function that fires a credit-spending or account-mutating GraphQL call. When a new
# spend path ships, add it here -- test_no_spend_path_calls_gql_adhoc_directly is what
# makes forgetting loud instead of silent.
SPEND_PATHS = ("submit_generation", "run_generate", "run_generate_video",
               "run_reference_video", "run_edit_image", "upload_media",
               "delete_batch_media_gql",
               # The per-image delete's router (2026-09-06): it fires one of the two
               # delete mutations after reading the live task, so it is an
               # account-mutating path in its own right.
               "delete_image_routed",
               # LoRA training: spends real credits once the free-training quota is
               # gone, and a re-POST would start a SECOND training (2026-08-06).
               "submit_training",
               # Session J's two GraphQL writers (waves 2+3 review, F5): the advanced
               # draft (createTrainingTask -- a re-POST would make a second draft) and
               # making a LoRA public (upsertGenerationModel -- irreversible).
               "create_advanced_training_draft", "make_model_public",
               # Artwork mutations: no credits, but they change the public account and
               # a retry would publish twice / delete something already gone.
               "publish_artwork_from_task", "update_artwork", "delete_artwork",
               # Session M's run sender (2026-09-29): up to 24 generations, one after
               # another, each through submit() -> submit_generation(exact=True).
               "send_run")

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
    real_query = core.PixAIClient.query
    real_mutate = core.PixAIClient.mutate
    box = {"verb": None}

    def _query(self, document, variables=None, retries=None):
        box["verb"] = "query"
        try:
            return real_query(self, document, variables, retries)
        finally:
            box["verb"] = None

    def _mutate(self, document, variables=None):
        box["verb"] = "mutate"
        try:
            return real_mutate(self, document, variables)
        finally:
            box["verb"] = None

    def _recorder(self, document, variables, retries):
        calls.append(SimpleNamespace(query=document, variables=variables,
                                     retries=retries, verb=box["verb"]))
        return _STUB_PAYLOAD

    monkeypatch.setattr(core.PixAIClient, "query", _query)
    monkeypatch.setattr(core.PixAIClient, "mutate", _mutate)
    monkeypatch.setattr(core.PixAIClient, "_graphql_post", _recorder)
    return calls


@pytest.fixture
def cli_stubs(mock_session, monkeypatch):
    """The minimum needed to drive a CLI runner as far as its submit: a session, no free
    card (the spend-time check is a live REST call), and no polling."""
    monkeypatch.setattr(core, "_make_session", lambda token: mock_session)
    monkeypatch.setattr(core, "match_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "_poll_task_status", lambda *a, **k: None)
    monkeypatch.setattr(core, "task_detail_gql", lambda *a, **k: {})
    monkeypatch.setattr(core, "_maybe_dump_params", lambda *a, **k: None)
    monkeypatch.setattr(core, "_download_video_task", lambda *a, **k: [])
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
        assert "retries" not in inspect.signature(core.PixAIClient.mutate).parameters
        with pytest.raises(TypeError):
            core.PixAIClient(None).mutate("mutation { x }", None, retries=3)


class TestGqlAdhocDefault:
    """The backstop: even a call site that reaches past gql_mutate cannot inherit a retry
    for a mutation. Asserted at the network level -- the property is the number of POSTs,
    not the value of an argument."""

    def test_a_mutation_document_is_never_re_posted(self, mock_session, monkeypatch):
        monkeypatch.setattr(core.time, "sleep", lambda s: None)
        mock_session.post.side_effect = requests.ConnectionError("connection dropped")
        with pytest.raises(requests.RequestException):
            core.gql_adhoc(mock_session, core._GEN_MUTATION, {"parameters": {}})
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
        assert core._is_mutation_document(document) is is_mutation


# ---------------------------------------------------------------------------
# The spending paths
# ---------------------------------------------------------------------------

class TestSpendingPathsAreSingleAttempt:
    def test_submit_generation(self, mock_session, gql_calls):
        core.submit_generation(mock_session, {"prompts": "a cat"})
        _assert_single_attempt(gql_calls, core._GEN_MUTATION)

    def test_send_run(self, mock_session, gql_calls, monkeypatch):
        """Session M's run sender: N jobs, N mutations, each single-attempt through the one
        verb that offers no retries (submit -> submit_generation(exact=True) -> gql_mutate)."""
        monkeypatch.setattr(core, "match_kaisuuken", lambda *a, **k: None)
        hooks = SimpleNamespace(sending=lambda cell: None, sent=lambda *a: None,
                                failed=lambda *a: None)
        jobs = [{"cell": k, "req": core.GenerationRequest(mode="image",
                                                          parameters={"prompts": p}),
                 "no_card": None} for k, p in enumerate(("a cat", "a dog"))]
        res = core.send_run(mock_session, jobs, hooks=hooks, gap_s=0)
        assert res["status"] == "sent"
        _assert_single_attempt(gql_calls, core._GEN_MUTATION)
        assert len(gql_calls) == 2

    def test_run_generate(self, tmp_path, cli_stubs, gql_calls):
        _drive(core.run_generate, _cli_args(tmp_path))
        _assert_single_attempt(gql_calls, core._GEN_MUTATION)

    def test_run_generate_video(self, tmp_path, cli_stubs, gql_calls):
        _drive(core.run_generate_video, _cli_args(tmp_path, image="mid1"))
        _assert_single_attempt(gql_calls, core._GEN_MUTATION)

    def test_run_reference_video(self, tmp_path, cli_stubs, gql_calls):
        _drive(core.run_reference_video, _cli_args(tmp_path, ref_image=["mid1"]))
        _assert_single_attempt(gql_calls, core._GEN_MUTATION)

    def test_run_edit_image(self, tmp_path, cli_stubs, gql_calls):
        _drive(core.run_edit_image, _cli_args(tmp_path, edit_src=["mid1"]))
        _assert_single_attempt(gql_calls, core._GEN_MUTATION)

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
        core.delete_batch_media_gql(mock_session, "T1", "M1")
        _assert_single_attempt(gql_calls, core._DELETE_BATCH_MEDIA_MUT)

    def test_submit_training(self, mock_session, gql_calls, monkeypatch):
        """LoRA training spends real credits once the free-training quota is gone; a re-POST
        after a lost response would start (and pay for) a SECOND training. validate_training
        is stubbed so the test exercises the submit, not the (separately-tested) form rules."""
        monkeypatch.setattr(core, "validate_training", lambda *a, **k: ["trigger"])
        core.submit_training(mock_session, "base1", ["m1"], "Title", "trig", "style")
        _assert_single_attempt(gql_calls, core._CREATE_TRAINING)

    def test_publish_artwork_from_task(self, mock_session, gql_calls):
        """No credits, but a re-POST after a lost response publishes the artwork twice."""
        core.publish_artwork_from_task(mock_session, "task1")
        _assert_single_attempt(gql_calls, core._PUBLISH_FROM_TASK)

    def test_update_artwork(self, mock_session, gql_calls):
        core.update_artwork(mock_session, "art1", title="new title")
        _assert_single_attempt(gql_calls, core._UPSERT_ARTWORK)

    def test_delete_artwork(self, mock_session, gql_calls):
        """Like deleteGenerationTask: success is the ABSENCE of an error, and a retry could
        delete something already gone."""
        core.delete_artwork(mock_session, "art1")
        _assert_single_attempt(gql_calls, core._DELETE_ARTWORK)


class TestNoSpendPathReachesPastTheHelper:
    """The structural half. The dynamic tests above only cover the paths someone thought
    to drive; this one reads the source of every declared spend path and fails if it POSTs
    a mutation through `gql_adhoc` instead of `gql_mutate` -- including through a branch no
    test happens to exercise (the inferenceProfile re-submit inside submit_generation is
    exactly such a branch)."""

    @pytest.mark.parametrize("name", SPEND_PATHS)
    def test_no_spend_path_calls_gql_adhoc_directly(self, name):
        src = inspect.getsource(getattr(core, name))
        assert not _CALLS_GQL_ADHOC.search(src), (
            "{}() calls gql_adhoc() directly -- a spending path must call gql_mutate(), "
            "which cannot be given a retry count. gql_adhoc's mutation-aware default "
            "would catch it, but the explicit helper is what makes the intent "
            "reviewable.".format(name))

    def test_every_declared_spend_path_exists(self):
        """A renamed-away entry in SPEND_PATHS would silently stop guarding anything."""
        for name in SPEND_PATHS:
            assert callable(getattr(core, name, None)), \
                "SPEND_PATHS names {}, which no longer exists".format(name)


class TestRestSpendPathsAreSingleAttempt:
    """The account-mutating paths that are NOT GraphQL. They all ride `_rest_post`, which is
    one bare `session.post` with no retry loop, and the session mounts no urllib3 Retry
    adapter (requests' default HTTPAdapter is max_retries=0) -- so they are single-attempt
    by construction. Pinned rather than assumed: a retry loop added to `_rest_post` later
    would silently make a Fix submit, a claim, and a contest entry double-fire. (The contest
    entry's single POST is pinned in dev/tests/test_contest.py::TestContestEnterIsGuarded.)"""

    def test_submit_fixer_posts_once(self, mock_session, monkeypatch):
        posts = []
        monkeypatch.setattr(core, "_rest_post",
                            lambda s, p, b, **k: posts.append(p) or {"id": "T1"})
        boxes = [{"x": 0, "y": 0, "width": 10, "height": 10, "tag": "hand"}]
        assert core.submit_fixer(mock_session, "mid1", boxes) == "T1"
        assert posts == ["/task/fixer"]

    def test_the_routed_image_delete_has_no_retry_loop(self):
        """The per-image delete's WHOLE-TASK branch calls delete_task_gql, which hand-rolls
        one session.post rather than riding gql_mutate -- so the no-retry rule cannot be
        inherited from the helper there. Read as structure, the same way _rest_post is
        above: neither the router nor the function it calls may put a loop around the post.

        Parsed rather than string-scanned, so prose in the docstrings ("for it", "wait for")
        cannot make this pass or fail by accident."""
        for fn, name in ((core.delete_image_routed, "delete_image_routed"),
                         (core.delete_task_gql, "delete_task_gql")):
            tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
            loops = [n for n in ast.walk(tree)
                     if isinstance(n, (ast.For, ast.AsyncFor, ast.While))]
            assert not loops, (
                "{} grew a loop around a destructive delete -- a re-sent deleteGeneration"
                "Task can fire again against a task that already changed".format(name))
        # A comprehension or generator expression is a loop too: it can wrap the delete
        # call without any For/While statement. Checked on the router only -- it is the
        # function that picks the branch and must fire exactly one of them.
        routed = ast.parse(textwrap.dedent(inspect.getsource(core.delete_image_routed)))
        comps = [n for n in ast.walk(routed)
                 if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp))]
        assert not comps, (
            "delete_image_routed grew a loop around a destructive delete -- it must fire once")

    def test_rest_post_has_no_retry_loop(self):
        """Read the IMPLEMENTATION, not the delegate. `core._rest_post` is now one line
        that forwards to `PixAIClient.rest_post`, so scanning it alone would pass even if
        the real road grew a loop. Both are checked: the delegate must stay a delegate and
        the verb must stay single-attempt."""
        for fn, name in ((core._rest_post, "_rest_post"),
                         (core.PixAIClient.rest_post, "PixAIClient.rest_post"),
                         # the training routes' dataset/description PUT and the rebate PATCH
                         (core._rest_put, "_rest_put"),
                         (core.PixAIClient.rest_put, "PixAIClient.rest_put"),
                         (core._rest_patch, "_rest_patch"),
                         (core.PixAIClient.rest_patch, "PixAIClient.rest_patch")):
            src = inspect.getsource(fn)
            assert "for " not in src and "while " not in src, (
                "{} grew a retry loop -- submit_fixer and claim_reward would "
                "double-fire".format(name))

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
