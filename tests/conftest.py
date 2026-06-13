"""Shared fixtures for the pixai-gallery-backup test suite."""
import os
import pytest


@pytest.fixture(autouse=True)
def _no_pixai_token(monkeypatch):
    """Remove PIXAI_TOKEN so tests that don't need it don't accidentally call live APIs."""
    monkeypatch.delenv("PIXAI_TOKEN", raising=False)


@pytest.fixture()
def mock_session(mocker):
    """Return a MagicMock that quacks like a requests.Session."""
    session = mocker.MagicMock()
    return session
