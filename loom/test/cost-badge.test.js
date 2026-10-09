import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import React from "react";
import { loadComponent, renderElement, query, one } from "../test-support/render.mjs";
import { classify, isShort } from "../../gallery/src/gen/costBadgeCore.js";

// PORTED 2026-08-08 (static/ -> React, vanilla campaign step 4): static/mg-cost-badge.js's
// <mg-cost-badge> custom element was reimplemented as gallery/src/components/CostBadge.jsx --
// a forwardRef + useImperativeHandle component so every existing costRef.current.setPrice/
// setChecking/clear call site (useGenerate/useEditGenerate/EditTab/FixTab and the Loom's
// priceInto) keeps working verbatim. static/mg-cost-badge.js was deleted with its last embedder,
// the video drawer, in step 7 (the campaign's end) -- the video drawer is now the React
// <VideoDrawer>, which embeds this same React <CostBadge>.
//
// What these pin is the HONESTY MACHINE: the whole reason this component exists is that a
// displayed "free"/"0 credits" must only ever mean a settled zero-cost result, never "not priced
// yet" and never "the check failed". Those invariants must survive any future refactor.
//
// They used to be regexes over the component's source. Now the verdict (classify / isShort) is
// tested as plain functions from gallery/src/gen/costBadgeCore.js, and what the badge SHOWS is
// tested by mounting the real component with a ref, pushing responses through its real handle
// and reading the markup (mountWithRef below). Three source/CSS lints stay lints: a network
// call the badge must never make (now read over the core module too), and two CSS cascade facts
// no render can see.
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../gallery/src/components/CostBadge.jsx"), "utf8");
const COST_BADGE = "gallery/src/components/CostBadge.jsx";

/* mountWithRef -- CostBadge mounted with a ref and driven through its REAL imperative handle.

   The render helper (../test-support/render.mjs) is static: it attaches no ref and runs no
   effect, so on its own it can only draw the badge's first, idle frame -- and the badge's whole
   job is what setPrice / setChecking / clear do to that frame. This is the smallest host that
   runs one forwardRef component's hooks for real: it calls the component's own render function
   with a hook dispatcher of its own (installed in React 18's dispatcher slot, the one the
   reconciler itself uses), attaches the imperative handle after the render the way React's
   commit does, runs effects after the handle, re-renders while state changed, and hands every
   frame to the helper's renderElement, so the markup is real react-dom/server output. It
   implements exactly the hooks CostBadge calls; any other hook throws by name, so a new hook in
   the badge fails here loudly instead of being skipped. Written against react@18.3.1 (loom's
   pinned devDependency); a React that moved the dispatcher slot fails the assertion below. */
const INTERNALS = React.__SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED;

function mountWithRef(Component, props = {}) {
  assert.equal(Component.$$typeof, Symbol.for("react.forward_ref"), "mountWithRef mounts a forwardRef component");
  const slot = INTERNALS && INTERNALS.ReactCurrentDispatcher;
  assert.ok(slot && "current" in slot,
    "React's hook dispatcher slot is missing -- mountWithRef is written against react@18.3.1");
  const ref = { current: null };
  const cells = [];
  let cursor = 0, dirty = false, markup = "", layout = [], passive = [];
  const cell = (make) => {
    if (!(cursor in cells)) cells[cursor] = make();
    return cells[cursor++];
  };
  const depsChanged = (prev, next) => next === undefined || prev === undefined
    || next.length !== prev.length || next.some((d, i) => !Object.is(d, prev[i]));
  const hooks = {
    useState(initial) {
      const c = cell(() => {
        const s = { value: typeof initial === "function" ? initial() : initial };
        s.set = (u) => {
          const v = typeof u === "function" ? u(s.value) : u;
          if (!Object.is(v, s.value)) { s.value = v; dirty = true; }
        };
        return s;
      });
      return [c.value, c.set];
    },
    useRef(initial) { return cell(() => ({ current: initial })); },
    useImperativeHandle(r, create, deps) {
      const c = cell(() => ({}));
      if (depsChanged(c.deps, deps)) { c.deps = deps; layout.push(() => { r.current = create(); }); }
    },
    useEffect(effect, deps) {
      const c = cell(() => ({}));
      if (depsChanged(c.deps, deps)) {
        c.deps = deps;
        passive.push(() => {
          if (c.cleanup) c.cleanup();
          const out = effect();
          c.cleanup = typeof out === "function" ? out : null;
        });
      }
    },
  };
  const dispatcher = new Proxy(hooks, {
    get(target, name) {
      if (name in target) return target[name];
      return () => { throw new Error("mountWithRef: the badge now calls " + String(name) + ", which this host does not implement -- add it here"); };
    },
  });
  const renderPass = () => {
    cursor = 0; dirty = false; layout = []; passive = [];
    const prev = slot.current;
    slot.current = dispatcher;
    let element;
    try { element = Component.render(props, ref); } finally { slot.current = prev; }
    markup = renderElement(element);
    layout.forEach((f) => f());
    passive.forEach((f) => f());
  };
  const settle = () => {
    for (let n = 0; dirty; n++) {
      assert.ok(n < 20, "the badge kept re-rendering");
      renderPass();
    }
  };
  renderPass();
  settle();
  return {
    ref,
    /** Call the handle the way a host does (costRef.current.setPrice(d)), then re-render. */
    act(fn) { fn(ref.current); settle(); },
    get $() { return query(markup); },
    get badge() { return one(query(markup).byClass("cost-badge"), "cost badge"); },
  };
}

