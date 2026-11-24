"""
moonglade/web_policy.py
=======================
The web app's security policy constants and helpers (app security review 2026-11-19, red team
2026-11-18): the request and zip size caps and their refusal sentences, the session lifetimes
(the remembered device's included), the TV pairing's limits,
`harden_file_response` (a file from the library never runs as a page), the page CSP
(`page_csp`), the cross-origin and plain-HTTP refusals, and `same_origin_write`. The hooks that
apply them are moonglade/routes_gate.py's. Moved verbatim out of moonglade/gallery.py in the
3.22 split (phase 4).

It needs nothing from the gallery or the engine.
"""
import os
import re


# ---------------------------------------------------------------------------
# SIZE CAPS (app security review 2026-11-19, finding 9)
# ---------------------------------------------------------------------------
# Every request body has a ceiling, and every zip the app opens has one on what it unpacks.
# REQUEST_MAX_BYTES is the app-wide default (Flask's MAX_CONTENT_LENGTH): JSON bodies, the
# branding uploads, everything that names no larger cap. The few routes that take big files
# raise it for themselves before their form is read. A refusal is a 413 with a plain sentence.
# The import limits are sized for a whole library (a zip of years of pictures, a long video):
# they stop a runaway or hostile upload from filling the drive, not a real library. Past them,
# the command-line import (IMPORT_CLI_HINT) reads a folder in place with no upload at all.
_GB = 1024 ** 3
REQUEST_MAX_BYTES = 64 * 1024 * 1024
UPLOAD_MAX_BYTES = 8 * _GB                      # /api/upload: one file handed to PixAI
IMPORT_REQUEST_MAX_BYTES = 50 * _GB             # /api/import-local: one request (the page sends
                                                # batches of at most 256 MB; a lone bigger
                                                # file -- a library zip, a long video -- alone)
LOOM_BUNDLE_REQUEST_MAX_BYTES = 50 * _GB        # /api/loom/import-bundle
# What a zip may unpack to (Import's zips and Loom bundles): its member count, any one member,
# and the bytes of the whole -- all counted as they are written, never taken from the zip's own
# headers, which a zip bomb lies in.
ZIP_MAX_MEMBERS = 200000
ZIP_MAX_MEMBER_BYTES = 8 * _GB
ZIP_MAX_TOTAL_BYTES = 50 * _GB
IMPORT_CLI_HINT = ("For something this big, import it from the command line on this PC instead: "
                   "python -m moonglade --import-local \"<folder>\" (unzip it first).")
ZIP_TOO_MANY_MEMBERS = ("That zip holds more than {:,} files, so nothing in it was imported. "
                        .format(ZIP_MAX_MEMBERS) + IMPORT_CLI_HINT)
