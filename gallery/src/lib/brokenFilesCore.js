/* The Broken files list's rules and words (Session W, the Archive Integrity Handoff, picks W1a ·
   W2a · W3c · W4c · W5a · W6a). Pure, so loom/test/broken-files-core.test.js holds them.

   The server (moonglade_integrity.broken_list, GET /api/integrity/broken) decides each row's
   chip (`kind`), its pill (`state`) and the one fix that applies (`action`); this file turns that
   into what the desktop section and the phone screen draw, and into the confirm's and the end
   toast's sentences. Never the word "corrupt": a cut-short file is "suspect". Nothing here is
   ruby; held and refused states are peach. */

// The chips, in the handoff's order. Lost cuts across the other three.
export const CHIPS = Object.freeze([
  { key: "all", label: "All", phone: "All" },
  { key: "zero", label: "Zero-byte", phone: "Zero-byte" },
  { key: "thumb", label: "Thumbnail", phone: "Thumb" },
  { key: "suspect", label: "Suspect", phone: "Suspect" },
  { key: "lost", label: "Lost", phone: "Lost" },
]);

// Health's problem tiles and the chip each one opens the list at (useHealth.js's labels).
// Missing files has no chip of its own, so its tile opens the list at All.
export const TILE_CHIP = Object.freeze({ "Zero-byte files": "zero", "Missing thumbs": "thumb", "Missing files": "all" });
// ...and the count that says the tile has rows on the list (peach, and a link) at all.
const TILE_COUNT = Object.freeze({ "Zero-byte files": "zero", "Missing thumbs": "thumb", "Missing files": "missing" });

/* The chip a Health tile opens the list at, or null when the list has nothing under it (then
   the tile stays plain: no peach, no link). */
export function tileChip(label, counts) {
  const k = TILE_COUNT[label];
  return k && counts && counts[k] > 0 ? TILE_CHIP[label] : null;
}

// ARCHIVE: the grid's word for a picture PixAI no longer has, with the grid's own tooltip
// (Grid.jsx, Lane C, the owner's ruling 2026-10-02).
export const ARCHIVE_WORD = "ARCHIVE";
export const ARCHIVE_TIP = "Deleted on PixAI. This is the only copy.";

const PROBLEM_WORDS = {
  "missing": "missing",
  "zero-byte": "zero-byte",
  "suspect: truncated": "suspect · ends early",
  "no thumbnail": "thumbnail missing",
  "no poster": "poster missing",
  "zero-byte thumbnail": "thumbnail empty",
};

/* The chips to draw: every chip with a row under it (zero-count chips are hidden), each with
   its count. `phone` takes the phone's shorter labels. */
export function visibleChips(counts, phone) {
  const c = counts || {};
  return CHIPS.filter((ch) => (c[ch.key] || 0) > 0)
    .map((ch) => ({ key: ch.key, label: phone ? ch.phone : ch.label, n: c[ch.key] || 0 }));
}

/* The chip to show: the one picked while it still has rows, else All (a fix run can empty a
   chip under the owner's eyes, and its button is hidden at zero). */
export function chipOrAll(chips, chip) {
  return (chips || []).some((c) => c.key === chip) ? chip : "all";
}

/* Whether a row sits under a chip. */
export function inChip(row, chip) {
  if (!row) return false;
  if (!chip || chip === "all") return true;
  if (chip === "lost") return row.state === "lost";
  return row.kind === chip;
}

/* "#2038…4167": the id's head and tail, mono on screen; a short id is shown whole. */
export function shortId(mid) {
  const s = String(mid || "");
  return "#" + (s.length > 10 ? s.slice(0, 4) + "…" + s.slice(-4) : s);
}

/* A path cut in the MIDDLE to `max` characters, so the folder and the file's own end both stay
   readable ("images/1gi_…8148.webp"). The whole path rides the row's title attribute. */
export function middleEllipsis(path, max) {
  const s = String(path || "");
  const n = Math.max(8, Math.floor(max || 40));
  if (s.length <= n) return s;
  const keep = n - 1;
  const head = Math.ceil(keep / 2);
  return s.slice(0, head) + "…" + s.slice(s.length - (keep - head));
}

/* The row's problem in words: "zero-byte", "suspect · ends early", "thumbnail missing". */
export function problemWords(row) {
  const p = row && row.problem;
  return PROBLEM_WORDS[p] || String(p || "");
}

