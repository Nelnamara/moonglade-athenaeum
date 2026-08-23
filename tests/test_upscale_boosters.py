"""Upscale (both PixAI methods) + the Generate-tab boosters as ORDINARY generation
parameters on the t2i/i2i submit path -- enlarge/enlargeModel, upscale + its denoising
block, enableADetailer, qualityTag -- plus the dynamic ratio cap those sliders honour.
Pure builders + one mocked /v2/task-price and the web drawer's payload mapping; no
network, no spend."""
import json
import os
import pathlib
import shutil
import subprocess
from types import SimpleNamespace

import pytest

import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, save_catalog

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


def test_drawer_offers_hires_as_a_booster_and_not_the_enlarge_method():
    """PixAI runs Upscale/Hires from the IMAGE VIEW, on a picture that already exists. The
    only upscale that belongs in the generation panel is their `Enhance Details (HiRes)`
    BOOSTER, beside Face Fix and Quality Tag.

    Since the classic cut (2026-08-08) the drawer is the React Create surface
    (gallery/src) -- same rules, restated against it: the Hires booster is a
    settings-free chip (PixAI's Add Booster menu offers add-or-remove and nothing
    else; owner, verifying live: "It just adds a chip. you can only remove it."), and
    the ESRGAN `enlarge` method is not offered at all: there is no source image here.
    The ratio/denoise controls live on <UpscalePanel>, where a real picture exists.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    jsx = (root / "gallery" / "src" / "components" / "CreateMobile.jsx").read_text(encoding="utf-8")
    for chip in ("Face Fix", "Quality Tag", "Enhance Details"):
        assert chip in jsx, chip + " chip is missing from the Create surface"
    core_js = (root / "gallery" / "src" / "gen" / "genCore.js").read_text(encoding="utf-8")
    # The chip carries NO settings: the payload takes PixAI's own captured constants,
    # not values off ratio/denoise controls that no longer exist in the drawer.
    assert "upscale: hires ? MG_HIRES.ratio : null" in core_js
    # The enlarge method (and its upscaler dropdown) never entered this surface.
    for src, name in ((core_js, "genCore.js"), (jsx, "CreateMobile.jsx")):
        assert "enlarge" not in src, "the enlarge method is offered in " + name


def test_upscale_constants_reach_the_client_from_core(tmp_path):
    """The upscaler names and the pixel ceilings are handed to the page from core, so the
    image-view panel needs no second hand port of max_upscale_ratio and no retyped model
    list. PixAI matches the names literally -- mixed underscores, spaces and plus signs --
    so a template typo is a rejected submit, not a cosmetic slip."""
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    cli = login_client(tmp_path)
    # Since the classic cut the marker is substituted into NEXT_PAGE ("/") and the
    # Loom shells -- the surfaces with upscale UI -- not INDEX/DETAIL.
    for path in ("/", "/loom"):
        html = cli.get(path).get_data(as_text=True)
        assert "__UPSCALE_CONST__" not in html, path + " left the raw marker on the page"
        blob = html.split("window.MG_UPSCALE=", 1)
        assert len(blob) == 2, path + " never received window.MG_UPSCALE"
        # Two globals ship in one tag now (MG_UPSCALE then MG_LORA), so this splits on the
        # next assignment rather than the tag's end.
        payload = json.loads(blob[1].split(";window.MG_LORA=", 1)[0])
        assert payload["enlargeModels"] == list(core.ENLARGE_MODELS)
        assert payload["defaultEnlargeModel"] == core.DEFAULT_ENLARGE_MODEL
        assert payload["ceiling"] == core.UPSCALE_PIXEL_CEILING
        for name in core.ENLARGE_MODELS:
            assert name in html, name


def test_the_login_shell_does_not_leak_the_marker(tmp_path):
    """__UPSCALE_CONST__ is substituted into NEXT_PAGE and the Loom shells only. The login
    shell is the one other full page a browser renders (deliberately its own, smaller
    template), and the marker placed in a shared head instead would render as literal text
    to every anonymous visitor. (Was the /health//panel//dupes BASE_HTML check before the
    classic cut deleted those pages.)"""
    from moonglade_gallery import create_app
    r = create_app(tmp_path).test_client().get("/login")
    assert r.status_code == 200
    assert "__UPSCALE_CONST__" not in r.get_data(as_text=True)


def test_image_meta_route_serves_what_an_upscale_needs_and_no_host_path(tmp_path):
    """The lightbox is driven from card elements that carry a thumbnail and an index, so the
    panel asks for the one row it needs rather than every card's markup growing fields only
    one feature reads.

    Scoped narrow on purpose: `filename` is a HOST PATH fragment and stays out, matching the
    withholding /panel already does for non-local callers.
    """
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="1", filename="C:/secret/place/a_1.png", created_at="2025-01-01T00:00:00",
             width="1400", height="784", model_id="4242", model_name="WAI v17",
             prompt_full="night elf druid"),
    ])
    cli = login_client(tmp_path)
    d = cli.get("/api/image-meta/1").get_json()
    assert d["width"] == "1400" and d["height"] == "784"
    assert d["model_id"] == "4242" and d["model_name"] == "WAI v17"
    assert d["prompt"] == "night elf druid"
    assert d["local_import"] is False
    assert "filename" not in d, "the host path must not ride along"
    assert cli.get("/api/image-meta/nope").status_code == 404


def test_image_meta_flags_a_locally_imported_file(tmp_path):
    """A locally imported file has no PixAI task behind it, so it can NEVER carry a model.
    That is a different answer from "your catalog has not been swept yet" -- one is fixable
    with --backfill-full-meta and the other never will be -- and the panel says so only
    because the route distinguishes them."""
    save_catalog(tmp_path / "catalog.db", [
        _row(media_id="2", filename="b_2.png", created_at="2025-01-01T00:00:00",
             width="512", height="512", source="local"),
    ])
    d = login_client(tmp_path).get("/api/image-meta/2").get_json()
    assert d["local_import"] is True and d["model_id"] == ""


def test_upscale_lives_on_the_image_view_on_both_surfaces():
    """PixAI invokes Upscale on a picture that already exists, so it belongs where you look
    at one. Since the classic cut those surfaces are the React Lightbox (a flyout off one
    icon) and the Details view (an inline panel) -- BOTH mounting the same shared React
    <UpscalePanel> component (2026-08-08 no-vanilla port of <mg-upscale-panel>), never a
    second drifting copy of its controls.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    lbx = (root / "gallery" / "src" / "components" / "Lightbox.jsx").read_text(encoding="utf-8")
    assert "import UpscalePanel" in lbx and "<UpscalePanel ref={upEl}" in lbx, \
        "the lightbox no longer mounts the panel"
    assert "upEl.current.open(it.media_id)" in lbx, "one icon opens the flyout for THIS picture"
    # The Details surfaces drive it through the ONE shared hook (desktop + mobile): the hook
    # owns the upEl handle + toggleUpscale, and each Details view renders <UpscalePanel ref={upEl}>.
    hook = (root / "gallery" / "src" / "hooks" / "useImageDetails.js").read_text(encoding="utf-8")
    assert "upEl" in hook and "toggleUpscale" in hook, "the details hook no longer drives the panel"
    for fname in ("DetailsView.jsx", "ImageDetailsMobile.jsx"):
        v = (root / "gallery" / "src" / "components" / fname).read_text(encoding="utf-8")
        assert "import UpscalePanel" in v and "<UpscalePanel ref={upEl}" in v, \
            fname + " no longer renders the shared panel"
    det = (root / "gallery" / "src" / "components" / "DetailsView.jsx").read_text(encoding="utf-8")
    assert "toggleUpscale" in det and "Upscale" in det, "the details view lost its Upscale control"


