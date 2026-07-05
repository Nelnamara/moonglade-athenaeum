import React, { useState, useEffect, useRef, useCallback } from "react";

/* =========================================================================
   THE EDIT BAY v2 — reusable Seedance 2.0 storyboard with continuity chaining
   Frame handoff (close-of-N -> open-of-N+1), connection methods, a reusable
   Cast & Assets reference library, and continuity-aware prompt assembly.
   Persists to window.storage. Self-contained.
   ========================================================================= */

const STYLES = `
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;700&display=swap');
:root{
  --bg:#15131C;--bg2:#1C1925;--panel:#221E2D;--panel2:#2A2535;
  --line:#363046;--line2:#46405A;--ink:#ECE7F2;--ink2:#A79EBA;--ink3:#6F6783;
  --amber:#E0A24E;--amber-d:#B47E33;--cyan:#6FB8B2;--green:#73C281;--coral:#E07A52;
  --shadow:0 10px 30px rgba(0,0,0,.45);
}
*{box-sizing:border-box}
.sb-root{font-family:'Inter',system-ui,sans-serif;background:
  radial-gradient(1200px 600px at 80% -10%,rgba(224,162,78,.07),transparent 60%),var(--bg);
  color:var(--ink);min-height:100vh;padding:0 0 80px;-webkit-font-smoothing:antialiased}
.sb-mono{font-family:'JetBrains Mono',monospace}.sb-disp{font-family:'Bricolage Grotesque','Inter',sans-serif}

.sb-top{position:sticky;top:0;z-index:30;background:rgba(21,19,28,.86);backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line);padding:14px 20px}
.sb-topgrid{display:flex;gap:18px;align-items:center;flex-wrap:wrap;max-width:1320px;margin:0 auto}
.sb-brand{display:flex;align-items:baseline;gap:10px;flex:1 1 auto;min-width:0}
.sb-brand h1{font-size:19px;font-weight:800;letter-spacing:-.02em;margin:0;white-space:nowrap}
.sb-clap{color:var(--amber)}
.sb-projname{background:transparent;border:none;border-bottom:1px dashed transparent;color:var(--ink2);
  font:inherit;font-size:14px;padding:2px 4px;min-width:60px;max-width:300px;flex:1 1 auto}
.sb-projname:hover{border-bottom-color:var(--line2)}
.sb-projname:focus{outline:none;border-bottom-color:var(--amber);color:var(--ink)}
.sb-stat{display:flex;flex-direction:column;align-items:flex-end;line-height:1.1}
.sb-stat b{font-family:'JetBrains Mono',monospace;font-size:15px}
.sb-stat span{font-size:10px;color:var(--ink3);letter-spacing:.08em;text-transform:uppercase}
.sb-saved{font-size:11px;color:var(--ink3);display:flex;align-items:center;gap:5px}
.sb-dot{width:7px;height:7px;border-radius:50%;background:var(--green);transition:opacity .3s}
.sb-dot.busy{background:var(--amber)}

.sb-reel-wrap{max-width:1320px;margin:12px auto 0;padding:0 2px}
.sb-reel{position:relative;height:30px;background:var(--bg2);border:1px solid var(--line);border-radius:7px;display:flex;overflow:hidden}
.sb-seg{position:relative;min-width:3px;border-right:1px solid rgba(0,0,0,.35);transition:filter .15s}
.sb-seg:hover{filter:brightness(1.35)}
.sb-seg.todo{background:#3a3450}.sb-seg.wip{background:linear-gradient(var(--amber),var(--amber-d))}
.sb-seg.done{background:linear-gradient(var(--green),#4f9a5c)}
.sb-target{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--coral);z-index:4}
.sb-target::after{content:'8:00';position:absolute;top:-15px;left:50%;transform:translateX(-50%);
  font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--coral);white-space:nowrap}
.sb-reel-legend{display:flex;gap:16px;margin-top:18px;font-size:11px;color:var(--ink3);flex-wrap:wrap}
.sb-reel-legend i{width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:5px;vertical-align:middle}

.sb-main{max-width:1320px;margin:22px auto 0;padding:0 20px}
.sb-wrap{max-width:1320px;margin:0 auto;padding:14px 20px}
.sb-toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.sb-divider{flex:1 1 auto}

.sb-act{margin-bottom:30px}
.sb-acthead{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--line);margin-bottom:18px}
.sb-actname{background:transparent;border:none;color:var(--ink);font-family:'Bricolage Grotesque',sans-serif;
  font-weight:700;font-size:20px;letter-spacing:-.01em;flex:1 1 auto;min-width:0;padding:2px 0}
.sb-actname:focus{outline:none}
.sb-actcode{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--amber);
  background:rgba(224,162,78,.1);border:1px solid rgba(224,162,78,.25);border-radius:5px;padding:3px 8px}
.sb-actmeta{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--ink3)}

.sb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:16px}
.sb-card{background:var(--panel);border:1px solid var(--line);border-radius:11px;overflow:hidden;
  display:flex;flex-direction:column;transition:border-color .15s,box-shadow .15s}
.sb-card:hover{border-color:var(--line2)}
.sb-card.open{box-shadow:var(--shadow);border-color:var(--amber-d);grid-column:1/-1}

.sb-shotprev{position:relative;margin-top:8px;border-radius:8px;overflow:hidden;
  background:#000;cursor:col-resize;max-width:340px}
.sb-shotprev video{width:100%;display:block;aspect-ratio:16/9;object-fit:contain;background:#000}
.sb-shotprev-hint{position:absolute;right:7px;bottom:6px;font-size:10.5px;color:rgba(255,255,255,.75);
  background:rgba(0,0,0,.5);border-radius:5px;padding:2px 7px;pointer-events:none;
  opacity:0;transition:opacity .15s}
.sb-shotprev:hover .sb-shotprev-hint{opacity:1}
.sb-shotprev-wrap{margin-top:8px;max-width:340px}
.sb-trim{margin-top:6px}
.sb-trim-track{position:relative;height:20px;background:var(--panel2);border:1px solid var(--line);border-radius:6px;cursor:pointer;touch-action:none}
.sb-trim-sel{position:absolute;top:0;bottom:0;background:rgba(224,162,78,.26);border-left:2px solid var(--amber);border-right:2px solid var(--amber)}
.sb-trim-h{position:absolute;top:-3px;width:11px;height:26px;margin-left:-6px;border-radius:4px;background:var(--amber);cursor:ew-resize;box-shadow:0 1px 4px rgba(0,0,0,.55);touch-action:none;z-index:2}
.sb-trim-h:hover{background:#f0b866}
.sb-trim-read{font-size:11px;color:var(--ink2);margin-top:6px;font-family:'JetBrains Mono',monospace}
.sb-trim-read b{color:var(--amber)}
.sb-trim-reset{margin-left:9px;background:none;border:1px solid var(--line);color:var(--ink2);border-radius:5px;font-size:10px;padding:1px 8px;cursor:pointer}
.sb-trim-reset:hover{border-color:var(--amber);color:var(--amber)}
.sb-seq{position:fixed;inset:0;z-index:500;background:rgba(4,3,10,.92);display:flex;align-items:center;justify-content:center;padding:22px}
.sb-seq-box{max-width:1120px;width:100%;display:flex;flex-direction:column;gap:11px}
.sb-seq video{width:100%;max-height:78vh;background:#000;border-radius:11px;display:block;cursor:pointer}
.sb-seq-bar{display:flex;align-items:center;gap:9px;color:var(--ink);font-size:13px}
.sb-seq-bar span{flex:1;font-family:'JetBrains Mono',monospace;color:var(--ink2)}

.sb-fromstrip{display:flex;align-items:center;gap:8px;padding:7px 12px;background:var(--bg2);
  border-bottom:1px solid var(--line);font-size:11px;color:var(--ink3)}
.sb-fromstrip .sb-linkdot{font-size:12px}
.sb-link-ok{color:var(--green)}.sb-link-warn{color:var(--coral)}
.sb-connbadge{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--cyan);
  border:1px solid rgba(111,184,178,.4);border-radius:4px;padding:1px 6px;margin-left:auto}

.sb-slate{display:flex;align-items:center;gap:10px;padding:11px 13px;
  background:repeating-linear-gradient(45deg,#211d2c,#211d2c 9px,#1b1825 9px,#1b1825 18px);
  border-bottom:1px solid var(--line)}
.sb-code{font-family:'JetBrains Mono',monospace;font-weight:700;font-size:13px;color:var(--amber);
  background:#15131c;border:1px solid var(--line2);border-radius:5px;padding:3px 7px;white-space:nowrap}
.sb-ctitle{flex:1 1 auto;min-width:0;background:transparent;border:none;color:var(--ink);font:inherit;
  font-weight:600;font-size:14px;padding:2px 0;text-overflow:ellipsis}
.sb-ctitle:focus{outline:none}
.sb-mode{font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--cyan);
  border:1px solid rgba(111,184,178,.4);border-radius:4px;padding:2px 5px}
.sb-tc{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--ink2)}
.sb-tick{width:22px;height:22px;border-radius:6px;border:1.5px solid var(--line2);background:transparent;
  cursor:pointer;flex:none;display:grid;place-items:center;color:transparent;transition:all .12s;padding:0}
.sb-tick.wip{border-color:var(--amber);color:var(--amber)}
.sb-tick.done{border-color:var(--green);background:var(--green);color:#15131c}

.sb-body{padding:12px 13px;display:flex;flex-direction:column;gap:11px}
.sb-frames-mini{display:flex;align-items:stretch;gap:8px}
.sb-fm{flex:1 1 0;min-width:0}
.sb-fm .sb-fmlab{font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink3);margin-bottom:3px;display:flex;justify-content:space-between}
.sb-fmbox{height:62px;border-radius:6px;border:1px solid var(--line2);background:var(--bg2);overflow:hidden;
  display:grid;place-items:center;color:var(--ink3);font-size:10px;text-align:center;padding:4px;position:relative}
.sb-fmbox img{width:100%;height:100%;object-fit:cover}
.sb-fmbox.discreet img{filter:blur(8px)}
.sb-arrowmid{display:grid;place-items:center;color:var(--amber);font-size:16px;flex:0 0 auto;padding-top:14px}
.sb-prompt-mini{font-size:12.5px;color:var(--ink2);line-height:1.5;display:-webkit-box;-webkit-line-clamp:3;
  -webkit-box-orient:vertical;overflow:hidden;white-space:pre-wrap;cursor:text}
.sb-prompt-mini.empty{color:var(--ink3);font-style:italic}
.sb-minimeta{display:flex;flex-wrap:wrap;gap:6px;font-size:11px}
.sb-chip{font-size:11px;color:var(--ink2);background:var(--bg2);border:1px solid var(--line);border-radius:20px;padding:3px 9px}
.sb-chip b{color:var(--ink3);font-weight:500}

.sb-edit{display:flex;flex-direction:column;gap:14px;padding:4px 13px 16px}
.sb-row{display:flex;gap:12px;flex-wrap:wrap}
.sb-field{display:flex;flex-direction:column;gap:5px;flex:1 1 200px;min-width:0}
.sb-lab{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink3);font-weight:600;display:flex;align-items:center;gap:6px}
.sb-in,.sb-ta,.sb-sel{background:var(--bg2);border:1px solid var(--line2);border-radius:7px;color:var(--ink);
  font:inherit;font-size:13px;padding:8px 10px;width:100%}
.sb-ta{resize:vertical;min-height:74px;line-height:1.55}.sb-ta.big{min-height:104px}
.sb-in:focus,.sb-ta:focus,.sb-sel:focus{outline:none;border-color:var(--amber)}
.sb-hint{font-size:10.5px;color:var(--ink3)}

.sb-section{border:1px solid var(--line);border-radius:10px;padding:12px;background:var(--bg2)}
.sb-section>h5{margin:0 0 10px;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--amber);font-weight:700}
.sb-twoframes{display:flex;gap:12px;align-items:flex-start}
.sb-twoframes .sb-frame{flex:1 1 0;min-width:0}
.sb-conn-mid{flex:0 0 auto;align-self:center;color:var(--amber);font-size:20px;padding-top:10px}

.sb-frame{display:flex;flex-direction:column;gap:6px}
.sb-framehead{display:flex;align-items:center;justify-content:space-between;gap:6px}
.sb-frameprev{height:84px;border-radius:7px;border:1px solid var(--line2);background:var(--panel2);overflow:hidden;
  display:grid;place-items:center;color:var(--ink3);font-size:11px;cursor:pointer;position:relative}
.sb-frameprev img{width:100%;height:100%;object-fit:cover}
.sb-frameprev.discreet img{filter:blur(9px)}
.sb-tagin{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--cyan);background:#15131c;
  border:1px solid var(--line2);border-radius:5px;padding:3px 6px;width:90px}

.sb-pal{display:flex;flex-wrap:wrap;gap:5px;margin-top:4px}
.sb-palgrp{width:100%;font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink3);margin-top:5px}
.sb-pchip{font-family:'JetBrains Mono',monospace;font-size:10.5px;color:var(--ink2);background:var(--bg2);
  border:1px solid var(--line);border-radius:5px;padding:3px 7px;cursor:pointer;transition:all .1s}
.sb-pchip:hover{border-color:var(--amber);color:var(--amber)}

.sb-casttoggle{display:flex;flex-wrap:wrap;gap:6px}
.sb-castchip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;border:1px solid var(--line2);
  background:var(--panel2);color:var(--ink2);border-radius:20px;padding:4px 10px;cursor:pointer}
.sb-castchip.on{border-color:var(--cyan);color:var(--cyan);background:rgba(111,184,178,.1)}
.sb-castchip .sb-ct{font-family:'JetBrains Mono',monospace;font-size:9px;opacity:.8}

.sb-ref{background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:10px;display:flex;gap:10px;align-items:flex-start}
.sb-refprev{width:64px;height:48px;border-radius:6px;border:1px solid var(--line2);background:var(--panel2);
  flex:none;display:grid;place-items:center;font-size:18px;cursor:pointer;overflow:hidden}
.sb-refprev img{width:100%;height:100%;object-fit:cover}.sb-refprev.discreet img{filter:blur(8px)}
.sb-refbody{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:6px}

.sb-btn{font:inherit;font-size:12.5px;font-weight:500;border-radius:7px;padding:7px 12px;cursor:pointer;
  border:1px solid var(--line2);background:var(--panel2);color:var(--ink);transition:all .12s;display:inline-flex;align-items:center;gap:6px}
.sb-btn:hover{border-color:var(--amber);color:var(--amber)}
.sb-btn.amber{background:var(--amber);color:#15131c;border-color:var(--amber);font-weight:600}
.sb-btn.amber:hover{filter:brightness(1.08);color:#15131c}
.sb-btn.ghost{background:transparent}.sb-btn.sm{font-size:11px;padding:5px 9px}
.sb-btn.danger:hover{border-color:var(--coral);color:var(--coral)}
.sb-ico{background:transparent;border:none;color:var(--ink3);cursor:pointer;padding:5px;border-radius:6px;font-size:14px;line-height:1;transition:all .12s}
.sb-ico:hover{color:var(--ink);background:var(--panel2)}
.sb-toggle{display:inline-flex;align-items:center;gap:7px;font-size:12px;color:var(--ink2);cursor:pointer}
.sb-add{width:100%;border:1.5px dashed var(--line2);background:transparent;color:var(--ink3);border-radius:11px;padding:14px;font:inherit;font-size:13px;cursor:pointer;transition:all .12s}
.sb-add:hover{border-color:var(--amber);color:var(--amber)}

.sb-panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-top:12px}
.sb-panelhead{display:flex;align-items:center;gap:10px;padding:12px 16px;cursor:pointer}
.sb-panelhead h3{margin:0;font-family:'Bricolage Grotesque',sans-serif;font-size:15px;font-weight:700}
.sb-panelbody{padding:0 16px 16px;display:flex;flex-direction:column;gap:10px}
.sb-assetrow{display:flex;gap:10px;align-items:center;background:var(--bg2);border:1px solid var(--line);border-radius:9px;padding:9px}
.sb-assetprev{width:54px;height:42px;border-radius:6px;border:1px solid var(--line2);background:var(--panel2);
  flex:none;display:grid;place-items:center;font-size:16px;cursor:pointer;overflow:hidden}
.sb-assetprev img{width:100%;height:100%;object-fit:cover}.sb-assetprev.discreet img{filter:blur(8px)}

.sb-helpbox{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;font-size:12.5px;color:var(--ink2);line-height:1.65;margin-top:12px}
.sb-helpbox h4{margin:0 0 8px;color:var(--ink);font-family:'Bricolage Grotesque',sans-serif;font-size:14px}
.sb-helpbox h4:not(:first-child){margin-top:14px}
.sb-helpbox code{font-family:'JetBrains Mono',monospace;color:var(--cyan);font-size:12px}
.sb-helpbox b{color:var(--amber)}
.sb-empty{text-align:center;color:var(--ink3);padding:30px;font-size:13px}

@media (max-width:560px){.sb-grid{grid-template-columns:1fr}.sb-main,.sb-top,.sb-wrap{padding-left:13px;padding-right:13px}
  .sb-twoframes{flex-direction:column}.sb-conn-mid{align-self:flex-start;padding:0}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
:focus-visible{outline:2px solid var(--amber);outline-offset:2px}
`;

