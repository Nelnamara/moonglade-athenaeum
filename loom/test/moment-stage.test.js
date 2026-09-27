// THE CLIP MOMENTS' STAGE, pinned to their locked Design Handoff pages (the celebration-videos
// set in the private moonglade-internal repo, which this public file cannot read and does not
// quote). The pages render a 1920 x 1080 stage whose every overlay value is a pure function of
// one authored clock T; gallery/src/moments/momentCore.js (the player model) and scenes.js
// (the two overlays) are that, ported number for number, and they carry no DOM, so this file
// can pin them without a browser. The render harness (tests/test_render_harness.py) drives
// the real thing; the parity pass (moonglade-internal) compares it with the pages pixel for
// pixel. What this file adds is the NUMBERS, where a quiet drift fails in seconds:
//
//   * the clock: the page's clamp, the lead-in, the video as the clock while it plays, the
//     Hold on the page clock, and the harness seek's 20 ms rule;
//   * the two layers: cover/contain for the stage, a contain-fitted safe box for the UI, and
//     the minimum type sizes on small screens -- all exactly scale 1 at 1920 x 1080;
//   * reduced motion: one still, the overlay settled, no flare, no stars, no keycap motion;
//   * both overlays' geometry and cues, the page's own values;
//   * the store: one moment at a time, the same moment JOINED, and the Escape/mousedown guard;
//   * the component's contract with the parity lane (data-moment, data-moment-stage, data-part)
//     and with the shells (the Control Panel request, held until the panel's own read lands).
import { test, describe, before, after, mock } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "../../gallery/src");
const read = (p) => readFileSync(path.join(SRC, p), "utf8").replace(/\r\n/g, "\n");

const core = await import("../../gallery/src/moments/momentCore.js");
const scenes = await import("../../gallery/src/moments/scenes.js");
const { cuesFrom, SCENES, LEAD, CLIP_DUR } = core;
const SF = cuesFrom(SCENES.starfall);
const KT = cuesFrom(SCENES.keyturn);
const close = (a, b, why) => assert.ok(Math.abs(a - b) < 1e-9, (why || "") + " (" + a + " vs " + b + ")");

describe("the player model is the page's", () => {
  test("the scene lists give the pages' own cues and lengths", () => {
    assert.equal(LEAD, 0.5);
    assert.equal(CLIP_DUR, 15.04);
    assert.deepEqual(SF.cues, { Code: 0, Turn: 3, Gather: 6, Cast: 10.5, Starfall: 12.3, Hold: 15.54 });
    assert.equal(SF.total, 18.04);
    assert.deepEqual(KT.cues, { Rise: 0, Key: 3.5, Flight: 7.2, Door: 9.8, Inside: 13.2 });
    assert.equal(KT.total, 19.2);
    assert.equal(SF.cues.Hold, LEAD + CLIP_DUR, "the Hold beat starts exactly where the clip ends");
  });

  test("the page's clamp: clamp(T - LEAD, 0, CLIP_DUR - .05)", () => {
    assert.equal(core.clipTime(0), 0, "the lead-in shows the first frame");
    assert.equal(core.clipTime(0.3), 0);
    close(core.clipTime(7.25), 6.75);
    close(core.clipTime(15.5), CLIP_DUR - 0.05, "the last .05 s of the clip is never shown");
    close(core.clipTime(18), CLIP_DUR - 0.05, "and the Hold freezes on that frame");
    close(core.clipTime(5, core.clipEndOf(2)), 1.95, "a shorter file freezes on its own last frame");
    assert.equal(core.clipEndOf(15.04), CLIP_DUR);
    assert.equal(core.clipEndOf(NaN), CLIP_DUR);
    assert.equal(core.needsSeek(1.0, 1.019), false, "the page re-seeks only past 20 ms");
    assert.equal(core.needsSeek(1.0, 1.021), true);
  });

  test("the live clock: lead on the page clock, the VIDEO while it plays, the Hold on the page clock", () => {
    let s = core.startClock(1000);
    s = core.stepClock(s, { now: 1300, videoTime: 0, total: SF.total });
    close(s.T, 0.3); assert.equal(s.phase, "lead"); assert.equal(s.play, false);
    s = core.stepClock(s, { now: 1520, videoTime: 0, total: SF.total });
    assert.equal(s.phase, "clip"); assert.equal(s.play, true, "the clip starts at T = LEAD");
    close(s.T, LEAD);
    s = core.stepClock(s, { now: 99999, videoTime: 4.2, total: SF.total });
    close(s.T, 4.7, "while the clip plays T is the video's time + LEAD, whatever the wall clock says");
    s = core.stepClock(s, { now: 5000, videoTime: CLIP_DUR - 0.09, total: SF.total });
    assert.equal(s.phase, "hold", "the page stops playing once the clip time reaches CLIP_DUR - .1");
    assert.equal(s.pause, true);
    const base = s.T;
    s = core.stepClock(s, { now: 6000, videoTime: CLIP_DUR - 0.09, total: SF.total });
    close(s.T, base + 1, "and T runs on from where the video left off");
    close(s.seekTo, CLIP_DUR - 0.05, "the clip is held on the clamped frame");
    s = core.stepClock(s, { now: 6010, videoTime: CLIP_DUR - 0.05, total: SF.total });
    assert.equal(s.seekTo, null, "no re-seek once the held frame is shown");
    s = core.stepClock(s, { now: 1e7, videoTime: CLIP_DUR - 0.05, total: SF.total });
    assert.equal(s.done, true); close(s.T, SF.total);
  });

  test("a clip that ends early (the fixture) hands over to the page clock too", () => {
    let s = { ...core.startClock(0), phase: "clip", T: LEAD };
    s = core.stepClock(s, { now: 3000, videoTime: 2, ended: true, clipEnd: 2, total: KT.total });
    assert.equal(s.phase, "hold");
    s = core.stepClock(s, { now: 4000, videoTime: 1.95, clipEnd: 2, total: KT.total });
    close(s.T, 3.5);
    assert.equal(s.seekTo, null, "held on 1.95, the file's own last shown frame, not re-sought every tick");
  });
});

