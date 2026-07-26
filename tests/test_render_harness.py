"""THE RENDERING HARNESS: assertions that the CSS *works*, not that it *exists*.

Why this file exists
--------------------
docs/AUDIT_2026-07-21.md's **T5-CSS** row is the brief. Established by experiment, not
argument: this suite asserts that CSS *exists* (substring-in-a-blob) and never that it
*renders*, so a whole class of defect ships invisibly and reaches the owner instead of CI.
Four of them did, all in one evening:

  1. The model picker's grid was capped at a fixed 320px inside a panel sized to fill the
     viewport, leaving a large dead strip below it ("the panel is cut in half").
  2. `.lv-df-veil` renders inside `.lv-overlay`'s 400 atom, so the corner FABs (401/402)
     painted OVER Deep Focus.
  3. At <=480px the Generate drawer renders 352.5px wide with a dead gutter and
     `#model-flyout` lands at y = -332.9px, half above the viewport.
  4. `test_portrait_mobile_pass` passes anyway, because it asserts the rule's TEXT.

Every assertion below is a regression guard for one of those, written the only way that
can actually see them: drive a REAL browser against a REAL server and measure the
resulting layout / stacking / computed style.

Design, and why
---------------
* **A live server, not Flask's test client.** A test client never renders. The real app is
  bound to an ephemeral port (`make_server(..., 0, ...)`) in a daemon thread against a
  throwaway catalog, started once for the module so the cost is paid once.
* **Real login, no bypass.** `moonglade_gallery.py`'s `_is_authorized_request()` has no
  localhost bypass and re-validates the session against `config.json`'s `AUTH_USERS` on
  every request, so the harness posts the real `/login` form with a real scrypt-hashed
  account made by `core.add_or_update_web_user` -- the same thing `tests/conftest.py`'s
  `login_client()` helpers do for the test client. Nothing here weakens an auth path.
* **The conftest interaction that matters.** `tests/conftest.py::_isolated_auth_config` is
  autouse and function-scoped: it re-points `core._config_path()` at each test's own
  `tmp_path`. Our server outlives an individual test and reads that same function on every
  authenticated request, so `logged_in_page` re-pins it back at the harness's own
  config -- and pytest guarantees an explicitly-requested fixture is set up AFTER the
  autouse fixtures of the same scope, which is exactly the ordering that makes this work.
  That ordering is asserted, and `_login()` asserts the login actually redirected, so a
  future change here fails loudly instead of silently logging nobody in.
* **Skips clean, never fails, with no browser.** `pytest.importorskip` at import, and the
  session browser fixture skips if the chromium binary is missing. `python -m pytest -q`
  on a bare machine (and in the current CI workflow, which installs no playwright) stays
  green. Marker `render` is registered in `pytest.ini` so `-m "not render"` works too.

Measurement discipline -- both halves of this were learned the hard way
----------------------------------------------------------------------
1. **Freeze motion before measuring.** An earlier probe read interpolated mid-transition
   values off `#gen-drawer` (`transition: transform .2s, width .2s`) and reported a false
   diff. `_freeze_motion()` kills `transition`/`animation` with `!important` so every
   geometry read is of a settled layout. It deliberately does NOT use Playwright's
   `reduced_motion="reduce"`: this app ships real `@media (prefers-reduced-motion)` rules,
   so flipping that flag would measure a DIFFERENT stylesheet than the default user gets.
2. **Wait for the JS, don't sleep.** A screenshot once beat the JS that writes
   `#gen-dim-note` and looked like a regression. Nothing below sleeps: every phase waits
   on the actual post-condition (`#gen-drawer.open`, a rendered `.mg-card`, `.lv-df-veil`)
   and then `_settle()` yields two animation frames so the read happens after layout.

Each test proves itself
-----------------------
"An assertion nobody has seen fail is not a guard." So each test runs two phases: assert
the shipped, fixed behaviour, then apply the pre-fix state as an in-page override (a
`<style>` tag or a class removal -- NEVER a committed revert) and assert the same metric
flips. That makes every threshold here demonstrably non-vacuous on every run, not just on
the day it was written.

The CI gap, and what covers it
------------------------------
This module SKIPS without playwright + chromium, and `.github/workflows/tests.yml`
installs neither -- so on CI these guards do not run at all. That is a deliberate
trade (see the marker note in `pytest.ini`), but it means defect 3 above would have
regressed on a `push` unseen. `tests/csshelp.py` covers exactly that one axis in pure
stdlib: it resolves which declaration WINS the cascade (!important, specificity,
document order) with no browser, and
`tests/test_web_pick.py::test_portrait_mobile_drawer_rules_actually_win` asserts on
that. It is a strictly weaker instrument -- it proves the winner, not the pixels -- and
is not a reason to skip adding a rendering test here.
"""
import base64
import json
import threading

import pytest

import moonglade_backup as core
from moonglade_gallery import CATALOG_FIELDS, create_app, save_catalog

# No playwright (or no browser) => this whole module skips. It is not installed by
# .github/workflows/tests.yml, so these tests SKIP in CI today and run locally.
_pw = pytest.importorskip(
    "playwright.sync_api",
    reason="the rendering harness needs playwright + a chromium binary")
_PlaywrightTimeout = _pw.TimeoutError

pytestmark = pytest.mark.render

_USERNAME = "render-harness"
_PASSWORD = "a-real-test-password-1"

# 1280x900 desktop: what every threshold below was measured at.
DESKTOP = {"width": 1280, "height": 900}
# 375x812 portrait phone: inside the <=480px breakpoint, matching the audit's own probe.
MOBILE_PORTRAIT = {"width": 375, "height": 812}

# Kill every transition/animation so a geometry read can never catch an interpolated
# mid-flight value. `*` + !important beats the app's id-selector rules; applied to the
# document under test, never to committed CSS.
_FREEZE_MOTION_CSS = (
    "*, *::before, *::after {"
    " transition: none !important; transition-duration: 0s !important;"
    " animation: none !important; animation-duration: 0s !important; }"
)

