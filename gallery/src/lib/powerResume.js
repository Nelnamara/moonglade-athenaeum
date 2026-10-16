/* Picking the Stop / Restart reconnect watch back up after the Control Panel remounts (#84).

   After Stop or Restart the panel polls /api/ping until the server has gone (and, for a restart,
   come back). That watch lived only in the mounted hook, so a panel closed and reopened -- or a page
   that remounted it -- mid-wait showed an idle panel with live buttons, as if nothing had happened.

   Two signals bring it back, because the wait has two halves:

     1. The SERVER's marker. /api/panel/status carries `power` ("stop" | "restart" | "") from the
        moment the exit is scheduled until the process is gone (moonglade/gallery.py,
        _power_in_progress). A panel that mounts in that window reads it.
     2. This browser's own note. Once the process HAS gone the server cannot answer anything, so a
        panel that mounts then gets a network error from the very read that would have carried the
        marker. The click leaves a short-lived note in sessionStorage (this tab only, gone with it) and
        that error plus a fresh note means "the server is down because we asked it to be".

   The note is only ever a companion to the server's marker: it is trusted only when the status read
   FAILED, never over a server that answers, and it expires, so a stale one cannot start a watch long
   after the fact. Storage can be blocked (private windows) -- every access is wrapped, and without it
   the server's marker alone still works. */

export const POWER_NOTE_KEY = "mg_power_note";
export const POWER_NOTE_TTL_MS = 3 * 60 * 1000;

const MODES = ["stop", "restart"];

function store() {
  try { return typeof sessionStorage === "undefined" ? null : sessionStorage; } catch { return null; }
}

/* Leave the note: a Stop or Restart was just sent from this tab. */
export function notePower(mode, now = Date.now()) {
  if (!MODES.includes(mode)) return;
  const s = store();
  if (!s) return;
  try { s.setItem(POWER_NOTE_KEY, JSON.stringify({ mode, at: now })); } catch { /* storage blocked: the server marker still works */ }
}

export function clearPowerNote() {
  const s = store();
  if (!s) return;
  try { s.removeItem(POWER_NOTE_KEY); } catch { /* nothing to clear */ }
}

/* The fresh note's mode ("stop" | "restart"), else "". An expired or unreadable note reads as none. */
export function readPowerNote(now = Date.now()) {
  const s = store();
  if (!s) return "";
  try {
    const n = JSON.parse(s.getItem(POWER_NOTE_KEY) || "null");
    if (!n || !MODES.includes(n.mode)) return "";
    const age = now - Number(n.at);
    return age >= 0 && age <= POWER_NOTE_TTL_MS ? n.mode : "";
  } catch {
    return "";
  }
}

/* Which watch (if any) a freshly mounted panel should resume, from its /api/panel/status read.
     the server names one                         -> that one
     the read dropped (the server is not answering) -> the fresh note's mode
     the server answered with nothing in progress  -> none (and the note is stale: the caller clears it)
   `status` is the parsed answer; apiGet never throws, so a failed read arrives as {error}. */
export function powerToResume(status, noteMode) {
  if (status && MODES.includes(status.power)) return status.power;
  // Only a dropped connection says "down" (api.js words it "network error: ..."); a 401 or a 500 is a
  // server that IS answering, and the note must not start a watch against it.
  if (status && /^network error/i.test(String(status.error || "")) && MODES.includes(noteMode)) return noteMode;
  return "";
}