describe("two layers: the stage scales as one unit, the UI sits in a contain-fitted safe box", () => {
  test("at 1920 x 1080 both are scale 1 at the origin -- the parity frame", () => {
    assert.deepEqual(core.fitStage(1920, 1080), { scale: 1, x: 0, y: 0, mode: "cover" });
    assert.deepEqual(core.fitSafe(1920, 1080), { scale: 1, x: 0, y: 0 });
    const m = core.minType(1);
    assert.deepEqual([m.title, m.line, m.caption, m.button], [42, 20, 30, 1],
      "at scale 1 the minimums are the page's own sizes, untouched");
  });

  test("landscape covers, portrait contains (letterboxed, the whole composition)", () => {
    const wide = core.fitStage(2560, 1080);
    close(wide.scale, 2560 / 1920); assert.equal(wide.mode, "cover");
    assert.ok(wide.y < 0, "cover crops top and bottom on an ultrawide");
    const phone = core.fitStage(390, 844);
    close(phone.scale, 390 / 1920); assert.equal(phone.mode, "contain");
    close(phone.x, 0); assert.ok(phone.y > 0, "letterboxed on the moment's dark ground");
    const safe = core.fitSafe(1280, 900);
    close(safe.scale, 1280 / 1920, "the safe box is always contained, never cropped");
    close(safe.y, (900 - 720) / 2);
  });

  test("the minimum type size on a small screen", () => {
    const su = 390 / 1920;
    const m = core.minType(su);
    close(m.title * su, 20, "a toast title never renders under 20 px");
    close(m.line * su, 13, "a line never under 13 px");
    close(46 * m.button * su, 36, "the button never under 36 px tall");
    const f = scenes.keyturnFrame(KT.cues.Inside + 2, KT.cues, KT.total, { su, copy: {} });
    close(f.toast.title.fontSize * su, 20);
    close(f.toast.line.fontSize * su, 13);
    close(f.toast.button.height * su, 36);
  });
});