def test_the_upscale_flyout_never_outlives_the_picture_it_was_opened_for():
    """It is bound to ONE media_id. Stepping to the next image or closing the overlay must
    close it, or a half-configured panel is left pointed at a picture you have moved off --
    the same class of bug as the filters panel's toggle-used-as-close. Since the classic
    cut the lightbox is React (desktop + mobile), so the rule is pinned against both."""
    root = pathlib.Path(__file__).resolve().parent.parent
    for fname in ("Lightbox.jsx", "LightboxMobile.jsx"):
        src = (root / "gallery" / "src" / "components" / fname).read_text(encoding="utf-8")
        step = src[src.index("const step = useCallback"):]
        step = step[:step.index("}, [")]
        assert "closeUpscale()" in step, fname + ": stepping leaves the upscale flyout open"
        close = src[src.index("const close = useCallback"):]
        close = close[:close.index("}, [")]
        assert "upEl.current.close()" in close, fname + ": closing the overlay leaves the flyout open"
        # ...and a media_id change by ANY path (filmstrip jump, swipe) closes it too.
        assert "useEffect(() => { closeUpscale(); }, [mid])" in src, \
            fname + ": the flyout outlives a picture change"


def test_the_upscale_panel_reuses_the_generate_routes(tmp_path):
    """An image-view upscale is an ordinary i2i generation -- mediaId + strength on a normal
    submit -- so it posts the SAME /api/price and /api/generate the drawer uses.

    There is deliberately no /api/upscale: a second submit path is a second place for the
    read-only guard, the free-card check and the job-tracker registration to be forgotten.
    That last one is not hypothetical -- this panel proved it. Until 2026-08-23 it POSTed
    /api/generate with its own fetch, which meant it never called Jobs.track and an upscale
    was registered nowhere: not the job log, not the Activity tray its own success toast
    points at, not the server's orphan sweep. Both halves now ride their shared module.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    src = (root / "gallery" / "src" / "components" / "UpscalePanel.jsx").read_text(encoding="utf-8")
    # Both halves are the SHARED module's now, so what pins each is the panel's import plus the
    # route it hands over -- the fetch literals live in those modules. (The component's own doc
    # names /api/upscale in prose while explaining why it does not exist, hence the quoted forms.)
    probe = (root / "gallery" / "src" / "gen" / "usePriceProbe.js").read_text(encoding="utf-8")
    # Re-anchored 2026-08-23: the POST came out of the hook too. usePriceProbe still owns the
    # debounce, the sequence guard and the verdict; gen/priceRequest.js owns the request and is
    # the one /api/price caller under gallery/src (the Loom rides it as well).
    transport = (root / "gallery" / "src" / "gen" / "priceRequest.js").read_text(encoding="utf-8")
    road = (root / "gallery" / "src" / "gen" / "submitTask.js").read_text(encoding="utf-8")
    assert "usePriceProbe" in src
    assert "requestPrice" in probe and '"/api/price"' in transport
    assert 'from "../gen/submitTask.js"' in src, "the submit must ride the one road"
    assert 'submitTask("/api/generate"' in src, "and it must hand the road the generate route"
    assert "await fetch(route" in road, "which is where the actual POST lives"
    assert "window.Jobs.track(" in road, (
        "the road's registration is the whole reason this panel stopped POSTing for itself")
    assert 'fetch("/api/generate"' not in src, "no bespoke spend fetch may come back"
    assert "'/api/upscale'" not in src and '"/api/upscale"' not in src
    assert "ref_media_id" in src and "ref_strength" in src, "an image-view upscale is i2i"
    # The ceilings come from the server (core.UPSCALE_PIXEL_CEILING via window.MG_UPSCALE),
    # not a second hand port. A drifted copy would offer a ratio the server then silently
    # clamps, with nothing on screen to say the number changed.
    assert "window.MG_UPSCALE" in src
    assert "2048" not in src, "the pixel ceilings must come from the server, not be retyped"
    for name in core.ENLARGE_MODELS:
        assert name not in src, name + " is retyped in the component instead of served"
    # CostBadge's real handle is setChecking()/setPrice(). An invented one (.loading()/.show())
    # is silently a no-op -- the panel renders, the price line never updates, nothing reports it.
    # The panel supplies the badge ref and the probe drives it, so the call sites live there.
    badge = (root / "gallery" / "src" / "components" / "CostBadge.jsx").read_text(encoding="utf-8")
    assert "<CostBadge" in src and "ref={costRef}" in src, "the panel must own the badge instance"
    for meth in ("setChecking", "setPrice"):
        assert meth + "(" in probe, "the probe must call the badge's " + meth
        assert meth + "(" in badge, meth + " is not actually on the badge"
    # Scoped to the badge handle -- Toast.show() is a real, different API on this page.
    for f in (src, probe):
        assert "costRef.current.show(" not in f and "costRef.current.loading(" not in f, (
            "those are not badge methods; calling them fails silently")


def test_lora_weight_spans_pixais_real_range_on_every_surface():
    """PixAI's Advanced panel bounds LoRA weight at -2..2, step 0.1, and NEGATIVE weights are
    legal there -- a LoRA at a negative weight subtracts its influence.

    Ours was a number spinner clamped at 0, so half of their range was unreachable: this was
    a capability gap hiding behind a widget choice, not only a styling preference. Both
    surfaces must agree, because both submit through the same builder. Since the classic
    cut the gallery surface is the React Create screen (gallery/src).
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    jsx = (root / "gallery" / "src" / "components" / "CreateMobile.jsx").read_text(encoding="utf-8")
    # A range slider whose bounds come per ARCHITECTURE from the served table, and whose
    # step is served too -- nothing baked into the markup.
    assert 'type="range"' in jsx and "loraStep()" in jsx
    assert "min={loraLo} max={loraHi}" in jsx, "the LoRA slider bounds are not per-architecture"
    assert 'min="0"' not in jsx, "a 0-floored spinner survives; negative weights are legal on SD"
    core_js = (root / "gallery" / "src" / "gen" / "genCore.js").read_text(encoding="utf-8")
    assert "export function loraRange" in core_js and "window.MG_LORA" in core_js
    use = (root / "gallery" / "src" / "gen" / "useGenerate.js").read_text(encoding="utf-8")
    assert use.count("clampLoras(old.loras, model.model_type)") >= 2, \
        "switching base model AND switching version must both re-clamp attached LoRAs"

    # The Loom's Image tab shares the model, so it must share the control.
    jsx = (root / "loom" / "master-storyboard.jsx").read_text(encoding="utf-8")
    assert 'type="range" step="0.1"' in jsx
    # ...and the SHIPPED bundle must actually carry it. A source-only assertion passes
    # happily against a stale dist/ that no rebuild ever touched.
    bundle = (root / "loom" / "dist" / "master-storyboard.bundle.js").read_text(
        encoding="utf-8", errors="replace")
    # NOT a hardcoded "-2" any more: the bound is per-architecture and read from the served
    # table, so what the shipped bundle must prove is that it uses that mechanism. A
    # source-only check would pass against a stale dist/ that no rebuild ever touched.
    assert 'type: "range"' in bundle and "MG_LORA" in bundle and "loraRange" in bundle, (
        "the Loom bundle is stale -- run `npm run build --prefix loom`")


