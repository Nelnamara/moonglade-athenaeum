// "Where the Refit Broke" #6 (#31) -- three fidelity repairs against the locked designs
// (design_handoff/design_handoff_moonglade_suite/Image Details.dc.html + Lightbox.dc.html):
//
//   A. Similar, un-inverted. The DC gives the Details RECORD an inline 8-tile strip
//      (DC:127-140) and sends the Lightbox's Similar chip AWAY to the gallery (DC:354).
//      The refit had it backwards: a Similar button in the record opening the 48-grid
//      modal, and the Lightbox stacking that same modal on the viewer.
//
// B2 of the 2026-09-04 Gallery Chrome handoff finished that repair and changed two
// things these guards pin. The MARK is ◈, app-wide, for visual similarity -- the
// ✧ these tests used to assert is gone from every Similar surface. And the
// destination is no longer a MODAL at all: the lookalikes render in the grid's place
// (SimilarResults.jsx) under a dismissible ◈ token in the library bar, so the library
// beneath is never disturbed and ✕/Esc restores it exactly.
//   B. Publish's metal. Lightbox.dc.html:357 builds Publish with btn(..., true) -- the
//      PRIMARY/metal face, same as Slideshow -- which the refit had dropped to a plain chip.
//   C. One vt-reveal per view. Opening the Lightbox over Details left TWO elements carrying
//      the morph name; the View Transitions spec skips such a transition outright.
//
// Source guards (node --test, no DOM): the shapes that make each repair true, read
// straight out of the component files, so a later edit can't quietly re-invert them.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (rel) => readFileSync(path.join(here, "..", "..", "gallery", "src", rel), "utf8");

const details = src("components/DetailsView.jsx");
const lightbox = src("components/Lightbox.jsx");
const app = src("App.jsx");
const css = src("styles.css");
const hook = src("hooks/useSimilar.js");
const mobile = src("components/ImageDetailsMobile.jsx");

// ---------------------------------------------------------------- A. the inline strip

test("A: DetailsView renders the ◈ SIMILAR header + an 8-tile strip, inline in the record", () => {
  assert.match(details, /className="p-similar-head"/);
  assert.match(details, /◈ SIMILAR/);
  assert.doesNotMatch(details, /✧ SIMILAR/);                         // B2: one mark, app-wide
  assert.match(details, /the closest by eye, not by model/);             // DC:129's caption, verbatim
  assert.match(details, /className="p-similar-strip"/);
  assert.match(details, /similar\.images\.slice\(0, 8\)\.map/);           // eight tiles, DC:135
  assert.match(details, /className="p-sim-tile"/);
  // B2: the door is ALWAYS offered when the strip renders, and says what every other
  // ◈ door says. It used to read "see all N" and appear only past eight results --
  // true then, but four doors reading four different ways is what B2 set out to end.
  assert.match(details, /className="p-seeall"/);
  assert.match(details, /◈ Similar/);
  assert.doesNotMatch(details, /see all \{similar\.images\.length\}/);
  // the strip sits INSIDE the record, after LINEAGE (DC:108 then :127), with only the
  // app's quiet More row after it (the 2026-08-23 rebuild put the record actions where
  // the DC has them, BEFORE lineage -- details-actions.test.js)
  const lineageEnd = details.indexOf('className="p-lineage"');
  const strip = details.indexOf('className="p-similar"');
  const moreRow = details.indexOf("p-actions-more");
  const asideEnd = details.indexOf("</aside>");
  assert.ok(lineageEnd > 0 && strip > lineageEnd, "strip comes after LINEAGE");
  assert.ok(moreRow > strip && asideEnd > moreRow, "only the More row follows it inside the record");
});

