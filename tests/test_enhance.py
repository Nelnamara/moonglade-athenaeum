"""Enhance: PixAI art filters, and the guards that keep the dead panelplugin-workflow
surface deleted. Builders pinned to REAL captured submits (2026-07-02). Pure/mocked -- no
network, no spend."""
from types import SimpleNamespace

import pixai_gallery_backup as core
import pixai_gallery


# ---- art filter (pixai-image-filter) ----

def test_filter_matches_real_submit():
    p = core.build_filter_parameters("739361299672561699", "filter-v1-m2", strength=0.77)
    assert p["model"] == "pixai-image-filter"
    assert p["mediaId"] == "739361299672561699"
    assert p["inputs"] == {"filterId": "filter-v1-m2", "strength": 0.77}
    assert p["enablePreview"] is False


def test_enhance_kaisuuken_inject():
    assert core.build_filter_parameters("1", "f", kaisuuken_id="c")["kaisuukenId"] == "c"


# ---- run_enhance guards ----

def _enh_args(tmp_path, **kw):
    base = dict(out=str(tmp_path), token=None, enhance=True, src="100",
                filter_id="filter-v1-m2", params_json="", strength=0.5, kaisuuken_id="",
                confirm=False, task_id="", poll_timeout=300, name_length=60, name_sep="_",
                dump_params=False)
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
        core.run_enhance(_enh_args(tmp_path, filter_id=""))


def test_enhance_filter_preview_uses_filter(tmp_path, capsys):
    core.run_enhance(_enh_args(tmp_path, filter_id="filter-v1-m2"))
    out = capsys.readouterr().out
    assert "pixai-image-filter" in out and "filter-v1-m2" in out


# ---- the panelplugin surface is gone and must stay gone ----

def test_no_panelplugin_submit_path_survives():
    """PixAI never assigns a worker to a `pixai-panelplugin` task submitted by an API-key
    client. It accepts the submit, queues it, charges for it, then cancels it at roughly 60
    minutes with outputs.reason "waiting timeout" and refunds. Measured 2026-07-24 and proven
    by elimination: the identical payload built with PixAI's OWN official preset workflow id
    also never dispatches, while their web client runs that same workflow in 1-3 seconds, and
    a taskKind=chat Fix submitted from this app minutes earlier dispatched in one second. So
    the workflow id, the input keys and the payload shape are all irrelevant -- no panelplugin
    submit from an API key can ever complete, and there is nothing to repair.

    The whole Enhance workflow surface (ten one-click cards, the ComfyUI catalog search,
    /api/enhance, /api/workflows, build_panelplugin_parameters, workflow_catalog,
    --workflow-id) was therefore deleted rather than fixed. This guard exists because that
    surface LOOKS correct from the client side -- it accepts, queues and reports a price -- and
    costs an hour of wall-clock per attempt to disprove."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    # The two literals a submit path cannot do without: the model id and the parameter that
    # names the workflow. Both are absent from the modules -- the word "panelplugin" on its own
    # still appears in the comments that explain WHY, which is the point of leaving them.
    for mod in ("pixai_gallery.py", "pixai_gallery_backup.py"):
        src = (root / mod).read_text(encoding="utf-8")
        assert "pixai-panelplugin" not in src, mod + " still names the panelplugin model"
        assert "workflowId" not in src, mod + " still addresses a panelplugin workflow"
    core_src = (root / "pixai_gallery_backup.py").read_text(encoding="utf-8")
    assert '"--workflow-id"' not in core_src        # the CLI flag that fed it
    assert not hasattr(core, "build_panelplugin_parameters")
    assert not hasattr(core, "workflow_catalog")


def test_no_route_reaches_a_panelplugin_submit(tmp_path):
    """The route-level half of the guard above: neither the submit route nor the catalog
    route that populated its picker may exist, so no reachable request can queue a task
    PixAI will never run."""
    app = pixai_gallery.create_app(tmp_path)
    rules = {str(r.rule) for r in app.url_map.iter_rules()}
    assert "/api/enhance" not in rules
    assert "/api/workflows" not in rules


def test_enhance_plugins_dict_and_dead_plugin_branch_are_gone():
    """ENHANCE_PLUGINS ("detail-fix"/"hand-fix"/"face-fix") had zero production callers: the
    Edit tab's Enhance UI never sent a `plugin` key, so the dict and the route's `elif plug:`
    branch that read it were unreachable dead code (audit: sweep-bcd, orphaned, 2026-07-21).
    The route itself is gone now too, which makes that branch unreachable twice over -- this
    still guards the plugin-name shortcut specifically, so a future refinement surface cannot
    resurrect it as a way back into a panelplugin submit. hand-fix and face-fix are superseded
    by the real, working box-based /api/fix (submit_fixer)."""
    from pathlib import Path
    assert not hasattr(pixai_gallery, "ENHANCE_PLUGINS")
    src = (Path(__file__).resolve().parents[1] / "pixai_gallery.py").read_text(encoding="utf-8")
    assert "ENHANCE_PLUGINS" not in src
    assert 'p.get("plugin")' not in src
