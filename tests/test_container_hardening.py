"""Container v2 hardening (moonglade_container.py). Proves: the read API still returns
decoded originals (so callers/existing tests are unaffected), the sealed roster payload
round-trips, and the 'annoying to read' bar actually bites -- no plaintext survives in the
file (`strings` is defeated), the second layer only touches sealed payloads, and a v1
container is rejected. Obfuscation, not secrecy (see the module docstring): these assert
the annoyance is real, not that it's uncrackable."""
import json
import os
import struct
import zlib
from pathlib import Path

import pytest

import moonglade_container as mc


def test_roundtrip_assets_payloads_and_read_contract(tmp_path):
    p = tmp_path / "t.dat"
    assets = {"banner.png": b"\x89PNG-fake-art-bytes", "marks/m.json": b'{"marks":[]}'}
    secret = json.dumps([{"id": "night-owl", "roast": "SECRET", "threshold": 5}]).encode()
    payloads = {"achievements": secret, "other": b"non-sensitive-payload"}
    assert mc.write_container(p, assets, payloads) == (2, 2)

    box = mc.open_container(p)
    assert box is not None
    # assets round-trip; API returns the ORIGINAL bytes (decode is internal)
    assert box.get("banner.png") == assets["banner.png"]
    assert box.get("marks/m.json") == assets["marks/m.json"]
    # the SEALED roster payload round-trips through both layers + compression
    assert box.payload("achievements") == secret
    assert box.payload("other") == b"non-sensitive-payload"
    # listings + membership
    assert box.paths() == ["banner.png", "marks/m.json"]
    assert box.payload_names() == ["achievements", "other"]
    assert box.has("banner.png") and not box.has("missing.png")
    # absent -> None (the "degrade to missing" contract), never garbage
    assert box.get("missing.png") is None
    assert box.payload("missing") is None


def test_no_plaintext_in_the_file(tmp_path):
    """A casual `strings moonglade.dat | grep roast` must find nothing."""
    p = tmp_path / "t.dat"
    secret = b'[{"id":"night-owl","name":"Night Owl","roast":"UNMISTAKABLE_SPOILER_TEXT"}]'
    mc.write_container(p, {"a.png": b"x"}, {"achievements": secret})
    blob = p.read_bytes()
    for needle in (b"UNMISTAKABLE_SPOILER_TEXT", b"night-owl", b"Night Owl", b"roast", b"id"):
        assert needle not in blob, "plaintext %r leaked into the .dat" % needle


def test_second_layer_hits_sealed_payloads_only(tmp_path):
    """The roster gets a SECOND, independently-keyed layer; other payloads just compress.
    So cracking the general/art layer does not hand over the roster."""
    x = b"identical-bytes-for-both-names-0123456789"
    sealed = mc._pack_payload("achievements", x)   # in _SEALED
    plain = mc._pack_payload("other", x)           # not sealed
    assert sealed != plain                          # the extra layer changed it
    assert plain == zlib.compress(x, 9)             # non-sealed == plain compression
    assert sealed != zlib.compress(x, 9)            # sealed != plain compression
    # both still reverse correctly
    assert mc._unpack_payload("achievements", sealed) == x
    assert mc._unpack_payload("other", plain) == x


def test_key_is_derived_not_a_bare_constant():
    """The working key must not be a single grep-able constant: it comes from scrypt
    over assembled fragments, so it is 32 bytes and not equal to any one fragment."""
    assert isinstance(mc._KEY, bytes) and len(mc._KEY) == 32
    assert mc._KEY != mc._KEY2                       # two independent derivations
    for frag in (mc._FRAG_A, mc._FRAG_B, mc._FRAG_C):
        assert mc._KEY != frag and not mc._KEY.startswith(frag)


def test_v1_container_is_rejected(tmp_path):
    """A file claiming the old format version reads as None -- rebuild required."""
    good = tmp_path / "good.dat"
    mc.write_container(good, {"a.png": b"x"}, {})
    raw = bytearray(good.read_bytes())
    struct.pack_into("<H", raw, 4, 1)               # stamp version = 1 in the header
    old = tmp_path / "old.dat"
    old.write_bytes(bytes(raw))
    assert mc.open_container(old) is None


def test_missing_and_foreign_files(tmp_path):
    assert mc.open_container(tmp_path / "nope.dat") is None
    foreign = tmp_path / "foreign.dat"
    foreign.write_bytes(b"just some other file's bytes, not a container" * 8)
    assert mc.open_container(foreign) is None


