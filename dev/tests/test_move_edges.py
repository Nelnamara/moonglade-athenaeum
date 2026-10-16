"""The edge cases GitHub issue #79 collected from the 3.20 release gate (the move, moonglade.migrate;
the start, moonglade.setup and the launcher). Each test here fails without its fix.

Next to data loss, first:
  * a dead plain-name login file whose time was reset by a copy tool never beats the live one;
  * the art pack at the old place is compared before it goes, and set aside when it differs;
  * two runs.db copies at the first move are merged run by run, not one parked and deleted;
  * a library banner is kept (never parked, then deleted) when the install already wears one,
    and a banner brought across but cut short before it was recorded is recorded by the next start;
  * a new home that is empty (or saved with a byte order mark) is not a stop on every start;
  * a mark an older install set later than the new home's wins the clash;
  * a merge made while another program writes the new home is made again, not written over it;
  * a file named like a temp goes into the safety copy before it is removed;
  * an older launcher's still-held log is added to once, not re-merged whole at every start;
then the slow first move on a large Loom folder (journalled in groups), and the setup, wording and
platform edges: a UNC library's SQLite files, a local\\settings.json of another program, the
install's own local\\ as a library, the account commands of the command line, the words of the
--out refusal, a record with a time a zip cannot hold, config.json saved as UTF-16 or with a
byte order mark, the lock's release, a lock this very process holds, the launcher's reason and
its --https probe.
"""
import json
import os
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

from moonglade import backup as core
from moonglade import migrate
from moonglade import paths
from moonglade import settings
from moonglade import setup as msetup
from tests.move_layouts import KEY_NEL, make_db, rig, start, write, write_config


@pytest.fixture
def r(tmp_path, monkeypatch):
    return rig(tmp_path, monkeypatch)


