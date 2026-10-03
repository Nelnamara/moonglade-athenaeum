"""Session P, Stage B1: the Loom's new LOCAL routes -- the music bed (P3), the editor handoff
export (P4) and the read-only prompt lookup "as shots, in order" titles from (P5).

What these pin (BUILD-w5-p §4 and §5.1/§5.5; rulings 6-8, 15; review F17, F18, F19, N2):

  * LOCAL ONLY, NEVER A RENDER. Every route answers normally with core.submit,
    core.submit_generation, core.build_request, core.gql_mutate and the PixAI session maker
    booby-trapped to raise -- and an AST walk of the route functions finds none of those names.
  * LOGIN tier, and 403 without the session's CSRF token on every POST.
  * THE BED: sniffed by its bytes (never its name), capped at 50 MB BEFORE the body is read
    and again while it streams, stored content-addressed in the caller's own folder
    (atomically; an identical bed is not rewritten), served only from there (no traversal,
    no other account's bed), never deleted automatically -- an explicit sweep deletes only
    what is still unused when it looks again. The full bundle carries it and an import
    RE-HASHES it (F19).
  * THE EDL ZIP: every name validated, a half-written clip never read (MISSING.txt instead),
    the bed only from the caller's folder, the name sanitised, the zip deleted on close and a
    stale one swept at start (F18).
  * ⇧ Render (the local ffmpeg cut) mixes the bed by the page's rules: the pure filter-graph
    text is pinned (ffmpeg is not installed here, so the real mix cannot run -- the command's
    shape is what is asserted).
"""
import ast
import hashlib
import io
import json
import os
import re
import time
import wave
import zipfile
from pathlib import Path

import pytest

import moonglade_backup as core
import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, _account_key, create_app, save_catalog
from tests.conftest import _TEST_USERNAME, login_test_client

REPO = Path(__file__).resolve().parent.parent
OTHER_USER, OTHER_PW = "someone-else", "another-real-password-2"


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _wav(seconds=0.2, rate=8000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x01" * int(seconds * rate))
    return buf.getvalue()


MP3_ID3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 200
MP3_FRAME = b"\xff\xfb\x90\x64" + b"\x00" * 200
AAC_ADTS = b"\xff\xf1\x50\x80\x02\x1f\xfc" + b"\x00" * 200
FLAC = b"fLaC\x00\x00\x00\x22" + b"\x00" * 200
OGG = b"OggS\x00\x02" + b"\x00" * 200
M4A = b"\x00\x00\x00\x20ftypM4A \x00\x00\x00\x00M4A mp42isom\x00\x00\x00\x00" + b"\x00" * 200
MP4_VIDEO = b"\x00\x00\x00\x20ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200


@pytest.fixture
def traps(monkeypatch):
    """Every road to PixAI and to a render raises; the list records any attempt."""
    hit = []

    def _trap(name):
        def f(*a, **k):
            hit.append(name)
            raise AssertionError("a Loom local route reached " + name)
        return f
    for name in ("submit", "submit_generation", "build_request", "gql_mutate", "gql_adhoc",
                 "_make_session", "upload_media"):
        monkeypatch.setattr(core, name, _trap(name))
    return hit


@pytest.fixture
def rig(tmp_path, traps):
    app = create_app(tmp_path)
    cli = login_test_client(app)
    cli.csrf = cli.get("/api/account/prefs").get_json()["csrf"]
    return {"app": app, "cli": cli, "tmp": tmp_path, "traps": traps}


def _other(app):
    cli = login_test_client(app, username=OTHER_USER, password=OTHER_PW)
    cli.csrf = cli.get("/api/account/prefs").get_json()["csrf"]
    return cli


def _upload(cli, data, filename="bed.mp3", csrf=None, board="b1"):
    return cli.post("/api/loom/bed", content_type="multipart/form-data",
                    data={"csrf": cli.csrf if csrf is None else csrf, "board": board,
                          "file": (io.BytesIO(data), filename)})


def _beds_dir(tmp, user=_TEST_USERNAME):
    return tmp / "loom" / "_beds" / _account_key(user)


def _save_board(cli, board_id, project):
    r = cli.post("/api/loom/set", json={"key": "storyboard:v2:proj:" + board_id,
                                        "value": json.dumps(project)})
    assert r.get_json()["ok"]


def _age(path, seconds=3600):
    t = time.time() - seconds
    os.utime(path, (t, t))


# ---- the bed: upload, sniff, cap, store --------------------------------------------------

@pytest.mark.parametrize("data,ext", [(MP3_ID3, "mp3"), (MP3_FRAME, "mp3"), (AAC_ADTS, "aac"), (FLAC, "flac"),
                                      (OGG, "ogg"), (M4A, "m4a")])
def test_the_bytes_decide_the_type_never_the_name(rig, data, ext):
    r = _upload(rig["cli"], data, filename="whatever.bin")
    assert r.status_code == 200, r.get_json()
    d = r.get_json()
    assert d["file"] == hashlib.sha1(data).hexdigest() + "." + ext
    assert d["name"] == "whatever.bin" and d["bytes"] == len(data)
    assert (_beds_dir(rig["tmp"]) / d["file"]).read_bytes() == data
    assert rig["traps"] == []


def test_a_real_wav_is_stored_content_addressed_in_the_callers_own_folder(rig):
    data = _wav()
    d = _upload(rig["cli"], data, filename="Elune theme.wav").get_json()
    assert g.LOOM_BED_FILE_RE.match(d["file"]) and d["file"].endswith(".wav")
    p = _beds_dir(rig["tmp"]) / d["file"]
    assert p.read_bytes() == data
    assert d["dur"] is None or d["dur"] > 0, "ffprobe's length when it is installed, else null"
    assert not [f for f in p.parent.iterdir() if f.name.endswith(".part")], "no temp file left behind"


@pytest.mark.parametrize("data,name", [(PNG, "cover.mp3"), (MP4_VIDEO, "clip.m4a"), (b"hello world " * 20, "notes.wav"),
                                       (b"", "empty.mp3")])
def test_anything_that_is_not_audio_is_refused_whatever_it_is_called(rig, data, name):
    r = _upload(rig["cli"], data, filename=name)
    assert r.status_code in (400, 415)
    assert not _beds_dir(rig["tmp"]).exists() or not [f for f in _beds_dir(rig["tmp"]).iterdir()]


def test_an_identical_bed_is_not_rewritten(rig):
    d1 = _upload(rig["cli"], FLAC).get_json()
    p = _beds_dir(rig["tmp"]) / d1["file"]
    _age(p)
    before = p.stat().st_mtime
    d2 = _upload(rig["cli"], FLAC, filename="again.flac").get_json()
    assert d2["file"] == d1["file"]
    assert p.stat().st_mtime == before, "the stored file was not touched"
    assert len(list(p.parent.iterdir())) == 1


def test_a_different_bed_can_never_overwrite_another(rig):
    a = _upload(rig["cli"], FLAC).get_json()["file"]
    b = _upload(rig["cli"], OGG).get_json()["file"]
    assert a != b
    assert (_beds_dir(rig["tmp"]) / a).read_bytes() == FLAC


class _Untouchable(io.RawIOBase):
    """A request body of `size` bytes that must never be read. The test client measures a
    stream by seeking to its end, so seek/tell report the size; reading raises."""
    reads = 0

    def __init__(self, size=0):
        super().__init__()
        self._size, self._pos = size, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, pos, whence=0):
        self._pos = self._size if whence == 2 else pos
        return self._pos

    def readinto(self, b):
        _Untouchable.reads += 1
        raise AssertionError("the body of an over-cap upload was read")


