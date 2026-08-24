"""Enhance: the guards around two PixAI submit families. The panelplugin/Enhance surface is
RESTORED as the mirror-gated Bridge tier (drift §44 / SCOPE §3) -- these tests pin that it
refuses with the mirror off, that its telemetry defers to terminal success, and that its output
files with correct lineage. The art-filter generation stays deleted (the browser composites it
for free). All pure/mocked -- no network, no spend (submit is always mocked)."""
from pathlib import Path

import pytest

import moonglade_backup as core
import moonglade_gallery

from tests.conftest import login_client

ROOT = Path(__file__).resolve().parents[1]


def _enhance_client(tmp_path):
    """A logged-in client over an empty catalog -- the Bridge routes never read the catalog on
    the paths these tests exercise (source is a non-catalog id, collect is mocked)."""
    moonglade_gallery.save_catalog(tmp_path / "catalog.db", [])
    return login_client(tmp_path)


def _arm_mirror(monkeypatch):
    """Mirror ARMED with a live session, and every spend/collect entry point mocked so nothing
    reaches the network. submit_generation is mocked so no createGenerationTask is ever sent."""
    calls = {"submit": 0, "last_params": None}

    def _submit(session, params):
        calls["submit"] += 1
        calls["last_params"] = params
        return "T-ENH-1"

    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "mirror_enabled", lambda: True)
    monkeypatch.setattr(core, "make_mirror_session", lambda *a, **k: object())
    monkeypatch.setattr(core, "_apply_kaisuuken", lambda *a, **k: None)
    monkeypatch.setattr(core, "submit_generation", _submit)
    return calls


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


# ---- the panelplugin surface is RESTORED, mirror-gated (the Bridge tier) ----

def test_panelplugin_surface_restored_mirror_gated():
    """The Bridge reversal (drift §44 / SCOPE §3): panelplugin was never "impossible" -- it was
    dead ONLY on the API key. A panelplugin task submitted on the browser JWT (the mirror)
    dispatches in seconds; the 2026-07-24 deletion overshot from "the API key can't run this" to
    "do not rebuild", and dropped the qualifier. So the builder and catalog come BACK, addressed
    by the mirror-gated /api/enhance route (which refuses unless the mirror is armed -- see
    test_enhance_refuses_when_mirror_off).

    Inverts the old "must stay gone" grep: the two literals a panelplugin submit cannot do
    without -- the model id and the workflow-id parameter -- must now be PRESENT in core, in the
    restored builder. The CLI flag that fed the API-key path stays gone (the Bridge is web-only)."""
    assert hasattr(core, "build_panelplugin_parameters")
    assert hasattr(core, "workflow_catalog")
    core_src = (ROOT / "moonglade_backup.py").read_text(encoding="utf-8")
    assert "pixai-panelplugin" in core_src, "the restored builder must name the panelplugin model"
    assert "workflowId" in core_src, "the restored builder must address a panelplugin workflow"
    # LEFT INTACT: the CLI --workflow-id flag stays deleted -- the Bridge is web-route-only, and a
    # bare CLI flag could submit a panelplugin task on the API key (the reaped-at-60-min bug).
    assert '"--workflow-id"' not in core_src
    assert not hasattr(core, "run_enhance")          # no CLI runner either


def test_the_enhance_and_workflows_routes_are_restored(tmp_path):
    """The route-level half of the reversal: the mirror-gated submit route and its catalog route
    both exist again. (Whether the submit REFUSES with the mirror off is
    test_enhance_refuses_when_mirror_off; here we only assert the routes are registered.)"""
    app = moonglade_gallery.create_app(tmp_path)
    rules = {str(r.rule) for r in app.url_map.iter_rules()}
    assert "/api/enhance" in rules
    assert "/api/workflows" in rules
    # The free art-filters panel still saves through the existing local-import path, unchanged.
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


# ---- the Bridge tier: mirror gate, deferred telemetry, lineage ----

def test_enhance_refuses_when_mirror_off(tmp_path, monkeypatch, pixai):
    """[BLOCKER] The FIRST line of /api/enhance is the backend mirror gate. With the mirror OFF,
    a panelplugin submit would otherwise fall through submit_generation's mirror-off branch to
    the API-key session -- the paid-then-reaped-at-60-min bug the whole surface was deleted for.
    So a mirror-off request must 409 and submit NOTHING (no createGenerationTask, no charge)."""
    monkeypatch.setattr(core, "mirror_enabled", lambda: False)          # mirror OFF
    submitted = {"n": 0}
    monkeypatch.setattr(core, "submit_generation",
                        lambda *a, **k: submitted.__setitem__("n", submitted["n"] + 1) or "X")
    # make_mirror_session must never even be consulted for a spend here, but stub it defensively.
    monkeypatch.setattr(core, "make_mirror_session", lambda *a, **k: None)

    cli = _enhance_client(tmp_path)
    r = cli.post("/api/enhance", json={"source": "srcABC",
                                       "workflow_id": "1793447160259872021"})
    assert r.status_code == 409
    assert "Mirror to PixAI must be armed" in (r.get_json() or {}).get("error", "")
    assert submitted["n"] == 0, "a mirror-off enhance reached the submit choke"
    # And no telemetry moved on a refused run.
    telem = moonglade_gallery.load_telemetry(tmp_path)
    assert not telem["counters"].get("enhances")
    assert "enhance" not in telem["sets"].get("tools", [])
    assert not telem["sets"].get("enhance_workflows")