def test_lora_weight_bounds_follow_the_base_architecture(tmp_path):
    """Owner-reported from the live site: DiT models take 0..1.2, the SD family -2..+2.

    There is no single correct range, which is why both earlier attempts were wrong in
    opposite directions -- a 0..2 spinner blocked the legal negatives SD allows, and a flat
    -2..2 slider offered DiT weights PixAI rejects. The table is served from core so the
    slider and the builder cannot drift apart.
    """
    assert core.lora_weight_range("DIT7B_MODEL") == (0.0, 1.2)
    assert core.lora_weight_range("MMDIT26A_MODEL") == (0.0, 1.2)
    assert core.lora_weight_range("DIT9_MODEL") == (0.0, 1.2)
    assert core.lora_weight_range("SDXL_MODEL") == (-2.0, 2.0)
    assert core.lora_weight_range("SD_V1_MODEL") == (-2.0, 2.0)
    # Unknown or not-yet-picked falls back to the WIDER range, not the narrower: an unknown
    # architecture must not silently remove a capability the account has, and a weight the
    # architecture refuses comes back as a refused submit, which costs nothing.
    assert core.lora_weight_range("") == (-2.0, 2.0)
    assert core.lora_weight_range("SOMETHING_NEW") == (-2.0, 2.0)

    # 2026-07-26: the table held five architectures when the enum has twenty-five members,
    # enumerated from PixAI's own bundle. Because an unrecognised architecture falls through to
    # the SD range, every missing DiT was being offered -2..+2 against a real ceiling of 1.2.
    #
    # DIT7_MODEL is the one that mattered: it is what their base-model picker actually SENDS for
    # "DiT.1" (measured off a live request), and only DIT7B_MODEL was listed, so the commonest
    # DiT case was very likely already wrong.
    assert core.lora_weight_range("DIT7_MODEL") == (0.0, 1.2)
    # DiT.3, which had no entry at all -- its token was unknown to this project until today.
    assert core.lora_weight_range("MMDIT26B_MODEL") == (0.0, 1.2)
    # A user-TRAINED DiT.2, which is what the owner's own LoRAs are.
    assert core.lora_weight_range("USER_DIT26A_MODEL") == (0.0, 1.2)
    for variant in ("DIT7A_MODEL", "DIT7C_MODEL", "DIT7D_MODEL"):
        assert core.lora_weight_range(variant) == (0.0, 1.2), variant

    # Every DiT-family member the table knows about must be 0..1.2. Guards the real failure mode:
    # someone adds a new DiT token to the browse whitelist and forgets the range, which is
    # silent -- it just widens a slider.
    for arch, rng in core.LORA_WEIGHT_RANGES.items():
        if "DIT" in arch:
            assert rng == (0.0, 1.2), "{} is a DiT architecture but ranges {}".format(arch, rng)
        else:
            assert rng == (-2.0, 2.0), "{} is not DiT but ranges {}".format(arch, rng)

    # DELIBERATELY unmapped: the owner's ranges covered DiT.1/DiT.2/Community DiT/SD1.5/SDXL and
    # said nothing about these two. They must keep falling through to the widest range rather
    # than being guessed at, since narrowing a slider on a guess removes a real capability.
    assert "SD3_MEDIUM_MODEL" not in core.LORA_WEIGHT_RANGES
    assert "Z_IMAGE_V1_MODEL" not in core.LORA_WEIGHT_RANGES
    assert core.lora_weight_range("SD3_MEDIUM_MODEL") == (-2.0, 2.0)


    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="1", filename="a_1.png", created_at="2025-01-01T00:00:00")])
    html = login_client(tmp_path).get("/").get_data(as_text=True)
    served = json.loads(html.split("window.MG_LORA=", 1)[1].split(";</script>", 1)[0])
    assert served["ranges"]["DIT7B_MODEL"] == [0.0, 1.2]
    assert served["ranges"]["SDXL_MODEL"] == [-2.0, 2.0]
    assert served["fallback"] == [-2.0, 2.0] and served["step"] == 0.1


