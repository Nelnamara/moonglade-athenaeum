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
* **Real login, no bypass.** `pixai_gallery.py`'s `_is_authorized_request()` has no
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
"""
import json
import threading

import pytest

import pixai_gallery_backup as core
from pixai_gallery import CATALOG_FIELDS, create_app, save_catalog

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
        for i in range(6)
    ])
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
_FLYOUT_RECT_JS = """() => {
  const f = document.getElementById('model-flyout');
  const r = f.getBoundingClientRect().toJSON();
  r.innerWidth = window.innerWidth;
  r.innerHeight = window.innerHeight;
  return r;
}"""


def _assert_flyout_within_viewport(rect):
    assert rect["width"] > 0 and rect["height"] > 0, "flyout has no box -- did it open?"
    assert rect["top"] >= 0, (
        "#model-flyout's top is {:.1f}px -- it is hanging above the viewport".format(
            rect["top"]))
    assert rect["bottom"] <= rect["innerHeight"], (
        "#model-flyout's bottom is {:.1f}px past the {:.0f}px viewport".format(
            rect["bottom"] - rect["innerHeight"], rect["innerHeight"]))
    assert rect["left"] >= 0, (
        "#model-flyout's left is {:.1f}px -- it is hanging off the left edge".format(
            rect["left"]))
    assert rect["right"] <= rect["innerWidth"], (
        "#model-flyout's right is {:.1f}px past the {:.0f}px viewport".format(
            rect["right"] - rect["innerWidth"], rect["innerWidth"]))


def test_model_flyout_is_fully_inside_the_viewport_at_desktop(logged_in_page):
    """Measured as shipped at 1280x900: top 0, bottom 900 (== innerHeight), left 489,
    right 861. Exactly flush at the bottom, which is why `<=` and not `<`."""
    page = logged_in_page(**DESKTOP)
    _stub_model_search(page)
    _visit(page, "/")
    _open_drawer_and_model_flyout(page)
    _assert_flyout_within_viewport(page.evaluate(_FLYOUT_RECT_JS))


@pytest.mark.xfail(strict=False, reason=(
    "KNOWN, being fixed in another worktree right now (docs/AUDIT_2026-07-21.md T5-CSS): "
    "at <=480px both mobile @media rules use bare id selectors and lose to later base "
    "rules at equal specificity, so #model-flyout keeps its desktop right:100%/height:100% "
    "geometry and lands at y = -332.9px -- half above the viewport. strict=False on "
    "purpose: this flips to XPASS on its own the moment that fix lands, and starts failing "
    "again if it ever regresses. Do not delete or weaken it to get green."))
def test_model_flyout_is_fully_inside_the_viewport_at_mobile_portrait(logged_in_page):
    """Same assertion, 375x812. Measured as shipped: top -332.9, bottom 332.9."""
    page = logged_in_page(**MOBILE_PORTRAIT)
    _stub_model_search(page)
    _visit(page, "/")
    _open_drawer_and_model_flyout(page)
    _assert_flyout_within_viewport(page.evaluate(_FLYOUT_RECT_JS))


# ---------------------------------------------------------------------------
# 3. Deep Focus's veil vs the corner FABs  (stacking OUTCOME, not a z-index number)
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
    page.evaluate("() => localStorage.setItem('skin', 'ember')")

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
