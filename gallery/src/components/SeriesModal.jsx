import React, { useEffect, useMemo, useRef, useState } from "react";
import { fetchSeriesStack } from "../api.js";
import { localDay } from "../gen/dates.js";
import "../styles/series-modal.css";

/* ============================================================================
   B3 -- a series stack opens in a MODAL (Gallery Chrome Handoff.dc.html,
   2026-09-04).

   WHAT THIS REPLACES. Opening a stacked series card used to be a NAVIGATION: it
   pushed the sid into the library's own `series` filter (#34 direction B's
   ?series= drill-down), the whole gallery re-loaded as that series' members, and
   getting back out meant finding Clear. The handoff retires that takeover. The
   library is left exactly as it was -- same filters, same page, same scroll --
   and the stack opens over it. Esc goes straight back, because there is nothing
   to undo.

   THE RAIL is #34's LINEAGE pattern. A dial-in series is a chain of RUNS (the
   backend's `steps`: one task each, in order, with the prompt delta that made it
   and how many images it produced). They draw as an indented descent line so the
   chain reads as a chain, each with its own count, headed by "All runs".

   FACET CHIPS sit in the rail's footer and AND with the run selection -- pick
   Run 3 and ★ and you get Run 3's rated pictures, not a union. All three facets
   are grounded in fields the listing already carries: is_video, h > w, rating.

   THE SORT is the handoff's own: run № orders by run then index within it, and
   every tile badges r№·i so the order is legible rather than implied; newest is
   flat reverse-chronology across the whole series. The badge is on the tile in
   both sorts -- under "newest" it is the only thing saying which run a picture
   came from.

   DATA: api.js's fetchSeriesStack -- /api/series/<sid> for the runs, and the
   same ?series=<sid> listing the retired takeover used, asked for directly here.
   No new backend.
   ========================================================================== */

/* The run a media row belongs to: its task's position in the chain (1-based),
   or 0 for a row whose task isn't a step -- which shouldn't happen, since the
   listing is constrained to this series' member tasks, but a series recomputed
   between the two requests could produce one, and dropping such a row silently
   would make the grid disagree with the header's count. It gets run 0 and sorts
   last, visibly. */
function runIndexByTask(steps) {
  const m = new Map();
  steps.forEach((s) => m.set(String(s.task_id || ""), s.v));
  return m;
}

const FACETS = [
  ["portrait", "portrait", (it) => {
    const w = parseInt(it.w, 10), h = parseInt(it.h, 10);
    return Number.isFinite(w) && Number.isFinite(h) && h > w;
  }],
  ["video", "video", (it) => !!it.is_video],
  ["star", "★", (it) => (it.rating || 0) > 0],
];

