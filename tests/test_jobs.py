"""Job activity log + the Jobs card's endpoints.

The log is an APPEND-ONLY jsonl the web "Jobs" card reads: every writer (Flask
server, panel subprocess, CLI-from-terminal) appends one line per job event, and
read_jobs() collapses by job_id (last event wins; a terminal done/failed is sticky).
This is the paper trail that survives a reload -- so these tests pin the collapse,
stickiness, dismissal, ageing, cap, and compaction behavior, plus the register /
list / dismiss endpoints and their localhost gate.
"""
import threading
import time

import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_client, login_test_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _client(tmp_path):
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    return create_app(tmp_path).test_client()


def _authed_client(tmp_path):
    """Like _client(), but logged in for real -- for every endpoint test below EXCEPT
    test_jobs_endpoints_are_localhost_only, which deliberately stays anonymous to prove
    the gate itself (an unauthenticated request is refused regardless of address)."""
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    return login_client(tmp_path)


def _lan(cli, method, url, **kw):
    kw.setdefault("environ_overrides", {})["REMOTE_ADDR"] = "192.168.1.9"
    return getattr(cli, method)(url, **kw)


# --------------------------------------------------------------------------- core

def test_append_and_read_basic(tmp_path):
    core.append_job_event(tmp_path, "j1", status="running", type="generate", label="Sunset")
    jobs = core.read_jobs(tmp_path)
    assert len(jobs) == 1
    j = jobs[0]
    assert j["job_id"] == "j1" and j["status"] == "running"
    assert j["label"] == "Sunset" and j["type"] == "generate"
    assert isinstance(j["ts"], (int, float))


def test_missing_file_is_empty(tmp_path):
    assert core.read_jobs(tmp_path) == []


def test_string_fields_are_capped_at_the_write_choke_point(tmp_path):
    """Audit 2026-07-21, S3: _cli_job_finish wrote a caught exception's str(e) here with
    NO cap at all -- the only error-write in either module missing one, fed by blanket
    `except Exception` wrappers around whole download/sync runs. append_job_event is the
    ONE place every job event from every source (web routes, the Panel's subprocess
    reader, the CLI's own logging) funnels through, so capping here closes it for all of
    them at once rather than requiring every current and future caller to remember its
    own [:200]. Matches the str(e)[:200] convention already used everywhere else.

    Bite: remove the cap and this fails with a 5000-char error stored verbatim.
    """
    core.append_job_event(tmp_path, "j1", status="failed", error="x" * 5000)
    stored = core.read_jobs(tmp_path)[0]["error"]
    assert len(stored) == 200, "error field was not capped to 200 chars"
    assert stored == "x" * 200


def test_capping_does_not_touch_non_string_fields(tmp_path):
    """The cap must be type-aware -- media_ids is a list, done/total are ints. A cap that
    tried to slice everything would crash on the very first non-string job event, or
    silently corrupt done/total into something unusable."""
    core.append_job_event(tmp_path, "j1", status="done",
                          media_ids=["m1", "m2"], done=5, total=10)
    j = core.read_jobs(tmp_path)[0]
    assert j["media_ids"] == ["m1", "m2"]
    assert j["done"] == 5 and j["total"] == 10


def test_a_short_string_field_is_unaffected(tmp_path):
    """The cap must not change the common case -- most labels/errors are far under 200
    chars and must round-trip byte-for-byte."""
    core.append_job_event(tmp_path, "j1", status="running", label="Sunset over the ruins")
    assert core.read_jobs(tmp_path)[0]["label"] == "Sunset over the ruins"


def test_collapse_last_event_wins_and_merges(tmp_path):
    # queued/running carries the label; the later done carries media_ids -- read_jobs
    # must MERGE them into one job that has both.
    core.append_job_event(tmp_path, "j1", status="running", type="generate", label="Moon elf")
    core.append_job_event(tmp_path, "j1", status="done", media_ids=["m9"])
    jobs = core.read_jobs(tmp_path)
    assert len(jobs) == 1
    j = jobs[0]
    assert j["status"] == "done"
    assert j["label"] == "Moon elf"          # kept from the earlier event
    assert j["media_ids"] == ["m9"]          # added by the later event


def test_started_at_survives_the_collapse(tmp_path):
    """Owner field-report 2026-07-23: two generations sat spinning with no way to recover
    their task id manually. The Activity tray's row(j) never surfaces the task id at all --
    fixing that is separate -- but a detail card also wants "time spent", which needs the
    job's ORIGINAL registration ts, not just its latest event's ts. Before this fix,
    _reconstruct_jobs's `cur.update(rec)` on every later event blindly overwrote `ts`, so by
    the time a job went 'done' the true start time was gone -- unreconstructable. The first
    event's ts must survive under a distinct `started_at` key, even once later events move
    `ts` on to the terminal event's own time."""
    core.append_job_event(tmp_path, "j1", status="running", type="generate", label="Elf",
                          ts=1000.0)
    core.append_job_event(tmp_path, "j1", status="done", media_ids=["m1"], ts=1042.5)
    j = core.read_jobs(tmp_path, now=1042.5)[0]
    assert j["ts"] == 1042.5                  # latest event's ts -- unchanged behavior
    assert j["started_at"] == 1000.0, "registration ts was discarded by the collapse"


def test_started_at_is_the_first_event_not_the_latest_running_heartbeat(tmp_path):
    """A job that gets several 'running' heartbeats before finishing must keep the FIRST
    one's ts as started_at, not the most recent heartbeat's -- otherwise "time spent" would
    shrink every time the card polls a long-running job instead of growing."""
    core.append_job_event(tmp_path, "j1", status="running", type="generate", ts=1000.0)
    core.append_job_event(tmp_path, "j1", status="running", done=1, total=10, ts=1010.0)
    core.append_job_event(tmp_path, "j1", status="running", done=5, total=10, ts=1020.0)
    j = core.read_jobs(tmp_path, now=1020.0)[0]
    assert j["started_at"] == 1000.0
    assert j["ts"] == 1020.0


def test_started_at_survives_compaction(tmp_path):
    """The compacted log's single surviving line per job must itself carry the real
    started_at (not the compaction-time ts) so a job's elapsed-time reconstruction doesn't
    silently reset the moment the raw log crosses the line cap."""
    core.append_job_event(tmp_path, "j1", status="running", type="generate", ts=1000.0)
    for i in range(core._JOBS_COMPACT_AT + 5):
        core.append_job_event(tmp_path, "j1", status="running", done=i, total=99999)
    core.append_job_event(tmp_path, "j1", status="done", media_ids=["m"])
    core.maybe_compact_jobs(tmp_path)
    j = core.read_jobs(tmp_path)[0]
    assert j["started_at"] == 1000.0


def test_terminal_state_is_sticky(tmp_path):
    """A late/interleaved running heartbeat must not drag a finished job back to running,
    nor inject its progress/heartbeat fields onto the finished record."""
    core.append_job_event(tmp_path, "j1", status="done", media_ids=["m1"])
    core.append_job_event(tmp_path, "j1", status="running", done=5, total=10, note="stale")
    j = core.read_jobs(tmp_path)[0]
    assert j["status"] == "done"             # sticky status
    assert j["media_ids"] == ["m1"]
    # the stale heartbeat's fields are ignored -- no zombie progress meter on a done job
    assert "note" not in j and "done" not in j and "total" not in j


def test_done_with_errors_is_sticky_too(tmp_path):
    """D-4's new terminal status must be sticky the same way done/failed already are --
    a late running heartbeat must not drag it back to 'running'."""
    core.append_job_event(tmp_path, "j1", status="done_with_errors",
                          error="3 file(s) failed to download")
    core.append_job_event(tmp_path, "j1", status="running", done=5, total=10)
    j = core.read_jobs(tmp_path)[0]
    assert j["status"] == "done_with_errors"
    assert "done" not in j and "total" not in j


def test_dismissed_is_filtered_out(tmp_path):
    core.append_job_event(tmp_path, "j1", status="done", media_ids=["m1"])
    core.append_job_event(tmp_path, "j2", status="failed", error="boom")
    core.append_job_event(tmp_path, "j1", dismissed=True)
    ids = [j["job_id"] for j in core.read_jobs(tmp_path)]
    assert ids == ["j2"]                      # j1 dismissed; dismiss keeps status intact


def test_dismiss_does_not_revive_or_flip_status(tmp_path):
    core.append_job_event(tmp_path, "j1", status="failed", error="boom")
    core.append_job_event(tmp_path, "j1", dismissed=True)
    jobs, order, _ = core._reconstruct_jobs(tmp_path)
    assert jobs["j1"]["status"] == "failed" and jobs["j1"]["dismissed"] is True


