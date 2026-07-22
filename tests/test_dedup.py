"""Tests for the duplicate audit/dedup engine and the resume-matcher alignment
that fixes the images/+month duplication bug."""
import types
from pathlib import Path

import pytest

import pixai_gallery_backup as core
from pixai_gallery import (media_id_of, find_files_for_media_id, find_image_file,
                           init_db, save_catalog, load_catalog)


# ---------------------------------------------------------------------------
# media_id_of  (INVARIANT 1 - single source of truth)
# ---------------------------------------------------------------------------

def test_media_id_of_flat():
    assert media_id_of("prompt_text_task123_999888.webp") == "999888"


def test_media_id_of_batch():
    assert media_id_of("01_999888.webp") == "999888"


def test_media_id_of_bare():
    # The single-image --organize month layout: no underscore at all.
    assert media_id_of("999888.webp") == "999888"


# ---------------------------------------------------------------------------
# find_files_for_media_id / already_downloaded  (the alignment fix)
# ---------------------------------------------------------------------------

def test_resume_finds_bare_month_file(tmp_path):
    """Regression: bare <mid>.ext files (single-image --organize) MUST be seen by
    resume. Before the fix the `*_<mid>.*` glob missed them, causing re-downloads
    and the images/+month duplication."""
    month = tmp_path / "2023-10"
    month.mkdir()
    (month / "375741317926742088.webp").write_bytes(b"img")
    assert core.already_downloaded(tmp_path, "375741317926742088") is not None


def test_find_files_returns_both_layouts(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "2023-10").mkdir()
    (tmp_path / "images" / "prompt_t1_555.webp").write_bytes(b"img")
    (tmp_path / "2023-10" / "555.webp").write_bytes(b"img")
    matches = find_files_for_media_id(tmp_path, "555")
    assert len(matches) == 2


def test_exact_match_prevents_substring_collision(tmp_path):
    # mid "999" must NOT match a file whose id is "1999".
    (tmp_path / "1999.webp").write_bytes(b"img")
    assert find_files_for_media_id(tmp_path, "999") == []


def test_gallery_thumbnails_excluded(tmp_path):
    g = tmp_path / "gallery"
    g.mkdir()
    (g / "777.webp").write_bytes(b"thumb")
    assert core.already_downloaded(tmp_path, "777") is None


# ---------------------------------------------------------------------------
# bucket classification + keeper priority
# ---------------------------------------------------------------------------

def test_bucket_classification():
    assert core._bucket_of("images/x.webp") == "images"
    assert core._bucket_of("batches/some_batch/01_x.webp") == "batches"
    assert core._bucket_of("2023-10/x.webp") == "month"
    assert core._bucket_of("unknown-date/x.webp") == "month"
    assert core._bucket_of("randomfolder/x.webp") == "other"


# ---------------------------------------------------------------------------
# audit_collection
# ---------------------------------------------------------------------------

def _make_class_a_tree(tmp_path):
    (tmp_path / "images").mkdir()
    (tmp_path / "2023-10").mkdir()
    # same media_id in images/ (flat) and month/ (bare) -> Class A
    (tmp_path / "images" / "a_prompt_t1_111.webp").write_bytes(b"AAAA")
    (tmp_path / "2023-10" / "111.webp").write_bytes(b"AAAA")
    # a unique file (no dupe)
    (tmp_path / "2023-10" / "222.webp").write_bytes(b"BBBB")
    return tmp_path


def test_audit_detects_class_a_and_keeps_organized(tmp_path):
    _make_class_a_tree(tmp_path)
    rep = core.audit_collection(tmp_path, content=False)
    assert rep["totals"]["class_a_groups"] == 1
    grp = rep["class_a"][0]
    assert grp["media_id"] == "111"
    # keeper must be the organized (month) copy, not the flat images/ one
    assert grp["keeper"][2] == "month"
    assert grp["losers"][0][2] == "images"


def test_audit_detects_class_b_content_dupe(tmp_path):
    (tmp_path / "images").mkdir()
    # identical bytes, DIFFERENT media_ids -> Class B
    (tmp_path / "images" / "p_t1_333.webp").write_bytes(b"IDENTICAL-BYTES")
    (tmp_path / "images" / "p_t2_444.webp").write_bytes(b"IDENTICAL-BYTES")
    rep = core.audit_collection(tmp_path, content=True)
    assert rep["totals"]["class_b_groups"] == 1


