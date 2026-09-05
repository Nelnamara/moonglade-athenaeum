import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE OVERLAY-OPEN RENDER PATH (2026-09-04). Source-level guards, the established pattern
   for this runner -- there is no React test renderer here (see contestSyncFlow.js's own
   header for why the pure logic is extracted instead), so what CAN be pinned is the
   structure the behaviour rests on. Every assertion below guards a property that silently
   stops paying the moment someone edits past it:

     · a memo that is still applied,
     · props that are still referentially stable (one inline arrow at the call site and the
       memo compares unequal every render -- strictly slower than no memo at all),
     · every full-viewport scrim's blur still applied AFTER its fade rather than during it,
       and still switchable OFF wholesale by the Control Panel's per-device preference,
     · the reserved scrollbar gutter that stops the open from resizing the viewport,
     · the mutation seams that purge the read cache.

   None of these can fail loudly at runtime: the app keeps working, just slowly again. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Line endings are normalized on read: the repo stores LF (.gitattributes `* text=auto`)
// while Windows checks out CRLF, and several assertions below are line-anchored.
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");

const app = src("App.jsx");
const grid = src("components/Grid.jsx");
const drawer = src("components/GenerateDrawer.jsx");
const library = src("hooks/useLibrary.js");
const styles = src("styles.css");
const contests = src("components/ContestsOverlay.jsx");
const publish = src("components/PublishOverlay.jsx");
const jobs = src("notify/jobs.js");

/** The attribute block of a single JSX element, from `<Name` to the `>` that closes the
    opening tag. The match requires an ATTRIBUTE right after the name, so a `<Grid>` written
    inside a prose comment is not mistaken for the call site. Good enough here because none
    of these call sites nest an element inside an attribute. */
function propsOf(source, name) {
  const m = source.match(new RegExp("<" + name + "\\s+\\w+=\\{"));
  assert.ok(m && m.index > 0, "no <" + name + "> call site found");
  const end = source.indexOf(">", m.index);
  assert.ok(end > m.index);
  return source.slice(m.index, end);
}

describe("the two memoized children", () => {
  test("Grid is exported through React.memo", () => {
    assert.match(grid, /export default React\.memo\(Grid\);/);
    assert.doesNotMatch(grid, /export default function Grid/);
  });

  test("GenerateDrawer is exported through React.memo", () => {
    assert.match(drawer, /export default React\.memo\(GenerateDrawer\);/);
    assert.doesNotMatch(drawer, /export default function GenerateDrawer/);
  });
});

describe("the memo only pays if the props stay referentially stable", () => {
  test("no inline arrow function is handed to <Grid>", () => {
    // The failure this catches is invisible: an inline arrow makes that prop a new value on
    // every render, so React.memo compares unequal every time and the whole grid
    // re-reconciles anyway -- plus the cost of the comparison.
    assert.doesNotMatch(propsOf(app, "Grid"), /=>/);
  });

  test("no inline arrow function is handed to <GenerateDrawer>", () => {
    assert.doesNotMatch(propsOf(app, "GenerateDrawer"), /=>/);
  });

  test("every callback <Grid> takes is useCallback'd (or a setState)", () => {
    // openSeries replaced filterBySeries in B3 (a stack opens a modal now, it does not
    // set a filter) and showSimilar joined the list in B2 (the tile's own hover door).
    for (const name of ["goToPage", "openDetails", "rate", "openContextMenu",
                        "openSeries", "filterByBatch", "showSimilar"]) {
      assert.match(app, new RegExp("const " + name + " = useCallback\\("), name);
    }
    // openLightbox={setLbIndex} / onFocusCard={setGridFocus}: setState functions, stable by
    // React's own contract, so they need nothing.
    const props = propsOf(app, "Grid");
    assert.match(props, /openLightbox=\{setLbIndex\}/);
    assert.match(props, /onFocusCard=\{setGridFocus\}/);
  });

  test("toggleSelected is useCallback'd in useLibrary -- it is a <Grid> prop too", () => {
    assert.match(library, /const toggleSelected = useCallback\(\(mid\) =>/);
    assert.match(propsOf(app, "Grid"), /toggleSelected=\{toggleSelected\}/);
  });

  test("the three-listener effect has its dep array back", () => {
    // With no array at all it tore down and re-added mg-gen-done / mg-submit / mg-result on
    // EVERY render of the shell.
    const i = app.indexOf('window.addEventListener("mg-gen-done", onGenDone);');
    assert.ok(i > 0);
    const tail = app.slice(i, i + 1400);
    assert.match(tail, /\}, \[load\]\);/);
    assert.doesNotMatch(tail, /\}\); \/\/ eslint-disable-line react-hooks\/exhaustive-deps/);
  });
});

