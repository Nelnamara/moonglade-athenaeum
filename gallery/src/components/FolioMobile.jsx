import React, { useEffect, useRef, useState } from "react";
import useFolio, { NARRATOR_LINES, commentary, revealMod, fmt, displayBucket } from "../hooks/useFolio.js";
import MobileSheet from "./MobileSheet.jsx";
import { badgeSrc, badgeHop } from "../notify/badgeArt.js";
import "../styles/gallery-mobile.css";
import "../styles/folio-overlay.css";
import "../styles/folio-mobile.css";

/* The Folio of Honors -- MOBILE full-page destination. Data/narrator/
   glitch-reveal/replay engine is useFolio.js (gallery/src/hooks/), the
   EXACT SAME hook FolioOverlay.jsx (desktop) consumes -- one fetch of
   GET /api/achievements, one 34ms/26-tick scramble implementation, one
   window.Ach.replay() call site. This file is ONLY the mobile-specific
   chrome: the sticky top bar, hero header, segmented tabs, carousels, the
   single-card hero tier navigator, and the two bottom sheets -- matching
   this session's own useHealth/useMyArt/useContests/useImport split (a
   shared hook, a desktop Overlay, a mobile screen, never a second data
   layer). REUSES folio-overlay.css's tier-triad tokens (--tc/--tcl/--tcd,
   `.mgfo-t-*`) and its `.mgfo-glitch`/`.mgfo-settled`/pill classes verbatim
   (byte-for-byte, not redefined) -- see the import list above.

   ENTRY POINT: rendered by AppMobile.jsx as a fixed, full-viewport overlay
   (z above the hero AND the tab bar) when the hero's gold "🌙 Folio of
   Honors" icon is tapped -- replacing the "Its own mobile design file...
   coming later" toast that icon used to show. See AppMobile.jsx's own
   header comment for the folioOpen/openFolio/closeFolio wiring.

   WHY A DEDICATED FULL-SCREEN PRESENTATION, NOT MobileScreen.jsx: same
   reasoning as ImageDetailsMobile.jsx's own header comment -- this design's
   own top bar carries a back link, a title chip AND the narrator avatar (a
   three-part header, plus a whole hero+tabs layer below it) that
   MobileScreen's fixed back-chevron+title contract wasn't built for. Folio
   is also reached from the hero's OWN icon row, not the hamburger Menu
   sheet's six destinations -- one level up from every MobileScreen consumer.

   Pixel source of truth: design_handoff/design_handoff_moonglade_suite/
   "Folio Mobile.dc.html" (527 lines). Real-data deviations from that mock,
   disclosed here for the owner's review -- same standard every prior mobile
   surface this session used:

   1. REAL CELEBRATION / NARRATOR / GLITCH-REVEAL, ADDED: the design mock has
      NONE of these (confirmed absent by this build's own design research --
      no `pokes`/`triggered`/`unleashed`/`reveal`/`roast_nsfw` anywhere in the
      mock, `poke()` is a fake local quoteIdx bump). Per this session's own
      explicit direction, they are NOT dropped on mobile just because the mock
      predates them: tapping ANY earned row or Recently-entered card here
      fires the REAL window.Ach.replay() celebration (useFolio.js's
      replayToast(), the identical call desktop's AchCard makes -- verified
      live, see build notes) in addition to opening the mock's own static
      detail sheet; the header avatar AND the Nel-strip quote both call the
      REAL, server-persisted pokeNarrator() (POST /api/ach-event -- the SAME
      function desktop's header avatar uses, not the mock's decorative tap);
      and a small "Unleash the AI" pill (real, once `triggered`) sits under
      the hero stat line -- the one place in this layout with room for it.
   2. RECENTLY ENTERED: shows the SAME real, cross-type reverse-chronological
      merge (`vm.recent`, up to 6, by real earned_at) desktop already uses --
      not the mock's fixed "4 ladder tiers + 2 flat" split, which wasn't
      achieving true recency in the mock's own fabricated per-array demo data
      (it just reverse()'d two separate static arrays, never merge-sorted by
      date).
   3. DETAIL SHEET IMAGE: the REAL square badge -- badgeSrc(): the animated
      `/badge-thumb/<id>.webp` master when there is one, else the `.png` thumb
      (the same asset AchCard/the recent strip/every other badge image in this
      app already uses) -- object-fit:cover into the design's 1.6:1 frame, not
      the mock's own wide illustration path, which points at a per-item
      "hero art" file that doesn't exist anywhere on disk. Inventing pixels
      for an asset that isn't there is exactly what this codebase's own
      established rule (GalleryGridMobile.jsx's header comment) already
      rules out.
   4. RELIC SWATCHES: the real, already-shipped 4-hex-per-skin SKIN_SW table
      static/mg-notify.js's own classic Trophy Hall relic rows already use,
      copied byte-for-byte below -- not a new invented palette (desktop's
      own FolioOverlay.jsx doesn't render swatches at all, only name+status,
      so this is new to the Folio surfaces but real and shipped elsewhere).
   5. STAT LINE: the honors-total denominator only folds the real feat count
      in once `data.feats_revealed` is true (matching every other feats-
      masking spot in this app, including this same stat line's own "??? feats"
      neighbor) -- the mock's own formula summed the raw feat count into the
      denominator unconditionally, even while displaying "??? feats" right
      beside it, which isn't internally consistent once real cloaking rules
      apply.
   6. NARRATOR LINES: the full, real 6-line NARRATOR_LINES shared constant
      (useFolio.js -- the SAME array desktop's rail uses), not the mock's own
      4-line demo subset -- one narrator voice, one source of truth.
   7. SCOPED OUT (design has no room for them on these compact rows, matching
      AchCard's own scope on desktop's tighter card too): criteria checklists,
      skin-unlock/banner-reward flags. Real fields, just not exposed in this
      pass's row/sheet layout.

   MOUNT-RACE CHECK (explicit, per this session's own standing rule): the
   only mobile-local state added beyond useFolio.js is `tierIdx`/`sheetId`/
   `relicsOpen` -- plain UI state, no custom element, no DOM ref target. The
   hero tier navigator guards `tierIdx` with a modulo against the CURRENT
   ladder's tier count on every render (`tierIdxSafe` below, mirroring the
   design script's own `S.tierIdx % ladder.tiers.length`) rather than an
   effect that resets it on mount -- so a stale index from a prior ladder can
   never read out of bounds, and there is nothing here keyed to mount timing
   instead of data actually arriving. */

