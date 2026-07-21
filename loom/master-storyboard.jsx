import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
// Pure, framework-agnostic logic (tag numbering, continuity checks, shot-text
// assembly, reel duration/pricing math) lives in ./src/loom-core.js so it can
// be unit-tested under `node --test` outside React. `shotPayload` is imported
// under an alias because App() wraps it with the component's own `imgSrc`
// (which closes over `thumbs` state) under the ORIGINAL single-arg call shape.
import {
  CONNECT, CONTINUITY_PHRASE, actLetter,
  maxTagNum, nextTag, frameLinked, connectMeta,
  flat, shotText, durOf, reelStats, effectivePrompt,
  priceFingerprint, tallyPrices, formatCostEstimate, costTooltip,
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
} from "./src/loom-mutations.js";

/* =========================================================================
   THE EDIT BAY v2 — reusable Seedance 2.0 storyboard with continuity chaining
   Frame handoff (close-of-N -> open-of-N+1), connection methods, a reusable
   Cast & Assets reference library, and continuity-aware prompt assembly.
   Persists to window.storage. Self-contained.
   ========================================================================= */

const STYLES = `
:root{
  /* Loom palette now INHERITS the gallery's design tokens (pixai_gallery.py's
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
   sans-serif} exactly (pixai_gallery.py) and its ui-monospace,monospace mono
   convention, rather than inventing a new stack. .sb-disp keeps a heavier weight for
   the visual hierarchy Bricolage Grotesque gave, without a fake "semibold" family name. */
.sb-root{font-family:system-ui,sans-serif;background:
  radial-gradient(1200px 600px at 80% -10%,rgba(255,255,255,.05),transparent 60%),var(--bg);
  color:var(--ink);min-height:100vh;padding:0 0 80px;-webkit-font-smoothing:antialiased}
.sb-mono{font-family:ui-monospace,monospace}.sb-disp{font-family:system-ui,sans-serif;font-weight:800}

.sb-topgrid{display:flex;gap:18px;align-items:center;flex-wrap:wrap;max-width:1320px;margin:0 auto}
.sb-brand{display:flex;align-items:baseline;gap:10px;flex:1 1 auto;min-width:0}
.sb-brand h1{font-size:19px;font-weight:800;letter-spacing:-.02em;margin:0;white-space:nowrap}
.sb-clap{color:var(--amber)}
.sb-projname{background:transparent;border:none;border-bottom:1px dashed transparent;color:var(--ink2);
  font:inherit;font-size:14px;padding:2px 4px;min-width:60px;max-width:300px;flex:1 1 auto}
.sb-projname:hover{border-bottom-color:var(--line2)}
.sb-projname:focus{outline:none;border-bottom-color:var(--amber);color:var(--ink)}
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
.sb-stat{display:flex;flex-direction:column;align-items:flex-end;line-height:1.1}
.sb-stat b{font-family:ui-monospace,monospace;font-size:15px}
.sb-stat span{font-size:10px;color:var(--ink3);letter-spacing:.08em;text-transform:uppercase}
.sb-saved{font-size:11px;color:var(--ink3);display:flex;align-items:center;gap:5px}
.sb-dot{width:7px;height:7px;border-radius:50%;background:var(--green);transition:opacity .3s}
.sb-dot.busy{background:var(--amber)}

.sb-reel-wrap{max-width:1320px;margin:12px auto 0;padding:0 2px}
.sb-reel{position:relative;height:30px;background:var(--bg2);border:1px solid var(--line);border-radius:7px;display:flex;overflow:hidden}
.sb-seg{position:relative;min-width:3px;border-right:1px solid rgba(0,0,0,.35);transition:filter .15s}
.sb-seg:hover{filter:brightness(1.35)}
.sb-seg.todo{background:var(--surface1)}.sb-seg.wip{background:linear-gradient(var(--amber),var(--amber-d))}
.sb-seg.done{background:linear-gradient(var(--green),color-mix(in srgb, var(--green) 70%, black))}
.sb-target{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--coral);z-index:4}
.sb-target::after{content:'8:00';position:absolute;top:-15px;left:50%;transform:translateX(-50%);
  font-family:ui-monospace,monospace;font-size:9px;color:var(--coral);white-space:nowrap}
.sb-reel-legend{display:flex;gap:16px;margin-top:18px;font-size:11px;color:var(--ink3);flex-wrap:wrap}
.sb-reel-legend i{width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:5px;vertical-align:middle}

.sb-main{max-width:1320px;margin:22px auto 0;padding:0 20px}
.sb-wrap{max-width:1320px;margin:0 auto;padding:14px 20px}
.sb-toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.sb-divider{flex:1 1 auto}

.sb-act{margin-bottom:30px}
.sb-acthead{display:flex;align-items:center;gap:12px;padding:10px 0;border-bottom:1px solid var(--line);margin-bottom:18px}
.sb-actname{background:transparent;border:none;color:var(--ink);font-family:system-ui,sans-serif;
  font-weight:700;font-size:20px;letter-spacing:-.01em;flex:1 1 auto;min-width:0;padding:2px 0}
.sb-actname:focus{outline:none}
.sb-actcode{font-family:ui-monospace,monospace;font-size:12px;color:var(--amber);
  background:rgba(224,162,78,.1);border:1px solid rgba(224,162,78,.25);border-radius:5px;padding:3px 8px}
.sb-actmeta{font-family:ui-monospace,monospace;font-size:12px;color:var(--ink3)}

.sb-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:16px}

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
.sb-pick-count{margin-left:auto;font-size:11px;color:var(--ink3);font-family:ui-monospace,monospace}
.sb-pick-grid{flex:1;overflow-y:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(118px,1fr));grid-auto-rows:118px;gap:8px;align-content:start}
.sb-pick-cell{position:relative;border-radius:8px;overflow:hidden;border:1px solid var(--line);cursor:pointer;background:var(--panel2)}
.sb-pick-cell:hover{border-color:var(--amber)}
.sb-pick-cell img{width:100%;height:100%;object-fit:cover;display:block}
.sb-pick-vid{position:absolute;top:5px;right:5px;background:rgba(6,4,16,.72);color:var(--ink);font-size:9px;border-radius:4px;padding:1px 6px}
.sb-pick-empty{grid-column:1/-1;color:var(--ink3);text-align:center;padding:34px;font-size:13px}

.sb-fromstrip{display:flex;align-items:center;gap:8px;padding:7px 12px;background:var(--bg2);
  border-bottom:1px solid var(--line);font-size:11px;color:var(--ink3)}
.sb-fromstrip .sb-linkdot{font-size:12px}
.sb-link-ok{color:var(--green)}.sb-link-warn{color:var(--coral)}
.sb-connbadge{font-family:ui-monospace,monospace;font-size:10px;color:var(--cyan);
  border:1px solid rgba(111,184,178,.4);border-radius:4px;padding:1px 6px;margin-left:auto}

.sb-slate{display:flex;align-items:center;gap:10px;padding:11px 13px;
  background:repeating-linear-gradient(45deg,var(--panel),var(--panel) 9px,var(--bg) 9px,var(--bg) 18px);
  border-bottom:1px solid var(--line)}
.sb-code{font-family:ui-monospace,monospace;font-weight:700;font-size:13px;color:var(--amber);
  background:var(--base);border:1px solid var(--line2);border-radius:5px;padding:3px 7px;white-space:nowrap}
.sb-ctitle{flex:1 1 auto;min-width:0;background:transparent;border:none;color:var(--ink);font:inherit;
  font-weight:600;font-size:14px;padding:2px 0;text-overflow:ellipsis}
.sb-ctitle:focus{outline:none}
.sb-mode{font-family:ui-monospace,monospace;font-size:10px;color:var(--cyan);
  border:1px solid rgba(111,184,178,.4);border-radius:4px;padding:2px 5px}
.sb-tc{font-family:ui-monospace,monospace;font-size:12px;color:var(--ink2)}
.sb-tick{width:22px;height:22px;border-radius:6px;border:1.5px solid var(--line2);background:transparent;
  cursor:pointer;flex:none;display:grid;place-items:center;color:transparent;transition:all .12s;padding:0}
.sb-tick.wip{border-color:var(--amber);color:var(--amber)}
.sb-tick.done{border-color:var(--green);background:var(--green);color:var(--base)}
.sb-tick.error{border-color:var(--coral);color:var(--coral)}

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
.sb-tagin{font-family:ui-monospace,monospace;font-size:11px;color:var(--cyan);background:var(--base);
  border:1px solid var(--line2);border-radius:5px;padding:3px 6px;width:90px}

.sb-pal{display:flex;flex-wrap:wrap;gap:5px;margin-top:4px}
.sb-palgrp{width:100%;font-size:9px;letter-spacing:.08em;text-transform:uppercase;color:var(--ink3);margin-top:5px}
.sb-pchip{font-family:ui-monospace,monospace;font-size:10.5px;color:var(--ink2);background:var(--bg2);
  border:1px solid var(--line);border-radius:5px;padding:3px 7px;cursor:pointer;transition:all .1s}
.sb-pchip:hover{border-color:var(--amber);color:var(--amber)}

.sb-casttoggle{display:flex;flex-wrap:wrap;gap:6px}
.sb-castchip{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;border:1px solid var(--line2);
  background:var(--panel2);color:var(--ink2);border-radius:20px;padding:4px 10px;cursor:pointer}
.sb-castchip.on{border-color:var(--cyan);color:var(--cyan);background:rgba(111,184,178,.1)}
.sb-castchip .sb-ct{font-family:ui-monospace,monospace;font-size:9px;opacity:.8}

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
.sb-add{width:100%;border:1.5px dashed var(--line2);background:transparent;color:var(--ink3);border-radius:11px;padding:14px;font:inherit;font-size:13px;cursor:pointer;transition:all .12s}
.sb-add:hover{border-color:var(--amber);color:var(--amber)}

.sb-panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-top:12px}
.sb-panelhead{display:flex;align-items:center;gap:10px;padding:12px 16px;cursor:pointer}
.sb-panelhead h3{margin:0;font-family:system-ui,sans-serif;font-size:15px;font-weight:700}
.sb-panelbody{padding:0 16px 16px;display:flex;flex-direction:column;gap:10px}
.sb-assetrow{display:flex;gap:10px;align-items:center;background:var(--bg2);border:1px solid var(--line);border-radius:9px;padding:9px}
.sb-assetprev{width:54px;height:42px;border-radius:6px;border:1px solid var(--line2);background:var(--panel2);
  flex:none;display:grid;place-items:center;font-size:16px;cursor:pointer;overflow:hidden}
.sb-assetprev img{width:100%;height:100%;object-fit:cover}.sb-assetprev.discreet img{filter:blur(8px)}

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

const uid = () => Math.random().toString(36).slice(2, 9);
const fmt = (s) => { s = Math.max(0, Math.round(s || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };
// Module scope (not a local inside useGenerationPipeline) because both pollShot (inside that
// hook) and onVideoSlow/onVideoPaused (inside App(), a different function entirely) need it.
const elapsedLabel = (ms) => ms < 3600000 ? Math.round(ms / 60000) + "m" : (Math.round(ms / 360000) / 10) + "h";
const emptyFrame = () => ({ thumbId: "", source: "", desc: "", tag: "" });
// CONNECT, CONTINUITY_PHRASE, actLetter, maxTagNum/nextTag, frameLinked, and
// connectMeta now live in ./src/loom-core.js (imported above) -- Phase 1
// tooling pass, 2026-07-16.

/* ---------- storage ---------- */
const hasStore = typeof window !== "undefined" && window.storage;
const PKEY = "storyboard:v2:project";        // legacy single-project key — migrated into PPRE on first load
const PPRE = "storyboard:v2:proj:";          // one KV key per saved storyboard: PPRE + id
const ACTIVE_KEY = "storyboard:v2:active";   // id of the storyboard currently open
const TPRE = "storyboard:v2:thumb:";
async function sGet(k) { try { const r = await window.storage.get(k); return r ? r.value : null; } catch { return null; } }
async function sSet(k, v) { try { await window.storage.set(k, v, false); } catch (e) { console.error(e); } }
async function sList(p) { try { const r = await window.storage.list(p, false); if (!r) return []; return (r.keys || []).map((k) => (typeof k === "string" ? k : k.key)); } catch { return []; } }
async function sDel(k) { try { await window.storage.delete(k); } catch (e) { console.error(e); } }

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
// Locked design source: docs/ROADMAP_LOOM_ACHIEVEMENTS.md §1 + the two owner-approved
// mockup artifacts (e41a3020 full shell, 84be1748 Timeline-only wireframe).
const V2_STYLES = `
.lv-overlay{position:fixed;inset:0;z-index:400;background:var(--base);display:flex;flex-direction:column;}
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
/* Fixed 4-region shell: top Timeline drawer (below), then a row of left card /
   board column / right drawer -- nothing free-floating, nothing draggable. */
