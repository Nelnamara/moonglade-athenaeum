"""The design kit's inline token copies are GENERATED -- this is the drift alarm.

static/design-tokens.css and every `mg-tokens:begin/end` block inside the kit's standalone
pages are written by tools/export_design_kit.py from moonglade_gallery.py's
DESIGN_TOKENS_CSS. A hand edit to any copy, or a token change that skips the export step,
fails here naming the one command that repairs it. Same discipline as the drawer's ported
upscale constants (tests/test_upscale_boosters.py): a copy may exist only while a test
pins it to its source -- this codebase has shipped the alternative before (the twin-drawer
drift), and the kit's OLD hand-typed token slices had already drifted from the constant
(--mantle #131024 vs the real #0a0818) when this test was introduced.
"""
import importlib.util
import pathlib

import moonglade_gallery as gallery

REPO = pathlib.Path(__file__).resolve().parents[1]


def _kit():
    # tools/ is not a package; load the exporter off its file path.
    spec = importlib.util.spec_from_file_location(
        "export_design_kit", REPO / "tools" / "export_design_kit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


KIT = _kit()
TOKENS = gallery.DESIGN_TOKENS_CSS.strip("\n")


def test_textual_extraction_matches_the_runtime_constant():
    # The exporter reads moonglade_gallery.py as TEXT (so it needs none of the app's
    # dependencies); the app serves the CONSTANT. If the r-string anchor ever stops
    # isolating exactly that constant, every downstream guarantee is off -- fail here
    # first, loudly.
    src = (REPO / "moonglade_gallery.py").read_text(encoding="utf-8")
    assert KIT.extract_tokens(src) == TOKENS


def test_design_tokens_css_is_current():
    on_disk = (REPO / "static" / "design-tokens.css").read_text(encoding="utf-8")
    assert on_disk == KIT.css_file_text(TOKENS), (
        "static/design-tokens.css is stale -- run: python tools/export_design_kit.py")


def test_every_kit_page_is_stamped_current_and_carries_its_card_marker():
    pages = KIT.kit_pages(REPO)
    names = {p.name for p in pages}
    # The foundation pages. Every vanilla component harness is now gone: mg-gallery-picker,
    # mg-model-picker, mg-upscale-panel, mg-notify, mg-cost-badge and (last, 2026-08-08)
    # mg-generate-drawer were all ported to React (GalleryPicker/ModelPicker/UpscalePanel, the
    # notify system in gallery/src/notify/, CostBadge, VideoDrawer) and their harness pages
    # removed with them -- so the campaign has emptied static/ of vanilla JS and its component
    # harnesses. What remains carrying the markers is the design-token foundation; any later
    # Claude Design pass is flagged separately. A kit page announces itself by carrying the
    # markers; this floor stops a rename from quietly dropping one.
    assert {"design-tokens.html", "design-skins.html"} <= names

    stamp = KIT.tokens_stamp(TOKENS)
    for page in pages:
        text = page.read_text(encoding="utf-8")
        # First line is the claude.ai/design card marker -- the Design System pane
        # builds its card index from it, and the DesignSync bundle relies on it.
        assert text.startswith("<!-- @dsCard "), page.name
        assert stamp in text, (
            f"{page.name} stamp is stale -- run: python tools/export_design_kit.py")
