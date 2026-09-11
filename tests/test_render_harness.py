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
This module SKIPS without playwright + a browser. `.github/workflows/tests.yml` installs
playwright and chromium for the pytest job, so on CI these guards RUN on chromium (the
WebKit profile is local-only: `MG_HARNESS_BROWSER=webkit`). Before 2026-09 CI installed
neither and defect 3 above regressed on a `push` unseen. `tests/csshelp.py` covers that one axis in pure
stdlib: it resolves which declaration WINS the cascade (!important, specificity,
document order) with no browser, and
`tests/test_web_pick.py::test_portrait_mobile_drawer_rules_actually_win` asserts on
that. It is a strictly weaker instrument -- it proves the winner, not the pixels -- and
is not a reason to skip adding a rendering test here.
"""
import base64
import json
import re
import threading

import os
import pytest

from tests.conftest import _SEALED_DONOR

import moonglade_backup as core
from moonglade_gallery import (
    CATALOG_FIELDS, create_app, load_catalog, save_catalog,
    achievement_metrics, compute_achievements, save_ach_state,
    telem_flag, telemetry_metrics, load_telemetry,
)

# No playwright (or no browser) => this whole module skips. .github/workflows/tests.yml installs
# playwright + chromium, so on CI this module runs; a checkout without them skips it cleanly.
_pw = pytest.importorskip(
    "playwright.sync_api",
    reason="the rendering harness needs playwright + a chromium binary")
_PlaywrightTimeout = _pw.TimeoutError

pytestmark = pytest.mark.render

_USERNAME = "render-harness"
_PASSWORD = "a-real-test-password-1"

# 1280x900 desktop: what every threshold below was measured at.
DESKTOP = {"width": 1280, "height": 900}

# 390x844 phone: the width Login Mobile.dc.html proves the design at, and comfortably
# inside useIsMobile.js's own 520px breakpoint (430 until 2026-09-07), so main.jsx mounts AppMobile.jsx here.
PHONE = {"width": 390, "height": 844}
# The owner's phone, as a browser sees it (2026-09-07, from his 5059 screenshot: a Pro Max
# class iPhone in Safari with its toolbars up). 430 CSS px wide; 740 tall is the VISIBLE
# viewport with Safari's address bar and bottom toolbar on screen -- the screen's full 932 is
# what iOS hands `vh`, and the gap between the two is where a 78vh bottom sheet loses its
# head. Touch, the iOS user agent and the 3x ratio come with it, so the phone shell's own
# device gates run the way they run in his hand. The ENGINE is a separate choice: chromium by
# default (CI's only engine); `MG_HARNESS_BROWSER=webkit` runs this module on the engine iPhone
# Safari uses (`python -m playwright install webkit` once). Neither engine reproduces the two
# iOS-only behaviours the sheet fix answers, which is why that test also pins them structurally.
IPHONE_PRO_MAX = {
    "width": 430, "height": 740, "device_scale_factor": 3, "is_mobile": True, "has_touch": True,
    "user_agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
                   "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"),
}

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
        # MG_HARNESS_BROWSER=webkit runs this whole module on the engine iPhone Safari uses
        # (`python -m playwright install webkit`); chromium is the default and CI's only engine.
        engine = (os.environ.get("MG_HARNESS_BROWSER") or "chromium").strip().lower()
        if engine not in ("chromium", "firefox", "webkit"):
            # A typo here must not turn the whole harness into a SKIP with a reason that
            # blames a missing chromium binary (red team, 2026-09-08).
            pw.stop()
            pytest.fail("MG_HARNESS_BROWSER=%r is not one of chromium, firefox, webkit" % engine)
        browser = getattr(pw, engine).launch()
    except Exception as exc:                                  # pragma: no cover
        pw.stop()
        # First line only: playwright's own message trails a multi-line ASCII banner that
        # would swamp the -rs summary.
        pytest.skip("no usable %s binary (run `playwright install %s`): "
                    "%s" % (engine, engine, str(exc).splitlines()[0]))
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
    module scope) pins the same things conftest's autouse fixtures pin per test, so the
    server never sees this machine's real config, credentials, coded tree or pack:
    `MOONGLADE_DISABLE_WATCH=1` (no live-mirror WebSocket), `core._config_path` (so
    `get_or_create_secret_key()` and the account write land in tmp, not next to the
    checkout), an empty `core._cfg`, and `gallery.branding_root` (so both the discovery
    tree `create_app()` builds and `_container_path()`, which is this folder's PARENT plus
    `moonglade.dat`, land under this fixture's own root).

    That last pin is load-bearing and was missing until 2026-09-10. A module-scoped fixture
    is set up BEFORE the function-scoped autouse ones, so at the moment the achievement
    block below ran, `branding_root()` was still the real resolver: `_container_path()`
    named the checkout's own `moonglade.dat`. A dev box has a full pack there and pre-seeded
    every earned id into `seen`/`earned_at`; CI has none and pre-seeded nothing. Same code,
    two different fixtures, decided by a file nobody in this module wrote. The pin plus
    `seed_sealed_container()` (conftest's, the same helper the per-test fixture uses) makes
    the container this fixture reads one it wrote itself -- from the private donor when it
    is checked out, and absent exactly as on CI when it is not.
    """
    import logging
    from types import SimpleNamespace

    from werkzeug.serving import make_server

    import moonglade_gallery as _gallery
    from tests.conftest import clear_sealed_caches, seed_sealed_container

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
    # BEFORE anything below reads achievement state (and before create_app() builds a
    # discovery tree): this fixture's own coded tree, and its own sealed pack beside it.
    mp.setattr(_gallery, "branding_root", lambda: root / "branding")
    seed_sealed_container(root / "moonglade.dat")

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
    # first-run Setup Wizard) -- app_page()'s boot payload now computes needs_key from
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
        # The container caches are process globals: clear them on the way out too, or this
        # module's pack answers the next module's seal check (same two-sided contract
        # conftest's per-test fixture keeps).
        clear_sealed_caches()
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

    def _open(width=DESKTOP["width"], height=DESKTOP["height"], **device):
        # base_url makes page.goto("/loom") resolve against the ephemeral port, so no test
        # has to carry the port around. `device` carries a real phone's identity when a test
        # opens one (IPHONE_PRO_MAX below): user agent, touch, mobile viewport semantics and
        # pixel ratio -- the owner's phone is not a 390-wide desktop window (2026-09-07).
        opts = {"device_scale_factor": 1}
        opts.update(device)
        ctx = render_browser.new_context(viewport={"width": width, "height": height},
                                         base_url=render_server.base_url, **opts)
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


# The one route in this app that must never fire for real from a test. Named once so the
# guard below and the contest helpers at the bottom of the file cannot drift apart.
_CONTEST_ENTER_ROUTE = "**/api/contest/enter"


def _is_confirmed_entry(body):
    """Does this /api/contest/enter body ask the server to actually SUBMIT?

    An unreadable body counts as confirmed on purpose: a guard whose whole job is to prove
    that nothing irreversible happened must fail on anything it cannot prove is harmless.
    """
    try:
        return bool((json.loads(body or "{}") or {}).get("confirm"))
    except (TypeError, ValueError):
        return True


@pytest.fixture(autouse=True)
def no_confirmed_contest_entry(render_browser):
    """MODULE-WIDE BACKSTOP: no test in this file may submit a CONFIRMED contest entry.

    Entering a contest is an irreversible, PUBLIC account write and PixAI publishes no
    un-enter route -- `moonglade_gallery.py::api_contest_enter` says exactly that in its own
    docstring. Until this fixture existed, the only thing standing between this harness and
    a real one was the `page.route` inside `_open_contests_on_the_phone`: a CONVENTION, not
    a rule. Any test that reached the entry screen by another door -- the lightbox's
    "Enter contest" chip, say, which is precisely what
    `test_the_phone_enters_from_a_picture_with_that_picture_pre_ticked` below now does --
    would have had no interception at all, on a screen whose confirm bar is one click from
    armed. This makes the guarantee structural.

    It hangs off the ONE thing every page in this module has in common: `new_context` on the
    module's single browser, which both page-creating sites (`logged_in_page`'s factory and
    `test_setup_wizard_onboards_a_genuinely_fresh_install`'s own context) go through. So it
    covers a test nobody has written yet, which is the point of a backstop. Each context
    gets two halves, and they do different jobs -- proven against a live chromium, not
    assumed from the docs:

      * `ctx.route()` INTERCEPTS, so a page with no interception of its own can never reach
        the real route. A test's own `page.route` still wins over it (page routes are
        matched before context routes), which is why `_open_contests_on_the_phone`'s own
        interception stays exactly as it was: this is the floor, not a replacement.
      * `ctx.on("request")` RECORDS every body regardless of who fulfils it -- the request
        event fires for intercepted requests too -- so the assertion below sees the helper's
        traffic as well as its own.

    TWO OTHER LAYERS EXIST and neither is a reason to drop this one. The entry screen POSTs
    `confirm: true` only from a press of its confirm bar; and the server short-circuits an
    unconfirmed body before any network call at all (`if not body.get("confirm"): return
    jsonify({"preview": True, ...})` -- the same route's own preview contract, which is why
    the unconfirmed previews these tests DO fire are safe). Both of those stop the
    unconfirmed form. Nothing but this stops the confirmed one.
    """
    seen = []

    def _arm(ctx):
        def _record(req):
            if req.method == "POST" and req.url.endswith("/api/contest/enter"):
                seen.append(req.post_data or "")
        ctx.on("request", _record)
        # The same shape the real route answers an unconfirmed body with, so a page that
        # falls through to here gets the server's own preview instead of an error.
        ctx.route(_CONTEST_ENTER_ROUTE, lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"preview": True, "spends_credits": None})))

    real_new_context = render_browser.new_context

    def _guarded(*args, **kwargs):
        ctx = real_new_context(*args, **kwargs)
        _arm(ctx)
        return ctx

    render_browser.new_context = _guarded
    try:
        yield seen
    finally:
        # Drop the instance attribute rather than re-assigning the bound method, so the
        # shared module-scoped browser is left byte-for-byte as it was found.
        del render_browser.new_context
    confirmed = [b for b in seen if _is_confirmed_entry(b)]
    assert not confirmed, (
        "a CONFIRMED /api/contest/enter left this test: {!r} -- entering a contest is an "
        "irreversible, public account write with no un-enter route".format(confirmed))


# ---------------------------------------------------------------------------
# 0. The hermeticity of this file's own fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def unpinned_module_view():
    """What a module-scoped fixture that pins NOTHING sees when it resolves the coded tree.

    Deliberately the careless fixture: no MonkeyPatch, no `branding_root` pin, set up at
    module scope -- i.e. before conftest's function-scoped `_isolated_branding` has run.
    That is exactly the shape `render_server` had until 2026-09-10, and the reading it takes
    here is the reading that used to be the checkout's own tree and the real pack beside it.
    """
    from types import SimpleNamespace

    import moonglade_gallery as _g
    return SimpleNamespace(root=_g.branding_root(), container=_g._container_path())


def test_a_module_scoped_fixture_can_never_reach_the_real_coded_tree(unpinned_module_view):
    """The machine-dependence itself, asserted -- not the symptom it produced.

    conftest's `_real_coded_tree_untouched` watches the real tree for WRITES, and a read
    leaves nothing for it to see: on a checkout that already holds the discovery folders
    (the owner's does) an un-pinned `create_app()` writes nothing new, yet `_container_path()`
    quietly names the real 802MB pack and the fixture's achievement state becomes a property
    of the machine. So the rule is enforced by prevention -- conftest's session-scoped
    `_real_coded_tree_pinned_away` -- and this is the test that the prevention holds at the
    scope where it matters.

    Fails loudly if a future change unpins it: the next symptom would again be a fixture that
    behaves one way on a dev box and another on CI, which is not a failure anyone reads as
    "the resolver was not pinned"."""
    from tests.conftest import _REAL_CODED_ROOT

    real_pack = _REAL_CODED_ROOT.parent / "moonglade.dat"
    assert unpinned_module_view.root != _REAL_CODED_ROOT, (
        "a module-scoped fixture resolved branding_root() to the checkout's own coded tree "
        "at {}".format(_REAL_CODED_ROOT))
    assert _REAL_CODED_ROOT not in unpinned_module_view.root.parents
    assert unpinned_module_view.container != real_pack, (
        "a module-scoped fixture resolved _container_path() to the pack beside the checkout "
        "at {} -- its achievement state would be whatever that file happens to hold on this "
        "machine".format(real_pack))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _dismiss_any_achievement_toast(page, rounds=4):
    """Click-dismiss EVERY real achievement celebration (.ach-m2) that is up, in turn.

    render_server's fixture pre-seeds `seen` from the harness's INITIAL catalog state
    (suppresses the page-load toast), but a test's own real actions -- a job run, an
    account add -- can organically cross a NEW achievement threshold mid-test (telemetry
    counters, day/session flags), firing a fresh one the pre-seed can't have predicted.
    `.ach-m2` is a deliberate full-screen, click-or-timeout-to-dismiss overlay (by design,
    not a bug -- see `_play()` in gallery/src/notify/ach.js, the 2026-08-08 React-port home
    of the celebration engine), so left alone it blocks every click under it for its real
    4.2-6.4s hold. A no-op when nothing is showing.

    2026-09-07: this used to dismiss ONE moment and return, which is not the same thing as
    clearing the screen -- `celebrate()` pushes onto `_q`, so two achievements earned at
    once are two moments, and the old one-shot's very next click went to the successor
    overlay instead of the control under it. It now loops until the screen is genuinely
    clear, bounded, and says so loudly rather than silently giving up.

    2026-09-07, second pass -- REFINES the loop above, whose stated model of ach.js was
    wrong. That first rewrite waited for `.ach-m2` to reach `state="detached"` and treated
    a following `state="attached"` as "another one is queued", on the belief that `_play()`
    calls `_next()` 500ms AFTER the clicked moment is removed. It does not. `_play()`'s
    `done()` (ach.js:264-268) schedules ONE callback that removes the clicked moment and
    calls `after()` -- which IS `_next` (ach.js:444) -- in the same task, and `_next`
    (ach.js:437-445) is plain synchronous code that ends in `_play()`'s
    `document.body.appendChild(m)` (ach.js:259-260). Old node out, new node in, one tick,
    same `.ach-m2` class. So when a moment really is queued there is NO observable moment
    at which `.ach-m2` matches zero elements, `state="detached"` can never resolve, and the
    helper raised a Playwright TimeoutError in exactly the queued-parade case it was
    written to fix.

    What the loop waits for now is "the moment I clicked is gone", not "the screen went
    empty": hold the clicked element's own handle, then wait until that node is off the
    document OR the front `.ach-m2` is a different node. That is satisfied by both real
    shapes -- the last moment leaving (nothing replaces it) and a queued successor being
    swapped in on the same tick -- so the loop advances to the successor instead of timing
    out on a state ach.js never enters.

    Call it before any interaction a full-screen overlay could swallow, not just once after
    boot. NOT a match for the >3 flood parade (`_floodParade`, owner ruling 2026-09-03):
    there a click RECEDES the moment into the `_trail` instead of removing it, so the node
    keeps its `.ach-m2` class and the count climbs rather than falling. Receded layers drop
    their scrim and pointer events, so they swallow nothing -- but this helper is not the
    thing that clears them.
    """
    for _ in range(rounds):
        toast = page.locator(".ach-m2")
        if not toast.count():
            return
        try:
            handle = toast.first.element_handle(timeout=1000)
        except _PlaywrightTimeout:
            continue                       # it left on its own between the count and here
        if handle is None:
            continue
        try:
            toast.first.click(timeout=1000)
            # Bounded, and deliberately NOT a `.ach-m2` count/detached check: a queued
            # successor is appended in the same task the clicked one is removed in.
            # 500ms removal + the successor's own append, with room for a loaded runner.
            page.wait_for_function(
                "el => !el.isConnected || document.querySelector('.ach-m2') !== el",
                arg=handle, timeout=3000)
        except _PlaywrightTimeout:
            break                          # the assert below reports it
        finally:
            handle.dispose()
    assert not page.locator(".ach-m2").count(), (
        "still an .ach-m2 celebration up after dismissing up to {} of them -- either the "
        "app is firing an unbounded parade or the overlay stopped closing on click".format(
            rounds))


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
    # The login's own budget, wider than the context default: on a two-core CI runner the
    # gallery's first load after sign-in (its data calls, then the quiet stretch
    # "networkidle" waits for) took longer than the ~3s left of the 10s default and failed
    # a geometry test that had not even started (2026-09-06). Signing in is not the thing
    # under test; a slow sign-in must not fail it.
    with page.expect_navigation(wait_until="networkidle", timeout=30_000):
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
# 4. Deep Focus's veil vs the corner FABs -- RETIRED 2026-08-09
# ---------------------------------------------------------------------------
# This test (test_deep_focus_veil_wins_over_the_corner_fabs) verified that Deep Focus's veil
# painted OVER the OLD floating #jobs-fab, a body-portaled element sitting OUTSIDE
# .lv-overlay's own DOM subtree -- exactly the shape of bug where a z-index comparison alone
# (450 > 401) reads correctly on paper while the veil still visually loses, because the FAB
# was never really competing inside .lv-overlay's stacking context at all.
#
# Claude Design handoff 2026-08-09 (drift item 39) retired that floating FAB entirely. The
# new Activity control (.lv-top-act-wrap, in loom/master-storyboard.jsx's own toolbar) is a
# normal DESCENDANT of .lv-overlay -- confirmed by reading the actual JSX nesting, not
# assumed -- so it was never a candidate for this bug class again: anything Deep Focus's veil
# already covers inside .lv-overlay (which is everything in that subtree, toolbar included)
# covers the new control too, by ordinary DOM stacking, no z-index reconciliation needed. The
# property this test measured (a floating overlay racing a full-screen veil via z-index) no
# longer describes anything real on this page, so there is nothing left to regression-guard --
# keeping the test would mean asserting on a selector (#jobs-fab) that no longer exists.
# `loom/test/loom-df-veil-stacking.test.js`'s own guard (the `.lv-overlay-df` z-index-bump
# mechanism itself, not the FAB it used to protect) is UNTOUCHED and still accurate -- that
# mechanism wasn't removed, it's just no longer load-bearing for the Activity control
# specifically; left in place since nothing here asked it to be pulled out.


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

    Since the classic cut this measures the React shell at "/" -- APP_PAGE carries the
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
# 6. The Activity control's QUEUED state, rendered -- and rendered IDENTICALLY on both hosts
# ---------------------------------------------------------------------------
# Owner complaint 2026-07-25: a plain generation "goes right to generated and spins until
# done. That's it." A task PixAI has accepted but never dispatched sits at a non-terminal
# status for ~60 minutes and used to draw the same spinning mascot as real work.
#
# Asserted the only way that can see it: read the mascot's COMPUTED animationName. Asserting
# the CSS text alone proves nothing about whether the class reaches the element or wins the
# cascade -- and each host CAN carry its own extra CSS (the Loom shell's own <style>), which
# is precisely the shape of edit that could break one host and not the other (the tray's
# font-family already drifted that way once, 2026-07-21).
#
# RE-PORT 2026-08-09 (Claude Design handoff, drift item 39): the floating #jobs-fab/#jobs-tray
# pair (one shared portaled component, identical ids on both hosts) is retired. Each host now
# mounts its OWN trigger inline in its own header -- gallery/src/components/SeparatorBar.jsx's
# `.mgx-act-wrap .at-chip` vs the Loom's `.lv-top-act-wrap .at-chip` in
# loom/master-storyboard.jsx -- so the TRIGGER selector is host-specific, but everything past
# it (the dropdown panel, the row, the spinner) is the SAME shared `.at-*` markup/CSS on both,
# which is what this test actually verifies stays identical.
#
# _freeze_motion is deliberately NOT used here: it nulls every animation on the page, which
# would make "animationName is none" trivially true and this whole test vacuous.
_TRAY_QUEUED_JS = """() => {
  const item = document.querySelector('.at-panel .at-row');
  const spin = item.querySelector('.at-spin');
  const nel = spin.querySelector('.at-nel');
  const ring = spin.querySelector('.at-ring');
  const pill = item.querySelector('.at-phase');
  const eta = item.querySelector('.at-eta');
  return {
    hasQueuedClass: spin.classList.contains('at-queued'),
    mascotAnimation: getComputedStyle(nel).animationName,
    ringAnimation: getComputedStyle(ring).animationName,
    pillText: pill ? pill.textContent.trim() : null,
    pillTransform: pill ? getComputedStyle(pill).textTransform : null,
    pillColor: pill ? getComputedStyle(pill).color : null,
    etaText: eta ? eta.textContent.trim() : null,
    // The row must still be a visible, laid-out row -- not collapsed to nothing by the
    // extra chips wrapping badly in the panel's ~380px.
    rowWidth: Math.round(item.getBoundingClientRect().width),
    iconVisible: getComputedStyle(nel).display !== 'none',
  };
}"""

# One queued job, stubbed at /api/jobs rather than written into the harness server's own
# jobs.jsonl: the log's collapse/ageing behaviour has thorough coverage in
# tests/test_jobs.py, and what needs a browser is only how the row DRAWS this record.
_QUEUED_JOB = {"jobs": [{
    "job_id": "2037594262049550370", "type": "generate", "label": "Generated",
    "status": "running", "started": False, "eta_seconds": 27,
    "ts": 0, "started_at": 0,
}]}


# The row renders `<img class="at-nel" ...>` with an onError handler that REMOVES the element
# (ActivityRow.jsx's own self-delete, ported from the vanilla row() before it), so on a
# throwaway catalog with no branding/ directory the mascot DELETES ITSELF and there is no
# element left to read an animationName off (this test's first run died exactly there). A
# real install has the file; served here as a 1x1 transparent PNG so the measured DOM matches
# a real one.
_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4zwAAAgIBAG4/xUwAAAAASUVORK5CYII=")


def _open_tray_with_queued_job(page, path):
    page.route("**/api/jobs", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(_QUEUED_JOB)))
    page.route("**/branding/nel_spinner.png", lambda route: route.fulfill(
        status=200, content_type="image/png", body=_PIXEL_PNG))
    page.goto(path, wait_until="domcontentloaded")
    # The trigger chip is ALWAYS rendered now (idle or live -- there is no more separate
    # "show" class to wait for; the old floating FAB only existed at all once the tray had
    # something to report). One trigger per page on either host.
    page.wait_for_selector(".at-chip")
    page.click(".at-chip")
    page.wait_for_selector(".at-panel .at-row")
    # The panel's own entrance animation (atSlideIn, 220ms, notify.css) carries a
    # translateY+scale transform that only resolves to `transform:none` once it finishes --
    # _settle()'s two animation frames (~32ms) are nowhere near long enough to guarantee that,
    # so a geometry read right after opening can catch it mid-transform (measured live: a
    # lingering scale(.97) shrank a 380px-wide panel to 368.6px, explained exactly by
    # 380*.97). Polled rather than a fixed sleep so this waits exactly as long as needed, no
    # more -- and freeze_motion is NOT an option here, several callers of this helper
    # (test_queued_generation_stops_the_spinner_on_both_hosts) measure the ring's OWN
    # continuous animationName, which freeze_motion would zero out and make vacuous.
    # A settled `transform: none` (the animation's own "to" keyframe, held via its `both`
    # fill-mode) serializes as the identity matrix, NOT the literal string "none" -- measured
    # live (Chromium): 'matrix(1, 0, 0, 1, 0, 0)'. Accept either serialization rather than
    # assume one.
    page.wait_for_function(
        "() => { const t = getComputedStyle(document.querySelector('.at-panel')).transform;"
        " return t === 'none' || t === 'matrix(1, 0, 0, 1, 0, 0)'; }")
    _settle(page)