const mountBadge = async (props) => mountWithRef(await loadComponent(COST_BADGE), props);

test("CostBadge is a forwardRef whose imperative handle keeps the setPrice/clear/setChecking contract", async () => {
  const CostBadge = await loadComponent(COST_BADGE);
  assert.equal(CostBadge.$$typeof, Symbol.for("react.forward_ref"),
    "hosts hold the badge by ref (costRef.current.setPrice ...), so it must forward one");
  const b = mountWithRef(CostBadge, { hint: "Pick a model to see the cost." });
  for (const m of ["setPrice", "clear", "setChecking"]) {
    assert.equal(typeof b.ref.current[m], "function", "the handle must keep " + m + "()");
  }
  assert.equal(b.badge.attr("data-state"), "idle");

  // setPrice feeds the parsed response straight through classify(): a failed check (null) is
  // the could-not-verify ERROR state, worded so it still warns -- not the idle hint clear() gives.
  b.act((h) => h.setPrice(null));
  assert.equal(b.badge.attr("data-state"), "error");
  assert.equal(b.badge.text, "⚠ Couldn't verify the cost — generating may spend credits.");
  assert.equal(b.ref.current.state, "error");
  assert.equal(b.ref.current.settled, false);

  b.act((h) => h.setPrice({ free: false, cost: 600 }));
  assert.equal(b.badge.attr("data-state"), "paid");
  assert.equal(b.badge.text, "≈ 600 credits");
  assert.equal(b.ref.current.state, "paid");
  assert.equal(b.ref.current.settled, true);
  assert.equal(b.ref.current.free, false);
  assert.equal(b.ref.current.cost, 600);
  assert.equal(b.ref.current.text, b.badge.text, "the text accessor reads what the badge shows");

  b.act((h) => h.setChecking());
  assert.equal(b.badge.attr("data-state"), "checking");
  assert.equal(b.badge.text, "Checking cost…");
  assert.equal(b.ref.current.settled, false, "a quote in flight is not a settled price");

  b.act((h) => h.clear("Choose a size first."));
  assert.equal(b.badge.attr("data-state"), "idle");
  assert.equal(b.badge.text, "Choose a size first.", "clear(h) takes a one-shot label");
  assert.equal(b.ref.current.cost, null);
  b.act((h) => h.clear());
  assert.equal(b.badge.text, "Pick a model to see the cost.", "clear() falls back to the hint prop");
});

test("classify: a null/undefined response is the could-not-verify ERROR state, never idle", () => {
  // resp === null/undefined means the fetch itself failed -- the fail-closed state a spend
  // gate exists for. Conflating it with clear()'s idle is precisely the bug this prevents.
  for (const resp of [null, undefined, "", 0, "not json"]) {
    assert.deepEqual(classify(resp), { state: "error", note: "", msg: "", raw: null },
      "classify(" + JSON.stringify(resp) + ") must be the could-not-verify error");
  }
  assert.deepEqual(classify({ error: "upstream 502" }),
    { state: "error", note: "", msg: "upstream 502", raw: { error: "upstream 502" } });
});

test("classify checks a real cost BEFORE the server's note, so a note can never hide a cost", () => {
  const note = "Pick a model to see the cost.";
  assert.equal(classify({ free: false, cost: 600, note }).state, "paid",
    "a response carrying a cost AND a note is a cost");
  assert.equal(classify({ free: false, cost: 0, note }).state, "paid", "a settled zero beats a note too");
  // ...and the note branch still answers when there is no cost at all.
  assert.deepEqual(classify({ free: false, cost: null, note }),
    { state: "idle", note, msg: "", raw: { free: false, cost: null, note } });
});

