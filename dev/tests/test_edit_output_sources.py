"""The source rules for Edit Pro's SVG and GIF outputs, as PixAI's own (`task-Bjykk1Ur.js`,
DESIGN_3.22 1.6 and 5.3, step S5): an SVG takes no image tool, no use-as-base and no edit; a
GIF may be read for a prompt (and upscaled or varied on PixAI's site) but is never an edit
source, a video frame or a base. Refused HERE, by the catalog's recorded format and then the
file's extension, before any upload or network call: in build_request, the gallery routes
that take a source outside it, the CLI runners and the Loom's shot route. Mutation target 19's
source half. Nothing here touches the network.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from moonglade import backup as core
from moonglade import gen_cli
from moonglade import gen_params
from moonglade import gen_road


@pytest.fixture(autouse=True)
def _writable(monkeypatch):
    monkeypatch.setattr(core, "READ_ONLY", False)
    monkeypatch.setattr(core, "_read_only_now", lambda: False)


# ---------------------------------------------------------------------------
# The pure rules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value, row, want", [
    ("55", {"output_format": "svg", "filename": "images/a_55.png"}, "svg"),
    ("55", {"output_format": "", "filename": "images/a_55.GIF"}, "gif"),
    ("55", {"output_format": "gif", "filename": "images/a_55.svg"}, "gif"),   # recorded first
    ("55", {"output_format": "", "filename": "images/a_55.png"}, ""),
    ("55", None, ""),
    ("C:/pics/logo.svg", None, "svg"),
    ("anim.gif", None, "gif"),
    ("photo.png", None, ""),
    ("data:image/svg+xml;base64,PHN2Zz4=", None, "svg"),
    ("data:image/gif;base64,R0lGOD", None, "gif"),
    ("data:image/png;base64,iVBOR", None, ""),
    ("", None, ""),
])
def test_the_format_comes_from_the_catalog_then_the_extension(value, row, want):
    assert gen_params.source_format(value, row) == want


@pytest.mark.parametrize("use", gen_params.SOURCE_USES)
def test_an_svg_is_never_a_source(use):
    assert gen_params.source_refusal("svg", use)
    with pytest.raises(core.LocalRefusal, match="An SVG can't be"):
        gen_params.refuse_unusable_source("svg", use)


@pytest.mark.parametrize("use, refused", [("edit", True), ("video", True), ("base", True),
                                          ("tool", True), ("prompt", False)])
def test_a_gif_is_read_for_a_prompt_and_nothing_else_here(use, refused):
    assert bool(gen_params.source_refusal("gif", use)) is refused


def test_every_other_picture_is_a_source():
    for use in gen_params.SOURCE_USES:
        assert gen_params.source_refusal("", use) is None
        assert gen_params.source_refusal("png", use) is None


# ---------------------------------------------------------------------------
# build_request: every road refuses before its media resolver (the upload) runs
# ---------------------------------------------------------------------------

FORMATS = {"901": "svg", "902": "gif"}


def _rs():
    return gen_road.RequestResolver(
        source_format=lambda v: FORMATS.get(str(v), ""),
        media_id=lambda v: pytest.fail("uploaded {}".format(v)))


@pytest.mark.parametrize("bad", ["901", "902"])
@pytest.mark.parametrize("mode, payload", [
    ("edit", lambda b: {"source": b, "instruction": "night"}),
    ("edit", lambda b: {"source": "11", "sources": ["11", b], "instruction": "night"}),
    ("fix", lambda b: {"source": b, "boxes": [{"x": 1, "y": 1, "width": 9, "height": 9,
                                               "tag": "hand"}]}),
    ("enhance", lambda b: {"source": b, "workflow_name": "mymusise/39a2c67c:x"}),
    ("video", lambda b: {"mode": "I2V", "images": [b], "prompt": "go"}),
    ("video", lambda b: {"mode": "R2V", "images": ["11", b], "prompt": "@image1"}),
    ("image", lambda b: {"prompt": "x", "version_id": "1", "ref_media_id": b}),
    ("image", lambda b: {"prompt": "x", "version_id": "1", "ref_media_id": b, "enlarge": 2}),
    ("image", lambda b: {"prompt": "x @image1", "version_id": "1", "context_images": [b]}),
])
def test_build_request_refuses_an_svg_or_gif_source_before_any_upload(mode, payload, bad):
    with pytest.raises(core.LocalRefusal, match="can't be"):
        gen_road.build_request(payload(bad), mode=mode, resolve=_rs())


def test_a_plain_source_still_builds():
    rs = gen_road.RequestResolver(source_format=lambda v: "", media_id=lambda v: "U" + v)
    req = gen_road.build_request({"source": "11", "instruction": "night"}, mode="edit",
                                 resolve=rs)
    assert req.parameters["chat"]["mediaIds"] == ["U11"]


# ---------------------------------------------------------------------------
# The gallery: its catalog lookup, the scene and suggest-prompt routes, the Loom's shot route
# ---------------------------------------------------------------------------

@pytest.fixture
def app(tmp_path, monkeypatch):
    from moonglade import gallery as g
    from tests.conftest import login_test_client
    blank = {f: "" for f in g.CATALOG_FIELDS}
    g.save_catalog(tmp_path / "catalog.db", [
        dict(blank, media_id="71", filename="images/logo_71.svg"),
        dict(blank, media_id="72", filename="images/anim_72.png", output_format="gif"),
        dict(blank, media_id="73", filename="images/plain_73.png")])
    sent = []
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "upload_media", lambda *a, **k: pytest.fail("uploaded"))
    monkeypatch.setattr(gen_road, "submit",
                        lambda s, req, **k: sent.append(req) or {"task_id": "t1"})
    monkeypatch.setattr(core, "suggest_prompt", lambda s, mid: sent.append(mid) or ["a tag"])
    return SimpleNamespace(cli=login_test_client(g.create_app(tmp_path)), sent=sent)


@pytest.mark.parametrize("mid", ["71", "72"])
def test_the_edit_route_refuses_by_the_catalogs_format(app, mid):
    out = app.cli.post("/api/edit", json={"mode": "edit", "source": mid,
                                          "instruction": "night"}).get_json()
    assert "can't be edited" in json.dumps(out)
    assert app.sent == []
    priced = app.cli.post("/api/price", json={"mode": "edit", "source": mid,
                                              "instruction": "night"}).get_json()
    assert priced.get("cost") is None and "can't be edited" in json.dumps(priced)


def test_suggest_prompt_refuses_an_svg_and_reads_a_gif(app):
    out = app.cli.get("/api/suggest-prompt?media_id=71").get_json()
    assert "An SVG can't be read for a prompt" in out.get("error", "")
    assert app.sent == []
    assert app.cli.get("/api/suggest-prompt?media_id=72").get_json()["suggestions"] == ["a tag"]
    assert app.sent == ["72"]


@pytest.mark.parametrize("img", ["71", "72", "data:image/svg+xml;base64,PHN2Zz4=",
                                 "data:image/gif;base64,R0lGODlh"])
def test_the_loom_shot_route_refuses_before_any_upload(app, monkeypatch, img):
    out = app.cli.post("/api/loom/generate", json={"mode": "I2V", "images": [img],
                                                   "prompt": "go"}).get_json()
    assert "can't be a video frame" in json.dumps(out)
    assert app.sent == []


def test_the_scene_route_refuses_before_any_upload(app, monkeypatch):
    from moonglade import mirror as mirror_mod
    monkeypatch.setattr(mirror_mod, "mirror_enabled", lambda: True)
    monkeypatch.setattr(mirror_mod, "make_mirror_session", lambda *a, **k: object())
    monkeypatch.setattr(gen_road, "submit_scene", lambda *a, **k: pytest.fail("sent a scene"))
    out = app.cli.post("/api/scene", json={"scene_id": "character-card",
                                           "media_ids": ["72"]}).get_json()
    assert "A GIF can't be used with an AI tool" in json.dumps(out)


# ---------------------------------------------------------------------------
# The CLI runners: by the catalog under --out, else the local file's extension
# ---------------------------------------------------------------------------

@pytest.fixture
def library(tmp_path, monkeypatch):
    from moonglade import gallery as g
    blank = {f: "" for f in g.CATALOG_FIELDS}
    g.save_catalog(tmp_path / "catalog.db", [
        dict(blank, media_id="81", filename="images/a_81.svg"),
        dict(blank, media_id="82", filename="images/a_82.png", output_format="gif")])
    (tmp_path / "logo.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "anim.gif").write_bytes(b"GIF89a")
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: pytest.fail("made a session"))
    monkeypatch.setattr(core, "upload_media", lambda *a, **k: pytest.fail("uploaded"))
    return tmp_path


def _args(lib, confirm, **kw):
    base = dict(out=str(lib), confirm=confirm, task_id="", token=None, prompt="go",
                params_json="", edit_src=[], edit_model="", edit_resolution="",
                edit_aspect="", edit_quality="", kaisuuken_id="", no_card=True, image="",
                tail="", ref_image=[], ref_video=[], ref_audio=[], video_model="",
                vchannel="private", video_ratio="")
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("confirm", [False, True])
@pytest.mark.parametrize("runner, kw, words", [
    (gen_cli.run_edit_image, lambda lib: dict(edit_src=["81"]), "An SVG can't be edited"),
    (gen_cli.run_edit_image, lambda lib: dict(edit_src=[str(lib / "anim.gif")]),
     "A GIF can't be edited"),
    (gen_cli.run_edit_image, lambda lib: dict(params_json=json.dumps(
        gen_params.build_chat_edit_parameters("x", ["82"]))), "A GIF can't be edited"),
    (gen_cli.run_generate_video, lambda lib: dict(image="82"), "A GIF can't be a video frame"),
    (gen_cli.run_generate_video, lambda lib: dict(image="73", tail="81"),
     "An SVG can't be a video frame"),
    (gen_cli.run_reference_video, lambda lib: dict(ref_image=[str(lib / "logo.svg")]),
     "An SVG can't be a video frame"),
])
def test_each_cli_runner_refuses_before_any_upload(library, runner, kw, words, confirm):
    with pytest.raises(core.LocalRefusal, match=words):
        runner(_args(library, confirm, **kw(library)))


def test_the_cli_suggest_prompt_refuses_an_svg_file(library):
    with pytest.raises(core.LocalRefusal, match="An SVG can't be read for a prompt"):
        core.run_suggest_prompt(SimpleNamespace(suggest_prompt=str(library / "logo.svg"),
                                                out=str(library), token=None))
    with pytest.raises(core.LocalRefusal, match="An SVG can't be read"):
        core.run_suggest_prompt(SimpleNamespace(suggest_prompt="81", out=str(library),
                                                token=None))
