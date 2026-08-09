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

Every assertion below is a regression guard written the only way that can actually see
this class of defect: drive a REAL browser against a REAL server and measure the
resulting layout / stacking / computed style.

2026-08-08, the classic-UI cut: the classic pages (/classic, /image/<id>, their inline
JS) were deleted, and every guard that DROVE a classic page went with them -- the four
numbered defects above were classic-flyout/drawer layout bugs and are historical context
now, not live subjects. What remains here targets the two surviving hosts: the React
shell at "/" (which still ships the pre-paint skin script, the design tokens with every
skin, and the shared Activity tray -- since the 2026-08-08 React port that tray is
gallery/src/notify/ActivityTray.jsx + gallery/src/styles/notify.css, bundled into BOTH
hosts, not static/mg-notify.js, which is deleted) and the Loom at /loom.

Design, and why
---------------
* **A live server, not Flask's test client.** A test client never renders. The real app is
  bound to an ephemeral port (`make_server(..., 0, ...)`) in a daemon thread against a
  throwaway catalog, started once for the module so the cost is paid once.
* **Real login, no bypass.** `moonglade_gallery.py`'s `_is_authorized_request()` has no
  localhost bypass and re-validates the session against `config.json`'s `AUTH_USERS` on
  every request, so the harness drives the real React login page (GET /login serves the
  shell; its form fetches POST /api/login) with a real scrypt-hashed account made by
  `core.add_or_update_web_user` -- the same endpoint `tests/conftest.py`'s
  `login_client()` helpers post to for the test client. Nothing here weakens an auth path.
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
from moonglade_gallery import (
    CATALOG_FIELDS, create_app, load_catalog, save_catalog,
    achievement_metrics, compute_achievements, save_ach_state,
    telem_flag, telemetry_metrics, load_telemetry,
)

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

# Kill every transition/animation so a geometry read can never catch an interpolated
# mid-flight value. `*` + !important beats the app's id-selector rules; applied to the
# document under test, never to committed CSS.
_FREEZE_MOTION_CSS = (
    "*, *::before, *::after {"
    " transition: none !important; transition-duration: 0s !important;"
    " animation: none !important; animation-duration: 0s !important; }"
)

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
        # so a fake size would make every assertion about the cap meaningless.
        | ({"width": "900", "height": "600", "model_id": "4242",
            "model_name": "Harness Model", "prompt_full": "harness prompt"} if i == 0 else {})
        # Row 1 is the half-swept state: the size is known but the model never was. That is
        # what a locally imported file looks like once it has a thumbnail, and what any row
        # predating a full meta sweep looks like. It exists so the "no model" case can be
        # tested on its OWN -- the other bare rows also have no size, which disables the
        # ratio slider for an unrelated reason and would mask what is being measured.
        | ({"width": "900", "height": "600"} if i == 1 else {})
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
    # This module's tests assume an already-onboarded install (the real gallery, not the
    # first-run Setup Wizard) -- next_gallery()'s boot payload now computes needs_key from
    # a fresh config.json read, and this fixture's config would otherwise have none.
    # test_setup_wizard_onboards_a_genuinely_fresh_install below gets its OWN dedicated
    # server with no key and an empty catalog, precisely so it can exercise the state this
    # one is deliberately configured out of.
    cfg = json.loads(config_path.read_text()) if config_path.exists() else {}
    cfg["PIXAI_API_KEY"] = "sk-render-harness-fake"
    config_path.write_text(json.dumps(cfg))

    # Same "already-onboarded" reasoning as the API key above, extended to achievements.
    # Two pieces, both load-bearing:
    #
    # 1. The Under-the-Hood earn-state. The Branding tab is gated behind the real
    #    `under-the-hood` feat (owner decision 2026-08-05, `brandingUnlocked` in
    #    useControlPanel.js) -- and conftest's autouse `_isolated_branding` fixture
    #    (correctly) points branding_root() at an empty per-test tmp dir, so the
    #    sweep_telemetry()/sweep_branding_drops() earn paths can never fire in a test:
    #    no marks, nothing to adopt, feat never earned, ✦ Branding button never
    #    renders. test_control_panel_runs_real_jobs_and_manages_a_real_account has been
    #    failing on exactly that since the gate landed (verified: identical failure on
    #    the pre-gate-session baseline; NOT an isolation leak -- the isolation is doing
    #    its job, the gate just shipped without updating this harness). The telemetry
    #    flag below is the REAL persisted earn-state (sweep_branding_drops fires this
    #    exact flag on a real adoption), scoped to this module's own out_dir --
    #    per-test-tmp-independent, no real branding folder involved.
    telem_flag("branding_custom_file", out_dir=root)
    #
    # 2. Everything earned is pre-marked SEEN, so no toast fires on page load. A truly
    #    fresh state file makes every already-earned achievement "newly earned" on first
    #    fetch, and the celebration overlay (.ach-m2 -- a deliberate full-screen,
    #    click-or-timeout-to-dismiss design, not a bug) blocks every click under it for
    #    4.2-6.4s per achievement. Computed the same way api_achievements itself does
    #    (catalog metrics + telemetry metrics + telemetry sets), so `seen` covers
    #    exactly what the server will report as earned.
    import datetime as _dt
    _telem = load_telemetry(root)
    _metrics = achievement_metrics(root / "catalog.db")
    _metrics.update(telemetry_metrics(root))
    _ach_result = compute_achievements(_metrics, sets=_telem.get("sets", {}))
    _today = _dt.date.today().isoformat()
    _earned_ids = [a["id"] for a in _ach_result["achievements"] if a["earned"]]
    save_ach_state(root, {"seen": _earned_ids, "earned_at": {i: _today for i in _earned_ids}})

    server = make_server("127.0.0.1", 0, create_app(root), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True,
                              name="render-harness-server")
    thread.start()
    try:
        yield SimpleNamespace(
            base_url="http://127.0.0.1:%d" % server.server_port,
            config_path=config_path, root=root)
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
def _dismiss_any_achievement_toast(page):
    """Click-dismiss a real achievement celebration (.ach-m2) if one happens to be up.

    render_server's fixture pre-seeds `seen` from the harness's INITIAL catalog state
    (suppresses the page-load toast), but a test's own real actions -- a job run, an
    account add -- can organically cross a NEW achievement threshold mid-test (telemetry
    counters, day/session flags), firing a fresh one the pre-seed can't have predicted.
    `.ach-m2` is a deliberate full-screen, click-or-timeout-to-dismiss overlay (by design,
    not a bug -- see `_play()` in gallery/src/notify/ach.js, the 2026-08-08 React-port home
    of the celebration engine), so left alone it blocks every click under it for its real
    4.2-6.4s hold. A no-op when nothing is showing.
    """
    toast = page.locator(".ach-m2")
    if toast.count():
        toast.first.click(timeout=1000)
        page.wait_for_selector(".ach-m2", state="detached", timeout=2000)