def test_core_clamps_the_lora_weight_to_pixais_bounds():
    """The last place before the submit. A value outside PixAI's own range is a rejected
    generation, not a stronger effect, so it is clamped here the same way the upscale ratio
    is -- and NOT clamped at 0, which would silently discard a legal negative weight."""
    assert (core.LORA_WEIGHT_MIN, core.LORA_WEIGHT_MAX) == (-2.0, 2.0)
    m, lst = core._lora_params([("v1", -0.8), ("v2", 5), ("v3", -9), ("v4", "0.55")])
    assert m["v1"] == -0.8, "a legal negative weight was clamped away"
    assert m["v2"] == 2.0 and m["v3"] == -2.0, "out-of-range weights must clamp to the bounds"
    assert m["v4"] == 0.55
    assert {e["versionId"]: e["weight"] for e in lst} == m, "the two shapes disagree"


def test_drawer_no_longer_carries_the_ratio_cap_port():
    """The drawer's hand port of max_upscale_ratio existed ONLY to drive its ratio slider,
    and the slider is gone. It was also the wrong rule for this surface: the ceiling was
    inferred from PixAI's image-view DIALOG maxima, and a real booster task submitted
    upscale 1.5 on a 1400x784 source (2100x1176 -- over that inferred ceiling) and
    completed (task 2039053268124647852, 2026-07-28). The port still belongs to
    <UpscalePanel>, which has a real slider and a real source picture; that copy is
    covered by test_upscale_panel_ratio_cap_agrees_with_python. The React Create surface
    must not grow the port back either: it has no ratio UI, so it has no use for the
    ceiling table at all.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    for fname in ("gen/genCore.js", "gen/useGenerate.js", "components/CreateMobile.jsx"):
        src = (root / "gallery" / "src" / fname).read_text(encoding="utf-8")
        for gone in ("upCeil", "upMax(", "syncUpscale(", "MG_UPSCALE"):
            assert gone not in src, gone + " is in the generation surface (" + fname + ")"


def test_drawer_sends_pixais_own_booster_values():
    """Captured, not chosen. PixAI's Enhance Details booster exposes no controls, so their
    SERVER picks the values -- read off a real task (2039053268124647852, 2026-07-28):
    upscale 1.5, upscaleDenoisingStrength 0.6, and upscaleDenoisingSteps 32 alongside
    samplingSteps 32, i.e. the denoise steps MIRROR the generation's own steps rather than
    being a constant. Our old hardcoded 26 was a number nobody chose. The builder is
    genCore.js's buildPayload since the classic cut -- one function feeding BOTH
    /api/price and /api/generate.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    src = (root / "gallery" / "src" / "gen" / "genCore.js").read_text(encoding="utf-8")
    assert "export const MG_HIRES = { ratio: 1.5, denoise: 0.6 }" in src, \
        "PixAI's captured values are gone"
    assert "upscale: hires ? MG_HIRES.ratio : null" in src
    assert "upscale_denoise: hires ? MG_HIRES.denoise : null" in src
    # The denoise steps mirror the generation's own sampling steps (with the classic's
    # ||25 fallback applied to BOTH), not a constant.
    assert "upscale_denoise_steps: hires ? eff : null" in src, \
        "denoise steps must mirror the generation's sampling steps, not a constant"
    assert 'const eff = s.steps === "" ? STEPS_FALLBACK : Number(s.steps)' in src
    assert "export const STEPS_FALLBACK = 25" in src

