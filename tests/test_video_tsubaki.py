"""The Tsubaki video engines and the video parity fixes (SCOPE_2026-09-26 lane V).

Every rule here is pinned to the 2026-09-26 probe (PROBE_2026-09-26_site.md V01-V09) and the
owner's own tasks -- prompts are never copied, only placeholders. No network: builders are
pure, the gallery routes run against the `pixai` fake with the spend legs stubbed, and every
length lookup reads a temp library with `duration` stubbed (no ffprobe needed).
"""
import math
import sqlite3
from types import SimpleNamespace

import pytest

import moonglade_backup as core
import moonglade_gallery as g
from moonglade_gallery import CATALOG_FIELDS, save_catalog, load_catalog

TBKV = ("tbkv1.0", "tbkv1.0.1")
TBKV_IDS = {"tbkv1.0": "2042030623542642408", "tbkv1.0.1": "2054378086834851904"}


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


# =============================================================================
# V1 -- the roster
# =============================================================================
def test_both_tsubaki_engines_are_in_the_roster_with_their_wire_ids():
    for name, vid in TBKV_IDS.items():
        assert core.video_model_id(name) == vid
    assert core.VIDEO_MODELS["tbkv1.0.1"]["label"] == "Tsubaki Video"
    assert core.VIDEO_MODELS["tbkv1.0"]["label"] == "Tsubaki Video Flash"
    assert core.DEFAULT_VIDEO_MODEL == "v4.0.1", "the app's default engine stays v4.0.1"


def test_gallery_repair_table_matches_the_roster():
    """The catalog repair keeps its own name->id copy (the gallery cannot import the backup
    module at load time). It must be exactly VIDEO_MODELS' engines that publish an id."""
    want = {n: m["model_id"] for n, m in core.VIDEO_MODELS.items() if m["model_id"]}
    assert g._VIDEO_NAME_TO_ID == want


# =============================================================================
# V2 -- never another model's id
# =============================================================================
@pytest.mark.parametrize("model", TBKV + ("v4.0", "v3.2"))
def test_reference_path_sends_the_engines_own_id(model):
    p = core.build_shot_video_params("R2V", "@image1", image_ids=["1"], model=model)
    assert p["modelId"] == core.video_model_id(model)


def test_the_default_engine_is_byte_identical():
    p = core.build_shot_video_params("R2V", "@image1", image_ids=["1"], model="v4.0.1")
    assert p["modelId"] == core.REFVIDEO_MODEL_ID == "2003969750675682808"


def test_an_engine_with_no_id_omits_the_key_on_both_paths():
    r = core.build_shot_video_params("R2V", "@image1", image_ids=["1"], model="v9.9-new")
    i = core.build_shot_video_params("I2V", "x", image_ids=["1"], model="v9.9-new")
    assert "modelId" not in r and "modelId" not in i


@pytest.mark.parametrize("model", TBKV)
def test_tbkv_i2v_goes_out_in_the_sites_name_only_shape(model):
    """No tbkv i2vPro task exists yet and the site sends the name only, so the unobserved
    top-level modelId stays at today's behaviour -- omitted -- on both i2vPro shots, even when
    a caller passes one (review V-R7). The reference path still sends tbkv's own id (V2)."""
    for shot, imgs in (("I2V", ["1"]), ("FLF", ["1", "2"])):
        assert "modelId" not in core.build_shot_video_params(shot, "x", image_ids=imgs,
                                                              model=model)
    assert "modelId" not in core.build_video_parameters("x", "1", model=model,
                                                        model_id=TBKV_IDS[model])
    assert core.build_shot_video_params("R2V", "@image1", image_ids=["1"],
                                        model=model)["modelId"] == TBKV_IDS[model]
    # the existing engines keep the id their card match needs
    assert core.build_shot_video_params("I2V", "x", image_ids=["1"],
                                        model="v4.0.1")["modelId"] == "2003969750675682808"


def test_cli_reference_video_preview_sends_the_chosen_engines_id(tmp_path, capsys):
    core.run_reference_video(_refvid_args(tmp_path, video_model="v4.0"))
    out = capsys.readouterr().out
    assert '"modelId": "2003968021137101826"' in out
    assert core.REFVIDEO_MODEL_ID not in out


# =============================================================================
# V3 -- durations and audio
# =============================================================================
@pytest.mark.parametrize("model", TBKV)
def test_tbkv_renders_15s_and_carries_audio_on_both_paths(model):
    i = core.build_shot_video_params("I2V", "x", image_ids=["1"], model=model, duration=15,
                                     generate_audio=True, audio_language="english")["i2vPro"]
    assert i["duration"] == "15" and i["generateAudio"] is True and i["audioLanguage"] == "english"
    r = core.build_shot_video_params("R2V", "@image1", image_ids=["1"], model=model,
                                     duration=15, generate_audio=True,
                                     audio_language="english")["referenceVideo"]
    assert r["duration"] == 15 and r["generateAudio"] is True and r["audioLanguage"] == "english"


@pytest.mark.parametrize("model", TBKV)
def test_six_seconds_snaps_to_five_on_tbkv_only(model):
    assert core._snap_video_duration(6, model) == 5
    assert core.build_shot_video_params("I2V", "x", image_ids=["1"], model=model,
                                         duration=6)["i2vPro"]["duration"] == "5"
    assert core.build_shot_video_params("R2V", "@image1", image_ids=["1"], model=model,
                                         duration=6)["referenceVideo"]["duration"] == 5
    a = SimpleNamespace(prompt="p", image="55", tail="", duration=6, model="",
                        video_model=model, vmode="basic", audio=False,
                        audio_language="english", negative="", video_prompt_helper=False,
                        params_json="")
    assert core._gen_video_parameters(a)["i2vPro"]["duration"] == "5"


