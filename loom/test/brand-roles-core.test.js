import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

/* The Branding tab's named roles (Session X, Branding Roles Handoff), client side: the rules the
   editor ticks live before anything is uploaded. The server decides (tests/test_branding_roles.py
   holds its half); these hold that this side says the same words about the same facts. */

import {
  imageUrl, phoneState, ratioLabel, refusalText, restoreAsk, rowSub, seeThroughFraction,
  sniffAnimated, sniffFormat, specFailures, specLine, ticks, unreadableNote,
} from "../../gallery/src/lib/brandRolesCore.js";

/* The spec an IMAGE's override must meet (the server's role_image_spec, handed over in the Branding
   payload): the role's formats and drawn minimum, with the SHAPE the pack default's (within 8 %), the
   minimum lowered to the default's own where that is smaller, and animation only where allowed. */
const T = { see_through_min: 0.01, aspect_tolerance: 0.08, transparent: true, animated_formats: [] };
const LOGIN = { ...T, formats: ["WEBP", "PNG"], animated_formats: ["WEBP"], aspect: [488, 480],
  min_axis: "height", min_px: 480 };
const SQUARE = (px) => ({ ...T, formats: ["PNG"], aspect: [1, 1], min_axis: "side", min_px: px });
const DONE = { ...T, formats: ["PNG"], aspect: [329, 364], min_axis: "side", min_px: 128 };   // taller than wide
const facts = (o) => ({ format: "PNG", w: 256, h: 256, see_through: 0.4, animated: false, ...o });

describe("the spec line (the gold mono line): the effective rule", () => {
  test("format · transparency · shape · minimum size", () => {
    assert.equal(specLine(LOGIN), "WEBP/PNG · transparent · about square · ≥ 480 px tall · animated WebP ok");
    assert.equal(specLine(SQUARE(128)), "PNG · transparent · about square · ≥ 128 px");
  });
  test("a shape that is not square is named as the pack's own, about", () => {
    assert.equal(specLine(DONE), "PNG · transparent · about 9:10 · ≥ 128 px");
    assert.equal(specLine({ ...DONE, aspect: [324, 365] }), "PNG · transparent · about 8:9 · ≥ 128 px");
    assert.equal(specLine({ ...DONE, aspect: [402, 356] }), "PNG · transparent · about 9:8 · ≥ 128 px");
    assert.equal(specLine({ ...SQUARE(64), aspect: [128, 119] }), "PNG · transparent · about square · ≥ 64 px");
  });
  test("the phone's role screen drops 'tall'", () => {
    assert.equal(specLine(LOGIN, { phone: true }), "WEBP/PNG · transparent · about square · ≥ 480 px · animated WebP ok");
  });
});

