"""
moonglade/loom_files.py
=======================
The Loom's file-side helpers: the render-ids cache (`loom_render_ids`, which the catalog's
type: search and moonglade/health.py read), the music bed and EDL export constants and pure
helpers (`sniff_audio_ext`, `loom_edl_zip_stem`, the board-name salvage, `loom_board_beds`,
`loom_bed_windows`, `loom_bed_audio_graph`), the bundle's name patterns and caps, and the frame
ribbon's limits. The routes that use them are moonglade/routes_loom.py's and the store is
moonglade/web_loom_store.py. Moved verbatim out of moonglade/gallery.py in the 3.22 split
(phase 4).

It needs nothing from the gallery or the engine.
"""
import json
import os
import re

from moonglade import paths as _paths


_LOOM_IDS_CACHE = {}          # str(out_dir) -> (signature, frozenset of media ids)


def _loom_board_files(out_dir):
    """Every saved Loom board on disk: this install's per-account folders and the legacy shared
    layer, both under the Loom's kv/ (moonglade.paths.loom_root), keyed `storyboard:v2:proj:<id>` (the Loom's own PPRE) or the
    legacy single-project key. Read-only; a missing folder is simply no boards."""
    from urllib.parse import unquote
    kv = _paths.loom_root(out_dir) / "kv"
    out = []
    try:
        entries = list(kv.iterdir())
    except OSError:
        return out
    for p in entries:
        try:
            files = list(p.iterdir()) if p.is_dir() else [p]
        except OSError:
            continue
        for f in files:
            if f.suffix != ".json":
                continue
            key = unquote(f.stem)
            if key.startswith("storyboard:v2:proj:") or key == "storyboard:v2:project":
                out.append(f)
    return out


def loom_render_ids(out_dir):
    """The media ids the Loom rendered: every board's shot result and every re-roll attempt it
    kept, minus footage the owner imported into a shot (that is theirs, not a render). This is
    what "Loom renders" means in the Storage bars and `type:loom`.

    It reads the boards straight off disk -- nothing is written and no network is touched -- and
    remembers the answer until a board's file moves (path, mtime and size are the key), so a
    search that runs it per row costs one directory listing, not a re-parse."""
    files = _loom_board_files(out_dir)
    sig = []
    for f in files:
        try:
            st = f.stat()
            sig.append((str(f), st.st_mtime_ns, st.st_size))
        except OSError:
            continue
    sig = tuple(sorted(sig))
    hit = _LOOM_IDS_CACHE.get(str(out_dir))
    if hit and hit[0] == sig:
        return hit[1]
    ids = set()
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, str):            # the Loom stores a project as a JSON string
                data = json.loads(data)
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for act in data.get("acts") or []:
            for card in (act or {}).get("cards") or []:
                if not isinstance(card, dict) or card.get("imported"):
                    continue
                if card.get("resultMid"):
                    ids.add(str(card["resultMid"]))
                for a in card.get("attempts") or []:
                    if isinstance(a, dict) and a.get("media_id"):
                        ids.add(str(a["media_id"]))
    frozen = frozenset(ids)
    _LOOM_IDS_CACHE[str(out_dir)] = (sig, frozen)
    return frozen


# ---------------------------------------------------------------------------
# THE LOOM'S MUSIC BED AND EDL EXPORT (Session P, Stage B1: NOTES P3/P4; BUILD-w5-p §5.1/§5.5;
# rulings 6-8 and 15; review F18/F19/N2). Pure helpers here; the routes are in create_app.
#
# A bed is one local audio file per storyboard, stored content-addressed at
# out_dir/_moonglade/loom/_beds/<account key>/<sha1>.<ext> -- never uploaded, never sent to PixAI, and
# never deleted automatically (an explicit, confirmed sweep of beds no board of the account
# references is offered instead). Its name is the sha1 of its bytes, so a duplicated board
# shares it and an imported bundle's bed is RE-HASHED on arrival, never trusted by name.
# ---------------------------------------------------------------------------