def test_six_seconds_is_unchanged_on_the_existing_engines():
    """The 6 s stop of the existing engines is NOT touched by this branch (pinned by
    test_video_gen.py and test_doc_truth_residuals.py too)."""
    for model in ("v4.0.1", "v4.0", "v3.2", "v3.0.2"):
        assert core._snap_video_duration(6, model) == 6, model
    assert core.build_shot_video_params("I2V", "x", image_ids=["1"], model="v4.0.1",
                                         duration=6)["i2vPro"]["duration"] == "6"
    assert core.VIDEO_DURATIONS == (5, 6, 10, 15)
    assert core.video_model_durations("v4.0.1") == core.VIDEO_DURATIONS
    assert core.video_model_durations("tbkv1.0.1") == (5, 10, 15)


def test_cli_reference_video_preview_snaps_six_to_five_on_tbkv(tmp_path, capsys):
    core.run_reference_video(_refvid_args(tmp_path, video_model="tbkv1.0.1", duration=6))
    assert '"duration": 5,' in capsys.readouterr().out


def test_build_request_says_when_the_engine_snaps_the_length():
    """A length the engine does not take is snapped AND reported (review f-V-F5): the drawer
    snaps on the client first, so this is the receipt for a Remix-built or hand-rolled
    payload. A length the engine takes says nothing, and v4.0.1 keeps its 6 s stop."""
    def req(model, d, shot="I2V"):
        return core.build_request({"mode": shot, "images": ["1"], "prompt": "x",
                                   "video_model": model, "duration": d}, mode="video")
    r = req("tbkv1.0.1", 6)
    assert r.parameters["i2vPro"]["duration"] == "5"
    assert r.adjusted == [{"field": "duration", "asked": 6, "used": 5,
                           "why": "this engine takes 5/10/15 s"}]
    r = req("tbkv1.0", "6", shot="R2V")
    assert r.parameters["referenceVideo"]["duration"] == 5
    assert [(e["field"], e["used"]) for e in r.adjusted] == [("duration", 5)]
    (e,) = req("v3.2", 15).adjusted
    assert (e["used"], e["why"]) == (10, "this engine takes 5/6/10 s")
    for model, d in (("tbkv1.0.1", 10), ("tbkv1.0.1", 15), ("v4.0.1", 6), ("v4.0.1", "15")):
        assert req(model, d).adjusted == [], (model, d)
    assert core.build_request({"mode": "I2V", "images": ["1"], "prompt": "x"},
                              mode="video").adjusted == []          # no duration: the 5 default


# =============================================================================
# V4 -- ratio on tbkv reference videos
# =============================================================================
def _rv(**kw):
    base = dict(image_media_ids=["1"], model="tbkv1.0.1")
    base.update(kw)
    return core.build_reference_video_parameters("@image1", **base)["referenceVideo"]


def test_ratio_is_sent_for_tbkv_on_the_reference_path():
    assert _rv(ratio="16:9")["ratio"] == "16:9"
    assert _rv(model="tbkv1.0", ratio="3:2")["ratio"] == "3:2"


def test_ratio_is_omitted_when_empty_or_adaptive():
    assert "ratio" not in _rv(ratio="")
    assert "ratio" not in _rv(ratio="adaptive")
    assert "ratio" not in _rv()


def test_ratio_is_never_sent_to_a_non_tbkv_engine():
    assert "ratio" not in _rv(model="v4.0.1", ratio="16:9")


def test_an_unknown_ratio_is_refused_at_build_time():
    with pytest.raises(core.PixAIError):
        _rv(ratio="5:4")


def test_the_ratio_set_is_the_sites_nine():
    assert core.VIDEO_RATIOS == ("adaptive", "1:1", "2:3", "3:2", "3:4", "4:3",
                                 "9:16", "16:9", "21:9")


def test_video_ratio_flag_reaches_the_cli_preview(monkeypatch, tmp_path, capsys):
    captured = {}
    # A scoped context, never monkeypatch.undo(): undo would also lift conftest's autouse
    # network blocks for the rest of this test.
    with monkeypatch.context() as m:
        m.setattr(core, "run_reference_video", lambda a: captured.setdefault("args", a))
        m.setattr("sys.argv", ["prog", "--reference-video", "--ref-image", "1",
                               "--video-model", "tbkv1.0.1", "--video-ratio", "21:9",
                               "--out", str(tmp_path)])
        core.main()
    assert captured["args"].video_ratio == "21:9"
    core.run_reference_video(_refvid_args(tmp_path, video_model="tbkv1.0.1", video_ratio="21:9"))
    assert '"ratio": "21:9"' in capsys.readouterr().out


def test_video_ratio_flag_refuses_a_value_pixai_does_not_take(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["prog", "--reference-video", "--ref-image", "1",
                                     "--video-ratio", "5:4", "--out", str(tmp_path)])
    with pytest.raises(SystemExit):
        core.main()


def test_video_ratio_on_a_non_tbkv_engine_says_it_is_not_sent(tmp_path, capsys):
    core.run_reference_video(_refvid_args(tmp_path, video_model="v4.0.1", video_ratio="16:9"))
    out = capsys.readouterr().out
    assert '"ratio"' not in out and "only sent to the Tsubaki video engines" in out