.lv-shell{flex:1;display:flex;min-height:0;overflow:hidden;}
.lv-side{flex:none;background:var(--surface0);display:flex;flex-direction:column;min-height:0;
  transition:width .18s ease;overflow-x:hidden;}
.lv-side.left{width:280px;border-right:1px solid var(--surface1);}
.lv-side.left.wide{width:560px;}
.lv-side.right{width:560px;border-left:1px solid var(--surface1);}
.lv-side.collapsed{width:52px;}
.lv-sidehead{flex:none;display:flex;align-items:center;gap:8px;padding:8px;border-bottom:1px solid var(--surface1);}
.lv-sidetabs{flex:1;min-width:0;margin-bottom:0;}
.lv-col{width:22px;height:20px;border:1px solid var(--surface1);background:var(--base);color:var(--subtext);
  border-radius:5px;cursor:pointer;font-size:11px;flex:0 0 auto;}
.lv-col:hover{color:var(--accent);}
.lv-railicons{flex:1;min-height:0;display:flex;flex-direction:column;align-items:center;gap:7px;padding:10px 0;width:100%;overflow:auto;}
.lv-railbtn{width:38px;height:38px;border:1px solid var(--surface1);background:var(--base);color:var(--subtext);
  border-radius:8px;cursor:pointer;font-size:17px;line-height:1;flex:0 0 auto;}
