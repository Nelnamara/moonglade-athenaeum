"""The gallery picker must not let the wheel reach the page behind it (owner report: over the
Video drawer the library scrolled under three stacked backdrop blurs and Mac Chrome flickered).
Two rules, both pinned here at the source:

1. `overscroll-behavior: contain` on the scrim and on the grid, so a scroll that hits the
   grid's end does not chain to the page.
2. The page is held still while the picker is mounted, through the shared reference-counted
   useScrollLock hook (which restores the page's own overflow when the LAST layer unmounts,
   so two stacked pickers never release it early)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "gallery" / "src"


def _rule_body(css, selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert m, selector + " has no rule"
    return m.group(1)


def test_the_scrim_and_the_grid_contain_their_overscroll():
    css = (ROOT / "styles" / "gallery-picker.css").read_text(encoding="utf-8")
    for selector in (".mg-gallery-picker", ".mg-gallery-picker .mg-pk-grid"):
        body = _rule_body(css, selector)
        assert re.search(r"overscroll-behavior\s*:\s*contain", body), selector


def test_the_picker_locks_the_page_while_mounted():
    jsx = (ROOT / "components" / "GalleryPicker.jsx").read_text(encoding="utf-8")
    assert re.search(r'import\s+useScrollLock\s+from\s+"\.\./hooks/useScrollLock\.js"', jsx)
    assert re.search(r"^\s*useScrollLock\(\);", jsx, re.M)


def test_the_lock_is_counted_and_restores_the_previous_overflow():
    hook = (ROOT / "hooks" / "useScrollLock.js").read_text(encoding="utf-8")
    assert "_locks === 0" in hook and "_locks += 1" in hook and "_locks -= 1" in hook
    assert "_prevOverflow = document.body.style.overflow" in hook
    assert "document.body.style.overflow = _prevOverflow" in hook
