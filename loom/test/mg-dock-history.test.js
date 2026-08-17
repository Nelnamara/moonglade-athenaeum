import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  HISTORY_TILE, HISTORY_STRIP, dayKeyLocal, dayLabel, tileSize, costText, costColor,
  tipLines, mergeHistoryPages, olderLabel, dayCells, rowTag, anyRunning, modelDisplay,
} from "../../gallery/src/gen/historyCore.js";
import { dockLayout, SLAB_CHROME } from "../../gallery/src/gen/dockLayout.js";

// The Generate dock's HISTORY mode -- DECISIONS.md "Generate dock History -- LOCKED"
// (2026-08-16) + the height-pass amendment, drawn in Frontend Gallery.dc.html (C3a):
// 7 local-day buckets newest first, a 2-row column-flow grid per day, fixed 96px
// aspect-true tiles, "Load N older days ⌄" appending pages, the tooltip on every single
// tile mounted OUTSIDE the transformed dock, cost text from the settled paid_credit --
// and History as its own dock mode (ceiling 100vh − 28). historyCore.js is pure and runs
// here directly; what cannot be pure (the strip's place in the dock, the header copy,
// prefill leaving History, the tooltip's mount) is pinned in the source, short and literal.

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8");

describe("day labels: Today · Yesterday · 'Sat 9 Aug' (DC 2679 / 1909)", () => {
  test("today and yesterday by LOCAL calendar day, then weekday day month, no year, no zero pad", () => {
    assert.equal(dayLabel("2026-08-17", "2026-08-17"), "Today");
    assert.equal(dayLabel("2026-08-16", "2026-08-17"), "Yesterday");
    // the DC's "Sat 9 Aug" pattern -- real weekdays for the real dates (the DC's own
    // labels were a hand-written stand-in on a fictional calendar)
    assert.equal(dayLabel("2026-08-15", "2026-08-17"), "Sat 15 Aug");
    assert.equal(dayLabel("2026-08-09", "2026-08-17"), "Sun 9 Aug");
    assert.equal(dayLabel("2026-08-14", "2026-08-17"), "Fri 14 Aug");
    assert.equal(dayLabel("2026-08-10", "2026-08-17"), "Mon 10 Aug");
    assert.equal(dayLabel("2026-01-05", "2026-08-17"), "Mon 5 Jan");
  });
  test("yesterday across a month boundary", () => {
    assert.equal(dayLabel("2026-07-31", "2026-08-01"), "Yesterday");
    assert.equal(dayLabel("2026-07-30", "2026-08-01"), "Thu 30 Jul");
  });
  test("dayKeyLocal buckets by the given offset (a 06:30Z row on the 17th is the 16th at tz -420)", () => {
    const ts = Date.UTC(2026, 7, 17, 6, 30) / 1000;
    assert.equal(dayKeyLocal(ts, -420), "2026-08-16");
    assert.equal(dayKeyLocal(ts, 0), "2026-08-17");
    assert.equal(dayKeyLocal(ts, 600), "2026-08-17");
  });
});

describe("tiles: th 96, width max(44, round(th × w/h)) from real dims (DC 2689)", () => {
  test("real dims -> aspect-true widths", () => {
    assert.equal(HISTORY_TILE, 96);
    assert.deepEqual(tileSize("image", 832, 1216), { w: 66, h: 96 });
    assert.deepEqual(tileSize("image", 1024, 1024), { w: 96, h: 96 });
    assert.deepEqual(tileSize("image", 1216, 832), { w: 140, h: 96 });
    assert.deepEqual(tileSize("image", 1344, 768), { w: 168, h: 96 });
    assert.deepEqual(tileSize("video", 1280, 720), { w: 171, h: 96 });
  });
  test("fallbacks: image 832×1216, VIDEO 1280×720 (most video rows lack dims)", () => {
    assert.deepEqual(tileSize("image", null, null), { w: 66, h: 96 });
    assert.deepEqual(tileSize("video", null, null), { w: 171, h: 96 });
    assert.deepEqual(tileSize("image", 0, undefined), { w: 66, h: 96 });
  });
  test("the 44px floor and a custom th", () => {
    assert.deepEqual(tileSize("image", 100, 1000), { w: 44, h: 96 });
    assert.deepEqual(tileSize("image", 832, 1216, 132), { w: 90, h: 132 });
  });
});