.lv-railbtn:hover{border-color:var(--accent);color:var(--accent);}
.lv-railbtn.on{border-color:var(--accent);color:var(--accent);background:color-mix(in srgb,var(--accent) 14%,var(--base));}
.lv-boardcol{flex:1;min-width:0;overflow:auto;background:var(--base);}
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
.lv-actname{font:700 10px/1 system-ui;text-transform:uppercase;letter-spacing:.06em;color:var(--accent);margin:2px 0 7px;}
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
.lv-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(122px,1fr));gap:8px;}
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
.lv-reel{position:relative;flex:1;min-height:40px;display:flex;background:var(--base);border:1px solid var(--surface1);border-radius:7px;overflow:hidden;}
.lv-seg{position:relative;min-width:3px;border-right:1px solid rgba(0,0,0,.35);cursor:pointer;}
.lv-seg.todo{background:var(--surface1);}.lv-seg.wip{background:var(--amber);}.lv-seg.done{background:var(--green);}.lv-seg.error{background:var(--coral);}
.lv-seg.sel{outline:2px solid var(--accent);outline-offset:-2px;z-index:2;}
.lv-target{position:absolute;top:0;bottom:0;width:2px;background:var(--accent);opacity:.7;}
.lv-tlinfo{font-size:11px;color:var(--text);}
.lv-dim{color:var(--subtext);font-style:italic;}
.lv-gen{flex:1;min-height:0;overflow-y:auto;padding:10px;}
.lv-genhead{font:700 13px/1.2 system-ui;color:var(--text);margin-bottom:6px;display:flex;align-items:center;gap:8px;}
.lv-unbind{margin-left:auto;flex:none;font:600 10px/1 system-ui;background:var(--surface1);border:1px solid var(--surface1);
  color:var(--subtext);border-radius:6px;padding:4px 8px;cursor:pointer;}
.lv-unbind:hover{border-color:var(--accent);color:var(--accent);}
.lv-framehandoff{display:flex;gap:8px;align-items:flex-start;margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid var(--surface1);}
.lv-framehandoff .sb-frame{flex:1 1 0;min-width:0;}
/* The @tag input (.sb-tagin) is 90px in classic Loom's own wide layout -- too wide for
   a frame-slot header squeezed into this narrower drawer, which is what actually caused
   the side-scroll. Narrower here only; classic Loom keeps its own room to spare. */
.lv-framehandoff .sb-framehead{flex-wrap:nowrap;}
.lv-framehandoff .sb-tagin{width:62px;}
.lv-framehandoff .sb-frameprev{height:64px;}
.lv-lab{font:700 9px/1 system-ui;text-transform:uppercase;letter-spacing:.05em;color:var(--subtext);display:block;margin:9px 0 5px;}
.lv-check{display:flex;align-items:center;gap:6px;font:600 11px/1 system-ui;color:var(--text);margin:9px 0 5px;cursor:pointer;user-select:none;}
.lv-check input{margin:0;cursor:pointer;}
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
.lv-note2{font-size:9px;color:var(--subtext);font-style:italic;margin-top:8px;text-align:center;}
.lv-cframe{height:48px;border-radius:5px;overflow:hidden;background:var(--base);border:1px solid var(--surface1);display:flex;align-items:center;justify-content:center;margin-bottom:5px;}
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
.lv-castitem{display:flex;gap:8px;align-items:center;padding:5px;border-radius:7px;border:1px solid transparent;cursor:pointer;}
.lv-castitem:hover{background:var(--surface1);}
.lv-castitem.on{border-color:var(--accent);background:color-mix(in srgb,var(--accent) 10%,transparent);}
.lv-castitem img{width:34px;height:34px;border-radius:6px;object-fit:cover;flex:0 0 auto;}
.lv-castph{width:34px;height:34px;border-radius:6px;background:var(--surface1);flex:0 0 auto;}
.lv-castmeta b{font:700 10px/1 ui-monospace,monospace;color:var(--accent);display:block;}
.lv-castmeta span{font-size:10px;color:var(--subtext);}
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
.lv-in:focus{outline:0;border-color:var(--accent);}
.lv-mini{display:flex;flex-wrap:wrap;gap:4px;margin-top:5px;}
.lv-minichip{font-size:9px;color:var(--subtext);background:var(--base);border:1px solid var(--surface1);border-radius:5px;padding:2px 5px;cursor:pointer;}
.lv-minichip:hover{border-color:var(--accent);color:var(--accent);}
.lv-refline{font-size:10px;color:var(--subtext);margin:10px 0 4px;}
/* Draft-mode "route into a shot" picker -- shown only with no shot selected. */
.lv-drafttarget{margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid var(--surface1);}
.lv-drafttarget select.lv-sel{display:block;width:100%;flex:none;padding:7px 8px;font-size:11px;}
.lv-mini2{font-size:9px;color:var(--subtext);background:var(--base);border:1px solid var(--surface1);border-radius:5px;padding:3px 7px;cursor:pointer;margin:5px 0;}
.lv-mini2:hover{border-color:var(--accent);color:var(--accent);}
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
.lv-df-frames{display:flex;gap:12px;align-items:flex-start;margin-top:14px;}
.lv-df-frames .sb-frame{flex:1 1 0;min-width:0;}
.lv-gerr{font-size:10px;color:var(--coral);margin-top:6px;}
.lv-bal{font-size:10.5px;color:var(--text);padding:5px 0 3px;border-bottom:1px solid var(--surface1);margin-bottom:9px;letter-spacing:.02em;opacity:.85;}
.lv-balclaim{color:var(--accent);}
.lv-editsrc{max-width:100%;max-height:120px;border-radius:8px;border:1px solid var(--surface1);margin:4px 0;display:block}
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