test("classify: free:false + cost:null + no note + no error is ERROR, not a silent zero", () => {
  // the trailing branch: nothing was actually priced -> honest 'we don't know', never "0 credits".
  for (const resp of [{}, { free: false }, { free: false, cost: null }, { free: false, cost: "n/a" }, { free: false, cost: NaN }]) {
    const v = classify(resp);
    assert.equal(v.state, "error", JSON.stringify(resp) + " priced nothing, so it must be error");
    assert.equal(v.raw, resp);
  }
  // the free branch is the server's verdict and still answers free.
  assert.equal(classify({ free: true }).state, "free");
  assert.equal(classify({ free: true, cost: 600 }).state, "free");
});

test("all five honesty states are represented", async () => {
  const b = await mountBadge({});
  const seen = [b.badge.attr("data-state")];
  b.act((h) => h.setChecking());
  seen.push(b.badge.attr("data-state"));
  b.act((h) => h.setPrice({ free: true, card_name: "Daily card" }));
  seen.push(b.badge.attr("data-state"));
  b.act((h) => h.setPrice({ free: false, cost: 600 }));
  seen.push(b.badge.attr("data-state"));
  b.act((h) => h.setPrice(null));
  seen.push(b.badge.attr("data-state"));
  assert.deepEqual(seen, ["idle", "checking", "free", "paid", "error"]);
});

