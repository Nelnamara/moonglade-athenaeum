"""The live-event WebSocket watcher (--watch). The real graphql-transport-ws transport is
mocked so nothing touches the network: we verify the handshake frames we SEND and that a
`next` frame is dispatched to on_event."""
import asyncio
import json

import websockets

import moonglade_backup as core


class _FakeWS:
    """Stands in for a graphql-transport-ws connection: an async context manager that
    records sent frames and replays a scripted server sequence from recv()."""
    def __init__(self, script):
        self.script = list(script)
        self.sent = []
        self._i = 0

    async def send(self, m):
        self.sent.append(json.loads(m))

    async def recv(self):
        if self._i >= len(self.script):
            raise AssertionError("recv() called past the scripted frames")
        f = self.script[self._i]
        self._i += 1
        return f

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _run(monkeypatch, script):
    ws = _FakeWS(script)
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: ws)
    got = []
    asyncio.run(core._watch_events_async("Bearer sk-x", got.append, None))
    return ws, got


def test_watch_handshake_and_dispatch(monkeypatch):
    script = [
        json.dumps({"type": "connection_ack"}),
        json.dumps({"type": "next", "payload": {"data": {"personalEvents": {
            "taskUpdated": {"id": "T1", "status": "completed", "mediaId": "M1",
                            "media": {"urls": [{"url": "https://cdn/x"}]}},
            "newNotification": None}}}}),
        json.dumps({"type": "complete"}),
    ]
    ws, got = _run(monkeypatch, script)
    # we sent connection_init (with the token) then a subscribe for personalEvents
    assert ws.sent[0]["type"] == "connection_init"
    assert ws.sent[0]["payload"]["Authorization"] == "Bearer sk-x"
    assert ws.sent[1]["type"] == "subscribe"
    assert "personalEvents" in ws.sent[1]["payload"]["query"]
    # on_event saw the 'subscribed' marker then the real taskUpdated event
    assert got[0].get("__meta__") == "subscribed"
    tu = [e for e in got if e.get("taskUpdated")]
    assert tu and tu[0]["taskUpdated"]["status"] == "completed"


def test_watch_answers_ping_and_raises_on_error(monkeypatch):
    # server ping -> we must pong; then an error frame must raise (subscription rejected)
    script = [
        json.dumps({"type": "connection_ack"}),
        json.dumps({"type": "ping"}),
        json.dumps({"type": "error", "payload": [{"message": "bad field"}]}),
    ]
    ws = _FakeWS(script)
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: ws)
    try:
        asyncio.run(core._watch_events_async("Bearer x", lambda e: None, None))
        assert False, "expected PixAIError on the error frame"
    except core.PixAIError as e:
        assert "rejected" in str(e)
    assert any(m.get("type") == "pong" for m in ws.sent)   # replied to the ping


def test_watch_backup_mirrors_completed_only(monkeypatch, tmp_path):
    """--watch-backup mirrors a task the instant it hits 'completed' (and only then), once."""
    import threading
    from types import SimpleNamespace

    # feed a full lifecycle through a fake transport, synchronously
    async def fake_watch(auth, on_event, seconds):
        on_event({"__meta__": "subscribed"})
        on_event({"taskUpdated": {"id": "T9", "status": "waiting"}})
        on_event({"taskUpdated": {"id": "T9", "status": "running"}})
        on_event({"taskUpdated": {"id": "T9", "status": "completed", "mediaId": "M9"}})
        on_event({"taskUpdated": {"id": "T9", "status": "completed", "mediaId": "M9"}})  # dup
    monkeypatch.setattr(core, "_watch_events_async", fake_watch)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _Sess())

    class _FakeThread:   # run the mirror synchronously so the test is deterministic
        def __init__(self, target=None, args=(), daemon=None):
            self._t, self._a = target, args
        def start(self):
            self._t(*self._a)
    monkeypatch.setattr(threading, "Thread", _FakeThread)

    calls = []
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: calls.append(tid) or {"saved": 4})

    args = SimpleNamespace(token=None, watch_seconds=0, watch_backup=True, out=str(tmp_path))
    core.run_watch(args)
    assert calls == ["T9"]   # mirrored exactly once, only on 'completed' (waiting/running ignored)


class _Sess:
    headers = {"Authorization": "Bearer sk-x"}


