"""
moonglade/media_tools.py
========================
The ONE ffmpeg / ffprobe seam: tool discovery, the no-window flag, the timeout policy,
ToolResult, the probes and frame grabs, the poster thumbnail and the faststart remux. Moved
verbatim out of moonglade/backup.py in the 3.21.0 split (phase 3).

The one name it reads from the engine (`vlog`) is imported from moonglade.backup inside each
function that uses it, at call time, so importing this module never imports the engine and a
test's patch of backup's binding still reaches it. The no-window flag comes from moonglade.deps,
which spells the same constant and imports only the standard library.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from moonglade.deps import _NO_WINDOW

# ===========================================================================
# media_tools -- the ONE ffmpeg / ffprobe seam
# ===========================================================================
# Every ffmpeg and ffprobe invocation in this app enters the OS through this
# section. Before it existed there were seven call sites across
# moonglade_backup.py and moonglade_gallery.py, and each one re-typed the same
# four things: an availability check, `creationflags=_NO_WINDOW`, a timeout, and
# a blanket `except`. They disagreed on all four. Two of them asked ffprobe the
# SAME question -- how long is this clip -- through different `-of` flags and
# answered differently (one rounded to 2dp, one did not), and were called
# crosswise from both modules. Two invoked the binary by bare name where the
# others used a which()-resolved path. One cached its which(), one re-ran it per
# file. video_poster_thumb's own comment had already banked the diagnosis: "two
# copies of this wheel WILL drift."
#
# What lives here, exactly once:
#
#   * availability -- ffmpeg_path() / ffprobe_path(), one cached probe each,
#     asked separately because they are separately installable.
#   * the flags -- NO_WINDOW, on every spawn.
#   * the timeouts -- the *_TIMEOUT constants below ARE the policy; a caller
#     naming its own number is how the old sites drifted 15 apart from 20.
#   * the failure rule -- a media tool NEVER raises at its caller and never
#     blocks the work it serves. run_ffmpeg/run_ffprobe answer with a
#     ToolResult, and every failure they swallow gets a vlog() line so a
#     degraded run is on record instead of silent.
#
# ToolResult.missing is the load-bearing part. "The binary is not installed" used
# to reach every caller as a FileNotFoundError caught by a blanket `except` that
# could not tell it apart from a corrupt file, so the difference between "there
# is no audio" and "I could not look" was lost at the seam. It is now a field.
# That is the mechanism under the standing rule that a missing ffprobe DEGRADES
# the Loom export and never blocks it: the export can ask which kind of nothing
# it got back.
#
# A nonzero returncode is deliberately NOT logged here and NOT a `missing`: it is
# ffmpeg's ordinary way of refusing a file, its meaning is caller-specific (the
# faststart remux reads its stderr and names the clip; a thumbnail just retries
# with different flags), and logging it here would double up on the caller's own,
# better message.
#
# The gallery reaches this section as `_media_tools.<name>` through a module-level
# `from moonglade import media_tools as _media_tools`: this module imports neither the
# gallery nor the engine at module scope, so there is no import cycle.

NO_WINDOW = _NO_WINDOW   # re-exported: no caller of this section reaches for the raw constant

# The timeout policy, in one place. Sized by what the invocation actually does,
# not by which module happens to be calling.
PROBE_TIMEOUT = 20         # ffprobe: a metadata read, no decoding
FRAME_TIMEOUT = 45         # one frame out of one clip
THUMB_TIMEOUT = 90         # the thumbnail filter scans a batch of opening frames
THUMB_RETRY_TIMEOUT = 60   # ...and the literal-first-frame retry behind it
REMUX_TIMEOUT = 300        # faststart: -c copy over the whole file


@dataclass(frozen=True)
class ToolResult:
    """What one ffmpeg/ffprobe invocation did. Never an exception.

    `ok`          -- the process ran and exited 0.
    `returncode`  -- its exit code, or None when no process completed at all
                     (binary absent, timed out, failed to spawn).
    `stdout`/`stderr` -- text, always captured. ffmpeg reports WHY it refused
                     something on stderr and nowhere else.
    `missing`     -- the binary is not installed. The degrade-never-block road:
                     a caller answers this differently from a real failure.
    """
    ok: bool
    returncode: object
    stdout: str
    stderr: str
    missing: bool


_TOOL_PATHS = {}


def _tool_path(name):
    """Resolved path to a media binary, or '' -- asked of the OS once per process.

    Cached because it is asked on per-file hot paths (every clip in a thumbnail
    sweep, every shot in an export) and a which() is a directory walk. The price is
    that installing ffmpeg while the app runs needs a restart to be noticed, which
    is the deal the old `_ffmpeg_path` already made; the gallery's uncached copies
    paid a which() per file for a refresh nobody was waiting on."""
    if name not in _TOOL_PATHS:
        import shutil
        _TOOL_PATHS[name] = shutil.which(name) or ""
    return _TOOL_PATHS[name]


def ffmpeg_path():
    """Path to ffmpeg, or '' when it is not installed (cached -- see _tool_path).

    Public because some callers must gate BEFORE building work: the faststart sweep
    prints one honest line instead of walking the library, and the Loom export
    refuses up front rather than assembling a filtergraph nothing can run."""
    return _tool_path("ffmpeg")


def ffprobe_path():
    """Path to ffprobe, or '' when it is not installed (cached -- see _tool_path).

    Asked SEPARATELY from ffmpeg_path() on purpose. They ship together in a full
    build but not in every package, and the machine with ffmpeg and no ffprobe is
    exactly the one the Loom export has to keep serving -- gating the two together
    would take a working feature away over a binary the wiki never asks for."""
    return _tool_path("ffprobe")


def _reset_tool_cache():
    """Forget the resolved binary paths. For tests that exercise the caching itself;
    production has no reason to re-ask."""
    _TOOL_PATHS.clear()


def _as_text(v):
    """Whatever a completed process handed back, as str. The one decode point."""
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


def _run_tool(name, path, args, timeout, input=None):
    """Spawn one media binary and answer with a ToolResult. Never raises.

    The single owner of the missing-binary road, `creationflags=NO_WINDOW`, the
    timeout, stream capture, decoding, and the vlog() line for every failure that
    used to disappear into a caller's blanket `except`."""
    from moonglade.backup import vlog
    import subprocess
    if not path:
        vlog("{} is not installed; skipping: {}".format(
            name, " ".join(str(a) for a in args[:4])))
        return ToolResult(ok=False, returncode=None, stdout="",
                          stderr="{} not found on PATH".format(name), missing=True)
    argv = [path] + [str(a) for a in args]
    try:
        # stdout/stderr are PIPEd explicitly rather than via capture_output=True:
        # ffmpeg's stderr is the entire diagnostic on a refusal, and with `-v error`
        # it prints nothing at all on success, so piping costs nothing on the happy
        # path. Decoding is pinned to utf-8/replace because the alternative -- the
        # platform locale with strict errors -- can raise out of a call whose whole
        # contract is that it does not.
        # stdin is DEVNULL whenever no input is given: a server launched detached on
        # Windows has no valid stdin handle to inherit, and the child then fails with
        # WinError 6 -- which this function swallows by contract, so frame_at returned
        # None and an export silently lost its audio (real-ffmpeg smoke test, 2026-09-29).
        stdin_kw = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
        r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, creationflags=NO_WINDOW, **stdin_kw)
    except FileNotFoundError as e:
        # which() said yes and the exec still failed: the binary moved, or a shim
        # points at nothing. Same road for the caller as never having had it.
        vlog("{} vanished between which() and exec: {}".format(name, e))
        return ToolResult(ok=False, returncode=None, stdout="", stderr=str(e), missing=True)
    except subprocess.TimeoutExpired:
        vlog("{} timed out after {}s: {}".format(name, timeout, " ".join(argv[1:5])))
        return ToolResult(ok=False, returncode=None, stdout="",
                          stderr="timed out after {}s".format(timeout), missing=False)
    except Exception as e:                       # noqa: BLE001 -- a media tool never raises at its caller
        vlog("{} failed to run: {}".format(name, e))
        return ToolResult(ok=False, returncode=None, stdout="", stderr=str(e), missing=False)
    return ToolResult(ok=(r.returncode == 0), returncode=r.returncode,
                      stdout=_as_text(r.stdout), stderr=_as_text(r.stderr), missing=False)