def _moved(r):
    """A library whose move has finished: what the first 3.20 start leaves."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": "before-the-move"}\n')
    start(r)
    assert json.loads((r.lib / "_moonglade" / ".journal.json").read_text())["finished"]


def _older_install_writes(path, data):
    """An older install writes `path` after the move (its time is later than the journal's)."""
    write(path, data)
    later = Path(path).stat().st_mtime + 120
    os.utime(path, (later, later))
    return Path(path)


def _bring_in(r):
    """The start after the older install wrote stops once (close it); the next brings it in."""
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    assert "An older Moonglade is still using the library" in str(e.value)
    return start(r)


def _said(done):
    return " ".join(line for _lvl, line in done.report.all_lines())


def _snapshot_names(root):
    zips = sorted((Path(root) / ".snapshot").glob("*.zip"))
    names = []
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            names += zf.namelist()
    return names


def _parked(root):
    folder = Path(root) / ".snapshot" / "parked"
    return sorted(p.name for p in folder.rglob("*") if p.is_file()) if folder.exists() else []


# ---- the first move --------------------------------------------------------------------------

def test_a_line_with_a_unicode_line_separator_stays_one_line_in_a_merge(r):
    """raw_tasks.jsonl lines are written with ensure_ascii=False, so a prompt can hold U+2028;
    str.splitlines() cut such a line in two invalid halves when two copies were merged."""
    write_config(r)
    odd = json.dumps({"prompt": "line one line two\u0085end"}, ensure_ascii=False)
    write(r.lib / "raw_tasks.jsonl", odd + "\n" + '{"t": 2}\n')
    write(r.lib / "jobs.jsonl", '{"id": "j1"}\n')
    # the new home already holds a file of its own (a start's writes before the move finished)
    new = r.lib / "_moonglade" / "records" / "raw_tasks.jsonl"
    write(new, '{"t": 1}\n')
    start(r)
    lines = new.read_bytes().decode("utf-8").split("\n")
    assert odd in lines, "the record with U+2028 inside it is still one line"
    assert '{"t": 1}' in lines and '{"t": 2}' in lines
    for ln in lines:
        if ln:
            json.loads(ln)                      # every line is still a whole record


def test_a_dead_plain_name_file_with_a_newer_time_never_beats_the_live_one(r):
    """A file named by a login's plain name was written before the hashed keys and nothing since
    has read it. A copy tool that reset its time to now must not make it win the home: the live
    hashed file is kept, and the plain-name one is set aside."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": "j1"}\n')
    live = write(r.lib / "account_prefs" / (KEY_NEL + ".json"), {"theme": "live"})
    dead = write(r.lib / "account_prefs" / "Nel.json", {"theme": "dead"})
    os.utime(live, (1_700_000_000, 1_700_000_000))
    os.utime(dead, (1_750_000_000, 1_750_000_000))          # newer: a copy tool's doing
    start(r)
    home = r.lib / "_moonglade" / "accounts" / KEY_NEL / "prefs.json"
    assert json.loads(home.read_text()) == {"theme": "live"}
    assert _parked(r.lib / "_moonglade") == ["Nel.json"]
    parked = next((r.lib / "_moonglade" / ".snapshot" / "parked").rglob("Nel.json"))
    assert json.loads(parked.read_text()) == {"theme": "dead"}, "kept for the safety copy's life"


def test_an_art_pack_at_the_old_place_that_differs_is_set_aside_not_deleted(r):
    """Step 2 removed the root pack whenever local\\ held one, without comparing the two: a
    candidate pack put there by hand went with no trace. Different bytes are parked."""
    write_config(r)
    write(r.local / paths.PACK_NAME, b"PACK-IN-USE" * 50)
    write(r.local / (paths.PACK_NAME + ".version"), {"version": "7"})
    write(r.app / paths.PACK_NAME, b"A-CANDIDATE" * 50)
    write(r.app / (paths.PACK_NAME + ".version"), {"version": "x"})
    done = start(r)
    assert (r.local / paths.PACK_NAME).read_bytes() == b"PACK-IN-USE" * 50
    assert not (r.app / paths.PACK_NAME).exists() and not (r.app / (paths.PACK_NAME + ".version")).exists()
    parked = list((r.local / ".snapshot" / "parked").rglob(paths.PACK_NAME))
    assert len(parked) == 1 and parked[0].read_bytes() == b"A-CANDIDATE" * 50
    assert "differs" in _said(done)


def test_an_art_pack_at_the_old_place_with_the_same_bytes_is_only_removed(r):
    write_config(r)
    write(r.local / paths.PACK_NAME, b"THE-PACK" * 50)
    write(r.app / paths.PACK_NAME, b"THE-PACK" * 50)
    start(r)
    assert not (r.app / paths.PACK_NAME).exists()
    assert (r.local / paths.PACK_NAME).read_bytes() == b"THE-PACK" * 50
    assert _parked(r.local) == [], "the same bytes are one: nothing to keep"


def _runs_db(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        con.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, label TEXT)")
        con.executemany("INSERT INTO runs (id, label) VALUES (?, ?)", rows)
        con.commit()
    finally:
        con.close()


def _labels(path):
    con = sqlite3.connect(str(path))
    try:
        return [x[0] for x in con.execute("SELECT label FROM runs ORDER BY id")]
    finally:
        con.close()


def test_two_runs_dbs_at_the_first_move_are_merged_not_one_parked_and_deleted(r):
    """C:'s copy-first layout (and a library that appears late) can hold a runs.db at both
    places. The older was parked and deleted after five clean starts, with every run only it
    held (and their spend reservations)."""
    write_config(r)
    _runs_db(r.lib / "_moonglade" / "runs.db", [(1, "live-1"), (2, "live-2")])
    _runs_db(r.lib / "runs.db", [(1, "old-1"), (7, "only-the-old-one-has-this")])
    start(r)
    home = r.lib / "_moonglade" / "records" / "runs.db"
    assert _labels(home) == ["live-1", "live-2", "only-the-old-one-has-this"]
    assert not (r.lib / "runs.db").exists()
    assert _parked(r.lib / "_moonglade") == [], "nothing was set aside: the rows were folded in"


def test_a_banner_the_install_cannot_wear_is_kept_not_parked_and_lost(r):
    """A second library moved by the same install: the slot already wears a banner, and the
    library's only-copy render was parked beside the safety copy, deleted after five starts."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": "j1"}\n')
    settings.update_branding(lambda b: b.__setitem__("worn_banner", {"banner_main": {"kind": "migrated"}}))
    write(r.local / "banners" / "banner.png", b"THE-INSTALLS-OWN")
    write(r.lib / "gallery" / "cache" / "_banners" / "banner.png", b"THIS-LIBRARYS-OWN")
    done = start(r)
    assert (r.local / "banners" / "banner.png").read_bytes() == b"THE-INSTALLS-OWN"
    kept = r.local / "banners" / "banner-from-library.png"
    assert kept.read_bytes() == b"THIS-LIBRARYS-OWN"
    assert _parked(r.lib / "_moonglade") == []
    assert settings.branding()["worn_banner"] == {"banner_main": {"kind": "migrated"}}
    assert "kept, not worn" in _said(done)


