import React, { useEffect, useMemo, useState } from "react";
import { apiGet } from "../api.js";
import { fmt, countdown, dayOf, tsOf } from "../hooks/useContests.js";
import { parseMarkdownLite } from "../lib/markdownLite.js";
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
   you what the surface is for; one that vanishes teaches nothing.

   2026-09-03 -- the three blocks the first build shipped without: THE BRIEF, PRIZE
   BREAKDOWN and REQUIREMENTS, built to the owner-approved OPTION A of the Claude Design
   handoff `../moonglade-internal/design/contest/Contest Brief Board.dc.html` (option A =
   the first section, brief FIRST, the Enter bar under the requirements rather than above
   the brief). Reading what a contest wants now precedes deciding to enter it, which is
   the order the surface should have had from the start. */

/* The brief's markdown, as React elements. parseMarkdownLite returns plain data and every
   piece of it lands in a text child -- there is no innerHTML on this path, so upstream
   text cannot become markup no matter what PixAI puts in a description. */
function Spans({ spans }) {
  return (
    <>
      {spans.map((s, i) => {
        if (s.t === "br") return <br key={i} />;
        if (s.t === "b") return <strong key={i}>{s.v}</strong>;
        if (s.t === "i") return <em key={i}>{s.v}</em>;
        if (s.t === "a") {
          return (
            <a key={i} href={s.href} target="_blank" rel="noopener noreferrer">{s.v || s.href}</a>
          );
        }
        return <React.Fragment key={i}>{s.v}</React.Fragment>;
      })}
    </>
  );
}

function Markdown({ text }) {
  const blocks = useMemo(() => parseMarkdownLite(text), [text]);
  if (!blocks.length) return null;
  return (
    <div className="mgct-md">
      {blocks.map((b, i) => {
        if (b.type === "h") {
          const H = "h" + Math.min(b.level + 3, 6);   // #→h4, ##→h5, ###→h6: the slab's
          return <H key={i}><Spans spans={b.spans} /></H>;  // own title already owns h-1..3
        }
        if (b.type === "ul" || b.type === "ol") {
          const L = b.type;
          return (
            <L key={i}>
              {b.items.map((it, j) => <li key={j}><Spans spans={it} /></li>)}
            </L>
          );
        }
        return <p key={i}><Spans spans={b.spans} /></p>;
      })}
    </div>
  );
}

