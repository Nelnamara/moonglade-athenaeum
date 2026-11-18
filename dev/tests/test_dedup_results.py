"""The Dedup stages each end with ONE plain sentence behind organize.RESULT_PREFIX, and the
Control Panel's result box (gallery/src/lib/dedupResult.js) leads with it and folds the file
lines (owner pick 2026-11-18). These tests pin the sentence of every stage, zero and non-zero,
and the front-end parser that finds it."""
import json
import shutil
import subprocess
import types
from pathlib import Path

import pytest

from moonglade.gallery import init_db
from moonglade import organize as organize_mod

NODE = shutil.which("node")
P = organize_mod.RESULT_PREFIX


def _args(**kw):
    base = dict(out=None, no_content=True, dedup_delete=False, apply=False, progress=None,
                restore_orphans=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _dupes(tmp_path):
    """Two Class A pairs: 2 redundant files, 8 bytes."""
    (tmp_path / "images").mkdir()
    (tmp_path / "2023-10").mkdir()
    for mid in ("111", "222"):
        (tmp_path / "images" / "p_t1_{}.webp".format(mid)).write_bytes(b"AAAA")
        (tmp_path / "2023-10" / "{}.webp".format(mid)).write_bytes(b"AAAA")
    db = tmp_path / "catalog.db"
    init_db(db)
    return db


def _last(capsys):
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    return lines[-1]


def test_audit_sentence_with_duplicates(tmp_path, capsys):
    _dupes(tmp_path)
    organize_mod.cmd_audit(_args(), tmp_path)
    assert _last(capsys) == P + "Found 2 duplicate files (8.0 B you could free). Nothing changed."


def test_audit_sentence_with_none(tmp_path, capsys):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "p_t1_111.webp").write_bytes(b"AAAA")
    organize_mod.cmd_audit(_args(), tmp_path)
    assert _last(capsys) == P + "No duplicates found. Nothing changed."


def test_audit_lists_the_files_it_found(tmp_path, capsys):
    _dupes(tmp_path)
    organize_mod.cmd_audit(_args(), tmp_path)
    out = capsys.readouterr().out
    assert "  images" in out and "p_t1_111.webp" in out


def test_preview_sentence(tmp_path, capsys):
    db = _dupes(tmp_path)
    organize_mod.cmd_dedup(_args(), tmp_path, db)
    assert _last(capsys) == P + "2 duplicate files would move to _duplicates/ (8.0 B). Nothing moved yet."


def test_preview_delete_variant_sentence(tmp_path, capsys):
    db = _dupes(tmp_path)
    organize_mod.cmd_dedup(_args(dedup_delete=True), tmp_path, db)
    assert _last(capsys) == P + "2 duplicate files would be deleted (8.0 B). Nothing deleted yet."


def test_preview_sentence_with_none(tmp_path, capsys):
    (tmp_path / "images").mkdir()
    db = tmp_path / "catalog.db"
    init_db(db)
    organize_mod.cmd_dedup(_args(), tmp_path, db)
    assert _last(capsys) == P + "No duplicates found. Nothing changed."


def test_quarantine_sentence_is_last_even_after_the_auto_verify(tmp_path, capsys):
    db = _dupes(tmp_path)
    organize_mod.cmd_dedup(_args(apply=True), tmp_path, db)
    out = capsys.readouterr().out
    assert out.rstrip().splitlines()[-1] == P + "Moved 2 files to _duplicates/."
    assert out.count(P) == 1


def test_delete_sentence(tmp_path, capsys):
    db = _dupes(tmp_path)
    organize_mod.cmd_dedup(_args(apply=True, dedup_delete=True), tmp_path, db)
    assert _last(capsys) == P + "Deleted 2 duplicate files."


def test_verify_sentence_safe(tmp_path, capsys):
    (tmp_path / "2023-10").mkdir()
    (tmp_path / "_duplicates" / "images").mkdir(parents=True)
    (tmp_path / "2023-10" / "111.webp").write_bytes(b"SAME")
    (tmp_path / "_duplicates" / "images" / "p_t1_111.webp").write_bytes(b"SAME")
    organize_mod.cmd_verify_dupes(_args(), tmp_path)
    assert _last(capsys) == P + "All 1 file in _duplicates/ has a copy kept in the library. Safe to delete."


def test_verify_sentence_not_safe(tmp_path, capsys):
    (tmp_path / "_duplicates" / "images").mkdir(parents=True)
    (tmp_path / "_duplicates" / "images" / "p_t1_222.webp").write_bytes(b"LONELY")
    organize_mod.cmd_verify_dupes(_args(), tmp_path)
    assert _last(capsys) == (P + "Not safe to delete yet: 1 of 1 file in _duplicates/ need a look. "
                             "Review the flagged items above.")


def test_verify_sentence_when_empty(tmp_path, capsys):
    organize_mod.cmd_verify_dupes(_args(), tmp_path)
    assert _last(capsys) == P + "_duplicates/ is empty, so there is nothing to check."


def test_thousands_separators(capsys):
    organize_mod._result("x")
    assert "{:,}".format(12345) == "12,345" and organize_mod._files(12345) == "12,345 duplicate files"


def test_panel_audit_prefix_matches_the_python_constant():
    """The front end finds the line by this prefix: the two constants must agree."""
    js = (Path(__file__).resolve().parents[2] / "gallery" / "src" / "lib" / "dedupResult.js").read_text(encoding="utf-8")
    assert 'DEDUP_RESULT_PREFIX = "{}"'.format(P) in js


@pytest.mark.skipif(NODE is None, reason="node not installed")
def test_front_end_parser_leads_with_the_sentence_and_folds_the_files():
    mod = Path(__file__).resolve().parents[2] / "gallery" / "src" / "lib" / "dedupResult.js"
    script = (
        "import(%s).then(m => {"
        "const lines = ['Dedup plan: 14 redundant files', '  2026-10/a.webp', '  ... and 12 more',"
        " '  safe - byte-identical keeper exists       : 3', '', %s];"
        "console.log(JSON.stringify([m.parseDedupResult(lines), m.parseDedupResult(['nothing here'])]));"
        "})" % (json.dumps(mod.as_uri()),
                json.dumps(P + "14 duplicate files would move to _duplicates/ (25.6 MB). Nothing moved yet."))
    )
    out = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    got, none = json.loads(out.stdout)
    assert got["sentence"] == "14 duplicate files would move to _duplicates/ (25.6 MB). Nothing moved yet."
    assert got["files"] == ["2026-10/a.webp", "... and 12 more"]
    assert got["count"] == "14"
    assert none is None
