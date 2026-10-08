"""The settings merge: serve.txt, config.json's app-written keys, branding.json and
branding_slots.json fold into local/settings.json (B1, B5, S17; SPEC_3.20_REBUILD.md).

  * For the library, host and port the merge keeps what the old version actually used: the
    serve.txt flag (the old launcher passed it, and an explicit flag always won), then the
    config.json key, then the default. The losing values go to the log only. C:'s exact
    disagreement -- serve.txt pins `--out pixai_backup --port 5057` while config.json's
    LIBRARY_DIR names another install's library -- must keep C: on its own library.
  * Other serve.txt flags become launch_args: the lasting switches kept, one-shot and unknown
    ones dropped with a log line.
  * serve.txt, branding.json and branding_slots.json are deleted; the moved keys leave
    config.json (through its own atomic writer). READ_ONLY and every hand-edited value stay.
  * A config.json that cannot be read stops the first merge rather than guess the library.

Every install here is the test's own (dev/tests/move_layouts.py rig()).
"""
import json

import pytest

from moonglade import gallery as g
from moonglade import migrate
from moonglade import settings
from moonglade import setup as msetup
from tests.move_layouts import read_config, rig, write, write_config


@pytest.fixture
def r(tmp_path, monkeypatch):
    return rig(tmp_path, monkeypatch)


def _prepare(**kw):
    return msetup.prepare("cli", **kw)


def test_c_s_exact_disagreement_keeps_c_on_its_own_library(r):
    """C:: serve.txt (local\\ and the root copy) pins pixai_backup and port 5057, config.json's
    LIBRARY_DIR names D:'s library. The old launcher passed --out, and an explicit --out always
    won, so C: was serving pixai_backup. The merge must keep that, and only log D:'s path."""
    write_config(r, LIBRARY_DIR=r"D:\Moonglade Athenaeum\pixai_backup", PORT=5000,
                 READ_ONLY=True)
    write(r.app / "serve.txt", "--out pixai_backup --port 5057\n")
    write(r.local / "serve.txt", "--out pixai_backup --port 5057\n")
    (r.app / "pixai_backup").mkdir()
    done = _prepare()
    s = settings.read()
    assert s["library_dir"] == "pixai_backup" and s["port"] == 5057
    assert done.library == r.app / "pixai_backup", "C: opens its own library, never D:'s"
    assert settings.library_path() == r.app / "pixai_backup"
    cfg = read_config(r)
    assert "LIBRARY_DIR" not in cfg and "PORT" not in cfg
    assert cfg["READ_ONLY"] is True, "READ_ONLY stays in config.json (B5)"
    losers = [line for _lvl, line in done.report.lines if "was not used" in line]
    assert any(r"D:\Moonglade Athenaeum\pixai_backup" in line for line in losers)
    assert any("5000" in line for line in losers)
    assert not (r.app / "serve.txt").exists() and not (r.local / "serve.txt").exists()


def test_with_no_flag_the_config_key_is_what_the_old_version_used(r):
    write_config(r, LIBRARY_DIR=str(r.lib), HOST="0.0.0.0", PORT=5858)
    done = _prepare()
    assert settings.library_dir() == str(r.lib) and done.library == r.lib
    assert settings.server()["host"] == "0.0.0.0" and settings.server()["port"] == 5858
    assert not {"LIBRARY_DIR", "HOST", "PORT"} & set(read_config(r))


def test_with_neither_the_default_stays_the_default(r):
    write_config(r)
    write(r.app / "serve.txt", "--https\n")
    done = _prepare()
    assert "library_dir" not in settings.read() and "port" not in settings.read()
    assert done.library == r.app / "pixai_backup"
    assert settings.server()["port"] == 5000


def test_d_s_serve_txt_host_and_port(r):
    """D: (3.17): `--host 0.0.0.0 --port 5757` and no library flag."""
    write_config(r)
    write(r.app / "serve.txt", "--host 0.0.0.0 --port 5757\n")
    _prepare()
    assert settings.server()["host"] == "0.0.0.0" and settings.server()["port"] == 5757
    assert settings.launch_args() == []


