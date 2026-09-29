import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* The masked-feats wiring, pinned at the source (Session G). The components are React and
   this suite has no renderer, so what is asserted here is the shape of the wiring that the
   pure cores (masked-feats-core.test.js) cannot see: that the veil is drawn only through
   veilState (so search hides it and only the server's own mask route is drawn), that the two
   Folios draw the feats' count as "found" and never out of a total, and that nothing in the
   client builds a key or a request from a feat's identity. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8");

const hook = src("hooks/useFolio.js");
const desk = src("components/FolioOverlay.jsx");
const phone = src("components/FolioMobile.jsx");
const parts = src("folio/MaskedFeatParts.jsx");

describe("the veil is drawn only through veilState", () => {
  test("useFolio derives it from the payload's feats object, the search text and the Unleash switch", () => {
    assert.match(hook, /veilState\(featsPayload, \{ query: qlc, unleashed \}\)/);
    assert.match(hook, /featsPayload = \(data && data\.feats\)/);
  });

  test("both Folios draw the veil only when veil.show, and the gold line only when veil.allFound", () => {
    for (const [name, file] of [["desktop", desk], ["phone", phone]]) {
      assert.match(file, /veil\.show &&/, name);
      assert.match(file, /veil\.allFound &&/, name);
      assert.ok(!/feats\.masked/.test(file.replace(/\/\*[\s\S]*?\*\//g, "")), name + " reads the raw masked object");
    }
  });

  test("the veil components are given a mask URL and a riddle, nothing that names a feat", () => {
    for (const file of [desk, phone]) {
      for (const m of file.matchAll(/<(VeilCard|VeilBanner)\s([^>]*)\/>/g)) {
        assert.equal(m[2].replace(/\{[^}]*\}/g, "{}").trim().split(/\s+/).sort().join(" "),
          "maskUrl={} riddle={} waiting={}");
      }
    }
    assert.ok(!/\b(name|id|desc|badge)\b\s*[:=]/.test(parts.split("export function RevealLayers")[0].replace(/\/\*[\s\S]*?\*\//g, "")
      .replace(/className="[^"]*"/g, "")), "the veil parts take no feat identity");
  });

  test("the mask is applied by one CSS declaration from a custom property", () => {
    assert.match(parts, /"--mgfm-mask": "url\(" \+ maskUrl \+ "\)"/);
  });
});

describe("the feats' count says found, never out of", () => {
  test("no feats count is drawn as earned/total in either Folio", () => {
    for (const [name, file] of [["desktop", desk], ["phone", phone]]) {
      assert.ok(!/earnedFeats\}\s*\/\s*\{[^}]*totalFeats/.test(file), name);
      assert.ok(!/vm\.earnedFeats[^\n]*\/[^\n]*vm\.totalFeats/.test(file), name);
      assert.match(file, /featCountText/, name);
      assert.match(file, /foundText\(foundCount, veil\.allFound\)/, name);
    }
  });
});

describe("nothing is built from a feat's identity", () => {
  test("the seen record is one fixed key holding ids the server already sent as earned", () => {
    assert.match(hook, /prefs\.get\(SEEN_KEY, undefined\)/);
    assert.match(hook, /prefs\.set\(SEEN_KEY, nextSeen\(seenRaw, feats\)\)/);
    assert.ok(!/prefs\.(get|set)\([^)]*\+/.test(hook), "a pref key is built from something");
  });

  test("a deep link carries only an earned feat's id, and it is checked against the earned list", () => {
    assert.match(hook, /feats\.some\(\(a\) => a\.id === focusId && a\.earned\)/);
  });

  test("the client never fetches by feat: the only request a feat causes is the server's own mask URL, as CSS", () => {
    for (const file of [hook, desk, phone, parts]) {
      assert.ok(!/apiGet\([^)]*(feat|mask)/i.test(file.replace(/\/\*[\s\S]*?\*\//g, "")));
    }
  });
});

describe("nothing writes on open", () => {
  test("the seen write waits for the reveal's last beat, on screen", () => {
    const write = hook.slice(hook.indexOf("The one-time \"seen\" write"), hook.indexOf("One card's reveal frame"));
    assert.match(write, /REVEAL\.VEIL/);
    assert.match(write, /wroteRef\.current\.has/);
  });
});
