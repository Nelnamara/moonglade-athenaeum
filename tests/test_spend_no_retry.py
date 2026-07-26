"""A credit-spending mutation must be submitted EXACTLY ONCE.

`gql_adhoc` retries on a RequestException and on a 429/5xx. For a QUERY that is correct
and free. For `createGenerationTask` it is a double-spend: a lost RESPONSE is
indistinguishable from a lost REQUEST, so a read timeout, a dropped connection, or a
proxy's 502 arriving after PixAI already created and CHARGED for the task makes the retry
submit -- and pay for -- a second generation.

`delete_batch_media_gql` already recognised this and passed `retries=0` by hand
(tests/test_poll.py::test_delete_batch_media_never_retries). Every spending path was
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
import inspect
import re
from types import SimpleNamespace

import pytest
import requests

import moonglade_backup as core


# Every function that fires a credit-spending or account-mutating GraphQL call. When a new
# spend path ships, add it here -- test_no_spend_path_calls_gql_adhoc_directly is what
# makes forgetting loud instead of silent.
SPEND_PATHS = ("submit_generation", "run_generate", "run_generate_video",
               "run_reference_video", "run_edit_image", "upload_media",
               "delete_batch_media_gql")

# A real call, not a mention: the comments in these functions name gql_adhoc on purpose
# ("gql_mutate, never gql_adhoc") and must not trip the check.
_CALLS_GQL_ADHOC = re.compile(r"\bgql_adhoc\s*\(")


@pytest.fixture
def gql_calls(monkeypatch):
    """Record every `gql_adhoc` call the code under test makes and answer it with a
    plausible payload so the caller keeps going.

    The recorder's signature mirrors the real `gql_adhoc`'s, so a call that omits
    `retries` records None ("took the default") while a call through `gql_mutate` records
    0. Patching `gql_adhoc` -- not `gql_mutate` -- is deliberate: `gql_mutate` delegates
    through the module global, so this sees what the retry loop would ACTUALLY have been
    handed.
    """
    calls = []

    def _recorder(session, query, variables=None, retries=None):
        calls.append(SimpleNamespace(query=query, variables=variables, retries=retries))
        return {"createGenerationTask": {"id": "T1"},
                "updateGenerationTask": {"id": "T1"},
                "uploadMedia": {"uploadUrl": "https://s3.example/put",
                                "externalId": "E1", "mediaId": "M1"}}

    monkeypatch.setattr(core, "gql_adhoc", _recorder)
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
    tests/test_read_only_cli_paths.py uses)."""
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
    """The two spending paths that are NOT GraphQL. Both ride `_rest_post`, which is one
    bare `session.post` with no retry loop, and the session mounts no urllib3 Retry adapter
    (requests' default HTTPAdapter is max_retries=0) -- so they are single-attempt by
    construction. Pinned rather than assumed: a retry loop added to `_rest_post` later
    would silently make a Fix submit and a claim double-fire."""

    def test_submit_fixer_posts_once(self, mock_session, monkeypatch):
        posts = []
        monkeypatch.setattr(core, "_rest_post",
                            lambda s, p, b, **k: posts.append(p) or {"id": "T1"})
        boxes = [{"x": 0, "y": 0, "width": 10, "height": 10, "tag": "hand"}]
        assert core.submit_fixer(mock_session, "mid1", boxes) == "T1"
        assert posts == ["/task/fixer"]

    def test_rest_post_has_no_retry_loop(self):
        src = inspect.getsource(core._rest_post)
        assert "for " not in src and "while " not in src, \
            "_rest_post grew a retry loop -- submit_fixer and claim_reward would double-fire"
