"""/api/video-task-params/<task_id> -- "↺ Remix for videos" recipe recovery (SCOPE_2026-08-17 §2).

The video sibling of /api/task-params (tests/test_task_params.py), and it inherits the same
adversarial-review contract, inverted where the two recipes differ:

- membership: only task ids present in the local catalog resolve (finding 4.3), and the row
  must be a VIDEO row -- an IMAGE row is refused (its recipe belongs to the image sibling),
  as is a chat task;
- the three shot shapes map correctly: i2v (i2vPro, no tail), flf (i2vPro + tailMediaId),
  r2v (referenceVideo, N reference ids);
- each source / reference media id is flagged in_lib against the catalog, so the client
  restores only what it actually holds (issue #7 -- upload ids are disclosed, not wired in);
- task_detail_gql returning None (its NETWORK-failure value, not a raise) answers
  {"error": ...}, never a success-shaped empty recipe;
- retries=1 (a prefill, not a lost generation -- finding 4.1);
- an exception answers a host-path-redacted error.

Patch seam mirrors test_task_params.py: _gen_session hands back the moonglade_backup module
itself, so task_detail_gql is patched on `core`, with _make_session stubbed."""
import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, save_catalog
from tests.conftest import login_client

VID_TID = "8000000000000009001"


def _row(**kw):
    r = {f: "" for f in CATALOG_FIELDS}
    r.update(kw)
    return r


def _cli(tmp_path, monkeypatch, rows):
    save_catalog(tmp_path / "catalog.db", rows)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    return login_client(tmp_path)


def _wire_task(monkeypatch, task):
    """Stub task_detail_gql, capturing the retries it was called with."""
    calls = {"retries": None}

    def detail(session, tid, retries=3):
        calls["retries"] = retries
        return task
    monkeypatch.setattr(core, "task_detail_gql", detail)
    return calls


def _video_rows(*extra_media_ids):
    """A video row for VID_TID, plus a catalog row for each media id that must read in_lib."""
    rows = [_row(media_id="v1", filename="clip_v1.mp4", task_id=VID_TID, is_video="1",
                 created_at="2025-01-01T00:00:00")]
    for mid in extra_media_ids:
        rows.append(_row(media_id=mid, filename=mid + ".png",
                         created_at="2025-01-01T00:00:00"))
    return rows


# ---------------------------------------------------------------------------
# the three shot shapes
# ---------------------------------------------------------------------------

def test_i2v_shape(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch, _video_rows("frame_in"))
    _wire_task(monkeypatch, {"parameters": {
        "modelId": "2003969750675682808", "isPrivate": True,
        "i2vPro": {
            "model": "v4.0.1", "mediaId": "frame_in", "mode": "professional",
            "duration": "5", "prompts": "a slow cinematic pan", "negativePrompts": "blurry",
            "usePromptsHelper": True, "generateAudio": True, "audioLanguage": "japanese",
            "cameraMovement": "zoom",
        }}})
    d = cli.get("/api/video-task-params/" + VID_TID).get_json()
    assert "error" not in d
    assert d["kind"] == "i2v"
    assert d["video_model"] == "v4.0.1"
    assert d["duration"] == 5                 # coerced from the "5" string
    assert d["quality"] == "professional"
    assert d["camera"] == "zoom"
    assert d["audio"] is True and d["audio_language"] == "japanese"
    assert d["prompt_helper"] is True
    assert d["negative"] == "blurry"
    assert d["prompt"] == "a slow cinematic pan"
    assert d["is_private"] is True
    assert d["start"] == {"media_id": "frame_in", "in_lib": True}
    assert d["end"] is None
    assert d["image_refs"] == [] and d["video_refs"] == [] and d["audio_refs"] == []


def test_flf_shape_end_frame_membership(tmp_path, monkeypatch):
    # start frame in the library, end frame NOT -- the client discloses the missing end.
    cli = _cli(tmp_path, monkeypatch, _video_rows("start_in"))
    _wire_task(monkeypatch, {"parameters": {
        "i2vPro": {
            "model": "v4.0.1", "mediaId": "start_in", "tailMediaId": "end_gone",
            "mode": "basic", "duration": "10", "prompts": "morph the start into the end",
        }}})
    d = cli.get("/api/video-task-params/" + VID_TID).get_json()
    assert d["kind"] == "flf"
    assert d["quality"] == "basic"
    assert d["duration"] == 10
    assert d["start"] == {"media_id": "start_in", "in_lib": True}
    assert d["end"] == {"media_id": "end_gone", "in_lib": False}


