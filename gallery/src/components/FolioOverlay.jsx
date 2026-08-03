import React, { useEffect, useMemo, useRef, useState } from "react";
import "../styles/overlays.css";
import "../styles/folio-overlay.css";

/* The Folio of Honors -- the seventh designed nav overlay to port, opened from
   Banner.jsx's gold "🏆 Folio" button (App.jsx's onFolio -> openOverlay("folio"),
   already wired). Self-contained fetch of GET /api/achievements on mount, same
   dead-guard pattern as HealthOverlay.jsx / DuplicateReviewOverlay.jsx.

   Pixel source of truth: design_handoff/design_handoff_moonglade_suite/
   "Folio of Honors.dc.html" (988 lines) + folio-glitch-spec.md. The DC's own
   "trophy-data.js" mock module does NOT exist in this repo -- buildViewModel()
   below derives the same shape (ladders grouped by track, buckets, recent,
   within-reach, relics, rarity/ladder stats) from the REAL flat achievements
   array instead. The DC's "rarity" vocabulary IS this app's real "tier" field
   (common/rare/epic/legendary/feat) -- same concept, not remapped.

   Read-only surface (three tabs, the right rail, local search, the 4-bucket
   category filter) plus the full narrator-poke / Unleash / glitch-reveal
   interaction from folio-glitch-spec.md: poking the header avatar
   (mgfo-nar-avatar) posts to the SAME /api/ach-event endpoint the classic
   Trophy Hall's Ach.poke() uses, so it counts toward the real, persisted
   "Triggered" feat -- the pill (`triggered`) shows once that's earned,
   whether that happened just now, in a past session, or via the classic UI.
   "Unleash the AI" is a free client-side toggle once the pill exists;
   clicking any EARNED card (or the toast it opens) glitch-scrambles its
   description from the clean roast to the NSFW one via `reveal[id]`, the
   shared per-achievement state that drives both surfaces off one source
   of truth. See runScramble/rerunToast/replayToast below for the exact
   34ms/26-tick algorithm, copied from the DC's own _runScramble. */

const BUCKETS = [
  { key: "ladder", label: "Evolution Ladders" },
  { key: "milestone", label: "Milestones" },
  { key: "mastery", label: "Masteries" },
  { key: "feat", label: "Feats of the Athenaeum" },
];

// Rarity/points table (wiki/Folio-of-Honors.md "Rarity and points") scores four
// tiers -- feat is deliberately excluded from every rarity breakdown (it scores
// 0 points by design, "pure bragging-rights flair", achievement_points() in
// moonglade_gallery.py), matching the DC's own RARITY_ORDER.
const RARITY_ORDER = ["common", "rare", "epic", "legendary"];

// The narrator's rotating lines, verbatim from the DC script's `nelLines` --
// this app's own shipped product copy (the same voice mg-notify.js's roasts
// use), not third-party content. Poke-driven reveal lines stay out of scope
// for this stage.
const NARRATOR_LINES = [
  "Keep going. The Void will not archive itself.",
  "Every relic you skip, I catalog as a grudge.",
  "I've seen better hoards from goblins.",
  "Progress. Or at least the illusion of it.",
  "The archive remembers what you'd rather forget.",
  "Dust doesn't collect itself. Neither do trophies, apparently.",
];

const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());

function matchesQuery(a, q) {
  if (!q) return true;
  const hay = ((a.name || "") + " " + (a.desc || "") + " " + (a.tier || "")).toLowerCase();
  return hay.indexOf(q) >= 0;
}

/* ---- Glitch-reveal: verbatim from "Folio of Honors.dc.html"'s own GLYPHS
   constant + folio-glitch-spec.md (copied character-for-character, not
   retyped by hand). Shared by AchCard's inline description and the replay
   toast off the same `reveal[id]` map -- single source of truth per id. ---- */
const GLYPHS = "▉▊▋▌░▒▓@#%&$*<>/\\|=+×÷¤§øþ";

/* Pure: reveal[id] (if present) always wins over the earned `roast`/locked
   `desc` -- this is what makes a card's body and the replay toast for the
   same id show the identical text as it glitches/settles. */
