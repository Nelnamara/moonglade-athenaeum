import { useEffect, useMemo, useRef, useState } from "react";

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
// Byte-for-byte from static/mg-notify.js's own `poke()` (~line 1061) -- the
// REAL escalating warning toast every poke already shows in the classic
// Trophy Hall. The React port was posting to /api/ach-event silently with no
// per-click feedback at all, which is what made 5 real pokes feel trivial/
// unearned compared to classic's actual build-up -- not a missing time-gate
// (verified: neither poke() nor /api/ach-event's server handler has ANY
// cooldown/rate-limit, client or server side; 5 real, separate clicks is the
// only real gate there ever was), just this missing feedback loop.
export const POKES = [
  "The narrator ignores you.",
  "The narrator raises an eyebrow. Do you mind?",
  "The narrator is DESCRIBING things. Hands off.",
  "The narrator’s eye twitches. Last warning.",
  "FINE. You want the REAL commentary? Unleashed. Happy now?",
];

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

/* Pure: flat achievements[] + ladders[] (the 10 track defs) + skin/earned_at ->
   the grouped shape the Folio's three tabs actually render from. Kept as one
   small pure function on purpose (per the task brief) so the next stage can
   extend it without re-deriving the grouping logic from render code. */
export function buildViewModel(data) {
  const achievements = data.achievements || [];
  const earnedAt = data.earned_at || {};
  const ladderDefs = data.ladders || [];

  const nonFeat = achievements.filter((a) => a.bucket !== "feat");
  const feats = achievements.filter((a) => a.bucket === "feat");

  // ---- Categories: the right rail's 4 bucket filters + Summary's ledger +
  // Statistics' "by bucket" list all read the same {key,label,earned,total}. ----
  const buckets = BUCKETS.map(({ key, label }) => {
    const rows = achievements.filter((a) => a.bucket === key);
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
  // would be meaningless (or a de-facto spoiler) rather than informative. ----
  const withinReach = nonFeat
    .filter((a) => !a.earned && a.threshold > 0)
    .map((a) => ({ ...a, _ratio: Math.min(1, a.current / a.threshold) }))
    .sort((x, y) => y._ratio - x._ratio)
    .slice(0, 3);

  // ---- Relics: read-only skin display; active = the currently-applied skin. ----
  const relics = (data.skins || []).map((s) => ({ ...s, active: s.id === data.skin }));
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
    milestones: achievements.filter((a) => a.bucket === "milestone"),
    masteries: achievements.filter((a) => a.bucket === "mastery"),
    feats,
    buckets, recent, withinReach, relics, skinsById, rarityRows, ladderRows,
    earnedNonFeat: nonFeat.filter((a) => a.earned).length, totalNonFeat: nonFeat.length,
    earnedFeats: feats.filter((a) => a.earned).length, totalFeats: feats.length,
  };
}

export default function useFolio() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const [tab, setTab] = useState("summary");
  const [q, setQ] = useState("");
  const [bucketFilter, setBucketFilter] = useState(null);
  const [activeLadderId, setActiveLadderId] = useState(null);
  const [quoteIdx, setQuoteIdx] = useState(0);

  // ---- Unleash + glitch-reveal state (folio-glitch-spec.md). `triggered`
  // gates the pill's existence; `unleashed` is the free toggle once it
  // exists. `reveal`/`activeToast` are the shared per-id source of truth
  // driving both a card's inline description and the replay toast. ----
  const [triggered, setTriggered] = useState(false);
  const [unleashed, setUnleashed] = useState(false);
  const [reveal, setReveal] = useState({});
  const [activeToast, setActiveToast] = useState(null);
  // Per-id interval/timeout handles -- plain instance maps (ref, not state):
  // no re-render needed to track them, matching the DC's own this._scrIv/_scrT.
  const scrIvRef = useRef({});
  const scrTRef = useRef({});
  const mountedRef = useRef(true);
  // The REAL celebration moment currently on screen (Ach.replay()'s handle,
  // tagged with the achievement id it belongs to) -- NOT React-rendered; it
  // lives in its own DOM node appended straight to document.body by
  // mg-notify.js, same as any other unlock celebration. Kept in a ref so the
  // scramble's setInterval tick can write into it directly without a
  // re-render, and so close/unmount can dismiss it if one is still showing.
  const replayHandleRef = useRef(null);

  useEffect(() => {
    let dead = false;
    fetch("/api/achievements")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((d) => { if (!dead) setData(d); })
      .catch((e) => { if (!dead) setErr(String(e.message || e)); });
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
  // Ach.replay() is immediate and NOT queued (unlike a real earn-event) --
  // dismiss whatever moment might already be showing before starting the
  // next one, so two clicks in a row don't stack.
  function replayToast(a) {
    if (!a.earned) return;
    const { sfw, nsfw } = roastPair(a);
    clearScr(a.id);
    if (replayHandleRef.current && replayHandleRef.current.dismiss) replayHandleRef.current.dismiss();
    const at = { id: a.id, name: a.name, tier: a.tier || "feat", sfw, nsfw };
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
    setUnleashed(next);
    setReveal({});
    clearAllScr();
    rerunToast(activeToast, next);
  }
  // Real onClick on the narrator avatar: POSTs to the SAME /api/ach-event
  // endpoint mg-notify.js's own Ach.poke() uses (narrator_pokes, persisted,
  // cross-session/cross-surface -- poking here counts toward the identical
  // "Triggered" feat poking in the classic Trophy Hall does). On snap,
  // refetch /api/achievements so the newly-unblanked roast_nsfw text is
  // actually there to scramble to (mirrors mg-notify.js's poke()->load(true)).
  function pokeNarrator() {
    fetch("/api/ach-event", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event: "narrator" }),
    })
      .then((r) => r.json())
      .then((res) => {
        if (!mountedRef.current) return;
        // Same escalating warning toast the classic poke() shows on every
        // single click, byte-for-byte (POKES above) -- the real feedback
        // loop that makes 5 pokes feel earned, not the count alone.
        if (window.Toast && res) {
          const n = Math.max(1, Math.min(res.pokes || 1, POKES.length));
          window.Toast.show({ title: POKES[n - 1], kind: n >= POKES.length ? "err" : "", icon: "👆" });
        }
        if (res && (res.snapped || (res.pokes || 0) >= 5)) {
          setTriggered(true);
          fetch("/api/achievements")
            .then((r2) => (r2.ok ? r2.json() : null))
            .then((d) => { if (mountedRef.current && d) setData(d); })
            .catch(() => {});
        }
      })
      .catch(() => {});
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
    if (replayHandleRef.current && replayHandleRef.current.dismiss) replayHandleRef.current.dismiss();
    replayHandleRef.current = null;
  }

  const vm = useMemo(() => (data ? buildViewModel(data) : null), [data]);
  const earnedAt = (data && data.earned_at) || {};

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
  const filteredFeats = vm ? vm.feats.filter((a) => matchesQuery(a, qlc)) : [];

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

  const nothingFound = !!qlc && (
    (!showLadders || filteredActiveTiers.length === 0) &&
    (!showMilestones || filteredMilestones.length === 0) &&
    (!showMasteries || filteredMasteries.length === 0) &&
    (!showFeats || filteredFeats.length === 0)
  );

  return {
    data, err, vm, earnedAt,
    tab, setTab, q, setQ, onSearchChange,
    bucketFilter, toggleBucket, setBucketFilter,
    activeLadderId, setActiveLadderId, ladderId, activeLadder,
    quoteIdx,
    triggered, unleashed, toggleUnleash,
    reveal, activeToast,
    pokeNarrator, replayToast, close,
    showLadders, showMilestones, showMasteries, showFeats,
    filteredActiveTiers, filteredMilestones, filteredMasteries, filteredFeats, nothingFound,
    filteredLadderGroups, showGroups, groupedTierCount,
  };
}
