import { test } from "node:test";
import assert from "node:assert/strict";
import {
  render, loadComponent, loadModule, bundleInputs, renderElement, h, query, one, LOOM_MOCKS,
} from "../test-support/render.mjs";

// The render helper (loom/test-support/render.mjs) proves itself here on real components:
// two from gallery/src and one from inside loom/master-storyboard.jsx. Each test renders the
// component with props and asserts on the MARKUP, never on the source text. What a static
// render cannot see (clicks, effects, timers, imperative handles) is in the helper's header.

const COST_BADGE = "gallery/src/components/CostBadge.jsx";
const ACTIVITY_ROW = "gallery/src/notify/ActivityRow.jsx";
const STORYBOARD = "loom/master-storyboard.jsx";

/* ---------- gallery/src: CostBadge, the one renderer of "this costs N credits" ---------- */

// CostBadge uses hooks, so these renders also prove the bundle's React is the helper's own copy
// (loom/node_modules): a second React would throw "Invalid hook call" here.
test("CostBadge before any price: idle, its hint, and never a free or zero-credit claim", async () => {
  const $ = query(await render(COST_BADGE, "default", { hint: "Pick a model to see the cost." }));
  const badge = one($.byClass("cost-badge"), "cost badge");
  assert.equal(badge.attr("data-state"), "idle");
  assert.equal(badge.attr("role"), "status");
  assert.equal(badge.text, "Pick a model to see the cost.");
  // Not priced yet must never read as free or as a settled zero (the badge's fail-closed rule).
  assert.doesNotMatch(badge.text, /free|0 credits/i);
  assert.equal(badge.attr("data-warn"), undefined);
  assert.equal(badge.attr("data-short"), undefined);
});

test("CostBadge with no hint falls back to its own not-priced wording; compact adds the class", async () => {
  const $ = query(await render(COST_BADGE, "default", { compact: true, className: "lv-cost" }));
  const badge = one($.byClass("cost-badge"), "cost badge");
  assert.deepEqual(badge.classes, ["cost-badge", "compact", "lv-cost"]);
  assert.equal(badge.text, "No cost yet — nothing to price.");
  // An idle chip has no value to show, so the chip parts are not drawn.
  assert.equal($.byClass("mgc-val").length, 0);
});

/* ---------- gallery/src: ActivityRow, one job in the Activity dropdown ---------- */

const doneJob = {
  job_id: "task-123", type: "generate", status: "done", label: "Generated",
  ts: 1700000000, started_at: 1699999990,
};

test("ActivityRow expanded shows a COST row only when the job carries a real credit figure", async () => {
  const withCost = query(await render(ACTIVITY_ROW, "default",
    { job: { ...doneJob, paid_credit: 1200 }, expanded: true }));
  const costKey = one(withCost.byText("COST"), "COST label");
  assert.equal(costKey.parent.text, "COST1,200 credits");

  // No figure, or a non-finite one: no row at all, never a made-up "0 credits".
  for (const paid_credit of [undefined, null, NaN, "1200"]) {
    const $ = query(await render(ACTIVITY_ROW, "default", { job: { ...doneJob, paid_credit }, expanded: true }));
    assert.equal($.byText("COST").length, 0, "no COST row for paid_credit=" + String(paid_credit));
    assert.equal($.byText("credits").length, 0);
  }
});

test("ActivityRow states: a finished row offers Dismiss, a running one says it only stops tracking", async () => {
  const done = query(await render(ACTIVITY_ROW, "default", { job: doneJob, expanded: false }));
  const row = one(done.byClass("at-row"), "row");
  assert.equal(row.attr("aria-expanded"), "false");
  assert.equal(done.byClass("at-detail").length, 0, "collapsed: no detail block");
  assert.equal(one(done.byClass("at-x")).attr("title"), "Dismiss");

  const running = query(await render(ACTIVITY_ROW, "default",
    { job: { ...doneJob, status: "running", started: false }, expanded: true }));
  const stop = one(running.byText("Stop tracking"), "stop button");
  assert.equal(stop.tag, "button");
  assert.match(stop.attr("title"), /does not cancel it on PixAI/);
  assert.equal(running.byClass("at-phase")[0].text, "queued");
  assert.equal(one(running.byText("Queued")).attr("class"), "at-dv");
});

test("effects never run: a running, expanded row (whose effect starts a 1 s timer) renders with no timer or fetch", async () => {
  const Row = await loadComponent(ACTIVITY_ROW);
  const calls = [];
  const saved = { setInterval: globalThis.setInterval, setTimeout: globalThis.setTimeout, fetch: globalThis.fetch };
  globalThis.setInterval = (...a) => { calls.push("setInterval"); return saved.setInterval(...a); };
  globalThis.setTimeout = (...a) => { calls.push("setTimeout"); return saved.setTimeout(...a); };
  globalThis.fetch = async () => { calls.push("fetch"); throw new Error("no fetch in a render"); };
  let html;
  try {
    html = renderElement(h(Row, { job: { ...doneJob, status: "running" }, expanded: true }));
  } finally {
    Object.assign(globalThis, saved);
  }
  assert.deepEqual(calls, []);
  assert.match(query(html).byClass("at-detail")[0].text, /so far/);
});

/* ---------- loom/master-storyboard.jsx: TakeList, a component the file does not export ---------- */

const card = {
  resultMid: "m2", takeSeq: 2, selectedTake: 2,
  takes: [
    { id: "t1", n: 1, mid: "m1", at: "", source: "render", settings: { mode: "I2V", duration: 5, quality: "720p" } },
    { id: "t2", n: 2, mid: "m2", at: "", source: "render", settings: null },
  ],
};
const noop = () => {};

