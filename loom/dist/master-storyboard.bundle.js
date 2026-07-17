var LoomBundle = (() => {
  var __defProp = Object.defineProperty;
  var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
  var __getOwnPropNames = Object.getOwnPropertyNames;
  var __hasOwnProp = Object.prototype.hasOwnProperty;
  var __export = (target, all) => {
    for (var name in all)
      __defProp(target, name, { get: all[name], enumerable: true });
  };
  var __copyProps = (to, from, except, desc) => {
    if (from && typeof from === "object" || typeof from === "function") {
      for (let key of __getOwnPropNames(from))
        if (!__hasOwnProp.call(to, key) && key !== except)
          __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
    }
    return to;
  };
  var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

  // master-storyboard.jsx
  var master_storyboard_exports = {};
  __export(master_storyboard_exports, {
    default: () => App
  });

  // src/loom-core.js
  var CONNECT = {
    new: { label: "New scene", hint: "intentional break \u2014 fresh look/place" },
    cut: { label: "Cut (in edit)", hint: "hard/match cut joined in your editor \u2014 rhyme the frames" },
    flf: { label: "First\u2192Last", hint: "land on an exact end frame; prompt the motion between" },
    extend: { label: "Extend prev", hint: "feed previous clip as @video1; continue seamlessly" }
  };
  var CONTINUITY_PHRASE = "Smooth, continuous, seamless \u2014 no hard cut.";
  var actLetter = (i) => i < 26 ? String.fromCharCode(65 + i) : `A${i}`;
  var maxTagNum = (items, prefix) => {
    const re = new RegExp("^" + prefix + "(\\d+)$");
    return (items || []).reduce((mx, x) => {
      const m = re.exec(x.tag || "");
      return m ? Math.max(mx, +m[1]) : mx;
    }, 0);
  };
  var nextTag = (items, prefix) => prefix + (maxTagNum(items, prefix) + 1);
  var frameLinked = (a, b) => !!a && !!b && (!!a.mediaId && !!b.mediaId && a.mediaId === b.mediaId || !!a.thumbId && !!b.thumbId && a.thumbId === b.thumbId);
  var connectMeta = (connect) => CONNECT[connect] || CONNECT.new;
  var flat = (p) => p.acts.flatMap((a, ai) => a.cards.map((c, ci) => ({ c, a, ai, ci, code: `${actLetter(ai)}\xB7${String(ci + 1).padStart(2, "0")}` })));
  var shotText = (entry, p) => {
    const { c, code, ai } = entry;
    const idx = flat(p).findIndex((x) => x.c.id === c.id);
    const prev = idx > 0 ? flat(p)[idx - 1] : null;
    const L = [`[${code} \u2014 "${c.title || "untitled"}"]  (${c.mode}, ~${c.duration}s, ${connectMeta(c.connect).label})`, ""];
    if (c.connect === "extend" && prev) L.push(`Continue seamlessly from the previous clip ${prev.code} (upload it as @video1).`);
    if (c.connect === "flf") {
      if (c.openFrame.desc || c.openFrame.tag) L.push(`Opening frame ${c.openFrame.tag || "(first image)"}: ${c.openFrame.desc || "\u2014"}`);
      if (c.closeFrame.desc || c.closeFrame.tag) L.push(`Closing frame ${c.closeFrame.tag || "(last image)"}: ${c.closeFrame.desc || "\u2014"}`);
    }
    L.push("", c.prompt || "(prompt tbd)");
    if (c.connect === "extend" || c.connect === "flf") L.push(CONTINUITY_PHRASE);
    const usedCast = (p.assets || []).filter((as) => c.cast.includes(as.id));
    if (usedCast.length) {
      L.push("", "Keep consistent:");
      usedCast.forEach((as) => L.push(`  ${as.name} \u2014 ${as.lock ? "maintain exact appearance from " : "reference "}${as.tag}`));
    }
    if (c.refs.length) {
      L.push("", "Other references:");
      c.refs.forEach((r) => L.push(`  ${r.tag} \u2014 ${r.role || "(role tbd)"}${r.source ? `  [${r.source}]` : ""}`));
    }
    if (c.camera) L.push("", `Camera: ${c.camera}`);
    if (c.lighting) L.push(`Lighting/Mood: ${c.lighting}`);
    if (c.audioCue) L.push(`Audio: ${c.audioCue}`);
    if (c.transIn || c.transOut) L.push(`Edit transitions: in ${c.transIn || "\u2014"} / out ${c.transOut || "\u2014"}`);
    if (c.notes) L.push(`Notes: ${c.notes}`);
    return L.join("\n");
  };
  var shotPayload = (entry, project, imgSrc) => {
    const c = entry.c;
    const tagNum = (t) => {
      const m = /(\d+)/.exec(t || "");
      return m ? +m[1] : 99;
    };
    const imgs = [];
    (project.assets || []).filter((as) => as.kind === "image" && c.cast.includes(as.id)).forEach((as) => {
      const d = as.mediaId || imgSrc(as.thumbId, as.source);
      if (d) imgs.push({ tag: as.tag, d });
    });
    [["@image8", c.openFrame], ["@image9", c.mode === "FLF" ? c.closeFrame : null]].forEach(([fallbackTag, f]) => {
      if (!f) return;
      const d = f.mediaId || imgSrc(f.thumbId, f.source);
      if (d) imgs.push({ tag: f.tag || fallbackTag, d });
    });
    (c.refs || []).filter((r) => r.kind === "image").forEach((r) => {
      const d = r.mediaId || imgSrc(r.thumbId, r.source);
      if (d) imgs.push({ tag: r.tag, d });
    });
    const vids = (c.refs || []).filter((r) => r.kind === "video" && /^\d+$/.test(r.source || "")).map((r) => r.source);
    imgs.sort((a, b) => tagNum(a.tag) - tagNum(b.tag));
    return {
      mode: c.mode,
      prompt: shotText(entry, project),
      images: imgs.map((x) => x.d),
      video_refs: vids,
      duration: c.duration,
      hasInput: imgs.length + vids.length > 0
    };
  };
  var durOf = (c) => Number(c.actualDur || c.duration) || 0;
  var reelStats = (entries, target) => {
    const total = entries.reduce((s, x) => s + durOf(x.c), 0);
    const scale = Math.max(total, target) || 1;
    const over = total - target;
    return { total, scale, over };
  };

  // src/loom-mutations.js
  var patchCard = (project, actId, cardId, fn) => ({
    ...project,
    acts: project.acts.map((a) => a.id !== actId ? a : {
      ...a,
      cards: a.cards.map((c) => c.id !== cardId ? c : fn(c))
    })
  });
  var patchCardById = (project, cardId, patch) => ({
    ...project,
    acts: project.acts.map((a) => ({
      ...a,
      cards: a.cards.map((c) => c.id !== cardId ? c : { ...c, ...patch })
    }))
  });
  var patchAct = (project, actId, patch) => ({
    ...project,
    acts: project.acts.map((a) => a.id !== actId ? a : { ...a, ...patch })
  });
  var patchAssets = (project, fn) => ({ ...project, assets: fn(project.assets || []) });
  var appendCardToAct = (project, actId, card) => ({
    ...project,
    acts: project.acts.map((a) => a.id !== actId ? a : { ...a, cards: [...a.cards, card] })
  });
  var buildDuplicateCard = (card, newCardId, newRefIds) => ({
    ...JSON.parse(JSON.stringify(card)),
    id: newCardId,
    refs: card.refs.map((r, i) => ({ ...r, id: newRefIds && newRefIds[i] || r.id })),
    // A duplicate is a fresh, unrendered shot -- it must not inherit the
    // original's generation result, or it silently shows "done" and Export
    // plays the SAME clip twice.
    resultMid: "",
    status: "todo",
    actualDur: null,
    trimIn: 0,
    trimOut: null
  });
  var insertCardAfter = (project, actId, origCardId, newCard2) => ({
    ...project,
    acts: project.acts.map((a) => a.id !== actId ? a : { ...a, cards: a.cards.flatMap((x) => x.id === origCardId ? [x, newCard2] : [x]) })
  });
  var removeCard = (project, actId, cardId) => ({
    ...project,
    acts: project.acts.map((a) => a.id !== actId ? a : { ...a, cards: a.cards.filter((c) => c.id !== cardId) })
  });
  var moveCardInAct = (project, actId, idx, dir) => ({
    ...project,
    acts: project.acts.map((a) => {
      if (a.id !== actId) return a;
      const j = idx + dir;
      if (j < 0 || j >= a.cards.length) return a;
      const cs = [...a.cards];
      [cs[idx], cs[j]] = [cs[j], cs[idx]];
      return { ...a, cards: cs };
    })
  });
  var moveCardToAct = (project, fromActId, card, toActId) => {
    if (fromActId === toActId) return project;
    return {
      ...project,
      acts: project.acts.map((a) => a.id === fromActId ? { ...a, cards: a.cards.filter((c) => c.id !== card.id) } : a.id === toActId ? { ...a, cards: [...a.cards, card] } : a)
    };
  };
  var nextActName = (project) => `Act ${project.acts.length + 1}`;
  var appendAct = (project, act) => ({ ...project, acts: [...project.acts, act] });
  var removeAct = (project, actId) => ({ ...project, acts: project.acts.filter((a) => a.id !== actId) });
  var moveActInProject = (project, idx, dir) => {
    const j = idx + dir;
    if (j < 0 || j >= project.acts.length) return project;
    const as = [...project.acts];
    [as[idx], as[j]] = [as[j], as[idx]];
    return { ...project, acts: as };
  };
  var buildNewRef = (kind, id) => ({ id, kind, tag: "", role: "", source: "", thumbId: "" });
  var patchRef = (project, actId, cardId, refId, patch) => patchCard(project, actId, cardId, (c) => ({ ...c, refs: c.refs.map((r) => r.id !== refId ? r : { ...r, ...patch }) }));
  var removeRef = (project, actId, cardId, refId) => patchCard(project, actId, cardId, (c) => ({ ...c, refs: c.refs.filter((r) => r.id !== refId) }));
  var countShots = (project) => (project.acts || []).reduce((n, a) => n + (a.cards || []).length, 0);
  var parseCastIdsFromSearch = (search) => (search || "").replace(/^\?/, "").split("&").map((kv) => kv.split("=")).filter(([k]) => k === "cast").flatMap(([, v]) => (v || "").split(",")).map((s) => decodeURIComponent(s).trim()).filter((s) => /^\d+$/.test(s));
  function friendlyGenErr(raw) {
    const s = String(raw || "");
    if (/insufficient|INSUFFICIENT_BALANCE|40300010/i.test(s))
      return "Out of balance for this model \u2014 no free card matched and credits are 0. Claim your daily rewards, or pick a card-covered model.";
    if (/moderat|content.?policy|flagged|prohibit|sensitive|not.?allowed|violat/i.test(s))
      return "PixAI's content filter blocked this generation \u2014 that's decided on PixAI's side, not in the Loom.";
    return s || "generation failed";
  }
  function classifyTaskStatus(d) {
    if (!d) return { phase: "pending" };
    if (d.phase === "done") {
      const mid = (d.media_ids || [])[0] || "";
      const out = { phase: "done", mid };
      if (d.duration) out.duration = d.duration;
      return out;
    }
    if (d.phase === "failed") return { phase: "failed", msg: friendlyGenErr(d.error || d.status || "failed") };
    return { phase: "pending" };
  }
  function buildShotListText(project, fmt2, actLetter2, shotText2) {
    let out = `${project.name}
Runtime target ${fmt2(project.target)}
`;
    if ((project.assets || []).length) {
      out += `
Cast & assets:
`;
      project.assets.forEach((as) => {
        out += `  ${as.tag}  ${as.name} (${as.kind})${as.lock ? " \xB7 lock appearance" : ""}
`;
      });
    }
    project.acts.forEach((a, ai) => {
      out += `
${"=".repeat(48)}
${a.name}
${"=".repeat(48)}

`;
      a.cards.forEach((c, ci) => {
        out += shotText2({ c, code: `${actLetter2(ai)}\xB7${String(ci + 1).padStart(2, "0")}`, ai, ci }, project) + "\n\n";
      });
    });
    return out;
  }
  var buildPlaySequence = (entries) => entries.filter((e) => e.c.resultMid).map((e) => ({
    mid: e.c.resultMid,
    in: e.c.trimIn || 0,
    out: e.c.trimOut,
    title: e.c.title,
    code: e.code
  }));
  function buildExportClips(entries) {
    const clips = entries.filter((e) => e.c.resultMid).map((e) => {
      const dur = e.c.actualDur || e.c.duration || 8, cin = e.c.trimIn || 0;
      const cout = e.c.trimOut != null ? e.c.trimOut : dur;
      return { mid: e.c.resultMid, in: cin, out: e.c.trimOut, span: Math.max(0.1, cout - cin) };
    });
    const total = clips.reduce((s, c) => s + c.span, 0);
    return { clips, total };
  }

  // master-storyboard.jsx
  var { useState, useEffect, useRef, useCallback } = React;
  var STYLES = `
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

.sb-top{position:sticky;top:0;z-index:30;background:rgba(0,0,0,.5);backdrop-filter:blur(10px);
  border-bottom:1px solid var(--line);padding:14px 20px}
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
.sb-shotprev-play{position:absolute;left:7px;bottom:6px;font-size:12px;line-height:1;color:#fff;
  background:rgba(0,0,0,.55);border:1px solid rgba(255,255,255,.25);border-radius:5px;padding:4px 7px;
  cursor:pointer;}
.sb-shotprev-play:hover{background:rgba(0,0,0,.75);border-color:var(--amber);}
.sb-shotprev-wrap{margin-top:8px;max-width:340px}
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
.sb-pick-ov{position:fixed;inset:0;z-index:400;background:rgba(6,4,16,.76);display:flex;align-items:center;justify-content:center;padding:20px}
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

.sb-helpbox{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px;font-size:12.5px;color:var(--ink2);line-height:1.65;margin-top:12px}
.sb-helpbox h4{margin:0 0 8px;color:var(--ink);font-family:system-ui,sans-serif;font-size:14px}
.sb-helpbox h4:not(:first-child){margin-top:14px}
.sb-helpbox code{font-family:ui-monospace,monospace;color:var(--cyan);font-size:12px}
.sb-helpbox b{color:var(--amber)}
.sb-empty{text-align:center;color:var(--ink3);padding:30px;font-size:13px}

@media (max-width:560px){.sb-grid{grid-template-columns:1fr}.sb-main,.sb-top,.sb-wrap{padding-left:13px;padding-right:13px}
  .sb-twoframes{flex-direction:column}.sb-conn-mid{align-self:flex-start;padding:0}}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
:focus-visible{outline:2px solid var(--amber);outline-offset:2px}
`;
  var MODES = ["I2V", "R2V", "V2V", "FLF"];
  var MODE_HINT = {
    T2V: "Text only \u2014 describe the whole scene",
    I2V: "Image-to-video \u2014 ref is first frame; prompt only motion",
    R2V: "Reference-to-video \u2014 lock identity/style/motion via @tags",
    V2V: "Video edit / extend an existing clip",
    FLF: "First & last frame \u2014 interpolate between two images"
  };
  var CAM_PALETTE = {
    "Shot size": ["EWS", "WS", "MLS", "MS", "MCU", "CU", "ECU", "OTS", "two-shot", "insert", "POV"],
    "Movement": [
      "static/locked",
      "pan left",
      "pan right",
      "tilt up",
      "tilt down",
      "dolly in",
      "dolly out",
      "push in",
      "pull out",
      "truck left",
      "truck right",
      "pedestal up",
      "crane up",
      "arc",
      "orbit",
      "tracking/follow",
      "handheld",
      "steadicam",
      "rack focus",
      "whip pan",
      "Dutch angle"
    ],
    "Lens / feel": ["wide", "telephoto", "shallow depth of field", "deep focus", "slow motion", "macro"]
  };
  var TRANS_PALETTE = [
    "cut",
    "hard cut",
    "match cut",
    "smash cut",
    "dissolve",
    "crossfade",
    "fade in",
    "fade to black",
    "J-cut",
    "L-cut",
    "wipe",
    "whip-pan transition"
  ];
  var LIGHTING_PALETTE = [
    "golden hour",
    "blue hour",
    "low-key",
    "high-key",
    "warm haze",
    "cool moonlight",
    "candlelit",
    "firelight",
    "neon glow",
    "backlit / rim light",
    "soft diffused",
    "hard shadows",
    "chiaroscuro",
    "volumetric god rays",
    "overcast",
    "silhouette"
  ];
  var AUDIO_PALETTE = [
    "no music",
    "room tone",
    "ambient hum",
    "soft breathing",
    "whispered dialogue",
    "distant music",
    "rain",
    "heartbeat",
    "beat sync",
    "diegetic only",
    "muffled",
    "rustling fabric"
  ];
  var uid = () => Math.random().toString(36).slice(2, 9);
  var fmt = (s) => {
    s = Math.max(0, Math.round(s || 0));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };
  var emptyFrame = () => ({ thumbId: "", source: "", desc: "", tag: "" });
  var hasStore = typeof window !== "undefined" && window.storage;
  var PKEY = "storyboard:v2:project";
  var PPRE = "storyboard:v2:proj:";
  var ACTIVE_KEY = "storyboard:v2:active";
  var TPRE = "storyboard:v2:thumb:";
  async function sGet(k) {
    try {
      const r = await window.storage.get(k);
      return r ? r.value : null;
    } catch {
      return null;
    }
  }
  async function sSet(k, v) {
    try {
      await window.storage.set(k, v, false);
    } catch (e) {
      console.error(e);
    }
  }
  async function sList(p) {
    try {
      const r = await window.storage.list(p, false);
      if (!r) return [];
      return (r.keys || []).map((k) => typeof k === "string" ? k : k.key);
    } catch {
      return [];
    }
  }
  async function sDel(k) {
    try {
      await window.storage.delete(k);
    } catch (e) {
      console.error(e);
    }
  }
  function fileToThumb(file, maxDim = 480, q = 0.72) {
    return new Promise((res, rej) => {
      const img = new Image(), url = URL.createObjectURL(file);
      img.onload = () => {
        const sc = Math.min(1, maxDim / Math.max(img.width, img.height));
        const w = Math.round(img.width * sc), h = Math.round(img.height * sc);
        const cv = document.createElement("canvas");
        cv.width = w;
        cv.height = h;
        cv.getContext("2d").drawImage(img, 0, 0, w, h);
        URL.revokeObjectURL(url);
        try {
          res(cv.toDataURL("image/jpeg", q));
        } catch (e) {
          rej(e);
        }
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        rej(new Error("img"));
      };
      img.src = url;
    });
  }
  function newCard(extra = {}) {
    return {
      id: uid(),
      title: "",
      status: "todo",
      mode: "I2V",
      duration: 8,
      connect: "cut",
      prompt: "",
      openFrame: emptyFrame(),
      closeFrame: emptyFrame(),
      cast: [],
      refs: [],
      camera: "",
      lighting: "",
      audioCue: "",
      transIn: "",
      transOut: "",
      notes: "",
      discreet: false,
      trimIn: 0,
      trimOut: null,
      ...extra
    };
  }
  function seedProject() {
    return {
      name: "Untitled storyboard",
      target: 480,
      assets: [
        { id: uid(), name: "Her", kind: "image", tag: "@image1", thumbId: "", source: "", lock: true },
        { id: uid(), name: "Me", kind: "image", tag: "@image2", thumbId: "", source: "", lock: true },
        { id: uid(), name: "The room", kind: "image", tag: "@image3", thumbId: "", source: "", lock: false },
        { id: uid(), name: "The song", kind: "audio", tag: "@audio1", thumbId: "", source: "", lock: false }
      ],
      acts: [
        {
          id: uid(),
          name: "Act 1 \u2014 Setup",
          collapsed: false,
          cards: [newCard({
            title: "Establishing shot",
            mode: "I2V",
            duration: 8,
            connect: "new",
            prompt: "Quiet sunlit room at golden hour, dust drifting in the light. Slow reveal of the empty space. Warm, intimate, lived-in.",
            openFrame: { thumbId: "", source: "", desc: "Wide, empty room. Light from window, camera-left.", tag: "@image1" },
            closeFrame: { thumbId: "", source: "", desc: "Same room, camera has pushed in slightly toward the window seat.", tag: "" },
            camera: "WS, slow push in, shallow depth of field",
            lighting: "golden hour, warm low sun, soft haze",
            audioCue: "ambient room tone",
            transIn: "fade in",
            transOut: "dissolve",
            notes: "Example card \u2014 duplicate or delete. The closing frame here becomes the next shot's opening frame."
          })]
        },
        { id: uid(), name: "Act 2 \u2014 Build", collapsed: false, cards: [] },
        { id: uid(), name: "Act 3 \u2014 Payoff", collapsed: false, cards: [] }
      ]
    };
  }
  var V2_STYLES = `
.lv-overlay{position:fixed;inset:0;z-index:400;background:var(--base);display:flex;flex-direction:column;}
.lv-top{display:flex;align-items:center;gap:12px;padding:10px 16px;border-bottom:1px solid var(--surface1);background:var(--surface0);}
.lv-eyebrow{font:700 11px/1 system-ui,sans-serif;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);}
.lv-note{color:var(--subtext);font-size:12px;}
.lv-top button{background:var(--surface1);border:1px solid var(--surface1);color:var(--text);border-radius:8px;padding:7px 13px;font:600 12px/1 system-ui;cursor:pointer;}
.lv-top .lv-close{margin-left:auto;}
.lv-top button:hover{border-color:var(--accent);}
.lv-top button:disabled{opacity:.5;cursor:default;}
.lv-top button:disabled:hover{border-color:var(--surface1);}
/* Fixed 4-region shell: top Timeline drawer (below), then a row of left card /
   board column / right drawer -- nothing free-floating, nothing draggable. */
.lv-shell{flex:1;display:flex;min-height:0;overflow:hidden;}
.lv-side{flex:none;background:var(--surface0);display:flex;flex-direction:column;min-height:0;
  transition:width .18s ease;overflow-x:hidden;}
.lv-side.left{width:280px;border-right:1px solid var(--surface1);}
.lv-side.left.wide{width:560px;}
.lv-side.right{width:380px;border-left:1px solid var(--surface1);}
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
.lv-tlpreviewzone{padding:10px 14px 4px;height:280px;box-sizing:border-box;}
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
.lv-reel{position:relative;flex:1;min-height:40px;display:flex;background:var(--base);border:1px solid var(--surface1);border-radius:7px;overflow:hidden;}
.lv-seg{position:relative;min-width:3px;border-right:1px solid rgba(0,0,0,.35);cursor:pointer;}
.lv-seg.todo{background:var(--surface1);}.lv-seg.wip{background:var(--amber);}.lv-seg.done{background:var(--green);}
.lv-seg.sel{outline:2px solid var(--accent);outline-offset:-2px;z-index:2;}
.lv-target{position:absolute;top:0;bottom:0;width:2px;background:var(--accent);opacity:.7;}
.lv-tlinfo{font-size:11px;color:var(--text);}
.lv-dim{color:var(--subtext);font-style:italic;}
.lv-gen{flex:1;min-height:0;overflow-y:auto;padding:10px;}
.lv-genhead{font:700 13px/1.2 system-ui;color:var(--text);margin-bottom:6px;}
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
.lv-note2{font-size:9px;color:var(--subtext);font-style:italic;margin-top:8px;text-align:center;}
.lv-cframe{height:48px;border-radius:5px;overflow:hidden;background:var(--base);border:1px solid var(--surface1);display:flex;align-items:center;justify-content:center;margin-bottom:5px;}
.lv-cframe img{width:100%;height:100%;object-fit:cover;}
.lv-cframeph{font:700 9px/1 system-ui;color:var(--subtext);}
.lv-cast{flex:1;min-height:0;overflow-y:auto;padding:8px;}
.lv-castrow-h{font:700 10px/1 system-ui;text-transform:uppercase;letter-spacing:.05em;color:var(--subtext);margin-bottom:8px;}
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
  var V2Boundary = class extends React.Component {
    constructor(props) {
      super(props);
      this.state = { err: null };
    }
    static getDerivedStateFromError(e) {
      return { err: e };
    }
    render() {
      if (this.state.err) return /* @__PURE__ */ React.createElement("div", { className: "lv-overlay" }, /* @__PURE__ */ React.createElement("div", { className: "lv-err" }, /* @__PURE__ */ React.createElement("p", null, "The V2 layout hit an error \u2014 your classic Loom is completely safe."), /* @__PURE__ */ React.createElement("pre", null, String(this.state.err && this.state.err.stack || this.state.err)), /* @__PURE__ */ React.createElement("button", { className: "lv-close", onClick: this.props.onClose }, "\u2190 Back to classic Loom")));
      return this.props.children;
    }
  };
  function ProjectSwitcher({ api }) {
    const { activeId, projList, projMenu, setProjMenu, readProjList, openProject, newProject, duplicateProject, deleteProject } = api;
    return /* @__PURE__ */ React.createElement("div", { className: "sb-projwrap" }, /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-projbtn",
        onClick: () => {
          setProjMenu((v) => !v);
          readProjList();
        },
        title: "Switch, create, or manage storyboards",
        "aria-label": "Storyboards"
      },
      "\u25BE"
    ), projMenu && /* @__PURE__ */ React.createElement("div", { className: "sb-projveil", onClick: () => setProjMenu(false) }), projMenu && /* @__PURE__ */ React.createElement("div", { className: "sb-projpop" }, /* @__PURE__ */ React.createElement("div", { className: "sb-projpoph" }, "Storyboards"), /* @__PURE__ */ React.createElement("div", { className: "sb-projlist" }, projList.map((pr) => /* @__PURE__ */ React.createElement("div", { key: pr.id, className: "sb-projitem" + (pr.id === activeId ? " on" : "") }, /* @__PURE__ */ React.createElement("button", { className: "sb-projopen", onClick: () => openProject(pr.id), title: "Open this storyboard" }, /* @__PURE__ */ React.createElement("b", null, pr.name || "Untitled"), /* @__PURE__ */ React.createElement("span", null, pr.shots, " shot", pr.shots === 1 ? "" : "s")), /* @__PURE__ */ React.createElement("button", { className: "sb-projx", title: "Delete", onClick: () => deleteProject(pr.id) }, "\u2715")))), /* @__PURE__ */ React.createElement("div", { className: "sb-projacts" }, /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm", onClick: newProject }, "+ New"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm ghost", onClick: duplicateProject }, "\u29C9 Duplicate"))));
  }
  function LoomV2({ onClose, project, setCard, setAssets, entries, durOf: durOf2, scale, selShot, setSelShot, generateShot, useExistingVideo, genState, thumbs, openPick, storeThumb, setAct, addCard, dupCard, delCard, moveCard, moveCardToAct: moveCardToAct2, addAct, delAct, moveAct, genImgState, imgModel, setImgModel, genImage, routeImg, genEditState, setGenEditState, genRefState, setGenRefState, genEdit, genRef, routeGen, projectApi, playSequence }) {
    const [tab, setTab] = useState("Video");
    const [acct, setAcct] = useState(null);
    const [handoff, setHandoff] = useState("");
    const [deepFocus, setDeepFocus] = useState(null);
    const [leftTab, setLeftTab] = useState("cast");
    const [leftCollapsed, setLeftCollapsed] = useState(false);
    const [density, setDensity] = useState("detailed");
    const [rightCollapsed, setRightCollapsed] = useState(false);
    const [tlState, setTlState] = useState("slim");
    const [tlDragH, setTlDragH] = useState(null);
    const [palFor, setPalFor] = useState(null);
    const [dzHover, setDzHover] = useState(false);
    const [draftCard, setDraftCard] = useState(() => ({
      id: "__draft__",
      mode: "R2V",
      duration: 5,
      connect: "new",
      title: "",
      prompt: "",
      camera: "",
      lighting: "",
      transIn: "",
      transOut: "",
      audioCue: "",
      notes: "",
      imgPrompt: "",
      editPrompt: "",
      refPrompt: "",
      cast: [],
      refs: [],
      openFrame: {},
      closeFrame: {}
    }));
    const [draftTarget, setDraftTarget] = useState("");
    const [draftAttachedInfo, setDraftAttachedInfo] = useState(null);
    const tlDrag = useRef({ dragging: false, startY: 0, startH: 0 });
    useEffect(() => {
      const prevOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = prevOverflow;
      };
    }, []);
    useEffect(() => {
      fetch("/api/account").then((r) => r.json()).then(setAcct).catch(() => {
      });
    }, []);
    useEffect(() => {
      if (!deepFocus) return;
      const onKey = (ev) => {
        if (ev.key === "Escape") setDeepFocus(null);
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [deepFocus]);
    const bindPicker = useCallback((el) => {
      if (el && !el._mgBound) {
        el._mgBound = true;
        el.addEventListener("mg-pick", (e) => setImgModel({ model_id: e.detail.model_id, title: e.detail.title }));
      }
    }, [setImgModel]);
    const TL_HEIGHTS = { hidden: 0, slim: 64, full: 360 };
    const tlPointerDown = (e) => {
      tlDrag.current = { dragging: true, startY: e.clientY, startH: TL_HEIGHTS[tlState], lastH: TL_HEIGHTS[tlState] };
      e.currentTarget.setPointerCapture(e.pointerId);
    };
    const tlPointerMove = (e) => {
      if (!tlDrag.current.dragging) return;
      const h = Math.max(0, Math.min(TL_HEIGHTS.full, tlDrag.current.startH + (e.clientY - tlDrag.current.startY)));
      tlDrag.current.lastH = h;
      setTlDragH(h);
    };
    const tlPointerUp = () => {
      if (!tlDrag.current.dragging) return;
      tlDrag.current.dragging = false;
      const h = tlDrag.current.lastH;
      let best = "hidden", bestD = Infinity;
      Object.entries(TL_HEIGHTS).forEach(([k, v]) => {
        const d = Math.abs(v - h);
        if (d < bestD) {
          bestD = d;
          best = k;
        }
      });
      setTlState(best);
      setTlDragH(null);
    };
    const togglePal = (which) => setPalFor((p) => p === which ? null : which);
    const sel = entries.find((e) => e.c.id === selShot) || null;
    const draftEntry = { a: { id: "__draft__" }, c: draftCard, code: "Draft" };
    const active = sel || draftEntry;
    const routeTarget = sel || entries.find((e) => e.c.id === draftTarget) || null;
    const frameSrc = (f) => f && f.thumbId ? thumbs[f.thumbId] : f && f.mediaId ? "/thumbs/" + f.mediaId + ".jpg" : null;
    const board = /* @__PURE__ */ React.createElement("div", { className: "lv-board" }, project.acts.map((act, ai) => {
      const items = entries.filter((e) => e.ai === ai);
      return /* @__PURE__ */ React.createElement("div", { key: act.id, className: "lv-act" }, /* @__PURE__ */ React.createElement("div", { className: "lv-actrow" }, /* @__PURE__ */ React.createElement("input", { className: "lv-actname-in", value: act.name, onChange: (ev) => setAct(act.id, { name: ev.target.value }), "aria-label": "Act name" }), /* @__PURE__ */ React.createElement("button", { className: "lv-ico", onClick: () => moveAct(ai, -1), title: "Move act up" }, "\u2191"), /* @__PURE__ */ React.createElement("button", { className: "lv-ico", onClick: () => moveAct(ai, 1), title: "Move act down" }, "\u2193"), /* @__PURE__ */ React.createElement("button", { className: "lv-ico danger", onClick: () => delAct(act.id), title: "Delete act" }, "\u2715")), /* @__PURE__ */ React.createElement("div", { className: "lv-cards" }, items.map((e) => {
        const gs = genState[e.c.id];
        const st = gs && gs.phase && gs.phase !== "done" && gs.phase !== "error" ? "wip" : e.c.status;
        return /* @__PURE__ */ React.createElement(
          "div",
          {
            key: e.c.id,
            className: "lv-card " + (e.c.id === selShot ? "sel" : ""),
            onClick: () => setSelShot(e.c.id),
            onDoubleClick: () => setDeepFocus(e),
            title: "Double-click to open in Deep Focus"
          },
          /* @__PURE__ */ React.createElement("div", { className: "lv-cframe" }, (() => {
            const s = frameSrc(e.c.openFrame) || (e.c.resultMid ? "/thumbs/" + e.c.resultMid + ".jpg" : null);
            return s ? /* @__PURE__ */ React.createElement("img", { src: s, alt: "" }) : /* @__PURE__ */ React.createElement("span", { className: "lv-cframeph" }, e.c.mode);
          })()),
          /* @__PURE__ */ React.createElement("div", { className: "lv-code" }, e.code),
          /* @__PURE__ */ React.createElement("div", { className: "lv-ctitle" }, e.c.title || "untitled"),
          /* @__PURE__ */ React.createElement("div", { className: "lv-cmeta" }, /* @__PURE__ */ React.createElement("span", { className: "lv-mode" }, e.c.mode), /* @__PURE__ */ React.createElement("span", { className: "lv-dur" }, durOf2(e.c), "s"), /* @__PURE__ */ React.createElement("span", { className: "lv-st " + st }, gs && gs.msg ? gs.msg : st)),
          /* @__PURE__ */ React.createElement("div", { className: "lv-crow", onClick: (ev) => ev.stopPropagation(), onDoubleClick: (ev) => ev.stopPropagation() }, /* @__PURE__ */ React.createElement("button", { className: "lv-ico xs", onClick: () => moveCard(act.id, e.ci, -1), title: "Move up" }, "\u2191"), /* @__PURE__ */ React.createElement("button", { className: "lv-ico xs", onClick: () => moveCard(act.id, e.ci, 1), title: "Move down" }, "\u2193"), /* @__PURE__ */ React.createElement("button", { className: "lv-ico xs", onClick: () => dupCard(act.id, e.c), title: "Duplicate" }, "\u29C9"), /* @__PURE__ */ React.createElement("button", { className: "lv-ico xs danger", onClick: () => delCard(act.id, e.c), title: "Delete" }, "\u2715"), project.acts.length > 1 && /* @__PURE__ */ React.createElement(
            "select",
            {
              className: "lv-actsel",
              value: "",
              title: "Move to another act",
              onChange: (ev) => ev.target.value && moveCardToAct2(act.id, e.c, ev.target.value)
            },
            /* @__PURE__ */ React.createElement("option", { value: "" }, "move to\u2026"),
            project.acts.filter((a) => a.id !== act.id).map((a) => /* @__PURE__ */ React.createElement("option", { key: a.id, value: a.id }, a.name))
          ))
        );
      })), /* @__PURE__ */ React.createElement("button", { className: "lv-mini2", onClick: () => addCard(act.id) }, "+ Add shot to ", act.name));
    }), /* @__PURE__ */ React.createElement("button", { className: "lv-mini2", onClick: addAct }, "+ New act"), !project.acts.length && /* @__PURE__ */ React.createElement("div", { className: "lv-ph" }, "No acts yet \u2014 add one below."));
    const tlHeight = tlDragH != null ? tlDragH : TL_HEIGHTS[tlState];
    const showTlPreview = tlHeight > (TL_HEIGHTS.slim + TL_HEIGHTS.full) / 2;
    const timelineDrawer = /* @__PURE__ */ React.createElement("div", { className: "lv-tldrawer" }, /* @__PURE__ */ React.createElement("div", { className: "lv-tlcontent", style: { height: tlHeight, transition: tlDragH != null ? "none" : "height .28s cubic-bezier(.2,.8,.2,1)" } }, showTlPreview && /* @__PURE__ */ React.createElement("div", { className: "lv-tlpreviewzone" }, sel && sel.c.resultMid ? /* @__PURE__ */ React.createElement(
      ShotPreview,
      {
        mid: sel.c.resultMid,
        trimIn: sel.c.trimIn,
        trimOut: sel.c.trimOut,
        onTrim: (i, o) => setCard(sel.a.id, sel.c.id, (c) => ({ ...c, trimIn: i, trimOut: o }))
      }
    ) : /* @__PURE__ */ React.createElement("div", { className: "lv-tlpreviewbox lv-ph" }, sel ? "This shot hasn't rendered yet." : "Select a shot to preview it here.")), /* @__PURE__ */ React.createElement("div", { className: "lv-tlreelzone" }, /* @__PURE__ */ React.createElement("div", { className: "lv-reel" }, entries.map((x, i) => /* @__PURE__ */ React.createElement(
      "div",
      {
        key: i,
        className: "lv-seg " + x.c.status + (x.c.id === selShot ? " sel" : ""),
        style: { width: `${durOf2(x.c) / scale * 100}%` },
        title: `${x.code} ${x.c.title || ""}`,
        onClick: () => setSelShot(x.c.id)
      }
    )), /* @__PURE__ */ React.createElement("div", { className: "lv-target", style: { left: `${project.target / scale * 100}%` } })), /* @__PURE__ */ React.createElement("div", { className: "lv-tlinfo" }, sel ? /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("b", null, sel.code), " \xB7 ", sel.c.title || "untitled", " \xB7 ", sel.c.mode, " \xB7 ", durOf2(sel.c), "s") : /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "click a shot to select it \u2014 the whole workspace binds to it")))), /* @__PURE__ */ React.createElement("div", { className: "lv-tlhandle", onPointerDown: tlPointerDown, onPointerMove: tlPointerMove, onPointerUp: tlPointerUp, onPointerCancel: tlPointerUp }, /* @__PURE__ */ React.createElement("div", { className: "lv-tlgrip" })));
    const GEN_ICONS = [["Image", "\u2726"], ["Edit", "\u270E"], ["Reference", "\u{1F5BC}"], ["Video", "\u{1F3AC}"]];
    let gen;
    {
      const gs = genState[active.c.id];
      const busy = gs && gs.phase && gs.phase !== "done" && gs.phase !== "error";
      const patch = (fn) => {
        if (sel) setCard(sel.a.id, sel.c.id, fn);
        else setDraftCard(fn);
      };
      const appendTo = (field, term) => patch((c) => ({ ...c, [field]: c[field] ? c[field] + ", " + term : term }));
      const selIdx = sel ? entries.findIndex((e) => e.c.id === sel.c.id) : -1;
      const prevEntry = selIdx > 0 ? entries[selIdx - 1] : null;
      const patchFrame = (key, fp) => patch((c) => ({ ...c, [key]: { ...c[key], ...fp } }));
      const inheritPrev = () => {
        if (!prevEntry) return;
        const rmid = prevEntry.c.resultMid;
        if (rmid) {
          setHandoff("wip");
          fetch("/api/loom/handoff", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ video_media_id: rmid })
          }).then((r) => r.json()).then((d) => {
            if (d.error || !d.frame_media_id) {
              setHandoff("err");
              return;
            }
            setHandoff("");
            patchFrame("openFrame", {
              mediaId: d.frame_media_id,
              thumbId: "",
              source: "",
              desc: "handed off from " + (prevEntry.code || "prev shot")
            });
          }).catch(() => setHandoff("err"));
        } else {
          patchFrame("openFrame", { ...prevEntry.c.closeFrame });
        }
      };
      let tabBody;
      if (tab === "Video") tabBody = /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Mode"), /* @__PURE__ */ React.createElement("div", { className: "lv-chips" }, MODES.map((m) => /* @__PURE__ */ React.createElement("span", { key: m, className: "lv-chip " + (m === active.c.mode ? "on" : ""), onClick: () => patch((c) => ({ ...c, mode: m })) }, m))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Continuity"), /* @__PURE__ */ React.createElement("div", { className: "lv-chips" }, Object.keys(CONNECT).map((k) => /* @__PURE__ */ React.createElement("span", { key: k, className: "lv-chip " + (k === (active.c.connect || "new") ? "on" : ""), title: CONNECT[k].hint, onClick: () => patch((c) => ({ ...c, connect: k })) }, CONNECT[k].label))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Prompt"), /* @__PURE__ */ React.createElement("textarea", { className: "lv-ta", value: active.c.prompt || "", onChange: (ev) => patch((c) => ({ ...c, prompt: ev.target.value })) }), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Duration"), /* @__PURE__ */ React.createElement("div", { className: "lv-chips" }, [5, 6, 10, 15].map((d) => /* @__PURE__ */ React.createElement("span", { key: d, className: "lv-chip " + (d === active.c.duration ? "on" : ""), onClick: () => patch((c) => ({ ...c, duration: d })) }, d, "s"))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Camera ", /* @__PURE__ */ React.createElement("button", { className: "lv-termsbtn", onClick: () => togglePal("camera") }, "+ terms")), /* @__PURE__ */ React.createElement("input", { className: "lv-in", value: active.c.camera || "", placeholder: "e.g. slow push in, shallow DoF", onChange: (ev) => patch((c) => ({ ...c, camera: ev.target.value })) }), palFor === "camera" && /* @__PURE__ */ React.createElement("div", { className: "lv-termspal" }, Object.entries(CAM_PALETTE).map(([grp, items]) => /* @__PURE__ */ React.createElement("div", { key: grp, className: "lv-termsgrp" }, /* @__PURE__ */ React.createElement("div", { className: "lv-termsgrpt" }, grp), items.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-minichip", onClick: () => appendTo("camera", t) }, t))))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Lighting ", /* @__PURE__ */ React.createElement("button", { className: "lv-termsbtn", onClick: () => togglePal("lighting") }, "+ terms")), /* @__PURE__ */ React.createElement("input", { className: "lv-in", value: active.c.lighting || "", placeholder: "e.g. moonlit, soft haze", onChange: (ev) => patch((c) => ({ ...c, lighting: ev.target.value })) }), palFor === "lighting" && /* @__PURE__ */ React.createElement("div", { className: "lv-termspal" }, LIGHTING_PALETTE.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-minichip", onClick: () => appendTo("lighting", t) }, t))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Transition in ", /* @__PURE__ */ React.createElement("button", { className: "lv-termsbtn", onClick: () => togglePal("transIn") }, "+ terms")), /* @__PURE__ */ React.createElement("input", { className: "lv-in", value: active.c.transIn || "", placeholder: "e.g. cut, dissolve", onChange: (ev) => patch((c) => ({ ...c, transIn: ev.target.value })) }), palFor === "transIn" && /* @__PURE__ */ React.createElement("div", { className: "lv-termspal" }, TRANS_PALETTE.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-minichip", onClick: () => patch((c) => ({ ...c, transIn: t })) }, t))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Transition out ", /* @__PURE__ */ React.createElement("button", { className: "lv-termsbtn", onClick: () => togglePal("transOut") }, "+ terms")), /* @__PURE__ */ React.createElement("input", { className: "lv-in", value: active.c.transOut || "", placeholder: "e.g. cut, dissolve", onChange: (ev) => patch((c) => ({ ...c, transOut: ev.target.value })) }), palFor === "transOut" && /* @__PURE__ */ React.createElement("div", { className: "lv-termspal" }, TRANS_PALETTE.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-minichip", onClick: () => patch((c) => ({ ...c, transOut: t })) }, t))), /* @__PURE__ */ React.createElement("div", { className: "lv-refline" }, (active.c.cast || []).length, " cast \xB7 ", (active.c.refs || []).length, " refs ", /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "(toggle cast in the Cast & assets tab)")), /* @__PURE__ */ React.createElement("button", { className: "lv-go", disabled: busy, onClick: () => generateShot(active) }, busy ? gs.msg || "generating\u2026" : "\u25B6 Generate shot"), sel && /* @__PURE__ */ React.createElement("button", { className: "lv-usevid", disabled: busy, onClick: () => useExistingVideo(sel), title: "Skip generation -- use a video you already have in your gallery as this shot's clip" }, "\u{1F4BE} Use an existing video instead"), !sel && gs && gs.mid && /* @__PURE__ */ React.createElement("div", { className: "lv-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + gs.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lv-route" }, /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "attach to shot \u2192"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn", disabled: !routeTarget, onClick: () => {
        if (!routeTarget) return;
        setCard(routeTarget.a.id, routeTarget.c.id, (x) => ({ ...x, status: "done", resultMid: gs.mid, ...gs.duration ? { actualDur: gs.duration } : {} }));
        setDraftAttachedInfo({ mid: gs.mid, code: routeTarget.code });
      } }, routeTarget ? `attach to ${routeTarget.code}` : "choose a shot above")), draftAttachedInfo && draftAttachedInfo.mid === gs.mid && /* @__PURE__ */ React.createElement("div", { className: "lv-ok2" }, "\u2713 attached to ", draftAttachedInfo.code, " \xB7 it's now that shot's result")));
      else if (tab === "Image") {
        const gi = genImgState[active.c.id] || {};
        const busyI = gi.phase === "submitting" || gi.phase === "running";
        tabBody = /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Model ", imgModel ? /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "\xB7 ", imgModel.title) : null), /* @__PURE__ */ React.createElement("mg-model-picker", { ref: bindPicker, kind: "base" }), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Image prompt"), /* @__PURE__ */ React.createElement(
          "textarea",
          {
            className: "lv-ta",
            value: active.c.imgPrompt || "",
            placeholder: "describe the reference still (subject, pose, composition, light)\u2026",
            onChange: (ev) => patch((c) => ({ ...c, imgPrompt: ev.target.value }))
          }
        ), sel && /* @__PURE__ */ React.createElement("button", { className: "lv-mini2", onClick: () => patch((c) => ({ ...c, imgPrompt: [c.title, c.prompt, c.openFrame && c.openFrame.desc || "", c.lighting || ""].filter(Boolean).join(", ") })) }, "\u21A7 seed from shot description"), /* @__PURE__ */ React.createElement("button", { className: "lv-go", disabled: busyI, onClick: () => genImage(active) }, busyI ? gi.msg || "generating\u2026" : "\u2726 Generate reference image"), gi.phase === "error" && /* @__PURE__ */ React.createElement("div", { className: "lv-gerr" }, gi.msg), gi.mid && /* @__PURE__ */ React.createElement("div", { className: "lv-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + gi.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lv-route" }, /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "route \u2192"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gi.routed === "open" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeImg(routeTarget, "open", active.c.id) }, "open frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gi.routed === "close" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeImg(routeTarget, "close", active.c.id) }, "close frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gi.routed === "cast" ? " on" : ""), onClick: () => routeImg(routeTarget || active, "cast", active.c.id) }, "cast")), gi.routed && /* @__PURE__ */ React.createElement("div", { className: "lv-ok2" }, "\u2713 sent to ", gi.routed, sel ? " \xB7 it now feeds this shot's video gen" : "")));
      } else if (tab === "Edit") {
        const ge = genEditState[active.c.id] || {};
        const busyE = ge.phase === "submitting" || ge.phase === "running";
        const src = active.c.openFrame && active.c.openFrame.mediaId;
        tabBody = /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Source \u2014 ", sel ? "this shot's" : "the draft's", " open frame"), src ? /* @__PURE__ */ React.createElement("img", { className: "lv-editsrc", src: "/thumbs/" + src + ".jpg", alt: "source" }) : /* @__PURE__ */ React.createElement("div", { className: "lv-ph" }, "No open-frame image yet \u2014 ", sel ? /* @__PURE__ */ React.createElement(React.Fragment, null, "route one from the ", /* @__PURE__ */ React.createElement("b", null, "Image"), " tab, or ") : null, "pick it into the open frame above."), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Edit instruction"), /* @__PURE__ */ React.createElement(
          "textarea",
          {
            className: "lv-ta",
            value: active.c.editPrompt || "",
            placeholder: "e.g. make it night, add rain, warmer key light\u2026",
            onChange: (ev) => patch((c) => ({ ...c, editPrompt: ev.target.value }))
          }
        ), /* @__PURE__ */ React.createElement("button", { className: "lv-go", disabled: busyE || !src, onClick: () => genEdit(active) }, busyE ? ge.msg || "editing\u2026" : "\u2726 Edit the open frame"), ge.phase === "error" && /* @__PURE__ */ React.createElement("div", { className: "lv-gerr" }, ge.msg), ge.mid && /* @__PURE__ */ React.createElement("div", { className: "lv-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + ge.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lv-route" }, /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "route \u2192"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (ge.routed === "open" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeGen(genEditState, setGenEditState, routeTarget, "open", active.c.id) }, "open frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (ge.routed === "close" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeGen(genEditState, setGenEditState, routeTarget, "close", active.c.id) }, "close frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (ge.routed === "cast" ? " on" : ""), onClick: () => routeGen(genEditState, setGenEditState, routeTarget || active, "cast", active.c.id) }, "cast")), ge.routed && /* @__PURE__ */ React.createElement("div", { className: "lv-ok2" }, "\u2713 sent to ", ge.routed)));
      } else if (tab === "Reference") {
        const gr = genRefState[active.c.id] || {};
        const busyR = gr.phase === "submitting" || gr.phase === "running";
        const refs = (project.assets || []).filter((a) => a.kind === "image" && a.mediaId);
        tabBody = /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "References \u2014 cast @image members (", refs.length, ")"), refs.length ? /* @__PURE__ */ React.createElement("div", { className: "lv-refstrip" }, refs.map((a) => /* @__PURE__ */ React.createElement("img", { key: a.id, src: "/thumbs/" + a.mediaId + ".jpg", title: a.tag, alt: "" }))) : /* @__PURE__ */ React.createElement("div", { className: "lv-ph" }, "No cast @image references with a gallery image yet \u2014 add some in ", /* @__PURE__ */ React.createElement("b", null, "Cast & assets"), "."), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Prompt"), /* @__PURE__ */ React.createElement(
          "textarea",
          {
            className: "lv-ta",
            value: active.c.refPrompt || "",
            placeholder: "compose a new still from the references\u2026",
            onChange: (ev) => patch((c) => ({ ...c, refPrompt: ev.target.value }))
          }
        ), /* @__PURE__ */ React.createElement("button", { className: "lv-go", disabled: busyR || !refs.length, onClick: () => genRef(active) }, busyR ? gr.msg || "generating\u2026" : "\u2726 Generate from references"), gr.phase === "error" && /* @__PURE__ */ React.createElement("div", { className: "lv-gerr" }, gr.msg), gr.mid && /* @__PURE__ */ React.createElement("div", { className: "lv-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + gr.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lv-route" }, /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "route \u2192"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gr.routed === "open" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeGen(genRefState, setGenRefState, routeTarget, "open", active.c.id) }, "open frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gr.routed === "close" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeGen(genRefState, setGenRefState, routeTarget, "close", active.c.id) }, "close frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gr.routed === "cast" ? " on" : ""), onClick: () => routeGen(genRefState, setGenRefState, routeTarget || active, "cast", active.c.id) }, "cast")), gr.routed && /* @__PURE__ */ React.createElement("div", { className: "lv-ok2" }, "\u2713 sent to ", gr.routed)));
      } else tabBody = /* @__PURE__ */ React.createElement("div", { className: "lv-ph" }, "The ", /* @__PURE__ */ React.createElement("b", null, tab), " tab renders the shot on PixAI.");
      gen = /* @__PURE__ */ React.createElement("div", { className: "lv-gen" }, /* @__PURE__ */ React.createElement("div", { className: "lv-genhead" }, sel ? /* @__PURE__ */ React.createElement(React.Fragment, null, "\u2699 ", sel.code, " \xB7 ", sel.c.title || "untitled") : /* @__PURE__ */ React.createElement(React.Fragment, null, "\u2728 Draft generation ", /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "\u2014 generate freely, then route or attach it to a shot"))), !sel && /* @__PURE__ */ React.createElement("div", { className: "lv-drafttarget" }, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Route results into a shot ", /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "(cast doesn't need one)")), /* @__PURE__ */ React.createElement("select", { className: "lv-sel", value: draftTarget, onChange: (ev) => setDraftTarget(ev.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "" }, "\u2014 choose a shot \u2014"), entries.map((e) => /* @__PURE__ */ React.createElement("option", { key: e.c.id, value: e.c.id }, e.code, " \xB7 ", e.c.title || "untitled")))), /* @__PURE__ */ React.createElement("div", { className: "lv-framehandoff" }, /* @__PURE__ */ React.createElement(
        FrameSlot,
        {
          which: "open",
          frame: active.c.openFrame,
          discreet: active.c.discreet,
          framePrev: frameSrc,
          storeThumb,
          openPick,
          onPatch: (p) => patchFrame("openFrame", p),
          extraBtn: prevEntry ? /* @__PURE__ */ React.createElement(
            "button",
            {
              className: "sb-btn ghost sm",
              onClick: inheritPrev,
              disabled: handoff === "wip",
              title: prevEntry.c.resultMid ? `Splice in ${prevEntry.code}'s generated clip's last frame` : `Copy ${prevEntry.code}'s closing frame here`
            },
            handoff === "wip" ? "\u2702 splicing\u2026" : handoff === "err" ? "\u2702 splice failed \u2014 retry" : prevEntry.c.resultMid ? `\u2702 splice ${prevEntry.code}'s last frame` : `\u21B3 inherit ${prevEntry.code} close`
          ) : /* @__PURE__ */ React.createElement("span", { className: "sb-hint" }, sel ? "first shot \u2014 no previous frame" : "draft \u2014 no shot sequence to inherit from")
        }
      ), /* @__PURE__ */ React.createElement("div", { className: "sb-conn-mid" }, "\u2192"), /* @__PURE__ */ React.createElement(
        FrameSlot,
        {
          which: "close",
          frame: active.c.closeFrame,
          discreet: active.c.discreet,
          framePrev: frameSrc,
          storeThumb,
          openPick,
          onPatch: (p) => patchFrame("closeFrame", p)
        }
      )), /* @__PURE__ */ React.createElement("div", { className: "lv-tabs" }, ["Image", "Edit", "Reference", "Video"].map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-tab " + (t === tab ? "on" : ""), onClick: () => setTab(t) }, t))), acct && /* @__PURE__ */ React.createElement("div", { className: "lv-bal" }, "\u26A1 ", acct.credits == null ? "\u2014" : acct.credits, " credits \xB7 ", acct.cards || 0, " card", acct.cards === 1 ? "" : "s", acct.claim_credits ? /* @__PURE__ */ React.createElement("span", { className: "lv-balclaim" }, " \xB7 +", acct.claim_credits, " claimable") : null), tabBody);
    }
    const castList = /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lv-castrow-h" }, "Cast & assets", sel ? /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, " \u2014 bound to ", sel.code) : null), /* @__PURE__ */ React.createElement("div", { className: "lv-tabs lv-density" }, /* @__PURE__ */ React.createElement("span", { className: "lv-tab " + (density === "simple" ? "on" : ""), onClick: () => setDensity("simple") }, "Simple"), /* @__PURE__ */ React.createElement("span", { className: "lv-tab " + (density === "detailed" ? "on" : ""), onClick: () => setDensity("detailed") }, "Detailed")), density === "detailed" ? (project.assets || []).map((as) => {
      const inShot = sel && (sel.c.cast || []).includes(as.id);
      const toggleInShot = () => sel && setCard(sel.a.id, sel.c.id, (c) => ({ ...c, cast: (c.cast || []).includes(as.id) ? c.cast.filter((x) => x !== as.id) : [...c.cast || [], as.id] }));
      const src = frameSrc(as);
      return /* @__PURE__ */ React.createElement("div", { key: as.id, className: "lv-assetrow" }, as.kind === "image" ? /* @__PURE__ */ React.createElement("label", { className: "lv-assetprev", title: "Attach image" }, src ? /* @__PURE__ */ React.createElement("img", { src, alt: "" }) : "\uFF0B", /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "file",
          accept: "image/*",
          style: { display: "none" },
          onChange: async (e) => {
            const f = e.target.files[0];
            if (!f) return;
            const id = await storeThumb(f);
            setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, thumbId: id, source: x.source || f.name, mediaId: "" }));
          }
        }
      )) : /* @__PURE__ */ React.createElement("div", { className: "lv-assetprev" }, as.kind === "video" ? "\u{1F39E}" : "\u266A"), /* @__PURE__ */ React.createElement(
        "input",
        {
          className: "lv-in",
          style: { flex: "1 1 100px" },
          value: as.name,
          placeholder: "name",
          onChange: (e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, name: e.target.value }))
        }
      ), /* @__PURE__ */ React.createElement(
        "input",
        {
          className: "lv-tagin",
          value: as.tag,
          onChange: (e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, tag: e.target.value }))
        }
      ), /* @__PURE__ */ React.createElement(
        "select",
        {
          className: "lv-sel",
          value: as.kind,
          onChange: (e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, kind: e.target.value }))
        },
        /* @__PURE__ */ React.createElement("option", { value: "image" }, "image"),
        /* @__PURE__ */ React.createElement("option", { value: "video" }, "video"),
        /* @__PURE__ */ React.createElement("option", { value: "audio" }, "audio")
      ), /* @__PURE__ */ React.createElement("label", { className: "lv-locklab", title: "Write 'maintain exact appearance' in prompts" }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: !!as.lock, onChange: (e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, lock: e.target.checked })) }), "lock"), sel && /* @__PURE__ */ React.createElement("label", { className: "lv-inshot", title: "Include in the selected shot's cast" }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: !!inShot, onChange: toggleInShot }), "in ", sel.code), /* @__PURE__ */ React.createElement("button", { className: "lv-ico xs danger", onClick: () => setAssets((a) => a.filter((x) => x.id !== as.id)), title: "Remove" }, "\u2715"));
    }) : /* @__PURE__ */ React.createElement("div", { className: "lv-simplegrid" }, (project.assets || []).map((as) => {
      const inShot = sel && (sel.c.cast || []).includes(as.id);
      const src = frameSrc(as);
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          key: as.id,
          className: "lv-simplecard " + (inShot ? "on " : "") + (!sel ? "nosel" : ""),
          title: sel ? `Toggle into ${sel.code}` : "Select a shot on the board to toggle its cast",
          onClick: () => sel && setCard(sel.a.id, sel.c.id, (c) => ({ ...c, cast: (c.cast || []).includes(as.id) ? c.cast.filter((x) => x !== as.id) : [...c.cast || [], as.id] }))
        },
        src ? /* @__PURE__ */ React.createElement("img", { src, alt: "" }) : /* @__PURE__ */ React.createElement("span", { className: "lv-castph" }),
        /* @__PURE__ */ React.createElement("b", null, as.name || as.kind),
        /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, as.tag)
      );
    })), !(project.assets || []).length && /* @__PURE__ */ React.createElement("div", { className: "lv-ph" }, "No cast yet \u2014 add one below."), /* @__PURE__ */ React.createElement("button", { className: "lv-addcast", onClick: () => openPick((mid, thumb, isVideo) => setAssets((a) => {
      const k = isVideo ? "video" : "image", pre = isVideo ? "@video" : "@image";
      return [...a, { id: uid(), name: "", kind: k, tag: nextTag(a, pre), thumbId: "", source: "", mediaId: mid, lock: false }];
    }), "image", true) }, "+ add from gallery"));
    const finished = entries.filter((e) => e.c.resultMid);
    const addAssetFromFile = async (file) => {
      if (!file || !file.type || !file.type.startsWith("image/")) return;
      const id = await storeThumb(file);
      setAssets((a) => [...a, { id: uid(), name: "", kind: "image", tag: nextTag(a, "@image"), thumbId: id, source: file.name, lock: false }]);
    };
    const footageList = /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lv-footagehead" }, /* @__PURE__ */ React.createElement("span", { className: "lv-castrow-h" }, "Finished shots"), /* @__PURE__ */ React.createElement("button", { className: "lv-browsebtn", onClick: () => openPick((mid, thumb, isVideo) => setAssets((a) => {
      const k = isVideo ? "video" : "image", pre = isVideo ? "@video" : "@image";
      return [...a, { id: uid(), name: "", kind: k, tag: nextTag(a, pre), thumbId: "", source: "", mediaId: mid, lock: false }];
    }), "video", true) }, "\u2315 Browse library")), finished.length ? /* @__PURE__ */ React.createElement("div", { className: "lv-footage" }, finished.map((e) => /* @__PURE__ */ React.createElement("div", { key: e.c.id, className: "lv-fclip " + (e.c.id === selShot ? "sel" : ""), onClick: () => setSelShot(e.c.id) }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + e.c.resultMid + ".jpg", alt: "" }), /* @__PURE__ */ React.createElement("div", { className: "lv-fmeta" }, /* @__PURE__ */ React.createElement("b", null, e.code), /* @__PURE__ */ React.createElement("span", null, durOf2(e.c), "s"))))) : /* @__PURE__ */ React.createElement("div", { className: "lv-ph" }, "No rendered shots yet \u2014 generate one and it lands here."), /* @__PURE__ */ React.createElement(
      "div",
      {
        className: "lv-dropzone" + (dzHover ? " hover" : ""),
        onDragEnter: (ev) => {
          ev.preventDefault();
          setDzHover(true);
        },
        onDragOver: (ev) => ev.preventDefault(),
        onDragLeave: () => setDzHover(false),
        onDrop: (ev) => {
          ev.preventDefault();
          setDzHover(false);
          [...ev.dataTransfer.files].forEach(addAssetFromFile);
        }
      },
      "\u21E9 drag an image here to add it as a cast reference"
    ));
    return /* @__PURE__ */ React.createElement("div", { className: "lv-overlay" }, /* @__PURE__ */ React.createElement("style", null, V2_STYLES), /* @__PURE__ */ React.createElement("div", { className: "lv-top" }, /* @__PURE__ */ React.createElement("span", { className: "lv-eyebrow" }, "The Loom \xB7 V2"), /* @__PURE__ */ React.createElement("span", { className: "lv-note" }, "Click a shot \u2192 it binds to Generate."), /* @__PURE__ */ React.createElement(ProjectSwitcher, { api: projectApi }), /* @__PURE__ */ React.createElement(
      "button",
      {
        disabled: !entries.some((e) => e.c.resultMid),
        onClick: () => playSequence(entries),
        title: "Play every finished shot back-to-back, honoring trims \u2014 a rough cut, no rendering"
      },
      "\u25B6\u25B6 Play"
    ), /* @__PURE__ */ React.createElement("button", { className: "lv-close", onClick: onClose }, "\u2190 Back to classic Loom")), timelineDrawer, /* @__PURE__ */ React.createElement("div", { className: "lv-shell" }, /* @__PURE__ */ React.createElement("div", { className: "lv-side left" + (leftCollapsed ? " collapsed" : "") + (!leftCollapsed && leftTab === "cast" && density === "detailed" ? " wide" : "") }, /* @__PURE__ */ React.createElement("div", { className: "lv-sidehead" }, !leftCollapsed && /* @__PURE__ */ React.createElement("div", { className: "lv-tabs lv-sidetabs" }, /* @__PURE__ */ React.createElement("span", { className: "lv-tab " + (leftTab === "cast" ? "on" : ""), onClick: () => setLeftTab("cast") }, "Cast & assets"), /* @__PURE__ */ React.createElement("span", { className: "lv-tab " + (leftTab === "footage" ? "on" : ""), onClick: () => setLeftTab("footage") }, "Footage")), /* @__PURE__ */ React.createElement("button", { className: "lv-col", onClick: () => setLeftCollapsed((v) => !v), title: "collapse" }, leftCollapsed ? "\u25B8" : "\u25C2")), leftCollapsed ? /* @__PURE__ */ React.createElement("div", { className: "lv-railicons" }, /* @__PURE__ */ React.createElement("button", { className: "lv-railbtn" + (leftTab === "cast" ? " on" : ""), title: "Cast & assets", onClick: () => {
      setLeftTab("cast");
      setLeftCollapsed(false);
    } }, "\u{1F464}"), /* @__PURE__ */ React.createElement("button", { className: "lv-railbtn" + (leftTab === "footage" ? " on" : ""), title: "Footage", onClick: () => {
      setLeftTab("footage");
      setLeftCollapsed(false);
    } }, "\u{1F3AC}")) : /* @__PURE__ */ React.createElement("div", { className: "lv-cast" }, leftTab === "cast" ? castList : footageList)), /* @__PURE__ */ React.createElement("div", { className: "lv-boardcol" }, board), /* @__PURE__ */ React.createElement("div", { className: "lv-side right" + (rightCollapsed ? " collapsed" : "") }, /* @__PURE__ */ React.createElement("div", { className: "lv-sidehead" }, /* @__PURE__ */ React.createElement("button", { className: "lv-col", onClick: () => setRightCollapsed((v) => !v), title: "collapse" }, rightCollapsed ? "\u25C2" : "\u25B8"), !rightCollapsed && /* @__PURE__ */ React.createElement("div", { className: "lv-tabs lv-sidetabs" }, ["Image", "Edit", "Reference", "Video"].map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-tab " + (t === tab ? "on" : ""), onClick: () => setTab(t) }, t)))), rightCollapsed ? /* @__PURE__ */ React.createElement("div", { className: "lv-railicons" }, GEN_ICONS.map(([t, ic]) => /* @__PURE__ */ React.createElement(
      "button",
      {
        key: t,
        className: "lv-railbtn" + (t === tab ? " on" : ""),
        title: t,
        onClick: () => {
          setTab(t);
          setRightCollapsed(false);
        }
      },
      ic
    ))) : gen)), deepFocus && (() => {
      const live = entries.find((x) => x.c.id === deepFocus.c.id);
      if (!live) {
        setDeepFocus(null);
        return null;
      }
      const dfPatch = (fn) => setCard(live.a.id, live.c.id, fn);
      const dfPatchFrame = (key, fp) => dfPatch((cc) => ({ ...cc, [key]: { ...cc[key], ...fp } }));
      const c = live.c;
      return /* @__PURE__ */ React.createElement("div", { className: "lv-df-veil", onClick: (ev) => {
        if (ev.target === ev.currentTarget) setDeepFocus(null);
      } }, /* @__PURE__ */ React.createElement("div", { className: "lv-df" }, /* @__PURE__ */ React.createElement("div", { className: "lv-df-head" }, /* @__PURE__ */ React.createElement("span", { className: "lv-df-code" }, deepFocus.code), /* @__PURE__ */ React.createElement(
        "input",
        {
          className: "lv-df-title",
          value: c.title || "",
          placeholder: "untitled",
          onChange: (ev) => dfPatch((cc) => ({ ...cc, title: ev.target.value }))
        }
      ), /* @__PURE__ */ React.createElement("button", { className: "lv-col", onClick: () => setDeepFocus(null), title: "Close (Esc)" }, "\u2715")), /* @__PURE__ */ React.createElement("div", { className: "lv-df-row" }, /* @__PURE__ */ React.createElement("div", { className: "lv-field" }, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Mode"), /* @__PURE__ */ React.createElement("div", { className: "lv-chips" }, MODES.map((m) => /* @__PURE__ */ React.createElement(
        "span",
        {
          key: m,
          className: "lv-chip " + (m === c.mode ? "on" : ""),
          onClick: () => dfPatch((cc) => ({ ...cc, mode: m }))
        },
        m
      )))), /* @__PURE__ */ React.createElement("div", { className: "lv-field narrow" }, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Duration (s)"), /* @__PURE__ */ React.createElement(
        "input",
        {
          className: "lv-in",
          type: "number",
          min: "1",
          value: c.duration,
          onChange: (ev) => dfPatch((cc) => ({ ...cc, duration: Number(ev.target.value) }))
        }
      ))), /* @__PURE__ */ React.createElement("div", { className: "lv-df-frames" }, /* @__PURE__ */ React.createElement(
        FrameSlot,
        {
          which: "open",
          frame: c.openFrame,
          discreet: c.discreet,
          framePrev: frameSrc,
          storeThumb,
          openPick,
          onPatch: (p) => dfPatchFrame("openFrame", p)
        }
      ), /* @__PURE__ */ React.createElement("div", { className: "sb-conn-mid" }, "\u2192"), /* @__PURE__ */ React.createElement(
        FrameSlot,
        {
          which: "close",
          frame: c.closeFrame,
          discreet: c.discreet,
          framePrev: frameSrc,
          storeThumb,
          openPick,
          onPatch: (p) => dfPatchFrame("closeFrame", p)
        }
      )), /* @__PURE__ */ React.createElement("button", { className: "lv-go", onClick: () => {
        setSelShot(c.id);
        setDeepFocus(null);
      } }, "Select in Generate \u2192")));
    })());
  }
  function useProjectStore(setSelShot) {
    const [project, setProject] = useState(null);
    const [thumbs, setThumbs] = useState({});
    const [busy, setBusy] = useState(false);
    const [activeId, setActiveId] = useState(null);
    const [projList, setProjList] = useState([]);
    const [projMenu, setProjMenu] = useState(false);
    const saveTimer = useRef(null);
    const castImported = useRef(false);
    const readProjList = useCallback(async () => {
      if (!hasStore) return [];
      const keys = await sList(PPRE);
      const out = [];
      for (const k of keys) {
        try {
          const raw = await sGet(k);
          if (!raw) continue;
          const pr = JSON.parse(raw);
          out.push({ id: k.slice(PPRE.length), name: pr.name || "Untitled", shots: countShots(pr) });
        } catch {
        }
      }
      out.sort((a, b) => (a.name || "").localeCompare(b.name || ""));
      setProjList(out);
      return out;
    }, []);
    const flushSave = useCallback(async (id, p) => {
      if (hasStore && id && p) await sSet(PPRE + id, JSON.stringify(p));
    }, []);
    useEffect(() => {
      (async () => {
        if (!hasStore) {
          setProject(seedProject());
          return;
        }
        let keys = await sList(PPRE);
        if (!keys.length) {
          const legacy = await sGet(PKEY);
          const id = uid();
          await sSet(PPRE + id, legacy || JSON.stringify(seedProject()));
          await sSet(ACTIVE_KEY, id);
          keys = [PPRE + id];
        }
        let aid = await sGet(ACTIVE_KEY);
        if (!aid || !keys.includes(PPRE + aid)) aid = keys[0].slice(PPRE.length);
        let p = null;
        try {
          const raw = await sGet(PPRE + aid);
          if (raw) p = JSON.parse(raw);
        } catch {
        }
        if (!p) {
          p = seedProject();
          await sSet(PPRE + aid, JSON.stringify(p));
        }
        setActiveId(aid);
        setProject(p);
        const tkeys = await sList(TPRE);
        const map = {};
        for (const k of tkeys) {
          const v = await sGet(k);
          if (v) map[k.slice(TPRE.length)] = v;
        }
        setThumbs(map);
        readProjList();
      })();
    }, []);
    const openProject = useCallback(async (id) => {
      if (!id || id === activeId) {
        setProjMenu(false);
        return;
      }
      await flushSave(activeId, project);
      let p = null;
      try {
        const raw = await sGet(PPRE + id);
        if (raw) p = JSON.parse(raw);
      } catch {
      }
      if (!p) return;
      await sSet(ACTIVE_KEY, id);
      setActiveId(id);
      setProject(p);
      setSelShot(null);
      setProjMenu(false);
    }, [activeId, project, flushSave, setSelShot]);
    const newProject = useCallback(async () => {
      await flushSave(activeId, project);
      const id = uid();
      const p = seedProject();
      p.name = "New storyboard";
      await sSet(PPRE + id, JSON.stringify(p));
      await sSet(ACTIVE_KEY, id);
      setActiveId(id);
      setProject(p);
      setSelShot(null);
      setProjMenu(false);
      readProjList();
    }, [activeId, project, flushSave, readProjList, setSelShot]);
    const duplicateProject = useCallback(async () => {
      await flushSave(activeId, project);
      const id = uid();
      const p = { ...project, name: (project.name || "Untitled") + " copy" };
      await sSet(PPRE + id, JSON.stringify(p));
      await sSet(ACTIVE_KEY, id);
      setActiveId(id);
      setProject(p);
      setProjMenu(false);
      readProjList();
    }, [activeId, project, flushSave, readProjList]);
    const deleteProject = useCallback(async (id) => {
      const list = await readProjList();
      if (list.length <= 1) {
        window.alert("This is your only storyboard \u2014 make another before deleting this one.");
        return;
      }
      const tgt = list.find((x) => x.id === id);
      if (!window.confirm(`Delete "${tgt && tgt.name || "this storyboard"}"? This can't be undone.`)) return;
      if (id === activeId) {
        const next = list.find((x) => x.id !== id);
        let p = null;
        try {
          const raw = await sGet(PPRE + next.id);
          if (raw) p = JSON.parse(raw);
        } catch {
        }
        await sDel(PPRE + id);
        await sSet(ACTIVE_KEY, next.id);
        setActiveId(next.id);
        setProject(p || seedProject());
        setSelShot(null);
      } else {
        await sDel(PPRE + id);
      }
      await readProjList();
      setProjMenu(false);
    }, [activeId, readProjList, setSelShot]);
    const projectApi = { activeId, projList, projMenu, setProjMenu, readProjList, openProject, newProject, duplicateProject, deleteProject };
    useEffect(() => {
      if (!project || castImported.current) return;
      castImported.current = true;
      const ids = parseCastIdsFromSearch(location.search);
      if (!ids.length) return;
      setProject((p) => {
        const existing = p.assets || [];
        let n = maxTagNum(existing, "@image");
        const added = ids.map((mid) => ({
          id: uid(),
          name: "",
          kind: "image",
          tag: "@image" + ++n,
          thumbId: "",
          source: "",
          mediaId: mid,
          lock: true
        }));
        return { ...p, assets: [...existing, ...added] };
      });
      history.replaceState(null, "", location.pathname);
    }, [project]);
    useEffect(() => {
      if (!project || !hasStore || !activeId) return;
      setBusy(true);
      clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(async () => {
        await sSet(PPRE + activeId, JSON.stringify(project));
        setBusy(false);
      }, 600);
      return () => clearTimeout(saveTimer.current);
    }, [project, activeId]);
    const storeThumb = useCallback(async (file) => {
      const data = await fileToThumb(file);
      const id = uid();
      setThumbs((t) => ({ ...t, [id]: data }));
      if (hasStore) await sSet(TPRE + id, data);
      return id;
    }, []);
    const importJSON = async (file) => {
      if (!file) return;
      try {
        const d = JSON.parse(await file.text());
        if (!d.project) {
          window.alert("That file didn't parse as a storyboard backup.");
          return;
        }
        if (!window.confirm(`Import "${d.project.name || "this backup"}" as a NEW storyboard?

Your currently-open board is left untouched.`)) return;
        await flushSave(activeId, project);
        const id = uid();
        await sSet(PPRE + id, JSON.stringify(d.project));
        await sSet(ACTIVE_KEY, id);
        if (d.thumbs) {
          setThumbs((t) => ({ ...t, ...d.thumbs }));
          if (hasStore) for (const [k, v] of Object.entries(d.thumbs)) await sSet(TPRE + k, v);
        }
        setActiveId(id);
        setProject(d.project);
        setSelShot(null);
        readProjList();
      } catch {
        window.alert("That file didn't parse as a storyboard backup.");
      }
    };
    return {
      project,
      setProject,
      thumbs,
      storeThumb,
      busy,
      projList,
      projMenu,
      setProjMenu,
      projectApi,
      importJSON
    };
  }
  function useShotMutations(project, setProject) {
    const [open, setOpen] = useState({});
    const setCard = useCallback((aId, cId, fn) => setProject((p) => patchCard(p, aId, cId, fn)), [setProject]);
    const setAct = useCallback((aId, patch) => setProject((p) => patchAct(p, aId, patch)), [setProject]);
    const setAssets = useCallback((fn) => setProject((p) => patchAssets(p, fn)), [setProject]);
    const setCardStatus = (cardId, patch) => setProject((p) => patchCardById(p, cardId, patch));
    const addCard = (aId) => {
      const c = newCard();
      setProject((p) => appendCardToAct(p, aId, c));
      setOpen((o) => ({ ...o, [c.id]: true }));
    };
    const dupCard = (aId, card) => {
      const clone = buildDuplicateCard(card, uid(), card.refs.map(() => uid()));
      setProject((p) => insertCardAfter(p, aId, card.id, clone));
    };
    const delCard = (aId, card) => setProject((p) => removeCard(p, aId, card.id));
    const moveCard = (aId, idx, dir) => setProject((p) => moveCardInAct(p, aId, idx, dir));
    const moveCardToAct2 = (fromId, card, toId) => setProject((p) => moveCardToAct(p, fromId, card, toId));
    const addAct = () => setProject((p) => appendAct(p, { id: uid(), name: nextActName(p), collapsed: false, cards: [] }));
    const delAct = (aId) => {
      const a = project.acts.find((x) => x.id === aId);
      if (a.cards.length && !window.confirm(`Delete "${a.name}" and its ${a.cards.length} card(s)?`)) return;
      setProject((p) => removeAct(p, aId));
    };
    const moveAct = (idx, dir) => setProject((p) => moveActInProject(p, idx, dir));
    const addRef = (aId, card, kind) => {
      const pre = kind === "image" ? "@image" : kind === "video" ? "@video" : "@audio";
      const tag = nextTag(card.refs.filter((r) => r.kind === kind), pre);
      setCard(aId, card.id, (c) => ({ ...c, refs: [...c.refs, { ...buildNewRef(kind, uid()), tag }] }));
    };
    const setRef = (aId, cId, rId, patch) => setProject((p) => patchRef(p, aId, cId, rId, patch));
    const delRef = (aId, cId, ref) => setProject((p) => removeRef(p, aId, cId, ref.id));
    return {
      open,
      setOpen,
      setCard,
      setAct,
      setAssets,
      setCardStatus,
      addCard,
      dupCard,
      delCard,
      moveCard,
      moveCardToAct: moveCardToAct2,
      addAct,
      delAct,
      moveAct,
      addRef,
      setRef,
      delRef
    };
  }
  function useGenerationPipeline({ project, thumbs, setCard, setCardStatus, setAssets, openPick }) {
    const [genState, setGenState] = useState({});
    const [genImgState, setGenImgState] = useState({});
    const [imgModel, setImgModel] = useState(null);
    const [genEditState, setGenEditState] = useState({});
    const [genRefState, setGenRefState] = useState({});
    const [batching, setBatching] = useState(false);
    const imgSrc = (thumbId, source) => thumbId ? thumbs[thumbId] : source && (source.startsWith("http") || source.startsWith("data:") || /^\d+$/.test(source)) ? source : null;
    const shotPayload2 = (entry) => shotPayload(entry, project, imgSrc);
    const priceShot = async (entry) => {
      try {
        const r = await fetch("/api/price", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(shotPayload2(entry))
        });
        return await r.json();
      } catch {
        return null;
      }
    };
    const generateShot = async (entry, opts = {}) => {
      const c = entry.c;
      const p = shotPayload2(entry);
      if (!p.hasInput) {
        setGenState((s) => ({ ...s, [c.id]: { phase: "error", msg: "attach a frame or cast image first" } }));
        return;
      }
      if (!opts.skipConfirm) {
        const pr = await priceShot(entry);
        if (pr && !pr.free && pr.cost != null && !window.confirm(`No free card covers this shot \u2014 it will spend ~${pr.cost.toLocaleString()} credits.

Generate anyway?`)) return;
      }
      setGenState((s) => ({ ...s, [c.id]: { phase: "submitting", msg: "Submitting\u2026" } }));
      setCardStatus(c.id, { status: "wip" });
      try {
        const r = await fetch("/api/loom/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            mode: p.mode,
            prompt: p.prompt,
            images: p.images,
            video_refs: p.video_refs,
            duration: p.duration,
            origin: "loom-shot"
          })
        });
        const d = await r.json();
        if (d.error || !d.task_id) {
          setGenState((s) => ({ ...s, [c.id]: { phase: "error", msg: d.error ? friendlyGenErr(d.error) : "submit failed" } }));
          return;
        }
        pollShot(c.id, d.task_id);
      } catch {
        setGenState((s) => ({ ...s, [c.id]: { phase: "error", msg: "network error" } }));
      }
    };
    const pollShot = (cardId, tid) => {
      setGenState((s) => ({ ...s, [cardId]: { phase: "running", msg: "Rendering\u2026 (task " + String(tid).slice(-6) + ")" } }));
      const tick = () => fetch("/api/task-status?task_id=" + tid).then((r) => r.json()).then((d) => {
        const cls = classifyTaskStatus(d);
        if (cls.phase === "done") {
          setGenState((s) => ({ ...s, [cardId]: { phase: "done", msg: "Done", mid: cls.mid, duration: cls.duration } }));
          setCardStatus(cardId, { status: "done", resultMid: cls.mid, ...cls.duration ? { actualDur: cls.duration } : {} });
        } else if (cls.phase === "failed") setGenState((s) => ({ ...s, [cardId]: { phase: "error", msg: cls.msg } }));
        else setTimeout(tick, 4e3);
      }).catch(() => setTimeout(tick, 5e3));
      setTimeout(tick, 2500);
    };
    const useExistingVideo = (entry) => {
      openPick((mid, thumb, isVideo, duration) => {
        const dur = parseFloat(duration);
        setGenState((s) => ({ ...s, [entry.c.id]: { phase: "done", msg: "Attached from your gallery", mid } }));
        setCardStatus(entry.c.id, {
          status: "done",
          resultMid: mid,
          ...dur > 0 ? { actualDur: dur } : {}
        });
      }, "video");
    };
    const pollImg = (cardId, tid) => {
      const tick = () => fetch("/api/task-status?task_id=" + tid).then((r) => r.json()).then((d) => {
        const cls = classifyTaskStatus(d);
        if (cls.phase === "done") setGenImgState((s) => ({ ...s, [cardId]: { phase: "done", msg: "Done", mid: cls.mid } }));
        else if (cls.phase === "failed") setGenImgState((s) => ({ ...s, [cardId]: { phase: "error", msg: cls.msg } }));
        else setTimeout(tick, 4e3);
      }).catch(() => setTimeout(tick, 5e3));
      setTimeout(tick, 2500);
    };
    const genImage = async (entry) => {
      const c = entry.c;
      const prompt = (c.imgPrompt || "").trim();
      if (!imgModel) {
        setGenImgState((s) => ({ ...s, [c.id]: { phase: "error", msg: "pick a model first" } }));
        return;
      }
      if (!prompt) {
        setGenImgState((s) => ({ ...s, [c.id]: { phase: "error", msg: "enter an image prompt" } }));
        return;
      }
      if (!window.confirm(`Generate a reference image for ${c.title || "this shot"}?

A matching free card auto-applies; otherwise it spends credits.`)) return;
      setGenImgState((s) => ({ ...s, [c.id]: { phase: "submitting", msg: "Submitting\u2026" } }));
      try {
        const r = await fetch("/api/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_id: imgModel.model_id, prompt })
        });
        const d = await r.json();
        if (d.error || !d.task_id) {
          setGenImgState((s) => ({ ...s, [c.id]: { phase: "error", msg: d.error ? friendlyGenErr(d.error) : "submit failed" } }));
          return;
        }
        setGenImgState((s) => ({ ...s, [c.id]: { phase: "running", msg: "Generating\u2026" } }));
        pollImg(c.id, d.task_id);
      } catch {
        setGenImgState((s) => ({ ...s, [c.id]: { phase: "error", msg: "network error" } }));
      }
    };
    const routeImg = (entry, target, sourceId) => {
      const c = entry.c;
      const sid = sourceId || c.id;
      const gs = genImgState[sid];
      if (!gs || !gs.mid) return;
      const mid = gs.mid;
      if (target === "open") setCard(entry.a.id, c.id, (x) => ({ ...x, openFrame: { ...x.openFrame, mediaId: mid, thumbId: "", source: "", desc: x.openFrame.desc || "generated in Loom" } }));
      else if (target === "close") setCard(entry.a.id, c.id, (x) => ({ ...x, closeFrame: { ...x.closeFrame, mediaId: mid, thumbId: "", source: "", desc: x.closeFrame.desc || "generated in Loom" } }));
      else if (target === "cast") setAssets((a) => [...a, { id: uid(), name: c.title || "", kind: "image", tag: nextTag(a, "@image"), thumbId: "", source: "", mediaId: mid, lock: false }]);
      setGenImgState((s) => ({ ...s, [sid]: { ...s[sid], routed: target } }));
    };
    const runGen = async (setState, cardId, endpoint, body, confirmMsg) => {
      if (confirmMsg && !window.confirm(confirmMsg)) return;
      setState((s) => ({ ...s, [cardId]: { phase: "submitting", msg: "Submitting\u2026" } }));
      const poll = (tid) => {
        const tick = () => fetch("/api/task-status?task_id=" + tid).then((r) => r.json()).then((d) => {
          const cls = classifyTaskStatus(d);
          if (cls.phase === "done") setState((s) => ({ ...s, [cardId]: { phase: "done", msg: "Done", mid: cls.mid } }));
          else if (cls.phase === "failed") setState((s) => ({ ...s, [cardId]: { phase: "error", msg: cls.msg } }));
          else setTimeout(tick, 4e3);
        }).catch(() => setTimeout(tick, 5e3));
        setTimeout(tick, 2500);
      };
      try {
        const r = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        const d = await r.json();
        if (d.error || !d.task_id) {
          setState((s) => ({ ...s, [cardId]: { phase: "error", msg: d.error ? friendlyGenErr(d.error) : "submit failed" } }));
          return;
        }
        setState((s) => ({ ...s, [cardId]: { phase: "running", msg: "Generating\u2026" } }));
        poll(d.task_id);
      } catch {
        setState((s) => ({ ...s, [cardId]: { phase: "error", msg: "network error" } }));
      }
    };
    const routeGen = (state, setState, entry, target, sourceId) => {
      const c = entry.c;
      const sid = sourceId || c.id;
      const gs = state[sid];
      if (!gs || !gs.mid) return;
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
      if (!src) {
        setGenEditState((s) => ({ ...s, [c.id]: { phase: "error", msg: "the open frame needs a gallery image first (route one from the Image tab, or pick it into the frame)" } }));
        return;
      }
      if (!instruction) {
        setGenEditState((s) => ({ ...s, [c.id]: { phase: "error", msg: "describe the edit" } }));
        return;
      }
      runGen(
        setGenEditState,
        c.id,
        "/api/edit",
        { source: src, instruction, edit_model: "edit-pro" },
        `Edit the open frame of ${c.title || "this shot"}?

An Edit-Pro card auto-applies; otherwise it spends credits.`
      );
    };
    const genRef = (entry) => {
      const c = entry.c;
      const refs = (project.assets || []).filter((a) => a.kind === "image" && a.mediaId).map((a) => a.mediaId);
      const prompt = (c.refPrompt || "").trim();
      if (!refs.length) {
        setGenRefState((s) => ({ ...s, [c.id]: { phase: "error", msg: "add cast @image references (with gallery images) first" } }));
        return;
      }
      if (!prompt) {
        setGenRefState((s) => ({ ...s, [c.id]: { phase: "error", msg: "enter a prompt" } }));
        return;
      }
      runGen(
        setGenRefState,
        c.id,
        "/api/edit",
        { source: refs[0], sources: refs, instruction: prompt, edit_model: "reference-pro" },
        `Generate a still for ${c.title || "this shot"} from ${refs.length} reference${refs.length === 1 ? "" : "s"}?

A Reference-Pro card auto-applies; otherwise it spends credits.`
      );
    };
    const batchGenerate = async (entries) => {
      const todo = entries.filter((e) => e.c.status !== "done");
      if (!todo.length) return;
      setBatching(true);
      const prices = await Promise.all(todo.map((e) => priceShot(e)));
      let free = 0, paid = 0, credits = 0;
      prices.forEach((pr) => {
        if (pr && pr.free) free++;
        else {
          paid++;
          if (pr && pr.cost != null) credits += pr.cost;
        }
      });
      const msg = `Generate ${todo.length} shot(s)?

\u{1F3AB} ${free} covered by a free card
\u2248 ${paid} will spend credits \u2014 about ${credits.toLocaleString()} total.`;
      if (!window.confirm(msg)) {
        setBatching(false);
        return;
      }
      for (const e of todo) {
        try {
          await generateShot(e, { skipConfirm: true });
        } catch (_e) {
        }
        await new Promise((r) => setTimeout(r, 2200));
      }
      setBatching(false);
    };
    return {
      genState,
      genImgState,
      imgModel,
      setImgModel,
      genEditState,
      setGenEditState,
      genRefState,
      setGenRefState,
      batching,
      generateShot,
      useExistingVideo,
      genImage,
      routeImg,
      genEdit,
      genRef,
      routeGen,
      batchGenerate
    };
  }
  function useExportPipeline(project, thumbs) {
    const [seq, setSeq] = useState(null);
    const [exp, setExp] = useState(null);
    const exportPoll = useRef(null);
    const download = (text, name, type) => {
      const url = URL.createObjectURL(new Blob([text], { type }));
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1e3);
    };
    const exportAll = () => download(
      buildShotListText(project, fmt, actLetter, shotText),
      `${project.name.replace(/\s+/g, "_")}_shotlist.txt`,
      "text/plain"
    );
    const exportJSON = () => download(JSON.stringify({ project, thumbs }, null, 2), `${project.name.replace(/\s+/g, "_")}_backup.json`, "application/json");
    const playSequence = (entries) => {
      const clips = buildPlaySequence(entries);
      if (clips.length) setSeq(clips);
      else alert("No finished shots yet \u2014 generate one first.");
    };
    const exportCut = (entries) => {
      const { clips, total } = buildExportClips(entries);
      if (!clips.length) {
        alert("No finished shots to export yet \u2014 generate one first.");
        return;
      }
      setExp({ status: "running", progress: 0, elapsed: 0 });
      fetch("/api/loom/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clips: clips.map((c) => ({ mid: c.mid, in: c.in, out: c.out })), total_seconds: total })
      }).then((r) => r.json()).then((d) => {
        if (d.error) {
          setExp({ status: "failed", error: d.error });
          return;
        }
        const tick = () => fetch("/api/loom/export-status").then((r) => r.json()).then((s) => {
          setExp(s);
          if (s.status === "running") exportPoll.current = setTimeout(tick, 1e3);
        }).catch(() => {
          exportPoll.current = setTimeout(tick, 2e3);
        });
        tick();
      }).catch(() => setExp({ status: "failed", error: "network error" }));
    };
    const cancelExport = () => {
      fetch("/api/loom/export-cancel", { method: "POST" }).catch(() => {
      });
    };
    const closeExport = () => {
      if (exportPoll.current) clearTimeout(exportPoll.current);
      setExp(null);
    };
    const closeSequence = () => setSeq(null);
    return { seq, exp, playSequence, exportCut, cancelExport, closeExport, closeSequence, exportAll, exportJSON };
  }
  function App() {
    const [selShot, setSelShot] = useState(null);
    const {
      project,
      setProject,
      thumbs,
      storeThumb,
      busy,
      projList,
      projMenu,
      setProjMenu,
      projectApi,
      importJSON
    } = useProjectStore(setSelShot);
    const {
      open,
      setOpen,
      setCard,
      setAct,
      setAssets,
      setCardStatus,
      addCard,
      dupCard,
      delCard,
      moveCard,
      moveCardToAct: moveCardToAct2,
      addAct,
      delAct,
      moveAct,
      addRef,
      setRef,
      delRef
    } = useShotMutations(project, setProject);
    const [pickCb, setPickCb] = useState(null);
    const [pickKind, setPickKind] = useState("image");
    const [pickAllowType, setPickAllowType] = useState(false);
    const [importOpen, setImportOpen] = useState(false);
    const [v2, setV2] = useState(false);
    const [showHelp, setShowHelp] = useState(false);
    const [showGuide, setShowGuide] = useState(() => {
      try {
        return !localStorage.getItem("loom_guide_seen");
      } catch (e) {
        return true;
      }
    });
    const [showCast, setShowCast] = useState(true);
    const openPick = useCallback((cb, kind, allowType) => {
      setPickKind(kind || "image");
      setPickAllowType(!!allowType);
      setPickCb(() => cb);
    }, []);
    const bindGalleryPicker = useCallback((el) => {
      if (el && !el._mgBound) {
        el._mgBound = true;
        el.addEventListener("mg-pick", (e) => {
          const cb = pickCb;
          setPickCb(null);
          if (cb) cb(e.detail.media_id, e.detail.thumb, e.detail.is_video, e.detail.duration);
        });
        el.addEventListener("mg-close", () => setPickCb(null));
      }
    }, [pickCb]);
    const {
      genState,
      genImgState,
      imgModel,
      setImgModel,
      genEditState,
      setGenEditState,
      genRefState,
      setGenRefState,
      batching,
      generateShot,
      useExistingVideo,
      genImage,
      routeImg,
      genEdit,
      genRef,
      routeGen,
      batchGenerate
    } = useGenerationPipeline({ project, thumbs, setCard, setCardStatus, setAssets, openPick });
    const { seq, exp, playSequence, exportCut, cancelExport, closeExport, closeSequence, exportAll, exportJSON } = useExportPipeline(project, thumbs);
    const importCollection = (items, cname) => {
      setImportOpen(false);
      if (!items || !items.length) return;
      setAssets((a) => {
        let n = maxTagNum(a, "@image");
        const added = items.map((it, i) => ({
          id: uid(),
          name: it.name || `${cname} ${i + 1}`,
          kind: "image",
          tag: "@image" + ++n,
          thumbId: "",
          source: "",
          mediaId: it.mediaId,
          lock: false
        }));
        return [...a, ...added];
      });
    };
    const copyShot = (entry) => navigator.clipboard?.writeText(shotText(entry, project));
    if (!project) return /* @__PURE__ */ React.createElement("div", { className: "sb-root" }, /* @__PURE__ */ React.createElement("style", null, STYLES), /* @__PURE__ */ React.createElement("div", { className: "sb-empty" }, "Loading the bay\u2026"));
    const entries = flat(project);
    const anyDone = entries.some((e) => e.c.resultMid);
    const { total, scale, over } = reelStats(entries, project.target);
    const done = entries.filter((x) => x.c.status === "done").length;
    return /* @__PURE__ */ React.createElement("div", { className: "sb-root" }, /* @__PURE__ */ React.createElement("style", null, STYLES), v2 && /* @__PURE__ */ React.createElement(V2Boundary, { onClose: () => setV2(false) }, /* @__PURE__ */ React.createElement(
      LoomV2,
      {
        onClose: () => setV2(false),
        project,
        setCard,
        setAssets,
        entries,
        durOf,
        scale,
        selShot,
        setSelShot,
        generateShot,
        useExistingVideo,
        genState,
        thumbs,
        openPick,
        storeThumb,
        setAct,
        addCard,
        dupCard,
        delCard,
        moveCard,
        moveCardToAct: moveCardToAct2,
        addAct,
        delAct,
        moveAct,
        genImgState,
        imgModel,
        setImgModel,
        genImage,
        routeImg,
        genEditState,
        setGenEditState,
        genRefState,
        setGenRefState,
        genEdit,
        genRef,
        routeGen,
        projectApi,
        playSequence
      }
    )), seq && /* @__PURE__ */ React.createElement(SequencePlayer, { clips: seq, onClose: closeSequence }), exp && /* @__PURE__ */ React.createElement("div", { className: "sb-seq", onClick: (e) => {
      if (e.target === e.currentTarget && exp.status !== "running") closeExport();
    } }, /* @__PURE__ */ React.createElement("div", { className: "sb-export-box" }, /* @__PURE__ */ React.createElement("div", { className: "sb-pick-head" }, /* @__PURE__ */ React.createElement("span", { className: "sb-pick-t" }, "Export the cut"), exp.status !== "running" && /* @__PURE__ */ React.createElement("button", { className: "sb-pick-x", onClick: closeExport }, "\xD7")), exp.status === "running" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "sb-exp-bar" }, /* @__PURE__ */ React.createElement("i", { style: { width: (exp.progress || 0) + "%" } })), /* @__PURE__ */ React.createElement("div", { className: "sb-exp-txt" }, "Rendering\u2026 ", exp.progress || 0, "% \xB7 ", Math.round(exp.elapsed || 0), "s of cut"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", style: { alignSelf: "center" }, onClick: cancelExport }, "\u25A0 Stop")), exp.status === "done" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "sb-exp-txt", style: { color: "var(--green)" } }, "\u2713 Cut rendered."), /* @__PURE__ */ React.createElement("a", { className: "sb-btn amber", href: "/api/loom/export-file", style: { alignSelf: "center", textDecoration: "none" } }, "\u21E9 Download mp4"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", style: { alignSelf: "center" }, onClick: closeExport }, "Close")), (exp.status === "failed" || exp.status === "cancelled") && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "sb-exp-txt", style: { color: exp.status === "failed" ? "var(--coral)" : "var(--ink2)" } }, exp.status === "failed" ? "\u26A0 " + (exp.error || "export failed") : "\u25A0 Export stopped."), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", style: { alignSelf: "center" }, onClick: closeExport }, "Close")))), pickCb && (pickAllowType ? /* @__PURE__ */ React.createElement("mg-gallery-picker", { ref: bindGalleryPicker, "default-type": pickKind, "show-type": true }) : /* @__PURE__ */ React.createElement("mg-gallery-picker", { ref: bindGalleryPicker, "default-type": pickKind })), importOpen && /* @__PURE__ */ React.createElement(ImportCollection, { onClose: () => setImportOpen(false), onImport: importCollection }), /* @__PURE__ */ React.createElement("header", { className: "sb-top" }, /* @__PURE__ */ React.createElement("div", { className: "sb-topgrid" }, /* @__PURE__ */ React.createElement("div", { className: "sb-brand" }, /* @__PURE__ */ React.createElement(
      "a",
      {
        href: "/",
        className: "sb-btn ghost sm",
        title: "Back to the gallery",
        style: { textDecoration: "none", flexShrink: 0 }
      },
      "\u2190 Gallery"
    ), /* @__PURE__ */ React.createElement("h1", { className: "sb-disp" }, /* @__PURE__ */ React.createElement("span", { className: "sb-clap" }, "\u25B0"), " The Loom"), /* @__PURE__ */ React.createElement("input", { className: "sb-projname", value: project.name, onChange: (e) => setProject((p) => ({ ...p, name: e.target.value })), "aria-label": "Project name" }), /* @__PURE__ */ React.createElement(ProjectSwitcher, { api: projectApi }), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-btn",
        onClick: () => batchGenerate(entries),
        disabled: batching || !entries.length,
        title: "Generate every shot that isn't done yet, one after another"
      },
      batching ? "\u25B6 generating all\u2026" : `\u25B6 Generate all (${entries.filter((e) => e.c.status !== "done").length})`
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-btn amber",
        onClick: () => playSequence(entries),
        disabled: !anyDone,
        title: "Play every finished shot back-to-back, honoring trims \u2014 a rough cut, no rendering"
      },
      "\u25B6\u25B6 Play"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-btn",
        onClick: () => exportCut(entries),
        disabled: !anyDone,
        title: "Trim + stitch every finished shot into one mp4 (ffmpeg)"
      },
      "\u21E9 Export"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-btn ghost sm",
        onClick: () => setV2(true),
        title: "Preview the new dockable V2 layout (non-destructive \u2014 your board is untouched)"
      },
      "\u25EB V2 layout"
    )), /* @__PURE__ */ React.createElement("div", { className: "sb-stat" }, /* @__PURE__ */ React.createElement("b", null, done, "/", entries.length), /* @__PURE__ */ React.createElement("span", null, "shots done")), /* @__PURE__ */ React.createElement("div", { className: "sb-stat" }, /* @__PURE__ */ React.createElement("b", { style: { color: over > 0 ? "var(--coral)" : "var(--ink)" } }, fmt(total)), /* @__PURE__ */ React.createElement("span", null, "of ", fmt(project.target), over > 0 ? ` \xB7 +${fmt(over)} over` : "")), /* @__PURE__ */ React.createElement("div", { className: "sb-saved", title: hasStore ? "Saved to this browser" : "In-memory only \u2014 export to keep" }, /* @__PURE__ */ React.createElement("span", { className: "sb-dot" + (busy ? " busy" : "") }), " ", hasStore ? busy ? "saving" : "saved" : "session only")), /* @__PURE__ */ React.createElement("div", { className: "sb-reel-wrap" }, /* @__PURE__ */ React.createElement("div", { className: "sb-reel" }, entries.map((x, i) => /* @__PURE__ */ React.createElement(
      "div",
      {
        key: i,
        className: "sb-seg " + x.c.status,
        style: { width: `${durOf(x.c) / scale * 100}%` },
        title: `${x.code} ${x.c.title || ""} \xB7 ${durOf(x.c)}s${x.c.actualDur ? " (rendered)" : ""}`
      }
    )), /* @__PURE__ */ React.createElement("div", { className: "sb-target", style: { left: `${project.target / scale * 100}%` } })), /* @__PURE__ */ React.createElement("div", { className: "sb-reel-legend" }, /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("i", { style: { background: "var(--surface1)" } }), "to do"), /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("i", { style: { background: "var(--amber)" } }), "in progress"), /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("i", { style: { background: "var(--green)" } }), "done"), /* @__PURE__ */ React.createElement("span", { style: { marginLeft: "auto" } }, entries.length, " clips \xB7 target 8:00")))), /* @__PURE__ */ React.createElement("div", { className: "sb-wrap" }, /* @__PURE__ */ React.createElement("div", { className: "sb-toolbar" }, /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm", onClick: () => setShowGuide((s) => !s) }, showGuide ? "Hide guide" : "? How it works"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", onClick: () => setShowHelp((s) => !s) }, showHelp ? "Hide cheat-sheet" : "Continuity cheat-sheet"), /* @__PURE__ */ React.createElement("div", { className: "sb-divider" }), /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm", onClick: exportAll }, "Export shot list (.txt)"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm", onClick: exportJSON }, "Backup (.json)"), /* @__PURE__ */ React.createElement("label", { className: "sb-btn sm ghost", style: { cursor: "pointer" } }, "Restore", /* @__PURE__ */ React.createElement("input", { type: "file", accept: "application/json", style: { display: "none" }, onChange: (e) => importJSON(e.target.files[0]) }))), showGuide && /* @__PURE__ */ React.createElement("div", { className: "sb-helpbox", style: { borderColor: "var(--amber-d)" } }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "baseline", gap: 10 } }, /* @__PURE__ */ React.createElement("h4", { style: { marginTop: 0 } }, "What the Loom is"), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-btn ghost sm",
        style: { marginLeft: "auto" },
        onClick: () => {
          setShowGuide(false);
          try {
            localStorage.setItem("loom_guide_seen", "1");
          } catch (e) {
          }
        }
      },
      "Got it"
    )), "The ", /* @__PURE__ */ React.createElement("b", null, "Generate"), " card makes ", /* @__PURE__ */ React.createElement("b", null, "one"), " clip. The Loom is where you ", /* @__PURE__ */ React.createElement("b", null, "direct a sequence"), " \u2014 plan a multi-shot video, generate each shot on PixAI, then trim and stitch them into one cut. Camera vs. editing suite.", /* @__PURE__ */ React.createElement("h4", null, "The flow, top to bottom"), /* @__PURE__ */ React.createElement("b", null, "1 \xB7 Cast & Assets"), " \u2014 build a pool of reusable people / places / refs. ", /* @__PURE__ */ React.createElement("code", null, "\u25A4 Pick from gallery"), " or ", /* @__PURE__ */ React.createElement("code", null, "\u21AF Import collection"), " to fill it fast; each keeps its media_id, so referencing it is free.", /* @__PURE__ */ React.createElement("br", null), /* @__PURE__ */ React.createElement("b", null, "2 \xB7 Shots"), " \u2014 add cards. Per shot: write the prompt, attach cast + open/close frames, set the mode (I2V / First\u2192Last / R2V) and duration (5/10/15s).", /* @__PURE__ */ React.createElement("br", null), /* @__PURE__ */ React.createElement("b", null, "3 \xB7 Generate shot"), " \u2014 renders on PixAI (free with a V4.0 card). The clip lands in your gallery and appears on the card.", /* @__PURE__ */ React.createElement("br", null), /* @__PURE__ */ React.createElement("b", null, "4 \xB7 Trim"), " \u2014 drag the amber in/out handles on each clip to keep only the good seconds.", /* @__PURE__ */ React.createElement("br", null), /* @__PURE__ */ React.createElement("b", null, "5 \xB7 Play & Export"), " \u2014 ", /* @__PURE__ */ React.createElement("code", null, "\u25B6\u25B6 Play"), " watches the rough cut back-to-back; ", /* @__PURE__ */ React.createElement("code", null, "\u21E9 Export"), " stitches it into one mp4.", /* @__PURE__ */ React.createElement("h4", null, "Chaining shots so cuts flow"), "Frame handoff, ", /* @__PURE__ */ React.createElement("code", null, "@tags"), ", and cast lock keep continuity across shots \u2014 open the ", /* @__PURE__ */ React.createElement("b", null, "Continuity cheat-sheet"), " for those."), showHelp && /* @__PURE__ */ React.createElement("div", { className: "sb-helpbox" }, /* @__PURE__ */ React.createElement("h4", null, "@references in plain terms"), "An ", /* @__PURE__ */ React.createElement("code", null, "@tag"), " is a name for a file you upload, numbered in upload order: the first image is ", /* @__PURE__ */ React.createElement("code", null, "@image1"), ", the first video ", /* @__PURE__ */ React.createElement("code", null, "@video1"), ", first audio ", /* @__PURE__ */ React.createElement("code", null, "@audio1"), ". In the prompt you say what each one is ", /* @__PURE__ */ React.createElement("b", null, "for"), " \u2014 identity, the opening frame, camera motion, the beat.", /* @__PURE__ */ React.createElement("h4", null, "Three ways to keep clips flowing"), /* @__PURE__ */ React.createElement("b", null, "Extend"), " \u2014 feed the previous clip as ", /* @__PURE__ */ React.createElement("code", null, "@video1"), "; the model anchors to its final frames and continues forward. Keep each extension ~5\u201310s.", /* @__PURE__ */ React.createElement("br", null), /* @__PURE__ */ React.createElement("b", null, "First\u2192Last"), " \u2014 give the shot a start image and an end image; prompt the ", /* @__PURE__ */ React.createElement("b", null, "motion between them"), ', not the stills, with "', CONTINUITY_PHRASE, '" Keep the two frames similar in composition or the subject warps.', /* @__PURE__ */ React.createElement("br", null), /* @__PURE__ */ React.createElement("b", null, "Cast lock"), " \u2014 define each recurring person/place once in ", /* @__PURE__ */ React.createElement("b", null, "Cast & Assets"), " and reuse the same ", /* @__PURE__ */ React.createElement("code", null, "@tag"), ' everywhere; the assembled prompt writes "maintain exact appearance from @image1" for you.', /* @__PURE__ */ React.createElement("h4", null, "The drift rule"), "Consistency fades the further you chain. Re-anchor to your original Cast reference every ", /* @__PURE__ */ React.createElement("b", null, "4\u20135 shots"), ", and your closing frame of one shot should be the opening frame of the next \u2014 that's the chain the board tracks.")), /* @__PURE__ */ React.createElement("div", { className: "sb-wrap", style: { paddingTop: 0 } }, /* @__PURE__ */ React.createElement("div", { className: "sb-panel" }, /* @__PURE__ */ React.createElement("div", { className: "sb-panelhead", onClick: () => setShowCast((s) => !s) }, /* @__PURE__ */ React.createElement("span", { className: "sb-ico" }, showCast ? "\u25BE" : "\u25B8"), /* @__PURE__ */ React.createElement("h3", { className: "sb-disp" }, "Cast & Assets"), /* @__PURE__ */ React.createElement("span", { className: "sb-hint", style: { marginLeft: "auto" } }, (project.assets || []).length, " reusable refs \u2014 define once, reuse everywhere")), showCast && /* @__PURE__ */ React.createElement("div", { className: "sb-panelbody" }, (project.assets || []).map((as) => {
      const prev = as.thumbId ? thumbs[as.thumbId] : as.mediaId ? "/thumbs/" + as.mediaId + ".jpg" : as.kind === "image" && as.source.startsWith("http") ? as.source : null;
      return /* @__PURE__ */ React.createElement("div", { className: "sb-assetrow", key: as.id }, as.kind === "image" ? /* @__PURE__ */ React.createElement("label", { className: "sb-assetprev", title: "Attach image" }, prev ? /* @__PURE__ */ React.createElement("img", { src: prev, alt: as.name }) : "\uFF0B", /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "file",
          accept: "image/*",
          style: { display: "none" },
          onChange: async (e) => {
            const f = e.target.files[0];
            if (!f) return;
            const id = await storeThumb(f);
            setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, thumbId: id, source: x.source || f.name, mediaId: "" }));
          }
        }
      )) : /* @__PURE__ */ React.createElement("div", { className: "sb-assetprev" }, as.kind === "video" ? "\u{1F39E}" : "\u266A"), as.kind === "image" && /* @__PURE__ */ React.createElement(
        "button",
        {
          className: "sb-ico",
          title: "Pick from the gallery",
          onClick: () => openPick((mid) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, mediaId: mid, thumbId: "", source: "" })))
        },
        "\u25A4"
      ), /* @__PURE__ */ React.createElement(
        "input",
        {
          className: "sb-in",
          style: { flex: "1 1 120px" },
          value: as.name,
          placeholder: "name (Her, Me, the room\u2026)",
          onChange: (e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, name: e.target.value }))
        }
      ), /* @__PURE__ */ React.createElement("input", { className: "sb-tagin sb-mono", value: as.tag, onChange: (e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, tag: e.target.value })) }), /* @__PURE__ */ React.createElement("select", { className: "sb-sel", style: { width: "auto" }, value: as.kind, onChange: (e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, kind: e.target.value })) }, /* @__PURE__ */ React.createElement("option", { value: "image" }, "image"), /* @__PURE__ */ React.createElement("option", { value: "video" }, "video"), /* @__PURE__ */ React.createElement("option", { value: "audio" }, "audio")), /* @__PURE__ */ React.createElement("label", { className: "sb-toggle", title: "Write 'maintain exact appearance' in prompts" }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: as.lock, onChange: (e) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, lock: e.target.checked })) }), "lock"), /* @__PURE__ */ React.createElement("button", { className: "sb-ico", onClick: () => setAssets((a) => a.filter((x) => x.id !== as.id)), title: "Remove" }, "\u2715"));
    }), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, flexWrap: "wrap", alignSelf: "flex-start" } }, /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-btn ghost sm",
        onClick: () => setAssets((a) => [...a, { id: uid(), name: "", kind: "image", tag: nextTag(a, "@image"), thumbId: "", source: "", lock: true }])
      },
      "+ Add reference"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-btn ghost sm",
        onClick: () => setImportOpen(true),
        title: "Pull a whole gallery collection in as reusable @image references"
      },
      "\u21AF Import collection"
    ))))), /* @__PURE__ */ React.createElement("main", { className: "sb-main" }, project.acts.map((act, ai) => {
      const sub = act.cards.reduce((s, c) => s + (Number(c.duration) || 0), 0);
      return /* @__PURE__ */ React.createElement("section", { className: "sb-act", key: act.id }, /* @__PURE__ */ React.createElement("div", { className: "sb-acthead" }, /* @__PURE__ */ React.createElement("button", { className: "sb-ico", onClick: () => setAct(act.id, { collapsed: !act.collapsed }) }, act.collapsed ? "\u25B8" : "\u25BE"), /* @__PURE__ */ React.createElement("span", { className: "sb-actcode sb-mono" }, actLetter(ai)), /* @__PURE__ */ React.createElement("input", { className: "sb-actname", value: act.name, onChange: (e) => setAct(act.id, { name: e.target.value }), "aria-label": "Act name" }), /* @__PURE__ */ React.createElement("span", { className: "sb-actmeta" }, act.cards.length, " \xB7 ", fmt(sub)), /* @__PURE__ */ React.createElement("button", { className: "sb-ico", onClick: () => moveAct(ai, -1), title: "Move act up" }, "\u2191"), /* @__PURE__ */ React.createElement("button", { className: "sb-ico", onClick: () => moveAct(ai, 1), title: "Move act down" }, "\u2193"), /* @__PURE__ */ React.createElement("button", { className: "sb-ico", onClick: () => delAct(act.id), title: "Delete act" }, "\u2715")), !act.collapsed && /* @__PURE__ */ React.createElement("div", { className: "sb-grid" }, act.cards.map((card, ci) => {
        const code = `${actLetter(ai)}\xB7${String(ci + 1).padStart(2, "0")}`;
        const gIdx = entries.findIndex((x) => x.c.id === card.id);
        const prev = gIdx > 0 ? entries[gIdx - 1] : null;
        return /* @__PURE__ */ React.createElement(CardView, { key: card.id, ...{
          act,
          card,
          ci,
          ai,
          code,
          prev,
          project,
          thumbs,
          open,
          setOpen,
          setCard,
          addRef,
          setRef,
          delRef,
          storeThumb,
          dupCard,
          delCard,
          moveCard,
          moveCardToAct: moveCardToAct2,
          copyShot,
          generateShot,
          genState,
          entries,
          openPick
        } });
      }), /* @__PURE__ */ React.createElement("button", { className: "sb-add", onClick: () => addCard(act.id) }, "+ Add shot to ", act.name)));
    }), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost", onClick: addAct, style: { marginTop: 6 } }, "+ Add act")));
  }
  function ShotPreview({ mid, trimIn, trimOut, onTrim }) {
    const vidRef = useRef(null), trackRef = useRef(null);
    const [dur, setDur] = useState(0);
    const [range, setRange] = useState({ in: trimIn || 0, out: trimOut });
    const [playing, setPlaying] = useState(false);
    const rangeRef = useRef(range);
    rangeRef.current = range;
    const durRef = useRef(0);
    durRef.current = dur;
    const dragRef = useRef(null);
    useEffect(() => {
      setRange({ in: trimIn || 0, out: trimOut });
    }, [trimIn, trimOut]);
    const effOut = (range.out == null ? dur : range.out) || dur;
    const pct = (s) => dur ? Math.max(0, Math.min(100, s / dur * 100)) : 0;
    const fT = (s) => (s || 0).toFixed(1) + "s";
    const secAt = (clientX) => {
      const t = trackRef.current.getBoundingClientRect();
      return Math.max(0, Math.min(durRef.current, (clientX - t.left) / t.width * durRef.current));
    };
    const scrub = (e) => {
      if (playing) return;
      const v = vidRef.current;
      if (!v || !dur) return;
      const r = e.currentTarget.getBoundingClientRect();
      const t = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
      v.currentTime = range.in + t * Math.max(0.01, effOut - range.in);
    };
    const togglePlay = (e) => {
      e.stopPropagation();
      const v = vidRef.current;
      if (!v) return;
      if (playing) {
        v.pause();
        setPlaying(false);
        return;
      }
      if (v.currentTime < range.in || v.currentTime >= effOut) v.currentTime = range.in;
      v.play();
      setPlaying(true);
    };
    const onTimeUpdate = (e) => {
      if (playing && e.currentTarget.currentTime >= effOut) {
        e.currentTarget.pause();
        e.currentTarget.currentTime = range.in;
        setPlaying(false);
      }
    };
    const onMove = (e) => {
      if (!dragRef.current || !durRef.current) return;
      const s = secAt(e.clientX), r = rangeRef.current, eff = r.out == null ? durRef.current : r.out;
      setRange(dragRef.current === "in" ? { ...r, in: Math.min(s, eff - 0.1) } : { ...r, out: Math.max(s, r.in + 0.1) });
      const v = vidRef.current;
      if (v) v.currentTime = s;
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      if (dragRef.current) {
        const r = rangeRef.current;
        onTrim(r.in, r.out);
      }
      dragRef.current = null;
    };
    const startDrag = (which) => (e) => {
      e.preventDefault();
      e.stopPropagation();
      dragRef.current = which;
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    };
    const trimmed = range.in > 0 || range.out != null;
    return /* @__PURE__ */ React.createElement("div", { className: "sb-shotprev-wrap" }, /* @__PURE__ */ React.createElement(
      "div",
      {
        className: "sb-shotprev",
        onMouseMove: scrub,
        onMouseLeave: () => {
          if (playing) return;
          const v = vidRef.current;
          if (v) v.currentTime = range.in;
        }
      },
      /* @__PURE__ */ React.createElement(
        "video",
        {
          ref: vidRef,
          src: "/video-file/" + mid,
          muted: true,
          preload: "metadata",
          playsInline: true,
          onLoadedMetadata: (e) => setDur(e.currentTarget.duration || 0),
          onTimeUpdate,
          onEnded: () => setPlaying(false)
        }
      ),
      /* @__PURE__ */ React.createElement("button", { className: "sb-shotprev-play", onClick: togglePlay, title: playing ? "Pause" : "Play" }, playing ? "\u23F8" : "\u25B6"),
      /* @__PURE__ */ React.createElement("div", { className: "sb-shotprev-hint" }, "hover to scrub")
    ), /* @__PURE__ */ React.createElement("div", { className: "sb-trim" }, /* @__PURE__ */ React.createElement(
      "div",
      {
        className: "sb-trim-track",
        ref: trackRef,
        onPointerDown: (e) => {
          const v = vidRef.current;
          if (v && dur) v.currentTime = secAt(e.clientX);
        }
      },
      /* @__PURE__ */ React.createElement("div", { className: "sb-trim-sel", style: { left: pct(range.in) + "%", right: 100 - pct(effOut) + "%" } }),
      /* @__PURE__ */ React.createElement("div", { className: "sb-trim-h", style: { left: pct(range.in) + "%" }, onPointerDown: startDrag("in"), title: "Trim in" }),
      /* @__PURE__ */ React.createElement("div", { className: "sb-trim-h", style: { left: pct(effOut) + "%" }, onPointerDown: startDrag("out"), title: "Trim out" })
    ), /* @__PURE__ */ React.createElement("div", { className: "sb-trim-read" }, fT(range.in), " \u2192 ", fT(effOut), " \xB7 ", /* @__PURE__ */ React.createElement("b", null, fT(Math.max(0, effOut - range.in))), " kept", trimmed && /* @__PURE__ */ React.createElement("button", { className: "sb-trim-reset", onClick: () => onTrim(0, null) }, "reset"))));
  }
  function SequencePlayer({ clips, onClose }) {
    const vRef = useRef(null);
    const [i, setI] = useState(0);
    const clip = clips[i];
    useEffect(() => {
      const v = vRef.current;
      if (!v || !clip) return;
      const seekPlay = () => {
        try {
          v.currentTime = clip.in || 0;
        } catch (e) {
        }
        v.play().catch(() => {
        });
      };
      const onTime = () => {
        const end = (clip.out != null ? clip.out : v.duration) || 0;
        if (end && v.currentTime >= end - 0.04) {
          if (i < clips.length - 1) setI(i + 1);
          else onClose();
        }
      };
      v.addEventListener("loadedmetadata", seekPlay);
      v.addEventListener("timeupdate", onTime);
      if (v.readyState >= 1) seekPlay();
      return () => {
        v.removeEventListener("loadedmetadata", seekPlay);
        v.removeEventListener("timeupdate", onTime);
      };
    }, [i]);
    useEffect(() => {
      const esc = (e) => {
        if (e.key === "Escape") onClose();
      };
      window.addEventListener("keydown", esc);
      return () => window.removeEventListener("keydown", esc);
    }, []);
    if (!clip) return null;
    return /* @__PURE__ */ React.createElement("div", { className: "sb-seq", onClick: (e) => {
      if (e.target === e.currentTarget) onClose();
    } }, /* @__PURE__ */ React.createElement("div", { className: "sb-seq-box" }, /* @__PURE__ */ React.createElement(
      "video",
      {
        ref: vRef,
        key: clip.mid,
        src: "/video-file/" + clip.mid,
        autoPlay: true,
        muted: true,
        playsInline: true,
        onClick: (e) => {
          const v = e.currentTarget;
          v.paused ? v.play() : v.pause();
        }
      }
    ), /* @__PURE__ */ React.createElement("div", { className: "sb-seq-bar" }, /* @__PURE__ */ React.createElement("span", null, "Shot ", i + 1, "/", clips.length, clip.code ? " \xB7 " + clip.code : "", clip.title ? " \u2014 " + clip.title : ""), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", onClick: () => setI(Math.max(0, i - 1)), disabled: i === 0 }, "\u25C0 prev"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", onClick: () => {
      if (i < clips.length - 1) setI(i + 1);
      else onClose();
    } }, "next \u25B6"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm", onClick: onClose }, "\u2715 close"))));
  }
  function CardView({ act, card, ci, ai, code, prev, project, thumbs, open, setOpen, setCard, addRef, setRef, delRef, storeThumb, dupCard, delCard, moveCard, moveCardToAct: moveCardToAct2, copyShot, generateShot, genState, entries, openPick }) {
    const isOpen = open[card.id];
    const framePrev = (f) => f.thumbId ? thumbs[f.thumbId] : f.mediaId ? "/thumbs/" + f.mediaId + ".jpg" : f.source && f.source.startsWith("http") ? f.source : null;
    const openImg = framePrev(card.openFrame), closeImg = framePrev(card.closeFrame);
    const prevClose = prev ? prev.c.closeFrame : null;
    const linked = prev && frameLinked(card.openFrame, prevClose);
    const needsLink = prev && (card.connect === "extend" || card.connect === "flf" || card.connect === "cut");
    const entry = { c: card, code, ai, ci };
    return /* @__PURE__ */ React.createElement("article", { className: "sb-card" + (isOpen ? " open" : "") }, prev && card.connect !== "new" && /* @__PURE__ */ React.createElement("div", { className: "sb-fromstrip" }, /* @__PURE__ */ React.createElement("span", { className: "sb-linkdot " + (linked ? "sb-link-ok" : needsLink ? "sb-link-warn" : "") }, linked ? "\u2713" : needsLink ? "\u26A0" : "\xB7"), linked ? `opens on ${prev.code}'s closing frame` : needsLink ? `open frame \u2260 ${prev.code} close \u2014 link it` : `from ${prev.code}`, /* @__PURE__ */ React.createElement("span", { className: "sb-connbadge" }, connectMeta(card.connect).label)), /* @__PURE__ */ React.createElement("div", { className: "sb-slate" }, /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-tick " + card.status,
        title: `Status: ${card.status} (click to cycle)`,
        onClick: () => setCard(act.id, card.id, (c) => ({ ...c, status: c.status === "todo" ? "wip" : c.status === "wip" ? "done" : "todo" }))
      },
      "\u2713"
    ), /* @__PURE__ */ React.createElement("span", { className: "sb-code" }, code), /* @__PURE__ */ React.createElement("input", { className: "sb-ctitle", placeholder: "shot title\u2026", value: card.title, onChange: (e) => setCard(act.id, card.id, (c) => ({ ...c, title: e.target.value })) }), /* @__PURE__ */ React.createElement("span", { className: "sb-mode" }, card.mode), /* @__PURE__ */ React.createElement("span", { className: "sb-tc" }, card.duration, "s"), /* @__PURE__ */ React.createElement("button", { className: "sb-ico", onClick: () => setOpen((o) => ({ ...o, [card.id]: !isOpen })), title: isOpen ? "Collapse" : "Edit" }, isOpen ? "\u25BE" : "\u270E")), !isOpen ? /* @__PURE__ */ React.createElement("div", { className: "sb-body" }, /* @__PURE__ */ React.createElement("div", { className: "sb-frames-mini" }, /* @__PURE__ */ React.createElement("div", { className: "sb-fm" }, /* @__PURE__ */ React.createElement("div", { className: "sb-fmlab" }, /* @__PURE__ */ React.createElement("span", null, "open")), /* @__PURE__ */ React.createElement("div", { className: "sb-fmbox" + (card.discreet ? " discreet" : "") }, openImg ? /* @__PURE__ */ React.createElement("img", { src: openImg, alt: "open" }) : card.openFrame.desc || "\u2014")), /* @__PURE__ */ React.createElement("div", { className: "sb-arrowmid" }, "\u2192"), /* @__PURE__ */ React.createElement("div", { className: "sb-fm" }, /* @__PURE__ */ React.createElement("div", { className: "sb-fmlab" }, /* @__PURE__ */ React.createElement("span", null, "close")), /* @__PURE__ */ React.createElement("div", { className: "sb-fmbox" + (card.discreet ? " discreet" : "") }, closeImg ? /* @__PURE__ */ React.createElement("img", { src: closeImg, alt: "close" }) : card.closeFrame.desc || "\u2014"))), /* @__PURE__ */ React.createElement("div", { className: "sb-prompt-mini" + (card.prompt ? "" : " empty"), onClick: () => setOpen((o) => ({ ...o, [card.id]: true })) }, card.prompt || "no prompt yet \u2014 tap to write"), /* @__PURE__ */ React.createElement("div", { className: "sb-minimeta" }, card.camera && /* @__PURE__ */ React.createElement("span", { className: "sb-chip" }, /* @__PURE__ */ React.createElement("b", null, "cam"), " ", card.camera), card.cast.length > 0 && /* @__PURE__ */ React.createElement("span", { className: "sb-chip" }, /* @__PURE__ */ React.createElement("b", null, "cast"), " ", card.cast.length))) : /* @__PURE__ */ React.createElement(CardEditor, { ...{ act, card, ci, ai, prev, project, thumbs, setCard, addRef, setRef, delRef, storeThumb, dupCard, delCard, moveCard, moveCardToAct: moveCardToAct2, copyShot, generateShot, genState, entry, framePrev, openPick } }));
  }
  function ImportCollection({ onImport, onClose }) {
    const [colls, setColls] = useState([]);
    const [sel, setSel] = useState("");
    const [total, setTotal] = useState(0);
    const CAP = 48;
    useEffect(() => {
      fetch("/api/collections").then((r) => r.json()).then((d) => setColls(d.collections || [])).catch(() => {
      });
    }, []);
    useEffect(() => {
      if (!sel) {
        setTotal(0);
        return;
      }
      fetch(`/api/gallery-images?type=image&limit=1&collection=${encodeURIComponent(sel)}`).then((r) => r.json()).then((d) => setTotal(d.total || 0)).catch(() => {
      });
    }, [sel]);
    const doImport = () => {
      if (!sel) return;
      fetch(`/api/gallery-images?type=image&limit=${CAP}&sort=newest&collection=${encodeURIComponent(sel)}`).then((r) => r.json()).then((d) => onImport((d.images || []).map((m) => ({ mediaId: m.media_id, name: (m.prompt || "").slice(0, 26) })), sel)).catch(() => {
      });
    };
    return /* @__PURE__ */ React.createElement("div", { className: "sb-pick-ov", onClick: (e) => {
      if (e.target === e.currentTarget) onClose();
    } }, /* @__PURE__ */ React.createElement("div", { className: "sb-pick-box", style: { height: "auto", width: 520 } }, /* @__PURE__ */ React.createElement("div", { className: "sb-pick-head" }, /* @__PURE__ */ React.createElement("span", { className: "sb-pick-t" }, "Import a collection"), /* @__PURE__ */ React.createElement("button", { className: "sb-pick-x", onClick: onClose, title: "Close" }, "\xD7")), /* @__PURE__ */ React.createElement("p", { style: { fontSize: 12.5, color: "var(--ink2)", margin: "0 0 4px", lineHeight: 1.5 } }, "Pull a gallery collection in as reusable ", /* @__PURE__ */ React.createElement("b", null, "@image"), " references. Each keeps its PixAI media_id, so every one generates ", /* @__PURE__ */ React.createElement("b", null, "free"), " \u2014 no re-upload."), /* @__PURE__ */ React.createElement("div", { className: "sb-pick-filters" }, /* @__PURE__ */ React.createElement("select", { value: sel, onChange: (e) => setSel(e.target.value), style: { flex: 1, maxWidth: "none" } }, /* @__PURE__ */ React.createElement("option", { value: "" }, "Choose a collection\u2026"), colls.map((c) => /* @__PURE__ */ React.createElement("option", { key: c, value: c }, c)))), sel && /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: "var(--ink3)", margin: "6px 0 0" } }, total.toLocaleString(), " image", total === 1 ? "" : "s", total > CAP ? ` \u2014 importing the newest ${CAP}` : ""), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 12 } }, /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", onClick: onClose }, "Cancel"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn amber sm", disabled: !sel, onClick: doImport }, "Import references"))));
  }
  function FrameSlot({ which, frame, discreet, framePrev, onPatch, storeThumb, openPick, extraBtn }) {
    const img = framePrev(frame);
    return /* @__PURE__ */ React.createElement("div", { className: "sb-frame" }, /* @__PURE__ */ React.createElement("div", { className: "sb-framehead" }, /* @__PURE__ */ React.createElement("span", { className: "sb-lab" }, which === "open" ? "Opening frame" : "Closing frame"), openPick && /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-ico",
        title: "Pick from the gallery",
        onClick: () => openPick((mid) => onPatch({ mediaId: mid, thumbId: "", source: "" }))
      },
      "\u25A4"
    ), /* @__PURE__ */ React.createElement("input", { className: "sb-tagin sb-mono", placeholder: "@image1", value: frame.tag, onChange: (e) => onPatch({ tag: e.target.value }) })), /* @__PURE__ */ React.createElement("label", { className: "sb-frameprev" + (discreet ? " discreet" : ""), title: "Attach image" }, img ? /* @__PURE__ */ React.createElement("img", { src: img, alt: which }) : "\uFF0B attach frame", /* @__PURE__ */ React.createElement(
      "input",
      {
        type: "file",
        accept: "image/*",
        style: { display: "none" },
        onChange: async (e) => {
          const f = e.target.files[0];
          if (!f) return;
          const id = await storeThumb(f);
          onPatch({ thumbId: id, source: frame.source || f.name, mediaId: "" });
        }
      }
    )), /* @__PURE__ */ React.createElement("input", { className: "sb-in", placeholder: "describe this frame (composition, subject position, light)", value: frame.desc, onChange: (e) => onPatch({ desc: e.target.value }) }), extraBtn);
  }
  function CardEditor({ act, card, ci, ai, prev, project, thumbs, setCard, addRef, setRef, delRef, storeThumb, dupCard, delCard, moveCard, moveCardToAct: moveCardToAct2, copyShot, generateShot, genState, entry, framePrev, openPick }) {
    const [palFor, setPalFor] = useState(null);
    const setF = (field, val) => setCard(act.id, card.id, (c) => ({ ...c, [field]: val }));
    const append = (field, val) => setCard(act.id, card.id, (c) => ({ ...c, [field]: c[field] ? `${c[field]}, ${val}` : val }));
    const patchFrame = (key, patch) => setCard(act.id, card.id, (c) => ({ ...c, [key]: { ...c[key], ...patch } }));
    const [handoff, setHandoff] = useState("");
    const inheritPrev = () => {
      if (!prev) return;
      const rmid = prev.c.resultMid;
      if (rmid) {
        setHandoff("wip");
        fetch("/api/loom/handoff", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_media_id: rmid })
        }).then((r) => r.json()).then((d) => {
          if (d.error || !d.frame_media_id) {
            setHandoff("err");
            return;
          }
          setHandoff("");
          patchFrame("openFrame", {
            mediaId: d.frame_media_id,
            thumbId: "",
            source: "",
            desc: "handed off from " + (prev.code || "prev shot")
          });
        }).catch(() => setHandoff("err"));
      } else {
        patchFrame("openFrame", { ...prev.c.closeFrame });
      }
    };
    const toggleCast = (id) => setCard(act.id, card.id, (c) => ({ ...c, cast: c.cast.includes(id) ? c.cast.filter((x) => x !== id) : [...c.cast, id] }));
    return /* @__PURE__ */ React.createElement("div", { className: "sb-edit" }, /* @__PURE__ */ React.createElement("div", { className: "sb-row" }, /* @__PURE__ */ React.createElement("div", { className: "sb-field", style: { flex: "0 0 110px" } }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Mode"), /* @__PURE__ */ React.createElement("select", { className: "sb-sel", value: card.mode, onChange: (e) => setF("mode", e.target.value) }, MODES.map((m) => /* @__PURE__ */ React.createElement("option", { key: m }, m))), /* @__PURE__ */ React.createElement("span", { className: "sb-hint" }, MODE_HINT[card.mode])), /* @__PURE__ */ React.createElement("div", { className: "sb-field", style: { flex: "0 0 150px" } }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Joins previous via"), /* @__PURE__ */ React.createElement("select", { className: "sb-sel", value: card.connect, onChange: (e) => setF("connect", e.target.value) }, Object.entries(CONNECT).map(([k, v]) => /* @__PURE__ */ React.createElement("option", { key: k, value: k }, v.label))), /* @__PURE__ */ React.createElement("span", { className: "sb-hint" }, connectMeta(card.connect).hint)), /* @__PURE__ */ React.createElement("div", { className: "sb-field", style: { flex: "0 0 90px" } }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Duration (s)"), /* @__PURE__ */ React.createElement("input", { className: "sb-in", type: "number", min: "1", value: card.duration, onChange: (e) => setF("duration", Number(e.target.value)) })), /* @__PURE__ */ React.createElement("div", { className: "sb-field", style: { flex: "0 0 auto", justifyContent: "flex-end" } }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Discreet"), /* @__PURE__ */ React.createElement("label", { className: "sb-toggle", title: "Blur this shot's frames/refs on the board" }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: card.discreet, onChange: (e) => setF("discreet", e.target.checked) }), "blur previews"))), /* @__PURE__ */ React.createElement("div", { className: "sb-section" }, /* @__PURE__ */ React.createElement("h5", null, "Frame handoff \u2014 close of one shot opens the next"), /* @__PURE__ */ React.createElement("div", { className: "sb-twoframes" }, /* @__PURE__ */ React.createElement(
      FrameSlot,
      {
        which: "open",
        frame: card.openFrame,
        discreet: card.discreet,
        framePrev,
        storeThumb,
        openPick,
        onPatch: (p) => patchFrame("openFrame", p),
        extraBtn: prev ? /* @__PURE__ */ React.createElement(
          "button",
          {
            className: "sb-btn ghost sm",
            onClick: inheritPrev,
            disabled: handoff === "wip",
            title: prev.c.resultMid ? `Splice in ${prev.code}'s generated clip's last frame` : `Copy ${prev.code}'s closing frame here`
          },
          handoff === "wip" ? "\u2702 splicing\u2026" : handoff === "err" ? "\u2702 splice failed \u2014 retry" : prev.c.resultMid ? `\u2702 splice ${prev.code}'s last frame` : `\u21B3 inherit ${prev.code} close`
        ) : /* @__PURE__ */ React.createElement("span", { className: "sb-hint" }, "first shot \u2014 no previous frame")
      }
    ), /* @__PURE__ */ React.createElement("div", { className: "sb-conn-mid" }, "\u2192"), /* @__PURE__ */ React.createElement(
      FrameSlot,
      {
        which: "close",
        frame: card.closeFrame,
        discreet: card.discreet,
        framePrev,
        storeThumb,
        openPick,
        onPatch: (p) => patchFrame("closeFrame", p)
      }
    )), /* @__PURE__ */ React.createElement("span", { className: "sb-hint", style: { marginTop: 6 } }, "For First\u2192Last shots, prompt the motion between these two \u2014 not the stills. Keep them close in composition so the subject doesn't warp.")), /* @__PURE__ */ React.createElement("div", { className: "sb-field" }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Prompt \u2014 lead with subject + action"), /* @__PURE__ */ React.createElement(
      "textarea",
      {
        className: "sb-ta big",
        value: card.prompt,
        onChange: (e) => setF("prompt", e.target.value),
        placeholder: card.connect === "extend" ? "What happens next as the previous clip continues (motion only)\u2026" : "Who/what is in frame and what they're doing first; then environment, then style\u2026"
      }
    )), (project.assets || []).length > 0 && /* @__PURE__ */ React.createElement("div", { className: "sb-field" }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Cast in this shot \u2014 keeps them consistent"), /* @__PURE__ */ React.createElement("div", { className: "sb-casttoggle" }, project.assets.map((as) => /* @__PURE__ */ React.createElement("button", { key: as.id, className: "sb-castchip" + (card.cast.includes(as.id) ? " on" : ""), onClick: () => toggleCast(as.id) }, as.name || "(unnamed)", " ", /* @__PURE__ */ React.createElement("span", { className: "sb-ct" }, as.tag), as.lock ? " \u{1F512}" : "")))), /* @__PURE__ */ React.createElement("div", { className: "sb-field" }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Other references & @tags"), card.refs.map((r) => {
      const preview = r.thumbId ? thumbs[r.thumbId] : r.kind === "image" && r.source.startsWith("http") ? r.source : null;
      return /* @__PURE__ */ React.createElement("div", { className: "sb-ref", key: r.id }, r.kind === "image" ? /* @__PURE__ */ React.createElement("label", { className: "sb-refprev" + (card.discreet ? " discreet" : ""), title: "Attach image" }, preview ? /* @__PURE__ */ React.createElement("img", { src: preview, alt: r.tag }) : "\uFF0B", /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "file",
          accept: "image/*",
          style: { display: "none" },
          onChange: async (e) => {
            const f = e.target.files[0];
            if (!f) return;
            const id = await storeThumb(f);
            setRef(act.id, card.id, r.id, { thumbId: id, source: r.source || f.name });
          }
        }
      )) : /* @__PURE__ */ React.createElement("div", { className: "sb-refprev" }, r.kind === "video" ? "\u{1F39E}" : "\u266A"), /* @__PURE__ */ React.createElement("div", { className: "sb-refbody" }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("input", { className: "sb-tagin sb-mono", value: r.tag, onChange: (e) => setRef(act.id, card.id, r.id, { tag: e.target.value }) }), /* @__PURE__ */ React.createElement("span", { className: "sb-hint" }, r.kind), /* @__PURE__ */ React.createElement("button", { className: "sb-ico", style: { marginLeft: "auto" }, onClick: () => delRef(act.id, card.id, r) }, "\u2715")), /* @__PURE__ */ React.createElement("input", { className: "sb-in", placeholder: "what to use it for (motion / camera / mood\u2026)", value: r.role, onChange: (e) => setRef(act.id, card.id, r.id, { role: e.target.value }) }), /* @__PURE__ */ React.createElement("input", { className: "sb-in", placeholder: "file name or URL", value: r.source, onChange: (e) => setRef(act.id, card.id, r.id, { source: e.target.value }) })));
    }), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 7, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm ghost", onClick: () => addRef(act.id, card, "image") }, "+ Image"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm ghost", onClick: () => addRef(act.id, card, "video") }, "+ Video"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm ghost", onClick: () => addRef(act.id, card, "audio") }, "+ Audio"))), /* @__PURE__ */ React.createElement("div", { className: "sb-field" }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Camera ", /* @__PURE__ */ React.createElement("button", { className: "sb-ico", style: { fontSize: 11 }, onClick: () => setPalFor(palFor === "camera" ? null : "camera") }, "\uFF0Bterms")), /* @__PURE__ */ React.createElement("input", { className: "sb-in", value: card.camera, onChange: (e) => setF("camera", e.target.value), placeholder: "e.g. CU, slow push in, shallow depth of field" }), palFor === "camera" && /* @__PURE__ */ React.createElement("div", { className: "sb-pal" }, Object.entries(CAM_PALETTE).map(([grp, items]) => /* @__PURE__ */ React.createElement(React.Fragment, { key: grp }, /* @__PURE__ */ React.createElement("div", { className: "sb-palgrp" }, grp), items.map((t) => /* @__PURE__ */ React.createElement("button", { key: t, className: "sb-pchip sb-mono", onClick: () => append("camera", t) }, t)))))), /* @__PURE__ */ React.createElement("div", { className: "sb-row" }, /* @__PURE__ */ React.createElement("div", { className: "sb-field" }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Lighting & mood ", /* @__PURE__ */ React.createElement("button", { className: "sb-ico", style: { fontSize: 11 }, onClick: () => setPalFor(palFor === "lighting" ? null : "lighting") }, "\uFF0Bterms")), /* @__PURE__ */ React.createElement("input", { className: "sb-in", value: card.lighting, onChange: (e) => setF("lighting", e.target.value), placeholder: "golden hour, low-key, warm haze\u2026" }), palFor === "lighting" && /* @__PURE__ */ React.createElement("div", { className: "sb-pal" }, LIGHTING_PALETTE.map((t) => /* @__PURE__ */ React.createElement("button", { key: t, className: "sb-pchip sb-mono", onClick: () => append("lighting", t) }, t)))), /* @__PURE__ */ React.createElement("div", { className: "sb-field" }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Music / audio cue ", /* @__PURE__ */ React.createElement("button", { className: "sb-ico", style: { fontSize: 11 }, onClick: () => setPalFor(palFor === "audio" ? null : "audio") }, "\uFF0Bterms")), /* @__PURE__ */ React.createElement("input", { className: "sb-in", value: card.audioCue, onChange: (e) => setF("audioCue", e.target.value), placeholder: "track, beat sync, room tone\u2026" }), palFor === "audio" && /* @__PURE__ */ React.createElement("div", { className: "sb-pal" }, AUDIO_PALETTE.map((t) => /* @__PURE__ */ React.createElement("button", { key: t, className: "sb-pchip sb-mono", onClick: () => append("audioCue", t) }, t))))), /* @__PURE__ */ React.createElement("div", { className: "sb-row" }, /* @__PURE__ */ React.createElement("div", { className: "sb-field" }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Transition in ", /* @__PURE__ */ React.createElement("button", { className: "sb-ico", style: { fontSize: 11 }, onClick: () => setPalFor(palFor === "in" ? null : "in") }, "\uFF0B")), /* @__PURE__ */ React.createElement("input", { className: "sb-in", value: card.transIn, onChange: (e) => setF("transIn", e.target.value), placeholder: "cut, fade in\u2026" }), palFor === "in" && /* @__PURE__ */ React.createElement("div", { className: "sb-pal" }, TRANS_PALETTE.map((t) => /* @__PURE__ */ React.createElement("button", { key: t, className: "sb-pchip sb-mono", onClick: () => setF("transIn", t) }, t)))), /* @__PURE__ */ React.createElement("div", { className: "sb-field" }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Transition out ", /* @__PURE__ */ React.createElement("button", { className: "sb-ico", style: { fontSize: 11 }, onClick: () => setPalFor(palFor === "out" ? null : "out") }, "\uFF0B")), /* @__PURE__ */ React.createElement("input", { className: "sb-in", value: card.transOut, onChange: (e) => setF("transOut", e.target.value), placeholder: "cut, dissolve\u2026" }), palFor === "out" && /* @__PURE__ */ React.createElement("div", { className: "sb-pal" }, TRANS_PALETTE.map((t) => /* @__PURE__ */ React.createElement("button", { key: t, className: "sb-pchip sb-mono", onClick: () => setF("transOut", t) }, t))))), /* @__PURE__ */ React.createElement("div", { className: "sb-field" }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Notes"), /* @__PURE__ */ React.createElement("textarea", { className: "sb-ta", value: card.notes, onChange: (e) => setF("notes", e.target.value), placeholder: "blocking, continuity reminders\u2026" })), /* @__PURE__ */ React.createElement("div", { className: "sb-toolbar" }, /* @__PURE__ */ React.createElement("button", { className: "sb-btn amber sm", onClick: () => copyShot(entry) }, "Copy shot"), (() => {
      const g = genState[card.id] || {};
      const busy = g.phase === "submitting" || g.phase === "running";
      return /* @__PURE__ */ React.createElement(
        "button",
        {
          className: "sb-btn sm",
          disabled: busy,
          onClick: () => generateShot(entry),
          title: "Render this shot on PixAI (free with a V4.0 card)"
        },
        busy ? "Generating\u2026" : "\u25B6 Generate shot"
      );
    })(), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", onClick: () => moveCard(act.id, ci, -1) }, "\u2191"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", onClick: () => moveCard(act.id, ci, 1) }, "\u2193"), /* @__PURE__ */ React.createElement("select", { className: "sb-sel sm", style: { width: "auto", fontSize: 12, padding: "6px 8px" }, value: "", onChange: (e) => e.target.value && moveCardToAct2(act.id, card, e.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "" }, "move to act\u2026"), project.acts.filter((a) => a.id !== act.id).map((a) => /* @__PURE__ */ React.createElement("option", { key: a.id, value: a.id }, a.name))), /* @__PURE__ */ React.createElement("div", { className: "sb-divider" }), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", onClick: () => dupCard(act.id, card) }, "Duplicate"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm danger", onClick: () => delCard(act.id, card) }, "Delete")), (() => {
      const g = genState[card.id];
      if (!g) return null;
      const col = g.phase === "done" ? "var(--green)" : g.phase === "error" ? "var(--coral)" : "var(--amber)";
      return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { style: { fontSize: 12, color: col, display: "flex", alignItems: "center", gap: 10, marginTop: 2 } }, /* @__PURE__ */ React.createElement("span", null, g.phase === "done" ? "\u2713 " : g.phase === "error" ? "\u26A0 " : "\u2026 ", g.msg), g.phase === "done" && g.mid && /* @__PURE__ */ React.createElement(
        "a",
        {
          className: "sb-mono",
          href: "/image/" + g.mid,
          target: "_blank",
          rel: "noreferrer",
          style: { color: "var(--cyan)" }
        },
        "open full \u2197"
      )));
    })(), card.resultMid && /* @__PURE__ */ React.createElement(
      ShotPreview,
      {
        mid: card.resultMid,
        trimIn: card.trimIn,
        trimOut: card.trimOut,
        onTrim: (i, o) => setCard(act.id, card.id, (c) => ({ ...c, trimIn: i, trimOut: o }))
      }
    ));
  }
  return __toCommonJS(master_storyboard_exports);
})();