def test_the_cap_is_enforced_before_the_body_is_read(rig):
    _Untouchable.reads = 0
    r = rig["cli"].post("/api/loom/bed", input_stream=_Untouchable(g.LOOM_BED_MAX_BYTES + g.LOOM_BED_FORM_SLACK + 1),
                        content_type="multipart/form-data; boundary=zzz")
    assert r.status_code == 413
    assert _Untouchable.reads == 0
    assert "50 MB" in r.get_json()["error"]


def test_the_cap_also_holds_while_the_file_streams(rig, monkeypatch):
    """A body under the declared-length check whose file part is still over the cap."""
    monkeypatch.setattr(g, "LOOM_BED_MAX_BYTES", 1000)
    r = _upload(rig["cli"], FLAC + b"\x00" * 2000)
    assert r.status_code == 413
    assert not [f for f in _beds_dir(rig["tmp"]).iterdir()], "nothing kept, not even a temp file"


def test_an_upload_without_a_length_is_refused(rig):
    r = rig["cli"].post("/api/loom/bed", input_stream=_Untouchable(),
                        content_type="multipart/form-data; boundary=zzz",
                        headers={"Transfer-Encoding": "chunked"})
    assert r.status_code in (411, 413)


def test_a_bad_board_id_is_refused(rig):
    assert _upload(rig["cli"], FLAC, board="../x").status_code == 400


# ---- the bed: served only from the caller's own folder -------------------------------------

def test_get_streams_the_bed_with_range_support(rig):
    data = _wav(seconds=0.5)
    name = _upload(rig["cli"], data).get_json()["file"]
    r = rig["cli"].get("/api/loom/bed?file=" + name)
    assert r.status_code == 200 and r.data == data
    assert r.headers["Content-Type"].startswith("audio/wav")
    part = rig["cli"].get("/api/loom/bed?file=" + name, headers={"Range": "bytes=0-9"})
    assert part.status_code == 206 and part.data == data[:10]


@pytest.mark.parametrize("bad", ["../../catalog.db", "..\\config.json", "/etc/passwd", "C:\\x\\y.mp3",
                                 "%2e%2e/catalog.db", "0" * 40 + ".exe", "0" * 39 + ".mp3",
                                 "A" * 40 + ".mp3", "0" * 40 + ".mp3/../../x", ""])
def test_traversal_and_junk_names_are_refused(rig, bad):
    (rig["tmp"] / "catalog.db").write_bytes(b"secret")
    r = rig["cli"].get("/api/loom/bed", query_string={"file": bad})
    assert r.status_code == 404


def test_another_accounts_bed_is_not_yours(rig):
    name = _upload(rig["cli"], FLAC).get_json()["file"]
    other = _other(rig["app"])
    assert other.get("/api/loom/bed?file=" + name).status_code == 404
    assert other.post("/api/loom/beds/sweep", json={"csrf": other.csrf, "files": [name]}).get_json()["removed"] == []
    assert (_beds_dir(rig["tmp"]) / name).exists()


def test_a_symlink_out_of_the_folder_is_not_followed(rig):
    d = _beds_dir(rig["tmp"])
    d.mkdir(parents=True)
    (rig["tmp"] / "config.json.bak").write_bytes(b"secret")
    link = d / ("f" * 40 + ".mp3")
    try:
        link.symlink_to(rig["tmp"] / "config.json.bak")
    except (OSError, NotImplementedError):
        pytest.skip("this filesystem cannot make a symlink")
    assert rig["cli"].get("/api/loom/bed?file=" + link.name).status_code == 404


# ---- unused beds and the explicit sweep (ruling 15, F18) -----------------------------------

def test_unused_lists_only_beds_no_board_references_and_the_sweep_rechecks(rig):
    cli = rig["cli"]
    used = _upload(cli, FLAC).get_json()["file"]
    spare = _upload(cli, OGG).get_json()["file"]
    fresh = _upload(cli, MP3_ID3).get_json()["file"]
    for n in (used, spare):
        _age(_beds_dir(rig["tmp"]) / n)
    _save_board(cli, "b1", {"name": "b", "acts": [], "bed": {"file": used, "name": "x", "db": -8}})
    d = cli.get("/api/loom/beds/unused").get_json()
    assert [f["file"] for f in d["files"]] == [spare], "a referenced bed and a just-added one are never offered"
    assert d["count"] == 1 and d["bytes"] == len(OGG)
    # Asking to sweep a bed a board uses, or the one just added, removes nothing of those.
    r = cli.post("/api/loom/beds/sweep", json={"csrf": cli.csrf, "files": [used, spare, fresh]}).get_json()
    assert r["removed"] == [spare] and sorted(r["kept"]) == sorted([used, fresh])
    assert (_beds_dir(rig["tmp"]) / used).exists() and (_beds_dir(rig["tmp"]) / fresh).exists()
    assert not (_beds_dir(rig["tmp"]) / spare).exists()