function commentary(a, reveal) {
  const rv = reveal && reveal[a.id];
  if (rv) return rv.text;
  if (a.earned) return a.roast || a.desc;
  return a.desc;
}
// Color/font law (folio-glitch-spec.md): mid-scramble -> monospace + red;
// settled on the NSFW line (done, no longer glitching) -> red, still italic.
function revealMod(a, reveal) {
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
function buildViewModel(data) {
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
    .slice(0, 6);

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
  const ladderRows = ladders.map((l) => ({ id: l.id, name: l.name, earned: l.earnedCount, total: l.totalCount }));

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

function Bar({ pct, variant, tier }) {
  return (
    <div className={"mgfo-bar" + (variant ? " " + variant : "") + (tier ? " mgfo-t-" + tier : "")}>
      <i style={{ width: Math.max(0, Math.min(100, pct)) + "%" }} />
    </div>
  );
}

/* One achievement/tier card -- shared by the ladder grid, Milestones,
   Masteries and Feats (masked hidden feats arrive from the server already
   sanitized -- id/name/desc/icon replaced -- so this needs no client-side
   masking logic of its own, just a render branch for the "masked" look).

   Layout matches the DC's own tierCard/flatCard exactly: name + description
   (+ ladder meta, + criteria checklist) in the body, tier pill + points +
   earned-date/"not yet" stacked in a right-aligned side column -- the DC
   deliberately does NOT put a numeric progress bar on every locked card
   (that's reserved for the curated "Within reach" list); this card just
   says "not yet". Criteria checklists (full-toolbox/master-of-the-loom)
   are a real field the DC's own mock predates -- kept per the task's data
   contract and wiki/Folio-of-Honors.md, not a DC omission to second-guess. */
function AchCard({ a, ladderName, date, skinsById, reveal, onReplay }) {
  const masked = !a.earned && a.hidden;
  const isFeat = a.bucket === "feat";
  const tierClass = "mgfo-t-" + (a.tier || "common");
  const badgeSrc = masked
    ? "/branding/mystery/secret_feat.png"
    : "/badge-thumb/" + encodeURIComponent(a.id) + ".png";
  const desc = masked ? "Hidden until earned" : commentary(a, reveal);
  const skinName = a.skin && skinsById && skinsById[a.skin] ? skinsById[a.skin].name : a.skin;
  const sub = a.earned ? (date || "") : "not yet";

  return (
    // Click replays this card's earn celebration (Ach/mg-notify.js precedent:
    // earned-only -- onReplay/replayToast no-ops on a locked/masked card).
    <div className={"mgfo-card " + tierClass + (a.earned ? " earned" : " locked") + (masked ? " masked" : "")}
      onClick={() => onReplay && onReplay(a)}>
      <span className="mgfo-card-gem" aria-hidden="true" />
      <div className="mgfo-card-ico">
        <span className="mgfo-card-emoji" aria-hidden="true">{masked ? "❓" : a.icon}</span>
        <img className="mgfo-card-badge" src={badgeSrc} alt="" draggable={false}
          onError={(e) => e.currentTarget.remove()} />
      </div>
      <div className="mgfo-card-body">
        <div className="mgfo-card-nm">{masked ? "???" : a.name}</div>
        <div className={"mgfo-card-ds" + (masked ? "" : revealMod(a, reveal))}>{desc}</div>
        {a.bucket === "ladder" && ladderName && !masked && (
          <div className="mgfo-card-meta">{ladderName} · {fmt(a.threshold)}</div>
        )}
        {a.criteria && a.criteria.length > 0 && (
          <div className="mgfo-crit">
            {a.criteria.map((c) => (
              <span key={c.key} className={c.done ? "on" : ""}>{c.done ? "✓" : "○"} {c.label}</span>
            ))}
          </div>
        )}
        {!masked && a.skin && <div className="mgfo-flag">★ unlocks {skinName} skin</div>}
        {!masked && a.banner_reward && <div className="mgfo-flag">⚑ unlocks a banner</div>}
      </div>
      <div className="mgfo-card-side">
        {!masked && <span className="mgfo-pill">{isFeat ? "feat" : a.tier}</span>}
        <span className="mgfo-card-pts">
          {a.points ? "+" + a.points + " pts" : (isFeat && !masked ? "for the glory" : "")}
        </span>
        {!masked && <span className="mgfo-card-subl">{sub}</span>}
      </div>
    </div>
  );
}

function CardGrid({ items, ladderName, earnedAt, skinsById, emptyLabel, reveal, onReplay }) {
  if (!items.length) return emptyLabel ? <div className="mgfo-empty-mini">{emptyLabel}</div> : null;
  return (
    <div className="mgfo-cardgrid">
      {items.map((a) => (
        <AchCard key={a.id} a={a} ladderName={ladderName} date={earnedAt[a.id]} skinsById={skinsById}
          reveal={reveal} onReplay={onReplay} />
      ))}
    </div>
  );
}

export default function FolioOverlay({ onClose }) {
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
    // Belt-and-suspenders with handleClose(): App.jsx's global Escape
    // handler unmounts this overlay directly (setOverlay(null)) without
    // going through onClose's own wrapper, so this is what actually
    // guarantees a still-open celebration moment gets dismissed on Escape.
    return () => {
      mountedRef.current = false;
      clearAllScr();
      if (replayHandleRef.current && replayHandleRef.current.dismiss) replayHandleRef.current.dismiss();
      replayHandleRef.current = null;
    };
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
  // invented toast). Locked/masked cards are wired to the same handler
  // (matching the DC's own cardBase) but no-op here.
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
  // Close (scrim / crumb / ✕ / Esc via App.jsx's onClose) clears every
  // in-flight scramble and resets reveal/toast so the next open starts clean.
  function handleClose() {
    clearAllScr();
    setReveal({});
    setActiveToast(null);
    if (replayHandleRef.current && replayHandleRef.current.dismiss) replayHandleRef.current.dismiss();
    replayHandleRef.current = null;
    onClose();
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

  const nothingFound = !!qlc && (
    (!showLadders || filteredActiveTiers.length === 0) &&
    (!showMilestones || filteredMilestones.length === 0) &&
    (!showMasteries || filteredMasteries.length === 0) &&
    (!showFeats || filteredFeats.length === 0)
  );

  return (
    <>
      <div className="mgv-scrim" onClick={handleClose} />
      <div className="mgv-host">
        <div className="mgv-slab mgfo-slab" role="dialog" aria-label="The Folio of Honors">
          <div className="mgfo-head">
            <div className="mgfo-crumb" onClick={handleClose} title="Back to the library — Esc closes the overlay">← Library</div>
            <div className="mgfo-div" />
            <div className="mgfo-label">🏆 The Folio of Honors</div>
            {/* Poke until it snaps -- 5 real, server-persisted pokes (shared
                with the classic Trophy Hall's own Ach.poke()) earns "Triggered"
                and reveals the pill below, permanently, for good. */}
            <div className="mgfo-nar-avatar" title="…" onClick={pokeNarrator} />
            {triggered && (
              <div className="mgfo-unleash" title="Toggle the narrator's unfiltered commentary"
                onClick={toggleUnleash}>
                <span className={"mgfo-unleash-dot" + (unleashed ? " on" : "")} />
                Unleash the AI
              </div>
            )}
            <div className="mgfo-spacer" />
            {vm && <div className="mgfo-index">record {fmt(vm.earnedNonFeat)} of {fmt(vm.totalNonFeat)}</div>}
            <div className="mgfo-search">
              <span className="mgfo-search-ic">⌕</span>
              <input type="text" placeholder="search the record…" value={q} onChange={onSearchChange} />
            </div>
            <button type="button" className="mgv-x" onClick={handleClose} aria-label="Close">×</button>
          </div>

          {!data && !err && <div className="mgh-loading">opening the record…</div>}
          {err && <div className="mgh-loading">couldn't load the Folio — {err}</div>}

          {data && vm && (
            <div className="mgfo-body">
              <div className="mgfo-main">
                <div className="mgfo-title-row">
                  <div className="mgfo-title-col">
                    <div className="mgfo-eyebrow">The Moonglade Athenaeum · honors of the house</div>
                    <div className="mgfo-h1">The Folio of Honors</div>
                    <div className="mgfo-rule" />
                  </div>
                  <div className="mgfo-stats-trio">
                    <div className="mgfo-stat">
                      <div className="mgfo-stat-lab">Points</div>
                      <div className="mgfo-stat-val gold">{fmt(data.earned_points)}</div>
                      <div className="mgfo-stat-sub">of {fmt(data.possible_points)}</div>
                    </div>
                    <div className="mgfo-stat">
                      <div className="mgfo-stat-lab">Earned</div>
                      <div className="mgfo-stat-val">{fmt(vm.earnedNonFeat)}</div>
                      <div className="mgfo-stat-sub">of {fmt(vm.totalNonFeat)} honors</div>
                    </div>
                    <div className="mgfo-stat">
                      <div className="mgfo-stat-lab feat">Feats</div>
                      <div className="mgfo-stat-val feat">{data.feats_revealed ? fmt(vm.earnedFeats) : "???"}</div>
                      <div className="mgfo-stat-sub">{data.feats_revealed ? "of " + fmt(vm.totalFeats) + " feats" : "cloaked"}</div>
                    </div>
                  </div>
                </div>

                <div className="mgfo-tabs">
                  <button type="button" className={"mgfo-tab" + (tab === "summary" ? " on" : "")} onClick={() => setTab("summary")}>Summary</button>
                  <button type="button" className={"mgfo-tab" + (tab === "all" ? " on" : "")} onClick={() => setTab("all")}>All</button>
                  <button type="button" className={"mgfo-tab" + (tab === "stats" ? " on" : "")} onClick={() => setTab("stats")}>Statistics</button>
                  {bucketFilter && (
                    <div className="mgfo-clearfilter" onClick={() => setBucketFilter(null)}>
                      {BUCKETS.find((b) => b.key === bucketFilter).label} ✕
                    </div>
                  )}
                  <div className="mgfo-flex1" />
                  <div className="mgfo-hint">feats stay cloaked until the first is earned</div>
                </div>

                {tab === "summary" && (
                  <div className="mgfo-grid2">
                    <div>
                      <div className="mgfo-sec-h"><b>Recently entered</b><span>the newest lines in the record</span></div>
                      <div className="mgfo-recent">
                        {vm.recent.length === 0 && <div className="mgfo-empty-mini">Nothing yet — go make something.</div>}
                        {vm.recent.map((a) => (
                          <div className={"mgfo-recrow mgfo-t-" + a.tier} key={a.id}>
                            <div className="mgfo-recico">
                              <img src={"/badge-thumb/" + encodeURIComponent(a.id) + ".png"} alt=""
                                onError={(e) => e.currentTarget.remove()} />
                            </div>
                            <div className="mgfo-rectxt">
                              <div className="mgfo-recnm">{a.name}</div>
                              <div className={"mgfo-recds" + revealMod(a, reveal)}>{commentary(a, reveal)}</div>
                            </div>
                            <div className="mgfo-recside">
                              <span className={"mgfo-pill mgfo-t-" + a.tier}>{a.tier}</span>
                              <div className="mgfo-recmeta">{earnedAt[a.id]}{a.points ? " · +" + a.points + " pts" : ""}</div>
                            </div>
                          </div>
                        ))}
                      </div>

                      <div className="mgfo-sec-h"><b>The ledger</b><span>how the record stands</span></div>
                      <div className="mgfo-ledger">
                        {vm.buckets.map((b) => {
                          const masked = b.key === "feat" && !data.feats_revealed;
                          const pct = b.total ? (b.earned / b.total) * 100 : 0;
                          return (
                            <div className="mgfo-progrow" key={b.key}>
                              <div className="mgfo-progrow-lab">{b.key === "feat" ? "Feats" : b.label}</div>
                              <Bar pct={masked ? 0 : pct} />
                              <div className="mgfo-progrow-ct">{masked ? "???" : fmt(b.earned) + "/" + fmt(b.total)}</div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                    <div>
                      <div className="mgfo-sec-h emerald"><b>Within reach</b><span>closest to the pen</span></div>
                      <div className="mgfo-reach">
                        {vm.withinReach.length === 0 && <div className="mgfo-empty-mini">Nothing left within reach — go finish the record.</div>}
                        {vm.withinReach.map((a) => (
                          <div className="mgfo-reachcard" key={a.id}>
                            <div className="mgfo-reachtop">
                              <b>{a.name}</b>
                              <span className="mgfo-reachnote">{fmt(a.current)} / {fmt(a.threshold)}</span>
                              <i className="mgfo-flex1" />
                              <span className="mgfo-reachpts">+{a.points} pts</span>
                            </div>
                            <Bar pct={a._ratio * 100} variant="reach" />
                          </div>
                        ))}
                      </div>

                      <div className="mgfo-sec-h emerald"><span className="mgfo-dot" /><b>Relics — earned rewards</b></div>
                      <div className="mgfo-relicnote">applied from the Control Panel; recorded here</div>
                      <div className="mgfo-relics">
                        {vm.relics.map((r) => (
                          <div className={"mgfo-relicrow" + (r.active ? " active" : r.earned ? " unlocked" : "")} key={r.id}>
                            <span className="mgfo-relicnm">{r.name}</span>
                            <i className="mgfo-flex1" />
                            <span className="mgfo-relicsub">{r.active ? "active" : r.earned ? "unlocked" : "🔒 locked"}</span>
                          </div>
                        ))}
                        <div className="mgfo-relicrow dim">
                          <span className="mgfo-relicnm-small">Banner</span>
                          <span className="mgfo-relicsub-txt">The Great Library</span>
                          <i className="mgfo-flex1" />
                          <span className="mgfo-relicsub">🔒 50k images</span>
                        </div>
                        <div className="mgfo-relicrow dim">
                          <span className="mgfo-relicnm-small">Icons</span>
                          <span className="mgfo-relicsub-txt">Feat sigils</span>
                          <i className="mgfo-flex1" />
                          <span className="mgfo-relicsub">🔒 any feat</span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {tab === "all" && (
                  <div className="mgfo-all">
                    {nothingFound && (
                      <div className="mgfo-nothingfound">
                        <div className="mgfo-nf-h">Nothing in the record</div>
                        <div className="mgfo-nf-sub">no honor answers "{q}" — the page waits.</div>
                      </div>
                    )}
                    {!qlc && bucketFilter === "feat" && vm.earnedFeats === 0 && (
                      <div className="mgfo-nothingfound">
                        <div className="mgfo-nf-h">Feats stay cloaked</div>
                        <div className="mgfo-nf-sub">earn your first one and this category opens up.</div>
                      </div>
                    )}

                    {showLadders && vm.ladders.length > 0 && (
                      <>
                        <div className="mgfo-sec-h">
                          <b>The ten tracks</b><span>pick a wing of the record</span>
                          <i className="mgfo-flex1" />
                          <span className="mgfo-count">{fmt(vm.buckets.find((b) => b.key === "ladder").earned)}/{fmt(vm.buckets.find((b) => b.key === "ladder").total)} rungs</span>
                        </div>
                        <div className="mgfo-laddergrid">
                          {vm.ladders.map((l) => {
                            const on = activeLadder && l.id === activeLadder.id;
                            return (
                              <div key={l.id} className={"mgfo-ladderbadge" + (on ? " on" : "") + (l.earnedCount ? "" : " zero")}
                                onClick={() => setActiveLadderId(l.id)}>
                                <div className="mgfo-lb-img">
                                  <img src={l.tiers[0] ? "/badge-thumb/" + encodeURIComponent(l.tiers[0].id) + ".png" : ""} alt=""
                                    onError={(e) => e.currentTarget.remove()} />
                                </div>
                                <div className="mgfo-lb-pips">
                                  {l.tiers.map((t) => <i key={t.id} className={t.earned ? "mgfo-t-" + t.tier : ""} />)}
                                </div>
                                <p className="mgfo-lb-name">{l.name}</p>
                              </div>
                            );
                          })}
                        </div>

                        {activeLadder && (
                          <>
                            <div className="mgfo-sec-h">
                              <b>{activeLadder.name}</b><span>measured in {activeLadder.metric}</span>
                              <i className="mgfo-flex1" />
                              <span className="mgfo-count">{activeLadder.earnedCount}/{activeLadder.totalCount}</span>
                            </div>
                            <CardGrid items={filteredActiveTiers} ladderName={activeLadder.name}
                              earnedAt={earnedAt} skinsById={vm.skinsById}
                              emptyLabel="No rung on this track answers the search."
                              reveal={reveal} onReplay={replayToast} />
                          </>
                        )}
                      </>
                    )}

                    {showMilestones && filteredMilestones.length > 0 && (
                      <>
                        <div className="mgfo-sec-h">
                          <b>Milestones</b><span>one-shot firsts</span>
                          <i className="mgfo-flex1" />
                          <span className="mgfo-count">{vm.buckets.find((b) => b.key === "milestone").earned}/{vm.buckets.find((b) => b.key === "milestone").total}</span>
                        </div>
                        <CardGrid items={filteredMilestones} earnedAt={earnedAt} skinsById={vm.skinsById}
                          reveal={reveal} onReplay={replayToast} />
                      </>
                    )}

                    {showMasteries && filteredMasteries.length > 0 && (
                      <>
                        <div className="mgfo-sec-h">
                          <b>Masteries</b><span>breadth over depth</span>
                          <i className="mgfo-flex1" />
                          <span className="mgfo-count">{vm.buckets.find((b) => b.key === "mastery").earned}/{vm.buckets.find((b) => b.key === "mastery").total}</span>
                        </div>
                        <CardGrid items={filteredMasteries} earnedAt={earnedAt} skinsById={vm.skinsById}
                          reveal={reveal} onReplay={replayToast} />
                      </>
                    )}

                    {showFeats && (
                      <>
                        <div className="mgfo-sec-h feat">
                          <b>Feats of the Athenaeum</b><span>no points — done for the glory. Cloaked until the first is earned.</span>
                          <i className="mgfo-flex1" />
                          <span className="mgfo-count feat">{vm.earnedFeats}/{vm.totalFeats}</span>
                        </div>
                        <CardGrid items={filteredFeats} earnedAt={earnedAt} skinsById={vm.skinsById}
                          reveal={reveal} onReplay={replayToast} />
                      </>
                    )}
                  </div>
                )}

                {tab === "stats" && (
                  <div className="mgfo-grid2 even">
                    <div>
                      <div className="mgfo-sec-h"><b>By rarity</b></div>
                      <div className="mgfo-statblock">
                        {vm.rarityRows.map((r) => (
                          <div className="mgfo-progrow" key={r.tier}>
                            <div className={"mgfo-progrow-lab mgfo-t-" + r.tier}>{r.tier}</div>
                            <Bar pct={r.total ? (r.earned / r.total) * 100 : 0} variant="rarity" tier={r.tier} />
                            <div className="mgfo-progrow-ct">{r.earned}/{r.total}</div>
                          </div>
                        ))}
                      </div>

                      <div className="mgfo-sec-h"><b>The buckets</b></div>
                      <div className="mgfo-statblock">
                        {vm.buckets.map((b) => {
                          const masked = b.key === "feat" && !data.feats_revealed;
                          return (
                            <div className="mgfo-progrow" key={b.key}>
                              <div className="mgfo-progrow-lab">{b.key === "feat" ? "Feats" : b.label}</div>
                              <Bar pct={masked ? 0 : (b.total ? (b.earned / b.total) * 100 : 0)} />
                              <div className="mgfo-progrow-ct">{masked ? "???" : fmt(b.earned) + "/" + fmt(b.total)}</div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                    <div>
                      <div className="mgfo-sec-h"><b>Ladder completion</b></div>
                      <div className="mgfo-statblock">
                        {vm.ladderRows.map((l) => (
                          <div className="mgfo-progrow" key={l.id}>
                            <div className="mgfo-progrow-lab wide">{l.name}</div>
                            <Bar pct={l.total ? (l.earned / l.total) * 100 : 0} />
                            <div className="mgfo-progrow-ct">{l.earned}/{l.total}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <div className="mgfo-rail">
                <div className="mgfo-rail-scroll">
                  <div>
                    <div className="mgfo-rail-h">Categories</div>
                    <div className="mgfo-catlist">
                      {vm.buckets.map((b) => {
                        const active = bucketFilter === b.key;
                        const masked = b.key === "feat" && !data.feats_revealed;
                        return (
                          <div key={b.key} className={"mgfo-catrow" + (active ? " on" : "")} onClick={() => toggleBucket(b.key)}>
                            <span className="mgfo-catlab">{b.label}</span>
                            <i className="mgfo-flex1" />
                            <span className="mgfo-catct">{masked ? "???" : fmt(b.earned) + "/" + fmt(b.total)}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                  <div className="mgfo-raildiv" />
                  <div className="mgfo-narrator">
                    <div className="mgfo-narrator-h"><span className="mgfo-dot" />The narrator</div>
                    {/* Rail portrait stays inert on purpose -- the DC only ever
                        wires the poke onto the small header avatar, never this one. */}
                    <img className="mgfo-narrator-img" src="/branding/mascots/gen_nel.png" alt="Nel, the Athenaeum archivist"
                      onError={(e) => e.currentTarget.remove()} />
                    <div className="mgfo-narrator-quote" title="she has opinions about your backlog">
                      "{NARRATOR_LINES[quoteIdx]}"
                    </div>
                  </div>
                </div>
                <div className="mgfo-rail-foot">
                  <b>Relics</b> apply from the <b>Control Panel</b> — recorded on the Summary page.
                </div>
              </div>
            </div>
          )}
        </div>
        {/* No React-rendered toast here on purpose: clicking an earned card
            plays the REAL celebration moment (Ach.replay(), in
            mg-notify.js -- badge sweep, mascot, ring pulse, chime, and the
            full confetti/star fanfare on legendary/feat) via replayToast()
            above. That moment lives in its own DOM node appended straight to
            document.body, outside this overlay's tree entirely -- the same
            place any other achievement unlock in this app shows up. */}
      </div>
    </>
  );
}
