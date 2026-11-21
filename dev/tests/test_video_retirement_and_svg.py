"""V3.2 video retirement (PixAI, 2026-11-23 03:00 UTC) and SVG results saved as .svg.

The clock is injected: every check names an instant on one side of the cut rather than reading
today's date, so this file means the same thing before and after 23 Nov 2026."""
import datetime
from pathlib import Path

import pytest

from moonglade import backup as core
from moonglade import gallery as g
from moonglade import gen_params as gen_params_mod
from moonglade import gen_road as gen_road_mod
from moonglade import integrity
from moonglade import scan
from moonglade import thumbs as thumbs_mod
from moonglade import media_fetch as media_fetch_mod

UTC = datetime.timezone.utc
CUT = datetime.datetime(2026, 11, 23, 3, 0, 0, tzinfo=UTC)
BEFORE = CUT - datetime.timedelta(seconds=1)


class _Session:
    """A session that fails the test on ANY use: a refused submit must never touch it."""
    calls = 0

    def __getattr__(self, name):
        _Session.calls += 1
        raise AssertionError("the session was used: " + name)


@pytest.fixture()
def after_cut(monkeypatch):
    monkeypatch.setattr(gen_params_mod, "_video_clock", lambda: CUT)


@pytest.fixture()
def before_cut(monkeypatch):
    monkeypatch.setattr(gen_params_mod, "_video_clock", lambda: BEFORE)


def test_retired_table_names_the_announced_instant():
    assert gen_params_mod.VIDEO_MODEL_RETIRED == {"v3.2": "2026-11-23T03:00:00Z"}
    assert "v3.2" in gen_params_mod.VIDEO_MODELS            # the label map stays: old videos keep "V3.2"
    assert gen_params_mod.VIDEO_MODELS["v3.2"]["label"] == "V3.2"


def test_retired_flips_at_the_instant_not_before():
    assert not gen_params_mod.video_model_retired("v3.2", BEFORE)
    assert gen_params_mod.video_model_retired("v3.2", CUT)
    assert not gen_params_mod.video_model_retired("v4.0.1", CUT + datetime.timedelta(days=400))
    assert not gen_params_mod.video_model_retired("", CUT)


def test_nothing_changes_before_the_cut(before_cut):
    p = gen_params_mod.build_video_parameters("a", "123", model="v3.2")
    assert p["i2vPro"]["model"] == "v3.2"
    gen_params_mod.check_video_model_retired("v3.2")                     # no raise
    gen_params_mod._params_video_models(p)


def test_builder_refuses_after_the_cut(after_cut):
    with pytest.raises(core.PixAIError) as e:
        gen_params_mod.build_video_parameters("a", "123", model="v3.2")
    assert "retired by PixAI on 23 Nov" in str(e.value)
    assert "nothing was created or charged" in str(e.value)


def test_submit_refuses_before_any_network_call(after_cut, monkeypatch):
    """The refusal sits ahead of the session: no mirror lookup, no HTTP, no spend."""
    monkeypatch.setattr(core, "_check_read_only", lambda *a, **k: None)
    params = {"i2vPro": {"model": "v3.2", "mediaId": "1"}}
    _Session.calls = 0
    with pytest.raises(core.PixAIError, match="retired by PixAI"):
        gen_road_mod.submit_generation(_Session(), params)
    assert _Session.calls == 0


def test_submit_refuses_a_reference_video_naming_it(after_cut, monkeypatch):
    monkeypatch.setattr(core, "_check_read_only", lambda *a, **k: None)
    with pytest.raises(core.PixAIError, match="retired by PixAI"):
        gen_road_mod.submit_generation(_Session(), {"referenceVideo": {"model": "v3.2"}})


def test_submit_of_another_engine_is_not_refused_by_the_gate(after_cut, monkeypatch):
    """The gate looks only at a retired engine; v4.0.1 goes on to the (stubbed) next step."""
    monkeypatch.setattr(core, "_check_read_only", lambda *a, **k: None)

    class Reached(Exception):
        pass

    def _boom(*a, **k):
        raise Reached()

    monkeypatch.setattr(gen_road_mod, "is_lane_request", _boom)
    with pytest.raises(Reached):
        gen_road_mod.submit_generation(_Session(), {"i2vPro": {"model": "v4.0.1"}})


def test_front_end_mirror_matches_server_table():
    src = (Path(__file__).resolve().parents[2] / "gallery" / "src" / "gen" / "videoDrawerCore.js"
           ).read_text(encoding="utf-8")
    for name, when in gen_params_mod.VIDEO_MODEL_RETIRED.items():
        assert 'VIDEO_MODEL_RETIRED = { "%s": "%s" }' % (name, when) in src


# ---- SVG -------------------------------------------------------------------------------------

def test_ext_from_ct_maps_svg():
    assert media_fetch_mod.ext_from_ct("image/svg+xml") == ".svg"
    assert media_fetch_mod.ext_from_ct("IMAGE/SVG+XML; charset=utf-8") == ".svg"
    assert media_fetch_mod.ext_from_ct("image/png") == ".png"        # the others are untouched
    assert media_fetch_mod.ext_from_ct("image/gif") == ".gif"


_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"><rect width="8" height="8"/></svg>'


def test_a_svg_in_the_library_is_catalogued_and_nothing_raises(tmp_path):
    img = tmp_path / "images"
    img.mkdir()
    f = img / "123456789.svg"
    f.write_bytes(_SVG)
    # the scan sees it (kept and catalogued) ...
    found = [e.path.name for e in scan.scan_library(tmp_path)]
    assert "123456789.svg" in found
    assert scan.find_files_for_media_id(tmp_path, "123456789")
    # ... and every Pillow-backed walker answers "no" instead of raising
    thumb = tmp_path / "gallery" / "thumbs" / "123456789.jpg"
    assert thumbs_mod.make_thumbnail(f, thumb) is False
    assert not thumb.exists()
    assert thumbs_mod.compute_dhash(f) is None
    assert media_fetch_mod.embed_metadata(f, {"prompt": "x"}) == "unsupported"
    assert integrity.structural_problem(f) is None
    assert f.read_bytes() == _SVG                          # kept, untouched
