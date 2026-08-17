// The Generate dock's HISTORY mode -- the pure half (no DOM, no React), so the loom
// node-tests run the SAME functions the strip renders from.
//
// Design of record: design_handoff/design_handoff_moonglade_suite/Frontend Gallery.dc.html
// (C3a) -- mkRun 2683-2726 (tile geometry, caption cost), groupDefs 2677-2681 (day labels),
// olderLabel 3524, tooltip 2711-2723 + 1594-1605; DECISIONS.md "Generate dock History --
// LOCKED" (2026-08-16). Content is REAL: the catalog-backed feed GET /api/next/history
// (7 local days, newest first, jobs.jsonl live rows merged server-side) replaces the DC's
// SEEDED / OLDER_SEED stand-ins, DAY_LABELS, `age` bucketing and the hand-written cost.

import { fmtClock } from "../notify/format.js";
import { MODELS as VIDEO_MODELS } from "./videoDrawerCore.js";

export const HISTORY_TILE = 96;    // DC 2689: `th = s.historyOpen ? 96 : …`
// The strip's chrome for dockLayout: 2 rows × (96 tile + 6 gap + ~14 caption) + 10 row gap
// + 11/7 padding ≈ 260 -- the Respec's own budget number (RS 393).
export const HISTORY_STRIP = 260;
export const HISTORY_DAYS = 7;

const WD = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const pad2 = (n) => (n < 10 ? "0" : "") + n;

/* ---- local-day keys ("YYYY-MM-DD") ------------------------------------------------ */

// tsSec -> the LOCAL calendar day. With `tzMin` (minutes EAST of UTC, the /api/next/history
// `tz` idiom) the day is computed for that offset -- deterministic for the tests; without
// it, the runtime's own zone (Date getters).
export function dayKeyLocal(tsSec, tzMin) {
  if (tzMin === undefined || tzMin === null) {
    const d = new Date((tsSec || 0) * 1000);
    return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
  }
  const d = new Date(((tsSec || 0) + tzMin * 60) * 1000);
  return d.getUTCFullYear() + "-" + pad2(d.getUTCMonth() + 1) + "-" + pad2(d.getUTCDate());
}
export function todayKey(nowSec, tzMin) {
  return dayKeyLocal(nowSec === undefined ? Date.now() / 1000 : nowSec, tzMin);
}
export function tzMinutes() { return -new Date().getTimezoneOffset(); }

const parseKey = (s) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || ""));
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
};
const utcOf = (k) => (k ? Date.UTC(k[0], k[1] - 1, k[2]) : NaN);

// DC 2679 / 1909: Today · Yesterday · then `<Www> <D> <Mon>` (weekday abbrev, day without a
// leading zero, month abbrev, no year -- e.g. "Sat 9 Aug").
export function dayLabel(dateStr, todayStr) {
  const k = parseKey(dateStr);
  if (!k) return String(dateStr || "");
  const t = parseKey(todayStr);
  if (t) {
    const diff = utcOf(t) - utcOf(k);
    if (diff === 0) return "Today";
    if (diff === 86400000) return "Yesterday";
  }
  const wd = new Date(utcOf(k)).getUTCDay();
  return WD[wd] + " " + k[2] + " " + MON[k[1] - 1];
}

/* ---- tiles ------------------------------------------------------------------------- */

// DC 2689: width = max(44, round(th × w/h)), fallback 832×1216 for images. Video rows mostly
// lack dims; the DC drew its video tile at 1280×720, so that is the video fallback.
export function tileSize(kind, w, h, th) {
  const H = th || HISTORY_TILE;
  const video = kind === "video";
  const fw = video ? 1280 : 832, fh = video ? 720 : 1216;
  const W = Number(w) > 0 ? Number(w) : fw;
  const Hh = Number(h) > 0 ? Number(h) : fh;
  return { w: Math.max(44, Math.round(H * (W / Hh))), h: H };
}

// ONE verdict per job across the reel and History: `stale` (accepted-but-stuck /
// unreachable, moonglade_backup._reconcile) is NOT running -- the reel's isRunningJob
// already treats it as terminal, the peek pill does not count it, and a stuck job must
// not wear the mascot for 24h. It renders as the fail cell with its own caption.
export const isRunningState = (st) => st === "running";

// THE settled-cost formatter (DC 2706 / 2719 as strings, `paid_credit` -- the settled actual
// -- as data). RunsReel and History both use it; nobody hand-formats a cost line.
export function costText(paidCredit, state) {
  if (isRunningState(state)) return "still resolving…";
  if (paidCredit === 0) return "free card";
  if (typeof paidCredit === "number" && isFinite(paidCredit)) {
    return "~" + Math.round(paidCredit).toLocaleString() + " cr";
  }
  return "";
}
// DC 2707 (caption: free green / paid overlay0) and DC 2720 (tooltip: free green / paid mauve);
// "still resolving…" is subtext (DC 3529's default).
export function costColor(paidCredit, state, where) {
  if (isRunningState(state)) return "var(--subtext)";
  if (paidCredit === 0) return "var(--green)";
  if (typeof paidCredit === "number" && isFinite(paidCredit)) {
    return where === "tip" ? "var(--mauve)" : "var(--overlay0)";
  }
  return where === "tip" ? "var(--subtext)" : "var(--overlay0)";
}

