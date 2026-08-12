"""tools/build_container.py -- the container packer + cold byte-for-byte verify +
manifest writer.

The flagged gap (docs/DECISIONS.md, "P1 test-suite audit", 2026-08-11): the tool
had ZERO test coverage even though it produces the shipped moonglade.dat and the
committed moonglade_manifest.json. Covered here: gather()'s _thumbs exclusion, the
happy-path build (container reads back byte-for-byte + manifest keyed to the whole
file + the achievements payload), the version-bump and url-carry-forward rules,
explicit --version/--url override, the empty/missing-branding refusals, and the
verification-failure-deletes-the-output safety (a silently-wrong container is worse
than none).

The conftest's autouse _isolated_branding + _isolated_asset_manifest fixtures point
branding_root() AND manifest_path() at each test's tmp_path, so main() -- whose
default output is branding_root().parent/moonglade.dat and whose manifest goes
through manifest_path() -- can never touch the developer's real art or the committed
manifest. That the manifest resolver is isolated is what makes it safe to run the
real main() here at all."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

import moonglade_assets as ma
import moonglade_container as mc
import moonglade_gallery as g

# tools/ is not a package; load the script by path (its own module-level code only
# does imports + a sys.path insert, so importing it at collection time is safe --
# it never touches branding_root() until main() runs, under a test's fixtures).
_TOOL = Path(__file__).resolve().parents[1] / "tools" / "build_container.py"
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


def _run(monkeypatch, *argv):
    """Invoke the tool's main() with argv, the way the CLI would."""
    monkeypatch.setattr(bc.sys, "argv", ["build_container.py", *argv])
    return bc.main()


def _out_path():
    return g.branding_root().parent / "moonglade.dat"


# ---------------------------------------------------------------------------
# gather(): the _thumbs exclusion
# ---------------------------------------------------------------------------
def test_gather_excludes_thumbs_at_any_depth():
    root = _seed_branding({
        "banner.png": PNG_1PX,
        "marks/marks.json": b'{"marks":[]}',
        "marks/mark_4.png": PNG_1PX,
        "badges/first-light.png": PNG_1PX,
        "_thumbs/cache.png": b"REGENERABLE",         # top-level cache dir
        "marks/_thumbs/mark_4.png": b"REGENERABLE",  # nested cache dir
    })
    got = bc.gather(root)
    assert set(got) == {"banner.png", "marks/marks.json", "marks/mark_4.png",
                        "badges/first-light.png"}
    assert all("_thumbs" not in rel for rel in got)
    assert got["marks/mark_4.png"] == PNG_1PX        # real bytes, posix keys


# ---------------------------------------------------------------------------
# The happy path: build -> verified container + manifest
# ---------------------------------------------------------------------------
def test_build_writes_a_verified_container_and_manifest(monkeypatch):
    _seed_branding({"banner.png": PNG_1PX,
                    "marks/marks.json": b'{"marks":[]}',
                    "marks/mark_4.png": PNG_1PX})
    _run(monkeypatch)                                 # no args -> defaults

    out = _out_path()
    assert out.is_file()
    box = mc.open_container(out)
    assert box is not None
    assert box.get("banner.png") == PNG_1PX
    assert box.get("marks/marks.json") == b'{"marks":[]}'
    # The tool always packs the live achievement definitions as a reserved payload.
    assert box.payload("achievements") == json.dumps(g.ACHIEVEMENTS).encode("utf-8")

    # Manifest describes the WHOLE FILE (what the downloader fetches + verifies),
    # version "1" on a fresh manifest, and no urls until one is supplied.
    man = ma.read_manifest()
    assert man is not None
    assert man["version"] == "1"
    assert man["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert man["size"] == out.stat().st_size
    assert man["urls"] == []


def test_version_bumps_and_urls_carry_forward(monkeypatch):
    # A prior manifest with a real integer version and a mirror URL already set.
    ma.write_manifest("3", "deadbeef" * 8, 123, ["https://old.example/moonglade.dat"])
    _seed_branding({"banner.png": PNG_1PX})
    _run(monkeypatch)                                 # no --version, no --url

    man = ma.read_manifest()
    assert man["version"] == "4"                                   # 3 -> 4
    assert man["urls"] == ["https://old.example/moonglade.dat"]    # carried forward
    # ...and sha/size now describe the NEW file, not the prior stub.
    out = _out_path()
    assert man["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()
    assert man["sha256"] != "deadbeef" * 8


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
def test_refuses_missing_branding(monkeypatch):
    assert not g.branding_root().exists()
    with pytest.raises(SystemExit):
        _run(monkeypatch)


def test_refuses_empty_branding(monkeypatch):
    g.branding_root().mkdir(parents=True, exist_ok=True)          # exists but empty
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