const MODES = ["T2V", "I2V", "R2V", "V2V", "FLF"];
const MODE_HINT = {
  T2V: "Text only — describe the whole scene",
  I2V: "Image-to-video — ref is first frame; prompt only motion",
  R2V: "Reference-to-video — lock identity/style/motion via @tags",
  V2V: "Video edit / extend an existing clip",
  FLF: "First & last frame — interpolate between two images",
};
const CONNECT = {
  new:    { label: "New scene",     hint: "intentional break — fresh look/place" },
  cut:    { label: "Cut (in edit)", hint: "hard/match cut joined in your editor — rhyme the frames" },
  flf:    { label: "First→Last",    hint: "land on an exact end frame; prompt the motion between" },
  extend: { label: "Extend prev",   hint: "feed previous clip as @video1; continue seamlessly" },
};
const CAM_PALETTE = {
  "Shot size": ["EWS", "WS", "MLS", "MS", "MCU", "CU", "ECU", "OTS", "two-shot", "insert", "POV"],
  "Movement": ["static/locked", "pan left", "pan right", "tilt up", "tilt down", "dolly in", "dolly out",
    "push in", "pull out", "truck left", "truck right", "pedestal up", "crane up", "arc", "orbit",
    "tracking/follow", "handheld", "steadicam", "rack focus", "whip pan", "Dutch angle"],
  "Lens / feel": ["wide", "telephoto", "shallow depth of field", "deep focus", "slow motion", "macro"],
};
const TRANS_PALETTE = ["cut", "hard cut", "match cut", "smash cut", "dissolve", "crossfade",
  "fade in", "fade to black", "J-cut", "L-cut", "wipe", "whip-pan transition"];
