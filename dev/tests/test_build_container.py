"""dev/tools/build_container.py -- the container packer + cold byte-for-byte verify +
manifest writer.

The flagged gap (docs/DECISIONS.md, "P1 test-suite audit", 2026-08-11): the tool
had ZERO test coverage even though it produces the shipped art pack and the
committed moonglade_manifest.json. Covered here: gather()'s _thumbs exclusion, the
happy-path build (container reads back byte-for-byte + manifest keyed to the whole
file + the achievements payload), the version-bump and url-carry-forward rules,
explicit --version/--url override, the empty/missing-branding refusals, and the
verification-failure-deletes-the-output safety (a silently-wrong container is worse
than none). Since 2026-09-07 also the BUILD STAMP: the provenance the packer writes
into the TOC, that the verify step refuses a pack whose stamp did not round-trip, and
the one consequence of putting a clock inside the file -- an unpinned rebuild is new
bytes, so it fails closed without a --url exactly as any other byte change does.

The conftest's autouse _isolated_branding + _isolated_asset_manifest fixtures point
branding_root() AND manifest_path() at each test's tmp_path, so main() -- whose
default output is _container_path() (moonglade.mgpack) and whose manifest goes
through manifest_path() -- can never touch the developer's real art or the committed
manifest. That the manifest resolver is isolated is what makes it safe to run the
real main() here at all."""
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

from moonglade import assets as ma
from moonglade import backup as core
from moonglade import container as mc
from moonglade import gallery as g

# tools/ is not a package; load the script by path (its own module-level code only
# does imports + a sys.path insert, so importing it at collection time is safe --
# it never touches branding_root() until main() runs, under a test's fixtures).
_TOOL = Path(__file__).resolve().parents[2] / "dev" / "tools" / "build_container.py"
_spec = importlib.util.spec_from_file_location("build_container", _TOOL)
bc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bc)

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c626001000000ffff03000006000557bfabd40000000049454e44ae426082")


def _seed_branding(files):
    """Write {relposix: bytes} under the isolated branding_root(); returns it."""
    root = g.branding_root()
    for rel, data in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return root


# A minimal sealed-definitions donor so these tests don't depend on the private companion
# repo -- the roster no longer lives in source, so build_container reads it from a donor.
_TEST_DONOR = {
    "roster": [{"id": "first-light", "name": "First Light", "icon": "*", "desc": "d",
                "metric": "images", "threshold": 1, "tier": "common", "bucket": "milestone"}],
    "skins": [{"id": "moonglade", "name": "Moonglade", "free": True, "desc": "d"}],
    "skin_unlock": {}, "ach_criteria": {}, "ladder_tracks": [], "poke_lines": {},
}


def _run(monkeypatch, *argv):
    """Invoke the tool's main() with argv, the way the CLI would. Auto-supplies a test
    donor (so the build never reaches for the private repo) unless argv sets one."""
    argv = list(argv)
    if "--donor" not in argv:
        donor_file = g.branding_root().parent / "_test_donor.json"
        donor_file.write_text(json.dumps(_TEST_DONOR), encoding="utf-8")
        argv += ["--donor", str(donor_file)]
    monkeypatch.setattr(bc.sys, "argv", ["build_container.py", *argv])
    return bc.main()


def _out_path():
    return g._container_path()          # the builder's default IS where the app reads


# ---------------------------------------------------------------------------
# gather(): the _thumbs exclusion
# ---------------------------------------------------------------------------
def test_gather_excludes_thumbs_at_any_depth():
    # Seed rels are CODED (built from the ROLE_CODE map -- the real tree gather()
    # packs is coded end to end); _thumbs stays a LITERAL name at any depth.
    root = _seed_branding({
        "banner.png": PNG_1PX,
        g._role_rel("marks", "marks.json"): b'{"marks":[]}',
        g._role_rel("marks", "mark_4.png"): PNG_1PX,
        g._role_rel("badges", "first-light.png"): PNG_1PX,
        "_thumbs/cache.png": b"REGENERABLE",                          # top-level cache dir
        g._role_rel("marks", "_thumbs", "mark_4.png"): b"REGENERABLE",  # nested cache dir
    })
    got = bc.gather(root)
    assert set(got) == {"banner.png",
                        g._role_rel("marks", "marks.json"),
                        g._role_rel("marks", "mark_4.png"),
                        g._role_rel("badges", "first-light.png")}
    assert all("_thumbs" not in rel for rel in got)
    assert got[g._role_rel("marks", "mark_4.png")] == PNG_1PX  # real bytes, posix keys


