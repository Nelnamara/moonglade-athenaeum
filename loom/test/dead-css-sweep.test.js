import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE DEAD-CODE SWEEP'S OWN CLAIMS, CHECKED (red team 2026-09-07).

   The 2026-09-07 sweep removed the classic `.grid` card block from gallery/src/styles.css and
   left a comment naming the neighbours it did NOT remove as "still live". One of the seven --
   `.srcbadge` -- had never been wired to anything: the grid card's real source label is
   grid.css's `.mgg-pill` (Grid.jsx). So the comment certified dead code as live, which is worse
   than the dead rule itself, because the next reader trusts it.

   Nothing in this repo lints CSS against its render sites, and there is no harness that can
   render these components, so this file is the guard: it re-runs the sweep's own grep. Every
   selector the comment calls live must appear in a component, and each selector the sweep
   removed must stay gone from BOTH the stylesheets and the components -- so "put it back" and
   "certify another dead one as live" both fail here rather than silently.

   gallery/dist/ is deliberately not read: it is compiled from these sources, so a hit there is
   an echo of styles.css, never independent evidence that anything renders the class. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "../../gallery/src");

const read = (p) => readFileSync(p, "utf8").replace(/\r\n/g, "\n");

/** Every file under gallery/src whose name matches `rx`, joined. */
function sources(rx) {
  const out = [];
  (function walk(dir) {
    for (const name of readdirSync(dir)) {
      const p = path.join(dir, name);
      if (statSync(p).isDirectory()) { walk(p); continue; }
      if (rx.test(name)) out.push(read(p));
    }
  })(SRC);
  return out;
}

/* Block comments come OUT before anything is searched, on both sides. A class named in a
   comment is prose -- not a render site, and not a rule: `.srch` outlived its own class in
   Flyout.jsx's header sentence, and the sweep comment below names the very selectors it
   removed. Only code counts as evidence, in either direction. */
const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, " ");

const jsxFiles = sources(/\.(jsx|js)$/);
assert.ok(jsxFiles.length > 40, "gallery/src suddenly has almost no components -- the walk is broken");
const jsx = stripComments(jsxFiles.join("\n"));
const styles = stripComments(sources(/\.css$/).join("\n"));
const sheet = read(path.join(SRC, "styles.css"));   // comments INTACT: they are the subject

/** A class name as a whole token: `mgd-slot` must not answer a search for `gd-slot`. */
const token = (cls) => new RegExp("(^|[^\\w-])" + cls + "(?![\\w-])");
const has = (hay, cls) => token(cls).test(hay);

describe("the sweep comment's 'still live' list is true", () => {
  /* The comment itself is the subject. The names are READ OUT of it rather than hardcoded
     here -- adding a name to that sentence is precisely the mistake this catches. */
  test("every selector the comment calls live is rendered by a component", () => {
    const i = sheet.indexOf("The CLASSIC .grid card block");
    assert.ok(i > 0, "styles.css no longer carries the 2026-09-07 grid-sweep comment");
    const comment = sheet.slice(i, sheet.indexOf("*/", i));
    const j = comment.indexOf("below are");
    assert.ok(j > 0, "the sweep comment no longer names which neighbours are still live "
      + "(the list is read from the words before \"below are\")");
    const listStart = comment.lastIndexOf("wholesale\".", j);
    assert.ok(listStart > 0 && listStart < j,
      "cannot find the start of the survivor list in the sweep comment");
    const named = (comment.slice(listStart + 11, j).match(/\.[a-z][\w-]*/g) || []).map((s) => s.slice(1));
    assert.ok(named.length >= 5,
      "read only " + named.length + " selectors out of the survivor list -- expected the six "
      + "the sweep left standing");
    const dead = named.filter((c) => !has(jsx, c));
    assert.deepEqual(dead, [],
      "styles.css's sweep comment calls these \"still live\", but nothing in gallery/src "
      + "renders them: " + dead.map((c) => "." + c).join(", ")
      + " -- either wire them up or sweep them with the rest");
  });
});

describe("the swept selectors stay swept", () => {
  /* One entry per selector removed after proving it dead. Each must stay absent from the
     components (nothing renders it) AND from the stylesheets (nothing styles it), with the
     class that DID survive named beside it so a reader can see what to use instead. */
  const SWEPT = [
    ["srcbadge", "mgg-pill", "the grid card's source label (grid.css, Grid.jsx)"],
  ];

  for (const [dead, alive, where] of SWEPT) {
    test("." + dead + " is gone -- " + where + " is ." + alive, () => {
      assert.ok(!has(jsx, dead),
        "a component renders ." + dead + " again; if that is deliberate, the rule and this "
        + "entry both need to come back");
      assert.ok(!has(styles, dead),
        "." + dead + " is back in a stylesheet with nothing rendering it");
      assert.ok(has(jsx, alive),
        "." + alive + " -- the live class ." + dead + " was swept in favour of -- is itself no "
        + "longer rendered, so this entry's reasoning has gone stale");
    });
  }
});