const CONTINUITY_PHRASE = "Smooth, continuous, seamless — no hard cut.";

const uid = () => Math.random().toString(36).slice(2, 9);
const fmt = (s) => { s = Math.max(0, Math.round(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
const actLetter = (i) => (i < 26 ? String.fromCharCode(65 + i) : `A${i}`);
const emptyFrame = () => ({ thumbId: "", source: "", desc: "", tag: "" });

/* ---------- storage ---------- */
const hasStore = typeof window !== "undefined" && window.storage;
const PKEY = "storyboard:v2:project";
const TPRE = "storyboard:v2:thumb:";
async function sGet(k) { try { const r = await window.storage.get(k); return r ? r.value : null; } catch { return null; } }
async function sSet(k, v) { try { await window.storage.set(k, v, false); } catch (e) { console.error(e); } }
async function sList(p) { try { const r = await window.storage.list(p, false); if (!r) return []; return (r.keys || []).map((k) => (typeof k === "string" ? k : k.key)); } catch { return []; } }

function fileToThumb(file, maxDim = 480, q = 0.72) {
  return new Promise((res, rej) => {
    const img = new Image(), url = URL.createObjectURL(file);
    img.onload = () => {
      const sc = Math.min(1, maxDim / Math.max(img.width, img.height));
      const w = Math.round(img.width * sc), h = Math.round(img.height * sc);
      const cv = document.createElement("canvas"); cv.width = w; cv.height = h;
      cv.getContext("2d").drawImage(img, 0, 0, w, h);
      URL.revokeObjectURL(url);
      try { res(cv.toDataURL("image/jpeg", q)); } catch (e) { rej(e); }
    };
    img.onerror = () => { URL.revokeObjectURL(url); rej(new Error("img")); };
    img.src = url;
  });
}

function newCard(extra = {}) {
  return {
    id: uid(), title: "", status: "todo", mode: "I2V", duration: 8, connect: "cut",
    prompt: "", openFrame: emptyFrame(), closeFrame: emptyFrame(),
    cast: [], refs: [], camera: "", lighting: "", audioCue: "",
    transIn: "", transOut: "", notes: "", discreet: false, trimIn: 0, trimOut: null, ...extra,
  };
}
function seedProject() {
  return {
    name: "Untitled storyboard", target: 480,
    assets: [
      { id: uid(), name: "Her", kind: "image", tag: "@image1", thumbId: "", source: "", lock: true },
      { id: uid(), name: "Me", kind: "image", tag: "@image2", thumbId: "", source: "", lock: true },
      { id: uid(), name: "The room", kind: "image", tag: "@image3", thumbId: "", source: "", lock: false },
      { id: uid(), name: "The song", kind: "audio", tag: "@audio1", thumbId: "", source: "", lock: false },
    ],
    acts: [
      {
        id: uid(), name: "Act 1 — Setup", collapsed: false,
        cards: [newCard({
          title: "Establishing shot", mode: "I2V", duration: 8, connect: "new",
          prompt: "Quiet sunlit room at golden hour, dust drifting in the light. Slow reveal of the empty space. Warm, intimate, lived-in.",
          openFrame: { thumbId: "", source: "", desc: "Wide, empty room. Light from window, camera-left.", tag: "@image1" },
          closeFrame: { thumbId: "", source: "", desc: "Same room, camera has pushed in slightly toward the window seat.", tag: "" },
          camera: "WS, slow push in, shallow depth of field",
          lighting: "golden hour, warm low sun, soft haze", audioCue: "ambient room tone",
          transIn: "fade in", transOut: "dissolve",
          notes: "Example card — duplicate or delete. The closing frame here becomes the next shot's opening frame.",
        })],
      },
      { id: uid(), name: "Act 2 — Build", collapsed: false, cards: [] },
      { id: uid(), name: "Act 3 — Payoff", collapsed: false, cards: [] },
    ],
  };
}

/* ============================ APP ============================ */
export default function App() {
  const [project, setProject] = useState(null);
  const [thumbs, setThumbs] = useState({});
  const [open, setOpen] = useState({});
  const [busy, setBusy] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [showCast, setShowCast] = useState(true);
  const [genState, setGenState] = useState({});   // cardId -> {phase, msg, mid}
  const [seq, setSeq] = useState(null);           // Play-sequence: [clip,...] or null
  const [pickCb, setPickCb] = useState(null);     // gallery picker: cb(mid, thumb) or null
  const [batching, setBatching] = useState(false);
  const openPick = useCallback((cb) => setPickCb(() => cb), []);
  const saveTimer = useRef(null);
  const castImported = useRef(false);

  useEffect(() => {
    (async () => {
      let p = null;
      if (hasStore) { const raw = await sGet(PKEY); if (raw) { try { p = JSON.parse(raw); } catch {} } }
      setProject(p || seedProject());
      if (hasStore) {
        const keys = await sList(TPRE); const map = {};
        for (const k of keys) { const v = await sGet(k); if (v) map[k.slice(TPRE.length)] = v; }
        setThumbs(map);
      }
    })();
  }, []);

  // Gallery -> cast: /edit-bay?cast=id1,id2 (from the gallery's "Send to Loom cast" bulk
  // action) adds those images as reusable @image cast members, once, then clears the URL.
  useEffect(() => {
    if (!project || castImported.current) return;
    castImported.current = true;
    const ids = (new URLSearchParams(location.search).get("cast") || "")
      .split(",").map((s) => s.trim()).filter((s) => /^\d+$/.test(s));
    if (!ids.length) return;
    setProject((p) => {
      const base = (p.assets || []).filter((a) => a.kind === "image").length;
      const added = ids.map((mid, i) => ({ id: uid(), name: "", kind: "image",
        tag: `@image${base + i + 1}`, thumbId: "", source: "", mediaId: mid, lock: true }));
      return { ...p, assets: [...(p.assets || []), ...added] };
    });
    history.replaceState(null, "", location.pathname);
  }, [project]);

  useEffect(() => {
    if (!project || !hasStore) return;
    setBusy(true); clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => { await sSet(PKEY, JSON.stringify(project)); setBusy(false); }, 600);
    return () => clearTimeout(saveTimer.current);
  }, [project]);

  const storeThumb = useCallback(async (file) => {
    const data = await fileToThumb(file); const id = uid();
    setThumbs((t) => ({ ...t, [id]: data })); if (hasStore) await sSet(TPRE + id, data); return id;
  }, []);

  /* mutators */
  const setCard = useCallback((aId, cId, fn) => setProject((p) => ({ ...p, acts: p.acts.map((a) =>
    a.id !== aId ? a : { ...a, cards: a.cards.map((c) => c.id !== cId ? c : fn(c)) }) })), []);
  const setAct = useCallback((aId, patch) => setProject((p) => ({ ...p, acts: p.acts.map((a) => a.id !== aId ? a : { ...a, ...patch }) })), []);
  const setAssets = useCallback((fn) => setProject((p) => ({ ...p, assets: fn(p.assets || []) })), []);

  const addCard = (aId) => { const c = newCard();
    setProject((p) => ({ ...p, acts: p.acts.map((a) => a.id !== aId ? a : { ...a, cards: [...a.cards, c] }) }));
    setOpen((o) => ({ ...o, [c.id]: true })); };
  const dupCard = (aId, card) => { const c = { ...JSON.parse(JSON.stringify(card)), id: uid(), refs: card.refs.map((r) => ({ ...r, id: uid() })) };
    setProject((p) => ({ ...p, acts: p.acts.map((a) => a.id !== aId ? a : { ...a, cards: a.cards.flatMap((x) => x.id === card.id ? [x, c] : [x]) }) })); };
  const delCard = (aId, card) => setProject((p) => ({ ...p, acts: p.acts.map((a) => a.id !== aId ? a : { ...a, cards: a.cards.filter((c) => c.id !== card.id) }) }));
  const moveCard = (aId, idx, dir) => setProject((p) => ({ ...p, acts: p.acts.map((a) => {
    if (a.id !== aId) return a; const j = idx + dir; if (j < 0 || j >= a.cards.length) return a;
    const cs = [...a.cards];[cs[idx], cs[j]] = [cs[j], cs[idx]]; return { ...a, cards: cs }; }) }));
  const moveCardToAct = (fromId, card, toId) => { if (fromId === toId) return;
    setProject((p) => ({ ...p, acts: p.acts.map((a) => a.id === fromId ? { ...a, cards: a.cards.filter((c) => c.id !== card.id) } : a.id === toId ? { ...a, cards: [...a.cards, card] } : a) })); };
  const addAct = () => setProject((p) => ({ ...p, acts: [...p.acts, { id: uid(), name: `Act ${p.acts.length + 1}`, collapsed: false, cards: [] }] }));
  const delAct = (aId) => { const a = project.acts.find((x) => x.id === aId);
    if (a.cards.length && !window.confirm(`Delete "${a.name}" and its ${a.cards.length} card(s)?`)) return;
    setProject((p) => ({ ...p, acts: p.acts.filter((x) => x.id !== aId) })); };
  const moveAct = (idx, dir) => setProject((p) => { const j = idx + dir; if (j < 0 || j >= p.acts.length) return p;
    const as = [...p.acts];[as[idx], as[j]] = [as[j], as[idx]]; return { ...p, acts: as }; });

  /* refs */
  const addRef = (aId, card, kind) => { const n = card.refs.filter((r) => r.kind === kind).length + 1;
    const pre = kind === "image" ? "@image" : kind === "video" ? "@video" : "@audio";
    setCard(aId, card.id, (c) => ({ ...c, refs: [...c.refs, { id: uid(), kind, tag: `${pre}${n}`, role: "", source: "", thumbId: "" }] })); };
  const setRef = (aId, cId, rId, patch) => setCard(aId, cId, (c) => ({ ...c, refs: c.refs.map((r) => r.id !== rId ? r : { ...r, ...patch }) }));
  const delRef = (aId, cId, ref) => setCard(aId, cId, (c) => ({ ...c, refs: c.refs.filter((r) => r.id !== ref.id) }));

  /* export */
  const flat = (p) => p.acts.flatMap((a, ai) => a.cards.map((c, ci) => ({ c, a, ai, ci, code: `${actLetter(ai)}·${String(ci + 1).padStart(2, "0")}` })));
  const shotText = (entry, p) => {
    const { c, code, ai } = entry;
    const idx = flat(p).findIndex((x) => x.c.id === c.id);
    const prev = idx > 0 ? flat(p)[idx - 1] : null;
    const L = [`[${code} — "${c.title || "untitled"}"]  (${c.mode}, ~${c.duration}s, ${CONNECT[c.connect].label})`, ""];
    if (c.connect === "extend" && prev) L.push(`Continue seamlessly from the previous clip ${prev.code} (upload it as @video1).`);
    if (c.connect === "flf") {
      if (c.openFrame.desc || c.openFrame.tag) L.push(`Opening frame ${c.openFrame.tag || "(first image)"}: ${c.openFrame.desc || "—"}`);
      if (c.closeFrame.desc || c.closeFrame.tag) L.push(`Closing frame ${c.closeFrame.tag || "(last image)"}: ${c.closeFrame.desc || "—"}`);
    }
    L.push("", c.prompt || "(prompt tbd)");
    if (c.connect === "extend" || c.connect === "flf") L.push(CONTINUITY_PHRASE);
    const usedCast = (p.assets || []).filter((as) => c.cast.includes(as.id));
    if (usedCast.length) { L.push("", "Keep consistent:"); usedCast.forEach((as) =>
      L.push(`  ${as.name} — ${as.lock ? "maintain exact appearance from " : "reference "}${as.tag}`)); }
    if (c.refs.length) { L.push("", "Other references:"); c.refs.forEach((r) => L.push(`  ${r.tag} — ${r.role || "(role tbd)"}${r.source ? `  [${r.source}]` : ""}`)); }
    if (c.camera) L.push("", `Camera: ${c.camera}`);
    if (c.lighting) L.push(`Lighting/Mood: ${c.lighting}`);
    if (c.audioCue) L.push(`Audio: ${c.audioCue}`);
    if (c.transIn || c.transOut) L.push(`Edit transitions: in ${c.transIn || "—"} / out ${c.transOut || "—"}`);
    if (c.notes) L.push(`Notes: ${c.notes}`);
    return L.join("\n");
  };
  const copyShot = (entry) => navigator.clipboard?.writeText(shotText(entry, project));

  /* ---- Generate shot on PixAI (video provider) ---- */
  const setCardStatus = (cardId, patch) => setProject((p) => ({ ...p, acts: p.acts.map((a) =>
    ({ ...a, cards: a.cards.map((c) => c.id !== cardId ? c : { ...c, ...patch }) })) }));
  const imgSrc = (thumbId, source) => thumbId ? thumbs[thumbId]
    : (source && (source.startsWith("http") || source.startsWith("data:") || /^\d+$/.test(source)) ? source : null);
  const generateShot = async (entry) => {
    const c = entry.c;
    const tagNum = (t) => { const m = /(\d+)/.exec(t || ""); return m ? +m[1] : 99; };
    const imgs = [];
    (project.assets || []).filter((as) => as.kind === "image" && c.cast.includes(as.id))
      .forEach((as) => { const d = as.mediaId || imgSrc(as.thumbId, as.source); if (d) imgs.push({ tag: as.tag, d }); });
    [c.openFrame, c.mode === "FLF" ? c.closeFrame : null].filter(Boolean).forEach((f) => {
      const d = f.mediaId || imgSrc(f.thumbId, f.source); if (d) imgs.push({ tag: f.tag || "@image9", d }); });
    (c.refs || []).filter((r) => r.kind === "image").forEach((r) => {
      const d = r.mediaId || imgSrc(r.thumbId, r.source); if (d) imgs.push({ tag: r.tag, d }); });
    const vids = (c.refs || []).filter((r) => r.kind === "video" && /^\d+$/.test(r.source || "")).map((r) => r.source);
    imgs.sort((a, b) => tagNum(a.tag) - tagNum(b.tag));
    if (!imgs.length && !vids.length) {
      setGenState((s) => ({ ...s, [c.id]: { phase: "error", msg: "attach a frame or cast image first" } })); return; }
    setGenState((s) => ({ ...s, [c.id]: { phase: "submitting", msg: "Submitting…" } }));
    setCardStatus(c.id, { status: "wip" });
    try {
      const r = await fetch("/api/editbay/generate", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: c.mode, prompt: shotText(entry, project), images: imgs.map((x) => x.d),
          video_refs: vids, duration: c.duration }) });
      const d = await r.json();
      if (d.error || !d.task_id) { setGenState((s) => ({ ...s, [c.id]: { phase: "error", msg: d.error || "submit failed" } })); return; }
      pollShot(c.id, d.task_id);
    } catch { setGenState((s) => ({ ...s, [c.id]: { phase: "error", msg: "network error" } })); }
  };
  const pollShot = (cardId, tid) => {
    setGenState((s) => ({ ...s, [cardId]: { phase: "running", msg: "Rendering… (task " + String(tid).slice(-6) + ")" } }));
    const tick = () => fetch("/api/task-status?task_id=" + tid).then((r) => r.json()).then((d) => {
      if (d.phase === "done") { const mid = (d.media_ids || [])[0] || "";
        setGenState((s) => ({ ...s, [cardId]: { phase: "done", msg: "Done", mid } }));
        // capture the clip's REAL length so the reel reflects what was rendered, not planned
        setCardStatus(cardId, { status: "done", resultMid: mid,
          ...(d.duration ? { actualDur: d.duration } : {}) }); }
      else if (d.phase === "failed") setGenState((s) => ({ ...s, [cardId]: { phase: "error", msg: d.error || "failed" } }));
      else setTimeout(tick, 4000);
    }).catch(() => setTimeout(tick, 5000));
    setTimeout(tick, 2500);
  };
  const download = (text, name, type) => { const url = URL.createObjectURL(new Blob([text], { type }));
    const a = document.createElement("a"); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
  const exportAll = () => { let out = `${project.name}\nRuntime target ${fmt(project.target)}\n`;
    if ((project.assets || []).length) { out += `\nCast & assets:\n`; project.assets.forEach((as) => out += `  ${as.tag}  ${as.name} (${as.kind})${as.lock ? " · lock appearance" : ""}\n`); }
    project.acts.forEach((a, ai) => { out += `\n${"=".repeat(48)}\n${a.name}\n${"=".repeat(48)}\n\n`;
      a.cards.forEach((c, ci) => { out += shotText({ c, code: `${actLetter(ai)}·${String(ci + 1).padStart(2, "0")}`, ai, ci }, project) + "\n\n"; }); });
    download(out, `${project.name.replace(/\s+/g, "_")}_shotlist.txt`, "text/plain"); };
  const exportJSON = () => download(JSON.stringify({ project, thumbs }, null, 2), `${project.name.replace(/\s+/g, "_")}_backup.json`, "application/json");
  const importJSON = async (file) => { if (!file) return; try { const d = JSON.parse(await file.text());
    if (d.project) { setProject(d.project); if (d.thumbs) { setThumbs(d.thumbs); if (hasStore) for (const [k, v] of Object.entries(d.thumbs)) await sSet(TPRE + k, v); } } }
    catch { window.alert("That file didn't parse as a storyboard backup."); } };

  if (!project) return <div className="sb-root"><style>{STYLES}</style><div className="sb-empty">Loading the bay…</div></div>;

  const entries = flat(project);
  // Play-sequence: every finished shot (persisted resultMid), in order, with its
  // in/out trim -- a rough cut played back-to-back, nothing rendered.
  const playSequence = () => {
    const clips = entries.filter((e) => e.c.resultMid).map((e) => ({
      mid: e.c.resultMid, in: e.c.trimIn || 0, out: e.c.trimOut, title: e.c.title, code: e.code }));
    if (clips.length) setSeq(clips); else alert("No finished shots yet — generate one first.");
  };
  const anyDone = entries.some((e) => e.c.resultMid);
  // reel uses the ACTUAL generated length when a shot has rendered, else the planned duration
  const durOf = (c) => Number(c.actualDur || c.duration) || 0;
  const total = entries.reduce((s, x) => s + durOf(x.c), 0);
  const done = entries.filter((x) => x.c.status === "done").length;
  const scale = Math.max(total, project.target) || 1;
  const over = total - project.target;

  // Batch-generate the whole board: fire every not-done shot in sequence, staggered so
  // the submits don't collide. Each shot manages its own status/poll via generateShot.
  const batchGenerate = async () => {
    const todo = entries.filter((e) => e.c.status !== "done");
    if (!todo.length) return;
    if (!window.confirm(`Generate ${todo.length} shot(s) on PixAI? Each is free with a V4.0 card; otherwise credits apply.`)) return;
    setBatching(true);
    for (const e of todo) {
      try { await generateShot(e); } catch (_e) { /* keep going */ }
      await new Promise((r) => setTimeout(r, 2200));
    }
    setBatching(false);
  };

  return (
    <div className="sb-root">
      <style>{STYLES}</style>
      {seq && <SequencePlayer clips={seq} onClose={() => setSeq(null)} />}
      {pickCb && <GalleryPick onClose={() => setPickCb(null)}
        onPick={(mid, thumb) => { const cb = pickCb; setPickCb(null); cb(mid, thumb); }} />}

      <header className="sb-top">
        <div className="sb-topgrid">
          <div className="sb-brand">
            <a href="/" className="sb-btn ghost sm" title="Back to the gallery"
              style={{ textDecoration: "none", flexShrink: 0 }}>← Gallery</a>
            <h1 className="sb-disp"><span className="sb-clap">▰</span> The Loom</h1>
            <input className="sb-projname" value={project.name} onChange={(e) => setProject((p) => ({ ...p, name: e.target.value }))} aria-label="Project name" />
            <button className="sb-btn" onClick={batchGenerate} disabled={batching || !entries.length}
              title="Generate every shot that isn't done yet, one after another">
              {batching ? "▶ generating all…" : `▶ Generate all (${entries.filter((e) => e.c.status !== "done").length})`}</button>
            <button className="sb-btn amber" onClick={playSequence} disabled={!anyDone}
              title="Play every finished shot back-to-back, honoring trims — a rough cut, no rendering">&#9654;&#9654; Play</button>
          </div>
          <div className="sb-stat"><b>{done}/{entries.length}</b><span>shots done</span></div>
          <div className="sb-stat"><b style={{ color: over > 0 ? "var(--coral)" : "var(--ink)" }}>{fmt(total)}</b>
            <span>of {fmt(project.target)}{over > 0 ? ` · +${fmt(over)} over` : ""}</span></div>
          <div className="sb-saved" title={hasStore ? "Saved to this browser" : "In-memory only — export to keep"}>
            <span className={"sb-dot" + (busy ? " busy" : "")} /> {hasStore ? (busy ? "saving" : "saved") : "session only"}</div>
        </div>
        <div className="sb-reel-wrap">
          <div className="sb-reel">
            {entries.map((x, i) => (<div key={i} className={"sb-seg " + x.c.status}
              style={{ width: `${(durOf(x.c) / scale) * 100}%` }}
              title={`${x.code} ${x.c.title || ""} · ${durOf(x.c)}s${x.c.actualDur ? " (rendered)" : ""}`} />))}
            <div className="sb-target" style={{ left: `${(project.target / scale) * 100}%` }} />
          </div>
          <div className="sb-reel-legend">
            <span><i style={{ background: "#3a3450" }} />to do</span>
            <span><i style={{ background: "var(--amber)" }} />in progress</span>
            <span><i style={{ background: "var(--green)" }} />done</span>
            <span style={{ marginLeft: "auto" }}>{entries.length} clips · target 8:00</span>
          </div>
        </div>
      </header>

      <div className="sb-wrap">
        <div className="sb-toolbar">
          <button className="sb-btn ghost sm" onClick={() => setShowHelp((s) => !s)}>{showHelp ? "Hide cheat-sheet" : "Continuity cheat-sheet"}</button>
          <div className="sb-divider" />
          <button className="sb-btn sm" onClick={exportAll}>Export shot list (.txt)</button>
          <button className="sb-btn sm" onClick={exportJSON}>Backup (.json)</button>
          <label className="sb-btn sm ghost" style={{ cursor: "pointer" }}>Restore
            <input type="file" accept="application/json" style={{ display: "none" }} onChange={(e) => importJSON(e.target.files[0])} /></label>
        </div>
        {showHelp && (
          <div className="sb-helpbox">
            <h4>@references in plain terms</h4>
            An <code>@tag</code> is a name for a file you upload, numbered in upload order: the first image is <code>@image1</code>, the first video <code>@video1</code>, first audio <code>@audio1</code>. In the prompt you say what each one is <b>for</b> — identity, the opening frame, camera motion, the beat.
            <h4>Three ways to keep clips flowing</h4>
            <b>Extend</b> — feed the previous clip as <code>@video1</code>; the model anchors to its final frames and continues forward. Keep each extension ~5–10s.<br />
            <b>First→Last</b> — give the shot a start image and an end image; prompt the <b>motion between them</b>, not the stills, with "{CONTINUITY_PHRASE}" Keep the two frames similar in composition or the subject warps.<br />
            <b>Cast lock</b> — define each recurring person/place once in <b>Cast &amp; Assets</b> and reuse the same <code>@tag</code> everywhere; the assembled prompt writes "maintain exact appearance from @image1" for you.
            <h4>The drift rule</h4>
            Consistency fades the further you chain. Re-anchor to your original Cast reference every <b>4–5 shots</b>, and your closing frame of one shot should be the opening frame of the next — that's the chain the board tracks.
          </div>
        )}
      </div>

      {/* CAST & ASSETS */}
      <div className="sb-wrap" style={{ paddingTop: 0 }}>
        <div className="sb-panel">
          <div className="sb-panelhead" onClick={() => setShowCast((s) => !s)}>
            <span className="sb-ico">{showCast ? "▾" : "▸"}</span>
            <h3 className="sb-disp">Cast &amp; Assets</h3>
            <span className="sb-hint" style={{ marginLeft: "auto" }}>{(project.assets || []).length} reusable refs — define once, reuse everywhere</span>
          </div>
          {showCast && (
            <div className="sb-panelbody">
              {(project.assets || []).map((as) => {
                const prev = as.thumbId ? thumbs[as.thumbId]
                  : (as.mediaId ? "/thumbs/" + as.mediaId + ".jpg"
                    : (as.kind === "image" && as.source.startsWith("http") ? as.source : null));
                return (
                  <div className="sb-assetrow" key={as.id}>
                    {as.kind === "image" ? (
                      <label className="sb-assetprev" title="Attach image">
                        {prev ? <img src={prev} alt={as.name} /> : "＋"}
                        <input type="file" accept="image/*" style={{ display: "none" }}
                          onChange={async (e) => { const f = e.target.files[0]; if (!f) return; const id = await storeThumb(f);
                            setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, thumbId: id, source: x.source || f.name, mediaId: "" })); }} /></label>
                    ) : <div className="sb-assetprev">{as.kind === "video" ? "🎞" : "♪"}</div>}
                    {as.kind === "image" && <button className="sb-ico" title="Pick from the gallery"
                      onClick={() => openPick((mid) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, mediaId: mid, thumbId: "", source: "" })))}>▤</button>}
                    <input className="sb-in" style={{ flex: "1 1 120px" }} value={as.name} placeholder="name (Her, Me, the room…)"
                      onChange={(e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, name: e.target.value }))} />
                    <input className="sb-tagin sb-mono" value={as.tag} onChange={(e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, tag: e.target.value }))} />
                    <select className="sb-sel" style={{ width: "auto" }} value={as.kind} onChange={(e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, kind: e.target.value }))}>
                      <option value="image">image</option><option value="video">video</option><option value="audio">audio</option></select>
                    <label className="sb-toggle" title="Write 'maintain exact appearance' in prompts">
                      <input type="checkbox" checked={as.lock} onChange={(e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, lock: e.target.checked }))} />lock</label>
                    <button className="sb-ico" onClick={() => setAssets((a) => a.filter((x) => x.id !== as.id))} title="Remove">✕</button>
                  </div>
                );
              })}
              <button className="sb-btn ghost sm" style={{ alignSelf: "flex-start" }}
                onClick={() => setAssets((a) => [...a, { id: uid(), name: "", kind: "image", tag: `@image${a.filter((x) => x.kind === "image").length + 1}`, thumbId: "", source: "", lock: true }])}>+ Add reference</button>
            </div>
          )}
        </div>
      </div>

      {/* ACTS */}
      <main className="sb-main">
        {project.acts.map((act, ai) => {
          const sub = act.cards.reduce((s, c) => s + (Number(c.duration) || 0), 0);
          return (
            <section className="sb-act" key={act.id}>
              <div className="sb-acthead">
                <button className="sb-ico" onClick={() => setAct(act.id, { collapsed: !act.collapsed })}>{act.collapsed ? "▸" : "▾"}</button>
                <span className="sb-actcode sb-mono">{actLetter(ai)}</span>
                <input className="sb-actname" value={act.name} onChange={(e) => setAct(act.id, { name: e.target.value })} aria-label="Act name" />
                <span className="sb-actmeta">{act.cards.length} · {fmt(sub)}</span>
                <button className="sb-ico" onClick={() => moveAct(ai, -1)} title="Move act up">↑</button>
                <button className="sb-ico" onClick={() => moveAct(ai, 1)} title="Move act down">↓</button>
                <button className="sb-ico" onClick={() => delAct(act.id)} title="Delete act">✕</button>
              </div>
              {!act.collapsed && (
                <div className="sb-grid">
                  {act.cards.map((card, ci) => {
                    const code = `${actLetter(ai)}·${String(ci + 1).padStart(2, "0")}`;
                    const gIdx = entries.findIndex((x) => x.c.id === card.id);
                    const prev = gIdx > 0 ? entries[gIdx - 1] : null;
                    return (
                      <CardView key={card.id} {...{ act, card, ci, ai, code, prev, project, thumbs, open, setOpen,
                        setCard, addRef, setRef, delRef, storeThumb, dupCard, delCard, moveCard, moveCardToAct, copyShot, generateShot, genState, entries, openPick }} />
                    );
                  })}
                  <button className="sb-add" onClick={() => addCard(act.id)}>+ Add shot to {act.name}</button>
                </div>
              )}
            </section>
          );
        })}
        <button className="sb-btn ghost" onClick={addAct} style={{ marginTop: 6 }}>+ Add act</button>
      </main>
    </div>
  );
}

