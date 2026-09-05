import React, { useEffect, useState } from "react";
import useContests, { fmt, countdown, dayOf, tsOf } from "../hooks/useContests.js";
import ContestDetailMobile from "./ContestDetailMobile.jsx";
import "../styles/myart-contests.css";
import "../styles/overlays.css";
import "../styles/contest-mobile.css";

/* CONTESTS ON THE PHONE — pixel source
   `../moonglade-internal/design/contest/Contest Mobile Handoff.dc.html` frame D1
   ("BOARD — one scroll"), Session D picks 1a · 1d · 1f, committed 2026-09-04.

   WHAT THIS REPLACES. Until this pass the phone's Contests screen was a list that flung
   you at pixai.art: tapping any card called openContest() and opened the website in a new
   tab, because there was no in-app destination to open. The desktop workbench built one
   (2026-08-31), and this is its phone pass. Every tap now lands somewhere inside the app;
   the pixai.art link-out survives ONLY as the footnote on the detail view.

   ONE SCROLL. The official contest is a 16:9 hero with an OFFICIAL badge; the community
   ones are list cards below it. "MY ENTRIES · n" in the header is the ONE door to My
   entries -- and My entries is not a second layout, it is this same board filtered to the
   contests this library has pieces in, with one extra status line on each card.

   THE BADGE HUES ARE THE HANDOFF'S -- OFFICIAL lavender, COMMUNITY gold -- and as of
   2026-09-05 they are the desktop board's too. The two surfaces used to paint those two
   words the opposite way round from each other; the owner ruled one law for both and
   myart-contests.css was brought over to this one. The render harness now pins the pair
   on BOTH surfaces in a single test, so they cannot drift apart again.

   REAL-DATA DEVIATIONS from the frame, disclosed (the same duty every surface in this
   codebase's mobile pass carries, and the same list this file has always kept):
   1. OFFICIAL COUNT: the frame always has exactly one official contest. The real feed can
      have zero, one or more -- this features the first and folds any others into the
      community list, exactly as the desktop overlay does.
   2. ENTRY COUNTS: the frame's cards read "104 entries". The board row carries no entry
      count (`list_contests`, moonglade_backup.py) -- that number comes from a per-contest
      read of /api/contest/<slug>/artworks, which the DETAIL view makes and a list of ten
      cards must not make ten of. Cards show the prize, the winner count and the countdown,
      all of which the board row really holds; the entries chip lives on the detail.
   3. COVER ART: the frame's cards are flat colour tints. Real cover_url renders as an
      image when present, over the frame's own gradient as the fallback.
   4. WINNER COUNT: summed from prize_distribution's per-rank `count` (the frame's "9
      winners" for a 3-tier contest is that same sum), not the number of tiers.

   THE ENTRIES HALF IS NOW OPT-IN HERE TOO. This file used to call bare useContests()
   deliberately, so the phone made not one request more than the board. The header's
   "MY ENTRIES · n" is a live count and My entries is a real view, so it asks for
   { mine: true } like desktop -- one extra GET and the same one fire-and-forget sync POST
   the desktop overlay has always kicked on open. */

