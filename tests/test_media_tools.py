"""The media_tools section of moonglade_backup.py -- the one ffmpeg/ffprobe seam.

Seven call sites used to re-type an availability check, `creationflags=_NO_WINDOW`, a
timeout and a blanket `except`, and disagreed on all four; two of them asked ffprobe the
same duration question through different flags and answered differently. These tests pin
the seam that replaced them, on three axes:

  * the ARGV, FLAGS and TIMEOUT each public function hands the OS -- caught by a recording
    fake runner, because "it still works" is not the same claim as "it still asks for
    -movflags +faststart with 300 seconds and no console window";
  * the BINARY-ABSENT road for every one of them -- the standing rule is that a missing
    ffprobe degrades a feature and never blocks it, so each function must answer
    None/False/`missing`, must not raise, and must leave a vlog() line so a degraded run is
    on record rather than silent;
  * that the two duration probes this section replaced AGREE on one fixture, which is the
    drift the section exists to end.
"""
import subprocess
from types import SimpleNamespace

import pytest

import moonglade_backup as core
import moonglade_gallery as g


# ---------------------------------------------------------------------------
# a recording fake runner
# ---------------------------------------------------------------------------

class _Rec:
    """Stands in for subprocess.run and remembers every call, faithfully shaped:
    a real CompletedProcess always has returncode, stdout and stderr."""

    def __init__(self, monkeypatch, returncode=0, stdout="", stderr="", writes=None,
                 raises=None):
        self.calls = []
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr
        self.writes, self.raises = writes, raises
        monkeypatch.setattr(subprocess, "run", self)

    def __call__(self, argv, **kw):
        self.calls.append((list(argv), kw))
        if self.raises is not None:
            raise self.raises
        if self.writes is not None:
            with open(argv[-1], "wb") as fh:
                fh.write(self.writes)
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout,
                               stderr=self.stderr)

    @property
    def argv(self):
        assert len(self.calls) == 1, "expected exactly one spawn, got {}".format(len(self.calls))
        return self.calls[0][0]

    @property
    def kwargs(self):
        assert len(self.calls) == 1, "expected exactly one spawn, got {}".format(len(self.calls))
        return self.calls[0][1]


@pytest.fixture()
def verbose():
    """Turn -v on for the duration of a test (and back off afterwards, always), so a vlog()
    line lands in capsys. Mirrors tests/test_med_backup_errors.py's fixture of the same
    name -- "the failure was swallowed but not silenced" is only checkable under -v."""
    core.set_verbose(True)
    try:
        yield
    finally:
        core.set_verbose(False)


@pytest.fixture
def have_tools(monkeypatch):
    """Both binaries 'installed', at paths distinctive enough to prove argv[0] came from
    the seam and not from a bare name typed at the call site."""
    monkeypatch.setattr(core, "ffmpeg_path", lambda: "/opt/bin/ffmpeg")
    monkeypatch.setattr(core, "ffprobe_path", lambda: "/opt/bin/ffprobe")


@pytest.fixture
def no_tools(monkeypatch):
    monkeypatch.setattr(core, "ffmpeg_path", lambda: "")
    monkeypatch.setattr(core, "ffprobe_path", lambda: "")


# ---------------------------------------------------------------------------
# availability: one cached probe each, asked separately
# ---------------------------------------------------------------------------

def test_the_binaries_are_resolved_once_each_and_separately(monkeypatch):
    """Cached, because it is asked per-file on thumbnail sweeps and per-shot on exports.
    Separately, because a machine with ffmpeg and no ffprobe is a real machine the Loom
    export has to keep serving -- one shared answer would gate the two together."""
    import shutil
    asked = []
    monkeypatch.setattr(shutil, "which",
                        lambda n: asked.append(n) or ("/opt/bin/" + n if n == "ffmpeg" else None))
    core._reset_tool_cache()
    try:
        assert core.ffmpeg_path() == "/opt/bin/ffmpeg"
        assert core.ffmpeg_path() == "/opt/bin/ffmpeg"      # cached: no second which()
        assert core.ffprobe_path() == ""                    # absent, and its own answer
        assert core.ffprobe_path() == ""
        assert asked == ["ffmpeg", "ffprobe"]
    finally:
        core._reset_tool_cache()