export default function SeriesModal({ sid, onClose, onOpenDetails }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [run, setRun] = useState(-1);          // -1 = All runs
  const [sort, setSort] = useState("run");     // "run" | "new"
  const [facets, setFacets] = useState([]);    // active facet keys, ANDed
  const seq = useRef(0);
  const panelRef = useRef(null);

  useEffect(() => {
    if (!sid) return;
    const mine = ++seq.current;
    setLoading(true);
    setData(null);
    setRun(-1);
    setFacets([]);
    fetchSeriesStack(sid).then((d) => {
      if (mine !== seq.current) return;
      setData(d);
      setLoading(false);
    });
  }, [sid]);

  /* Esc goes STRAIGHT BACK -- one key, one level, no ladder. That is the whole
     point of B3: the gallery underneath was never disturbed, so closing is the
     entire undo. Capture phase, because this modal sits over the grid whose own
     arrow-key handler is live (App gates that on the modal being shut, but the
     capture listener makes the ordering explicit rather than incidental). */
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  // Focus the panel on open so Esc and Tab land inside it rather than in the grid.
  useEffect(() => { if (panelRef.current) panelRef.current.focus(); }, [sid]);

  const steps = (data && data.steps) || [];
  const byTask = useMemo(() => runIndexByTask(steps), [steps]);

  /* Every tile, with its run number and its index WITHIN that run resolved once.
     The within-run index follows the order the listing already returned rows in,
     which for a task's outputs is #33's batch order where it is known -- the same
     order the sibling strip and /api/siblings use, so r2·3 means the same picture
     everywhere in the app. */
  const tiles = useMemo(() => {
    const items = (data && data.items) || [];
    const seen = new Map();
    return items.map((it) => {
      const rn = byTask.get(String(it.task_id || "")) || 0;
      const i = (seen.get(rn) || 0) + 1;
      seen.set(rn, i);
      return { it, rn, i, badge: "r" + rn + "·" + i };
    });
  }, [data, byTask]);

  // Run counts come from the RUNS themselves (steps[].n), not from the tiles: the
  // rail describes the series, and must not drift when a facet chip is on.
  const shown = useMemo(() => {
    const active = FACETS.filter(([k]) => facets.includes(k));
    let out = tiles.filter((t) => (run < 0 || t.rn === run + 1)
      && active.every(([, , test]) => test(t.it)));
    if (sort === "run") {
      out = out.slice().sort((a, b) => (a.rn - b.rn) || (a.i - b.i));
    } else {
      // newest first, flat across every run; created_at is an ISO-ish string, so a
      // plain string compare is chronological. media_id breaks ties deterministically.
      out = out.slice().sort((a, b) =>
        String(b.it.created_at || "").localeCompare(String(a.it.created_at || ""))
        || String(b.it.media_id).localeCompare(String(a.it.media_id)));
    }
    return out;
  }, [tiles, run, sort, facets]);

  const toggleFacet = (k) =>
    setFacets((old) => (old.includes(k) ? old.filter((x) => x !== k) : old.concat(k)));

  if (!sid) return null;

  const title = (data && data.title) || "Series";
  const nImages = data ? (data.count_images != null ? data.count_images : tiles.length) : 0;
  const nRuns = steps.length;

  const seg = (on) => "mgss-seg" + (on ? " on" : "");
  const railRow = (on) => "mgss-run" + (on ? " on" : "");

  return (
    <>
      <div className="mgss-scrim" onClick={onClose} />
      <div className="mgss" role="dialog" aria-modal="true" aria-label={title + " — the series"}
        ref={panelRef} tabIndex={-1}>
        <div className="mgss-head">
          <span className="mgss-title">{title} — the series</span>
          <span className="mgss-meta">
            {nImages} image{nImages === 1 ? "" : "s"} · {nRuns} run{nRuns === 1 ? "" : "s"}
          </span>
          <span className="mgss-sp" />
          {/* Sort: run № orders by run then index; newest is flat reverse-chronology. */}
          <div className="mgss-segs" role="group" aria-label="Sort">
            <button type="button" className={seg(sort === "run")} aria-pressed={sort === "run"}
              title="By run, then by position within the run" onClick={() => setSort("run")}>run №</button>
            <button type="button" className={seg(sort === "new")} aria-pressed={sort === "new"}
              title="Newest first, across every run" onClick={() => setSort("new")}>newest</button>
          </div>
          <span className="mgss-esc">Esc ↩ gallery</span>
          <button type="button" className="mgss-x" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="mgss-body">
          <div className="mgss-rail">
            <button type="button" className={railRow(run < 0)} onClick={() => setRun(-1)}>
              <span className="mgss-dot" aria-hidden="true" />
              <span className="mgss-runtext">
                <span className="mgss-runname">All runs</span>
                <span className="mgss-runmeta">{nImages} image{nImages === 1 ? "" : "s"}</span>
              </span>
            </button>
            {steps.map((s, i) => {
              // The date of a run is the day its own pictures carry -- read off a
              // member row rather than guessed from the series span, which only
              // knows its two ends.
              const first = tiles.find((t) => t.rn === s.v);
              const day = first ? (localDay(first.it.created_at) || first.it.date || "") : "";
              return (
                <button
                  key={s.task_id} type="button" className={railRow(run === i)}
                  style={{ marginLeft: 8 + i * 7 }}
                  title={s.label || ("Run " + s.v)}
                  onClick={() => setRun(i)}
                >
                  <span className="mgss-dot" aria-hidden="true" />
                  <span className="mgss-runtext">
                    <span className="mgss-runname">Run {s.v}{s.label ? " · " + s.label : ""}</span>
                    <span className="mgss-runmeta">
                      {s.n} img{day ? " · " + day : ""}
                    </span>
                  </span>
                </button>
              );
            })}
            {/* Facet chips compress into the rail's footer and AND with the run
                pick above them -- the handoff's own arrangement. */}
            <div className="mgss-facets">
              {FACETS.map(([k, label]) => (
                <button key={k} type="button"
                  className={"mgss-facet" + (facets.includes(k) ? " on" : "")}
                  aria-pressed={facets.includes(k)}
                  title={"Only " + (k === "star" ? "rated" : k) + " — narrows whatever run is picked"}
                  onClick={() => toggleFacet(k)}>{label}</button>
              ))}
            </div>
          </div>

          <div className="mgss-grid">
            {loading ? (
              <p className="mgss-note">Opening the series…</p>
            ) : !data ? (
              <p className="mgss-note">This series is no longer in the catalog.</p>
            ) : shown.length ? (
              shown.map((t) => (
                <button
                  key={t.it.media_id} type="button" className="mgss-tile"
                  title={"Run " + t.rn + ", image " + t.i + " — open the record"}
                  onClick={() => onOpenDetails(t.it.media_id)}
                >
                  <img src={t.it.thumb} alt="" loading="lazy" decoding="async" />
                  <span className="mgss-badge">{t.badge}</span>
                  {t.it.is_video ? <span className="mgss-v">▶</span> : null}
                </button>
              ))
            ) : (
              <p className="mgss-note">Nothing in this run matches those chips.</p>
            )}
            {data && data.truncated ? (
              <p className="mgss-note mgss-wide">
                This series is larger than one view — showing the first {tiles.length}.
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </>
  );
}
