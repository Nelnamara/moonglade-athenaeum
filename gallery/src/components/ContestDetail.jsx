import React, { useEffect, useState } from "react";
import { apiGet } from "../api.js";
import { fmt, countdown, dayOf, tsOf } from "../hooks/useContests.js";
import "../styles/myart-contests.css";

/* THE DETAIL — Contest Surface v2.dc.html B1-B4, §8.1: an IN-MODAL expansion that
   replaces the list inside the same slab, with a ‹ All contests way back. (A slide-over
   would fight the modal's centered composition and its height budget.)

   Four states off the same data: running · running-and-entered (with the <48h gold
   countdown, §8.4) · closed-awaiting-results · results-in with the winners strip.

   THE WINNERS STRIP IS NOT ASKED FOR BEFORE resultAt. PixAI answers a running contest's
   winners with an empty array, so an early call could only ever draw nothing -- the strip
   stays hidden and no request is made until the result date has actually passed.

   §8.3's disabled grammar: the Enter button keeps its label when it cannot fire, and the
   reason goes on the line underneath. A dimmed button that still says what it is tells
   you what the surface is for; one that vanishes teaches nothing. */

export default function ContestDetail({ contest, mineRow, onBack, onClose, onEnter }) {
  const [preview, setPreview] = useState(null);
  const [winners, setWinners] = useState(null);

  const slug = contest.slug || "";
  const resultTs = tsOf(contest.result_at);
  const decided = resultTs !== null && resultTs <= Date.now();

  useEffect(() => {
    let dead = false;
    setPreview(null);
    if (slug) {
      apiGet("/api/contest/" + encodeURIComponent(slug) + "/artworks")
        .then((d) => { if (!dead) setPreview(d); });
    }
    return () => { dead = true; };
  }, [slug]);

  useEffect(() => {
    let dead = false;
    setWinners(null);
    if (slug && decided) {
      apiGet("/api/contest/" + encodeURIComponent(slug) + "/winners")
        .then((d) => { if (!dead) setWinners(d.winners || []); });
    }
    return () => { dead = true; };
  }, [slug, decided]);

  const official = (contest.type || "") === "official";
  const entered = mineRow && mineRow.entry_artwork_ids ? mineRow.entry_artwork_ids.length : 0;
  const myThumbs = ((mineRow && mineRow.entries) || []).filter((e) => e.thumb).slice(0, 3);
  const tiers = (contest.prize_distribution || []).length;
  const total = preview && preview.total_count ? preview.total_count : 0;
  const ends = countdown(contest.end_at);
  const results = countdown(contest.result_at);
  const running = !!contest.active;

  // §8.3 -- why the button cannot fire, in the contest's own terms.
  const why = running ? ""
    : decided ? "Contest ended"
    : "Entries closed " + (dayOf(contest.end_at) || "—")
      + (contest.result_at ? " — results " + dayOf(contest.result_at) : "");

  // 1ST / 2ND / 3RD / 4TH … (11-13 are TH, as English insists)
  const rankLabel = (n) => {
    const v = Number(n) || 0;
    const tens = v % 100;
    const suffix = (tens >= 11 && tens <= 13) ? "TH" : (["TH", "ST", "ND", "RD"][v % 10] || "TH");
    return v + suffix;
  };

  return (
    <>
      <div className="mgv-titlerow">
        <button type="button" className="mgct-back" onClick={onBack}>
          <span className="c">‹</span> All contests
        </button>
        <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
      </div>

      <div className={"mgct-banner" + (official ? " official" : "")}>
        <div className="mgct-bannerart">
          {contest.cover_url ? <img src={contest.cover_url} alt="" /> : null}
          <div className="mgct-scrim" />
          <div className="mgct-overlaid">
            <div className="mgct-badges">
              <span className={"mgct-badge " + (official ? "official" : "community")}>
                {official ? "☀ OFFICIAL" : "🤝 COMMUNITY"}
              </span>
              {entered > 0 && (
                <span className="mgct-entered strong">★ Entered ×{entered}</span>
              )}
            </div>
            <div className="mgct-dtitle">{contest.title}</div>
          </div>
        </div>
      </div>

      <div className="mgct-chips">
        {contest.prize_amount > 0 && (
          <span className="mgct-chip gold">♦ {fmt(contest.prize_amount)} CR total</span>
        )}
        {tiers > 0 && <span className="mgct-chip">{tiers} tier{tiers === 1 ? "" : "s"}</span>}
        {total > 0 && <span className="mgct-chip">{fmt(total)} entries</span>}
        {!running && !decided && <span className="mgct-chip await">AWAITING RESULTS</span>}
        {myThumbs.length > 0 && (
          <span className="mgct-mine">
            {myThumbs.map((e) => (
              <img className="mgct-minethumb" key={e.artwork_id} src={e.thumb} alt="" />
            ))}
            <span className="mgct-minelab">your entries</span>
          </span>
        )}
      </div>

      <div className="mgct-datebar">
        <div>
          <div className="mgct-dk">{running ? "CLOSES" : "CLOSED"}</div>
          {running && ends && ends.hot ? (
            <div className="mgct-dv hot">{ends.text}</div>
          ) : (
            <div className={"mgct-dv" + (running ? "" : " dim")}>
              {dayOf(contest.end_at) || "—"}
              {running && ends && !ends.over ? <span className="rest"> · {ends.text}</span> : null}
            </div>
          )}
        </div>
        <div>
          <div className="mgct-dk">RESULTS</div>
          <div className={"mgct-dv" + (decided ? " dim" : "")}>
            {dayOf(contest.result_at) || "—"}
            {decided ? " ✓" : results && !results.over
              ? <span className="rest"> · {results.text}</span> : null}
          </div>
        </div>
        <div className="mgct-enterwrap">
          <button type="button" className="mgct-enter" disabled={!running}
            onClick={() => onEnter(contest)}>
            {entered > 0 ? "Enter another" : "Enter this contest"}
          </button>
          {why && <div className="mgct-why">{why}</div>}
        </div>
      </div>

      {decided && winners && winners.length > 0 && (
        <>
          <div className="mgct-winhead">
            🏆 WINNERS <span className="n">· announced {dayOf(contest.result_at)}</span>
          </div>
          <div className="mgct-winrows">
            {winners.map((w, i) => (
              <div key={w.id || i}
                className={"mgct-winrow" + (w.mine ? " me" : w.rank === 1 ? " top" : "")}>
                <span className={"mgct-rank" + (w.rank === 1 ? " first" : "")}>
                  {rankLabel(w.rank || i + 1)}
                </span>
                {w.thumb
                  ? <img className={"mgct-winthumb" + (w.rank <= 3 ? " gold" : "")} src={w.thumb} alt="" />
                  : <span className="mgct-winthumb" />}
                <span className="mgct-winname">{w.author_name || "—"}</span>
                {w.mine && <span className="mgct-you">YOU</span>}
                {w.prize_amount > 0 && (
                  <span className="mgct-prize">♦ {fmt(w.prize_amount)} CR</span>
                )}
              </div>
            ))}
          </div>
        </>
      )}

      <div className="mgct-sechead">
        <div className="mgct-sectitle">ENTRIES PREVIEW</div>
        {contest.url && (
          <a className="mgct-viewall" href={contest.url} target="_blank" rel="noopener noreferrer">
            view all{total > 0 ? " " + fmt(total) : ""} on PixAI ↗
          </a>
        )}
      </div>
      <div className="mgct-prevgrid">
        {(preview && preview.entries ? preview.entries : []).slice(0, 8).map((e, i) => (
          e.thumb
            ? <img className="mgct-prevtile" key={e.id || i} src={e.thumb} alt="" loading="lazy"
                onError={(ev) => { ev.currentTarget.style.visibility = "hidden"; }} />
            : <span className="mgct-prevtile" key={e.id || i} />
        ))}
        {(!preview || !preview.entries || !preview.entries.length)
          && Array.from({ length: 8 }, (_, i) => <span className="mgct-prevtile" key={"p" + i} />)}
      </div>
    </>
  );
}
