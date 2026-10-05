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

from moonglade import backup as core
from moonglade import gallery as g
from moonglade import integrity as integ
from moonglade import paths
from moonglade.gallery import create_app
from tests.conftest import login_test_client, with_csrf
from tests.test_integrity import _mp4, _png, _webp
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
    """What resolve_media and download see: a media object per id, and the file at its url.
    A file may name the variant PixAI lists it under (PUBLIC, the full size, by default)."""

    def __init__(self, files):
        self.files = files                    # media id -> (bytes, content type[, variant])
        self.calls = []

    def get(self, url, stream=False, timeout=None):
        self.calls.append(url)
        for mid, spec in self.files.items():
            body, ctype = spec[0], spec[1]
            variant = spec[2] if len(spec) > 2 else "PUBLIC"
            if url == core.MEDIA_BASE.format(id=mid):
                return _Resp(obj={"urls": [{"variant": variant, "url": "https://cdn.test/" + mid}]})
            if url == "https://cdn.test/" + mid:
                return _Resp(body=body, ctype=ctype)
        return _Resp(status=404)


def _no_network():
    raise AssertionError("this path must not reach the network")


# What the list showed for each row of the fixture library -- the action a client sends with
# each id (review finding 3). 109 and 112 are LOST and show none; a test that sends them anyway
# is a client ignoring the missing button, which the runner must refuse by itself.
_SHOWN = {"102": "redownload", "103": "redownload", "105": "redownload", "106": "rebuild",
          "107": "rebuild", "108": "rebuild", "109": "redownload", "112": "redownload",
          "101": "redownload", "999": "redownload"}


def _items(ids):
    return [{"media_id": m, "action": _SHOWN[m]} for m in ids]


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
    d = cli.post("/api/integrity/fix", json=with_csrf(cli, {"items": _items(["109"])})).get_json()
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
    # Review finding 2: Windows strips a trailing dot or space from a path part, so these
    # would land in branding/ (a pruned tree) or a folder other than the one checked.
    "branding./105.png",                    # the reviewer's probe
    "images./p_t1_105.png",
    "images /p_t1_105.png",
    "images/p_t1_105.png.",
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


def test_a_re_download_never_lands_on_another_pictures_file(tmp_path):
    """Review finding 1. An odd catalog row (120) names 109's file -- an empty file PixAI no
    longer has, the only copy anywhere. 120 is not archive-only, so only a check of the file's
    own media id stands between 120's picture and 109's file."""
    out = _broken_library(tmp_path)
    from tests.test_integrity import _row as _r
    g.save_catalog(out / "catalog.db", [_r(media_id="120", filename="images/p_t1_109.png")])
    res = integ.redownload_one(out, out / "catalog.db", "120", session_factory=_no_network)
    assert res["ok"] is False and res["refused"] == "not_this_picture"
    assert _bytes(out, "images/p_t1_109.png") == b""


def test_a_rebuild_never_draws_another_pictures_thumbnail(tmp_path):
    out = _broken_library(tmp_path)
    from tests.test_integrity import _row as _r
    g.save_catalog(out / "catalog.db", [_r(media_id="121", filename="images/p_t1_106.png")])
    res = integ.rebuild_one(out, out / "catalog.db", "121")
    assert res["ok"] is False and res["refused"] == "not_this_picture"
    assert not (out / "gallery" / "thumbs" / "121.jpg").exists()


def test_a_shown_rebuild_never_becomes_a_re_download_and_back(tmp_path):
    """Review finding 3. The client sends the action the list showed; when the file has changed
    since the check so that the live fix differs, nothing runs and the row says so."""
    out = _broken_library(tmp_path)
    res = integ.fix_one(out, out / "catalog.db", "102", session_factory=_no_network,
                        expect="rebuild")                   # 102 is an empty file now
    assert res["ok"] is False and res["refused"] == "changed"
    assert res["error"] == "This file has changed since the check. Run the check again."
    res = integ.fix_one(out, out / "catalog.db", "106", session_factory=_no_network,
                        expect="redownload")                # 106 only lacks a thumbnail
    assert res["ok"] is False and res["refused"] == "changed"
    assert not (out / "gallery" / "thumbs" / "106.jpg").exists()


def test_the_route_wants_the_action_shown_with_every_file(tmp_path):
    out = _broken_library(tmp_path)
    cli = login_test_client(create_app(out))
    for body in ({"ids": ["106"]}, {"items": [{"media_id": "106"}]},
                 {"items": [{"media_id": "106", "action": "delete"}]}, {"items": []}):
        r = cli.post("/api/integrity/fix", json=with_csrf(cli, body))
        assert r.status_code == 400, body
    assert not (out / "gallery" / "thumbs" / "106.jpg").exists()


