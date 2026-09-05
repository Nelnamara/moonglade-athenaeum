import React, { useEffect, useMemo, useState } from "react";
import { apiGet } from "../api.js";
import { fmt, countdown, dayOf, tsOf } from "../hooks/useContests.js";
import { Markdown } from "./ContestDetail.jsx";
import "../styles/contest-mobile.css";

/* THE DETAIL, ON THE PHONE — pixel source `Contest Mobile Handoff.dc.html` frame D2
   ("DETAIL — accordion (live)"), Session D picks 1a · 1d · 1f.

   ONE SCROLL, THREE FOLDS. Desktop's ContestDetail.jsx lays the brief, the prize
   breakdown and the requirements out as full sections side by side, which is right on a
   980px slab and is four screens of scrolling on a 390pt phone. Here they are an
   accordion: the brief open by default, Prizes and Requirements folded with their KEY
   FIGURE still visible in the collapsed row (the pool and winner count; the tag), one
   section open at a time. Same data, same fetches, phone-shaped chrome.

   WHAT THIS DOES NOT PORT, and why:
     - the winners strip and the entries-preview grid. The handoff draws neither; D2 is
       back-row · banner · chips · accordion · Enter bar · footnote and nothing else. The
       entries COUNT is kept (it is a chip) so /api/contest/<slug>/artworks is still read;
       the winners route is not called at all from this surface.

   THE BADGE HUES on this banner -- OFFICIAL lavender, COMMUNITY gold -- are the handoff's,
   and since 2026-09-05 the desktop board's too; that pair used to be the opposite way
   round there. See ContestsMobile.jsx's header for the ruling.

   THE pixai.art LINK-OUT survives here and ONLY here, as the footnote the handoff writes
   ("view on pixai.art ↗"). Every other place the phone used to fling you at the website
   now has a real in-app destination. */

const voteWords = (v) => (v === "user_vote" ? "community vote" : String(v || "").replace(/_/g, " "));

