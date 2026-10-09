"""Sessions R + Y (lane R): delivery (R4b, drift 126) and TASK told once (R2c, drift 124).

PixAI's socket already carries `newNotification` to the live mirror. The mirror now counts it
(in memory, id only -- never its words) and the one poll every open tab already runs
(/api/jobs) carries that count, so the badge moves live with no new loop. A reconnect is
counted the same way, so the client can re-read the count. TASK is never an inbox row: a job
Activity has never seen joins Activity tagged as PixAI's, and a job Activity holds as failed
that PixAI says finished gets a note.

No network: the frame handler is driven through app.extensions["mg_watch_on_event"], and PixAI
is the `pixai` fixture's FakePixAI."""
import pytest

from moonglade import backup as core
from moonglade import inbox
from moonglade.gallery import CATALOG_FIELDS, create_app, save_catalog
from tests.conftest import login_test_client


@pytest.fixture(autouse=True)
def _fresh():
    inbox.clear_caches()
    yield
    inbox.clear_caches()


def _app(tmp_path):
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "1", "filename": "a_1.png", "created_at": "2025-01-01T00:00:00"}])
    return create_app(tmp_path)


def _row(nid, ntype="COMMENT", unread=True, content="nice"):
    return {"id": nid, "type": ntype, "kind": "ACTOR_ARTWORK", "unread": unread,
            "createdAt": "2026-10-03T11:00:00Z", "updatedAt": "2026-10-03T11:00:00Z",
            "relatedUsers": [{"id": "u1", "displayName": "kurone", "activeDecorationIds": []}],
            "artwork": {"id": "1788621522581677948", "title": "Moonwell Vigil"},
            "content": content}


def _page(*rows):
    return {"data": list(rows), "pageInfo": {"startCursor": "a", "hasPreviousPage": False}}


def test_a_push_is_counted_by_id_and_never_keeps_its_words():
    inbox.note_push({"id": "n7", "title": "kurone: a stranger's words",
                     "createdAt": "2026-10-03T11:00:00Z", "userId": "u-test"})
    st = inbox.live_state()
    assert st["seq"] == 1
    assert "stranger" not in repr(inbox._live), "a push's title was kept"


def test_pushed_since_reads_the_newest_rows_once_and_answers_only_newer_pushes(pixai):
    inbox.note_push({"id": "n1"})
    inbox.note_push({"id": "n2"})
    pixai.on("/user/me/notifications/", _page(_row("n2"), _row("n1", ntype="LIKE")))
    out = inbox.pushed_since(pixai, 1)
    assert [i["id"] for i in out["items"]] == ["n2"] and out["seq"] == 2
    assert len(pixai.calls) == 1 and pixai.calls[0].verb == "rest_get"
    assert inbox.pushed_since(pixai, 2)["items"] == []
    assert len(pixai.calls) == 1, "nothing new to tell must cost no read"


def test_the_mirror_counts_a_notification_frame_and_a_reconnect(tmp_path):
    app = _app(tmp_path)
    # A connect asks for the catch-up sweep, and the app's own spawn starts a real thread that
    # waits WATCH_SUBSCRIBE_SETTLE and then reads PixAI -- by then inside whichever test is
    # running, through THAT test's network stand-in. It once landed in
    # test_the_pushed_route_answers_the_new_rows below as a `persisted` call that test never
    # made. The sweep is not what this test is about (dev/tests/test_watch.py drives it), so
    # the request is recorded and nothing is started.
    sweeps = []
    app.extensions["mg_watch_catchup_env"]["spawn"] = sweeps.append
    on_event = app.extensions["mg_watch_on_event"]
    on_event({"__meta__": "subscribed"})
    on_event({"newNotification": {"id": "n9", "title": "x", "createdAt": "", "userId": "u"}})
    st = inbox.live_state()
    assert st["seq"] == 1 and st["connects"] == 1
    assert len(sweeps) == 1, "the connect asked for its catch-up sweep through the stand-in"


def test_the_jobs_poll_carries_the_live_count(tmp_path, pixai):
    inbox.note_push({"id": "n1"})
    cli = login_test_client(_app(tmp_path))
    d = cli.get("/api/jobs").get_json()
    assert d["inbox"] == {"seq": 1, "connects": 0}


def test_the_pushed_route_answers_the_new_rows(tmp_path, pixai):
    inbox.note_push({"id": "n2"})
    pixai.on("/user/me/notifications/", _page(_row("n2")))
    cli = login_test_client(_app(tmp_path))
    d = cli.get("/api/inbox/pushed?after=0").get_json()
    assert [i["id"] for i in d["items"]] == ["n2"]
    assert {c.verb for c in pixai.calls} == {"rest_get"}


# ---------------------------------------------------------------------------
# TASK is told once: by Activity
# ---------------------------------------------------------------------------

def _task(nid, tid, at="2026-10-03T11:00:00Z"):
    return {"id": nid, "type": "GENERATION_TASK_COMPLETED", "kind": "REF_ITEM", "unread": True,
            "createdAt": at, "updatedAt": at, "refType": "TASK", "refId": tid,
            "refTitle": "a quiet library", "relatedUsers": []}


def test_a_finished_job_activity_never_saw_joins_activity_as_pixais(tmp_path, pixai, monkeypatch):
    monkeypatch.setattr(inbox, "_now_ts", lambda: 1791025200.0)       # 2026-10-03 11:00 UTC
    pixai.on("/user/me/notifications/", _page(_task("n1", "2062832974899841293")))
    cli = login_test_client(_app(tmp_path))
    assert cli.get("/api/inbox").get_json()["items"] == []            # never an inbox row
    job = {j["job_id"]: j for j in core.read_jobs(tmp_path)}["2062832974899841293"]
    assert job["status"] == "done" and job["source"] == "pixai" and job["via"] == "inbox"
    # Review nit 7: the notification's own words never reach the disk; the label is fixed.
    assert job["label"] == "Generation"
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert b"a quiet library" not in p.read_bytes(), p


def test_an_old_finished_job_is_not_resurrected(tmp_path, pixai, monkeypatch):
    monkeypatch.setattr(inbox, "_now_ts", lambda: 1791025200.0)
    pixai.on("/user/me/notifications/", _page(_task("n1", "2062832974899841293",
                                                    at="2026-09-01T00:00:00Z")))
    cli = login_test_client(_app(tmp_path))
    cli.get("/api/inbox")
    assert "2062832974899841293" not in {j["job_id"] for j in core.read_jobs(tmp_path)}


def test_a_job_activity_calls_failed_that_pixai_finished_gets_a_note(tmp_path, pixai, monkeypatch):
    monkeypatch.setattr(inbox, "_now_ts", lambda: 1791025200.0)
    core.append_job_event(tmp_path, "2062832974899841293", status="failed", type="generate",
                          label="a quiet library", source="web", error="timed out")
    pixai.on("/user/me/notifications/", _page(_task("n1", "2062832974899841293")))
    cli = login_test_client(_app(tmp_path))
    cli.get("/api/inbox")
    job = {j["job_id"]: j for j in cli.get("/api/jobs").get_json()["jobs"]}["2062832974899841293"]
    assert job["status"] == "failed" and job["pixai_says"] == "done"
