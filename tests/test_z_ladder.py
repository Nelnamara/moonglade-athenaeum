"""The fixed-overlay z-index LADDER (issue #39) — relations, not pixels.

The lightbox (.lbx) was raised to z-index 400 at some point and silently stranded three
whole overlay layers beneath it: the shared .mgv overlay band (Publish and nine siblings,
300/301), the Similar modal (316/317) and the Upscale panel (320 — whose own comment still
said "must clear the lightbox's own 300"). Every one of them can be OPENED from inside the
lightbox or Details, so each painted invisibly behind the picture; the 2026-08-29 surface
walk caught Publish "appearing to do nothing" and the other two fell to the same class.

A z-index is a relationship wearing a number's clothing, so this guard asserts the
RELATIONSHIPS between the bands, parsed from the committed source CSS (no browser needed —
this runs on CI, where the render harness skips). Renumber freely; reorder and this fails
with the pair that flipped. The canonical ladder comment lives in
gallery/src/styles/overlays.css.
"""
import re
from pathlib import Path

import pytest

STYLES = Path(__file__).resolve().parent.parent / "gallery" / "src"


def _z(css_file, selector):
    """First z-index declared in the rule whose selector list contains `selector` exactly."""
    text = (STYLES / css_file).read_text(encoding="utf-8")
    # comments first: the ladder comment in overlays.css names every selector, and an
    # unstripped `.mgv-host` in prose would match before the real rule does
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    # find the selector at a rule boundary, then the first z-index before the block closes
    pat = re.compile(re.escape(selector) + r"[^{]*\{([^}]*)\}", re.S)
    for m in pat.finditer(text):
        z = re.search(r"z-index:\s*(\d+)", m.group(1))
        if z:
            return int(z.group(1))
    raise AssertionError("no z-index found for %r in %s" % (selector, css_file))


@pytest.fixture(scope="module")
def z():
    return {
        "lbx":           _z("styles/lightbox.css", ".lbx "),
        "mgv_scrim":     _z("styles/overlays.css", ".mgv-scrim"),
        "mgv_host":      _z("styles/overlays.css", ".mgv-host"),
        "similar_scrim": _z("styles.css", ".similar-scrim"),
        "similar_modal": _z("styles.css", ".similar-modal"),
        "upscale":       _z("styles/upscale-panel.css", ".upscale-panel:not(.inline) "),
        "cp_sub":        _z("styles/control-panel.css", ".mgcp-sub-scrim"),
        "cp_sub_host":   _z("styles/control-panel.css", ".mgcp-sub-host"),
        "cp_pwr":        _z("styles/control-panel.css", ".mgcp-pwr-scrim"),
        "cp_pwr_host":   _z("styles/control-panel.css", ".mgcp-pwr-host"),
        "mgl_scrim":     _z("styles/librarybar.css", ".mgl-scrim"),
        "mgl_menu":      _z("styles/librarybar.css", ".mgl-menu"),
        "claim":         _z("styles/claim-modal.css", ".mgclaim-scrim"),
        "claim_host":    _z("styles/claim-modal.css", ".mgclaim-host"),
        "mgai":          _z("styles/ai-tools.css", ".mgai-scrim"),
        "ct_sub":        _z("styles/myart-contests.css", ".mgct-subscrim"),
        "ct_sub_host":   _z("styles/myart-contests.css", ".mgct-subhost"),
    }


def test_lightbox_launched_layers_clear_the_lightbox(z):
    """Publish (mgv band), Similar and Upscale all open from inside the lightbox/Details —
    each must paint ABOVE it, or its scrim+content render invisibly behind the picture."""
    assert z["mgv_scrim"] > z["lbx"], "the shared overlay band is BEHIND the lightbox again"
    assert z["similar_scrim"] > z["lbx"], "Similar opens behind the lightbox again"
    assert z["upscale"] > z["lbx"], "the Upscale modal opens behind the picture it upscales"


def test_each_scrim_sits_under_its_own_content(z):
    assert z["mgv_host"] > z["mgv_scrim"]
    assert z["similar_modal"] > z["similar_scrim"]
    assert z["mgl_menu"] > z["mgl_scrim"]
    # the first cut of #39 raised these two SCRIMS and left their hosts at 321/341 --
    # the scrim painted over its own sub-overlay and the render harness's Trash-close
    # click was intercepted. The pair moves together or not at all.
    assert z["cp_sub_host"] > z["cp_sub"]
    assert z["cp_pwr_host"] > z["cp_pwr"]
    # ...and the SECOND recurrence, caught by adversarial review after the first fix:
    # the claim modal's scrim went to 440 while its host sat at 361 -- a full-screen
    # click-eating scrim OVER the Claim button. Every scrim/host pair is listed now.
    assert z["claim_host"] > z["claim"]
    # ...and the contest picker/confirm pair, which joined the same class of hazard the
    # day it was built: both open ON TOP of the Contests (or My Art) slab.
    assert z["ct_sub_host"] > z["ct_sub"]


def test_layers_that_stack_on_the_overlay_band_stay_above_it(z):
    """These open ON TOP of an mgv-hosted overlay (Control Panel sub-modals, its power
    modal, the Claim modal over Contests/MyArt) — flipping any of them under 411 hides a
    modal the user just asked for."""
    assert z["cp_sub"] > z["mgv_host"]
    assert z["cp_pwr"] > z["cp_sub_host"]
    assert z["claim"] > z["mgv_host"]
    # the contest picker (C) and confirm (D) open from the Contests/My Art slabs
    assert z["ct_sub"] > z["mgv_host"]
    assert z["mgl_scrim"] > z["mgv_host"]
    # .mgai-scrim TIED .lbx at 400 and survived only on accidental DOM order --
    # now a deliberate rung above the lightbox.
    assert z["mgai"] > z["lbx"]


def test_actions_menu_can_never_outgrow_the_viewport():
    """#40's belt half: .mgl-menu carries a viewport-bounded max-height + its own scroll,
    so the useLayoutEffect clamp in ActionsMenu.jsx always has a menu that FITS to place.
    (The flip-above logic itself is behavior; this pins the CSS contract it relies on.)"""
    text = (STYLES / "styles/librarybar.css").read_text(encoding="utf-8")
    m = re.search(r"\.mgl-menu\s*\{([^}]*)\}", text, re.S)
    assert m, "no .mgl-menu rule"
    assert "max-height" in m.group(1), ".mgl-menu lost its viewport max-height (issue #40)"
    assert re.search(r"overflow-y:\s*auto", m.group(1)), ".mgl-menu lost its internal scroll"