ZIP_MEMBER_TOO_BIG = ("A file in that zip unpacks to more than {} GB, so nothing in it was "
                      "imported. ".format(ZIP_MAX_MEMBER_BYTES // _GB) + IMPORT_CLI_HINT)
ZIP_TOO_BIG = ("That zip unpacks to more than {} GB, so nothing in it was imported. "
               .format(ZIP_MAX_TOTAL_BYTES // _GB) + IMPORT_CLI_HINT)


class ZipTooBig(ValueError):
    """A zip over ZIP_MAX_MEMBERS, ZIP_MAX_MEMBER_BYTES or ZIP_MAX_TOTAL_BYTES; str() is the
    plain sentence."""


def _too_large_sentence(limit):
    """The 413's words for a body over `limit` bytes."""
    if limit and limit >= 1024 ** 3:
        size = "{:g} GB".format(round(limit / 1024 ** 3, 1))
    elif limit:
        size = "{:g} MB".format(round(limit / 1024 ** 2, 1))
    else:
        size = "the limit"
    return ("That is more than Moonglade takes in one go ({}), so nothing was sent. Send "
            "fewer or smaller files at a time. ".format(size) + IMPORT_CLI_HINT)


# ---------------------------------------------------------------------------
# SESSIONS (app security review 2026-11-19, finding 6)
# ---------------------------------------------------------------------------
# A sign-in lasts at most SESSION_ABSOLUTE_LIFETIME_S from the moment it was made, however
# often it is used (the cookie itself still renews on use, Flask's permanent session, so an
# idle one also ends after SESSION_IDLE_LIFETIME_DAYS). Every session carries its own id, and
# Log Out records that id as signed out (moonglade.web_sessions), so a copy of the cookie stops
# working the moment the device that made it signs out.
SESSION_ABSOLUTE_LIFETIME_S = 30 * 86400
SESSION_IDLE_LIFETIME_DAYS = 30
# "Remember this device" (owner ruling 2026-11-22, Direction C): a ticked sign-in, and a paired TV,
# is a device record (moonglade.web_devices) that lasts this long from the moment it was made. Its
# cookie expires with the record, and the cookie's signature is accepted up to this age; every
# other session keeps the two 30-day limits above.
REMEMBER_DEVICE_LIFETIME_S = 90 * 86400
# The TV's pairing (Apple TV plan S1): a code lives this long, and these are its guesses' limits.
PAIR_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PAIR_CODE_LENGTH = 6
PAIR_CODE_LIFETIME_S = 600
PAIR_WINDOW_S = 600                 # every pairing limit below counts over this window
PAIR_STARTS_PER_IP = 5
PAIR_WRONG_CODES_PER_ACCOUNT = 5
PAIR_WRONG_CODES_PER_IP = 5
PAIR_WRONG_CODES_GLOBAL = 30
PAIR_POLL_WINDOW_S = 60
PAIR_POLLS_PER_IP = 60              # the TV polls every 2 s; twice that rate is refused


# ---------------------------------------------------------------------------
# FILES FROM THE LIBRARY NEVER RUN AS A PAGE (red team, 2026-11-18)
# ---------------------------------------------------------------------------
# Every route that hands back a file someone else made -- a library picture or clip, a
# thumb, a music bed, a PixAI CDN cover, an export -- goes out through
# harden_file_response. A browser shown only a raster picture, a video or a sound has
# nothing to run; anything else (an SVG above all: Edit Pro makes them, the library
# catalogs them, and an SVG may carry <script>) opened at its own URL would run AS
# Moonglade, with the signed-in session. So: every such response says nosniff (the
# browser keeps to the stated type) and a CSP sandbox (no script, no same-origin even if
# it did render), and a type outside the list below is sent as a download. An <img>,
# <video> or <audio> ignores Content-Disposition, so in-page display is unchanged.
_INLINE_FILE_TYPES = frozenset({
    "image/png", "image/jpeg", "image/pjpeg", "image/webp", "image/gif", "image/avif",
    "image/bmp", "image/x-icon", "image/vnd.microsoft.icon",
    "video/mp4", "video/webm", "video/quicktime", "video/x-m4v",
    "audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/wave", "audio/mp4",
    "audio/aac", "audio/ogg", "audio/flac", "audio/x-flac",
})
FILE_RESPONSE_CSP = "sandbox"
# An SVG (3.22 S5, DESIGN_3.22 5.4) goes out under its real type, image/svg+xml, so an <img src>
# (or a CSS background-image) can draw it -- an image context never runs SVG script. It is still
# always a download (an SVG is not on _INLINE_FILE_TYPES), so a direct visit never becomes a
# page on Moonglade's origin, and this policy is the belt if a browser ignores the disposition:
# sandboxed, nothing fetched, only its own inline styles. Never shown any other way: no
# <object>, <embed>, <iframe>, innerHTML, data URL from its text or fetch-then-inject.
SVG_FILE_CSP = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
# The library's own picture and clip types, named here rather than asked of the system's
# type table (on Windows that reads the registry, which can say anything).
_MEDIA_TYPE_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif", ".avif": "image/avif", ".mp4": "video/mp4", ".webm": "video/webm",
    ".mov": "video/quicktime", ".m4v": "video/x-m4v",
    ".svg": "image/svg+xml",           # a download with SVG_FILE_CSP (harden_file_response)
}


def media_type_for(name):
    """The fixed type for a library picture or clip by its extension; None for anything
    else (the caller's guess then stands, and harden_file_response makes it a download)."""
    return _MEDIA_TYPE_BY_EXT.get(os.path.splitext(str(name or ""))[1].lower())


def _attachment_disposition(name):
    """`attachment; filename=...` for any name: an ASCII fallback plus the RFC 5987 form."""
    from urllib.parse import quote
    name = os.path.basename(str(name or "")) or "download"
    plain = re.sub(r'[^\x20-\x7e]|["\\]', "_", name)
    return "attachment; filename=\"{}\"; filename*=UTF-8''{}".format(plain, quote(name, safe=""))


def harden_file_response(resp, filename=None):
    """Stamp a served file's response so it can never run as a page on this origin.

    Always: X-Content-Type-Options: nosniff and Content-Security-Policy: sandbox (an SVG,
    by its type or its name: the stricter SVG_FILE_CSP). And a type that is not a raster
    picture, a video or a sound goes out as a download (Content-Disposition: attachment),
    whatever the route asked for. Returns resp."""
    resp.headers["X-Content-Type-Options"] = "nosniff"
    mime = (resp.mimetype or "").lower()
    svg = mime == "image/svg+xml" or str(filename or "").lower().endswith(".svg")
    resp.headers["Content-Security-Policy"] = SVG_FILE_CSP if svg else FILE_RESPONSE_CSP
    if mime not in _INLINE_FILE_TYPES:
        if not (resp.headers.get("Content-Disposition") or "").lower().startswith("attachment"):
            resp.headers["Content-Disposition"] = _attachment_disposition(filename)
    return resp


# ---------------------------------------------------------------------------
# THE APP'S OWN PAGES, AND WHERE A WRITE MAY COME FROM (app security review 2026-11-19)
# ---------------------------------------------------------------------------
# The policy every HTML page goes out with (create_app's _protective_headers). Scripts: this
# origin's files, plus the inline ones the page templates mark with CSP_NONCE_MARK, which the
# serving route replaces with a fresh nonce per request (_noncify) -- no 'unsafe-inline', no
# 'unsafe-eval' (neither bundle evaluates strings; the Loom has shipped pre-built since the
# Babel-standalone retirement). Styles may be inline: React writes style attributes and the
# pages carry their design tokens in a <style>, and a style cannot run anything. Pictures and
# video may come from https: (PixAI's own covers), data: and blob: (QR codes, import previews).
# Only Moonglade's own pages may frame one (the same-origin phone-layout check frames the app),
# and no page may submit a form or open a plugin elsewhere.
CSP_NONCE_MARK = "__CSP_NONCE__"
CSP_PAGE_POLICY = ("default-src 'self'; script-src 'self'{nonce}; "
                   "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
                   "media-src 'self' data: blob: https:; font-src 'self' data:; "
                   "connect-src 'self'; worker-src 'self'; manifest-src 'self'; "
                   "object-src 'none'; base-uri 'none'; form-action 'self'; "
                   "frame-ancestors 'self'")


def page_csp(nonce=None):
    """CSP_PAGE_POLICY for one response: with its nonce when the page used one."""
    return CSP_PAGE_POLICY.format(nonce=(" 'nonce-%s'" % nonce) if nonce else "")


CROSS_ORIGIN_REFUSED = ("That request came from a page that isn't one of this Moonglade's own, "
                        "so nothing was done. Open Moonglade itself and try again there.")
PLAIN_HTTP_REFUSED = ("Moonglade only takes this over an encrypted connection from another "
                      "device. Open Moonglade at {url} and try again there.")
CONNECT_TOKEN_NEEDS_HTTPS = ("Connect from PixAI from another device only works over an "
                             "encrypted connection, so nothing was saved. Open Moonglade at its "
                             "https:// address (the Control Panel's LAN card shows it), make the "
                             "Connect from PixAI bookmark again there, and click it on a "
                             "pixai.art tab.")
# The TV's pairing and its token (R5): another device reaches them over HTTPS only. This PC's own
# loopback may stay plain. A bearer request is refused with this, never redirected.
DEVICE_NEEDS_HTTPS = ("Pairing and a paired device's requests only work over an encrypted "
                      "connection from another device. Connect to Moonglade at its https:// "
                      "address (the Control Panel's LAN card shows it).")


def _origin_tuple(url):
    """(scheme, host, port) of an http(s) URL or origin, the default port filled in; None for
    anything else ("null", an empty value, another scheme, a malformed port)."""
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(str(url or "").strip())
        scheme = parts.scheme.lower()
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        return None
    if scheme not in ("http", "https") or not host:
        return None
    return scheme, host, port or (443 if scheme == "https" else 80)


def same_origin_write(origin, referer, fetch_site, scheme, host):
    """Does a state-changing request come from this server's own origin? Pure.

    `origin`, `referer` and `fetch_site` are the request's Origin, Referer and Sec-Fetch-Site
    headers (None when absent); `scheme` and `host` are the request's own (request.scheme,
    request.host -- what the browser addressed). The rule, in order:
      * a Sec-Fetch-Site other than "same-origin" refuses (same-site is NOT enough: another
        port on this PC is same-site);
      * an Origin header decides alone, and "null" or anything unparseable refuses;
      * with no Origin, a Referer decides the same way;
      * with none of the three, the caller is not a browser and passes (it has no ambient
        cookie for another page to ride)."""
    own = _origin_tuple("{}://{}".format(scheme or "", host or ""))
    if own is None:
        return False
    if fetch_site is not None and fetch_site.strip().lower() != "same-origin":
        return False
    if origin is not None:
        return _origin_tuple(origin) == own
    if referer:
        return _origin_tuple(referer) == own
    return True
