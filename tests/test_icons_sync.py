"""gallery/src/icons/Icons.jsx is GENERATED -- this is the drift alarm.

tools/build_icons.py transcribes the seven .svg files in gallery/src/icons/ into that one
React module. A copy of anything may exist only while a test pins it to its source, which
is the same discipline tests/test_design_kit_sync.py applies to static/design-tokens.css
and tests/test_upscale_boosters.py to the drawer's ported constants. Without this, a hand
edit to a path -- or an edited .svg with no re-run -- ships an icon that no longer matches
the licensed art it claims to be.

The icons are the owner's Glyph Ledger picks (moonglade-internal/design/glyphs/README.md,
2026-09-05), from the Glyphs set (glyphs.fyi, MIT). Which file means what in the app is
build_icons.py's ICONS table; the render-side guards are loom/test/glyph-ledger.test.js.
"""
import importlib.util
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
ICON_DIR = REPO / "gallery" / "src" / "icons"


def _builder():
    # tools/ is not a package; load the generator off its file path (test_design_kit_sync's
    # own pattern).
    spec = importlib.util.spec_from_file_location(
        "build_icons", REPO / "tools" / "build_icons.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BUILD = _builder()


def test_the_generated_module_is_current():
    on_disk = (ICON_DIR / "Icons.jsx").read_text(encoding="utf-8")
    assert on_disk == BUILD.build(), (
        "gallery/src/icons/Icons.jsx is stale -- run: python tools/build_icons.py")


def test_every_named_icon_has_its_art_and_the_art_is_all_named():
    named = {fname for _, fname, _ in BUILD.ICONS}
    on_disk = {p.stem for p in ICON_DIR.glob("*.svg")}
    assert named == on_disk, "the ICONS table and the .svg files disagree"
    # the app's own keys, so a rename in one place fails here rather than at runtime
    assert [key for key, _, _ in BUILD.ICONS] == [
        "search", "uses", "lora", "entered", "snippets", "folio", "panel"]


def test_the_shipped_art_is_tintable_and_carries_no_hardcoded_colour():
    for path in sorted(ICON_DIR.glob("*.svg")):
        text = path.read_text(encoding="utf-8")
        assert "currentColor" in text, path.name
        assert "#" not in text, "%s still draws in a fixed colour" % path.name
        # the transform is idempotent: running the generator again must not re-edit these
        assert BUILD.transform(text, poly=path.stem.endswith("_poly")) == text, path.name


def test_the_licence_travels_with_the_art():
    notice = (ICON_DIR / "NOTICE").read_text(encoding="utf-8")
    for needle in ("glyphs.fyi", "github.com/gorango/glyphs", "MIT License",
                   'THE SOFTWARE IS PROVIDED "AS IS"'):
        assert needle in notice, needle
