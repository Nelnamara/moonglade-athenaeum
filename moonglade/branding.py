"""
moonglade/branding.py
=====================
Branding: the art tree and the sealed pack it reads (branding_root, the role paths, the pack
cache and its readers, the moment clips), the marks and the masked-feat card, the banner and
role slots with their upload rules, the discovery tree and the dropped-art sweep, the banner
flats, the settings.json branding block, and the launcher shortcut and pack file type. Moved
verbatim out of moonglade/gallery.py in the 3.21.0 split (phase 3). (moonglade/container.py is
the pack FORMAT; this module is what the app does with the pack.)

It reaches achievements and telemetry as `_achievements.X` / `_telemetry.X`, the way the
gallery did once they moved out; both import this module only inside functions, so there is no
import cycle. It needs nothing else from the gallery.
"""
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import sys
import threading
import time
from pathlib import Path

try:
    from flask import request
except ImportError:
    sys.exit("Flask is required for the gallery server.\n"
             "Install it with:  pip install flask")

from moonglade import achievements as _achievements
from moonglade import container as moonglade_container
from moonglade import paths as _paths
from moonglade import scan as _scan
from moonglade import settings as _settings
from moonglade import telemetry as _telemetry

# ---------------------------------------------------------------------------
# Branding: the banner mark (the animated icon beside the title) is one of the
# owner's own cut marks in the art tree's marks/ (branding_root()), chosen + animated from the
# Control Panel. settings.json's branding = {"mark": "mark_4", "animation": {"anim": "classic", ...}}.
# The favicon is a plain file (served at /branding/favicon.png); the double-click launcher
# icon is a Desktop .lnk whose icon we point at a mark's .ico (a .pyw can't
# carry its own icon -- the shortcut can).

# The mark animation roster, settled by the two-round marks workshop (2026-08-31).
# The survivors keep their ORIGINAL ids on purpose -- "classic" is the modernized
# classic, not a new id -- so an install that already stored a pick keeps wearing the
# treatment it chose, now rebuilt. moondust is the promoted canvas demo.
# "sheen" split out of classic 2026-09-04 (owner: "star and glint should be
# separate. the star was the OG classic") -- classic is the star alone; sheen is
# the vanilla interface's selectable glass sweep, masked to the mark's silhouette.
MARK_ANIMS = ["classic", "sheen", "glow", "shine", "aurora", "twinkle", "shoot",
              "eclipse", "mist", "prism", "moondust", "none"]
# Retired by the same workshop. A stored pick of one of these is NOT an error: it
# renders as classic (load_branding's own validation does that), the picker stops
# offering it, and nothing has to migrate settings.json's branding.
MARK_ANIMS_RETIRED = ("halo", "breathe", "tilt", "float", "orbit", "ripple")

# The owner-tunable animation settings the workshop asked for ("There should be a
# speed and size slider setting for animations") plus glow's own colour/direction
# pair. Numbers are clamped to these ranges server-side; the client's sliders use
# the same bounds, but the server is the one that decides.
_BRAND_NUM_RANGES = {"anim_speed": (0.25, 3.0), "anim_scale": (0.5, 2.0),
                     "glow_angle": (0.0, 360.0)}
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_BRAND_DEFAULTS = {"mark": "mark_4", "anim": "classic",
                   # 1.0 = the treatments' authored tempo. The workshop board
                   # exported at 0.80x, but that was the owner auditioning the
                   # slider, not a ruling on the default -- so the shipped default
                   # stays the authored speed until he says otherwise.
                   "anim_speed": 1.0, "anim_scale": 1.0,
                   "glow_color": "#94e2d5", "glow_angle": 0.0}


def _brand_num(key, value, fallback):
    """One branding number, coerced and CLAMPED to its own range. A junk value
    falls back rather than raising: branding is cosmetic and must never be the
    reason a page fails to render."""
    lo, hi = _BRAND_NUM_RANGES[key]
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return fallback


def _brand_color(value, fallback):
    """A #rrggbb colour, or the fallback. Deliberately strict: this string is
    interpolated into a CSS custom property, so anything that is not exactly a
    six-digit hex colour never reaches the stylesheet."""
    s = str(value or "").strip()
    return s if _HEX_COLOR_RE.match(s) else fallback


def branding_root():
    """Where branding lives: the APP folder, beside the launcher -- NOT inside the library.

    Moved 2026-07-26 (owner decision) for two reasons, the first of which was a live bug.

    It used to be `Path(out_dir) / "branding"`, and out_dir comes from resolve_library_dir(), so
    the library-folder setting shipped the day before silently relocated it. Point the app at a
    different library and every mark, mascot and banner disappeared from its view -- the files
    still on disk in the old folder, the app just no longer looking there. Nobody hit it because
    only one library has ever existed.

    And the slot folders are meant to be VISIBLE: they sit beside the launcher, in the same
    folder the user already opens to start the app, rather than inside a picture library full of
    month folders and thumbnail caches nobody browses by hand. Deliberately NOT inside the
    /moonglade package that the naming pass will create either -- that is for code, and user art
    in a package boundary gets treated as code by something eventually.

    Every caller goes through here. Nine sites used to derive this path independently, which is
    exactly how the out_dir coupling above went unnoticed.

    Renamed to the coded goods root 2026-08-21 (the bundle-v2 rewire,
    SCOPE_bundle-v2-contract.md): the on-disk tree is coded end
    to end -- role names never appear as folder names -- while the browser keeps
    requesting the friendly /branding/<role>/... URLs and the serve route
    translates once at the boundary (_public_rel_to_coded below).

    The path itself is moonglade.paths.art_root(), the one place app-root paths are derived.
    The machine files that used to be this folder's siblings by derivation (the pack, the
    branding picks, the icons) live in local/ instead (moonglade.paths, moonglade.settings),
    so the art tree and they can move separately."""
    return _paths.art_root()


# ---------------------------------------------------------------------------
# The role -> coded-folder map (bundle-v2, 2026-08-21). Codes exist ONLY on
# disk and inside the art pack; the public URL contract stays /branding/
# <role>/... and every emitted URL keeps the role vocabulary. This dict is the
# SINGLE source of truth for the coded tree -- _seal_rule, the resolver
# callers, the discovery scaffold and the migration all DERIVE their paths
# from it, never retype them (a retyped prefix is how a seal silently fails
# open). `_thumbs` is a LEGACY literal: the badge-thumb cache now lives OUTSIDE
# the tree (badge_cache_dir(): local/cache/badges/); the _thumbs/ seal
# deny + the builder's exclusion stay as belt-and-braces for a stale cache left
# behind by an older build -- never coded, never packed, never served.
# ---------------------------------------------------------------------------
_GOODS_ROOT_NAME = _paths.GOODS_ROOT_NAME  # hex "goods" -- the on-disk branding root folder name
_GOODS_MID = "3f/00100100"             # 0x3F "?" / Bender's apartment -- shared middle
# The pre-2026-08-21 badge-thumb cache folder, as a path SEGMENT at any depth --
# the same shape dev/tools/build_container.py's EXCLUDED_DIRS uses, and the reason
# the container can never name one of these files. Read by the seal (deny).
# An install that upgraded through that move still carries a folder of
# app-rendered PNGs inside the tree; nothing here has to special-case them any
# more, because a snapshot taken before anyone looked already holds them
# (_branding_tree_has_new_art).
_LEGACY_THUMB_DIR = "_thumbs"

ROLE_CODE = {
    # role            -> coded folder rel-from-root (POSIX, no trailing slash)
    "banner_main":    _GOODS_MID + "/001",
    "banner_login":   _GOODS_MID + "/009",
    "banner_loom":    _GOODS_MID + "/019",
    "mystery":        _GOODS_MID + "/01473",
    "marks":          _GOODS_MID + "/101",
    "rewards":        _GOODS_MID + "/109",
    "system":         _GOODS_MID + "/5S5",
    "bridge":         _GOODS_MID + "/0xB01",
    "enhance":        _GOODS_MID + "/0xB01/0x534958",
    "emotion":        _GOODS_MID + "/0xB01/0x656d6f7465",
    "badges":         _GOODS_MID + "/A01",
    "mascots":        _GOODS_MID + "/A02",
    "mascots_ach":    _GOODS_MID + "/A02/ach",
    "earned_banners": _GOODS_MID + "/B0N",
    # Basic training's goal pictures (pack v7): /branding/training/goal_<goal>.png, the
    # address gallery/src/lib/goalTileCore.js asks before the bundle's own copy. Open chrome.
    "training":       _GOODS_MID + "/0x747261696e",
    "starfall":       "ABBA/a2c/0x53746172",
    "breadcrumb":     "ABBA/a2c/0x53746172/GONK",
    # A sibling of starfall, NOT nested under it: starfall's seal is a prefix
    # rule gated on a different feat, so a folder inside it would inherit the
    # wrong gate.
    "keyturn":        "ABBA/a2c/0x4B6579",
}

# The bespoke moments' clips: {moment flag: the clip's PUBLIC /branding/ name}.
# Neutral names on purpose -- the URL is visible in the network tab, so it names
# the moment, never the feat. The starfall clip rides translation rule 3 into the
# starfall bucket like the rest of its set; the keyturn clip has its own rule
# (2b) ahead of that one, into its own bucket.
_MOMENT_CLIPS = {
    "starfall": "ee_starfall_clip.mp4",
    "keyturn":  "ee_keyturn_clip.mp4",
}
# Rule 2b: a bare public clip name routed to a bucket OTHER than starfall's.
_MOMENT_CLIP_ROLES = {"ee_keyturn_clip.mp4": "keyturn"}


def _role_rel(role, *tail):
    """posix rel-from-root for a role file: _role_rel('marks','marks.json') ->
    '3f/00100100/101/marks.json'. No tail -> the role folder's own rel."""
    return "/".join((ROLE_CODE[role],) + tail)


def _role_dir(role):
    """Path: branding_root() / coded role folder."""
    return branding_root() / ROLE_CODE[role]


# The top-level system files rule 2 of the translation maps into the system
# role -- the app's chrome, requested by bare public name since before the
# coded tree existed.
_SYSTEM_TOP_FILES = frozenset({"logo.png", "favicon.png", "favicon.ico",
                               "nel_spinner.png", "login_nel.webp", "login_nel.png"})


def _public_rel_to_coded(rel):
    """Translate ONE incoming public /branding/ rel to its coded on-disk /
    container rel. Applied exactly once, at the serve boundary (the
    /branding/<path:fname> route); everything downstream -- seal, loose file,
    container key -- operates on the CODED rel only, so loose disk path ==
    container key always. First matching rule wins; the order is the contract
    (SCOPE_bundle-v2-contract.md section 2):

      1. the three banner flats -- bare names, returned as-is. Translation is a
         no-op for them BECAUSE they are not coded-tree assets at all: the
         rendered flat lives in the app cache (banner_cache_dir()) and its
         shipped-default fallback lives in the slot's coded folder. Both of
         those are SERVING rules the route applies after translation; the coded
         root itself is never read for a flat.
      2. top-level system files -> system/<name>
     2b. a bare moment clip that is not starfall's (_MOMENT_CLIP_ROLES) ->
         its own role. MUST precede rule 3: the clip's name is also a bare
         ee_*, and rule 3 would file it under the starfall bucket's seal
      3. bare ee_* filenames -> starfall/<name>
      4. bridge/emotion/<f> -> emotion ; bridge/preset_<f> -> enhance ;
         bridge/<f> -> bridge (the SIX subfolder holds the presets on disk,
         but the front-end asks for them flat under bridge/ -- filename rule)
      5. mascots/ach/<f> -> mascots_ach ; mascots/<f> -> mascots
      6. the single-segment role prefixes -> their coded folder + remainder
      7. _thumbs/<f>, sfx/<f> (no shipped sfx role -- absent -> 404 -> the
         synth-chime fallback) and anything unmatched: returned as-is. A probe
         that guesses a coded path lands here unchanged, so the seal still
         judges it."""
    if rel in _BANNER_FLAT.values():                              # rule 1
        return rel
    if rel in _SYSTEM_TOP_FILES:                                  # rule 2
        return _role_rel("system", rel)
    if rel in _MOMENT_CLIP_ROLES:                                 # rule 2b
        return _role_rel(_MOMENT_CLIP_ROLES[rel], rel)
    if "/" not in rel and rel.startswith("ee_"):                  # rule 3
        return _role_rel("starfall", rel)
    if rel.startswith("bridge/"):                                 # rule 4
        f = rel[len("bridge/"):]
        if f.startswith("emotion/"):
            return _role_rel("emotion", f[len("emotion/"):])
        if f.startswith("preset_"):
            return _role_rel("enhance", f)
        return _role_rel("bridge", f)
    if rel.startswith("mascots/"):                                # rule 5
        f = rel[len("mascots/"):]
        if f[:4].lower() == "ach/":   # case-insensitive: the seal is too (Windows FS)
            return _role_rel("mascots_ach", f[4:])
        return _role_rel("mascots", f)
    for role in ("marks", "badges", "rewards", "mystery", "banner_main",
                 "banner_login", "banner_loom", "earned_banners",
                 "training"):                                     # rule 6
        if rel.startswith(role + "/"):
            return _role_rel(role, rel[len(role) + 1:])
    return rel                                                    # rule 7


# ---------------------------------------------------------------------------
# The asset container -- loose-then-container resolution (2026-08-10,
# moonglade-internal/DECISIONS.md "The asset container, re-scoped from scratch").
#
# moonglade.mgpack, the art pack (moonglade/container.py's custom format; built by
# dev/tools/build_container.py, delivered as a GitHub Release asset, never
# committed) carries the app's DEFAULT branding so a fresh install is fully
# dressed while branding/ itself stays empty -- that emptiness is a shipped
# mechanic, not a gap. Resolution order everywhere below: a real loose file
# under branding/ ALWAYS wins; the container only answers when no loose file
# exists.
#
# The coded tree's read-only scan (_branding_tree_has_new_art, and so both
# sweep_branding_drops and sweep_telemetry) does NOT consult the container in
# either direction, and that is a correctness requirement rather than a
# convention. Asking "does the pack ship this?" as a POSITIVE would make an
# untouched default install look customized. Asking it as a NEGATIVE, to
# dismiss a candidate, fails OPEN on an install that has no pack at all (a
# legacy tree's art left loose then counts for everyone who upgrades) and fails
# CLOSED on the owner's own loose-wins override (his bytes under a shipped
# asset's filename are still "shipped"). The scan compares against a BASELINE of
# what was already on disk instead -- one snapshot per library-and-app-folder
# pairing, since the snapshot is stored in the library and the tree is not
# (_baseline_key) -- a question that is answerable identically with a pack and
# without one. See _branding_tree_has_new_art.
# ---------------------------------------------------------------------------
def _container_path():
    """THE path of the art pack, `moonglade.mgpack` (pack v7; `.mgpack` so Explorer can give it
    a type of its own): local/moonglade.mgpack (moonglade.paths.local_path()), not the art
    tree's parent. Every code path that reads, fetches, checks or builds the pack asks this;
    its `.version` marker is derived from it (moonglade.assets._version_marker_path). The
    pack's pre-v7 name is read only by the one-time rename the move runs
    (moonglade.assets.migrate_legacy_name, from moonglade.migrate)."""
    return _paths.local_path(_paths.PACK_NAME)


_container_cache = {"path": None, "mtime": None, "box": None}
_container_lock = threading.Lock()


def _get_container():
    """The current container read handle, or None if no (valid) art pack
    exists. Cached per (path, mtime) so the TOC parses once, and re-opened
    automatically when the file is replaced -- the downloader's atomic swap and
    a hand-copied update both just work on the next request."""
    p = _container_path()
    try:
        mtime = p.stat().st_mtime
    except OSError:
        with _container_lock:
            _container_cache.update(path=None, mtime=None, box=None)
        return None
    with _container_lock:
        if _container_cache["path"] == p and _container_cache["mtime"] == mtime:
            return _container_cache["box"]
        box = moonglade_container.open_container(p)
        _container_cache.update(path=p, mtime=mtime, box=box)
        return box


def _branding_bytes(rel):
    """One branding asset's bytes by branding_root()-relative posix path --
    loose file first, container second, None if neither has it."""
    loose = branding_root() / rel
    try:
        if loose.is_file():
            return loose.read_bytes()
    except OSError:
        pass
    box = _get_container()
    return box.get(rel) if box else None


def _branding_exists(rel):
    loose = branding_root() / rel
    try:
        if loose.is_file():
            return True
    except OSError:
        pass
    box = _get_container()
    return bool(box and box.has(rel))


def _branding_mtime(rel):
    """Freshness stamp for cache-invalidation: the loose file's own mtime when
    it exists, else the container FILE's mtime (a whole-container rebuild is the
    only way container-sourced content changes)."""
    loose = branding_root() / rel
    try:
        if loose.is_file():
            return loose.stat().st_mtime
    except OSError:
        pass
    try:
        return _container_path().stat().st_mtime
    except OSError:
        return None


# ---------------------------------------------------------------------------
# HTTP Range for CONTAINER-sourced branding assets (pack v5). A <video> seeks by
# asking for byte ranges, and the container used to answer every request with the
# whole body. Loose files never needed this: send_from_directory already ranges.
#
# A range is SLICED from bytes that were read and SHA-verified whole, never
# decoded mid-blob on the fly: Container.get() is the one place that checks an
# asset against its TOC digest, so a slice of a verified copy is the only slice
# that is known good. For the moments' clips -- the assets a browser actually
# ranges, fifty requests to a seek -- the verified copy is kept in a small
# in-memory cache keyed on the TOC digest (content, not path: a replaced pack
# that carries the same clip reuses it, a changed clip is a different key). It
# holds at most one entry per moment, least-recently-used out first.
# ---------------------------------------------------------------------------
_moment_clip_cache = {}            # toc sha256 -> verified bytes (insertion = LRU order)
_moment_clip_cache_lock = threading.Lock()


def _moment_clip_rels():
    """The CODED rels of the moments' clips -- the only assets the cache admits."""
    return frozenset(_public_rel_to_coded(n) for n in _MOMENT_CLIPS.values())


def _container_clip_bytes(rel):
    """One moment clip's bytes from the container, read and verified ONCE per
    content digest and served from memory after that. None when the container is
    absent or does not carry it, or the blob fails its checksum (never cached)."""
    box = _get_container()
    sha = box.sha256(rel) if box is not None else None
    if not sha:
        return None
    with _moment_clip_cache_lock:
        raw = _moment_clip_cache.pop(sha, None)
        if raw is not None:
            _moment_clip_cache[sha] = raw          # re-insert: most recently used
            return raw
    raw = box.get(rel)                             # whole blob, sha-verified
    if raw is None:
        return None
    with _moment_clip_cache_lock:
        _moment_clip_cache.pop(sha, None)
        _moment_clip_cache[sha] = raw
        while len(_moment_clip_cache) > max(1, len(_MOMENT_CLIPS)):
            _moment_clip_cache.pop(next(iter(_moment_clip_cache)))
    return raw