def test_model_type_filter_mapping_is_measured_not_guessed():
    """Their Model Type filter maps a label to a GenerationModelType, and the ones that matter
    were read off live requests rather than inferred.

    Recorded because a wrong token here does not error -- `types` with an unrecognised member
    would simply return the wrong rows, or none, and look like an empty result.
    """
    m = dict(core.MODEL_TYPE_FILTERS)
    # Measured 2026-07-26 by driving their base-model picker and reading the request.
    assert m["All"] == "ANY_MODEL", "All sends ANY_MODEL; it does NOT omit the argument"
    assert m["DiT.3"] == "MMDIT26B_MODEL"
    assert m["DiT.2"] == "MMDIT26A_MODEL"
    assert m["DiT.1"] == "DIT7_MODEL", "their DiT.1 is DIT7_MODEL, not DIT7B_MODEL"
    # Every mapped token must be one this app is willing to send.
    for label, token in core.MODEL_TYPE_FILTERS:
        if token.startswith("ANY_"):
            continue
        assert token in core.LORA_BASE_MODEL_TYPES, \
            "{} maps to {}, which is not on the send whitelist".format(label, token)


def test_upscale_works_without_a_recorded_model(monkeypatch, tmp_path):
    """An image whose model the catalog never recorded must still be upscalable.

    PixAI's own upscale dialog has NO model control -- their submit sets a fixed modelId
    and takes prompts/width/height off the source's original task. This app invented the
    requirement, and it made every locally imported file (and anything predating a full
    meta sweep) impossible to upscale: Go stayed dead behind "pick a model first", and if
    the picker failed to render there was no way to satisfy it at all.

    The fallback is a model VERSION id, so it must travel as `version_id`. Sent as
    `model_id` it enters the model->versions lookup, matches nothing, and comes back
    "pick a model first" -- the very error it exists to prevent.
    """
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="u1", filename="u1.png", source="local",
                       created_at="2026-07-01T00:00:00", width="1959", height="1097")])
    seen = {}
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "submit_generation",
                        lambda _s, params: seen.setdefault("params", params) and "t1" or "t1")
    cli = login_client(tmp_path)
    r = cli.post("/api/generate", json={
        "version_id": core.UPSCALE_FALLBACK_VERSION_ID,
        "prompt": "x", "width": 1959, "height": 1097, "count": 1,
        "enlarge": 1.4, "enlarge_model": core.DEFAULT_ENLARGE_MODEL,
        "ref_media_id": "u1", "ref_strength": 0.55,
    })
    d = r.get_json()
    assert r.status_code == 200 and not d.get("error"), d
    assert seen["params"]["modelId"] == core.UPSCALE_FALLBACK_VERSION_ID
    assert seen["params"]["enlarge"] == 1.4


