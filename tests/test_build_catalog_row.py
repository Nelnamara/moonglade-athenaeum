"""build_catalog_row: the ONE create-time catalog row (issue #19 item 4).

Seven capture paths used to hand-assemble the same row inline, and they drifted -- the
2026-08-15 audit found lineage missing from all of them at once, the video paths dropped
fields the image paths kept, and on 2026-09-03 the duplication cost real data (re-collecting
a generation rebuilt its row from the blank template and wiped artwork_id, rating,
collections, title and published state).

This module is the refactor's proof, in two halves:

  * GOLDEN. `_old_*` below are VERBATIM copies of the six pre-refactor inline builders as
    they stood at c4546f7 (plus the gallery's Loom-bundle one). Each test drives the REAL
    capture function with the download stubbed, reads the row back out of catalog.db, and
    asserts it is field-for-field identical to what the old builder would have produced from
    the same inputs. Driving the real function (rather than comparing two expressions in
    this file) is what binds the CALL SITE, not just the helper.
  * CARRY. The same seven paths, run over a media_id that already carries local curation,
    must leave every locally-owned field standing. Four of them had no carry at all before
    the shared builder gave them one.
"""
import io
import json
import time
import types
import zipfile

import pytest

import moonglade_backup as core
import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, load_catalog, save_catalog

from tests.conftest import login_test_client


# --------------------------------------------------------------------------------------
# The pre-refactor builders, transcribed verbatim (c4546f7). Do not "tidy" these -- their
# whole value is being a frozen copy of what the six call sites used to write.
# --------------------------------------------------------------------------------------
def _old_sync_videos(node, o, path, out, shared, detail, params, task, full_meta):
    full = {f: "" for f in CATALOG_FIELDS}
    full.update({
        "task_id": str(node["id"]),
        "media_id": o["video_media_id"],
        "filename": str(path.relative_to(out)).replace("\\", "/"),
        "prompt_full": shared.get("prompt", ""),
        "prompt_preview": (node.get("promptsPreview") or "")[:100],
        "seed": str(o.get("seed") or ""),
        "created_at": node.get("createdAt", ""),
        "width": str(detail.get("width") or ""),
        "height": str(detail.get("height") or ""),
        "model_id": str(params.get("modelId") or ""),
        "negative_prompt": shared.get("negative_prompt", ""),
        "status": "completed",
        "is_video": "1",
        "poster_media_id": o.get("poster_media_id", ""),
        "paid_credit": core._paid_credit_str(task),
        "video_duration": str(shared.get("duration") or ""),
    })
    full.update({k: full_meta.get(k, "") for k in core._TASK_ROW_FIELDS})
    return full


def _old_import_local(mid, rel, created, stem, is_vid):
    full = {f: "" for f in CATALOG_FIELDS}
    full.update({
        "media_id": mid, "filename": rel, "source": "local",
        "status": "imported", "created_at": created,
        "prompt_preview": stem[:100],
        "is_video": "1" if is_vid else "",
    })
    return full


def _old_generate(task_id, mid, path, out, url, result, prompt, seeds, fm, params,
                  info, pick, model_name, loras):
    full = {f: "" for f in CATALOG_FIELDS}
    full.update({
        "task_id": str(task_id), "media_id": mid,
        "filename": str(path.relative_to(out)).replace("\\", "/"),
        "url": url, "source": "api", "status": "completed",
        "created_at": result.get("createdAt") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prompt_full": prompt,
        "prompt_preview": (prompt or "")[:100],
        "negative_prompt": pick("negative_prompt", "negativePrompts"),
        "seed": seeds.get(mid) or pick("seed", "seed"),
        "steps": fm.get("steps", ""),
        "cfg_scale": fm.get("cfg_scale", ""),
        "model_id": pick("model_id", "modelId"),
        "model_name": model_name,
        "sampler": fm.get("sampler", ""),
        "natural_prompt": fm.get("natural_prompt", ""),
        "clip_skip": fm.get("clip_skip", ""),
        "loras": loras,
        "paid_credit": core._paid_credit_str(result),
        "width": str((info or {}).get("width") or params.get("width") or ""),
        "height": str((info or {}).get("height") or params.get("height") or ""),
    })
    full.update({k: fm.get(k, "") for k in core._TASK_ROW_FIELDS})
    return full


