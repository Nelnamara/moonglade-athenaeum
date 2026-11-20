/* THE CLIENT HALF OF THE UNCLEAR-SEND HOLD (3.21.2; DESIGN_3.22 "Live in master today" L1,
   2.12). A single send whose answer cannot show whether PixAI made the task -- the server's
   {unclear: true, state: "may_have_started"}, or no readable answer at all -- says so in plain
   words instead of an ordinary error, and the SAME send (route + the request as built) is held
   here for SEND_HOLD_MS: pressing it again shows the hold sentence and posts nothing. The
   server keeps its own record of the same send (gallery.py _send_claim), so a second tab, a
   stale bundle or a hand-rolled POST is held there too; this half only keeps the button from
   inviting the second paid tap.

   Pure (no DOM, no fetch): every surface that sends -- the gallery's submitTask, the Loom's
   Image / Edit / Reference / Fix tabs -- shares this one copy of the words and the clock. */

export const SEND_HOLD_MS = 60000;

export const UNCLEAR_SEND_MSG =
  "PixAI may have started this. It was not sent again; check the Activity tray (or pixai.art) before sending it again.";

export const HELD_SEND_MSG =
  "The last one may still be starting, so this was not sent. Check the Activity tray (or pixai.art) before sending it again.";

/* The words for an unclear (or held) answer. PixAI's own reason, when the server has one
   (`detail`: an NSFW_DETECTED or INPUT_IMAGE_TOO_LARGE that does not prove nothing was made, an
   expired sign-in's 401), follows the sentence, so the owner can see why without a log. */
export function unclearText(d) {
  if (d && d.held) return d.error || HELD_SEND_MSG;
  const detail = d && typeof d.detail === "string" ? d.detail.trim() : "";
  return detail ? UNCLEAR_SEND_MSG + " PixAI's answer: " + detail : UNCLEAR_SEND_MSG;
}

/* True for a server answer that says the send may have started. */
export function isUnclearAnswer(d) {
  return !!d && (d.unclear === true || d.state === "may_have_started");
}

/* The key one send is held under: its route and the request as the surface built it (before
   the quote flag and the Loom's target are added), with object keys in a fixed order. */
export function sendKey(route, body) {
  const norm = (v) => {
    if (Array.isArray(v)) return v.map(norm);
    if (v && typeof v === "object") {
      const out = {};
      for (const k of Object.keys(v).sort()) out[k] = norm(v[k]);
      return out;
    }
    return v;
  };
  let blob;
  try { blob = JSON.stringify(norm(body)); } catch { blob = String(body); }
  return String(route) + " " + blob;
}

/* A hold table. `now` is injectable for tests. */
export function makeSendHolds(now = () => Date.now(), ms = SEND_HOLD_MS) {
  const until = new Map();
  return {
    hold(key) { until.set(key, now() + ms); },
    held(key) {
      const t = until.get(key);
      if (t == null) return false;
      if (now() >= t) { until.delete(key); return false; }
      return true;
    },
    release(key) { until.delete(key); },
  };
}

/* The one table every surface in this page shares. */
export const sendHolds = makeSendHolds();