def test_queued_generation_stops_the_spinner_on_both_hosts(logged_in_page):
    """The gallery and the Loom render the SAME shared Activity markup/CSS -- ActivityRow.jsx
    + gallery/src/styles/notify.css, built into TWO separate bundles (Vite's app.css for "/",
    esbuild's master-storyboard.bundle.css for /loom) -- so the queued state must be
    measurably identical on both. That is the claim, and this measures it rather than
    inferring it from the source being shared: two build pipelines is exactly how one host's
    bundle could go stale while the other moves on.

    Measured as shipped at 1280x900, on `/` and on `/loom?bundle=1` alike: the icon carries
    `at-queued`, the ring's computed animationName is `none` (a rendering job reads
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
            "{}: the queued row's icon has no at-queued modifier".format(host))
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
        page.evaluate("() => document.querySelector('.at-panel .at-spin')"
                      ".classList.remove('at-queued')")
        _settle(page)
        reverted = page.evaluate(_TRAY_QUEUED_JS)
        assert reverted["ringAnimation"] == "gen-spin", (
            "{}: removing at-queued left the ring at {!r}".format(
                host, reverted["ringAnimation"]))

    assert seen["gallery"] == seen["loom"], (
        "the shared Activity markup renders the queued state DIFFERENTLY on the two hosts:\n"
        "  gallery: {!r}\n  loom:    {!r}".format(seen["gallery"], seen["loom"]))


_TRAY_GEOMETRY_JS = {
    "gallery": """() => {
        const chip = document.querySelector('.mgx-act-wrap').getBoundingClientRect();
        const cred = document.querySelector('.mgx-cred').getBoundingClientRect();
        const row = document.querySelector('.mgx-sepright').getBoundingClientRect();
        const panel = document.querySelector('.at-panel').getBoundingClientRect();
        return {chipLeft: chip.left, credLeft: cred.left, rowRight: row.right, panelRight: panel.right};
    }""",
    "loom": """() => {
        const chip = document.querySelector('.lv-top-act-wrap').getBoundingClientRect();
        const close = document.querySelector('a.lv-close').getBoundingClientRect();
        const row = document.querySelector('.lv-top').getBoundingClientRect();
        const panel = document.querySelector('.at-panel').getBoundingClientRect();
        return {chipLeft: chip.left, credLeft: close.left, rowRight: row.right, panelRight: panel.right};
    }""",
}


def test_activity_dropdown_reaches_the_true_edge_regardless_of_trigger_position(logged_in_page):
    """Regression guard for a real, live-found bug and its real, live-found fix (both
    2026-08-09/10, same day): the dropdown must always reach the header row's true outer
    edge, and that must hold NO MATTER where the trigger chip itself sits in the row.

    Sequence of events this pins down: the trigger originally sat FIRST in its row, and its
    dropdown (`right:0` anchored to its own small box) fell short of the row's true right
    edge by however wide the sibling chips after it were. The first fix moved the trigger
    itself to be LAST in the row -- which worked, but was never actually shown to the owner
    for approval, only "the dropdown is cut off" was (2026-08-10 correction). The real fix
    decouples the two: `.mgx-sepright` / `.lv-top` (the whole row) is now the panel's
    positioned ancestor, not the trigger's own wrapper, so the panel reaches the true edge
    regardless of where the trigger sits -- letting the trigger go back to its original,
    FIRST position without reintroducing the cutoff. Both properties are asserted below so
    neither a `position:relative` regression on the trigger wrapper NOR a reorder-without-
    approval regression can land silently again.
    """
    for host, path in (("gallery", "/"), ("loom", "/loom?bundle=1")):
        page = logged_in_page(**DESKTOP)
        _open_tray_with_queued_job(page, path)
        g = page.evaluate(_TRAY_GEOMETRY_JS[host])

        assert g["chipLeft"] < g["credLeft"], (
            "{}: the Activity trigger is not before the credits/close chip anymore -- "
            "{!r}".format(host, g))
        assert abs(g["panelRight"] - g["rowRight"]) <= 1, (
            "{}: the dropdown does not reach the row's true right edge (panel right={}, "
            "row right={})".format(host, g["panelRight"], g["rowRight"]))


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
    # The panel paints "opening the panel..." until /api/panel/summary answers; under load
    # that outlasts _settle (seen 2026-09-07 with a test workflow running beside the
    # harness), so wait for the summary's own text rather than a fixed pause.
    page.wait_for_function(
        "() => /THE LIBRARY/.test(document.querySelector('[aria-label=\"Control Panel\"]')?.innerText || '')",
        timeout=20_000)
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
    # wait for the SETTLED empty-state text, not just the dialog mounting -- it opens
    # showing "0 items"/"Loading..." before its own /api/trash/list fetch resolves and
    # swaps in "Nothing in the trash.", a race this assertion used to lose reliably in CI
    # (consistently slower than local) while passing every time locally (found via 13
    # straight red "Tests" runs on master, 2026-08-09 through 2026-08-10, never checked).
    page.wait_for_selector('[aria-label="Trash"] .mgcp-trashempty:has-text("Nothing in the trash")')
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
    # The tab is achievement-gated (brandingUnlocked = "under-the-hood" earned; the
    # harness seeds branding_custom_file to earn it). Since bundle-v2 the roster is
    # SEALED in moonglade.dat, so that gate can only resolve when the private donor is
    # present -- donor-absent (public CI) the tab never renders. Gate just this block
    # so the rest of this test (jobs, account, trash, power modal) still renders in CI;
    # the branding path stays covered on any donor-present run. ---
    if _SEALED_DONOR.is_file():
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
# 7b. "Blur behind popups" -- the per-device toggle, measured as COMPUTED STYLE
# ---------------------------------------------------------------------------
# Owner ruling 2026-09-04 (docs/DECISIONS.md, "the popup blur gets a Control Panel
# toggle"): the backdrop-filter every popup's scrim carries is the largest thing an OPEN
# popup keeps paying for on a weak machine, so it becomes a preference in the browser's own
# storage -- per device, never config.json.
#
# This is exactly the defect class this whole file exists for. loom/test/overlay-open-perf
# .test.js already pins that the override rule EXISTS and is written `!important`; only a
# real engine can answer whether the declaration actually WINS -- the blur reaches these
# scrims from a keyframe, and an author !important outranking an animation is a cascade
# rule, not something a substring search can verify. So the read below is
# getComputedStyle on the live scrim, not the stylesheet text.
#
# _freeze_motion is deliberately NOT used here (same reasoning as the tray test above):
# it sets `animation: none !important`, which would kill the deferred blur keyframe and
# make "backdropFilter is none" trivially true in BOTH states -- the test would pass while
# measuring nothing. Nothing sleeps either: every phase waits on the computed value itself.
_READ_SCRIM_JS = """() => {
  const s = document.querySelector('.mgv-scrim');
  const cs = s ? getComputedStyle(s) : null;
  return {
    found: !!s,
    blur: cs ? (cs.backdropFilter || cs.webkitBackdropFilter || 'none') : null,
    background: cs ? cs.backgroundColor : null,
    opacity: cs ? cs.opacity : null,
    rootFlagged: document.documentElement.classList.contains('mg-noblur'),
    stored: (() => { try { return localStorage.getItem('mg_noblur'); } catch (e) { return 'THREW'; } })(),
  };
}"""

# WAIT FOR THE SETTLED VALUE, NOT THE FIRST FRAME THAT HAS ONE (#54, 2026-09-06).
# The blur reaches this scrim from a KEYFRAME -- `mgvScrimBlur .01s linear .3s forwards`
# (overlays.css) -- so "is it blurred yet" and "has the blur ARRIVED" are two different
# questions, and this predicate only ever asked the first: /blur\(/ matches the interpolated
# blur(0.042px) exactly as happily as the final blur(7px). Both reads below (`before` in
# phase 1, `restored` in phase 5) are taken the instant it goes true, so a read that landed
# inside those 10ms carried a half-grown radius and phase 5's restored == before comparison
# failed on a value that was merely measured too early -- twice on 2026-09-05, in two
# independent full-module runs, green in isolation every time.
# The gate is now the element's OWN animation clock: every CSS animation on the scrim
# reporting `finished`. That is the settled-value poll in its exact form -- an answer from
# the engine rather than a sample-it-twice heuristic that a fast raf could still fool -- and
# it is the same discipline _freeze_motion() enforces for the geometry reads elsewhere in
# this file, applied where freezing is not allowed (the note above: `animation: none` would
# kill the very keyframe under test).
# Strengthening it does not weaken phase 4, which requires this predicate to TIME OUT: the
# same predicate has to have gone true in phase 1 before phase 4 is reached, so it cannot
# quietly become unsatisfiable and pass that step vacuously.
# An engine without getAnimations() reads an empty list and falls back to the plain check.
_SCRIM_BLURRED = ("() => { const s = document.querySelector('.mgv-scrim'); if (!s) return false; "
                  "const a = s.getAnimations ? s.getAnimations() : []; "
                  "if (a.some((x) => x.playState !== 'finished')) return false; "
                  "return /blur\\(/.test(getComputedStyle(s).backdropFilter || ''); }")
# No settle gate on this one, and none needed: `none` here is the author !important of
# html.mg-noblur (overlays.css), which outranks the keyframe outright -- there is no
# interpolation to catch it mid-way, at any moment of the animation's life.
_SCRIM_SHARP = ("() => { const s = document.querySelector('.mgv-scrim'); return !!s && "
                "(getComputedStyle(s).backdropFilter || 'none') === 'none'; }")


def _open_panel(page):
    _dismiss_any_achievement_toast(page)
    page.click('nav[aria-label="Destinations"] button:has-text("Panel")')
    page.wait_for_selector('[aria-label="Control Panel"]')


def test_the_living_librarys_runs_itself_block_renders_and_really_toggles(logged_in_page):
    """The living library on the Panel, in a real browser (2026-09-06).

    Four things, in the order the owner meets them:
      1. the "Runs itself" block exists and leads -- it sits ABOVE the manual grid, which
         is the demotion the scope asked for ("the manual-jobs block shrinks");
      2. every shipped job has a row, each saying how often it runs, when it last ran,
         when it next will, and carrying its own Run now;
      3. a toggle is a REAL round trip to /api/panel/schedule and it sticks across a
         reopen -- not local component state that evaporates;
      4. the rows are the vocabulary that already existed (.mgcp-standing), and none of
         them is wider than the console that holds them -- an element-level assertion
         cannot see a row that has silently overflowed its container, and that is exactly
         the class of break this harness exists for.
    """
    page = logged_in_page(**DESKTOP)
    _visit(page, "/")
    _settle(page)
    _open_panel(page)
    page.wait_for_selector(".mgcp-living")

    # 1. it leads: the block's bottom edge is above the manual grid's top edge.
    box = page.locator(".mgcp-living").bounding_box()
    grid = page.locator(".mgcp-grid").bounding_box()
    assert box["y"] + box["height"] <= grid["y"] + 1, (
        "the Runs-itself block must sit above the manual grid -- that ordering IS the "
        "Control Panel demoting (block {}, grid {})".format(box, grid))

    # 2. a row per shipped job, each with a Run now
    text = page.inner_text(".mgcp-living")
    for label in ("Published-artwork sweep", "Sync now", "Sync i2v videos",
                  "Reconcile deleted", "Top up Similar", "Full re-walk",
                  "Rebuild ALL thumbnails"):
        assert label in text, "%r has no row in the Runs-itself block" % label
    assert "last ran" in text and "60 days" in text     # the staleness backstop, in words
    rows = page.locator(".mgcp-living .mgcp-standing")
    assert rows.count() >= 7
    assert page.locator('.mgcp-living button.mgcp-run:has-text("Run now")').count() >= 7

    # 3. a REAL toggle: flip the sweep off, and it is still off after closing and
    #    reopening the Panel (i.e. it went to the server, not to component state).
    sweep = page.locator('.mgcp-living .mgcp-standing:has-text("Published-artwork sweep")')
    assert sweep.locator("button.mgcp-standing-toggle").inner_text().strip() == "on"
    sweep.locator("button.mgcp-standing-toggle").click()
    page.wait_for_function(
        "() => { const r = [...document.querySelectorAll('.mgcp-living .mgcp-standing')]"
        ".find((e) => e.textContent.includes('Published-artwork sweep')); "
        "const b = r && r.querySelector('button.mgcp-standing-toggle'); "
        "return b && b.textContent.trim() === 'off'; }")
    page.click('[aria-label="Control Panel"] button[aria-label="Close"]')
    page.wait_for_selector('[aria-label="Control Panel"]', state="detached")
    _open_panel(page)
    page.wait_for_selector(".mgcp-living")
    assert page.locator(
        '.mgcp-living .mgcp-standing:has-text("Published-artwork sweep") '
        "button.mgcp-standing-toggle").inner_text().strip() == "off"
    # put it back, so this test leaves the harness's shared server as it found it
    page.locator('.mgcp-living .mgcp-standing:has-text("Published-artwork sweep") '
                 "button.mgcp-standing-toggle").click()
    page.wait_for_function(
        "() => { const r = [...document.querySelectorAll('.mgcp-living .mgcp-standing')]"
        ".find((e) => e.textContent.includes('Published-artwork sweep')); "
        "const b = r && r.querySelector('button.mgcp-standing-toggle'); "
        "return b && b.textContent.trim() === 'on'; }")

    # 4. no row overflows the console that holds it
    overflow = page.evaluate(
        "() => { const host = document.querySelector('.mgcp-living'); "
        "const w = host.getBoundingClientRect().width; "
        "return [...host.querySelectorAll('.mgcp-standing')]"
        ".filter((r) => r.scrollWidth > Math.ceil(w) + 1).length; }")
    assert overflow == 0, "%d Runs-itself row(s) overflow the block" % overflow


def test_blur_behind_popups_toggles_the_real_backdrop_filter(logged_in_page):
    """The Panel's own scrim is the subject AND the surface carrying the switch.

    Four things get proved, in the order a person would meet them:
      1. by default the scrim really is blurred (so step 2 is not vacuous),
      2. flipping the toggle clears the blur on a popup that is ALREADY OPEN,
      3. the dark scrim itself is untouched -- same colour, same opacity,
      4. after a reload the class is on <html> before any popup exists, and the
         scrim comes up sharp and STAYS sharp past the deferred keyframe's delay.
    """
    page = logged_in_page(**DESKTOP)
    # Not _visit(): see the freeze-motion note above.
    page.goto("/", wait_until="domcontentloaded")
    _settle(page)
    _open_panel(page)

    # 1. THE DEFAULT. An install that has never touched this looks exactly as it always
    #    has. The wait is on the blur landing, which also proves the deferred keyframe
    #    (asserted structurally in loom/test/overlay-open-perf.test.js) really fires.
    page.wait_for_function(_SCRIM_BLURRED)
    before = page.evaluate(_READ_SCRIM_JS)
    assert before["found"]
    assert "blur(" in before["blur"], before
    assert before["rootFlagged"] is False
    assert before["stored"] in (None, ""), (
        "a fresh browser context must carry no stored preference: {!r}".format(before["stored"]))

    # 2. THE FLIP, on the open popup. No reload, no reopen -- the class lands on <html>
    #    and the scrim under this very Panel goes sharp.
    page.click('.mgcp-tile:has-text("Blur behind popups") button.mgcp-bjtoggle')
    page.wait_for_function(_SCRIM_SHARP)
    after = page.evaluate(_READ_SCRIM_JS)
    assert after["blur"] == "none", after
    assert after["rootFlagged"] is True
    assert after["stored"] == "1", "the preference must persist to this browser's storage"

    # 3. ONLY THE BLUR MOVED. The owner asked for a blur toggle, not a scrim toggle: the
    #    popup still lands on the same dark layer, the gallery behind it is merely sharp.
    assert after["background"] == before["background"], (
        "the dark scrim changed colour: {!r} -> {!r}".format(before["background"], after["background"]))
    assert after["opacity"] == before["opacity"]

    # 4. THE BOOT ORDER, measured. main.jsx applies the class at module scope, above
    #    createRoot -- so on a fresh load it is already on <html> with no popup open at
    #    all, and the scrim that opens next is never blurred for a frame.
    page.goto("/", wait_until="domcontentloaded")
    _settle(page)
    assert page.evaluate("() => document.documentElement.classList.contains('mg-noblur')"), (
        "the preference was not applied at boot -- a popup opened on the first frame "
        "would paint blurred")
    assert not page.evaluate("() => !!document.querySelector('.mgv-scrim')"), (
        "no scrim should exist yet; this assertion is what makes the one above a "
        "statement about BOOT rather than about an already-open overlay")
    _open_panel(page)
    page.wait_for_function(_SCRIM_SHARP)
    # ...and it stays sharp past the moment the deferred keyframe would otherwise have
    # switched the blur on (.3s). Waiting for the OPPOSITE and requiring a timeout is what
    # makes this a real assertion about the keyframe being overridden, not just about the
    # first frame after open.
    with pytest.raises(_PlaywrightTimeout):
        page.wait_for_function(_SCRIM_BLURRED, timeout=1200)

    # 5. AND BACK. A one-way switch would pass every assertion above.
    page.click('.mgcp-tile:has-text("Blur behind popups") button.mgcp-bjtoggle')
    page.wait_for_function(_SCRIM_BLURRED)
    restored = page.evaluate(_READ_SCRIM_JS)
    assert restored["rootFlagged"] is False
    assert restored["stored"] == "", "on writes the empty string, never a stray '1'"
    assert restored["blur"] == before["blur"], (
        "turning it back on must restore the SAME blur, not a different radius")


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
    caught it on a SECOND recording after that fix shipped, still "wonky". The spinner's icon
    box was a flex CHILD of a narrower parent but declared its own wider width with no shrink
    override -- a flex item's default flex-shrink:1 compresses its WIDTH to fit the narrower
    parent while its explicit HEIGHT is untouched (flexbox only resizes the main axis),
    measured live via getBoundingClientRect as genuinely non-square before the fix. The ring's
    `inset` on that non-square box made it an ELLIPSE, and animating an ellipse's rotation
    visibly bulges/narrows as it turns -- exactly the "wonky, offset" look, independent of
    which crop the portrait itself carries. Fix: flex-shrink:0 on the spin box. Asserted as
    real rendered geometry (not CSS text presence) because that is exactly the kind of
    mismatch a shrink-eligible flex child creates invisibly -- the declared width was never
    the lie, the cascade was.

    Re-port note 2026-08-09 (Claude Design handoff, drift item 39): `.jt-spin`/`.jt-ic`/
    `.gen-ring` -> `.at-spin`/`.at-ic`/`.at-ring` (the header-docked Activity control's own
    prefix). The old 34px-vs-48px mismatch is gone in the new markup (`.at-ic` and `.at-spin`
    both declare 44px now), but flex-shrink:0 stays on `.at-spin` as a guard -- this test still
    measures the real box, not just trusts the declared value.
    """
    page = logged_in_page(**DESKTOP)
    _open_tray_with_queued_job(page, "/")
    page.evaluate("() => document.querySelector('.at-panel .at-spin').classList.remove('at-queued')")
    _settle(page)
    geo = page.evaluate("""() => {
        const spin = document.querySelector('.at-panel .at-spin');
        const ring = spin.querySelector('.at-ring');
        const r = el => { const b = el.getBoundingClientRect(); return {w: b.width, h: b.height}; };
        return {spin: r(spin), ring: r(ring)};
    }""")
    assert abs(geo["spin"]["w"] - geo["spin"]["h"]) < 0.5, (
        ".at-spin is not square ({!r}) -- a flex child of a narrower parent shrinking its "
        "own declared width again".format(geo["spin"]))
    assert abs(geo["ring"]["w"] - geo["ring"]["h"]) < 0.5, (
        ".at-ring is not square ({!r}) -- it renders an ellipse, which bulges/narrows as it "
        "rotates instead of spinning cleanly".format(geo["ring"]))


# ---------------------------------------------------------------------------
# 8. The phone's ◈ Similar: viewer door -> results -> token -> the library back
# ---------------------------------------------------------------------------
def _fake_similar_module(hits):
    """A stand-in for `moonglade_similar`, the optional CLIP sidecar.

    The real module needs pixeltable + a built index, which no test machine here has, so
    the live route would answer `images: []` + an error line and only the EMPTY path
    would ever be exercised. This is patched into `sys.modules` for one test, so
    `moonglade_gallery.api_similar`'s own in-handler `import moonglade_similar` picks it
    up and EVERY OTHER PART of the route stays real -- the login gate, the media_id and
    on-disk-file lookups, the per-hit `get_row` catalog reads, the response shape the
    client renders. Only the CLIP maths is faked, because only the CLIP maths is absent.
    """
    from types import SimpleNamespace
    return SimpleNamespace(
        similar=lambda path, k=24, exclude_media_id=None: [
            (mid, score) for mid, score in hits if mid != exclude_media_id][:k],
        count=lambda: len(hits),
    )


# The one harness row with a real bitmap on disk (render_server writes harness_0.png for
# it), which find_image_file has to resolve before /api/similar will look for neighbours
# at all -- so every door pressed below is pressed on this picture.
_DOOR_TILE = '.glm-tile:has(img[src="/thumbs/100.jpg"])'


def test_phone_similar_door_opens_results_and_the_token_puts_the_library_back(
        logged_in_page, monkeypatch):
    """The phone half of B2's one-system Similar, end to end at a real 390px viewport.

    Owner, 2026-09-05: the phone's ◈ Similar was left a stub toast and the carve-out
    written into the changelog, on the claim that the phone had nowhere to put the token.
    It has a search field (GalleryMobile.jsx's `.glm-search`), so this pins the whole
    round trip the desktop already has: the full-screen viewer's ◈ Similar chip is a real
    DOOR, the lookalikes take the grid's place, the dismissible ◈ token rides in the
    search bar with the match count, and ✕ puts the library back with its own state --
    query, tiles, scroll offset -- untouched.

    Everything below is the real app against the real Flask route; only the absent CLIP
    sidecar is stubbed (see _fake_similar_module).
    """
    import sys
    monkeypatch.setitem(sys.modules, "moonglade_similar",
                        _fake_similar_module([("101", 0.91), ("102", 0.88), ("103", 0.77)]))

    page = logged_in_page(**PHONE)
    _visit(page, "/")
    page.wait_for_selector(".glm-grid .glm-tile")
    _dismiss_any_achievement_toast(page)

    # The phone really does have a search field -- the premise the carve-out denied.
    assert page.locator(".glm-search input").count() == 1
    page.fill(".glm-search input", "harness")
    tiles_before = page.locator(".glm-grid .glm-tile").count()

    # A tap opens the full-screen viewer (GalleryMobile's tapView -> LightboxMobile).
    # Clear the screen first: a full-screen .ach-m2 swallows this tap, and this test's own
    # page load can cross a threshold the module fixture's `seen` pre-seed never saw.
    _dismiss_any_achievement_toast(page)
    page.locator(_DOOR_TILE).click()
    page.wait_for_selector(".lbm-root")
    # Put the library at a known offset UNDER the viewer -- the offset is set here rather
    # than before the tap because Playwright scrolls the tile into view to click it, which
    # moves .glm-body itself. This is the number that has to come back.
    #
    # 2026-09-07, order-independence: the offset used to be a hardcoded 40, which only fits
    # because SOME EARLIER TEST grew the module-scoped catalog (the import-overlay test
    # writes real rows into the same render_server catalog). On the fixture's own six rows
    # .glm-body overscrolls by 15px, so scrollTop clamped to 15 and this assertion failed --
    # alone, and under any -k that deselected the importer. The number now comes from the
    # live scroller, capped at the same 40; what the assertion actually needs is a non-zero
    # offset that survives the round trip, and that is what it now demands.
    scroll_before = page.evaluate("""() => {
        const b = document.querySelector('.glm-body');
        b.scrollTop = Math.min(40, b.scrollHeight - b.clientHeight);
        return b.scrollTop;
    }""")
    _settle(page)
    scroll_before = page.evaluate("() => document.querySelector('.glm-body').scrollTop")
    assert scroll_before > 0, (
        "the phone's library scroller would not take a test offset ({!r}) -- the restore "
        "assertion below would be vacuous".format(scroll_before))

    # ...and the viewer's Similar is a DOOR now, wearing the app's one mark, not a toast.
    chip = page.locator(".lbm-actsrow .lbm-similar")
    assert chip.count() == 1
    assert "◈" in chip.inner_text()
    # Same guard again: the tile tap itself is a real action, so a fresh moment can be up
    # over the viewer by now and the chip click would land on the overlay instead.
    _dismiss_any_achievement_toast(page)
    chip.click()

    # The viewer closes, the lookalikes take the GRID's place, and the token is up.
    page.wait_for_selector(".lbm-root", state="detached")
    page.wait_for_selector(".simres-grid .simres-card")
    assert page.locator(".glm-grid").count() == 0, "the library grid is still rendered under Similar"
    assert page.locator(".glm-pager").count() == 0, "the library's pager rode along into Similar"
    tok = page.locator(".glm-simtok")
    assert tok.count() == 1, "no ◈ token in the phone's search bar"
    assert "◈ Similar to this" in tok.inner_text()
    # the token carries the SOURCE picture's own thumb, so "similar to what?" is answered
    assert page.locator(".glm-simtok-th").get_attribute("src") == "/thumbs/100.jpg"
    assert "3 matches" in page.locator(".glm-simcount").inner_text()
    # three neighbours + the badged source tile leading the set
    assert page.locator(".simres-card").count() == 4
    assert page.locator(".simres-card.is-source").count() == 1
    # the token sits inside the real search bar, not floating somewhere else...
    assert page.evaluate(
        "() => document.querySelector('.glm-bar')"
        ".contains(document.querySelector('.glm-simtok'))")
    # ...on its OWN line, below the field, rather than crushing it (the phone's one
    # deliberate deviation from the desktop token's placement)
    geo = page.evaluate("""() => {
        const f = document.querySelector('.glm-search input').getBoundingClientRect();
        const t = document.querySelector('.glm-simtok').getBoundingClientRect();
        return {fieldW: f.width, fieldBottom: f.bottom, tokTop: t.top};
    }""")
    assert geo["tokTop"] >= geo["fieldBottom"] - 1, "the token is beside the field, not under it"
    assert geo["fieldW"] > 200, (
        "the search field was crushed to {:.0f}px by the token".format(geo["fieldW"]))
    # a phone has no hover, so a result's own ◈ door must be visible without one
    assert page.evaluate(
        "() => getComputedStyle(document.querySelector('.simres-door')).opacity") == "1"
    # ...and the results are laid out for a phone, not in the desktop's one 210px column
    cols = page.evaluate(
        "() => getComputedStyle(document.querySelector('.simres-grid'))"
        ".gridTemplateColumns.split(' ').length")
    assert cols == 2, "the lookalikes render {} column(s) on a 390px phone".format(cols)

    # ✕ puts the library back EXACTLY: same query, same tiles, same place on the page.
    page.locator(".glm-simtok-x").click()
    page.wait_for_selector(".glm-grid .glm-tile")
    assert page.locator(".glm-simtok").count() == 0
    assert page.locator(".simres").count() == 0
    assert page.input_value(".glm-search input") == "harness"
    assert page.locator(".glm-grid .glm-tile").count() == tiles_before
    _settle(page)
    assert page.evaluate("() => document.querySelector('.glm-body').scrollTop") == scroll_before


