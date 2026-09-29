import { useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost } from "../api.js";
import { noticeAchievements } from "../notify/ach.js";
import { peek, put } from "./swrCache.js";
import useAccountPrefs, { accountPrefs, accountCsrf } from "./useAccountPrefs.js";
import { takeFolioFocus, takeFolioRow } from "../folio/folioFocus.js";
import { vigilView, togglePin, canPin, PIN_KEY, VIGIL_HEADER_KEY, pinnedId, vigilInHeader } from "../folio/goalCore.js";
import { honorsCardModel } from "../folio/honorsCardCore.js";
import { pokeView, choiceValue } from "../folio/pokeCore.js";
import { UNLEASH_KEY, isUnleashed } from "../folio/unleashPref.js";
import {
  SEEN_KEY, REVEAL, orderFeats, unseenFeatIds, nextSeen, veilState, revealFrame,
} from "../folio/maskedFeatsCore.js";
import {
  progressOf, completionOf, loadSort, saveSort, sortHonors, relicRows,
} from "../folio/completionistCore.js";
import { applySkin } from "./useControlPanel.js";

/* useFolio -- FolioOverlay.jsx's fetch/state/narrator/glitch-reveal/replay
   engine, mechanically lifted out (2026-08-03), same precedent as
   useMyArt.js/useHealth.js/useImport.js/useContests.js this session (see
   useMyArt.js's own header comment for the full "ONE place this state has
   ever lived, refactored to CONSUME rather than duplicate" rationale).
   FolioOverlay.jsx (desktop) is refactored to CONSUME this hook; the new
   mobile Folio screen (FolioMobile.jsx) gets the IDENTICAL data/narrator/
   glitch-reveal/replay engine, not a second fetch of GET /api/achievements
   and not a second, drifting implementation of the 34ms/26-tick scramble.

   Everything below is copied verbatim from FolioOverlay.jsx's own prior
   implementation (git history has the byte-for-byte prior version) --
   nothing here was re-derived or simplified. See that file's own remaining
   header comment for the feature's full narrative background
   (narrator-poke -> real /api/ach-event -> "Triggered" feat -> free
   Unleash toggle -> per-id glitch-reveal shared between a card's inline
   description and the REAL window.Ach.replay() celebration).

   MOUNT-RACE CHECK (explicitly verified, not assumed, per this session's
   own standing rule after finding the bug class twice already): the ONLY
   "handle" this engine holds onto is `replayHandleRef`, the plain object
   window.Ach.replay() returns -- and that object is created and populated
   ENTIRELY inside replayToast(), which only ever runs from a user's click
   on an already-rendered, already-earned card. There is no custom element,
   no DOM ref, and no effect here that depends on a target existing by its
   first run: `mountedRef`'s own effect below touches no DOM at all (it's a
   plain boolean guard for async setState-after-unmount), and the data-fetch
   effect's dead-flag guard is the same pattern useHealth.js/useContests.js/
   useImport.js already use. Nothing in this file has an early-return keyed
   to mount timing rather than to data actually arriving. */

export const BUCKETS = [
  { key: "ladder", label: "Evolution Ladders" },
  { key: "milestone", label: "Milestones" },
  { key: "mastery", label: "Masteries" },
  { key: "feat", label: "Feats of the Athenaeum" },
];

// The Folio renders four sections; the roster carries two extra structural buckets that
// fold into existing sections rather than adding new tabs (owner decision, 2026-08-30):
// meta achievements (the Glories / The Way Is Shut -- feat-tier, no points) render with the
// Feats, and streaks (Seven Candles / Lamplighter) render with the Masteries. displayBucket
// maps a card's raw bucket to the section it belongs to, so the four bucket denominators and
// the three rendered sections all stay consistent. Bucket labels are structural, not roster
// data -- sealing-safe.
export const BUCKET_ALIAS = { meta: "feat", streak: "mastery" };
export const displayBucket = (a) => BUCKET_ALIAS[a.bucket] || a.bucket;

// Rarity/points table (wiki/Folio-of-Honors.md "Rarity and points") scores four
// tiers -- feat is deliberately excluded from every rarity breakdown (it scores
// 0 points by design, "pure bragging-rights flair", achievement_points() in
// moonglade_gallery.py), matching the DC's own RARITY_ORDER.
export const RARITY_ORDER = ["common", "rare", "epic", "legendary"];

// The narrator's rotating lines, verbatim from the DC script's `nelLines` --
// this app's own shipped product copy (the same voice mg-notify.js's roasts
// use), not third-party content. Poke-driven reveal lines stay out of scope
// for this stage. Folio Mobile.dc.html's OWN nelLines is a 4-line SUBSET of
// this exact same 6-line array (its own demo predates the real shared
// constant) -- FolioMobile.jsx uses this full array rather than hand-copying
// the mock's shorter one, one narrator voice, one source of truth, matching
// this file's own established rule for shared product copy.
// (The narrator's poke lines are NOT here: the server keeps the count and chooses each line
// from the sealed pack, and the page only shows what it is told -- see pokeNarrator below and
// folio/pokeCore.js.)

