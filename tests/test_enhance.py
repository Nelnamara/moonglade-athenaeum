"""Enhance: PixAI panelplugin workflows (face fix / upscale / bg-remove) + art filters.
Builders pinned to REAL captured submits (2026-07-02). Pure/mocked -- no network, no spend."""
from types import SimpleNamespace

import pixai_gallery_backup as core
import pixai_gallery


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


def test_panelplugin_by_workflow_name():
    p = core.build_panelplugin_parameters("M", workflow_name="mymusise/hand-fix")
    assert p["workflowName"] == "mymusise/hand-fix" and "workflowId" not in p
    assert p["model"] == "pixai-panelplugin"
    assert p["inputs"]["image"] == {"type": "media", "media_id": "M"}


def test_panelplugin_needs_a_workflow():
    import pytest
    with pytest.raises(core.PixAIError):
        core.build_panelplugin_parameters("M")


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


def test_enhance_plugins_dict_and_dead_plugin_branch_are_gone():
    """ENHANCE_PLUGINS ("detail-fix"/"hand-fix"/"face-fix") had zero production callers --
    the Edit tab's Enhance UI only ever sends workflow_id (runTask('/api/enhance',
    {source:src, workflow_id:wid}, ...)), never plugin, so the dict and the route's
    `elif plug:` branch that read it were unreachable dead code (audit: sweep-bcd,
    orphaned, 2026-07-21). hand-fix/face-fix are superseded by the real, working
    box-based /api/fix (submit_fixer); detail-fix's workflow is reachable the normal
    way, through the same workflow_id path every other Enhance workflow uses."""
    from pathlib import Path
    assert not hasattr(pixai_gallery, "ENHANCE_PLUGINS")
    src = (Path(__file__).resolve().parents[1] / "pixai_gallery.py").read_text(encoding="utf-8")
    assert "ENHANCE_PLUGINS" not in src
    assert 'p.get("plugin")' not in src
