"""local/settings.json: everything the app writes, in one store (moonglade.settings).

  * written whole and atomically, under one lock every process honours, and read once per
    change of the file (a reader costs one stat until the file changes);
  * a file that will not parse, or cannot be read, reads as {} for a page -- but is never
    written over: a change is refused (SettingsUnreadable), and every start stops with a
    sentence (moonglade.setup); a moment's failure to read is never cached (S4);
  * read with or without a byte order mark (Notepad and PowerShell write one);
  * one key each for the library, host and port (S17), with the resolvers the server, the
    command line and the MCP server share (S8);
  * the Control Panel's writers (library field, Bonjour chip, Mirror switch, branding picks)
    write here and never rewrite config.json.

conftest pins local_dir() (so settings.json) and config_path() to each test's own folder.
"""
import json
import os
import threading

import pytest

from moonglade import backup as core
from moonglade import gallery as g
from moonglade import paths
from moonglade import settings
from tests.conftest import login_client


def test_a_missing_file_reads_as_nothing_stored(tmp_path):
    assert not paths.settings_path().exists()
    assert settings.read() == {}
    assert settings.library_dir() == ""
    assert settings.server() == {"host": "127.0.0.1", "port": 5000, "bonjour_enabled": False,
                                 "bonjour_name": "Moonglade"}
    assert settings.launch_args() == [] and settings.mirror_to_pixai() is False


def test_a_change_is_written_whole_and_read_back(tmp_path):
    settings.set_values(port=5101, host="0.0.0.0")
    on_disk = json.loads(paths.settings_path().read_text(encoding="utf-8"))
    assert on_disk == {"port": 5101, "host": "0.0.0.0"}
    assert settings.server()["port"] == 5101 and settings.server()["host"] == "0.0.0.0"
    settings.set_values(host=None)                       # None removes a key
    assert "host" not in settings.read()
    assert not list(paths.settings_path().parent.glob("settings.json.tmp*"))
    assert not paths.settings_path().with_name("settings.json.lock").exists()


def test_a_reader_parses_once_per_change(tmp_path, monkeypatch):
    settings.set_values(mirror_to_pixai=True)
    calls = []
    real = settings._parse
    monkeypatch.setattr(settings, "_parse", lambda p: calls.append(p) or real(p))
    settings._cache.update(key=None, doc=None)
    for _ in range(5):
        assert settings.mirror_to_pixai() is True
    assert len(calls) == 1
    settings.set_values(mirror_to_pixai=False)          # the writer refreshes the cache
    assert settings.mirror_to_pixai() is False


def test_a_change_by_another_process_is_seen(tmp_path):
    settings.set_values(port=5101)
    assert settings.server()["port"] == 5101
    doc = json.loads(paths.settings_path().read_text(encoding="utf-8"))
    doc["port"] = 5202
    paths.settings_path().write_text(json.dumps(doc) + "\n\n", encoding="utf-8")
    assert settings.server()["port"] == 5202


def test_a_corrupt_file_reads_as_nothing_and_is_never_written_over(tmp_path):
    """S4: a write over a damaged file would throw away the library pin, the port and every
    pick; the change is refused and the file kept as it is."""
    paths.settings_path().parent.mkdir(parents=True, exist_ok=True)
    paths.settings_path().write_text('{"library_dir": "D:\\lib", ', encoding="utf-8")
    assert settings.read() == {}
    assert settings.state() == ("corrupt", "it isn't valid JSON")
    with pytest.raises(settings.SettingsUnreadable):
        settings.set_values(port=5101)
    assert paths.settings_path().read_text(encoding="utf-8") == '{"library_dir": "D:\\lib", '
    assert not list(paths.settings_path().parent.glob("settings.json.corrupt-*"))


def test_a_file_that_cannot_be_read_is_not_cached_or_written_over(tmp_path, monkeypatch):
    """S4: another program holding the file for a moment must not make the whole process read
    the default library until the file changes."""
    settings.set_values(library_dir="D:\\lib", port=5101)
    settings._cache.update(key=None, doc=None)
    real = settings._parse
    held = {"on": True}

    def parse(p):
        if held["on"]:
            return {}, "unreadable", "another program has it open"
        return real(p)
    monkeypatch.setattr(settings, "_parse", parse)
    assert settings.read() == {}
    with pytest.raises(settings.SettingsUnreadable):
        settings.set_values(port=6000)
    held["on"] = False
    assert settings.library_dir() == "D:\\lib" and settings.server()["port"] == 5101


def test_a_byte_order_mark_is_read(tmp_path):
    paths.settings_path().parent.mkdir(parents=True, exist_ok=True)
    paths.settings_path().write_bytes(b"\xef\xbb\xbf" + b'{"port": 5151}')
    assert settings.server()["port"] == 5151
    assert settings.state() == ("ok", "")
    settings.set_values(host="0.0.0.0")
    assert settings.read() == {"port": 5151, "host": "0.0.0.0"}


