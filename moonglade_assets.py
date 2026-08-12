"""Acquiring the asset container over the network: the manifest format, the
version marker, and the fetch job (start, stream+verify+swap, poll).

Placement of the resulting UI moment (Setup Wizard phase vs. standalone) was
ruled by the owner 2026-08-10 -- see docs/DECISIONS.md. This module is the
engine only, deliberately UI-agnostic: it exposes a start/poll pair any caller
can drive (the wizard, a standalone boot check, a future settings page).

MANIFEST. moonglade_manifest.json, committed at the app root -- a FEW LINES
telling every install what container it should have and where to get it:
    {"version": "1", "sha256": "<hex>", "size": <bytes>, "urls": [...]}
`urls` is an ORDERED mirror list (first that works wins); it may be EMPTY
during development (no release cut yet) -- fetch then fails cleanly with
"no download source configured", never a crash. Built/refreshed by
tools/build_container.py --write-manifest, from a REAL container.

VERSION MARKER. <container>.version, a tiny sidecar written ONLY right after
a download's sha256 verification passes. This is what makes a boot-time
"is my container current" check cheap: comparing a few bytes, not re-hashing
a 392 MB file on every page load. A container that arrived some other way
(hand-copied from another machine, an older build) has no marker yet -- it is
treated as present-but-unverified, which is enough to dress the app; a real
version mismatch only shows once the marker disagrees with the manifest.
"""
import hashlib
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_CHUNK = 1 << 20    # 1 MiB per read -- coarse enough for real throughput,
                    # fine enough for smooth progress and quick cancel response.


def _friendly_error(exc):
    """Map a low-level download exception to a plain-language reason -- found
    live 2026-08-10 checking the interrupted phase: a raw mirror-refused
    connection surfaced as '<urlopen error [WinError 10061] No connection
    could be made because the target machine actively refused it>' straight
    into the wizard's UI. The owner's users are not expected to parse socket
    errno text (see the 'plain language, not programmer' standing rule), so
    every path here classifies instead of relaying str(exc)."""
    if isinstance(exc, ValueError) and "checksum" in str(exc):
        return "the download didn't match what was expected"
    if isinstance(exc, urllib.error.HTTPError):
        return "the server reported an error (HTTP %s)" % exc.code
    if isinstance(exc, (urllib.error.URLError, OSError, ConnectionError, TimeoutError)):
        return "couldn't reach the download server"
    return "an unexpected error interrupted the download"


def manifest_path():
    return Path(__file__).resolve().parent / "moonglade_manifest.json"