def test_stale_jobs_age_out_regardless_of_status(tmp_path):
    """Anything with no activity for max_age ages out -- running included. A day-old
    'running' entry is a zombie (tab closed / blip before the done poll), so it must not
    linger forever; fresh jobs (recent ts) always survive."""
    core.append_job_event(tmp_path, "old_done", status="done", media_ids=["m1"])
    core.append_job_event(tmp_path, "old_run", status="running", label="zombie")
    future = time.time() + 25 * 3600         # 25h later, no further activity
    assert core.read_jobs(tmp_path, now=future) == []   # both aged out -- no zombies


def test_running_kept_within_window_even_past_keep_cap(tmp_path):
    """The keep cap trims FINISHED history only; an in-window running job is never capped
    away by a flood of newer completions (mirrored in compaction)."""
    core.append_job_event(tmp_path, "run", status="running", label="live")
    time.sleep(0.002)
    for i in range(60):
        core.append_job_event(tmp_path, "d%d" % i, status="done", media_ids=["m"])
        time.sleep(0.001)                    # distinct ts -> deterministic newest-50
    jobs = core.read_jobs(tmp_path, keep=50)
    ids = [j["job_id"] for j in jobs]
    assert "run" in ids                      # running survives despite 60 newer finished
    assert sum(1 for j in jobs if j["status"] == "done") == 50   # finished capped to 50


def test_keep_cap_returns_newest_n(tmp_path):
    for i in range(60):
        core.append_job_event(tmp_path, "j%d" % i, status="done", media_ids=["m%d" % i])
        time.sleep(0.001)                    # keep timestamps distinct for ordering
    jobs = core.read_jobs(tmp_path, keep=50)
    assert len(jobs) == 50
    assert jobs[0]["job_id"] == "j59"        # newest first
    kept = {j["job_id"] for j in jobs}
    assert "j0" not in kept                  # oldest fell off the cap


def test_corrupt_lines_are_skipped(tmp_path):
    p = core._jobs_path(tmp_path)
    core.append_job_event(tmp_path, "j1", status="done", media_ids=["m1"])
    with p.open("a", encoding="utf-8") as fh:
        fh.write("not json at all\n\n")      # garbage + blank line
    core.append_job_event(tmp_path, "j2", status="running")
    ids = sorted(j["job_id"] for j in core.read_jobs(tmp_path))
    assert ids == ["j1", "j2"]               # garbage skipped, real rows survive


def test_compaction_bounds_the_log(tmp_path):
    """The append-only log can't grow forever: past _JOBS_COMPACT_AT lines the reader
    rewrites it down to the reconstructed kept records without losing any job."""
    p = core._jobs_path(tmp_path)
    for i in range(core._JOBS_COMPACT_AT + 30):
        core.append_job_event(tmp_path, "j%d" % (i % 3), status="running", done=i, total=9999)
    for jid in ("j0", "j1", "j2"):
        core.append_job_event(tmp_path, jid, status="done", media_ids=["m"])
    raw_before = len(p.read_text(encoding="utf-8").splitlines())
    assert raw_before > core._JOBS_COMPACT_AT
    core.maybe_compact_jobs(tmp_path)
    raw_after = len(p.read_text(encoding="utf-8").splitlines())
    assert raw_after == 3                     # one line per surviving job
    jobs = {j["job_id"]: j for j in core.read_jobs(tmp_path)}
    assert set(jobs) == {"j0", "j1", "j2"} and all(j["status"] == "done" for j in jobs.values())


def test_compaction_noop_under_threshold(tmp_path):
    p = core._jobs_path(tmp_path)
    core.append_job_event(tmp_path, "j1", status="running")
    core.append_job_event(tmp_path, "j1", status="done", media_ids=["m1"])
    before = p.read_text(encoding="utf-8")
    core.maybe_compact_jobs(tmp_path)
    assert p.read_text(encoding="utf-8") == before   # untouched below the line cap


def test_compaction_agrees_with_read_and_preserves_running(tmp_path):
    """read_jobs and maybe_compact_jobs share one selection, so compaction can never delete
    a job the card is showing -- and an in-flight running job survives compaction even when
    50+ newer finished jobs exist and the raw log crossed the line cap."""
    core.append_job_event(tmp_path, "run", status="running", label="live")
    time.sleep(0.002)
    for i in range(60):
        core.append_job_event(tmp_path, "d%d" % i, status="done", media_ids=["m"])
        time.sleep(0.001)
    # push the raw log past the compaction threshold with heartbeats on the running job
    for _ in range(core._JOBS_COMPACT_AT):
        core.append_job_event(tmp_path, "run", status="running", label="live")
    before = {j["job_id"] for j in core.read_jobs(tmp_path)}
    core.maybe_compact_jobs(tmp_path)
    after = {j["job_id"] for j in core.read_jobs(tmp_path)}
    assert before == after                   # compaction dropped nothing the card showed
    assert "run" in after                    # the running job survived the rewrite


# ----------------------------------------------------------------------- endpoints

def test_register_list_dismiss_roundtrip(tmp_path):
    cli = _authed_client(tmp_path)
    assert cli.get("/api/jobs").get_json()["jobs"] == []
    r = cli.post("/api/jobs", json={"job_id": "t1", "type": "generate", "label": "Elf"})
    assert r.get_json()["ok"] is True
    jobs = cli.get("/api/jobs").get_json()["jobs"]
    assert len(jobs) == 1 and jobs[0]["job_id"] == "t1"
    assert jobs[0]["status"] == "running" and jobs[0]["label"] == "Elf"
    assert cli.post("/api/jobs/dismiss", json={"job_id": "t1"}).get_json()["ok"] is True
    assert cli.get("/api/jobs").get_json()["jobs"] == []


def test_register_requires_job_id(tmp_path):
    cli = _authed_client(tmp_path)
    assert cli.post("/api/jobs", json={"label": "no id"}).status_code == 400