def _old_download_video_task(task_id, o, path, out, url, result, prompt, sent, shared,
                             detail, fm):
    full = {f: "" for f in CATALOG_FIELDS}
    full.update({
        "task_id": str(task_id), "media_id": o["video_media_id"],
        "filename": str(path.relative_to(out)).replace("\\", "/"),
        "url": url, "source": "api", "status": "completed", "is_video": "1",
        "created_at": result.get("createdAt") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prompt_full": prompt, "prompt_preview": (prompt or "")[:100],
        "negative_prompt": sent.get("negativePrompts", ""),
        "seed": str(o.get("seed") or ""),
        "poster_media_id": o.get("poster_media_id", ""),
        "paid_credit": core._paid_credit_str(result),
        "video_duration": str(shared.get("duration") or sent.get("duration") or ""),
        "model_id": str(sent.get("model") or ""),
        "width": str(detail.get("width") or ""),
        "height": str(detail.get("height") or ""),
    })
    full.update({k: fm.get(k, "") for k in core._TASK_ROW_FIELDS})
    return full


def _old_download_image_task(task_id, mid, seed, path, out, url, result, prompt, fm,
                             info, model_name, loras):
    full = {f: "" for f in CATALOG_FIELDS}
    full.update({
        "task_id": str(task_id), "media_id": mid, "seed": seed,
        "filename": str(path.relative_to(out)).replace("\\", "/"),
        "url": url, "source": "api", "status": "completed",
        "created_at": result.get("createdAt") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prompt_full": prompt, "prompt_preview": (prompt or "")[:100],
        "model_id": fm.get("model_id", ""),
        "model_name": model_name,
        "steps": fm.get("steps", ""),
        "sampler": fm.get("sampler", ""),
        "cfg_scale": fm.get("cfg_scale", ""),
        "negative_prompt": fm.get("negative_prompt", ""),
        "natural_prompt": fm.get("natural_prompt", ""),
        "clip_skip": fm.get("clip_skip", ""),
        "loras": loras,
        "paid_credit": core._paid_credit_str(result),
        "width": str((info or {}).get("width") or ""),
        "height": str((info or {}).get("height") or ""),
    })
    full.update({k: fm.get(k, "") for k in core._TASK_ROW_FIELDS})
    return full


def _old_edit_image(task_id, mid, path, out, url, result, prompt_used, seeds, fm,
                    info, model_id_used, model_name):
    full = {f: "" for f in CATALOG_FIELDS}
    full.update({
        "task_id": str(task_id), "media_id": mid, "seed": seeds.get(mid, ""),
        "filename": str(path.relative_to(out)).replace("\\", "/"),
        "url": url, "source": "api", "status": "completed",
        "created_at": result.get("createdAt") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "prompt_full": prompt_used, "prompt_preview": (prompt_used or "")[:100],
        "model_id": model_id_used,
        "model_name": model_name,
        "paid_credit": core._paid_credit_str(result),
        "width": str((info or {}).get("width") or ""),
        "height": str((info or {}).get("height") or ""),
    })
    full.update({k: fm.get(k, "") for k in core._TASK_ROW_FIELDS})
    return full


def _old_loom_bundle(mid, rel, stem, is_vid, created):
    row = {k: "" for k in CATALOG_FIELDS}
    row.update({
        "media_id": mid, "filename": rel,
        "source": "api", "status": "imported",
        "created_at": created,
        "prompt_preview": stem[:100], "is_video": "1" if is_vid else "",
    })
    return row


# --------------------------------------------------------------------------------------
# Shared fixtures: ONE stubbed task/result and ONE extract_full_meta answer, so every site
# is compared on the same inputs and a difference is the builder's, not the fixture's.
# --------------------------------------------------------------------------------------
TASK_ID = "t-golden"
CREATED = "2026-08-01T12:00:00Z"

