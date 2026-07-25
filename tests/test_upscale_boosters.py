"""Upscale (both PixAI methods) + the Generate-tab boosters as ORDINARY generation
parameters on the t2i/i2i submit path -- enlarge/enlargeModel, upscale + its denoising
block, enableADetailer, qualityTag -- plus the dynamic ratio cap those sliders honour.
Pure builders + one mocked /v2/task-price and the web drawer's payload mapping; no
network, no spend."""
import json
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

import pixai_gallery_backup as core
from pixai_gallery import CATALOG_FIELDS, save_catalog

from tests.conftest import login_client


def _row(**kw):
    return {f: "" for f in CATALOG_FIELDS} | kw


def _gen_args(**kw):
    base = dict(params_json="", prompt="p", model="m", negative="", width=512, height=512,
                steps=25, cfg=7, count=1, priority=500, mode="auto", seed=None, lora=None,
                prompt_helper=True, kaisuuken_id="")
    base.update(kw)
    return SimpleNamespace(**base)


UPSCALE_KEYS = ("enlarge", "enlargeModel", "upscale", "upscaleDenoisingStrength",
                "upscaleDenoisingSteps", "upscaleSampler")


# --- the dynamic ratio cap ---------------------------------------------------

def test_output_dims_match_the_dialog_the_slider_drives():
    """Their own dialog labelled a 1400x784 source '1952x1096' at Hires 1.4 and
    '2656x1488' at enlarge 1.9 -- the multiple-of-8 snap SD needs, floored."""
    assert core.upscale_output_dims(1400, 784, 1.4) == (1952, 1096)
    assert core.upscale_output_dims(1400, 784, 1.9) == (2656, 1488)
    assert core.upscale_output_dims(1400, 784, 1.0) == (1400, 784)   # 1.0 = identity


def test_max_ratio_reproduces_both_measured_hires_sliders():
    """Two real sliders, same mode, DIFFERENT maxima -- which is the whole reason this
    is computed instead of hardcoded."""
    assert core.max_upscale_ratio(768, 1280, "upscale") == 1.5
    assert core.max_upscale_ratio(1400, 784, "upscale") == 1.4


def test_max_ratio_reproduces_the_measured_enlarge_slider():
    assert core.max_upscale_ratio(1400, 784, "enlarge") == 1.9


def test_max_ratio_is_derived_from_the_source_size():
    # a small source can go much further than a large one in the SAME mode; a source
    # already past the ceiling cannot be upscaled at all.
    assert core.max_upscale_ratio(512, 512, "upscale") > core.max_upscale_ratio(1400, 784, "upscale")
    assert core.max_upscale_ratio(2048, 2048, "upscale") == 1.0
    assert core.max_upscale_ratio(3000, 3000, "enlarge") == 1.0


def test_max_ratio_rejects_an_unknown_mode():
    with pytest.raises(core.PixAIError):
        core.max_upscale_ratio(512, 512, "hires")


# --- the two upscale methods on the generate path ----------------------------

def test_no_upscale_or_booster_keys_unless_asked():
    p = core._gen_parameters(_gen_args())
    for k in UPSCALE_KEYS + ("enableADetailer", "qualityTag"):
        assert k not in p


def test_enlarge_emits_ratio_plus_upscaler_and_nothing_else():
    p = core._gen_parameters(_gen_args(enlarge=1.2))
    assert p["enlarge"] == 1.2
    assert p["enlargeModel"] == core.DEFAULT_ENLARGE_MODEL == "R-ESRGAN 4x+ Anime6B"
    # enlarge is the plain-upscaler method: it has no denoising controls at all
    assert "upscale" not in p and "upscaleDenoisingStrength" not in p


def test_enlarge_model_choice_is_carried_and_unknown_names_fall_back():
    assert core._gen_parameters(_gen_args(enlarge=1.2, enlarge_model="SwinIR_4x"))["enlargeModel"] == "SwinIR_4x"
    p = core._gen_parameters(_gen_args(enlarge=1.2, enlarge_model="Lanczos"))
    assert p["enlargeModel"] == core.DEFAULT_ENLARGE_MODEL


def test_hires_emits_the_whole_denoising_block():
    p = core._gen_parameters(_gen_args(upscale=1.4, width=1400, height=784))
    assert p["upscale"] == 1.4
    assert p["upscaleDenoisingStrength"] == 0.6
    assert p["upscaleDenoisingSteps"] == 26
    assert p["upscaleSampler"] == ""
    assert "enlarge" not in p and "enlargeModel" not in p   # no upscaler dropdown in Hires