def test_running_then_done_merges_through_the_endpoint(tmp_path):
    """The real lifecycle: the card POSTs a running job on submit, then /api/task-status
    writes the authoritative done event (same _log_job path). GET must show ONE job,
    done, with the label from register AND the media_ids from completion."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "t7", "type": "generate", "label": "Nightsong"})
    core.append_job_event(tmp_path, "t7", status="done", media_ids=["mid42"])  # what task-status does
    jobs = cli.get("/api/jobs").get_json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "done" and jobs[0]["label"] == "Nightsong"
    assert jobs[0]["media_ids"] == ["mid42"]


def test_dismiss_finished_clears_done_and_failed_only(tmp_path):
    cli = _authed_client(tmp_path)
    core.append_job_event(tmp_path, "d", status="done", media_ids=["m"])
    core.append_job_event(tmp_path, "f", status="failed", error="x")
    core.append_job_event(tmp_path, "r", status="running", label="live")
    cli.post("/api/jobs/dismiss", json={"finished": True})
    ids = [j["job_id"] for j in cli.get("/api/jobs").get_json()["jobs"]]
    assert ids == ["r"]                        # running survives; finished cleared


def test_dismiss_finished_also_clears_done_with_errors(tmp_path):
    """D-4: without wiring the new status into the same terminal set /api/jobs/dismiss
    already uses, a done_with_errors job could never be cleared by 'clear finished' --
    it would just sit there forever even though the run it represents is over."""
    cli = _authed_client(tmp_path)
    core.append_job_event(tmp_path, "w", status="done_with_errors", error="2 failed")
    core.append_job_event(tmp_path, "r", status="running", label="live")
    cli.post("/api/jobs/dismiss", json={"finished": True})
    ids = [j["job_id"] for j in cli.get("/api/jobs").get_json()["jobs"]]
    assert ids == ["r"]


def test_resolve_orphan_jobs_resolves_stuck_running(tmp_path):
    """A generate job stuck at 'running' (its Generate-card poller was closed before the
    task finished) gets resolved to its true terminal state by asking PixAI once. Only
    numeric-task-id generate jobs are checked; panel/delete jobs are left alone. This is
    the fix for the 'failed on PixAI but our Activity still says in progress' bug."""
    core.append_job_event(tmp_path, "2030945851997330461", status="running",
                          type="generate", label="Edited")     # the orphaned edit
    core.append_job_event(tmp_path, "999", status="running", type="generate", label="live gen")
    core.append_job_event(tmp_path, "panel-abc", status="running", type="panel", label="Sync")
    core.append_job_event(tmp_path, "5", status="done", type="generate")  # already terminal

    asked = []
    def _status(tid):
        asked.append(tid)
        return {"2030945851997330461": "failed", "999": "running"}.get(tid, "running")

    n = core.resolve_orphan_jobs(tmp_path, _status)

    assert n == 1                                   # only the failed one resolved
    assert set(asked) == {"2030945851997330461", "999"}   # panel + already-done skipped
    by_id = {j["job_id"]: j for j in core.read_jobs(tmp_path)}
    assert by_id["2030945851997330461"]["status"] == "failed"
    assert by_id["999"]["status"] == "running"      # genuinely still running -> untouched
    assert by_id["panel-abc"]["status"] == "running"


def test_resolve_orphan_jobs_survives_lookup_errors(tmp_path):
    """One task whose status lookup raises must not stop the others from resolving."""
    core.append_job_event(tmp_path, "111", status="running", type="generate")
    core.append_job_event(tmp_path, "222", status="running", type="generate")
    def _status(tid):
        if tid == "111":
            raise RuntimeError("network blip")
        return "done"
    n = core.resolve_orphan_jobs(tmp_path, _status)
    assert n == 1
    by_id = {j["job_id"]: j for j in core.read_jobs(tmp_path)}
    assert by_id["111"]["status"] == "running" and by_id["222"]["status"] == "done"


def test_jobs_endpoints_are_localhost_only(tmp_path):
    cli = _client(tmp_path)
    core.append_job_event(tmp_path, "j1", status="running")
    # GET from the LAN reveals nothing and 401s (the global front-door hook, not
    # api_jobs()'s own body -- see moonglade_gallery.py's _enforce_front_door())
    r = _lan(cli, "get", "/api/jobs")
    assert r.status_code == 401 and "jobs" not in r.get_json()
    # register + dismiss are refused from the LAN
    assert _lan(cli, "post", "/api/jobs", json={"job_id": "x"}).status_code == 401
    assert _lan(cli, "post", "/api/jobs/dismiss", json={"job_id": "j1"}).status_code == 401
    # ...and nothing was written by those rejected calls
    assert [j["job_id"] for j in core.read_jobs(tmp_path)] == ["j1"]


def test_reaper_accepts_what_generation_status_actually_returns(tmp_path):
    """THE BUG THIS EXISTS FOR: resolve_orphan_jobs compares status_fn's return against
    ("done","failed"), and every test above stubs status_fn with the documented STRING.
    The real web caller passed core.generation_status(...) straight through, which
    returns {status, phase, paid_credit} -- a dict is never in that tuple, so the reaper
    silently resolved nothing and returned 0 on every run while looking perfectly
    healthy. Nothing caught it: the unit tests honoured a contract the only real caller
    broke, and the failure mode was "quietly does nothing", which no assertion was
    watching for. Feed it the REAL shape and require the job to actually resolve."""
    core.append_job_event(tmp_path, "2035858031750209359", status="running",
                          type="generate", label="Enhanced")

    def _status(tid):                       # exactly generation_status()'s return shape
        return {"status": "completed", "phase": "done", "paid_credit": 0}

    n = core.resolve_orphan_jobs(tmp_path, _status)
    assert n == 1, "reaper ignored generation_status()'s real dict return"
    by_id = {j["job_id"]: j for j in core.read_jobs(tmp_path)}
    assert by_id["2035858031750209359"]["status"] == "done"


def test_reaper_still_leaves_running_jobs_alone_in_dict_form(tmp_path):
    """The dict tolerance must not turn every lookup terminal -- a genuinely running
    task stays running."""
    core.append_job_event(tmp_path, "777", status="running", type="generate")
    n = core.resolve_orphan_jobs(
        tmp_path, lambda tid: {"status": "processing", "phase": "running"})
    assert n == 0
    assert {j["job_id"]: j for j in core.read_jobs(tmp_path)}["777"]["status"] == "running"


# ------------------------------------------------------- fix 2: age-gated reconciliation

def test_resolve_orphan_jobs_min_age_skips_jobs_that_are_not_old_enough_yet(tmp_path):
    """The ongoing /api/jobs sweep passes a real min_age so a job that's only just been
    submitted (its own Generate card is very likely still actively polling it) is never
    even asked about -- asking would be pointless PixAI traffic on every poll for every
    normal, healthy generation."""
    core.append_job_event(tmp_path, "1", status="running", type="generate")   # ts ~ now
    asked = []
    n = core.resolve_orphan_jobs(tmp_path, lambda tid: asked.append(tid) or "done", min_age=1800)
    assert n == 0 and asked == []
    assert {j["job_id"]: j for j in core.read_jobs(tmp_path)}["1"]["status"] == "running"


def test_stale_job_reconciliation_marks_stale_when_pixai_cannot_be_reached(tmp_path):
    """THE FIX (docs/AUDIT_2026-07-21.md, owner-2026-07-23, fix 2): a job stuck at
    'running' well past a reasonable age gets re-checked against PixAI's real status.
    When that check itself fails (network error -- PixAI's own state genuinely can't be
    determined), the job must NOT be silently left exactly as it was forever, and must
    NOT be guessed into 'done' or 'failed' -- either guess could be wrong and would hide
    real evidence from the owner. It gets a distinct, visible 'stale' marker instead,
    with the failure reason recorded, so the owner can see a job got stuck AND that we
    tried and couldn't confirm why -- never a silent, untraceable disappearance."""
    old_ts = time.time() - 3700           # well past the 1800s threshold used below
    core.append_job_event(tmp_path, "2037215124834251576", status="running",
                          type="generate", label="Generated", ts=old_ts)

    def _network_error(tid):
        raise RuntimeError("connection reset")

    n = core.resolve_orphan_jobs(tmp_path, _network_error, min_age=1800)

    assert n == 0                                    # NOT resolved to done/failed
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["2037215124834251576"]
    assert job["status"] == "stale", "a failed status check silently vanished instead of being marked"
    assert job["status"] not in core._JOBS_TERMINAL   # never guessed into a false done/failed
    assert job.get("error")                           # the owner can see WHY it's stuck


def test_stale_job_reconciliation_resolves_a_real_orphan_when_pixai_confirms_it(tmp_path):
    """The other half: when PixAI CAN be reached and reports the aged job actually
    finished (or failed), the sweep resolves it for real -- 'stale' is only for when the
    check itself is impossible, not a substitute for actually asking."""
    old_ts = time.time() - 3700
    core.append_job_event(tmp_path, "5551", status="running", type="generate", ts=old_ts)
    n = core.resolve_orphan_jobs(tmp_path, lambda tid: "done", min_age=1800)
    assert n == 1
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["5551"]
    assert job["status"] == "done"


def test_stale_job_reconciliation_refreshes_ts_for_a_confirmed_still_running_aged_job(tmp_path):
    """A job that crosses min_age but IS genuinely still running (PixAI confirms
    'running', no error) must not get re-asked on literally every subsequent poll for as
    long as it stays running -- a real video generation can easily run past 30 minutes.
    The sweep refreshes its ts on a confirmed-alive check, resetting the min_age clock,
    so the next ask waits another full min_age instead of firing again immediately."""
    old_ts = time.time() - 3700
    core.append_job_event(tmp_path, "9001", status="running", type="generate", ts=old_ts)
    core.resolve_orphan_jobs(tmp_path, lambda tid: "running", min_age=1800)
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["9001"]
    assert job["status"] == "running"
    assert job["ts"] > old_ts + 3000, "ts was not refreshed -- the job will be re-asked every poll"


def test_api_jobs_endpoint_reconciles_a_stale_orphan_on_poll(tmp_path, monkeypatch, pixai):
    """End-to-end: /api/jobs itself (not just the library function) runs the sweep --
    same 'runs opportunistically off an existing poll' shape as maybe_compact_jobs right
    beside it. A generate job old enough to cross JOBS_ORPHAN_SWEEP_AGE, whose PixAI
    status check fails, comes back from a plain GET /api/jobs already marked 'stale'."""
    cli = _authed_client(tmp_path)
    old_ts = time.time() - core.JOBS_ORPHAN_SWEEP_AGE - 100
    core.append_job_event(tmp_path, "2037215124834251576", status="running",
                          type="generate", label="Generated", ts=old_ts)

    def _boom(session, tid):
        raise RuntimeError("network blip")
    monkeypatch.setattr(core, "generation_status", _boom)

    jobs = cli.get("/api/jobs").get_json()["jobs"]
    by_id = {j["job_id"]: j for j in jobs}
    assert by_id["2037215124834251576"]["status"] == "stale"


