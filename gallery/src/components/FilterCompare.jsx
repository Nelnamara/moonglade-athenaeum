import React, { useCallback, useEffect, useRef, useState } from "react";
import MgArtFilters from "../art/artFilters.js";
import { apiUpload } from "../api.js";

/* The art-filters COMPARE OVERLAY -- Frontend Gallery.dc.html 591-658 + its getters
   (2944-2978), the Enhance sub-tab's '◉ Open filters' destination. This is the panel
   FiltersPanel.jsx used to carry as ArtFiltersPanel (the build map always meant it to be
   FilterCompare.jsx under the dock workstream); lifted here in the 2026-08-16 dock
   fidelity pass and rebuilt to the DC's geometry:

     scrim   fixed inset 0 · rgba(5,4,13,.72) · backdrop blur 7px · click closes   (592)
     layer   fixed inset 0 · grid place-items center · padding 20 · no pointer     (593)
     panel   min(1100px, 100vw-40) · max-height 92vh · radius 16 · surface0 ·
             1px surface1 · shadow 0 34px 80px -18px · padding 16px 20px 20px      (594)
     header  '◐ Art filters' 15px/800 · spacer · ✕ 28×28 chip                     (595-599)
     grid    1fr 1fr 220px · gap 16 · align start                                  (600)
     boxes   square (aspect-ratio 1) · radius 10 · base · 1px surface1 · cover     (2948)
     rail    flex col gap 12: MOONGLADE + PIXAI tile groups (3-col, gap 6, 9px .12em
             headings 2952), STRENGTH / ANGLE sliders (2966: 9px .08em; range 0-1
             step .05 / 0-360 step 1, height 3px), two button rows, the spend note (653)
   Viewport-centred, NOT anchored above the dock: the DC draws it as a page-level
   overlay (this supersedes the 2026-07-25 'placement threshold' rule, which was
   written for the old side drawer). z stays in the dock's overlay band (scrim 305,
   layer 306 -- the DC's 42/43 are relative numbers inside its own stack); toasts and
   the celebration layer (510+) stay above it.

   REAL DATA (documented divergences, checklist region 3):
   - The tiles and the preview render PixAI's + Moonglade's REAL recipes through the
     art-filter engine (AF.renderSwatch / AF.applyPreview -- per-layer blend modes and
     opacities, drift-report 7: 'implementation must render from the component, not
     from those approximations'); the DC's swatch is a fixed 2-colour 135deg gradient
     and its preview one mix-blend-mode:overlay layer. 12 recipes (5 + 7), the DC's
     FILTER_SETS count. Names come from the recipes ('Filter M1' … reads 'M1', as the
     DC labels them).
   - Save to library / Send to image gen / Publish are the REAL actions (DECISIONS
     2026-07-25 'Filter actions'): Save bakes at full resolution and POSTs to the local
     import route; Send uploads the composite (free S3 handshake) and lands it as the
     EDIT SOURCE -- the DC's fcSendToGen (2976) merely switched to the image tab; the
     label stays the DC's, the title says where it really goes (owner call pending,
     see the checklist row); Publish is DISABLED until Epic C rather than a mock close
     -- drawn as the DC's primary, at rest.
   - The spend note (653) shows the DC's '<filter> · nothing sent, nothing spent' AND
     doubles as the status line for the two server-touching exits (saved / duplicate /
     error) and the engine's dropped-layer warnings -- real outcomes the DC's stand-in
     never had to report.
   - Nothing here is a cost quote: filters composite in the browser and the exits are
     free; the DC's tile tip 'Free — click to apply' is the panel's own statement of a
     client-side operation, not the CostBadge (which stays idle in the footer).

   THE SOURCE IS SHARED: `source` is slab 1's picture (the drawer's editS.source, the
   same one Edit and the Fixer use -- DC 1513 'Pick a source image above'); the overlay
   has no picker of its own. Two <img> of the same /full/ url: the preview <img> is the
   one the engine mutates (a CSS filter on it, overlay divs beside it), so the Original
   needs its own element to stay unfiltered -- same-origin and cached, a cache hit. */

const TIP_ON = "Applied — click to remove";
const TIP_OFF = "Free — click to apply";