def test_watch_no_ack_raises(monkeypatch):
    ws = _FakeWS([json.dumps({"type": "connection_error", "payload": "nope"})])
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: ws)
    try:
        asyncio.run(core._watch_events_async("Bearer x", lambda e: None, None))
        assert False, "expected PixAIError when no connection_ack"
    except core.PixAIError as e:
        assert "handshake" in str(e).lower()


# --- Staleness watchdog ----------------------------------------------------------
# The real incident this guards against: the WebSocket never errored and never sent
# a close frame -- it just stopped producing ANY frame, including PixAI's own
# keepalive pings, for ~21 minutes while real generations were finishing. Before this
# fix, the receive loop's `await ws.recv()` had no timeout at all, so a socket in
# that state hung the loop forever: `connected` stayed True and `last_error` stayed
# None indefinitely (verified live via `/api/watch/status`), and nothing in
# `_watch_loop`'s outer reconnect/backoff logic ever ran because no exception was
# ever raised to trigger it.

class _SilentAfterAckWS(_FakeWS):
    """Answers the connection_ack handshake normally, then goes silent forever on
    every subsequent recv() -- exactly a zombie connection that looks open but
    produces nothing, not even a ping."""
    async def recv(self):
        if self._i < len(self.script):
            return await super().recv()
        # No more scripted frames: block far longer than any timeout under test,
        # so this only resolves if something is broken and the wait_for around it
        # failed to cancel us.
        await asyncio.sleep(10)
        raise AssertionError("recv() blocked past its wait_for timeout -- the "
                              "staleness watchdog did not fire")


def test_watch_raises_when_connection_goes_stale_despite_looking_healthy(monkeypatch):
    """Fail-first case: reproduces 'connected but silently dead'. A tiny
    _WS_STALE_TIMEOUT stands in for the real several-minute one so the test itself
    stays fast; the mechanism under test is the same either way -- ws.recv() is
    awaited with a timeout, and a lapse raises WatchStaleError instead of hanging."""
    monkeypatch.setattr(core, "_WS_STALE_TIMEOUT", 0.05)
    ws = _SilentAfterAckWS([json.dumps({"type": "connection_ack"})])
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: ws)
    got = []
    try:
        asyncio.run(core._watch_events_async("Bearer x", got.append, None))
        assert False, "expected WatchStaleError when the socket goes silent"
    except core.WatchStaleError as e:
        assert "no frame" in str(e).lower()             # says what happened
        assert str(core._WS_STALE_TIMEOUT) in str(e)    # names the timeout it hit
        # WatchStaleError must still be a PixAIError so nothing that already does a
        # bare `except PixAIError` (or `except Exception`, like _watch_loop) needs
        # to change to start handling it.
        assert isinstance(e, core.PixAIError)
    # subscribed fired first -- this is genuinely the "looked connected" case, not a
    # handshake failure.
    assert got and got[0].get("__meta__") == "subscribed"


def test_watch_pings_reset_the_staleness_clock(monkeypatch):
    """Companion/negative case: a steady trickle of frames -- even bare keepalive
    pings, no real taskUpdated events -- must NOT trip the watchdog, since a quiet
    account (no generations running) is a normal, healthy state, not a stale one."""
    # THE NUMBERS ARE THE TEST -- do not "simplify" them.
    #
    # The watchdog is a per-frame `asyncio.wait_for(ws.recv(), timeout=_WS_STALE_TIMEOUT)`, so
    # what proves the clock RESETS per frame is: every individual gap stays under the timeout
    # while the TOTAL run comfortably exceeds it. A cumulative clock would lapse partway
    # through. Raising the timeout without also lengthening the script would make this pass
    # even with the reset logic deleted -- vacuous, not robust.
    #
    # Ratios chosen for that meaning AND against CI flake. This previously ran a 0.05s timeout
    # against a 0.01s pace: only a 5x per-frame margin, which a loaded runner (three suites in
    # parallel) overshoots, failing a test about staleness for reasons that have nothing to do
    # with staleness. Now 0.02s per frame against a 0.5s timeout -- a 25x margin, so a single
    # frame would have to stall 25x its sleep to trip it -- while 40 frames total ~0.8s, still
    # well past the 0.5s timeout a cumulative clock would have hit around frame 25.
    PACE, TIMEOUT, PINGS = 0.02, 0.5, 40
    assert PACE * PINGS > TIMEOUT, "script must outlast the timeout or this proves nothing"
    monkeypatch.setattr(core, "_WS_STALE_TIMEOUT", TIMEOUT)
    script = [json.dumps({"type": "connection_ack"})]
    script += [json.dumps({"type": "ping"})] * PINGS
    script += [json.dumps({"type": "complete"})]

    class _PacedWS(_FakeWS):
        async def recv(self):
            await asyncio.sleep(PACE)   # well inside the timeout -- never lets it lapse
            return await super().recv()

    ws = _PacedWS(script)
    monkeypatch.setattr(websockets, "connect", lambda *a, **k: ws)
    got = []
    asyncio.run(core._watch_events_async("Bearer x", got.append, None))   # must not raise
    assert any(m.get("type") == "pong" for m in ws.sent)   # still answered every ping