# Every column extract_full_meta can hand over, all non-blank, so a dropped field shows up
# as a difference instead of hiding behind a shared "".
FM = {
    "prompt_full": "a moonlit elf", "natural_prompt": "an elf, at night",
    "negative_prompt": "blurry", "seed": "424242", "steps": "28", "sampler": "Euler a",
    "cfg_scale": "5.5", "clip_skip": "2", "model_id": "V-MODEL", "model_name": "",
    "loras": "", "width": "1024", "height": "1536",
    "inference_profile": "standard", "quality_tag": "Masterpiece", "prompt_helper": "on",
    "control_nets": '[{"x": 1}]', "lora_parameters": '[{"versionId": "L1", "weight": 0.7}]',
    "priority": "1500", "render_seconds": "12.5", "backend": "pdr",
    "started_at": "S", "ended_at": "E", "updated_at": "U", "retry_count": "1",
    "moderation": "PASS", "video_mode": "professional", "video_model": "v3.0.2",
    "source_media_id": "src-1", "derive_kind": "edit",
}
RESULT = {"createdAt": CREATED, "paidCredit": 42, "outputs": {"mediaId": "m-golden"},
          "parameters": {"modelId": "V-MODEL", "prompts": "a moonlit elf"}}
INFO = {"width": "896", "height": "1152"}
MODEL_NAME = "Tsubaki.2"
LORAS = "Moonlight:0.7"

# The locally-owned columns a re-capture must never blank. Same set the 2026-09-03 bug hit.
LOCAL = {
    "artwork_id": "aw-77", "is_published": "1", "title": "The Nightfallen",
    "rating": "5", "collections": "Favourites, Prints", "art_tags": "elf, moon",
    "aes_score": "7.25", "blurhash": "LEHV6nWB2yk8",
}


class _Args(object):
    name_length = 60
    name_sep = "_"
    out = "."
    token = None
    task_id = TASK_ID
    confirm = False
    workers = 1
    delay = 0.0
    progress = None
    page_size = 250
    poll_timeout = 5


def _seed_local(db, media_id):
    """A row that already carries the user's curation, so the carry has something to lose."""
    row = {f: "" for f in CATALOG_FIELDS}
    row.update({"media_id": media_id, "task_id": TASK_ID, "filename": "images/old.png",
                "created_at": "2026-01-01T00:00:00"})
    row.update(LOCAL)
    save_catalog(db, [row])


def _stub_file(out, name, sub):
    p = out / sub / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"not really media")
    return p


def _row(db, media_id):
    return {r["media_id"]: r for r in load_catalog(db)}[media_id]


def _same(got, want):
    """Compare on CATALOG_FIELDS only -- load_catalog answers the stored columns."""
    diff = {f: (want.get(f, ""), got.get(f, "")) for f in CATALOG_FIELDS
            if (want.get(f, "") or "") != (got.get(f, "") or "")}
    assert not diff, "row drifted from the pre-refactor builder: %s" % diff


# --------------------------------------------------------------------------------------
# IMG -- _download_image_task
# --------------------------------------------------------------------------------------
def _stub_image_task(monkeypatch, out, mid="m-golden", seed="424242"):
    path = _stub_file(out, "old.png", "images")
    monkeypatch.setattr(core, "download", lambda s, url, stem: ("skip", path))
    monkeypatch.setattr(core, "resolve_media", lambda s, m: ("https://x/i.png", dict(INFO)))
    monkeypatch.setattr(core, "_task_image_media", lambda outputs: [(mid, seed)])
    monkeypatch.setattr(core, "extract_full_meta", lambda r: dict(FM))
    monkeypatch.setattr(core, "_fill_preset_defaults", lambda s, fm, r: None)
    monkeypatch.setattr(core, "_resolved_model_name", lambda s, fm, m: MODEL_NAME)
    monkeypatch.setattr(core, "_resolved_loras", lambda s, r: LORAS)
    monkeypatch.setattr(g, "make_thumbnail", lambda *a, **k: None)
    return path


def test_image_task_row_is_identical_to_the_old_builder(tmp_path, monkeypatch):
    path = _stub_image_task(monkeypatch, tmp_path)
    core._download_image_task(object(), dict(RESULT), TASK_ID, tmp_path, _Args(),
                              prompt="a moonlit elf")
    _same(_row(tmp_path / "catalog.db", "m-golden"),
          _old_download_image_task(TASK_ID, "m-golden", "424242", path, tmp_path,
                                   "https://x/i.png", RESULT, "a moonlit elf", FM,
                                   INFO, MODEL_NAME, LORAS))


