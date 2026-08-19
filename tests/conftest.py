"""Shared fixtures for the pixai-gallery-backup test suite."""
import json
import os
import re
from pathlib import Path

import pytest

import moonglade_assets
import moonglade_backup as core
import moonglade_container as _mc
import moonglade_gallery as gallery

# The sealed achievement-definitions donor (private companion repo). The roster no longer
# lives in source, so roster tests need a container built from this.
_SEALED_DONOR = (Path(__file__).resolve().parents[1].parent
                 / "moonglade-internal" / "achievements_sealed_donor.json")


@pytest.fixture(autouse=True)
def _no_pixai_token(monkeypatch):
    """Remove PIXAI_TOKEN so tests that don't need it don't accidentally call live APIs."""
    monkeypatch.delenv("PIXAI_TOKEN", raising=False)


@pytest.fixture(autouse=True)
def _no_ambient_api_key(monkeypatch):
    """Force core._cfg (the import-time config cache) empty for every test, so a
    developer machine behaves exactly like CI.

    CI has no config.json, so at import core._cfg is {}. A developer machine loads
    the real PIXAI_API_KEY into it, and _make_session() falls back to that cache --
    so any test that reaches _make_session() WITHOUT stubbing it passes locally
    (silently borrowing the developer's key) and fails in CI with "No API key
    found." That gap hid eleven such tests until CI caught them. Making the cache
    empty here means local == CI: a test that needs a session must stub
    core._make_session, which is already this suite's convention (test_claims,
    test_jobs, test_kaisuuken, test_generate_model_id, ...). test_filesystem.py did
    exactly this by hand for the same reason before it was generalized here. The
    delenv stops an exported key from re-opening the same hole."""
    monkeypatch.setattr(core, "_cfg", {})
    monkeypatch.delenv("PIXAI_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _isolated_auth_config(tmp_path, monkeypatch):
    """Web-login auth (AUTH_SECRET_KEY/AUTH_USERS) lives in config.json.
    moonglade_gallery.create_app() -- called by ~every test in this suite -- now
    generates + PERSISTS a session secret key via get_or_create_secret_key() the
    first time it runs if config.json has none. Without this fixture, that write
    would land in the REAL, git-ignored config.json next to the checkout (the one
    holding the developer's actual PIXAI_API_KEY), the moment any test calls
    create_app(). Redirect _config_path() to THIS test's own tmp_path instead, so
    the whole suite never reads or mutates the real file.

    Deliberately named plain "config.json" (not some other throwaway name): this
    is the SAME path tests/test_filesystem.py's test_load_config_reads_file /
    test_load_config_missing_returns_empty already write to / expect via their own
    tmp_path, so this fixture is a no-op improvement for them (it just replaces
    their __file__-based resolution with an equivalent tmp_path-based one) rather
    than a second, conflicting source of truth."""
    monkeypatch.setattr(core, "_config_path", lambda: tmp_path / "config.json")


@pytest.fixture(autouse=True)
def _isolated_branding(tmp_path, monkeypatch):
    """Branding art moved OUT of the library folder and into the app root on 2026-07-26, so
    branding_root() now resolves from __file__ -- meaning the real checkout, for every test that
    exercises a mark, badge, mascot or banner.

    Same hazard and same remedy as _isolated_auth_config above: without this, a test that writes a
    fake mark would drop PNGs into the developer's actual branding folder, and a test asserting
    "no marks installed" would instead pick up whatever real art is sitting there -- passing or
    failing based on the machine it ran on rather than the code.

    Redirecting the resolver to tmp_path restores exactly the semantics the whole suite was
    already written against (branding under the per-test directory), so every existing branding
    test keeps working unchanged and this is a no-op for them. Note _branding_path() derives
    branding.json as a SIBLING of this, which lands it at tmp_path/branding.json -- the path
    tests/test_branding.py already expects."""
    monkeypatch.setattr(gallery, "branding_root", lambda: tmp_path / "branding")


@pytest.fixture(autouse=True)
def _isolated_asset_manifest(tmp_path, monkeypatch):
    """moonglade_manifest.json (the first-run asset downloader's manifest,
    2026-08-10) resolves from __file__ in moonglade_assets.py -- same hazard,
    same remedy as _isolated_branding above: without this, every test reading
    it would see the REAL checkout's own committed manifest (once one exists),
    passing or failing based on whatever the developer's machine happens to
    have built, not the code under test.

    Redirected to a tmp_path file that does not exist by default, matching
    read_manifest()'s own contract for "nothing here" (None, not an error) --
    tests that need a real manifest write one via moonglade_assets.write_manifest()
    after this fixture has already pointed the resolver at their own tmp_path."""
    monkeypatch.setattr(moonglade_assets, "manifest_path",
                        lambda: tmp_path / "moonglade_manifest.json")


@pytest.fixture(autouse=True)
def _sealed_roster_container(request, tmp_path):
    """Ship the sealed achievement roster to every test. The definitions live in
    moonglade.dat now (not source), so without a container the roster is empty and every
    roster-dependent test fails. _isolated_branding points branding_root() at
    tmp_path/branding, so _container_path() resolves to tmp_path/moonglade.dat -- write a
    sealed container there from the private donor. Skips silently when the donor is absent
    (public CI without the companion repo): roster tests then see the empty fallback and
    are expected to skip, not fail. The sealed-defs cache is cleared around each test so no
    roster leaks between them (and test_build_container, which rebuilds this same path via
    main(), just overwrites the seed).

    EXCEPTION: the asset-downloader tests (test_assets.py) test downloading a container TO
    this exact path and assert on its presence/absence -- pre-seeding it there breaks them,
    so they opt out."""
    if "test_assets" in request.node.nodeid:
        yield
        return
    if _SEALED_DONOR.is_file():
        defs = json.loads(_SEALED_DONOR.read_text(encoding="utf-8"))
        _mc.write_container(tmp_path / "moonglade.dat", {"_seed.txt": b"x"},
                            {"achievements": json.dumps(defs, separators=(",", ":")).encode("utf-8")})
    gallery._sealed_cache.update(path=None, mtime=None, defs=None)
    gallery._container_cache.update(path=None, mtime=None, box=None)
    yield
    gallery._sealed_cache.update(path=None, mtime=None, defs=None)
    gallery._container_cache.update(path=None, mtime=None, box=None)


@pytest.fixture()
def sealed_donor_present():
    """Skip a test when the private sealed-definitions donor isn't checked out (public
    CI). Use on tests that assert specific roster content (ids, thresholds, the ladder)."""
    if not _SEALED_DONOR.is_file():
        pytest.skip("sealed-definitions donor (private repo) not present")


@pytest.fixture(autouse=True)
def _no_live_watch(monkeypatch):
    """create_app() is called by ~every test in this suite. Without this, its
    live-mirror watcher thread would call _make_session(None), which re-reads THIS
    machine's real config.json (whatever real credentials happen to be there) and open
    a genuine WebSocket to wss://gw.pixai.art -- during every single test run. Skip its
    auto-start entirely in tests; see MOONGLADE_DISABLE_WATCH in moonglade_gallery.py."""
    monkeypatch.setenv("MOONGLADE_DISABLE_WATCH", "1")


@pytest.fixture(autouse=True)
def _no_live_card_network(monkeypatch):
    """The card list/match hit PixAI's live /v2 REST API. Keep unit tests offline by
    default: _rest_get/_rest_post raise (so list_kaisuukens -> [] and match_kaisuuken ->
    None) unless a test overrides them, and user-id resolution is stubbed so _make_session
    (now reached from generation previews via the free/paid note) builds no network.
    Exception: match_kaisuuken(raise_on_error=True) -- the spend-time check inside
    _apply_kaisuuken -- deliberately does NOT fail soft here; it propagates this same
    blocked-network error, so any test that reaches _apply_kaisuuken's auto-match path
    must stub match_kaisuuken (or READ_ONLY-gate/--no-card/--kaisuuken-id past it)."""
    def _blocked(*a, **k):
        raise core.PixAIError("live /v2 REST blocked in tests")
    monkeypatch.setattr(core, "_rest_get", _blocked, raising=False)
    monkeypatch.setattr(core, "_rest_post", _blocked, raising=False)
    # Pin USER_ID so _make_session (now reached from generation previews) never triggers a
    # live resolve_user_id lookup. Setting the global -- not stubbing the function -- keeps
    # resolve_user_id itself testable in test_auth.
    monkeypatch.setattr(core, "USER_ID", "0", raising=False)


@pytest.fixture()
def mock_session(mocker):
    """Return a MagicMock that quacks like a requests.Session."""
    session = mocker.MagicMock()
    return session


# ---------------------------------------------------------------------------
# Real-login test helpers
# ---------------------------------------------------------------------------
# moonglade_gallery.py's _is_authorized_request() has NO localhost bypass -- login is
# required via every path, localhost hostname or IP included. It is true only for a request
# carrying a valid logged-in session. Every test that just needs to be past the
# front door (not testing the gate itself) should log in for real through these
# helpers rather than relying on the test client's default REMOTE_ADDR=127.0.0.1,
# which no longer buys anything. Tests whose entire point IS the gate/boundary
# itself (tests/test_web_auth.py, the "refuses authenticated LAN session" tests,
# anything asserting a 401/403/redirect-to-login) should keep hand-rolling an
# unauthenticated (or deliberately-still-anonymous) client instead -- see
# tests/test_branding.py::test_shortcut_refuses_authenticated_lan_session and
# tests/test_panel.py::test_destructive_action_refuses_authenticated_lan_session,
# which already do the same GET-csrf-then-POST dance these helpers wrap.
_TEST_USERNAME = "tester"
_TEST_PASSWORD = "a-real-test-password-1"


def extract_login_csrf(html_or_boot):
    """CSRF token off GET /login's response: the React shell's window.MG_BOOT JSON
    blob (the ONLY login page since the classic cut, 2026-08-08 -- the classic form
    and its hidden input died with LOGIN_HTML; the classic-input pattern is kept in
    the regex purely so a regression that resurrects it still extracts+fails loudly
    at the POST step rather than silently here)."""
    m = re.search(r'name="csrf" value="([^"]+)"|"csrf":\s*"([^"]+)"', html_or_boot)
    return (m.group(1) or m.group(2)) if m else None


def _do_login(cli, username, password):
    """Authenticate `cli` the way the real app does (2026-08-08, classic cut): GET
    /login for the session csrf, then POST /api/login (JSON) -- the one and only
    sign-in path now. Asserts success so callers never continue anonymous on a
    typo/regression."""
    html = cli.get("/login").get_data(as_text=True)
    csrf = extract_login_csrf(html)
    assert csrf, "login page did not render a csrf token in MG_BOOT"
    d = cli.post("/api/login", json={"username": username, "password": password,
                                     "csrf": csrf}).get_json()
    assert d and d.get("ok"), (
        "test login helper failed to authenticate: {!r}".format(d))
    return cli


def login_existing_client(cli, username=_TEST_USERNAME, password=_TEST_PASSWORD):
    """Authenticate an ALREADY-BUILT test client IN PLACE: create a real account (via
    core.add_or_update_web_user) then log `cli` itself in. Use this when a test needs
    to make some calls anonymously first (e.g. to prove an unauthenticated/LAN request
    is refused) and then continue as a logged-in session against the very same client/
    app instance."""
    core.add_or_update_web_user(username, password)
    return _do_login(cli, username, password)


def login_test_client(app, username=_TEST_USERNAME, password=_TEST_PASSWORD):
    """Given an already-built create_app(tmp_path) app (e.g. one a test file's own
    helper seeded with a catalog), create a real account and return a FRESH,
    now-authenticated test_client() for it."""
    core.add_or_update_web_user(username, password)
    return _do_login(app.test_client(), username, password)


def login_client(tmp_path, username=_TEST_USERNAME, password=_TEST_PASSWORD):
    """The common one-liner: build create_app(tmp_path) AND log into it in one call.
    Returns the authenticated test client, ready to use exactly like
    create_app(tmp_path).test_client() used to be before the local-request bypass
    was removed."""
    from moonglade_gallery import create_app
    return login_test_client(create_app(tmp_path), username=username, password=password)

