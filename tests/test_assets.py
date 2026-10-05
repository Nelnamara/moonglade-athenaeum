"""The asset container's first-run fetch engine: the manifest, the version
marker, and AssetFetchJob's start/stream/verify/swap/retry/mirror-fallback
behaviour. Decision record: docs/DECISIONS.md "The asset container, re-scoped
from scratch" (2026-08-10). Deliberately UI-agnostic -- these tests never touch
the Setup Wizard; placement of the resulting screen is a frontend decision this
engine doesn't know or care about.
"""
import hashlib
import json
import logging
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


def test_needs_download_present_no_marker_size_mismatch_is_true(tmp_path):
    """A readable, markerless hand-copied pack whose SIZE disagrees with the
    manifest is an OUTDATED pack (the version-bump case) -- re-fetch it rather
    than trust it forever. Regression guard for 2026-09-08: a D: install carried
    the v3 pack under a v4 manifest and never re-fetched, because a markerless
    readable pack was trusted regardless of size."""
    import moonglade_container as mc
    c = tmp_path / "c.dat"
    mc.write_container(str(c), {"_seed.txt": b"x"}, {})
    real = _manifest_for(c.read_bytes())
    manifest = dict(real, size=real["size"] + 4096)   # manifest wants a different-sized pack
    assert ma._read_marker(c) is None
    assert ma._container_readable(c) is True
    assert ma.needs_download(c, manifest) is True


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
_WAIT_DONE_TIMEOUT = 5.0   # the terminal-state deadline every job test below is judged by


def _wait_done(job, timeout=_WAIT_DONE_TIMEOUT):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        st = job.status()
        if st["status"] in ("done", "failed", "idle"):
            return st
        time.sleep(0.02)
    pytest.fail("job never reached a terminal state")


def test_successful_fetch_writes_verified_file_and_marker(tmp_path):
    target = tmp_path / "moonglade.mgpack"
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


# The fake stream the progress test runs on. Named, because the guard below is what stops
# them drifting back into a budget that races _wait_done rather than measuring progress.
_PROGRESS_DATA = REAL_BYTES * 50   # big enough to see multiple chunks land
_PROGRESS_CHUNK = 4096
_PROGRESS_DELAY = 0.01             # _FakeResponse.read sleeps this once per read


def _progress_fixture_reads():
    """How many `.read()` calls the progress fixture's stream costs -- every full chunk,
    the short tail if there is one, and the final empty read that ends the loop."""
    full, tail = divmod(len(_PROGRESS_DATA), _PROGRESS_CHUNK)
    return full + (1 if tail else 0) + 1


def test_the_progress_fixture_stays_well_inside_its_deadline():
    """The progress test must fail on PROGRESS, never on the clock.

    2026-09-07: it used to spend ~4.0s of fixture sleeps against `_wait_done`'s 5s
    deadline, and under a loaded machine it was `_wait_done`'s "job never reached a
    terminal state" that fired -- a failure that says nothing about the thing the test
    is for. This pins both halves of the fix from the same constants the test itself
    passes to `_opener`, so neither can move without the other: the sleep budget stays a
    small fraction of the deadline, AND the stream stays a real multi-chunk one with
    plenty of mid-download moments for the poller to catch.
    """
    reads = _progress_fixture_reads()
    budget = reads * _PROGRESS_DELAY
    assert budget < _WAIT_DONE_TIMEOUT / 2, (
        "the progress fixture sleeps {:.2f}s of a {:.1f}s terminal deadline ({} reads x "
        "{}s) -- that is a race with the clock, not a measurement of progress".format(
            budget, _WAIT_DONE_TIMEOUT, reads, _PROGRESS_DELAY))
    assert reads >= 8, (
        "the progress fixture streams in {} reads -- too few to guarantee the poller a "
        "mid-download window, which is the whole point of chunking it".format(reads))


