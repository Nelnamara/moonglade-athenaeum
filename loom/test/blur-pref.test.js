import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  BLUR_OFF_KEY, NOBLUR_CLASS, isBlurOff, setBlurOff, applyBlurClass, syncBlurClass,
} from "../../gallery/src/lib/blurPref.js";

/* "BLUR BEHIND POPUPS" -- the per-device display preference (owner ruling, 2026-09-04).

   Two halves, tested two ways. The STORAGE/CLASS logic is a real import: blurPref.js takes
   no React and no DOM library, exactly so it can be exercised here (the same reason
   markdownLite.js is importable -- there is no React harness in this runner). The WIRING
   -- who calls it, and in what order -- is a source guard, the established pattern for
   this suite.

   The invariant everything below protects: the stored value means blur OFF. Blur is the
   default and the historical look, so a browser that has never seen this toggle, and one
   that refuses storage outright, must both render exactly as the app always has. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");

/** The smallest localStorage that satisfies this module, plus a switch to make it throw
    the way a private-mode / blocked-site-data browser does. */
function fakeStorage() {
  const map = new Map();
  return {
    throws: false,
    getItem(k) { if (this.throws) throw new Error("blocked"); return map.has(k) ? map.get(k) : null; },
    setItem(k, v) { if (this.throws) throw new Error("blocked"); map.set(k, String(v)); },
    raw: map,
  };
}

/** A classList stand-in with just the two verbs applyBlurClass uses. */
function fakeRoot() {
  const set = new Set();
  return {
    classList: { add: (c) => set.add(c), remove: (c) => set.delete(c), has: (c) => set.has(c) },
    set,
  };
}

describe("blurPref -- reading the preference", () => {
  afterEach(() => { delete globalThis.localStorage; });

  test("no stored value means the blur stays ON -- the default is the old behaviour", () => {
    globalThis.localStorage = fakeStorage();
    assert.equal(isBlurOff(), false);
  });

  test('only an explicit "1" turns the blur off', () => {
    const ls = fakeStorage();
    globalThis.localStorage = ls;
    ls.raw.set(BLUR_OFF_KEY, "1");
    assert.equal(isBlurOff(), true);
    // Anything else is the empty/absent case, including the string a careless writer
    // might leave behind.
    for (const junk of ["", "0", "true", "yes"]) {
      ls.raw.set(BLUR_OFF_KEY, junk);
      assert.equal(isBlurOff(), false, junk);
    }
  });

  test("storage that THROWS reads as no preference, not as a crash", () => {
    const ls = fakeStorage();
    ls.throws = true;
    globalThis.localStorage = ls;
    assert.equal(isBlurOff(), false);
  });

  test("no localStorage global at all is the same -- blur on, no throw", () => {
    // `localStorage` is simply not defined here: the bare reference throws a
    // ReferenceError, which is exactly what the try/catch is for.
    assert.equal(isBlurOff(), false);
  });
});

describe("blurPref -- writing the preference", () => {
  afterEach(() => { delete globalThis.localStorage; });

  test('off writes "1"; on writes the empty string, never a missing key', () => {
    const ls = fakeStorage();
    globalThis.localStorage = ls;
    setBlurOff(true);
    assert.equal(ls.raw.get(BLUR_OFF_KEY), "1");
    setBlurOff(false);
    assert.equal(ls.raw.get(BLUR_OFF_KEY), "");
    // ...and the empty string reads back as "blur on", which is the whole point of it
    // being allowed to sit there.
    assert.equal(isBlurOff(), false);
  });

  test("a write against blocked storage is swallowed -- the toggle still works this session", () => {
    const ls = fakeStorage();
    ls.throws = true;
    globalThis.localStorage = ls;
    assert.doesNotThrow(() => setBlurOff(true));
  });

  test("a round trip survives: off, read, on, read", () => {
    globalThis.localStorage = fakeStorage();
    setBlurOff(true);
    assert.equal(isBlurOff(), true);
    setBlurOff(false);
    assert.equal(isBlurOff(), false);
  });
});

describe("blurPref -- the class on <html>", () => {
  afterEach(() => { delete globalThis.localStorage; });

  test("applyBlurClass adds and removes exactly one class", () => {
    const root = fakeRoot();
    applyBlurClass(root, true);
    assert.ok(root.classList.has(NOBLUR_CLASS));
    assert.equal(root.set.size, 1, "one class, nothing else touched");
    applyBlurClass(root, false);
    assert.equal(root.set.size, 0);
  });

  test("the class name is the one the stylesheets answer to", () => {
    // A rename here without a rename there is silent: the toggle would flip a class
    // nothing reads. Pinned against the canonical rule in overlays.css.
    assert.equal(NOBLUR_CLASS, "mg-noblur");
    assert.match(src("styles/overlays.css"), /html\.mg-noblur \.mgv-scrim/);
  });

  test("applyBlurClass tolerates a missing root rather than throwing at boot", () => {
    assert.doesNotThrow(() => applyBlurClass(null, true));
    assert.doesNotThrow(() => applyBlurClass({}, true));
  });

  test("syncBlurClass reads storage and applies in one call, returning what it applied", () => {
    const ls = fakeStorage();
    globalThis.localStorage = ls;
    const root = fakeRoot();
    ls.raw.set(BLUR_OFF_KEY, "1");
    assert.equal(syncBlurClass(root), true);
    assert.ok(root.classList.has(NOBLUR_CLASS));
    ls.raw.set(BLUR_OFF_KEY, "");
    assert.equal(syncBlurClass(root), false);
    assert.equal(root.set.size, 0);
  });
});