test("TakeList (inside master-storyboard.jsx) lists takes newest first and guards the take in use", async () => {
  const $ = query(await render(STORYBOARD, "TakeList",
    { card, code: "S1", onUse: noop, onReuse: noop, onDelete: noop }, { mocks: LOOM_MOCKS }));
  const list = one($.byClass("lv-takelist"), "take list");
  assert.equal(list.attr("aria-label"), "Takes of S1");
  assert.equal(one(list.byClass("lv-takelist-h")).text, "S1 · 2 takes");

  const items = list.byClass("lv-takeitem");
  assert.deepEqual(items.map((i) => one(i.byClass("lv-taketitle")).text), ["take 2 · ★ in use", "take 1"]);
  const [inUse, other] = items;
  assert.ok(inUse.hasClass("on"));

  // The selected take: no Use button, and its Delete is disabled (select another take first).
  assert.equal(inUse.byText("★ Use").length, 0);
  const delInUse = one(inUse.byText("Delete…"));
  assert.equal(delInUse.attr("disabled"), "");
  assert.equal(delInUse.attr("title"), "Select another take first");
  // No settings were recorded for take 2: Reuse is disabled and says why.
  const reuseInUse = one(inUse.byText("Reuse settings"));
  assert.equal(reuseInUse.attr("disabled"), "");

  // The other take: Use offered, Delete enabled, its settings summarised and reusable.
  assert.equal(one(other.byText("★ Use")).attr("title"), "Use take 1 for Play, Render and Export");
  assert.equal(one(other.byText("Delete…")).attr("disabled"), undefined);
  assert.equal(one(other.byText("Reuse settings")).attr("disabled"), undefined);
  assert.equal(one(other.byClass("lv-takemeta")).text, "an earlier render · I2V · 5 s · 720p");
});

test("TakeList renders nothing for a shot with no render", async () => {
  const html = await render(STORYBOARD, "TakeList",
    { card: { takes: [] }, code: "S2", onUse: noop, onReuse: noop, onDelete: noop }, { mocks: LOOM_MOCKS });
  assert.equal(html, "");
});

test("master-storyboard.jsx refuses to load without LOOM_MOCKS, and fetches nothing trying", async () => {
  const saved = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async () => { calls.push("fetch"); throw new Error("no fetch"); };
  try {
    await assert.rejects(loadModule(STORYBOARD), /window is not defined[\s\S]*mock that module/);
  } finally {
    globalThis.fetch = saved;
  }
  assert.deepEqual(calls, []);
});

/* ---------- the helper itself ---------- */

test("builds are cached: the same file and mocks give the same component, without a rebuild", async () => {
  // A rebuild would evaluate a fresh module, and with it a new function: identity is the proof.
  const a = await loadComponent(STORYBOARD, "TakeList", { mocks: LOOM_MOCKS });
  const b = await loadComponent(STORYBOARD, "TakeList", { mocks: LOOM_MOCKS });
  assert.equal(a, b);
  assert.equal(await loadComponent(COST_BADGE), await loadComponent(COST_BADGE, "default"));
});

// gallery/node_modules exists on a dev box (CI's loom job never installs it), so a bundle that
// quietly resolved a package from it would pass here and break CI: this is the guard for that.
test("nothing is bundled from any node_modules (React stays external) and a gallery-only package is stubbed", async () => {
  for (const [src, opts] of [[COST_BADGE, {}], [ACTIVITY_ROW, {}], [STORYBOARD, { mocks: LOOM_MOCKS }],
    ["gallery/src/components/BonjourCard.jsx", {}]]) {
    const inputs = await bundleInputs([src], opts);
    assert.ok(inputs.length > 0);
    assert.deepEqual(inputs.filter((p) => /node_modules/.test(p)), [], src + " bundled a package file");
  }
  // BonjourCard imports qrcode-generator, which only gallery/node_modules has: it loads, stubbed.
  const mod = await loadModule("gallery/src/components/BonjourCard.jsx");
  assert.equal(typeof mod.default, "function");
});

test("an unknown name fails with the names the file does have", async () => {
  await assert.rejects(loadComponent(COST_BADGE, "NoSuchThing"), /no export or top-level component named 'NoSuchThing'.*default/);
});

test("query: entities, void elements, nesting, innermost text match, attribute and class lookups", () => {
  const html = renderElement(h("div", { className: "a b", "data-x": "1" },
    h("p", null, "Tom & Jerry <3 \"quoted\""),
    h("img", { src: "/x.png", alt: "" }),
    h("ul", null, h("li", { className: "b" }, "one"), h("li", null, h("span", null, "two"))),
    h("button", { disabled: true, title: "it's" }, "Go")));
  const $ = query(html);
  const root = one($.byClass("a"));
  assert.equal(root.tag, "div");
  assert.equal(root.html, html);
  assert.equal(one($.byTag("p")).text, "Tom & Jerry <3 \"quoted\"");
  assert.equal(one($.byTag("img")).attr("src"), "/x.png");
  assert.equal($.byTag("li").length, 2);
  assert.equal($.byClass("b").length, 2);                      // the div and the first li
  assert.equal(one($.byText("two")).tag, "span");              // innermost, not the li or ul
  assert.equal(one($.byText(/^Go$/)).attr("title"), "it's");
  assert.equal(one($.byAttr("disabled")).tag, "button");
  assert.equal(one($.byAttr("data-x", "1")).tag, "div");
  assert.equal(root.text, "Tom & Jerry <3 \"quoted\"onetwoGo");
});
