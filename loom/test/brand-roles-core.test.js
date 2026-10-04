import { test, describe } from "node:test";
import assert from "node:assert/strict";

/* The Branding tab's named roles (Session X, Branding Roles Handoff), client side: the rules the
   editor ticks live before anything is uploaded. The server decides (tests/test_branding_roles.py
   holds its half); these hold that this side says the same words about the same facts. */

import {
  imageUrl, phoneState, ratioLabel, refusalText, restoreAsk, rowSub, seeThroughFraction,
  sniffFormat, specFailures, specLine, ticks, unreadableNote,
} from "../../gallery/src/lib/brandRolesCore.js";

const T = { see_through_min: 0.01, aspect_tolerance: 0.02, transparent: true };
const LOGIN = { ...T, formats: ["WEBP", "PNG"], aspect: [3, 4], min_axis: "height", min_px: 600 };
const SQUARE = (px) => ({ ...T, formats: ["PNG"], aspect: [1, 1], min_axis: "side", min_px: px });
const facts = (o) => ({ format: "PNG", w: 256, h: 256, see_through: 0.4, ...o });

describe("the spec line (the gold mono line)", () => {
  test("format · transparency · shape · minimum size", () => {
    assert.equal(specLine(LOGIN), "WEBP/PNG · transparent · 3:4 · ≥ 600 px tall");
    assert.equal(specLine(SQUARE(128)), "PNG · transparent · square · ≥ 128 px");
  });
  test("the phone's role screen drops 'tall'", () => {
    assert.equal(specLine(LOGIN, { phone: true }), "WEBP/PNG · transparent · 3:4 · ≥ 600 px");
  });
});

describe("the rules (the same ones the server runs)", () => {
  test("a file that meets the spec has nothing to fix", () => {
    assert.deepEqual(specFailures(SQUARE(256), facts()), []);
    assert.deepEqual(specFailures(LOGIN, facts({ format: "WEBP", w: 450, h: 600 })), []);
  });
  test("the boundaries pass: exactly the minimum, and a shape a few percent off", () => {
    assert.deepEqual(specFailures(SQUARE(64), facts({ w: 64, h: 64 })), []);
    assert.deepEqual(specFailures(SQUARE(128), facts({ w: 566, h: 560 })), []);       // the owner's spinner
    assert.equal(specFailures(SQUARE(64), facts({ w: 128, h: 119 })).map((f) => f.rule).join(), "aspect");
  });
  test("each rule names what it needed and what it measured", () => {
    assert.deepEqual(specFailures(SQUARE(256), facts({ format: "JPEG", see_through: 0 })), [
      { rule: "format", need: "PNG", got: "JPEG" },
      { rule: "transparent", need: "a transparent background", got: "opaque" },
    ]);
    assert.deepEqual(specFailures(LOGIN, facts({ format: "WEBP", w: 800, h: 800 })), [
      { rule: "aspect", need: "3:4", got: "1:1" },
    ]);
    assert.deepEqual(specFailures(SQUARE(64), facts({ w: 48, h: 48 })), [
      { rule: "size", need: "at least 64 px", got: "48 px" },
    ]);
    assert.deepEqual(specFailures(LOGIN, facts({ w: 449, h: 598 })), [
      { rule: "size", need: "at least 600 px tall", got: "598 px tall" },
    ]);
  });
  test("a trace of see-through is still opaque to the rule, and says how much it had", () => {
    const [f] = specFailures(SQUARE(64), facts({ see_through: 0.004 }));
    assert.deepEqual(f, { rule: "transparent", need: "a transparent background", got: "0.4% see-through" });
  });
  test("the shape in words", () => {
    assert.equal(ratioLabel(1000, 1000), "1:1");
    assert.equal(ratioLabel(1536, 1024), "3:2");
    assert.equal(ratioLabel(900, 1200), "3:4");
    assert.equal(ratioLabel(1920, 1080), "16:9");
    assert.equal(ratioLabel(1007, 600), "1.68:1");
  });
});

describe("the live ticks", () => {
  test("the handoff's line: ✓ WEBP ✓ transparent ✕ 3:4 (got 1:1) ✓ ≥ 600 px", () => {
    const t = ticks(LOGIN, facts({ format: "WEBP", w: 800, h: 800 }));
    assert.deepEqual(t.map((x) => (x.ok ? "✓ " : "✕ ") + x.text),
      ["✓ WEBP", "✓ transparent", "✕ 3:4 (got 1:1)", "✓ ≥ 600 px"]);
  });
  test("a wrong format ticks the format and, being opaque, the transparency too", () => {
    const t = ticks(SQUARE(256), facts({ format: "JPEG", see_through: 0 }));
    assert.deepEqual(t.map((x) => (x.ok ? "✓ " : "✕ ") + x.text),
      ["✕ PNG (got JPEG)", "✕ transparent (got opaque)", "✓ square", "✓ ≥ 256 px"]);
  });
});