/* ---------------------------------------------------------------------------------------
   EVERY full-viewport blurred scrim defers its blur, not only the one that started this.

   The pathology in one sentence: a `backdrop-filter` on a `position: fixed; inset: 0`
   element that is ALSO running an opacity animation makes the browser re-blur the entire
   viewport on every frame of that animation, and what sits behind these is a live 100-card
   grid. The fix is a split -- fade a plain scrim for its own duration, then a near-zero
   keyframe, delayed past that fade, which switches the blur on `forwards`. The resting look
   is identical; only WHEN the blur turns on moves.

   Reading one file for one class (which is what this block used to do) guards nothing: four
   more scrims were shipping the un-split form the whole time and none of them failed
   anything. So the scan below is structural. It walks every stylesheet under
   gallery/src/styles, finds the shape, and resolves each `animation` item against the
   keyframes actually defined -- pooled across all of them, because .mgct-subscrim genuinely
   reaches into overlays.css for mgvFade and mgvScrimBlur. A scrim written the old way fails
   here on the day it lands. ------------------------------------------------------------- */

const STYLE_DIR = path.resolve(__dirname, "../../gallery/src/styles");

/* Full-viewport blurred surfaces deliberately left out of this pass, each with its reason.
   Kept as data rather than as silence: the exactness test below asserts that NOTHING ELSE
   is unsplit, so the list cannot quietly grow. */
const KNOWN_UNSPLIT = new Map([
  [".mg-gallery-picker",
   "verbatim port of the vanilla static/mg-gallery-picker.js (its own header pins it " +
   "spec-literal); re-timing its motion is a porting decision, not plumbing"],
  [".lgn-welcome", "login screen -- what it blurs is the sign-in card, never the grid"],
  [".lgnm-welcome", "login screen (mobile) -- same"],
]);

function cssFiles(dir) {
  const out = [];
  for (const e of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...cssFiles(p));
    else if (e.name.endsWith(".css")) out.push(p);
  }
  return out.sort();
}

const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, " ");

/** Every `sel { body }` pair. At-rule wrappers (@media, @keyframes) drop out on their own:
    their braces cannot match `[^{}]`, so only the innermost rules are yielded. */
function* rules(css) {
  const re = /([^{}]+)\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(css))) {
    const sel = m[1].trim();
    if (!sel || sel.startsWith("@")) continue;
    yield { sel, body: m[2].replace(/\s+/g, " ").trim() };
  }
}

