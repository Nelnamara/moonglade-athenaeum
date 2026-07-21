"""CLI-side job logging: running the CLI straight from a terminal
(python pixai_gallery_backup.py --sync / --update / --generate / --generate-video)
must log into out_dir/jobs.jsonl the same way the Control Panel already does for
panel-spawned subprocess runs (job_id "panel-<uuid>" -- see pixai_gallery.py's
_panel_run/_panel_reader) and bulk-delete (job_id "bulkdel-<uuid>"). The CLI's own
flavor is "cli-<uuid>". Everything here drives core.main() directly (argv +
monkeypatch), analogous to tests/test_sync.py and
tests/test_purge.py::test_bulk_delete_async_logs_a_job_that_completes -- fully
mocked, no real PixAI network, no credits spent (conftest's autouse fixtures
already block the live /v2 REST + WebSocket surfaces; --generate without
--confirm never spends credits regardless)."""
import sys

import pytest

import pixai_gallery_backup as core


def _patch_sync_chain(monkeypatch, calls, *, download_exc=None):
    """Replace every stage of the --sync chain with a recorder, mirroring
    tests/test_sync.py's _patch_chain -- main() exercises only the job-logging
    wiring, never a real download/network."""
    def _dl(args, progress=None):
        calls.append("download")
        if download_exc is not None:
            raise download_exc
    monkeypatch.setattr(core, "run_download", _dl)
    monkeypatch.setattr(core, "run_fix_models", lambda args: calls.append("fix_models"))
    monkeypatch.setattr(core, "run_backfill_full_meta", lambda args: calls.append("backfill"))
    monkeypatch.setattr(core, "load_catalog", lambda db: [])
    monkeypatch.setattr(core, "build_thumbnails",
                        lambda *a, **k: calls.append("thumbnails"))
    monkeypatch.setattr(core, "run_reconcile_deleted", lambda args: calls.append("reconcile"))


def _cli_jobs(tmp_path, label=None):
    jobs = [j for j in core.read_jobs(tmp_path) if j.get("type") == "cli"]
    if label is not None:
        jobs = [j for j in jobs if j.get("label") == label]
    return jobs


# --------------------------------------------------------------------------- --sync

def test_sync_logs_a_cli_job_that_completes(monkeypatch, tmp_path):
    calls = []
    _patch_sync_chain(monkeypatch, calls)
    monkeypatch.setattr(sys, "argv", ["prog", "--sync", "--out", str(tmp_path)])

    core.main()

    assert calls == ["download", "fix_models", "backfill", "thumbnails", "reconcile"]
    jobs = _cli_jobs(tmp_path, "sync")
    assert len(jobs) == 1
    job = jobs[0]
    assert job["job_id"].startswith("cli-")           # the CLI's own job-id convention
    assert job["status"] == "done"


def test_sync_failure_logs_a_failed_cli_job_and_still_raises(monkeypatch, tmp_path):
    """A real failure must still surface exactly as before (sys.exit via PixAIError) --
    the job log is a pure side channel, never a behavior change."""
    calls = []
    _patch_sync_chain(monkeypatch, calls, download_exc=core.PixAIError("network blip"))
    monkeypatch.setattr(sys, "argv", ["prog", "--sync", "--out", str(tmp_path)])

    with pytest.raises(SystemExit):
        core.main()

    jobs = _cli_jobs(tmp_path, "sync")
    assert len(jobs) == 1
    assert jobs[0]["status"] == "failed"
    assert "network blip" in jobs[0]["error"]
    # fix_models/backfill/etc never ran -- the download step raised first
    assert calls == ["download"]


def test_sync_progress_ticks_feed_the_same_job(monkeypatch, tmp_path):
    """The download step's progress callback (args.progress, extended by _make_progress)
    optionally ALSO logs heartbeats into the same cli-<uuid> job -- not a second job."""
    def _dl(args, progress=None):
        assert callable(progress)
        progress(1, 2, 0)          # 50%
        progress(2, 2, 0)          # 100%
    monkeypatch.setattr(core, "run_download", _dl)
    monkeypatch.setattr(core, "run_fix_models", lambda args: None)
    monkeypatch.setattr(core, "run_backfill_full_meta", lambda args: None)
    monkeypatch.setattr(core, "load_catalog", lambda db: [])
    monkeypatch.setattr(core, "build_thumbnails", lambda *a, **k: None)
    monkeypatch.setattr(core, "run_reconcile_deleted", lambda args: None)
    monkeypatch.setattr(sys, "argv", ["prog", "--sync", "--out", str(tmp_path)])

    core.main()

    jobs = _cli_jobs(tmp_path, "sync")
    assert len(jobs) == 1                              # progress heartbeats, not new jobs
    assert jobs[0]["status"] == "done"