def test_mirror_and_reconcile_agree_on_what_done_means():
    """The live mirror's COLLECT branch and its RECONCILE branch read the same event, so they
    must agree on which statuses mean finished.

    They did not. Collect matched `status == _WS_DONE_STATUS` -- one exact string -- while
    reconcile accepted `status in _GEN_DONE`, which is five. A done-status PixAI spelled any
    other way would therefore resolve the Activity row while silently NOT mirroring the file,
    which looks exactly like the "my video never came into the gallery" report that found this
    (2026-07-26) and is just as invisible after the fact.

    Kept as a source check even though the handler became directly callable on 2026-09-07
    (it moved out of _watch_loop's inner `while True` into the _watch_on_event closure, and
    is exposed as app.extensions["mg_watch_on_event"]): the behavioural tests below drive the
    ROW the frames produce, while this pins the one line that decides whether the FILE gets
    collected at all -- a branch whose failure mode is silence, not a wrong row."""
    import pathlib as _p
    src = _p.Path(__file__).resolve().parent.parent / "moonglade_gallery.py"
    text = src.read_text(encoding="utf-8")

    i = text.index("def _watch_on_event(ev):")
    loop = text[i:i + 4000]

    assert "if status in core._GEN_DONE and tid and tid not in _watch_backed:" in loop, (
        "the mirror's collect branch must accept every _GEN_DONE status, not one exact string")
    assert "status == core._WS_DONE_STATUS" not in loop, (
        "the single-status collect trigger is back -- see this test's docstring")

    # And the constant it now shares really is the broader set.
    assert core._WS_DONE_STATUS in core._GEN_DONE
    assert len(core._GEN_DONE) > 1


def test_catchup_sweep_is_bounded_rate_limited_and_off_thread():
    """The mirror back-fills what it missed while disconnected, and does so safely.

    A push mirror is blind whenever its socket is down, and reconnecting does not replay the gap
    -- so before this, a drop stranded those generations until someone ran a manual sync. The
    owner's objection was the right one: he should not have to press a button for it.

    But this is UNATTENDED network activity on his machine, so the guardrails matter as much as
    the feature. This test pins the guardrails at SOURCE level; its behavioural companion
    (test_catchup_backfills_absent_media_skips_present_and_rate_limits) drives the same closure
    through the app.extensions["mg_watch_catchup"] seam and proves the gap-fill / skip / rate-limit
    actually run. _watch_catchup is invoked only from a background thread the suite never starts
    (MOONGLADE_DISABLE_WATCH), so both angles are worth keeping."""
    import pathlib as _p
    src = _p.Path(__file__).resolve().parent.parent / "moonglade_gallery.py"
    text = src.read_text(encoding="utf-8")

    assert "def _watch_catchup(reason):" in text

    i = text.index("def _watch_catchup(reason):")
    body = text[i:i + 4400]

    # Bounded: one page, never a history walk. WATCH_CATCHUP_TASKS is the page size passed to
    # page_variables; the account id now rides the client (USER_ID retired from page_variables),
    # so the catchup threads it explicitly rather than leaning on a module global.
    assert "WATCH_CATCHUP_TASKS = 30" in text
    assert "core.page_variables(" in body
    assert "WATCH_CATCHUP_TASKS, core._client_of(session).user_id" in body

    # Rate-limited: a reconnect storm must not become a request storm.
    assert "WATCH_CATCHUP_MIN_GAP" in body and "_catchup_at" in body

    # Only collects what is genuinely absent -- re-collecting present media is pure waste.
    # Asked of the ids the catalog is KEYED by, never of media_ids_for (which names a batch
    # task's composite grid and a video task's poster still -- ids no row ever holds, so the
    # test was false forever and every sweep relisted the same tasks). A video summary names
    # none of a video's cataloged ids at all, so that shape is asked by task id instead.
    assert "core.cataloged_media_ids(node)" in body
    assert "core.media_ids_for(" not in body
    assert "core._is_video_task_node(node):" in body
    assert "get_row_by_task(db_path, tid)" in body
    assert "if all(get_row(db_path, m) for m in mids):" in body

    # Paced, so it stays polite to PixAI's servers.
    assert "_time.sleep(1.0)" in body

    # Cannot kill the watcher thread that calls it.
    assert "except Exception as e:" in body

    # Only finished tasks are candidates.
    assert "core._GEN_DONE" in body

    # And it is invoked OFF the WebSocket event loop, at both trigger points.
    assert 'threading.Thread(target=_watch_catchup, args=("startup",), daemon=True).start()' in text
    assert 'threading.Thread(target=_watch_catchup, args=("reconnect",),' in text