def test_a_thumbnail_is_never_taken_for_the_picture(tmp_path):
    """Review finding 4. resolve_media falls back to a THUMBNAIL variant when PixAI lists no
    full-size one; that small copy must never replace an original. Refused before the file
    is fetched, and the broken file is left as it is."""
    out = _broken_library(tmp_path)
    for variant in ("THUMBNAIL", "STILL_THUMBNAIL"):
        session = FakeMediaSession({"102": (_png(4, 4), "image/png", variant)})
        res = integ.redownload_one(out, out / "catalog.db", "102", session_factory=lambda: session)
        assert res["ok"] is False and res["refused"] == "small_copy", variant
        assert res["error"] == "PixAI only has a small copy; nothing changed."
        assert session.calls == [core.MEDIA_BASE.format(id="102")]   # the file itself never fetched
        assert _bytes(out, "images/p_t1_102.png") == b""


def test_the_new_picture_must_be_the_size_the_catalog_says(tmp_path):
    out = _broken_library(tmp_path)
    from tests.test_integrity import _row as _r
    g.save_catalog(out / "catalog.db", [_r(media_id="102", filename="p_t1_102.png",
                                           width="8", height="8")])
    session = FakeMediaSession({"102": (_png(4, 4), "image/png")})
    res = integ.redownload_one(out, out / "catalog.db", "102", session_factory=lambda: session)
    assert res["ok"] is False and res["refused"] == "size_differs"
    assert _bytes(out, "images/p_t1_102.png") == b""
    session = FakeMediaSession({"102": (_png(8, 8), "image/png")})
    res = integ.redownload_one(out, out / "catalog.db", "102", session_factory=lambda: session)
    assert res["ok"] is True and _bytes(out, "images/p_t1_102.png") == _png(8, 8)


def test_a_cut_short_file_is_only_replaced_by_one_at_least_as_big(tmp_path):
    out = _broken_library(tmp_path)
    torn = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 20          # no IEND: suspect, ~5 KB
    (out / "images" / "p_t1_103.png").write_bytes(torn)
    session = FakeMediaSession({"103": (_png(2, 2), "image/png")})    # whole, but far smaller
    res = integ.redownload_one(out, out / "catalog.db", "103", session_factory=lambda: session)
    assert res["ok"] is False and res["refused"] == "smaller"
    assert _bytes(out, "images/p_t1_103.png") == torn


class FakeVideoSession:
    """PixAI as the backup's own video path meets it: GET /v1/media/<video> answers an EMPTY url
    list (the real shape for a video), and the GraphQL `media` object carries the mp4 in
    `fileUrl` (moonglade_backup.media_file_gql)."""

    def __init__(self, mid, body):
        self.mid, self.body, self.calls = mid, body, []

    def get(self, url, stream=False, timeout=None):
        self.calls.append(("GET", url))
        if url == core.MEDIA_BASE.format(id=self.mid):
            return _Resp(obj={"urls": [], "type": "VIDEO"})
        if url == "https://cdn.test/video/" + self.mid + ".mp4":
            return _Resp(body=self.body, ctype="video/mp4")
        return _Resp(status=404)

    def post(self, url, json=None, timeout=None):
        self.calls.append(("POST", (json or {}).get("variables")))
        media = {"id": self.mid, "type": "VIDEO", "duration": 5, "hlsUrl": None, "size": None,
                 "fileUrl": "https://cdn.test/video/" + self.mid + ".mp4"}
        return _Resp(obj={"data": {"media": media}})


def test_a_video_is_re_downloaded_the_way_the_backup_downloads_videos(tmp_path):
    """Review finding 5. /v1/media lists no URL for a video, so resolve_media can never find
    one; the backup's sync reads the GraphQL media object's fileUrl, and so does this."""
    out = _broken_library(tmp_path)
    (out / "videos" / "p_t1_114.mp4").write_bytes(b"")
    from tests.test_integrity import _row as _r
    g.save_catalog(out / "catalog.db", [_r(media_id="114", filename="videos/p_t1_114.mp4",
                                           is_video="1")])
    integ.verify_library(out, out / "catalog.db", deep=True)
    row = {r["media_id"]: r for r in integ.broken_list(out, out / "catalog.db")["rows"]}["114"]
    assert (row["state"], row["action"]) == ("recoverable", "redownload")
    session = FakeVideoSession("114", _mp4())
    res = integ.redownload_one(out, out / "catalog.db", "114", session_factory=lambda: session)
    assert res["ok"] is True, res
    assert _bytes(out, "videos/p_t1_114.mp4") == _mp4()
    assert ("POST", {"id": "114"}) in session.calls
    assert ("GET", "https://cdn.test/video/114.mp4") in session.calls