def _login(page):
    """Post the real /login form. No bypass, no fabricated session cookie.

    LoginPage.jsx's submit is async (fetch POST /api/login, then a CLIENT-SIDE
    window.location.href navigation on success) -- unlike a native HTML form
    submit, page.click() itself only waits for the click event to dispatch, not
    for that fetch-then-navigate chain. A plain wait_for_load_state right after
    the click can resolve against the CURRENT, already-settled /login page
    before the real navigation has even started (2026-08-02, caught live: the
    POST really did complete, but page.url was still /login afterward).
    expect_navigation ties the wait to the actual navigation instead, whenever
    it actually happens -- the same fix works for a synchronous native submit
    too, so this isn't React-specific plumbing leaking into a shared helper."""
    page.goto("/login", wait_until="domcontentloaded")
    page.fill("input[name=username]", _USERNAME)
    page.fill("input[name=password]", _PASSWORD)
    with page.expect_navigation(wait_until="networkidle"):
        page.click("button[type=submit]")
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
    # The floating side panels (the real floating-glass-panel design, 2026-08-05 rebuild)
    # open OVER the board, each with its own backdrop -- while either is up, no board
    # card is clickable, by design. A real user collapses them first (each panel's own
    # ‹/› button), so the test does exactly that. This test predates the floating
    # rebuild; it used to reach the card directly because the old panels were docked
    # siblings, not overlays.
    for side in ("left", "right"):
        if page.locator(".lv-panel." + side).count():
            page.click(".lv-panel." + side + " .lv-col")
            page.wait_for_selector(".lv-panel." + side, state="detached")
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

    Since the classic cut this measures the React shell at "/" -- its sticky
    `<header class="mgx-hdr">` reads `var(--mantle)` exactly as classic's header did
    (gallery/src/styles/shell.css), so the measured values are unchanged.
    """
    page = logged_in_page(**DESKTOP)
    _visit(page, "/")
    page.wait_for_selector("header")     # the React bundle must mount App first
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

    Since the classic cut this measures the React shell at "/" -- NEXT_PAGE carries the
    same pre-paint inline script in `<head>`, and (2026-08-08 port note) the post-load
    syncSkin() reconcile this test's seeding dance exists for now lives in
    gallery/src/notify/ach.js, bundled into "/" -- same behaviour, new home.
    """
    page = logged_in_page(**DESKTOP)
    _visit(page, "/")
    # THE RACE THIS TEST FIRST TRIPPED ON, and a live example of why nothing here sleeps:
    # syncSkin() (gallery/src/notify/ach.js since the 2026-08-08 React port; check() runs
    # it from installNotify()) reconciles the pre-paint guess against the server
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
# the CSS text (`.jt-spin.jt-queued .jt-nel{animation:none}` -- since the 2026-08-08 React
# port it lives in gallery/src/styles/notify.css, verbatim) proves nothing about whether
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