# ---------------------------------------------------------------------------
# The happy path: build -> verified container + manifest
# ---------------------------------------------------------------------------
def test_build_writes_a_verified_container_and_manifest(monkeypatch):
    _seed_branding({"banner.png": PNG_1PX,
                    g._role_rel("marks", "marks.json"): b'{"marks":[]}',
                    g._role_rel("marks", "mark_4.png"): PNG_1PX})
    _run(monkeypatch)                                 # no args -> defaults

    out = _out_path()
    assert out.is_file()
    box = mc.open_container(out)
    assert box is not None
    assert box.get("banner.png") == PNG_1PX
    assert box.get(g._role_rel("marks", "marks.json")) == b'{"marks":[]}'
    # The tool packs the SEALED achievement definitions (from the donor) as a reserved
    # payload -- the roster no longer lives in source, so this is the donor, byte-for-byte.
    assert box.payload("achievements") == json.dumps(_TEST_DONOR, separators=(",", ":")).encode("utf-8")

    # Manifest describes the WHOLE FILE (what the downloader fetches + verifies),
    # version "1" on a fresh manifest, and no urls until one is supplied.
    man = ma.read_manifest()
    assert man is not None
    assert man["version"] == "1"
    assert man["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert man["size"] == out.stat().st_size
    assert man["urls"] == []


def test_changed_bytes_without_url_fails_closed(monkeypatch):
    """Release-integrity guard (adversarial, 2026-08-22): if the container bytes change
    (new sha256) but no --url is given, the prior manifest's URL still points at the OLD
    file -- a fresh install would download bytes that fail the new checksum and end up
    undressed. The builder must refuse rather than write that impossible manifest."""
    ma.write_manifest("3", "deadbeef" * 8, 123, ["https://old.example/moonglade.mgpack"])
    _seed_branding({"banner.png": PNG_1PX})
    with pytest.raises(SystemExit):
        _run(monkeypatch)                             # new bytes, no --url -> refuse
    # the prior manifest is left untouched (NOT bumped to a broken state)
    man = ma.read_manifest()
    assert man["version"] == "3" and man["sha256"] == "deadbeef" * 8


def test_version_bumps_and_urls_carry_forward_on_identical_bytes(monkeypatch):
    """Carry the prior URL forward ONLY when the rebuild is byte-identical (same sha) --
    then the existing URL genuinely still serves those bytes. First build sets the URL;
    an identical rebuild with no --url keeps it and bumps the version.

    --built-at is PINNED on both builds (build stamp, 2026-09-07): the build time is now
    inside the container, so reproducing bytes means reproducing that too. Without the pin
    this test passed or failed on whether the two builds landed in the same wall-clock
    second -- see the next test, which asserts the unpinned rebuild fails closed."""
    _seed_branding({"banner.png": PNG_1PX})
    pin = ["--built-at", "2026-09-07T12:00:00Z"]
    _run(monkeypatch, "--url", "https://old.example/moonglade.mgpack", *pin)  # url + real sha
    v1 = ma.read_manifest()
    _run(monkeypatch, *pin)                           # rebuild identical bytes, no --url
    man = ma.read_manifest()
    assert man["urls"] == ["https://old.example/moonglade.mgpack"]    # carried forward (same bytes)
    assert man["sha256"] == v1["sha256"]                          # identical
    assert int(man["version"]) == int(v1["version"]) + 1          # still bumps


def test_explicit_version_and_urls_override(monkeypatch):
    ma.write_manifest("3", "deadbeef" * 8, 123, ["https://old.example/x"])
    _seed_branding({"banner.png": PNG_1PX})
    _run(monkeypatch, "--version", "9", "--url", "https://a/x", "--url", "https://b/x")

    man = ma.read_manifest()
    assert man["version"] == "9"
    assert man["urls"] == ["https://a/x", "https://b/x"]           # replace, ordered


# ---------------------------------------------------------------------------
# Refusals and safety
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# The donor: the folio donor by default, and every key the v6 pack needed
# ---------------------------------------------------------------------------
def test_the_default_donor_is_the_folio_donor():
    """The pack ships from the folio donor (the full roster plus its poke lines). The old
    default was the earlier sealed donor, so a rebuild that forgot --donor silently shipped
    the old, shorter roster."""
    assert bc.DEFAULT_DONOR.name == "achievements_folio_donor.json"
    assert bc.DEFAULT_DONOR.parent.name == "moonglade-internal"


@pytest.mark.parametrize("missing", ["roster", "skins", "skin_unlock", "ach_criteria",
                                     "ladder_tracks", "poke_lines"])
def test_a_donor_missing_a_v6_key_is_refused_and_nothing_is_written(monkeypatch, missing):
    _seed_branding({"banner.png": PNG_1PX})
    donor = {k: v for k, v in _TEST_DONOR.items() if k != missing}
    donor_file = g.branding_root().parent / "_short_donor.json"
    donor_file.write_text(json.dumps(donor), encoding="utf-8")
    before = _out_path().read_bytes() if _out_path().exists() else None   # the seeded pack
    with pytest.raises(SystemExit) as e:
        _run(monkeypatch, "--donor", str(donor_file))
    assert missing in str(e.value)
    assert (_out_path().read_bytes() if _out_path().exists() else None) == before
    assert ma.read_manifest() is None


def test_a_donor_key_of_the_wrong_shape_is_refused(monkeypatch):
    _seed_branding({"banner.png": PNG_1PX})
    donor_file = g.branding_root().parent / "_bad_donor.json"
    donor_file.write_text(json.dumps(dict(_TEST_DONOR, poke_lines=[])), encoding="utf-8")
    before = _out_path().read_bytes() if _out_path().exists() else None
    with pytest.raises(SystemExit) as e:
        _run(monkeypatch, "--donor", str(donor_file))
    assert "poke_lines" in str(e.value)
    assert (_out_path().read_bytes() if _out_path().exists() else None) == before
    assert ma.read_manifest() is None


def test_refuses_missing_branding(monkeypatch):
    assert not g.branding_root().exists()
    with pytest.raises(SystemExit):
        _run(monkeypatch)


def test_refuses_empty_branding(monkeypatch):
    g.branding_root().mkdir(parents=True, exist_ok=True)          # exists but empty
    _out_path().unlink(missing_ok=True)   # drop the conftest fixture's seed container first
    with pytest.raises(SystemExit):
        _run(monkeypatch)
    assert not _out_path().exists()


def test_verification_failure_deletes_output_and_writes_no_manifest(monkeypatch):
    """If the cold read-back can't verify, the tool must delete the container and
    fail loudly -- and must NOT have written a manifest pointing at bytes it just
    deleted (write_manifest runs only AFTER verification passes)."""
    _seed_branding({"banner.png": PNG_1PX})
    monkeypatch.setattr(bc.mc, "open_container", lambda p: None)  # force cold-open fail
    with pytest.raises(SystemExit):
        _run(monkeypatch)
    assert not _out_path().exists()
    assert ma.read_manifest() is None


# ---------------------------------------------------------------------------
# The build stamp (moonglade_container TOC schema 1, 2026-09-07)
# ---------------------------------------------------------------------------
def test_the_build_stamps_provenance_into_the_container(monkeypatch):
    """The packer writes `built_at` (ISO-8601 UTC) and `builder` (its own version string,
    with the app version) into the TOC, alongside the `schema` and `content_sha256` the
    format writes for itself -- so a pack can be traced to when and what cut it."""
    _seed_branding({"banner.png": PNG_1PX})
    _run(monkeypatch, "--built-at", "2026-09-07T12:00:00Z")

    stamp = mc.open_container(_out_path()).stamp()
    assert stamp["schema"] == mc.SUPPORTED_SCHEMA
    assert stamp["built_at"] == "2026-09-07T12:00:00Z"
    assert stamp["builder"] == bc.builder_stamp() == "build_container.py/1 moonglade/%s" % (
        core.__version__)
    assert len(stamp["content_sha256"]) == 64        # a real digest, not a placeholder


def test_the_default_build_time_is_utc_now(monkeypatch):
    """No --built-at means the clock: second-resolution ISO-8601 UTC, Z-suffixed."""
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", bc.utc_now_iso())
    before = bc.utc_now_iso()
    _seed_branding({"banner.png": PNG_1PX})
    _run(monkeypatch)
    after = bc.utc_now_iso()
    got = mc.open_container(_out_path()).stamp()["built_at"]
    assert before <= got <= after                    # ISO-8601 UTC sorts as text


def test_verification_fails_loudly_if_the_stamp_does_not_round_trip(monkeypatch):
    """The stamp is verified on the same terms as the bytes: a container whose provenance
    did not survive the cold re-open is deleted, not published."""
    _seed_branding({"banner.png": PNG_1PX})

    real_write = bc.mc.write_container

    def drop_the_stamp(out, assets, payloads=None, builder="", built_at=""):
        return real_write(out, assets, payloads)     # writes schema/digest, no provenance

    monkeypatch.setattr(bc.mc, "write_container", drop_the_stamp)
    with pytest.raises(SystemExit) as e:
        _run(monkeypatch)
    assert "build stamp mismatch" in str(e.value)
    assert not _out_path().exists()                  # and the bad container is gone
    assert ma.read_manifest() is None


def test_an_unpinned_rebuild_is_new_bytes_and_fails_closed_without_a_url(monkeypatch):
    """The consequence of stamping the build time INSIDE the file, stated out loud: two
    builds of the same tree are no longer byte-identical unless --built-at is pinned. The
    release-integrity rule then does exactly what it should -- the sha moved, so the prior
    URL no longer serves these bytes, so the manifest is not written."""
    _seed_branding({"banner.png": PNG_1PX})
    _run(monkeypatch, "--url", "https://old.example/moonglade.mgpack",
         "--built-at", "2026-09-07T12:00:00Z")
    first = ma.read_manifest()

    with pytest.raises(SystemExit) as e:
        _run(monkeypatch, "--built-at", "2026-09-07T12:00:01Z")   # one second later
    assert "no --url was given" in str(e.value)
    assert "--built-at" in str(e.value)              # the message names the way out
    assert ma.read_manifest() == first              # prior manifest untouched


# ---------------------------------------------------------------------------
# The carried login set (Session I decision 4b): the pack build writes the app's own copy
# of the login mascot and banner, so the sign-in page looks finished before a pack exists.
# ---------------------------------------------------------------------------
def _png_bytes(size, rgba=(120, 90, 180, 255)):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGBA", size, rgba).save(buf, "PNG")
    return buf.getvalue()


def _decode_uri(uri):
    import base64
    import io
    from PIL import Image
    assert uri.startswith("data:image/webp;base64,")
    return Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))


