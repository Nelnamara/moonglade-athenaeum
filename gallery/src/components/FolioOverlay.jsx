import React, { useState } from "react";
import "../styles/overlays.css";
import "../styles/folio-overlay.css";
import useFolio, { BUCKETS, NARRATOR_LINES, commentary, revealMod, fmt, displayBucket } from "../hooks/useFolio.js";
import useHealth from "../hooks/useHealth.js";
import useScrollLock from "../hooks/useScrollLock.js";

/* The Folio of Honors -- the seventh designed nav overlay to port, opened from
   Banner.jsx's gold "🏆 Folio" button (App.jsx's onFolio -> openOverlay("folio"),
   already wired). Data/narrator/glitch-reveal/replay engine lives in
   useFolio.js (gallery/src/hooks/), lifted out 2026-08-03 -- the SAME hook the
   new mobile Folio screen (FolioMobile.jsx) now consumes, so there is ONE
   fetch of GET /api/achievements, ONE 34ms/26-tick scramble implementation,
   ONE window.Ach.replay() call site, never a second drifting copy. This file
   keeps ONLY the desktop-specific chrome: the mgv-scrim/mgv-host/mgv-slab
   modal shell, the tab bar, right rail, AchCard/CardGrid/Bar presentational
   markup, and local search -- none of which the mobile screen shares (see
   useFolio.js's own header comment on why the split lands exactly there).

   Pixel source of truth: design_handoff/design_handoff_moonglade_suite/
   "Folio of Honors.dc.html" (988 lines) + folio-glitch-spec.md. The DC's own
   "trophy-data.js" mock module does NOT exist in this repo -- buildViewModel()
   (useFolio.js) derives the same shape (ladders grouped by track, buckets,
   recent, within-reach, relics, rarity/ladder stats) from the REAL flat
   achievements array instead. The DC's "rarity" vocabulary IS this app's real
   "tier" field (common/rare/epic/legendary/feat) -- same concept, not remapped.

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
   of truth. See useFolio.js's runScramble/rerunToast/replayToast for the
   exact 34ms/26-tick algorithm, copied from the DC's own _runScramble. */

// Byte-for-byte from static/mg-notify.js's own Ach IIFE (`SKIN_SW`, ~line 11225) --
// the classic Trophy Hall's relic-row swatch colors, the SAME table FolioMobile.jsx
// already carries (that file's own header comment, point 4) -- not a second,
// differently-invented palette.
const SKIN_SW = {
  moonglade: ["#0c0a1c", "#b692e6", "#4fc99a", "#d4af37"],
  nightfallen: ["#0a0713", "#a678f0", "#7f6fe0", "#d9b3ff"],
  moonlit: ["#0b1018", "#8fb8e8", "#68d5e0", "#cfe1f5"],
  ember: ["#160c0c", "#e8935f", "#e0a94b", "#ffcf7a"],
  verdant: ["#0a1410", "#5fd39a", "#4fc99a", "#c8e6a8"],
};

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
  const isFeat = displayBucket(a) === "feat";   // meta folds into feats (no points, "for the glory")
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

// spanWrap: the DC's own tierCard/flatCard helper (wrapStyle/innerStyle) --
// a trailing ODD card spans both grid columns and centers at half width,
// instead of stretching full-width alone on its own row.
function CardGrid({ items, ladderName, earnedAt, skinsById, emptyLabel, reveal, onReplay }) {
  if (!items.length) return emptyLabel ? <div className="mgfo-empty-mini">{emptyLabel}</div> : null;
  return (
    <div className="mgfo-cardgrid">
      {items.map((a, i) => {
        const lastOdd = items.length % 2 !== 0 && i === items.length - 1;
        return (
          <div key={a.id} className={"mgfo-card-wrap" + (lastOdd ? " last-odd" : "")}>
            <AchCard a={a} ladderName={ladderName} date={earnedAt[a.id]} skinsById={skinsById}
              reveal={reveal} onReplay={onReplay} />
          </div>
        );
      })}
    </div>
  );
}

