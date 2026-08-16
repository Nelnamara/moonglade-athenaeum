import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

// PORTED 2026-08-08 (static/ -> React, vanilla campaign step 4): static/mg-cost-badge.js's
// <mg-cost-badge> custom element was reimplemented as gallery/src/components/CostBadge.jsx --
// a forwardRef + useImperativeHandle component so every existing costRef.current.setPrice/
// setChecking/clear call site (useGenerate/useEditGenerate/EditTab/FixTab and the Loom's
// priceInto) keeps working verbatim. static/mg-cost-badge.js was deleted with its last embedder,
// the video drawer, in step 7 (the campaign's end) -- the video drawer is now the React
// <VideoDrawer>, which embeds this same React <CostBadge>.
//
// No jsdom/React harness in this runner (same as ModelPicker.jsx / master-storyboard.jsx) --
// source-presence assertions are the established pattern; real interaction was verified live
// (the Gallery drawer's CostBadge priced a picked model to its FREE state, 2026-08-08). What
// these pin is the HONESTY MACHINE: the whole reason this component exists is that a displayed
// "free"/"0 credits" must only ever mean a settled zero-cost result, never "not priced yet"
// and never "the check failed". Those invariants must survive any future refactor.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../gallery/src/components/CostBadge.jsx"), "utf8");

