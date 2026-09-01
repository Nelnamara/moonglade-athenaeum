import React from "react";
import { fmt, countdown, dayOf } from "../hooks/useContests.js";
import "../styles/myart-contests.css";

/* The contest ROW LIST — Contest Surface v2.dc.html F1 (the publish row's ⌄ list) and
   F2 (My Art's "Enter into contest…" chooser). One grammar, two hosts, because the DC
   draws them as the same row: banner thumb · title · "ends MM-DD · ♦ N CR" · ›.

   It picks nothing on its own. F2's own note says it out loud — "picking one opens the
   confirm (D) — nothing submits from here" — and that is the whole contract of this
   component: it hands a contest back and stops. */

export default function ContestChooser({ contests, onPick, empty }) {
  const rows = contests || [];
  if (!rows.length) {
    return <div className="mgctch-note">{empty || "No running contests right now."}</div>;
  }
  return (
    <div className="mgctch">
      {rows.map((c) => {
        const left = countdown(c.end_at);
        const ends = dayOf(c.end_at).slice(5) || "—";
        const prize = c.prize_amount > 0 ? " · ♦ " + fmt(c.prize_amount) + " CR" : "";
        return (
          <button type="button" className="mgctch-row" key={c.id} onClick={() => onPick(c)}>
            {c.cover_url
              ? <img className="mgctch-banner" src={c.cover_url} alt="" loading="lazy" />
              : <span className="mgctch-banner" />}
            <div className="mgctch-col">
              <div className="mgctch-t" title={c.title}>{c.title}</div>
              <div className="mgctch-sub">
                ends {ends}{prize}{left && left.hot ? " · " + left.text : ""}
              </div>
            </div>
            <div className="mgctch-chev">›</div>
          </button>
        );
      })}
    </div>
  );
}