def test_empty_output_task_is_logged_failed_not_left_running(tmp_path, monkeypatch, pixai):
    """A task PixAI calls 'done' whose outputs carry no media is TERMINAL -- it produced
    nothing and never will. /api/task-status used to let that fall into the catch-all
    `except`, which deliberately withholds a terminal event so a transient 5xx can't
    brick the card with a false failure. Correct for a blip, wrong here: the job spun on
    'running' forever. (Real case: an enhance submitted with an unusable input media id
    sat at 'running' while PixAI considered it long finished.) EmptyOutputsError exists
    solely to tell those two apart at this catch site."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "555", "type": "generate", "label": "Enhanced"})

    monkeypatch.setattr(core, "generation_status",
                        lambda s, tid: {"status": "completed", "phase": "done",
                                        "paid_credit": 0})

    def _boom(*a, **k):
        raise core.EmptyOutputsError("task completed but no media ids found")
    monkeypatch.setattr(core, "collect_generation", _boom)

    r = cli.get("/api/task-status?task_id=555")
    assert r.get_json()["phase"] == "failed"
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["555"]
    assert job["status"] == "failed", "empty-output task left spinning at 'running'"


def test_a_transient_blip_still_does_not_write_a_false_failure(tmp_path, monkeypatch, pixai):
    """The other half of the same contract, and the reason a bare `except PixAIError`
    would have been the wrong fix: an ordinary error during collect (5xx/429/timeout,
    which surfaces as a plain PixAIError) must still leave the job at its last-known
    state, because the task has probably succeeded and a sticky 'failed' would brick the
    card. Only EmptyOutputsError is terminal."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "556", "type": "generate", "label": "Enhanced"})

    monkeypatch.setattr(core, "generation_status",
                        lambda s, tid: {"status": "completed", "phase": "done",
                                        "paid_credit": 0})

    def _blip(*a, **k):
        raise core.PixAIError("503 Service Unavailable")
    monkeypatch.setattr(core, "collect_generation", _blip)

    cli.get("/api/task-status?task_id=556")
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["556"]
    assert job["status"] == "running", "a transient blip wrote a sticky false failure"


def test_collect_is_single_flight_across_watcher_and_poll(tmp_path, monkeypatch, pixai):
    """The in-process half of the video-corruption fix (owner field-test 2026-07-23):
    the always-on live-mirror watcher and a /api/task-status done-poll both collect the
    same task seconds apart. They must coalesce into ONE collect_generation -- the
    second entrant waits, then answers from the catalog instead of re-downloading
    (the double collect is what lined up two concurrent video_faststart remuxes on the
    same clip in the first place). The watcher-mirror closure is driven through the
    app.extensions seam create_app exposes for exactly this."""
    import threading
    from moonglade_gallery import create_app

    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    app = create_app(tmp_path)
    cli = login_test_client(app)

    monkeypatch.setattr(core, "generation_status",
                        lambda s, tid: {"status": "completed", "phase": "done",
                                        "paid_credit": 0})

    mu = threading.Lock()
    stats = {"cur": 0, "max": 0, "calls": 0}
    entered = threading.Event()

    def slow_collect(session, tid, out, **kw):
        with mu:
            stats["cur"] += 1
            stats["calls"] += 1
            stats["max"] = max(stats["max"], stats["cur"])
        entered.set()
        time.sleep(0.4)                    # hold the collect open so the poll overlaps it
        save_catalog(tmp_path / "catalog.db", [
            _row(task_id="909", media_id="M9", is_video="1",
                 filename="videos/x_909_M9.mp4", created_at="2025-01-02T00:00:00")])
        with mu:
            stats["cur"] -= 1
        return {"media_ids": ["M9"], "saved": 1, "is_video": True, "duration": 2.0}

    monkeypatch.setattr(core, "collect_generation", slow_collect)

    t = threading.Thread(target=app.extensions["mg_watch_mirror"], args=("909",))
    t.start()
    assert entered.wait(5), "the watcher-mirror path never reached collect_generation"
    r = cli.get("/api/task-status?task_id=909")     # arrives while the collect is in flight
    t.join(10)
    assert not t.is_alive()

    body = r.get_json()
    assert body["phase"] == "done" and body["media_ids"] == ["M9"]
    assert body.get("is_video") is True             # catalog re-read keeps the video flag
    assert stats["calls"] == 1, "the same task was collected twice"
    assert stats["max"] == 1, "two collects for one task ran concurrently"


# ------------------------------------------------- the live-mirror watcher's own logging
# Two things can mark a generation job terminal, and before 2026-07-24 only ONE of them
# recorded which media the task produced:
#
#   * /api/task-status's done branch    -> done WITH media_ids  (the tray gets a thumbnail)
#   * the watcher's _reconcile_job      -> a bare done, no media_ids
#
# _watch_mirror DID download + catalog the media (it calls _collect_single_flight and gets
# {media_ids, saved, is_video} back) and then threw that return value away. Whichever
# writer won the race decided whether the Activity tray card had a thumbnail forever
# after: the orphan sweep only re-checks jobs stuck at 'running', so a job already sitting
# at a bare 'done' was never revisited by anything. These tests drive the mirror through
# the app.extensions["mg_watch_mirror"] seam create_app exposes for exactly this
# (conftest's _no_live_watch keeps the real watcher thread from ever starting).


def _mirror_app(tmp_path):
    """A create_app instance with a seeded catalog, for the mg_watch_mirror seam."""
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    return create_app(tmp_path)


def _stub_collect(monkeypatch, result, calls=None):
    """Offline stand-in for core.collect_generation returning its real shape."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())

    def _collect(session, tid, out, **kw):
        if calls is not None:
            calls.append(str(tid))
        return dict(result)
    monkeypatch.setattr(core, "collect_generation", _collect)


def test_watcher_mirror_records_the_media_it_collected_after_a_bare_done(tmp_path, monkeypatch):
    """The owner's real production sequence, two back-to-back generations (jobs.jsonl,
    2026-07-24). Gen #2's log read, verbatim in shape:

        running                              (its Generate card registered it)
        done                                 (bare -- the watcher's _reconcile_job)
        ...and nothing further, ever.

    Its four images WERE downloaded and catalogued (verified against catalog.db) -- the
    watcher's mirror collected them fine while the browser was still busy collecting gen
    #1. But no media_ids ever reached the job log, and static/mg-notify.js's row() builds
    its thumbnail from `(j.media_ids||[])[0]`, so that card rendered permanently blank.
    Not a stuck job, not lost data: a finished job that can never show what it made.

    Bite: throw away _collect_single_flight's return value again and media_ids is absent."""
    tid = "2037566630884963619"
    app = _mirror_app(tmp_path)
    core.append_job_event(tmp_path, tid, status="running", type="generate", label="Generated")
    core.append_job_event(tmp_path, tid, status="done")   # exactly what _reconcile_job writes
    _stub_collect(monkeypatch, {"media_ids": ["A", "B", "C", "D"], "saved": 4,
                               "is_video": False})

    app.extensions["mg_watch_mirror"](tid)

    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}[tid]
    assert job["status"] == "done"
    assert job.get("media_ids") == ["A", "B", "C", "D"], (
        "the watcher collected the media but never recorded it -- permanently blank card")
    assert job.get("is_video") is False


def test_a_later_bare_done_cannot_clobber_the_mirrors_media_ids(tmp_path, monkeypatch):
    """The same race the other way round, which is a real interleaving and not a
    hypothetical: _reconcile_job's read ("is this job still non-terminal?") and its write
    are not atomic, so the mirror thread can land its media_ids event BETWEEN them and the
    bare `done` gets appended afterwards. _reconstruct_jobs merges a later event over the
    current one (`cur.update(rec)`) rather than replacing it, and the bare event carries no
    media_ids key at all, so the media survives -- pinned here so a future change to that
    merge (e.g. replace-instead-of-update) cannot silently reintroduce the blank card from
    the other direction."""
    tid = "2037566243599720339"
    app = _mirror_app(tmp_path)
    core.append_job_event(tmp_path, tid, status="running", type="generate", label="Generated")
    _stub_collect(monkeypatch, {"media_ids": ["A", "B"], "saved": 2, "is_video": False})

    app.extensions["mg_watch_mirror"](tid)
    core.append_job_event(tmp_path, tid, status="done")   # _reconcile_job's write, arriving late

    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}[tid]
    assert job["status"] == "done"
    assert job.get("media_ids") == ["A", "B"], "a bare terminal event blanked a good entry"


def test_mirror_matches_task_status_event_shape_for_a_video(tmp_path, monkeypatch):
    """Same event shape /api/task-status's done branch writes -- including is_video, and
    deliberately EXCLUDING duration. collect_generation returns a duration for videos and
    task-status only puts it in its JSON response, never in the job log; the two writers
    must stay indistinguishable in jobs.jsonl."""
    tid = "4242"
    app = _mirror_app(tmp_path)
    core.append_job_event(tmp_path, tid, status="running", type="generate", label="Rendered")
    core.append_job_event(tmp_path, tid, status="done")
    _stub_collect(monkeypatch, {"media_ids": ["V1"], "saved": 1, "is_video": True,
                               "duration": 3.0})

    app.extensions["mg_watch_mirror"](tid)

    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}[tid]
    assert job.get("media_ids") == ["V1"] and job.get("is_video") is True
    assert "duration" not in job, "logged a field /api/task-status's done branch never logs"


