import React from "react";
import useHealth, { fmt } from "../hooks/useHealth.js";
import useBrokenFiles from "../hooks/useBrokenFiles.js";
import StorageBars from "./StorageBars.jsx";
import BrokenFiles from "./BrokenFiles.jsx";
import { tileChip } from "../lib/brokenFilesCore.js";
import { subscribeBrokenFilesIntent, takeBrokenFilesIntent } from "../lib/brokenFilesNav.js";
import { onRunEnd } from "../lib/brokenFixRun.js";
import "../styles/overlays.css";
import useScrollLock from "../hooks/useScrollLock.js";

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

/* Gallery-era pass (handoff-2026-08-06 §4): the two chart sections gained switchable,
   animated views. Chart math is the DC's own derivation verbatim (Frontend
   Gallery.dc.html healthVals): trend = 680×150 SVG on a SQRT scale so tiny months
   still read, donut = conic-gradient of the top 5 models + Other. */
const DONUT_COLORS = ["var(--accent)", "var(--mauve)", "var(--emerald)", "var(--gold)", "var(--blue, #8fb8e8)", "var(--overlay0)"];

function trendData(months) {
  const W = 680, H = 150, PAD = 6;
  const n = months.length;
  const maxv = Math.sqrt(Math.max(1, Math.max(...months.map((m) => m[1]))));
  const pts = months.map((m, i) => {
    const x = n <= 1 ? 0 : (i / (n - 1)) * W;
    const y = H - PAD - (Math.sqrt(m[1]) / maxv) * (H - PAD * 2);
    return [Math.round(x * 10) / 10, Math.round(y * 10) / 10];
  });
  const linePath = pts.map((p, i) => (i === 0 ? "M" : "L") + p[0] + " " + p[1]).join(" ");
  const areaPath = linePath + " L" + W + " " + H + " L0 " + H + " Z";
  const peakIdx = months.reduce((b, m, i) => (m[1] > months[b][1] ? i : b), 0);
  return { W, H, pts, linePath, areaPath, peakIdx };
}

function donutData(models) {
  const top = models.slice(0, 5);
  const othersN = models.slice(5).reduce((a, m) => a + m[1], 0);
  const data = top.map((m) => [m[0], m[1]]).concat(othersN > 0 ? [["Other", othersN]] : []);
  const total = data.reduce((a, d) => a + d[1], 0) || 1;
  let acc = 0;
  const stops = data.map((d, i) => {
    const from = (acc / total) * 100; acc += d[1];
    const to = (acc / total) * 100;
    return DONUT_COLORS[i % DONUT_COLORS.length] + " " + from.toFixed(2) + "% " + to.toFixed(2) + "%";
  });
  return { data, total, gradient: "conic-gradient(" + stops.join(", ") + ")" };
}