# ---------------------------------------------------------------------------
# run_ffmpeg / run_ffprobe: argv, flags, timeout, and the ToolResult
# ---------------------------------------------------------------------------

def test_run_ffmpeg_supplies_the_binary_the_flags_and_the_timeout(have_tools, monkeypatch):
    rec = _Rec(monkeypatch, stdout="out", stderr="err")
    r = core.run_ffmpeg(["-i", "a.mp4", "b.png"], timeout=12)

    assert rec.argv == ["/opt/bin/ffmpeg", "-i", "a.mp4", "b.png"], "the caller passes args only"
    kw = rec.kwargs
    assert kw["timeout"] == 12
    assert kw["creationflags"] == core.NO_WINDOW     # no console window flashes on Windows
    assert kw["stderr"] is subprocess.PIPE           # ffmpeg says WHY only here
    assert kw["stdout"] is subprocess.PIPE
    assert kw["text"] is True and kw["encoding"] == "utf-8" and kw["errors"] == "replace"
    assert (r.ok, r.returncode, r.stdout, r.stderr, r.missing) == (True, 0, "out", "err", False)


def test_run_ffprobe_supplies_the_binary_the_flags_and_the_timeout(have_tools, monkeypatch):
    rec = _Rec(monkeypatch, stdout="7.5\n")
    r = core.run_ffprobe(["-show_entries", "format=duration", "clip.mp4"], timeout=9)

    assert rec.argv == ["/opt/bin/ffprobe", "-show_entries", "format=duration", "clip.mp4"]
    assert rec.kwargs["timeout"] == 9
    assert rec.kwargs["creationflags"] == core.NO_WINDOW
    assert r.ok is True and r.missing is False and r.stdout == "7.5\n"


def test_run_ffmpeg_passes_stdin_through(have_tools, monkeypatch):
    rec = _Rec(monkeypatch)
    core.run_ffmpeg(["-f", "concat", "-i", "-", "out.mp4"], timeout=5, input="file 'a.mp4'\n")
    assert rec.kwargs["input"] == "file 'a.mp4'\n"


def test_a_nonzero_exit_is_an_answer_not_an_exception(have_tools, monkeypatch):
    """ffmpeg's ordinary way of refusing a file. It comes back as a ToolResult carrying the
    code and ffmpeg's own stderr -- not missing, not raised, and deliberately not logged
    here: what it MEANS is the caller's to say (the remux names the clip; the thumbnail
    retries with different flags)."""
    _Rec(monkeypatch, returncode=1, stderr="could not find sample table")
    r = core.run_ffmpeg(["-i", "bad.mp4", "out.mp4"], timeout=5)
    assert r.ok is False and r.returncode == 1 and r.missing is False
    assert "sample table" in r.stderr


def test_a_timeout_is_swallowed_named_and_logged(have_tools, monkeypatch, verbose, capsys):
    _Rec(monkeypatch, raises=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=5))
    r = core.run_ffmpeg(["-i", "slow.mp4", "out.mp4"], timeout=5)
    assert r.ok is False and r.missing is False and r.returncode is None
    assert "timed out" in r.stderr
    assert "timed out after 5s" in capsys.readouterr().out


def test_a_binary_that_vanished_after_which_takes_the_missing_road(have_tools, monkeypatch,
                                                                   verbose, capsys):
    """which() said yes and the exec still failed -- a moved binary, or a shim pointing at
    nothing. Indistinguishable to the caller from never having had it, so it answers the
    same way rather than escaping as the FileNotFoundError a blanket except used to eat."""
    _Rec(monkeypatch, raises=FileNotFoundError("no such file: ffmpeg"))
    r = core.run_ffmpeg(["-i", "a.mp4", "b.png"], timeout=5)
    assert r.missing is True and r.ok is False and r.returncode is None
    assert "vanished" in capsys.readouterr().out


