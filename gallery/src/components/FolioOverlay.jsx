import React from "react";
import "../styles/overlays.css";
import "../styles/folio-overlay.css";
import useFolio, { BUCKETS, NARRATOR_LINES, commentary, revealMod, fmt } from "../hooks/useFolio.js";

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
                    {!q.trim() && bucketFilter === "feat" && vm.earnedFeats === 0 && (
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
