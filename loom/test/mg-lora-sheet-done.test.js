import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// The phone's model/LoRA sheet gets a Done button (owner ruling, 2026-09-07: "Done
// button matches pixai").
//
// WHAT WAS WRONG. The sheet is ModelFlyout.jsx, mounted as-is by CreateMobile and
// re-anchored as a bottom sheet by create-mobile.css. Its head ended in a "✕" titled
// "Esc" -- a desktop vestige, since the phone has no Escape key. A BASE pick closes the
// sheet by itself (CreateMobile's onBasePick calls setFlyOpen(false)), but a LoRA pick
// only TOGGLES the entry, because multi-select is the point -- so after picking a LoRA
// nothing happened and the sheet read as stuck.
//
// Source-presence guards in the style of mg-model-picker-multi-select.test.js: the front
// end can't be booted headless here, so these pin the exact wiring the build depends on.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8");

const flyout = src("gallery/src/components/ModelFlyout.jsx");
const createMobile = src("gallery/src/components/CreateMobile.jsx");
const drawer = src("gallery/src/components/GenerateDrawer.jsx");
const css = src("gallery/src/styles/create-mobile.css");

describe("the phone sheet's head ends in Done; the desktop's still ends in ✕", () => {
  test("the label is ONE exported constant, so PixAI's wording is a one-line change", () => {
    assert.match(flyout, /export const LORA_SHEET_DONE_LABEL = "Done";/);
    assert.ok(flyout.includes("{LORA_SHEET_DONE_LABEL}"),
      "the button must render the constant, not a second literal that can drift from it");
  });

  test("`phone` is a PROP with an off default -- not a media query inside the component", () => {
    // The two mounts already know which they are: CreateMobile is the phone one,
    // GenerateDrawer the desktop one. A matchMedia read in here would make the control
    // depend on viewport width rather than on which shell mounted it.
    assert.match(flyout, /onBasePick, onLoraPick, onClose,\s*phone = false,/);
    assert.ok(!/matchMedia|innerWidth/.test(flyout),
      "ModelFlyout must not sniff the viewport; the caller says whether it is the phone");
  });

  test("phone renders Done wired to onClose; desktop keeps the ✕ titled Esc", () => {
    assert.ok(flyout.includes('<button type="button" className="glm-primary mfly-done" onClick={onClose}>'),
      "Done must close the sheet, and wear the phone's own primary-button class");
    assert.ok(flyout.includes('<button className="card" onClick={onClose} title="Esc">✕</button>'),
      "the desktop head is untouched");
    // one ternary, two arms -- exactly one of each control can ever render
    assert.equal((flyout.match(/mfly-done/g) || []).length, 1);
    assert.equal((flyout.match(/title="Esc"/g) || []).length, 1);
    assert.ok(flyout.indexOf("phone ? (") < flyout.indexOf("mfly-done"));
  });

  test("CreateMobile is the mount that passes `phone`; GenerateDrawer is not", () => {
    const mount = createMobile.slice(createMobile.indexOf("<ModelFlyout"));
    assert.match(mount.slice(0, 400), /<ModelFlyout\s*\r?\n\s*phone\b/);
    const deskMount = drawer.slice(drawer.indexOf("<ModelFlyout"));
    assert.ok(!/\bphone\b/.test(deskMount.slice(0, 400)),
      "the desktop drawer must never pass phone");
  });

  test("both sheet kinds get it -- the control is in the HEAD, not in the LoRA pane", () => {
    // base auto-closes on pick anyway, so Done there simply closes; the point is that
    // the head is one head and neither kind can be left with no way out but the scrim.
    const head = flyout.slice(flyout.indexOf('className="mfly-head"'),
      flyout.indexOf('<div style={{ display: kind === "base"'));
    assert.ok(head.includes("mfly-done"));
    assert.ok(head.includes('setKind("lora")') && head.includes('setKind("base")'));
  });

  test("the Done button is scoped to the phone sheet in CSS and un-stretched", () => {
    // .glm-primary is written for a full-width sheet action (flex: 1); in the head's
    // flex row it must not stretch.
    const i = css.indexOf(".cm-modelwrap .mfly-head .mfly-done {");
    assert.ok(i > 0, "the rule is scoped under .cm-modelwrap so it cannot leak to desktop");
    const rule = css.slice(i, css.indexOf("}", i));
    assert.match(rule, /flex: none;/);
  });
});
