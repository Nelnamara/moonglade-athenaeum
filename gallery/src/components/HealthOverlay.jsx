import React from "react";
import useHealth, { fmt } from "../hooks/useHealth.js";
import "../styles/overlays.css";

/* The Collection Health overlay — the first of the six designed nav overlays
   to port (Frontend Gallery DC, the ovHealth slab). In-app modal, NOT the
   /health page: same data, served as JSON by GET /api/health (the gap audit's
   route #10), same computation the page runs.

   Live affordances the DC draws that we wire to REAL filters (each closes the
   overlay and applies through App's applyAdvanced — the same one-patch commit
   path every filter control uses):
     · a Top-model count  → filter the gallery to that model
     · a tag chip         → filter to that tag
     · a LoRA chip        → filter to that LoRA
     · Duplicates/Reclaimable → opens the Duplicate Review overlay
       (DuplicateReviewOverlay.jsx, live 2026-08-02; onOpenDuplicates below)

   DATA LAYER (2026-08-03): the fetch + stats/monthMax/modelMax/tier/buckets
   derivations that used to live inline here were mechanically lifted into
   useHealth.js so the new mobile Health screen (HealthMobile.jsx) can
   consume the EXACT same logic -- see that hook's own header comment. This
   file is refactored to CONSUME it rather than hold a second, drifting copy
   of the same fetch. The filter/Duplicate-Review callbacks below are
   unchanged -- they stay props, per useHealth.js's own note on why. */

export default function HealthOverlay({ onClose, onModelFilter, onTagFilter, onLoraFilter, onOpenDuplicates }) {
  const { h, err, stats, monthMax, modelMax, tier, buckets } = useHealth();

  return (
    <>
      <div className="mgv-scrim" onClick={onClose} />
      <div className="mgv-host">
        <div className="mgv-slab" role="dialog" aria-label="Collection Health">
          <div className="mgv-titlerow">
            <div className="mgv-title">♡ Collection Health</div>
            <button type="button" className="mgv-x" onClick={onClose} aria-label="Close">×</button>
          </div>

          {!h && !err && <div className="mgh-loading">measuring the collection…</div>}
          {err && <div className="mgh-loading">couldn't load health data — {err}</div>}

          {h && (
            <>
              <div className="mgh-stats">
                {stats.map((st) => (
                  <div className="mgh-stat" key={st.label}>
                    <div className="mgh-stat-label">{st.label}</div>
                    {st.dup ? (
                      <button type="button" className="mgh-stat-value dup"
                        style={{ display: "block", width: "100%", border: "none", background: "none",
                          padding: 0, font: "inherit", textAlign: "left" }}
                        title="Open Duplicate Review"
                        onClick={() => onOpenDuplicates && onOpenDuplicates()}>
                        {st.value}
                      </button>
                    ) : (
                      <div className={"mgh-stat-value" + (st.gold ? " gold" : "")}>
                        {st.value}
                      </div>
                    )}
                  </div>
                ))}
              </div>

              <div className="mgh-h">Images by month</div>
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

              <div className="mgh-h">Top models</div>
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

              <div className="mgh-h">Top tags &amp; contests</div>
              <div className="mgh-chips">
                {(h.top_tags || []).map(([label, count]) => (
                  <button type="button" className="mgh-chip" key={label}
                    title={"Filter the gallery to tag: " + label}
                    onClick={() => onTagFilter && onTagFilter(label)}>
                    {label} <span className="n">{fmt(count)}</span>
                  </button>
                ))}
              </div>

              <div className="mgh-h">Prompt word cloud</div>
              <div className="mgh-cloud">
                {(h.top_words || []).map(([word], i) => (
                  <span className={"mgh-word " + tier(i)} key={word}>{word}</span>
                ))}
              </div>

              <div className="mgh-h">Top LoRAs</div>
              <div className="mgh-chips">
                {(h.top_loras || []).map(([label, count]) => (
                  <button type="button" className="mgh-chip" key={label}
                    title={"Filter the gallery to LoRA: " + label}
                    onClick={() => onLoraFilter && onLoraFilter(label)}>
                    {label} <span className="n">{fmt(count)}</span>
                  </button>
                ))}
              </div>

              {buckets.length > 0 && (
                <>
                  <div className="mgh-h">Folder breakdown</div>
                  <div className="mgh-folders">
                    {buckets.map(([name, count], i) => (
                      <span key={name}>{i > 0 ? " · " : ""}<b>{fmt(count)}</b> {name}</span>
                    ))}
                  </div>
                </>
              )}

              {h.uncataloged > 0 && (
                <div className="mgh-note">
                  · {fmt(h.uncataloged)} file(s) on disk aren't in the catalog. Use the
                  classic gallery's ↑ Import button, or run --import-local, to catalog them.
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