def test_a_banner_brought_across_but_not_yet_recorded_is_recorded_by_the_next_start(r, monkeypatch):
    """The render moved into local\\banners\\ and the start was cut short before worn_banner
    was saved: the next start found no render in the library's cache and never recorded it, so
    the install did not wear the banner it had."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": "j1"}\n')
    write(r.lib / "gallery" / "cache" / "_banners" / "banner.png", b"MY-BANNER")
    real = migrate._wear

    def cut_short(slot, value):
        raise OSError("settings.json is busy")
    monkeypatch.setattr(migrate, "_wear", cut_short)
    with pytest.raises(msetup.MoveStopped):
        start(r)
    assert (r.local / "banners" / "banner.png").read_bytes() == b"MY-BANNER"
    assert "worn_banner" not in settings.branding()
    monkeypatch.setattr(migrate, "_wear", real)
    start(r)
    assert settings.branding()["worn_banner"] == {"banner_main": {"kind": "migrated"}}
    assert (r.local / "banners" / "banner.png").read_bytes() == b"MY-BANNER"


def test_a_banner_the_person_stopped_wearing_is_not_put_back_by_a_later_start(r):
    """The repair of a cut-short banner move is for that move only: after it finished, a slot
    that wears nothing is the person's choice (picking a banner clears the wear and leaves the
    kept render in local/banners), not a record to restore."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": "j1"}\n')
    write(r.lib / "gallery" / "cache" / "_banners" / "banner.png", b"MY-BANNER")
    start(r)
    assert settings.branding()["worn_banner"] == {"banner_main": {"kind": "migrated"}}
    settings.update_branding(lambda b: b.pop("worn_banner", None))
    _older_install_writes(r.lib / "jobs.jsonl", '{"id": "from-the-older-install"}\n')
    _bring_in(r)
    assert "worn_banner" not in settings.branding()


def test_an_older_launcher_s_held_log_is_added_to_once_not_merged_whole_each_start(r, monkeypatch):
    """An older launcher still running holds its serve.log open: Windows refuses to delete it
    after the copy, so every later start met two copies. The merge wrote the copied lines a
    second time, every start."""
    write_config(r)
    old = write(r.app / "serve.log", "L1\nL2\n")
    real_remove = migrate._remove

    def held(p):
        if Path(p) == old:
            raise migrate._Failed("couldn't remove %s (another program has it open)" % p)
        return real_remove(p)

    def no_rename(src, dest):
        raise PermissionError(13, "the file is in use")      # Windows: held without sharing delete
    monkeypatch.setattr(migrate, "_remove", held)
    monkeypatch.setattr(migrate, "_rename_into", no_rename)
    start(r)
    new = r.local / "logs" / "serve.log"
    assert new.read_text() == "L1\nL2\n" and old.exists()
    with open(new, "a") as f:
        f.write("N1\n")                          # this launcher's own line
    with open(old, "a") as f:
        f.write("L3\n")                          # the older launcher's, still running
    start(r)
    lines = new.read_text().splitlines()
    assert sorted(lines) == ["L1", "L2", "L3", "N1"], lines
    with open(old, "a") as f:
        f.write("L4\n")
    start(r)
    lines = new.read_text().splitlines()
    assert sorted(lines) == ["L1", "L2", "L3", "L4", "N1"], lines


# ---- later starts: bringing in an older install's writes ---------------------------------------

def test_an_empty_new_home_is_not_a_stop_on_every_start(r):
    """A snippets.json written non-atomically and cut short is 0 bytes: the app reads it as
    empty. The move stopped on it at every start until it was restored or deleted by hand."""
    _moved(r)
    acc = r.lib / "_moonglade" / "accounts" / KEY_NEL
    write(acc / "snippets.json", b"")
    _older_install_writes(r.lib / "prompt_snippets" / (KEY_NEL + ".json"), ["golden hour"])
    start_2 = _bring_in(r)
    assert json.loads((acc / "snippets.json").read_text()) == ["golden hour"]
    assert not (r.lib / "prompt_snippets").exists()
    assert start_2 is not None


def test_a_new_home_saved_with_a_byte_order_mark_is_merged_not_called_broken(r):
    _moved(r)
    acc = r.lib / "_moonglade" / "accounts" / KEY_NEL
    write(acc / "prefs.json", b"\xef\xbb\xbf" + json.dumps({"theme": "dusk"}).encode())
    _older_install_writes(r.lib / "account_prefs" / (KEY_NEL + ".json"), {"grid": "large"})
    _bring_in(r)
    assert json.loads((acc / "prefs.json").read_text()) == {"theme": "dusk", "grid": "large"}


def test_a_new_home_that_is_really_damaged_still_stops_and_says_how_out(r):
    _moved(r)
    acc = r.lib / "_moonglade" / "accounts" / KEY_NEL
    write(acc / "prefs.json", '{"theme": "du')
    _older_install_writes(r.lib / "account_prefs" / (KEY_NEL + ".json"), {"grid": "large"})
    with pytest.raises(msetup.MoveStopped):
        start(r)                                     # the older install's write: closed first
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    words = str(e.value)
    assert "won't read" in words and "delete that damaged file" in words
    assert "safety copy" in words, "it names the zip that holds the older file"
    (acc / "prefs.json").unlink()                    # the way out the sentence gives
    start(r)
    assert json.loads((acc / "prefs.json").read_text()) == {"grid": "large"}