def test_r2v_shape_reference_membership(tmp_path, monkeypatch):
    # two image refs: one we hold, one an upload we don't; the client restores the first
    # and discloses the second (issue #7 -- §2.5).
    cli = _cli(tmp_path, monkeypatch, _video_rows("ref_in"))
    _wire_task(monkeypatch, {"parameters": {
        "modelId": "2003969750675682808",
        "referenceVideo": {
            "model": "v4.0.1", "mode": "professional", "duration": 6,
            "prompt": "the druid from @image1 dances",
            "referenceImageMediaIds": ["ref_in", "ref_upload"],
            "referenceVideoMediaIds": [], "referenceAudioMediaIds": [],
            "generateAudio": False, "audioLanguage": "english",
        }}})
    d = cli.get("/api/video-task-params/" + VID_TID).get_json()
    assert d["kind"] == "r2v"
    assert d["video_model"] == "v4.0.1"
    assert d["duration"] == 6
    assert d["prompt"] == "the druid from @image1 dances"
    assert d["camera"] == "" and d["negative"] == ""      # r2v carries neither
    assert d["image_refs"] == [
        {"media_id": "ref_in", "in_lib": True},
        {"media_id": "ref_upload", "in_lib": False},
    ]
    assert d["video_refs"] == [] and d["audio_refs"] == []


# ---------------------------------------------------------------------------
# refusals -- image + chat, unknown task, unreadable
# ---------------------------------------------------------------------------

def test_image_row_refused(tmp_path, monkeypatch):
    img_tid = "9000000000000000001"
    rows = _video_rows() + [_row(media_id="i1", filename="a_1.png", task_id=img_tid,
                                 created_at="2025-01-01T00:00:00")]
    cli = _cli(tmp_path, monkeypatch, rows)
    _wire_task(monkeypatch, {"parameters": {"i2vPro": {"model": "v4.0.1", "mediaId": "x"}}})
    r = cli.get("/api/video-task-params/" + img_tid)
    assert r.status_code == 400 and "video" in r.get_json()["error"]


def test_chat_task_refused(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch, _video_rows())
    _wire_task(monkeypatch, {"parameters": {"chat": {"mediaId": "m", "modelId": "x"}}})
    r = cli.get("/api/video-task-params/" + VID_TID)
    assert r.status_code == 400 and "video" in r.get_json()["error"]


def test_video_row_with_neither_block_refused(tmp_path, monkeypatch):
    # a video row whose task carries neither i2vPro nor referenceVideo: nothing safe to
    # prefill, so it is refused rather than answered with a hollow success shape.
    cli = _cli(tmp_path, monkeypatch, _video_rows())
    _wire_task(monkeypatch, {"parameters": {"priority": 1000}})
    r = cli.get("/api/video-task-params/" + VID_TID)
    assert r.status_code == 400 and "video" in r.get_json()["error"]


def test_unknown_task_refused(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch, _video_rows())
    _wire_task(monkeypatch, {"parameters": {"i2vPro": {"model": "v4.0.1", "mediaId": "x"}}})
    r = cli.get("/api/video-task-params/12345")
    assert r.status_code == 404 and r.get_json()["error"]


def test_unreadable_task_is_an_error_not_empty(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch, _video_rows())
    _wire_task(monkeypatch, None)              # task_detail_gql None == network failure
    d = cli.get("/api/video-task-params/" + VID_TID).get_json()
    assert d.get("error")                      # NEVER a success-shaped empty recipe
    assert "kind" not in d


def test_retries_is_one_not_the_default_ladder(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch, _video_rows())
    calls = _wire_task(monkeypatch, {"parameters": {"i2vPro": {"model": "v4.0.1", "mediaId": "x"}}})
    cli.get("/api/video-task-params/" + VID_TID)
    assert calls["retries"] == 1


def test_exception_answers_redacted_error(tmp_path, monkeypatch):
    cli = _cli(tmp_path, monkeypatch, _video_rows())

    def boom(session, tid, retries=3):
        raise RuntimeError(r"C:\Users\gwilkins\secret\place blew up")
    monkeypatch.setattr(core, "task_detail_gql", boom)
    r = cli.get("/api/video-task-params/" + VID_TID)
    d = r.get_json()
    assert r.status_code == 200 and d["error"]
    assert "gwilkins" not in d["error"]
