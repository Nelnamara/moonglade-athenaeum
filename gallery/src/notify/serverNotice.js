/* notify/serverNotice.js -- a sentence the SERVER asks every open tab to say once.

   The one user today (3.20): things outside the app that still name its old files -- a
   scheduled task, Claude's Moonglade tools, a shortcut (moonglade/outside.py). The server
   finds them when it starts and asks a tab on its own machine to say so, with one button,
   Fix them, which asks the server to rewrite them and then says what it did. The words are
   the server's (moonglade/gallery.py's server_notice() and /api/outside/fix); this file only
   decides when to show them, and runs the button.

   It rides the /api/jobs poll (jobsStore.js), the one server-truth channel every open tab
   already runs, and shows the existing corner toast, with the toast's existing one-button
   `action` -- no new surface.

   ONCE PER SERVER START. The notice carries a key that is new each time the server starts.
   The key last shown is written down (localStorage, with a memory copy for a browser that
   blocks it), so a reload, a second tab or the next poll says nothing more -- and the next
   server start, if something is still unfixed, says it again. Sticky: it asks for a choice,
   and must not fade before it is read. */

import { apiPost } from "../api.js";
import { show as toastShow } from "./toastStore.js";

const SEEN_KEY = "mg_server_notice";
let seenHere = "";                 // the memory copy, for a browser that blocks storage

function lastShown() {
  try { return localStorage.getItem(SEEN_KEY) || seenHere; } catch { return seenHere; }
}

function markShown(key) {
  seenHere = key;
  try { localStorage.setItem(SEEN_KEY, key); } catch { /* blocked: memory only */ }
}

/* The button: the server rewrites what it found and answers {kind, title, msg}. A refusal
   (an expired session, a fix already running) or no answer is said as it came. Returns the
   promise, for the tests. */
export function runFix(fix) {
  return apiPost("/api/outside/fix", { csrf: String((fix && fix.csrf) || "") }).then((d) => {
    if (!d || d.error) {
      toastShow({ kind: "err", sticky: true, title: "Couldn't fix them.",
                  msg: String((d && d.error) || "The app didn't answer.") });
      return d;
    }
    const ok = d.kind === "ok";
    toastShow({ kind: ok ? "ok" : "err", sticky: !ok,
                title: String(d.title || ""), msg: String(d.msg || "") });
    return d;
  });
}

/* Hand it the poll's `notice` field: {key, title, msg, fix?: {label, csrf}}, or null when
   the server has nothing to say. Returns true when it put a toast up. */
export function noteServerNotice(notice) {
  if (!notice || !notice.key || (!notice.title && !notice.msg)) return false;
  const key = String(notice.key);
  if (lastShown() === key) return false;
  markShown(key);
  const fix = notice.fix && notice.fix.label ? notice.fix : null;
  toastShow({
    kind: "", sticky: true, title: String(notice.title || ""), msg: String(notice.msg || ""),
    action: fix ? { label: String(fix.label), run: () => { runFix(fix); } } : undefined,
  });
  return true;
}
