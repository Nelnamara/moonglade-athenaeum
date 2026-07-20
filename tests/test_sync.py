"""--sync one-shot pipeline: main() must wire the full chain in order --
pull(+full-meta) -> fix-models -> backfill -> thumbnails -> reconcile -- set the
update/full-meta flags, and treat reconcile as advisory (a reconcile failure is a
warning, never a whole-sync failure). Fully mocked; no network, no disk beyond tmp."""
import sys

import pytest

import pixai_gallery_backup as core


def _patch_chain(monkeypatch, calls, *, reconcile_exc=None):
    """Replace every stage of the sync chain with a recorder so main() exercises only
    the wiring/order, not the real download/network."""
    monkeypatch.setattr(core, "run_download",
                        lambda args, progress=None: calls.append("download"))
    monkeypatch.setattr(core, "run_fix_models",
                        lambda args: calls.append("fix_models"))
    monkeypatch.setattr(core, "run_backfill_full_meta",
                        lambda args: calls.append("backfill"))
    # build_thumbnails is fed straight from the catalog; stub load_catalog so it has rows.
    monkeypatch.setattr(core, "load_catalog",
                        lambda db: [{"media_id": "1", "filename": "a_1.png"}])

    def _thumbs(rows, out_dir, thumb_dir, **kw):
        calls.append("thumbnails")
        # got the actual catalog rows, and the canonical gallery/thumbs target
        assert rows and rows[0]["media_id"] == "1"
        assert thumb_dir.name == "thumbs" and thumb_dir.parent.name == "gallery"
    monkeypatch.setattr(core, "build_thumbnails", _thumbs)

    def _recon(args):
        calls.append("reconcile")
        if reconcile_exc is not None:
            raise reconcile_exc
    monkeypatch.setattr(core, "run_reconcile_deleted", _recon)


def test_sync_runs_full_chain_in_order(monkeypatch, tmp_path):
    calls = []
    _patch_chain(monkeypatch, calls)
    monkeypatch.setattr(sys, "argv", ["prog", "--sync", "--out", str(tmp_path)])
    core.main()
    assert calls == ["download", "fix_models", "backfill", "thumbnails", "reconcile"]


def test_sync_sets_update_and_full_meta(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(core, "run_download", lambda args, progress=None:
                        seen.update(update=args.update, full_meta=args.full_meta))
    monkeypatch.setattr(core, "run_fix_models", lambda args: None)
    monkeypatch.setattr(core, "run_backfill_full_meta", lambda args: None)
    monkeypatch.setattr(core, "load_catalog", lambda db: [])
    monkeypatch.setattr(core, "build_thumbnails", lambda *a, **k: None)
    monkeypatch.setattr(core, "run_reconcile_deleted", lambda args: None)
    monkeypatch.setattr(sys, "argv", ["prog", "--sync", "--out", str(tmp_path)])
    core.main()
    assert seen == {"update": True, "full_meta": True}


@pytest.mark.parametrize("exc", [
    core.PixAIError("live feed returned no tasks"),
    # A bare network/HTTP error -- gql() re-raises requests exceptions that are NOT
    # PixAIError, so this case would crash the whole sync under a narrow `except PixAIError`.
    RuntimeError("transient network error during feed scan"),
], ids=["pixai-error", "non-pixai-error"])
def test_sync_survives_reconcile_failure(monkeypatch, tmp_path, capsys, exc):
    """A reconcile failure -- of ANY exception type -- must be downgraded to a warning:
    the backup already succeeded, so main() must return normally (not raise / sys.exit)
    and still print 'Sync complete.'."""
    calls = []
    _patch_chain(monkeypatch, calls, reconcile_exc=exc)
    monkeypatch.setattr(sys, "argv", ["prog", "--sync", "--out", str(tmp_path)])
    core.main()   # must NOT raise / sys.exit, regardless of the exception type
    assert calls == ["download", "fix_models", "backfill", "thumbnails", "reconcile"]
    out = capsys.readouterr().out
    assert "reconcile skipped" in out
    assert "Sync complete." in out