test("A: the strip's CSS exists and matches the DC's geometry (flex row, gap 8, overflow-x, 78px tiles)", () => {
  assert.match(css, /\.p-similar-strip \{[^}]*display: flex;[^}]*gap: 8px;[^}]*overflow-x: auto;[^}]*padding: 2px;/);
  assert.match(css, /\.p-sim-tile \{[^}]*width: 78px;[^}]*height: 78px;[^}]*border-radius: 9px;/);
  assert.match(css, /\.p-similar-head \.k \{[^}]*font-size: 9\.5px;[^}]*font-weight: 700;[^}]*letter-spacing: \.14em;[^}]*var\(--overlay0\)/);
  assert.match(css, /\.p-similar-head \.s \{[^}]*font-size: 10\.5px;[^}]*rgba\(214,210,226,\.5\)/);
  assert.match(css, /\.p-seeall \{[^}]*var\(--lavender/);
});

test("A: NO SimilarModal open-button in the Details record any more -- the modal is gone from DetailsView", () => {
  assert.doesNotMatch(details, /SimilarModal/);
  assert.doesNotMatch(details, /setSimilarOpen|similarOpen/);
  assert.doesNotMatch(details, />✧ Similar</);                          // the old footer button
});

test("A: desktop shares the mobile strip's data path -- one useSimilar hook, /api/similar?k=48", () => {
  assert.match(hook, /export default function useSimilar\(mediaId\)/);
  assert.match(hook, /"\/api\/similar\/" \+ encodeURIComponent\(mediaId\) \+ "\?k=48"/);
  assert.match(details, /import useSimilar from "\.\.\/hooks\/useSimilar\.js"/);
  assert.match(mobile, /import useSimilar from "\.\.\/hooks\/useSimilar\.js"/);
  assert.doesNotMatch(mobile, /export function useSimilar/);            // moved, not duplicated
  assert.match(details, /const similar = useSimilar\(row \? row\.media_id : null\)/);
});

// ---------------------------------------------------------------- B. availability gate

