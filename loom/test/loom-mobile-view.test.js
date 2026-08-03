import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// First increment of the Loom Mobile board/reel view (2026-08-03), per the locked design
// (design_handoff/design_handoff_moonglade_suite/"Loom Mobile.dc.html"). master-storyboard.jsx
// has no jsdom/React render harness in this runner (same situation as every other JSX-only
// feature here -- see loom-continuity-badge.test.js's own comment) -- source-presence/
// source-structure assertions are the established pattern for anything that lives in the
// .jsx file, real behavioral assertions for anything pure enough to live in loom-core.js/
// loom-mutations.js instead. The reel's pointer-drag scrub is genuinely new UI logic with no
// pure counterpart to extract (it reads getBoundingClientRect off a real DOM node), so it is
// covered here the same way, plus a live-browser check (see the task's own verification step).
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8");

// LoomMobile is inserted immediately before the "COMPOSED HOOKS" banner comment -- a simple,
// robust landmark to slice its own source out for scoped assertions (negative checks in
// particular must not accidentally match LoomV2's OWN "Cast & assets"/Generate copy elsewhere
// in this same file), the same "known landmark" technique other tests in this suite already
// use rather than a hand-rolled brace-balancer.
const mobileStart = src.indexOf("function LoomMobile({");
const mobileEnd = src.indexOf("COMPOSED HOOKS (Phase 2", mobileStart);
assert.ok(mobileStart > 0, "expected to find LoomMobile's function declaration");
assert.ok(mobileEnd > mobileStart, "expected to find the COMPOSED HOOKS banner after LoomMobile");
const loomMobileSrc = src.slice(mobileStart, mobileEnd);