def test_an_absent_binary_never_spawns_and_says_so(no_tools, monkeypatch, verbose, capsys):
    rec = _Rec(monkeypatch)
    for r in (core.run_ffmpeg(["-i", "a.mp4"], timeout=5),
              core.run_ffprobe(["clip.mp4"], timeout=5)):
        assert r.missing is True and r.ok is False and r.returncode is None
    assert rec.calls == [], "asked the OS to run a binary it had already been told is absent"
    out = capsys.readouterr().out
    assert "ffmpeg is not installed" in out and "ffprobe is not installed" in out


# ---------------------------------------------------------------------------
# duration()
# ---------------------------------------------------------------------------

def test_duration_argv_and_full_precision(have_tools, monkeypatch):
    rec = _Rec(monkeypatch, stdout="12.345678\n")
    assert core.duration("clip.mp4") == 12.345678, "the one answer does not round for anyone"
    assert rec.argv == ["/opt/bin/ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", "clip.mp4"]
    assert rec.kwargs["timeout"] == core.PROBE_TIMEOUT


def test_duration_without_ffprobe_is_none_never_a_raise(no_tools, monkeypatch, verbose, capsys):
    _Rec(monkeypatch)
    assert core.duration("clip.mp4") is None
    assert "ffprobe is not installed" in capsys.readouterr().out


def test_duration_survives_garbage_and_a_refusal(have_tools, monkeypatch):
    _Rec(monkeypatch, stdout="N/A\n")
    assert core.duration("clip.mp4") is None
    _Rec(monkeypatch, returncode=1, stdout="")
    assert core.duration("clip.mp4") is None


# ---------------------------------------------------------------------------
# has_audio()
# ---------------------------------------------------------------------------

def test_has_audio_argv_and_three_way_answer(have_tools, monkeypatch):
    rec = _Rec(monkeypatch, stdout="0\n")
    assert core.has_audio("clip.mp4") is True
    assert rec.argv == ["/opt/bin/ffprobe", "-v", "error", "-select_streams", "a",
                        "-show_entries", "stream=index", "-of", "csv=p=0", "clip.mp4"]
    assert rec.kwargs["timeout"] == core.PROBE_TIMEOUT

    _Rec(monkeypatch, stdout="")
    assert core.has_audio("silent.mp4") is False, "ffprobe looked and found no stream"


def test_has_audio_without_ffprobe_is_none_not_false(no_tools, monkeypatch, verbose, capsys):
    """The distinction the whole seam exists for. "Definitely silent" and "I could not
    look" are different facts; collapsing them is how a machine without ffprobe came to
    read every clip as silent with nothing able to notice. The gallery's own face still
    coerces to False -- deliberately, in one place (see probe_has_audio)."""
    _Rec(monkeypatch)
    assert core.has_audio("clip.mp4") is None
    assert g.probe_has_audio("clip.mp4") is False
    assert "ffprobe is not installed" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# extract_last_frame() / frame_at()
# ---------------------------------------------------------------------------

def test_frame_at_eof_argv(have_tools, monkeypatch, tmp_path):
    out = tmp_path / "f.png"
    rec = _Rec(monkeypatch, writes=b"PNG")
    assert core.frame_at("clip.mp4", None, out) == str(out)
    assert rec.argv == ["/opt/bin/ffmpeg", "-y", "-sseof", "-0.15", "-i", "clip.mp4",
                        "-update", "1", "-frames:v", "1", "-q:v", "2", str(out)]
    assert rec.kwargs["timeout"] == core.FRAME_TIMEOUT


def test_frame_at_seeks_a_hair_before_the_out_point(have_tools, monkeypatch, tmp_path):
    """Trim-aware handoff: the measured clip is longer than the asked-for point, so the
    explicit seek is used -- backed off 0.05s so we land ON the last kept frame."""
    out = tmp_path / "f.png"
    monkeypatch.setattr(core, "duration", lambda p, **k: 10.0)
    rec = _Rec(monkeypatch, writes=b"PNG")
    assert core.frame_at("clip.mp4", 3.2, out) == str(out)
    assert rec.argv[1:6] == ["-y", "-ss", "3.150", "-i", "clip.mp4"]


