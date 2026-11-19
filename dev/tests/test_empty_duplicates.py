"""Empty _duplicates/ (One Tidy place, 2026-11-19): the last step of the duplicates road.

It sends the files in _duplicates/ to the Recycle Bin, and only:
  * after a --verify-dupes that found every quarantined file safe (a byte- or pixel-identical
    keeper still in the library; nothing DIFFERS, nothing ORPHAN) -- that check, and only that
    check, writes the exact list it passed;
  * while _duplicates/ is exactly that list (a file added, removed or changed since blocks it);
  * after checking again on the spot (a keeper deleted since would leave an orphan);
  * with READ_ONLY off and send2trash installed -- without it, nothing is ever hard-deleted.
These drive moonglade/organize.py's cmd_empty_duplicates against real files, with send2trash
replaced by a stand-in that moves each file into a "bin" folder (CI installs no send2trash, and
no test may touch the real Recycle Bin). The mutation checks at the foot prove the gate is what
stops each case: with the gate bypassed, the same scenario empties the folder."""
import shutil
import sys
import types

import pytest

from moonglade import backup as core
from moonglade import organize as organize_mod
from moonglade.gallery import init_db

P = organize_mod.RESULT_PREFIX


def _args(**kw):
    base = dict(apply=False, progress=None, restore_orphans=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _last(capsys):
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return lines[-1]


@pytest.fixture
def bin_(tmp_path, monkeypatch):
    """A stand-in send2trash: moves each file into tmp_path/bin and records it."""
    binned = []
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def send2trash(path):
        src = type(tmp_path)(path)
        binned.append(src.name)
        shutil.move(str(src), str(bin_dir / (str(len(binned)) + "_" + src.name)))
    mod = types.ModuleType("send2trash")
    mod.send2trash = send2trash
    monkeypatch.setitem(sys.modules, "send2trash", mod)
    return binned


def _library(tmp_path, n=2):
    """`n` quarantined copies in _duplicates/, each with its keeper in a month folder, plus one
    Duplicate Review undo note. Returns the library folder."""
    out = tmp_path / "lib"
    (out / "2023-10").mkdir(parents=True)
    q = out / "_duplicates" / "images"
    q.mkdir(parents=True)
    for i in range(n):
        mid = str(111 + i)
        (out / "2023-10" / "{}.webp".format(mid)).write_bytes(b"SAME" + mid.encode())
        (q / "p_t1_{}.webp".format(mid)).write_bytes(b"SAME" + mid.encode())
    (q / "p_t1_111.webp.undo.json").write_text("{}", encoding="utf-8")
    init_db(out / "catalog.db")
    return out


def _verify(out):
    organize_mod.cmd_verify_dupes(_args(), out)


def _empty(out, **kw):
    return organize_mod.cmd_empty_duplicates(_args(**kw), out, out / "catalog.db")


def _files_left(out):
    return sorted(p.name for p in (out / "_duplicates").rglob("*") if p.is_file()) \
        if (out / "_duplicates").exists() else []


# ---------------------------------------------------------------------------- the happy road

def test_a_clean_check_then_a_preview_moves_nothing(tmp_path, bin_, capsys):
    out = _library(tmp_path)
    _verify(out)
    assert _last(capsys) == P + "All 2 files in _duplicates/ (14.0 B) have a copy kept in the library. Safe to delete."
    _empty(out)
    assert _last(capsys) == P + "2 files (14.0 B) in _duplicates/ would go to the Recycle Bin. Nothing moved yet."
    assert bin_ == [] and len(_files_left(out)) == 3


def test_a_clean_check_then_apply_sends_the_files_to_the_recycle_bin(tmp_path, bin_, capsys):
    out = _library(tmp_path)
    _verify(out)
    capsys.readouterr()
    r = _empty(out, apply=True)
    assert _last(capsys) == P + "Moved 2 files (14.0 B) from _duplicates/ to the Recycle Bin. _duplicates/ is gone."
    assert sorted(bin_) == ["p_t1_111.webp", "p_t1_111.webp.undo.json", "p_t1_112.webp"]
    assert not (out / "_duplicates").exists()
    assert r["emptied"] == 2 and r["folder_gone"] is True
    # the keepers are untouched, and the all-clear was used up
    assert sorted(p.name for p in (out / "2023-10").iterdir()) == ["111.webp", "112.webp"]
    assert organize_mod._read_verified_snapshot(out) is None


def test_a_folder_holding_something_else_stays(tmp_path, bin_, capsys):
    out = _library(tmp_path)
    (out / "_duplicates" / "notes.txt").write_text("mine", encoding="utf-8")
    _verify(out)
    _empty(out, apply=True)
    assert _last(capsys).endswith("_duplicates/ still holds other files.")
    assert _files_left(out) == ["notes.txt"]


# ---------------------------------------------------------------------------- every gate

def test_no_check_no_emptying(tmp_path, bin_, capsys):
    out = _library(tmp_path)
    _empty(out, apply=True)
    assert _last(capsys).startswith(P + "Not emptied: _duplicates/ has not passed Check _duplicates/")
    assert bin_ == [] and len(_files_left(out)) == 3


def test_a_check_that_found_an_orphan_opens_nothing(tmp_path, bin_, capsys):
    out = _library(tmp_path)
    (out / "_duplicates" / "images" / "p_t1_999.webp").write_bytes(b"LONELY")
    _verify(out)
    assert "Not safe to delete yet" in _last(capsys)
    assert organize_mod._read_verified_snapshot(out) is None
    _empty(out, apply=True)
    assert "Not emptied" in _last(capsys) and bin_ == []


def test_a_failed_check_withdraws_an_earlier_all_clear(tmp_path, bin_, capsys):
    out = _library(tmp_path)
    _verify(out)
    assert organize_mod._read_verified_snapshot(out) is not None
    (out / "2023-10" / "111.webp").unlink()            # its keeper goes: now an orphan
    _verify(out)
    assert organize_mod._read_verified_snapshot(out) is None
    _empty(out, apply=True)
    assert "Not emptied" in _last(capsys) and bin_ == []


def test_a_file_added_since_the_check_blocks_it(tmp_path, bin_, capsys):
    out = _library(tmp_path)
    _verify(out)
    # a SAFE file (its keeper exists): only the check's own list can tell it arrived later
    (out / "2023-10" / "120.webp").write_bytes(b"NEW")
    (out / "_duplicates" / "images" / "p_t1_120.webp").write_bytes(b"NEW")
    _empty(out, apply=True)
    assert _last(capsys) == (P + "Not emptied: _duplicates/ changed since it was checked (1 added). "
                             "Run the check again. Nothing was moved.")
    assert bin_ == [] and len(_files_left(out)) == 4


def test_a_file_changed_since_the_check_blocks_it(tmp_path, bin_, capsys):
    out = _library(tmp_path)
    _verify(out)
    (out / "_duplicates" / "images" / "p_t1_111.webp").write_bytes(b"DIFFERENT AND LONGER")
    _empty(out, apply=True)
    assert "changed since it was checked (1 changed)" in _last(capsys) and bin_ == []


def test_a_keeper_deleted_since_the_check_is_caught_by_checking_again(tmp_path, bin_, capsys):
    out = _library(tmp_path)
    _verify(out)
    (out / "2023-10" / "112.webp").unlink()            # _duplicates/ itself is unchanged
    _empty(out, apply=True)
    assert _last(capsys).startswith(P + "Not emptied: _duplicates/ is no longer all clear (0 differ, 1 with no copy kept")
    assert bin_ == [] and len(_files_left(out)) == 3
    assert organize_mod._read_verified_snapshot(out) is None


def test_read_only_refuses(tmp_path, bin_, capsys, monkeypatch):
    out = _library(tmp_path)
    _verify(out)
    monkeypatch.setattr(core, "READ_ONLY", True)
    _empty(out, apply=True)
    assert _last(capsys) == P + "Not emptied: read-only mode is on. Nothing was moved."
    assert bin_ == [] and len(_files_left(out)) == 3


def test_without_send2trash_nothing_is_deleted(tmp_path, capsys, monkeypatch):
    out = _library(tmp_path)
    _verify(out)
    monkeypatch.setitem(sys.modules, "send2trash", None)   # `import send2trash` -> ImportError
    _empty(out, apply=True)
    assert "needs the send2trash package" in _last(capsys)
    assert len(_files_left(out)) == 3


def test_an_empty_folder_says_so(tmp_path, bin_, capsys):
    out = tmp_path / "lib"
    out.mkdir()
    _empty(out, apply=True)
    assert _last(capsys) == P + "_duplicates/ is empty, so there is nothing to empty."


# ---------------------------------------------------------------------------- mutation checks

@pytest.mark.parametrize("scenario", ["no check", "added since"])
def test_the_check_gate_is_what_stops_it(tmp_path, bin_, capsys, monkeypatch, scenario):
    """With the gate bypassed, the very scenarios above empty the folder -- so it is the gate,
    not some other accident of the setup, that the gate tests are watching."""
    out = _library(tmp_path)
    if scenario == "added since":
        _verify(out)
        (out / "2023-10" / "120.webp").write_bytes(b"NEW")
        (out / "_duplicates" / "images" / "p_t1_120.webp").write_bytes(b"NEW")
    monkeypatch.setattr(organize_mod, "empty_gate", lambda out_dir, listing: "")
    _empty(out, apply=True)
    assert _last(capsys).startswith(P + "Moved "), "the bypassed gate should have let it through"
    assert bin_, "nothing was binned with the gate bypassed -- the scenario no longer exercises it"


def test_the_gate_reads_only_the_checks_own_list(tmp_path):
    """The list exists only after an all-clear check; a hand-made one that does not match what
    is on disk opens nothing."""
    out = _library(tmp_path)
    listing = organize_mod._quarantine_listing(out)
    assert organize_mod.empty_gate(out, listing).startswith("_duplicates/ has not passed")
    organize_mod._write_verified_snapshot(out, {"_duplicates/images/x.webp": [1, 1]})
    assert "changed since it was checked" in organize_mod.empty_gate(out, listing)


# ---------------------------------------------------------------------------- the Panel and the CLI

def test_the_cli_flag_exists_and_previews_by_default(monkeypatch):
    import argparse
    seen = {}
    orig = argparse.ArgumentParser.parse_args

    def grab(self, *a, **k):
        ns = orig(self, ["--empty-duplicates"])
        seen["ns"] = ns
        raise SystemExit(0)
    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", grab)
    with pytest.raises(SystemExit):
        core.main()
    assert seen["ns"].empty_duplicates is True and seen["ns"].apply is False


def test_the_panel_action_is_destructive_and_localhost_only(tmp_path, monkeypatch):
    import io
    import subprocess
    from moonglade.gallery import CATALOG_FIELDS, create_app, save_catalog
    from tests.conftest import login_test_client
    spawned = []

    class FakeProc:
        def __init__(self):
            self.stdout = io.StringIO("")

        def wait(self):
            return 0
    # only the job itself counts (the app also asks git for its version through Popen)
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **k: (
        spawned.append(argv) if "--empty-duplicates" in argv else None) or FakeProc())
    save_catalog(tmp_path / "catalog.db", [{f: "" for f in CATALOG_FIELDS} | {"media_id": "1"}])
    cli = login_test_client(create_app(tmp_path))
    r = cli.post("/api/panel/run", json={"action": "empty-dupes"})
    assert r.status_code >= 400 and not spawned, "ran without the confirm"
    r = cli.post("/api/panel/run", json={"action": "empty-dupes", "confirm": True},
                 environ_overrides={"REMOTE_ADDR": "192.168.1.9"})
    assert r.status_code == 403 and not spawned, "ran for a LAN session"
    d = cli.get("/api/panel/summary").get_json()
    assert any(a["action"] == "empty-dupes" and a["destructive"] for a in d["actions"])
    lan = cli.get("/api/panel/summary", environ_overrides={"REMOTE_ADDR": "192.168.1.9"}).get_json()
    assert not any(a["action"] == "empty-dupes" for a in lan["actions"]), "a LAN session sees the button"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_panel_reads_the_checks_own_all_clear_sentence(tmp_path, capsys):
    """The Tidy tab opens Empty _duplicates/ off Check's one sentence (lib/dedupResult.js,
    verifiedAllClear): the sentence this command really prints must parse, with its count and
    size, and the not-safe one must not."""
    import json
    import subprocess
    from pathlib import Path
    out = _library(tmp_path)
    _verify(out)
    safe = _last(capsys)[len(P):]
    (out / "2023-10" / "111.webp").unlink()
    _verify(out)
    unsafe = _last(capsys)[len(P):]
    mod = Path(__file__).resolve().parents[2] / "gallery" / "src" / "lib" / "dedupResult.js"
    script = ("import(%s).then(m => console.log(JSON.stringify([m.verifiedAllClear({sentence: %s}),"
              " m.verifiedAllClear({sentence: %s})])))" % (
                  json.dumps(mod.as_uri()), json.dumps(safe), json.dumps(unsafe)))
    r = subprocess.run([shutil.which("node"), "-e", script], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got, none = json.loads(r.stdout)
    assert got == {"count": "2", "size": "14.0 B"}, safe
    assert none is None, unsafe
