"""Shared fixtures for the pixai-gallery-backup test suite."""
import os
import pytest

import pixai_gallery_backup as core


@pytest.fixture(autouse=True)
def _no_pixai_token(monkeypatch):
    """Remove PIXAI_TOKEN so tests that don't need it don't accidentally call live APIs."""
    monkeypatch.delenv("PIXAI_TOKEN", raising=False)


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
    (now reached from generation previews via the free/paid note) builds no network."""
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
