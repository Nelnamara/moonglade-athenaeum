"""The asset container's first-run fetch engine: the manifest, the version
marker, and AssetFetchJob's start/stream/verify/swap/retry/mirror-fallback
behaviour. Decision record: docs/DECISIONS.md "The asset container, re-scoped
from scratch" (2026-08-10). Deliberately UI-agnostic -- these tests never touch
the Setup Wizard; placement of the resulting screen is a frontend decision this
engine doesn't know or care about.
"""
import hashlib
import json
import time

import pytest

import moonglade_assets as ma
from tests.conftest import login_client

REAL_BYTES = b"\x89PNG" + b"X" * 4093   # a stand-in "container": size/hash matter, not content


class _FakeResponse:
    """Minimal urlopen-response stand-in: a context manager with .headers and
    .read(n). Feeds bytes in fixed-size pieces so a real chunk loop is
    exercised, not a single-shot read. `delay` sleeps per chunk -- enough for
    a polling test to actually observe an in-flight state, not so much it
    makes the suite slow."""

    def __init__(self, data, chunk=1024, content_length=None, delay=0.0):
        self._data = data
        self._chunk = chunk
        self._pos = 0
        self._delay = delay
        self.headers = {"Content-Length": str(
            content_length if content_length is not None else len(data))}

    def read(self, n):
        if self._delay:
            time.sleep(self._delay)
        end = min(self._pos + min(n, self._chunk), len(self._data))
        out = self._data[self._pos:end]
        self._pos = end
        return out

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(data, fail_first_n=0, chunk=1024, delay=0.0):
    """A fake `opener(url, timeout=...)` -- the first `fail_first_n` calls
    raise (simulating a dead mirror), then it succeeds."""
    calls = {"n": 0}

    def _open(url, timeout=30):
        calls["n"] += 1
        if calls["n"] <= fail_first_n:
            raise OSError("mirror %s is down" % url)
        return _FakeResponse(data, chunk=chunk, delay=delay)
    _open.calls = calls
    return _open


def _manifest_for(data, urls=("https://example.invalid/a.dat",)):
    return {"version": "1", "sha256": hashlib.sha256(data).hexdigest(),
           "size": len(data), "urls": list(urls)}


# ---------------------------------------------------------------------------
# Manifest + version marker
# ---------------------------------------------------------------------------
def test_read_manifest_missing_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(ma, "manifest_path", lambda: tmp_path / "nope.json")
    assert ma.read_manifest() is None


def test_read_manifest_corrupt_is_none(tmp_path, monkeypatch):
    p = tmp_path / "m.json"
    p.write_text("not json")
    monkeypatch.setattr(ma, "manifest_path", lambda: p)
    assert ma.read_manifest() is None


def test_read_manifest_missing_required_fields_is_none(tmp_path, monkeypatch):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"urls": ["https://x"]}))   # no version/sha256
    monkeypatch.setattr(ma, "manifest_path", lambda: p)
    assert ma.read_manifest() is None


def test_write_then_read_manifest_round_trips(tmp_path, monkeypatch):
    p = tmp_path / "m.json"
    monkeypatch.setattr(ma, "manifest_path", lambda: p)
    ma.write_manifest("3", "ab" * 32, 12345, ["https://a", "https://b"])
    m = ma.read_manifest()
    assert m == {"version": "3", "sha256": "ab" * 32, "size": 12345,
                "urls": ["https://a", "https://b"]}


def test_needs_download_no_manifest_is_false(tmp_path):
    assert ma.needs_download(tmp_path / "c.dat", manifest=None) is False


def test_needs_download_missing_file_is_true(tmp_path):
    manifest = _manifest_for(REAL_BYTES)
    assert ma.needs_download(tmp_path / "missing.dat", manifest) is True


def test_needs_download_present_no_marker_but_readable_is_false(tmp_path):
    """A REAL container that exists but never went through the downloader
    (hand-copied, pre-downloader install) counts as satisfied -- it opens and
    dresses the app; only a version mismatch re-triggers a fetch."""
    import moonglade_container as mc
    c = tmp_path / "c.dat"
    mc.write_container(str(c), {"_seed.txt": b"x"}, {})
    manifest = _manifest_for(c.read_bytes())
    assert ma._read_marker(c) is None
    assert ma._container_readable(c) is True
    assert ma.needs_download(c, manifest) is False