# ---------------------------------------------------------------------------
# Zero-byte files (audit 2026-07-21, S-tier: a 0-byte file could win keeper
# selection on bucket priority alone and send the REAL image to quarantine --
# or, under --dedup-delete, straight to unlink() with no verify step at all)
# ---------------------------------------------------------------------------

def test_zero_byte_file_is_invisible_to_the_audit(tmp_path):
    """The primary fix: a 0-byte file must not enter by_mid/by_size at all, so it can
    never become a keeper OR a loser -- an empty file isn't a duplicate of anything."""
    (tmp_path / "images").mkdir()
    (tmp_path / "2023-10").mkdir()
    (tmp_path / "images" / "a_prompt_t1_111.webp").write_bytes(b"REAL-IMAGE-BYTES")
    (tmp_path / "2023-10" / "111.webp").write_bytes(b"")   # interrupted download
    rep = core.audit_collection(tmp_path, content=False)
    assert rep["totals"]["class_a_groups"] == 0, (
        "the zero-byte file paired with the real one as a Class A duplicate group")


def test_zero_byte_file_would_lose_to_a_real_copy_even_by_bucket_priority_alone(tmp_path):
    """The scenario that made this an S-tier finding rather than a curiosity: place the
    EMPTY file in the higher-priority bucket ('batches' outranks 'images' in
    _BUCKET_PRIORITY) and the real image in the lower-priority one -- exactly the layout
    where bucket-priority-only selection would have picked the empty file as keeper and
    sent the real image to quarantine. Same assertion as the test above, but the tree is
    built specifically to defeat a fix that only reordered priority instead of excluding
    zero-byte files from the pool."""
    (tmp_path / "images").mkdir()
    (tmp_path / "batches" / "b1").mkdir(parents=True)
    (tmp_path / "images" / "p_t1_111.webp").write_bytes(b"REAL-IMAGE-BYTES")
    (tmp_path / "batches" / "b1" / "111.webp").write_bytes(b"")
    rep = core.audit_collection(tmp_path, content=False)
    assert rep["totals"]["class_a_groups"] == 0, (
        "the empty batches/ file paired with the real images/ file as a duplicate group "
        "-- bucket priority alone would have made it the keeper")


def test_find_image_file_does_not_serve_a_zero_byte_file(tmp_path):
    """The third site the audit found for the same invariant: find_image_file()'s FAST
    path (try the catalog's exact filename first) checked is_file() but not size, so a
    catalog row still pointing at its original filename would have the gallery serve a
    truncated/interrupted download back as if it were the real image -- while the
    fallback path (find_files_for_media_id, exercised by the tests below) already
    correctly skipped zero-byte files. Both paths must agree."""
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "p_t1_111.webp").write_bytes(b"")   # interrupted download
    assert find_image_file(tmp_path, "111", "p_t1_111.webp") is None


def test_find_image_file_still_finds_a_real_file_by_exact_filename(tmp_path):
    """The fast path must keep working for the normal case -- this guards against a
    fix that over-corrects into refusing every file, not just empty ones."""
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "p_t1_111.webp").write_bytes(b"REAL-IMAGE-BYTES")
    found = find_image_file(tmp_path, "111", "p_t1_111.webp")
    assert found is not None
    assert found.name == "p_t1_111.webp"


def test_dedup_delete_never_unlinks_the_only_real_copy(tmp_path):
    """The sharpest version of the bug: --dedup --apply --dedup-delete skips the
    auto-verify safety net entirely (unlike plain --apply, which flags a mismatch as
    'REVIEW NEEDED'), so if a zero-byte file ever won keeper selection, the real image
    would be gone with no recovery path. Drives the real CLI action, not audit_collection
    directly."""
    (tmp_path / "images").mkdir()
    (tmp_path / "batches" / "b1").mkdir(parents=True)
    (tmp_path / "images" / "p_t1_111.webp").write_bytes(b"THE-ONLY-REAL-COPY")
    (tmp_path / "batches" / "b1" / "111.webp").write_bytes(b"")   # interrupted, 0 bytes
    db = tmp_path / "catalog.db"
    init_db(db)
    core.cmd_dedup(_args(apply=True, dedup_delete=True), tmp_path, db)
    assert (tmp_path / "images" / "p_t1_111.webp").exists(), (
        "the real image was deleted or quarantined -- the zero-byte file was treated "
        "as a duplicate of it")
    assert (tmp_path / "images" / "p_t1_111.webp").read_bytes() == b"THE-ONLY-REAL-COPY"
    # The empty file is simply left alone -- it was never part of a duplicate group,
    # so dedup correctly has nothing to say about it either way.
    assert not (tmp_path / "_duplicates").exists()