def test_image_task_carries_local_fields(tmp_path, monkeypatch):
    _seed_local(tmp_path / "catalog.db", "m-golden")
    _stub_image_task(monkeypatch, tmp_path)
    core._download_image_task(object(), dict(RESULT), TASK_ID, tmp_path, _Args(),
                              prompt="a moonlit elf")
    row = _row(tmp_path / "catalog.db", "m-golden")
    assert {f: row[f] for f in LOCAL} == LOCAL


# --------------------------------------------------------------------------------------
# VID -- _download_video_task
# --------------------------------------------------------------------------------------
VOUT = {"video_media_id": "v-golden", "seed": 777, "poster_media_id": "p-1"}
VSHARED = {"prompt": "a moonlit elf", "duration": 5, "negative_prompt": "n/a"}
VDETAIL = {"width": 720, "height": 1280}


def _stub_video_task(monkeypatch, out):
    path = _stub_file(out, "old.mp4", "videos")
    result = dict(RESULT)
    result["outputs"] = {"detailParameters": dict(VDETAIL)}
    monkeypatch.setattr(core, "download", lambda s, url, stem: ("skip", path))
    monkeypatch.setattr(core, "video_outputs", lambda r: ([dict(VOUT)], dict(VSHARED)))
    monkeypatch.setattr(core, "media_file_gql", lambda s, m: {"fileUrl": "https://x/v.mp4"})
    monkeypatch.setattr(core, "extract_full_meta", lambda r: dict(FM))
    monkeypatch.setattr(core, "resolve_media", lambda s, m: ("", {}))
    monkeypatch.setattr(core, "video_poster_thumb", lambda *a, **k: None)
    monkeypatch.setattr(core, "video_faststart", lambda p: None)
    monkeypatch.setattr(g, "make_thumbnail", lambda *a, **k: None)
    return path, result


def test_video_task_row_is_identical_to_the_old_builder(tmp_path, monkeypatch):
    path, result = _stub_video_task(monkeypatch, tmp_path)
    sent = {"model": "i2v-pro", "negativePrompts": "blurry", "duration": 9}
    core._download_video_task(object(), result, TASK_ID, tmp_path, _Args(),
                              {"i2vPro": dict(sent)})
    _same(_row(tmp_path / "catalog.db", "v-golden"),
          _old_download_video_task(TASK_ID, VOUT, path, tmp_path, "https://x/v.mp4",
                                   result, "a moonlit elf", sent, VSHARED, VDETAIL, FM))


def test_video_task_carries_local_fields(tmp_path, monkeypatch):
    _seed_local(tmp_path / "catalog.db", "v-golden")
    _, result = _stub_video_task(monkeypatch, tmp_path)
    core._download_video_task(object(), result, TASK_ID, tmp_path, _Args(), {})
    row = _row(tmp_path / "catalog.db", "v-golden")
    assert {f: row[f] for f in LOCAL} == LOCAL


# --------------------------------------------------------------------------------------
# GEN -- run_generate (recovering an existing task by id: no credits, no submit)
# --------------------------------------------------------------------------------------
GEN_PARAMS = {"modelId": "V-SUBMITTED", "prompts": "a moonlit elf", "width": 512,
              "height": 768, "negativePrompts": "submitted-neg", "seed": 111}


def _stub_generate(monkeypatch, out):
    path = _stub_file(out, "old.png", "images")
    monkeypatch.setattr(core, "_gen_parameters", lambda a: dict(GEN_PARAMS))
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "task_detail_gql", lambda s, t: dict(RESULT))
    monkeypatch.setattr(core, "_maybe_dump_params", lambda a, r: None)
    monkeypatch.setattr(core, "_task_image_media", lambda outputs: [("m-golden", "424242")])
    monkeypatch.setattr(core, "video_outputs", lambda r: ([], {}))
    monkeypatch.setattr(core, "extract_full_meta", lambda r: dict(FM))
    monkeypatch.setattr(core, "_fill_preset_defaults", lambda s, fm, r: None)
    monkeypatch.setattr(core, "_resolved_model_name", lambda s, fm, m: MODEL_NAME)
    monkeypatch.setattr(core, "_resolved_loras", lambda s, r: LORAS)
    monkeypatch.setattr(core, "resolve_media", lambda s, m: ("https://x/i.png", dict(INFO)))
    monkeypatch.setattr(core, "download", lambda s, url, stem: ("skip", path))
    monkeypatch.setattr(g, "make_thumbnail", lambda *a, **k: None)
    return path


