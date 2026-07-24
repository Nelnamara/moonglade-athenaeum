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
  var continuityLinked = (entries, entryId) => {
    const idx = (entries || []).findIndex((x) => x.c.id === entryId);
    if (idx <= 0) return false;
    return frameLinked(entries[idx - 1].c.closeFrame, entries[idx].c.openFrame);
  };
  var connectMeta = (connect) => CONNECT[connect] || CONNECT.new;
  var flat = (p) => p.acts.flatMap((a, ai) => a.cards.map((c, ci) => ({ c, a, ai, ci, code: `${actLetter(ai)}\xB7${String(ci + 1).padStart(2, "0")}` })));
  var effectivePrompt = (c) => c.promptOverride ? c.promptOverrideText || "" : c.prompt || "";
  var shotImageRefs = (entry, project, imgSrc) => {
    const c = entry.c;
    const tagNum = (t) => {
      const m = /(\d+)/.exec(t || "");
      return m ? +m[1] : 99;
    };
    const items = [];
    (project.assets || []).filter((as) => as.kind === "image" && c.cast.includes(as.id)).forEach((as) => {
      const d = as.mediaId || imgSrc(as.thumbId, as.source);
      if (d) items.push({ tag: as.tag, d, kind: "cast", id: as.id });
    });
    [["@image8", "openFrame", c.openFrame], ["@image9", "closeFrame", c.mode === "FLF" ? c.closeFrame : null]].forEach(([fallbackTag, key, f]) => {
      if (!f) return;
      const d = f.mediaId || imgSrc(f.thumbId, f.source);
      if (d) items.push({ tag: f.tag || fallbackTag, d, kind: "frame", id: key });
    });
    (c.refs || []).filter((r) => r.kind === "image").forEach((r) => {
      const d = r.mediaId || imgSrc(r.thumbId, r.source);
      if (d) items.push({ tag: r.tag, d, kind: "ref", id: r.id });
    });
    const kindRank = (it) => it.kind === "frame" ? 0 : 1;
    const sortNum = (it) => it.kind === "frame" ? 0 : tagNum(it.tag);
    items.sort((a, b) => kindRank(a) - kindRank(b) || sortNum(a) - sortNum(b));
    return items.slice(0, 6);
  };
  var noImgSrc = () => null;
  var positionTag = (entry, project, imgSrc, id) => {
    const items = shotImageRefs(entry, project, imgSrc);
    const idx = items.findIndex((it) => it.id === id);
    return idx < 0 ? null : "@image" + (idx + 1);
  };
  var pickTarget = (entry, project, imgSrc, slot) => {
    const items = shotImageRefs(entry, project, imgSrc);
    const existing = items[slot];
    if (existing) return { type: "replace", kind: existing.kind, id: existing.id };
    return { type: "append", tag: nextTag(items, "@image") };
  };
  var shotVideoRefs = (entry) => (entry.c.refs || []).filter((r) => r.kind === "video" && /^\d+$/.test(r.source || ""));
  var pickVideoTarget = (entry, slot) => {
    const items = shotVideoRefs(entry);
    const existing = items[slot];
    if (existing) return { type: "replace", id: existing.id };
    const allVideoRefs = (entry.c.refs || []).filter((r) => r.kind === "video");
    return { type: "append", tag: nextTag(allVideoRefs, "@video") };
  };
  var shotText = (entry, p, imgSrc) => {
    const { c, code, ai } = entry;
    if (c.promptOverride) return effectivePrompt(c);
    const resolve = imgSrc || noImgSrc;
    const idx = flat(p).findIndex((x) => x.c.id === c.id);
    const prev = idx > 0 ? flat(p)[idx - 1] : null;
    const L = [`[${code} \u2014 "${c.title || "untitled"}"]  (${c.mode}, ~${c.duration}s, ${connectMeta(c.connect).label})`, ""];
    if (c.connect === "extend" && prev) L.push(`Continue seamlessly from the previous clip ${prev.code} (upload it as @video1).`);
    if (c.connect === "flf") {
      const openTag = positionTag(entry, p, resolve, "openFrame") || c.openFrame.tag;
      const closeTag = positionTag(entry, p, resolve, "closeFrame") || c.closeFrame.tag;
      if (c.openFrame.desc || openTag) L.push(`Opening frame ${openTag || "(first image)"}: ${c.openFrame.desc || "\u2014"}`);
      if (c.closeFrame.desc || closeTag) L.push(`Closing frame ${closeTag || "(last image)"}: ${c.closeFrame.desc || "\u2014"}`);
    }
    L.push("", c.prompt || "(prompt tbd)");
    if (c.connect === "extend" || c.connect === "flf") L.push(CONTINUITY_PHRASE);
    if (p.look) L.push("", `Look (consistent across the film): ${p.look}`);
    const usedCast = (p.assets || []).filter((as) => c.cast.includes(as.id));
    if (usedCast.length) {
      L.push("", "Keep consistent:");
      usedCast.forEach((as) => {
        const tag = positionTag(entry, p, resolve, as.id) || as.tag;
        L.push(`  ${as.name} \u2014 ${as.lock ? "maintain exact appearance from " : "reference "}${tag}`);
      });
    }
    if (c.refs.length) {
      L.push("", "Other references:");
      c.refs.forEach((r) => {
        const tag = positionTag(entry, p, resolve, r.id) || r.tag;
        L.push(`  ${tag} \u2014 ${r.role || "(role tbd)"}${r.source ? `  [${r.source}]` : ""}`);
      });
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
    const imgs = shotImageRefs(entry, project, imgSrc);
    const vids = (c.refs || []).filter((r) => r.kind === "video" && /^\d+$/.test(r.source || "")).map((r) => r.source).slice(0, 3);
    return {
      mode: c.mode,
      prompt: shotText(entry, project, imgSrc),
      images: imgs.map((x) => x.d),
      video_refs: vids,
      duration: c.duration,
      quality: project.draft ? "basic" : "professional",
      generate_audio: !!c.audioGen,
      audio_language: c.audioLanguage || "english",
      hasInput: imgs.length + vids.length > 0
    };
  };
  var PRICE_FIELDS = ["mode", "images", "video_refs", "duration", "quality", "generate_audio", "audio_language"];
  var priceFingerprint = (payload) => JSON.stringify(PRICE_FIELDS.map((k) => payload[k]));
  var tallyPrices = (prices) => {
    let free = 0, paid = 0, credits = 0, unknown = 0;
    prices.forEach((pr) => {
      if (pr && pr.free) free++;
      else if (pr && pr.cost != null) {
        paid++;
        credits += pr.cost;
      } else unknown++;
    });
    return { free, paid, credits, unknown };
  };
  var formatCostEstimate = ({ free = 0, paid = 0, credits = 0, unknown = 0, pending = 0 } = {}) => {
    const settledNone = free === 0 && paid === 0 && unknown === 0;
    const trail = pending > 0 ? " \u27F3" : "";
    if (settledNone && pending > 0) return "\u2026";
    if (credits > 0) return `\u2248${credits.toLocaleString()} cr${unknown ? ` (+${unknown} unk)` : ""}${trail}`;
    if (unknown > 0) return `${unknown} unpriced${trail}`;
    if (free > 0) return `\u{1F3AB} free${trail}`;
    if (paid > 0) return `0 cr${trail}`;
    return "\u2026" + trail;
  };
  var costTooltip = ({ free = 0, paid = 0, credits = 0, unknown = 0, pending = 0 } = {}) => `Cost to finish: ${free} free-card, ${paid} paid (\u2248${credits.toLocaleString()} credits), ${unknown} unpriced${pending ? `, ${pending} still estimating` : ""}.`;
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
  var setPromptOverride = (c, text) => ({ ...c, promptOverride: true, promptOverrideText: text });
  var clearPromptOverride = (c) => ({ ...c, promptOverride: false, promptOverrideText: "" });
  var importedFootagePatch = (mediaId, duration) => {
    const dur = Number(duration);
    return {
      status: "done",
      resultMid: mediaId,
      trimIn: 0,
      trimOut: null,
      imported: true,
      ...dur > 0 ? { actualDur: dur } : {}
    };
  };
  var patchAct = (project, actId, patch) => ({
    ...project,
    acts: project.acts.map((a) => a.id !== actId ? a : { ...a, ...patch })
  });
  var patchAssets = (project, fn) => ({ ...project, assets: fn(project.assets || []) });
  var appendCardToAct = (project, actId, card) => ({
    ...project,
    acts: project.acts.map((a) => a.id !== actId ? a : { ...a, cards: [...a.cards, card] })
  });
  var landInFirstAct = (project, card, newActId) => {
    const first = project.acts[0];
    const withAct = first ? project : appendAct(project, { id: newActId, name: nextActName(project), collapsed: false, cards: [] });
    return appendCardToAct(withAct, first ? first.id : newActId, card);
  };
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
  var splitCardAt = (project, actId, cardId, t, newCardId) => {
    const act = project.acts.find((a) => a.id === actId);
    const card = act && act.cards.find((c) => c.id === cardId);
    if (!card) return project;
    const ti = card.trimIn || 0, to = card.trimOut;
    if (!(t > ti + 0.1 && (to == null || t < to - 0.1))) return project;
    const right = {
      ...JSON.parse(JSON.stringify(card)),
      id: newCardId,
      title: card.title ? card.title + " (cont.)" : "cont.",
      trimIn: t,
      trimOut: to
    };
    const withLeft = patchCard(project, actId, cardId, (c) => ({ ...c, trimOut: t }));
    return insertCardAfter(withLeft, actId, cardId, right);
  };
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
  var setShotMode = (c, mode) => ({
    ...c,
    mode,
    connect: mode !== "FLF" && c.connect === "flf" ? "new" : c.connect
  });
  var setShotConnect = (c, connect) => ({
    ...c,
    connect,
    mode: connect === "flf" ? "FLF" : c.mode
  });
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
      const clip = { mid: e.c.resultMid, in: cin, out: e.c.trimOut, span: Math.max(0.1, cout - cin) };
      const cr = e.c.crop;
      if (cr && cr.w > 0.05 && cr.h > 0.05 && (cr.w < 0.99 || cr.h < 0.99 || cr.x > 0.01 || cr.y > 0.01))
        clip.crop = { x: cr.x, y: cr.y, w: cr.w, h: cr.h };
      return clip;
    });
    const total = clips.reduce((s, c) => s + c.span, 0);
    return { clips, total };
  }
  function loraIncompat(baseModelType, loraBaseType) {
    const b = (baseModelType || "").toUpperCase();
    const l = (loraBaseType || "").toUpperCase();
    if (!b || !l) return false;
    return b !== l;
  }
  function resolveLoraPayload(loras) {
    return (loras || []).filter((l) => l.version_id).map((l) => ({ version_id: l.version_id, weight: l.weight }));
  }
  function anyLoraUnresolved(loras) {
    return (loras || []).some((l) => !l.version_id);
  }
  function snap8(n) {
    return Math.max(64, Math.min(4096, Math.round((Number(n) || 0) / 8) * 8));
  }
  function resolveGenDims2({ aspectW, aspectH, size, customW, customH } = {}) {
    const cw = Number(customW) || 0, ch = Number(customH) || 0;
    if (cw > 0 && ch > 0) return { w: snap8(cw), h: snap8(ch), custom: true };
    const rw = Number(aspectW) || 1, rh = Number(aspectH) || 1;
    const sz = Number(size) || 1024;
    const w = rw >= rh ? sz : sz * rw / rh;
    const h = rw >= rh ? sz * rh / rw : sz;
    return { w: snap8(w), h: snap8(h), custom: false };
  }
  function buildImgGenBody(imgModel, imgLoras, imgAdv, prompt) {
    const a = imgAdv || {};
    const dims = resolveGenDims2({
      aspectW: a.aspectW,
      aspectH: a.aspectH,
      size: a.size,
      customW: a.customW,
      customH: a.customH
    });
    return {
      model_id: imgModel && imgModel.model_id || "",
      prompt: prompt || "",
      loras: resolveLoraPayload(imgLoras),
      negative: a.negative || "",
      width: dims.w,
      height: dims.h,
      mode: a.mode || "auto",
      steps: Number(a.steps) || 25,
      cfg: Number(a.cfg) || 7,
      count: Number(a.count) || 1,
      seed: String(a.seed || "").trim(),
      high_priority: !!a.highPriority,
      prompt_helper: !!a.promptHelper
    };
  }

  // master-storyboard.jsx
  var { useState, useEffect, useRef, useCallback, useMemo } = React;
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
/* Export \u25BE menu reuses .sb-projwrap/.sb-projbtn/.sb-projveil/.sb-projpop's chrome as-is --
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
  var MODES = ["I2V", "R2V", "V2V", "FLF"];
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
  var elapsedLabel = (ms) => ms < 36e5 ? Math.round(ms / 6e4) + "m" : Math.round(ms / 36e4) / 10 + "h";
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
      // audioGen/audioLanguage are the actual generation request (does PixAI render sound at
      // all, and in what language) -- distinct from audioCue above, which is prompt TEXT
      // ("ambient room tone") that only ever influences wording, never the real generateAudio/
      // audioLanguage params. Neither surface exposed this until now (private/GENERATOR_SURFACE.md
      // had it reverse-engineered but never wired to a control): the server already accepts
      // generate_audio/audio_language on /api/loom/generate, this was purely a missing control.
      audioGen: false,
      audioLanguage: "english",
      transIn: "",
      transOut: "",
      notes: "",
      discreet: false,
      trimIn: 0,
      trimOut: null,
      // promptOverride/promptOverrideText: a hand-edit made directly in the drawer's composed-
      // prompt box, durable across shot reselect/reload. When set, shotText() returns
      // promptOverrideText verbatim instead of composing from camera/lighting/cast/etc --
      // see loom-core.js's shotText() and effectivePrompt().
      promptOverride: false,
      promptOverrideText: "",
      ...extra
    };
  }
  function seedProject() {
    return {
      name: "Untitled storyboard",
      target: 480,
      look: "",
      draft: false,
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
/* While Deep Focus is open, lift the WHOLE overlay's root-context z-index to .lv-df-veil's
   own intended 450 (see the "AUDIT_2026-07-21.md" comment above the .lv-overlay mount) so
   the body-level corner FABs -- #jobs-fab/#jobs-tray at 401/402 -- stop painting over Deep
   Focus and its nested flyouts, which are otherwise contained inside .lv-overlay's own
   stacking context and can never out-rank a root-level sibling on their own. */
