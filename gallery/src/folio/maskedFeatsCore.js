/* THE MASKED-FEATS LOGIC -- pure, importless, so loom/test/masked-feats-core.test.js can pin it
   with no renderer, DOM or fetch (Session G, design/notes/masked-feats/NOTES.md).

   What the Folio knows about a feat it has not been shown is one riddle and one silhouette
   (`data.feats.masked`), and nothing else. Everything below works on feats the server has
   already listed as EARNED:

     - which earned feats are new to this account (the per-account "seen" record, kept in the
       wave-1 account store, key SEEN_KEY);
     - what order the earned cards stand in;
     - what the glitch reveal looks like at any instant (revealFrame -- a pure function of
       elapsed milliseconds, so the timings in NOTES decision 3 are asserted, not eyeballed);
     - the words for the counts, which never say how many remain.

   SEEN_KEY's value is a list of feat ids the account has been SHOWN as earned. Its key is
   fixed and says nothing about any feat, and the client only ever names an id the server
   already sent as earned -- no key is ever built from, or checked against, a feat's identity. */

export const SEEN_KEY = "folio.seen";

/* NOTES decision 3, in milliseconds from the moment the earned card is on screen:
     0    veil at rest (the card's well shows the veil art)             HOLD
     300  split: ruby + --loomc copies, +-4/-+2 px, 60 ms steps          STEP x STEPS
     540  snap: the badge takes the well; ruby glow + gunmetal band      SNAP
     700  the "NEWLY FOUND" ribbon                                       RIBBON
     900  the next veil fades in last (.42 s), or the gold line          VEIL, VEIL_FADE
   The move into date order (.42 s) is MOVE; the card is the newest, so it is already home. */
export const REVEAL = { HOLD: 300, STEP: 60, STEPS: 4, SNAP: 540, RIBBON: 700, VEIL: 900, VEIL_FADE: 420, MOVE: 420 };
export const REVEAL_END = REVEAL.VEIL + REVEAL.VEIL_FADE;

/* The day the reveal shipped. An account with NO stored record cannot tell an earn from before it
   (found long ago, already known) from one after it (found and not yet shown), so a feat counts
   as new only if it was earned on or after this date. It bounds the worst case: a feat found
   since, and never viewed in the Folio, plays its reveal once when the record is first written. */
export const SEEN_EPOCH = "2026-09-29";

/** The ids in a stored seen list, or null when nothing has ever been stored under the key. */
export function readSeen(value) {
  if (!Array.isArray(value)) return null;
  return value.filter((x) => typeof x === "string" && x);
}

/* THE EARNED FEATS THIS ACCOUNT HAS NOT YET BEEN SHOWN.
   With a stored list it is exact: every earned feat not on it. With NO stored list (an
   account that has never viewed a reveal -- which includes everyone who had feats before this
   shipped) the record cannot tell an old earn from a new one, so a feat counts as new only if
   it was earned on or after SEEN_EPOCH. Anything earned earlier is taken as already known and
   is not replayed as a "newly found" ribbon on a card the account found last month. */
export function unseenFeatIds({ feats, earnedAt, seen, since = SEEN_EPOCH }) {
  const stored = readSeen(seen);
  const dates = earnedAt || {};
  const out = [];
  for (const a of feats || []) {
    if (!a || !a.earned || !a.id) continue;
    if (stored) {
      if (!stored.includes(a.id)) out.push(a.id);
    } else if (dates[a.id] && dates[a.id] >= since) {
      out.push(a.id);
    }
  }
  return out;
}

/** The seen list to store once these earned feats have been shown: the old list (if any) plus
    every earned feat currently on the page, de-duplicated, in a stable order. Marking them all
    is what keeps a first write from leaving older feats "new" the next time. */
export function nextSeen(seen, feats) {
  const out = readSeen(seen) || [];
  for (const a of feats || []) {
    if (a && a.earned && a.id && !out.includes(a.id)) out.push(a.id);
  }
  return out;
}

/** Earned feats in the order they were found (oldest first; ties and undated ones keep the
    roster's order), then any feat that is listed but not yet earned, in its own order. */
export function orderFeats(feats, earnedAt) {
  const dates = earnedAt || {};
  const tagged = (feats || []).map((a, i) => ({ a, i }));
  const earned = tagged.filter((t) => t.a.earned)
    .sort((x, y) => (dates[x.a.id] || "").localeCompare(dates[y.a.id] || "") || x.i - y.i);
  return earned.concat(tagged.filter((t) => !t.a.earned)).map((t) => t.a);
}

/** The Feats header's count: what has been found, never out of anything. */
export function foundText(found, allFound) {
  return (found || 0) + " found" + (allFound ? " · all" : "");
}

/** One Feats bucket's count where the Folio draws "earned/total" for the other buckets. */
export function featCountText(earned) {
  return (earned || 0) + " found";
}

/* The only shape a mask URL may have: the server's own route and an opaque hex token. Anything
   else is not drawn, so a value that is not the server's cannot steer a CSS url(). */
export const MASK_URL_RE = /^\/feat-mask\/[0-9a-f]{32}\.png$/;

/** What the veil card may show, given the payload's `feats` object and what the reader is
    doing. `query` is the Folio's search text: the veil is never a search result. */
export function veilState(feats, { query = "", unleashed = false } = {}) {
  const f = feats && typeof feats === "object" ? feats : {};
  const m = f.masked && typeof f.masked === "object" ? f.masked : null;
  const allFound = f.all_found === true && !m;
  const searching = !!String(query || "").trim();
  const riddle = m ? ((unleashed && m.riddle_nsfw) ? m.riddle_nsfw : m.riddle) : "";
  const show = !!(m && m.riddle && MASK_URL_RE.test(String(m.mask_url || ""))) && !searching;
  return {
    show,
    allFound: allFound && !searching,
    riddle: show ? String(riddle) : "",
    maskUrl: show ? String(m.mask_url) : "",
  };
}

/* THE REVEAL AT ONE INSTANT. `t` is milliseconds since the card came on screen (null or
   negative: not started). `reduced` is prefers-reduced-motion: no split, no jitter -- the
   earned card is at rest with its ribbon and the next veil is already in place.
     art        what fills the well: the veil art until the snap, then the badge
     coverOpacity  how solid the veil art is (it flickers under the split)
     split      null, or {dx, dy} for the ruby copy (the --loomc copy is its mirror)
     glow       the ruby glow and gunmetal band (they arrive with the snap)
     ribbon     the "NEWLY FOUND" ribbon
     veilIn     the next veil (or the gold line) may show; fades in over VEIL_FADE
     done       nothing is left to animate */
export function revealFrame(t, reduced) {
  if (reduced) {
    return { art: "badge", coverOpacity: 0, split: null, glow: true, ribbon: true, veilIn: true, done: true };
  }
  const at = t == null || t < 0 ? 0 : t;
  const splitting = at >= REVEAL.HOLD && at < REVEAL.SNAP;
  let split = null;
  let coverOpacity = at < REVEAL.SNAP ? 1 : 0;
  if (splitting) {
    const k = Math.floor((at - REVEAL.HOLD) / REVEAL.STEP);
    const j = (k % 3) - 1;
    split = { dx: 4 * j, dy: -2 * j };
    coverOpacity = k % 2 ? 0.55 : 1;
  }
  return {
    art: at < REVEAL.SNAP ? "veil" : "badge",
    coverOpacity,
    split,
    glow: at >= REVEAL.SNAP,
    ribbon: at >= REVEAL.RIBBON,
    veilIn: at >= REVEAL.VEIL,
    done: at >= REVEAL_END,
  };
}
