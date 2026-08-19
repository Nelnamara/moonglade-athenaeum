"""Container v2 hardening (moonglade_container.py). Proves: the read API still returns
decoded originals (so callers/existing tests are unaffected), the sealed roster payload
round-trips, and the 'annoying to read' bar actually bites -- no plaintext survives in the
file (`strings` is defeated), the second layer only touches sealed payloads, and a v1
container is rejected. Obfuscation, not secrecy (see the module docstring): these assert
the annoyance is real, not that it's uncrackable."""
import json
import struct
import zlib

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