def test_phone_similar_is_dismissed_by_the_back_gesture_too(logged_in_page, monkeypatch):
    """The phone's stand-in for the desktop's Escape.

    AppMobile.jsx pushes ONE same-address history entry when Similar opens, so the
    hardware/browser Back gesture pops it and lands back on the library instead of
    walking out of the app.
    """
    import sys
    monkeypatch.setitem(sys.modules, "moonglade_similar",
                        _fake_similar_module([("104", 0.8), ("105", 0.7)]))

    page = logged_in_page(**PHONE)
    _visit(page, "/")
    page.wait_for_selector(".glm-grid .glm-tile")
    _dismiss_any_achievement_toast(page)

    page.locator(_DOOR_TILE).click()
    page.wait_for_selector(".lbm-root")
    page.locator(".lbm-actsrow .lbm-similar").click()
    page.wait_for_selector(".simres-grid .simres-card")

    page.go_back()
    page.wait_for_selector(".glm-grid .glm-tile")
    assert page.locator(".glm-simtok").count() == 0, "Back left the token up"
    assert "/login" not in page.url, "Back walked out of the app instead of dismissing Similar"


def test_phone_picture_screen_speaks_the_same_similar_mark(logged_in_page):
    """The picture screen was the last surface in the app still wearing ✧.

    Its SIMILAR strip reads ◈ now -- one mark for visual similarity, everywhere -- and
    the model filter beside it says what it does ("Filter by model"), the same rename
    the desktop record took in B2. The strip's own data is left to the live route: with
    no CLIP sidecar installed it renders its honest unavailable line, which is exactly
    the state this test wants to leave alone.
    """
    page = logged_in_page(**PHONE)
    _visit(page, "/")
    page.wait_for_selector(".glm-grid .glm-tile")
    _dismiss_any_achievement_toast(page)

    page.locator(_DOOR_TILE).click()
    page.wait_for_selector(".lbm-root")
    page.click(".lbm-actsrow >> text=Details")
    page.wait_for_selector(".idm-similar")

    head = page.locator(".idm-similar .idm-subhead").inner_text()
    assert "◈ SIMILAR" in head, "the picture screen still wears the old mark: {!r}".format(head)
    recrow = page.locator(".idm-recrow").inner_text()
    assert "Filter by model" in recrow
    assert "Find similar (model)" not in recrow


# ---------------------------------------------------------------------------
# 9. Contests on the phone (Contest Mobile Handoff.dc.html, Session D 2026-09-04)
# ---------------------------------------------------------------------------
# 390x844 is the frame the handoff is drawn at (an iPhone-class CSS viewport) and it is
# under useIsMobile.js's 520px breakpoint (430 until 2026-09-07), so the REAL mobile build mounts -- these drive
# AppMobile.jsx, not App.jsx behind a narrow window.
MOBILE = {"width": 390, "height": 844}

# Every contest read is fulfilled from here. Two reasons, and the second is the important
# one: (a) the harness's PixAI key is a fake, so a real board read would soft-fail to an
# empty board and there would be nothing to measure; (b) ENTERING A CONTEST IS AN
# IRREVERSIBLE, PUBLIC ACCOUNT WRITE that PixAI offers no way to withdraw. Nothing here may
# reach the real route even by accident, so /api/contest/enter is intercepted and the test
# asserts that the only body it ever saw was the server's own unconfirmed preview.
_MOBILE_BOARD = {
    "contests": [
        {"id": "c-off", "slug": "autumn-grimoire", "title": "Autumn Grimoire",
         "type": "official", "status": "running", "active": True,
         "vote_type": "creator_pick", "prize_amount": 1000000,
         "prize_distribution": [{"rank": 1, "count": 1, "amount": 1000000}],
         "cover_url": "", "start_at": "2026-08-01T00:00:00.000Z",
         "end_at": "2099-01-01T00:00:00.000Z", "result_at": "2099-02-01T00:00:00.000Z",
         "url": "https://pixai.art/en/contest/autumn-grimoire",
         "description": "Show us an autumn grimoire.", "rules": [],
         "tack_name": "autumn", "desc_url": "", "result_url": ""},
        {"id": "c-com", "slug": "jojo-pose", "title": "JoJo Pose",
         "type": "community", "status": "running", "active": True,
         "vote_type": "user_vote", "prize_amount": 500000,
         "prize_distribution": [{"rank": 1, "count": 1, "amount": 200000},
                                {"rank": 2, "count": 3, "amount": 50000},
                                {"rank": 3, "count": 5, "amount": 30000}],
         "cover_url": "", "start_at": "2026-08-01T00:00:00.000Z",
         "end_at": "2099-01-01T00:00:00.000Z", "result_at": "2099-02-01T00:00:00.000Z",
         "url": "https://pixai.art/en/contest/jojo-pose",
         "description": "Your coolest JoJo pose.", "rules": [],
         "tack_name": "jojo", "desc_url": "", "result_url": ""},
    ],
    "official": 1, "community": 1,
}
_MOBILE_ART = {
    "csrf": "harness-csrf",
    "items": [
        {"media_id": "a%d" % i, "artwork_id": "art%d" % i, "title": "Piece %d" % i,
         "thumb": "/thumbs/a%d.jpg" % i, "is_video": False, "is_nsfw": False,
         "date": "2026-08-20", "created_at": "2026-08-20T00:00:00", "tags": [],
         "public": True, "sensitive": False, "likes": 0, "comments": 0}
        for i in range(6)
    ],
}
# The SAME published-art shape, but keyed to the media_ids `render_server` actually writes
# into the harness catalog (100..105). The image-side entry path needs that overlap and the
# board-side path does not: pre-selection matches the media_id the LIBRARY grid handed down
# against the eligible set read from /api/myart/items, so with `_MOBILE_ART`'s a0..a5 the
# tick could never land and the test would pass for the wrong reason (an empty selection
# looks identical to one the source picture was rightly refused from). Titles carry the
# media_id because the picker's tile puts `title` on the button -- that attribute is the
# only thing in the rendered DOM that says WHICH picture came back ticked.
_MOBILE_ART_FROM_LIBRARY = {
    "csrf": "harness-csrf",
    "items": [
        {"media_id": str(100 + i), "artwork_id": "art-lib-%d" % i,
         "title": "Harness %d" % (100 + i),
         "thumb": "/thumbs/%d.jpg" % (100 + i), "is_video": False, "is_nsfw": False,
         "date": "2026-08-20", "created_at": "2026-08-20T00:00:00", "tags": [],
         "public": True, "sensitive": False, "likes": 0, "comments": 0}
        for i in range(6)
    ],
}


def _json_route(page, pattern, payload):
    page.route(pattern, lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(payload)))


def _open_contests_on_the_phone(page, entry_posts):
    """Menu -> Contests, with every contest read stubbed and the entry POST captured."""
    _json_route(page, "**/api/contests", _MOBILE_BOARD)
    _json_route(page, "**/api/contest/mine",
                {"contests": [], "total_entries": 0, "sync_running": False})
    _json_route(page, "**/api/contest/*/artworks", {"entries": [], "total_count": 104})
    _json_route(page, "**/api/contest/sync", {"started": False, "skipped": "recent"})
    _json_route(page, "**/api/myart/items", _MOBILE_ART)

    def _enter(route):
        entry_posts.append(route.request.post_data or "")
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"preview": True, "spends_credits": None}))
    page.route(_CONTEST_ENTER_ROUTE, _enter)

    # Motion frozen BEFORE the Menu is opened: the pushed screen slides in over 220ms
    # (glmScreenIn's translateX), and a screen measured mid-slide is a screen sitting
    # partly off the right edge -- the exact "measured an interpolated value" trap this
    # module's _FREEZE_MOTION_CSS exists for.
    page.goto("/", wait_until="domcontentloaded")
    page.wait_for_selector(".glm-body", timeout=10_000)
    _freeze_motion(page)
    page.click('button[title="More"]')
    page.click('.glm-menu-item:has-text("Contests")')
    page.wait_for_selector(".cmb-hero", timeout=10_000)
    _settle(page)


def test_the_phone_contest_board_is_a_hero_over_cards_with_one_door_to_my_entries(
        logged_in_page):
    """Frame D1. The mobile build really mounts at 390pt, the official contest renders as a
    16:9 hero carrying the GOLD METAL official badge, community contests are list cards
    below it, and "MY ENTRIES" is a real 44pt target rather than the 9px label the frame
    draws (the handoff's own plumbing note asks for >=44pt, which a 9px line is not).

    Measured, not read off the stylesheet: a 16/9 aspect-ratio declaration means nothing if
    an ancestor's flex rules override the box, which is exactly the class of defect this
    module exists for."""
    page = logged_in_page(**MOBILE)
    _open_contests_on_the_phone(page, [])

    assert page.locator(".glm-screen").count() == 1, (
        "the desktop shell mounted at 390pt -- this is not the mobile build")
    geo = page.evaluate("""() => {
        const r = (s) => { const el = document.querySelector(s); if (!el) return null;
                           const b = el.getBoundingClientRect();
                           return {w: b.width, h: b.height, top: b.top, bottom: b.bottom}; };
        const badge = document.querySelector('.cmb-hero .cmb-badge');
        const bcs = badge ? getComputedStyle(badge) : null;
        return {hero: r('.cmb-hero'), door: r('.cmb-door'), card: r('.cmb-card'),
                cards: document.querySelectorAll('.cmb-card').length,
                badgeClass: badge ? badge.className : '',
                badgeColor: bcs ? bcs.color : '',
                badgeFill: bcs ? bcs.backgroundImage : '',
                badgeBg: bcs ? bcs.backgroundColor : ''};
    }""")
    ratio = geo["hero"]["w"] / geo["hero"]["h"]
    assert abs(ratio - 16 / 9) < 0.05, (
        "the official hero renders {:.3f}:1, not the D1 frame's 16:9".format(ratio))
    assert "official" in geo["badgeClass"], "the hero's badge is not the OFFICIAL one"
    # The hue law, checked against the LIVE token rather than a hex written here: OFFICIAL
    # is GOLD AND METALLIC (owner ruling, 2026-09-05), and a regression to the flat lavender
    # this surface wore earlier that same day is the specific mistake worth catching.
    # Because the badge is metal, its gold is in the FACE, not in the text: the ink is dark
    # for contrast and --gold is the gradient's dominant stop. Reading backgroundImage is
    # therefore reading the badge's colour, not a detail of how it is built -- a flat gold
    # fill would fail here too, and it should: the ruling says metallic.
    # The desktop half of the same law is driven by
    # test_official_and_community_wear_one_badge_law_on_both_surfaces below.
    lav, gold = page.evaluate("""() => {
        const cs = getComputedStyle(document.documentElement);
        const probe = (v) => { const el = document.createElement('span');
            el.style.color = v; document.body.appendChild(el);
            const c = getComputedStyle(el).color; el.remove(); return c; };
        return [probe(cs.getPropertyValue('--lavender').trim()),
                probe(cs.getPropertyValue('--gold').trim())];
    }""")
    assert "gradient" in geo["badgeFill"] and gold in geo["badgeFill"], (
        "the OFFICIAL badge's face is {!r} -- the law is the house gold metal, a gradient "
        "whose dominant stop is the live --gold ({})".format(geo["badgeFill"], gold))
    assert lav not in geo["badgeFill"] and geo["badgeBg"] != lav, (
        "the OFFICIAL badge is painted lavender ({}) -- that was this surface's pre-ruling "
        "state and is the exact revert this pins: {!r}".format(lav, geo))
    assert geo["door"]["h"] >= 44, (
        "MY ENTRIES is {:.1f}px tall -- under the handoff's 44pt floor".format(
            geo["door"]["h"]))
    assert geo["cards"] == 1 and geo["card"]["h"] >= 44, (
        "community cards missing or under 44pt: {!r}".format(geo))

    # THE COMMUNITY HALF OF THE SAME HUE LAW, which nothing guarded. Only the official half
    # is asserted above, so a revert of the community half -- to the gold it wore before the
    # ruling moved gold to OFFICIAL, or to the mauve the desktop board painted before that
    # -- would have gone through green.
    #
    # Read one tap OFF the board, and that is deliberate rather than a wander: the board's
    # community CARD renders no badge at all. `.cmb-badge` is emitted in exactly two places
    # in the whole gallery -- ContestsMobile's hero (always `official`) and
    # ContestDetailMobile's banner (`official` or `community`) -- so the community hue's
    # only live pixel anywhere is the detail banner of the very contest this card opens.
    # Following the card there is the shortest honest path to the thing being guarded; a
    # `.cmb-badge.community` probe synthesised on the board would assert a rule, not a
    # rendering, which is the substring-in-a-blob habit this whole module exists to break.
    page.click(".cmb-card")
    page.wait_for_selector(".cmb-banner .cmb-badge", timeout=10_000)
    _settle(page)
    com = page.evaluate("""() => {
        const badge = document.querySelector('.cmb-banner .cmb-badge');
        const cs = getComputedStyle(document.documentElement);
        // null (not a colour) for a token that does not resolve, so a vanished --mauve
        // cannot make the "differs from mauve" assertion below quietly vacuous.
        const probe = (name) => { const v = cs.getPropertyValue(name).trim();
            if (!v) return null;
            const el = document.createElement('span');
            el.style.color = v; document.body.appendChild(el);
            const c = getComputedStyle(el).color; el.remove(); return c; };
        return {cls: badge.className, color: getComputedStyle(badge).color,
                gold: probe('--gold'), lav: probe('--lavender'), mauve: probe('--mauve')};
    }""")
    assert "community" in com["cls"], (
        "the community contest's banner badge is not the COMMUNITY one: {!r}".format(
            com["cls"]))
    assert None not in (com["gold"], com["lav"], com["mauve"]), (
        "a token this assertion compares against no longer resolves: {!r}".format(com))
    assert com["color"] == com["lav"], (
        "the COMMUNITY badge is {} -- the 2026-09-05 ruling assigns it --lavender ({})"
        .format(com["color"], com["lav"]))
    assert com["color"] != com["gold"] and com["color"] != com["mauve"], (
        "the COMMUNITY badge collapsed onto another hue (gold {}, mauve {}) -- gold is what "
        "this badge wore before the ruling handed gold to OFFICIAL, and mauve is what "
        "desktop's .mgct-badge.community painted before that; both are the reverts this "
        "guards".format(com["gold"], com["mauve"]))


def test_the_phone_contest_detail_folds_to_one_open_section_over_a_pinned_enter_bar(
        logged_in_page):
    """Frame D2. Three sections, the brief open on arrival, exactly ONE body rendered at a
    time, and the Enter bar pinned INSIDE the viewport (sticky) rather than scrolled off the
    bottom of a long brief -- which is the whole reason the handoff pins it."""
    page = logged_in_page(**MOBILE)
    _open_contests_on_the_phone(page, [])
    page.click(".cmb-hero")
    page.wait_for_selector(".cmb-acc", timeout=10_000)
    _settle(page)

    read = """() => {
        const heads = [...document.querySelectorAll('.cmb-sechead')];
        const bar = document.querySelector('.cmb-enterbar').getBoundingClientRect();
        const btn = document.querySelector('.cmb-enterbar .cmb-metal').getBoundingClientRect();
        return {
            sections: heads.length,
            open: heads.map(h => h.parentElement.querySelector('.cmb-secbody') ? 1 : 0),
            labels: heads.map(h => h.querySelector('.cmb-seclab').textContent.trim()),
            shortest: Math.min(...heads.map(h => h.getBoundingClientRect().height)),
            barBottom: bar.bottom, btnH: btn.height, vh: window.innerHeight,
        };
    }"""
    before = page.evaluate(read)
    assert before["sections"] == 3, (
        "expected brief/prizes/requirements, got {!r}".format(before["labels"]))
    assert sum(before["open"]) == 1 and before["open"][0] == 1, (
        "the accordion is not one-open-at-a-time with the brief first: {!r}".format(before))
    assert before["shortest"] >= 44, (
        "an accordion row is {:.1f}px tall -- under 44pt".format(before["shortest"]))
    assert before["barBottom"] <= before["vh"] + 0.5, (
        "the Enter bar's bottom is at {:.1f} in an {:.0f}px viewport -- it is not pinned"
        .format(before["barBottom"], before["vh"]))
    assert before["btnH"] >= 44, (
        "the Enter button is {:.1f}px tall -- under 44pt".format(before["btnH"]))

    # Opening Prizes closes the brief: one section open, never two.
    page.click(".cmb-acc .cmb-sec:nth-child(2) .cmb-sechead")
    _settle(page)
    after = page.evaluate(read)
    assert sum(after["open"]) == 1 and after["open"][1] == 1, (
        "opening a second section did not close the first: {!r}".format(after))


def test_the_phone_entry_screen_never_enters_on_one_tap(logged_in_page):
    """Frame D3, and the safety half of it. The confirm bar is DISABLED with nothing picked,
    the tiles are real 44pt+ targets, picking two arms the bar with the count -- and no
    confirmed POST ever leaves this test: the only /api/contest/enter body seen is the
    server's own unconfirmed preview, which touches no account. Entering a contest is
    irreversible and public; a rendering test must never fire one."""
    posts = []
    page = logged_in_page(**MOBILE)
    _open_contests_on_the_phone(page, posts)
    page.click(".cmb-hero")
    page.wait_for_selector(".cmb-enterbar .cmb-metal", timeout=10_000)
    page.click(".cmb-enterbar .cmb-metal")
    page.wait_for_selector(".cmb-entry", timeout=10_000)
    page.wait_for_selector(".cmb-tile", timeout=10_000)
    _settle(page)

    read = """() => {
        const btn = document.querySelector('.cmb-confirmbar .cmb-metal');
        const bar = document.querySelector('.cmb-confirmbar');
        const tile = document.querySelector('.cmb-tile').getBoundingClientRect();
        return {disabled: btn.disabled, label: btn.textContent.trim(),
                tileW: tile.width, tileH: tile.height,
                barPad: getComputedStyle(bar).paddingBottom,
                screenText: document.querySelector('.cmb-entry').textContent,
                feeSlots: document.querySelectorAll('.cmb-entry .fee').length,
                count: document.querySelector('.cmb-entryhead .n').textContent.trim()};
    }"""
    idle = page.evaluate(read)
    # THERE ARE NO ENTRY FEES (owner, 2026-09-05). This screen used to end its tag line with
    # a cost slot -- "Free", "♦ N CR", or "Entry fee unverified" -- and all three told a
    # reader that entering might cost something. Asserted as RENDERED TEXT rather than as
    # the absence of a class, so re-introducing the sentence by any other markup fails too.
    assert idle["feeSlots"] == 0, "the entry screen still renders a cost slot"
    assert not re.search(r"\bfree\b|\bfees?\b|\bCR\b|♦|credit", idle["screenText"], re.I), (
        "the entry screen still says something about cost: {!r}".format(idle["screenText"]))
    assert idle["disabled"] is True, "the confirm bar is armed with nothing picked"
    assert "Pick at least one" in idle["label"], (
        "the disabled bar dropped its reason: {!r}".format(idle["label"]))
    assert idle["tileW"] >= 44 and idle["tileH"] >= 44, (
        "picker tiles are {:.1f}x{:.1f} -- under 44pt".format(idle["tileW"], idle["tileH"]))
    # >=18px of bottom padding: the handoff's own D3 value, and what
    # max(18px, env(safe-area-inset-bottom)) resolves to on a browser reporting no inset
    # (which headless chromium does) -- so this measures the max(), not the inset.
    assert float(idle["barPad"].replace("px", "")) >= 18, (
        "the confirm bar sits flush against the safe area: {}".format(idle["barPad"]))

    page.click(".cmb-grid .cmb-tile:nth-child(1)")
    page.click(".cmb-grid .cmb-tile:nth-child(2)")
    _settle(page)
    armed = page.evaluate(read)
    assert armed["disabled"] is False, "two picks did not arm the confirm bar"
    assert "2 images" in armed["label"], (
        "the confirm bar does not count the picks: {!r}".format(armed["label"]))
    assert armed["count"] == "2 selected", (
        "the header counter reads {!r} -- the board row states no entry limit, so it must "
        "not quote a '/ N max' the contest never published".format(armed["count"]))
    # Not one body, confirmed or otherwise: picking no longer probes the route (the cost
    # probe died with the cost slot), so the only thing that may POST here is the bar.
    assert posts == [], (
        "an entry POST left this test without the confirm bar being pressed: {!r}"
        .format(posts))


def test_the_phone_enters_from_a_picture_with_that_picture_pre_ticked(
        logged_in_page, no_confirmed_contest_entry):
    """THE IMAGE-SIDE DOOR, and the half of D3 the board-side tests structurally cannot see.

    The handoff keeps THREE entry points and only two of them start from a picture -- the
    lightbox's action row and Image Details' chip -- and those two are exactly the two that
    PRE-SELECT the picture they came from. Every test above drives the third (the board's
    own Enter bar), which pre-selects nothing by design, so the whole pre-selection chain
    shipped unmeasured: LightboxMobile's chip -> AppMobile's `openContestFor` -> the ENTER
    INTO A CONTEST sheet -> `openContestEntry(contest, contestFor)` -> ContestEntryMobile's
    one-shot `seeded` effect. Four hand-offs of one media_id, any of which can drop it, and
    a dropped one fails SILENTLY: the screen simply opens with nothing ticked, which is also
    what a legitimately ineligible source looks like.

    Driven as a person drives it, at 390pt: tap a real grid tile, tap the chip, pick a
    contest in the sheet, and land on the entry screen. Every one of those is an ordinary
    `page.click`, which makes this test ALSO the standing guard on the chooser sheet's
    z-index: Playwright refuses a click on a covered element, so if the sheet ever slips
    back under the viewer that opened it (the 2026-09-04 defect -- MobileSheet's shared
    30/31 behind .lbm-root's 55) the row click fails outright with the intercepting
    element named. The assertion is that the ticked tile is THAT picture and no other, and
    that the confirm bar came up armed and counting one. The bar is left unpressed -- this
    proves the screen opens ready, never that it fires -- and the module-wide guard fixture
    is asserted for the same guarantee the board-side test makes with its own `posts` list.

    ONE of the two image-side doors is driven here, not both: the lightbox's. Image
    Details' chip is gated on `row.artwork_id` (ImageDetailsMobile.jsx) and `render_server`
    seeds all six catalog rows from a blank CATALOG_FIELDS template, so artwork_id is ""
    for every one of them and that chip does not render on this fixture at all. Reaching it
    would mean stubbing /api/next/detail with an invented published row -- a fixture this
    module does not have and this test is not the place to invent. The z-index half is
    covered regardless, and by the HARDER of the two: .idm-root is 50 and .lbm-root is 55,
    so a chooser that clears the lightbox clears Image Details by construction. What stays
    unmeasured is Details' own chip wiring, not the layer it opens onto.
    """
    page = logged_in_page(**MOBILE)
    _json_route(page, "**/api/contests", _MOBILE_BOARD)
    _json_route(page, "**/api/contest/*/artworks", {"entries": [], "total_count": 104})
    _json_route(page, "**/api/myart/items", _MOBILE_ART_FROM_LIBRARY)

    page.goto("/", wait_until="domcontentloaded")
    page.wait_for_selector(".glm-body", timeout=10_000)
    _freeze_motion(page)                      # before the lightbox's own 280ms slide-in
    page.wait_for_selector(".glm-tile", timeout=10_000)
    # Catalog row 100 is the ONE row render_server gives a prompt_full to ("harness prompt"),
    # so its caption is unique among the six -- rows 101..105 caption "harness row n". That
    # makes this a deterministic handle on a known media_id without a data-* attribute the
    # component does not ship.
    page.click('.glm-tile:has-text("harness prompt")')
    page.wait_for_selector(".lbm-root", timeout=10_000)
    _settle(page)

    page.click('.lbm-chip:has-text("Enter contest")')
    page.wait_for_selector(".glm-sheet .mgctch-row", timeout=10_000)
    _settle(page)
    rows = page.locator(".glm-sheet .mgctch-row")
    assert rows.count() == 2, (
        "the chooser is not offering both running contests: {!r}".format(
            rows.all_inner_texts()))

    # A REAL click, and the load-bearing one. Playwright's actionability check refuses a
    # click on a covered element and names the element doing the covering, so this single
    # line is what holds the chooser above the viewer that opened it: when the sheet rode
    # MobileSheet's shared 30/31 it failed here with "<button class='lbm-chip'>Similar
    # </button> from .lbm-root subtree intercepts pointer events" -- .lbm-root is z 55 and
    # opaque. It now sits on contest-mobile.css's own rung (.cmb-choosersheet, 67/68), the
    # tap lands on the row itself, and picking the contest closes the sheet and mounts the
    # entry screen at z 70.
    page.click('.glm-sheet .mgctch-row:has-text("JoJo Pose")')
    page.wait_for_selector(".cmb-entry .cmb-tile", timeout=10_000)
    _settle(page)

    got = page.evaluate("""() => {
        const tiles = [...document.querySelectorAll('.cmb-entry .cmb-tile')];
        const on = tiles.filter(t => t.classList.contains('on'));
        const btn = document.querySelector('.cmb-confirmbar .cmb-metal');
        return {
            tiles: tiles.length,
            ticked: on.map(t => t.getAttribute('title')),
            pressed: on.map(t => t.getAttribute('aria-pressed')),
            head: document.querySelector('.cmb-entryhead .t').textContent.trim(),
            count: document.querySelector('.cmb-entryhead .n').textContent.trim(),
            label: btn.textContent.trim(), disabled: btn.disabled,
            notes: [...document.querySelectorAll('.cmb-entrynote')]
                     .map(n => n.textContent.trim()),
        };
    }""")
    assert got["head"] == "Enter JoJo Pose", (
        "the sheet's pick did not carry into the entry screen: {!r}".format(got["head"]))
    assert got["tiles"] == 6, (
        "the picker is not showing the eligible library: {!r}".format(got))
    assert got["ticked"] == ["Harness 100"], (
        "the entry screen opened with {!r} ticked -- the lightbox's own picture (Harness "
        "100) must arrive pre-selected, and nothing else may".format(got["ticked"]))
    assert got["pressed"] == ["true"], (
        "the ticked tile does not report aria-pressed -- a screen reader is told nothing "
        "was pre-selected: {!r}".format(got["pressed"]))
    assert got["notes"] == [], (
        "the entry screen is explaining itself instead of pre-selecting: {!r}".format(
            got["notes"]))
    assert got["count"] == "1 selected", (
        "the header counter reads {!r}".format(got["count"]))
    assert got["disabled"] is False, "the pre-selection did not arm the confirm bar"
    assert "1 image" in got["label"] and "1 images" not in got["label"], (
        "the confirm bar mis-counts (or mis-pluralises) one pick: {!r}".format(got["label"]))
    # Same guarantee the board-side test makes with its own `posts` list, read off the
    # module-wide guard instead -- which is the whole reason that guard exists: this test
    # reaches the armed confirm bar through a door `_open_contests_on_the_phone` never opens.
    #
    # NOTHING AT ALL is on that wire now, and that is the assertion. Until 2026-09-05 the
    # seeded pick fired an unconfirmed POST to ask the route what an entry WOULD cost, and
    # this block waited for that body; the cost slot is gone (there are no entry fees), the
    # probe went with it, and /api/contest/enter is now touched by exactly one thing: a
    # press of the confirm bar, which this test does not make.
    assert no_confirmed_contest_entry == [], (
        "the entry screen reached /api/contest/enter without the confirm bar being "
        "pressed: {!r}".format(no_confirmed_contest_entry))