LOOM_BED_MAX_BYTES = 50 * 1024 * 1024
# The multipart envelope around the file (boundaries, headers, the csrf and board fields). A
# request whose declared length is over the cap plus this is refused before a byte is read.
LOOM_BED_FORM_SLACK = 64 * 1024
LOOM_BED_FILE_RE = re.compile(r"^[0-9a-f]{40}\.(mp3|wav|m4a|aac|ogg|flac)$")
# A bundle import stores at most this many beds (the one its board names), each under the cap
# above -- so one import writes at most LOOM_BED_MAX_BYTES of beds (spend review S5).
LOOM_BUNDLE_MAX_BEDS = 1
LOOM_BED_MIMES = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4", "aac": "audio/aac",
                  "ogg": "audio/ogg", "flac": "audio/flac"}


# A bed added in the last few minutes may belong to a board whose save has not landed yet, so
# the unused list never offers it (the sweep re-checks the same rule).
LOOM_BED_UNUSED_GRACE_S = 10 * 60
# A bed upload's or a bundle import's temp file (.upload-*.part / .import-*.part) that a crash
# left in _beds/<account>/ is swept at the next start once it is this old (spend review N5):
# the unused-bed list and its sweep only ever see finished, content-hashed names.
LOOM_BED_TEMP_SWEEP_AGE_S = 3600
# THE EDL ZIP'S NAMES -- the same patterns as loom/src/loom-edl-core.js's EDL_CLIP_FILE_RE and
# EDL_BED_NAME_RE (dev/tests/test_loom_p_routes.py compares the two sources).
LOOM_EDL_CLIP_RE = re.compile(r"^[A-Za-z0-9]{1,8}_t\d{1,4}\.mp4$")
LOOM_EDL_BED_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.(mp3|wav|m4a|aac|ogg|flac)$")
LOOM_MEDIA_ID_RE = re.compile(r"^(\d+|local_[0-9a-f]{12})$")
# A bundle's media entry: exactly media/<id><picture or video extension>, nothing else; the id
# is letters, digits, '_' and '-' only (no separator, drive letter, colon or dot).
# The name inside a zip is the sender's to choose, so it is never trusted as a path: anything
# else (another extension such as .html/.svg, a separator, a drive letter, "..") is skipped
# unread (red team 2026-10-01). Each entry is copied under this cap.
LOOM_BUNDLE_MEDIA_RE = re.compile(
    r"^media/([A-Za-z0-9][A-Za-z0-9_-]{0,63})\.(png|jpg|jpeg|webp|gif|avif|mp4|webm|mov|mkv|m4v)$")
LOOM_BUNDLE_MEDIA_MAX_BYTES = 1024 * 1024 * 1024
LOOM_EDL_MAX_EDL_CHARS = 1024 * 1024
LOOM_EDL_MAX_CSV_CHARS = 4 * 1024 * 1024
LOOM_EDL_MAX_CLIPS = 2000
LOOM_EXPORT_SWEEP_AGE_S = 3600

# THE CONTINUITY RIBBON'S FRAMES (Session P, P9; review F18). GET /api/loom/frame extracts ONE
# small still from a local clip -- ffmpeg on this machine, never an upload, never PixAI -- and
# keeps it in out_dir/_moonglade/loom/_frames/ as <mid>_<frame>.png, the time quantised to a 24 fps frame
# so a trim dragged across a second makes at most 24 files, not one per float. The cache is
# capped by count and by bytes, least-recently-used first, swept on every write; only files of
# exactly this name shape are ever swept (the ✂ splice's own <mid>_last.png is not).
LOOM_FRAME_FPS = 24
LOOM_FRAME_WIDTH = 160
LOOM_FRAME_MAX_SECONDS = 6 * 3600
LOOM_FRAME_CACHE_MAX_FILES = 600
LOOM_FRAME_CACHE_MAX_BYTES = 64 * 1024 * 1024
# GitHub #62: a frame spliced before 3.15.0 has no thumbs/<id>.jpg. /api/loom/frame-thumbs fills
# one from PixAI once (a media read, then the picture from the image CDN), at most this many ids
# a request, one at a time with this pause between PixAI calls.
LOOM_FRAME_THUMBS_MAX = 60
LOOM_FRAME_THUMBS_PAUSE_S = 0.3
LOOM_FRAME_THUMB_ID_RE = re.compile(r"^\d{1,32}$")
# <mid>_<frame>.png, or <mid>_end.png: the clip's true last frame, asked for when a take's
# length was never recorded (GitHub #63). The splice's <mid>_last.png is NOT this shape.
LOOM_FRAME_FILE_RE = re.compile(r"^(\d+|local_[0-9a-f]{12})_(\d{1,7}|end)\.png$")