export default function ContestDetailMobile({ contest, mineRow, onBack, onEnter }) {
  const [preview, setPreview] = useState(null);
  // The handoff opens the brief; a contest with no description opens Prizes instead, so
  // the accordion is never a stack of three closed rows on first paint.
  const [open, setOpen] = useState("brief");

  const slug = contest.slug || "";
  useEffect(() => {
    let dead = false;
    setPreview(null);
    if (slug) {
      apiGet("/api/contest/" + encodeURIComponent(slug) + "/artworks")
        .then((d) => { if (!dead) setPreview(d); });
    }
    return () => { dead = true; };
  }, [slug]);

  const official = (contest.type || "") === "official";
  const running = !!contest.active;
  const resultTs = tsOf(contest.result_at);
  const decided = resultTs !== null && resultTs <= Date.now();
  const entered = mineRow && mineRow.entry_artwork_ids ? mineRow.entry_artwork_ids.length : 0;

  // Rank-ascending tiers. `count` is how many people place at that rank, so the WINNER
  // count is the sum of counts, not the number of tiers -- two genuinely different
  // questions, exactly as desktop's ContestDetail.jsx already computes them.
  const prizes = useMemo(() => (contest.prize_distribution || [])
    .filter((p) => p && typeof p === "object")
    .map((p) => ({ rank: Number(p.rank) || 0, count: Number(p.count) || 0,
                   amount: Number(p.amount) || 0 }))
    .sort((a, b) => a.rank - b.rank), [contest.prize_distribution]);
  const winnersN = prizes.reduce((n, p) => n + p.count, 0);
  const pool = contest.prize_amount > 0
    ? contest.prize_amount
    : prizes.reduce((n, p) => n + p.amount * p.count, 0);
  const rules = (contest.rules || []).filter((r) => r && typeof r === "object");
  const total = preview && preview.total_count ? preview.total_count : 0;
  const brief = String(contest.description || "").trim();
  const ends = countdown(contest.end_at);

  // §8.3's disabled grammar, kept: the button keeps its label when it cannot fire and the
  // reason goes on the line underneath.
  const why = running ? ""
    : decided ? "Contest ended"
    : "Entries closed " + (dayOf(contest.end_at) || "—")
      + (contest.result_at ? " — results " + dayOf(contest.result_at) : "");

  useEffect(() => { setOpen(brief ? "brief" : (prizes.length ? "prizes" : "reqs")); },
            [slug, brief, prizes.length]);

  const toggle = (id) => setOpen((cur) => (cur === id ? null : id));

  const section = (id, label, hint, body) => (
    <div className="cmb-sec" key={id}>
      <button type="button" className="cmb-sechead" onClick={() => toggle(id)}
        aria-expanded={open === id}>
        <span className="cmb-seclab">{label}</span>
        {hint ? <span className="cmb-sechint">{hint}</span> : null}
        <span className="cmb-secchev" aria-hidden="true">{open === id ? "▴" : "▾"}</span>
      </button>
      {open === id ? <div className="cmb-secbody">{body}</div> : null}
    </div>
  );

  /* THE DETAIL IS ITS OWN SCROLL LAYER (2026-09-05). Everything above the Enter bar sits
     in `.cmb-detailbody`, which owns the scrolling and latches it (`overscroll-behavior:
     contain`); the bar and its reason line are the layer's own footer, not a sticky
     passenger in the Contests screen's scroller. Before this the detail was a flat column
     inside `.glm-screen-body`, so a flick that ran past the brief chained out of the
     screen entirely and landed in the Control tab underneath -- the owner's own repro. */
  return (
    <div className="cmb-detail">
      <div className="cmb-detailbody">
        <button type="button" className="cmb-back" onClick={onBack}>
          <span aria-hidden="true">‹</span> All contests
        </button>

        <div className="cmb-banner">
          {contest.cover_url
            ? <img src={contest.cover_url} alt="" loading="lazy" decoding="async" />
            : null}
          <span className={"cmb-badge " + (official ? "official" : "community")}>
            {official ? "OFFICIAL" : "COMMUNITY"}
          </span>
          <div className="cmb-bannername">{contest.title}</div>
        </div>

        <div className="cmb-chips">
          {contest.prize_amount > 0 && (
            <span className="cmb-chip gold">◆ {fmt(contest.prize_amount)} CR</span>
          )}
          {winnersN > 0 && (
            <span className="cmb-chip">{fmt(winnersN)} winner{winnersN === 1 ? "" : "s"}</span>
          )}
          {total > 0 && <span className="cmb-chip">{fmt(total)} entries</span>}
          {!running && !decided && <span className="cmb-chip">AWAITING RESULTS</span>}
          {entered > 0 && <span className="cmb-chip entered">★ Entered ×{entered}</span>}
        </div>

        <div className="cmb-acc">
          {brief ? section("brief", "The brief", "", <Markdown text={brief} />) : null}

          {prizes.length > 0 ? section("prizes", "Prizes",
            (pool > 0 ? "◆ " + fmt(pool) + " CR" : "")
              + (pool > 0 && winnersN > 0 ? " · " : "")
              + (winnersN > 0 ? fmt(winnersN) + " winner" + (winnersN === 1 ? "" : "s") : ""),
            <>
              {prizes.map((p, i) => (
                <div className="cmb-tier" key={p.rank || i}>
                  <span className="r">RANK {p.rank || i + 1}</span>
                  <span className="a">{fmt(p.amount)} CR{p.count > 1 ? " each" : ""}</span>
                  <span className="w">{fmt(p.count)} winner{p.count === 1 ? "" : "s"}</span>
                </div>
              ))}
            </>) : null}

          {section("reqs", "Requirements",
            contest.tack_name ? "#" + contest.tack_name : (rules.length ? "" : "no restrictions"),
            <>
              {contest.tack_name ? (
                <>
                  <span className="k">Tag</span>
                  <span className="cmb-tack">#{contest.tack_name}</span>
                </>
              ) : null}
              <span className="k">Models</span>
              {rules.length === 0 ? (
                <span><span className="cmb-ok">✓</span> no model or LoRA restrictions</span>
              ) : (
                // The ids link out rather than resolving to names: nothing in this client
                // turns a model id into its title, and inventing a lookup would be a new
                // upstream call per id. Same call desktop's ContestDetail.jsx makes.
                rules.map((r, i) => {
                  const lora = r.type === "required_lora_ids";
                  const ids = (lora ? r.lora_ids : r.model_ids) || [];
                  return (
                    <span key={i}>
                      {ids.length} required {lora ? "LoRA" : "model"}{ids.length === 1 ? "" : "s"}
                      {ids.map((id) => (
                        <span key={String(id)}>
                          {" "}
                          <a href={"https://pixai.art/model/" + encodeURIComponent(String(id))}
                            target="_blank" rel="noopener noreferrer">{String(id)} ↗</a>
                        </span>
                      ))}
                    </span>
                  );
                })
              )}
              <span className="k">Rules doc</span>
              {contest.desc_url ? (
                <a href={contest.desc_url} target="_blank" rel="noopener noreferrer">read the rules ↗</a>
              ) : (
                <span>none published for this contest</span>
              )}
              {contest.vote_type ? (
                <>
                  <span className="k">Votes</span>
                  <span>{voteWords(contest.vote_type)}</span>
                </>
              ) : null}
            </>)}
        </div>

        {contest.url ? (
          <div className="cmb-foot">
            <a href={contest.url} target="_blank" rel="noopener noreferrer">view on pixai.art ↗</a>
          </div>
        ) : null}
      </div>

      {/* §8.3 again: the reason sits ABOVE the bar. Outside the scroller with it, so a
          disabled bar and the sentence explaining it are never separated by a flick. */}
      {why ? <div className="cmb-why">{why}</div> : null}

      {/* The Enter bar — the layer's own footer, above the safe area, per the handoff's
          own plumbing note. */}
      <div className="cmb-enterbar">
        <div className="cmb-when">
          <div className="cmb-whenk">{running ? "CLOSES" : "CLOSED"}</div>
          <div className={"cmb-whenv" + (running && ends && ends.hot ? " hot" : "")}>
            {running && ends && !ends.over ? ends.text : (dayOf(contest.end_at) || "—")}
          </div>
        </div>
        <button type="button" className="cmb-metal" disabled={!running}
          onClick={() => onEnter(contest)}>
          {entered > 0 ? "Enter another" : "Enter this contest"}
          <i aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