def test_the_phone_my_entries_door_filters_the_same_board_and_adds_a_status_line(
        logged_in_page):
    """The handoff's one door: "MY ENTRIES · n" does not open a second layout, it filters
    THIS board to the contests this library has pieces in and adds ONE status line to the
    same card. Asserted as rendered DOM -- same .cmb-card class, one row per entered
    contest, a derived status (running / awaiting results / won / not placed), and no
    official hero, because a filtered board is not the board plus a list."""
    page = logged_in_page(**MOBILE)
    _open_contests_on_the_phone(page, [])
    # Re-answer /api/contest/mine with real rows, then reopen the screen so it re-reads.
    _json_route(page, "**/api/contest/mine", {"sync_running": False, "total_entries": 3,
        "contests": [
            {"contest_id": "c-com", "slug": "jojo-pose", "title": "JoJo Pose",
             "type": "community", "active": True, "won": False,
             "end_at": "2099-01-01T00:00:00.000Z", "result_at": "2099-02-01T00:00:00.000Z",
             "url": "", "entry_artwork_ids": ["art0", "art1"], "entries": []},
            {"contest_id": "c-old", "slug": "spring-oath", "title": "Spring Oath",
             "type": "official", "active": False, "won": True,
             "end_at": "2026-08-20T00:00:00.000Z", "result_at": "2026-08-25T00:00:00.000Z",
             "url": "", "entry_artwork_ids": ["art2"], "entries": []},
        ]})
    page.click(".glm-screen-back")
    page.click('button[title="More"]')
    page.click('.glm-menu-item:has-text("Contests")')
    page.wait_for_selector(".cmb-door", timeout=10_000)
    page.click(".cmb-door")
    page.wait_for_selector(".cmb-cardstatus", timeout=10_000)
    _settle(page)

    got = page.evaluate("""() => [...document.querySelectorAll('.cmb-card')].map(c => ({
        name: c.querySelector('.cmb-cardname').textContent.trim(),
        status: (c.querySelector('.cmb-cardstatus') || {}).textContent || '',
        cls: (c.querySelector('.cmb-cardstatus') || {}).className || '',
    }))""")
    assert len(got) == 2, (
        "My entries is not the board filtered to entered contests: {!r}".format(got))
    by = {g["name"]: g for g in got}
    assert "RUNNING" in by["JoJo Pose"]["status"], by
    assert "2 pieces" in by["JoJo Pose"]["status"], by
    # An ENDED contest is not on the running board at all, so its card is rebuilt from the
    # entries row itself -- the only way a finished contest can still be opened in-app.
    assert "WON" in by["Spring Oath"]["status"] and "won" in by["Spring Oath"]["cls"], by
    assert page.locator(".cmb-hero").count() == 0, (
        "the official hero is still painted in the My-entries view")


# A brief long enough that the detail REALLY scrolls at 390x844. The harness board's own
# one-liner descriptions leave the detail shorter than the screen, and a scroll test on a
# surface with nothing to scroll proves nothing.
_LONG_BRIEF = ("Show us an autumn grimoire. " * 60).strip()


def _board_with_a_long_brief():
    board = json.loads(json.dumps(_MOBILE_BOARD))
    for row in board["contests"]:
        row["description"] = _LONG_BRIEF
    return board


def _open_contests_from_the_control_tab(page, board):
    """The owner's own route in: stand on Control, then the menu -> Contests."""
    _json_route(page, "**/api/contests", board)
    _json_route(page, "**/api/contest/mine",
                {"contests": [], "total_entries": 0, "sync_running": False})
    _json_route(page, "**/api/contest/*/artworks", {"entries": [], "total_count": 104})
    _json_route(page, "**/api/contest/sync", {"started": False, "skipped": "recent"})
    _json_route(page, "**/api/myart/items", _MOBILE_ART)
    page.goto("/", wait_until="domcontentloaded")
    page.wait_for_selector(".glm-body", timeout=10_000)
    _freeze_motion(page)
    page.click('.glm-navitem:has-text("Control")')
    page.wait_for_selector(".glm-tab", timeout=10_000)
    _settle(page)
    page.click('button[title="More"]')
    page.click('.glm-menu-item:has-text("Contests")')
    page.wait_for_selector(".cmb-hero", timeout=10_000)
    _settle(page)


# What the Control tab paints, and nothing the Contests screen ever paints: if one of these
# is under the thumb, the screen has been scrolled away and the tab beneath is showing.
_CONTROL_MARKS = ".mgcp-tilenote, .mgcp-skindesc, .mgcp-skinsrow, .mgcp-tilesmall, .ctm-stat"

_SCROLL_READ = """() => {
    const body = document.querySelector('.glm-body');
    const screen = document.querySelector('.glm-screen');
    const sbody = document.querySelector('.glm-screen-body');
    const detail = document.querySelector('.cmb-detailbody');
    const bar = document.querySelector('.cmb-enterbar');
    const r = screen.getBoundingClientRect();
    const b = bar.getBoundingClientRect();
    const sb = sbody.getBoundingClientRect();
    // Three probes down the screen's own height: what a thumb would actually be on.
    const at = [r.top + 30, (r.top + r.bottom) / 2, r.bottom - 30].map((y) => {
        const el = document.elementFromPoint(Math.round(r.left + r.width / 2), Math.round(y));
        if (!el) return null;
        return (el.closest(CONTROL_MARKS) ? 'CONTROL:' : '') + (el.className || el.tagName);
    });
    // VISIBLE, not merely laid out: the Control tab is always sitting under this screen,
    // so an intersection test would count it even when the opaque screen covers it. A
    // Control node counts only if it WINS the hit test at its own centre.
    const shown = [...document.querySelectorAll(CONTROL_MARKS)].filter((el) => {
        const q = el.getBoundingClientRect();
        if (q.width <= 0 || q.height <= 0) return false;
        const cx = Math.round(q.left + q.width / 2), cy = Math.round(q.top + q.height / 2);
        if (cx < 0 || cy < 0 || cx > window.innerWidth || cy > window.innerHeight) return false;
        const hit = document.elementFromPoint(cx, cy);
        return !!hit && (hit === el || el.contains(hit));
    }).length;
    return {
        bodyTop: body.scrollTop, bodyRange: body.scrollHeight - body.clientHeight,
        screenTop: r.top, screenBottom: r.bottom,
        sbodyRange: sbody.scrollHeight - sbody.clientHeight,
        detailTop: detail.scrollTop, detailRange: detail.scrollHeight - detail.clientHeight,
        barBottom: b.bottom, sbodyBottom: sb.bottom, at, controlShown: shown,
    };
}""".replace("CONTROL_MARKS", json.dumps(_CONTROL_MARKS))


def _flick(page, x=195, y=430, times=8):
    """A real wheel over the detail, well past the end of anything on this screen."""
    page.mouse.move(x, y)
    for _ in range(times):
        page.mouse.wheel(0, 600)
    _settle(page)


def test_the_phone_contest_detail_scrolls_itself_and_never_the_control_tab_under_it(
        logged_in_page):
    """THE 2026-09-05 DEFECT, as the owner described it: opening a contest, the enter button
    is a floating panel in front of the rest, scrolling behind it. Tapping back to contest
    details and scrolling again lands you in the Control panel underneath instead.

    Measured before the fix, at 390x844 with Control as the standing tab: `.glm-screen` is
    position:absolute INSIDE `.glm-body`, which is the tab's own scroller and still held the
    whole Control panel underneath -- 1579px of range against a 600px screen. The detail's
    scroll chained straight out of `.glm-screen-body` into that, and the entire Contests
    screen slid off the top (top +172 -> -1407), leaving the Control panel's tiles under the
    thumb. The same root cause opened a screen at top -824 -- invisible -- whenever the tab
    beneath happened to be scrolled when Contests was tapped.

    What this asserts, in the order it goes wrong: the DETAIL is what scrolls; the tab's
    scroller never moves; the screen never leaves the place it was drawn; the Enter bar
    stays on the bottom edge of that screen; and no Control-panel node is ever inside the
    screen's rectangle. Then it walks the owner's second half -- into the entry screen, back
    out, scroll again -- because that is where he saw it, and finally proves itself by
    putting the pre-fix CSS back in the page and watching every one of those flip."""
    page = logged_in_page(**MOBILE)
    _open_contests_from_the_control_tab(page, _board_with_a_long_brief())
    page.click(".cmb-hero")
    page.wait_for_selector(".cmb-acc", timeout=10_000)
    _settle(page)

    start = page.evaluate(_SCROLL_READ)
    assert start["bodyRange"] > 200, (
        "the Control tab under this screen has only {:.0f}px of scroll range -- this test "
        "cannot see the defect it exists for".format(start["bodyRange"]))
    assert start["detailRange"] > 100, (
        "the contest detail has only {:.0f}px of its own to scroll; the brief fixture is "
        "not long enough for this to mean anything".format(start["detailRange"]))
    assert start["sbodyRange"] <= 1, (
        "the Contests screen's body still scrolls ({:.0f}px) -- the detail is meant to fill "
        "it exactly and own the scrolling itself".format(start["sbodyRange"]))
    assert abs(start["barBottom"] - start["sbodyBottom"]) <= 1, (
        "the Enter bar's bottom is {:.1f} against a screen body ending at {:.1f} -- it is "
        "not the layer's footer".format(start["barBottom"], start["sbodyBottom"]))

    _flick(page)
    after = page.evaluate(_SCROLL_READ)
    assert after["detailTop"] > 100, (
        "the flick did not scroll the detail at all ({:.0f}px) -- nothing was measured"
        .format(after["detailTop"]))
    assert after["bodyTop"] == 0, (
        "the Control tab's scroller moved to {:.0f} -- the flick chained out of the contest "
        "screen".format(after["bodyTop"]))
    assert abs(after["screenTop"] - start["screenTop"]) < 1, (
        "the Contests screen moved from {:.1f} to {:.1f} -- it is being scrolled away"
        .format(start["screenTop"], after["screenTop"]))
    assert after["controlShown"] == 0 and not any(
        (p or "").startswith("CONTROL:") for p in after["at"]), (
        "the Control panel is showing through the contest screen: {!r}".format(after))
    assert abs(after["barBottom"] - after["sbodyBottom"]) <= 1, (
        "the Enter bar left the bottom edge while the detail scrolled: {!r}".format(after))

    # The owner's second half: into the entry screen, back to the detail, scroll again.
    page.click(".cmb-enterbar .cmb-metal")
    page.wait_for_selector(".cmb-entry .cmb-tile", timeout=10_000)
    _settle(page)
    page.click(".cmb-entryhead .cmb-back")
    page.wait_for_selector(".cmb-acc", timeout=10_000)
    _settle(page)
    _flick(page)
    back = page.evaluate(_SCROLL_READ)
    assert back["bodyTop"] == 0 and back["controlShown"] == 0, (
        "coming back from the entry screen and scrolling still lands in the Control "
        "panel: {!r}".format(back))
    assert abs(back["screenTop"] - start["screenTop"]) < 1, (
        "the Contests screen is no longer where it was drawn after the round trip: {!r}"
        .format(back))

    # PROVE IT. The pre-fix state, applied as an in-page override -- never a committed
    # revert: the tab's scroller unlocked and both latches off, which is exactly what
    # shipped on 2026-09-04. Every assertion above must flip.
    page.add_style_tag(content=(
        ".glm-body:has(.glm-screen) { overflow: auto !important; }"
        ".glm-screen-body, .cmb-detailbody { overscroll-behavior: auto !important; }"))
    _settle(page)
    _flick(page, times=12)
    broke = page.evaluate(_SCROLL_READ)
    assert broke["bodyTop"] > 100, (
        "with the pre-fix CSS back the tab's scroller still did not move -- this guard is "
        "not measuring what it claims to: {!r}".format(broke))
    assert broke["screenTop"] < start["screenTop"] - 100, (
        "with the pre-fix CSS back the Contests screen did not slide away: {!r}".format(
            broke))
    assert broke["controlShown"] > 0, (
        "with the pre-fix CSS back the Control panel still never showed -- the defect this "
        "guards is not reproducible from here: {!r}".format(broke))


def test_official_and_community_wear_one_badge_law_on_both_surfaces(logged_in_page):
    """ONE BADGE LAW, PINNED ON BOTH SURFACES AT ONCE (owner ruling, 2026-09-05): OFFICIAL
    is GOLD AND METALLIC, COMMUNITY is LAVENDER, on the phone AND on the desktop board.

    The ruling was given at the desktop board, whose official contest is already framed in
    gold -- "I think the official contest badge should be gold too. and metallic IMO" -- and
    it supersedes the same day's earlier alignment, which had made official lavender on both
    surfaces. Lavender, the pair's other hue, moves to COMMUNITY.

    Both halves are read in ONE test, from REAL renders in two viewports, and asserted equal
    to each other as well as to the law: a drift on either surface fails here, which is the
    only way two stylesheets stay in step. Because OFFICIAL is metal, its gold lives in the
    FACE and its text is dark ink, so the official half is read off backgroundImage -- the
    gradient must carry the live --gold as its dominant stop, and a FLAT gold fill fails
    here too, which is the "and metallic" half of the ruling.

    The desktop pair is read where each word actually renders: the board's own section
    headers (.mgct-h.official / .mgct-h.community) and the detail banner's badge, which
    means opening a contest -- the same one tap a person makes."""
    phone = logged_in_page(**MOBILE)
    _open_contests_on_the_phone(phone, [])
    phone.click(".cmb-card")                       # the community contest's own detail
    phone.wait_for_selector(".cmb-banner .cmb-badge", timeout=10_000)
    _settle(phone)
    ph = phone.evaluate("""() => {
        const cs = getComputedStyle(document.documentElement);
        const probe = (name) => { const v = cs.getPropertyValue(name).trim();
            if (!v) return null;
            const el = document.createElement('span'); el.style.color = v;
            document.body.appendChild(el);
            const c = getComputedStyle(el).color; el.remove(); return c; };
        return {community: getComputedStyle(
                    document.querySelector('.cmb-banner .cmb-badge.community')).color,
                lav: probe('--lavender'), gold: probe('--gold'), mauve: probe('--mauve')};
    }""")
    phone.click(".cmb-back")
    phone.wait_for_selector(".cmb-hero .cmb-badge.official", timeout=10_000)
    _settle(phone)
    ph["official"] = phone.evaluate("""() => {
        const cs = getComputedStyle(
            document.querySelector('.cmb-hero .cmb-badge.official'));
        return {face: cs.backgroundImage, ink: cs.color, bg: cs.backgroundColor};
    }""")

    desk = logged_in_page(**DESKTOP)
    _json_route(desk, "**/api/contests", _MOBILE_BOARD)
    _json_route(desk, "**/api/contest/mine",
                {"contests": [], "total_entries": 0, "sync_running": False})
    _json_route(desk, "**/api/contest/*/artworks", {"entries": [], "total_count": 104})
    _json_route(desk, "**/api/contest/sync", {"started": False, "skipped": "recent"})
    desk.goto("/", wait_until="domcontentloaded")
    _freeze_motion(desk)
    desk.wait_for_selector(".mgx-navspine", timeout=10_000)
    desk.click('.mgx-navspine button.mgx-nav:has-text("Contests")')
    desk.wait_for_selector(".mgct-h.official", timeout=10_000)
    _settle(desk)
    dk = desk.evaluate("""() => {
        const c = (s) => { const el = document.querySelector(s);
                           return el ? getComputedStyle(el).color : null; };
        return {hOfficial: c('.mgct-h.official'), hCommunity: c('.mgct-h.community')};
    }""")
    desk.click(".mgct-card")                       # the community contest's own detail
    desk.wait_for_selector(".mgct-badge.community", timeout=10_000)
    _settle(desk)
    dk["badgeCommunity"] = desk.evaluate(
        "() => getComputedStyle(document.querySelector('.mgct-badge.community')).color")
    # The OFFICIAL badge is read LAST so it is the one still on screen for the proof phase
    # below -- it is the half the ruling actually moved.
    desk.click(".mgct-back")
    desk.wait_for_selector(".mgct-official", timeout=10_000)
    desk.click(".mgct-official")                   # the featured official contest
    desk.wait_for_selector(".mgct-badge.official", timeout=10_000)
    _settle(desk)
    dk["badgeOfficial"] = desk.evaluate("""() => {
        const cs = getComputedStyle(document.querySelector('.mgct-badge.official'));
        return {face: cs.backgroundImage, ink: cs.color, bg: cs.backgroundColor};
    }""")

    assert None not in (ph["lav"], ph["gold"], ph["mauve"]), (
        "a token this test compares against no longer resolves: {!r}".format(ph))
    # The phone half of the law. OFFICIAL is metal, so its gold is the gradient's dominant
    # stop rather than its text colour; COMMUNITY is a plain lavender word.
    assert "gradient" in ph["official"]["face"] and ph["gold"] in ph["official"]["face"], (
        "the phone's OFFICIAL badge face is {!r} -- the law is gold metal, a gradient whose "
        "dominant stop is --gold ({})".format(ph["official"]["face"], ph["gold"]))
    assert ph["community"] == ph["lav"], (
        "the phone's COMMUNITY badge is {} -- the law is lavender ({})".format(
            ph["community"], ph["lav"]))
    # The desktop half, and the two words wherever desktop writes them.
    assert dk["hOfficial"] == ph["gold"], (
        "the desktop board's 'Official' header is {} -- the law is gold ({}), which is "
        "what the phone's official badge is made of".format(dk["hOfficial"], ph["gold"]))
    assert dk["hCommunity"] == ph["lav"], (
        "the desktop board's 'Community' header is {} -- the law is lavender ({}), which is "
        "what the phone paints".format(dk["hCommunity"], ph["lav"]))
    # ZERO DRIFT, asserted between the two REAL renders rather than between two stylesheets:
    # the same face, the same ink, on a 1280pt window and a 390pt one.
    assert dk["badgeOfficial"]["face"] == ph["official"]["face"], (
        "the OFFICIAL badge wears a different face on each surface --\n  desktop {!r}\n  "
        "phone   {!r}".format(dk["badgeOfficial"]["face"], ph["official"]["face"]))
    assert dk["badgeOfficial"]["ink"] == ph["official"]["ink"], (
        "the OFFICIAL badge's ink differs: desktop {}, phone {}".format(
            dk["badgeOfficial"]["ink"], ph["official"]["ink"]))
    assert ph["lav"] not in dk["badgeOfficial"]["face"] and (
        dk["badgeOfficial"]["bg"] != ph["lav"]), (
        "the desktop OFFICIAL badge is filled lavender ({}) -- that was the state between "
        "the two 2026-09-05 rulings and is the exact revert this pins: {!r}".format(
            ph["lav"], dk["badgeOfficial"]))
    assert dk["badgeCommunity"] == ph["lav"], (
        "the desktop COMMUNITY badge is {} -- the law is lavender ({})".format(
            dk["badgeCommunity"], ph["lav"]))
    assert ph["mauve"] not in (dk["hCommunity"], dk["badgeCommunity"]), (
        "the desktop community word fell back onto mauve: {!r}".format(dk))
    assert dk["badgeCommunity"] != ph["gold"], (
        "the desktop COMMUNITY badge is gold -- gold belongs to OFFICIAL since the ruling")

    # PROVE IT. The OFFICIAL badge exactly as it read between the two 2026-09-05 rulings --
    # a FLAT lavender fill with pale ink -- applied as an in-page override (never a
    # committed revert) to the badge on screen right now. Every official assertion above
    # has to flip: no gradient, no gold, and the fill back on lavender.
    desk.add_style_tag(content=(
        ".mgct-badge.official { background: var(--lavender) !important;"
        " color: #14102a !important; }"))
    _settle(desk)
    reverted = desk.evaluate("""() => {
        const cs = getComputedStyle(document.querySelector('.mgct-badge.official'));
        return {face: cs.backgroundImage, ink: cs.color, bg: cs.backgroundColor};
    }""")
    assert reverted["bg"] == ph["lav"] and "gradient" not in reverted["face"], (
        "the pre-ruling rule no longer changes what the OFFICIAL badge paints ({!r} vs "
        "lavender {}) -- this guard is reading something other than that badge's face"
        .format(reverted, ph["lav"]))
    assert ph["gold"] not in reverted["face"], (
        "the reverted OFFICIAL badge still carries gold ({}) in its face {!r} -- the gold "
        "this test reads is coming from somewhere the ruling does not govern".format(
            ph["gold"], reverted["face"]))


# ---------------------------------------------------------------------------
# THE LIBRARY STANDS STILL (2026-09-05)
# ---------------------------------------------------------------------------
# Count the app's OWN calls, in the page, by wrapping window.fetch before any bundle runs.
# api.js is the one request module (its own header: "nothing else under gallery/src calls
# fetch" bar three named exemptions), so this sees every /api/ call the shell makes. Read
# via page.evaluate rather than performance.getEntriesByType: a 100-card page pushes well
# past the resource-timing buffer's default 250 entries, and dropped entries would make a
# "no request was made" assertion pass for the wrong reason.
#
# The same wrapper also owns the HOLD, which is how the race below is made observable. A
# route handler cannot do this job: Playwright's sync API dispatches route handlers on the
# calling thread, so a handler that slept would also block the very page.evaluate that has to
# fire the completion event MID-flight. Held in the page instead -- the first request whose
# URL contains `__mgHold.pattern` is parked on a promise until the test releases it, and the
# real fetch then runs untouched. One request only (the pattern is cleared as it matches), so
# whatever the app does next is unimpeded and countable.
_COUNT_FETCH_JS = """
window.__mgCalls = { library: 0, account: 0 };
window.__mgHold = { pattern: null, started: 0, release: null };
const _f = window.fetch;
window.fetch = function (...args) {
  const u = String((args[0] && args[0].url) || args[0] || "");
  if (u.indexOf("/api/next/library") >= 0) window.__mgCalls.library++;
  else if (u.indexOf("/api/account") >= 0) window.__mgCalls.account++;
  const h = window.__mgHold;
  if (h.pattern && u.indexOf(h.pattern) >= 0) {
    h.pattern = null;
    h.started++;
    return new Promise((go) => { h.release = go; }).then(() => _f.apply(window, args));
  }
  return _f.apply(this, args);
};
"""

