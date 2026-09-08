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
    and still print its 'Sync complete ...' line. (The line gained a tail saying WHICH
    ending happened on 2026-09-07, so this asserts the stem, not the old full stop.)"""
    calls = []
    _patch_chain(monkeypatch, calls, reconcile_exc=exc)
    monkeypatch.setattr(sys, "argv", ["prog", "--sync", "--out", str(tmp_path)])
    core.main()   # must NOT raise / sys.exit, regardless of the exception type
    assert calls == ["download", "backfill", "fix_models", "thumbnails", "reconcile"]
    out = capsys.readouterr().out
    assert "reconcile skipped" in out
    assert "Sync complete" in out


# ---------------------------------------------------------------------------
# Which ending did this Sync have? (owner report, 2026-09-07)
# ---------------------------------------------------------------------------

def _dl_result(**kw):
    """What run_download hands back now: the counters, plus how the walk ended."""
    base = {"ok": 0, "skip": 0, "missing": 0, "fail": 0,
            "pages": 0, "reached_end": False, "stopped_early": False, "end_known": False}
    base.update(kw)
    return base


def test_sync_that_reached_the_end_says_so_and_marks_the_first_sync(
        monkeypatch, tmp_path, capsys):
    """A walk that saw the oldest page reports the distance it covered, and only THEN is
    first_sync_done set -- the flag the achievement-toast gate (first_sync_complete) reads."""
    import moonglade_gallery as g
    calls = []
    _patch_chain(monkeypatch, calls)

    def _dl(args, progress=None):
        calls.append("download")
        core.mark_walk_end_reached(tmp_path)      # what the real walk does at the tail
        return _dl_result(pages=5, reached_end=True, end_known=True)
    monkeypatch.setattr(core, "run_download", _dl)
    monkeypatch.setattr(sys, "argv", ["prog", "--sync", "--out", str(tmp_path)])

    core.main()

    out = capsys.readouterr().out
    assert "Sync complete — walked to the end of your history (5 pages)." in out
    assert "caught up" not in out
    assert g.load_telemetry(tmp_path)["flags"].get("first_sync_done")


def test_sync_that_only_caught_up_says_so_and_withholds_the_first_sync_flag(
        monkeypatch, tmp_path, capsys):
    """The interrupted-first-backup shape: nothing has proven the end of history, so the
    line says 'caught up' and first_sync_done stays unset. Before the fix it was set on
    EVERY --sync exit, which told the gallery a mostly-empty library was fully backed up."""
    import moonglade_gallery as g
    calls = []
    _patch_chain(monkeypatch, calls)              # the stub returns None: no end reached
    monkeypatch.setattr(sys, "argv", ["prog", "--sync", "--out", str(tmp_path)])

    core.main()

    out = capsys.readouterr().out
    assert "Sync complete — caught up (nothing new in the last 2 pages)." in out
    assert "walked to the end" not in out
    assert not g.load_telemetry(tmp_path)["flags"].get("first_sync_done")


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