# =============================================================================
# V5 -- input video lengths
# =============================================================================
def test_input_video_durations_keep_order_and_are_all_or_nothing():
    lens = {"9": 10.04166698455811, "8": 3.5}
    assert core.input_video_durations(["9", "8"], lens.get) == ([10.04166698455811, 3.5], False)
    assert core.input_video_durations(["8", "9"], lens.get) == ([3.5, 10.04166698455811], False)
    # one unknown -> the whole list goes back to [], never a partial list
    assert core.input_video_durations(["9", "7"], lens.get) == ([], True)
    # zero / negative is not a length
    assert core.input_video_durations(["9"], {"9": 0}.get) == ([], True)
    # no video refs -> nothing to say
    assert core.input_video_durations([], lens.get) == ([], False)
    # no lookup at all -> today's list, flagged
    assert core.input_video_durations(["9"], None) == ([], True)


def test_build_request_fills_input_lengths_through_the_resolver():
    lens = {"9": 10.04166698455811, "8": 21.5}
    rs = core.RequestResolver(video_duration=lens.get)
    req = core.build_request({"mode": "R2V", "images": [], "video_refs": ["9", "8"],
                              "prompt": "@video1 @video2", "duration": 5},
                             mode="video", resolve=rs)
    rv = req.parameters["referenceVideo"]
    assert rv["referenceVideoMediaIds"] == ["9", "8"]
    assert rv["inputVideoDurations"] == [10.04166698455811, 21.5]
    assert req.adjusted == []


def test_an_unknown_length_sends_the_empty_list_and_a_receipt():
    rs = core.RequestResolver(video_duration={"9": 10.0}.get)
    req = core.build_request({"mode": "R2V", "video_refs": ["9", "8"], "prompt": "x"},
                             mode="video", resolve=rs)
    assert req.parameters["referenceVideo"]["inputVideoDurations"] == []
    (entry,) = req.adjusted
    assert entry["field"] == "inputVideoDurations" and entry["used"] == []
    assert entry["why"] == core.INPUT_VIDEO_UNKNOWN_WHY
    # never described as the higher (or the honest) price: it can be either
    assert "higher" not in entry["why"] and "honest" not in entry["why"]


def test_an_i2v_shot_never_reads_or_reports_input_lengths():
    def boom(mid):
        raise AssertionError("an i2vPro shot has no referenceVideo to fill")
    req = core.build_request({"mode": "I2V", "images": ["1"], "video_refs": ["9"], "prompt": "x"},
                             mode="video", resolve=core.RequestResolver(video_duration=boom))
    assert "i2vPro" in req.parameters and req.adjusted == []


def _site_billed_input_seconds(durations, n_video_refs):
    """The site's pricer (Pricing-CLORo0_g.js): a list shorter than the video refs is a flat
    15 s in total, otherwise the sum of each entry's floor."""
    if n_video_refs > len(durations):
        return 15
    return sum(math.floor(v) for v in durations[:n_video_refs])


def _site_price_task(session, params):
    """A price_task stub with the site's reference-video formula (4,200 a second, output plus
    billed input -- 105,000 for a 15 s job over one 10 s clip, 126,000 over [])."""
    rv = params["referenceVideo"]
    return 4200 * (int(rv["duration"]) + _site_billed_input_seconds(
        rv.get("inputVideoDurations") or [], len(rv.get("referenceVideoMediaIds") or [])))


def test_a_true_length_can_raise_the_quote_above_the_empty_list_and_can_lower_it(
        tmp_path, monkeypatch, pixai):
    """Why the receipt never calls [] the higher price, driven through the APP: /api/price
    sends a catalogued clip's measured length unclamped (20.5 s stays 20.5, not 15), so a long
    clip quotes ABOVE the flat 15 s that [] gets, and a short one (the live 126,000 vs 105,000
    case) quotes below it. price_task is stubbed with the site's formula; nothing else is."""
    from tests.conftest import login_test_client
    long_vid, short_vid, unknown_vid = ("766390091666197258", "766390091666197259",
                                        "766390091666197260")
    monkeypatch.setattr(core, "duration",
                        lambda p, **k: 20.5 if long_vid in str(p) else 10.04166698455811)
    save_catalog(tmp_path / "catalog.db", [_video_file(tmp_path, long_vid),
                                           _video_file(tmp_path, short_vid)])
    sent_lengths = {}

    def _price(session, params):
        rv = params["referenceVideo"]
        sent_lengths[rv["referenceVideoMediaIds"][0]] = list(rv["inputVideoDurations"])
        return _site_price_task(session, params)
    monkeypatch.setattr(core, "price_task", _price)
    monkeypatch.setattr(core, "match_kaisuuken", lambda *a, **k: None)
    cli = login_test_client(g.create_app(tmp_path))

    def quote(vid):
        d = cli.post("/api/price", json={"mode": "R2V", "images": [], "video_refs": [vid],
                                         "prompt": "@video1", "duration": 15,
                                         "video_model": "v4.0.1"}).get_json()
        assert d["cost"] is not None, d
        return d["cost"]
    long_cost, short_cost, unknown_cost = quote(long_vid), quote(short_vid), quote(unknown_vid)
    assert sent_lengths[long_vid] == [20.5], "sent as measured, never clamped to 15"
    assert sent_lengths[short_vid] == [10.04166698455811]
    assert sent_lengths[unknown_vid] == []
    assert long_cost > unknown_cost > short_cost
    assert (short_cost, unknown_cost) == (105000, 126000)


def _video_file(out, mid, secs_row=""):
    (out / "videos").mkdir(parents=True, exist_ok=True)
    f = out / "videos" / ("clip_%s.mp4" % mid)
    f.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32)
    return _row(media_id=mid, filename="videos/" + f.name, is_video="1",
                video_duration=secs_row, created_at="2026-09-16T00:00:00Z")


