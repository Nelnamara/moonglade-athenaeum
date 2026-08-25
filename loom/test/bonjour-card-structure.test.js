import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// The Control Panel's Bonjour chip (BonjourCard.jsx). The suite has no React render harness, so
// this is a source-structure guard (the established pattern); the live render + the save
// round-trip + the QR were verified in a real browser against a mocked API, and the owner's
// real-device pass is the network-level check.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const card = readFileSync(path.join(__dirname, "../../gallery/src/components/BonjourCard.jsx"), "utf8").replace(/\r\n/g, "\n");
const overlay = readFileSync(path.join(__dirname, "../../gallery/src/components/ControlPanelOverlay.jsx"), "utf8").replace(/\r\n/g, "\n");

describe("the Bonjour chip is wired to its routes and gated to localhost", () => {
  test("reads status and writes settings through the request module, never a bare fetch", () => {
    assert.match(card, /apiGet\("\/api\/bonjour\/status"\)/);
    assert.match(card, /apiPost\("\/api\/bonjour\/settings"/);
    assert.doesNotMatch(card, /\bfetch\(/, "must ride api.js's apiGet/apiPost, not a bare fetch");
  });

  test("offers exactly the fixed name choices -- a dropdown, never a free-text name", () => {
    assert.match(card, /const NAME_CHOICES = \["Moonglade", "Athenaeum", "Moonglade Athenaeum", "The Library"\]/);
    assert.match(card, /<select/);
  });

  test("editable settings are gated on isLocal (the write route is LOCALHOST-tier)", () => {
    const idx = card.indexOf("isLocal ?");
    assert.ok(idx >= 0, "the form must be inside an isLocal branch");
    assert.ok(card.indexOf("mgcp-bjform", idx) > idx, "the edit form lives in the isLocal branch");
  });

  test("the QR uses the vendored zero-dep generator and fails soft", () => {
    assert.match(card, /import qrcode from "qrcode-generator"/);
    assert.match(card, /function qrDataUrl/);
    assert.match(card, /catch \{\s*return null;\s*\}/, "a QR failure must not throw");
  });

  test("ControlPanelOverlay renders the chip under the server controls, passing isLocal", () => {
    assert.match(overlay, /import BonjourCard from "\.\/BonjourCard\.jsx"/);
    assert.match(overlay, /<BonjourCard isLocal=\{isLocal\} \/>/);
    assert.ok(overlay.indexOf("Stop still works.") < overlay.indexOf("<BonjourCard"),
      "the chip sits AFTER the Stop/Restart controls");
    assert.ok(overlay.indexOf("<BonjourCard") < overlay.indexOf('className="mgcp-ver"'),
      "and BEFORE the version footer");
  });
});