function LoomV2({ project, setCard, setAssets, entries, durOf, scale, selShot, setSelShot, generateShot, useExistingVideo, genState, thumbs, openPick, storeThumb, setAct, addCard, dupCard, delCard, moveCard, moveCardToAct, addAct, delAct, moveAct, genImgState, imgModel, setImgModel, genImage, routeImg, genEditState, setGenEditState, genRefState, setGenRefState, genEdit, genRef, routeGen, projectApi, playSequence, exportCut, batching, batchGenerate, addRef, setRef, delRef, exportAll, exportJSON, exportBundle, bundling, importBackup, setImportOpen, copyShot, setLook, setDraft, splitShot, onVideoSubmit, onVideoResult, onVideoError, onVideoSlow, onVideoPaused, pollShot, costEstimate, refreshEstimate, batchTally }) {
  const [tab, setTab] = useState("Video");
  const [acct, setAcct] = useState(null);  // credits/cards for the inline balance line
  const [handoff, setHandoff] = useState("");   // frame-handoff splice state: '', 'wip', 'err'
  const [deepFocus, setDeepFocus] = useState(null);   // entry {a,c,ai,ci,code} double-clicked on the board, or null
  // Deep Focus's own body is an IIFE inside a conditional render (below), not a component or
  // hook -- calling useState there would violate the rules of hooks (conditional hook call).
  // This state belongs to Deep Focus but has to live up here, at LoomV2's real top level, same
  // as deepFocus itself; the IIFE below only reads/writes it via closure.
  const [dfPalFor, setDfPalFor] = useState(null);     // which term-palette is open in Deep Focus, or null
  const [leftTab, setLeftTab] = useState("cast");        // 'cast' | 'footage'
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [density, setDensity] = useState("detailed");    // 'simple' | 'detailed' -- Cast tab only
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [tlState, setTlState] = useState("slim");        // 'hidden' | 'slim' | 'full'
  const [tlDragH, setTlDragH] = useState(null);          // live px height while dragging the handle, else null
  const [palFor, setPalFor] = useState(null);            // which field's "+ terms" popover is open, or null
  const [dzHover, setDzHover] = useState(false);          // footage drop-zone hover feedback
  const [overrideClearedFlash, setOverrideClearedFlash] = useState(false);   // brief notice when the native Prompt field destroys an active override
  // Draft generation: the Generate drawer works with no shot selected, exactly like the
  // main gallery's own drawer -- a "card" that lives in component state instead of the
  // project, generation-state dicts keyed by its "__draft__" id right alongside real shots'.
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
  // Bridge the shared <mg-model-picker> web component to React: a ref callback (React
  // doesn't route custom events through JSX props) that binds the 'mg-pick' listener once.
  const bindPicker = useCallback((el) => {
    if (el && !el._mgBound) {
      el._mgBound = true;
      el.addEventListener("mg-pick", (e) => setImgModel({ model_id: e.detail.model_id, title: e.detail.title }));
    }
  }, [setImgModel]);
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
      el.addEventListener("mg-pick-request", (e) => {
        openPick((mid, thumb) => e.detail.respond(mid, thumb), e.detail.kind === "video" ? "video" : "image");
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
        const composed = already ? null : shotText(a, projectRef.current);
        if (!already && text === composed) return;
        const apply = (c) => setPromptOverride(c, text);
        a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
        promptDirtyRef.current = false;
      });
    }
  }, [openPick, onVideoSubmit, onVideoResult, onVideoError, onVideoSlow, onVideoPaused]);

  // Fixed Timeline drawer: hidden(0) / slim(default, scrubber only) / full(preview above
  // scrubber, real 16:9). The handle drags freely between 0 and TL_HEIGHTS.full, snapping
  // to the nearest named state on release -- same mechanic as the owner-approved mockup.
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
    : (source && (source.startsWith("http") || source.startsWith("data:") || /^\d+$/.test(source)) ? source : null);
  const asRef = (d) => ({ media_id: d, thumb: /^\d+$/.test(d) ? ("/thumbs/" + d + ".jpg") : d });
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
            const composed = already ? null : shotText(outEntry, project);
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
      payload.images = [active.c.openFrame, active.c.closeFrame].filter((f) => f && f.mediaId)
        .map((f) => ({ media_id: f.mediaId, thumb: frameSrc(f) }));
    } else if (nextMode === "r2v") {
      const sp = buildShotPayload(active, project, imgSrc);
      payload.images = sp.images.map(asRef);
      const vids = (sp.video_refs || []).map(asRef);
      if (active.c.connect === "extend" && weavePrevEntry && weavePrevEntry.c.resultMid) {
        vids.push({ media_id: weavePrevEntry.c.resultMid, thumb: "/thumbs/" + weavePrevEntry.c.resultMid + ".jpg" });
      }
      payload.video_refs = vids;
    }
    if (!promptDirtyRef.current) payload.prompt = shotText(active, project);
    el.prefill(payload);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active.c.id, active.c.mode, active.c.connect, active.c.duration, active.c.audioGen, active.c.audioLanguage,
      active.c.prompt, active.c.camera, active.c.lighting, active.c.transIn, active.c.transOut,
      active.c.cast, active.c.refs, project.assets,
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
                return (
                  <div key={e.c.id} className={"lv-card " + (e.c.id === selShot ? "sel" : "")} onClick={() => setSelShot(e.c.id)}
                    onDoubleClick={() => setDeepFocus(e)} title="Double-click to open in Deep Focus">
                    <div className="lv-cframe">{(() => { const s = frameSrc(e.c.openFrame) || (e.c.resultMid ? "/thumbs/" + e.c.resultMid + ".jpg" : null); return s ? <img src={s} alt="" /> : <span className="lv-cframeph">{e.c.mode}</span>; })()}</div>
                    <div className="lv-code">{e.code}</div>
                    <div className="lv-ctitle">{e.c.title || "untitled"}</div>
                    <div className="lv-cmeta"><span className="lv-mode">{e.c.mode}</span><span className="lv-dur">{durOf(e.c)}s</span>
                      <span className={"lv-st " + st}
                        onClick={paused ? (ev) => { ev.stopPropagation(); pollShot(e.c.id, e.c.pendingTaskId); } : undefined}
                        style={paused ? { cursor: "pointer" } : undefined}
                        title={paused ? "Click to check again" : undefined}>
                        {gs && gs.msg ? gs.msg : st}</span></div>
                    <div className="lv-crow" onClick={(ev) => ev.stopPropagation()} onDoubleClick={(ev) => ev.stopPropagation()}>
                      <button className="lv-ico xs" onClick={() => moveCard(act.id, e.ci, -1)} title="Move up">&#8593;</button>
                      <button className="lv-ico xs" onClick={() => moveCard(act.id, e.ci, 1)} title="Move down">&#8595;</button>
                      <button className="lv-ico xs" onClick={() => dupCard(act.id, e.c)} title="Duplicate">&#10697;</button>
                      <button className="lv-ico xs danger" onClick={() => delCard(act.id, e.c)} title="Delete">&#10005;</button>
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
            {entries.map((x, i) => (<div key={i} className={"lv-seg " + x.c.status + (x.c.id === selShot ? " sel" : "")}
              style={{ width: `${(durOf(x.c) / scale) * 100}%` }} title={`${x.code} ${x.c.title || ""}`} onClick={() => setSelShot(x.c.id)} />))}
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
            const composed = shotText({ ...active, c: { ...active.c, promptOverride: false } }, project);
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
          <label className="lv-lab">Model {imgModel ? <span className="lv-dim">· {imgModel.title}</span> : null}</label>
          <mg-model-picker ref={bindPicker} kind="base"></mg-model-picker>
          <label className="lv-lab">Image prompt</label>
          <textarea className="lv-ta" value={active.c.imgPrompt || ""} placeholder="describe the reference still (subject, pose, composition, light)…"
            onChange={(ev) => patch((c) => ({ ...c, imgPrompt: ev.target.value }))} />
          {sel && <button className="lv-mini2" onClick={() => patch((c) => ({ ...c, imgPrompt: [c.title, c.prompt, (c.openFrame && c.openFrame.desc) || "", c.lighting || ""].filter(Boolean).join(", ") }))}>&#8615; seed from shot description</button>}
          <button className="lv-go" disabled={busyI} onClick={() => genImage(active)}>{busyI ? (gi.msg || "generating…") : "✦ Generate reference image"}</button>
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
      tabBody = (
        <div>
          <label className="lv-lab">Source — {sel ? "this shot's" : "the draft's"} open frame</label>
          {src ? <img className="lv-editsrc" src={"/thumbs/" + src + ".jpg"} alt="source" />
               : <div className="lv-ph">No open-frame image yet — {sel ? <>route one from the <b>Image</b> tab, or </> : null}pick it into the open frame above.</div>}
          <label className="lv-lab">Edit instruction</label>
          <textarea className="lv-ta" value={active.c.editPrompt || ""} placeholder="e.g. make it night, add rain, warmer key light…"
            onChange={(ev) => patch((c) => ({ ...c, editPrompt: ev.target.value }))} />
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
        <div className="lv-framehandoff">
          <FrameSlot which="open" frame={active.c.openFrame} discreet={active.c.discreet} framePrev={frameSrc} storeThumb={storeThumb} openPick={openPick}
            onPatch={(p) => patchFrame("openFrame", p)}
            extraBtn={prevEntry ? <button className="sb-btn ghost sm" onClick={inheritPrev} disabled={handoff === "wip"}
                title={prevEntry.c.resultMid ? `Splice in ${prevEntry.code}'s generated clip's last frame` : `Copy ${prevEntry.code}'s closing frame here`}>
                {handoff === "wip" ? "✂ splicing…" : handoff === "err" ? "✂ splice failed — retry"
                  : prevEntry.c.resultMid ? `✂ splice ${prevEntry.code}'s last frame` : `↳ inherit ${prevEntry.code} close`}</button>
              : <span className="sb-hint">{sel ? "first shot — no previous frame" : "draft — no shot sequence to inherit from"}</span>} />
          <div className="sb-conn-mid">&#8594;</div>
          <FrameSlot which="close" frame={active.c.closeFrame} discreet={active.c.discreet} framePrev={frameSrc} storeThumb={storeThumb} openPick={openPick}
            onPatch={(p) => patchFrame("closeFrame", p)} />
        </div>
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
        <mg-generate-drawer ref={bindGenDrawer} style={{ display: tab === "Video" ? "" : "none" }}></mg-generate-drawer>
        {videoTrailer}
      </div>
    );
  }
  const castList = (
    <>
      <div className="lv-castrow-h">Cast &amp; assets{sel ? <span className="lv-dim"> — bound to {sel.code}</span> : null}</div>
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
        return (
          <div key={as.id} className="lv-assetrow">
            {as.kind !== "audio" && <button className="lv-pickico" title="Pick from your gallery"
              onClick={() => openPick((mid) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, thumbId: "", source: "", mediaId: mid })), as.kind === "video" ? "video" : "image")}>🖼</button>}
            {as.kind === "image" ? (
              <label className="lv-assetprev" title="Attach image">
                {src ? <img src={src} alt="" /> : "＋"}
                <input type="file" accept="image/*" style={{ display: "none" }}
                  onChange={async (e) => { const f = e.target.files[0]; if (!f) return; const id = await storeThumb(f);
                    setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, thumbId: id, source: x.source || f.name, mediaId: "" })); }} />
              </label>
            ) : <div className="lv-assetprev">{as.kind === "video" ? "🎞" : "♪"}</div>}
            <input className="lv-in" style={{ flex: "1 1 100px" }} value={as.name} placeholder="name"
              onChange={(e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, name: e.target.value }))} />
            <input className="lv-tagin" value={as.tag}
              onChange={(e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, tag: e.target.value }))} />
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
          return (
            <div key={as.id} className={"lv-simplecard " + (inShot ? "on " : "") + (!sel ? "nosel" : "")}
              title={sel ? `Toggle into ${sel.code}` : "Select a shot on the board to toggle its cast"}
              onClick={() => sel && setCard(sel.a.id, sel.c.id, (c) => ({ ...c, cast: (c.cast || []).includes(as.id) ? c.cast.filter((x) => x !== as.id) : [...(c.cast || []), as.id] }))}>
              {src ? <img src={src} alt="" /> : <span className="lv-castph" />}
              <b>{as.name || as.kind}</b><span className="lv-dim">{as.tag}</span>
            </div>
          );
        })}</div>
      )}
      {!(project.assets || []).length && <div className="lv-ph">No cast yet — add one below.</div>}
      <button className="lv-addcast" onClick={() => openPick((mid, thumb, isVideo) => setAssets((a) => {
        const k = isVideo ? "video" : "image", pre = isVideo ? "@video" : "@image";
        return [...a, { id: uid(), name: "", kind: k, tag: nextTag(a, pre), thumbId: "", source: "", mediaId: mid, lock: false }];
      }), "image", true)}>+ add from gallery</button>
      <button className="lv-addcast" onClick={() => setImportOpen(true)}
        title="Pull a whole gallery collection in as reusable @image references">&#8623; Import collection</button>
    </>
  );
  const finished = entries.filter((e) => e.c.resultMid);
  // Dropped/browsed footage becomes a reusable Cast & Assets reference -- "footage" itself
  // means "this project's own rendered shots" (keyed off resultMid), so external media has
  // nowhere else honest to land. addAssetFromFile only handles images; video files are
  // directed to "Browse library" instead of a half-built local-video-upload path.
  const addAssetFromFile = async (file) => {
    if (!file || !file.type || !file.type.startsWith("image/")) return;
    const id = await storeThumb(file);
    setAssets((a) => [...a, { id: uid(), name: "", kind: "image", tag: nextTag(a, "@image"), thumbId: id, source: file.name, lock: false }]);
  };
  const footageList = (
    <>
      <div className="lv-footagehead">
        <span className="lv-castrow-h">Finished shots</span>
        <button className="lv-browsebtn" onClick={() => openPick((mid, thumb, isVideo) => setAssets((a) => {
          const k = isVideo ? "video" : "image", pre = isVideo ? "@video" : "@image";
          return [...a, { id: uid(), name: "", kind: k, tag: nextTag(a, pre), thumbId: "", source: "", mediaId: mid, lock: false }];
        }), "video", true)}>&#8981; Browse library</button>
      </div>
      {finished.length
        ? <div className="lv-footage">{finished.map((e) => (
            <div key={e.c.id} className={"lv-fclip " + (e.c.id === selShot ? "sel" : "")} onClick={() => setSelShot(e.c.id)}>
              <img src={"/thumbs/" + e.c.resultMid + ".jpg"} alt="" />
              <div className="lv-fmeta"><b>{e.code}</b><span>{durOf(e.c)}s</span></div>
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

  return (
    <div className="lv-overlay">
      <style>{V2_STYLES}</style>
      <div className="lv-top">
        <span className="lv-eyebrow">The Loom · V2</span>
        <span className="lv-note">Click a shot → it binds to Generate.</span>
        <ProjectSwitcher api={projectApi} />
        <label className={"lv-draft" + (project.draft ? " on" : "")}
          title="Draft mode renders every shot at the cheaper 'basic' quality — block out the animatic, then turn Draft off and re-generate the keepers at pro quality">
          <input type="checkbox" checked={!!project.draft} onChange={(e) => setDraft(e.target.checked)} />⚡ Draft</label>
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
            const composed = already ? null : shotText(a, project);
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
          title="Trim + stitch every finished shot into one mp4 (ffmpeg)">&#8681; Export</button>
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
        <div className={"lv-side left" + (leftCollapsed ? " collapsed" : "") + (!leftCollapsed && leftTab === "cast" && density === "detailed" ? " wide" : "")}>
          <div className="lv-sidehead">
            {!leftCollapsed && (
              <div className="lv-tabs lv-sidetabs">
                <span className={"lv-tab " + (leftTab === "cast" ? "on" : "")} onClick={() => setLeftTab("cast")}>Cast &amp; assets</span>
                <span className={"lv-tab " + (leftTab === "footage" ? "on" : "")} onClick={() => setLeftTab("footage")}>Footage</span>
              </div>
            )}
            <button className="lv-col" onClick={() => setLeftCollapsed((v) => !v)} title="collapse">{leftCollapsed ? "▸" : "◂"}</button>
          </div>
          {leftCollapsed ? (
            <div className="lv-railicons">
              <button className={"lv-railbtn" + (leftTab === "cast" ? " on" : "")} title="Cast & assets" onClick={() => { setLeftTab("cast"); setLeftCollapsed(false); }}>&#128100;</button>
              <button className={"lv-railbtn" + (leftTab === "footage" ? " on" : "")} title="Footage" onClick={() => { setLeftTab("footage"); setLeftCollapsed(false); }}>&#127916;</button>
            </div>
          ) : (
            <div className="lv-cast">{leftTab === "cast" ? castList : footageList}</div>
          )}
        </div>

        <div className="lv-boardcol">{board}</div>

        <div className={"lv-side right" + (rightCollapsed ? " collapsed" : "")}>
          <div className="lv-sidehead">
            <button className="lv-col" onClick={() => setRightCollapsed((v) => !v)} title="collapse">{rightCollapsed ? "◂" : "▸"}</button>
            {!rightCollapsed && (
              <div className="lv-tabs lv-sidetabs">{["Image", "Edit", "Reference", "Video"].map((t) => (
                <span key={t} className={"lv-tab " + (t === tab ? "on" : "")} onClick={() => setTab(t)}>{t}</span>))}</div>
            )}
          </div>
          {rightCollapsed ? (
            <div className="lv-railicons">
              {GEN_ICONS.map(([t, ic]) => (<button key={t} className={"lv-railbtn" + (t === tab ? " on" : "")} title={t}
                onClick={() => { setTab(t); setRightCollapsed(false); }}>{ic}</button>))}
            </div>
          ) : gen}
        </div>
      </div>
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
              <div className="lv-df-frames">
                <FrameSlot which="open" frame={c.openFrame} discreet={c.discreet} framePrev={frameSrc} storeThumb={storeThumb} openPick={openPick}
                  onPatch={(p) => dfPatchFrame("openFrame", p)} />
                <div className="sb-conn-mid">&#8594;</div>
                <FrameSlot which="close" frame={c.closeFrame} discreet={c.discreet} framePrev={frameSrc} storeThumb={storeThumb} openPick={openPick}
                  onPatch={(p) => dfPatchFrame("closeFrame", p)} />
              </div>
              <div className="sb-field">
                <label className="sb-lab">Other references &amp; @tags</label>
                {c.refs.map((r) => {
                  const preview = r.thumbId ? thumbs[r.thumbId] : (r.kind === "image" && r.source.startsWith("http") ? r.source : null);
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
    // A pending 600ms autosave timer for THIS project can otherwise fire during the
    // awaits below (sGet/sDel/sSet all hit the network) and re-create the very key
    // sDel just removed, silently resurrecting a "permanently deleted" board.
    clearTimeout(saveTimer.current);
    if (id === activeId) {
      // Switch to a survivor WITHOUT flushing the doomed project first — openProject()'s
      // flushSave(activeId) would re-create the very project we're deleting.
      const next = list.find((x) => x.id !== id);
      let p = null; try { const raw = await sGet(PPRE + next.id); if (raw) p = JSON.parse(raw); } catch {}
      await sDel(PPRE + id);
      await sSet(ACTIVE_KEY, next.id);
      setActiveId(next.id); setProject(p || seedProject()); setSelShot(null);
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
    const ids = parseCastIdsFromSearch(location.search);
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
    addCard, dupCard, delCard, moveCard, moveCardToAct, addAct, delAct, moveAct,
    addRef, setRef, delRef, splitShot };
}

// ---- 3. useGenerationPipeline: generate/poll/route across all four modes ----
function useGenerationPipeline({ project, thumbs, setCard, setCardStatus, setAssets, openPick, activeId }) {
  const [genState, setGenState] = useState({});         // cardId -> {phase, msg, mid} (video)
  const resumedRef = useRef({});    // taskId -> true: shots whose interrupted poll we've re-attached this session
  const [genImgState, setGenImgState] = useState({});   // shotId -> {phase,msg,mid,routed} (in-Loom image ref-gen)
  const [imgModel, setImgModel] = useState(null);        // {model_id,title} for reference-image gen
  const [genEditState, setGenEditState] = useState({});  // shotId -> {phase,msg,mid,routed} (in-Loom instruct-edit)
  const [genRefState, setGenRefState] = useState({});    // shotId -> {...} (multi-reference gen)
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
    : (source && (source.startsWith("http") || source.startsWith("data:") || /^\d+$/.test(source)) ? source : null);
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
      setGenState((s) => ({ ...s, [c.id]: { phase: "error", msg: "attach a frame or cast image first" } }));
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
  // and unrecoverable short of a fresh submit. The owner's own motivating case (a render that
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
      } else if (cls.phase === "failed") {
        setGenState((s) => ({ ...s, [cardId]: { phase: "error", msg: cls.msg } }));
        setCardStatus(cardId, { status: "error", pendingTaskId: null, genStartedAt: null });
        setBatchOutcome(cardId, "failed");
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
  useEffect(() => {
    if (!project) return;   // project is null until the store loads the first board
    (project.acts || []).forEach((a) => (a.cards || []).forEach((c) => {
      if (c.status === "wip" && c.pendingTaskId && !resumedRef.current[c.pendingTaskId]) {
        resumedRef.current[c.pendingTaskId] = true;
        pollShot(c.id, c.pendingTaskId, c.genStartedAt);
      }
    }));
  }, [activeId]);   // eslint-disable-line
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
      if (cls.phase === "done") setState((s) => ({ ...s, [cardId]: { phase: "done", msg: "Done", mid: cls.mid } }));
      else if (cls.phase === "failed") setState((s) => ({ ...s, [cardId]: { phase: "error", msg: cls.msg } }));
      else again(4000);
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
    if (!(await confirmSpend({ model_id: imgModel.model_id, prompt }, `Generate a reference image for ${c.title || "this shot"}?`))) return;
    setGenImgState((s) => ({ ...s, [c.id]: { phase: "submitting", msg: "Submitting…" } }));
    try {
      const r = await fetch("/api/generate", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model_id: imgModel.model_id, prompt }) });
      const d = await r.json();
      if (d.error || !d.task_id) { setGenImgState((s) => ({ ...s, [c.id]: { phase: "error", msg: (d.error ? friendlyGenErr(d.error) : "submit failed") } })); return; }
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
  const runGen = async (setState, cardId, endpoint, body, priceBody, label) => {
    if (priceBody && !(await confirmSpend(priceBody, label))) return;
    setState((s) => ({ ...s, [cardId]: { phase: "submitting", msg: "Submitting…" } }));
    // Same unbounded-loop fix as pollImg -- see pollTaskWithCeiling's comment.
    const poll = (tid) => pollTaskWithCeiling(tid, setState, cardId);
    try {
      const r = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const d = await r.json();
      if (d.error || !d.task_id) { setState((s) => ({ ...s, [cardId]: { phase: "error", msg: (d.error ? friendlyGenErr(d.error) : "submit failed") } })); return; }
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
      `Edit the open frame of ${c.title || "this shot"}?`);
  };
  const genRef = (entry) => {
    const c = entry.c;
    const refs = (project.assets || []).filter((a) => a.kind === "image" && a.mediaId).map((a) => a.mediaId);
    const prompt = (c.refPrompt || "").trim();
    if (!refs.length) { setGenRefState((s) => ({ ...s, [c.id]: { phase: "error", msg: "add cast @image references (with gallery images) first" } })); return; }
    if (!prompt) { setGenRefState((s) => ({ ...s, [c.id]: { phase: "error", msg: "enter a prompt" } })); return; }
    const refBody = { source: refs[0], sources: refs, instruction: prompt, edit_model: "reference-pro" };
    runGen(setGenRefState, c.id, "/api/edit", refBody, { mode: "edit", ...refBody },
      `Generate a still for ${c.title || "this shot"} from ${refs.length} reference${refs.length === 1 ? "" : "s"}?`);
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
    genState, setGenState, genImgState, setGenImgState, imgModel, setImgModel, genEditState, setGenEditState,
    genRefState, setGenRefState, batching, batchTally,
    generateShot, pollShot, useExistingVideo, genImage, routeImg, genEdit, genRef, routeGen, batchGenerate,
    costEstimate, refreshEstimate,
  };
}

// ---- 4. useExportPipeline: shot-list/backup export, play-sequence, ffmpeg cut ----
function useExportPipeline(project, thumbs) {
  const [seq, setSeq] = useState(null);           // Play-sequence: [clip,...] or null
  const [exp, setExp] = useState(null);           // export overlay: {status,progress,...} or null
  const exportPoll = useRef(null);

  const download = (text, name, type) => { const url = URL.createObjectURL(new Blob([text], { type }));
    const a = document.createElement("a"); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); };
  const exportAll = () => download(buildShotListText(project, fmt, actLetter, shotText),
    `${project.name.replace(/\s+/g, "_")}_shotlist.txt`, "text/plain");
  const exportJSON = () => download(JSON.stringify({ project, thumbs }, null, 2), `${project.name.replace(/\s+/g, "_")}_backup.json`, "application/json");
  const [bundling, setBundling] = useState(false);
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
      const missing = parseInt(r.headers.get("X-Bundle-Missing-Count") || "0", 10);
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url;
      a.download = `${project.name.replace(/\s+/g, "_")}_bundle.zip`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      if (missing) alert(`Bundle exported, but ${missing} referenced file(s) couldn't be found on disk and were left out.`);
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
    exportAll, exportJSON, exportBundle, bundling };
}

export default function App() {
  const [selShot, setSelShot] = useState(null);   // V2 selected-shot: card.id or null
  const { project, setProject, thumbs, storeThumb, busy,
    projList, projMenu, setProjMenu, projectApi, importBackup, activeId } = useProjectStore(setSelShot);

  const { open, setOpen, setCard, setAct, setAssets, setCardStatus,
    addCard, dupCard, delCard, moveCard, moveCardToAct, addAct, delAct, moveAct,
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
  // Bridge the shared <mg-gallery-picker> web component to React (mirrors bindPicker):
  // pickCb doesn't change while the picker is mounted (only open->close via setPickCb),
  // so the closure captured on mount stays correct for the whole picking session.
  const bindGalleryPicker = useCallback((el) => {
    if (el && !el._mgBound) {
      el._mgBound = true;
      el.addEventListener("mg-pick", (e) => {
        const cb = pickCb; setPickCb(null);
        if (cb) cb(e.detail.media_id, e.detail.thumb, e.detail.is_video, e.detail.duration);
      });
      el.addEventListener("mg-close", () => setPickCb(null));
    }
  }, [pickCb]);

  const { genState, setGenState, genImgState, setGenImgState, imgModel, setImgModel, genEditState, setGenEditState,
    genRefState, setGenRefState, batching, batchTally,
    generateShot, pollShot, useExistingVideo, genImage, routeImg, genEdit, genRef, routeGen, batchGenerate,
    costEstimate, refreshEstimate }
    = useGenerationPipeline({ project, thumbs, setCard, setCardStatus, setAssets, openPick, activeId });
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
  useEffect(() => {
    const clearDraft = (s) => { if (!("__draft__" in s)) return s; const n = { ...s }; delete n.__draft__; return n; };
    setGenState(clearDraft); setGenImgState(clearDraft); setGenEditState(clearDraft); setGenRefState(clearDraft);
  }, [activeId]);

  const { seq, exp, playSequence, exportCut, cancelExport, closeExport, closeSequence,
    exportAll, exportJSON, exportBundle, bundling } = useExportPipeline(project, thumbs);

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
      <V2Boundary><LoomV2
        project={project} setCard={setCard} setAssets={setAssets} entries={entries} durOf={durOf} scale={scale}
        selShot={selShot} setSelShot={setSelShot} generateShot={generateShot} useExistingVideo={useExistingVideo} genState={genState}
        thumbs={thumbs} openPick={openPick} storeThumb={storeThumb}
        setAct={setAct} addCard={addCard} dupCard={dupCard} delCard={delCard} moveCard={moveCard}
        moveCardToAct={moveCardToAct} addAct={addAct} delAct={delAct} moveAct={moveAct}
        genImgState={genImgState} imgModel={imgModel} setImgModel={setImgModel} genImage={genImage} routeImg={routeImg}
        genEditState={genEditState} setGenEditState={setGenEditState} genRefState={genRefState} setGenRefState={setGenRefState} genEdit={genEdit} genRef={genRef} routeGen={routeGen}
        projectApi={projectApi} playSequence={playSequence} exportCut={exportCut}
        batching={batching} batchGenerate={batchGenerate} batchTally={batchTally}
        addRef={addRef} setRef={setRef} delRef={delRef}
        exportAll={exportAll} exportJSON={exportJSON} exportBundle={exportBundle} bundling={bundling}
        importBackup={importBackup} setImportOpen={setImportOpen} copyShot={copyShot} setLook={setLook} setDraft={setDraft} splitShot={splitShot}
        onVideoSubmit={onVideoSubmit} onVideoResult={onVideoResult} onVideoError={onVideoError}
        onVideoSlow={onVideoSlow} onVideoPaused={onVideoPaused} pollShot={pollShot}
        costEstimate={costEstimate} refreshEstimate={refreshEstimate} /></V2Boundary>
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
      {pickCb && (pickAllowType
        ? <mg-gallery-picker ref={bindGalleryPicker} default-type={pickKind} show-type></mg-gallery-picker>
        : <mg-gallery-picker ref={bindGalleryPicker} default-type={pickKind}></mg-gallery-picker>)}
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
  const [cropping, setCropping] = useState(false);   // crop-draw mode active
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
  const clip = clips[i];
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