def test_lookup_measures_the_local_file_first_then_the_catalog_then_none(tmp_path, monkeypatch):
    measured = []
    monkeypatch.setattr(core, "duration",
                        lambda p, **k: measured.append(p) or 10.04166698455811)
    rows = [_video_file(tmp_path, "700000000000000001", secs_row="10"),
            _row(media_id="700000000000000002", is_video="1", video_duration="5",
                 filename="videos/missing_700000000000000002.mp4")]
    save_catalog(tmp_path / "catalog.db", rows)
    look = core.make_video_duration_lookup(tmp_path)
    assert look("700000000000000001") == 10.04166698455811          # the file, unrounded
    assert look("700000000000000002") == 5.0                        # no file -> catalog
    assert look("700000000000000003") is None                       # neither
    n = len(measured)
    assert look("700000000000000001") == 10.04166698455811
    assert len(measured) == n, "a second read of the same id is the cached answer"


def test_price_and_loom_submit_send_byte_identical_reference_blocks(tmp_path, monkeypatch, pixai):
    """The badge (/api/price) and the Video drawer's / Loom's submit (/api/loom/generate) read
    the SAME cached length lookup, so the referenceVideo they build is one shape."""
    from tests.conftest import login_test_client
    monkeypatch.setattr(core, "duration", lambda p, **k: 10.04166698455811)
    vid = "766390091666197254"
    save_catalog(tmp_path / "catalog.db", [_video_file(tmp_path, vid)])
    priced, sent = {}, {}
    monkeypatch.setattr(core, "price_task", lambda s, params: priced.update(params) or 105000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "submit_generation",
                        lambda s, params: sent.update(params) or "task-rv")
    cli = login_test_client(g.create_app(tmp_path))
    body = {"mode": "R2V", "images": [], "video_refs": [vid], "prompt": "@video1",
            "duration": 15, "video_model": "v4.0.1", "quality": "professional",
            "audio": True, "audio_language": "english"}
    d = cli.post("/api/price", json=body).get_json()
    assert d["cost"] == 105000, d
    r = cli.post("/api/loom/generate", json=body)
    assert r.get_json().get("task_id") == "task-rv", r.get_data(as_text=True)
    assert priced["referenceVideo"]["inputVideoDurations"] == [10.04166698455811]
    assert sent["referenceVideo"] == priced["referenceVideo"]


def test_a_missing_local_file_with_no_catalog_length_prices_the_empty_list(tmp_path,
                                                                           monkeypatch, pixai):
    from tests.conftest import login_test_client
    monkeypatch.setattr(core, "duration", lambda p, **k: pytest.fail("no file to measure"))
    vid = "766390091666197255"
    save_catalog(tmp_path / "catalog.db", [_row(media_id=vid, is_video="1",
                                                filename="videos/gone_%s.mp4" % vid)])
    priced = {}
    monkeypatch.setattr(core, "price_task", lambda s, params: priced.update(params) or 126000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda *a, **k: None)
    cli = login_test_client(g.create_app(tmp_path))
    d = cli.post("/api/price", json={"mode": "R2V", "video_refs": [vid], "prompt": "@video1",
                                     "duration": 15}).get_json()
    assert d["cost"] == 126000
    assert priced["referenceVideo"]["inputVideoDurations"] == []