def _gen_pick(fm_key, *param_keys):
    """run_generate's own _pick, over the same fm/params the stubs hand it."""
    if FM.get(fm_key):
        return str(FM[fm_key])
    for pk in param_keys:
        if GEN_PARAMS.get(pk):
            return str(GEN_PARAMS[pk])
    return ""


def test_generate_row_is_identical_to_the_old_builder(tmp_path, monkeypatch):
    path = _stub_generate(monkeypatch, tmp_path)
    args = _Args()
    args.out = str(tmp_path)
    core.run_generate(args)
    _same(_row(tmp_path / "catalog.db", "m-golden"),
          _old_generate(TASK_ID, "m-golden", path, tmp_path, "https://x/i.png", RESULT,
                        FM["prompt_full"], {"m-golden": "424242"}, FM, GEN_PARAMS, INFO,
                        _gen_pick, MODEL_NAME, LORAS))


def test_generate_carries_local_fields(tmp_path, monkeypatch):
    """--generate --task-id recovering a task whose media is already published/rated. This
    path had NO carry before the shared builder."""
    _seed_local(tmp_path / "catalog.db", "m-golden")
    _stub_generate(monkeypatch, tmp_path)
    args = _Args()
    args.out = str(tmp_path)
    core.run_generate(args)
    row = _row(tmp_path / "catalog.db", "m-golden")
    assert {f: row[f] for f in LOCAL} == LOCAL


# --------------------------------------------------------------------------------------
# EDIT -- run_edit_image (recovering an existing edit task by id)
# --------------------------------------------------------------------------------------
EDIT_CFG = {"model_id": "EDIT-M", "resolution": "1k", "aspect_ratio": "1:1",
            "quality": "standard", "kaisuuken_id": ""}
EDIT_MODEL_NAME = "Edit Pro"


def _stub_edit(monkeypatch, out):
    path = _stub_file(out, "old.png", "images")
    monkeypatch.setattr(core, "_edit_config_from_args", lambda a: dict(EDIT_CFG))
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "task_detail_gql", lambda s, t: dict(RESULT))
    monkeypatch.setattr(core, "_maybe_dump_params", lambda a, r: None)
    monkeypatch.setattr(core, "_task_image_media", lambda outputs: [("m-golden", "424242")])
    monkeypatch.setattr(core, "extract_full_meta", lambda r: dict(FM))
    monkeypatch.setattr(core, "_fill_preset_defaults", lambda s, fm, r: None)
    monkeypatch.setattr(core, "_edit_model_label", lambda s, fm, m: EDIT_MODEL_NAME)
    monkeypatch.setattr(core, "resolve_media", lambda s, m: ("https://x/i.png", dict(INFO)))
    monkeypatch.setattr(core, "download", lambda s, url, stem: ("skip", path))
    monkeypatch.setattr(g, "make_thumbnail", lambda *a, **k: None)
    return path


def test_edit_row_is_identical_to_the_old_builder(tmp_path, monkeypatch):
    path = _stub_edit(monkeypatch, tmp_path)
    args = _Args()
    args.out = str(tmp_path)
    core.run_edit_image(args)
    # `params` is {} on the recovery path, so chat is {} and the model id comes off fm.
    _same(_row(tmp_path / "catalog.db", "m-golden"),
          _old_edit_image(TASK_ID, "m-golden", path, tmp_path, "https://x/i.png", RESULT,
                          FM["prompt_full"], {"m-golden": "424242"}, FM, INFO,
                          FM["model_id"], EDIT_MODEL_NAME))