def test_enhance_telemetry_fires_only_on_terminal_success(tmp_path, monkeypatch):
    """[BLOCKER] submit_generation returns at createGenerationTask ACCEPTANCE, before the job
    starts -- and a panelplugin job can be accepted then reaped. So the three producers must NOT
    fire at submit; they fire only when /api/task-status confirms a terminal 'done' WITH output."""
    calls = _arm_mirror(monkeypatch)
    cli = _enhance_client(tmp_path)

    # Submit accepted -> task_id returned, but telemetry has NOT moved yet.
    r = cli.post("/api/enhance", json={"source": "srcABC",
                                       "workflow_id": "1793447160259872021"})
    assert r.status_code == 200 and r.get_json().get("task_id") == "T-ENH-1"
    assert calls["submit"] == 1
    telem = moonglade_gallery.load_telemetry(tmp_path)
    assert not telem["counters"].get("enhances"), "telemetry fired at submit-acceptance"
    assert "enhance" not in telem["sets"].get("tools", [])
    assert not telem["sets"].get("enhance_workflows")

    # Now the poll reports a terminal SUCCESS with output -> all three fire, exactly once.
    monkeypatch.setattr(core, "generation_status",
                        lambda session, tid: {"phase": "done", "paid_credit": 0})
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: {"media_ids": ["OUT1"], "saved": 1,
                                                  "is_video": False})
    d = cli.get("/api/task-status", query_string={"task_id": "T-ENH-1"}).get_json()
    assert d["phase"] == "done"
    telem = moonglade_gallery.load_telemetry(tmp_path)
    assert telem["counters"].get("enhances") == 1
    assert "enhance" in telem["sets"].get("tools", [])
    # The identity ACTUALLY submitted (here the numeric id) is what counts toward Enhance Adept.
    assert "1793447160259872021" in telem["sets"].get("enhance_workflows", [])

    # A second poll of the same finished task must NOT double-count (pending entry consumed).
    cli.get("/api/task-status", query_string={"task_id": "T-ENH-1"})
    assert moonglade_gallery.load_telemetry(tmp_path)["counters"].get("enhances") == 1


def test_enhance_telemetry_does_not_fire_on_dispatched_then_failed(tmp_path, monkeypatch):
    """A task that IS accepted (dispatched) but reaches a terminal FAILURE -- the reaped
    "waiting timeout" is exactly this -- must never count. The pending entry is dropped without
    firing when /api/task-status reports 'failed'."""
    _arm_mirror(monkeypatch)
    cli = _enhance_client(tmp_path)
    assert cli.post("/api/enhance", json={"source": "srcABC",
                                          "workflow_name": "kyo/emotionlab"}
                    ).get_json().get("task_id") == "T-ENH-1"

    monkeypatch.setattr(core, "generation_status",
                        lambda session, tid: {"phase": "failed", "status": "cancelled",
                                              "reason": "waiting timeout", "started": False})
    d = cli.get("/api/task-status", query_string={"task_id": "T-ENH-1"}).get_json()
    assert d["phase"] == "failed"
    telem = moonglade_gallery.load_telemetry(tmp_path)
    assert not telem["counters"].get("enhances"), "a reaped/failed enhance counted"
    assert "enhance" not in telem["sets"].get("tools", [])
    assert not telem["sets"].get("enhance_workflows")


def test_enhance_workflow_name_preset_counts_toward_adept(tmp_path, monkeypatch):
    """[MAJOR] A preset pinned by workflowName (e.g. Background Remover
    'mymusise/39a2c67c:unet-0.1.3.2') must count too. telem_set_add skips FALSY values, so the
    route records the identity actually submitted (wname or wid) -- never an empty string."""
    _arm_mirror(monkeypatch)
    cli = _enhance_client(tmp_path)
    cli.post("/api/enhance", json={"source": "srcABC",
                                   "workflow_name": "mymusise/39a2c67c:unet-0.1.3.2"})
    monkeypatch.setattr(core, "generation_status",
                        lambda session, tid: {"phase": "done", "paid_credit": 0})
    monkeypatch.setattr(core, "collect_generation",
                        lambda s, tid, out, **k: {"media_ids": ["OUT1"], "saved": 1,
                                                  "is_video": False})
    cli.get("/api/task-status", query_string={"task_id": "T-ENH-1"})
    ews = moonglade_gallery.load_telemetry(tmp_path)["sets"].get("enhance_workflows", [])
    assert "mymusise/39a2c67c:unet-0.1.3.2" in ews


def test_source_media_of_task_derives_enhance_lineage():
    """[MAJOR] A Bridge result must file with its SOURCE image, not as an original generation.
    source_media_of_task grows a 4th branch reading inputs.image.media_id -- checked BEFORE the
    top-level mediaId branch. Fixture is the real b93ce1e submit shape (build_panelplugin_
    parameters), so this pins the SUBMIT body we send.

    TODO(bridge): re-verify this against a REAL captured COMPLETED panelplugin task from
    getTaskById -- PixAI may camelCase media_id -> mediaId on the persisted read-back. This
    fixture proves the derive branch, not the field name PixAI stores it under."""
    params = core.build_panelplugin_parameters("SRC123", "1796053397111789217")
    assert core.source_media_of_task({"parameters": params}) == ("SRC123", "enhance")
    # A workflowName preset carries the same inputs.image.media_id shape.
    p2 = core.build_panelplugin_parameters("SRC456", workflow_name="mymusise/hand-fix")
    assert core.source_media_of_task({"parameters": p2}) == ("SRC456", "enhance")
    # A plain txt2img (no inputs.image) is still an original -> (None, None), unchanged.
    assert core.source_media_of_task({"parameters": {"modelId": "m", "prompt": "x"}}) == (None, None)
