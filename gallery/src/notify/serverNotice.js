/* notify/serverNotice.js -- a sentence the SERVER asks every open tab to say once.

   The one user today (3.20, "the move"): a server started by a launcher that was already
   running when the install updated into the moonglade/ folder. That old launcher still
   starts the server through the stand-in it left behind, and the server asks the person to
   stop it once and start it again from its shortcut, which starts the new launcher. The words are the
   server's (moonglade/gallery.py's server_notice()); this file only decides when to show them.

   It rides the /api/jobs poll (jobsStore.js), the one server-truth channel every open tab
   already runs, and shows the existing corner toast -- no new surface.

   ONCE PER SERVER START. The notice carries a key that is new each time the server starts.
   The key last shown is written down (localStorage, with a memory copy for a browser that
   blocks it), so a reload, a second tab or the next poll says nothing more -- and the next
   server start, still through the old launcher, says it again. Sticky: it is an instruction,
   not news, and must not fade before it is read. */

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

/* Hand it the poll's `notice` field: {key, title, msg}, or null when the server has
   nothing to say. Returns true when it put a toast up. */
export function noteServerNotice(notice) {
  if (!notice || !notice.key || (!notice.title && !notice.msg)) return false;
  const key = String(notice.key);
  if (lastShown() === key) return false;
  markShown(key);
  toastShow({ kind: "", sticky: true, title: String(notice.title || ""), msg: String(notice.msg || "") });
  return true;
}
