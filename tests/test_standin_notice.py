"""Close and reopen once (3.20, "the move").

A server the root moonglade_gallery.py stand-in started (it sets MOONGLADE_VIA_STANDIN=1) was
started by a launcher that was already running when the install updated into the moonglade/
folder. That old launcher only knows the old path. So the server:
  * asks, once per server start, for Moonglade to be closed and opened again (which starts the
    new launcher), through the /api/jobs poll every open tab already runs -- the client shows
    it as the existing corner toast (gallery/src/notify/serverNotice.js);
  * says `via_standin` in the update status;
  * refuses to update until that has happened (tests/test_updater.py), because the next
    release deletes the stand-in the old launcher would need to restart into it.
A server the new launcher started says none of this.
"""
import os
import subprocess
import sys

import pytest

from moonglade import gallery as g
from moonglade.gallery import CATALOG_FIELDS, create_app, save_catalog
from tests.conftest import REPO_ROOT, login_test_client

TITLE = "Moonglade moved into its new folder."
MSG = "Close it and open it again once to finish."


def _client(tmp_path):
    row = {f: "" for f in CATALOG_FIELDS}
    save_catalog(tmp_path / "catalog.db", [
        row | {"media_id": "1", "filename": "a_1.png", "created_at": "2025-01-01T00:00:00"}])
    return login_test_client(create_app(tmp_path))


@pytest.fixture
def old_launcher(monkeypatch):
    monkeypatch.setenv("MOONGLADE_VIA_STANDIN", "1")


@pytest.fixture
def new_launcher(monkeypatch):
    monkeypatch.setenv("MOONGLADE_VIA_STANDIN", "0")     # restored after, whatever it was
    monkeypatch.delenv("MOONGLADE_VIA_STANDIN")


def test_through_the_stand_in_the_jobs_poll_asks_for_one_close_and_reopen(tmp_path, old_launcher):
    cli = _client(tmp_path)
    first = cli.get("/api/jobs").get_json()["notice"]
    assert first["title"] == TITLE and first["msg"] == MSG
    assert first["key"]
    # every poll of this server start carries the SAME key, which is what lets every open tab
    # show it once and not on every poll
    assert cli.get("/api/jobs").get_json()["notice"] == first


def test_a_server_the_new_launcher_started_says_nothing(tmp_path, new_launcher):
    d = _client(tmp_path).get("/api/jobs").get_json()
    assert "notice" in d and d["notice"] is None


def test_the_update_status_says_whether_an_old_launcher_is_in_charge(tmp_path, monkeypatch):
    monkeypatch.setenv("MOONGLADE_VIA_STANDIN", "1")
    cli = _client(tmp_path)
    assert cli.get("/api/update/status").get_json()["via_standin"] is True
    monkeypatch.delenv("MOONGLADE_VIA_STANDIN")
    assert cli.get("/api/update/status").get_json()["via_standin"] is False


def test_each_server_start_has_a_key_of_its_own():
    """The next start, still through the old launcher, must ask again: two processes, two
    keys."""
    code = ("import os; os.environ['MOONGLADE_VIA_STANDIN'] = '1'; "
            "from moonglade import gallery as g; print(g.server_notice()['key'])")
    keys = [subprocess.run([sys.executable, "-c", code], cwd=str(REPO_ROOT),
                           stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           timeout=120, env=dict(os.environ)).stdout.strip()
            for _ in range(2)]
    assert all(keys) and keys[0] != keys[1], keys
