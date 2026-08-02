import React, { useEffect, useState } from "react";
import "../styles/overlays.css";
import "../styles/myart-contests.css";

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
     never wires an actual handler to it. */

const fmt = (n) => (n == null ? "—" : Number(n).toLocaleString());

export default function MyArtOverlay({ onClose, onOpenPost }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    let dead = false;
    fetch("/api/your-art")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status))))
      .then((data) => { if (!dead) setD(data); })
      .catch((e) => { if (!dead) setErr(String(e.message || e)); });
    return () => { dead = true; };
  }, []);

  const totals = d ? d.totals || {} : {};
  const items = d ? d.items || [] : [];
  const stats = d ? [
    { value: fmt(totals.count), label: "PUBLISHED" },
    { value: fmt(totals.likes), label: "TOTAL LIKES" },
    { value: fmt(totals.comments), label: "COMMENTS" },
    { value: d.views_synced ? fmt(totals.views_top) : "—", label: "VIEWS (TOP " + items.length + ")" },
  ] : [];

  const maxViews = items.length ? Math.max(1, ...items.map((r) => r.views || 0)) : 1;

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
                    <div className="mgma-stat-value">{st.value}</div>
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
                    const meta = fmt(r.views) + " views · " + fmt(r.likes) + " likes"
                      + (r.comments ? " · " + fmt(r.comments) + " comments" : "");
                    return (
                      <button type="button" className="mgma-post" key={r.media_id}
                        onClick={() => onOpenPost && onOpenPost(r.media_id)}>
                        <div className="mgma-rank">{i + 1}</div>
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
