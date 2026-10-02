import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  LAYOUT_KEY, SAVER_KEY, SEEN_KEY, readLayout, readMarker, readSaverMode, writeLayout, writeMarker,
  writeSaverMode,
} from "../../gallery/src/lib/phonePrefs.js";

/* Session Q's three per-device values. What this file pins is the promise in lib/phonePrefs.js's header:
   reads never write, a missing key is the default and is never stored back, storage that throws changes
   nothing, and the only writers are the ones a tap (or leaving the gallery) calls. */

function recorder(seed) {
  const data = new Map(Object.entries(seed || {}));
  const log = [];
  return {
    log, data,
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => { log.push(["set", k, v]); data.set(k, String(v)); },
    removeItem: (k) => { log.push(["remove", k]); data.delete(k); },
  };
}

const throwing = {
  getItem() { throw new Error("blocked"); },
  setItem() { throw new Error("blocked"); },
};

describe("reads", () => {
  test("a fresh device answers the defaults and writes NOTHING (nothing writes on open)", () => {
    const s = recorder();
    assert.equal(readLayout(s), "grid");
    assert.equal(readSaverMode(s), "auto");
    assert.equal(readMarker(s), null);
    assert.deepEqual(s.log, []);
    assert.equal(s.data.size, 0);
  });

  test("stored values come back, and junk falls to the defaults without being rewritten", () => {
    const s = recorder({ [LAYOUT_KEY]: "feed", [SAVER_KEY]: "always",
      [SEEN_KEY]: JSON.stringify({ id: "7", ts: 5, at: 9 }) });
    assert.equal(readLayout(s), "feed");
    assert.equal(readSaverMode(s), "always");
    assert.deepEqual(readMarker(s), { id: "7", ts: 5, at: 9 });
    const junk = recorder({ [LAYOUT_KEY]: "sideways", [SAVER_KEY]: "sometimes", [SEEN_KEY]: "{oops" });
    assert.equal(readLayout(junk), "grid");
    assert.equal(readSaverMode(junk), "auto");
    assert.equal(readMarker(junk), null);
    assert.deepEqual(junk.log, []);
  });

  test("storage that throws (private mode, site data blocked) answers the defaults, never an error", () => {
    assert.equal(readLayout(throwing), "grid");
    assert.equal(readSaverMode(throwing), "auto");
    assert.equal(readMarker(throwing), null);
    assert.equal(writeLayout("feed", throwing), false);
    assert.equal(writeSaverMode("always", throwing), false);
    assert.equal(writeMarker({ id: "1", ts: 1, at: 1 }, throwing), false);
  });
});

describe("writes", () => {
  test("each writer writes exactly its own key, once, with a normalised value", () => {
    const s = recorder();
    assert.equal(writeLayout("feed", s), true);
    assert.equal(writeSaverMode("always", s), true);
    assert.equal(writeMarker({ id: "9", ts: 2, at: 3, extra: "dropped" }, s), true);
    assert.deepEqual(s.log.map((e) => e[1]), [LAYOUT_KEY, SAVER_KEY, SEEN_KEY]);
    assert.equal(s.data.get(LAYOUT_KEY), "feed");
    assert.equal(s.data.get(SAVER_KEY), "always");
    assert.deepEqual(JSON.parse(s.data.get(SEEN_KEY)), { id: "9", ts: 2, at: 3 });
  });

  test("a value that is not a real one is stored as the default, not as itself", () => {
    const s = recorder();
    writeLayout("weird", s);
    writeSaverMode("weird", s);
    assert.equal(s.data.get(LAYOUT_KEY), "grid");
    assert.equal(s.data.get(SAVER_KEY), "auto");
  });

  test("no marker, no write", () => {
    const s = recorder();
    assert.equal(writeMarker(null, s), false);
    assert.equal(writeMarker({}, s), false);
    assert.deepEqual(s.log, []);
  });
});

/* WHO MAY CALL A WRITER. The runtime half of "nothing writes on open" is the render harness (it wraps
   localStorage.setItem on a real page); this is the static half: the write functions are called only
   from the handlers below and never from a mount effect, a render body or a hook body. */
describe("who calls the writers", () => {
  const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "gallery", "src");
  const read = (rel) => readFileSync(path.join(SRC, rel), "utf8").replace(/\r\n/g, "\n");
  const code = (rel) => read(rel).replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

  test("the hooks only wrap the writers in callbacks a caller must invoke", () => {
    const hook = code("hooks/usePhonePrefs.js");
    assert.ok(/const setLayout = useCallback\(\(v\) => \{ writeLayout\(v\); \}, \[\]\);/.test(hook));
    assert.ok(/const setMode = useCallback\(\(m\) => \{ writeSaverMode\(m\); \}, \[\]\);/.test(hook));
    // never inside an effect
    assert.ok(!/useEffect\([^)]*write/.test(hook));
  });

  test("writeMarker is called from the shell's leave path only, never from a mount effect", () => {
    const app = code("components/AppMobile.jsx");
    const at = [...app.matchAll(/writeMarker\(/g)].length;
    assert.equal(at, 1, "one call site");
    // the one call sits in saveSeen, which is reached from the tab-leave effect and the hide listeners
    assert.ok(/const saveSeen = useCallback\(\(\) => \{[\s\S]*?writeMarker\(m\);[\s\S]*?\}, \[\]\);/.test(app));
    // the tab-leave effect writes only on a change AWAY from the gallery
    assert.ok(/if \(was === "gallery" && tab !== "gallery"\)/.test(app));
    // the hide listeners only ever call saveSeen while the gallery tab is the one showing
    assert.ok(/const hide = \(\) => \{ if \(tabRef\.current === "gallery"\) saveSeen\(\); \};/.test(app));
  });

  test("nothing else under gallery/src writes any of the three keys", () => {
    const hits = [];
    (function walk(dir) {
      readdirSync(dir).forEach((n) => {
        const f = path.join(dir, n);
        if (statSync(f).isDirectory()) { walk(f); return; }
        if (!/\.(js|jsx)$/.test(n)) return;
        const rel = path.relative(SRC, f).split(path.sep).join("/");
        if (rel === "lib/phonePrefs.js") return;
        const text = readFileSync(f, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
        if (/mg_phone_(layout|saver|seen)/.test(text)) hits.push(rel);
      });
    })(SRC);
    assert.deepEqual(hits, [], "the keys are private to lib/phonePrefs.js");
  });
});