# The page's bed rules (loom/src/loom-bed-core.js holds the same numbers for Play).
LOOM_BED_FADE_IN = 2.0
LOOM_BED_FADE_OUT = 3.0
LOOM_BED_DUCK_DB = -12


def sniff_audio_ext(head):
    """The audio type of a file from its first bytes -- the magic, never the file name.
    mp3 (an ID3 tag or an MPEG layer I-III frame sync), wav (RIFF/WAVE), m4a (an ISO-BMFF
    ftyp box of an audio brand), aac (ADTS), ogg (OggS), flac (fLaC). None for anything else,
    a video mp4 included."""
    b = bytes(head or b"")
    if len(b) < 4:
        return None
    if b[:4] == b"fLaC":
        return "flac"
    if b[:4] == b"OggS":
        return "ogg"
    if b[:4] == b"RIFF" and b[8:12] == b"WAVE":
        return "wav"
    if b[:3] == b"ID3":
        return "mp3"
    if len(b) >= 12 and b[4:8] == b"ftyp":
        try:
            size = int.from_bytes(b[:4], "big")
        except ValueError:
            size = 0
        box = b[8:min(len(b), max(16, size))]
        brands = {box[i:i + 4] for i in range(0, len(box) - 3, 4)}
        if brands & {b"M4A ", b"M4B ", b"M4P ", b"F4A ", b"F4B "}:
            return "m4a"
        return None
    if b[0] == 0xFF and (b[1] & 0xF0) == 0xF0 and ((b[1] >> 1) & 3) == 0:
        return "aac"                        # ADTS: 12-bit sync, layer 00
    if b[0] == 0xFF and (b[1] & 0xE0) == 0xE0 and ((b[1] >> 1) & 3) in (1, 2, 3):
        return "mp3"                        # MPEG audio frame sync, layer I-III
    return None


def _unlink_quiet(path):
    """Remove a file if it is there; a missing file or a held handle is not an error (the
    export sweep collects what a Windows handle kept)."""
    try:
        os.unlink(str(path))
    except OSError:
        pass


def loom_edl_zip_stem(name):
    """The export's file stem: the board's name kept to [A-Za-z0-9 _.-], 64 characters at
    most, never empty and never starting with a dot (review F19: it goes into
    Content-Disposition and the zip's entry names)."""
    s = re.sub(r"[^A-Za-z0-9 _.-]", "", str(name or ""))[:64].strip().lstrip(".").strip()
    return s or "storyboard"


_LOOM_BOARD_NAME_RE = re.compile(r'\s*\{\s*"name"\s*:\s*"((?:[^"\\\x00-\x1f]|\\.){0,600})"')


def _json_string_body(text):
    """The text inside a JSON string literal that starts `text`, unescaped as far as it goes
    (a torn file simply stops). Lenient on purpose: it only ever feeds the name salvage."""
    out, i, n = [], 1, len(text)
    simple = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
    while i < n:
        ch = text[i]
        if ch == '"':
            break
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        if i + 1 >= n:
            break
        esc = text[i + 1]
        if esc == "u" and re.match(r"[0-9a-fA-F]{4}$", text[i + 2:i + 6]):
            out.append(chr(int(text[i + 2:i + 6], 16)))
            i += 6
            continue
        out.append(simple.get(esc, esc))
        i += 2
    return "".join(out)