def run_ffmpeg(args, *, timeout, input=None):
    """Run ffmpeg with `args` -- everything AFTER the binary, which this supplies.
    Never raises; see ToolResult. `input` is stdin text for the rare filter that
    wants it (the streams are text-mode, so bytes are not accepted)."""
    return _run_tool("ffmpeg", ffmpeg_path(), args, timeout, input=input)


def run_ffprobe(args, *, timeout):
    """Run ffprobe with `args` -- everything AFTER the binary, which this supplies.
    Never raises; see ToolResult."""
    return _run_tool("ffprobe", ffprobe_path(), args, timeout)


def duration(path, *, timeout=None):
    """Real length of a clip in seconds, or None when it cannot be read.

    THE one answer to "how long is this file". There used to be two, asking ffprobe
    the same question through different flags: this module's `probe_video_duration`
    (`-of default=noprint_wrappers=1:nokey=1`, 20s, rounded to 2dp) and the
    gallery's `probe_duration` (`-of csv=p=0`, 15s, full precision), each called
    from both modules. Full precision wins, because rounding is a display choice and
    a measurement that has already been rounded cannot be un-rounded -- a caller that
    wants 2dp rounds at its own call site, where the reason it wants them is visible.
    """
    r = run_ffprobe(["-v", "error", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(path)],
                    timeout=PROBE_TIMEOUT if timeout is None else timeout)
    if not r.ok:
        return None
    try:
        return float(r.stdout.strip())
    except (TypeError, ValueError):
        return None