// Byte-for-byte from static/mg-notify.js's own Ach IIFE (`SKIN_SW`, ~line 519)
// -- the classic Trophy Hall's relic-row swatch colors, reused rather than a
// second, differently-invented palette. See point 4 above.
const SKIN_SW = {
  moonglade: ["#0c0a1c", "#b692e6", "#4fc99a", "#d4af37"],
  nightfallen: ["#0a0713", "#a678f0", "#7f6fe0", "#d9b3ff"],
  moonlit: ["#0b1018", "#8fb8e8", "#68d5e0", "#cfe1f5"],
  ember: ["#160c0c", "#e8935f", "#e0a94b", "#ffcf7a"],
  verdant: ["#0a1410", "#5fd39a", "#4fc99a", "#c8e6a8"],
};

// The sheet's own sub-line convention -- byte-for-byte the same three
// branches the design script's mkTierRow/mkFlatRow/mkFeatRow onClick
// handlers build, just reading REAL fields (earnedAt/threshold) instead of
// the mock's fabricated ones.
function subFor(a, earnedAt) {
  if (!a) return "";
  if (displayBucket(a) === "feat") return a.earned ? (earnedAt[a.id] || "") : "";
  if (a.earned) return earnedAt[a.id] || "";
  if (a.bucket === "ladder") return "not yet — " + fmt(a.threshold);
  return "not yet";
}

/* One achievement/tier row -- shared by the ladder list, Milestones,
   Masteries and Feats. Locked FEATS render as a separate, non-interactive
   branch (server already sanitizes a hidden feat's id/name/desc/icon before
   this ever sees it) -- everything else stays clickable whether earned or
   locked, matching mkTierRow/mkFlatRow's own onClick (fires either way). */
