import React from "react";
import useMyArt, { fmt } from "../hooks/useMyArt.js";
import "../styles/control-mobile.css";
import "../styles/create-mobile.css";
import "../styles/myart-contests.css";
import "../styles/overlays.css";

/* My Art -- mobile screen (design spec: Moonglade Mobile.dc.html screenIsMyArt
   block, lines 500-508 & demo data at 676-677). Pushed via MobileScreen.jsx
   from AppMobile.jsx's Menu sheet, replacing that destination's former
   honest placeholder. Data layer: useMyArt.js, the EXACT hook
   MyArtOverlay.jsx (desktop) now consumes too -- live GET /api/your-art, no
   second fetch of the same route.

   Real-data deviations from the design mock, disclosed here for the owner's
   review -- same standard every prior mobile surface this session used, not
   decided unilaterally:

   1. STAT LABELS/ORDER: the design's demo stats are Published/Views/Likes/
      Comments -- a plain "Views" total. The real /api/your-art route has no
      such field, only a synced top-N view count (views_top, "—" until a
      --sync-artworks run) -- exactly what MyArtOverlay.jsx's own header
      comment already discloses adapting for desktop. This screen keeps THAT
      real label set (Published/Total Likes/Comments/Views-Top-N) rather
      than inventing a plain Views number the API can't back.
   2. STAT-CARD SHAPE: the design draws label-above-value; MyArtOverlay.jsx's
      own desktop CSS (.mgma-stat) draws value-above-label -- a real
      inconsistency between the mock and its own shipped desktop port.
      Rather than pick a third order, this reuses ControlMobile.jsx's
      ALREADY-SHIPPED .ctm-statgrid/.ctm-statcard (value-above-label) for
      cohesion with the one other mobile screen with a stat grid so far
      (Control's "At a glance"), per "one cohesive app, one design language"
      -- not a random pick.
   3. SECTION COPY: "Top posts by views" matches the design's copy exactly
      (dropping desktop's "Your … :" wording) -- a pure text call, no data
      implication either way.
   4. ROW CONTENT: unlike the design's plain rank+title+meta row, this keeps
      the comments segment and the view-share bar MyArtOverlay.jsx's real
      data already computes -- real, already-fetched numbers the design's
      static mock never had to address, not invented.
   5. ROW CLICK-THROUGH (the one gap): MyArtOverlay.jsx wires a row tap to
      open that post's real Details view (onOpenPost). Mobile Details/
      Lightbox surfaces exist now (ImageDetailsMobile.jsx/LightboxMobile.jsx),
      but this screen has no route to either from here (it isn't handed an
      onOpenDetails prop, and its own media_id shape isn't confirmed against
      the Gallery tab's loaded items array). Matching the same disclosed-gap
      treatment (see Health's Duplicate Review link), rows here are NOT
      clickable this pass -- wiring a tap to a destination this screen can't
      actually reach yet would be worse than the design's own static row, not
      better. */

export default function MyArtMobile() {
  const { d, err, items, stats, maxViews } = useMyArt();

  if (err) return <div className="mgh-loading">couldn't load — {err}</div>;
  if (!d) return <div className="mgh-loading">loading your published art…</div>;

  return (
    <>
      <div className="ctm-statgrid" style={{ marginBottom: 16 }}>
        {stats.map((st) => (
          <div className="ctm-statcard" key={st.label}>
            <div className="ctm-statnum">{st.value}</div>
            <div className="ctm-statlabel">{st.label}</div>
          </div>
        ))}
      </div>

      <div className="cm-subhead">Top posts by views</div>
      {items.length === 0 ? (
        <div className="mgh-loading" style={{ padding: "24px 0" }}>
          Nothing published yet — publish an image from its Details page.
        </div>
      ) : (
        <div className="mgma-posts" style={{ gridTemplateColumns: "1fr" }}>
          {items.map((r, i) => {
            const title = (r.title || "").trim() || (r.prompt_preview || "").trim() || "untitled";
            const meta = fmt(r.views) + " views · " + fmt(r.likes) + " likes"
              + (r.comments ? " · " + fmt(r.comments) + " comments" : "");
            return (
              <div className="mgma-post" key={r.media_id} style={{ cursor: "default" }}>
                <div className="mgma-rank">{i + 1}</div>
                <div className="mgma-postbody">
                  <div className="mgma-posttitle" title={title}>{title}</div>
                  <div className="mgma-postmeta">{meta}</div>
                  <div className="mgma-barwrap">
                    <div className="mgma-bar" style={{ width: Math.max(2, ((r.views || 0) / maxViews) * 100) + "%" }} />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <div className="mgma-footnote">
        Live view counts, fetched fresh{d.views_synced ? "" : " (unavailable this load — showing catalog data only)"}.
        Likes/comments from your last <code>--sync-artworks</code>.
      </div>
    </>
  );
}
