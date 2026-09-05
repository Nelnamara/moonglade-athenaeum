import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MgArtFilters from "../art/artFilters.js";
import { apiUpload } from "../api.js";
import CustomSlider from "./CustomSlider.jsx";

/* THE DARKROOM -- the full-screen art-filters room (issue #48), built to
   `moonglade-internal/design/enhance/Enhance Family Handoff.dc.html` comp A1 (pick 1a,
   committed 2026-09-04). It REPLACES the centred compare panel this file's ancestor
   (FilterCompare.jsx, the DC 591-658 overlay) drew, and the drawer's inline
   "◐ Open compare view — M1–M7" strip that opened it.

   WHAT THE HANDOFF CHANGED, surface only -- the filter engine underneath is untouched:
     full screen   the old panel was min(1100px, 100vw-40) centred in a scrim; the
                   Darkroom takes the viewport (inset 0), so the picture gets the room.
     rail LEFT     180px, MgArtFilters.groups() order (ours first, then PixAI's), one
                   ROW per filter -- 32px swatch + name + tag -- instead of the old
                   3-across swatch grid on the right.
     two panes     source | filtered, 4:3, side by side in the stage (comp A1 lines
                   70-80). Same shared source as before: slab 1's editS.source.
     actions       Save to library (the METAL cta, shell.css .mgx-metal) · Send to Edit ·
                   Reset to source. **Publish is GONE** -- it was drawn disabled "until
                   Epic C" and read as a dead control; it returns only with community
                   publish, elsewhere. "Send to image gen" is renamed "Send to Edit":
                   SAME destination it always had (uploads the composite, loads it as the
                   Edit source) -- only the words were dishonest.
     persistence   selection + strength + angle survive for the SESSION (sessionStorage),
                   including a source change. This deliberately reverses the old
                   per-source reset ("a filter judged on one picture says nothing about
                   the next") -- the handoff's call: you came here to work a look.

   The tag under each rail name is real: ours carry the handoff's own descriptors, and
   PixAI's read exact/approx off BLEND_MODE_MAP -- M1/M2/M5/M6 use Photoshop's whole-colour
   darker-color/lighter-color, which CSS can only approximate (artFilters.js header). */

const SESSION_KEY = "mg-darkroom";

// Our five, as the handoff labels them (comp A1's renderVals F table). PixAI's tag is
// DERIVED below, so a recipe refresh can never leave a stale "exact" on screen.
const MG_TAGS = {
  "mg-moonglade": "ours · soft-light",
  "mg-nightfallen": "ours · color-burn",
  "mg-moonlit": "ours · gentlest",
  "mg-ember": "ours · contrast up",
  "mg-verdant": "ours · strongest",
};

/** "PixAI · exact" only when every layer's blend mode has a real CSS/canvas equivalent. */
function pixaiTag(AF, rec) {
  const map = AF.BLEND_MODE_MAP || {};
  const layers = (rec && rec.filters) || [];
  const exact = layers.every((l) => {
    const m = map[l.blendMode];
    return m && m.exact !== false;
  });
  return "PixAI · " + (exact ? "exact" : "approx");
}

function readSession() {
  try {
    const raw = window.sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const v = JSON.parse(raw);
    return v && typeof v === "object" ? v : null;
  } catch { return null; }
}

/* One rail row: its own swatch, painted once per mount by the engine (renderSwatch draws
   that filter's REAL gradients, not a two-stop stand-in). */
function RailRow({ id, name, tag, on, onPick }) {
  const AF = MgArtFilters;
  const swRef = useRef(null);
  useEffect(() => { if (AF && swRef.current) AF.renderSwatch(swRef.current, id); }, [AF, id]);
  return (
    <div className={"mgdk-row" + (on ? " on" : "")} role="button" tabIndex={0}
      onClick={onPick} aria-pressed={on} aria-label={name}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onPick(); } }}>
      <div className="mgdk-sw" ref={swRef} />
      <div className="mgdk-rowtt">
        <div className="mgdk-rowname">{name}</div>
        <div className="mgdk-rowtag">{tag}</div>
      </div>
    </div>
  );
}

