/* fonts -- the System + Hero type pairing, one per device.

   PIXEL SOURCE: moonglade-internal/design/identity/"Identity Chrome Handoff.dc.html", C1.

   WHAT IT CONTROLS. Two CSS variables and nothing else:
     --font-hero    the italic-serif display voice: page titles, modal heads, the mark's
                    own lettering, every place the app already said "Georgia".
     --font-system  everything else -- body text, controls, labels.
   Mono kickers are deliberately NOT in this scheme: they stay `ui-monospace, Menlo,
   monospace` wherever they are written, because the whole point of a kicker is that it
   reads as machine type no matter what the rest of the page is wearing.

   NO FONT FILES. Every stack below is made of faces that are already on the machine, and
   each pairing IS its own fallback stack -- nothing is downloaded, nothing is served, and
   a face a given OS does not have degrades inside its own list rather than falling off a
   cliff to the browser default. That is the whole reason the set is stacks rather than
   webfonts.

   THE SET IS PROVISIONAL, THE MECHANICS ARE NOT (owner note on the handoff: 1a was picked
   as "a start", neither option loved). PAIRINGS below is data: swapping, adding or
   removing an entry needs no change to the storage shape, the pre-paint script, the CSS
   variables or the picker. Only the DEFAULT id is special, and only because it must stay
   byte-identical to what the app shipped before this existed.

   HOUSE DEFAULT IS THE APP'S OWN STACKS, not the handoff's shorthand for them. The comp
   labels pairing 1 "Georgia + UI sans"; what actually ships today is `--serif` (Georgia,
   "Times New Roman", serif) over body's own `system-ui, -apple-system, "Segoe UI",
   sans-serif`. Writing the comp's slightly different sans list here would have quietly
   restyled every install that never touches this picker, which is the one thing a
   "default" must never do. The other four pairings are the handoff's stacks verbatim.

   WHY BROWSER STORAGE, and why a pre-paint script: same two answers the skin already
   gives. It is a property of the DEVICE (localStorage, no round trip, see
   lib/blurPref.js's own note), and it PAINTS THE PAGE -- so it has to be applied in
   <head> before first paint or the whole app renders in the wrong face and then jumps.
   moonglade_gallery.py's _PREPAINT_BOOT_JS does that, alongside the data-skin line it has
   always carried. This module is the reconcile pass that runs afterwards. */

export const FONTS_KEY = "fonts";

/* [id, name, sub, hero stack, system stack] -- name/sub are the picker's own two lines,
   verbatim from the handoff's PAIRS table. */
export const PAIRINGS = [
  {
    id: "house",
    name: "House default",
    sub: "Georgia + UI sans",
    hero: 'Georgia, "Times New Roman", serif',
    system: 'system-ui, -apple-system, "Segoe UI", sans-serif',
  },
  {
    id: "bookish",
    name: "Bookish",
    sub: "Palatino + UI sans",
    hero: '"Palatino Linotype", Palatino, serif',
    system: "ui-sans-serif, system-ui, sans-serif",
  },
  {
    id: "engraved",
    name: "Engraved",
    sub: "Baskerville + Gill alt",
    hero: 'Baskerville, "Baskerville Old Face", serif',
    system: '"Gill Sans", "Trebuchet MS", sans-serif',
  },
  {
    id: "modernist",
    name: "Modernist",
    sub: "Didot + Helvetica",
    hero: 'Didot, "Bodoni MT", serif',
    system: "Helvetica, Arial, sans-serif",
  },
  {
    id: "scriptorium",
    name: "Scriptorium",
    sub: "Book Antiqua + Verdana",
    hero: '"Book Antiqua", Palatino, serif',
    system: "Verdana, Geneva, sans-serif",
  },
];

export const DEFAULT_PAIRING_ID = "house";

export function pairingById(id) {
  return PAIRINGS.find((p) => p.id === id) || null;
}

/** The stored pick, as a pairing from the CURRENT table -- or null.
    Storage can throw outright (private mode, site data blocked), and the honest answer
    there is "no preference", which means the house default. Same try/catch discipline as
    lib/blurPref.js and notify/jobsStore.js. */
export function readPairing() {
  let raw = null;
  try { raw = localStorage.getItem(FONTS_KEY); } catch { return null; }
  if (!raw) return null;
  let stored = null;
  try { stored = JSON.parse(raw); } catch { return null; }
  if (!stored || typeof stored !== "object") return null;
  // The TABLE is authoritative, not the stored copy: an id that no longer exists (the
  // provisional set was swapped) falls back to the default rather than pinning a browser
  // to a pairing this build no longer offers.
  return pairingById(stored.id);
}

/** Put a pairing's two stacks on a document root as inline custom properties -- the same
    place and the same precedence the pre-paint script uses, so the reconcile below can
    only ever agree with it or correct it, never fight it. Passing null clears both, which
    hands the page back to the :root defaults in styles.css (= the house pairing). */
export function applyPairing(root, pairing) {
  const el = root || (typeof document !== "undefined" ? document.documentElement : null);
  if (!el || !el.style) return;
  if (!pairing) {
    el.style.removeProperty("--font-hero");
    el.style.removeProperty("--font-system");
    return;
  }
  el.style.setProperty("--font-hero", pairing.hero);
  el.style.setProperty("--font-system", pairing.system);
}

/** Write the pick AND apply it. The house default is stored as an explicit record rather
    than a removed key so a reader can tell "chose the house face" from "never chose". */
export function setPairing(id, root) {
  const p = pairingById(id) || pairingById(DEFAULT_PAIRING_ID);
  try {
    localStorage.setItem(FONTS_KEY, JSON.stringify({ id: p.id, hero: p.hero, system: p.system }));
  } catch { /* private mode -- the applied value below still holds for this session */ }
  applyPairing(root, p);
  return p;
}

/** Read storage and apply, in one call: main.jsx's boot pass. It is a RECONCILE, not the
    first application -- the served shells already painted from the same key in <head>.
    It exists for the two cases that script cannot cover: the dev shell's own copy drifting,
    and a stored pairing whose stacks this build has since changed (the id still matches,
    so the table's current stacks win). Returns the pairing in force. */
export function syncPairing(root) {
  const p = readPairing() || pairingById(DEFAULT_PAIRING_ID);
  applyPairing(root, p);
  return p;
}