def test_a_line_file_with_torn_bytes_is_still_merged(r):
    """raw_tasks.jsonl cut mid-character is still lines: it is never a broken home."""
    _moved(r)
    new = r.lib / "_moonglade" / "records" / "raw_tasks.jsonl"
    write(new, b'{"t": 1}\n{"p": "caf\xc3')
    _older_install_writes(r.lib / "raw_tasks.jsonl", '{"t": 2}\n')
    _bring_in(r)
    data = new.read_bytes()
    assert b'{"t": 1}\n' in data and b'{"t": 2}\n' in data and data.count(b'caf\xc3') == 1


def test_the_older_install_s_skin_fills_a_new_home_that_never_chose_one(r):
    _moved(r)
    rec = r.lib / "_moonglade" / "records"
    write(rec / "achievements.json", {"seen": ["a1"], "earned_at": {"a1": "2026-09-01"}})
    _older_install_writes(r.lib / "achievements.json", {"seen": ["a2"], "skin": "dusk",
                                                         "earned_at": {}})
    _bring_in(r)
    doc = json.loads((rec / "achievements.json").read_text())
    assert doc["skin"] == "dusk" and sorted(doc["seen"]) == ["a1", "a2"]


def test_the_new_home_s_skin_stays_over_the_older_install_s(r):
    _moved(r)
    rec = r.lib / "_moonglade" / "records"
    write(rec / "achievements.json", {"seen": [], "skin": "moonglade", "earned_at": {}})
    _older_install_writes(r.lib / "achievements.json", {"seen": [], "skin": "dusk",
                                                         "earned_at": {}})
    _bring_in(r)
    assert json.loads((rec / "achievements.json").read_text())["skin"] == "moonglade"


def test_a_merge_is_made_again_when_the_new_home_changes_under_it(r, monkeypatch):
    """A second PC's server on a shared library writes the new home while the older install's
    lines are being folded in: its line was lost to the swap (the merge was read before it)."""
    _moved(r)
    new = r.lib / "_moonglade" / "records" / "jobs.jsonl"
    _older_install_writes(r.lib / "jobs.jsonl", '{"id": "from-the-older-install"}\n')
    real = migrate._settled_bytes
    calls = []

    def racing(src, dest, how):
        out = real(src, dest, how)
        if not calls:                                # the other PC writes right after the read
            with open(dest, "ab") as f:
                f.write(b'{"id": "from-the-other-pc"}\n')
        calls.append(1)
        return out
    monkeypatch.setattr(migrate, "_settled_bytes", racing)
    _bring_in(r)
    lines = new.read_text().splitlines()
    assert '{"id": "from-the-other-pc"}' in lines, "what the other server wrote meanwhile survives"
    assert '{"id": "from-the-older-install"}' in lines
    assert len(calls) == 2, "the merge was read again after the new home changed"


def test_a_merge_gives_up_loudly_when_the_new_home_never_holds_still(r, monkeypatch):
    _moved(r)
    _older_install_writes(r.lib / "jobs.jsonl", '{"id": "x"}\n')
    real = migrate._settled_bytes
    n = []

    def always_racing(src, dest, how):
        out = real(src, dest, how)
        with open(dest, "ab") as f:
            f.write(b'{"id": "other-%d"}\n' % len(n))
        n.append(1)
        return out
    monkeypatch.setattr(migrate, "_settled_bytes", always_racing)
    with pytest.raises(msetup.MoveStopped):
        start(r)                                     # the older install's write: closed first
    with pytest.raises(msetup.MoveStopped) as e:
        start(r)
    assert "keeps changing" in str(e.value)
    assert len(n) == migrate.MERGE_TRIES


# ---- a file named like a temp -------------------------------------------------------------------

