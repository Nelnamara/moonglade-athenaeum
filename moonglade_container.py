"""The Moonglade asset container -- a custom packed binary format (.dat), the app's
own MPQ.

WHAT THIS IS. One opaque file carrying the app's default identity: every branding
asset (marks, banners, mascots, badges, rewards) plus reserved payload slots for
non-file data (e.g. the achievement roster). Built by tools/build_container.py from
a real branding/ tree; read at runtime by moonglade_gallery.py's loose-then-container
resolution layer, where a real file on disk always wins over the container (branding
drop-in is a shipped feature and the discovery mechanic depends on it).

OBFUSCATION, NOT SECRECY -- read this before "improving" it. This is a self-hosted,
open-source app: the running server must decode the container, so the decode path
lives in this public module, so a DETERMINED reader can always write an extractor.
We do not pretend otherwise. What v2 buys over v1 is ANNOYANCE, deliberately: the
working key is no longer a single grep-able constant (it is assembled from scattered
fragments and stretched through a slow KDF), payloads are compressed so `strings`
finds nothing, and the sensitive payloads (the roster) sit behind a SECOND,
independently-derived layer -- so cracking the art layer does not hand over the
roster. The bar moves from "copy _KEY, run ten lines" to "trace the derivation,
implement scrypt with the right params, reverse two layers, decompress." That is the
whole and only goal; the real protection for spoilers is that they no longer sit in
plaintext anywhere in the public repo (see ACHIEVEMENT_SEALING_SPEC.md). Do NOT
present this as cryptographic protection anywhere.

FORMAT (v2, little-endian):
    header  32 bytes: magic 'MGC1' | u16 version(=2) | u16 flags | u64 toc_off
                      | u64 toc_size | 8 reserved
    body    asset blobs back-to-back, each XOR-obfuscated with the keystream at its
            absolute file offset (UNCHANGED from v1 -- art needs fast random access);
            then payload blobs, each zlib-compressed (and, for a SEALED payload, XOR'd
            with the second keystream) before the same offset-aligned obfuscation.
    toc     JSON {"assets": {relpath: [off, size, sha256hex_of_original]},
                  "payloads": {name: [off, on_disk_size, sha256hex_of_original]}}
            zlib-compressed then obfuscated, at toc_off.
The keystream is SHAKE-256 counter blocks (64 KiB each) aligned to ABSOLUTE file
offsets (block = offset // 65536), so any byte range decodes independently -- random
access and HTTP-Range serving of art need no full-file pass. The XOR runs as one
big-integer op per call (C speed, ~GB/s). Pure stdlib; no deps.

Read-side contract (UNCHANGED): open_container() returns None (never raises) for a
missing, truncated, corrupt, or foreign/old-version file, and Container.get()/payload()
return None on a checksum mismatch -- callers degrade to "asset absent", exactly as a
missing loose file already does. A broken container must never 500 the gallery. A v1
container reads as None under v2 (version mismatch) -- rebuild required, by design.
"""
import hashlib
import json
import struct
import zlib
from pathlib import Path

MAGIC = b"MGC1"
VERSION = 2
_HEADER = struct.Struct("<4sHHQQ8s")   # 32 bytes
HEADER_SIZE = _HEADER.size
_BLOCK = 65536

# ---- key material -----------------------------------------------------------------
# The working keys are DERIVED, not stored. Fragments are scattered on purpose (see the
# module docstring: annoyance, not secrecy). scrypt stretches them so a reader must run
# the KDF, not copy a constant; the cost is paid ONCE at import and cached below.
_FRAG_A = b"moonglade"
_SCRYPT = {"n": 1 << 14, "r": 8, "p": 1, "dklen": 32, "maxmem": 64 * 1024 * 1024}


def _blend(*parts):
    return b"\x1f".join(parts)


_FRAG_B = b"athenaeum"
_FRAG_C = bytes(reversed(b"tcafetra"))   # -> b"artefact", assembled not spelled


def _derive(tag):
    """A 32-byte key for `tag`, assembled from the scattered fragments + the format
    identity and stretched through scrypt. Deliberately not a lookup of one constant."""
    material = _blend(_FRAG_A, _FRAG_B, _FRAG_C, bytes(MAGIC),
                      struct.pack("<H", VERSION), tag)
    salt = hashlib.sha256(_blend(bytes(MAGIC), tag, _FRAG_C)).digest()
    return hashlib.scrypt(material, salt=salt, **_SCRYPT)