def test_a_board_saved_between_the_list_and_the_sweep_keeps_its_bed(rig):
    cli = rig["cli"]
    n = _upload(cli, FLAC).get_json()["file"]
    _age(_beds_dir(rig["tmp"]) / n)
    assert [f["file"] for f in cli.get("/api/loom/beds/unused").get_json()["files"]] == [n]
    _save_board(cli, "b2", {"name": "b", "acts": [], "bed": {"file": n}})
    r = cli.post("/api/loom/beds/sweep", json={"csrf": cli.csrf, "files": [n]}).get_json()
    assert r["removed"] == [] and (_beds_dir(rig["tmp"]) / n).exists()


def test_removing_a_bed_from_a_board_deletes_nothing(rig):
    """Removing is a board edit; the file stays until the owner sweeps it."""
    cli = rig["cli"]
    n = _upload(cli, FLAC).get_json()["file"]
    _save_board(cli, "b3", {"name": "b", "acts": [], "bed": {"file": n}})
    _save_board(cli, "b3", {"name": "b", "acts": []})
    assert (_beds_dir(rig["tmp"]) / n).exists()


def test_the_sweep_refuses_bad_names(rig):
    cli = rig["cli"]
    for files in (["../../catalog.db"], "notalist", [0] * 501):
        assert cli.post("/api/loom/beds/sweep", json={"csrf": cli.csrf, "files": files}).status_code == 400


# ---- CSRF, tiers, and never a render ------------------------------------------------------

def test_every_new_post_refuses_without_the_csrf_token(rig):
    cli = rig["cli"]
    assert _upload(cli, FLAC, csrf="nope").status_code == 403
    assert not _beds_dir(rig["tmp"]).exists() or not [f for f in _beds_dir(rig["tmp"]).iterdir() if not f.name.startswith(".")]
    assert cli.post("/api/loom/beds/sweep", json={"csrf": "nope", "files": []}).status_code == 403
    assert cli.post("/api/loom/export-edl", json={"csrf": "nope", "name": "x", "edl": "TITLE: X", "csv": "",
                                                   "clips": []}).status_code == 403
    assert cli.post("/api/loom/beds/sweep", json={"files": []}).status_code == 403


def test_every_new_route_is_login_tier(tmp_path):
    anon = create_app(tmp_path).test_client()
    for method, path in (("POST", "/api/loom/bed"), ("GET", "/api/loom/bed?file=x"),
                         ("GET", "/api/loom/beds/unused"), ("POST", "/api/loom/beds/sweep"),
                         ("POST", "/api/loom/export-edl"), ("GET", "/api/loom/prompts?ids=1"),
                         ("GET", "/api/loom/frame?mid=1&at=0")):
        r = anon.open(path, method=method, json={} if method == "POST" else None)
        assert r.status_code == 401, (method, path, r.status_code)


_NEW_FUNCS = ("api_loom_bed_upload", "api_loom_bed_get", "api_loom_beds_unused", "api_loom_beds_sweep",
              "api_loom_export_edl", "api_loom_prompts", "_loom_bed_path", "_loom_store_bed",
              "_loom_account_projects", "_loom_unused_beds", "_loom_complete_clip", "_loom_beds_dir",
              # Stage B2 (P9): the continuity ribbon's frame route and its cache sweep
              "loom_frame", "_loom_frame_sweep")
_SPEND = {"submit", "submit_generation", "build_request", "gql_mutate", "gql_adhoc", "_gen_session",
          "_make_session", "upload_media", "submit_fixer"}