describe("the rules (the same ones the server runs)", () => {
  test("a file that meets the spec has nothing to fix", () => {
    assert.deepEqual(specFailures(SQUARE(256), facts()), []);
    assert.deepEqual(specFailures(LOGIN, facts({ format: "WEBP", w: 500, h: 490, animated: true })), []);
  });
  test("the pack's own art passes its own rule, odd shapes and animation included", () => {
    assert.deepEqual(specFailures(LOGIN, facts({ format: "WEBP", w: 488, h: 480, animated: true })), []);
    assert.deepEqual(specFailures(DONE, facts({ w: 329, h: 364 })), []);
    assert.deepEqual(specFailures({ ...SQUARE(64), aspect: [128, 119] }, facts({ w: 128, h: 119 })), []);
  });
  test("the boundaries pass: exactly the minimum, and a shape within 8 % of the default's", () => {
    assert.deepEqual(specFailures(SQUARE(64), facts({ w: 64, h: 64 })), []);
    assert.deepEqual(specFailures(SQUARE(128), facts({ w: 566, h: 560 })), []);       // the owner's spinner
    assert.deepEqual(specFailures(SQUARE(64), facts({ w: 128, h: 119 })), [], "7 % wider is inside 8 %");
    assert.deepEqual(specFailures(LOGIN, facts({ w: 480, h: 480 })), []);              // exactly 480 tall
    assert.equal(specFailures(SQUARE(64), facts({ w: 143, h: 128 })).map((f) => f.rule).join(), "aspect");   // 11.7 %
  });
  test("each rule names what it needed and what it measured", () => {
    assert.deepEqual(specFailures(SQUARE(256), facts({ format: "JPEG", see_through: 0 })), [
      { rule: "format", need: "PNG", got: "JPEG" },
      { rule: "transparent", need: "a transparent background", got: "opaque" },
    ]);
    assert.deepEqual(specFailures(LOGIN, facts({ format: "WEBP", w: 600, h: 800 })), [
      { rule: "aspect", need: "about square", got: "3:4" },
    ]);
    assert.deepEqual(specFailures(DONE, facts({ w: 256, h: 256 })), [
      { rule: "aspect", need: "about 9:10", got: "1:1" },
    ]);
    assert.deepEqual(specFailures(SQUARE(64), facts({ w: 48, h: 48 })), [
      { rule: "size", need: "at least 64 px", got: "48 px" },
    ]);
    assert.deepEqual(specFailures(LOGIN, facts({ w: 470, h: 470 })), [
      { rule: "size", need: "at least 480 px tall", got: "470 px tall" },
    ]);
  });
  test("animation is a rule: allowed for the format the role allows, a failure everywhere else", () => {
    assert.deepEqual(specFailures(SQUARE(64), facts({ animated: true })), [
      { rule: "animation", need: "a still picture", got: "animated" },
    ]);
    assert.deepEqual(specFailures(LOGIN, facts({ format: "PNG", w: 500, h: 490, animated: true })), [
      { rule: "animation", need: "a still picture", got: "animated" },
    ], "an animated PNG is not the animated WebP the login companion may be");
    assert.deepEqual(specFailures(SQUARE(64), facts({ format: "WEBP", animated: true })).map((f) => f.rule),
      ["format", "animation"]);
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
  test("the handoff's line, with the effective rule: ✓ PNG ✓ transparent ✕ about square (got 3:4) ✓ ≥ 480 px", () => {
    const t = ticks(LOGIN, facts({ format: "PNG", w: 600, h: 800 }));
    assert.deepEqual(t.map((x) => (x.ok ? "✓ " : "✕ ") + x.text),
      ["✓ PNG", "✓ transparent", "✕ about square (got 3:4)", "✓ ≥ 480 px"]);
  });
  test("a wrong format ticks the format and, being opaque, the transparency too", () => {
    const t = ticks(SQUARE(256), facts({ format: "JPEG", see_through: 0 }));
    assert.deepEqual(t.map((x) => (x.ok ? "✓ " : "✕ ") + x.text),
      ["✕ PNG (got JPEG)", "✕ transparent (got opaque)", "✓ about square", "✓ ≥ 256 px"]);
  });
  test("an animation gets its own tick, only when the file moves", () => {
    const moving = ticks(LOGIN, facts({ format: "WEBP", w: 488, h: 480, animated: true }));
    assert.deepEqual(moving.map((x) => (x.ok ? "✓ " : "✕ ") + x.text),
      ["✓ WEBP", "✓ transparent", "✓ animated", "✓ about square", "✓ ≥ 480 px"]);
    const refused = ticks(SQUARE(64), facts({ animated: true }));
    assert.deepEqual(refused.map((x) => (x.ok ? "✓ " : "✕ ") + x.text),
      ["✓ PNG", "✓ transparent", "✕ still picture (got animated)", "✓ about square", "✓ ≥ 64 px"]);
    assert.equal(ticks(SQUARE(64), facts()).length, 4);
  });
});

describe("the refusal says what the server's says", () => {
  // the same sentences tests/test_branding_roles.py pins
  test("one broken rule", () => {
    assert.equal(refusalText("Login companion", [{ rule: "aspect", need: "about square", got: "3:4" }]),
      "Refused: the Login companion must be about square. This one is 3:4. Your current art is unchanged.");
    assert.equal(refusalText("Power poses", [{ rule: "transparent", need: "a transparent background", got: "opaque" }]),
      "Refused: the Power poses must have a transparent background. This one is opaque. Your current art is unchanged.");
    assert.equal(refusalText("Reward icons", [{ rule: "size", need: "at least 64 px", got: "48 px" }]),
      "Refused: the Reward icons must be at least 64 px. This one is 48 px. Your current art is unchanged.");
    assert.equal(refusalText("Power poses", specFailures(SQUARE(64), facts({ animated: true }))),
      "Refused: the Power poses must be a still picture. This one is animated. Your current art is unchanged.");
  });
  test("several, as pairs", () => {
    assert.equal(refusalText("Power poses", specFailures(SQUARE(256), facts({ format: "JPEG", see_through: 0 }))),
      "Refused: the Power poses must be PNG (this one is JPEG) and have a transparent background "
      + "(this one is opaque). Your current art is unchanged.");
    assert.equal(refusalText("Job tracker mascots", specFailures({ ...DONE, min_px: 128 }, facts({ w: 96, h: 64 }))),
      "Refused: the Job tracker mascots must be about 9:10 (this one is 3:2) and at least 128 px "
      + "(this one is 64 px). Your current art is unchanged.");
    assert.equal(refusalText("Reward icons", specFailures(SQUARE(64), facts({ format: "WEBP", animated: true }))),
      "Refused: the Reward icons must be PNG (this one is WEBP) and a still picture (this one is animated). "
      + "Your current art is unchanged.");
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
  test("whether it moves is the bytes' too: an animated WebP's header flag, an APNG's acTL chunk", () => {
    const webp = (flags) => [...Buffer.from("RIFF\0\0\0\0WEBPVP8X"), 10, 0, 0, 0, flags, 0, 0, 0];
    assert.equal(sniffAnimated(webp(0x12), "WEBP"), true);       // animation + alpha
    assert.equal(sniffAnimated(webp(0x10), "WEBP"), false);      // alpha only
    assert.equal(sniffAnimated([...Buffer.from("RIFF\0\0\0\0WEBPVP8 ")], "WEBP"), false);
    const png = (...chunks) => [0x89, 0x50, 0x4E, 0x47, 13, 10, 26, 10, ...Buffer.from(chunks.join(""))];
    assert.equal(sniffAnimated(png("IHDR", "acTL", "IDAT"), "PNG"), true);
    assert.equal(sniffAnimated(png("IHDR", "IDAT", "acTL"), "PNG"), false, "acTL after the first IDAT is not an APNG");
    assert.equal(sniffAnimated(png("IHDR", "IDAT"), "PNG"), false);
    assert.equal(sniffAnimated([...Buffer.from("GIF89a")], "GIF"), false, "a GIF fails on format first");
  });
  test("the see-through share counts pixels more than half clear", () => {
    const px = (a) => [10, 20, 30, a];
    const data = Uint8ClampedArray.from([...px(0), ...px(127), ...px(128), ...px(255)]);
    assert.equal(seeThroughFraction(data), 0.5);
    assert.equal(seeThroughFraction(new Uint8ClampedArray(0)), 0);
    assert.equal(seeThroughFraction(Uint8ClampedArray.from([...px(255), ...px(255)])), 0);
  });
});

describe("the phone's role screen has exactly two buttons, and a passing pick uploads at once", () => {
  // code only: the header comment says why there is no Use this, and names it
  const phone = readFileSync(new URL("../../gallery/src/components/BrandRolesPhone.jsx", import.meta.url), "utf8")
    .split("\r\n").join("\n").replace(/\/\*[\s\S]*?\*\//g, "");
  const hook = readFileSync(new URL("../../gallery/src/components/brandroles/useRoleEditor.js", import.meta.url), "utf8")
    .split("\r\n").join("\n");
  test("no Use this on the phone; only Choose photo and Use default", () => {
    assert.doesNotMatch(phone, /Use this/);
    assert.doesNotMatch(phone, /mgcp-rlm-use/);
    assert.match(phone, />Choose photo<\/button>/);
    assert.match(phone, />Use default<\/button>/);
  });
  test("Use default is enabled only where there is a default to go back to, as on the desktop", () => {
    assert.match(phone, /disabled=\{ed\.busy \|\| !img\.yours \|\| !img\.default_url\}/);
  });
  test("the photo picker commits the pick: it uploads itself when every rule passes", () => {
    assert.match(phone, /ed\.pickFile\(f, \{ commit: true \}\)/);
    assert.match(hook, /if \(commit && !failed\.length\) await send\(source\);/);
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