# ---------------------------------------------------------------------------
# cmd_dedup (quarantine + catalog reconcile)
# ---------------------------------------------------------------------------

def _args(**kw):
    base = dict(out=None, no_content=True, dedup_delete=False, apply=False, progress=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_dedup_dry_run_changes_nothing(tmp_path):
    _make_class_a_tree(tmp_path)
    db = tmp_path / "catalog.db"
    init_db(db)
    core.cmd_dedup(_args(apply=False), tmp_path, db)
    # both copies still present
    assert (tmp_path / "images" / "a_prompt_t1_111.webp").exists()
    assert (tmp_path / "2023-10" / "111.webp").exists()
    assert not (tmp_path / "_duplicates").exists()


def test_dedup_apply_quarantines_loser_keeps_keeper(tmp_path):
    _make_class_a_tree(tmp_path)
    db = tmp_path / "catalog.db"
    init_db(db)
    save_catalog(db, [{"media_id": "111", "filename": "a_prompt_t1_111.webp",
                       "batch": "", "task_id": "t1"}])
    core.cmd_dedup(_args(apply=True), tmp_path, db)
    # keeper (month) stays, loser (images) moved to _duplicates/
    assert (tmp_path / "2023-10" / "111.webp").exists()
    assert not (tmp_path / "images" / "a_prompt_t1_111.webp").exists()
    assert (tmp_path / "_duplicates" / "images" / "a_prompt_t1_111.webp").exists()
    # catalog reconciled to point at the surviving bare filename
    rows = {r["media_id"]: r for r in load_catalog(db)}
    assert rows["111"]["filename"] == "111.webp"


# ---------------------------------------------------------------------------
# verify_quarantine
# ---------------------------------------------------------------------------

def test_verify_safe_when_identical_keeper_exists(tmp_path):
    (tmp_path / "2023-10").mkdir()
    (tmp_path / "_duplicates" / "images").mkdir(parents=True)
    (tmp_path / "2023-10" / "111.webp").write_bytes(b"SAME")
    (tmp_path / "_duplicates" / "images" / "p_t1_111.webp").write_bytes(b"SAME")
    res = core.verify_quarantine(tmp_path)
    assert res["safe"] == 1
    assert res["differs"] == [] and res["orphan"] == []


def test_verify_flags_orphan(tmp_path):
    # quarantined file with NO surviving keeper anywhere
    (tmp_path / "_duplicates" / "images").mkdir(parents=True)
    (tmp_path / "_duplicates" / "images" / "p_t1_222.webp").write_bytes(b"LONELY")
    res = core.verify_quarantine(tmp_path)
    assert len(res["orphan"]) == 1


def test_verify_restore_orphans_moves_back(tmp_path):
    (tmp_path / "_duplicates" / "images").mkdir(parents=True)
    (tmp_path / "_duplicates" / "images" / "p_t1_333.webp").write_bytes(b"LONELY")
    res = core.verify_quarantine(tmp_path, restore_orphans=True)
    assert res["restored"] == 1
    assert (tmp_path / "images" / "p_t1_333.webp").exists()


def test_verify_flags_genuine_pixel_difference(tmp_path):
    # same media_id, different bytes AND non-image content (Pillow can't decode ->
    # _same_pixels returns None -> treated as a genuine differ, not auto-safe)
    (tmp_path / "2023-10").mkdir()
    (tmp_path / "_duplicates" / "images").mkdir(parents=True)
    (tmp_path / "2023-10" / "444.webp").write_bytes(b"CONTENT-A")
    (tmp_path / "_duplicates" / "images" / "p_t1_444.webp").write_bytes(b"CONTENT-B-DIFFERENT")
    res = core.verify_quarantine(tmp_path)
    assert len(res["differs"]) == 1


def test_dedup_apply_then_verify_reports_safe(tmp_path):
    """After dedup quarantines, a verify pass should confirm every moved file is
    redundant (the coupling that closes dedup's no-byte-check gap)."""
    _make_class_a_tree(tmp_path)
    db = tmp_path / "catalog.db"
    init_db(db)
    save_catalog(db, [{"media_id": "111", "filename": "a_prompt_t1_111.webp",
                       "batch": "", "task_id": "t1"}])
    core.cmd_dedup(_args(apply=True), tmp_path, db)
    res = core.verify_quarantine(tmp_path)
    assert res["safe"] + res["meta_only"] == res["total"]
    assert res["differs"] == [] and res["orphan"] == []