# The identity of what is on screen: every card's own thumbnail, in render order. Grid.jsx
# hangs no media_id on the card element, and this is the value that would change if the
# grid restacked -- which is the whole subject.
_TILES_JS = ("() => Array.from(document.querySelectorAll('.mgg-card img.mgg-art'))"
             ".map((el) => el.getAttribute('src'))")


@pytest.fixture()
def paged_library_server(tmp_path_factory, monkeypatch):
    """An already-onboarded install with enough rows to actually PAGE -- its own server.

    The module's shared `render_server` holds six rows, which is one page at every per-page
    the UI offers (50/100/200 -- FiltersPanel.jsx's PER_CYCLE, GalleryMobile's
    PER_PAGE_OPTS), and per-page is not addressable in the URL either (gen/urlState.js reads
    page/image/series and nothing else). "Page 2" cannot be reached over there at all. So
    this seeds 120 rows against a server of its own rather than reshaping the fixture the
    other eighteen tests measure against -- the same call
    `test_setup_wizard_onboards_a_genuinely_fresh_install` makes for the opposite state.
    """
    import datetime as _dt
    import logging
    from types import SimpleNamespace

    from werkzeug.serving import make_server

    wz_log = logging.getLogger("werkzeug")
    wz_level = wz_log.level
    wz_log.setLevel(logging.ERROR)

    root = tmp_path_factory.mktemp("render-harness-paged")
    config_path = root / "config.json"
    monkeypatch.setenv("MOONGLADE_DISABLE_WATCH", "1")
    monkeypatch.setattr(core, "_config_path", lambda: config_path)
    monkeypatch.setattr(core, "_cfg", {})
    # 120 rows at the default 100 per page = exactly two pages, so page 2 is a real place
    # with real cards on it (20 of them) rather than an empty edge case.
    save_catalog(root / "catalog.db", [
        {f: "" for f in CATALOG_FIELDS} | {
            "media_id": str(1000 + i), "filename": "paged_%03d.png" % i,
            "prompt_preview": "paged row %d" % i,
            "created_at": "2025-02-01T%02d:%02d:00" % (i // 60, i % 60)}
        for i in range(120)
    ])
    # A REAL bitmap for the NEWEST row (media_id 1119, the first card on page 1 under the
    # default newest-first sort), for the same reason render_server writes harness_0.png:
    # /api/similar refuses before it ever reaches the CLIP sidecar unless find_image_file
    # resolves an actual file ("image file not found", 200). The ◈ test below needs the
    # answering half of that route, not its refusal.
    from PIL import Image
    Image.new("RGB", (900, 600), (120, 90, 180)).save(root / "paged_119.png")
    core.add_or_update_web_user(_USERNAME, _PASSWORD)
    # Already onboarded, exactly as render_server is: a key, so app_page() serves the real
    # gallery instead of the Setup Wizard...
    cfg = json.loads(config_path.read_text()) if config_path.exists() else {}
    cfg["PIXAI_API_KEY"] = "sk-render-harness-fake"
    config_path.write_text(json.dumps(cfg))
    # ...and every earned achievement pre-marked seen, so no .ach-m2 celebration is up while
    # the grid is being measured. window.Ach.check() runs on mg-gen-done (App.jsx, and now
    # AppMobile.jsx too), which is precisely the event this test fires.
    _telem = load_telemetry(root)
    _metrics = achievement_metrics(root / "catalog.db")
    _metrics.update(telemetry_metrics(root))
    _ach = compute_achievements(_metrics, sets=_telem.get("sets", {}))
    _today = _dt.date.today().isoformat()
    _earned = [a["id"] for a in _ach["achievements"] if a["earned"]]
    save_ach_state(root, {"seen": _earned, "earned_at": {i: _today for i in _earned}})

    server = make_server("127.0.0.1", 0, create_app(root), threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True,
                              name="render-harness-paged-server")
    thread.start()
    try:
        yield SimpleNamespace(base_url="http://127.0.0.1:%d" % server.server_port,
                              config_path=config_path, root=root)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        wz_log.setLevel(wz_level)


def test_a_finished_generation_never_moves_the_page_the_owner_is_reading(
        paged_library_server, render_browser, monkeypatch):
    """THE POLICY (owner, 2026-09-05): nothing moves the owner's view of the library except
    his own hands. A generation finishing announces itself; it never restacks the grid.

    App.jsx's completion handler used to be `const refresh = () => { load(1, true); ... }`
    fired by mg-gen-done and mg-result -- i.e. by EVERY edit / enhance / fix / scene /
    generate / upscale (gen/submitTask.js dispatches mg-gen-done for all six) and by the
    video drawer. Read page 7 of your own library, have a job you queued ten minutes ago
    land, and the grid you were reading was replaced by page 1 under your eyes.

    Both halves are measured here on one real page with one instrument, and they are each
    other's proof: on page 2 the dispatch must produce NO library request and no visible
    change at all, and on page 1 the SAME dispatch must produce one. A "no request" that
    could never have fired would pass the first half and fail the second.

    The event is delivered by hand (`window.dispatchEvent(new CustomEvent("mg-gen-done"))`)
    rather than by running a real generation, which would need a real PixAI account and
    real credits -- this harness has neither. Everything downstream of the dispatch is the
    real shipped shell against the real Flask app.
    """
    monkeypatch.setattr(core, "_config_path", lambda: paged_library_server.config_path)
    assert core._config_path() == paged_library_server.config_path

    ctx = render_browser.new_context(
        viewport={"width": DESKTOP["width"], "height": DESKTOP["height"]},
        device_scale_factor=1, base_url=paged_library_server.base_url)
    ctx.set_default_timeout(10_000)
    ctx.add_init_script(_COUNT_FETCH_JS)
    try:
        page = ctx.new_page()
        _login(page)

        # --- ON PAGE 2, where the owner put himself -----------------------------------
        _visit(page, "/?page=2")
        page.wait_for_selector(".mgg-card")
        page.wait_for_selector(".pagebar .pg-num.current")
        _dismiss_any_achievement_toast(page)
        _settle(page)

        assert page.locator(".pagebar .pg-num.current").inner_text().strip() == "2", (
            "the harness never reached page 2, so nothing below is measuring the subject")
        tiles_before = page.evaluate(_TILES_JS)
        assert tiles_before, "page 2 rendered no cards"
        before = page.evaluate("() => ({ ...window.__mgCalls })")
        scroll_before = page.evaluate("() => window.scrollY")

        page.evaluate("() => window.dispatchEvent(new CustomEvent('mg-gen-done'))")
        # The credits chip is refreshed unconditionally, on every page -- so a fresh
        # /api/account call is the proof the handler really ran, which is what stops the
        # "no library request" assertion below from passing vacuously. /api/account is
        # fetched exactly twice in this app (App.jsx's mount effect and this handler);
        # nothing polls it.
        page.wait_for_function(
            "(n) => window.__mgCalls.account > n", arg=before["account"])
        _settle(page)

        after = page.evaluate("() => ({ ...window.__mgCalls })")
        assert after["library"] == before["library"], (
            "a finished generation re-loaded the library from page 2 ({} -> {} calls) -- "
            "the grid the owner was reading was thrown away".format(
                before["library"], after["library"]))
        assert "page=2" in page.url, (
            "the address left page 2 on a completion: {}".format(page.url))
        assert page.locator(".pagebar .pg-num.current").inner_text().strip() == "2", (
            "the grid moved off page 2 on a completion")
        assert page.evaluate(_TILES_JS) == tiles_before, (
            "the visible tiles changed under the reader on a completion")
        assert page.evaluate("() => window.scrollY") == scroll_before

        # --- AND ON PAGE 1, the default perch, where a refresh moves nothing -----------
        # A user's own hand on the pager: this one IS allowed to move everything.
        page.click('.pagebar .pg-nav:has-text("Prev")')
        page.wait_for_function(
            "() => { const el = document.querySelector('.pagebar .pg-num.current');"
            " return el && el.textContent.trim() === '1'; }")
        _settle(page)
        assert "page=" not in page.url, (
            "page 1 is the address's default and omits the param (gen/urlState.js): {}"
            .format(page.url))
        one_before = page.evaluate("() => ({ ...window.__mgCalls })")

        page.evaluate("() => window.dispatchEvent(new CustomEvent('mg-gen-done'))")
        # Same instrument, opposite expectation: here the refresh IS the wanted behaviour
        # (same page, same address, the new picture simply arrives at the top), so the
        # library call must appear.
        page.wait_for_function(
            "(n) => window.__mgCalls.library > n", arg=one_before["library"])
        _settle(page)
        assert page.locator(".pagebar .pg-num.current").inner_text().strip() == "1"
        assert "page=" not in page.url
    finally:
        ctx.close()


def test_a_completion_leaves_the_similar_view_alone_even_at_page_1(
        paged_library_server, render_browser, monkeypatch):
    """The perch is not the whole rule: at page 1, ◈ Similar still refuses.

    The first pass guarded only the page number, so at page 1 -- the default perch, where a
    refresh was reasoned to move nothing -- a completion reloaded the library underneath an
    open ◈ Similar view. The grid is not even mounted there (SimilarResults takes its place)
    and the whole contract of the token is that the library beneath it is UNTOUCHED, so ✕
    puts back exactly what was there without re-running anything. Reloading it under the
    token breaks that promise invisibly: nothing on screen moves, and then the ✕ hands back
    a different library. The phone refused under its own Similar from the start
    (AppMobile.jsx's genSimilarRef); this is the desktop catching up.

    Both halves again, one instrument: with the token up the SAME dispatch must produce no
    library request at all, and with it dismissed -- same page, same everything else -- it
    must produce one. Only the CLIP maths is stubbed (see _fake_similar_module); the route,
    the door, the token and the results are the real shipped ones.
    """
    import sys
    monkeypatch.setattr(core, "_config_path", lambda: paged_library_server.config_path)
    # Neighbours that really exist in this catalog, so api_similar's own get_row lookups
    # resolve and real result tiles render.
    monkeypatch.setitem(sys.modules, "moonglade_similar",
                        _fake_similar_module([("1118", 0.93), ("1117", 0.87)]))

    ctx = render_browser.new_context(
        viewport={"width": DESKTOP["width"], "height": DESKTOP["height"]},
        device_scale_factor=1, base_url=paged_library_server.base_url)
    ctx.set_default_timeout(10_000)
    ctx.add_init_script(_COUNT_FETCH_JS)
    try:
        page = ctx.new_page()
        _login(page)
        _visit(page, "/")
        page.wait_for_selector(".mgg-card")
        _dismiss_any_achievement_toast(page)
        _settle(page)
        assert "page=" not in page.url, "the harness did not start on the default perch"

        # The ◈ door on the newest card -- the one row with a real bitmap on disk, so the
        # route answers with neighbours instead of "image file not found".
        page.locator(".mgg-card").first.locator(".mgg-door").click()
        page.wait_for_selector(".simres")
        page.wait_for_selector(".simres-grid .simres-card")
        assert page.locator(".mgg-card").count() == 0, (
            "the library grid is still mounted under the ◈ view -- this test is not in the "
            "state it claims to be measuring")
        assert page.locator(".mgl-simtok").count() == 1, "no ◈ token in the library bar"
        _settle(page)

        cards_before = page.evaluate(
            "() => Array.from(document.querySelectorAll('.simres-card img'))"
            ".map((el) => el.getAttribute('src'))")
        assert len(cards_before) == 3, (
            "expected the source tile plus two lookalikes, got {}".format(cards_before))
        token_before = page.locator(".mgl-simcount").inner_text().strip()
        assert "match" in token_before
        before = page.evaluate("() => ({ ...window.__mgCalls })")

        page.evaluate("() => window.dispatchEvent(new CustomEvent('mg-gen-done'))")
        # Same proof-of-life as the page-2 half above: the credits chip is refreshed on
        # every completion whatever the shell is showing, so a fresh /api/account call is
        # what stops the "no library request" assertion from passing vacuously.
        page.wait_for_function("(n) => window.__mgCalls.account > n", arg=before["account"])
        _settle(page)

        after = page.evaluate("() => ({ ...window.__mgCalls })")
        assert after["library"] == before["library"], (
            "a finished generation re-loaded the library underneath the ◈ token ({} -> {} "
            "calls) -- the ✕ no longer restores what was there".format(
                before["library"], after["library"]))
        assert page.locator(".mgl-simtok").count() == 1, "the ◈ token went away on a completion"
        assert page.locator(".mgl-simcount").inner_text().strip() == token_before
        assert page.evaluate(
            "() => Array.from(document.querySelectorAll('.simres-card img'))"
            ".map((el) => el.getAttribute('src'))") == cards_before, (
            "the lookalikes changed under the reader on a completion")
        assert page.locator(".mgg-card").count() == 0, (
            "the library grid came back over the ◈ results on a completion")

        # --- and the other half: dismiss the token, and the SAME dispatch does refresh ----
        _dismiss_any_achievement_toast(page)
        page.locator(".mgl-simtok-x").click()
        page.wait_for_selector(".mgg-card")
        _settle(page)
        cleared = page.evaluate("() => ({ ...window.__mgCalls })")
        assert cleared["library"] == before["library"], (
            "dismissing the ◈ token re-fetched the library -- it is supposed to restore "
            "the page that was never touched")

        page.evaluate("() => window.dispatchEvent(new CustomEvent('mg-gen-done'))")
        page.wait_for_function("(n) => window.__mgCalls.library > n", arg=cleared["library"])
        _settle(page)
        assert page.locator(".pagebar .pg-num.current").inner_text().strip() == "1"
    finally:
        ctx.close()


def test_a_completion_never_out_races_the_owners_own_page_change(
        paged_library_server, render_browser, monkeypatch):
    """The page the owner ASKS for is the page he gets, whenever the completion lands.

    The window this measures: goToPage writes ?page=2 and calls load(2, true), but the
    shell's own `page` only becomes 2 when the SERVER answers. A completion landing in
    between read the page he was LEAVING, decided it was at the page-1 perch, and fired its
    own load(1, true) -- whose newer reqSeq (useLibrary.js) then discarded the page-2
    response the owner was waiting on, and whose settled page dragged the address back to
    the front of the library. The rule held; the race beat it.

    Made observable by holding the page-2 request itself in the page (see _COUNT_FETCH_JS's
    __mgHold), which is exactly the mid-flight moment, and firing the completion while it
    hangs there. Everything else is the real shipped shell against the real Flask app: the
    real pager button, the real request, the real address.
    """
    monkeypatch.setattr(core, "_config_path", lambda: paged_library_server.config_path)

    ctx = render_browser.new_context(
        viewport={"width": DESKTOP["width"], "height": DESKTOP["height"]},
        device_scale_factor=1, base_url=paged_library_server.base_url)
    ctx.set_default_timeout(10_000)
    ctx.add_init_script(_COUNT_FETCH_JS)
    try:
        page = ctx.new_page()
        _login(page)

        # What page 2 actually looks like, read once from a plain visit, so "his response
        # rendered" is an assertion about real cards and not about a page number alone.
        _visit(page, "/?page=2")
        page.wait_for_selector(".mgg-card")
        page.wait_for_selector(".pagebar .pg-num.current")
        _dismiss_any_achievement_toast(page)
        _settle(page)
        page_two_tiles = page.evaluate(_TILES_JS)
        assert page_two_tiles, "page 2 rendered no cards"

        # Back to the perch, by a fresh load (which re-arms the counters and the hold).
        _visit(page, "/")
        page.wait_for_selector(".mgg-card")
        page.wait_for_selector(".pagebar .pg-num.current")
        _dismiss_any_achievement_toast(page)
        _settle(page)
        page_one_tiles = page.evaluate(_TILES_JS)
        assert page_one_tiles != page_two_tiles, (
            "pages 1 and 2 render identical tiles -- nothing below could tell them apart")
        assert page.locator(".pagebar .pg-num.current").inner_text().strip() == "1"

        # Park the page-2 request the moment it is made. `page=2&` is unambiguous in the
        # query api.js builds (`?page=2&page_size=100`) -- per_page is 100, not 2.
        page.evaluate("() => { window.__mgHold.pattern = 'page=2&'; }")
        before = page.evaluate("() => ({ ...window.__mgCalls })")

        # The owner's own hand on the pager -- and then, mid-flight, the completion.
        page.click('.pagebar .pg-nav:has-text("Next")')
        page.wait_for_function("() => window.__mgHold.started > 0")
        assert "page=2" in page.url, (
            "goToPage's pushState is what makes this the owner's navigation; without it "
            "there is no intent for a completion to out-race: {}".format(page.url))
        page.evaluate("() => window.dispatchEvent(new CustomEvent('mg-gen-done'))")
        page.wait_for_function("(n) => window.__mgCalls.account > n", arg=before["account"])
        _settle(page)

        held = page.evaluate("() => ({ ...window.__mgCalls })")
        assert held["library"] == before["library"] + 1, (
            "the completion fired a library load of its own while the owner's page-2 "
            "request was still in the air ({} -> {} calls, only the held one is his) -- "
            "that load wins the reqSeq race and his answer is thrown away".format(
                before["library"], held["library"]))

        # Let his request land.
        page.evaluate("() => window.__mgHold.release()")
        try:
            page.wait_for_function(
                "() => { const el = document.querySelector('.pagebar .pg-num.current');"
                " return el && el.textContent.trim() === '2'; }")
        except _PlaywrightTimeout:
            raise AssertionError(
                "the owner asked for page 2 and the grid is on page {} -- a completion "
                "landing mid-flight took the navigation away from him".format(
                    page.locator(".pagebar .pg-num.current").inner_text().strip()))
        _settle(page)

        assert "page=2" in page.url, (
            "the owner is on page 2 but the address was dragged back: {}".format(page.url))
        assert page.evaluate(_TILES_JS) == page_two_tiles, (
            "page 2's own cards are not what rendered -- his response was discarded and "
            "something else answered for it")
        after = page.evaluate("() => ({ ...window.__mgCalls })")
        assert after["library"] == before["library"] + 1, (
            "a second library load arrived after the owner's own ({} -> {} calls)".format(
                before["library"], after["library"]))
    finally:
        ctx.close()


# The phone's own two reads, for the test below. The grid is a two-COLUMN masonry
# (GalleryGridMobile.jsx's .glm-col / .glm-col-off), so DOM order is not visual order --
# it is still deterministic for the same page, which is all "are these page 2's cards?"
# needs. And the page number lives in prose ("Page 2 of 2 · 120 matches",
# GalleryMobile.jsx's .glm-pager-info) because the phone has no numbered pagebar and no
# ?page= to read it off instead.
_PHONE_TILES_JS = ("() => Array.from(document.querySelectorAll('.glm-grid .glm-tile-img'))"
                   ".map((el) => el.getAttribute('src'))")
_PHONE_PAGE_JS = ("() => { const el = document.querySelector('.glm-pager-info');"
                  " if (!el) return 0;"
                  " const m = /Page\\s+(\\d+)\\s+of/.exec(el.textContent);"
                  " return m ? Number(m[1]) : 0; }")


def _phone_on_page(page, n):
    """Wait until the phone's pager says page `n` -- which it only does once the load has
    landed, because GalleryMobile renders the pager under `!loading`."""
    page.wait_for_function(
        "(n) => { const el = document.querySelector('.glm-pager-info');"
        " if (!el) return false;"
        " const m = /Page\\s+(\\d+)\\s+of/.exec(el.textContent);"
        " return !!m && Number(m[1]) === n; }", arg=n)


def test_a_completion_never_out_races_the_owners_own_page_change_on_the_phone(
        paged_library_server, render_browser, monkeypatch):
    """The same race, the same rule, at 390px -- the phone's own hand on its own pager.

    The desktop's pass closed this on App.jsx (the test above). The phone carried the
    identical shape for the identical reason and was NOT covered by it: GalleryMobile's
    pager calls `load(page + 1, true)` straight through, and AppMobile's completion guard
    read `genPageRef` -- a mirror of `lib.page`, which only becomes 2 when the SERVER
    answers. A completion landing in that window read the page he was LEAVING, found 1,
    passed the perch guard and fired its own load(1, true), whose newer reqSeq
    (useLibrary.js) discarded the page-2 answer he was waiting on. On the phone there is no
    ?page= for that to drag back -- the loaded page IS the whole of where you are -- so the
    only symptom is the one that matters: the tap simply does not happen.

    Same instrument as the desktop's: the page-2 request is HELD in the page
    (_COUNT_FETCH_JS's __mgHold), which is exactly the mid-flight moment, and the
    completion is fired while it hangs there. Everything else is the real shipped mobile
    shell against the real Flask app -- the real pager button, the real request.

    Page 2 is reached by the pager rather than by an address, because this shell keeps no
    page in the URL at all; that absence is the reason the intent ref has to carry it.
    """
    monkeypatch.setattr(core, "_config_path", lambda: paged_library_server.config_path)

    ctx = render_browser.new_context(
        viewport={"width": PHONE["width"], "height": PHONE["height"]},
        device_scale_factor=1, base_url=paged_library_server.base_url)
    ctx.set_default_timeout(10_000)
    ctx.add_init_script(_COUNT_FETCH_JS)
    try:
        page = ctx.new_page()
        _login(page)
        _visit(page, "/")
        page.wait_for_selector(".glm-grid .glm-tile")
        page.wait_for_selector(".glm-pager")
        _dismiss_any_achievement_toast(page)
        _settle(page)
        assert page.evaluate(_PHONE_PAGE_JS) == 1, "the phone did not open at page 1"

        # What page 2 actually looks like, read once by the only route this shell offers,
        # so "his response rendered" is an assertion about real cards, not a page number.
        page.click('.glm-pager button:has-text("Next")')
        _phone_on_page(page, 2)
        _settle(page)
        page_two_tiles = page.evaluate(_PHONE_TILES_JS)
        assert page_two_tiles, "page 2 rendered no tiles"

        # Back to the perch, by the pager's own Prev.
        page.click('.glm-pager button:has-text("Prev")')
        _phone_on_page(page, 1)
        _settle(page)
        page_one_tiles = page.evaluate(_PHONE_TILES_JS)
        assert page_one_tiles != page_two_tiles, (
            "pages 1 and 2 render identical tiles -- nothing below could tell them apart")

        # Park the page-2 request the moment it is made. `page=2&` is unambiguous in the
        # query api.js builds (`?page=2&page_size=100`) -- per_page is 100, not 2.
        page.evaluate("() => { window.__mgHold.pattern = 'page=2&'; }")
        before = page.evaluate("() => ({ ...window.__mgCalls })")

        # The owner's own hand on the pager -- and then, mid-flight, the completion.
        page.click('.glm-pager button:has-text("Next")')
        page.wait_for_function("() => window.__mgHold.started > 0")
        page.evaluate("() => window.dispatchEvent(new CustomEvent('mg-gen-done'))")
        # The credits half of the handler is unconditional, so this is how we know the
        # completion really ran and did not simply lose a race with the assertion.
        page.wait_for_function("(n) => window.__mgCalls.account > n", arg=before["account"])
        _settle(page)

        held = page.evaluate("() => ({ ...window.__mgCalls })")
        assert held["library"] == before["library"] + 1, (
            "the completion fired a library load of its own while the owner's page-2 "
            "request was still in the air ({} -> {} calls, only the held one is his) -- "
            "that load wins the reqSeq race and his answer is thrown away".format(
                before["library"], held["library"]))

        # Let his request land.
        page.evaluate("() => window.__mgHold.release()")
        try:
            _phone_on_page(page, 2)
        except _PlaywrightTimeout:
            raise AssertionError(
                "the owner tapped for page 2 and the grid is on page {} -- a completion "
                "landing mid-flight took the navigation away from him".format(
                    page.evaluate(_PHONE_PAGE_JS)))
        _settle(page)

        assert page.evaluate(_PHONE_TILES_JS) == page_two_tiles, (
            "page 2's own cards are not what rendered -- his response was discarded and "
            "something else answered for it")
        after = page.evaluate("() => ({ ...window.__mgCalls })")
        assert after["library"] == before["library"] + 1, (
            "a second library load arrived after the owner's own ({} -> {} calls)".format(
                before["library"], after["library"]))
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# The Loom as its own arena -- the crossing, measured (2026-09-06)
# ---------------------------------------------------------------------------
# SCOPE_2026-09-06_loom-arena.md's own test note: "Steps 2-3 want a new case here -- cross
# to the Loom and back, and land where you started." These are the assertions no source
# guard can make, because every one is about what a REAL browser does across a REAL
# whole-page navigation between two separately-built bundles: a snapshot written by the
# library's pagehide and read back in the Loom's own document, an address the Loom rewrites
# only after its store has answered, and a phone rule evaluated by an actual matchMedia.
#
# Deliberately catalog-independent. The library's address is SET on the page rather than
# arrived at by paging, so these measure the crossing itself and not how many pictures the
# throwaway catalog happens to hold -- assertions that move with fixture data are exactly
# what this file's own docstring warns about.

_LOOM_READY = ".lv-top, .lm-root"   # whichever skin of the Loom mounted


def _loom_board_param(page):
    return page.evaluate("() => new URLSearchParams(location.search).get('board')")


def test_the_loom_gives_a_storyboard_its_own_address(logged_in_page):
    """A bare /loom grows a ?board= for whatever it opened, and that address opens it again.

    The first half is what makes a storyboard copyable at all; the second is what makes it a
    place rather than a decoration -- and together they are what stops the address and the
    server-side pointer from becoming two different ideas of "which board is open".
    """
    page = logged_in_page(**DESKTOP)
    _visit(page, "/loom")
    page.wait_for_selector(_LOOM_READY)
    page.wait_for_function("() => new URLSearchParams(location.search).get('board')")

    board = _loom_board_param(page)
    assert board, "the Loom opened but put no storyboard in the address"

    # Go somewhere else entirely, then follow the address back: the SAME board must open.
    _visit(page, "/")
    _visit(page, "/loom?board=" + board)
    page.wait_for_selector(_LOOM_READY)
    _settle(page)
    assert _loom_board_param(page) == board, (
        "following a storyboard's own address did not open that storyboard -- the address "
        "is now {!r}".format(_loom_board_param(page)))


def test_an_unknown_storyboard_address_opens_a_real_board_and_says_so(logged_in_page):
    """No blank page and no invented screen: the board you would have got anyway, the app's
    ordinary corner note, and an address that corrects itself to what actually opened."""
    page = logged_in_page(**DESKTOP)
    _visit(page, "/loom?board=nosuchboard")
    page.wait_for_selector(_LOOM_READY)
    page.wait_for_function(
        "() => { const b = new URLSearchParams(location.search).get('board');"
        " return b && b !== 'nosuchboard'; }")
    _settle(page)

    assert _loom_board_param(page) != "nosuchboard"
    toast = page.locator(".mg-toast", has_text="No storyboard at that address")
    assert toast.count() >= 1, "an unknown board id opened silently -- no corner note"


def test_the_return_trip_lands_where_the_library_was(logged_in_page):
    """Cross to the Loom and back, and land where you started -- the whole of owner call 2.

    Measured across the real navigation both ways, because that is the only place it can
    break: the library writes the snapshot as its page goes away, and a different document
    entirely reads it back.
    """
    page = logged_in_page(**DESKTOP)
    _visit(page, "/")
    page.wait_for_selector(".mgx-actrow")
    # 2026-09-07: wait for the library's FIRST load to land before faking the address.
    # `.mgx-actrow` is painted from boot-time data (Banner.jsx), so it is up long before
    # the grid's own request resolves -- and App's page-mirror effect (App.jsx:465-468,
    # "whenever the loaded page settles somewhere the URL doesn't say") fires the moment
    # `loading` goes false and `total` arrives, calling setUrl({page: 1}); buildUrl
    # deletes `page` for n <= 1 and leaves `image` alone (urlState.js:47-54), so a
    # replaceState made mid-flight came back as `/?image=demo-mid-42` and the test failed
    # on its own setup. Flaked twice in the 3.10 wave on exactly that; a real visit to
    # /?page=3 cannot hit it, because readPage() seeds React's `page` from the real
    # address at mount and the mirror writes back the same 3.
    page.wait_for_selector(".mgg-card")
    page.wait_for_load_state("networkidle")
    _settle(page)

    # The library, somewhere other than its front door.
    page.evaluate("() => history.replaceState(null, '', '/?page=3&image=demo-mid-42')")
    _settle(page)
    assert page.url.endswith("/?page=3&image=demo-mid-42"), (
        "the app rewrote the address to {!r} before the crossing even started -- the "
        "library's own first load was still in flight".format(page.url))

    # Out through the hero's own Loom button -- a plain anchor that runs no JS of its own,
    # which is exactly why the snapshot rides pagehide rather than a click handler.
    page.click("a.mgx-metal-loom")
    page.wait_for_selector(_LOOM_READY)

    back = page.get_attribute("a.lv-close[href]", "href")
    assert back == "/?page=3&image=demo-mid-42", (
        "the back link points at {!r} -- the crossing forgot the page and the open "
        "picture".format(back))

    page.click("a.lv-close[href]")
    page.wait_for_selector(".mgx-actrow")
    assert "page=3" in page.url and "image=demo-mid-42" in page.url, (
        "came back to {!r} instead of the address the library was at".format(page.url))


def test_a_loom_opened_cold_still_offers_the_library_front_door(logged_in_page):
    """A tab that was never in the library has nothing to remember, and must say nothing
    untrue about it -- the link falls back to the front door, exactly what it always was."""
    page = logged_in_page(**DESKTOP)
    _visit(page, "/loom")
    page.wait_for_selector(_LOOM_READY)
    assert page.get_attribute("a.lv-close[href]", "href") == "/"


def test_a_phone_opens_the_phone_layout_and_a_tablet_does_not(logged_in_page):
    """Owner call 5, and the constraint attached to it: "I want to be mindful of the tablet
    still being able to use desktop."

    Both halves in one test on purpose -- the promise IS the pair, and a threshold that
    drifted would break them together while either alone still passed.
    """
    phone = logged_in_page(width=390, height=844)
    _visit(phone, "/loom")
    phone.wait_for_selector(_LOOM_READY)
    assert phone.locator(".lm-root").count() == 1, (
        "a 390px phone got the wide desktop board")

    tablet = logged_in_page(width=768, height=1024)
    _visit(tablet, "/loom")
    tablet.wait_for_selector(_LOOM_READY)
    assert tablet.locator(".lm-root").count() == 0, (
        "a 768px tablet was pulled onto the phone layout -- the auto-open is keyed on a "
        "threshold of its own instead of useIsMobile's phone rule")
    assert tablet.locator(".lv-top").count() == 1


def test_the_manual_switch_still_overrules_the_phone_auto_open(logged_in_page):
    """Never a one-way trip: a phone that asks for the wide board gets it, and keeps it."""
    phone = logged_in_page(width=390, height=844)
    _visit(phone, "/loom")
    phone.wait_for_selector(".lm-root")
    phone.click(".lm-chip:has-text('Desktop')")
    phone.wait_for_selector(".lv-top")
    assert phone.locator(".lm-root").count() == 0

    # ...and it is remembered, so the auto-open does not simply undo it on the next visit.
    _visit(phone, "/loom")
    phone.wait_for_selector(_LOOM_READY)
    _settle(phone)
    assert phone.locator(".lv-top").count() == 1, (
        "the phone auto-open overruled a choice the owner actually made")


# ---------------------------------------------------------------------------
# THE PHONE'S FOUNDATIONS (2026-09-06) -- the mobile audit's four confirmed defects
# ---------------------------------------------------------------------------
# Each of the four below was independently re-reproduced on a driven 390x844 chromium
# before it was fixed, and each fails on the pre-fix source. The source-shape guards for
# the wiring these rest on are loom/test/phone-back-layers.test.js.

# What the phone's own scroller is doing, in one read. .glm-body is the tab's scroller
# (gallery-mobile.css gives it overflow-y:auto) and the ONE element every finding here
# turns on -- the pager's landing, the sheet's containment and the per-tab memory are all
# statements about this number.
_BODY_SCROLL_JS = """() => {
    const el = document.querySelector('.glm-body');
    if (!el) return null;
    return { top: el.scrollTop, range: el.scrollHeight - el.clientHeight };
}"""


def _body_top(page):
    return page.evaluate(_BODY_SCROLL_JS)["top"]


def _wheel_over(page, x, y, times=8, dy=600):
    """A real wheel burst, well past the end of anything under the pointer."""
    page.mouse.move(x, y)
    for _ in range(times):
        page.mouse.wheel(0, dy)
    _settle(page)


# HOW DEEP THE BACK LEDGER IS, read off the browser rather than off the app. Each entry the
# layer manager pushes carries its own depth in the history state ({mgLayer: n} --
# gallery/src/hooks/useLayerHistory.js), so the current entry's number IS the number of open
# layers, and the base entry the shell opened on carries none at all.
#   Not `history.length`: that is a high-water mark. It never shrinks on a back, and a
# pushState after one overwrites the forward entry rather than adding to the count -- so a
# second layer opened after any earlier back reads as no growth at all. Measured, not
# assumed: this test's own two-deep stack read 5 against a 4 that had already been reached.
_LAYER_DEPTH_JS = ("() => (window.history.state && window.history.state.mgLayer) || 0")


def _layer_depth(page):
    return page.evaluate(_LAYER_DEPTH_JS)


def test_the_back_gesture_closes_one_layer_at_a_time_and_never_leaves_the_app(
        logged_in_page):
    """THE 2026-09-06 AUDIT'S FIRST FINDING, and an app-wide one.

    The phone half of Similar was the only surface on this shell that guarded the Back
    gesture (AppMobile pushed one same-address entry when it opened). Every OTHER layer it
    stacks over the library -- the full-screen viewer, the picture screen, all six Menu
    destinations, the Folio, the contact sheet, the contest entry screen, and the three
    local drill-ins -- consumed zero history depth, so the phone's own "go up one" walked
    past all of them and straight out of Moonglade.

    Three shapes, in the order a person meets them: one layer, a SWAP of two mutually
    exclusive ones (the viewer and the picture screen null each other, mirroring App.jsx's
    own pairing -- so "Details" trades one layer for another and the depth never moves),
    and a genuine two-deep stack (the Folio opened over a pushed Menu screen: the hero is
    still reachable above .glm-body while a screen is up). The ledger's own depth is read
    at each step, because the defect was never visible in the DOM -- the layers always
    rendered, they simply held no entry to consume.
    """
    page = logged_in_page(**PHONE)
    _visit(page, "/")
    page.wait_for_selector(".glm-grid .glm-tile")
    _dismiss_any_achievement_toast(page)
    _settle(page)
    home = page.url
    assert _layer_depth(page) == 0, "the bare gallery is holding a layer entry"

    # --- one layer: the full-screen viewer -----------------------------------------
    page.locator(_DOOR_TILE).click()
    page.wait_for_selector(".lbm-root")
    _settle(page)
    assert _layer_depth(page) == 1, (
        "the viewer took no history entry -- Back will walk past it and out of the app")
    page.go_back()
    page.wait_for_selector(".lbm-root", state="detached")
    page.wait_for_selector(".glm-grid .glm-tile")
    assert page.url == home, "Back left the app instead of closing the viewer"
    _settle(page)
    assert _layer_depth(page) == 0, "the viewer's entry outlived the viewer"

    # --- a SWAP: viewer -> picture screen is one layer the whole way through --------
    page.locator(_DOOR_TILE).click()
    page.wait_for_selector(".lbm-root")
    page.click(".lbm-actsrow >> text=Details")
    page.wait_for_selector(".idm-root")
    _settle(page)
    assert _layer_depth(page) == 1, (
        "the viewer and the picture screen are mutually exclusive, so trading one for the "
        "other must not stack a second entry -- the depth is {}".format(_layer_depth(page)))
    page.go_back()
    page.wait_for_selector(".idm-root", state="detached")
    page.wait_for_selector(".glm-grid .glm-tile")
    assert page.url == home, "Back left the app instead of closing the picture screen"
    assert page.locator(".lbm-root").count() == 0, (
        "closing the picture screen re-opened the viewer -- the two are mutually "
        "exclusive, so the trade was one layer and Back lands on the library")

    # --- a genuine two-deep stack: the Folio over a pushed Menu screen --------------
    page.click('button[title="More"]')
    page.click('.glm-menu-item:has-text("My Art")')
    page.wait_for_selector(".glm-screen")
    _settle(page)
    assert _layer_depth(page) == 1, "the pushed Menu screen took no history entry"
    page.click('button[title="Folio of Honors"]')
    page.wait_for_selector(".fm-root")
    _settle(page)
    assert _layer_depth(page) == 2, (
        "two stacked layers did not take two entries -- one Back would close both, or "
        "neither")

    page.go_back()
    page.wait_for_selector(".fm-root", state="detached")
    assert page.locator(".glm-screen").count() == 1, (
        "Back closed the Folio AND the screen underneath it -- one press, one layer")
    assert page.url == home
    _settle(page)
    assert _layer_depth(page) == 1, "the ledger did not come down with the Folio"

    page.go_back()
    page.wait_for_selector(".glm-screen", state="detached")
    page.wait_for_selector(".glm-grid .glm-tile")
    assert page.url == home, "the second Back left the app instead of closing the screen"
    _settle(page)
    assert _layer_depth(page) == 0

    # --- and the bare gallery is exactly as it was: no trap ------------------------
    # With nothing open the manager holds no entries, so a Back here does what it always
    # did -- leaves. Proven by landing back on the login page the harness came in through,
    # which is the entry immediately before this one.
    page.go_back()
    page.wait_for_load_state("domcontentloaded")
    assert "/login" in page.url, (
        "Back on the bare gallery did not leave the app -- the manager is holding an "
        "entry for a layer that is not open, which is a trap: {}".format(page.url))


_BANNER_EXPAND_JS = """
() => new Promise((resolve) => {
  /* Sample the expand while it is RUNNING. Everything this measures is mid-transition, so
     nothing here may wait for it to settle: the banner's box, the mark's box, and whether
     a point inside the mark that lies BELOW the banner's own bottom edge still belongs to
     the mark. elementFromPoint is the honest test of a clip -- a clipped element keeps its
     layout rect, so a rect alone can never see one. */
  const bnr = document.querySelector(".mgx-bnr");
  const mark = document.querySelector(".mgx-mark");
  const band = document.querySelector(".mgx-bottom");
  const frames = [];
  const t0 = performance.now();
  const sample = (again) => {
    const b = bnr.getBoundingClientRect();
    const m = mark.getBoundingClientRect();
    const r = band.getBoundingClientRect();
    const x = Math.round(m.left + m.width / 2);
    const y = Math.round(Math.min(m.bottom - 2, b.bottom + 2));
    const hit = document.elementFromPoint(x, y);
    frames.push({
      t: Math.round(performance.now() - t0),
      expanding: bnr.classList.contains("expanding"),
      overflow: getComputedStyle(bnr).overflowY,
      bandOverflow: getComputedStyle(band).overflowY,
      bandMaxH: getComputedStyle(band).maxHeight,
      bnrH: Math.round(b.height * 10) / 10,
      markH: Math.round(m.height * 10) / 10,
      markBelow: Math.round((m.bottom - b.bottom) * 10) / 10,
      // is the point inside the mark, but below the banner's edge, still the mark's?
      belowEdge: m.bottom > b.bottom + 2,
      hitsMark: !!(hit && (hit === mark || mark.contains(hit))),
      bandPaints: r.height > 0 && r.bottom > b.bottom + 2,
    });
    if (!again) return;
    if (performance.now() - t0 < 620) requestAnimationFrame(() => sample(true));
    else resolve(frames);
  };
  sample(false);            // t=0, before a frame has been yielded: the pin at its tightest
  requestAnimationFrame(() => sample(true));
})
"""


def test_the_banner_expand_never_crops_the_mark_and_never_spills_the_band(logged_in_page):
    """RED TEAM #14 and #24, in a real engine and mid-animation.

    The expand's height pin (`.mgx-bnr.expanding { height: 62px }`) carried an
    `overflow: hidden` on the BANNER, and the mark runs its own independent .5s size
    transition -- 56px to 96px -- inside that still-pinned 62px box. So the pin cropped the
    mark, its halo and its moondust field for the whole animation, contradicting in every
    frame the invariant `.mgx-bnr { overflow: visible }` exists for and that
    loom/test/mark-anim-containment.test.js states in as many words. That suite measures
    static hero-size overhang budgets only; a transitional state is invisible to it, and no
    real-browser test measured this geometry at all.

    The clip is scoped to the returning band now, so this holds both ends at once: the mark
    may spill, and the band still may not.

    Motion is deliberately NOT frozen here -- the animation IS the subject.
    """
    page = logged_in_page(**DESKTOP)
    page.goto("/", wait_until="domcontentloaded")     # no _freeze_motion: see the docstring
    page.wait_for_selector(".mgx-bnr")
    _dismiss_any_achievement_toast(page)
    _settle(page)

    collapse = page.locator('.mgx-sqbtn[title="Collapse the banner to its slim bar"]')
    collapse.click()
    page.wait_for_selector(".mgx-bnr.slim")
    page.wait_for_timeout(700)                        # let the collapse finish entirely

    page.evaluate("() => { window.__mgFrames = null; }")
    page.locator('.mgx-sqbtn[title="Expand the banner to its hero height"]').click()
    frames = page.evaluate(_BANNER_EXPAND_JS)

    pinned = [f for f in frames if f["expanding"]]
    assert len(pinned) >= 5, (
        "the expand's pin was never observed -- nothing below measures anything: "
        "{}".format(frames[:6]))

    # 1. THE BANNER IS NOT A CLIP while it expands. This is the invariant the mark's own
    #    halo and moondust rely on at every other moment too.
    assert all(f["overflow"] == "visible" for f in pinned), (
        "the banner clipped itself during the expand: "
        "{}".format(sorted({f["overflow"] for f in pinned})))

    # 2. THE CLIP MOVED, it did not simply go. The band is what the pin has to hold, and
    #    the guard is only narrowed if the band is still clipped in the same frames.
    assert all(f["bandOverflow"] == "hidden" and f["bandMaxH"] == "0px" for f in pinned), (
        "the pin's clip was dropped rather than scoped to the band: {}".format(
            sorted({(f["bandOverflow"], f["bandMaxH"]) for f in pinned})))

    # 3. WHERE THE MARK DOES outgrow the pinned box, it still belongs to the mark --
    #    elementFromPoint below the banner's own edge is what a clip would take away.
    #    Not required to happen: min-height leaves 62px within a few milliseconds, so the
    #    overhang is a handful of pixels for a handful of frames and a slow runner can
    #    step over it. Assertion 1 is the deterministic half; this is the direct evidence
    #    when the timing offers it.
    cropped = [f for f in pinned if f["belowEdge"] and not f["hitsMark"]]
    assert not cropped, (
        "the mark was cropped by the banner mid-expand at {}".format(
            [(f["t"], f["markBelow"]) for f in cropped]))

    # 4. AND THE BAND STILL DOES NOT SPILL. That is what the pin's clip was for, and
    #    narrowing it must not give that up.
    spilling = [f for f in pinned if f["bandPaints"]]
    assert not spilling, (
        "the hero band painted below the pinned banner at {}".format(
            [f["t"] for f in spilling]))

    # 5. and the expand itself is still ONE motion: it starts at the slim row, not at
    #    content height, which is the fix this pin exists for.
    assert pinned[0]["bnrH"] <= 80, (
        "the expand jumped to content height in its first frame again: "
        "{}".format([(f["t"], f["bnrH"]) for f in pinned[:4]]))
    assert max(f["bnrH"] for f in frames) > 200, "the banner never reached its hero height"


_DONE_JOB = {"jobs": [{
    "job_id": "77", "type": "generate", "label": "Generated", "status": "done",
    "media_ids": ["100"], "ts": 0, "started_at": 0,
}]}


def test_the_phone_activity_thumbnail_really_opens_the_picture(logged_in_page):
    """RED TEAM #24. The phone's ONE route from "your image is done" to the image.

    Under the library-stands-still policy nothing restacks the grid when a generation
    lands, so the Activity row's thumbnail is the whole of the way there. ActivityRow
    cancels its own anchor for a plain tap and dispatches `mg-open-details` instead -- and
    until this branch the only listener lived in App.jsx, so on the phone the tap was
    swallowed whole: the link cancelled, nothing opened in its place.

    That fix shipped with a regex over the JSX and its own docstring saying the behaviour
    "belongs in tests/test_render_harness.py if it is ever measured live". This is that.
    """
    page = logged_in_page(**PHONE)
    page.route("**/api/jobs", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(_DONE_JOB)))
    _visit(page, "/")
    page.wait_for_selector(".glm-grid .glm-tile")
    _dismiss_any_achievement_toast(page)
    _settle(page)

    page.click('button[title="Activity"]')
    page.wait_for_selector(".glm-sheet .at-row")
    thumb = page.locator(".glm-sheet .at-row .at-thumb")
    assert thumb.count() == 1, (
        "a finished job with a media id must offer its thumbnail -- there is no other way "
        "to the picture from here")
    before = page.url

    thumb.click()
    page.wait_for_selector(".idm-root")
    assert page.url == before, (
        "the tap followed the desktop shell's /?image= address and reloaded the app "
        "instead of opening the phone's own picture record: {}".format(page.url))
    # ...and the sheet it was tapped in got out of the way, rather than being what the
    # owner lands back on when the picture closes
    assert page.locator('.glm-sheet:has(.at-row)').count() == 0


_MASCOT_PROBE_JS = """
() => {
  /* The restart mascot's own markup, mounted against the SHIPPED stylesheet rather than by
     restarting the harness's server. What is being read is a CSS fact -- whether the rule
     the owner's ruling removed is still gone from the bundle the browser actually loaded --
     and the modal is unreachable here without a real restart. */
  const host = document.createElement("div");
  host.className = "mgcp-pwr-card";
  host.style.cssText = "position:fixed;left:-9999px;top:0;";
  host.innerHTML = '<div class="mgcp-pwr-mascotwrap">'
    + '<div class="mgcp-pwr-halo busy"></div>'
    + '<div class="mgcp-pwr-mascot"></div></div>';
  document.body.appendChild(host);
  const mascot = host.querySelector(".mgcp-pwr-mascot");
  const halo = host.querySelector(".mgcp-pwr-halo");
  const out = {
    mascotAnim: getComputedStyle(mascot).animationName,
    haloAnim: getComputedStyle(halo).animationName,
    // the greyed-out state the ruling explicitly kept
    offFilter: (() => {
      mascot.classList.add("off");
      const f = getComputedStyle(mascot).filter;
      mascot.classList.remove("off");
      return f;
    })(),
    // ...and a class nothing renders any more must not be quietly resurrected in CSS
    spinAnim: (() => {
      mascot.classList.add("spin");
      const a = getComputedStyle(mascot).animationName;
      mascot.classList.remove("spin");
      return a;
    })(),
  };
  host.remove();
  return out;
}
"""


def test_the_restart_mascot_holds_still_and_the_halo_keeps_pulsing(logged_in_page):
    """RED TEAM #24, and the owner's own words: "I don't want the mascot to spin anymore.
    it just looks wrong. I like the pulse, we can keep that."

    Both halves of that ruling, read off the stylesheet the browser really loaded: the
    mascot has no animation of its own, the halo's pulse is untouched, and the `spin` class
    the removal took out of the JSX does not quietly still exist in CSS waiting for someone
    to put the class back. Nothing measured this in a browser before -- and cpSpin itself
    is still defined and still used by the job console's spinner, so a stray selector here
    would animate again with no source change anyone would notice.

    Mounted directly rather than by opening the modal: reaching it needs a real restart of
    the harness's own server, and what is under test is a CSS fact, not the route to it.
    """
    page = logged_in_page(**DESKTOP)
    page.goto("/", wait_until="domcontentloaded")     # no motion freeze: it would zero these
    page.wait_for_selector(".mgx-bnr")
    _settle(page)
    seen = page.evaluate(_MASCOT_PROBE_JS)

    assert seen["mascotAnim"] == "none", (
        "the restart mascot is animating again: {}".format(seen["mascotAnim"]))
    assert seen["spinAnim"] == "none", (
        "a .spin rule survived in the stylesheet: {}".format(seen["spinAnim"]))
    # The pulse the owner kept, now with the ember the 2026-09-07 restart-card verdict
    # layered beside it on the same beat. Both names, in that order, on the one element.
    assert [a.strip() for a in seen["haloAnim"].split(",")] == ["cpPulse", "cpEmber"], (
        "the halo's pulse+ember pair is not what ships: {}".format(seen["haloAnim"]))
    assert "grayscale" in seen["offFilter"], (
        "the greyed stopped-server state went with it: {}".format(seen["offFilter"]))


def test_two_fast_backs_inside_a_layers_exit_animation_do_not_leave_the_app(
        logged_in_page):
    """RED TEAM #13. The ledger and the visible layer disagreed for 200-220ms every time.

    Five of the ten registered layers -- the Menu screens, Branding, the composer's Advanced
    screen, Duplicates and the Folio -- keep their `open` flag true for another fifth of a
    second after being told to close, because that is how long their exit takes to play.
    onPop dropped its entry the instant the FIRST Back arrived, so for that whole window
    `depth` read 0 while a full-screen layer still covered the display -- and a second real
    Back inside it found nothing of ours to consume and went straight to the browser. The
    app closed with the screen still on screen: the exact defect the manager exists to fix.

    Two presses, thirty milliseconds apart, driven from inside the page so they really land
    inside the window -- a wait_for_selector(state="detached") between them would step over
    the whole bug. The layer's exit is a JS timer, not a CSS transition, so the harness's
    motion freeze does not shorten it.
    """
    page = logged_in_page(**PHONE)
    _visit(page, "/")
    page.wait_for_selector(".glm-grid .glm-tile")
    _dismiss_any_achievement_toast(page)
    _settle(page)
    home = page.url

    page.click('button[title="More"]')
    page.click('.glm-menu-item:has-text("My Art")')
    page.wait_for_selector(".glm-screen")
    _settle(page)
    assert _layer_depth(page) == 1

    page.evaluate("""() => new Promise((r) => {
        window.history.back();
        setTimeout(() => { window.history.back(); setTimeout(r, 80); }, 30);
    })""")
    assert page.url == home, (
        "a second Back inside the exit animation left the app while the screen was still "
        "on it: {}".format(page.url))

    page.wait_for_selector(".glm-screen", state="detached")
    page.wait_for_selector(".glm-grid .glm-tile")
    _settle(page)
    assert _layer_depth(page) == 0, "the ledger did not come down with the screen"
    # ...and the gallery underneath is not a trap: with nothing open, Back leaves as always
    page.go_back()
    page.wait_for_load_state("domcontentloaded")
    assert "/login" in page.url, (
        "the swallowed press was never handed back -- the manager is holding an entry for "
        "a layer that is not open: {}".format(page.url))


def test_the_pager_lands_each_page_at_its_top(
        paged_library_server, render_browser, monkeypatch):
    """THE 2026-09-06 AUDIT'S SECOND FINDING: tap Next from halfway down page 1 and page 2
    opened already halfway down -- the search field, the media pills and the whole first row
    of pictures scrolled away above a page not one word of which had been read.

    GalleryMobile's Prev/Next just calls load(page +/- 1, true); nothing ever touched
    .glm-body's offset, so the scroller kept whatever the READER had left it at while the
    tiles under it were replaced wholesale. The fix rides the owner's own load (AppMobile's
    userLoad, the intent path the library-stands-still policy already runs everything
    through), so a background refresh is untouched -- and it fires only when the page really
    changed.

    Needs a library that pages, so it takes `paged_library_server`'s 120 rows rather than
    the module fixture's six.
    """
    monkeypatch.setattr(core, "_config_path", lambda: paged_library_server.config_path)

    ctx = render_browser.new_context(
        viewport={"width": PHONE["width"], "height": PHONE["height"]},
        device_scale_factor=1, base_url=paged_library_server.base_url)
    ctx.set_default_timeout(10_000)
    try:
        page = ctx.new_page()
        _login(page)
        _visit(page, "/")
        page.wait_for_selector(".glm-grid .glm-tile")
        page.wait_for_selector(".glm-pager")
        _dismiss_any_achievement_toast(page)
        _settle(page)
        assert page.evaluate(_PHONE_PAGE_JS) == 1, "the phone did not open at page 1"

        start = page.evaluate(_BODY_SCROLL_JS)
        assert start["range"] > 400, (
            "the phone's library has only {:.0f}px of scroll range at 390x844 -- there is "
            "no 'halfway down' for this test to leave the reader at".format(start["range"]))
        page.evaluate("() => { document.querySelector('.glm-body').scrollTop = 400; }")
        _settle(page)
        assert _body_top(page) == 400, (
            "the library scroller would not take a test offset -- nothing below measures "
            "anything")
        # ...and from there the pill row really is scrolled away, which is the complaint.
        away = page.evaluate("""() => {
            const body = document.querySelector('.glm-body').getBoundingClientRect();
            const pills = document.querySelector('.glm-bar2').getBoundingClientRect();
            return pills.bottom <= body.top;
        }""")
        assert away, (
            "the media pills are still on screen at 400px down, so 'the pill row scrolled "
            "away' is not the state this test starts from")

        page.click('.glm-pager button:has-text("Next")')
        _phone_on_page(page, 2)
        _settle(page)

        landed = _body_top(page)
        assert landed == 0, (
            "page 2 opened {:.0f}px down -- the reader lands mid-page on a page they have "
            "not read".format(landed))
        geo = page.evaluate("""() => {
            const body = document.querySelector('.glm-body').getBoundingClientRect();
            const bar = document.querySelector('.glm-bar').getBoundingClientRect();
            const pills = document.querySelector('.glm-bar2').getBoundingClientRect();
            return {bodyTop: body.top, barTop: bar.top, pillsTop: pills.top,
                    pillsBottom: pills.bottom};
        }""")
        assert geo["barTop"] >= geo["bodyTop"] - 1 and geo["pillsBottom"] > geo["bodyTop"], (
            "the search bar and the media pills are not on screen on the page that just "
            "landed: {!r}".format(geo))

        # Prev, the other direction, is the same hand and lands the same way.
        page.evaluate("() => { document.querySelector('.glm-body').scrollTop = 300; }")
        _settle(page)
        page.click('.glm-pager button:has-text("Prev")')
        _phone_on_page(page, 1)
        _settle(page)
        assert _body_top(page) == 0, (
            "Prev kept the offset -- the landing is the owner's page change, either way "
            "he asked for it")
    finally:
        ctx.close()


def test_an_open_sheet_holds_the_library_still_behind_it(
        paged_library_server, render_browser, monkeypatch):
    """THE 2026-09-06 AUDIT'S THIRD FINDING, and the one the measurement does not agree
    with -- recorded here rather than quietly dressed up, because a guard that claims a bite
    it does not have is worse than no guard.

    THE REPORT: a wheel or flick over an open Sort / Advanced Search / Actions sheet
    scrolled the library GRID behind the dim, because the 2026-09-05 pass latched the pushed
    SCREENS (`.glm-body:has(.glm-screen)` + `overscroll-behavior: contain`) and left the
    sheets one layer shallower.

    WHAT THIS BROWSER DOES, probed before the fix was written and again after: the library
    does not move. Wheel burst and real CDP touch drag, over the scrim and over the slab, on
    a 120-row library with 9057px of range, with the new rules in place and with them
    overridden back off -- 200px in, 200px out, every time. The reason is in the same probe:
    every sheet surface is position:fixed with no containing-block ancestor
    (`sheet.offsetParent === null`), so it scroll-chains to the document and never to
    .glm-body, DOM descendant or not. So the leak is not reproducible from here, and this
    test does not pretend otherwise -- there is no revert phase, because nothing flips.

    WHAT IT DOES PIN, all of it real and all of it new: the sheet does not move the reader
    on its way up, the tab's scroller is genuinely latched while the sheet is up (the
    `:has(.glm-sheet)` rule -- without it that read is "auto"), the sheet contains its own
    overscroll, and the latch comes off with the sheet leaving the library exactly where it
    was. gallery-mobile.css's own block states the same thing in full.

    Measured on the paged fixture because the module's six rows do not fill a 390x844 phone,
    and a containment test on a surface with nothing to scroll proves nothing.
    """
    monkeypatch.setattr(core, "_config_path", lambda: paged_library_server.config_path)

    ctx = render_browser.new_context(
        viewport={"width": PHONE["width"], "height": PHONE["height"]},
        device_scale_factor=1, base_url=paged_library_server.base_url)
    ctx.set_default_timeout(10_000)
    try:
        page = ctx.new_page()
        _login(page)
        _visit(page, "/")
        page.wait_for_selector(".glm-grid .glm-tile")
        _dismiss_any_achievement_toast(page)
        _settle(page)

        assert page.evaluate(_BODY_SCROLL_JS)["range"] > 400, (
            "the library does not scroll at 390x844 here -- nothing could leak")
        page.evaluate("() => { document.querySelector('.glm-body').scrollTop = 200; }")
        _settle(page)
        held = _body_top(page)
        assert held == 200

        # Advanced Search rather than Sort, and for a reason worth stating: the Sort pill
        # lives in .glm-bar2, which has scrolled away by 200px, so driving it would make
        # Playwright scroll it into view and move the very number this test is watching.
        # "Advanced" sits in .glm-bar, which is position:sticky and always on screen. All
        # three sheets are the same shared .glm-sheet chrome (MobileSheet.jsx) mounted in
        # the same place (inside .glm-tab-gallery), so the containment measured on one is
        # the containment all three have.
        page.click(".glm-search-adv")
        page.wait_for_selector(".glm-sheet")
        _settle(page)
        # The sheet must not have moved the reader on its way up, either.
        assert _body_top(page) == held, "opening the sheet moved the library by itself"

        # A burst over the dim, where the grid is showing through...
        _wheel_over(page, 195, 200)
        assert _body_top(page) == held, (
            "a flick over the scrim scrolled the library behind it")
        # ...and one over the sheet's own body, which is where a thumb actually lands.
        sheet_y = page.evaluate(
            "() => { const r = document.querySelector('.glm-sheet').getBoundingClientRect();"
            " return Math.round(r.top + Math.min(60, r.height / 2)); }")
        _wheel_over(page, 195, sheet_y)
        assert _body_top(page) == held, (
            "a flick over the sheet chained out into the library behind it")
        assert page.locator(".glm-sheet").count() == 1, "the sheet closed under the wheel"

        # THE LOCK IS REAL, and this is what CAN be proven from here: while the sheet is up
        # the tab's scroller is latched, and the moment it closes the library is both
        # scrollable again AND exactly where it was left. Without the `:has(.glm-sheet)`
        # rule the first read below is "auto" and the assertion fails.
        assert page.evaluate(
            "() => getComputedStyle(document.querySelector('.glm-body')).overflowY"
        ) == "hidden", "the tab's scroller is not latched while a sheet is up"
        assert page.evaluate(
            "() => getComputedStyle(document.querySelector('.glm-sheet')).overscrollBehaviorY"
        ) == "contain", "the sheet does not contain its own overscroll"
        page.keyboard.press("Escape")            # no-op; the scrim is the real dismiss
        page.click(".glm-scrim", position={"x": 195, "y": 60}, force=True)
        page.wait_for_selector(".glm-sheet", state="detached")
        _settle(page)
        assert page.evaluate(
            "() => getComputedStyle(document.querySelector('.glm-body')).overflowY"
        ) == "auto", "the latch outlived the sheet -- the library can no longer be scrolled"
        assert _body_top(page) == held, (
            "the library did not come back to where the reader left it: {:.0f} vs {:.0f}"
            .format(_body_top(page), held))
    finally:
        ctx.close()


def test_each_tab_keeps_its_own_scroll(
        paged_library_server, render_browser, monkeypatch):
    """THE 2026-09-06 AUDIT'S FOURTH FINDING: all three tabs share ONE scroller (.glm-body),
    so a deep read of the library opened the Create tab a thousand pixels down its own
    composer, and coming back put you somewhere neither tab had chosen.

    The shell keeps a per-tab memory now: leaving a tab records its offset, entering one
    puts it back. Driven as a person drives it -- the real bottom nav, a real round trip --
    on the paged fixture, because the module's six rows do not give the Gallery tab enough
    range for "deep" to mean anything (with 120 it has 8682px of it).

    The BLEED half is measured on the pair the report named, Gallery -> Create. The
    KEEPS-ITS-OWN half is measured on Gallery <-> Control instead, and that is a fixture
    fact rather than a scope call: measured at 390x844, the composer runs 30px past the
    frame and Control 984, so Create has no offset of its own to hold and Control does. The
    memory itself is per-tab and keyed on nothing but the tab name.
    """
    monkeypatch.setattr(core, "_config_path", lambda: paged_library_server.config_path)

    ctx = render_browser.new_context(
        viewport={"width": PHONE["width"], "height": PHONE["height"]},
        device_scale_factor=1, base_url=paged_library_server.base_url)
    ctx.set_default_timeout(10_000)
    try:
        page = ctx.new_page()
        _login(page)
        _visit(page, "/")
        page.wait_for_selector(".glm-grid .glm-tile")
        _dismiss_any_achievement_toast(page)
        _settle(page)

        assert page.evaluate(_BODY_SCROLL_JS)["range"] > 500, (
            "the library does not run deep enough at 390x844 for this to mean anything")
        page.evaluate("() => { document.querySelector('.glm-body').scrollTop = 500; }")
        _settle(page)
        assert _body_top(page) == 500

        # Over to Create -- the exact bleed the report named: it opens at ITS top, not
        # 500px down someone else's tab.
        page.click('.glm-navitem:has-text("Create")')
        page.wait_for_selector(".cm-pad", timeout=10_000)
        _settle(page)
        assert _body_top(page) == 0, (
            "the Create tab opened {:.0f}px down -- the Gallery's depth bled into it"
            .format(_body_top(page)))

        # Control is the tab deep enough to hold a place of its own (see the docstring).
        page.click('.glm-navitem:has-text("Control")')
        page.wait_for_selector(".ctm-statcard", timeout=10_000)
        _settle(page)
        arrived = page.evaluate(_BODY_SCROLL_JS)
        assert arrived["top"] == 0, (
            "the Control tab opened {:.0f}px down".format(arrived["top"]))
        assert arrived["range"] > 300, (
            "the Control panel has only {:.0f}px of range here, so 'Control keeps its own "
            "place' cannot be measured".format(arrived["range"]))
        page.evaluate("() => { document.querySelector('.glm-body').scrollTop = 300; }")
        _settle(page)
        assert _body_top(page) == 300

        # Back to the library: deep stays deep.
        page.click('.glm-navitem:has-text("Gallery")')
        page.wait_for_selector(".glm-grid .glm-tile")
        _settle(page)
        assert _body_top(page) == 500, (
            "the library came back at {:.0f} instead of the 500 it was left at"
            .format(_body_top(page)))

        # ...and Control kept its own, separately.
        page.click('.glm-navitem:has-text("Control")')
        page.wait_for_selector(".ctm-statcard")
        _settle(page)
        assert _body_top(page) == 300, (
            "Control came back at {:.0f} instead of the 300 it was left at"
            .format(_body_top(page)))

        # A PUSHED SCREEN PARKS THIS SCROLLER, and the memory stands down while it does --
        # MobileScreen.jsx has held .glm-body at 0 since the 2026-09-05 contest fix, so a
        # tab switch under an open screen must not record that 0 as the tab's place.
        page.click('.glm-navitem:has-text("Gallery")')
        page.wait_for_selector(".glm-grid .glm-tile")
        _settle(page)
        page.click('button[title="More"]')
        page.click('.glm-menu-item:has-text("My Art")')
        page.wait_for_selector(".glm-screen")
        _settle(page)
        assert _body_top(page) == 0, "the screen did not park the scroller"
        page.click('.glm-navitem:has-text("Create")')
        _settle(page)
        page.click('.glm-navitem:has-text("Gallery")')
        _settle(page)
        page.click(".glm-screen-back")
        page.wait_for_selector(".glm-screen", state="detached")
        _settle(page)
        assert _body_top(page) == 500, (
            "a tab round trip UNDER an open screen overwrote the library's place with the "
            "parked 0: it came back at {:.0f}".format(_body_top(page)))
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# A branding file DROPPED into a slot folder, all the way to the browser
# ---------------------------------------------------------------------------
# tests/test_branding.py already covers the sweep as a FUNCTION (adopt, delete the raw
# file, register the asset, fire the feat) against Flask's test client. Nothing covered
# the trip the owner actually takes: put a picture in the folder, reload the page, and
# see the app wearing it. That is three mechanisms in a row, and a unit test can see none
# of them -- the boot fetch that runs the sweep at all (notify/index.jsx's installNotify
# -> ach.check() -> GET /api/achievements?mark=1), the serve route that translates the
# friendly /branding/<role>/... URL back to the coded on-disk rel, and the celebration.
_UNDER_THE_HOOD = "under-the-hood"     # the hidden feat sweep_branding_drops() fires
_DROP_RGB = (200, 40, 90)              # a colour nothing else in this harness paints, so a
#                                        served pixel PROVES it came from this exact drop
_DROP_SIZE = (1200, 300)               # banner_main's own 4:1, so the flat's crop is the
#                                        whole picture and the colour check stays meaningful


def _png_of(size, rgb):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, rgb).save(buf, format="PNG")
    return buf.getvalue()


