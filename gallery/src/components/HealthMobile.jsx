import React from "react";
import useHealth, { fmt } from "../hooks/useHealth.js";
import "../styles/overlays.css";
import "../styles/control-mobile.css";
import "../styles/create-mobile.css";
import "../styles/menu-screens-mobile.css";

/* Collection Health -- mobile screen (design spec: Moonglade Mobile.dc.html
   screenIsHealth block, lines 565-574 & demo data at 687-690). Pushed via
   MobileScreen.jsx from AppMobile.jsx's Menu sheet, replacing that
   destination's former honest placeholder. Data layer: useHealth.js, the
   EXACT hook HealthOverlay.jsx (desktop) now consumes too -- live GET
   /api/health, no second fetch of the same route.

   ACTION WIRING (deliberately NOT the hook's job, per useHealth.js's own
   header comment): HealthOverlay.jsx closes its overlay and calls App.jsx's
   applyAdvanced() directly on a filter tap. There's no overlay to close
   here, so AppMobile.jsx wires onModelFilter/onTagFilter/onLoraFilter to
   lib.applyAdvanced() -- the SAME already-lifted useLibrary() instance
   GalleryMobile.jsx reads/writes -- plus a tab switch to Gallery and a
   screen-close, so tapping a filter actually SHOWS the filtered result.
   "Reuse existing UI mechanisms over building parallel UI."

   Real-data deviations from the design mock, disclosed here for the owner's
   review -- same standard every prior mobile surface this session used:

   1. STAT COUNT: the design's mock shows 8 tiles (Images on disk/Storage
      used/Catalog rows/Full-meta/Published/Total likes/Duplicates/
      Uncataloged) -- missing Model named/Rated/Missing files/Reclaimable,
      which /api/health DOES return and HealthOverlay.jsx DOES show on
      desktop. Dropping four real, working stat tiles just to match a
      placeholder mock's count would be exactly the "skip real data reuse"
      the brief says installing-as-specified does not license -- so this
      shows all 12, the same set desktop shows, in the design's own 2-col
      grid shape.
   2. "TOP MODELS": absent from the design mock entirely, but real,
      already-wired data desktop shows (a live filter, not decoration) --
      added here as its own bar-list section (reusing the exact
      .mgh-row/.model shapes the design's own "Images by month" bars already
      establish) rather than silently dropped.
   3. TAG/LORA CHIPS: the design's mock chips are inert (chipOffStyle, no
      onClick anywhere in that block). Desktop's are real, live filter
      buttons. Per "reuse existing UI mechanisms over building parallel UI",
      these stay live here too -- tapping one filters the SAME Gallery tab
      the hamburger menu was opened from, not a decorative no-op.
   4. DUPLICATES/RECLAIMABLE: HealthOverlay.jsx opens DuplicateReviewOverlay.jsx
      on a tap; no mobile Duplicate Review surface exists ANYWHERE in this
      app yet. Per this round's explicit scope (disclose the gap, don't
      build the surface), these two tiles render as PLAIN, non-clickable
      stat cards here -- same real numbers, no dead tap pretending to lead
      somewhere.
   5. SCOPED OUT, ON PURPOSE: the prompt word-cloud and folder-breakdown
      sections (both real, both on desktop) aren't in the design's mobile
      spec at all, and are lower-signal, more decorative sections on a
      screen already carrying 12 stats + 2 bar-lists + 2 chip rows -- left
      out of THIS pass as a deliberate scope trim, not an oversight or a
      "skip real data" call (unlike point 1, nothing here is being hidden
      that the design itself asked for).
   6. UNCATALOGED FOOTER: real count (not the mock's hardcoded "4"), and --
      since Import is a real screen this SAME pass -- tapping it opens the
      Import screen directly, a real destination that didn't exist before
      this batch, instead of the design's plain static note. */

export default function HealthMobile({ onModelFilter, onTagFilter, onLoraFilter, onOpenImport }) {
  const { h, err, stats, monthMax, modelMax, buckets } = useHealth();
  void buckets; // folder breakdown intentionally not shown on mobile this pass -- see header comment, point 5

  if (err) return <div className="mgh-loading">couldn't load health data — {err}</div>;
  if (!h) return <div className="mgh-loading">measuring the collection…</div>;

  return (
    <>
      <div className="ctm-statgrid" style={{ marginBottom: 16 }}>
        {stats.map((st) => (
          <div className="ctm-statcard" key={st.label}>
            <div className={"ctm-statnum" + (st.gold ? " gold" : "")}>{st.value}</div>
            <div className="ctm-statlabel">{st.label}</div>
          </div>
        ))}
      </div>

      <div className="cm-subhead">Images by month</div>
      <div className="mgh-rows">
        {(h.by_month || []).map(([label, count]) => (
          <div className="mgh-row" key={label}>
            <div className="mgh-rowlabel">{label}</div>
            <div className="mgh-barwrap">
              <div className="mgh-bar" style={{ width: Math.max(0.5, (count / monthMax) * 100) + "%" }} />
            </div>
            <div className="mgh-rowcount">{fmt(count)}</div>
          </div>
        ))}
      </div>

      <div className="cm-subhead">Top models</div>
      <div className="mgh-rows">
        {(h.top_models || []).map(([label, count]) => (
          <div className="mgh-row" key={label}>
            <div className="mgh-rowlabel model" title={label}>{label}</div>
            <div className="mgh-barwrap">
              <div className="mgh-bar model" style={{ width: Math.max(0.5, (count / modelMax) * 100) + "%" }} />
            </div>
            <button type="button" className="mgh-chip mgh-rowcount model"
              style={{ border: "none", background: "none", padding: 0 }}
              title={"Filter the gallery to " + label}
              onClick={() => onModelFilter && onModelFilter(label)}>
              {fmt(count)}
            </button>
          </div>
        ))}
      </div>

      <div className="cm-subhead">Top tags</div>
      <div className="mgh-chips">
        {(h.top_tags || []).map(([label, count]) => (
          <button type="button" className="mgh-chip" key={label}
            title={"Filter the gallery to tag: " + label}
            onClick={() => onTagFilter && onTagFilter(label)}>
            {label} <span className="n">{fmt(count)}</span>
          </button>
        ))}
      </div>

      <div className="cm-subhead">Top LoRAs</div>
      <div className="mgh-chips">
        {(h.top_loras || []).map(([label, count]) => (
          <button type="button" className="mgh-chip" key={label}
            title={"Filter the gallery to LoRA: " + label}
            onClick={() => onLoraFilter && onLoraFilter(label)}>
            {label} <span className="n">{fmt(count)}</span>
          </button>
        ))}
      </div>

      {h.uncataloged > 0 && (
        onOpenImport ? (
          <button type="button" className="mnu-notebtn" onClick={onOpenImport}>
            · {fmt(h.uncataloged)} file(s) on disk aren't in the catalog — tap to Import and catalog them.
          </button>
        ) : (
          <div className="mgh-note">
            · {fmt(h.uncataloged)} file(s) on disk aren't in the catalog — use ⬆ Import to catalog them.
          </div>
        )
      )}
    </>
  );
}