function Row({ a, ladderName, onOpen }) {
  const isFeat = displayBucket(a) === "feat";   // meta folds into feats; streak into masteries
  if (isFeat && !a.earned) {
    return (
      <div className="fm-row fm-row-featlocked">
        <span className="fm-row-gem" />
        <div className="fm-row-thumbwrap">
          <img src="/branding/mystery/secret_feat.png" alt="" draggable={false}
            onError={(e) => e.currentTarget.remove()} />
        </div>
        <div className="fm-row-textcol">
          <div className="fm-row-name">???</div>
          <div className="fm-row-meta">hidden until earned</div>
        </div>
        <div className="fm-row-rightcol center"><span className="fm-row-glyph">🔒</span></div>
      </div>
    );
  }
  const tierClass = "mgfo-t-" + (a.tier || "common");
  const meta = a.bucket === "ladder"
    ? (ladderName ? ladderName + " · " + fmt(a.threshold) : fmt(a.threshold))
    : isFeat ? "feat · no points"
    : a.bucket === "milestone" ? "milestone" : "mastery";
  return (
    <button type="button" className={"fm-row " + tierClass + (a.earned ? " earned" : " locked")}
      onClick={() => onOpen(a)}>
      <span className="fm-row-gem" />
      <div className="fm-row-thumbwrap">
        <img src={badgeSrc(a.id)} alt="" loading="lazy" draggable={false}
          onError={(e) => { if (!badgeHop(e.currentTarget, a.id)) e.currentTarget.remove(); }} />
        {!a.earned && <div className="fm-row-lock">🔒</div>}
      </div>
      <div className="fm-row-textcol">
        <div className="fm-row-name">{a.name}</div>
        <div className="fm-row-meta">{meta}</div>
      </div>
      {isFeat ? (
        <div className="fm-row-rightcol center"><span className="fm-row-glyph">✓</span></div>
      ) : (
        <div className="fm-row-rightcol">
          <span className="fm-row-pill">{a.tier}</span>
          <span className="fm-row-pts">{a.points ? "+" + a.points : ""}</span>
        </div>
      )}
    </button>
  );
}

