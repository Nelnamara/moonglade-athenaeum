"""READ_ONLY on the five CLI generation entry points -- the gap tests/test_read_only.py's
own docstring didn't know it had.

That file's docstring said "all four choke points... are covered -- both the CLI and the
web app's generate/edit/enhance/fix/delete/claim routes funnel through these same four
functions." That was true for the web app and false for the CLI: run_generate,
run_generate_video, run_reference_video, run_enhance and run_edit_image each build their
OWN gql_adhoc call instead of calling through submit_generation()/submit_fixer(), so none
of them ever called _check_read_only.

Found 2026-07-21 by a 33-agent post-release audit, proved dynamically here rather than
asserted: with READ_ONLY=True and the CLI's own --confirm passed, all five used to reach
the mutation, and the free-card check (_apply_kaisuuken) fired FIRST -- a live network call
before any guard ran at all. Every test below drives the real CLI entry point, the same way
tests/test_read_only.py's own delete-task test does, and the property that matters is not
"does it raise" but that mock_session.post is NEVER CALLED -- no network call fires, from
_apply_kaisuuken, an upload, or the mutation itself.

Update 2026-07-24: run_generate's OWN reason for building a separate gql_adhoc call (a
one-off inferenceProfile retry submit_generation() didn't have) is gone -- that retry now
lives in submit_generation() itself, and run_generate calls through it for the mutation.
It still needs the direct _check_read_only call below it though, ahead of
_apply_kaisuuken's free-card network call, which fires before submit_generation() is ever
reached -- see _check_read_only's own docstring. The other four runners are unchanged.

All five use --params-json to reach the actual-submit branch with the fewest required
args -- every one of the five param-builders checks it first and returns immediately,
which is also why real callers can use it to recover a task's exact submit shape for free.
"""
from types import SimpleNamespace

import pytest

import pixai_gallery_backup as core


def _args(tmp_path, **extra):
    base = dict(out=str(tmp_path), params_json='{"prompts": "test"}', confirm=True,
                task_id="", token=None)
    base.update(extra)
    return SimpleNamespace(**base)


class TestRunGenerateReadOnly:
    def test_blocked_when_read_only(self, tmp_path, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        monkeypatch.setattr(core, "_make_session", lambda token: mock_session)
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.run_generate(_args(tmp_path))
        mock_session.post.assert_not_called()

    def test_allowed_when_not_read_only(self, tmp_path, mock_session, mocker, monkeypatch):
        """The guard must not become a blanket refusal -- a normal --confirm run with
        READ_ONLY unset (the default) has to keep reaching the network.

        _poll_task_status is mocked directly rather than fed a fake 'completed' response
        through mock_session.post: that response would also answer the SUBMIT call (both
        ride the same session.post), so a real run here spun in _poll_task_status's actual
        time.sleep() loop for the real 300s timeout before this was caught. Mocking the
        poll is also the right abstraction level -- this test's only job is proving the
        submit reaches the network when READ_ONLY is off, not exercising poll behaviour."""
        monkeypatch.setattr(core, "READ_ONLY", False)
        monkeypatch.setattr(core, "_make_session", lambda token: mock_session)
        # This test's job is the READ_ONLY gate, not free-card matching -- stub the
        # auto-match directly (no card) rather than let it hit conftest's blocked
        # _rest_post, which _apply_kaisuuken now correctly treats as a real failure
        # and aborts on (see match_kaisuuken/_apply_kaisuuken, fail-open fix).
        monkeypatch.setattr(core, "match_kaisuuken", lambda *a, **k: None)
        resp = mocker.MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"data": {"createGenerationTask": {"id": "t1"}}}
        mock_session.post.return_value = resp
        monkeypatch.setattr(core, "_poll_task_status", lambda *a, **k: None)
        monkeypatch.setattr(core, "task_detail_gql", lambda *a, **k: {"outputs": {"mediaId": "m1"}})
        monkeypatch.setattr(core, "_download_image_task", lambda *a, **k: [])
        core.run_generate(_args(tmp_path))
        mock_session.post.assert_called()


