import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  BEAT_KEY, BEAT, beatPlan, beatPhase, holdsOnMaintenance, tabVisible, tileState,
} from "../../gallery/src/lib/brandingBeatCore.js";
import { prefKeyProblem } from "../../gallery/src/hooks/accountPrefsStore.js";

/* THE BRANDING BEAT (Session L, decision 5): the first Control Panel open after the unlock
   cross-fades the tile (0.4 s), then slides the tab in with a gold shimmer (0.8 s); reduced
   motion just presents both; the seen flag is the account's. The motion is CSS, so half of
   what is pinned here is that the CSS and the core say the same numbers. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").replace(/\r\n/g, "\n");

describe("whether the beat plays", () => {
  const P = (o) => beatPlan({ unlocked: true, status: "ready", seen: false, reduced: false, ...o });

  test("its key is one the account store accepts and is not a per-browser thing", () => {
    assert.equal(prefKeyProblem(BEAT_KEY), "");
    assert.match(BEAT_KEY, /^seen\./);
  });

  test("first open after the unlock, with motion: it plays", () => {
    assert.equal(P({}), "play");
  });

  test("first open, reduced motion: both simply present, flag still set", () => {
    assert.equal(P({ reduced: true }), "rest");
  });

  test("already seen: nothing plays, in either motion setting", () => {
    assert.equal(P({ seen: true }), "seen");
    assert.equal(P({ seen: true, reduced: true }), "seen");
  });

  test("before the unlock there is no beat and no tab", () => {
    assert.equal(P({ unlocked: false }), "off");
    assert.equal(P({ unlocked: false, seen: true }), "off");
  });

  test("while the account has not answered, the new pieces wait; an account that cannot answer skips the beat", () => {
    for (const status of ["idle", "loading"]) assert.equal(P({ status }), "wait");
    assert.equal(P({ status: "error" }), "seen", "never hold the tab hostage to a store that is down");
  });

  test("only a real true is 'seen'", () => {
    for (const seen of [1, "true", null, undefined, {}]) assert.equal(P({ seen }), "play");
  });
});

describe("the timeline", () => {
  test("0.4 s for the tile, 0.8 s for the tab, 1.2 s in all", () => {
    assert.deepEqual(BEAT, { TILE_MS: 400, TAB_MS: 800, TOTAL_MS: 1200 });
    assert.equal(BEAT.TILE_MS + BEAT.TAB_MS, BEAT.TOTAL_MS);
    assert.ok(BEAT.TOTAL_MS <= 1200, "the handoff's ceiling for the celebration's button is 1.2 s");
  });

  test("phases fall on the edges", () => {
    assert.equal(beatPhase(0), "tile");
    assert.equal(beatPhase(399), "tile");
    assert.equal(beatPhase(400), "tab");
    assert.equal(beatPhase(1199), "tab");
    assert.equal(beatPhase(1200), "done");
    assert.equal(beatPhase(-5), "tile");
    assert.equal(beatPhase(NaN), "tile");
  });

  test("the tab is drawn only in its own half and after; the tile fades in only in the first", () => {
    assert.equal(tabVisible("play", "tile"), false);
    assert.equal(tabVisible("play", "tab"), true);
    assert.equal(tabVisible("play", "done"), true);
    assert.equal(tabVisible("wait", "tile"), false);
    assert.equal(tabVisible("off", "done"), false);
    for (const plan of ["seen", "rest"]) assert.equal(tabVisible(plan, "tile"), true);
    assert.equal(tileState("wait", "tile"), "hold");
    assert.equal(tileState("play", "tile"), "in");
    for (const ph of ["tab", "done"]) assert.equal(tileState("play", ph), "rest");
    for (const plan of ["seen", "rest", "off"]) assert.equal(tileState(plan, "tile"), "rest");
  });

  test("a panel opened on Branding holds on Maintenance for the beat, and not otherwise", () => {
    assert.equal(holdsOnMaintenance("play", "tile"), true);
    assert.equal(holdsOnMaintenance("play", "tab"), true);
    assert.equal(holdsOnMaintenance("play", "done"), false);
    assert.equal(holdsOnMaintenance("wait", "tile"), true);
    for (const plan of ["seen", "rest", "off"]) assert.equal(holdsOnMaintenance(plan, "tile"), false);
  });
});

describe("the CSS says the same numbers", () => {
  const css = src("styles/control-panel.css");
  const block = (name) => {
    const m = css.match(new RegExp("\\." + name + "\\s*\\{[^}]*\\}"));
    assert.ok(m, "no ." + name + " rule");
    return m[0];
  };

  test("the tile cross-fades in 0.4 s, the ghost out in 0.4 s", () => {
    assert.match(block("mgcp-tile-in"), /animation:\s*mgcp-beat-in \.4s/);
    assert.match(block("mgcp-tileghost"), /animation:\s*mgcp-beat-out \.4s/);
  });

  test("the tab arrives in 0.8 s, ease-out, and its shimmer runs the same 0.8 s", () => {
    assert.match(block("mgcp-tab-arrive"), /animation:\s*mgcp-tab-arrive \.8s ease-out/);
    assert.match(css, /\.mgcp-tab-arrive::after\s*\{[^}]*animation:\s*mgcp-tab-shimmer \.8s ease-out/);
  });

  test("the gold is the handoff's own", () => {
    assert.match(css, /rgba\(212,175,55,\.5\)/);
    assert.match(css, /box-shadow:\s*0 0 12px rgba\(212,175,55,\.45\)/);
  });

  test("reduced motion has a backstop", () => {
    assert.match(css, /@media \(prefers-reduced-motion: reduce\) \{\s*\.mgcp-tile-in, \.mgcp-tab-arrive, \.mgcp-tab-arrive::after \{ animation: none; \}/);
  });
});

describe("the wiring", () => {
  const hook = src("hooks/useBrandingBeat.js");
  const cp = src("components/ControlPanelOverlay.jsx");

  test("the flag is written when the beat ENDS (or at once under reduced motion), never on open", () => {
    const sets = hook.match(/prefs\.set\(BEAT_KEY, true\)/g) || [];
    assert.equal(sets.length, 2);
    assert.match(hook, /if \(plan === "rest"\) \{ prefs\.set\(BEAT_KEY, true\); return undefined; \}/);
    assert.match(hook, /setTimeout\(\(\) => \{ setPhase\("done"\); prefs\.set\(BEAT_KEY, true\); \}, BEAT\.TOTAL_MS\)/);
    assert.match(hook, /setTimeout\(\(\) => setPhase\("tab"\), BEAT\.TILE_MS\)/);
    assert.match(hook, /return \(\) => \{ clearTimeout\(t1\); clearTimeout\(t2\); \}/,
      "a panel closed halfway has not shown the beat: no flag");
  });

  test("the panel draws a held tab, and the shipped guards still read the same words", () => {
    assert.match(cp, /const tab = beat\.holds && tabState === "brand" \? "maint" : tabState;/);
    assert.match(cp, /brandingUnlocked && \(\s*<button type="button" className=\{beat\.tabArriving/);
    assert.match(cp, /tab === "brand" && brandingUnlocked/);
  });

  test("the pointer tile is one component the beat and the shipped panel share", () => {
    assert.match(cp, /<BrandingPointerTile state=\{beat\.tile\} onOpen=\{\(\) => setTab\("brand"\)\} \/>/);
    assert.match(cp, /state === "in" \? \(\s*<div className="mgcp-tileghost" aria-hidden="true">/);
  });

  test("the celebration's button still asks for the Branding tab through the shell's own request", () => {
    const clip = src("moments/ClipMoment.jsx");
    assert.match(clip, /const opened = openPanelHere\("brand"\);/);
    assert.match(clip, /finish\("button", opened \? null : \(\) => carryPanelTab\("brand"\)\);/);
  });
});