def test_mirror_writes_no_event_when_the_collect_produced_nothing(tmp_path, monkeypatch):
    """A collect that genuinely yielded no media must NOT get a media_ids event: an empty
    list would be indistinguishable from a real result to the tray and would blank an
    entry that another writer had already filled in correctly. Prefer writing nothing."""
    tid = "7777"
    app = _mirror_app(tmp_path)
    core.append_job_event(tmp_path, tid, status="running", type="generate", label="Generated")
    _stub_collect(monkeypatch, {"media_ids": [], "saved": 0, "is_video": False})

    app.extensions["mg_watch_mirror"](tid)

    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}[tid]
    assert job["status"] == "running", "wrote a terminal event for a collect that made nothing"
    assert not job.get("media_ids")


def test_mirror_never_invents_a_job_for_a_task_we_do_not_track(tmp_path, monkeypatch):
    """The watcher mirrors EVERY completed task on the account, including ones generated
    on pixai.art itself. Same contract _reconcile_job already keeps: only touch a job we
    already track, never invent one -- otherwise every website generation would appear as
    a new row in the owner's Activity tray."""
    app = _mirror_app(tmp_path)
    _stub_collect(monkeypatch, {"media_ids": ["Z"], "saved": 1, "is_video": False})

    app.extensions["mg_watch_mirror"]("8888")

    assert core.read_jobs(tmp_path) == [], "invented an Activity row for a website generation"


def test_mirror_logging_failure_cannot_break_mirroring(tmp_path, monkeypatch):
    """The whole watcher chain is deliberately fail-soft and _watch_mirror runs on a
    daemon thread nobody joins. A problem READING the job log must not abort the mirror,
    lose its 'mirrored' count, or masquerade as a mirror error in the Panel's watch-status
    line."""
    app = _mirror_app(tmp_path)
    cli = login_test_client(app)
    core.append_job_event(tmp_path, "99", status="running", type="generate", label="Generated")
    calls = []
    _stub_collect(monkeypatch, {"media_ids": ["Z"], "saved": 1, "is_video": False}, calls)

    def _boom(*a, **k):
        raise RuntimeError("job log read exploded")
    monkeypatch.setattr(core, "_reconstruct_jobs", _boom)

    app.extensions["mg_watch_mirror"]("99")      # must not raise

    assert calls == ["99"], "the mirror itself was aborted by a logging problem"
    st = cli.get("/api/watch/status").get_json()
    assert st["mirrored"] == 1
    assert not st["last_error"], "a logging problem was reported as a mirror failure"


# ---- generation_status must carry WHY, not just WHAT (silent-death bug, 2026-07-24) ----

def test_generation_status_surfaces_pixai_cancel_reason(monkeypatch):
    """PixAI reaps a task it never dispatched with outputs={"reason": "waiting timeout"}.
    generation_status returned only the bare status, so every caller -- the web poller,
    the job log, the tracker card -- could say no more than "cancelled", which reads as
    though the OWNER cancelled it. He hit this five times across four days and the reason
    string never once reached him."""
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {"task": {
        "status": "cancelled", "startedAt": None,
        "outputs": {"reason": "waiting timeout"}, "paidCredit": 1200}})
    st = core.generation_status(object(), "2037594262049550370")
    assert st["phase"] == "failed"
    assert st.get("reason") == "waiting timeout", \
        "PixAI's own reason must survive into the status dict: {!r}".format(st)


def test_generation_status_reports_whether_the_task_ever_started(monkeypatch):
    """`started` is the only thing separating "queued, no worker ever took it" from
    "genuinely working". Both sit at a non-terminal status, so without this a tracker can
    only show an indefinite spinner -- which is exactly how an hour of nothing looked."""
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {"task": {
        "status": "waiting", "startedAt": None}})
    assert core.generation_status(object(), "t1")["started"] is False

    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {"task": {
        "status": "running", "startedAt": "2026-07-25T05:00:00.000Z"}})
    assert core.generation_status(object(), "t2")["started"] is True


def test_generation_status_keeps_its_existing_keys(monkeypatch):
    """resolve_orphan_jobs and /api/task-status both read this dict positionally by key;
    adding fields must not drop the three they already depend on."""
    monkeypatch.setattr(core, "gql_adhoc", lambda *a, **k: {"task": {
        "status": "completed", "paidCredit": 42}})
    st = core.generation_status(object(), "t3")
    assert st["status"] == "completed" and st["phase"] == "done" and st["paid_credit"] == 42


def test_reaped_task_logs_pixai_reason_not_a_bare_cancelled(tmp_path, monkeypatch, pixai):
    """When PixAI reaps a task it never dispatched, /api/task-status DOES mark it failed --
    but it logged the bare status, so the tracker card and the CLI both said only
    'cancelled'. The owner read that as "something cancelled my job" and had no way to
    learn PixAI had timed it out of its own queue. Log and return the reason."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "2037594262049550370", "type": "generate",
                                "label": "Enhanced"})
    monkeypatch.setattr(core, "generation_status",
                        lambda s, tid: {"status": "cancelled", "phase": "failed",
                                        "paid_credit": 1200, "started": False,
                                        "reason": "waiting timeout"})

    r = cli.get("/api/task-status?task_id=2037594262049550370")
    body = r.get_json()
    assert body["phase"] == "failed"
    assert "waiting timeout" in str(body), \
        "reason absent from the response: {!r}".format(body)
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["2037594262049550370"]
    assert "waiting timeout" in str(job.get("error") or ""), \
        "reason absent from the job log: {!r}".format(job)


def test_running_response_says_whether_a_worker_ever_picked_it_up(tmp_path, monkeypatch, pixai):
    """A queued-but-undispatched task is non-terminal for ~60 minutes and looks identical
    to real work over the wire, so the tracker could only show an endless spinner. Pass
    `started` through so the card can say "queued" instead of implying progress."""
    cli = _authed_client(tmp_path)
    monkeypatch.setattr(core, "generation_status",
                        lambda s, tid: {"status": "waiting", "phase": "running",
                                        "paid_credit": None, "started": False, "reason": ""})
    body = cli.get("/api/task-status?task_id=999").get_json()
    assert body["phase"] == "running"
    assert body.get("started") is False, "no way to tell queued from working: {!r}".format(body)


def test_reaper_marks_a_never_started_job_stale_with_an_explanation(tmp_path):
    """The visible half of the silent-death fix. A task PixAI accepted but never dispatched
    stays NON-TERMINAL for ~60 minutes, so the reaper's terminal check never fires and the
    card spins with no hint anything is wrong -- which is precisely how five of the owner's
    enhances died unnoticed. `stale` is reused deliberately: it already renders a warning
    glyph + message in the tracker, and it is NOT in _JOBS_TERMINAL, so if PixAI does
    eventually start the task a later done/failed still wins."""
    core.append_job_event(tmp_path, "2037594262049550370", status="running",
                          type="generate", label="Enhanced")

    def _status(tid):
        return {"status": "waiting", "phase": "running", "paid_credit": 1200,
                "started": False, "reason": ""}

    core.resolve_orphan_jobs(tmp_path, _status, min_age=0, now=time.time() + 9999)
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["2037594262049550370"]
    assert job["status"] == "stale", "never-started job left spinning: {!r}".format(job)
    assert "not started" in str(job.get("error") or "").lower(), \
        "stale marker must explain why: {!r}".format(job)


def test_reaper_leaves_a_genuinely_started_job_running(tmp_path):
    """A long video generation legitimately runs for many minutes. `started` True must keep
    it on the running heartbeat, not brand it stale."""
    core.append_job_event(tmp_path, "888", status="running", type="generate")
    core.resolve_orphan_jobs(
        tmp_path, lambda tid: {"status": "processing", "phase": "running", "started": True},
        min_age=0, now=time.time() + 9999)
    assert {j["job_id"]: j for j in core.read_jobs(tmp_path)}["888"]["status"] == "running"


def test_reaper_ignores_a_status_fn_that_never_reports_started(tmp_path):
    """Back-compat, and the reason the check is `started is False` and not `not started`:
    a caller (or an older job log) that omits the field must NOT have every in-flight job
    branded stale. Absent means unknown, and unknown is not a failure."""
    core.append_job_event(tmp_path, "889", status="running", type="generate")
    core.resolve_orphan_jobs(
        tmp_path, lambda tid: {"status": "processing", "phase": "running"},
        min_age=0, now=time.time() + 9999)
    assert {j["job_id"]: j for j in core.read_jobs(tmp_path)}["889"]["status"] == "running"


def test_api_jobs_endpoint_marks_a_never_started_orphan_stale(tmp_path, monkeypatch, pixai):
    """END-TO-END, and the guard that catches the wiring this fix nearly shipped broken.

    resolve_orphan_jobs can only see `started` if its status_fn hands over the whole
    generation_status dict. The real caller in create_app returned
    `generation_status(...)["phase"]` -- a bare string -- so the never-started branch was
    DEAD CODE in production while every unit test around it passed, because they call the
    library function directly with their own stub. That is the same caller/contract
    mismatch that once made this reaper resolve nothing at all, in mirror image.

    Drives the real GET /api/jobs against a task PixAI accepted and never dispatched."""
    cli = _authed_client(tmp_path)
    old_ts = time.time() - core.JOBS_ORPHAN_SWEEP_AGE - 100
    core.append_job_event(tmp_path, "2037625229523385030", status="running",
                          type="generate", label="Enhanced", ts=old_ts)
    monkeypatch.setattr(core, "generation_status",
                        lambda s, tid: {"status": "waiting", "phase": "running",
                                        "paid_credit": 1200, "started": False, "reason": ""})

    by_id = {j["job_id"]: j for j in cli.get("/api/jobs").get_json()["jobs"]}
    job = by_id["2037625229523385030"]
    assert job["status"] == "stale", \
        "never-started orphan still spinning through the real endpoint: {!r}".format(job)
    assert "not started" in str(job.get("error") or "").lower()


def test_done_event_records_what_the_generation_actually_cost(tmp_path, monkeypatch, pixai):
    """/api/task-status already receives PixAI's server-authoritative `paidCredit` and
    returns it to the browser, but dropped it from the job log -- so the Activity tray's
    detail popover could show a task id, a send time and an elapsed time, and never what
    the job cost. Cost is the one number the owner cannot reconstruct later without
    re-querying PixAI per task, and it is exactly what makes an unexpected spend visible."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "4242", "type": "generate", "label": "Generated"})
    monkeypatch.setattr(core, "generation_status",
                        lambda s, tid: {"status": "completed", "phase": "done",
                                        "paid_credit": 3700, "started": True, "reason": ""})
    monkeypatch.setattr(core, "collect_generation",
                        lambda *a, **k: {"media_ids": ["m1"], "saved": 1, "is_video": False})

    assert cli.get("/api/task-status?task_id=4242").get_json()["phase"] == "done"
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["4242"]
    assert job.get("paid_credit") == 3700, \
        "the job log did not record the actual cost: {!r}".format(job)