def test_cli_reference_video_measures_a_catalog_ref_against_out(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(core, "duration", lambda p, **k: 12.25)
    vid = "766390091666197256"
    save_catalog(tmp_path / "catalog.db", [_video_file(tmp_path, vid)])
    core.run_reference_video(_refvid_args(tmp_path, ref_image=None, ref_video=[vid]))
    out = capsys.readouterr().out
    assert '"inputVideoDurations": [\n        12.25\n      ]' in out


def test_cli_reference_video_says_when_a_length_is_unknown(tmp_path, monkeypatch, capsys):
    core.run_reference_video(_refvid_args(tmp_path, ref_image=None,
                                          ref_video=["766390091666197257"]))
    out = capsys.readouterr().out
    assert '"inputVideoDurations": []' in out and core.INPUT_VIDEO_UNKNOWN_WHY in out


# =============================================================================
# V1 caps / V6 per-model fields
# =============================================================================
@pytest.mark.parametrize("model", TBKV)
def test_tbkv_i2v_block_carries_only_the_sites_fields(model):
    p = core.build_shot_video_params("FLF", "x", image_ids=["1", "2"], model=model,
                                     negative="blurry", camera_movement="zoom",
                                     generate_audio=True, use_prompt_helper=True)
    assert set(p["i2vPro"]) == {"model", "mediaId", "usePromptsHelper", "prompts", "mode",
                                "duration", "tailMediaId", "generateAudio", "audioLanguage"}


def test_negative_and_camera_still_reach_the_existing_engines():
    i = core.build_shot_video_params("I2V", "x", image_ids=["1"], model="v4.0.1",
                                     negative="blurry", camera_movement="zoom")["i2vPro"]
    assert i["negativePrompts"] == "blurry" and i["cameraMovement"] == "zoom"


def test_build_request_says_what_tbkv_did_not_take():
    req = core.build_request({"mode": "I2V", "images": ["1"], "prompt": "x",
                              "video_model": "tbkv1.0.1", "negative": "blurry",
                              "camera_movement": "pan"}, mode="video")
    assert {e["field"] for e in req.adjusted} == {"negativePrompts", "cameraMovement"}
    assert all(e["used"] is None for e in req.adjusted)
    assert "negativePrompts" not in req.parameters["i2vPro"]
    # an "unset" camera and an empty negative are nothing to report
    quiet = core.build_request({"mode": "I2V", "images": ["1"], "prompt": "x",
                                "video_model": "tbkv1.0.1", "camera_movement": "unset"},
                               mode="video")
    assert quiet.adjusted == []


def test_cli_generate_video_says_what_tbkv_does_not_send(tmp_path, capsys):
    """The CLI i2v road's receipts (review f-V-F5 / V-R4): a negative, a camera move and a
    --video-ratio that --generate-video drops are named under the preview, never silent."""
    core.run_generate_video(_i2v_args(tmp_path, video_model="tbkv1.0.1", negative="blurry",
                                      camera_movement="pan", video_ratio="16:9"))
    out = capsys.readouterr().out
    assert "note: negative prompt not used by Tsubaki Video (not sent)." in out
    assert "note: camera not used by Tsubaki Video (not sent)." in out
    assert "note: --video-ratio applies to --reference-video only (not sent)." in out
    assert '"negativePrompts"' not in out and '"cameraMovement"' not in out


def test_cli_generate_video_prints_no_note_where_everything_is_sent(tmp_path, capsys):
    core.run_generate_video(_i2v_args(tmp_path, video_model="v4.0.1", negative="blurry",
                                      camera_movement="pan"))
    out = capsys.readouterr().out
    assert "note: " not in out
    assert '"negativePrompts": "blurry"' in out and '"cameraMovement": "pan"' in out


def test_cli_generate_video_names_the_drops_before_a_confirmed_submit(tmp_path, monkeypatch,
                                                                     capsys):
    """The --confirm road prints the same receipts before it submits (the submit is stubbed
    to stop right there: nothing reaches PixAI)."""
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_check_read_only", lambda *a, **k: None)

    class _Stop(Exception):
        pass

    def _no_submit(*a, **k):
        raise _Stop()
    monkeypatch.setattr(core, "_apply_kaisuuken", _no_submit)
    with pytest.raises(_Stop):
        core.run_generate_video(_i2v_args(tmp_path, video_model="tbkv1.0", negative="blurry",
                                          confirm=True))
    assert "note: negative prompt not used by Tsubaki Video Flash (not sent)." in \
        capsys.readouterr().out


@pytest.mark.parametrize("model", TBKV)
def test_video_references_are_refused_on_tbkv(model):
    with pytest.raises(core.PixAIError, match="takes no video references"):
        core.build_shot_video_params("R2V", "@image1 @video1", image_ids=["1"],
                                     video_ids=["9"], model=model)
    # images + audio are fine
    p = core.build_shot_video_params("R2V", "@image1 @audio1", image_ids=["1"],
                                     audio_ids=["7"], model=model)
    assert p["referenceVideo"]["referenceAudioMediaIds"] == ["7"]


def test_the_badge_shows_the_video_ref_refusal_as_its_note(tmp_path, monkeypatch, pixai):
    from tests.conftest import login_test_client
    monkeypatch.setattr(core, "price_task", lambda *a: pytest.fail("a refusal is not priced"))
    save_catalog(tmp_path / "catalog.db", [_row(media_id="1", filename="a_1.png")])
    cli = login_test_client(g.create_app(tmp_path))
    d = cli.post("/api/price", json={"mode": "R2V", "images": ["1"], "video_refs": ["9"],
                                     "video_model": "tbkv1.0.1", "prompt": "x"}).get_json()
    assert d["cost"] is None and "no video references" in d["note"]


def test_cli_refuses_video_refs_on_tbkv_before_any_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "upload_media",
                        lambda *a, **k: pytest.fail("refused before any upload"))
    with pytest.raises(core.PixAIError, match="takes no video references"):
        core.run_reference_video(_refvid_args(tmp_path, video_model="tbkv1.0.1",
                                              ref_video=["9"], confirm=True))


# =============================================================================
# V7 -- the catalog
# =============================================================================
def _vtask(block, model_id=None):
    params = {"priority": 1000, "channel": "private", "isPrivate": True}
    params.update(block)
    if model_id:
        params["modelId"] = model_id
    return {"id": "T-v", "createdAt": "2026-09-24T00:00:00Z", "paidCredit": 35700,
            "parameters": params,
            "outputs": {"videos": [{"mediaId": "780000000000000001", "seed": "1"}]}}


_RV_TBKV = {"referenceVideo": {"mode": "professional", "model": "tbkv1.0", "ratio": "3:2",
                               "prompt": "<redacted>", "duration": 15, "generateAudio": True,
                               "audioLanguage": "english", "inputVideoDurations": [],
                               "referenceAudioMediaIds": [],
                               "referenceImageMediaIds": ["769016725775324808"],
                               "referenceVideoMediaIds": []}}


def test_extract_full_meta_reads_the_reference_video_block():
    fm = core.extract_full_meta(_vtask(_RV_TBKV, TBKV_IDS["tbkv1.0"]))
    assert fm["video_model"] == "tbkv1.0" and fm["video_mode"] == "professional"
    assert fm["model_id"] == TBKV_IDS["tbkv1.0"]


def _collect(tmp_path, monkeypatch, task, names=None):
    from pathlib import Path
    monkeypatch.setattr(core, "media_file_gql", lambda s, m: {"fileUrl": "https://x/v.mp4"})

    def _dl(session, url, stem, **kw):
        p = Path(str(stem) + ".mp4")
        p.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        return "ok", p
    monkeypatch.setattr(core, "download", _dl)
    monkeypatch.setattr(core, "video_poster_thumb", lambda *a, **k: None)
    monkeypatch.setattr(core, "video_faststart", lambda p: None)
    looked = []
    monkeypatch.setattr(core, "model_name_gql",
                        lambda s, mid, **k: looked.append(mid) or (names or {}).get(mid, mid))
    core._download_video_task(object(), task, "T-v", tmp_path,
                              SimpleNamespace(name_length=60), task["parameters"])
    return {r["media_id"]: r for r in load_catalog(tmp_path / "catalog.db")}, looked