def read_manifest():
    """The current manifest dict, or None if absent/corrupt -- never raises.
    A missing/broken manifest means 'nothing to fetch', not a crash: an old
    checkout without this file at all must still boot and run undressed."""
    try:
        data = json.loads(manifest_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("sha256") or not data.get("version"):
        return None
    data.setdefault("urls", [])
    return data


def write_manifest(version, sha256_hex, size, urls=None):
    manifest_path().write_text(json.dumps(
        {"version": str(version), "sha256": sha256_hex, "size": int(size),
         "urls": list(urls or [])}, indent=2) + "\n", encoding="utf-8")


def _version_marker_path(container_path):
    return container_path.with_suffix(container_path.suffix + ".version")


def _read_marker(container_path):
    try:
        return json.loads(_version_marker_path(container_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_marker(container_path, manifest):
    _version_marker_path(container_path).write_text(json.dumps(
        {"version": manifest["version"], "sha256": manifest["sha256"]}), encoding="utf-8")


def needs_download(container_path, manifest=None):
    """True if `container_path` should be (re)fetched: missing entirely, or
    its version marker disagrees with the current manifest. A container with
    NO marker but that DOES exist (hand-copied, pre-downloader) counts as
    satisfied -- it dresses the app; only a confirmed version mismatch
    re-triggers a fetch, never a guess."""
    manifest = manifest if manifest is not None else read_manifest()
    if manifest is None:
        return False           # nothing to compare against -- nothing to fetch
    if not container_path.exists():
        return True
    marker = _read_marker(container_path)
    if marker is None:
        return False           # present, unverified -- treated as satisfied
    return marker.get("sha256") != manifest["sha256"]


class AssetFetchJob:
    """Single-flight background download: start() launches a daemon thread
    (a second start() while one is running is a no-op, matching the Panel job
    runner's own single-flight contract), status() is a cheap dict read under
    a lock. Streams through a .part file in the SAME directory as the final
    target (atomic os.replace needs same-filesystem), verifies the full
    sha256 cold before the swap, and falls through the manifest's mirror list
    in order on any network failure -- one bad mirror never fails the job
    while others remain untried."""

    def __init__(self, container_path):
        self.container_path = Path(container_path)
        self._lock = threading.Lock()
        self._state = {"status": "idle", "downloaded": 0, "total": 0,
                       "speed_bps": 0.0, "eta_seconds": None, "error": None,
                       "url_index": 0}
        self._thread = None
        self._cancel = threading.Event()

    def status(self):
        with self._lock:
            return dict(self._state)

    def start(self, manifest=None, opener=None):
        """Returns True if a fetch was (newly) started, False if one was
        already running (the caller's 409, matching /api/panel/run)."""
        manifest = manifest if manifest is not None else read_manifest()
        with self._lock:
            if self._state["status"] == "running":
                return False
            if manifest is None:
                self._state.update(status="failed", error="no asset manifest present")
                return False
            urls = manifest.get("urls") or []
            if not urls:
                self._state.update(status="failed",
                                   error="no download source configured")
                return False
            self._state = {"status": "running", "downloaded": 0,
                           "total": int(manifest.get("size") or 0),
                           "speed_bps": 0.0, "eta_seconds": None, "error": None,
                           "url_index": 0}
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._run, args=(manifest, opener), daemon=True,
            name="asset-fetch")
        self._thread.start()
        return True

    def cancel(self):
        self._cancel.set()

    def _run(self, manifest, opener):
        urls = manifest.get("urls") or []
        last_err = None
        for i, url in enumerate(urls):
            with self._lock:
                if self._state["status"] != "running":
                    return          # cancelled between attempts
                self._state["url_index"] = i
                self._state["downloaded"] = 0
            try:
                self._attempt(url, manifest, opener)
                return              # success -- _attempt already set status=done
            except _Cancelled:
                with self._lock:
                    self._state.update(status="idle", error=None)
                return
            except Exception as e:                     # noqa: BLE001
                last_err = _friendly_error(e)
                continue            # try the next mirror
        with self._lock:
            self._state.update(status="failed",
                               error=last_err or "every download source failed")

    def _attempt(self, url, manifest, opener):
        opener = opener or urllib.request.urlopen
        tmp_fd, tmp_name = tempfile.mkstemp(
            dir=str(self.container_path.parent), prefix=".moonglade-fetch-", suffix=".part")
        hasher = hashlib.sha256()
        start = time.monotonic()
        try:
            with os.fdopen(tmp_fd, "wb") as fh, opener(url, timeout=30) as resp:
                total = int(resp.headers.get("Content-Length") or manifest.get("size") or 0)
                with self._lock:
                    self._state["total"] = total or self._state["total"]
                downloaded = 0
                while True:
                    if self._cancel.is_set():
                        raise _Cancelled()
                    chunk = resp.read(_CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    hasher.update(chunk)
                    downloaded += len(chunk)
                    elapsed = max(time.monotonic() - start, 0.001)
                    speed = downloaded / elapsed
                    remaining = self._state["total"] - downloaded
                    with self._lock:
                        self._state["downloaded"] = downloaded
                        self._state["speed_bps"] = speed
                        self._state["eta_seconds"] = (
                            round(remaining / speed) if speed > 0 and remaining > 0 else None)
            if hasher.hexdigest() != manifest["sha256"]:
                raise ValueError("checksum mismatch after download")
            os.replace(tmp_name, str(self.container_path))    # atomic same-filesystem swap
            _write_marker(self.container_path, manifest)
            with self._lock:
                self._state.update(status="done", eta_seconds=0)
        finally:
            # Any path that did NOT reach os.replace still has a .part file to clean up
            # (success already renamed it away, so this is a no-op then).
            try:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            except OSError:
                pass


class _Cancelled(Exception):
    pass
