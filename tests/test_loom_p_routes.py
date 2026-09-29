"""Session P, Stage B1: the Loom's new LOCAL routes -- the music bed (P3).

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
    assert cli.post("/api/loom/beds/sweep", json={"files": []}).status_code == 403


def test_every_new_route_is_login_tier(tmp_path):
    anon = create_app(tmp_path).test_client()
    for method, path in (("POST", "/api/loom/bed"), ("GET", "/api/loom/bed?file=x"),
                         ("GET", "/api/loom/beds/unused"), ("POST", "/api/loom/beds/sweep")):
        r = anon.open(path, method=method, json={} if method == "POST" else None)
        assert r.status_code == 401, (method, path, r.status_code)


_NEW_FUNCS = ("api_loom_bed_upload", "api_loom_bed_get", "api_loom_beds_unused", "api_loom_beds_sweep",
              "_loom_bed_path", "_loom_store_bed", "_loom_account_projects", "_loom_unused_beds",
              "_loom_beds_dir")
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
    assert stored == sorted([want, hashlib.sha1(MP3_ID3).hexdigest() + ".mp3"])
    assert not (rig["tmp"].parent / "evil.py").exists() and not (rig["tmp"] / "evil.py").exists()
    assert not (_beds_dir(rig["tmp"]) / forged).exists()


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
