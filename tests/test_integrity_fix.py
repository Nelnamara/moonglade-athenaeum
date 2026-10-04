"""The Broken files list's fixes (Session W, W3c/W4c): the targeted runner.

  - RE-DOWNLOAD (an empty or cut-short file PixAI still has) goes through the app's own
    single-media download path, moonglade_backup.resolve_media + download, ONE attempt.
    The new bytes land in a staging file first; only when they are a whole file of the
    same kind does an atomic replace put them over the broken one. Nothing is deleted.
  - REBUILD (a missing or empty thumbnail) is local: the same make_thumbnail the gallery
    uses, no network.
  - THE RUNNER REFUSES AN ARCHIVE-ONLY ROW BY ITSELF. A picture PixAI no longer has is the
    only copy; the runner reads that from the catalog, whatever the client sent, before it
    reaches for the network. READ_ONLY blocks re-downloads, never rebuilds.
  - When a run ends, only the rows it touched are checked again (read-only), and the
    report's lines and counts for them are rewritten.

Every network call here is a fake: no test reaches PixAI.
"""
import json
import time

import pytest
import requests

import moonglade_backup as core
import moonglade_gallery as g
import moonglade_integrity as integ
from moonglade_gallery import create_app
from tests.conftest import login_test_client, with_csrf
from tests.test_integrity import _png, _webp
from tests.test_integrity_broken import _broken_library


class _Resp:
    def __init__(self, status=200, body=b"", ctype="image/png", obj=None):
        self.status_code = status
        self._body = body
        self._obj = obj
        self.headers = {"Content-Type": ctype, "Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("{} error".format(self.status_code))

    def json(self):
        return self._obj

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), 7):          # small chunks: the byte bar moves
            yield self._body[i:i + 7]


class FakeMediaSession:
    """What resolve_media and download see: a media object per id, and the file at its url."""

    def __init__(self, files):
        self.files = files                                # media id -> (bytes, content type)
        self.calls = []

    def get(self, url, stream=False, timeout=None):
        self.calls.append(url)
        for mid, (body, ctype) in self.files.items():
            if url == core.MEDIA_BASE.format(id=mid):
                return _Resp(obj={"urls": [{"variant": "PUBLIC", "url": "https://cdn.test/" + mid}]})
            if url == "https://cdn.test/" + mid:
                return _Resp(body=body, ctype=ctype)
        return _Resp(status=404)


def _no_network():
    raise AssertionError("this path must not reach the network")


def _bytes(out, rel):
    return (out / rel).read_bytes()


# ---------------------------------------------------------------------------
# THE RULE: an archive-only row is refused by the runner itself
# ---------------------------------------------------------------------------

def test_the_runner_refuses_an_archive_only_row_by_itself(tmp_path):
    """109 is broken AND PixAI no longer has it. Even asked directly -- as a client that
    ignored the missing button would ask -- the runner refuses before any network call,
    and the only copy is left exactly as it is."""
    out = _broken_library(tmp_path)
    before = _bytes(out, "images/p_t1_109.png")
    session = FakeMediaSession({"109": (_png(), "image/png")})
    res = integ.redownload_one(out, out / "catalog.db", "109", session_factory=lambda: session)
    assert res["ok"] is False and res["refused"] == "archive_only"
    assert session.calls == []
    assert _bytes(out, "images/p_t1_109.png") == before


def test_a_per_image_deletion_is_archive_only_too(tmp_path):
    out = _broken_library(tmp_path)
    session = FakeMediaSession({"112": (_png(), "image/png")})
    res = integ.redownload_one(out, out / "catalog.db", "112", session_factory=lambda: session)
    assert res["refused"] == "archive_only" and session.calls == []


def test_fix_all_through_the_route_refuses_it_too(tmp_path, monkeypatch):
    out = _broken_library(tmp_path)
    session = FakeMediaSession({"109": (_png(), "image/png")})
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: session)
    app = create_app(out)
    cli = login_test_client(app)
    d = cli.post("/api/integrity/fix", json=with_csrf(cli, {"ids": ["109"]})).get_json()
    assert d["started"] is True
    app.extensions["mg_integrity_fix"].wait(10)
    st = cli.get("/api/integrity/fix/status").get_json()
    assert [r["refused"] for r in st["results"]] == ["archive_only"]
    assert session.calls == []
    assert _bytes(out, "images/p_t1_109.png") == b""