def test_a_trim_at_or_past_the_real_end_falls_back_to_eof(have_tools, monkeypatch, tmp_path):
    out = tmp_path / "f.png"
    monkeypatch.setattr(core, "duration", lambda p, **k: 5.0)
    rec = _Rec(monkeypatch, writes=b"PNG")
    core.frame_at("clip.mp4", 5.0, out)
    assert "-sseof" in rec.argv and "-ss" not in rec.argv


def test_trim_aware_false_skips_the_measurement(have_tools, monkeypatch, tmp_path):
    out = tmp_path / "f.png"

    def _never(*a, **k):
        raise AssertionError("trim_aware=False must not measure the clip")
    monkeypatch.setattr(core, "duration", _never)
    rec = _Rec(monkeypatch, writes=b"PNG")
    core.frame_at("clip.mp4", 3.2, out, trim_aware=False)
    assert rec.argv[1:4] == ["-y", "-ss", "3.150"]


def test_frame_zero_is_the_first_frame_through_the_same_primitive(have_tools, monkeypatch,
                                                                  tmp_path):
    """DECISIONS: extract_last_frame is a GENERAL frame primitive -- at_seconds=0.0 takes
    the explicit-seek branch and yields the FIRST frame, and nothing may duplicate it.
    frame_at is that primitive under the module's argument order, not a second copy."""
    out = tmp_path / "f.png"
    monkeypatch.setattr(core, "duration", lambda p, **k: 8.0)
    rec = _Rec(monkeypatch, writes=b"PNG")
    core.frame_at("clip.mp4", 0.0, out)
    assert rec.argv[1:4] == ["-y", "-ss", "0.000"], "0.0 must not become the EOF path"
    assert core.extract_last_frame("clip.mp4", out, at_seconds=0.0) == str(out)


def test_frame_extraction_without_ffmpeg_is_none_never_a_raise(no_tools, monkeypatch,
                                                               tmp_path, verbose, capsys):
    rec = _Rec(monkeypatch)
    out = tmp_path / "f.png"
    assert core.frame_at("clip.mp4", None, out) is None
    assert core.extract_last_frame("clip.mp4", out) is None
    assert rec.calls == []
    assert not out.exists()
    assert "ffmpeg is not installed" in capsys.readouterr().out


def test_an_empty_output_file_is_not_a_frame(have_tools, monkeypatch, tmp_path):
    out = tmp_path / "f.png"
    _Rec(monkeypatch, writes=b"")          # ffmpeg exits 0 but writes nothing usable
    assert core.frame_at("clip.mp4", None, out) is None


# ---------------------------------------------------------------------------
# the callers that used to re-type all of this
# ---------------------------------------------------------------------------

def test_the_faststart_remux_takes_its_binary_flags_and_timeout_from_the_seam(
        have_tools, monkeypatch, tmp_path):
    """The unique-temp-name concurrency rule is pinned by test_filesystem.py; this pins
    that the remux goes through the seam -- resolved binary, no-window flag, the section's
    own REMUX_TIMEOUT -- and still asks for exactly the lossless faststart shape."""
    import struct
    clip = tmp_path / "nf.mp4"
    clip.write_bytes(b"".join(struct.pack(">I", 16) + t + b"\x00" * 8
                              for t in (b"ftyp", b"mdat", b"moov")))
    rec = _Rec(monkeypatch, writes=b"REMUXED")
    assert core.video_faststart(clip) is True
    argv, kw = rec.calls[0]
    assert argv[0] == "/opt/bin/ffmpeg"
    assert argv[1:8] == ["-y", "-v", "error", "-i", str(clip), "-c", "copy"]
    assert argv[8:10] == ["-movflags", "+faststart"]
    assert "__fstmp__" in argv[-1] and argv[-1].endswith(".mp4")
    assert kw["timeout"] == core.REMUX_TIMEOUT and kw["creationflags"] == core.NO_WINDOW
    assert clip.read_bytes() == b"REMUXED"