def test_no_new_route_function_names_a_render_or_pixai():
    tree = ast.parse((REPO / "moonglade_gallery.py").read_text(encoding="utf-8"))
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in _NEW_FUNCS:
            called = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    f = sub.func
                    called.add(f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", ""))
            found[node.name] = called
    assert set(found) == set(_NEW_FUNCS), "a function was renamed: " + repr(set(_NEW_FUNCS) - set(found))
    for name, called in found.items():
        assert not (called & _SPEND), name + " calls " + repr(called & _SPEND)


# ---- the EDL export (P4) ----------------------------------------------------------------------

@pytest.fixture
def clips(rig):
    """Three catalogued videos: two complete, one zero-byte (a download that did not finish),
    and a .part file in the library that must never be read."""
    tmp = rig["tmp"]
    (tmp / "videos").mkdir()
    (tmp / "videos" / "shot_7001.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42clip-one")
    (tmp / "videos" / "shot_7002.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42clip-two")
    (tmp / "videos" / "shot_7003.mp4").write_bytes(b"")
    (tmp / "videos" / "shot_7004.mp4.part").write_bytes(b"half")
    save_catalog(tmp / "catalog.db", [
        _row(media_id="7001", filename="videos/shot_7001.mp4", is_video="1"),
        _row(media_id="7002", filename="videos/shot_7002.mp4", is_video="1"),
        _row(media_id="7003", filename="videos/shot_7003.mp4", is_video="1"),
        _row(media_id="7004", filename="videos/shot_7004.mp4.part", is_video="1"),
    ])
    return rig


def _edl_body(cli, **kw):
    b = {"csrf": cli.csrf, "name": "moonwell-ep1", "edl": "TITLE: MOONWELL\r\nFCM: NON-DROP FRAME\r\n",
         "csv": "order,code,title,take,file,in,out,duration,mode,prompt\r\n",
         "clips": [{"mid": "7001", "file": "A01_t2.mp4"}, {"mid": "7001", "file": "A02_t2.mp4"},
                   {"mid": "7002", "file": "A03_t1.mp4"}]}
    b.update(kw)
    return b


def test_the_zip_holds_the_edl_the_csv_and_each_clip_under_its_name(clips):
    cli = clips["cli"]
    r = cli.post("/api/loom/export-edl", json=_edl_body(cli))
    assert r.status_code == 200 and r.mimetype == "application/zip"
    assert r.headers["Content-Disposition"] == 'attachment; filename="moonwell-ep1.zip"'
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert sorted(z.namelist()) == ["A01_t2.mp4", "A02_t2.mp4", "A03_t1.mp4", "moonwell-ep1.csv", "moonwell-ep1.edl"]
    assert z.read("A02_t2.mp4") == z.read("A01_t2.mp4"), "a split's halves are two files of one clip"
    assert all(i.compress_type == zipfile.ZIP_STORED for i in z.infolist())
    assert r.headers["X-Edl-Missing-Count"] == "0"
    assert clips["traps"] == []


def test_a_half_written_or_unknown_clip_is_listed_never_read(clips):
    cli = clips["cli"]
    r = cli.post("/api/loom/export-edl", json=_edl_body(cli, clips=[
        {"mid": "7001", "file": "A01_t1.mp4"}, {"mid": "7003", "file": "A02_t1.mp4"},
        {"mid": "7004", "file": "A03_t1.mp4"}, {"mid": "9999", "file": "A04_t1.mp4"}]))
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert "A01_t1.mp4" in z.namelist()
    for missing in ("A02_t1.mp4", "A03_t1.mp4", "A04_t1.mp4"):
        assert missing not in z.namelist()
        assert missing in z.read("MISSING.txt").decode()
    assert r.headers["X-Edl-Missing-Count"] == "3"


def test_the_bed_rides_along_from_the_callers_folder_only(clips):
    cli = clips["cli"]
    bed = _upload(cli, FLAC).get_json()["file"]
    r = cli.post("/api/loom/export-edl", json=_edl_body(cli, bed_file=bed, bed_name="elune-theme.flac"))
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert z.read("elune-theme.flac") == FLAC
    # a bed name that is not the planner's shape falls back; never a path
    r2 = cli.post("/api/loom/export-edl", json=_edl_body(cli, bed_file=bed, bed_name="../../evil.flac"))
    assert "music_bed.flac" in zipfile.ZipFile(io.BytesIO(r2.data)).namelist()


@pytest.mark.parametrize("bad", ["../../catalog.db", "..\\config.json", "../../../secret.json", "/etc/passwd",
                                 "0" * 40 + ".mp3"])
def test_bed_file_traversal_is_refused_f19(clips, bad):
    cli = clips["cli"]
    (clips["tmp"] / "secret.json").write_text('{"PIXAI_API_KEY": "sk-secret"}')
    r = cli.post("/api/loom/export-edl", json=_edl_body(cli, bed_file=bad))
    assert r.status_code == 400
    assert b"sk-secret" not in r.data


def test_another_accounts_bed_cannot_ride_in_your_zip(clips):
    other = _other(clips["app"])
    theirs = _upload(other, OGG).get_json()["file"]
    cli = clips["cli"]
    assert cli.post("/api/loom/export-edl", json=_edl_body(cli, bed_file=theirs)).status_code == 400


@pytest.mark.parametrize("clip", [{"mid": "7001", "file": "../A01_t1.mp4"}, {"mid": "7001", "file": "A01_t1.mp4/x"},
                                  {"mid": "7001", "file": "A01_t1.exe"}, {"mid": "7001", "file": "A012345678_t1.mp4"},
                                  {"mid": "../7001", "file": "A01_t1.mp4"}, {"mid": "local_XYZ", "file": "A01_t1.mp4"},
                                  "not-a-dict"])
def test_every_clip_name_and_id_is_validated(clips, clip):
    cli = clips["cli"]
    assert cli.post("/api/loom/export-edl", json=_edl_body(cli, clips=[clip])).status_code == 400


def test_two_clips_may_not_share_a_name(clips):
    cli = clips["cli"]
    body = _edl_body(cli, clips=[{"mid": "7001", "file": "A01_t1.mp4"}, {"mid": "7002", "file": "a01_t1.mp4"}])
    assert cli.post("/api/loom/export-edl", json=body).status_code == 400


@pytest.mark.parametrize("name,stem", [("Moonwell · ep 1", "Moonwell  ep 1"), ('x"\r\nSet-Cookie: a=b', "xSet-Cookie ab"),
                                       ("../../etc/passwd", "etcpasswd"), ("☾☾", "storyboard"), ("", "storyboard"),
                                       ("a" * 200, "a" * 64)])
def test_the_name_is_sanitised(clips, name, stem):
    cli = clips["cli"]
    r = cli.post("/api/loom/export-edl", json=_edl_body(cli, name=name))
    assert r.status_code == 200
    assert g.loom_edl_zip_stem(name) == stem
    assert stem + ".edl" in zipfile.ZipFile(io.BytesIO(r.data)).namelist()
    assert "\n" not in r.headers["Content-Disposition"]


def test_edl_and_csv_are_capped(clips, monkeypatch):
    cli = clips["cli"]
    monkeypatch.setattr(g, "LOOM_EDL_MAX_EDL_CHARS", 10)
    assert cli.post("/api/loom/export-edl", json=_edl_body(cli, edl="x" * 11)).status_code == 413
    monkeypatch.setattr(g, "LOOM_EDL_MAX_CSV_CHARS", 10)
    assert cli.post("/api/loom/export-edl", json=_edl_body(cli, edl="ok", csv="y" * 11)).status_code == 413
    assert cli.post("/api/loom/export-edl", json=_edl_body(cli, edl="")).status_code == 400


def test_the_zip_is_deleted_once_the_download_closes(clips):
    cli = clips["cli"]
    r = cli.post("/api/loom/export-edl", json=_edl_body(cli), buffered=True)
    assert r.status_code == 200
    r.close()
    d = clips["tmp"] / "loom" / "_exports"
    assert d.is_dir() and not list(d.glob("*.zip"))


def test_a_stale_export_is_swept_at_start_and_a_fresh_one_kept(tmp_path):
    d = tmp_path / "loom" / "_exports"
    d.mkdir(parents=True)
    old, new = d / "old.zip", d / "new.zip"
    old.write_bytes(b"x")
    new.write_bytes(b"y")
    _age(old, g.LOOM_EXPORT_SWEEP_AGE_S + 60)
    create_app(tmp_path)
    assert not old.exists() and new.exists()


def test_the_name_patterns_are_the_planners_own():
    js = (REPO / "loom" / "src" / "loom-edl-core.js").read_text(encoding="utf-8")
    clip = re.search(r"export const EDL_CLIP_FILE_RE = /(.+)/;", js).group(1)
    bed = re.search(r"export const EDL_BED_NAME_RE = /(.+)/;", js).group(1)
    assert clip == g.LOOM_EDL_CLIP_RE.pattern
    assert bed == g.LOOM_EDL_BED_NAME_RE.pattern
    bedjs = (REPO / "loom" / "src" / "loom-bed-core.js").read_text(encoding="utf-8")
    assert re.search(r"export const BED_FILE_RE = /(.+)/;", bedjs).group(1) == g.LOOM_BED_FILE_RE.pattern
    assert "export const BED_MAX_BYTES = 50 * 1024 * 1024;" in bedjs and g.LOOM_BED_MAX_BYTES == 50 * 1024 * 1024


# ---- the full bundle carries the bed; an import re-hashes it (F19) -------------------------

def test_the_bundle_carries_the_bed_and_an_import_rehashes_it(rig):
    cli = rig["cli"]
    bed = _upload(cli, FLAC).get_json()["file"]
    project = {"name": "P", "acts": [], "assets": [], "bed": {"file": bed, "name": "x.flac", "db": -8}}
    r = cli.post("/api/loom/export-bundle", json={"project": project, "thumbs": {}})
    z = zipfile.ZipFile(io.BytesIO(r.data))
    assert z.read("beds/" + bed) == FLAC
    # imported on another account: stored under the hash of the bytes, board re-pointed
    other = _other(rig["app"])
    d = other.post("/api/loom/import-bundle", data={"file": (io.BytesIO(r.data), "b.zip")},
                   content_type="multipart/form-data").get_json()
    assert d["project"]["bed"]["file"] == bed
    assert (_beds_dir(rig["tmp"], OTHER_USER) / bed).read_bytes() == FLAC


def test_a_crafted_bundle_cannot_place_or_forge_a_bed(rig):
    cli = rig["cli"]
    forged = "0" * 40 + ".mp3"
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w") as z:
        z.writestr("project.json", json.dumps({"project": {"name": "P", "acts": [], "assets": [],
                                                           "bed": {"file": forged, "name": "x"}}, "thumbs": {}}))
        z.writestr("beds/" + forged, OGG)                  # the name claims a hash its bytes don't have
        z.writestr("beds/../../evil.py", MP3_ID3)          # a traversing name
        z.writestr("beds/notes.mp3", b"plain text, not audio" * 5)
    d = cli.post("/api/loom/import-bundle", data={"file": (io.BytesIO(mem.getvalue()), "b.zip")},
                 content_type="multipart/form-data").get_json()
    want = hashlib.sha1(OGG).hexdigest() + ".ogg"
    assert d["project"]["bed"]["file"] == want, "re-pointed at the name its own bytes give it"
    stored = sorted(f.name for f in _beds_dir(rig["tmp"]).iterdir())
    # Spend review S5: the traversing entry is real audio, but the board does not name it, so
    # it is never read or stored (it used to be stored under its own hash).
    assert stored == [want]
    assert not (rig["tmp"].parent / "evil.py").exists() and not (rig["tmp"] / "evil.py").exists()
    assert not (_beds_dir(rig["tmp"]) / forged).exists()


def test_a_bundle_stores_only_the_bed_its_board_names(rig):
    """Spend review S5. Every beds/ entry used to be re-hashed and stored, each up to 50 MB with
    no count or total cap, so a small bundle of compressible 'audio' (an ID3 header then zeros)
    could fill the disk with beds nothing referenced. Only the board's own bed is stored now."""
    mem = io.BytesIO()
    named = hashlib.sha1(FLAC).hexdigest() + ".flac"
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps({"project": {"name": "P", "acts": [], "assets": [],
                                                           "bed": {"file": named, "name": "x"}}, "thumbs": {}}))
        z.writestr("beds/" + named, FLAC)
        for n in range(12):
            filler = MP3_ID3 + bytes([n]) + b"\0" * (2 * 1024 * 1024)
            z.writestr("beds/%s.mp3" % hashlib.sha1(filler).hexdigest(), filler)
    assert len(mem.getvalue()) < 256 * 1024, "the hostile bundle is small"
    d = rig["cli"].post("/api/loom/import-bundle", data={"file": (io.BytesIO(mem.getvalue()), "b.zip")},
                        content_type="multipart/form-data").get_json()
    assert d["project"]["bed"]["file"] == named
    stored = sorted(f.name for f in _beds_dir(rig["tmp"]).iterdir())
    assert stored == [named], "one bed, the one the board names; nothing else is written"
    assert g.LOOM_BUNDLE_MAX_BEDS == 1