def test_a_file_named_like_a_temp_goes_into_the_safety_copy_before_it_is_removed(r):
    """The old loom\\ folder's .part/.tmp/.lock files were removed without being snapshotted: a
    person's own file with such a name was gone for good. Small ones are in the zip now."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": "j1"}\n')
    write(r.lib / "loom" / "kv" / KEY_NEL / "storyboard%3Av2%3Aproj%3Ab1.json", {"b": 1})
    mine = write(r.lib / "loom" / "kv" / KEY_NEL / "my notes.tmp", "do not lose me")
    write(r.lib / "loom" / "exports" / "render.mp4.part", b"half a render")
    start(r)
    assert not mine.exists()
    names = _snapshot_names(r.lib / "_moonglade")
    assert "loom/kv/%s/my notes.tmp" % KEY_NEL in names
    assert "loom/exports/render.mp4.part" in names
    z = next((r.lib / "_moonglade" / ".snapshot").glob("*.zip"))
    with zipfile.ZipFile(z) as zf:
        assert zf.read("loom/kv/%s/my notes.tmp" % KEY_NEL) == b"do not lose me"


# ---- a large Loom folder ----------------------------------------------------------------------

def _frames(r, n):
    for i in range(n):
        write(r.lib / "loom" / "_frames" / ("f%04d.png" % i), b"FRAME-%d" % i)


def test_a_large_loom_folder_is_journalled_in_groups_not_twice_per_file(r, monkeypatch):
    """The journal is written whole with a flush: a save per file made the first move O(n^2) in
    file count (3000 frames took 57 s on an SSD)."""
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": "j1"}\n')
    _frames(r, 300)
    saves = []
    real = migrate.Journal.save

    def counted(self):
        saves.append(1)
        return real(self)
    monkeypatch.setattr(migrate.Journal, "save", counted)
    start(r)
    new = r.lib / "_moonglade" / "loom" / "_frames"
    assert sorted(p.name for p in new.iterdir()) == ["f%04d.png" % i for i in range(300)]
    assert (new / "f0123.png").read_bytes() == b"FRAME-123"
    assert not (r.lib / "loom").exists()
    assert len(saves) < 60, "%d journal writes for 300 files" % len(saves)
    journal = json.loads((r.lib / "_moonglade" / ".journal.json").read_text())
    entry = journal["items"]["_moonglade/loom/_frames/f0007.png"]
    assert entry["state"] == "made" and entry["how"] == "renamed" and entry["src"] == "loom/_frames/f0007.png"


def test_a_group_cut_short_is_finished_by_the_next_start_and_nothing_is_lost(r, monkeypatch):
    """A start cut short half-way through a group leaves "renaming" entries; the next start
    settles them file by file (made when the file is at its new place, forgotten when it never
    left) and moves what is left."""
    class Crash(BaseException):
        pass

    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": "j1"}\n')
    _frames(r, 150)
    real = migrate._rename_into
    seen = []

    def dies_part_way(src, dest):
        seen.append(src)
        if len(seen) == 60:
            raise Crash()
        return real(src, dest)
    monkeypatch.setattr(migrate, "_rename_into", dies_part_way)
    with pytest.raises(Crash):
        start(r)
    monkeypatch.setattr(migrate, "_rename_into", real)
    start(r)
    new = r.lib / "_moonglade" / "loom" / "_frames"
    names = sorted(p.name for p in new.iterdir())
    assert names == ["f%04d.png" % i for i in range(150)]
    for i in (0, 58, 59, 60, 149):
        assert (new / ("f%04d.png" % i)).read_bytes() == b"FRAME-%d" % i
    assert not (r.lib / "loom").exists()


# ---- setup, wording and platform edges ----------------------------------------------------------

def test_a_unc_library_is_opened_with_the_uri_form_sqlite_accepts():
    """Path.as_uri() gives file://nas/share/..., and SQLite refuses the authority."""
    assert migrate._ro_uri_of("\\\\nas\\share\\lib\\catalog.db") == \
        "file:////nas/share/lib/catalog.db?mode=ro"
    assert migrate._ro_uri_of("\\\\?\\UNC\\nas\\share\\my lib\\catalog.db") == \
        "file:////nas/share/my%20lib/catalog.db?mode=ro"


@pytest.mark.skipif(sys.platform != "win32", reason="a UNC path is a Windows thing")
def test_a_catalog_on_a_unc_path_counts_as_a_moonglade_marker(tmp_path):
    db = tmp_path / "catalog.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE catalog (a)")
    con.commit()
    con.close()
    drive, rest = os.path.splitdrive(str(db))
    unc = "\\\\localhost\\" + drive[0] + "$" + rest
    if not os.path.exists(unc):
        pytest.skip("no administrative share on this machine")
    assert migrate._db_has_table(unc, "catalog") is True


def test_another_program_s_local_settings_json_in_a_library_is_not_an_install(r):
    folder = r.lib.parent / "somebodys-library"
    write(folder / "local" / "settings.json", {"theme": "dark", "font": 12})
    assert migrate.library_refusal(folder) is None
    mine = r.lib.parent / "a-copy-of-an-install"
    write(mine / "local" / "settings.json", {"port": 5000, "library_dir": "x"})
    assert "Moonglade program" in migrate.library_refusal(mine)
    notjson = r.lib.parent / "other"
    write(notjson / "local" / "settings.json", "[section]\nkey=1\n")
    assert migrate.library_refusal(notjson) is None
    empty = r.lib.parent / "begun"
    write(empty / "local" / "settings.json", "")
    assert "Moonglade program" in migrate.library_refusal(empty), "an empty one is Moonglade's"