# ---------------------------------------------------------------------------
# Re-download: the existing single-media path, then verify, then an atomic replace
# ---------------------------------------------------------------------------

def test_a_zero_byte_file_is_re_downloaded_over_itself(tmp_path):
    out = _broken_library(tmp_path)
    fresh = _png(4, 4)
    session = FakeMediaSession({"102": (fresh, "image/png")})
    seen = []
    res = integ.redownload_one(out, out / "catalog.db", "102", session_factory=lambda: session,
                               on_bytes=lambda n, total: seen.append((n, total)))
    assert res["ok"] is True and res["action"] == "redownload"
    assert _bytes(out, "images/p_t1_102.png") == fresh     # same name, new bytes
    assert seen and seen[-1] == (len(fresh), len(fresh))   # the byte bar's true fraction
    # one resolve, one file fetch: one attempt
    assert session.calls == [core.MEDIA_BASE.format(id="102"), "https://cdn.test/102"]
    # the fresh file gets a thumbnail; the staging folder is left empty
    assert (out / "gallery" / "thumbs" / "102.jpg").stat().st_size > 0
    assert not list((out / "gallery" / integ.STAGING_DIRNAME).glob("*"))


def test_a_cut_short_file_is_replaced_in_place(tmp_path):
    out = _broken_library(tmp_path)
    fresh = _png(3, 3)
    session = FakeMediaSession({"103": (fresh, "image/png")})
    res = integ.redownload_one(out, out / "catalog.db", "103", session_factory=lambda: session)
    assert res["ok"] is True
    assert _bytes(out, "images/p_t1_103.png") == fresh
    assert integ.structural_problem(out / "images/p_t1_103.png") is None


def test_a_missing_file_is_re_downloaded_to_the_catalogs_own_path(tmp_path):
    """105's catalog row names a bare file and nothing is on disk. The backup records most
    pictures by bare name in images/, so that is where the fresh copy lands -- through the
    same staging file and the same checks as any other re-download."""
    out = _broken_library(tmp_path)
    fresh = _png(4, 4)
    session = FakeMediaSession({"105": (fresh, "image/png")})
    res = integ.redownload_one(out, out / "catalog.db", "105", session_factory=lambda: session)
    assert res["ok"] is True and res["action"] == "redownload"
    assert _bytes(out, "images/p_t1_105.png") == fresh
    assert (out / "gallery" / "thumbs" / "105.jpg").stat().st_size > 0
    assert not list((out / "gallery" / integ.STAGING_DIRNAME).glob("*"))


def test_a_missing_file_with_a_folder_in_its_path_goes_back_there(tmp_path):
    out = _broken_library(tmp_path)
    from tests.test_integrity import _row as _r
    g.save_catalog(out / "catalog.db", [_r(media_id="105", filename="2026-01/p_t1_105.png")])
    session = FakeMediaSession({"105": (_png(3, 3), "image/png")})
    res = integ.redownload_one(out, out / "catalog.db", "105", session_factory=lambda: session)
    assert res["ok"] is True
    assert _bytes(out, "2026-01/p_t1_105.png") == _png(3, 3)


@pytest.mark.parametrize("crafted", [
    "../escape_105.png",                    # climbs out of the library
    "images/../../escape_105.png",          # climbs out after a folder
    "C:/Windows/Temp/p_t1_105.png",         # a drive path
    "/tmp/p_t1_105.png",                    # a rooted path
    "gallery/thumbs/p_t1_105.png",          # inside a tree every walk prunes
    "_deleted/p_t1_105.png",                # the Trash
    "images/p_t1_999.png",                  # a name that is another picture's
    "images/p_t1_105.exe",                  # not a picture
])
def test_a_crafted_path_is_refused_before_anything_is_fetched(tmp_path, crafted):
    out = _broken_library(tmp_path / "lib")
    from tests.test_integrity import _row as _r
    g.save_catalog(out / "catalog.db", [_r(media_id="105", filename=crafted)])
    before = {p for p in tmp_path.rglob("*")}
    res = integ.redownload_one(out, out / "catalog.db", "105", session_factory=_no_network)
    assert res["ok"] is False and res["refused"] == "bad_path", crafted
    assert {p for p in tmp_path.rglob("*")} == before, "a refused path wrote something"


