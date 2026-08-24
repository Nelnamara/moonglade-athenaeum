"""--sync one-shot pipeline: main() must wire the full chain in order --
pull(+full-meta) -> backfill -> fix-models -> thumbnails -> reconcile -- set the
update/full-meta flags, and treat reconcile as advisory (a reconcile failure is a
warning, never a whole-sync failure). backfill precedes fix-models on purpose: it fills
model_id for rows that never saw detail, so fix-models then gets to relabel those same-run
rather than next-run (audit 2026-08-15). Fully mocked; no network, no disk beyond tmp."""
import sys

import pytest

import moonglade_backup as core


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
    assert calls == ["download", "backfill", "fix_models", "thumbnails", "reconcile"]


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
    assert calls == ["download", "backfill", "fix_models", "thumbnails", "reconcile"]
    out = capsys.readouterr().out
    assert "reconcile skipped" in out
    assert "Sync complete." in out


def test_update_builds_missing_thumbnails(monkeypatch, tmp_path):
    """A plain --update (not --sync) must backfill missing preview thumbnails. run_download
    writes image files + catalog rows but no thumbs, so main() now mirrors --sync's thumbnail
    tail on the plain-download path: build into out/gallery/thumbs straight from the catalog,
    and NOT force=True (rebuild only the missing thumbs -- cheap on a no-op update). --sync must
    still build exactly once: the plain-path addition sits behind the sync branch's own return,
    so the two never both fire for one command."""
    calls = []
    seen = {}
    _patch_chain(monkeypatch, calls)
    # Override the chain's thumbnail stub with one that also captures the exact call args,
    # so we can assert on the target dir and the force kwarg (the base stub discards **kw).
    def _thumbs(rows, out_dir, thumb_dir, **kw):
        calls.append("thumbnails")
        seen.update(rows=rows, out_dir=out_dir, thumb_dir=thumb_dir, kw=kw)
    monkeypatch.setattr(core, "build_thumbnails", _thumbs)

    # --- plain --update: download, then the thumbnail backfill -- and nothing else
    # (backfill / fix-models / reconcile are --sync-only). ---
    monkeypatch.setattr(sys, "argv", ["prog", "--update", "--out", str(tmp_path)])
    core.main()
    assert calls == ["download", "thumbnails"]
    assert seen["rows"][0]["media_id"] == "1"                       # fed straight from the catalog
    assert seen["out_dir"] == tmp_path
    assert seen["thumb_dir"] == tmp_path / "gallery" / "thumbs"     # canonical target
    assert seen["kw"].get("force") in (None, False)                # missing thumbs only, never a full rebuild

    # --- --sync must STILL build thumbnails exactly once (no double with the plain-path tail). ---
    calls.clear()
    monkeypatch.setattr(sys, "argv", ["prog", "--sync", "--out", str(tmp_path)])
    core.main()
    assert calls.count("thumbnails") == 1
    assert calls == ["download", "backfill", "fix_models", "thumbnails", "reconcile"]