def test_a_free_card_generation_records_zero_not_missing(tmp_path, monkeypatch, pixai):
    """A card-covered generation genuinely costs 0. That must round-trip as the number 0,
    not vanish -- otherwise "free" and "unknown" are indistinguishable in the log, and the
    tray would hide the cost row on exactly the generations worth confirming were free."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "4243", "type": "generate", "label": "Generated"})
    monkeypatch.setattr(core, "generation_status",
                        lambda s, tid: {"status": "completed", "phase": "done",
                                        "paid_credit": 0, "started": True, "reason": ""})
    monkeypatch.setattr(core, "collect_generation",
                        lambda *a, **k: {"media_ids": ["m1"], "saved": 1, "is_video": False})

    cli.get("/api/task-status?task_id=4243")
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["4243"]
    assert job.get("paid_credit") == 0, "free generation lost its explicit 0: {!r}".format(job)


# ---- "it just says 'fails'": make a failure message say something usable ----

def test_failed_with_no_reason_explains_itself_instead_of_saying_failed(tmp_path, monkeypatch, pixai):
    """Owner report 2026-07-25, three hand-fix attempts: the tracker showed status `failed`
    and error `failed`, which is the whole message. PixAI's own status string for a failed
    generation genuinely IS just "failed" and `outputs` came back empty -- so forwarding
    their string faithfully (which we already do) still leaves the user with one useless
    word. When they tell us nothing, say something ourselves: it ran, it failed, and the
    credits come back."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "9101", "type": "generate", "label": "Fixed"})
    monkeypatch.setattr(core, "generation_status",
                        lambda s, tid: {"status": "failed", "phase": "failed",
                                        "paid_credit": 8000, "started": True, "reason": ""})

    body = cli.get("/api/task-status?task_id=9101").get_json()
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["9101"]
    msg = str(job.get("error") or "")
    assert msg.strip().lower() != "failed", "still just the bare word: {!r}".format(msg)
    assert "refund" in msg.lower(), "must say the credits come back: {!r}".format(msg)
    assert "refund" in str(body).lower()


def test_failed_before_it_ever_started_says_so_rather_than_blaming_the_render(tmp_path, monkeypatch, pixai):
    """The other failure mode, and it needs the opposite message: a task PixAI never
    dispatched did not 'fail to render' -- it was never picked up. Telling someone their
    render failed when no worker ever took it sends them debugging their prompt."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "9102", "type": "generate", "label": "Enhanced"})
    monkeypatch.setattr(core, "generation_status",
                        lambda s, tid: {"status": "cancelled", "phase": "failed",
                                        "paid_credit": 1200, "started": False,
                                        "reason": "waiting timeout"})

    cli.get("/api/task-status?task_id=9102")
    msg = str({j["job_id"]: j for j in core.read_jobs(tmp_path)}["9102"].get("error") or "")
    assert "waiting timeout" in msg, "PixAI's own reason must still lead: {!r}".format(msg)
    assert "never started" in msg.lower(), "must distinguish never-dispatched: {!r}".format(msg)


def test_a_reason_from_pixai_is_never_buried_under_our_own_words(tmp_path, monkeypatch, pixai):
    """When PixAI DOES explain itself, their explanation is the useful part and must not be
    replaced by our generic copy."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "9103", "type": "generate", "label": "Generated"})
    monkeypatch.setattr(core, "generation_status",
                        lambda s, tid: {"status": "failed", "phase": "failed",
                                        "paid_credit": 0, "started": True,
                                        "reason": "content policy"})
    cli.get("/api/task-status?task_id=9103")
    msg = str({j["job_id"]: j for j in core.read_jobs(tmp_path)}["9103"].get("error") or "")
    assert "content policy" in msg


# ---- "it goes right to generated and spins until done": say WHICH phase it's in ----
# The Activity tray renders from /api/jobs (the server-side log), never from
# /api/task-status's response, so `started` only reaches the tray if this route writes it
# down. Writing it server-side is also what makes the signal identical on both hosts:
# the gallery's Jobs.poll(), the Loom's pollShot/pollTaskWithCeiling and
# mg-generate-drawer.js's own poll ALL hit this one route.

def _queued(tid_status="waiting", started=False):
    return lambda s, tid: {"status": tid_status, "phase": "running", "paid_credit": None,
                           "started": started, "reason": ""}


def _no_estimate(monkeypatch):
    """Silence the queue-estimate side trip for the phase-only tests below."""
    monkeypatch.setattr(core, "_task_detail_query", lambda s, tid: {"parameters": {}})
    monkeypatch.setattr(core, "queue_wait_estimate", lambda *a, **k: None)


def _raw_lines(tmp_path):
    return core._reconstruct_jobs(tmp_path)[2]


def test_a_queued_job_is_recorded_as_not_yet_started(tmp_path, monkeypatch, pixai):
    """The whole point: a task PixAI accepted but has not dispatched must reach the tray as
    QUEUED, not as an indefinite rendering spinner. `started` was already in this route's
    JSON response and nothing wrote it to the log, so the tray -- which reads the log --
    could not tell the two apart."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "7001", "type": "generate", "label": "Generated"})
    monkeypatch.setattr(core, "generation_status", _queued())
    _no_estimate(monkeypatch)

    cli.get("/api/task-status?task_id=7001")
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["7001"]
    assert job.get("started") is False, \
        "the job log has no queued/rendering distinction: {!r}".format(job)
    assert job["status"] == "running", "queued is a phase of running, not a new status"


def test_the_phase_is_written_once_per_change_not_once_per_poll(tmp_path, monkeypatch, pixai):
    """Four different pollers hit this route every 3s per job. A write per poll would add
    1,200+ lines for one task PixAI sits on for its full ~60-minute reap window, and would
    refresh `ts` so often the ongoing orphan-reconciliation sweep could never see the job
    cross JOBS_ORPHAN_SWEEP_AGE."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "7002", "type": "generate", "label": "Generated"})
    monkeypatch.setattr(core, "generation_status", _queued())
    _no_estimate(monkeypatch)

    before = _raw_lines(tmp_path)
    for _ in range(6):
        cli.get("/api/task-status?task_id=7002")
    assert _raw_lines(tmp_path) - before == 1, \
        "six identical polls wrote {} log lines instead of one".format(
            _raw_lines(tmp_path) - before)