def test_edit_carries_local_fields(tmp_path, monkeypatch):
    """Another path that had no carry before the shared builder."""
    _seed_local(tmp_path / "catalog.db", "m-golden")
    _stub_edit(monkeypatch, tmp_path)
    args = _Args()
    args.out = str(tmp_path)
    core.run_edit_image(args)
    row = _row(tmp_path / "catalog.db", "m-golden")
    assert {f: row[f] for f in LOCAL} == LOCAL


# --------------------------------------------------------------------------------------
# SV -- run_sync_videos
# --------------------------------------------------------------------------------------
SV_NODE = {"id": TASK_ID, "i2vProModel": "v3.0.2", "promptsPreview": "a moonlit elf (preview)",
           "createdAt": CREATED}


def _stub_sync_videos(monkeypatch, out):
    path = _stub_file(out, "sv.mp4", "videos")
    task = dict(RESULT)
    task["outputs"] = {"detailParameters": dict(VDETAIL)}
    pages = {"n": 0}

    def _find_connection(_data):
        pages["n"] += 1
        if pages["n"] > 1:
            return None
        return {"edges": [{"node": dict(SV_NODE)}], "pageInfo": {"hasPreviousPage": False}}

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_client_of",
                        lambda s: types.SimpleNamespace(user_id="u1"))
    monkeypatch.setattr(core, "gql", lambda s, v: {})
    monkeypatch.setattr(core, "find_connection", _find_connection)
    monkeypatch.setattr(core, "task_detail_gql", lambda s, t: task)
    monkeypatch.setattr(core, "video_outputs", lambda r: ([dict(VOUT)], dict(VSHARED)))
    monkeypatch.setattr(core, "media_file_gql", lambda s, m: {"fileUrl": "https://x/v.mp4"})
    monkeypatch.setattr(core, "extract_full_meta", lambda r: dict(FM))
    monkeypatch.setattr(core, "download", lambda s, url, stem: ("ok", path))
    monkeypatch.setattr(core, "resolve_media", lambda s, m: ("", {}))
    monkeypatch.setattr(core, "video_poster_thumb", lambda *a, **k: None)
    monkeypatch.setattr(core, "video_faststart", lambda p: None)
    monkeypatch.setattr(g, "make_thumbnail", lambda *a, **k: None)
    return path, task


def test_sync_videos_row_is_identical_to_the_old_builder(tmp_path, monkeypatch):
    path, task = _stub_sync_videos(monkeypatch, tmp_path)
    # --sync-videos runs on an EXISTING backup (_ensure_db refuses an empty catalog), so
    # give it an unrelated row to find. It is not this video, so nothing is carried.
    save_catalog(tmp_path / "catalog.db",
                 [dict({f: "" for f in CATALOG_FIELDS}, media_id="seed-x")])
    args = _Args()
    args.out = str(tmp_path)
    core.run_sync_videos(args)
    _same(_row(tmp_path / "catalog.db", "v-golden"),
          _old_sync_videos(SV_NODE, VOUT, path, tmp_path, VSHARED, VDETAIL,
                           RESULT["parameters"], task, FM))


def test_sync_videos_carries_local_fields(tmp_path, monkeypatch):
    _seed_local(tmp_path / "catalog.db", "v-golden")
    _stub_sync_videos(monkeypatch, tmp_path)
    args = _Args()
    args.out = str(tmp_path)
    core.run_sync_videos(args)
    row = _row(tmp_path / "catalog.db", "v-golden")
    assert {f: row[f] for f in LOCAL} == LOCAL


# --------------------------------------------------------------------------------------
# IMP -- run_import_local
# --------------------------------------------------------------------------------------
def _import_args(tmp_path, src):
    a = _Args()
    a.out = str(tmp_path)
    a.import_local = str(src)
    a.verbose = False
    return a


def test_import_local_row_is_identical_to_the_old_builder(tmp_path, monkeypatch):
    pytest.importorskip("PIL")
    src = tmp_path / "src"
    src.mkdir()
    from PIL import Image
    Image.new("RGB", (8, 8), (90, 70, 160)).save(src / "my_ref.png")
    monkeypatch.setattr(g, "make_thumbnail", lambda *a, **k: None)

    core.run_import_local(_import_args(tmp_path, src))

    rows = [r for r in load_catalog(tmp_path / "catalog.db") if r.get("source") == "local"]
    assert len(rows) == 1
    got = rows[0]
    stored = tmp_path / got["filename"]
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stored.stat().st_mtime))
    _same(got, _old_import_local(got["media_id"], got["filename"], created,
                                 stored.stem, False))