describe("LoomMobile exists as a real component, inline (matching this file's own convention)", () => {
  test("LoomMobile is a real function component, not left as TODO/stub", () => {
    assert.match(loomMobileSrc, /function LoomMobile\(\{/);
    assert.match(loomMobileSrc, /return \(\s*<div className="lm-root">/,
      "expected LoomMobile to actually render something, not bail out with a placeholder");
  });

  test("LoomMobile is NOT split into a separate loom/src/ module", () => {
    // Deliberate call, documented in LoomMobile's own header comment: components live inline
    // in this file (LoomV2/ProjectSwitcher/ExportMenu/ShotPreview/... all do); only
    // React-free, DOM-free pure logic belongs in loom/src/ (loom-core.js, loom-mutations.js),
    // because the Flask /loom route's Babel-standalone fallback only knows how to inline
    // exactly those two files -- a third imported module would break the DEFAULT /loom page
    // (see LoomMobile's own comment for the full reasoning).
    assert.doesNotMatch(src, /from\s*["']\.\/src\/loom-mobile/,
      "LoomMobile must not be imported from a new ./src/loom-mobile* module");
  });

  test("its own styles are defined and actually injected", () => {
    assert.match(src, /const LOOM_MOBILE_STYLES = `/);
    assert.match(loomMobileSrc, /<style>\{LOOM_MOBILE_STYLES\}<\/style>/);
  });

  test("locks the body scroll while mounted, same reasoning as LoomV2's own identical effect", () => {
    assert.match(loomMobileSrc, /document\.body\.style\.overflow = "hidden"/);
  });
});

describe("the Mobile-view toggle: a new, persisted, manual owner-preference switch", () => {
  test("a small, real useLocalToggle hook exists (no prior localStorage-toggle hook in this file)", () => {
    assert.match(src, /function useLocalToggle\(key, defaultVal\)\s*\{/);
    assert.match(src, /window\.localStorage\.getItem\(key\)/);
    assert.match(src, /window\.localStorage\.setItem\(key, val \? "1" : "0"\)/);
  });

  test("the localStorage key is a real, named constant", () => {
    assert.match(src, /const MOBILE_UI_KEY = "mg_loom_mobile_ui";/);
  });

  test("App() wires mobileUI/setMobileUI through useLocalToggle(MOBILE_UI_KEY, false)", () => {
    assert.match(src, /const \[mobileUI, setMobileUI\] = useLocalToggle\(MOBILE_UI_KEY, false\);/);
  });

  test("a toggle chip lives in LoomV2's own .lv-top bar, reusing .lv-draft's exact visual pattern", () => {
    const topBarMatch = src.match(/<div className="lv-top">[\s\S]*?<\/div>/);
    assert.ok(topBarMatch, "expected to find the .lv-top toolbar's own JSX block");
    assert.match(topBarMatch[0], /<label className=\{"lv-draft" \+ \(mobileUI \? " on" : ""\)\}/,
      "expected the Mobile-view chip to reuse the .lv-draft checkbox-chip class, not invent a new visual language");
    assert.match(topBarMatch[0], /checked=\{!!mobileUI\}/);
    assert.match(topBarMatch[0], /onChange=\{\(e\) => setMobileUI\(e\.target\.checked\)\}/);
  });

  test("LoomMobile carries its own reciprocal switch back to desktop (never a one-way trap)", () => {
    // Not in the locked design (whose mobile top bar has no return path to LoomV2 at all) --
    // required so the owner is never stranded: LoomV2's own .lv-top bar, which carries the
    // ONLY other instance of this switch, stops rendering entirely once mobileUI is true.
    assert.match(loomMobileSrc, /onClick=\{\(\) => setMobileUI\(false\)\}/);
  });

  test("App() actually renders ONE of LoomMobile / LoomV2, gated on mobileUI", () => {
    assert.match(src, /\{mobileUI \? \(\s*<V2Boundary><LoomMobile/);
    assert.match(src, /\) : \(\s*<V2Boundary><LoomV2/);
  });
});

describe("draftCard/draftTarget/draftAttachedInfo: lifted from LoomV2 to App(), unchanged behavior", () => {
  test("each of the three is declared via useState EXACTLY ONCE in the whole file (no duplicate left behind)", () => {
    for (const name of ["draftCard", "draftTarget", "draftAttachedInfo"]) {
      const re = new RegExp(`const \\[${name}, set${name[0].toUpperCase()}${name.slice(1)}\\] = useState\\(`, "g");
      const hits = src.match(re) || [];
      assert.equal(hits.length, 1, `expected exactly one useState declaration for ${name}, found ${hits.length}`);
    }
  });

  test("the one declaration site for each lives in App(), not in LoomV2", () => {
    const appStart = src.indexOf("export default function App() {");
    const appToStoreCall = src.slice(appStart, src.indexOf("useProjectStore(setSelShot);", appStart));
    assert.match(appToStoreCall, /const \[draftCard, setDraftCard\] = useState\(\(\) => \(\{/);
    assert.match(appToStoreCall, /const \[draftTarget, setDraftTarget\] = useState\(""\);/);
    assert.match(appToStoreCall, /const \[draftAttachedInfo, setDraftAttachedInfo\] = useState\(null\);/);
  });

  test("LoomV2's own function signature now RECEIVES all three as props", () => {
    const sigMatch = src.match(/function LoomV2\(\{([\s\S]*?)\}\)\s*\{/);
    assert.ok(sigMatch, "expected to find LoomV2's function signature");
    for (const name of ["draftCard", "setDraftCard", "draftTarget", "setDraftTarget", "draftAttachedInfo", "setDraftAttachedInfo"]) {
      assert.match(sigMatch[1], new RegExp(`\\b${name}\\b`), `LoomV2's signature should destructure ${name}`);
    }
  });

  test("LoomMobile's own function signature ALSO receives all three (threaded for the next increment)", () => {
    const sigMatch = loomMobileSrc.match(/function LoomMobile\(\{([\s\S]*?)\}\)\s*\{/);
    assert.ok(sigMatch, "expected to find LoomMobile's function signature");
    for (const name of ["draftCard", "setDraftCard", "draftTarget", "setDraftTarget", "draftAttachedInfo", "setDraftAttachedInfo"]) {
      assert.match(sigMatch[1], new RegExp(`\\b${name}\\b`), `LoomMobile's signature should destructure ${name}`);
    }
  });

  test("both the <LoomV2 .../> and <LoomMobile .../> call sites pass all three through", () => {
    const loomV2Call = src.match(/<LoomV2\b[\s\S]*?\/>/);
    const loomMobileCall = src.match(/<LoomMobile\b[\s\S]*?\/>/);
    assert.ok(loomV2Call, "expected to find the <LoomV2 .../> call site");
    assert.ok(loomMobileCall, "expected to find the <LoomMobile .../> call site");
    for (const call of [loomV2Call[0], loomMobileCall[0]]) {
      for (const prop of ["draftCard={draftCard}", "setDraftCard={setDraftCard}", "draftTarget={draftTarget}",
        "setDraftTarget={setDraftTarget}", "draftAttachedInfo={draftAttachedInfo}", "setDraftAttachedInfo={setDraftAttachedInfo}"]) {
        assert.ok(call.includes(prop), `expected "${prop}" in: ${call.slice(0, 60)}...`);
      }
    }
  });
});

describe("the reel's pointer-drag scrub: real fraction-of-width math, no gesture library", () => {
  test("the reel bar wires all four pointer handlers", () => {
    assert.match(loomMobileSrc,
      /onPointerDown=\{onReelDown\} onPointerMove=\{onReelMove\} onPointerUp=\{onReelUp\} onPointerLeave=\{onReelLeave\}/);
  });

  test("onReelDown actually calls setPointerCapture with the real pointerId, not a no-op", () => {
    assert.match(loomMobileSrc, /e\.currentTarget\.setPointerCapture\(e\.pointerId\)/);
  });

  test("the fraction is computed from a real getBoundingClientRect + clientX, not a fake/stubbed value", () => {
    assert.match(loomMobileSrc, /const r = e\.currentTarget\.getBoundingClientRect\(\);/);
    assert.match(loomMobileSrc, /\(e\.clientX - r\.left\) \/ r\.width/);
  });

  test("the fraction resolves to a shot INDEX via cumulative duration (not just a raw percentage)", () => {
    assert.match(loomMobileSrc, /const idxAtFrac = \(frac\) => \{/);
    assert.match(loomMobileSrc, /cum \+= durOf\(entries\[i\]\.c\) \|\| 1/);
  });

  test("releasing the drag selects the shot it landed on", () => {
    assert.match(loomMobileSrc, /const onReelUp = \(\) => \{ setScrubbing\(false\); if \(scrubIdx != null && entries\[scrubIdx\]\) setSelShot\(entries\[scrubIdx\]\.c\.id\); \};/);
  });

  test("a floating preview card renders only while scrubbing, showing the live shot under the pointer", () => {
    assert.match(loomMobileSrc, /\{scrubbing && scrubEntry && \(/);
    assert.match(loomMobileSrc, /className="lm-preview"/);
  });

  test("a target-duration tick mark is derived from project.target, not hardcoded", () => {
    assert.match(loomMobileSrc, /const tickFrac = total > 0 \? Math\.min\(1, \(project\.target \|\| 0\) \/ total\) : 0;/);
  });
});

describe("the act-grouped shot board: add-shot / add-act / tap-to-select", () => {
  test("+ Shot calls the real addCard(act.id) mutation", () => {
    assert.match(loomMobileSrc, /className="lm-addshot" onClick=\{\(\) => addCard\(act\.id\)\}/);
  });

  test("+ New act calls the real addAct mutation", () => {
    assert.match(loomMobileSrc, /className="lm-addact" onClick=\{addAct\}/);
  });

  test("tapping a shot card selects it (the documented 'binds to Generate' contract), not a dead tap or a fake modal", () => {
    assert.match(loomMobileSrc, /className=\{"lm-card"[^}]*\}\s*\n\s*onClick=\{\(\) => setSelShot\(e\.c\.id\)\}/);
  });

  test("cards show a real thumbnail resolved the same way LoomV2's own board does (open frame, else the rendered result)", () => {
    assert.match(loomMobileSrc, /const cardThumb = \(c\) => frameSrc\(c\.openFrame\) \|\| \(c\.resultMid \? "\/thumbs\/" \+ c\.resultMid \+ "\.jpg" : null\);/);
  });

  test("status pill and reel segment color share ONE statusOf() computation (never two independent copies)", () => {
    const hits = loomMobileSrc.match(/const statusOf = \(c\) => \{/g) || [];
    assert.equal(hits.length, 1, "statusOf must be defined exactly once and reused by both the reel and the board card");
    assert.match(loomMobileSrc, /statusOf\(x\.c\)/, "the reel segment should call statusOf");
    assert.match(loomMobileSrc, /const st = statusOf\(e\.c\);/, "the board card should call the SAME statusOf");
  });
});

describe("scope discipline: this increment does NOT build shot detail / cast sheet / generate / review-trim / filter-compare", () => {
  test("no Deep-Focus-equivalent, Cast & assets, Generate, Review & trim, or Filter-compare UI leaked into LoomMobile yet", () => {
    for (const phrase of ["Cast & assets", "Generate reference image", "Review & trim", "Art filters", "Edit instruction", "Generate video"]) {
      assert.ok(!loomMobileSrc.includes(phrase),
        `LoomMobile should not yet contain "${phrase}" -- that belongs to a later increment`);
    }
  });
});
