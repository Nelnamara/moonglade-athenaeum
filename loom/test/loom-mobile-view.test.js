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
    // Two pairs since 2026-08-04: Shot Detail's own, plus the Generate > Reference tab's
    // Opening/Closing pair (the punch-list item shipped that day reusing this exact
    // component). This guard still failed at "exactly one" until 2026-08-06 -- the
    // Reference-pair commit never re-ran this suite; caught by the next full run.
    assert.equal(opens.length, 2, "expected the Shot Detail + Reference-tab open FrameSlots");
    assert.equal(closes.length, 2, "expected the Shot Detail + Reference-tab close FrameSlots");
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
    // closeCastSheet (not a bare setCastSheetOpen(false)) since 2026-08-06 -- the animated
    // close plays lmSheetDown before the sheet actually unmounts.
    assert.match(loomMobileSrc, /onClick=\{\(\) => \{ dfPickFootage\(e\.c\.resultMid, e\.code\); closeCastSheet\(\); \}\}/);
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

describe("scope discipline: Fixer is now REAL (seventh and FINAL increment -- Loom Mobile is complete)", () => {
  // A prior increment's own report claimed "Fixer's touch box-drawing has zero reference
  // implementation anywhere in this codebase" and deferred it on that basis. That claim was
  // WRONG -- gallery/src/components/FixTab.jsx is the real, already-shipped Fixer for
  // regular Gallery images, using the exact same real Pointer-Events + getBoundingClientRect
  // + DISPLAY-to-ORIGINAL-pixel-scaling technique already proven in THIS component (the reel
  // scrub, increment 1; the trim handles/crop rectangle, increment 5). This describe block
  // replaces the old negative "Fixer must not exist" assertions with real, positive ones.
  test("Shot Detail / Cast & assets / Frame picker / Review & trim / Filter compare / Fixer copy ALL exist now -- Loom Mobile is complete", () => {
    assert.ok(loomMobileSrc.includes("Cast &amp; assets"), "expected the Cast & assets sheet's own tab label to exist now");
    assert.ok(loomMobileSrc.includes("Other references &amp; @tags"), "expected Shot Detail's real references section to exist now");
    assert.ok(loomMobileSrc.includes("Music / audio cue"), "expected Shot Detail's audio-cue field to exist now");
    assert.ok(loomMobileSrc.includes("Review &amp; trim"), "expected Review & trim's own screen title to exist now (fifth increment)");
    assert.ok(loomMobileSrc.includes("Art filters"), "expected Filter compare's own screen title to exist now (sixth increment)");
    assert.ok(loomMobileSrc.includes("Drag a box over the hand or face on the source."), "expected Fixer's own real hint text to exist now (seventh increment)");
  });
});

