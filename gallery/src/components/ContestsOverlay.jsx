import React, { useState } from "react";
import useContests, { fmt } from "../hooks/useContests.js";
import "../styles/overlays.css";
import "../styles/myart-contests.css";
import useScrollLock from "../hooks/useScrollLock.js";
import ContestDetail from "./ContestDetail.jsx";
import ContestMyEntries from "./ContestMyEntries.jsx";
import ContestPicker from "./ContestPicker.jsx";
import ContestConfirm from "./ContestConfirm.jsx";

/* Contests overlay — ported from the Frontend Gallery DC's ovContests slab
   (lines ~601-645): one official contest, a grid of community ones. Real
   data from GET /api/contests (core.list_contests) -- real prize amounts,
   real vote types, real cover art, real dates. No demo numbers.

   Real-data adaptations from the DC, disclosed:
   - The DC always has exactly one official contest to feature; the real feed
     can have zero, one, or (rarely) more -- this features the first and
     lists any additional official ones alongside the community grid instead
     of dropping them.
   - vote_type drives the PixAI-real pill text directly ("creator_pick" /
     "user_vote") rather than the DC's hardcoded "CREATOR PICK"/"USER VOTE"
     labels, which only ever showed one of each.
   - Clicking a card opens the real contest on pixai.art (row.url) in a new
     tab -- the DC's cards are cursor:pointer with no wired destination; this
     is the only real destination that exists for "view this contest".

   DATA LAYER (2026-08-03): the fetch + official/community/featured/
   restOfficial derivations and openContest()/dateRange() that used to live
   inline here were mechanically lifted into useContests.js so the new
   mobile Contests screen (ContestsMobile.jsx) can consume the EXACT same
   logic -- see that hook's own header comment. This file is refactored to
   CONSUME it rather than hold a second, drifting copy of the same fetch.

   THE WORKBENCH (2026-08-31, Contest Surface v2.dc.html). The list above is KEPT
   verbatim -- extended, not replaced, exactly as the handoff anchors it. What grew
   around it:
     A  the header tab pair (Contests / My entries, with a count badge), an
        ★ Entered ×N chip on cards this library has entries in, and cards that now
        open the IN-APP detail; the pixai.art link-out moved into that detail, where
        the DC puts it ("view all N on PixAI").
     B  ContestDetail replaces the list INSIDE this slab (§8.1) with ‹ All contests back.
     C  ContestPicker and D ContestConfirm are the shared entry road -- the same two
        components the My Art path uses, so an entry looks and behaves identically
        wherever it starts.
     E  ContestMyEntries, the deadline/results listing behind the second tab.
   Opening the overlay also kicks ONE fire-and-forget sync (in useContests), so entries
   made on pixai.art or another device are already there by the time the tab is clicked. */