def test_a_collected_reference_video_row_stores_the_numeric_id_and_the_title(tmp_path,
                                                                             monkeypatch):
    rows, looked = _collect(tmp_path, monkeypatch, _vtask(_RV_TBKV, TBKV_IDS["tbkv1.0"]),
                            names={TBKV_IDS["tbkv1.0"]: "Tsubaki Video Flash v1.0"})
    row = rows["780000000000000001"]
    assert row["model_id"] == TBKV_IDS["tbkv1.0"]
    assert row["model_name"] == "Tsubaki Video Flash v1.0"
    assert row["video_model"] == "tbkv1.0" and row["video_mode"] == "professional"
    assert looked == [TBKV_IDS["tbkv1.0"]]


def test_a_failed_title_lookup_falls_back_to_the_roster_label(tmp_path, monkeypatch):
    rows, _ = _collect(tmp_path, monkeypatch, _vtask(_RV_TBKV, TBKV_IDS["tbkv1.0"]))
    assert rows["780000000000000001"]["model_name"] == "Tsubaki Video Flash"


def test_an_i2v_row_gets_the_same_treatment(tmp_path, monkeypatch):
    i2v = {"i2vPro": {"model": "v4.0.1", "mode": "professional", "mediaId": "767513920025866554",
                      "prompts": "<redacted>", "duration": "15"}}
    rows, _ = _collect(tmp_path, monkeypatch, _vtask(i2v, "2003969750675682808"),
                       names={"2003969750675682808": "V4.0 Lite Preview v4.0.1"})
    row = rows["780000000000000001"]
    assert row["model_id"] == "2003969750675682808"
    assert row["model_name"] == "V4.0 Lite Preview v4.0.1"
    assert row["video_model"] == "v4.0.1"


def test_a_task_with_no_numeric_id_keeps_the_engine_name_never_blank(tmp_path, monkeypatch):
    rv = {"referenceVideo": dict(_RV_TBKV["referenceVideo"], model="v3.0.1")}
    rows, looked = _collect(tmp_path, monkeypatch, _vtask(rv))
    row = rows["780000000000000001"]
    assert row["model_id"] == "v3.0.1" and row["model_name"] == "V3.0 Flash"
    assert looked == [], "a name is never handed to the version lookup"


def test_needs_model_fix_never_hands_a_name_to_the_version_lookup():
    for name in ("tbkv1.0.1", "v4.0.1", "v3.0.1"):
        assert core._needs_model_fix({"model_id": name, "model_name": "",
                                      "is_video": "1"}) == ""
    # ruling 3: a VIDEO row with a numeric id and a blank name IS filled
    assert core._needs_model_fix({"model_id": TBKV_IDS["tbkv1.0.1"], "model_name": "",
                                  "is_video": "1"}) == TBKV_IDS["tbkv1.0.1"]
    assert core._needs_model_fix({"model_id": TBKV_IDS["tbkv1.0.1"], "model_name": "",
                                  "is_video": "1", "video_model": "tbkv1.0.1"}) \
        == TBKV_IDS["tbkv1.0.1"]


# Real v2.7 / v3.0.1 tasks carry this IMAGE checkpoint as modelId (build_video_parameters'
# docstring). Its title must never land on a video row (review f-V-F2 / V-R2).
IMAGE_CKPT = "1648918127446573124"


def test_a_v27_task_carrying_an_image_checkpoint_keeps_its_engine_name(tmp_path, monkeypatch):
    i2v = {"i2vPro": {"model": "v2.7", "mode": "professional", "mediaId": "767513920025866554",
                      "prompts": "<redacted>", "duration": "5"}}
    rows, looked = _collect(tmp_path, monkeypatch, _vtask(i2v, IMAGE_CKPT),
                            names={IMAGE_CKPT: "Some Image Checkpoint v3"})
    row = rows["780000000000000001"]
    assert (row["model_id"], row["model_name"]) == ("v2.7", "V2.7 (High Dynamics)")
    assert row["video_model"] == "v2.7"
    assert looked == [], "the image checkpoint is never looked up for a video row"


def test_an_engine_the_roster_does_not_know_still_takes_its_numeric_id(tmp_path, monkeypatch):
    rv = {"referenceVideo": dict(_RV_TBKV["referenceVideo"], model="v9.9-new")}
    rows, _ = _collect(tmp_path, monkeypatch, _vtask(rv, "2099000000000000001"),
                       names={"2099000000000000001": "Brand New Video v1"})
    row = rows["780000000000000001"]
    assert (row["model_id"], row["model_name"]) == ("2099000000000000001", "Brand New Video v1")


def test_needs_model_fix_never_titles_a_video_row_with_another_models_id():
    v27 = {"model_id": IMAGE_CKPT, "model_name": "", "is_video": "1", "video_model": "v2.7"}
    assert core._needs_model_fix(v27) == ""
    # a v4.0 row filed under v4.0.1's id is not v4.0's to title either
    assert core._needs_model_fix({"model_id": "2003969750675682808", "model_name": "",
                                  "is_video": "1", "video_model": "v4.0"}) == ""
    # no engine recorded (older rows) and image rows keep today's rule
    assert core._needs_model_fix(dict(v27, video_model="")) == IMAGE_CKPT
    assert core._needs_model_fix(dict(v27, is_video="", video_model="")) == IMAGE_CKPT


