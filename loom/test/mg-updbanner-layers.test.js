import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE STRIP PUSHES EVERY SHELL DOWN, INCLUDING THE ONES NOBODY LISTED (2026-09-07, later the
   same day the update banner shipped).

   The first cut of the banner moved the shells it could name: `.app`, the desktop header,
   the phone stage, `.sb-root`, the wizard. `.sb-root` was the Loom's whole answer -- and it
   is a padding on an ordinary in-flow div, while the Loom's REAL shells (`.lv-overlay` on the
   desktop, `.lm-root` on the phone) are `position:fixed; inset:0` layers pinned to the
   viewport. No ancestor's padding can move a fixed layer, so the z-509 strip painted over
   the Loom's top bar and the phone Loom's only "< Gallery" link, and took their clicks with
   it (the expanded strip is not pointer-events:none). The full-screen viewer `.lbx` was
   covered the same way.

   So the fix is a RULE, and this is the test that keeps it one: re-derive every
   `position:fixed; inset:0` root from the stylesheets themselves -- gallery/src/styles/*.css
   plus the Loom's three inline styleset literals -- and require each to be either offset by
   `top:var(--mg-updbanner-h)` under `html.mg-updbanner-on`, or named in the exemption list
   below with a reason. A new full-screen layer added next month fails here until somebody
   decides which it is. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const STYLES_DIR = path.join(__dirname, "../../gallery/src/styles");
const LOOM_JSX = path.join(__dirname, "../master-storyboard.jsx");
const read = (p) => readFileSync(p, "utf8").replace(/\r\n/g, "\n");

/* The two layers that are deliberately NOT offset. Each entry is a reason, not a shrug --
   adding one here is a decision, and the string is what the next reader gets. */
const EXEMPT = new Map([
  [".mgx-veil",
    "z-index 2, pointer-events:none -- a decorative bottom gradient that must reach the " +
    "viewport edge. It covers no control and can eat no click."],
  [".ach-m2",
    "z-index 520, ABOVE the strip on purpose -- an earned achievement owns the whole screen " +
    "for its few seconds, the strip included."],
]);

const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "");

/* Every `sel { decls }` pair in a sheet. @media wrappers fall out on their own: the selector
   half cannot contain a brace, so the engine walks past the wrapper and matches the rules
   inside it. */
function* rules(css) {
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(css))) yield { sel: m[1].trim(), decl: m[2] };
}

const flat = (decl) => decl.replace(/\s+/g, "");
const isFixedFullScreen = (decl) => {
  const d = flat(decl);
  return d.includes("position:fixed") && /(^|;)inset:0(px)?(;|$)/.test(d);
};
const zOf = (decl) => {
  const m = /z-index:\s*(-?\d+)/.exec(decl);
  return m ? Number(m[1]) : null;
};

/* The Loom keeps its CSS in three template literals inside the JSX. Read them the same way
   the browser eventually does -- as stylesheets. */
function loomStylesets() {
  const src = read(LOOM_JSX);
  const out = [];
  const re = /const (\w*STYLES)\s*=\s*`/g;
  let m;
  while ((m = re.exec(src))) {
    const start = m.index + m[0].length;
    const end = src.indexOf("`", start);
    assert.ok(end > start, `${m[1]} literal is unterminated`);
    out.push({ name: `master-storyboard.jsx:${m[1]}`, css: src.slice(start, end) });
  }
  return out;
}

function allSheets() {
  const sheets = readdirSync(STYLES_DIR)
    .filter((f) => f.endsWith(".css"))
    .sort()
    .map((f) => ({ name: `styles/${f}`, css: read(path.join(STYLES_DIR, f)) }));
  return sheets.concat(loomStylesets());
}

/* Every fixed full-screen layer root in the app, as {selector -> {sheet, z}}. */
function fixedRoots() {
  const found = new Map();
  for (const sheet of allSheets()) {
    for (const { sel, decl } of rules(stripComments(sheet.css))) {
      if (!isFixedFullScreen(decl)) continue;
      const z = zOf(decl);
      for (const one of sel.split(",")) {
        const s = one.trim();
        if (!s || s.startsWith("@") || s.includes("`")) continue;
        if (!found.has(s)) found.set(s, { sheet: sheet.name, z });
      }
    }
  }
  return found;
}