// vote_type as a reader's phrase. 'user_vote' is the community deciding, which is what the
// handoff's Votes row says; anything else is shown as its own value, humanized, rather
// than guessed at -- PixAI can add a mode tomorrow and this must not invent a name for it.
const voteWords = (v) => (v === "user_vote" ? "community vote" : String(v || "").replace(/_/g, " "));

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
  // The prize tiers, rank-ascending. `count` is how many people place at that rank, so the
  // WINNER count is the sum of counts, not the number of tiers -- the locked frame's chip
  // says "3 tiers · 9 winners" and the two numbers are genuinely different questions.
  const prizes = useMemo(() => (contest.prize_distribution || [])
    .filter((p) => p && typeof p === "object")
    .map((p) => ({ rank: Number(p.rank) || 0, count: Number(p.count) || 0,
                   amount: Number(p.amount) || 0 }))
    .sort((a, b) => a.rank - b.rank), [contest.prize_distribution]);
  const tiers = prizes.length;
  const winnersN = prizes.reduce((n, p) => n + p.count, 0);
  // The pool follows the chip: prize_amount is what "♦ N CR total" already renders, so the
  // footer must not quote a second, tier-summed number beside it. The sum is the fallback
  // for a contest that publishes tiers and no headline amount.
  const pool = contest.prize_amount > 0
    ? contest.prize_amount
    : prizes.reduce((n, p) => n + p.amount * p.count, 0);

  const rules = (contest.rules || []).filter((r) => r && typeof r === "object");
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
        {tiers > 0 && (
          <span className="mgct-chip">
            {tiers} tier{tiers === 1 ? "" : "s"}
            {winnersN > 0 && (
              <>
                <span className="sep">·</span>
                {fmt(winnersN)} winner{winnersN === 1 ? "" : "s"}
              </>
            )}
          </span>
        )}
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

      {/* ---- THE BRIEF (Option A: before the Enter bar, and FULL -- never clamped).
           The handoff offered a clamped "read the whole brief ▾" variant in option B and
           the owner did not take it: a brief you have to expand is a brief you enter a
           contest without reading. ---- */}
      {String(contest.description || "").trim() && (
        <>
          <div className="mgct-sechead">
            <div className="mgct-sectitle">THE BRIEF</div>
          </div>
          <div className="mgct-brief">
            <Markdown text={contest.description} />
          </div>
        </>
      )}

      <div className={"mgct-cols" + (tiers > 0 ? "" : " oneup")}>
        {tiers > 0 && (
          <div>
            <div className="mgct-sechead">
              <div className="mgct-sectitle">PRIZE BREAKDOWN</div>
            </div>
            <div className="mgct-tiers">
              {prizes.map((p, i) => (
                <div className={"mgct-tier" + (p.rank === 1 ? " top" : "")} key={p.rank || i}>
                  <span className="mgct-tierrank">RANK <b>{p.rank || i + 1}</b></span>
                  <span className="mgct-tieramt">
                    {fmt(p.amount)}<small>CR{p.count > 1 ? " each" : ""}</small>
                  </span>
                  <span className="mgct-tierwin">
                    {fmt(p.count)} winner{p.count === 1 ? "" : "s"}
                    {p.count > 1 ? " · " + fmt(p.amount * p.count) + " total" : ""}
                  </span>
                </div>
              ))}
            </div>
            <div className="mgct-tierfoot">
              <span>{fmt(winnersN)} winner{winnersN === 1 ? "" : "s"} across {tiers} tier{tiers === 1 ? "" : "s"}</span>
              {pool > 0 && <span><b>{fmt(pool)} CR</b> in the pool</span>}
            </div>
          </div>
        )}

        {/* ---- REQUIREMENTS. Every row answers a question you would otherwise have to
             leave the app to ask. The MODELS row shows required model/LoRA IDS, not
             names: nothing in this client resolves a model id to its title (
             /api/model-version answers version metadata, /api/model-search answers a
             query string -- neither is an id→name lookup), and inventing one would be a
             new upstream call per id on a surface that must not stall. The ids link out
             instead, which is honest about where the name lives. ---- */}
        <div>
          <div className="mgct-sechead">
            <div className="mgct-sectitle">REQUIREMENTS</div>
          </div>
          <div className="mgct-reqs">
            {contest.tack_name ? (
              <div className="mgct-req">
                <span className="mgct-reqk">Tag</span>
                <span className="mgct-reqv">
                  <span className="mgct-tack"><span className="h">#</span>{contest.tack_name}</span>
                </span>
              </div>
            ) : null}
            <div className="mgct-req">
              <span className="mgct-reqk">Models</span>
              <span className="mgct-reqv">
                {rules.length === 0 ? (
                  <><span className="mgct-ok">✓</span>no model or LoRA restrictions</>
                ) : (
                  rules.map((r, i) => {
                    const lora = r.type === "required_lora_ids";
                    const ids = (lora ? r.lora_ids : r.model_ids) || [];
                    const kind = lora ? "LoRA" : "model";
                    return (
                      <span className="mgct-reqrule" key={i}>
                        <span className="mgct-reqnote">
                          {ids.length} required {kind}{ids.length === 1 ? "" : "s"}
                        </span>
                        {ids.map((id) => (
                          <a className="mgct-idlink" key={String(id)}
                            href={"https://pixai.art/model/" + encodeURIComponent(String(id))}
                            target="_blank" rel="noopener noreferrer">
                            {String(id)} <span className="a">↗</span>
                          </a>
                        ))}
                      </span>
                    );
                  })
                )}
              </span>
            </div>
            <div className="mgct-req">
              <span className="mgct-reqk">Rules doc</span>
              <span className="mgct-reqv">
                {contest.desc_url ? (
                  <a className="mgct-viewall" href={contest.desc_url}
                    target="_blank" rel="noopener noreferrer">read the rules ↗</a>
                ) : (
                  <span className="mgct-none">none published for this contest</span>
                )}
              </span>
            </div>
            {contest.vote_type ? (
              <div className="mgct-req">
                <span className="mgct-reqk">Votes</span>
                <span className="mgct-reqv">{voteWords(contest.vote_type)}</span>
              </div>
            ) : null}
          </div>
        </div>
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
