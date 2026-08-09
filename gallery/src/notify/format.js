/* notify/format.js -- the pure formatting helpers of the notify system, ported verbatim from
   static/mg-notify.js (the 2026-08-08 no-vanilla campaign, component 6). Pure functions with no
   DOM/React dependency, exported individually so the loom node-tests can import and run the REAL
   implementations instead of regex-extracting function bodies out of a vanilla file.

   All hand-formatted (no toLocaleString) on purpose: identical output regardless of the browser's
   ICU/locale data, and trivially unit-testable. */

export function ago(ts) {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - (ts || 0)));
  if (s < 60) return "just now";
  if (s < 3600) return Math.floor(s / 60) + "m ago";
  if (s < 86400) return Math.floor(s / 3600) + "h ago";
  return Math.floor(s / 86400) + "d ago";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function pad2(n) { return (n < 10 ? "0" : "") + n; }

// A real clock time ("Time Sent") -- companion to ago()'s relative "3m ago".
export function fmtClock(ts) {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  const h = d.getHours(), ap = h >= 12 ? "PM" : "AM", h12 = h % 12 || 12;
  return MONTHS[d.getMonth()] + " " + d.getDate() + ", " + h12 + ":" + pad2(d.getMinutes()) + " " + ap;
}

// A DURATION, not an "X ago" -- deliberately its own function rather than reusing ago()'s
// bucketing (which would render a 92-minute job as merely "1h ago"). Two units of precision
// throughout, so "time spent" reads as an honest duration ("1h 32m"), not a vague bucket.
export function fmtDuration(s) {
  s = Math.max(0, Math.floor(s || 0));
  if (s < 60) return s + "s";
  if (s < 3600) return Math.floor(s / 60) + "m " + (s % 60) + "s";
  if (s < 86400) return Math.floor(s / 3600) + "h " + Math.floor((s % 3600) / 60) + "m";
  return Math.floor(s / 86400) + "d " + Math.floor((s % 86400) / 3600) + "h";
}

// Where a job came from, in words. `j.type` is an internal enum -- rendered raw it turned 'cli'
// into the non-word "Cli". An unmapped type falls through to its own value rather than vanishing.
export const KIND_LABEL = {
  cli: "Terminal", panel: "Control Panel", generate: "Generate",
  delete: "Delete", import: "Import",
};
export function kindLabel(t) { return KIND_LABEL[t] || t || "Job"; }

// The stored `label` is the COMPLETION wording (written at SUBMIT time), so an in-flight card
// read "Generated" while the thing was still queued (owner report 2026-07-25). Terminal rows keep
// the stored wording; an in-progress row gets the present tense from this table. Anything not in
// it falls through UNCHANGED -- a label this table has never heard of is better shown as-is.
export const LABEL_ING = {
  Generated: "Generating", Edited: "Editing", Rendered: "Rendering",
  Fixed: "Fixing", Upscaled: "Upscaling", Imported: "Importing",
  Uploaded: "Uploading",
};
export function labelFor(j, terminal) {
  const l = j.label || "Generation";
  return terminal ? l : (LABEL_ING[l] || l);
}

// Thousands-grouped by hand (no toLocaleString) -- the Cost row's locale-stable formatter.
export function groupThousands(n) {
  const s = String(Math.round(Math.abs(n)));
  let grp = "", i = 0;
  for (let k = s.length - 1; k >= 0; k--) {
    grp = s.charAt(k) + grp;
    if (++i % 3 === 0 && k > 0) grp = "," + grp;
  }
  return grp;
}