def test_the_video_thumbnail_takes_its_binary_and_timeouts_from_the_seam(
        have_tools, monkeypatch, tmp_path):
    """Two shapes, one seam: the representative-frame filter first, then the literal first
    frame for clips too short for it to get a batch. Each with the section's own timeout."""
    from PIL import Image

    def _write_a_jpeg(argv, **kw):
        Image.new("RGB", (8, 8), (10, 20, 30)).save(argv[-1], "JPEG")

    calls = []

    def fake_run(argv, **kw):
        calls.append((list(argv), kw))
        if len(calls) == 1:
            return SimpleNamespace(returncode=1, stdout="", stderr="too short")
        _write_a_jpeg(argv, **kw)
        return SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert g.make_video_thumbnail(tmp_path / "clip.mp4", tmp_path / "t.jpg") is True
    assert (tmp_path / "t.jpg").exists()
    assert [a[0][0] for a in calls] == ["/opt/bin/ffmpeg", "/opt/bin/ffmpeg"]
    assert "thumbnail=72" in calls[0][0] and "-vf" not in calls[1][0]
    assert calls[0][1]["timeout"] == core.THUMB_TIMEOUT
    assert calls[1][1]["timeout"] == core.THUMB_RETRY_TIMEOUT
    assert all(c[1]["creationflags"] == core.NO_WINDOW for c in calls)


def test_the_video_thumbnail_without_ffmpeg_is_false_and_spawns_nothing(
        no_tools, monkeypatch, tmp_path):
    rec = _Rec(monkeypatch)
    assert g.make_video_thumbnail(tmp_path / "clip.mp4", tmp_path / "t.jpg") is False
    assert core.video_poster_thumb(tmp_path / "clip.mp4", tmp_path / "t.jpg") is False
    assert rec.calls == [] and not (tmp_path / "t.jpg").exists()


# ---------------------------------------------------------------------------
# the drift this section exists to end
# ---------------------------------------------------------------------------

def test_the_two_old_duration_probes_agree_on_one_fixture(have_tools, monkeypatch):
    """The reason there is one answer now. `probe_video_duration` (backup) and
    `probe_duration` (gallery) asked ffprobe the SAME question through different `-of`
    flags with different timeouts, and disagreed in the last two decimals because one of
    them rounded inside the probe. Both names now resolve to media_tools.duration, so on
    one fixture they must return the identical object -- and the value must be the
    unrounded measurement, since rounding is a thing a caller does where it can be seen.
    """
    _Rec(monkeypatch, stdout="6.283185\n")
    ours = core.duration("clip.mp4")
    theirs = g.probe_duration("clip.mp4")
    assert ours == theirs == 6.283185
    assert round(ours, 2) == 6.28, "a caller that wants 2dp still gets them, at its own site"


def test_every_media_spawn_in_the_app_goes_through_the_seam():
    """The structural half of "one module": no ffmpeg or ffprobe command may be assembled
    outside media_tools. A new call site that re-types a bare binary name is exactly how
    the seven sites drifted apart in the first place, and it would not fail any behavioural
    test above -- only this one."""
    import io
    import re
    from pathlib import Path
    repo = Path(__file__).resolve().parent.parent
    # The section owns the only two literal binary names; the Loom export's streaming Popen
    # keeps its `_run_export` docstring mention. Anything else naming a binary in a list
    # literal is a call site that skipped the seam.
    pat = re.compile(r"""\[\s*["'](ffmpeg|ffprobe)["']""")
    offenders = []
    for name in ("moonglade_backup.py", "moonglade_gallery.py"):
        src = io.open(repo / name, encoding="utf-8").read()
        for m in pat.finditer(src):
            offenders.append("{}:{}".format(name, src[:m.start()].count("\n") + 1))
    assert offenders == [], (
        "these lines build an ffmpeg/ffprobe command from a bare binary name instead of "
        "going through media_tools: {}".format(offenders))