def has_audio(path, *, timeout=None):
    """True/False for "does this file carry at least one audio stream", and None
    when ffprobe could not answer at all.

    The three-way answer is the whole point. "Definitely silent" and "I could not
    look" are different facts, and collapsing them is how a machine without ffprobe
    came to read every clip as silent with nothing able to notice. A caller that
    only needs the safe reading -- treat unknown as silent -- coerces with bool(),
    in one place, on purpose."""
    r = run_ffprobe(["-v", "error", "-select_streams", "a", "-show_entries",
                     "stream=index", "-of", "csv=p=0", str(path)],
                    timeout=PROBE_TIMEOUT if timeout is None else timeout)
    if not r.ok:
        return None
    return bool(r.stdout.strip())


def frame_seek_point(at_seconds, dur):
    """Where a trim-aware frame grab lands on a clip `dur` seconds long: `at_seconds` itself
    when it is inside the clip, else None -- the clip's LAST frame (no time asked, a time
    at/after the real end, or a length that could not be measured). The one rule, read by
    extract_last_frame and by /api/loom/handoff, which reports back where the frame it
    uploaded came from (the Loom's anchor records that time; owner walk 2026-09-30)."""
    if at_seconds is None:
        return None
    if not (dur and at_seconds < dur - 0.05):
        return None
    return at_seconds


def extract_last_frame(video_path, out_png, at_seconds=None, *, trim_aware=True):
    """Grab a clip's frame to out_png via ffmpeg. This is the frame-handoff primitive:
    one shot's last frame becomes the next shot's opening frame, so a sequence reads as
    one continuous scene.

    `at_seconds` makes the handoff TRIM-AWARE: the previous shot's trimOut is the point
    the cut actually ends on, so the handed-off frame must be the frame AT that out-point,
    not the untrimmed clip's real final frame. When it's None (no trim) -- or past the
    clip's real end -- decode the clip's last half second and keep the final frame decoded
    (`-update 1` with no frame cap overwrites out_png per frame). A clip shorter than that
    is decoded whole, so it still yields its LAST frame; the old fixed "-sseof -0.15
    -frames:v 1" clamped to the start on such a clip and handed back the FIRST.
    Returns out_png or None.

    It is also GENERAL: `at_seconds=0.0` takes the explicit-seek branch and yields the
    FIRST frame. Nothing in this app should write a second frame extractor; `frame_at`
    below is this function under the module's argument order, not another copy of it.

    `trim_aware=False` skips the duration measurement and seeks to `at_seconds` as given
    -- for a caller that already knows its timestamp is inside the clip."""
    import os
    if at_seconds is not None and trim_aware:
        # a trimOut at/after the real end is just "the last frame" -> use the EOF path
        at_seconds = frame_seek_point(at_seconds, duration(video_path))
    try:
        if at_seconds is None:
            seek = ["-sseof", "-0.5", "-i", str(video_path)]
            take = ["-update", "1"]
        else:
            # -ss before -i (fast, keyframe-accurate enough for a still); back off a hair
            # so we land ON the last kept frame, not the first discarded one.
            seek = ["-ss", "{:.3f}".format(max(0.0, float(at_seconds) - 0.05)), "-i", str(video_path)]
            take = ["-update", "1", "-frames:v", "1"]
    except (TypeError, ValueError):
        return None
    r = run_ffmpeg(["-y"] + seek + take + ["-q:v", "2", str(out_png)],
                   timeout=FRAME_TIMEOUT)
    if not r.ok:
        return None
    try:
        return str(out_png) if os.path.exists(out_png) and os.path.getsize(out_png) > 0 else None
    except OSError:
        return None