export const NARRATOR_LINES = [
  "Keep going. The Void will not archive itself.",
  "Every relic you skip, I catalog as a grudge.",
  "I've seen better hoards from goblins.",
  "Progress. Or at least the illusion of it.",
  "The archive remembers what you'd rather forget.",
  "Dust doesn't collect itself. Neither do trophies, apparently.",
];

export const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());

export function matchesQuery(a, q) {
  if (!q) return true;
  const hay = ((a.name || "") + " " + (a.desc || "") + " " + (a.tier || "")).toLowerCase();
  return hay.indexOf(q) >= 0;
}

/* ---- Glitch-reveal: verbatim from "Folio of Honors.dc.html"'s own GLYPHS
   constant + folio-glitch-spec.md (copied character-for-character, not
   retyped by hand). Shared by AchCard's inline description and the replay
   toast off the same `reveal[id]` map -- single source of truth per id. ---- */
export const GLYPHS = "▉▊▋▌░▒▓@#%&$*<>/\\|=+×÷¤§øþ";

/* Pure: reveal[id] (if present) always wins over the earned `roast`/locked
   `desc` -- this is what makes a card's body and the replay toast for the
   same id show the identical text as it glitches/settles. */
export function commentary(a, reveal) {
  const rv = reveal && reveal[a.id];
  if (rv) return rv.text;
  if (a.earned) return a.roast || a.desc;
  return a.desc;
}
// Color/font law (folio-glitch-spec.md): mid-scramble -> monospace + red;
// settled on the NSFW line (done, no longer glitching) -> red, still italic.
export function revealMod(a, reveal) {
  const rv = reveal && reveal[a.id];
  if (!rv) return "";
  if (rv.g) return " mgfo-glitch";
  if (rv.done) return " mgfo-settled";
  return "";
}

/* THE LADDER'S FACE (2026-09-04, Identity Chrome handoff C4): the art of the HIGHEST
   EARNED rung, not rung 1's.

   A ten-track badge row that always showed each track's FIRST rung showed the same ten
   pictures on day one and after a year of collecting -- the one place a glance could have
   told you how far up each track you are, and it said nothing. The face is now the rung
   you actually reached, so it upgrades itself the moment a higher one lands and the row
   becomes a record rather than a menu.

   `tiers` arrives sorted by rung (buildViewModel sorts it), so the LAST earned entry is
   the highest -- found by scanning from the end rather than trusting a max(), because a
   roster where two rungs share a threshold must still resolve to one face.

   Pre-earn there is no face to show, so rung 1 stands in DIMMED (grayscale .6 ·
   brightness .6, per the handoff) -- the track is legible, and legibly untouched. `rung`
   is 1-based for the r№ badge; `earned` is what tells a renderer which of the two states
   it is drawing. */
export function ladderFace(tiers) {
  if (!tiers || !tiers.length) return null;
  for (let i = tiers.length - 1; i >= 0; i--) {
    if (tiers[i].earned) {
      return { tier: tiers[i], rung: i + 1, rarity: tiers[i].tier || "common", earned: true };
    }
  }
  return { tier: tiers[0], rung: 1, rarity: tiers[0].tier || "common", earned: false };
}

/* Pure: flat achievements[] + ladders[] (the 10 track defs) + skin/earned_at ->
   the grouped shape the Folio's three tabs actually render from. Kept as one
   small pure function on purpose (per the task brief) so the next stage can
   extend it without re-deriving the grouping logic from render code. */