def test_a_crash_left_bed_temp_file_is_swept_at_start_once_an_hour_old(tmp_path):
    """Spend review N5. A bed upload or a bundle import killed mid-write leaves
    .upload-*.part / .import-*.part in _beds/<account>/, which the unused list and its sweep
    never see. The next start sweeps an old one -- and touches nothing else."""
    d = _beds_dir(tmp_path)
    d.mkdir(parents=True)
    bed = hashlib.sha1(MP3_ID3).hexdigest() + ".mp3"
    names = {".upload-abc123.part": True, ".import-def456.part": True, ".upload-fresh.part": False,
             bed: False, "notes.part": False, ".upload-x.partial": False}
    for n in names:
        (d / n).write_bytes(MP3_ID3)
        if n != ".upload-fresh.part":
            _age(d / n, seconds=2 * g.LOOM_BED_TEMP_SWEEP_AGE_S)
    create_app(tmp_path)
    left = sorted(f.name for f in d.iterdir())
    assert left == sorted(n for n, swept in names.items() if not swept)


def test_a_bundle_whose_board_names_no_bed_stores_none(rig):
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w") as z:
        z.writestr("project.json", json.dumps({"project": {"name": "P", "acts": [], "assets": []}, "thumbs": {}}))
        z.writestr("beds/" + hashlib.sha1(FLAC).hexdigest() + ".flac", FLAC)
    d = rig["cli"].post("/api/loom/import-bundle", data={"file": (io.BytesIO(mem.getvalue()), "b.zip")},
                        content_type="multipart/form-data").get_json()
    assert "bed" not in d["project"]
    assert not _beds_dir(rig["tmp"]).exists() or not list(_beds_dir(rig["tmp"]).iterdir())


