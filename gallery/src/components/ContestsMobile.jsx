import React from "react";
import useContests, { fmt } from "../hooks/useContests.js";
import "../styles/myart-contests.css";
import "../styles/overlays.css";

/* Contests -- mobile screen (design spec: Moonglade Mobile.dc.html
   screenIsContests block, lines 548-563 & demo data at 680-686). Pushed via
   MobileScreen.jsx from AppMobile.jsx's Menu sheet, replacing that
   destination's former honest placeholder. Data layer: useContests.js, the
   EXACT hook ContestsOverlay.jsx (desktop) now consumes too -- live GET
   /api/contests, no second fetch of the same route.

   Real-data deviations from the design mock, disclosed here for the owner's
   review (matching ContestsOverlay.jsx's own header comment's precedent for
   the SAME real-vs-demo gaps, ported forward rather than re-decided):

   1. OFFICIAL COUNT: the design always has exactly one official contest to
      feature. The real feed can have zero, one, or more -- this features
      the first (official[0]) and folds any additional official ones into
      the community grid, exactly like the desktop overlay already does,
      instead of assuming there's only ever one.
   2. VOTE-TYPE PILL: the design hardcodes "CREATOR PICK" on the one
      official card and shows NO vote pill at all on community cards. The
      real vote_type field drives the pill live here (creator_pick/
      user_vote) on EVERY card that has one, official or community -- same
      real branching ContestsOverlay.jsx already does on desktop, not the
      mock's one-of-each assumption.
   3. COMBINED "range · days left" (CORRECTED 2026-08-04): the design's own mapping
      (`Frontend Gallery.dc.html:2434`, `c.dates + ' · ' + c.left`) combines BOTH a real
      date range and a computed days-left for every card, official and community alike.
      A prior version of this file showed the official card range-only and community
      cards days-left-only (a real, disclosed choice at the time, but one that didn't
      actually match the design's own literal formula, confirmed by the 2026-08-04
      audit) -- now every card gets the same real `dateRange(row) + " · " + daysLeft(row)`
      combination desktop now also uses, computed client-side from real start_at/end_at
      (the same math classic's own daysLeft() helper already does), not invented.
   4. COVER ART: the design's cards are flat color tints (no real image
      slot modeled anywhere in that block). Real cover_url renders as an
      actual image when present, falling back to .mgct-cover's own default
      (var(--surface0)) otherwise -- the exact same fallback
      ContestsOverlay.jsx already uses on desktop, nothing invented.
   5. CLICK-THROUGH: the design's cards have no onClick anywhere. Tapping a
      card here opens the real contest on pixai.art (row.url) in a new tab,
      the one real destination that exists for "view this contest" -- the
      exact affordance ContestsOverlay.jsx's own header comment already
      discloses adding for desktop, ported forward rather than left dead. */

export default function ContestsMobile() {
  const { d, err, contests, official, community, featured, restOfficial, openContest, dateRange, daysLeft } = useContests();
  const dateWithLeft = (row) => {
    const left = daysLeft(row);
    return left ? dateRange(row) + " · " + left : dateRange(row);
  };

  if (err) return <div className="mgh-loading">couldn't load — {err}</div>;
  if (!d) return <div className="mgh-loading">loading live contests…</div>;

  return (
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
          <button type="button" className="mgct-official" onClick={() => openContest(featured)}>
            <div className="mgct-cover">
              {featured.cover_url ? <img src={featured.cover_url} alt="" /> : null}
            </div>
            <div className="mgct-body">
              <div className="mgct-title">{featured.title}</div>
              <div className="mgct-tags">
                {featured.prize_amount > 0 && (
                  <span className="mgct-prize">♦ {fmt(featured.prize_amount)} CR</span>
                )}
                {featured.vote_type ? (
                  <span className={"mgct-votepick" + (featured.vote_type === "user_vote" ? " user" : "")}>
                    {featured.vote_type === "user_vote" ? "USER VOTE" : "CREATOR PICK"}
                  </span>
                ) : null}
              </div>
              <div className="mgct-dates">{dateWithLeft(featured)}</div>
            </div>
          </button>
        </>
      )}

      {(community.length > 0 || restOfficial.length > 0) && (
        <div className="mgct-h community">🤝 Community <span className="n">{fmt(community.length)}</span></div>
      )}
      {(community.length > 0 || restOfficial.length > 0) && (
        <div className="mgct-grid" style={{ gridTemplateColumns: "1fr" }}>
          {restOfficial.map((c) => (
            <button type="button" className="mgct-card" key={c.id} onClick={() => openContest(c)}>
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
          ))}
          {community.map((c) => (
            <button type="button" className="mgct-card" key={c.id} onClick={() => openContest(c)}>
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
          ))}
        </div>
      )}
      {/* Same real-count + Discord footer as ContestsOverlay.jsx -- see its comment. */}
      {community.length > 0 && (
        <div className="mgct-footer">
          {fmt(community.length)} community contest{community.length === 1 ? "" : "s"} running
          {" — find more on the "}
          <a className="mgct-discord" href="https://discord.gg/cRtTuq5Z4"
            target="_blank" rel="noopener noreferrer">official PixAI Discord</a>.
        </div>
      )}
    </>
  );
}
