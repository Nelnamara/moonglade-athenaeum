"""The Moonglade asset container -- a custom packed binary format (.dat), the app's
own MPQ.

WHAT THIS IS. One opaque file carrying the app's default identity: every branding
asset (marks, banners, mascots, badges, rewards) plus reserved payload slots for
non-file data. Built by tools/build_container.py from a real branding/ tree; read
at runtime by moonglade_gallery.py's loose-then-container resolution layer, where
a real file on disk always wins over the container (branding drop-in is a shipped
feature and the discovery mechanic depends on it).

WHY A CUSTOM FORMAT (decided 2026-08-10, docs/DECISIONS.md "The asset container,
re-scoped from scratch"): the protection bar is WoW-MPQ-class -- a normal user
sees an unrecognized binary blob no tool opens; a power user who studies this
public source can write an extractor, and that is accepted. Rejected alternatives
and why: encrypted SQLite (a free viewer opens it once the key is read from this
repo), AES-zip (the file listing stays readable with no password at all). This
format is the only shape where the crack requires actually writing code.

THE OBFUSCATION IS DELIBERATELY NOT SECRECY. The key below is committed to a
public repo, exactly as MPQ's algorithm was public. What the browser renders, the
browser has. The point is opacity to casual inspection, not cryptographic
protection -- do not "upgrade" this to real key management, and do not present it
as security anywhere.

FORMAT (v1, little-endian):
    header  32 bytes: magic 'MGC1' | u16 version | u16 flags | u64 toc_off
                      | u64 toc_size | 8 reserved
    body    asset blobs back-to-back, each XOR-obfuscated with the keystream
    toc     JSON {"assets": {relpath: [off, size, sha256hex]},
                  "payloads": {name: [off, size, sha256hex]}}
            zlib-compressed then keystream-obfuscated, at toc_off
The keystream is SHAKE-256 counter blocks (64 KiB each) aligned to ABSOLUTE file
offsets (block = offset // 65536), so any byte range decodes independently --
random access and future HTTP-Range serving need no full-file pass. The XOR runs
as one big-integer operation per call (C speed, ~GB/s): a 392 MB pack takes
seconds and a 3 MB per-request read costs single-digit milliseconds, measured --
the first cut used 32-byte SHA-256 blocks with a per-byte Python loop and packed
at ~3 MB/s, which would have made every gallery image a ~1 s read. Pure stdlib;
no deps.

Read-side contract: open_container() returns None (never raises) for a missing,
truncated, or corrupt file, and Container.get() returns None on a checksum
mismatch -- callers degrade to "asset absent", the same behaviour a missing loose
file already has. A broken container must never 500 the gallery.
"""
import hashlib
import json
import struct
import zlib
from pathlib import Path

MAGIC = b"MGC1"
VERSION = 1
_HEADER = struct.Struct("<4sHHQQ8s")   # 32 bytes
HEADER_SIZE = _HEADER.size

# Public-by-design (see the module docstring). Changing this orphans every
# container built before the change -- version-bump the format if it ever must.
_KEY = bytes.fromhex(
    "6d6f6f6e676c6164652d617468656e6165756d2d61727465666163742d763101")

_BLOCK = 65536


def _xor_at(data, file_offset):
    """XOR `data` with the keystream as laid at absolute position `file_offset`.
    Involutive: applying it twice is identity, so this is both encode and decode.
    Block alignment is to the FILE, not the blob, so a slice read mid-blob still
    decodes -- the property that makes random access free.

    Speed is load-bearing here (see the module docstring): the pad is generated
    64 KiB at a time by SHAKE-256 (one C-level call per block) and the XOR is a
    single big-integer op over the whole range -- no Python byte loop anywhere."""
    n = len(data)
    if n == 0:
        return b""
    first = file_offset // _BLOCK
    last = (file_offset + n - 1) // _BLOCK
    pads = [hashlib.shake_256(_KEY + struct.pack("<Q", b)).digest(_BLOCK)
            for b in range(first, last + 1)]
    start = file_offset - first * _BLOCK
    pad = b"".join(pads)[start:start + n]
    return (int.from_bytes(data, "little")
            ^ int.from_bytes(pad, "little")).to_bytes(n, "little")


def write_container(out_path, assets, payloads=None):
    """Pack {relpath: bytes} (+ optional {name: bytes} payloads) into out_path.
    Returns (n_assets, n_payloads). Deterministic layout (sorted keys) so two
    builds from identical inputs are byte-identical -- diffable and testable."""
    out_path = Path(out_path)
    toc = {"assets": {}, "payloads": {}}
    with open(out_path, "wb") as fh:
        fh.write(b"\0" * HEADER_SIZE)                 # placeholder header
        off = HEADER_SIZE
        for section, table in (("assets", assets), ("payloads", payloads or {})):
            for name in sorted(table):
                raw = table[name]
                toc[section][name] = [off, len(raw),
                                      hashlib.sha256(raw).hexdigest()]
                fh.write(_xor_at(raw, off))
                off += len(raw)
        toc_raw = _xor_at(zlib.compress(
            json.dumps(toc, separators=(",", ":")).encode("utf-8"), 9), off)
        fh.write(toc_raw)
        fh.seek(0)
        fh.write(_HEADER.pack(MAGIC, VERSION, 0, off, len(toc_raw), b"\0" * 8))
    return len(toc["assets"]), len(toc["payloads"])


class Container:
    """Read handle over one container file. The TOC loads once; each get() is a
    seek + read + XOR + checksum of just that blob. Instances hold no open file
    descriptor between calls, so the .dat can be atomically replaced (the
    downloader's swap) without Windows file-locking fights."""

    def __init__(self, path, toc):
        self.path = Path(path)
        self._toc = toc

    def _read(self, section, name):
        entry = self._toc.get(section, {}).get(name)
        if not entry:
            return None
        off, size, sha = entry
        try:
            with open(self.path, "rb") as fh:
                fh.seek(off)
                raw = fh.read(size)
        except OSError:
            return None
        if len(raw) != size:
            return None
        data = _xor_at(raw, off)
        if hashlib.sha256(data).hexdigest() != sha:
            return None            # truncated/corrupt -> "absent", never garbage
        return data

    def has(self, relpath):
        return relpath in self._toc.get("assets", {})

    def get(self, relpath):
        return self._read("assets", relpath)

    def payload(self, name):
        return self._read("payloads", name)

    def paths(self):
        return sorted(self._toc.get("assets", {}))

    def payload_names(self):
        return sorted(self._toc.get("payloads", {}))


def open_container(path):
    """Container for `path`, or None for missing/corrupt/foreign files. All
    failure modes collapse to None on purpose -- see the module docstring."""
    path = Path(path)
    try:
        with open(path, "rb") as fh:
            head = fh.read(HEADER_SIZE)
            if len(head) != HEADER_SIZE:
                return None
            magic, version, _flags, toc_off, toc_size, _r = _HEADER.unpack(head)
            if magic != MAGIC or version != VERSION:
                return None
            fh.seek(toc_off)
            toc_raw = fh.read(toc_size)
        if len(toc_raw) != toc_size:
            return None
        toc = json.loads(zlib.decompress(_xor_at(toc_raw, toc_off)))
        if not isinstance(toc, dict) or "assets" not in toc:
            return None
        return Container(path, toc)
    except (OSError, ValueError, zlib.error, struct.error):
        return None