def test_an_imported_bed_naming_no_storable_file_is_dropped(rig):
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w") as z:
        z.writestr("project.json", json.dumps({"project": {"name": "P", "acts": [], "assets": [],
                                                           "bed": {"file": "../../x.mp3"}}, "thumbs": {}}))
    d = rig["cli"].post("/api/loom/import-bundle", data={"file": (io.BytesIO(mem.getvalue()), "b.zip")},
                        content_type="multipart/form-data").get_json()
    assert "bed" not in d["project"]


# ---- ⇧ Render mixes the bed (P3): the filter graph, pure; the command's shape -------------

def test_the_bed_graph_follows_the_pages_rules():
    fc = g.loom_bed_audio_graph(3, -8, 14.0, 102, [(5.0, 8.0)])
    assert fc == ("[3:a]atrim=end=14.000,asetpts=PTS-STARTPTS,aformat=sample_rates=48000:channel_layouts=stereo,"
                  "volume=-8dB,volume=-12dB:enable='between(t,5.000,8.000)',afade=t=in:st=0:d=2.000,"
                  "afade=t=out:st=11.000:d=3.000[bed];"
                  "[acut]aformat=sample_rates=48000:channel_layouts=stereo[acutf];"
                  "[acutf][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]")


def test_a_short_bed_ends_where_it_ends_and_never_loops():
    fc = g.loom_bed_audio_graph(2, -3, 14.0, 10.0, [(8.0, 12.0)], cut_label=None)
    assert "atrim=end=10.000" in fc and "afade=t=out:st=7.000:d=3.000" in fc
    assert "between(t,8.000,10.000)" in fc, "the duck is clipped to the bed"
    assert "aloop" not in fc and "loop" not in fc
    assert fc.endswith("[aout]") and "amix" not in fc, "with no shot audio the bed is the track"


def test_level_is_clamped_and_tiny_beds_do_not_overlap_their_fades():
    assert "volume=-24dB" in g.loom_bed_audio_graph(1, -99, 10, None)
    assert "volume=0dB" in g.loom_bed_audio_graph(1, 5, 10, None)
    tiny = g.loom_bed_audio_graph(1, -8, 10, 2.0)
    assert "afade=t=in:st=0:d=1.000" in tiny and "afade=t=out:st=1.000:d=1.000" in tiny


def test_duck_windows_are_runs_of_own_audio_shots():
    assert g.loom_bed_windows([5, 3, 6], [False, True, False]) == [(5.0, 8.0)]
    assert g.loom_bed_windows([5, 3, 6], [True, True, False]) == [(0.0, 8.0)]
    assert g.loom_bed_windows([5, 3, 6], [False, True, True], bed_len=10) == [(5.0, 10.0)]
    assert g.loom_bed_windows([5, 3], [False, False]) == []


def test_render_passes_the_bed_as_an_input_with_the_graph(rig, monkeypatch, clips):
    cli = rig["cli"]
    bed = _upload(cli, FLAC).get_json()["file"]
    monkeypatch.setattr(core, "ffmpeg_path", lambda: "ffmpeg-fake")
    monkeypatch.setattr(core, "ffprobe_path", lambda: "ffprobe-fake")
    monkeypatch.setattr(g, "probe_has_audio", lambda p, timeout=None: p.endswith("7002.mp4"))
    monkeypatch.setattr(g, "probe_duration", lambda p, timeout=None: 60.0 if p.endswith(".flac") else 5.0)
    started = []

    class _Thread:
        def __init__(self, target=None, args=(), daemon=None, **k):
            started.append(args)

        def start(self):
            pass
    monkeypatch.setattr(g.threading, "Thread", _Thread)
    r = cli.post("/api/loom/export", json={
        "clips": [{"mid": "7001", "in": 0, "out": 4, "own_audio": False, "span": 4},
                  {"mid": "7002", "in": 0, "out": None, "own_audio": True, "span": 5}],
        "total_seconds": 9, "bed": {"file": bed, "db": -6, "dur": 60}})
    assert r.get_json().get("ok") is True, r.get_json()
    cmd = started[0][0]
    bi = cmd.index(str(_beds_dir(rig["tmp"]) / bed))
    assert cmd[bi - 1] == "-i", "the bed is an ffmpeg input, read from the caller's own folder"
    assert bi < cmd.index("-filter_complex")
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "[2:a]atrim" in fc, "the bed's input index follows the two clips (no silence input here)"
    assert "concat=n=2:v=1:a=1[vout][acut]" in fc
    assert "volume=-6dB" in fc and "between(t,4.000,9.000)" in fc and "atrim=end=9.000" in fc
    assert fc.endswith("normalize=0[aout]")
    assert cmd[cmd.index("-map", cmd.index("[vout]")) + 1] == "[aout]"
    assert rig["traps"] == []


def test_render_without_the_bed_file_says_so_and_renders_the_cut(rig, monkeypatch, clips):
    cli = rig["cli"]
    monkeypatch.setattr(core, "ffmpeg_path", lambda: "ffmpeg-fake")
    monkeypatch.setattr(g, "probe_has_audio", lambda p, timeout=None: True)
    monkeypatch.setattr(g, "probe_duration", lambda p, timeout=None: 5.0)
    started = []

    class _Thread:
        def __init__(self, target=None, args=(), daemon=None, **k):
            started.append(args)

        def start(self):
            pass
    monkeypatch.setattr(g.threading, "Thread", _Thread)
    r = cli.post("/api/loom/export", json={"clips": [{"mid": "7001", "in": 0, "out": 4}], "total_seconds": 4,
                                            "bed": {"file": "1" * 40 + ".mp3", "db": -8}})
    assert r.get_json()["ok"] is True
    fc = started[0][0][started[0][0].index("-filter_complex") + 1]
    assert "amix" not in fc and fc.endswith("[vout][aout]")
    assert "music bed" in cli.get("/api/loom/export-status").get_json()["warning"]


# ---- the read-only prompt lookup (P5) ------------------------------------------------------------