def test_the_path_rule_on_its_own(tmp_path):
    """missing_target: the one place a missing file's destination is decided."""
    out = tmp_path
    (out / "images").mkdir()
    row = {"media_id": "105", "filename": "p_t1_105.png", "is_video": ""}
    assert integ.missing_target(out, row) == ((out / "images" / "p_t1_105.png").resolve(), "")
    vid = {"media_id": "108", "filename": "p_t1_108.mp4", "is_video": "1"}
    assert integ.missing_target(out, vid)[0] == (out / "videos" / "p_t1_108.mp4").resolve()
    (out / "images" / "p_t1_105.png").write_bytes(b"x")       # something is there now
    assert integ.missing_target(out, row) == (None, "occupied")
    assert integ.missing_target(out, {"media_id": "105", "filename": ""}) == (None, "bad_path")


def test_a_missing_file_pixai_no_longer_has_is_refused_by_the_runner(tmp_path):
    out = _broken_library(tmp_path)
    from tests.test_integrity import _row as _r
    g.save_catalog(out / "catalog.db", [_r(media_id="113", filename="p_t1_113.png",
                                           deleted_remote="1")])
    integ.verify_library(out, out / "catalog.db", deep=True)
    res = integ.redownload_one(out, out / "catalog.db", "113", session_factory=_no_network)
    assert res["refused"] == "archive_only"
    assert not (out / "images" / "p_t1_113.png").exists()


def test_new_bytes_that_do_not_check_out_leave_the_old_file_alone(tmp_path):
    out = _broken_library(tmp_path)
    before = _bytes(out, "images/p_t1_103.png")
    torn = _png(5, 5)[:-12]
    session = FakeMediaSession({"103": (torn, "image/png")})
    res = integ.redownload_one(out, out / "catalog.db", "103", session_factory=lambda: session)
    assert res["ok"] is False and res["refused"] == "unverified"
    assert _bytes(out, "images/p_t1_103.png") == before
    assert not list((out / "gallery" / integ.STAGING_DIRNAME).glob("*"))


def test_a_page_that_is_not_a_picture_never_lands(tmp_path):
    """A 200 that is an error page carries no picture's first bytes: not "unknown, so fine"."""
    out = _broken_library(tmp_path)
    session = FakeMediaSession({"102": (b"<html>try again later</html>", "image/png")})
    res = integ.redownload_one(out, out / "catalog.db", "102", session_factory=lambda: session)
    assert res["refused"] == "unverified"
    assert _bytes(out, "images/p_t1_102.png") == b""


def test_a_different_kind_of_file_leaves_the_old_one_alone(tmp_path):
    out = _broken_library(tmp_path)
    session = FakeMediaSession({"102": (_webp(), "image/webp")})
    res = integ.redownload_one(out, out / "catalog.db", "102", session_factory=lambda: session)
    assert res["ok"] is False and res["refused"] == "type_differs"
    assert _bytes(out, "images/p_t1_102.png") == b""


def test_pixai_returning_nothing_is_said_plainly(tmp_path):
    out = _broken_library(tmp_path)
    session = FakeMediaSession({})                       # every url answers 404
    res = integ.redownload_one(out, out / "catalog.db", "102", session_factory=lambda: session)
    assert res["ok"] is False
    assert res["error"] == "Couldn't re-download. PixAI didn't return the file."
    assert len(session.calls) == 1                       # one attempt, no retry


def test_one_attempt_per_file(tmp_path):
    out = _broken_library(tmp_path)

    class Flaky(FakeMediaSession):
        def get(self, url, stream=False, timeout=None):
            if url.startswith("https://cdn.test/"):
                self.calls.append(url)
                raise requests.ConnectionError("reset")
            return super().get(url, stream=stream, timeout=timeout)

    session = Flaky({"102": (_png(), "image/png")})
    res = integ.redownload_one(out, out / "catalog.db", "102", session_factory=lambda: session)
    assert res["ok"] is False
    assert session.calls.count("https://cdn.test/102") == 1


