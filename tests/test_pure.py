"""Tests for pure / stateless functions (no network, no filesystem)."""
import pytest

import pixai_gallery_backup as core


# ---------------------------------------------------------------------------
# _format_size
# ---------------------------------------------------------------------------

def test_format_size_bytes():
    assert core._format_size(0) == "0.0 B"
    assert core._format_size(500) == "500.0 B"
    assert core._format_size(1023) == "1023.0 B"


def test_format_size_kilobytes():
    assert core._format_size(1024) == "1.0 KB"
    assert core._format_size(2048) == "2.0 KB"


def test_format_size_megabytes():
    assert core._format_size(1024 ** 2) == "1.0 MB"


def test_format_size_gigabytes():
    assert core._format_size(1024 ** 3) == "1.0 GB"


def test_format_size_terabytes():
    assert core._format_size(1024 ** 4) == "1.0 TB"


# ---------------------------------------------------------------------------
# _progress_line
# ---------------------------------------------------------------------------

def test_progress_line_with_total():
    line = core._progress_line(50, 100)
    assert "50/100" in line
    assert "50.0%" in line
    assert "checked" in line


def test_progress_line_full():
    line = core._progress_line(100, 100)
    assert "100/100" in line
    assert "100.0%" in line


def test_progress_line_no_total():
    line = core._progress_line(42, 0)
    assert "42" in line
    assert "Checking" in line


def test_progress_line_new_suffix():
    line = core._progress_line(50, 100, new=7)
    assert "+7 new" in line


def test_progress_line_no_new_suffix_when_zero():
    line = core._progress_line(50, 100, new=0)
    assert "new" not in line


def test_progress_line_starts_with_cr():
    assert core._progress_line(1, 10).startswith("\r")


# ---------------------------------------------------------------------------
# slug_from_prompt
# ---------------------------------------------------------------------------

def test_slug_basic():
    s = core.slug_from_prompt("a beautiful cat", 60)
    assert s == "a_beautiful_cat"


def test_slug_removes_forbidden_chars():
    s = core.slug_from_prompt('cat: "meow"', 60)
    assert ":" not in s
    assert '"' not in s


def test_slug_truncates():
    s = core.slug_from_prompt("word " * 20, 10)
    assert len(s) <= 10


def test_slug_empty():
    assert core.slug_from_prompt("", 60) == ""

    assert core.slug_from_prompt(None, 60) == ""


# ---------------------------------------------------------------------------
# build_stem_name
# ---------------------------------------------------------------------------

def test_build_stem_name_contains_ids():
    stem = core.build_stem_name("a cat", "task123", "mid456", 60, "_")
    assert "task123" in stem
    assert "mid456" in stem


def test_build_stem_name_media_id_last():
    stem = core.build_stem_name("a cat", "task123", "mid456", 60, "_")
    assert stem.endswith("mid456")


def test_build_stem_name_no_prompt():
    stem = core.build_stem_name("", "task1", "mid1", 60, "_")
    assert "task1" in stem
    assert "mid1" in stem


def test_build_stem_name_sep():
    stem = core.build_stem_name("hello world", "t1", "m1", 60, "-")
    assert "_" not in stem
    assert "-" in stem


# ---------------------------------------------------------------------------
# media_ids_for
# ---------------------------------------------------------------------------

def test_media_ids_for_single():
    node = {"mediaId": "abc123", "batchMediaIds": None}
    assert core.media_ids_for(node) == ["abc123"]


def test_media_ids_for_batch_dedup():
    node = {"mediaId": "abc123", "batchMediaIds": ["abc123", "def456", "ghi789"]}
    assert core.media_ids_for(node) == ["abc123", "def456", "ghi789"]


def test_media_ids_for_empty_node():
    assert core.media_ids_for({}) == []


def test_media_ids_for_batch_only():
    node = {"mediaId": None, "batchMediaIds": ["a", "b"]}
    assert core.media_ids_for(node) == ["a", "b"]


def test_media_ids_for_falsy_batch_entries_skipped():
    node = {"mediaId": "x", "batchMediaIds": ["x", "", None, "y"]}
    result = core.media_ids_for(node)
    assert "" not in result
    assert None not in result
    assert "y" in result


# ---------------------------------------------------------------------------
# extract_meta
# ---------------------------------------------------------------------------

def test_extract_meta_basic():
    node = {
        "id": "task1",
        "createdAt": "2024-01-15T10:00:00Z",
        "promptsPreview": "a beautiful cat",
        "status": "succeeded",
    }
    meta = core.extract_meta(node)
    assert meta["task_id"] == "task1"
    assert meta["created_at"] == "2024-01-15T10:00:00Z"
    assert meta["prompt_preview"] == "a beautiful cat"
    assert meta["status"] == "succeeded"


def test_extract_meta_missing_fields():
    meta = core.extract_meta({})
    assert meta["task_id"] == ""
    assert meta["prompt_preview"] == ""


def test_extract_meta_null_prompt():
    node = {"id": "t", "promptsPreview": None}
    assert core.extract_meta(node)["prompt_preview"] == ""


# ---------------------------------------------------------------------------
# find_connection
# ---------------------------------------------------------------------------

def test_find_connection_nested():
    data = {"user": {"taskSummaries": {"edges": [], "pageInfo": {"hasPreviousPage": False}}}}
    conn = core.find_connection(data)
    assert conn is not None
    assert "edges" in conn
    assert "pageInfo" in conn


def test_find_connection_returns_none_on_empty():
    assert core.find_connection({}) is None
    assert core.find_connection(None) is None


def test_find_connection_returns_none_no_match():
    assert core.find_connection({"a": 1, "b": 2}) is None