export default function ContestsMobile({ onEnter, entriesEpoch = 0 }) {
  const ct = useContests({ mine: true });
  const { d, err, contests, official, community, featured, restOfficial,
          dateRange, daysLeft, mineRows, mineErr, entriesFor, enteredCount,
          syncing, reloadMine } = ct;
  const [view, setView] = useState("board");     // "board" | "mine"
  const [detail, setDetail] = useState(null);

  // An entry fired from anywhere (this screen, the lightbox, Image Details) bumps the
  // epoch; the count in the header and the My-entries view re-read on the next tick
  // rather than waiting for the screen to be closed and reopened.
  useEffect(() => { if (entriesEpoch) reloadMine(); }, [entriesEpoch, reloadMine]);

  const closes = (row) => {
    const c = countdown(row.end_at);
    if (c && !c.over) return "closes " + c.text;
    const left = daysLeft(row);
    return left || dateRange(row);
  };
  const winnersOf = (row) => (row.prize_distribution || [])
    .filter((p) => p && typeof p === "object")
    .reduce((n, p) => n + (Number(p.count) || 0), 0);

  // The live board row wins when there is one; a contest that has ENDED is no longer on
  // the running board, so a My-entries row rebuilds what it can from itself. Same
  // fallback shape ContestsOverlay.jsx's openFromRow uses on desktop.
  const liveOr = (row) => contests.find((c) => String(c.id) === String(row.contest_id)) || {
    id: row.contest_id, slug: row.slug, title: row.title, type: row.type,
    end_at: row.end_at, result_at: row.result_at, active: row.active, url: row.url,
    prize_amount: 0, prize_distribution: [], cover_url: "", rules: [],
  };

  /* The status line My entries adds to the same card. Derived, never stored: running →
     awaiting results → results in (won / not placed), exactly the four ContestMyEntries.jsx
     derives on desktop. There is no per-entry RANK on the row to show -- /api/contest/mine
     answers entries and a `won` flag; rank lives behind the winners route, which this
     surface does not call -- so the line states the standing it can actually know. */
  const statusOf = (row) => {
    const resultTs = tsOf(row.result_at);
    const decided = resultTs !== null && resultTs <= Date.now();
    const ends = row.active ? countdown(row.end_at) : null;
    if (row.active) {
      return { cls: ends && ends.hot ? "hot" : "",
               text: "RUNNING" + (ends && !ends.over ? " · " + ends.text : "") };
    }
    if (!decided) return { cls: "awaiting", text: "AWAITING RESULTS · " + (dayOf(row.result_at) || "—") };
    if (row.won) return { cls: "won", text: "🏆 WON" };
    return { cls: "", text: "NOT PLACED" };
  };

  const card = (c, extra) => (
    <button type="button" className={"cmb-card" + (c.active === false ? " ended" : "")}
      key={c.id} onClick={() => setDetail(c)}>
      <div className="cmb-thumb">
        {c.cover_url ? <img src={c.cover_url} alt="" loading="lazy" decoding="async" /> : null}
      </div>
      <div className="cmb-cardcol">
        <span className="cmb-cardname">{c.title}</span>
        {(c.prize_amount > 0 || winnersOf(c) > 0) && (
          <span className="cmb-cardprize">
            {c.prize_amount > 0 ? "◆ " + fmt(c.prize_amount) + " CR" : ""}
            {c.prize_amount > 0 && winnersOf(c) > 0 ? " · " : ""}
            {winnersOf(c) > 0 ? fmt(winnersOf(c)) + " winner" + (winnersOf(c) === 1 ? "" : "s") : ""}
          </span>
        )}
        <span className="cmb-cardmeta">
          {enteredCount(c) > 0 ? "★ entered ×" + enteredCount(c) + " · " : ""}{closes(c)}
        </span>
        {extra}
      </div>
    </button>
  );

  if (detail) {
    return (
      <ContestDetailMobile contest={detail} mineRow={entriesFor(detail)}
        onBack={() => setDetail(null)}
        onEnter={(c) => onEnter && onEnter(c)} />
    );
  }

  return (
    <>
      <div className="cmb-boardhead">
        <button type="button" className={"cmb-door" + (view === "mine" ? " on" : "")}
          aria-pressed={view === "mine"}
          onClick={() => setView((v) => (v === "mine" ? "board" : "mine"))}>
          {view === "mine" ? "‹ ALL CONTESTS" : <>MY ENTRIES <span className="n">· {mineRows.length}</span></>}
        </button>
      </div>

      {view === "mine" ? (
        <>
          {mineErr && !mineRows.length && (
            <div className="cmb-note">Couldn't read your entries — {mineErr}</div>
          )}
          {!mineErr && !mineRows.length && (
            <div className="cmb-note">
              <b>No entries yet.</b> Open a contest and press Enter — every entry lands
              here with its deadlines.{syncing ? " (still refreshing…)" : ""}
            </div>
          )}
          {mineRows.length > 0 && (
            <>
              <div className="cmb-sectionlab">
                Your entries · {mineRows.length} contest{mineRows.length === 1 ? "" : "s"}
                {syncing ? " · refreshing…" : ""}
              </div>
              <div className="cmb-list">
                {mineRows.slice().sort((a, b) => {
                  const ka = tsOf(a.end_at) ?? tsOf(a.result_at) ?? Infinity;
                  const kb = tsOf(b.end_at) ?? tsOf(b.result_at) ?? Infinity;
                  return ka - kb;
                }).map((row) => {
                  const c = liveOr(row);
                  const st = statusOf(row);
                  const n = (row.entry_artwork_ids || []).length;
                  return card(c, (
                    <span className={"cmb-cardstatus " + st.cls}>
                      {st.text} · {n} {n === 1 ? "piece" : "pieces"}
                    </span>
                  ));
                })}
              </div>
            </>
          )}
        </>
      ) : (
        <>
          {err && <div className="cmb-note">couldn't load — {err}</div>}
          {!d && !err && <div className="cmb-note">loading live contests…</div>}
          {d && contests.length === 0 && (
            <div className="cmb-note">
              Nothing running right now — official contests land every few weeks.
              Community rounds fill the gaps on Discord.
            </div>
          )}

          {featured && (
            <button type="button" className="cmb-hero" onClick={() => setDetail(featured)}>
              {featured.cover_url
                ? <img src={featured.cover_url} alt="" loading="lazy" decoding="async" />
                : null}
              <span className="cmb-heroveil" />
              <span className="cmb-badge official">OFFICIAL</span>
              <span className="cmb-herofoot">
                <span className="cmb-heroname">{featured.title}</span>
                <span className="cmb-herometa">
                  {featured.prize_amount > 0 ? "◆ " + fmt(featured.prize_amount) + " CR · " : ""}
                  {closes(featured)}
                </span>
              </span>
            </button>
          )}

          {(community.length > 0 || restOfficial.length > 0) && (
            <>
              <div className="cmb-sectionlab">
                Community · {fmt(community.length)} open
              </div>
              <div className="cmb-list">
                {restOfficial.map((c) => card(c))}
                {community.map((c) => card(c))}
              </div>
            </>
          )}

          {community.length > 0 && (
            <div className="cmb-foot">
              {fmt(community.length)} community contest{community.length === 1 ? "" : "s"} running
              {" — find more on the "}
              <a href="https://discord.gg/cRtTuq5Z4" target="_blank" rel="noopener noreferrer">
                official PixAI Discord</a>.
            </div>
          )}
        </>
      )}
    </>
  );
}