def frame_at(path, t, out, *, trim_aware=True):
    """Write the frame at `t` seconds of `path` to `out`; `t=None` means the clip's
    last frame, `t=0.0` its first. Returns `out` or None.

    The module-interface face of extract_last_frame, which stays THE frame primitive
    and keeps its name because the rest of the app and the decision record both call
    it that. This is a signature, not a second implementation."""
    return extract_last_frame(path, out, at_seconds=t, trim_aware=trim_aware)


# --- end media_tools -------------------------------------------------------


def video_poster_thumb(video_path, thumb_path):
    """Extract a frame of a video via ffmpeg and write it as the gallery thumbnail.
    OPTIONAL: returns False (no-op) if ffmpeg isn't on PATH, so videos just fall
    back to the placeholder + play badge. Used for imported videos and as a
    fallback for i2v videos with no still-frame poster.

    Thin delegate: the ONE ffmpeg-extract implementation lives in
    moonglade.gallery.make_video_thumbnail (which build_thumbnails' poster-less
    fallback also uses) -- two copies of this wheel WILL drift. The availability
    guard stays here because import-local and sync-videos gate on it."""
    if not ffmpeg_path():
        return False
    from moonglade.thumbs import make_video_thumbnail
    return make_video_thumbnail(video_path, thumb_path)


def _mp4_is_faststart(path):
    """True if an mp4's `moov` atom precedes `mdat` — i.e. iOS/Safari can stream it
    progressively over HTTP. Best-effort top-level box scan; returns True on any parse
    trouble so we never remux a file we can't read."""
    import struct
    order = []
    try:
        with open(path, "rb") as f:
            while len(order) < 12:
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                size = struct.unpack(">I", hdr[:4])[0]
                order.append(hdr[4:8].decode("latin1", "replace"))
                if size == 1:                       # 64-bit extended size
                    size = struct.unpack(">Q", f.read(8))[0]; f.seek(size - 16, 1)
                elif size == 0:                     # extends to EOF
                    break
                else:
                    f.seek(size - 8, 1)
                if "moov" in order and "mdat" in order:
                    break
    except (OSError, struct.error, ValueError):
        return True
    if "moov" not in order:
        return True
    di = order.index("mdat") if "mdat" in order else 10 ** 9
    return order.index("moov") < di


# What a faststart attempt actually DID. Three outcomes, because two are not enough: a bool
# collapses "I tried and ffmpeg refused" into the same False as "there was nothing to do",
# and a sweep that treats that union as failure reports a healthy file as broken. The
# concurrency that makes them collide is BLESSED by the docs -- wiki/Backing-Up.md says
# --faststart-videos is safe to run while the gallery or a live watch is collecting, and the
# live mirror remuxes the same clips -- so between one caller's "not faststart" check and the
# next line of code the file can legitimately already be fixed, or gone from Trash entirely
# (M04 round 2, 2026-07-27).
FASTSTART_REWROTE = "rewrote"        # the file was not faststart and now is
FASTSTART_NOT_NEEDED = "not-needed"  # nothing to do: already faststart, vanished, not a video
FASTSTART_REFUSED = "refused"        # ffmpeg (or the swap) tried and failed -- a REAL failure


