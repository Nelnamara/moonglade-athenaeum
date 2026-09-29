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
        # B2 (2026-09-04) retired the Similar MODAL: Similar renders in the grid's own
        # place under a token in the library bar, so it has no z-index to place and cannot
        # paint behind anything. B3's series stack modal took its 414/415 rung.
        "series_scrim":  _z("styles/series-modal.css", ".mgss-scrim"),
        "series_panel":  _z("styles/series-modal.css", ".mgss "),
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
        "pal_scrim":     _z("styles/command-palette.css", ".mgpal-scrim"),
        "pal_host":      _z("styles/command-palette.css", ".mgpal-host"),
        "pal_gchip":     _z("styles/command-palette.css", ".mgpal-gchip"),
        "ks_scrim":      _z("styles/command-palette.css", ".mgks-scrim"),
        "ks_host":       _z("styles/command-palette.css", ".mgks-host"),
        "ct_sub":        _z("styles/myart-contests.css", ".mgct-subscrim"),
        "ct_sub_host":   _z("styles/myart-contests.css", ".mgct-subhost"),
        "pal_c_scrim":   _z("styles/color-palette.css", ".cpal-scrim"),
        "pal_c_host":    _z("styles/color-palette.css", ".cpal-host"),
        "recipes_scrim": _z("styles/recipes.css", ".rcp-scrim"),
        "recipes_host":  _z("styles/recipes.css", ".rcp-host"),
        "recipes_phone": _z("styles/recipes.css", ".rcp-m "),
        "gallery_picker": _z("styles/gallery-picker.css", ".mg-gallery-picker"),
        # Session N (wave 5): the collections manager and the curation undo toast
        "cu_scrim":      _z("styles/curation.css", ".mgcu-scrim"),
        "cu_mgr":        _z("styles/curation.css", ".mgcu-mgr "),
        "cu_toast":      _z("styles/curation.css", ".mgcu-toast "),
    }


def test_lightbox_launched_layers_clear_the_lightbox(z):
    """Publish (mgv band) and Upscale open from inside the lightbox/Details — each must
    paint ABOVE it, or its scrim+content render invisibly behind the picture. (Similar was
    the third; B2 turned it into a state on the library rather than a layer, so it is no
    longer on this ladder at all — see the series modal below, which took its rung.)"""
    assert z["mgv_scrim"] > z["lbx"], "the shared overlay band is BEHIND the lightbox again"
    assert z["upscale"] > z["lbx"], "the Upscale modal opens behind the picture it upscales"
    # the series stack modal opens over the GRID, never from inside the lightbox, but it
    # stays above 400 with the rest of the band: one ladder, one direction.
    assert z["series_scrim"] > z["lbx"], "the series stack modal fell under the lightbox"


def test_each_scrim_sits_under_its_own_content(z):
    assert z["mgv_host"] > z["mgv_scrim"]
    assert z["series_panel"] > z["series_scrim"]
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
    # ...and the command palette + its cheat-sheet, added with the same pairing discipline
    # the two recurrences above bought: a scrim without its host is a click-eating sheet of
    # glass over the thing it is supposed to be dimming.
    assert z["pal_host"] > z["pal_scrim"]
    assert z["ks_host"] > z["ks_scrim"]
    # ...and the contest picker/confirm pair, which joined the same class of hazard the
    # day it was built: both open ON TOP of the Contests (or My Art) slab.
    assert z["ct_sub_host"] > z["ct_sub"]
    # ...and the Generate drawer's colour palette (lane w2-small, 2026-09-28): it opens over the
    # dock (7) and the phone's Advanced screen (308), above the phone's model sheet (345).
    assert z["pal_c_host"] > z["pal_c_scrim"] > 345


def test_the_collections_manager_and_its_undo_toast_keep_their_rungs(z):
    """Session N: the manager takes the free 418/419 between the recipe picker and the upscale
    panel (it opens over the gallery, never from inside a layer, so it needs no more than the
    band's floor above the lightbox); its scrim sits under its own slab. The undo toast is a
    rating pressed INSIDE any layer's answer -- the lightbox, the record -- so it must clear
    every sub-overlay a rating can be pressed under, and stay below the power modal."""
    assert z["cu_mgr"] > z["cu_scrim"], "the manager's scrim would eat clicks meant for its own rows"
    assert z["cu_scrim"] > z["lbx"] and z["cu_scrim"] > z["recipes_host"]
    assert z["cu_mgr"] < z["upscale"]
    assert z["cu_toast"] > z["ct_sub_host"] > z["cp_sub_host"], "a rating's Undo hid under a sub-overlay"
    assert z["cu_toast"] > z["cu_mgr"] and z["cu_toast"] < z["cp_pwr"]


def test_the_colour_palette_stays_under_the_picker_it_opens():
    """"Extract from image" -> "From the gallery" opens the shared picker ON TOP of the palette
    window; flip that pair and the picker paints behind the window that asked for it."""
    zz = {"host": _z("styles/color-palette.css", ".cpal-host"),
          "picker": _z("styles/gallery-picker.css", ".mg-gallery-picker")}
    assert zz["picker"] > zz["host"], zz


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