def test_a_worker_picking_the_job_up_flips_the_recorded_phase(tmp_path, monkeypatch, pixai):
    """The other half of "once per change": when PixAI finally assigns a worker, the tray
    has to stop saying queued. One more line, and only one."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "7003", "type": "generate", "label": "Generated"})
    monkeypatch.setattr(core, "generation_status", _queued())
    _no_estimate(monkeypatch)
    cli.get("/api/task-status?task_id=7003")

    monkeypatch.setattr(core, "generation_status", _queued("processing", started=True))
    before = _raw_lines(tmp_path)
    cli.get("/api/task-status?task_id=7003")
    cli.get("/api/task-status?task_id=7003")
    assert _raw_lines(tmp_path) - before == 1
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["7003"]
    assert job.get("started") is True, "still reads as queued while a worker renders it"


def test_a_terminal_poll_writes_no_running_phase_and_forgets_the_task(tmp_path, monkeypatch, pixai):
    """Two things at once. The done branch must not also emit a `running` phase line (the
    terminal-stickiness in _reconstruct_jobs would ignore it, but it is still noise), and
    the in-process de-dupe map must DROP the finished task -- otherwise it grows for the
    whole life of the server, one entry per generation ever polled. The observable proof of
    the drop is that a later queued sighting of the same id writes again."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "7004", "type": "generate", "label": "Generated"})
    monkeypatch.setattr(core, "generation_status", _queued())
    _no_estimate(monkeypatch)
    cli.get("/api/task-status?task_id=7004")

    monkeypatch.setattr(core, "generation_status",
                        lambda s, tid: {"status": "completed", "phase": "done",
                                        "paid_credit": 0, "started": True, "reason": ""})
    monkeypatch.setattr(core, "collect_generation",
                        lambda *a, **k: {"media_ids": ["m1"], "saved": 1, "is_video": False})
    before = _raw_lines(tmp_path)
    cli.get("/api/task-status?task_id=7004")
    assert _raw_lines(tmp_path) - before == 1, "the done poll wrote more than its done event"

    monkeypatch.setattr(core, "generation_status", _queued())
    before = _raw_lines(tmp_path)
    cli.get("/api/task-status?task_id=7004")
    assert _raw_lines(tmp_path) - before == 1, \
        "the finished task was never dropped from the de-dupe map -- it leaks one entry " \
        "per generation for the life of the process"
    assert {j["job_id"]: j for j in core.read_jobs(tmp_path)}["7004"]["status"] == "done", \
        "a late running event must not revert a finished job (terminal stickiness)"


