"""Concurrent generations (owner-approved 2026-07-23), gallery side -- pilot coverage.

The classic drawer's inline runTask() died with the classic cut (2026-08-08), but the
guarantees it carried did not: gallery/src/gen/submitTask.js is its explicit port ("The
classic has runTask; this is its port") -- ONE shared submit path for /api/generate,
/api/edit and /api/fix -- with useResultLines() as the per-submission result-line side,
and FixTab.jsx carrying the classic fix()'s spend confirm. These tests keep the same
guarantees pinned on those surviving sources, with the same source-level string technique
the old template checks used (no JS runtime in this suite):

- the busy latch frees the moment the SERVER ANSWERS the submit (accepted or rejected),
  never inside Jobs.track's later completion tick;
- each submission owns its OWN appended result line; nothing rewrites the whole strip;
- the Fix spend confirm still gates every /api/fix submission;
- every submitting surface still routes through the one shared submitTask().

(The classic-only "draw a box first" DOM-overwrite hazard died with the classic cut:
FixTab renders its no-boxes hint as separate React state, structurally unable to wipe
the result lines, so that test went with the template. The shared <mg-generate-drawer>'s
own copy of this concurrency behavior keeps its own separate coverage:
loom/test/mg-generate-drawer-concurrent.test.js.)
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _src(rel):
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_submit_task_resolves_on_submit_answer_not_on_task_completion():
    """A caller's `await submitTask(...)` must finish (freeing its busy latch) the moment
    the server answers the submit -- success OR rejection -- not when Jobs.track's poll
    reaches a terminal phase."""
    src = _src("gallery/src/gen/submitTask.js")
    assert "window.Jobs.track(" in src, "submitTask no longer hands polling off to Jobs.track"
    # Tracking is registration only -- awaiting it would hold the caller's busy latch
    # until the task completed, resurrecting the old single-flight lock.
    assert "await window.Jobs.track" not in src, (
        "submitTask awaits Jobs.track -- the button would stay locked until the whole "
        "task finished instead of freeing on the submit answer")
    # A rejected submit must RESOLVE (return null), not throw -- otherwise the caller's
    # `await` raises past its unlock lines and the button stays disabled forever.
    i = src.index("if (d.error || !d.task_id)")
    assert "return null;" in src[i:i + 250], (
        "the rejected-submit branch no longer resolves with null -- a rejected submit "
        "could leave the caller's button disabled forever")
    # The completion callback (the poll side) must not be what frees the button.
    track_cb = src[src.index("window.Jobs.track("):]
    assert "setBusy" not in track_cb and "busyRef" not in track_cb, (
        "submitTask's Jobs.track callback touches the busy latch -- the old "
        "disabled-until-completion lock is back")
    # And the generate caller frees its latch RIGHT AFTER the awaited submit answer.
    gen = _src("gallery/src/gen/useGenerate.js")
    j = gen.index('await submitTask("/api/generate"')
    after = gen[j:j + 250]
    assert "busyRef.current = false" in after and "setBusy(false)" in after, (
        "useGenerate no longer unlocks immediately after the awaited submit answer")


def test_result_lines_append_per_submission_and_patch_only_their_own_line():
    """Two submissions in flight at once must not fight over one shared result strip --
    useResultLines() appends a line per open() and its emit patches ONLY that line."""
    src = _src("gallery/src/gen/submitTask.js")
    i = src.index("export function useResultLines()")
    fn = src[i:]
    assert "old.concat([{ id" in fn, (
        "useResultLines no longer APPENDS a per-submission line -- concurrent tasks "
        "would fight over one shared result element")
    assert "x.id === id ? { ...x, ...patch } : x" in fn, (
        "emit no longer patches only its OWN line by id -- a second submission's "
        "updates could clobber the first task's still-live status/result")
    assert "innerHTML" not in src, (
        "submitTask.js rewrites raw innerHTML somewhere -- a second submission could "
        "wipe the first task's still-live status/result")


def test_fix_spend_confirm_still_gates_each_submission():
    """No-regression: a Fix can never be covered by a free card, so FixTab's
    window.confirm is a real spend gate (see FixTab.jsx's own header comment).
    Concurrency must never bypass a spend gate -- the confirm still runs, and still
    bails out, before every submitTask('/api/fix') submission."""
    src = _src("gallery/src/components/FixTab.jsx")
    assert "window.confirm(" in src, "the Fix spend confirm is gone"
    assert src.index("window.confirm(") < src.index('submitTask("/api/fix"'), (
        "the Fix spend confirm no longer gates the submission")
    gate = src[src.index("if (!window.confirm("):src.index('submitTask("/api/fix"')]
    assert ") return;" in gate, (
        "declining the Fix spend confirm no longer bails out before the submission")


def test_generate_edit_fix_all_still_route_through_the_shared_submit_task():
    """No-regression: every submitting surface in the pilot must still go through the one
    shared submitTask() the guarantees above cover -- if any of them grew its own bespoke
    fetch to a spend route, it would silently lose the concurrency fix (and the no-retry /
    spend-gate guarantees) above."""
    assert 'submitTask("/api/generate"' in _src("gallery/src/gen/useGenerate.js")
    assert 'submitTask("/api/edit"' in _src("gallery/src/components/EditTab.jsx")
    assert 'submitTask("/api/edit"' in _src("gallery/src/gen/useEditGenerate.js")
    assert 'submitTask("/api/fix"' in _src("gallery/src/components/FixTab.jsx")
    # No surface owns a bespoke fetch to a spend route -- the ONLY fetch of these
    # routes is submitTask's own fetch(route).
    #
    # ONE deliberate exception: UpscalePanel.jsx (2026-08-08 port of static/mg-upscale-panel.js).
    # The image-view upscale is a one-shot MODAL that closes on success and shows its own inline
    # error, so it does not fit submitTask's openLine/result-line contract. It posts the SAME
    # /api/generate (server-side READ_ONLY / free-card / job-tracker guards all apply) and carries
    # its OWN equivalents of the client guarantees this test protects: a busyRef double-submit
    # latch, a canSubmit spend-gate, and a single no-retry fetch. The vanilla did exactly this;
    # it was invisible here only because it lived in static/ (this test globs gallery/src). If a
    # future pass wants the shared path anyway, route it through submitTask and drop this skip.
    bespoke = re.compile(r'fetch\(\s*["\']/api/(?:generate|edit|fix)["\']')
    exempt = {(_ROOT / "gallery" / "src" / "components" / "UpscalePanel.jsx").resolve()}
    for f in (_ROOT / "gallery" / "src").rglob("*.js*"):
        if f.resolve() in exempt:
            continue
        assert not bespoke.search(f.read_text(encoding="utf-8")), (
            "bespoke spend-route fetch outside submitTask: " + str(f))
