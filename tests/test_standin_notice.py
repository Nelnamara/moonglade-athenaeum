"""Stop and start once (3.20, "the move").

A server the root moonglade_gallery.py stand-in started (it sets MOONGLADE_VIA_STANDIN=1) was
started by a launcher that was already running when the install updated into the moonglade/
folder. That old launcher only knows the old path. So the server:
  * asks, once per server start, for Moonglade to be stopped once and started again (which
    starts the new launcher), through the /api/jobs poll every open tab already runs -- the
    client shows it as the existing corner toast (gallery/src/notify/serverNotice.js);
  * says `via_standin` in the update status;
  * refuses to update until that has happened (tests/test_updater.py), so an install that
    passes through 3.20 is on the new launcher before it takes another release. (The
    stand-in itself stays for good: an install can skip 3.20 and never meet this gate.)
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
MSG = ("Stop it once (Control Panel → Server → ■ Stop, and confirm), then start it "
       "again from its shortcut.")


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


def test_through_the_stand_in_the_jobs_poll_asks_for_one_stop_and_start(tmp_path, old_launcher):
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


def test_the_notice_names_the_stop_control_the_control_panel_really_has():
    """Closing the browser leaves the server running, the shortcut then finds the port taken
    and only opens a tab, and Restart goes back through the old launcher -- so the notice
    names the one control that ends the old launcher: the Control Panel's Server section's
    ■ Stop (it asks once more, "Confirm — Stop?", before it fires)."""
    desktop = (REPO_ROOT / "gallery/src/components/ControlPanelOverlay.jsx").read_text(
        encoding="utf-8")
    server = desktop[desktop.index('<div className="mgcp-sidekick">Server</div>'):]
    server = server[:server.index("mgcp-tilenote")]          # the Server row's own buttons
    assert '"■ Stop"' in server and 'clickPower("stop")' in server
    phone = (REPO_ROOT / "gallery/src/components/ControlMobile.jsx").read_text(encoding="utf-8")
    assert '"■ Stop"' in phone and 'clickPower("stop")' in phone
    hook = (REPO_ROOT / "gallery/src/hooks/useControlPanel.js").read_text(encoding="utf-8")
    assert 'apiPost("/api/server/stop"' in hook
    assert "Control Panel → Server → ■ Stop" in g.STANDIN_NOTICE_MSG
    assert "shortcut" in g.STANDIN_NOTICE_MSG


def test_stopping_from_the_control_panel_ends_the_old_launcher_too(tmp_path, old_launcher,
                                                                    monkeypatch):
    """■ Stop asks /api/server/stop, which ends the server with exit code 0. The stand-in
    hands that code straight back (tests/test_root_standins.py), and every launcher -- the
    old one too, 3.17 to 3.19 -- relaunches only on 42 (tests/test_launcher_runs_the_package.py
    holds the loop): anything else ends it. So the old launcher stops with the server, and
    the shortcut then starts the new one."""
    codes = []
    monkeypatch.setattr(g, "_supervised", lambda: True)
    monkeypatch.setattr(g, "_schedule_server_exit", lambda c: codes.append(c))
    cli = _client(tmp_path)
    assert cli.post("/api/server/stop").get_json() == {"ok": True, "action": "stop"}
    assert codes == [0] and 42 not in codes


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
