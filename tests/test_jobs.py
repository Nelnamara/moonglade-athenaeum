"""Job activity log + the Jobs card's endpoints.

The log is an APPEND-ONLY jsonl the web "Jobs" card reads: every writer (Flask
server, panel subprocess, CLI-from-terminal) appends one line per job event, and
read_jobs() collapses by job_id (last event wins; a terminal done/failed is sticky).
This is the paper trail that survives a reload -- so these tests pin the collapse,
stickiness, dismissal, ageing, cap, and compaction behavior, plus the register /
list / dismiss endpoints and their localhost gate.
"""
import time

import pixai_gallery_backup as core
from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_client


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
    # api_jobs()'s own body -- see pixai_gallery.py's _enforce_front_door())
    r = _lan(cli, "get", "/api/jobs")
    assert r.status_code == 401 and "jobs" not in r.get_json()
    # register + dismiss are refused from the LAN
    assert _lan(cli, "post", "/api/jobs", json={"job_id": "x"}).status_code == 401
    assert _lan(cli, "post", "/api/jobs/dismiss", json={"job_id": "j1"}).status_code == 401
    # ...and nothing was written by those rejected calls
    assert [j["job_id"] for j in core.read_jobs(tmp_path)] == ["j1"]
