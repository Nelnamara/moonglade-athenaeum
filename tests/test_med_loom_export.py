"""Regressions for two Loom export defects found in the 2026-07-27 review.

M23 -- /api/loom/export synthesized silence for an untrimmed silent shot from a
hardcoded 0.1s whenever ffprobe couldn't report the clip's real duration. Since the
concat filter lays each segment's audio end-to-end, a 0.1s span behind a multi-second
video shifts EVERY later segment's audio early for the rest of loom_cut.mp4 -- the exact
desync the silence-synthesis path exists to prevent, produced silently, in an export that
reports "done".

The first repair refused the whole export instead, which turned out to take the feature
away from an entire class of machine: with ffmpeg but no ffprobe, probe_has_audio() fails
soft to False so EVERY shot reads as silent, and an untrimmed shot is the common case --
so the first shot tripped the refusal and no cut was produced at all, where before there
was at least a (badly desynced) file. These tests pin the current shape: a span is only
ever a trim's own out point or a real measurement; when neither exists the export drops
the audio track (nothing is lost -- that track was going to be synthesized silence) and
still writes the file; and the refusal is kept for the one genuinely corrupt case, where
some shot HAS real audio that a guessed span would push permanently out of sync.

M24 -- /api/loom/export-bundle computed the list of media_ids it couldn't find on disk
and then threw it away, shipping only X-Bundle-Missing-Count, under a comment claiming
"the client surfaces this list". It could not: the owner was told "2 files are missing"
with no way to learn which act/shot they belonged to. The repair puts the ids, each with
the act/shot code it was referenced from, into the zip's own project.json, and adds a
bounded ASCII X-Bundle-Missing header for the live client.
"""
import io
import json
import zipfile

from PIL import Image

import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