.lv-overlay.lv-overlay-df{z-index:450;}
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
/* Continuity indicator (frameLinked/continuityLinked) -- reuses the .lv-st badge's own
   font/padding/border-radius, just a distinct color (--cyan, not --green) so it never reads
   as "shot generation status" and margin-left:0 so it sits with mode/duration on the left
   instead of racing .lv-st's own margin-left:auto for the row's one right-aligned slot. */
.lv-st.linked{margin-left:0;color:var(--cyan);background:color-mix(in srgb,var(--cyan) 16%,transparent);}
/* Imported-footage provenance badge -- coexists with the real status pill the same way
   .linked does (margin-left:0, not competing for the row's one auto-margined slot).
   Neutral/informational, not a warning -- reuses .todo's own subtext-on-base treatment
   rather than inventing a new color. */
.lv-st.imported{margin-left:0;color:var(--subtext);background:var(--base);}
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
.lv-minichip{font-size:9px;color:var(--subtext);background:var(--base);border:1px solid var(--surface1);border-radius:5px;padding:2px 5px;cursor:pointer;}
.lv-minichip:hover{border-color:var(--accent);color:var(--accent);}
.lv-refline{font-size:10px;color:var(--subtext);margin:10px 0 4px;}
/* Draft-mode "route into a shot" picker -- shown only with no shot selected. */
.lv-drafttarget{margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid var(--surface1);}
.lv-drafttarget select.lv-sel{display:block;width:100%;flex:none;padding:7px 8px;font-size:11px;}
.lv-mini2{font-size:9px;color:var(--subtext);background:var(--base);border:1px solid var(--surface1);border-radius:5px;padding:3px 7px;cursor:pointer;margin:5px 0;}
.lv-mini2:hover{border-color:var(--accent);color:var(--accent);}
/* L536: Image tab field-parity additions -- a 2-up row (Size/Custom W\xD7H, Mode/Count) and a
   labeled checkbox row, mirroring pixai_gallery.py's .gen-row/.gen-check at the same sizing. */
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
.lv-df-frames{display:flex;gap:12px;align-items:flex-start;margin-top:14px;}
.lv-df-frames .sb-frame{flex:1 1 0;min-width:0;}
.lv-gerr{font-size:10px;color:var(--coral);margin-top:6px;}
/* D-11: LoRA chips in the Image tab -- mirrors the Gallery's own .lora-chip shape
   (pixai_gallery.py) at the Loom's smaller scale/token set, not a copy-paste of it. */
/* The show/hide toggle reuses .lv-chip (the same toggle-chip chrome as the Video tab's
   Continuity/Mode controls) -- this rule only adds the standalone spacing .lv-chips'
   flex-gap would otherwise supply. Do not re-add background/border/color/font here. */