test("CostBadge is a forwardRef whose imperative handle keeps the setPrice/clear/setChecking contract", () => {
  assert.match(src, /const CostBadge = forwardRef\(/);
  assert.match(src, /useImperativeHandle\(ref, \(\) => \(\{/);
  assert.match(src, /setPrice\(resp\)\s*\{\s*setView\(classify\(resp\)\);/,
    "setPrice must feed the parsed response straight through classify()");
  assert.match(src, /clear\(h\)\s*\{/);
  assert.match(src, /setChecking\(\)\s*\{/);
});

test("classify: a null/undefined response is the could-not-verify ERROR state, never idle", () => {
  // resp === null/undefined means the fetch itself failed -- the fail-closed state a spend
  // gate exists for. Conflating it with clear()'s idle is precisely the bug this prevents.
  assert.match(src, /if \(!d\) return \{ state: "error"/);
});

test("classify checks a real cost BEFORE the server's note, so a note can never hide a cost", () => {
  const costIdx = src.indexOf('return { state: "paid"');
  const noteIdx = src.indexOf('return { state: "idle"');
  assert.ok(costIdx > -1 && noteIdx > -1, "both the paid and note(idle) branches must exist");
  assert.ok(costIdx < noteIdx,
    "the cost/paid branch must be tested before the note/idle branch");
});

test("classify: free:false + cost:null + no note + no error is ERROR, not a silent zero", () => {
  // the trailing branch: nothing was actually priced -> honest 'we don't know', never "0 credits".
  assert.match(src, /\/\/ free:false, cost:null, no note[\s\S]{0,180}return \{ state: "error"/);
  // (issue #15: the free branch is additionally guarded by !isShort(d) -- see the
  // card_short test below -- so the pattern allows that guard.)
  assert.match(src, /if \(d\.free(?: && !isShort\(d\))?\) return \{ state: "free"/);
});

test("all five honesty states are represented", () => {
  for (const st of ["idle", "checking", "free", "paid", "error"]) {
    assert.ok(src.includes(`"${st}"`), `state "${st}" must appear in the source`);
  }
});

test("CostBadge NEVER fetches -- the host owns the /api/price call and pushes the result in", () => {
  assert.doesNotMatch(src, /\bfetch\s*\(/, "CostBadge must not call fetch; pricing is pushed in via the ref");
  assert.doesNotMatch(src, /XMLHttpRequest|EventSource|WebSocket/,
    "CostBadge must not open any network channel of its own");
});

test("a settled ZERO renders as paid-spends-nothing, never borrowing the free-card wording", () => {
  // loom-core.js's distinction: a priced 0 is real but is NOT the free-card state.
  assert.match(src, /n === 0.*"0 credits — this spends nothing"/);
  assert.match(src, /🎫 FREE — /, "the free-card branch keeps its own ticket wording");
});

// ---- issue #15: multi-ticket cards. The badge is the ONE honest renderer of the card
// sentence; hosts never hand-write it. Two response shapes matter: COVERED (held >= needed,
// free, "uses N of H cards") and SHORT (matched but held < needed -> nothing attached, FULL
// price charged -> paid + amber, never free). Same source-presence pattern as above.
test("free branch: a multi-ticket job says how many of the held cards it uses (1-ticket keeps '(N left)')", () => {
  assert.match(src, /needN != null && needN > 1/, "multi-ticket wording is gated on cards_needed > 1");
  assert.match(src, /"uses " \+ fmt\(needN\) \+ " of " \+ \(heldN != null \? fmt\(heldN\) : "your"\) \+ " cards"/,
    "covered wording must be 'uses N of H cards' with N = cards_needed and H = cards_held");
  assert.match(src, /fmt\(heldN\) \+ " left"/, "the 1-ticket '(N left)' wording survives unchanged");
  assert.match(src, /cardCount\(d\.cards_held != null \? d\.cards_held : d\.cards\)/,
    "held count reads cards_held with the legacy `cards` key as fallback");
  assert.match(src, /cardCount\(d\.cards_needed\)/, "needed count reads cards_needed");
});

test("classify: card_short can NEVER produce the free state -- short is paid, at the full price", () => {
  // The free branch is guarded by isShort(); a short response falls through to paid (cost)
  // or error (no cost) -- never emerald. This is the exact bug of issue #15 (FREE shown while
  // the submit charged full price).
  assert.match(src, /if \(d\.free && !isShort\(d\)\) return \{ state: "free"/,
    "the free branch must be guarded by isShort()");
  assert.match(src, /function isShort\(d\)[\s\S]{0,400}if \(d\.card_short\) return true;/,
    "the server's card_short flag is authoritative");
  assert.match(src, /return need != null && held != null && held < need;/,
    "held < needed is the belt for a response carrying counts but no flag");
  const isShortIdx = src.indexOf("function isShort(");
  const classifyIdx = src.indexOf("function classify(");
  assert.ok(isShortIdx > -1 && classifyIdx > -1 && isShortIdx < classifyIdx);
});

test("short renders as PAID with the amber warn treatment + data-short, and the honest full-price note", () => {
  // paid branch derives `short` itself from the raw counts (host never hands it in), and a
  // settled zero is never short.
  assert.match(src, /short = \(n !== 0\) && isShort\(d\);/);
  // The note wording is deliberate (owner + review): NOTHING is attached, the FULL price is
  // charged -- never "covers 2 of 3, the rest costs N" (partial application).
  assert.match(src, /"You hold " \+ \(heldN != null \? fmt\(heldN\) : "\?"\) \+ " of the "/);
  assert.match(src, /" cards this needs — not enough, so no card "\s*\+ "is used\. Costs the full ~" \+ fmt\(n\) \+ " credits\."/);
  assert.doesNotMatch(src, /the rest costs|partially|covers \d+ of/i,
    "no partial-application wording anywhere in the badge");
  // Amber = the existing warn treatment (data-warn), NOT red (error is could-not-verify only).
  assert.match(src, /const dataWarn = \(m\.state === "paid" && \(m\.warn \|\| m\.short\)\) \? "1" : undefined;/,
    "short must ride the paid+warn (amber) attribute -- never invent a red settled state");
  assert.match(src, /const dataShort = \(m\.state === "paid" && m\.short\) \? "1" : undefined;/);
  assert.match(src, /data-short=\{dataShort\}/, "the root carries data-short so hosts/tests can tell short from a host warn");
  // The host's single-slot `warn` keeps its prefix; short does not overwrite it.
  assert.match(src, /\(warn \? "⚠ " \+ warn \+ " · " : \(short \? "⚠ " : ""\)\) \+ "≈ " \+ fmt\(n\) \+ " credits"/,
    "warn keeps its slot in the main line; the short note rides the sub/note line");
  assert.match(src, /if \(short && !compact\) sub = \{ text: shortNote, title: shortNote, days: null \};/);
  // onCost detail exposes it, so a listener (separator chip) can react without parsing text.
  assert.match(src, /card_short: !!m\.short,/);
});

test("the CSS pins the short note in the amber ink (data-short), not the muted expiry grey", () => {
  const css = readFileSync(path.join(__dirname, "../../gallery/src/styles/cost-badge.css"), "utf8");
  assert.match(css, /\.cost-badge\[data-short\] \.mgc-sub \{ color: inherit; \}/);
  assert.match(css, /\.cost-badge\[data-state="paid"\]\[data-warn\]/, "the amber warn rule short rides on still exists");
});