export default function HealthOverlay({ onClose, onModelFilter, onTagFilter, onLoraFilter, onOpenDuplicates, onStoragePick, onOpenDetails }) {
  useScrollLock();   // page never scrolls behind a full-screen panel (2026-08-06)
  // A Broken files fix run changed the library under this panel: the tiles re-measure when it ends.
  const [runsEnded, setRunsEnded] = React.useState(0);
  React.useEffect(() => onRunEnd(() => setRunsEnded((n) => n + 1)), []);
  const { h, err, stats, monthMax, modelMax, tier, buckets, storage } = useHealth(runsEnded);
  const [monthView, setMonthView] = React.useState("trend");   // DC default
  const [modelView, setModelView] = React.useState("bars");    // DC default

  /* Session W (W1a): the Broken files section, under the tiles and above the storage bars, only
     while the last integrity check found broken rows. A problem tile opens it at its chip; the
     Control Panel's "Review ▸" and a fix run's Activity row open it at All (lib/brokenFilesNav.js:
     on mount, or live when Health is already up). */
  const bf = useBrokenFiles();
  const [bfChip, setBfChip] = React.useState("all");
  const bfRef = React.useRef(null);
  const [bfGo, setBfGo] = React.useState(() => takeBrokenFilesIntent());
  React.useEffect(() => subscribeBrokenFilesIntent(() => setBfGo(takeBrokenFilesIntent())), []);
  const bfShown = !!(bf.doc && bf.doc.counts && bf.doc.counts.all > 0);
  const openBroken = (chip) => setBfGo(chip || "all");
  React.useEffect(() => {
    if (!bfGo || !bfShown || !h) return;
    setBfChip(bf.doc.counts[bfGo] > 0 ? bfGo : "all");
    const el = bfRef.current;
    if (el && el.scrollIntoView) el.scrollIntoView({ behavior: "smooth", block: "start" });
    setBfGo(null);
  }, [bfGo, bfShown, h]);

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
                {stats.map((st) => {
                  // Session W: a problem tile with rows on the Broken files list wears peach and
                  // opens the list at its chip; a clean library reads 0 with no peach.
                  const chip = bfShown ? tileChip(st.label, bf.doc.counts) : null;
                  const flag = !!chip;
                  return (
                  <div className={"mgh-stat" + (flag ? " flag" : "")} key={st.label}>
                    <div className="mgh-stat-label">{st.label}</div>
                    {flag ? (
                      <button type="button" className="mgh-stat-value flag"
                        style={{ display: "block", width: "100%", border: "none", background: "none",
                          padding: 0, font: "inherit", textAlign: "left" }}
                        title="Show these in Broken files"
                        onClick={() => openBroken(chip)}>
                        {st.value}
                      </button>
                    ) : st.dup ? (
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
                  );
                })}
              </div>

              {bfShown ? (
                <BrokenFiles bf={bf} chip={bfChip} setChip={setBfChip} sectionRef={bfRef}
                  onOpenDetails={onOpenDetails} />
              ) : null}

              {/* N6: Storage used, as three stacked bars. A segment closes this and opens the
                  gallery filtered to it (App's onStoragePick). */}
              <StorageBars storage={storage} onPick={onStoragePick} />

              <div className="mgh-hrow">
                <div className="mgh-h">Images over time</div>
                <div className="mgh-seg">
                  {[["trend", "Trend"], ["bars", "Bars"]].map(([k, label]) => (
                    <button type="button" key={k} className={"mgh-segbtn" + (monthView === k ? " on" : "")}
                      onClick={() => setMonthView(k)}>{label}</button>
                  ))}
                </div>
              </div>
              {monthView === "trend" && (h.by_month || []).length > 0 ? (() => {
                const months = h.by_month;
                const t = trendData(months);
                return (
                  <div className="mgh-trendbox">
                    <svg viewBox={"0 0 " + t.W + " " + t.H} preserveAspectRatio="none"
                      style={{ width: "100%", height: 150, display: "block", overflow: "visible" }}>
                      <defs>
                        <linearGradient id="hArea" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.42" />
                          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
                        </linearGradient>
                      </defs>
                      <path d={t.areaPath} fill="url(#hArea)" style={{ animation: "hArea .9s ease .25s both" }} />
                      <path d={t.linePath} fill="none" stroke="var(--accent)" strokeWidth="2"
                        strokeLinejoin="round" strokeLinecap="round"
                        style={{ strokeDasharray: 3000, strokeDashoffset: 3000, animation: "hDraw 1.5s cubic-bezier(.3,.8,.3,1) .1s forwards" }} />
                      {t.pts.map((p, i) => (
                        <circle key={i} cx={p[0]} cy={p[1]} r="3" fill="var(--mauve)" stroke="#0a0818" strokeWidth="1.5"
                          style={{ opacity: 0, transformBox: "fill-box", transformOrigin: "center",
                            animation: "hDot .3s ease " + (0.4 + i * 0.05).toFixed(2) + "s both" }}>
                          <title>{months[i][0] + " · " + fmt(months[i][1])}</title>
                        </circle>
                      ))}
                    </svg>
                    <div className="mgh-trendfoot">
                      <span>{months[0][0]}</span>
                      <span>▲ {months[t.peakIdx][0]} · {fmt(months[t.peakIdx][1])}</span>
                      <span>{months[months.length - 1][0]}</span>
                    </div>
                  </div>
                );
              })() : (
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
              )}

              <div className="mgh-hrow">
                <div className="mgh-h">Top models</div>
                <div className="mgh-seg">
                  {[["bars", "Bars"], ["donut", "Share"]].map(([k, label]) => (
                    <button type="button" key={k} className={"mgh-segbtn" + (modelView === k ? " on" : "")}
                      onClick={() => setModelView(k)}>{label}</button>
                  ))}
                </div>
              </div>
              {modelView === "donut" && (h.top_models || []).length > 0 ? (() => {
                const d = donutData(h.top_models);
                return (
                  <div className="mgh-donutwrap">
                    <div className="mgh-donut">
                      <div className="mgh-donutring" style={{ background: d.gradient }} />
                      <div className="mgh-donuthole">
                        <div>
                          <div className="mgh-donuttotal">{fmt(d.total)}</div>
                          <div className="mgh-donutlab">TAGGED</div>
                        </div>
                      </div>
                    </div>
                    <div className="mgh-donutlegend">
                      {d.data.map(([label, count], i) => (
                        <div className="mgh-donutrow" key={label}>
                          <span className="mgh-donutdot" style={{ background: DONUT_COLORS[i % DONUT_COLORS.length] }} />
                          <span className="mgh-donutname" title={label}>{label}</span>
                          <span className="mgh-donutpct">{Math.round((count / d.total) * 100)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })() : (
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
              )}

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
                  · {fmt(h.uncataloged)} file(s) on disk aren't in the catalog. Use Import
                  (in the row under the banner), or run --import-local, to catalog them.
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