test("B: the strip is gated on the route's availability signal -- empty images => no section, no header", () => {
  // the whole <div className="p-similar"> (header included) sits under ONE guard on images.length
  const m = details.match(/\{similar\.images\.length \? \(\s*<div className="p-similar">/);
  assert.ok(m, "the p-similar block is conditional on similar.images.length");
  // nothing renders a "loading" or error note for the strip -- unavailable means absent
  const block = details.slice(details.indexOf('className="p-similar"'), details.indexOf("p-actions-more"));
  assert.doesNotMatch(block, /similar\.error|similar\.loading/);
  // and the hook really does collapse every unavailable case to images: []
  assert.match(hook, /const images = \(d && d\.images\) \|\| \[\]/);
  assert.match(hook, /catch\(\(\) => \{[\s\S]*images: \[\]/);
});

// ---------------------------------------------------------------- C. the Lightbox navigates

test("C: the Lightbox's Similar NAVIGATES (onSimilar) -- no modal state, no SimilarModal in Lightbox.jsx", () => {
  assert.doesNotMatch(lightbox, /SimilarModal/);
  assert.doesNotMatch(lightbox, /setSimilarOpen|setSimilarFor|similarFor/);
  assert.match(lightbox, /onClick=\{\(\) => onSimilar && onSimilar\(it\.media_id\)\}>◈ Similar</);
  assert.match(lightbox, /onOpenDetails, onPublish, onSimilar,/);          // a real prop, not a global
});

test("C: App routes both Similar entry points to the gallery's own lookalike set (closes viewer + record first)", () => {
  // useCallback since B2: showSimilar became a <Grid> prop (the tile hover door) and Grid
  // is memoized, so a fresh identity per render would defeat that memo.
  const m = app.match(/const showSimilar = useCallback\(\(mid\) => \{([\s\S]*?)\}, \[closeDetails\]\);/);
  assert.ok(m, "App.jsx defines showSimilar as a useCallback");
  assert.match(m[1], /setLbIndex\(null\)/);
  assert.match(m[1], /closeDetails\(\)/);
  assert.match(m[1], /setSimilarFor\(mid\)/);
  // the Lightbox and Details both get it
  const lbProps = app.slice(app.indexOf("<Lightbox"), app.indexOf("/>", app.indexOf("<Lightbox")));
  assert.match(lbProps, /onSimilar=\{showSimilar\}/);
  const dvProps = app.slice(app.indexOf("<DetailsView"), app.indexOf("/>", app.indexOf("<DetailsView")));
  assert.match(dvProps, /onSimilar=\{showSimilar\}/);
  // ...and so do the other two doors B2 names, so all four call one verb
  assert.match(app, /onSimilar: \(mid\) => showSimilar\(mid\)/);          // the right-click row
  assert.match(app, /<Grid[\s\S]{0,900}onSimilar=\{showSimilar\}/);        // the tile hover door
  // the destination is the in-flow results surface, NOT a modal: it replaces <Grid> in
  // <main>, and the library bar wears the token that dismisses it.
  assert.doesNotMatch(app, /SimilarModal/);
  assert.match(app, /\) : similarFor \? \(/);
  assert.match(app, /<SimilarResults/);
  assert.match(app, /similar=\{similarToken\} onClearSimilar=/);
});

test("B2: the ◈ token is the one result state -- thumb, mark and dismiss, in the search slab", () => {
  const bar = src("components/FiltersPanel.jsx");
  assert.match(bar, /className="mgl-simtok"/);
  assert.match(bar, /className="mgl-simtok-th"/);                       // the source picture's own thumb
  assert.match(bar, /◈ Similar to this/);
  assert.match(bar, /className="mgl-simtok-x"/);                        // ✕ dismisses
  assert.match(bar, /className="mgl-simcount"/);                        // "N matches - by likeness"
  assert.match(bar, /by likeness/);
  // the layout picker moved OUT of this bar in the same pass (B1)
  assert.doesNotMatch(bar, /LayoutPicker|mgl-laybtn/);
  // Escape dismisses the token too, and only while Similar is the top thing up.
  const esc = app.match(/if \(!similarFor\) return undefined;([\s\S]*?)\}, \[similarFor\]\);/);
  assert.ok(esc, "App.jsx has the Similar Escape effect");
  assert.match(esc[1], /e\.key !== "Escape"/);
  assert.match(esc[1], /setSimilarFor\(null\)/);
});

test("B2: ◈ is the mark on every door -- tile hover, right-click row, lightbox chip", () => {
  assert.match(src("components/Grid.jsx"), /className="mgg-door"[\s\S]{0,240}◈/);
  assert.match(src("components/GridContextMenu.jsx"), /\["◈", "Find similar"/);
  assert.match(lightbox, /className="lbx-chip lbx-similar"/);
  // ...and the lavender treatment those three share, all tokens
  assert.match(src("styles/lightbox.css"), /\.lbx-similar \{[^}]*var\(--lavender\)/);
  assert.match(src("styles/grid.css"), /\.mgg-door \{[^}]*var\(--lavender\)/);
});

// ---------------------------------------------------------------- D. Publish's metal

test("D: the Lightbox's Publish chip carries the app's metal class (Lightbox.dc.html:357 btn(..., true))", () => {
  assert.match(lightbox, /className="lbx-chip lbx-chip-metal" title="Publish this image to PixAI"/);
  // the class is the existing shared recipe, not a fresh duplicate
  const lbxCss = src("styles/lightbox.css");
  assert.match(lbxCss, /\.lbx-chip-metal, \.lbx-chip-metal:hover \{/);
  assert.match(lbxCss, /animation: lbxMetal 7s ease-in-out infinite/);   // the suite's mgMetal drift, lbx-scoped
});

// ---------------------------------------------------------------- E. one vt-reveal per view

test("E: vt-reveal is unique per view -- Details drops the name while the Lightbox is mounted on top", () => {
  // DetailsView: the ONE carrier, gated on `morph`
  const dvNames = details.match(/vt-reveal/g) || [];
  assert.match(details, /viewTransitionName: morph \? "vt-reveal" : "none"/);
  assert.equal((details.match(/viewTransitionName:/g) || []).length, 1, "exactly one view-transition-name site in DetailsView");
  assert.match(details, /onPublish, onSimilar,\s*morph = true,/);        // defaults to carrying it
  assert.ok(dvNames.length >= 1);
  // App: morph is false exactly while the Lightbox is mounted (lbIndex != null)
  const dvProps = app.slice(app.indexOf("<DetailsView"), app.indexOf("/>", app.indexOf("<DetailsView")));
  assert.match(dvProps, /morph=\{lbIndex == null\}/);
  assert.match(app, /\{lbIndex != null && \(\s*<Lightbox/);
  // Lightbox: the stage's two name sites are the two arms of ONE video/img ternary --
  // only one of them is ever mounted
  const stage = lightbox.match(/\{it\.is_video \? \(([\s\S]*?)\) : \(([\s\S]*?)\)\}/);
  assert.ok(stage, "the stage media is one video/img ternary");
  assert.equal((stage[1].match(/vt-reveal/g) || []).length, 1);
  assert.equal((stage[2].match(/vt-reveal/g) || []).length, 1);
  assert.equal((lightbox.match(/viewTransitionName: "vt-reveal"/g) || []).length, 2, "no third carrier in the Lightbox");
  // nobody else in the desktop tree claims the name
  const others = ["components/Grid.jsx", "components/SimilarResults.jsx", "components/ImageDetailsMobile.jsx",
    "components/LightboxMobile.jsx"];
  for (const f of others) assert.doesNotMatch(src(f), /vt-reveal/, f + " must not carry vt-reveal");
});

// ---------------------------------------------------------------- F. the phone half

// 2026-09-05 (owner). B2 shipped the desktop and wrote a carve-out saying the phone had
// nowhere to put the token. The phone has a search field -- GalleryMobile.jsx's
// .glm-search -- so the carve-out was wrong and is gone. These pin the phone half's
// wiring; tests/test_render_harness.py drives the whole round trip at a real 390px
// viewport (door -> results -> token -> the library back).
const appMobile = src("components/AppMobile.jsx");
const lbMobile = src("components/LightboxMobile.jsx");
const galleryMobile = src("components/GalleryMobile.jsx");

test("F: the phone viewer's Similar is a DOOR, not a toast, and wears ◈", () => {
  assert.match(lbMobile, /className="lbm-chip lbm-similar"[\s\S]{0,160}◈ Similar</);
  assert.match(lbMobile, /onClick=\{\(\) => onSimilar && onSimilar\(it\.media_id\)\}/);
  assert.doesNotMatch(lbMobile, /✧ Similar/);
  assert.doesNotMatch(lbMobile, /toast\("Similar"/);          // the stub is gone
  assert.match(lbMobile, /onOpenDetails, onSimilar,/);        // a real prop, not a global
  assert.match(src("styles/lightbox-mobile.css"), /\.lbm-similar \{[^}]*var\(--lavender/);
  // Edit / To Video are still honest toasts -- this pass fixed Similar, not those
  assert.match(lbMobile, /toast\("Send to Video"/);
});

test("F: AppMobile owns one verb and one data path, exactly like App.jsx does", () => {
  assert.match(appMobile, /import useSimilar from "\.\.\/hooks\/useSimilar\.js"/);
  assert.match(appMobile, /const similar = useSimilar\(similarFor\)/);
  const verb = appMobile.match(/const showSimilar = \(mid\) => \{([\s\S]*?)\n  \};/);
  assert.ok(verb, "AppMobile defines showSimilar");
  assert.match(verb[1], /setLbIndex\(null\)/);        // the viewer closes
  assert.match(verb[1], /setDetailsFor\(null\)/);     // the record closes
  assert.match(verb[1], /setTab\("gallery"\)/);       // the answer has to be visible
  assert.match(verb[1], /setSimilarFor\(mid\)/);
  // the viewer gets the verb, and so does the gallery tab (its results re-anchor on it)
  assert.match(appMobile, /<LightboxMobile[\s\S]{0,400}onSimilar=\{showSimilar\}/);
  assert.match(appMobile, /<GalleryMobile[\s\S]{0,400}onSimilar=\{showSimilar\}/);
});

test("F: the phone restores the library exactly -- its OWN scroller, and Back as the second dismiss", () => {
  // .glm-body is the phone's scroller (gallery-mobile.css: overflow-y:auto), not the
  // window the desktop saves -- so the offset save/restore reads that element.
  assert.match(appMobile, /libScrollRef\.current = bodyRef\.current \? bodyRef\.current\.scrollTop : 0;/);
  assert.match(appMobile, /if \(bodyRef\.current\) bodyRef\.current\.scrollTop = y;/);
  assert.match(appMobile, /className="glm-body" ref=\{bodyRef\}/);
  // only the FIRST entry saves, so chaining ◈ can't overwrite the library's own offset
  assert.match(appMobile, /if \(libScrollRef\.current === null\) \{/);
  // no Escape on a phone: ONE same-address history entry stands in for it, keyed on the
  // boolean so re-anchoring the set never churns history
  assert.match(appMobile, /const simOn = !!similarFor;/);
  assert.match(appMobile, /window\.history\.pushState\(\{ mgSimilar: 1 \}, ""\);/);
  assert.match(appMobile, /if \(!popped\) window\.history\.back\(\);/);
});

test("F: the ◈ token rides the phone's own search bar, and the results take the grid's place", () => {
  assert.match(galleryMobile, /className="glm-simtok"/);
  assert.match(galleryMobile, /className="glm-simtok-th"/);      // the source picture's thumb
  assert.match(galleryMobile, /◈ Similar to this/);
  assert.match(galleryMobile, /className="glm-simtok-x"/);       // ✕ dismisses
  assert.match(galleryMobile, /className="glm-simcount"/);
  assert.match(galleryMobile, /by likeness/);
  // it is INSIDE .glm-bar, the row that holds the search field
  const bar = galleryMobile.slice(galleryMobile.indexOf('className="glm-bar"'),
    galleryMobile.indexOf('className="glm-bar2"'));
  assert.match(bar, /className="glm-simrow"/);
  assert.match(bar, /className="glm-search"/);
  // the SHARED results component, not a mobile fork, and it replaces the grid + pager
  assert.match(galleryMobile, /import SimilarResults from "\.\/SimilarResults\.jsx"/);
  assert.match(galleryMobile, /\{similar \? \([\s\S]{0,700}<SimilarResults/);
  assert.match(galleryMobile, /\{!similar && !loading && pages > 1 && \(/);
  // and the phone's own layout overrides for it (the desktop track is one column at 390px,
  // and there is no hover to reveal a result's door with)
  const gmCss = src("styles/gallery-mobile.css");
  assert.match(gmCss, /\.glm-tab-gallery \.simres-grid \{[^}]*grid-template-columns: 1fr 1fr;/);
  assert.match(gmCss, /\.glm-tab-gallery \.simres-door \{[^}]*opacity: 1;/);
});

test("F: ✧ is gone from the phone, and its model filter says what it does", () => {
  // Comments are stripped first: the files still SAY the old mark where they record what
  // it used to be, and that history is worth keeping. What must not survive is a ✧ the
  // phone actually draws.
  const code = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  for (const [name, file] of [["picture screen", mobile], ["viewer", lbMobile],
    ["gallery tab", galleryMobile], ["shell", appMobile]]) {
    assert.doesNotMatch(code(file), /✧/, "✧ is still drawn by the phone's " + name);
  }
  assert.match(mobile, />◈ SIMILAR</);                    // the strip head
  assert.match(mobile, /title="◈ SIMILAR"/);              // the "see all" sheet
  assert.match(code(mobile), />\s*Filter by model\s*</);
  assert.doesNotMatch(code(mobile), /Find similar \(model\)/);
  // the sheet stays a SHEET -- the phone's own idiom for "the rest of these"
  assert.match(mobile, /<MobileSheet open=\{simSheetOpen\}/);
});

test("useSimilar consumes apiGet's parsed body directly -- never double-parses (#31 Similar strip)", () => {
  const hook = src("hooks/useSimilar.js");
  assert.match(hook, /apiGet\(/, "useSimilar must call apiGet (the one request module), not raw fetch");
  assert.doesNotMatch(hook, /\.json\(\)/,
    "apiGet already returns the parsed body; a stray .then(r=>r.json()) throws and blanks the strip");
});