def test_upscale_panel_offers_the_fallback_instead_of_blocking():
    """The panel must not dead-disable Go when the catalog has no model, and the constant
    must be SERVED rather than retyped into the component."""
    root = pathlib.Path(__file__).resolve().parent.parent
    src = (root / "gallery" / "src" / "components" / "UpscalePanel.jsx").read_text(encoding="utf-8")
    # Go's disabled derives from goReady, which accepts the served fallback version -- so a
    # no-model image stays submittable, never dead-disabled. (2026-08-22: goReady is also what
    # the cost badge prices on -- ONE predicate, so a fallback-only picture is quoted rather
    # than offered a live button with no price beside it.)
    assert "(src && src.model_id) || fallbackVersion()" in src, \
        "the no-model case must still submit via the fallback, not dead-disable Go"
    assert "const canGo = goReady && probe.canSubmit;" in src, \
        "Go is the panel's own readiness AND a price settled for THIS payload"
    assert "idle: goReady ? null : true" in src, \
        "the badge must price whenever Go is possible -- one predicate, not two"
    assert "disabled={!canGo || busy}" in src
    assert core.UPSCALE_FALLBACK_VERSION_ID not in src, \
        "the id must come from window.MG_UPSCALE, not a second copy in the component"
    assert "fallbackVersion()" in src


