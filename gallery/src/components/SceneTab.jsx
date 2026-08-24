import React, { useEffect, useRef, useState } from "react";
import { submitTask, useResultLines } from "../gen/submitTask.js";
import { ResultLines } from "./EditTab.jsx";
import { askPicker } from "./PickerHost.jsx";
import { apiGet } from "../api.js";

/* The Bridge §5 scene generator -- where a scene picked in the "✦ AI Tools" nav modal lands
   (DECISIONS: the AI-Tools tier splits by function -- browse in the nav modal, generate in the
   gen drawer). Data-driven: it fetches the picked scene's control schema from /api/scenes and
   renders exactly the controls that scene needs --
     * 1-click (plushie, lego, giant-statue)  -> just Generate
     * preset chips (tarot, fantasy class)     -> a selectable chip row
     * language + text (character-card, vtuber)-> language chips + a name/caption field
     * dual (dual-character-generator)         -> a 2nd source slot + pose chips + aspect toggle
   The PRIMARY source is slab 1's shared SourceSlab (same as EnhanceTab -- "Shares slab 1's
   source"); dual adds its own 2nd slot here via the same askPicker() the rest of the drawer
   uses. Generate -> POST /api/scene (mirror-gated, JWT) -> the runs/History reel shows the
   result, identical to every other gen. Scenes carry no pre-price (PixAI exposes no scene
   task-price op), so the confirm names the spend and the reel reports the real cost after. */

export default function SceneTab({ scene, source, armed }) {
  const [cfg, setCfg] = useState(null);       // null = loading; the matched control schema else
  const [failed, setFailed] = useState(false);
  const [preset, setPreset] = useState("random");
  const [sel, setSel] = useState({});         // selectorId -> chosen option key
  const [custom, setCustom] = useState("");
  const [ref2, setRef2] = useState(null);     // {media_id, thumb} -- 2nd source for dual scenes
  const [lines, openLine] = useResultLines();
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  const slug = scene && scene.slug;
  useEffect(() => {
    if (!armed || !slug) { setCfg(null); return undefined; }
    let live = true;
    setCfg(null); setFailed(false); setRef2(null); setCustom("");
    apiGet("/api/scenes").then((d) => {
      if (!live) return;
      const m = ((d && d.scenes) || []).find((s) => s.sceneId === slug) || null;
      if (!m) { setFailed(true); return; }
      setCfg(m);
      const keys = (m.presets || []).map((p) => p.key);
      const onlyCustom = keys.length === 1 && keys[0] === "custom";
      setPreset(onlyCustom ? "custom" : (keys.find((k) => k !== "custom") || "random"));
      const sv = {};
      (m.selectors || []).forEach((x) => { const o = x.options || []; sv[x.id] = x.default || (o[0] && o[0].key); });
      setSel(sv);
    });
    return () => { live = false; };
  }, [armed, slug]);

  if (!scene) return null;

  const loading = cfg === null && !failed;
  const needsTwo = (cfg ? cfg.refMin : 1) >= 2;
  const hasCustom = !!(cfg && cfg.custom);
  const presets = (cfg && cfg.presets) || [];
  const selectors = (cfg && cfg.selectors) || [];
  const thumb = "/branding/bridge/scene_" + slug + ".webp";
  const missing = !source || (needsTwo && !ref2);
  const genOff = loading || busy || missing || failed;

  const pick2 = async () => {
    const m = await askPicker({ type: "image" });
    if (m) setRef2({ media_id: m.media_id, thumb: m.thumb });
  };

  const run = async () => {
    if (busyRef.current || genOff) return;
    if (!window.confirm((scene.name || "This scene") + " on your source — this spends credits and "
      + "runs on the PixAI mirror. Go?")) return;
    busyRef.current = true; setBusy(true);
    const emit = openLine("Submitting " + (scene.name || "scene") + "…");
    const media = needsTwo ? [source, ref2 && ref2.media_id].filter(Boolean) : [source];
    const body = {
      scene_id: slug, media_ids: media, preset,
      custom: hasCustom ? custom : undefined,
      selector_values: selectors.map((x) => ({ id: x.id, value: sel[x.id] })),
    };
    await submitTask("/api/scene", body, { label: scene.name || slug, emit });
    busyRef.current = false; setBusy(false);
  };

  return (
    <div className="mgdock-slab mgdock-scslab">
      <div className="mgdock-schead">
        <img className="mgdock-scthumb" src={thumb} alt="" loading="lazy"
          onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
        <div className="mgdock-sctt">
          <div className="mgdock-scname">{scene.name}
            {scene.tier ? <span className="mgdock-sctier">{typeof scene.tier === "boolean" ? "Tier" : "Tier " + scene.tier}</span> : null}</div>
          <div className="mgdock-scsub">&#10022; AI Tools <span className="dot">·</span>
            <span className="mir">● runs on the mirror</span></div>
        </div>
      </div>

      {failed ? (
        <div className="mgdock-scnote">Couldn&rsquo;t load this tool &mdash; arm the mirror and try again.</div>
      ) : (
        <>
          {needsTwo && (
            <>
              <div className="mgdock-sclbl">Second character</div>
              <button type="button" className={"mgdock-scslot" + (ref2 ? " on" : "")} onClick={pick2}>
                {ref2 ? <img src={ref2.thumb} alt="" />
                  : <span className="mgdock-scplus">&#65291; pick a 2nd image</span>}
              </button>
            </>
          )}

          {presets.length > 0 && (
            <>
              <div className="mgdock-sclbl">{needsTwo ? "Pose" : (hasCustom ? "Style" : "Preset")}</div>
              <div className="mgdock-scchips">
                {presets.map((p) => (
                  <button key={p.key} type="button"
                    className={"mgdock-scchip" + (preset === p.key ? " on" : "")}
                    onClick={() => setPreset(p.key)}>{p.label}</button>
                ))}
              </div>
            </>
          )}

          {selectors.map((x) => (
            <div key={x.id}>
              <div className="mgdock-sclbl">{x.label}</div>
              <div className="mgdock-scseg">
                {(x.options || []).map((o) => (
                  <button key={o.key} type="button"
                    className={"mgdock-scsegb" + (sel[x.id] === o.key ? " on" : "")}
                    onClick={() => setSel((s) => ({ ...s, [x.id]: o.key }))}>{o.label}</button>
                ))}
              </div>
            </div>
          ))}

          {hasCustom && (
            <>
              <div className="mgdock-sclbl">Text</div>
              <input className="mgdock-sctxt" value={custom} onChange={(e) => setCustom(e.target.value)}
                placeholder="A name or short description…" aria-label="Scene text" />
            </>
          )}

          <button type="button" className={"mgdock-enhgen mgdock-scgen" + (genOff ? " off" : "")}
            disabled={genOff}
            title={missing ? (needsTwo ? "Pick two source images" : "Add a source image above")
              : loading ? "Loading…" : "Generate — runs on the mirror"}
            onClick={run}>
            <span>&#10022; Generate {scene.name}</span>
          </button>
          {missing && !loading ? (
            <div className="mgdock-scnote">{needsTwo
              ? "Add a source above and pick a 2nd character to generate."
              : "Add a source image in SOURCE above to generate."}</div>
          ) : null}
          <ResultLines lines={lines} />
        </>
      )}
    </div>
  );
}