def test_the_install_s_own_local_folder_is_no_library(r):
    r.local.mkdir(parents=True, exist_ok=True)
    assert "machine folder" in migrate.library_refusal(r.local)
    write_config(r)
    settings.set_values(library_dir=str(r.local))
    for _ in range(3):                      # it was: ok, STOP, ok, STOP -- now it never starts
        with pytest.raises(msetup.MoveStopped) as e:
            msetup.prepare("launcher")
        assert "can't be a library" in str(e.value)


def test_the_account_commands_of_the_command_line_never_wait_on_the_library(r, monkeypatch, capsys):
    """--list-web-users and --add-web-user read and write config.json alone: a library still in
    an older layout, or an older Moonglade writing it, blocked them."""
    write_config(r)
    settings.set_values(library_dir=str(r.lib))
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    monkeypatch.setattr(sys, "argv", ["moonglade", "--list-web-users"])
    core.main()
    assert "Nel" in capsys.readouterr().out
    assert (r.lib / "jobs.jsonl").is_file() and not (r.lib / "_moonglade").exists()
    # --remove-web-user does touch the library (it deletes the login's folder there)
    monkeypatch.setattr(sys, "argv", ["moonglade", "--remove-web-user", "Nel"])
    with pytest.raises(SystemExit) as e:
        core.main()
    assert "older Moonglade's layout" in str(e.value.code)


def test_prepare_can_skip_the_library_half(r):
    write_config(r)
    settings.set_values(library_dir=str(r.lib))
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    with pytest.raises(msetup.MoveStopped):
        msetup.prepare("cli")
    done = msetup.prepare("cli", library_half=False)
    assert done.library == r.lib and done.library_ran


def test_the_out_refusal_says_how_to_move_it_without_the_flag(r):
    write_config(r)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')
    with pytest.raises(msetup.MoveStopped) as e:
        msetup.prepare("server", explicit_out=str(r.lib))
    words = str(e.value)
    assert "--out or MOONGLADE_OUT" in words
    assert "library_dir in %s" % paths.settings_path() in words
    assert "without --out" in words


def test_a_library_that_appears_after_prepare_looked_is_moved_before_it_is_served(r):
    """prepare() runs the library half only when the folder is there; the server makes the
    folder itself a moment later. If it appeared in between, that session served an un-moved
    library over empty spend guards in the new homes."""
    write_config(r)
    missing = r.lib.parent / "late-library"
    settings.set_values(library_dir=str(missing))
    done = msetup.prepare("server")
    assert not done.library_ran
    write(missing / "jobs.jsonl", '{"id": "j1"}\n')
    write(missing / "train_guard.json", {"basic": {}, "retried": {}, "paid": {}})
    done.late_library()
    assert done.library_ran
    assert (missing / "_moonglade" / "records" / "train_guard.json").is_file()
    assert not (missing / "train_guard.json").exists()


def test_the_server_looks_late_after_making_the_folder_only_when_it_was_there():
    import inspect
    from moonglade import gallery as g
    src = inspect.getsource(g.main)
    assert src.index("prepare(") < src.index("folder_was_there") < src.index("late_library(")


def test_a_record_with_a_time_a_zip_cannot_hold_is_still_snapshotted(r):
    """zipfile refuses a file time before 1980: the ValueError escaped prepare() and stopped
    every launcher and server start."""
    write_config(r)
    odd = write(r.lib / "jobs.jsonl", '{"id": "j1"}\n')
    os.utime(odd, (0, 0))
    done = start(r)
    assert done.report.worked["library"]
    assert "jobs.jsonl" in _snapshot_names(r.lib / "_moonglade")
    assert (r.lib / "_moonglade" / "records" / "jobs.jsonl").is_file()


def test_config_json_saved_as_utf16_or_with_a_byte_order_mark_still_reads(r):
    doc = {"PIXAI_API_KEY": "sk-test-not-real", "AUTH_USERS": [{"username": "Nel", "password_hash": "x"}]}
    text = json.dumps(doc, indent=2)
    r.cfg.write_bytes(text.encode("utf-16"))                      # PowerShell 5.1's ">"
    got, state = migrate._read_config_strict()
    assert state == "ok" and got == doc
    r.cfg.write_bytes(b"\xef\xbb\xbf" + text.encode("utf-8"))      # an editor's BOM
    got, state = migrate._read_config_strict()
    assert state == "ok" and got == doc
    assert core._load_config() == doc, "the app reads it as the same config, not an empty one"
    r.cfg.write_bytes(b"\xff\xfe\x00 not utf-16 at all \xfe")      # neither: corrupt, no codec error
    assert migrate._read_config_strict()[1] == "corrupt"
    r.cfg.write_bytes(b"{\"k\": \"caf\xe9\"}")                       # latin-1, not UTF-8
    assert migrate._read_config_strict()[1] == "corrupt"