describe("cost: the ONE settled-cost formatter (DC 2706/2719 strings, paid_credit as data)", () => {
  test("costText by state", () => {
    assert.equal(costText(null, "running"), "still resolving…");
    assert.equal(costText(1200, "stale"), "~1,200 cr");   // stale is NOT running -- the reel's verdict
    assert.equal(costText(0, "done"), "free card");
    assert.equal(costText(1200, "done"), "~1,200 cr");
    assert.equal(costText(35, "done"), "~35 cr");
    assert.equal(costText(null, "done"), "");
    assert.equal(costText(undefined, "done"), "");
    assert.equal(costText(null, "failed"), "");
  });
  test("costColor: free green; paid mauve in the tooltip, overlay0 in the caption; resolving subtext", () => {
    assert.equal(costColor(0, "done", "tip"), "var(--green)");
    assert.equal(costColor(0, "done", "caption"), "var(--green)");
    assert.equal(costColor(1200, "done", "tip"), "var(--mauve)");
    assert.equal(costColor(1200, "done", "caption"), "var(--overlay0)");
    assert.equal(costColor(null, "running", "tip"), "var(--subtext)");
    assert.equal(costColor(null, "running", "caption"), "var(--subtext)");
  });
});

describe("tooltip lines (DC 2711-2723 / 1594-1605): tag · time · model · dims · prompt · cost", () => {
  const ts = new Date(2026, 7, 16, 19, 27).getTime() / 1000;   // local Aug 16, 7:27 PM
  test("an image row", () => {
    const L = tipLines({
      task_id: "task_abc1234", media_id: "m9", kind: "image", state: "done", ts,
      w: 832, h: 1216, model: "Moonbeam XL", prompt: "  a fox\n  in   moonlight ", paid_credit: 1200,
    });
    assert.equal(L.tag, "#1234");
    assert.equal(L.time, "Aug 16, 7:27 PM");
    assert.equal(L.model, "Moonbeam XL");
    assert.equal(L.dims, "832 × 1216");
    assert.equal(L.prompt, "a fox in moonlight");
    assert.equal(L.cost, "~1,200 cr");
    assert.equal(L.costColor, "var(--mauve)");
    assert.deepEqual(Object.keys(L), ["tag", "time", "model", "dims", "prompt", "cost", "costColor"]);
  });
  test("a video row: roster name for the model id, ' · Ns' after the dims", () => {
    const L = tipLines({ task_id: "t5678", kind: "video", state: "done", ts, w: 1280, h: 720, model: "v4.0.1", duration: 5, paid_credit: 0 });
    assert.equal(L.model, "V4.0 Lite Preview");
    assert.equal(L.dims, "1280 × 720 · 5s");
    assert.equal(L.cost, "free card");
    assert.equal(L.costColor, "var(--green)");
    assert.equal(modelDisplay({ kind: "video", model: "v2.7" }), "V2.7 (High Dynamics)");
    assert.equal(modelDisplay({ kind: "video", model: "vX" }), "vX", "an unknown id stays raw");
  });
  test("a running synthetic row: '—' model, no dims (no fake 832×1216), no prompt, 'still resolving…'", () => {
    const L = tipLines({ job_id: "j0042", task_id: "j0042", kind: "image", state: "running", ts, w: null, h: null, prompt: null, model: null });
    assert.equal(L.tag, "#0042");
    assert.equal(L.model, "—");
    assert.equal(L.dims, "");
    assert.equal(L.prompt, "");
    assert.equal(L.cost, "still resolving…");
    assert.equal(L.costColor, "var(--subtext)");
  });
  test("tag falls back task_id -> media_id -> job_id", () => {
    assert.equal(rowTag({ media_id: "media_9999" }), "#9999");
    assert.equal(rowTag({ job_id: "abcd" }), "#abcd");
  });
});