def test_needs_download_present_no_marker_but_unreadable_is_true(tmp_path):
    """A present-but-UNREADABLE `.dat` with no marker -- a stale hand-copied
    pack from an older container format (a v1 pack under the v2 reader) or a
    truncated file -- must re-trigger the fetch, not leave the app silently
    undressed forever with no signal (adversarial finding, 2026-08-22)."""
    c = tmp_path / "c.dat"
    c.write_bytes(b"MGC0 old-format, not this build's container" + bytes(300))
    manifest = _manifest_for(c.read_bytes())   # marker-less: sha is not consulted
    assert ma._read_marker(c) is None
    assert ma._container_readable(c) is False
    assert ma.needs_download(c, manifest) is True


def test_needs_download_marker_matches_is_false(tmp_path):
    c = tmp_path / "c.dat"
    c.write_bytes(REAL_BYTES)
    manifest = _manifest_for(REAL_BYTES)
    ma._write_marker(c, manifest)
    assert ma.needs_download(c, manifest) is False


def test_needs_download_marker_stale_is_true(tmp_path):
    c = tmp_path / "c.dat"
    c.write_bytes(REAL_BYTES)
    old_manifest = _manifest_for(REAL_BYTES)
    ma._write_marker(c, old_manifest)
    new_manifest = _manifest_for(b"different content entirely" * 100)
    assert ma.needs_download(c, new_manifest) is True