.lv-loratoggle{display:inline-block;margin:7px 0 5px;}
.lv-loras{display:flex;flex-direction:column;gap:5px;margin-bottom:6px;}
.lv-lchip{display:flex;align-items:center;gap:7px;padding:5px 7px;border-radius:6px;background:var(--surface0);border:1px solid var(--surface1);font-size:10.5px;color:var(--text);}
.lv-lchip.failed{border-color:var(--coral);}
.lv-lchip .lv-lnm{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lv-lchip.failed .lv-lnm{color:var(--coral);}
.lv-lchip input{width:52px;background:var(--base);border:1px solid var(--surface1);border-radius:4px;color:var(--text);font-size:10px;padding:2px 4px;}
.lv-lchip .lv-lrm{background:none;border:none;color:var(--subtext);cursor:pointer;font-size:13px;padding:0 2px;line-height:1;}
.lv-lchip .lv-lrm:hover{color:var(--coral);}
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
      if (this.state.err) return /* @__PURE__ */ React.createElement("div", { className: "lv-overlay" }, /* @__PURE__ */ React.createElement("div", { className: "lv-err" }, /* @__PURE__ */ React.createElement("p", null, "The Loom hit a render error. Your storyboards are saved and safe \u2014 reload to recover."), /* @__PURE__ */ React.createElement("pre", null, String(this.state.err && this.state.err.stack || this.state.err)), /* @__PURE__ */ React.createElement("button", { className: "lv-close", onClick: () => window.location.reload() }, "\u21BB Reload the Loom"), /* @__PURE__ */ React.createElement("a", { className: "lv-close", href: "/", style: { textDecoration: "none" } }, "\u2190 Back to the gallery")));
      return this.props.children;
    }
  };
  function ProjectSwitcher({ api }) {
    const { activeId, projList, projMenu, setProjMenu, readProjList, openProject, newProject, duplicateProject, deleteProject } = api;
    useEffect(() => {
      if (!projMenu) return;
      const onKey = (ev) => {
        if (ev.key === "Escape") setProjMenu(false);
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [projMenu, setProjMenu]);
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
  function ExportMenu({ exportAll, exportJSON, exportBundle, importBackup, bundling }) {
    const [open, setOpen] = useState(false);
    useEffect(() => {
      if (!open) return;
      const onKey = (ev) => {
        if (ev.key === "Escape") setOpen(false);
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [open]);
    return /* @__PURE__ */ React.createElement("div", { className: "sb-projwrap" }, /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-projbtn",
        onClick: () => setOpen((v) => !v),
        title: "Export or restore this project",
        "aria-label": "Export"
      },
      "Export \u25BE"
    ), open && /* @__PURE__ */ React.createElement("div", { className: "sb-projveil", onClick: () => setOpen(false) }), open && /* @__PURE__ */ React.createElement("div", { className: "sb-projpop" }, /* @__PURE__ */ React.createElement("div", { className: "sb-projpoph" }, "Export"), /* @__PURE__ */ React.createElement("button", { className: "sb-exportitem", onClick: () => {
      exportAll();
      setOpen(false);
    } }, "Shot list ", /* @__PURE__ */ React.createElement("small", null, ".txt")), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-exportitem",
        onClick: () => {
          exportJSON();
          setOpen(false);
        },
        title: "Project + any locally-added assets, referencing your own catalog by media id -- the quiet default for your own home \u21C4 work use"
      },
      "Lightweight backup ",
      /* @__PURE__ */ React.createElement("small", null, ".json")
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-exportitem",
        disabled: bundling,
        onClick: () => {
          exportBundle();
          setOpen(false);
        },
        title: "Everything in the lightweight backup, plus the actual media files -- for sharing with someone who doesn't share your catalog"
      },
      bundling ? "Building bundle\u2026" : /* @__PURE__ */ React.createElement(React.Fragment, null, "Full bundle ", /* @__PURE__ */ React.createElement("small", null, ".zip"))
    ), /* @__PURE__ */ React.createElement("div", { className: "sb-exportdiv" }), /* @__PURE__ */ React.createElement(
      "label",
      {
        className: "sb-exportitem",
        style: { cursor: "pointer" },
        title: "Restore either a lightweight backup or a full bundle -- always opens as a new storyboard"
      },
      "\u21E9 Restore from file",
      /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "file",
          accept: ".json,.zip,application/json,application/zip",
          style: { display: "none" },
          onChange: (e) => {
            importBackup(e.target.files[0]);
            setOpen(false);
          }
        }
      )
    )));
  }
  function LoomV2({ project, setCard, setAssets, entries, durOf: durOf2, scale, selShot, setSelShot, useExistingVideo, genState, thumbs, openPick, storeThumb, setAct, addCard, importFootage, dupCard, delCard, moveCard, moveCardToAct: moveCardToAct2, addAct, delAct, moveAct, genImgState, imgModel, setImgModel, imgLoras, setImgLoras, imgAdv, setImgAdv, modelDefaults, setModelDefaults, genImage, routeImg, genEditState, setGenEditState, genRefState, setGenRefState, genEdit, genRef, routeGen, projectApi, playSequence, exportCut, batching, batchGenerate, addRef, setRef, delRef, exportAll, exportJSON, exportBundle, bundling, importBackup, setImportOpen, copyShot, setLook, setDraft, splitShot, onVideoSubmit, onVideoResult, onVideoError, onVideoSlow, onVideoPaused, pollShot, costEstimate, refreshEstimate, batchTally }) {
    const [tab, setTab] = useState("Video");
    const [acct, setAcct] = useState(null);
    const [handoff, setHandoff] = useState("");
    const [deepFocus, setDeepFocus] = useState(null);
    const [dfPalFor, setDfPalFor] = useState(null);
    const [loraOpen, setLoraOpen] = useState(false);
    const [leftTab, setLeftTab] = useState("cast");
    const [leftCollapsed, setLeftCollapsed] = useState(false);
    const [density, setDensity] = useState("detailed");
    const [rightCollapsed, setRightCollapsed] = useState(false);
    const [tlState, setTlState] = useState("slim");
    const [tlDragH, setTlDragH] = useState(null);
    const [palFor, setPalFor] = useState(null);
    const [dzHover, setDzHover] = useState(false);
    const [overrideClearedFlash, setOverrideClearedFlash] = useState(false);
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
      audioGen: false,
      audioLanguage: "english",
      imgPrompt: "",
      editPrompt: "",
      refPrompt: "",
      cast: [],
      refs: [],
      openFrame: {},
      closeFrame: {},
      promptOverride: false,
      promptOverrideText: ""
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
    const imgModelSeqRef = useRef(0);
    const bindPicker = useCallback((el) => {
      if (el && !el._mgBound) {
        el._mgBound = true;
        el.addEventListener("mg-pick", (e) => {
          const m = { model_id: e.detail.model_id, title: e.detail.title };
          setImgModel(m);
          setModelDefaults(null);
          const mySeq = ++imgModelSeqRef.current;
          fetch("/api/model-version?model_id=" + encodeURIComponent(m.model_id)).then((r) => r.json()).then((d) => {
            if (mySeq !== imgModelSeqRef.current) return;
            setImgModel((cur) => cur && cur.model_id === m.model_id ? { ...cur, model_type: d.model_type || "" } : cur);
            const has = d.negative_prompt || d.sampling_steps || d.cfg_scale;
            setModelDefaults(has ? { negative_prompt: d.negative_prompt || "", sampling_steps: d.sampling_steps || null, cfg_scale: d.cfg_scale || null } : null);
            if (has) {
              setImgAdv((cur) => ({
                ...cur,
                negative: d.negative_prompt || cur.negative,
                steps: d.sampling_steps || cur.steps,
                cfg: d.cfg_scale || cur.cfg
              }));
            }
          }).catch(() => {
          });
        });
      }
    }, [setImgModel, setImgAdv, setModelDefaults]);
    const bindLoraPicker = useCallback((el) => {
      if (el && !el._mgBound) {
        el._mgBound = true;
        el.addEventListener("mg-pick", (e) => {
          const { model, selected } = e.detail;
          setImgLoras((cur) => {
            const i = cur.findIndex((l) => l.model_id === model.model_id);
            if (!selected) return i < 0 ? cur : cur.filter((l) => l.model_id !== model.model_id);
            if (i < 0) return [...cur, model];
            const next = cur.slice();
            next[i] = model;
            return next;
          });
        });
      }
    }, [setImgLoras]);
    const imgCostRef = useRef(null);
    const editCostRef = useRef(null);
    const refCostRef = useRef(null);
    const priceInto = (ref, body) => {
      const badge = ref.current;
      if (!badge) return;
      badge.setChecking();
      fetch("/api/price", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json()).then((d) => {
        if (ref.current === badge) badge.setPrice(d);
      }).catch(() => {
        if (ref.current === badge) badge.setPrice(null);
      });
    };
    const activeRef = useRef(null);
    const projectRef = useRef(project);
    projectRef.current = project;
    const thumbsRef = useRef(thumbs);
    thumbsRef.current = thumbs;
    const genDrawerRef = useRef(null);
    const promptDirtyRef = useRef(false);
    const genTargetRef = useRef(null);
    const lastActiveIdRef = useRef(null);
    const bindGenDrawer = useCallback((el) => {
      genDrawerRef.current = el;
      if (el && !el._mgBound) {
        el._mgBound = true;
        el.addEventListener("mg-dirty", () => {
          promptDirtyRef.current = true;
        });
        el.addEventListener("mg-mode-commit", (e) => {
          const a = activeRef.current;
          if (!a) return;
          const vmode = e.detail.vmode;
          const apply = (c) => drawerModeFor(c.mode) === vmode ? c : setShotMode(c, cardModeForVmode(vmode));
          a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
        });
        el.addEventListener("mg-duration-commit", (e) => {
          const a = activeRef.current;
          if (!a) return;
          const d = e.detail.duration;
          const apply = (c) => ({ ...c, duration: d });
          a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
        });
        el.addEventListener("mg-audio-commit", (e) => {
          const a = activeRef.current;
          if (!a) return;
          const { audioGen, audioLanguage } = e.detail;
          const apply = (c) => ({ ...c, audioGen, audioLanguage });
          a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
        });
        el.addEventListener("mg-pick-request", (e) => {
          const { slot, bank, mode: reqMode } = e.detail;
          if (bank === "primary" && reqMode === "r2v") {
            openPick((mid, thumb, isVideo, duration, isNsfw) => {
              e.detail.respond(mid, thumb, isNsfw);
              const a = activeRef.current;
              if (!a) return;
              const proj = projectRef.current;
              const resolve = (thumbId, source) => thumbId ? thumbsRef.current[thumbId] : source && (source.startsWith("http") || source.startsWith("data:") || /^\d+$/.test(source)) ? source : null;
              const plan = pickTarget(a, proj, resolve, slot);
              if (plan.type === "replace" && plan.kind === "cast") {
                setAssets((arr) => arr.map((x) => x.id !== plan.id ? x : { ...x, mediaId: String(mid), thumbId: "", source: "" }));
              } else if (plan.type === "replace" && plan.kind === "ref") {
                const apply = (c) => ({ ...c, refs: c.refs.map((r) => r.id !== plan.id ? r : { ...r, mediaId: String(mid), thumbId: "", source: "" }) });
                a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
              } else if (plan.type === "replace" && plan.kind === "frame") {
                const apply = (c) => ({ ...c, [plan.id]: { ...c[plan.id], mediaId: String(mid), thumbId: "", source: "" } });
                a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
              } else {
                const newRef = { ...buildNewRef("image", uid()), tag: plan.tag, mediaId: String(mid) };
                const apply = (c) => ({ ...c, refs: [...c.refs, newRef] });
                a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
              }
            }, "image");
          } else if (bank === "primary" && (reqMode === "i2v" || reqMode === "flf")) {
            openPick((mid, thumb, isVideo, duration, isNsfw) => {
              e.detail.respond(mid, thumb, isNsfw);
              const a = activeRef.current;
              if (!a) return;
              const key = slot === 1 ? "closeFrame" : "openFrame";
              const apply = (c) => ({ ...c, [key]: { ...c[key], mediaId: String(mid), thumbId: "", source: "" } });
              a.c.id === "__draft__" ? setDraftCard(apply) : setCard(a.a.id, a.c.id, apply);
            }, "image");
          } else if (bank === "vid") {
            openPick((mid, thumb, isVideo, duration, isNsfw) => {
              e.detail.respond(mid, thumb, isNsfw);
              const a = activeRef.current;
              if (!a) return;
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
        el.addEventListener("mg-prompt-commit", (e) => {
          const a = activeRef.current;
          if (!a) return;
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
    const TL_HEIGHTS = { hidden: 0, slim: 64, full: 442 };
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
    activeRef.current = active;
    const editSrcMid = active.c.openFrame && active.c.openFrame.mediaId;
    const refMids = (project.assets || []).filter((a) => a.kind === "image" && a.mediaId).map((a) => a.mediaId);
    const refMidsKey = refMids.join(",");
    useEffect(() => {
      const badge = imgCostRef.current;
      if (!badge) return;
      const prompt = (active.c.imgPrompt || "").trim();
      if (!imgModel || !prompt || anyLoraUnresolved(imgLoras)) {
        badge.clear();
        return;
      }
      const t = setTimeout(() => priceInto(imgCostRef, buildImgGenBody(imgModel, imgLoras, imgAdv, prompt)), 250);
      return () => clearTimeout(t);
    }, [imgModel, imgLoras, imgAdv, active.c.id, active.c.imgPrompt]);
    useEffect(() => {
      const badge = editCostRef.current;
      if (!badge) return;
      const instruction = (active.c.editPrompt || "").trim();
      if (!editSrcMid || !instruction) {
        badge.clear();
        return;
      }
      const t = setTimeout(() => priceInto(editCostRef, { mode: "edit", source: editSrcMid, instruction, edit_model: "edit-pro" }), 250);
      return () => clearTimeout(t);
    }, [editSrcMid, active.c.id, active.c.editPrompt]);
    useEffect(() => {
      const badge = refCostRef.current;
      if (!badge) return;
      const prompt = (active.c.refPrompt || "").trim();
      if (!refMids.length || !prompt) {
        badge.clear();
        return;
      }
      const t = setTimeout(() => priceInto(refCostRef, { mode: "edit", source: refMids[0], sources: refMids, instruction: prompt, edit_model: "reference-pro" }), 250);
      return () => clearTimeout(t);
    }, [refMidsKey, active.c.id, active.c.refPrompt]);
    const drawerModeFor = (m) => {
      const u = (m || "R2V").toUpperCase();
      return u === "FLF" ? "flf" : u === "I2V" ? "i2v" : "r2v";
    };
    const cardModeForVmode = (v) => v === "flf" ? "FLF" : v === "i2v" ? "I2V" : "R2V";
    const weaveSelIdx = sel ? entries.findIndex((e) => e.c.id === sel.c.id) : -1;
    const weavePrevEntry = weaveSelIdx > 0 ? entries[weaveSelIdx - 1] : null;
    const imgSrc = (thumbId, source) => thumbId ? thumbs[thumbId] : source && (source.startsWith("http") || source.startsWith("data:") || /^\d+$/.test(source)) ? source : null;
    const asRef = (d) => ({ media_id: d, thumb: /^\d+$/.test(d) ? "/thumbs/" + d + ".jpg" : d });
    useEffect(() => {
      const el = genDrawerRef.current;
      if (!el || tab !== "Video") return;
      if (lastActiveIdRef.current !== active.c.id) {
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
      const payload = {
        mode: nextMode,
        duration: active.c.duration,
        audio: !!active.c.audioGen,
        audio_language: active.c.audioLanguage || "english",
        quality: project.draft ? "basic" : "professional",
        images: [],
        video_refs: [],
        audio_ref: null
      };
      if (nextMode === "i2v" && active.c.openFrame && active.c.openFrame.mediaId) {
        payload.images = [{ media_id: active.c.openFrame.mediaId, thumb: frameSrc(active.c.openFrame) }];
      } else if (nextMode === "flf") {
        payload.images = [active.c.openFrame, active.c.closeFrame].filter((f) => f && f.mediaId).map((f) => ({ media_id: f.mediaId, thumb: frameSrc(f) }));
      } else if (nextMode === "r2v") {
        const sp = shotPayload(active, project, imgSrc);
        payload.images = sp.images.map(asRef);
        const vids = (sp.video_refs || []).map(asRef);
        if (active.c.connect === "extend" && weavePrevEntry && weavePrevEntry.c.resultMid) {
          vids.push({ media_id: weavePrevEntry.c.resultMid, thumb: "/thumbs/" + weavePrevEntry.c.resultMid + ".jpg" });
        }
        payload.video_refs = vids;
      }
      if (!promptDirtyRef.current) payload.prompt = shotText(active, project);
      el.prefill(payload);
    }, [
      active.c.id,
      active.c.mode,
      active.c.connect,
      active.c.duration,
      active.c.audioGen,
      active.c.audioLanguage,
      active.c.prompt,
      active.c.camera,
      active.c.lighting,
      active.c.transIn,
      active.c.transOut,
      active.c.cast,
      active.c.refs,
      project.assets,
      active.c.title,
      project.look,
      project.draft,
      tab,
      active.c.promptOverride,
      active.c.promptOverrideText
    ]);
    useEffect(() => {
      const gs = genState[active.c.id];
      const stillBusy = active.c.status === "wip" && !(gs && gs.phase === "paused");
      const el = genDrawerRef.current;
      if (el && el.setBusy) el.setBusy(stillBusy);
    }, [active.c.id, active.c.status, genState[active.c.id] && genState[active.c.id].phase]);
    const board = /* @__PURE__ */ React.createElement("div", { className: "lv-board" }, project.acts.map((act, ai) => {
      const items = entries.filter((e) => e.ai === ai);
      return /* @__PURE__ */ React.createElement("div", { key: act.id, className: "lv-act" }, /* @__PURE__ */ React.createElement("div", { className: "lv-actrow" }, /* @__PURE__ */ React.createElement("input", { className: "lv-actname-in", value: act.name, onChange: (ev) => setAct(act.id, { name: ev.target.value }), "aria-label": "Act name" }), /* @__PURE__ */ React.createElement("button", { className: "lv-ico", onClick: () => moveAct(ai, -1), title: "Move act up" }, "\u2191"), /* @__PURE__ */ React.createElement("button", { className: "lv-ico", onClick: () => moveAct(ai, 1), title: "Move act down" }, "\u2193"), /* @__PURE__ */ React.createElement("button", { className: "lv-ico danger", onClick: () => delAct(act.id), title: "Delete act" }, "\u2715")), /* @__PURE__ */ React.createElement("div", { className: "lv-cards" }, items.map((e) => {
        const gs = genState[e.c.id];
        const paused = gs && gs.phase === "paused";
        const st = paused ? "paused" : gs && gs.phase && gs.phase !== "done" && gs.phase !== "error" ? "wip" : e.c.status;
        const linked = continuityLinked(entries, e.c.id);
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
          /* @__PURE__ */ React.createElement("div", { className: "lv-cmeta" }, /* @__PURE__ */ React.createElement("span", { className: "lv-mode" }, e.c.mode), /* @__PURE__ */ React.createElement("span", { className: "lv-dur" }, durOf2(e.c), "s"), linked && /* @__PURE__ */ React.createElement("span", { className: "lv-st linked", title: "Opening frame matches the previous shot's closing frame \u2014 continuous across the cut" }, "linked"), e.c.imported && /* @__PURE__ */ React.createElement("span", { className: "lv-st imported", title: "Imported from your gallery -- no PixAI task backs this clip, so re-roll has nothing to redo" }, "imported"), /* @__PURE__ */ React.createElement(
            "span",
            {
              className: "lv-st " + st,
              onClick: paused ? (ev) => {
                ev.stopPropagation();
                pollShot(e.c.id, e.c.pendingTaskId);
              } : void 0,
              style: paused ? { cursor: "pointer" } : void 0,
              title: paused ? "Click to check again" : void 0
            },
            gs && gs.msg ? gs.msg : st
          )),
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
        key: sel.c.id,
        mid: sel.c.resultMid,
        trimIn: sel.c.trimIn,
        trimOut: sel.c.trimOut,
        onTrim: (i, o) => setCard(sel.a.id, sel.c.id, (c) => ({ ...c, trimIn: i, trimOut: o })),
        onSplit: (t) => splitShot(sel, t),
        crop: sel.c.crop,
        onCrop: (rect) => setCard(sel.a.id, sel.c.id, (c) => ({ ...c, crop: rect }))
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
      const busy = gs && gs.phase && gs.phase !== "done" && gs.phase !== "error" && gs.phase !== "paused";
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
            body: JSON.stringify({ video_media_id: rmid, trim_out: prevEntry.c.trimOut })
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
      let videoTrailer = null;
      if (tab === "Video") {
        tabBody = /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Continuity"), /* @__PURE__ */ React.createElement("div", { className: "lv-chips" }, Object.keys(CONNECT).map((k) => /* @__PURE__ */ React.createElement(
          "span",
          {
            key: k,
            className: "lv-chip " + (k === (active.c.connect || "new") ? "on" : ""),
            title: CONNECT[k].hint,
            onClick: () => patch((c) => setShotConnect(c, k))
          },
          CONNECT[k].label
        ))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Prompt"), /* @__PURE__ */ React.createElement("textarea", { className: "lv-ta", value: active.c.prompt || "", onChange: (ev) => {
          if (active.c.promptOverride) {
            setOverrideClearedFlash(true);
            setTimeout(() => setOverrideClearedFlash(false), 1600);
          }
          patch((c) => ({ ...clearPromptOverride(c), prompt: ev.target.value }));
        } }), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Camera ", /* @__PURE__ */ React.createElement("button", { className: "lv-termsbtn", onClick: () => togglePal("camera") }, "+ terms")), /* @__PURE__ */ React.createElement("input", { className: "lv-in", value: active.c.camera || "", placeholder: "e.g. slow push in, shallow DoF", onChange: (ev) => patch((c) => ({ ...c, camera: ev.target.value })) }), palFor === "camera" && /* @__PURE__ */ React.createElement("div", { className: "lv-termspal" }, Object.entries(CAM_PALETTE).map(([grp, items]) => /* @__PURE__ */ React.createElement("div", { key: grp, className: "lv-termsgrp" }, /* @__PURE__ */ React.createElement("div", { className: "lv-termsgrpt" }, grp), items.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-minichip", onClick: () => appendTo("camera", t) }, t))))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Lighting ", /* @__PURE__ */ React.createElement("button", { className: "lv-termsbtn", onClick: () => togglePal("lighting") }, "+ terms")), /* @__PURE__ */ React.createElement("input", { className: "lv-in", value: active.c.lighting || "", placeholder: "e.g. moonlit, soft haze", onChange: (ev) => patch((c) => ({ ...c, lighting: ev.target.value })) }), palFor === "lighting" && /* @__PURE__ */ React.createElement("div", { className: "lv-termspal" }, LIGHTING_PALETTE.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-minichip", onClick: () => appendTo("lighting", t) }, t))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Transition in ", /* @__PURE__ */ React.createElement("button", { className: "lv-termsbtn", onClick: () => togglePal("transIn") }, "+ terms")), /* @__PURE__ */ React.createElement("input", { className: "lv-in", value: active.c.transIn || "", placeholder: "e.g. cut, dissolve", onChange: (ev) => patch((c) => ({ ...c, transIn: ev.target.value })) }), palFor === "transIn" && /* @__PURE__ */ React.createElement("div", { className: "lv-termspal" }, TRANS_PALETTE.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-minichip", onClick: () => patch((c) => ({ ...c, transIn: t })) }, t))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Transition out ", /* @__PURE__ */ React.createElement("button", { className: "lv-termsbtn", onClick: () => togglePal("transOut") }, "+ terms")), /* @__PURE__ */ React.createElement("input", { className: "lv-in", value: active.c.transOut || "", placeholder: "e.g. cut, dissolve", onChange: (ev) => patch((c) => ({ ...c, transOut: ev.target.value })) }), palFor === "transOut" && /* @__PURE__ */ React.createElement("div", { className: "lv-termspal" }, TRANS_PALETTE.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-minichip", onClick: () => patch((c) => ({ ...c, transOut: t })) }, t))), /* @__PURE__ */ React.createElement("div", { className: "lv-refline" }, (active.c.cast || []).length, " cast \xB7 ", (active.c.refs || []).length, " refs ", /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "(toggle cast in the Cast & assets tab; add extra image/video/audio refs directly below)")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", margin: "10px 0 2px" } }, active.c.promptOverride ? /* @__PURE__ */ React.createElement("span", { className: "lv-dim lv-override-badge", title: "Hand-edited override -- Camera/Lighting/cast/notes above are NOT composed into it. Re-sync to go back to auto-compose." }, "\u270E override active \u2014 fields above not woven in") : /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "\u2193 woven into the form below"), /* @__PURE__ */ React.createElement("button", { className: "lv-mini2", onClick: () => {
          promptDirtyRef.current = false;
          const composed = shotText({ ...active, c: { ...active.c, promptOverride: false } }, project);
          active.c.id === "__draft__" ? setDraftCard(clearPromptOverride) : setCard(active.a.id, active.c.id, clearPromptOverride);
          if (genDrawerRef.current) genDrawerRef.current.prefill({ prompt: composed });
        } }, "\u21BA re-sync from shot")), overrideClearedFlash && /* @__PURE__ */ React.createElement("div", { className: "lv-overrideflash" }, "override cleared \u2014 back to auto-compose"));
        videoTrailer = /* @__PURE__ */ React.createElement(React.Fragment, null, sel && /* @__PURE__ */ React.createElement("button", { className: "lv-usevid", disabled: busy, onClick: () => useExistingVideo(sel), title: "Skip generation -- use a video you already have in your gallery as this shot's clip" }, "\u{1F4BE} Use an existing video instead"), !sel && gs && gs.mid && /* @__PURE__ */ React.createElement("div", { className: "lv-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + gs.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lv-route" }, /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "attach to shot \u2192"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn", disabled: !routeTarget, onClick: () => {
          if (!routeTarget) return;
          setCard(routeTarget.a.id, routeTarget.c.id, (x) => ({ ...x, status: "done", resultMid: gs.mid, trimIn: 0, trimOut: null, ...gs.duration ? { actualDur: gs.duration } : {} }));
          setDraftAttachedInfo({ mid: gs.mid, code: routeTarget.code });
        } }, routeTarget ? `attach to ${routeTarget.code}` : "choose a shot above")), draftAttachedInfo && draftAttachedInfo.mid === gs.mid && /* @__PURE__ */ React.createElement("div", { className: "lv-ok2" }, "\u2713 attached to ", draftAttachedInfo.code, " \xB7 it's now that shot's result")));
      } else if (tab === "Image") {
        const gi = genImgState[active.c.id] || {};
        const busyI = gi.phase === "submitting" || gi.phase === "running";
        tabBody = /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Model ", imgModel ? /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "\xB7 ", imgModel.title) : null), /* @__PURE__ */ React.createElement("mg-model-picker", { ref: bindPicker, kind: "base" }), imgLoras.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "lv-loras" }, imgLoras.map((l) => {
          const incompat = loraIncompat(imgModel && imgModel.model_type, l.lora_base_type);
          return /* @__PURE__ */ React.createElement("div", { key: l.model_id, className: "lv-lchip" + (l.failed || incompat ? " failed" : "") }, /* @__PURE__ */ React.createElement(
            "span",
            {
              className: "lv-lnm",
              title: incompat ? l.title + " \u2014 needs a different base architecture than the one selected; remove it or switch the base" : l.title
            },
            l.title,
            !l.version_id ? l.failed ? " \u26A0" : " \u23F3" : incompat ? " \u26A0" : ""
          ), /* @__PURE__ */ React.createElement(
            "input",
            {
              type: "number",
              step: "0.05",
              min: "0",
              max: "2",
              value: l.weight,
              title: "Weight",
              onChange: (ev) => {
                const w = +ev.target.value || 0;
                setImgLoras((cur) => cur.map((x) => x.model_id === l.model_id ? { ...x, weight: w } : x));
              }
            }
          ), /* @__PURE__ */ React.createElement(
            "button",
            {
              type: "button",
              className: "lv-lrm",
              title: "Remove",
              onClick: () => setImgLoras((cur) => cur.filter((x) => x.model_id !== l.model_id))
            },
            "\xD7"
          ));
        })), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lv-chip lv-loratoggle" + (loraOpen ? " on" : ""), onClick: () => setLoraOpen((v) => !v) }, loraOpen ? "\u2212 hide LoRA picker" : "+ add LoRA"), loraOpen && /* @__PURE__ */ React.createElement("mg-model-picker", { ref: bindLoraPicker, kind: "lora", multi: true }), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Image prompt"), /* @__PURE__ */ React.createElement(
          "textarea",
          {
            className: "lv-ta",
            value: active.c.imgPrompt || "",
            placeholder: "describe the reference still (subject, pose, composition, light)\u2026",
            onChange: (ev) => patch((c) => ({ ...c, imgPrompt: ev.target.value }))
          }
        ), sel && /* @__PURE__ */ React.createElement("button", { className: "lv-mini2", onClick: () => patch((c) => ({ ...c, imgPrompt: [c.title, c.prompt, c.openFrame && c.openFrame.desc || "", c.lighting || ""].filter(Boolean).join(", ") })) }, "\u21A7 seed from shot description"), /* @__PURE__ */ React.createElement("details", null, /* @__PURE__ */ React.createElement("summary", { style: { cursor: "pointer", color: "var(--subtext)", fontSize: 11 } }, "Advanced"), /* @__PURE__ */ React.createElement(
          "textarea",
          {
            className: "lv-ta",
            style: { marginTop: 5 },
            value: imgAdv.negative,
            placeholder: "lowres, text, watermark\u2026",
            onChange: (ev) => setImgAdv((a) => ({ ...a, negative: ev.target.value }))
          }
        ), /* @__PURE__ */ React.createElement("div", { className: "lv-row2" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab", style: { margin: "6px 0 3px" } }, "Steps"), /* @__PURE__ */ React.createElement(
          "input",
          {
            className: "lv-in",
            type: "number",
            min: "1",
            max: "150",
            step: "1",
            value: imgAdv.steps,
            onChange: (ev) => setImgAdv((a) => ({ ...a, steps: +ev.target.value || 25 }))
          }
        )), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab", style: { margin: "6px 0 3px" } }, "CFG scale"), /* @__PURE__ */ React.createElement(
          "input",
          {
            className: "lv-in",
            type: "number",
            min: "1",
            max: "30",
            step: "0.5",
            value: imgAdv.cfg,
            onChange: (ev) => setImgAdv((a) => ({ ...a, cfg: +ev.target.value || 7 }))
          }
        ))), modelDefaults && /* @__PURE__ */ React.createElement("div", { className: "lv-advnote" }, /* @__PURE__ */ React.createElement("span", null, "\u2713 using this model's tuned preset"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lv-mini2", style: { margin: 0 }, onClick: () => {
          setImgAdv((a) => ({
            ...a,
            negative: modelDefaults.negative_prompt || a.negative,
            steps: modelDefaults.sampling_steps || a.steps,
            cfg: modelDefaults.cfg_scale || a.cfg
          }));
        } }, "\u21B6 reset"))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Aspect"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 5, flexWrap: "wrap" } }, [
          [1, 1, "1:1"],
          [3, 4, "3:4"],
          [4, 3, "4:3"],
          [2, 3, "2:3"],
          [3, 2, "3:2"],
          [9, 16, "9:16"],
          [16, 9, "16:9"],
          [3, 1, "3:1"]
        ].map(([rw, rh, label]) => /* @__PURE__ */ React.createElement(
          "button",
          {
            key: label,
            type: "button",
            className: "lv-chip" + (imgAdv.aspectW === rw && imgAdv.aspectH === rh ? " on" : ""),
            onClick: () => setImgAdv((a) => ({ ...a, aspectW: rw, aspectH: rh }))
          },
          label
        ))), /* @__PURE__ */ React.createElement("div", { className: "lv-row2" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Size \xB7 long edge"), /* @__PURE__ */ React.createElement(
          "select",
          {
            className: "lv-sel",
            style: { width: "100%" },
            value: imgAdv.size,
            onChange: (ev) => setImgAdv((a) => ({ ...a, size: +ev.target.value }))
          },
          /* @__PURE__ */ React.createElement("option", { value: "768" }, "S \xB7 768"),
          /* @__PURE__ */ React.createElement("option", { value: "1024" }, "M \xB7 1024"),
          /* @__PURE__ */ React.createElement("option", { value: "1536" }, "L \xB7 1536"),
          /* @__PURE__ */ React.createElement("option", { value: "2048" }, "XL \xB7 2048")
        )), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Custom W\xD7H ", /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "\xB7 overrides")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 5, alignItems: "center" } }, /* @__PURE__ */ React.createElement(
          "input",
          {
            className: "lv-in",
            type: "number",
            min: "64",
            max: "4096",
            step: "8",
            placeholder: "W",
            value: imgAdv.customW,
            onChange: (ev) => setImgAdv((a) => ({ ...a, customW: ev.target.value }))
          }
        ), /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "\xD7"), /* @__PURE__ */ React.createElement(
          "input",
          {
            className: "lv-in",
            type: "number",
            min: "64",
            max: "4096",
            step: "8",
            placeholder: "H",
            value: imgAdv.customH,
            onChange: (ev) => setImgAdv((a) => ({ ...a, customH: ev.target.value }))
          }
        )))), /* @__PURE__ */ React.createElement("div", { className: "lv-dim", style: { fontSize: 11, marginTop: 5 } }, (() => {
          const d = resolveGenDims(imgAdv);
          return "\u2192 " + d.w + " \xD7 " + d.h + (d.custom ? " \xB7 custom" : " px");
        })()), /* @__PURE__ */ React.createElement("div", { className: "lv-row2" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Mode"), /* @__PURE__ */ React.createElement(
          "select",
          {
            className: "lv-sel",
            style: { width: "100%" },
            value: imgAdv.mode,
            onChange: (ev) => setImgAdv((a) => ({ ...a, mode: ev.target.value }))
          },
          /* @__PURE__ */ React.createElement("option", { value: "auto" }, "Auto"),
          /* @__PURE__ */ React.createElement("option", { value: "lite" }, "Lite"),
          /* @__PURE__ */ React.createElement("option", { value: "standard" }, "Standard"),
          /* @__PURE__ */ React.createElement("option", { value: "pro" }, "Pro"),
          /* @__PURE__ */ React.createElement("option", { value: "ultra" }, "Ultra")
        )), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Count"), /* @__PURE__ */ React.createElement(
          "select",
          {
            className: "lv-sel",
            style: { width: "100%" },
            value: imgAdv.count,
            onChange: (ev) => setImgAdv((a) => ({ ...a, count: +ev.target.value }))
          },
          /* @__PURE__ */ React.createElement("option", { value: "1" }, "1"),
          /* @__PURE__ */ React.createElement("option", { value: "2" }, "2"),
          /* @__PURE__ */ React.createElement("option", { value: "3" }, "3"),
          /* @__PURE__ */ React.createElement("option", { value: "4" }, "4")
        ))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Seed ", /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "\xB7 blank = random")), /* @__PURE__ */ React.createElement(
          "input",
          {
            className: "lv-in",
            type: "number",
            placeholder: "random",
            value: imgAdv.seed,
            onChange: (ev) => setImgAdv((a) => ({ ...a, seed: ev.target.value }))
          }
        ), /* @__PURE__ */ React.createElement("label", { className: "lv-ck", title: "This IS the site's Turbo tier (priority=1000): a faster runner. Costs more credits when paid, but a matching free card covers it." }, /* @__PURE__ */ React.createElement(
          "input",
          {
            type: "checkbox",
            checked: imgAdv.highPriority,
            onChange: (ev) => setImgAdv((a) => ({ ...a, highPriority: ev.target.checked }))
          }
        ), " High priority \xB7 Turbo (faster)"), /* @__PURE__ */ React.createElement("label", { className: "lv-ck" }, /* @__PURE__ */ React.createElement(
          "input",
          {
            type: "checkbox",
            checked: imgAdv.promptHelper,
            onChange: (ev) => setImgAdv((a) => ({ ...a, promptHelper: ev.target.checked }))
          }
        ), " Prompt helper"), /* @__PURE__ */ React.createElement("mg-cost-badge", { ref: imgCostRef, hint: "Pick a model and write a prompt to see the cost.", "card-label": "a card" }), /* @__PURE__ */ React.createElement(
          "button",
          {
            className: "lv-go",
            disabled: busyI || anyLoraUnresolved(imgLoras) || imgLoras.some((l) => loraIncompat(imgModel && imgModel.model_type, l.lora_base_type)),
            onClick: () => genImage(active)
          },
          busyI ? gi.msg || "generating\u2026" : anyLoraUnresolved(imgLoras) ? "waiting on LoRA\u2026" : imgLoras.some((l) => loraIncompat(imgModel && imgModel.model_type, l.lora_base_type)) ? "incompatible LoRA \u2014 remove or switch base" : "\u2726 Generate reference image"
        ), gi.phase === "error" && /* @__PURE__ */ React.createElement("div", { className: "lv-gerr" }, gi.msg), gi.mid && /* @__PURE__ */ React.createElement("div", { className: "lv-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + gi.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lv-route" }, /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "route \u2192"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gi.routed === "open" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeImg(routeTarget, "open", active.c.id) }, "open frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gi.routed === "close" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeImg(routeTarget, "close", active.c.id) }, "close frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gi.routed === "cast" ? " on" : ""), onClick: () => routeImg(routeTarget || active, "cast", active.c.id) }, "cast")), gi.routed && /* @__PURE__ */ React.createElement("div", { className: "lv-ok2" }, "\u2713 sent to ", gi.routed, sel ? " \xB7 it now feeds this shot's video gen" : "")));
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
        ), /* @__PURE__ */ React.createElement("mg-cost-badge", { ref: editCostRef, hint: "Add a source image and instruction to see the cost.", "card-label": "an Edit card" }), /* @__PURE__ */ React.createElement("button", { className: "lv-go", disabled: busyE || !src, onClick: () => genEdit(active) }, busyE ? ge.msg || "editing\u2026" : "\u2726 Edit the open frame"), ge.phase === "error" && /* @__PURE__ */ React.createElement("div", { className: "lv-gerr" }, ge.msg), ge.mid && /* @__PURE__ */ React.createElement("div", { className: "lv-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + ge.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lv-route" }, /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "route \u2192"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (ge.routed === "open" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeGen(genEditState, setGenEditState, routeTarget, "open", active.c.id) }, "open frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (ge.routed === "close" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeGen(genEditState, setGenEditState, routeTarget, "close", active.c.id) }, "close frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (ge.routed === "cast" ? " on" : ""), onClick: () => routeGen(genEditState, setGenEditState, routeTarget || active, "cast", active.c.id) }, "cast")), ge.routed && /* @__PURE__ */ React.createElement("div", { className: "lv-ok2" }, "\u2713 sent to ", ge.routed)));
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
        ), /* @__PURE__ */ React.createElement("mg-cost-badge", { ref: refCostRef, hint: "Add references and a prompt to see the cost.", "card-label": "an Edit card" }), /* @__PURE__ */ React.createElement("button", { className: "lv-go", disabled: busyR || !refs.length, onClick: () => genRef(active) }, busyR ? gr.msg || "generating\u2026" : "\u2726 Generate from references"), gr.phase === "error" && /* @__PURE__ */ React.createElement("div", { className: "lv-gerr" }, gr.msg), gr.mid && /* @__PURE__ */ React.createElement("div", { className: "lv-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + gr.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lv-route" }, /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "route \u2192"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gr.routed === "open" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeGen(genRefState, setGenRefState, routeTarget, "open", active.c.id) }, "open frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gr.routed === "close" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeGen(genRefState, setGenRefState, routeTarget, "close", active.c.id) }, "close frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gr.routed === "cast" ? " on" : ""), onClick: () => routeGen(genRefState, setGenRefState, routeTarget || active, "cast", active.c.id) }, "cast")), gr.routed && /* @__PURE__ */ React.createElement("div", { className: "lv-ok2" }, "\u2713 sent to ", gr.routed)));
      } else tabBody = /* @__PURE__ */ React.createElement("div", { className: "lv-ph" }, "The ", /* @__PURE__ */ React.createElement("b", null, tab), " tab renders the shot on PixAI.");
      gen = /* @__PURE__ */ React.createElement("div", { className: "lv-gen" }, /* @__PURE__ */ React.createElement("div", { className: "lv-genhead" }, sel ? /* @__PURE__ */ React.createElement(React.Fragment, null, "\u2699 ", sel.code, " \xB7 ", sel.c.title || "untitled") : /* @__PURE__ */ React.createElement(React.Fragment, null, "\u2728 Draft generation ", /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "\u2014 generate freely, then route or attach it to a shot")), sel && /* @__PURE__ */ React.createElement(
        "button",
        {
          className: "lv-unbind",
          onClick: () => setSelShot(null),
          title: "Unbind this shot and go back to draft generation"
        },
        "\u2715 unbind"
      )), !sel && /* @__PURE__ */ React.createElement("div", { className: "lv-drafttarget" }, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Route results into a shot ", /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "(cast doesn't need one)")), /* @__PURE__ */ React.createElement("select", { className: "lv-sel", value: draftTarget, onChange: (ev) => setDraftTarget(ev.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "" }, "\u2014 choose a shot \u2014"), entries.map((e) => /* @__PURE__ */ React.createElement("option", { key: e.c.id, value: e.c.id }, e.code, " \xB7 ", e.c.title || "untitled")))), /* @__PURE__ */ React.createElement("div", { className: "lv-framehandoff" }, /* @__PURE__ */ React.createElement(
        FrameSlot,
        {
          which: "open",
          frame: active.c.openFrame,
          liveTag: positionTag(active, project, imgSrc, "openFrame"),
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
          liveTag: positionTag(active, project, imgSrc, "closeFrame"),
          discreet: active.c.discreet,
          framePrev: frameSrc,
          storeThumb,
          openPick,
          onPatch: (p) => patchFrame("closeFrame", p)
        }
      )), acct && /* @__PURE__ */ React.createElement("div", { className: "lv-bal" }, "\u26A1 ", acct.credits == null ? "\u2014" : acct.credits, " credits \xB7 ", acct.cards || 0, " card", acct.cards === 1 ? "" : "s", acct.claim_credits ? /* @__PURE__ */ React.createElement("span", { className: "lv-balclaim" }, " \xB7 +", acct.claim_credits, " claimable") : null), tabBody, /* @__PURE__ */ React.createElement("mg-generate-drawer", { ref: bindGenDrawer, "data-loom-ctx": "", style: { display: tab === "Video" ? "" : "none" } }), videoTrailer);
    }
    const castList = /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lv-castrow-h" }, "Cast & assets", sel ? /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, " \u2014 bound to ", sel.code) : null), /* @__PURE__ */ React.createElement("details", { className: "lv-look", open: !!(project.look || "").trim() }, /* @__PURE__ */ React.createElement("summary", null, "\u{1F3A8} Project look", (project.look || "").trim() ? "" : /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, " \u2014 a style line added to every shot")), /* @__PURE__ */ React.createElement(
      "textarea",
      {
        className: "lv-lookin",
        value: project.look || "",
        rows: 2,
        onChange: (e) => setLook(e.target.value),
        placeholder: "e.g. muted teal grade, 35mm grain, anamorphic flares \u2014 applied to every shot's prompt"
      }
    )), /* @__PURE__ */ React.createElement("div", { className: "lv-tabs lv-density" }, /* @__PURE__ */ React.createElement("span", { className: "lv-tab " + (density === "simple" ? "on" : ""), onClick: () => setDensity("simple") }, "Simple"), /* @__PURE__ */ React.createElement("span", { className: "lv-tab " + (density === "detailed" ? "on" : ""), onClick: () => setDensity("detailed") }, "Detailed")), density === "detailed" ? (project.assets || []).map((as) => {
      const inShot = sel && (sel.c.cast || []).includes(as.id);
      const toggleInShot = () => sel && setCard(sel.a.id, sel.c.id, (c) => ({ ...c, cast: (c.cast || []).includes(as.id) ? c.cast.filter((x) => x !== as.id) : [...c.cast || [], as.id] }));
      const src = frameSrc(as);
      return /* @__PURE__ */ React.createElement("div", { key: as.id, className: "lv-assetrow" }, as.kind !== "audio" && /* @__PURE__ */ React.createElement(
        "button",
        {
          className: "lv-pickico",
          title: "Pick from your gallery",
          onClick: () => openPick((mid) => setAssets((a) => a.map((x) => x.id !== as.id ? x : { ...x, thumbId: "", source: "", mediaId: mid })), as.kind === "video" ? "video" : "image")
        },
        "\u{1F5BC}"
      ), as.kind === "image" ? /* @__PURE__ */ React.createElement("label", { className: "lv-assetprev", title: "Attach image" }, src ? /* @__PURE__ */ React.createElement("img", { src, alt: "" }) : "\uFF0B", /* @__PURE__ */ React.createElement(
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
      )) : /* @__PURE__ */ React.createElement("div", { className: "lv-assetprev", title: as.kind === "video" ? "Video asset \u2014 poster from your gallery" : void 0 }, as.kind === "video" && src ? /* @__PURE__ */ React.createElement("img", { src, alt: "" }) : as.kind === "video" ? "\u{1F39E}" : "\u266A"), /* @__PURE__ */ React.createElement(
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
    }), "all", true) }, "+ add from gallery"), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "lv-addcast",
        onClick: () => setImportOpen(true),
        title: "Pull a whole gallery collection in as reusable @image references"
      },
      "\u21AF Import collection"
    ));
    const finished = entries.filter((e) => e.c.resultMid);
    const addAssetFromFile = async (file) => {
      if (!file || !file.type || !file.type.startsWith("image/")) return;
      const id = await storeThumb(file);
      setAssets((a) => [...a, { id: uid(), name: "", kind: "image", tag: nextTag(a, "@image"), thumbId: id, source: file.name, lock: false }]);
    };
    const importPickedFootage = async (mid, duration) => {
      let dur = parseFloat(duration);
      if (!(dur > 0)) {
        try {
          const r = await fetch("/api/loom/video-duration?media_id=" + encodeURIComponent(mid));
          const d = await r.json();
          if (d && d.duration) dur = d.duration;
        } catch {
        }
      }
      setSelShot(importFootage(mid, dur));
    };
    const footageList = /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lv-footagehead" }, /* @__PURE__ */ React.createElement("span", { className: "lv-castrow-h" }, "Finished shots"), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "lv-browsebtn",
        title: "Import an already-rendered video from your gallery straight onto the board as a real, placeable shot",
        onClick: () => openPick((mid, thumb, isVideo, duration) => {
          if (!isVideo) return;
          importPickedFootage(mid, duration);
        }, "video")
      },
      "\u2315 Browse library"
    )), finished.length ? /* @__PURE__ */ React.createElement("div", { className: "lv-footage" }, finished.map((e) => /* @__PURE__ */ React.createElement("div", { key: e.c.id, className: "lv-fclip " + (e.c.id === selShot ? "sel" : ""), onClick: () => setSelShot(e.c.id) }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + e.c.resultMid + ".jpg", alt: "" }), /* @__PURE__ */ React.createElement("div", { className: "lv-fmeta" }, /* @__PURE__ */ React.createElement("b", null, e.code), e.c.imported && /* @__PURE__ */ React.createElement("span", { title: "Imported from your gallery, not rendered by this project" }, "\u21AF"), /* @__PURE__ */ React.createElement("span", null, durOf2(e.c), "s"))))) : /* @__PURE__ */ React.createElement("div", { className: "lv-ph" }, "No rendered shots yet \u2014 generate one and it lands here."), /* @__PURE__ */ React.createElement(
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
    return /* @__PURE__ */ React.createElement("div", { className: "lv-overlay" + (deepFocus ? " lv-overlay-df" : "") }, /* @__PURE__ */ React.createElement("style", null, V2_STYLES), /* @__PURE__ */ React.createElement("div", { className: "lv-top" }, /* @__PURE__ */ React.createElement("span", { className: "lv-eyebrow" }, "The Loom \xB7 V2"), /* @__PURE__ */ React.createElement("span", { className: "lv-note" }, "Click a shot \u2192 it binds to Generate."), /* @__PURE__ */ React.createElement(ProjectSwitcher, { api: projectApi }), /* @__PURE__ */ React.createElement(
      "label",
      {
        className: "lv-draft" + (project.draft ? " on" : ""),
        title: "Draft mode renders every shot at the cheaper 'basic' quality \u2014 block out the animatic, then turn Draft off and re-generate the keepers at pro quality"
      },
      /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: !!project.draft, onChange: (e) => setDraft(e.target.checked) }),
      "\u26A1 Draft"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => {
          const pending = genDrawerRef.current && genDrawerRef.current.flushPromptEdit ? genDrawerRef.current.flushPromptEdit() : null;
          let liveEntries = entries;
          if (pending != null && activeRef.current) {
            const a = activeRef.current;
            const already = !!a.c.promptOverride;
            const composed = already ? null : shotText(a, project);
            if (already || pending !== composed) {
              const patchedCard = setPromptOverride(a.c, pending);
              liveEntries = entries.map((e) => e.c.id === a.c.id ? { ...e, c: patchedCard } : e);
              a.c.id === "__draft__" ? setDraftCard(() => patchedCard) : setCard(a.a.id, a.c.id, () => patchedCard);
            }
          }
          batchGenerate(liveEntries);
        },
        disabled: batching || !entries.length,
        title: "Generate every shot that isn't done yet, one after another"
      },
      batching ? "\u25B6 generating all\u2026" : `\u25B6 Generate all (${costEstimate.notDoneCount})`
    ), costEstimate.notDoneCount > 0 && /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "lv-cost-pill",
        onClick: refreshEstimate,
        disabled: batching,
        title: costTooltip(costEstimate) + " \u2014 estimate reflects Generate-all composition; a shot generated by hand from its own Video-tab drawer (esp. I2V/FLF with both cast images and a frame set) may price differently. Click to refresh."
      },
      formatCostEstimate(costEstimate)
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        disabled: !entries.some((e) => e.c.resultMid),
        onClick: () => playSequence(entries),
        title: "Play every finished shot back-to-back, honoring trims \u2014 a rough cut, no rendering"
      },
      "\u25B6\u25B6 Play"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        disabled: !entries.some((e) => e.c.resultMid),
        onClick: () => exportCut(entries),
        title: "Trim + stitch every finished shot into one mp4 (ffmpeg)"
      },
      "\u21E9 Export"
    ), /* @__PURE__ */ React.createElement(
      ExportMenu,
      {
        exportAll,
        exportJSON,
        exportBundle,
        bundling,
        importBackup
      }
    ), /* @__PURE__ */ React.createElement("a", { className: "lv-close", href: "/", style: { textDecoration: "none" } }, "\u2190 Gallery")), batchTally && (() => {
      const outs = Object.values(batchTally.outcomes);
      const done = outs.filter((o) => o === "done").length;
      const failed = outs.filter((o) => o === "failed").length;
      const stale = outs.filter((o) => o === "stale").length;
      return /* @__PURE__ */ React.createElement("div", { className: "lv-batchbar" }, "Batch: ", batchTally.submitted, "/", batchTally.total, " submitted \xB7 ", done, " done", failed ? /* @__PURE__ */ React.createElement(React.Fragment, null, " \xB7 ", /* @__PURE__ */ React.createElement("span", { className: "lv-batchfail" }, failed, " failed")) : null, stale ? /* @__PURE__ */ React.createElement(React.Fragment, null, " \xB7 ", /* @__PURE__ */ React.createElement("span", { className: "lv-batchstale" }, stale, " paused (check manually)")) : null, done + failed + stale < batchTally.total ? " \xB7 rendering\u2026" : "");
    })(), timelineDrawer, /* @__PURE__ */ React.createElement("div", { className: "lv-shell" }, /* @__PURE__ */ React.createElement("div", { className: "lv-side left" + (leftCollapsed ? " collapsed" : "") + (!leftCollapsed && leftTab === "cast" && density === "detailed" ? " wide" : "") }, /* @__PURE__ */ React.createElement("div", { className: "lv-sidehead" }, !leftCollapsed && /* @__PURE__ */ React.createElement("div", { className: "lv-tabs lv-sidetabs" }, /* @__PURE__ */ React.createElement("span", { className: "lv-tab " + (leftTab === "cast" ? "on" : ""), onClick: () => setLeftTab("cast") }, "Cast & assets"), /* @__PURE__ */ React.createElement("span", { className: "lv-tab " + (leftTab === "footage" ? "on" : ""), onClick: () => setLeftTab("footage") }, "Footage")), /* @__PURE__ */ React.createElement("button", { className: "lv-col", onClick: () => setLeftCollapsed((v) => !v), title: "collapse" }, leftCollapsed ? "\u25B8" : "\u25C2")), leftCollapsed ? /* @__PURE__ */ React.createElement("div", { className: "lv-railicons" }, /* @__PURE__ */ React.createElement("button", { className: "lv-railbtn" + (leftTab === "cast" ? " on" : ""), title: "Cast & assets", onClick: () => {
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
      const dfAppend = (field, val) => dfPatch((cc) => ({ ...cc, [field]: cc[field] ? `${cc[field]}, ${val}` : val }));
      const c = live.c;
      return /* @__PURE__ */ React.createElement("div", { className: "lv-df-veil", onClick: (ev) => {
        if (ev.target === ev.currentTarget) setDeepFocus(null);
      } }, /* @__PURE__ */ React.createElement("div", { className: "lv-df" }, /* @__PURE__ */ React.createElement("div", { className: "lv-df-head" }, /* @__PURE__ */ React.createElement(
        "button",
        {
          className: "sb-tick " + c.status,
          title: `Status: ${c.status} (click to cycle${c.status === "error" ? " \u2014 clears the error" : ""})`,
          onClick: () => dfPatch((cc) => ({ ...cc, status: cc.status === "todo" ? "wip" : cc.status === "wip" ? "done" : "todo" }))
        },
        "\u2713"
      ), /* @__PURE__ */ React.createElement("span", { className: "lv-df-code" }, deepFocus.code), /* @__PURE__ */ React.createElement(
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
          onClick: () => dfPatch((cc) => setShotMode(cc, m))
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
      )), /* @__PURE__ */ React.createElement("div", { className: "lv-field narrow" }, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Discreet"), /* @__PURE__ */ React.createElement("label", { className: "sb-toggle", title: "Blur this shot's frames/refs on the board" }, /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: c.discreet, onChange: (ev) => dfPatch((cc) => ({ ...cc, discreet: ev.target.checked })) }), "blur previews"))), /* @__PURE__ */ React.createElement("div", { className: "sb-field", style: { marginTop: 10 } }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Prompt"), /* @__PURE__ */ React.createElement(
        "textarea",
        {
          className: "lv-ta",
          value: c.prompt || "",
          placeholder: "what happens in this shot",
          onChange: (ev) => {
            if (c.promptOverride) {
              setOverrideClearedFlash(true);
              setTimeout(() => setOverrideClearedFlash(false), 1600);
            }
            dfPatch((cc) => ({ ...clearPromptOverride(cc), prompt: ev.target.value }));
          }
        }
      ), overrideClearedFlash && /* @__PURE__ */ React.createElement("div", { className: "lv-overrideflash" }, "override cleared \u2014 back to auto-compose"), /* @__PURE__ */ React.createElement("span", { className: "sb-hint" }, "the shot's base prompt \u2014 Camera, Lighting and cast are woven in on top when it generates")), /* @__PURE__ */ React.createElement("div", { className: "lv-df-frames" }, /* @__PURE__ */ React.createElement(
        FrameSlot,
        {
          which: "open",
          frame: c.openFrame,
          liveTag: positionTag(live, project, imgSrc, "openFrame"),
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
          liveTag: positionTag(live, project, imgSrc, "closeFrame"),
          discreet: c.discreet,
          framePrev: frameSrc,
          storeThumb,
          openPick,
          onPatch: (p) => dfPatchFrame("closeFrame", p)
        }
      )), /* @__PURE__ */ React.createElement("div", { className: "sb-field" }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Other references & @tags"), c.refs.map((r) => {
        const preview = r.thumbId ? thumbs[r.thumbId] : r.kind === "image" && r.source.startsWith("http") ? r.source : null;
        return /* @__PURE__ */ React.createElement("div", { className: "sb-ref", key: r.id }, r.kind === "image" ? /* @__PURE__ */ React.createElement("label", { className: "sb-refprev" + (c.discreet ? " discreet" : ""), title: "Attach image" }, preview ? /* @__PURE__ */ React.createElement("img", { src: preview, alt: r.tag }) : "\uFF0B", /* @__PURE__ */ React.createElement(
          "input",
          {
            type: "file",
            accept: "image/*",
            style: { display: "none" },
            onChange: async (e) => {
              const f = e.target.files[0];
              if (!f) return;
              const id = await storeThumb(f);
              setRef(live.a.id, c.id, r.id, { thumbId: id, source: r.source || f.name });
            }
          }
        )) : /* @__PURE__ */ React.createElement("div", { className: "sb-refprev" }, r.kind === "video" ? "\u{1F39E}" : "\u266A"), /* @__PURE__ */ React.createElement("div", { className: "sb-refbody" }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("input", { className: "sb-tagin sb-mono", value: r.tag, onChange: (e) => setRef(live.a.id, c.id, r.id, { tag: e.target.value }) }), /* @__PURE__ */ React.createElement("span", { className: "sb-hint" }, r.kind), /* @__PURE__ */ React.createElement("button", { className: "sb-ico", style: { marginLeft: "auto" }, onClick: () => delRef(live.a.id, c.id, r) }, "\u2715")), /* @__PURE__ */ React.createElement("input", { className: "sb-in", placeholder: "what to use it for (motion / camera / mood\u2026)", value: r.role, onChange: (e) => setRef(live.a.id, c.id, r.id, { role: e.target.value }) }), /* @__PURE__ */ React.createElement("input", { className: "sb-in", placeholder: "file name or URL", value: r.source, onChange: (e) => setRef(live.a.id, c.id, r.id, { source: e.target.value }) })));
      }), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 7, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm ghost", onClick: () => addRef(live.a.id, c, "image") }, "+ Image"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm ghost", onClick: () => addRef(live.a.id, c, "video") }, "+ Video"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm ghost", onClick: () => addRef(live.a.id, c, "audio") }, "+ Audio"))), /* @__PURE__ */ React.createElement("div", { className: "sb-field" }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Music / audio cue ", /* @__PURE__ */ React.createElement("button", { className: "sb-ico", style: { fontSize: 11 }, onClick: () => setDfPalFor(dfPalFor === "audio" ? null : "audio") }, "\uFF0Bterms")), /* @__PURE__ */ React.createElement("input", { className: "sb-in", value: c.audioCue, onChange: (ev) => dfPatch((cc) => ({ ...cc, audioCue: ev.target.value })), placeholder: "track, beat sync, room tone\u2026" }), dfPalFor === "audio" && /* @__PURE__ */ React.createElement("div", { className: "sb-pal" }, AUDIO_PALETTE.map((t) => /* @__PURE__ */ React.createElement("button", { key: t, className: "sb-pchip sb-mono", onClick: () => dfAppend("audioCue", t) }, t)))), /* @__PURE__ */ React.createElement("div", { className: "sb-field" }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Notes"), /* @__PURE__ */ React.createElement("textarea", { className: "sb-ta", value: c.notes, onChange: (ev) => dfPatch((cc) => ({ ...cc, notes: ev.target.value })), placeholder: "blocking, continuity reminders\u2026" })), /* @__PURE__ */ React.createElement("div", { className: "sb-toolbar" }, /* @__PURE__ */ React.createElement("button", { className: "sb-btn amber sm", onClick: () => copyShot(live) }, "Copy shot")), /* @__PURE__ */ React.createElement("button", { className: "lv-go", onClick: () => {
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
      clearTimeout(saveTimer.current);
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
    const _adoptBackup = async (d) => {
      if (!d || !d.project) {
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
    };
    const importJSON = async (file) => {
      if (!file) return;
      try {
        await _adoptBackup(JSON.parse(await file.text()));
      } catch {
        window.alert("That file didn't parse as a storyboard backup.");
      }
    };
    const importBundle = async (file) => {
      if (!file) return;
      try {
        const fd = new FormData();
        fd.append("file", file);
        const r = await fetch("/api/loom/import-bundle", { method: "POST", body: fd });
        const d = await r.json();
        if (d.error) {
          window.alert("Couldn't import that bundle: " + d.error);
          return;
        }
        await _adoptBackup(d);
      } catch {
        window.alert("Couldn't import that bundle -- network error.");
      }
    };
    const importBackup = (file) => {
      if (!file) return;
      const isZip = /\.zip$/i.test(file.name) || file.type === "application/zip";
      return isZip ? importBundle(file) : importJSON(file);
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
      importJSON,
      importBackup,
      activeId
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
    const importFootage = (mediaId, duration) => {
      const c = newCard(importedFootagePatch(mediaId, duration));
      setProject((p) => landInFirstAct(p, c, uid()));
      return c.id;
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
    const splitShot = (entry, t) => setProject((p) => splitCardAt(p, entry.a.id, entry.c.id, t, uid()));
    return {
      open,
      setOpen,
      setCard,
      setAct,
      setAssets,
      setCardStatus,
      addCard,
      importFootage,
      dupCard,
      delCard,
      moveCard,
      moveCardToAct: moveCardToAct2,
      addAct,
      delAct,
      moveAct,
      addRef,
      setRef,
      delRef,
      splitShot
    };
  }
  function useGenerationPipeline({ project, thumbs, setCard, setCardStatus, setAssets, openPick, activeId }) {
    const [genState, setGenState] = useState({});
    const resumedRef = useRef({});
    const [genImgState, setGenImgState] = useState({});
    const [imgModel, setImgModel] = useState(null);
    const [imgLoras, setImgLoras] = useState([]);
    const [imgAdv, setImgAdv] = useState(() => ({
      negative: "",
      steps: 25,
      cfg: 7,
      aspectW: 1,
      aspectH: 1,
      size: 1024,
      customW: "",
      customH: "",
      mode: "auto",
      count: 1,
      seed: "",
      highPriority: false,
      promptHelper: true
    }));
    const [modelDefaults, setModelDefaults] = useState(null);
    const [genEditState, setGenEditState] = useState({});
    const [genRefState, setGenRefState] = useState({});
    const [batching, setBatching] = useState(false);
    const [batchTally, setBatchTally] = useState(null);
    const setBatchOutcome = (cardId, outcome) => setBatchTally((prev) => prev && prev.ids.has(cardId) ? { ...prev, outcomes: { ...prev.outcomes, [cardId]: outcome } } : prev);
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
    const confirmSpend = async (priceBody, label) => {
      let pr = null;
      try {
        const r = await fetch("/api/price", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(priceBody)
        });
        pr = await r.json();
      } catch {
        pr = null;
      }
      if (pr && pr.free) return true;
      if (pr && !pr.free && pr.cost != null) {
        return window.confirm(`${label}

No free card covers it \u2014 it will spend ~${pr.cost.toLocaleString()} credits.

Generate anyway?`);
      }
      return window.confirm(`${label}

Couldn't verify the cost or free-card coverage \u2014 it may spend credits.

Generate anyway?`);
    };
    const generateShot = async (entry, opts = {}) => {
      const c = entry.c;
      const p = shotPayload2(entry);
      if (!p.hasInput) {
        const msg = c.imported ? 'Imported footage \u2014 nothing to re-roll. Attach a frame/cast image to render a NEW clip here, or swap the video via "Use an existing video instead".' : "attach a frame or cast image first";
        setGenState((s) => ({ ...s, [c.id]: { phase: "error", msg } }));
        return { ok: false, reason: "no-input" };
      }
      if (!opts.skipConfirm) {
        const pr = await priceShot(entry);
        if (pr && !pr.free && pr.cost != null) {
          if (!window.confirm(`No free card covers this shot \u2014 it will spend ~${pr.cost.toLocaleString()} credits.

Generate anyway?`)) return { ok: false, reason: "cancelled" };
        } else if (!pr || !pr.free) {
          if (!window.confirm("Couldn't verify this shot's cost or free-card coverage \u2014 it may spend credits.\n\nGenerate anyway?")) return { ok: false, reason: "cancelled" };
        }
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
            quality: p.quality,
            generate_audio: p.generate_audio,
            audio_language: p.audio_language,
            origin: "loom-shot"
          })
        });
        const d = await r.json();
        if (d.error || !d.task_id) {
          setGenState((s) => ({ ...s, [c.id]: { phase: "error", msg: d.error ? friendlyGenErr(d.error) : "submit failed" } }));
          return { ok: false, reason: "submit-failed" };
        }
        const startedAt = Date.now();
        setCardStatus(c.id, { pendingTaskId: d.task_id, genStartedAt: startedAt });
        pollShot(c.id, d.task_id, startedAt);
        if (window.Jobs && window.Jobs.register) window.Jobs.register(d.task_id, entry.code + " \xB7 " + (c.title || "untitled"));
        return { ok: true, taskId: d.task_id };
      } catch {
        setGenState((s) => ({ ...s, [c.id]: { phase: "error", msg: "network error" } }));
        return { ok: false, reason: "network" };
      }
    };
    const POLL_SLOW_AT_MS = 20 * 60 * 1e3;
    const POLL_SLOW_MS = 20 * 1e3;
    const POLL_STALE_AT_MS = 90 * 60 * 1e3;
    const POLL_STALE_MS = 3 * 60 * 1e3;
    const POLL_CEILING_MS = 6 * 60 * 60 * 1e3;
    const pollShot = (cardId, tid, existingStartedAt) => {
      setGenState((s) => ({ ...s, [cardId]: { phase: "running", msg: "Rendering\u2026 (task " + String(tid).slice(-6) + ")" } }));
      const startedAt = existingStartedAt || Date.now();
      const pause = () => {
        setGenState((s) => ({ ...s, [cardId]: {
          phase: "paused",
          msg: "Paused auto-checking after " + elapsedLabel(POLL_CEILING_MS) + " with no result \u2014 click to check again, or check the task on pixai.art (task " + String(tid).slice(-6) + ")"
        } }));
        setBatchOutcome(cardId, "stale");
      };
      const tick = () => fetch("/api/task-status?task_id=" + tid).then((r) => r.json()).then((d) => {
        const cls = classifyTaskStatus(d);
        const elapsed = Date.now() - startedAt;
        if (cls.phase === "done") {
          setGenState((s) => ({ ...s, [cardId]: { phase: "done", msg: "Done", mid: cls.mid, duration: cls.duration } }));
          setCardStatus(cardId, { status: "done", resultMid: cls.mid, trimIn: 0, trimOut: null, pendingTaskId: null, genStartedAt: null, ...cls.duration ? { actualDur: cls.duration } : {} });
          setBatchOutcome(cardId, "done");
          if (window.JobsCard && window.JobsCard.refresh) window.JobsCard.refresh();
        } else if (cls.phase === "failed") {
          setGenState((s) => ({ ...s, [cardId]: { phase: "error", msg: cls.msg } }));
          setCardStatus(cardId, { status: "error", pendingTaskId: null, genStartedAt: null });
          setBatchOutcome(cardId, "failed");
          if (window.JobsCard && window.JobsCard.refresh) window.JobsCard.refresh();
        } else if (elapsed > POLL_CEILING_MS) {
          pause();
        } else if (elapsed > POLL_STALE_AT_MS) {
          setGenState((s) => ({ ...s, [cardId]: {
            phase: "stale",
            msg: "Still going after " + elapsedLabel(elapsed) + " \u2014 unusual. Check pixai.art, or keep waiting (task " + String(tid).slice(-6) + ")"
          } }));
          setTimeout(tick, POLL_STALE_MS);
        } else if (elapsed > POLL_SLOW_AT_MS) {
          setGenState((s) => ({ ...s, [cardId]: {
            phase: "slow",
            msg: "Taking longer than expected (" + elapsedLabel(elapsed) + ", task " + String(tid).slice(-6) + ")"
          } }));
          setTimeout(tick, POLL_SLOW_MS);
        } else setTimeout(tick, 4e3);
      }).catch(() => {
        const elapsed = Date.now() - startedAt;
        if (elapsed > POLL_CEILING_MS) {
          pause();
          return;
        }
        setTimeout(tick, elapsed > POLL_STALE_AT_MS ? POLL_STALE_MS : elapsed > POLL_SLOW_AT_MS ? POLL_SLOW_MS : 5e3);
      });
      setTimeout(tick, 2500);
    };
    useEffect(() => {
      if (!project) return;
      (project.acts || []).forEach((a) => (a.cards || []).forEach((c) => {
        if (c.status === "wip" && c.pendingTaskId && !resumedRef.current[c.pendingTaskId]) {
          resumedRef.current[c.pendingTaskId] = true;
          pollShot(c.id, c.pendingTaskId, c.genStartedAt);
        }
      }));
    }, [activeId]);
    const useExistingVideo = (entry) => {
      openPick((mid, thumb, isVideo, duration) => {
        const dur = parseFloat(duration);
        setGenState((s) => ({ ...s, [entry.c.id]: { phase: "done", msg: "Attached from your gallery", mid } }));
        setCardStatus(entry.c.id, {
          status: "done",
          resultMid: mid,
          trimIn: 0,
          trimOut: null,
          pendingTaskId: null,
          genStartedAt: null,
          ...dur > 0 ? { actualDur: dur } : {}
        });
      }, "video");
    };
    const pollTaskWithCeiling = (tid, setState, cardId) => {
      const startedAt = Date.now();
      const tick = () => fetch("/api/task-status?task_id=" + tid).then((r) => r.json()).then((d) => {
        const cls = classifyTaskStatus(d);
        if (cls.phase === "done") setState((s) => ({ ...s, [cardId]: { phase: "done", msg: "Done", mid: cls.mid } }));
        else if (cls.phase === "failed") setState((s) => ({ ...s, [cardId]: { phase: "error", msg: cls.msg } }));
        else again(4e3);
      }).catch(() => again(5e3));
      const again = (ms) => {
        if (Date.now() - startedAt > POLL_CEILING_MS) {
          setState((s) => ({ ...s, [cardId]: {
            phase: "error",
            msg: "Stopped checking after " + elapsedLabel(POLL_CEILING_MS) + " \u2014 the task may still be running; check it on pixai.art (task " + String(tid).slice(-6) + ")"
          } }));
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
      if (!imgModel) {
        setGenImgState((s) => ({ ...s, [c.id]: { phase: "error", msg: "pick a model first" } }));
        return;
      }
      if (!prompt) {
        setGenImgState((s) => ({ ...s, [c.id]: { phase: "error", msg: "enter an image prompt" } }));
        return;
      }
      if (anyLoraUnresolved(imgLoras)) {
        setGenImgState((s) => ({ ...s, [c.id]: { phase: "error", msg: "still waiting on a LoRA to resolve" } }));
        return;
      }
      const body = buildImgGenBody(imgModel, imgLoras, imgAdv, prompt);
      if (!await confirmSpend(body, `Generate a reference image for ${c.title || "this shot"}?`)) return;
      setGenImgState((s) => ({ ...s, [c.id]: { phase: "submitting", msg: "Submitting\u2026" } }));
      try {
        const r = await fetch("/api/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body)
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
    const runGen = async (setState, cardId, endpoint, body, priceBody, label) => {
      if (priceBody && !await confirmSpend(priceBody, label)) return;
      setState((s) => ({ ...s, [cardId]: { phase: "submitting", msg: "Submitting\u2026" } }));
      const poll = (tid) => pollTaskWithCeiling(tid, setState, cardId);
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
      const editBody = { source: src, instruction, edit_model: "edit-pro" };
      runGen(
        setGenEditState,
        c.id,
        "/api/edit",
        editBody,
        { mode: "edit", ...editBody },
        `Edit the open frame of ${c.title || "this shot"}?`
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
      const refBody = { source: refs[0], sources: refs, instruction: prompt, edit_model: "reference-pro" };
      runGen(
        setGenRefState,
        c.id,
        "/api/edit",
        refBody,
        { mode: "edit", ...refBody },
        `Generate a still for ${c.title || "this shot"} from ${refs.length} reference${refs.length === 1 ? "" : "s"}?`
      );
    };
    const batchGenerate = async (entries) => {
      const todo = entries.filter((e) => e.c.status !== "done" && e.c.status !== "wip");
      if (!todo.length) return;
      setBatching(true);
      const prices = await Promise.all(todo.map((e) => priceShot(e)));
      const { free, paid, credits, unknown } = tallyPrices(prices);
      const emptyPromptShots = todo.filter((e) => !effectivePrompt(e.c).trim());
      const msg = `Generate ${todo.length} shot(s)?

\u{1F3AB} ${free} covered by a free card
\u2248 ${paid} will spend credits \u2014 about ${credits.toLocaleString()} total` + (unknown ? `
\u26A0 ${unknown} shot(s)' cost couldn't be verified \u2014 they may also spend credits.` : ".") + (emptyPromptShots.length ? `
\u26A0 ${emptyPromptShots.length} shot(s) have no prompt text yet: ${emptyPromptShots.map((e) => e.code).join(", ")}` : "");
      if (!window.confirm(msg)) {
        setBatching(false);
        return;
      }
      const ids = new Set(todo.map((e) => e.c.id));
      setBatchTally({ total: todo.length, submitted: 0, ids, outcomes: {} });
      for (const e of todo) {
        let r;
        try {
          r = await generateShot(e, { skipConfirm: true });
        } catch (_e) {
          r = { ok: false };
        }
        if (r.ok) setBatchTally((prev) => prev && prev.ids.has(e.c.id) ? { ...prev, submitted: prev.submitted + 1 } : prev);
        else setBatchOutcome(e.c.id, "failed");
        await new Promise((res) => setTimeout(res, 2200));
      }
      setBatching(false);
    };
    const PRICE_DEBOUNCE_MS = 600;
    const [priceCache, setPriceCache] = useState({});
    const priceInFlightRef = useRef({});
    const ensurePriced = useCallback((entry, force) => {
      const payload = shotPayload2(entry);
      const fp = priceFingerprint(payload);
      const cached = priceCache[entry.c.id];
      if (!force && cached && cached.fp === fp && !cached.loading) return;
      if (!payload.hasInput) {
        setPriceCache((s) => ({ ...s, [entry.c.id]: { fp, pr: null, loading: false } }));
        return;
      }
      if (priceInFlightRef.current[entry.c.id] === fp) return;
      priceInFlightRef.current[entry.c.id] = fp;
      setPriceCache((s) => ({ ...s, [entry.c.id]: { fp, pr: cached && cached.fp === fp ? cached.pr : null, loading: true } }));
      priceShot(entry).then((pr) => {
        const stillCurrent = priceInFlightRef.current[entry.c.id] === fp;
        if (stillCurrent) delete priceInFlightRef.current[entry.c.id];
        if (!stillCurrent) return;
        setPriceCache((s) => ({ ...s, [entry.c.id]: { fp, pr, loading: false } }));
      });
    }, [project, priceCache]);
    const { notDone, notDoneFp } = useMemo(() => {
      const boardEntries = project ? flat(project) : [];
      const nd = boardEntries.filter((e) => e.c.status !== "done");
      const fp = nd.map((e) => e.c.id + ":" + priceFingerprint(shotPayload2(e))).join("|");
      return { notDone: nd, notDoneFp: fp };
    }, [project]);
    const priceDebounceRef = useRef(null);
    useEffect(() => {
      clearTimeout(priceDebounceRef.current);
      priceDebounceRef.current = setTimeout(() => notDone.forEach((e) => ensurePriced(e)), PRICE_DEBOUNCE_MS);
      return () => clearTimeout(priceDebounceRef.current);
    }, [notDoneFp]);
    const refreshEstimate = useCallback(() => notDone.forEach((e) => ensurePriced(e, true)), [notDone, ensurePriced]);
    const pending = notDone.filter((e) => {
      const r = priceCache[e.c.id];
      return !r || r.loading;
    }).length;
    const settled = notDone.filter((e) => {
      const r = priceCache[e.c.id];
      return r && !r.loading;
    }).map((e) => priceCache[e.c.id].pr);
    const costEstimate = { ...tallyPrices(settled), pending, notDoneCount: notDone.length };
    return {
      genState,
      setGenState,
      genImgState,
      setGenImgState,
      imgModel,
      setImgModel,
      imgLoras,
      setImgLoras,
      imgAdv,
      setImgAdv,
      modelDefaults,
      setModelDefaults,
      genEditState,
      setGenEditState,
      genRefState,
      setGenRefState,
      batching,
      batchTally,
      generateShot,
      pollShot,
      useExistingVideo,
      genImage,
      routeImg,
      genEdit,
      genRef,
      routeGen,
      batchGenerate,
      costEstimate,
      refreshEstimate
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
    const [bundling, setBundling] = useState(false);
    const exportBundle = async () => {
      setBundling(true);
      try {
        const r = await fetch("/api/loom/export-bundle", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ project, thumbs })
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          alert("Bundle export failed: " + (d.error || r.status));
          return;
        }
        const missing = parseInt(r.headers.get("X-Bundle-Missing-Count") || "0", 10);
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${project.name.replace(/\s+/g, "_")}_bundle.zip`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1e3);
        if (missing) alert(`Bundle exported, but ${missing} referenced file(s) couldn't be found on disk and were left out.`);
      } catch {
        alert("Bundle export failed -- network error.");
      } finally {
        setBundling(false);
      }
    };
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
        body: JSON.stringify({ clips: clips.map((c) => ({ mid: c.mid, in: c.in, out: c.out, crop: c.crop })), total_seconds: total })
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
    return {
      seq,
      exp,
      playSequence,
      exportCut,
      cancelExport,
      closeExport,
      closeSequence,
      exportAll,
      exportJSON,
      exportBundle,
      bundling
    };
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
      importBackup,
      activeId
    } = useProjectStore(setSelShot);
    const {
      open,
      setOpen,
      setCard,
      setAct,
      setAssets,
      setCardStatus,
      addCard,
      importFootage,
      dupCard,
      delCard,
      moveCard,
      moveCardToAct: moveCardToAct2,
      addAct,
      delAct,
      moveAct,
      addRef,
      setRef,
      delRef,
      splitShot
    } = useShotMutations(project, setProject);
    const [pickCb, setPickCb] = useState(null);
    const [pickKind, setPickKind] = useState("image");
    const [pickAllowType, setPickAllowType] = useState(false);
    const [importOpen, setImportOpen] = useState(false);
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
          if (cb) cb(e.detail.media_id, e.detail.thumb, e.detail.is_video, e.detail.duration, e.detail.is_nsfw);
        });
        el.addEventListener("mg-close", () => setPickCb(null));
      }
    }, [pickCb]);
    const {
      genState,
      setGenState,
      genImgState,
      setGenImgState,
      imgModel,
      setImgModel,
      imgLoras,
      setImgLoras,
      imgAdv,
      setImgAdv,
      modelDefaults,
      setModelDefaults,
      genEditState,
      setGenEditState,
      genRefState,
      setGenRefState,
      batching,
      batchTally,
      pollShot,
      useExistingVideo,
      genImage,
      routeImg,
      genEdit,
      genRef,
      routeGen,
      batchGenerate,
      costEstimate,
      refreshEstimate
    } = useGenerationPipeline({ project, thumbs, setCard, setCardStatus, setAssets, openPick, activeId });
    const onVideoSubmit = useCallback((cardId, detail) => {
      setGenState((s) => ({ ...s, [cardId]: { phase: "running", msg: "Rendering\u2026 (task " + String(detail.task_id).slice(-6) + ")" } }));
      setCardStatus(cardId, { status: "wip", pendingTaskId: detail.task_id, genStartedAt: Date.now() });
      if (window.Jobs && window.Jobs.register) window.Jobs.register(detail.task_id, "Rendered");
    }, [setGenState, setCardStatus]);
    const onVideoResult = useCallback((cardId, detail) => {
      const mid = (detail.media_ids || [])[0];
      setGenState((s) => ({ ...s, [cardId]: { phase: "done", msg: "Done", mid, duration: detail.duration } }));
      setCardStatus(cardId, {
        status: "done",
        resultMid: mid,
        trimIn: 0,
        trimOut: null,
        pendingTaskId: null,
        genStartedAt: null,
        ...detail.duration ? { actualDur: detail.duration } : {}
      });
    }, [setGenState, setCardStatus]);
    const onVideoError = useCallback((cardId, detail) => {
      setGenState((s) => ({ ...s, [cardId]: { phase: "error", msg: detail.error } }));
      setCardStatus(cardId, { status: "error", pendingTaskId: null, genStartedAt: null });
    }, [setGenState, setCardStatus]);
    const onVideoSlow = useCallback((cardId, detail) => {
      setGenState((s) => ({ ...s, [cardId]: {
        phase: detail.tier,
        msg: detail.tier === "stale" ? "Still going after " + elapsedLabel(detail.elapsed) + " \u2014 unusual. Check pixai.art, or keep waiting (task " + String(detail.task_id).slice(-6) + ")" : "Taking longer than expected (" + elapsedLabel(detail.elapsed) + ", task " + String(detail.task_id).slice(-6) + ")"
      } }));
    }, [setGenState]);
    const onVideoPaused = useCallback((cardId, detail) => {
      setGenState((s) => ({ ...s, [cardId]: {
        phase: "paused",
        msg: "Paused auto-checking with no result \u2014 click to check again, or check pixai.art (task " + String(detail.task_id).slice(-6) + ")"
      } }));
    }, [setGenState]);
    useEffect(() => {
      const clearDraft = (s) => {
        if (!("__draft__" in s)) return s;
        const n = { ...s };
        delete n.__draft__;
        return n;
      };
      setGenState(clearDraft);
      setGenImgState(clearDraft);
      setGenEditState(clearDraft);
      setGenRefState(clearDraft);
    }, [activeId]);
    const {
      seq,
      exp,
      playSequence,
      exportCut,
      cancelExport,
      closeExport,
      closeSequence,
      exportAll,
      exportJSON,
      exportBundle,
      bundling
    } = useExportPipeline(project, thumbs);
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
    const setLook = (v) => setProject((p) => ({ ...p, look: v }));
    const setDraft = (v) => setProject((p) => ({ ...p, draft: v }));
    if (!project) return /* @__PURE__ */ React.createElement("div", { className: "sb-root" }, /* @__PURE__ */ React.createElement("style", null, STYLES), /* @__PURE__ */ React.createElement("div", { className: "sb-empty" }, "Loading the bay\u2026"));
    const entries = flat(project);
    const anyDone = entries.some((e) => e.c.resultMid);
    const { total, scale, over } = reelStats(entries, project.target);
    const done = entries.filter((x) => x.c.status === "done").length;
    return /* @__PURE__ */ React.createElement("div", { className: "sb-root" }, /* @__PURE__ */ React.createElement("style", null, STYLES), /* @__PURE__ */ React.createElement(V2Boundary, null, /* @__PURE__ */ React.createElement(
      LoomV2,
      {
        project,
        setCard,
        setAssets,
        entries,
        durOf,
        scale,
        selShot,
        setSelShot,
        useExistingVideo,
        genState,
        thumbs,
        openPick,
        storeThumb,
        setAct,
        addCard,
        importFootage,
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
        imgLoras,
        setImgLoras,
        imgAdv,
        setImgAdv,
        modelDefaults,
        setModelDefaults,
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
        playSequence,
        exportCut,
        batching,
        batchGenerate,
        batchTally,
        addRef,
        setRef,
        delRef,
        exportAll,
        exportJSON,
        exportBundle,
        bundling,
        importBackup,
        setImportOpen,
        copyShot,
        setLook,
        setDraft,
        splitShot,
        onVideoSubmit,
        onVideoResult,
        onVideoError,
        onVideoSlow,
        onVideoPaused,
        pollShot,
        costEstimate,
        refreshEstimate
      }
    )), seq && /* @__PURE__ */ React.createElement(SequencePlayer, { clips: seq, onClose: closeSequence }), exp && /* @__PURE__ */ React.createElement("div", { className: "sb-seq", onClick: (e) => {
      if (e.target === e.currentTarget && exp.status !== "running") closeExport();
    } }, /* @__PURE__ */ React.createElement("div", { className: "sb-export-box" }, /* @__PURE__ */ React.createElement("div", { className: "sb-pick-head" }, /* @__PURE__ */ React.createElement("span", { className: "sb-pick-t" }, "Export the cut"), exp.status !== "running" && /* @__PURE__ */ React.createElement("button", { className: "sb-pick-x", onClick: closeExport }, "\xD7")), exp.status === "running" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "sb-exp-bar" }, /* @__PURE__ */ React.createElement("i", { style: { width: (exp.progress || 0) + "%" } })), /* @__PURE__ */ React.createElement("div", { className: "sb-exp-txt" }, "Rendering\u2026 ", exp.progress || 0, "% \xB7 ", Math.round(exp.elapsed || 0), "s of cut"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", style: { alignSelf: "center" }, onClick: cancelExport }, "\u25A0 Stop")), exp.status === "done" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "sb-exp-txt", style: { color: "var(--green)" } }, "\u2713 Cut rendered."), /* @__PURE__ */ React.createElement("a", { className: "sb-btn amber", href: "/api/loom/export-file", style: { alignSelf: "center", textDecoration: "none" } }, "\u21E9 Download mp4"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", style: { alignSelf: "center" }, onClick: closeExport }, "Close")), (exp.status === "failed" || exp.status === "cancelled") && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "sb-exp-txt", style: { color: exp.status === "failed" ? "var(--coral)" : "var(--ink2)" } }, exp.status === "failed" ? "\u26A0 " + (exp.error || "export failed") : "\u25A0 Export stopped."), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", style: { alignSelf: "center" }, onClick: closeExport }, "Close")))), pickCb && (pickAllowType ? /* @__PURE__ */ React.createElement("mg-gallery-picker", { ref: bindGalleryPicker, "default-type": pickKind, "show-type": true }) : /* @__PURE__ */ React.createElement("mg-gallery-picker", { ref: bindGalleryPicker, "default-type": pickKind })), importOpen && /* @__PURE__ */ React.createElement(ImportCollection, { onClose: () => setImportOpen(false), onImport: importCollection }));
  }
  function ShotPreview({ mid, trimIn, trimOut, onTrim, onSplit, crop, onCrop }) {
    const vidRef = useRef(null), trackRef = useRef(null);
    const [dur, setDur] = useState(0);
    const [range, setRange] = useState({ in: trimIn || 0, out: trimOut });
    const [playing, setPlaying] = useState(false);
    const [cropping, setCropping] = useState(false);
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
      if (playing) {
        const v = vidRef.current;
        if (v) v.pause();
        setPlaying(false);
      }
      dragRef.current = which;
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    };
    const seek = (delta) => {
      const v = vidRef.current;
      if (!v || !dur) return;
      if (playing) {
        v.pause();
        setPlaying(false);
      }
      v.currentTime = Math.max(0, Math.min(dur, v.currentTime + delta));
    };
    const doSplit = () => {
      const v = vidRef.current;
      if (!v || !onSplit) return;
      const t = v.currentTime;
      if (t > range.in + 0.15 && t < effOut - 0.15) onSplit(t);
      else alert("Move the playhead to where you want the cut first (not at either edge).");
    };
    const cropRef = useRef(null);
    const [cropDraft, setCropDraft] = useState(null);
    const cropStart = (e) => {
      if (!cropping) return;
      e.preventDefault();
      e.stopPropagation();
      const box = e.currentTarget.getBoundingClientRect();
      const fx = (cx) => Math.max(0, Math.min(1, (cx - box.left) / box.width));
      const fy = (cy) => Math.max(0, Math.min(1, (cy - box.top) / box.height));
      const x0 = fx(e.clientX), y0 = fy(e.clientY);
      const move = (ev) => {
        const x1 = fx(ev.clientX), y1 = fy(ev.clientY);
        const r = { x: Math.min(x0, x1), y: Math.min(y0, y1), w: Math.abs(x1 - x0), h: Math.abs(y1 - y0) };
        cropRef.current = r;
        setCropDraft(r);
      };
      const up = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", up);
        const r = cropRef.current;
        if (r && r.w > 0.05 && r.h > 0.05 && onCrop) onCrop(r);
        cropRef.current = null;
        setCropDraft(null);
        setCropping(false);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    };
    const shownCrop = cropDraft || crop;
    const trimmed = range.in > 0 || range.out != null;
    return /* @__PURE__ */ React.createElement("div", { className: "sb-shotprev-wrap" }, /* @__PURE__ */ React.createElement(
      "div",
      {
        className: "sb-shotprev",
        onMouseMove: cropping ? void 0 : scrub,
        onMouseLeave: () => {
          if (playing || cropping) return;
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
      shownCrop && /* @__PURE__ */ React.createElement("div", { className: "sb-crop-rect", style: {
        left: shownCrop.x * 100 + "%",
        top: shownCrop.y * 100 + "%",
        width: shownCrop.w * 100 + "%",
        height: shownCrop.h * 100 + "%"
      } }),
      cropping && /* @__PURE__ */ React.createElement("div", { className: "sb-crop-layer", onPointerDown: cropStart }, "drag to crop"),
      !cropping && /* @__PURE__ */ React.createElement("button", { className: "sb-shotprev-play", onClick: togglePlay, title: playing ? "Pause" : "Play" }, playing ? "\u23F8" : "\u25B6"),
      !cropping && /* @__PURE__ */ React.createElement("div", { className: "sb-shotprev-hint" }, "hover to scrub")
    ), /* @__PURE__ */ React.createElement("div", { className: "sb-shotprev-ctrls" }, /* @__PURE__ */ React.createElement("button", { onClick: () => seek(-0.25), title: "Rewind (step back)" }, "\u23EA"), /* @__PURE__ */ React.createElement("button", { onClick: () => seek(0.25), title: "Fast-forward (step ahead)" }, "\u23E9"), onSplit && /* @__PURE__ */ React.createElement("button", { onClick: doSplit, title: "Split this shot in two at the playhead" }, "\u2702 Split"), onCrop && /* @__PURE__ */ React.createElement(
      "button",
      {
        className: cropping ? "on" : "",
        onClick: () => {
          setCropping((v) => !v);
          setCropDraft(null);
        },
        title: "Crop the frame \u2014 drag a rectangle; applied on export"
      },
      "\u26F6 Crop"
    ), crop && onCrop && /* @__PURE__ */ React.createElement("button", { onClick: () => onCrop(null), title: "Clear crop" }, "clear crop")), /* @__PURE__ */ React.createElement("div", { className: "sb-trim" }, /* @__PURE__ */ React.createElement(
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
      const advance = () => {
        if (i < clips.length - 1) setI(i + 1);
        else onClose();
      };
      const onTime = () => {
        const end = (clip.out != null ? clip.out : v.duration) || 0;
        if (end && v.currentTime >= end - 0.04) advance();
      };
      v.addEventListener("loadedmetadata", seekPlay);
      v.addEventListener("timeupdate", onTime);
      v.addEventListener("ended", advance);
      if (v.readyState >= 1) seekPlay();
      return () => {
        v.removeEventListener("loadedmetadata", seekPlay);
        v.removeEventListener("timeupdate", onTime);
        v.removeEventListener("ended", advance);
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
  function FrameSlot({ which, frame, liveTag, discreet, framePrev, onPatch, storeThumb, openPick, extraBtn }) {
    const img = framePrev(frame);
    return /* @__PURE__ */ React.createElement("div", { className: "sb-frame" }, /* @__PURE__ */ React.createElement("div", { className: "sb-framehead" }, /* @__PURE__ */ React.createElement("span", { className: "sb-lab" }, which === "open" ? "Opening frame" : "Closing frame"), openPick && /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-ico",
        title: "Pick from the gallery",
        onClick: () => openPick((mid) => onPatch({ mediaId: mid, thumbId: "", source: "" }))
      },
      "\u25A4"
    ), /* @__PURE__ */ React.createElement("span", { className: "sb-tagin sb-mono", title: "This slot's live @imageN \u2014 computed from position, not editable" }, liveTag || "\u2014")), /* @__PURE__ */ React.createElement("label", { className: "sb-frameprev" + (discreet ? " discreet" : ""), title: "Attach image" }, img ? /* @__PURE__ */ React.createElement("img", { src: img, alt: which }) : "\uFF0B attach frame", /* @__PURE__ */ React.createElement(
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
  return __toCommonJS(master_storyboard_exports);
})();