export function rowTag(row) {
  const id = (row && (row.task_id || row.media_id || row.job_id)) || "";
  return "#" + String(id).slice(-4);
}
export function rowKey(row) {
  return (row.task_id || row.job_id || "") + ":" + (row.media_id || "");
}

// The video roster's display name for a video row's `model` (e.g. v4.0.1 -> "V4.0 Lite
// Preview"); image rows carry their display name already (COALESCE(model_name, …)).
export function modelDisplay(row) {
  const raw = (row && row.model) || "";
  if (row && row.kind === "video") {
    const m = VIDEO_MODELS.find((x) => x.value === raw);
    if (m) return m.label;
  }
  return raw || "—";
}

// DC 2711-2723: the tooltip's lines, in the DC's order. `dims` is only written when the row
// really has dims (the DC's 832×1216 fallback is a stand-in -- no fake dims); `prompt` is
// one line; empty strings mean "no line".
export function tipLines(row, modelName) {
  const r = row || {};
  const video = r.kind === "video";
  const w = Number(r.w) > 0 ? Number(r.w) : 0, h = Number(r.h) > 0 ? Number(r.h) : 0;
  let dims = w && h ? w + " × " + h : "";
  if (video && Number(r.duration) > 0) dims += (dims ? " · " : "") + Math.round(Number(r.duration)) + "s";
  return {
    tag: rowTag(r),
    time: fmtClock(Number(r.ts) || 0),
    model: modelName || modelDisplay(r),
    dims,
    prompt: String(r.prompt || "").replace(/\s+/g, " ").trim(),
    cost: costText(r.paid_credit, r.state),
    costColor: costColor(r.paid_credit, r.state, "tip"),
  };
}

/* ---- pages ------------------------------------------------------------------------- */

const byDateDesc = (a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0);

// Append a page (older days -- or a refresh of days already loaded, whose rows then WIN),
// keep newest-first, never duplicate a date. The paging cursor (next_before / has_more /
// older_days) follows whichever page reaches furthest back.
export function mergeHistoryPages(prev, page) {
  if (!page) return prev || null;
  const map = new Map();
  ((prev && prev.days) || []).forEach((d) => map.set(d.date, d));
  (page.days || []).forEach((d) => map.set(d.date, d));
  const days = Array.from(map.values()).sort(byDateDesc);
  const oldest = (p) => { const ds = (p && p.days) || []; return ds.length ? ds[ds.length - 1].date : null; };
  const po = oldest(prev), no = oldest(page);
  const cursorFrom = (!prev || po === null || (no !== null && no <= po)) ? page : prev;
  return {
    tz: page.tz !== undefined ? page.tz : (prev ? prev.tz : undefined),
    days,
    next_before: cursorFrom.next_before || null,
    has_more: !!cursorFrom.has_more,
    older_days: Number(cursorFrom.older_days) || 0,
  };
}

// DC 3524: 'Load N older days ⌄' / 'Loaded through <oldest loaded day>'; 'Loading…' while a
// page is in flight.
export function olderLabel(page, loading, todayStr) {
  if (loading) return "Loading…";
  if (!page) return "";
  if (page.has_more) return "Load " + (Number(page.older_days) || 0) + " older days ⌄";
  const ds = page.days || [];
  const oldest = ds.length ? ds[ds.length - 1].date : null;
  return oldest ? "Loaded through " + dayLabel(oldest, todayStr) : "";
}

// One day's rows -> render cells. Each row is one cell; a running row with count > 1
// is the batch CLUSTER (DC 2740-2755); cost shows once per task, on its first (newest) row.
export function dayCells(rows) {
  const seenTask = new Set();
  return (rows || []).map((r) => {
    const st = r.state || "done";
    const running = isRunningState(st);
    const count = running ? Math.max(1, Math.min(4, Number(r.count) || 1)) : 1;
    const kind = running ? (count > 1 ? "cluster" : "running") : st === "done" && r.media_id ? "done" : "fail";
    const tid = r.task_id || r.job_id || r.media_id || "";
    const showCost = !seenTask.has(tid);
    seenTask.add(tid);
    const size = kind === "cluster" ? { w: HISTORY_TILE, h: HISTORY_TILE } : tileSize(r.kind, r.w, r.h, HISTORY_TILE);
    return { key: rowKey(r), row: r, kind, count, size, tag: rowTag(r), showCost, video: r.kind === "video" };
  });
}

export function anyRunning(page) {
  return !!(page && (page.days || []).some((d) => (d.rows || []).some((r) => isRunningState(r.state))));
}