describe("reduced motion: one still, the overlay settled", () => {
  test("the still and the overlay use separate times (review amendment 11)", () => {
    const S = core.STILL;
    close(S.starfall.still(SF.cues), SF.cues.Cast + 0.5, "Starfall's still: arms raised");
    close(S.starfall.overlay(SF.cues), SF.cues.Cast + 2.1, "its toast settled");
    close(S.keyturn.still(KT.cues), KT.cues.Inside + 1, "the key turn's still: the library");
    close(S.keyturn.overlay(KT.cues), KT.cues.Inside + 1.5, "its final toast and button");
  });

  test("no flare, no stars, no keycap motion -- even at a time the live frame has them", () => {
    const T = SF.cues.Cast + 1.2;   // flare and the first stars are both live here
    const live = scenes.starfallFrame(T, SF.cues, SF.total, {});
    assert.ok(live.castflare, "the live frame has the flare at this T");
    assert.ok(live.stars.length > 0, "and stars");
    const still = scenes.starfallFrame(T, SF.cues, SF.total, { still: true });
    assert.equal(still.castflare, null, "reduced motion: no flare");
    assert.equal(still.stars.length, 0, "no stars");
    const keys = scenes.starfallFrame(1, SF.cues, SF.total, { still: true }).keys;
    assert.ok(keys.caps.every((c) => c.style.opacity === 1 && /translateY\(0px\) scale\(1\)/.test(c.style.transform)),
      "keycaps, where they show at all, are drawn at rest -- no pop");
    const kt = scenes.keyturnFrame(KT.cues.Door + 1.5, KT.cues, KT.total, { still: true });
    assert.equal(kt.doorflare, null, "no door flare");
    const settled = scenes.keyturnFrame(core.STILL.keyturn.overlay(KT.cues), KT.cues, KT.total, { still: true, copy: { title2: "B" } });
    assert.equal(settled.toast.box.opacity, 1, "the final toast is up");
    assert.equal(settled.toast.offer, 1, "with its button");
    assert.equal(settled.toast.titleText, "B", "showing its SECOND copy");
  });

  test("the component draws the settled state for reduced motion and for a clip that cannot play", () => {
    const cm = read("moments/ClipMoment.jsx");
    assert.match(cm, /prefers-reduced-motion: reduce/);
    assert.match(cm, /const overlayT = settled \? STILL\[kind\]\.overlay\(cues\) : T;/);
    assert.match(cm, /const clipT = settled \? STILL\[kind\]\.still\(cues\) : T;/);
    assert.match(cm, /onLoadedData=\{reduced \? onReady : undefined\}/,
      "reduced motion never plays the clip: it seeks one still once the first frame is decodable");
    assert.match(cm, /later\(\(\) => fallBack\(\), LOAD_CEILING_MS\)/,
      "a clip that never becomes playable falls back after the ceiling instead of just ending");
    assert.match(cm, /onError=\{onVideoError\}/);
    assert.match(cm, /if \(stalled > LOAD_CEILING_MS\) \{ settle\("fallback"\); return; \}/,
      "the video IS the clock, so one that stops for good must fall back -- or the moment, and " +
      "the hold on every later toast, never ends");
    assert.match(cm, /v\.play\(\)\.catch\(\(\) => \{ settle\("fallback"\); \}\);/,
      "and so must one that will not play even muted");
    assert.match(cm, /ee_starfall_cast\.ogg/, "the starfall's fallback keeps its two recorded tracks");
    assert.match(cm, /ee_starfall_loop\.ogg/);
    assert.match(cm, /if \(kind !== "starfall" \|\| tracksRef\.current\.length\) return;/,
      "and only the starfall's: the key turn's fallback is the toast alone");
    assert.equal(core.LOAD_CEILING_MS, 20000);
  });
});