def test_catchup_does_not_run_in_the_test_suite():
    """Belt and braces: the sweep must never fire during tests, or the suite would hit PixAI with
    whatever real credentials are on the machine. It is reachable only from the watcher thread,
    which conftest disables via MOONGLADE_DISABLE_WATCH."""
    import os
    assert os.environ.get("MOONGLADE_DISABLE_WATCH") == "1"


def test_catchup_backfills_absent_media_skips_present_and_rate_limits(monkeypatch, tmp_path):
    """BEHAVIOURAL companion to the source-level guard above: actually EXECUTE the self-heal
    sweep through the mg_watch_catchup seam and prove the recovery the ROADMAP requires —
    "the piece must appear on its own, no manual sync." It must:
      - COLLECT a finished task whose media the catalog is missing (the gap-fill);
      - SKIP a finished task already present (idempotent — re-collecting is pure waste),
        a non-done task, and a done task with no media;
      - RATE-LIMIT: a second sweep inside WATCH_CATCHUP_MIN_GAP is a no-op, even though the
        gap notionally still exists.
    (The live stop-server / generate-while-down / restart recipe stays the owner's to run;
    this pins the logic that recipe exercises so it can't silently regress.)"""
    import time
    import moonglade_gallery as mg
    from moonglade_gallery import create_app

    app = create_app(tmp_path)
    catchup = app.extensions["mg_watch_catchup"]        # the new seam

    # One page of recent tasks: finished+absent (collect), finished+present (skip),
    # running (skip), finished+no-media (skip).
    edges = [
        {"node": {"id": "T_absent", "status": "completed"}},
        {"node": {"id": "T_present", "status": "completed"}},
        {"node": {"id": "T_running", "status": "running"}},
        {"node": {"id": "T_nomedia", "status": "completed"}},
    ]
    media = {"T_absent": ["M_absent"], "T_present": ["M_present"],
             "T_running": ["M_run"], "T_nomedia": []}
    present = {"M_present"}                             # only this media is already catalogued

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _Sess())
    monkeypatch.setattr(core, "gql", lambda *a, **k: {})
    monkeypatch.setattr(core, "page_variables", lambda *a, **k: {})
    monkeypatch.setattr(core, "find_connection", lambda *a, **k: {"edges": edges})
    monkeypatch.setattr(core, "cataloged_media_ids",
                        lambda node: media.get(str(node.get("id")), []))
    monkeypatch.setattr(mg, "get_row", lambda db_path, m: (object() if m in present else None))
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)   # keep the paced sweep fast

    collected = []
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: collected.append(str(tid)) or {"saved": 1})

    catchup("startup")
    assert collected == ["T_absent"]     # ONLY the finished task whose media was missing

    # Rate limit: a second sweep inside WATCH_CATCHUP_MIN_GAP does nothing — the gap still
    # "exists" (get_row still reports M_absent absent), but the floor suppresses the sweep.
    catchup("reconnect")
    assert collected == ["T_absent"]     # no second collection