const day = (date, rows = []) => ({ date, label_hint: null, rows });
const P1 = { tz: -420, days: [day("2026-08-17", [{ task_id: "a" }]), day("2026-08-16"), day("2026-08-15", [{ task_id: "b" }])],
  next_before: "2026-08-13", has_more: true, older_days: 3 };
const P2 = { tz: -420, days: [day("2026-08-12", [{ task_id: "c" }]), day("2026-08-11"), day("2026-08-10", [{ task_id: "d" }])],
  next_before: null, has_more: false, older_days: 0 };

describe("paging: mergeHistoryPages appends older days, newest first, no duplicate dates", () => {
  test("first page from nothing", () => {
    const M = mergeHistoryPages(null, P1);
    assert.deepEqual(M.days.map((d) => d.date), ["2026-08-17", "2026-08-16", "2026-08-15"]);
    assert.equal(M.has_more, true);
    assert.equal(M.older_days, 3);
    assert.equal(M.next_before, "2026-08-13");
  });
  test("an older page appends and takes over the cursor", () => {
    const M = mergeHistoryPages(mergeHistoryPages(null, P1), P2);
    assert.deepEqual(M.days.map((d) => d.date),
      ["2026-08-17", "2026-08-16", "2026-08-15", "2026-08-12", "2026-08-11", "2026-08-10"]);
    assert.equal(M.has_more, false);
    assert.equal(M.next_before, null);
  });
  test("a refresh of the first page replaces its days' rows and keeps the older pages + cursor", () => {
    const M0 = mergeHistoryPages(mergeHistoryPages(null, P1), P2);
    const fresh = { ...P1, days: [day("2026-08-17", [{ task_id: "z" }, { task_id: "a" }]), day("2026-08-16"), day("2026-08-15", [{ task_id: "b" }])] };
    const M = mergeHistoryPages(M0, fresh);
    assert.equal(M.days.length, 6);
    assert.deepEqual(M.days[0].rows.map((r) => r.task_id), ["z", "a"]);
    assert.equal(M.has_more, false, "the cursor still belongs to the furthest-back page");
  });
  test("olderLabel: 'Load N older days ⌄' / 'Loaded through <oldest>' / 'Loading…'", () => {
    const M1 = mergeHistoryPages(null, P1);
    assert.equal(olderLabel(M1, false, "2026-08-17"), "Load 3 older days ⌄");
    const M2 = mergeHistoryPages(M1, P2);
    assert.equal(olderLabel(M2, false, "2026-08-17"), "Loaded through Mon 10 Aug");
    assert.equal(olderLabel(mergeHistoryPages(null, { ...P1, has_more: false }), false, "2026-08-16"),
      "Loaded through Yesterday");
    assert.equal(olderLabel(M2, true, "2026-08-17"), "Loading…");
    assert.equal(olderLabel(null, false, "2026-08-17"), "");
  });
});