test("CostBadge NEVER fetches -- the host owns the /api/price call and pushes the result in", () => {
  assert.doesNotMatch(src, /\bfetch\s*\(/, "CostBadge must not call fetch; pricing is pushed in via the ref");
  assert.doesNotMatch(src, /XMLHttpRequest|EventSource|WebSocket/,
    "CostBadge must not open any network channel of its own");
  // The badge's verdict moved to gen/costBadgeCore.js; the same rule covers it.
  const core = readFileSync(path.join(__dirname, "../../gallery/src/gen/costBadgeCore.js"), "utf8");
  assert.doesNotMatch(core, /\bfetch\s*\(/, "costBadgeCore must not call fetch");
  assert.doesNotMatch(core, /XMLHttpRequest|EventSource|WebSocket/,
    "costBadgeCore must not open any network channel of its own");
});

test("a settled ZERO renders as paid-spends-nothing, never borrowing the free-card wording", async () => {
  // loom-core.js's distinction: a priced 0 is real but is NOT the free-card state.
  const b = await mountBadge({});
  b.act((h) => h.setPrice({ free: false, cost: 0 }));
  assert.equal(b.badge.attr("data-state"), "paid");
  assert.equal(b.badge.text, "0 credits — this spends nothing");
  assert.equal(b.badge.attr("title"), "Priced at zero credits. No free card was involved.");
  assert.doesNotMatch(b.badge.html, /FREE|🎫/, "a settled zero never borrows the free card's words");

  b.act((h) => h.setPrice({ free: true, card_name: "Daily card", cost: 600 }));
  assert.equal(b.badge.attr("data-state"), "free");
  assert.equal(b.badge.text, "🎫 FREE — Daily card covers this · saves ~600 credits",
    "the free-card branch keeps its own ticket wording");
  assert.doesNotMatch(b.badge.text, /spends nothing/);
});

// ---- issue #15: multi-ticket cards. The badge is the ONE honest renderer of the card
// sentence; hosts never hand-write it. Two response shapes matter: COVERED (held >= needed,
// free, "uses N of H cards") and SHORT (matched but held < needed -> nothing attached, FULL
// price charged -> paid + amber, never free).
test("free branch: a multi-ticket job says how many of the held cards it uses (1-ticket keeps '(N left)')", async () => {
  const b = await mountBadge({});
  const shown = (resp) => { b.act((h) => h.setPrice({ free: true, card_name: "Video card", ...resp })); return b.badge.text; };
  // covered wording is 'uses N of H cards' with N = cards_needed and H = cards_held
  assert.equal(shown({ cards_needed: 3, cards_held: 5 }), "🎫 FREE — Video card covers this — uses 3 of 5 cards");
  assert.equal(shown({ cards_needed: 2, cards_held: 2 }), "🎫 FREE — Video card covers this — uses 2 of 2 cards",
    "multi-ticket wording starts at cards_needed > 1");
  assert.equal(shown({ cards_needed: 2 }), "🎫 FREE — Video card covers this — uses 2 of your cards");
  // the 1-ticket '(N left)' wording survives unchanged
  assert.equal(shown({ cards_held: 4 }), "🎫 FREE — Video card covers this (4 left)");
  assert.equal(shown({ cards_needed: 1, cards_held: 4 }), "🎫 FREE — Video card covers this (4 left)");
  // held count reads cards_held with the legacy `cards` key as fallback
  assert.equal(shown({ cards: 7 }), "🎫 FREE — Video card covers this (7 left)");
  assert.equal(shown({ cards_held: 2, cards: 9, cards_needed: 2 }), "🎫 FREE — Video card covers this — uses 2 of 2 cards",
    "cards_held wins over the legacy key");
});

test("classify: card_short can NEVER produce the free state -- short is paid, at the full price", () => {
  // A short response falls through to paid (cost) or error (no cost) -- never emerald. This is
  // the exact bug of issue #15 (FREE shown while the submit charged full price).
  const short = { free: false, card_short: true, cost: 600, cards_held: 1, cards_needed: 3 };
  assert.equal(isShort(short), true, "the server's card_short flag is THE short verdict");
  assert.equal(classify(short).state, "paid");
  assert.equal(classify({ card_short: true, cost: 600 }).state, "paid", "short with free absent is paid");
  assert.equal(classify({ free: false, card_short: true, cost: null }).state, "error",
    "short with no cost is could-not-verify, never free and never a silent zero");
  // isShort reads the SERVER verdict only (card_short), and defers to `free`. It used to also
  // re-derive held<needed as a "belt" that could override free:true -- which made this badge
  // disagree with loom-core's priceIsShort (which defers to free) on the identical response:
  // two spend surfaces, two verdicts, one page (review 2026-08-16). One rule now: server decides.
  assert.equal(isShort({ free: true, card_short: true }), false, "isShort must defer to the server's free verdict first");
  assert.equal(isShort({ free: false, cards_held: 1, cards_needed: 3 }), false,
    "no client re-derivation of held<needed inside isShort -- it can only disagree with the server");
  assert.equal(isShort({ free: false, card_short: "true" }), false, "only a real true is the verdict");
  assert.equal(isShort(null), false);
  assert.equal(isShort(undefined), false);
});

test("short renders as PAID with the amber warn treatment + data-short, and the honest full-price note", async () => {
  const shortResp = { free: false, card_short: true, cost: 600, cards_held: 1, cards_needed: 3 };
  // The note wording is deliberate (owner + review): NOTHING is attached, the FULL price is
  // charged -- never "covers 2 of 3, the rest costs N" (partial application).
  const NOTE = "You hold 1 of the 3 cards this needs — not enough, so no card is used. Costs the full ~600 credits.";
  const details = [];
  const b = await mountBadge({ onCost: (d) => details.push(d) });
  b.act((h) => h.setPrice(shortResp));
  const badge = b.badge;
  assert.equal(badge.attr("data-state"), "paid");
  // Amber = the existing warn treatment (data-warn), NOT red (error is could-not-verify only).
  assert.equal(badge.attr("data-warn"), "1", "short must ride the paid+warn (amber) attribute");
  assert.equal(badge.attr("data-short"), "1", "the root carries data-short so hosts/tests can tell short from a host warn");
  // the price line, then the note line (its own span) under it; the text accessor joins them
  assert.equal(badge.text, "⚠ ≈ 600 credits" + NOTE);
  assert.equal(b.ref.current.text, "⚠ ≈ 600 credits · " + NOTE);
  const sub = one(b.$.byClass("mgc-sub"), "note line");
  assert.equal(sub.text, NOTE);
  assert.equal(sub.attr("title"), NOTE);
  assert.doesNotMatch(badge.html, /the rest costs|partially|covers \d+ of/i,
    "no partial-application wording anywhere in the badge");
  // onCost detail exposes it, so a listener (separator chip) can react without parsing text.
  const last = details.at(-1);
  assert.equal(last.card_short, true);
  assert.equal(last.state, "paid");
  assert.equal(last.free, false);
  assert.equal(last.cost, 600);

  // A plain paid price is neither short nor amber, and says so to onCost too.
  b.act((h) => h.setPrice({ free: false, cost: 600 }));
  assert.equal(b.badge.attr("data-short"), undefined);
  assert.equal(b.badge.attr("data-warn"), undefined);
  assert.equal(details.at(-1).card_short, false);

  // A settled zero is never short.
  b.act((h) => h.setPrice({ ...shortResp, cost: 0 }));
  assert.equal(b.badge.attr("data-short"), undefined);
  assert.equal(b.badge.text, "0 credits — this spends nothing");
  assert.equal(details.at(-1).card_short, false);

  // The host's single-slot `warn` keeps its prefix; short does not overwrite it, and the short
  // note rides the note line. A host warn alone is amber without being short.
  const warned = await mountBadge({ warn: "V4.0 full costs more" });
  warned.act((h) => h.setPrice(shortResp));
  assert.equal(warned.badge.text, "⚠ V4.0 full costs more · ≈ 600 credits" + NOTE);
  assert.equal(one(warned.$.byClass("mgc-sub")).text, NOTE);
  assert.equal(warned.badge.attr("data-short"), "1");
  warned.act((h) => h.setPrice({ free: false, cost: 600 }));
  assert.equal(warned.badge.attr("data-warn"), "1");
  assert.equal(warned.badge.attr("data-short"), undefined);

  // The chip has no room for the sentence: no note line there, it rides the label + billing tip.
  const chip = await mountBadge({ compact: true });
  chip.act((h) => h.setPrice(shortResp));
  assert.equal(chip.badge.attr("data-short"), "1");
  assert.equal(chip.$.byClass("mgc-sub").length, 0);
  assert.equal(one(chip.$.byClass("mgc-val")).text, "⚠ ≈ 600");
  assert.equal(one(chip.$.byClass("mgc-lab")).text, "credits · card short");
  assert.equal(one(chip.$.byClass("mgc-tip")).text, NOTE);

  // A short response with no counts never invents one: the unknown count reads "?", never "0".
  b.act((h) => h.setPrice({ free: false, card_short: true, cost: 600 }));
  assert.equal(one(b.$.byClass("mgc-sub")).text,
    "You hold ? of the ? cards this needs — not enough, so no card is used. Costs the full ~600 credits.");
});

test("the badge takes the short verdict from the server's card_short only -- it never re-derives held<needed", async () => {
  // isShort's own assertions cannot see a component that re-derives on its own. Review 2026-08-16
  // removed that 'belt' (held < needed) because it made two spend surfaces give two verdicts on
  // the same response; the badge must follow card_short and `free`, nothing else.
  const b = await mountBadge({});
  b.act((h) => h.setPrice({ free: false, cost: 600, cards_held: 1, cards_needed: 3 }));
  assert.equal(b.badge.attr("data-state"), "paid");
  assert.equal(b.badge.attr("data-short"), undefined, "no card_short flag, so not short");
  assert.equal(b.badge.attr("data-warn"), undefined);
  assert.equal(b.$.byClass("mgc-sub").length, 0, "no short note without the server's verdict");
  assert.equal(b.badge.text, "≈ 600 credits");
  // ...and the server's free verdict wins over a card_short flag.
  b.act((h) => h.setPrice({ free: true, card_short: true, cost: 600, cards_held: 5, cards_needed: 3, card_name: "Video card" }));
  assert.equal(b.badge.attr("data-state"), "free");
  assert.equal(b.badge.attr("data-short"), undefined);
});

test("the CSS pins the short note in the amber ink (data-short), not the muted expiry grey", () => {
  const css = readFileSync(path.join(__dirname, "../../gallery/src/styles/cost-badge.css"), "utf8");
  assert.match(css, /\.cost-badge\[data-short\] \.mgc-sub \{ color: inherit; \}/);
  assert.match(css, /\.cost-badge\[data-state="paid"\]\[data-warn\]/, "the amber warn rule short rides on still exists");
});

test("the VIDEO drawer's CSS does not paint the short state red -- short is settled-paid (amber), red means could-not-verify", () => {
  // Review 2026-08-16: gen-drawer.css overrides paid+data-warn to RED for the V4.0-full caution,
  // at higher specificity than the badge's amber. Video is the ONLY host where multi-ticket short
  // occurs and it lives in this drawer -- so every real short badge painted red, identical to the
  // error state, collapsing the settled-vs-unverified distinction exactly where it matters. The
  // fix re-asserts amber for [data-short] AFTER the red rule at higher specificity. The old test
  // only read cost-badge.css and so never saw this.
  const css = readFileSync(path.join(__dirname, "../../gallery/src/styles/gen-drawer.css"), "utf8");
  const red = css.indexOf('.gen-drawer .cost-badge[data-state="paid"][data-warn]{border-color:var(--red');
  const amber = css.indexOf('.gen-drawer .cost-badge[data-state="paid"][data-warn][data-short]{border-color:var(--peach');
  assert.ok(red >= 0, "the drawer's red V4.0-full override still exists");
  assert.ok(amber >= 0, "the drawer must re-assert amber for [data-short]");
  assert.ok(amber > red, "the amber short rule must come AFTER the red rule so it wins the cascade");
});
