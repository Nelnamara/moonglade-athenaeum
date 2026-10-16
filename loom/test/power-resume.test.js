import { test, describe, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import {
  POWER_NOTE_KEY, POWER_NOTE_TTL_MS, clearPowerNote, notePower, powerToResume, readPowerNote,
} from "../../gallery/src/lib/powerResume.js";

// #84: the Control Panel's Stop/Restart reconnect watch lived only in the mounted hook, so a panel
// reopened mid-wait showed an idle panel. The server now says a stop or restart is under way
// (`power` on /api/panel/status) and the hook resumes the ping watch from it on mount, desktop and
// phone alike (one hook, two consumers).

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");

function fakeStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)); },
    removeItem: (k) => { m.delete(k); },
    _m: m,
  };
}

describe("powerToResume: what a freshly mounted panel does with its /api/panel/status read", () => {
  test("the server names a stop or a restart under way: resume exactly that watch", () => {
    assert.equal(powerToResume({ status: "idle", power: "restart" }, ""), "restart");
    assert.equal(powerToResume({ status: "idle", power: "stop" }, "restart"), "stop");   // the server wins over the note
  });

  test("nothing under way and the server answering: no watch, whatever an old note says", () => {
    assert.equal(powerToResume({ status: "idle", power: "" }, "restart"), "");
    assert.equal(powerToResume({ status: "idle" }, "stop"), "");
  });

  test("the read dropped (the server is down) and this tab just asked for a stop/restart: resume from the note", () => {
    assert.equal(powerToResume({ error: "network error: Failed to fetch" }, "restart"), "restart");
    assert.equal(powerToResume({ error: "network error: unreachable" }, "stop"), "stop");
  });

  test("a dropped read with no note is just an offline panel, not a restart", () => {
    assert.equal(powerToResume({ error: "network error: Failed to fetch" }, ""), "");
  });

  test("a server that answers with an error (401, 500) is not a server that is down", () => {
    assert.equal(powerToResume({ error: "401 Unauthorized", http_status: 401 }, "restart"), "");
    assert.equal(powerToResume({ error: "500 Internal Server Error", http_status: 500 }, "stop"), "");
  });

  test("a mode it does not know never starts a watch", () => {
    assert.equal(powerToResume({ power: "reboot" }, ""), "");
    assert.equal(powerToResume({ error: "network error: x" }, "reboot"), "");
    assert.equal(powerToResume(null, "restart"), "");
  });
});

describe("the browser-side note", () => {
  let saved;
  beforeEach(() => { saved = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage"); });
  afterEach(() => {
    if (saved) Object.defineProperty(globalThis, "sessionStorage", saved);
    else delete globalThis.sessionStorage;
  });
  const install = (s) => Object.defineProperty(globalThis, "sessionStorage", { value: s, configurable: true, writable: true });

  test("a click leaves a note that reads back as its mode, and clears", () => {
    install(fakeStorage());
    notePower("restart", 1000);
    assert.equal(readPowerNote(2000), "restart");
    clearPowerNote();
    assert.equal(readPowerNote(2000), "");
  });

  test("a note expires, so a stale one cannot start a watch long after the fact", () => {
    install(fakeStorage());
    notePower("stop", 1000);
    assert.equal(readPowerNote(1000 + POWER_NOTE_TTL_MS), "stop");
    assert.equal(readPowerNote(1000 + POWER_NOTE_TTL_MS + 1), "");
  });

  test("junk, an unknown mode or a note from the future reads as none", () => {
    const s = fakeStorage();
    install(s);
    s.setItem(POWER_NOTE_KEY, "{not json");
    assert.equal(readPowerNote(), "");
    s.setItem(POWER_NOTE_KEY, JSON.stringify({ mode: "reboot", at: 1000 }));
    assert.equal(readPowerNote(1500), "");
    s.setItem(POWER_NOTE_KEY, JSON.stringify({ mode: "stop", at: 9000 }));
    assert.equal(readPowerNote(1500), "");
    notePower("reboot", 1000);                                   // an unknown mode is never written
    assert.equal(s.getItem(POWER_NOTE_KEY), JSON.stringify({ mode: "stop", at: 9000 }));
  });

  test("blocked storage (private window) is survivable: nothing throws, the note reads as none", () => {
    install({
      getItem() { throw new Error("blocked"); },
      setItem() { throw new Error("blocked"); },
      removeItem() { throw new Error("blocked"); },
    });
    assert.doesNotThrow(() => notePower("restart"));
    assert.doesNotThrow(() => clearPowerNote());
    assert.equal(readPowerNote(), "");
  });

  test("no sessionStorage at all (server render, tests) is the same", () => {
    delete globalThis.sessionStorage;
    assert.doesNotThrow(() => notePower("stop"));
    assert.equal(readPowerNote(), "");
  });
});

describe("the hook resumes the watch on mount and never sends the stop or restart again", () => {
  const hook = src("gallery/src/hooks/useControlPanel.js");

  test("the mount check reads the marker, ahead of the running-job check", () => {
    const mount = hook.slice(hook.indexOf('apiGet("/api/panel/status")'));
    const resume = mount.indexOf("powerToResume(d, readPowerNote())");
    assert.ok(resume > 0, "the mount check calls powerToResume");
    assert.ok(mount.indexOf("resumePower(resume)") > resume);
    assert.ok(resume < mount.indexOf('d.status === "running"'), "the resume check comes before the running-job check");
  });

  test("a resumed run goes straight to the watch: doPower returns before either POST", () => {
    const doPower = hook.slice(hook.indexOf("const doPower = async"), hook.indexOf("const _watch ="));
    const resumed = doPower.indexOf("resumedPowerRef.current");
    assert.ok(resumed > 0);
    assert.ok(doPower.indexOf("_watch(power !== \"stop\")") > resumed);
    assert.ok(doPower.indexOf("return;") > resumed && doPower.indexOf("return;") < doPower.indexOf("/api/server/stop"));
    assert.ok(doPower.indexOf("return;") < doPower.indexOf("/api/server/restart"));
  });

  test("a real click clears the resumed flag and leaves the note once the server accepted it", () => {
    assert.match(hook, /const startPower = \(mode\) => \{\n\s+powerCancelledRef\.current = false;\n\s+resumedPowerRef\.current = false;/);
    assert.match(hook, /notePower\("stop"\);\n\s+_watch\(false\);/);
    assert.match(hook, /notePower\("restart"\);\n\s+_watch\(true\);/);
  });

  test("the server answering again ends the wait, and the note with it", () => {
    const watch = hook.slice(hook.indexOf("const _watch ="), hook.indexOf("pingRef.current = setInterval(() => {\n      tries++;"));
    assert.match(watch, /const back = \(\) => \{\n\s+clearInterval\(pingRef\.current\);\n\s+clearPowerNote\(\);/);
  });

  test("closing the power modal drops the note", () => {
    const close = hook.slice(hook.indexOf("const closePower"), hook.indexOf("const skins ="));
    assert.match(close, /clearPowerNote\(\)/);
  });

  test("both surfaces consume this one hook, so desktop and phone resume alike", () => {
    for (const f of ["gallery/src/components/ControlPanelOverlay.jsx", "gallery/src/components/ControlMobile.jsx"]) {
      const s = src(f);
      assert.match(s, /useControlPanel\(/, f);
      assert.match(s, /<PowerModal mode=\{power\}/, f);
    }
  });
});