# =============================================================================
# V7 -- the --generate-video --task-id recovery road (review f-V-F1)
# =============================================================================
def _recover_i2v(tmp_path, monkeypatch, task, lookup=None):
    """run_generate_video --task-id with NO --video-model: the args-built params default to
    v4.0.1, and the row must still be filed from the recovered task."""
    from pathlib import Path
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "task_detail_gql", lambda s, t, **k: task)
    monkeypatch.setattr(core, "media_file_gql", lambda s, m: {"fileUrl": "https://x/v.mp4"})

    def _dl(session, url, stem, **kw):
        p = Path(str(stem) + ".mp4")
        p.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        return "ok", p
    monkeypatch.setattr(core, "download", _dl)
    monkeypatch.setattr(core, "video_poster_thumb", lambda *a, **k: None)
    monkeypatch.setattr(core, "video_faststart", lambda p: None)

    def _no_title(s, mid, **k):
        raise core.PixAIError("lookup failed")
    monkeypatch.setattr(core, "model_name_gql", lookup or _no_title)
    got = core.run_generate_video(_i2v_args(tmp_path, task_id="T-v", image=""))
    assert got["submitted"] is True and got["videos"] == 1
    return {r["media_id"]: r for r in load_catalog(tmp_path / "catalog.db")}["780000000000000001"]


def test_recovering_a_tsubaki_task_files_it_under_its_own_engine(tmp_path, monkeypatch):
    i2v = {"i2vPro": {"model": "tbkv1.0.1", "mode": "professional", "mediaId": "767513920025866554",
                      "prompts": "PROMPT-PLACEHOLDER", "duration": "15"}}
    row = _recover_i2v(tmp_path, monkeypatch, _vtask(i2v, TBKV_IDS["tbkv1.0.1"]))
    assert (row["model_id"], row["model_name"]) == (TBKV_IDS["tbkv1.0.1"], "Tsubaki Video")
    assert row["video_model"] == "tbkv1.0.1"
    # the rest of the row is the task's too, not this run's args
    assert row["prompt_full"] == "PROMPT-PLACEHOLDER" and row["video_duration"] == "15"


def test_recovering_a_task_with_no_numeric_id_keeps_its_engine_name(tmp_path, monkeypatch):
    i2v = {"i2vPro": {"model": "v3.0.1", "mode": "professional", "mediaId": "767513920025866554",
                      "prompts": "PROMPT-PLACEHOLDER", "duration": "5"}}
    looked = []
    row = _recover_i2v(tmp_path, monkeypatch, _vtask(i2v),
                       lookup=lambda s, mid, **k: looked.append(mid) or "Wrong Title")
    assert (row["model_id"], row["model_name"]) == ("v3.0.1", "V3.0 Flash")
    assert looked == [], "v4.0.1's id (the args default) is never borrowed or looked up"


def _seed_raw(db, rows):
    save_catalog(db, rows)
    g._MIGRATED.discard(g._catalog_key(db))


def test_the_video_row_repair_migration_is_idempotent(tmp_path):
    db = tmp_path / "catalog.db"
    _seed_raw(db, [
        _row(media_id="a", is_video="1", model_id="tbkv1.0.1"),
        _row(media_id="b", is_video="1", model_id="v4.0.1", video_model="v4.0.1",
             video_mode="professional"),
        _row(media_id="c", is_video="1", model_id="v3.0.1"),          # no id: keeps its name
        _row(media_id="d", is_video="1", model_id="v9.9-unknown"),    # unknown: untouched
        _row(media_id="e", is_video="", model_id="v4.0.1"),           # not a video row
        _row(media_id="f", is_video="1", model_id="2042030623542642408",
             model_name="Tsubaki Video Flash v1.0"),                  # already numeric
        # review V-R3: what the old name-as-id lookup could leave in model_name
        _row(media_id="g", is_video="1", model_id="tbkv1.0",
             model_name="Unknown or removed model"),                  # --relabel-removed stamp
        _row(media_id="h", is_video="1", model_id="v4.0", model_name="v4.0"),
        _row(media_id="i", is_video="1", model_id="v3.2", model_name="V3.2 by hand"),
    ])
    g.migrate(db, force=True)
    first = {r["media_id"]: r for r in load_catalog(db)}
    g.migrate(db, force=True)
    second = {r["media_id"]: r for r in load_catalog(db)}
    assert first == second, "a second run changes nothing"
    assert (first["a"]["model_id"], first["a"]["video_model"]) == (TBKV_IDS["tbkv1.0.1"],
                                                                   "tbkv1.0.1")
    assert first["a"]["model_name"] == ""          # --fix-models titles it (ruling 3)
    assert (first["b"]["model_id"], first["b"]["video_model"]) == ("2003969750675682808",
                                                                   "v4.0.1")
    assert first["c"]["model_id"] == "v3.0.1"
    assert first["d"]["model_id"] == "v9.9-unknown"
    assert first["e"]["model_id"] == "v4.0.1"
    assert first["f"]["model_id"] == "2042030623542642408"
    assert first["f"]["model_name"] == "Tsubaki Video Flash v1.0"
    # and the repaired row is now something --fix-models can title
    assert core._needs_model_fix(first["a"]) == TBKV_IDS["tbkv1.0.1"]
    # a stamp the name-as-id lookup left behind is cleared, so the real title can land
    assert (first["g"]["model_id"], first["g"]["model_name"]) == (TBKV_IDS["tbkv1.0"], "")
    assert core._needs_model_fix(first["g"]) == TBKV_IDS["tbkv1.0"]
    assert (first["h"]["model_id"], first["h"]["model_name"]) == ("2003968021137101826", "")
    # a name that is neither is somebody's, and stays
    assert first["i"]["model_name"] == "V3.2 by hand"