# ---------------------------------------------------------------------------------------
# A run started on the WEBSITE gets an Activity row of its own (owner ruling, 2026-09-07)
#
#   "I often have things going from the app and website, so the generations I start on the
#    website I would like to see on the app with the usual spinner."
#
# This reverses the 2026-07-06 contract the mirror was built on ("never invents one for a
# task generated on the website"). tests/test_jobs.py's
# test_mirror_never_invents_a_job_for_a_task_we_do_not_track still holds and must: the
# reversal is scoped to the two paths that hold a live frame, so _watch_mirror called on its
# own for an untracked task still writes nothing at all.
#
# Driven through app.extensions["mg_watch_on_event"], the frame handler create_app exposes
# for exactly this. Nothing here touches the network: the "event stream" is a list of the
# taskUpdated frames the real socket carries (measured lifecycle: waiting -> running ->
# completed), fed in by hand, and every collect is stubbed.
# ---------------------------------------------------------------------------------------

def _watch_app(tmp_path):
    """A create_app instance for the frame-handler seam. conftest's MOONGLADE_DISABLE_WATCH
    keeps the real watcher thread (and therefore the real socket) from ever starting."""
    from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog
    save_catalog(tmp_path / "catalog.db",
                 [{f: "" for f in CATALOG_FIELDS} | {
                     "media_id": "1", "filename": "a_1.png",
                     "created_at": "2025-01-01T00:00:00"}])
    return create_app(tmp_path)


def _frame(tid, status, **extra):
    """One `taskUpdated` frame in the shape _WS_SUBSCRIPTION actually delivers."""
    return {"taskUpdated": dict({"id": tid, "status": status}, **extra)}


def _jobs(tmp_path):
    return {j["job_id"]: j for j in core.read_jobs(tmp_path)}


def _sync_threads(monkeypatch):
    """Run every daemon thread the handler spawns inline, so the test is deterministic."""
    import threading

    class _FakeThread:
        def __init__(self, target=None, args=(), daemon=None):
            self._t, self._a = target, args

        def start(self):
            self._t(*self._a)
    monkeypatch.setattr(threading, "Thread", _FakeThread)


def test_a_waiting_frame_for_an_unknown_task_creates_a_queued_website_row(tmp_path):
    """(a) The first thing the socket says about a website run is `waiting`, and that is
    enough to put the row on screen -- queued, spinner stopped, exactly as an app run reads
    in the same phase.

    Bite: drop the _website_job_seen call from the handler and the Activity window stays
    empty until the pictures simply appear in the library, which is the state the owner
    objected to."""
    app = _watch_app(tmp_path)
    app.extensions["mg_watch_on_event"](_frame("W1", "waiting"))

    job = _jobs(tmp_path)["W1"]
    assert job["status"] == "running" and job["started"] is False, (
        "a waiting task must read as QUEUED -- status running with started false, the same "
        "two fields ActivityRow reads for an app run")
    assert job["type"] == "generate", "the row must be an ordinary generate job"
    assert job["source"] == "pixai", (
        "the source mark is the ONLY thing that may distinguish this row from an app run")
    assert job["label"] == "From the website", (
        "the live subscription carries no `parameters`, so the generic label is the honest one")


def test_a_running_frame_flips_the_website_row_out_of_queued(tmp_path):
    """(b) waiting -> running is the moment a worker picked it up. The same flip
    /api/task-status writes for an app run (_note_gen_phase), so the row starts spinning."""
    app = _watch_app(tmp_path)
    on_event = app.extensions["mg_watch_on_event"]
    on_event(_frame("W2", "waiting"))
    assert _jobs(tmp_path)["W2"]["started"] is False

    on_event(_frame("W2", "running"))

    job = _jobs(tmp_path)["W2"]
    assert job["started"] is True, "the row is still marked queued while it is rendering"
    assert job["status"] == "running"
    assert job["source"] == "pixai" and job["label"] == "From the website", (
        "the phase update must not blank the fields the create event wrote")


def test_the_whole_lifecycle_closes_one_website_row_with_its_media(tmp_path, monkeypatch):
    """(c) The full measured lifecycle plus the mirror receipt: waiting -> running ->
    completed leaves ONE done row carrying the media ids the mirror collected -- which is
    what puts the pictures in the window, since ActivityRow builds its thumbnail from
    (j.media_ids||[])[0].

    The ORDER is the load-bearing part. _log_mirrored_media writes only for a task that
    already has a row, so the row has to be created synchronously on the frame before the
    mirror thread starts. Reverse that and this row goes terminal with no media and renders
    blank forever -- the exact 2026-07-24 bug in a new place."""
    app = _watch_app(tmp_path)
    _sync_threads(monkeypatch)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _Sess())
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: {"media_ids": ["MA", "MB"], "saved": 2,
                                                  "is_video": False})

    on_event = app.extensions["mg_watch_on_event"]
    on_event(_frame("W3", "waiting"))
    on_event(_frame("W3", "running"))
    on_event(_frame("W3", "completed", mediaId="MA"))

    rows = core.read_jobs(tmp_path)
    assert [r["job_id"] for r in rows] == ["W3"], (
        "one run must be one row -- the job id IS the task id on every writer for exactly this")
    job = rows[0]
    assert job["status"] == "done"
    assert job["media_ids"] == ["MA", "MB"], (
        "the mirror collected the media but the row never recorded it -- a permanently blank "
        "card, and seeing the pictures was the whole point of the feature")
    assert job["source"] == "pixai" and job["type"] == "generate"