def test_prompts_answers_in_order_and_leaves_unknown_ids_out(rig):
    save_catalog(rig["tmp"] / "catalog.db", [
        _row(media_id="11", filename="a.png", prompt_full="first line\nsecond", created_at="2026-01-02"),
        _row(media_id="local_0123456789ab", filename="b.png", prompt_preview="imported", created_at="2026-01-01"),
        _row(media_id="13", filename="c.mp4", is_video="1", created_at="2026-01-03"),
    ])
    d = rig["cli"].get("/api/loom/prompts?ids=13,99,local_0123456789ab,11,../x").get_json()
    assert [p["media_id"] for p in d["pictures"]] == ["13", "local_0123456789ab", "11"]
    assert d["pictures"][2] == {"media_id": "11", "prompt": "first line\nsecond", "created_at": "2026-01-02",
                                "is_video": False}
    assert d["pictures"][0]["is_video"] is True
    assert rig["cli"].get("/api/loom/prompts?ids=" + ",".join(str(i) for i in range(201))).status_code == 400
    assert rig["traps"] == []


# ---- the sniffer, directly -------------------------------------------------------------------------

def test_sniff_audio_ext():
    assert g.sniff_audio_ext(_wav()) == "wav"
    assert g.sniff_audio_ext(MP3_ID3) == "mp3"
    assert g.sniff_audio_ext(MP3_FRAME) == "mp3"
    assert g.sniff_audio_ext(AAC_ADTS) == "aac"
    assert g.sniff_audio_ext(FLAC) == "flac"
    assert g.sniff_audio_ext(OGG) == "ogg"
    assert g.sniff_audio_ext(M4A) == "m4a"
    for bad in (MP4_VIDEO, PNG, b"", b"RIFF\x00\x00\x00\x00AVI ", b"\xff\xd8\xff\xe0jpeg"):
        assert g.sniff_audio_ext(bad) is None, bad[:12]


# ---- the continuity ribbon's frames (P9; review F18) ------------------------------------------------
# GET /api/loom/frame: a small local still, cached as <mid>_<frame>.png, the time quantised to
# 1/24 s, the cache LRU-capped by count and bytes and swept on write -- no upload, never PixAI.
# ffmpeg is not installed here, so core.frame_at (the app's one frame primitive) is faked with a
# recorder that writes a real PNG; the route's own scaling, naming and cache are what is tested.

@pytest.fixture
def frames(clips, monkeypatch):
    calls = []

    def fake_frame_at(path, t, out, *, trim_aware=True):
        from PIL import Image
        calls.append((Path(path).name, t, Path(out).name))
        Image.new("RGB", (640, 360), (40 + len(calls), 60, 120)).save(out, "PNG")
        return out
    monkeypatch.setattr(core, "frame_at", fake_frame_at)
    clips["calls"] = calls
    clips["fdir"] = clips["tmp"] / "loom" / "_frames"
    return clips


def _frame(cli, mid, at):
    return cli.get("/api/loom/frame", query_string={"mid": mid, "at": at})


def test_a_frame_is_a_small_png_named_by_its_quantised_frame(frames):
    from PIL import Image
    cli = frames["cli"]
    r = _frame(cli, "7001", "1.0")
    assert r.status_code == 200 and r.mimetype == "image/png"
    assert Image.open(io.BytesIO(r.data)).size == (160, 90), "scaled to LOOM_FRAME_WIDTH, aspect kept"
    assert frames["calls"] == [("shot_7001.mp4", 1.0, frames["calls"][0][2])]
    assert (frames["fdir"] / "7001_24.png").is_file()
    assert _frame(cli, "7001", "1.01").status_code == 200, "1.01 s is still frame 24"
    assert len(frames["calls"]) == 1, "served from the cache, no second extraction"
    assert _frame(cli, "7001", "1.03").status_code == 200
    assert frames["calls"][1][1] == 25 / 24.0, "the extraction asks for the quantised time"
    assert sorted(f.name for f in frames["fdir"].iterdir()) == ["7001_24.png", "7001_25.png"], "no temp file left"
    assert frames["traps"] == []


@pytest.mark.parametrize("mid", ["../7001", "7001/../x", "abc", "local_xyz", "local_0123456789abc", "", "7001.png", "-1"])
def test_a_bad_media_id_is_refused_before_anything_runs(frames, mid):
    assert _frame(frames["cli"], mid, "1").status_code == 400
    assert frames["calls"] == [] and not frames["fdir"].exists()


@pytest.mark.parametrize("at", ["", "x", "-1", "nan", "inf", "-inf", str(6 * 3600 + 1)])
def test_a_bad_time_is_refused_before_anything_runs(frames, at):
    assert _frame(frames["cli"], "7001", at).status_code == 400
    assert frames["calls"] == []


def test_a_clip_not_on_this_machine_or_with_no_frame_is_a_404_and_leaves_nothing(frames, monkeypatch):
    cli = frames["cli"]
    assert _frame(cli, "9999", "1").status_code == 404
    assert _frame(cli, "7003", "1").status_code == 404, "a zero-byte (half-written) clip is not read"
    assert frames["calls"] == []
    monkeypatch.setattr(core, "frame_at", lambda *a, **k: None)
    r = _frame(cli, "7001", "2")
    assert r.status_code == 404 and "ffmpeg" in r.get_json()["error"]
    assert [f.name for f in frames["fdir"].iterdir()] == [], "no cache file and no temp file"


def test_the_cache_is_lru_capped_and_touches_nothing_else(frames, monkeypatch):
    cli, fdir = frames["cli"], frames["fdir"]
    monkeypatch.setattr(g, "LOOM_FRAME_CACHE_MAX_FILES", 3)
    fdir.mkdir(parents=True)
    (fdir / "7001_last.png").write_bytes(b"the splice's own frame")
    (fdir / "notes.txt").write_bytes(b"x")
    for i, at in enumerate(("1", "2", "3")):
        assert _frame(cli, "7001", at).status_code == 200
        _age(fdir / ("7001_%d.png" % (24 * (i + 1))), 3600 - i * 60)
    assert _frame(cli, "7001", "1").status_code == 200, "a cache hit is a use"
    assert _frame(cli, "7002", "1").status_code == 200
    names = sorted(f.name for f in fdir.iterdir())
    assert names == ["7001_24.png", "7001_72.png", "7001_last.png", "7002_24.png", "notes.txt"], \
        "the least recently used frame (2 s) went; other files are never counted or touched"
    monkeypatch.setattr(g, "LOOM_FRAME_CACHE_MAX_BYTES", 1)
    assert _frame(cli, "7002", "5").status_code in (200, 404)
    assert sorted(f.name for f in fdir.iterdir() if g.LOOM_FRAME_FILE_RE.match(f.name)) in ([], ["7002_120.png"])
    assert (fdir / "7001_last.png").read_bytes() == b"the splice's own frame"
    assert frames["traps"] == []