function Tile({ id, name, on, hovered, onEnter, onLeave, onPick }) {
  const AF = MgArtFilters;
  const swRef = useRef(null);
  // the tile IS that filter's own gradients (AF.renderSwatch), painted once per mount
  useEffect(() => { if (AF && swRef.current) AF.renderSwatch(swRef.current, id); }, [AF, id]);
  return (
    <div className={"mgfc-tile" + (on ? " on" : "")} role="button" tabIndex={0}
      onClick={onPick} onMouseEnter={onEnter} onMouseLeave={onLeave}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(); } }}
      aria-pressed={on} aria-label={name}>
      <div className="mgfc-sw" ref={swRef} />
      <div className="mgfc-name">{name}</div>
      {hovered ? <div className="mgfc-tip">{on ? TIP_ON : TIP_OFF}</div> : null}
    </div>
  );
}

export default function FilterCompare({ open, onClose, source, onSendToEdit }) {
  const AF = MgArtFilters;
  const [active, setActive] = useState(null);
  const [strength, setStrength] = useState(1);   // DC 1922 filterStrength: 1
  const [angle, setAngle] = useState(180);       // DC 1922 filterAngle: 180
  const [hover, setHover] = useState(null);
  const [msg, setMsg] = useState("");            // outcome / warning line (real-data)
  const [busy, setBusy] = useState(false);
  const stageRef = useRef(null);
  const imgRef = useRef(null);

  const opts = useCallback(() => ({ strength: Number(strength), angle: Number(angle) }), [strength, angle]);
  const rec = active && AF ? (AF.get(active) || {}) : {};
  const activeName = active ? (rec.name || active).replace("Filter ", "") : "";

  // A new source starts clean (a filter judged on one picture says nothing about the next).
  useEffect(() => { setActive(null); setMsg(""); }, [source]);

  // (re)apply the live preview -- pure CSS overlays, no pixels copied
  useEffect(() => {
    if (!open || !AF || !stageRef.current) return;
    const host = stageRef.current;
    AF.clearPreview(host);
    if (!active || !source) { setMsg(""); return; }
    const n = AF.applyPreview(host, active, opts());
    // normalizeLayers reports any layer it had to drop (an unmapped blend mode, a stop
    // colour that isn't a plain literal) -- the preview still renders, just without that
    // layer, so saying so is the difference between "this looks off" and a silent wrong result.
    setMsg(n.warnings && n.warnings.length ? n.warnings[0] : "");
  }, [AF, active, source, opts, open]);

  const bake = async () => {
    if (!AF || !imgRef.current || !active) return null;
    return AF.toBlob(imgRef.current, active, opts());
  };

  const save = async () => {
    if (!active || !source) return;
    setBusy(true);
    try {
      const blob = await bake();
      if (!blob) return;
      const fd = new FormData();
      // Strength/angle are part of the OUTPUT, not just the filter id -- without them in
      // the name, re-saving the same filter at a different slider position collides with
      // the first file's name and run_import_local's path-based dedup silently treats a
      // genuinely different image as the same one (owner 2026-07-29: "wont save its new
      // image... writing the same filename" -- confirmed against run_import_local, which
      // keys purely on filename, not content).
      const tag = active + "_s" + Number(strength).toFixed(2).replace(".", "") + "_a" + angle;
      fd.append("files", blob, source + "_" + tag + ".png");
      const d = await apiUpload("/api/import-local", fd);
      if (d.error) {
        const friendly = d.http_status === 403
          ? "This only works when you're at the machine running the server — not over LAN/tablet."
          : d.error;
        setMsg(friendly);
        if (window.Toast) window.Toast.show({ kind: "err", title: "Not saved", msg: friendly });
        return;
      }
      const text = d.imported ? "Saved to your library." : "Already in your library (a duplicate).";
      setMsg(text);
      if (window.Toast) window.Toast.show({ kind: d.imported ? "ok" : "", title: text });
      if (d.imported) window.dispatchEvent(new CustomEvent("mg-gen-done"));
    } catch (e) {
      const m = "Couldn't save: " + (e && e.message ? e.message : "unknown error");
      setMsg(m);
      if (window.Toast) window.Toast.show({ kind: "err", title: "Not saved", msg: m });
    } finally { setBusy(false); }
  };

  const sendToEdit = async () => {
    if (!active || !source) return;
    setBusy(true);
    try {
      const blob = await bake();
      if (!blob) return;
      const fd = new FormData();
      fd.append("file", blob, "filtered_" + active + ".png");
      const d = await apiUpload("/api/upload", fd);
      if (d.error || !d.media_id) { setMsg(d.error || "Upload failed."); return; }
      const name = rec.name || active;
      onClose();
      onSendToEdit(d.media_id);
      if (window.Toast) {
        window.Toast.show({ kind: "ok", title: "Filtered image is your edit source", msg: name + " · uploaded free, nothing generated yet" });
      }
    } catch (e) {
      setMsg("Couldn't send: " + (e && e.message ? e.message : "unknown error"));
    } finally { setBusy(false); }
  };

  if (!open) return null;

  const src = source ? "/full/" + encodeURIComponent(source) : null;
  const groups = AF ? AF.groups() : [];
  const canAct = !!active && !!source && !busy;
  // DC 2978 fcSpendNote: (filter || 'No filter') + ' · nothing sent, nothing spent'; the
  // real outcome/warning line (msg) takes the slot while it has something to say.
  const spendNote = msg || ((active ? activeName : "No filter") + " · nothing sent, nothing spent");

  return (
    <>
      <div className="mgfc-scrim" onClick={onClose} />
      <div className="mgfc-layer">
        <div className="mgfc-panel" role="dialog" aria-label="Art filters">
          <div className="mgfc-head">
            <div className="mgfc-title">◐ Art filters</div>
            <span className="sp" />
            <button type="button" className="mgfc-x" onClick={onClose} aria-label="Close">✕</button>
          </div>
          {!AF ? (
            <div className="mgfc-empty">The art-filter library did not load on this page.</div>
          ) : (
            <div className="mgfc-grid">
              <div>
                <div className="mgfc-box">
                  {src ? <img alt="the unfiltered original" src={src} />
                    : <span className="mgfc-ph">source image</span>}
                </div>
                <div className="mgfc-cap">Original</div>
              </div>
              <div>
                <div className="mgfc-box">
                  {/* the stage is the engine's preview host: overlay divs at inset 0 over the
                      <img>, so it fills the box exactly (cover, no letterbox bars) */}
                  <div className="mgfc-stage" ref={stageRef}>
                    {src ? <img ref={imgRef} alt="filtered preview" src={src} /> : null}
                  </div>
                  {!src ? <span className="mgfc-ph">source image</span> : null}
                </div>
                <div className="mgfc-cap">Preview · {active ? activeName : "no filter"}</div>
              </div>
              <div className="mgfc-rail">
                {groups.map((g) => (
                  <div key={g.source}>
                    <div className="mgfc-grp">{g.label}</div>
                    <div className="mgfc-tiles">
                      {g.ids.map((id) => {
                        const r = AF.get(id) || {};
                        return (
                          <Tile key={id} id={id} name={(r.name || id).replace("Filter ", "")}
                            on={active === id} hovered={hover === id}
                            onEnter={() => setHover(id)} onLeave={() => setHover(null)}
                            onPick={() => setActive((cur) => (cur === id ? null : id))} />
                        );
                      })}
                    </div>
                  </div>
                ))}
                <div>
                  <div className="mgfc-sliderlbl">STRENGTH <b>{Number(strength).toFixed(2)}</b></div>
                  <input className="mgfc-range" type="range" min="0" max="1" step="0.05" value={strength}
                    onChange={(e) => setStrength(parseFloat(e.target.value))} />
                </div>
                <div>
                  <div className="mgfc-sliderlbl">ANGLE <b>{angle}°</b></div>
                  <input className="mgfc-range" type="range" min="0" max="360" step="1" value={angle}
                    onChange={(e) => setAngle(parseInt(e.target.value, 10))} />
                </div>
                <div className="mgfc-btnrow">
                  <button type="button" className="mgfc-btn" onClick={() => setActive(null)}>No filter</button>
                  <button type="button" className="mgfc-btn primary" disabled={!canAct} onClick={save}
                    title={canAct ? "Bake the filter at full resolution and save it to your library"
                      : source ? "Pick a filter first" : "Pick a source image first"}>
                    Save to library
                  </button>
                </div>
                <div className="mgfc-btnrow">
                  <button type="button" className="mgfc-btn" disabled={!canAct} onClick={sendToEdit}
                    title={canAct ? "Upload the filtered image to PixAI (free) and load it as the Edit source"
                      : source ? "Pick a filter first" : "Pick a source image first"}>
                    Send to image gen
                  </button>
                  <button type="button" className="mgfc-btn primary" disabled
                    title="Publishing to PixAI is not built yet">Publish</button>
                </div>
                <div className="mgfc-spend">{spendNote}</div>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