// Seventh and FINAL increment (2026-08-03): Fixer (face/hand touch-up repair), per the locked
// design's own editSubIsFixer/pickFace/pickHand/fixHintStyle/fixWarnStyle/fixKind (Loom
// Mobile.dc.html). Ported verbatim from the real, already-shipped
// gallery/src/components/FixTab.jsx -- same FIX_COLORS/FIX_MIN_PX/FIX_MAX_BOXES/scaleBoxes
// values (editCore.js), same Pointer-Events box-drawing math, same real confirm-gated submit
// through the real /api/fix endpoint (genFix, useGenerationPipeline). Closes the last
// disclosed gap in Loom Mobile's original 6-increment plan.
describe("Fixer: local, verbatim copies of FixTab.jsx's own real editCore.js constants (not a cross-directory import)", () => {
  test("FIX_COLORS/FIX_MIN_PX/FIX_MAX_BOXES match editCore.js's own real values exactly", () => {
    assert.match(src, /const FIX_COLORS = \{ face: "#b692e6", hand: "#4fc99a" \};/);
    assert.match(src, /const FIX_MIN_PX = 6;/);
    assert.match(src, /const FIX_MAX_BOXES = 20;/);
  });

  test("scaleFixBoxes is a verbatim port of editCore.js's scaleBoxes: naturalWidth/clientWidth scale, {x,y,width,height,tag} output", () => {
    assert.match(src, /const scaleFixBoxes = \(boxes, imgEl\) => \{/);
    assert.match(src, /const scale = imgEl && imgEl\.clientWidth \? \(imgEl\.naturalWidth \/ imgEl\.clientWidth\) : 1;/);
    assert.match(src, /width: Math\.round\(b\.w \* scale\), height: Math\.round\(b\.h \* scale\), tag: b\.tag,/);
  });

  test("the Fixer constants stay LOCAL copies -- editCore.js's constants are not cross-dir imported", () => {
    // Since the Loom went bundle-only (2026-08-08), real cross-directory imports from
    // ../gallery/src ARE the intended pattern -- shared modules the campaign is converging
    // (artFilters, GalleryPicker, more to come) live there and import normally. So this no
    // longer polices ALL gallery imports; it pins the ONE thing this describe block is about:
    // FixTab.jsx's editCore.js constants (FIX_COLORS/FIX_MIN_PX/FIX_MAX_BOXES/scaleBoxes)
    // must stay the verbatim LOCAL copies checked above, never an import of editCore.js.
    // ^-anchored (multiline) so it matches only a REAL import statement, not the prose
    // comment right above the local copies that quotes `import ... from ".../editCore.js"`
    // to explain why the import is deliberately absent.
    assert.doesNotMatch(src,
      /^\s*import[^\n]*from\s*["']\.\.\/gallery\/src\/gen\/editCore\.js["']/m,
      "the Fixer constants must stay LOCAL verbatim copies, not a live import of editCore.js");
  });
});

describe("Fixer: the Edit/Fixer/Enhance sub-strip is now the design's real three-way chip row", () => {
  test("editSub defaults to 'edit' and a real Fixer chip exists alongside Edit/Enhance", () => {
    assert.match(loomMobileSrc, /const \[editSub, setEditSub\] = useState\("edit"\);/);
    const editBlock = loomMobileSrc.slice(loomMobileSrc.indexOf('genTab === "Edit" && (() => {'));
    assert.match(editBlock, /className=\{"lm-tabbtn" \+ \(editSub === "edit" \? " on" : ""\)\}/);
    assert.match(editBlock, /className=\{"lm-tabbtn" \+ \(editSub === "fixer" \? " on" : ""\)\}/);
    assert.match(editBlock, /className=\{"lm-tabbtn" \+ \(editSub === "enhance" \? " on" : ""\)\}/);
    assert.match(editBlock, /onClick=\{\(\) => setEditSub\("fixer"\)\}>Fixer<\/button>/);
  });

  test("the sub-strip still reuses .lm-tabsrow/.lm-tabbtn verbatim -- no new sub-tab visual language for the third chip", () => {
    const editBlock = loomMobileSrc.slice(loomMobileSrc.indexOf('genTab === "Edit" && (() => {'));
    assert.match(editBlock, /<div className="lm-tabsrow" style=\{\{ marginBottom: 10 \}\}>/);
  });
});

describe("Fixer: source is this shot's real open frame -- same convention as the Edit sub-tab", () => {
  test("the Fixer body renders only while editSub === 'fixer', reusing the SAME `src` (c.openFrame.mediaId) the Edit sub-tab already resolves -- not a second, independently-derived source", () => {
    const editBlock = loomMobileSrc.slice(loomMobileSrc.indexOf('genTab === "Edit" && (() => {'));
    assert.match(editBlock, /const src = c\.openFrame && c\.openFrame\.mediaId;/);
    assert.match(editBlock, /\{editSub === "fixer" && \(<>/);
    const fixerBlock = editBlock.slice(editBlock.indexOf('{editSub === "fixer" && (<>'), editBlock.indexOf('{editSub === "enhance" && ('));
    assert.match(fixerBlock, /Source — this shot's open frame/);
    assert.match(fixerBlock, /\{src \? \(/, "the Fixer canvas must gate on the same real `src` the Edit sub-tab uses");
  });
});

describe("Fixer: real box-drawing canvas -- verbatim port of FixTab.jsx's paint()/onDown/onMove/onUp", () => {
  test("the canvas wires all four real pointer handlers over a same-sized <img>+<canvas> stack (.lm-fixwrap)", () => {
    assert.match(loomMobileSrc, /<div className="lm-fixwrap">/);
    assert.match(loomMobileSrc, /<img ref=\{fixImgRef\} src=\{"\/thumbs\/" \+ src \+ "\.jpg"\} alt="source"/);
    assert.match(loomMobileSrc,
      /<canvas ref=\{fixCanvasRef\}\s*\n\s*onPointerDown=\{fixDown\} onPointerMove=\{fixMove\}\s*\n\s*onPointerUp=\{fixUp\} onPointerLeave=\{fixUp\} \/>/);
  });

  test("canvas dimensions track the rendered <img>'s own clientWidth/clientHeight every paint, same as FixTab.jsx's own paint()", () => {
    assert.match(loomMobileSrc, /const w = img\.clientWidth, h = img\.clientHeight;/);
    assert.match(loomMobileSrc, /if \(cvs\.width !== w \|\| cvs\.height !== h\) \{ cvs\.width = w; cvs\.height = h; \}/);
  });

  test("boxes are drawn with the real per-tag FIX_COLORS, verbatim strokeRect/fillText port", () => {
    assert.match(loomMobileSrc, /ctx\.strokeStyle = FIX_COLORS\[b\.tag\] \|\| FIX_COLORS\.face;/);
    assert.match(loomMobileSrc, /ctx\.strokeRect\(b\.x, b\.y, b\.w, b\.h\);/);
  });

  test("the drag-box coordinates come from a real getBoundingClientRect + clientX/clientY off the canvas, not a fake/stubbed value", () => {
    assert.match(loomMobileSrc, /const r = fixCanvasRef\.current\.getBoundingClientRect\(\);/);
    assert.match(loomMobileSrc, /return \{ x: e\.clientX - r\.left, y: e\.clientY - r\.top \};/);
  });

  test("onUp applies FixTab.jsx's own minimum-drag-size and max-box-count rules verbatim (FIX_MIN_PX/FIX_MAX_BOXES), not re-derived values", () => {
    assert.match(loomMobileSrc, /if \(d\.w > FIX_MIN_PX && d\.h > FIX_MIN_PX\) \{/);
    assert.match(loomMobileSrc, /if \(fixBoxes\.length >= FIX_MAX_BOXES\) \{/);
    assert.match(loomMobileSrc, /setFixBoxes\(\(old\) => old\.concat\(\[\{ x: d\.x, y: d\.y, w: d\.w, h: d\.h, tag: fixTag \}\]\)\);/);
  });

  test("setPointerCapture is used on drag-start, the same real mobile convention every other pointer-drag gesture in this component already uses", () => {
    const fixerStateBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("const [fixTag, setFixTag]"), loomMobileSrc.indexOf("// ---- Filter compare -- sixth and FINAL increment"));
    assert.match(fixerStateBlock, /try \{ e\.currentTarget\.setPointerCapture\(e\.pointerId\); \} catch \(err\) \{\}/);
  });

  test("boxes reset whenever the source image changes (new shot selected, or this shot's open frame replaced) -- a stale box is never silently carried onto a different picture", () => {
    assert.match(loomMobileSrc,
      /useEffect\(\(\) => \{\s*\n\s*setFixBoxes\(\[\]\);\s*\n\s*\}, \[dfLive && dfLive\.c\.id, dfLive && dfLive\.c\.openFrame && dfLive\.c\.openFrame\.mediaId\]\);/);
  });

  test("Face/Hand tag chips reuse .lm-modechips/.lm-modechip (the same chip language MODES/CONNECT already use), colored per-tag exactly like FixTab.jsx's own active chip", () => {
    assert.match(loomMobileSrc, /className=\{"lm-modechip" \+ \(fixTag === t \? " on" : ""\)\}/);
    assert.match(loomMobileSrc, /style=\{fixTag === t \? \{ borderColor: FIX_COLORS\[t\], color: FIX_COLORS\[t\] \} : null\}/);
  });
});

describe("Fixer: the real, mandatory spend warning and confirm-gated submit through the real /api/fix endpoint", () => {
  test("the warning text is byte-for-byte the locked design's own real fixWarnStyle copy", () => {
    assert.match(loomMobileSrc, /A fix can't be card-covered — it always spends, and always asks first\./);
  });

  test("the Fix button label mirrors the locked design's own `Fix {{ fixKind }}` interpolation (lowercase tag)", () => {
    assert.match(loomMobileSrc, /\{busyF \? \(gf\.msg \|\| "fixing…"\) : "✦ Fix " \+ fixTag\}/);
  });

  test("genFix is threaded through as a real prop, not re-invented inside LoomMobile", () => {
    const sigMatch = loomMobileSrc.match(/function LoomMobile\(\{([\s\S]*?)\}\)\s*\{/);
    assert.ok(sigMatch, "expected to find LoomMobile's function signature");
    for (const name of ["genFixState", "setGenFixState", "genFix"]) {
      assert.match(sigMatch[1], new RegExp(`\\b${name}\\b`), `LoomMobile's signature should destructure ${name}`);
    }
    const loomMobileCall = src.match(/<LoomMobile\b[\s\S]*?\/>/);
    assert.ok(loomMobileCall, "expected to find the <LoomMobile .../> call site");
    for (const prop of ["genFixState={genFixState}", "setGenFixState={setGenFixState}", "genFix={genFix}"]) {
      assert.ok(loomMobileCall[0].includes(prop), `expected "${prop}" at the <LoomMobile .../> call site`);
    }
  });

  test("the submit button calls the real genFix(dfLive, scaleFixBoxes(...)), passing already-scaled ORIGINAL-pixel boxes -- no DOM ref crosses into useGenerationPipeline", () => {
    assert.match(loomMobileSrc, /onClick=\{\(\) => genFix\(dfLive, scaleFixBoxes\(fixBoxes, fixImgRef\.current\)\)\}/);
  });

  test("genFix lives in useGenerationPipeline, submits to the real /api/fix endpoint via runGen (the same submit/poll/register machinery genEdit/genRef already share)", () => {
    assert.match(src, /const genFix = async \(entry, scaledBoxes\) => \{/);
    assert.match(src, /runGen\(setGenFixState, c\.id, "\/api\/fix", \{ source: src, boxes: scaledBoxes \}, null, "",/);
  });

  test("genFix runs its own fresh mode:\"fix\" price check right before its confirm -- the real, read-only cost check, not skipped", () => {
    // Re-anchored 2026-08-23: the check used to be a hand-rolled fetch here and is now the
    // Loom's one price call site (priceBody -> gen/priceRequest.js). What matters and is
    // unchanged: genFix asks for THIS Fix's real price, freshly, before its own confirm --
    // never a cached or skipped one, and never a different body than the one it submits.
    const genFixBlock = src.slice(src.indexOf("const genFix = async (entry, scaledBoxes) => {"), src.indexOf("// Batch-generate the whole board"));
    assert.match(genFixBlock, /const pr = await priceBody\(\{ mode: "fix", source: src, boxes: scaledBoxes \}\);/);
    const priceAt = genFixBlock.indexOf("const pr = await priceBody(");
    const confirmAt = genFixBlock.indexOf("if (!window.confirm(");
    assert.ok(priceAt >= 0 && confirmAt > priceAt, "the price check must run BEFORE the confirm");
  });

  test("the confirm wording is ported VERBATIM from FixTab.jsx's own run() -- 'ALWAYS spends' / 'never covered by a free card', never confirmSpend's generic phrasing", () => {
    const genFixBlock = src.slice(src.indexOf("const genFix = async (entry, scaledBoxes) => {"), src.indexOf("// Batch-generate the whole board"));
    assert.match(genFixBlock, /"The price could not be verified, and a Fix ALWAYS spends credits \(no free card can ever cover it\)\."/);
    assert.match(genFixBlock, /"This will spend " \+ Number\(priced\)\.toLocaleString\(\) \+ " credits — a Fix is never covered by a free card\."/);
    assert.match(genFixBlock, /if \(!window\.confirm\(/, "the real window.confirm gate must fire before any submit");
  });

  test("genFix passes quoteBody:null to runGen -- it must never trigger runGen's OWN confirmSpend gate on top of its own real, Fix-correct confirm above", () => {
    // The parameter is positional and unchanged; only its NAME moved (priceBody -> quoteBody,
    // 2026-08-23), because priceBody is now the Loom's one price call site.
    const genFixBlock = src.slice(src.indexOf("const genFix = async (entry, scaledBoxes) => {"), src.indexOf("// Batch-generate the whole board"));
    assert.match(genFixBlock, /runGen\(setGenFixState, c\.id, "\/api\/fix", \{ source: src, boxes: scaledBoxes \}, null,/,
      "quoteBody must be null so runGen's own confirmSpend (generic, free-card-implying wording) never runs a second confirm");
  });

  test("a missing open-frame source or an empty box list is refused BEFORE any price check or confirm, same defensive-gate shape as genEdit", () => {
    const genFixBlock = src.slice(src.indexOf("const genFix = async (entry, scaledBoxes) => {"), src.indexOf("// One fresh /api/price check"));
    assert.match(genFixBlock, /if \(!src\) \{ setGenFixState/);
    assert.match(genFixBlock, /if \(!scaledBoxes \|\| !scaledBoxes\.length\) \{ setGenFixState/);
  });
});

describe("Fixer: real cost PREVIEW and real result routing, mirroring the Edit/Reference tabs' own conventions", () => {
  test("the price preview debounces a real mode:\"fix\" price check, gated on genOpen/genTab/editSub, same convention as imgPrice/editPrice/refPrice", () => {
    assert.match(loomMobileSrc, /const \[genFixPrice, setGenFixPrice\] = useState\(\{\}\);/);
    assert.match(loomMobileSrc, /if \(!genOpen \|\| genTab !== "Edit" \|\| editSub !== "fixer" \|\| !dfLive\) return;/);
    // Re-anchored 2026-08-23: was a hand-rolled fetch of /api/price, now the Loom's one price
    // call site. The BODY is the assertion -- this preview must price the same mode:"fix" shape
    // genFix submits -- and it is unchanged; only the transport under it moved.
    assert.match(loomMobileSrc,
      /priceBody\(\{ mode: "fix", source: src, boxes: scaleFixBoxes\(fixBoxes, fixImgRef\.current\) \}\)[\s\S]{0,200}\}, 250\);/,
      "the preview must price the same mode:\"fix\" body genFix submits, and stay debounced");
  });

  test("the preview line reuses the SAME priceLine/priceTitle helpers the Image/Edit/Reference tabs already share -- no new formatter", () => {
    assert.match(loomMobileSrc, /priceLine\(genFixPrice, c\.id, "Drag a box over a hand or face to see the cost\."\)/);
    assert.match(loomMobileSrc, /priceTitle\(genFixPrice, c\.id\)/);
  });

  test("a completed Fix result routes into open/close frame or cast via the real, generic routeGen -- same function genEdit/genRef already use, not a forked router", () => {
    assert.match(loomMobileSrc, /routeGen\(genFixState, setGenFixState, dfLive, "open", c\.id\)/);
    assert.match(loomMobileSrc, /routeGen\(genFixState, setGenFixState, dfLive, "close", c\.id\)/);
    assert.match(loomMobileSrc, /routeGen\(genFixState, setGenFixState, dfLive, "cast", c\.id\)/);
  });
});

// Fifth increment (2026-08-03): Review & trim, per the locked design's own reviewFor/
// cropping/playing state (Loom Mobile.dc.html -- see its own _trimInMove/_trimOutMove/
// _cropDragMove/_doSplit/_togglePlay implementations). A crop rectangle dragged via real
// pointer events, two trim handles on a track below, a playhead scrub track, and a real
// <video> preview -- opened from the board's own real ▶ badge on a finished shot. Filter
// compare (the locked design's next and final screen) was still out of scope as of this
// increment -- now built by the sixth increment below.
describe("Review & trim: the board's own real ▶ affordance opens it on a finished shot", () => {
  test("canReview is the real, defensive statusOf(c)+resultMid check, not the mockup's bare c.st === 'done'", () => {
    assert.match(loomMobileSrc, /const canReview = st === "done" && !!e\.c\.resultMid;/);
  });

  test("the badge is a real sibling <button>, never nested inside the .lm-card <button> beneath it", () => {
    assert.match(loomMobileSrc, /\{canReview && \(\s*<button type="button" className="lm-reviewbadge"/);
  });

  test("tapping the badge selects the shot and opens Review, resetting the prior shot's local playback/crop state", () => {
    assert.match(loomMobileSrc,
      /setSelShot\(e\.c\.id\); setReviewOpen\(true\);\s*\n\s*setReviewCropping\(false\); setReviewPlaying\(false\);\s*\n\s*setReviewDur\(0\); setReviewCur\(0\);/);
  });
});

describe("Review & trim: real data, real live-lookup safety (mirrors dfLive exactly)", () => {
  test("reviewLive reuses selShot/entries.find() -- no second 'which shot' id invented (the design's own local reviewFor)", () => {
    assert.match(loomMobileSrc, /const reviewLive = reviewOpen \? entries\.find\(\(x\) => x\.c\.id === selShot\) : null;/);
  });

  test("a stale reference (the shot vanished out from under it) closes Review instead of rendering blank", () => {
    assert.match(loomMobileSrc, /if \(reviewOpen && !reviewLive\) \{ setReviewOpen\(false\); \}/);
  });

  test("the real <video> element points at this shot's actual rendered clip, the same /video-file/ route ShotPreview/SequencePlayer already use", () => {
    assert.match(loomMobileSrc, /src=\{"\/video-file\/" \+ c\.resultMid\}/);
  });

  test("trimIn/trimOut/crop are the REAL, already-existing card fields (loom-mutations.js: buildDuplicateCard/importedFootagePatch/splitCardAt; loom-core.js: buildExportClips) -- nothing new was added to the data model", () => {
    assert.match(loomMobileSrc, /const trimIn = c\.trimIn \|\| 0;/);
    assert.match(loomMobileSrc, /const trimOut = c\.trimOut != null \? c\.trimOut : dur;/);
    assert.match(loomMobileSrc, /const crop = c\.crop \|\| \{ x: 0\.35, y: 0\.35, w: 0\.3, h: 0\.3 \};/);
  });
});

describe("Review & trim: trim-handle pointer-drag math -- real fraction-of-track, design's own clamp formulas", () => {
  test("both trim handles wire real pointer handlers, captured via setPointerCapture (not a no-op)", () => {
    assert.match(loomMobileSrc, /onPointerDown=\{trimInStart\} onPointerMove=\{trimInMove\} onPointerUp=\{trimInEnd\}/);
    assert.match(loomMobileSrc, /onPointerDown=\{trimOutStart\} onPointerMove=\{trimOutMove\} onPointerUp=\{trimOutEnd\}/);
    const hits = loomMobileSrc.match(/e\.currentTarget\.setPointerCapture\(e\.pointerId\)/g) || [];
    assert.ok(hits.length >= 4, "expected setPointerCapture on all four review drags (trim-in, trim-out, scrub, crop)");
  });

  test("the fraction is read off the STATIC track (reviewTrimTrackRef), not the moving handle the design's own _trimInMove/_trimOutMove read", () => {
    assert.match(loomMobileSrc, /const r = reviewTrimTrackRef\.current\.getBoundingClientRect\(\);/);
    assert.match(loomMobileSrc, /r\.width \? Math\.max\(0, Math\.min\(1, \(e\.clientX - r\.left\) \/ r\.width\)\) : 0;/);
  });

  test("the minimum-gap clamp is the design's own real math verbatim (0.05, in fraction space)", () => {
    assert.match(loomMobileSrc, /const newFrac = Math\.max\(0, Math\.min\(trimFrac\(e\), outFrac - 0\.05\)\);/);
    assert.match(loomMobileSrc, /const newFrac = Math\.min\(1, Math\.max\(trimFrac\(e\), inFrac \+ 0\.05\)\);/);
  });

  test("the resulting fraction is converted to ABSOLUTE SECONDS before patching the real card field (the one disclosed unit adaptation -- the design's own model is 0..1 fractions, this codebase's trimIn/trimOut never are)", () => {
    assert.match(loomMobileSrc, /const t = newFrac \* dur;\s*\n\s*reviewPatch\(\(cc\) => \(\{ \.\.\.cc, trimIn: t \}\)\);/);
    assert.match(loomMobileSrc, /const t = newFrac \* dur;\s*\n\s*reviewPatch\(\(cc\) => \(\{ \.\.\.cc, trimOut: t \}\)\);/);
  });

  test("the readout renders both real seconds values, same one-decimal format as the design's own trimInLabel/trimOutLabel", () => {
    assert.match(loomMobileSrc, /const fmtT = \(s\) => \(s \|\| 0\)\.toFixed\(1\) \+ "s";/);
    assert.match(loomMobileSrc, /\{fmtT\(trimIn\)\} &rarr; \{fmtT\(trimOut\)\}/);
  });
});

describe("Review & trim: crop-rectangle pointer-drag math -- verbatim port of the design's own _cropFrac/_cropDragMove", () => {
  test("the fraction is read off the STATIC preview-wrap container via parentElement, exactly like the design's own _cropFrac (this one had no self-recentering bug to fix)", () => {
    assert.match(loomMobileSrc, /const r = e\.currentTarget\.parentElement\.getBoundingClientRect\(\);/);
  });

  test("the clamp is the design's own real math verbatim: f.x/f.y minus the 0.15 half-box offset, capped at 0.68 so the fixed-size box stays on-frame", () => {
    assert.match(loomMobileSrc, /x: Math\.max\(0, Math\.min\(f\.x - 0\.15, 0\.68\)\),/);
    assert.match(loomMobileSrc, /y: Math\.max\(0, Math\.min\(f\.y - 0\.15, 0\.68\)\),/);
  });

  test("the crop rect only renders while actively cropping, matching the design's own sc-if gate", () => {
    assert.match(loomMobileSrc, /\{reviewCropping && \(\s*\n\s*<div className="lm-review-croprect"/);
  });

  test("the Crop/Done toggle button label flips exactly like the design's own cropLabel", () => {
    assert.match(loomMobileSrc, /onClick=\{\(\) => setReviewCropping\(\(v\) => !v\)\}>&#9974; \{reviewCropping \? "Done" : "Crop"\}<\/button>/);
  });
});

describe("Review & trim: split-at-playhead calls the REAL splitCardAt-backed mutator", () => {
  test("splitShot is threaded through as a real prop, the same function desktop's ShotPreview.onSplit already calls (not re-derived)", () => {
    const sigMatch = loomMobileSrc.match(/function LoomMobile\(\{([\s\S]*?)\}\)\s*\{/);
    assert.ok(sigMatch, "expected to find LoomMobile's function signature");
    assert.match(sigMatch[1], /\bsplitShot\b/, "LoomMobile's signature should destructure splitShot");
    const loomMobileCall = src.match(/<LoomMobile\b[\s\S]*?\/>/);
    assert.ok(loomMobileCall, "expected to find the <LoomMobile .../> call site");
    assert.ok(loomMobileCall[0].includes("splitShot={splitShot}"), "expected splitShot={splitShot} at the <LoomMobile .../> call site");
  });

  test("doSplit uses the same 0.15s edge guard and the same message text as ShotPreview's own doSplit -- reused, not reinvented", () => {
    assert.match(loomMobileSrc, /if \(t > trimIn \+ 0\.15 && t < trimOut - 0\.15\) \{ splitShot\(reviewLive, t\); closeReview\(\); \}/);
    assert.match(loomMobileSrc, /alert\("Move the playhead to where you want the cut first \(not at either edge\)\."\)/);
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
    // genFix appended (seventh increment, 2026-08-03) -- same return value, same convention.
    assert.match(src, /generateShot, pollShot, useExistingVideo, genImage, routeImg, genEdit, genRef, genFix, routeGen, batchGenerate,\s*\n\s*costEstimate, refreshEstimate, priceShot,/);
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

  test("the Video tab's price preview is still driven by the real priceShot(dfLive), untouched by the fourth increment", () => {
    // Other price checks legitimately exist elsewhere in LoomMobile (the Image/Edit/Reference
    // tabs added in the fourth increment -- see that increment's own describe block below,
    // which asserts those calls mirror LoomV2's own priceInto bodies verbatim, not a new
    // pricing shape). Since 2026-08-23 they all go through priceBody, the Loom's one price
    // call site. This test narrows to what it actually protects: the VIDEO tab's cost line
    // specifically must still go through priceShot(dfLive) -- the SHOT-shaped price, built by
    // shotPayload -- never a hand-built body of its own.
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

describe("Image/Edit/Reference tabs (fourth increment, 2026-08-03) -- LoomV2's own GEN_ICONS rail, ported", () => {
  test("a 4-tab strip mirrors LoomV2's own GEN_ICONS order (Image, Edit, Reference, Video)", () => {
    const genBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("genOpen && dfLive && (() => {"));
    assert.match(genBlock, /\{\["Image", "Edit", "Reference", "Video"\]\.map\(\(t\) => \(/);
    assert.match(genBlock, /onClick=\{\(\) => setGenTab\(t\)\}/);
    assert.match(loomMobileSrc, /const \[genTab, setGenTab\] = useState\("Video"\);/,
      "must default to Video, matching LoomV2's own const [tab, setTab] = useState(\"Video\") default");
  });

  test("Image/Edit/Reference generation state and setters are threaded through as real props, never re-invented", () => {
    const sigMatch = loomMobileSrc.match(/function LoomMobile\(\{([\s\S]*?)\}\)\s*\{/);
    assert.ok(sigMatch, "expected to find LoomMobile's function signature");
    for (const name of ["genImgState", "imgModel", "setImgModel", "imgLoras", "setImgLoras", "imgAdv", "setImgAdv",
      "modelDefaults", "setModelDefaults", "genImage", "routeImg",
      "genEditState", "setGenEditState", "genRefState", "setGenRefState", "genEdit", "genRef", "routeGen"]) {
      assert.match(sigMatch[1], new RegExp(`\\b${name}\\b`), `LoomMobile's signature should destructure ${name}`);
    }
  });

  test("the <LoomMobile .../> call site passes every one of those through from the SAME useGenerationPipeline instance App() already drives", () => {
    const loomMobileCall = src.match(/<LoomMobile\b[\s\S]*?\/>/);
    assert.ok(loomMobileCall, "expected to find the <LoomMobile .../> call site");
    for (const prop of ["genImgState={genImgState}", "imgModel={imgModel}", "setImgModel={setImgModel}",
      "imgLoras={imgLoras}", "setImgLoras={setImgLoras}", "imgAdv={imgAdv}", "setImgAdv={setImgAdv}",
      "modelDefaults={modelDefaults}", "setModelDefaults={setModelDefaults}", "genImage={genImage}", "routeImg={routeImg}",
      "genEditState={genEditState}", "setGenEditState={setGenEditState}", "genRefState={genRefState}", "setGenRefState={setGenRefState}",
      "genEdit={genEdit}", "genRef={genRef}", "routeGen={routeGen}"]) {
      assert.ok(loomMobileCall[0].includes(prop), `expected "${prop}" at the <LoomMobile .../> call site`);
    }
  });

  test("Image/Edit/Reference submit through the real genImage(dfLive)/genEdit(dfLive)/genRef(dfLive) -- no forked submit, no new endpoint", () => {
    assert.match(loomMobileSrc, /onClick=\{\(\) => genImage\(dfLive\)\}/);
    assert.match(loomMobileSrc, /onClick=\{\(\) => genEdit\(dfLive\)\}/);
    assert.match(loomMobileSrc, /onClick=\{\(\) => genRef\(dfLive\)\}/);
    assert.doesNotMatch(loomMobileSrc, /fetch\(["']\/api\/generate["']/,
      "genImage() already owns the real /api/generate submit -- LoomMobile must not duplicate it");
    assert.doesNotMatch(loomMobileSrc, /fetch\(["']\/api\/edit["']/,
      "genEdit()/genRef() already own the real submit via runGen() -- LoomMobile must not duplicate it");
    // Scoped to the Generate screen's own block, not the whole component -- the completeness-
    // pass kebab actions sheet (added after this fourth increment) legitimately calls the
    // REAL window.confirm elsewhere in this file, porting LoomV2's own real delete-confirm
    // gate verbatim (see that describe block below). This assertion's actual intent is
    // narrower than "no window.confirm anywhere": Image/Edit/Reference submit specifically
    // must not re-implement confirmSpend's own gate, so it only inspects Generate's own block.
    const genBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("genOpen && dfLive && (() => {"));
    assert.doesNotMatch(genBlock, /window\.confirm\(/,
      "confirmSpend's fail-closed window.confirm gate lives inside genImage/genEdit/genRef themselves -- LoomMobile must not re-implement it");
  });

  test("routing a result into open/close frame or cast calls the real routeImg/routeGen, targeting dfLive itself (this screen is always bound to a real shot)", () => {
    assert.match(loomMobileSrc, /onClick=\{\(\) => routeImg\(dfLive, "open", c\.id\)\}/);
    assert.match(loomMobileSrc, /onClick=\{\(\) => routeImg\(dfLive, "close", c\.id\)\}/);
    assert.match(loomMobileSrc, /onClick=\{\(\) => routeImg\(dfLive, "cast", c\.id\)\}/);
    assert.match(loomMobileSrc, /routeGen\(genEditState, setGenEditState, dfLive, "open", c\.id\)/);
    assert.match(loomMobileSrc, /routeGen\(genRefState, setGenRefState, dfLive, "cast", c\.id\)/);
  });

  test("the Image/Edit/Reference price previews mirror LoomV2's own priceInto body shapes verbatim -- no new pricing math", () => {
    assert.match(loomMobileSrc, /buildImgGenBody\(imgModel, imgLoras, imgAdv, prompt\)/);
    assert.match(loomMobileSrc, /\{ mode: "edit", source: editSrcMid, instruction, edit_model: "edit-pro" \}/);
    assert.match(loomMobileSrc, /\{ mode: "edit", source: refMids\[0\], sources: refMids, instruction: prompt, edit_model: "reference-pro" \}/);
    assert.match(loomMobileSrc, /tallyPrices\(\[p\.pr\]\)/, "the preview text must reuse the SAME tallyPrices/formatCostEstimate helpers, not a new formatter");
  });

  test("the model/LoRA picker mounts the SAME real <ModelPicker> component LoomV2's own floating overlay uses (ported from <mg-model-picker>: attrs->props, mg-pick CustomEvent->onPick/onToggle, controlled value/selected)", () => {
    // Base picker: kind/visible props (was kind attr + the ensureSearched display:none dance),
    // value={imgModel} controlled selection (was the element's internal _selected), and the
    // mg-pick CustomEvent is now the onPick={onBasePick} prop (bindPicker's ref-callback logic
    // survives verbatim as onBasePick).
    assert.match(loomMobileSrc, /<ModelPicker kind="base" visible=\{pickerKind === "base"\} value=\{imgModel\} onPick=\{onBasePick\}/);
    // LoRA picker: multi mode + baseType prop (was the base-type attr), controlled selected={imgLoras}
    // array (was the element's internal _selected + deselect()), and the multi mg-pick detail
    // {model,selected} is now onToggle={onLoraPick}(model, selected) (bindLoraPicker survives as onLoraPick).
    assert.match(loomMobileSrc, /<ModelPicker kind="lora" multi baseType=\{\(imgModel && imgModel\.model_type\) \|\| ""\} visible=\{pickerKind === "lora"\} selected=\{imgLoras\} onToggle=\{onLoraPick\}/);
  });

  test("Image tab field parity: Aspect/Size/Custom W×H/Mode/Count/Seed/High-priority/Prompt-helper all exist, same as LoomV2's own Image tab (L536)", () => {
    for (const label of ["Aspect", "Size &middot; long edge", "Custom W&times;H", "Seed &middot; blank = random",
      "High priority &middot; Turbo (faster)", "Prompt helper"]) {
      assert.ok(loomMobileSrc.includes(label), `expected the Image tab to render "${label}"`);
    }
    assert.match(loomMobileSrc, /resolveGenDims\(imgAdv\)/);
  });
});

describe("Credit safety: the drawer's own component-local poll vs. this increment's fix (fourth increment)", () => {
  test("useGenerationPipeline's resume-on-reload effect also depends on mobileUI, so a <mg-generate-drawer>-submitted Video render is re-attached the instant the toggle unmounts it", () => {
    assert.match(src, /function useGenerationPipeline\(\{ project, thumbs, setCard, setCardStatus, setAssets, openPick, activeId, mobileUI \}\)/);
    assert.match(src, /\}, \[activeId, mobileUI\]\);\s*\/\/ eslint-disable-line/);
  });

  test("App() passes its own mobileUI into useGenerationPipeline, not a stale/local copy", () => {
    assert.match(src, /= useGenerationPipeline\(\{ project, thumbs, setCard, setCardStatus, setAssets, openPick, activeId, mobileUI \}\);/);
  });

  test("genImage/genEdit/genRef's own polls are plain setTimeout chains (pollImg/pollTaskWithCeiling), never a DOM element's lifecycle -- confirmed, not just asserted", () => {
    // pollTaskWithCeiling is a closure inside useGenerationPipeline itself -- no
    // connectedCallback/disconnectedCallback anywhere near it, unlike mg-generate-drawer.js's
    // own _poll (which explicitly tears down _pollTimers on disconnect -- see that file).
    assert.match(src, /const pollTaskWithCeiling = \(tid, setState, cardId\) => \{/);
    assert.doesNotMatch(src.slice(src.indexOf("const pollTaskWithCeiling"), src.indexOf("const pollImg = (cardId, tid)")),
      /disconnectedCallback|connectedCallback/,
      "pollTaskWithCeiling must never be tied to a custom element's connect lifecycle");
  });
});

// Sixth and FINAL increment (2026-08-03): Filter compare, per the locked design's own
// "Art filters" screen (Loom Mobile.dc.html -- filterCompareOpen/fcSkinFilters/
// fcPixaiFilters/fcStrength/fcAngle/fcClear/fcSaveLibrary/FILTER_SETS). Reached from
// Generate's Edit tab via a new Edit/Enhance sub-strip, matching BOTH the design's own
// editSubChips AND the real, already-shipped GenerateDrawer.jsx's identical Edit/Fixer/
// Enhance mgdock-subtabs. Applies PixAI's real, free, client-side art-filter library
// (static/mg-art-filters.js) to the shot's real open frame, with a genuine Original/Preview
// comparison (a real <img> both times, a live AF.applyPreview CSS-overlay composite on the
// right) and genuine persistence onto the shot card (filter/filterStrength/filterAngle --
// new, optional fields, same "not in newCard(), read with a fallback" convention as Review &
// trim's own `crop`). This is the last screen in the locked design -- Loom Mobile is now
// complete, minus Fixer (see the "scope discipline" describe block above for why that stays
// out).
describe("Filter compare: reused from the real art-filter engine (imported), not forked", () => {
  test("AF is the imported MgArtFilters engine -- not a forked blend/gradient recipe", () => {
    // Since 2026-08-08 the engine is a bundled ES module (gallery/src/art/artFilters.js),
    // imported at the top of master-storyboard.jsx, not read off a window global.
    assert.match(loomMobileSrc, /const AF = MgArtFilters;/);
  });

  test("the swatch grid is built from the real AF.groups() -- not the design mockup's own hardcoded FILTER_SETS/GALLERY_POOL-style placeholder", () => {
    assert.match(loomMobileSrc, /const fcGroups = AF \? AF\.groups\(\) : \[\];/);
    // Checking for an actual array DECLARATION, not the bare name -- this increment's own
    // disclosure comments legitimately CITE "FILTER_SETS" in prose (the design's own search
    // hint, quoting its identifier so a reader can find the corresponding design markup),
    // the same way they cite "fcSkinFilters"/"fcPixaiFilters" two lines above. What must
    // never exist is the mockup's own hardcoded 12-entry array itself.
    assert.doesNotMatch(loomMobileSrc, /const FILTER_SETS = \[/, "the locked design's own simplified 12-entry placeholder array (name + two flat hex stops, one hardcoded mix-blend-mode) must not be reproduced here -- the real recipe data comes from AF.groups()/AF.get() instead");
  });

  test("each tile paints via the real AF.renderSwatch(el, id) -- no hand-rolled two-color CSS gradient standing in for it", () => {
    assert.match(loomMobileSrc, /if \(el && !el\._mgafPainted\) \{ AF\.renderSwatch\(el, id\); el\._mgafPainted = true; \}/);
  });

  test("the live preview composites via the real AF.applyPreview/AF.clearPreview -- CSS overlay + mix-blend-mode, per mg-art-filters.js's own documented approach, not a fake color swatch", () => {
    assert.match(loomMobileSrc, /AF\.clearPreview\(host\);/);
    assert.match(loomMobileSrc, /if \(fcActive\) AF\.applyPreview\(host, fcActive, \{ strength: fcStrength, angle: fcAngle \}\);/);
  });

  test("a real <img> renders on BOTH sides (Original and Preview) -- never a flat color div standing in for the image", () => {
    assert.match(loomMobileSrc, /<img className="lm-fc-img" src=\{fcSrc\} alt="original" \/>/);
    assert.match(loomMobileSrc, /<img ref=\{fcImgRef\} className="lm-fc-img" src=\{fcSrc\} alt="preview" \/>/);
  });

  test("the source is this shot's REAL open frame (frameSrc(c.openFrame)), the same helper Shot Detail/Edit already use -- not a fabricated tint", () => {
    assert.match(loomMobileSrc, /const fcSrc = frameSrc\(c\.openFrame\);/);
  });
});

describe("Filter compare: reached from Generate's Edit tab via a real Edit/Fixer/Enhance sub-strip (not Shot Detail or the reel directly)", () => {
  test("editSub state exists and defaults to 'edit', matching the sub-strip's own default chip", () => {
    assert.match(loomMobileSrc, /const \[editSub, setEditSub\] = useState\("edit"\);/);
  });

  test("the sub-strip reuses .lm-tabsrow/.lm-tabbtn verbatim -- the same classes the Cast sheet's Cast/Footage strip and the model picker's Models/LoRAs strip already use, not a new visual language", () => {
    const editBlock = loomMobileSrc.slice(loomMobileSrc.indexOf('genTab === "Edit" && (() => {'));
    assert.match(editBlock, /<div className="lm-tabsrow" style=\{\{ marginBottom: 10 \}\}>/);
    assert.match(editBlock, /className=\{"lm-tabbtn" \+ \(editSub === "edit" \? " on" : ""\)\}/);
    assert.match(editBlock, /className=\{"lm-tabbtn" \+ \(editSub === "enhance" \? " on" : ""\)\}/);
  });

  test("the Enhance sub-tab's 'Open filters' button calls the real openFilterCompare (not a stub)", () => {
    assert.match(loomMobileSrc, /<button type="button" className="lm-openfiltersbtn" onClick=\{openFilterCompare\}>&#9673; Open filters<\/button>/);
  });

  // Fixer WAS deliberately excluded from this sub-strip through the sixth increment (see the
  // "scope discipline" describe block above, and its own updated comment) -- now built as the
  // seventh and FINAL increment; see the dedicated "Fixer: ..." describe blocks below for its
  // own coverage. This block only still asserts Edit/Enhance's own unrelated behavior above.
  test("Fixer IS one of the sub-strip's chips now, matching the locked design's own three-way editSubChips", () => {
    const editBlock = loomMobileSrc.slice(loomMobileSrc.indexOf('genTab === "Edit" && (() => {'), loomMobileSrc.indexOf('{genTab === "Reference"'));
    assert.match(editBlock, /editSub === "fixer"/);
  });
});

describe("Filter compare: genuine persistence onto the real shot/card data (no fake 'saved' state)", () => {
  test("opening seeds the candidate from the card's ALREADY-SAVED fields (reopen shows the persisted choice, not a blank slate)", () => {
    assert.match(loomMobileSrc, /const openFilterCompare = \(\) => \{/);
    assert.match(loomMobileSrc, /setFcActive\(dfLive\.c\.filter \|\| null\);/);
    assert.match(loomMobileSrc, /setFcStrength\(dfLive\.c\.filterStrength != null \? dfLive\.c\.filterStrength : 1\);/);
    assert.match(loomMobileSrc, /setFcAngle\(dfLive\.c\.filterAngle != null \? dfLive\.c\.filterAngle : 180\);/);
  });

  test("filter/filterStrength/filterAngle are NOT added to newCard() -- same optional-field-with-fallback convention as Review & trim's own `crop`, nothing forked into the base card shape", () => {
    const newCardMatch = src.match(/function newCard\(extra = \{\}\) \{[\s\S]*?\n\}/);
    assert.ok(newCardMatch, "expected to find newCard()");
    assert.doesNotMatch(newCardMatch[0], /\bfilter\b|\bfilterStrength\b|\bfilterAngle\b/,
      "filter/filterStrength/filterAngle must stay optional card fields (read with a fallback), not required base-shape fields");
  });

  test("Save genuinely writes filter/filterStrength/filterAngle onto the real card via dfPatch (the same setCard mutation every other Shot Detail/Generate field already uses) -- no new endpoint, no network call", () => {
    assert.match(loomMobileSrc, /const fcSave = \(\) => \{/);
    assert.match(loomMobileSrc, /dfPatch\(\(cc\) => \(\{ \.\.\.cc, filter: fcActive, filterStrength: fcStrength, filterAngle: fcAngle \}\)\);/);
  });

  test("'No filter' (fcClear) genuinely, immediately removes the SAVED filter via dfPatch -- not just a pending in-memory reset that Close would silently discard", () => {
    assert.match(loomMobileSrc, /const fcClear = \(\) => \{ setFcActive\(null\); dfPatch\(\(cc\) => \(\{ \.\.\.cc, filter: null \}\)\); \};/);
  });

  test("Close/back (closeFilterCompare) is a plain cancel -- it must NOT call dfPatch/setCard, so an unsaved candidate can be backed out of", () => {
    const closeLine = loomMobileSrc.match(/const closeFilterCompare = \(\) => setFcOpen\(false\);/);
    assert.ok(closeLine, "expected closeFilterCompare to be a one-line setFcOpen(false), no patch call");
  });

  test("no new /api endpoint, no fetch, backs Filter compare -- these are plain card fields, matching mg-art-filters.js's own 'nothing sent, nothing spent' contract", () => {
    const fcBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("Filter compare -- sixth and FINAL increment"));
    assert.doesNotMatch(fcBlock, /fetch\(/, "Filter compare must never touch the network -- it is free, offline, client-side compositing only");
  });
});

describe("Filter compare: real live-lookup safety (reuses dfLive, no second 'which shot' id invented)", () => {
  test("the screen only renders while fcOpen && dfLive, exactly like genOpen's own reuse of dfLive", () => {
    assert.match(loomMobileSrc, /\{fcOpen && dfLive && \(\(\) => \{/);
  });

  test("openFilterCompare guards on dfLive itself, never assumes a shot is selected", () => {
    const openBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("const openFilterCompare = () => {"), loomMobileSrc.indexOf("const closeFilterCompare"));
    assert.match(openBlock, /if \(!dfLive\) return;/);
  });
});

// Completeness-pass addition (2026-08-03): the per-shot-card kebab (⋮) actions sheet --
// Move up / Move down / Duplicate / Delete / Cancel -- was fully specified in the locked
// design (Loom Mobile.dc.html: onKebab/kebabStyle/actionsOpen/closeActions/actMoveUp/
// actMoveDown/actDuplicate/actDelete/actionSheetStyle/actionRowDangerStyle) but was never
// wired into LoomMobile at all across the six increments above -- a real, disclosed gap
// found in a final completeness pass, closed here. moveCard/dupCard/delCard are the exact
// same real mutators LoomV2's own board-card buttons already call (useShotMutations, App()),
// threaded through for the first time; delete keeps the real window.confirm gate.
describe("Kebab actions sheet: moveCard/dupCard/delCard threaded through, no forked logic", () => {
  test("LoomMobile's own function signature now receives moveCard/dupCard/delCard", () => {
    const sigMatch = loomMobileSrc.match(/function LoomMobile\(\{([\s\S]*?)\}\)\s*\{/);
    assert.ok(sigMatch, "expected to find LoomMobile's function signature");
    for (const name of ["moveCard", "dupCard", "delCard"]) {
      assert.match(sigMatch[1], new RegExp(`\\b${name}\\b`), `LoomMobile's signature should destructure ${name}`);
    }
  });

  test("the <LoomMobile .../> call site passes all three through from the SAME useShotMutations instance LoomV2 already uses", () => {
    const loomMobileCall = src.match(/<LoomMobile\b[\s\S]*?\/>/);
    assert.ok(loomMobileCall, "expected to find the <LoomMobile .../> call site");
    for (const prop of ["moveCard={moveCard}", "dupCard={dupCard}", "delCard={delCard}"]) {
      assert.ok(loomMobileCall[0].includes(prop), `expected "${prop}" at the <LoomMobile .../> call site`);
    }
  });

  test("moveCard/dupCard/delCard are declared exactly once in the whole file (App()'s useShotMutations) -- no second, forked copy added for mobile", () => {
    for (const name of ["moveCard", "dupCard", "delCard"]) {
      const re = new RegExp(`const ${name} = \\(`, "g");
      const hits = src.match(re) || [];
      assert.equal(hits.length, 1, `expected exactly one "const ${name} = (" declaration, found ${hits.length}`);
    }
  });
});

describe("Kebab actions sheet: the board-card ⋮ button", () => {
  test("every board card renders a real sibling <button> kebab, never nested inside .lm-card", () => {
    assert.match(loomMobileSrc,
      /<button type="button" className="lm-kebab" title="More actions for this shot"\s*\n\s*onClick=\{\(ev\) => \{ ev\.stopPropagation\(\); setSelShot\(e\.c\.id\); setActionsOpen\(true\); \}\}>&#8942;<\/button>/);
  });

  test("tapping the kebab selects the shot and opens the actions sheet -- same selShot-reuse convention as the ▶ review badge", () => {
    assert.match(loomMobileSrc, /setSelShot\(e\.c\.id\); setActionsOpen\(true\);/);
  });

  test("the kebab is unconditional -- it renders for every card, not gated behind canReview like the ▶ badge", () => {
    const cardBlock = loomMobileSrc.slice(loomMobileSrc.indexOf('key={e.c.id} className="lm-cardrow"'), loomMobileSrc.indexOf("{!items.length &&"));
    // canReview's own {canReview && (...)} guard must close BEFORE the kebab button, i.e. the
    // kebab sits outside that conditional block, not inside it.
    const kebabIdx = cardBlock.indexOf('className="lm-kebab"');
    const canReviewCloseIdx = cardBlock.indexOf(")}", cardBlock.indexOf("{canReview && ("));
    assert.ok(kebabIdx > 0 && canReviewCloseIdx > 0 && kebabIdx > canReviewCloseIdx,
      "expected the kebab button to render outside (after) the {canReview && (...)} block");
  });
});

describe("Kebab actions sheet: real live-lookup safety (mirrors dfLive/reviewLive exactly)", () => {
  test("actionsOpen is a plain local boolean; actionsLive reuses selShot/entries.find(), no second 'which shot' id invented (the design's own local actionsFor)", () => {
    assert.match(loomMobileSrc, /const \[actionsOpen, setActionsOpen\] = useState\(false\);/);
    assert.match(loomMobileSrc, /const actionsLive = actionsOpen \? entries\.find\(\(x\) => x\.c\.id === selShot\) : null;/);
  });

  test("a stale reference (the shot vanished out from under it) closes the sheet instead of acting on stale data", () => {
    assert.match(loomMobileSrc, /if \(actionsOpen && !actionsLive\) \{ setActionsOpen\(false\); \}/);
  });

  test("the sheet only renders while actionsOpen && actionsLive, never an empty/placeholder sheet", () => {
    assert.match(loomMobileSrc, /\{actionsOpen && actionsLive && \(/);
  });
});

describe("Kebab actions sheet: reuses the Cast sheet's own bottom-sheet convention, not a new one", () => {
  test("wraps with the SAME .lm-scrim/.lm-sheet/.lm-sheethandle classes the Cast & assets sheet already uses", () => {
    const sheetBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("{actionsOpen && actionsLive && ("), loomMobileSrc.indexOf("{dfOpen && dfLive && (() => {"));
    // Both carry the (2026-08-06) closing-state ternary -- the design's own lmSheetDown/
    // lmFadeOut close choreography -- same classes, now animated.
    assert.match(sheetBlock, /<div className=\{"lm-scrim" \+ \(actionsClosing \? " closing" : ""\)\} onClick=\{closeActions\} \/>/);
    assert.match(sheetBlock, /<div className=\{"lm-sheet" \+ \(actionsClosing \? " closing" : ""\)\}>/);
    assert.match(sheetBlock, /<div className="lm-sheethandle" \/>/);
  });

  test("Cancel reuses the SAME .lm-sheetclose class the Cast sheet's own 'Done' button uses, just different label text", () => {
    const sheetBlock = loomMobileSrc.slice(loomMobileSrc.indexOf("{actionsOpen && actionsLive && ("), loomMobileSrc.indexOf("{dfOpen && dfLive && (() => {"));
    assert.match(sheetBlock, /<button type="button" className="lm-sheetclose" onClick=\{closeActions\}>Cancel<\/button>/);
  });

  test("only the row styling (.lm-kebab/.lm-actionrow/.lm-actionrow.danger) is new CSS -- no second scrim/sheet/handle class invented", () => {
    assert.match(src, /\.lm-kebab\{flex:none;width:30px;height:30px;/);
    assert.match(src, /\.lm-actionrow\{display:block;width:100%;/);
    assert.match(src, /\.lm-actionrow\.danger\{color:var\(--red\);border-bottom:none;\}/);
    assert.doesNotMatch(loomMobileSrc, /lm-actionscrim|lm-actionsheet\b/,
      "expected the sheet to reuse .lm-scrim/.lm-sheet verbatim, not invent parallel classes");
  });
});

describe("Kebab actions sheet: all five rows, wired to the real mutators with the exact e.ci/act.id shape LoomV2's own buttons use", () => {
  test("Move up calls the real moveCard(actionsLive.a.id, actionsLive.ci, -1)", () => {
    assert.match(loomMobileSrc, /onClick=\{\(\) => \{ moveCard\(actionsLive\.a\.id, actionsLive\.ci, -1\); closeActions\(\); \}\}>&#8593; Move up<\/button>/);
  });

  test("Move down calls the real moveCard(actionsLive.a.id, actionsLive.ci, 1)", () => {
    assert.match(loomMobileSrc, /onClick=\{\(\) => \{ moveCard\(actionsLive\.a\.id, actionsLive\.ci, 1\); closeActions\(\); \}\}>&#8595; Move down<\/button>/);
  });

  test("Duplicate calls the real dupCard(actionsLive.a.id, actionsLive.c)", () => {
    assert.match(loomMobileSrc, /onClick=\{\(\) => \{ dupCard\(actionsLive\.a\.id, actionsLive\.c\); closeActions\(\); \}\}>&#10697; Duplicate<\/button>/);
  });

  test("actionsLive.ci/.a/.c are flat()'s own entry fields (loom-core.js) -- nothing new invented to address the card", () => {
    // flat()'s shape is {c, a, ai, ci, code}; the sheet uses exactly a/ci/c, the same fields
    // LoomV2's own real per-card buttons index by (act.id/e.ci/e.c). `entries` (LoomMobile's
    // own prop) is App()'s real flat(project) -- checked here via the import + the prop wire,
    // not a second read of loom-core.js (whose own flat() shape is loom-core.test.js's job).
    assert.match(src, /flat, shotText, castMissingImages, castPastBudget, refBudget, resolvedImage,/, "expected flat to be imported from loom-core.js");
    assert.match(src, /const entries = flat\(project\);/, "expected App()'s entries -- passed to LoomMobile as-is -- to be built from the real flat(project)");
  });

  test("Cancel and 'Done' outside a confirm both wire to the same closeActions -- the animated close (2026-08-06): closing state first, setActionsOpen(false) only after the 280ms lmSheetDown window", () => {
    assert.match(loomMobileSrc, /const closeActions = \(\) => \{\s*setActionsClosing\(true\);/);
    assert.match(loomMobileSrc,
      /actionsCloseTimer\.current = setTimeout\(\(\) => \{ setActionsOpen\(false\); setActionsClosing\(false\); \}, 280\);/);
  });
});

describe("Kebab actions sheet: Delete keeps the REAL window.confirm gate -- not silently dropped for mobile", () => {
  test("the confirm message is byte-for-byte the same text LoomV2's own real desktop ✕ button uses", () => {
    // LoomV2's own real delete button (verified against the exact source above this
    // component in the same file): window.confirm(`Delete shot ${e.code}${e.c.title ? ` —
    // "${e.c.title}"` : ""}? This can't be undone.`). This assertion pulls BOTH occurrences
    // out of the live source and checks they are identical, rather than hand-copying the
    // string a second time into the test (which could silently drift from either real site).
    const msgRe = /Delete shot \$\{[^}]+\.code\}\$\{[^}]+\.c\.title \? ` — "\$\{[^}]+\.c\.title\}"` : ""\}\? This can't be undone\./g;
    const hits = src.match(msgRe) || [];
    assert.equal(hits.length, 2, "expected the exact same delete-confirm message text at BOTH LoomV2's real button and the mobile kebab sheet's Delete row");
  });

  test("Delete is gated behind window.confirm before delCard ever runs -- an early return, not a fire-then-ask", () => {
    assert.match(loomMobileSrc,
      /if \(!window\.confirm\(`Delete shot \$\{actionsLive\.code\}\$\{actionsLive\.c\.title \? ` — "\$\{actionsLive\.c\.title\}"` : ""\}\? This can't be undone\.`\)\) return;/);
  });

  test("cancelling the confirm (the early return) never reaches delCard -- delCard is called only AFTER the confirm line, not before it", () => {
    const delBlock = loomMobileSrc.slice(loomMobileSrc.indexOf('className="lm-actionrow danger"'), loomMobileSrc.indexOf("Delete</button>") + 20);
    const confirmIdx = delBlock.indexOf("window.confirm(");
    const delCallIdx = delBlock.indexOf("delCard(actionsLive.a.id, actionsLive.c);");
    assert.ok(confirmIdx > -1 && delCallIdx > -1 && delCallIdx > confirmIdx,
      "expected window.confirm to be checked BEFORE delCard is ever called");
  });

  test("LoomMobile does not define a second, parallel confirm-less delete path for this row", () => {
    const delBlock = loomMobileSrc.slice(loomMobileSrc.indexOf('className="lm-actionrow danger"'), loomMobileSrc.indexOf("Delete</button>") + 20);
    const delCardHits = delBlock.match(/delCard\(/g) || [];
    assert.equal(delCardHits.length, 1, "expected exactly one delCard( call in the Delete row, guarded by the confirm above it");
  });
});