_KEY = _derive(b"general")     # the art / toc / payload container layer
_KEY2 = _derive(b"roster")     # the SECOND layer, over sealed payloads only

# Payload names that get the second, independently-keyed layer. The roster is the crown
# jewel; everything else in the container is art (already binary) or non-sensitive.
_SEALED = frozenset({"achievements"})


def _keystream(key, first_block, n_blocks):
    return b"".join(hashlib.shake_256(key + struct.pack("<Q", b)).digest(_BLOCK)
                    for b in range(first_block, first_block + n_blocks))


def _xor_at(data, file_offset, key=_KEY):
    """XOR `data` with the keystream as laid at absolute `file_offset`. Involutive
    (encode == decode). Block-aligned to the FILE so a mid-blob slice still decodes --
    the property that keeps art random-access free. One big-int op, no byte loop."""
    n = len(data)
    if n == 0:
        return b""
    first = file_offset // _BLOCK
    last = (file_offset + n - 1) // _BLOCK
    pad = _keystream(key, first, last - first + 1)
    start = file_offset - first * _BLOCK
    pad = pad[start:start + n]
    return (int.from_bytes(data, "little")
            ^ int.from_bytes(pad, "little")).to_bytes(n, "little")


def _xor_whole(data, key):
    """Whole-blob keystream from position 0 -- the second layer for sealed payloads,
    which are always read in full (no random access needed, so no offset alignment)."""
    n = len(data)
    if n == 0:
        return b""
    pad = _keystream(key, 0, (n - 1) // _BLOCK + 1)[:n]
    return (int.from_bytes(data, "little")
            ^ int.from_bytes(pad, "little")).to_bytes(n, "little")


def _pack_payload(name, raw):
    """Compress; a SEALED payload also gets the second-layer XOR. Returns the bytes to
    lay in the body (before the outer offset-aligned obfuscation)."""
    blob = zlib.compress(raw, 9)
    if name in _SEALED:
        blob = _xor_whole(blob, _KEY2)
    return blob


def _unpack_payload(name, blob):
    """Reverse of _pack_payload (after the outer layer is already undone)."""
    if name in _SEALED:
        blob = _xor_whole(blob, _KEY2)
    return zlib.decompress(blob)


def write_container(out_path, assets, payloads=None):
    """Pack {relpath: bytes} (+ optional {name: bytes} payloads) into out_path.
    Returns (n_assets, n_payloads). Deterministic layout (sorted keys) so two builds
    from identical inputs are byte-identical -- diffable and testable. Assets are laid
    exactly as v1 (offset XOR, uncompressed -- art); payloads are compressed and, when
    sealed, second-layer XOR'd, before the outer obfuscation."""
    out_path = Path(out_path)
    toc = {"assets": {}, "payloads": {}}
    with open(out_path, "wb") as fh:
        fh.write(b"\0" * HEADER_SIZE)                 # placeholder header
        off = HEADER_SIZE
        for name in sorted(assets):
            raw = assets[name]
            toc["assets"][name] = [off, len(raw), hashlib.sha256(raw).hexdigest()]
            fh.write(_xor_at(raw, off))
            off += len(raw)
        for name in sorted(payloads or {}):
            raw = payloads[name]
            disk = _xor_at(_pack_payload(name, raw), off)
            toc["payloads"][name] = [off, len(disk), hashlib.sha256(raw).hexdigest()]
            fh.write(disk)
            off += len(disk)
        toc_raw = _xor_at(zlib.compress(
            json.dumps(toc, separators=(",", ":")).encode("utf-8"), 9), off)
        fh.write(toc_raw)
        fh.seek(0)
        fh.write(_HEADER.pack(MAGIC, VERSION, 0, off, len(toc_raw), b"\0" * 8))
    return len(toc["assets"]), len(toc["payloads"])


class Container:
    """Read handle over one container file. The TOC loads once; each get() is a
    seek + read + decode + checksum of just that blob. Holds no open fd between calls,
    so the .dat can be atomically replaced (the downloader's swap) without Windows
    file-locking fights."""

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
        outer = _xor_at(raw, off)
        if section == "payloads":
            try:
                data = _unpack_payload(name, outer)
            except (zlib.error, ValueError):
                return None            # corrupt/foreign -> "absent", never garbage
        else:
            data = outer               # asset: laid raw, uncompressed
        if hashlib.sha256(data).hexdigest() != sha:
            return None                # truncated/corrupt -> "absent"
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
    """Container for `path`, or None for missing/corrupt/foreign/old-version files. All
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