def test_writer_stamps_the_current_reader_version(tmp_path):
    """The writer and the running reader must always agree on the format version: a fresh
    build stamps mc.VERSION in the header and open_container accepts it. This is the
    tripwire for the 'v1 file under a v2 reader -> empty Folio' class -- if someone bumps
    mc.VERSION without keeping the writer/reader in step, a fresh build stops round-tripping
    here, LOUDLY, instead of a rebuilt-but-still-rejected container reaching an install.
    (It cannot police the DELIVERED release asset -- that's the deploy lockstep's job:
    rebuild the .dat, republish it, bump moonglade_manifest.json, all with the merge.)"""
    p = tmp_path / "v.dat"
    mc.write_container(p, {"a.png": b"x"}, {"achievements": b'{"roster":[]}'})
    raw = p.read_bytes()
    assert raw[:4] == b"MGC1"                         # magic
    (ver,) = struct.unpack_from("<H", raw, 4)         # format version, header offset 4
    assert ver == mc.VERSION
    assert mc.open_container(p) is not None            # and the current reader accepts it


# ---------------------------------------------------------------------------
# The build stamp (TOC schema 1, 2026-09-07)
# ---------------------------------------------------------------------------
# The header only ever said "this is format v2". It said nothing about WHAT was inside or
# who packed it, so a TOC with entries swapped, renamed or trimmed opened perfectly and
# failed later, one asset at a time, as a silent "absent". schema + content_sha256 close
# that at open time and read no blob to do it; built_at + builder are the provenance the
# builder writes. A pre-stamp v2 file (the shipped moonglade.dat) must still open.

def _toc_of(path):
    """Decode a container's TOC dict straight off disk, using the format's own primitives."""
    raw = path.read_bytes()
    magic, ver, _flags, toc_off, toc_size, _r = mc._HEADER.unpack(raw[:mc.HEADER_SIZE])
    assert magic == mc.MAGIC and ver == mc.VERSION
    return json.loads(zlib.decompress(mc._xor_at(raw[toc_off:toc_off + toc_size], toc_off)))


def _rewrite_toc(src, dst, mutate):
    """Copy `src` to `dst` with its TOC passed through `mutate`. The TOC is the LAST thing
    in the file, so re-encoding it and re-stamping the header's toc_size is a complete
    rewrite -- which is exactly how a tamperer, or an older writer, would have done it."""
    raw = src.read_bytes()
    _m, _v, flags, toc_off, _ts, _r = mc._HEADER.unpack(raw[:mc.HEADER_SIZE])
    toc = mutate(_toc_of(src))
    body = raw[mc.HEADER_SIZE:toc_off]
    blob = mc._xor_at(zlib.compress(json.dumps(toc, separators=(",", ":")).encode(), 9), toc_off)
    dst.write_bytes(mc._HEADER.pack(mc.MAGIC, mc.VERSION, flags, toc_off, len(blob), b"\0" * 8)
                    + body + blob)
    return dst


def _stamped(tmp_path, name="s.dat"):
    p = tmp_path / name
    mc.write_container(p, {"a.png": b"art", "b.png": b"more"},
                       {"achievements": b'{"roster":[]}'},
                       builder="test-packer/9", built_at="2026-09-07T00:00:00Z")
    return p


def test_the_writer_stamps_the_toc_and_the_reader_hands_it_back(tmp_path):
    p = _stamped(tmp_path)
    toc = _toc_of(p)
    assert toc["schema"] == mc.SUPPORTED_SCHEMA == 1
    assert toc["content_sha256"] == mc._content_digest(toc)   # covers assets + payloads
    box = mc.open_container(p)
    assert box is not None
    assert box.stamp() == {"schema": 1, "content_sha256": toc["content_sha256"],
                           "built_at": "2026-09-07T00:00:00Z", "builder": "test-packer/9"}
    assert box.schema() == 1


def test_built_at_and_builder_default_to_empty_so_a_build_stays_reproducible(tmp_path):
    """schema/content_sha256 are DERIVED from the content, so they cost determinism
    nothing. built_at/builder are the caller's to supply precisely because a wall-clock
    value inside the file makes two builds of identical inputs differ -- and
    tools/build_container.py's carry-the-URL-forward rule depends on reproducing bytes."""
    p1, p2 = tmp_path / "1.dat", tmp_path / "2.dat"
    mc.write_container(p1, {"a.png": b"x"})
    mc.write_container(p2, {"a.png": b"x"})
    assert p1.read_bytes() == p2.read_bytes()
    assert mc.open_container(p1).stamp() == {
        "schema": 1, "content_sha256": _toc_of(p1)["content_sha256"],
        "built_at": "", "builder": ""}