/* ===================== CARD ===================== */
/* Hover-scrub preview + non-destructive TRIM. Hovering the video maps mouse-X to
   playback time (clamped to the kept region); a track below has draggable in/out
   handles that store trimIn/trimOut (seconds) on the shot. Nothing is re-encoded
   here -- trims are just metadata that Play-sequence and Export will honor.
   /video-file/<id> supports Range requests, so every seek is instant. */
function ShotPreview({ mid, trimIn, trimOut, onTrim }) {
  const vidRef = useRef(null), trackRef = useRef(null);
  const [dur, setDur] = useState(0);
  const [range, setRange] = useState({ in: trimIn || 0, out: trimOut });
  const rangeRef = useRef(range); rangeRef.current = range;
  const durRef = useRef(0); durRef.current = dur;
  const dragRef = useRef(null);
  useEffect(() => { setRange({ in: trimIn || 0, out: trimOut }); }, [trimIn, trimOut]);
  const effOut = (range.out == null ? dur : range.out) || dur;
  const pct = (s) => (dur ? Math.max(0, Math.min(100, (s / dur) * 100)) : 0);
  const fT = (s) => (s || 0).toFixed(1) + "s";
  const secAt = (clientX) => {
    const t = trackRef.current.getBoundingClientRect();
    return Math.max(0, Math.min(durRef.current, ((clientX - t.left) / t.width) * durRef.current));
  };
  const scrub = (e) => {
    const v = vidRef.current; if (!v || !dur) return;
    const r = e.currentTarget.getBoundingClientRect();
    const t = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    v.currentTime = range.in + t * Math.max(0.01, effOut - range.in);
  };
  const onMove = (e) => {
    if (!dragRef.current || !durRef.current) return;
    const s = secAt(e.clientX), r = rangeRef.current, eff = (r.out == null ? durRef.current : r.out);
    setRange(dragRef.current === "in" ? { ...r, in: Math.min(s, eff - 0.1) }
                                      : { ...r, out: Math.max(s, r.in + 0.1) });
    const v = vidRef.current; if (v) v.currentTime = s;
  };
  const onUp = () => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    if (dragRef.current) { const r = rangeRef.current; onTrim(r.in, r.out); }
    dragRef.current = null;
  };
  const startDrag = (which) => (e) => {
    e.preventDefault(); e.stopPropagation(); dragRef.current = which;
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };
  const trimmed = range.in > 0 || range.out != null;
  return (
    <div className="sb-shotprev-wrap">
      <div className="sb-shotprev" onMouseMove={scrub}
        onMouseLeave={() => { const v = vidRef.current; if (v) v.currentTime = range.in; }}>
        <video ref={vidRef} src={"/video-file/" + mid} muted preload="metadata" playsInline
          onLoadedMetadata={(e) => setDur(e.currentTarget.duration || 0)} />
        <div className="sb-shotprev-hint">hover to scrub</div>
      </div>
      <div className="sb-trim">
        <div className="sb-trim-track" ref={trackRef}
          onPointerDown={(e) => { const v = vidRef.current; if (v && dur) v.currentTime = secAt(e.clientX); }}>
          <div className="sb-trim-sel" style={{ left: pct(range.in) + "%", right: (100 - pct(effOut)) + "%" }} />
          <div className="sb-trim-h" style={{ left: pct(range.in) + "%" }} onPointerDown={startDrag("in")} title="Trim in" />
          <div className="sb-trim-h" style={{ left: pct(effOut) + "%" }} onPointerDown={startDrag("out")} title="Trim out" />
        </div>
        <div className="sb-trim-read">
          {fT(range.in)} &rarr; {fT(effOut)} &middot; <b>{fT(Math.max(0, effOut - range.in))}</b> kept
          {trimmed && <button className="sb-trim-reset" onClick={() => onTrim(0, null)}>reset</button>}
        </div>
      </div>
    </div>
  );
}