def _ranged_bytes_response(response_class, raw, mime):
    """A 200 / 206 / 416 for an in-memory body, per the request's Range header.

    One satisfiable byte range -> 206 with Content-Range; `bytes=0-1`, a suffix
    (`bytes=-500`, clamped to the whole body when longer than it) and an open end
    (`bytes=100-`) all land here. A range that starts at or past the end -> 416
    with `Content-Range: bytes */<length>`. A header this does not understand --
    another unit, a malformed spec, several ranges, or an If-Range (these
    responses carry no validator it could match) -- is IGNORED and the whole body
    goes out as 200, which is what RFC 9110 permits a server to do. Accept-Ranges
    is advertised either way so the client knows it may seek."""
    from werkzeug.http import parse_range_header
    n = len(raw)
    resp = None
    header = request.headers.get("Range")
    if header and request.method in ("GET", "HEAD") and "If-Range" not in request.headers:
        rng = parse_range_header(header)
        if rng is not None and rng.units == "bytes" and len(rng.ranges) == 1:
            start, stop = rng.ranges[0]            # stop exclusive, None = to the end
            if start < 0:                          # suffix: the last -start bytes
                start, stop = max(n + start, 0), n
            else:
                stop = n if stop is None else min(stop, n)
            if start >= n:
                resp = response_class(b"", status=416)
                resp.headers["Content-Range"] = "bytes */%d" % n
            else:
                resp = response_class(raw[start:stop], status=206, mimetype=mime)
                resp.headers["Content-Range"] = "bytes %d-%d/%d" % (start, stop - 1, n)
    if resp is None:
        resp = response_class(raw, mimetype=mime)
    resp.headers["Accept-Ranges"] = "bytes"
    resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


# ---------------------------------------------------------------------------
# The bundle's unlock split, ENFORCED at the serving layer (moonglade-internal/DECISIONS.md
# "The bundle's unlock split" 2026-07-27 + the "Mascots-in-Branding" correction
# 2026-08-06): achievement-bound art -- badge masters, the per-achievement
# mascot poses under mascots/ach/, the rewards/ tree, the easter-egg ee_* assets --
# is sealed to the achievement that earns it. System chrome (narrator, login
# companion, wizard poses, tracker spinner/status art, present_* fallbacks)
# stays open: it is the app's default dress, not a reward. Deny answers are
# 404, indistinguishable from "no such file", so the route is not an oracle
# for what art exists.
# ---------------------------------------------------------------------------
# Earned-art gate ids come from the SEALED roster via _ach_ids()/_ach_hidden() (below),
# not a module-level frozenset -- the roster is no longer in this source.


def _seal_rule(rel):
    """(mode, achievement_id) for one branding_root()-relative posix path:
    'open' (serve normally), 'deny' (never serve), or 'earned' (serve only once
    the named achievement is earned).

    Operates on the CODED rel (the serve route translates the public form
    first). Every prefix here is DERIVED from ROLE_CODE, never retyped -- an
    unmatched rel falls through to open, so a hand-typed prefix that drifts
    from the map would silently LEAK sealed art, not 404 it."""
    # The filesystem this guards is case-INSENSITIVE on Windows, so the seal is
    # too: decide on a lowercased copy of the rel and compare against lowercased
    # prefixes. Otherwise a case-variant of a sealed path (e.g. mascots/ACH/<id>)
    # dodges a case-sensitive prefix check, falls through to the fail-open
    # default, and the case-insensitive FS serves the real sealed file anyway.
    # Achievement ids are lowercase, so a lowercased stem matches _ach_ids()
    # directly. (bundle-v2 adversarial-review HIGH finding, 2026-08-21.)
    low = rel.lower()
    rew = ROLE_CODE["rewards"].lower()
    if low in (rew + "/claim.png", rew + "/gift.png", rew + "/inbox.png"):
        # The D8 exception: the two reward UI icons notify.css fetches for the
        # claim toast/modal -- chrome, not prizes, so they stay open while the
        # rest of the bucket seals (an open pair beats a physical move, which
        # would change the public URLs and force a dist rebuild). inbox.png is
        # the same kind of chrome: the header's Inbox button, beside the gift
        # box (owner's art, 2026-10-04; the pack carries it from v7).
        return ("open", None)
    if low.startswith(rew + "/") or low == rew:
        # rewards/ is pure achievement data with no live front-end consumer (the
        # reward-marker reconciliation is tracked work; gate per-achievement when
        # it lands).
        return ("deny", None)
    if low.startswith(_LEGACY_THUMB_DIR + "/") or low == _LEGACY_THUMB_DIR:
        # _thumbs/ was the badge-thumb cache before it moved out to
        # badge_cache_dir(); a stale one may linger in an older install's tree.
        # /badge-thumb/ is the one sanctioned path so its own hidden-feat gate
        # can't be walked around -- keep denying it here.
        return ("deny", None)
    marks = ROLE_CODE["marks"].lower()
    if low.startswith(marks + "/"):
        # Marks are a MIXED bucket: free/shipped tile marks serve open, but a
        # mark bound to an achievement (its marks.json `unlock`) is reward art --
        # served only once earned, exactly like a badge or mascot. Without this
        # branch the lock was CSS-only and /branding/marks/<id>.<ext> handed the
        # full-res locked art to anyone (red team 2026-09-08). marks.json itself
        # is the manifest the picker reads, always open; no nesting under marks/.
        name = low[len(marks) + 1:]
        if "/" in name:
            return ("deny", None)
        if name == "marks.json":
            return ("open", None)
        unlock = _mark_unlock_for(name.rsplit(".", 1)[0])
        if unlock:
            return ("earned", unlock)     # bound: the serve route 404s it until earned
        return ("open", None)             # free mark (or an unknown stem) serves normally
    badges = ROLE_CODE["badges"].lower()
    if low.startswith(badges + "/"):
        aid = low[len(badges) + 1:]
        if aid.endswith(".png"):
            aid = aid[:-4]
        if "/" not in aid and aid in _achievements._ach_ids():
            return ("earned", aid)    # full-res master: the celebration fetches it AT earn time
        return ("deny", None)         # the whole bucket is sauce; unknown files stay sealed
    mascots_ach = ROLE_CODE["mascots_ach"].lower()
    if low.startswith(mascots_ach + "/"):
        aid = low[len(mascots_ach) + 1:].rsplit(".", 1)[0]
        if "/" not in aid and aid in _achievements._ach_ids():
            return ("earned", aid)
        return ("deny", None)
    for moment in ("starfall", "keyturn"):
        if low.startswith(ROLE_CODE[moment].lower() + "/"):
            # A moment's whole bucket -- art, audio, the clip, and for starfall
            # the GONK folder inside it (ROLE_CODE['breadcrumb'] nests under
            # starfall, so this prefix covers it without its own branch) -- is
            # gated on the feat the sealed roster flags with that moment. The
            # feat is looked up, never named here; a roster that carries no
            # such flag (no pack, an older pack) DENIES, because this is the
            # one branch where falling through would fail open.
            aid = _achievements._moment_ach().get(moment)
            return ("earned", aid) if aid else ("deny", None)
    earned_b = ROLE_CODE["earned_banners"].lower()
    if low == earned_b + "/great_library.png":
        return ("earned", "the-great-library")
    if low.startswith(earned_b + "/") or low == earned_b:
        # The rest of the bucket (void_banner.png) is an UNWIRED future reward
        # (achievements #57-60) -- sealed shut until its achievement exists.
        return ("deny", None)
    return ("open", None)


_earned_ids_cache = {"t": 0.0, "ids": frozenset()}
_earned_ids_lock = threading.Lock()


def _earned_achievement_ids(out_dir, db_path, need=None):
    """The set of currently-earned achievement ids -- the seal check for
    achievement-bound art. Cached briefly (one celebration fetches several
    sealed assets back-to-back); a cache answer that would DENY `need` is
    recomputed fresh first, so the fetch that lands milliseconds after the
    earning event never 404s off a stale cache -- staleness can only ever
    delay a denial's recompute, never a legitimate serve."""
    now = time.time()
    with _earned_ids_lock:
        ids = _earned_ids_cache["ids"]
        if now - _earned_ids_cache["t"] < 5.0 and (need is None or need in ids):
            return ids
    metrics = _achievements.achievement_metrics(db_path)
    metrics.update(_telemetry.telemetry_metrics(out_dir))
    result = _achievements.compute_achievements(metrics, (),
                                  sets=_telemetry.load_telemetry(out_dir).get("sets", {}),
                                  earned_at=_achievements.load_ach_state(out_dir).get("earned_at"))
    ids = frozenset(a["id"] for a in result["achievements"] if a["earned"])
    with _earned_ids_lock:
        _earned_ids_cache.update(t=now, ids=ids)
    return ids


def _seed_loose_manifest(rel):
    """Promote a container-shipped manifest to a real loose file before the
    first read-modify-write against it. Without this, the first custom upload
    on a container-dressed install would start from an EMPTY loose manifest and
    silently shadow every shipped default out of the picker (loose wins). A
    no-op when the loose file already exists or the container lacks it."""
    loose = branding_root() / rel
    if loose.exists():
        return
    box = _get_container()
    data = box.get(rel) if box else None
    if data is None:
        return
    try:
        loose.parent.mkdir(parents=True, exist_ok=True)
        loose.write_bytes(data)
    except OSError:
        pass


# Marks the owner has REMOVED from the roster: mark_12 "Gem Tome" (ruled
# 2026-07-23), and mark_74 (the Winged Crescent, remade as mark_nightfallen for
# bundle-v2 -- the old id's loose file lingers on every full-tree install the
# owner ran before the rename). A tombstone rather than a container rebuild alone
# because the rebuild can't reach everywhere: _seed_loose_manifest promotes the
# container's marks.json to a loose file on first customization, and loose wins
# forever after -- so an install that already seeded keeps a removed mark in its
# picker no matter what a new container ships. Just as important, a tombstoned
# stem reads as KNOWN to sweep_branding_drops, so a still-on-disk loose file is
# NOT re-adopted as a fresh hand-drop (which would delete the original, register
# a custom mark, AND fire the branding feat -- the mark_12 near-miss of
# 2026-08-13, which mark_74 would have repeated on the owner's own upgrade).
_MARK_TOMBSTONES = frozenset({"mark_12", "mark_74"})


# A mark's art may be a .png or a .webp. The webp lane exists for ANIMATED marks:
# an animated webp plays natively in an <img>, so the owner can author one himself
# (his Grok -> key -> webp pipeline) and drop it in. png is tried first because
# every shipped default is one; the order is the tie-break, not a preference.
MARK_EXTS = (".png", ".webp")


def mark_art_ext(mark_id):
    """The extension one mark's art actually exists as (loose or container), or ""
    when it has none. The single place the app decides what a mark's file is
    called -- every other site asks here rather than assuming .png."""
    for ext in MARK_EXTS:
        if _branding_exists(_role_rel("marks", str(mark_id) + ext)):
            return ext
    return ""


def list_marks(out_dir, earned_ids=None):
    """Marks available on THIS machine: marks/marks.json entries whose art
    actually exists, resolved loose-then-container (_branding_bytes) so the
    shipped defaults show up even though branding/ itself is deliberately empty
    on a fresh install -- and still empty on a truly bare install with no
    container at all. Tombstoned ids (_MARK_TOMBSTONES) never list.

    Art is .png OR .webp (see MARK_EXTS). The payload key stays `png` even for a
    webp mark: it is the shipped contract every client already reads (and
    brand_context's mark_url comes straight off it), so renaming it would be a
    breaking change for a field that was only ever a URL.

    `unlock` (2026-09-08): a mark entry may carry `unlock: "<achievement id>"`,
    the mark's reward binding -- empty/absent means a free pick, the marks-are-
    pure-data default the 2026-08 rewire plan set. `earned_ids` is the set of
    currently-earned achievement ids (from _earned_achievement_ids); pass it and each
    mark reports `earned` (free, or its unlock is in the set) plus `unlock_name`
    for the "Unlocks with <name>" needle. Pass None -- the many callers that
    don't gate (the custom-mark upload response, the launcher-icon path) -- and
    every mark reports earned:True, exactly the pre-gate behaviour. This is the
    marks half of the same reward gate `/api/skin` already applies to skins."""
    raw = _branding_bytes(_role_rel("marks", "marks.json"))
    if raw is None:
        return []
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []          # corrupt manifest degrades to "no marks", never a 500
    out = []
    for m in data.get("marks") or []:
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or "")
        if mid in _MARK_TOMBSTONES:
            continue
        # Disk/container lookups are coded; the emitted URL stays the PUBLIC
        # role form (the /branding/ route translates on the way back in).
        ext = mark_art_ext(mid) if mid else ""
        if ext:
            unlock = str(m.get("unlock") or "")
            earned = (not unlock) or (earned_ids is None) or (unlock in earned_ids)
            # A feat the roster marks hidden stays masked until it is earned
            # (leak class HIGH #2, owner 2026-08-21; /api/achievements masks the
            # same feat to "???"). So only name the unlock when it is non-hidden,
            # or GENUINELY earned (a real earned set that carries it --
            # earned_ids=None means "not gating / earned unknown", which for a
            # masked feat must stay silent).
            # Fail CLOSED on the roster, exactly as the badge-thumb route does
            # (adversarial 2026-08-22): when the container is missing/invalid/stale
            # _ach_hidden() goes EMPTY, so `unlock not in _ach_hidden()` passes for
            # every mark -- and _ach_name falls back to returning the id itself, so
            # a masked feat's id would be published to an unearned user in exactly
            # the state we cannot verify anything. Name it only when the roster
            # actually carries it.
            named = bool(unlock) and unlock in _achievements._ach_ids() and (
                unlock not in _achievements._ach_hidden()
                or (earned_ids is not None and unlock in earned_ids))
            out.append({"id": mid, "label": m.get("label") or mid,
                        "kind": m.get("kind") or "tile",
                        "png": "/branding/marks/%s%s" % (mid, ext),
                        "animated": ext == ".webp",
                        # BOTH the raw id and the display name are spoiler-masked on
                        # the SAME `named` gate: the earlier fix masked only
                        # unlock_name and left `unlock` carrying the raw hidden-feat
                        # id to any unearned LOGIN user on
                        # GET /api/branding and /api/panel/summary (spoiler audit
                        # 2026-09-08). `earned` is computed off the local `unlock`
                        # above, and the seal rule reads the binding straight from
                        # marks.json -- neither depends on this emitted field.
                        "unlock": unlock if named else "",
                        "unlock_name": _ach_name(unlock) if named else "",
                        "earned": earned,
                        "ico": _branding_exists(_role_rel("marks", mid + ".ico"))})
    return out


def _earned_roster_flags(entry):
    """The sealed roster flags /api/achievements adds to an achievement ONCE IT IS
    EARNED (pack v5), from its roster `entry`: `unlocks` (what the earn opens, e.g.
    a Control Panel tab), and for a feat with a bespoke moment `moment`,
    `moment_clip` (the clip's neutral public /branding/ URL, "" for a moment this
    build has no clip for) and `moment_copy` (the moment's sealed strings). The
    caller applies it to earned entries only -- before the earn none of these keys
    exists in the payload, the same masking unlock_name gets -- and the client keys
    on these flags, never on an achievement id. {} for an entry with no flags."""
    out = {}
    if not isinstance(entry, dict):
        return out
    unlocks = entry.get("unlocks")
    if isinstance(unlocks, str) and unlocks:
        out["unlocks"] = unlocks
    moment = entry.get("moment")
    if isinstance(moment, str) and moment:
        clip = _MOMENT_CLIPS.get(moment)
        copy = entry.get("moment_copy")
        out["moment"] = moment
        out["moment_clip"] = "/branding/" + clip if clip else ""
        out["moment_copy"] = ({k: v for k, v in copy.items()
                               if isinstance(k, str) and isinstance(v, str)}
                              if isinstance(copy, dict) else {})
    return out


def earned_relic_marks(out_dir, earned_ids):
    """The marks an achievement AWARDED and the account has earned -- the Folio's Marks row
    (Small Calls L2, relics by kind). A free mark (no `unlock` binding) is not a relic, and an
    unearned one is never listed at all, so nothing here says a locked mark exists: the row is
    built from earned marks only and the client shows no empty slot. `unlock` is the awarding
    achievement's id (list_marks blanks it for a hidden feat until that feat is earned, so a
    listed mark's binding is always one the account already holds); the client dates the mark
    by that achievement's earned_at. `earned_ids` is the set of currently-earned ids."""
    out = []
    for m in list_marks(out_dir, set(earned_ids or ())):
        if m.get("earned") and m.get("unlock"):
            out.append({"id": m["id"], "label": m["label"], "png": m["png"],
                        "animated": bool(m.get("animated")), "unlock": m["unlock"]})
    return out


# ---------------------------------------------------------------------------
# MASKED FEATS (Session G): the Folio's ONE veil card. The payload carries a riddle and an
# alpha-only silhouette of the NEXT unfound feat's badge, and nothing else about it -- no
# id, name, description, count, order, points, earned-by, badge art or file name. The
# roster fields it reads are the sealed `riddle` (and its unleashed twin `riddle_nsfw`);
# a feat whose roster entry carries no riddle is never picked, so a pack that has none yet
# shows no veil at all rather than invented copy.
# ---------------------------------------------------------------------------
FEAT_MASK_PX = 256


def feat_mask_png(badge_bytes, max_px=FEAT_MASK_PX):
    """The alpha-only mask of one badge: white on transparent, cut from the badge's OWN
    alpha channel and never carrying its colours. `badge_bytes` is the badge file's bytes
    (any format Pillow reads); the result is PNG bytes at most `max_px` on the long edge,
    or None when the bytes are not an image. A badge with no alpha at all yields a solid
    silhouette (its honest outline) rather than a leak of its pixels.

    A small PURE helper on purpose: the pack build (pack v6) calls it too, to pre-cut the
    masks it ships, so the lazy cut below and the pre-cut file can never disagree."""
    import io
    try:
        from PIL import Image
        with Image.open(io.BytesIO(badge_bytes)) as im:
            im.load()
            if "A" in im.getbands() or "transparency" in im.info:
                alpha = im.convert("RGBA").getchannel("A")
            else:
                alpha = Image.new("L", im.size, 255)
        alpha.thumbnail((int(max_px), int(max_px)))
        out = Image.new("RGBA", alpha.size, (255, 255, 255, 255))
        out.putalpha(alpha)
        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        return None


def _feat_riddles(entry):
    """(riddle, riddle_nsfw) from one sealed roster entry: stripped strings, "" when the
    field is absent or not text. Never invents a riddle."""
    if not isinstance(entry, dict):
        return "", ""
    out = []
    for key in ("riddle", "riddle_nsfw"):
        v = entry.get(key)
        out.append(v.strip() if isinstance(v, str) else "")
    return out[0], out[1]