def test_the_other_flags_become_launch_args_or_are_dropped(r):
    write_config(r)
    write(r.app / "serve.txt",
          "--https --skip-thumbs -v --rebuild-thumbs --open-browser --mystery 7 --port=5151\n")
    done = _prepare()
    assert settings.read()["launch_args"] == ["--https", "--skip-thumbs", "-v"]
    assert settings.server()["port"] == 5151
    dropped = " ".join(line for _lvl, line in done.report.lines if "dropped" in line)
    assert "--rebuild-thumbs" in dropped and "--open-browser" in dropped
    assert "--mystery 7" in dropped


def test_bonjour_and_the_mirror_switch_move(r):
    write_config(r, BONJOUR_ENABLED=True, BONJOUR_NAME="Den", MIRROR_TO_PIXAI=True)
    _prepare()
    assert settings.server()["bonjour_enabled"] is True
    assert settings.server()["bonjour_name"] == "Den"
    assert settings.mirror_to_pixai() is True
    assert not {"BONJOUR_ENABLED", "BONJOUR_NAME", "MIRROR_TO_PIXAI"} & set(read_config(r))


def test_the_branding_files_fold_into_settings_and_go(r):
    write_config(r)
    write(r.app / "branding.json", {"mark": "mark_2", "anim": "glow", "anim_speed": 1.5,
                                    "glow_color": "#112233"})
    write(r.app / "branding_slots.json", {"banner_main": "a1", "banner_login": ""})
    _prepare()
    b = settings.branding()
    assert b["mark"] == "mark_2"
    assert b["animation"] == {"anim": "glow", "anim_speed": 1.5, "glow_color": "#112233"}
    assert b["slots"] == {"banner_main": "a1"}
    assert not (r.app / "branding.json").exists()
    assert not (r.app / "branding_slots.json").exists()
    assert g._recorded_slot_active(r.lib) == {"banner_main": "a1"}


def test_every_hand_edited_value_stays_in_config_json(r):
    hand = {"READ_ONLY": True, "USER_ID": "u1", "PERSISTED_QUERY_HASH": "h1",
            "TASK_DETAIL_HASH": "h2", "AUTH_EPOCH_SEQ": 7}
    before = write_config(r, LIBRARY_DIR=str(r.lib), **hand)
    _prepare()
    after = read_config(r)
    for k in ("PIXAI_API_KEY", "AUTH_SECRET_KEY", "AUTH_USERS") + tuple(hand):
        assert after[k] == before[k], k


def test_an_unreadable_config_stops_the_first_merge_and_touches_nothing(r):
    r.cfg.write_text("{ not json", encoding="utf-8")
    write(r.app / "serve.txt", "--port 5057\n")
    with pytest.raises(migrate.MoveStopped) as e:
        _prepare()
    assert "config.json" in str(e.value)
    assert (r.app / "serve.txt").is_file(), "nothing is deleted on a guess"
    assert r.cfg.read_text(encoding="utf-8") == "{ not json"
    assert not (r.local / "settings.json").exists()


def test_a_key_written_by_hand_after_the_move_is_brought_across_too(r):
    """The merge is a standing sweep: following an old help page later still works."""
    write_config(r)
    _prepare()
    cfg = read_config(r)
    cfg["PORT"] = 6060
    r.cfg.write_text(json.dumps(cfg), encoding="utf-8")
    write(r.app / "serve.txt", "--https\n")
    _prepare()
    assert settings.server()["port"] == 6060 and settings.launch_args() == ["--https"]
    assert "PORT" not in read_config(r) and not (r.app / "serve.txt").exists()


def test_a_second_start_finds_nothing_to_merge(r):
    write_config(r, PORT=5151)
    _prepare()
    stamp = (r.local / "settings.json").stat().st_mtime_ns
    done = _prepare()
    assert done.report.worked["install"] is False
    assert (r.local / "settings.json").stat().st_mtime_ns == stamp


def test_the_merge_writes_settings_before_it_deletes_anything(r, monkeypatch):
    """If settings.json cannot be written, the old files and keys are all still there."""
    write_config(r, PORT=5151)
    write(r.app / "serve.txt", "--port 5057\n")

    def refuse(fn):
        raise OSError("disk full")
    monkeypatch.setattr(settings, "update", refuse)
    with pytest.raises((migrate.MoveStopped, OSError)):
        _prepare()
    assert (r.app / "serve.txt").is_file() and read_config(r)["PORT"] == 5151