# --------------------------------------------------------------------------- --update

def test_update_logs_a_cli_job_labeled_update(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(core, "run_download",
                        lambda args: seen.update(update=args.update))
    monkeypatch.setattr(sys, "argv", ["prog", "--update", "--out", str(tmp_path)])

    core.main()

    assert seen == {"update": True}
    jobs = _cli_jobs(tmp_path, "update")
    assert len(jobs) == 1 and jobs[0]["status"] == "done"
    assert jobs[0]["job_id"].startswith("cli-")


def test_plain_download_logs_a_cli_job_labeled_download(monkeypatch, tmp_path):
    """No flags at all -> the same fallback branch as --update, labeled 'download'."""
    monkeypatch.setattr(core, "run_download", lambda args: None)
    monkeypatch.setattr(sys, "argv", ["prog", "--out", str(tmp_path)])

    core.main()

    jobs = _cli_jobs(tmp_path, "download")
    assert len(jobs) == 1 and jobs[0]["status"] == "done"


# --------------------------------------------------------------------------- --generate

def test_generate_preview_logs_a_cli_job_that_completes(monkeypatch, tmp_path):
    """--generate without --confirm is a preview: no network, no credits. conftest's
    autouse fixtures already keep the free-card note offline; nothing else to mock."""
    monkeypatch.setattr(sys, "argv",
                        ["prog", "--generate", "--prompt", "a quiet moonlit grove",
                         "--out", str(tmp_path)])

    core.main()

    jobs = _cli_jobs(tmp_path, "generate")
    assert len(jobs) == 1
    assert jobs[0]["job_id"].startswith("cli-")
    assert jobs[0]["status"] == "done"


def test_generate_failure_logs_a_failed_cli_job_and_still_raises(monkeypatch, tmp_path):
    """Force the submit itself to blow up (as if the API rejected the task) and confirm
    the job goes to 'failed' with the error message, while main() still raises exactly
    as it would without any job logging."""
    # --confirm submits, so the path builds a real session; stub it (no key in CI, and
    # conftest now forces _cfg empty locally too) so execution reaches the patched
    # gql_adhoc rather than dying at "No API key found" and logging THAT as the error.
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "gql_adhoc",
                        lambda *a, **k: (_ for _ in ()).throw(core.PixAIError("rejected")))
    monkeypatch.setattr(sys, "argv",
                        ["prog", "--generate", "--prompt", "p", "--confirm",
                         "--out", str(tmp_path)])

    with pytest.raises(SystemExit):
        core.main()

    jobs = _cli_jobs(tmp_path, "generate")
    assert len(jobs) == 1
    assert jobs[0]["status"] == "failed"
    assert "rejected" in jobs[0]["error"]


# --------------------------------------------------------------------------- --generate-video

def test_generate_video_preview_logs_a_cli_job_that_completes(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv",
                        ["prog", "--generate-video", "--image", "55", "--prompt", "p",
                         "--out", str(tmp_path)])

    core.main()

    jobs = _cli_jobs(tmp_path, "generate-video")
    assert len(jobs) == 1
    assert jobs[0]["job_id"].startswith("cli-")
    assert jobs[0]["status"] == "done"


# --------------------------------------------------------------------------- panel parity

def test_panel_spawned_run_does_not_double_log_a_cli_job(monkeypatch, tmp_path):
    """Under the Control Panel (MOONGLADE_PROGRESS=1) the panel already logs its OWN
    'panel-<uuid>' job for this exact subprocess (see pixai_gallery.py's _panel_run).
    The CLI must NOT also create a 'cli-<uuid>' job here, or the Jobs card would show
    two entries for one real run."""
    calls = []
    _patch_sync_chain(monkeypatch, calls)
    monkeypatch.setenv("MOONGLADE_PROGRESS", "1")
    monkeypatch.setattr(sys, "argv", ["prog", "--sync", "--out", str(tmp_path)])

    core.main()

    assert calls == ["download", "fix_models", "backfill", "thumbnails", "reconcile"]
    assert core.read_jobs(tmp_path) == []               # no cli-* job written


# --------------------------------------------------------------------------- catalog-stats
# (a read-only command NOT in the instrumented set -- confirms this feature is additive
# and scoped, not a blanket "every command gets a job" change)

def test_catalog_stats_is_not_instrumented(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "run_catalog_stats", lambda args: None)
    monkeypatch.setattr(sys, "argv", ["prog", "--catalog-stats", "--out", str(tmp_path)])

    core.main()

    assert core.read_jobs(tmp_path) == []