def _decode(raw):
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(raw))
    im.load()
    return im


def test_a_branding_drop_is_adopted_and_the_browser_wears_it(
        logged_in_page, render_server, tmp_path):
    """Drop a PNG into a slot folder; reload; the app is wearing it.

    Order-independent by construction, and that is worth spelling out because this test
    writes to two trees, one of which OUTLIVES it:

      * the branding tree is `tmp_path/branding` -- conftest's autouse `_isolated_branding`
        re-points branding_root() there for the duration of THIS test, so the folder the
        drop lands in (and the adopted asset, the manifest and the rendered flat that
        follow it) evaporates with the test. Asserted below rather than assumed: a test
        that drops files into a real folder must prove first that the folder is the
        throwaway one.
      * the feat's earn-state lives in the module server's out_dir, which every later test
        in this file shares. So this one snapshots the two files it disturbs -- the
        telemetry flags and the achievement state -- and restores them in a `finally`,
        whether it passes or not.

    FOUR preconditions have to be undone for the celebration to be a real earn rather
    than a re-run of an already-recognized one, and each is a fixture decision made for an
    unrelated reason:
      1. render_server pre-seeds the `branding_custom_file` flag, to unlock the Branding
         tab for the Control Panel test -- cleared here, so the sweep is what sets it;
      2. it pre-marks every earned achievement `seen`, to stop boot toasts -- this feat is
         un-seen here, so its own toast is allowed to fire;
      3. it also stamps every earned achievement into `earned_at`, and since #37 (pin-once,
         2026-08-29) anything in `earned_at` STAYS earned whatever its live metric says.
         Clearing the flag alone therefore un-earns nothing, so the feat is un-PINNED here
         too. Without that, the login landing page's own boot fetch (logged_in_page ->
         _login -> "/" -> installNotify -> ach.check) finds it earned-and-unseen, celebrates
         it and marks it seen BEFORE the drop is even written, and the post-drop reload the
         test captures reports `newly: []`. Caught 2026-09-10 by tracing every
         /api/achievements response across login and reload: two ?mark=1 fetches, the
         FIRST carrying the feat. It went unnoticed because whether the fixture pinned it
         used to depend on the machine -- see 4 -- and CI, which has no donor, skips the
         assertion. Still required now that the fixture is hermetic: donor present, the
         roster is full and every earned id (this feat included, since the fixture arms its
         flag itself) IS pinned, so the un-pin below is what makes the earn a first earn.
      4. `first_sync_complete()` withholds `newly` (and leaves `seen` alone) until a first
         library sync has finished. Its backfill keys on a non-empty `seen`/`earned_at`,
         which the fixture computes at module setup from the roster its container yields.
         That container used to be the checkout's own moonglade.dat -- module-scoped
         fixtures are set up before conftest's per-test container is pinned -- so the
         backfill depended on a file nobody in this module wrote: none there (CI) and the
         roster is empty, nothing seen or pinned and the gate reads "still syncing"; a real
         pack there (a dev box) and the roster is full, everything earned is pinned. The
         fixture now seeds its own container from the donor (2026-09-10), so the only
         remaining fork is donor-vs-no-donor, which is the fork this file gates on
         deliberately. The flag is still set here explicitly so the gate depends on neither.
         An install with a fully swept catalog, which is exactly what this harness serves,
         has that flag set; it is set here for the same reason the API key above it is.

    The achievement half is donor-gated exactly like the Branding tab in
    test_control_panel_runs_real_jobs_and_manages_a_real_account: the roster is SEALED in
    moonglade.dat, so donor-absent (public CI) there is no `under-the-hood` to earn and no
    toast to wait for. The adoption half -- the part with no coverage at all -- runs either
    way.
    """
    import moonglade_gallery as _g
    from moonglade_gallery import list_slot_assets, load_ach_state

    slot = "banner_main"
    sdir = _g._slot_dir(slot)          # asked of the app's own ROLE_CODE map, never retyped
    assert tmp_path in sdir.parents, (
        "branding_root() is {} -- not under this test's tmp_path. Refusing to write a "
        "drop into a real branding tree.".format(_g.branding_root()))
    sdir.mkdir(parents=True, exist_ok=True)

    root = render_server.root
    before_ids = {a["id"] for a in list_slot_assets(root, slot)}
    flags_before = dict(load_telemetry(root)["flags"])
    ach_before = load_ach_state(root)

    try:
        # --- put the feat back to genuinely-unearned, and open the celebration gate ---
        _g._telem_mutate(root, lambda d: d["flags"].pop("branding_custom_file", None))
        telem_flag("first_sync_done", out_dir=root)
        save_ach_state(root, dict(
            ach_before,
            seen=[i for i in (ach_before.get("seen") or []) if i != _UNDER_THE_HOOD],
            # precondition 3: `earned_at` is authoritative (pin-once), so an id left in it
            # is earned no matter what the flag above says
            earned_at={k: v for k, v in (ach_before.get("earned_at") or {}).items()
                       if k != _UNDER_THE_HOOD}))
        assert not load_telemetry(root)["flags"].get("branding_custom_file")
        assert _UNDER_THE_HOOD not in (load_ach_state(root).get("earned_at") or {}), (
            "the feat is still pinned in earned_at -- the login page would earn it first")

        page = logged_in_page(**DESKTOP)
        if _SEALED_DONOR.is_file():
            # The landing page must NOT have celebrated it already: that is the exact
            # failure precondition 3 exists to prevent, and this names it at the point it
            # happens rather than three assertions later as an empty `newly`.
            assert page.locator(".ach-m2").count() == 0, (
                "a celebration fired on the login landing page, before the drop -- the feat "
                "was already earned (pinned or flagged) when the page first booted")

        # --- the drop itself: a picture, by hand, into the slot folder ---
        drop = sdir / "my_own_banner.png"
        drop.write_bytes(_png_of(_DROP_SIZE, _DROP_RGB))
        assert drop.exists()

        # --- the reload the owner would do. The boot fetch is what runs the sweep, so
        # wait on THAT response, not on a wall-clock guess: when it lands, so has the
        # adoption -- and its body is the payload the celebration engine reads.
        with page.expect_response(
                lambda r: "/api/achievements" in r.url and r.request.method == "GET") as boot:
            _visit(page, "/")

        # 1. the raw drop is consumed, not left sitting beside the adopted copy
        assert not drop.exists(), (
            "the dropped file is still in the slot folder -- the sweep never adopted it")

        # 2. the slot now holds exactly one NEW asset, and the app really serves it
        after = [a for a in list_slot_assets(root, slot) if a["id"] not in before_ids]
        assert len(after) == 1, "expected one newly adopted asset, got {}".format(after)
        asset = after[0]
        assert asset["png"] == "/branding/%s/%s.png" % (slot, asset["id"])

        # Fetched through the BROWSER's own context (its session cookie, its base_url), so
        # this is the URL the page itself asks for -- coded-rel translation included.
        got = page.request.get(asset["png"])
        assert got.status == 200, "{} served {}".format(asset["png"], got.status)
        im = _decode(got.body())
        assert im.format == "PNG"
        assert im.size == _DROP_SIZE, (
            "the served asset is {}, not the dropped picture's own {}".format(
                im.size, _DROP_SIZE))
        assert im.convert("RGB").getpixel((600, 150)) == _DROP_RGB, (
            "the slot serves SOMETHING, but not the file that was dropped")

        # 3. ...and the flat the header actually paints was re-rendered from it, which is
        # the difference between "stored" and "worn" (add_slot_asset -> _write_banner_flat).
        flat = page.request.get("/branding/banner.png")
        assert flat.status == 200, "/branding/banner.png served {}".format(flat.status)
        flat_im = _decode(flat.body()).convert("RGB")
        assert flat_im.size == (1920, 480), "banner_main's flat is {}".format(flat_im.size)
        assert flat_im.getpixel((960, 240)) == _DROP_RGB, (
            "the header's flat did not re-render from the adopted drop")

        # 4. the sweep really fired the feat, and it really paid out ON SCREEN.
        # Donor-gated: no sealed roster, no achievement to earn and nothing to celebrate.
        assert load_telemetry(root)["flags"].get("branding_custom_file"), (
            "the adoption did not fire branding_custom_file")
        if _SEALED_DONOR.is_file():
            payload = boot.value.json()
            assert _UNDER_THE_HOOD in (payload.get("newly") or []), (
                "the boot fetch did not report the feat as newly earned: newly={!r}"
                .format(payload.get("newly")))
            page.wait_for_selector(".ach-m2")
            shown = page.locator(".ach-m2").first.inner_text()
            assert "Under the Hood" in shown, (
                "a celebration fired, but not the one the drop earns: {!r}".format(shown))
            # Leave the screen clear for whatever runs next -- see the helper's docstring.
            _dismiss_any_achievement_toast(page)
            assert page.locator(".ach-m2").count() == 0
    finally:
        # The module's shared out_dir goes back byte-for-byte, pass or fail: the flags this
        # test cleared and set, and the `seen`/`earned_at` the ?mark=1 above rewrote.
        _g._telem_mutate(root, lambda d: d.__setitem__("flags", dict(flags_before)))
        save_ach_state(root, ach_before)


