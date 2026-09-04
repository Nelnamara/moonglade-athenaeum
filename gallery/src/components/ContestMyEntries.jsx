import React from "react";
import { countdown, dayOf, tsOf } from "../hooks/useContests.js";
import "../styles/myart-contests.css";

/* MY ENTRIES — Contest Surface v2.dc.html E1-E4 (§8.2's tab), the contest workbench's
   first real slice: every contest this library has a piece in, with its deadlines and
   where it stands. Rows sort by nearest deadline and the list scrolls inside the modal.

   Status is derived, not stored: running → awaiting results → results in (won / not
   placed). A won row takes the gold treatment; the not-placed row stays deliberately
   quiet. The achievement side of a win is the toast's business and appears nowhere here.

   E4 (record a win manually) renders as the DC draws it and is DISABLED: its claim route
   is design-gated and does not exist yet. Rendering it dimmed says the affordance is
   coming; omitting it would quietly redesign the frame. */

export default function ContestMyEntries({ rows, loaded = true, syncing, err, onOpen, onBrowse }) {
  const list = (rows || []).slice().sort((a, b) => {
    const ka = tsOf(a.end_at) ?? tsOf(a.result_at) ?? Infinity;
    const kb = tsOf(b.end_at) ?? tsOf(b.result_at) ?? Infinity;
    return ka - kb;
  });
  const pieces = list.reduce((n, r) => n + (r.entry_artwork_ids || []).length, 0);
  const soonest = list
    .map((r) => (r.active ? countdown(r.end_at) : null))
    .find((c) => c && !c.over);

  // "No entries yet" is a FACT about an account, and it was being shown before anything
  // had been read -- so a slow first fetch told you that you had entered nothing. `rows`
  // is null until the read lands; only then is the empty state true.
  if (!loaded) {
    return <div className="mgh-loading">reading your entries…</div>;
  }

  // An error belongs in the LOADED state, not only inside the empty one. A failed first
  // read used to leave this on "reading your entries…" forever with the error unreachable
  // -- the one case where something had gone wrong and the surface said nothing.
  if (err && !list.length) {
    return (
      <div className="mgcte-empty">
        <div className="glyph">🏅</div>
        <div className="t">Couldn't read your entries</div>
        <div className="c">{err}</div>
        <div className="a">
          <button type="button" className="mgct-ghost lav" onClick={onBrowse}>
            Browse running contests
          </button>
        </div>
      </div>
    );
  }

  if (!list.length) {
    return (
      <div className="mgcte-empty">
        <div className="glyph">🏅</div>
        <div className="t">No entries yet</div>
        <div className="c">
          Enter from a contest's page, from a published piece in My Art, or right at
          publish time — every entry lands here with its deadlines.
          {err ? " (Couldn't refresh just now: " + err + ")" : ""}
        </div>
        <div className="a">
          <button type="button" className="mgct-ghost lav" onClick={onBrowse}>
            Browse running contests
          </button>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="mgcte-sum">
        <b>{pieces}</b> piece{pieces === 1 ? "" : "s"} across <b>{list.length}</b> contest
        {list.length === 1 ? "" : "s"}
        {soonest ? <> · next deadline <b className={soonest.hot ? "hot" : ""}>{soonest.text}</b></> : null}
        {syncing ? " · refreshing…" : ""}
      </div>
      <div className="mgcte-cols">
        <div>CONTEST</div><div>PIECES</div><div>CLOSES</div><div>RESULTS</div><div>STATUS</div>
      </div>
      <div className="mgcte-rows">
        {list.map((r) => {
          const official = (r.type || "") === "official";
          const n = (r.entry_artwork_ids || []).length;
          const thumbs = (r.entries || []).filter((e) => e.thumb).slice(0, 3);
          const resultTs = tsOf(r.result_at);
          const decided = resultTs !== null && resultTs <= Date.now();
          const ends = r.active ? countdown(r.end_at) : null;
          const status = r.active ? { cls: "", text: "RUNNING" }
            : !decided ? { cls: "awaiting", text: "AWAITING RESULTS" }
            : r.won ? { cls: "won", text: "🏆 WON" }
            : { cls: "quiet", text: "NOT PLACED" };
          return (
            <button type="button" key={r.contest_id}
              className={"mgcte-row" + (r.won && decided ? " won" : "")}
              onClick={() => onOpen && onOpen(r)}>
              <div style={{ minWidth: 0 }}>
                <div className="mgcte-name">
                  <span className={"mgct-badge " + (official ? "official" : "community")}>
                    {official ? "☀ OFFICIAL" : "🤝 COMMUNITY"}
                  </span>
                  <span className="t" title={r.title}>{r.title || r.slug || r.contest_id}</span>
                </div>
                <div className="mgcte-sub">
                  {n} {n === 1 ? "entry" : "entries"}
                </div>
              </div>
              <div className="mgcte-thumbs">
                {thumbs.map((e) => (
                  <img className={"mgcte-thumb" + (r.won && decided ? " gold" : "")}
                    key={e.artwork_id} src={e.thumb} alt=""
                    onError={(ev) => { ev.currentTarget.style.visibility = "hidden"; }} />
                ))}
              </div>
              <div className={"mgcte-when" + (ends && ends.hot ? " hot" : r.active ? "" : " dim")}>
                {r.active
                  ? (ends && !ends.over ? ends.text : dayOf(r.end_at))
                  : "closed " + (dayOf(r.end_at).slice(5) || "—")}
              </div>
              <div className="mgcte-when res">
                {dayOf(r.result_at).slice(5) || "—"}{decided ? " ✓" : ""}
              </div>
              <div><span className={"mgcte-status " + status.cls}>{status.text}</span></div>
            </button>
          );
        })}
      </div>
      <div className="mgcte-foot">
        <div className="n">results land automatically at each contest's result date</div>
        <button type="button" className="mgcte-record" disabled
          title="coming with results season">record a win manually…</button>
      </div>
    </>
  );
}