def test_the_frame_route_never_reaches_pixai_or_a_render(frames):
    """The rig's traps make core.submit, submit_generation, build_request, gql_mutate,
    gql_adhoc, the PixAI session maker and upload_media raise; the AST test above pins that
    loom_frame names none of them (nor _gen_session)."""
    assert _frame(frames["cli"], "7002", "0.5").status_code == 200
    assert _frame(frames["cli"], "7002", "0.5").status_code == 200
    assert frames["traps"] == [], "no submit, no build_request, no gql, no session, no upload"
    assert len(frames["calls"]) == 1


def test_a_board_that_will_not_read_blocks_the_unused_list_and_the_sweep(rig):
    """Red team 2026-10-01: an unreadable board was skipped, so its bed counted as unused and
    the sweep deleted it -- though /api/loom/get says the board exists (500, not 404). Now both
    routes refuse while any board does not read, and the bed stays."""
    cli = rig["cli"]
    n = _upload(cli, FLAC).get_json()["file"]
    _age(_beds_dir(rig["tmp"]) / n)
    _save_board(cli, "b9", {"name": "b", "acts": [], "bed": {"file": n}})
    boards = [p for p in (rig["tmp"] / "loom").rglob("*.json") if "b9" in p.name]
    assert len(boards) == 1, boards
    boards[0].write_text('{"name": "b", "acts": [', encoding="utf-8")     # torn mid-write
    r = cli.get("/api/loom/beds/unused")
    assert r.status_code == 409 and "Nothing was swept" in r.get_json()["error"]
    r = cli.post("/api/loom/beds/sweep", json={"csrf": cli.csrf, "files": [n]})
    assert r.status_code == 409
    assert (_beds_dir(rig["tmp"]) / n).exists()


def _legacy_board_file(tmp, board_id, text):
    """A board only the legacy shared layer (out_dir/loom/kv/) holds, written as-is."""
    from urllib.parse import quote
    d = tmp / "loom" / "kv"
    d.mkdir(parents=True, exist_ok=True)
    p = d / (quote("storyboard:v2:proj:" + board_id, safe="") + ".json")
    p.write_text(text, encoding="utf-8")
    return p


def test_the_refusal_names_every_board_that_will_not_read_and_where_its_file_is(rig):
    """GitHub #57: the refusal used to name no board, so there was no way to find the file. It
    now names EVERY unreadable board (the first bad one no longer hides a second), each with its
    id, a best-effort name, when it was saved and where its file is -- relative to the library,
    never a host path -- and nothing else from the board. Both routes, and the bed stays."""
    cli, tmp = rig["cli"], rig["tmp"]
    n = _upload(cli, FLAC).get_json()["file"]
    _age(_beds_dir(tmp) / n)
    _save_board(cli, "b9", {"name": "Moonwell ep 1", "acts": [], "bed": {"file": n}})
    own = [p for p in (tmp / "loom").rglob("*.json") if "b9" in p.name]
    assert len(own) == 1, own
    # The account's own copy, torn mid-write (the stored value is the board as a JSON string).
    own[0].write_text('"{\\"name\\": \\"Moonwell ep 1\\", \\"acts\\": [{\\"id\\": \\"x', encoding="utf-8")
    # A board only the legacy layer holds: its file reads, the board inside it does not.
    _legacy_board_file(tmp, "b8", json.dumps('{"name": "Old reel", "acts": [{"id": "act-private-words'))
    own_where = "loom/kv/" + _account_key(_TEST_USERNAME) + "/storyboard%3Av2%3Aproj%3Ab9.json"
    legacy_where = "loom/kv/storyboard%3Av2%3Aproj%3Ab8.json"
    for r in (cli.get("/api/loom/beds/unused"),
              cli.post("/api/loom/beds/sweep", json={"csrf": cli.csrf, "files": [n]})):
        assert r.status_code == 409, r.get_json()
        d = r.get_json()
        rows = sorted(d["unreadable"], key=lambda x: x["board"])
        assert [(x["board"], x["name"], x["where"]) for x in rows] == [
            ("b8", "Old reel", legacy_where), ("b9", "Moonwell ep 1", own_where)], rows
        assert all(re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", x["saved"]) for x in rows), rows
        assert all(set(x) == {"board", "name", "saved", "where"} for x in rows), "nothing else from the board"
        assert '"Moonwell ep 1"' in d["error"] and '"Old reel"' in d["error"]
        assert own_where in d["error"] and legacy_where in d["error"]
        assert d["error"].endswith("Nothing was swept.")
        body = r.get_data(as_text=True)
        assert str(tmp) not in body and tmp.as_posix() not in body and "\\\\" not in body, "no host path"
        assert "act-private-words" not in body and "acts" not in body, "no board content"
    assert (_beds_dir(tmp) / n).exists()
    assert rig["traps"] == []


@pytest.mark.parametrize("text,name", [
    ('{"name": "Moonwell ep 1", "acts": [', "Moonwell ep 1"),             # torn after the name
    (json.dumps(json.dumps({"name": 'Say "hi" \u263e', "acts": []}))[:-9], 'Say "hi" \u263e'),   # stored as a string
    ('  {\n  "name" : "Spaced",', "Spaced"),
    ('{"name": "Moonw', ""),                                             # torn inside the name
    ('{"acts": [{"name": "Act 1"}], "name": "late"}', ""),               # an act's name is never the board's
    ('{"name": 7}', ""),
    ("", ""),
    ("\x00\x00\x00", ""),
])
def test_the_board_name_is_salvaged_from_a_file_that_will_not_read(text, name):
    assert g.loom_board_name_salvage(text) == name
    assert len(g.loom_board_name_salvage('{"name": "' + "x" * 500 + '"}')) == 120
