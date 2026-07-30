"""tools/export_design_kit.py -- keeps the design kit's inline token copies true.

The kit's standalone pages (static/mg-*.html, static/design-*.html) each carry the app's
design tokens INLINE, so a page renders on its own anywhere -- opened as a file, served at
/static/, or mounted as a card in a claude.ai/design project. An inline copy is still a
copy, and this codebase has been burned by copies before (the twin-drawer drift, the
friendlyGenErr duplication), so the kit uses the same discipline as the drawer's ported
upscale constants: the copy is GENERATED, documented as generated, and pinned by a test.

  * every inline copy sits between two exact marker comment lines;
  * this script regenerates every marked block from moonglade_gallery.py's
    DESIGN_TOKENS_CSS, plus static/design-tokens.css as a plain stylesheet
    (that one exists for build tooling -- e.g. the React pilot -- to import);
  * tests/test_design_kit_sync.py fails the suite when any copy is stale.

Run after any change to DESIGN_TOKENS_CSS:

    python tools/export_design_kit.py

Extraction is textual, anchored on the constant's own `r\"\"\"` fence, rather than an
import -- so this tool runs on a bare Python with none of the app's dependencies
installed. The test imports the real module and asserts the textual extraction equals the
runtime constant, so if the anchor ever breaks the suite fails loudly instead of the kit
going quietly stale.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GALLERY_PY = REPO / "moonglade_gallery.py"
STATIC = REPO / "static"
TOKENS_CSS = STATIC / "design-tokens.css"

ANCHOR_BEGIN = 'DESIGN_TOKENS_CSS = r"""'
ANCHOR_END = '"""'

# The begin marker is matched by PREFIX (everything up to the first "--") so its wording
# can be improved without stranding stamped pages; the end marker is matched exactly.
BEGIN_PREFIX = "/* mg-tokens:begin"
BEGIN_MARK = (
    "/* mg-tokens:begin -- generated from moonglade_gallery.DESIGN_TOKENS_CSS by "
    "tools/export_design_kit.py; hand-edits between these markers are overwritten */"
)
END_MARK = "/* mg-tokens:end */"

CSS_HEADER = (
    "/* static/design-tokens.css -- GENERATED from moonglade_gallery.DESIGN_TOKENS_CSS by\n"
    "   tools/export_design_kit.py; do not hand-edit. The Python constant is the single\n"
    "   source of truth (the app substitutes it directly into its own pages); this file\n"
    "   exists so build tooling outside the Flask app -- the React pilot, the design-kit\n"
    "   bundle pushed to claude.ai/design -- can import the same tokens instead of\n"
    "   carrying a hand-typed copy. Pinned by tests/test_design_kit_sync.py. */\n"
)


def extract_tokens(gallery_source: str) -> str:
    """The raw CSS between the constant's r-string fences, exactly as the app serves it."""
    start = gallery_source.index(ANCHOR_BEGIN) + len(ANCHOR_BEGIN)
    end = gallery_source.index(ANCHOR_END, start)
    return gallery_source[start:end].strip("\n")


def tokens_stamp(tokens: str) -> str:
    return BEGIN_MARK + "\n" + tokens + "\n" + END_MARK


def restamp(page_text: str, stamp: str) -> str:
    """Replace the marked block (inclusive) with a fresh stamp; ValueError if unmarked."""
    begin = page_text.index(BEGIN_PREFIX)
    end = page_text.index(END_MARK, begin) + len(END_MARK)
    return page_text[:begin] + stamp + page_text[end:]


def kit_pages(repo: Path = REPO) -> list[Path]:
    """Every static page carrying the markers -- the definition of 'a kit page'."""
    return sorted(
        p for p in (repo / "static").glob("*.html")
        if BEGIN_PREFIX in p.read_text(encoding="utf-8")
    )


def css_file_text(tokens: str) -> str:
    return CSS_HEADER + "\n" + tokens + "\n"


def main() -> int:
    tokens = extract_tokens(GALLERY_PY.read_text(encoding="utf-8"))
    stamp = tokens_stamp(tokens)
    touched = []

    new_css = css_file_text(tokens)
    if not TOKENS_CSS.exists() or TOKENS_CSS.read_text(encoding="utf-8") != new_css:
        TOKENS_CSS.write_text(new_css, encoding="utf-8", newline="\n")
        touched.append(TOKENS_CSS)

    for page in kit_pages():
        old = page.read_text(encoding="utf-8")
        new = restamp(old, stamp)
        if new != old:
            page.write_text(new, encoding="utf-8", newline="\n")
            touched.append(page)

    for path in touched:
        print(f"refreshed  {path.relative_to(REPO)}")
    if not touched:
        print("kit already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