def test_find_connection_inside_list():
    data = [{"edges": [], "pageInfo": {}}]
    conn = core.find_connection(data)
    assert conn is not None


# ---------------------------------------------------------------------------
# extract_full_meta
# ---------------------------------------------------------------------------

_SAMPLE_TASK = {
    "parameters": {
        "prompts": "A night elf druid with lavender skin",
        "modelId": "1983308862240288769",
        "extra": {"naturalPrompts": "night elf female druid lavender skin"},
    },
    "outputs": {
        "seed": 2973364003509396,
        "detailParameters": {
            "steps": 4,
            "sampler": "Euler a",
            "cfg_scale": 7,
        },
    },
}


def test_extract_full_meta_all_fields():
    m = core.extract_full_meta(_SAMPLE_TASK)
    assert m["prompt_full"] == "A night elf druid with lavender skin"
    assert m["natural_prompt"] == "night elf female druid lavender skin"
    assert m["seed"] == "2973364003509396"
    assert m["steps"] == "4"
    assert m["sampler"] == "Euler a"
    assert m["cfg_scale"] == "7"
    assert m["model_id"] == "1983308862240288769"


def test_extract_full_meta_none_returns_empty():
    assert core.extract_full_meta(None) == {}


def test_extract_full_meta_negative_and_clip_skip():
    task = {
        "parameters": {"prompts": "cat", "negativePrompts": "bad hands", "modelId": "m"},
        "outputs": {"detailParameters": {"steps": 30, "clipSkip": 2}},
    }
    m = core.extract_full_meta(task)
    assert m["negative_prompt"] == "bad hands"
    assert m["clip_skip"] == "2"


def test_extract_full_meta_no_negative_is_blank():
    # newer "structured prompt" tasks have no separate negative
    m = core.extract_full_meta({"parameters": {"prompts": "cat"}, "outputs": {}})
    assert m["negative_prompt"] == ""
    assert m["clip_skip"] == ""


# ---------------------------------------------------------------------------
# video_outputs (image-to-video task parsing)
# ---------------------------------------------------------------------------

def test_video_outputs_extracts_video_and_poster():
    task = {
        "parameters": {"modelId": "M",
                       "referenceVideo": {"prompt": "night elf dance",
                                          "duration": 10, "model": "v4.0.1"}},
        "outputs": {"mediaId": "THUMB", "detailParameters": {"width": 1248, "height": 716},
                    "videos": [{"seed": 42, "mediaId": "VID1", "thumbnailMediaId": "THUMB"}]},
    }
    outs, shared = core.video_outputs(task)
    assert outs == [{"video_media_id": "VID1", "poster_media_id": "THUMB", "seed": "42"}]
    assert shared["prompt"] == "night elf dance"
    assert shared["duration"] == 10


def test_video_outputs_none_and_empty():
    assert core.video_outputs(None) == ([], {})
    assert core.video_outputs({"outputs": {}, "parameters": {}}) == ([], {"prompt": "", "duration": "", "i2v_model": ""})


def test_extract_full_meta_partial():
    task = {"parameters": {"prompts": "cat"}, "outputs": {}}
    m = core.extract_full_meta(task)
    assert m["prompt_full"] == "cat"
    assert m["seed"] == ""
    assert m["steps"] == ""


# ---------------------------------------------------------------------------
# _merge_full
# ---------------------------------------------------------------------------

def test_merge_full_prefers_fm():
    fm = {"prompt_full": "new", "natural_prompt": "", "seed": "123",
          "steps": "4", "sampler": "Euler a", "cfg_scale": "7",
          "model_id": "m1", "model_name": "Tsubaki.2 v1"}
    kr = {"prompt_full": "old", "seed": "999", "model_name": "OldModel v0"}
    result = core._merge_full(fm, kr)
    assert result["prompt_full"] == "new"
    assert result["seed"] == "123"
    assert result["model_name"] == "Tsubaki.2 v1"


def test_merge_full_falls_back_to_known():
    fm = {}
    kr = {"prompt_full": "stored prompt", "seed": "777", "model_name": "OldModel",
          "natural_prompt": "", "steps": "", "sampler": "", "cfg_scale": "", "model_id": ""}
    result = core._merge_full(fm, kr)
    assert result["prompt_full"] == "stored prompt"
    assert result["seed"] == "777"


def test_merge_full_empty_both():
    result = core._merge_full({}, {})
    for f in core._FULL_META_FIELDS:
        assert result[f] == ""


# ---------------------------------------------------------------------------
# _parallel_map (shared worker-pool helper)
# ---------------------------------------------------------------------------

def test_parallel_map_serial_preserves_order():
    assert list(core._parallel_map([1, 2, 3], lambda x: x * 10, workers=1)) == \
        [(1, 10), (2, 20), (3, 30)]


def test_parallel_map_parallel_covers_all_items():
    got = sorted(core._parallel_map([1, 2, 3, 4, 5], lambda x: x * 10, workers=4))
    assert got == [(1, 10), (2, 20), (3, 30), (4, 40), (5, 50)]


def test_parallel_map_worker_exception_yields_none():
    def boom(x):
        raise ValueError("nope")
    assert list(core._parallel_map([1, 2], boom, workers=3)) == [(1, None), (2, None)]


def test_parallel_map_progress_called_per_item():
    seen = []
    list(core._parallel_map([1, 2, 3], lambda x: x, workers=2,
                            progress=lambda d, t, n: seen.append((d, t))))
    assert len(seen) == 3 and seen[-1][1] == 3 and {d for d, t in seen} == {1, 2, 3}