def test_the_repair_clears_exactly_the_label_fix_models_stamps():
    import inspect
    assert "'Unknown or removed model'" in g._VIDEO_ROW_REPAIR_SQL
    assert '"Unknown or removed model"' in inspect.getsource(core.run_fix_models)


def test_video_task_params_route_reports_the_sources_ratio(tmp_path, monkeypatch, pixai):
    from tests.conftest import login_test_client
    save_catalog(tmp_path / "catalog.db", [_row(media_id="780000000000000001", task_id="T-v",
                                                is_video="1", filename="videos/v.mp4")])
    monkeypatch.setattr(core, "task_detail_gql",
                        lambda s, t, **k: _vtask(_RV_TBKV, TBKV_IDS["tbkv1.0"]))
    cli = login_test_client(g.create_app(tmp_path))
    d = cli.get("/api/video-task-params/T-v").get_json()
    assert d["kind"] == "r2v" and d["video_model"] == "tbkv1.0" and d["ratio"] == "3:2"


# =============================================================================
# helpers
# =============================================================================
def _refvid_args(tmp_path, **kw):
    base = dict(out=str(tmp_path), token=None, reference_video=True, ref_image=["10"],
                ref_video=None, ref_audio=None, params_json="", prompt="@image1",
                video_model="", duration=5, vmode="professional", audio=False,
                audio_language="english", vchannel="private", kaisuuken_id="",
                confirm=False, task_id="", poll_timeout=600, name_length=60,
                dump_params=False, video_ratio="")
    base.update(kw)
    return SimpleNamespace(**base)


def _i2v_args(tmp_path, **kw):
    base = dict(out=str(tmp_path), token=None, generate_video=True, image="55", tail="",
                prompt="p", params_json="", video_model="", model="", duration=5,
                vmode="professional", audio=False, audio_language="english", negative="",
                video_prompt_helper=False, kaisuuken_id="", camera_movement="",
                vchannel="private", confirm=False, task_id="", poll_timeout=600,
                name_length=60, dump_params=False, video_ratio="")
    base.update(kw)
    return SimpleNamespace(**base)


# =============================================================================
# The Generate drawer's ratio picker on the web road (lane w2-small, 2026-09-28)
# =============================================================================
# The drawer sends `ratio` only for a Tsubaki engine in Multi-Reference and never as Auto
# (videoDrawerCore.ratioForPayload); build_request carries it to the referenceVideo road and
# writes a receipt where it cannot go -- keyed on the ROAD, not the shot mode (spend review N6).

def _web(**kw):
    body = {"mode": "R2V", "images": ["1"], "prompt": "@image1", "video_model": "tbkv1.0.1",
            "duration": 5}
    body.update(kw)
    return core.build_request(body, mode="video")


def test_the_web_road_sends_the_ratio_for_tbkv_multi_reference():
    for model in ("tbkv1.0.1", "tbkv1.0"):
        r = _web(video_model=model, ratio="21:9")
        assert r.parameters["referenceVideo"]["ratio"] == "21:9"
        assert r.adjusted == []


def test_no_ratio_or_auto_is_byte_identical():
    plain = _web().parameters
    assert _web(ratio="").parameters == plain
    assert _web(ratio="adaptive").parameters == plain
    assert "ratio" not in plain["referenceVideo"]


def test_a_ratio_the_road_cannot_carry_is_dropped_with_a_receipt():
    why = "only Tsubaki Video's Multi-Reference takes an aspect ratio"
    r = _web(video_model="v4.0.1", ratio="16:9")
    assert "ratio" not in r.parameters["referenceVideo"]
    assert r.adjusted == [{"field": "ratio", "asked": "16:9", "used": None, "why": why}]
    r = _web(mode="I2V", ratio="16:9")
    assert "i2vPro" in r.parameters and "ratio" not in r.parameters["i2vPro"]
    assert [a["field"] for a in r.adjusted] == ["ratio"]


def test_an_flf_with_one_frame_is_a_reference_video_and_keeps_its_ratio():
    """N6: the receipt follows the ROAD. An FLF shot with only a start frame goes out as a
    reference video, where a Tsubaki engine takes the ratio."""
    r = _web(mode="FLF", ratio="3:4")
    assert r.parameters["referenceVideo"]["ratio"] == "3:4"
    assert r.adjusted == []


def test_an_unknown_ratio_is_the_badges_note_not_a_spend(tmp_path, monkeypatch):
    with pytest.raises(core.PixAIError):
        _web(ratio="5:4")
    from tests.conftest import login_client
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    cli = login_client(tmp_path)
    d = cli.post("/api/price", json={"mode": "R2V", "images": ["1"], "prompt": "@image1",
                                     "video_model": "tbkv1.0.1", "ratio": "5:4"}).get_json()
    assert d["cost"] is None and "aspect ratio" in d["note"]


def test_the_quote_and_the_submit_carry_the_same_ratio(tmp_path, monkeypatch):
    from tests.conftest import login_client
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task", lambda s, params: seen.update(priced=params) or 21000)
    monkeypatch.setattr(core, "match_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "submit",
                        lambda s, req, **k: seen.update(sent=req.parameters) or {"task_id": "v1"})
    cli = login_client(tmp_path)
    body = {"mode": "R2V", "images": ["1"], "prompt": "@image1", "video_model": "tbkv1.0.1",
            "duration": 5, "ratio": "9:16"}
    assert cli.post("/api/price", json=body).get_json()["cost"] == 21000
    assert cli.post("/api/loom/generate", json=body).get_json().get("task_id") == "v1"
    assert seen["priced"]["referenceVideo"] == seen["sent"]["referenceVideo"]
    assert seen["sent"]["referenceVideo"]["ratio"] == "9:16"
