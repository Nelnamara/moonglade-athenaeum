"""Enhance: PixAI panelplugin workflows (face fix / upscale / bg-remove) + art filters.
Builders pinned to REAL captured submits (2026-07-02). Pure/mocked -- no network, no spend."""
from types import SimpleNamespace

import pixai_gallery_backup as core


# ---- panelplugin workflow (pixai-panelplugin) ----

def test_panelplugin_matches_real_submit():
    p = core.build_panelplugin_parameters("739361299672561699", "1797414829336369706", strength=0.5)
    assert p["model"] == "pixai-panelplugin"
    assert p["workflowId"] == "1797414829336369706"
    assert p["inputs"]["image"] == {"type": "media", "media_id": "739361299672561699"}
    assert p["inputs"]["strength"] == 0.5
    assert p["enablePreview"] is True and p["isPrivate"] is False


def test_panelplugin_omits_strength_when_none():
    assert "strength" not in core.build_panelplugin_parameters("1", "wf")["inputs"]


# ---- art filter (pixai-image-filter) ----

def test_filter_matches_real_submit():
    p = core.build_filter_parameters("739361299672561699", "filter-v1-m2", strength=0.77)
    assert p["model"] == "pixai-image-filter"
    assert p["mediaId"] == "739361299672561699"
    assert p["inputs"] == {"filterId": "filter-v1-m2", "strength": 0.77}
    assert p["enablePreview"] is False


def test_enhance_kaisuuken_inject():
    assert core.build_panelplugin_parameters("1", "wf", kaisuuken_id="c")["kaisuukenId"] == "c"
    assert core.build_filter_parameters("1", "f", kaisuuken_id="c")["kaisuukenId"] == "c"


# ---- run_enhance guards ----

def _enh_args(tmp_path, **kw):
    base = dict(out=str(tmp_path), token=None, enhance=True, src="100", workflow_id="wf9",
                filter_id="", params_json="", strength=0.5, kaisuuken_id="", confirm=False,
                task_id="", poll_timeout=300, name_length=60, name_sep="_", dump_params=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_enhance_previews_without_confirm(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "gql_adhoc",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network in preview")))
    monkeypatch.setattr(core, "upload_media",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no upload in preview")))
    assert core.run_enhance(_enh_args(tmp_path)) == {"submitted": False}


def test_enhance_requires_src_and_id(tmp_path):
    import pytest
    with pytest.raises(core.PixAIError):
        core.run_enhance(_enh_args(tmp_path, src=""))
    with pytest.raises(core.PixAIError):
        core.run_enhance(_enh_args(tmp_path, workflow_id="", filter_id=""))


def test_enhance_filter_preview_uses_filter(tmp_path, capsys):
    core.run_enhance(_enh_args(tmp_path, workflow_id="", filter_id="filter-v1-m2"))
    out = capsys.readouterr().out
    assert "pixai-image-filter" in out and "filter-v1-m2" in out