/* The row's size: "0 B", "1.4 MB", "850 KB"; a missing file whose expected size the catalog
   doesn't know says "size unknown"; a thumbnail row shows none (its report has no file size). */
export function sizeText(row) {
  if (!row || row.kind === "thumb") return "";
  const n = Number(row.size);
  if (row.size === "" || row.size == null || !Number.isFinite(n)) return row.kind === "missing" ? "size unknown" : "";
  if (n === 0) return "0 B";
  if (n < 1024 * 1024) return Math.max(1, Math.round(n / 1024)) + " KB";
  return (Math.round((n / (1024 * 1024)) * 10) / 10) + " MB";
}

/* The pill: {label, tone}. A row that just finished reads ✓ FIXED (emerald) for its 2 s. */
export function pillFor(row, fixed) {
  if (fixed) return { label: "✓ FIXED", tone: "ok" };
  const st = row && row.state;
  if (st === "lost") return { label: "LOST", tone: "lost" };
  if (st === "suspect") return { label: "SUSPECT", tone: "peach" };
  return { label: "RECOVERABLE", tone: "" };
}

/* The row's own action, if one applies right now: "redownload" | "rebuild" | null. READ_ONLY
   takes the re-download away (it is a network write to the archive); a rebuild is local. */
export function rowAction(row, readOnly) {
  const a = row && row.action;
  if (a === "redownload" && readOnly) return null;
  return a === "redownload" || a === "rebuild" ? a : null;
}

export const ACTION_LABEL = Object.freeze({ redownload: "Re-download", rebuild: "Rebuild" });

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/* "2026-10-02" -> "Oct 2". Read by hand, never through Date, so a time zone can't move the day. */
export function fmtDay(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ""));
  if (!m) return "";
  const mi = Number(m[2]) - 1;
  return mi >= 0 && mi < 12 ? MONTHS[mi] + " " + Number(m[3]) : "";
}

/* A LOST row's reason, for a picture PixAI no longer has (W5a). Null for any other row, and for
   one the owner already said "Keep as is" to. The date is the archive-only flag's last rewrite;
   without one the sentence simply has no date. */
export function lostLine(row) {
  if (!row || row.state !== "lost" || !row.archive_only || row.mark) return null;
  const day = fmtDay(row.gone_as_of);
  return "Broken here, and gone from your PixAI history" + (day ? " as of " + day : "")
    + ". There's no copy left to re-download.";
}

/* "12 broken · 1 lost" (the section header and the phone's entry row). */
export function headerSummary(doc) {
  const b = (doc && doc.broken) || 0;
  const l = (doc && doc.lost) || 0;
  return l ? b + " broken · " + l + " lost" : b + " broken";
}

/* The phone's "Broken files ›" row: "12 · 1 lost ›". */
export function entrySummary(doc) {
  const b = (doc && doc.broken) || 0;
  const l = (doc && doc.lost) || 0;
  return (l ? b + " · " + l + " lost" : String(b)) + " ›";
}

/* The Control Panel check row's link: "12 broken · Review ▸", or the lost count when every row
   is lost. "" when the last check found nothing. */
export function reviewLabel(doc) {
  const all = (doc && doc.counts && doc.counts.all) || 0;
  if (!all) return "";
  const b = doc.broken || 0;
  return (b ? b + " broken" : (doc.lost || 0) + " lost") + " · Review ▸";
}

/* What "Fix all recoverable" would do with the rows as they stand: zero-byte, suspect and
   thumbnail rows that are not LOST and not archive-only, minus anything already fixed. READ_ONLY
   leaves only the rebuilds. `bytes` scales the server's estimate to the re-downloads counted. */
export function fixPlan(doc, readOnly, done) {
  const gone = done || {};
  const rows = (doc && doc.rows) || [];
  const fixable = rows.filter((r) => r.action && !r.archive_only && r.state !== "lost"
    && !gone[r.media_id]);
  const redownload = readOnly ? [] : fixable.filter((r) => r.action === "redownload").map((r) => r.media_id);
  const rebuild = fixable.filter((r) => r.action === "rebuild").map((r) => r.media_id);
  const est = doc && doc.fix ? doc.fix.redownload_bytes : null;
  const base = doc && doc.fix && doc.fix.redownload ? doc.fix.redownload.length : 0;
  const bytes = typeof est === "number" && est > 0 && base > 0 && redownload.length
    ? Math.round(est * (redownload.length / base)) : null;
  const lost = rows.filter((r) => r.state === "lost").length;
  return { redownload, rebuild, ids: redownload.concat(rebuild), total: redownload.length + rebuild.length, lost, bytes };
}