def test_command_palette_band_clears_every_layer_it_opens_over(z):
    """Ctrl/⌘ K works from ANY layer — that is the point of a palette — so its scrim must
    clear the topmost thing the app can already have up (the claim modal's host), and the
    cheat-sheet must in turn clear the palette. The `?` sheet opens FROM the palette; flip
    that pair and the sheet paints behind the panel that launched it, which is the exact
    class of bug #39 was about."""
    assert z["pal_scrim"] > z["claim_host"], "the command palette opens under the claim modal"
    assert z["pal_gchip"] > z["pal_host"], "the G… chip can be buried by the palette panel"
    assert z["ks_scrim"] > z["pal_host"], "the cheat-sheet opens behind the palette"


def test_the_recipes_overlay_clears_the_lightbox_and_sits_under_its_own_pickers(z):
    """The recipe picker, market and creator (lane w2-recipes). ⁂ Make a recipe opens the
    creator FROM the Lightbox (desktop and phone), so the whole band must clear .lbx and
    the shared slab it can also open over; the creator asks the gallery picker for
    pictures, and the palette opens from any layer, so both stay above it. The scrim/host
    pair moves together."""
    assert z["recipes_scrim"] > z["lbx"] and z["recipes_scrim"] > z["mgv_host"]
    assert z["recipes_host"] > z["recipes_scrim"]
    assert z["recipes_phone"] == z["recipes_host"]
    assert z["gallery_picker"] > z["recipes_host"], "the creator's picture picker opens behind it"
    assert z["pal_scrim"] > z["recipes_host"], "the palette opens under the recipes overlay"


def test_actions_menu_can_never_outgrow_the_viewport():
    """#40's belt half: .mgl-menu carries a viewport-bounded max-height + its own scroll,
    so the useLayoutEffect clamp in ActionsMenu.jsx always has a menu that FITS to place.
    (The flip-above logic itself is behavior; this pins the CSS contract it relies on.)"""
    text = (STYLES / "styles/librarybar.css").read_text(encoding="utf-8")
    m = re.search(r"\.mgl-menu\s*\{([^}]*)\}", text, re.S)
    assert m, "no .mgl-menu rule"
    assert "max-height" in m.group(1), ".mgl-menu lost its viewport max-height (issue #40)"
    assert re.search(r"overflow-y:\s*auto", m.group(1)), ".mgl-menu lost its internal scroll"


def test_the_guide_and_help_sit_over_every_surface_and_under_the_palette(z):
    """Session I (lane w3-help, help.css's THE RUNGS): the first-run guide's blocker, ring and
    cards stand over every surface they point at -- the Control Panel and its subs top out at
    the claim modal -- Help stands over the guide it can replay, About opens from Help's own
    page and the what's-new sheet opens About; the command palette, which closes before
    anything it opens, stays above all of them."""
    h = {
        "block": _z("styles/help.css", ".mgguide-block"),
        "ring": _z("styles/help.css", ".mgguide-ring"),
        "mark": _z("styles/help.css", ".mgguide-mark"),
        "welcome": _z("styles/help.css", ".mgguide-welcome"),
        "help_scrim": _z("styles/help.css", ".mghelp-scrim"),
        "help_host": _z("styles/help.css", ".mghelp-host"),
        "ab_scrim": _z("styles/help.css", ".mgab-scrim"),
        "ab_host": _z("styles/help.css", ".mgab-host"),
        "wn_scrim": _z("styles/help.css", ".mgwn-scrim"),
        "wn_host": _z("styles/help.css", ".mgwn-host"),
    }
    assert h["block"] > z["claim_host"] and h["block"] > z["cp_pwr_host"], h
    assert h["block"] > z["recipes_host"] and h["block"] > z["mgv_host"], h
    assert h["ring"] > h["block"] and h["mark"] > h["ring"] and h["welcome"] == h["mark"], h
    assert h["help_scrim"] > h["mark"] and h["help_host"] > h["help_scrim"], h
    assert h["ab_scrim"] > h["help_host"] and h["ab_host"] > h["ab_scrim"], h
    assert h["wn_scrim"] > h["ab_host"] and h["wn_host"] > h["wn_scrim"], h
    assert z["pal_scrim"] > h["wn_host"], "the palette opens under Help's layers"
    assert all(300 <= v <= 500 for v in h.values()), "a Help layer left the overlay band"


def test_train_a_lora_phone_sheets_open_over_their_screen(z):
    """Session J (lane w3-train, train-mobile.css): Train a LoRA's phone sheets are portalled to
    .glm-stage, so they need a rung above the pushed screen they open from (.glm-screen 308),
    scrim under slab, and stay under the full-screen viewers (315) and the Create tab's model
    sheet (345)."""
    screen = _z("styles/gallery-mobile.css", ".glm-screen ")
    scrim = _z("styles/train-mobile.css", ".glm-scrim.trm-sheet")
    sheet = _z("styles/train-mobile.css", ".glm-sheet.trm-sheet")
    viewer = _z("styles/image-details-mobile.css", ".idm-root")
    assert sheet > scrim > screen, (screen, scrim, sheet)
    assert sheet < viewer, "a Train sheet would cover the full-screen viewer"
    assert all(300 <= v <= 500 for v in (screen, scrim, sheet)), "a phone layer left the band"