# /api/model-search reaches PixAI's live API. Fulfilled from the test instead: 24 rows is
# what the real endpoint's default page size returns, so the grid gets a realistic amount
# of content to overflow with. preview_url is empty on purpose -- the picker renders no
# <img> for a falsy url, so there is no outbound image request to stub as well.
_FAKE_MODEL_SEARCH = {
    "results": [
        {"model_id": str(1000 + i), "name": "Harness Model %d" % i, "author": "harness",
         "model_type": "SDXL_MODEL", "likes": 12, "ref_count": 34, "preview_url": "",
         "should_blur": False, "description": "a fixture row", "category": "sdxl",
         "official": False}
        for i in range(24)
    ],
    "has_more": True,
    "next_cursor": "24",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def render_browser():
    """One chromium for this whole module -- a launch per test would dominate runtime.

    MODULE, not session, and that is load-bearing rather than tidiness: playwright's SYNC api
    installs a running asyncio event loop in the calling thread and keeps it running until
    `stop()`. Leaving it up for the rest of the session breaks every test that calls
    `asyncio.run()` itself -- proven, not theorized: at session scope all six of
    `tests/test_watch.py`'s tests failed with "asyncio.run() cannot be called from a running
    event loop" purely because this module happens to sort before them. Module scope tears the
    loop down at the last test here, and since this is the only rendering module the runtime
    cost is identical.

    Skips (never fails) when the browser binary is absent, which is the state of any machine
    that has the pip package but never ran `playwright install`. (A machine with no pip
    package at all -- including CI -- never gets here: the module-level importorskip does it.)
    """
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch()
    except Exception as exc:                                  # pragma: no cover
        pw.stop()
        # First line only: playwright's own message trails a multi-line ASCII banner that
        # would swamp the -rs summary.
        pytest.skip("no usable chromium binary (run `playwright install chromium`): "
                    "{}".format(str(exc).splitlines()[0]))
    try:
        yield browser
    finally:
        browser.close()
        pw.stop()


@pytest.fixture(scope="module")
def render_server(tmp_path_factory):
    """The real Flask app on a real ephemeral port, started once for this module.

    Module-scoped for the same reason as `render_browser`: nothing this harness starts should
    outlive it. That also means the server thread, the `MOONGLADE_DISABLE_WATCH` pin and the
    quieted werkzeug logger are all gone before any later test file runs.

    Its own `pytest.MonkeyPatch` (the function-scoped `monkeypatch` fixture cannot reach
    module scope) pins the same three things conftest's autouse fixtures pin per test, so
    the server never sees this machine's real config or credentials:
    `MOONGLADE_DISABLE_WATCH=1` (no live-mirror WebSocket), `core._config_path` (so
    `get_or_create_secret_key()` and the account write land in tmp, not next to the
    checkout) and an empty `core._cfg`.
    """
    import logging
    from types import SimpleNamespace

    from werkzeug.serving import make_server

    # A browser pulls ~40 sub-resources per page; werkzeug's per-request access log buries
    # a real failure's traceback in captured output. Restored on teardown.
    wz_log = logging.getLogger("werkzeug")
    wz_level = wz_log.level
    wz_log.setLevel(logging.ERROR)

    mp = pytest.MonkeyPatch()
    root = tmp_path_factory.mktemp("render-harness")
    config_path = root / "config.json"
    mp.setenv("MOONGLADE_DISABLE_WATCH", "1")
    mp.setattr(core, "_config_path", lambda: config_path)
    mp.setattr(core, "_cfg", {})

    save_catalog(root / "catalog.db", [
        {f: "" for f in CATALOG_FIELDS} | {
            "media_id": str(100 + i), "filename": "harness_%d.png" % i,
            "prompt_preview": "harness row %d" % i,
            "created_at": "2025-01-%02dT00:00:00" % (i + 1)}
        # Row 0 alone carries what a swept catalog holds: the REAL size of the bitmap written
        # below, plus a model. The upscale panel derives its ratio cap from those dimensions,
        # so a fake size would make every assertion about the cap meaningless, and without a
        # model the panel correctly refuses to submit and there would be nothing to measure.
        | ({"width": "900", "height": "600", "model_id": "4242",
            "model_name": "Harness Model", "prompt_full": "harness prompt"} if i == 0 else {})
        for i in range(6)
    ])
    # A REAL bitmap on disk for the first row, so /full/100 serves a decodable image through
    # its real route (find_image_file -> send_from_directory). It cannot be a page.route stub:
    # the app registers a service worker whose fetch handler already answers `/full/`, and a
    # service worker's own fetch bypasses Playwright's request interception. It has to be a
    # realistic SHAPE too -- every layout assertion about the filters panel is downstream of
    # the image's intrinsic aspect, which a 1x1 placeholder would not have.
    from PIL import Image
    Image.new("RGB", (900, 600), (120, 90, 180)).save(root / "harness_0.png")
    core.add_or_update_web_user(_USERNAME, _PASSWORD)

    server = make_server("127.0.0.1", 0, create_app(root), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True,
                              name="render-harness-server")
    thread.start()
    try:
        yield SimpleNamespace(
            base_url="http://127.0.0.1:%d" % server.server_port,
            config_path=config_path)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        mp.undo()
        wz_log.setLevel(wz_level)


@pytest.fixture()
def logged_in_page(render_server, render_browser, monkeypatch):
    """Factory: `logged_in_page(**viewport)` -> a fresh authenticated page.

    Re-pins `core._config_path` at the harness's own config, undoing conftest's
    per-test redirect for the duration of this test (see the module docstring). A fresh
    context per page keeps cookies/localStorage isolated between tests -- the skin tests
    below write localStorage, and leaking that into the picker tests would be a real
    cross-test coupling.
    """
    monkeypatch.setattr(core, "_config_path", lambda: render_server.config_path)
    # Fail loudly rather than mysteriously if the autouse-before-requested fixture ordering
    # this depends on ever changes: an unpinned path means AUTH_USERS looks empty and every
    # login silently leaves an anonymous session behind.
    assert core._config_path() == render_server.config_path
    contexts = []

    def _open(width=DESKTOP["width"], height=DESKTOP["height"]):
        # base_url makes page.goto("/loom") resolve against the ephemeral port, so no test
        # has to carry the port around.
        ctx = render_browser.new_context(viewport={"width": width, "height": height},
                                         device_scale_factor=1,
                                         base_url=render_server.base_url)
        # Playwright's 30s default turns "the fix is broken" into a 30s stall per test.
        # 10s is ~6x the slowest real wait here (the Loom bundle boot, ~1.7s) and keeps a
        # genuine regression failing in seconds.
        ctx.set_default_timeout(10_000)
        contexts.append(ctx)
        page = ctx.new_page()
        _login(page)
        return page

    try:
        yield _open
    finally:
        for ctx in contexts:
            ctx.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _login(page):
    """Post the real /login form. No bypass, no fabricated session cookie."""
    page.goto("/login", wait_until="domcontentloaded")
    page.fill("input[name=username]", _USERNAME)
    page.fill("input[name=password]", _PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_load_state("networkidle")
    assert "/login" not in page.url, (
        "the harness failed to authenticate -- most likely core._config_path() is not "
        "pointing at the harness's own config.json, so AUTH_USERS looked empty")


def _visit(page, path):
    """Navigate and immediately freeze motion, so nothing is ever measured mid-transition."""
    page.goto(path, wait_until="domcontentloaded")
    _freeze_motion(page)


def _freeze_motion(page):
    page.add_style_tag(content=_FREEZE_MOTION_CSS)


def _settle(page):
    """Yield two animation frames: style recalc + layout have both run before we read."""
    page.evaluate("() => new Promise(r => requestAnimationFrame("
                  "() => requestAnimationFrame(r)))")


def _stub_model_search(page):
    page.route("**/api/model-search*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(_FAKE_MODEL_SEARCH)))


def _open_drawer_and_model_flyout(page):
    """Click the real controls (never a private helper) and wait on each post-condition."""
    page.click("button.btn-primary:has-text('Generate')")     # header -> Gen.open()
    page.wait_for_selector("#gen-drawer.open", state="attached")
    page.click("#gen-selrow")                                 # -> Gen.toggleFlyout()
    page.wait_for_selector("#model-flyout.open", state="attached")
    # The grid is filled by fetch -> render. Wait for the LAST card, not the first: a
    # geometry read taken mid-render measures a grid that is still growing.
    page.wait_for_function(
        "() => document.querySelectorAll('#model-flyout .mg-card').length === %d"
        % len(_FAKE_MODEL_SEARCH["results"]))
    _settle(page)


_PICKER_METRICS_JS = """() => {
  const panel = document.getElementById('model-flyout');
  const grid  = panel.querySelector('mg-model-picker .mg-grid');
  const r = el => el.getBoundingClientRect().toJSON();
  return {
    panel: r(panel),
    grid: r(grid),
    cards: grid.querySelectorAll('.mg-card').length,
    gridScrollHeight: grid.scrollHeight,
    gridClientHeight: grid.clientHeight,
    deadSpaceBelowGrid: r(panel).bottom - r(grid).bottom,
  };
}"""

# The pre-fix CSS, restored as a later-in-cascade !important override so it wins against
# the shipped id-scoped rules. This is the state of the repo BEFORE the picker-parity-round2
# fix: mg-model-picker was display:block, .mg-grid carried its own fixed max-height:320px,
# and #model-flyout .gen-body was the outer scroll container. NEVER committed to any CSS.
_REVERT_PICKER_FIX_CSS = """
mg-model-picker { display: block !important; }
mg-model-picker .mg-grid { flex: none !important; max-height: 320px !important; }
#model-flyout .gen-body { overflow: auto !important; display: block !important; }
"""


# ---------------------------------------------------------------------------
# 1. The picker grid fills its panel  (the "panel is cut in half" bug)
# ---------------------------------------------------------------------------
def test_model_picker_grid_fills_the_flyout_panel(logged_in_page):
    """The model picker's grid must consume the flyout panel, leaving no dead strip.

    THRESHOLD, from measured reality at 1280x900:
      as shipped   dead space below the grid = 13.0px
      pre-fix      dead space below the grid = 442.4px

    13.0px is not slack, it is the panel's own chrome: `.gen-body{padding:12px 14px}`
    contributes 12px of bottom padding and `#model-flyout` a 1px border. 24px is therefore
    ~2x the real chrome (room for a padding bump or a scrollbar gutter) and ~18x smaller
    than the defect, so it cannot be satisfied by a regression: half a card row is ~100px.
    """
    page = logged_in_page(**DESKTOP)
    _stub_model_search(page)
    _visit(page, "/")
    _open_drawer_and_model_flyout(page)

    m = page.evaluate(_PICKER_METRICS_JS)
    assert m["cards"] == 24, "measured an empty grid -- the metric would be meaningless"
    assert m["deadSpaceBelowGrid"] <= 24, (
        "dead space below the picker grid is {:.1f}px in a {:.0f}px panel -- the grid is "
        "not filling the flyout (the 'panel is cut in half' regression)".format(
            m["deadSpaceBelowGrid"], m["panel"]["height"]))
    # The grid, not the panel, must be the scrolling region -- that is the shape of the fix.
    assert m["gridScrollHeight"] > m["gridClientHeight"], (
        "the grid has no internal overflow, so 24 cards are not actually scrollable in it")

    # --- phase 2: prove the guard bites. Restore the pre-fix CSS in-page only. ---
    page.add_style_tag(content=_REVERT_PICKER_FIX_CSS)
    _settle(page)
    reverted = page.evaluate(_PICKER_METRICS_JS)
    assert reverted["deadSpaceBelowGrid"] > 24, (
        "the pre-fix CSS was re-applied and this metric did NOT go over threshold "
        "({:.1f}px) -- the assertion above is vacuous".format(
            reverted["deadSpaceBelowGrid"]))


# ---------------------------------------------------------------------------
# 2. The model flyout is fully inside the viewport when open
# ---------------------------------------------------------------------------
# Parameterised by element id: the same containment property is asserted for #model-flyout
# below and for #filters-flyout in section 3, and the two panels are positioned by different
# mechanisms (CSS dock rules vs Gen.placeFilters()), so one shared measurement keeps them
# honest against each other rather than drifting into two near-identical checks.
_RECT_JS = """(id) => {
  const f = document.getElementById(id);
  const r = f.getBoundingClientRect().toJSON();
  r.innerWidth = window.innerWidth;
  r.innerHeight = window.innerHeight;
  return r;
}"""


def _assert_within_viewport(rect, label):
    assert rect["width"] > 0 and rect["height"] > 0, label + " has no box -- did it open?"
    assert rect["top"] >= 0, (
        "{}'s top is {:.1f}px -- it is hanging above the viewport".format(label, rect["top"]))
    assert rect["bottom"] <= rect["innerHeight"], (
        "{}'s bottom is {:.1f}px past the {:.0f}px viewport".format(
            label, rect["bottom"] - rect["innerHeight"], rect["innerHeight"]))
    assert rect["left"] >= 0, (
        "{}'s left is {:.1f}px -- it is hanging off the left edge".format(label, rect["left"]))
    assert rect["right"] <= rect["innerWidth"], (
        "{}'s right is {:.1f}px past the {:.0f}px viewport".format(
            label, rect["right"] - rect["innerWidth"], rect["innerWidth"]))


def test_model_flyout_is_fully_inside_the_viewport_at_desktop(logged_in_page):
    """Measured as shipped at 1280x900: top 0, bottom 900 (== innerHeight), left 489,
    right 861. Exactly flush at the bottom, which is why `<=` and not `<`."""
    page = logged_in_page(**DESKTOP)
    _stub_model_search(page)
    _visit(page, "/")
    _open_drawer_and_model_flyout(page)
    _assert_within_viewport(page.evaluate(_RECT_JS, "model-flyout"), "#model-flyout")


def test_model_flyout_is_fully_inside_the_viewport_at_mobile_portrait(logged_in_page):
    """Same assertion, 375x812.

    This carried an xfail(strict=False) while the defect it describes was open: at <=480px
    both mobile @media rules used bare id selectors and lost to later base rules at equal
    specificity, so #model-flyout kept its desktop right:100%/height:100% geometry and
    landed at y = -332.9px, half above the viewport. That fix has LANDED -- the drawer's
    portrait overrides now sit at the end of the drawer's own stylesheet, after the rules
    they override -- and this test went XPASS on the strength of it. The marker is gone
    rather than left to report XPASS forever, because an xfail'd guard is a dead guard: a
    regression would come back as "expected failure" and read as green, which is the exact
    class of blind spot this whole module exists to remove. Measured after the fix: the
    flyout is fixed/centered and fully inside the viewport in every dock.
    """
    page = logged_in_page(**MOBILE_PORTRAIT)
    _stub_model_search(page)
    _visit(page, "/")
    _open_drawer_and_model_flyout(page)
    _assert_within_viewport(page.evaluate(_RECT_JS, "model-flyout"), "#model-flyout")


# ---------------------------------------------------------------------------
# 3. The art-filters flyout is genuinely SIDE BY SIDE  (the flex-basis wrap bug)
# ---------------------------------------------------------------------------
def _open_filters_flyout(page):
    """Click the real controls, then wait on each post-condition -- including the image's own
    decode, because the panel's height and the left column's width both depend on it."""
    page.click("button.btn-primary:has-text('Generate')")       # header -> Gen.open()
    page.wait_for_selector("#gen-drawer.open", state="attached")
    page.click("#gm-edit")                                      # -> Gen.setMode('edit')
    page.click("#es-enhance")                                   # -> Gen.setEditSub('enhance')
    page.fill("#edit-src", "100")
    page.dispatch_event("#edit-src", "input")                   # -> Gen.setEditSource('100')
    page.click("#af-open")                                      # -> Gen.toggleFilters()
    page.wait_for_selector("#filters-flyout.open", state="attached")
    # 12 tiles in two headed groups: the Moonglade five lead, PixAI's seven follow.
    page.wait_for_function("() => document.querySelectorAll('#af-swatches .af-tile').length === 12")
    page.wait_for_function("() => document.querySelectorAll('#af-swatches .af-grp').length === 2")
    page.wait_for_function("() => ['af-img','af-orig'].every(id => { const i ="
                           " document.getElementById(id); return i.complete && i.naturalWidth > 0; })")
    _settle(page)
    page.click('.af-tile[data-af="filter-v1-m4"]')              # a filter with image_parameters
    page.wait_for_function("() => document.querySelectorAll("
                           "'#af-stage > [data-mgaf-layer]').length === 2")
    _settle(page)


_FILTERS_LAYOUT_JS = """() => {
  const f = document.getElementById('filters-flyout');
  const img = document.getElementById('af-img');
  const og = document.getElementById('af-orig');
  const stage = document.getElementById('af-stage');
  const sw = document.getElementById('af-swatches');
  const frame = img.closest('.af-frame'), oframe = og.closest('.af-frame');
  const r = el => el.getBoundingClientRect().toJSON();
  const fr = r(f), ir = r(img), sr = r(stage), wr = r(sw), or = r(og), fmr = r(frame);
  const ofr = r(oframe);
  return {
    flyout: fr, image: ir, stage: sr, swatches: wr, original: or,
    // The comparison: original LEFT of the preview, on the same row.
    originalLeftOfPreview: or.right <= ir.left,
    originalShareTopBand: Math.abs(or.top - ir.top) < 80,
    originalWidth: or.width,
    // ...and genuinely UNFILTERED. applyPreview() puts a CSS `filter` on its target <img> and
    // stacks overlay divs in the stage; if either reached the original there would be two
    // filtered pictures side by side and nothing to compare against. Read from the computed
    // style, not the inline one, so a stylesheet rule cannot sneak one in either.
    originalFilter: getComputedStyle(og).filter,
    originalOverlays: og.parentElement.querySelectorAll('[data-mgaf-layer]').length,
    innerWidth: window.innerWidth, innerHeight: window.innerHeight,
    // side by side == the controls start to the RIGHT of the picture and share the top band of
    // the COLUMN. A wrapped layout fails the first half; a swapped one would fail it too.
    // Measured against the frame, not the image: the frames stretch to the row's height and
    // centre their picture inside, so a landscape source sits a couple of hundred px below
    // the rail's top while being perfectly in-row. Comparing image tops would fail on
    // matting, which is a layout SUCCESS.
    controlsRightOfImage: wr.left >= ir.right,
    controlsShareTopBand: Math.abs(wr.top - fmr.top) < 80,
    frame: fmr, originalFrame: ofr,
    // ALL THREE on one row -- the actual claim. Checking any PAIR is not enough: with an
    // `auto` basis the original wraps to its own line while the preview and the rail still
    // fit together on the next one, so a preview-vs-rail comparison reads a broken panel as
    // intact. Measured: rail top 571, preview frame top 571, original stranded above.
    oneRow: Math.abs(wr.top - fmr.top) < 80 && Math.abs(ofr.top - fmr.top) < 80,
    // the stage is MgArtFilters' overlay host: its box must be the image's box exactly, or
    // the gradient layers (inset:0) paint over letterbox bars the image is not using.
    stageMatchesImage: Math.abs(sr.width - ir.width) < 1 && Math.abs(sr.height - ir.height) < 1,
    layers: stage.querySelectorAll(':scope > [data-mgaf-layer]').length,
    blendModes: [...stage.querySelectorAll(':scope > [data-mgaf-layer]')]
                  .map(d => getComputedStyle(d).mixBlendMode),
    imageFilter: img.style.filter || '',
  };
}"""

# The pre-fix CSS, restored as a later-in-cascade !important override. `flex: 1 1 auto` was
# what shipped first: from an `auto` basis an image column's base size is the IMAGE's
# max-content width (900px for a normal generation, since `max-width:100%` cannot resolve
# against a container the image is itself sizing), the columns' hypothetical sizes exceed the
# panel, and flex-wrap breaks the line -- dropping the rail under the pictures at every panel
# width. Worse now than when it was first found: there are TWO image columns to overflow.
# NEVER committed to any CSS.
_REVERT_FILTERS_FLEX_CSS = """
#filters-flyout .af-col { flex: 1 1 auto !important; min-width: 260px !important; }
"""


def test_art_filters_flyout_is_side_by_side_with_the_image_left(logged_in_page):
    """The filters panel exists so a filter can be JUDGED, which needs both pictures at size
    on one row -- original, preview, then the swatches. That is a layout fact no HTML-string
    assertion can see, and neither is the one that matters most here: that the LEFT picture is
    genuinely unfiltered. Sharing one <img> between the two columns, or letting the stage's
    overlays reach the original, yields two filtered pictures and no comparison at all, while
    every markup assertion still passes.

    Measured at 1280x900, right dock, Edit tab (a 600px `.wide` drawer): 647px of room beside
    the drawer is below AF_MIN_SIDE, so placeFilters() takes its centred branch -- the same
    fallback #model-flyout documents for the top/bottom docks -- and the panel clamps to the
    viewport with both columns comfortably over 200px.

    The pre-fix `flex: 1 1 auto` (phase 2 below) is why an explicit basis is load-bearing
    rather than a style preference: from an `auto` basis each image column is as wide as the
    image's intrinsic width, so the rail wrapped below the pictures at every panel width.

    Also asserts the two things that would make a side-by-side panel useless anyway: that the
    overlay stage is exactly the image's box (so the gradients don't spill onto letterbox
    bars), and that the browser really ACCEPTED the mapped blend modes instead of silently
    falling back to `normal`, which would render a flat gradient and look like a working
    filter.
    """
    page = logged_in_page(**DESKTOP)
    _visit(page, "/")
    _open_filters_flyout(page)

    m = page.evaluate(_FILTERS_LAYOUT_JS)
    assert m["image"]["width"] > 200, (
        "the preview image is only {:.1f}px wide -- too small to judge a filter on, and the "
        "metrics below would be measuring a collapsed column".format(m["image"]["width"]))
    assert m["controlsRightOfImage"], (
        "the swatches start at x={:.1f} but the image ends at x={:.1f} -- the controls have "
        "WRAPPED under the image instead of sitting beside it".format(
            m["swatches"]["left"], m["image"]["right"]))
    assert m["originalLeftOfPreview"] and m["originalShareTopBand"], (
        "the original is at x={:.1f}..{:.1f} y={:.1f} and the preview at x={:.1f} y={:.1f} -- "
        "they are not a side-by-side pair".format(
            m["original"]["left"], m["original"]["right"], m["original"]["top"],
            m["image"]["left"], m["image"]["top"]))
    assert m["originalWidth"] > 200, (
        "the original is only {:.1f}px wide -- too small to compare against".format(
            m["originalWidth"]))
    # The load-bearing property of the whole relayout: the left picture is UNTOUCHED.
    assert m["originalFilter"] == "none" and m["originalOverlays"] == 0, (
        "the original is being filtered too (filter={!r}, {} overlay layers) -- there is "
        "nothing left to compare the preview against".format(
            m["originalFilter"], m["originalOverlays"]))
    assert m["oneRow"], (
        "original/preview/rail tops are {:.1f}/{:.1f}/{:.1f} -- the three columns are not on "
        "one row".format(m["originalFrame"]["top"], m["frame"]["top"], m["swatches"]["top"]))
    assert m["controlsShareTopBand"], (
        "the swatches' top is {:.1f}px from the picture frame's -- they are not on the same "
        "row".format(abs(m["swatches"]["top"] - m["frame"]["top"])))
    assert m["stageMatchesImage"], (
        "the overlay stage is {:.1f}x{:.1f} but the image is {:.1f}x{:.1f} -- the gradient "
        "layers (inset:0) would paint outside the picture".format(
            m["stage"]["width"], m["stage"]["height"],
            m["image"]["width"], m["image"]["height"]))
    # filter-v1-m4 is soft-light + color-burn, and carries image_parameters.
    assert m["layers"] == 2
    assert m["blendModes"] == ["soft-light", "color-burn"], (
        "the browser resolved the overlay blend modes to {} -- a mode it does not accept "
        "computes as `normal`, which paints a flat gradient and is not the filter".format(
            m["blendModes"]))
    assert m["imageFilter"] == "brightness(1.04) contrast(1.05) saturate(1.1)", (
        "filter-v1-m4's image_parameters (+0.04/+0.05/+0.1 as signed OFFSETS from 1) did not "
        "reach the <img>: got {!r}".format(m["imageFilter"]))
    _assert_within_viewport(page.evaluate(_RECT_JS, "filters-flyout"), "#filters-flyout")

    # --- phase 2: prove the guard bites. Restore the pre-fix flex basis in-page only. ---
    page.add_style_tag(content=_REVERT_FILTERS_FLEX_CSS)
    _settle(page)
    reverted = page.evaluate(_FILTERS_LAYOUT_JS)
    # The symptom is that the row BREAKS, which is why this checks the top band rather than
    # the horizontal order: an `auto` basis sizes each column to the image's intrinsic width
    # (measured: a 902px frame in a 1180px panel), so the columns wrap onto their own lines --
    # and a picture narrower than its blown-out column can still leave the rail to its right
    # while sitting hundreds of px below it. Comparing x alone read that as "fine".
    assert not reverted["oneRow"], (
        "`flex: 1 1 auto` was re-applied and the panel did NOT break (original frame top "
        "{:.1f}, preview frame top {:.1f}, rail top {:.1f}, column {:.1f}px wide) -- the "
        "in-row assertion above is vacuous".format(
            reverted["originalFrame"]["top"], reverted["frame"]["top"],
            reverted["swatches"]["top"], reverted["frame"]["width"]))


def test_art_filters_flyout_is_fully_inside_the_viewport_at_mobile_portrait(logged_in_page):
    """375x812: the panel is far wider than the phone, so placeFilters() must fall through to
    its centred branch and clamp. The layout is expected to STACK here (that is what the
    `flex-wrap` + `min-width` pair is for), so this asserts containment only -- and that the
    page itself never gains a horizontal scroll, which is how an unclamped fixed panel shows
    up to a user rather than as an off-screen rect."""
    page = logged_in_page(**MOBILE_PORTRAIT)
    _visit(page, "/")
    _open_filters_flyout(page)
    _assert_within_viewport(page.evaluate(_RECT_JS, "filters-flyout"), "#filters-flyout")
    assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth + 1"), (
        "the document scrolls horizontally with the filters panel open -- it is overflowing "
        "the viewport rather than being clamped into it")


_UPSCALE_JS = """() => {
  const p = document.getElementById('up-panel');
  // Addressed by their own data hooks rather than by "is there a visible <select>": the
  // panel has a second one for the model fallback, and probing by tag matched THAT and
  // reported the upscaler as visible under Hires, where it is not.
  const vis = sel => { const e = p.querySelector(sel);
                       return !!e && getComputedStyle(e).display !== 'none'; };
  const ratio = p.querySelector('input[type=range]');
  return {
    open: p.hasAttribute('open'),
    ratioMax: parseFloat(ratio.max),
    ratioDisabled: ratio.disabled,
    // The upscaler dropdown exists only for enlarge; the denoising pair only for Hires.
    upscalerShown: vis('[data-mgu="upscaler"]'),
    denoiseShown: vis('[data-mgu="denoise"]'),
    pickerOffered: vis('.mgu-pick') || [...p.querySelectorAll('button')]
                     .some(b => /choose a model/i.test(b.textContent)
                                && getComputedStyle(b).display !== 'none'),
    text: p.innerText,
    goDisabled: p.querySelector('.mgu-go').disabled,
    // 'idle' means the badge was never fed at all. It is the state an invented API name
    // leaves it in -- a custom element swallows an unknown method call, so the panel looks
    // finished while its price line silently never updates.
    costState: (p.querySelector('mg-cost-badge') || {}).state || 'missing',
  };
}"""


def test_the_upscale_panel_derives_its_ratio_cap_from_the_real_picture(logged_in_page):
    """The whole reason Upscale moved out of the Generate drawer: the cap is DYNAMIC, derived
    from the source's own dimensions against a per-mode pixel ceiling, and a drawer has no
    source. Here there is one -- a real 900x600 bitmap with a catalog row to match -- so the
    number the slider offers can be checked against the Python the server clamps to.

    Also asserts the control asymmetry, which is PixAI's and not a layout shortcut: the
    upscaler dropdown exists only for `enlarge`, the denoising pair only for Hires.
    """
    page = logged_in_page(**DESKTOP)
    _visit(page, "/image/100")
    page.click("#upscale-btn")
    page.wait_for_selector("mg-upscale-panel[open]", state="attached")
    page.wait_for_function("() => { const r = document.querySelector('mg-upscale-panel "
                           "input[type=range]'); return r && parseFloat(r.max) > 1; }")
    _settle(page)

    enlarge = page.evaluate(_UPSCALE_JS)
    assert enlarge["open"]
    assert enlarge["ratioMax"] == core.max_upscale_ratio(900, 600, "enlarge"), (
        "the slider offers {}x but the server clamps 900x600 enlarge to {}x -- a client that "
        "offers more has the ratio silently pulled back with nothing on screen to say so"
        .format(enlarge["ratioMax"], core.max_upscale_ratio(900, 600, "enlarge")))
    assert enlarge["upscalerShown"], "enlarge must offer the 5-option upscaler picker"
    assert not enlarge["denoiseShown"], "enlarge has no denoising controls -- that is Hires"
    assert "900\u00d7600" in enlarge["text"], "the panel must name the real source size"
    assert not enlarge["goDisabled"], "the row has a model, so the submit must be available"
    # This harness has no API key, so the price check fails -- which is exactly why it is
    # worth asserting: the badge must have been FED (checking, then an error), not left
    # untouched on its idle hint.
    assert enlarge["costState"] != "idle", (
        "the cost badge was never fed -- the panel is calling a method it does not have")

    # Switch to Hires: a different ceiling, a different cap, and the opposite control set.
    page.click("mg-upscale-panel .mgu-seg button:nth-child(2)")
    _settle(page)
    hires = page.evaluate(_UPSCALE_JS)
    assert hires["ratioMax"] == core.max_upscale_ratio(900, 600, "upscale")
    assert hires["ratioMax"] != enlarge["ratioMax"], (
        "both methods offered the same cap -- the per-mode ceiling is not being applied")
    assert hires["denoiseShown"], "Hires must offer denoising strength and steps"
    assert not hires["upscalerShown"], "Hires has no upscaler dropdown"


def test_choosing_a_model_scrolls_the_picker_into_view(logged_in_page):
    """Owner report, from the lightbox flyout: "asks me to choose a model but a picker does
    not open."

    It did open. The panel scrolls (overflow:auto) and the Model row sits near the bottom, so
    mounting the picker without moving to it put the whole thing BELOW the fold -- the click
    looked like it did nothing. Measured before the fix in that exact flyout: the panel was
    711px tall in an 828px box with the picker appended past the visible area.

    This asserts the OUTCOME -- the picker ends up inside the panel's visible box -- rather
    than that scrollIntoView was called, because the first is what the owner experiences.
    """
    # A SHORT viewport on purpose: the panel is max-height:calc(100vh - 72px), so it only
    # scrolls -- and can therefore only hide the picker -- once its content exceeds that.
    # At 1280x900 it fits whole and the bug does not reproduce, which is exactly why the
    # first version of this test passed against the broken build.
    page = logged_in_page(width=1280, height=420)
    _visit(page, "/")
    page.evaluate("() => openLightbox(null, 1)")        # media 101: no model -> offers the picker
    page.wait_for_selector("#lightbox.open", state="attached")
    page.click("#lb-upscale")
    page.wait_for_selector("mg-upscale-panel[open]", state="attached")
    _settle(page)
    page.evaluate("""() => {
      const p = document.getElementById('up-flyout');
      const b = [...p.querySelectorAll('button')].find(x => /choose a model/i.test(x.textContent));
      b.click();
    }""")
    page.wait_for_selector("#up-flyout mg-model-picker", state="attached")
    _settle(page)
    page.wait_for_timeout(500)                          # the scroll is smooth + rAF-deferred
    m = page.evaluate("""() => {
      const p = document.getElementById('up-flyout');
      const el = p.querySelector('mg-model-picker');
      const pr = p.getBoundingClientRect(), er = el.getBoundingClientRect();
      return {picker: {top: er.top, bottom: er.bottom, h: er.height},
              panel: {top: pr.top, bottom: pr.bottom},
              // How much of the picker is ACTUALLY on screen. "its top edge is inside the
              // box" is not enough: measured against the broken build at this viewport, the
              // top edge sat 9px above the panel's bottom edge -- technically inside, and
              // nine pixels of a 254px control is not a picker anyone can see or use.
              shown: Math.max(0, Math.min(pr.bottom, er.bottom) - Math.max(pr.top, er.top)),
              zIndex: getComputedStyle(p).zIndex};
    }""")
    assert m["picker"]["h"] > 40, "the picker mounted with no height"
    assert m["shown"] >= 120, (
        "only {:.0f}px of the picker is on screen (it sits at y={:.0f}, the panel's visible "
        "box is {:.0f}..{:.0f}) -- it opened below the fold, which reads as nothing "
        "happening".format(m["shown"], m["picker"]["top"], m["panel"]["top"],
                           m["panel"]["bottom"]))
    # It must also be ABOVE the lightbox it is opened over, not behind the picture.
    assert int(m["zIndex"]) > 300, "the flyout is behind the lightbox overlay"


def test_the_upscale_panel_offers_a_picker_when_the_model_is_unknown(logged_in_page):
    """An upscale is an i2i generation and every generation needs a model. Row 101 has none --
    the state a catalog that has never been swept is in, and the permanent state of anything
    imported from this computer, which has no PixAI task behind it at all.

    The panel must not guess one (guessing a model on an upscale silently restyles the
    picture) and must not simply refuse either (the upscale needs *a* model, not necessarily
    the original). So: submit stays disabled, the reason is named along with the command that
    fixes it, and the SAME picker the Generate drawer uses is offered.
    """
    page = logged_in_page(**DESKTOP)
    _visit(page, "/image/101")
    page.click("#upscale-btn")
    page.wait_for_selector("mg-upscale-panel[open]", state="attached")
    _settle(page)
    m = page.evaluate(_UPSCALE_JS)
    assert m["goDisabled"], "no model, but the panel would still submit"
    assert "backfill-full-meta" in m["text"], (
        "the panel must name the command that fixes it, not just refuse")
    assert m["pickerOffered"], "the owner must be able to pick a model rather than be blocked"
    # It is the shared component, not a bespoke model list built for this panel.
    assert page.evaluate("() => !!window.customElements.get('mg-model-picker')"), (
        "the detail page must load the shared picker the fallback mounts")


# ---------------------------------------------------------------------------
# 4. Deep Focus's veil vs the corner FABs  (stacking OUTCOME, not a z-index number)
# ---------------------------------------------------------------------------
_DF_STACKING_JS = """() => {
  const overlay = document.querySelector('.lv-overlay');
  const veil = document.querySelector('.lv-df-veil');
  const fab = document.getElementById('jobs-fab');
  const b = fab.getBoundingClientRect();
  // The one coordinate where the two provably overlap: the FAB's own centre. The veil is
  // position:fixed;inset:0, so it covers this point whenever it is painted at all.
  const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
  return {
    overlayClass: overlay.className,
    overlayZ: getComputedStyle(overlay).zIndex,
    veilPresent: !!veil,
    veilZ: veil ? getComputedStyle(veil).zIndex : null,
    veilCoversFab: !!veil && (() => {
      const v = veil.getBoundingClientRect();
      return v.left <= b.left && v.top <= b.top && v.right >= b.right && v.bottom >= b.bottom;
    })(),
    fabZ: getComputedStyle(fab).zIndex,
    fabDisplay: getComputedStyle(fab).display,
    hitIsFab: !!hit && !!hit.closest('#jobs-fab'),
    hitIsVeil: !!hit && !!hit.closest('.lv-df-veil'),
    hitDescription: hit ? (hit.id || String(hit.className) || hit.tagName) : null,
  };
}"""


def test_deep_focus_veil_wins_over_the_corner_fabs(logged_in_page):
    """Deep Focus must paint OVER #jobs-fab/#jobs-tray -- asserted as the effective
    stacking outcome (`elementFromPoint` where they overlap), not as a z-index number.

    Measured as shipped at 1280x900: `.lv-overlay.lv-overlay-df` computes z-index 450 and
    `#jobs-fab` 401 (both real, both live), the veil is inset:0 so it covers the FAB's
    31x79 box at (14, 781), and the hit test at that box's centre lands in `.lv-df-veil`.
    A z-index comparison alone would have MISSED the original bug entirely: 450 > 401 read
    correctly on paper the whole time, and the veil still lost, because it renders inside
    `.lv-overlay`'s 400 atom. Only the hit test sees that.

    Deep Focus is opened for real (double-click a board card, exactly as a user does), so
    this covers the JSX toggle and the CSS together. `loom/test/loom-df-veil-stacking.test.js`
    is the text-level guard on the same rule; this is the rendering one.
    """
    page = logged_in_page(**DESKTOP)
    # ?bundle=1 serves the committed esbuild bundle instead of transpiling the JSX in the
    # browser with Babel-standalone -- several seconds faster, and CI already has a
    # stale-bundle gate so it cannot drift from the source.
    _visit(page, "/loom?bundle=1")
    page.wait_for_selector(".lv-overlay")
    page.wait_for_selector(".lv-card")
    _freeze_motion(page)                       # re-applied: React injects its own <style>
    page.dblclick(".lv-card")                  # -> setDeepFocus(entry)
    page.wait_for_selector(".lv-df-veil")
    _settle(page)

    m = page.evaluate(_DF_STACKING_JS)
    assert m["fabDisplay"] != "none", "#jobs-fab is not rendered -- nothing to lose to"
    assert m["veilCoversFab"], "the veil does not cover the FAB, so the hit test proves nothing"
    assert m["hitIsVeil"] and not m["hitIsFab"], (
        "with Deep Focus open, the topmost element over #jobs-fab is {!r} (overlay z={}, "
        "fab z={}) -- the corner FABs are painting over the veil".format(
            m["hitDescription"], m["overlayZ"], m["fabZ"]))

    # --- phase 2: prove the guard bites. Drop the `.lv-overlay-df` modifier the JSX adds
    # while Deep Focus is open; that IS the pre-fix state (a 450 veil inside a 400 atom).
    page.evaluate("() => document.querySelector('.lv-overlay')"
                  ".classList.remove('lv-overlay-df')")
    _settle(page)
    reverted = page.evaluate(_DF_STACKING_JS)
    assert reverted["hitIsFab"] and not reverted["hitIsVeil"], (
        "removing .lv-overlay-df restored the pre-fix stacking and the veil STILL won "
        "the hit test ({!r}) -- the assertion above is vacuous".format(
            reverted["hitDescription"]))


# ---------------------------------------------------------------------------
# 4. Skins re-tint real components, and apply before first paint
# ---------------------------------------------------------------------------
# Four of the five skins (the fifth, "moonglade", is the tokens' own default -- no
# data-skin attribute at all).
_SKINS = ["moonglade", "nightfallen", "moonlit", "ember", "verdant"]

_READ_SKIN_JS = """(skin) => {
  if (skin === 'moonglade') document.documentElement.removeAttribute('data-skin');
  else document.documentElement.setAttribute('data-skin', skin);
  const root = getComputedStyle(document.documentElement);
  const header = document.querySelector('header');
  return {
    accentToken: root.getPropertyValue('--accent').trim(),
    headerBackground: getComputedStyle(header).backgroundColor,
    bodyBackground: getComputedStyle(document.body).backgroundColor,
  };
}"""


def test_skins_retint_real_components(logged_in_page):
    """Setting `data-skin` must re-tint an actual rendered component, not just redefine a
    custom property nothing consumes.

    Measured as shipped at 1280x900 -- `<header>`'s computed background-color, which reads
    `var(--mantle)`:
      moonglade   rgb(10, 8, 24)     nightfallen rgb(8, 6, 16)
      moonlit     rgb(8, 13, 21)     ember       rgb(18, 9, 9)
      verdant     rgb(8, 17, 13)
    Five distinct values, so the assertion is "all five differ", which is strictly stronger
    than the brief's "at least two".
    """
    page = logged_in_page(**DESKTOP)
    _visit(page, "/")
    _settle(page)

    seen = {s: page.evaluate(_READ_SKIN_JS, s) for s in _SKINS}
    headers = {s: v["headerBackground"] for s, v in seen.items()}
    assert len(set(headers.values())) == len(_SKINS), (
        "skins do not re-tint <header>: {}".format(headers))
    assert len({v["accentToken"] for v in seen.values()}) == len(_SKINS), (
        "the --accent token itself does not differ per skin: {}".format(
            {s: v["accentToken"] for s, v in seen.items()}))

    # --- phase 2: prove the guard bites, with the real regression shape -- a component
    # that hardcodes its colour instead of reading the token. The token keeps varying;
    # only the rendered component stops. A test that watched only --accent would miss this.
    page.add_style_tag(content="header { background: #000 !important; }")
    _settle(page)
    after = {s: page.evaluate(_READ_SKIN_JS, s) for s in _SKINS}
    assert len({v["headerBackground"] for v in after.values()}) == 1, (
        "a hardcoded header background was injected and the header STILL re-tinted -- the "
        "assertion above is vacuous")
    assert len({v["accentToken"] for v in after.values()}) == len(_SKINS), (
        "sanity: the tokens should still vary; only the component stopped tracking them")


# Records every data-skin mutation from the earliest moment a page script can observe one.
# `document` (not `document.documentElement`, which is still null at init-script time) with
# subtree:true is what makes this observable at all.
_SKIN_TRACE_INIT_JS = """
// Seed the saved skin HERE, in the same document that will read it, rather than in the
// previous one. Setting it before the reload leaves a window in which the outgoing page's
// own scripts can write `skin` again and clobber it -- the reloaded page then applies the
// server default and this fails looking exactly like a broken pre-paint script. Waiting for
// the page's first write (below) narrows that window but cannot close it: under load a
// later write lands after the wait returns. An init script runs before ANY page script in
// the new document, so there is no window left at all.
localStorage.setItem('skin', 'ember');
window.__skinTrace = [];
new MutationObserver(function (records) {
  records.forEach(function () {
    window.__skinTrace.push({
      value: document.documentElement.getAttribute('data-skin'),
      bodyExists: !!document.body,
      readyState: document.readyState,
    });
  });
}).observe(document, { attributes: true, subtree: true, attributeFilter: ['data-skin'] });
"""


def test_saved_skin_is_applied_before_the_body_exists(logged_in_page):
    """The no-flash (FOUC) arrangement, asserted at runtime instead of by grepping for the
    script's text.

    A saved skin is applied by an inline `<script>` in `<head>` specifically so the first
    paint is already tinted. `DESIGN_TOKENS_CSS` is one of T5-CSS's standing extraction
    exclusions for exactly this reason -- externalizing it would put a network round-trip
    in front of first paint. This is the guard that makes that exclusion enforceable.

    Measured as shipped: the first `data-skin` mutation is `value='ember'` with
    `document.body === null` and `readyState === 'loading'` -- i.e. during head parsing,
    before `<body>` is even parsed, therefore before any paint.
    """
    page = logged_in_page(**DESKTOP)
    _visit(page, "/")
    # THE RACE THIS TEST FIRST TRIPPED ON, and a live example of why nothing here sleeps:
    # static/mg-notify.js's syncSkin() reconciles the pre-paint guess against the server
    # ("server is source of truth") after /api/achievements resolves, and writes the result
    # to localStorage. Seeding 'ember' before that lands gets it overwritten with the
    # server's default, the reloaded page then has nothing to apply, and this test fails
    # looking exactly like a broken pre-paint script. Wait for that write, THEN seed.
    page.wait_for_function("() => localStorage.getItem('skin') !== null")

    # The seed itself now lives INSIDE the init script (see _SKIN_TRACE_INIT_JS) so nothing
    # in the outgoing document can clobber it between here and the reload. The wait above is
    # kept only to prove the app really does persist a skin -- if that ever stops being true
    # this test should fail loudly rather than silently testing our own seed.
    page.add_init_script(_SKIN_TRACE_INIT_JS)      # runs before any page script
    page.reload(wait_until="domcontentloaded")
    try:
        page.wait_for_function("() => window.__skinTrace && window.__skinTrace.length > 0")
    except _PlaywrightTimeout:
        # Turn "the pre-paint script is gone entirely" into a legible failure instead of a
        # bare timeout -- that is exactly what happened when this guard was demonstrated
        # against a source revert that moved the script out of <head>.
        pytest.fail("no data-skin mutation was observed at all: a saved skin is never "
                    "applied, so every load flashes the default theme first")
    first = page.evaluate("() => window.__skinTrace[0]")

    assert first["value"] == "ember", (
        "the saved skin was not the first thing applied (got {!r})".format(first["value"]))
    assert first["bodyExists"] is False and first["readyState"] == "loading", (
        "the saved skin was applied at readyState={!r} with body {} -- it is no longer "
        "running pre-paint in <head>, so the theme will flash".format(
            first["readyState"], "present" if first["bodyExists"] else "absent"))

    # --- phase 2: prove `bodyExists is False` is a discriminating measurement and not
    # something trivially true of every data-skin mutation.
    page.evaluate("() => document.documentElement.setAttribute('data-skin', 'verdant')")
    page.wait_for_function("() => window.__skinTrace.length > 1")
    later = page.evaluate("() => window.__skinTrace[window.__skinTrace.length - 1]")
    assert later["bodyExists"] is True, (
        "a post-load skin change was recorded with body absent -- the pre-paint assertion "
        "above cannot distinguish pre- from post-paint and is vacuous")
# ---------------------------------------------------------------------------
# 6. The Activity tray's QUEUED state, rendered -- and rendered IDENTICALLY on both hosts
# ---------------------------------------------------------------------------
# Owner complaint 2026-07-25: a plain generation "goes right to generated and spins until
# done. That's it." A task PixAI has accepted but never dispatched sits at a non-terminal
# status for ~60 minutes and used to draw the same spinning mascot as real work.
#
# Asserted the only way that can see it: read the mascot's COMPUTED animationName. Asserting
# the CSS text (`.jt-spin.jt-queued .jt-nel{animation:none}`) proves nothing about whether
# the class reaches the element or wins the cascade -- and the Loom overrides #jobs-tray CSS
# in its own <style>, which is precisely the shape of edit that could break one host and not
# the other (the tray's font-family already drifted that way once, 2026-07-21).
#
# _freeze_motion is deliberately NOT used here: it nulls every animation on the page, which
# would make "animationName is none" trivially true and this whole test vacuous.
_TRAY_QUEUED_JS = """() => {
  const item = document.querySelector('#jobs-tray .jt-item');
  const spin = item.querySelector('.jt-spin');
  const nel = spin.querySelector('.jt-nel');
  const ring = spin.querySelector('.gen-ring');
  const pill = item.querySelector('.jt-phase');
  const eta = item.querySelector('.jt-eta');
  return {
    hasQueuedClass: spin.classList.contains('jt-queued'),
    mascotAnimation: getComputedStyle(nel).animationName,
    ringAnimation: getComputedStyle(ring).animationName,
    pillText: pill ? pill.textContent.trim() : null,
    pillTransform: pill ? getComputedStyle(pill).textTransform : null,
    pillColor: pill ? getComputedStyle(pill).color : null,
    etaText: eta ? eta.textContent.trim() : null,
    // The row must still be a visible, laid-out row -- not collapsed to nothing by the
    // extra chips wrapping badly in the tray's 366px.
    rowWidth: Math.round(item.getBoundingClientRect().width),
    iconVisible: getComputedStyle(nel).display !== 'none',
  };
}"""

# One queued job, stubbed at /api/jobs rather than written into the harness server's own
# jobs.jsonl: the log's collapse/ageing behaviour has thorough coverage in
# tests/test_jobs.py, and what needs a browser is only how the tray DRAWS this record.
_QUEUED_JOB = {"jobs": [{
    "job_id": "2037594262049550370", "type": "generate", "label": "Generated",
    "status": "running", "started": False, "eta_seconds": 27,
    "ts": 0, "started_at": 0,
}]}


# row() writes `<img class="jt-nel" ... onerror="this.remove()">`, so on a throwaway catalog
# with no branding/ directory the mascot DELETES ITSELF and there is no element left to read
# an animationName off (this test's first run died exactly there). A real install has the
# file; served here as a 1x1 transparent PNG so the measured DOM matches a real one.
_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4zwAAAgIBAG4/xUwAAAAASUVORK5CYII=")


def _open_tray_with_queued_job(page, path):
    page.route("**/api/jobs", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(_QUEUED_JOB)))
    page.route("**/branding/gen_nel.png", lambda route: route.fulfill(
        status=200, content_type="image/png", body=_PIXEL_PNG))
    page.goto(path, wait_until="domcontentloaded")
    # The fab is what a user clicks; JobsCard.applyState() reveals it on DOMContentLoaded.
    page.wait_for_selector("#jobs-fab.show")
    page.click("#jobs-fab")
    page.wait_for_selector("#jobs-tray.open #jobs-tray .jt-item, #jobs-tray.open .jt-item")
    _settle(page)


def test_queued_generation_stops_the_spinner_on_both_hosts(logged_in_page):
    """The gallery and the Loom load ONE static/mg-notify.js, so the queued state must be
    measurably identical on both -- that is the claim, and this measures it rather than
    inferring it from the file being shared.

    Measured as shipped at 1280x900, on `/` and on `/loom?bundle=1` alike: the icon carries
    `jt-queued`, the mascot's and ring's computed animationName are both `none` (a rendering
    job reads `gen-spin`), the phase pill reads "queued" uppercased, and the estimate chip
    reads "est. 27s wait".
    """
    seen = {}
    for host, path in (("gallery", "/"), ("loom", "/loom?bundle=1")):
        page = logged_in_page(**DESKTOP)
        _open_tray_with_queued_job(page, path)
        m = page.evaluate(_TRAY_QUEUED_JS)
        seen[host] = m

        assert m["hasQueuedClass"], (
            "{}: the queued row's icon has no jt-queued modifier".format(host))
        assert m["mascotAnimation"] == "none", (
            "{}: the mascot is still animating ({!r}) on a job PixAI has not started -- "
            "motion is what reads as work in progress".format(host, m["mascotAnimation"]))
        assert m["ringAnimation"] == "none", (
            "{}: the progress ring is still spinning ({!r})".format(
                host, m["ringAnimation"]))
        assert m["pillText"] == "queued", (
            "{}: phase pill reads {!r}".format(host, m["pillText"]))
        assert m["pillTransform"] == "uppercase", (
            "{}: the phase pill is not styled as a state label ({!r})".format(
                host, m["pillTransform"]))
        assert m["etaText"] == "est. 27s wait", (
            "{}: estimate chip reads {!r}".format(host, m["etaText"]))
        assert m["iconVisible"] and m["rowWidth"] > 200, (
            "{}: the queued row did not lay out ({!r})".format(host, m))

        # --- phase 2, per host: prove the measurement discriminates. Dropping the modifier
        # is the pre-fix state exactly (one spinner for queued and rendering alike); if the
        # animation stays `none` without it, the assertions above are vacuous.
        page.evaluate("() => document.querySelector('#jobs-tray .jt-spin')"
                      ".classList.remove('jt-queued')")
        _settle(page)
        reverted = page.evaluate(_TRAY_QUEUED_JS)
        assert reverted["mascotAnimation"] == "gen-spin", (
            "{}: removing jt-queued left the mascot's animationName at {!r} -- the "
            "'none' assertion above proves nothing".format(
                host, reverted["mascotAnimation"]))
        assert reverted["ringAnimation"] == "gen-spin", (
            "{}: removing jt-queued left the ring at {!r}".format(
                host, reverted["ringAnimation"]))

    assert seen["gallery"] == seen["loom"], (
        "the shared Activity tray renders the queued state DIFFERENTLY on the two hosts:\n"
        "  gallery: {!r}\n  loom:    {!r}".format(seen["gallery"], seen["loom"]))




