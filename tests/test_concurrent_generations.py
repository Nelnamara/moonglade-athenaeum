"""Concurrent generations (owner-approved 2026-07-23), gallery side. Every gen panel's Go
button used to disable at submit and stay disabled until the whole task finished -- but
PixAI itself runs tasks in parallel, and Jobs.track (static/mg-notify.js) already polls
each task_id independently. runTask() now frees the button the moment the SERVER ANSWERS
the submit (accepted or rejected), not when Jobs.track's poll reaches a terminal phase, and
each submission gets its OWN line appended into the result strip instead of one shared
innerHTML a second submission would overwrite. Generate/Edit/Enhance/Fix all share this one
runTask(), so fixing it here covers all four. Template-level checks on the embedded JS, the
same technique test_web_pick.py's B4 drawer-wiring tests use (no JS runtime in this suite).

(The shared <mg-generate-drawer>'s own concurrency -- per-task poll registry, unlock on
accept, per-submission result lines -- is a separate file with its own test coverage:
loom/test/mg-generate-drawer-concurrent.test.js.)
"""
from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _authed_client(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00"),
    ])
    return login_client(tmp_path)


def _run_task_fn(html):
    """The runTask() source as served -- generate() is the next function in the module."""
    i = html.index("function runTask(")
    j = html.index("function generate()", i)
    return html[i:j]


def test_run_task_unlocks_on_submit_answer_not_on_task_completion(tmp_path):
    """The button must free up the moment fetch() resolves (the server answered the
    submit), not inside Jobs.track's callback (which only fires on a later poll tick)."""
    html = _authed_client(tmp_path).get("/").get_data(as_text=True)
    fn = _run_task_fn(html)
    assert "Jobs.track(" in fn, "runTask no longer hands polling off to Jobs.track"
    before_track = fn[: fn.index("Jobs.track(")]
    # unlock() must be called, and called BEFORE the d.error/d.task_id check -- i.e. on
    # every server answer, success or rejection, not gated behind a successful submit.
    assert "function unlock()" in before_track
    unlock_call_idx = before_track.index("unlock();")
    error_check_idx = before_track.index("if(d.error || !d.task_id)")
    assert unlock_call_idx < error_check_idx, (
        "unlock() must run as soon as the server answers, before branching on whether "
        "the submit was accepted -- otherwise a rejected submit could leave the button "
        "disabled forever, or an accepted one stays locked pending a later check"
    )
    # And Jobs.track's own callback (the completion/poll side) must NOT be what frees the
    # button anymore -- only render the per-submission line.
    track_cb = fn[fn.index("Jobs.track("): fn.index(".catch(", fn.index("Jobs.track("))]
    assert "unlock()" not in track_cb, (
        "runTask's Jobs.track callback still frees the button -- the old single-flight "
        "lock (disabled until the task completes) is back"
    )


def test_run_task_gives_each_submission_its_own_result_line(tmp_path):
    """Two submissions in flight at once must not fight over one shared result div --
    each gets its own appended line, and nothing in runTask rewrites the whole strip."""
    html = _authed_client(tmp_path).get("/").get_data(as_text=True)
    fn = _run_task_fn(html)
    assert "res.appendChild(line)" in fn, (
        "runTask no longer appends a per-submission line -- concurrent tasks would "
        "fight over one shared result element")
    assert "res.innerHTML=" not in fn, (
        "runTask still rewrites the WHOLE result strip -- a second submission would "
        "wipe the first task's still-live status/result")
    # Every render call inside runTask must target the submission's OWN `line`, never the
    # shared `res` container directly.
    assert "renderResultInto(res," not in fn and "renderResultInto(line," in fn


def test_fix_tab_no_boxes_warning_appends_instead_of_overwriting(tmp_path):
    """fix()'s own pre-submit validation (no boxes drawn) used to overwrite el('fix-result')
    directly, bypassing runTask's per-line convention -- a Fix task already rendering from a
    PRIOR submission would be wiped by a second click that forgot to draw a box first."""
    html = _authed_client(tmp_path).get("/").get_data(as_text=True)
    i = html.index("function fix(){")
    j = html.index("function openEdit(", i)
    fix_fn = html[i:j]
    assert "fr.appendChild(w)" in fix_fn, (
        "the 'draw a box first' warning no longer appends its own line -- it can wipe "
        "an in-flight Fix submission's own status/result")
    assert "fr.innerHTML=" not in fix_fn and "el('fix-result').innerHTML=" not in fix_fn


def test_fix_spend_confirm_still_gates_each_submission(tmp_path):
    """No-regression: the Fix tab's window.confirm is the app's fail-closed guardrail for
    the one spend surface /api/price cannot price (see Gen.fix's own comment). Concurrency
    must never bypass a spend gate -- the confirm still runs before every
    runTask('/api/fix') submission."""
    html = _authed_client(tmp_path).get("/").get_data(as_text=True)
    i = html.index("function fix()")
    fix_fn = html[i: html.index("function openEdit(", i)]
    assert "window.confirm(" in fix_fn, "the Fix spend confirm is gone"
    assert fix_fn.index("window.confirm(") < fix_fn.index("runTask('/api/fix'"), (
        "the Fix spend confirm no longer gates the submission")


def test_generate_edit_enhance_all_still_route_through_the_shared_runtask(tmp_path):
    """No-regression: Generate/Edit/Enhance must still submit through the one shared
    runTask() the fixes above cover -- if any of them grew its own bespoke submit path,
    it would silently lose the concurrency fix (and the spend-gate guarantees) above."""
    html = _authed_client(tmp_path).get("/").get_data(as_text=True)
    assert "runTask('/api/generate'" in html
    assert "runTask('/api/edit'" in html
    assert "runTask('/api/enhance'" in html
    assert "runTask('/api/fix'" in html