/* Play-sequence overlay: plays finished shots back-to-back, each from its in
   point to its out point, then advances. A rough cut with zero rendering --
   the browser just seeks a single <video> through /video-file/<id> per clip. */
function SequencePlayer({ clips, onClose }) {
  const vRef = useRef(null);
  const [i, setI] = useState(0);
  const clip = clips[i];
  useEffect(() => {
    const v = vRef.current; if (!v || !clip) return;
    const seekPlay = () => { try { v.currentTime = clip.in || 0; } catch (e) {} v.play().catch(() => {}); };
    const onTime = () => {
      const end = (clip.out != null ? clip.out : v.duration) || 0;
      if (end && v.currentTime >= end - 0.04) {
        if (i < clips.length - 1) setI(i + 1); else onClose();
      }
    };
    v.addEventListener("loadedmetadata", seekPlay);
    v.addEventListener("timeupdate", onTime);
    if (v.readyState >= 1) seekPlay();
    return () => { v.removeEventListener("loadedmetadata", seekPlay); v.removeEventListener("timeupdate", onTime); };
  }, [i]);   // eslint-disable-line
  useEffect(() => {
    const esc = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc); return () => window.removeEventListener("keydown", esc);
  }, []);
  if (!clip) return null;
  return (
    <div className="sb-seq" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="sb-seq-box">
        <video ref={vRef} key={clip.mid} src={"/video-file/" + clip.mid} autoPlay playsInline
          onClick={(e) => { const v = e.currentTarget; v.paused ? v.play() : v.pause(); }} />
        <div className="sb-seq-bar">
          <span>Shot {i + 1}/{clips.length}{clip.code ? " · " + clip.code : ""}{clip.title ? " — " + clip.title : ""}</span>
          <button className="sb-btn ghost sm" onClick={() => setI(Math.max(0, i - 1))} disabled={i === 0}>&#9664; prev</button>
          <button className="sb-btn ghost sm" onClick={() => { if (i < clips.length - 1) setI(i + 1); else onClose(); }}>next &#9654;</button>
          <button className="sb-btn sm" onClick={onClose}>&#10005; close</button>
        </div>
      </div>
    </div>
  );
}