def _pick_masked_feat(earned_ids, roster=None, has_art=None):
    """The roster entry the veil card is drawn for, or None. It is the first hidden feat,
    in roster order, that is not earned yet, carries a riddle and (when `has_art` is given)
    has badge art to cut a silhouette from. None until a feat has been earned at all (the
    Feats section stays cloaked until then), and None once nothing eligible is left.

    The server picks; the client never names which. Roster order is used only to choose --
    it is never sent."""
    roster = _achievements._roster() if roster is None else roster
    entries = [a for a in roster if isinstance(a, dict)]
    if not any(a.get("tier") == "feat" and a.get("id") in earned_ids for a in entries):
        return None
    for a in entries:
        aid = a.get("id")
        if not a.get("hidden") or not aid or aid in earned_ids:
            continue
        if not _feat_riddles(a)[0]:
            continue
        if has_art is not None and not has_art(aid):
            continue
        return a
    return None


def _feat_mask_token(secret, aid):
    """The opaque token that names the veil's mask in its URL: an HMAC of the achievement
    id under this install's own secret, so it reveals nothing about the feat's id, name or
    file, is stable for one feat on one install (the browser can cache the mask), and
    cannot be computed by anyone who lacks the secret."""
    key = ("feat-mask:" + str(secret)).encode("utf-8")
    return hmac.new(key, str(aid).encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def _feats_payload(earned_ids, n_masked, feats_revealed, unleashed, secret):
    """The `feats` object /api/achievements carries beside the earned feats (which stay in
    `achievements`, unchanged):

        masked     None, or {"riddle", "mask_url"[, "riddle_nsfw"]} for the ONE feat the
                   server picks. `riddle_nsfw` is the unleashed twin, present only where
                   roast_nsfw is (the account has earned Triggered) and the pack has one:
                   the client's Unleash switch chooses which line to show, exactly as it
                   does for the roast.
        all_found  True only when the roster has hidden feats and none is left. It is what
                   tells the client "Every secret found" apart from "no veil yet" (a pack
                   with no riddles), and it says nothing a masked veil does not already.

    Both are cloaked (None / False) until a feat has been earned, so devtools before the
    first earn learns nothing. Nothing else about a masked feat is ever built into this."""
    out = {"masked": None, "all_found": False}
    if not feats_revealed:
        return out
    hidden_total = len(_achievements._ach_hidden())
    out["all_found"] = bool(hidden_total) and n_masked == 0
    pick = _pick_masked_feat(
        earned_ids, has_art=lambda aid: _branding_exists(_role_rel("badges", aid + ".png")))
    if pick is not None:
        riddle, riddle_nsfw = _feat_riddles(pick)
        masked = {"riddle": riddle,
                  "mask_url": "/feat-mask/" + _feat_mask_token(secret, pick["id"]) + ".png"}
        if unleashed and riddle_nsfw:
            masked["riddle_nsfw"] = riddle_nsfw
        out["masked"] = masked
    return out


def feat_mask_cache_dir(out_dir=None):
    """Where the lazily cut masks live: local/cache/masks/, a sibling of badge_cache_dir()'s
    badges/ (outside the coded branding tree, and outside every library: a mask's name is an
    HMAC under this install's secret, meaningless to any other install). Files are named by
    the opaque token, never by the achievement id. Rebuildable: anything here is cut again
    when next asked for. (`out_dir` is accepted and unused.)"""
    return _paths.cache_dir() / "masks"


def _feat_mask_bytes(out_dir, aid, token):
    """The mask PNG bytes for one feat: the pack's badge cut to its alpha silhouette once
    and cached under the library folder (re-cut when the badge master changes). None when
    the badge is missing or unreadable. A cache that cannot be written still answers."""
    rel = _role_rel("badges", aid + ".png")
    if not _branding_exists(rel):
        return None
    dst = feat_mask_cache_dir(out_dir) / (token + ".png")
    src_mtime = _branding_mtime(rel)
    try:
        if dst.is_file() and src_mtime is not None and dst.stat().st_mtime >= src_mtime:
            return dst.read_bytes()
    except OSError:
        pass
    raw = _branding_bytes(rel)
    if raw is None:
        return None
    png = feat_mask_png(raw)
    if png is None:
        return None
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(png)
    except OSError:
        pass
    return png


def _ach_name(aid):
    """The display name of one achievement id, or the id itself if the roster
    has no entry (a mark bound to an id the current pack does not carry still
    shows *something* rather than an empty needle)."""
    if not aid:
        return ""
    for a in _achievements._roster():
        if (a.get("id") if isinstance(a, dict) else a) == aid:
            return (a.get("name") if isinstance(a, dict) else "") or aid
    return aid


def _mark_unlock_for(mid):
    """The achievement id a mark is bound to (its marks.json `unlock`), or "" for
    a free mark, an unknown id, or a missing/corrupt manifest. Read fresh from
    the manifest so the seal check on mark ART (_seal_rule's marks/ branch) can
    never drift from the `unlock` list_marks() offers the picker off the same
    file. Fails open ("" -> serve): a bound mark only exists when marks.json
    parses AND carries its unlock, so a corrupt manifest has no bound mark to
    leak (list_marks returns [] from it too)."""
    if not mid:
        return ""
    raw = _branding_bytes(_role_rel("marks", "marks.json"))
    if not raw:
        return ""
    try:
        for m in (json.loads(raw.decode("utf-8")).get("marks") or []):
            if isinstance(m, dict) and str(m.get("id") or "") == mid:
                return str(m.get("unlock") or "")
    except (ValueError, UnicodeDecodeError):
        pass
    return ""


# The 4 Branding-tab slots Control Panel.dc.html specs beyond Icons & marks
# (banner-main/banner-login/mascots/rewards) -- none had any backend at all
# before this. Deliberately ONE shape for all four (manifest.json + <id>.png
# per slot, same "many stored, one exists-checked" contract list_marks() above
# already established) rather than a bespoke single-file slot vs. a bespoke
# multi-file slot: the F1/F2 SQLite-bundle work only has to learn ONE storage
# shape to take over, not four. Rotating-source selection (Banner-main's own
# "pick FROM a collection" mechanic) is explicitly deferred until that bundle
# work lands (owner call, 2026-08-05) -- for now every slot is just "the
# uploaded assets, one of which is active", identical to how marks/mark
# already relate, so that later mechanic has real asset ids to pick FROM
# instead of a schema migration first.
# banner_loom (12:1 workspace strip) added 2026-08-06 with the Branding-tab rebuild
# (Control Panel.dc.html SLOTS index 5: "Banner - Loom", 1920x160). It joins the two
# 4:1 banners as a real, written-through slot.
#
# mascots/rewards were REMOVED from this tuple 2026-08-13, enforcing the bundle's
# unlock split (moonglade-internal/DECISIONS.md 2026-07-27 + the 2026-08-06 mascots correction):
# the Branding surface reaches banners + marks only. rewards/ is achievement data,
# and mascots' customization ships later as a named-role checklist over an
# owner-curated SELECTION of system roles -- not a pick-one-active gallery, and not
# the full role list. Until then neither is a slot: the payload doesn't list them,
# the upload/crop/set-active routes refuse them. Their on-disk folders stay
# (see _BRANDING_DISCOVERY_SLOTS).
#
# That checklist is here now (Session X, 2026-10-03): the four named roles below. The
# banner-shaped slots keep their own tuple, because every banner function (manifest,
# active pick, crop, render) is about THAT shape and must not see a role.
BANNER_SLOTS = ("banner_main", "banner_login", "banner_loom")

# The named roles: an owner-curated four of the app's own system art (the keep-fixed roles,
# the easter-egg set, achievement-bound art, the claim popup, the logo, the favicon and the app
# icons are NOT here and never will be by accident -- adding one means editing this table).
# Each role is a set of images keyed by a short name; each image owns ONE public /branding/
# name, the one the app already asks for. An override is a single file written where that name
# resolves first (the coded tree, loose before the pack), so every screen that shows the art
# wears it with no change of its own; the pack's default stays in the container and is never
# written.
#
# WHAT AN UPLOAD MUST BE is checked HERE whatever the client said, and it is derived from the
# art it replaces (role_image_spec): the role's formats and drawn minimum size, plus, per image,
# `default` -- the pack default's own size (and whether it moves). The shape must lie between square
# and that default's shape, ROLE_ASPECT_TOLERANCE beyond either (so a tall mascot's slot takes a
# square picture as well as one shaped like it), the minimum size is the drawn one unless the default
# is smaller (then the default's own), and an animation is allowed only where the role says its format
# may (the login companion's default is an animated WebP). Transparency is always required. The
# stand-in specs drawn first (3:4, square) would have refused the pack's own login companion, the
# tracker's done / failed / empty and the gift icon; dev/tests/test_branding_roles.py holds that every
# pack default passes its own role's check.
ROLE_SLOTS = {
    "login_companion": {
        "name": "Login companion", "where": "the sign-in page",
        "spec": {"formats": ["WEBP", "PNG"], "transparent": True, "animated_formats": ["WEBP"],
                 "min_axis": "height", "min_px": 600},
        # Pack v7 re-encoded every animation 360 px tall: the login companion is 366 x 360.
        "images": {"companion": {"label": "Companion", "public": "login_nel.webp",
                                 "default": {"w": 366, "h": 360, "animated": True}}},
    },
    "tracker_mascots": {
        "name": "Job tracker mascots", "where": "the job tracker",
        "spec": {"formats": ["PNG"], "transparent": True, "animated_formats": [],
                 "min_axis": "side", "min_px": 128},
        "images": {"spinner": {"label": "Spinner", "public": "nel_spinner.png",
                               "default": {"w": 566, "h": 560}},
                   "done": {"label": "Done", "public": "mascots/trk_done.png",
                            "default": {"w": 329, "h": 364}},
                   "failed": {"label": "Failed", "public": "mascots/trk_fail.png",
                              "default": {"w": 324, "h": 365}},
                   "empty": {"label": "Empty", "public": "mascots/trk_empty.png",
                             "default": {"w": 402, "h": 356}}},
    },
    "reward_icons": {
        "name": "Reward icons", "where": "the claim toast and the header",
        "spec": {"formats": ["PNG"], "transparent": True, "animated_formats": [],
                 "min_axis": "side", "min_px": 64},
        "images": {"claim": {"label": "Claim", "public": "rewards/claim.png",
                             "default": {"w": 128, "h": 128}},
                   "gift": {"label": "Gift", "public": "rewards/gift.png",
                            "default": {"w": 128, "h": 119}}},
    },
    "power_poses": {
        "name": "Power poses", "where": "the restart and shutdown screens",
        "spec": {"formats": ["PNG"], "transparent": True, "animated_formats": [],
                 "min_axis": "side", "min_px": 256},
        "images": {"restart": {"label": "Restart", "public": "mascots/nel_restart.png",
                               "default": {"w": 406, "h": 401}},
                   "shutdown": {"label": "Shutdown", "public": "mascots/nel_shutdown.png",
                                "default": {"w": 401, "h": 398}}},
    },
}
BRANDING_SLOTS = BANNER_SLOTS + tuple(ROLE_SLOTS)

# What an upload to a role must clear besides its spec: a hard ceiling on the bytes read and on
# the pixels' extent (checked from the header, before any pixel is decoded), the shape tolerance
# (how far beyond square, or beyond the pack default's shape, a picture's may lie, relative), "transparent"
# meaning at least 1 % of the pixels are more than half see-through, and the budget for an
# animation the role allows (its frames are decoded one at a time to prove the file is sound, so
# the count and the total pixels are capped first).
ROLE_MAX_BYTES = 12 * 1024 * 1024
ROLE_MAX_SIDE = 4096
ROLE_ASPECT_TOLERANCE = 0.08
ROLE_SEE_THROUGH_MIN = 0.01
ROLE_MAX_FRAMES = 300
ROLE_MAX_ANIM_PIXELS = 64_000_000
# The only formats a role upload ever opens. Pillow identifies dozens, some with decoders that shell
# out or are old and sprawling (EPS via Ghostscript, TIFF, PSD...); those never reach a decoder here.
# PNG and WebP are what a role takes; JPEG and GIF are opened only so the editor can refuse them BY
# NAME ("this one is JPEG") rather than "couldn't read this".
ROLE_OPEN_FORMATS = ("PNG", "WEBP", "JPEG", "GIF")
# The same question asked of a banner upload (/api/branding/slot decodes the same way): banners are
# wide, so the ceiling is higher, but a WebP may not declare a canvas past it.
BANNER_MAX_SIDE = 8192


def _slot_dir(slot):
    # Slot names double as ROLE_CODE keys, so the coded folder falls straight
    # out of the map -- the LOGICAL slot key ("banner_main") stays the JSON/API
    # vocabulary everywhere above this line.
    return _role_dir(slot)


def _asset_transform(it):
    """Normalize one manifest item's crop transform to the design's zoom/cropX/cropY
    model (Control Panel.dc.html:953 -- object-position cropX% cropY% + scale(zoom/100)).
    Back-compat: an item written under the OLD left/center/right crop model (pre
    2026-08-06) maps to the equivalent pan -- left->cropX 0, center->50, right->100 --
    at zoom 100, cropY 50, so an existing install's banners keep displaying unchanged
    until re-tuned."""
    if not isinstance(it, dict):
        it = {}
    if "zoom" in it or "cropX" in it or "cropY" in it:
        z = it.get("zoom", 100); cx = it.get("cropX", 50); cy = it.get("cropY", 50)
    else:
        legacy = {"left": 0, "right": 100}.get(it.get("crop") or "center", 50)
        z, cx, cy = 100, legacy, 50
    try:
        z = max(100, min(int(z), 250))
        cx = max(0, min(int(cx), 100))
        cy = max(0, min(int(cy), 100))
    except (TypeError, ValueError):
        z, cx, cy = 100, 50, 50
    return {"zoom": z, "cropX": cx, "cropY": cy}


def list_slot_assets(out_dir, slot):
    """Uploaded assets for one Branding slot: branding/<slot>/manifest.json
    entries whose .png actually exists. Empty on a fresh install / until that
    slot's first real upload, exactly like list_marks() above. Each asset carries
    its zoom/cropX/cropY transform (normalized, legacy crop migrated)."""
    if slot not in BANNER_SLOTS:
        return []
    raw = _branding_bytes(_role_rel(slot, "manifest.json"))
    if raw is None:
        return []
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []          # corrupt manifest degrades to "no assets", never a 500
    out = []
    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        iid = str(it.get("id") or "")
        if iid and _branding_exists(_role_rel(slot, iid + ".png")):
            out.append({"id": iid, **_asset_transform(it),
                        "png": "/branding/%s/%s.png" % (slot, iid)})
    return out


def _recorded_slot_active(out_dir):
    """The RECORDED pick per slot, exactly as settings.json's branding.slots holds it -- no
    self-heal, no existence check, no defaulting. Split out so the resolver below can be
    handed ONE read instead of re-reading it per slot. (settings.json is written through
    moonglade.settings.update_branding, which changes only the key it is asked to, so the
    mark's writer can never clobber a slot pick or the other way round.)"""
    raw = _settings.branding().get("slots")
    if not isinstance(raw, dict):
        return {}
    return {k: str(v) for k, v in raw.items() if k in BANNER_SLOTS and v}


def resolve_slot_active(out_dir, slot, recorded=None, assets=None):
    """Which asset a slot actually wears, by ONE rule for every caller:

      1. the RECORDED pick, when an asset with that id still exists on disk;
      2. otherwise the manifest's LAST item -- the most recent upload, which is
         the one add_slot_asset() makes active on the way in, so a pick that
         went missing heals to the asset the last upload had already chosen;
      3. otherwise None (the slot is empty).

    One function because the answer has to be the SAME answer in three places:
    the payload the Branding tab is served, load_slot_active()'s self-heal, and
    the startup ensure pass that decides whether a render is still current. The
    self-heal used to be `next(iter({ids}), None)` over a SET, and a set of
    strings iterates in hash order -- which is randomised per process. With two
    assets and no recorded pick, two starts of one install could resolve to
    different assets, so the ensure pass compared the render against one answer
    and re-rendered it to the other, on every other boot.

    `recorded` / `assets` let a caller that already has them skip the re-read."""
    if slot not in BANNER_SLOTS:
        return None
    ids = [a["id"] for a in (list_slot_assets(out_dir, slot) if assets is None else assets)]
    if recorded is None:
        recorded = _recorded_slot_active(out_dir).get(slot)
    if recorded in ids:
        return recorded
    return ids[-1] if ids else None


def load_slot_active(out_dir):
    """Which uploaded asset (by id) is the ACTIVE one per slot -- the same
    relationship settings.json's branding "mark" already has to list_marks():
    many stored, one worn. Self-heals exactly like load_branding() does for
    "mark": a recorded active id that no longer exists on disk (deleted file,
    corrupt manifest) falls back through resolve_slot_active() above, which is
    where the healing rule -- and its determinism -- lives."""
    recorded = _recorded_slot_active(out_dir)
    return {slot: resolve_slot_active(out_dir, slot, recorded.get(slot))
            for slot in BANNER_SLOTS}


def save_slot_active(out_dir, active):
    slots = {k: v for k, v in active.items() if v}
    _settings.update_branding(lambda b: b.__setitem__("slots", slots))


def add_slot_asset(out_dir, slot, png_bytes, zoom=100, cropx=50, cropy=50):
    """Save a new upload into one Branding slot and make it the active one.
    Returns the new asset dict, or None for an unknown slot. Caller (the
    /api/branding/slot route) is responsible for making sure png_bytes is a
    real PNG before this is called -- this function just persists it. New
    uploads start at the neutral transform (zoom 100, centered) -- the
    equivalent of the design's own defaults."""
    if slot not in BANNER_SLOTS:
        return None
    sdir = _slot_dir(slot)
    sdir.mkdir(parents=True, exist_ok=True)
    # First write against a container-dressed slot: promote the shipped manifest
    # loose first, or this upload would shadow every default out of the picker.
    _seed_loose_manifest(_role_rel(slot, "manifest.json"))
    try:
        data = json.loads((sdir / "manifest.json").read_text(encoding="utf-8"))
        items = list(data.get("items") or []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        items = []
    new_id = secrets.token_hex(4)
    (sdir / (new_id + ".png")).write_bytes(png_bytes)
    # The app just put a file in the tree: record it as a default in the same
    # breath, so the read-only scan cannot later read the app's own write as a
    # file the install did not put there (_baseline_note_app_write).
    _baseline_note_app_write(out_dir, _role_rel(slot, new_id + ".png"))
    t = _asset_transform({"zoom": zoom, "cropX": cropx, "cropY": cropy})
    items.append({"id": new_id, **t})
    (sdir / "manifest.json").write_text(json.dumps({"items": items}, indent=2), encoding="utf-8")
    active = load_slot_active(out_dir)
    active[slot] = new_id
    save_slot_active(out_dir, active)
    _write_banner_flat(out_dir, slot)   # the new upload is now active -> display it
    return {"id": new_id, **t, "png": "/branding/%s/%s.png" % (slot, new_id)}


def set_slot_crop(out_dir, slot, item_id, zoom=None, cropx=None, cropy=None):
    """Update one already-uploaded asset's zoom/cropX/cropY transform (Control
    Panel.dc.html's three banner sliders -- zoom 100-250, cropX/cropY 0-100).
    Any field left None keeps its stored value. False for an unknown slot/item,
    never a 500. Widened 2026-08-06 from the old 3-value left/center/right crop."""
    if slot not in BANNER_SLOTS:
        return False
    sdir = _slot_dir(slot)
    # Adjusting a shipped default's crop is a WRITE -- promote the manifest
    # loose first so the edit lands on a real file (P3-review lesson: without
    # this, retuning a container-shipped banner just failed).
    _seed_loose_manifest(_role_rel(slot, "manifest.json"))
    try:
        data = json.loads((sdir / "manifest.json").read_text(encoding="utf-8"))
        items = data.get("items") if isinstance(data, dict) else None
    except (OSError, ValueError):
        return False
    if not isinstance(items, list):
        return False
    found = False
    for it in items:
        if isinstance(it, dict) and str(it.get("id")) == str(item_id):
            cur = _asset_transform(it)
            merged = {
                "zoom": cur["zoom"] if zoom is None else zoom,
                "cropX": cur["cropX"] if cropx is None else cropx,
                "cropY": cur["cropY"] if cropy is None else cropy,
            }
            norm = _asset_transform(merged)
            it.pop("crop", None)          # drop the legacy field once re-tuned
            it.update(norm)
            found = True
    if not found:
        return False
    (sdir / "manifest.json").write_text(json.dumps({"items": items}, indent=2), encoding="utf-8")
    if load_slot_active(out_dir).get(slot) == str(item_id):
        _write_banner_flat(out_dir, slot)   # the transform is baked into the displayed flat
    return True


def set_slot_active(out_dir, slot, item_id):
    """Mark an already-uploaded asset as the active one for its slot. False for
    an unknown slot or an item_id that isn't a real asset in it -- there is no
    "clear to none" here on purpose: the design never models deselecting a slot
    back to empty, only picking among what's uploaded, and load_slot_active()'s
    own self-heal (falling back to the first real asset when nothing is
    recorded) would silently undo a stored None anyway, since the two cases
    look identical on disk."""
    if slot not in BANNER_SLOTS:
        return False
    if not item_id or item_id not in {a["id"] for a in list_slot_assets(out_dir, slot)}:
        return False
    active = load_slot_active(out_dir)
    active[slot] = item_id
    save_slot_active(out_dir, active)
    _write_banner_flat(out_dir, slot)
    return True


def _mark_earned(out_dir, db_path, ach_id):
    """Whether one specific achievement id is currently earned -- runs the exact
    same compute_achievements() pipeline /api/achievements itself uses, so a
    custom-mark upload can never disagree with what the Branding tab already
    shows unlocked. Pure read (no save_ach_state call), so unlike that route it
    needs no lock -- nothing here can race a concurrent write."""
    metrics = _achievements.achievement_metrics(db_path)
    metrics.update(_telemetry.telemetry_metrics(out_dir))
    state = _achievements.load_ach_state(out_dir)
    result = _achievements.compute_achievements(metrics, state.get("seen"),
                                   sets=_telemetry.load_telemetry(out_dir).get("sets", {}),
                                   earned_at=state.get("earned_at"))
    return any(a["id"] == ach_id and a["earned"] for a in result["achievements"])


ICO_SIZES = (16, 32, 48, 256)


def _cut_mark_ico(mdir, mark_id, art_bytes):
    """Cut <mark_id>.ico beside an uploaded mark's art. Returns True if the file was
    written, False if it could not be (and the caller keeps the mark either way).

    WHY: the Desktop launcher shortcut is the app's real icon (make_launcher_shortcut --
    a .pyw cannot carry one, the .lnk can), and it reads a mark's .ico off disk. The
    shipped tile marks are delivered with one already cut; an UPLOADED mark never had one,
    so POST /api/branding/shortcut answered "no .ico cut" for it and a custom mark could
    never become the launcher's icon. Cutting it at upload time is what closes that.

    The art is padded to a SQUARE on transparency (an icon is square; letterboxing beats
    stretching), and scaled to 256 when it is smaller, so all four of ICO_SIZES really land
    in the file rather than Pillow silently dropping the ones larger than the source. An
    animated webp contributes its FIRST frame -- an .ico has no animation to keep it in.

    FAILS SOFT on everything: no Pillow, unreadable art, a write that cannot happen. The
    mark itself is already saved by the time this runs, and losing the icon is not a reason
    to lose the mark."""
    try:
        import io
        from PIL import Image
        with Image.open(io.BytesIO(art_bytes)) as im:
            im.load()
            rgba = im.convert("RGBA")
        side = max(rgba.width, rgba.height)
        if side <= 0:
            return False
        if rgba.width != rgba.height:
            square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            square.paste(rgba, ((side - rgba.width) // 2, (side - rgba.height) // 2))
            rgba = square
        biggest = max(ICO_SIZES)
        if side < biggest:
            rgba = rgba.resize((biggest, biggest), Image.LANCZOS)
        rgba.save(mdir / (str(mark_id) + ".ico"), format="ICO",
                  sizes=[(s, s) for s in ICO_SIZES])
        return True
    except Exception:
        return False


def add_custom_mark(out_dir, png_bytes, label="Custom mark", ext=".png"):
    """Save The Great Library's custom-mark upload into branding/marks/ and make
    it the active mark. Same manifest shape list_marks() already reads
    (marks.json + <id>.png) -- one new kind:'upload' entry, not a new storage
    concept, matching how add_slot_asset() extends the identical contract for
    banner slots. Unlike _adopt_mark() (the filesystem-drop path, which derives
    an id from the dropped filename), this is a real upload with a random id,
    same convention add_slot_asset() uses for banner uploads.

    There is only ONE custom-mark slot (the design's single 6th tile), so a
    second upload REPLACES the first -- any existing kind:'upload' entry (and
    its .png/.webp/.ico) is dropped here first, rather than accumulating
    orphaned marks the picker would need de-duping logic to hide.

    Also cuts the mark's launcher .ico (2026-09-07, see _cut_mark_ico) -- the
    returned `ico` is True when that file was written and False when the cut
    failed, and the mark is saved either way."""
    mdir = _role_dir("marks")
    mdir.mkdir(parents=True, exist_ok=True)
    _seed_loose_manifest(_role_rel("marks", "marks.json"))   # keep shipped defaults in the picker
    try:
        data = json.loads((mdir / "marks.json").read_text(encoding="utf-8"))
        marks = list(data.get("marks") or []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        marks = []
    for old in [m for m in marks if isinstance(m, dict) and (m.get("kind") or "tile") == "upload"]:
        # ".ico" joins MARK_EXTS here (2026-09-07): an upload now gets one cut for it, so
        # the replaced upload's icon has to go with its art -- otherwise a stale .ico
        # outlives the mark it was cut from and list_marks would keep claiming it.
        for old_ext in MARK_EXTS + (".ico",):   # the replaced upload may be either format
            old_art = mdir / (str(old.get("id")) + old_ext)
            if old_art.exists():
                old_art.unlink()
    marks = [m for m in marks if not (isinstance(m, dict) and (m.get("kind") or "tile") == "upload")]
    new_id = secrets.token_hex(4)
    (mdir / (new_id + ext)).write_bytes(png_bytes)
    # Cut the launcher icon too (2026-09-07). Before this an upload always reported
    # ico:False and POST /api/branding/shortcut refused it, so a custom mark could never
    # become the app's Desktop icon. Best effort: the mark is already on disk, and a
    # failed cut costs the icon, never the mark.
    ico = _cut_mark_ico(mdir, new_id, png_bytes)
    # Both files the app just wrote into the tree go into the baseline as
    # defaults (_baseline_note_app_write). The .ico matters as much as the art:
    # Pillow reads an .ico perfectly well, so an unrecorded one would raise the
    # flag on the very next scan.
    _baseline_note_app_write(out_dir, _role_rel("marks", new_id + ext))
    if ico:
        _baseline_note_app_write(out_dir, _role_rel("marks", new_id + ".ico"))
    marks.append({"id": new_id, "label": label, "kind": "upload"})
    (mdir / "marks.json").write_text(json.dumps({"marks": marks}, indent=2), encoding="utf-8")
    cfg = load_branding(out_dir)
    cfg["mark"] = new_id
    save_branding(out_dir, cfg)
    return {"id": new_id, "label": label, "kind": "upload",
            "png": "/branding/marks/%s%s" % (new_id, ext),
            "animated": ext == ".webp", "ico": ico}


def remove_custom_mark(out_dir, mark_id):
    """Remove one uploaded custom mark. Refuses to touch a non-upload (built-in
    tile) mark -- the design's Replace/Remove chips only ever appear next to the
    uploaded one, but this guard makes that true at the data layer too, not just
    the UI. Reverts the active mark back to the default logo if the removed one
    was the one currently worn."""
    mdir = _role_dir("marks")
    try:
        data = json.loads((mdir / "marks.json").read_text(encoding="utf-8"))
        marks = list(data.get("marks") or []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        return False
    target = next((m for m in marks if isinstance(m, dict) and str(m.get("id")) == str(mark_id)
                   and (m.get("kind") or "tile") == "upload"), None)
    if target is None:
        return False
    keep = [m for m in marks if m is not target]
    (mdir / "marks.json").write_text(json.dumps({"marks": keep}, indent=2), encoding="utf-8")
    # ".ico" joins the sweep (2026-09-07): an upload gets a launcher icon cut for it, and
    # it must not outlive the mark -- a left-behind .ico is an icon path pointing at a
    # mark that no longer exists.
    for ext in MARK_EXTS + (".ico",):    # an uploaded mark may be png or webp
        art = mdir / (str(mark_id) + ext)
        if art.exists():
            art.unlink()
    cfg = load_branding(out_dir)
    if cfg.get("mark") == str(mark_id):
        cfg["mark"] = "logo"
        save_branding(out_dir, cfg)
    return True


def branding_slots_payload(out_dir):
    """The Branding tab's full slot state -- assets + which one is active, per
    slot -- in the one shape both /api/branding and /api/panel/summary hand to
    the React BrandingTab. A single function so both routes can never disagree
    about what a slot looks like.

    The active id comes from resolve_slot_active() -- the same function the
    self-heal and the startup render pass ask -- so what the tab shows as active
    is what the header is actually wearing. Each slot's manifest is parsed once
    and handed to both halves."""
    recorded = _recorded_slot_active(out_dir)
    out = {}
    for slot in BANNER_SLOTS:
        assets = list_slot_assets(out_dir, slot)
        out[slot] = {"assets": assets,
                     "active": resolve_slot_active(out_dir, slot, recorded.get(slot), assets)}
    return out


# ---------------------------------------------------------------------------
# The named roles (Session X): what an upload must be, how it is written, how it is undone,
# and what the app does when an override cannot be read. ROLE_SLOTS (above) is the table.
# ---------------------------------------------------------------------------
def _ratio_label(w, h):
    """A picture's shape in words for a refusal: "1:1", "3:2", "16:9", or "1.71:1" when no small
    whole-number ratio matches within half a percent."""
    if w <= 0 or h <= 0:
        return "0:0"
    have = w / h
    for q in range(1, 17):
        p = round(have * q)
        if p >= 1 and abs(have - p / q) / have <= 0.005:
            g = math.gcd(p, q)
            return "%d:%d" % (p // g, q // g)
    return "%.2f:1" % have


def role_image_spec(slot, key):
    """What ONE image's override must be: the role's formats, transparency and drawn minimum, with
    the SHAPE taken from the pack default it replaces (anything between square and that shape,
    ROLE_ASPECT_TOLERANCE beyond either: see role_spec_failures) and the minimum size lowered to the
    default's own where the default is smaller than the drawn minimum (the login companion's pack
    art is 360 px tall, the drawn minimum 600)."""
    role = ROLE_SLOTS[slot]
    base, d = role["spec"], role["images"][key]["default"]
    own = d["h"] if base["min_axis"] == "height" else min(d["w"], d["h"])
    return {"formats": list(base["formats"]), "transparent": base["transparent"],
            "animated_formats": list(base["animated_formats"]),
            "aspect": [d["w"], d["h"]], "aspect_tolerance": ROLE_ASPECT_TOLERANCE,
            "min_axis": base["min_axis"], "min_px": min(base["min_px"], own)}


def _aspect_words(aw, ah, tol):
    """The shape an image may take, in words for a rule: "about square" when its pack default is
    square to within the tolerance, else the span from that default's shape to square, "about 9:10
    to square" (a tall default) or "about square to 9:8" (a wide one)."""
    a = aw / ah
    if abs(a - 1.0) <= tol:
        return "about square"
    label = _ratio_label(aw, ah)
    return "about %s to square" % label if a < 1 else "about square to %s" % label


def role_spec_failures(spec, facts):
    """The rules `facts` breaks against one image's spec (role_image_spec), in the order the editor
    lists them: format, transparency, animation, shape, size. [] means the file is acceptable.

    `facts` is what was MEASURED (role_measure): {"format": "PNG", "w": 256, "h": 256,
    "see_through": 0.31, "animated": False} (see_through = the share of pixels more than half
    clear). Each failure is {"rule", "need", "got"}: the words a refusal and the editor's tick
    line both use. The client runs the same rules over the same measurements
    (lib/brandRolesCore.js) to tick them live; THIS is the one that decides."""
    failed = []
    fmt = str(facts.get("format") or "").upper()
    if fmt not in spec["formats"]:
        failed.append({"rule": "format", "need": " or ".join(spec["formats"]), "got": fmt or "unknown"})
    if spec["transparent"] and facts["see_through"] < ROLE_SEE_THROUGH_MIN:
        clear = facts["see_through"]
        failed.append({"rule": "transparent", "need": "a transparent background",
                       "got": "opaque" if clear <= 0 else "%.1f%% see-through" % (clear * 100)})
    if facts.get("animated") and fmt not in spec["animated_formats"]:
        failed.append({"rule": "animation", "need": "a still picture", "got": "animated"})
    w, h = facts["w"], facts["h"]
    aw, ah = spec["aspect"]
    want, tol = aw / ah, spec["aspect_tolerance"]
    # anything between square and the default's shape, `tol` beyond either edge
    lo, hi = min(1.0, want) * (1 - tol), max(1.0, want) * (1 + tol)
    if h <= 0 or not (lo <= w / h <= hi):
        failed.append({"rule": "aspect", "need": _aspect_words(aw, ah, tol), "got": _ratio_label(w, h)})
    tall = spec["min_axis"] == "height"
    have = h if tall else min(w, h)
    if have < spec["min_px"]:
        unit = " px tall" if tall else " px"
        failed.append({"rule": "size", "need": "at least %d%s" % (spec["min_px"], unit),
                       "got": "%d%s" % (have, unit)})
    return failed


_ROLE_NEED_VERB = {"format": "be", "transparent": "have", "animation": "be", "aspect": "be", "size": "be"}


def role_refusal_text(role_name, failed):
    """The loud refusal, in plain words: the rule and the measured value, ending on the one
    thing the user most needs to hear. One broken rule reads "...must be about square. This one
    is 3:4."; several read as pairs, "...must be about 9:10 (this one is 3:2) and at least 128 px
    (this one is 64 px)."."""
    if len(failed) == 1:
        f = failed[0]
        what = "%s %s. This one is %s." % (_ROLE_NEED_VERB[f["rule"]], f["need"], f["got"])
    else:
        parts, last = [], None
        for f in failed:
            verb = _ROLE_NEED_VERB[f["rule"]]
            parts.append(("" if verb == last else verb + " ") + "%s (this one is %s)" % (f["need"], f["got"]))
            last = verb
        what = ", ".join(parts[:-1]) + " and " + parts[-1] + "."
    return "Refused: the %s must %s Your current art is unchanged." % (role_name, what)


class ImageRefused(Exception):
    """A picture the app turns away in its own plain words (the message IS the sentence to show). It is
    deliberately NOT a ValueError: Pillow raises ValueErrors of its own ("tile cannot extend outside
    image"), and one of those must never pass for a sentence meant for the user."""


_UNREADABLE = "Couldn't read this image."


def webp_declared_size(head):
    """The canvas a WebP's own header declares, as (width, height), read by hand from its first ~30
    bytes; None when `head` is not a WebP at all. Raises ImageRefused when it IS a WebP whose header
    cannot be read: no picture chunk a WebP may start with, or a lossy / lossless header missing its
    start code / signature, or a header cut short.

    WHY BY HAND: libwebp commits the whole declared canvas when Pillow merely OPENS a WebP, so a
    138-byte file claiming 16383 x 16383 costs ~2 GB before any size check Pillow offers has run.
      VP8X (animated, or with alpha / metadata): 24-bit width-1 at offset 24, height-1 at 27.
      VP8  (lossy): after the frame tag and the 9d 01 2a start code, 14-bit width at 26, height at 28.
      VP8L (lossless): after the 0x2f signature, 14-bit width-1 and 14-bit height-1 packed at 21."""
    if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WEBP":
        return None
    kind = head[12:16]
    if kind == b"VP8X" and len(head) >= 30:
        return (int.from_bytes(head[24:27], "little") + 1, int.from_bytes(head[27:30], "little") + 1)
    if kind == b"VP8 " and len(head) >= 30 and head[23:26] == b"\x9d\x01\x2a":
        return (int.from_bytes(head[26:28], "little") & 0x3FFF, int.from_bytes(head[28:30], "little") & 0x3FFF)
    if kind == b"VP8L" and len(head) >= 25 and head[20] == 0x2F:
        bits = int.from_bytes(head[21:25], "little")
        return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
    raise ImageRefused(_UNREADABLE)


def guard_webp_canvas(head, max_side):
    """Refuse, BEFORE anything opens the file, a WebP whose declared canvas is past `max_side` on a
    side (or whose header cannot be read). Pass the file's first 64 bytes or more. One helper for every
    upload that decodes user pictures: the named roles (role_measure) and the banner slots."""
    size = webp_declared_size(head)
    if size is not None and max(size) > max_side:
        raise ImageRefused("That picture is larger than {:,} px on a side.".format(max_side))


def role_measure(raw):
    """Open one picture's bytes and measure it: (facts, rgba) with facts as role_spec_failures reads
    them. A WebP's declared canvas is read from its header first (guard_webp_canvas); the size of
    anything else comes from its header too and is refused past ROLE_MAX_SIDE before a pixel is
    decoded; an animation is refused past its frame and pixel budget before any frame is. Raises
    ImageRefused with the plain-words message when the picture cannot be used at all; anything
    Pillow itself raises becomes the one plain sentence about not being able to read it."""
    import io
    guard_webp_canvas(raw[:64], ROLE_MAX_SIDE)
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw), formats=ROLE_OPEN_FORMATS)
        fmt, (w, h) = im.format, im.size
        if max(w, h) > ROLE_MAX_SIDE:
            raise ImageRefused("That picture is larger than {:,} px on a side.".format(ROLE_MAX_SIDE))
        frames = getattr(im, "n_frames", 1)
        if frames > 1 and (frames > ROLE_MAX_FRAMES or frames * w * h > ROLE_MAX_ANIM_PIXELS):
            raise ImageRefused("That animation is too long or too big.")
        im.load()
        rgba = im.convert("RGBA")
    except ImageRefused:
        raise
    except Exception:                      # noqa: BLE001 -- anything Pillow raises, ValueErrors included
        raise ImageRefused(_UNREADABLE)
    clear = sum(rgba.getchannel("A").histogram()[:128]) / float(w * h)
    return {"format": fmt, "w": w, "h": h, "see_through": clear, "animated": frames > 1}, rgba


_ROLE_KEEP_CHUNKS = (b"VP8X", b"ICCP", b"ANIM", b"ANMF")


def _role_animation_bytes(raw):
    """An accepted animated WebP, ready to store: rebuilt from only the chunks the picture needs (the
    VP8X header, a colour profile, the animation's parameters and its frames), so metadata a sender
    embedded (a camera's EXIF, an editor's XMP) is not served from the sign-in page, with the VP8X
    header no longer claiming it; cut at the end of its RIFF container so nothing appended after the
    picture survives; and every frame decoded once to prove the file is sound. Raises ImageRefused for
    a stream that stops short, has a chunk that overruns, or will not decode."""
    import io
    from PIL import Image
    if raw[:4] != b"RIFF" or raw[8:12] != b"WEBP":
        raise ImageRefused(_UNREADABLE)
    end = 8 + int.from_bytes(raw[4:8], "little")
    if end > len(raw):
        raise ImageRefused(_UNREADABLE)
    body, pos, kept = raw[12:end], 0, []
    while pos + 8 <= len(body):
        fourcc = body[pos:pos + 4]
        size = int.from_bytes(body[pos + 4:pos + 8], "little")
        if pos + 8 + size > len(body):
            raise ImageRefused(_UNREADABLE)
        span = min(8 + size + (size & 1), len(body) - pos)          # a chunk is padded to an even length
        if fourcc in _ROLE_KEEP_CHUNKS:
            kept.append(body[pos:pos + span])
        pos += span
    if not kept or kept[0][:4] != b"VP8X" or len(kept[0]) < 18:
        raise ImageRefused(_UNREADABLE)
    head = bytearray(kept[0])
    head[8] &= ~0x0C & 0xFF                                         # no EXIF (0x08), no XMP (0x04)
    kept[0] = bytes(head)
    data = b"RIFF" + (4 + sum(len(c) for c in kept)).to_bytes(4, "little") + b"WEBP" + b"".join(kept)
    try:
        with Image.open(io.BytesIO(data), formats=("WEBP",)) as im:
            for i in range(getattr(im, "n_frames", 1)):
                im.seek(i)
                im.load()
    except Exception:                      # noqa: BLE001
        raise ImageRefused(_UNREADABLE)
    return data


def _role_coded_rel(slot, key):
    return _public_rel_to_coded(ROLE_SLOTS[slot]["images"][key]["public"])


def _role_override_path(slot, key):
    return branding_root() / _role_coded_rel(slot, key)


def _role_coded_rels():
    """Every role image's CODED rel, lowercased (the filesystem the tree lives on is
    case-insensitive on Windows, so the serve route compares the way the seal does)."""
    return frozenset(_role_coded_rel(slot, key).lower()
                     for slot, role in ROLE_SLOTS.items() for key in role["images"])


_role_decode_memo = {}


def _role_file_decodes(path):
    """Whether an override file on disk still decodes as a picture. Answered once per
    (file, mtime, size): the public /branding/ route asks on every request for these names, and a
    decode per request would be work a stranger on the LAN could schedule. A changed file is a
    new key, so a repaired override is believed at once."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    key = (str(path), st.st_mtime_ns, st.st_size)
    hit = _role_decode_memo.get(key)
    if hit is not None:
        return hit
    try:
        from PIL import Image
        with Image.open(path, formats=ROLE_OPEN_FORMATS) as im:
            im.load()
        ok = True
    except Exception:                      # noqa: BLE001 -- anything undecodable is "unreadable"
        ok = False
    if len(_role_decode_memo) > 128:
        _role_decode_memo.clear()
    _role_decode_memo[key] = ok
    return ok


def branding_roles_payload(out_dir):
    """The Roles section's state for the Branding tab, in the fixed meeting order (the order of
    ROLE_SLOTS): per role its name and where it shows, and per image its own spec, the URL the app
    wears now, whether that is the install's own file, whether that file still decodes (a
    missing or unreadable override is served as the pack's default -- see the /branding/ route
    -- and the row says so), and a URL for the pack's own art so the row can show default
    beside yours. Both /api/branding and /api/panel/summary hand it over, so the two cannot
    disagree."""
    box = _get_container()
    roles = []
    for slot, role in ROLE_SLOTS.items():
        images = []
        for key, img in role["images"].items():
            coded = _public_rel_to_coded(img["public"])
            path = branding_root() / coded
            try:
                yours = path.is_file()
                stamp = path.stat().st_mtime_ns // 1_000_000 if yours else 0
            except OSError:
                yours, stamp = False, 0
            images.append({
                "key": key, "label": img["label"], "url": "/branding/" + img["public"],
                "yours": yours, "unreadable": bool(yours and not _role_file_decodes(path)),
                "v": stamp,
                "default_url": ("/api/branding/role/default/%s/%s" % (slot, key))
                               if box is not None and box.has(coded) else None,
                # the rule THIS image's override must meet (role_image_spec), for the editor to tick
                "spec": dict(role_image_spec(slot, key), see_through_min=ROLE_SEE_THROUGH_MIN),
            })
        roles.append({"slot": slot, "name": role["name"], "where": role["where"], "images": images})
    return roles


def _role_payload(out_dir, slot):
    return next(r for r in branding_roles_payload(out_dir) if r["slot"] == slot)


def branding_role_upload(out_dir, slot, key, upload=None, media_id="", check_only=False):
    """POST /api/branding/slot for a role slot: one picture becomes the install's override of
    one role image. Returns (body, status). Read it top to bottom -- it is the whole path:

      1. take the bytes, from the uploaded file or from the user's own library by media id,
         capped at ROLE_MAX_BYTES;
      2. open the picture and read its size from the HEADER; refuse anything over ROLE_MAX_SIDE a
         side before a pixel is decoded (role_measure);
      3. decode it (first frame), measure format, shape, size, whether it moves and how much of it
         is see-through, and check those against THIS image's spec (role_image_spec) -- a broken
         rule is a 400 that names the rule and the measured value, and NOTHING has been written;
      4. only then write it: a still is re-encoded from the decoded pixels (nothing the sender
         appended survives; the login companion is stored as WebP, every other role as PNG, under
         the public name the app already asks for); the one animation a role allows (the login
         companion's WebP) is decoded frame by frame and stored as sent, cut at its container's end
         (_role_animation_bytes). The override file is replaced whole.

    `check_only` stops after step 3 and answers with the measurements ({"facts": ...}) instead of
    judging them: that is how a picture already in the library ("From the gallery") gets its rules
    ticked in the editor before Use this, with the same numbers the client's rules read. It never
    writes.

    The pack is read-only here: the file lands in the coded tree, where loose beats the pack."""
    import io
    role = ROLE_SLOTS[slot]
    img = role["images"].get(key)
    if img is None:
        return {"error": "unknown image"}, 400
    if upload is not None and getattr(upload, "filename", ""):
        raw = upload.stream.read(ROLE_MAX_BYTES + 1)
    elif media_id:
        hit = next((p for p in _scan.find_files_for_media_id(out_dir, media_id)
                    if p.suffix.lower() in _scan._IMAGE_EXTS), None)
        if hit is None:
            return {"error": "no local image for that media id"}, 400
        try:
            if hit.stat().st_size > ROLE_MAX_BYTES:
                return {"error": "That file is too large."}, 400
            raw = hit.read_bytes()
        except OSError:
            return {"error": _UNREADABLE}, 400
    else:
        return {"error": "no file"}, 400
    if len(raw) > ROLE_MAX_BYTES:
        return {"error": "That file is too large."}, 400
    try:
        facts, rgba = role_measure(raw)
    except ImageRefused as exc:
        return {"error": str(exc)}, 400
    if check_only:
        return {"facts": facts}, 200
    failed = role_spec_failures(role_image_spec(slot, key), facts)
    if failed:
        return {"error": role_refusal_text(role["name"], failed), "failed": failed}, 400
    buf = io.BytesIO()
    if facts["animated"]:
        try:
            buf.write(_role_animation_bytes(raw))
        except ImageRefused as exc:
            return {"error": str(exc)}, 400
    elif img["public"].lower().endswith(".webp"):
        rgba.save(buf, "WEBP", lossless=True, quality=100, method=4)
    else:
        rgba.save(buf, "PNG", optimize=True)
    path = _role_override_path(slot, key)
    tmp = path.with_name("%s.%s.tmp" % (path.name, secrets.token_hex(4)))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(buf.getvalue())
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return {"error": "Couldn't save that file. Your current art is unchanged."}, 500
    _baseline_note_app_write(out_dir, _role_coded_rel(slot, key))
    return {"slot": slot, "key": key, "role": _role_payload(out_dir, slot)}, 200


def branding_role_restore(out_dir, slot, key):
    """POST /api/branding/role/restore: remove the install's override of one role image, so the
    pack's default answers again. Returns (body, status). It unlinks ONE file under the coded
    tree and nothing else; the pack (the container) is never opened for writing, and removing
    an override that is not there is a quiet {"removed": false}, never an error.

    It refuses (409) when the pack holds no default for that image: then the file under the coded
    tree is the only copy of that art (the legacy branding migration moved an old install's loose
    files into these very paths, and the art pack may be absent), and deleting it would leave the
    role with nothing at all."""
    if key not in ROLE_SLOTS[slot]["images"]:
        return {"error": "unknown image"}, 400
    path = _role_override_path(slot, key)
    removed = False
    try:
        if path.is_file():
            box = _get_container()
            if box is None or not box.has(_role_coded_rel(slot, key)):
                return {"error": "There's no default to go back to, so your file is kept."}, 409
            path.unlink()
            removed = True
    except OSError:
        return {"error": "Couldn't remove your file."}, 409
    return {"slot": slot, "key": key, "removed": removed, "role": _role_payload(out_dir, slot)}, 200


# The raw-drop path (moonglade-internal/DECISIONS.md, 2026-07-26, owner-confirmed 2026-08-05):
# a fresh install ships the branding slot folders EMPTY, and a raw PNG/JPEG
# placed by hand into one of the four adopt folders is ADOPTED into that slot by
# the app itself -- no marks.json to hand-author, no upload UI, no authenticated
# request. That is the point: the Branding tab's own upload API is gated, so a
# drop has to be picked up by scanning the filesystem rather than by extending
# the authenticated upload routes above.
# Fallback README text ONLY (container absent): the real README content is a
# SEALED asset materialized by ensure_branding_discovery_tree and deliberately
# kept out of this public source.
_BRANDING_README = "Maybe something goes in here.\n"
# The folders the app creates at startup, so an install has somewhere to put
# art. mascots/rewards are listed EXPLICITLY even though they are no longer
# BRANDING_SLOTS (the 2026-08-13 unlock-split enforcement): existing installs
# already have them, so the on-disk tree keeps the same six roles (now coded). A
# drop in either is DETECTED and nothing else -- the wide read-only scan raises
# the branding_custom_file flag (2026-09-10), while adoption stays narrow
# (_SWEEPABLE_SLOTS + marks), so the role-bound files those two folders hold are
# read but never consumed.
_BRANDING_DISCOVERY_SLOTS = BANNER_SLOTS + ("mascots", "rewards", "marks")


def _migrate_legacy_branding_root():
    """One-time move of an existing install's OLD role-named `branding/` tree
    into the coded goods tree (bundle-v2, SCOPE_bundle-v2-contract.md section
    5). MOVE only, NEVER delete -- renaming the root would otherwise orphan
    every real upload an existing install has (custom marks, banner slots, the
    rendered flats). Rules:

      - the six role folders' files -> their coded dirs (recursive, so the old
        mascots/ach/ nesting lands under the coded ach folder too);
      - old top-level loose files route through _public_rel_to_coded: the
        three banner flats land top-level at the coded root, system files /
        ee_* land in their coded homes (leaving them at the coded top would
        strand a working override where the resolver no longer looks). The
        flats do not STAY at the root: _migrate_root_banner_flats(), which a
        real server start (main()) runs immediately after this, moves them on
        into the banner cache (2026-09-10 -- renders live outside the tree
        now). Two separate migrations on purpose: this one is legacy-tree-
        shaped, additive-or-move-only and safe to run from create_app(); that
        one is cache-shaped, needs an out_dir, and is destructive to the tree,
        so it stays out of app construction;
      - anything unrecognized STAYS PUT (flag-to-owner territory, per the
        standing stray-copy rule), and a destination that already exists is
        never overwritten -- the source stays put and is logged;
      - emptied old folders are removed; the old root goes only if COMPLETELY
        empty. One log line per move via the standard logger.

    A no-op on fresh installs (no old root at all)."""
    import logging as _logging
    import shutil
    old = branding_root().parent / "branding"
    if not old.is_dir():
        return
    log = _logging.getLogger(__name__)

    def _move(src, dst):
        if dst.exists():
            log.warning("branding migration: NOT moving %s (destination %s already exists)",
                        src, dst)
            return
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            log.info("branding migration: moved %s -> %s", src, dst)
        except OSError:
            log.warning("branding migration: failed to move %s -> %s",
                        src, dst, exc_info=True)

    for role in ("banner_main", "banner_login", "banner_loom",
                 "marks", "mascots", "rewards"):
        src_dir = old / role
        if not src_dir.is_dir():
            continue
        for p in sorted(src_dir.rglob("*")):
            if p.is_file():
                _move(p, _role_dir(role) / p.relative_to(src_dir))
    try:
        top = sorted(old.iterdir())
    except OSError:
        top = []
    for p in top:
        if not p.is_file():
            continue
        coded = _public_rel_to_coded(p.name)
        if p.name in _BANNER_FLAT.values() or coded != p.name:
            _move(p, branding_root() / coded)
        # else: unrecognized (the old README.txt, stray notes) -- stays put.
    # Sweep away what emptied, deepest-first; rmdir refuses anything non-empty,
    # which is exactly the "removed only if left completely empty" contract.
    for d in sorted((q for q in old.rglob("*") if q.is_dir()), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    try:
        old.rmdir()
    except OSError:
        pass
    # Anything left behind was unrecognized (not a role folder, not a flat/system
    # /ee_ file) so it stayed put by design -- but surface it rather than let it
    # 404 silently, so the owner can move a stray by hand. (Re-logs each start
    # while the leftover remains; that is a persistent, accurate nudge.)
    if old.is_dir():
        leftovers = [str(p.relative_to(old)) for p in old.rglob("*") if p.is_file()]
        if leftovers:
            log.warning("branding migration: %d file(s) left unmigrated in the old "
                        "branding/ folder (unrecognized -- move by hand if wanted): %s",
                        len(leftovers), ", ".join(sorted(leftovers)[:20]))


def ensure_branding_discovery_tree():
    """Create the empty, coded slot folders + the one GONK folder's README, so a
    fresh install has the tree on disk. Idempotent and additive only -- never
    touches a folder or file that already exists, so it is safe to call on every
    server start regardless of what's already on disk (the owner's own real
    tree, a returning install with real uploads, ...). Runs the one-time legacy
    migration first so an old install's real files land in the coded dirs before
    the empties go down. The README's content is materialized from the SEALED
    asset (it never appears in this public source); a container-less install
    gets the plain one-liner. The old root-level README is no longer written.

    Called at STARTUP, never per-request, and from TWO places: create_app()
    runs it, and main() runs it again itself immediately before
    _migrate_root_banner_flats() -- which is what lets an ancient install's
    legacy flats land at the coded root and be moved on within the same
    start."""
    _migrate_legacy_branding_root()
    for slot in _BRANDING_DISCOVERY_SLOTS:
        _role_dir(slot).mkdir(parents=True, exist_ok=True)
    crumb_dir = _role_dir("breadcrumb")
    readme = crumb_dir / "README.txt"
    if not readme.exists():
        try:
            crumb_dir.mkdir(parents=True, exist_ok=True)
            raw = _branding_bytes(_role_rel("breadcrumb", "README.txt"))
            if raw is not None:
                readme.write_bytes(raw)
            else:
                readme.write_text(_BRANDING_README, encoding="utf-8")
        except OSError:
            pass


def _migrate_root_banner_flats(out_dir):
    """One-time MOVE of any rendered banner flat still sitting at the coded
    root into banner_cache_dir() (2026-09-10 owner ruling: renders leave the
    tree; afterwards the root holds nothing the app wrote). Idempotent and a
    no-op once the root holds no flats, so it is safe on every start.

    Called from main() only -- NOT from create_app(). This is the one startup
    step that writes destructively to the coded tree, and create_app() is built
    by ~every test in the suite, several of them from module-scoped fixtures
    that conftest's per-test branding isolation cannot reach; running it there
    would relocate the owner's own dressed banner into a pytest tmp dir on a
    plain test run. main() is the one caller that knows this is a real server
    start with this install's real out_dir, and it runs the (additive,
    idempotent) ensure_branding_discovery_tree() itself immediately before this
    call, so an ancient install's legacy flats land at the coded root and are
    moved on within the SAME start.

    MOVE, never delete: the flat IS the banner an existing install is currently
    wearing, and re-rendering it needs the active asset, which may only exist
    inside the container. It is the only copy, so it goes to banner_keep_dir()
    (local/banners/), never into a cache, and settings.json's worn_banner says the
    slot wears it ({"kind": "migrated"}) -- which is what makes the move stick: the
    create_app ensure pass that runs moments later leaves a migrated banner alone.
    Only an explicit upload, pick, crop or apply-earned replaces it. A slot that
    already wears something else, or a kept copy already there, is the newer truth
    and wins -- the stale root leftover is left where it is and logged, exactly
    the never-overwrite rule _migrate_legacy_branding_root() holds."""
    import logging as _logging
    import shutil
    root = branding_root()
    dst_dir = banner_keep_dir()
    log = _logging.getLogger(__name__)
    for slot, name in _BANNER_FLAT.items():
        src = root / name
        try:
            if not src.is_file():
                continue
        except OSError:
            continue
        dst = dst_dir / name
        if dst.exists() or _worn_banner(slot) is not None:
            log.warning("banner flat migration: NOT moving %s (the slot already wears "
                        "another banner)", src)
            continue
        try:
            dst_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            _set_worn_banner(slot, {"kind": "migrated"})
            log.info("banner flat migration: moved %s -> %s", src, dst)
        except OSError:
            log.warning("banner flat migration: failed to move %s -> %s",
                        src, dst, exc_info=True)


def _is_readable_image(path):
    """True when Pillow can open `path` as an image at all. The validation half of
    the verbatim-webp path: the bytes are passed through untouched, so this is what
    stops a renamed .txt (or anything else) from being adopted as a mark."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
        return True
    except Exception:                       # noqa: BLE001 -- any failure means "not an image"
        return False


# How deep the read-only detection walk below descends. The deepest SHIPPED
# coded folder is four segments from the root (ROLE_CODE's enhance/emotion under
# bridge, and the GONK folder under starfall), so six leaves two levels of
# user-made nesting inside the cap and still bounds the cost on a per-request path.
_BRANDING_WALK_MAX_DEPTH = 6


# The baselines[] entry this install's coded-tree snapshot is stored under, and
# how much of each file goes into a fingerprint. 64 KiB carries a whole image
# header plus a real slab of pixel data for anything this tree holds, costs one
# or two reads off the page cache, and is BOUNDED -- a fingerprint whose cost
# scaled with file size would put a multi-megabyte mascot on a per-request path.
_BASELINE_GOODS = "goods_tree"
_BASELINE_HEAD = 64 * 1024
# How recently a file may have been written and still be trusted to the
# in-process clean memo below. Windows' file-time clock ticks about every
# 15.6 ms, so two writes inside one tick can share an mtime to the nanosecond;
# two seconds is three orders of magnitude clear of that.
_BASELINE_SETTLE_NS = 2_000_000_000
# Per-process memo of "this exact file was compared against the baseline and was
# a default": {(out_dir, baseline key) -> frozenset of (rel, size, mtime_ns)}.
# Small on purpose -- one entry per library/app-folder pairing a single process
# ever scans -- and cleared wholesale rather than evicted, because a rebuilt memo
# costs one scan and a clever eviction costs a bug.
_BASELINE_CLEAN_MEMO = {}
_BASELINE_CLEAN_MEMO_MAX = 8


def _branding_tree_files():
    """Yield (coded rel, os.DirEntry) for every FILE in the coded tree -- ONE
    walk definition, shared by the baseline snapshot and the read-only scan that
    compares against it, so a file the scan can reach is a file the baseline
    recorded and vice versa.

    Two boundaries, both of them the tree's own rules rather than tuning knobs:

      - the coded ROOT's own top-level files are skipped. The app writes nothing
        there (renders live in banner_cache_dir()) and the serve route never
        reads it, so a file parked at the root is neither counted nor served --
        the FOLDERS are what this tree is for.
      - the walk descends to _BRANDING_WALK_MAX_DEPTH and no further. Anything
        past the cap is outside the tree's vocabulary in BOTH directions:
        invisible to the baseline and invisible to the scan, which is the only
        arrangement in which the cap itself cannot manufacture a difference.

    An unreadable directory yields nothing rather than raising -- a permissions
    oddity in one corner must not take a page render down."""
    pending = [(branding_root(), "", 0)]
    while pending:
        d, prefix, depth = pending.pop()
        try:
            with os.scandir(d) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:                     # unreadable dir -> nothing to see, not a crash
            continue
        for e in entries:
            try:
                if e.is_dir():
                    if depth < _BRANDING_WALK_MAX_DEPTH:
                        pending.append((Path(e.path), prefix + e.name + "/", depth + 1))
                    continue
                if depth == 0 or not e.is_file():
                    continue                # the root's own files never count
            except OSError:
                continue
            yield prefix + e.name, e


def _file_fingerprint(path):
    """[size, sha256 of the first _BASELINE_HEAD bytes] for one file, or None if
    it cannot be read. Size ALONE would miss a same-size overwrite, and that is
    the case this has to catch: the owner dropping his own art under a shipped
    asset's exact filename is the loose-wins override, not a default."""
    import hashlib
    try:
        size = os.stat(path).st_size
        with open(path, "rb") as fh:
            head = fh.read(_BASELINE_HEAD)
    except OSError:
        return None
    return [int(size), hashlib.sha256(head).hexdigest()]


def _baseline_key():
    """The baselines[] key a coded-tree snapshot is stored under: the goods-tree
    name PLUS the identity of the tree it describes.

    The two halves of this mechanism hang off DIFFERENT folders. The snapshot
    lives in the LIBRARY's telemetry (out_dir); the tree it describes is the APP
    folder's (branding_root(), beside the launcher). branding_root() was moved
    out of out_dir in 2026-07-26 precisely because the two are independent, and
    _ensure_banner_flat() already handles the same split for renders -- but a
    single shared snapshot key would ignore it here. Point a second checkout at
    the same library (the D: run-copy, a worktree, a branch tried out live) and
    that library's one snapshot would describe a tree this install has never
    seen: every file in it missing from the record, every file therefore "new",
    and the flag raised on the first fetch with no user action at all.

    So the pairing is part of the key: a library remembers one snapshot per app
    folder it has been pointed at, and a tree is only ever compared against a
    snapshot of ITSELF. A never-seen pairing takes its own first snapshot and
    reports nothing, exactly like a fresh install.

    Hashed rather than spelled out: the path is normalised for case first so
    Windows' several spellings of one folder agree, and a telemetry dump has no
    need to carry a filesystem path in the clear."""
    import hashlib
    p = os.path.normcase(str(branding_root()))
    return "%s@%s" % (_BASELINE_GOODS,
                      hashlib.sha256(p.encode("utf-8", "replace")).hexdigest()[:16])


def _branding_baseline(out_dir, telem=None):
    """This library's recorded snapshot of THIS app folder's coded tree (see
    _baseline_key), or None when that pairing has never taken one.

    None and {} are deliberately DIFFERENT answers. An empty dict is the correct
    record for a tree that held nothing when the snapshot was taken (a fresh
    install), and it is exactly what makes the first later drop count; None means
    nobody has looked yet, and the next look records rather than judges."""
    d = _telemetry.load_telemetry(out_dir) if telem is None else telem
    base = (d.get("baselines") or {}).get(_baseline_key())
    return base if isinstance(base, dict) else None


def _record_branding_baseline(out_dir):
    """Take the snapshot: every file the walk can reach, fingerprinted, stored in
    the library's telemetry beside flags and sets, under this library-and-app-
    folder pairing's own key. Once per pairing, on that pairing's first scan --
    which is why that scan reports nothing.

    EVERY file the walk reaches is recorded, including one whose bytes could not
    be read when the snapshot was taken (locked by another process, a
    permissions corner). Such a file is stored with its size and a NULL hash
    rather than dropped, because dropping it is wrong in both directions: an
    absent rel counts as new forever -- a permanent false positive on a file that
    was always there -- while pretending it is fine forever would be a permanent
    blind spot. Size alone is what the snapshot honestly knows, so that is what
    it stores, and the comparison honours it exactly: a later file at that rel
    with the same size is the file that was already there (readable or not), and
    a different size is a real change and counts. A stat that fails too leaves
    the rel recorded with nothing known, which the comparison reads as changed --
    and the scan cannot stat such a file either, so it never reaches judgement."""
    snap = {}
    for rel, e in _branding_tree_files():
        fp = _file_fingerprint(e.path)
        if fp is None:
            try:
                fp = [int(e.stat().st_size), None]
            except (OSError, TypeError, ValueError):
                fp = [None, None]
        snap[rel] = fp

    def _store(d):
        d.setdefault("baselines", {})[_baseline_key()] = snap
    _telemetry._telem_mutate(out_dir, _store)
    return snap


def _baseline_note_app_write(out_dir, rel):
    """Fold ONE file the app itself just wrote INTO the tree into the standing
    baseline, so it reads as a default from the moment it exists.

    Its callers are exactly the paths that still REGISTER an asset into the
    tree: add_slot_asset() (`<id>.png` into a banner slot, every Branding-tab
    upload), _adopt_mark() (`<id>.png|.webp` into marks) and add_custom_mark()
    (the custom mark plus the launcher .ico cut beside it -- Pillow reads an
    .ico, so an unrecorded one would raise the flag). Everything else the app
    writes now lands outside the tree (banner_cache_dir(), badge_cache_dir()),
    and grep for this function's name is the live list.

    A no-op before the first snapshot exists -- with no baseline yet, the next
    scan is about to sweep this file up anyway."""
    if _branding_baseline(out_dir) is None:
        return
    fp = _file_fingerprint(branding_root() / rel)
    if fp is None:
        return

    def _note(d):
        cur = d.setdefault("baselines", {}).get(_baseline_key())
        if isinstance(cur, dict):
            cur[rel] = fp
    _telemetry._telem_mutate(out_dir, _note)


def _branding_tree_has_new_art(out_dir):
    """True when the coded tree holds a readable image the baseline does not
    account for. ONE detector, two callers: sweep_branding_drops() on every
    /api/achievements fetch, and sweep_telemetry()'s once-a-day backstop.

    STRICTLY READ-ONLY over the whole tree. It never unlinks, renames,
    re-encodes, moves or registers anything, at any depth, in any folder --
    including the four that sweep_branding_drops() does adopt from. That is what
    keeps the 2026-08-05 near-miss dead: mascots/ and rewards/ hold role-bound
    files real code reads by exact filename, and being SEEN cannot consume them.

    Why a BASELINE rather than a list of what the app ships. Every regression
    this check has had was the same one -- something that was always on disk got
    counted as somebody's drop -- and every attempt to enumerate the app's own
    art failed at one end or the other. Comparing a candidate against the
    shipped container fails OPEN on an install that HAS no container (a legacy
    tree's art left loose then counts on every upgrade) and fails CLOSED on the
    owner's own override (his bytes under a shipped asset's name are still
    "shipped"). A snapshot asks a question with no such gap: what was here
    before anyone looked? Everything else is new.

    So the first call on a pairing RECORDS and reports nothing, and from then on
    a file counts when its coded rel is absent from the snapshot, or when the
    bytes at a recorded rel have changed -- the override case, and the reason a
    candidate can never be dismissed on its path alone.

    WHAT IT COSTS, precisely, because this runs on every /api/achievements fetch
    until the flag is set. Deciding "same path, same bytes" needs the bytes: an
    UNCHANGED baseline file is same-size by definition, so a full comparison
    reads and hashes 64 KiB of every file in the tree -- and an upgraded install
    can carry a hundred of them in a legacy _thumbs cache. So the answer is
    memoised per process: a file compared and found to be a default is
    remembered as (rel, size, mtime_ns), and a later scan that finds the same
    triple skips straight past it. The first scan of a process pays the reads;
    every scan after it pays the walk's own stats, plus -- every single call,
    memo or no memo -- the one read-and-JSON-parse of the telemetry store that
    fetching the baseline costs (_branding_baseline -> load_telemetry). That
    parse is why the callers guard this on the flag not already being set.

    The memo trusts an mtime, so it deliberately does NOT trust a fresh one: a
    file written within _BASELINE_SETTLE_NS of the scan is left out of the memo
    and re-read next time, which closes the one window where a coarse filesystem
    clock could hand a changed file its predecessor's timestamp. Nothing here
    touches the persisted baseline, so a change the memo could ever miss inside
    one process is still caught by the full comparison the next start runs.

    Cheapest test first within a file, too: the memo lookup, then a dict lookup,
    then a size compare off the walk's own stat, so only a same-size unmemoised
    candidate pays a read; the Pillow decode is last. First hit wins and the walk
    stops there."""
    import time
    base = _branding_baseline(out_dir)
    if base is None:
        _record_branding_baseline(out_dir)
        return False
    memo_key = (str(out_dir), _baseline_key())
    was_clean = _BASELINE_CLEAN_MEMO.get(memo_key) or frozenset()
    now = time.time_ns()
    clean = []
    for rel, e in _branding_tree_files():
        try:
            st = e.stat()
            stamp = (rel, int(st.st_size), int(st.st_mtime_ns))
        except (OSError, TypeError, ValueError):
            continue                        # unreadable now -> nothing to judge
        if stamp in was_clean:
            clean.append(stamp)
            continue                        # already compared, byte for byte, this process
        known = base.get(rel)
        if isinstance(known, list) and len(known) == 2:
            try:
                same_size = stamp[1] == int(known[0])
            except (TypeError, ValueError):
                same_size = False
            if same_size:
                # A NULL hash is the snapshot saying it could not read this file
                # when it looked: size is the whole of what it knows, so a
                # same-size file at that rel is the file it recorded, and there
                # is nothing to compare bytes against.
                fp = None if known[1] is None else _file_fingerprint(e.path)
                if fp is None or fp[1] == known[1]:
                    if now - stamp[2] > _BASELINE_SETTLE_NS:
                        clean.append(stamp)
                    continue                # same path, same bytes -> a default
        if _is_readable_image(Path(e.path)):
            _BASELINE_CLEAN_MEMO.pop(memo_key, None)
            return True
        if now - stamp[2] > _BASELINE_SETTLE_NS:
            clean.append(stamp)             # not art, and not art again next time
    if memo_key not in _BASELINE_CLEAN_MEMO and len(_BASELINE_CLEAN_MEMO) >= _BASELINE_CLEAN_MEMO_MAX:
        _BASELINE_CLEAN_MEMO.clear()
    _BASELINE_CLEAN_MEMO[memo_key] = frozenset(clean)
    return False


def _adopt_dropped_file(path):
    """Re-encode a raw dropped image (PNG/JPEG/anything Pillow can read) into
    real PNG bytes, or None if it isn't a readable image at all -- the same
    defense-in-depth the authenticated upload route above applies, just
    against a file that arrived by hand instead of by POST."""
    try:
        from PIL import Image
        import io
        im = Image.open(path)
        im.load()
        buf = io.BytesIO()
        im.convert("RGBA").save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _adopt_mark(out_dir, raw_stem, art_bytes, ext=".png"):
    """Register a raw dropped file into marks.json + write its art, then make it
    the active mark -- the marks-folder half of sweep_branding_drops()'s
    auto-adopt (marks predate BRANDING_SLOTS and keep their own established
    list_marks()/marks.json shape rather than being folded into the newer
    per-slot manifest convention).

    `ext` is .png for anything re-encoded on the way in, .webp for a dropped webp
    kept verbatim -- see the sweep, which is where that decision is made."""
    mdir = _role_dir("marks")
    mid = re.sub(r"[^a-z0-9_-]+", "-", raw_stem.lower()).strip("-")[:40] or "custom"
    # Tombstoned ids count as taken: adopting a drop AS a tombstoned id would
    # register a mark list_marks() then refuses to show.
    have = {m["id"] for m in list_marks(out_dir)} | set(_MARK_TOMBSTONES)
    if mid in have:
        mid = (mid + "-" + secrets.token_hex(3))[:40]
    _seed_loose_manifest(_role_rel("marks", "marks.json"))   # keep shipped defaults in the picker
    try:
        data = json.loads((mdir / "marks.json").read_text(encoding="utf-8"))
        marks = list(data.get("marks") or []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        marks = []
    marks.append({"id": mid, "label": mid.replace("-", " "), "kind": "tile"})
    (mdir / "marks.json").write_text(json.dumps({"marks": marks}, indent=2), encoding="utf-8")
    (mdir / (mid + ext)).write_bytes(art_bytes)
    # Same reason as add_slot_asset's own note: the art this just registered is
    # the app's own write from here on, not a standing flag.
    _baseline_note_app_write(out_dir, _role_rel("marks", mid + ext))
    cfg = load_branding(out_dir)
    cfg["mark"] = mid
    save_branding(out_dir, cfg)


# SAFETY, 2026-08-05: mascots/ and rewards/ are NOT empty user-customizable
# buckets -- they already hold a family of specifically-named, role-bound
# files real shipped code reads by exact filename (the narrator/login/power-
# modal mascots, the claim icon, and a per-achievement ach/<id>.png chain that
# has no fixed, enumerable list). The original version of this sweep had no
# awareness of that and would have adopted-then-DELETED every one of those
# files the first time it ran against an install that actually has them --
# caught before it ever ran against real assets, but only just. Until
# mascots/rewards get a real design (named-role overrides, most likely, not
# a manifest-of-many-pick-one-active gallery like the other two slots), the
# sweep only ever touches the slots that map cleanly onto a real,
# already-established single displayed flat: banner_main -> banner.png,
# banner_login -> login-banner.png, banner_loom -> banner-loom.png (WIRED to
# write those exact files as of 2026-08-06 -- see _write_banner_flat below;
# owner call: "Yes, seems obvious"). Those three RENDERS live in
# banner_cache_dir() since 2026-09-10, not at the coded root -- the flat is
# derived per-install state, and the tree holds slot folders and nothing else.
#
# 2026-09-10 (owner ruling), the one thing that DID change: mascots/ and
# rewards/ -- and every other folder under the coded root, at any depth -- are
# now READ by _branding_tree_has_new_art(), which raises the
# branding_custom_file telemetry flag when it sees an image the install's
# baseline does not account for. Reading is not adopting. This note's substance
# is untouched: nothing outside the four adopt folders below (these three slots
# + marks) is ever unlinked, renamed, re-encoded, moved or registered, so the
# family of role-bound files above still cannot be eaten.
_SWEEPABLE_SLOTS = ("banner_main", "banner_login", "banner_loom")

# The flat files the header/login/Loom templates read directly (the header's
# <img src="/branding/banner.png">, the login page's login-banner.png, and the
# Loom's workspace strip). The slot system stores MANY assets; these flats are
# the ONE the app displays -- so every path that changes which asset is active
# (upload, pick-active, re-crop the active one, a raw drop the sweep adopts)
# re-renders its slot's flat.
_BANNER_FLAT = {"banner_main": "banner.png", "banner_login": "login-banner.png",
                "banner_loom": "banner-loom.png"}
# The SHIPPED default banner per slot -- a sealed container asset inside the
# slot's own coded folder, served only when no loose flat exists (bundle-v2:
# the coded tree ships real default banners; the old repo tree shipped the
# slots empty, so brand_context's flat-only check left a fresh install bare).
# Filenames as the tree actually carries them -- banner_loom's is hyphenated.
_BANNER_FLAT_DEFAULT = {"banner_main": "banner_main.png",
                        "banner_login": "banner_login.png",
                        "banner_loom": "banner-loom.png"}


def _flat_default_rel(slot):
    """Coded rel of one slot's shipped default banner (the rule-8 fallback)."""
    return _role_rel(slot, _BANNER_FLAT_DEFAULT[slot])


def banner_cache_dir(out_dir=None):
    """Where the RENDERED banner flats live: local/cache/banners/. A sibling of
    badge_cache_dir()'s badges/, for exactly its reasons: these files are rebuildable --
    a slot render from the slot's pick, an earned render from the pack -- and derived from
    this install's picks, not from any library, so they live with the install.

    Moved OUT of the coded goods root on 2026-09-10 (owner ruling). The tree now holds slot
    folders and nothing else: the root is empty and inert, the app writes nothing there and
    serves nothing from there, and a file dropped at the root is neither served nor
    overwritten by the next re-render. A render that is the ONLY copy of what the install
    wears (one migrated from an early version's root) is not a cache and lives in
    banner_keep_dir() instead (B6). (`out_dir` is accepted and unused.)"""
    return _paths.cache_dir() / "banners"


def banner_keep_dir():
    """local/banners/: banner renders that are the only copy of what this install wears (moved
    in from an early version's art-tree root, or a render with no record). Never regenerated,
    never in a cache; settings.json's branding.worn_banner says a slot wears one (B6)."""
    return _paths.banners_dir()


# The earned banners, by id, and the achievement each one is gated on.
_EARNED_BANNERS = {"great_library": "the-great-library"}


def _served_flat_dir(out_dir, slot):
    """The folder `slot`'s flat is served from: banner_keep_dir() while the slot wears an only
    copy (a migrated banner, or a kind this build does not know), else the render cache."""
    worn = _worn_banner(slot)
    if worn is not None and worn.get("kind") != "earned":
        return banner_keep_dir()
    return banner_cache_dir(out_dir)


def _worn_banner(slot):
    """What `slot` wears beyond its own pick, from settings.json's branding.worn_banner:
    {"kind": "earned", "banner_id": ...} (applied from the pack), {"kind": "migrated"} (the
    only copy, in banner_keep_dir()), or None (the slot's own pick)."""
    worn = _settings.branding().get("worn_banner")
    v = worn.get(slot) if isinstance(worn, dict) else None
    return v if isinstance(v, dict) and v.get("kind") else None


def _set_worn_banner(slot, value):
    """Store (or with None clear) what `slot` wears beyond its pick. Fail-soft: a choice that
    cannot be saved costs the choice, never a request."""
    def _apply(b):
        worn = b.get("worn_banner") if isinstance(b.get("worn_banner"), dict) else {}
        if value is None:
            worn.pop(slot, None)
        else:
            worn[slot] = value
        if worn:
            b["worn_banner"] = worn
        else:
            b.pop("worn_banner", None)
    try:
        _settings.update_branding(_apply)
        return True
    except (OSError, _settings.SettingsBusy):
        return False


# The output aspect each banner flat is cropped to (width / height). banner_loom
# is the 12:1 workspace strip added with the Branding-tab rebuild.
_BANNER_RATIO = {"banner_main": 4.0, "banner_login": 4.0, "banner_loom": 12.0}
# Canonical output pixel size per slot (the DC's own spec strings: 1920x480,
# 1920x160). The saved flat is resized to this so downstream CSS never upsamples
# an oddly-sized source.
_BANNER_OUT = {"banner_main": (1920, 480), "banner_login": (1920, 480),
               "banner_loom": (1920, 160)}


def _banner_window(w, h, target_ar, zoom, cropx, cropy):
    """The source-pixel crop box that reproduces the design's live preview EXACTLY
    (Control Panel.dc.html:953): an object-fit:cover image with
    `object-position: cropX% cropY%`, `transform: scale(zoom/100)`,
    `transform-origin: cropX% cropY%`. WYSIWYG matters here -- the owner tunes the
    sliders watching that preview, so the flat must match it, not merely approximate.

    Derivation: model a display frame of the target aspect, replicate the CSS
    (cover-fit, then object-position, then the scale about the crop-origin), and map
    the frame's four corners back into source-pixel space; their bounding rectangle
    is the visible window. Returns (left, top, right, bottom) clamped to the source.
    """
    z = max(1.0, zoom / 100.0)
    px, py = cropx / 100.0, cropy / 100.0
    # A frame of the target aspect, sized in the source's own units (height = h) so
    # the cover math stays in familiar pixels; only the ratio matters.
    FH = float(h)
    FW = target_ar * FH
    sc = max(FW / w, FH / h)                      # object-fit: cover
    disp_w, disp_h = w * sc, h * sc
    over_x, over_y = disp_w - FW, disp_h - FH     # >= 0
    img_l, img_t = -px * over_x, -py * over_y     # object-position placement
    ox, oy = px * FW, py * FH                     # transform-origin in frame coords

    def src(fx, fy):
        # undo scale(z) about (ox,oy), then undo cover placement -> source px
        qx = ox + (fx - ox) / z
        qy = oy + (fy - oy) / z
        return (qx - img_l) / sc, (qy - img_t) / sc

    corners = [src(0, 0), src(FW, 0), src(0, FH), src(FW, FH)]
    xs = [c[0] for c in corners]; ys = [c[1] for c in corners]
    l, t, r, b = min(xs), min(ys), max(xs), max(ys)
    # clamp into the source, then re-fit the exact target aspect inside the clamp so
    # the saved file's aspect is precise even at an edge-panned extreme.
    l, t = max(0.0, l), max(0.0, t)
    r, b = min(float(w), r), min(float(h), b)
    cw, ch = r - l, b - t
    if cw <= 0 or ch <= 0:
        return (0, 0, w, h)
    if cw / ch > target_ar:                       # too wide -> trim width, keep centre
        nw = ch * target_ar; l += (cw - nw) / 2; r = l + nw
    else:                                         # too tall -> trim height
        nh = cw / target_ar; t += (ch - nh) / 2; b = t + nh
    # Size-preserving integer rounding: round the origin, derive the far edge from the
    # SIZE (min 1px). Rounding all four edges independently can collapse a sub-pixel-
    # tall box to zero height (round(1.5)=2 and round(2.5)=2 under banker's rounding),
    # which made Pillow produce an empty crop for small sources.
    li, ti = int(round(l)), int(round(t))
    wi = max(1, int(round(r - l))); hi = max(1, int(round(b - t)))
    li = max(0, min(li, w - wi)); ti = max(0, min(ti, h - hi))
    return (li, ti, li + wi, ti + hi)


# ---------------------------------------------------------------------------
# What the banner cache holds, and why it holds a RECORD beside every render.
#
# banner_cache_dir() carries the three rendered flats the header/login/Loom
# templates display, and beside each one a sidecar `<name>.json` naming where
# that render CAME FROM. Three kinds, and they are not interchangeable:
#
#   {"kind": "slot", "asset_id": ..., "transform": {...}}
#       rendered from a banner slot's active pick at that pick's stored
#       zoom/cropX/cropY. The ONLY kind anything is allowed to regenerate, and
#       only when the pick or the transform no longer matches what is recorded.
#   {"kind": "earned", "banner_id": ...}
#       applied from sealed container bytes by the earned-banner route, with no
#       slot pick behind it at all.
#   {"kind": "migrated"}
#       moved in from a pre-2026-09-10 install's coded root. The bytes are the
#       banner that install is WEARING and there may be nothing left to
#       re-render them from.
#
# The record exists because the cache used to decide staleness by MTIME against
# the shared branding_slots.json, and that is not a provenance: every slot's
# flat went stale when any slot's pick changed, and an applied earned banner or
# a just-migrated flat was silently re-rendered back to the slot's pick on the
# next request. A render whose record is absent or unreadable is treated as
# opaque and left alone for the same reason -- the file is what the install is
# wearing, and nothing here knows better than it does.
# ---------------------------------------------------------------------------
def _banner_record_path(out_dir, name):
    """The sidecar beside one rendered flat. `.json` on the flat's own full
    name, so banner.png -> banner.png.json -- never a second name to keep in
    step with _BANNER_FLAT."""
    return banner_cache_dir(out_dir) / (name + ".json")


def _read_banner_record(out_dir, name):
    """The provenance record for one rendered flat, or None when there is none
    (or it is unreadable, or it is not an object). None means OPAQUE: a render
    nothing here may regenerate."""
    try:
        rec = json.loads(_banner_record_path(out_dir, name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) else None


def _write_banner_record(out_dir, name, record):
    """Stamp a render's provenance. Best effort: a record that fails to write
    leaves an opaque render, which is the SAFE failure -- a later pass declines
    to touch it rather than regenerating something it cannot account for."""
    try:
        banner_cache_dir(out_dir).mkdir(parents=True, exist_ok=True)
        _banner_record_path(out_dir, name).write_text(
            json.dumps(record, indent=2), encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass


def _slot_render_record(out_dir, slot):
    """The record a render of `slot`'s CURRENT active pick would carry --
    {"kind": "slot", "asset_id", "transform"} -- or None when the slot has no
    active asset to render from. The one place the comparison shape is built,
    so what _ensure_banner_renders compares against and what _write_banner_flat
    stamps can never disagree.

    "Current active pick" is resolve_slot_active()'s answer, not this function's
    own: a slot with assets and no recorded pick has to resolve the same way
    here as it does for the payload and the self-heal, or the ensure pass
    compares a render against an answer nothing else would give."""
    assets = list_slot_assets(out_dir, slot)
    active_id = resolve_slot_active(out_dir, slot, assets=assets)
    a = next((x for x in assets if x["id"] == active_id), None)
    if not a:
        return None
    return {"kind": "slot", "asset_id": a["id"],
            "transform": {"zoom": a.get("zoom", 100), "cropX": a.get("cropX", 50),
                          "cropY": a.get("cropY", 50)}}


def _render_banner_flat(out_dir, slot, raw, zoom=100, cropx=50, cropy=50, record=None):
    """The ratio/size pipeline itself: bake raw image bytes into `slot`'s flat
    via _banner_window (the design's own preview math) at the slot's canonical
    output size, and stamp `record` beside it. Shared by _write_banner_flat (the
    active-asset path) and the earned-banner apply route (sealed bytes straight
    from the container) so the two writers can never drift.

    The rendered FLAT lives in banner_cache_dir(out_dir) -- derived per-install
    state, not shipped art, and outside the coded tree since 2026-09-10 (which
    is why this takes out_dir at all). `record` is what says where it came from;
    every caller passes one, and the record is written only after the render
    itself succeeded, so a stale record can never outlive its bytes. Fails soft
    (False), never a 500."""
    name = _BANNER_FLAT.get(slot)
    if not name or raw is None:
        return False
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.load()
        w, hh = im.size
        ar = _BANNER_RATIO.get(slot, 4.0)
        box = _banner_window(w, hh, ar, zoom, cropx, cropy)
        crop = im.crop(box)
        ow, oh = _BANNER_OUT.get(slot, (1920, int(round(1920 / ar))))
        crop = crop.resize((ow, oh), Image.LANCZOS)
        cdir = banner_cache_dir(out_dir)
        cdir.mkdir(parents=True, exist_ok=True)
        crop.save(cdir / name, format="PNG")
    except Exception:
        return False
    _write_banner_record(out_dir, name, record if isinstance(record, dict) else {})
    return True


def _write_banner_flat(out_dir, slot, wear=True):
    """Render a banner slot's ACTIVE asset into its flat, baking the stored
    zoom/cropX/cropY transform in via _render_banner_flat above, and stamp the
    pick it came from. That is what makes the banner sliders REAL -- the
    transform was stored metadata nothing rendered before.

    `wear`: an explicit action (an upload, a pick, a re-crop) also makes the slot wear its
    own pick again, clearing an earned or migrated banner it wore (settings.json's
    worn_banner). The startup ensure pass passes False: re-rendering a pick never changes
    what the owner chose to wear.

    One of the EXPLICIT writers: an upload, a pick, a re-crop, and the startup
    ensure pass -- each an authenticated action or a server start. Nothing on the
    GET/serve path calls this: the /branding/ route only serves. Fails soft (False),
    never a 500: a banner that fails to render leaves the previous flat and its
    record in place, which still displays -- strictly better than a broken
    header image."""
    if slot not in _BANNER_FLAT:
        return False
    rec = _slot_render_record(out_dir, slot)
    if rec is None:
        return False
    # The active asset may be a shipped default living only in the container --
    # read via the resolution layer (coded rel), not a raw path.
    raw = _branding_bytes(_role_rel(slot, rec["asset_id"] + ".png"))
    t = rec["transform"]
    done = _render_banner_flat(out_dir, slot, raw, t["zoom"], t["cropX"], t["cropY"],
                               record=rec)
    if done and wear and _worn_banner(slot) is not None:
        _set_worn_banner(slot, None)
    return done


def _earned_banner_ok(out_dir, banner_id, db_path=None):
    """Is the earned banner `banner_id` earned in THIS library (S5)? The choice to wear it is
    the install's (settings.json), the reward is the library's: in a library where it is not
    earned the slot shows its own pick, and the stored choice is kept for when the library
    changes back. Fail-closed: anything that cannot be computed answers False."""
    aid = _EARNED_BANNERS.get(str(banner_id or ""))
    if not aid:
        return False
    try:
        return _mark_earned(out_dir, db_path or (Path(out_dir) / "catalog.db"), aid)
    except Exception:                      # noqa: BLE001 -- a banner must never fail a boot
        return False


def _ensure_banner_flat(out_dir, slot, db_path=None):
    """Bring one slot's flat up to date, and return the Path the slot is served from (None
    when there is nothing of this install's to serve: the route then falls through to the
    container copy and the shipped sealed default).

    What the slot wears decides it (settings.json's branding.worn_banner, B6):

      - "migrated" (or a kind this build does not know): the only copy, in
        banner_keep_dir(). Never rendered, never touched; None when it is gone.
      - "earned": rendered from the pack into the cache (banner_cache_dir()) when the render
        there is missing or is not that banner -- but only while the banner is earned in this
        library (S5). In a library where it is not, the slot's own pick is rendered instead,
        and the choice stays stored for when the library changes back.
      - nothing: the slot's own pick, rendered into the cache when the render there is
        missing, or its record no longer matches the pick or its transform.

    Everything in the cache is this app's own, rebuildable render, stamped with a record
    (_write_banner_record) saying what it was rendered from; one without a record is stale.

    Called at STARTUP (create_app, via _ensure_banner_renders) and from nowhere on the
    request path: the /branding/ flat route serves what is here and never decodes,
    resizes or writes."""
    name = _BANNER_FLAT.get(slot)
    if not name:
        return None
    worn = _worn_banner(slot)
    kind = worn.get("kind") if worn else None
    if kind not in (None, "earned"):
        keep = banner_keep_dir() / name
        try:
            return keep if keep.is_file() else None
        except OSError:
            return None
    dst = banner_cache_dir(out_dir) / name
    try:
        have = dst.is_file()
    except OSError:
        have = False
    rec = _read_banner_record(out_dir, name)
    if kind == "earned" and _earned_banner_ok(out_dir, worn.get("banner_id"), db_path):
        want = {"kind": "earned", "banner_id": str(worn.get("banner_id"))}
        if have and isinstance(rec, dict) and rec.get("kind") == "earned" \
                and rec.get("banner_id") == want["banner_id"]:
            return dst
        raw = _branding_bytes(_role_rel("earned_banners", want["banner_id"] + ".png"))
        if raw is not None and _render_banner_flat(out_dir, slot, raw, record=want):
            return dst
        # the pack has no bytes for it right now: fall through to the slot's own pick
    want = _slot_render_record(out_dir, slot)
    if want is None:
        if have and not (isinstance(rec, dict) and rec.get("kind") == "slot"):
            # an earned render this library has not earned, with no pick to show instead
            for stale in (dst, _banner_record_path(out_dir, name)):
                try:
                    stale.unlink()
                except OSError:
                    pass
            return None
        return dst if have else None
    if (have and isinstance(rec, dict) and rec.get("kind") == "slot"
            and rec.get("asset_id") == want["asset_id"]
            and rec.get("transform") == want["transform"]):
        return dst
    _write_banner_flat(out_dir, slot, wear=False)
    try:
        return dst if dst.is_file() else None
    except OSError:
        return None


def _record_slot_resolution(out_dir):
    """Write the resolution the startup pass is about to render from back into
    settings.json's branding slots, so a slot that HAD no recorded pick has one from here
    on and the answer stops being re-derived at every start.

    Resolution is already deterministic (resolve_slot_active), so this changes
    no bytes; what it changes is where the answer lives. A slot whose pick was
    only ever implied -- assets adopted from a hand-drop by an older build, a
    pick file lost with a copied library -- is one manifest edit away from
    implying a different asset, and a render then disagrees with a record that
    was never written down. Recording it makes the render's `asset_id` a claim
    about a stored pick rather than about a derivation.

    Called from main() only -- NOT from create_app(), and for the same reason
    _migrate_root_banner_flats() is not: before settings.json held the picks, the pick file
    was addressed off branding_root(), the REAL coded tree on any test that did not patch it,
    and ~every test in the suite builds create_app(), several from module-scoped
    fixtures that conftest's per-test branding isolation cannot reach. Run there,
    a plain pytest run on a dressed install would rewrite the owner's own pick
    file. main() is the one caller that knows this is a real start, and it runs
    immediately before create_app(), so the ensure pass inside it still stamps
    its renders with picks that are by then written down.

    Writes only when a slot actually resolved to an asset the file does not
    already name: a library with no assets at all leaves no file behind, and the
    owner's own recorded picks are never rewritten. Fail-soft -- a pick that
    cannot be persisted still resolves the same way and still renders."""
    try:
        recorded = _recorded_slot_active(out_dir)
        resolved = {slot: resolve_slot_active(out_dir, slot, recorded.get(slot))
                    for slot in BANNER_SLOTS}
        if not any(resolved[slot] and recorded.get(slot) != resolved[slot]
                   for slot in BANNER_SLOTS):
            return
        save_slot_active(out_dir, resolved)
    except Exception:                      # noqa: BLE001 -- a pick must never fail a boot
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "banner render: the slot resolution could not be recorded", exc_info=True)


def _ensure_banner_renders(out_dir, db_path=None):
    """The startup pass: every banner slot's flat brought up to date once, at
    app construction, instead of lazily on a request. The public unauthenticated
    /branding/ route must only ever SERVE -- an anonymous GET that can trigger a
    Pillow decode-crop-resize-save is work a stranger on the LAN schedules --
    and doing it here means the page's very first paint already has the right
    bytes.

    Fails soft per slot, and deliberately BROADLY: this runs inside create_app,
    so anything that escapes here takes the whole server down at construction.
    A banner that cannot be rendered costs a banner -- the route still falls
    through to the container copy and then the shipped sealed default.

    Reads the slot picks, never writes them: on a real start main() has already
    persisted the resolution (_record_slot_resolution) a moment earlier, so the
    picks stamped into the renders below are picks this install has written
    down, and on a test build there is nothing here that can touch the coded
    tree's own pick file."""
    for slot in BANNER_SLOTS:
        try:
            _ensure_banner_flat(out_dir, slot, db_path=db_path)
        except Exception:                  # noqa: BLE001 -- a banner must never fail a boot
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "banner render: %s could not be brought up to date", slot, exc_info=True)


def sweep_branding_drops(out_dir, telem=None):
    """Two jobs with deliberately different scopes (owner ruling, 2026-09-10).

    ADOPT -- the only part that WRITES -- covers exactly four folders: the three
    _SWEEPABLE_SLOTS plus marks. A raw file there that arrived by hand and isn't
    already a known asset is read, deleted, and re-registered as a real slot
    asset (re-encoded to PNG) or a real mark (a .webp kept verbatim). Nothing
    anywhere else is ever adopted, and that list has not changed.

    SCAN -- strictly READ-ONLY -- covers everything under the coded root:
    mascots, rewards, the bridge/system/starfall folders, a folder the user
    invented, at any depth to _BRANDING_WALK_MAX_DEPTH, plus the four adopt
    folders themselves. One readable image in there that this install's BASELINE
    does not account for raises the branding_custom_file telemetry flag, with
    the file left exactly as it was -- not unlinked, not renamed, not
    re-encoded, not moved, not registered. The coded ROOT's own top-level files
    are outside both jobs: not adopted, not scanned, not served.

    The baseline is the whole of "the app did not put it there", and it is
    recorded on the FIRST scan this library-and-app-folder pairing ever runs,
    which therefore reports nothing (_branding_tree_has_new_art). That is what
    stops an upgrade from counting art an older build left behind. Adoption is
    unaffected: a drop in one of the four folders is consumed and flagged on the
    very first sweep, baseline or no baseline, because ADOPTING is itself the
    signal.

    Runs on every /api/achievements fetch rather than sweep_telemetry()'s
    once-a-day cadence, so a file that arrived since the last fetch is adopted,
    or raises the flag, on the next reload rather than up to a day later --
    the same cadence the four adopt folders have always had for a hand-placed
    file. The cost of that cadence is the scan's, and it is
    priced in _branding_tree_has_new_art: the first scan of a process reads and
    hashes a head of each baseline file, every scan after it is the walk's stats
    and a memo lookup. The adopt half is a handful of small directory listings,
    matching list_marks()/list_quarantined()'s own "stays cheap" precedent.

    `telem` is this request's already-loaded telemetry store, when the caller has
    one (/api/achievements does, and used to make the short-circuit below parse
    the file a second time). Handed in, it is READ for the flag short-circuit and
    UPDATED in place with any flag this call raises, so the caller's copy still
    matches the file it was parsed from -- which matters because that caller goes
    on reading its copy further down the same request.

    Returns True if anything was ADOPTED this call -- the flag can fire off the
    scan without that being true."""
    def _raise_flag():
        _telemetry.telem_flag("branding_custom_file", out_dir=out_dir)
        if isinstance(telem, dict) and isinstance(telem.get("flags"), dict):
            telem["flags"]["branding_custom_file"] = 1

    adopted = False
    for slot in _SWEEPABLE_SLOTS:
        sdir = _slot_dir(slot)
        if not sdir.is_dir():
            continue
        known = {a["id"] for a in list_slot_assets(out_dir, slot)}
        try:
            entries = sorted(sdir.iterdir())
        except OSError:
            continue
        for p in entries:
            if not p.is_file() or p.name == "manifest.json" or p.stem in known:
                continue
            png_bytes = _adopt_dropped_file(p)
            if png_bytes is None:
                continue
            # Delete the raw drop BEFORE writing the adopted copy, not after: the
            # adopted asset's own filename can legitimately collide with the raw
            # drop's path (add_slot_asset uses a random id, but a stem-derived id
            # elsewhere -- see _adopt_mark below -- routinely does), and deleting
            # afterward would then remove the file it just wrote instead of the
            # original. png_bytes is already read into memory, so the source file
            # is safe to remove first regardless of what gets written next.
            try:
                p.unlink()
            except OSError:
                pass
            add_slot_asset(out_dir, slot, png_bytes)   # neutral transform (zoom 100, centered)
            adopted = True
    mdir = _role_dir("marks")
    if mdir.is_dir():
        known = {m["id"] for m in list_marks(out_dir)}
        try:
            entries = sorted(mdir.iterdir())
        except OSError:
            entries = []
        for p in entries:
            # A tombstoned stem is KNOWN, not a fresh drop. Without this, delisting
            # a mark makes its still-on-disk loose file invisible to the `known` set
            # and the sweep ADOPTS it -- delete-and-re-encode of a real asset, the
            # exact 2026-08-05 near-miss. Caught live 2026-08-13 on the mark_12
            # tombstone: the owner's own mark_12.png got eaten on first page load.
            if (not p.is_file() or p.name == "marks.json" or p.suffix.lower() == ".ico"
                    or p.stem in known or p.stem in _MARK_TOMBSTONES):
                continue
            # A dropped WEBP is kept VERBATIM. _adopt_dropped_file re-encodes to
            # PNG, which is right for a still image and destructive for an animated
            # one -- Pillow's convert() keeps frame one and throws the animation
            # away. Since the whole point of the webp lane is an animated mark the
            # owner authored, the bytes have to survive the trip; the file is still
            # validated as a readable image first, so this is not an unchecked pass.
            is_webp = p.suffix.lower() == ".webp"
            art = p.read_bytes() if (is_webp and _is_readable_image(p)) \
                else _adopt_dropped_file(p)
            if art is None:
                continue
            try:              # delete first -- see the identical note above
                p.unlink()
            except OSError:
                pass
            _adopt_mark(out_dir, p.stem, art, ext=".webp" if is_webp else ".png")
            adopted = True
    # The scan is WIDER than adoption: a drop the four folders above could not
    # touch still counts. Guarded on the flag ALREADY being set, because this
    # whole function runs on every /api/achievements fetch and the flag is
    # one-shot by contract ("once set they stay set"). Without the guard, every
    # request on a dressed install would both walk the tree and take
    # _telem_mutate's process lock + atomic rewrite to store a 1 that is already
    # there. One cheap read replaces both -- and on the request path it is not
    # even a read: `telem` is the store that request already parsed, so the
    # guard costs a dict lookup.
    if adopted:
        _raise_flag()
    else:
        try:
            d = _telemetry.load_telemetry(out_dir) if telem is None else telem
            already = (d["flags"] or {}).get("branding_custom_file")
        except Exception:                  # noqa: BLE001 -- a broken read must not hide a real drop
            already = False
        if not already and _branding_tree_has_new_art(out_dir):
            _raise_flag()
    return adopted


def load_branding(out_dir):
    """Current branding choice, validated against what exists on disk. Falls back
    to the legacy drop-in logo.png ('logo') when no cut marks are present."""
    cfg = dict(_BRAND_DEFAULTS)
    stored = _settings.branding()          # settings.json's branding: {mark, animation, ...}
    raw = dict(stored.get("animation") or {}) if isinstance(stored.get("animation"), dict) \
        else {}
    if stored.get("mark"):
        raw["mark"] = stored["mark"]
    if raw:                     # a junk value degrades to the default, never a 500
        cfg.update({k: str(v) for k, v in raw.items() if k in ("mark", "anim")})
        for k in ("anim_speed", "anim_scale", "glow_angle"):
            if k in raw:
                cfg[k] = _brand_num(k, raw[k], _BRAND_DEFAULTS[k])
        if "glow_color" in raw:
            cfg["glow_color"] = _brand_color(raw["glow_color"],
                                             _BRAND_DEFAULTS["glow_color"])
    # A retired animation (the six the 2026-08-31 workshop killed) is a stored pick
    # this build no longer has a treatment for -- it wears classic instead. Same
    # line that has always caught a typo'd id; nothing migrates, nothing errors.
    if cfg["anim"] not in MARK_ANIMS:
        cfg["anim"] = "classic"
    have = {m["id"] for m in list_marks(out_dir)}
    if cfg["mark"] not in have:
        cfg["mark"] = _BRAND_DEFAULTS["mark"] if _BRAND_DEFAULTS["mark"] in have else "logo"
    return cfg


def save_branding(out_dir, cfg):
    """Persist the branding choice into settings.json's branding (mark, animation). Every key
    is written explicitly (never the caller's whole dict) so a stray field can't land in the
    file, and the numbers go through the same clamp load_branding applies on the way back in
    -- the file can only ever hold a value the app would accept. The slot picks and the worn
    banner beside them are left exactly as they are."""
    mark = str(cfg["mark"])
    animation = {
        "anim": str(cfg["anim"]),
        "anim_speed": _brand_num("anim_speed", cfg.get("anim_speed"),
                                 _BRAND_DEFAULTS["anim_speed"]),
        "anim_scale": _brand_num("anim_scale", cfg.get("anim_scale"),
                                 _BRAND_DEFAULTS["anim_scale"]),
        "glow_color": _brand_color(cfg.get("glow_color"), _BRAND_DEFAULTS["glow_color"]),
        "glow_angle": _brand_num("glow_angle", cfg.get("glow_angle"),
                                 _BRAND_DEFAULTS["glow_angle"]),
    }

    def _apply(b):
        b["mark"] = mark
        b["animation"] = animation
    _settings.update_branding(_apply)


def _branding_tuning(cfg):
    """The four owner-tunable animation settings, as the API hands them out. One
    function so /api/branding's GET, its POST echo and the Control Panel summary
    can never disagree about the shape."""
    return {"anim_speed": cfg["anim_speed"], "anim_scale": cfg["anim_scale"],
            "glow_color": cfg["glow_color"], "glow_angle": cfg["glow_angle"]}


def brand_context(out_dir):
    """Template vars for the header mark on every page (fed by a context
    processor, so old installs with only logo.png render exactly as before)."""
    cfg = load_branding(out_dir)
    marks = {m["id"]: m for m in list_marks(out_dir)}
    # A banner shows when ANY of the three things /branding/banner.png serves
    # exists -- and this is the SAME three, in the same order, as the route's
    # flat branch, because this flag has to agree with what that route answers:
    #   1. this install's RENDERED flat, in the app cache (not the coded root);
    #   2. a bare top-level flat inside the container, which a pack cut from a
    #      pre-2026-09-10 dressed tree carries (dev/tools/build_container.py gathers
    #      the root recursively);
    #   3. the slot's shipped sealed default -- the route's rule-8 fallback.
    # Dropping any one of them here is how the header renders no banner while
    # the route happily answers 200.
    #
    # This runs from a context processor, i.e. on EVERY page render, so it stays
    # a lookup: one stat for the render, then two cheap existence checks. It
    # deliberately no longer consults load_slot_active() -- that parses each
    # slot's manifest (container-resolved) on every page just to ask whether a
    # pick exists, and it is no longer the right question either. Since the
    # render pass moved to startup, a recorded pick has already become a real
    # render by the time any page is served, and if rendering it failed the
    # route falls through to rule 3, which line 3 below is exactly what checks.
    flat = _BANNER_FLAT["banner_main"]
    try:
        has_flat = (_served_flat_dir(out_dir, "banner_main") / flat).is_file()
    except OSError:
        has_flat = False
    box = _get_container()
    has_banner = (has_flat
                  or bool(box and box.has(flat))
                  or _branding_exists(_flat_default_rel("banner_main")))
    # The animation settings ride along on every page render, exactly as the mark
    # and its anim id always have -- the header reads them straight off MG_BOOT and
    # needs no extra fetch to dress itself correctly on first paint.
    tune = {"anim_speed": cfg["anim_speed"], "anim_scale": cfg["anim_scale"],
            "glow_color": cfg["glow_color"], "glow_angle": cfg["glow_angle"]}
    if cfg["mark"] in marks:
        m = marks[cfg["mark"]]
        return dict(tune, mark_url=m["png"], mark_anim=cfg["anim"], mark_kind=m["kind"],
                    has_banner=has_banner)
    return dict(tune, mark_url="/branding/logo.png", mark_anim=cfg["anim"],
                mark_kind="alpha", has_banner=has_banner)


def _mark_ico_path(mark_id):
    """The app icon for `mark_id` as a REAL file in local\\icons\\ (moonglade.paths.icons_dir()),
    or None when the mark has no .ico cut. Every shortcut the app makes or re-points
    (make_launcher_shortcut, moonglade.outside) takes its icon from here, because Windows
    reads an icon only off disk -- and this folder is no cache, so no clean-up ever blanks a
    shortcut, as deleting 3.19's _container_cache\\ would have. The bytes are the loose cut in
    the coded tree when there is one, else the pack's; the file is rewritten only when they
    differ."""
    raw = _branding_bytes(_role_rel("marks", str(mark_id) + ".ico"))
    if raw is None:
        return None
    ico = _paths.icons_dir() / (str(mark_id) + ".ico")
    try:
        if ico.is_file() and ico.read_bytes() == raw:
            return ico
        ico.parent.mkdir(parents=True, exist_ok=True)
        tmp = ico.with_name(ico.name + ".tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, ico)                   # whole, never half-written under a shortcut
    except OSError:
        return None
    return ico


def make_launcher_shortcut(out_dir, mark_id):
    """Create/refresh the Desktop 'Moonglade Athenaeum.lnk' whose icon is the
    chosen mark's .ico, targeting Moonglade Launcher.pyw via pythonw. Returns the
    .lnk path. Machine-local action -- caller must gate to localhost. The Desktop is the
    shell's own (one moved into OneDrive included: moonglade.outside.desktop_dir()). The
    shortcut is written by the same fixed-script writer the outside-references fixer uses
    (moonglade.outside._save_lnk_with_powershell): every path reaches PowerShell as an
    environment variable, never quoted into the script, so a quote in one -- a typographic
    one included, which also ends a PowerShell '...' string -- can't break or steer it."""
    from moonglade import outside as moonglade_outside
    # PowerShell's CreateShortcut reads IconLocation straight off disk, so the .ico is
    # written into local\icons\ first (_mark_ico_path).
    ico = _mark_ico_path(mark_id)
    if ico is None:
        raise RuntimeError("no .ico cut for %s yet (branding/marks/)" % mark_id)
    repo = _paths.APP_ROOT
    pyw = _paths.launcher_path()
    if not pyw.exists():
        raise RuntimeError("Moonglade Launcher.pyw not found next to the server")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    target = pythonw if pythonw.exists() else Path(sys.executable)
    lnk = moonglade_outside.desktop_dir() / "Moonglade Athenaeum.lnk"
    moonglade_outside._save_lnk_with_powershell(
        lnk, str(target), '"%s"' % pyw, str(repo), str(ico) + ",0",
        description="Moonglade Athenaeum")
    return str(lnk)


# The art pack's own file type in Explorer (pack v7; the owner approved the per-user registry
# entry 2026-10-02). The app's first registry write, so it is kept to this one function.
PACK_PROGID = "MoongladeAthenaeum.ArtPack"
PACK_TYPE_NAME = "Moonglade art pack"


def register_pack_file_type(out_dir, winreg=None, platform=None):
    """Give the art pack a type of its own in Explorer -- the name "Moonglade art pack" and the
    app's icon, instead of a blank Type column and a generic icon. A real start runs this
    (main()) once the pack is present. Current user only, under HKEY_CURRENT_USER\\Software\\
    Classes: no admin rights, no other account touched, nothing machine-wide:

        .mgpack                                 (default)          MoongladeAthenaeum.ArtPack
        MoongladeAthenaeum.ArtPack              (default)          Moonglade art pack
                                                FriendlyTypeName   Moonglade art pack
        MoongladeAthenaeum.ArtPack\\DefaultIcon  (default)          <_pack_type_icon()>,0

    The icon is a per-user copy of the current mark's .ico, the Desktop shortcut's picture
    (_pack_type_icon). With no .ico to copy, or a copy that failed, the icon value is left as
    it is. There is deliberately NO open command: the pack isn't meant to be opened; the
    app reads it by itself (double-click one and Windows asks which app to open it with).

    Each value is read first and written only when it differs, so a start that finds them in
    place writes nothing (and only a start that wrote asks Explorer to refresh). A no-op off
    Windows. Any error logs one warning and returns: a missing file type is cosmetic and must
    never stop the server. `winreg` and `platform` are seams for the tests, which always pass a
    fake registry. Returns True when something was written."""
    if (platform or sys.platform) != "win32" or not _container_path().is_file():
        return False
    try:
        if winreg is None:
            import winreg
        hkcu = winreg.HKEY_CURRENT_USER      # first: a registry that is not there fails here,
        classes = "Software\\Classes\\"     # before any file is written
        want = [(classes + _container_path().suffix, "", PACK_PROGID),
                (classes + PACK_PROGID, "", PACK_TYPE_NAME),
                (classes + PACK_PROGID, "FriendlyTypeName", PACK_TYPE_NAME)]
        icon, wrote = _pack_type_icon(out_dir)
        if icon is not None:
            want.append((classes + PACK_PROGID + "\\DefaultIcon", "", str(icon) + ",0"))
        for key_path, name, value in want:
            try:
                with winreg.OpenKey(hkcu, key_path) as key:
                    if winreg.QueryValueEx(key, name)[0] == value:
                        continue                   # already right: leave it alone
            except OSError:
                pass                               # not there yet: write it below
            with winreg.CreateKeyEx(hkcu, key_path, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            wrote = True
        if wrote:
            _tell_explorer_file_types_changed()
        return wrote
    except Exception as e:                         # noqa: BLE001 -- cosmetic, never fatal
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "art pack: could not register its Explorer file type (%s); carrying on.", e)
        return False


def _pack_type_icon(out_dir):
    """(path, rewritten) for the pack's Explorer icon: %LOCALAPPDATA%\\Moonglade Athenaeum\\
    mgpack.ico, a copy of the current mark's .ico (the Desktop shortcut's picture, read the
    same loose-then-pack way). One fixed per-user place, outside every install, so the D: and
    C: installs point Explorer at the same path and moving or deleting an install never leaves
    it pointing at a file that is gone. Rewritten only when its bytes differ. (None, False)
    when the mark has no .ico, or when the copy fails -- logged once, and the caller then
    leaves the registry's icon as it was."""
    raw = _branding_bytes(_role_rel("marks", str(load_branding(out_dir)["mark"]) + ".ico"))
    if raw is None:
        return None, False
    try:
        dst = Path(os.environ["LOCALAPPDATA"]) / "Moonglade Athenaeum" / "mgpack.ico"
        if dst.is_file() and dst.read_bytes() == raw:
            return dst, False
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".tmp")
        tmp.write_bytes(raw)
        os.replace(tmp, dst)                   # whole, never half-written under Explorer
        return dst, True
    except (KeyError, OSError) as e:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "art pack: could not copy its Explorer icon (%r); the icon is left as it was.", e)
        return None, False


def _tell_explorer_file_types_changed():
    """SHChangeNotify(SHCNE_ASSOCCHANGED): Explorer picks up the new type name and icon now
    instead of at the next sign-in. Best-effort; it changes nothing by itself."""
    try:
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    except Exception:                              # noqa: BLE001 -- a refresh hint only
        pass