def test_a_failed_frame_closes_the_website_row_as_failed(tmp_path):
    """The other terminal. _reconcile_job already knew how to write it and needed no change;
    what changed is that there is now a row for it to write to."""
    app = _watch_app(tmp_path)
    on_event = app.extensions["mg_watch_on_event"]
    on_event(_frame("W4", "waiting"))
    on_event(_frame("W4", "failed"))

    job = _jobs(tmp_path)["W4"]
    assert job["status"] == "failed" and job["error"] == "failed"


def test_the_catchup_writes_a_done_row_for_a_website_task_it_had_to_collect(tmp_path, monkeypatch):
    """(d) The restart case. The socket was down while the task finished, so the event path
    never saw a frame for it -- the catch-up finds it, collects it, and must leave the window
    telling the same story it would have told live: a finished website run, with its media.

    Born done deliberately: nothing is left to spin for something that finished while the app
    was closed, and a row arriving at 'running' would sit there until the orphan sweep got
    round to it."""
    import time
    import moonglade_gallery as mg
    app = _watch_app(tmp_path)
    catchup = app.extensions["mg_watch_catchup"]

    # A live TaskSummary names the media it holds; since the 2026-09-07 catch-up fix the
    # "already collected?" test resolves THOSE ids (cataloged_media_ids), so the fake node
    # carries one, and the by-task lookup a video would use answers nothing.
    edges = [{"node": {"id": "W5", "status": "completed", "mediaId": "M5", "batchMediaIds": None}}]
    monkeypatch.setattr(mg, "get_row_by_task", lambda db_path, t: None)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _Sess())
    monkeypatch.setattr(core, "gql", lambda *a, **k: {})
    monkeypatch.setattr(core, "page_variables", lambda *a, **k: {})
    monkeypatch.setattr(core, "find_connection", lambda *a, **k: {"edges": edges})
    monkeypatch.setattr(core, "media_ids_for", lambda node: ["M5"])
    monkeypatch.setattr(mg, "get_row", lambda db_path, m: None)     # nothing catalogued yet
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: {"media_ids": ["M5"], "saved": 1,
                                                  "is_video": False})

    catchup("startup")

    rows = core.read_jobs(tmp_path)
    assert [r["job_id"] for r in rows] == ["W5"], "the catch-up wrote more than one row"
    job = rows[0]
    assert job["status"] == "done" and job["media_ids"] == ["M5"]
    assert job["source"] == "pixai" and job["type"] == "generate"
    assert job["label"] == "From the website"


def test_the_event_path_and_the_catchup_converge_on_one_row(tmp_path, monkeypatch):
    """Both writers can see the same task -- a frame arrives and a catch-up sweep fires on
    the same reconnect. The job id is derived from the task id (it IS the task id, as an app
    run's is), so the second writer finds the first one's row and adds none. Two rows for one
    generation is the failure that derivation exists to prevent."""
    import time
    import moonglade_gallery as mg
    app = _watch_app(tmp_path)
    _sync_threads(monkeypatch)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _Sess())
    monkeypatch.setattr(core, "gql", lambda *a, **k: {})
    monkeypatch.setattr(core, "page_variables", lambda *a, **k: {})
    monkeypatch.setattr(core, "find_connection", lambda *a, **k:
                        {"edges": [{"node": {"id": "W6", "status": "completed"}}]})
    monkeypatch.setattr(core, "media_ids_for", lambda node: ["M6"])
    monkeypatch.setattr(mg, "get_row", lambda db_path, m: None)
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: {"media_ids": ["M6"], "saved": 1,
                                                  "is_video": False})

    app.extensions["mg_watch_on_event"](_frame("W6", "waiting"))
    app.extensions["mg_watch_catchup"]("startup")

    rows = core.read_jobs(tmp_path)
    assert [r["job_id"] for r in rows] == ["W6"], "one generation produced two Activity rows"
    assert rows[0]["source"] == "pixai"


