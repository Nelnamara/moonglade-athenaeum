import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE CONTROL PANEL'S SCROLL PANE MUST ACTUALLY GET THE OVERFLOW (owner's walk, 2026-09-07:
   "Font section added to branding pushed things down and is unscrollable").

   .mgcp-main is the panel's one scroll pane -- a flex column with overflow-y:auto. Each tab
   drops one or two slabs straight into it. .mgcp-brandgrid, the Branding tab's slab, also
   carried `overflow:hidden` (it rounds the corners over the two columns) and `min-height:620px`.

   That combination silently disarms the pane. CSS Flexbox 4.5, the automatic minimum size:
   a flex item's `min-height:auto` resolves to its CONTENT size only while its overflow is
   visible -- with any other overflow value it resolves to zero. So the branding slab was free
   to shrink below its own content, and it did: the moment the fonts row pushed the sections
   past 620px, the slab shrank back to its min-height and clipped the surplus itself. Nothing
   ever overflowed .mgcp-main, so .mgcp-main never scrolled, and the fonts row was unreachable.

   The guard is therefore a rule about the pair, not about one selector: a slab that clips its
   own overflow must also refuse to shrink, so the surplus is handed up to the pane that scrolls.
   It reads the slab list out of ControlPanelOverlay.jsx rather than hard-coding it, so a fifth
   tab added later is covered on the day it is written. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Line endings normalized on read: the repo stores LF, Windows checks out CRLF.
const read = (p) => readFileSync(path.resolve(__dirname, "../..", p), "utf8").replace(/\r\n/g, "\n");
const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, " ");

const css = stripComments(read("gallery/src/styles/control-panel.css"));
const jsxRaw = read("gallery/src/components/ControlPanelOverlay.jsx");
const jsx = jsxRaw.split("\n");

/** The body of the bare (non-@media) rule for a single class selector. */
function decl(sel) {
  const re = new RegExp("(^|[},])\\s*\\." + sel + "\\s*\\{([^}]*)\\}", "m");
  const m = css.match(re);
  assert.ok(m, "." + sel + " has no bare rule in control-panel.css -- it was renamed or moved, "
    + "so this guard is now blind. Point it at the new selector rather than deleting it.");
  return m[2];
}

/** A declaration's value, or null when the property is not set in that body. */
function prop(body, name) {
  const m = body.match(new RegExp("(?:^|;)\\s*" + name + "\\s*:\\s*([^;]+)"));
  return m ? m[1].trim() : null;
}

/** Does this rule clip its own overflow (i.e. switch off the flex automatic minimum size)? */
function clips(body) {
  for (const name of ["overflow", "overflow-y", "overflow-x", "overflow-block"]) {
    const v = prop(body, name);
    if (v && !/^(visible|clip)\b/.test(v)) return name + ":" + v;
  }
  return null;
}

/** The classes ControlPanelOverlay renders as direct children of .mgcp-main. */
function slabs() {
  const start = jsx.findIndex((l) => /<div className="mgcp-main">/.test(l));
  assert.ok(start >= 0, "ControlPanelOverlay no longer renders a .mgcp-main -- the panel's scroll "
    + "pane was renamed, so this guard is blind. Re-point it before touching the CSS.");
  const indent = (l) => l.match(/^ */)[0].length;
  const N = indent(jsx[start]);
  let end = start + 1;
  for (; end < jsx.length; end++) if (jsx[end].trim() === "</div>" && indent(jsx[end]) === N) break;
  assert.ok(end < jsx.length, ".mgcp-main's closing tag was not found at its own indent");

  // Children sit at most three levels in: the tab conditionals and their fragments are
  // wrappers that render nothing, so `{tab === "maint" && (<>` costs two levels of source
  // indent and no level of DOM.
  const found = new Set();
  for (let i = start + 1; i < end; i++) {
    const line = jsx[i];
    if (indent(line) > N + 6) continue;
    const cls = line.match(/className="([^"{]+)"/);
    if (cls) { found.add(cls[1].trim()); continue; }
    const comp = line.match(/^\s*<([A-Z][A-Za-z0-9_]*)/);
    if (comp) found.add(rootClassOf(comp[1]));
  }
  found.delete(null);
  return [...found];
}

/** The class on the element a child component returns -- its slab in the pane. */
function rootClassOf(name) {
  const at = jsxRaw.indexOf("function " + name + "(");
  assert.ok(at >= 0, name + " is mounted in .mgcp-main but not defined in ControlPanelOverlay.jsx; "
    + "this guard cannot see what it renders. Teach it where to look.");
  const body = jsxRaw.slice(at);
  const ret = body.search(/\n\s*return \(/);
  assert.ok(ret >= 0, name + " has no `return (` this guard can read");
  const m = body.slice(ret).match(/className="([^"{]+)"/);
  return m ? m[1].trim() : null;
}

describe("the Control Panel's scroll pane gets the overflow", () => {
  test(".mgcp-main is still the flex column that scrolls", () => {
    // Every claim below rests on these three. If the pane stops being a flex column, or stops
    // scrolling, the flex automatic-minimum-size trap no longer applies and this whole file
    // should be rewritten to whatever replaced it -- not relaxed.
    const main = decl("mgcp-main");
    assert.match(prop(main, "display") || "", /flex/);
    assert.match(prop(main, "flex-direction") || "", /column/);
    assert.match(prop(main, "overflow-y") || "", /auto|scroll/);
  });

  test("the Branding slab hands its overflow up instead of clipping it", () => {
    const brand = decl("mgcp-brandgrid");
    const clipped = clips(brand);
    if (clipped) {
      assert.equal(prop(brand, "flex-shrink"), "0",
        ".mgcp-brandgrid sets " + clipped + ", which zeroes its flex automatic minimum size "
        + "(Flexbox 4.5), so it shrinks under its own content and swallows the overflow the "
        + "Control Panel needs to scroll. Either drop the overflow or keep flex-shrink:0.");
    }
    // And the min-height it shrinks back TO is the fixed slab the owner saw content vanish
    // behind -- named here so a future reader sees why shrinking was so visible.
    assert.equal(prop(brand, "min-height"), "620px");
  });

  test("every slab the panel drops into the pane obeys the same pair", () => {
    const list = slabs();
    assert.ok(list.includes("mgcp-brandgrid") && list.includes("mgcp-tabs"),
      "the slab scan found " + JSON.stringify(list) + " -- it no longer sees the panel's real "
      + "children, so fix the scan rather than trusting a green test");
    for (const cls of list) {
      const body = decl(cls);
      const clipped = clips(body);
      if (!clipped) continue;
      assert.equal(prop(body, "flex-shrink"), "0",
        "." + cls + " is a direct child of .mgcp-main and sets " + clipped + ". A flex item "
        + "whose overflow is not visible gets min-height:auto = 0, so it shrinks under its own "
        + "content and the pane never scrolls. Add flex-shrink:0 or drop the overflow.");
    }
  });
});