def test_progress_updates_during_download(tmp_path):
    target = tmp_path / "moonglade.mgpack"
    data = _PROGRESS_DATA
    manifest = _manifest_for(data)
    job = ma.AssetFetchJob(target)
    # A small per-chunk delay so the poller below is guaranteed a window to
    # observe an in-flight state -- an instant fake download can finish
    # between two poll iterations and make this assertion vacuous.
    #
    # 2026-09-07: chunk was 512, which is 401 sleeps == ~4.0s of fixture delay against
    # _wait_done's 5s deadline below -- under 20% headroom, and it was _wait_done's
    # "job never reached a terminal state" that fired under load in this wave, not the
    # seen_partial assertion this test is about. _PROGRESS_CHUNK keeps the same shape (a
    # real multi-chunk loop, a mid-download window the 5ms poller cannot miss) at a
    # fraction of the deadline; test_the_progress_fixture_stays_well_inside_its_deadline
    # below holds that margin so it cannot quietly erode again.
    job.start(manifest=manifest, opener=_opener(
        data, chunk=_PROGRESS_CHUNK, delay=_PROGRESS_DELAY))
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
    target = tmp_path / "moonglade.mgpack"
    manifest = _manifest_for(REAL_BYTES)
    job = ma.AssetFetchJob(target)
    # opener serves DIFFERENT bytes than the manifest promises -- checksum must catch it.
    job.start(manifest=manifest, opener=_opener(b"WRONG BYTES" * 400))
    st = _wait_done(job)
    assert st["status"] == "failed"
    assert not target.exists()
    assert not list(tmp_path.glob(".moonglade-fetch-*"))


def test_mirror_fallback_tries_next_url_on_failure(tmp_path):
    target = tmp_path / "moonglade.mgpack"
    manifest = _manifest_for(REAL_BYTES, urls=["https://dead.invalid/a", "https://good.invalid/b"])
    job = ma.AssetFetchJob(target)
    opener = _opener(REAL_BYTES, fail_first_n=1)
    job.start(manifest=manifest, opener=opener)
    st = _wait_done(job)
    assert st["status"] == "done"
    assert target.read_bytes() == REAL_BYTES
    assert opener.calls["n"] == 2, "did not actually try a second mirror"


def test_all_mirrors_failing_reports_the_last_error(tmp_path):
    target = tmp_path / "moonglade.mgpack"
    manifest = _manifest_for(REAL_BYTES, urls=["https://a.invalid", "https://b.invalid"])
    job = ma.AssetFetchJob(target)
    job.start(manifest=manifest, opener=_opener(REAL_BYTES, fail_first_n=99))
    st = _wait_done(job)
    assert st["status"] == "failed"
    assert st["error"]


def test_no_urls_configured_fails_cleanly_not_a_crash(tmp_path):
    target = tmp_path / "moonglade.mgpack"
    manifest = _manifest_for(REAL_BYTES, urls=[])
    job = ma.AssetFetchJob(target)
    started = job.start(manifest=manifest, opener=_opener(REAL_BYTES))
    assert started is False
    assert job.status()["status"] == "failed"
    assert "no download source" in job.status()["error"]


def test_no_manifest_fails_cleanly(tmp_path):
    job = ma.AssetFetchJob(tmp_path / "moonglade.mgpack")
    started = job.start(manifest=None, opener=_opener(REAL_BYTES))
    assert started is False
    assert job.status()["status"] == "failed"


def test_single_flight_second_start_is_a_noop_while_running(tmp_path):
    target = tmp_path / "moonglade.mgpack"
    manifest = _manifest_for(REAL_BYTES * 200)   # big enough to still be running
    job = ma.AssetFetchJob(target)
    slow_opener = _opener(REAL_BYTES * 200, chunk=16)   # tiny chunks -> stays "running" a while
    job.start(manifest=manifest, opener=slow_opener)
    assert job.status()["status"] == "running"
    second = job.start(manifest=manifest, opener=_opener(REAL_BYTES))
    assert second is False, "a second start() while running must be a no-op, not a new job"
    _wait_done(job)