describe("the starfall overlay, number for number", () => {
  const C = SF.cues;
  test("the clip covers the stage with a 1.00 -> 1.07 push-in from 50% 40%", () => {
    const f0 = scenes.starfallFrame(0, C, SF.total, {});
    assert.equal(f0.clip.width, 1920); assert.equal(f0.clip.height, 1080);
    assert.equal(f0.clip.objectFit, "cover");
    assert.equal(f0.clip.transformOrigin, "50% 40%");
    assert.equal(f0.clip.transform, "scale(1)");
    assert.equal(scenes.starfallFrame(LEAD + CLIP_DUR, C, SF.total, {}).clip.transform, "scale(1.07)");
    close(f0.fade, 0, "fades up from black");
    close(scenes.starfallFrame(SF.total, C, SF.total, {}).fade, 0, "and back to black at the end");
    close(scenes.starfallFrame(SF.total - 0.6, C, SF.total, {}).fade, 1, "over the last .6 s");
  });

  test("ten keycaps at top 120, 64 x 64, gap 12, popping .2 s apart from LEAD + .15", () => {
    const f = scenes.starfallFrame(1.2, C, SF.total, {});
    assert.equal(f.keys.row.top, 120);
    assert.equal(f.keys.row.gap, 12);
    assert.equal(f.keys.row.justifyContent, "center");
    assert.equal(f.keys.caps.length, 10);
    const cap = f.keys.caps[0].style;
    assert.equal(cap.width, 64); assert.equal(cap.height, 64); assert.equal(cap.borderRadius, 12);
    assert.equal(cap.fontSize, 28); assert.equal(cap.fontWeight, 600);
    assert.equal(cap.border, "1px solid var(--moment-lav)", "lit lavender");
    assert.equal(f.keys.caps[9].style.opacity, 0, "the tenth has not popped yet at T = 1.2");
    const at5 = LEAD + 0.15 + 5 * 0.2;
    assert.equal(scenes.starfallFrame(at5 + 0.09, C, SF.total, {}).keys.caps[5].style.border, "1px solid var(--moment-s1)",
      "a cap lights .1 s into its pop");
    close(scenes.starfallFrame(at5 + 0.35, C, SF.total, {}).keys.caps[5].style.opacity, 1);
    assert.equal(scenes.starfallFrame(C.Turn + 0.5, C, SF.total, {}).keys, null, "gone by Turn + .5");
    close(scenes.starfallFrame(C.Turn - 0.1, C, SF.total, {}).keys.row.opacity, 1, "fading from Turn - .1");
    assert.deepEqual(scenes.CODE.join(""), "↑↑↓↓←→←→BA");
  });

  test("the cast flare at (960, 250), from Cast + .9 over 1.3 s", () => {
    assert.equal(scenes.starfallFrame(C.Cast + 0.89, C, SF.total, {}).castflare, null);
    const peak = scenes.starfallFrame(C.Cast + 0.9 + 0.18 * 1.3, C, SF.total, {}).castflare;
    close(peak.bloom.opacity, 1, "peaks 18% into its run");
    close(peak.wash.opacity, 0.3);
    assert.equal(peak.bloom.left + 520, 960); assert.equal(peak.bloom.top + 520, 250);
    assert.equal(peak.bloom.width, 1040);
    assert.equal(peak.bloom.mixBlendMode, "screen");
    assert.equal(scenes.starfallFrame(C.Cast + 2.21, C, SF.total, {}).castflare, null);
  });

  test("110 seeded stars from Cast + 1.1, lavender", () => {
    assert.equal(scenes.STARS.length, 110);
    close(scenes.STARS[0].x, (Math.sin(311.7) * 43758.5453 - Math.floor(Math.sin(311.7) * 43758.5453)) * 1920,
      "the page's own seeded field, star for star");
    assert.equal(scenes.starfallFrame(C.Cast + 1.09, C, SF.total, {}).stars.length, 0);
    const f = scenes.starfallFrame(C.Cast + 4, C, SF.total, {});
    assert.ok(f.stars.length > 20, "it keeps raining through the hold");
    assert.equal(f.stars[0].style.color, "var(--moment-lav)");
  });

  test("the toast frosts in from Cast + 1.4, bottom 56, min-width 620", () => {
    assert.equal(scenes.starfallFrame(C.Cast + 1.4, C, SF.total, {}).toast.box.opacity, 0);
    const t = scenes.starfallFrame(C.Cast + 2.1, C, SF.total, { greeting: "G", line: "L" }).toast;
    close(t.box.opacity, 1);
    assert.equal(t.box.bottom, 56); assert.equal(t.box.left, 960); assert.equal(t.box.minWidth, 620);
    assert.equal(t.box.transform, "translate(-50%, 0) scale(1)");
    assert.equal(t.box.filter, "blur(0px)");
    assert.equal(t.box.padding, "26px 52px 24px"); assert.equal(t.box.borderRadius, 18);
    assert.equal(t.title.fontSize, 42); assert.equal(t.title.fontStyle, "italic");
    assert.equal(t.line.fontSize, 20); assert.equal(t.line.color, "var(--moment-sub-sf)");
    assert.equal(t.titleText, "G"); assert.equal(t.lineText, "L", "the line is the delivered copy, not source text");
  });
});

