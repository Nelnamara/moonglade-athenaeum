"""--dedup --apply --dedup-delete must never keep a damaged copy and delete the whole one.

Same-media_id copies were ranked by folder alone, and only Quarantine was byte-checked
afterwards, so a truncated download in a month folder outranked the whole image in images/
and Delete removed the whole one for good (red team, 2026-11-19). Real image files here,
because "opens as an image" is the property under test.
"""
import io
import types

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image, PngImagePlugin  # noqa: E402

from moonglade import organize as organize_mod  # noqa: E402
from moonglade.gallery import init_db  # noqa: E402


def _png(color, text=None):
    buf = io.BytesIO()
    info = None
    if text:
        info = PngImagePlugin.PngInfo()
        info.add_text("prompt", text)
    Image.new("RGB", (64, 64), color).save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


def _args(**kw):
    base = dict(out=None, no_content=True, dedup_delete=True, apply=True, progress=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _tree(tmp_path, month_bytes, images_bytes):
    (tmp_path / "images").mkdir()
    (tmp_path / "2023-10").mkdir()
    month = tmp_path / "2023-10" / "111.png"          # the folder dedup prefers
    flat = tmp_path / "images" / "p_t1_111.png"
    month.write_bytes(month_bytes)
    flat.write_bytes(images_bytes)
    db = tmp_path / "catalog.db"
    init_db(db)
    return month, flat, db


def test_a_damaged_copy_in_the_preferred_folder_is_the_one_deleted(tmp_path):
    whole = _png("red")
    month, flat, db = _tree(tmp_path, whole[: len(whole) // 2], whole)
    grp = organize_mod.audit_collection(tmp_path, content=False)["class_a"][0]
    assert grp["keeper"][0] == flat, "the copy that opens must be kept over a tidier folder"
    organize_mod.cmd_dedup(_args(), tmp_path, db)
    assert flat.exists() and flat.read_bytes() == whole, "Delete removed the whole image"
    assert not month.exists(), "the damaged copy is the redundant one"


def test_a_truncated_copy_is_damaged_even_after_similar_relaxed_pillow(tmp_path, monkeypatch):
    """moonglade/similar.py sets Pillow's process-wide LOAD_TRUNCATED_IMAGES at import, and
    with it a half PNG "opens". The check must not depend on what the process imported."""
    from PIL import ImageFile
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", True)
    whole = _png("red")
    half = tmp_path / "half.png"
    half.write_bytes(whole[: len(whole) // 2])
    assert organize_mod._opens_as_image(half) is False
    assert ImageFile.LOAD_TRUNCATED_IMAGES is True, "the check must put the setting back"


def test_a_damaged_copy_loses_even_when_it_is_the_bigger_file(tmp_path):
    """Size alone is no proof: a truncated download of a busy picture can still outweigh a
    whole copy of a plain one."""
    noise = Image.effect_noise((256, 256), 90).convert("RGB")
    buf = io.BytesIO()
    noise.save(buf, "WEBP", quality=95)
    damaged = buf.getvalue()[: len(buf.getvalue()) * 2 // 3]
    whole = _png("red")
    assert len(damaged) > len(whole)
    (tmp_path / "images").mkdir()
    (tmp_path / "2023-10").mkdir()
    month = tmp_path / "2023-10" / "111.webp"
    flat = tmp_path / "images" / "p_t1_111.png"
    month.write_bytes(damaged)
    flat.write_bytes(whole)
    db = tmp_path / "catalog.db"
    init_db(db)
    organize_mod.cmd_dedup(_args(), tmp_path, db)
    assert flat.exists(), "Delete removed the only copy that opens"
    assert not month.exists()


def test_two_different_pictures_under_one_id_are_both_kept(tmp_path, capsys):
    month, flat, db = _tree(tmp_path, _png("red"), _png("blue"))
    organize_mod.cmd_dedup(_args(), tmp_path, db)
    assert month.exists() and flat.exists(), "Delete removed a picture that was not a copy"
    last = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()][-1]
    assert last == organize_mod.RESULT_PREFIX + \
        "Nothing deleted. Kept 1 copy that is not the same as the one kept."


def test_nothing_is_deleted_when_no_copy_opens(tmp_path):
    month, flat, db = _tree(tmp_path, b"\x89PNG broken one", b"\x89PNG broken two!")
    organize_mod.cmd_dedup(_args(), tmp_path, db)
    assert month.exists() and flat.exists(), \
        "with no copy that opens, Delete cannot know which one to keep"


def test_the_larger_whole_copy_is_kept_and_the_same_picture_deleted(tmp_path):
    small, large = _png("green"), _png("green", text="a long embedded prompt " * 20)
    assert len(large) > len(small)
    month, flat, db = _tree(tmp_path, small, large)
    organize_mod.cmd_dedup(_args(), tmp_path, db)
    assert flat.exists() and flat.read_bytes() == large, "the larger whole copy must be kept"
    assert not month.exists(), "a smaller copy of the same pixels is redundant"


def test_the_quarantine_check_tells_two_opaque_pictures_apart(tmp_path):
    """The pixel compare looked at the alpha band only, so a different picture quarantined
    under the same id was reported "metadata-only" and safe to delete."""
    (tmp_path / "2023-10").mkdir()
    (tmp_path / "_duplicates" / "images").mkdir(parents=True)
    (tmp_path / "2023-10" / "111.png").write_bytes(_png("red"))
    (tmp_path / "_duplicates" / "images" / "p_t1_111.png").write_bytes(_png("blue"))
    res = organize_mod.verify_quarantine(tmp_path)
    assert len(res["differs"]) == 1 and res["meta_only"] == 0


def test_the_dry_run_counts_only_what_it_would_really_delete(tmp_path, capsys):
    month, flat, db = _tree(tmp_path, _png("red"), _png("blue"))
    organize_mod.cmd_dedup(_args(apply=False), tmp_path, db)
    last = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()][-1]
    assert last.startswith(organize_mod.RESULT_PREFIX + "Nothing would be deleted.")
    assert month.exists() and flat.exists()