# ---------------------------------------------------------------------------
# The review's nits (6-10)
# ---------------------------------------------------------------------------

def test_each_report_write_has_its_own_temp_file(tmp_path, monkeypatch):
    """Nit 6: two writers of one report never share a temp name."""
    seen = []
    real = core._atomic_replace
    monkeypatch.setattr(core, "_atomic_replace", lambda tmp, dest: (seen.append(tmp.name), real(tmp, dest)))
    integ._write_atomic(tmp_path / "integrity_report.json", b"1")
    integ._write_atomic(tmp_path / "integrity_report.json", b"2")
    assert len(set(seen)) == 2 and all(".tmp-" in n for n in seen)
    assert (tmp_path / "integrity_report.json").read_bytes() == b"2"
    assert not [p.name for p in tmp_path.iterdir() if ".tmp" in p.name]     # none left behind


def test_the_recheck_waits_for_the_report_lock(tmp_path, monkeypatch):
    """Nit 6: the re-check's read-modify-write holds integrity_report.lock, so it cannot
    interleave with another writer of the reports; it waits while the lock is held."""
    import threading
    out = _broken_library(tmp_path)
    lock = out / integ.REPORT_LOCK
    lock.write_text("held")
    before = (paths.reports_path(out, "integrity_report.csv")).read_bytes()
    (out / "images" / "p_t1_102.png").write_bytes(_png(4, 4))            # fixed meanwhile
    t = threading.Thread(target=integ.reverify, args=(out, out / "catalog.db", ["102"]))
    t.start()
    t.join(0.6)
    assert t.is_alive() and (paths.reports_path(out, "integrity_report.csv")).read_bytes() == before
    lock.unlink()
    t.join(10)
    assert not t.is_alive()
    assert "102" not in {ln[0] for ln in integ.read_lines(out)}
    assert not lock.exists()


def test_a_stale_report_lock_is_broken(tmp_path):
    import os
    import time as _t
    out = _broken_library(tmp_path)
    lock = out / integ.REPORT_LOCK
    lock.write_text("left by a process that died")
    old = _t.time() - integ.REPORT_LOCK_STALE_S - 5
    os.utime(lock, (old, old))
    (out / "images" / "p_t1_102.png").write_bytes(_png(4, 4))
    integ.reverify(out, out / "catalog.db", ["102"])
    assert "102" not in {ln[0] for ln in integ.read_lines(out)} and not lock.exists()


def test_a_file_fixed_meanwhile_is_not_replaced(tmp_path):
    """Nit 7: just before the replace, the target is looked at again; a sync that mended it
    while the re-download ran wins, and the run says so."""
    out = _broken_library(tmp_path)
    mended = _png(5, 5)

    class Mending(FakeMediaSession):
        def get(self, url, stream=False, timeout=None):
            if url == "https://cdn.test/102":
                (out / "images" / "p_t1_102.png").write_bytes(mended)
            return super().get(url, stream=stream, timeout=timeout)

    session = Mending({"102": (_png(4, 4), "image/png")})
    res = integ.redownload_one(out, out / "catalog.db", "102", session_factory=lambda: session)
    assert res["ok"] is True and res["note"] == "already sound"
    assert _bytes(out, "images/p_t1_102.png") == mended
    assert not list((out / "gallery" / integ.STAGING_DIRNAME).glob("*"))


def test_a_download_cut_off_leaves_no_part_file(tmp_path):
    """Nit 8: the staging folder keeps nothing of a failed download, .part included."""
    out = _broken_library(tmp_path)

    class Cut(_Resp):
        def iter_content(self, chunk_size=65536):
            yield self._body[:7]
            raise requests.ConnectionError("cut")

    class Cutting(FakeMediaSession):
        def get(self, url, stream=False, timeout=None):
            if url == "https://cdn.test/102":
                self.calls.append(url)
                return Cut(body=_png(4, 4), ctype="image/png")
            return super().get(url, stream=stream, timeout=timeout)

    res = integ.redownload_one(out, out / "catalog.db", "102",
                               session_factory=lambda: Cutting({"102": (_png(4, 4), "image/png")}))
    assert res["ok"] is False
    assert not list((out / "gallery" / integ.STAGING_DIRNAME).glob("*"))