def test_cancel_stops_the_download_and_leaves_no_partial(tmp_path):
    target = tmp_path / "moonglade.mgpack"
    manifest = _manifest_for(REAL_BYTES * 500)
    job = ma.AssetFetchJob(target)
    # A per-chunk delay, not a small chunk, is what keeps this download running at the
    # moment cancel() fires: with no delay a fast runner finished the whole 2 MB inside
    # the 50 ms sleep, the file was legitimately complete, and the "no partial" assertion
    # read a finished download as a leaked one (CI, 2026-09-06).
    job.start(manifest=manifest, opener=_opener(REAL_BYTES * 500, chunk=16, delay=0.02))
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


# ---------------------------------------------------------------------------
# The one-time rename (pack v7): the pack's pre-v7 name -> moonglade.mgpack. A real start
# runs it before anything asks whether the pack is current (main(); its call site is held in
# tests/test_pack_file_name.py). Every case below works in its own folder, so the install
# shape under test is exactly the one written here.
# ---------------------------------------------------------------------------
_NEW = "moonglade.mgpack"


def _old_pack(folder, data=REAL_BYTES, manifest=None):
    """An install's pack under its pre-v7 name, plus the marker a verified download wrote
    beside it when `manifest` is given."""
    old = folder / ma.LEGACY_NAME
    old.write_bytes(data)
    if manifest is not None:
        ma._write_marker(old, manifest)
    return old


def _names(folder):
    return sorted(p.name for p in folder.iterdir())


def _warnings(caplog):
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_rename_moves_the_pack_and_its_marker_and_nothing_downloads(tmp_path):
    """The marker matches the manifest: renamed, marker moved with it, and the check that
    follows asks for no download -- an 800 MB pack is never fetched again for a new name."""
    manifest = _manifest_for(REAL_BYTES)
    _old_pack(tmp_path, manifest=manifest)
    new = tmp_path / _NEW
    assert ma.migrate_legacy_name(new) == "renamed"
    assert new.read_bytes() == REAL_BYTES
    assert ma._read_marker(new) == {"version": "1", "sha256": manifest["sha256"]}
    assert _names(tmp_path) == [_NEW, _NEW + ".version"]
    assert ma.needs_download(new, manifest) is False


def test_rename_then_a_newer_manifest_downloads_over_it_leaving_one_pack(tmp_path):
    """A v6 marker against a v7 manifest: renamed first, then the ordinary verified download
    replaces the renamed file in place. One pack and one marker remain, no orphan copy."""
    v6 = _manifest_for(REAL_BYTES)
    _old_pack(tmp_path, manifest=v6)
    new = tmp_path / _NEW
    assert ma.migrate_legacy_name(new) == "renamed"
    v7_bytes = b"v7 art" * 900
    v7 = dict(_manifest_for(v7_bytes), version="7")
    assert ma.needs_download(new, v7) is True
    job = ma.AssetFetchJob(new)
    assert job.start(manifest=v7, opener=_opener(v7_bytes)) is True
    assert _wait_done(job)["status"] == "done"
    assert new.read_bytes() == v7_bytes
    assert ma._read_marker(new) == {"version": "7", "sha256": v7["sha256"]}
    assert _names(tmp_path) == [_NEW, _NEW + ".version"]


def test_both_names_present_leaves_the_old_copy_untouched_and_says_so(tmp_path, caplog):
    """A pack already under the new name AND one under the old: nothing moves, nothing is
    deleted (a stray asset copy is the owner's to remove), and one warning says it is there."""
    manifest = _manifest_for(REAL_BYTES)
    _old_pack(tmp_path, data=b"an older pack", manifest=manifest)
    new = tmp_path / _NEW
    new.write_bytes(REAL_BYTES)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    with caplog.at_level(logging.INFO):
        assert ma.migrate_legacy_name(new) == "both"
    after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
    assert after == before
    warned = _warnings(caplog)
    assert len(warned) == 1 and ma.LEGACY_NAME in warned[0].getMessage()