/** The body of every `@media (prefers-reduced-motion: reduce)` block, brace-matched. */
function reducedMotionBlocks(css) {
  const out = [];
  const re = /@media[^{]*prefers-reduced-motion:\s*reduce[^{]*\{/g;
  let m;
  while ((m = re.exec(css))) {
    let depth = 1, i = re.lastIndex;
    while (i < css.length && depth > 0) {
      if (css[i] === "{") depth++;
      else if (css[i] === "}") depth--;
      i++;
    }
    out.push(css.slice(re.lastIndex, i - 1));
  }
  return out;
}

const sheets = cssFiles(STYLE_DIR).map((f) => ({
  file: path.relative(STYLE_DIR, f).replace(/\\/g, "/"),
  css: stripComments(readFileSync(f, "utf8").replace(/\r\n/g, "\n")),
}));

/** name -> keyframe body, pooled across every sheet: @keyframes are global once bundled. */
const keyframes = new Map();
for (const { css } of sheets) {
  const re = /@keyframes\s+([\w-]+)\s*\{/g;
  let m;
  while ((m = re.exec(css))) {
    let depth = 1, i = re.lastIndex;
    while (i < css.length && depth > 0) {
      if (css[i] === "{") depth++;
      else if (css[i] === "}") depth--;
      i++;
    }
    keyframes.set(m[1], css.slice(re.lastIndex, i - 1));
  }
}

const seconds = (t) => (t.endsWith("ms") ? parseFloat(t) / 1000 : parseFloat(t));

/** Split an `animation:` value on its TOP-LEVEL commas -- cubic-bezier(.2,.9,.24,1) carries
    commas of its own and has to survive intact. */
function splitTopLevel(value) {
  const out = [];
  let depth = 0, cur = "";
  for (const ch of value) {
    if (ch === "(") depth++;
    else if (ch === ")") depth--;
    if (ch === "," && depth === 0) { out.push(cur); cur = ""; } else cur += ch;
  }
  if (cur.trim()) out.push(cur);
  return out.map((s) => s.trim()).filter(Boolean);
}

/** Each item of an `animation` shorthand, resolved against the keyframe it names. */
function parseAnimation(body) {
  const m = body.match(/(?:^|[\s;])animation:\s*([^;]+)/);
  if (!m) return [];
  return splitTopLevel(m[1]).map((item) => {
    const name = item.split(/\s+/).find((tok) => keyframes.has(tok)) || null;
    const times = (item.match(/(?:\d*\.)?\d+m?s\b/g) || []).map(seconds);
    const kf = name ? keyframes.get(name) : "";
    return {
      raw: item,
      name,
      duration: times[0] || 0,
      delay: times[1] || 0,
      fill: (/\b(forwards|backwards|both)\b/.exec(item) || [, "none"])[1],
      movesPixels: /opacity|transform/.test(kf),
      appliesBlur: /backdrop-filter/.test(kf),
    };
  });
}

/** Every rule shaped like a full-viewport scrim that ends up blurred, however it gets there,
    and that animates while doing it. A blurred scrim with NO animation is not the pathology
    (nothing makes the browser re-blur per frame), so it is passed over. */
function scrimRules() {
  const found = [];
  for (const { file, css } of sheets) {
    const rm = reducedMotionBlocks(css).join("\n");
    for (const r of rules(css)) {
      if (rm.includes(r.body)) continue;            // reduced-motion overrides: own test below
      if (!/position:\s*fixed/.test(r.body)) continue;
      if (!/inset:\s*0/.test(r.body)) continue;
      const items = parseAnimation(r.body);
      const blurInBody = /backdrop-filter/.test(r.body);
      const blurItems = items.filter((i) => i.appliesBlur);
      if (!blurInBody && !blurItems.length) continue;
      const motion = items.filter((i) => i.movesPixels);
      if (!motion.length) continue;
      found.push({ file, ...r, items, blurInBody, blurItems, motion });
    }
  }
  return found;
}

const scrims = scrimRules();

describe("every full-viewport scrim blurs AFTER its fade, not during it", () => {
  test("the scan sees the scrims at all -- a broken parser must not pass vacuously", () => {
    const names = scrims.map((s) => s.sel);
    for (const expected of [".mgv-scrim", ".mgclaim-scrim", ".mgpal-scrim", ".mgks-scrim",
                            ".mgct-subscrim", ".mgai-scrim", ".mgdock-scrim",
                            ...KNOWN_UNSPLIT.keys()]) {
      assert.ok(names.includes(expected), expected + " was not seen by the stylesheet scan");
    }
    assert.ok(keyframes.has("mgvFade") && keyframes.has("mgvScrimBlur"));
  });

  test("none of them carries the blur on the very rule the fade animates", () => {
    for (const s of scrims) {
      if (KNOWN_UNSPLIT.has(s.sel)) continue;
      assert.equal(s.blurInBody, false,
        s.file + " " + s.sel + ": a backdrop-filter on the animated rule re-blurs the whole " +
        "viewport on every frame of " + s.motion.map((m) => m.name).join(" + "));
    }
  });

  test("each switches the blur on from a delayed keyframe that fills FORWARDS", () => {
    for (const s of scrims) {
      if (KNOWN_UNSPLIT.has(s.sel)) continue;
      assert.equal(s.blurItems.length, 1,
                   s.file + " " + s.sel + ": exactly one deferred-blur keyframe");
      const blur = s.blurItems[0];
      // `both` fills BACKWARDS as well -- the blur would be on for the whole fade, which is
      // the exact thing being avoided.
      assert.equal(blur.fill, "forwards", s.file + " " + s.sel + ": " + blur.raw);
      const fadeEnds = Math.max(...s.motion.map((m) => m.duration + m.delay));
      assert.ok(blur.delay >= fadeEnds,
        s.file + " " + s.sel + ": the blur starts at " + blur.delay + "s but the fade runs to " +
        fadeEnds + "s -- the deferral has to clear the motion, not land inside it");
      assert.ok(blur.duration <= 0.05,
                s.file + " " + s.sel + ": the blur switch is a flip, not a second fade");
    }
  });

  test("the exemption list is exact -- nothing else may stay unsplit", () => {
    for (const s of scrims.filter((x) => x.blurInBody)) {
      assert.ok(KNOWN_UNSPLIT.has(s.sel),
        s.file + " " + s.sel + " is a full-viewport blurred scrim under an animation and is " +
        "not split -- defer its blur, or say here why it does not");
    }
    // ...and the list cannot rot: every name on it must still be a live rule somewhere.
    for (const sel of KNOWN_UNSPLIT.keys()) {
      assert.ok(sheets.some(({ css }) => [...rules(css)].some((r) => r.sel === sel)),
                sel + " no longer exists -- drop it from KNOWN_UNSPLIT");
    }
  });

  test("a closing/exiting state re-states the blur, since it replaces the animation", () => {
    // `.mgpal-scrim.closing { animation: ... }` overrides the shorthand wholesale, dropping
    // the deferred keyframe AND its forwards fill with it -- without a blur of its own the
    // scrim would go sharp the instant the exit begins.
    for (const s of scrims) {
      if (KNOWN_UNSPLIT.has(s.sel)) continue;
      const state = new RegExp("^" + s.sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\.[\\w-]+$");
      for (const { file, css } of sheets) {
        const rm = reducedMotionBlocks(css).join("\n");
        for (const r of rules(css)) {
          if (!state.test(r.sel) || rm.includes(r.body)) continue;
          if (!/(?:^|[\s;])animation:/.test(r.body)) continue;
          assert.match(r.body, /backdrop-filter/,
                       file + " " + r.sel + " replaces the animation but drops the blur");
        }
      }
    }
  });

  /* THE BLUR SWITCH (owner ruling 2026-09-04). Deferring the blur made the OPEN cheap; it
     did not make the blur free, so it is now a per-device preference -- a class on <html>,
     written by the Control Panel through gallery/src/lib/blurPref.js.

     This belongs in THIS block, not in a file of its own, because it is the same contract
     seen from the other side: every rule the assertions above force to defer a blur, the
     assertion below forces to also be able to switch it OFF. A scrim that gains a deferred
     blur and no override would pass every test above while leaving one popup permanently
     blurred on the machine that most needs it not to be. The scan is the same structural
     one -- no list of seven names to keep in sync, it reads whatever the scan found. */
  test("each one can be switched OFF -- html.mg-noblur wins over every path the blur takes", () => {
    for (const s of scrims) {
      if (KNOWN_UNSPLIT.has(s.sel)) continue;
      const overrides = [];
      for (const { file, css } of sheets) {
        for (const r of rules(css)) {
          const listed = r.sel.split(",").map((x) => x.trim());
          if (!listed.includes("html.mg-noblur " + s.sel)) continue;
          overrides.push({ file, ...r });
        }
      }
      assert.equal(overrides.length, 1,
        s.file + " " + s.sel + ": expected exactly one `html.mg-noblur " + s.sel + "` rule, " +
        "saw " + overrides.length + " -- the toggle cannot turn this scrim's blur off");
      const o = overrides[0];
      assert.equal(o.file, s.file,
        s.sel + ": its override lives in " + o.file + ", not beside the rule it neutralises " +
        "in " + s.file + " -- a stylesheet must not depend on another one shipping");
      // `!important`, and the reason is not stylistic. The blur reaches these scrims from
      // three places -- the deferred keyframe, the .closing/.exiting rules that re-state
      // it, and the reduced-motion blocks that re-state it too. An author !important is
      // the one declaration that outranks all three (CSS Cascading 4 sorts important-author
      // above animation declarations); a plain `backdrop-filter: none` loses to the
      // keyframe and the toggle would do nothing at all.
      assert.match(o.body, /backdrop-filter:\s*none\s*!important/,
        o.file + " " + o.sel + ": must be `backdrop-filter: none !important` -- without the " +
        "!important the deferred keyframe still wins and the toggle is inert");
      assert.match(o.body, /-webkit-backdrop-filter:\s*none\s*!important/,
        o.file + " " + o.sel + ": the -webkit- pair is prefixed everywhere else here too");
      // Off must change ONLY the blur. The dark scrim, its fade and its timing are the
      // resting look either way -- the owner asked for a blur toggle, not a scrim toggle.
      assert.doesNotMatch(o.body, /(?:^|[\s;])(background|animation|opacity|display|transition)\s*:/,
        o.file + " " + o.sel + ": the override may only drop the blur -- the plain dark " +
        "scrim and its fade stay exactly as they are");
    }
  });

  test("the override reaches the state classes too, via the base selector", () => {
    // `.mgclaim-scrim.exiting` and `.mgpal-scrim.closing` re-state the blur DIRECTLY in
    // their own bodies. They are not separately overridden and must not need to be: an
    // element carrying `.exiting` is still an `.mgclaim-scrim`, so the base override
    // already matches it. What this pins is that nobody "fixes" that by narrowing the
    // override to a selector the state rules would escape.
    for (const { css } of sheets) {
      for (const r of rules(css)) {
        for (const sel of r.sel.split(",").map((x) => x.trim())) {
          if (!sel.startsWith("html.mg-noblur ")) continue;
          const target = sel.slice("html.mg-noblur ".length);
          assert.ok(/^\.[\w-]+$/.test(target),
            sel + ": the override must target the scrim's BASE class alone -- anything " +
            "narrower leaves .closing/.exiting blurred with the preference off");
        }
      }
    }
  });

  test("reduced motion still gets the blur -- it has no animation to defer behind", () => {
    // `animation: none` kills the deferred keyframe along with the fade. Any reduced-motion
    // block that silences a split scrim has to state the blur outright, or that user never
    // gets one at all.
    let checked = 0;
    const listed = (sel, r) => r.sel.split(",").map((x) => x.trim()).includes(sel);
    for (const s of scrims) {
      if (KNOWN_UNSPLIT.has(s.sel)) continue;
      for (const { file, css } of sheets) {
        for (const block of reducedMotionBlocks(css)) {
          const inBlock = [...rules(block)];
          if (!inBlock.some((r) => listed(s.sel, r) && /animation:\s*none/.test(r.body))) continue;
          checked++;
          assert.ok(inBlock.some((r) => listed(s.sel, r) && /backdrop-filter/.test(r.body)),
            file + ": reduced motion silences " + s.sel + " without re-stating its blur");
        }
      }
    }
    assert.ok(checked >= 4,
              "expected the mgv / mgclaim / mgpal / mgks reduced-motion blocks, saw " + checked);
  });
});

describe("opening an overlay must not resize the viewport", () => {
  test("the scrollbar gutter is reserved on the document root", () => {
    // body{overflow:hidden} otherwise widens the page by the scrollbar, which fires every
    // ResizeObserver in the shell on the frame the overlay is animating in.
    assert.match(styles, /^html \{ color-scheme: dark; scrollbar-gutter: stable; \}$/m);
  });

  test("useScrollLock keeps a feature-detected padding fallback for engines without it", () => {
    const lock = src("hooks/useScrollLock.js");
    assert.match(lock, /CSS\.supports\("scrollbar-gutter", "stable"\)/);
    assert.match(lock, /document\.body\.style\.paddingRight = bar \+ "px";/);
  });
});

describe("remote images do not block the open frame", () => {
  test("every contest cover is lazy + async-decoded", () => {
    const imgs = contests.match(/<img src=\{[a-zA-Z.]*cover_url\}[^>]*>/g) || [];
    assert.equal(imgs.length, 3, "three board covers -- featured, official, community");
    for (const tag of imgs) {
      assert.match(tag, /loading="lazy"/, tag);
      assert.match(tag, /decoding="async"/, tag);
    }
  });

  test("Publish's hero decodes off the main thread -- and still loads the full-res image", () => {
    assert.match(publish, /<img src=\{"\/full\/" \+ encodeURIComponent\(mid\)\} alt="" decoding="async" \/>/);
    assert.doesNotMatch(publish, /<img src=\{"\/thumbs\//, "WHAT it loads is the owner's design");
  });
});

describe("the invalidation seams", () => {
  test("App's one mutation seam purges the read cache before it reloads", () => {
    const seam = app.slice(app.indexOf("const afterMutation = async () => {"),
                           app.indexOf("const actions = {"));
    for (const p of ["/api/your-art", "/api/myart/items", "/api/next/detail/",
                     "/api/achievements", "/api/health"]) {
      assert.ok(seam.includes(p), p);
    }
  });

  test("a finished job purges, and adds NO request to the spend-critical poller", () => {
    // jobs.js's contract at the top of that file: this module never submits and never
    // spends. invalidate() drops entries from a client-side map and issues no request --
    // which is the only reason it is allowed in here at all.
    assert.match(jobs, /invalidate\(\["\/api\/achievements", "\/api\/health", "\/api\/panel\/summary"/);
    assert.equal((jobs.match(/\bfetch\(/g) || []).length, 1,
                 "the one /api/task-status read, exactly as before");
    assert.doesNotMatch(jobs, /apiGet\(/);
  });

  test("the reads that must never be seeded from cache are named, and are not", () => {
    const panel = src("hooks/useControlPanel.js");
    // /api/panel/status is the live-job resume check; /api/ping is the restart watch.
    assert.doesNotMatch(panel, /peek\("\/api\/panel\/status"\)/);
    assert.doesNotMatch(panel, /peek\("\/api\/ping"\)/);
    assert.doesNotMatch(panel, /put\("\/api\/panel\/status"/);
    assert.doesNotMatch(panel, /put\("\/api\/ping"/);
    // Publish's per-image record: a stale artwork_id re-enables the Publish button.
    assert.doesNotMatch(publish, /peek\("\/api\/next\/detail\//);
    assert.doesNotMatch(publish, /put\("\/api\/next\/detail\//);
  });

  test("the store itself refuses to keep a csrf, so no call site has to remember", () => {
    const store = src("hooks/swrStore.js");
    assert.match(store, /if \("csrf" in data\) \{/);
    assert.match(store, /delete keep\.csrf;/);
  });
});
