"""Enhance: the guards that keep two deleted PixAI submit families deleted -- the panelplugin
workflows PixAI never dispatches for an API-key client, and the art-filter generation that
charged credits for something the browser composites itself. Pure/mocked -- no network,
no spend."""
from pathlib import Path

import pytest

import moonglade_backup as core
import moonglade_gallery

ROOT = Path(__file__).resolve().parents[1]


# ---- art filters are not a generation, and can no longer be submitted as one ----

def test_no_art_filter_submit_path_survives():
    """PixAI's 7 art filters are gradient-overlay composites, not inference. Their whole
    definition -- two or three linear gradients with a blend mode, an opacity and an optional
    brightness/contrast/saturation trim -- comes from a PUBLIC unauthenticated config endpoint
    (GET https://api.pixai.art/config/imageArtFilters, 200 with no key), and PixAI's own web
    client applies them in the browser: their Filters tab shows source and result side by side,
    with no Generate button and no price anywhere on it.

    build_filter_parameters and --filter-id sent that to createGenerationTask as a
    `pixai-image-filter` task, which charged credits and waited on a worker queue to perform a
    handful of gradient fills -- strictly worse than static/mg-art-filters.js, which does the
    same composite locally, offline and free. So the paid path is removed rather than left as a
    second, worse option a user could pick by accident.

    Asserted against the SOURCE as well as the module namespace: a builder that survives under
    another name, or a stray `pixai-image-filter` model literal, is the same defect back."""
    assert not hasattr(core, "build_filter_parameters")
    for mod in ("moonglade_gallery.py", "moonglade_backup.py"):
        src = (ROOT / mod).read_text(encoding="utf-8")
        assert "pixai-image-filter" not in src, mod + " still names the paid filter model"
        assert "filterId" not in src, mod + " still builds a filter task's inputs"


def test_the_enhance_command_is_gone_from_the_cli(monkeypatch, capsys):
    """--enhance had exactly two halves and both are now gone: panelplugin workflows (which
    PixAI never runs for an API-key client) and art filters (which cost nothing locally). A
    command with no builder left is not a command, so the flag, its three companions and
    run_enhance itself were removed rather than kept as an entry point to nothing.

    Driven through main()'s real parser rather than asserted against the source, because the
    property that matters is that the CLI does not ACCEPT these -- a leftover add_argument keeps
    a flag accepted no matter what the source around run_enhance looks like. main() is pure
    argparse up to parse_args(), so no command runs and no network is touched."""
    assert not hasattr(core, "run_enhance")
    monkeypatch.setattr("sys.argv", ["moonglade_backup.py", "--enhance", "--src", "1",
                                     "--filter-id", "filter-v1-m2", "--strength", "0.77"])
    with pytest.raises(SystemExit) as ex:
        core.main()
    assert ex.value.code != 0
    err = capsys.readouterr().err
    assert "unrecognized arguments" in err
    # argparse lists every argument it did not recognise, so checking all four means one
    # surviving flag cannot hide behind its neighbours failing.
    for flag in ("--enhance", "--src", "--filter-id", "--strength"):
        assert flag in err, flag + " is still accepted by the parser"


def test_the_local_filter_module_ships_with_the_recipes_baked_in():
    """The replacement has to work with no connection -- offline is a property of the whole
    app, not a nicety -- so the 7 recipes are baked into the module rather than fetched, and it
    makes no request of any kind. The engine's behaviour is exercised for real in
    loom/test/mg-art-filters.test.js; this pins the Python-side fact that the module the
    React build imports exists and is self-contained. (Ported out of static/mg-art-filters.js
    into gallery/src/art/artFilters.js on 2026-08-08, the vanilla static/ -> React campaign.)"""
    js = (ROOT / "gallery" / "src" / "art" / "artFilters.js").read_text(encoding="utf-8")
    assert "api.pixai.art/config/imageArtFilters" in js      # names where the data came from
    for fid in ("filter-v1-m1", "filter-v1-m4", "filter-v1-m7"):
        assert fid in js, fid + " is not baked in"
    assert "fetch(" not in js, "applying a filter must cost nothing and reach no network"


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
    # The two literals a submit path cannot do without: the model id and the parameter that
    # names the workflow. Both are absent from the modules -- the word "panelplugin" on its own
    # still appears in the comments that explain WHY, which is the point of leaving them.
    for mod in ("moonglade_gallery.py", "moonglade_backup.py"):
        src = (ROOT / mod).read_text(encoding="utf-8")
        assert "pixai-panelplugin" not in src, mod + " still names the panelplugin model"
        assert "workflowId" not in src, mod + " still addresses a panelplugin workflow"
    core_src = (ROOT / "moonglade_backup.py").read_text(encoding="utf-8")
    assert '"--workflow-id"' not in core_src        # the CLI flag that fed it
    assert not hasattr(core, "build_panelplugin_parameters")
    assert not hasattr(core, "workflow_catalog")


def test_no_route_reaches_a_panelplugin_or_filter_submit(tmp_path):
    """The route-level half of the guards above: neither the submit route nor the catalog route
    that populated its picker may exist, so no reachable request can queue a task PixAI will
    never run -- or pay for a composite the browser does for free."""
    app = moonglade_gallery.create_app(tmp_path)
    rules = {str(r.rule) for r in app.url_map.iter_rules()}
    assert "/api/enhance" not in rules
    assert "/api/workflows" not in rules
    # The filters panel saves its result through the existing local-import path rather than a
    # route of its own, so that one DOES have to be reachable for "Save to library" to work.
    assert "/api/import-local" in rules


def test_enhance_plugins_dict_and_dead_plugin_branch_are_gone():
    """ENHANCE_PLUGINS ("detail-fix"/"hand-fix"/"face-fix") had zero production callers: the
    Edit tab's Enhance UI never sent a `plugin` key, so the dict and the route's `elif plug:`
    branch that read it were unreachable dead code (audit: sweep-bcd, orphaned, 2026-07-21).
    The route itself is gone now too, which makes that branch unreachable twice over -- this
    still guards the plugin-name shortcut specifically, so a future refinement surface cannot
    resurrect it as a way back into a panelplugin submit. hand-fix and face-fix are superseded
    by the real, working box-based /api/fix (submit_fixer)."""
    assert not hasattr(moonglade_gallery, "ENHANCE_PLUGINS")
    src = (ROOT / "moonglade_gallery.py").read_text(encoding="utf-8")
    assert "ENHANCE_PLUGINS" not in src
    assert 'p.get("plugin")' not in src
