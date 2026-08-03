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

  test("tapping a shot card selects it AND opens Shot Detail (second increment) -- the 'binds to Generate' contract still fires, it's just no longer the only thing the tap does", () => {
    assert.match(loomMobileSrc, /className=\{"lm-card"[^}]*\}\s*\n\s*onClick=\{\(\) => \{ setSelShot\(e\.c\.id\); setDfOpen\(true\); \}\}/);
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

// Second increment of the Loom Mobile view (2026-08-03), per the same locked design.
// Shot Detail (Deep Focus's mobile equivalent), the Cast & assets sheet, and the Frame
// picker are now built; Generate (all 4 modes), Review & trim, and Filter compare are
// still out of scope for a later increment.

// Third increment (2026-08-03): Generate (the real, billed video-submit screen, across all
// 4 real modes -- I2V/R2V/V2V/FLF, per loom-core.js's own MODES/mode logic, not the locked
// design's own separate "Image/Edit/Reference/Video" tab strip) is now built. The locked
// design's OTHER three Generate tabs (Image/Edit/Reference -- still-image generation, a
// different feature from "submit this shot's video") are deliberately NOT built this
// increment, same as Review & trim / Filter compare -- this increment's own scope was
// framed entirely around "the 4 real modes," which is a Video-submit-only concept.

describe("Shot Detail (mobile Deep Focus): opens from the board, edits the REAL shot", () => {
  test("renders only while dfOpen && dfLive -- never an empty/placeholder screen", () => {
    assert.match(loomMobileSrc, /\{dfOpen && dfLive && \(\(\) => \{/);
    assert.match(loomMobileSrc, /<div className="lm-df">/);
  });

  test("a stale reference (the shot vanished out from under it) closes Shot Detail instead of rendering blank", () => {
    assert.match(loomMobileSrc, /const dfLive = dfOpen \? entries\.find\(\(x\) => x\.c\.id === selShot\) : null;/);
    assert.match(loomMobileSrc, /if \(dfOpen && !dfLive\) \{ setDfOpen\(false\); \}/);
  });

  test("Mode chips render the real MODES array and write through the real setShotMode reducer", () => {
    assert.match(loomMobileSrc, /\{MODES\.map\(\(m\) => \(/);
    assert.match(loomMobileSrc, /onClick=\{\(\) => dfPatch\(\(cc\) => setShotMode\(cc, m\)\)\}/);
  });

  test("Duration and Discreet bind to the shot's real c.duration/c.discreet fields", () => {
    assert.match(loomMobileSrc, /value=\{c\.duration\}/);
    assert.match(loomMobileSrc, /checked=\{!!c\.discreet\}/);
  });

  test("Prompt is the real c.prompt, and typing it clears an active promptOverride exactly like LoomV2's own Deep Focus", () => {
    assert.match(loomMobileSrc, /value=\{c\.prompt \|\| ""\} placeholder="what happens in this shot"/);
    assert.match(loomMobileSrc, /dfPatch\(\(cc\) => \(\{ \.\.\.clearPromptOverride\(cc\), prompt: ev\.target\.value \}\)\)/);
  });

  test("the status pill cycles the real, persisted 3-state c.status (todo->wip->done->todo) -- 'paused' is a genState display-only phase, never invented as a 4th persisted status", () => {
    assert.match(loomMobileSrc, /status: cc\.status === "todo" \? "wip" : cc\.status === "wip" \? "done" : "todo"/);
  });

  test("frame slots reuse the REAL, already-shipped FrameSlot component (not a hand-rolled duplicate) for both Opening and Closing frame", () => {
    const opens = loomMobileSrc.match(/<FrameSlot which="open"/g) || [];
    const closes = loomMobileSrc.match(/<FrameSlot which="close"/g) || [];
    assert.equal(opens.length, 1, "expected exactly one open FrameSlot in Shot Detail");
    assert.equal(closes.length, 1, "expected exactly one close FrameSlot in Shot Detail");
    // Real props, not mock data: the real openPick/storeThumb this component now receives,
    // and the real positionTag() live-slot numbering loom-core.js computes.
    assert.match(loomMobileSrc, /liveTag=\{positionTag\(dfLive, project, imgSrc, "openFrame"\)\}/);
    assert.match(loomMobileSrc, /storeThumb=\{storeThumb\} openPick=\{openPick\}/);
  });

  test("the opening frame's 'inherit previous close' extraBtn only appears with a real previous shot, mirroring LoomV2's own inheritPrev/handoff splice", () => {
    assert.match(loomMobileSrc, /extraBtn=\{dfPrevEntry \? \(/);
    assert.match(loomMobileSrc, /fetch\("\/api\/loom\/handoff", \{ method: "POST"/);
  });

  test("Other references & @tags uses the real addRef/setRef/delRef mutations over c.refs, not the design mockup's flat extraRefs tag-string array", () => {
    assert.match(loomMobileSrc, /onClick=\{\(\) => addRef\(dfLive\.a\.id, c, "image"\)\}/);
    assert.match(loomMobileSrc, /onClick=\{\(\) => addRef\(dfLive\.a\.id, c, "video"\)\}/);
    assert.match(loomMobileSrc, /onClick=\{\(\) => addRef\(dfLive\.a\.id, c, "audio"\)\}/);
    assert.match(loomMobileSrc, /onClick=\{\(\) => delRef\(dfLive\.a\.id, c\.id, r\)\}/);
    assert.doesNotMatch(src, /extraRefs/, "extraRefs is the design mockup's own fictional field -- the real card shape has no such field, and none of this file should invent one");
  });

  test("the Cast button shows the shot's REAL cast count ((c.cast||[]).length), not a separate mock toggle map", () => {
    assert.match(loomMobileSrc, /className="lm-df-cast" onClick=\{\(\) => setCastSheetOpen\(true\)\}/);
    assert.match(loomMobileSrc, /&#128101; \{\(c\.cast \|\| \[\]\)\.length\}/);
  });

  test("Copy shot calls the real, already-shared copyShot(dfLive)", () => {
    assert.match(loomMobileSrc, /onClick=\{\(\) => copyShot\(dfLive\)\}/);
  });
});

describe("Cast & assets sheet: real project.assets, mode-aware budget, and a Footage tab off real finished shots", () => {
  test("the sheet has its own Cast/Footage tab strip, matching the locked design's own layout", () => {
    assert.match(loomMobileSrc, /Cast &amp; assets<\/button>/);
    assert.match(loomMobileSrc, /onClick=\{\(\) => setCastSheetTab\("footage"\)\}>Footage<\/button>/);
  });

  test("cast rows toggle the shot's REAL c.cast array (project.assets), not a design-mockup castToggle map keyed off array index", () => {
    assert.match(loomMobileSrc,
      /onClick=\{\(\) => dfPatch\(\(cc\) => \(\{ \.\.\.cc, cast: \(cc\.cast \|\| \[\]\)\.includes\(as\.id\) \? cc\.cast\.filter\(\(x\) => x !== as\.id\) : \[\.\.\.\(cc\.cast \|\| \[\]\), as\.id\] \}\)\)\}/);
  });

  test("the budget line is the REAL, mode-aware refBudget()/modeSendsRefs() -- not the design mockup's hardcoded 'N of 4 reference slots' or its I2V-only special case (FLF also doesn't send cast/refs)", () => {
    assert.match(loomMobileSrc, /const castBudget = dfLive \? refBudget\(dfLive, project, imgSrc\) : null;/);
    assert.match(loomMobileSrc, /!modeSendsRefs\(c\.mode\)/);
    assert.doesNotMatch(loomMobileSrc, /of 4 reference slots/, "the real cap is 6 minus attached frames (refBudget), never a hardcoded 4");
  });

  test("+ Image ref / + Audio ref append real, taggable project.assets entries via setAssets + nextTag", () => {
    assert.match(loomMobileSrc, /setAssets\(\(a\) => \[\.\.\.a, \{ id: uid\(\), name: "New reference", kind: "image", tag: nextTag\(a, "@image"\)/);
    assert.match(loomMobileSrc, /setAssets\(\(a\) => \[\.\.\.a, \{ id: uid\(\), name: "New audio", kind: "audio", tag: nextTag\(a, "@audio"\)/);
  });

  test("the Footage tab lists REAL finished shots (entries with a resultMid), not fabricated footage rows", () => {
    assert.match(loomMobileSrc, /const finishedShots = entries\.filter\(\(e\) => e\.c\.resultMid\);/);
    assert.match(loomMobileSrc, /src=\{"\/thumbs\/" \+ e\.c\.resultMid \+ "\.jpg"\}/);
  });

  test("picking a finished shot appends it as a real @videoN reference on the open shot (dfPickFootage), not the design mockup's fictional extraRefs concat", () => {
    assert.match(loomMobileSrc, /const dfPickFootage = \(mid, code\) => \{/);
    assert.match(loomMobileSrc, /const tag = nextTag\(dfLive\.c\.refs\.filter\(\(r\) => r\.kind === "video"\), "@video"\);/);
    assert.match(loomMobileSrc, /onClick=\{\(\) => \{ dfPickFootage\(e\.c\.resultMid, e\.code\); setCastSheetOpen\(false\); \}\}/);
  });
});

describe("Frame picker: the shared, already-real gallery picker -- not a fabricated grid of mock data", () => {
  test("LoomMobile never defines its own picker grid or mock gallery pool -- it reuses the real FrameSlot -> openPick -> <mg-gallery-picker> chain every other Loom surface already uses", () => {
    assert.doesNotMatch(loomMobileSrc, /GALLERY_POOL/, "GALLERY_POOL was the LOCKED DESIGN's own fictional placeholder tint grid -- the real app must not reproduce fabricated gallery data");
    // openPick is threaded in as a real prop and handed straight to FrameSlot -- no second,
    // parallel picker implementation lives in this component.
    assert.match(loomMobileSrc, /openPick=\{openPick\}/);
  });
});

describe("scope discipline: Review & trim / Filter compare (and the OTHER 3 Generate tabs) are still NOT built", () => {
  test("no Review & trim, Filter-compare, or still-image-generation UI leaked into LoomMobile", () => {
    // "Generate video" is now REAL (this increment's own scope, asserted positively below) --
    // removed from this negative list on purpose, not an oversight. Everything else here
    // remains a later increment: Review & trim and Filter compare outright, and the locked
    // design's Image/Edit/Reference Generate tabs (a different feature -- generating a still,
    // not submitting this shot's video) which this increment's own "all 4 real MODES" framing
    // never covered either.
    for (const phrase of ["Generate reference image", "Review & trim", "Art filters", "Edit instruction"]) {
      assert.ok(!loomMobileSrc.includes(phrase),
        `LoomMobile should not yet contain "${phrase}" -- that belongs to a later increment`);
    }
  });

  test("Shot Detail / Cast & assets / Frame picker copy NOW DOES exist (prior increment's scope)", () => {
    assert.ok(loomMobileSrc.includes("Cast &amp; assets"), "expected the Cast & assets sheet's own tab label to exist now");
    assert.ok(loomMobileSrc.includes("Other references &amp; @tags"), "expected Shot Detail's real references section to exist now");
    assert.ok(loomMobileSrc.includes("Music / audio cue"), "expected Shot Detail's audio-cue field to exist now");
  });
});

describe("Generate: real submit, real cost preview, real generation-state tracking (third increment)", () => {
  test("Shot Detail's own 'Select in Generate →' button opens the real genOpen screen (not a stub)", () => {
    assert.match(loomMobileSrc, /className="lm-genbtn" onClick=\{\(\) => setGenOpen\(true\)\}>Select in Generate/);
  });

  test("genState/priceShot/generateShot/useExistingVideo are threaded through as real props, not re-invented", () => {
    const sigMatch = loomMobileSrc.match(/function LoomMobile\(\{([\s\S]*?)\}\)\s*\{/);
    assert.ok(sigMatch, "expected to find LoomMobile's function signature");
    for (const name of ["generateShot", "priceShot", "useExistingVideo"]) {
      assert.match(sigMatch[1], new RegExp(`\\b${name}\\b`), `LoomMobile's signature should destructure ${name}`);
    }
  });

  test("the <LoomMobile .../> call site passes generateShot/priceShot/useExistingVideo through", () => {
    const loomMobileCall = src.match(/<LoomMobile\b[\s\S]*?\/>/);
    assert.ok(loomMobileCall, "expected to find the <LoomMobile .../> call site");
    for (const prop of ["generateShot={generateShot}", "priceShot={priceShot}", "useExistingVideo={useExistingVideo}"]) {
      assert.ok(loomMobileCall[0].includes(prop), `expected "${prop}" at the <LoomMobile .../> call site`);
    }
  });

  test("priceShot is exposed by useGenerationPipeline's own return value (not a new fetch/pricing implementation)", () => {
    assert.match(src, /generateShot, pollShot, useExistingVideo, genImage, routeImg, genEdit, genRef, routeGen, batchGenerate,\s*\n\s*costEstimate, refreshEstimate, priceShot,/);
  });

  test("Mode chips render the real MODES array (all 4: I2V/R2V/V2V/FLF) inside the Generate screen too, writing through the real setShotMode reducer", () => {
    const genBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("genOpen && dfLive && (() => {"));
    assert.match(genBlock, /\{MODES\.map\(\(m\) => \(/);
    assert.match(genBlock, /onClick=\{\(\) => dfPatch\(\(cc\) => setShotMode\(cc, m\)\)\}/);
  });

  test("Continuity chips render the real CONNECT map, writing through the real setShotConnect reducer", () => {
    const genBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("genOpen && dfLive && (() => {"));
    assert.match(genBlock, /\{Object\.keys\(CONNECT\)\.map\(\(k\) => \(/);
    assert.match(genBlock, /onClick=\{\(\) => dfPatch\(\(cc\) => setShotConnect\(cc, k\)\)\}/);
  });

  test("which frame slots render is mode-aware via the REAL usesCloseFrame(), not a hardcoded I2V special case", () => {
    const genBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("genOpen && dfLive && (() => {"));
    assert.match(genBlock, /const showClose = usesCloseFrame\(c\.mode\);/);
  });

  test("the assembled-prompt preview calls the REAL shotText(), not a fabricated preview string", () => {
    const genBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("genOpen && dfLive && (() => {"));
    assert.match(genBlock, /<div className="lm-genpreview">\{shotText\(dfLive, project, imgSrc\)\}<\/div>/);
  });

  test("Generate audio wires the REAL c.audioGen/c.audioLanguage fields (never exposed on mobile before this increment), with the real 5-value language enum mg-generate-drawer.js itself uses", () => {
    const genBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("genOpen && dfLive && (() => {"));
    assert.match(genBlock, /checked=\{!!c\.audioGen\}/);
    assert.match(genBlock, /onChange=\{\(ev\) => dfPatch\(\(cc\) => \(\{ \.\.\.cc, audioGen: ev\.target\.checked \}\)\)\}/);
    for (const lang of ["english", "japanese", "chinese", "korean", "none"]) {
      assert.ok(genBlock.includes(`value="${lang}"`), `expected a real "${lang}" audio-language option`);
    }
  });

  test("the cost preview reuses tallyPrices/formatCostEstimate/costTooltip VERBATIM -- no new pricing math", () => {
    const genBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("genOpen && dfLive && (() => {"));
    assert.match(genBlock, /const tally = gp\.pr \? tallyPrices\(\[gp\.pr\]\) : null;/);
    assert.match(genBlock, /formatCostEstimate\(tally\)/);
    assert.match(genBlock, /costTooltip\(tally\)/);
  });

  test("the price preview is driven by the real priceShot(dfLive), never a hand-rolled fetch('/api/price', ...)", () => {
    assert.doesNotMatch(loomMobileSrc, /fetch\(["']\/api\/price["']/,
      "Loom Mobile must reuse priceShot() -- a second, independent /api/price call here would be exactly the forked pricing logic this increment's brief forbids");
    assert.match(loomMobileSrc, /priceShot\(dfLive\)\.then\(\(pr\) => /);
  });

  test("the real submit button calls generateShot(dfLive) UNMODIFIED -- no skipConfirm, no new confirm dialog, no new endpoint", () => {
    const genBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("genOpen && dfLive && (() => {"));
    assert.match(genBlock, /className="lm-genbtn"[\s\S]*?onClick=\{genSubmit\}/);
    assert.doesNotMatch(loomMobileSrc, /generateShot\(dfLive, \{\s*skipConfirm/,
      "a single, owner-initiated tap must still go through generateShot's own real price-check + confirm, same as it would for any other real single submit");
    assert.match(loomMobileSrc, /r = await generateShot\(dfLive\);/);
    assert.doesNotMatch(loomMobileSrc, /fetch\(["']\/api\/loom\/generate["']/,
      "Loom Mobile must not submit through a second, independent /api/loom/generate call -- generateShot is the one real submit path");
  });

  test("'Use an existing video instead' calls the real, already-shipped useExistingVideo(dfLive) -- no spend, no forked attach path", () => {
    const genBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("genOpen && dfLive && (() => {"));
    assert.match(genBlock, /onClick=\{\(\) => useExistingVideo\(dfLive\)\}/);
  });

  test("closing Generate or Shot Detail never touches genState/pollShot/generateShot -- both are plain local LoomMobile booleans", () => {
    // The credit-safety contract this increment's own report explains in full: genOpen/dfOpen
    // gate JSX only. The real generation-tracking state (genState) and its poll loop
    // (pollShot's recursive setTimeout chain, inside useGenerationPipeline) live in App(),
    // are passed down as a read-only prop, and are never declared or reset anywhere in
    // LoomMobile -- so no LoomMobile-local state transition (this screen closing, Shot Detail
    // closing, or the Mobile-view toggle unmounting LoomMobile entirely) can ever orphan an
    // in-flight generation.
    assert.match(loomMobileSrc, /const \[genOpen, setGenOpen\] = useState\(false\);/);
    assert.doesNotMatch(loomMobileSrc, /const \[genState, setGenState\] = useState/,
      "genState must remain a prop LoomMobile reads, never a second local copy of its own");
  });
});