export default function FolioMobile({ onClose }) {
  const folio = useFolio();
  const {
    data, err, vm, earnedAt,
    tab, setTab,
    bucketFilter, toggleBucket,
    activeLadder, setActiveLadderId,
    quoteIdx,
    triggered, unleashed, toggleUnleash,
    reveal,
    pokeNarrator, replayToast,
  } = folio;

  const [closing, setClosing] = useState(false);
  const [tierIdx, setTierIdx] = useState(0);

  const [sheetId, setSheetId] = useState(null);
  const [sheetClosing, setSheetClosing] = useState(false);
  const sheetTimer = useRef(null);

  const [relicsOpen, setRelicsOpen] = useState(false);
  const [relicsClosing, setRelicsClosing] = useState(false);
  const relicsTimer = useRef(null);

  useEffect(() => () => { clearTimeout(sheetTimer.current); clearTimeout(relicsTimer.current); }, []);

  // Tap an earned/locked (non-feat-locked) row or a Recently-entered card:
  // open the static detail sheet (design's own interaction) AND, for earned
  // achievements, fire the REAL celebration via useFolio's replayToast()
  // (a no-op for locked ones, guarded inside the hook) -- see point 1 above.
  function openDetail(a) {
    setSheetId(a.id);
    replayToast(a);
  }
  function closeSheet() {
    setSheetClosing(true);
    clearTimeout(sheetTimer.current);
    sheetTimer.current = setTimeout(() => { setSheetId(null); setSheetClosing(false); }, 280);
  }
  function openRelics() { setRelicsOpen(true); }
  function closeRelics() {
    setRelicsClosing(true);
    clearTimeout(relicsTimer.current);
    relicsTimer.current = setTimeout(() => { setRelicsOpen(false); setRelicsClosing(false); }, 280);
  }

  // Plays the exit fade before the real unmount, same overlay law every big
  // surface in this codebase follows (ImageDetailsMobile.jsx's own close()).
  // folio.close() runs synchronously right away (not deferred to the fade) --
  // it clears in-flight scrambles and dismisses any still-open celebration,
  // exactly matching FolioOverlay.jsx's own handleClose ordering.
  function handleClose() {
    folio.close();
    setClosing(true);
    setTimeout(onClose, 200);
  }

  const sheetAch = sheetId && vm ? vm.achievements.find((x) => x.id === sheetId) : null;
  const sheetIsFeat = sheetAch ? displayBucket(sheetAch) === "feat" : false;
  const sheetPts = sheetAch ? (sheetAch.points ? "+" + sheetAch.points + " pts" : (sheetIsFeat ? "for the glory" : "")) : "";

  const ladderTiers = activeLadder ? activeLadder.tiers : [];
  const tiersLen = ladderTiers.length;
  const tierIdxSafe = tiersLen ? ((tierIdx % tiersLen) + tiersLen) % tiersLen : 0;
  const tier = tiersLen ? ladderTiers[tierIdxSafe] : null;
  const prevTier = () => setTierIdx(tiersLen ? (tierIdxSafe - 1 + tiersLen) % tiersLen : 0);
  const nextTier = () => setTierIdx(tiersLen ? (tierIdxSafe + 1) % tiersLen : 0);
  const selectLadder = (id) => { setActiveLadderId(id); setTierIdx(0); };

  // Honors-total denominator: only folds the real feat count in once
  // feats_revealed, matching every other feats-masking spot -- point 5 above.
  const grandTotal = vm ? vm.totalNonFeat + (data.feats_revealed ? vm.totalFeats : 0) : 0;

  return (
    <div className={"fm-root" + (closing ? " closing" : "")} role="dialog" aria-modal="true" aria-label="The Folio of Honors">
      <div className="fm-topbar">
        <button type="button" className="fm-back" onClick={handleClose}>← Gallery</button>
        <div className="fm-fill" />
        <div className="fm-titlechip">🏆 Folio</div>
        <div className="fm-fill" />
        {/* Poke until it snaps -- 5 real, server-persisted pokes (the SAME
            /api/ach-event narrator_pokes counter the classic Trophy Hall's
            Ach.poke() and desktop's own header avatar use) earns "Triggered"
            and reveals the Unleash pill below, permanently, for good. */}
        <button type="button" className="fm-avatar" title="…" onClick={pokeNarrator} aria-label="Poke the narrator">
          <span className="fm-avatar-dot" />
        </button>
      </div>

      {!data && !err && <div className="fm-loading">opening the record…</div>}
      {err && <div className="fm-loading">couldn't load the Folio — {err}</div>}

      {data && vm && (
        <div className="fm-scroll">
          <div className="fm-hero">
            <div className="fm-kicker">THE MOONGLADE ATHENAEUM</div>
            <div className="fm-h1">The Folio of Honors</div>
            <div className="fm-rulewrap"><div className="fm-rule" /></div>
            <div className="fm-statline">
              {fmt(data.earned_points)} pts · {fmt(vm.earnedNonFeat)}/{fmt(grandTotal)} honors ·{" "}
              {data.feats_revealed ? fmt(vm.earnedFeats) : "???"} feats
            </div>
            {triggered && (
              <div className="fm-unleash" onClick={toggleUnleash} title="Toggle the narrator's unfiltered commentary">
                <span className={"fm-unleash-dot" + (unleashed ? " on" : "")} />
                <span className="fm-unleash-label">Unleash the AI</span>
              </div>
            )}
          </div>

          <div className="fm-tabsrow">
            <button type="button" className={"fm-tab" + (tab === "summary" ? " on" : "")} onClick={() => setTab("summary")}>Summary</button>
            <button type="button" className={"fm-tab" + (tab === "all" ? " on" : "")} onClick={() => setTab("all")}>All</button>
            <button type="button" className={"fm-tab" + (tab === "stats" ? " on" : "")} onClick={() => setTab("stats")}>Statistics</button>
          </div>

          <div className="fm-body">
            {tab === "summary" && (
              <div>
                <div className="fm-sech"><b>Recently entered</b><span>newest first</span></div>
                <div className="fm-hscroll">
                  {vm.recent.length === 0 && <div className="fm-empty">Nothing yet — go make something.</div>}
                  {vm.recent.map((a) => (
                    <button type="button" className="fm-reccard" key={a.id} onClick={() => openDetail(a)}>
                      <div className="fm-reccard-imgwrap">
                        <img src={badgeSrc(a.id)} alt="" loading="lazy" draggable={false}
                          onError={(e) => { if (!badgeHop(e.currentTarget, a.id)) e.currentTarget.remove(); }} />
                      </div>
                      <div className="fm-reccard-name">{a.name}</div>
                    </button>
                  ))}
                </div>

                <div className="fm-sech"><b>The ledger</b></div>
                <div className="fm-ledgerbox">
                  {vm.buckets.map((b) => {
                    const masked = b.key === "feat" && !data.feats_revealed;
                    const pct = b.total ? (b.earned / b.total) * 100 : 0;
                    return (
                      <div className="fm-progrow" key={b.key}>
                        <div className="fm-progrow-lab">{b.key === "feat" ? "Feats" : b.label}</div>
                        <div className="fm-bartrack"><i style={{ width: (masked ? 0 : pct) + "%" }} /></div>
                        <div className="fm-progrow-ct">{masked ? "???" : fmt(b.earned) + "/" + fmt(b.total)}</div>
                      </div>
                    );
                  })}
                </div>

                <div className="fm-sech emerald"><b>Within reach</b></div>
                {vm.withinReach.length === 0 && <div className="fm-empty">Nothing left within reach — go finish the record.</div>}
                {vm.withinReach.map((a) => (
                  <div className="fm-reachcard" key={a.id}>
                    <div className="fm-reachtop">
                      <b>{a.name}</b>
                      <span className="fm-reachnote">{fmt(a.current)} / {fmt(a.threshold)}</span>
                      <span style={{ flex: 1 }} />
                      <span className="fm-reachpts">+{a.points} pts</span>
                    </div>
                    <div className="fm-bartrack"><i className="reach" style={{ width: (a._ratio * 100) + "%" }} /></div>
                  </div>
                ))}

                <div className="fm-sech"><b>Relics</b><span>from the Control Panel</span></div>
                <div className="fm-relicnote">tap to see the full list</div>
                <div className="fm-hscroll" onClick={openRelics} role="button" tabIndex={0}
                  onKeyDown={(e) => { if (e.key === "Enter") openRelics(); }}>
                  {vm.relics.map((r) => (
                    <div className={"fm-relicchip" + (r.earned ? "" : " dim")} key={r.id}>
                      <div className="fm-relicsw">
                        {(SKIN_SW[r.id] || []).map((c, i) => <i key={i} style={{ background: c }} />)}
                      </div>
                      <div className="fm-relicchip-name">{r.name}</div>
                    </div>
                  ))}
                </div>

                <div className="fm-nelstrip">
                  <div className="fm-nelimg" />
                  <button type="button" className="fm-nelquote" onClick={pokeNarrator}>
                    "{NARRATOR_LINES[quoteIdx]}"
                  </button>
                </div>
              </div>
            )}

            {tab === "all" && (
              <div>
                <div className="fm-chipsrow">
                  {vm.buckets.map((b) => {
                    const active = bucketFilter === b.key;
                    const masked = b.key === "feat" && !data.feats_revealed;
                    const label = b.key === "feat" ? "Feats" : b.label.replace(" Ladders", "");
                    return (
                      <button type="button" key={b.key} className={"fm-chip" + (active ? " on" : "")}
                        onClick={() => toggleBucket(b.key)}>
                        {label} <span className="fm-chip-ct">{masked ? "???" : fmt(b.earned) + "/" + fmt(b.total)}</span>
                      </button>
                    );
                  })}
                </div>

                {folio.showLadders && vm.ladders.length > 0 && (
                  <>
                    <div className="fm-hscroll">
                      {vm.ladders.map((l) => {
                        const on = activeLadder && l.id === activeLadder.id;
                        return (
                          <button type="button" key={l.id} className={"fm-laddericon" + (on ? " on" : "") + (l.earnedCount ? "" : " zero")}
                            onClick={() => selectLadder(l.id)}>
                            <div className="fm-laddericon-tile">
                              <img src={l.tiers[0] ? badgeSrc(l.tiers[0].id) : ""} alt="" loading="lazy"
                                draggable={false} onError={(e) => { if (!(l.tiers[0] && badgeHop(e.currentTarget, l.tiers[0].id))) e.currentTarget.remove(); }} />
                            </div>
                            <div className="fm-laddericon-lab">{l.name}</div>
                          </button>
                        );
                      })}
                    </div>

                    {activeLadder && tier && (
                      <div className={"fm-herowrap mgfo-t-" + (tier.tier || "common")}>
                        <div className="fm-herokicker">
                          {activeLadder.name} · rung {tierIdxSafe + 1}/{tiersLen} · {activeLadder.earnedCount} earned
                        </div>
                        <div className={"fm-herobadgewrap" + (tier.earned ? " earned" : "")}>
                          <img className="fm-heroimg" src={badgeSrc(tier.id)} alt="" loading="lazy"
                            draggable={false} onError={(e) => { if (!badgeHop(e.currentTarget, tier.id)) e.currentTarget.remove(); }} />
                          {tier.earned && <div className="fm-herocheck">✓</div>}
                        </div>
                        <div className="fm-heronavrow">
                          <button type="button" className="fm-heroarrow" onClick={prevTier} aria-label="Previous tier">‹</button>
                          <div className="fm-heropipsrow">
                            {ladderTiers.map((t, i) => (
                              <button type="button" key={t.id}
                                className={"fm-heropip" + (i === tierIdxSafe ? " on" : (t.earned ? " earned" : ""))}
                                onClick={() => setTierIdx(i)} aria-label={t.name} />
                            ))}
                          </div>
                          <button type="button" className="fm-heroarrow" onClick={nextTier} aria-label="Next tier">›</button>
                        </div>
                        <div className="fm-heroname">{tier.name}</div>
                        <div className="fm-herodesc">{tier.earned ? (tier.roast || tier.desc) : tier.desc}</div>
                        <div className="fm-herometarow">
                          <span className="fm-row-pill">{tier.tier}</span>
                          <span className="fm-heropts">+{tier.points} pts</span>
                        </div>
                        <div className="fm-herosubmeta">
                          {fmt(tier.threshold)} · {tier.earned ? (earnedAt[tier.id] || "") : "not yet"}
                        </div>
                      </div>
                    )}

                    <div className="fm-sech"><b>{activeLadder ? activeLadder.name : ""}</b>
                      <span>{activeLadder ? activeLadder.earnedCount + "/" + activeLadder.totalCount : ""}</span>
                    </div>
                    <div className="fm-listcol">
                      {folio.filteredActiveTiers.map((t) => (
                        <Row key={t.id} a={t} ladderName={activeLadder ? activeLadder.name : ""} onOpen={openDetail} />
                      ))}
                    </div>
                  </>
                )}

                {folio.showMilestones && folio.filteredMilestones.length > 0 && (
                  <>
                    <div className="fm-sech"><b>Milestones</b>
                      <span>{vm.buckets.find((b) => b.key === "milestone").earned}/{vm.buckets.find((b) => b.key === "milestone").total}</span>
                    </div>
                    <div className="fm-listcol">
                      {folio.filteredMilestones.map((a) => <Row key={a.id} a={a} onOpen={openDetail} />)}
                    </div>
                  </>
                )}

                {folio.showMasteries && folio.filteredMasteries.length > 0 && (
                  <>
                    <div className="fm-sech"><b>Masteries</b>
                      <span>{vm.buckets.find((b) => b.key === "mastery").earned}/{vm.buckets.find((b) => b.key === "mastery").total}</span>
                    </div>
                    <div className="fm-listcol">
                      {folio.filteredMasteries.map((a) => <Row key={a.id} a={a} onOpen={openDetail} />)}
                    </div>
                  </>
                )}

                {folio.showFeats && (
                  <>
                    <div className="fm-sech feat"><b>Feats</b>
                      <span className="fm-count feat">{vm.earnedFeats}/{vm.totalFeats}</span>
                    </div>
                    <div className="fm-listcol">
                      {folio.filteredFeats.map((a) => <Row key={a.id} a={a} onOpen={openDetail} />)}
                    </div>
                  </>
                )}
              </div>
            )}

            {tab === "stats" && (
              <div>
                <div className="fm-sech"><b>By rarity</b></div>
                <div className="fm-ledgerbox">
                  {vm.rarityRows.map((r) => (
                    <div className={"fm-progrow mgfo-t-" + r.tier} key={r.tier}>
                      <div className="fm-progrow-lab" style={{ color: "var(--tc)" }}>{r.tier}</div>
                      <div className="fm-bartrack"><i className="rarity" style={{ width: (r.total ? (r.earned / r.total) * 100 : 0) + "%" }} /></div>
                      <div className="fm-progrow-ct">{r.earned}/{r.total}</div>
                    </div>
                  ))}
                </div>

                <div className="fm-sech"><b>Buckets</b></div>
                <div className="fm-ledgerbox">
                  {vm.buckets.map((b) => {
                    const masked = b.key === "feat" && !data.feats_revealed;
                    return (
                      <div className="fm-progrow" key={b.key}>
                        <div className="fm-progrow-lab">{b.key === "feat" ? "Feats" : b.label}</div>
                        <div className="fm-bartrack"><i style={{ width: (masked ? 0 : (b.total ? (b.earned / b.total) * 100 : 0)) + "%" }} /></div>
                        <div className="fm-progrow-ct">{masked ? "???" : fmt(b.earned) + "/" + fmt(b.total)}</div>
                      </div>
                    );
                  })}
                </div>

                <div className="fm-sech"><b>Ladder completion</b></div>
                <div className="fm-ledgerbox">
                  {vm.ladderRows.map((l) => (
                    <div className="fm-progrow" key={l.id}>
                      <div className="fm-progrow-lab wide">{l.name}</div>
                      <div className="fm-bartrack"><i style={{ width: (l.total ? (l.earned / l.total) * 100 : 0) + "%" }} /></div>
                      <div className="fm-progrow-ct">{l.earned}/{l.total}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Detail sheet -- design's own per-row tap target. Its description
          reads live off `reveal[id]` (commentary/revealMod, from
          useFolio.js) so the SAME glitch-scramble that drives the real
          celebration also updates this sheet's text in lockstep, exactly
          like desktop's AchCard. No custom/duplicate celebration renders
          here -- the real one lives in its own DOM node on document.body
          (mg-notify.js), entirely outside this sheet. */}
      <MobileSheet open={!!sheetId} closing={sheetClosing} onClose={closeSheet} title="">
        {sheetAch && (
          <div className={"mgfo-t-" + (sheetAch.tier || "common")}>
            <div className={"fm-sheet-imgwrap" + (sheetAch.earned ? " earned" : "")}>
              <img src={badgeSrc(sheetAch.id)} alt="" loading="lazy" draggable={false}
                onError={(e) => { if (!badgeHop(e.currentTarget, sheetAch.id)) e.currentTarget.remove(); }} />
            </div>
            <div className="fm-sheet-name">{sheetAch.name}</div>
            <div className="fm-sheet-metarow">
              <span className="fm-row-pill">{sheetIsFeat ? "feat" : sheetAch.tier}</span>
              <span className="fm-sheet-pts">{sheetPts}</span>
            </div>
            <div className={"fm-sheet-desc" + revealMod(sheetAch, reveal)}>{commentary(sheetAch, reveal)}</div>
            <div className="fm-sheet-sub">{subFor(sheetAch, earnedAt)}</div>
            <button type="button" className="fm-sheet-closebtn" onClick={closeSheet}>Close</button>
          </div>
        )}
      </MobileSheet>

      {/* Relics sheet -- the FULL list (Summary's carousel only fits what
          scrolls into view); real skin data throughout (name/desc/active/
          earned), swatches from the byte-for-byte SKIN_SW table above. */}
      <MobileSheet open={relicsOpen} closing={relicsClosing} onClose={closeRelics} title="Relics — earned rewards">
        {vm && vm.relics.map((r) => (
          <div className="fm-relicrow" key={r.id}>
            <div className="fm-relicrow-sw">
              {(SKIN_SW[r.id] || []).map((c, i) => <i key={i} style={{ background: c }} />)}
            </div>
            <div className="fm-relicrow-textcol">
              <div className={"fm-relicrow-name" + (r.active ? " active" : "")}>{r.name}</div>
              <div className="fm-relicrow-desc">{r.desc}</div>
            </div>
            <div className={"fm-relicrow-sub" + (r.active ? " active" : "")}>
              {r.active ? "active" : r.earned ? "unlocked" : "🔒 locked"}
            </div>
          </div>
        ))}
        <button type="button" className="fm-sheet-closebtn" onClick={closeRelics}>Close</button>
      </MobileSheet>
    </div>
  );
}