def test_a_config_with_a_byte_order_mark_does_not_stop_the_start(r):
    doc = {"PIXAI_API_KEY": "sk-test-not-real", "LIBRARY_DIR": str(r.lib), "AUTH_USERS": []}
    r.cfg.write_bytes(b"\xef\xbb\xbf" + json.dumps(doc).encode("utf-8"))
    start(r)                                        # the moved key is read, and dropped
    assert settings.library_dir() == str(r.lib)
    assert "LIBRARY_DIR" not in json.loads(r.cfg.read_text(encoding="utf-8"))


def test_a_lock_released_through_a_moment_s_refusal_is_still_removed(r, monkeypatch):
    r.local.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(migrate, "REMOVE_BACKOFF_S", 0.001)
    lock = migrate.FolderLock(r.local, "the app folder").acquire()
    real = os.remove
    refused = []

    def scanner_holds_it(p):
        if Path(p) == lock.path and len(refused) < 2:
            refused.append(1)
            e = PermissionError(13, "sharing violation")
            e.winerror = 32
            raise e
        return real(p)
    monkeypatch.setattr(os, "remove", scanner_holds_it)
    lock.release()
    assert refused == [1, 1] and not lock.path.exists()


def test_a_lock_another_thread_of_this_process_holds_is_not_taken_over(r, monkeypatch):
    r.local.mkdir(parents=True, exist_ok=True)
    first = migrate.FolderLock(r.local, "the app folder").acquire()
    try:
        with pytest.raises(msetup.MoveStopped) as e:
            migrate.FolderLock(r.local, "the app folder").acquire(wait=0.3)
        assert "still tidying" in str(e.value)
        assert first.path.read_text() == first.token, "the live holder's lock was not touched"
    finally:
        first.release()
    assert not first.path.exists()


def test_the_mcp_server_reports_the_apps_version():
    pytest.importorskip("fastmcp")
    from moonglade import mcp_server
    assert mcp_server.mcp.version == core.__version__


def test_the_claude_tools_notice_agrees_with_its_plural_subject():
    from moonglade import outside
    claude = outside.Item("claude", "k", "Claude Code's Moonglade tools", {}, plural=True)
    title, _msg = outside.notice_words([claude])
    assert title == "Claude Code's Moonglade tools still use Moonglade's old file names."
    task = outside.Item("task", "k", "the scheduled task “Moonglade sync”", {})
    assert outside.notice_words([task])[0].endswith("still uses Moonglade's old file names.")
    done = outside.Result(claude.label, True)
    done.plural = True
    assert "now use the new names." in outside.result_words([done])[2]
    one = outside.Result(task.label, True)
    assert "now uses the new names." in outside.result_words([one])[2]


def test_a_snippets_save_cut_short_leaves_the_old_file_whole(tmp_path, monkeypatch):
    """snippets.json was written in place: a write cut short left a torn file, which the move
    then calls a damaged new home. It is written to a temp and swapped in."""
    from pathlib import Path as RealPath
    from tests.conftest import login_client, with_csrf
    cli = login_client(tmp_path)
    assert cli.post("/api/snippets", json=with_csrf(cli, {"snippets": ["keep me"]})).status_code == 200
    target = next(tmp_path.rglob("snippets.json"))
    real_write = RealPath.write_text

    def torn(self, data, *a, **k):
        if self.name.startswith("snippets.json"):
            real_write(self, data[:3], *a, **k)
            raise OSError("the disk went away")
        return real_write(self, data, *a, **k)
    monkeypatch.setattr(RealPath, "write_text", torn)
    r = cli.post("/api/snippets", json=with_csrf(cli, {"snippets": ["a", "much", "longer", "list"]}))
    assert "disk went away" in r.get_data(as_text=True)
    assert json.loads(target.read_text()) == ["keep me"]


def test_the_wizard_saves_the_key_through_the_atomic_writer(tmp_path, monkeypatch):
    """A torn config.json stops every 3.20 start (3.19 still started): the key is saved by the
    atomic writer, so a swap that fails leaves the old file whole."""
    from tests.conftest import login_client, with_csrf
    monkeypatch.setattr(core, "_config_path", lambda: tmp_path / "config.json")
    cli = login_client(tmp_path)
    before = (tmp_path / "config.json").read_bytes()
    monkeypatch.setattr(core, "account_info",
                        lambda session, raise_on_error=False: {"quotaAmount": 5})
    monkeypatch.setattr(core.os, "replace",
                        lambda *a: (_ for _ in ()).throw(PermissionError(13, "held")))
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    r = cli.post("/api/setup/save-key", json=with_csrf(cli, {"api_key": "sk-new"}))
    assert "couldn't write config.json" in r.get_data(as_text=True)
    assert (tmp_path / "config.json").read_bytes() == before