def test_a_sound_file_is_never_overwritten(tmp_path):
    out = _broken_library(tmp_path)
    before = _bytes(out, "images/p_t1_101.png")
    res = integ.redownload_one(out, out / "catalog.db", "101", session_factory=_no_network)
    assert res["ok"] is True and res["note"] == "already sound"
    assert _bytes(out, "images/p_t1_101.png") == before


def test_read_only_blocks_re_downloads_but_not_rebuilds(tmp_path, monkeypatch):
    out = _broken_library(tmp_path)
    monkeypatch.setattr(core, "READ_ONLY", True)
    res = integ.redownload_one(out, out / "catalog.db", "102", session_factory=_no_network)
    assert res["ok"] is False and res["refused"] == "read_only"
    res = integ.rebuild_one(out, out / "catalog.db", "106")
    assert res["ok"] is True
    assert (out / "gallery" / "thumbs" / "106.jpg").stat().st_size > 0


# ---------------------------------------------------------------------------
# Rebuild: local only
# ---------------------------------------------------------------------------

def test_a_rebuild_makes_the_thumbnail_here(tmp_path):
    out = _broken_library(tmp_path)
    for mid in ("106", "107"):
        res = integ.rebuild_one(out, out / "catalog.db", mid)
        assert res["ok"] is True and res["action"] == "rebuild", mid
        assert (out / "gallery" / "thumbs" / (mid + ".jpg")).stat().st_size > 0


def test_a_rebuild_never_touches_a_broken_file(tmp_path):
    out = _broken_library(tmp_path)
    res = integ.rebuild_one(out, out / "catalog.db", "102")
    assert res["ok"] is False and res["refused"] == "file_broken"


def test_a_lost_mark_is_respected_by_the_runner(tmp_path):
    out = _broken_library(tmp_path)
    integ.set_mark(out, "102", "lost")
    res = integ.fix_one(out, out / "catalog.db", "102", session_factory=_no_network)
    assert res["ok"] is False and res["refused"] == "marked_lost"


# ---------------------------------------------------------------------------
# The run: in order, progress, Stop, then a re-check of the touched rows only
# ---------------------------------------------------------------------------

def _runner(out, session, events=None):
    def log_job(job_id, **fields):
        if events is not None:
            events.append(dict(fields, job_id=job_id))
    return integ.FixRunner(out, out / "catalog.db", log_job=log_job,
                           session_factory=lambda: session)


def test_a_run_fixes_what_it_can_and_rechecks_only_those_rows(tmp_path):
    out = _broken_library(tmp_path)
    summary_before = integ.read_summary(out)
    session = FakeMediaSession({"102": (_png(4, 4), "image/png")})
    events = []
    run = _runner(out, session, events)
    st = run.start(["102", "106", "109"])
    assert st["running"] is True and st["total"] == 3
    run.wait(10)
    st = run.status()
    assert st["running"] is False and st["done"] == 3
    assert [(r["media_id"], r["ok"]) for r in st["results"]] == [
        ("102", True), ("106", True), ("109", False)]
    assert (st["fixed"], st["failed"]) == (2, 1)
    # the touched rows were checked again; an untouched one keeps its line as it was
    lines = {ln[0]: ln[1] for ln in integ.read_lines(out)}
    assert "102" not in lines and "106" not in lines
    assert lines["109"] == "zero-byte" and lines["103"] == "suspect: truncated"
    after = integ.read_summary(out)
    assert after["verified_at"] == summary_before["verified_at"]   # the full check's stamp
    assert after["reverified_at"].endswith("Z")
    assert after["counts"]["zero_byte"] == 1 and after["counts"]["missing_thumb"] == 1
    # the Activity row mirrors it: one job, "Fixing 3 files", n / N, then the counts
    assert {e["job_id"] for e in events} == {st["job_id"]}
    assert events[0]["type"] == "integrity" and events[0]["label"] == "Fixing 3 files"
    assert events[0]["status"] == "running" and events[0]["total"] == 3
    assert events[-1]["status"] == "done_with_errors"
    assert events[-1]["label"] == "Fixed 2 of 3 · 1 couldn't be re-downloaded"