from tests.conftest import login_test_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _png_bytes(color=(30, 90, 160), size=(8, 8)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _post_json(cli, url, payload):
    return cli.post(url, data=json.dumps(payload), content_type="application/json")


# --- M23: /api/loom/export ---------------------------------------------------------


def _mock_export_ffmpeg(monkeypatch):
    """ffmpeg present, Popen faked. Mirrors tests/test_panel.py's helper of the same
    name, including its argv[0] guard -- create_app() shells `git rev-parse --short HEAD`
    for its build stamp through this same patched Popen, and writing to argv[-1]
    unconditionally would drop a stray file named HEAD into the repo root."""
    import io as _io
    import subprocess
    import moonglade_backup as core
    # ffmpeg present, ffprobe absent -- the export asks media_tools now, not
    # shutil.which. "ffmpeg" stays the resolved path so argv[0] keeps reading "ffmpeg".
    monkeypatch.setattr(core, "ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(core, "ffprobe_path", lambda: "")
    captured = []

    class FakeProc:
        def __init__(self, argv):
            captured.append(argv)
            if argv and argv[0] == "ffmpeg":
                open(argv[-1], "wb").write(b"OUTPUT")
            self.stderr = _io.StringIO("frame=1 time=00:00:01.00 bitrate=x\n")

        def wait(self):
            return 0

    monkeypatch.setattr(subprocess, "Popen", lambda argv, **k: FakeProc(argv))
    return captured


def _video_client(tmp_path, mids=("v1", "v2")):
    (tmp_path / "videos").mkdir(exist_ok=True)
    rows = []
    for m in mids:
        (tmp_path / "videos" / "shot_{}.mp4".format(m)).write_bytes(b"fakemp4")
        rows.append(_row(media_id=m, filename="videos/shot_{}.mp4".format(m),
                         is_video="1", created_at="2025-01-01T00:00:00"))
    save_catalog(tmp_path / "catalog.db", rows)
    return login_test_client(create_app(tmp_path))


def _ffmpeg_call(captured):
    return next((argv for argv in captured if argv and argv[0] == "ffmpeg"), None)


def _filter_complex(captured):
    argv = _ffmpeg_call(captured)
    assert argv is not None, "no ffmpeg was spawned"
    return argv, argv[argv.index("-filter_complex") + 1]


def test_a_machine_with_ffmpeg_but_no_ffprobe_still_gets_a_cut(tmp_path, monkeypatch):
    """The regression the first M23 repair introduced, and the reason it needed softening.

    _mock_export_ffmpeg reports ffprobe absent, which is the real shape of that machine:
    probe_has_audio() fails soft to False for EVERY clip, and an untrimmed shot is the
    documented default (`co is None`), so the very first shot hit the refusal and the owner
    got no export at all -- a feature wiki/The-Loom.md says needs ffmpeg, taken away over a
    binary it never mentions.

    A file comes out again, and the 0.1s guess is still gone: with no real audio anywhere,
    the entire audio track was going to be synthesized silence, so it is dropped rather than
    invented. Nothing can drift, because there is nothing left to drift against.
    """
    captured = _mock_export_ffmpeg(monkeypatch)
    monkeypatch.setattr(g, "probe_has_audio", lambda path: False)
    monkeypatch.setattr(g, "probe_duration", lambda path: None)
    cli = _video_client(tmp_path)
    r = cli.post("/api/loom/export", json={"clips": [{"mid": "v1", "in": 0},
                                                     {"mid": "v2", "in": 0}],
                                           "total_seconds": 10})
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True and body["audio"] is False
    argv, fc = _filter_complex(captured)
    assert "atrim=duration=" not in fc, "a silence span was invented after all"
    assert "0.100" not in fc
    assert "concat=n=2:v=1:a=0[vout]" in fc
    assert "[aout]" not in argv and "anullsrc=channel_layout=stereo:sample_rate=48000" not in argv
    assert "-c:a" not in argv, "an audio codec for a stream that isn't mapped"


def test_a_dropped_audio_track_is_reported_on_screen_not_only_in_the_log(tmp_path, monkeypatch):
    """Degrading quietly is its own bug. The owner asked for a cut with sound and got one
    without; the reason is a missing binary they can install in a minute, and the person
    staring at the export dialog is the only one positioned to fix it. Writing that to the
    server log -- a file nobody opens unless they already suspect something -- is how it
    stays a mystery, so `warning` rides the status the dialog is already polling.

    `warning` is deliberately separate from `error`: the export SUCCEEDED. Folding it into
    `error` would paint the dialog red and hide the download button for a file that exists
    and is fine apart from its audio.
    """
    _mock_export_ffmpeg(monkeypatch)
    monkeypatch.setattr(g, "probe_has_audio", lambda path: False)
    monkeypatch.setattr(g, "probe_duration", lambda path: None)
    cli = _video_client(tmp_path)
    r = cli.post("/api/loom/export", json={"clips": [{"mid": "v1", "in": 0},
                                                     {"mid": "v2", "in": 0}],
                                           "total_seconds": 10})
    assert r.status_code == 200 and r.get_json()["audio"] is False

    st = cli.get("/api/loom/export-status").get_json()
    assert "warning" in st, "the dialog polls this route; a warning it never sees is a log entry"
    w = st["warning"]
    assert w, "the track was dropped and nothing said so"
    assert "no audio track" in w
    assert "ffprobe" in w, "name the missing piece -- 'something went wrong' is not actionable"
    assert not st["error"], "a successful export must not read as failed"


def test_the_export_refuses_only_when_real_audio_would_be_desynced(tmp_path, monkeypatch):
    """The one refusal left, and the case that earns it. v1 carries real recorded audio;
    v2 is silent, untrimmed, and unmeasurable. Padding v2 with a guess pushes v1's real
    audio permanently out of position, and dropping the track throws that audio away -- both
    are worse than not producing a file, so this one stops.

    The message names ffprobe, because that is the tool that could not answer, and the shot,
    because setting its out point is the fix the owner can apply without installing anything.
    """
    captured = _mock_export_ffmpeg(monkeypatch)
    monkeypatch.setattr(g, "probe_has_audio", lambda path: "v1" in str(path))
    monkeypatch.setattr(g, "probe_duration", lambda path: None)
    cli = _video_client(tmp_path)
    r = cli.post("/api/loom/export", json={"clips": [
        {"mid": "v1", "in": 0}, {"mid": "v2", "in": 0}], "total_seconds": 8})
    assert r.status_code == 400
    err = r.get_json()["error"]
    assert "v2" in err                          # names the shot the owner has to go fix
    assert "ffprobe" in err                     # ...and the tool that could not answer
    assert "out point" in err
    assert _ffmpeg_call(captured) is None       # nothing spawned -- no desynced cut exists
    assert cli.get("/api/loom/export-status").get_json()["status"] != "running"


def test_an_unreadable_file_among_silent_shots_degrades_instead_of_refusing(tmp_path, monkeypatch):
    """ffprobe IS installed and answers for v1, but v2's duration is unreadable (truncated,
    still downloading). No shot has real audio, so there is still nothing to keep in sync:
    the cut is written without an audio track rather than refused. Refusing here would cost
    the owner the whole export to protect a track of silence."""
    captured = _mock_export_ffmpeg(monkeypatch)
    import moonglade_backup as core
    # ffprobe IS installed here -- that is this test's whole premise. Only ffprobe is
    # re-pinned; ffmpeg_path stays "ffmpeg" from _mock_export_ffmpeg so the FakeProc
    # guard and _ffmpeg_call() still recognise the spawned command.
    monkeypatch.setattr(core, "ffprobe_path", lambda: "/usr/bin/ffprobe")
    monkeypatch.setattr(g, "probe_has_audio", lambda path: False)
    monkeypatch.setattr(g, "probe_duration",
                        lambda path: 4.0 if "v1" in str(path) else None)
    cli = _video_client(tmp_path)
    r = cli.post("/api/loom/export", json={"clips": [
        {"mid": "v1", "in": 0}, {"mid": "v2", "in": 0}], "total_seconds": 8})
    assert r.status_code == 200 and r.get_json()["audio"] is False
    _argv, fc = _filter_complex(captured)
    assert "concat=n=2:v=1:a=0[vout]" in fc
    assert "atrim=duration=" not in fc, (
        "v1's measurable span is irrelevant once the track is dropped -- a half-built audio "
        "chain is how a filtergraph ends up referencing labels concat never receives")


def test_real_audio_beside_a_measurable_silent_shot_is_not_refused(tmp_path, monkeypatch):
    """The refusal is gated on `unmeasurable AND have_real_audio`, and the second half is
    the new condition -- so this pins that adding it did not make every mixed project
    refuse. v1 has a real audio stream, v2 is silent and untrimmed but measurable: the
    export runs with both chains, exactly as it always did."""
    captured = _mock_export_ffmpeg(monkeypatch)
    monkeypatch.setattr(g, "probe_has_audio", lambda path: "v1" in str(path))
    monkeypatch.setattr(g, "probe_duration", lambda path: 6.0)
    cli = _video_client(tmp_path)
    r = cli.post("/api/loom/export", json={"clips": [
        {"mid": "v1", "in": 0}, {"mid": "v2", "in": 1}], "total_seconds": 11})
    assert r.status_code == 200 and r.get_json()["audio"] is True
    _argv, fc = _filter_complex(captured)
    assert "[0:a]atrim=start=0.000" in fc            # v1's REAL audio, trimmed not replaced
    assert "[2:a]atrim=duration=5.000" in fc         # v2's silence: 6.0 - 1
    assert "concat=n=2:v=1:a=1[vout][aout]" in fc


def test_export_still_runs_when_the_duration_is_readable(tmp_path, monkeypatch):
    """The guard must not fire on the healthy path: a measured duration still produces a
    span of dur - in, exactly as before."""
    captured = _mock_export_ffmpeg(monkeypatch)
    monkeypatch.setattr(g, "probe_has_audio", lambda path: False)
    monkeypatch.setattr(g, "probe_duration", lambda path: 7.5)
    cli = _video_client(tmp_path)
    r = cli.post("/api/loom/export", json={"clips": [{"mid": "v1", "in": 1.5}],
                                           "total_seconds": 6})
    assert r.get_json()["ok"] is True
    argv = _ffmpeg_call(captured)
    fc = argv[argv.index("-filter_complex") + 1]
    assert "[1:a]atrim=duration=6.000" in fc      # 7.5 - 1.5, not 0.1


def test_export_never_probes_when_every_silent_shot_carries_an_out_point(tmp_path, monkeypatch):
    """Why ffprobe is NOT gated by the up-front ffmpeg_path() check: an export
    whose silent shots all have explicit out points needs no probe at all and produces a
    correct cut on a machine with no ffprobe. Refusing that up front would reject work
    that was going to succeed."""
    captured = _mock_export_ffmpeg(monkeypatch)
    monkeypatch.setattr(g, "probe_has_audio", lambda path: False)

    def _never(path):
        raise AssertionError("probe_duration must not be called when 'out' is given")

    monkeypatch.setattr(g, "probe_duration", _never)
    cli = _video_client(tmp_path)
    r = cli.post("/api/loom/export", json={"clips": [
        {"mid": "v1", "in": 0, "out": 2}, {"mid": "v2", "in": 1, "out": 4}],
        "total_seconds": 5})
    assert r.get_json()["ok"] is True
    fc_argv = _ffmpeg_call(captured)
    fc = fc_argv[fc_argv.index("-filter_complex") + 1]
    assert "[2:a]atrim=duration=2.000" in fc and "[2:a]atrim=duration=3.000" in fc


# --- M24: /api/loom/export-bundle --------------------------------------------------


def _authed_client(tmp_path, rows=()):
    if rows:
        save_catalog(tmp_path / "catalog.db", list(rows))
    return login_test_client(create_app(tmp_path))


def _project_with_missing_shot():
    """Act 1 shot 1 has a resultMid nothing on disk can resolve, plus a dead cast asset."""
    return {
        "name": "Bundle Test",
        "acts": [{"id": "a1", "name": "Act 1", "cards": [
            {"id": "c1", "title": "Establishing shot", "resultMid": "gone-1",
             "openFrame": {}, "closeFrame": {}},
        ]}],
        "assets": [{"id": "as1", "name": "Her", "tag": "@image1", "mediaId": "gone-2"}],
    }


def test_bundle_lists_missing_ids_in_the_zip_not_just_a_count(tmp_path):
    """The M24 regression proper. Against the old code the only signal was
    X-Bundle-Missing-Count: 2 -- `missing` was discarded after len() was taken, so neither
    the header nor the zip carried a single id. The list now travels INSIDE the bundle,
    which is what makes it survive the download and reach whoever the zip is handed to."""
    cli = _authed_client(tmp_path, [])
    r = _post_json(cli, "/api/loom/export-bundle",
                   {"project": _project_with_missing_shot(), "thumbs": {}})
    assert r.status_code == 200
    assert r.headers.get("X-Bundle-Missing-Count") == "2"
    z = zipfile.ZipFile(io.BytesIO(r.data))
    payload = json.loads(z.read("project.json"))
    ids = {m["media_id"] for m in payload["missing_media"]}
    assert ids == {"gone-1", "gone-2"}
    # ...and the envelope import-bundle reads is untouched by the added key.
    assert payload["project"]["name"] == "Bundle Test"
    assert "thumbs" in payload


def test_bundle_missing_entries_name_the_act_and_shot(tmp_path):
    """The finding's actual complaint: "2 files are missing" with no way to identify which
    act/shot they belong to short of hand-diffing every project reference. Each entry
    carries the same A·NN shot code the Loom prints on screen."""
    cli = _authed_client(tmp_path, [])
    r = _post_json(cli, "/api/loom/export-bundle",
                   {"project": _project_with_missing_shot(), "thumbs": {}})
    by_id = {m["media_id"]: m["referenced_by"]
             for m in json.loads(zipfile.ZipFile(io.BytesIO(r.data)).read("project.json"))["missing_media"]}
    assert by_id["gone-1"] == ["A·01 Establishing shot (shot result)"]
    assert by_id["gone-2"] == ["cast/asset Her"]


def test_bundle_missing_header_carries_the_ids(tmp_path):
    """X-Bundle-Missing is the live copy the client can name ids from; the count header
    stays for the client that already reads it."""
    cli = _authed_client(tmp_path, [])
    r = _post_json(cli, "/api/loom/export-bundle",
                   {"project": _project_with_missing_shot(), "thumbs": {}})
    assert set(r.headers["X-Bundle-Missing"].split(",")) == {"gone-1", "gone-2"}
    assert r.headers["X-Bundle-Missing-Count"] == "2"


def test_bundle_missing_header_is_absent_when_nothing_is_missing(tmp_path):
    (tmp_path / "a_100.png").write_bytes(_png_bytes())
    cli = _authed_client(tmp_path, [_row(media_id="100", filename="a_100.png")])
    project = {"name": "P", "acts": [], "assets": [{"id": "as1", "mediaId": "100"}]}
    r = _post_json(cli, "/api/loom/export-bundle", {"project": project, "thumbs": {}})
    assert r.headers["X-Bundle-Missing-Count"] == "0"
    assert "X-Bundle-Missing" not in r.headers
    assert json.loads(zipfile.ZipFile(io.BytesIO(r.data)).read("project.json"))["missing_media"] == []


def test_bundle_missing_header_is_sanitized_against_client_supplied_ids(tmp_path):
    """media_ids come out of client-supplied project JSON, so they are filtered, not
    trusted: a CR/LF in one would be header injection, and a non-latin-1 one makes
    Werkzeug raise while serialising the response -- turning a successful export into a
    500. The unfiltered id still travels intact in project.json, where it is data."""
    nasty = "bad\r\nX-Injected: yes"
    project = {"name": "P", "acts": [],
               "assets": [{"id": "as1", "mediaId": nasty},
                          {"id": "as2", "mediaId": "café-ÿ"}]}
    cli = _authed_client(tmp_path, [])
    r = _post_json(cli, "/api/loom/export-bundle", {"project": project, "thumbs": {}})
    assert r.status_code == 200
    assert "X-Injected" not in r.headers
    hdr = r.headers["X-Bundle-Missing"]
    assert "\r" not in hdr and "\n" not in hdr
    assert hdr.encode("ascii")                   # latin-1 safe, so Werkzeug can serialise it
    assert "badX-Injectedyes" in hdr             # separators stripped, not the whole id
    ids = {m["media_id"] for m in
           json.loads(zipfile.ZipFile(io.BytesIO(r.data)).read("project.json"))["missing_media"]}
    assert nasty in ids                          # the real id is preserved where it's safe


def test_bundle_missing_header_is_bounded_for_a_project_missing_hundreds(tmp_path):
    """A header that grows with the project is how a bundle downloads on the machine that
    built it and gets rejected by a proxy on the next. The count header stays authoritative
    and the full list is in the zip, so the truncation loses nothing."""
    project = {"name": "P", "acts": [],
               "assets": [{"id": "as%d" % i, "mediaId": "missing-media-id-%04d" % i}
                          for i in range(400)]}
    cli = _authed_client(tmp_path, [])
    r = _post_json(cli, "/api/loom/export-bundle", {"project": project, "thumbs": {}})
    hdr = r.headers["X-Bundle-Missing"]
    assert len(hdr) < 1000                       # bounded, not 400 * ~21 bytes
    assert hdr.endswith("more")                  # explicit "+N more" tail, not a silent cut
    assert r.headers["X-Bundle-Missing-Count"] == "400"
    payload = json.loads(zipfile.ZipFile(io.BytesIO(r.data)).read("project.json"))
    assert len(payload["missing_media"]) == 400  # nothing truncated where it matters


def test_bundle_collector_dedupes_but_keeps_every_reference_site(tmp_path):
    """One media_id used as both a shot's close frame and the next shot's open frame is a
    single zip entry, but the report has to name BOTH places it was referenced -- otherwise
    the owner fixes one and is surprised by the other."""
    project = {
        "name": "P",
        "acts": [{"id": "a1", "cards": [
            {"id": "c1", "title": "One", "closeFrame": {"mediaId": "shared"}},
            {"id": "c2", "title": "Two", "openFrame": {"mediaId": "shared"}},
        ]}],
        "assets": [],
    }
    cli = _authed_client(tmp_path, [])
    r = _post_json(cli, "/api/loom/export-bundle", {"project": project, "thumbs": {}})
    assert r.headers["X-Bundle-Missing-Count"] == "1"
    entries = json.loads(zipfile.ZipFile(io.BytesIO(r.data)).read("project.json"))["missing_media"]
    assert len(entries) == 1
    assert entries[0]["referenced_by"] == ["A·01 One (closeFrame)",
                                           "A·02 Two (openFrame)"]


def test_bundle_import_ignores_the_missing_manifest(tmp_path):
    """import-bundle reads `project`/`thumbs`; the added key must not disturb the round
    trip -- exporting a partial bundle and importing it back still yields the project."""
    cli = _authed_client(tmp_path, [])
    r = _post_json(cli, "/api/loom/export-bundle",
                   {"project": _project_with_missing_shot(), "thumbs": {"t1": "data"}})
    back = cli.post("/api/loom/import-bundle",
                    data={"file": (io.BytesIO(r.data), "bundle.zip")},
                    content_type="multipart/form-data")
    d = back.get_json()
    assert back.status_code == 200
    assert d["project"]["name"] == "Bundle Test"
    assert d["thumbs"] == {"t1": "data"}