# ---------------------------------------------------------------------------
# The dismiss helper vs a QUEUE of celebrations (2026-09-07, second pass)
# ---------------------------------------------------------------------------
# _dismiss_any_achievement_toast's whole reason to exist is the parade: two achievements
# earned in one pass are two moments, and the helper must leave the screen clear, not
# hand the next click to the successor overlay. Its first rewrite was written against a
# model of ach.js that ach.js does not implement -- `_play()`'s done() removes the clicked
# moment and calls `_next()` in the SAME task, so `.ach-m2` never matches zero elements
# between them -- and so it timed out on exactly the case it was meant to fix. Nothing
# pinned that, because every existing call site happens to be single-moment.
#
# The queue is driven through the REAL engine (installNotify -> ach.check() -> GET
# /api/achievements?mark=1 -> toastNew -> celebrate x2 -> _q/_next), with only the boot
# payload faked -- the achievements themselves are irrelevant to what is under test and
# a real two-at-once earn would have to mutate the module server's shared out_dir. The
# unmarked /api/achievements calls the rest of the app makes are passed straight through.
#
# Two ORDINARY tiers deliberately: `_fanfare` (legendary/feat only) seats a mascot off a
# canvas alpha sample and rains 84 confetti nodes, none of which the queue handoff cares
# about.
_QUEUED_ACH = [
    {"id": "harness-queued-one", "name": "First In The Queue", "tier": "epic",
     "desc": "the moment that gets clicked first", "points": 10, "icon": "\U0001F3C6"},
    {"id": "harness-queued-two", "name": "Second In The Queue", "tier": "rare",
     "desc": "the moment appended in the same task the first one leaves in",
     "points": 5, "icon": "\U0001F3C5"},
]