function CardView({ act, card, ci, ai, code, prev, project, thumbs, open, setOpen, setCard, addRef, setRef, delRef, storeThumb, dupCard, delCard, moveCard, moveCardToAct, copyShot, generateShot, genState, entries, openPick }) {
  const isOpen = open[card.id];
  const framePrev = (f) => f.thumbId ? thumbs[f.thumbId]
    : (f.mediaId ? "/thumbs/" + f.mediaId + ".jpg"
      : (f.source && f.source.startsWith("http") ? f.source : null));
  const openImg = framePrev(card.openFrame), closeImg = framePrev(card.closeFrame);
  const prevClose = prev ? prev.c.closeFrame : null;
  const linked = prev && prevClose && card.openFrame.thumbId && prevClose.thumbId && card.openFrame.thumbId === prevClose.thumbId;
  const needsLink = prev && (card.connect === "extend" || card.connect === "flf" || card.connect === "cut");
  const entry = { c: card, code, ai, ci };

  return (
    <article className={"sb-card" + (isOpen ? " open" : "")}>
      {prev && card.connect !== "new" && (
        <div className="sb-fromstrip">
          <span className={"sb-linkdot " + (linked ? "sb-link-ok" : needsLink ? "sb-link-warn" : "")}>{linked ? "✓" : needsLink ? "⚠" : "·"}</span>
          {linked ? `opens on ${prev.code}'s closing frame` : needsLink ? `open frame ≠ ${prev.code} close — link it` : `from ${prev.code}`}
          <span className="sb-connbadge">{CONNECT[card.connect].label}</span>
        </div>
      )}
      <div className="sb-slate">
        <button className={"sb-tick " + card.status} title={`Status: ${card.status} (click to cycle)`}
          onClick={() => setCard(act.id, card.id, (c) => ({ ...c, status: c.status === "todo" ? "wip" : c.status === "wip" ? "done" : "todo" }))}>✓</button>
        <span className="sb-code">{code}</span>
        <input className="sb-ctitle" placeholder="shot title…" value={card.title} onChange={(e) => setCard(act.id, card.id, (c) => ({ ...c, title: e.target.value }))} />
        <span className="sb-mode">{card.mode}</span>
        <span className="sb-tc">{card.duration}s</span>
        <button className="sb-ico" onClick={() => setOpen((o) => ({ ...o, [card.id]: !isOpen }))} title={isOpen ? "Collapse" : "Edit"}>{isOpen ? "▾" : "✎"}</button>
      </div>

      {!isOpen ? (
        <div className="sb-body">
          <div className="sb-frames-mini">
            <div className="sb-fm">
              <div className="sb-fmlab"><span>open</span></div>
              <div className={"sb-fmbox" + (card.discreet ? " discreet" : "")}>{openImg ? <img src={openImg} alt="open" /> : (card.openFrame.desc || "—")}</div>
            </div>
            <div className="sb-arrowmid">→</div>
            <div className="sb-fm">
              <div className="sb-fmlab"><span>close</span></div>
              <div className={"sb-fmbox" + (card.discreet ? " discreet" : "")}>{closeImg ? <img src={closeImg} alt="close" /> : (card.closeFrame.desc || "—")}</div>
            </div>
          </div>
          <div className={"sb-prompt-mini" + (card.prompt ? "" : " empty")} onClick={() => setOpen((o) => ({ ...o, [card.id]: true }))}>
            {card.prompt || "no prompt yet — tap to write"}</div>
          <div className="sb-minimeta">
            {card.camera && <span className="sb-chip"><b>cam</b> {card.camera}</span>}
            {card.cast.length > 0 && <span className="sb-chip"><b>cast</b> {card.cast.length}</span>}
          </div>
        </div>
      ) : (
        <CardEditor {...{ act, card, ci, ai, prev, project, thumbs, setCard, addRef, setRef, delRef, storeThumb, dupCard, delCard, moveCard, moveCardToAct, copyShot, generateShot, genState, entry, framePrev, openPick }} />
      )}
    </article>
  );
}