def test_import_local_carries_local_fields(tmp_path, monkeypatch):
    """The import guards already skip a cataloged media_id, so this proves the BUILDER's
    carry rather than the caller's: the row is written through build_catalog_row with a
    `known` map that holds the seeded curation."""
    known = {"m-imp": {f: "" for f in CATALOG_FIELDS}}
    known["m-imp"].update({"media_id": "m-imp"}, **LOCAL)
    row = core.build_catalog_row("m-imp", known=known, filename="imported/x.png",
                                 source="local", status="imported",
                                 created_at="2026-08-01T00:00:00Z",
                                 prompt_preview="x", is_video="")
    assert {f: row[f] for f in LOCAL} == LOCAL
    assert row["source"] == "local" and row["filename"] == "imported/x.png"


# --------------------------------------------------------------------------------------
# LOOM -- the gallery's /api/loom/import-bundle
# --------------------------------------------------------------------------------------
def _bundle(mid="m-loom"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("project.json", json.dumps({"project": {"id": "p1", "shots": []},
                                               "thumbs": {}}))
        z.writestr("media/{}.png".format(mid), b"not really a png")
    buf.seek(0)
    return buf


def test_loom_bundle_row_is_identical_to_the_old_builder(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "make_thumbnail", lambda *a, **k: None)
    monkeypatch.setattr(g, "make_video_thumbnail", lambda *a, **k: None)
    cli = login_test_client(g.create_app(tmp_path))
    r = cli.post("/api/loom/import-bundle",
                 data={"file": (_bundle(), "bundle.zip")},
                 content_type="multipart/form-data")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["media_added"] == 1
    got = _row(tmp_path / "catalog.db", "m-loom")
    # The route's created_at is its own NAIVE local stamp, deliberately unchanged by the
    # refactor (see build_catalog_row / _created_at_utc for why the two sort differently).
    _same(got, _old_loom_bundle("m-loom", "imported/m-loom.png", "m-loom", False,
                                got["created_at"]))
    assert "Z" not in got["created_at"]      # the pre-existing divergence, still there


# --------------------------------------------------------------------------------------
# The helper's own contract
# --------------------------------------------------------------------------------------
def test_every_row_starts_from_the_full_blank_template():
    row = core.build_catalog_row("m1")
    assert sorted(row) == sorted(CATALOG_FIELDS)
    assert all(row[f] == "" for f in CATALOG_FIELDS if f != "media_id")


def test_task_row_fields_are_spread_for_every_caller():
    """issue #18 + lineage, applied in ONE place instead of six -- including for a caller
    that passes no other task field at all."""
    row = core.build_catalog_row("m1", fm=dict(FM))
    for f in core._TASK_ROW_FIELDS:
        assert row[f] == FM[f], f + " was not spread from fm"


def test_prompt_preview_defaults_to_the_prompt_but_can_be_overridden():
    long_prompt = "x" * 200
    assert core.build_catalog_row("m1", prompt_full=long_prompt)["prompt_preview"] == "x" * 100
    assert core.build_catalog_row("m1", prompt_full=long_prompt,
                                 prompt_preview="own")["prompt_preview"] == "own"


def test_created_at_utc_falls_back_to_a_z_stamp():
    assert core._created_at_utc("2026-01-01T00:00:00Z") == "2026-01-01T00:00:00Z"
    assert core._created_at_utc("").endswith("Z")
    assert core._created_at_utc(None).endswith("Z")


def test_a_fresh_media_id_is_not_turned_into_a_no_op():
    """The carry must never make a first capture vanish: an id absent from `known` passes
    through with only what the capture wrote."""
    row = core.build_catalog_row("m-new", known={"other": dict(LOCAL)},
                                 task_id="t1", source="api")
    assert row["task_id"] == "t1" and row["source"] == "api"
    assert all(row[f] == "" for f in LOCAL)