def test_hires_denoising_overrides_clamp_to_the_slider_bounds():
    p = core._gen_parameters(_gen_args(upscale=1.2, upscale_denoising_strength=0.45,
                                       upscale_denoising_steps=12))
    assert p["upscaleDenoisingStrength"] == 0.45 and p["upscaleDenoisingSteps"] == 12
    hi = core._gen_parameters(_gen_args(upscale=1.2, upscale_denoising_strength=5,
                                        upscale_denoising_steps=900))
    assert hi["upscaleDenoisingStrength"] == 0.99 and hi["upscaleDenoisingSteps"] == 50
    lo = core._gen_parameters(_gen_args(upscale=1.2, upscale_denoising_strength=0,
                                        upscale_denoising_steps=0))
    assert lo["upscaleDenoisingStrength"] == 0.01 and lo["upscaleDenoisingSteps"] == 1


def test_the_two_methods_are_mutually_exclusive():
    with pytest.raises(core.PixAIError):
        core._gen_parameters(_gen_args(enlarge=1.2, upscale=1.4))


def test_ratio_at_or_below_one_is_not_an_upscale_at_all():
    for kw in ({"enlarge": 1.0}, {"enlarge": 0.5}, {"upscale": 1.0}, {"enlarge": ""},
               {"upscale": None}):
        p = core._gen_parameters(_gen_args(**kw))
        for k in UPSCALE_KEYS:
            assert k not in p, kw


def test_ratio_is_snapped_to_the_slider_step_and_clamped_to_the_computed_max():
    # 1400x784 Hires tops out at 1.4 -- asking for 1.9 must not submit an out-of-range ratio
    assert core._gen_parameters(_gen_args(upscale=1.9, width=1400, height=784))["upscale"] == 1.4
    # ...while the SAME 1.9 is legal in enlarge mode on that size
    assert core._gen_parameters(_gen_args(enlarge=1.9, width=1400, height=784))["enlarge"] == 1.9
    assert core._gen_parameters(_gen_args(enlarge=1.24, width=512, height=512))["enlarge"] == 1.2


def test_a_source_already_at_the_ceiling_emits_nothing_rather_than_a_1x_upscale():
    """Clamping to a 1.0 max must DROP the block, not submit `enlarge: 1.0` -- that would
    change the priced shape of a generation that gains nothing from it."""
    for kw in ({"enlarge": 1.5}, {"upscale": 1.5}):
        p = core._gen_parameters(_gen_args(width=2048, height=2048, **kw))
        for k in UPSCALE_KEYS:
            assert k not in p, kw


# --- boosters ----------------------------------------------------------------

def test_face_fix_is_opt_in_and_boolean():
    assert core._gen_parameters(_gen_args(face_fix=True))["enableADetailer"] is True
    assert "enableADetailer" not in core._gen_parameters(_gen_args(face_fix=False))


def test_quality_tag_is_a_prefix_object():
    p = core._gen_parameters(_gen_args(quality_tag="Masterpiece"))
    assert p["qualityTag"] == {"prefix": "Masterpiece"}
    assert core._gen_parameters(_gen_args(quality_tag="best quality"))["qualityTag"] == {"prefix": "best quality"}
    assert "qualityTag" not in core._gen_parameters(_gen_args(quality_tag=""))


# --- pricing -----------------------------------------------------------------

def test_the_priced_upscale_params_reach_task_price(monkeypatch):
    """The two methods differ ~3x in cost, so the drawer's badge is only honest if these
    actually land in the /v2/task-price query."""
    seen = {}
    monkeypatch.setattr(core, "_rest_get",
                        lambda s, path, params=None, **k: seen.update(params=params) or {"actualPrice": 3700})
    core.price_task(object(), core._gen_parameters(
        _gen_args(width=1400, height=784, upscale=1.4, face_fix=True)))
    q = seen["params"]
    assert q["upscale"] == 1.4 and q["upscaleDenoisingStrength"] == 0.6
    assert q["upscaleDenoisingSteps"] == 26 and q["enableADetailer"] is True

    seen.clear()
    core.price_task(object(), core._gen_parameters(
        _gen_args(width=1400, height=784, enlarge=1.9)))
    assert seen["params"]["enlarge"] == 1.9


# --- CLI ---------------------------------------------------------------------