# The tray row renders `<img class="jt-nel" ...>` with an onError handler that REMOVES the
# element (ActivityTray.jsx's Row since the 2026-08-08 React port -- same self-delete the
# vanilla row() had), so on a throwaway catalog with no branding/ directory the mascot
# DELETES ITSELF and there is no element left to read an animationName off (this test's
# first run died exactly there). A real install has the file; served here as a 1x1
# transparent PNG so the measured DOM matches a real one.
_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4zwAAAgIBAG4/xUwAAAAASUVORK5CYII=")


def _open_tray_with_queued_job(page, path):
    page.route("**/api/jobs", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(_QUEUED_JOB)))
    page.route("**/branding/nel_spinner.png", lambda route: route.fulfill(
        status=200, content_type="image/png", body=_PIXEL_PNG))
    page.goto(path, wait_until="domcontentloaded")
    # The fab is what a user clicks. 2026-08-08 port note: the vanilla's
    # JobsCard.applyState() reveal-on-DOMContentLoaded is now ActivityTray.jsx rendering
    # #jobs-fab with class "show" whenever the tray is closed (installNotify() ->
    # jobsStore.start() has already run by the time the bundle mounts) -- same selector,
    # same first observable state.
    page.wait_for_selector("#jobs-fab.show")
    page.click("#jobs-fab")
    page.wait_for_selector("#jobs-tray.open #jobs-tray .jt-item, #jobs-tray.open .jt-item")
    _settle(page)