export default function FolioOverlay({ onClose }) {
  useScrollLock();   // page never scrolls behind a full-screen panel (2026-08-06)
  const {
    data, err, vm, earnedAt,
    tab, setTab, q, onSearchChange,
    bucketFilter, toggleBucket, setBucketFilter,
    activeLadder, setActiveLadderId,
    quoteIdx,
    triggered, unleashed, toggleUnleash,
    reveal,
    pokeNarrator, replayToast, close,
    showLadders, showMilestones, showMasteries, showFeats,
    filteredActiveTiers, filteredMilestones, filteredMasteries, filteredFeats, nothingFound,
    filteredLadderGroups, showGroups, groupedTierCount,
  } = useFolio();

  // Close (scrim / crumb / ✕ / Esc via App.jsx's global handler) clears every
  // in-flight scramble and resets reveal/toast (useFolio's own close()) so
  // the next open starts clean, THEN calls the onClose prop -- WHAT happens
  // next (unmounting this overlay) is this component's own presentation
  // decision, per useFolio.js's documented split.
  function handleClose() {
    close();
    onClose();
  }

  // Hero tier carousel (the plinth), Folio of Honors.dc.html lines 219-271.
  // Local UI-only position state, matching FolioMobile.jsx's own tierIdx
  // precedent (not shared data, so it doesn't belong in useFolio.js).
  const [tierIdx, setTierIdx] = useState(0);
  const ladderTiers = activeLadder ? activeLadder.tiers : [];
  const tiersLen = ladderTiers.length;
  const tierIdxSafe = tiersLen ? ((tierIdx % tiersLen) + tiersLen) % tiersLen : 0;
  const carTier = tiersLen ? ladderTiers[tierIdxSafe] : null;
  const prevTier = () => setTierIdx(tiersLen ? (tierIdxSafe - 1 + tiersLen) % tiersLen : 0);
  const nextTier = () => setTierIdx(tiersLen ? (tierIdxSafe + 1) % tiersLen : 0);
  const selectLadder = (id) => { setActiveLadderId(id); setTierIdx(0); };

  // Feats-total denominator: only folds the real feat count in once
  // data.feats_revealed (== "any feat earned"), matching FolioMobile.jsx's
  // own grandTotal (that file's header comment, point 5). Desktop previously
  // never added it back in (vm.totalNonFeat alone), permanently excluding
  // feats from these two header numbers even after the first was earned.
  const grandTotal = vm ? vm.totalNonFeat + (data && data.feats_revealed ? vm.totalFeats : 0) : 0;

  // Statistics tab, owner-requested addition (not in the DC mock): more of
  // the real collection data already computed for Health, reused rather
  // than a second fetch/derivation. Library size + Coverage render as stat
  // tiles (Health's own .mgh-stats/.mgh-stat, already global via
  // overlays.css) specifically so they read differently from the bar rows
  // already on this tab (By rarity/The buckets/Ladder completion) --
  // point values aren't comparative, so they don't get a bar.
  const { h, stats: healthStats, monthMax, modelMax } = useHealth();
  const LIBRARY_LABELS = ["Images on disk", "Storage used", "Catalog rows"];
  const COVERAGE_LABELS = ["Full-meta", "Model known", "Uncataloged"];
  const libraryStats = healthStats.filter((s) => LIBRARY_LABELS.includes(s.label));
  const coverageStats = healthStats.filter((s) => COVERAGE_LABELS.includes(s.label));

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
            {vm && <div className="mgfo-index">record {fmt(vm.earnedNonFeat)} of {fmt(grandTotal)}</div>}
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
                      <div className="mgfo-stat-sub">of {fmt(grandTotal)} honors</div>
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
                      <div className="mgfo-sec-h"><b>Recently Earned</b><span>the newest lines in the record</span></div>
                      <div className="mgfo-recent">
                        {vm.recent.length === 0 && <div className="mgfo-empty-mini">Nothing yet — go make something.</div>}
                        {vm.recent.map((a) => (
                          <div className={"mgfo-recrow mgfo-t-" + a.tier} key={a.id} onClick={() => replayToast(a)}>
                            <span className="mgfo-recrow-gem" aria-hidden="true" />
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
                            <div className="mgfo-relic-sw">
                              {(SKIN_SW[r.id] || SKIN_SW.moonglade).map((c, i) => <span key={i} style={{ background: c }} />)}
                            </div>
                            <span className="mgfo-relicnm">{r.name}</span>
                            <i className="mgfo-flex1" />
                            <span className="mgfo-relicsub">{r.active ? "active" : r.earned ? "unlocked" : "🔒 locked"}</span>
                            <div className="mgfo-relic-tip">
                              <p className="mgfo-relic-tip-nm">{r.name}</p>
                              <p className="mgfo-relic-tip-ds">{r.desc}</p>
                            </div>
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
                        <div className="mgfo-relic-secret">…and one the Athenaeum keeps to itself.</div>
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
                    {!q.trim() && bucketFilter === "feat" && vm.earnedFeats === 0 && (
                      <div className="mgfo-nothingfound">
                        <div className="mgfo-nf-h">Feats stay cloaked</div>
                        <div className="mgfo-nf-sub">earn your first one and this category opens up.</div>
                      </div>
                    )}

                    {showLadders && vm.ladders.length > 0 && (
                      <>
                        {activeLadder && carTier && (
                          <div className={"mgfo-plinth-row mgfo-t-" + (carTier.tier || "common")}>
                            <div className="mgfo-plinth-col">
                              <div className="mgfo-plinth" onClick={() => replayToast(carTier)}>
                                <div className="mgfo-plinth-inset" />
                                <div className="mgfo-plinth-float">
                                  <div className={"mgfo-plinth-badge" + (carTier.earned ? " earned" : "")}>
                                    <img src={"/badge-thumb/" + encodeURIComponent(carTier.id) + ".png"} alt=""
                                      draggable={false} onError={(e) => e.currentTarget.remove()} />
                                  </div>
                                </div>
                                <div className="mgfo-plinth-glow" />
                              </div>
                              <div className="mgfo-plinth-navrow">
                                <button type="button" className="mgfo-plinth-arrow" onClick={prevTier}>‹ Prev</button>
                                <div className="mgfo-plinth-pips">
                                  {ladderTiers.map((t, i) => (
                                    <button type="button" key={t.id}
                                      className={"mgfo-plinth-pip" + (i === tierIdxSafe ? " on" : (t.earned ? " earned" : ""))}
                                      onClick={() => setTierIdx(i)} aria-label={t.name} />
                                  ))}
                                </div>
                                <button type="button" className="mgfo-plinth-arrow" onClick={nextTier}>Next ›</button>
                              </div>
                            </div>
                            <div className="mgfo-plinth-detailcol">
                              <div className="mgfo-plinth-eyebrow">
                                {activeLadder.name} · rung {tierIdxSafe + 1} of {tiersLen} · {activeLadder.earnedCount} earned
                              </div>
                              <div className="mgfo-plinth-name">{carTier.name}</div>
                              <div className="mgfo-plinth-rule" />
                              <div className="mgfo-plinth-desc">{carTier.desc}</div>
                              <div className="mgfo-plinth-facts">
                                <div className="mgfo-plinth-fact">
                                  <span className="mgfo-plinth-fact-lab">Rarity</span>
                                  <span className="mgfo-pill">{carTier.tier}</span>
                                </div>
                                <div className="mgfo-plinth-fact">
                                  <span className="mgfo-plinth-fact-lab">Reward</span>
                                  <span className="mgfo-plinth-fact-gold">+{carTier.points} points</span>
                                </div>
                                <div className="mgfo-plinth-fact">
                                  <span className="mgfo-plinth-fact-lab">Threshold</span>
                                  <span className="mgfo-plinth-fact-val">{fmt(carTier.threshold)}</span>
                                </div>
                                <div className="mgfo-plinth-fact last">
                                  <span className="mgfo-plinth-fact-lab">Entered</span>
                                  <span className={"mgfo-plinth-fact-entered" + (carTier.earned ? " earned" : "")}>
                                    {carTier.earned && earnedAt[carTier.id] ? earnedAt[carTier.id] : "not yet — the page waits"}
                                  </span>
                                </div>
                              </div>
                            </div>
                          </div>
                        )}

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
                                onClick={() => selectLadder(l.id)}>
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

                        {showGroups && (
                          <>
                            <div className="mgfo-sec-h">
                              <b>Every rung, every ladder</b>
                              <i className="mgfo-flex1" />
                              <span className="mgfo-count">{groupedTierCount} rungs</span>
                            </div>
                            <div className="mgfo-groups">
                              {filteredLadderGroups.map((l) => (
                                <div key={l.id} className="mgfo-group">
                                  <div className="mgfo-group-h">
                                    <img className="mgfo-group-icon"
                                      src={l.tiers[0] ? "/badge-thumb/" + encodeURIComponent(l.tiers[0].id) + ".png" : ""}
                                      alt="" onError={(e) => e.currentTarget.remove()} />
                                    <span className="mgfo-group-name">{l.name} — measured in {l.metric}</span>
                                    <span className="mgfo-group-count">
                                      {l.filteredTiers.filter((t) => t.earned).length}/{l.filteredTiers.length}
                                    </span>
                                    <div className="mgfo-group-rule" />
                                  </div>
                                  <CardGrid items={l.filteredTiers} ladderName={l.name}
                                    earnedAt={earnedAt} skinsById={vm.skinsById}
                                    reveal={reveal} onReplay={replayToast} />
                                </div>
                              ))}
                            </div>
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
                            {l.iconTierId && (
                              <img className="mgfo-progrow-ico" src={"/badge-thumb/" + encodeURIComponent(l.iconTierId) + ".png"} alt=""
                                onError={(e) => e.currentTarget.remove()} />
                            )}
                            <div className="mgfo-progrow-lab wide">{l.name}</div>
                            <Bar pct={l.total ? (l.earned / l.total) * 100 : 0} />
                            <div className="mgfo-progrow-ct">{l.earned}/{l.total}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}

                {tab === "stats" && h && (
                  <div className="mgfo-stats-extra">
                    <div className="mgfo-sec-h"><b>Library</b><span>the raw numbers</span></div>
                    <div className="mgh-stats">
                      {libraryStats.map((s) => (
                        <div className="mgh-stat" key={s.label}>
                          <div className="mgh-stat-label">{s.label}</div>
                          <div className="mgh-stat-value">{s.value}</div>
                        </div>
                      ))}
                    </div>

                    <div className="mgfo-sec-h"><b>Coverage</b><span>how complete the catalog is</span></div>
                    <div className="mgh-stats">
                      {coverageStats.map((s) => (
                        <div className="mgh-stat" key={s.label}>
                          <div className="mgh-stat-label">{s.label}</div>
                          <div className={"mgh-stat-value" + (s.gold ? " gold" : "")}>{s.value}</div>
                        </div>
                      ))}
                    </div>

                    <div className="mgfo-grid2 even">
                      <div>
                        <div className="mgfo-sec-h"><b>Top models</b></div>
                        <div className="mgfo-statblock">
                          {(h.top_models || []).map(([label, count]) => (
                            <div className="mgfo-progrow" key={label}>
                              <div className="mgfo-progrow-lab wide" title={label}>{label}</div>
                              <Bar pct={Math.max(0.5, (count / modelMax) * 100)} />
                              <div className="mgfo-progrow-ct">{fmt(count)}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                      <div>
                        <div className="mgfo-sec-h"><b>Monthly activity</b></div>
                        <div className="mgfo-statblock">
                          {(h.by_month || []).map(([label, count]) => (
                            <div className="mgfo-progrow" key={label}>
                              <div className="mgfo-progrow-lab wide">{label}</div>
                              <Bar pct={Math.max(0.5, (count / monthMax) * 100)} />
                              <div className="mgfo-progrow-ct">{fmt(count)}</div>
                            </div>
                          ))}
                        </div>
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
                    {/* Rail portrait also pokes now -- the same real
                        pokeNarrator() the header avatar uses, per owner
                        direction (the DC's own mock never wired this one,
                        but there's no reason the bigger portrait shouldn't
                        answer a click too). */}
                    <img className="mgfo-narrator-img poke" src="/branding/mascots/nel_narrator.png" alt="Nel, the Athenaeum archivist"
                      onClick={pokeNarrator} onError={(e) => e.currentTarget.remove()} />
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