def _video_faststart_attempt(path):
    """The remux, reporting WHICH of the three FASTSTART_* outcomes happened.

    `video_faststart` below is the bool face of this, kept because almost every caller only
    wants "did the file change" -- see its docstring for the mechanism and the unique-temp
    rationale. Only run_faststart_videos, which has to account for every clip it walked and
    name the ones still broken, needs the third answer."""
    from moonglade.backup import vlog
    p = Path(path)
    if p.suffix.lower() not in (".mp4", ".mov", ".m4v"):
        return FASTSTART_NOT_NEEDED
    ff = ffmpeg_path()
    if not ff or not p.exists() or _mp4_is_faststart(p):
        # Deliberately NOT a refusal. This is the branch a concurrent collector's remux (or a
        # Trash purge) lands in when it wins the race with a sweep that had already decided
        # this file needed work; calling it a failure prints "still not iOS-playable" about a
        # file that is now perfectly playable.
        return FASTSTART_NOT_NEEDED
    from uuid import uuid4
    # unique per call; the real ext stays LAST so ffmpeg still picks the muxer by extension
    tmp = p.with_name(p.stem + ".__fstmp__" + uuid4().hex[:8] + p.suffix)
    try:
        # Through media_tools: the binary, the no-window flag, the timeout and the "never
        # raises" rule all come from there. stderr arrives CAPTURED because run_ffmpeg pipes
        # it always -- ffmpeg reports why it refused a remux there and nowhere else, and with
        # -v error it prints nothing at all on success.
        r = run_ffmpeg(["-y", "-v", "error", "-i", str(p),
                        "-c", "copy", "-movflags", "+faststart", str(tmp)],
                       timeout=REMUX_TIMEOUT)
        if r.ok and tmp.exists() and tmp.stat().st_size > 0:
            os.replace(str(tmp), str(p))            # atomic swap
            return FASTSTART_REWROTE
        # A non-zero returncode raises NOTHING -- it is ffmpeg's ordinary way of refusing a
        # file (a stream anomaly `-c copy` won't carry, say), which is why media_tools hands
        # it back rather than logging it: the message worth printing is this one, naming the
        # clip. This branch used to fall straight through to the cleanup below, so the one
        # genuinely COMMON failure mode was the one that produced no message even under -v --
        # flatly contradicting the comment in the except clause below (M04, 2026-07-27).
        # Report the code and ffmpeg's own reason, since "it didn't work" without either is
        # not something a user can act on.
        why = " ".join((r.stderr or "").split())[:400] or (
            "no stderr; wrote no usable temp file" if r.ok else "no stderr")
        vlog("faststart remux failed for {}: ffmpeg exit {} -- {}".format(
            p.name, r.returncode, why))
    except Exception as e:                          # noqa: BLE001 -- remux must never crash a collect
        # swallowed by design (a failed remux leaves the original playable), but never
        # silently: a lost race or an odd ffmpeg failure must at least show under -v.
        vlog("faststart remux failed for {}: {}".format(p.name, e))
    try:
        if tmp.exists():
            tmp.unlink()   # the temp is unique to THIS call, so this only ever cleans our own leftover
    except OSError:
        pass
    if not p.exists():
        # The SOURCE went away while ffmpeg was reading it -- a Trash purge from the gallery,
        # or an --organize move, both of which the docs say may run alongside this. ffmpeg
        # failing to open a file that no longer exists is not a refusal, and reporting it as
        # one names a file the user cannot go and look at. Checked here rather than up front
        # because this is the only window the earlier `p.exists()` cannot cover.
        return FASTSTART_NOT_NEEDED
    return FASTSTART_REFUSED


def video_faststart(path):
    """Losslessly move an mp4's `moov` atom to the front (ffmpeg -c copy -movflags
    +faststart) so iOS/Safari will play it over HTTP -- PixAI serves videos with moov at
    the END, which desktop tolerates but iOS refuses (MediaError 4). No re-encode, no
    quality loss. Returns True only when it rewrote the file; no-op (False) if ffmpeg is
    absent, the file is already faststart, or the remux fails (original left untouched).

    A caller that has to tell a refusal apart from a no-op wants `_video_faststart_attempt`,
    which this wraps -- False here is deliberately the union of both, and the collect-time
    callers (which just want the file made streamable if it can be) do not care which.

    The temp name is UNIQUE per invocation (uuid suffix), never derived from the
    filename alone. Two collectors can legitimately remux the same clip seconds apart
    (the gallery's live-mirror watcher and a /api/task-status done-poll both collect a
    finished task, and the CLI's --watch-backup is a whole separate process), and with
    a deterministic temp name their two concurrent ffmpeg runs interleaved writes into
    the SAME temp file: the survivor was a full-length mp4 carrying the other run's
    stale pre-shift bytes exactly one moov-size offset out of place -- it played fine
    and then stopped mid-way. With unique temps any overlap is safe: each remux is
    complete and self-contained, and whichever os.replace lands last wins with a
    COMPLETE file either way."""
    return _video_faststart_attempt(path) == FASTSTART_REWROTE