def test_cli_flags_reach_the_builder(monkeypatch, tmp_path):
    """Driven through the REAL parser (core.main) so the add_argument() calls themselves
    are what's pinned, not a re-derived namespace."""
    captured = {}
    monkeypatch.setattr(core, "run_generate", lambda a: captured.setdefault("args", a))
    monkeypatch.setattr("sys.argv", ["prog", "--generate", "--prompt", "p", "--model", "m",
                                     "--width", "1400", "--height", "784",
                                     "--upscale", "1.4", "--upscale-denoise", "0.5",
                                     "--upscale-denoise-steps", "30",
                                     "--face-fix", "--quality-tag",
                                     "--out", str(tmp_path)])
    core.main()
    p = core._gen_parameters(captured["args"])
    assert p["upscale"] == 1.4 and p["upscaleDenoisingStrength"] == 0.5
    assert p["upscaleDenoisingSteps"] == 30 and p["enableADetailer"] is True
    assert p["qualityTag"] == {"prefix": core.DEFAULT_QUALITY_TAG}


def test_cli_enlarge_flags_reach_the_builder(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(core, "run_generate", lambda a: captured.setdefault("args", a))
    monkeypatch.setattr("sys.argv", ["prog", "--generate", "--prompt", "p", "--model", "m",
                                     "--enlarge", "1.5", "--enlarge-model", "Lollypop",
                                     "--out", str(tmp_path)])
    core.main()
    p = core._gen_parameters(captured["args"])
    assert p["enlarge"] == 1.5 and p["enlargeModel"] == "Lollypop"


def test_cli_generate_without_the_new_flags_is_unchanged(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(core, "run_generate", lambda a: captured.setdefault("args", a))
    monkeypatch.setattr("sys.argv", ["prog", "--generate", "--prompt", "p", "--model", "m",
                                     "--out", str(tmp_path)])
    core.main()
    p = core._gen_parameters(captured["args"])
    for k in UPSCALE_KEYS + ("enableADetailer", "qualityTag"):
        assert k not in p


# --- web drawer --------------------------------------------------------------

def _priced(monkeypatch, tmp_path, body):
    """POST the drawer's payload at /api/price and return the params it priced."""
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    cli = login_client(tmp_path)
    seen = {}

    def fake_price(_session, params):
        seen["params"] = params
        return 1200

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "price_task", fake_price)
    monkeypatch.setattr(core, "match_kaisuuken", lambda *a, **k: None)
    r = cli.post("/api/price", json=body)
    return seen.get("params"), r.get_json()


def test_web_payload_carries_hires_and_boosters(monkeypatch, tmp_path):
    params, d = _priced(monkeypatch, tmp_path,
                        {"version_id": "v1", "prompt": "x", "width": 1400, "height": 784,
                         "upscale": 1.4, "upscale_denoise": 0.5, "upscale_denoise_steps": 30,
                         "face_fix": True, "quality_tag": "Masterpiece"})
    assert params["upscale"] == 1.4 and params["upscaleDenoisingStrength"] == 0.5
    assert params["upscaleDenoisingSteps"] == 30
    assert params["enableADetailer"] is True
    assert params["qualityTag"] == {"prefix": "Masterpiece"}
    assert d["cost"] == 1200


def test_web_payload_carries_enlarge(monkeypatch, tmp_path):
    params, _d = _priced(monkeypatch, tmp_path,
                         {"version_id": "v1", "prompt": "x", "width": 1400, "height": 784,
                          "enlarge": 1.9, "enlarge_model": "SwinIR_4x"})
    assert params["enlarge"] == 1.9 and params["enlargeModel"] == "SwinIR_4x"


def test_web_payload_without_upscale_is_unchanged(monkeypatch, tmp_path):
    params, _d = _priced(monkeypatch, tmp_path, {"version_id": "v1", "prompt": "x"})
    for k in UPSCALE_KEYS + ("enableADetailer", "qualityTag"):
        assert k not in params


def test_web_both_methods_at_once_is_a_note_not_a_traceback(monkeypatch, tmp_path):
    _params, d = _priced(monkeypatch, tmp_path,
                         {"version_id": "v1", "prompt": "x", "enlarge": 1.2, "upscale": 1.4})
    assert d["cost"] is None and "mutually exclusive" in (d.get("note") or "")


def test_drawer_offers_hires_as_a_booster_and_not_the_enlarge_method(tmp_path):
    """PixAI runs Upscale/Hires from the IMAGE VIEW, on a picture that already exists. The
    only upscale that belongs in the generation panel is their `Enhance Details (HiRes)`
    BOOSTER, beside Face Fix and Quality Tag.

    So the drawer keeps the Hires controls (ratio + denoising) as that chip's disclosure and
    must NOT offer the ESRGAN `enlarge` method at all: there is no source image here, which
    is exactly why the old three-way segment showed a ratio cap and an output size derived
    from the size the generation was about to be rather than from a real picture.
    """
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = login_client(tmp_path).get("/").get_data(as_text=True)
    for probe in ('id="gen-hires"', 'id="gen-up-ratio"', 'id="gen-up-dims"',
                  'id="gen-up-denoise"', 'id="gen-facefix"', 'id="gen-qtag"'):
        assert probe in html, probe
    # The enlarge method and its dropdown left the drawer with the segment.
    for gone in ('id="gen-up-seg"', 'id="gen-up-model"', 'id="gu-enlarge"', 'id="gu-off"',
                 "Gen.setUpscale("):
        assert gone not in html, gone + " is still in the generation panel"


def test_upscale_constants_reach_the_client_from_core(tmp_path):
    """The upscaler names and the pixel ceilings are handed to the page from core, so the
    image-view panel needs no second hand port of max_upscale_ratio and no retyped model
    list. PixAI matches the names literally -- mixed underscores, spaces and plus signs --
    so a template typo is a rejected submit, not a cosmetic slip."""
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    cli = login_client(tmp_path)
    for path in ("/", "/image/1"):
        html = cli.get(path).get_data(as_text=True)
        assert "__UPSCALE_CONST__" not in html, path + " left the raw marker on the page"
        blob = html.split("window.MG_UPSCALE=", 1)
        assert len(blob) == 2, path + " never received window.MG_UPSCALE"
        payload = json.loads(blob[1].split(";</script>", 1)[0])
        assert payload["enlargeModels"] == list(core.ENLARGE_MODELS)
        assert payload["defaultEnlargeModel"] == core.DEFAULT_ENLARGE_MODEL
        assert payload["ceiling"] == core.UPSCALE_PIXEL_CEILING
        for name in core.ENLARGE_MODELS:
            assert name in html, name


def test_the_other_base_html_pages_do_not_leak_the_marker(tmp_path):
    """__UPSCALE_CONST__ is substituted into INDEX_HTML and DETAIL_HTML only. Four more
    templates derive from the same BASE_HTML, and a marker placed there instead would render
    as literal text on every one of them."""
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    cli = login_client(tmp_path)
    for path in ("/health", "/panel", "/dupes"):
        r = cli.get(path)
        if r.status_code != 200:
            continue
        assert "__UPSCALE_CONST__" not in r.get_data(as_text=True), path


def test_drawer_ratio_cap_agrees_with_the_python_one(tmp_path):
    """The drawer carries a HAND PORT of max_upscale_ratio/upscale_output_dims so the
    slider can show a live max and output size without a round-trip. Run the real ported
    JS in Node and compare it to the Python it was copied from -- a drifted ceiling would
    offer a ratio the server then silently clamps, with no visible sign in the UI."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = login_client(tmp_path).get("/").get_data(as_text=True)
    block = "var upCeil=" + html.split("var upCeil=", 1)[1].split("function syncUpscale", 1)[0]
    sizes = [(768, 1280), (1400, 784), (512, 512), (1024, 1024), (2048, 2048), (1536, 640)]
    harness = "console.log(JSON.stringify([{}].map(function(d){{ return [upMax(d[0],d[1],'enlarge'), upMax(d[0],d[1],'upscale'), upDims(d[0],d[1],1.4)]; }})));".format(
        ",".join("[{},{}]".format(w, h) for w, h in sizes))
    js = tmp_path / "cap.js"
    js.write_text(block + "\n" + harness, encoding="utf-8")
    out = tmp_path / "cap.out"
    # Real files + DEVNULL stdin, same reason as tests/test_js_syntax.py: some sandboxes
    # cannot duplicate pytest's captured std handles.
    try:
        with open(out, "w", encoding="utf-8") as fh, open(os.devnull) as nul:
            rc = subprocess.call([node, str(js)], stdin=nul, stdout=fh,
                                 stderr=subprocess.STDOUT)
    except OSError as e:                              # noqa: BLE001
        pytest.skip("cannot spawn node in this environment: {}".format(e))
    text = out.read_text(encoding="utf-8")
    assert rc == 0, text
    got = json.loads(text)
    want = [[core.max_upscale_ratio(w, h, "enlarge"), core.max_upscale_ratio(w, h, "upscale"),
             list(core.upscale_output_dims(w, h, 1.4))] for w, h in sizes]
    assert got == want