def test_odd_report_and_marks_files_never_break_the_list(tmp_path):
    """Nit 9: a size cell like '²' (isdigit() but not int()) and a marks file nested deep
    enough to raise RecursionError still give a list, and the route answers."""
    out = _broken_library(tmp_path)
    csv_path = paths.reports_path(out, "integrity_report.csv")
    csv_path.write_text(csv_path.read_text(encoding="utf-8").replace(
        "images/p_t1_102.png,0,", "images/p_t1_102.png,\u00b2,"), encoding="utf-8")
    (out / integ.MARKS_FILE).write_text("[" * 200000, encoding="utf-8")
    doc = integ.broken_list(out, out / "catalog.db")
    assert {r["media_id"]: r for r in doc["rows"]}["102"]["size"] == ""
    assert integ.read_marks(out) == {}
    cli = login_test_client(create_app(out))
    assert cli.get("/api/integrity/broken").status_code == 200


def test_one_download_session_per_run_and_no_identity_query(tmp_path, monkeypatch):
    """Nit 10: a run opens ONE session for all its re-downloads, and opening it does not ask
    PixAI who you are (that `me` query retries three times and has no place inside a run)."""
    out = _broken_library(tmp_path)
    made = []

    def factory():
        made.append(1)
        return FakeMediaSession({"102": (_png(4, 4), "image/png"),
                                 "103": (_png(3, 3), "image/png")})

    run = integ.FixRunner(out, out / "catalog.db", session_factory=factory)
    run.start(_items(["102", "103", "106"]))
    run.wait(10)
    assert run.status()["fixed"] == 3 and len(made) == 1
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: seen.update(k) or "session")
    assert integ._download_session() == "session" and seen == {"resolve_user": False}


def test_make_session_can_skip_the_identity_query(tmp_path, monkeypatch):
    import json as _json
    cfg = core._config_path()
    cfg.write_text(_json.dumps({"PIXAI_API_KEY": "sk-test-not-real"}), encoding="utf-8")
    monkeypatch.setattr(core, "USER_ID", "")

    def _no_me(*a, **k):
        raise AssertionError("the identity query must not run")

    monkeypatch.setattr(core, "resolve_user_id", _no_me)
    client = core._make_session(None, resolve_user=False)
    assert client is not None


def test_a_missing_file_is_placed_without_overwriting(tmp_path):
    """Nit 10: a missing file goes into place with a move that refuses an existing file."""
    src, dest = tmp_path / "staged.png", tmp_path / "there.png"
    src.write_bytes(b"new")
    dest.write_bytes(b"someone else's")
    with pytest.raises(FileExistsError):
        integ._move_no_clobber(src, dest)
    assert dest.read_bytes() == b"someone else's" and src.exists()
    dest.unlink()
    integ._move_no_clobber(src, dest)
    assert dest.read_bytes() == b"new" and not src.exists()


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
    st = run.start(_items(["102", "106", "109"]))
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
    run.start(_items(["102", "103", "106", "107", "108", "109", "112"]))
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
    run.start(_items(["102", "106", "107"]))
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
    st = run.start(_items(["106", "101", "999"]))
    assert st["total"] == 1                               # a sound row and a stranger are not on it
    assert sorted(st["refused"]) == ["101", "999"]
    assert run.start(_items(["107"])) is None                     # busy
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
    r = cli.post("/api/integrity/fix", json={"items": _items(["102"])})
    assert r.status_code == 400 and "session expired" in r.get_json()["error"]
    assert cli.get("/api/integrity/broken").get_json()["run"]["running"] is False
    d = cli.post("/api/integrity/fix", json=with_csrf(cli, {"items": _items(["102", "106"])})).get_json()
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
    assert cli.post("/api/integrity/fix", json=with_csrf(cli, {"items": _items(["106"])})).get_json()["started"]
    r = cli.post("/api/integrity/fix", json=with_csrf(cli, {"items": _items(["107"])}))
    assert r.status_code == 409
    hold["go"] = True
    run.wait(10)


def test_an_interrupted_run_is_closed_at_the_next_start(tmp_path):
    core.append_job_event(tmp_path, "integrity-abc", status="running", type="integrity",
                          label="Fixing 3 files", done=1, total=3)
    assert core.resolve_interrupted_local_jobs(tmp_path) == 1


def test_the_report_lock_retries_when_windows_answers_permission_denied(tmp_path, monkeypatch):
    """While another writer's lock file is being deleted, Windows answers EACCES (PermissionError)
    to an exclusive create, not EEXIST. That is "busy": the lock waits and tries again rather than
    crashing the re-check thread (seen in the full run, 2026-10-04)."""
    real_open = integ.os.open
    calls = {"n": 0}

    def flaky_open(path, flags, *a):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, flags, *a)

    monkeypatch.setattr(integ.os, "open", flaky_open)
    with integ._ReportLock(tmp_path) as lk:
        assert lk.held and paths.reports_path(tmp_path, integ.REPORT_LOCK).exists()
    assert calls["n"] == 2 and not paths.reports_path(tmp_path, integ.REPORT_LOCK).exists()