/* ===================== EDITOR ===================== */
function GalleryPick({ onPick, onClose }) {
  const [q, setQ] = useState("");
  const [imgs, setImgs] = useState([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const load = (p, query, append) =>
    fetch(`/api/gallery-images?limit=60&page=${p}&q=${encodeURIComponent(query)}`)
      .then((r) => r.json())
      .then((d) => { setImgs((old) => append ? [...old, ...(d.images || [])] : (d.images || [])); setTotal(d.total || 0); })
      .catch(() => {});
  useEffect(() => { load(1, "", false); }, []);
  return (
    <div style={{ position: "fixed", inset: 0, zIndex: 400, background: "rgba(6,4,16,.72)", display: "flex", alignItems: "center", justifyContent: "center" }}
         onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{ width: 860, maxWidth: "92vw", height: "80vh", background: "var(--panel, #1d1a26)", border: "1px solid var(--line, #3a3550)", borderRadius: 12, padding: 14, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <b>Pick from your gallery</b>
          <input className="sb-in" style={{ flex: 1 }} placeholder="Search prompts…" value={q} autoFocus
            onChange={(e) => { setQ(e.target.value); setPage(1); load(1, e.target.value, false); }} />
          <button className="sb-btn ghost sm" onClick={onClose}>✕</button>
        </div>
        <div style={{ flex: 1, overflowY: "auto", display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(110px,1fr))", gap: 8, alignContent: "start" }}>
          {imgs.map((m) => (
            <div key={m.media_id} title={m.prompt}
                 style={{ borderRadius: 8, overflow: "hidden", border: "1px solid var(--line, #3a3550)", cursor: "pointer" }}
                 onClick={() => onPick(m.media_id, m.thumb)}>
              <img src={m.thumb} loading="lazy" decoding="async" alt=""
                style={{ width: "100%", aspectRatio: "1", objectFit: "cover", display: "block" }} />
            </div>))}
        </div>
        {imgs.length < total &&
          <button className="sb-btn ghost sm" style={{ alignSelf: "center" }}
            onClick={() => { const p = page + 1; setPage(p); load(p, q, true); }}>Load more ({imgs.length}/{total})</button>}
      </div>
    </div>
  );
}

function FrameSlot({ which, frame, discreet, framePrev, onPatch, storeThumb, openPick, extraBtn }) {
  const img = framePrev(frame);
  return (
    <div className="sb-frame">
      <div className="sb-framehead">
        <span className="sb-lab">{which === "open" ? "Opening frame" : "Closing frame"}</span>
        {openPick && <button className="sb-ico" title="Pick from the gallery"
          onClick={() => openPick((mid) => onPatch({ mediaId: mid, thumbId: "", source: "" }))}>▤</button>}
        <input className="sb-tagin sb-mono" placeholder="@image1" value={frame.tag} onChange={(e) => onPatch({ tag: e.target.value })} />
      </div>
      <label className={"sb-frameprev" + (discreet ? " discreet" : "")} title="Attach image">
        {img ? <img src={img} alt={which} /> : "＋ attach frame"}
        <input type="file" accept="image/*" style={{ display: "none" }}
          onChange={async (e) => { const f = e.target.files[0]; if (!f) return; const id = await storeThumb(f); onPatch({ thumbId: id, source: frame.source || f.name, mediaId: "" }); }} /></label>
      <input className="sb-in" placeholder="describe this frame (composition, subject position, light)" value={frame.desc} onChange={(e) => onPatch({ desc: e.target.value })} />
      {extraBtn}
    </div>
  );
}

function CardEditor({ act, card, ci, ai, prev, project, thumbs, setCard, addRef, setRef, delRef, storeThumb, dupCard, delCard, moveCard, moveCardToAct, copyShot, generateShot, genState, entry, framePrev, openPick }) {
  const [palFor, setPalFor] = useState(null);
  const setF = (field, val) => setCard(act.id, card.id, (c) => ({ ...c, [field]: val }));
  const append = (field, val) => setCard(act.id, card.id, (c) => ({ ...c, [field]: c[field] ? `${c[field]}, ${val}` : val }));
  const patchFrame = (key, patch) => setCard(act.id, card.id, (c) => ({ ...c, [key]: { ...c[key], ...patch } }));
  const [handoff, setHandoff] = useState("");   // '', 'wip', 'err'
  const inheritPrev = () => {
    if (!prev) return;
    // Frame handoff: if the previous shot was actually GENERATED, pull its clip's real
    // last frame; otherwise fall back to copying its planned closing frame.
    const rmid = prev.c.resultMid;
    if (rmid) {
      setHandoff("wip");
      fetch("/api/editbay/handoff", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_media_id: rmid }) })
        .then((r) => r.json()).then((d) => {
          if (d.error || !d.frame_media_id) { setHandoff("err"); return; }
          setHandoff("");
          patchFrame("openFrame", { mediaId: d.frame_media_id, thumbId: "", source: "",
            desc: "handed off from " + (prev.code || "prev shot") });
        }).catch(() => setHandoff("err"));
    } else {
      patchFrame("openFrame", { ...prev.c.closeFrame });
    }
  };
  const toggleCast = (id) => setCard(act.id, card.id, (c) => ({ ...c, cast: c.cast.includes(id) ? c.cast.filter((x) => x !== id) : [...c.cast, id] }));

  return (
    <div className="sb-edit">
      <div className="sb-row">
        <div className="sb-field" style={{ flex: "0 0 110px" }}>
          <label className="sb-lab">Mode</label>
          <select className="sb-sel" value={card.mode} onChange={(e) => setF("mode", e.target.value)}>{MODES.map((m) => <option key={m}>{m}</option>)}</select>
          <span className="sb-hint">{MODE_HINT[card.mode]}</span>
        </div>
        <div className="sb-field" style={{ flex: "0 0 150px" }}>
          <label className="sb-lab">Joins previous via</label>
          <select className="sb-sel" value={card.connect} onChange={(e) => setF("connect", e.target.value)}>
            {Object.entries(CONNECT).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}</select>
          <span className="sb-hint">{CONNECT[card.connect].hint}</span>
        </div>
        <div className="sb-field" style={{ flex: "0 0 90px" }}>
          <label className="sb-lab">Duration (s)</label>
          <input className="sb-in" type="number" min="1" value={card.duration} onChange={(e) => setF("duration", Number(e.target.value))} />
        </div>
        <div className="sb-field" style={{ flex: "0 0 auto", justifyContent: "flex-end" }}>
          <label className="sb-lab">Discreet</label>
          <label className="sb-toggle" title="Blur this shot's frames/refs on the board">
            <input type="checkbox" checked={card.discreet} onChange={(e) => setF("discreet", e.target.checked)} />blur previews</label>
        </div>
      </div>

      {/* FRAME HANDOFF */}
      <div className="sb-section">
        <h5>Frame handoff — close of one shot opens the next</h5>
        <div className="sb-twoframes">
          <FrameSlot which="open" frame={card.openFrame} discreet={card.discreet} framePrev={framePrev} storeThumb={storeThumb} openPick={openPick}
            onPatch={(p) => patchFrame("openFrame", p)}
            extraBtn={prev ? <button className="sb-btn ghost sm" onClick={inheritPrev} disabled={handoff === "wip"}
                title={prev.c.resultMid ? `Splice in ${prev.code}'s generated clip's last frame` : `Copy ${prev.code}'s closing frame here`}>
                {handoff === "wip" ? "✂ splicing…" : handoff === "err" ? "✂ splice failed — retry"
                  : prev.c.resultMid ? `✂ splice ${prev.code}'s last frame` : `↳ inherit ${prev.code} close`}</button>
              : <span className="sb-hint">first shot — no previous frame</span>} />
          <div className="sb-conn-mid">→</div>
          <FrameSlot which="close" frame={card.closeFrame} discreet={card.discreet} framePrev={framePrev} storeThumb={storeThumb} openPick={openPick}
            onPatch={(p) => patchFrame("closeFrame", p)} />
        </div>
        <span className="sb-hint" style={{ marginTop: 6 }}>For First→Last shots, prompt the motion between these two — not the stills. Keep them close in composition so the subject doesn't warp.</span>
      </div>

      <div className="sb-field">
        <label className="sb-lab">Prompt — lead with subject + action</label>
        <textarea className="sb-ta big" value={card.prompt} onChange={(e) => setF("prompt", e.target.value)}
          placeholder={card.connect === "extend" ? "What happens next as the previous clip continues (motion only)…" : "Who/what is in frame and what they're doing first; then environment, then style…"} />
      </div>

      {/* CAST */}
      {(project.assets || []).length > 0 && (
        <div className="sb-field">
          <label className="sb-lab">Cast in this shot — keeps them consistent</label>
          <div className="sb-casttoggle">
            {project.assets.map((as) => (
              <button key={as.id} className={"sb-castchip" + (card.cast.includes(as.id) ? " on" : "")} onClick={() => toggleCast(as.id)}>
                {as.name || "(unnamed)"} <span className="sb-ct">{as.tag}</span>{as.lock ? " 🔒" : ""}</button>
            ))}
          </div>
        </div>
      )}

      {/* EXTRA REFS */}
      <div className="sb-field">
        <label className="sb-lab">Other references &amp; @tags</label>
        {card.refs.map((r) => {
          const preview = r.thumbId ? thumbs[r.thumbId] : (r.kind === "image" && r.source.startsWith("http") ? r.source : null);
          return (
            <div className="sb-ref" key={r.id}>
              {r.kind === "image" ? (
                <label className={"sb-refprev" + (card.discreet ? " discreet" : "")} title="Attach image">
                  {preview ? <img src={preview} alt={r.tag} /> : "＋"}
                  <input type="file" accept="image/*" style={{ display: "none" }}
                    onChange={async (e) => { const f = e.target.files[0]; if (!f) return; const id = await storeThumb(f); setRef(act.id, card.id, r.id, { thumbId: id, source: r.source || f.name }); }} /></label>
              ) : <div className="sb-refprev">{r.kind === "video" ? "🎞" : "♪"}</div>}
              <div className="sb-refbody">
                <div style={{ display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap" }}>
                  <input className="sb-tagin sb-mono" value={r.tag} onChange={(e) => setRef(act.id, card.id, r.id, { tag: e.target.value })} />
                  <span className="sb-hint">{r.kind}</span>
                  <button className="sb-ico" style={{ marginLeft: "auto" }} onClick={() => delRef(act.id, card.id, r)}>✕</button>
                </div>
                <input className="sb-in" placeholder="what to use it for (motion / camera / mood…)" value={r.role} onChange={(e) => setRef(act.id, card.id, r.id, { role: e.target.value })} />
                <input className="sb-in" placeholder="file name or URL" value={r.source} onChange={(e) => setRef(act.id, card.id, r.id, { source: e.target.value })} />
              </div>
            </div>
          );
        })}
        <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
          <button className="sb-btn sm ghost" onClick={() => addRef(act.id, card, "image")}>+ Image</button>
          <button className="sb-btn sm ghost" onClick={() => addRef(act.id, card, "video")}>+ Video</button>
          <button className="sb-btn sm ghost" onClick={() => addRef(act.id, card, "audio")}>+ Audio</button>
        </div>
      </div>

      <div className="sb-field">
        <label className="sb-lab">Camera <button className="sb-ico" style={{ fontSize: 11 }} onClick={() => setPalFor(palFor === "camera" ? null : "camera")}>＋terms</button></label>
        <input className="sb-in" value={card.camera} onChange={(e) => setF("camera", e.target.value)} placeholder="e.g. CU, slow push in, shallow depth of field" />
        {palFor === "camera" && (<div className="sb-pal">{Object.entries(CAM_PALETTE).map(([grp, items]) => (
          <React.Fragment key={grp}><div className="sb-palgrp">{grp}</div>
            {items.map((t) => <button key={t} className="sb-pchip sb-mono" onClick={() => append("camera", t)}>{t}</button>)}</React.Fragment>))}</div>)}
      </div>

      <div className="sb-row">
        <div className="sb-field"><label className="sb-lab">Lighting &amp; mood</label>
          <input className="sb-in" value={card.lighting} onChange={(e) => setF("lighting", e.target.value)} placeholder="golden hour, low-key, warm haze…" /></div>
        <div className="sb-field"><label className="sb-lab">Music / audio cue</label>
          <input className="sb-in" value={card.audioCue} onChange={(e) => setF("audioCue", e.target.value)} placeholder="track, beat sync, room tone…" /></div>
      </div>

      <div className="sb-row">
        <div className="sb-field"><label className="sb-lab">Transition in <button className="sb-ico" style={{ fontSize: 11 }} onClick={() => setPalFor(palFor === "in" ? null : "in")}>＋</button></label>
          <input className="sb-in" value={card.transIn} onChange={(e) => setF("transIn", e.target.value)} placeholder="cut, fade in…" />
          {palFor === "in" && <div className="sb-pal">{TRANS_PALETTE.map((t) => <button key={t} className="sb-pchip sb-mono" onClick={() => setF("transIn", t)}>{t}</button>)}</div>}</div>
        <div className="sb-field"><label className="sb-lab">Transition out <button className="sb-ico" style={{ fontSize: 11 }} onClick={() => setPalFor(palFor === "out" ? null : "out")}>＋</button></label>
          <input className="sb-in" value={card.transOut} onChange={(e) => setF("transOut", e.target.value)} placeholder="cut, dissolve…" />
          {palFor === "out" && <div className="sb-pal">{TRANS_PALETTE.map((t) => <button key={t} className="sb-pchip sb-mono" onClick={() => setF("transOut", t)}>{t}</button>)}</div>}</div>
      </div>

      <div className="sb-field"><label className="sb-lab">Notes</label>
        <textarea className="sb-ta" value={card.notes} onChange={(e) => setF("notes", e.target.value)} placeholder="blocking, continuity reminders…" /></div>

      <div className="sb-toolbar">
        <button className="sb-btn amber sm" onClick={() => copyShot(entry)}>Copy shot</button>
        {(() => { const g = genState[card.id] || {}; const busy = g.phase === "submitting" || g.phase === "running";
          return <button className="sb-btn sm" disabled={busy} onClick={() => generateShot(entry)}
            title="Render this shot on PixAI (free with a V4.0 card)">{busy ? "Generating…" : "▶ Generate shot"}</button>; })()}
        <button className="sb-btn ghost sm" onClick={() => moveCard(act.id, ci, -1)}>↑</button>
        <button className="sb-btn ghost sm" onClick={() => moveCard(act.id, ci, 1)}>↓</button>
        <select className="sb-sel sm" style={{ width: "auto", fontSize: 12, padding: "6px 8px" }} value="" onChange={(e) => e.target.value && moveCardToAct(act.id, card, e.target.value)}>
          <option value="">move to act…</option>{project.acts.filter((a) => a.id !== act.id).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select>
        <div className="sb-divider" />
        <button className="sb-btn ghost sm" onClick={() => dupCard(act.id, card)}>Duplicate</button>
        <button className="sb-btn ghost sm danger" onClick={() => delCard(act.id, card)}>Delete</button>
      </div>
      {(() => { const g = genState[card.id]; if (!g) return null;
        const col = g.phase === "done" ? "var(--green)" : g.phase === "error" ? "var(--coral)" : "var(--amber)";
        return (<>
        <div style={{ fontSize: 12, color: col, display: "flex", alignItems: "center", gap: 10, marginTop: 2 }}>
          <span>{g.phase === "done" ? "✓ " : g.phase === "error" ? "⚠ " : "… "}{g.msg}</span>
          {g.phase === "done" && g.mid && (<a className="sb-mono" href={"/image/" + g.mid} target="_blank" rel="noreferrer"
            style={{ color: "var(--cyan)" }}>open full ↗</a>)}
        </div>
        </>); })()}
      {card.resultMid &&
        <ShotPreview mid={card.resultMid} trimIn={card.trimIn} trimOut={card.trimOut}
          onTrim={(i, o) => setCard(act.id, card.id, (c) => ({ ...c, trimIn: i, trimOut: o }))} />}
    </div>
  );
}
