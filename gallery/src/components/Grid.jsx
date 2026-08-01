import React from "react";
import Stars from "./Stars.jsx";

/* The grid: glass cards over the void, with REAL pagination -- Prev/Next + page
   numbers, matching the classic gallery. Infinite scroll was tried here and was
   wrong for this surface (owner QA 2026-07-30: "why have a per page setting"
   if the grid never stops loading, and a 35k-deep library makes an ever-growing
   DOM a real problem). Infinite scroll stays exactly where it already lived and
   belongs -- the picker, which is the shared <mg-gallery-picker> component, not
   this one. */
export default function Grid({
  items, total, loading, page, pages, goToPage,
  blur, selectMode, selected, toggleSelected, openLightbox, onRate,
}) {
  const go = (p) => {
    if (p < 1 || p > pages || p === page) return;
    goToPage(p);
    window.scrollTo({ top: 0, behavior: "instant" in document.documentElement.style ? "instant" : "auto" });
  };

  return (
    <div className={"gridwrap" + (blur ? " blur-on" : "")}>
      {/* The separator bar the classic had between the controls and the grid:
          count left, browsing tip right (verbatim from master — the owner missed
          it, and it does real work giving the grid air from the header instead of
          the cards butting straight into the strip). */}
      <div className="tipbar">
        {total != null && (
          <span className="tb-count">
            {Number(total).toLocaleString()} match{total === 1 ? "" : "es"}
          </span>
        )}
        <span className="sp" />
        <span className="tb-tip">
          tip: click an image to open the lightbox · arrow keys to browse · F for slideshow
        </span>
      </div>
      <div className="grid" aria-busy={loading}>
        {items.map((it, i) => {
          const isSel = selected.has(it.media_id);
          const fname = it.filename || "";
          const shortName = fname.length > 22 ? fname.slice(0, 10) + "…" + fname.slice(-9) : fname;
          return (
            <figure
              key={it.media_id}
              className={
                "gcard" +
                (it.is_nsfw ? " nsfw" : "") +
                (isSel ? " sel" : "")
              }
              onClick={() =>
                selectMode ? toggleSelected(it.media_id) : openLightbox(i)
              }
            >
              {selectMode && (
                <span className={"tick" + (isSel ? " on" : "")}>✓</span>
              )}
              {it.is_video ? <span className="vbadge">▶</span> : null}
              {it.source ? <span className="srcbadge" title={"source: " + it.source}>{it.source}</span> : null}
              <img loading="lazy" src={it.thumb} alt="" />
              <figcaption>
                <span className="model">{it.model || "—"}</span>
                <span className="date">{it.date || ""}</span>
                {fname ? <span className="fname" title={fname}>{shortName}</span> : null}
                <Stars mediaId={it.media_id} rating={it.rating} onRate={onRate} />
              </figcaption>
            </figure>
          );
        })}
      </div>
      {loading && <div className="sentinel">summoning…</div>}
      {!loading && pages > 1 && (
        <PageBar page={page} pages={pages} go={go} />
      )}
    </div>
  );
}

/* Windowed page numbers with ellipses -- first, last, current ±2 -- because a
   35k-image library at 100/page is ~350 pages; a flat list would be absurd. */
function PageBar({ page, pages, go }) {
  const nums = [];
  const add = (n) => { if (!nums.includes(n)) nums.push(n); };
  add(1); add(pages);
  for (let d = -2; d <= 2; d++) { const n = page + d; if (n >= 1 && n <= pages) add(n); }
  nums.sort((a, b) => a - b);
  const withGaps = [];
  nums.forEach((n, i) => {
    if (i > 0 && n - nums[i - 1] > 1) withGaps.push("…" + n);
    withGaps.push(n);
  });
  return (
    <nav className="pagebar" aria-label="Pages">
      <button className="pg-nav" disabled={page <= 1} onClick={() => go(page - 1)}>‹ Prev</button>
      {withGaps.map((n) =>
        typeof n === "string" ? (
          <span key={n} className="pg-ellipsis">…</span>
        ) : (
          <button key={n} className={"pg-num" + (n === page ? " current" : "")}
            onClick={() => go(n)} aria-current={n === page ? "page" : undefined}>
            {n}
          </button>
        )
      )}
      <button className="pg-nav" disabled={page >= pages} onClick={() => go(page + 1)}>Next ›</button>
    </nav>
  );
}