describe("cells: one per row, cluster for a running batch, cost once per task", () => {
  test("done rows keep their order; cost shows on the first row of a task only", () => {
    const cells = dayCells([
      { task_id: "t1", media_id: "m2", state: "done", kind: "image", w: 1024, h: 1024, paid_credit: 900 },
      { task_id: "t1", media_id: "m1", state: "done", kind: "image", w: 1024, h: 1024, paid_credit: 900 },
      { task_id: "t0", media_id: "v1", state: "done", kind: "video", duration: 5 },
    ]);
    assert.deepEqual(cells.map((c) => c.kind), ["done", "done", "done"]);
    assert.deepEqual(cells.map((c) => c.showCost), [true, false, true]);
    assert.deepEqual(cells[0].size, { w: 96, h: 96 });
    assert.deepEqual(cells[2].size, { w: 171, h: 96 });
    assert.equal(cells[2].video, true);
    assert.equal(cells[0].key, "t1:m2");
  });
  test("running count 1 -> a running tile; count > 1 -> the 96×96 cluster; failed/stale -> fail", () => {
    const cells = dayCells([
      { job_id: "j1", task_id: "j1", state: "running", kind: "image", count: 1 },
      { job_id: "j2", task_id: "j2", state: "running", kind: "image", count: 4 },
      { job_id: "j3", task_id: "j3", state: "failed", kind: "image", count: 2 },
      { job_id: "j4", task_id: "j4", state: "stale", kind: "image", count: 4 },
    ]);
    assert.deepEqual(cells.map((c) => c.kind), ["running", "cluster", "fail", "fail"]);
    assert.equal(cells[1].count, 4);
    assert.deepEqual(cells[1].size, { w: 96, h: 96 });
    assert.equal(cells[2].count, 1);
    // stale is the reel's verdict too (isRunningJob treats it as terminal): no mascot, no poll
    assert.equal(anyRunning({ days: [day("2026-08-17", [{ state: "done" }, { state: "stale" }])] }), false);
    assert.equal(anyRunning({ days: [day("2026-08-17", [{ state: "done" }, { state: "running" }])] }), true);
    assert.equal(anyRunning({ days: [day("2026-08-17", [{ state: "done" }])] }), false);
  });
});

describe("History is its own dock mode (DC dockStyle 3505-3506; DECISIONS 2551/2565)", () => {
  const desk = { vh: 1080, sepBottom: 262, promptLen: 0, promptFocus: false };
  test("historyOpen alone lifts the clamp to 100vh − 28 and the reel's cap with it", () => {
    const L = dockLayout({ ...desk, historyOpen: true });
    assert.equal(L.capH, desk.vh - 28);
    assert.equal(L.reelRoom, (desk.vh - 28) - 56 - 118 - 46);
    assert.equal(L.reelVisible, true);
    const S = dockLayout({ ...desk });
    assert.equal(S.capH, desk.vh - desk.sepBottom - 14);
  });
  test("the prompt cap counts the 2-row strip (HISTORY_STRIP) in place of the reel term", () => {
    assert.equal(HISTORY_STRIP, 260);
    const L = dockLayout({ ...desk, vh: 900, historyOpen: true, promptLen: 2000 });
    // chrome = 46 + 260 + 96 = 402; (872 − 402) / 25 = 18 -> capped at 14
    assert.equal(L.promptMax, 14);
    const E = dockLayout({ ...desk, vh: 900, historyOpen: true, expanded: true, promptLen: 2000 });
    // chrome = 46 + 260 + 330 + 96 = 732; (872 − 732) / 25 = 5 -> cap 5, floor 6 wins
    assert.equal(E.promptMax, Math.floor((872 - (46 + HISTORY_STRIP + SLAB_CHROME + 96)) / 25));
    assert.equal(E.promptRows, 6);
  });
});