def test_queued_generation_stops_the_spinner_on_both_hosts(logged_in_page):
    """The gallery and the Loom render ONE shared tray source -- since the 2026-08-08 React
    port that is gallery/src/notify/ActivityTray.jsx + gallery/src/styles/notify.css, built
    into TWO separate bundles (Vite's app.css for "/", esbuild's
    master-storyboard.bundle.css for /loom) -- so the queued state must be measurably
    identical on both. That is the claim, and this measures it rather than inferring it
    from the source being shared: two build pipelines is exactly how one host's bundle
    could go stale while the other moves on.

    Measured as shipped at 1280x900, on `/` and on `/loom?bundle=1` alike: the icon carries
    `jt-queued`, the ring's computed animationName is `none` (a rendering job reads
    `gen-spin`), the phase pill reads "queued" uppercased, and the estimate chip reads
    "est. 27s wait". The mascot's own animationName is checked too but is ALWAYS `none`,
    queued or not -- since the 2026-08-09 fix (owner: "spins weirdly offset") the portrait
    never animates by design (object-position:60% 32% crops it off-center to frame the face;
    rotating that asymmetric crop as a rigid unit made the face itself tumble through every
    orientation), so the ring alone is the real discriminator now.
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
            "{}: the mascot has an animationName again ({!r}) -- it must never spin (an "
            "asymmetric object-position crop tumbles the face when rotated as a rigid unit, "
            "the 2026-08-09 bug); this should hold true regardless of queued/running state, "
            "not just here".format(host, m["mascotAnimation"]))
        assert m["ringAnimation"] == "none", (
            "{}: the progress ring is still spinning ({!r}) on a job PixAI has not started -- "
            "motion is what reads as work in progress".format(host, m["ringAnimation"]))
        assert m["pillText"] == "queued", (
            "{}: phase pill reads {!r}".format(host, m["pillText"]))
        assert m["pillTransform"] == "uppercase", (
            "{}: the phase pill is not styled as a state label ({!r})".format(
                host, m["pillTransform"]))
        assert m["etaText"] == "est. 27s wait", (
            "{}: estimate chip reads {!r}".format(host, m["etaText"]))
        assert m["iconVisible"] and m["rowWidth"] > 200, (
            "{}: the queued row did not lay out ({!r})".format(host, m))

        # --- phase 2, per host: prove the RING measurement discriminates (the mascot's own
        # animationName can't -- it's always "none", queued or not, since the 2026-08-09 fix).
        # Dropping the modifier is the pre-fix state exactly (one spinner for queued and
        # rendering alike); if the ring's animation stays `none` without it, the assertion
        # above proves nothing.
        page.evaluate("() => document.querySelector('#jobs-tray .jt-spin')"
                      ".classList.remove('jt-queued')")
        _settle(page)
        reverted = page.evaluate(_TRAY_QUEUED_JS)
        assert reverted["ringAnimation"] == "gen-spin", (
            "{}: removing jt-queued left the ring at {!r}".format(
                host, reverted["ringAnimation"]))

    assert seen["gallery"] == seen["loom"], (
        "the shared Activity tray renders the queued state DIFFERENTLY on the two hosts:\n"
        "  gallery: {!r}\n  loom:    {!r}".format(seen["gallery"], seen["loom"]))


# ---------------------------------------------------------------------------
# 7. Import overlay -- real files, through the real control, land in the real catalog
# ---------------------------------------------------------------------------
def test_import_overlay_uploads_real_files_and_updates_the_catalog(logged_in_page, render_server):
    """ImportOverlay.jsx (2026-08-02) is a straight port of classic's real, working
    ImportUI onto the React front door -- POST /api/import-local never changed; see
    tests/test_import_local.py for that contract's own thorough coverage (naming,
    zip-slip, localhost-only). What has NOT been proven anywhere else is that the new
    component actually drives it: a real <input type=file>, real multipart bytes, and
    the post-import refresh that is supposed to make a brand-new collection show up in
    the SAME overlay's own picker without a page reload (afterMutation -> fetchCollections
    -> setCollections in App.jsx). A component that renders perfectly but posts the wrong
    field name, or never re-fetches collections, would pass every other test in this
    repo and still be broken -- which is exactly the class of defect this harness exists
    to catch (see the module docstring).
    """
    from PIL import Image

    page = logged_in_page(**DESKTOP)
    _visit(page, "/")

    # Two real, DIFFERENT-sized PNGs: de-dupe is by (name, size), so same-size fixtures
    # would not prove the picker keeps both rows independently.
    f1 = render_server.root / "mgim_upload_a.png"
    f2 = render_server.root / "mgim_upload_b.png"
    Image.new("RGB", (40, 40), (10, 200, 10)).save(f1)
    Image.new("RGB", (80, 80), (200, 10, 10)).save(f2)
    coll_name = "mgim-harness-import"

    page.click('nav[aria-label="Destinations"] button:has-text("Import")')
    page.wait_for_selector('[aria-label="Import into your library"]')
    _settle(page)
    assert "Drop images" in page.inner_text('[aria-label="Import into your library"]'), (
        "the empty-state drop zone did not render")

    page.set_input_files("#mgim-file-input", [str(f1), str(f2)])
    page.wait_for_function("() => document.querySelectorAll('.mgim-row').length === 2")
    names = page.eval_on_selector_all(".mgim-nm", "els => els.map(e => e.textContent)")
    assert set(names) == {"mgim_upload_a.png", "mgim_upload_b.png"}, (
        "the staged rows do not show the two real filenames: {}".format(names))

    # Pick "+ New collection..." and name it -- the inline-entry path, not the plain list.
    page.click(".mgim-collpick")
    page.wait_for_selector(".mgim-collmenu")
    page.click(".mgim-collopt.new")
    page.fill(".mgim-collinput", coll_name)

    page.click(".mgim-go")
    page.wait_for_selector(".mgim-result.ok")
    result_text = page.inner_text(".mgim-result.ok")
    assert "Imported" in result_text and "2" in result_text, (
        "the success banner does not report 2 imported files: {!r}".format(result_text))
    assert coll_name in result_text, (
        "the success banner does not name the collection: {!r}".format(result_text))

    # --- backend truth: real bytes on disk, real catalog rows, source='local' ---
    stored = sorted(p.name for p in (render_server.root / "imported").glob("mgim_upload_*"))
    assert len(stored) == 2, (
        "expected 2 real files copied into imported/, found {}".format(stored))
    rows = [r for r in load_catalog(render_server.root / "catalog.db")
            if r.get("source") == "local" and "mgim_upload" in (r.get("filename") or "")]
    assert len(rows) == 2, "expected 2 new catalog rows for the uploaded files, found {}".format(
        len(rows))
    assert all(coll_name in (r.get("collections") or "") for r in rows), (
        "the uploaded rows are not tagged with the collection entered in the picker: {}".format(
            [r.get("collections") for r in rows]))

    # --- the wiring this test exists for: close, reopen, and the NEW collection must
    # already be offered -- proving afterMutation's fetchCollections() round-trip landed
    # in React state, not just that the server persisted it. The picker (and its menu) only
    # exist once a file is staged, so a third file gets the fresh instance to that branch. ---
    page.click('[aria-label="Import into your library"] button[aria-label="Close"]')
    page.wait_for_selector('[aria-label="Import into your library"]', state="detached")
    page.click('nav[aria-label="Destinations"] button:has-text("Import")')
    page.wait_for_selector('[aria-label="Import into your library"]')
    _settle(page)
    f3 = render_server.root / "mgim_upload_c.png"
    Image.new("RGB", (20, 20), (10, 10, 200)).save(f3)
    page.set_input_files("#mgim-file-input", [str(f3)])
    page.wait_for_selector(".mgim-collpick")
    page.click(".mgim-collpick")
    page.wait_for_selector(".mgim-collmenu")
    offered = page.eval_on_selector_all(
        ".mgim-collopt", "els => els.map(e => e.textContent)")
    assert coll_name in offered, (
        "the collection created a moment ago is not offered on reopen ({!r}) -- the "
        "post-import refresh did not reach the picker without a full page reload".format(
            offered))


# ---------------------------------------------------------------------------
# 9. Control Panel -- a real safe job, a real account added and removed, real
#    branding writes, and the power modal's real ping-poll reconnect (stubbed only
#    where running it for real would kill this module's own shared server)
# ---------------------------------------------------------------------------
def test_control_panel_runs_real_jobs_and_manages_a_real_account(logged_in_page, monkeypatch):
    """ControlPanelOverlay.jsx (2026-08-02) ports classic's /panel page as a modal (owner's
    live correction: "Control panel is now ALSO modal. no separate pages anymore"). Every
    action it drives is real, pre-existing backend -- this proves the wiring end to end
    against render_server's real (if throwaway) config and catalog, EXCEPT server
    stop/restart, which are stubbed: running them for real would kill the module-scoped
    server every other test in this file still needs.

    subprocess.Popen is mocked for the job-console step, matching EVERY test in
    tests/test_panel.py (none of them spawn a real subprocess either -- that is the CLI's
    own test suite's job, not this route's). The real thing this test proves is
    unique to it: that the REACT COMPONENT drives /api/panel/run + /api/panel/status
    correctly, not that a maintenance subprocess itself runs -- that part is already
    covered thoroughly elsewhere.
    """
    # Restart is disabled client-side unless the server reports itself supervised
    # (summary.supervised, from _supervised() -- os.environ["MOONGLADE_SUPERVISED"]).
    # This harness's server isn't launched via Serve Gallery, so without this the Restart
    # button would be a disabled no-op and this test could never reach it for real.
    monkeypatch.setenv("MOONGLADE_SUPERVISED", "1")

    import subprocess as _subprocess
    import io as _io
    import time as _time

    class _FakeProc:
        """A brief, deliberate delay before wait() -- an instant-return fake would let the
        background reader thread finish before Playwright's own wait_for_selector ever gets
        a chance to observe the transient 'running' view at all (caught live: the first
        version of this test timed out waiting on a state that had already come and gone
        in milliseconds). Still far faster than a real subprocess spin-up, just not
        literally zero."""
        def __init__(self):
            self.stdout = _io.StringIO("scanning catalog...\n✓ 6 rows checked\n")
        def wait(self):
            _time.sleep(0.6)
            return 0
    monkeypatch.setattr(_subprocess, "Popen", lambda *a, **k: _FakeProc())

    page = logged_in_page(**DESKTOP)
    _visit(page, "/")
    _settle(page)

    page.click('nav[aria-label="Destinations"] button:has-text("Panel")')
    page.wait_for_selector('[aria-label="Control Panel"]')
    _settle(page)
    # innerText reflects the CSS text-transform:uppercase on .mgcp-sidekick, not the raw
    # JSX literal ("The library") -- assert what actually renders.
    assert "THE LIBRARY" in page.inner_text('[aria-label="Control Panel"]')

    # --- a REAL safe job: Catalog stats, via the REAL /api/panel/run + /api/panel/status
    # this harness's own real (throwaway) catalog answers. The row's own text ("Catalog
    # stats") and its run button ("run ▸") are siblings, not nested -- select the row
    # by its text, then the button within it. ---
    page.click('.mgcp-checkrow:has-text("Catalog stats") button.mgcp-run')
    page.wait_for_selector(".mgcp-running")
    page.wait_for_selector(".mgcp-running", state="detached")
    assert not page.locator(".mgcp-runerr").count(), (
        "a real, non-destructive job (--catalog-stats) failed against the harness's own "
        "real catalog: {!r}".format(page.locator(".mgcp-runerr").all_inner_texts()))
    # Regression guard (2026-08-02 review): the finished job's own output used to be
    # discarded the instant `running` cleared, so the idle grid never showed a
    # read-only Check action's actual result -- the entire point of running one.
    page.wait_for_selector(".mgcp-runresult")
    assert "6 rows checked" in page.inner_text(".mgcp-runresult")

    # --- Trash sub-overlay: real /api/trash/list against a genuinely empty quarantine. ---
    page.click('div.mgcp-tile:has-text("Trash")')
    page.wait_for_selector('[aria-label="Trash"]')
    assert "Nothing in the trash" in page.inner_text('[aria-label="Trash"]')
    page.click('[aria-label="Trash"] button[aria-label="Close"]')
    page.wait_for_selector('[aria-label="Trash"]', state="detached")

    # --- Users sub-overlay: a REAL account added, then REAL-removed via
    # /api/users/add|remove -- proving CSRF, the real add/remove contract, and that the
    # Panel's own account list refreshes without a page reload. ---
    page.click('div.mgcp-tile:has-text("Accounts")')
    page.wait_for_selector('[aria-label="Accounts"]')
    page.fill('[aria-label="Accounts"] input[placeholder="username"]', "harness-added-user")
    page.fill('[aria-label="Accounts"] input[placeholder="password"]', "a-real-test-password-2")
    page.fill('[aria-label="Accounts"] input[placeholder="confirm"]', "a-real-test-password-2")
    page.click('[aria-label="Accounts"] button:has-text("+ Add")')
    page.wait_for_function(
        "() => document.body.innerText.includes('harness-added-user')")
    # .mgcp-useraction is shared with the (2026-08-02) "reset password..." control added
    # to the same row for local sessions -- disambiguate by the real button text.
    page.click('.mgcp-userrow:has-text("harness-added-user") button:has-text("remove")')
    page.wait_for_function(
        "() => !document.body.innerText.includes('harness-added-user')")
    page.click('[aria-label="Accounts"] button[aria-label="Close"]')
    page.wait_for_selector('[aria-label="Accounts"]', state="detached")

    # --- Branding tab: a REAL POST /api/branding, picking a real animation from the
    # real MARK_ANIMS list this harness's own out_dir/branding.json now persists.
    # (The tab is achievement-gated -- see render_server's telem_flag seeding.) ---
    _dismiss_any_achievement_toast(page)
    page.click('button:has-text("✦ Branding")')
    page.wait_for_selector(".mgcp-brandgrid")
    # The 2026-08-06 rebuild: anims are Title-cased chips in the default
    # "Icons, marks & animation" section (Control Panel.dc.html:922-927's chip form
    # over the real MARK_ANIMS values -- "glow" renders as "Glow").
    page.click('.mgcp-animchip:has-text("Glow")')
    page.wait_for_function(
        "() => { const el = document.querySelector('.mgcp-animchip.on'); "
        "return el && el.textContent === 'Glow'; }")

    # --- Power modal: the client-side ping-poll reconnect logic (ported from classic's
    # real _watchServer()), proven against STUBBED /api/server/restart + /api/ping --
    # the real routes would actually kill this module's shared server. The Server section
    # lives in the sidebar, a sibling of the tab content, so it's visible on either tab. ---
    page.route("**/api/server/restart", lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"ok": true, "action": "restart"}'))
    ping_calls = {"n": 0}

    def _ping(route):
        ping_calls["n"] += 1
        # First two calls: still down (the real gap _watchServer() waits to see before it
        # will ever reload). Third call onward: back up -- sawDown was already true by
        # then, so THIS is the call that triggers the real reload.
        if ping_calls["n"] <= 2:
            route.fulfill(status=503, content_type="application/json", body="{}")
        else:
            route.fulfill(status=200, content_type="application/json", body='{"ok": true}')
    page.route("**/api/ping", _ping)

    # Restart now arms on the first click ("Confirm -- Restart?") and only actually fires
    # on the second (2026-08-02 fix -- classic gates the same action behind window.confirm,
    # and the first version of this component fired immediately with zero confirmation).
    page.click('button:has-text("⟳ Restart")')
    page.wait_for_selector('button:has-text("Confirm — Restart?")')
    page.click('button:has-text("Confirm — Restart?")')
    page.wait_for_selector(".mgcp-pwr-card")
    assert "Restarting" in page.inner_text(".mgcp-pwr-title")
    # The stubbed sequence genuinely drives the component to its real
    # window.location.reload() call, on its own timer. ControlPanelOverlay is a modal
    # over the still-mounted App/NavSpine (not a page replacement like LoginPage/
    # SetupWizard), so the nav bar never disappears and is no signal of a reload at all
    # -- caught live: an earlier version of this assertion waited on the nav and passed
    # instantly, before the ping interval had even ticked once. The Panel's OWN dialog
    # detaching is the real signal: only a full reload resets the React tree that owns it.
    page.wait_for_selector('[aria-label="Control Panel"]', state="detached", timeout=15_000)
    assert ping_calls["n"] >= 3, "the reload fired before the down-then-up sequence completed"



# ---------------------------------------------------------------------------
# 8. Setup Wizard -- a genuinely fresh install, real key save, real needs_key flip,
#    live sync progress, and the honest failure path
# ---------------------------------------------------------------------------
@pytest.fixture()
def fresh_install_server(tmp_path_factory, monkeypatch):
    """A genuinely fresh install: empty catalog, no PIXAI_API_KEY -- exactly the state
    SetupWizard exists for. Its OWN server, separate from the module's shared
    `render_server` -- that fixture is deliberately configured OUT of this state (see its
    own comment) so the rest of the module can keep assuming an already-onboarded install;
    this is the one test that needs the state it was configured out of."""
    import logging
    from types import SimpleNamespace

    from werkzeug.serving import make_server

    wz_log = logging.getLogger("werkzeug")
    wz_level = wz_log.level
    wz_log.setLevel(logging.ERROR)

    root = tmp_path_factory.mktemp("render-harness-fresh")
    config_path = root / "config.json"
    monkeypatch.setenv("MOONGLADE_DISABLE_WATCH", "1")
    monkeypatch.setattr(core, "_config_path", lambda: config_path)
    monkeypatch.setattr(core, "_cfg", {})
    # /api/setup/save-key deliberately does NOT go through core._config_path() (see its
    # own docstring) -- it derives its path from core.__file__'s directory instead, the
    # exact mechanism tests/test_setup_wizard.py's own _redirect_config_to() patches.
    # MISSING THIS ONCE caused a real test to overwrite the checkout's actual config.json
    # with a fake key, live, 2026-08-02 -- caught immediately by checking the file, but
    # never again: both path mechanisms this route family can use must be redirected.
    monkeypatch.setattr(core, "__file__", str(root / "moonglade_backup.py"))
    save_catalog(root / "catalog.db", [])          # genuinely empty -- no rows at all
    core.add_or_update_web_user(_USERNAME, _PASSWORD)

    server = make_server("127.0.0.1", 0, create_app(root), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True,
                              name="render-harness-fresh-server")
    thread.start()
    try:
        yield SimpleNamespace(base_url="http://127.0.0.1:%d" % server.server_port,
                              config_path=config_path)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        wz_log.setLevel(wz_level)


def test_setup_wizard_onboards_a_genuinely_fresh_install(
        fresh_install_server, render_browser, monkeypatch):
    """SetupWizard.jsx (2026-08-02) is a full-fidelity port of the DC's theatrical 4-phase
    onboarding -- intro carousel, key entry, sync, ready -- driven by the SAME real
    endpoints classic's own plainer "paste a key / sync now" banner already used
    (/api/setup/save-key, /api/panel/run, /api/panel/status, /api/stats). This proves the
    whole chain against a server that starts in the exact state the wizard exists for:
    no account key, zero catalog rows.

    The key-save step is real end to end (real POST, real config.json write, mocked only
    `core.account_info` -- the same substitution tests/test_setup_wizard.py already uses,
    since this harness has no real PixAI credential to validate against). The sync step
    cannot be: a real `--sync` subprocess needs a real, working PixAI account, which does
    not exist here either. Its three endpoints are stubbed with REALISTIC shapes instead
    (a genuine failure with real-looking traceback lines, then a genuine success with live
    done/total/new progress and real-shaped final counts) -- proving SetupWizard's own
    polling/error/retry/reveal logic, which is the part that is actually new here; the
    backend contract itself is already covered by tests/test_setup_wizard.py and classic's
    own years of use.
    """
    ctx = render_browser.new_context(viewport={"width": DESKTOP["width"], "height": DESKTOP["height"]},
                                     device_scale_factor=1, base_url=fresh_install_server.base_url)
    ctx.set_default_timeout(10_000)
    try:
        page = ctx.new_page()
        _login(page)
        _freeze_motion(page)
        _settle(page)

        # --- stub the sync-phase endpoints FIRST, before any interaction -- SetupWizard's
        # own useEffect fires startSync() the INSTANT phase becomes 'sync' (no button click
        # gates it, matching the DC's single continuous phase machine), so registering these
        # after clicking Authenticate is too late: a real, unstubbed sync subprocess would
        # already be underway against this harness's fake key before the stub ever attaches
        # (caught live -- the first version of this test raced exactly that and timed out
        # waiting on progress numbers a real, doomed subprocess was never going to produce).
        # A real subprocess sync needs a real, working PixAI account this harness doesn't
        # have; page.route persists across the reload below, so one registration covers
        # both times 'sync' is entered. ---
        run_calls = []

        def _run(route):
            run_calls.append(route.request.post_data)
            if len(run_calls) == 1:
                # This first call is the auto-trigger fired by the natural key-save ->
                # 'sync' transition, BEFORE the reload below -- not the run this test
                # actually observes. A harmless one-shot "busy" error keeps it from ever
                # starting to poll (startSync() returns on d.error before scheduling the
                # interval), so it cannot interleave with the sequence asserted on below.
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"error": "a job is already running"}))
                return
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True, "action": "sync", "label": "Sync now"}))
        page.route("**/api/panel/run", _run)

        status_calls = {"n": 0}

        def _status(route):
            status_calls["n"] += 1
            n = status_calls["n"]
            if n == 1:
                body = {"status": "running", "rc": None, "lines": [],
                        "progress": {"done": 3, "total": 40, "new": 3, "pct": 7.5}}
            elif n == 2:
                body = {"status": "failed", "rc": 1, "progress": None,
                        "lines": ["Traceback (most recent call last):",
                                 "requests.exceptions.ConnectionError", "sync aborted"]}
            elif n == 3:
                body = {"status": "running", "rc": None, "lines": [],
                        "progress": {"done": 12, "total": 40, "new": 12, "pct": 30.0}}
            else:
                body = {"status": "done", "rc": 0, "progress": None, "lines": []}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
        page.route("**/api/panel/status", _status)

        page.route("**/api/stats", lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"images": 5029, "videos": 41, "collections": 6,
                            "local_tasks": 4100, "server_tasks": 4100, "coverage_pct": 100.0})))

        # --- intro: real clicks through the real 4-slide carousel, Back really goes back ---
        assert page.inner_text(".wz-slidehead") == "Welcome to the Athenaeum"
        for _ in range(3):
            page.click(".wz-next")
        assert page.inner_text(".wz-slidehead") == "One composer, every craft"
        assert page.inner_text(".wz-next") == "Let's set up my key →"
        page.click(".wz-back")
        assert page.inner_text(".wz-slidehead") == "Weave shots into a story"
        page.click(".wz-next")
        page.click(".wz-next")  # -> phase 'key'

        # --- key: a REAL POST /api/setup/save-key; only account_info is mocked (the same
        # substitution tests/test_setup_wizard.py uses -- this harness has no real key) ---
        monkeypatch.setattr(core, "account_info",
                            lambda session, raise_on_error=False: {"quotaAmount": 777})
        page.fill(".wz-keyinput", "sk-harness-fake-key")
        page.click(".wz-authbtn")
        page.wait_for_selector(".wz-synchead")  # phase flipped to 'sync'
        cfg = json.loads(fresh_install_server.config_path.read_text())
        assert cfg["PIXAI_API_KEY"] == "sk-harness-fake-key", (
            "the real key was not written to config.json by the real route")

        # --- reload proves the flip is real SERVER-SIDE state, not just client memory:
        # needs_key must now be false, landing directly on 'sync' (skipping intro/key). ---
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector(".wz-synchead")
        boot = page.evaluate("() => window.MG_BOOT")
        assert boot["needs_key"] is False and boot["catalog_empty"] is True, (
            "boot payload after the real key save: {!r}".format(boot))

        page.wait_for_function(
            "() => (document.querySelector('.wz-reveal-v') || {}).textContent === '3 / 40'")
        page.wait_for_selector(".wz-syncerr")
        assert "ConnectionError" in page.inner_text(".wz-syncerr"), (
            "the real subprocess's own traceback lines did not reach the error banner")
        page.click(".wz-retrybtn")
        # 3, not 2: call 1 was the harmless pre-reload auto-trigger (never observed), call
        # 2 was the reload's own natural auto-trigger (the one that just failed above),
        # call 3 is this explicit retry click.
        assert len(run_calls) == 3, "clicking Try again did not re-POST /api/panel/run"

        page.wait_for_function(
            "() => (document.querySelector('.wz-reveal-v') || {}).textContent === '12 / 40'")
        page.wait_for_selector(".wz-readyhead")
        assert page.inner_text(".wz-readyhead") == "Welcome home."
        ready_body = page.inner_text(".wz-readybody")
        assert "5,029 images" in ready_body and "41 videos" in ready_body and "6 collections" in ready_body, (
            "the ready phase does not show the real /api/stats numbers: {!r}".format(ready_body))

        with page.expect_navigation(wait_until="domcontentloaded"):
            page.click(".wz-enterbtn")
        assert page.url == fresh_install_server.base_url + "/"
        # The stubbed sync never touched the REAL catalog (still genuinely empty), so
        # landing back on the wizard -- now needs_key: false for real -- is the honest
        # outcome, not a test bug. This is the property that actually matters: the key
        # save from earlier survived the navigation as real server state.
        boot_after = page.evaluate("() => window.MG_BOOT")
        assert boot_after["needs_key"] is False
    finally:
        ctx.close()



def test_tracker_spin_ring_renders_as_a_true_circle_not_an_ellipse(logged_in_page):
    """A second, independent bug hiding behind the 2026-08-09 face-tumble fix above: owner
    caught it on a SECOND recording after that fix shipped, still "wonky". `.jt-spin` is a
    flex CHILD of `.jt-ic` (34px wide) but declares `width:48px` with no shrink override --
    a flex item's default flex-shrink:1 compresses its WIDTH to fit the 34px parent while its
    explicit HEIGHT:48px is untouched (flexbox only resizes the main axis), measured live via
    getBoundingClientRect at 34x48 before the fix. `.gen-ring`'s `inset:2px` on that non-square
    box made it an ELLIPSE, and animating an ellipse's rotation visibly bulges/narrows as it
    turns -- exactly the "wonky, offset" look, independent of which crop the portrait itself
    carries. Fix: flex-shrink:0 on .jt-spin. Asserted as real rendered geometry (not CSS text
    presence) because that is exactly the kind of mismatch a shrink-eligible flex child creates
    invisibly -- the declared width:48px in the stylesheet was never the lie, the cascade was.
    """
    page = logged_in_page(**DESKTOP)
    _open_tray_with_queued_job(page, "/")
    page.evaluate("() => document.querySelector('#jobs-tray .jt-spin').classList.remove('jt-queued')")
    _settle(page)
    geo = page.evaluate("""() => {
        const spin = document.querySelector('#jobs-tray .jt-spin');
        const ring = spin.querySelector('.gen-ring');
        const r = el => { const b = el.getBoundingClientRect(); return {w: b.width, h: b.height}; };
        return {spin: r(spin), ring: r(ring)};
    }""")
    assert abs(geo["spin"]["w"] - geo["spin"]["h"]) < 0.5, (
        ".jt-spin is not square ({!r}) -- a flex child of the 34px-wide .jt-ic shrinking its "
        "own declared 48px width again".format(geo["spin"]))
    assert abs(geo["ring"]["w"] - geo["ring"]["h"]) < 0.5, (
        ".gen-ring is not square ({!r}) -- it renders an ellipse, which bulges/narrows as it "
        "rotates instead of spinning cleanly".format(geo["ring"]))