# Records every .ach-m2 the engine appends, by its name line, so the test can prove the
# SECOND moment really presented rather than inferring it from an empty screen.
_WATCH_MOMENTS_JS = """
window.__achSeen = [];
document.addEventListener('DOMContentLoaded', () => {
  new MutationObserver((recs) => {
    recs.forEach((r) => Array.prototype.forEach.call(r.addedNodes, (n) => {
      if (n.nodeType === 1 && n.classList && n.classList.contains('ach-m2')) {
        const el = n.querySelector('.n');
        window.__achSeen.push(el ? el.textContent : '');
      }
    }));
  }).observe(document.body, { childList: true });
});
"""


def test_the_dismiss_helper_clears_a_queue_of_celebrations(logged_in_page):
    """Two achievements earned at once, both dismissed through the helper, no timeout.

    This is the shape the helper's own docstring promises to handle and the shape its
    2026-09-07 first rewrite could not: ach.js swaps the successor in on the same tick the
    clicked moment leaves on, so a helper that waits for `.ach-m2` to detach waits for a
    state the engine never enters.
    """
    page = logged_in_page(**DESKTOP)
    page.add_init_script(_WATCH_MOMENTS_JS)

    payload = {"achievements": list(_QUEUED_ACH), "skins": [], "skin": "moonglade",
               "newly": [a["id"] for a in _QUEUED_ACH]}

    def _boot(route):
        # ONLY the mark-and-toast boot fetch is faked; the Folio's and the Panel's own
        # unmarked reads go to the real server untouched.
        if "mark=1" in route.request.url:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps(payload))
        else:
            route.continue_()

    _is_ach = lambda url: "/api/achievements" in url   # noqa: E731 -- unroute needs the identity
    page.route(_is_ach, _boot)
    try:
        _visit(page, "/")
        page.wait_for_selector(".ach-m2")
        assert page.locator(".ach-m2").count() == 1, (
            "the engine put {} moments on screen at once -- this test is meant to drive "
            "the QUEUE (_q/_next), not the flood parade".format(
                page.locator(".ach-m2").count()))
        assert _QUEUED_ACH[0]["name"] in page.locator(".ach-m2").first.inner_text()

        try:
            _dismiss_any_achievement_toast(page)
        except _PlaywrightTimeout as exc:
            pytest.fail(
                "the dismiss helper timed out on a two-deep celebration queue -- ach.js "
                "removes the clicked moment and appends its successor in one task, so "
                "`.ach-m2` is never absent between them: {}".format(exc))

        assert page.locator(".ach-m2").count() == 0, (
            "the helper returned with a celebration still on screen")
        seen = page.evaluate("() => window.__achSeen")
        assert seen == [a["name"] for a in _QUEUED_ACH], (
            "the queue did not present both moments in turn -- saw {!r}".format(seen))
    finally:
        page.unroute(_is_ach, _boot)


# ---------------------------------------------------------------------------
# The Bridge §1 -- the Control Panel's Mirror tile, at rest
# ---------------------------------------------------------------------------
# ROADMAP-internal.md kept one Bridge follow-on open: "a render-harness guard". The tile
# (ControlPanelOverlay.jsx's MirrorTile, control-panel.css's "The Bridge §1" block) is a
# credential gate, so the two things worth guarding are what it SAYS at rest and what it
# REFUSES to do. Its colour ladder -- emerald >7 days / peach <=7 / ruby <=0 / grey off --
# lives entirely in CSS class rules, which is exactly the shape of thing a substring test
# can confirm exists while the rendered ring paints something else.
#
# Nothing in this test may reach pixai.art. It cannot by construction: the resting state
# is `connected: false` (no mirror_session.json under the harness's own config path), and
# MirrorTile.toggle() short-circuits BEFORE any fetch when the switch is asked to arm with
# no session. That is asserted, not assumed, and a route abort backs it up.

# Read the ring's rendered stroke against the two tokens the ladder names, resolved by the
# browser from real probe elements -- comparing a computed rgb() to a raw token string
# would be the substring test this file exists to replace.
_READ_MIRROR_RING_JS = """() => {
  const probe = (tok) => {
    const d = document.createElement('div');
    d.style.color = 'var(' + tok + ')';
    document.body.appendChild(d);
    const c = getComputedStyle(d).color;
    d.remove();
    return c;
  };
  const ring = document.querySelector('.mgbr-ring');
  const fg = ring.querySelector('.mgbr-ring-fg');
  return {
    ringClass: ring.className,
    stroke: getComputedStyle(fg).stroke,
    grey: probe('--overlay0'),
    emerald: probe('--emerald'),
    dasharray: fg.getAttribute('stroke-dasharray'),
    dashoffset: fg.getAttribute('stroke-dashoffset'),
  };
}"""


def test_the_bridges_mirror_tile_rests_off_and_refuses_to_arm_itself(logged_in_page):
    """The Bridge §1's gate, rendered: grey ring, empty ring, pill off, and a toggle that
    goes nowhere.

    Four assertions, in the order the owner meets the tile:
      1. it is there and it is NOT armed -- .mgbr-tile without .armed;
      2. the JWT ring is in its OFF state, measured rather than read off a class name: the
         rendered stroke is the ladder's grey (--overlay0) and not its emerald, and the arc
         is drawn at zero length (dashoffset == the full circumference), which is what "no
         session, no days" looks like;
      3. the pill toggle exists, is off, and says so to a screen reader (aria-pressed);
      4. pressing it ARMS NOTHING. MirrorTile.toggle() refuses a want-on with no connected
         session before it fetches anything, so the tile stays off, the refusal appears in
         its own message line, and no /api/mirror write -- and no request to any host but
         this harness's own server -- ever leaves the page.

    The Connect button is deliberately never pressed: /api/mirror/connect makes the SERVER
    read this machine's real browser cookie store. Reading the tile's resting state is the
    guard the roadmap asked for; arming it is not.
    """
    from urllib.parse import urlparse

    page = logged_in_page(**DESKTOP)
    # Belt and braces under the assertion below: even a regression that tried could not
    # actually reach the site from this page.
    page.route("**/*pixai.art/**", lambda route: route.abort())
    seen = []
    page.on("request", lambda r: seen.append((r.method, r.url)))

    _visit(page, "/")
    page.wait_for_selector("header")
    _open_panel(page)
    page.wait_for_selector(".mgcp-bridge .mgbr-tile")
    # The pill is disabled until /api/mirror/status answers, so this is also the wait for
    # the tile to be driven by the SERVER's real state rather than its null-state placeholder.
    page.wait_for_selector(".mgbr-pill:not([disabled])")
    _settle(page)

    # 1. present, and off
    tile = page.locator(".mgcp-bridge .mgbr-tile")
    assert tile.count() == 1
    assert "armed" not in (tile.get_attribute("class") or ""), (
        "the Mirror tile is armed on a harness server that has no session at all")
    assert "Off · tier hidden" in page.locator(".mgbr-status").inner_text()
    assert "Not connected" in page.locator(".mgbr-session-sub").inner_text()

    # 2. the ring's OFF rung of the ladder, as rendered
    ring = page.evaluate(_READ_MIRROR_RING_JS)
    assert "off" in ring["ringClass"].split(), (
        "the ring is on the {!r} rung with no session".format(ring["ringClass"]))
    assert ring["stroke"] == ring["grey"], (
        "the OFF ring paints {} -- the ladder's grey (--overlay0) is {}".format(
            ring["stroke"], ring["grey"]))
    assert ring["stroke"] != ring["emerald"], "the OFF ring paints the ARMED colour"
    assert ring["dashoffset"] == ring["dasharray"], (
        "the OFF ring draws an arc ({} of {}) -- with no session there are no days to show"
        .format(ring["dashoffset"], ring["dasharray"]))
    assert page.locator(".mgbr-days").inner_text().strip() == "0"

    # --- phase 2: prove that ladder is LIVE css, not a rule nothing reaches. Flip the rung
    # in the page only (never a committed change) and the same stroke must move to emerald.
    page.evaluate("() => { const r = document.querySelector('.mgbr-ring');"
                  " r.classList.remove('off'); r.classList.add('healthy'); }")
    _settle(page)
    armed_ring = page.evaluate(_READ_MIRROR_RING_JS)
    assert armed_ring["stroke"] == armed_ring["emerald"], (
        "the healthy rung does not repaint the ring ({}) -- the OFF assertion above is "
        "vacuous".format(armed_ring["stroke"]))
    page.evaluate("() => { const r = document.querySelector('.mgbr-ring');"
                  " r.classList.remove('healthy'); r.classList.add('off'); }")

    # 3. the pill, off
    pill = page.locator(".mgbr-pill")
    assert pill.count() == 1
    assert "on" not in (pill.get_attribute("class") or "").split()
    assert pill.get_attribute("aria-pressed") == "false"

    # 4. pressing it arms nothing and calls nothing
    before = len(seen)
    pill.click()
    page.wait_for_selector(".mgbr-msg")
    assert "Connect a session first" in page.locator(".mgbr-msg").inner_text(), (
        "the toggle did something other than refuse: {!r}".format(
            page.locator(".mgbr-msg").inner_text()))
    _settle(page)
    assert "armed" not in (tile.get_attribute("class") or ""), "the tile armed itself"
    assert "on" not in (pill.get_attribute("class") or "").split(), "the pill flipped on"
    assert page.evaluate(_READ_MIRROR_RING_JS)["stroke"] == ring["grey"]

    after = seen[before:]
    assert not after, "pressing the toggle fired {} request(s): {}".format(len(after), after)
    # And over the WHOLE test: the tile read its status and wrote nothing, and nothing at
    # all went anywhere but this harness's own ephemeral port.
    host = urlparse(page.url).hostname
    foreign = [u for (m, u) in seen
               if urlparse(u).hostname not in (None, "", host)]
    assert not foreign, "requests left the harness server: {}".format(foreign)
    writes = [(m, u) for (m, u) in seen if "/api/mirror/" in u and m != "GET"]
    assert not writes, "a mirror WRITE left the page: {}".format(writes)
    assert any(m == "GET" and "/api/mirror/status" in u for (m, u) in seen), (
        "the tile never read /api/mirror/status -- it is rendering a placeholder, so every "
        "assertion above is about nothing")


# --- The pickers page past 24 (owner, 2026-09-07, twice: "still do not scroll past a set
# selection of models and lora in all tabs and sorts", desktop and phone). Two fixes were
# claimed from code reads before this test existed; this is the browser proof, on both shells,
# with the market faked so PixAI is never called. -----------------------------------------
def _fake_market_pages(monkeypatch, per_page=24, pages=3, overlap=0):
    """Three pages of LoRA rows the way /api/model-search hands them to the picker.

    `overlap` = how many of a page's first rows REPEAT the previous page's last rows (same
    model_id, same title), the way PixAI's ranking feeds actually page (measured live 2026-09-07:
    288 trending rows, 281 distinct). A keyword search answers with five "Hands LoRA" hits."""
    def _row(n, i):
        return {"model_id": "fake-%d-%d" % (n, i), "title": "Fake LoRA %d.%02d" % (n, i),
                "preview_url": "", "liked_count": i, "lora_base_model_type": "",
                "description": "", "official": False, "should_blur": False}

    def page(n):
        rows = [_row(n, i) for i in range(per_page)]
        if overlap and n > 1:
            rows[:overlap] = [_row(n - 1, i) for i in range(per_page - overlap, per_page)]
        return {"results": rows, "has_more": n < pages, "next_cursor": ("p%d" % (n + 1)) if n < pages else ""}

    def hits(keyword):
        rows = [{"model_id": "hit-%d" % i, "title": "Hands LoRA %d" % i, "preview_url": "",
                 "liked_count": 0, "lora_base_model_type": "", "description": keyword,
                 "official": False, "should_blur": False} for i in range(1, 6)]
        return {"results": rows, "has_more": False, "next_cursor": ""}
    calls = []

    def fake_search(session, keyword="", category="", sort="", usage="MODEL", limit=24, after=None, **kw):
        calls.append(after)
        if keyword:
            return hits(keyword)
        n = int(after[1:]) if after else 1
        return page(n)
    monkeypatch.setattr(core, "model_search_market_gql", fake_search)
    monkeypatch.setattr(core, "model_search_rest", fake_search)
    monkeypatch.setattr(core, "_make_session", lambda *a, **k: object())
    return calls


def _scroll_pane_to_bottom(page):
    """Scroll whichever element actually scrolls the open picker: the flyout's non-head pane."""
    page.evaluate("""() => {
        const fly = document.querySelector('.mfly.open');
        const panes = [...fly.querySelectorAll(':scope > div:not(.mfly-head)')].filter(d => d.style.display !== 'none');
        const pane = panes[0];
        pane.scrollTop = pane.scrollHeight;
        const grid = pane.querySelector('.mg-grid');
        if (grid) grid.scrollTop = grid.scrollHeight;
    }""")


def _cards(page):
    return page.locator(".mfly.open .mg-card").count()


def test_desktop_lora_picker_pages_past_its_first_24(logged_in_page, monkeypatch):
    calls = _fake_market_pages(monkeypatch)
    page = logged_in_page(**DESKTOP)
    _visit(page, "/")
    _settle(page)
    page.click(".mgx-gen")
    page.wait_for_selector(".mgdock")
    # the LoRA row lives in the dock's settings; expand if the + LoRA control is not on screen
    if not page.locator(".mgdock-addlora").is_visible():
        page.click(".mgdock-expand")
    page.wait_for_selector(".mgdock-addlora", state="visible")
    page.click(".mgdock-addlora")
    page.wait_for_selector(".mfly.open .mg-card")
    # >= 24, not == 24: the next page is prefetched a page early, so the list may already be past
    # its first page by the time this looks
    page.wait_for_function("() => document.querySelectorAll('.mfly.open .mg-card').length >= 24")
    _scroll_pane_to_bottom(page)
    page.wait_for_function("() => document.querySelectorAll('.mfly.open .mg-card').length >= 48", timeout=8000)
    _scroll_pane_to_bottom(page)
    page.wait_for_function("() => document.querySelectorAll('.mfly.open .mg-card').length >= 72", timeout=8000)
    assert _cards(page) == 72, "three pages of 24 must all be in the list"
    assert calls[:3] == [None, "p2", "p3"], calls


def test_desktop_lora_search_replaces_the_list_with_no_leftover_cards(logged_in_page, monkeypatch):
    """The feed repeats a model across pages; a repeated model_id is a repeated React key, and the
    card behind it can never be removed again -- it stayed at the top of every later list, above
    the real results. Owner, 2026-09-07: "its always the SAME lora exactly", "Search is still
    shit". Twenty-two such leftovers sat in his tab over the 24 "Perfect Hands" hits React held.
    The list must carry each model once, and a search must leave nothing of the old list behind."""
    _fake_market_pages(monkeypatch, overlap=2)
    page = logged_in_page(**DESKTOP)
    _visit(page, "/")
    _settle(page)
    page.click(".mgx-gen")
    page.wait_for_selector(".mgdock")
    if not page.locator(".mgdock-addlora").is_visible():
        page.click(".mgdock-expand")
    page.wait_for_selector(".mgdock-addlora", state="visible")
    page.click(".mgdock-addlora")
    page.wait_for_selector(".mfly.open .mg-card")
    page.wait_for_function("() => document.querySelectorAll('.mfly.open .mg-card').length >= 24")
    _scroll_pane_to_bottom(page)
    # page 2 repeats page 1's last two rows: 48 rows handed over, 46 distinct models
    page.wait_for_function("() => document.querySelectorAll('.mfly.open .mg-card').length >= 46", timeout=8000)
    mids = page.evaluate("() => [...document.querySelectorAll('.mfly.open .mg-card')].map(c => c.dataset.mid)")
    assert len(mids) == len(set(mids)), "a model is in the list twice: %s" % [m for m in mids if mids.count(m) > 1]
    # now a search: the whole list must be the five hits, the first card the first hit, nothing left over
    page.locator(".mfly.open .mg-q").locator("visible=true").fill("hands")
    page.wait_for_function(
        "() => [...document.querySelectorAll('.mfly.open .mg-card')].some(c => c.textContent.includes('Hands LoRA 1'))",
        timeout=8000)
    page.wait_for_timeout(400)   # let any straggling continuation land before counting
    cards = page.evaluate("() => [...document.querySelectorAll('.mfly.open .mg-card')].map(c => c.textContent.trim().slice(0, 12))")
    assert len(cards) == 5, "leftover cards from the old list are still in the grid: %s" % cards
    assert cards[0].startswith("Hands LoRA 1"), cards
    assert not any(c.startswith("Fake LoRA") for c in cards), cards


def test_phone_lora_sheet_pages_past_its_first_24_and_confirm_closes_it(logged_in_page, monkeypatch):
    calls = _fake_market_pages(monkeypatch)
    page = logged_in_page(**PHONE)
    _visit(page, "/")
    _settle(page)
    page.click("button:has-text('Create')")
    page.wait_for_selector(".cm-addlora")
    page.click(".cm-addlora")
    page.wait_for_selector(".mfly.open .mg-card")
    page.wait_for_function("() => document.querySelectorAll('.mfly.open .mg-card').length >= 24")
    _scroll_pane_to_bottom(page)
    page.wait_for_function("() => document.querySelectorAll('.mfly.open .mg-card').length >= 48", timeout=8000)
    assert calls[:2] == [None, "p2"], calls
    # the way out: the sheet head's Confirm selection, visible inside the viewport, closes the sheet
    done = page.locator(".mfly.open .mfly-done")
    assert done.count() == 1, "the phone sheet head carries the Confirm selection button"
    box = done.bounding_box()
    vw, vh = PHONE["width"], PHONE["height"]
    assert box and 0 <= box["y"] and box["y"] + box["height"] <= vh and box["x"] + box["width"] <= vw, box
    assert done.inner_text().strip() == "Confirm selection"
    # a tap on a card keeps the sheet open (multi-select) and the button still reachable
    page.locator(".mfly.open .mg-card").first.click()
    assert page.locator(".mfly.open").count() == 1
    assert done.is_visible()
    done.click()
    page.wait_for_function("() => !document.querySelector('.mfly.open')", timeout=5000)


# --- The phone's LoRA sheet, on the owner's actual phone profile (2026-09-07, his 5059
# screenshot: the sheet with no head at all -- no Models/LoRAs tabs, no Confirm selection, no
# search box -- the page's hero sitting above it and the tab bar below). The 390x844 desktop-
# Chromium proof above passed while his phone showed this, so the proof was not the phone. ----
def _sheet_geometry(page):
    """Everything about where the open sheet and its head actually are, from the page's side."""
    return page.evaluate("""() => {
        const r = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
            return {x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height)}; };
        const hit = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
            const cx = b.x + b.width / 2, cy = b.y + b.height / 2;
            if (cx < 0 || cy < 0 || cx > innerWidth || cy > innerHeight) return "off-screen";
            const at = document.elementFromPoint(cx, cy);
            return at && (at === el || el.contains(at)) ? "hit" : (at ? (at.className || at.tagName).toString().slice(0, 40) : "nothing"); };
        const fly = document.querySelector('.mfly.open');
        const pane = fly && [...fly.querySelectorAll(':scope > div:not(.mfly-head)')].find(d => d.style.display !== 'none');
        const head = fly && fly.querySelector('.mfly-head');
        const done = fly && fly.querySelector('.mfly-done');
        const q = pane && pane.querySelector('.mg-q');
        const chain = []; let e = fly && fly.parentElement;
        while (e && e !== document.documentElement) { const s = getComputedStyle(e);
            if (s.transform !== 'none' || s.contain !== 'none' || s.filter !== 'none' || s.overflow !== 'visible' || s.position === 'fixed')
                chain.push({cls: (e.className || e.tagName).toString().split(' ')[0], transform: s.transform !== 'none', contain: s.contain, overflow: s.overflow, position: s.position, z: s.zIndex, rect: r(e)});
            e = e.parentElement; }
        const scrim = document.querySelector('.glm-scrim'); const hero = document.querySelector('.glm-hero');
        const chainOf = (el) => { const out = []; while (el && el !== document.body) { out.push((el.className || el.tagName).toString().split(' ')[0]); el = el.parentElement; } return out.join('<'); };
        const oy = fly ? Math.round(fly.getBoundingClientRect().y + 4) : -1;
        const overlapTopmost = oy >= 0 ? chainOf(document.elementFromPoint(215, oy)).slice(0, 120) : null;
        const body = document.querySelector('.glm-body');
        const insideScroller = !!(fly && body && body.contains(fly));
        const scrimInsideScroller = !!(scrim && body && body.contains(scrim));
        // the hero's centre: the scrim must be the topmost thing there while the sheet is open
        const hb = hero && hero.getBoundingClientRect();
        const atHero = hb ? document.elementFromPoint(hb.x + hb.width / 2, hb.y + hb.height / 2) : null;
        const scrimOverHero = !!(scrim && atHero === scrim);
        return {viewport: {w: innerWidth, h: innerHeight}, insideScroller, scrimInsideScroller, scrimOverHero, overlapProbeY: oy, overlapTopmost, scrimZ: scrim ? getComputedStyle(scrim).zIndex : null,
            heroStack: hero ? getComputedStyle(hero).position + '/' + getComputedStyle(hero).zIndex : null, sheet: r(fly), sheetOffsetParent: fly && fly.offsetParent ? (fly.offsetParent.className || 'el').toString().split(' ')[0] : null,
            head: r(head), headHit: hit(head), done: r(done), doneHit: hit(done), search: r(q), searchHit: hit(q),
            hero: r(document.querySelector('.glm-hero')), nav: r(document.querySelector('.glm-nav')), chain};
    }""")


def _open_phone_lora_sheet(page):
    page.click("button:has-text('Create')")
    page.wait_for_selector(".cm-addlora")
    page.click(".cm-addlora")
    page.wait_for_selector(".mfly.open .mg-card")


@pytest.mark.parametrize("profile", ["PHONE", "IPHONE_PRO_MAX"])
def test_phone_lora_sheet_head_and_search_box_are_on_screen_and_tappable(logged_in_page, monkeypatch, profile):
    """The sheet's head (Models / LoRAs / Confirm selection) and its search box must be on
    screen and the topmost thing at their own centre, on the owner's phone profile as on the
    390-wide one. His screenshot had neither: the hero sat where the head should be."""
    _fake_market_pages(monkeypatch)
    page = logged_in_page(**globals()[profile])
    _visit(page, "/")
    _settle(page)
    _open_phone_lora_sheet(page)
    g = _sheet_geometry(page)
    engine = page.context.browser.browser_type.name
    print("\nSHEET GEOMETRY", profile, "on", engine, g)
    assert g["head"] and g["headHit"] == "hit", "the sheet head is not on screen or something covers it: %r" % g
    assert g["search"] and g["searchHit"] == "hit", "the search box is not on screen or something covers it: %r" % g
    assert g["doneHit"] == "hit", "Confirm selection is not tappable: %r" % g
    assert g["sheet"]["y"] >= 0, "the sheet's top is above the screen: %r" % g["sheet"]
    # The second half of his report: hero and tab bar UNDIMMED, i.e. the scrim was confined too.
    assert g["scrimOverHero"], "the scrim is not the topmost thing over the hero while the sheet is open: %r" % g
    assert str(g["overlapTopmost"]).startswith("mfly"), "where the sheet overlaps the hero, the hero paints on top: %r" % g
    # The rule no desktop engine can prove for us, so it is pinned structurally: iPhone Safari
    # confines a fixed element inside a touch scroller to the scroller's box (his screenshot).
    # Neither the sheet nor its scrim may be a DOM descendant of the scrolling body.
    assert g["insideScroller"] is False, "the sheet lives inside the scrolling .glm-body again -- iPhone Safari clips it there"
    assert g["scrimInsideScroller"] is False, "the scrim lives inside the scrolling .glm-body again -- iPhone Safari confines it there"
    # Negative control (the module's own contract: each test proves itself). On these engines
    # every geometry number above is the same with the old code, so the structural probe is
    # the discriminating one -- prove it discriminates: put the sheet back inside the scroller
    # and the probe must say so.
    page.evaluate("() => document.querySelector('.glm-body').appendChild(document.querySelector('.cm-modelwrap'))")
    assert _sheet_geometry(page)["insideScroller"] is True, "the scroller probe cannot see a sheet that IS inside .glm-body -- it proves nothing"