export function buildViewModel(data) {
  const achievements = data.achievements || [];
  const earnedAt = data.earned_at || {};
  const ladderDefs = data.ladders || [];

  // displayBucket folds meta -> feat and streak -> mastery, so the four sections stay the
  // four sections and their denominators fold the extra buckets in consistently.
  const nonFeat = achievements.filter((a) => displayBucket(a) !== "feat");
  const feats = achievements.filter((a) => displayBucket(a) === "feat");

  // ---- Categories: the right rail's 4 bucket filters + Summary's ledger +
  // Statistics' "by bucket" list all read the same {key,label,earned,total}. ----
  const buckets = BUCKETS.map(({ key, label }) => {
    const rows = achievements.filter((a) => displayBucket(a) === key);
    return { key, label, earned: rows.filter((a) => a.earned).length, total: rows.length };
  });

  // ---- The ten Evolution Ladder tracks, each grouped from the flat array by
  // its real `track` field and sorted by `rung` (ladder-only fields). ----
  const byTrack = {};
  achievements.forEach((a) => {
    if (a.bucket !== "ladder") return;
    (byTrack[a.track] || (byTrack[a.track] = [])).push(a);
  });
  Object.keys(byTrack).forEach((t) => byTrack[t].sort((x, y) => x.rung - y.rung));
  const ladders = ladderDefs
    .map((t) => {
      const tiers = byTrack[t.id] || [];
      return {
        id: t.id, name: t.name, metric: t.metric, tiers,
        face: ladderFace(tiers),
        earnedCount: tiers.filter((x) => x.earned).length,
        totalCount: tiers.length,
      };
    })
    .filter((l) => l.totalCount > 0);

  // ---- Recently entered: newest earned, by earned_at date. Feats are left out
  // of this feed on purpose (matching the DC's own recentRows split) -- they
  // carry no points and are meant to be found by playing, not surfaced as a
  // routine unlock alongside everything else. ----
  const recent = nonFeat
    .filter((a) => a.earned && earnedAt[a.id])
    .slice()
    .sort((x, y) => (earnedAt[y.id] || "").localeCompare(earnedAt[x.id] || ""))
    .slice(0, 4);

  // ---- Within reach: closest LOCKED non-feat achievements to their threshold.
  // Feats are excluded -- most are one-shot triggers where a "% there" number
  // would be meaningless (or a de-facto spoiler) rather than informative. Only an honor the
  // server sent a count for is measured: one whose metric is not tracked has no count, so it
  // is not "within reach" of anything (Session O, O1: no count, no moon).
  const withinReach = nonFeat
    .map((a) => ({ a, p: progressOf(a) }))
    .filter(({ p }) => p && p.threshold > 0)
    .map(({ a, p }) => ({ ...a, _ratio: p.fraction }))
    .sort((x, y) => y._ratio - x._ratio)
    .slice(0, 3);

  // The relics are drawn by kind from relicRows (folio/completionistCore.js), not from here:
  // the skins list carries locked skins too, and only what is earned is ever shown.
  const skinsById = {};
  (data.skins || []).forEach((s) => { skinsById[s.id] = s; });

  // ---- Statistics: by-rarity + ladder completion. ----
  const rarityRows = RARITY_ORDER.map((tier) => {
    const rows = nonFeat.filter((a) => a.tier === tier);
    return { tier, earned: rows.filter((a) => a.earned).length, total: rows.length };
  });
  const ladderRows = ladders.map((l) => ({
    id: l.id, name: l.name, earned: l.earnedCount, total: l.totalCount,
    iconTierId: l.tiers[0] && l.tiers[0].id,
  }));

  return {
    achievements, ladders,
    milestones: achievements.filter((a) => displayBucket(a) === "milestone"),
    masteries: achievements.filter((a) => displayBucket(a) === "mastery"),
    feats,
    buckets, recent, withinReach, skinsById, rarityRows, ladderRows,
    earnedNonFeat: nonFeat.filter((a) => a.earned).length, totalNonFeat: nonFeat.length,
    earnedFeats: feats.filter((a) => a.earned).length, totalFeats: feats.length,
  };
}

// Today's date on THIS device, YYYY-MM-DD (the card's foot line).
function localDate() {
  const d = new Date();
  const z = (n) => String(n).padStart(2, "0");
  return d.getFullYear() + "-" + z(d.getMonth() + 1) + "-" + z(d.getDate());
}

// localStorage, or null when the browser refuses even to hand it over (private windows,
// blocked site data): the sort then simply does not persist.
function safeStorage() {
  try { return window.localStorage || null; } catch { return null; }
}