export default function Darkroom({ open, onClose, source, onSendToEdit }) {
  const AF = MgArtFilters;
  const saved = useMemo(() => readSession() || {}, []);
  // A restored id is VALIDATED against the live recipes: refresh FILTERS from the endpoint
  // and a filter can disappear, and applyPreview/toBlob THROW on an id they cannot resolve.
  // A forgotten pick is a shrug; a room that will not open is not.
  const [active, setActive] = useState(
    saved.filter && AF && AF.get(saved.filter) ? saved.filter : null);
  const [strength, setStrength] = useState(
    typeof saved.strength === "number" ? saved.strength : 1);
  const [angle, setAngle] = useState(
    typeof saved.angle === "number" ? saved.angle : (AF ? AF.DEFAULT_ANGLE_DEG : 180));
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const stageRef = useRef(null);
  const imgRef = useRef(null);

  const opts = useCallback(() => ({ strength: Number(strength), angle: Number(angle) }),
    [strength, angle]);
  const rec = active && AF ? (AF.get(active) || {}) : {};
  const activeName = active ? (rec.name || active) : "no filter";

  // Session persistence (the handoff: "selection + strength persist for the session").
  useEffect(() => {
    try {
      window.sessionStorage.setItem(SESSION_KEY,
        JSON.stringify({ filter: active, strength, angle }));
    } catch { /* private mode / quota -- the room still works, it just forgets */ }
  }, [active, strength, angle]);

  // A new source clears the OUTCOME line (it described the old picture), never the pick.
  useEffect(() => { setMsg(""); }, [source]);

  // Esc closes.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => { if (e.key === "Escape") onClose && onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

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

  // "Send to Edit" -- the words this action always deserved. Unchanged behaviour: bake,
  // upload the composite (free S3 handshake), hand the media_id to the drawer, which loads
  // it as the EDIT SOURCE.
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
  const pct = Math.round(Number(strength) * 100);

  return (
    <div className="mgdk" role="dialog" aria-label="The Darkroom">
      <div className="mgdk-head">
        <span className="mgdk-name">The Darkroom</span>
        <span className="mgdk-free">free · offline · no credits</span>
        <span className="sp" />
        <button type="button" className="mgdk-x" onClick={onClose} aria-label="Close">✕ Esc</button>
      </div>

      {!AF ? (
        <div className="mgdk-empty">The art-filter library did not load on this page.</div>
      ) : (
        <div className="mgdk-body">
          <div className="mgdk-rail">
            {groups.map((g) => (
              <React.Fragment key={g.source}>
                <div className="mgdk-grp">{g.label} · {g.source === "moonglade" ? g.ids.length : "M1–M" + g.ids.length}</div>
                <div className="mgdk-rows">
                  {g.ids.map((id) => {
                    const r = AF.get(id) || {};
                    return (
                      <RailRow key={id} id={id} name={r.name || id}
                        tag={MG_TAGS[id] || pixaiTag(AF, r)}
                        on={active === id}
                        onPick={() => setActive((cur) => (cur === id ? null : id))} />
                    );
                  })}
                </div>
              </React.Fragment>
            ))}
          </div>

          <div className="mgdk-stage">
            <div className="mgdk-panes">
              <div className="mgdk-pane">
                {src ? <img alt="the unfiltered original" src={src} />
                  : <span className="mgdk-ph">pick a source image above</span>}
                <span className="mgdk-badge">source</span>
              </div>
              <div className="mgdk-pane on">
                {/* the stage IS the engine's preview host: overlay divs at inset 0 over
                    the <img>, so it fills the pane exactly (cover, no letterbox bars) */}
                <div className="mgdk-host" ref={stageRef}>
                  {src ? <img ref={imgRef} alt="filtered preview" src={src} /> : null}
                </div>
                {!src ? <span className="mgdk-ph">pick a source image above</span> : null}
                <span className="mgdk-badge on">{activeName}</span>
              </div>
            </div>

            {/* Both tracks are the app's own CustomSlider (drift §48) rather than a
                bespoke one -- same drag math, keyboard arrows, and the shared
                mauve→lavender fill the SIZE pill already wears. */}
            <div className="mgdk-ctl">
              <span className="mgdk-ctllbl">Strength</span>
              <div className="mgdk-track">
                <CustomSlider compact value={strength} min={0} max={1} step={0.05}
                  ariaLabel="Filter strength" onChange={setStrength} />
              </div>
              <span className="mgdk-ctlval">{pct}%</span>
              {/* The comp draws the angle as a label + readout; it is a real control
                  (handoff: "strength + angle (180° default)"), so the readout keeps its
                  place and a short track sits beside it. 180° = CSS top-to-bottom, the
                  engine's DEFAULT_ANGLE_DEG -- preview and baked PNG share it. */}
              <span className="mgdk-ctllbl gap">Angle</span>
              <div className="mgdk-track short">
                <CustomSlider compact value={angle} min={0} max={360} step={1}
                  ariaLabel="Gradient angle" onChange={(v) => setAngle(Math.round(v))} />
              </div>
              <span className="mgdk-ctlval wide">{angle}°</span>
            </div>

            <div className="mgdk-acts">
              <button type="button" className="mgx-metal mgx-metal-md mgdk-save"
                disabled={!canAct} onClick={save}
                title={canAct ? "Bake the filter at full resolution and save it to your library"
                  : source ? "Pick a filter first" : "Pick a source image first"}>
                Save to library
              </button>
              <button type="button" className="mgdk-send" disabled={!canAct} onClick={sendToEdit}
                title={canAct ? "Upload the filtered image to PixAI (free) and load it as the Edit source"
                  : source ? "Pick a filter first" : "Pick a source image first"}>
                Send to Edit →
              </button>
              <button type="button" className="mgdk-reset" onClick={() => setActive(null)}
                title="Clear the filter — the strength and angle stay where you set them">
                Reset to source
              </button>
              <span className="sp" />
              {/* At rest the comp's italic note; the real outcome/warning takes the slot
                  while it has something to say (the old panel's spend-note did the same). */}
              <span className={"mgdk-note" + (msg ? " say" : "")}>
                {msg || "bakes at full resolution"}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