def test_pixais_own_queue_estimate_is_recorded_when_a_job_is_seen_queued(tmp_path, monkeypatch, pixai):
    """PixAI publishes no progress on a task at all, but it does publish the queue wait it
    shows beside its own Generate button. Recorded once, off the task's real submit
    parameters, so the tray can put "PixAI estimated ~27s" next to an elapsed time the
    owner can compare it against."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "7005", "type": "generate", "label": "Generated"})
    monkeypatch.setattr(core, "generation_status", _queued())
    asked = []
    monkeypatch.setattr(core, "_task_detail_query",
                        lambda s, tid: {"parameters": {"modelId": "1983308862240288769",
                                                       "priority": 1000}})
    monkeypatch.setattr(core, "queue_wait_estimate",
                        lambda s, pri, mid: asked.append((pri, mid)) or 27)

    for _ in range(3):
        cli.get("/api/task-status?task_id=7005")
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["7005"]
    assert job.get("eta_seconds") == 27, "no queue estimate recorded: {!r}".format(job)
    assert asked == [(1000, "1983308862240288769")], \
        "the estimate must be fetched ONCE, with the task's own priority + model: " \
        "{!r}".format(asked)


def test_a_job_that_starts_before_its_first_poll_costs_no_extra_calls(tmp_path, monkeypatch, pixai):
    """The common case. A generation a worker takes immediately was never queued from this
    route's point of view, so it must not trigger the two read-only calls the estimate
    needs -- politeness to their servers is the whole reason this is once-per-job and not
    per-poll."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "7006", "type": "generate", "label": "Generated"})
    monkeypatch.setattr(core, "generation_status", _queued("processing", started=True))
    monkeypatch.setattr(core, "_task_detail_query",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not ask")))
    monkeypatch.setattr(core, "queue_wait_estimate",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not ask")))

    cli.get("/api/task-status?task_id=7006")
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["7006"]
    assert job.get("started") is True and "eta_seconds" not in job


def test_an_unavailable_estimate_still_ships_the_phase(tmp_path, monkeypatch, pixai):
    """The ETA is optional and the phase is not. If wait-time (or the parameter lookup it
    needs) fails, the queued signal must still be written -- degrading to "no number" is
    fine, degrading to "no phase" puts the spinner back."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "7007", "type": "generate", "label": "Generated"})
    monkeypatch.setattr(core, "generation_status", _queued())
    monkeypatch.setattr(core, "_task_detail_query",
                        lambda *a, **k: (_ for _ in ()).throw(core.PixAIError("boom")))

    cli.get("/api/task-status?task_id=7007")
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["7007"]
    assert job.get("started") is False, \
        "a failed estimate lookup swallowed the phase signal too: {!r}".format(job)
    assert "eta_seconds" not in job


def test_a_slow_eta_fetch_cannot_overwrite_a_newer_rendering_phase(tmp_path, monkeypatch, pixai):
    """RACE, found in code review 2026-07-25. _note_gen_phase claimed the phase under a lock
    but then released it before doing the SLOW part (two network calls for the queue ETA) and
    the write. So:

      poll A  sees queued -> claims it -> stalls in the ETA fetch
      worker  starts the job
      poll B  sees rendering -> claims it -> writes {started: True} immediately
      poll A  wakes -> writes its stale {started: False, eta_seconds: N} ON TOP

    and because the seen-map now records True, every later poll returns early at the dedupe
    check, so nothing ever corrects it: a job that is really rendering shows QUEUED for its
    entire life. The window is exactly two network calls wide and real jobs start in a few
    seconds, so this is the common case, not a corner.

    Drives the real route twice concurrently with the ETA fetch held open, which is the only
    way to actually order the interleaving."""
    cli = _authed_client(tmp_path)
    cli.post("/api/jobs", json={"job_id": "race1", "type": "generate", "label": "Generated"})

    phases = iter([False, True])          # first poll: queued. second: rendering.
    monkeypatch.setattr(core, "generation_status", lambda s, tid: {
        "status": "running", "phase": "running", "paid_credit": None,
        "started": next(phases, True), "reason": ""})

    held, b_done = threading.Event(), threading.Event()

    def _slow_estimate(*a, **k):
        """Stand in for the two real calls: block until poll B has finished writing."""
        b_done.wait(timeout=5)
        return 42
    monkeypatch.setattr(core, "_task_detail_query", lambda *a, **k: {"parameters": {}})
    monkeypatch.setattr(core, "queue_wait_estimate", _slow_estimate)

    a_err = []
    def _poll_a():
        try: cli.get("/api/task-status?task_id=race1")
        except Exception as e: a_err.append(e)
        finally: held.set()

    ta = threading.Thread(target=_poll_a); ta.start()
    time.sleep(0.15)                       # let A claim the phase and enter the ETA fetch
    cli.get("/api/task-status?task_id=race1")   # poll B: sees rendering, writes it
    b_done.set()
    ta.join(timeout=6)
    held.wait(timeout=6)
    assert not a_err, a_err

    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["race1"]
    assert job.get("started") is True, (
        "a rendering job was left showing queued by the slow poll's stale write: {!r}".format(job))

# ---------------------------------------------------------------------------
# resolve_interrupted_local_jobs: a server-owned job cannot outlive the server
# ---------------------------------------------------------------------------

def test_sweep_resolves_a_server_owned_job_left_running(tmp_path):
    """The owner's production case: a panel job killed mid-flight shows 'running' forever.

    resolve_orphan_jobs() cannot fix it -- that works by asking PixAI about a task id, and a
    panel job has none. Nothing else ever writes the terminal event, because the process that
    would have written it is gone."""
    core.append_job_event(tmp_path, "panel-3d49d9bffea2", status="running",
                          type="panel", label="Rebuild the Similar index")

    assert core.resolve_interrupted_local_jobs(tmp_path) == 1

    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["panel-3d49d9bffea2"]
    assert job["status"] == "failed"
    assert job["status"] in core._JOBS_TERMINAL      # so it leaves the live list
    assert "Interrupted" in job["error"]
    assert "corrupted" in job["error"]               # tells the user it is safe to re-run


def test_sweep_leaves_cli_jobs_alone(tmp_path):
    """A `cli-` job belongs to a SEPARATE process with its own lifetime.

    This is the one that would do real damage: the server knows nothing about a command running
    in a terminal, so sweeping it would brand a genuinely-running job dead and, worse, do it
    while the job is still writing its own events."""
    core.append_job_event(tmp_path, "cli-abc123", status="running", type="cli", label="--sync")

    assert core.resolve_interrupted_local_jobs(tmp_path) == 0
    assert core.read_jobs(tmp_path)[0]["status"] == "running"


def test_sweep_leaves_pixai_generate_jobs_alone(tmp_path):
    """Numeric ids are PixAI tasks and belong to resolve_orphan_jobs(), which can actually ASK
    whether they finished. Reaping them here would destroy a real running generation's record
    and lose the reward/claim that follows it."""
    core.append_job_event(tmp_path, "1672848509142493791", status="running", type="generate")

    assert core.resolve_interrupted_local_jobs(tmp_path) == 0
    assert core.read_jobs(tmp_path)[0]["status"] == "running"


def test_sweep_is_idempotent_and_skips_finished_jobs(tmp_path):
    """Runs on every boot, so a second pass must be a no-op -- otherwise each restart appends
    another failure event to a job that was already resolved."""
    core.append_job_event(tmp_path, "panel-aaa", status="running", type="panel")
    core.append_job_event(tmp_path, "panel-bbb", status="done", type="panel")
    core.append_job_event(tmp_path, "bulkdel-ccc", status="done_with_errors", type="panel")

    assert core.resolve_interrupted_local_jobs(tmp_path) == 1     # only panel-aaa
    assert core.resolve_interrupted_local_jobs(tmp_path) == 0     # nothing left to do

    by_id = {j["job_id"]: j for j in core.read_jobs(tmp_path)}
    assert by_id["panel-bbb"]["status"] == "done"                 # untouched
    assert by_id["bulkdel-ccc"]["status"] == "done_with_errors"   # untouched


def test_sweep_covers_every_server_owned_prefix(tmp_path):
    """import-/bulkdel- are spawned by the server exactly like panel-, so all three must be
    swept. Pinned as a set so adding a new server-spawned prefix without adding it here fails
    loudly rather than leaving a whole job class stuck at 'running'."""
    assert set(core._JOBS_SERVER_OWNED_PREFIXES) == {"panel-", "import-", "bulkdel-"}
    for jid in ("panel-1", "import-2", "bulkdel-3"):
        core.append_job_event(tmp_path, jid, status="running", type="panel")

    assert core.resolve_interrupted_local_jobs(tmp_path) == 3


def test_a_surviving_subprocess_can_still_correct_a_premature_failure(tmp_path):
    """The documented imprecision, pinned so the safety net cannot silently disappear.

    A panel job is a SUBPROCESS, so a server restart while one genuinely runs marks it failed
    early. That self-corrects only because _reconstruct_jobs() blocks a NON-terminal record from
    overwriting a terminal one but permits terminal -> terminal. If that ever changed, this sweep
    would start permanently mislabelling live work."""
    core.append_job_event(tmp_path, "panel-live", status="running", type="panel")
    core.resolve_interrupted_local_jobs(tmp_path)
    assert core.read_jobs(tmp_path)[0]["status"] == "failed"

    core.append_job_event(tmp_path, "panel-live", status="done")   # the subprocess survived
    assert core.read_jobs(tmp_path)[0]["status"] == "done"


def _status_client(tmp_path):
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {"media_id": "m1"}])
    return login_test_client(create_app(tmp_path))


def test_task_status_reports_our_OWN_defect_as_failed(tmp_path, monkeypatch, pixai):
    """A bug in this poll cannot come good on a retry, so it must not be reported as a job
    that is merely still running.

    The broad handler beneath is deliberate and stays: a PixAI 5xx/429/timeout answers
    'running' precisely so mg-notify's poller keeps trying instead of bricking the card with
    a false failure. But it caught programming errors too, so a genuinely broken poll looked
    identical to a slow one -- for the full 6h polling ceiling, with nothing saying otherwise.
    """
    def boom(*_a, **_k):
        raise TypeError("unsupported operand type(s)")
    monkeypatch.setattr(core, "generation_status", boom)
    d = _status_client(tmp_path).get("/api/task-status?task_id=T1").get_json()
    assert d["phase"] == "failed", d
    assert "internal error" in (d.get("error") or "").lower()


def test_task_status_still_treats_a_pixai_blip_as_non_terminal(tmp_path, monkeypatch, pixai):
    """The other half, so the above can't be 'achieved' by making everything terminal."""
    def blip(*_a, **_k):
        raise core.PixAIError("502 Bad Gateway")
    monkeypatch.setattr(core, "generation_status", blip)
    d = _status_client(tmp_path).get("/api/task-status?task_id=T2").get_json()
    assert d["phase"] == "running", "a transient blip must stay non-terminal: %s" % d


# ---------------------------------------------------------------------------
# The claim's own tracker line (owner ask, 2026-08-31). The activity tray renders
# SERVER truth -- /api/jobs off jobs.jsonl -- so a claim's line is written by the
# claim route itself, at the one seam both claim triggers (the header pill and the
# mascot popup) funnel through.
# ---------------------------------------------------------------------------

def _claim_stubs(monkeypatch, rewards):
    """A claimable account with no network: the route's session, its reward list, and a
    claim call that succeeds. Nothing here reaches PixAI."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "list_claims", lambda s: rewards)
    monkeypatch.setattr(core, "claim_reward", lambda s, cid: {"id": cid})


def _claim_rows(cli):
    return [j for j in cli.get("/api/jobs").get_json()["jobs"] if j.get("type") == "claim"]


def test_a_successful_claim_writes_one_tracker_line(tmp_path, monkeypatch):
    _claim_stubs(monkeypatch, [
        {"id": "pixai-daily-credits", "amount": 30000, "canClaim": True},
        {"id": "agent-daily-stamina", "amount": 20, "canClaim": True}])
    cli = _authed_client(tmp_path)
    d = cli.post("/api/claim").get_json()
    assert (d["claimed"], d["credits"]) == (2, 30000)
    rows = _claim_rows(cli)
    assert len(rows) == 1, rows
    row = rows[0]
    # Born terminal: claiming is instantaneous, so the row never passes through running.
    assert row["status"] == "done"
    assert row["label"] == "+30,000 credits claimed"
    assert row["job_id"].startswith("claim-")
    assert row["ts"] > 0
    # It carries no spend/media fields -- "no field, no row" is the tracker's own rule,
    # and a claim is a gain, so a COST row would misreport it.
    assert "paid_credit" not in row and not row.get("media_ids")


def test_a_second_claim_gets_its_own_line(tmp_path, monkeypatch):
    """Each claim keeps its own line rather than overwriting the last -- the log collapses
    by job_id, so a fixed id would have made the tracker show only the most recent claim."""
    _claim_stubs(monkeypatch, [{"id": "pixai-daily-credits", "amount": 100, "canClaim": True}])
    cli = _authed_client(tmp_path)
    cli.post("/api/claim")
    cli.post("/api/claim")
    rows = _claim_rows(cli)
    assert len(rows) == 2
    assert len({r["job_id"] for r in rows}) == 2


def test_a_claim_that_claims_nothing_writes_no_line(tmp_path, monkeypatch):
    """Nothing happened, so nothing is reported. The tracker is a record of events, not of
    button presses."""
    _claim_stubs(monkeypatch, [{"id": "pixai-daily-credits", "amount": 30000, "canClaim": False}])
    cli = _authed_client(tmp_path)
    assert cli.post("/api/claim").get_json()["claimed"] == 0
    assert _claim_rows(cli) == []


def test_a_failed_claim_writes_no_line(tmp_path, monkeypatch):
    """An upstream failure answers with its error and leaves no trail of a claim that never
    landed."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "list_claims",
                        lambda s: (_ for _ in ()).throw(core.PixAIError("claims are down")))
    cli = _authed_client(tmp_path)
    assert cli.post("/api/claim").get_json()["error"]
    assert _claim_rows(cli) == []


def test_claim_line_grammar(tmp_path):
    """The wording, in one place. Credits lead when there are any -- grouped, like every
    other figure in the tray -- and a stamina-only claim counts rewards instead of
    announcing "+0 credits", which would read as a bug rather than a fact."""
    from moonglade_gallery import claim_job_label
    assert claim_job_label(1, 30000) == "+30,000 credits claimed"
    assert claim_job_label(2, 500) == "+500 credits claimed"
    assert claim_job_label(1, 0) == "1 reward claimed"
    assert claim_job_label(3, 0) == "3 rewards claimed"
    assert claim_job_label(1, None) == "1 reward claimed"      # junk degrades, never raises
    assert claim_job_label(0, "nonsense") == "1 reward claimed"