def loom_board_name_salvage(text):
    """A board's name from a file that will not read (GitHub #57), or "" when it cannot be
    read. Best effort and nothing else: the name is the first field of every board, so only a
    `"name": "..."` that opens the board counts (an act's or a cast member's name is never
    taken for it). A board stored as a JSON string (the Loom's own saves) is unescaped first.
    At most 120 characters; never any other content of the board."""
    t = str(text or "").lstrip()
    if t.startswith('"'):
        t = _json_string_body(t)
    m = _LOOM_BOARD_NAME_RE.match(t)
    if not m:
        return ""
    try:
        name = json.loads('"' + m.group(1) + '"')
    except ValueError:
        return ""
    return name.strip()[:120]


def loom_board_beds(projects):
    """The bed files a list of parsed boards references (project.bed.file), valid names only."""
    out = set()
    for p in projects or []:
        bed = p.get("bed") if isinstance(p, dict) else None
        f = str((bed or {}).get("file") or "") if isinstance(bed, dict) else ""
        if LOOM_BED_FILE_RE.match(f):
            out.add(f)
    return out


def loom_bed_windows(spans, own_audio, bed_len=None):
    """Where the bed ducks: [(start, end)] in cut seconds, one per run of consecutive shots
    with their own audio, clipped to the bed's length. `spans` and `own_audio` are per
    segment, in cut order (the twin of loom-bed-core.js's bedPlan windows)."""
    out, at = [], 0.0
    for span, own in zip(spans or [], own_audio or []):
        a, b = at, at + max(0.0, float(span or 0))
        at = b
        if not own:
            continue
        if bed_len is not None:
            b = min(b, float(bed_len))
        if b <= a:
            continue
        if out and abs(out[-1][1] - a) < 1e-9:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def loom_bed_audio_graph(bed_idx, db, cut_len, bed_dur=None, windows=(), cut_label="acut",
                         out_label="aout"):
    """The ffmpeg filter text that mixes a music bed under the Loom's local cut (⇧ Render),
    by the page's rules -- the server's twin of loom-bed-core.js, which Play uses:
      level `db` (−24…0), −12 dB more inside each duck window, a 2 s in-fade and a 3 s
      out-fade, the bed cut to the cut (atrim) and ending with its out-fade there; a shorter
      bed ends where it ends, with its own out-fade, and never loops.
    `bed_idx` is the bed's ffmpeg input index. With `cut_label` (the concatenated shots'
    audio) the two are summed by amix without normalising, so the shots keep their level;
    with cut_label=None the bed IS the cut's audio track. Returns filter chains joined by ';'.
    Pure: dev/tests/test_loom_p_routes.py pins the text."""
    cut_len = max(0.0, float(cut_len or 0))
    try:
        bd = float(bed_dur) if bed_dur not in (None, "") else None
    except (TypeError, ValueError):
        bd = None
    bed_len = min(bd, cut_len) if bd and bd > 0 else cut_len
    try:
        level = int(round(float(db)))
    except (TypeError, ValueError):
        level = -8
    level = max(-24, min(0, level))
    fin = min(LOOM_BED_FADE_IN, bed_len / 2.0)
    fout = min(LOOM_BED_FADE_OUT, bed_len / 2.0)
    chain = ["atrim=end=%.3f" % bed_len, "asetpts=PTS-STARTPTS",
             "aformat=sample_rates=48000:channel_layouts=stereo", "volume=%ddB" % level]
    wins = [(a, min(b, bed_len)) for (a, b) in (windows or ()) if min(b, bed_len) > a]
    if wins:
        chain.append("volume=%ddB:enable='%s'" % (
            LOOM_BED_DUCK_DB, "+".join("between(t,%.3f,%.3f)" % (a, b) for (a, b) in wins)))
    chain.append("afade=t=in:st=0:d=%.3f" % fin)
    chain.append("afade=t=out:st=%.3f:d=%.3f" % (max(0.0, bed_len - fout), fout))
    if cut_label is None:
        return "[%d:a]%s[%s]" % (bed_idx, ",".join(chain), out_label)
    return ";".join([
        "[%d:a]%s[bed]" % (bed_idx, ",".join(chain)),
        "[%s]aformat=sample_rates=48000:channel_layouts=stereo[acutf]" % cut_label,
        "[acutf][bed]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[%s]" % out_label,
    ])
