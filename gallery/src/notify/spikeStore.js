/* notify/spikeStore.js -- THE BLOW-UP NOTE.

   The owner's addition to the community-surface scope, 2026-09-06, verbatim: "if something
   BLOWS up can there be a trigger or metric for that?"

   Answered as one corner note, through the standard toastStore idiom, once per view sweep.
   Nothing else: no feed, no counter that ticks in the chrome, no second poll. The rule that
   decides what counts as a blow-up is SERVER-SIDE and testable in isolation
   (moonglade_gallery.py's views_spike / published_spikes); this module only carries the
   answer to a person.

   THE LIBRARY STANDS STILL (owner, 2026-09-05) applies here in full. This announces and
   does nothing else -- it never opens an overlay, never navigates, never restacks a grid,
   never scrolls. It is the same shape as notify/updateStore.js's release note and its
   receipt: something happened while you were away, and here is a sentence about it.

   ONCE PER SWEEP, not once per boot and not once per mount. Spikes only change when
   --sync-artworks runs, so the sweep's own timestamp (`views_at`) is the identity of the
   news. A reload, a second tab, or ten overlay opens between two sweeps are all the same
   piece of news and get one note between them.

   A MODULE SINGLETON outside any React lifecycle, and MEMORY FIRST before storage, for the
   reason updateStore.js learned the hard way: a browser with localStorage blocked throws on
   both getItem and setItem, and a guarded read that swallows the throw answers "" -- which
   reads as "never announced" and re-announces forever. The in-memory mark is the layer that
   cannot fail; storage is only what carries the promise across a reload. */

import { show as toastShow } from "./toastStore.js";
import { apiGet } from "../api.js";
// From the STORE, not hooks/swrCache.js: that module imports React for its hook, and this
// one runs where React may not be installed (the Loom's node test job installs only loom/).
// swrCache re-exports this same `put`, so the cache the overlays read is the same cache.
import { put } from "../hooks/swrStore.js";

const SEEN_KEY = "mg_spike_announced";

// The sweep this BROWSER has already been told about. See the header: memory is
// authoritative, storage is the cross-reload layer.
let memSeen = "";
let asked = false;                 // one fetch per page life, whatever else calls in

function readStored() {
  try { return localStorage.getItem(SEEN_KEY) || ""; } catch { return ""; }
}

function markSeen(at) {
  memSeen = at;
  try { localStorage.setItem(SEEN_KEY, at); } catch { /* private mode: memory carries it */ }
}

/* Cross-tab, exactly as updateStore.js does it: the `storage` event is how a browser tells
   its other tabs what one of them just wrote, so a sibling that already announced this
   sweep stops this one from repeating it. Sweeps are identified by timestamp and only ever
   move forward, so a plain string compare is the whole comparison. */
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
  window.addEventListener("storage", (e) => {
    if (!e || e.key !== SEEN_KEY) return;
    const v = String(e.newValue || "");
    if (v && v > memSeen) memSeen = v;
  });
}

/* The sentence itself. One work by name; the rest counted, never listed -- a note that
   names six things is a feed with rounded corners, which is the thing this must not become. */
export function spikeMessage(spikes) {
  const list = spikes || [];
  if (!list.length) return null;
  const top = list[0];
  const name = (top.title || "").trim() || "One of your works";
  const others = list.length - 1;
  /* A BLOW-UP FROM NOTHING has no usual pace to be a multiple of (owner's call,
     2026-09-06: a previous reading of 0 counts as a spike once the gain clears the
     floor), so views_spike sends `multiple: null` and this says it in words. Printing
     the field regardless would read "about null× its usual pace" on the single most
     dramatic case the rule has. */
  const pace = top.multiple == null
    ? "up from nothing"
    : "about " + top.multiple + "× its usual pace";
  return {
    title: "◈ " + name + " is taking off",
    msg: "+" + Number(top.gained).toLocaleString() + " views in the last "
      + top.window_hours + "h — " + pace
      + (others ? " (and " + others + " more picking up)" : "") + ".",
  };
}

/* Hand it a /api/your-art payload. Returns true when it actually announced.

   Deliberately silent, never optimistic, in every ambiguous case: no sweep timestamp (a
   library that has never been swept), no spikes, or a sweep this browser has already been
   told about. The FIRST sweep of a fresh library announces nothing by construction -- the
   server-side rule has no previous reading to compare against, so it returns no spikes at
   all. That is the no-announce baseline case, and it is a property of the rule rather than
   a special case here. */
export function note(payload) {
  const d = payload || {};
  const at = String(d.views_at || "");
  const spikes = d.spikes || [];
  if (!at || !spikes.length) return false;
  if (at <= memSeen) return false;
  const stored = readStored();
  if (stored && at <= stored) { memSeen = stored; return false; }
  const words = spikeMessage(spikes);
  if (!words) return false;
  markSeen(at);
  toastShow({
    kind: "ok",
    sticky: true,           // a sweep can finish with nobody at the keyboard; see updateStore
    icon: "◈",
    title: words.title,
    msg: words.msg,
  });
  return true;
}

/* Boot entry, called once from installNotify(). Reads the panel's own route -- which since
   2026-09-06 is a pure local catalog read with no PixAI call behind it, so this costs a
   SQLite query and nothing on the network -- and seeds the shared read cache with the
   answer, so opening My Art afterwards paints from it instead of asking again. */
export function checkSpikes() {
  if (asked) return Promise.resolve(false);
  asked = true;
  return apiGet("/api/your-art").then((d) => {
    if (!d || d.error) return false;
    try { put("/api/your-art", d); } catch { /* cache is a convenience, never a dependency */ }
    return note(d);
  }).catch(() => false);
}