# ---- the launcher ----------------------------------------------------------------------------
# (Run the way dev/tests/test_launcher_gets_ready_first.py runs it: the .pyw with every outside
# effect stood in for.)
import types  # noqa: E402

from tests.conftest import stub_code_module  # noqa: E402
from tests.test_launcher_gets_ready_first import _ready, _setup, launch  # noqa: E402,F401


def test_a_later_failure_is_not_given_an_earlier_start_s_sentence(launch, monkeypatch):
    """The launcher showed the last "[prepare] " line anywhere in serve.log's last 200 lines:
    one left by an earlier start (a move that stopped, then was put right) was given as the
    reason a later start (a port taken, a crash) stopped."""
    from moonglade import gallery as g
    stub_code_module(monkeypatch, "setup", _setup(lambda kind: _ready()))
    log = paths.logs_dir() / "serve.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n" + g.PREPARE_MARK + "Another Moonglade start is still tidying the "
                   "library. Wait a minute.\n", encoding="utf-8")
    run = launch(codes=[1], windows=True,
                 child_says="OSError: [WinError 10013] the port is not allowed\n")
    text = run.boxes[0][0]
    assert "still tidying" not in text
    assert "stopped as it started (code 1)" in text and "WinError 10013" in text


def test_the_launcher_probes_an_https_server_over_tls(launch, monkeypatch):
    """With --https stored the server speaks TLS: the http probe never saw it, so a second
    double-click ran prepare() under the live server and its own server then refused the port."""
    calls = []
    stub_code_module(monkeypatch, "setup", types.SimpleNamespace(
        prepare=lambda kind: calls.append(kind),
        peek_server=lambda: {"port": 5757, "launch_args": ["--https"]}))
    run = launch(codes=[0], ours_on_port=True)
    assert calls == [] and run.started == [] and run.exit == 0
    assert run.probed == ["https://localhost:5757/api/ping"]
    assert run.opened == ["https://localhost:5757/"]


# ---- a port that cannot be had --------------------------------------------------------------

def test_a_taken_port_under_the_launcher_points_at_settings_json_not_at_flags(monkeypatch, capsys):
    """The launcher passes no flags, so "--port N" and "--allow-port-reuse" were advice nobody
    under it could follow; the way out is settings.json."""
    from moonglade import gallery as g
    monkeypatch.setenv("MOONGLADE_SUPERVISED", "1")
    g._say_port_refused("other", 5000)
    err = capsys.readouterr().err
    assert str(paths.settings_path()) in err and '"port"' in err and '"launch_args"' in err
    assert "--port" not in err
    monkeypatch.delenv("MOONGLADE_SUPERVISED")
    g._say_port_refused("other", 5000)
    assert "--port 5001" in capsys.readouterr().err, "started by hand, the flags are the way"


def test_a_port_that_cannot_be_opened_is_said_with_the_way_out(monkeypatch, capsys):
    from moonglade import gallery as g
    monkeypatch.setenv("MOONGLADE_SUPERVISED", "1")
    g._say_port_unbindable(5000, OSError(10013, "access forbidden by its permissions"))
    err = capsys.readouterr().err
    assert "can't open port 5000" in err and str(paths.settings_path()) in err
    assert "excludedportrange" in err


def test_the_server_says_a_port_it_cannot_bind_instead_of_a_traceback(r, monkeypatch, capsys):
    import werkzeug.serving
    from moonglade import gallery as g
    write_config(r)
    settings.set_values(library_dir=str(r.lib), launch_args=["--skip-thumbs"], port=5224)
    write(r.lib / "jobs.jsonl", '{"id": 1}\n')

    def cannot(*a, **k):
        raise OSError(10013, "An attempt was made to access a socket in a way forbidden")
    monkeypatch.setattr(g, "port_owner", lambda host, port: "")
    monkeypatch.setattr(werkzeug.serving, "make_server", cannot)
    monkeypatch.setenv("MOONGLADE_SUPERVISED", "1")
    monkeypatch.setattr(sys, "argv", ["x"])
    assert g.main() == 2
    err = capsys.readouterr().err
    assert "can't open port 5224" in err and "excludedportrange" in err


def test_the_pack_builder_names_the_place_it_really_writes(r):
    """build_container's help named <app root>/moonglade.mgpack, a place the pack left when it
    moved into local/ (3.20)."""
    from moonglade import gallery as g
    from tests.conftest import REPO_ROOT
    src = (REPO_ROOT / "dev" / "tools" / "build_container.py").read_text(encoding="utf-8")
    assert "<app root>/moonglade.mgpack" not in src
    assert src.count("<app root>/local/moonglade.mgpack") == 2
    assert g._container_path() == r.local / paths.PACK_NAME