/* Everything notify.css moves down by the strip's height. */
function offsetSelectors() {
  const css = stripComments(read(path.join(STYLES_DIR, "notify.css")));
  const out = new Set();
  for (const { sel, decl } of rules(css)) {
    if (!/(top|padding-top):\s*var\(--mg-updbanner-h/.test(decl)) continue;
    for (const one of sel.split(",")) {
      const s = one.trim();
      const m = /^html\.mg-updbanner-on\s+(.+)$/.exec(s);
      if (m) out.add(m[1].trim());
    }
  }
  return out;
}

const STRIP_Z = (() => {
  const css = stripComments(read(path.join(STYLES_DIR, "notify.css")));
  for (const { sel, decl } of rules(css)) {
    if (sel.split(",").some((s) => s.trim() === ".mg-updbanner")) {
      const z = zOf(decl);
      if (z !== null) return z;
    }
  }
  return null;
})();

describe("the update strip and the app's fixed full-screen layers", () => {
  test("the strip's own rung is where the rest of this test reasons from", () => {
    assert.equal(STRIP_Z, 509, "the strip sits at 509; a move here changes every verdict below");
  });

  test("every fixed inset:0 layer under the strip is pushed down by it", () => {
    const offset = offsetSelectors();
    const roots = fixedRoots();
    assert.ok(roots.size > 20, `expected the whole app's layers, found ${roots.size}`);

    const missing = [];
    for (const [sel, info] of roots) {
      if (sel === ".mg-updbanner" || EXEMPT.has(sel)) continue;
      if (info.z !== null && info.z >= STRIP_Z) {
        missing.push(`${sel} (${info.sheet}) ranks at ${info.z}, at or above the strip's ` +
          `${STRIP_Z}, but is not in this test's exemption list with a reason`);
        continue;
      }
      if (!offset.has(sel)) {
        missing.push(`${sel} (${info.sheet}, z-index ${info.z === null ? "auto" : info.z}) is a ` +
          "fixed inset:0 layer under the strip with no top:var(--mg-updbanner-h) in notify.css");
      }
    }
    assert.deepEqual(missing, [],
      "a fixed inset:0 root is pinned to the VIEWPORT -- no ancestor's padding moves it, so " +
      "each one must be offset under html.mg-updbanner-on or exempted here on purpose");
  });

  test("the exemptions are real layers, and each carries its reason", () => {
    const roots = fixedRoots();
    for (const [sel, why] of EXEMPT) {
      assert.ok(roots.has(sel), `${sel} is exempted but is no longer a fixed inset:0 layer`);
      assert.ok(why.length > 40, `${sel}'s exemption must say why, not just name it`);
    }
    assert.ok(EXEMPT.get(".ach-m2").includes("520"),
      "the achievement modal is exempt because it deliberately outranks the strip");
  });

  /* The three the red team actually walked. Named on purpose: the generic sweep above would
     still pass if somebody deleted these rules and widened the exemption list instead. */
  test("the Loom's two shells and the full-screen viewer are among the pushed", () => {
    const offset = offsetSelectors();
    for (const sel of [".lv-overlay", ".lm-root", ".lbx"]) {
      assert.ok(offset.has(sel),
        `${sel} must start at the strip's bottom edge -- it is the shell's own top bar ` +
        "(the phone Loom's only '< Gallery' link is inside .lm-root) and the strip takes clicks");
    }
  });

  /* The rule that made .sb-root's padding useless, stated once so it cannot be re-learned the
     hard way: an ancestor's padding never moves a position:fixed descendant. */
  test(".sb-root's padding is kept for the in-flow fallback, not counted as the Loom's answer", () => {
    const offset = offsetSelectors();
    assert.ok(offset.has(".sb-root"), "the Loom's in-flow wrapper still moves");
    const loom = loomStylesets().map((s) => s.css).join("\n");
    for (const shell of [".lv-overlay", ".lm-root"]) {
      const re = new RegExp("\\" + shell + "\\s*\\{([^}]*)\\}");
      const m = re.exec(loom);
      assert.ok(m, `${shell} should still be declared in the Loom's stylesets`);
      assert.ok(flat(m[1]).includes("position:fixed"),
        `${shell} is still position:fixed, which is why .sb-root's padding cannot move it`);
    }
  });
});

/* THE HEIGHT EVERY RULE ABOVE IS MULTIPLIED BY (2026-09-07, later the same day).

   Each offset in notify.css is `top:var(--mg-updbanner-h)`, so all of it is only as right as
   that one number. The first cut read `el.offsetHeight` synchronously in a layout effect and
   watched the default CONTENT box -- while notify.css transitions the strip's PADDING over
   180ms between 8px/8px expanded and 4px/4px folded. So re-expanding the pill published the
   new content with the old padding, ~8px short, and no ResizeObserver callback ever fixed it:
   a padding-only change does not move the content box. Every shell then sat 8px too high and
   the strip overlapped the chrome it exists to push down.

   A source guard, and here is its honest limit: BannerHost needs a DOM and a mounted React
   tree, which this repo's node runner has no renderer for. What it CAN pin is the two
   mechanics that were wrong and would rot back silently. */
describe("the height the strip publishes", () => {
  const host = read(path.join(__dirname, "../../gallery/src/notify/BannerHost.jsx"));
  const notify = stripComments(read(path.join(STYLES_DIR, "notify.css")));

  test("the strip's padding really is transitioned, which is why this matters", () => {
    assert.ok(/\.mg-updbanner\{transition:[^}]*padding/.test(notify),
      "if the padding stopped animating this guard could be dropped -- it has not");
    const pad = (sel) => {
      const m = new RegExp("(?:^|\n)\\" + sel + "\{([^}]*)\}").exec(notify);
      return m ? /padding:([^;]*)/.exec(m[1])[1] : null;
    };
    assert.notEqual(pad(".mg-updbanner"), pad(".mg-updbanner.small"),
      "expanded and folded carry different padding, so the box really does change height");
  });

  test("it measures the border box, not the content box", () => {
    assert.ok(/ro\.observe\(el,\s*\{\s*box:\s*"border-box"/.test(host),
      "a default ResizeObserver watches the content box, which a padding change never touches");
    assert.ok(host.includes("borderBoxSize"),
      "and the callback reads the border-box size the observer hands it");
    assert.ok(host.includes("getBoundingClientRect()"),
      "with the border-box rect as the fallback where borderBoxSize is missing");
  });

  test("it publishes again when the padding transition lands", () => {
    assert.ok(/addEventListener\("transitionend"/.test(host),
      "the settled height must be the last word, not the mid-flight one");
    assert.ok(/removeEventListener\("transitionend"/.test(host),
      "and the listener comes off with the strip");
  });
});