def test_nothing_is_deleted_by_a_run(tmp_path):
    out = _broken_library(tmp_path)
    before = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    session = FakeMediaSession({"102": (_png(4, 4), "image/png"), "103": (_png(2, 3), "image/png")})
    run = _runner(out, session)
    run.start(["102", "103", "106", "107", "108", "109", "112"])
    run.wait(20)
    after = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert before <= after, sorted(before - after)


def test_stop_finishes_the_current_file_and_stops(tmp_path):
    out = _broken_library(tmp_path)
    session = FakeMediaSession({"102": (_png(4, 4), "image/png")})
    run = _runner(out, session)
    gate = {"n": 0}
    real = integ.fix_one

    def slow_fix(*a, **k):
        gate["n"] += 1
        if gate["n"] == 1:
            run.stop()                      # pressed while the first file is going
        return real(*a, **k)

    run._fix = slow_fix
    run.start(["102", "106", "107"])
    run.wait(10)
    st = run.status()
    assert st["stopped"] is True and st["done"] == 1
    assert [r["media_id"] for r in st["results"]] == ["102"]
    assert _bytes(out, "images/p_t1_102.png") == _png(4, 4)   # the current file finished


def test_one_run_at_a_time_and_only_ids_on_the_list(tmp_path):
    out = _broken_library(tmp_path)
    run = _runner(out, FakeMediaSession({}))
    hold = {"go": False}

    def held(*a, **k):
        while not hold["go"]:
            time.sleep(0.01)
        return {"media_id": a[2], "action": "rebuild", "ok": True, "refused": "", "error": "",
                "note": ""}

    run._fix = held
    st = run.start(["106", "101", "999"])
    assert st["total"] == 1                               # a sound row and a stranger are not on it
    assert sorted(st["refused"]) == ["101", "999"]
    assert run.start(["107"]) is None                     # busy
    hold["go"] = True
    run.wait(10)


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

def test_the_fix_routes(tmp_path, monkeypatch):
    out = _broken_library(tmp_path)
    session = FakeMediaSession({"102": (_png(4, 4), "image/png")})
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: session)
    app = create_app(out)
    cli = login_test_client(app)
    r = cli.post("/api/integrity/fix", json={"ids": ["102"]})
    assert r.status_code == 400 and "session expired" in r.get_json()["error"]
    assert cli.get("/api/integrity/broken").get_json()["run"]["running"] is False
    d = cli.post("/api/integrity/fix", json=with_csrf(cli, {"ids": ["102", "106"]})).get_json()
    assert d["started"] is True and d["total"] == 2
    app.extensions["mg_integrity_fix"].wait(10)
    st = cli.get("/api/integrity/fix/status").get_json()
    assert st["fixed"] == 2 and st["running"] is False
    d = cli.post("/api/integrity/fix/stop", json=with_csrf(cli)).get_json()
    assert d["ok"] is True
    assert _bytes(out, "images/p_t1_102.png") == _png(4, 4)
    doc = cli.get("/api/integrity/broken").get_json()
    assert "102" not in {x["media_id"] for x in doc["rows"]}


def test_the_fix_route_answers_busy(tmp_path, monkeypatch):
    out = _broken_library(tmp_path)
    app = create_app(out)
    cli = login_test_client(app)
    run = app.extensions["mg_integrity_fix"]
    hold = {"go": False}

    def held(*a, **k):
        while not hold["go"]:
            time.sleep(0.01)
        return {"media_id": a[2], "action": "rebuild", "ok": True, "refused": "", "error": "",
                "note": ""}

    run._fix = held
    assert cli.post("/api/integrity/fix", json=with_csrf(cli, {"ids": ["106"]})).get_json()["started"]
    r = cli.post("/api/integrity/fix", json=with_csrf(cli, {"ids": ["107"]}))
    assert r.status_code == 409
    hold["go"] = True
    run.wait(10)


def test_an_interrupted_run_is_closed_at_the_next_start(tmp_path):
    core.append_job_event(tmp_path, "integrity-abc", status="running", type="integrity",
                          label="Fixing 3 files", done=1, total=3)
    assert core.resolve_interrupted_local_jobs(tmp_path) == 1
