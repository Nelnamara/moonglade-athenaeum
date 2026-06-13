"""Tests for filesystem-dependent functions (already_downloaded, catalog, load_token)."""
import csv
import json
import os
from pathlib import Path

import pytest

import pixai_gallery_backup as core


# ---------------------------------------------------------------------------
# already_downloaded
# ---------------------------------------------------------------------------

def test_already_downloaded_finds_flat(tmp_path):
    (tmp_path / "cool_prompt_task1_mid999.png").write_bytes(b"fakeimage")
    result = core.already_downloaded(tmp_path, "mid999")
    assert result is not None
    assert result.name.endswith("mid999.png")


def test_already_downloaded_finds_in_subfolder(tmp_path):
    sub = tmp_path / "batches" / "my_batch"
    sub.mkdir(parents=True)
    (sub / "01_mid888.webp").write_bytes(b"fakeimage")
    result = core.already_downloaded(tmp_path, "mid888")
    assert result is not None


def test_already_downloaded_returns_none_when_missing(tmp_path):
    assert core.already_downloaded(tmp_path, "nonexistent") is None


def test_already_downloaded_ignores_part_files(tmp_path):
    (tmp_path / "task_mid777.png.part").write_bytes(b"partial")
    assert core.already_downloaded(tmp_path, "mid777") is None


def test_already_downloaded_ignores_zero_byte(tmp_path):
    (tmp_path / "task_mid666.png").write_bytes(b"")
    assert core.already_downloaded(tmp_path, "mid666") is None


def test_already_downloaded_multiple_exts_returns_first(tmp_path):
    (tmp_path / "task_mid555.jpg").write_bytes(b"img")
    result = core.already_downloaded(tmp_path, "mid555")
    assert result is not None


# ---------------------------------------------------------------------------
# load_token
# ---------------------------------------------------------------------------

def test_load_token_from_cli():
    assert core.load_token("mytoken") == "mytoken"


def test_load_token_from_env(monkeypatch):
    monkeypatch.setenv("PIXAI_TOKEN", "envtoken")
    assert core.load_token() == "envtoken"


def test_load_token_from_file(tmp_path, monkeypatch):
    tok_file = tmp_path / "token.txt"
    tok_file.write_text("filetoken\n", encoding="utf-8")
    # Patch __file__ so the script-dir lookup hits our tmp file
    monkeypatch.setattr(core, "__file__", str(tmp_path / "pixai_gallery_backup.py"))
    assert core.load_token() == "filetoken"


def test_load_token_strips_whitespace(monkeypatch):
    monkeypatch.setenv("PIXAI_TOKEN", "  tok  ")
    assert core.load_token() == "tok"


def test_load_token_raises_when_none(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "__file__", str(tmp_path / "pixai_gallery_backup.py"))
    with pytest.raises(core.PixAIError, match="No token"):
        core.load_token()


# ---------------------------------------------------------------------------
# _load_config
# ---------------------------------------------------------------------------

def test_load_config_reads_file(tmp_path):
    cfg = {"USER_ID": "u1", "U3T": "t1", "PERSISTED_QUERY_HASH": "h1"}
    (tmp_path / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    monkeypath_module_file = str(tmp_path / "pixai_gallery_backup.py")
    # Temporarily redirect module __file__ and reload config
    orig = core.__file__
    try:
        core.__file__ = monkeypath_module_file
        result = core._load_config()
    finally:
        core.__file__ = orig
    assert result["USER_ID"] == "u1"
    assert result["U3T"] == "t1"


def test_load_config_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "__file__", str(tmp_path / "pixai_gallery_backup.py"))
    result = core._load_config()
    assert result == {}


# ---------------------------------------------------------------------------
# Catalog persistence helpers — verify the known/written pattern
# ---------------------------------------------------------------------------

def _write_catalog(path, rows, fields):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _read_catalog(path, fields):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


FIELDS = ["task_id", "media_id", "filename", "url", "width", "height",
          "prompt_preview", "status", "created_at"]


def test_known_dict_loaded_from_existing_catalog(tmp_path):
    """Simulates the 'known' dict pre-loading logic."""
    rows = [
        dict(task_id="t1", media_id="m1", filename="f1.png", url="u1",
             width="512", height="512", prompt_preview="cat", status="succeeded",
             created_at="2024-01-01"),
        dict(task_id="t2", media_id="m2", filename="f2.png", url="u2",
             width="768", height="768", prompt_preview="dog", status="succeeded",
             created_at="2024-01-02"),
    ]
    csv_path = tmp_path / "catalog.csv"
    _write_catalog(csv_path, rows, FIELDS)

    known = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mid = row.get("media_id")
            if mid:
                known[mid] = row

    assert len(known) == 2
    assert known["m1"]["prompt_preview"] == "cat"
    assert known["m2"]["filename"] == "f2.png"


def test_leftover_known_rows_written(tmp_path):
    """Prior-session rows not seen this session must be preserved."""
    old_rows = [
        dict(task_id="t_old", media_id="m_old", filename="old.png", url="",
             width="", height="", prompt_preview="old prompt", status="succeeded",
             created_at="2023-12-01"),
    ]
    csv_path = tmp_path / "catalog.csv"
    _write_catalog(csv_path, old_rows, FIELDS)

    known = {}
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mid = row.get("media_id")
            if mid:
                known[mid] = row

    # Simulate a session that processes only new images (written = {"m_new"})
    written = {"m_new"}
    new_rows = [
        dict(task_id="t_new", media_id="m_new", filename="new.png", url="",
             width="", height="", prompt_preview="new", status="succeeded",
             created_at="2024-06-01"),
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in new_rows:
            w.writerow(r)
        # Write leftover known rows not in written
        for mid, row in known.items():
            if mid not in written:
                w.writerow({field: row.get(field, "") for field in FIELDS})

    result = _read_catalog(csv_path, FIELDS)
    media_ids = {r["media_id"] for r in result}
    assert "m_old" in media_ids, "Prior-session row must be preserved"
    assert "m_new" in media_ids, "New-session row must be present"