/* ---------------------------------------------------------------------------------------
   THE WIRING. Source guards: nothing below can fail loudly at runtime -- the app keeps
   working, the preference just stops being honoured somewhere. --------------------------*/

const main = src("main.jsx");
const panel = src("components/ControlPanelOverlay.jsx");
const mobile = src("components/ControlMobile.jsx");

describe("the boot order guarantee", () => {
  test("main.jsx applies the class at MODULE scope, above createRoot", () => {
    const applied = main.indexOf("syncBlurClass(document.documentElement);");
    const mounted = main.indexOf("createRoot(");
    assert.ok(applied > 0, "main.jsx does not apply the preference at all");
    assert.ok(mounted > applied,
      "the class must be on <html> BEFORE React can render -- a scrim mounted first " +
      "would paint blurred for a frame with the preference off");
  });

  test("it is a top-level statement, not tucked inside a component or an effect", () => {
    // Indented, it would run on mount instead of on load -- which is a different, later
    // moment, and the one a boot-time popup (ClaimModal opens AT BOOT) beats.
    assert.match(main, /^syncBlurClass\(document\.documentElement\);$/m);
  });

  test("main.jsx imports it from the one module that owns the key", () => {
    assert.match(main, /import \{ syncBlurClass \} from "\.\/lib\/blurPref\.js";/);
  });
});

describe("the Control Panel toggle", () => {
  test("the tile is defined once and exported, so both surfaces share one behaviour", () => {
    assert.match(panel, /export function BlurToggleTile\(/);
  });

  test("it uses the Panel's own On\/Off pill and says what it does in plain words", () => {
    const tile = panel.slice(panel.indexOf("export function BlurToggleTile("),
                             panel.indexOf("export default function ControlPanelOverlay"));
    assert.match(tile, /className="mgcp-mkick">This device</);
    assert.match(tile, /Blur behind popups/);
    assert.match(tile, /mgcp-bjtoggle/, "the house toggle, not a new control");
    assert.match(tile, /aria-pressed=\{blurOn\}/);
    // The one-line note has to name the reason a person would turn it off, and say the
    // setting is per-browser -- both are the owner's ruling, not decoration.
    assert.match(tile, /slow/);
    assert.match(tile, /this browser only/);
  });

  test("the pill reads as the FEATURE's state -- On means blurred", () => {
    const tile = panel.slice(panel.indexOf("export function BlurToggleTile("),
                             panel.indexOf("export default function ControlPanelOverlay"));
    // The stored key is inverted (mg_noblur), which is exactly the trap: a tile that
    // rendered the raw stored value would show "On" for a blur that is off.
    assert.match(tile, /useState\(\(\) => !isBlurOff\(\)\)/);
    assert.match(tile, /\{blurOn \? "On" : "Off"\}/);
  });

  test("a flip writes storage AND repaints live -- a popup already open must follow", () => {
    const tile = panel.slice(panel.indexOf("export function BlurToggleTile("),
                             panel.indexOf("export default function ControlPanelOverlay"));
    assert.match(tile, /setBlurOff\(!nextOn\);/);
    assert.match(tile, /applyBlurClass\(document\.documentElement, !nextOn\);/);
  });

  test("no server round trip -- this preference never reaches config.json", () => {
    const tile = panel.slice(panel.indexOf("export function BlurToggleTile("),
                             panel.indexOf("export default function ControlPanelOverlay"));
    assert.doesNotMatch(tile, /apiPost|apiGet/,
      "per-device by ruling: one server value cannot be both the phone's and the desktop's");
  });

  test("the desktop Panel renders it in the Maintenance tile grid", () => {
    assert.match(panel, /<BlurToggleTile \/>/);
  });
});

describe("the mobile Control screen", () => {
  test("it imports the same tile rather than growing its own", () => {
    assert.match(mobile, /BlurToggleTile,?\n?\} from "\.\/ControlPanelOverlay\.jsx";/s);
    assert.match(mobile, /<BlurToggleTile className="mgcp-tile" \/>/);
  });

  test("the tile takes a className so it can drop the desktop grid span on mobile", () => {
    assert.match(panel, /export function BlurToggleTile\(\{ className = "mgcp-tile mgcp-tile4" \}\)/);
  });
});