export default function ContestsOverlay({ onClose, onShortlist, selectedCount = 0, onOpenPublish }) {
  useScrollLock();   // page never scrolls behind a full-screen panel (2026-08-06)
  const ct = useContests({ mine: true });
  const { d, err, contests, official, community, featured, restOfficial,
          dateRange, daysLeft, mine, mineRows, mineErr, entriesFor, enteredCount,
          syncing, reloadMine } = ct;
  const [tab, setTab] = useState("contests");     // "contests" | "mine"
  const [detail, setDetail] = useState(null);     // the contest whose detail is open
  const [picking, setPicking] = useState(null);   // the contest we are picking art for
  const [entering, setEntering] = useState(null); // {contest, art} -> the confirm

  // A card no longer links out; it opens the in-app detail (the DC's A annotation).
  const openDetail = (c) => { setDetail(c); setTab("contests"); };
  // A My-entries row opens the same in-app detail. The live board only carries RUNNING
  // contests, so an ended one is rebuilt from the row itself -- fewer chips (no prize
  // pool, no cover art the board would have carried), but B3/B4 stay in-app, which is
  // the whole point of §8.1. The winners strip needs only the slug and the result date.
  const openFromRow = (row) => {
    const live = contests.find((c) => String(c.id) === String(row.contest_id));
    openDetail(live || {
      id: row.contest_id, slug: row.slug, title: row.title, type: row.type,
      end_at: row.end_at, result_at: row.result_at, active: row.active, url: row.url,
      prize_amount: 0, prize_distribution: [], cover_url: "",
    });
  };
  const closeEnter = (where) => {
    setEntering(null);
    if (where === "mine") { setTab("mine"); setDetail(null); }
  };
  // Frontend Gallery.dc.html:2434 -- every card's date field is a combined
  // "range · N days left" string (`c.dates + ' · ' + c.left`); real code showed range-only
  // everywhere. daysLeft() already existed (built for mobile) but was never called here.
  const dateWithLeft = (row) => {
    const left = daysLeft(row);
    return left ? dateRange(row) + " · " + left : dateRange(row);
  };

  // "☆ Shortlist" -- re-implemented from the classic contest-shortlist branch onto the
  // React overlay. Rendered as a SIBLING overlaid on the card, not nested inside it: the
  // cards are <button>s and a button-in-a-button is invalid HTML. stopPropagation keeps a
  // Shortlist click from also firing the card's openContest (which opens pixai.art). The
  // count in the label is the live gallery selection App hands down.
  const shortlistBtn = (c) => onShortlist ? (
    <button type="button" className="mgct-shortlist"
      title="Add your selected gallery images to a collection for this contest"
      onClick={(e) => { e.stopPropagation(); e.preventDefault(); onShortlist(c); }}>
      ☆ Shortlist{selectedCount ? " (" + selectedCount + ")" : ""}
    </button>
  ) : null;

  return (
    <>
      <div className="mgv-scrim" onClick={onClose} />
      <div className="mgv-host">
        <div className="mgv-slab mgct-slab" role="dialog" aria-label="Contests">
          {detail ? (
            <ContestDetail contest={detail} mineRow={entriesFor(detail)}
              onBack={() => setDetail(null)} onClose={onClose}
              onEnter={(c) => setPicking(c)} />
          ) : (
          <>
          <div className="mgv-titlerow">
            <div className="mgv-title">🏅 Contests</div>
            {/* §8.2 -- the tab pair, with the live count of contests holding entries. */}
            <div className="mgct-tabs">
              <button type="button" className={"mgct-tab" + (tab === "contests" ? " on" : "")}
                onClick={() => setTab("contests")}>Contests</button>
              <button type="button" className={"mgct-tab" + (tab === "mine" ? " on" : "")}
                onClick={() => setTab("mine")}>
                My entries{mineRows.length > 0 ? <> <b>{mineRows.length}</b></> : null}
              </button>
            </div>
            <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
          </div>

          {tab === "mine" && (
            <ContestMyEntries rows={mineRows} loaded={mine !== null} syncing={syncing} err={mineErr}
              onOpen={openFromRow} onBrowse={() => setTab("contests")} />
          )}

          {tab === "contests" && !d && !err && <div className="mgh-loading">loading live contests…</div>}
          {tab === "contests" && err && <div className="mgh-loading">couldn't load — {err}</div>}

          {tab === "contests" && d && (
            <>
              <div className="mgct-summary">
                <b>{fmt(official.length)}</b> official · <b>{fmt(community.length)}</b> community running now
              </div>

              {/* §8.6's empty copy, written in-frame by the design. */}
              {contests.length === 0 && (
                <div className="mgct-empty">
                  Nothing running right now — official contests land every few weeks.
                  Community rounds fill the gaps on Discord.
                </div>
              )}

              {featured && (
                <>
                  <div className="mgct-h official">☀ Official <span className="n">{fmt(official.length)}</span></div>
                  {/* Gallery-era correction (handoff-2026-08-06 §5): one FULL-WIDTH 3:1
                      banner, title/pills/dates OVERLAID along the bottom over a gradient
                      scrim -- no separate body block below the image anymore. */}
                  <div className="mgct-cardwrap official">
                    <button type="button" className="mgct-official" onClick={() => openDetail(featured)}>
                      <div className="mgct-cover official">
                        {featured.cover_url ? <img src={featured.cover_url} alt="" /> : null}
                        <div className="mgct-scrim" />
                        <div className="mgct-overlaid">
                          <div className="mgct-title big">{featured.title}</div>
                          <div className="mgct-tags">
                            {featured.prize_amount > 0 && (
                              <span className="mgct-prize strong">♦ {fmt(featured.prize_amount)} CR</span>
                            )}
                            {featured.vote_type ? (
                              <span className={"mgct-votepick" + (featured.vote_type === "user_vote" ? " user" : "")}>
                                {featured.vote_type === "user_vote" ? "USER VOTE" : "CREATOR PICK"}
                              </span>
                            ) : null}
                            {/* list-level deadline awareness: this library's own count */}
                            {enteredCount(featured) > 0 && (
                              <span className="mgct-entered">★ Entered ×{enteredCount(featured)}</span>
                            )}
                            <span className="mgct-dates dim">{dateWithLeft(featured)}</span>
                          </div>
                        </div>
                      </div>
                    </button>
                    {shortlistBtn(featured)}
                  </div>
                </>
              )}

              {(community.length > 0 || restOfficial.length > 0) && (
                <div className="mgct-h community">🤝 Community <span className="n">{fmt(community.length)}</span></div>
              )}
              {(community.length > 0 || restOfficial.length > 0) && (
                <div className="mgct-grid">
                  {restOfficial.map((c) => (
                    <div className="mgct-cardwrap" key={c.id}>
                      <button type="button" className="mgct-card" onClick={() => openDetail(c)}>
                        <div className="mgct-cover">{c.cover_url ? <img src={c.cover_url} alt="" /> : null}</div>
                        <div className="mgct-body">
                          <div className="mgct-title">{c.title}</div>
                          <div className="mgct-tags">
                            {c.prize_amount > 0 && <span className="mgct-prize">♦ {fmt(c.prize_amount)} CR</span>}
                            {enteredCount(c) > 0 && (
                              <span className="mgct-entered">★ Entered ×{enteredCount(c)}</span>
                            )}
                          </div>
                          <div className="mgct-dates">{dateWithLeft(c)}</div>
                        </div>
                      </button>
                      {shortlistBtn(c)}
                    </div>
                  ))}
                  {community.map((c) => (
                    <div className="mgct-cardwrap" key={c.id}>
                      <button type="button" className="mgct-card" onClick={() => openDetail(c)}>
                        <div className="mgct-cover">{c.cover_url ? <img src={c.cover_url} alt="" /> : null}</div>
                        <div className="mgct-body">
                          <div className="mgct-title">{c.title}</div>
                          <div className="mgct-tags">
                            {c.prize_amount > 0 && <span className="mgct-prize">♦ {fmt(c.prize_amount)} CR</span>}
                            {c.vote_type ? (
                              <span className={"mgct-votepick" + (c.vote_type === "user_vote" ? " user" : "")}>
                                {c.vote_type === "user_vote" ? "USER VOTE" : "CREATOR PICK"}
                              </span>
                            ) : null}
                            {enteredCount(c) > 0 && (
                              <span className="mgct-entered">★ Entered ×{enteredCount(c)}</span>
                            )}
                          </div>
                          <div className="mgct-dates">{dateWithLeft(c)}</div>
                        </div>
                      </button>
                      {shortlistBtn(c)}
                    </div>
                  ))}
                </div>
              )}
              {/* Frontend Gallery.dc.html:642's "+12 more below the fold" replaced per the
                  owner's Option C (2026-08-04) with the REAL live count + the official
                  Discord (link owner-supplied 2026-08-06; copy owner-approved same day).
                  community.length is the full unpaginated API list -- an accurate number,
                  not the mock's static demo text. */}
              {community.length > 0 && (
                <div className="mgct-footer">
                  {fmt(community.length)} community contest{community.length === 1 ? "" : "s"} running
                  {" — find more on the "}
                  <a className="mgct-discord" href="https://discord.gg/cRtTuq5Z4"
                    target="_blank" rel="noopener noreferrer">official PixAI Discord</a>.
                </div>
              )}
            </>
          )}
          </>
          )}
        </div>
      </div>

      {/* C -- pick the art. Its two empty-state ways out belong to the app, not to the
          picker: Publish opens the publish flow, Browse returns to the gallery. */}
      {picking && (
        <ContestPicker contest={picking}
          onCancel={() => setPicking(null)}
          onOpenPublish={() => { setPicking(null); if (onOpenPublish) onOpenPublish(); else onClose(); }}
          onBrowse={() => { setPicking(null); onClose(); }}
          onPick={(art) => {
            setEntering({ contest: picking, art });
            setPicking(null);
          }} />
      )}

      {/* D -- the always-confirm. A successful entry re-pulls My entries so the tab,
          the chips and the detail's "your entries" strip agree immediately. */}
      {entering && (
        <ContestConfirm contest={entering.contest} art={entering.art}
          onClose={closeEnter}
          onEntered={() => reloadMine()}
          onPickDifferent={() => { setPicking(entering.contest); setEntering(null); }} />
      )}
    </>
  );
}