describe("the key turn overlay, number for number", () => {
  const C = KT.cues;
  test("the clip is letterboxed 1920 x 837 with a 1.00 -> 1.09 push-in", () => {
    const f = scenes.keyturnFrame(0, C, KT.total, {});
    assert.equal(f.clip.top, (1080 - 837) / 2); assert.equal(f.clip.height, 837); assert.equal(f.clip.width, 1920);
    assert.equal(f.clip.transformOrigin, "50% 50%");
    assert.equal(scenes.keyturnFrame(LEAD + CLIP_DUR, C, KT.total, {}).clip.transform, "scale(1.09)");
    close(scenes.keyturnFrame(KT.total - 0.5, C, KT.total, {}).fade, 1, "fades out over the last .5 s");
  });

  test("the door flare at (960, 520), from Door + 1.1 over 1.4 s", () => {
    const peak = scenes.keyturnFrame(C.Door + 1.1 + 0.18 * 1.4, C, KT.total, {}).doorflare;
    close(peak.bloom.opacity, 1); close(peak.wash.opacity, 0.35);
    assert.equal(peak.bloom.left + 500, 960); assert.equal(peak.bloom.top + 500, 520);
    assert.equal(scenes.keyturnFrame(C.Door + 1.1, C, KT.total, {}).doorflare, null);
  });

  test("the rail: right 56, top 150, 360 wide, 54 px rows, the lock at Door + 2.3, Branding at + 2.65", () => {
    const r = scenes.keyturnFrame(C.Door + 3.3, C, KT.total, {}).rail;
    assert.equal(r.box.right, 56); assert.equal(r.box.top, 150); assert.equal(r.box.width, 360);
    assert.equal(r.box.padding, 24); assert.equal(r.box.borderRadius, 20);
    assert.equal(r.heading.fontSize, 26); assert.equal(r.heading.fontStyle, "italic");
    assert.equal(r.tab(true).row.height, 54); assert.equal(r.tab(true).row.fontSize, 20);
    assert.equal(r.lockRow.height, 54);
    assert.equal(r.branding.height, 54); assert.equal(r.branding.color, "var(--moment-loom)");
    close(r.branding.opacity, 1, "the Branding row has slid in by Door + 3.3");
    assert.equal(r.box.opacity, 1);
    close(scenes.keyturnFrame(C.Door + 0.2, C, KT.total, {}).rail.box.opacity, 0, "it slides in from Door + .2");
    assert.equal(scenes.keyturnFrame(C.Door + 2.3, C, KT.total, {}).rail.body.background, "var(--moment-ov)",
      "the lock is shut until Door + 2.3");
    assert.equal(scenes.keyturnFrame(C.Door + 2.4, C, KT.total, {}).rail.body.background, "var(--moment-em)");
    close(scenes.keyturnFrame(C.Door + 2.65, C, KT.total, {}).rail.branding.opacity, 0);
  });

  test("the rail draws the REAL Control Panel tabs (the handoff's own note)", () => {
    const cm = read("moments/ClipMoment.jsx");
    assert.match(cm, /import \{ PANEL_TABS \} from "\.\.\/lib\/panelTabs\.js";/);
    assert.match(read("components/ControlPanelOverlay.jsx"), /panelTabLabel\("brand"\)/,
      "the panel's own tab buttons read the same list, so the two cannot drift");
    assert.doesNotMatch(cm, /"General"|"Appearance"|"Account"/, "the page's stand-in labels are not ported");
  });

  test("the toast: rises at Key + 1.9, dips at Flight + .1, returns at Inside + .3 with the button at + .9", () => {
    const copy = { title1: "one", line1: "l1", title2: "two", line2: "l2", button: "Go →", caption: "c" };
    const at = (T) => scenes.keyturnFrame(T, C, KT.total, { copy }).toast;
    close(at(C.Key + 1.9).box.opacity, 0); close(at(C.Key + 2.6).box.opacity, 1);
    assert.equal(at(C.Key + 2.6).titleText, "one");
    close(at(C.Flight + 0.7).box.opacity, 0, "dipped out for the flight");
    close(at(C.Inside + 0.9).box.opacity, 1);
    assert.equal(at(C.Inside + 0.9).titleText, "two"); assert.equal(at(C.Inside + 0.9).lineText, "l2");
    close(at(C.Inside + 1.5).offer, 1, "the button has popped by Inside + 1.5");
    assert.equal(at(C.Inside + 0.9).offer, 0);
    assert.equal(at(C.Inside + 1.5).box.border, "1px solid var(--moment-em)", "the key turn's toast is emerald");
    assert.equal(at(C.Inside + 1.5).button.height, 46); assert.equal(at(C.Inside + 1.5).button.background, "var(--moment-lav)");
    assert.equal(at(C.Inside + 1.5).buttonText, "Go", "the arrow is drawn once, in its own span");
  });

  test("the caption from Door + .4 until the library, with the engine's .18 s fade", () => {
    const cap = (T) => scenes.keyturnFrame(T, C, KT.total, { copy: { caption: "c" } }).caption;
    assert.equal(cap(C.Door + 0.39), null);
    close(cap(C.Door + 0.4 + 0.09).style.opacity, 0.5);
    close(cap(C.Door + 1.5).style.opacity, 1);
    assert.equal(cap(C.Inside), null);
    assert.equal(cap(C.Door + 1.5).style.bottom, "7%"); assert.equal(cap(C.Door + 1.5).style.fontSize, 30);
  });
});