def test_content_sha256_covers_names_order_and_membership(tmp_path):
    """It is a digest of the per-entry ORIGINAL hashes IN TOC ORDER, name included -- so a
    rename, a dropped entry or a swapped hash all move it, without reading one blob."""
    p = _stamped(tmp_path)
    base = _toc_of(p)["content_sha256"]

    def digest(mutate):
        t = _toc_of(p)
        mutate(t)
        return mc._content_digest(t)

    assert digest(lambda t: t["assets"].__setitem__(
        "c.png", t["assets"].pop("a.png"))) != base            # renamed
    assert digest(lambda t: t["assets"].pop("b.png")) != base   # dropped
    assert digest(lambda t: t["assets"]["a.png"].__setitem__(2, "0" * 64)) != base  # re-hashed
    assert digest(lambda t: t["payloads"].pop("achievements")) != base   # payloads count too
    assert digest(lambda t: None) == base                       # and it is stable


def test_a_tampered_toc_is_refused_at_open(tmp_path):
    """Every one of these opened FINE before the stamp and then answered 'absent' asset by
    asset. Now the container is refused whole, on the same terms as a bad header."""
    cases = [
        ("renamed entry", lambda t: t["assets"].__setitem__("c.png", t["assets"].pop("a.png"))),
        ("dropped entry", lambda t: t["assets"].pop("b.png")),
        ("swapped hash", lambda t: t["assets"]["a.png"].__setitem__(2, "0" * 64)),
        ("dropped payload", lambda t: t["payloads"].pop("achievements")),
        ("blanked digest", lambda t: t.__setitem__("content_sha256", "")),
        ("digest not a string", lambda t: t.__setitem__("content_sha256", 123)),
    ]
    p = _stamped(tmp_path)
    for label, mutate in cases:
        def m(t, _f=mutate):
            _f(t)
            return t
        bad = _rewrite_toc(p, tmp_path / "bad.dat", m)
        assert mc.open_container(bad) is None, label
        bad.unlink()


def test_a_newer_schema_is_refused_and_a_bad_one_never_raises(tmp_path):
    p = _stamped(tmp_path)

    def restamp(v):
        def m(t):
            t["schema"] = v
            t["content_sha256"] = mc._content_digest(t)
            return t
        return _rewrite_toc(p, tmp_path / "restamped.dat", m)

    assert mc.open_container(restamp(mc.SUPPORTED_SCHEMA + 1)) is None   # a newer packer
    assert mc.open_container(restamp(-1)) is None
    assert mc.open_container(restamp("1")) is None                       # not an int
    assert mc.open_container(restamp(True)) is None                      # bool is not a schema


def test_a_pre_stamp_v2_container_still_opens_as_schema_zero(tmp_path):
    """A v2 file built before the stamp existed has no `schema` key at all. It must open
    exactly as it always did -- the shipped moonglade.dat is one of these, and refusing it
    would undress every install that has not re-downloaded the pack."""
    p = _stamped(tmp_path)

    def strip(t):
        for k in ("schema", "content_sha256", "built_at", "builder"):
            t.pop(k, None)
        return t

    old = _rewrite_toc(p, tmp_path / "old.dat", strip)
    box = mc.open_container(old)
    assert box is not None
    assert box.get("a.png") == b"art"                       # and it still reads
    assert box.payload("achievements") == b'{"roster":[]}'
    assert box.schema() == 0
    assert box.stamp() == {"schema": 0, "content_sha256": "", "built_at": "", "builder": ""}


def test_the_shipped_container_still_opens():
    """The real moonglade.dat, if this machine has one. It predates the stamp, so this runs
    the pre-stamp path against the actual shipped artefact rather than a fixture -- the one
    file that must not stop opening. It is git-ignored (delivery is a Release asset) and
    absent in CI and in a worktree, so this SKIPS rather than fails when it is not there;
    the fixture test above covers the same path unconditionally. MOONGLADE_DAT points it at
    a copy elsewhere."""
    candidates = [Path(__file__).resolve().parents[1] / "moonglade.dat"]
    env = os.environ.get("MOONGLADE_DAT")
    if env:
        candidates.insert(0, Path(env))
    real = next((c for c in candidates if c.is_file()), None)
    if real is None:
        pytest.skip("no built moonglade.dat on this machine to check")
    box = mc.open_container(real)
    assert box is not None
    assert box.paths()                                       # it really has content
    assert box.schema() <= mc.SUPPORTED_SCHEMA