describe("the dock wires History (source guards -- the parts that are not pure)", () => {
  const dock = src("gallery/src/components/GenerateDrawer.jsx");
  const strip = src("gallery/src/components/HistoryStrip.jsx");
  const reel = src("gallery/src/components/RunsReel.jsx");
  const css = src("gallery/src/styles/dock.css");

  test("HistoryStrip renders in the reel's place under reelVisible && historyOpen", () => {
    assert.match(dock, /import HistoryStrip, \{ RunTip \} from "\.\/HistoryStrip\.jsx"/);
    assert.match(dock, /\{reelVisible && \(historyOpen\s*\? <HistoryStrip[\s\S]*?: <RunsReel/);
  });
  test("header copy: label 'History', note '7 days · newest first · …', the live note wins; no stale title", () => {
    assert.match(dock, /const reelLabel = historyOpen \? "History" : \(runningCount \? "Making" : "Runs"\);/);
    assert.match(dock, /"7 days · newest first · click any run to reuse its settings"/);
    assert.match(dock, /"today · click any run to reuse its settings"/);
    assert.doesNotMatch(dock, /grouped by day/);
    assert.doesNotMatch(dock, /Fold yesterday's runs/);
  });
  test("prefill from a tile exits History into the expanded composer (DC 2321)", () => {
    const i = dock.indexOf("const prefillFromRun = useCallback(");
    const body = dock.slice(i, dock.indexOf("}, [g]);", i));
    assert.match(body, /setExpanded\(true\);/);
    assert.match(body, /setHistoryOpen\(false\);/);
  });
  test("the tooltip is a SIBLING of the aside, never inside the transformed .mgdock", () => {
    const asideOpen = dock.indexOf("<aside ref={drawerRef}");
    const asideClose = dock.indexOf("</aside>", asideOpen);
    const tip = dock.indexOf("<RunTip tip={runTip} />");
    assert.ok(asideOpen > 0 && asideClose > asideOpen && tip > asideClose, "RunTip after </aside>");
    assert.match(css, /\.mgdock-runtip \{ position: fixed; z-index: 300;/);
    assert.match(css, /transform: translate\(-50%, calc\(-100% - 8px\)\)/);
    assert.match(css, /background: #0a0818; border: 1px solid rgba\(182, 146, 230, \.4\)/);
  });
  test("no native title on tiles (the tooltip replaces it); the DC's hint copy", () => {
    for (const s of [strip, reel]) {
      const tiles = s.match(/className=\{"mgdock-tile[\s\S]*?>/g) || [];
      assert.ok(tiles.length > 0);
      for (const t of tiles) assert.doesNotMatch(t, /\btitle=/);
      assert.match(s, /Use these settings →/);
    }
    assert.doesNotMatch(reel, /Reuse prompt/);
  });
  test("RunsReel: no yesterday grouping, no .wrap; cost via costText; mascot + shimmer, no eclipse", () => {
    assert.doesNotMatch(reel, /historyOpen/);
    assert.doesNotMatch(reel, /" wrap"/);
    assert.doesNotMatch(css, /\.mgdock-reel\.wrap/);
    assert.match(reel, /costText\(/);
    assert.doesNotMatch(reel, /free card/);
    assert.doesNotMatch(reel, /mgdock-eclipse/);
    assert.match(reel, /<RunningFace/);
  });
  test("the strip: fixed 96 tiles, day divider evolved (padding-right 4px), the 2-row grid, No runs, the older control", () => {
    assert.match(strip, /GET \/api\/next\/history|\/api\/next\/history\?days=/);
    assert.match(strip, /"No runs"|>No runs</);
    assert.match(strip, /className="mgdock-histgrid"/);
    assert.match(strip, /className="mgdock-older"/);
    assert.match(css, /\.mgdock-histgrid \{ display: grid; grid-auto-flow: column; grid-template-rows: repeat\(2, auto\);\s*gap: 10px 12px; align-items: start; \}/);
    assert.match(css, /\.mgdock-daydiv \{[^}]*padding-right: 4px;/);
    assert.match(css, /\.mgdock-vtag \{ position: absolute; left: 5px; bottom: 5px; z-index: 2; font-size: 8\.5px;/);
    assert.match(css, /@keyframes mgNelHalo/);
    assert.match(css, /@keyframes mgShimmer/);
    assert.match(css, /\/branding\/mascots\/gen_nel\.png/);
    assert.match(strip, /const MASCOT = "\/branding\/mascots\/gen_nel\.png"/);
    assert.match(strip, /<img className="mgdock-runmascot" src=\{MASCOT\} alt="" onError=/);
    // reduced motion covers the halo and the shimmer
    const rm = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    assert.match(rm, /\.mgdock-runhalo/);
    assert.match(rm, /\.mgdock-shim > i/);
  });
});