describe("the refusal says what the server's says", () => {
  // the same sentences tests/test_branding_roles.py pins
  test("one broken rule", () => {
    assert.equal(refusalText("Login companion", [{ rule: "aspect", need: "3:4", got: "1:1" }]),
      "Refused: the Login companion must be 3:4. This one is 1:1. Your current art is unchanged.");
    assert.equal(refusalText("Power poses", [{ rule: "transparent", need: "a transparent background", got: "opaque" }]),
      "Refused: the Power poses must have a transparent background. This one is opaque. Your current art is unchanged.");
    assert.equal(refusalText("Reward icons", [{ rule: "size", need: "at least 64 px", got: "48 px" }]),
      "Refused: the Reward icons must be at least 64 px. This one is 48 px. Your current art is unchanged.");
  });
  test("several, as pairs", () => {
    assert.equal(refusalText("Power poses", specFailures(SQUARE(256), facts({ format: "JPEG", see_through: 0 }))),
      "Refused: the Power poses must be PNG (this one is JPEG) and have a transparent background "
      + "(this one is opaque). Your current art is unchanged.");
    assert.equal(refusalText("Job tracker mascots", specFailures(SQUARE(128), facts({ w: 96, h: 64 }))),
      "Refused: the Job tracker mascots must be square (this one is 3:2) and at least 128 px "
      + "(this one is 64 px). Your current art is unchanged.");
  });
});

describe("measuring on the device", () => {
  test("the format is the bytes', not the name's", () => {
    assert.equal(sniffFormat([0x89, 0x50, 0x4E, 0x47, 13, 10, 26, 10]), "PNG");
    assert.equal(sniffFormat([...Buffer.from("RIFF\0\0\0\0WEBPVP8 ")]), "WEBP");
    assert.equal(sniffFormat([0xFF, 0xD8, 0xFF, 0xE0]), "JPEG");
    assert.equal(sniffFormat([...Buffer.from("GIF89a")]), "GIF");
    assert.equal(sniffFormat([...Buffer.from("MZ not a picture")]), "");
    assert.equal(sniffFormat(null), "");
  });
  test("the see-through share counts pixels more than half clear", () => {
    const px = (a) => [10, 20, 30, a];
    const data = Uint8ClampedArray.from([...px(0), ...px(127), ...px(128), ...px(255)]);
    assert.equal(seeThroughFraction(data), 0.5);
    assert.equal(seeThroughFraction(new Uint8ClampedArray(0)), 0);
    assert.equal(seeThroughFraction(Uint8ClampedArray.from([...px(255), ...px(255)])), 0);
  });
});

describe("what a row says about itself", () => {
  const img = (key, label, o = {}) => ({ key, label, url: "/branding/" + key + ".png", yours: false, unreadable: false, v: 0, ...o });
  const role = (images, o = {}) => ({ slot: "s", name: "Power poses", where: "the restart and shutdown screens", images, ...o });
  test("a single-image role names where it shows", () => {
    assert.equal(rowSub(role([img("companion", "Companion")], { where: "the sign-in page" })), "the sign-in page");
    assert.equal(phoneState(role([img("companion", "Companion")])), "default");
    assert.equal(phoneState(role([img("companion", "Companion", { yours: true })])), "yours");
  });
  test("a multi-image role lists its images and counts the ones that are yours", () => {
    const r = role([img("restart", "Restart", { yours: true }), img("shutdown", "Shutdown")]);
    assert.equal(rowSub(r), "restart · shutdown · 1 of 2 yours");
    assert.equal(phoneState(r), "1 of 2 yours");
    assert.equal(rowSub(role([img("restart", "Restart"), img("shutdown", "Shutdown")])), "restart · shutdown");
    assert.equal(phoneState(role([img("restart", "Restart"), img("shutdown", "Shutdown")])), "default");
  });
  test("an override's URL carries its stamp, so a changed file is fetched afresh", () => {
    assert.equal(imageUrl(img("a", "A", { yours: true, v: 1234 })), "/branding/a.png?v=1234");
    assert.equal(imageUrl(img("a", "A")), "/branding/a.png");
  });
  test("an unreadable override gets the peach note", () => {
    assert.equal(unreadableNote(role([img("a", "A", { yours: true, unreadable: true })])),
      "Your file couldn't be read; showing the default.");
    assert.equal(unreadableNote(role([img("a", "A", { yours: true })])), "");
  });
  test("the one-time ask names the role, and the image when there are several", () => {
    assert.equal(restoreAsk(role([img("companion", "Companion")], { name: "Login companion" }), { label: "Companion" }),
      "Go back to the default Login companion?");
    assert.equal(restoreAsk(role([img("restart", "Restart"), img("shutdown", "Shutdown")]), { label: "Restart" }),
      "Go back to the default Power poses (restart)?");
  });
});
