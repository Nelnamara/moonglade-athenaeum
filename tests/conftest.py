"""Shared fixtures for the pixai-gallery-backup test suite."""
import os
import re

import pytest

import pixai_gallery_backup as core


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
    pixai_gallery.create_app() -- called by ~every test in this suite -- now
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
def _no_live_watch(monkeypatch):
    """create_app() is called by ~every test in this suite. Without this, its
    live-mirror watcher thread would call _make_session(None), which re-reads THIS
    machine's real config.json (whatever real credentials happen to be there) and open
    a genuine WebSocket to wss://gw.pixai.art -- during every single test run. Skip its
    auto-start entirely in tests; see MOONGLADE_DISABLE_WATCH in pixai_gallery.py."""
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
# pixai_gallery.py's _is_authorized_request() (owner directive 2026-07-19: "I would
# expect to require login via any path with this new setup whether localhost
# hostname or IP") has NO localhost bypass anymore -- true only for a request
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


def _do_login(cli, username, password):
    """Perform the real GET (csrf) + POST /login flow against `cli` and return it,
    now authenticated. Asserts the login actually redirected (succeeded) rather
    than silently leaving callers with a still-anonymous client on a typo/regression."""
    html = cli.get("/login").get_data(as_text=True)
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "login page did not render a csrf hidden field"
    r = cli.post("/login", data={"username": username, "password": password,
                                 "csrf": m.group(1)})
    assert r.status_code in (301, 302, 303, 307, 308), (
        "test login helper failed to authenticate: {}".format(
            r.get_data(as_text=True)[:300]))
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
    from pixai_gallery import create_app
    return login_test_client(create_app(tmp_path), username=username, password=password)

