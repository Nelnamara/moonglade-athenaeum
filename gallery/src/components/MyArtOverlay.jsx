import React from "react";
import useMyArt, { fmt } from "../hooks/useMyArt.js";
import "../styles/overlays.css";
import "../styles/myart-contests.css";
import useScrollLock from "../hooks/useScrollLock.js";

/* "Your Art" overlay — ported from the Frontend Gallery DC's ovMyArt slab
   (lines ~567-599): stats row + top-published-by-views list. Real data from
   GET /api/your-art (top_published_rows + published_totals, enriched with
   LIVE per-artwork view counts) -- no demo numbers.

   Real-data adaptations from the DC, disclosed:
   - artStats picks 4 fields from the DC's own demo set; the real route gives
     count/likes/comments/views_top, so this shows those four instead.
   - Each row's title falls back to prompt_preview when the catalog's own
     title is blank (common for API-key-only accounts) -- the DC's demo data
     always had a title, so it never needed this.
   - Row click opens the real Details view for that image (onOpenPost), the
     same natural target every other "here's one of your images" row in this
     app already uses -- the DC's markup gives the row cursor:pointer but
     never wires an actual handler to it.

   DATA LAYER (2026-08-03): the fetch + stats/maxViews derivations that used
   to live inline here were mechanically lifted into useMyArt.js so the new
   mobile My Art screen (MyArtMobile.jsx) can consume the EXACT same logic --
   see that hook's own header comment. This file is refactored to CONSUME it
   rather than hold a second, drifting copy of the same fetch. */

export default function MyArtOverlay({ onClose, onOpenPost }) {
  useScrollLock();   // page never scrolls behind a full-screen panel (2026-08-06)
  const { d, err, items, stats, maxViews } = useMyArt();

  return (
    <>
      <div className="mgv-scrim" onClick={onClose} />
      <div className="mgv-host">
        <div className="mgv-slab mgma-slab" role="dialog" aria-label="Your Art">
          <div className="mgv-titlerow">
            <div className="mgv-title">📈 Your Art</div>
            <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
          </div>

          {!d && !err && <div className="mgh-loading">loading your published art…</div>}
          {err && <div className="mgh-loading">couldn't load — {err}</div>}

          {d && (
            <>
              <div className="mgma-stats">
                {stats.map((st) => (
                  <div className="mgma-stat" key={st.label}>
                    <div className={"mgma-stat-value" + (st.accent ? " accent" : "")}>{st.value}</div>
                    <div className="mgma-stat-label">{st.label}</div>
                  </div>
                ))}
              </div>

              <div className="mgh-h">Your top posts by views:</div>
              {items.length === 0 ? (
                <div className="mgh-loading">Nothing published yet — publish an image from its Details page.</div>
              ) : (
                <div className="mgma-posts">
                  {items.map((r, i) => {
                    const title = (r.title || "").trim() || (r.prompt_preview || "").trim() || "untitled";
                    // Frontend Gallery.dc.html:2428 -- icon-driven compact format ("👁 N ·
                    // ♥ N"), desktop-only (mobile's own design already specifies the
                    // spelled-out "N views · N likes" this used to be everywhere).
                    const meta = "👁 " + fmt(r.views) + " · ♥ " + fmt(r.likes)
                      + (r.comments ? " · 💬 " + fmt(r.comments) : "");
                    // Frontend Gallery.dc.html:2429-2430 -- rank #1 gold, #2-3 mauve, rest overlay0.
                    const tier = i === 0 ? " tier-gold" : i < 3 ? " tier-mauve" : "";
                    return (
                      <button type="button" className="mgma-post" key={r.media_id}
                        onClick={() => onOpenPost && onOpenPost(r.media_id)}>
                        <div className={"mgma-rank" + tier}>{i + 1}</div>
                        <div className="mgma-postbody">
                          <div className="mgma-posttitle" title={title}>{title}</div>
                          <div className="mgma-postmeta">{meta}</div>
                          <div className="mgma-barwrap">
                            <div className="mgma-bar" style={{ width: Math.max(2, ((r.views || 0) / maxViews) * 100) + "%" }} />
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
              <div className="mgma-footnote">
                Live view counts, fetched fresh{d.views_synced ? "" : " (unavailable this load — showing catalog data only)"}.
                Likes/comments from your last <code>--sync-artworks</code>.
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