class TestRunGenerateVideoReadOnly:
    def test_blocked_when_read_only(self, tmp_path, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        monkeypatch.setattr(core, "_make_session", lambda token: mock_session)
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.run_generate_video(_args(tmp_path, image="mid1"))
        mock_session.post.assert_not_called()


class TestRunReferenceVideoReadOnly:
    def test_blocked_when_read_only(self, tmp_path, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        monkeypatch.setattr(core, "_make_session", lambda token: mock_session)
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.run_reference_video(_args(tmp_path))
        mock_session.post.assert_not_called()

    def test_blocked_before_resolving_local_refs(self, tmp_path, mock_session, monkeypatch):
        """The stricter claim: even a LOCAL FILE reference (which would upload -- a genuine
        network call) must not resolve before the guard. Omit --params-json so the function
        takes the _resolve_refs() path instead of the override shortcut."""
        monkeypatch.setattr(core, "READ_ONLY", True)
        monkeypatch.setattr(core, "_make_session", lambda token: mock_session)
        local_file = tmp_path / "ref.png"
        local_file.write_bytes(b"\x89PNG\r\n")
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.run_reference_video(_args(tmp_path, params_json="",
                                            ref_image=[str(local_file)]))
        mock_session.post.assert_not_called()


class TestRunEnhanceReadOnly:
    def test_blocked_when_read_only(self, tmp_path, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        monkeypatch.setattr(core, "_make_session", lambda token: mock_session)
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.run_enhance(_args(tmp_path))
        mock_session.post.assert_not_called()

    def test_blocked_before_uploading_local_source(self, tmp_path, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        monkeypatch.setattr(core, "_make_session", lambda token: mock_session)
        local_file = tmp_path / "src.png"
        local_file.write_bytes(b"\x89PNG\r\n")
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.run_enhance(_args(tmp_path, params_json="", src=str(local_file),
                                    workflow_id="wf1"))
        mock_session.post.assert_not_called()


class TestRunEditImageReadOnly:
    def test_blocked_when_read_only(self, tmp_path, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        monkeypatch.setattr(core, "_make_session", lambda token: mock_session)
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.run_edit_image(_args(tmp_path))
        mock_session.post.assert_not_called()

    def test_blocked_before_uploading_local_source(self, tmp_path, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        monkeypatch.setattr(core, "_make_session", lambda token: mock_session)
        local_file = tmp_path / "src.png"
        local_file.write_bytes(b"\x89PNG\r\n")
        with pytest.raises(core.PixAIError, match="READ_ONLY"):
            core.run_edit_image(_args(tmp_path, params_json="", edit_src=[str(local_file)]))
        mock_session.post.assert_not_called()


class TestReadOnlyStillAllowsFreeTaskRecovery:
    """--task-id recovery is free (no submit, no credits) and must stay reachable under
    READ_ONLY -- the guard is scoped to the SUBMIT branch (the `else:` where existing_task
    is falsy), never the recovery branch."""

    def test_generate_video_recovery_not_blocked(self, tmp_path, mock_session, monkeypatch):
        monkeypatch.setattr(core, "READ_ONLY", True)
        monkeypatch.setattr(core, "_make_session", lambda token: mock_session)
        monkeypatch.setattr(core, "task_detail_gql", lambda *a, **k: {})
        monkeypatch.setattr(core, "_maybe_dump_params", lambda *a, **k: None)
        monkeypatch.setattr(core, "_download_video_task", lambda *a, **k: [])
        # No PixAIError -- recovery must proceed even with READ_ONLY set.
        core.run_generate_video(_args(tmp_path, task_id="existing123", image=""))
        mock_session.post.assert_not_called()  # recovery is a GET-shaped read, not a POST