/* "9 MB", "850 KB": the confirm's size, always an estimate (the caller adds the "~"). */
export function fmtSize(n) {
  const b = Number(n);
  if (!Number.isFinite(b) || b <= 0) return "";
  if (b < 1024 * 1024) return Math.max(1, Math.round(b / 1024)) + " KB";
  const mb = b / (1024 * 1024);
  return (mb >= 10 ? Math.round(mb) : Math.round(mb * 10) / 10) + " MB";
}

/* The confirm, line by line (W3c): the total, the re-downloads with their size, the local
   rebuilds, the lost files left alone, and "Nothing is deleted." `metered` adds Data saver's
   line. {title, lines, go}. */
export function confirmLines(plan, metered) {
  const p = plan || { redownload: [], rebuild: [], total: 0, lost: 0, bytes: null };
  const n = p.total;
  const size = fmtSize(p.bytes);
  const parts = [];
  const r = p.redownload.length;
  const t = p.rebuild.length;
  if (r) parts.push(r + " re-download" + (r === 1 ? "" : "s") + " from PixAI" + (size ? " (~" + size + ")" : ""));
  if (t) parts.push(t + " thumbnail" + (t === 1 ? "" : "s") + " rebuilt here");
  const lines = [];
  if (parts.length) lines.push(parts.join(" · ") + ".");
  const kept = p.lost ? (p.lost === 1 ? "1 lost file is left as is. " : p.lost + " lost files are left as is. ") : "";
  lines.push(kept + "Nothing is deleted.");
  if (metered && r) lines.push((size ? "~" + size + ". " : "") + "You're on a metered connection.");
  return { title: "Fix " + n + " file" + (n === 1 ? "" : "s") + "?", lines, go: "Fix " + n };
}

/* The end toast (W4c): "Fixed 11 of 12. 1 couldn't be re-downloaded." Failures are counted by
   what was being tried. */
export function endToast(status) {
  const st = status || {};
  const res = st.results || [];
  const fixed = res.filter((x) => x.ok).length;
  const failed = res.filter((x) => !x.ok);
  const redl = failed.filter((x) => x.action === "redownload").length;
  const reb = failed.filter((x) => x.action === "rebuild").length;
  const other = failed.length - redl - reb;
  let s = "Fixed " + fixed + " of " + (st.total || res.length) + ".";
  if (redl) s += " " + redl + " couldn't be re-downloaded.";
  if (reb) s += " " + reb + " thumbnail" + (reb === 1 ? "" : "s") + " couldn't be rebuilt.";
  if (other) s += " " + other + " couldn't be fixed.";
  if (st.stopped) s += " Stopped.";
  return s;
}

/* The active row's problem line while it downloads: "re-downloading… 1.8 / 3.0 MB", with both
   sides in the unit the total reads in. Without a total there is no fraction to show. */
export function bytesLine(cur) {
  const n = Number((cur && cur.bytes) || 0);
  const t = Number((cur && cur.expect) || 0);
  if (!(t > 0)) return n > 0 ? "re-downloading… " + fmtSize(n) : "re-downloading…";
  const mb = t >= 1024 * 1024;
  const unit = mb ? 1024 * 1024 : 1024;
  const f = (x) => (mb ? (Math.round((x / unit) * 10) / 10).toFixed(1) : String(Math.round(x / unit)));
  return "re-downloading… " + f(Math.min(n, t)) + " / " + f(t) + (mb ? " MB" : " KB");
}

/* The byte bar's fraction (a TRUE one: bytes of a known total), or null. */
export function byteFraction(cur) {
  const n = Number((cur && cur.bytes) || 0);
  const t = Number((cur && cur.expect) || 0);
  return t > 0 ? Math.min(1, Math.max(0, n / t)) : null;
}

/* "5 / 12 fixed" for the header while a run is going (done counts every row that finished). */
export function runHeader(status) {
  const st = status || {};
  return (st.done || 0) + " / " + (st.total || 0) + " fixed";
}

/* The rows to draw under a chip: the server's order, minus rows that finished more than 2 s ago
   (`hidden`), which have left the list. */
export function rowsFor(doc, chip, hidden) {
  const h = hidden || {};
  return ((doc && doc.rows) || []).filter((r) => inChip(r, chip) && !h[r.media_id]);
}