def _exports(js):
    return dict(re.findall(r'export const (\w+) = "([^"]+)";', js))


def test_the_build_writes_the_carried_login_set_beside_the_container(monkeypatch, tmp_path):
    _seed_branding({"banner.png": PNG_1PX,
                    g._role_rel("system", "login_nel.png"): _png_bytes((488, 480)),
                    g._flat_default_rel("banner_login"): _png_bytes((1920, 480))})
    out_js = tmp_path / "carried" / "loginArt.js"
    _run(monkeypatch, "--carry-to", str(out_js))
    ex = _exports(out_js.read_text(encoding="utf-8"))
    nel, ban = _decode_uri(ex["LOGIN_NEL"]), _decode_uri(ex["LOGIN_BANNER"])
    assert (nel.format, nel.size[0]) == ("WEBP", bc.CARRIED_NEL_W)
    assert (ban.format, ban.size) == ("WEBP", (bc.CARRIED_BANNER_W, bc.CARRIED_BANNER_H))


def test_a_tree_without_login_art_leaves_the_carried_set_alone(monkeypatch, tmp_path):
    _seed_branding({"banner.png": PNG_1PX})
    out_js = tmp_path / "loginArt.js"
    _run(monkeypatch, "--carry-to", str(out_js))
    assert not out_js.exists()
    assert bc.write_carried_login_art(g.branding_root(), out_js) is None


def test_the_committed_carried_set_is_small_and_decodes():
    """The handoff's budget is about 120 KB for the two together, in the app bundle."""
    js = bc.carried_login_js_path().read_text(encoding="utf-8")
    ex = _exports(js)
    assert set(ex) == {"LOGIN_NEL", "LOGIN_BANNER"}
    raw = sum(len(v.split(",", 1)[1]) * 3 // 4 for v in ex.values())
    assert raw <= 130 * 1024, "carried login set is %d bytes" % raw
    assert _decode_uri(ex["LOGIN_NEL"]).size[0] == bc.CARRIED_NEL_W
    assert _decode_uri(ex["LOGIN_BANNER"]).size == (bc.CARRIED_BANNER_W, bc.CARRIED_BANNER_H)
