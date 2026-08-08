import React from "react";
import useContests, { fmt } from "../hooks/useContests.js";
import "../styles/overlays.css";
import "../styles/myart-contests.css";
import useScrollLock from "../hooks/useScrollLock.js";

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
   CONSUME it rather than hold a second, drifting copy of the same fetch. */

export default function ContestsOverlay({ onClose, onShortlist, selectedCount = 0 }) {
  useScrollLock();   // page never scrolls behind a full-screen panel (2026-08-06)
  const { d, err, contests, official, community, featured, restOfficial, openContest, dateRange, daysLeft } = useContests();
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
          <div className="mgv-titlerow">
            <div className="mgv-title">🏅 Contests</div>
            <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
          </div>

          {!d && !err && <div className="mgh-loading">loading live contests…</div>}
          {err && <div className="mgh-loading">couldn't load — {err}</div>}

          {d && (
            <>
              <div className="mgct-summary">
                <b>{fmt(official.length)}</b> official · <b>{fmt(community.length)}</b> community running now
              </div>

              {contests.length === 0 && (
                <div className="mgct-empty">No contests running right now.</div>
              )}

              {featured && (
                <>
                  <div className="mgct-h official">☀ Official <span className="n">{fmt(official.length)}</span></div>
                  {/* Gallery-era correction (handoff-2026-08-06 §5): one FULL-WIDTH 3:1
                      banner, title/pills/dates OVERLAID along the bottom over a gradient
                      scrim -- no separate body block below the image anymore. */}
                  <div className="mgct-cardwrap official">
                    <button type="button" className="mgct-official" onClick={() => openContest(featured)}>
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
                      <button type="button" className="mgct-card" onClick={() => openContest(c)}>
                        <div className="mgct-cover">{c.cover_url ? <img src={c.cover_url} alt="" /> : null}</div>
                        <div className="mgct-body">
                          <div className="mgct-title">{c.title}</div>
                          <div className="mgct-tags">
                            {c.prize_amount > 0 && <span className="mgct-prize">♦ {fmt(c.prize_amount)} CR</span>}
                          </div>
                          <div className="mgct-dates">{dateWithLeft(c)}</div>
                        </div>
                      </button>
                      {shortlistBtn(c)}
                    </div>
                  ))}
                  {community.map((c) => (
                    <div className="mgct-cardwrap" key={c.id}>
                      <button type="button" className="mgct-card" onClick={() => openContest(c)}>
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
        </div>
      </div>
    </>
  );
}