describe("the moment's own colours, in every skin", () => {
  test("scenes.js draws in the moment's tokens only -- no hex, no skin token", () => {
    const src = read("moments/scenes.js");
    assert.doesNotMatch(src.replace(/\/\*[\s\S]*?\*\//g, ""), /#[0-9a-fA-F]{3,8}\b/,
      "a hex literal in the overlay code is a colour no token governs");
    assert.doesNotMatch(src, /var\(--(lavender|emerald|loomc|text|subtext|surface\d|overlay\d|accent)\)/,
      "a skin token recolours the celebration (Nightfallen's emerald is lavender)");
  });

  test("the tokens are the root palette's values, defined on the moment's own root", () => {
    const css = read("styles/moments.css");
    const tok = (n) => (css.match(new RegExp("--moment-" + n + ":\\s*(#[0-9a-f]{6})")) || [])[1];
    assert.deepEqual(
      ["lav", "em", "loom", "text", "sub", "s0", "s1", "ov"].map(tok),
      ["#b692e6", "#4fc99a", "#47cbc3", "#d6d2e2", "#9a93ab", "#211f3a", "#3a3460", "#6a6088"]);
    assert.match(css, /^\.mgm-root \{/m, "on the moment's root, where no html[data-skin] rule reaches");
  });

  test("the page's box model and stacking: content-box, scrim 515, stage 516", () => {
    const css = read("styles/moments.css");
    assert.match(css, /\.mgm-root, \.mgm-root \* \{ box-sizing: content-box; \}/,
      "the pages lay out content-box; the app's global border-box would shrink every keycap and toast");
    assert.match(css, /\.mgm-scrim \{[^}]*z-index: 515;/);
    assert.match(css, /\.mgm-host \{[^}]*z-index: 516;/);
    assert.match(css, /\.mgm-host \{[^}]*line-height: normal;/);
  });
});

describe("the component's contract with the parity lane", () => {
  const cm = read("moments/ClipMoment.jsx");
  test("the moment root, the stage, and every part the page draws", () => {
    assert.match(cm, /data-moment=\{kind\}/);
    assert.match(cm, /data-moment-stage=""/);
    for (const part of ["clip", "keys", "key", "star", "lock", "tab-branding", "toast", "toast-title",
      "toast-line", "button", "caption", "rail"]) {
      assert.match(cm, new RegExp('data-part="' + part + '"'), "no data-part=\"" + part + "\"");
    }
    assert.match(cm, /"castflare" : "doorflare"/);
  });

  test("the harness seek exists only under the harness flag and never mounts a moment", () => {
    assert.match(cm, /window\.__MG_MOMENT_HARNESS === true/);
    const hook = cm.slice(cm.indexOf("// The harness seek"), cm.indexOf("const skip = "));
    assert.match(hook, /if \(!harnessOn\(\)\) return undefined;/);
    assert.match(hook, /window\.__mgMomentSeek = seek;/,
      "defined by a MOUNTED moment's effect -- it cannot create one");
    assert.match(hook, /if \(needsSeek\(v\.currentTime, ct\)\) \{/,
      "and it waits on `seeked` only when the time really changes -- the page's own rule");
    assert.match(hook, /const ct = clipTime\(t, clipEndOf\(v\.duration\)\);/, "through the page's clamp");
    assert.doesNotMatch(read("App.jsx") + read("notify/index.jsx"), /__mgMomentSeek/);
  });

  test("autoplay: sound first, muted with a chip that is not a skip", () => {
    assert.match(cm, /v\.muted = true;\s*\n\s*setNeedsSound\(true\);/);
    assert.match(cm, /const unmute = \(e\) => \{\s*\n\s*e\.stopPropagation\(\);/);
    assert.match(cm, /const takeMeThere = \(e\) => \{\s*\n\s*e\.stopPropagation\(\);/,
      "the button ends the moment its own way, not as a skip");
    assert.match(cm, /className="mgm-host" onClick=\{skip\}/, "any other click is a skip");
  });
});

describe("one moment at a time, and Escape belongs to it", () => {
  let store;
  const keyLs = [];
  const downLs = [];
  before(async () => {
    globalThis.window = globalThis.window || {};
    const w = globalThis.window;
    const realAdd = w.addEventListener;
    w.addEventListener = (t, fn, cap) => {
      if (t === "keydown" && cap) keyLs.push(fn);
      if (t === "mousedown" && cap) downLs.push(fn);
      if (realAdd) realAdd.call(w, t, fn, cap);
    };
    store = await import("../../gallery/src/moments/momentStore.js?stage-test");
  });
  const esc = () => {
    const seen = { prevented: false, stopped: false };
    const ev = { key: "Escape", preventDefault() { seen.prevented = true; },
      stopPropagation() { seen.stopped = true; }, stopImmediatePropagation() { seen.stopped = true; } };
    keyLs.forEach((fn) => fn(ev));
    return seen;
  };

  test("the same moment is JOINED, a different one waits its turn", async () => {
    const p1 = store.playMoment({ moment: "starfall" });
    const cur = store.currentMoment();
    assert.equal(store.playMoment({ moment: "starfall", id: "x" }), p1,
      "the trigger starts the starfall and its marking check hands the same feat back: one starfall");
    let second = false;
    store.playMoment({ moment: "keyturn" }).then(() => { second = true; });
    store.finishMoment(cur.id, "done");
    assert.equal(await p1, "done");
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(store.currentMoment().kind, "keyturn", "the other moment starts once the first has ended");
    assert.equal(second, false);
    store.finishMoment(store.currentMoment().id, "done");
    await new Promise((r) => setTimeout(r, 0));
    assert.equal(second, true);
    assert.equal(await store.playMoment({ moment: "nope" }), "none", "an unknown kind plays nothing");
  });

  test("Escape is claimed only while a moment is ON SCREEN, and it skips that moment", () => {
    assert.equal(keyLs.length >= 1, true, "the guard is registered at module load, in capture");
    const p = store.playMoment({ moment: "keyturn" });
    const cur = store.currentMoment();
    let skipped = 0;
    store.attachMoment(cur.id, () => { skipped++; });
    const early = esc();
    assert.equal(early.prevented, false, "a moment still loading its clip is invisible and owns nothing");
    assert.equal(store.isMomentUp(), false);
    store.setMomentVisible(cur.id, true);
    assert.equal(store.isMomentUp(), true);
    const claimed = esc();
    assert.equal(claimed.prevented, true); assert.equal(claimed.stopped, true,
      "stopped in capture, so no overlay under the moment closes on the same key");
    assert.equal(skipped, 1, "and the moment's own fading exit runs");
    store.finishMoment(cur.id, "skipped");
    assert.equal(esc().prevented, false, "with no moment up the key is untouched");
    return p;
  });

  test("a click on the moment never reaches an outside-click closer under it", () => {
    store.playMoment({ moment: "starfall" });
    const cur = store.currentMoment();
    store.setMomentVisible(cur.id, true);
    let stopped = false;
    const ev = { target: { closest: (s) => (s === "[data-moment]" ? {} : null) },
      stopPropagation() { stopped = true; }, stopImmediatePropagation() { stopped = true; } };
    downLs.forEach((fn) => fn(ev));
    assert.equal(stopped, true);
    store.finishMoment(cur.id, "done");
  });

  test("a moment no host ever attaches to ends on its own ceiling", async () => {
    mock.timers.enable({ apis: ["setTimeout"] });
    try {
      const p = store.playMoment({ moment: "starfall" });
      mock.timers.tick(store.ATTACH_CEILING_MS);
      assert.equal(await p, "no-host",
        "a shell that never rendered the host would otherwise hold every later toast forever");
    } finally { mock.timers.reset(); }
  });

  test("App's own capture handlers read the moment-up guard", () => {
    const app = read("App.jsx");
    assert.match(app, /if \(isMomentUp\(\)\) return;\s+\/\/ a clip moment ends FIRST/);
    assert.match(app, /if \(isMomentUp\(\)\) return;\s+\/\/ a click on a moment ends the moment only/);
  });
});

describe("the button: the Control Panel, on its Branding tab", () => {
  let req;
  before(async () => {
    req = await import("../../gallery/src/notify/panelRequest.js");
  });
  after(() => { delete globalThis.CustomEvent; });

  test("a shell with a panel claims the request; one without carries it to the gallery", () => {
    const store = new Map();
    const assigned = [];
    let claim = true;
    globalThis.CustomEvent = class { constructor(t, o) { this.type = t; this.detail = o.detail; this.cancelable = o.cancelable; } };
    globalThis.window = Object.assign(globalThis.window || {}, {
      dispatchEvent: (ev) => { assert.equal(ev.type, req.OPEN_PANEL_EVENT); assert.equal(ev.detail.tab, "brand"); return !claim; },
      sessionStorage: { setItem: (k, v) => store.set(k, v), getItem: (k) => (store.has(k) ? store.get(k) : null), removeItem: (k) => store.delete(k) },
      location: { pathname: "/loom", search: "", assign: (u) => assigned.push(u) },
    });
    assert.equal(req.OPEN_PANEL_EVENT, "mg-open-control-panel");
    assert.equal(req.requestPanelTab("brand"), "opened", "claimed: the shell opens its own panel");
    claim = false;
    assert.equal(req.requestPanelTab("brand"), "navigating", "the Loom has no panel: it crosses to the gallery");
    assert.deepEqual(assigned, ["/"]);
    assert.equal(req.takeCarriedPanelTab(), "brand", "and the gallery takes the one-shot on boot");
    assert.equal(req.takeCarriedPanelTab(), "", "exactly once");
  });

  test("both shells claim it, and the panel holds the tab until its own read has answered", () => {
    const app = read("App.jsx");
    assert.match(app, /window\.addEventListener\(OPEN_PANEL_EVENT, onRequest\);/);
    assert.match(app, /open\(takeCarriedPanelTab\(\)\);/);
    assert.match(app, /tabRequest=\{panelTab\}/);
    const mob = read("components/AppMobile.jsx");
    assert.match(mob, /window\.addEventListener\(OPEN_PANEL_EVENT, onRequest\);/);
    assert.match(mob, /<ControlMobile account=\{account\} brandRequest=\{brandRequest\} \/>/);
    const cp = read("components/ControlPanelOverlay.jsx");
    assert.match(cp, /fetchAchievements\(\)\.then\(\(\) => \{ if \(live\) setTabHeld\(false\); \}\);/);
    assert.match(cp, /if \(tab === "brand" && !brandingUnlocked && !tabHeld && achievementsFresh\) setTab\("maint"\);/,
      "a cached roster from before the earn must not snap a just-unlocked tab back");
    assert.match(read("components/ControlMobile.jsx"),
      /fetchAchievements\(\)\.then\(\(d\) => \{ if \(live && brandingUnlockedIn\(d\)\) openBrand\(\); \}\);/);
  });

  test("the Branding tab is unlocked by the roster's `unlocks` flag, never an id", () => {
    const hook = read("hooks/useControlPanel.js");
    assert.match(hook, /a\.unlocks === "branding_tab" && a\.earned/);
    assert.doesNotMatch(hook, /a\.id === "/);
    assert.match(hook, /if \(achInFlight\.current\) return achInFlight\.current;/,
      "a requested tab joins the read already in flight rather than sweeping the server twice");
  });
});