def test_an_app_run_is_untouched_by_any_of_this(tmp_path, monkeypatch):
    """(e) The regression guard. An app run registers its own row through /api/jobs the
    moment it is submitted -- source 'web', its own label, its own requested count. Every
    frame for it must leave all of that alone: it is not a website run and must not be marked
    as one, or the source mark would be a lie on the owner's own dock runs."""
    app = _watch_app(tmp_path)
    _sync_threads(monkeypatch)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _Sess())
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: {"media_ids": ["MX"], "saved": 1,
                                                  "is_video": False})
    # exactly what api_jobs_register writes for a dock submit
    core.append_job_event(tmp_path, "A1", status="running", type="generate",
                          label="Generated", source="web", count=2)

    on_event = app.extensions["mg_watch_on_event"]
    on_event(_frame("A1", "waiting"))
    on_event(_frame("A1", "running"))
    on_event(_frame("A1", "completed", mediaId="MX"))

    rows = core.read_jobs(tmp_path)
    assert [r["job_id"] for r in rows] == ["A1"]
    job = rows[0]
    assert job["source"] == "web", "an app run was re-branded as a website run"
    assert job["label"] == "Generated", "an app run's own label was overwritten"
    assert job["count"] == 2, "the app row's own fields were clobbered"
    assert job["status"] == "done" and job["media_ids"] == ["MX"], (
        "the ordinary app-run resolution broke while adding the website one")
    assert "started" not in job, (
        "a phase this app never observed was invented on an app row -- `started` is written "
        "by /api/task-status's own poll, and absent means UNKNOWN to ActivityRow")


def test_a_dismissed_website_row_is_not_resurrected_by_a_later_frame(tmp_path):
    """A repeated 'completed' frame (they do repeat, and a reconnect replays), or any later
    frame at all, must not put back a row the owner cleared. The existence check reads the
    RAW log rather than read_jobs() for exactly this: dismissed is still a row."""
    app = _watch_app(tmp_path)
    on_event = app.extensions["mg_watch_on_event"]
    on_event(_frame("W7", "waiting"))
    core.append_job_event(tmp_path, "W7", dismissed=True)

    on_event(_frame("W7", "running"))
    on_event(_frame("W7", "waiting"))

    assert core.read_jobs(tmp_path) == [], "a dismissed website row came back"


def test_a_frame_that_carries_a_prompt_labels_the_row_with_its_first_words(tmp_path):
    """The label rule. _WS_SUBSCRIPTION does not ask for `parameters` as of 2026-09-07, so
    every LIVE frame takes the generic fallback -- this pins the behaviour for the paths that
    can carry one (the catch-up's task nodes, and any later widening of that subscription),
    so the fallback stays a fallback rather than the only thing that works."""
    app = _watch_app(tmp_path)
    on_event = app.extensions["mg_watch_on_event"]

    on_event(_frame("W8", "waiting",
                    parameters={"prompts": "a sleeping bear in a moonlit library"}))
    assert _jobs(tmp_path)["W8"]["label"] == "a sleeping bear in a moonlit library"

    # A long prompt is cut to its first words -- the row's label line is one ellipsised line
    # and a whole prompt in it would just be a wall of truncated text.
    on_event(_frame("W8b", "waiting",
                    parameters={"prompt": "one two three four five six seven eight nine ten"}))
    assert _jobs(tmp_path)["W8b"]["label"] == "one two three four five six seven eight"

    # A video task keeps its prompt inside its own block, never at the top level.
    on_event(_frame("W8c", "waiting",
                    parameters={"i2vPro": {"prompts": "the bear turns a page"}}))
    assert _jobs(tmp_path)["W8c"]["label"] == "the bear turns a page"


def test_the_row_writer_cannot_kill_the_socket(tmp_path, monkeypatch):
    """Same fail-soft discipline as every other writer on this path: the handler runs on the
    WebSocket's own event loop, so a logging problem must never propagate out of it."""
    app = _watch_app(tmp_path)

    def _boom(*a, **k):
        raise RuntimeError("job log read exploded")
    monkeypatch.setattr(core, "_reconstruct_jobs", _boom)

    app.extensions["mg_watch_on_event"](_frame("W9", "waiting"))   # must not raise