def test_neither_name_present_is_a_normal_fresh_download(tmp_path):
    new = tmp_path / _NEW
    assert ma.migrate_legacy_name(new) == "none"
    assert _names(tmp_path) == []
    manifest = _manifest_for(REAL_BYTES)
    assert ma.needs_download(new, manifest) is True
    job = ma.AssetFetchJob(new)
    assert job.start(manifest=manifest, opener=_opener(REAL_BYTES)) is True
    assert _wait_done(job)["status"] == "done"
    assert _names(tmp_path) == [_NEW, _NEW + ".version"]


def test_a_rename_refused_by_a_read_only_folder_logs_and_the_start_carries_on(
        tmp_path, monkeypatch, caplog):
    """A folder the app may not write in refuses the rename with a PermissionError (driven
    here at os.replace, the one call that moves anything, since a read-only folder cannot be
    made portably). One warning, nothing lost or half-moved, no exception -- and the start
    goes on exactly as before the rename existed: no pack under the new name, so the check
    offers the download."""
    manifest = _manifest_for(REAL_BYTES)
    old = _old_pack(tmp_path, manifest=manifest)

    def _refuse(src, dst):
        raise PermissionError(13, "Access is denied", str(src))
    monkeypatch.setattr(ma.os, "replace", _refuse)
    with caplog.at_level(logging.INFO):
        assert ma.migrate_legacy_name(tmp_path / _NEW) == "failed"
    monkeypatch.undo()
    assert old.read_bytes() == REAL_BYTES
    assert _names(tmp_path) == [ma.LEGACY_NAME, ma.LEGACY_NAME + ".version"]
    assert len(_warnings(caplog)) == 1
    assert ma.needs_download(tmp_path / _NEW, manifest) is True


def test_a_marker_left_under_the_new_name_never_vouches_for_the_renamed_pack(tmp_path):
    """A marker can outlive its pack (the pack deleted by hand, the marker not). It describes
    a file that is gone, so it must not vouch for the old pack renamed into its place: the
    renamed pack is judged as unverified (size and readability), never as current."""
    v7_bytes = b"v7 art" * 900
    v7 = dict(_manifest_for(v7_bytes), version="7")
    new = tmp_path / _NEW
    ma._write_marker(new, v7)                              # left behind, no pack beside it
    _old_pack(tmp_path)                                    # an old pack with no marker
    assert ma.migrate_legacy_name(new) == "renamed"
    assert _names(tmp_path) == [_NEW]
    assert ma.needs_download(new, v7) is True              # a different size: fetch v7


def test_a_marker_that_cannot_follow_its_pack_never_leaves_a_stale_one_vouching(
        tmp_path, monkeypatch, caplog):
    """The pack moves but its own marker cannot (a locked file), while a marker left by a
    pack that is gone sits under the new name. That stale marker must not survive to vouch
    for the moved pack: it is dropped first, so the pack is judged unverified."""
    v7_bytes = b"v7 art" * 900
    v7 = dict(_manifest_for(v7_bytes), version="7")
    new = tmp_path / _NEW
    ma._write_marker(new, v7)                              # left behind, no pack beside it
    _old_pack(tmp_path, manifest=_manifest_for(REAL_BYTES))
    real_replace = ma.os.replace

    def _markers_locked(src, dst):
        if str(src).endswith(".version"):
            raise PermissionError(13, "The process cannot access the file", str(src))
        return real_replace(src, dst)
    monkeypatch.setattr(ma.os, "replace", _markers_locked)
    with caplog.at_level(logging.INFO):
        assert ma.migrate_legacy_name(new) == "renamed"
    monkeypatch.undo()
    assert ma._read_marker(new) is None
    assert ma.needs_download(new, v7) is True
    assert len(_warnings(caplog)) == 1