def test_upscale_sends_the_images_model_as_a_version_id():
    """The catalog's model_id is the task's submitted `modelId`, which IS a model VERSION
    id -- so an upscale must send it as version_id.

    Sent as model_id it entered /api/generate's model->versions lookup, matched nothing,
    and came back "pick a model first" on a picture whose model the panel was displaying
    on screen. Only a model chosen in the PICKER is a real model id.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    src = (root / "gallery" / "src" / "components" / "UpscalePanel.jsx").read_text(encoding="utf-8")
    body = src[src.index("const payload = ()"):src.index("const build = useCallback(")]
    assert 'model_id: s.model_picked ? (s.model_id || "") : ""' in body, \
        "only a PICKED model may travel as model_id"
    assert 'version_id: s.model_picked ? "" : (s.model_id || fallbackVersion())' in body, \
        "the image's own model id is a version id and must travel as version_id"


def test_generate_rejects_a_version_id_sent_as_a_model_id(monkeypatch, tmp_path):
    """Pins the server behaviour the above exists to avoid, so the reason stays visible:
    a version id in the model_id field resolves to nothing and is refused."""
    save_catalog(tmp_path / "catalog.db",
                 [_row(media_id="u2", filename="u2.png", created_at="2026-07-01T00:00:00",
                       width="900", height="600")])
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "list_model_versions", lambda *a, **k: [])   # not a model id
    monkeypatch.setattr(core, "submit_generation", lambda *a, **k: "nope")
    cli = login_client(tmp_path)
    r = cli.post("/api/generate", json={
        "model_id": core.UPSCALE_FALLBACK_VERSION_ID, "prompt": "x",
        "width": 900, "height": 600, "count": 1, "ref_media_id": "u2",
    })
    assert r.status_code == 400 and "pick a model first" in (r.get_json() or {}).get("error", "")


# --- per-model booster gating ------------------------------------------------

def test_enhance_details_is_gated_on_the_model_declaring_upscale_support():
    """PixAI's own Add Booster menu omits Enhance Details on a DiT model (measured
    2026-07-28 on Tsubaki.2, whose extra.compatibility carries `upscale:false`), and offers
    it on SDXL. Our drawer used to show all three boosters on every model, so it would send
    the `upscale` family to a model that rejects it -- the image-side twin of the V3.0 Lite
    video bug, where an unsupported flag came back as a bogus NSFW refusal.

    The gate reads the same field PixAI does, through the existing capability path, and
    fails OPEN: only an explicit false disables anything, so a never-probed model is
    unchanged. Since the classic cut it lives in the React gen hook/builder.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    use = (root / "gallery" / "src" / "gen" / "useGenerate.js").read_text(encoding="utf-8")
    # PixAI's own field, read through the one capability accessor...
    assert 'compat_upscale: cget(v, "upscale")' in use, \
        "Enhance Details must gate on compatibility.upscale, not on an architecture guess"
    # ...which fails OPEN: absent key -> undefined -> unknown, and every gate below
    # compares `=== false`, so only an explicit false disables anything.
    assert "return key in c ? c[key] : undefined" in use, \
        "the capability accessor must fail OPEN on unknown data"
    # A booster armed before the model changed underneath it must be disarmed, or the
    # payload would still carry a ratio the new model cannot use -- on BOTH paths a
    # version can change (model pick and manual version switch).
    assert use.count("model.compat_upscale === false") >= 2, \
        "switching to an incompatible model/version must disarm the armed chip"
    assert use.count("hires: false") >= 2
    core_js = (root / "gallery" / "src" / "gen" / "genCore.js").read_text(encoding="utf-8")
    # Belt-and-braces at the payload itself, same explicit-false-only rule.
    assert "s.boosters.hires && !(s.model && s.model.compat_upscale === false)" in core_js
    jsx = (root / "gallery" / "src" / "components" / "CreateMobile.jsx").read_text(encoding="utf-8")
    assert "disabled={m && m.compat_upscale === false}" in jsx, \
        "the Enhance Details chip itself must disable on an explicit upscale:false"


def test_booster_gate_does_not_touch_quality_tag_or_face_fix():
    """Quality Tag is a MEMBERSHIP question (PixAI crowns it) and Face Fix has no
    compatibility key at all -- neither is decided by extra.compatibility, so neither is
    gated here. Pinned so a later pass doesn't quietly extend the capability gate over a
    product decision the owner has not made.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    jsx = (root / "gallery" / "src" / "components" / "CreateMobile.jsx").read_text(encoding="utf-8")
    row = jsx.split('<div className="cm-lbl">Boosters</div>')[1].split("Prompt helper")[0]
    chips = row.split("<button")
    face = next(c for c in chips if "Face Fix" in c)
    qual = next(c for c in chips if "Quality Tag" in c)
    assert "disabled" not in face and "compat" not in face, \
        "Face Fix has no compatibility flag to gate on"
    assert "disabled" not in qual and "compat" not in qual, \
        "Quality Tag gating is an owner decision"
    # ...and the disarm-on-model-change patch touches hires only.
    use = (root / "gallery" / "src" / "gen" / "useGenerate.js").read_text(encoding="utf-8")
    assert "face: false" not in use and "quality: false" not in use, \
        "the capability gate must not disarm Face Fix or Quality Tag"