def test_catchup_tests_the_ids_the_catalog_actually_holds(monkeypatch, tmp_path, caplog):
    """The catch-up relisted the same finished tasks forever, and said in the log they had
    never been mirrored while their rows sat complete in catalog.db (owner: "the app no
    longer picks up tracking of generations run from the website", 2026-09-07).

    Cause: "already collected?" was asked of `media_ids_for`, i.e. every media id the feed
    summary NAMES -- and on the two commonest shapes those are ids no row is ever keyed by.
    A batch task's `mediaId` is the composite preview grid (the pictures are the batch
    members); a video task's is the poster still (the row is keyed by the mp4, an id only
    getTaskById carries). Both tested absent every sweep, so every sweep relisted them and
    re-collected them for nothing.

    Drives the REAL resolution (no stub over `cataloged_media_ids`) across the four shapes
    that matter, on nodes shaped like the live `TaskSummary`: id / status / mediaId /
    batchMediaIds / i2vProModel, no `outputs` -- because the summary genuinely has none."""
    import time
    import moonglade_gallery as mg
    from moonglade_gallery import create_app

    app = create_app(tmp_path)
    catchup = app.extensions["mg_watch_catchup"]

    edges = [
        # (a) a 4-up batch, every member already cataloged. Nothing holds GRID_1.
        {"node": {"id": "T_batch_done", "status": "completed", "mediaId": "GRID_1",
                  "batchMediaIds": ["B1", "B2", "B3", "B4"]}},
        # (b) the same batch with one member missing -- EVERY id must have a row, so a
        # half-collected batch is still finished off.
        {"node": {"id": "T_batch_half", "status": "completed", "mediaId": "GRID_2",
                  "batchMediaIds": ["H1", "H2", "H3", "H4"]}},
        # (c) a video task whose real output is cataloged. POSTER_1 is the still, never a
        # row; the mp4's row carries the task id, which is the only thing a summary shares
        # with it.
        {"node": {"id": "T_video_done", "status": "completed", "mediaId": "POSTER_1",
                  "i2vProModel": "v4.0.1"}},
        {"node": {"id": "T_video_new", "status": "completed", "mediaId": "POSTER_2",
                  "i2vProModel": "v4.0.1"}},
        # (d) every member deleted from PixAI: the ids come through as holes, so there is
        # nothing left to collect -- and `mediaId` (the grid) is NOT a fallback here.
        {"node": {"id": "T_batch_gone", "status": "completed", "mediaId": "GRID_3",
                  "batchMediaIds": [None, None, None, None]}},
        # the plain single-image gap-fill this sweep has always existed for
        {"node": {"id": "T_single_new", "status": "completed", "mediaId": "S_new",
                  "batchMediaIds": None}},
    ]
    present = {"B1", "B2", "B3", "B4", "H1", "H2", "H4", "V_real"}
    by_task = {"T_video_done": {"media_id": "V_real", "task_id": "T_video_done",
                                "is_video": "1"}}

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: _Sess())
    monkeypatch.setattr(core, "gql", lambda *a, **k: {})
    monkeypatch.setattr(core, "page_variables", lambda *a, **k: {})
    monkeypatch.setattr(core, "find_connection", lambda *a, **k: {"edges": edges})
    monkeypatch.setattr(mg, "get_row",
                        lambda db_path, m: ({"media_id": m} if m in present else None))
    monkeypatch.setattr(mg, "get_row_by_task", lambda db_path, t: by_task.get(str(t)))
    monkeypatch.setattr(time, "sleep", lambda *a, **k: None)

    collected = []
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: collected.append(str(tid)) or {"saved": 1})

    with caplog.at_level("INFO"):
        catchup("startup")

    # The cataloged batch and the cataloged video are NOT relisted; the half batch, the
    # uncollected video and the new single image are.
    assert collected == ["T_batch_half", "T_video_new", "T_single_new"]

    # And the warning names only those, without claiming a half-collected batch was never
    # mirrored.
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "T_batch_done" not in warnings[0]
    assert "T_video_done" not in warnings[0]
    assert "T_batch_gone" not in warnings[0]
    assert "3 finished task(s) are missing media from the catalog" in warnings[0]
    assert "never mirrored" not in warnings[0]
