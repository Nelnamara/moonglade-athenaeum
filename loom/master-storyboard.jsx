import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
// Pure, framework-agnostic logic (tag numbering, continuity checks, shot-text
// assembly, reel duration/pricing math) lives in ./src/loom-core.js so it can
// be unit-tested under `node --test` outside React. `shotPayload` is imported
// under an alias because App() wraps it with the component's own `imgSrc`
// (which closes over `thumbs` state) under the ORIGINAL single-arg call shape.
import {
  CONNECT, CONTINUITY_PHRASE, actLetter,
  maxTagNum, nextTag, isCatalogMediaId, frameLinked, connectMeta, continuityLinked,
  flat, shotText, castMissingImages, castPastBudget, refBudget, resolvedImage,
  usesCloseFrame,
  pickTarget, pickVideoTarget, positionTag, durOf,
  reelStats, effectivePrompt,
  priceFingerprint, tallyPrices, formatCostEstimate, costTooltip, bundleMissingReport,
  shotPayload as buildShotPayload,
} from "./src/loom-core.js";
// Pure project-tree mutators + response-shape classifiers (Phase 2, composed-
// hooks extraction pass, 2026-07-16) -- same discipline as loom-core.js
// (no React, no DOM, no fetch), consumed by the useProjectStore /
// useShotMutations / useGenerationPipeline / useExportPipeline hooks below.
import {
  patchCard, patchCardById, patchAct, patchAssets,
  appendCardToAct, buildDuplicateCard, insertCardAfter, removeCard, splitCardAt,
  moveCardInAct, moveCardToAct as mvCardToAct, nextActName, appendAct, removeAct, moveActInProject,
  buildNewRef, patchRef, removeRef, countShots, setShotMode, setShotConnect,
  parseCastIdsFromSearch,
  friendlyGenErr, classifyTaskStatus,
  buildShotListText, buildPlaySequence, buildExportClips,
  setPromptOverride, clearPromptOverride,
  loraIncompat, resolveLoraPayload, anyLoraUnresolved, overLoraCap,
  landInFirstAct, importedFootagePatch, importedFramesPatch,
  // resolveGenDims was USED below (the Advanced panel's "→ W × H" readout) without ever
  // being imported. The in-browser Babel path inlines every module into one global scope,
  // so it happened to resolve there and the omission was invisible; esbuild builds a real
  // module graph, so `/loom?bundle=1` threw `ReferenceError: resolveGenDims is not defined`
  // and the whole tab body failed to render. Nothing else in this file is missing from
  // these two import lists -- checked by diffing every export against every identifier
  // called here (shotPayload/moveCardToAct look missing but are deliberate local wrappers
  // over the aliased buildShotPayload/mvCardToAct imports).
  buildImgGenBody, resolveGenDims,
} from "./src/loom-mutations.js";
// PixAI's art-filter engine (gradient/canvas compositing, offline, free). Ported out of
// static/mg-art-filters.js into the React build (2026-08-08, the vanilla static/ campaign);
// now a plain import esbuild bundles, not a window global loaded by a <script> tag. The
// Loom is bundle-only now, so this resolves the same way the gallery's FiltersPanel does.
import MgArtFilters from "../gallery/src/art/artFilters.js";
// The shared gallery-image picker modal (React component, imports its own CSS). Ported out
// of static/mg-gallery-picker.js (2026-08-08); the Loom's own GalleryPick was already
// converged onto the shared picker in an earlier pass, so this just swaps the last
// <mg-gallery-picker> web-component mount for the React component.
import GalleryPicker from "../gallery/src/components/GalleryPicker.jsx";
import ModelPicker from "../gallery/src/components/ModelPicker.jsx";

// The Loom.dc.html's own TINTS + tint formula (line ~681, ~760): 6 rotating per-shot
// gradients so same-status shots stay visually distinguishable from each other, not just
// from other statuses. `(ai*3+ci) % TINTS.length` is the design's real assignment rule --
// ai/ci already exist on every flat() entry (loom-core.js:118), so this needs no change to
// that pure-logic file, just reading fields it already provides.
const LV_TINTS = [
  "linear-gradient(150deg, #33236d 0%, #1b1733 100%)",
  "linear-gradient(150deg, #3a3460 0%, #17142b 100%)",
  "linear-gradient(150deg, #643aac 0%, #241f5b 100%)",
  "linear-gradient(150deg, #2a4a58 0%, #171f38 100%)",
  "linear-gradient(150deg, #4a3a6e 0%, #1f1a36 100%)",
  "linear-gradient(150deg, #3a2b63 0%, #191338 100%)",
];

/* =========================================================================
   THE EDIT BAY v2 — reusable Seedance 2.0 storyboard with continuity chaining
   Frame handoff (close-of-N -> open-of-N+1), connection methods, a reusable
   Cast & Assets reference library, and continuity-aware prompt assembly.
   Persists to window.storage. Self-contained.
   ========================================================================= */

const STYLES = `
:root{
  /* Loom palette now INHERITS the gallery's design tokens (moonglade_gallery.py's
     DESIGN_TOKENS_CSS, shared with BASE_HTML) instead of hardcoding its own --
     switching skin in the gallery header re-colors the Loom too. --line
     deliberately maps to --overlay0 rather than --surface1 (which --panel2
     already uses) so a --line border never vanishes against a --panel2
     background (e.g. .sb-trim-track uses both together). */
  --bg:var(--base);          --bg2:var(--mantle);
  --panel:var(--surface0);   --panel2:var(--surface1);
  --line:var(--overlay0);    --line2:color-mix(in srgb, var(--overlay0) 55%, var(--text) 45%);
  --ink:var(--text);         --ink2:var(--subtext);      --ink3:var(--overlay0);
  --amber:var(--accent);     --amber-d:color-mix(in srgb, var(--accent) 70%, black);
  --cyan:var(--emerald);     --green:var(--green);       --coral:var(--red);
  --shadow:0 10px 30px rgba(0,0,0,.45);
}
*{box-sizing:border-box}
/* System fonts only (no CDN) -- matches the gallery's own body{font-family:system-ui,
   sans-serif} exactly (moonglade_gallery.py) and its ui-monospace,monospace mono
   convention, rather than inventing a new stack. */
.sb-root{font-family:system-ui,sans-serif;background:
  radial-gradient(1200px 600px at 80% -10%,rgba(255,255,255,.05),transparent 60%),var(--bg);
  color:var(--ink);min-height:100vh;padding:0 0 80px;-webkit-font-smoothing:antialiased}
.sb-mono{font-family:ui-monospace,monospace}
.sb-projwrap{position:relative;display:inline-flex}
.sb-projbtn{background:transparent;border:1px solid var(--line);border-radius:6px;color:var(--ink3);cursor:pointer;font-size:11px;line-height:1;padding:3px 6px;margin-left:2px}
.sb-projbtn:hover{color:var(--ink);border-color:var(--line2)}
.sb-projpop{position:absolute;top:calc(100% + 6px);left:0;z-index:60;min-width:240px;max-width:320px;background:var(--panel);border:1px solid var(--line2);border-radius:10px;box-shadow:0 12px 34px rgba(0,0,0,.5);padding:8px;display:flex;flex-direction:column;gap:6px}
.sb-projpoph{font-size:10px;letter-spacing:.09em;text-transform:uppercase;color:var(--ink3);padding:2px 4px}
.sb-projlist{display:flex;flex-direction:column;gap:2px;max-height:280px;overflow:auto}
.sb-projitem{display:flex;align-items:stretch;gap:4px;border-radius:7px}
.sb-projitem.on{background:rgba(255,255,255,.06)}
.sb-projopen{flex:1 1 auto;display:flex;flex-direction:column;align-items:flex-start;gap:1px;background:transparent;border:none;cursor:pointer;text-align:left;padding:6px 8px;border-radius:7px;color:var(--ink)}
.sb-projopen:hover{background:rgba(255,255,255,.05)}
.sb-projopen b{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:210px}
.sb-projopen span{font-size:10px;color:var(--ink3)}
.sb-projitem.on .sb-projopen b{color:var(--amber)}
.sb-projx{background:transparent;border:none;color:var(--ink3);cursor:pointer;padding:0 8px;font-size:11px;border-radius:7px}
.sb-projx:hover{color:var(--coral);background:rgba(255,80,80,.12)}
.sb-projacts{display:flex;gap:6px;border-top:1px solid var(--line);padding-top:6px}
.sb-projveil{position:fixed;inset:0;z-index:59}
/* Export ▾ menu reuses .sb-projwrap/.sb-projbtn/.sb-projveil/.sb-projpop's chrome as-is --
   same popover language as the storyboard switcher it sits beside. Only the row style is new. */
.sb-exportitem{display:flex;align-items:center;gap:6px;background:transparent;border:none;cursor:pointer;text-align:left;padding:7px 8px;border-radius:7px;color:var(--ink);font-size:12px;width:100%}
.sb-exportitem:hover{background:rgba(255,255,255,.05)}
.sb-exportitem:disabled{color:var(--ink3);cursor:default;background:transparent}
.sb-exportitem small{color:var(--ink3);font-size:10px;margin-left:auto;white-space:nowrap}
.sb-exportdiv{border-top:1px solid var(--line);margin:2px 0}
.sb-toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.sb-shotprev{position:relative;margin-top:8px;border-radius:8px;overflow:hidden;
  background:#000;cursor:col-resize;max-width:460px}
.sb-shotprev video{width:100%;display:block;aspect-ratio:16/9;object-fit:contain;background:#000}
.sb-shotprev-hint{position:absolute;right:7px;bottom:6px;font-size:10.5px;color:rgba(255,255,255,.75);
  background:rgba(0,0,0,.5);border-radius:5px;padding:2px 7px;pointer-events:none;
  opacity:0;transition:opacity .15s}
.sb-shotprev:hover .sb-shotprev-hint{opacity:1}
.sb-shotprev-play{position:absolute;left:7px;bottom:6px;font-size:12px;line-height:1;color:#fff;
  background:rgba(0,0,0,.55);border:1px solid rgba(255,255,255,.25);border-radius:5px;padding:4px 7px;
  cursor:pointer;}
.sb-shotprev-play:hover{background:rgba(0,0,0,.75);border-color:var(--amber);}
.sb-shotprev-wrap{margin:8px auto 0;max-width:460px}
.sb-shotprev-ctrls{display:flex;gap:5px;margin-top:6px;flex-wrap:wrap}
.sb-shotprev-ctrls button{font:600 11px/1 system-ui;color:var(--ink2);background:var(--panel2);
  border:1px solid var(--line);border-radius:6px;padding:5px 8px;cursor:pointer}
.sb-shotprev-ctrls button:hover{border-color:var(--amber);color:var(--ink)}
.sb-shotprev-ctrls button.on{background:var(--amber);color:#1a1206;border-color:var(--amber)}
.sb-crop-rect{position:absolute;border:2px solid var(--amber);box-shadow:0 0 0 9999px rgba(0,0,0,.45);
  pointer-events:none;z-index:2}
.sb-crop-layer{position:absolute;inset:0;z-index:3;cursor:crosshair;touch-action:none;
  display:flex;align-items:center;justify-content:center;font:600 11px/1 system-ui;
  color:rgba(255,255,255,.85);background:rgba(0,0,0,.15)}
.sb-trim{margin-top:6px}
.sb-trim-track{position:relative;height:20px;background:var(--panel2);border:1px solid var(--line);border-radius:6px;cursor:pointer;touch-action:none}
.sb-trim-sel{position:absolute;top:0;bottom:0;background:rgba(224,162,78,.26);border-left:2px solid var(--amber);border-right:2px solid var(--amber)}
.sb-trim-h{position:absolute;top:-3px;width:11px;height:26px;margin-left:-6px;border-radius:4px;background:var(--amber);cursor:ew-resize;box-shadow:0 1px 4px rgba(0,0,0,.55);touch-action:none;z-index:2}
.sb-trim-h:hover{background:var(--gold)}
.sb-trim-read{font-size:11px;color:var(--ink2);margin-top:6px;font-family:ui-monospace,monospace}
.sb-trim-read b{color:var(--amber)}
.sb-trim-reset{margin-left:9px;background:none;border:1px solid var(--line);color:var(--ink2);border-radius:5px;font-size:10px;padding:1px 8px;cursor:pointer}
.sb-trim-reset:hover{border-color:var(--amber);color:var(--amber)}
.sb-seq{position:fixed;inset:0;z-index:500;background:rgba(4,3,10,.92);display:flex;align-items:center;justify-content:center;padding:22px}
.sb-seq-box{max-width:1120px;width:100%;display:flex;flex-direction:column;gap:11px}
.sb-seq video{width:100%;max-height:78vh;background:#000;border-radius:11px;display:block;cursor:pointer}
.sb-seq-bar{display:flex;align-items:center;gap:9px;color:var(--ink);font-size:13px}
.sb-seq-bar span{flex:1;font-family:ui-monospace,monospace;color:var(--ink2)}
.sb-export-box{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:20px 22px;width:420px;max-width:92vw;display:flex;flex-direction:column;gap:13px}
.sb-exp-bar{height:9px;background:var(--panel2);border:1px solid var(--line);border-radius:999px;overflow:hidden}
.sb-exp-bar i{display:block;height:100%;background:linear-gradient(90deg,var(--amber),var(--gold));transition:width .3s}
.sb-exp-txt{font-size:13px;color:var(--ink);text-align:center;font-family:ui-monospace,monospace}
.sb-miss-list{max-height:44vh;overflow-y:auto;display:flex;flex-direction:column;gap:8px;border:1px solid var(--line);border-radius:8px;padding:10px 12px;background:var(--panel2)}
.sb-miss-row{display:flex;flex-direction:column;gap:2px;font-size:12px;color:var(--ink)}
.sb-miss-row i{color:var(--ink2);font-style:normal}
.sb-miss-id{font-family:ui-monospace,monospace;font-size:11px;color:var(--ink2);word-break:break-all}
/* 500, not 400: ImportCollection opens ON TOP of the V2 shell, and .lv-overlay is also 400 --
   at a tie it only stayed above because it happens to render later in App's child order.
   500 clears both that and Deep Focus's .lv-df-veil (450) outright. */
.sb-pick-ov{position:fixed;inset:0;z-index:500;background:rgba(6,4,16,.76);display:flex;align-items:center;justify-content:center;padding:20px}
.sb-pick-box{width:920px;max-width:94vw;height:82vh;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px;display:flex;flex-direction:column;gap:9px}
.sb-pick-head{display:flex;align-items:center;gap:9px}
.sb-pick-t{font-size:15px;font-weight:700;white-space:nowrap}
.sb-pick-x{background:none;border:none;color:var(--ink2);font-size:24px;line-height:1;cursor:pointer;padding:0 4px}
.sb-pick-x:hover{color:var(--ink)}
.sb-pick-filters{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.sb-pick-filters select{background:var(--panel2);border:1px solid var(--line);border-radius:6px;color:var(--ink);padding:5px 9px;font-size:12px;cursor:pointer;max-width:210px}
.sb-pick-cell{position:relative;border-radius:8px;overflow:hidden;border:1px solid var(--line);cursor:pointer;background:var(--panel2)}
.sb-pick-cell:hover{border-color:var(--amber)}
.sb-pick-cell img{width:100%;height:100%;object-fit:cover;display:block}
.sb-tick{width:22px;height:22px;border-radius:6px;border:1.5px solid var(--line2);background:transparent;
  cursor:pointer;flex:none;display:grid;place-items:center;color:transparent;transition:all .12s;padding:0}
.sb-tick.wip{border-color:var(--amber);color:var(--amber)}
.sb-tick.done{border-color:var(--green);background:var(--green);color:var(--base)}
.sb-tick.error{border-color:var(--coral);color:var(--coral)}
.sb-field{display:flex;flex-direction:column;gap:5px;flex:1 1 200px;min-width:0}
.sb-lab{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink3);font-weight:600;display:flex;align-items:center;gap:6px}
.sb-in,.sb-ta,.sb-sel{background:var(--bg2);border:1px solid var(--line2);border-radius:7px;color:var(--ink);
  font:inherit;font-size:13px;padding:8px 10px;width:100%}
.sb-ta{resize:vertical;min-height:74px;line-height:1.55}.sb-ta.big{min-height:104px}
.sb-in:focus,.sb-ta:focus,.sb-sel:focus{outline:none;border-color:var(--amber)}
.sb-hint{font-size:10.5px;color:var(--ink3)}
.sb-conn-mid{flex:0 0 auto;align-self:center;color:var(--amber);font-size:20px;padding-top:10px}
.sb-frame{display:flex;flex-direction:column;gap:6px}
.sb-framehead{display:flex;align-items:center;justify-content:space-between;gap:6px}
.sb-frameprev{height:84px;border-radius:7px;border:1px solid var(--line2);background:var(--panel2);overflow:hidden;
  display:grid;place-items:center;color:var(--ink3);font-size:11px;cursor:pointer;position:relative}
.sb-frameprev img{width:100%;height:100%;object-fit:cover}
.sb-frameprev.discreet img{filter:blur(9px)}
.sb-tagin{font-family:ui-monospace,monospace;font-size:11px;color:var(--cyan);background:var(--base);
  border:1px solid var(--line2);border-radius:5px;padding:3px 6px;width:90px}
.sb-pal{display:flex;flex-wrap:wrap;gap:5px;margin-top:4px}
.sb-pchip{font-family:ui-monospace,monospace;font-size:10.5px;color:var(--ink2);background:var(--bg2);
  border:1px solid var(--line);border-radius:5px;padding:3px 7px;cursor:pointer;transition:all .1s}
.sb-pchip:hover{border-color:var(--amber);color:var(--amber)}
.sb-ref{background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:10px;display:flex;gap:10px;align-items:flex-start}
.sb-refprev{width:64px;height:48px;border-radius:6px;border:1px solid var(--line2);background:var(--panel2);
  flex:none;display:grid;place-items:center;font-size:18px;cursor:pointer;overflow:hidden}
.sb-refprev img{width:100%;height:100%;object-fit:cover}.sb-refprev.discreet img{filter:blur(8px)}
.sb-refbody{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:6px}
.sb-btn{font:inherit;font-size:12.5px;font-weight:500;border-radius:7px;padding:7px 12px;cursor:pointer;
  border:1px solid var(--line2);background:var(--panel2);color:var(--ink);transition:all .12s;display:inline-flex;align-items:center;gap:6px}
.sb-btn:hover{border-color:var(--amber);color:var(--amber)}
.sb-btn.amber{background:var(--amber);color:var(--base);border-color:var(--amber);font-weight:600}
.sb-btn.amber:hover{filter:brightness(1.08);color:var(--base)}
.sb-btn.ghost{background:transparent}.sb-btn.sm{font-size:11px;padding:5px 9px}
.sb-btn.danger:hover{border-color:var(--coral);color:var(--coral)}
.sb-ico{background:transparent;border:none;color:var(--ink3);cursor:pointer;padding:5px;border-radius:6px;font-size:14px;line-height:1;transition:all .12s}
.sb-ico:hover{color:var(--ink);background:var(--panel2)}
.sb-toggle{display:inline-flex;align-items:center;gap:7px;font-size:12px;color:var(--ink2);cursor:pointer}
.sb-empty{text-align:center;color:var(--ink3);padding:30px;font-size:13px}
@media (max-width:560px){.sb-conn-mid{align-self:flex-start;padding:0}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
:focus-visible{outline:2px solid var(--amber);outline-offset:2px}
`;

const MODES = ["I2V", "R2V", "V2V", "FLF"];   // T2V retired: these video models need an input frame/ref
// PixAI's real audio-language enum (private/GENERATOR_SURFACE.md, VIDEO_MODELS.md) --
const MODE_HINT = {
  I2V: "Image-to-video — ref is first frame; prompt only motion",
  R2V: "Reference-to-video — lock identity/style/motion via @tags",
  V2V: "Video edit / extend an existing clip",
  FLF: "First & last frame — interpolate between two images",
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
const LIGHTING_PALETTE = ["golden hour", "blue hour", "low-key", "high-key", "warm haze", "cool moonlight",
  "candlelit", "firelight", "neon glow", "backlit / rim light", "soft diffused", "hard shadows",
  "chiaroscuro", "volumetric god rays", "overcast", "silhouette"];
const AUDIO_PALETTE = ["no music", "room tone", "ambient hum", "soft breathing", "whispered dialogue",
  "distant music", "rain", "heartbeat", "beat sync", "diegetic only", "muffled", "rustling fabric"];

// Fix (face/hand touch-up repair) constants -- ported VERBATIM from the real, already-shipped
// gallery/src/gen/editCore.js's FIX_COLORS/FIX_MIN_PX/FIX_MAX_BOXES/scaleBoxes, which
// gallery/src/components/FixTab.jsx's own real box-drawing canvas already uses (Loom Mobile's
// own Fixer sub-screen, built 2026-08-03, ports that exact real technique -- see LoomMobile's
// own Fixer comment for the full trace). Deliberately a LOCAL COPY, not a cross-directory
// `import ... from "../gallery/src/gen/editCore.js"`: it stays a small, verbatim LOCAL copy.
// (The Loom went BUNDLE-ONLY on 2026-08-08, so the old hard reason -- the retired
// Babel-standalone /loom path could only inline ./src/loom-core.js and ./src/loom-mutations.js
// and would choke on a third raw import -- is gone; esbuild now resolves real cross-directory
// imports, which is exactly how the art-filter engine above is pulled from
// ../gallery/src/art/artFilters.js. Converging these Fixer constants the same way is future
// vanilla-campaign work; until then the local copy stays, same as modeSendsRefs/liveTagText
// etc. keep their own copies for values outside this file's two DO-NOT-MODIFY pure modules.)
const FIX_COLORS = { face: "#b692e6", hand: "#4fc99a" };
const FIX_MIN_PX = 6;
const FIX_MAX_BOXES = 20;   // clean_fix_boxes truncates at 20 server-side
// boxes arrive as {x,y,w,h,tag} in DISPLAY pixels (the canvas's own coordinate space); the
// wire wants {x,y,width,height,tag} in ORIGINAL-image pixels. Scale comes from the rendered
// <img> -- naturalWidth/clientWidth -- exactly like editCore.js's scaleBoxes; the server does
// NOT rescale, so getting this wrong repairs the wrong part of the picture.
const scaleFixBoxes = (boxes, imgEl) => {
  const scale = imgEl && imgEl.clientWidth ? (imgEl.naturalWidth / imgEl.clientWidth) : 1;
  return boxes.map((b) => ({
    x: Math.round(b.x * scale), y: Math.round(b.y * scale),
    width: Math.round(b.w * scale), height: Math.round(b.h * scale), tag: b.tag,
  }));
};

const uid = () => Math.random().toString(36).slice(2, 9);
const fmt = (s) => { s = Math.max(0, Math.round(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
// Module scope (not a local inside useGenerationPipeline) because both pollShot (inside that
// hook) and onVideoSlow/onVideoPaused (inside App(), a different function entirely) need it.
const elapsedLabel = (ms) => ms < 3600000 ? Math.round(ms / 60000) + "m" : (Math.round(ms / 360000) / 10) + "h";
const emptyFrame = () => ({ thumbId: "", source: "", desc: "", tag: "" });
// A durable, manual owner-preference toggle backed by localStorage -- NOT window.storage
// (the sGet/sSet/sList/sDel family above, which is the async, server-backed project store):
// this is a per-browser UI-chrome preference (which SKIN of the Loom to show), not project
// data, so it has no business round-tripping through the server or living in a storyboard's
// own JSON. There is no existing hook in this file for that -- the main gallery only ever
// auto-detects viewport width for its own mobile layout, it never persists a manual override
// -- so this is a small, real, new one (used by App()'s "📱 Mobile view" switch), not a
// borrowed one. Reads localStorage exactly once, in the lazy useState initializer, and
// writes it back only when the value actually changes.
function useLocalToggle(key, defaultVal) {
  const [val, setVal] = useState(() => {
    try { const raw = window.localStorage.getItem(key); return raw === null ? defaultVal : raw === "1"; }
    catch (e) { return defaultVal; }
  });
  useEffect(() => {
    try { window.localStorage.setItem(key, val ? "1" : "0"); } catch (e) {}
  }, [key, val]);
  return [val, setVal];
}
const MOBILE_UI_KEY = "mg_loom_mobile_ui";   // "📱 Mobile view" toggle -- see useLocalToggle above
// CONNECT, CONTINUITY_PHRASE, actLetter, maxTagNum/nextTag, frameLinked, and
// connectMeta now live in ./src/loom-core.js (imported above) -- Phase 1
// tooling pass, 2026-07-16. continuityLinked (same module) added 2026-07-23 to
// give frameLinked a real caller -- see its use in the board card below.

/* ---------- storage ---------- */
const hasStore = typeof window !== "undefined" && window.storage;
const PKEY = "storyboard:v2:project";        // legacy single-project key — migrated into PPRE on first load
const PPRE = "storyboard:v2:proj:";          // one KV key per saved storyboard: PPRE + id
const ACTIVE_KEY = "storyboard:v2:active";   // id of the storyboard currently open
const TPRE = "storyboard:v2:thumb:";
// Every one of these used to swallow its error and answer as though nothing had gone wrong:
// sGet returned null for BOTH "no such key" and "the read failed", sList returned [] for
// both "nothing stored" and "the listing failed", and sSet/sDel reported success after a
// failed write. That is not a small thing here -- storyboards ARE this storage. A delete
// guarded on `if (!p)` could not tell a hiccup from an empty board, and a save that never
// landed looked identical to one that did.
// They still never THROW -- every caller is written around a soft answer, and turning that
// into an exception mid-autosave would be its own bug -- but a real failure is now recorded
// and surfaced once, so it stops being invisible. sGet additionally reports whether the read
// itself failed, which is the distinction the delete path actually needs.
let _storeWarned = false;
function storeFailed(op, k, e) {
  console.error("storage " + op + " failed for " + k, e);
  // One banner per session: a flapping backend would otherwise stack a toast per autosave.
  if (!_storeWarned && typeof window !== "undefined" && window.Toast) {
    _storeWarned = true;
    window.Toast.show({ kind: "err", sticky: true, title: "Storyboard storage is failing",
      msg: "Your recent changes may not be saved. Check the server, then reload before editing further." });
  }
}
async function sGetX(k) {
  try { const r = await window.storage.get(k); return { value: r ? r.value : null, failed: false }; }
  catch (e) { storeFailed("read", k, e); return { value: null, failed: true }; }
}
async function sGet(k) { return (await sGetX(k)).value; }
async function sSet(k, v) { try { await window.storage.set(k, v, false); return true; } catch (e) { storeFailed("write", k, e); return false; } }
async function sList(p) { try { const r = await window.storage.list(p, false); if (!r) return []; return (r.keys || []).map((k) => (typeof k === "string" ? k : k.key)); } catch (e) { storeFailed("list", p, e); return []; } }
async function sDel(k) { try { await window.storage.delete(k); return true; } catch (e) { storeFailed("delete", k, e); return false; } }

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
    // audioGen/audioLanguage are the actual generation request (does PixAI render sound at
    // all, and in what language) -- distinct from audioCue above, which is prompt TEXT
    // ("ambient room tone") that only ever influences wording, never the real generateAudio/
    // audioLanguage params. Neither surface exposed this until now (private/GENERATOR_SURFACE.md
    // had it reverse-engineered but never wired to a control): the server already accepts
    // generate_audio/audio_language on /api/loom/generate, this was purely a missing control.
    audioGen: false, audioLanguage: "english",
    transIn: "", transOut: "", notes: "", discreet: false, trimIn: 0, trimOut: null,
    // promptOverride/promptOverrideText: a hand-edit made directly in the drawer's composed-
    // prompt box, durable across shot reselect/reload. When set, shotText() returns
    // promptOverrideText verbatim instead of composing from camera/lighting/cast/etc --
    // see loom-core.js's shotText() and effectivePrompt().
    promptOverride: false, promptOverrideText: "",
    ...extra,
  };
}
function seedProject() {
  return {
    name: "Untitled storyboard", target: 480, look: "", draft: false,
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
// ─── Loom V2 — a fixed 4-region shell (left Cast&Assets/Footage, center board, right
// Generate, top Timeline drawer), replacing the old free-floating dockable-panel system.
const V2_STYLES = `
.lv-overlay{position:fixed;inset:0;z-index:400;background:var(--base);display:flex;flex-direction:column;}
/* While Deep Focus is open, lift the WHOLE overlay's root-context z-index to .lv-df-veil's
   own intended 450 (see the 2026-07-21 audit comment above the .lv-overlay mount) so
   the body-level corner FABs -- #jobs-fab/#jobs-tray at 401/402 -- stop painting over Deep
   Focus and its nested flyouts, which are otherwise contained inside .lv-overlay's own
   stacking context and can never out-rank a root-level sibling on their own. */
.lv-overlay.lv-overlay-df{z-index:450;}
/* The Loom.dc.html:36-45's hero banner -- radial-gradient art layer + hide/show toggle. */
.lv-banner{position:relative;width:100%;height:160px;overflow:hidden;background:var(--base);
  flex:none;border-bottom:1px solid var(--surface1);}
.lv-banner-art{position:absolute;inset:0;
  background:radial-gradient(120% 140% at 18% 0%, color-mix(in oklab, var(--accent) 26%, #0b0820) 0%, #0b0820 62%, #070512 100%);}
.lv-banner-img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;}
.lv-banner-hide{position:absolute;top:10px;right:12px;font-size:10px;font-weight:700;letter-spacing:.04em;
  color:#fff;background:rgba(6,4,14,.55);backdrop-filter:blur(6px);border:1px solid rgba(255,255,255,.25);
  border-radius:999px;padding:5px 11px;cursor:pointer;font-family:inherit;}
.lv-banner-show{font-size:10.5px;font-weight:700;letter-spacing:.04em;color:var(--subtext);
  background:var(--surface1);border:1px solid var(--surface1);border-radius:7px;padding:7px 11px;
  cursor:pointer;white-space:nowrap;font-family:inherit;}
.lv-top{display:flex;align-items:center;gap:12px;padding:10px 16px;border-bottom:1px solid var(--surface1);background:var(--surface0);}
.lv-eyebrow{font:700 11px/1 system-ui,sans-serif;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);}
.lv-note{color:var(--subtext);font-size:12px;}
/* The trailing "a" in this selector is deliberate: the back-to-gallery control is an
   anchor, not a button, so a button-only selector left it as an unstyled browser link --
   rgb(0,0,238) on the dark bar, a measured 1.69:1 against a 4.5:1 floor, and the only way
   out of the Loom. Found by a browser crawl; invisible to any DOM/network check because
   the link works perfectly, it is just illegible.
   NB: this whole block is a JS template literal -- no backticks in these comments. */
.lv-top button,.lv-top label,.lv-top a{background:var(--surface1);border:1px solid var(--surface1);color:var(--text);border-radius:8px;padding:7px 13px;font:600 12px/1 system-ui;cursor:pointer;}
.lv-top a{text-decoration:none;display:inline-block;}
.lv-top a:hover{border-color:var(--accent);}
.lv-top .lv-close{margin-left:auto;}
.lv-top button:hover{border-color:var(--accent);}
.lv-top button:disabled{opacity:.5;cursor:default;}
.lv-top button:disabled:hover{border-color:var(--surface1);}
.lv-cost-pill{opacity:.85;font-weight:600;}
.lv-cost-pill:disabled{opacity:.5;}
.lv-batchbar{padding:6px 20px;font-size:12px;color:var(--subtext);background:var(--surface0);border-bottom:1px solid var(--surface1);}
.lv-batchfail{color:var(--coral);font-weight:600;}
.lv-batchstale{color:var(--subtext);font-weight:600;}
.lv-override-badge{color:var(--amber);font-style:normal;font-weight:600;}
.lv-overrideflash{font-size:11px;color:var(--amber);background:rgba(0,0,0,.15);border-radius:5px;padding:3px 7px;margin-top:2px;animation:lv-flash-fade 1.6s ease-out forwards;}
@keyframes lv-flash-fade{0%{opacity:1;}70%{opacity:1;}100%{opacity:0;}}
/* Board fills the shell's full width always; Cast/Generate float over it as glass
   panels (The Loom.dc.html's leftPanelStyle/rightPanelStyle/leftBackdropStyle),
   collapsing to a permanent 58px icon rail -- not the old 3-column flex share
   this replaced (2026-08-04 structural-fidelity fix, see docs/DECISIONS.md).
   .lv-shell is position:relative so the floating panel + backdrop below
   resolve their position:absolute against the WHOLE shell (board + rails),
   exactly like the design's own equivalent wrapper. */
.lv-shell{flex:1;display:flex;min-height:0;overflow:hidden;position:relative;}
.lv-rail{flex:none;width:58px;box-sizing:border-box;display:flex;flex-direction:column;
  align-items:center;gap:7px;padding:10px 0;margin:10px 4px;border-radius:14px;
  border:1px solid rgba(182,146,230,.32);
  background:linear-gradient(120deg,rgba(24,18,54,.92) 0%,rgba(14,11,32,.95) 100%);
  backdrop-filter:blur(18px) saturate(1.12);
  box-shadow:0 24px 60px rgba(0,0,0,.55),0 0 34px rgba(182,146,230,.14);}
.lv-boardcol{flex:1;min-width:0;overflow:auto;background:var(--base);}

.lv-backdrop{position:absolute;inset:0;z-index:40;background:rgba(5,4,13,.62);
  backdrop-filter:blur(7px);animation:lvFadeIn .32s ease both;}
.lv-backdrop.closing{animation:lvFadeOut .34s ease both;}
.lv-panel{position:absolute;top:20px;bottom:20px;z-index:41;box-sizing:border-box;
  display:flex;flex-direction:column;min-height:0;border-radius:16px;
  border:1px solid rgba(182,146,230,.32);
  background:linear-gradient(120deg,rgba(24,18,54,.92) 0%,rgba(14,11,32,.95) 100%);
  backdrop-filter:blur(18px) saturate(1.12);
  box-shadow:0 24px 60px rgba(0,0,0,.55),0 0 34px rgba(182,146,230,.14);overflow:hidden;}
.lv-panel.left{left:20px;width:clamp(220px,21vw,292px);
  animation:lvSlideL .4s cubic-bezier(.18,1.02,.26,1) both;}
.lv-panel.left.wide{width:min(572px,37vw);}
.lv-panel.left.closing{animation:lvSlideOutL .34s cubic-bezier(.4,0,.2,1) both;}
.lv-panel.right{right:20px;width:clamp(332px,35vw,572px);
  animation:lvSlideR .4s cubic-bezier(.18,1.02,.26,1) both;}
.lv-panel.right.closing{animation:lvSlideOutR .34s cubic-bezier(.4,0,.2,1) both;}
@keyframes lvFadeIn{from{opacity:0;}to{opacity:1;}}
@keyframes lvFadeOut{from{opacity:1;}to{opacity:0;}}
@keyframes lvSlideL{from{opacity:0;transform:translateX(-34px) scale(.985);}60%{opacity:1;}to{opacity:1;transform:none;}}
@keyframes lvSlideOutL{from{opacity:1;transform:none;}to{opacity:0;transform:translateX(-34px) scale(.985);}}
@keyframes lvSlideR{from{opacity:0;transform:translateX(34px) scale(.985);}60%{opacity:1;}to{opacity:1;transform:none;}}
@keyframes lvSlideOutR{from{opacity:1;transform:none;}to{opacity:0;transform:translateX(34px) scale(.985);}}

.lv-sidehead{flex:none;display:flex;align-items:center;gap:8px;padding:8px;border-bottom:1px solid var(--surface1);}
.lv-sidetabs{flex:1;min-width:0;margin-bottom:0;}
.lv-col{width:22px;height:20px;border:1px solid var(--surface1);background:var(--base);color:var(--subtext);
  border-radius:5px;cursor:pointer;font-size:11px;flex:0 0 auto;}
.lv-col:hover{color:var(--accent);}
.lv-railbtn{width:38px;height:38px;border:1px solid var(--surface1);background:var(--base);color:var(--subtext);
  border-radius:8px;cursor:pointer;font-size:17px;line-height:1;flex:0 0 auto;}
.lv-railbtn:hover{border-color:var(--accent);color:var(--accent);}
.lv-railbtn.on{border-color:var(--accent);color:var(--accent);background:color-mix(in srgb,var(--accent) 14%,var(--base));}
/* Timeline: genuinely fixed to the banner, full width, never draggable -- unlike every
   other region. Three states (hidden/slim/full) driven by tlState + a live drag height;
   the preview sits ABOVE the scrubber, only rendered once mostly expanded. */
.lv-tldrawer{flex:none;position:relative;background:var(--surface0);border-bottom:1px solid var(--surface1);}
.lv-tlcontent{overflow:hidden;position:relative;}
.lv-tlpreviewzone{padding:10px 14px 4px;height:362px;box-sizing:border-box;}
.lv-tlpreviewbox{height:100%;border-radius:8px;background:var(--base);border:1px solid var(--surface1);
  display:flex;align-items:center;justify-content:center;text-align:center;}
.lv-tlreelzone{padding:8px 14px 10px;}
.lv-tlhandle{position:absolute;left:50%;bottom:-1px;transform:translateX(-50%);z-index:2;
  display:flex;align-items:center;justify-content:center;padding:5px 22px;cursor:ns-resize;touch-action:none;}
.lv-tlgrip{width:40px;height:4px;border-radius:3px;background:var(--surface1);transition:background .15s;}
.lv-tlhandle:hover .lv-tlgrip{background:var(--accent);}
.lv-ph{padding:14px;color:var(--subtext);font:12.5px/1.5 system-ui,sans-serif;font-style:italic;}
.lv-board{padding:8px;}
.lv-act{margin-bottom:12px;}
.lv-actrow{display:flex;align-items:center;gap:4px;margin:2px 0 7px;}
.lv-actname-in{flex:1;min-width:0;background:transparent;border:none;border-bottom:1px dashed var(--surface1);
  color:var(--accent);font:700 10px/1 system-ui;text-transform:uppercase;letter-spacing:.06em;padding:2px 0;}
.lv-actname-in:focus{outline:none;border-bottom-color:var(--accent);}
.lv-ico{width:19px;height:17px;border:1px solid var(--surface1);background:var(--base);color:var(--subtext);
  border-radius:4px;cursor:pointer;font-size:10px;line-height:1;flex:0 0 auto;}
.lv-ico:hover{color:var(--accent);border-color:var(--accent);}
.lv-ico.danger:hover{color:var(--coral,#e06c75);border-color:var(--coral,#e06c75);}
.lv-ico.xs{width:16px;height:15px;font-size:9px;}
.lv-crow{display:flex;flex-wrap:wrap;gap:3px;margin-top:5px;}
.lv-actsel{font-size:8px;background:var(--base);border:1px solid var(--surface1);color:var(--subtext);
  border-radius:4px;padding:1px 3px;cursor:pointer;max-width:100%;}
/* Owner 2026-07-26: the compact shot cards on the main screen are too small; the Deep
   Focus cards were already right. 122px was tight. Because the grid is auto-fill,
   raising the minimum reflows on its own -- fewer, larger cards per row -- so this is a
   single value rather than a layout change. */
.lv-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(158px,1fr));gap:8px;}
.lv-card{background:var(--surface1);border:1px solid var(--surface1);border-radius:8px;padding:7px;cursor:pointer;}
.lv-card:hover{border-color:var(--accent);}
.lv-card.sel{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset;}
.lv-code{font:700 9px/1 system-ui;color:var(--subtext);}
.lv-ctitle{font:600 11px/1.2 system-ui;color:var(--text);margin:4px 0;min-height:26px;}
.lv-cmeta{display:flex;gap:5px;align-items:center;flex-wrap:wrap;}
.lv-mode{font:700 8px/1 system-ui;color:var(--accent);}
.lv-dur{font-size:9px;color:var(--subtext);}
.lv-st{font:700 8px/1 system-ui;text-transform:uppercase;padding:2px 5px;border-radius:4px;margin-left:auto;}
.lv-st.done{color:var(--green);background:color-mix(in srgb,var(--green) 16%,transparent);}
.lv-st.wip{color:var(--amber);background:color-mix(in srgb,var(--amber) 16%,transparent);}
.lv-st.todo{color:var(--subtext);background:var(--base);}
.lv-st.paused{color:var(--subtext);background:var(--base);border:1px dashed var(--subtext);}
/* Continuity indicator (frameLinked/continuityLinked) -- reuses the .lv-st badge's own
   font/padding/border-radius, just a distinct color (--cyan, not --green) so it never reads
   as "shot generation status" and margin-left:0 so it sits with mode/duration on the left
   instead of racing .lv-st's own margin-left:auto for the row's one right-aligned slot. */
.lv-st.linked{margin-left:0;color:var(--cyan);background:color-mix(in srgb,var(--cyan) 16%,transparent);}
/* A shot cast someone it has no picture for: they are left out of the prompt (citing an
   @imageN with nothing behind it is worse than saying nothing), so the card has to say so. */
.lv-st.warn{margin-left:0;color:var(--peach);background:color-mix(in srgb,var(--peach) 16%,transparent);}
/* A cast member whose picture is fine but lost PixAI's 6-slot contest (frames first) --
   castPastBudget in loom-core.js. Quieter than .warn on purpose: nothing is broken, the
   shot is simply over budget, so this reads informational (dashed outline, subtext) rather
   than fix-me peach. */
.lv-st.oob{margin-left:0;color:var(--subtext);background:var(--base);border:1px dashed var(--overlay0);}
/* Imported-footage provenance badge -- coexists with the real status pill the same way
   .linked does (margin-left:0, not competing for the row's one auto-margined slot).
   Neutral/informational, not a warning -- reuses .todo's own subtext-on-base treatment
   rather than inventing a new color. */
.lv-st.imported{margin-left:0;color:var(--subtext);background:var(--base);}
.lv-reel{position:relative;flex:1;min-height:40px;display:flex;background:var(--base);border:1px solid var(--surface1);border-radius:7px;overflow:hidden;}
.lv-seg{position:relative;min-width:3px;border-right:1px solid rgba(0,0,0,.35);cursor:pointer;
  display:flex;align-items:flex-end;padding:4px 6px;box-sizing:border-box;overflow:hidden;}
.lv-seg.sel{outline:2px solid var(--accent);outline-offset:-2px;z-index:2;}
.lv-segcode{font-size:9px;font-weight:700;color:rgba(6,4,14,.55);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;pointer-events:none;}
.lv-segbar{position:absolute;left:0;right:0;bottom:0;height:4px;}
.lv-segbar.todo{background:rgba(255,255,255,.25);}
.lv-segbar.wip{background:#f2c14a;}
.lv-segbar.done{background:var(--green,#4fc99a);}
.lv-segbar.error{background:var(--coral,#f38ba8);}
.lv-target{position:absolute;top:0;bottom:0;width:2px;background:var(--accent);opacity:.7;}
.lv-tlinfo{font-size:11px;color:var(--text);}
.lv-dim{color:var(--subtext);font-style:italic;}
.lv-gen{flex:1;min-height:0;overflow-y:auto;padding:10px;}
.lv-genhead{font:700 13px/1.2 system-ui;color:var(--text);margin-bottom:6px;display:flex;align-items:center;gap:8px;}
.lv-unbind{margin-left:auto;flex:none;font:600 10px/1 system-ui;background:var(--surface1);border:1px solid var(--surface1);
  color:var(--subtext);border-radius:6px;padding:4px 8px;cursor:pointer;}
.lv-unbind:hover{border-color:var(--accent);color:var(--accent);}
.lv-fhlabel{font-size:9.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--overlay0);margin-bottom:6px;}
.lv-framehandoff{display:flex;gap:8px;align-items:flex-start;margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid var(--surface1);}
.lv-framehandoff .sb-frame{flex:1 1 0;min-width:0;}
/* The @tag input (.sb-tagin) is 90px in classic Loom's own wide layout -- too wide for
   a frame-slot header squeezed into this narrower drawer, which is what actually caused
   the side-scroll. Narrower here only; classic Loom keeps its own room to spare. */
.lv-framehandoff .sb-framehead{flex-wrap:nowrap;}
.lv-framehandoff .sb-tagin{width:62px;}
.lv-framehandoff .sb-frameprev{height:64px;}
.lv-lab{font:700 9px/1 system-ui;text-transform:uppercase;letter-spacing:.05em;color:var(--subtext);display:block;margin:9px 0 5px;}
.lv-chips{display:flex;gap:5px;flex-wrap:wrap;}
.lv-chip{background:var(--surface1);border:1px solid var(--surface1);color:var(--subtext);border-radius:6px;padding:3px 9px;font:600 10px/1 system-ui;cursor:pointer;}
.lv-chip.on{background:color-mix(in srgb,var(--accent) 18%,transparent);border-color:var(--accent);color:var(--accent);}
.lv-ta{width:100%;background:var(--base);border:1px solid var(--surface1);border-radius:7px;padding:8px;color:var(--text);font:11px/1.4 system-ui;resize:vertical;min-height:60px;}
.lv-ta:focus{outline:0;border-color:var(--accent);}
.lv-go{width:100%;margin-top:11px;background:var(--accent);color:var(--base);border:0;border-radius:8px;padding:9px;font:700 12px/1 system-ui;cursor:pointer;}
.lv-go:disabled{opacity:.6;cursor:default;}
.lv-usevid{width:100%;margin-top:7px;background:transparent;color:var(--subtext);border:1px solid var(--surface1);border-radius:8px;padding:7px;font:600 11px/1 system-ui;cursor:pointer;}
.lv-usevid:hover{border-color:var(--accent);color:var(--accent);}
.lv-usevid:disabled{opacity:.5;cursor:default;}
/* 80px, not 48px: the frame is object-fit:cover inside a card whose content width is 144px at
   the narrowest column (.lv-cards minmax(158px) minus .lv-card's 7px padding either side). A
   16:9 frame wants 81px at that width and a 2048x1072 clip wants 75px, so a 48px box was
   cropping ~40% of the height away and showing a middle band -- the frame was there, you just
   could not see it. 80px covers both without letterboxing. Portrait frames still crop (cover
   is deliberate; contain would leave wide empty bars on the common case). */
.lv-cframe{height:80px;border-radius:5px;overflow:hidden;background:var(--base);border:1px solid var(--surface1);display:flex;align-items:center;justify-content:center;margin-bottom:5px;}
.lv-cframe img{width:100%;height:100%;object-fit:cover;}
.lv-cframeph{font:700 9px/1 system-ui;color:var(--subtext);}
.lv-cast{flex:1;min-height:0;overflow-y:auto;padding:8px;}
.lv-castrow-h{font:700 10px/1 system-ui;text-transform:uppercase;letter-spacing:.05em;color:var(--subtext);margin-bottom:8px;}
.lv-draft{display:inline-flex;align-items:center;gap:4px;font:600 11px/1 system-ui;color:var(--subtext);cursor:pointer;padding:5px 8px;border-radius:7px;border:1px solid var(--surface1);user-select:none;}
.lv-draft.on{color:var(--accent);border-color:var(--accent);}
.lv-draft input{margin:0;cursor:pointer;}
.lv-look{margin-bottom:10px;border:1px solid var(--surface1);border-radius:8px;padding:6px 8px;background:var(--surface0);}
.lv-look>summary{font:600 11px/1.3 system-ui;color:var(--text);cursor:pointer;list-style:none;user-select:none;}
.lv-look>summary::-webkit-details-marker{display:none;}
.lv-lookin{width:100%;margin-top:6px;box-sizing:border-box;resize:vertical;font:12px/1.4 system-ui;color:var(--text);background:var(--surface1);border:1px solid var(--surface1);border-radius:6px;padding:6px;}
.lv-castph{width:34px;height:34px;border-radius:6px;background:var(--surface1);flex:0 0 auto;}
/* Detailed Cast & Assets row -- genuinely editable (name/tag/kind/lock), matching V1's
   original sb-assetrow, not just a relabeled copy of the Simple glance card. */
.lv-assetrow{display:flex;gap:7px;align-items:center;flex-wrap:wrap;background:var(--base);
  border:1px solid var(--surface1);border-radius:9px;padding:7px;margin-bottom:6px;}
.lv-assetprev{width:38px;height:32px;border-radius:6px;border:1px solid var(--surface1);background:var(--surface1);
  flex:none;display:flex;align-items:center;justify-content:center;font-size:14px;cursor:pointer;overflow:hidden;}
.lv-assetprev img{width:100%;height:100%;object-fit:cover;}
.lv-pickico{width:38px;height:32px;flex:none;border-radius:6px;border:1px dashed var(--surface1);
  background:transparent;color:var(--subtext);font-size:14px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;}
.lv-pickico:hover{color:var(--accent);border-color:var(--accent);}
.lv-tagin{width:76px;flex:none;background:var(--base);border:1px solid var(--surface1);border-radius:6px;
  color:var(--accent);font:11px/1.3 ui-monospace,monospace;padding:6px 7px;}
.lv-tagin:focus{outline:0;border-color:var(--accent);}
/* The bound shot's LIVE positional @imageN beside the stored-tag input -- read-only and
   visually distinct from it (dashed border + cyan, matching FrameSlot's own derived
   .sb-tagin display) so the panel never implies the editable stored tag is what gets sent.
   .oob = has a picture but lost the 6-slot contest ("not sent" on R2V/V2V; "not cited" on
   FLF/I2V, where nothing cast-shaped is sent either way -- see modeSendsRefs/liveTagText).
   Worn by the Cast & assets rows (both densities) AND Deep Focus's Other-references image
   rows (round 3) -- one class, one wording source, so the surfaces cannot drift. */
.lv-livetag{flex:none;font:11px/1.3 ui-monospace,monospace;color:var(--cyan);background:var(--base);
  border:1px dashed var(--overlay0);border-radius:6px;padding:6px 7px;}
.lv-livetag.oob{color:var(--peach);border-color:var(--peach);font-size:9.5px;}
.lv-assetrow.oob,.lv-simplecard.oob{opacity:.6;}
/* Live reference-slot budget under the Cast & assets header (6 minus attached frames --
   see refBudget in loom-core.js). .lv-refbudget-over = more resolvable cast/refs than
   slots, i.e. the rows marked .oob below exist. */
.lv-refbudget{font-size:10px;color:var(--subtext);margin:-4px 0 8px;}
.lv-refbudget-over{color:var(--peach);font-weight:700;}
.lv-sel{flex:none;background:var(--base);border:1px solid var(--surface1);border-radius:6px;color:var(--text);
  font:10.5px/1.3 system-ui;padding:6px 3px;}
.lv-locklab,.lv-inshot{display:flex;align-items:center;gap:4px;font-size:9.5px;color:var(--subtext);
  cursor:pointer;flex:none;white-space:nowrap;}
.lv-addcast{margin-top:8px;width:100%;background:var(--surface1);border:1px dashed var(--surface1);color:var(--subtext);border-radius:7px;padding:7px;font:600 11px/1 system-ui;cursor:pointer;}
.lv-addcast:hover{border-color:var(--accent);color:var(--accent);}
/* Density toggle (Cast tab) + the Simple view's square-card grid. */
.lv-density{margin-bottom:10px;}
.lv-simplegrid{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:8px;}
.lv-simplecard{background:var(--surface1);border:1px solid var(--surface1);border-radius:8px;padding:6px;
  text-align:center;}
.lv-simplecard:not(.nosel){cursor:pointer;}
.lv-simplecard:not(.nosel):hover{border-color:var(--accent);}
.lv-simplecard.on{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 10%,transparent);}
.lv-simplecard.nosel{opacity:.55;}
.lv-simplecard img,.lv-simplecard .lv-castph{width:100%;aspect-ratio:1;border-radius:6px;object-fit:cover;margin-bottom:5px;display:block;}
.lv-simplecard b{display:block;font-size:10.5px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lv-simplecard span{display:block;font-size:9px;}
/* Footage tab: browse-the-whole-library + drop-to-add, both land as a Cast & Assets ref. */
.lv-footagehead{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px;}
.lv-footagehead .lv-castrow-h{margin-bottom:0;}
.lv-browsebtn{font:600 10px/1 system-ui;background:var(--base);border:1px solid var(--surface1);color:var(--accent);
  border-radius:6px;padding:5px 8px;cursor:pointer;flex:0 0 auto;}
.lv-browsebtn:hover{border-color:var(--accent);}
.lv-dropzone{margin-top:8px;border:1.5px dashed var(--surface1);border-radius:8px;padding:12px 8px;text-align:center;
  font-size:10.5px;color:var(--subtext);transition:all .15s;}
.lv-dropzone.hover{border-color:var(--accent);color:var(--accent);background:color-mix(in srgb,var(--accent) 6%,transparent);}
/* Legend as an on-demand "+ terms" popover per field -- no persistent panel anywhere. */
.lv-termsbtn{font-size:9px;text-transform:none;letter-spacing:0;color:var(--accent);background:none;border:none;
  cursor:pointer;text-decoration:underline;text-underline-offset:2px;margin-left:6px;}
.lv-termspal{display:flex;flex-wrap:wrap;gap:4px;margin:5px 0 2px;padding:7px;background:var(--surface1);border-radius:7px;}
.lv-termsgrp{width:100%;display:flex;flex-wrap:wrap;gap:4px;align-items:center;}
.lv-termsgrpt{width:100%;font-size:8px;letter-spacing:.05em;text-transform:uppercase;color:var(--subtext);margin-top:4px;}
.lv-footage{padding:8px;display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:8px;align-content:start;}
.lv-fclip{border-radius:7px;overflow:hidden;border:1px solid var(--surface1);cursor:pointer;background:var(--base);}
.lv-fclip.sel{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset;}
.lv-fclip img{width:100%;aspect-ratio:16/10;object-fit:cover;display:block;}
.lv-fmeta{display:flex;justify-content:space-between;padding:3px 5px;font-size:9px;}
.lv-fmeta b{color:var(--accent);}.lv-fmeta span{color:var(--subtext);}
.lv-err{padding:40px;text-align:center;}
.lv-err p{color:var(--coral);}
.lv-err pre{color:var(--subtext);font-size:11px;white-space:pre-wrap;text-align:left;max-height:200px;overflow:auto;background:var(--base);padding:10px;border-radius:7px;}
.lv-tabs{display:flex;gap:4px;margin-bottom:10px;}
.lv-tab{flex:1;text-align:center;font:600 10px/1 system-ui;padding:6px 4px;border-radius:6px;border:1px solid var(--surface1);background:var(--surface1);color:var(--subtext);cursor:pointer;}
.lv-tab.on{background:color-mix(in srgb,var(--accent) 18%,transparent);border-color:var(--accent);color:var(--accent);}
.lv-in{width:100%;background:var(--base);border:1px solid var(--surface1);border-radius:7px;padding:7px 8px;color:var(--text);font:11px/1.3 system-ui;}
.cap-off{opacity:.4;cursor:not-allowed;}
.lv-in:focus{outline:0;border-color:var(--accent);}
.lv-minichip{font-size:9px;color:var(--subtext);background:var(--base);border:1px solid var(--surface1);border-radius:5px;padding:2px 5px;cursor:pointer;}
.lv-minichip:hover{border-color:var(--accent);color:var(--accent);}
.lv-refline{font-size:10px;color:var(--subtext);margin:10px 0 4px;}
/* Draft-mode "route into a shot" picker -- shown only with no shot selected. */
.lv-drafttarget{margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid var(--surface1);}
.lv-drafttarget select.lv-sel{display:block;width:100%;flex:none;padding:7px 8px;font-size:11px;}
.lv-mini2{font-size:9px;color:var(--subtext);background:var(--base);border:1px solid var(--surface1);border-radius:5px;padding:3px 7px;cursor:pointer;margin:5px 0;}
.lv-mini2:hover{border-color:var(--accent);color:var(--accent);}
/* L536: Image tab field-parity additions -- a 2-up row (Size/Custom W×H, Mode/Count) and a
   labeled checkbox row, mirroring moonglade_gallery.py's .gen-row/.gen-check at the same sizing. */
.lv-row2{display:flex;gap:8px;margin-top:8px;}
.lv-row2>div{flex:1;min-width:0;}
.lv-ck{display:flex;align-items:center;gap:7px;color:var(--subtext);font-size:11px;margin-top:8px;cursor:pointer;}
.lv-advnote{display:flex;align-items:center;justify-content:space-between;margin-top:6px;font-size:10px;color:var(--overlay0);}
/* Deep Focus: double-click a board card to open a maximized, distraction-free editor
   for just that shot (title/mode/duration/frames) without leaving the V2 overlay. */
.lv-df-veil{position:fixed;inset:0;z-index:450;background:rgba(6,4,14,.72);display:flex;align-items:center;justify-content:center;padding:24px;}
.lv-df{width:min(640px,92vw);max-height:88vh;overflow:auto;background:var(--surface0);border:1px solid var(--surface1);
  border-radius:14px;padding:18px 20px 22px;box-shadow:0 30px 70px -20px rgba(0,0,0,.7);}
.lv-df-head{display:flex;align-items:center;gap:10px;margin-bottom:14px;}
.lv-df-code{font:700 11px/1 ui-monospace,monospace;color:var(--subtext);flex:0 0 auto;}
.lv-df-title{flex:1;min-width:0;background:transparent;border:none;border-bottom:1px solid var(--surface1);
  color:var(--text);font:600 17px/1.2 system-ui;padding:4px 0;}
.lv-df-title:focus{outline:none;border-bottom-color:var(--accent);}
.lv-df-row{display:flex;gap:16px;margin-bottom:6px;}
.lv-field{flex:1;min-width:0;}
.lv-field.narrow{flex:0 0 120px;}
.lv-df-frames{display:flex;flex-wrap:wrap;gap:12px;align-items:flex-start;margin-top:14px;}
/* Owner, repeatedly: a shot's attached images are too small to tell apart in Deep Focus. They
   were flex:1 1 0 with min-width:0 and no wrapping, so N frames divided the 640px panel between
   them -- six refs landed at roughly 95x84px, too small to distinguish two similar characters,
   which is the entire job of this view. Now they WRAP at a real basis instead of squeezing, and
   the preview is taller here specifically. Scoped to .lv-df-frames on purpose: the compact
   drawer's .lv-framehandoff rule stays as it is, because shrinking is correct in a narrow rail. */
.lv-df-frames .sb-frame{flex:1 1 150px;min-width:150px;max-width:100%;}
.lv-df-frames .sb-frameprev{height:150px;}
.lv-gerr{font-size:10px;color:var(--coral);margin-top:6px;}
/* D-11: LoRA chips in the Image tab -- mirrors the Gallery's own .lora-chip shape
   (moonglade_gallery.py) at the Loom's smaller scale/token set, not a copy-paste of it. */
/* picker-parity-round2 (2026-07-24): this used to be a show/hide toggle that expanded the
   LoRA <ModelPicker> INLINE into this ~280px rail column -- the owner's exact complaint
   ("cramped mess... does not have a flyout like the gallery"). It now opens the SAME
   .lv-mpick-veil overlay the Model row's own trigger does (see below), just pre-selected to
   the LoRAs segment -- reuses .lv-chip's chrome unchanged, only what the click DOES changed. */
.lv-loratoggle{display:inline-block;margin:7px 0 5px;}
.lv-loracap{margin-left:8px;font-size:10.5px;color:var(--subtext);}
.lv-loracap.over{color:var(--coral);font-weight:600;}
.lv-lw{display:flex;align-items:center;gap:6px;flex:0 0 auto;}
.lv-lw input[type=range]{width:92px;padding:0;background:none;border:none;}
.lv-lw b{min-width:32px;text-align:right;font-size:11px;font-weight:600;color:var(--amber);font-variant-numeric:tabular-nums;}
.lv-loras{display:flex;flex-direction:column;gap:5px;margin-bottom:6px;}
.lv-lchip{display:flex;align-items:center;flex-wrap:wrap;gap:7px;padding:5px 7px;border-radius:6px;background:var(--surface0);border:1px solid var(--surface1);font-size:10.5px;color:var(--text);}
.lv-lchip.failed{border-color:var(--coral);}
.lv-lchip .lv-lnm{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lv-lchip.failed .lv-lnm{color:var(--coral);}
.lv-lchip input{width:52px;background:var(--base);border:1px solid var(--surface1);border-radius:4px;color:var(--text);font-size:10px;padding:2px 4px;}
.lv-lorver{flex:1 1 100%;margin-top:1px;background:var(--base);border:1px solid var(--surface1);border-radius:4px;color:var(--text);font-size:10px;padding:2px 4px;}
.lv-lchip .lv-lrm{background:none;border:none;color:var(--subtext);cursor:pointer;font-size:13px;padding:0 2px;line-height:1;}
.lv-lchip .lv-lrm:hover{color:var(--coral);}
/* picker-parity-round2 (problem 2): the Image tab's model/LoRA picker used to render
   <ModelPicker> INLINE in this ~280px rail (cramped: results, a toggle button, a
   SECOND search box, more results, all stacked). Now a trigger row (mirrors
   moonglade_gallery.py's own #gen-selrow) that opens a floating overlay -- .lv-mpick-veil below
   -- matching the Gallery's #model-flyout presentation: ONE picker experience, not a
   cramped-inline one here and a proper flyout there. */
.lv-selrow{display:flex;align-items:center;gap:8px;width:100%;padding:7px 9px;border-radius:6px;background:var(--panel);border:1px solid var(--line);color:var(--ink);cursor:pointer;font-size:11.5px;text-align:left;}
.lv-selrow:hover{border-color:var(--line2);}
.lv-selthumb{width:26px;height:26px;border-radius:6px;object-fit:cover;flex:0 0 auto;}
.lv-selname{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lv-selhint{flex:0 0 auto;font-size:10px;}
.lv-caps{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px;}
.lv-cap{font-size:9.5px;padding:2px 8px;border-radius:10px;background:var(--panel);border:1px solid var(--line);color:var(--ink2);}
.lv-cap.method{color:var(--amber);border-color:var(--amber-d);}
.lv-versel{margin-top:6px;}
/* Floating overlay for the Model/LoRA picker -- centered modal, matching the Loom's own
   established .sb-pick-ov/.lv-df-veil pattern (this file has no per-side "dock" concept for
   the right rail the way the Gallery's #gen-drawer does, so a centered panel is the
   idiomatic Loom equivalent of "floats as its own proper overlay panel", not an attempt to
   pixel-clone the Gallery's specific side-docked mechanics). z-index 470: above
   .lv-overlay/.lv-df-veil (400/450, this picker can be opened from within Deep Focus too)
   and below .sb-seq/.sb-pick-ov (500, an unrelated picker-within-a-picker must still win). */
.lv-mpick-veil{position:fixed;inset:0;z-index:470;background:rgba(6,4,16,.76);display:none;align-items:center;justify-content:center;padding:20px;}
.lv-mpick-veil.open{display:flex;}
.lv-mpick-panel{background:var(--panel);border:1px solid var(--line2);border-radius:12px;box-shadow:var(--shadow);width:460px;max-width:94vw;height:min(640px,86vh);max-height:86vh;display:flex;flex-direction:column;overflow:hidden;}
.lv-mpick-head{display:flex;align-items:center;gap:8px;padding:12px 14px;border-bottom:1px solid var(--line);flex:none;}
.lv-mpick-head .t{font-size:14px;font-weight:600;flex:1;}
.lv-mpick-head .x{background:none;border:none;color:var(--ink2);font-size:22px;cursor:pointer;line-height:1;padding:0 4px;}
.lv-mpick-head .x:hover{color:var(--coral);}
.lv-mpick-seg{display:flex;gap:6px;padding:10px 14px 0;flex:none;}
.lv-mpick-seg button{flex:1;padding:6px 0;border-radius:7px;background:transparent;border:1px solid var(--line);color:var(--ink2);cursor:pointer;font-size:12px;}
.lv-mpick-seg button.on{background:var(--panel2);color:var(--ink);border-color:var(--amber);font-weight:600;}
.lv-mpick-body{padding:10px 14px 14px;display:flex;flex-direction:column;min-height:0;flex:1;}
.lv-mpick-body .model-picker{flex:1;min-height:0;}
.lv-bal{font-size:10.5px;color:var(--text);padding:5px 0 3px;border-bottom:1px solid var(--surface1);margin-bottom:9px;letter-spacing:.02em;opacity:.85;}
.lv-balclaim{color:var(--accent);}
.lv-editsrc{max-width:100%;max-height:120px;border-radius:8px;border:1px solid var(--surface1);margin:4px 0;display:block}
/* Fixer canvas wrapper -- same values as LoomMobile's own .lm-fixwrap/.lm-fixhint/.lm-fixwarn
   (Loom Mobile.dc.html's fixHintStyle/fixWarnStyle), desktop naming only. */
.lv-fixwrap{position:relative;border-radius:8px;overflow:hidden;background:var(--base);
  border:1px solid var(--surface1);margin-top:4px;max-width:100%;}
.lv-fixwrap img{width:100%;max-height:280px;object-fit:contain;display:block;background:#000;}
.lv-fixwrap canvas{position:absolute;inset:0;width:100%;height:100%;touch-action:none;cursor:crosshair;}
.lv-fixhint{font-size:10.5px;line-height:1.5;color:var(--subtext);margin:10px 0 6px;}
.lv-fixwarn{font-size:10px;line-height:1.45;color:var(--peach);background:rgba(232,147,95,.08);
  border:1px solid rgba(232,147,95,.3);border-radius:8px;padding:7px 9px;margin-top:8px;}
.lv-openfilters{display:block;width:100%;box-sizing:border-box;text-align:center;padding:10px;
  border-radius:10px;font-size:12px;font-weight:700;cursor:pointer;border:1px solid var(--surface1);
  background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--accent);margin:6px 0;}
.lv-openfilters:hover{border-color:var(--accent);}
/* Filter compare modal -- The Loom.dc.html's own filterCompareOpen, literal values (fixed
   veil + centered card, 920px cap, 3-column grid: preview/preview/filters+sliders). */
.lv-fc-veil{position:fixed;inset:0;z-index:47;background:rgba(5,4,13,.72);backdrop-filter:blur(7px);}
.lv-fc-host{position:fixed;inset:0;z-index:48;display:grid;place-items:center;pointer-events:none;padding:20px;}
.lv-fc-card{pointer-events:auto;box-sizing:border-box;width:min(920px,calc(100vw - 40px));
  max-height:92vh;overflow-y:auto;border-radius:16px;border:1px solid var(--surface1);
  background:var(--surface0);box-shadow:0 34px 80px -18px rgba(0,0,0,.75);padding:16px 20px 20px;}
.lv-fc-head{display:flex;align-items:center;gap:10px;margin-bottom:14px;}
.lv-fc-title{font-size:15px;font-weight:800;}
.lv-fc-grid{display:grid;grid-template-columns:1fr 1fr 200px;gap:16px;align-items:start;}
.lv-fc-previewcol{min-width:0;}
.lv-fc-previewbox{position:relative;width:100%;aspect-ratio:1;border-radius:10px;overflow:hidden;
  background:var(--base);border:1px solid var(--surface1);}
.lv-fc-stage{position:relative;width:100%;height:100%;}
.lv-fc-img{width:100%;height:100%;object-fit:cover;display:block;}
.lv-fc-side{display:flex;flex-direction:column;gap:10px;}
.lv-fc-grouplabel{font-size:9px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;
  color:var(--overlay0);margin-bottom:5px;}
.lv-fc-swatchgrid{display:grid;grid-template-columns:repeat(3,1fr);gap:5px;}
.lv-fc-tile{position:relative;display:flex;flex-direction:column;gap:3px;cursor:pointer;
  border-radius:8px;padding:3px;border:1px solid transparent;background:none;}
.lv-fc-tile.on{border-color:var(--accent);}
.lv-fc-swatch{width:100%;aspect-ratio:1;border-radius:6px;background:var(--surface1);}
.lv-fc-name{font-size:8.5px;text-align:center;padding:2px 1px;color:var(--subtext);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lv-fc-range{width:100%;height:3px;cursor:pointer;}
.lv-fc-btnrow{display:flex;gap:6px;}
.lv-refstrip{display:flex;gap:5px;flex-wrap:wrap;margin:4px 0 2px}
.lv-refstrip img{width:44px;height:44px;object-fit:cover;border-radius:6px;border:1px solid var(--surface1)}
.lv-imgresult{margin-top:10px;border:1px solid var(--surface1);border-radius:8px;padding:8px;}
.lv-imgresult>img{width:100%;border-radius:6px;display:block;}
.lv-route{display:flex;gap:5px;align-items:center;flex-wrap:wrap;margin-top:8px;}
.lv-routebtn{font:600 10px/1 system-ui;padding:5px 9px;border-radius:6px;border:1px solid var(--surface1);background:var(--surface1);color:var(--subtext);cursor:pointer;}
.lv-routebtn:hover{border-color:var(--accent);color:var(--accent);}
.lv-routebtn.on{background:color-mix(in srgb,var(--accent) 22%,transparent);border-color:var(--accent);color:var(--accent);}
.lv-ok2{font-size:10px;color:var(--accent);margin-top:6px;}
`;
class V2Boundary extends React.Component {
  constructor(props) { super(props); this.state = { err: null }; }
  static getDerivedStateFromError(e) { return { err: e }; }
  render() {
    if (this.state.err) return (
      <div className="lv-overlay"><div className="lv-err">
        <p>The Loom hit a render error. Your storyboards are saved and safe — reload to recover.</p>
        <pre>{String((this.state.err && this.state.err.stack) || this.state.err)}</pre>
        <button className="lv-close" onClick={() => window.location.reload()}>↻ Reload the Loom</button>
        <a className="lv-close" href="/" style={{ textDecoration: "none" }}>← Back to the gallery</a>
      </div></div>
    );
    return this.props.children;
  }
}
// friendlyGenErr now imported from ./src/loom-mutations.js (Phase 2).

// Shared storyboard switcher — used in BOTH the classic header and the V2 header.
// All project state/actions arrive bundled as `api` (built once in App).
function ProjectSwitcher({ api }) {
  const { activeId, projList, projMenu, setProjMenu, readProjList, openProject, newProject, duplicateProject, deleteProject } = api;
  // Escape closes it, same as Deep Focus's handler in LoomV2. Without this the only way out
  // is a click, and .sb-projveil is a full-viewport pointer-events layer -- so until you
  // find somewhere to click, nothing else in the app responds at all.
  useEffect(() => {
    if (!projMenu) return;
    const onKey = (ev) => { if (ev.key === "Escape") setProjMenu(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [projMenu, setProjMenu]);
  return (
    <div className="sb-projwrap">
      <button className="sb-projbtn" onClick={() => { setProjMenu((v) => !v); readProjList(); }}
        title="Switch, create, or manage storyboards" aria-label="Storyboards">&#9662;</button>
      {projMenu && <div className="sb-projveil" onClick={() => setProjMenu(false)} />}
      {projMenu && (
        <div className="sb-projpop">
          <div className="sb-projpoph">Storyboards</div>
          <div className="sb-projlist">
            {projList.map((pr) => (
              <div key={pr.id} className={"sb-projitem" + (pr.id === activeId ? " on" : "")}>
                <button className="sb-projopen" onClick={() => openProject(pr.id)} title="Open this storyboard">
                  <b>{pr.name || "Untitled"}</b><span>{pr.shots} shot{pr.shots === 1 ? "" : "s"}</span></button>
                <button className="sb-projx" title="Delete" onClick={() => deleteProject(pr.id)}>&#10005;</button>
              </div>
            ))}
          </div>
          <div className="sb-projacts">
            <button className="sb-btn sm" onClick={newProject}>+ New</button>
            <button className="sb-btn sm ghost" onClick={duplicateProject}>&#10697; Duplicate</button>
          </div>
        </div>
      )}
    </div>
  );
}

// Two-tier project export, off the ProjectSwitcher as one "Export ▾" menu (the locked
// design) rather than three flat buttons: Shot list (.txt, unchanged), Lightweight backup
// (.json -- project + local-only thumbs, referencing your own catalog by media id, the
// existing exportJSON), and Full bundle (.zip -- the same JSON plus the actual referenced
// media files, for sharing with someone who doesn't share your catalog). Restore accepts
// either file back; importBackup sniffs which one it got.
function ExportMenu({ exportAll, exportJSON, exportBundle, importBackup, bundling }) {
  const [open, setOpen] = useState(false);
  // Escape closes it -- same reason as ProjectSwitcher above: this menu reuses .sb-projveil.
  useEffect(() => {
    if (!open) return;
    const onKey = (ev) => { if (ev.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);
  return (
    <div className="sb-projwrap">
      <button className="sb-projbtn" onClick={() => setOpen((v) => !v)}
        title="Export or restore this project" aria-label="Export">Export &#9662;</button>
      {open && <div className="sb-projveil" onClick={() => setOpen(false)} />}
      {open && (
        <div className="sb-projpop">
          <div className="sb-projpoph">Export</div>
          <button className="sb-exportitem" onClick={() => { exportAll(); setOpen(false); }}>
            Shot list <small>.txt</small></button>
          <button className="sb-exportitem" onClick={() => { exportJSON(); setOpen(false); }}
            title="Project + any locally-added assets, referencing your own catalog by media id -- the quiet default for your own home ⇄ work use">
            Lightweight backup <small>.json</small></button>
          <button className="sb-exportitem" disabled={bundling}
            onClick={() => { exportBundle(); setOpen(false); }}
            title="Everything in the lightweight backup, plus the actual media files -- for sharing with someone who doesn't share your catalog">
            {bundling ? "Building bundle…" : <>Full bundle <small>.zip</small></>}</button>
          <div className="sb-exportdiv" />
          <label className="sb-exportitem" style={{ cursor: "pointer" }}
            title="Restore either a lightweight backup or a full bundle -- always opens as a new storyboard">
            &#8681; Restore from file
            <input type="file" accept=".json,.zip,application/json,application/zip" style={{ display: "none" }}
              onChange={(e) => { importBackup(e.target.files[0]); setOpen(false); }} /></label>
        </div>
      )}
    </div>
  );
}

function LoomV2({ project, setCard, setAssets, entries, durOf, scale, selShot, setSelShot, useExistingVideo, genState, thumbs, openPick, storeThumb, setAct, addCard, importFootage, dupCard, delCard, moveCard, moveCardToAct, addAct, delAct, moveAct, genImgState, imgModel, setImgModel, imgLoras, setImgLoras, imgAdv, setImgAdv, modelDefaults, setModelDefaults, genImage, routeImg, genEditState, setGenEditState, genRefState, setGenRefState, genEdit, genRef, routeGen, genFixState, setGenFixState, genFix, projectApi, playSequence, exportCut, batching, batchGenerate, addRef, setRef, delRef, exportAll, exportJSON, exportBundle, bundling, importBackup, setImportOpen, copyShot, setLook, setDraft, splitShot, onVideoSubmit, onVideoResult, onVideoError, onVideoSlow, onVideoPaused, pollShot, costEstimate, refreshEstimate, batchTally,
  // draftCard/draftTarget/draftAttachedInfo used to be LoomV2's own useState triple (a
  // Generate-drawer draft with no shot selected yet, keyed "__draft__" everywhere else in
  // this file already keys genState/genImgState/etc). LIFTED to App() (mobile-board-view
  // pass, 2026-08-03) so a still-in-progress draft survives toggling to Mobile view and back
  // -- before this, the draft lived only in LoomV2's own component state, so unmounting it
  // (which is exactly what picking Mobile view does) silently discarded whatever the owner
  // had half-typed into Generate. Every reference below is unchanged from when these were
  // local useState calls -- only the declaration moved, so LoomV2's own behavior is identical.
  mobileUI, setMobileUI, draftCard, setDraftCard, draftTarget, setDraftTarget, draftAttachedInfo, setDraftAttachedInfo }) {
  // The Loom.dc.html:33-45's collapsible hero banner -- entirely missing before this.
  // Design's own state (line 743, `bannerOpen: true`) is plain in-memory, not persisted, so
  // this matches exactly rather than adding localStorage this feature never had in spec.
  const [bannerOpen, setBannerOpen] = useState(true);
  const [tab, setTab] = useState("Video");
  const [acct, setAcct] = useState(null);  // credits/cards for the inline balance line
  const [handoff, setHandoff] = useState("");   // frame-handoff splice state: '', 'wip', 'err'
  const [deepFocus, setDeepFocus] = useState(null);   // entry {a,c,ai,ci,code} double-clicked on the board, or null
  // Deep Focus's own body is an IIFE inside a conditional render (below), not a component or
  // hook -- calling useState there would violate the rules of hooks (conditional hook call).
  // This state belongs to Deep Focus but has to live up here, at LoomV2's real top level, same
  // as deepFocus itself; the IIFE below only reads/writes it via closure.
  const [dfPalFor, setDfPalFor] = useState(null);     // which term-palette is open in Deep Focus, or null
  // picker-parity-round2 (problem 2): replaces the old loraOpen boolean (D-11), which just
  // toggled the LoRA <ModelPicker> INLINE into this rail -- the owner's exact complaint.
  // pickerOpen/pickerKind instead drive the floating .lv-mpick-veil overlay (mirrors
  // moonglade_gallery.py's #model-flyout open state + Models/LoRAs segment), opened via either
  // the Model row's trigger (kind="base") or "+ add LoRA" (kind="lora").
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerKind, setPickerKind] = useState("base");
  const [leftTab, setLeftTab] = useState("cast");        // 'cast' | 'footage'
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [leftClosing, setLeftClosing] = useState(false);  // true for 340ms while the panel plays its slide-out, matching The Loom.dc.html's own leftClosing/lvSlideOutL
  const [density, setDensity] = useState("detailed");    // 'simple' | 'detailed' -- Cast tab only
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [rightClosing, setRightClosing] = useState(false);
  const leftCloseTimer = useRef(null);
  const rightCloseTimer = useRef(null);
  // Panels float over the board now (design's leftPanelStyle/rightPanelStyle), so closing
  // needs the same two-step the design uses: play the .34s slide-out, THEN actually collapse --
  // an instant collapse would cut the exit animation off after one frame.
  const closeLeftPanel = () => {
    setLeftClosing(true);
    clearTimeout(leftCloseTimer.current);
    leftCloseTimer.current = setTimeout(() => { setLeftCollapsed(true); setLeftClosing(false); }, 340);
  };
  const closeRightPanel = () => {
    setRightClosing(true);
    clearTimeout(rightCloseTimer.current);
    rightCloseTimer.current = setTimeout(() => { setRightCollapsed(true); setRightClosing(false); }, 340);
  };
  const openLeftPanel = () => { clearTimeout(leftCloseTimer.current); setLeftClosing(false); setLeftCollapsed(false); };
  const openRightPanel = () => { clearTimeout(rightCloseTimer.current); setRightClosing(false); setRightCollapsed(false); };
  useEffect(() => () => { clearTimeout(leftCloseTimer.current); clearTimeout(rightCloseTimer.current); }, []);
  const [tlState, setTlState] = useState("slim");        // 'hidden' | 'slim' | 'full'
  const [tlDragH, setTlDragH] = useState(null);          // live px height while dragging the handle, else null
  const [palFor, setPalFor] = useState(null);            // which field's "+ terms" popover is open, or null
  const [dzHover, setDzHover] = useState(false);          // footage drop-zone hover feedback
  const [overrideClearedFlash, setOverrideClearedFlash] = useState(false);   // brief notice when the native Prompt field destroys an active override
  // Draft generation: the Generate drawer works with no shot selected, exactly like the
  // main gallery's own drawer -- a "card" that lives in component state instead of the
  // project, generation-state dicts keyed by its "__draft__" id right alongside real shots'.
  // draftCard/draftTarget/draftAttachedInfo are now App()-level props (see this function's
  // own signature comment) -- lifted, not removed; every use below is unchanged.
  const tlDrag = useRef({ dragging: false, startY: 0, startH: 0 });
  // The overlay is position:fixed, so it never visibly moves -- but classic Loom's own
  // page underneath is a normal tall document, and without this, its body/html scrollbar
  // stays live. A wheel scroll that isn't captured by one of the internal panels (already
  // at its own scroll limit, or over a non-scrolling area) bubbles up and scrolls THAT,
  // which reads as the whole thing randomly jumping since nothing visible moved to explain it.
  useEffect(() => {
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prevOverflow; };
  }, []);
  useEffect(() => { fetch("/api/account").then((r) => r.json()).then(setAcct).catch(() => {}); }, []);
  useEffect(() => {
    if (!deepFocus) return;
    const onKey = (ev) => { if (ev.key === "Escape") setDeepFocus(null); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deepFocus]);
  // picker-parity-round2: Escape closes the model/LoRA overlay, same as every other veil
  // in this file (deepFocus above, the Export popover, ProjectSwitcher).
  useEffect(() => {
    if (!pickerOpen) return;
    const onKey = (ev) => { if (ev.key === "Escape") setPickerOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pickerOpen]);
  // picker-parity-round2: lazy-mount both <ModelPicker> instances on FIRST open (mirrors
  // moonglade_gallery.py's ensurePickers() -- "only fetch on first open", not an always-mounted
  // base+LoRA fetch on every Loom load just because the right rail happens to be expanded).
  // Once true, stays true -- the pickers then persist (hidden via .lv-mpick-veil's own
  // display:none/.open) so a close/reopen never loses either one's search/scroll state.
  const [pickerMounted, setPickerMounted] = useState(false);
  useEffect(() => { if (pickerOpen) setPickerMounted(true); }, [pickerOpen]);
  // Bridge the shared <ModelPicker> web component to React: a ref callback (React
  // doesn't route custom events through JSX props) that binds the 'mg-pick' listener once.
  // imgModelSeqRef guards the /api/model-version fetch below the same way the Gallery's own
  // selectCard() guards its identical fetch with a local selSeq/mySeq pair: a fast second
  // pick must not let the FIRST pick's now-stale response land after it.
  const imgModelSeqRef = useRef(0);
  // LoRA weight bounds for the CURRENT base model's architecture. DiT takes 0..1.2, the SD
  // family -2..+2; an unknown or not-yet-picked base falls back to the widest range rather
  // than the narrowest, so an unrecognised architecture never silently removes a capability
  // the account has. Served from core (window.MG_LORA) -- one table, three consumers.
  const loraRange = useMemo(() => {
    const L = window.MG_LORA;
    const t = String((imgModel && imgModel.model_type) || "").toUpperCase();
    if (!L) return [-2, 2];
    return (L.ranges && L.ranges[t]) || L.fallback || [-2, 2];
  }, [imgModel]);
  // Switching base architecture with LoRAs already attached must bring their weights into
  // the new range -- a -0.8 left over from SDXL is a weight a DiT model rejects.
  useEffect(() => {
    setImgLoras((cur) => {
      let changed = false;
      const next = cur.map((l) => {
        const w = Math.max(loraRange[0], Math.min(loraRange[1], +l.weight));
        if (w !== l.weight) changed = true;
        return w === l.weight ? l : { ...l, weight: w };
      });
      return changed ? next : cur;
    });
  }, [loraRange, setImgLoras]);
  const onBasePick = useCallback((row) => {
    // Owner report 2026-07-24: picking a model left the overlay open, forcing a
    // manual close -- close it the instant a base model is picked (single-select:
    // one choice ends the browsing task), mirroring moonglade_gallery.py's onBasePick.
    // LoRA picking (the other <ModelPicker> mount, kind="lora" multi) is
    // deliberately left open -- see the "+ add LoRA" toggle below.
    setPickerOpen(false);
    const m = { model_id: row.model_id, title: row.title, preview_url: row.preview_url || "" };
    setImgModel(m);
    setModelDefaults(null);
    // L536 + D-11: resolve model_type (so the LoRA compat warning has a real base to
    // compare against -- the Loom never fetched this at all before) and prefill the
    // model author's own tuned preset (negative/steps/cfg), mirroring
    // moonglade_gallery.py's Gen.applyModelDefaults() exactly: only for fields the model
    // actually has data for, and it OVERWRITES whatever's currently in imgAdv, same as
    // the Gallery's own (deliberate, already-shipped) behavior on every base-model pick.
    // picker-parity-round2 (problem 4/5): ?all=1 replaces the old single-version fetch --
    // ONE request either way (same endpoint), but now returns every published release
    // (versions[0] is the same "latest" the old fetch always resolved) so the version
    // picker + sampling_method + capabilities the app was resolving and discarding can
    // finally be shown, mirroring moonglade_gallery.py's onBasePick/applyVersion exactly.
    const mySeq = ++imgModelSeqRef.current;
    fetch("/api/model-version?model_id=" + encodeURIComponent(m.model_id) + "&all=1")
      .then((r) => r.json())
      .then((d) => {
        if (mySeq !== imgModelSeqRef.current) return;   // a newer pick superseded this fetch
        const versions = (d && d.versions) || [], v = versions[0] || {};
        // Owner report 2026-07-24: the version dropdown never appeared on the Loom for a
        // model confirmed (same model, same account) to show one on the Gallery. Root
        // cause: this updater ALSO required cur.model_id===m.model_id on top of the
        // mySeq check above -- redundant for the "newer pick superseded this one" case
        // mySeq already covers, but a real liability for anything else that can touch
        // imgModel while this fetch is in flight (a shot switch, a project reload) --
        // any of those silently drops the whole versions/compatibility/restrictions
        // payload with no error, no retry, nothing visibly wrong. The Gallery's own
        // onBasePick has never done a model_id re-check here, only the sequence guard --
        // matching it exactly rather than carrying an extra condition that was never
        // proven necessary and demonstrably breaks the one thing it must never break.
        setImgModel((cur) => cur ? {
          ...cur, version_id: v.version_id || "", model_type: v.model_type || "",
          sampling_method: v.sampling_method || "", capabilities: v.capabilities || [],
          compatibility: v.compatibility || {}, restrictions: v.restrictions || {},
          versions,
        } : cur);
        const has = v.negative_prompt || v.sampling_steps || v.cfg_scale;
        setModelDefaults(has ? { negative_prompt: v.negative_prompt || "", sampling_steps: v.sampling_steps || null, cfg_scale: v.cfg_scale || null } : null);
        if (has) {
          setImgAdv((cur) => ({
            ...cur,
            negative: v.negative_prompt || cur.negative,
            steps: v.sampling_steps || cur.steps,
            cfg: v.cfg_scale || cur.cfg,
          }));
        }
      })
      .catch(() => {});
  }, [setImgModel, setImgAdv, setModelDefaults]);
  // problem 4: PixAI's own model/LoRA cards offer a version selector; resolve_version_meta
  // always silently took the newest release. imgModel.versions (populated by bindPicker's
  // ?all=1 fetch above) lists every one -- switching re-applies that version's OWN meta (a
  // different release can, in principle, carry a different tuned preset or model_type)
  // through the same shape bindPicker uses, no extra network call, the data's already in
  // hand.
  const pickVersion = useCallback((vid) => {
    if (!imgModel || !imgModel.versions) return;
    const v = imgModel.versions.find((x) => x.version_id === vid);
    if (!v) return;
    setImgModel((cur) => ({
      ...cur, version_id: v.version_id || "", model_type: v.model_type || "",
      sampling_method: v.sampling_method || "", capabilities: v.capabilities || [],
      compatibility: v.compatibility || {}, restrictions: v.restrictions || {},
    }));
    const has = v.negative_prompt || v.sampling_steps || v.cfg_scale;
    setModelDefaults(has ? { negative_prompt: v.negative_prompt || "", sampling_steps: v.sampling_steps || null, cfg_scale: v.cfg_scale || null } : null);
    if (has) {
      setImgAdv((a) => ({
        ...a,
        negative: v.negative_prompt || a.negative,
        steps: v.sampling_steps || a.steps,
        cfg: v.cfg_scale || a.cfg,
      }));
    }
  }, [imgModel, setImgModel, setImgAdv, setModelDefaults]);
  // D-11: the LoRA picker uses mg-model-picker's opt-in `multi` mode, whose mg-pick
  // detail shape is { model, selected } (not the raw row bindPicker above expects) --
  // upsert-by-model_id on selected=true (covers both the initial pending entry and the
  // later resolved-version_id update, same entry re-dispatched), remove on selected=false.
  const onLoraPick = useCallback((model, selected) => {
    setImgLoras((cur) => {
      const i = cur.findIndex((l) => l.model_id === model.model_id);
      if (!selected) return i < 0 ? cur : cur.filter((l) => l.model_id !== model.model_id);
      if (i < 0) return [...cur, model];
      const next = cur.slice(); next[i] = model; return next;
    });
  }, [setImgLoras]);
  // D-12 increments 2-4: read-only cost badges for the Image/Edit/Reference tabs -- refs to
  // the <mg-cost-badge> custom elements (imperative setChecking/setPrice/clear API, the same
  // component the Gallery's Generate and Edit tabs use). Kept ALONGSIDE -- not instead of --
  // confirmSpend's window.confirm at submit time below: these three tabs' confirm dialog IS
  // the fail-closed guardrail that got built after they used to lie about cost (see
  // confirmSpend's own comment), so the badge is an added preview, not a replacement for the
  // submit-time gate.
  const imgCostRef = useRef(null);
  const editCostRef = useRef(null);
  const refCostRef = useRef(null);
  // Shared read-only price fetch, imperative so a fast-changing prompt never triggers a
  // React re-render just to show "checking...". Guards on `ref.current === badge` (captured
  // at call time) so a response for a badge the ref has since moved off of -- tab switch,
  // unmount -- never writes into whatever now lives at ref.current.
  const priceInto = (ref, body) => {
    const badge = ref.current;
    if (!badge) return;
    badge.setChecking();
    fetch("/api/price", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then((r) => r.json())
      .then((d) => { if (ref.current === badge) badge.setPrice(d); })
      .catch(() => { if (ref.current === badge) badge.setPrice(null); });
  };
  // Bridge <mg-generate-drawer> the same way. activeRef always holds the CURRENT active
  // shot (updated every render below) so these long-lived, bind-once listeners never read
  // a stale closure from whichever shot happened to be selected when the element first
  // mounted. promptDirtyRef tracks "the owner has typed in the drawer's prompt box since
  // the last prefill" -- the weave-resync effect below checks it so a hand-edit wins,
  // exactly the locked design's "your edit wins" rule. onVideoSubmit/onVideoResult/
  // onVideoError are passed down from the parent (where setGenState/setCardStatus live,
  // via useGenerationPipeline) -- LoomV2 itself only gets genState read-only, not its
  // setter, so the actual state writes stay owned one level up, same layering as
  // generateShot/useExistingVideo already crossing this same boundary.
  const activeRef = useRef(null);
  // mg-prompt-commit's listener (below) is bound once and needs the CURRENT project to
  // compute "did this hand-edit actually change anything from the auto-composed text" --
  // a plain closure over the `project` param from whichever render bindGenDrawer's callback
  // last ran on would go stale the moment the project changes without a re-bind.
  const projectRef = useRef(project);
  projectRef.current = project;
  // Same staleness reasoning as projectRef, for the mg-pick-request handler below (also
  // bound once, also needs to resolve local thumbId-based images at whatever moment the
  // owner actually completes a pick, not whichever render bindGenDrawer last ran on).
  const thumbsRef = useRef(thumbs);
  thumbsRef.current = thumbs;
  const genDrawerRef = useRef(null);
  const promptDirtyRef = useRef(false);
  // The drawer resolves its OWN completion target via activeRef at listener-registration
  // time -- but activeRef always points at "whatever shot is currently selected," read at
  // whatever moment mg-result/mg-error actually FIRE, which can be minutes after submit if
  // the owner switches shots while the render is in flight. genTargetRef freezes "which shot
  // this drawer generation belongs to" the moment mg-submit fires (the earliest point the
  // host can observe), so a later result/error routes to the shot that was ACTUALLY
  // generated, not whatever happens to be selected when the poll resolves. Found 2026-07-18
  // live-testing: switching shots mid-render silently attributed the result to the wrong
  // card. The drawer only ever has one poll in flight at a time (its own Go button disables
  // during a render), so a single ref -- not a task_id-keyed map -- is sufficient.
  const genTargetRef = useRef(null);
  // Tracks which shot the prefill effect below last ran for, so it can tell "the owner
  // switched shots" apart from "a field on the SAME shot changed" (both re-trigger the
  // effect, since active.c.* is in its dependency array). Only the former should clear
  // promptDirtyRef -- without this, promptDirtyRef.current stays true forever after the
  // FIRST hand-edit anywhere, and every other shot's drawer stops re-syncing its composed
  // prompt: selecting shot B after hand-editing shot A leaves B's drawer showing A's stale
  // text with no warning. Found 2026-07-18 live-testing.
  const lastActiveIdRef = useRef(null);
  const bindGenDrawer = useCallback((el) => {
    genDrawerRef.current = el;
    if (el && !el._mgBound) {
      el._mgBound = true;
      el.addEventListener("mg-dirty", () => { promptDirtyRef.current = true; });
      // Fired ONLY from a direct user click on the drawer's own mode-segment buttons (see
      // mg-generate-drawer.js's _userSetMode) -- never from the drawer re-asserting/auto-
      // switching its mode internally (prefill()/_applyModelGating()), which would create a
      // host<->drawer sync loop. Routes through the existing, tested setShotMode reducer so
      // its Continuity-reset side effect (connect:"flf"->"new") keeps firing exactly as it
      // does today via the (soon-removed) Continuity-panel MODE chips.
      el.addEventListener("mg-mode-commit", (e) => {
        const a = activeRef.current; if (!a) return;
        const vmode = e.detail.vmode;
        // Guard against a redundant click: drawerModeFor collapses BOTH R2V and V2V into the
        // drawer's single 'r2v'/Multi-Reference display, since the drawer has no V2V concept
        // at all. Without this guard, clicking an already-highlighted Multi-Reference button
        // on a V2V shot (settable only via Deep Focus's surviving Mode chips) would silently
        // overwrite the card's real V2V mode to R2V -- a genuine, durable field mutation
        // disguised as a no-op re-click on a control that already looked selected.
        const apply = (c) => (drawerModeFor(c.mode) === vmode) ? c : setShotMode(c, cardModeForVmode(vmode));
        a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
      });
      // Duration has no cross-field coupling the way Mode/Connect do (grepping every
      // c.duration read across loom-core.js/loom-mutations.js turned up nothing that
      // transforms it alongside another field -- Deep Focus's own separate duration input
      // is equally uncoupled), so unlike mode this is a plain field write, no reducer.
      el.addEventListener("mg-duration-commit", (e) => {
        const a = activeRef.current; if (!a) return;
        const d = e.detail.duration;
        const apply = (c) => ({ ...c, duration: d });
        a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
      });
      // Same reasoning as duration: audioGen/audioLanguage are independent scalar fields (no
      // must-change-together invariant the way promptOverride/promptOverrideText have), so a
      // plain write covering both fields off the drawer's one shared commit event is correct.
      el.addEventListener("mg-audio-commit", (e) => {
        const a = activeRef.current; if (!a) return;
        const { audioGen, audioLanguage } = e.detail;
        const apply = (c) => ({ ...c, audioGen, audioLanguage });
        a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
      });
      // the 2026-07-21 audit's pinned "reference picker corruption" row, requirement 2: a
      // successful pick used to ONLY ever call e.detail.respond(), which writes into the
      // drawer's own PRIVATE _slots/_imgSlots/_vidSlots array and nothing else -- invisible
      // to the rest of the app, and silently discarded the next time ANY host-tracked field
      // changes and the prefill effect below rebuilds the drawer's banks fresh from
      // buildShotPayload(). That is why "the Image References panel never advances past its
      // original entries" -- a pick had nowhere durable to land. Commit 2e714fd fixed this
      // for the Multi-Reference bank specifically (bank:"primary", mode:"r2v") -- the exact
      // panel the owner's bug was about. Every other (bank, mode) combination the drawer can
      // ever actually request now gets the same treatment: i2v/flf's Start/End-frame slots
      // write into c.openFrame/c.closeFrame directly (no cast/ref folding needed -- a slot
      // index maps unambiguously to one of the two), and r2v's separate video-reference bank
      // (bank:"vid") goes through pickVideoTarget()'s own small plan (loom-core.js -- video
      // refs store their media id in c.refs' .source, not .mediaId). The plain
      // e.detail.respond()-only fallback stays as the last branch, for any (bank, mode) the
      // dedicated cases above don't recognize -- forward-compatible dead code today, not a
      // gap (still correct for a SUBMIT either way, since the drawer's own payload() reads
      // its live slots directly regardless of what the host durably records).
      el.addEventListener("mg-pick-request", (e) => {
        const { slot, bank, mode: reqMode } = e.detail;
        if (bank === "primary" && reqMode === "r2v") {
          openPick((mid, thumb, isVideo, duration, isNsfw) => {
            e.detail.respond(mid, thumb, isNsfw);   // keep the drawer's own immediate slot/chip repaint
            const a = activeRef.current; if (!a) return;
            const proj = projectRef.current;
            const resolve = (thumbId, source) => thumbId ? thumbsRef.current[thumbId]
              : (source && (source.startsWith("http") || source.startsWith("data:") || isCatalogMediaId(source)) ? source : null);
            const plan = pickTarget(a, proj, resolve, slot);
            if (plan.type === "replace" && plan.kind === "cast") {
              // Cast assets are project-GLOBAL (shared identity across every shot that uses
              // them) -- same setAssets() call the Cast & assets panel's own "Pick from your
              // gallery" icon already makes (line ~1458), so this stays consistent with the
              // one other place a cast member's picture is replaced.
              setAssets((arr) => arr.map((x) => x.id !== plan.id ? x : { ...x, mediaId: String(mid), thumbId: "", source: "" }));
            } else if (plan.type === "replace" && plan.kind === "ref") {
              // c.refs lives on the CARD, not project.acts -- setRef (which goes through
              // patchRef/project.acts) would silently no-op for the "__draft__" card, so this
              // uses the same direct setCard/setDraftCard idiom as every other handler here.
              const apply = (c) => ({ ...c, refs: c.refs.map((r) => r.id !== plan.id ? r : { ...r, mediaId: String(mid), thumbId: "", source: "" }) });
              a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
            } else if (plan.type === "replace" && plan.kind === "frame") {
              const apply = (c) => ({ ...c, [plan.id]: { ...c[plan.id], mediaId: String(mid), thumbId: "", source: "" } });
              a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
            } else {
              // A genuinely NEW reference (the "+ add" slot, past everything this shot already
              // supplies) -- append it to the shot's own refs so it persists and re-weaves into
              // the composed prompt at its real (positional) tag, instead of vanishing the
              // moment anything else re-triggers the prefill effect below.
              const newRef = { ...buildNewRef("image", uid()), tag: plan.tag, mediaId: String(mid) };
              const apply = (c) => ({ ...c, refs: [...c.refs, newRef] });
              a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
            }
          }, "image");
        } else if (bank === "primary" && (reqMode === "i2v" || reqMode === "flf")) {
          // i2v's single Start Frame slot is always slot 0; flf's Start/End Frame boxes
          // request slot 0/1 respectively (see mg-generate-drawer.js's _renderSlots()/
          // _renderEndSlot()) -- unlike the r2v bank there's no cast/ref folding to resolve,
          // so this needs no pickTarget()-style plan, just the same direct openFrame/
          // closeFrame merge FrameSlot's own "Pick from the gallery" icon already performs
          // (patchFrame, ~line 1227) for Deep Focus's identical frame slots.
          openPick((mid, thumb, isVideo, duration, isNsfw) => {
            e.detail.respond(mid, thumb, isNsfw);
            const a = activeRef.current; if (!a) return;
            const key = slot === 1 ? "closeFrame" : "openFrame";
            const apply = (c) => ({ ...c, [key]: { ...c[key], mediaId: String(mid), thumbId: "", source: "" } });
            a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
          }, "image");
        } else if (bank === "vid") {
          // r2v's SEPARATE video-reference bank -- c.refs entries of kind:"video" hold their
          // media id in .source (a numeric string), not .mediaId the way image refs do (see
          // shotPayload()'s `vids` computation in loom-core.js), so this goes through its own
          // small pickVideoTarget() plan rather than pickTarget()'s image-shaped one.
          openPick((mid, thumb, isVideo, duration, isNsfw) => {
            e.detail.respond(mid, thumb, isNsfw);
            const a = activeRef.current; if (!a) return;
            const plan = pickVideoTarget(a, slot);
            if (plan.type === "replace") {
              const apply = (c) => ({ ...c, refs: c.refs.map((r) => r.id !== plan.id ? r : { ...r, source: String(mid), thumbId: "" }) });
              a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
            } else {
              const newRef = { ...buildNewRef("video", uid()), tag: plan.tag, source: String(mid) };
              const apply = (c) => ({ ...c, refs: [...c.refs, newRef] });
              a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
            }
          }, "video");
        } else {
          openPick((mid, thumb, isVideo, duration, isNsfw) => e.detail.respond(mid, thumb, isNsfw), e.detail.kind === "video" ? "video" : "image");
        }
      });
      el.addEventListener("mg-submit", (e) => {
        const a = activeRef.current;
        genTargetRef.current = a.c.id;
        // The drawer may have submitted a different mode than the card believes -- e.g. a
        // model-gating auto-switch (_applyModelGating) that never wrote back on its own (that
        // would let casual model-browsing silently corrupt a card's real mode). Reconcile the
        // card's durable mode field to what ACTUALLY got submitted, at the one moment it's
        // known for certain, so badges/shotText/telemetry never permanently disagree with the
        // render that's about to attach to this card.
        const submitted = e.detail.payload && e.detail.payload.mode;
        if (a && submitted && submitted !== a.c.mode) {
          const apply = (c) => setShotMode(c, submitted);
          a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
        }
        onVideoSubmit(genTargetRef.current, e.detail);
      });
      el.addEventListener("mg-result", (e) => onVideoResult(genTargetRef.current || activeRef.current.c.id, e.detail));
      el.addEventListener("mg-error", (e) => onVideoError(genTargetRef.current || activeRef.current.c.id, e.detail));
      el.addEventListener("mg-slow", (e) => onVideoSlow(genTargetRef.current || activeRef.current.c.id, e.detail));
      el.addEventListener("mg-paused", (e) => onVideoPaused(genTargetRef.current || activeRef.current.c.id, e.detail));
      // Durably persists a hand-edit made while typing normally (NOT switching shots or
      // batch-generating -- those paths call flushPromptEdit() directly, see below and the
      // toolbar button). A no-op if the committed text is identical to what auto-compose
      // would already produce (round-tripping back to the composed text shouldn't flip a
      // shot into "override" mode).
      el.addEventListener("mg-prompt-commit", (e) => {
        const a = activeRef.current; if (!a) return;
        const text = e.detail.text;
        const already = !!a.c.promptOverride;
        // SAME RESOLVER AS THE PREFILL (2026-07-27, round 3 -- the drawer-COUPLED
        // shotText family). The drawer's prompt box is prefilled from
        // shotText(active, project, imgSrc) -- the live, thumbs-aware resolver -- and
        // this comparator decides "did the owner actually change anything" by
        // recomposing. Round 2 composed here with NO resolver (mediaId-only), so on any
        // shot carrying a thumb-only picture the two texts differed by construction
        // (the thumb entity is numbered in one and invisible to the other) and every
        // purely-prefilled prompt froze as a hand-edit override -- silent, sticky
        // corruption. All sites that feed the drawer's prompt or compare against it now
        // compose with the same thumbs-aware resolver; copyShot/exportAll are the
        // deliberate standalone exceptions (see their comments).
        // thumbsRef, not the `thumbs` prop: this listener registers once and its closure
        // goes stale -- the exact idiom the mg-pick-request resolve above already uses.
        const resolve = (thumbId, source) => thumbId ? thumbsRef.current[thumbId]
          : (source && (source.startsWith("http") || source.startsWith("data:") || isCatalogMediaId(source)) ? source : null);
        const composed = already ? null : shotText(a, projectRef.current, resolve);
        if (!already && text === composed) return;
        const apply = (c) => setPromptOverride(c, text);
        a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
        promptDirtyRef.current = false;
      });
    }
  }, [openPick, onVideoSubmit, onVideoResult, onVideoError, onVideoSlow, onVideoPaused]);

  // Fixed Timeline drawer: hidden(0) / slim(default, scrubber only) / full(preview above
  // scrubber, real 16:9). The handle drags freely between 0 and TL_HEIGHTS.full, snapping
  // to the nearest named state on release.
  const TL_HEIGHTS = { hidden: 0, slim: 64, full: 442 };
  const tlPointerDown = (e) => { tlDrag.current = { dragging: true, startY: e.clientY, startH: TL_HEIGHTS[tlState], lastH: TL_HEIGHTS[tlState] }; e.currentTarget.setPointerCapture(e.pointerId); };
  const tlPointerMove = (e) => {
    if (!tlDrag.current.dragging) return;
    const h = Math.max(0, Math.min(TL_HEIGHTS.full, tlDrag.current.startH + (e.clientY - tlDrag.current.startY)));
    tlDrag.current.lastH = h;   // read by tlPointerUp -- setTlDragH's state update is batched/async,
    setTlDragH(h);               // so the ref (not the state) is the reliable live value on release.
  };
  const tlPointerUp = () => {
    if (!tlDrag.current.dragging) return;
    tlDrag.current.dragging = false;
    const h = tlDrag.current.lastH;
    let best = "hidden", bestD = Infinity;
    Object.entries(TL_HEIGHTS).forEach(([k, v]) => { const d = Math.abs(v - h); if (d < bestD) { bestD = d; best = k; } });
    setTlState(best); setTlDragH(null);
  };
  const togglePal = (which) => setPalFor((p) => (p === which ? null : which));

  const sel = entries.find((e) => e.c.id === selShot) || null;
  // No shot selected -> operate on the draft card instead (same shape, "__draft__" id).
  // routeTarget is who an Image/Edit/Reference/Video RESULT gets routed/attached into:
  // the selected shot when bound, or whatever's chosen in the draft-mode shot picker.
  const draftEntry = { a: { id: "__draft__" }, c: draftCard, code: "Draft" };
  const active = sel || draftEntry;
  const routeTarget = sel || entries.find((e) => e.c.id === draftTarget) || null;
  const frameSrc = (f) => (f && f.thumbId ? thumbs[f.thumbId] : (f && f.mediaId ? "/thumbs/" + f.mediaId + ".jpg" : null));
  activeRef.current = active;

  // ---- Fixer -- desktop port of LoomMobile's own seventh increment (2026-08-03), itself a
  // verbatim port of gallery/src/components/FixTab.jsx's real, already-shipped box-drawing
  // (same FIX_COLORS/FIX_MIN_PX/FIX_MAX_BOXES/scaleFixBoxes module-scope constants, same
  // paint()/onDown/onMove/onUp math). The real submit path (genFixState/setGenFixState/
  // genFix) already existed on useGenerationPipeline's own return value and was already
  // computed every render in App() -- it just wasn't threaded into this component's props before
  // this fix (2026-08-04, closing the design-fidelity punch list's "Edit tab has no Fixer or
  // Enhance sub-tabs at all" item). No new backend, no new pipeline -- purely wiring +
  // this tab's own canvas UI, same as LoomMobile already proved out.
  const [editSub, setEditSub] = useState("edit");   // 'edit' | 'fixer' | 'enhance'
  const [fixTag, setFixTag] = useState("face");
  const [fixBoxes, setFixBoxes] = useState([]);
  const fixImgRef = useRef(null);
  const fixCanvasRef = useRef(null);
  const fixDragRef = useRef(null);
  const [genFixPrice, setGenFixPrice] = useState({});
  useEffect(() => {
    setFixBoxes([]);
  }, [active && active.c.id, active && active.c.openFrame && active.c.openFrame.mediaId]);
  const fixPaint = useCallback(() => {
    const cvs = fixCanvasRef.current, img = fixImgRef.current;
    if (!cvs || !img) return;
    const w = img.clientWidth, h = img.clientHeight;
    if (!w || !h) return;
    if (cvs.width !== w || cvs.height !== h) { cvs.width = w; cvs.height = h; }
    const ctx = cvs.getContext("2d");
    ctx.clearRect(0, 0, w, h);
    const draw = (b) => {
      ctx.strokeStyle = FIX_COLORS[b.tag] || FIX_COLORS.face;
      ctx.lineWidth = 2;
      ctx.strokeRect(b.x, b.y, b.w, b.h);
      ctx.fillStyle = ctx.strokeStyle;
      ctx.font = "11px system-ui";
      ctx.fillText(b.tag, b.x + 3, b.y + 13);
    };
    fixBoxes.forEach(draw);
    if (fixDragRef.current) draw({ ...fixDragRef.current, tag: fixTag });
  }, [fixBoxes, fixTag]);
  useEffect(() => { fixPaint(); }, [fixPaint]);
  useEffect(() => {
    const onResize = () => fixPaint();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [fixPaint]);
  const fixRel = (e) => {
    const r = fixCanvasRef.current.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  const fixDown = (e) => {
    if (e.button !== 0 || !(active && active.c.openFrame && active.c.openFrame.mediaId)) return;
    const p = fixRel(e);
    fixDragRef.current = { x: p.x, y: p.y, w: 0, h: 0, ox: p.x, oy: p.y };
    e.preventDefault();
  };
  const fixMove = (e) => {
    if (!fixDragRef.current) return;
    const p = fixRel(e);
    const d = fixDragRef.current;
    fixDragRef.current = {
      ...d,
      x: Math.min(d.ox, p.x), y: Math.min(d.oy, p.y),
      w: Math.abs(p.x - d.ox), h: Math.abs(p.y - d.oy),
    };
    fixPaint();
  };
  const fixUp = () => {
    const d = fixDragRef.current;
    fixDragRef.current = null;
    if (!d) return;
    if (d.w > FIX_MIN_PX && d.h > FIX_MIN_PX) {
      if (fixBoxes.length >= FIX_MAX_BOXES) {
        if (window.Toast) {
          window.Toast.show({
            kind: "err", title: "That's the limit",
            msg: "A Fix carries at most " + FIX_MAX_BOXES + " boxes — the rest would be dropped server-side.",
          });
        }
      } else {
        setFixBoxes((old) => old.concat([{ x: d.x, y: d.y, w: d.w, h: d.h, tag: fixTag }]));
      }
    }
    fixPaint();
  };
  // Debounced, read-only /api/price preview -- same shape as LoomMobile's own, mode:"fix"
  // always comes back free:false server-side (a Fix can never be card-covered), matching
  // FixTab.jsx's own cost badge.
  useEffect(() => {
    if (tab !== "Edit" || editSub !== "fixer" || !active) return;
    const id = active.c.id;
    const src = active.c.openFrame && active.c.openFrame.mediaId;
    if (!src || !fixBoxes.length) { setGenFixPrice((s) => ({ ...s, [id]: null })); return; }
    setGenFixPrice((s) => ({ ...s, [id]: { ...(s[id] || {}), loading: true } }));
    let live = true;
    const t = setTimeout(() => {
      fetch("/api/price", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "fix", source: src, boxes: scaleFixBoxes(fixBoxes, fixImgRef.current) }) })
        .then((r) => r.json()).then((pr) => { if (live) setGenFixPrice((s) => ({ ...s, [id]: { loading: false, pr } })); })
        .catch(() => { if (live) setGenFixPrice((s) => ({ ...s, [id]: { loading: false, pr: null } })); });
    }, 250);
    return () => { live = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, editSub, active && active.c.id, active && active.c.openFrame && active.c.openFrame.mediaId, fixBoxes]);

  // ---- Filter compare -- desktop port of LoomMobile's own sixth increment (2026-08-03).
  // Real, shared, offline art-filter library (static/mg-art-filters.js) -- PixAI's own 7
  // gradient-overlay recipes plus this app's own 5, composited entirely client-side (no
  // network call, no credit spend), same AF.groups()/AF.get()/AF.renderSwatch()/
  // AF.applyPreview()/AF.clearPreview() API LoomMobile already uses. Genuinely persists via
  // the same `patch` every other Generate field writes through -- no new endpoint.
  const AF = MgArtFilters;   // was window.MgArtFilters (static/mg-art-filters.js), now bundled
  const [fcOpen, setFcOpen] = useState(false);
  const [fcActive, setFcActive] = useState(null);
  const [fcStrength, setFcStrength] = useState(1);
  const [fcAngle, setFcAngle] = useState(180);
  const fcStageRef = useRef(null);
  const fcImgRef = useRef(null);
  const openFilterCompare = () => {
    if (!active) return;
    setFcActive(active.c.filter || null);
    setFcStrength(active.c.filterStrength != null ? active.c.filterStrength : 1);
    setFcAngle(active.c.filterAngle != null ? active.c.filterAngle : 180);
    setFcOpen(true);
  };
  const closeFilterCompare = () => setFcOpen(false);
  const fcClear = () => { setFcActive(null); patch((cc) => ({ ...cc, filter: null })); };
  const fcSave = () => {
    patch((cc) => ({ ...cc, filter: fcActive, filterStrength: fcStrength, filterAngle: fcAngle }));
    setFcOpen(false);
  };
  useEffect(() => {
    if (!fcOpen || !AF || !fcStageRef.current) return;
    const host = fcStageRef.current;
    AF.clearPreview(host);
    if (fcActive) AF.applyPreview(host, fcActive, { strength: fcStrength, angle: fcAngle });
    return () => { AF.clearPreview(host); };
  }, [fcOpen, fcActive, fcStrength, fcAngle, AF]);

  // D-12 increments 2-4: debounced read-only price checks feeding the three badges declared
  // above. Each depends only on primitives (never the whole active.c / project.assets object),
  // so an unrelated re-render -- a poll tick, another tab's state -- doesn't reset the
  // debounce timer or refire a check nothing actually changed.
  const editSrcMid = active.c.openFrame && active.c.openFrame.mediaId;
  const refMids = (project.assets || []).filter((a) => a.kind === "image" && a.mediaId).map((a) => a.mediaId);
  const refMidsKey = refMids.join(",");
  useEffect(() => {
    const badge = imgCostRef.current;
    if (!badge) return;
    const prompt = (active.c.imgPrompt || "").trim();
    if (!imgModel || !prompt || anyLoraUnresolved(imgLoras)) { badge.clear(); return; }
    // L536: price the SAME body genImage() will actually submit (size/mode/count/seed/etc
    // all affect real PixAI cost) -- imgAdv is safe as a dependency here despite being an
    // object: unlike active.c/project.assets, it's leaf useState that only gets a new
    // reference when a field genuinely changes, never as a side effect of an unrelated re-render.
    const t = setTimeout(() => priceInto(imgCostRef, buildImgGenBody(imgModel, imgLoras, imgAdv, prompt)), 250);
    return () => clearTimeout(t);
  }, [imgModel, imgLoras, imgAdv, active.c.id, active.c.imgPrompt]);
  useEffect(() => {
    const badge = editCostRef.current;
    if (!badge) return;
    const instruction = (active.c.editPrompt || "").trim();
    if (!editSrcMid || !instruction) { badge.clear(); return; }
    const t = setTimeout(() => priceInto(editCostRef, { mode: "edit", source: editSrcMid, instruction, edit_model: "edit-pro" }), 250);
    return () => clearTimeout(t);
  }, [editSrcMid, active.c.id, active.c.editPrompt]);
  useEffect(() => {
    const badge = refCostRef.current;
    if (!badge) return;
    const prompt = (active.c.refPrompt || "").trim();
    if (!refMids.length || !prompt) { badge.clear(); return; }
    const t = setTimeout(() => priceInto(refCostRef, { mode: "edit", source: refMids[0], sources: refMids, instruction: prompt, edit_model: "reference-pro" }), 250);
    return () => clearTimeout(t);
  }, [refMidsKey, active.c.id, active.c.refPrompt]);
  // Duplicate of the Video tabBody's own selIdx/prevEntry below (kept deliberately separate
  // rather than hoisted -- that one lives inside a bare block for frame-handoff, this one
  // feeds a Hook, which can't live inside a block).
  const drawerModeFor = (m) => { const u = (m || "R2V").toUpperCase(); return u === "FLF" ? "flf" : u === "I2V" ? "i2v" : "r2v"; };
  // Inverse of drawerModeFor, but NOT its exact mirror -- the drawer only ever offers 3
  // vmodes, so its 'r2v' can only ever mean the card should become R2V, never V2V. The drawer
  // has no UI concept of "extend/transform an existing clip" (V2V's meaning -- Continuity's
  // "extend" chip already independently covers that idea via c.connect, orthogonal to mode),
  // and at the real submit layer V2V/R2V already resolve to the identical generation code
  // path (build_shot_video_params), so mapping Multi-Reference to R2V loses nothing.
  const cardModeForVmode = (v) => v === "flf" ? "FLF" : v === "i2v" ? "I2V" : "R2V";
  const weaveSelIdx = sel ? entries.findIndex((e) => e.c.id === sel.c.id) : -1;
  const weavePrevEntry = weaveSelIdx > 0 ? entries[weaveSelIdx - 1] : null;
  // imgSrc mirrors useGenerationPipeline's own private helper exactly (thumbs is a prop
  // here too) -- needed to call buildShotPayload directly from this scope.
  const imgSrc = (thumbId, source) => thumbId ? thumbs[thumbId]
    : (source && (source.startsWith("http") || source.startsWith("data:") || isCatalogMediaId(source)) ? source : null);
  
  // An imported file's `local_<hex>` id has a thumbnail at the SAME /thumbs/<id>.jpg
  // route a PixAI id does -- the numeric test used to send the raw id as the <img src>.
  const asRef = (d) => ({ media_id: d, thumb: isCatalogMediaId(d) ? ("/thumbs/" + d + ".jpg") : d });
  // ---- mode families for the Cast & assets panel and Deep Focus live tags (2026-07-27,
  // round 3). Which modes actually SEND the cast/ref image bank with a generation:
  // R2V/V2V take the full reference bank (the server resolves both through the same
  // build_shot_video_params path); an FLF generation consumes ONLY the two frames and an
  // I2V generation ONLY the opening frame -- cast/refs are never attached there. Derived
  // from usesCloseFrame/CLOSE_FRAME_MODES plus the mode itself, NEVER a second mode
  // table (the two-numbering-systems corruption loom-core.js catalogs began as exactly
  // that kind of independent second table). Round 2 shipped the budget line and live-tag
  // tooltips mode-BLIND: an I2V shot's panel asserted two cast members were "sent" while
  // its generation sends the opening frame alone -- refuted in adversarial review.
  //
  // The live @imageN itself stays visible in EVERY mode on purpose: shotText() cites
  // cast/refs by position regardless of mode (its "Keep consistent:"/"Other references:"
  // blocks are mode-independent), so the number is real -- it is the composed prompt's
  // citation. What is mode-dependent is the CLAIM around it: in R2V/V2V it is also what
  // the generator attaches; in FLF/I2V it is citation numbering only, so the
  // label/tooltip below say "not cited" rather than "not sent" for a past-budget row
  // there (nothing cast-shaped is sent in those modes either way) and never claim
  // send-ness for a numbered one.
  const modeSendsRefs = (m) => usesCloseFrame(m) && m !== "FLF";
  // One wording source shared by the budget-line replacement, the detailed cast rows,
  // the Simple grid AND Deep Focus's ref rows -- shared precisely so the surfaces cannot
  // drift apart again (round 2 gave cast rows the live tag and left Deep Focus's ref
  // rows showing only the stale stored tag).
  const modeSendsLine = (m) => (m === "FLF"
    ? "First & Last sends the start & end frames only — cast & refs here are for continuity/notes, not references"
    : "I2V sends the opening frame only — cast here is for continuity/notes, not references");
  const liveTagText = (liveTag, pastBudget, mode) =>
    liveTag || (pastBudget ? (modeSendsRefs(mode) ? "not sent" : "not cited") : "—");
  const liveTagTitle = (liveTag, pastBudget, mode, code) => {
    const framesOnly = mode === "FLF" ? "First & Last sends only the start/end frames" : "I2V sends only the opening frame";
    if (liveTag) {
      return modeSendsRefs(mode)
        ? `Live slot in ${code} — numbered by position; this is what the composed prompt and the generator actually send, not the stored tag on the left`
        : `${code}'s composed-prompt citation — numbered by position. ${framesOnly}, so this picture is NOT attached to the generation; the number is only what the prompt text cites`;
    }
    if (pastBudget) {
      return modeSendsRefs(mode)
        ? `Past the reference limit for ${code} (6 images minus attached frames) — not sent`
        : `Past the citation limit for ${code} (6 images minus attached frames) — left out of the composed prompt. ${framesOnly}; cast/ref pictures are not attached either way`;
    }
    return `No picture resolved on ${code} — nothing to number`;
  };
  // Feed the shot's structured fields into the mounted <mg-generate-drawer> whenever they
  // change -- mode/duration/audio/quality sync unconditionally (structural, not a "hand-edit"
  // concern); the composed PROMPT only re-syncs while the owner hasn't typed in the drawer's
  // own prompt box since the last sync (promptDirtyRef, set by the mg-dirty event).
  //
  // R2V's image/video banks are seeded from buildShotPayload -- the SAME tag-sorted
  // composition shotText()'s "@imageN"/"Keep consistent" lines are written against. This is
  // load-bearing, not a convenience: the composed prompt cites @image1/@image2/... by
  // POSITION, and the drawer renumbers whatever sits in its own slots by position too: if the
  // banks were left for the owner to fill by hand, in any order other than this exact one, a
  // citation like "maintain exact appearance from @image1" would silently bind to whatever
  // unrelated image happened to land in slot 1 -- wrong output with no error, not just a
  // missing one. (Audio refs were never part of buildShotPayload's composition, before or
  // now -- that gap is pre-existing, not introduced here.) Continuity "extend" still adds the
  // previous shot's clip as an extra video ref, on top of whatever the shot's own refs supply.
  useEffect(() => {
    const el = genDrawerRef.current;
    if (!el || tab !== "Video") return;
    if (lastActiveIdRef.current !== active.c.id) {
      // Flush a pending (not-yet-debounced) hand-edit on the OUTGOING shot before this
      // effect overwrites the drawer with the newly-active shot's content -- otherwise an
      // edit landing inside the drawer's 300ms commit debounce right as the owner switches
      // shots is silently discarded (never gets the chance to fire its own mg-prompt-commit).
      if (lastActiveIdRef.current) {
        const pending = el.flushPromptEdit();
        if (pending != null) {
          const outId = lastActiveIdRef.current, isDraft = outId === "__draft__";
          const outEntry = isDraft ? { a: { id: "__draft__" }, c: draftCard, code: "Draft" } : entries.find((e) => e.c.id === outId);
          if (outEntry) {
            const already = !!outEntry.c.promptOverride;
            // imgSrc: drawer-COUPLED comparator -- the pending text being flushed was
            // seeded from an imgSrc composition (payload.prompt below), so comparing it
            // against a noImgSrc recompose froze every thumb-carrying prefilled prompt
            // as an override. See the mg-prompt-commit handler's comment for the family.
            const composed = already ? null : shotText(outEntry, project, imgSrc);
            if (already || pending !== composed) {
              const apply = (c) => setPromptOverride(c, pending);
              isDraft ? setDraftCard(apply) : setCard(outEntry.a.id, outId, apply);
            }
          }
        }
      }
      promptDirtyRef.current = false;
      lastActiveIdRef.current = active.c.id;
    }
    const nextMode = drawerModeFor(active.c.mode);
    // images/video_refs/audio_ref are ALWAYS set explicitly below, even to an empty array/
    // null, never left out of the payload -- prefill()/setRefs() treat "key omitted" as
    // "no opinion, leave whatever's there" but an explicit empty value as "clear it." A
    // shot with zero refs used to leave the PREVIOUS shot's images/video/audio sitting in
    // the drawer, unnoticed, ready to submit against the wrong shot. Found 2026-07-18
    // live-testing (switching from a shot with an @image1 cast ref to an empty draft kept
    // showing that same @image1 in the drawer).
    const payload = {
      mode: nextMode, duration: active.c.duration, audio: !!active.c.audioGen,
      audio_language: active.c.audioLanguage || "english",
      quality: project.draft ? "basic" : "professional",
      images: [], video_refs: [], audio_ref: null,
    };
    if (nextMode === "i2v" && active.c.openFrame && active.c.openFrame.mediaId) {
      payload.images = [{ media_id: active.c.openFrame.mediaId, thumb: frameSrc(active.c.openFrame) }];
    } else if (nextMode === "flf") {
      // POSITIONAL, NULLS PRESERVED -- always [Start-or-null, End-or-null], never a
      // filtered list (2026-07-27, round 3). Round 2 built this with
      // `.filter((f) => f && f.mediaId)`, and the drawer's flf branch maps its list
      // positionally (images[0] -> Start box, images[1] -> End box) -- so an flf shot
      // whose END frame was picked first (start still empty) shipped images=[close] and
      // the drawer put the intended END frame in the START box. Generate then spent real
      // credits rendering FROM the end frame; both round-2 reviewers reproduced it. An
      // empty frame now travels as an explicit null (the drawer clears that slot), so the
      // list's SHAPE can never encode less than its POSITIONS again. Contained: this is
      // the only producer that puts nulls in `images`, it always states mode:'flf' in the
      // same payload, and the drawer's flf branch is the only consumer that sees it
      // (prefill() routes a mode:'flf' list of <=2 there unconditionally).
      //
      // resolvedImage(), not the round-2 `f.mediaId` test: a locally-uploaded frame
      // (thumbId only, no gallery mediaId yet) resolves to its data-URL through imgSrc,
      // the exact shape the r2v branch below already ships for cast thumbs via
      // buildShotPayload()/asRef() -- and the server's resolve_img()
      // (moonglade_gallery.py, /api/loom/generate) base64-uploads a `data:` URL for
      // EVERY mode, flf included (verified against that route before wiring this). So a
      // thumb-only frame the card numbers @image1/@image2 is genuinely sendable
      // end-to-end here, instead of silently never reaching the drawer at all.
      payload.images = [active.c.openFrame, active.c.closeFrame]
        .map((f) => { const d = resolvedImage(f, imgSrc); return d ? asRef(d) : null; });
    } else if (nextMode === "r2v") {
      const sp = buildShotPayload(active, project, imgSrc);
      payload.images = sp.images.map(asRef);
      const vids = (sp.video_refs || []).map(asRef);
      if (active.c.connect === "extend" && weavePrevEntry && weavePrevEntry.c.resultMid) {
        vids.push({ media_id: weavePrevEntry.c.resultMid, thumb: "/thumbs/" + weavePrevEntry.c.resultMid + ".jpg" });
      }
      payload.video_refs = vids;
    }
    // imgSrc (2026-07-27, round 3): the prompt must cite the SAME numbering as the bank
    // this effect just built -- buildShotPayload above composes the bank thumbs-aware,
    // while round 2 composed this prompt with NO resolver (mediaId-only). A thumb-only
    // frame or cast picture was therefore IN the bank but INVISIBLE to the prompt's
    // numbering, and every citation after it was off by one (reproduced in review: bank
    // held frame=@image1, Nelnamara=@image2; the prompt cited "Nelnamara — reference
    // @image1"). Drawer-COUPLED shotText family -- every site that feeds this drawer's
    // prompt or compares against it composes with imgSrc; the comparators are at
    // mg-prompt-commit, the outgoing-shot flush above, the re-sync button and the
    // Generate-all flush. copyShot/exportAll are the deliberate standalone exceptions.
    if (!promptDirtyRef.current) payload.prompt = shotText(active, project, imgSrc);
    el.prefill(payload);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active.c.id, active.c.mode, active.c.connect, active.c.duration, active.c.audioGen, active.c.audioLanguage,
      active.c.prompt, active.c.camera, active.c.lighting, active.c.transIn, active.c.transOut,
      active.c.cast, active.c.refs, project.assets,
      // The FRAMES' IDENTITY fields (2026-07-27, closing-frame pass). Every branch above
      // reads c.openFrame/c.closeFrame -- i2v/flf feed them to the drawer directly, r2v
      // through buildShotPayload() -- yet no frame field was a dependency, so attaching or
      // replacing a frame never re-ran this effect: the drawer kept showing (and PRICING,
      // and submitting) the bank from before the change, until some unrelated dep -- `tab`,
      // usually -- happened to fire it. That is the owner's "toggling a tab fixes the
      // missing frame" symptom, and the worse, quieter one behind it: mg-pick-request
      // resolves a picked slot INDEX against the fresh list (pickTarget) while the drawer
      // reported the pick against its stale bank, so a pick could replace a different
      // entity than the one the owner clicked (the reference-picker corruption class).
      // Identity fields, not the frame OBJECTS, on purpose: FrameSlot's desc/tag inputs
      // patch a fresh frame object per keystroke, and a re-prefill per keystroke of text
      // that cannot change which image is attached is churn this carefully-scoped effect
      // exists to avoid. mediaId/thumbId/source are exactly the fields shotImageRefs()
      // resolves an image from (resolvedImage in loom-core.js), so these six scalars fire
      // precisely when a frame's PICTURE changes and never otherwise.
      (active.c.openFrame || {}).mediaId, (active.c.openFrame || {}).thumbId, (active.c.openFrame || {}).source,
      (active.c.closeFrame || {}).mediaId, (active.c.closeFrame || {}).thumbId, (active.c.closeFrame || {}).source,
      active.c.title, project.look, project.draft, tab,
      active.c.promptOverride, active.c.promptOverrideText]);
  // Isolated, narrow busy-guard effect -- deliberately NOT folded into the big prefill
  // effect above (which re-runs the FULL prefill on any of a dozen fields and does not
  // track active.c.status at all). This one keys ONLY on id+status so a shot flipping
  // wip/done/error re-fires it without re-running mode/image/prompt resync, and setBusy()
  // itself no-ops while the drawer's own submit is what's driving the button (see
  // mg-generate-drawer.js). Closes the double-submit gap where a batch run (or a resumed
  // poll) marks the active shot "wip" but the drawer's own Go button stayed clickable.
  // "paused" carve-out (2026-07-18(pm)): a give-up-timer ceiling leaves status:"wip" but
  // frees the drawer's own Go button (see mg-generate-drawer.js's _poll pause()) -- without
  // this, reselecting a paused shot re-evaluates status==="wip" (still true by design) and
  // silently re-disables the Go button the drawer just freed, with no visible reason why
  // (found in review).
  useEffect(() => {
    const gs = genState[active.c.id];
    const stillBusy = active.c.status === "wip" && !(gs && gs.phase === "paused");
    const el = genDrawerRef.current;
    if (el && el.setBusy) el.setBusy(stillBusy);
  }, [active.c.id, active.c.status, genState[active.c.id] && genState[active.c.id].phase]);
  const board = (
    <div className="lv-board">
      {project.acts.map((act, ai) => {
        const items = entries.filter((e) => e.ai === ai);
        return (
          <div key={act.id} className="lv-act">
            <div className="lv-actrow">
              <input className="lv-actname-in" value={act.name} onChange={(ev) => setAct(act.id, { name: ev.target.value })} aria-label="Act name" />
              <button className="lv-ico" onClick={() => moveAct(ai, -1)} title="Move act up">&#8593;</button>
              <button className="lv-ico" onClick={() => moveAct(ai, 1)} title="Move act down">&#8595;</button>
              <button className="lv-ico danger" onClick={() => delAct(act.id)} title="Delete act">&#10005;</button>
            </div>
            <div className="lv-cards">
              {items.map((e) => {
                const gs = genState[e.c.id];
                // "paused" is its own visual state (auto-checking genuinely stopped);
                // running/slow/stale/submitting all still just read as the ordinary amber
                // "wip" look -- the escalating MESSAGE is the signal (gs.msg above), not a
                // color change, so a slow shot never looks alarming but also never looks
                // silently identical to a normal render. Clicking the badge while paused
                // re-polls the same pendingTaskId fresh -- the manual-recheck counterpart to
                // the reload-time resume effect.
                const paused = gs && gs.phase === "paused";
                const st = paused ? "paused" : (gs && gs.phase && gs.phase !== "done" && gs.phase !== "error" ? "wip" : e.c.status);
                // Continuity indicator (frameLinked, via continuityLinked in loom-core.js):
                // does this shot's OPENING frame already match the immediately-preceding
                // shot's CLOSING frame (checked across the GLOBAL `entries` list, same
                // cross-act "previous shot" convention the frame-handoff button already uses
                // below -- see prevEntry/weavePrevEntry). Rendered only when true: a quiet
                // affirmation, not a "you forgot this" warning -- most shots are deliberately
                // connect:"new" (an intentional fresh look/place, per CONNECT.new's own hint),
                // so a non-matching frame is usually the shot's INTENT, not a mistake to flag.
                const linked = continuityLinked(entries, e.c.id);
                return (
                  <div key={e.c.id} className={"lv-card " + (e.c.id === selShot ? "sel" : "")} onClick={() => setSelShot(e.c.id)}
                    onDoubleClick={() => setDeepFocus(e)} title="Double-click to open in Deep Focus">
                    <div className="lv-cframe">{(() => { const s = frameSrc(e.c.openFrame) || (e.c.resultMid ? "/thumbs/" + e.c.resultMid + ".jpg" : null); return s ? <img src={s} alt="" /> : <span className="lv-cframeph">{e.c.mode}</span>; })()}</div>
                    <div className="lv-code">{e.code}</div>
                    <div className="lv-ctitle">{e.c.title || "untitled"}</div>
                    <div className="lv-cmeta"><span className="lv-mode">{e.c.mode}</span><span className="lv-dur">{durOf(e.c)}s</span>
                      {/* A cast member on this shot with no picture for it. shotText() leaves
                          them out of the prompt rather than citing an @imageN with nothing
                          behind it, so this is what keeps that from being silent. Two chips
                          because they are two different repairs (2026-07-27): "no image"
                          means attach a picture; "past the reference limit" means the
                          picture is fine but PixAI's 6-image cap (frames first) trimmed it
                          -- drop a reference or a frame to fit. Calling the second "no
                          image" was the lie castMissingImages()'s own comment documents;
                          castPastBudget() is its honest counterpart. */}
                      {(() => {
                        const miss = castMissingImages(e, project, imgSrc);
                        const over = castPastBudget(e, project, imgSrc);
                        return <>
                          {miss.length ? (
                            <span className="lv-st warn"
                              title={`No picture on this shot for ${miss.join(", ")} — they are cast here but cannot be referenced, so they are left out of the prompt. Add an image to use them.`}>
                              {miss.length === 1 ? `${miss[0]}: no image` : `${miss.length} cast: no image`}
                            </span>
                          ) : null}
                          {over.length ? (
                            /* Same mode split as liveTagText/liveTagTitle (round 3): "not
                               sent" is a reference-slot claim and only R2V/V2V send
                               reference slots. On FLF/I2V the trim is real but it trims the
                               prompt's CITATION list, not a payload -- nothing cast-shaped
                               was going to be sent either way, and a chip asserting
                               send-ness there is the round-2 mode-blindness bug wearing a
                               different hat. */
                            <span className="lv-st oob"
                              title={modeSendsRefs(e.c.mode)
                                ? `Past the reference limit — not sent. PixAI takes 6 reference images and attached frames claim theirs first, so ${over.join(", ")} ${over.length === 1 ? "does" : "do"} not fit this shot. Remove a frame or another reference to include ${over.length === 1 ? "them" : "them all"}.`
                                : `Past the citation limit — not cited. The composed prompt numbers at most 6 pictures (frames first), so ${over.join(", ")} ${over.length === 1 ? "gets" : "get"} no @imageN here. In ${e.c.mode} only the frame${e.c.mode === "FLF" ? "s are" : " is"} sent either way.`}>
                              {over.length === 1
                                ? `${over[0]}: past ref limit — ${modeSendsRefs(e.c.mode) ? "not sent" : "not cited"}`
                                : `${over.length} cast past ref limit — ${modeSendsRefs(e.c.mode) ? "not sent" : "not cited"}`}
                            </span>
                          ) : null}
                        </>;
                      })()}
                      {linked && <span className="lv-st linked" title="Opening frame matches the previous shot's closing frame — continuous across the cut">linked</span>}
                      {e.c.imported && <span className="lv-st imported" title="Imported from your gallery -- no PixAI task backs this clip, so re-roll has nothing to redo">imported</span>}
                      <span className={"lv-st " + st}
                        onClick={paused ? (ev) => { ev.stopPropagation(); pollShot(e.c.id, e.c.pendingTaskId); } : undefined}
                        style={paused ? { cursor: "pointer" } : undefined}
                        title={paused ? "Click to check again" : undefined}>
                        {gs && gs.msg ? gs.msg : st}</span></div>
                    <div className="lv-crow" onClick={(ev) => ev.stopPropagation()} onDoubleClick={(ev) => ev.stopPropagation()}>
                      <button className="lv-ico xs" onClick={() => moveCard(act.id, e.ci, -1)} title="Move up">&#8593;</button>
                      <button className="lv-ico xs" onClick={() => moveCard(act.id, e.ci, 1)} title="Move down">&#8595;</button>
                      <button className="lv-ico xs" onClick={() => dupCard(act.id, e.c)} title="Duplicate">&#10697;</button>
                      {/* Confirmed, like every other destructive action here. A shot card holds
                          a prompt, its cast, its frames and any generated result, and the ✕ sits
                          between Duplicate and a dropdown -- there was no dialog and no undo. */}
                      <button className="lv-ico xs danger" title="Delete"
                        onClick={() => { if (window.confirm(`Delete shot ${e.code}${e.c.title ? ` — "${e.c.title}"` : ""}? This can't be undone.`)) delCard(act.id, e.c); }}>&#10005;</button>
                      {project.acts.length > 1 && (
                        <select className="lv-actsel" value="" title="Move to another act"
                          onChange={(ev) => ev.target.value && moveCardToAct(act.id, e.c, ev.target.value)}>
                          <option value="">move to&hellip;</option>
                          {project.acts.filter((a) => a.id !== act.id).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                        </select>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
            <button className="lv-mini2" onClick={() => addCard(act.id)}>+ Add shot to {act.name}</button>
          </div>
        );
      })}
      <button className="lv-mini2" onClick={addAct}>+ New act</button>
      {!project.acts.length && <div className="lv-ph">No acts yet — add one below.</div>}
    </div>
  );
  // Fixed drawer, banner-attached, never draggable (unlike every other region). Preview
  // only renders once the drawer is more than halfway to full, so it doesn't paint fighting
  // the collapse/expand animation.
  const tlHeight = tlDragH != null ? tlDragH : TL_HEIGHTS[tlState];
  const showTlPreview = tlHeight > (TL_HEIGHTS.slim + TL_HEIGHTS.full) / 2;
  const timelineDrawer = (
    <div className="lv-tldrawer">
      <div className="lv-tlcontent" style={{ height: tlHeight, transition: tlDragH != null ? "none" : "height .28s cubic-bezier(.2,.8,.2,1)" }}>
        {showTlPreview && (
          <div className="lv-tlpreviewzone">
            {sel && sel.c.resultMid
              // key={sel.c.id}: without it, switching between two finished shots on the
              // reel reuses the same instance -- swapping `mid` on a live <video> silently
              // pauses it (no pause event fires), leaving `playing` state stuck true (button
              // stuck on the pause icon, hover-scrub disabled) and `dur` stale until the new
              // clip's metadata loads. Forcing a remount resets all of that for free.
              ? <ShotPreview key={sel.c.id} mid={sel.c.resultMid} trimIn={sel.c.trimIn} trimOut={sel.c.trimOut}
                  onTrim={(i, o) => setCard(sel.a.id, sel.c.id, (c) => ({ ...c, trimIn: i, trimOut: o }))}
                  onSplit={(t) => splitShot(sel, t)}
                  crop={sel.c.crop} onCrop={(rect) => setCard(sel.a.id, sel.c.id, (c) => ({ ...c, crop: rect }))} />
              : <div className="lv-tlpreviewbox lv-ph">{sel ? "This shot hasn't rendered yet." : "Select a shot to preview it here."}</div>}
          </div>
        )}
        <div className="lv-tlreelzone">
          <div className="lv-reel">
            {/* The Loom.dc.html:906-914 -- per-shot tint (LV_TINTS, distinct from status
                color), the diagonal-stripe texture overlay, the shot's code+duration as
                VISIBLE text (not just the title tooltip, which stays too), and a separate
                thin status bar under the tint instead of the status color filling the
                whole segment. Duration-proportional width, selected outline, and the
                drag-resize grip (elsewhere in this file) are unchanged -- those already
                matched or exceeded the design. */}
            {entries.map((x, i) => {
              const tint = LV_TINTS[(x.ai * 3 + x.ci) % LV_TINTS.length];
              return (
                <div key={i} className={"lv-seg" + (x.c.id === selShot ? " sel" : "")}
                  style={{
                    width: `${(durOf(x.c) / scale) * 100}%`,
                    backgroundImage: `repeating-linear-gradient(90deg, rgba(0,0,0,.32) 0px, rgba(0,0,0,.32) 1px, transparent 1px, transparent 25px), ${tint}`,
                    backgroundSize: "25px 100%, 25px 100%", backgroundRepeat: "repeat-x, repeat-x",
                  }}
                  title={`${x.code} ${x.c.title || ""}`} onClick={() => setSelShot(x.c.id)}>
                  <span className="lv-segcode">{x.code} · {durOf(x.c)}s</span>
                  <span className={"lv-segbar " + x.c.status} />
                </div>
              );
            })}
            <div className="lv-target" style={{ left: `${(project.target / scale) * 100}%` }} />
          </div>
          <div className="lv-tlinfo">{sel
            ? <span><b>{sel.code}</b> &middot; {sel.c.title || "untitled"} &middot; {sel.c.mode} &middot; {durOf(sel.c)}s</span>
            : <span className="lv-dim">click a shot to select it — the whole workspace binds to it</span>}</div>
        </div>
      </div>
      <div className="lv-tlhandle" onPointerDown={tlPointerDown} onPointerMove={tlPointerMove} onPointerUp={tlPointerUp} onPointerCancel={tlPointerUp}>
        <div className="lv-tlgrip" />
      </div>
    </div>
  );
  // Collapsed Generate: the right-edge icon rail ("gallery-drawer muscle memory") —
  // clicking an icon expands the drawer back out AND switches to that tab.
  const GEN_ICONS = [["Image", "✦"], ["Edit", "✎"], ["Reference", "🖼"], ["Video", "🎬"]];
  let gen;
  {
    const gs = genState[active.c.id];
    // "paused" no longer counts as busy -- the auto-poll has genuinely stopped, so a manual
    // "use existing video" attach isn't racing a live network call anymore. running/slow/
    // stale (still actively polling) still block it, same as before.
    const busy = gs && gs.phase && gs.phase !== "done" && gs.phase !== "error" && gs.phase !== "paused";
    // Writes into the selected shot when bound, or the draft card when not -- everything
    // below (tab bodies, frame slots) reads/writes through this one function either way.
    const patch = (fn) => { if (sel) setCard(sel.a.id, sel.c.id, fn); else setDraftCard(fn); };
    const appendTo = (field, term) => patch((c) => ({ ...c, [field]: c[field] ? c[field] + ", " + term : term }));
    // Frame handoff (reparented from the classic CardEditor): open/close frame, same
    // splice-in-last-frame / inherit-close mechanics, driven by the same setCard.
    // "Previous shot" is a board-sequence concept -- a draft isn't on the board, so it
    // has none (selIdx stays -1, prevEntry stays null) rather than pretending otherwise.
    const selIdx = sel ? entries.findIndex((e) => e.c.id === sel.c.id) : -1;
    const prevEntry = selIdx > 0 ? entries[selIdx - 1] : null;
    const patchFrame = (key, fp) => patch((c) => ({ ...c, [key]: { ...c[key], ...fp } }));
    const inheritPrev = () => {
      if (!prevEntry) return;
      const rmid = prevEntry.c.resultMid;
      if (rmid) {
        setHandoff("wip");
        fetch("/api/loom/handoff", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_media_id: rmid, trim_out: prevEntry.c.trimOut }) })
          .then((r) => r.json()).then((d) => {
            if (d.error || !d.frame_media_id) { setHandoff("err"); return; }
            setHandoff("");
            patchFrame("openFrame", { mediaId: d.frame_media_id, thumbId: "", source: "",
              desc: "handed off from " + (prevEntry.code || "prev shot") });
          }).catch(() => setHandoff("err"));
      } else {
        patchFrame("openFrame", { ...prevEntry.c.closeFrame });
      }
    };
    let tabBody;
    // <mg-generate-drawer> itself is NOT part of tabBody -- it's rendered once, always
    // mounted, right below {tabBody} at the render site, and only CSS-hidden on other
    // tabs. It used to live inside this Video-only branch, which meant switching tabs
    // while a shot rendered unmounted the element and killed its in-flight poll outright
    // (drawer.js disconnectedCallback clears the poll timer) -- the shot got stuck "wip"
    // forever with no way to recover short of a full reload. videoTrailer holds the small
    // bit of Video-tab UI that sits AFTER the drawer in the layout (no internal state of
    // its own, safe to unmount/remount like every other tab) so the visual order is
    // preserved once the drawer moves out. Found + fixed 2026-07-18 live-testing.
    let videoTrailer = null;
    if (tab === "Video") { tabBody = (
      <div>
        <label className="lv-lab">Continuity</label>
        <div className="lv-chips">{Object.keys(CONNECT).map((k) => (<span key={k} className={"lv-chip " + (k === (active.c.connect || "new") ? "on" : "")} title={CONNECT[k].hint}
          onClick={() => patch((c) => setShotConnect(c, k))}>{CONNECT[k].label}</span>))}</div>
        <label className="lv-lab">Prompt</label>
        <textarea className="lv-ta" value={active.c.prompt || ""} onChange={(ev) => {
          // Typing here always means "auto-compose, using this text" -- clears an active
          // override immediately (matches the drawer's own "your edit wins" rule, just
          // from the other surface). Destructive with no undo, same as every other text
          // field here, but silent-until-you-notice is the actual hazard (found in review):
          // flash a brief, self-clearing notice at the moment it happens.
          if (active.c.promptOverride) { setOverrideClearedFlash(true); setTimeout(() => setOverrideClearedFlash(false), 1600); }
          patch((c) => ({ ...clearPromptOverride(c), prompt: ev.target.value }));
        }} />
        <label className="lv-lab">Camera <button className="lv-termsbtn" onClick={() => togglePal("camera")}>+ terms</button></label>
        <input className="lv-in" value={active.c.camera || ""} placeholder="e.g. slow push in, shallow DoF" onChange={(ev) => patch((c) => ({ ...c, camera: ev.target.value }))} />
        {palFor === "camera" && (
          <div className="lv-termspal">{Object.entries(CAM_PALETTE).map(([grp, items]) => (
            <div key={grp} className="lv-termsgrp">
              <div className="lv-termsgrpt">{grp}</div>
              {items.map((t) => (<span key={t} className="lv-minichip" onClick={() => appendTo("camera", t)}>{t}</span>))}
            </div>
          ))}</div>
        )}
        <label className="lv-lab">Lighting <button className="lv-termsbtn" onClick={() => togglePal("lighting")}>+ terms</button></label>
        <input className="lv-in" value={active.c.lighting || ""} placeholder="e.g. moonlit, soft haze" onChange={(ev) => patch((c) => ({ ...c, lighting: ev.target.value }))} />
        {palFor === "lighting" && (
          <div className="lv-termspal">{LIGHTING_PALETTE.map((t) => (<span key={t} className="lv-minichip" onClick={() => appendTo("lighting", t)}>{t}</span>))}</div>
        )}
        <label className="lv-lab">Transition in <button className="lv-termsbtn" onClick={() => togglePal("transIn")}>+ terms</button></label>
        <input className="lv-in" value={active.c.transIn || ""} placeholder="e.g. cut, dissolve" onChange={(ev) => patch((c) => ({ ...c, transIn: ev.target.value }))} />
        {palFor === "transIn" && (
          <div className="lv-termspal">{TRANS_PALETTE.map((t) => (<span key={t} className="lv-minichip" onClick={() => patch((c) => ({ ...c, transIn: t }))}>{t}</span>))}</div>
        )}
        <label className="lv-lab">Transition out <button className="lv-termsbtn" onClick={() => togglePal("transOut")}>+ terms</button></label>
        <input className="lv-in" value={active.c.transOut || ""} placeholder="e.g. cut, dissolve" onChange={(ev) => patch((c) => ({ ...c, transOut: ev.target.value }))} />
        {palFor === "transOut" && (
          <div className="lv-termspal">{TRANS_PALETTE.map((t) => (<span key={t} className="lv-minichip" onClick={() => patch((c) => ({ ...c, transOut: t }))}>{t}</span>))}</div>
        )}
        <div className="lv-refline">{(active.c.cast || []).length} cast &middot; {(active.c.refs || []).length} refs <span className="lv-dim">(toggle cast in the Cast &amp; assets tab; add extra image/video/audio refs directly below)</span></div>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", margin: "10px 0 2px" }}>
          {active.c.promptOverride
            ? <span className="lv-dim lv-override-badge" title="Hand-edited override -- Camera/Lighting/cast/notes above are NOT composed into it. Re-sync to go back to auto-compose.">&#9998; override active &mdash; fields above not woven in</span>
            : <span className="lv-dim">&#8595; woven into the form below</span>}
          <button className="lv-mini2" onClick={() => {
            promptDirtyRef.current = false;
            // Compute the composed text from a LOCALLY patched copy, not the async
            // setCard/setDraftCard queued just below -- reading shotText(active, project)
            // straight after queuing that update would still see the old promptOverride:true
            // and return stale (override) text, since the queued state write hasn't
            // committed yet at this point in the same synchronous handler.
            // imgSrc: this text goes straight INTO the drawer (prefill below), so it is
            // drawer-COUPLED and must carry the same thumbs-aware numbering the prefill
            // effect composes with -- see that effect's payload.prompt comment.
            const composed = shotText({ ...active, c: { ...active.c, promptOverride: false } }, project, imgSrc);
            active.c.id === "__draft__" ? setDraftCard(clearPromptOverride) : setCard(active.a.id, active.c.id, clearPromptOverride);
            if (genDrawerRef.current) genDrawerRef.current.prefill({ prompt: composed });
          }}>&#8634; re-sync from shot</button>
        </div>
        {overrideClearedFlash && <div className="lv-overrideflash">override cleared &mdash; back to auto-compose</div>}
      </div>
    );
    videoTrailer = (
      <>
        {sel && <button className="lv-usevid" disabled={busy} onClick={() => useExistingVideo(sel)} title="Skip generation -- use a video you already have in your gallery as this shot's clip">
          &#128190; Use an existing video instead
        </button>}
        {!sel && gs && gs.mid && (
          <div className="lv-imgresult">
            <img src={"/thumbs/" + gs.mid + ".jpg"} alt="result" />
            <div className="lv-route"><span className="lv-dim">attach to shot &#8594;</span>
              <button className="lv-routebtn" disabled={!routeTarget} onClick={() => {
                if (!routeTarget) return;
                setCard(routeTarget.a.id, routeTarget.c.id, (x) => ({ ...x, status: "done", resultMid: gs.mid, trimIn: 0, trimOut: null, ...(gs.duration ? { actualDur: gs.duration } : {}) }));
                setDraftAttachedInfo({ mid: gs.mid, code: routeTarget.code });
              }}>{routeTarget ? `attach to ${routeTarget.code}` : "choose a shot above"}</button>
            </div>
            {draftAttachedInfo && draftAttachedInfo.mid === gs.mid && <div className="lv-ok2">&#10003; attached to {draftAttachedInfo.code} &middot; it's now that shot's result</div>}
          </div>
        )}
      </>
    ); }
    else if (tab === "Image") {
      const gi = genImgState[active.c.id] || {};
      const busyI = gi.phase === "submitting" || gi.phase === "running";
      tabBody = (
        <div>
          <label className="lv-lab">Model</label>
          {/* picker-parity-round2 (problem 2): a trigger row, not an inline-mounted picker --
              mirrors moonglade_gallery.py's own #gen-selrow. The actual <mg-model-picker
              kind="base"> lives in the always-mounted .lv-mpick-veil overlay below (outside
              this tab-conditional block, next to <mg-generate-drawer>), matching that
              element's own "survive tab switches, CSS-hide instead of unmount" contract. */}
          <button type="button" className="lv-selrow" onClick={() => { setPickerKind("base"); setPickerOpen(true); }}>
            {imgModel && imgModel.preview_url ? <img className="lv-selthumb" src={imgModel.preview_url} alt="" /> : null}
            <span className="lv-selname">{imgModel ? imgModel.title : "none — browse models"}</span>
            <span className="lv-dim lv-selhint">☰ browse</span>
          </button>
          {/* problem 5: sampling_method/capabilities were resolved by onBasePick above and
              discarded -- read-only surfacing (not a submit field, see the Gallery's own
              identical applyModelDefaults() comment for why sampling_method stays display-only). */}
          {imgModel && (imgModel.sampling_method || (imgModel.capabilities || []).length > 0) && (
            <div className="lv-caps">
              {imgModel.sampling_method ? <span className="lv-cap method">{imgModel.sampling_method}</span> : null}
              {(imgModel.capabilities || []).map((c) => <span key={c} className="lv-cap">{c}</span>)}
            </div>
          )}
          {/* problem 4: a real version choice (PixAI's own model/LoRA cards have one; ours
              had none) -- only shown once there's actually more than one release to choose
              from. */}
          {imgModel && imgModel.versions && imgModel.versions.length > 1 && (
            <select className="lv-in lv-versel" value={imgModel.version_id || ""} onChange={(ev) => pickVersion(ev.target.value)}
              title="This model's published releases -- PixAI defaults to the latest; pick another to generate against it instead" aria-label="Model version">
              {imgModel.versions.map((v) => <option key={v.version_id} value={v.version_id}>{v.label || v.version_id}</option>)}
            </select>
          )}
          {imgLoras.length > 0 && (
            <div className="lv-loras">
              {imgLoras.map((l) => {
                // L536 + D-11: the base-model-compat warning D-11 explicitly deferred
                // ("would need the Loom to additionally resolve the selected base model's
                // own type, which it doesn't today") -- bindPicker above now DOES resolve
                // it, so the already-imported, already-tested loraIncompat() (previously
                // dead weight in this file) has real data to compare against. Reuses the
                // .failed visual treatment -- both states mean "this LoRA won't work as-is".
                const incompat = loraIncompat(imgModel && imgModel.model_type, l.lora_base_type);
                return (
                <div key={l.model_id} className={"lv-lchip" + ((l.failed || incompat) ? " failed" : "")}>
                  <span className="lv-lnm"
                    title={incompat ? l.title + " — needs a different base architecture than the one selected; remove it or switch the base" : l.title}>
                    {l.title}{!l.version_id ? (l.failed ? " ⚠" : " ⏳") : (incompat ? " ⚠" : "")}
                  </span>
                  {/* Bounds follow the BASE MODEL's architecture: DiT takes 0..1.2, the SD
                      family -2..+2 (negative subtracts that LoRA's influence). Served from
                      core in window.MG_LORA, the same table the gallery drawer reads, so the
                      two surfaces and the builder's own clamp cannot drift apart. */}
                  <span className="lv-lw">
                    <input type="range" step="0.1" min={loraRange[0]} max={loraRange[1]}
                      value={l.weight}
                      title={"Weight — " + loraRange[0] + " to " + loraRange[1] +
                             " for this base model" +
                             (loraRange[0] < 0 ? "; negative subtracts this LoRA's influence" : "")}
                      onChange={(ev) => { const w = Math.max(loraRange[0],
                                                             Math.min(loraRange[1], +ev.target.value || 0));
                        setImgLoras((cur) => cur.map((x) => x.model_id === l.model_id ? { ...x, weight: w } : x)); }} />
                    <b>{(+l.weight).toFixed(1)}</b>
                  </span>
                  {/* Controlled selection: dropping the LoRA from state un-lights the picker card too. */}
                  <button type="button" className="lv-lrm" title="Remove"
                    onClick={() => {
                      setImgLoras((cur) => cur.filter((x) => x.model_id !== l.model_id));
                    }}>×</button>
                  {/* Per-LoRA version selection: only when this LoRA actually has more than one
                      published release (l.versions, resolved alongside version_id itself by
                      the model picker's ?all=1 fetch -- see onLoraPick above). Mirrors
                      the base model's own #gen-version/.lv-versel switcher exactly, just
                      applied to this one chip's entry instead of the single imgModel. No new
                      network call -- the full version list is already on the entry. */}
                  {l.versions && l.versions.length > 1 && (
                    <select className="lv-lorver" value={l.version_id || ""}
                      title="This LoRA's published releases — PixAI defaults to the latest; pick another to use it instead"
                      onChange={(ev) => {
                        const vid = ev.target.value;
                        const v = l.versions.find((x) => x.version_id === vid);
                        if (!v) return;
                        setImgLoras((cur) => cur.map((x) => x.model_id === l.model_id
                          ? { ...x, version_id: v.version_id || "", lora_base_type: v.lora_base_model_type || "",
                              trigger_words: v.trigger_words || "", failed: !v.version_id }
                          : x));
                      }}>
                      {l.versions.map((v) => <option key={v.version_id} value={v.version_id}>{v.label || v.version_id}</option>)}
                    </select>
                  )}
                </div>
                );
              })}
            </div>
          )}
          <button type="button" className="lv-chip lv-loratoggle" onClick={() => { setPickerKind("lora"); setPickerOpen(true); }}>
            + add LoRA
          </button>
          {acct && acct.lora_cap != null && (
            <span className={"lv-loracap" + (overLoraCap(imgLoras, acct.lora_cap) ? " over" : "")}>
              {imgLoras.length} / {acct.lora_cap} LoRAs
            </span>
          )}
          <label className="lv-lab">Image prompt</label>
          <textarea className="lv-ta" value={active.c.imgPrompt || ""} placeholder="describe the reference still (subject, pose, composition, light)…"
            onChange={(ev) => patch((c) => ({ ...c, imgPrompt: ev.target.value }))} />
          {sel && <button className="lv-mini2" onClick={() => patch((c) => ({ ...c, imgPrompt: [c.title, c.prompt, (c.openFrame && c.openFrame.desc) || "", c.lighting || ""].filter(Boolean).join(", ") }))}>&#8615; seed from shot description</button>}
          {/* L536: full PixAI field parity with the gallery's own Generate tab (owner-decided
              scope, 2026-07-23) -- Advanced (negative/steps/cfg), 8 aspect-ratio buttons,
              Size + custom W×H, Mode, Count, Seed, High-priority, Prompt helper. Same field
              names/defaults/order as moonglade_gallery.py's #gen-mode-generate, submitted via
              buildImgGenBody() (loom-mutations.js) so the price badge below and the real
              submit in genImage() can never disagree about what these fields do. */}
          {(() => {
            // Capability gating (extra.compatibility, probed live 2026-07-06 -- memory
            // pixai-model-capability-schema): which of these params THIS model actually
            // honors, mirroring moonglade_gallery.py's gateField()/applyCapabilityGating()
            // exactly. Fails OPEN on unknown/absent data -- only an explicit `false`
            // disables anything (imgModel==null or a never-probed model -> compat={} ->
            // every field stays enabled, same as today).
            const compat = (imgModel && imgModel.compatibility) || {};
            const restr = (imgModel && imgModel.restrictions) || {};
            const negOff = compat.negativePrompt === false;
            const stepsOff = compat.samplingSteps === false;
            const cfgOff = compat.cfgScale === false;
            const stepsB = restr.samplingSteps || {};
            const cfgB = restr.cfgScale || {};
            const offTitle = "This model doesn’t use this setting";
            return (
          <details>
            <summary style={{ cursor: "pointer", color: "var(--subtext)", fontSize: 11 }}>Advanced</summary>
            <textarea className={"lv-ta" + (negOff ? " cap-off" : "")} style={{ marginTop: 5 }} value={imgAdv.negative}
              placeholder="lowres, text, watermark…" disabled={negOff} title={negOff ? offTitle : ""}
              onChange={(ev) => setImgAdv((a) => ({ ...a, negative: ev.target.value }))} />
            <div className="lv-row2">
              <div><label className="lv-lab" style={{ margin: "6px 0 3px" }}>Steps</label>
                <input className={"lv-in" + (stepsOff ? " cap-off" : "")} type="number"
                  min={stepsB.min != null ? stepsB.min : 1} max={stepsB.max != null ? stepsB.max : 150} step="1"
                  value={imgAdv.steps} disabled={stepsOff} title={stepsOff ? offTitle : ""}
                  onChange={(ev) => setImgAdv((a) => ({ ...a, steps: +ev.target.value || 25 }))} /></div>
              <div><label className="lv-lab" style={{ margin: "6px 0 3px" }}>CFG scale</label>
                <input className={"lv-in" + (cfgOff ? " cap-off" : "")} type="number"
                  min={cfgB.min != null ? cfgB.min : 1} max={cfgB.max != null ? cfgB.max : 30} step="0.5"
                  value={imgAdv.cfg} disabled={cfgOff} title={cfgOff ? offTitle : ""}
                  onChange={(ev) => setImgAdv((a) => ({ ...a, cfg: +ev.target.value || 7 }))} /></div>
            </div>
            {modelDefaults && (
              <div className="lv-advnote">
                <span>&#10003; using this model's tuned preset</span>
                <button type="button" className="lv-mini2" style={{ margin: 0 }} onClick={() => {
                  setImgAdv((a) => ({ ...a,
                    negative: modelDefaults.negative_prompt || a.negative,
                    steps: modelDefaults.sampling_steps || a.steps,
                    cfg: modelDefaults.cfg_scale || a.cfg }));
                }}>&#8630; reset</button>
              </div>
            )}
          </details>
            );
          })()}
          <label className="lv-lab">Aspect</label>
          <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
            {[[1, 1, "1:1"], [3, 4, "3:4"], [4, 3, "4:3"], [2, 3, "2:3"], [3, 2, "3:2"],
              [9, 16, "9:16"], [16, 9, "16:9"], [3, 1, "3:1"]].map(([rw, rh, label]) => (
              <button key={label} type="button"
                className={"lv-chip" + (imgAdv.aspectW === rw && imgAdv.aspectH === rh ? " on" : "")}
                onClick={() => setImgAdv((a) => ({ ...a, aspectW: rw, aspectH: rh }))}>{label}</button>
            ))}
          </div>
          <div className="lv-row2">
            <div><label className="lv-lab">Size · long edge</label>
              <select className="lv-sel" style={{ width: "100%" }} value={imgAdv.size}
                onChange={(ev) => setImgAdv((a) => ({ ...a, size: +ev.target.value }))}>
                <option value="768">S · 768</option>
                <option value="1024">M · 1024</option>
                <option value="1536">L · 1536</option>
                <option value="2048">XL · 2048</option>
              </select></div>
            <div><label className="lv-lab">Custom W&times;H <span className="lv-dim">· overrides</span></label>
              <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
                <input className="lv-in" type="number" min="64" max="4096" step="8" placeholder="W" value={imgAdv.customW}
                  onChange={(ev) => setImgAdv((a) => ({ ...a, customW: ev.target.value }))} />
                <span className="lv-dim">&times;</span>
                <input className="lv-in" type="number" min="64" max="4096" step="8" placeholder="H" value={imgAdv.customH}
                  onChange={(ev) => setImgAdv((a) => ({ ...a, customH: ev.target.value }))} />
              </div></div>
          </div>
          <div className="lv-dim" style={{ fontSize: 11, marginTop: 5 }}>
            {(() => { const d = resolveGenDims(imgAdv); return "→ " + d.w + " × " + d.h + (d.custom ? " · custom" : " px"); })()}
          </div>
          <div className="lv-row2">
            <div><label className="lv-lab">Mode</label>
              <select className="lv-sel" style={{ width: "100%" }} value={imgAdv.mode}
                onChange={(ev) => setImgAdv((a) => ({ ...a, mode: ev.target.value }))}>
                <option value="auto">Auto</option><option value="lite">Lite</option>
                <option value="standard">Standard</option><option value="pro">Pro</option>
                <option value="ultra">Ultra</option>
              </select></div>
            <div><label className="lv-lab">Count</label>
              <select className="lv-sel" style={{ width: "100%" }} value={imgAdv.count}
                onChange={(ev) => setImgAdv((a) => ({ ...a, count: +ev.target.value }))}>
                <option value="1">1</option><option value="2">2</option>
                <option value="3">3</option><option value="4">4</option>
              </select></div>
          </div>
          <label className="lv-lab">Seed <span className="lv-dim">· blank = random</span></label>
          <input className="lv-in" type="number" placeholder="random" value={imgAdv.seed}
            onChange={(ev) => setImgAdv((a) => ({ ...a, seed: ev.target.value }))} />
          <label className="lv-ck" title="This IS the site's Turbo tier (priority=1000): a faster runner. Costs more credits when paid, but a matching free card covers it.">
            <input type="checkbox" checked={imgAdv.highPriority}
              onChange={(ev) => setImgAdv((a) => ({ ...a, highPriority: ev.target.checked }))} /> High priority · Turbo (faster)</label>
          <label className="lv-ck">
            <input type="checkbox" checked={imgAdv.promptHelper}
              onChange={(ev) => setImgAdv((a) => ({ ...a, promptHelper: ev.target.checked }))} /> Prompt helper</label>
          <mg-cost-badge ref={imgCostRef} hint="Pick a model and write a prompt to see the cost." card-label="a card"></mg-cost-badge>
          {/* Gate on what genImage() itself refuses without -- a model and a prompt. It rejects
              both outright ("pick a model first" / "enter an image prompt"), so a live button
              made the tab's very FIRST click, before any model is picked, a dead end that only
              printed an error line. Same shape as the Edit/Reference Go buttons below, which
              already gate on their own required input (!src / !refs.length). */}
          <button className="lv-go"
            disabled={busyI || !imgModel || !(active.c.imgPrompt || "").trim() || anyLoraUnresolved(imgLoras) || imgLoras.some((l) => loraIncompat(imgModel && imgModel.model_type, l.lora_base_type)) || overLoraCap(imgLoras, acct && acct.lora_cap)}
            onClick={() => genImage(active)}>
            {busyI ? (gi.msg || "generating…")
              : anyLoraUnresolved(imgLoras) ? "waiting on LoRA…"
              : imgLoras.some((l) => loraIncompat(imgModel && imgModel.model_type, l.lora_base_type)) ? "incompatible LoRA — remove or switch base"
              : overLoraCap(imgLoras, acct && acct.lora_cap) ? "remove " + (imgLoras.length - acct.lora_cap) + " LoRA" + ((imgLoras.length - acct.lora_cap) === 1 ? "" : "s") + " to continue"
              : "✦ Generate reference image"}
          </button>
          {gi.phase === "error" && <div className="lv-gerr">{gi.msg}</div>}
          {gi.mid && (
            <div className="lv-imgresult">
              <img src={"/thumbs/" + gi.mid + ".jpg"} alt="result" />
              <div className="lv-route"><span className="lv-dim">route &#8594;</span>
                <button className={"lv-routebtn" + (gi.routed === "open" ? " on" : "")} disabled={!routeTarget} onClick={() => routeTarget && routeImg(routeTarget, "open", active.c.id)}>open frame</button>
                <button className={"lv-routebtn" + (gi.routed === "close" ? " on" : "")} disabled={!routeTarget} onClick={() => routeTarget && routeImg(routeTarget, "close", active.c.id)}>close frame</button>
                <button className={"lv-routebtn" + (gi.routed === "cast" ? " on" : "")} onClick={() => routeImg(routeTarget || active, "cast", active.c.id)}>cast</button>
              </div>
              {gi.routed && <div className="lv-ok2">&#10003; sent to {gi.routed}{sel ? " · it now feeds this shot's video gen" : ""}</div>}
            </div>)}
        </div>
      );
    }
    else if (tab === "Edit") {
      const ge = genEditState[active.c.id] || {};
      const busyE = ge.phase === "submitting" || ge.phase === "running";
      const src = active.c.openFrame && active.c.openFrame.mediaId;
      const gf = genFixState[active.c.id] || {};
      const busyF = gf.phase === "submitting" || gf.phase === "running";
      const fixPriceEntry = genFixPrice[active.c.id];
      tabBody = (
        <div>
          {/* Edit/Fixer/Enhance sub-strip -- The Loom.dc.html's editSubChips, ported from
              LoomMobile's own already-shipped Edit/Fixer/Enhance strip verbatim (same three
              sub-screens, same underlying real pipelines). Closes the design-fidelity punch
              list's "Edit tab has no Fixer or Enhance sub-tabs at all (desktop-only gap)"
              item -- 2026-08-04. */}
          <div className="lv-tabs" style={{ marginBottom: 9 }}>
            <span className={"lv-tab" + (editSub === "edit" ? " on" : "")} onClick={() => setEditSub("edit")}>Edit</span>
            <span className={"lv-tab" + (editSub === "fixer" ? " on" : "")} onClick={() => setEditSub("fixer")}>Fixer</span>
            <span className={"lv-tab" + (editSub === "enhance" ? " on" : "")} onClick={() => setEditSub("enhance")}>Enhance</span>
          </div>

          {editSub === "edit" && (
            <>
              <label className="lv-lab">Source — {sel ? "this shot's" : "the draft's"} open frame</label>
              {src ? <img className="lv-editsrc" src={"/thumbs/" + src + ".jpg"} alt="source" />
                   : <div className="lv-ph">No open-frame image yet — {sel ? <>route one from the <b>Image</b> tab, or </> : null}pick it into the open frame above.</div>}
              <label className="lv-lab">Edit instruction</label>
              <textarea className="lv-ta" value={active.c.editPrompt || ""} placeholder="e.g. make it night, add rain, warmer key light…"
                onChange={(ev) => patch((c) => ({ ...c, editPrompt: ev.target.value }))} />
              <mg-cost-badge ref={editCostRef} hint="Add a source image and instruction to see the cost." card-label="an Edit card"></mg-cost-badge>
              <button className="lv-go" disabled={busyE || !src} onClick={() => genEdit(active)}>{busyE ? (ge.msg || "editing…") : "✦ Edit the open frame"}</button>
              {ge.phase === "error" && <div className="lv-gerr">{ge.msg}</div>}
              {ge.mid && (
                <div className="lv-imgresult">
                  <img src={"/thumbs/" + ge.mid + ".jpg"} alt="result" />
                  <div className="lv-route"><span className="lv-dim">route &#8594;</span>
                    <button className={"lv-routebtn" + (ge.routed === "open" ? " on" : "")} disabled={!routeTarget} onClick={() => routeTarget && routeGen(genEditState, setGenEditState, routeTarget, "open", active.c.id)}>open frame</button>
                    <button className={"lv-routebtn" + (ge.routed === "close" ? " on" : "")} disabled={!routeTarget} onClick={() => routeTarget && routeGen(genEditState, setGenEditState, routeTarget, "close", active.c.id)}>close frame</button>
                    <button className={"lv-routebtn" + (ge.routed === "cast" ? " on" : "")} onClick={() => routeGen(genEditState, setGenEditState, routeTarget || active, "cast", active.c.id)}>cast</button>
                  </div>
                  {ge.routed && <div className="lv-ok2">&#10003; sent to {ge.routed}</div>}
                </div>)}
            </>
          )}

          {editSub === "fixer" && (
            <>
              <label className="lv-lab">Source — {sel ? "this shot's" : "the draft's"} open frame</label>
              {src ? (
                <div className="lv-fixwrap">
                  <img ref={fixImgRef} src={"/full/" + encodeURIComponent(src)} alt="source" onLoad={fixPaint} draggable={false} />
                  <canvas ref={fixCanvasRef}
                    onPointerDown={fixDown} onPointerMove={fixMove} onPointerUp={fixUp} onPointerLeave={fixUp} />
                </div>
              ) : <div className="lv-ph">No open-frame image yet — {sel ? <>route one from the <b>Image</b> tab, or </> : null}pick it into the open frame above.</div>}
              {src && (
                <>
                  <div className="lv-tabs" style={{ marginTop: 8 }}>
                    <span className={"lv-tab" + (fixTag !== "hand" ? " on" : "")} onClick={() => setFixTag("face")}>Face</span>
                    <span className={"lv-tab" + (fixTag === "hand" ? " on" : "")} onClick={() => setFixTag("hand")}>Hand</span>
                    <button className="lv-mini2" disabled={!fixBoxes.length} onClick={() => setFixBoxes([])}>Clear{fixBoxes.length ? " " + fixBoxes.length : ""}</button>
                  </div>
                  <div className="lv-fixhint">Drag a box over the hand or face on the source.</div>
                </>
              )}
              <div className="lv-fixwarn">A fix can't be card-covered — it always spends, and always asks first.</div>
              <div className="lv-dim" style={{ padding: "4px 2px" }}>
                {fixPriceEntry && fixPriceEntry.loading ? "checking…"
                  : fixPriceEntry && fixPriceEntry.pr && typeof fixPriceEntry.pr.cost === "number" ? "≈ " + Number(fixPriceEntry.pr.cost).toLocaleString() + " credits — never card-covered"
                  : !src ? "Pick a source image first."
                  : !fixBoxes.length ? "Drag at least one box to see the cost."
                  : "Couldn't verify the cost — a Fix always spends credits."}
              </div>
              <button className="lv-go" disabled={busyF || !src || !fixBoxes.length}
                onClick={() => genFix(active, scaleFixBoxes(fixBoxes, fixImgRef.current))}>
                {busyF ? (gf.msg || "fixing…") : "✦ Fix " + fixTag}
              </button>
              {gf.phase === "error" && <div className="lv-gerr">{gf.msg}</div>}
              {gf.mid && (
                <div className="lv-imgresult">
                  <img src={"/thumbs/" + gf.mid + ".jpg"} alt="result" />
                  <div className="lv-route"><span className="lv-dim">route &#8594;</span>
                    <button className={"lv-routebtn" + (gf.routed === "open" ? " on" : "")} disabled={!routeTarget} onClick={() => routeTarget && routeGen(genFixState, setGenFixState, routeTarget, "open", active.c.id)}>open frame</button>
                    <button className={"lv-routebtn" + (gf.routed === "close" ? " on" : "")} disabled={!routeTarget} onClick={() => routeTarget && routeGen(genFixState, setGenFixState, routeTarget, "close", active.c.id)}>close frame</button>
                    <button className={"lv-routebtn" + (gf.routed === "cast" ? " on" : "")} onClick={() => routeGen(genFixState, setGenFixState, routeTarget || active, "cast", active.c.id)}>cast</button>
                  </div>
                  {gf.routed && <div className="lv-ok2">&#10003; sent to {gf.routed}</div>}
                </div>)}
            </>
          )}

          {editSub === "enhance" && (
            <>
              <label className="lv-lab">Art filters · free, no generation</label>
              <button className="lv-openfilters" onClick={openFilterCompare}>&#9680; Open filters</button>
              <div className="lv-dim" style={{ padding: "6px 2px" }}>Gradient overlays, not AI — applied right in the browser: <b style={{ color: "var(--text)" }}>no credits, no request, works offline</b>.</div>
            </>
          )}
        </div>
      );
    }
    else if (tab === "Reference") {
      const gr = genRefState[active.c.id] || {};
      const busyR = gr.phase === "submitting" || gr.phase === "running";
      const refs = (project.assets || []).filter((a) => a.kind === "image" && a.mediaId);
      tabBody = (
        <div>
          <label className="lv-lab">References — cast @image members ({refs.length})</label>
          {refs.length ? <div className="lv-refstrip">{refs.map((a) => (<img key={a.id} src={"/thumbs/" + a.mediaId + ".jpg"} title={a.tag} alt="" />))}</div>
                       : <div className="lv-ph">No cast @image references with a gallery image yet — add some in <b>Cast &amp; assets</b>.</div>}
          <label className="lv-lab">Prompt</label>
          <textarea className="lv-ta" value={active.c.refPrompt || ""} placeholder="compose a new still from the references…"
            onChange={(ev) => patch((c) => ({ ...c, refPrompt: ev.target.value }))} />
          <mg-cost-badge ref={refCostRef} hint="Add references and a prompt to see the cost." card-label="an Edit card"></mg-cost-badge>
          <button className="lv-go" disabled={busyR || !refs.length} onClick={() => genRef(active)}>{busyR ? (gr.msg || "generating…") : "✦ Generate from references"}</button>
          {gr.phase === "error" && <div className="lv-gerr">{gr.msg}</div>}
          {gr.mid && (
            <div className="lv-imgresult">
              <img src={"/thumbs/" + gr.mid + ".jpg"} alt="result" />
              <div className="lv-route"><span className="lv-dim">route &#8594;</span>
                <button className={"lv-routebtn" + (gr.routed === "open" ? " on" : "")} disabled={!routeTarget} onClick={() => routeTarget && routeGen(genRefState, setGenRefState, routeTarget, "open", active.c.id)}>open frame</button>
                <button className={"lv-routebtn" + (gr.routed === "close" ? " on" : "")} disabled={!routeTarget} onClick={() => routeTarget && routeGen(genRefState, setGenRefState, routeTarget, "close", active.c.id)}>close frame</button>
                <button className={"lv-routebtn" + (gr.routed === "cast" ? " on" : "")} onClick={() => routeGen(genRefState, setGenRefState, routeTarget || active, "cast", active.c.id)}>cast</button>
              </div>
              {gr.routed && <div className="lv-ok2">&#10003; sent to {gr.routed}</div>}
            </div>)}
        </div>
      );
    }
    else tabBody = <div className="lv-ph">The <b>{tab}</b> tab renders the shot on PixAI.</div>;
    gen = (
      <div className="lv-gen">
        <div className="lv-genhead">{sel
          ? <>&#9881; {sel.code} &middot; {sel.c.title || "untitled"}</>
          : <>&#10024; Draft generation <span className="lv-dim">— generate freely, then route or attach it to a shot</span></>}
          {sel && <button className="lv-unbind" onClick={() => setSelShot(null)}
            title="Unbind this shot and go back to draft generation">&#10005; unbind</button>}</div>
        {!sel && (
          <div className="lv-drafttarget">
            <label className="lv-lab">Route results into a shot <span className="lv-dim">(cast doesn't need one)</span></label>
            <select className="lv-sel" value={draftTarget} onChange={(ev) => setDraftTarget(ev.target.value)}>
              <option value="">— choose a shot —</option>
              {entries.map((e) => <option key={e.c.id} value={e.c.id}>{e.code} &middot; {e.c.title || "untitled"}</option>)}
            </select>
          </div>
        )}
        {/* Gallery-era correction (handoff-2026-08-06 / The Loom.dc.html:399-427): the
            shared Frame Handoff block shows on the THREE tabs that consume it —
            Reference (still composition), Video (its Continuity/weave modes read these
            frames), Edit (reads openFrame as its source) — with a contextual label
            naming which role it plays. Hidden on Image, the one tab that doesn't use
            it. This is the re-scope the owner sent back 2026-08-04: shared
            infrastructure, never Reference-only. */}
        {(tab === "Reference" || tab === "Video" || tab === "Edit") && (
          <>
            <div className="lv-fhlabel">FRAME HANDOFF — {
              tab === "Video" ? "drives this shot’s motion" : tab === "Edit" ? "edit source" : "still composition"}</div>
            <div className="lv-framehandoff">
              <FrameSlot which="open" frame={active.c.openFrame} liveTag={positionTag(active, project, imgSrc, "openFrame")} discreet={active.c.discreet} framePrev={frameSrc} storeThumb={storeThumb} openPick={openPick}
                onPatch={(p) => patchFrame("openFrame", p)}
                extraBtn={prevEntry ? <button className="sb-btn ghost sm" onClick={inheritPrev} disabled={handoff === "wip"}
                    title={prevEntry.c.resultMid ? `Splice in ${prevEntry.code}'s generated clip's last frame` : `Copy ${prevEntry.code}'s closing frame here`}>
                    {handoff === "wip" ? "✂ splicing…" : handoff === "err" ? "✂ splice failed — retry"
                      : prevEntry.c.resultMid ? `✂ splice ${prevEntry.code}'s last frame` : `↳ inherit ${prevEntry.code} close`}</button>
                  : <span className="sb-hint">{sel ? "first shot — no previous frame" : "draft — no shot sequence to inherit from"}</span>} />
              <div className="sb-conn-mid">&#8594;</div>
              <FrameSlot which="close" frame={active.c.closeFrame} liveTag={positionTag(active, project, imgSrc, "closeFrame")} discreet={active.c.discreet} framePrev={frameSrc} storeThumb={storeThumb} openPick={openPick}
                onPatch={(p) => patchFrame("closeFrame", p)} />
            </div>
          </>
        )}
        {/* The Image/Edit/Reference/Video tab strip lives in the rail's .lv-sidehead
            (like the left rail's Cast/Footage tabs), so `gen` must NOT render its own --
            an identical strip here stacked a duplicate directly below the header one
            whenever the right rail was expanded. Removed to match the left-rail pattern:
            tabs in the header, content below without repeating them. */}
        {acct && (
          <div className="lv-bal">&#9889; {acct.credits == null ? "—" : acct.credits} credits &middot; {acct.cards || 0} card{acct.cards === 1 ? "" : "s"}
            {acct.claim_credits ? <span className="lv-balclaim"> &middot; +{acct.claim_credits} claimable</span> : null}</div>
        )}
        {tabBody}
        {/* Always mounted (never conditionally rendered on `tab`) so switching tabs mid-
            render can't unmount the element and kill its in-flight poll -- CSS-hidden
            instead, exactly like every other tab's content stays out of the DOM flow
            without losing its live state. See the videoTrailer comment above. */}
        {/* data-loom-ctx tells the shared drawer's own CSS (static/mg-generate-drawer.js) to
            hide its Camera + Basic/Professional controls -- this host already owns both (the
            shot Camera field above, the top-strip Draft toggle) via its own state. Without
            this attribute the drawer renders its own copies alongside the Loom's, showing two
            Camera controls and two quality controls for the same setting. */}
        <mg-generate-drawer ref={bindGenDrawer} data-loom-ctx="" style={{ display: tab === "Video" ? "" : "none" }}></mg-generate-drawer>
        {videoTrailer}
        {/* picker-parity-round2 (problem 2): the Model/LoRA picker overlay -- a floating
            panel, not squeezed inline into this rail (the owner's exact complaint). Lazy-
            mounted (pickerMounted above), then left mounted for the rest of the session --
            CSS-hidden via .open/inline display instead of unmounted, so a close/reopen never
            loses either picker's search/scroll state, matching the Gallery's own
            #model-flyout (created once by ensurePickers(), display toggled after that).
            pickerKind only switches which of the two is VISIBLE, same as the Gallery's
            setKind() -- both mount together and stay mounted, matching that "each keeps its
            OWN last-searched results independently" contract exactly. base-type on the LoRA
            mount reuses imgModel.model_type -- already resolved for the LoRA-compat warning
            above -- so switching the selected base re-sorts/re-badges LoRA results live. */}
        <div className={"lv-mpick-veil" + (pickerOpen ? " open" : "")}
          onClick={(ev) => { if (ev.target === ev.currentTarget) setPickerOpen(false); }}>
          <div className="lv-mpick-panel" role="dialog" aria-label="Models and LoRAs">
            <div className="lv-mpick-head">
              <span className="t">Models &amp; LoRAs</span>
              <button type="button" className="x" onClick={() => setPickerOpen(false)} aria-label="Close">&times;</button>
            </div>
            <div className="lv-mpick-seg">
              <button type="button" className={pickerKind === "base" ? "on" : ""} onClick={() => setPickerKind("base")}>Models</button>
              <button type="button" className={pickerKind === "lora" ? "on" : ""} onClick={() => setPickerKind("lora")}>LoRAs</button>
            </div>
            <div className="lv-mpick-body">
              {pickerMounted && (
                <>
                  <ModelPicker kind="base" visible={pickerKind === "base"} value={imgModel} onPick={onBasePick}
                    style={{ display: pickerKind === "base" ? "flex" : "none" }} />
                  <ModelPicker kind="lora" multi baseType={(imgModel && imgModel.model_type) || ""} visible={pickerKind === "lora"} selected={imgLoras} onToggle={onLoraPick}
                    style={{ display: pickerKind === "lora" ? "flex" : "none" }} />
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }
  const castList = (
    <>
      <div className="lv-castrow-h">Cast &amp; assets{sel ? <span className="lv-dim"> — bound to {sel.code}</span> : null}</div>
      {/* Live reference-slot budget for the bound shot (owner decision, 2026-07-27): PixAI
          takes 6 images, attached frames claim theirs only when attached, so cast/refs get
          6 minus attached frames -- refBudget() in loom-core.js, derived off the same
          item list shotImageRefs builds and actually ships, never a second count. `used` is
          deliberately uncapped: used > budget is the "some of these are not being sent"
          state the rows below mark, and hiding it here would put the panel back to
          silently trimming. No `sel` means no shot to budget against -- say nothing rather
          than invent a project-global number no generation ever uses. */}
      {sel && (() => {
        // MODE-AWARE (2026-07-27, round 3): the slot arithmetic below is only true of
        // modes whose generation takes the reference bank (R2V/V2V -- modeSendsRefs,
        // derived from usesCloseFrame + the mode, see its comment). Round 2 rendered it
        // unconditionally, so an I2V shot's panel claimed cast members were consuming
        // "reference slots" of a generation that sends the opening frame alone. For
        // FLF/I2V: no budget arithmetic at all, just the honest one-liner.
        if (!modeSendsRefs(sel.c.mode)) {
          return (
            <div className="lv-refbudget"
              title={`${sel.c.mode === "FLF" ? "A First & Last generation attaches only the Start and End frames" : "An I2V generation attaches only the opening frame"}. The @imageN numbers below are the composed prompt's citation numbering, not attachments.`}>
              {modeSendsLine(sel.c.mode)}
            </div>
          );
        }
        const b = refBudget(sel, project, imgSrc);
        return (
          <div className="lv-refbudget"
            title={`PixAI accepts 6 reference images per generation. ${b.frames
              ? `${b.frames === 1 ? "1 slot is" : `${b.frames} slots are`} held by ${sel.code}'s attached frame${b.frames === 1 ? "" : "s"}, leaving ${b.budget} for cast & image refs.`
              : "No frames attached, so all 6 are free for cast & image refs."} Anything past that is not sent.`}>
            <span className={b.used > b.budget ? "lv-refbudget-over" : undefined}>{b.used} of {b.budget} reference slot{b.budget === 1 ? "" : "s"} used</span>
            {b.frames ? <span className="lv-dim"> &middot; {b.frames} of 6 held by attached frame{b.frames === 1 ? "" : "s"}</span> : null}
          </div>
        );
      })()}
      <details className="lv-look" open={!!(project.look || "").trim()}>
        <summary>🎨 Project look{(project.look || "").trim() ? "" : <span className="lv-dim"> — a style line added to every shot</span>}</summary>
        <textarea className="lv-lookin" value={project.look || ""} rows={2}
          onChange={(e) => setLook(e.target.value)}
          placeholder="e.g. muted teal grade, 35mm grain, anamorphic flares — applied to every shot's prompt" />
      </details>
      <div className="lv-tabs lv-density">
        <span className={"lv-tab " + (density === "simple" ? "on" : "")} onClick={() => setDensity("simple")}>Simple</span>
        <span className={"lv-tab " + (density === "detailed" ? "on" : "")} onClick={() => setDensity("detailed")}>Detailed</span>
      </div>
      {density === "detailed" ? (project.assets || []).map((as) => {
        const inShot = sel && (sel.c.cast || []).includes(as.id);
        const toggleInShot = () => sel && setCard(sel.a.id, sel.c.id, (c) => ({ ...c, cast: (c.cast || []).includes(as.id) ? c.cast.filter((x) => x !== as.id) : [...(c.cast || []), as.id] }));
        const src = frameSrc(as);
        // This panel is shot-bound ("bound to A-02") yet used to show ONLY as.tag -- the
        // project-global, cast-add-order tag -- as if that were what gets sent. It is not:
        // the generator numbers by POSITION in the bound shot (shotImageRefs/positionTag,
        // loom-core.js), which is how the owner watched this panel say @image1/@image2
        // while the drawer and the composed prompt said @image2/@image3 for the same two
        // pictures. `liveTag` is that real, live number, shown READ-ONLY beside the stored-
        // tag input (which keeps editing as.tag exactly as before -- it still drives cast
        // ordering). null liveTag splits two honest ways: `pastBudget` (has a picture, lost
        // the 6-slot contest -- positionTag's null IS the cap's signal, same ordering that
        // trims, never re-derived) gets the row dimmed and marked "not sent"; no picture at
        // all gets a plain dash -- NOT a warning state, which round 1 invented here and
        // watched misfire on cap-trimmed members.
        const liveTag = sel && inShot && as.kind === "image" ? positionTag(sel, project, imgSrc, as.id) : null;
        const pastBudget = sel && inShot && as.kind === "image" && !liveTag && !!resolvedImage(as, imgSrc);
        return (
          <div key={as.id} className={"lv-assetrow" + (pastBudget ? " oob" : "")}>
            {as.kind !== "audio" && <button className="lv-pickico" title="Pick from your gallery"
              onClick={() => openPick((mid) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, thumbId: "", source: "", mediaId: mid })), as.kind === "video" ? "video" : "image")}>🖼</button>}
            {as.kind === "image" ? (
              <label className="lv-assetprev" title="Attach image">
                {src ? <img src={src} alt="" /> : "＋"}
                <input type="file" accept="image/*" style={{ display: "none" }}
                  onChange={async (e) => { const f = e.target.files[0]; if (!f) return; const id = await storeThumb(f);
                    setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, thumbId: id, source: x.source || f.name, mediaId: "" })); }} />
              </label>
            ) : <div className="lv-assetprev" title={as.kind === "video" ? "Video asset — poster from your gallery" : undefined}>
              {/* A gallery-picked video resolves its /thumbs/<mid>.jpg poster through
                  frameSrc exactly like an image does -- the bare film emoji made a
                  successful video import invisible here (issue #3's visibility half).
                  The emoji stays as the no-poster fallback (e.g. a hand-retyped kind). */}
              {as.kind === "video" && src ? <img src={src} alt="" /> : (as.kind === "video" ? "🎞" : "♪")}
            </div>}
            <input className="lv-in" style={{ flex: "1 1 100px" }} value={as.name} placeholder="name"
              onChange={(e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, name: e.target.value }))} />
            <input className="lv-tagin" value={as.tag}
              onChange={(e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, tag: e.target.value }))} />
            {/* liveTagTitle/liveTagText, not inline strings (round 3): round 2 hard-coded
                "what the composed prompt and the generator actually send" here for every
                mode -- false on FLF/I2V, whose generations never attach cast pictures.
                The shared helpers word the claim per mode family (see their comment). */}
            {sel && inShot && as.kind === "image" && (
              <span className={"lv-livetag" + (pastBudget ? " oob" : "")}
                title={liveTagTitle(liveTag, pastBudget, sel.c.mode, sel.code)}>
                {liveTagText(liveTag, pastBudget, sel.c.mode)}
              </span>
            )}
            <select className="lv-sel" value={as.kind}
              onChange={(e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, kind: e.target.value }))}>
              <option value="image">image</option><option value="video">video</option><option value="audio">audio</option>
            </select>
            <label className="lv-locklab" title="Write 'maintain exact appearance' in prompts">
              <input type="checkbox" checked={!!as.lock} onChange={(e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, lock: e.target.checked }))} />lock</label>
            {sel && <label className="lv-inshot" title="Include in the selected shot's cast">
              <input type="checkbox" checked={!!inShot} onChange={toggleInShot} />in {sel.code}</label>}
            <button className="lv-ico xs danger" onClick={() => setAssets((a) => a.filter((x) => x.id !== as.id))} title="Remove">&#10005;</button>
          </div>
        );
      }) : (
        <div className="lv-simplegrid">{(project.assets || []).map((as) => {
          const inShot = sel && (sel.c.cast || []).includes(as.id);
          const src = frameSrc(as);
          // Same live-number rule as the detailed rows above (see that comment): the shot's
          // real positional @imageN when this member is in the bound shot's cast, "not sent"
          // when a good picture lost the 6-slot contest, nothing at all when there is no
          // picture to number.
          const liveTag = inShot && as.kind === "image" ? positionTag(sel, project, imgSrc, as.id) : null;
          const pastBudget = inShot && as.kind === "image" && !liveTag && !!resolvedImage(as, imgSrc);
          return (
            <div key={as.id} className={"lv-simplecard " + (inShot ? "on " : "") + (pastBudget ? "oob " : "") + (!sel ? "nosel" : "")}
              title={sel ? `Toggle into ${sel.code}` : "Select a shot on the board to toggle its cast"}
              onClick={() => sel && setCard(sel.a.id, sel.c.id, (c) => ({ ...c, cast: (c.cast || []).includes(as.id) ? c.cast.filter((x) => x !== as.id) : [...(c.cast || []), as.id] }))}>
              {src ? <img src={src} alt="" /> : <span className="lv-castph" />}
              <b>{as.name || as.kind}</b><span className="lv-dim">{as.tag}</span>
              {/* Shared liveTagTitle/liveTagText wording, same round-3 mode-awareness as
                  the detailed rows above -- a Simple card must never claim "sent" on a
                  mode that doesn't attach cast pictures. Structure unchanged from round 2:
                  no-picture still renders nothing here (the compact card has no dash). */}
              {liveTag ? <span className="lv-livetag" title={liveTagTitle(liveTag, pastBudget, sel.c.mode, sel.code)}>{liveTag}</span>
                : pastBudget ? <span className="lv-livetag oob" title={liveTagTitle(liveTag, pastBudget, sel.c.mode, sel.code)}>{liveTagText(liveTag, pastBudget, sel.c.mode)}</span> : null}
            </div>
          );
        })}</div>
      )}
      {!(project.assets || []).length && <div className="lv-ph">No cast yet — add one below.</div>}
      {/* Opens on "all" (both kinds), not "image": with an image-only default an
          already-rendered video was absent from the view entirely, and the type
          dropdown's combined option didn't surface videos either (it submitted '',
          which the server maps to image-only) -- issue #3's reachability half. */}
      <button className="lv-addcast" onClick={() => openPick((mid, thumb, isVideo) => setAssets((a) => {
        const k = isVideo ? "video" : "image", pre = isVideo ? "@video" : "@image";
        return [...a, { id: uid(), name: "", kind: k, tag: nextTag(a, pre), thumbId: "", source: "", mediaId: mid, lock: false }];
      }), "all", true)}>+ add from gallery</button>
      <button className="lv-addcast" onClick={() => setImportOpen(true)}
        title="Pull a whole gallery collection in as reusable @image references">&#8623; Import collection</button>
    </>
  );
  const finished = entries.filter((e) => e.c.resultMid);
  // "Finished shots" is every shot card with a resultMid, however it got one -- this
  // project's own render pipeline (generateShot/pollShot) OR "Browse library" below,
  // which imports an already-rendered CATALOG video straight onto the board as a real,
  // placeable shot (importFootage -> landInFirstAct + importedFootagePatch, loom-mutations.js).
  // That's the footage tab's whole purpose, so its own button now means "bring this video
  // in", not "cite it in a prompt" -- Cast & Assets keeps its own separate "+ add from
  // gallery" button (above) for the reference use case, video included (type=all).
  // addAssetFromFile (the drop zone below) still only handles local IMAGE files -- there's
  // still no local-video-upload path here (out of scope); a dragged/dropped video has
  // nowhere to land except through the picker above.
  const addAssetFromFile = async (file) => {
    if (!file || !file.type || !file.type.startsWith("image/")) return;
    const id = await storeThumb(file);
    setAssets((a) => [...a, { id: uid(), name: "", kind: "image", tag: nextTag(a, "@image"), thumbId: id, source: file.name, lock: false }]);
  };
  // Resolve a picked video's real length before landing it: the picker already threads the
  // catalog's own `video_duration` straight through (same field useExistingVideo trusts) --
  // only fall back to a local ffprobe (server route, older/legacy rows with a blank column)
  // when that's missing, rather than leaving an imported clip's duration silently wrong.
  const importPickedFootage = async (mid, duration) => {
    let dur = parseFloat(duration);
    if (!(dur > 0)) {
      try {
        const r = await fetch("/api/loom/video-duration?media_id=" + encodeURIComponent(mid));
        const d = await r.json();
        if (d && d.duration) dur = d.duration;
      } catch { /* leave dur unresolved -- importFootage falls back to newCard's own default */ }
    }
    setSelShot(importFootage(mid, dur));
  };
  const footageList = (
    <>
      <div className="lv-footagehead">
        <span className="lv-castrow-h">Finished shots</span>
        <button className="lv-browsebtn"
          title="Import an already-rendered video from your gallery straight onto the board as a real, placeable shot"
          onClick={() => openPick((mid, thumb, isVideo, duration) => {
            if (!isVideo) return;   // picker is locked to video below; defensive only
            importPickedFootage(mid, duration);
          }, "video")}>&#8981; Browse library</button>
      </div>
      {finished.length
        ? <div className="lv-footage">{finished.map((e) => (
            <div key={e.c.id} className={"lv-fclip " + (e.c.id === selShot ? "sel" : "")} onClick={() => setSelShot(e.c.id)}>
              <img src={"/thumbs/" + e.c.resultMid + ".jpg"} alt="" />
              <div className="lv-fmeta"><b>{e.code}</b>
                {e.c.imported && <span title="Imported from your gallery, not rendered by this project">&#8623;</span>}
                <span>{durOf(e.c)}s</span></div>
            </div>))}</div>
        : <div className="lv-ph">No rendered shots yet — generate one and it lands here.</div>}
      <div className={"lv-dropzone" + (dzHover ? " hover" : "")}
        onDragEnter={(ev) => { ev.preventDefault(); setDzHover(true); }}
        onDragOver={(ev) => ev.preventDefault()}
        onDragLeave={() => setDzHover(false)}
        onDrop={(ev) => { ev.preventDefault(); setDzHover(false); [...ev.dataTransfer.files].forEach(addAssetFromFile); }}>
        &#8681; drag an image here to add it as a cast reference
      </div>
    </>
  );

  // the 2026-07-21 audit `state-owner-defects`: .lv-df-veil (z-index 450) renders as a
  // DESCENDANT of .lv-overlay (z-index 400), so from the root stacking context it's part
  // of the SAME 400 atom, not a real 450 -- the body-level corner FABs (#jobs-fab/#jobs-
  // tray, z-index 401/402; see moonglade_gallery.py's "Lift the Activity chip" comment) then
  // paint OVER Deep Focus's veil and everything nested inside it, though the numbering
  // says they shouldn't. The full fix (hoisting Deep Focus out to .sb-root level) is a
  // bigger DOM refactor, deferred; this raises .lv-overlay's own root-context z-index to
  // Deep Focus's intended 450 for as long as Deep Focus is open, so the corner FABs go
  // back to losing the comparison the way every other 400+ overlay in this file already
  // does -- no DOM move required.
  return (
    <div className={"lv-overlay" + (deepFocus ? " lv-overlay-df" : "")}>
      <style>{V2_STYLES}</style>
      {/* The Loom.dc.html:36-45 -- the hero banner. Radial-gradient art layer, real
          hide/show toggle. Entirely missing before this fix. */}
      {bannerOpen ? (
        <div className="lv-banner">
          <div className="lv-banner-art" />
          {/* The real Branding-slot flat (banner_loom -> /branding/banner-loom.png,
              written through by the Control Panel's banner editor). Layers OVER the
              design's gradient; onError removes itself so a fresh install with no
              upload shows the gradient exactly as the DC draws it. */}
          <img className="lv-banner-img" src="/branding/banner-loom.png" alt=""
            onError={(e) => e.currentTarget.remove()} />
          <button type="button" className="lv-banner-hide" title="Hide banner"
            onClick={() => setBannerOpen(false)}>⌄ Hide banner</button>
        </div>
      ) : null}
      <div className="lv-top">
        {!bannerOpen && (
          <button type="button" className="lv-banner-show" title="Show banner"
            onClick={() => setBannerOpen(true)}>🖼 Banner</button>
        )}
        <span className="lv-eyebrow">The Loom · V2</span>
        <span className="lv-note">Click a shot → it binds to Generate.</span>
        <ProjectSwitcher api={projectApi} />
        <label className={"lv-draft" + (project.draft ? " on" : "")}
          title="Draft mode renders every shot at the cheaper 'basic' quality — block out the animatic, then turn Draft off and re-generate the keepers at pro quality">
          <input type="checkbox" checked={!!project.draft} onChange={(e) => setDraft(e.target.checked)} />⚡ Draft</label>
        {/* Manual, owner-preference switch to the phone-sized board/reel view (LoomMobile,
            below useProjectStore) -- unlike everything else in this bar, this is a NEW pattern
            for the Loom: the main gallery only ever auto-detects viewport width for its own
            mobile layout, there is no existing "durable manual UI-mode toggle" hook anywhere
            in this file to reuse. Persisted (useLocalToggle, MOBILE_UI_KEY) so the choice
            survives a reload; reuses .lv-draft's own checkbox-chip visual pattern rather than
            inventing a new one. draftCard/draftTarget/draftAttachedInfo are lifted to App() --
            see this component's own prop-list comment -- specifically so flipping this switch
            mid-draft never loses it. */}
        <label className={"lv-draft" + (mobileUI ? " on" : "")}
          title="Switch to a phone-sized board/reel view — desktop chrome (panels, drawers) hides; your project and any in-progress draft are unaffected">
          <input type="checkbox" checked={!!mobileUI} onChange={(e) => setMobileUI(e.target.checked)} />📱 Mobile view</label>
        <button onClick={() => {
          // Flush+locally-patch BEFORE calling batchGenerate -- do not trust that a hand-
          // edit committed via blur (the button stealing focus fires the drawer's blur
          // handler synchronously) is already reflected in `entries`. It isn't: React
          // defers re-rendering until this whole synchronous click dispatch finishes, so
          // `entries` here is still the closure captured at the LAST render, before this
          // click. Found in review -- a fix that reasoned "blur fires before click, so
          // it's safe" was wrong once traced against exactly when React commits state.
          const pending = genDrawerRef.current && genDrawerRef.current.flushPromptEdit ? genDrawerRef.current.flushPromptEdit() : null;
          let liveEntries = entries;
          if (pending != null && activeRef.current) {
            const a = activeRef.current;
            const already = !!a.c.promptOverride;
            // imgSrc: drawer-COUPLED comparator (the flushed text was seeded thumbs-aware
            // by the prefill effect) -- composing without it here would freeze every
            // thumb-carrying prefilled prompt as an override the moment Generate-all is
            // clicked. See the prefill effect's payload.prompt comment for the family.
            const composed = already ? null : shotText(a, project, imgSrc);
            if (already || pending !== composed) {
              const patchedCard = setPromptOverride(a.c, pending);
              liveEntries = entries.map((e) => (e.c.id === a.c.id ? { ...e, c: patchedCard } : e));
              a.c.id === "__draft__" ? setDraftCard(() => patchedCard) : setCard(a.a.id, a.c.id, () => patchedCard);
            }
          }
          batchGenerate(liveEntries);
        }} disabled={batching || !entries.length}
          title="Generate every shot that isn't done yet, one after another">
          {batching ? "▶ generating all…" : `▶ Generate all (${costEstimate.notDoneCount})`}</button>
        {costEstimate.notDoneCount > 0 && (
          <button className="lv-cost-pill" onClick={refreshEstimate} disabled={batching}
            title={costTooltip(costEstimate) + " — estimate reflects Generate-all composition; a shot generated by hand from its own Video-tab drawer (esp. I2V/FLF with both cast images and a frame set) may price differently. Click to refresh."}>
            {formatCostEstimate(costEstimate)}
          </button>
        )}
        <button disabled={!entries.some((e) => e.c.resultMid)} onClick={() => playSequence(entries)}
          title="Play every finished shot back-to-back, honoring trims — a rough cut, no rendering">&#9654;&#9654; Play</button>
        <button disabled={!entries.some((e) => e.c.resultMid)} onClick={() => exportCut(entries)}
          title="Trim + stitch every finished shot into one mp4 (ffmpeg)">&#8681; Render</button>
        <ExportMenu exportAll={exportAll} exportJSON={exportJSON} exportBundle={exportBundle}
          bundling={bundling} importBackup={importBackup} />
        <a className="lv-close" href="/" style={{ textDecoration: "none" }}>← Gallery</a>
      </div>
      {batchTally && (() => {
        // done/failed/stale are DERIVED from the outcomes map every render, never stored as
        // separate counters -- see batchTally's own doc comment (useGenerationPipeline) for
        // why: a card's outcome can be reassigned (a `stale` shot resolving `done` later via
        // a manual recheck) by simply overwriting its one map entry, which self-corrects
        // instead of requiring manual decrement bookkeeping across two mutation sites.
        const outs = Object.values(batchTally.outcomes);
        const done = outs.filter((o) => o === "done").length;
        const failed = outs.filter((o) => o === "failed").length;
        const stale = outs.filter((o) => o === "stale").length;
        return (
          <div className="lv-batchbar">
            Batch: {batchTally.submitted}/{batchTally.total} submitted &middot; {done} done
            {failed ? <> &middot; <span className="lv-batchfail">{failed} failed</span></> : null}
            {stale ? <> &middot; <span className="lv-batchstale">{stale} paused (check manually)</span></> : null}
            {/* A shot settles via one of three paths: fails at submit time (recorded directly
                as an outcome, never touching `submitted`); is submitted then resolves via
                poll into done/failed; or is submitted and its poll hits the give-up timer's
                6h ceiling with neither -- `stale`. done+failed+stale reaching `total` means
                "nothing in this batch is being actively checked anymore," NOT "everything
                succeeded" -- that's why `stale` gets its own visible count instead of folding
                into `done` or `failed`. */}
            {done + failed + stale < batchTally.total ? " · rendering…" : ""}
          </div>
        );
      })()}
      {timelineDrawer}
      <div className="lv-shell">
        <div className="lv-rail">
          <button className={"lv-railbtn" + (!leftCollapsed && leftTab === "cast" ? " on" : "")} title="Cast & assets"
            onClick={() => { setLeftTab("cast"); openLeftPanel(); }}>&#128100;</button>
          <button className={"lv-railbtn" + (!leftCollapsed && leftTab === "footage" ? " on" : "")} title="Footage"
            onClick={() => { setLeftTab("footage"); openLeftPanel(); }}>&#127916;</button>
        </div>

        {(!leftCollapsed || leftClosing) && (
          <>
            <div className={"lv-backdrop" + (leftClosing ? " closing" : "")} onClick={closeLeftPanel} />
            <div className={"lv-panel left" + (leftClosing ? " closing" : "") + (leftTab === "cast" && density === "detailed" ? " wide" : "")}>
              <div className="lv-sidehead">
                <div className="lv-tabs lv-sidetabs">
                  <span className={"lv-tab " + (leftTab === "cast" ? "on" : "")} onClick={() => setLeftTab("cast")}>Cast &amp; assets</span>
                  <span className={"lv-tab " + (leftTab === "footage" ? "on" : "")} onClick={() => setLeftTab("footage")}>Footage</span>
                </div>
                <button className="lv-col" onClick={closeLeftPanel} title="collapse">&#8249;</button>
              </div>
              <div className="lv-cast">{leftTab === "cast" ? castList : footageList}</div>
            </div>
          </>
        )}

        <div className="lv-boardcol">{board}</div>

        {(!rightCollapsed || rightClosing) && (
          <>
            <div className={"lv-backdrop" + (rightClosing ? " closing" : "")} onClick={closeRightPanel} />
            <div className={"lv-panel right" + (rightClosing ? " closing" : "")}>
              <div className="lv-sidehead">
                <button className="lv-col" onClick={closeRightPanel} title="collapse">&#8250;</button>
                <div className="lv-tabs lv-sidetabs">{["Image", "Edit", "Reference", "Video"].map((t) => (
                  <span key={t} className={"lv-tab " + (t === tab ? "on" : "")} onClick={() => setTab(t)}>{t}</span>))}</div>
              </div>
              {gen}
            </div>
          </>
        )}

        <div className="lv-rail">
          {GEN_ICONS.map(([t, ic]) => (<button key={t} className={"lv-railbtn" + (!rightCollapsed && t === tab ? " on" : "")} title={t}
            onClick={() => { setTab(t); openRightPanel(); }}>{ic}</button>))}
        </div>
      </div>
      {/* ---- Filter compare -- The Loom.dc.html's own filterCompareOpen modal (a centered
          card, unlike LoomMobile's full-page screen -- desktop's real design spec, not a
          reused mobile layout). Opens from Generate's Edit tab -> Enhance sub-tab. */}
      {fcOpen && active && (() => {
        const c = active.c;
        const fcSrc = frameSrc(c.openFrame);
        const fcGroups = AF ? AF.groups() : [];
        const activeRec = fcActive && AF ? (AF.get(fcActive) || {}) : null;
        const activeName = activeRec ? (activeRec.name || fcActive) : null;
        return (
          <>
            <div className="lv-fc-veil" onClick={closeFilterCompare} />
            <div className="lv-fc-host">
              <div className="lv-fc-card">
                <div className="lv-fc-head">
                  <div className="lv-fc-title">&#9680; Art filters</div>
                  <span className="lv-dim" style={{ flex: "1 1 auto" }} />
                  <button type="button" className="lv-col" onClick={closeFilterCompare} title="Close">&#10005;</button>
                </div>
                {!AF ? (
                  <div className="lv-ph">The art-filter library did not load on this page.</div>
                ) : (
                  <div className="lv-fc-grid">
                    <div className="lv-fc-previewcol">
                      <div className="lv-fc-previewbox">
                        {fcSrc ? <img className="lv-fc-img" src={fcSrc} alt="original" /> : <div className="lv-ph">No open-frame image yet</div>}
                      </div>
                      <div className="lv-dim" style={{ textAlign: "center", paddingTop: 6 }}>Original</div>
                    </div>
                    <div className="lv-fc-previewcol">
                      <div className="lv-fc-previewbox">
                        <div className="lv-fc-stage" ref={fcStageRef}>
                          {fcSrc ? <img ref={fcImgRef} className="lv-fc-img" src={fcSrc} alt="preview" /> : <div className="lv-ph">No open-frame image yet</div>}
                        </div>
                      </div>
                      <div className="lv-dim" style={{ textAlign: "center", paddingTop: 6 }}>Preview &middot; <b style={{ color: "var(--text)" }}>{activeName || "no filter"}</b></div>
                    </div>
                    <div className="lv-fc-side">
                      {fcGroups.map((g) => (
                        <div key={g.source}>
                          <div className="lv-fc-grouplabel">{g.label}</div>
                          <div className="lv-fc-swatchgrid">
                            {g.ids.map((id) => {
                              const rec = AF.get(id) || {};
                              return (
                                <button type="button" key={id} className={"lv-fc-tile" + (fcActive === id ? " on" : "")}
                                  onClick={() => setFcActive((cur) => (cur === id ? null : id))}
                                  title={(rec.name || id) + " · free, applied in your browser" + (rec.note ? " — " + rec.note : "")}>
                                  <div className="lv-fc-swatch"
                                    ref={(el) => { if (el && !el._mgafPainted) { AF.renderSwatch(el, id); el._mgafPainted = true; } }} />
                                  <div className="lv-fc-name">{(rec.name || id).replace("Filter ", "")}</div>
                                </button>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                      <div>
                        <div className="lv-lab" style={{ margin: "4px 0" }}>Strength <b style={{ color: "var(--text)" }}>{Number(fcStrength).toFixed(2)}</b></div>
                        <input type="range" min="0" max="1" step="0.05" className="lv-fc-range"
                          value={fcStrength} onChange={(ev) => setFcStrength(parseFloat(ev.target.value))} />
                      </div>
                      <div>
                        <div className="lv-lab" style={{ margin: "4px 0" }}>Angle <b style={{ color: "var(--text)" }}>{fcAngle}&deg;</b></div>
                        <input type="range" min="0" max="360" step="1" className="lv-fc-range"
                          value={fcAngle} onChange={(ev) => setFcAngle(parseInt(ev.target.value, 10))} />
                      </div>
                      <div className="lv-fc-btnrow">
                        <button type="button" className="lv-mini2" onClick={fcClear}>No filter</button>
                        <button type="button" className="lv-go" style={{ padding: "9px 0" }} onClick={fcSave}>Save</button>
                      </div>
                      <div className="lv-dim" style={{ textAlign: "center" }}>{activeName || "No filter"} &middot; nothing sent, nothing spent</div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </>
        );
      })()}
      {deepFocus && (() => {
        // deepFocus itself is a one-time snapshot captured at double-click time -- setCard's
        // patches are immutable, so deepFocus.c never updates. Render from the LIVE entry
        // (re-derived from entries, which App() already recomputes every render) instead, or
        // every edit here would silently revert on the next keystroke while the board behind
        // the veil quietly shows the real change.
        const live = entries.find((x) => x.c.id === deepFocus.c.id);
        if (!live) { setDeepFocus(null); return null; }
        const dfPatch = (fn) => setCard(live.a.id, live.c.id, fn);
        const dfPatchFrame = (key, fp) => dfPatch((cc) => ({ ...cc, [key]: { ...cc[key], ...fp } }));
        const dfAppend = (field, val) => dfPatch((cc) => ({ ...cc, [field]: cc[field] ? `${cc[field]}, ${val}` : val }));
        const c = live.c;
        return (
          <div className="lv-df-veil" onClick={(ev) => { if (ev.target === ev.currentTarget) setDeepFocus(null); }}>
            <div className="lv-df">
              <div className="lv-df-head">
                <button className={"sb-tick " + c.status} title={`Status: ${c.status} (click to cycle${c.status === "error" ? " — clears the error" : ""})`}
                  onClick={() => dfPatch((cc) => ({ ...cc, status: cc.status === "todo" ? "wip" : cc.status === "wip" ? "done" : "todo" }))}>✓</button>
                <span className="lv-df-code">{deepFocus.code}</span>
                <input className="lv-df-title" value={c.title || ""} placeholder="untitled"
                  onChange={(ev) => dfPatch((cc) => ({ ...cc, title: ev.target.value }))} />
                <button className="lv-col" onClick={() => setDeepFocus(null)} title="Close (Esc)">&#10005;</button>
              </div>
              <div className="lv-df-row">
                <div className="lv-field"><label className="lv-lab">Mode</label>
                  <div className="lv-chips">{MODES.map((m) => (<span key={m} className={"lv-chip " + (m === c.mode ? "on" : "")}
                    // Deep Focus has no Continuity control of its own, but a shot can arrive here
                    // already set to connect:"flf" from the Generate-drawer editor -- setShotMode
                    // (loom-mutations.js) keeps the two fields coupled regardless of which surface
                    // touches them; see its comment for the bug this prevents.
                    onClick={() => dfPatch((cc) => setShotMode(cc, m))}>{m}</span>))}</div></div>
                <div className="lv-field narrow"><label className="lv-lab">Duration (s)</label>
                  <input className="lv-in" type="number" min="1" value={c.duration}
                    onChange={(ev) => dfPatch((cc) => ({ ...cc, duration: Number(ev.target.value) }))} /></div>
                <div className="lv-field narrow"><label className="lv-lab">Discreet</label>
                  <label className="sb-toggle" title="Blur this shot's frames/refs on the board">
                    <input type="checkbox" checked={c.discreet} onChange={(ev) => dfPatch((cc) => ({ ...cc, discreet: ev.target.checked }))} />blur previews</label></div>
              </div>
              {/* Base prompt. Deep Focus is A home for c.prompt, not the only one -- the
                  right panel's own Prompt field still writes it too. Editing the BASE prompt
                  here (not a per-shot override) is deliberate: it keeps hand-typed prompts
                  recomposable instead of freezing each one into an override. Placement --
                  after Mode/Duration/Discreet, before the frames -- keeps the field in the
                  same reading order on both surfaces. */}
              <div className="sb-field" style={{ marginTop: 10 }}>
                <label className="sb-lab">Prompt</label>
                <textarea className="lv-ta" value={c.prompt || ""} placeholder="what happens in this shot"
                  onChange={(ev) => {
                    // Same rule as the right panel's Prompt field: typing a base prompt means
                    // "auto-compose, using this text", so it clears an active drawer override.
                    //
                    // The flash matters MORE here than there. The panel's copy of the notice
                    // renders at .lv-overrideflash inside the right panel, which sits BEHIND
                    // .lv-df-veil (z-450) while Deep Focus is open -- so without the copy
                    // rendered below, editing here would destroy an override with no visible
                    // signal at all. That silent-until-you-notice failure is the exact hazard
                    // the flash was added for, and a second surface writing c.prompt would
                    // have quietly reintroduced it.
                    if (c.promptOverride) { setOverrideClearedFlash(true); setTimeout(() => setOverrideClearedFlash(false), 1600); }
                    dfPatch((cc) => ({ ...clearPromptOverride(cc), prompt: ev.target.value }));
                  }} />
                {overrideClearedFlash && <div className="lv-overrideflash">override cleared &mdash; back to auto-compose</div>}
                <span className="sb-hint">the shot's base prompt &mdash; Camera, Lighting and cast are woven in on top when it generates</span>
              </div>
              <div className="lv-df-frames">
                <FrameSlot which="open" frame={c.openFrame} liveTag={positionTag(live, project, imgSrc, "openFrame")} discreet={c.discreet} framePrev={frameSrc} storeThumb={storeThumb} openPick={openPick}
                  onPatch={(p) => dfPatchFrame("openFrame", p)} />
                <div className="sb-conn-mid">&#8594;</div>
                <FrameSlot which="close" frame={c.closeFrame} liveTag={positionTag(live, project, imgSrc, "closeFrame")} discreet={c.discreet} framePrev={frameSrc} storeThumb={storeThumb} openPick={openPick}
                  onPatch={(p) => dfPatchFrame("closeFrame", p)} />
              </div>
              <div className="sb-field">
                <label className="sb-lab">Other references &amp; @tags</label>
                {c.refs.map((r) => {
                  const preview = r.thumbId ? thumbs[r.thumbId] : (r.kind === "image" && r.source.startsWith("http") ? r.source : null);
                  // Same live-number treatment the Cast & assets rows got in round 2 (see
                  // castList's liveTag comment) -- round 2 left THESE rows showing only
                  // the stale stored r.tag, so a ref whose real position had shifted kept
                  // asserting a number the composed prompt and the drawer no longer use.
                  // Image refs only: @videoN/@audioN are their own namespaces, never
                  // renumbered by position -- there the stored tag IS the live name
                  // (shotText() prints it verbatim; see its video-ref comment), so a
                  // second "live" copy of it would be noise. Shares liveTagText/
                  // liveTagTitle with the cast rows so the two row types cannot drift.
                  const refLiveTag = r.kind === "image" ? positionTag(live, project, imgSrc, r.id) : null;
                  const refPastBudget = r.kind === "image" && !refLiveTag && !!resolvedImage(r, imgSrc);
                  return (
                    <div className="sb-ref" key={r.id}>
                      {r.kind === "image" ? (
                        <label className={"sb-refprev" + (c.discreet ? " discreet" : "")} title="Attach image">
                          {preview ? <img src={preview} alt={r.tag} /> : "＋"}
                          <input type="file" accept="image/*" style={{ display: "none" }}
                            onChange={async (e) => { const f = e.target.files[0]; if (!f) return; const id = await storeThumb(f); setRef(live.a.id, c.id, r.id, { thumbId: id, source: r.source || f.name }); }} /></label>
                      ) : <div className="sb-refprev">{r.kind === "video" ? "🎞" : "♪"}</div>}
                      <div className="sb-refbody">
                        <div style={{ display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap" }}>
                          <input className="sb-tagin sb-mono" value={r.tag} onChange={(e) => setRef(live.a.id, c.id, r.id, { tag: e.target.value })} />
                          {r.kind === "image" && (
                            <span className={"lv-livetag" + (refPastBudget ? " oob" : "")}
                              title={liveTagTitle(refLiveTag, refPastBudget, c.mode, live.code)}>
                              {liveTagText(refLiveTag, refPastBudget, c.mode)}
                            </span>
                          )}
                          <span className="sb-hint">{r.kind}</span>
                          <button className="sb-ico" style={{ marginLeft: "auto" }} onClick={() => delRef(live.a.id, c.id, r)}>✕</button>
                        </div>
                        <input className="sb-in" placeholder="what to use it for (motion / camera / mood…)" value={r.role} onChange={(e) => setRef(live.a.id, c.id, r.id, { role: e.target.value })} />
                        <input className="sb-in" placeholder="file name or URL" value={r.source} onChange={(e) => setRef(live.a.id, c.id, r.id, { source: e.target.value })} />
                      </div>
                    </div>
                  );
                })}
                <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
                  <button className="sb-btn sm ghost" onClick={() => addRef(live.a.id, c, "image")}>+ Image</button>
                  <button className="sb-btn sm ghost" onClick={() => addRef(live.a.id, c, "video")}>+ Video</button>
                  <button className="sb-btn sm ghost" onClick={() => addRef(live.a.id, c, "audio")}>+ Audio</button>
                </div>
              </div>
              <div className="sb-field"><label className="sb-lab">Music / audio cue <button className="sb-ico" style={{ fontSize: 11 }} onClick={() => setDfPalFor(dfPalFor === "audio" ? null : "audio")}>＋terms</button></label>
                <input className="sb-in" value={c.audioCue} onChange={(ev) => dfPatch((cc) => ({ ...cc, audioCue: ev.target.value }))} placeholder="track, beat sync, room tone…" />
                {dfPalFor === "audio" && <div className="sb-pal">{AUDIO_PALETTE.map((t) => <button key={t} className="sb-pchip sb-mono" onClick={() => dfAppend("audioCue", t)}>{t}</button>)}</div>}</div>
              <div className="sb-field"><label className="sb-lab">Notes</label>
                <textarea className="sb-ta" value={c.notes} onChange={(ev) => dfPatch((cc) => ({ ...cc, notes: ev.target.value }))} placeholder="blocking, continuity reminders…" /></div>
              <div className="sb-toolbar">
                <button className="sb-btn amber sm" onClick={() => copyShot(live)}>Copy shot</button>
              </div>
              <button className="lv-go" onClick={() => { setSelShot(c.id); setDeepFocus(null); }}>Select in Generate &rarr;</button>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

/* =========================================================================
   LOOM MOBILE -- first increment (2026-08-03). A phone-sized ALTERNATIVE to
   LoomV2, chosen by the "📱 Mobile view" toggle in LoomV2's own .lv-top bar
   (persisted via useLocalToggle/MOBILE_UI_KEY, see App()). Kept INLINE here
   rather than split into its own loom/src/loom-mobile.jsx file: unlike
   loom-core.js/loom-mutations.js (deliberately React-free, DOM-free, pure --
   see loom-core.js's own header -- so they can be `node --test`ed directly and
   so the Flask /loom route's Babel-standalone fallback can inline them ahead
   of the JSX by stripping their `export` keywords), LoomMobile IS a React
   component -- exactly the same category as LoomV2/ProjectSwitcher/ExportMenu/
   ShotPreview/SequencePlayer/ImportCollection/FrameSlot, every one of which
   already lives inline in this one file rather than as a separate module.
   A separate file would also need moonglade_gallery.py's loom() route taught
   to inline a THIRD file for the default (non-bundle) Babel path -- that
   route's inliner is hardcoded to exactly loom-core.js + loom-mutations.js
   (see its own comments), and a raw `import` surviving into that
   data-presets="react"-only <script type="text/babel"> blob is a hard
   SyntaxError in every browser (no ESM transform is loaded there) -- i.e. a
   third module would silently break the DEFAULT /loom page for every desktop
   user, not just anyone who opts into Mobile view. Matching the codebase's
   real, established convention (components inline, pure logic in src/) avoids
   that risk entirely and needs no Python change.

   Scope of THIS increment, per the locked design source (design_handoff/
   design_handoff_moonglade_suite/"Loom Mobile.dc.html", read in full before
   writing a line here): the top bar (back-link / title / Draft toggle), the
   horizontal reel/timeline scrub bar (pointer-drag, fraction-of-width math,
   floating preview card -- genuinely new for this codebase; LoomV2's own
   .lv-reel below is click-a-fixed-width-segment only, no drag, no preview),
   and the act-grouped shot board (add-shot/add-act). Deliberately NOT built
   yet (next increments): shot detail (Deep Focus's mobile equivalent), the
   Cast & assets sheet, Generate, Review & trim, Filter compare -- tapping a
   shot card this increment does the smallest real, honest thing available
   without any of those: it SELECTS the shot (setSelShot), matching the exact
   "Click a shot → it binds to Generate" contract LoomV2's own .lv-note
   already documents for the desktop board.
   ========================================================================= */
const LOOM_MOBILE_STYLES = `
.lm-root{position:fixed;inset:0;z-index:400;background:var(--mantle);color:var(--text);
  display:flex;flex-direction:column;font-family:system-ui,sans-serif;-webkit-font-smoothing:antialiased;}
.lm-top{flex:none;display:flex;align-items:center;gap:8px;flex-wrap:wrap;
  padding:max(10px,env(safe-area-inset-top)) 16px 8px;}
.lm-back{font:700 11.5px/1 system-ui;letter-spacing:.06em;text-transform:uppercase;
  color:var(--subtext);text-decoration:none;white-space:nowrap;background:none;border:none;cursor:pointer;padding:0;}
.lm-back:hover{color:var(--text);}
.lm-fill{flex:1 1 auto;}
.lm-title{font:700 11px/1 system-ui;letter-spacing:.08em;text-transform:uppercase;
  color:var(--subtext);white-space:nowrap;}
.lm-chip{display:inline-flex;align-items:center;gap:4px;font:600 10px/1 system-ui;
  color:var(--subtext);cursor:pointer;padding:6px 10px;border-radius:999px;
  border:1px solid var(--surface1);background:none;user-select:none;white-space:nowrap;}
.lm-chip:hover{border-color:var(--accent);color:var(--accent);}
.lm-chip.on{color:var(--gold);border-color:var(--gold);background:color-mix(in srgb,var(--gold) 15%,transparent);
  box-shadow:0 0 10px rgba(212,175,55,.35);}
.lm-chip input{margin:0;cursor:pointer;}
.lm-reelwrap{flex:none;padding:4px 16px 10px;position:relative;}
.lm-reelbar{display:flex;gap:3px;height:18px;border-radius:4px;cursor:pointer;touch-action:none;}
.lm-seg{border-radius:3px;height:100%;}
.lm-seg.todo{background:var(--surface1);}
.lm-seg.wip{background:var(--accent);}
.lm-seg.done{background:var(--emerald);}
.lm-seg.error{background:var(--red);}
.lm-seg.paused{background:var(--peach);}
.lm-seg.sel{outline:2px solid var(--text);outline-offset:-2px;}
.lm-tick{position:absolute;top:6px;bottom:12px;width:1px;background:rgba(255,255,255,.35);pointer-events:none;}
.lm-handle{position:absolute;top:13px;width:14px;height:14px;border-radius:50%;
  background:var(--accent);border:2px solid var(--text);transform:translate(-50%,-50%);
  box-shadow:0 1px 4px rgba(0,0,0,.5);pointer-events:none;}
.lm-scrubline{position:absolute;top:6px;bottom:12px;width:2px;background:var(--accent);
  box-shadow:0 0 6px color-mix(in srgb,var(--accent) 70%,transparent);pointer-events:none;}
.lm-preview{position:absolute;top:100%;margin-top:8px;z-index:10;display:flex;align-items:center;
  gap:8px;padding:7px 10px;border-radius:10px;background:var(--surface0);border:1px solid var(--surface1);
  box-shadow:0 10px 26px -8px rgba(0,0,0,.6);pointer-events:none;width:172px;box-sizing:border-box;}
.lm-prevthumb{width:34px;height:34px;border-radius:7px;flex:none;background-size:cover;
  background-position:center;background-color:var(--base);}
.lm-prevcol{min-width:0;display:flex;flex-direction:column;gap:2px;}
.lm-prevcode{font-family:ui-monospace,monospace;font-size:9px;color:var(--overlay0);}
.lm-prevtitle{font-size:11px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lm-prevmeta{font-size:9px;color:var(--subtext);}
.lm-body{flex:1 1 auto;overflow-y:auto;padding:0 16px 30px;-webkit-overflow-scrolling:touch;}
.lm-acthead{display:flex;align-items:baseline;gap:8px;padding:14px 0 8px;}
.lm-actname{font-family:Georgia,serif;font-style:italic;font-size:14px;color:var(--text);}
.lm-actcount{font-size:10px;color:var(--overlay0);}
.lm-addshot{font-size:10.5px;font-weight:700;color:var(--accent);cursor:pointer;background:none;border:none;padding:0;}
.lm-cardrow{position:relative;display:flex;align-items:center;gap:6px;margin-bottom:7px;}
.lm-card{flex:1 1 auto;min-width:0;display:flex;align-items:center;gap:10px;padding:8px 10px;
  border-radius:11px;border:1px solid var(--surface1);background:var(--surface0);cursor:pointer;
  text-align:left;font:inherit;color:inherit;}
.lm-card:hover,.lm-card:focus-visible{border-color:var(--accent);}
.lm-card.sel{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent) inset;}
.lm-thumb{width:48px;height:48px;border-radius:9px;flex:none;background-size:cover;
  background-position:center;background-color:var(--surface1);display:grid;place-items:center;
  font:700 9px/1 system-ui;color:var(--subtext);}
.lm-textcol{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:4px;}
.lm-titlerow{display:flex;align-items:baseline;gap:6px;min-width:0;}
.lm-code{font-family:ui-monospace,monospace;font-size:9.5px;color:var(--overlay0);flex:none;}
.lm-cardtitle{font-size:12.5px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lm-pillrow{display:flex;align-items:center;gap:6px;flex-wrap:wrap;}
.lm-modepill{font-size:9px;font-weight:700;padding:2px 6px;border-radius:5px;
  background:color-mix(in srgb,var(--accent) 15%,transparent);color:var(--accent);flex:none;}
.lm-durpill{font-size:9.5px;color:var(--subtext);flex:none;}
.lm-stpill{font-size:9px;font-weight:700;text-transform:uppercase;flex:none;}
.lm-stpill.done{color:var(--emerald);}
.lm-stpill.wip{color:var(--accent);}
.lm-stpill.todo{color:var(--overlay0);}
.lm-stpill.paused{color:var(--peach);}
.lm-stpill.error{color:var(--red);}
.lm-warn{font-size:9px;color:var(--peach);}
.lm-addact{text-align:center;font-size:11px;font-weight:700;color:var(--accent);padding:12px;
  border:1px dashed var(--surface1);border-radius:11px;cursor:pointer;margin-top:6px;background:none;width:100%;}
.lm-empty{text-align:center;color:var(--overlay0);font-size:11px;font-style:italic;padding:10px 6px;}

/* ---- Shot Detail (mobile Deep Focus) -- second increment, 2026-08-03 ---- */
@keyframes lmRise{from{opacity:0;transform:translateY(6px);}to{opacity:1;transform:none;}}
@keyframes lmSheetUp{from{transform:translateY(100%);}to{transform:translateY(0);}}
/* Loom Mobile.dc.html:18-21 -- the design's other 4 sheet/button animations, absent
   until 2026-08-06 (every sheet close was an instant unmount; primary buttons were
   flat). Close timing per the DC's own styles: sheet lmSheetDown .28s
   cubic-bezier(.4,0,.2,1) both, scrim lmFadeOut .28s / lmFadeIn .24s. */
@keyframes lmMetal{0%{background-position:0% 50%;}50%{background-position:100% 50%;}100%{background-position:0% 50%;}}
@keyframes lmSheetDown{from{transform:translateY(0);}to{transform:translateY(100%);}}
@keyframes lmFadeIn{from{opacity:0;}to{opacity:1;}}
@keyframes lmFadeOut{from{opacity:1;}to{opacity:0;}}
.lm-df{position:absolute;inset:0;z-index:20;background:var(--mantle);display:flex;flex-direction:column;
  animation:lmRise .22s ease both;}
.lm-df-top{flex:none;display:flex;align-items:center;gap:8px;
  padding:max(14px,env(safe-area-inset-top)) 16px 10px;}
.lm-df-title{flex:1 1 auto;min-width:0;background:transparent;border:none;
  border-bottom:1px solid var(--surface1);color:var(--text);font:600 14px/1.2 system-ui;padding:4px 0;}
.lm-df-title:focus{outline:none;border-bottom-color:var(--accent);}
.lm-df-st{flex:none;border-radius:5px;cursor:pointer;background:var(--base);border:1px solid var(--surface1);
  padding:4px 8px;}
.lm-df-cast{flex:none;font:700 11px/1 system-ui;padding:6px 9px;border-radius:8px;cursor:pointer;
  border:1px solid var(--surface1);background:var(--base);color:var(--subtext);white-space:nowrap;}
.lm-df-close{flex:none;width:28px;height:28px;display:flex;align-items:center;justify-content:center;
  border-radius:8px;border:1px solid var(--surface1);color:var(--subtext);cursor:pointer;background:none;
  font-size:13px;padding:0;}
.lm-df-body{flex:1 1 auto;overflow-y:auto;padding:4px 16px 30px;-webkit-overflow-scrolling:touch;}
.lm-microlab{display:block;font:700 9px/1 system-ui;text-transform:uppercase;color:var(--subtext);
  margin:10px 0 5px;}
.lm-hint{font-size:9.5px;color:var(--overlay0);padding:5px 2px 0;}
.lm-modechips{display:flex;gap:5px;}
.lm-modechip{flex:1;text-align:center;padding:8px 4px;border-radius:8px;font:700 11px/1 system-ui;
  cursor:pointer;border:1px solid var(--surface1);color:var(--subtext);background:none;}
.lm-modechip.on{background:color-mix(in srgb,var(--accent) 20%,transparent);border-color:var(--accent);
  color:var(--accent);}
.lm-row2{display:flex;gap:10px;margin:10px 0 4px;}
.lm-col{flex:1;min-width:0;}
.lm-in{width:100%;box-sizing:border-box;background:var(--base);border:1px solid var(--surface1);
  border-radius:8px;padding:8px 10px;color:var(--text);font:12.5px/1.3 system-ui;}
.lm-ta{width:100%;box-sizing:border-box;background:var(--base);border:1px solid var(--surface1);
  border-radius:9px;padding:10px;color:var(--text);font:12.5px/1.45 system-ui;resize:vertical;
  min-height:66px;}
.lm-check{display:flex;align-items:center;gap:7px;cursor:pointer;padding:8px 0 0;font-size:11px;
  color:var(--subtext);}
.lm-frow{display:flex;gap:10px;margin-top:16px;flex-wrap:wrap;}
.lm-fcol{flex:1 1 150px;min-width:150px;}
.lm-inheritbtn{margin-top:6px;display:inline-block;font-size:9.5px;font-weight:600;color:var(--accent);
  background:var(--surface1);border:none;border-radius:6px;padding:5px 8px;cursor:pointer;}
.lm-copybtn{display:inline-block;margin-top:18px;font:700 11px/1 system-ui;padding:8px 16px;
  border-radius:8px;cursor:pointer;border:1px solid color-mix(in srgb,var(--accent) 40%,transparent);
  background:color-mix(in srgb,var(--accent) 15%,transparent);color:var(--accent);}

/* Other references & @tags rows -- mirrors LoomV2's own sb-ref shape at mobile scale. */
.lm-refrow{display:flex;gap:10px;align-items:flex-start;background:var(--surface0);
  border:1px solid var(--surface1);border-radius:9px;padding:10px;margin-bottom:8px;}
.lm-refprev{width:52px;height:40px;border-radius:6px;border:1px solid var(--surface1);background:var(--base);
  flex:none;display:flex;align-items:center;justify-content:center;font-size:16px;overflow:hidden;
  cursor:pointer;}
.lm-refprev img{width:100%;height:100%;object-fit:cover;}
.lm-refbody{flex:1 1 auto;min-width:0;display:flex;flex-direction:column;gap:6px;}
.lm-reftoprow{display:flex;gap:7px;align-items:center;flex-wrap:wrap;}
.lm-reftag{font-family:ui-monospace,monospace;font-size:11px;color:var(--loomc,#47cbc3);background:var(--base);
  border:1px solid var(--surface1);border-radius:5px;padding:5px 6px;width:70px;}
.lm-refkind{font-size:9.5px;color:var(--subtext);}
.lm-refx{margin-left:auto;background:none;border:none;color:var(--subtext);font-size:14px;cursor:pointer;
  padding:0 2px;}
.lm-addrefrow{display:flex;gap:7px;flex-wrap:wrap;margin-top:4px;}
.lm-addrefbtn{font:700 10.5px/1 system-ui;padding:6px 11px;border-radius:999px;cursor:pointer;
  border:1px solid var(--surface1);background:var(--surface1);color:var(--text);}

/* ---- Cast & assets sheet (bottom sheet, opened from Shot Detail's 👥 button) ---- */
.lm-scrim{position:absolute;inset:0;z-index:30;background:rgba(3,2,8,.6);
  animation:lmFadeIn .24s ease both;}
.lm-scrim.closing{animation:lmFadeOut .28s ease both;}
.lm-sheet{position:absolute;left:0;right:0;bottom:0;z-index:31;background:var(--mantle);
  border-radius:18px 18px 0 0;border:1px solid var(--surface1);border-bottom:none;
  padding:12px 18px max(20px,env(safe-area-inset-bottom));max-height:75%;overflow-y:auto;
  animation:lmSheetUp .26s cubic-bezier(.2,.9,.24,1);}
.lm-sheet.closing{animation:lmSheetDown .28s cubic-bezier(.4,0,.2,1) both;}
.lm-sheethandle{width:36px;height:4px;border-radius:3px;background:rgba(255,255,255,.18);margin:0 auto 10px;}
.lm-tabsrow{display:flex;gap:4px;padding:3px;border-radius:9px;background:rgba(12,10,28,.6);
  border:1px solid var(--surface1);margin-bottom:10px;}
.lm-tabbtn{flex:1;text-align:center;padding:7px 4px;border-radius:7px;font:700 11px/1 system-ui;
  cursor:pointer;background:none;border:none;color:var(--subtext);}
.lm-tabbtn.on{background:color-mix(in srgb,var(--accent) 20%,transparent);color:var(--accent);}
.lm-budget{font-size:10.5px;color:var(--subtext);margin:4px 0 10px;}
.lm-budget-over{color:var(--peach);font-weight:700;}
.lm-i2vnote{font-size:10.5px;font-style:italic;color:var(--peach);margin:4px 0 10px;line-height:1.4;}
.lm-castrow{display:flex;align-items:center;gap:9px;padding:9px 4px;
  border:none;border-bottom:1px solid rgba(255,255,255,.06);cursor:pointer;background:none;
  width:100%;text-align:left;font:inherit;color:inherit;}
.lm-castbox{width:14px;height:14px;border-radius:4px;border:1px solid var(--surface1);flex:none;}
.lm-castbox.on{background:var(--accent);border-color:var(--accent);}
.lm-castthumb{width:30px;height:30px;border-radius:7px;flex:none;background-size:cover;
  background-position:center;background-color:var(--surface1);display:flex;align-items:center;
  justify-content:center;font-size:13px;}
.lm-castcol{flex:1 1 auto;min-width:0;}
.lm-castname{font-size:12px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lm-casttag{font-size:9.5px;font-family:ui-monospace,monospace;color:var(--loomc,#47cbc3);}
.lm-castmissing{font:700 9px/1 system-ui;color:var(--red);text-transform:uppercase;flex:none;}
.lm-castlive{flex:none;font:11px/1.3 ui-monospace,monospace;color:var(--loomc,#47cbc3);background:var(--base);
  border:1px dashed var(--overlay0);border-radius:6px;padding:5px 6px;}
.lm-castlive.oob{color:var(--peach);border-color:var(--peach);font-size:9px;}
.lm-castlock{font-size:11px;flex:none;}
.lm-castaddrow{display:flex;gap:8px;margin-top:10px;}
.lm-footagegrid{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:4px;}
.lm-fclip{border-radius:8px;overflow:hidden;border:1px solid var(--surface1);cursor:pointer;background:var(--base);}
.lm-fclip img{width:100%;aspect-ratio:16/10;object-fit:cover;display:block;}
.lm-fclipmeta{display:flex;justify-content:space-between;padding:5px 7px;font-size:9.5px;color:var(--subtext);}
.lm-sheetclose{margin-top:12px;text-align:center;padding:11px;border-radius:11px;
  border:1px solid var(--surface1);font:700 12.5px/1 system-ui;color:var(--subtext);cursor:pointer;
  background:none;width:100%;}

/* ---- Generate (third increment, 2026-08-03) -- opened from Shot Detail's own
   "Select in Generate →" button, matching the locked design's genOpen full-screen page. ---- */
.lm-gen{position:absolute;inset:0;z-index:25;background:var(--mantle);display:flex;flex-direction:column;
  animation:lmRise .22s ease both;}
.lm-gen-top{flex:none;display:flex;align-items:center;gap:8px;
  padding:max(14px,env(safe-area-inset-top)) 16px 10px;}
.lm-gen-back{flex:none;font:700 11.5px/1 system-ui;letter-spacing:.04em;color:var(--subtext);
  background:none;border:none;cursor:pointer;padding:0;white-space:nowrap;}
.lm-gen-back:hover{color:var(--text);}
.lm-gen-title{flex:1 1 auto;min-width:0;font:600 13px/1.2 system-ui;color:var(--text);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lm-gen-body{flex:1 1 auto;overflow-y:auto;padding:4px 16px 30px;-webkit-overflow-scrolling:touch;}
.lm-genbtn{display:block;width:100%;box-sizing:border-box;margin-top:12px;
  border:1px solid rgba(255,255,255,.3);
  color:color-mix(in oklab,var(--accent) 26%,#08040f);
  text-shadow:0 1px 0 rgba(255,255,255,.4);
  background:linear-gradient(100deg,color-mix(in oklab,var(--accent) 50%,#06030d) 0%,var(--accent) 18%,color-mix(in oklab,var(--accent) 22%,#ffffff) 34%,var(--accent) 50%,color-mix(in oklab,var(--accent) 74%,#06030d) 68%,var(--mauve) 84%,color-mix(in oklab,var(--accent) 50%,#06030d) 100%);
  background-size:220% 100%;animation:lmMetal 7s ease-in-out infinite;
  box-shadow:inset 0 1px 0 rgba(255,255,255,.6),inset 0 -2px 4px rgba(10,5,20,.45),0 6px 16px rgba(0,0,0,.45);
  border-radius:9px;padding:11px;font:800 12.5px/1 system-ui;cursor:pointer;
  text-align:center;}
.lm-genbtn:hover{filter:brightness(1.08);}
.lm-genbtn:disabled{opacity:.5;cursor:default;animation:none;}
@media (prefers-reduced-motion:reduce){.lm-genbtn{animation:none;}}
.lm-genexisting{display:block;width:100%;box-sizing:border-box;margin-top:7px;background:transparent;
  color:var(--subtext);border:1px solid var(--surface1);border-radius:8px;padding:9px;font:600 11px/1 system-ui;
  cursor:pointer;text-align:center;}
.lm-genexisting:hover{border-color:var(--accent);color:var(--accent);}
.lm-genexisting:disabled{opacity:.5;cursor:default;}
.lm-gentermbtn{font-size:9px;text-transform:none;letter-spacing:0;color:var(--accent);background:none;
  border:none;cursor:pointer;text-decoration:underline;text-underline-offset:2px;margin-left:6px;}
.lm-gentermpal{display:flex;flex-wrap:wrap;gap:4px;margin:5px 0 8px;padding:7px;background:var(--surface0);
  border-radius:7px;}
.lm-gentermgrp{width:100%;display:flex;flex-wrap:wrap;gap:4px;align-items:center;}
.lm-gentermgrpt{width:100%;font-size:8px;letter-spacing:.05em;text-transform:uppercase;color:var(--overlay0);
  margin-top:4px;}
.lm-genchip{font-family:ui-monospace,monospace;font-size:10px;color:var(--subtext);background:var(--base);
  border:1px solid var(--surface1);border-radius:5px;padding:3px 7px;cursor:pointer;}
.lm-genchip:hover{border-color:var(--accent);color:var(--accent);}
.lm-genrefline{font-size:10.5px;color:var(--subtext);margin:8px 0 2px;line-height:1.5;}
.lm-genframerow{display:flex;gap:10px;margin-top:8px;flex-wrap:wrap;}
.lm-genframecol{flex:1 1 130px;min-width:130px;}
.lm-genframe{height:90px;border-radius:8px;border:1px solid var(--surface1);background:var(--base);
  overflow:hidden;display:flex;align-items:center;justify-content:center;color:var(--overlay0);
  font-size:10.5px;position:relative;}
.lm-genframe img{width:100%;height:100%;object-fit:cover;}
.lm-genframetag{position:absolute;left:5px;bottom:5px;font-family:ui-monospace,monospace;font-size:9px;
  color:#fff;background:rgba(0,0,0,.55);padding:1px 5px;border-radius:5px;}
.lm-genpreview{font-size:10.5px;font-style:italic;color:var(--subtext);background:var(--base);
  border:1px dashed var(--surface1);border-radius:8px;padding:8px 10px;line-height:1.5;margin:6px 0 8px;
  white-space:pre-wrap;}
.lm-genoverride{font-size:11px;color:var(--gold);margin-top:4px;}
.lm-genflash{font-size:10.5px;color:var(--gold);background:rgba(0,0,0,.15);border-radius:5px;padding:4px 7px;
  margin-top:4px;}
/* Video tab's static model row + capability badges -- Loom Mobile.dc.html:854/856-857/930's
   own literal values (engineThumb gradient, caps chip chrome). */
.lm-genmodelrow{display:flex;align-items:center;padding:8px 10px;border-radius:8px;
  background:var(--base);border:1px solid var(--surface1);font:600 12px/1.2 system-ui;color:var(--text);}
.lm-genmodelthumb{width:26px;height:26px;border-radius:6px;flex:none;
  background:linear-gradient(150deg,#643aac 0%,#241f5b 100%);margin-right:8px;}
.lm-gencaps{display:flex;flex-wrap:wrap;gap:5px;margin:6px 0;}
.lm-gencap{font:600 9px/1.2 system-ui;padding:3px 7px;border-radius:5px;
  border:1px solid var(--surface1);background:rgba(33,31,58,.6);color:var(--subtext);}
.lm-gencost{display:flex;flex-direction:column;gap:2px;margin-top:14px;}
.lm-gencosttext{font-size:12px;font-weight:700;color:var(--emerald);}
.lm-gensel{width:100%;box-sizing:border-box;background:var(--base);border:1px solid var(--surface1);
  border-radius:8px;padding:8px 10px;color:var(--text);font:12.5px/1.3 system-ui;margin-top:6px;}

/* ---- Image/Edit/Reference tabs -- fourth increment (2026-08-03), added to the SAME
   Generate screen the third increment built. Reuses lm-in/lm-ta/lm-check/lm-row2/lm-col/
   lm-genbtn/lm-microlab/lm-hint/lm-genframe/lm-gencost*/lm-gensel unchanged; the classes
   below are the ones this increment's new fields genuinely need and nothing existing
   already covers. ---- */
.lm-bal{font-size:10.5px;color:var(--text);padding:6px 0;border-top:1px solid var(--surface1);
  border-bottom:1px solid var(--surface1);opacity:.85;}
.lm-selrow{display:flex;align-items:center;gap:8px;width:100%;box-sizing:border-box;padding:8px 10px;
  border-radius:8px;background:var(--base);border:1px solid var(--surface1);color:var(--text);
  cursor:pointer;font:12.5px/1.3 system-ui;text-align:left;}
.lm-selthumb{width:26px;height:26px;border-radius:6px;object-fit:cover;flex:none;}
.lm-selname{flex:1 1 auto;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lm-selhint{flex:none;font-size:10px;color:var(--subtext);}
.lm-caps{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px;}
.lm-cap{font-size:9.5px;padding:2px 8px;border-radius:10px;background:var(--base);
  border:1px solid var(--surface1);color:var(--subtext);}
.lm-cap.method{color:var(--gold);border-color:var(--gold);}
.lm-loras{display:flex;flex-direction:column;gap:5px;margin:8px 0 4px;}
.lm-lchip{display:flex;align-items:center;flex-wrap:wrap;gap:7px;padding:6px 8px;border-radius:7px;
  background:var(--surface0);border:1px solid var(--surface1);font-size:10.5px;color:var(--text);}
.lm-lchip.failed{border-color:var(--red);}
.lm-lnm{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lm-lchip.failed .lm-lnm{color:var(--red);}
.lm-lw{display:flex;align-items:center;gap:6px;flex:0 0 auto;}
.lm-lw input[type=range]{width:78px;}
.lm-lw b{min-width:28px;text-align:right;font-size:11px;font-weight:600;color:var(--gold);
  font-variant-numeric:tabular-nums;}
.lm-lrm{background:none;border:none;color:var(--subtext);cursor:pointer;font-size:14px;padding:0 2px;}
.lm-lrm:hover{color:var(--red);}
.lm-lorver{flex:1 1 100%;background:var(--base);border:1px solid var(--surface1);border-radius:5px;
  color:var(--text);font-size:10px;padding:4px 6px;}
.lm-mini2-btn{font-size:10px;color:var(--accent);background:none;border:none;cursor:pointer;
  text-decoration:underline;text-underline-offset:2px;padding:6px 0 0;display:block;}
.lm-gerr{font-size:10.5px;color:var(--red);margin-top:6px;}
.lm-imgresult{margin-top:10px;border:1px solid var(--surface1);border-radius:9px;padding:8px;}
.lm-imgresult>img{width:100%;border-radius:7px;display:block;}
.lm-route{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;}
.lm-routebtn{font:600 10px/1 system-ui;padding:6px 9px;border-radius:6px;border:1px solid var(--surface1);
  background:var(--surface1);color:var(--subtext);cursor:pointer;}
.lm-routebtn.on{background:color-mix(in srgb,var(--accent) 22%,transparent);border-color:var(--accent);
  color:var(--accent);}
.lm-ok2{font-size:10px;color:var(--accent);margin-top:6px;}
.lm-refstrip{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0 2px;}
.lm-refstrip img{width:44px;height:44px;object-fit:cover;border-radius:7px;border:1px solid var(--surface1);}

/* ---- Fixer (face/hand touch-up repair) -- closes the last disclosed gap in Loom Mobile's
   original 6-increment plan (2026-08-03). Lives inside Generate's Edit tab, alongside the
   Edit/Enhance sub-strip (now Edit/Fixer/Enhance -- see LoomMobile's own comment). The
   canvas overlay is a real, working port of gallery/src/components/FixTab.jsx's own
   .gd-fixwrap: an <img> in normal flow (sets the wrapper's real rendered height) with a
   same-sized <canvas> absolutely positioned on top, so canvas pixel coordinates and the
   image's own displayed pixels are the SAME coordinate space -- exactly what
   scaleFixBoxes() needs to convert them to original-image pixels afterward. .lm-fixhint/
   .lm-fixwarn colors/sizes are copied verbatim from the locked design's own real
   fixHintStyle/fixWarnStyle strings (Loom Mobile.dc.html's data-dc-script), not
   re-guessed. Face/Hand tag chips reuse .lm-modechips/.lm-modechip (the same chip visual
   language MODES/CONNECT already use in the Video tab) rather than inventing a second
   chip style. */
.lm-fixwrap{position:relative;border-radius:8px;overflow:hidden;background:var(--base);
  border:1px solid var(--surface1);margin-top:4px;}
.lm-fixwrap img{width:100%;display:block;}
.lm-fixwrap canvas{position:absolute;inset:0;width:100%;height:100%;touch-action:none;cursor:crosshair;}
.lm-fixhint{font-size:10.5px;line-height:1.5;color:var(--subtext);margin:12px 0 8px;}
.lm-fixwarn{font-size:10px;line-height:1.45;color:var(--peach);background:rgba(232,147,95,.08);
  border:1px solid rgba(232,147,95,.3);border-radius:8px;padding:7px 9px;margin-top:10px;}

/* Model/LoRA picker sheet -- a near-full-screen mobile sheet (unlike the half-height Cast
   sheet: <ModelPicker>'s search+grid genuinely needs the room), wrapping the SAME real
   custom element LoomV2's floating .lv-mpick-veil overlay uses. */
.lm-pick-sheet{position:absolute;left:0;right:0;bottom:0;top:6%;z-index:32;background:var(--mantle);
  border-radius:18px 18px 0 0;border:1px solid var(--surface1);border-bottom:none;
  padding:12px 16px max(14px,env(safe-area-inset-bottom));display:flex;flex-direction:column;min-height:0;
  animation:lmSheetUp .26s cubic-bezier(.2,.9,.24,1);}
.lm-pick-sheet.closing{animation:lmSheetDown .28s cubic-bezier(.4,0,.2,1) both;}
.lm-pick-head{flex:none;display:flex;align-items:center;gap:8px;margin-bottom:8px;}
.lm-pick-t{flex:1 1 auto;font-size:14px;font-weight:600;color:var(--text);}
.lm-pick-body{flex:1;min-height:0;display:flex;flex-direction:column;}
.lm-pick-body .model-picker{flex:1;min-height:0;}

/* ---- Review & trim (fifth increment, 2026-08-03) -- opened from the board's own ▶ badge
   on a finished shot, matching the locked design's reviewOpen/cropping/playing full-screen
   page. Reuses .lm-gen-top/.lm-gen-back/.lm-gen-title/.lm-df-close/.lm-df-body/.lm-microlab/
   .lm-hint/.lm-addrefbtn unchanged -- the classes below are only the ones this screen's own
   preview/transport/scrub/trim/crop chrome genuinely needs. */
.lm-reviewbadge{position:absolute;top:8px;left:10px;width:48px;height:48px;z-index:2;
  display:flex;align-items:center;justify-content:center;font-size:15px;color:#fff;
  background:rgba(0,0,0,.28);border:none;border-radius:9px;cursor:pointer;padding:0;}
.lm-review{position:absolute;inset:0;z-index:22;background:var(--mantle);display:flex;
  flex-direction:column;animation:lmRise .22s ease both;}
.lm-review-previewwrap{position:relative;width:100%;aspect-ratio:16/9;border-radius:10px;
  overflow:hidden;background:var(--base);margin-top:4px;}
.lm-review-video{width:100%;height:100%;object-fit:contain;background:var(--base);display:block;}
.lm-review-croprect{position:absolute;border:2px solid #fff;box-shadow:0 0 0 999px rgba(0,0,0,.45);
  cursor:grab;touch-action:none;}
.lm-review-crophandle{position:absolute;right:-3px;bottom:-3px;width:12px;height:12px;
  border-radius:50%;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.5);}
.lm-review-playbtn{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
  width:52px;height:52px;border-radius:50%;border:none;background:rgba(0,0,0,.4);color:#fff;
  font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center;}
.lm-review-transport{display:flex;align-items:center;justify-content:center;gap:14px;margin-top:10px;}
.lm-review-transportbtn{width:40px;height:40px;border-radius:50%;border:1px solid var(--surface1);
  background:var(--surface0);color:var(--text);font-size:15px;cursor:pointer;
  display:flex;align-items:center;justify-content:center;padding:0;}
.lm-review-transportbtn:hover{border-color:var(--accent);color:var(--accent);}
.lm-review-scrubtrack{position:relative;height:6px;border-radius:3px;background:var(--surface1);
  cursor:pointer;touch-action:none;margin:2px 0 4px;}
.lm-review-scrubfill{position:absolute;top:0;left:0;height:100%;border-radius:3px;background:var(--accent);
  pointer-events:none;}
.lm-review-scrubhandle{position:absolute;top:50%;width:14px;height:14px;border-radius:50%;
  background:var(--accent);border:2px solid var(--text);transform:translate(-50%,-50%);
  box-shadow:0 1px 4px rgba(0,0,0,.5);pointer-events:none;}
.lm-review-trimtrack{position:relative;height:18px;border-radius:5px;background:var(--surface1);
  margin:2px 0 4px;}
.lm-review-trimrange{position:absolute;top:50%;transform:translateY(-50%);height:5px;border-radius:3px;
  background:var(--accent);pointer-events:none;}
.lm-review-trimhandle{position:absolute;top:50%;width:18px;height:18px;border-radius:5px;
  background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.5);transform:translate(-50%,-50%);
  cursor:ew-resize;touch-action:none;}
.lm-review-trimreadout{font-family:ui-monospace,monospace;font-size:10.5px;color:var(--subtext);
  margin-top:2px;}
.lm-review-actionsrow{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px;}
.lm-review-cropbtn{font:700 10.5px/1 system-ui;padding:6px 12px;border-radius:999px;cursor:pointer;
  border:1px solid var(--surface1);background:var(--surface1);color:var(--text);}
.lm-review-cropbtn.on{background:color-mix(in srgb,var(--accent) 22%,transparent);
  border-color:var(--accent);color:var(--accent);}

/* ---- Filter compare -- sixth and FINAL increment (2026-08-03), the locked design's own
   "Art filters" screen (filterCompareOpen/fcSkinFilters/fcPixaiFilters/fcStrength/fcAngle).
   Reuses .lm-gen-top/.lm-gen-back/.lm-gen-title/.lm-fill/.lm-df-close (top bar),
   .lm-tabsrow/.lm-tabbtn (Edit/Enhance sub-strip -- same classes the Cast sheet's own
   Cast/Footage strip and the model picker's Models/LoRAs strip already use), .lm-df-body/
   .lm-microlab/.lm-hint/.lm-empty (body chrome) unchanged. Everything below is only what
   this screen's own preview/swatch-grid/slider chrome genuinely needs. */
.lm-openfiltersbtn{display:block;width:100%;box-sizing:border-box;text-align:center;padding:12px;
  border-radius:9px;font:700 12px/1 system-ui;cursor:pointer;border:1px solid var(--surface1);
  background:color-mix(in srgb,var(--accent) 14%,transparent);color:var(--accent);margin-top:8px;}
.lm-fc{position:absolute;inset:0;z-index:26;background:var(--mantle);display:flex;
  flex-direction:column;animation:lmRise .22s ease both;}
.lm-fc-previewrow{display:flex;gap:8px;margin:4px 0 16px;}
.lm-fc-previewcol{flex:1;min-width:0;}
.lm-fc-previewbox{position:relative;width:100%;aspect-ratio:1;border-radius:10px;
  overflow:hidden;background:var(--base);border:1px solid var(--surface1);
  display:flex;align-items:center;justify-content:center;}
/* .mgaf-stage (mg-art-filters.js's own injected stylesheet) already supplies
   position:relative + isolation:isolate -- the load-bearing line for mix-blend-mode -- the
   moment AF.applyPreview() touches this element; width/height:100% is this screen's own
   layout need on top of that, not a replacement for it. */
.lm-fc-stage{position:relative;width:100%;height:100%;}
.lm-fc-img{width:100%;height:100%;object-fit:cover;display:block;}
.lm-fc-previewcap{font-size:10px;color:var(--subtext);text-align:center;padding-top:6px;}
.lm-fc-grouplabel{font:700 9px/1 system-ui;letter-spacing:.1em;text-transform:uppercase;
  color:var(--overlay0);margin:0 0 6px;}
.lm-fc-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:16px;}
.lm-fc-tile{display:flex;flex-direction:column;gap:3px;cursor:pointer;border-radius:9px;
  padding:3px;border:1px solid transparent;background:none;font:inherit;}
.lm-fc-tile.on{border-color:var(--accent);}
/* Fallback paint only -- AF.renderSwatch() overwrites this with the filter's own real
   gradient layers (via .mgaf-swatch, injected by mg-art-filters.js itself) the instant its
   ref callback fires. */
.lm-fc-swatch{width:100%;aspect-ratio:1;border-radius:7px;background:var(--surface1);}
.lm-fc-name{font-size:8.5px;text-align:center;padding:3px 1px 0;color:var(--subtext);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lm-fc-sliderwrap{margin-bottom:14px;}
.lm-fc-sliderlab{font:700 9px/1 system-ui;letter-spacing:.08em;text-transform:uppercase;
  color:var(--overlay0);margin-bottom:5px;}
.lm-fc-range{width:100%;height:3px;cursor:pointer;}
.lm-fc-btnrow{display:flex;gap:8px;margin-bottom:10px;}
.lm-fc-btn{flex:1;text-align:center;padding:11px;border-radius:9px;font:700 11.5px/1 system-ui;
  cursor:pointer;border:1px solid var(--surface1);background:rgba(33,31,58,.6);color:var(--text);}
.lm-fc-btn.primary{border-color:rgba(255,255,255,.3);background:var(--accent);color:var(--base);}
.lm-fc-spendnote{font-size:10px;color:var(--overlay0);text-align:center;}

/* ---- Kebab actions sheet (completeness pass, 2026-08-03) -- the locked design's own
   card.onKebab/actionsOpen/actMoveUp/actMoveDown/actDuplicate/actDelete (Loom Mobile.dc.html),
   the one board-card affordance never wired into this view before now. Reuses .lm-scrim/
   .lm-sheet/.lm-sheethandle/.lm-sheetclose verbatim -- the Cast & assets sheet's own bottom-
   sheet convention -- only the row styling below (matching the design's own actionRowStyle/
   actionRowDangerStyle) is new. */
.lm-kebab{flex:none;width:30px;height:30px;display:flex;align-items:center;justify-content:center;
  font-size:16px;color:var(--overlay0);cursor:pointer;background:none;border:none;padding:0;}
.lm-actionrow{display:block;width:100%;text-align:left;padding:12px 4px;font:13px/1.3 system-ui;
  color:var(--text);border:none;border-bottom:1px solid rgba(255,255,255,.06);background:none;cursor:pointer;}
.lm-actionrow.danger{color:var(--red);border-bottom:none;}
`;

function LoomMobile({ project, entries, thumbs, genState, selShot, setSelShot, addCard, addAct, setDraft,
  mobileUI, setMobileUI,
  // Second increment (2026-08-03): Shot Detail (Deep Focus's mobile equivalent), the
  // Cast & assets sheet, and the Frame picker all need to actually MUTATE the project and
  // reach the real gallery picker -- setCard/setAssets/addRef/setRef/delRef (useShotMutations),
  // storeThumb (useProjectStore), and openPick/copyShot (App() itself) are the same real
  // functions LoomV2 already uses for its own Deep Focus/Cast&Assets/FrameSlot; threaded
  // straight through, nothing new invented.
  setCard, setAssets, addRef, setRef, delRef, storeThumb, openPick, copyShot,
  // Fifth increment (2026-08-03): Review & trim's own "✂ Split at playhead" needs the exact
  // same real splitCardAt-backed mutator LoomV2's own ShotPreview.onSplit already calls
  // (useShotMutations) -- not a re-derivation of the split logic.
  splitShot,
  // Completeness-pass addition (2026-08-03): the per-shot-card kebab (⋮) actions sheet
  // (Move up / Move down / Duplicate / Delete) was fully specified in the locked design
  // (Loom Mobile.dc.html: onKebab/actionsOpen/actMoveUp/actMoveDown/actDuplicate/actDelete)
  // but never wired into this component -- moveCard/dupCard/delCard are the EXACT same real
  // mutators LoomV2's own board-card buttons already call (useShotMutations, App()), threaded
  // through for the first time here rather than re-derived. delCard's real window.confirm
  // gate is preserved verbatim at its one call site below, not dropped for mobile.
  moveCard, dupCard, delCard,
  // Not read by earlier increments' Generate-less screens -- lifted to App() (see LoomV2's own
  // prop-list comment) and threaded through here so a still-in-progress draft already
  // survives toggling between this view and LoomV2.
  draftCard, setDraftCard, draftTarget, setDraftTarget, draftAttachedInfo, setDraftAttachedInfo,
  // Third increment (2026-08-03): Generate. Real, unmodified functions from
  // useGenerationPipeline -- generateShot (real submit: its own price-check + confirm +
  // /api/loom/generate + pollShot registration, the SAME function batchGenerate's per-card
  // loop already calls), priceShot (the SAME read-only /api/price check confirmSpend/
  // batchGenerate already use for a preview), and useExistingVideo (attach an
  // already-rendered gallery video as the finished clip, no generation, no spend -- already
  // wired to LoomV2's own board). No new submit call, no new pricing math, no forked spend
  // path: this screen is a new VIEW onto the exact same pipeline LoomV2 already drives.
  generateShot, priceShot, useExistingVideo,
  // Fourth increment (2026-08-03): Image/Edit/Reference/Video, mirroring LoomV2's own
  // right-rail GEN_ICONS strip (its "Video" tab is what the third increment above already
  // built, using generateShot/priceShot rather than <mg-generate-drawer> -- see this
  // increment's report for why that stays the right call here too). Every one of these is
  // the SAME hook-level state/function LoomV2 already reads/calls for its Image/Edit/
  // Reference tabs -- genImage/genEdit/genRef (and their genImgState/genEditState/
  // genRefState) are plain fetch+setTimeout closures living in useGenerationPipeline, not
  // tied to any DOM element's lifecycle, so (unlike the drawer) they already survive the
  // Mobile-view toggle with no fix needed -- confirmed by reading pollImg/
  // pollTaskWithCeiling, not assumed. No forked submit logic, no reinvented pricing, no new
  // endpoints: this screen calls the exact same functions LoomV2's Image/Edit/Reference
  // tab bodies call.
  genImgState, imgModel, setImgModel, imgLoras, setImgLoras, imgAdv, setImgAdv,
  modelDefaults, setModelDefaults, genImage, routeImg,
  genEditState, setGenEditState, genRefState, setGenRefState, genEdit, genRef, routeGen,
  // Fixer -- seventh increment (2026-08-03). Same real hook-level state/function shape as
  // genEditState/genEdit above (useGenerationPipeline): genFixState is a plain cardId->
  // {phase,msg,mid,routed} dict, genFix is the real confirm-gated submit through the real
  // /api/fix endpoint. Threaded through for the first time here -- desktop's LoomV2 has no
  // Fixer tab of its own (out of this increment's scope), so only LoomMobile receives it.
  genFixState, setGenFixState, genFix }) {
  // The overlay is position:fixed and covers the whole viewport, but the classic page
  // underneath is a normal tall document -- same reasoning, same fix, as LoomV2's own
  // identical effect (see its comment): without this, a touch/wheel scroll that isn't
  // captured by .lm-body (already at its own scroll limit) bubbles up and scrolls THAT.
  useEffect(() => {
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prevOverflow; };
  }, []);

  // imgSrc/frameSrc mirror LoomV2's own private copies exactly (see LoomV2's imgSrc comment)
  // -- each consumer in this file closes over its OWN `thumbs` prop rather than sharing one
  // implementation, which is the established pattern here, not an oversight.
  const imgSrc = (thumbId, source) => thumbId ? thumbs[thumbId]
    : (source && (source.startsWith("http") || source.startsWith("data:") || isCatalogMediaId(source)) ? source : null);
  const frameSrc = (f) => (f && f.thumbId ? thumbs[f.thumbId] : (f && f.mediaId ? "/thumbs/" + f.mediaId + ".jpg" : null));
  const cardThumb = (c) => frameSrc(c.openFrame) || (c.resultMid ? "/thumbs/" + c.resultMid + ".jpg" : null);
  // Real, shared, offline art-filter library (static/mg-art-filters.js) -- PixAI's own 7
  // gradient-overlay recipes plus this app's own 5, composited entirely client-side (no
  // network call, no credit spend). Read fresh each render rather than memoized: it is a
  // load-once global singleton (script tag in _LOOM_SHELL, loaded before this bundle), so
  // every render sees the same object reference. See Filter compare's own comment (below,
  // with this component's other hooks) for why this screen uses it instead of a simplified
  // local recipe.
  const AF = MgArtFilters;   // was window.MgArtFilters (static/mg-art-filters.js), now bundled
  // Single source of truth for "what status does this shot show right now", shared by BOTH
  // the reel segment's color and the board card's status pill -- computed once per entry
  // rather than twice, so the two can never silently disagree (the exact two-implementations-
  // of-one-idea drift this codebase's own loom-core.js header spends its whole first comment
  // warning against). "paused" mirrors LoomV2's own board-card logic verbatim: a live
  // genState phase of "paused" means auto-checking genuinely stopped; any other in-flight
  // phase still just reads as the ordinary "wip" look, and only a settled state falls back to
  // the shot's own persisted c.status.
  const statusOf = (c) => {
    const gs = genState[c.id];
    const paused = gs && gs.phase === "paused";
    return paused ? "paused" : (gs && gs.phase && gs.phase !== "done" && gs.phase !== "error" ? "wip" : c.status);
  };

  // ---- Shot Detail (mobile Deep Focus) + Cast & assets sheet -- second increment
  // (2026-08-03), per the locked design (design_handoff/design_handoff_moonglade_suite/
  // "Loom Mobile.dc.html"). Tapping a board card (below) now opens this full-screen editor
  // for that shot, on top of setSelShot's own "binds to Generate" contract from increment 1
  // -- selecting a shot and opening its detail are the same tap, not two separate actions.
  const [dfOpen, setDfOpen] = useState(false);
  // Splice-in-last-frame state for the opening frame's "inherit previous close" button --
  // mirrors LoomV2's own local `handoff` state (see its FrameSlot extraBtn) exactly:
  // '' | 'wip' | 'err'.
  const [dfHandoff, setDfHandoff] = useState("");
  const [castSheetOpen, setCastSheetOpen] = useState(false);
  const [castSheetTab, setCastSheetTab] = useState("cast");   // 'cast' | 'footage'
  // Sheet-close choreography -- Loom Mobile.dc.html's own *Closing states (lmSheetDown
  // .28s + lmFadeOut on the scrim), absent until 2026-08-06: every close was an instant
  // unmount. Same closing-state + ref-held-timer pattern LoomV2's closeLeftPanel/
  // closeRightPanel already establish (340ms there, the DC's own 280ms here).
  const [castSheetClosing, setCastSheetClosing] = useState(false);
  const castSheetCloseTimer = useRef(null);
  const closeCastSheet = () => {
    setCastSheetClosing(true);
    clearTimeout(castSheetCloseTimer.current);
    castSheetCloseTimer.current = setTimeout(() => { setCastSheetOpen(false); setCastSheetClosing(false); }, 280);
  };

  // ---- Kebab actions sheet (completeness pass, 2026-08-03) -- the locked design's own
  // per-card ⋮ menu (Loom Mobile.dc.html: onKebab/actionsOpen/actMoveUp/actMoveDown/
  // actDuplicate/actDelete), disclosed as a real, unbuilt gap left after the six increments
  // above. Purely local, ephemeral "is this sheet showing" state, same category as
  // dfOpen/castSheetOpen/reviewOpen -- which shot it targets reuses selShot (see actionsLive
  // below), not a second locally-tracked id like the design's own `actionsFor`.
  const [actionsOpen, setActionsOpen] = useState(false);
  const [actionsClosing, setActionsClosing] = useState(false);
  const actionsCloseTimer = useRef(null);

  // ---- Review & trim -- fifth increment (2026-08-03), per the locked design's own
  // reviewFor/cropping/playing state (Loom Mobile.dc.html). Opens from the board's own ▶
  // badge on a finished shot -- purely local, ephemeral UI state (no spend, no polling),
  // same credit-safety category as dfOpen/genOpen/castSheetOpen above. Declared here (up
  // with this component's other early state), NOT down by `return` -- reviewLive (below,
  // near dfLive/finishedShots) reads reviewOpen before render, and hooks can't be
  // forward-referenced.
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewPlaying, setReviewPlaying] = useState(false);
  const [reviewCropping, setReviewCropping] = useState(false);
  // Real native playback state off the real <video> element (mirrors ShotPreview's own
  // component-local `dur`/`playing` state exactly) -- NOT the design's synthetic
  // setInterval-driven reviewFrac, which only existed because the mockup's "video" is a
  // plain colored div with nothing to actually play.
  const [reviewDur, setReviewDur] = useState(0);
  const [reviewCur, setReviewCur] = useState(0);
  const reviewVidRef = useRef(null);
  const reviewTrimTrackRef = useRef(null);
  const reviewTrimDragRef = useRef(null);   // "in" | "out" | null
  const reviewCropDragRef = useRef(false);
  const reviewScrubDragRef = useRef(false);

  // ---- Generate -- third increment (2026-08-03), per the locked design's own "genOpen"
  // full-screen page opened from Shot Detail's "Select in Generate →" button. On DESKTOP
  // this is not a separate screen at all -- LoomV2's right rail (Video tab + the always-
  // mounted <mg-generate-drawer>) sits beside the board permanently, bound to whichever shot
  // is selected. Mobile has no persistent rail, so this screen is the honest mobile
  // equivalent of "go look at Generate for this shot" -- genOpen is purely a LOCAL, ephemeral
  // "is this screen showing" flag, same category as dfOpen/castSheetOpen above. It carries
  // NO generation state of its own on purpose (see the credit-safety note on the Generate
  // block below for exactly why).
  const [genOpen, setGenOpen] = useState(false);
  const [genPalFor, setGenPalFor] = useState(null);        // which term palette is open, or null
  const [genOverrideFlash, setGenOverrideFlash] = useState(false);
  const [genSubmitting, setGenSubmitting] = useState(false);
  // Read-only cost PREVIEW cache for whichever shot Generate is currently open on --
  // { loading, pr, noInput } for entry.c.id, or null before the first check. This is
  // strictly informational: the real spend gate is generateShot's OWN internal priceShot +
  // window.confirm (called unmodified below, exactly like every other real submit path in
  // this file), never re-implemented here. Debounced the same way LoomV2's own imgCostRef/
  // editCostRef/refCostRef effects are (see LoomV2's priceInto comment) so a fast run of
  // keystrokes in Camera/Lighting/Prompt doesn't fire a price check per keystroke.
  const [genPrice, setGenPrice] = useState({});   // cardId -> {loading, pr, noInput}

  // ---- Image / Edit / Reference / Video tab strip -- fourth increment (2026-08-03),
  // mirroring LoomV2's own GEN_ICONS rail (Image/Edit/Reference/Video) inside this SAME
  // Generate screen. "Video" is this screen's pre-existing content (third increment,
  // unchanged below) -- genTab defaults to "Video" to match LoomV2's own default tab.
  const [genTab, setGenTab] = useState("Video");
  // Credit balance line -- purely a read-only display (matches LoomV2's identical
  // component-local `acct` state and its own component-local fetch effect below), never
  // gates a submit. Duplicating this one fetch per view (rather than lifting it) is the
  // established pattern in this file for non-spend UI chrome (pickerOpen/pickerMounted are
  // the same kind of per-view local state) -- losing it on a toggle just means one more
  // free /api/account read next time this screen opens, not a credit-safety concern.
  const [acct, setAcct] = useState(null);
  useEffect(() => { fetch("/api/account").then((r) => r.json()).then(setAcct).catch(() => {}); }, []);

  // ---- Model/LoRA picker overlay for the Image tab -- a mobile sheet wrapping the SAME
  // real <ModelPicker> custom element LoomV2's own floating .lv-mpick-veil uses, bound
  // the same way (bindPicker/bindLoraPicker below are close-to-verbatim ports of LoomV2's
  // own, adapted only for this screen's local naming -- imgModel/imgLoras/imgAdv/
  // modelDefaults themselves are the SAME hook-level state LoomV2 reads/writes, passed down
  // as props, so picking a model here is visible on LoomV2 immediately and vice versa).
  // Component-local by design, same reasoning as LoomV2's own identical state: picking a
  // model/LoRA spends nothing, so losing this overlay's own open/search state on a Mobile
  // toggle is a cosmetic inconvenience, never a credit-safety concern -- unlike the video
  // drawer's poll, there is no in-flight spend riding on this element's mount lifetime.
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerKind, setPickerKind] = useState("base");
  const [pickerMounted, setPickerMounted] = useState(false);
  // Slide-out close (see closeCastSheet's comment). The picker stays MOUNTED through and
  // after the close (the display-toggle contract above) -- the closing class only drives
  // the 280ms lmSheetDown before display flips to none.
  const [pickerClosing, setPickerClosing] = useState(false);
  const pickerCloseTimer = useRef(null);
  const closePicker = () => {
    setPickerClosing(true);
    clearTimeout(pickerCloseTimer.current);
    pickerCloseTimer.current = setTimeout(() => { setPickerOpen(false); setPickerClosing(false); }, 280);
  };
  useEffect(() => { if (pickerOpen) setPickerMounted(true); }, [pickerOpen]);
  useEffect(() => {
    if (!pickerOpen) return;
    const onKey = (ev) => { if (ev.key === "Escape") closePicker(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pickerOpen]);
  const imgModelSeqRef = useRef(0);
  // LoRA weight bounds for the current base model's architecture -- verbatim copy of
  // LoomV2's own loraRange memo (same shared window.MG_LORA table, same fallback).
  const loraRange = useMemo(() => {
    const L = window.MG_LORA;
    const t = String((imgModel && imgModel.model_type) || "").toUpperCase();
    if (!L) return [-2, 2];
    return (L.ranges && L.ranges[t]) || L.fallback || [-2, 2];
  }, [imgModel]);
  useEffect(() => {
    setImgLoras((cur) => {
      let changed = false;
      const next = cur.map((l) => {
        const w = Math.max(loraRange[0], Math.min(loraRange[1], +l.weight));
        if (w !== l.weight) changed = true;
        return w === l.weight ? l : { ...l, weight: w };
      });
      return changed ? next : cur;
    });
  }, [loraRange, setImgLoras]);
  const onBasePick = useCallback((row) => {
    closePicker();
    const m = { model_id: row.model_id, title: row.title, preview_url: row.preview_url || "" };
    setImgModel(m);
    setModelDefaults(null);
    const mySeq = ++imgModelSeqRef.current;
    fetch("/api/model-version?model_id=" + encodeURIComponent(m.model_id) + "&all=1")
      .then((r) => r.json())
      .then((d) => {
        if (mySeq !== imgModelSeqRef.current) return;
        const versions = (d && d.versions) || [], v = versions[0] || {};
        setImgModel((cur) => cur ? {
          ...cur, version_id: v.version_id || "", model_type: v.model_type || "",
          sampling_method: v.sampling_method || "", capabilities: v.capabilities || [],
          compatibility: v.compatibility || {}, restrictions: v.restrictions || {},
          versions,
        } : cur);
        const has = v.negative_prompt || v.sampling_steps || v.cfg_scale;
        setModelDefaults(has ? { negative_prompt: v.negative_prompt || "", sampling_steps: v.sampling_steps || null, cfg_scale: v.cfg_scale || null } : null);
        if (has) {
          setImgAdv((cur) => ({
            ...cur,
            negative: v.negative_prompt || cur.negative,
            steps: v.sampling_steps || cur.steps,
            cfg: v.cfg_scale || cur.cfg,
          }));
        }
      })
      .catch(() => {});
  }, [setImgModel, setImgAdv, setModelDefaults]);
  const pickVersion = useCallback((vid) => {
    if (!imgModel || !imgModel.versions) return;
    const v = imgModel.versions.find((x) => x.version_id === vid);
    if (!v) return;
    setImgModel((cur) => ({
      ...cur, version_id: v.version_id || "", model_type: v.model_type || "",
      sampling_method: v.sampling_method || "", capabilities: v.capabilities || [],
      compatibility: v.compatibility || {}, restrictions: v.restrictions || {},
    }));
    const has = v.negative_prompt || v.sampling_steps || v.cfg_scale;
    setModelDefaults(has ? { negative_prompt: v.negative_prompt || "", sampling_steps: v.sampling_steps || null, cfg_scale: v.cfg_scale || null } : null);
    if (has) {
      setImgAdv((a) => ({
        ...a,
        negative: v.negative_prompt || a.negative,
        steps: v.sampling_steps || a.steps,
        cfg: v.cfg_scale || a.cfg,
      }));
    }
  }, [imgModel, setImgModel, setImgAdv, setModelDefaults]);
  const onLoraPick = useCallback((model, selected) => {
    setImgLoras((cur) => {
      const i = cur.findIndex((l) => l.model_id === model.model_id);
      if (!selected) return i < 0 ? cur : cur.filter((l) => l.model_id !== model.model_id);
      if (i < 0) return [...cur, model];
      const next = cur.slice(); next[i] = model; return next;
    });
  }, [setImgLoras]);

  // ---- mode families for the Cast & assets sheet + ref live-tag badges. Copied verbatim
  // from LoomV2's own local copies -- neither is exported from loom-core.js/loom-mutations.js
  // (this file's own DO-NOT-MODIFY pure-logic layer), so every consumer keeps its own, the
  // same convention LoomV2 already follows rather than exporting a third shared module just
  // for four small closures. See LoomV2's identical comment (above its own copies) for the
  // full reasoning: which modes actually SEND the cast/ref image bank with a generation
  // (R2V/V2V) vs. cite it in the composed prompt only (FLF/I2V, which attach just their
  // frame(s)) -- the locked mobile design's own Cast sheet mockup only special-cases I2V and
  // hardcodes "4" reference slots; both are wrong for an FLF shot and for the real, mode-aware
  // 6-minus-attached-frames budget refBudget() (loom-core.js) computes, so this matches
  // LoomV2's real, already-correct behavior instead of reproducing the mockup's simplification
  // (disclosed in the increment's own report).
  const modeSendsRefs = (m) => usesCloseFrame(m) && m !== "FLF";
  const modeSendsLine = (m) => (m === "FLF"
    ? "First & Last sends the start & end frames only — cast & refs here are for continuity/notes, not references"
    : "I2V sends the opening frame only — cast here is for continuity/notes, not references");
  const liveTagText = (liveTag, pastBudget, mode) =>
    liveTag || (pastBudget ? (modeSendsRefs(mode) ? "not sent" : "not cited") : "—");
  const liveTagTitle = (liveTag, pastBudget, mode, code) => {
    const framesOnly = mode === "FLF" ? "First & Last sends only the start/end frames" : "I2V sends only the opening frame";
    if (liveTag) {
      return modeSendsRefs(mode)
        ? `Live slot in ${code} — numbered by position; this is what the composed prompt and the generator actually send`
        : `${code}'s composed-prompt citation — numbered by position. ${framesOnly}, so this picture is not attached to the generation`;
    }
    if (pastBudget) {
      return modeSendsRefs(mode)
        ? `Past the reference limit for ${code} (6 images minus attached frames) — not sent`
        : `Past the citation limit for ${code} — left out of the composed prompt. ${framesOnly} either way`;
    }
    return `No picture resolved on ${code} — nothing to number`;
  };

  const total = entries.reduce((s, x) => s + durOf(x.c), 0);
  const tickFrac = total > 0 ? Math.min(1, (project.target || 0) / total) : 0;
  // Where the reel's selection handle sits when NOT actively being dragged: the currently
  // selected shot's own cumulative-duration midpoint, so tapping a board card (or nothing
  // ever having been scrubbed yet) still shows an honest, live position -- never a stale
  // handle stuck wherever the last drag happened to end.
  const selIdx = entries.findIndex((x) => x.c.id === selShot);
  let selFrac = null;
  if (selIdx >= 0 && total > 0) {
    let cum = 0;
    for (let i = 0; i < selIdx; i++) cum += durOf(entries[i].c) || 1;
    selFrac = (cum + (durOf(entries[selIdx].c) || 1) / 2) / total;
  }

  // ---- reel pointer-drag scrub: fraction-of-width -> cumulative-duration index ----
  // Genuinely new interaction for this codebase (LoomV2's own .lv-reel a few hundred lines up
  // is click-a-fixed-width-segment only -- no drag, no floating preview). No gesture library:
  // setPointerCapture + a plain clientX/getBoundingClientRect fraction, matching the design's
  // own hand-rolled pattern (Loom Mobile.dc.html's scrubFn/scrubStart/scrubMove/scrubEnd)
  // exactly rather than reinventing the math a different way.
  const [scrubbing, setScrubbing] = useState(false);
  const [scrubFrac, setScrubFrac] = useState(0);
  const [scrubIdx, setScrubIdx] = useState(null);
  const fracAt = (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    return r.width ? Math.max(0, Math.min(0.9999, (e.clientX - r.left) / r.width)) : 0;
  };
  const idxAtFrac = (frac) => {
    if (!entries.length || !total) return null;
    const t = frac * total;
    let cum = 0;
    for (let i = 0; i < entries.length; i++) { cum += durOf(entries[i].c) || 1; if (t < cum) return i; }
    return entries.length - 1;
  };
  const scrubTo = (e) => {
    const frac = fracAt(e);
    setScrubbing(true); setScrubFrac(frac); setScrubIdx(idxAtFrac(frac));
  };
  const onReelDown = (e) => {
    if (!entries.length) return;
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch (err) {}
    scrubTo(e);
  };
  const onReelMove = (e) => { if (scrubbing) scrubTo(e); };
  // Release selects the shot the drag landed on -- the reel's own "click a shot" contract
  // (LoomV2's .lv-reel does this on a plain click; here it's the natural end of a drag).
  const onReelUp = () => { setScrubbing(false); if (scrubIdx != null && entries[scrubIdx]) setSelShot(entries[scrubIdx].c.id); };
  // Cancel-without-selecting if the pointer leaves the bar mid-drag. setPointerCapture means
  // onReelUp already fires reliably even if released outside the element's bounds -- this is
  // the same defensive belt-and-suspenders handler the design itself carries (scrubCancel),
  // not load-bearing for the common case.
  const onReelLeave = () => setScrubbing(false);

  const handleFrac = scrubbing ? scrubFrac : selFrac;
  const scrubEntry = scrubIdx != null ? entries[scrubIdx] : null;
  const posStyle = (frac) => ({ left: `calc(16px + (100% - 32px) * ${frac})` });

  // Re-derived from `entries` every render (never from a stale snapshot captured at tap
  // time) -- same reasoning as LoomV2's own `deepFocus` -> `live` lookup: setCard's patches
  // are immutable, so a captured entry object would never show a later edit. If the shot
  // vanished out from under an open Shot Detail (deleted elsewhere), close it the same
  // inline way LoomV2 already does for its own veil -- a documented React bail-out (setting
  // this component's own state during its own render), not a bug.
  const dfLive = dfOpen ? entries.find((x) => x.c.id === selShot) : null;
  if (dfOpen && !dfLive) { setDfOpen(false); }
  const dfSelIdx = dfLive ? entries.findIndex((x) => x.c.id === dfLive.c.id) : -1;
  const dfPrevEntry = dfSelIdx > 0 ? entries[dfSelIdx - 1] : null;
  const dfPatch = (fn) => dfLive && setCard(dfLive.a.id, dfLive.c.id, fn);
  const dfPatchFrame = (key, fp) => dfPatch((cc) => ({ ...cc, [key]: { ...cc[key], ...fp } }));
  // Frame handoff -- identical mechanic to LoomV2's own inheritPrev (same /api/loom/handoff
  // splice-the-last-frame-off-a-rendered-clip endpoint, same closeFrame-copy fallback for a
  // previous shot that hasn't rendered yet), reimplemented here only because that function is
  // a private closure inside LoomV2's own component body, not something this file exports.
  const dfInheritPrev = () => {
    if (!dfPrevEntry) return;
    const rmid = dfPrevEntry.c.resultMid;
    if (rmid) {
      setDfHandoff("wip");
      fetch("/api/loom/handoff", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_media_id: rmid, trim_out: dfPrevEntry.c.trimOut }) })
        .then((r) => r.json()).then((d) => {
          if (d.error || !d.frame_media_id) { setDfHandoff("err"); return; }
          setDfHandoff("");
          dfPatchFrame("openFrame", { mediaId: d.frame_media_id, thumbId: "", source: "",
            desc: "handed off from " + (dfPrevEntry.code || "prev shot") });
        }).catch(() => setDfHandoff("err"));
    } else {
      dfPatchFrame("openFrame", { ...dfPrevEntry.c.closeFrame });
    }
  };
  // "Finished shots" (Cast sheet's Footage tab): tapping a rendered shot from elsewhere in
  // THIS project appends it as a real @videoN reference on the open shot -- the same shape
  // addRef("video") + a hand-typed source already produce, just pre-filled with a real
  // resultMid instead of leaving the source blank for the owner to type one in. Deliberately
  // NOT loom-core.js's pickVideoTarget/shotVideoRefs (the Multi-Reference drawer's slot-
  // REPLACE machinery) -- a footage tap always APPENDS a brand-new ref, never replaces an
  // existing numbered slot, so nextTag (addRef's own tag convention in useShotMutations) is
  // the correct, simpler tool, not a re-derivation of a different real mechanism.
  const dfPickFootage = (mid, code) => {
    if (!dfLive) return;
    const tag = nextTag(dfLive.c.refs.filter((r) => r.kind === "video"), "@video");
    const newRef = { ...buildNewRef("video", uid()), tag, source: String(mid), role: "footage from " + code };
    setCard(dfLive.a.id, dfLive.c.id, (c) => ({ ...c, refs: [...c.refs, newRef] }));
  };
  const castBudget = dfLive ? refBudget(dfLive, project, imgSrc) : null;
  const finishedShots = entries.filter((e) => e.c.resultMid);

  // ---- Review & trim's own "which shot" lookup -- reuses selShot/entries.find() exactly
  // like dfLive/genOpen's target already do, rather than a second id-tracking field (the
  // design's own local `reviewFor`). Same live-lookup safety: a shot deleted out from under
  // an open Review closes it instead of rendering stale data (identical to dfLive's guard
  // a few lines above).
  const reviewLive = reviewOpen ? entries.find((x) => x.c.id === selShot) : null;
  if (reviewOpen && !reviewLive) { setReviewOpen(false); }
  const reviewPatch = (fn) => reviewLive && setCard(reviewLive.a.id, reviewLive.c.id, fn);
  const closeReview = () => { setReviewOpen(false); setReviewPlaying(false); setReviewCropping(false); };

  // ---- Kebab actions sheet's own "which shot" lookup -- same live-lookup safety pattern as
  // dfLive/reviewLive above: a shot deleted out from under an open sheet closes it instead of
  // acting on stale data. `.a`/`.ci`/`.code` all come straight off flat()'s own entry shape
  // (loom-core.js), the same fields LoomV2's real per-card buttons already index by
  // (act.id/e.ci/e.code) -- nothing new derived here.
  const actionsLive = actionsOpen ? entries.find((x) => x.c.id === selShot) : null;
  if (actionsOpen && !actionsLive) { setActionsOpen(false); }
  // Slide-out close (see closeCastSheet's comment): actionsOpen stays true through the
  // 280ms lmSheetDown window, so actionsLive above keeps resolving while it plays.
  const closeActions = () => {
    setActionsClosing(true);
    clearTimeout(actionsCloseTimer.current);
    actionsCloseTimer.current = setTimeout(() => { setActionsOpen(false); setActionsClosing(false); }, 280);
  };

  // ---- Generate screen helpers (third increment, 2026-08-03) ----
  const genTogglePal = (which) => setGenPalFor((p) => (p === which ? null : which));
  const genAppendTo = (field, term) => dfPatch((cc) => ({ ...cc, [field]: cc[field] ? cc[field] + ", " + term : term }));
  // Debounced, read-only price PREVIEW for whichever shot Generate is open on -- the exact
  // real /api/price check (via priceShot) every other cost display in this file already
  // uses, just kept per-shot here since this component has no priceCache of its own (that
  // cache is private to useGenerationPipeline, and this screen only ever needs ONE shot's
  // price at a time, not the whole board's). Skipped entirely for a shot with nothing
  // attachable yet (payload.hasInput false) -- pricing an unsendable shot is meaningless,
  // and generateShot's own real submit already refuses it outright regardless of this.
  //
  // Purely informational: the real spend gate is generateShot's OWN internal priceShot +
  // window.confirm, called UNMODIFIED by genSubmit below -- this cache never gates the
  // Generate button itself, it only decides what the cost LINE displays before that.
  useEffect(() => {
    if (!genOpen || !dfLive) return;
    const id = dfLive.c.id;
    const payload = buildShotPayload(dfLive, project, imgSrc);
    if (!payload.hasInput) { setGenPrice((s) => ({ ...s, [id]: { loading: false, pr: null, noInput: true } })); return; }
    setGenPrice((s) => ({ ...s, [id]: { ...(s[id] || {}), loading: true, noInput: false } }));
    let live = true;
    const t = setTimeout(() => {
      priceShot(dfLive).then((pr) => { if (live) setGenPrice((s) => ({ ...s, [id]: { loading: false, pr, noInput: false } })); });
    }, 300);
    return () => { live = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [genOpen, dfLive && dfLive.c.id, dfLive && dfLive.c.mode, dfLive && dfLive.c.duration,
      dfLive && dfLive.c.connect, dfLive && dfLive.c.audioGen, dfLive && dfLive.c.audioLanguage,
      dfLive && dfLive.c.prompt, dfLive && dfLive.c.promptOverride, dfLive && dfLive.c.promptOverrideText,
      dfLive && JSON.stringify(dfLive.c.cast), dfLive && JSON.stringify(dfLive.c.refs), project.draft, project.assets,
      dfLive && (dfLive.c.openFrame || {}).mediaId, dfLive && (dfLive.c.openFrame || {}).thumbId, dfLive && (dfLive.c.openFrame || {}).source,
      dfLive && (dfLive.c.closeFrame || {}).mediaId, dfLive && (dfLive.c.closeFrame || {}).thumbId, dfLive && (dfLive.c.closeFrame || {}).source]);
  // The real submit: generateShot is called EXACTLY as batchGenerate's own per-card loop
  // calls it (minus skipConfirm -- this is a single, deliberate, owner-initiated tap, not a
  // pre-confirmed batch run, so generateShot's own internal priceShot+window.confirm gate
  // fires for real here, same as it would for any other single real submit in this file).
  // No new endpoint, no new price math, no new confirm dialog of this screen's own -- see
  // the increment's report for the full credit-safety trace.
  const genSubmit = async () => {
    if (!dfLive || genSubmitting) return;
    setGenSubmitting(true);
    let r;
    try { r = await generateShot(dfLive); } finally { setGenSubmitting(false); }
    // Only a CONFIRMED, successful submit returns to the board -- a cancelled confirm or a
    // submit-time failure leaves this screen open exactly as it was, so the owner can see
    // why (generateShot's own genState error write) or adjust and retry, instead of being
    // silently dumped back to Shot Detail with no visible outcome.
    if (r && r.ok) { setGenOpen(false); setDfOpen(false); }
  };

  // ---- Image / Edit / Reference tab bodies -- fourth increment (2026-08-03). genImage/
  // genEdit/genRef below are called EXACTLY as LoomV2's own Image/Edit/Reference tabs call
  // them (useGenerationPipeline) -- same confirmSpend fail-closed gate inside each, same
  // genImgState/genEditState/genRefState, same Job Tracker registration, same
  // pollTaskWithCeiling poll. No forked submit logic, no reinvented pricing, no new
  // endpoints. Unlike the Video tab (generateShot/priceShot, third increment), these three
  // never touch <mg-generate-drawer> at all -- LoomV2's OWN Image/Edit/Reference tabs don't
  // either, only its Video tab does, so this is genuine parity, not a workaround.
  const editSrcMid = dfLive && dfLive.c.openFrame && dfLive.c.openFrame.mediaId;
  const refMids = (project.assets || []).filter((a) => a.kind === "image" && a.mediaId).map((a) => a.mediaId);
  const refMidsKey = refMids.join(",");
  // Debounced, read-only /api/price PREVIEWS for the Image/Edit/Reference tabs -- the SAME
  // endpoint + body shapes LoomV2's own imgCostRef/editCostRef/refCostRef effects price
  // (buildImgGenBody for Image; the same {mode:"edit", source, instruction, edit_model}/
  // {..., sources} shapes for Edit/Reference), just rendered as a plain text line via the
  // same tallyPrices/formatCostEstimate/costTooltip pure helpers the Video tab's own genPrice
  // already uses above, instead of binding a <mg-cost-badge> custom element -- a
  // presentational choice (this screen has no other custom-element bindings besides the
  // model/LoRA pickers), not a pricing fork: the real cost gate is still confirmSpend's own
  // window.confirm inside genImage/genEdit/genRef, fired UNMODIFIED on submit below.
  const [imgPrice, setImgPrice] = useState({});
  const [editPrice, setEditPrice] = useState({});
  const [refPrice, setRefPrice] = useState({});
  useEffect(() => {
    if (!genOpen || genTab !== "Image" || !dfLive) return;
    const id = dfLive.c.id;
    const prompt = (dfLive.c.imgPrompt || "").trim();
    if (!imgModel || !prompt || anyLoraUnresolved(imgLoras)) { setImgPrice((s) => ({ ...s, [id]: null })); return; }
    setImgPrice((s) => ({ ...s, [id]: { ...(s[id] || {}), loading: true } }));
    let live = true;
    const t = setTimeout(() => {
      fetch("/api/price", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(buildImgGenBody(imgModel, imgLoras, imgAdv, prompt)) })
        .then((r) => r.json()).then((pr) => { if (live) setImgPrice((s) => ({ ...s, [id]: { loading: false, pr } })); })
        .catch(() => { if (live) setImgPrice((s) => ({ ...s, [id]: { loading: false, pr: null } })); });
    }, 250);
    return () => { live = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [genOpen, genTab, dfLive && dfLive.c.id, dfLive && dfLive.c.imgPrompt, imgModel, imgLoras, imgAdv]);
  useEffect(() => {
    if (!genOpen || genTab !== "Edit" || !dfLive) return;
    const id = dfLive.c.id;
    const instruction = (dfLive.c.editPrompt || "").trim();
    if (!editSrcMid || !instruction) { setEditPrice((s) => ({ ...s, [id]: null })); return; }
    setEditPrice((s) => ({ ...s, [id]: { ...(s[id] || {}), loading: true } }));
    let live = true;
    const t = setTimeout(() => {
      fetch("/api/price", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "edit", source: editSrcMid, instruction, edit_model: "edit-pro" }) })
        .then((r) => r.json()).then((pr) => { if (live) setEditPrice((s) => ({ ...s, [id]: { loading: false, pr } })); })
        .catch(() => { if (live) setEditPrice((s) => ({ ...s, [id]: { loading: false, pr: null } })); });
    }, 250);
    return () => { live = false; clearTimeout(t); };
  }, [genOpen, genTab, dfLive && dfLive.c.id, dfLive && dfLive.c.editPrompt, editSrcMid]);
  useEffect(() => {
    if (!genOpen || genTab !== "Reference" || !dfLive) return;
    const id = dfLive.c.id;
    const prompt = (dfLive.c.refPrompt || "").trim();
    if (!refMids.length || !prompt) { setRefPrice((s) => ({ ...s, [id]: null })); return; }
    setRefPrice((s) => ({ ...s, [id]: { ...(s[id] || {}), loading: true } }));
    let live = true;
    const t = setTimeout(() => {
      fetch("/api/price", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "edit", source: refMids[0], sources: refMids, instruction: prompt, edit_model: "reference-pro" }) })
        .then((r) => r.json()).then((pr) => { if (live) setRefPrice((s) => ({ ...s, [id]: { loading: false, pr } })); })
        .catch(() => { if (live) setRefPrice((s) => ({ ...s, [id]: { loading: false, pr: null } })); });
    }, 250);
    return () => { live = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [genOpen, genTab, dfLive && dfLive.c.id, dfLive && dfLive.c.refPrompt, refMidsKey]);
  const priceLine = (priceState, id, noInputMsg) => {
    const p = priceState[id];
    if (!p) return noInputMsg;
    if (p.loading) return "checking…";
    const tally = p.pr ? tallyPrices([p.pr]) : null;
    return tally ? formatCostEstimate(tally) : "—";
  };
  const priceTitle = (priceState, id) => {
    const p = priceState[id];
    const tally = p && p.pr ? tallyPrices([p.pr]) : null;
    return tally ? costTooltip(tally) : "";
  };

  // ---- Fixer -- the seventh and FINAL increment (2026-08-03), closing the one disclosed gap
  // left after the six increments below + the kebab-actions-sheet follow-up. A prior
  // increment's own report deferred it, claiming Fixer's touch box-drawing had "zero
  // reference implementation anywhere in this codebase" -- that claim was WRONG and has
  // since been corrected: gallery/src/components/FixTab.jsx is the real, already-shipped
  // Fixer for regular Gallery images, and its box-drawing already uses the exact same real
  // technique (Pointer Events + getBoundingClientRect + DISPLAY-to-ORIGINAL-pixel scaling)
  // already used successfully for the reel scrub (increment 1) and the trim handles/crop
  // rectangle (increment 5) in THIS component. This screen ports FixTab.jsx's real, working
  // approach verbatim -- same FIX_COLORS/FIX_MIN_PX/FIX_MAX_BOXES/scaleFixBoxes (this file's
  // own local copy of editCore.js's constants, see that comment for why it's a copy and not
  // an import), same paint()/onDown/onMove/onUp box math, same confirm-gated real submit
  // through the real /api/fix endpoint (genFix, useGenerationPipeline) -- not a re-derived
  // or lighter-weight version. Declared here, ahead of the Filter-compare block below, so
  // every one of its own real /api/price calls (the debounced preview effect at the end of
  // this block) stays OUT of that block's own "no fetch anywhere past this point" contract --
  // Filter compare is genuinely free/offline and must stay that way; Fixer is a real, billed
  // surface and must not be mistaken for part of it just because they share one sub-strip.
  const [editSub, setEditSub] = useState("edit");   // 'edit' | 'fixer' | 'enhance' -- also read by Filter compare below (reached via the Enhance chip)
  // Fixer's own box-drawing state -- 'face' | 'hand' (fixTag, matches the design's own
  // fixKind default) and the boxes themselves, {x,y,w,h,tag} in DISPLAY pixels (the canvas's
  // own coordinate space), scaled to ORIGINAL-image pixels only at submit/price time via
  // scaleFixBoxes -- same DISPLAY-vs-ORIGINAL split FixTab.jsx's own header comment
  // documents. Boxes reset whenever the source image changes (a new shot selected, or this
  // shot's open frame replaced) -- a box drawn against one picture's pixel grid is meaningless
  // (and potentially misleading) against a different one, so nothing here lets a stale box
  // silently ride along onto a picture it was never drawn on.
  const [fixTag, setFixTag] = useState("face");
  const [fixBoxes, setFixBoxes] = useState([]);
  const fixImgRef = useRef(null);
  const fixCanvasRef = useRef(null);
  const fixDragRef = useRef(null);
  const [genFixPrice, setGenFixPrice] = useState({});   // cardId -> {loading, pr} -- read-only preview, see the other three price effects above
  useEffect(() => {
    setFixBoxes([]);
  }, [dfLive && dfLive.c.id, dfLive && dfLive.c.openFrame && dfLive.c.openFrame.mediaId]);
  // ---- the canvas: draw, paint, resize -- verbatim port of FixTab.jsx's own paint()/onDown/
  // onMove/onUp, adapted only for this component's fixBoxes/fixTag/fixDragRef naming. Canvas
  // dimensions track the rendered <img>'s own clientWidth/clientHeight every paint (matching
  // FixTab.jsx exactly), so a box drawn here lives in the SAME pixel space the image is
  // actually displayed in -- scaleFixBoxes() is what converts that to original-image pixels
  // before it ever reaches the server.
  const fixPaint = useCallback(() => {
    const cvs = fixCanvasRef.current, img = fixImgRef.current;
    if (!cvs || !img) return;
    const w = img.clientWidth, h = img.clientHeight;
    if (!w || !h) return;
    if (cvs.width !== w || cvs.height !== h) { cvs.width = w; cvs.height = h; }
    const ctx = cvs.getContext("2d");
    ctx.clearRect(0, 0, w, h);
    const draw = (b) => {
      ctx.strokeStyle = FIX_COLORS[b.tag] || FIX_COLORS.face;
      ctx.lineWidth = 2;
      ctx.strokeRect(b.x, b.y, b.w, b.h);
      ctx.fillStyle = ctx.strokeStyle;
      ctx.font = "11px system-ui";
      ctx.fillText(b.tag, b.x + 3, b.y + 13);
    };
    fixBoxes.forEach(draw);
    if (fixDragRef.current) draw({ ...fixDragRef.current, tag: fixTag });
  }, [fixBoxes, fixTag]);
  useEffect(() => { fixPaint(); }, [fixPaint]);
  useEffect(() => {
    const onResize = () => fixPaint();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [fixPaint]);
  const fixRel = (e) => {
    const r = fixCanvasRef.current.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  // setPointerCapture on down -- NOT in FixTab.jsx (a desktop-mouse surface, where
  // onPointerLeave alone is enough), but the SAME real mobile convention every other
  // pointer-drag gesture in THIS component already uses (reel scrub's onReelDown, Review &
  // trim's cropDragStart/trimInStart/trimOutStart/scrubStart, all above) -- a touch drag that
  // leaves the canvas's own bounds needs capture to keep receiving move/up events, which a
  // mouse drag on desktop does not. onPointerLeave is kept alongside it anyway, matching
  // FixTab.jsx's own four-handler set exactly, as a harmless defensive fallback.
  const fixDown = (e) => {
    if (e.button !== 0 || !(dfLive && dfLive.c.openFrame && dfLive.c.openFrame.mediaId)) return;
    const p = fixRel(e);
    fixDragRef.current = { x: p.x, y: p.y, w: 0, h: 0, ox: p.x, oy: p.y };
    try { e.currentTarget.setPointerCapture(e.pointerId); } catch (err) {}
    e.preventDefault();
  };
  const fixMove = (e) => {
    if (!fixDragRef.current) return;
    const p = fixRel(e);
    const d = fixDragRef.current;
    fixDragRef.current = {
      ...d,
      x: Math.min(d.ox, p.x), y: Math.min(d.oy, p.y),
      w: Math.abs(p.x - d.ox), h: Math.abs(p.y - d.oy),
    };
    fixPaint();
  };
  const fixUp = () => {
    const d = fixDragRef.current;
    fixDragRef.current = null;
    if (!d) return;
    // FixTab.jsx's own minimum: a stray tap is not a box.
    if (d.w > FIX_MIN_PX && d.h > FIX_MIN_PX) {
      if (fixBoxes.length >= FIX_MAX_BOXES) {
        if (window.Toast) {
          window.Toast.show({
            kind: "err", title: "That's the limit",
            msg: "A Fix carries at most " + FIX_MAX_BOXES + " boxes — the rest would be dropped server-side.",
          });
        }
      } else {
        setFixBoxes((old) => old.concat([{ x: d.x, y: d.y, w: d.w, h: d.h, tag: fixTag }]));
      }
    }
    fixPaint();
  };
  // Debounced, read-only /api/price PREVIEW for the Fixer sub-tab -- same shape/convention
  // as imgPrice/editPrice/refPrice above (this screen's OWN informational cache, distinct
  // from genFix's own fresh, must-be-current price check right before its real confirm
  // dialog). mode:"fix" always comes back free:false (server-forced -- see
  // moonglade_gallery.py's _params_and_nocard), so this line can never show "free", matching
  // FixTab.jsx's own cost badge, which never offers a card-label for the same reason.
  useEffect(() => {
    if (!genOpen || genTab !== "Edit" || editSub !== "fixer" || !dfLive) return;
    const id = dfLive.c.id;
    const src = dfLive.c.openFrame && dfLive.c.openFrame.mediaId;
    if (!src || !fixBoxes.length) { setGenFixPrice((s) => ({ ...s, [id]: null })); return; }
    setGenFixPrice((s) => ({ ...s, [id]: { ...(s[id] || {}), loading: true } }));
    let live = true;
    const t = setTimeout(() => {
      fetch("/api/price", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "fix", source: src, boxes: scaleFixBoxes(fixBoxes, fixImgRef.current) }) })
        .then((r) => r.json()).then((pr) => { if (live) setGenFixPrice((s) => ({ ...s, [id]: { loading: false, pr } })); })
        .catch(() => { if (live) setGenFixPrice((s) => ({ ...s, [id]: { loading: false, pr: null } })); });
    }, 250);
    return () => { live = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [genOpen, genTab, editSub, dfLive && dfLive.c.id, dfLive && dfLive.c.openFrame && dfLive.c.openFrame.mediaId, fixBoxes]);

  // ---- Filter compare -- sixth and FINAL increment (2026-08-03), per the locked design's
  // own filterCompareOpen/fcStrength/fcAngle state (Loom Mobile.dc.html: search
  // "filterCompareOpen", "fcSkinFilters", "fcPixaiFilters", "fcStrength", "fcAngle",
  // "fcClear", "fcSaveLibrary", "FILTER_SETS" -- its own internal screen title is "Art
  // filters"). Reached from the SAME place the design puts it: Generate's Edit tab gets its
  // own Edit/Fixer/Enhance sub-strip above (editSub), and Enhance's "Open filters" button
  // opens this screen -- confirmed against the design (editSubChips: Edit/Fixer/Enhance,
  // editSubIsEnhance's own openFilterCompare button) AND independently against the real,
  // already-shipped gallery/src/components/GenerateDrawer.jsx, which carries the EXACT SAME
  // real, current Edit/Fixer/Enhance sub-tab strip (its own mgdock-subtabs; "Enhance" /
  // "Art filters — free, in your browser") wired to gallery/src/components/FiltersPanel.jsx's
  // ArtFiltersPanel. Two independent real sources agreeing is why this is placement, not a
  // guess.
  //
  // filter/filterStrength/filterAngle are NOT in newCard() -- same "optional field, sensible
  // fallback" convention Review & trim's own `c.crop || {...}` already established in this
  // file (crop isn't in newCard() either): nothing needed to change in the card's base
  // shape, a shot simply has no filter until one is genuinely Saved (below).
  const [fcOpen, setFcOpen] = useState(false);
  const [fcActive, setFcActive] = useState(null);     // candidate filter id, or null
  const [fcStrength, setFcStrength] = useState(1);
  const [fcAngle, setFcAngle] = useState(180);
  const fcStageRef = useRef(null);
  const fcImgRef = useRef(null);

  // Opening seeds the candidate from whatever is ALREADY SAVED on the real card, so
  // reopening shows the persisted choice rather than a blank slate. Reuses dfLive directly
  // (no separate "which shot" id) -- this can only ever be called from the Enhance sub-tab
  // inside Generate, which only renders while genOpen && dfOpen are both true, so dfLive is
  // already guaranteed live at the point this fires (same reasoning genOpen's own JSX
  // already relies on, unlike reviewOpen's separate entries.find() -- Review opens straight
  // off the board with no dfOpen underneath it to guarantee a live shot).
  const openFilterCompare = () => {
    if (!dfLive) return;
    setFcActive(dfLive.c.filter || null);
    setFcStrength(dfLive.c.filterStrength != null ? dfLive.c.filterStrength : 1);
    setFcAngle(dfLive.c.filterAngle != null ? dfLive.c.filterAngle : 180);
    setFcOpen(true);
  };
  // A plain cancel: closes without writing anything. This is the one place this screen's
  // real behavior can't match the design's own closeFilterCompare verbatim -- the mock never
  // actually persisted filter/filterStrength/filterAngle anywhere else, so its
  // closeFilterCompare and fcSaveLibrary do the literal same thing (setState + close). Here
  // Save genuinely writes to the card (below) and Close/back genuinely does not, so an
  // unsaved filter pick can be backed out of just by closing. Disclosed adaptation, not a
  // silent difference.
  const closeFilterCompare = () => setFcOpen(false);
  // "No filter" -- genuinely, immediately removes any SAVED filter (not just the
  // in-progress candidate), matching the task's own "should genuinely remove it": a clear is
  // a real, one-tap undo, not a pending edit that would be lost by tapping Close instead of
  // Save.
  const fcClear = () => { setFcActive(null); dfPatch((cc) => ({ ...cc, filter: null })); };
  // Save -- genuinely persists the candidate onto the real card via the SAME dfPatch/setCard
  // mutation every other Shot Detail/Generate field already writes through. No new endpoint,
  // no network call, no spend: filter/filterStrength/filterAngle become plain card fields,
  // read back by openFilterCompare (above) and the preview effect (below) like any other.
  const fcSave = () => {
    dfPatch((cc) => ({ ...cc, filter: fcActive, filterStrength: fcStrength, filterAngle: fcAngle }));
    setFcOpen(false);
  };
  // Live preview -- genuinely composites via the real AF.applyPreview/clearPreview (CSS
  // overlay divs + mix-blend-mode, exactly mg-art-filters.js's own documented approach), not
  // a fake color swatch. Re-runs on every strength/angle change so both sliders visibly
  // affect the SAME real overlay while dragging.
  useEffect(() => {
    if (!fcOpen || !AF || !fcStageRef.current) return;
    const host = fcStageRef.current;
    AF.clearPreview(host);
    if (fcActive) AF.applyPreview(host, fcActive, { strength: fcStrength, angle: fcAngle });
    return () => { AF.clearPreview(host); };
  }, [fcOpen, fcActive, fcStrength, fcAngle, AF]);

  return (
    <div className="lm-root">
      <style>{LOOM_MOBILE_STYLES}</style>
      <div className="lm-top">
        <a className="lm-back" href="/">&larr; Gallery</a>
        <span className="lm-fill" />
        <span className="lm-title">&#9642; The Loom</span>
        <span className="lm-fill" />
        <label className={"lm-chip" + (project.draft ? " on" : "")}
          title="Draft mode renders every shot at the cheaper 'basic' quality — block out the animatic, then turn Draft off and re-generate the keepers at pro quality">
          <input type="checkbox" checked={!!project.draft} onChange={(e) => setDraft(e.target.checked)} />&#9889; Draft</label>
        {/* Not in the locked design (which only shows back-link/title/Draft here) -- added
            because the design's own mobile screen has no return path to LoomV2 at all, and
            without one this toggle would be a one-way trap: flip to Mobile view and the
            .lv-top bar that carries the ONLY other instance of this switch stops rendering.
            A real, bidirectional owner-preference switch needs an exit on both sides. */}
        <button type="button" className="lm-chip" onClick={() => setMobileUI(false)}
          title="Switch back to the full desktop-style Loom">&#128421; Desktop</button>
      </div>

      <div className="lm-reelwrap">
        <div className="lm-reelbar"
          onPointerDown={onReelDown} onPointerMove={onReelMove} onPointerUp={onReelUp} onPointerLeave={onReelLeave}>
          {entries.map((x) => (
            <div key={x.c.id} className={"lm-seg " + statusOf(x.c) + (x.c.id === selShot ? " sel" : "")}
              style={{ flex: `${durOf(x.c) || 1} 1 0` }} />
          ))}
        </div>
        {total > 0 && <div className="lm-tick" style={posStyle(tickFrac)} />}
        {scrubbing && <div className="lm-scrubline" style={posStyle(scrubFrac)} />}
        {handleFrac != null && <div className="lm-handle" style={posStyle(handleFrac)} />}
        {scrubbing && scrubEntry && (
          <div className="lm-preview" style={{ left: `clamp(8px, calc(${(scrubFrac * 100).toFixed(3)}% - 86px), calc(100% - 8px - 172px))` }}>
            <div className="lm-prevthumb" style={cardThumb(scrubEntry.c) ? { backgroundImage: `url(${cardThumb(scrubEntry.c)})` } : undefined} />
            <div className="lm-prevcol">
              <div className="lm-prevcode">{scrubEntry.code}</div>
              <div className="lm-prevtitle">{scrubEntry.c.title || "untitled"}</div>
              <div className="lm-prevmeta">{scrubEntry.c.mode} &middot; {durOf(scrubEntry.c)}s</div>
            </div>
          </div>
        )}
      </div>

      <div className="lm-body">
        {project.acts.map((act, ai) => {
          const items = entries.filter((e) => e.ai === ai);
          return (
            <div key={act.id}>
              <div className="lm-acthead">
                <span className="lm-actname">{act.name}</span>
                <span className="lm-actcount">{items.length} shot{items.length === 1 ? "" : "s"}</span>
                <span className="lm-fill" />
                <button type="button" className="lm-addshot" onClick={() => addCard(act.id)}>+ Shot</button>
              </div>
              {items.map((e) => {
                const st = statusOf(e.c);
                const gs = genState[e.c.id];
                const miss = castMissingImages(e, project, imgSrc);
                const thumb = cardThumb(e.c);
                // canReview mirrors the locked design's own `canReview: c.st === 'done'`
                // (Loom Mobile.dc.html), narrowed to also require a real resultMid -- "done"
                // and "has a real rendered clip to review" are supposed to always coincide
                // (every status:"done" write in this file also writes resultMid in the same
                // patch), but this stays a real, defensive AND rather than trusting that
                // invariant silently. Reuses `st` (statusOf(e.c)), already computed above for
                // the status pill -- one statusOf() call, not a second copy.
                const canReview = st === "done" && !!e.c.resultMid;
                return (
                  <div key={e.c.id} className="lm-cardrow">
                    <button type="button" className={"lm-card" + (e.c.id === selShot ? " sel" : "")}
                      onClick={() => { setSelShot(e.c.id); setDfOpen(true); }}
                      title="Open this shot — it binds to Generate">
                      <div className="lm-thumb" style={thumb ? { backgroundImage: `url(${thumb})` } : undefined}>
                        {!thumb && e.c.mode}
                      </div>
                      <div className="lm-textcol">
                        <div className="lm-titlerow">
                          <span className="lm-code">{e.code}</span>
                          <span className="lm-cardtitle">{e.c.title || "untitled"}</span>
                        </div>
                        <div className="lm-pillrow">
                          <span className="lm-modepill">{e.c.mode}</span>
                          <span className="lm-durpill">{durOf(e.c)}s</span>
                          <span className={"lm-stpill " + st}>{gs && gs.msg ? gs.msg : st}</span>
                          {miss.length > 0 && (
                            <span className="lm-warn" title={`No picture on this shot for ${miss.join(", ")} — they are cast here but cannot be referenced, so they are left out of the prompt.`}>
                              &#9888; {miss.length === 1 ? `${miss[0]}: no image` : `${miss.length} cast: no image`}
                            </span>
                          )}
                        </div>
                      </div>
                    </button>
                    {/* Review & trim's own board affordance -- the locked design's ▶ badge,
                        overlaid on the thumbnail as a SIBLING of .lm-card (never nested inside
                        it: .lm-card is a real <button>, and a <button> inside a <button> is
                        invalid HTML/nesting) rather than the design's own plain-div-inside-
                        plain-div layering, which had no such constraint. Positioned via
                        .lm-cardrow{position:relative} + absolute placement so tapping the
                        thumbnail specifically opens Review while the rest of the card still
                        opens Shot Detail via the real button beneath it. */}
                    {canReview && (
                      <button type="button" className="lm-reviewbadge"
                        title="Review & trim this shot's rendered clip"
                        onClick={(ev) => {
                          ev.stopPropagation();
                          setSelShot(e.c.id); setReviewOpen(true);
                          setReviewCropping(false); setReviewPlaying(false);
                          setReviewDur(0); setReviewCur(0);
                        }}>▶</button>
                    )}
                    {/* Kebab actions sheet (completeness pass, 2026-08-03) -- the locked
                        design's own card.onKebab (Loom Mobile.dc.html), never wired into this
                        board before now. A plain flex sibling in .lm-cardrow, NOT absolutely
                        overlaid like the ▶ badge above -- the design's own kebabStyle is an
                        ordinary in-flow flex item at the end of the row, not a positioned
                        overlay, and .lm-cardrow's existing display:flex already lays it out
                        that way with no extra CSS needed. Also a real sibling <button>, for
                        the same "no <button> inside .lm-card" reason as the ▶ badge. */}
                    <button type="button" className="lm-kebab" title="More actions for this shot"
                      onClick={(ev) => { ev.stopPropagation(); setSelShot(e.c.id); setActionsOpen(true); }}>&#8942;</button>
                  </div>
                );
              })}
              {!items.length && <div className="lm-empty">No shots yet — tap + Shot.</div>}
            </div>
          );
        })}
        <button type="button" className="lm-addact" onClick={addAct}>+ New act</button>
        {!project.acts.length && <div className="lm-empty">No acts yet — add one below.</div>}
      </div>

      {/* Kebab actions sheet (completeness pass, 2026-08-03) -- Move up / Move down /
          Duplicate / Delete / Cancel, per the locked design's own actionsOpen/actMoveUp/
          actMoveDown/actDuplicate/actDelete (Loom Mobile.dc.html). A top-level conditional
          (like dfOpen/reviewOpen/genOpen below), not nested inside the board map above --
          it can open from ANY card, board-wide, same as the design's own single shared sheet.
          moveCard/dupCard/delCard are the exact same real mutators LoomV2's own board-card
          buttons call (useShotMutations) -- no forked move/duplicate/delete logic. */}
      {actionsOpen && actionsLive && (
        <>
          <div className={"lm-scrim" + (actionsClosing ? " closing" : "")} onClick={closeActions} />
          <div className={"lm-sheet" + (actionsClosing ? " closing" : "")}>
            <div className="lm-sheethandle" />
            <button type="button" className="lm-actionrow"
              onClick={() => { moveCard(actionsLive.a.id, actionsLive.ci, -1); closeActions(); }}>&#8593; Move up</button>
            <button type="button" className="lm-actionrow"
              onClick={() => { moveCard(actionsLive.a.id, actionsLive.ci, 1); closeActions(); }}>&#8595; Move down</button>
            <button type="button" className="lm-actionrow"
              onClick={() => { dupCard(actionsLive.a.id, actionsLive.c); closeActions(); }}>&#10697; Duplicate</button>
            {/* Confirmed, exactly like LoomV2's own real ✕ button -- same window.confirm gate,
                same message text, ported unmodified rather than dropped for mobile. Only
                closes the sheet once the delete actually happens; cancelling the confirm
                leaves the sheet open with nothing changed. */}
            <button type="button" className="lm-actionrow danger"
              onClick={() => {
                if (!window.confirm(`Delete shot ${actionsLive.code}${actionsLive.c.title ? ` — "${actionsLive.c.title}"` : ""}? This can't be undone.`)) return;
                delCard(actionsLive.a.id, actionsLive.c);
                closeActions();
              }}>&#128465; Delete</button>
            <button type="button" className="lm-sheetclose" onClick={closeActions}>Cancel</button>
          </div>
        </>
      )}

      {dfOpen && dfLive && (() => {
        const c = dfLive.c;
        return (
          <div className="lm-df">
            <div className="lm-df-top">
              <button type="button" className={"lm-df-st lm-stpill " + statusOf(c)}
                title={`Status: ${statusOf(c)} — tap to cycle`}
                onClick={() => dfPatch((cc) => ({ ...cc, status: cc.status === "todo" ? "wip" : cc.status === "wip" ? "done" : "todo" }))}>
                {statusOf(c)}
              </button>
              <span className="lm-code">{dfLive.code}</span>
              <input className="lm-df-title" value={c.title || ""} placeholder="untitled"
                onChange={(ev) => dfPatch((cc) => ({ ...cc, title: ev.target.value }))} />
              <button type="button" className="lm-df-cast" onClick={() => setCastSheetOpen(true)}
                title="Cast & assets bound to this shot">
                &#128101; {(c.cast || []).length}
              </button>
              <button type="button" className="lm-df-close" title="Close" onClick={() => setDfOpen(false)}>&#10005;</button>
            </div>
            <div className="lm-df-body">
              <span className="lm-microlab">Mode</span>
              <div className="lm-modechips">
                {MODES.map((m) => (
                  <button type="button" key={m} className={"lm-modechip" + (m === c.mode ? " on" : "")}
                    onClick={() => dfPatch((cc) => setShotMode(cc, m))}>{m}</button>
                ))}
              </div>
              <div className="lm-row2">
                <div className="lm-col">
                  <span className="lm-microlab">Duration (s)</span>
                  <input className="lm-in" type="number" min="1" value={c.duration}
                    onChange={(ev) => dfPatch((cc) => ({ ...cc, duration: Number(ev.target.value) || 1 }))} />
                </div>
                <div className="lm-col">
                  <span className="lm-microlab">Discreet</span>
                  <label className="lm-check">
                    <input type="checkbox" checked={!!c.discreet}
                      onChange={(ev) => dfPatch((cc) => ({ ...cc, discreet: ev.target.checked }))} />blur previews</label>
                </div>
              </div>
              <span className="lm-microlab">Prompt</span>
              <textarea className="lm-ta" value={c.prompt || ""} placeholder="what happens in this shot"
                onChange={(ev) => dfPatch((cc) => ({ ...clearPromptOverride(cc), prompt: ev.target.value }))} />
              <div className="lm-hint">the shot's base prompt &mdash; Camera, Lighting and cast are woven in on top when it generates</div>

              <div className="lm-frow">
                <div className="lm-fcol">
                  <FrameSlot which="open" frame={c.openFrame} liveTag={positionTag(dfLive, project, imgSrc, "openFrame")}
                    discreet={c.discreet} framePrev={frameSrc} storeThumb={storeThumb} openPick={openPick}
                    onPatch={(p) => dfPatchFrame("openFrame", p)}
                    extraBtn={dfPrevEntry ? (
                      <button type="button" className="lm-inheritbtn" onClick={dfInheritPrev} disabled={dfHandoff === "wip"}>
                        {dfHandoff === "wip" ? "✂ splicing…" : dfHandoff === "err" ? "✂ splice failed — retry"
                          : dfPrevEntry.c.resultMid ? `✂ splice ${dfPrevEntry.code}'s last frame` : `↳ inherit ${dfPrevEntry.code} close`}
                      </button>
                    ) : null} />
                </div>
                <div className="lm-fcol">
                  <FrameSlot which="close" frame={c.closeFrame} liveTag={positionTag(dfLive, project, imgSrc, "closeFrame")}
                    discreet={c.discreet} framePrev={frameSrc} storeThumb={storeThumb} openPick={openPick}
                    onPatch={(p) => dfPatchFrame("closeFrame", p)} />
                </div>
              </div>

              <span className="lm-microlab" style={{ marginTop: 16 }}>Other references &amp; @tags</span>
              {c.refs.map((r) => {
                const preview = r.thumbId ? thumbs[r.thumbId] : (r.kind === "image" && r.source.startsWith("http") ? r.source : null);
                // Image refs only -- @videoN/@audioN are their own namespaces, never
                // renumbered by position (see loom-core.js's shotText video-ref comment and
                // LoomV2's identical rule on its own ref rows).
                const refLiveTag = r.kind === "image" ? positionTag(dfLive, project, imgSrc, r.id) : null;
                const refPastBudget = r.kind === "image" && !refLiveTag && !!resolvedImage(r, imgSrc);
                return (
                  <div className="lm-refrow" key={r.id}>
                    {r.kind === "image" ? (
                      <label className="lm-refprev" title="Attach image">
                        {preview ? <img src={preview} alt={r.tag} /> : "＋"}
                        <input type="file" accept="image/*" style={{ display: "none" }}
                          onChange={async (e) => { const f = e.target.files[0]; if (!f) return; const id = await storeThumb(f); setRef(dfLive.a.id, c.id, r.id, { thumbId: id, source: r.source || f.name }); }} />
                      </label>
                    ) : <div className="lm-refprev">{r.kind === "video" ? "🎞" : "♪"}</div>}
                    <div className="lm-refbody">
                      <div className="lm-reftoprow">
                        <input className="lm-reftag" value={r.tag} onChange={(e) => setRef(dfLive.a.id, c.id, r.id, { tag: e.target.value })} />
                        {r.kind === "image" && (
                          <span className={"lm-castlive" + (refPastBudget ? " oob" : "")}
                            title={liveTagTitle(refLiveTag, refPastBudget, c.mode, dfLive.code)}>
                            {liveTagText(refLiveTag, refPastBudget, c.mode)}
                          </span>
                        )}
                        <span className="lm-refkind">{r.kind}</span>
                        <button type="button" className="lm-refx" onClick={() => delRef(dfLive.a.id, c.id, r)}>&#10005;</button>
                      </div>
                      <input className="lm-in" placeholder="what to use it for (motion / camera / mood…)" value={r.role}
                        onChange={(e) => setRef(dfLive.a.id, c.id, r.id, { role: e.target.value })} />
                      <input className="lm-in" placeholder="file name or URL" value={r.source}
                        onChange={(e) => setRef(dfLive.a.id, c.id, r.id, { source: e.target.value })} />
                    </div>
                  </div>
                );
              })}
              <div className="lm-addrefrow">
                <button type="button" className="lm-addrefbtn" onClick={() => addRef(dfLive.a.id, c, "image")}>+ Image</button>
                <button type="button" className="lm-addrefbtn" onClick={() => addRef(dfLive.a.id, c, "video")}>+ Video</button>
                <button type="button" className="lm-addrefbtn" onClick={() => addRef(dfLive.a.id, c, "audio")}>+ Audio</button>
              </div>

              <span className="lm-microlab">Music / audio cue</span>
              <input className="lm-in" value={c.audioCue} placeholder="track, beat sync, room tone…"
                onChange={(ev) => dfPatch((cc) => ({ ...cc, audioCue: ev.target.value }))} />

              <span className="lm-microlab">Notes</span>
              <textarea className="lm-ta" value={c.notes} placeholder="blocking, continuity reminders…"
                onChange={(ev) => dfPatch((cc) => ({ ...cc, notes: ev.target.value }))} />

              <button type="button" className="lm-copybtn" onClick={() => copyShot(dfLive)}>Copy shot</button>
              <button type="button" className="lm-genbtn" onClick={() => setGenOpen(true)}>Select in Generate &rarr;</button>
            </div>

            {castSheetOpen && (
              <>
                <div className={"lm-scrim" + (castSheetClosing ? " closing" : "")} onClick={closeCastSheet} />
                <div className={"lm-sheet" + (castSheetClosing ? " closing" : "")}>
                  <div className="lm-sheethandle" />
                  <div className="lm-tabsrow">
                    <button type="button" className={"lm-tabbtn" + (castSheetTab === "cast" ? " on" : "")}
                      onClick={() => setCastSheetTab("cast")}>Cast &amp; assets</button>
                    <button type="button" className={"lm-tabbtn" + (castSheetTab === "footage" ? " on" : "")}
                      onClick={() => setCastSheetTab("footage")}>Footage</button>
                  </div>
                  {castSheetTab === "cast" ? (
                    <>
                      {!modeSendsRefs(c.mode) ? (
                        <div className="lm-i2vnote">{modeSendsLine(c.mode)}</div>
                      ) : castBudget ? (
                        <div className="lm-budget">
                          <span className={castBudget.used > castBudget.budget ? "lm-budget-over" : undefined}>
                            {castBudget.used} of {castBudget.budget} reference slot{castBudget.budget === 1 ? "" : "s"} used
                          </span>
                          {castBudget.frames ? <span> &middot; {castBudget.frames} of 6 held by attached frame{castBudget.frames === 1 ? "" : "s"}</span> : null}
                        </div>
                      ) : null}
                      {(project.assets || []).map((as) => {
                        const inShot = (c.cast || []).includes(as.id);
                        const src = frameSrc(as);
                        const missing = as.kind === "image" && !resolvedImage(as, imgSrc);
                        const liveTag = inShot && as.kind === "image" ? positionTag(dfLive, project, imgSrc, as.id) : null;
                        const pastBudget = inShot && as.kind === "image" && !liveTag && !!resolvedImage(as, imgSrc);
                        return (
                          <button type="button" key={as.id} className="lm-castrow"
                            onClick={() => dfPatch((cc) => ({ ...cc, cast: (cc.cast || []).includes(as.id) ? cc.cast.filter((x) => x !== as.id) : [...(cc.cast || []), as.id] }))}>
                            <span className={"lm-castbox" + (inShot ? " on" : "")} />
                            <div className="lm-castthumb" style={src ? { backgroundImage: `url(${src})` } : undefined}>
                              {!src && (as.kind === "audio" ? "♪" : as.kind === "video" ? "🎞" : "🖼")}
                            </div>
                            <div className="lm-castcol">
                              <div className="lm-castname">{as.name || as.kind}</div>
                              <div className="lm-casttag">{as.tag}</div>
                            </div>
                            {missing && <span className="lm-castmissing">missing</span>}
                            {liveTag || pastBudget ? (
                              <span className={"lm-castlive" + (pastBudget ? " oob" : "")}>{liveTagText(liveTag, pastBudget, c.mode)}</span>
                            ) : null}
                            {!!as.lock && <span className="lm-castlock" title="Lock appearance">&#128274;</span>}
                          </button>
                        );
                      })}
                      {!(project.assets || []).length && <div className="lm-empty">No cast yet.</div>}
                      <div className="lm-castaddrow">
                        <button type="button" className="lm-addrefbtn"
                          onClick={() => setAssets((a) => [...a, { id: uid(), name: "New reference", kind: "image", tag: nextTag(a, "@image"), thumbId: "", source: "", lock: false }])}>
                          + Image ref</button>
                        <button type="button" className="lm-addrefbtn"
                          onClick={() => setAssets((a) => [...a, { id: uid(), name: "New audio", kind: "audio", tag: nextTag(a, "@audio"), thumbId: "", source: "", lock: false }])}>
                          + Audio ref</button>
                      </div>
                    </>
                  ) : (
                    finishedShots.length ? (
                      <div className="lm-footagegrid">
                        {finishedShots.map((e) => (
                          <div key={e.c.id} className="lm-fclip" onClick={() => { dfPickFootage(e.c.resultMid, e.code); closeCastSheet(); }}>
                            <img src={"/thumbs/" + e.c.resultMid + ".jpg"} alt="" />
                            <div className="lm-fclipmeta"><b>{e.code}</b><span>{durOf(e.c)}s</span></div>
                          </div>
                        ))}
                      </div>
                    ) : <div className="lm-empty">no rendered shots yet</div>
                  )}
                  <button type="button" className="lm-sheetclose" onClick={closeCastSheet}>Done</button>
                </div>
              </>
            )}
          </div>
        );
      })()}

      {/* ---- Generate -- third increment (2026-08-03). Real submit, real cost preview, real
          generation-state tracking; see the increment's own report for the full credit-safety
          trace (why toggling Mobile view, closing this screen, closing Shot Detail, and
          navigating the board can never orphan an in-flight generation here). Deliberately a
          SEPARATE top-level conditional from the dfOpen block above, not nested inside it --
          genOpen/dfOpen are independent booleans (closing Generate returns to Shot Detail;
          closing Shot Detail's own ✕ closes both), matching the locked design's own
          openGenerate/closeGenerate/backToShot split. */}
      {genOpen && dfLive && (() => {
        const c = dfLive.c;
        const gp = genPrice[c.id] || {};
        // tallyPrices/formatCostEstimate/costTooltip (loom-core.js) reused VERBATIM on a
        // one-element array -- the exact same aggregate math every other price display in
        // this file already trusts, not a new formatter invented for this screen.
        const tally = gp.pr ? tallyPrices([gp.pr]) : null;
        const costText = gp.noInput ? "attach a frame or cast image first"
          : gp.loading ? "checking…"
          : tally ? formatCostEstimate(tally) : "—";
        const costTitle = tally ? costTooltip(tally) : "";
        // genBusy mirrors LoomV2's own `busy` guard on its "Use an existing video instead"
        // button exactly (see LoomV2's gen block) -- "paused" does NOT count as busy (the
        // auto-poll has genuinely stopped, so a manual attach/re-submit isn't racing a live
        // network call).
        const gsSelf = genState[c.id];
        const genBusy = !!(gsSelf && gsSelf.phase && gsSelf.phase !== "done" && gsSelf.phase !== "error" && gsSelf.phase !== "paused");
        // usesCloseFrame (loom-core.js): I2V consumes only the opening frame; FLF/R2V/V2V
        // all reserve a closing-frame slot when one resolves -- the SAME predicate
        // shotImageRefs()/the Cast sheet's own modeSendsRefs already gate on, not a second,
        // independently-guessed mode table.
        const showClose = usesCloseFrame(c.mode);
        return (
          <div className="lm-gen">
            <div className="lm-gen-top">
              <button type="button" className="lm-gen-back" onClick={() => setGenOpen(false)}>&lsaquo; {dfLive.code}</button>
              <span className="lm-gen-title">{c.title || "untitled"}</span>
              <button type="button" className="lm-df-close" title="Close" onClick={() => { setGenOpen(false); setDfOpen(false); }}>&#10005;</button>
            </div>
            {/* Image/Edit/Reference/Video tab strip -- fourth increment. Mirrors LoomV2's own
                GEN_ICONS rail (same four tabs, same order, same "Video" default); reuses the
                Cast & assets sheet's own .lm-tabsrow/.lm-tabbtn chrome rather than inventing a
                new segmented-control style for a second time in this file. */}
            <div className="lm-tabsrow" style={{ margin: "0 16px 8px" }}>
              {["Image", "Edit", "Reference", "Video"].map((t) => (
                <button type="button" key={t} className={"lm-tabbtn" + (genTab === t ? " on" : "")}
                  onClick={() => setGenTab(t)}>{t}</button>
              ))}
            </div>
            {acct && (
              <div className="lm-bal" style={{ margin: "0 16px 8px" }}>
                &#9889; {acct.credits == null ? "—" : acct.credits} credits &middot; {acct.cards || 0} card{acct.cards === 1 ? "" : "s"}
                {acct.claim_credits ? <span style={{ color: "var(--gold)" }}> &middot; +{acct.claim_credits} claimable</span> : null}
              </div>
            )}
            <div className="lm-gen-body">
            {genTab === "Image" && (() => {
              const gi = genImgState[c.id] || {};
              const busyI = gi.phase === "submitting" || gi.phase === "running";
              const compat = (imgModel && imgModel.compatibility) || {};
              const restr = (imgModel && imgModel.restrictions) || {};
              const negOff = compat.negativePrompt === false;
              const stepsOff = compat.samplingSteps === false;
              const cfgOff = compat.cfgScale === false;
              const stepsB = restr.samplingSteps || {};
              const cfgB = restr.cfgScale || {};
              const offTitle = "This model doesn’t use this setting";
              return (
                <>
                  <span className="lm-microlab">Model</span>
                  <button type="button" className="lm-selrow" onClick={() => { setPickerKind("base"); setPickerOpen(true); }}>
                    {imgModel && imgModel.preview_url ? <img className="lm-selthumb" src={imgModel.preview_url} alt="" /> : null}
                    <span className="lm-selname">{imgModel ? imgModel.title : "none — browse models"}</span>
                    <span className="lm-selhint">&#9776; browse</span>
                  </button>
                  {imgModel && (imgModel.sampling_method || (imgModel.capabilities || []).length > 0) && (
                    <div className="lm-caps">
                      {imgModel.sampling_method ? <span className="lm-cap method">{imgModel.sampling_method}</span> : null}
                      {(imgModel.capabilities || []).map((cp) => <span key={cp} className="lm-cap">{cp}</span>)}
                    </div>
                  )}
                  {imgModel && imgModel.versions && imgModel.versions.length > 1 && (
                    <select className="lm-gensel" value={imgModel.version_id || ""} onChange={(ev) => pickVersion(ev.target.value)}
                      title="This model's published releases -- PixAI defaults to the latest; pick another to generate against it instead" aria-label="Model version">
                      {imgModel.versions.map((v) => <option key={v.version_id} value={v.version_id}>{v.label || v.version_id}</option>)}
                    </select>
                  )}
                  {imgLoras.length > 0 && (
                    <div className="lm-loras">
                      {imgLoras.map((l) => {
                        const incompat = loraIncompat(imgModel && imgModel.model_type, l.lora_base_type);
                        return (
                          <div key={l.model_id} className={"lm-lchip" + ((l.failed || incompat) ? " failed" : "")}>
                            <span className="lm-lnm" title={incompat ? l.title + " — needs a different base architecture than the one selected; remove it or switch the base" : l.title}>
                              {l.title}{!l.version_id ? (l.failed ? " ⚠" : " ⏳") : (incompat ? " ⚠" : "")}
                            </span>
                            <span className="lm-lw">
                              <input type="range" step="0.1" min={loraRange[0]} max={loraRange[1]} value={l.weight}
                                title={"Weight — " + loraRange[0] + " to " + loraRange[1] + " for this base model"}
                                onChange={(ev) => { const w = Math.max(loraRange[0], Math.min(loraRange[1], +ev.target.value || 0));
                                  setImgLoras((cur) => cur.map((x) => x.model_id === l.model_id ? { ...x, weight: w } : x)); }} />
                              <b>{(+l.weight).toFixed(1)}</b>
                            </span>
                            <button type="button" className="lm-lrm" title="Remove"
                              onClick={() => {
                                setImgLoras((cur) => cur.filter((x) => x.model_id !== l.model_id));
                              }}>&times;</button>
                            {l.versions && l.versions.length > 1 && (
                              <select className="lm-lorver" value={l.version_id || ""}
                                onChange={(ev) => {
                                  const vid = ev.target.value;
                                  const v = l.versions.find((x) => x.version_id === vid);
                                  if (!v) return;
                                  setImgLoras((cur) => cur.map((x) => x.model_id === l.model_id
                                    ? { ...x, version_id: v.version_id || "", lora_base_type: v.lora_base_model_type || "",
                                        trigger_words: v.trigger_words || "", failed: !v.version_id }
                                    : x));
                                }}>
                                {l.versions.map((v) => <option key={v.version_id} value={v.version_id}>{v.label || v.version_id}</option>)}
                              </select>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                  <button type="button" className="lm-addrefbtn" style={{ marginTop: 6 }}
                    onClick={() => { setPickerKind("lora"); setPickerOpen(true); }}>+ add LoRA</button>
                  {acct && acct.lora_cap != null && (
                    <span className="lm-hint" style={{ marginLeft: 8 }}>{imgLoras.length} / {acct.lora_cap} LoRAs</span>
                  )}
                  <span className="lm-microlab" style={{ marginTop: 12 }}>Image prompt</span>
                  <textarea className="lm-ta" value={c.imgPrompt || ""} placeholder="describe the reference still (subject, pose, composition, light)…"
                    onChange={(ev) => dfPatch((cc) => ({ ...cc, imgPrompt: ev.target.value }))} />
                  <button type="button" className="lm-mini2-btn" onClick={() => dfPatch((cc) => ({ ...cc, imgPrompt: [cc.title, cc.prompt, (cc.openFrame && cc.openFrame.desc) || "", cc.lighting || ""].filter(Boolean).join(", ") }))}>
                    &#8615; seed from shot description</button>
                  <details style={{ marginTop: 10 }}>
                    <summary className="lm-hint" style={{ cursor: "pointer" }}>Advanced</summary>
                    <textarea className="lm-ta" style={{ marginTop: 6 }} value={imgAdv.negative}
                      placeholder="lowres, text, watermark…" disabled={negOff} title={negOff ? offTitle : ""}
                      onChange={(ev) => setImgAdv((a) => ({ ...a, negative: ev.target.value }))} />
                    <div className="lm-row2">
                      <div className="lm-col"><span className="lm-microlab">Steps</span>
                        <input className="lm-in" type="number" min={stepsB.min != null ? stepsB.min : 1} max={stepsB.max != null ? stepsB.max : 150} step="1"
                          value={imgAdv.steps} disabled={stepsOff} title={stepsOff ? offTitle : ""}
                          onChange={(ev) => setImgAdv((a) => ({ ...a, steps: +ev.target.value || 25 }))} /></div>
                      <div className="lm-col"><span className="lm-microlab">CFG scale</span>
                        <input className="lm-in" type="number" min={cfgB.min != null ? cfgB.min : 1} max={cfgB.max != null ? cfgB.max : 30} step="0.5"
                          value={imgAdv.cfg} disabled={cfgOff} title={cfgOff ? offTitle : ""}
                          onChange={(ev) => setImgAdv((a) => ({ ...a, cfg: +ev.target.value || 7 }))} /></div>
                    </div>
                    {modelDefaults && (
                      <div className="lm-hint" style={{ display: "flex", justifyContent: "space-between" }}>
                        <span>&#10003; using this model's tuned preset</span>
                        <button type="button" className="lm-mini2-btn" onClick={() => setImgAdv((a) => ({ ...a,
                          negative: modelDefaults.negative_prompt || a.negative,
                          steps: modelDefaults.sampling_steps || a.steps,
                          cfg: modelDefaults.cfg_scale || a.cfg }))}>&#8630; reset</button>
                      </div>
                    )}
                  </details>
                  <span className="lm-microlab" style={{ marginTop: 12 }}>Aspect</span>
                  <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                    {[[1, 1, "1:1"], [3, 4, "3:4"], [4, 3, "4:3"], [2, 3, "2:3"], [3, 2, "3:2"],
                      [9, 16, "9:16"], [16, 9, "16:9"], [3, 1, "3:1"]].map(([rw, rh, label]) => (
                      <button type="button" key={label}
                        className={"lm-modechip" + (imgAdv.aspectW === rw && imgAdv.aspectH === rh ? " on" : "")}
                        style={{ flex: "0 0 auto", padding: "6px 10px" }}
                        onClick={() => setImgAdv((a) => ({ ...a, aspectW: rw, aspectH: rh }))}>{label}</button>
                    ))}
                  </div>
                  <div className="lm-row2">
                    <div className="lm-col"><span className="lm-microlab">Size &middot; long edge</span>
                      <select className="lm-gensel" style={{ marginTop: 0 }} value={imgAdv.size}
                        onChange={(ev) => setImgAdv((a) => ({ ...a, size: +ev.target.value }))}>
                        <option value="768">S &middot; 768</option><option value="1024">M &middot; 1024</option>
                        <option value="1536">L &middot; 1536</option><option value="2048">XL &middot; 2048</option>
                      </select></div>
                    <div className="lm-col"><span className="lm-microlab">Custom W&times;H</span>
                      <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
                        <input className="lm-in" type="number" min="64" max="4096" step="8" placeholder="W" value={imgAdv.customW}
                          onChange={(ev) => setImgAdv((a) => ({ ...a, customW: ev.target.value }))} />
                        <span className="lm-hint">&times;</span>
                        <input className="lm-in" type="number" min="64" max="4096" step="8" placeholder="H" value={imgAdv.customH}
                          onChange={(ev) => setImgAdv((a) => ({ ...a, customH: ev.target.value }))} />
                      </div></div>
                  </div>
                  <div className="lm-hint">{(() => { const d = resolveGenDims(imgAdv); return "→ " + d.w + " × " + d.h + (d.custom ? " · custom" : " px"); })()}</div>
                  <div className="lm-row2">
                    <div className="lm-col"><span className="lm-microlab">Mode</span>
                      <select className="lm-gensel" style={{ marginTop: 0 }} value={imgAdv.mode}
                        onChange={(ev) => setImgAdv((a) => ({ ...a, mode: ev.target.value }))}>
                        <option value="auto">Auto</option><option value="lite">Lite</option>
                        <option value="standard">Standard</option><option value="pro">Pro</option><option value="ultra">Ultra</option>
                      </select></div>
                    <div className="lm-col"><span className="lm-microlab">Count</span>
                      <select className="lm-gensel" style={{ marginTop: 0 }} value={imgAdv.count}
                        onChange={(ev) => setImgAdv((a) => ({ ...a, count: +ev.target.value }))}>
                        <option value="1">1</option><option value="2">2</option><option value="3">3</option><option value="4">4</option>
                      </select></div>
                  </div>
                  <span className="lm-microlab">Seed &middot; blank = random</span>
                  <input className="lm-in" type="number" placeholder="random" value={imgAdv.seed}
                    onChange={(ev) => setImgAdv((a) => ({ ...a, seed: ev.target.value }))} />
                  <label className="lm-check" title="This IS the site's Turbo tier (priority=1000): a faster runner. Costs more credits when paid, but a matching free card covers it.">
                    <input type="checkbox" checked={imgAdv.highPriority}
                      onChange={(ev) => setImgAdv((a) => ({ ...a, highPriority: ev.target.checked }))} /> High priority &middot; Turbo (faster)</label>
                  <label className="lm-check">
                    <input type="checkbox" checked={imgAdv.promptHelper}
                      onChange={(ev) => setImgAdv((a) => ({ ...a, promptHelper: ev.target.checked }))} /> Prompt helper</label>
                  <div className="lm-gencost">
                    <span className="lm-gencosttext" title={priceTitle(imgPrice, c.id)}>{priceLine(imgPrice, c.id, "Pick a model and write a prompt to see the cost.")}</span>
                  </div>
                  <button type="button" className="lm-genbtn"
                    disabled={busyI || !imgModel || !(c.imgPrompt || "").trim() || anyLoraUnresolved(imgLoras) || imgLoras.some((l) => loraIncompat(imgModel && imgModel.model_type, l.lora_base_type)) || overLoraCap(imgLoras, acct && acct.lora_cap)}
                    onClick={() => genImage(dfLive)}>
                    {busyI ? (gi.msg || "generating…")
                      : anyLoraUnresolved(imgLoras) ? "waiting on LoRA…"
                      : imgLoras.some((l) => loraIncompat(imgModel && imgModel.model_type, l.lora_base_type)) ? "incompatible LoRA — remove or switch base"
                      : overLoraCap(imgLoras, acct && acct.lora_cap) ? "remove " + (imgLoras.length - acct.lora_cap) + " LoRA" + ((imgLoras.length - acct.lora_cap) === 1 ? "" : "s") + " to continue"
                      : "✦ Generate reference image"}
                  </button>
                  {gi.phase === "error" && <div className="lm-gerr">{gi.msg}</div>}
                  {gi.mid && (
                    <div className="lm-imgresult">
                      <img src={"/thumbs/" + gi.mid + ".jpg"} alt="result" />
                      <div className="lm-route">
                        <button type="button" className={"lm-routebtn" + (gi.routed === "open" ? " on" : "")} onClick={() => routeImg(dfLive, "open", c.id)}>open frame</button>
                        <button type="button" className={"lm-routebtn" + (gi.routed === "close" ? " on" : "")} onClick={() => routeImg(dfLive, "close", c.id)}>close frame</button>
                        <button type="button" className={"lm-routebtn" + (gi.routed === "cast" ? " on" : "")} onClick={() => routeImg(dfLive, "cast", c.id)}>cast</button>
                      </div>
                      {gi.routed && <div className="lm-ok2">&#10003; sent to {gi.routed} — it now feeds this shot's video gen</div>}
                    </div>)}
                </>
              );
            })()}
            {genTab === "Edit" && (() => {
              const ge = genEditState[c.id] || {};
              const busyE = ge.phase === "submitting" || ge.phase === "running";
              const src = c.openFrame && c.openFrame.mediaId;
              const gf = genFixState[c.id] || {};
              const busyF = gf.phase === "submitting" || gf.phase === "running";
              return (
                <>
                  {/* Edit/Fixer/Enhance sub-strip -- matches the locked design's own
                      editSubChips verbatim AND the real, already-shipped
                      GenerateDrawer.jsx's identical mgdock-subtabs (its own real
                      Edit/Fixer/Enhance strip, wired to FixTab.jsx and FiltersPanel.jsx).
                      Reuses .lm-tabsrow/.lm-tabbtn verbatim -- the same classes the Cast
                      sheet's own Cast/Footage strip and the model picker's Models/LoRAs
                      strip already use, not a new sub-tab visual language. */}
                  <div className="lm-tabsrow" style={{ marginBottom: 10 }}>
                    <button type="button" className={"lm-tabbtn" + (editSub === "edit" ? " on" : "")}
                      onClick={() => setEditSub("edit")}>Edit</button>
                    <button type="button" className={"lm-tabbtn" + (editSub === "fixer" ? " on" : "")}
                      onClick={() => setEditSub("fixer")}>Fixer</button>
                    <button type="button" className={"lm-tabbtn" + (editSub === "enhance" ? " on" : "")}
                      onClick={() => setEditSub("enhance")}>Enhance</button>
                  </div>
                  {editSub === "edit" && (<>
                  <span className="lm-microlab">Source — this shot's open frame</span>
                  {src ? (
                    <div className="lm-genframe" style={{ height: 120, maxWidth: 220 }}>
                      <img src={"/thumbs/" + src + ".jpg"} alt="source" />
                    </div>
                  ) : <div className="lm-empty">No open-frame image yet — route one from the <b>Image</b> tab, or pick it into the open frame on Shot Detail.</div>}
                  <span className="lm-microlab" style={{ marginTop: 12 }}>Edit instruction</span>
                  <textarea className="lm-ta" value={c.editPrompt || ""} placeholder="e.g. make it night, add rain, warmer key light…"
                    onChange={(ev) => dfPatch((cc) => ({ ...cc, editPrompt: ev.target.value }))} />
                  <div className="lm-gencost">
                    <span className="lm-gencosttext" title={priceTitle(editPrice, c.id)}>{priceLine(editPrice, c.id, "Add a source image and instruction to see the cost.")}</span>
                  </div>
                  <button type="button" className="lm-genbtn" disabled={busyE || !src} onClick={() => genEdit(dfLive)}>
                    {busyE ? (ge.msg || "editing…") : "✦ Edit the open frame"}
                  </button>
                  {ge.phase === "error" && <div className="lm-gerr">{ge.msg}</div>}
                  {ge.mid && (
                    <div className="lm-imgresult">
                      <img src={"/thumbs/" + ge.mid + ".jpg"} alt="result" />
                      <div className="lm-route">
                        <button type="button" className={"lm-routebtn" + (ge.routed === "open" ? " on" : "")} onClick={() => routeGen(genEditState, setGenEditState, dfLive, "open", c.id)}>open frame</button>
                        <button type="button" className={"lm-routebtn" + (ge.routed === "close" ? " on" : "")} onClick={() => routeGen(genEditState, setGenEditState, dfLive, "close", c.id)}>close frame</button>
                        <button type="button" className={"lm-routebtn" + (ge.routed === "cast" ? " on" : "")} onClick={() => routeGen(genEditState, setGenEditState, dfLive, "cast", c.id)}>cast</button>
                      </div>
                      {ge.routed && <div className="lm-ok2">&#10003; sent to {ge.routed}</div>}
                    </div>)}
                  </>)}
                  {editSub === "fixer" && (<>
                  {/* Fixer -- real box-drawing canvas over this shot's real open frame,
                      real /api/price preview, real confirm-gated submit through the real
                      /api/fix endpoint (genFix, useGenerationPipeline). See this
                      component's own Fixer state block (declared with editSub/fixTag/
                      fixBoxes above) for the full port trace against FixTab.jsx. */}
                  <span className="lm-microlab">Source — this shot's open frame</span>
                  {src ? (
                    <div className="lm-fixwrap">
                      <img ref={fixImgRef} src={"/thumbs/" + src + ".jpg"} alt="source"
                        draggable={false} onLoad={fixPaint} />
                      <canvas ref={fixCanvasRef}
                        onPointerDown={fixDown} onPointerMove={fixMove}
                        onPointerUp={fixUp} onPointerLeave={fixUp} />
                    </div>
                  ) : <div className="lm-empty">No open-frame image yet — route one from the <b>Image</b> tab, or pick it into the open frame on Shot Detail.</div>}
                  {src && <div className="lm-fixhint">Drag a box over the hand or face on the source.</div>}
                  <div className="lm-modechips">
                    {["face", "hand"].map((t) => (
                      <button type="button" key={t} className={"lm-modechip" + (fixTag === t ? " on" : "")}
                        style={fixTag === t ? { borderColor: FIX_COLORS[t], color: FIX_COLORS[t] } : null}
                        onClick={() => setFixTag(t)}>{t === "face" ? "Face" : "Hand"}</button>
                    ))}
                  </div>
                  {fixBoxes.length > 0 && (
                    <button type="button" className="lm-addrefbtn" style={{ marginTop: 8 }}
                      onClick={() => setFixBoxes([])}>
                      Clear {fixBoxes.length} box{fixBoxes.length === 1 ? "" : "es"}
                    </button>
                  )}
                  <div className="lm-fixwarn">A fix can't be card-covered — it always spends, and always asks first.</div>
                  <div className="lm-gencost">
                    <span className="lm-gencosttext" title={priceTitle(genFixPrice, c.id)}>{priceLine(genFixPrice, c.id, "Drag a box over a hand or face to see the cost.")}</span>
                  </div>
                  <button type="button" className="lm-genbtn" disabled={busyF || !src || !fixBoxes.length}
                    title={!src ? "This shot has no open-frame image yet" : !fixBoxes.length ? "Drag at least one box" : "Submit the repair — always spends"}
                    onClick={() => genFix(dfLive, scaleFixBoxes(fixBoxes, fixImgRef.current))}>
                    {busyF ? (gf.msg || "fixing…") : "✦ Fix " + fixTag}
                  </button>
                  {gf.phase === "error" && <div className="lm-gerr">{gf.msg}</div>}
                  {gf.mid && (
                    <div className="lm-imgresult">
                      <img src={"/thumbs/" + gf.mid + ".jpg"} alt="result" />
                      <div className="lm-route">
                        <button type="button" className={"lm-routebtn" + (gf.routed === "open" ? " on" : "")} onClick={() => routeGen(genFixState, setGenFixState, dfLive, "open", c.id)}>open frame</button>
                        <button type="button" className={"lm-routebtn" + (gf.routed === "close" ? " on" : "")} onClick={() => routeGen(genFixState, setGenFixState, dfLive, "close", c.id)}>close frame</button>
                        <button type="button" className={"lm-routebtn" + (gf.routed === "cast" ? " on" : "")} onClick={() => routeGen(genFixState, setGenFixState, dfLive, "cast", c.id)}>cast</button>
                      </div>
                      {gf.routed && <div className="lm-ok2">&#10003; sent to {gf.routed}</div>}
                    </div>)}
                  </>)}
                  {editSub === "enhance" && (
                    <>
                      <span className="lm-microlab">Art filters &middot; free, no generation</span>
                      <button type="button" className="lm-openfiltersbtn" onClick={openFilterCompare}>&#9673; Open filters</button>
                      <div className="lm-hint" style={{ marginTop: 8 }}>Gradient overlays, not AI — applied right in the browser: no credits, no request, works offline.</div>
                    </>
                  )}
                </>
              );
            })()}
            {genTab === "Reference" && (() => {
              const gr = genRefState[c.id] || {};
              const busyR = gr.phase === "submitting" || gr.phase === "running";
              const refs = (project.assets || []).filter((a) => a.kind === "image" && a.mediaId);
              return (
                <>
                  {/* Opening/Closing frame pair -- Loom Mobile.dc.html's onRefTab block shows
                      this same pair (with the same dfHasPrev/dfInheritPrev "inherit prev
                      close" affordance) at the top of the Reference tab, not just inside Deep
                      Focus's own body. Real gap, closed 2026-08-04 (session 2) by reusing the
                      exact same FrameSlot calls Deep Focus's body already makes above --
                      same component, same props shape, not a second implementation. */}
                  <div className="lm-frow">
                    <div className="lm-fcol">
                      <FrameSlot which="open" frame={c.openFrame} liveTag={positionTag(dfLive, project, imgSrc, "openFrame")}
                        discreet={c.discreet} framePrev={frameSrc} storeThumb={storeThumb} openPick={openPick}
                        onPatch={(p) => dfPatchFrame("openFrame", p)}
                        extraBtn={dfPrevEntry ? (
                          <button type="button" className="lm-inheritbtn" onClick={dfInheritPrev} disabled={dfHandoff === "wip"}>
                            {dfHandoff === "wip" ? "✂ splicing…" : dfHandoff === "err" ? "✂ splice failed — retry"
                              : dfPrevEntry.c.resultMid ? `✂ splice ${dfPrevEntry.code}'s last frame` : `↳ inherit ${dfPrevEntry.code} close`}
                          </button>
                        ) : null} />
                    </div>
                    <div className="lm-fcol">
                      <FrameSlot which="close" frame={c.closeFrame} liveTag={positionTag(dfLive, project, imgSrc, "closeFrame")}
                        discreet={c.discreet} framePrev={frameSrc} storeThumb={storeThumb} openPick={openPick}
                        onPatch={(p) => dfPatchFrame("closeFrame", p)} />
                    </div>
                  </div>
                  <span className="lm-microlab">References — cast @image members ({refs.length})</span>
                  {refs.length ? (
                    <div className="lm-refstrip">{refs.map((a) => (<img key={a.id} src={"/thumbs/" + a.mediaId + ".jpg"} title={a.tag} alt="" />))}</div>
                  ) : <div className="lm-empty">No cast @image references with a gallery image yet — add some via the Cast &amp; assets sheet.</div>}
                  <span className="lm-microlab" style={{ marginTop: 12 }}>Prompt</span>
                  <textarea className="lm-ta" value={c.refPrompt || ""} placeholder="compose a new still from the references…"
                    onChange={(ev) => dfPatch((cc) => ({ ...cc, refPrompt: ev.target.value }))} />
                  <div className="lm-gencost">
                    <span className="lm-gencosttext" title={priceTitle(refPrice, c.id)}>{priceLine(refPrice, c.id, "Add references and a prompt to see the cost.")}</span>
                  </div>
                  <button type="button" className="lm-genbtn" disabled={busyR || !refs.length} onClick={() => genRef(dfLive)}>
                    {busyR ? (gr.msg || "generating…") : "✦ Generate from references"}
                  </button>
                  {gr.phase === "error" && <div className="lm-gerr">{gr.msg}</div>}
                  {gr.mid && (
                    <div className="lm-imgresult">
                      <img src={"/thumbs/" + gr.mid + ".jpg"} alt="result" />
                      <div className="lm-route">
                        <button type="button" className={"lm-routebtn" + (gr.routed === "open" ? " on" : "")} onClick={() => routeGen(genRefState, setGenRefState, dfLive, "open", c.id)}>open frame</button>
                        <button type="button" className={"lm-routebtn" + (gr.routed === "close" ? " on" : "")} onClick={() => routeGen(genRefState, setGenRefState, dfLive, "close", c.id)}>close frame</button>
                        <button type="button" className={"lm-routebtn" + (gr.routed === "cast" ? " on" : "")} onClick={() => routeGen(genRefState, setGenRefState, dfLive, "cast", c.id)}>cast</button>
                      </div>
                      {gr.routed && <div className="lm-ok2">&#10003; sent to {gr.routed}</div>}
                    </div>)}
                </>
              );
            })()}
            {genTab === "Video" && (<>
              <span className="lm-microlab">Mode</span>
              <div className="lm-modechips">
                {MODES.map((m) => (
                  <button type="button" key={m} className={"lm-modechip" + (m === c.mode ? " on" : "")}
                    onClick={() => dfPatch((cc) => setShotMode(cc, m))}>{m}</button>
                ))}
              </div>

              <span className="lm-microlab">Continuity</span>
              <div className="lm-modechips">
                {Object.keys(CONNECT).map((k) => (
                  <button type="button" key={k} className={"lm-modechip" + (k === (c.connect || "new") ? " on" : "")}
                    title={CONNECT[k].hint} onClick={() => dfPatch((cc) => setShotConnect(cc, k))}>{CONNECT[k].label}</button>
                ))}
              </div>

              <span className="lm-microlab">Prompt</span>
              <textarea className="lm-ta" value={c.prompt || ""} placeholder="Describe the motion…"
                onChange={(ev) => {
                  // Same rule as LoomV2's own Prompt field / Shot Detail's copy: typing here
                  // always means "auto-compose, using this text" -- clears an active override
                  // immediately, flashing a brief, self-clearing notice since that is silent-
                  // until-you-notice otherwise (see LoomV2's identical overrideClearedFlash).
                  if (c.promptOverride) { setGenOverrideFlash(true); setTimeout(() => setGenOverrideFlash(false), 1600); }
                  dfPatch((cc) => ({ ...clearPromptOverride(cc), prompt: ev.target.value }));
                }} />
              <div className="lm-hint">motion only — camera, lighting and cast weave in on top</div>
              {c.promptOverride && <div className="lm-genoverride">&#9998; override active — Camera/Lighting/cast not woven in</div>}
              {genOverrideFlash && <div className="lm-genflash">override cleared — back to auto-compose</div>}

              <span className="lm-microlab" style={{ marginTop: 12 }}>Camera <button type="button" className="lm-gentermbtn" onClick={() => genTogglePal("camera")}>+ terms</button></span>
              <input className="lm-in" value={c.camera || ""} placeholder="e.g. slow push in, shallow DoF"
                onChange={(ev) => dfPatch((cc) => ({ ...cc, camera: ev.target.value }))} />
              {genPalFor === "camera" && (
                <div className="lm-gentermpal">{Object.entries(CAM_PALETTE).map(([grp, items]) => (
                  <div key={grp} className="lm-gentermgrp">
                    <div className="lm-gentermgrpt">{grp}</div>
                    {items.map((t) => (<span key={t} className="lm-genchip" onClick={() => genAppendTo("camera", t)}>{t}</span>))}
                  </div>
                ))}</div>
              )}

              <span className="lm-microlab">Lighting <button type="button" className="lm-gentermbtn" onClick={() => genTogglePal("lighting")}>+ terms</button></span>
              <input className="lm-in" value={c.lighting || ""} placeholder="e.g. moonlit, soft haze"
                onChange={(ev) => dfPatch((cc) => ({ ...cc, lighting: ev.target.value }))} />
              {genPalFor === "lighting" && (
                <div className="lm-gentermpal">{LIGHTING_PALETTE.map((t) => (<span key={t} className="lm-genchip" onClick={() => genAppendTo("lighting", t)}>{t}</span>))}</div>
              )}

              <div className="lm-row2">
                <div className="lm-col">
                  <span className="lm-microlab">Transition in <button type="button" className="lm-gentermbtn" onClick={() => genTogglePal("transIn")}>+ terms</button></span>
                  <input className="lm-in" value={c.transIn || ""} placeholder="cut, dissolve"
                    onChange={(ev) => dfPatch((cc) => ({ ...cc, transIn: ev.target.value }))} />
                  {genPalFor === "transIn" && (
                    <div className="lm-gentermpal">{TRANS_PALETTE.map((t) => (<span key={t} className="lm-genchip" onClick={() => dfPatch((cc) => ({ ...cc, transIn: t }))}>{t}</span>))}</div>
                  )}
                </div>
                <div className="lm-col">
                  <span className="lm-microlab">Transition out <button type="button" className="lm-gentermbtn" onClick={() => genTogglePal("transOut")}>+ terms</button></span>
                  <input className="lm-in" value={c.transOut || ""} placeholder="cut, dissolve"
                    onChange={(ev) => dfPatch((cc) => ({ ...cc, transOut: ev.target.value }))} />
                  {genPalFor === "transOut" && (
                    <div className="lm-gentermpal">{TRANS_PALETTE.map((t) => (<span key={t} className="lm-genchip" onClick={() => dfPatch((cc) => ({ ...cc, transOut: t }))}>{t}</span>))}</div>
                  )}
                </div>
              </div>

              {/* Mode-aware weave summary -- shares modeSendsLine/modeSendsRefs with the Cast
                  sheet above so the two surfaces cannot silently disagree about which modes
                  actually send the cast/ref bank vs. cite it in the prompt only. */}
              <div className="lm-genrefline">
                {(c.cast || []).length} cast &middot; {(c.refs || []).length} refs
                {!modeSendsRefs(c.mode) && <><br />{modeSendsLine(c.mode)}</>}
              </div>

              <span className="lm-microlab" style={{ marginTop: 12 }}>{showClose ? "Start / end frame" : "Start frame"}</span>
              <div className="lm-genframerow">
                <div className="lm-genframecol">
                  <div className="lm-genframe">
                    {frameSrc(c.openFrame) ? <img src={frameSrc(c.openFrame)} alt="opening frame" /> : "no frame"}
                    <span className="lm-genframetag">{positionTag(dfLive, project, imgSrc, "openFrame") || "—"}</span>
                  </div>
                </div>
                {showClose && (
                  <div className="lm-genframecol">
                    <div className="lm-genframe">
                      {frameSrc(c.closeFrame) ? <img src={frameSrc(c.closeFrame)} alt="closing frame" /> : "no frame"}
                      <span className="lm-genframetag">{positionTag(dfLive, project, imgSrc, "closeFrame") || "—"}</span>
                    </div>
                  </div>
                )}
              </div>
              <div className="lm-hint">frames are attached on Shot Detail — this is a preview only</div>

              <span className="lm-microlab" style={{ marginTop: 12 }}>What will be sent</span>
              {/* shotText(), the REAL composed-prompt assembler (loom-core.js) -- not a fake
                  mockup string. Shows the owner the exact text about to be submitted, honoring
                  an active promptOverride verbatim, before they ever tap Generate. */}
              <div className="lm-genpreview">{shotText(dfLive, project, imgSrc)}</div>

              {/* The Video tab's two sanctioned cosmetic pieces (owner correction 2026-08-04:
                  of the design's 5 missing elements, only these two are safe to add --
                  negative prompt/channel have no real submit field, weave-mode may be
                  redundant). Loom Mobile.dc.html:408 (the static "PixAI Motion v2" model
                  row, non-interactive there too) and :411 (the capability badges). The
                  design pairs the model row with Duration -- that control already lives on
                  Shot Detail here, so no duplicate is invented alongside the label. */}
              <span className="lm-microlab" style={{ marginTop: 12 }}>Model</span>
              <div className="lm-genmodelrow"><span className="lm-genmodelthumb" />PixAI Motion v2</div>
              <div className="lm-gencaps">
                {["15s", "multi-ref", "audio", "end-frame"].map((cap) => (
                  <span key={cap} className="lm-gencap">{cap}</span>
                ))}
              </div>

              {/* Channel -- Loom Mobile.dc.html:412-414's rowGroup, restored 2026-08-06 after
                  an owner correction: this is the REAL Normal/Enhanced channel the desktop
                  drawer has always had (mg-generate-drawer's own select, submitting
                  is_private), NOT a design invention -- the earlier audit's "no channel
                  field exists" claim was wrong. Same control shape as the drawer, same
                  mapping (enhanced -> is_private), stored per-shot so shotPayload carries
                  it into both the price preview and the real submit. */}
              <div className="lm-row2">
                <div className="lm-col">
                  <span className="lm-microlab">Channel</span>
                  <select className="lm-gensel" value={c.isPrivate ? "enhanced" : "normal"}
                    onChange={(ev) => dfPatch((cc) => ({ ...cc, isPrivate: ev.target.value === "enhanced" }))}>
                    <option value="normal">Normal</option>
                    <option value="enhanced">👑 Enhanced</option>
                  </select>
                </div>
                <div className="lm-col">
                  <div className="lm-hint" style={{ marginTop: 22 }}>Please keep creations SFW</div>
                </div>
              </div>

              {/* generate_audio / audio_language -- REAL fields the card shape has always
                  carried (see newCard()'s own audioGen/audioLanguage comment), but with no UI
                  anywhere on mobile until now. The 5-value enum matches static/mg-generate-
                  drawer.js's own real <select> exactly (english/japanese/chinese/korean/none),
                  not an invented list. */}
              <label className="lm-check" style={{ marginTop: 6 }}>
                <input type="checkbox" checked={!!c.audioGen}
                  onChange={(ev) => dfPatch((cc) => ({ ...cc, audioGen: ev.target.checked }))} />
                Generate audio (spoken lines become voiceover)
              </label>
              {c.audioGen && (
                <select className="lm-gensel" value={c.audioLanguage || "english"}
                  onChange={(ev) => dfPatch((cc) => ({ ...cc, audioLanguage: ev.target.value }))}>
                  <option value="english">English</option>
                  <option value="japanese">Japanese</option>
                  <option value="chinese">Chinese</option>
                  <option value="korean">Korean</option>
                  <option value="none">SE only (no dialogue)</option>
                </select>
              )}

              <div className="lm-gencost">
                <span className="lm-gencosttext" title={costTitle}>{costText}</span>
                <span className="lm-hint">uploads are free &middot; one job at a time</span>
              </div>

              {/* generateShot -- the SAME real function batchGenerate's own per-card loop
                  calls (useGenerationPipeline), called here UNMODIFIED and without
                  skipConfirm: its own internal priceShot + window.confirm fires for real on
                  this tap, exactly as it would for any other single, owner-initiated real
                  submit in this file. No new endpoint, no new price math, no new confirm
                  dialog belongs to this screen. */}
              <button type="button" className="lm-genbtn" disabled={genBusy || genSubmitting || gp.noInput} onClick={genSubmit}>
                {genBusy ? "already rendering…" : genSubmitting ? "submitting…" : "Generate video"}
              </button>
              {/* useExistingVideo -- the SAME real, already-shipped attach-without-generating
                  path LoomV2's own board already offers (no spend, no PixAI task). */}
              <button type="button" className="lm-genexisting" disabled={genBusy}
                onClick={() => useExistingVideo(dfLive)}>Use an existing video instead</button>
            </>)}
            </div>
            {/* Model/LoRA picker -- a full-screen mobile sheet wrapping the SAME real
                <ModelPicker> element LoomV2's own floating overlay uses. Lazy-mounted on
                first open (pickerMounted), then left mounted for the rest of the session --
                same "CSS-hide instead of unmount" contract as LoomV2's .lv-mpick-veil, so a
                close/reopen never loses either picker's own search/scroll state. */}
            {pickerMounted && (
              <>
                <div className={"lm-scrim" + (pickerClosing ? " closing" : "")}
                  style={{ display: pickerOpen || pickerClosing ? "block" : "none" }} onClick={closePicker} />
                <div className={"lm-pick-sheet" + (pickerClosing ? " closing" : "")}
                  style={{ display: pickerOpen || pickerClosing ? "flex" : "none" }}>
                  <div className="lm-sheethandle" />
                  <div className="lm-pick-head">
                    <span className="lm-pick-t">Models &amp; LoRAs</span>
                    <button type="button" className="lm-df-close" onClick={closePicker} aria-label="Close">&#10005;</button>
                  </div>
                  <div className="lm-tabsrow">
                    <button type="button" className={"lm-tabbtn" + (pickerKind === "base" ? " on" : "")} onClick={() => setPickerKind("base")}>Models</button>
                    <button type="button" className={"lm-tabbtn" + (pickerKind === "lora" ? " on" : "")} onClick={() => setPickerKind("lora")}>LoRAs</button>
                  </div>
                  <div className="lm-pick-body">
                    <ModelPicker kind="base" visible={pickerKind === "base"} value={imgModel} onPick={onBasePick}
                      style={{ display: pickerKind === "base" ? "flex" : "none" }} />
                    <ModelPicker kind="lora" multi baseType={(imgModel && imgModel.model_type) || ""} visible={pickerKind === "lora"} selected={imgLoras} onToggle={onLoraPick}
                      style={{ display: pickerKind === "lora" ? "flex" : "none" }} />
                  </div>
                </div>
              </>
            )}
          </div>
        );
      })()}

      {/* ---- Review & trim -- fifth increment (2026-08-03), per the locked design's own
          reviewFor/cropping/playing state (Loom Mobile.dc.html: search "reviewFor",
          "_trimInMove"/"_trimOutMove"/"_cropDragMove"). Opens from the board's own real ▶
          badge above (canReview) -- a SEPARATE top-level conditional from dfOpen/genOpen,
          matching the design's own layout: Review opens directly off the board, never
          nested inside Shot Detail. reviewLive/reviewPatch/closeReview are declared up with
          this component's other hooks (Rules of Hooks -- nothing stateful may live inside
          this IIFE). See this increment's own report for the full trace of which numbers
          below are copied verbatim from the design's real math (the 0.05 trim min-gap, the
          0.68 crop max, the 0.15 crop-box-half-width offset) and which one deliberate unit
          adaptation was necessary (trimIn/trimOut are stored in ABSOLUTE SECONDS everywhere
          else in this codebase -- ShotPreview, splitCardAt, buildDuplicateCard,
          importedFootagePatch -- never the design's own 0..1 fraction-of-duration model, so
          the fraction math below converts to seconds at the moment it patches the card,
          not before). */}
      {reviewOpen && reviewLive && (() => {
        const c = reviewLive.c;
        // Real native duration once the <video> below reports it (onLoadedMetadata); before
        // that (or if it never fires -- a bad/missing file), fall back to the shot's own
        // planned/actual duration field so the trim track never divides by zero.
        const dur = reviewDur || durOf(c) || 0;
        const trimIn = c.trimIn || 0;
        const trimOut = c.trimOut != null ? c.trimOut : dur;
        const pctOf = (s) => (dur ? Math.max(0, Math.min(100, (s / dur) * 100)) : 0);
        const fmtT = (s) => (s || 0).toFixed(1) + "s";
        const crop = c.crop || { x: 0.35, y: 0.35, w: 0.3, h: 0.3 };   // design's own fallback (reviewC.cropX != null ? ... : 0.35)

        // ---- trim handle drag -- real getBoundingClientRect fraction math off the STATIC
        // track (reviewTrimTrackRef), the same real pattern increment 1's reel scrub and
        // desktop's own already-shipped ShotPreview.secAt() both use. Deliberately NOT
        // sourced off the handle element itself the way the design's own _trimInMove/
        // _trimOutMove read `e.currentTarget.getBoundingClientRect()`: the design binds
        // those pointer handlers to the 18px handle div, which re-centers to the new trim
        // position on every render, so that rect is a moving ~18px-wide target and the drag
        // cannot work as real fraction-of-track math in a real browser -- confirmed by
        // reading the design's own implementation, not assumed. The CLAMP FORMULAS are
        // copied verbatim from the design's real math: outFrac - 0.05 / inFrac + 0.05 (the
        // minimum-gap clamp), expressed here as a fraction of the real clip's native
        // duration before being multiplied back into the seconds this codebase's trimIn/
        // trimOut fields actually store.
        const trimFrac = (e) => {
          const r = reviewTrimTrackRef.current.getBoundingClientRect();
          return r.width ? Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) : 0;
        };
        const trimInStart = (e) => {
          try { e.currentTarget.setPointerCapture(e.pointerId); } catch (err) {}
          reviewTrimDragRef.current = "in"; trimInMove(e);
        };
        const trimInMove = (e) => {
          if (reviewTrimDragRef.current !== "in" || !dur) return;
          const outFrac = trimOut / dur;
          const newFrac = Math.max(0, Math.min(trimFrac(e), outFrac - 0.05));
          const t = newFrac * dur;
          reviewPatch((cc) => ({ ...cc, trimIn: t }));
          const v = reviewVidRef.current; if (v) v.currentTime = t;
          setReviewCur(t);
        };
        const trimInEnd = () => { reviewTrimDragRef.current = null; };
        const trimOutStart = (e) => {
          try { e.currentTarget.setPointerCapture(e.pointerId); } catch (err) {}
          reviewTrimDragRef.current = "out"; trimOutMove(e);
        };
        const trimOutMove = (e) => {
          if (reviewTrimDragRef.current !== "out" || !dur) return;
          const inFrac = trimIn / dur;
          const newFrac = Math.min(1, Math.max(trimFrac(e), inFrac + 0.05));
          const t = newFrac * dur;
          reviewPatch((cc) => ({ ...cc, trimOut: t }));
          const v = reviewVidRef.current; if (v) v.currentTime = t;
          setReviewCur(t);
        };
        const trimOutEnd = () => { reviewTrimDragRef.current = null; };

        // ---- playhead scrub track -- same real fraction-of-width pattern, applied straight
        // to the real <video>'s currentTime (seconds), matching the design's own separate
        // "Scrub" track (playheadDragStart/Move/End), not ShotPreview's different hover-
        // over-the-frame scrub gesture (that one belongs to desktop's own crop-draw UI).
        const scrubFrac = (e) => {
          const r = e.currentTarget.getBoundingClientRect();
          return r.width ? Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) : 0;
        };
        const scrubTo = (e) => {
          if (!dur) return;
          const t = scrubFrac(e) * dur;
          const v = reviewVidRef.current; if (v) v.currentTime = t;
          setReviewCur(t);
        };
        const scrubStart = (e) => {
          try { e.currentTarget.setPointerCapture(e.pointerId); } catch (err) {}
          reviewScrubDragRef.current = true;
          scrubTo(e);
        };
        const scrubMove = (e) => { if (reviewScrubDragRef.current) scrubTo(e); };
        const scrubEnd = () => { reviewScrubDragRef.current = false; };

        // ---- crop rectangle drag -- verbatim port of the design's own _cropFrac/
        // _cropDragMove math: fraction is read off the STATIC preview-wrap container
        // (e.currentTarget.parentElement), never the moving crop-rect div itself, exactly
        // like the design already does (this one has no self-recentering bug the trim
        // handles have, so it needed no mechanical fix -- only the port). A fixed-size
        // (30%x30%) box you drag to reposition, matching the design's own mobile-specific
        // crop UX exactly -- deliberately NOT desktop's ShotPreview.cropStart (which draws
        // an arbitrary new rectangle every time); the two are different, purpose-built UIs
        // for two different form factors, per the locked design.
        const cropFrac = (e) => {
          const r = e.currentTarget.parentElement.getBoundingClientRect();
          const x = e.clientX - r.left, y = e.clientY - r.top;
          return { x: Math.max(0, Math.min(1, x / r.width)), y: Math.max(0, Math.min(1, y / r.height)) };
        };
        const cropDragStart = (e) => {
          try { e.currentTarget.setPointerCapture(e.pointerId); } catch (err) {}
          reviewCropDragRef.current = true;
        };
        const cropDragMove = (e) => {
          if (!reviewCropDragRef.current) return;
          const f = cropFrac(e);
          reviewPatch((cc) => ({ ...cc, crop: {
            x: Math.max(0, Math.min(f.x - 0.15, 0.68)),
            y: Math.max(0, Math.min(f.y - 0.15, 0.68)),
            w: 0.3, h: 0.3,
          } }));
        };
        const cropDragEnd = () => { reviewCropDragRef.current = false; };

        // ---- playback -- a real <video>, real play()/pause()/timeupdate. Loops within the
        // kept [trimIn, trimOut) range while playing, matching the design's own _togglePlay
        // intent (its setInterval wraps back to inF on reaching outF and keeps going) --
        // unlike desktop's ShotPreview, which pauses at the trim-out point instead. Driven
        // by real playback events here, not a synthetic timer, because there is a real
        // video to play.
        const togglePlay = () => {
          const v = reviewVidRef.current; if (!v) return;
          if (reviewPlaying) { v.pause(); setReviewPlaying(false); return; }
          if (v.currentTime < trimIn || v.currentTime >= trimOut) v.currentTime = trimIn;
          v.play().catch(() => {});
          setReviewPlaying(true);
        };
        const onReviewTimeUpdate = (e) => {
          const cur = e.currentTarget.currentTime;
          setReviewCur(cur);
          if (reviewPlaying && trimOut > trimIn && cur >= trimOut - 0.02) {
            e.currentTarget.currentTime = trimIn;
          }
        };
        // Nudge back/forward -- the SAME real, already-shipped ±0.25s step ShotPreview's own
        // seek() uses ("framing a split or crop"), not the design's synthetic 0.04-of-total-
        // duration nudge (which only made sense against its own fake, interval-driven
        // reviewFrac). Disclosed adaptation: same purpose, reusing this codebase's real,
        // working number instead of inventing a new proportional one.
        const nudge = (delta) => {
          const v = reviewVidRef.current; if (!v || !dur) return;
          if (reviewPlaying) { v.pause(); setReviewPlaying(false); }
          const t = Math.max(0, Math.min(dur, v.currentTime + delta));
          v.currentTime = t; setReviewCur(t);
        };

        // ---- split -- the REAL splitCardAt-backed mutator (splitShot, threaded in as a
        // prop, exactly matching desktop's <ShotPreview onSplit={(t) => splitShot(sel, t)}>
        // call). Same 0.15s edge guard and the SAME message text as ShotPreview's own
        // doSplit, reused verbatim rather than inventing new copy. Matches the design's own
        // _doSplit, which also closes Review on a successful split (`reviewFor: null`).
        const doSplit = () => {
          const v = reviewVidRef.current; if (!v) return;
          const t = v.currentTime;
          if (t > trimIn + 0.15 && t < trimOut - 0.15) { splitShot(reviewLive, t); closeReview(); }
          else alert("Move the playhead to where you want the cut first (not at either edge).");
        };

        return (
          <div className="lm-review">
            <div className="lm-gen-top">
              <button type="button" className="lm-gen-back" onClick={closeReview}>&lsaquo; {reviewLive.code}</button>
              <span className="lm-gen-title">Review &amp; trim</span>
              <span className="lm-fill" />
              <button type="button" className="lm-df-close" title="Close" onClick={closeReview}>&#10005;</button>
            </div>
            <div className="lm-df-body">
              <div className="lm-review-previewwrap">
                <video key={c.id} ref={reviewVidRef} className="lm-review-video"
                  src={"/video-file/" + c.resultMid} playsInline preload="metadata"
                  onLoadedMetadata={(ev) => setReviewDur(ev.currentTarget.duration || 0)}
                  onTimeUpdate={onReviewTimeUpdate}
                  onEnded={() => setReviewPlaying(false)} />
                {reviewCropping && (
                  <div className="lm-review-croprect"
                    style={{ left: crop.x * 100 + "%", top: crop.y * 100 + "%", width: crop.w * 100 + "%", height: crop.h * 100 + "%" }}
                    onPointerDown={cropDragStart} onPointerMove={cropDragMove} onPointerUp={cropDragEnd}>
                    <div className="lm-review-crophandle" />
                  </div>
                )}
                <button type="button" className="lm-review-playbtn" onClick={togglePlay}>
                  {reviewPlaying ? "⏸" : "▶"}
                </button>
              </div>

              <div className="lm-review-transport">
                <button type="button" className="lm-review-transportbtn" onClick={() => nudge(-0.25)}>⏪</button>
                <button type="button" className="lm-review-transportbtn" onClick={togglePlay}>{reviewPlaying ? "⏸" : "▶"}</button>
                <button type="button" className="lm-review-transportbtn" onClick={() => nudge(0.25)}>⏩</button>
              </div>

              <span className="lm-microlab">Scrub</span>
              <div className="lm-review-scrubtrack"
                onPointerDown={scrubStart} onPointerMove={scrubMove} onPointerUp={scrubEnd}>
                <div className="lm-review-scrubfill" style={{ width: pctOf(reviewCur) + "%" }} />
                <div className="lm-review-scrubhandle" style={{ left: pctOf(reviewCur) + "%" }} />
              </div>

              <span className="lm-microlab">Trim <span className="lm-hint" style={{ display: "inline", padding: 0 }}>drag the in/out handles</span></span>
              <div className="lm-review-trimtrack" ref={reviewTrimTrackRef}>
                <div className="lm-review-trimrange" style={{ left: pctOf(trimIn) + "%", right: (100 - pctOf(trimOut)) + "%" }} />
                <div className="lm-review-trimhandle" style={{ left: pctOf(trimIn) + "%" }}
                  onPointerDown={trimInStart} onPointerMove={trimInMove} onPointerUp={trimInEnd} />
                <div className="lm-review-trimhandle" style={{ left: pctOf(trimOut) + "%" }}
                  onPointerDown={trimOutStart} onPointerMove={trimOutMove} onPointerUp={trimOutEnd} />
              </div>
              <div className="lm-review-trimreadout">{fmtT(trimIn)} &rarr; {fmtT(trimOut)}</div>

              <div className="lm-review-actionsrow">
                <button type="button" className="lm-addrefbtn" style={{ whiteSpace: "nowrap" }} onClick={doSplit}>&#9986; Split at playhead</button>
                <button type="button" className={"lm-review-cropbtn" + (reviewCropping ? " on" : "")}
                  onClick={() => setReviewCropping((v) => !v)}>&#9974; {reviewCropping ? "Done" : "Crop"}</button>
              </div>
            </div>
          </div>
        );
      })()}

      {/* ---- Filter compare -- sixth and FINAL increment (2026-08-03), the locked design's
          own "Art filters" screen (Loom Mobile.dc.html: search "filterCompareOpen",
          "fcSkinFilters", "fcPixaiFilters", "fcStrength", "fcAngle", "fcClear",
          "fcSaveLibrary", "FILTER_SETS"). Opens from Generate's Edit tab -> Enhance sub-tab
          (openFilterCompare, declared with this component's other hooks above). Reuses
          dfLive directly rather than a second entries.find() lookup -- see openFilterCompare's
          own comment for why that's safe here specifically (unlike reviewOpen). */}
      {fcOpen && dfLive && (() => {
        const c = dfLive.c;
        const fcSrc = frameSrc(c.openFrame);
        const fcGroups = AF ? AF.groups() : [];
        const activeRec = fcActive && AF ? (AF.get(fcActive) || {}) : null;
        const activeName = activeRec ? (activeRec.name || fcActive) : null;
        return (
          <div className="lm-fc" key={c.id}>
            <div className="lm-gen-top">
              <button type="button" className="lm-gen-back" onClick={closeFilterCompare}>&lsaquo; {dfLive.code}</button>
              <span className="lm-gen-title">Art filters</span>
              <span className="lm-fill" />
              <button type="button" className="lm-df-close" title="Close" onClick={closeFilterCompare}>&#10005;</button>
            </div>
            <div className="lm-df-body">
              {!AF ? (
                <div className="lm-empty">The art-filter library did not load on this page.</div>
              ) : (
                <>
                  {/* Original vs. Preview -- a REAL image (this shot's real open frame) both
                      times, never a fake color swatch. The right box is a live AF.applyPreview
                      compositing (CSS gradient overlay divs + mix-blend-mode, per
                      mg-art-filters.js's own documented approach) driven by the effect
                      declared with this component's other hooks -- nothing here paints the
                      overlay itself. */}
                  <div className="lm-fc-previewrow">
                    <div className="lm-fc-previewcol">
                      <div className="lm-fc-previewbox">
                        {fcSrc ? <img className="lm-fc-img" src={fcSrc} alt="original" />
                          : <div className="lm-empty">No open-frame image yet</div>}
                      </div>
                      <div className="lm-fc-previewcap">Original</div>
                    </div>
                    <div className="lm-fc-previewcol">
                      <div className="lm-fc-previewbox">
                        <div className="lm-fc-stage" ref={fcStageRef}>
                          {fcSrc ? <img ref={fcImgRef} className="lm-fc-img" src={fcSrc} alt="preview" />
                            : <div className="lm-empty">No open-frame image yet</div>}
                        </div>
                      </div>
                      <div className="lm-fc-previewcap">Preview &middot; <b>{activeName || "no filter"}</b></div>
                    </div>
                  </div>

                  {/* Swatch grids -- AF.groups() IS the real "Moonglade" (5, ours) / "PixAI"
                      (7, verbatim) split; nothing here hardcodes a count or a group label.
                      Each tile paints via the real AF.renderSwatch (the same gradient/blend
                      math the tile's own filter would apply as a preview), not a
                      hand-rolled two-color CSS gradient. */}
                  {fcGroups.map((g) => (
                    <div key={g.source}>
                      <div className="lm-fc-grouplabel">{g.label}</div>
                      <div className="lm-fc-grid">
                        {g.ids.map((id) => {
                          const rec = AF.get(id) || {};
                          return (
                            <button type="button" key={id} className={"lm-fc-tile" + (fcActive === id ? " on" : "")}
                              onClick={() => setFcActive((cur) => (cur === id ? null : id))}
                              title={(rec.name || id) + " · free, applied in your browser" + (rec.note ? " — " + rec.note : "")}>
                              <div className="lm-fc-swatch"
                                ref={(el) => { if (el && !el._mgafPainted) { AF.renderSwatch(el, id); el._mgafPainted = true; } }} />
                              <div className="lm-fc-name">{(rec.name || id).replace("Filter ", "")}</div>
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}

                  <div className="lm-fc-sliderwrap">
                    <div className="lm-fc-sliderlab">Strength — {Number(fcStrength).toFixed(2)}</div>
                    <input type="range" min="0" max="1" step="0.05" className="lm-fc-range"
                      value={fcStrength} onChange={(ev) => setFcStrength(parseFloat(ev.target.value))} />
                  </div>
                  <div className="lm-fc-sliderwrap">
                    <div className="lm-fc-sliderlab">Angle — {fcAngle}&deg;</div>
                    <input type="range" min="0" max="360" step="1" className="lm-fc-range"
                      value={fcAngle} onChange={(ev) => setFcAngle(parseInt(ev.target.value, 10))} />
                  </div>
                  <div className="lm-fc-btnrow">
                    <button type="button" className="lm-fc-btn" onClick={fcClear}>No filter</button>
                    <button type="button" className="lm-fc-btn primary" onClick={fcSave}>Save</button>
                  </div>
                  <div className="lm-fc-spendnote">{activeName || "No filter"} &middot; nothing sent, nothing spent</div>
                </>
              )}
            </div>
          </div>
        );
      })()}
    </div>
  );
}

/* =========================================================================
   COMPOSED HOOKS (Phase 2, 2026-07-16) -- App()'s former ~450-line body,
   decomposed by RESPONSIBILITY into four focused hooks instead of one
   monolithic one, each thin-wrapping the pure reducers/classifiers imported
   from ./src/loom-mutations.js above. App() composes them back together;
   every prop name a child component (LoomV2 and its subtree) already expects
   is preserved unchanged below.

     useProjectStore        -- multi-project CRUD + window.storage persistence
     useShotMutations        -- act/card/ref CRUD on the open project
     useGenerationPipeline    -- generate/poll/route across image/edit/reference/video
     useExportPipeline        -- shot-list/backup export, play-sequence, ffmpeg cut

   See the worktree report for exactly where this did and didn't separate
   cleanly (setCardStatus straddling shot-mutations/generation; the
   recursive-setTimeout poll loops not being meaningfully "pure").
   ========================================================================= */

// ---- 1. useProjectStore: multi-project CRUD + persistence ----
function useProjectStore(setSelShot) {
  const [project, setProject] = useState(null);
  const [thumbs, setThumbs] = useState({});
  const [busy, setBusy] = useState(false);
  const [activeId, setActiveId] = useState(null);   // id of the open storyboard (multi-project store)
  const [projList, setProjList] = useState([]);     // [{id,name,shots}] for the switcher
  const [projMenu, setProjMenu] = useState(false);  // switcher dropdown open?
  const saveTimer = useRef(null);
  const castImported = useRef(false);

  // ---- Multi-project store: each storyboard lives at PPRE+id; ACTIVE_KEY names the open one.
  //      The legacy single project (PKEY) is migrated in as the first storyboard on first load. ----
  const readProjList = useCallback(async () => {
    if (!hasStore) return [];
    const keys = await sList(PPRE); const out = [];
    for (const k of keys) {
      try { const raw = await sGet(k); if (!raw) continue; const pr = JSON.parse(raw);
        out.push({ id: k.slice(PPRE.length), name: pr.name || "Untitled", shots: countShots(pr) });
      } catch {}
    }
    out.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    setProjList(out); return out;
  }, []);
  const flushSave = useCallback(async (id, p) => { if (hasStore && id && p) await sSet(PPRE + id, JSON.stringify(p)); }, []);

  useEffect(() => {
    (async () => {
      if (!hasStore) { setProject(seedProject()); return; }
      let keys = await sList(PPRE);
      if (!keys.length) {                                  // one-time migration of the legacy single project
        const legacy = await sGet(PKEY);
        const id = uid();
        await sSet(PPRE + id, legacy || JSON.stringify(seedProject()));
        await sSet(ACTIVE_KEY, id);
        keys = [PPRE + id];
      }
      let aid = await sGet(ACTIVE_KEY);
      if (!aid || !keys.includes(PPRE + aid)) aid = keys[0].slice(PPRE.length);
      let p = null; try { const raw = await sGet(PPRE + aid); if (raw) p = JSON.parse(raw); } catch {}
      if (!p) { p = seedProject(); await sSet(PPRE + aid, JSON.stringify(p)); }
      setActiveId(aid); setProject(p);
      const tkeys = await sList(TPRE); const map = {};
      for (const k of tkeys) { const v = await sGet(k); if (v) map[k.slice(TPRE.length)] = v; }
      setThumbs(map);
      readProjList();
    })();
  }, []);

  const openProject = useCallback(async (id) => {
    if (!id || id === activeId) { setProjMenu(false); return; }
    await flushSave(activeId, project);
    let p = null; try { const raw = await sGet(PPRE + id); if (raw) p = JSON.parse(raw); } catch {}
    if (!p) return;
    await sSet(ACTIVE_KEY, id);
    setActiveId(id); setProject(p); setSelShot(null); setProjMenu(false);
  }, [activeId, project, flushSave, setSelShot]);
  const newProject = useCallback(async () => {
    await flushSave(activeId, project);
    const id = uid(); const p = seedProject(); p.name = "New storyboard";
    await sSet(PPRE + id, JSON.stringify(p)); await sSet(ACTIVE_KEY, id);
    setActiveId(id); setProject(p); setSelShot(null); setProjMenu(false); readProjList();
  }, [activeId, project, flushSave, readProjList, setSelShot]);
  const duplicateProject = useCallback(async () => {
    await flushSave(activeId, project);
    const id = uid(); const p = { ...project, name: (project.name || "Untitled") + " copy" };
    await sSet(PPRE + id, JSON.stringify(p)); await sSet(ACTIVE_KEY, id);
    setActiveId(id); setProject(p); setProjMenu(false); readProjList();
  }, [activeId, project, flushSave, readProjList]);
  const deleteProject = useCallback(async (id) => {
    const list = await readProjList();
    if (list.length <= 1) { window.alert("This is your only storyboard — make another before deleting this one."); return; }
    const tgt = list.find((x) => x.id === id);
    if (!window.confirm(`Delete "${(tgt && tgt.name) || "this storyboard"}"? This can't be undone.`)) return;
    if (id === activeId) {
      // Switch to a survivor WITHOUT flushing the doomed project first — openProject()'s
      // flushSave(activeId) would re-create the very project we're deleting.
      // Walk the survivors rather than trusting the first one. readProjList() parsed every
      // entry on this list moments ago, so a null here is a transient read and the next
      // candidate is almost certainly fine — refusing the whole delete because ONE key
      // blipped would be its own bug.
      // Giving up only when none of them read, and giving up WITHOUT deleting, is the
      // point: sGet() swallows its own errors and returns null, so a failed read and an
      // empty one look identical from here. Opening a seedProject() on that null (what
      // this did before) hands the 600ms autosave a blank board to write over a survivor's
      // own key — one dropped read costing TWO storyboards, the second of which nobody
      // asked to delete.
      let next = null, p = null, anyReadFailed = false;
      for (const cand of list) {
        if (cand.id === id) continue;
        try {
          const got = await sGetX(PPRE + cand.id);      // .failed distinguishes a broken read
          if (got.failed) { anyReadFailed = true; continue; }
          if (got.value) { p = JSON.parse(got.value); next = cand; break; }
        } catch { anyReadFailed = true; }               // stored, but not parseable
      }
      if (!p) {
        window.alert(anyReadFailed
          ? "Couldn't read your other storyboards, so nothing was deleted. Check the server and try again."
          : "Couldn't open another storyboard, so nothing was deleted. Try again.");
        return;
      }
      // A pending 600ms autosave timer for THIS project can otherwise fire during the
      // awaits below (sDel/sSet both hit the network) and re-create the very key
      // sDel just removed, silently resurrecting a "permanently deleted" board. The
      // timer belongs to whichever board is OPEN, so it is only ever cancelled when
      // the open board is the one being deleted — cancelling it while deleting some
      // other board would silently discard unsaved edits to the board still on screen.
      clearTimeout(saveTimer.current);
      await sDel(PPRE + id);
      await sSet(ACTIVE_KEY, next.id);
      setActiveId(next.id); setProject(p); setSelShot(null);
    } else {
      await sDel(PPRE + id);
    }
    await readProjList();
    setProjMenu(false);
  }, [activeId, readProjList, setSelShot]);
  const projectApi = { activeId, projList, projMenu, setProjMenu, readProjList, openProject, newProject, duplicateProject, deleteProject };

  // Gallery -> cast: /loom?cast=id1,id2 (from the gallery's "Send to Loom cast" bulk
  // action) adds those images as reusable @image cast members, once, then clears the URL.
  useEffect(() => {
    if (!project || castImported.current) return;
    castImported.current = true;
    // Two filters, deliberately: parseCastIdsFromSearch is the URL *sanitiser* (safe
    // characters only, so nothing can escape a path or a query), and isCatalogMediaId is
    // the *grammar* -- applied here, at the one call site that has both modules in scope,
    // so neither file has to carry a second copy of the other's rule. Junk in the URL is
    // dropped rather than becoming a cast member with no picture.
    const ids = parseCastIdsFromSearch(location.search).filter(isCatalogMediaId);
    if (!ids.length) return;
    setProject((p) => {
      const existing = p.assets || [];
      let n = maxTagNum(existing, "@image");
      const added = ids.map((mid) => ({ id: uid(), name: "", kind: "image",
        tag: "@image" + (++n), thumbId: "", source: "", mediaId: mid, lock: true }));
      return { ...p, assets: [...existing, ...added] };
    });
    history.replaceState(null, "", location.pathname);
  }, [project]);

  useEffect(() => {
    if (!project || !hasStore || !activeId) return;
    setBusy(true); clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => { await sSet(PPRE + activeId, JSON.stringify(project)); setBusy(false); }, 600);
    return () => clearTimeout(saveTimer.current);
  }, [project, activeId]);

  const storeThumb = useCallback(async (file) => {
    const data = await fileToThumb(file); const id = uid();
    setThumbs((t) => ({ ...t, [id]: data })); if (hasStore) await sSet(TPRE + id, data); return id;
  }, []);

  // A restored backup is always a NEW storyboard, never an in-place overwrite of
  // whatever's currently open -- this used to clobber the active project silently
  // (no new id, no confirm), a real data-loss footgun if you imported a backup
  // while a different board was open. Shared by both export tiers: a lightweight
  // {project, thumbs} parsed client-side, or the same shape handed back by the
  // server after a full-bundle zip's media has been reconciled into the catalog.
  const _adoptBackup = async (d) => {
    if (!d || !d.project) { window.alert("That file didn't parse as a storyboard backup."); return; }
    if (!window.confirm(`Import "${d.project.name || "this backup"}" as a NEW storyboard?\n\nYour currently-open board is left untouched.`)) return;
    await flushSave(activeId, project);
    const id = uid();
    await sSet(PPRE + id, JSON.stringify(d.project));
    await sSet(ACTIVE_KEY, id);
    if (d.thumbs) { setThumbs((t) => ({ ...t, ...d.thumbs })); if (hasStore) for (const [k, v] of Object.entries(d.thumbs)) await sSet(TPRE + k, v); }
    setActiveId(id); setProject(d.project); setSelShot(null); readProjList();
  };
  const importJSON = async (file) => { if (!file) return;
    try { await _adoptBackup(JSON.parse(await file.text())); }
    catch { window.alert("That file didn't parse as a storyboard backup."); } };
  // Full-bundle import: the zip's media is reconciled into THIS machine's catalog
  // server-side (existing media_ids are skipped -- both sides already have them),
  // then the response is the exact same {project, thumbs} shape as the lightweight
  // tier, so it shares _adoptBackup's create-new-project path unchanged.
  const importBundle = async (file) => { if (!file) return;
    try {
      const fd = new FormData(); fd.append("file", file);
      const r = await fetch("/api/loom/import-bundle", { method: "POST", body: fd });
      const d = await r.json();
      if (d.error) { window.alert("Couldn't import that bundle: " + d.error); return; }
      await _adoptBackup(d);
    } catch { window.alert("Couldn't import that bundle -- network error."); } };
  // Public entry point: sniff which tier a restored file actually is. Zips are only
  // ever full bundles; anything else is tried as the lightweight JSON.
  const importBackup = (file) => { if (!file) return;
    const isZip = /\.zip$/i.test(file.name) || file.type === "application/zip";
    return isZip ? importBundle(file) : importJSON(file); };

  return { project, setProject, thumbs, storeThumb, busy,
    projList, projMenu, setProjMenu, projectApi, importJSON, importBackup, activeId };
}

// ---- 2. useShotMutations: act/card/ref CRUD on the open project ----
function useShotMutations(project, setProject) {
  const [open, setOpen] = useState({});

  const setCard = useCallback((aId, cId, fn) => setProject((p) => patchCard(p, aId, cId, fn)), [setProject]);
  const setAct = useCallback((aId, patch) => setProject((p) => patchAct(p, aId, patch)), [setProject]);
  const setAssets = useCallback((fn) => setProject((p) => patchAssets(p, fn)), [setProject]);
  // setCardStatus finds a card by id ALONE (searches every act) -- distinct from setCard,
  // which needs the act id. generateShot/pollShot/useExistingVideo don't know (or care)
  // which act a shot lives in, so this stays a sibling of setCard rather than folding in.
  const setCardStatus = (cardId, patch) => setProject((p) => patchCardById(p, cardId, patch));

  const addCard = (aId) => { const c = newCard();
    setProject((p) => appendCardToAct(p, aId, c));
    setOpen((o) => ({ ...o, [c.id]: true })); };
  // Land an already-rendered gallery video as a REAL shot entry -- Finished Shots +
  // the existing per-card "move to..." dropdown -- instead of a Cast & Assets
  // reference. See the Footage tab's "Browse library" button (LoomV2) for the only
  // caller. Returns the new card's id so the caller can select it.
  const importFootage = (mediaId, duration) => {
    const c = newCard(importedFootagePatch(mediaId, duration));
    setProject((p) => landInFirstAct(p, c, uid()));
    // The card lands FIRST and the two stills fill in a beat later, on purpose. Landing the
    // footage is the Footage tab's whole action and has to stay instant; ffmpeg plus two
    // uploads take a second or two. The card is complete and placeable throughout -- the
    // frames are the only thing outstanding -- so nothing waits on this and a failure just
    // leaves the slots as they already were.
    fetch("/api/loom/import-frames", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_media_id: mediaId }) })
      .then((r) => r.json()).then((d) => {
        if (!d || d.error) return;
        const patch = importedFramesPatch(d.first_media_id, d.last_media_id);
        if (Object.keys(patch).length) setCardStatus(c.id, patch);
      }).catch(() => {});
    return c.id;
  };
  const dupCard = (aId, card) => {
    const clone = buildDuplicateCard(card, uid(), card.refs.map(() => uid()));
    setProject((p) => insertCardAfter(p, aId, card.id, clone));
  };
  const delCard = (aId, card) => setProject((p) => removeCard(p, aId, card.id));
  const moveCard = (aId, idx, dir) => setProject((p) => moveCardInAct(p, aId, idx, dir));
  const moveCardToAct = (fromId, card, toId) => setProject((p) => mvCardToAct(p, fromId, card, toId));
  const addAct = () => setProject((p) => appendAct(p, { id: uid(), name: nextActName(p), collapsed: false, cards: [] }));
  const delAct = (aId) => { const a = project.acts.find((x) => x.id === aId);
    if (a.cards.length && !window.confirm(`Delete "${a.name}" and its ${a.cards.length} card(s)?`)) return;
    setProject((p) => removeAct(p, aId)); };
  const moveAct = (idx, dir) => setProject((p) => moveActInProject(p, idx, dir));

  const addRef = (aId, card, kind) => {
    const pre = kind === "image" ? "@image" : kind === "video" ? "@video" : "@audio";
    const tag = nextTag(card.refs.filter((r) => r.kind === kind), pre);
    setCard(aId, card.id, (c) => ({ ...c, refs: [...c.refs, { ...buildNewRef(kind, uid()), tag }] })); };
  const setRef = (aId, cId, rId, patch) => setProject((p) => patchRef(p, aId, cId, rId, patch));
  const delRef = (aId, cId, ref) => setProject((p) => removeRef(p, aId, cId, ref.id));
  const splitShot = (entry, t) => setProject((p) => splitCardAt(p, entry.a.id, entry.c.id, t, uid()));

  return { open, setOpen, setCard, setAct, setAssets, setCardStatus,
    addCard, importFootage, dupCard, delCard, moveCard, moveCardToAct, addAct, delAct, moveAct,
    addRef, setRef, delRef, splitShot };
}

// ---- 3. useGenerationPipeline: generate/poll/route across all four modes ----
// mobileUI (mobile-generate-rail pass, 2026-08-03): NOT used for its value, only as a second
// dependency on the resume effect below -- see that effect's own comment for why the
// Mobile-view toggle needs to trigger the identical resume it already runs on project load.
function useGenerationPipeline({ project, thumbs, setCard, setCardStatus, setAssets, openPick, activeId, mobileUI }) {
  const [genState, setGenState] = useState({});         // cardId -> {phase, msg, mid} (video)
  const resumedRef = useRef({});    // taskId -> true: shots whose interrupted poll we've re-attached this session
  const [genImgState, setGenImgState] = useState({});   // shotId -> {phase,msg,mid,routed} (in-Loom image ref-gen)
  const [imgModel, setImgModel] = useState(null);        // {model_id,title} for reference-image gen
  const [imgLoras, setImgLoras] = useState([]);           // D-11: [{model_id,title,version_id,weight,lora_base_type,trigger_words,failed}]
  // L536: the Image tab's Advanced/aspect/size/mode/count/seed/checkbox state -- full PixAI
  // field parity with moonglade_gallery.py's own Generate tab (owner-decided scope, 2026-07-23:
  // "full PixAI parity, not a curated subset, for BOTH the Gallery and the Loom"). Lives
  // alongside imgModel/imgLoras (drawer-wide, not per-shot) for the same reason those do --
  // one Image-tab "form" shared across whichever shot is active, matching the Gallery's own
  // single Generate drawer. Defaults mirror the Gallery's HTML exactly (gen-size selected=
  // 1024, gen-steps value=25, gen-cfg value=7, gen-ph checked, 1:1 aspect .on by default).
  const [imgAdv, setImgAdv] = useState(() => ({
    negative: "", steps: 25, cfg: 7,
    aspectW: 1, aspectH: 1, size: 1024, customW: "", customH: "",
    mode: "auto", count: 1, seed: "", highPriority: false, promptHelper: true,
  }));
  // The model author's own tuned preset (negative/steps/cfg), fetched via /api/model-version
  // when a BASE model resolves -- mirrors moonglade_gallery.py's Gen.applyModelDefaults() (D-11
  // audit note: "resolve_version_meta already fetches these; the drawer just never used
  // them" -- true of the Gallery's OWN drawer at the time; the Loom never fetched
  // /api/model-version for its base model at all, so it never even had the data). Only
  // fields the model actually has data for are prefilled; a model with no tuned preset
  // leaves imgAdv's current negative/steps/cfg alone. modelDefaults holds what was offered
  // (for the "using this model's tuned preset" note); null when the current model has none.
  const [modelDefaults, setModelDefaults] = useState(null);
  const [genEditState, setGenEditState] = useState({});  // shotId -> {phase,msg,mid,routed} (in-Loom instruct-edit)
  const [genRefState, setGenRefState] = useState({});    // shotId -> {...} (multi-reference gen)
  const [genFixState, setGenFixState] = useState({});     // shotId -> {...} (in-Loom face/hand fix -- seventh increment, 2026-08-03)
  const [batching, setBatching] = useState(false);
  // batchTally: { total, submitted, ids: Set, outcomes: {[cardId]: "done"|"failed"|"stale"} }
  // for the CURRENTLY OPEN batch run, or null between runs. Distinct from tallyPrices()'s
  // free/paid/credits/unknown -- this tracks submit/render OUTCOMES, not cost. `submitted`
  // is a flat counter (incremented once per card, at launch, by batchGenerate's own loop --
  // immune to double-counting since that loop visits each card exactly once). Every other
  // outcome lives in `outcomes`, a MAP keyed by card id, not separate done/failed/stale
  // counters -- a card's outcome can be REASSIGNED later (e.g. the give-up-timer's "stale"
  // pause() eventually resolves into "done" via a manual recheck) by simply overwriting its
  // one entry, which is naturally self-correcting. Flat increment-only counters for
  // done/failed/stale were tried first and rejected in review: they double-count the instant
  // any shot's outcome changes after first being recorded (a `stale` shot that later resolves
  // `done` left `done+1` while `stale` stayed put, so the tally could sum to MORE than
  // `total`). Displayed counts are always DERIVED from this map (see the batch banner below),
  // never stored redundantly. Every mutation below uses the functional setState form and
  // checks membership against the CURRENT `prev` value inside the updater, never a
  // `batchTally` variable closed over by generateShot/pollShot -- those closures are captured
  // once (at the render active when the batch's button was clicked) and never see later
  // updates, exactly the same stale-closure trap generateShot's own return-value fix above
  // exists to avoid.
  const [batchTally, setBatchTally] = useState(null);
  const setBatchOutcome = (cardId, outcome) => setBatchTally((prev) =>
    (prev && prev.ids.has(cardId)) ? { ...prev, outcomes: { ...prev.outcomes, [cardId]: outcome } } : prev);

  const imgSrc = (thumbId, source) => thumbId ? thumbs[thumbId]
    : (source && (source.startsWith("http") || source.startsWith("data:") || isCatalogMediaId(source)) ? source : null);
  /* Build the /api/loom/generate + /api/price payload for a shot (single source).
     Wraps the pure, imported buildShotPayload with this hook's own `project` state
     + `imgSrc` (closes over `thumbs`), preserving the original single-argument
     call shape used below and in priceShot/generateShot. */
  const shotPayload = (entry) => buildShotPayload(entry, project, imgSrc);
  /* READ-ONLY cost + free-card check for a shot (reuses the drawer's /api/price; spends nothing). */
  const priceShot = async (entry) => {
    try {
      const r = await fetch("/api/price", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(shotPayload(entry)) });
      return await r.json();   // {cost, free, cards, note}
    } catch { return null; }
  };
  // Fail-closed cost gate for the Image / Edit / Reference tabs -- the SAME guardrail
  // generateShot (video) already runs, factored out so those three stop lying. They used
  // to show a flat "a free card auto-applies; otherwise it spends credits" confirm that
  // never actually checked: a shot with no covering card spent silently past an OK click.
  // `priceBody` is the exact shape the matching submit endpoint receives, so /api/price
  // prices precisely what will run. Fails CLOSED -- a null/failed price check still ASKS
  // before spending, never waves it through. Returns true to proceed.
  const confirmSpend = async (priceBody, label) => {
    let pr = null;
    try {
      const r = await fetch("/api/price", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(priceBody) });
      pr = await r.json();
    } catch { pr = null; }
    if (pr && pr.free) return true;                                    // a free card covers it: no spend, no prompt
    if (pr && !pr.free && pr.cost != null) {
      return window.confirm(`${label}\n\nNo free card covers it — it will spend ~${pr.cost.toLocaleString()} credits.\n\nGenerate anyway?`);
    }
    return window.confirm(`${label}\n\nCouldn't verify the cost or free-card coverage — it may spend credits.\n\nGenerate anyway?`);
  };
  // Returns an explicit outcome ({ok:true,taskId} | {ok:false,reason}) instead of only
  // writing state -- batchGenerate's own submit-time tally needs a value it can read
  // immediately after await, not genState (a React state variable batchGenerate's closure
  // captured once at render time; setGenState calls here only SCHEDULE an update, they
  // never retroactively change what that already-captured closure sees -- confirmed the
  // hard way tonight: two independent adversarial reviews both caught a first-draft tally
  // design that read genState right after this call and found it silently always stale).
  const generateShot = async (entry, opts = {}) => {
    const c = entry.c;
    const p = shotPayload(entry);
    if (!p.hasInput) {
      // Investigated, not assumed, what "re-roll on imported footage" actually does (an
      // imported clip -- c.imported, see importedFootagePatch -- has no cast/frames/refs,
      // so hasInput is false by construction): this branch is NOT the thing that protects
      // it in practice. generateShot has exactly one caller, batchGenerate, whose own
      // `todo` filter already excludes status:"done" -- importedFootagePatch always sets
      // that -- so an imported card never reaches here via "Generate all" either. The real
      // per-shot "Generate video" click lives entirely in <mg-generate-drawer>'s own
      // _generate() (static/mg-generate-drawer.js), a SEPARATE, pre-existing guard
      // (_hasAnyRef) with its own message ("Pick a source image first."/"Pick at least one
      // reference first.") -- live-verified: clicking it on an imported shot fires no
      // fetch, spends nothing, and leaves the footage untouched. This message stays as a
      // defensive fallback in case a future refactor ever re-routes per-shot generation
      // through generateShot the way it once did (see the LoomV2-dead-generateShot-prop
      // history) -- but do not mistake it for the operative guard today.
      const msg = c.imported
        ? "Imported footage — nothing to re-roll. Attach a frame/cast image to render a NEW clip here, or swap the video via \"Use an existing video instead\"."
        : "attach a frame or cast image first";
      setGenState((s) => ({ ...s, [c.id]: { phase: "error", msg } }));
      return { ok: false, reason: "no-input" };
    }
    // GUARDRAIL: never spend credits silently. Check cost + free-card, confirm any credit spend.
    // Must fail CLOSED: priceShot swallows its own errors and returns null, and the server's
    // own /api/price returns HTTP 200 with cost:null on any exception -- either one used to
    // slip straight through the confirm below (every condition short-circuited on cost==null),
    // submitting a paid generation with zero confirmation. A verify failure now still asks.
    if (!opts.skipConfirm) {
      const pr = await priceShot(entry);
      if (pr && !pr.free && pr.cost != null) {
        if (!window.confirm(`No free card covers this shot — it will spend ~${pr.cost.toLocaleString()} credits.\n\nGenerate anyway?`)) return { ok: false, reason: "cancelled" };
      } else if (!pr || !pr.free) {
        if (!window.confirm("Couldn't verify this shot's cost or free-card coverage — it may spend credits.\n\nGenerate anyway?")) return { ok: false, reason: "cancelled" };
      }
    }
    setGenState((s) => ({ ...s, [c.id]: { phase: "submitting", msg: "Submitting…" } }));
    setCardStatus(c.id, { status: "wip" });
    try {
      const r = await fetch("/api/loom/generate", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: p.mode, prompt: p.prompt, images: p.images,
          video_refs: p.video_refs, duration: p.duration, quality: p.quality,
          generate_audio: p.generate_audio, audio_language: p.audio_language, origin: "loom-shot" }) });
      const d = await r.json();
      if (d.error || !d.task_id) {
        setGenState((s) => ({ ...s, [c.id]: { phase: "error", msg: (d.error ? friendlyGenErr(d.error) : "submit failed") } }));
        // Roll the optimistic status:"wip" written above back to a real terminal "error" --
        // the same write pollShot makes when the SERVER reports a failed render, so a
        // rejection at SUBMIT time (content policy, no credits) lands in the same visible
        // state as one that fails mid-render. Without it the card kept status:"wip" forever:
        // indistinguishable from a live generation, and permanently skipped by
        // batchGenerate's own todo filter (which excludes "wip" as well as "done"), so every
        // later "Generate all" silently passed over the shot and the failure never surfaced.
        setCardStatus(c.id, { status: "error", pendingTaskId: null, genStartedAt: null });
        return { ok: false, reason: "submit-failed" };
      }
      // Persist the task id on the card so a mid-render tab close is recoverable: the
      // in-memory pollShot loop dies with the page, but a resume effect re-attaches it
      // from pendingTaskId on next load (otherwise the shot is stuck "wip" forever while
      // its clip lands orphaned in the gallery). Cleared on done/fail.
      // genStartedAt is ALSO persisted (not just held in pollShot's own closure) so the
      // give-up-timer's tiers survive a reload -- without a durable timestamp, a resumed
      // poll would compute elapsed from a fresh Date.now() every time, silently re-arming a
      // full 6h ceiling on every reload regardless of true elapsed time (found in review).
      const startedAt = Date.now();
      setCardStatus(c.id, { pendingTaskId: d.task_id, genStartedAt: startedAt });
      pollShot(c.id, d.task_id, startedAt);
      // Registers this generation in the shared Job Tracker (static/mg-notify.js) so it shows
      // up in the activity card no matter which surface is watching -- register-ONLY (no
      // poll loop of its own), since pollShot above already owns real completion handling;
      // Jobs.track()'s own polling would be redundant for a submission this file already
      // tracks. window.Jobs is guaranteed loaded here (mg-notify.js is always included in the
      // Loom's own shell), unlike a host-agnostic shared component that can't assume it.
      if (window.Jobs && window.Jobs.register) window.Jobs.register(d.task_id, entry.code + " · " + (c.title || "untitled"));
      return { ok: true, taskId: d.task_id };
    } catch {
      setGenState((s) => ({ ...s, [c.id]: { phase: "error", msg: "network error" } }));
      // Same rollback as the submit-error branch above, for the same reason: a throw here
      // (dropped connection, unparseable body) otherwise leaves the optimistic "wip" on the
      // card forever, where it reads as a live render and is skipped by every later batch.
      setCardStatus(c.id, { status: "error", pendingTaskId: null, genStartedAt: null });
      return { ok: false, reason: "network" };
    }
  };
  // classifyTaskStatus (loom-mutations.js) is the shared, tested response classifier;
  // the recursive setTimeout tick loop around it stays here since the polling/timing
  // itself is an inherently side-effectful concern, not a pure reducer.
  // No terminal "error" status previously existed on the card itself (only "todo"/"wip"/
  // "done") -- a failed render cleared pendingTaskId but left status:"wip" forever, so a
  // dead generation was indistinguishable from a live one after reload, and this loop
  // polled forever regardless (no give-up path, no cancel button anywhere in generation).
  // Found 2026-07-18 live-testing.
  //
  // Softened 2026-07-18(pm): that fix's own give-up traded the bug for an opposite one -- at
  // 20min elapsed with neither done nor failed reported, it wrote a REAL terminal
  // status:"error" and severed pendingTaskId, indistinguishable from a genuine server failure
  // and unrecoverable short of a fresh submit. The motivating real case (a render that
  // LOOKED lost) turned out to be a content-moderation rejection surfacing late, not an actual
  // timeout -- so a merely-slow shot was being punished identically to one PixAI actually
  // killed. Elapsed time alone now only ever downgrades the poll cadence and escalates
  // genState's message; only a REAL server response (cls.phase==="failed", below, unchanged)
  // can still end a shot in "error". Three thresholds: two cadence downgrades that keep
  // polling (so a shot that eventually finishes still lands its result), then a hard ceiling
  // that stops THIS TAB's own network calls against a task that may be permanently wedged or
  // deleted server-side -- without ever writing status:"error" or clearing pendingTaskId, so a
  // reload (resume effect below, now passing the persisted genStartedAt) or a manual recheck
  // (the card's own status badge, once it reads "paused") always gives it a completely fresh
  // budget rather than abandoning it. Mirrored in mg-generate-drawer.js's _poll -- KEEP THE
  // THREE NUMBERS BELOW IN SYNC with that file.
  const POLL_SLOW_AT_MS   = 20 * 60 * 1000;      // 20min: was the old hard give-up point
  const POLL_SLOW_MS      = 20 * 1000;           // slow-tier cadence
  const POLL_STALE_AT_MS  = 90 * 60 * 1000;      // 90min: second, slower downshift
  const POLL_STALE_MS     = 3 * 60 * 1000;       // stale-tier cadence
  const POLL_CEILING_MS   = 6 * 60 * 60 * 1000;  // 6h: stop auto-polling THIS tab; status untouched
  // existingStartedAt lets the resume-on-reload effect (and a manual "paused" recheck) hand
  // pollShot the card's real, PERSISTED start time instead of a fresh Date.now() -- without
  // this, every reload would silently re-arm a full 6h budget regardless of true elapsed
  // time, reintroducing (on a per-reload cadence) the exact "dead generation indistinguishable
  // from a live one" symptom this whole softening exists to fix (found in review).
  const pollShot = (cardId, tid, existingStartedAt) => {
    setGenState((s) => ({ ...s, [cardId]: { phase: "running", msg: "Rendering… (task " + String(tid).slice(-6) + ")" } }));
    const startedAt = existingStartedAt || Date.now();
    const pause = () => {
      // NOT a giveUp() -- status stays "wip", pendingTaskId stays set, and batchTally
      // records this card's outcome as "stale" (not "failed") so a batch banner never has to
      // lie about a shot this tab has genuinely stopped checking.
      setGenState((s) => ({ ...s, [cardId]: { phase: "paused",
        msg: "Paused auto-checking after " + elapsedLabel(POLL_CEILING_MS) + " with no result — click to check again, or check the task on pixai.art (task " + String(tid).slice(-6) + ")" } }));
      setBatchOutcome(cardId, "stale");
    };
    const tick = () => fetch("/api/task-status?task_id=" + tid).then((r) => r.json()).then((d) => {
      const cls = classifyTaskStatus(d);
      const elapsed = Date.now() - startedAt;
      if (cls.phase === "done") {
        // duration is stashed here too (not just via setCardStatus below) so a draft
        // generation -- with no real card for setCardStatus to find -- still has it
        // on hand when the owner later attaches this result to a shot.
        setGenState((s) => ({ ...s, [cardId]: { phase: "done", msg: "Done", mid: cls.mid, duration: cls.duration } }));
        // capture the clip's REAL length so the reel reflects what was rendered, not planned.
        // Reset trims too -- a re-roll's new clip is a different length than whatever the
        // PREVIOUS result was trimmed to, and a stale trimOut past the new clip's end can hang
        // SequencePlayer on it forever (it never reaches the advance threshold).
        setCardStatus(cardId, { status: "done", resultMid: cls.mid, trimIn: 0, trimOut: null, pendingTaskId: null, genStartedAt: null, ...(cls.duration ? { actualDur: cls.duration } : {}) });
        setBatchOutcome(cardId, "done");
        // Nudge the shared Activity tracker (static/mg-notify.js's JobsCard) the INSTANT
        // this shot's own poll -- the live, real-time signal the per-shot badge above
        // already trusts -- learns the task is done, exactly like the gallery's own
        // Jobs.poll() does on its done branch (mg-notify.js). Without this the tray was
        // only ever as fresh as ITS OWN independent, unsynchronized ~2.5-7s poll cycle
        // (register() above is register-ONLY, no poll of its own -- see that comment), a
        // second, unsynchronized hop that let the two surfaces visibly disagree about the
        // same task and made the tray read as frozen when that hop lagged. window.JobsCard
        // is guaranteed loaded here for the same reason window.Jobs is (mg-notify.js
        // always ships in the Loom's shell).
        if (window.JobsCard && window.JobsCard.refresh) window.JobsCard.refresh();
      } else if (cls.phase === "failed") {
        setGenState((s) => ({ ...s, [cardId]: { phase: "error", msg: cls.msg } }));
        setCardStatus(cardId, { status: "error", pendingTaskId: null, genStartedAt: null });
        setBatchOutcome(cardId, "failed");
        // Same nudge as the done branch above, mirroring mg-notify.js's Jobs.poll() on its
        // own failed branch -- a failed shot must not leave the tray stuck on stale
        // "running" until its own independent cycle happens to catch up.
        if (window.JobsCard && window.JobsCard.refresh) window.JobsCard.refresh();
      } else if (elapsed > POLL_CEILING_MS) {
        pause();
      } else if (elapsed > POLL_STALE_AT_MS) {
        setGenState((s) => ({ ...s, [cardId]: { phase: "stale",
          msg: "Still going after " + elapsedLabel(elapsed) + " — unusual. Check pixai.art, or keep waiting (task " + String(tid).slice(-6) + ")" } }));
        setTimeout(tick, POLL_STALE_MS);
      } else if (elapsed > POLL_SLOW_AT_MS) {
        setGenState((s) => ({ ...s, [cardId]: { phase: "slow",
          msg: "Taking longer than expected (" + elapsedLabel(elapsed) + ", task " + String(tid).slice(-6) + ")" } }));
        setTimeout(tick, POLL_SLOW_MS);
      } else setTimeout(tick, 4000);
    }).catch(() => {
      const elapsed = Date.now() - startedAt;
      if (elapsed > POLL_CEILING_MS) { pause(); return; }
      setTimeout(tick, elapsed > POLL_STALE_AT_MS ? POLL_STALE_MS : elapsed > POLL_SLOW_AT_MS ? POLL_SLOW_MS : 5000);
    });
    setTimeout(tick, 2500);
  };
  // Resume any shot whose render was interrupted by a tab close: the card kept
  // status:"wip" + pendingTaskId, but its in-memory poll loop died with the page. On
  // project load (activeId change), re-attach a poll so the finished clip lands on the
  // card. Deduped per task id so flipping projects back and forth mid-render doesn't
  // stack loops; a resumed poll clears pendingTaskId itself on done/fail.
  //
  // mobileUI ALSO in the dependency array (mobile-generate-rail pass, 2026-08-03 --
  // credit-safety finding): the desktop rail's Video tab submits through <mg-generate-
  // drawer>, whose OWN poll is genuinely component-local (mg-generate-drawer.js's
  // disconnectedCallback clears every _pollTimers entry -- confirmed by reading that
  // file). LoomV2 -- and any <mg-generate-drawer> mounted inside it -- unmounts
  // completely the instant the "📱 Mobile view" toggle flips (the same class of gap
  // increment 3 built generateShot/pollShot specifically to route around for a shot's
  // own clip). Unlike the drawer's documented 6h-ceiling pause, an unmount fires NO
  // 'mg-paused' event -- genState silently freezes on "Rendering…" with nothing left
  // polling, recoverable today only via a full page reload (which re-fires this same
  // effect from a fresh activeId). Re-running the identical, already-idempotent scan on
  // every mobileUI flip closes that gap immediately: any card left "wip"+pendingTaskId
  // by a just-unmounted drawer gets a fresh, hook-level pollShot() the instant the
  // toggle fires, regardless of whether LoomV2 or LoomMobile is the one now unmounting.
  // resumedRef dedupes by taskId (not by trigger reason), so this is a genuine no-op for
  // every task already resumed or still actively polling -- no double-poll risk, and
  // none of Image/Edit/Reference's OWN generation needs this at all: genImage/genEdit/
  // genRef's polls (pollImg/pollTaskWithCeiling, below) are plain setTimeout chains
  // living in this hook, never a DOM element's lifecycle, so they already survive the
  // toggle with no fix required -- verified by reading their implementations, not
  // assumed. See this increment's own report for the injected-state verification.
  useEffect(() => {
    if (!project) return;   // project is null until the store loads the first board
    (project.acts || []).forEach((a) => (a.cards || []).forEach((c) => {
      if (c.status === "wip" && c.pendingTaskId && !resumedRef.current[c.pendingTaskId]) {
        resumedRef.current[c.pendingTaskId] = true;
        pollShot(c.id, c.pendingTaskId, c.genStartedAt);
      }
    }));
  }, [activeId, mobileUI]);   // eslint-disable-line
  // Attach an already-produced video straight onto a shot as its finished clip -- no
  // generation involved. /api/loom/export already treats every resultMid as just "a video
  // file to trim+concat," so this writes the exact same shape pollShot does on completion.
  const useExistingVideo = (entry) => {
    openPick((mid, thumb, isVideo, duration) => {
      const dur = parseFloat(duration);
      setGenState((s) => ({ ...s, [entry.c.id]: { phase: "done", msg: "Attached from your gallery", mid } }));
      // pendingTaskId/genStartedAt cleared too, same as every other status:"done" write in
      // this file -- newly reachable while a generation is "paused" (Deep Focus's busy-guard
      // now lets a paused shot through) but was previously left stale/live here, unlike every
      // other done path (found in review).
      setCardStatus(entry.c.id, { status: "done", resultMid: mid, trimIn: 0, trimOut: null, pendingTaskId: null, genStartedAt: null,
        ...(dur > 0 ? { actualDur: dur } : {}) });
    }, "video");
  };
  // ---- In-Loom reference-image gen: reuse /api/generate (image), poll, then route the result into the shot ----
  // Shared drawer poll. pollShot has had a POLL_CEILING_MS guard since the
  // give-up-timer pass; these drawer polls never did, so a task that never reached
  // a terminal phase polled FOREVER -- and so did a persistently failing fetch,
  // because the .catch re-scheduled too. The control stayed disabled and the tab
  // kept hitting the server every few seconds with nothing to show for it.
  //
  // On hitting the ceiling this stops and reports rather than failing silently.
  // It uses phase "error" deliberately: these three drawers render only
  // submitting/running (busy) and error (message), with no "paused" affordance --
  // that exists on shot cards only. So "error" is what unsticks the control AND
  // surfaces the reason; the message says plainly that the task may still be
  // running, because elapsed time alone is not evidence of failure.
  const pollTaskWithCeiling = (tid, setState, cardId) => {
    const startedAt = Date.now();
    const tick = () => fetch("/api/task-status?task_id=" + tid).then((r) => r.json()).then((d) => {
      const cls = classifyTaskStatus(d);
      // The two JobsCard.refresh() nudges below mirror pollShot's (and mg-notify.js's own
      // Jobs.poll()): the /api/task-status response that reports done/failed is the very call
      // that made the server write the authoritative terminal job event, so refreshing right
      // here cannot race it. Without them a row registered by genImage/genEdit/genRef would sit
      // on stale "running" until the tray's own independent ~2.5-7s cycle happened to catch up --
      // the same "tracker looks frozen / the two surfaces disagree about one task" symptom
      // already fixed for shots. Deliberately NOT done on the ceiling path in again() below:
      // hitting the ceiling only means THIS TAB stopped asking, no job event was written, so a
      // refresh would just re-read the same running row (the server's own orphan-reconciliation
      // sweep, which /api/jobs runs on every read, owns that case).
      if (cls.phase === "done") {
        setState((s) => ({ ...s, [cardId]: { phase: "done", msg: "Done", mid: cls.mid } }));
        if (window.JobsCard && window.JobsCard.refresh) window.JobsCard.refresh();
      } else if (cls.phase === "failed") {
        setState((s) => ({ ...s, [cardId]: { phase: "error", msg: cls.msg } }));
        if (window.JobsCard && window.JobsCard.refresh) window.JobsCard.refresh();
      } else again(4000);
    }).catch(() => again(5000));
    const again = (ms) => {
      if (Date.now() - startedAt > POLL_CEILING_MS) {
        setState((s) => ({ ...s, [cardId]: { phase: "error",
          msg: "Stopped checking after " + elapsedLabel(POLL_CEILING_MS) +
               " — the task may still be running; check it on pixai.art (task " +
               String(tid).slice(-6) + ")" } }));
        return;
      }
      setTimeout(tick, ms);
    };
    setTimeout(tick, 2500);
  };
  const pollImg = (cardId, tid) => pollTaskWithCeiling(tid, setGenImgState, cardId);
  const genImage = async (entry) => {
    const c = entry.c;
    const prompt = (c.imgPrompt || "").trim();
    if (!imgModel) { setGenImgState((s) => ({ ...s, [c.id]: { phase: "error", msg: "pick a model first" } })); return; }
    if (!prompt) { setGenImgState((s) => ({ ...s, [c.id]: { phase: "error", msg: "enter an image prompt" } })); return; }
    if (anyLoraUnresolved(imgLoras)) { setGenImgState((s) => ({ ...s, [c.id]: { phase: "error", msg: "still waiting on a LoRA to resolve" } })); return; }
    // L536: ONE body, shared by the price check just below and the real submit two lines
    // later -- so the free-card/cost check the user is agreeing to is exactly what fires.
    const body = buildImgGenBody(imgModel, imgLoras, imgAdv, prompt);
    if (!(await confirmSpend(body, `Generate a reference image for ${c.title || "this shot"}?`))) return;
    setGenImgState((s) => ({ ...s, [c.id]: { phase: "submitting", msg: "Submitting…" } }));
    try {
      const r = await fetch("/api/generate", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body) });
      const d = await r.json();
      if (d.error || !d.task_id) { setGenImgState((s) => ({ ...s, [c.id]: { phase: "error", msg: (d.error ? friendlyGenErr(d.error) : "submit failed") } })); return; }
      // Register this submission in the shared Job Tracker (static/mg-notify.js -> /api/jobs)
      // the moment the server accepts it. This path -- and genEdit/genRef, via runGen below --
      // never did, so a generation launched from the Loom's Image/Edit/Reference tabs was
      // invisible in BOTH Activity trays (the Loom's and the gallery's): they render from the
      // shared job log, and nothing had ever told it the task existed. Found in the owner's field
      // test 2026-07-24 -- two Image-tab generations, no rows in either tray and not one entry in
      // jobs.jsonl for the task id, while the generation itself succeeded and the live-mirror
      // watcher collected all four of its images. The trays were not broken; they were never told.
      //
      // register(), not track() -- exactly like generateShot above and for the same reason:
      // pollImg below already owns real completion handling, so Jobs.track()'s own polling would
      // be a redundant second poll of the same task id. Terminal state still resolves, because
      // pollImg -> pollTaskWithCeiling polls /api/task-status, and THAT route's done/failed
      // branches are what write the authoritative terminal job event -- the poll already running
      // here is what closes the row out.
      //
      // Label order is deliberate: the TAB the owner clicked first, then the shot code + title
      // (the tail of generateShot's own label, so the two read as one family). .jt-lab is
      // nowrap + ellipsis in a 366px tray, so a long shot title truncates the END -- whatever
      // must survive goes first. A bare "Generated" on all three paths would only restate the
      // standing complaint that this tracker isn't informative.
      if (window.Jobs && window.Jobs.register) window.Jobs.register(d.task_id, "Image · " + entry.code + " · " + (c.title || "untitled"));
      setGenImgState((s) => ({ ...s, [c.id]: { phase: "running", msg: "Generating…" } }));
      pollImg(c.id, d.task_id);
    } catch { setGenImgState((s) => ({ ...s, [c.id]: { phase: "error", msg: "network error" } })); }
  };
  // sourceId defaults to entry.c.id (unchanged behavior: routing a bound shot's own
  // result into itself). Draft-mode calls pass "__draft__" explicitly, since the mid
  // being routed lives under the draft's key while entry is whichever shot got chosen
  // as the destination -- two different ids where bound mode only ever needed one.
  const routeImg = (entry, target, sourceId) => {
    const c = entry.c; const sid = sourceId || c.id; const gs = genImgState[sid]; if (!gs || !gs.mid) return;
    const mid = gs.mid;
    if (target === "open") setCard(entry.a.id, c.id, (x) => ({ ...x, openFrame: { ...x.openFrame, mediaId: mid, thumbId: "", source: "", desc: x.openFrame.desc || "generated in Loom" } }));
    else if (target === "close") setCard(entry.a.id, c.id, (x) => ({ ...x, closeFrame: { ...x.closeFrame, mediaId: mid, thumbId: "", source: "", desc: x.closeFrame.desc || "generated in Loom" } }));
    else if (target === "cast") setAssets((a) => [...a, { id: uid(), name: c.title || "", kind: "image", tag: nextTag(a, "@image"), thumbId: "", source: "", mediaId: mid, lock: false }]);
    setGenImgState((s) => ({ ...s, [sid]: { ...s[sid], routed: target } }));
  };
  // Generic gen runner for the Edit/Reference tabs — submit -> poll -> stash -> route.
  // Parameterized on the state setter so the proven Image path above stays untouched.
  // `label` is the confirmSpend() QUESTION ("Edit the open frame of X?"); `jobLabel` is the
  // separate, much shorter Job Tracker row text each caller supplies -- two different strings
  // for two different surfaces, so neither has to be bent to fit the other.
  const runGen = async (setState, cardId, endpoint, body, priceBody, label, jobLabel) => {
    if (priceBody && !(await confirmSpend(priceBody, label))) return;
    setState((s) => ({ ...s, [cardId]: { phase: "submitting", msg: "Submitting…" } }));
    // Same unbounded-loop fix as pollImg -- see pollTaskWithCeiling's comment.
    const poll = (tid) => pollTaskWithCeiling(tid, setState, cardId);
    try {
      const r = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const d = await r.json();
      if (d.error || !d.task_id) { setState((s) => ({ ...s, [cardId]: { phase: "error", msg: (d.error ? friendlyGenErr(d.error) : "submit failed") } })); return; }
      // Same register-ONLY call, same reasoning, as genImage above -- this helper is the whole
      // Edit + Reference submit path, and it had the identical never-registered gap.
      if (window.Jobs && window.Jobs.register) window.Jobs.register(d.task_id, jobLabel);
      setState((s) => ({ ...s, [cardId]: { phase: "running", msg: "Generating…" } }));
      poll(d.task_id);
    } catch { setState((s) => ({ ...s, [cardId]: { phase: "error", msg: "network error" } })); }
  };
  const routeGen = (state, setState, entry, target, sourceId) => {
    const c = entry.c; const sid = sourceId || c.id; const gs = state[sid]; if (!gs || !gs.mid) return;
    const mid = gs.mid;
    if (target === "open") setCard(entry.a.id, c.id, (x) => ({ ...x, openFrame: { ...x.openFrame, mediaId: mid, thumbId: "", source: "", desc: x.openFrame.desc || "generated in Loom" } }));
    else if (target === "close") setCard(entry.a.id, c.id, (x) => ({ ...x, closeFrame: { ...x.closeFrame, mediaId: mid, thumbId: "", source: "", desc: x.closeFrame.desc || "generated in Loom" } }));
    else if (target === "cast") setAssets((a) => [...a, { id: uid(), name: c.title || "", kind: "image", tag: nextTag(a, "@image"), thumbId: "", source: "", mediaId: mid, lock: false }]);
    setState((s) => ({ ...s, [sid]: { ...s[sid], routed: target } }));
  };
  const genEdit = (entry) => {
    const c = entry.c;
    const src = c.openFrame && c.openFrame.mediaId;
    const instruction = (c.editPrompt || "").trim();
    if (!src) { setGenEditState((s) => ({ ...s, [c.id]: { phase: "error", msg: "the open frame needs a gallery image first (route one from the Image tab, or pick it into the frame)" } })); return; }
    if (!instruction) { setGenEditState((s) => ({ ...s, [c.id]: { phase: "error", msg: "describe the edit" } })); return; }
    const editBody = { source: src, instruction, edit_model: "edit-pro" };
    runGen(setGenEditState, c.id, "/api/edit", editBody, { mode: "edit", ...editBody },
      `Edit the open frame of ${c.title || "this shot"}?`,
      "Edit · " + entry.code + " · " + (c.title || "untitled"));
  };
  const genRef = (entry) => {
    const c = entry.c;
    const refs = (project.assets || []).filter((a) => a.kind === "image" && a.mediaId).map((a) => a.mediaId);
    const prompt = (c.refPrompt || "").trim();
    if (!refs.length) { setGenRefState((s) => ({ ...s, [c.id]: { phase: "error", msg: "add cast @image references (with gallery images) first" } })); return; }
    if (!prompt) { setGenRefState((s) => ({ ...s, [c.id]: { phase: "error", msg: "enter a prompt" } })); return; }
    const refBody = { source: refs[0], sources: refs, instruction: prompt, edit_model: "reference-pro" };
    runGen(setGenRefState, c.id, "/api/edit", refBody, { mode: "edit", ...refBody },
      `Generate a still for ${c.title || "this shot"} from ${refs.length} reference${refs.length === 1 ? "" : "s"}?`,
      // The reference COUNT is the one fact this path is about (and the one its own confirm
      // already surfaces), so it rides in the row rather than being lost to "Reference".
      "Reference ×" + refs.length + " · " + entry.code + " · " + (c.title || "untitled"));
  };
  // ---- In-Loom Fix (face/hand touch-up repair) -- closes the last disclosed gap in Loom
  // Mobile's original 6-increment plan (2026-08-03). Ported from the real, already-shipped
  // gallery/src/components/FixTab.jsx -- SAME real endpoint (/api/fix), SAME real body shape
  // ({source, boxes}, boxes already scaled to ORIGINAL-image pixels by the caller -- see
  // LoomMobile's own scaleFixBoxes/genFix call site), SAME real /api/price mode:"fix" check,
  // SAME real confirm wording FixTab.jsx's own run() uses. Reuses runGen -- the exact submit/
  // poll/register/route machinery genEdit/genRef already share -- for the actual POST, poll,
  // and Job Tracker registration; only the CONFIRM step is bespoke, because a Fix's spend
  // gate is genuinely different from confirmSpend's generic one: a Fix can NEVER be
  // free-card-covered (the /v2/task/fixer endpoint has no kaisuukenId field at all -- see
  // moonglade_gallery.py's _params_and_nocard, mode=="fix" branch, which forces no_card=True
  // for exactly this reason, and FixTab.jsx's own header comment), so confirmSpend's generic
  // "No free card covers it" wording -- which implies one COULD have -- would misdescribe
  // every single Fix. `scaledBoxes` arrives already converted to ORIGINAL-image pixels by the
  // caller -- this function never touches DISPLAY-pixel coordinates or a DOM element, matching
  // every other real submit function in this hook (genEdit/genRef take already-resolved
  // ids/text, never DOM refs).
  const genFix = async (entry, scaledBoxes) => {
    const c = entry.c;
    const src = c.openFrame && c.openFrame.mediaId;
    if (!src) { setGenFixState((s) => ({ ...s, [c.id]: { phase: "error", msg: "the open frame needs a gallery image first (route one from the Image tab, or pick it into the frame)" } })); return; }
    if (!scaledBoxes || !scaledBoxes.length) { setGenFixState((s) => ({ ...s, [c.id]: { phase: "error", msg: "drag a box over a hand or face first" } })); return; }
    // One fresh /api/price check, right here, right before the confirm -- there is no
    // debounced cost cache to go stale against in THIS hook (unlike FixTab.jsx's own
    // colocated cost badge, which has to flush a pending debounce and await it before
    // reading its own costVal ref), so there is nothing to flush; this fetch already IS the
    // fresh read the moment the owner taps Fix. mode:"fix" always comes back free:false
    // (server-forced -- see _params_and_nocard), so `cost` is the only field this confirm
    // ever needs.
    let pr = null;
    try {
      const r = await fetch("/api/price", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "fix", source: src, boxes: scaledBoxes }) });
      pr = await r.json();
    } catch { pr = null; }
    const priced = pr && typeof pr.cost === "number" ? pr.cost : null;
    // Wording ported VERBATIM from FixTab.jsx's own run() -- "ALWAYS spends" / "never
    // covered by a free card" -- not confirmSpend's generic phrasing, which this Fix gate
    // deliberately does not call.
    const quote = priced == null
      ? "The price could not be verified, and a Fix ALWAYS spends credits (no free card can ever cover it)."
      : "This will spend " + Number(priced).toLocaleString() + " credits — a Fix is never covered by a free card.";
    if (!window.confirm(
      "Repair " + scaledBoxes.length + " area" + (scaledBoxes.length === 1 ? "" : "s") + "?\n\n" + quote
    )) return;
    // priceBody is null: runGen's own confirmSpend gate exists for the OTHER two drawer tabs
    // (which CAN be free-card-covered) -- this submit already ran its own, Fix-correct
    // confirm above, so passing null here skips a SECOND, wrongly-worded confirm rather than
    // stacking one on top of it.
    runGen(setGenFixState, c.id, "/api/fix", { source: src, boxes: scaledBoxes }, null, "",
      "Fix · " + entry.code + " · " + (c.title || "untitled"));
  };
  // Batch-generate the whole board: fire every not-done shot in sequence, staggered so
  // the submits don't collide. Each shot manages its own status/poll via generateShot.
  // Takes `entries` as a call-site argument (computed by App() from the current
  // project) rather than closing over it, since this hook has no `entries` of its own.
  const batchGenerate = async (entries) => {
    // Exclude "wip" alongside "done" -- a shot already mid-render (started individually via
    // the drawer, or reattached by the resume-on-load effect) must not be resubmitted just
    // because it isn't finished yet. Found in review: the batching flag only guards the
    // TOOLBAR button, not this filter, so a batch launched while some other shot happens to
    // already be rendering used to fire a second, duplicate /api/loom/generate for it.
    const todo = entries.filter((e) => e.c.status !== "done" && e.c.status !== "wip");
    if (!todo.length) return;
    // Price every shot FIRST so the confirm shows real cost + card coverage — no silent spend.
    setBatching(true);
    const prices = await Promise.all(todo.map((e) => priceShot(e)));
    // tallyPrices (loom-core.js) fails closed the same way this loop always did (a failed
    // price check buckets as "unknown", never a false "0 credits") -- now the one shared
    // implementation instead of a copy hand-rolled here.
    const { free, paid, credits, unknown } = tallyPrices(prices);
    // Soft warning, not a hard filter -- flagged shots still generate (matches generateShot's
    // own !hasInput behavior: a visible per-card error at submit time, not silently vanishing
    // from the count). Checked against the shot's own freeform field via effectivePrompt(),
    // NOT shotPayload().prompt/shotText() -- that composed string always starts with a
    // non-empty bracketed header before c.prompt is even appended, so a check against it
    // can never fire regardless of whether the shot's real prompt is blank (found in review).
    const emptyPromptShots = todo.filter((e) => !effectivePrompt(e.c).trim());
    const msg = `Generate ${todo.length} shot(s)?\n\n` +
      `🎫 ${free} covered by a free card\n` +
      `≈ ${paid} will spend credits — about ${credits.toLocaleString()} total` +
      (unknown ? `\n⚠ ${unknown} shot(s)' cost couldn't be verified — they may also spend credits.` : ".") +
      (emptyPromptShots.length ? `\n⚠ ${emptyPromptShots.length} shot(s) have no prompt text yet: ${emptyPromptShots.map((e) => e.code).join(", ")}` : "");
    if (!window.confirm(msg)) { setBatching(false); return; }
    // Reset ONLY after the confirm is accepted -- resetting before it and leaving batchTally
    // non-null on Cancel would freeze a permanent "0 submitted" banner on screen forever,
    // since nothing else would ever touch it again.
    const ids = new Set(todo.map((e) => e.c.id));
    setBatchTally({ total: todo.length, submitted: 0, ids, outcomes: {} });
    for (const e of todo) {
      // generateShot never throws (every failure path returns {ok:false,...}), so this
      // try/catch is defensive only -- the tally itself is driven by the return value, not
      // by whether an exception escaped (a first-draft design tried the latter and, since
      // generateShot swallows every failure internally, it never actually caught anything).
      let r;
      try { r = await generateShot(e, { skipConfirm: true }); } catch (_e) { r = { ok: false }; }
      // A successful submit only bumps `submitted` -- its eventual done/failed/stale outcome
      // is recorded later by pollShot via setBatchOutcome. An immediate submit-time failure
      // (r.ok===false) never gets a pollShot at all, so it records its own "failed" outcome
      // right here, the one place that will ever happen for this card.
      if (r.ok) setBatchTally((prev) => (prev && prev.ids.has(e.c.id) ? { ...prev, submitted: prev.submitted + 1 } : prev));
      else setBatchOutcome(e.c.id, "failed");
      await new Promise((res) => setTimeout(res, 2200));
    }
    setBatching(false);
  };

  // ---- Standing cost-to-finish estimate: a per-shot price CACHE, warm without gating on
  // the batch confirm dialog. Distinct from priceShot/batchGenerate's own one-shot,
  // no-caching, must-be-fresh-right-before-spending pricing pass -- that one keeps its own
  // Promise.all right before the irreversible confirm, deliberately not sharing this cache
  // (different timing/staleness contract). Only the pure tally math (tallyPrices) is shared.
  const PRICE_DEBOUNCE_MS = 600;
  const [priceCache, setPriceCache] = useState({});          // cardId -> {fp, pr, loading}
  const priceInFlightRef = useRef({});                       // cardId -> fp currently being fetched
  const ensurePriced = useCallback((entry, force) => {
    const payload = shotPayload(entry);
    const fp = priceFingerprint(payload);
    const cached = priceCache[entry.c.id];
    if (!force && cached && cached.fp === fp && !cached.loading) return;
    if (!payload.hasInput) { setPriceCache((s) => ({ ...s, [entry.c.id]: { fp, pr: null, loading: false } })); return; }
    if (priceInFlightRef.current[entry.c.id] === fp) return;
    priceInFlightRef.current[entry.c.id] = fp;
    setPriceCache((s) => ({ ...s, [entry.c.id]: { fp, pr: (cached && cached.fp === fp ? cached.pr : null), loading: true } }));
    priceShot(entry).then((pr) => {
      // Clear the in-flight marker on completion regardless of outcome -- leaving it set
      // forever (found in review) silently blocks BOTH the manual force-refresh AND the
      // ordinary case of a field changing away from and back to a previously-seen
      // fingerprint, since the guard above never sees priceInFlightRef clear to retry.
      const stillCurrent = priceInFlightRef.current[entry.c.id] === fp;
      if (stillCurrent) delete priceInFlightRef.current[entry.c.id];
      if (!stillCurrent) return;   // a newer edit superseded this fetch; don't clobber its slot
      setPriceCache((s) => ({ ...s, [entry.c.id]: { fp, pr, loading: false } }));
    });
  }, [project, priceCache]);   // eslint-disable-line react-hooks/exhaustive-deps
  // Memoized on `project` alone -- without this, genState updates (a poll tick fires every
  // 2.5-4s per actively-rendering shot, and lives in this same hook) would rebuild the
  // whole not-done board's shotText/fingerprint composition on every tick, precisely when
  // the board is busiest (found in review).
  const { notDone, notDoneFp } = useMemo(() => {
    const boardEntries = project ? flat(project) : [];
    const nd = boardEntries.filter((e) => e.c.status !== "done");
    const fp = nd.map((e) => e.c.id + ":" + priceFingerprint(shotPayload(e))).join("|");
    return { notDone: nd, notDoneFp: fp };
  }, [project]);   // eslint-disable-line react-hooks/exhaustive-deps
  const priceDebounceRef = useRef(null);
  useEffect(() => {
    clearTimeout(priceDebounceRef.current);
    priceDebounceRef.current = setTimeout(() => notDone.forEach((e) => ensurePriced(e)), PRICE_DEBOUNCE_MS);
    return () => clearTimeout(priceDebounceRef.current);
  }, [notDoneFp]);   // eslint-disable-line react-hooks/exhaustive-deps
  const refreshEstimate = useCallback(() => notDone.forEach((e) => ensurePriced(e, true)), [notDone, ensurePriced]);
  const pending = notDone.filter((e) => { const r = priceCache[e.c.id]; return !r || r.loading; }).length;
  const settled = notDone.filter((e) => { const r = priceCache[e.c.id]; return r && !r.loading; }).map((e) => priceCache[e.c.id].pr);
  const costEstimate = { ...tallyPrices(settled), pending, notDoneCount: notDone.length };

  return {
    genState, setGenState, genImgState, setGenImgState, imgModel, setImgModel,
    imgLoras, setImgLoras, imgAdv, setImgAdv, modelDefaults, setModelDefaults,
    genEditState, setGenEditState,
    genRefState, setGenRefState, genFixState, setGenFixState, batching, batchTally,
    // priceShot exposed (mobile-generate-screen pass, 2026-08-03): the SAME read-only
    // /api/price check generateShot/confirmSpend/batchGenerate already use internally --
    // Loom Mobile's own Generate screen needs a per-shot cost PREVIEW to show before the
    // owner ever taps the real submit button, and this is that exact function, not a new
    // fetch/pricing implementation. It was already defined here; only its exposure is new.
    generateShot, pollShot, useExistingVideo, genImage, routeImg, genEdit, genRef, genFix, routeGen, batchGenerate,
    costEstimate, refreshEstimate, priceShot,
  };
}

// ---- 4. useExportPipeline: shot-list/backup export, play-sequence, ffmpeg cut ----
function useExportPipeline(project, thumbs) {
  const [seq, setSeq] = useState(null);           // Play-sequence: [clip,...] or null
  const [exp, setExp] = useState(null);           // export overlay: {status,progress,...} or null
  const exportPoll = useRef(null);

  const download = (text, name, type) => { const url = URL.createObjectURL(new Blob([text], { type }));
    const a = document.createElement("a"); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
  // shotText is handed over UNBOUND, so buildShotListText composes noImgSrc -- the
  // drawer-DECOUPLED family (2026-07-27, round 3 resolver-split audit; same reasoning as
  // copyShot in App below): the exported shot list is a standalone .txt rendering that
  // never feeds or gets compared against the drawer's prompt box, and session-local thumb
  // data-URL numbering would be meaningless in a file on disk. The drawer-coupled family
  // (prefill/comparators in LoomV2) must all compose WITH imgSrc.
  const exportAll = () => download(buildShotListText(project, fmt, actLetter, shotText),
    `${project.name.replace(/\s+/g, "_")}_shotlist.txt`, "text/plain");
  const exportJSON = () => download(JSON.stringify({ project, thumbs }, null, 2), `${project.name.replace(/\s+/g, "_")}_backup.json`, "application/json");
  const [bundling, setBundling] = useState(false);
  const [bundleMissing, setBundleMissing] = useState(null);   // M24 report: {total, rows, hidden} or null
  // Tier 2: same {project, thumbs} as the lightweight backup, but the server zips in
  // every media file the project actually references (resultMid, both frame slots, every
  // cast/asset) -- for sharing with someone who doesn't share your catalog. media_ids ride
  // along unchanged; a real PixAI id is globally issued, so the receiving machine either
  // already has it or files it fresh -- no path-rewriting needed either direction.
  const exportBundle = async () => {
    setBundling(true);
    try {
      const r = await fetch("/api/loom/export-bundle", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project, thumbs }) });
      if (!r.ok) { const d = await r.json().catch(() => ({})); alert("Bundle export failed: " + (d.error || r.status)); return; }
      // A partial bundle is still a successful export, so the report about it has to reach the
      // owner some other way. Both headers, not just the count: "2 referenced file(s) couldn't
      // be found" told them a number and left them hand-diffing every reference in the project
      // against the zip's media/ folder to find out WHICH shot lost a file (M24). The act/shot
      // labels come from bundleMissingReport() walking the project we just posted -- see its
      // comment in loom-core.js for why they are not in the (length-capped) header.
      const report = bundleMissingReport(project, r.headers.get("X-Bundle-Missing-Count"), r.headers.get("X-Bundle-Missing"));
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url;
      a.download = `${project.name.replace(/\s+/g, "_")}_bundle.zip`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      // A dialog, not an alert(): this is a LIST the owner reads while looking at the board,
      // and alert() is modal to the whole tab, unreadable past a couple of lines, and gone the
      // moment it is dismissed. Same overlay the cut export already uses (setExp/.sb-export-box).
      if (report.total) setBundleMissing(report);
    } catch { alert("Bundle export failed -- network error."); }
    finally { setBundling(false); }
  };
  // Play-sequence: every finished shot (persisted resultMid), in order, with its
  // in/out trim -- a rough cut played back-to-back, nothing rendered.
  const playSequence = (entries) => {
    const clips = buildPlaySequence(entries);
    if (clips.length) setSeq(clips); else alert("No finished shots yet — generate one first.");
  };
  // Export: trim each finished shot + concat into one mp4 (ffmpeg, server-side).
  const exportCut = (entries) => {
    const { clips, total } = buildExportClips(entries);
    if (!clips.length) { alert("No finished shots to export yet — generate one first."); return; }
    setExp({ status: "running", progress: 0, elapsed: 0 });
    fetch("/api/loom/export", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clips: clips.map((c) => ({ mid: c.mid, in: c.in, out: c.out, crop: c.crop })), total_seconds: total }) })
      .then((r) => r.json()).then((d) => {
        if (d.error) { setExp({ status: "failed", error: d.error }); return; }
        const tick = () => fetch("/api/loom/export-status").then((r) => r.json()).then((s) => {
          setExp(s);
          if (s.status === "running") exportPoll.current = setTimeout(tick, 1000);
        }).catch(() => { exportPoll.current = setTimeout(tick, 2000); });
        tick();
      }).catch(() => setExp({ status: "failed", error: "network error" }));
  };
  const cancelExport = () => { fetch("/api/loom/export-cancel", { method: "POST" }).catch(() => {}); };
  const closeExport = () => { if (exportPoll.current) clearTimeout(exportPoll.current); setExp(null); };
  // The genuinely-confirmed root cause of "play works, but close/next don't once it's
  // playing": the sequence player's onClose called setSeq directly, but setSeq was never
  // exposed by this hook (only seq was) -- every close/next-past-the-end click threw
  // ReferenceError: setSeq is not defined, silently (only visible in the console), which
  // is exactly why it looked like the buttons just didn't respond.
  const closeSequence = () => setSeq(null);

  return { seq, exp, playSequence, exportCut, cancelExport, closeExport, closeSequence,
    exportAll, exportJSON, exportBundle, bundling,
    bundleMissing, closeBundleMissing: () => setBundleMissing(null) };
}

export default function App() {
  const [selShot, setSelShot] = useState(null);   // V2 selected-shot: card.id or null
  // "📱 Mobile view" -- a manual, owner-preference switch between LoomV2 (desktop-style
  // shell) and LoomMobile (phone-sized board/reel), persisted via useLocalToggle so it
  // survives a reload. The toggle itself lives in LoomV2's own .lv-top bar (and, so it's
  // never a one-way trap, a small reciprocal one in LoomMobile's own top bar).
  const [mobileUI, setMobileUI] = useLocalToggle(MOBILE_UI_KEY, false);
  // draftCard/draftTarget/draftAttachedInfo -- LIFTED up from LoomV2's own component state
  // (mobile-board-view pass, 2026-08-03) so an in-progress Generate-drawer draft (no shot
  // selected yet, keyed "__draft__" the same way genState/genImgState/etc already are)
  // survives toggling between LoomV2 and LoomMobile instead of being discarded the moment
  // whichever one owned it unmounts. Passed down to BOTH below; LoomV2's own behavior is
  // unchanged -- every reference to these three inside LoomV2 is identical to when they were
  // its own useState calls, only the declaration moved.
  const [draftCard, setDraftCard] = useState(() => ({
    id: "__draft__", mode: "R2V", duration: 5, connect: "new", title: "", prompt: "",
    camera: "", lighting: "", transIn: "", transOut: "", audioCue: "", notes: "",
    audioGen: false, audioLanguage: "english",
    imgPrompt: "", editPrompt: "", refPrompt: "",
    cast: [], refs: [], openFrame: {}, closeFrame: {},
    promptOverride: false, promptOverrideText: "",
  }));
  const [draftTarget, setDraftTarget] = useState("");              // shot id chosen to route/attach a draft result into
  const [draftAttachedInfo, setDraftAttachedInfo] = useState(null); // {mid, code} once a draft video is attached to a shot
  const { project, setProject, thumbs, storeThumb, busy,
    projList, projMenu, setProjMenu, projectApi, importBackup, activeId } = useProjectStore(setSelShot);

  const { open, setOpen, setCard, setAct, setAssets, setCardStatus,
    addCard, importFootage, dupCard, delCard, moveCard, moveCardToAct, addAct, delAct, moveAct,
    addRef, setRef, delRef, splitShot } = useShotMutations(project, setProject);

  const [pickCb, setPickCb] = useState(null);     // gallery picker: cb(mid, thumb, isVideo) or null
  const [pickKind, setPickKind] = useState("image");  // preferred default type for the picker
  const [pickAllowType, setPickAllowType] = useState(false);  // show the Image/Video/All filter?
  const [importOpen, setImportOpen] = useState(false);  // import-collection dialog
  const [showHelp, setShowHelp] = useState(false);
  const [showGuide, setShowGuide] = useState(() => {
    try { return !localStorage.getItem("loom_guide_seen"); } catch (e) { return true; } });
  const [showCast, setShowCast] = useState(true);
  const openPick = useCallback((cb, kind, allowType) => { setPickKind(kind || "image"); setPickAllowType(!!allowType); setPickCb(() => cb); }, []);
  // pickCb doesn't change while the picker is mounted (only open->close via setPickCb), so
  // the onPick closure below stays correct for the whole picking session.
  const onGalleryPick = (m) => {
    const cb = pickCb; setPickCb(null);
    if (cb) cb(m.media_id, m.thumb, m.is_video, m.duration, m.is_nsfw);
  };

  const { genState, setGenState, genImgState, setGenImgState, imgModel, setImgModel,
    imgLoras, setImgLoras, imgAdv, setImgAdv, modelDefaults, setModelDefaults,
    genEditState, setGenEditState,
    genRefState, setGenRefState,
    // genFixState/setGenFixState/genFix -- seventh increment (2026-08-03), the real Fixer
    // submit path (useGenerationPipeline's own genFix). Only LoomMobile receives it below --
    // desktop's LoomV2 has no Fixer tab (out of this increment's scope).
    genFixState, setGenFixState, batching, batchTally,
    // generateShot/priceShot newly destructured here (mobile-generate-screen pass,
    // 2026-08-03) -- both already existed on the hook's return value, generateShot simply
    // had no consumer above batchGenerate's own internal call until Loom Mobile's Generate
    // screen needed the exact same real per-shot submit + price-preview functions LoomV2's
    // batch path already uses. Nothing about either function changes; only who else gets a
    // reference to them.
    generateShot, priceShot,
    pollShot, useExistingVideo, genImage, routeImg, genEdit, genRef, genFix, routeGen, batchGenerate,
    costEstimate, refreshEstimate }
    // mobileUI passed in (mobile-generate-rail pass, 2026-08-03) so the resume-on-reload
    // effect can also fire on the Mobile-view toggle -- see that effect's own comment.
    = useGenerationPipeline({ project, thumbs, setCard, setCardStatus, setAssets, openPick, activeId, mobileUI });
  // <mg-generate-drawer> owns its own submit/poll now (Loom-mount build, 2026-07-18); these
  // mirror exactly what generateShot/pollShot already write for every OTHER path, so the
  // board card's live status badge, tab-close resume (pendingTaskId), and the finished clip
  // landing on the shot all keep working identically regardless of which UI submitted.
  const onVideoSubmit = useCallback((cardId, detail) => {
    setGenState((s) => ({ ...s, [cardId]: { phase: "running", msg: "Rendering… (task " + String(detail.task_id).slice(-6) + ")" } }));
    // genStartedAt persisted here too, not just in generateShot's own submit site -- the
    // resume-on-reload effect (useGenerationPipeline) resumes ANY wip+pendingTaskId card via
    // pollShot regardless of which path originally submitted it (the drawer's own in-memory
    // poll dies with the page same as pollShot's would). Without this, reloading a page with a
    // still-pending drawer-submitted shot would resume with no persisted start time, silently
    // re-arming a full 6h give-up budget on every reload (found while implementing).
    setCardStatus(cardId, { status: "wip", pendingTaskId: detail.task_id, genStartedAt: Date.now() });
    // Registers with the shared Job Tracker (static/mg-notify.js), mirroring generateShot's
    // own registration -- deliberately done HERE (the Loom's own host code), not inside
    // mg-generate-drawer.js itself, so the shared drawer component stays genuinely
    // host-agnostic (its own documented contract) rather than assuming window.Jobs exists.
    // "Rendered" matches the gallery's own existing label for this same /api/loom/generate
    // endpoint (Gen.videoGenerate()'s runTask call).
    if (window.Jobs && window.Jobs.register) window.Jobs.register(detail.task_id, "Rendered");
  }, [setGenState, setCardStatus]);
  const onVideoResult = useCallback((cardId, detail) => {
    const mid = (detail.media_ids || [])[0];
    setGenState((s) => ({ ...s, [cardId]: { phase: "done", msg: "Done", mid, duration: detail.duration } }));
    setCardStatus(cardId, { status: "done", resultMid: mid, trimIn: 0, trimOut: null, pendingTaskId: null, genStartedAt: null,
      ...(detail.duration ? { actualDur: detail.duration } : {}) });
  }, [setGenState, setCardStatus]);
  const onVideoError = useCallback((cardId, detail) => {
    setGenState((s) => ({ ...s, [cardId]: { phase: "error", msg: detail.error } }));
    // Persist the failure onto the card itself, not just the ephemeral (reload-wiped)
    // genState -- previously only pendingTaskId cleared here, leaving status:"wip" forever,
    // indistinguishable from a shot that's still genuinely rendering. Found 2026-07-18.
    // NOTE (2026-07-18(pm)): this now only ever fires on a REAL d.phase==='failed' from the
    // drawer's own poll -- elapsed-time-alone timeouts route through onVideoSlow/onVideoPaused
    // below instead, and never touch card.status at all.
    setCardStatus(cardId, { status: "error", pendingTaskId: null, genStartedAt: null });
  }, [setGenState, setCardStatus]);
  // mg-slow: the drawer's poll downshifted cadence without a real result. Board-grid cards
  // read their badge text from genState, not the drawer's own inline `res` div (only visible
  // while this shot's Video tab is open) -- this is the mirror write that keeps them in sync.
  // Never touches setCardStatus or batchTally: status stays "wip", and drawer-submitted shots
  // are never part of a batch run (batchGenerate only ever calls generateShot/pollShot
  // directly, never the drawer).
  const onVideoSlow = useCallback((cardId, detail) => {
    setGenState((s) => ({ ...s, [cardId]: {
      phase: detail.tier,
      msg: detail.tier === "stale"
        ? "Still going after " + elapsedLabel(detail.elapsed) + " — unusual. Check pixai.art, or keep waiting (task " + String(detail.task_id).slice(-6) + ")"
        : "Taking longer than expected (" + elapsedLabel(detail.elapsed) + ", task " + String(detail.task_id).slice(-6) + ")",
    } }));
  }, [setGenState]);
  // mg-paused: the drawer's poll hit its 6h ceiling and stopped scheduling calls for this
  // task. Same non-verdict as pollShot's own pause() -- status/pendingTaskId untouched.
  const onVideoPaused = useCallback((cardId, detail) => {
    setGenState((s) => ({ ...s, [cardId]: { phase: "paused",
      msg: "Paused auto-checking with no result — click to check again, or check pixai.art (task " + String(detail.task_id).slice(-6) + ")" } }));
  }, [setGenState]);
  // Draft-generation results (Image/Edit/Reference/Video) are keyed by the fixed "__draft__"
  // id, shared across every open project -- without this, a finished draft from project A
  // resurfaces in project B's drawer (still-live thumbnail + a working attach button that
  // writes into whichever shot in B you pick) the moment you switch projects, since nothing
  // else ever clears these four dicts. Reset all of them whenever the active project changes.
  // genFixState included for the same hygiene even though nothing currently drives it via
  // "__draft__" (LoomMobile's Fixer always operates on a real, bound dfLive shot -- draft
  // mode is desktop-only and out of this increment's scope) -- a genuine no-op today, kept
  // symmetric with its three siblings rather than a silent exception to this comment's own rule.
  useEffect(() => {
    const clearDraft = (s) => { if (!("__draft__" in s)) return s; const n = { ...s }; delete n.__draft__; return n; };
    setGenState(clearDraft); setGenImgState(clearDraft); setGenEditState(clearDraft); setGenRefState(clearDraft); setGenFixState(clearDraft);
  }, [activeId]);

  const { seq, exp, playSequence, exportCut, cancelExport, closeExport, closeSequence,
    exportAll, exportJSON, exportBundle, bundling,
    bundleMissing, closeBundleMissing } = useExportPipeline(project, thumbs);

  // Import a whole gallery collection as reusable @image references (media_id kept
  // -> free reference at generate time). Tags continue from the current max @imageN.
  const importCollection = (items, cname) => {
    setImportOpen(false);
    if (!items || !items.length) return;
    setAssets((a) => {
      let n = maxTagNum(a, "@image");
      const added = items.map((it, i) => ({ id: uid(), name: it.name || `${cname} ${i + 1}`, kind: "image",
        tag: "@image" + (++n), thumbId: "", source: "", mediaId: it.mediaId, lock: false }));
      return [...a, ...added];
    });
  };

  // Deliberately noImgSrc -- the drawer-DECOUPLED shotText family (2026-07-27, round 3
  // resolver-split audit). A copied shot is a standalone rendering for pasting OUTSIDE
  // this app; it never feeds the drawer's prompt box and is never compared against it, so
  // the "same resolver everywhere the drawer is involved" rule (see the prefill effect's
  // payload.prompt comment in LoomV2) does not bind it. It cites durable mediaId-backed
  // images only, by design -- a citation numbered off a session-local thumb data-URL
  // means nothing on a clipboard. The drawer-coupled family (prefill, mg-prompt-commit,
  // outgoing-shot flush, re-sync, Generate-all flush) must all pass imgSrc.
  const copyShot = (entry) => navigator.clipboard?.writeText(shotText(entry, project));
  const setLook = (v) => setProject((p) => ({ ...p, look: v }));
  const setDraft = (v) => setProject((p) => ({ ...p, draft: v }));

  if (!project) return <div className="sb-root"><style>{STYLES}</style><div className="sb-empty">Loading the bay…</div></div>;

  const entries = flat(project);
  const anyDone = entries.some((e) => e.c.resultMid);
  // durOf/reelStats now imported from ./src/loom-core.js (reel uses the ACTUAL
  // generated length when a shot has rendered, else the planned duration).
  const { total, scale, over } = reelStats(entries, project.target);
  const done = entries.filter((x) => x.c.status === "done").length;

  return (
    <div className="sb-root">
      <style>{STYLES}</style>
      {mobileUI ? (
        <V2Boundary><LoomMobile
          project={project} entries={entries} thumbs={thumbs} genState={genState}
          selShot={selShot} setSelShot={setSelShot} addCard={addCard} addAct={addAct} setDraft={setDraft}
          setCard={setCard} setAssets={setAssets} addRef={addRef} setRef={setRef} delRef={delRef}
          storeThumb={storeThumb} openPick={openPick} copyShot={copyShot} splitShot={splitShot}
          moveCard={moveCard} dupCard={dupCard} delCard={delCard}
          mobileUI={mobileUI} setMobileUI={setMobileUI}
          draftCard={draftCard} setDraftCard={setDraftCard} draftTarget={draftTarget} setDraftTarget={setDraftTarget}
          draftAttachedInfo={draftAttachedInfo} setDraftAttachedInfo={setDraftAttachedInfo}
          generateShot={generateShot} priceShot={priceShot} useExistingVideo={useExistingVideo}
          genImgState={genImgState} imgModel={imgModel} setImgModel={setImgModel}
          imgLoras={imgLoras} setImgLoras={setImgLoras} imgAdv={imgAdv} setImgAdv={setImgAdv}
          modelDefaults={modelDefaults} setModelDefaults={setModelDefaults} genImage={genImage} routeImg={routeImg}
          genEditState={genEditState} setGenEditState={setGenEditState} genRefState={genRefState} setGenRefState={setGenRefState}
          genEdit={genEdit} genRef={genRef} routeGen={routeGen}
          genFixState={genFixState} setGenFixState={setGenFixState} genFix={genFix} /></V2Boundary>
      ) : (
        <V2Boundary><LoomV2
          project={project} setCard={setCard} setAssets={setAssets} entries={entries} durOf={durOf} scale={scale}
          selShot={selShot} setSelShot={setSelShot} useExistingVideo={useExistingVideo} genState={genState}
          thumbs={thumbs} openPick={openPick} storeThumb={storeThumb}
          setAct={setAct} addCard={addCard} importFootage={importFootage} dupCard={dupCard} delCard={delCard} moveCard={moveCard}
          moveCardToAct={moveCardToAct} addAct={addAct} delAct={delAct} moveAct={moveAct}
          genImgState={genImgState} imgModel={imgModel} setImgModel={setImgModel}
          imgLoras={imgLoras} setImgLoras={setImgLoras} imgAdv={imgAdv} setImgAdv={setImgAdv}
          modelDefaults={modelDefaults} setModelDefaults={setModelDefaults}
          genImage={genImage} routeImg={routeImg}
          genEditState={genEditState} setGenEditState={setGenEditState} genRefState={genRefState} setGenRefState={setGenRefState} genEdit={genEdit} genRef={genRef} routeGen={routeGen}
          genFixState={genFixState} setGenFixState={setGenFixState} genFix={genFix}
          projectApi={projectApi} playSequence={playSequence} exportCut={exportCut}
          batching={batching} batchGenerate={batchGenerate} batchTally={batchTally}
          addRef={addRef} setRef={setRef} delRef={delRef}
          exportAll={exportAll} exportJSON={exportJSON} exportBundle={exportBundle} bundling={bundling}
          importBackup={importBackup} setImportOpen={setImportOpen} copyShot={copyShot} setLook={setLook} setDraft={setDraft} splitShot={splitShot}
          onVideoSubmit={onVideoSubmit} onVideoResult={onVideoResult} onVideoError={onVideoError}
          onVideoSlow={onVideoSlow} onVideoPaused={onVideoPaused} pollShot={pollShot}
          costEstimate={costEstimate} refreshEstimate={refreshEstimate}
          mobileUI={mobileUI} setMobileUI={setMobileUI}
          draftCard={draftCard} setDraftCard={setDraftCard} draftTarget={draftTarget} setDraftTarget={setDraftTarget}
          draftAttachedInfo={draftAttachedInfo} setDraftAttachedInfo={setDraftAttachedInfo} /></V2Boundary>
      )}
      {seq && <SequencePlayer clips={seq} onClose={closeSequence} />}
      {exp && (
        <div className="sb-seq" onClick={(e) => { if (e.target === e.currentTarget && exp.status !== "running") closeExport(); }}>
          <div className="sb-export-box">
            <div className="sb-pick-head"><span className="sb-pick-t">Export the cut</span>
              {exp.status !== "running" && <button className="sb-pick-x" onClick={closeExport}>&#215;</button>}</div>
            {exp.status === "running" && <>
              <div className="sb-exp-bar"><i style={{ width: (exp.progress || 0) + "%" }} /></div>
              <div className="sb-exp-txt">Rendering&hellip; {exp.progress || 0}% &middot; {Math.round(exp.elapsed || 0)}s of cut</div>
              <button className="sb-btn ghost sm" style={{ alignSelf: "center" }} onClick={cancelExport}>&#9632; Stop</button>
            </>}
            {exp.status === "done" && <>
              <div className="sb-exp-txt" style={{ color: "var(--green)" }}>&#10003; Cut rendered.</div>
              {/* A render that SUCCEEDED but came out different from what was asked for -- today
                  that means no audio track, because a missing ffprobe made every clip's length
                  unreadable. Shown next to the download button rather than logged, since the
                  owner is the one who can install the missing piece. */}
              {exp.warning && <div className="sb-exp-txt" style={{ color: "var(--amber)" }}>&#9888; {exp.warning}</div>}
              <a className="sb-btn amber" href="/api/loom/export-file" style={{ alignSelf: "center", textDecoration: "none" }}>&#8681; Download mp4</a>
              <button className="sb-btn ghost sm" style={{ alignSelf: "center" }} onClick={closeExport}>Close</button>
            </>}
            {(exp.status === "failed" || exp.status === "cancelled") && <>
              <div className="sb-exp-txt" style={{ color: exp.status === "failed" ? "var(--coral)" : "var(--ink2)" }}>
                {exp.status === "failed" ? ("⚠ " + (exp.error || "export failed")) : "■ Export stopped."}</div>
              <button className="sb-btn ghost sm" style={{ alignSelf: "center" }} onClick={closeExport}>Close</button>
            </>}
          </div>
        </div>)}
      {/* Full-bundle export, partial result (M24). The zip is already downloaded and still
          useful -- this names the references whose file wasn't on disk, by the same A·01 shot
          codes the board shows, so the owner knows where to look instead of being handed a
          count. Dismiss-only: there is nothing to retry here, the fix is off-screen (re-sync
          or re-generate the shot), and the durable copy travels in the zip's project.json. */}
      {bundleMissing && (
        <div className="sb-seq" onClick={(e) => { if (e.target === e.currentTarget) closeBundleMissing(); }}>
          <div className="sb-export-box">
            <div className="sb-pick-head"><span className="sb-pick-t">Bundle exported, {bundleMissing.total} file(s) left out</span>
              <button className="sb-pick-x" style={{ marginLeft: "auto" }} onClick={closeBundleMissing}>&#215;</button></div>
            <div className="sb-exp-txt" style={{ color: "var(--coral)" }}>
              &#9888; No file on disk for these references &mdash; everything else exported normally.</div>
            {bundleMissing.rows.length > 0 && (
              <div className="sb-miss-list">
                {bundleMissing.rows.map((row) => (
                  <div className="sb-miss-row" key={row.mid}>
                    {row.where.length
                      ? row.where.map((w, i) => <b key={i}>{w}</b>)
                      : <i>not referenced by any shot or cast entry in this project</i>}
                    <span className="sb-miss-id">{row.mid}</span>
                  </div>))}
              </div>)}
            {bundleMissing.hidden > 0 && (
              <div className="sb-exp-txt" style={{ color: "var(--ink2)", fontSize: "12px" }}>
                {bundleMissing.rows.length
                  ? `+${bundleMissing.hidden} more, not listed here.`
                  : `The server sent no id list.`}
                The complete list, with the shot each id came from, is inside the zip:
                <b>project.json</b> &rarr; <b>missing_media</b>.</div>)}
            <button className="sb-btn ghost sm" style={{ alignSelf: "center" }} onClick={closeBundleMissing}>Close</button>
          </div>
        </div>)}
      {/* sheet rides the Mobile-view toggle: the SAME picker reshapes into the Loom Mobile
          design's bottom sheet (GalleryPicker's .sheet variant) -- the punch-list item was
          that mobile silently reused the desktop modal shape. */}
      {pickCb && (
        <GalleryPicker defaultType={pickKind} showType={pickAllowType} sheet={mobileUI}
          onPick={onGalleryPick} onClose={() => setPickCb(null)} />
      )}
      {importOpen && <ImportCollection onClose={() => setImportOpen(false)} onImport={importCollection} />}

    </div>
  );
}

/* ===================== CARD ===================== */
/* Hover-scrub preview + non-destructive TRIM. Hovering the video maps mouse-X to
   playback time (clamped to the kept region); a track below has draggable in/out
   handles that store trimIn/trimOut (seconds) on the shot. Nothing is re-encoded
   here -- trims are just metadata that Play-sequence and Export will honor.
   /video-file/<id> supports Range requests, so every seek is instant. */
function ShotPreview({ mid, trimIn, trimOut, onTrim, onSplit, crop, onCrop }) {
  const vidRef = useRef(null), trackRef = useRef(null);
  const [dur, setDur] = useState(0);
  const [range, setRange] = useState({ in: trimIn || 0, out: trimOut });
  const [playing, setPlaying] = useState(false);
  // Sound defaults OFF, and that is not timidity: this preview scrubs on hover and a board
  // holds many cards, so audio tied to the element alone would fire from every card the
  // pointer crossed. See the mute effect below for the other half of the rule.
  const [soundOn, setSoundOn] = useState(false);
  const [cropping, setCropping] = useState(false);   // crop-draw mode active
  const rangeRef = useRef(range); rangeRef.current = range;
  const durRef = useRef(0); durRef.current = dur;
  const dragRef = useRef(null);
  useEffect(() => { setRange({ in: trimIn || 0, out: trimOut }); }, [trimIn, trimOut]);
  // Audio only while ACTUALLY PLAYING -- never while scrubbing. Two reasons, and both are the
  // reason this is not simply `v.muted = !soundOn`: this preview seeks on hover
  // (onMouseMove={scrub}), so a hover-scrub is the playhead being thrown around and sounds
  // like noise rather than like the shot; and a board holds many cards, so a pointer crossing
  // it would fire audio from every card it passed over. Applied imperatively because React
  // does not reliably reflect a `muted` prop onto a <video>.
  useEffect(() => {
    const v = vidRef.current;
    if (v) v.muted = !(soundOn && playing);
  }, [soundOn, playing]);
  const effOut = (range.out == null ? dur : range.out) || dur;
  const pct = (s) => (dur ? Math.max(0, Math.min(100, (s / dur) * 100)) : 0);
  const fT = (s) => (s || 0).toFixed(1) + "s";
  const secAt = (clientX) => {
    const t = trackRef.current.getBoundingClientRect();
    return Math.max(0, Math.min(durRef.current, ((clientX - t.left) / t.width) * durRef.current));
  };
  // Hover-scrub is a "not playing" interaction -- while actual playback is running,
  // mouse movement over the frame must not fight it by yanking currentTime around.
  const scrub = (e) => {
    if (playing) return;
    const v = vidRef.current; if (!v || !dur) return;
    const r = e.currentTarget.getBoundingClientRect();
    const t = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    v.currentTime = range.in + t * Math.max(0.01, effOut - range.in);
  };
  const togglePlay = (e) => {
    e.stopPropagation();
    const v = vidRef.current; if (!v) return;
    if (playing) { v.pause(); setPlaying(false); return; }
    if (v.currentTime < range.in || v.currentTime >= effOut) v.currentTime = range.in;
    v.play(); setPlaying(true);
  };
  // Playback honors the trim -- stop (and rewind to the kept range's start) at the
  // trimmed-out point, not the clip's real end, so play always previews what Export
  // would actually keep.
  const onTimeUpdate = (e) => {
    if (playing && e.currentTarget.currentTime >= effOut) {
      e.currentTarget.pause(); e.currentTarget.currentTime = range.in; setPlaying(false);
    }
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
    e.preventDefault(); e.stopPropagation();
    // scrub/mouseLeave already step aside while playing (see their `if (playing) return`
    // guards) so a drag doesn't fight the video's own advancing currentTime -- startDrag
    // needs the same courtesy, or dragging a handle mid-playback visibly yanks the seek
    // position and can trip onTimeUpdate's pause-and-rewind mid-drag.
    if (playing) { const v = vidRef.current; if (v) v.pause(); setPlaying(false); }
    dragRef.current = which;
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };
  // Fast-forward / rewind: nudge the playhead in small hops for framing a split or crop.
  const seek = (delta) => { const v = vidRef.current; if (!v || !dur) return;
    if (playing) { v.pause(); setPlaying(false); }
    v.currentTime = Math.max(0, Math.min(dur, v.currentTime + delta)); };
  // Split: cut this shot in two at the playhead -- the parent makes a second shot pointing
  // at the same clip with the kept range divided here. Only fires strictly inside the kept
  // range so neither half is zero-length.
  const doSplit = () => { const v = vidRef.current; if (!v || !onSplit) return;
    const t = v.currentTime;
    if (t > range.in + 0.15 && t < effOut - 0.15) onSplit(t);
    else alert("Move the playhead to where you want the cut first (not at either edge)."); };
  // Crop: drag a rectangle over the frame; stored as {x,y,w,h} fractions on the card and
  // applied at export via ffmpeg's crop filter. Draw-mode is one-shot (commits on release).
  const cropRef = useRef(null);
  const [cropDraft, setCropDraft] = useState(null);
  const cropStart = (e) => {
    if (!cropping) return;
    e.preventDefault(); e.stopPropagation();
    const box = e.currentTarget.getBoundingClientRect();
    const fx = (cx) => Math.max(0, Math.min(1, (cx - box.left) / box.width));
    const fy = (cy) => Math.max(0, Math.min(1, (cy - box.top) / box.height));
    const x0 = fx(e.clientX), y0 = fy(e.clientY);
    const move = (ev) => { const x1 = fx(ev.clientX), y1 = fy(ev.clientY);
      const r = { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) };
      cropRef.current = r; setCropDraft(r); };
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up);
      const r = cropRef.current;
      if (r && r.w > 0.05 && r.h > 0.05 && onCrop) onCrop(r);
      cropRef.current = null; setCropDraft(null); setCropping(false); };
    window.addEventListener("pointermove", move); window.addEventListener("pointerup", up);
  };
  const shownCrop = cropDraft || crop;   // draft while drawing, else the committed rect
  const trimmed = range.in > 0 || range.out != null;
  return (
    <div className="sb-shotprev-wrap">
      <div className="sb-shotprev" onMouseMove={cropping ? undefined : scrub}
        onMouseLeave={() => { if (playing || cropping) return; const v = vidRef.current; if (v) v.currentTime = range.in; }}>
        <video ref={vidRef} src={"/video-file/" + mid} muted preload="metadata" playsInline
          onLoadedMetadata={(e) => setDur(e.currentTarget.duration || 0)}
          onTimeUpdate={onTimeUpdate} onEnded={() => setPlaying(false)} />
        {shownCrop && <div className="sb-crop-rect" style={{ left: shownCrop.x * 100 + "%", top: shownCrop.y * 100 + "%",
          width: shownCrop.w * 100 + "%", height: shownCrop.h * 100 + "%" }} />}
        {cropping && <div className="sb-crop-layer" onPointerDown={cropStart}>drag to crop</div>}
        {!cropping && <button className="sb-shotprev-play" onClick={togglePlay} title={playing ? "Pause" : "Play"}>{playing ? "⏸" : "▶"}</button>}
        {!cropping && <div className="sb-shotprev-hint">hover to scrub</div>}
      </div>
      <div className="sb-shotprev-ctrls">
        <button onClick={() => seek(-0.25)} title="Rewind (step back)">⏪</button>
        <button onClick={() => seek(0.25)} title="Fast-forward (step ahead)">⏩</button>
        <button className={soundOn ? "on" : ""} onClick={() => setSoundOn((v) => !v)}
          aria-pressed={soundOn}
          title={soundOn ? "Sound on while playing (scrubbing stays silent)" : "Play this shot with sound"}>
          {soundOn ? "\u{1F50A}" : "\u{1F507}"}</button>
        {onSplit && <button onClick={doSplit} title="Split this shot in two at the playhead">✂ Split</button>}
        {onCrop && <button className={cropping ? "on" : ""} onClick={() => { setCropping((v) => !v); setCropDraft(null); }}
          title="Crop the frame — drag a rectangle; applied on export">⛶ Crop</button>}
        {crop && onCrop && <button onClick={() => onCrop(null)} title="Clear crop">clear crop</button>}
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
  // Starts muted so autoplay is never blocked (browsers refuse autoplay WITH sound without
  // a user gesture, and a reel that silently fails to start is worse than one that starts
  // quiet), but the reel is no longer HARD-muted: the exported mp4 carries real audio, so a
  // storyboard used to be reviewable end to end without ever hearing what the render will
  // sound like.
  const [muted, setMuted] = useState(true);
  const clip = clips[i];
  // Applied imperatively, and re-applied on shot change. Both halves are load-bearing:
  // React does not reliably reflect a `muted` JSX prop onto a <video>, so the attribute
  // alone can look right in source and do nothing live; and the element carries
  // key={clip.mid}, so advancing a shot destroys it and a fresh one returns with the
  // initial muted attribute -- without `i` in the deps, unmuting would quietly undo itself
  // at every shot boundary.
  useEffect(() => {
    const v = vRef.current;
    if (v) v.muted = muted;
  }, [muted, i]);
  useEffect(() => {
    const v = vRef.current; if (!v || !clip) return;
    const seekPlay = () => { try { v.currentTime = clip.in || 0; } catch (e) {} v.play().catch(() => {}); };
    const advance = () => { if (i < clips.length - 1) setI(i + 1); else onClose(); };
    const onTime = () => {
      const end = (clip.out != null ? clip.out : v.duration) || 0;
      if (end && v.currentTime >= end - 0.04) advance();
    };
    // Fallback for a stale/out-of-range trimOut (e.g. a clip got replaced by a differently-
    // sized re-roll without its old trim being reset): timeupdate's threshold can then sit
    // past the file's real end and never fire, hanging playback here forever. The browser's
    // own "ended" event still fires once real playback naturally finishes, regardless.
    v.addEventListener("loadedmetadata", seekPlay);
    v.addEventListener("timeupdate", onTime);
    v.addEventListener("ended", advance);
    if (v.readyState >= 1) seekPlay();
    return () => {
      v.removeEventListener("loadedmetadata", seekPlay);
      v.removeEventListener("timeupdate", onTime);
      v.removeEventListener("ended", advance);
    };
  }, [i]);   // eslint-disable-line
  useEffect(() => {
    const esc = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc); return () => window.removeEventListener("keydown", esc);
  }, []);
  if (!clip) return null;
  return (
    <div className="sb-seq" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="sb-seq-box">
        <video ref={vRef} key={clip.mid} src={"/video-file/" + clip.mid} autoPlay muted playsInline
          onClick={(e) => { const v = e.currentTarget; v.paused ? v.play() : v.pause(); }} />
        <div className="sb-seq-bar">
          <span>Shot {i + 1}/{clips.length}{clip.code ? " · " + clip.code : ""}{clip.title ? " — " + clip.title : ""}</span>
          <button className="sb-btn ghost sm" onClick={() => setMuted(!muted)}
            title={muted ? "Unmute — the rendered mp4 has audio" : "Mute"}
            aria-pressed={!muted}>{muted ? "\u{1F507} muted" : "\u{1F50A} sound"}</button>
          <button className="sb-btn ghost sm" onClick={() => setI(Math.max(0, i - 1))} disabled={i === 0}>&#9664; prev</button>
          <button className="sb-btn ghost sm" onClick={() => { if (i < clips.length - 1) setI(i + 1); else onClose(); }}>next &#9654;</button>
          <button className="sb-btn sm" onClick={onClose}>&#10005; close</button>
        </div>
      </div>
    </div>
  );
}


/* ===================== EDITOR ===================== */
/* The gallery picker used to be a self-contained component (GalleryPick) here; it's now
   the shared <mg-gallery-picker> web component (static/mg-gallery-picker.js, mounted via
   bindGalleryPicker above) -- same PickerCore underneath, one renderer instead of two.
   .sb-pick-* CSS below is still used by the Export dialog and ImportCollection. */

/* Import-a-collection dialog: choose a gallery collection, pull its images in as
   reusable @image references (media_id kept -> free at generate). Reuses the same
   /api/collections + /api/gallery-images the picker uses. */
function ImportCollection({ onImport, onClose }) {
  const [colls, setColls] = useState([]);
  const [sel, setSel] = useState("");
  const [total, setTotal] = useState(0);
  const CAP = 48;
  useEffect(() => { fetch("/api/collections").then((r) => r.json())
    .then((d) => setColls(d.collections || [])).catch(() => {}); }, []);
  useEffect(() => {
    if (!sel) { setTotal(0); return; }
    fetch(`/api/gallery-images?type=image&limit=1&collection=${encodeURIComponent(sel)}`)
      .then((r) => r.json()).then((d) => setTotal(d.total || 0)).catch(() => {});
  }, [sel]);
  const doImport = () => {
    if (!sel) return;
    fetch(`/api/gallery-images?type=image&limit=${CAP}&sort=newest&collection=${encodeURIComponent(sel)}`)
      .then((r) => r.json())
      .then((d) => onImport((d.images || []).map((m) => ({ mediaId: m.media_id, name: (m.prompt || "").slice(0, 26) })), sel))
      .catch(() => {});
  };
  return (
    <div className="sb-pick-ov" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="sb-pick-box" style={{ height: "auto", width: 520 }}>
        <div className="sb-pick-head">
          <span className="sb-pick-t">Import a collection</span>
          <button className="sb-pick-x" onClick={onClose} title="Close">&#215;</button>
        </div>
        <p style={{ fontSize: 12.5, color: "var(--ink2)", margin: "0 0 4px", lineHeight: 1.5 }}>
          Pull a gallery collection in as reusable <b>@image</b> references. Each keeps its
          PixAI media_id, so every one generates <b>free</b> &mdash; no re-upload.</p>
        <div className="sb-pick-filters">
          <select value={sel} onChange={(e) => setSel(e.target.value)} style={{ flex: 1, maxWidth: "none" }}>
            <option value="">Choose a collection&hellip;</option>
            {colls.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        {sel && <div style={{ fontSize: 12, color: "var(--ink3)", margin: "6px 0 0" }}>
          {total.toLocaleString()} image{total === 1 ? "" : "s"}{total > CAP ? ` — importing the newest ${CAP}` : ""}</div>}
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 }}>
          <button className="sb-btn ghost sm" onClick={onClose}>Cancel</button>
          <button className="sb-btn amber sm" disabled={!sel} onClick={doImport}>Import references</button>
        </div>
      </div>
    </div>
  );
}

function FrameSlot({ which, frame, liveTag, discreet, framePrev, onPatch, storeThumb, openPick, extraBtn }) {
  const img = framePrev(frame);
  return (
    <div className="sb-frame">
      <div className="sb-framehead">
        <span className="sb-lab">{which === "open" ? "Opening frame" : "Closing frame"}</span>
        {openPick && <button className="sb-ico" title="Pick from the gallery"
          onClick={() => openPick((mid) => onPatch({ mediaId: mid, thumbId: "", source: "" }))}>▤</button>}
        {/* Read-only, DERIVED from this frame's guaranteed live slot (shotImageRefs()/
            positionTag() in loom-core.js), never a free-text field the owner can independently
            edit here. Opening/Closing Frame always reserve the first slot(s) now (see
            loom-core.js's frame-reservation comment), so this is simply "@image1"/"@image2"
            whenever the frame has a resolvable image in this shot, and a dash otherwise --
            never stale text that can drift out of sync with what the composed prompt and the
            Multi-Reference drawer's own bank actually cite for the same picture (the owner's
            2026-07-23 live-test bug: this used to be a plain <input> writing straight into
            frame.tag, a second, independently-settable "@imageN" that could silently disagree
            with the shot's real, live numbering). */}
        <span className="sb-tagin sb-mono" title="This slot's live @imageN — computed from position, not editable">{liveTag || "—"}</span>
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