def test_two_writers_never_lose_each_others_change(tmp_path):
    """update() re-reads under the lock, so concurrent writers of different keys both land."""
    errors = []

    def writer(k):
        try:
            for i in range(10):
                settings.update(lambda d, k=k, i=i: d.__setitem__(k, i))
        except Exception as e:                    # noqa: BLE001
            errors.append(e)
    threads = [threading.Thread(target=writer, args=("k%d" % n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert settings.read() == {"k0": 9, "k1": 9, "k2": 9, "k3": 9}


def test_a_lock_held_by_another_process_refuses_the_write(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LOCK_WAIT_S", 0.2)
    paths.settings_path().parent.mkdir(parents=True, exist_ok=True)
    lock = paths.settings_path().with_name("settings.json.lock")
    lock.write_text("", encoding="utf-8")
    with pytest.raises(settings.SettingsBusy):
        settings.set_values(port=5101)
    assert not paths.settings_path().exists()
    os.utime(lock, (0, 0))                      # a dead writer's lock goes stale
    settings.set_values(port=5101)
    assert settings.server()["port"] == 5101


# ---- one key each, one resolver --------------------------------------------------------------

def test_the_library_resolver(tmp_path):
    """Explicit (this run's --out / MOONGLADE_OUT) wins as typed; then the stored one; then the
    default. A relative stored or default library is anchored to the app folder."""
    anchor = paths.library_anchor()
    assert settings.library_path() == anchor / "pixai_backup"
    assert str(settings.library_path("rel/lib")) == os.path.join("rel", "lib")
    settings.set_values(library_dir=str(tmp_path / "abs"))
    assert settings.library_path() == tmp_path / "abs"
    settings.set_values(library_dir="relative_library")
    assert settings.library_path() == anchor / "relative_library"
    assert settings.library_path(str(tmp_path / "x")) == tmp_path / "x"


def test_the_server_settings(tmp_path):
    settings.set_values(host="0.0.0.0", port=5757, bonjour={"enabled": True, "name": "Den"})
    assert settings.server() == {"host": "0.0.0.0", "port": 5757, "bonjour_enabled": True,
                                 "bonjour_name": "Den"}
    assert settings.server("127.0.0.1", 6000)["host"] == "127.0.0.1"   # explicit wins
    assert settings.server("127.0.0.1", 6000)["port"] == 6000
    settings.set_values(host="not-an-ip", port="junk")
    assert settings.server()["host"] == "127.0.0.1" and settings.server()["port"] == 5000
    settings.set_values(port=99999)
    assert settings.server()["port"] == 5000
    assert g.resolve_server_settings()["port"] == 5000              # the server asks the same


def test_launch_args_hold_only_lasting_switches(tmp_path):
    settings.set_values(launch_args=["--https", "--rebuild-thumbs", "--out", "x", "-v"])
    assert settings.launch_args() == ["--https", "-v"]


# ---- the Control Panel's writers write here, never config.json ------------------------------

@pytest.fixture
def cli(tmp_path):
    from moonglade.gallery import CATALOG_FIELDS, save_catalog
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {
        "media_id": "1", "filename": "a.png", "created_at": "2025-01-01T00:00:00"}])
    c = login_client(tmp_path)
    c.config_before = (tmp_path / "config.json").read_bytes()
    return c


def _config_untouched(tmp_path, cli):
    assert (tmp_path / "config.json").read_bytes() == cli.config_before


def test_the_bonjour_chip_writes_settings(tmp_path, cli):
    d = cli.post("/api/bonjour/settings", json={"enabled": True, "name": "Den",
                                               "host": "0.0.0.0", "port": 5757}).get_json()
    assert not d.get("error"), d
    assert settings.read()["bonjour"] == {"enabled": True, "name": "Den"}
    assert settings.server()["host"] == "0.0.0.0" and settings.server()["port"] == 5757
    st = cli.get("/api/bonjour/status").get_json()
    assert st["enabled"] is True and st["name"] == "Den"
    _config_untouched(tmp_path, cli)


def test_the_mirror_switch_writes_settings(tmp_path, cli, monkeypatch):
    monkeypatch.setattr(core, "_jwt_usable", lambda jwt: True)
    assert cli.post("/api/mirror/enable", json={"enabled": True}).get_json() == {"enabled": True}
    assert core.mirror_enabled() is True
    assert cli.post("/api/mirror/enable", json={"enabled": False}).get_json() == \
        {"enabled": False}
    assert core.mirror_enabled() is False
    _config_untouched(tmp_path, cli)


def test_the_branding_picks_write_settings_and_leave_each_other_alone(tmp_path):
    g.save_slot_active(tmp_path, {"banner_main": "a1"})
    g.save_branding(tmp_path, dict(g._BRAND_DEFAULTS, anim="glow", anim_speed=9))
    b = settings.branding()
    assert b["slots"] == {"banner_main": "a1"}, "the mark's writer kept the slot pick"
    assert b["animation"]["anim"] == "glow"
    assert b["animation"]["anim_speed"] == 3.0, "clamped on the way in"
    g.save_slot_active(tmp_path, {"banner_main": "a2"})
    assert settings.branding()["animation"]["anim"] == "glow", "the slot's writer kept the mark"


def test_config_json_keeps_only_hand_edited_values():
    """The keys the app used to write into config.json are gone from every writer."""
    import inspect
    src = inspect.getsource(g) + inspect.getsource(core)
    for key in ('"LIBRARY_DIR"', '"BONJOUR_ENABLED"', '"BONJOUR_NAME"', '"MIRROR_TO_PIXAI"'):
        assert key not in src, key
