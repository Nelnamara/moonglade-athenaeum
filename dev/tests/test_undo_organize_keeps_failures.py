"""Undo organize must not forget a move it could not undo (red team, 2026-11-19).

It deleted its manifest even when some reverts failed, so those files could never be put
back; and with --convert the manifest named the file as it was BEFORE conversion, so Undo
found nothing there and counted it "already gone".
"""
import csv
import io
import pathlib
from types import SimpleNamespace

import pytest

from moonglade import organize as organize_mod
from moonglade import paths
from moonglade.catalog import CATALOG_FIELDS, save_catalog


def _seed(tmp_path, names):
    db = tmp_path / "catalog.db"
    rows = []
    for i, name in enumerate(names, 1):
        rows.append({f: "" for f in CATALOG_FIELDS} | {
            "media_id": "m%d" % i, "task_id": "T%d" % i, "prompt_preview": "alpha",
            "created_at": "2024-03-01T00:00:00", "filename": name})
    save_catalog(db, rows)
    (tmp_path / "images").mkdir()
    return db


def _org_args(tmp_path, **kw):
    base = dict(out=str(tmp_path), name_length=60, name_sep="_", convert=None,
                dry_run=False, embed_metadata=False, jpeg_quality=92, jpeg_bg="white",
                keep_webp=False, progress=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _manifest(tmp_path):
    return paths.decisions_path(tmp_path, organize_mod.ORGANIZE_MANIFEST)


def _undo(tmp_path):
    organize_mod.cmd_undo_organize(SimpleNamespace(out=str(tmp_path), dry_run=False), tmp_path)


def test_a_revert_that_fails_stays_in_the_manifest_for_the_next_undo(tmp_path, monkeypatch):
    db = _seed(tmp_path, ["alpha_T1_m1.png", "alpha_T2_m2.png"])
    for n in ("alpha_T1_m1.png", "alpha_T2_m2.png"):
        (tmp_path / "images" / n).write_bytes(n.encode())
    organize_mod.cmd_organize(_org_args(tmp_path), tmp_path, tmp_path / "images", db)
    locked = tmp_path / "2024-03" / "alpha_T2_m2.png"
    assert locked.exists()

    real_replace = pathlib.Path.replace

    def replace(self, target):
        if self == locked:
            raise PermissionError(32, "The process cannot access the file")
        return real_replace(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", replace)
    _undo(tmp_path)
    assert (tmp_path / "images" / "alpha_T1_m1.png").exists(), "the other move was undone"
    assert _manifest(tmp_path).exists(), "Undo deleted the record of a move it could not undo"
    with open(_manifest(tmp_path), newline="", encoding="utf-8") as f:
        left = list(csv.DictReader(f))
    assert [(r["old_path"], r["new_path"]) for r in left] == [
        ("images/alpha_T2_m2.png", "2024-03/alpha_T2_m2.png")]

    monkeypatch.setattr(pathlib.Path, "replace", real_replace)   # the lock lets go
    _undo(tmp_path)
    assert (tmp_path / "images" / "alpha_T2_m2.png").exists()
    assert not locked.exists()
    assert not _manifest(tmp_path).exists()


def test_undo_never_moves_over_a_file_already_at_the_old_place(tmp_path):
    db = _seed(tmp_path, ["alpha_T1_m1.png"])
    (tmp_path / "images" / "alpha_T1_m1.png").write_bytes(b"organized")
    organize_mod.cmd_organize(_org_args(tmp_path), tmp_path, tmp_path / "images", db)
    (tmp_path / "images" / "alpha_T1_m1.png").write_bytes(b"a new file since")
    _undo(tmp_path)
    assert (tmp_path / "images" / "alpha_T1_m1.png").read_bytes() == b"a new file since"
    assert (tmp_path / "2024-03" / "alpha_T1_m1.png").read_bytes() == b"organized"
    assert _manifest(tmp_path).exists()


@pytest.mark.parametrize("keep_webp", [False, True], ids=["converted", "kept-webp"])
def test_a_converted_move_is_recorded_under_its_real_name_and_undoes(tmp_path, keep_webp):
    Image = pytest.importorskip("PIL.Image")
    db = _seed(tmp_path, ["alpha_T1_m1.webp"])
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), "red").save(buf, "WEBP")
    (tmp_path / "images" / "alpha_T1_m1.webp").write_bytes(buf.getvalue())
    organize_mod.cmd_organize(_org_args(tmp_path, convert="png", keep_webp=keep_webp),
                              tmp_path, tmp_path / "images", db)
    assert (tmp_path / "2024-03" / "alpha_T1_m1.png").exists()
    with open(_manifest(tmp_path), newline="", encoding="utf-8") as f:
        rows = [(r["old_path"], r["new_path"]) for r in csv.DictReader(f)]
    if keep_webp:
        assert rows == [("images/alpha_T1_m1.webp", "2024-03/alpha_T1_m1.webp")]
    else:
        assert rows == [("images/alpha_T1_m1.png", "2024-03/alpha_T1_m1.png")], \
            "the manifest must name the file as it ended up, after conversion"
    _undo(tmp_path)
    back = "alpha_T1_m1.webp" if keep_webp else "alpha_T1_m1.png"
    assert (tmp_path / "images" / back).exists(), "Undo could not find the converted file"
    assert not (tmp_path / "2024-03" / back).exists()
    assert not _manifest(tmp_path).exists()