# ---------------------------------------------------------------------------
# AssetFetchJob
# ---------------------------------------------------------------------------
def _wait_done(job, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = job.status()
        if st["status"] in ("done", "failed", "idle"):
            return st
        time.sleep(0.02)
    pytest.fail("job never reached a terminal state")


def test_successful_fetch_writes_verified_file_and_marker(tmp_path):
    target = tmp_path / "moonglade.dat"
    manifest = _manifest_for(REAL_BYTES)
    job = ma.AssetFetchJob(target)
    started = job.start(manifest=manifest, opener=_opener(REAL_BYTES))
    assert started is True
    st = _wait_done(job)
    assert st["status"] == "done"
    assert target.read_bytes() == REAL_BYTES
    assert not list(tmp_path.glob(".moonglade-fetch-*")), "leftover .part file"
    marker = ma._read_marker(target)
    assert marker == {"version": "1", "sha256": manifest["sha256"]}


def test_progress_updates_during_download(tmp_path):
    target = tmp_path / "moonglade.dat"
    data = REAL_BYTES * 50   # big enough to see multiple chunks land
    manifest = _manifest_for(data)
    job = ma.AssetFetchJob(target)
    # A small per-chunk delay so the poller below is guaranteed a window to
    # observe an in-flight state -- an instant fake download can finish
    # between two poll iterations and make this assertion vacuous.
    job.start(manifest=manifest, opener=_opener(data, chunk=512, delay=0.01))
    seen_partial = False
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        st = job.status()
        if 0 < st["downloaded"] < st["total"]:
            seen_partial = True
            assert st["total"] == len(data)
            break
        if st["status"] in ("done", "failed"):
            break
        time.sleep(0.005)
    _wait_done(job)
    assert seen_partial, "never observed a genuine in-flight progress reading"


def test_checksum_mismatch_fails_and_leaves_no_partial_file(tmp_path):
    target = tmp_path / "moonglade.dat"
    manifest = _manifest_for(REAL_BYTES)
    job = ma.AssetFetchJob(target)
    # opener serves DIFFERENT bytes than the manifest promises -- checksum must catch it.
    job.start(manifest=manifest, opener=_opener(b"WRONG BYTES" * 400))
    st = _wait_done(job)
    assert st["status"] == "failed"
    assert not target.exists()
    assert not list(tmp_path.glob(".moonglade-fetch-*"))


def test_mirror_fallback_tries_next_url_on_failure(tmp_path):
    target = tmp_path / "moonglade.dat"
    manifest = _manifest_for(REAL_BYTES, urls=["https://dead.invalid/a", "https://good.invalid/b"])
    job = ma.AssetFetchJob(target)
    opener = _opener(REAL_BYTES, fail_first_n=1)
    job.start(manifest=manifest, opener=opener)
    st = _wait_done(job)
    assert st["status"] == "done"
    assert target.read_bytes() == REAL_BYTES
    assert opener.calls["n"] == 2, "did not actually try a second mirror"


def test_all_mirrors_failing_reports_the_last_error(tmp_path):
    target = tmp_path / "moonglade.dat"
    manifest = _manifest_for(REAL_BYTES, urls=["https://a.invalid", "https://b.invalid"])
    job = ma.AssetFetchJob(target)
    job.start(manifest=manifest, opener=_opener(REAL_BYTES, fail_first_n=99))
    st = _wait_done(job)
    assert st["status"] == "failed"
    assert st["error"]


def test_no_urls_configured_fails_cleanly_not_a_crash(tmp_path):
    target = tmp_path / "moonglade.dat"
    manifest = _manifest_for(REAL_BYTES, urls=[])
    job = ma.AssetFetchJob(target)
    started = job.start(manifest=manifest, opener=_opener(REAL_BYTES))
    assert started is False
    assert job.status()["status"] == "failed"
    assert "no download source" in job.status()["error"]


def test_no_manifest_fails_cleanly(tmp_path):
    job = ma.AssetFetchJob(tmp_path / "moonglade.dat")
    started = job.start(manifest=None, opener=_opener(REAL_BYTES))
    assert started is False
    assert job.status()["status"] == "failed"


def test_single_flight_second_start_is_a_noop_while_running(tmp_path):
    target = tmp_path / "moonglade.dat"
    manifest = _manifest_for(REAL_BYTES * 200)   # big enough to still be running
    job = ma.AssetFetchJob(target)
    slow_opener = _opener(REAL_BYTES * 200, chunk=16)   # tiny chunks -> stays "running" a while
    job.start(manifest=manifest, opener=slow_opener)
    assert job.status()["status"] == "running"
    second = job.start(manifest=manifest, opener=_opener(REAL_BYTES))
    assert second is False, "a second start() while running must be a no-op, not a new job"
    _wait_done(job)


def test_cancel_stops_the_download_and_leaves_no_partial(tmp_path):
    target = tmp_path / "moonglade.dat"
    manifest = _manifest_for(REAL_BYTES * 500)
    job = ma.AssetFetchJob(target)
    job.start(manifest=manifest, opener=_opener(REAL_BYTES * 500, chunk=16))
    time.sleep(0.05)
    job.cancel()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and job.status()["status"] == "running":
        time.sleep(0.02)
    assert job.status()["status"] != "running"
    assert not target.exists()
    assert not list(tmp_path.glob(".moonglade-fetch-*"))


# ---------------------------------------------------------------------------
# Live route + boot payload, WSGI client
# ---------------------------------------------------------------------------
def test_boot_payload_reflects_needs_assets(tmp_path):
    # conftest's autouse _isolated_asset_manifest already points manifest_path()
    # at a tmp_path file that doesn't exist -- read_manifest() -> None ->
    # needs_download() -> False, exactly like a checkout with no manifest at all.
    client = login_client(tmp_path)
    r = client.get("/")
    assert r.status_code == 200
    assert 'needs_assets' in r.text


def test_assets_status_route_reports_shape(tmp_path):
    client = login_client(tmp_path)
    r = client.get("/api/assets/status")
    assert r.status_code == 200
    d = r.get_json()
    for key in ("needs", "manifest_present", "status", "downloaded", "total", "error"):
        assert key in d
    assert d["manifest_present"] is False and d["needs"] is False, (
        "no manifest at all must never present as 'a download is needed'")


def test_assets_status_route_reflects_a_real_isolated_manifest(tmp_path):
    """A real manifest exists (in THIS test's isolated tmp_path -- proves the
    conftest fixture actually redirects the resolver, not just that the
    no-manifest case degrades safely) but the container doesn't -- needs=True."""
    ma.write_manifest("1", "ab" * 32, 4096, ["https://example.invalid/a.dat"])
    client = login_client(tmp_path)
    r = client.get("/api/assets/status")
    d = r.get_json()
    assert d["manifest_present"] is True
    assert d["needs"] is True


def test_assets_fetch_route_admits_a_signed_in_lan_session(tmp_path):
    """LOGIN tier since 2026-08-26 (was LOCALHOST). A signed-in LAN device must
    reach this route: the Setup Wizard on a LAN device is where a first run hits
    it, and the localhost gate made that phase unreachable from the only machine
    that needed it. This asserts the GATE lets the request through, not that the
    fetch succeeds -- there is no manifest in this tmp_path, so the handler
    answers its own 200 {"error": "no asset manifest present"} and no download
    is ever started."""
    client = login_client(tmp_path)
    r = client.post("/api/assets/fetch", environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code != 403, "the LAN gate should be gone"
    assert r.get_json().get("error") == "no asset manifest present"


def test_assets_fetch_route_still_refuses_an_anonymous_lan_caller(tmp_path):
    """LOGIN is not PUBLIC: dropping the localhost half must not drop the
    session half with it."""
    from moonglade_gallery import create_app
    client = create_app(tmp_path).test_client()
    r = client.post("/api/assets/fetch", environ_overrides={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code == 401
    assert r.get_json() == {"error": "authentication required"}