export default function useFolio() {
  // Seeded from the shared read cache (hooks/swrCache.js) so a REOPEN paints the roster,
  // the points and the ladders in the first frame instead of showing the empty shell while
  // /api/achievements re-measures. The refetch below still runs every open and replaces it
  // in place; the seams that must never show a stale roster -- a claim, a contest entry, a
  // finished job, App.jsx's afterMutation -- invalidate("/api/achievements") explicitly.
  const [data, setData] = useState(() => peek("/api/achievements"));
  const [err, setErr] = useState(null);
  const [tab, setTab] = useState("summary");
  const [q, setQ] = useState("");
  const [bucketFilter, setBucketFilter] = useState(null);
  const [activeLadderId, setActiveLadderId] = useState(null);
  const [quoteIdx, setQuoteIdx] = useState(0);
  // The All tab's sort (Session O, O3): remembered per DEVICE (this browser's storage), read
  // once here and written only when a chip is clicked -- never on open.
  const [sortKey, setSortKey] = useState(() => loadSort(
    typeof window !== "undefined" ? safeStorage() : null));

  // ---- Unleash + glitch-reveal state (folio-glitch-spec.md). `triggered`
  // gates the pill's existence; `unleashed` is the free toggle once it
  // exists. `reveal`/`activeToast` are the shared per-id source of truth
  // driving both a card's inline description and the replay toast. ----
  const [triggered, setTriggered] = useState(false);
  // The account's own switch (folio/unleashPref.js): the same person sees the same narrator
  // on every device. The server still decides whether the spicier line is released at all.
  const prefs = useAccountPrefs();
  const unleashed = isUnleashed(prefs.prefs);
  const [reveal, setReveal] = useState({});
  const [activeToast, setActiveToast] = useState(null);
  // Per-id interval/timeout handles -- plain instance maps (ref, not state):
  // no re-render needed to track them, matching the DC's own this._scrIv/_scrT.
  const scrIvRef = useRef({});
  const scrTRef = useRef({});
  const mountedRef = useRef(true);

  // ---- Masked feats (Session G). `seen` is the account's record of which earned feats it has
  // been shown (the wave-1 store, key SEEN_KEY); an earned feat NOT on it plays the glitch
  // reveal once, on the first Folio view after the earn. `freshIds` are the feats revealing
  // in THIS visit (they keep their ribbon until the Folio closes, then are on the record);
  // `clock` is how many milliseconds of the Feats section the reader has actually had on
  // screen -- the reveal's own timeline, paused while they are on another tab. ----
  const seenRaw = prefs.get(SEEN_KEY, undefined);
  const [focusId] = useState(() => takeFolioFocus());
  // The honor the header's pinned-goal chip asked to see (folio/folioFocus.js setFolioRow): the
  // Folio opens on the All tab with that row scrolled to and ringed. `ringId` stays until the
  // Folio closes. An id that is not a listed honor with a count is simply ignored.
  const [rowFocus] = useState(() => takeFolioRow());
  const [ringId, setRingId] = useState(null);

  const [freshIds, setFreshIds] = useState(() => new Set());
  const [clock, setClock] = useState(0);
  const [scrollTarget, setScrollTarget] = useState(null);
  const clockRef = useRef(0);
  const startRef = useRef({});          // id -> the clock reading when it became new
  const wroteRef = useRef(new Set());   // ids whose "seen" write has been sent
  const introRef = useRef(false);       // the one time the Folio steers itself to the Feats
  // The REAL celebration moment currently on screen (Ach.replay()'s handle,
  // tagged with the achievement id it belongs to) -- NOT React-rendered; it
  // lives in its own DOM node appended straight to document.body by
  // mg-notify.js, same as any other unlock celebration. Kept in a ref so the
  // scramble's setInterval tick can write into it directly without a
  // re-render, and so close/unmount can dismiss it if one is still showing.
  const replayHandleRef = useRef(null);
  // The celebration currently up, as replayToast() recorded it: a callback that outlives one
  // render (the choice toast's buttons) reads this, not the `activeToast` it closed over.
  const activeToastRef = useRef(null);
  const pokingRef = useRef(false);      // a poke is on its way to the server

  useEffect(() => {
    let dead = false;
    apiGet("/api/achievements")
      .then((d) => {
        put("/api/achievements", d);
        // The read that opens the Folio can be the one that EARNS a feat (the server sweeps
        // on every read); a feat with its own moment plays it through ach.js's one gate.
        noticeAchievements(d);
        if (dead) return;
        // An error only surfaces when there is nothing cached to keep showing -- the
        // shared cache's own rule (hooks/swrCache.js).
        if (d.error) { if (peek("/api/achievements") == null) setErr(d.error); }
        else setData(d);
      });
    return () => { dead = true; };
  }, []);

  // The narrator's quote rotates on its own, like the DC's 7s interval.
  useEffect(() => {
    const iv = setInterval(() => setQuoteIdx((i) => (i + 1) % NARRATOR_LINES.length), 7000);
    return () => clearInterval(iv);
  }, []);

  // unleash_available reflects the REAL, server-persisted "Triggered" feat
  // (moonglade_gallery.py ~15235: any earned achievement with id "triggered",
  // itself earned off a real, cross-session narrator_pokes counter at
  // /api/ach-event -- NOT the DC prototype's local-only, zero-backend pokes
  // mock). If it's already true on load -- earned via the classic Trophy
  // Hall, or a past session -- the pill must show immediately, with no fresh
  // pokes demanded again in the Folio: `triggered` only ever turns ON, never
  // off, matching the DC's own "permanently true" semantics, just fed by a
  // real signal instead of a fake one.
  useEffect(() => {
    if (data && data.unleash_available) setTriggered(true);
  }, [data]);

  useEffect(() => {
    mountedRef.current = true;
    // Belt-and-suspenders with close(): a global Escape handler (App.jsx
    // desktop) or a screen back-button (mobile) can unmount the consumer
    // directly without going through close() first, so this unmount
    // cleanup is what actually guarantees a still-open celebration moment
    // gets dismissed no matter which exit path fired.
    return () => {
      mountedRef.current = false;
      clearAllScr();
      if (replayHandleRef.current && replayHandleRef.current.dismiss) replayHandleRef.current.dismiss();
      replayHandleRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function clearScr(id) {
    if (scrIvRef.current[id]) clearInterval(scrIvRef.current[id]);
    if (scrTRef.current[id]) clearTimeout(scrTRef.current[id]);
    delete scrIvRef.current[id];
    delete scrTRef.current[id];
  }
  function clearAllScr() {
    Object.values(scrIvRef.current).forEach(clearInterval);
    Object.values(scrTRef.current).forEach(clearTimeout);
    scrIvRef.current = {};
    scrTRef.current = {};
  }
  function reducedMotion() {
    return !!(typeof window !== "undefined" && window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  }
  // 34ms-tick scramble, 26 ticks (~885ms). Each tick locks in the target's
  // left-most floor((tick/26)*len) characters; everything still unlocked
  // (plus the target's own literal spaces) renders as a random GLYPHS pick.
  function runScramble(id, to) {
    let f = 0;
    const total = 26;
    const iv = setInterval(() => {
      if (!mountedRef.current) { clearInterval(iv); return; }
      f++;
      const lock = Math.floor((f / total) * to.length);
      let out = "";
      for (let i = 0; i < to.length; i++) {
        out += (i < lock || to[i] === " ") ? to[i] : GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
      }
      // Drive the real celebration moment (if this id's is the one currently
      // showing) in lockstep with the card's own React-rendered text -- same
      // reveal[id] source of truth, two surfaces.
      const h = replayHandleRef.current;
      const live = h && h.id === id;
      if (f >= total) {
        // Capture the handle locally before the by-id map lookup: a restart
        // can overwrite scrIvRef.current[id] before this final tick fires,
        // so clearing/deleting by lookup alone could orphan THIS interval.
        clearInterval(iv);
        if (scrIvRef.current[id] === iv) delete scrIvRef.current[id];
        setReveal((r) => ({ ...r, [id]: { text: to, g: false, done: true } }));
        if (live) { h.setText(to); h.setGlitching(false); h.setSettledNsfw(true); }
      } else {
        setReveal((r) => ({ ...r, [id]: { text: out, g: true, done: false } }));
        if (live) { h.setText(out); h.setGlitching(true); }
      }
    }, 34);
    scrIvRef.current[id] = iv;
  }
  function roastPair(a) {
    return { sfw: a.roast || a.desc || "", nsfw: a.roast_nsfw || "" };
  }
  // Clean text shows instantly. If Unleash is off, or this item has no NSFW
  // line (server keeps roast_nsfw blanked on every achievement until
  // "Triggered" is really earned -- see the unleash_available note above),
  // it stops there. Otherwise: a 600ms readable hold, then scramble (or,
  // reduced-motion, a plain 600ms snap straight to the NSFW text).
  function rerunToast(at, unleashedNow) {
    if (!at) return;
    clearScr(at.id);
    setReveal((r) => ({ ...r, [at.id]: { text: at.sfw, g: false, done: false } }));
    const h = replayHandleRef.current;
    if (h && h.id === at.id) { h.setText(at.sfw); h.setGlitching(false); h.setSettledNsfw(false); }
    if (!(unleashedNow && at.nsfw)) return;
    if (reducedMotion()) {
      scrTRef.current[at.id] = setTimeout(() => {
        if (!mountedRef.current) return;
        setReveal((r) => ({ ...r, [at.id]: { text: at.nsfw, g: false, done: true } }));
        const h2 = replayHandleRef.current;
        if (h2 && h2.id === at.id) { h2.setText(at.nsfw); h2.setSettledNsfw(true); }
      }, 600);
      return;
    }
    scrTRef.current[at.id] = setTimeout(() => {
      if (!mountedRef.current) return;
      runScramble(at.id, at.nsfw);
    }, 600);
  }
  // Click an earned card -> replay its REAL celebration moment (badge sweep,
  // mascot pop, ring pulse, chime, and -- legendary/feat -- the full
  // confetti/star fanfare: mg-notify.js's own Ach.replay(), the same
  // _mkMoment/_play/_fanfare a genuine new unlock uses, not a second
  // invented toast). Locked/masked achievements are wired to the same
  // handler by every consumer (matching the DC's own cardBase) but no-op
  // here.
  // Ach.replay() goes through the engine's ONE queue, at the FRONT of it: it
  // takes the screen over (the moment being presented is removed, a parade's
  // receded trail goes with it) but it is HELD like everything else while a
  // bespoke moment owns the screen or a cast is waiting for it, and it plays
  // when that lifts. So the handle can come back before the moment exists --
  // it records what it is told and the engine replays that onto the moment it
  // eventually builds. Dismiss whatever moment might already be showing before
  // starting the next one, so two clicks in a row don't stack: dismissing an
  // entry that never reached the screen simply takes it out of the queue.
  function replayToast(a) {
    if (!a.earned) return;
    const { sfw, nsfw } = roastPair(a);
    clearScr(a.id);
    if (replayHandleRef.current && replayHandleRef.current.dismiss) replayHandleRef.current.dismiss();
    const at = { id: a.id, name: a.name, tier: a.tier || "feat", sfw, nsfw };
    activeToastRef.current = at;
    setActiveToast(at);
    const h = window.Ach && window.Ach.replay ? window.Ach.replay(a, { line: sfw }) : null;
    replayHandleRef.current = h ? { id: a.id, ...h } : null;
    rerunToast(at, unleashed);
  }
  // Flips unleashed, wipes every revealed line, clears in-flight scrambles,
  // then re-runs whatever moment is currently showing at the new setting:
  // forward = scramble to NSFW, backward = snap straight to clean (no
  // reverse-animation) -- the moment itself stays open, only its text reacts.
  function toggleUnleash() {
    const next = !unleashed;
    prefs.set(UNLEASH_KEY, next);
    setReveal({});
    clearAllScr();
    rerunToast(activeToast, next);
  }
  // Real onClick on the narrator avatar (and the rail portrait, and the phone's quote).
  // POST /api/narrator/poke: the SERVER keeps the count and the clocks for this account,
  // decides whether the poke counts and chooses the line; the reply is a line and nothing
  // else, and a poke that did not count is shown exactly like one that did. A refusal (an
  // expired page, a busy store) is a quiet no-op, as every beacon has always been.
  // One request at a time: a click that fires twice is one poke, not a spam line.
  function pokeNarrator() {
    if (pokingRef.current) return;
    pokingRef.current = true;
    accountPrefs().ensureLoaded()
      .then(() => apiPost("/api/narrator/poke", { csrf: accountCsrf() }))
      .then((res) => {
        pokingRef.current = false;
        if (!mountedRef.current) return;
        const v = pokeView(res);
        if (!v.show) return;
        if (v.final) { endOfLadder(v); return; }
        if (window.Toast) window.Toast.show({ title: v.line, icon: "👆" });
      })
      .catch(() => { pokingRef.current = false; });
  }
  // The poke that ended the ladder (and earned the feat behind the pill): read the roster
  // once more -- marking it seen, so the ordinary earn toast does not follow -- and put the
  // feat's own celebration on screen with its clean line, then ask which narrator the
  // account wants from now on. "Unleash" turns the switch on and plays the glitch reveal on
  // the celebration already up; "Keep" writes the switch off, so it is an answer, not a blank.
  function endOfLadder(v) {
    setTriggered(true);
    apiGet("/api/achievements?mark=1").then((d) => {
      if (!d || d.error) return;
      put("/api/achievements", d);
      if (!mountedRef.current) return;
      setData(d);
      const card = (d.achievements || []).find((a) => a.id === v.card);
      if (card) replayToast(card);
      offerChoice(v.choice);
    });
  }
  function chooseUnleash(pick) {
    const on = choiceValue(pick);
    prefs.set(UNLEASH_KEY, on);
    if (!on || !mountedRef.current) return;
    setReveal({});
    clearAllScr();
    rerunToast(activeToastRef.current, true);
  }
  function offerChoice(copy) {
    if (!window.Toast) return;
    window.Toast.show({
      kind: "choice", icon: "👆", sticky: true,
      title: copy.title, foot: copy.foot,
      actions: [
        { label: copy.keep, run: () => chooseUnleash("keep") },
        { label: copy.unleash, tone: "ruby", run: () => chooseUnleash("unleash") },
      ],
    });
  }
  // Cleanup only -- clears every in-flight scramble, resets reveal/toast,
  // dismisses any still-open celebration. Deliberately does NOT navigate:
  // WHAT happens next (unmount an overlay, pop a mobile screen) is a
  // presentation decision each consumer owns, matching useHealth.js's own
  // documented split. Call this THEN the consumer's own close/back action.
  function close() {
    clearAllScr();
    setReveal({});
    setActiveToast(null);
    activeToastRef.current = null;
    if (replayHandleRef.current && replayHandleRef.current.dismiss) replayHandleRef.current.dismiss();
    replayHandleRef.current = null;
  }

  const vm = useMemo(() => (data ? buildViewModel(data) : null), [data]);
  const earnedAt = (data && data.earned_at) || {};

  // ---- The completion meter (O2): ladders + milestones + masteries only; feats are "N found"
  // and never part of the total. Relics by kind (Small Calls L2): earned rewards only, one row
  // per kind, hidden when empty.
  const meter = useMemo(() => (data ? completionOf(data.achievements) : null), [data]);
  const relics = useMemo(() => (data ? relicRows({
    skins: data.skins, achievements: data.achievements,
    marks: data.relics && data.relics.marks, earnedAt: data.earned_at, activeSkin: data.skin,
  }) : []), [data]);
  // A relic skin's tap applies it (POST /api/skin, the same road the Control Panel uses); a
  // refusal is a quiet no-op. Only a click ever writes.
  function pickSkin(id) {
    if (!data || data.skin === id) return;
    applySkin(id, data, setData).catch(() => {});
  }
  function chooseSort(key) {
    setSortKey(key);
    saveSort(safeStorage(), key);
  }

  // ---- The Vigil (O5) and the pinned goal (O4). The Vigil's numbers come from the payload; the
  // "show it in the app header" switch and the pin are the ACCOUNT's own preferences, written
  // only by a click (setVigilOn / pinToggle) -- never on open.
  const vigil = useMemo(() => vigilView(data && data.vigil), [data]);
  const pin = pinnedId(prefs.prefs);
  const vigilOn = vigilInHeader(prefs.prefs);
  function setVigilOn(on) {
    return on ? prefs.set(VIGIL_HEADER_KEY, true) : prefs.unset(VIGIL_HEADER_KEY);
  }
  // One pin: pinning another honor replaces it, pinning the pinned one lets go, and an honor
  // with no count (a feat, an unmeasured metric, one already earned) changes nothing.
  function pinToggle(a) {
    const next = togglePin(pin, a);
    if (next === null) return null;
    return next ? prefs.set(PIN_KEY, next) : prefs.unset(PIN_KEY);
  }
  // The Honors card's model (O6): drawn on this device, from what the Folio already holds.
  const cardModel = useMemo(() => (data ? honorsCardModel({
    user: (typeof window !== "undefined" && window.MG_BOOT && window.MG_BOOT.user) || "",
    achievements: data.achievements, earnedPoints: data.earned_points,
    earnedAt: data.earned_at, vigil: data.vigil, date: localDate(),
  }) : null), [data]);

  // Default ladder: "archive" (The Archive), matching the DC script's own
  // state default -- falls back to whichever ladder actually exists first if
  // that track is somehow absent from this install's roster.
  const ladderId = activeLadderId || (vm && (vm.ladders.some((l) => l.id === "archive") ? "archive" : (vm.ladders[0] && vm.ladders[0].id)));
  const activeLadder = vm ? (vm.ladders.find((l) => l.id === ladderId) || vm.ladders[0]) : null;

  const toggleBucket = (key) => {
    setBucketFilter((prev) => (prev === key ? null : key));
    setTab("all");
  };
  const onSearchChange = (e) => {
    setQ(e.target.value);
    setTab("all");
  };

  const qlc = q.trim().toLowerCase();
  const showLadders = !bucketFilter || bucketFilter === "ladder";
  const showMilestones = !bucketFilter || bucketFilter === "milestone";
  const showMasteries = !bucketFilter || bucketFilter === "mastery";
  const showFeats = (!bucketFilter || bucketFilter === "feat") && !!(vm && vm.earnedFeats > 0);

  const filteredActiveTiers = activeLadder ? activeLadder.tiers.filter((t) => matchesQuery(t, qlc)) : [];
  const filteredMilestones = vm ? vm.milestones.filter((a) => matchesQuery(a, qlc)) : [];
  const filteredMasteries = vm ? vm.masteries.filter((a) => matchesQuery(a, qlc)) : [];
  // Earned feats stand in the order they were found; the search filters them like any other
  // card. The veil is never one of them (see `veil` below).
  const filteredFeats = vm ? orderFeats(vm.feats.filter((a) => matchesQuery(a, qlc)), data.earned_at) : [];

  // ---- The sorted view (O3). Any sort but Default lays the ladders' rungs, the milestones and
  // the masteries out as ONE list in the chosen order, under the same search and category
  // filter as the sections it replaces. Feats are never in it (sortHonors sets them aside) and
  // keep their own section below, in the order they were found. ----
  const sortedHonors = useMemo(() => {
    if (!vm || sortKey === "default") return [];
    const flat = [];
    if (showLadders) vm.ladders.forEach((l) => l.tiers.forEach((t) => { if (matchesQuery(t, qlc)) flat.push(t); }));
    if (showMilestones) filteredMilestones.forEach((a) => flat.push(a));
    if (showMasteries) filteredMasteries.forEach((a) => flat.push(a));
    return sortHonors(flat, sortKey, earnedAt);
  }, [vm, sortKey, showLadders, showMilestones, showMasteries, qlc, filteredMilestones, filteredMasteries, earnedAt]);

  // ---- "Every rung, every ladder" (desktop-only, Folio of Honors.dc.html's
  // showGroups/ladderGroups): every ladder's OWN filtered tiers, grouped --
  // not just the one active ladder. Nested under showLadders in the DC's own
  // markup (both sc-ifs close together), so this only matters while a caller
  // also gates rendering on showLadders -- matching that same nesting here. ----
  const filteredLadderGroups = vm
    ? vm.ladders
        .map((l) => ({ ...l, filteredTiers: l.tiers.filter((t) => matchesQuery(t, qlc)) }))
        .filter((l) => l.filteredTiers.length > 0)
    : [];
  const groupedTierCount = filteredLadderGroups.reduce((n, l) => n + l.filteredTiers.length, 0);
  const showGroups = groupedTierCount > 0;

  // groupedTierCount, not filteredActiveTiers: since the ALL tab stopped rendering the
  // active ladder's own grid (handoff C4 -- "Every rung, every ladder" is the single
  // census), the question "did the search find any rung at all" is a question about the
  // census. Asking the old one meant a search that matched a rung on some OTHER track
  // still counted as nothing found, and the "Nothing in the record" panel printed above a
  // census full of hits.
  const nothingFound = !!qlc && (
    (!showLadders || groupedTierCount === 0) &&
    (!showMilestones || filteredMilestones.length === 0) &&
    (!showMasteries || filteredMasteries.length === 0) &&
    (!showFeats || filteredFeats.length === 0)
  );

  // ---- THE VEIL AND THE REVEAL -------------------------------------------------------
  const featsPayload = (data && data.feats) || null;
  const veil = veilState(featsPayload, { query: qlc, unleashed });
  const reduced = reducedMotion();
  // The Feats section is on screen: its own tab, and not filtered out by a category.
  const featsOnScreen = tab === "all" && showFeats;

  // Which earned feats are new to this account. Runs when the roster and the account's own
  // record have both arrived, and again if a new earn lands while the Folio is open. The FIRST
  // time it finds any (or when the earn moment's link asked for one) it steers the Folio to
  // the All tab and scrolls the card into view -- "the Folio opens scrolled to the Feats".
  useEffect(() => {
    if (!data || !prefs.ready) return;
    const feats = (data.achievements || []).filter((a) => displayBucket(a) === "feat");
    const fresh = unseenFeatIds({ feats, earnedAt: data.earned_at, seen: seenRaw })
      .filter((id) => !Object.prototype.hasOwnProperty.call(startRef.current, id));
    if (fresh.length) {
      fresh.forEach((id) => { startRef.current[id] = clockRef.current; });
      setFreshIds((prev) => new Set([...prev, ...fresh]));
    }
    if (!introRef.current) {
      const aim = (focusId && feats.some((a) => a.id === focusId && a.earned)) ? focusId : fresh[fresh.length - 1];
      if (aim) {
        introRef.current = true;
        setTab("all");
        setBucketFilter(null);
        setScrollTarget(aim);
      }
    }
  }, [data, prefs.ready, seenRaw, focusId]);

  // The pinned-goal chip's row: once the roster is here, go to the All tab, pick that honor's
  // ladder, ring its row and scroll it into view. Once per open, and never for an id that is not
  // a listed honor with a count (a feat, an earned honor, an unmeasured metric, or nothing).
  const [rowScroll, setRowScroll] = useState(null);
  const rowDoneRef = useRef(false);
  useEffect(() => {
    if (!rowFocus || !vm || rowDoneRef.current) return;
    rowDoneRef.current = true;
    const a = vm.achievements.find((x) => x.id === rowFocus);
    if (!a || !canPin(a)) return;
    setTab("all");
    setBucketFilter(null);
    if (a.bucket === "ladder" && a.track) setActiveLadderId(a.track);
    setRingId(a.id);
    setRowScroll(a.id);
  }, [rowFocus, vm]);
  useEffect(() => {
    if (!rowScroll || tab !== "all") return undefined;
    const raf = requestAnimationFrame(() => {
      const el = document.querySelector('[data-honor-id="' + String(rowScroll).replace(/["\\]/g, "") + '"]');
      if (el && el.scrollIntoView) el.scrollIntoView({ block: "center", behavior: "auto" });
      setRowScroll(null);
    });
    return () => cancelAnimationFrame(raf);
  }, [rowScroll, tab, vm]);

  // Scroll the aimed-at card into view once it is on the page.
  useEffect(() => {
    if (!scrollTarget || !featsOnScreen) return;
    const raf = requestAnimationFrame(() => {
      const el = document.querySelector('[data-feat-id="' + String(scrollTarget).replace(/["\\]/g, "") + '"]');
      if (el && el.scrollIntoView) el.scrollIntoView({ block: "center", behavior: "auto" });
      setScrollTarget(null);
    });
    return () => cancelAnimationFrame(raf);
  }, [scrollTarget, featsOnScreen, vm]);

  // The reveal's clock: runs only while a revealing feat is unfinished AND the Feats section is
  // on screen, so a reader who tabs away mid-reveal does not miss it.
  const unfinished = [...freshIds].some((id) => (clock - (startRef.current[id] || 0)) < REVEAL.VEIL + REVEAL.VEIL_FADE);
  useEffect(() => {
    if (!featsOnScreen || !unfinished) return;
    const t0 = performance.now() - clockRef.current;
    const iv = setInterval(() => {
      clockRef.current = performance.now() - t0;
      setClock(clockRef.current);
    }, 30);
    return () => clearInterval(iv);
  }, [featsOnScreen, unfinished]);

  // The one-time "seen" write: only when the reader has actually had the revealing card on
  // screen for the whole reveal, and never on open. It records every earned feat now on the
  // page, so a first write cannot leave an older feat "new" next time.
  useEffect(() => {
    if (!data || !prefs.ready) return;
    const due = [...freshIds].filter((id) => !wroteRef.current.has(id)
      && (clock - (startRef.current[id] || 0)) >= REVEAL.VEIL);
    if (!due.length) return;
    due.forEach((id) => wroteRef.current.add(id));
    const feats = (data.achievements || []).filter((a) => displayBucket(a) === "feat");
    prefs.set(SEEN_KEY, nextSeen(seenRaw, feats));
  }, [clock, freshIds, data, prefs.ready]);

  // One card's reveal frame (null when it is not revealing) and whether the next veil must
  // still wait for the reveal to reach its last beat.
  const frameFor = (id) => (freshIds.has(id)
    ? revealFrame(featsOnScreen ? clock - (startRef.current[id] || 0) : 0, reduced) : null);
  const veilWaiting = [...freshIds].some((id) => !frameFor(id).veilIn);

  return {
    data, err, vm, earnedAt,
    veil, frameFor, veilWaiting, freshIds, foundCount: vm ? vm.earnedFeats : 0,
    tab, setTab, q, setQ, onSearchChange,
    bucketFilter, toggleBucket, setBucketFilter,
    activeLadderId, setActiveLadderId, ladderId, activeLadder,
    quoteIdx,
    triggered, unleashed, toggleUnleash,
    reveal, activeToast,
    pokeNarrator, replayToast, close,
    showLadders, showMilestones, showMasteries, showFeats,
    meter, relics, pickSkin, sortKey, chooseSort, sortedHonors,
    vigil, vigilOn, setVigilOn, pin, pinToggle, ringId, cardModel,
    filteredActiveTiers, filteredMilestones, filteredMasteries, filteredFeats, nothingFound,
    filteredLadderGroups, showGroups, groupedTierCount,
  };
}
