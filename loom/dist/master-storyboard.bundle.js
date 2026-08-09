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
  var imageClaim = (tag) => {
    const m = /^@image(\d+)$/.exec(tag || "");
    return m ? +m[1] : 0;
  };
  var isCatalogMediaId = (s) => /^(?:\d+|local_[0-9a-f]{12})$/.test(String(s == null ? "" : s));
  var frameLinked = (a, b) => !!a && !!b && (!!a.mediaId && !!b.mediaId && a.mediaId === b.mediaId || !!a.thumbId && !!b.thumbId && a.thumbId === b.thumbId);
  var continuityLinked = (entries, entryId) => {
    const idx = (entries || []).findIndex((x) => x.c.id === entryId);
    if (idx <= 0) return false;
    return frameLinked(entries[idx - 1].c.closeFrame, entries[idx].c.openFrame);
  };
  var connectMeta = (connect) => CONNECT[connect] || CONNECT.new;
  var flat = (p) => p.acts.flatMap((a, ai) => a.cards.map((c, ci) => ({ c, a, ai, ci, code: `${actLetter(ai)}\xB7${String(ci + 1).padStart(2, "0")}` })));
  var effectivePrompt = (c) => c.promptOverride ? c.promptOverrideText || "" : c.prompt || "";
  var resolvedImage = (x, resolve) => x && (x.mediaId || resolve(x.thumbId, x.source)) || null;
  var CLOSE_FRAME_MODES = ["FLF", "R2V", "V2V"];
  var usesCloseFrame = (mode) => CLOSE_FRAME_MODES.includes(mode);
  var shotImageRefs = (entry, project, imgSrc) => {
    const c = entry.c;
    const items = [];
    (project.assets || []).filter((as) => as.kind === "image" && c.cast.includes(as.id)).forEach((as) => {
      const d = resolvedImage(as, imgSrc);
      if (d) items.push({ tag: as.tag, d, kind: "cast", id: as.id });
    });
    [["@image8", "openFrame", c.openFrame], ["@image9", "closeFrame", usesCloseFrame(c.mode) ? c.closeFrame : null]].forEach(([fallbackTag, key, f]) => {
      if (!f) return;
      const d = resolvedImage(f, imgSrc);
      if (d) items.push({ tag: f.tag || fallbackTag, d, kind: "frame", id: key });
    });
    (c.refs || []).filter((r) => r.kind === "image").forEach((r) => {
      const d = resolvedImage(r, imgSrc);
      if (d) items.push({ tag: r.tag, d, kind: "ref", id: r.id });
    });
    const kindRank = (it) => it.kind === "frame" ? 0 : it.kind === "cast" ? 1 : 2;
    const sortNum = (it) => it.kind === "cast" ? imageClaim(it.tag) || Number.MAX_SAFE_INTEGER : 0;
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
    const c = entry.c;
    const claims = new Set([
      ...(project.assets || []).filter((as) => (c.cast || []).includes(as.id)).map((as) => as.tag),
      (c.openFrame || {}).tag,
      (c.closeFrame || {}).tag,
      ...(c.refs || []).filter((r) => r.kind === "image").map((r) => r.tag)
    ].map(imageClaim).filter(Boolean));
    let n = items.length + 1;
    while (claims.has(n)) n++;
    return { type: "append", tag: "@image" + n };
  };
  var shotVideoRefs = (entry) => (entry.c.refs || []).filter((r) => r.kind === "video" && isCatalogMediaId(r.source));
  var pickVideoTarget = (entry, slot) => {
    const items = shotVideoRefs(entry);
    const existing = items[slot];
    if (existing) return { type: "replace", id: existing.id };
    const allVideoRefs = (entry.c.refs || []).filter((r) => r.kind === "video");
    return { type: "append", tag: nextTag(allVideoRefs, "@video") };
  };
  var castMissingImages = (entry, p, imgSrc) => {
    const resolve = imgSrc || noImgSrc;
    return (p.assets || []).filter((as) => (entry.c.cast || []).includes(as.id)).filter((as) => !(as.kind === "image" && resolvedImage(as, resolve))).map((as) => as.name || "(unnamed)");
  };
  var castPastBudget = (entry, p, imgSrc) => {
    const resolve = imgSrc || noImgSrc;
    return (p.assets || []).filter((as) => (entry.c.cast || []).includes(as.id)).filter((as) => as.kind === "image" && resolvedImage(as, resolve) && !positionTag(entry, p, resolve, as.id)).map((as) => as.name || "(unnamed)");
  };
  var refBudget = (entry, p, imgSrc) => {
    const resolve = imgSrc || noImgSrc;
    const c = entry.c;
    const frames = shotImageRefs(entry, p, resolve).filter((it) => it.kind === "frame").length;
    const used = (p.assets || []).filter((as) => as.kind === "image" && (c.cast || []).includes(as.id) && resolvedImage(as, resolve)).length + (c.refs || []).filter((r) => r.kind === "image" && resolvedImage(r, resolve)).length;
    return { used, budget: 6 - frames, frames };
  };
  var shotText = (entry, p, imgSrc) => {
    const { c, code, ai } = entry;
    if (c.promptOverride) return effectivePrompt(c);
    const resolve = imgSrc || noImgSrc;
    const idx = flat(p).findIndex((x) => x.c.id === c.id);
    const prev = idx > 0 ? flat(p)[idx - 1] : null;
    const L = [`[${code} \u2014 "${c.title || "untitled"}"]  (${c.mode}, ~${c.duration}s, ${connectMeta(c.connect).label})`, ""];
    if (c.connect === "extend" && prev) L.push(`Continue seamlessly from the previous clip ${prev.code} (upload it as @video1).`);
    if (c.mode === "FLF") {
      const openTag = positionTag(entry, p, resolve, "openFrame") || c.openFrame.tag;
      const closeTag = positionTag(entry, p, resolve, "closeFrame") || c.closeFrame.tag;
      if (c.openFrame.desc || openTag) L.push(`Opening frame ${openTag || "(first image)"}: ${c.openFrame.desc || "\u2014"}`);
      if (c.closeFrame.desc || closeTag) L.push(`Closing frame ${closeTag || "(last image)"}: ${c.closeFrame.desc || "\u2014"}`);
    }
    L.push("", c.prompt || "(prompt tbd)");
    if (c.connect === "extend" || c.connect === "flf") L.push(CONTINUITY_PHRASE);
    if (p.look) L.push("", `Look (consistent across the film): ${p.look}`);
    const usedCast = (p.assets || []).filter((as) => c.cast.includes(as.id)).map((as) => ({ as, tag: positionTag(entry, p, resolve, as.id) })).filter((x) => x.tag);
    if (usedCast.length) {
      L.push("", "Keep consistent:");
      usedCast.forEach(({ as, tag }) => {
        L.push(`  ${as.name} \u2014 ${as.lock ? "maintain exact appearance from " : "reference "}${tag}`);
      });
    }
    const usedRefs = (c.refs || []).map((r) => ({ r, tag: positionTag(entry, p, resolve, r.id) || (r.kind === "image" ? null : r.tag) })).filter((x) => x.tag);
    if (usedRefs.length) {
      L.push("", "Other references:");
      usedRefs.forEach(({ r, tag }) => {
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
    const vids = (c.refs || []).filter((r) => r.kind === "video" && isCatalogMediaId(r.source)).map((r) => r.source).slice(0, 3);
    return {
      mode: c.mode,
      prompt: shotText(entry, project, imgSrc),
      images: imgs.map((x) => x.d),
      video_refs: vids,
      duration: c.duration,
      quality: project.draft ? "basic" : "professional",
      generate_audio: !!c.audioGen,
      audio_language: c.audioLanguage || "english",
      // The Channel (Normal/Enhanced) -- the SAME real field mg-generate-drawer's own
      // channel select has always submitted (is_private: enhanced), and the server's
      // shared build_shot_video_params has accepted on this route all along; the Loom
      // client just never sent it (2026-08-06, owner correction -- an earlier audit
      // wrongly recorded "no channel field exists in the real backend contract").
      // Absent/false = Normal, matching the drawer's own default.
      is_private: !!c.isPrivate,
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
  var mediaRefIndex = (project) => {
    const ids = {};
    const note = (mid, where) => {
      const k = String(mid);
      (ids[k] = ids[k] || []).push(where);
    };
    ((project || {}).acts || []).forEach((act, ai) => {
      (act.cards || []).forEach((c, ci) => {
        const title = (c.title || "").trim();
        const code = `${actLetter(ai)}\xB7${String(ci + 1).padStart(2, "0")}${title ? ` ${title}` : ""}`;
        if (c.resultMid) note(c.resultMid, `${code} (shot result)`);
        ["openFrame", "closeFrame"].forEach((slot) => {
          const f = c[slot] || {};
          if (f.mediaId) note(f.mediaId, `${code} (${slot})`);
        });
      });
    });
    ((project || {}).assets || []).forEach((a) => {
      if (a.mediaId) note(a.mediaId, `cast/asset ${a.name || a.tag || a.id || "?"}`);
    });
    return ids;
  };
  var bundleMissingReport = (project, countHeader, listHeader) => {
    const total = Math.max(0, parseInt(countHeader || "0", 10) || 0);
    const index = mediaRefIndex(project);
    const rows = String(listHeader || "").split(",").map((s) => s.trim()).filter((s) => s && !/^\+\d+ more$/.test(s)).map((mid) => ({ mid, where: index[mid] || [] }));
    return { total, rows, hidden: Math.max(0, total - rows.length) };
  };

  // src/loom-mutations.js
  var patchCard = (project, actId, cardId, fn) => ({
    ...project,
    acts: project.acts.map((a) => a.id !== actId ? a : {
      ...a,
      cards: a.cards.map((c) => c.id !== cardId ? c : fn(c))
    })
  });
  var patchCardById = (project, cardId, patch2) => ({
    ...project,
    acts: project.acts.map((a) => ({
      ...a,
      cards: a.cards.map((c) => c.id !== cardId ? c : { ...c, ...patch2 })
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
  var importedFramesPatch = (firstMid, lastMid) => {
    const frame = (mid, desc) => ({ thumbId: "", source: "", tag: "", desc, mediaId: String(mid) });
    const p = {};
    if (firstMid) p.openFrame = frame(firstMid, "first frame of the imported clip");
    if (lastMid) p.closeFrame = frame(lastMid, "last frame of the imported clip");
    return p;
  };
  var patchAct = (project, actId, patch2) => ({
    ...project,
    acts: project.acts.map((a) => a.id !== actId ? a : { ...a, ...patch2 })
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
  var patchRef = (project, actId, cardId, refId, patch2) => patchCard(project, actId, cardId, (c) => ({ ...c, refs: c.refs.map((r) => r.id !== refId ? r : { ...r, ...patch2 }) }));
  var removeRef = (project, actId, cardId, refId) => patchCard(project, actId, cardId, (c) => ({ ...c, refs: c.refs.filter((r) => r.id !== refId) }));
  var countShots = (project) => (project.acts || []).reduce((n, a) => n + (a.cards || []).length, 0);
  var parseCastIdsFromSearch = (search) => (search || "").replace(/^\?/, "").split("&").map((kv) => kv.split("=")).filter(([k]) => k === "cast").flatMap(([, v]) => (v || "").split(",")).map((s) => decodeURIComponent(s).trim()).filter((s) => /^[A-Za-z0-9_-]{1,64}$/.test(s));
  function friendlyGenErr(raw) {
    const s = String(raw || "");
    if (!s) return "generation failed";
    let hint = "";
    if (/insufficient|INSUFFICIENT_BALANCE|40300010/i.test(s))
      hint = "Out of balance for this model \u2014 no free card matched and credits are 0. Claim your daily rewards, or pick a card-covered model.";
    else if (/maxLength|too long|exceeds maximum/i.test(s))
      hint = "That prompt is too long for video \u2014 PixAI allows 2000 characters. Trim it and resubmit; nothing was created or charged.";
    else if (/image contains (sensitive|nsfw|prohibited)|NSFW_DETECTED|40300032/i.test(s))
      hint = "PixAI refused the SOURCE IMAGE on content grounds, not the prompt \u2014 rewriting the text will not help. Try a different frame.";
    else if (/moderat|content.?polic|flagged|nsfw/i.test(s) || /prohibit|sensitive|not.?allowed|violat/i.test(s) && /content|prompt|polic|guideline|term|image/i.test(s))
      hint = "PixAI's content filter blocked this generation \u2014 that's decided on PixAI's side, not here.";
    else if (/inferenceProfile|i2vPro[./]mode|unknown mode/i.test(s))
      hint = "That quality setting isn't available for this model \u2014 try a different Mode.";
    return hint ? hint + " (PixAI said: " + s.slice(0, 160) + ")" : s;
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
  function buildShotListText(project, fmt4, actLetter2, shotText2) {
    let out = `${project.name}
Runtime target ${fmt4(project.target)}
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
  function overLoraCap(loras, cap) {
    return cap != null && (loras || []).length > cap;
  }
  function snap8(n) {
    return Math.max(64, Math.min(4096, Math.round((Number(n) || 0) / 8) * 8));
  }
  function resolveGenDims({ aspectW, aspectH, size, customW, customH } = {}) {
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
    const dims = resolveGenDims({
      aspectW: a.aspectW,
      aspectH: a.aspectH,
      size: a.size,
      customW: a.customW,
      customH: a.customH
    });
    return {
      model_id: imgModel && imgModel.model_id || "",
      // picker-parity-round2 (problem 4): the CHOSEN version, when the owner picked one
      // other than the latest via the version selector -- '' (absent) when they haven't,
      // which /api/generate already treats as "resolve the newest" (unchanged fallback).
      version_id: imgModel && imgModel.version_id || "",
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

  // ../gallery/src/art/artFilters.js
  var MgArtFilters = (function() {
    "use strict";
    var SOURCE_URL = "https://api.pixai.art/config/imageArtFilters";
    var CAPTURED = "2026-07-25";
    var DEFAULT_ANGLE_DEG = 180;
    var FILTERS = [
      {
        id: "filter-v1-m1",
        version: 1,
        name: "Filter M1",
        filters: [
          {
            name: "f1",
            enabled: true,
            blendMode: "darker-color",
            blendOpacity: 0.9,
            stops: [
              { color: "rgba(215, 255, 223, 1)", position: 1 },
              { color: "#ffffff", position: 0 }
            ]
          },
          {
            name: "f2",
            enabled: true,
            blendMode: "soft-light",
            blendOpacity: 0.7,
            stops: [
              { color: "rgba(179, 250, 255, 1)", position: 0 },
              { color: "rgba(117, 48, 227, 1)", position: 1 }
            ]
          }
        ]
      },
      {
        id: "filter-v1-m2",
        version: 1,
        name: "Filter M2",
        filters: [
          {
            name: "f1",
            enabled: true,
            blendMode: "darker-color",
            blendOpacity: 0.45,
            stops: [
              { color: "rgba(95, 78, 197, 1)", position: 0 },
              { color: "rgba(255, 249, 210, 1)", position: 1 }
            ]
          },
          {
            name: "f2",
            enabled: true,
            blendMode: "color-burn",
            blendOpacity: 0.7,
            stops: [
              { color: "rgba(255, 181, 0, 1)", position: 0 },
              { color: "rgba(255, 128, 213, 1)", position: 1 }
            ]
          },
          {
            name: "f3",
            enabled: true,
            blendMode: "lighter-color",
            blendOpacity: 0.4,
            stops: [
              { color: "rgba(163, 196, 223, 1)", position: 1 },
              { color: "rgba(111, 145, 186, 1)", position: 0 }
            ]
          }
        ]
      },
      {
        id: "filter-v1-m3",
        version: 1,
        name: "Filter M3",
        filters: [
          {
            name: "f1",
            enabled: true,
            blendMode: "plus-lighter",
            blendOpacity: 0.39,
            stops: [
              { color: "rgba(0, 238, 236, 1)", position: 0 },
              { color: "rgba(255, 203, 221, 1)", position: 1 }
            ]
          },
          {
            name: "f2",
            enabled: true,
            blendMode: "saturation",
            blendOpacity: 0.43,
            stops: [
              { color: "rgba(68, 47, 93, 1)", position: 0 },
              { color: "rgba(244, 157, 173, 1)", position: 1 }
            ]
          }
        ]
      },
      {
        id: "filter-v1-m4",
        version: 1,
        name: "Filter M4",
        filters: [
          {
            name: "f1",
            enabled: true,
            blendMode: "soft-light",
            blendOpacity: 0.54,
            stops: [
              { color: "rgba(255, 194, 161, 1)", position: 0 },
              { color: "rgba(255, 177, 189, 1)", position: 1 }
            ]
          },
          {
            name: "f2",
            enabled: true,
            blendMode: "color-burn",
            blendOpacity: 0.85,
            stops: [
              { color: "rgba(215, 214, 77, 1)", position: 0 },
              { color: "rgba(254, 169, 191, 1)", position: 0.5 },
              { color: "rgba(206, 255, 186, 1)", position: 1 }
            ]
          }
        ],
        image_parameters: { brightness: 0.04, contrast: 0.05, saturation: 0.1 }
      },
      {
        id: "filter-v1-m5",
        version: 1,
        name: "Filter M5",
        filters: [
          {
            name: "f1",
            enabled: true,
            blendMode: "darker-color",
            blendOpacity: 0.22,
            stops: [
              { color: "rgba(255, 204, 206, 1)", position: 0 },
              { color: "rgba(255, 218, 123, 1)", position: 1 }
            ]
          },
          {
            name: "f2",
            enabled: true,
            blendMode: "soft-light",
            blendOpacity: 0.9,
            stops: [
              { color: "rgba(255, 154, 173, 1)", position: 0 },
              { color: "rgba(255, 238, 255, 1)", position: 1 }
            ]
          }
        ],
        image_parameters: { brightness: 0.02, contrast: -0.26, saturation: 0.02 }
      },
      {
        id: "filter-v1-m6",
        version: 1,
        name: "Filter M6",
        filters: [
          {
            name: "f1",
            enabled: true,
            blendMode: "lighter-color",
            blendOpacity: 0.4,
            stops: [
              { color: "#f4e4c1", position: 1 },
              { color: "rgba(234, 118, 88, 1)", position: 0.6 },
              { color: "rgba(0, 17, 49, 1)", position: 1 }
            ]
          },
          {
            name: "f2",
            enabled: true,
            blendMode: "screen",
            blendOpacity: 0.16,
            stops: [
              { color: "rgba(250, 243, 98, 1)", position: 0 },
              { color: "rgba(235, 41, 171, 1)", position: 0.6 },
              { color: "rgba(0, 17, 49, 1)", position: 1 }
            ]
          }
        ],
        image_parameters: { brightness: 0, contrast: 0, saturation: 0.12 }
      },
      {
        id: "filter-v1-m7",
        version: 1,
        name: "Filter M7",
        filters: [
          {
            name: "f1",
            enabled: true,
            blendMode: "overlay",
            blendOpacity: 0.81,
            stops: [
              { color: "rgba(179, 250, 255, 1)", position: 0 },
              { color: "rgba(117, 48, 227, 1)", position: 1 }
            ]
          },
          {
            name: "f2",
            enabled: true,
            blendMode: "soft-light",
            blendOpacity: 0.4,
            stops: [
              { color: "rgba(150, 197, 255, 1)", position: 0 },
              { color: "#ffffff", position: 1 }
            ]
          }
        ],
        image_parameters: { brightness: 0.02, contrast: -0.06, saturation: 0 }
      }
    ];
    var MOONGLADE_FILTERS = [
      {
        id: "mg-moonglade",
        version: 1,
        name: "Moonglade",
        skin: "moonglade",
        note: "The default skin. Lavender leads, emerald in the shadows.",
        filters: [
          {
            name: "f1",
            enabled: true,
            blendMode: "soft-light",
            blendOpacity: 0.6,
            stops: [
              { color: "#b692e6", position: 0 },
              { color: "#4fc99a", position: 1 }
            ]
          },
          {
            name: "f2",
            enabled: true,
            blendMode: "screen",
            blendOpacity: 0.2,
            stops: [
              { color: "#0c0a1c", position: 0 },
              { color: "#3a3460", position: 1 }
            ]
          }
        ]
      },
      {
        id: "mg-nightfallen",
        version: 1,
        name: "Nightfallen",
        skin: "nightfallen",
        note: "Void-touched. Crushes the darks, keeps a violet bloom up top.",
        filters: [
          {
            name: "f1",
            enabled: true,
            blendMode: "color-burn",
            blendOpacity: 0.42,
            stops: [
              { color: "#241a3f", position: 0 },
              { color: "#a678f0", position: 1 }
            ]
          },
          {
            name: "f2",
            enabled: true,
            blendMode: "soft-light",
            blendOpacity: 0.55,
            stops: [
              { color: "#c9a6ff", position: 0 },
              { color: "#080610", position: 1 }
            ]
          }
        ]
      },
      {
        id: "mg-moonlit",
        version: 1,
        name: "Moonlit Silver",
        skin: "moonlit",
        note: "Cold silver and glacier blue. The gentlest of the five -- good on portraits.",
        filters: [
          {
            name: "f1",
            enabled: true,
            blendMode: "soft-light",
            blendOpacity: 0.6,
            stops: [
              { color: "#bcd6f5", position: 0 },
              { color: "#8fb8e8", position: 1 }
            ]
          },
          {
            name: "f2",
            enabled: true,
            blendMode: "screen",
            blendOpacity: 0.18,
            stops: [
              { color: "#0b1018", position: 0 },
              { color: "#334358", position: 1 }
            ]
          }
        ]
      },
      {
        id: "mg-ember",
        version: 1,
        name: "Embercourt",
        skin: "ember",
        note: "Warm venthyr gold. The only one of the five that pushes contrast up.",
        filters: [
          {
            name: "f1",
            enabled: true,
            blendMode: "overlay",
            blendOpacity: 0.48,
            stops: [
              { color: "#e8935f", position: 0 },
              { color: "#f0b48f", position: 1 }
            ]
          },
          {
            name: "f2",
            enabled: true,
            blendMode: "color-burn",
            blendOpacity: 0.32,
            stops: [
              { color: "#5a352c", position: 0 },
              { color: "#160c0c", position: 1 }
            ]
          }
        ]
      },
      {
        id: "mg-verdant",
        version: 1,
        name: "Verdant Grove",
        skin: "verdant",
        note: "Deep moss. The strongest colour shift of the set.",
        filters: [
          {
            name: "f1",
            enabled: true,
            blendMode: "soft-light",
            blendOpacity: 0.6,
            stops: [
              { color: "#8fe8bf", position: 0 },
              { color: "#5fd39a", position: 1 }
            ]
          },
          {
            name: "f2",
            enabled: true,
            blendMode: "color-burn",
            blendOpacity: 0.38,
            stops: [
              { color: "#173026", position: 0 },
              { color: "#2a5140", position: 1 }
            ]
          }
        ]
      }
    ];
    var GROUPS = [
      { source: "moonglade", label: "Moonglade", filters: MOONGLADE_FILTERS },
      { source: "pixai", label: "PixAI", filters: FILTERS }
    ];
    var ALL_FILTERS = GROUPS.reduce(function(acc, g) {
      return acc.concat(g.filters);
    }, []);
    var BLEND_MODE_MAP = {
      "darker-color": {
        css: "darken",
        canvas: "darken",
        exact: false,
        note: "Photoshop's Darker Color keeps whichever whole colour is darker; CSS/canvas darken takes the per-channel minimum, which can emit a colour present in neither input. Closest available -- differs where a gradient crosses the hue."
      },
      "lighter-color": {
        css: "lighten",
        canvas: "lighten",
        exact: false,
        note: "Photoshop's Lighter Color keeps whichever whole colour is lighter; CSS/canvas lighten takes the per-channel maximum. Same approximation as darker-color."
      },
      "soft-light": { css: "soft-light", canvas: "soft-light", exact: true },
      "color-burn": { css: "color-burn", canvas: "color-burn", exact: true },
      "screen": { css: "screen", canvas: "screen", exact: true },
      "overlay": { css: "overlay", canvas: "overlay", exact: true },
      "saturation": { css: "saturation", canvas: "saturation", exact: true },
      "plus-lighter": {
        css: "plus-lighter",
        canvas: "lighter",
        exact: true,
        note: "Same additive (Porter-Duff 'plus') operator in both, only the spelling differs: canvas has no 'plus-lighter', it calls it 'lighter'."
      }
    };
    function blendModeFor(mode, target) {
      if (target !== "css" && target !== "canvas") {
        throw new Error("mg-art-filters: blendModeFor target must be 'css' or 'canvas', got " + JSON.stringify(target));
      }
      var e = BLEND_MODE_MAP[mode];
      return e ? e[target] : null;
    }
    var SAFE_COLOR = /^(#[0-9a-fA-F]{3,8}|rgba?\(\s*[\d.,%\s]+\s*\))$/;
    function clamp01(n) {
      return n < 0 ? 0 : n > 1 ? 1 : n;
    }
    function round4(n) {
      return Math.round(n * 1e4) / 1e4;
    }
    function num(n) {
      return String(round4(n));
    }
    function get(id) {
      for (var i = 0; i < ALL_FILTERS.length; i++)
        if (ALL_FILTERS[i].id === id) return ALL_FILTERS[i];
      return null;
    }
    function list() {
      return ALL_FILTERS.map(function(f) {
        return f.id;
      });
    }
    function groups() {
      return GROUPS.map(function(g) {
        return {
          source: g.source,
          label: g.label,
          ids: g.filters.map(function(f) {
            return f.id;
          })
        };
      });
    }
    function resolve(idOrRecipe) {
      if (idOrRecipe && typeof idOrRecipe === "object") return idOrRecipe;
      var r = get(idOrRecipe);
      if (!r) throw new Error("mg-art-filters: no such filter: " + idOrRecipe);
      return r;
    }
    function normalizeLayers(idOrRecipe, opts) {
      var recipe = resolve(idOrRecipe);
      var o = opts || {};
      var strength = o.strength == null ? 1 : Number(o.strength);
      if (!isFinite(strength)) strength = 1;
      var warnings = [];
      var layers = [];
      (recipe.filters || []).forEach(function(L) {
        if (L.enabled === false) return;
        var css = blendModeFor(L.blendMode, "css");
        var canvas = blendModeFor(L.blendMode, "canvas");
        if (!css || !canvas) {
          warnings.push('dropped layer "' + (L.name || "?") + '" of ' + recipe.id + ': unmapped blend mode "' + L.blendMode + '"');
          return;
        }
        var stops = (L.stops || []).filter(function(s) {
          if (s && typeof s.color === "string" && SAFE_COLOR.test(s.color)) return true;
          warnings.push('dropped an unrecognised stop colour in "' + (L.name || "?") + '" of ' + recipe.id + ": " + JSON.stringify(s && s.color));
          return false;
        }).map(function(s, i) {
          return { color: s.color, position: clamp01(Number(s.position) || 0), _i: i };
        });
        stops.sort(function(a, b) {
          return a.position - b.position || a._i - b._i;
        });
        stops.forEach(function(s) {
          delete s._i;
        });
        layers.push({
          name: L.name || "",
          blendMode: L.blendMode,
          css,
          canvas,
          opacity: round4(clamp01(Number(L.blendOpacity) * strength)),
          stops
        });
      });
      return { id: recipe.id, layers, warnings };
    }
    function gradientCss(layer, angle) {
      var a = angle == null ? DEFAULT_ANGLE_DEG : angle;
      var parts = layer.stops.map(function(s) {
        return s.color + " " + num(s.position * 100) + "%";
      });
      return "linear-gradient(" + num(a) + "deg, " + parts.join(", ") + ")";
    }
    function gradientEndpoints(w, h, angle) {
      var a = angle == null ? DEFAULT_ANGLE_DEG : angle;
      var t = axisTrig(a);
      var dx = t.s, dy = -t.c;
      var len = Math.abs(w * t.s) + Math.abs(h * t.c);
      var cx = w / 2, cy = h / 2, half = len / 2;
      return { x0: cx - dx * half, y0: cy - dy * half, x1: cx + dx * half, y1: cy + dy * half };
    }
    function axisTrig(deg) {
      var r = (Number(deg) % 360 + 360) % 360;
      if (r === 0) return { s: 0, c: 1 };
      if (r === 90) return { s: 1, c: 0 };
      if (r === 180) return { s: 0, c: -1 };
      if (r === 270) return { s: -1, c: 0 };
      var rad = r * Math.PI / 180;
      return { s: Math.sin(rad), c: Math.cos(rad) };
    }
    function imageAdjustCss(idOrRecipe) {
      var p = resolve(idOrRecipe).image_parameters;
      if (!p) return "";
      var out = [];
      if (p.brightness) out.push("brightness(" + num(1 + p.brightness) + ")");
      if (p.contrast) out.push("contrast(" + num(1 + p.contrast) + ")");
      if (p.saturation) out.push("saturate(" + num(1 + p.saturation) + ")");
      return out.join(" ");
    }
    function swatchLayers(idOrRecipe) {
      var layers = normalizeLayers(idOrRecipe).layers.map(function(L) {
        return {
          name: L.name,
          blendMode: L.blendMode,
          css: L.css,
          canvas: L.canvas,
          opacity: L.opacity,
          stops: L.stops
        };
      });
      if (layers.length) {
        layers[0] = Object.assign({}, layers[0], { css: "normal", canvas: "source-over", opacity: 1 });
      }
      return layers;
    }
    var STYLE_ID = "mg-art-filters-style";
    var CSS = [
      ".mgaf-stage,.mgaf-swatch{position:relative;isolation:isolate;}",
      ".mgaf-stage{display:inline-block;line-height:0;}",
      ".mgaf-stage>[data-mgaf-layer],.mgaf-swatch>[data-mgaf-layer]{position:absolute;",
      " inset:0;pointer-events:none;}",
      ".mgaf-swatch{display:block;overflow:hidden;}"
    ].join("");
    function injectStyle() {
      if (document.getElementById(STYLE_ID)) return;
      var s = document.createElement("style");
      s.id = STYLE_ID;
      s.textContent = CSS;
      (document.head || document.documentElement).appendChild(s);
    }
    function clearLayers(host) {
      var old = host.querySelectorAll(":scope > [data-mgaf-layer]");
      for (var i = 0; i < old.length; i++) old[i].parentNode.removeChild(old[i]);
    }
    function buildLayerDivs(host, layers, angle) {
      layers.forEach(function(L) {
        var d = document.createElement("div");
        d.setAttribute("data-mgaf-layer", L.name || "");
        d.style.backgroundImage = gradientCss(L, angle);
        d.style.mixBlendMode = L.css;
        d.style.opacity = String(L.opacity);
        host.appendChild(d);
      });
    }
    function renderSwatch(el, idOrRecipe, opts) {
      injectStyle();
      var o = opts || {};
      el.classList.add("mgaf-swatch");
      clearLayers(el);
      buildLayerDivs(el, swatchLayers(idOrRecipe), o.angle);
      return el;
    }
    function applyPreview(host, idOrRecipe, opts) {
      injectStyle();
      var o = opts || {};
      var n = normalizeLayers(idOrRecipe, o);
      var target = o.target || host.querySelector("img,canvas,video");
      host.classList.add("mgaf-stage");
      clearLayers(host);
      if (target) target.style.filter = imageAdjustCss(idOrRecipe);
      buildLayerDivs(host, n.layers, o.angle);
      return n;
    }
    function clearPreview(host, opts) {
      var o = opts || {};
      var target = o.target || host.querySelector("img,canvas,video");
      if (target) target.style.filter = "";
      clearLayers(host);
      host.classList.remove("mgaf-stage");
      return host;
    }
    function composite(source, idOrRecipe, opts) {
      var o = opts || {};
      var n = normalizeLayers(idOrRecipe, o);
      var w = o.width || source.naturalWidth || source.videoWidth || source.width;
      var h = o.height || source.naturalHeight || source.videoHeight || source.height;
      if (!w || !h) {
        throw new Error("mg-art-filters: source has no intrinsic size yet -- wait for the image's load event, or pass {width, height}");
      }
      var canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      var ctx = canvas.getContext("2d");
      var adjust = imageAdjustCss(idOrRecipe);
      if (adjust) {
        if ("filter" in ctx) ctx.filter = adjust;
        else n.warnings.push("this canvas has no ctx.filter -- skipped " + adjust);
      }
      ctx.drawImage(source, 0, 0, w, h);
      if ("filter" in ctx) ctx.filter = "none";
      var g = gradientEndpoints(w, h, o.angle);
      n.layers.forEach(function(L) {
        var grad = ctx.createLinearGradient(g.x0, g.y0, g.x1, g.y1);
        L.stops.forEach(function(s) {
          grad.addColorStop(s.position, s.color);
        });
        ctx.globalCompositeOperation = L.canvas;
        ctx.globalAlpha = L.opacity;
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);
      });
      ctx.globalCompositeOperation = "source-over";
      ctx.globalAlpha = 1;
      canvas.mgafWarnings = n.warnings;
      return canvas;
    }
    function toDataURL(source, idOrRecipe, opts) {
      var o = opts || {};
      return composite(source, idOrRecipe, o).toDataURL(o.mime || "image/png", o.quality);
    }
    function toBlob(source, idOrRecipe, opts) {
      var o = opts || {};
      var canvas = composite(source, idOrRecipe, o);
      return new Promise(function(resolve_, reject) {
        canvas.toBlob(function(b) {
          if (b) resolve_(b);
          else reject(new Error("mg-art-filters: canvas.toBlob produced nothing"));
        }, o.mime || "image/png", o.quality);
      });
    }
    return {
      SOURCE_URL,
      CAPTURED,
      DEFAULT_ANGLE_DEG,
      FILTERS,
      MOONGLADE_FILTERS,
      BLEND_MODE_MAP,
      list,
      get,
      groups,
      blendModeFor,
      normalizeLayers,
      gradientCss,
      gradientEndpoints,
      imageAdjustCss,
      swatchLayers,
      renderSwatch,
      applyPreview,
      clearPreview,
      composite,
      toDataURL,
      toBlob
    };
  })();
  var artFilters_default = MgArtFilters;

  // scripts/react-global-shim.js
  var React2 = window.React;
  var react_global_shim_default = React2;
  var useState = React2.useState;
  var useEffect = React2.useEffect;
  var useLayoutEffect = React2.useLayoutEffect;
  var useRef = React2.useRef;
  var useCallback = React2.useCallback;
  var useMemo = React2.useMemo;
  var useReducer = React2.useReducer;
  var useContext = React2.useContext;
  var useImperativeHandle = React2.useImperativeHandle;
  var useDebugValue = React2.useDebugValue;
  var useId = React2.useId;
  var useTransition = React2.useTransition;
  var useDeferredValue = React2.useDeferredValue;
  var useSyncExternalStore = React2.useSyncExternalStore;
  var useInsertionEffect = React2.useInsertionEffect;
  var createElement = React2.createElement;
  var cloneElement = React2.cloneElement;
  var createContext = React2.createContext;
  var forwardRef = React2.forwardRef;
  var memo = React2.memo;
  var lazy = React2.lazy;
  var Suspense = React2.Suspense;
  var Fragment = React2.Fragment;
  var StrictMode = React2.StrictMode;
  var Children = React2.Children;
  var isValidElement = React2.isValidElement;
  var createRef = React2.createRef;
  var Component = React2.Component;
  var PureComponent = React2.PureComponent;

  // ../gallery/src/picker/pickerCore.js
  var PickerCore = (function() {
    "use strict";
    function createPickerCore(opts) {
      opts = opts || {};
      var endpoint = opts.endpoint || "/api/gallery-images";
      var collectionsEndpoint = opts.collectionsEndpoint || "/api/collections";
      var pageSize = opts.pageSize || 60;
      var debounceMs = opts.debounceMs == null ? 280 : opts.debounceMs;
      var maxAutoFillPage = opts.maxAutoFillPage || 4;
      var onResults = opts.onResults || function() {
      };
      var onCollections = opts.onCollections || function() {
      };
      var onError = opts.onError || function() {
      };
      var filters = Object.assign({
        q: "",
        collection: "",
        source: "",
        type: "",
        rating_min: 0,
        sort: "newest"
      }, opts.defaultFilters || {});
      var page = 1, loading = false, hasMore = false, debounceTimer = null, destroyed = false;
      var loadSeq = 0;
      function qs(p) {
        var enc = encodeURIComponent;
        return endpoint + "?limit=" + pageSize + "&page=" + p + "&q=" + enc(filters.q || "") + "&collection=" + enc(filters.collection || "") + "&source=" + enc(filters.source || "") + "&type=" + enc(filters.type || "") + "&rating_min=" + enc(filters.rating_min || 0) + "&sort=" + enc(filters.sort || "newest");
      }
      function fetchCollections() {
        fetch(collectionsEndpoint).then(function(r) {
          return r.json();
        }).then(function(d) {
          if (!destroyed) onCollections(d.collections || []);
        }).catch(function(e) {
          onError(e);
        });
      }
      function load2(append) {
        if (loading && append) return;
        loading = true;
        var atPage = page;
        var mine = ++loadSeq;
        fetch(qs(atPage)).then(function(r) {
          return r.json();
        }).then(function(d) {
          if (mine !== loadSeq) return;
          loading = false;
          if (destroyed) return;
          var imgs = d.images || [];
          hasMore = (d.page || atPage) * (d.limit || pageSize) < (d.total || 0);
          onResults(imgs, { total: d.total || 0, append: !!append, hasMore, page: atPage });
        }).catch(function(e) {
          if (mine !== loadSeq) return;
          loading = false;
          onError(e);
        });
      }
      function reload() {
        page = 1;
        load2(false);
      }
      function setFilter(key, value) {
        filters[key] = value;
        page = 1;
        load2(false);
      }
      function setFilters(patch2) {
        Object.assign(filters, patch2 || {});
        page = 1;
        load2(false);
      }
      function setQuery(q, ms) {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(function() {
          filters.q = q;
          page = 1;
          load2(false);
        }, ms == null ? debounceMs : ms);
      }
      function loadMore() {
        if (hasMore && !loading) {
          page++;
          load2(true);
        }
      }
      function maybeFillPage(gridEl) {
        if (hasMore && !loading && page < maxAutoFillPage && gridEl && gridEl.scrollHeight <= gridEl.clientHeight + 4) {
          page++;
          load2(true);
        }
      }
      function onScroll(gridEl, thresholdPx) {
        if (!gridEl) return;
        var t = thresholdPx == null ? 320 : thresholdPx;
        if (hasMore && !loading && gridEl.scrollTop + gridEl.clientHeight > gridEl.scrollHeight - t) {
          loadMore();
        }
      }
      function destroy() {
        destroyed = true;
        clearTimeout(debounceTimer);
      }
      return {
        setQuery,
        setFilter,
        setFilters,
        reload,
        loadMore,
        maybeFillPage,
        onScroll,
        fetchCollections,
        destroy,
        getFilters: function() {
          return Object.assign({}, filters);
        },
        getPage: function() {
          return page;
        },
        hasMore: function() {
          return hasMore;
        }
      };
    }
    return { create: createPickerCore };
  })();
  var pickerCore_default = PickerCore;

  // ../gallery/src/components/GalleryPicker.jsx
  var COPY_KEY = "pick-copyprompt";
  var TILE_KEY = "mg-pk-tile";
  function readTile() {
    try {
      return +localStorage.getItem(TILE_KEY) || 122;
    } catch {
      return 122;
    }
  }
  function readCopy() {
    try {
      return localStorage.getItem(COPY_KEY) === "1";
    } catch {
      return false;
    }
  }
  function GalleryPicker({
    defaultType = "image",
    showType = false,
    showSource = false,
    showUpload = false,
    showCopyPrompt = false,
    sheet = false,
    onPick,
    onClose
  }) {
    const initType = defaultType === "video" ? "video" : defaultType === "all" ? "all" : "image";
    const [images, setImages] = useState([]);
    const [collections, setCollections] = useState([]);
    const [total, setTotal] = useState(0);
    const [empty, setEmpty] = useState(false);
    const [closing, setClosing] = useState(false);
    const [uploadMsg, setUploadMsg] = useState(null);
    const [type, setType] = useState(initType);
    const [collection, setCollection] = useState("");
    const [source, setSource] = useState("");
    const [rating, setRating] = useState(0);
    const [sort, setSort] = useState("newest");
    const [q, setQ] = useState("");
    const [tile, setTile] = useState(readTile);
    const [copyOn, setCopyOn] = useState(readCopy);
    const coreRef = useRef(null);
    const gridRef = useRef(null);
    const qRef = useRef(null);
    const fileRef = useRef(null);
    const debounceRef = useRef(null);
    const closingRef = useRef(false);
    const fRef = useRef();
    fRef.current = { q, collection, type, source, rating_min: rating, sort };
    useEffect(() => {
      const core = pickerCore_default.create({
        defaultFilters: { type: initType, collection: "", source: "", rating_min: 0, sort: "newest" },
        onResults: (imgs, meta) => {
          setTotal(meta.total || 0);
          if (meta.append) {
            setImages((old) => old.concat(imgs));
          } else {
            setUploadMsg(null);
            setImages(imgs);
            setEmpty(!imgs.length);
          }
        },
        onCollections: (colls) => setCollections(colls || []),
        onError: () => {
        }
      });
      coreRef.current = core;
      core.fetchCollections();
      core.setFilters({ q: "", collection: "", type: initType, source: "", rating_min: 0, sort: "newest" });
      const t = setTimeout(() => qRef.current && qRef.current.focus(), 60);
      return () => {
        clearTimeout(t);
        core.destroy();
      };
    }, []);
    useEffect(() => {
      if (coreRef.current) coreRef.current.maybeFillPage(gridRef.current);
    }, [images]);
    useEffect(() => {
      try {
        localStorage.setItem(TILE_KEY, String(tile));
      } catch {
      }
    }, [tile]);
    const schedule2 = useCallback(() => {
      clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => {
        if (coreRef.current) coreRef.current.setFilters(fRef.current);
      }, 160);
    }, []);
    const toggleCopy = (checked) => {
      setCopyOn(checked);
      try {
        localStorage.setItem(COPY_KEY, checked ? "1" : "0");
      } catch {
      }
    };
    const doClose = useCallback(() => {
      if (closingRef.current) return;
      closingRef.current = true;
      setClosing(true);
      setTimeout(() => onClose && onClose(), 340);
    }, [onClose]);
    useEffect(() => {
      const onKey = (e) => {
        if (e.key === "Escape") doClose();
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [doClose]);
    const pick = (m) => {
      if (copyOn && m.prompt) {
        try {
          navigator.clipboard && navigator.clipboard.writeText(m.prompt);
        } catch {
        }
      }
      onPick && onPick({
        media_id: m.media_id,
        thumb: m.thumb,
        prompt: m.prompt || "",
        is_video: m.is_video === "1",
        duration: m.duration || "",
        is_nsfw: m.is_nsfw === "1"
      });
    };
    const doUpload = () => {
      const f = fileRef.current && fileRef.current.files[0];
      if (!f) return;
      setUploadMsg("Uploading " + f.name + "\u2026");
      const fd = new FormData();
      fd.append("file", f);
      fetch("/api/upload", { method: "POST", body: fd }).then((r) => r.json()).then((d) => {
        if (fileRef.current) fileRef.current.value = "";
        if (d.error || !d.media_id) {
          setUploadMsg("\u26A0 Upload failed: " + (d.error || "no media id"));
          return;
        }
        setUploadMsg(null);
        pick({ media_id: d.media_id, prompt: "", thumb: URL.createObjectURL(f) });
      }).catch(() => {
        if (fileRef.current) fileRef.current.value = "";
        setUploadMsg("\u26A0 Upload failed (network).");
      });
    };
    const cls = "mg-gallery-picker" + (sheet ? " sheet" : "") + (closing ? " mg-closing" : "");
    return /* @__PURE__ */ react_global_shim_default.createElement(
      "div",
      {
        className: cls,
        style: { "--mg-pk-tile": tile + "px" },
        onClick: (e) => {
          if (e.target === e.currentTarget) doClose();
        }
      },
      /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-pk-box", role: "dialog", "aria-label": "Pick from your gallery" }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-pk-head" }, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mg-pk-t" }, "Pick from your gallery"), /* @__PURE__ */ react_global_shim_default.createElement(
        "input",
        {
          ref: qRef,
          className: "mg-pk-q",
          type: "text",
          placeholder: "Search your images\u2026",
          value: q,
          onChange: (e) => {
            setQ(e.target.value);
            schedule2();
          }
        }
      ), /* @__PURE__ */ react_global_shim_default.createElement(
        "button",
        {
          type: "button",
          className: "mg-pk-x",
          "data-tip": "Close (Esc)",
          "aria-label": "Close (Esc)",
          onClick: doClose
        },
        "\xD7"
      )), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-pk-filters" }, /* @__PURE__ */ react_global_shim_default.createElement(
        "select",
        {
          "data-f": "collection",
          value: collection,
          onChange: (e) => {
            setCollection(e.target.value);
            schedule2();
          }
        },
        /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "" }, "All collections"),
        collections.map((c) => /* @__PURE__ */ react_global_shim_default.createElement("option", { key: c, value: c }, c))
      ), showType && /* @__PURE__ */ react_global_shim_default.createElement("select", { "data-f": "type", value: type, onChange: (e) => {
        setType(e.target.value);
        schedule2();
      } }, /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "all" }, "Image + video"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "image" }, "Images"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "video" }, "Videos")), showSource && /* @__PURE__ */ react_global_shim_default.createElement("select", { "data-f": "source", value: source, onChange: (e) => {
        setSource(e.target.value);
        schedule2();
      } }, /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "" }, "Any source"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "api" }, "Generated (AI)"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "local" }, "Imported local")), /* @__PURE__ */ react_global_shim_default.createElement("select", { "data-f": "rating", value: rating, onChange: (e) => {
        setRating(+e.target.value);
        schedule2();
      } }, /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "0" }, "Any rating"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "1" }, "\u2605+"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "2" }, "\u2605\u2605+"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "3" }, "\u2605\u2605\u2605+"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "4" }, "\u2605\u2605\u2605\u2605+"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "5" }, "\u2605\u2605\u2605\u2605\u2605")), /* @__PURE__ */ react_global_shim_default.createElement("select", { "data-f": "sort", value: sort, onChange: (e) => {
        setSort(e.target.value);
        schedule2();
      } }, /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "newest" }, "Newest first"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "oldest" }, "Oldest first")), showUpload && /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, /* @__PURE__ */ react_global_shim_default.createElement(
        "button",
        {
          type: "button",
          className: "mg-pk-upload",
          onClick: () => fileRef.current && fileRef.current.click()
        },
        "\uFF0B Upload"
      ), /* @__PURE__ */ react_global_shim_default.createElement(
        "input",
        {
          ref: fileRef,
          type: "file",
          className: "mg-pk-file",
          accept: "image/*",
          style: { display: "none" },
          onChange: doUpload
        }
      )), /* @__PURE__ */ react_global_shim_default.createElement("label", { className: "mg-pk-sizer" }, "Size", /* @__PURE__ */ react_global_shim_default.createElement(
        "input",
        {
          type: "range",
          min: "90",
          max: "240",
          step: "8",
          title: "Thumbnail size",
          value: tile,
          onChange: (e) => setTile(+e.target.value)
        }
      )), /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mg-pk-count" }, (total || 0).toLocaleString())), showCopyPrompt && /* @__PURE__ */ react_global_shim_default.createElement("label", { className: "mg-pk-copy" }, /* @__PURE__ */ react_global_shim_default.createElement(
        "input",
        {
          type: "checkbox",
          className: "mg-pk-copyck",
          checked: copyOn,
          onChange: (e) => toggleCopy(e.target.checked)
        }
      ), " Copy prompt on pick"), /* @__PURE__ */ react_global_shim_default.createElement(
        "div",
        {
          className: "mg-pk-grid",
          ref: gridRef,
          onScroll: () => coreRef.current && coreRef.current.onScroll(gridRef.current, 280)
        },
        images.map((m, i) => /* @__PURE__ */ react_global_shim_default.createElement(
          "div",
          {
            key: m.media_id + ":" + i,
            className: "mg-pk-cell",
            title: m.prompt || m.media_id,
            "data-nsfw": m.is_nsfw === "1" ? "1" : void 0,
            onClick: () => pick(m)
          },
          /* @__PURE__ */ react_global_shim_default.createElement("img", { loading: "lazy", decoding: "async", src: m.thumb, alt: "" }),
          m.is_video === "1" && /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mg-pk-vid" }, "\u25B6")
        ))
      ), (empty || uploadMsg) && /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-pk-empty" }, uploadMsg || "No matches for these filters."))
    );
  }

  // ../gallery/src/components/ModelPicker.jsx
  function fmt(n) {
    return (Number(n) || 0).toLocaleString();
  }
  function fmtCompact(n) {
    n = Number(n) || 0;
    if (n >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
    return String(n);
  }
  function tyShort(t) {
    t = (t || "").toUpperCase();
    if (t.indexOf("LORA") >= 0) return "LoRA";
    if (t.indexOf("MMDIT") >= 0) return "MMDiT";
    if (t.indexOf("DIT") >= 0) return "DiT";
    if (t.indexOf("SDXL") >= 0) return "SDXL";
    if (t.indexOf("SD_V1") >= 0) return "SD1.5";
    if (t.indexOf("SD3") >= 0) return "SD3";
    if (t.indexOf("Z_IMAGE") >= 0) return "Z-Image";
    if (t.indexOf("CHAT") >= 0) return "Chat";
    return (t.split("_")[0] || "model").toLowerCase();
  }
  function baseLabel(cat) {
    cat = (cat || "").replace(/^uploaded-/, "").replace(/[-_]+/g, " ").trim();
    if (!cat) return "";
    if (/sdxl/i.test(cat)) return "SDXL";
    if (/sd3/i.test(cat)) return "SD3";
    if (/^sd ?v?1/i.test(cat)) return "SD1.5";
    if (/flux/i.test(cat)) return "Flux";
    if (/pony/i.test(cat)) return "Pony";
    if (/illustrious/i.test(cat)) return "Illustrious";
    return cat.replace(/\b\w/g, (c) => c.toUpperCase());
  }
  function archLabel(m, kind) {
    const b = baseLabel(m.base_model);
    if (b) return b;
    const t = m.lora_base_model_type || m.model_type || "";
    if (t) return tyShort(t);
    if (kind === "base" && m.type) return tyShort(m.type);
    return "";
  }
  var LORA_CATS = [
    ["", "All"],
    ["character", "Character"],
    ["animal", "Animal"],
    ["style", "Style"],
    ["realistic", "Realistic"],
    ["pose", "Pose"],
    ["clothing", "Clothing"],
    ["background", "Background"],
    ["detail", "Detail"],
    ["other", "Other"]
  ];
  var BASE_TYPES = [
    ["", "All"],
    ["MMDIT26B_MODEL", "DiT.3"],
    ["MMDIT26A_MODEL", "DiT.2"],
    ["DIT7_MODEL", "DiT.1"],
    ["USER_DIT26A_MODEL", "Community DiT"],
    ["SDXL_MODEL", "SDXL"],
    ["SD_V1_MODEL", "SD 1.5"]
  ];
  var SORTS = [["trending", "Trending"], ["liked", "Most Liked"], ["used", "Most Used"], ["newest", "Latest"]];
  function ModelPicker({
    kind = "base",
    multi = false,
    market = false,
    baseType = "",
    value = null,
    selected = [],
    onPick,
    onToggle,
    visible = true,
    style
  }) {
    const [q, setQ] = useState("");
    const [qDebounced, setQDebounced] = useState("");
    const [rows, setRows] = useState([]);
    const [err, setErr] = useState("");
    const [loadingMore, setLoadingMore] = useState(false);
    const [dim, setDim] = useState(false);
    const [src, setSrc] = useState("market");
    const [sort, setSort] = useState("trending");
    const [category, setCategory] = useState("");
    const [modelTypes, setModelTypes] = useState([]);
    const [source, setSource] = useState("");
    const [posted, setPosted] = useState("");
    const [license, setLicense] = useState("");
    const [preview, setPreview] = useState(null);
    const seqRef = useRef(0);
    const cursorRef = useRef("");
    const hasMoreRef = useRef(false);
    const loadingMoreRef = useRef(false);
    const gridRef = useRef(null);
    const lastKeyRef = useRef(null);
    const previewTimerRef = useRef(null);
    const scrollRafRef = useRef(null);
    const selectedRef = useRef(selected);
    selectedRef.current = selected;
    useEffect(() => {
      const t = setTimeout(() => setQDebounced(q), 250);
      return () => clearTimeout(t);
    }, [q]);
    const searchUrl = useCallback((cursor) => {
      let u = "/api/model-search?kind=" + encodeURIComponent(kind) + "&size=24&q=" + encodeURIComponent(qDebounced || "");
      if (market) {
        u += "&src=" + encodeURIComponent(src);
        if (src !== "bookmark") {
          u += "&sort=" + encodeURIComponent(sort) + "&category=" + encodeURIComponent(category) + "&posted=" + encodeURIComponent(posted) + "&source=" + encodeURIComponent(source) + "&license=" + encodeURIComponent(license);
          modelTypes.forEach((t) => {
            u += "&model_type=" + encodeURIComponent(t);
          });
        }
      }
      if (kind === "lora" && baseType) u += "&base_type=" + encodeURIComponent(baseType);
      if (cursor) u += "&cursor=" + encodeURIComponent(cursor);
      return u;
    }, [kind, qDebounced, market, src, sort, category, posted, source, license, modelTypes, baseType]);
    const doSearch = useCallback(() => {
      const mine = ++seqRef.current;
      cursorRef.current = "";
      hasMoreRef.current = false;
      setDim(true);
      fetch(searchUrl()).then((r) => r.json()).then((d) => {
        if (mine !== seqRef.current) return;
        hasMoreRef.current = !!(d && d.has_more);
        cursorRef.current = d && d.next_cursor || "";
        setErr(d && d.error ? d.error : "");
        setRows(d && d.results || []);
        setDim(false);
      }).catch(() => {
        if (mine !== seqRef.current) return;
        setErr("network error");
        setRows([]);
        setDim(false);
      });
    }, [searchUrl]);
    const loadMore = useCallback(() => {
      if (!hasMoreRef.current || loadingMoreRef.current) return;
      const mine = seqRef.current;
      loadingMoreRef.current = true;
      setLoadingMore(true);
      fetch(searchUrl(cursorRef.current)).then((r) => r.json()).then((d) => {
        loadingMoreRef.current = false;
        setLoadingMore(false);
        if (mine !== seqRef.current) return;
        if (d && d.error) return;
        hasMoreRef.current = !!(d && d.has_more);
        cursorRef.current = d && d.next_cursor || "";
        setRows((old) => old.concat(d && d.results || []));
      }).catch(() => {
        loadingMoreRef.current = false;
        setLoadingMore(false);
      });
    }, [searchUrl]);
    useEffect(() => {
      if (!visible) return;
      const key = searchUrl();
      if (key === lastKeyRef.current) return;
      lastKeyRef.current = key;
      doSearch();
    }, [visible, searchUrl, doSearch]);
    const onScroll = () => {
      if (scrollRafRef.current) return;
      scrollRafRef.current = requestAnimationFrame(() => {
        scrollRafRef.current = null;
        const g = gridRef.current;
        if (g && g.scrollHeight - g.scrollTop - g.clientHeight < 150) loadMore();
      });
    };
    const isSelected = useCallback((m) => multi ? selected.some((e) => e.model_id === m.model_id) : !!(value && value.model_id === m.model_id), [multi, selected, value]);
    const toggleMulti = (m) => {
      const cur = selectedRef.current;
      const at = cur.findIndex((e) => e.model_id === m.model_id);
      if (at >= 0) {
        onToggle && onToggle(cur[at], false);
        return;
      }
      const entry = {
        model_id: m.model_id,
        title: m.title,
        preview_url: m.preview_url,
        version_id: "",
        weight: 0.7,
        lora_base_type: "",
        trigger_words: "",
        failed: false
      };
      onToggle && onToggle(entry, true);
      fetch("/api/model-version?model_id=" + encodeURIComponent(m.model_id) + "&all=1").then((r) => r.json()).then((d) => {
        if (!selectedRef.current.some((e) => e.model_id === m.model_id)) return;
        const versions = d && d.versions || [], v = versions[0] || {};
        onToggle && onToggle({
          ...entry,
          version_id: v.version_id || "",
          lora_base_type: v.lora_base_model_type || "",
          trigger_words: v.trigger_words || "",
          versions,
          failed: !v.version_id
        }, true);
      }).catch(() => {
        if (!selectedRef.current.some((e) => e.model_id === m.model_id)) return;
        onToggle && onToggle({ ...entry, failed: true }, true);
      });
    };
    const pick = (m) => {
      hidePreview();
      if (multi) {
        toggleMulti(m);
        return;
      }
      onPick && onPick(m);
    };
    const showPreview = (m, anchorEl) => {
      const r = anchorEl.getBoundingClientRect(), w = 300, gap = 12;
      let x = r.right + gap;
      if (x + w > window.innerWidth - 8) x = Math.max(8, r.left - w - gap);
      const y = Math.max(8, Math.min(r.top - 10, window.innerHeight - 380));
      setPreview({ m, x, y });
    };
    const schedulePreview = (m, anchorEl) => {
      clearTimeout(previewTimerRef.current);
      previewTimerRef.current = setTimeout(() => showPreview(m, anchorEl), 130);
    };
    const hidePreview = () => {
      clearTimeout(previewTimerRef.current);
      setPreview(null);
    };
    useEffect(() => () => {
      clearTimeout(previewTimerRef.current);
      if (scrollRafRef.current) cancelAnimationFrame(scrollRafRef.current);
    }, []);
    const filtersHidden = market && src === "bookmark";
    const p = preview && preview.m;
    return /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "model-picker", style }, /* @__PURE__ */ react_global_shim_default.createElement(
      "input",
      {
        className: "mg-q",
        type: "text",
        placeholder: "Search",
        "aria-label": "Search models",
        value: q,
        onChange: (e) => setQ(e.target.value)
      }
    ), market && /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-mktsrc" }, [["market", "Market"], ["bookmark", "Bookmarked"], ...kind === "lora" ? [["mine", "Mine"]] : []].map(([v, label]) => /* @__PURE__ */ react_global_shim_default.createElement(
      "button",
      {
        type: "button",
        key: v,
        className: src === v ? "on" : "",
        "data-src": v,
        onClick: () => setSrc(v)
      },
      label
    ))), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-mktfilters", style: filtersHidden ? { display: "none" } : void 0 }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-mktsort" }, SORTS.map(([v, label]) => /* @__PURE__ */ react_global_shim_default.createElement(
      "button",
      {
        type: "button",
        key: v,
        className: sort === v ? "on" : "",
        "data-sort": v,
        onClick: () => setSort(v)
      },
      label
    ))), kind === "lora" ? /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-mktcats" }, LORA_CATS.map(([v, label]) => /* @__PURE__ */ react_global_shim_default.createElement(
      "button",
      {
        type: "button",
        key: v || "all",
        className: category === v ? "on" : "",
        "data-cat": v,
        onClick: () => setCategory(v)
      },
      label
    ))) : /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-mktcats mg-mkttypes" }, BASE_TYPES.map(([v, label]) => {
      const on = v ? modelTypes.includes(v) : !modelTypes.length;
      return /* @__PURE__ */ react_global_shim_default.createElement(
        "button",
        {
          type: "button",
          key: v || "all",
          className: on ? "on" : "",
          "data-mt": v,
          onClick: () => setModelTypes((old) => !v ? [] : old.includes(v) ? old.filter((x) => x !== v) : old.concat(v))
        },
        label
      );
    })), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-mktsel" }, /* @__PURE__ */ react_global_shim_default.createElement(
      "select",
      {
        className: "mg-posted" + (posted ? " on" : ""),
        "aria-label": "Posted at",
        value: posted,
        onChange: (e) => setPosted(e.target.value)
      },
      /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "" }, "Any time"),
      /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "yesterday" }, "Yesterday"),
      /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "7d" }, "Past 7 days"),
      /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "30d" }, "Past 30 days")
    ), kind === "lora" && /* @__PURE__ */ react_global_shim_default.createElement(
      "select",
      {
        className: "mg-source" + (source ? " on" : ""),
        "aria-label": "Source",
        value: source,
        onChange: (e) => setSource(e.target.value)
      },
      /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "" }, "Any source"),
      /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "pixai" }, "PixAI-trained"),
      /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "external" }, "External")
    ), /* @__PURE__ */ react_global_shim_default.createElement(
      "select",
      {
        className: "mg-license" + (license ? " on" : ""),
        "aria-label": "License",
        value: license,
        onChange: (e) => setLicense(e.target.value)
      },
      /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "" }, "Any licence"),
      /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "COMMERCIAL" }, "Commercial use OK")
    )))), err ? /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-empty", style: { display: "block" } }, "\u26A0 ", err) : !rows.length ? /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-empty", style: { display: "block" } }, "No results \u2014 try another search.") : /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-empty" }), /* @__PURE__ */ react_global_shim_default.createElement(
      "div",
      {
        className: "mg-grid",
        role: "listbox",
        ref: gridRef,
        onScroll,
        style: { opacity: dim ? 0.45 : 1 }
      },
      rows.map((m) => {
        const incompat = m.compat === "no";
        const arch = archLabel(m, kind);
        const sel = isSelected(m);
        let tip = m.description || m.title || "";
        if (incompat && arch) tip += (tip ? " " : "") + "Needs a " + arch + " base.";
        const cost = kind !== "lora" ? "" : incompat ? arch ? "needs " + arch : "" : (() => {
          const L = typeof window !== "undefined" ? window.MG_LORA : null;
          if (!L) return "";
          const r = L.ranges && L.ranges[(baseType || "").toUpperCase()] || L.fallback;
          if (!r || r.length < 2 || !isFinite(r[0]) || !isFinite(r[1])) return "";
          return "weight " + Number(r[0]).toFixed(2) + "\u2013" + Number(r[1]).toFixed(2);
        })();
        const clickable = !incompat || sel;
        return /* @__PURE__ */ react_global_shim_default.createElement(
          "div",
          {
            key: m.model_id,
            className: "mg-card" + (sel ? " sel" : "") + (incompat ? " incompat" : ""),
            "data-mid": m.model_id,
            title: tip || void 0,
            onClick: clickable ? () => pick(m) : void 0,
            onMouseEnter: (e) => schedulePreview(m, e.currentTarget),
            onMouseLeave: hidePreview
          },
          /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-cov" }, m.preview_url && /* @__PURE__ */ react_global_shim_default.createElement("img", { className: m.should_blur ? "blur" : void 0, loading: "lazy", src: m.preview_url, alt: "" }), m.official && /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mg-pill" }, "Official"), incompat && arch && /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mg-ibadge" }, "\u26A0 ", arch)),
          /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-meta" }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-nm" }, m.title), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-sub" }, arch && /* @__PURE__ */ react_global_shim_default.createElement("span", null, arch), /* @__PURE__ */ react_global_shim_default.createElement("span", null, fmtCompact(m.liked_count), " likes")), cost && /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-costline" }, cost))
        );
      })
    ), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mg-loadmore" + (loadingMore ? " on" : ""), "aria-hidden": "true" }, "loading more\u2026"), /* @__PURE__ */ react_global_shim_default.createElement(
      "div",
      {
        className: "mg-preview" + (p ? " open" : ""),
        "aria-hidden": p ? "false" : "true",
        style: p ? { left: preview.x, top: preview.y } : void 0
      },
      p && /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, (p.cover_url || p.preview_url) && /* @__PURE__ */ react_global_shim_default.createElement("img", { src: p.cover_url || p.preview_url, className: p.should_blur ? "blur" : void 0, alt: "" }), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mp-meta" }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mp-nm" }, p.title), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mp-sub" }, /* @__PURE__ */ react_global_shim_default.createElement("span", null, tyShort(p.type)), p.ref_count ? /* @__PURE__ */ react_global_shim_default.createElement("span", null, "\u25C8 ", fmtCompact(p.ref_count), " uses") : null, /* @__PURE__ */ react_global_shim_default.createElement("span", null, "\u2665 ", fmt(p.liked_count)), p.comment_count ? /* @__PURE__ */ react_global_shim_default.createElement("span", null, "\u{1F4AC} ", fmt(p.comment_count)) : null), (baseLabel(p.base_model) || p.official) && /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mp-badges" }, baseLabel(p.base_model) && /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "bdg base" }, baseLabel(p.base_model)), p.official && /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "bdg official", title: "In-house / official model" }, "\u2713 Official")), p.description && /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mp-desc" }, p.description)))
    ));
  }

  // ../gallery/src/components/CostBadge.jsx
  function fmt2(n) {
    return Number(n).toLocaleString();
  }
  var DEFAULT_HINT = "No cost yet \u2014 nothing to price.";
  var ERR_TEXT = "Couldn't verify the cost \u2014 generating may spend credits.";
  var ERR_TITLE = "Couldn't verify the cost or free-card coverage. Generating may spend credits.";
  function expiryNote(v) {
    if (v == null || v === "") return null;
    let t;
    if (typeof v === "number") t = v < 1e12 ? v * 1e3 : v;
    else t = Date.parse(String(v));
    if (!isFinite(t)) return null;
    const days = Math.ceil((t - Date.now()) / 864e5);
    const when = days < 0 ? "expired" : days === 0 ? "expires today" : days === 1 ? "expires tomorrow" : "expires in " + days + " days";
    return { text: when, title: new Date(t).toLocaleString(), days };
  }
  function classify(resp) {
    const d = resp && typeof resp === "object" ? resp : null;
    if (!d) return { state: "error", note: "", msg: "", raw: null };
    if (d.error) return { state: "error", note: "", msg: String(d.error), raw: d };
    if (d.free) return { state: "free", note: "", msg: "", raw: d };
    if (d.cost != null && isFinite(Number(d.cost))) return { state: "paid", note: "", msg: "", raw: d };
    if (d.note) return { state: "idle", note: String(d.note), msg: "", raw: d };
    return { state: "error", note: "", msg: "", raw: d };
  }
  function build(view, props) {
    const { state, note, msg, raw } = view;
    const d = raw || {};
    const warn = (props.warn || "").trim();
    const compact = !!props.compact;
    let main = "", sub = null, title = "", val = "", lab = "", tip = "", dot = false;
    if (state === "free") {
      const card = d.card_name || (props.cardLabel || "").trim() || "a free card";
      const leftN = d.cards != null && isFinite(Number(d.cards)) ? fmt2(d.cards) + " left" : "";
      const savesN = d.cost != null && isFinite(Number(d.cost)) ? fmt2(d.cost) : "";
      main = "\u{1F3AB} FREE \u2014 " + card + " covers this" + (leftN ? " (" + leftN + ")" : "") + (savesN ? " \xB7 saves ~" + savesN + " credits" : "");
      sub = expiryNote(d.card_expires);
      title = "A free card is applied automatically at submit \u2014 this generation spends 0 credits.";
      val = "FREE";
      lab = card + (leftN ? " \xB7 " + leftN : "");
      tip = title + (savesN ? " Saves ~" + savesN + " credits." : "");
      if (sub) {
        tip += " Card " + sub.text + " \u2014 " + sub.title + ".";
        dot = sub.days <= 7;
      }
    } else if (state === "paid") {
      const n = Number(d.cost);
      main = n === 0 ? "0 credits \u2014 this spends nothing" : (warn ? "\u26A0 " + warn + " \xB7 " : "") + "\u2248 " + fmt2(n) + " credits";
      title = n === 0 ? "Priced at zero credits. No free card was involved." : "No free card covers this \u2014 generating spends credits.";
      val = n === 0 ? "0" : (warn ? "\u26A0 " : "") + "\u2248 " + fmt2(n);
      lab = n === 0 ? "credits \u2014 spends nothing" : "credits";
      tip = n !== 0 && warn ? "\u26A0 " + warn + ". " + title : title;
    } else if (state === "error") {
      main = "\u26A0 " + (msg || ERR_TEXT);
      title = ERR_TITLE;
      tip = ERR_TITLE;
    } else if (state === "checking") {
      main = "Checking cost\u2026";
    } else {
      main = note || (props.hint || "").trim() || DEFAULT_HINT;
    }
    const text = main + (sub ? " \xB7 " + sub.text : "");
    return { state, warn, compact, main, sub, title, val, lab, tip, dot, text, d };
  }
  function detailOf(m) {
    const d = m.d || {};
    return {
      state: m.state,
      settled: m.state === "free" || m.state === "paid",
      cost: d.cost != null && isFinite(Number(d.cost)) ? Number(d.cost) : null,
      free: m.state === "free",
      cards: d.cards != null ? d.cards : null,
      card_name: d.card_name != null ? d.card_name : null,
      card_expires: d.card_expires != null ? d.card_expires : null,
      text: m.text,
      raw: m.raw
    };
  }
  var IDLE = { state: "idle", note: "", msg: "", raw: null };
  var CostBadge = forwardRef(function CostBadge2(props, ref) {
    const { hint, warn, compact, cardLabel, onCost, id, className, style } = props;
    const [view, setView] = useState(IDLE);
    const viewRef = useRef(view);
    const propsRef = useRef(props);
    const mRef = useRef(null);
    viewRef.current = view;
    propsRef.current = props;
    useImperativeHandle(ref, () => ({
      setPrice(resp) {
        setView(classify(resp));
      },
      clear(h) {
        setView({ state: "idle", note: h ? String(h) : "", msg: "", raw: null });
      },
      setChecking() {
        setView((v) => ({ ...v, state: "checking", msg: "" }));
      },
      get state() {
        return viewRef.current.state || "idle";
      },
      get settled() {
        return viewRef.current.state === "free" || viewRef.current.state === "paid";
      },
      get free() {
        return viewRef.current.state === "free";
      },
      get cost() {
        const c = viewRef.current.raw && viewRef.current.raw.cost;
        return c != null && isFinite(Number(c)) ? Number(c) : null;
      },
      get text() {
        return mRef.current ? mRef.current.text : "";
      },
      get price() {
        return viewRef.current.raw;
      },
      set price(v) {
        setView(classify(v));
      }
    }), []);
    const mounted = useRef(false);
    useEffect(() => {
      if (!mounted.current) {
        mounted.current = true;
        return;
      }
      if (typeof propsRef.current.onCost === "function") {
        propsRef.current.onCost(detailOf(build(viewRef.current, propsRef.current)));
      }
    }, [view]);
    const m = build(view, { hint, warn, compact, cardLabel });
    mRef.current = m;
    const dataWarn = m.state === "paid" && m.warn ? "1" : void 0;
    const nativeTitle = m.title && !(m.compact && m.tip) ? m.title : void 0;
    const showChip = m.compact && m.val;
    return /* @__PURE__ */ react_global_shim_default.createElement(
      "div",
      {
        id,
        className: "cost-badge" + (m.compact ? " compact" : "") + (className ? " " + className : ""),
        "data-state": m.state,
        "data-warn": dataWarn,
        role: "status",
        "aria-live": "polite",
        title: nativeTitle,
        style
      },
      showChip ? /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgc-val" }, m.val), /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgc-div" }), /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgc-lab" }, m.lab), m.sub ? /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgc-sub" }, m.sub.text) : null, m.dot ? /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgc-dot", "aria-hidden": "true" }, "!") : null) : m.state === "checking" ? /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgc-pip" }), "Checking cost\u2026") : /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, m.main, m.sub ? /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgc-sub", title: m.sub.title }, m.sub.text) : null),
      m.compact && m.tip ? /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgc-tip", "aria-hidden": "true" }, m.tip) : null
    );
  });
  var CostBadge_default = CostBadge;

  // ../gallery/src/gen/videoDrawerCore.js
  var MODELS = [
    { value: "v4.0", label: "V4.0 Preview", caps: ["multi-ref", "audio", "15s", "top quality", "~2.5\xD7 cost"] },
    { value: "v4.0.1", label: "V4.0 Lite Preview", caps: ["multi-ref", "audio", "15s", "end-frame"] },
    { value: "v3.2", label: "V3.2", caps: ["audio", "prompt-following"] },
    { value: "v3.0.2", label: "V3.0 Lite", caps: ["complex motion", "cheap"] },
    { value: "v3.0", label: "V3.0 (High Consistency)", caps: ["high-consistency", "action presets", "start/end"] },
    { value: "v3.0.1", label: "V3.0 Flash", caps: ["multi-shot", "hires", "fastest", "no card"] },
    { value: "v2.7", label: "V2.7 (High Dynamics)", caps: ["camera moves", "dynamic", "no card"] }
  ];
  var MODEL_VMODES = {
    "v4.0": ["i2v", "flf", "r2v"],
    "v4.0.1": ["i2v", "flf", "r2v"],
    "v3.2": ["i2v", "flf"],
    "v3.0.2": ["i2v", "flf"],
    "v3.0": ["i2v", "flf"],
    "v3.0.1": ["i2v"],
    "v2.7": ["i2v"]
  };
  var MODEL_MAXDUR = { "v4.0": 15, "v4.0.1": 15 };
  var MODE_LBL = { i2v: "Start Frame", flf: "Start Frame", r2v: "Image references" };
  var MODE_PH = {
    i2v: "Describe the motion \u2014 \u2018slow cinematic pan right, gentle waves\u2026\u2019",
    flf: "Describe the transition from start frame to end frame\u2026",
    r2v: "Type @image1 / @video1 / @audio1 to cite a ref \u2014 it becomes a chip \u2014 \u2018the girl from @image1 dances to @audio1\u2026\u2019"
  };
  var CHANNEL_CAP = {
    normal: "Please keep creations SFW",
    enhanced: "\u{1F451} Enhanced \u2014 for professional creators"
  };
  var DURATIONS = [5, 6, 10, 15];
  function snapDuration(d) {
    d = Number(d);
    if (!isFinite(d)) return 5;
    return DURATIONS.reduce((best, v) => Math.abs(v - d) < Math.abs(best - d) ? v : best);
  }
  function joinAnd(parts) {
    if (parts.length < 2) return parts[0] || "";
    return parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1];
  }
  function refItem(r) {
    const mid = String(r.media_id || r.mid);
    return { media_id: mid, thumb: r.thumb || "/thumbs/" + mid + ".jpg", is_nsfw: !!r.is_nsfw };
  }
  function primaryBank(s) {
    return s.mode === "r2v" ? s.imgSlots : s.slots;
  }
  function setPrimaryBank(s, arr) {
    if (s.mode === "r2v") s.imgSlots = arr;
    else s.slots = arr;
  }
  function heldRefsNotice(s, m) {
    const imgs = s.imgSlots.filter((x) => x && x.media_id).length;
    const vids = s.vidSlots.filter((x) => x && x.media_id).length;
    const held = [];
    if (imgs) held.push(imgs + (imgs === 1 ? " image ref" : " image refs"));
    if (vids) held.push(vids + (vids === 1 ? " video ref" : " video refs"));
    if (s.audSlot && s.audSlot.media_id) held.push("the audio ref");
    if (!held.length) return "";
    return "Still held for Multi-Reference: " + joinAnd(held) + ". Nothing was deleted \u2014 " + (m === "flf" ? "First & Last Frames" : "First Frame") + " has nowhere to show that. Switch back to Multi-Reference, on a model that offers it, and it is all still there.";
  }
  function applyMode(s, m, userDriven) {
    const from = s.mode;
    s.mode = m;
    if (m === "i2v") s.slots = [s.slots[0] || null];
    else if (m === "flf") s.slots = [s.slots[0] || null, s.slots[1] || null];
    else {
      if (!s.imgSlots.length) s.imgSlots = [null];
      if (!s.vidSlots.length) s.vidSlots = [null];
    }
    s.modeNote = userDriven && from === "r2v" && m !== "r2v" ? heldRefsNotice(s, m) : "";
  }
  function applyModelGating(s, userDriven) {
    const allowed = MODEL_VMODES[s.model] || ["i2v", "flf", "r2v"];
    if (allowed.indexOf(s.mode) === -1) applyMode(s, allowed[0], userDriven);
    const maxDur = MODEL_MAXDUR[s.model] || 10;
    if (s.duration > maxDur) s.duration = maxDur;
  }
  function applySetRefs(s, refs) {
    if (!Array.isArray(refs)) return;
    refs = refs.slice(0, 6);
    if (refs.length > 1) applyMode(s, "r2v");
    const slots = refs.map(refItem);
    if (refs.length > 1) setPrimaryBank(s, slots);
    else if (s.mode === "r2v") setPrimaryBank(s, [slots[0] || null]);
    else s.slots[0] = slots[0] || null;
  }
  function applyPrefill(s, o) {
    o = o || {};
    s.modeNote = "";
    if (o.mode && MODE_LBL[String(o.mode).toLowerCase()]) applyMode(s, String(o.mode).toLowerCase());
    if (o.video_model != null) s.model = o.video_model;
    if (o.duration != null) s.duration = snapDuration(o.duration);
    if (o.quality != null) s.quality = o.quality;
    if (o.is_private != null) s.channel = o.is_private ? "enhanced" : "normal";
    if (o.audio != null) s.audioGen = !!o.audio;
    if (o.audio_language != null) s.audioLanguage = o.audio_language;
    if (o.negative != null) s.negative = o.negative;
    const imgList = Array.isArray(o.images) ? o.images : Array.isArray(o.refs) ? o.refs : null;
    if (imgList && s.mode === "flf" && imgList.length <= 2) {
      const flfSlots = imgList.map((r) => r ? refItem(r) : null);
      s.slots = [flfSlots[0] || null, flfSlots[1] || null];
    } else {
      if (o.refs) applySetRefs(s, o.refs);
      if (o.images) applySetRefs(s, o.images);
    }
    if (Array.isArray(o.video_refs)) s.vidSlots = o.video_refs.slice(0, 3).map(refItem);
    if (o.audio_ref !== void 0) s.audSlot = o.audio_ref ? { media_id: String(o.audio_ref.media_id), filename: o.audio_ref.filename || "audio ref" } : null;
    applyModelGating(s);
    return { setPrompt: o.prompt != null ? o.prompt : null };
  }
  function buildPayload(s, promptText) {
    const images = primaryBank(s).filter((x) => x && x.media_id).map((x) => x.media_id);
    const video_refs = s.mode === "r2v" ? s.vidSlots.filter((x) => x && x.media_id).map((x) => x.media_id) : [];
    const audio_refs = s.mode === "r2v" && s.audSlot && s.audSlot.media_id ? [s.audSlot.media_id] : [];
    return {
      mode: s.mode.toUpperCase(),
      prompt: promptText || "",
      negative: (s.negative || "").trim(),
      images,
      video_refs,
      audio_refs,
      duration: +s.duration,
      audio: s.audioGen,
      video_model: s.model,
      camera_movement: s.mode !== "r2v" ? s.camera : "",
      quality: s.quality,
      audio_language: s.audioLanguage,
      is_private: s.channel === "enhanced"
    };
  }
  function hasAnyRef(p) {
    return !!(p.images.length || p.video_refs.length || p.audio_refs.length);
  }
  function flfMissingStart(s) {
    return s.mode === "flf" && !(s.slots[0] && s.slots[0].media_id) && !!(s.slots[1] && s.slots[1].media_id);
  }
  function friendlyGenErr2(raw) {
    const s = String(raw || "");
    if (!s) return "generation failed";
    let hint = "";
    if (/insufficient|INSUFFICIENT_BALANCE|40300010/i.test(s)) {
      hint = "Out of balance for this model \u2014 no free card matched and credits are 0. Claim your daily rewards, or pick a card-covered model.";
    } else if (/maxLength|too long|exceeds maximum/i.test(s)) {
      hint = "That prompt is too long for video \u2014 PixAI allows 2000 characters. Trim it and resubmit; nothing was created or charged.";
    } else if (/image contains (sensitive|nsfw|prohibited)|NSFW_DETECTED|40300032/i.test(s)) {
      hint = "PixAI refused the SOURCE IMAGE on content grounds, not the prompt \u2014 rewriting the text will not help. Try a different frame.";
    } else if (/moderat|content.?polic|flagged|nsfw/i.test(s) || /prohibit|sensitive|not.?allowed|violat/i.test(s) && /content|prompt|polic|guideline|term|image/i.test(s)) {
      hint = "PixAI's content filter blocked this generation \u2014 that's decided on PixAI's side, not here.";
    } else if (/inferenceProfile|i2vPro[./]mode|unknown mode/i.test(s)) {
      hint = "That quality setting isn't available for this model \u2014 try a different Mode.";
    }
    return hint ? hint + " (PixAI said: " + s.slice(0, 160) + ")" : s;
  }

  // ../gallery/src/components/VideoDrawer.jsx
  var lineSeq = 0;
  var VideoDrawer = forwardRef(function VideoDrawer2(props, ref) {
    const { loomCtx, style, className } = props;
    const st = useRef({
      mode: "i2v",
      slots: [null],
      // i2v/flf primary bank ([0]=start, [1]=end for flf)
      imgSlots: [null],
      // r2v image bank (max 6)
      vidSlots: [],
      // r2v video bank (max 3)
      audSlot: null,
      // {media_id, filename} | null
      model: "v4.0.1",
      duration: 5,
      camera: "unset",
      quality: "professional",
      channel: "normal",
      audioGen: false,
      audioLanguage: "english",
      negative: "",
      modeNote: "",
      rendering: false,
      hostBusy: false
    });
    const [, force] = useState(0);
    const rerender = useCallback(() => force((n) => n + 1), []);
    const [results, setResults] = useState([]);
    const [warn, setWarnState] = useState("");
    const setWarn = useCallback((w) => setWarnState(w), []);
    const ceRef = useRef(null);
    const previewRef = useRef(null);
    const audFileRef = useRef(null);
    const costRef = useRef(null);
    const rootRef = useRef(null);
    const liveNode = useRef(null);
    const setRoot = useCallback((n) => {
      rootRef.current = n;
      if (n) liveNode.current = n;
    }, []);
    const costSeq = useRef(0);
    const costTimer = useRef(0);
    const chipTimer = useRef(0);
    const previewTimer = useRef(0);
    const dirty = useRef(false);
    const pollTimers = useRef([]);
    const connected = useRef(true);
    const emit3 = useCallback((name, detail) => {
      const n = liveNode.current;
      if (n) n.dispatchEvent(new CustomEvent(name, { bubbles: true, composed: true, detail: detail || {} }));
    }, []);
    useEffect(() => () => {
      connected.current = false;
      clearTimeout(costTimer.current);
      clearTimeout(chipTimer.current);
      clearTimeout(previewTimer.current);
      pollTimers.current.forEach((t) => clearTimeout(t));
      pollTimers.current = [];
    }, []);
    const primary = () => primaryBank(st.current);
    const setPrimary = (arr) => setPrimaryBank(st.current, arr);
    const syncPlaceholder = () => {
      if (ceRef.current) ceRef.current.setAttribute("data-placeholder", MODE_PH[st.current.mode]);
    };
    const setMode = (m, userDriven) => {
      applyMode(st.current, m, userDriven);
      syncPlaceholder();
      rerender();
      debCost();
    };
    const userSetMode = (m) => {
      setMode(m, true);
      emit3("mg-mode-commit", { vmode: m });
    };
    const applyModelGating2 = (userDriven) => {
      applyModelGating(st.current, userDriven);
      syncPlaceholder();
      rerender();
    };
    const refMap = () => {
      const s2 = st.current, map = {};
      let n = 0;
      primary().forEach((x) => {
        if (x && x.media_id) {
          n++;
          map["@image" + n] = { thumb: x.thumb, mid: x.media_id, kind: "image" };
        }
      });
      if (s2.mode === "r2v") {
        let vn = 0;
        s2.vidSlots.forEach((x) => {
          if (x && x.media_id) {
            vn++;
            map["@video" + vn] = { thumb: x.thumb, mid: x.media_id, kind: "video" };
          }
        });
        if (s2.audSlot && s2.audSlot.media_id) map["@audio1"] = { mid: s2.audSlot.media_id, kind: "audio" };
      }
      return map;
    };
    const esc2 = (s2) => (s2 == null ? "" : String(s2)).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
    const makeChip = (tag, info) => {
      const c = document.createElement("span");
      c.className = "mgd-chip";
      c.contentEditable = "false";
      c.setAttribute("data-ref", tag);
      const lead = info && info.thumb ? '<img src="' + esc2(info.thumb) + '" alt="">' : info && info.kind === "audio" ? "\u266A " : "";
      c.innerHTML = lead + tag;
      if (info && info.mid && info.kind !== "audio") {
        c.onmouseenter = () => showPreview(info.mid, c);
        c.onmouseleave = () => hidePreview();
      }
      return c;
    };
    const chipify = (final) => {
      const ce = ceRef.current;
      if (!ce) return;
      const map = refMap(), sel = window.getSelection();
      const walker = document.createTreeWalker(ce, NodeFilter.SHOW_TEXT), nodes = [];
      let tn;
      while (tn = walker.nextNode()) nodes.push(tn);
      const re = /@(?:image|video|audio)\d+/g;
      nodes.forEach((node) => {
        const t = node.nodeValue, found = [];
        let m;
        re.lastIndex = 0;
        while ((m = re.exec(t)) !== null) {
          if (!map[m[0]]) continue;
          if (!final && m.index + m[0].length === t.length) continue;
          found.push({ i: m.index, tag: m[0] });
        }
        if (!found.length) return;
        const caretHere = sel.rangeCount && sel.getRangeAt(0).startContainer === node;
        const frag = document.createDocumentFragment();
        let pos = 0;
        found.forEach((f) => {
          if (f.i > pos) frag.appendChild(document.createTextNode(t.slice(pos, f.i)));
          frag.appendChild(makeChip(f.tag, map[f.tag]));
          pos = f.i + f.tag.length;
        });
        const tail = document.createTextNode(t.slice(pos));
        frag.appendChild(tail);
        node.parentNode.replaceChild(frag, node);
        if (caretHere) {
          const r = document.createRange();
          r.setStart(tail, tail.length);
          r.collapse(true);
          sel.removeAllRanges();
          sel.addRange(r);
        }
      });
    };
    const promptText = () => {
      const ce = ceRef.current;
      if (!ce) return "";
      let out = "";
      (function walk(n) {
        n.childNodes.forEach((c) => {
          if (c.nodeType === 3) out += c.nodeValue;
          else if (c.classList && c.classList.contains("mgd-chip")) out += c.getAttribute("data-ref");
          else if (c.nodeName === "BR") out += "\n";
          else walk(c);
        });
      })(ce);
      return out.replace(/ /g, " ").trim();
    };
    const promptSet = (v) => {
      if (ceRef.current) {
        ceRef.current.textContent = v || "";
        chipify(true);
      }
      debCost();
      dirty.current = false;
    };
    const emitCommitIfDirty = () => {
      if (!dirty.current) return;
      dirty.current = false;
      emit3("mg-prompt-commit", { text: promptText() });
    };
    const onCeInput = useCallback(() => {
      dirty.current = true;
      emit3("mg-dirty", {});
      clearTimeout(chipTimer.current);
      chipTimer.current = setTimeout(() => {
        chipify(false);
        debCost();
        emitCommitIfDirty();
      }, 300);
    }, []);
    const onCeBlur = useCallback(
      () => {
        chipify(true);
        emitCommitIfDirty();
      },
      // eslint-disable-next-line react-hooks/exhaustive-deps
      []
    );
    const showPreview = (mid, anchor) => {
      const p = previewRef.current, rootEl = rootRef.current;
      if (rootEl) {
        const entry = (rootEl.getAnimations ? rootEl.getAnimations() : []).filter((a) => a.animationName === "mgdDockIn" && a.playState === "running")[0];
        if (entry) {
          entry.finished.then(() => {
            if (anchor.isConnected && anchor.matches(":hover")) showPreview(mid, anchor);
          }).catch(() => {
          });
          return;
        }
      }
      if (!p || !mid || !/^(?:\d+|local_[0-9a-f]{12})$/.test(mid)) return;
      clearTimeout(previewTimer.current);
      p.innerHTML = '<img src="/thumbs/' + esc2(mid) + '.jpg" alt="">';
      p.classList.add("open");
      p.setAttribute("aria-hidden", "false");
      const r = anchor.getBoundingClientRect(), w = 300, gap = 12;
      let x = r.right + gap;
      if (x + w > window.innerWidth - 8) x = Math.max(8, r.left - w - gap);
      const y = Math.max(8, Math.min(r.top - 10, window.innerHeight - 380));
      p.style.left = x + "px";
      p.style.top = y + "px";
      requestAnimationFrame(() => p.classList.add("in"));
    };
    const hidePreview = () => {
      const p = previewRef.current;
      if (!p) return;
      p.classList.remove("in");
      p.setAttribute("aria-hidden", "true");
      clearTimeout(previewTimer.current);
      previewTimer.current = setTimeout(() => p.classList.remove("open"), 180);
    };
    const requestPick = (bank, i) => {
      emit3("mg-pick-request", {
        slot: i,
        bank,
        mode: st.current.mode,
        kind: bank === "vid" ? "video" : "image",
        respond: (media_id, thumb, is_nsfw) => {
          if (!media_id) return;
          const item = refItem({ media_id, thumb, is_nsfw });
          if (bank === "vid") {
            st.current.vidSlots[i] = item;
          } else {
            const arr = primary();
            arr[i] = item;
            setPrimary(arr);
          }
          rerender();
          debCost();
        }
      });
    };
    const uploadAudio = (file) => {
      if (file.size > 15 * 1024 * 1024) {
        renderError("Audio file too large \u2014 PixAI allows up to 15MB.");
        return;
      }
      st.current.audSlot = { uploading: file.name };
      rerender();
      const fd = new FormData();
      fd.append("file", file);
      fetch("/api/upload", { method: "POST", body: fd }).then((r) => r.json()).then((d) => {
        if (d.error || !d.media_id) {
          renderError(d.error || "audio upload failed");
          st.current.audSlot = null;
          rerender();
          return;
        }
        st.current.audSlot = { media_id: String(d.media_id), filename: file.name };
        rerender();
        debCost();
      }).catch(() => {
        renderError("audio upload failed (network)");
        st.current.audSlot = null;
        rerender();
      });
    };
    const payload = () => buildPayload(st.current, promptText());
    const flfMissingStart2 = () => flfMissingStart(st.current);
    const debCost = () => {
      clearTimeout(costTimer.current);
      costTimer.current = setTimeout(costNow, 250);
    };
    const costNow = () => {
      const cost = costRef.current;
      if (!cost) return;
      const s2 = st.current, p = payload();
      const idleHint = s2.mode === "r2v" ? "Pick at least one reference to see the cost." : "Pick a source image to see the cost.";
      if (!hasAnyRef(p)) {
        setWarn("");
        cost.clear(idleHint);
        return;
      }
      if (flfMissingStart2()) {
        setWarn("");
        cost.clear("Pick a Start Frame \u2014 the End Frame alone can\u2019t drive First & Last.");
        return;
      }
      setWarn(p.video_model === "v4.0" ? "V4.0 full \u2014 ~2.5\xD7 Lite" : "");
      cost.setChecking();
      const mine = ++costSeq.current;
      fetch("/api/price", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(p) }).then((r) => r.json()).then((d) => {
        if (mine === costSeq.current && costRef.current) costRef.current.setPrice(d);
      }).catch(() => {
        if (mine === costSeq.current && costRef.current) costRef.current.setPrice(null);
      });
    };
    const pushLine = (line) => {
      const id = ++lineSeq;
      setResults((rs) => rs.concat([{ id, ...line }]));
      return id;
    };
    const updateLine = (id, patch2) => setResults((rs) => rs.map((l) => l.id === id ? { ...l, ...patch2 } : l));
    const doGenerate = () => {
      const s2 = st.current, p = payload();
      if (!hasAnyRef(p)) {
        pushLine({ kind: "error", text: s2.mode === "r2v" ? "Pick at least one reference first." : "Pick a source image first." });
        return;
      }
      if (flfMissingStart2()) {
        pushLine({ kind: "error", text: "Pick a Start Frame first \u2014 the End Frame alone can\u2019t drive First & Last." });
        return;
      }
      const id = pushLine({ kind: "status", moon: true, text: "Submitting\u2026" });
      st.current.rendering = true;
      rerender();
      const unlock = () => {
        st.current.rendering = false;
        rerender();
      };
      fetch("/api/loom/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(p) }).then((r) => r.json()).then((d) => {
        unlock();
        if (d.error || !d.task_id) {
          const msg = friendlyGenErr2(d.error || "submit failed");
          updateLine(id, { kind: "error", text: msg, moon: false });
          emit3("mg-error", { error: msg });
          return;
        }
        emit3("mg-submit", { task_id: d.task_id, payload: p });
        updateLine(id, { kind: "status", moon: true, text: "Queued \u2014 running\u2026" });
        poll2(d.task_id, id);
      }).catch(() => {
        unlock();
        updateLine(id, { kind: "error", text: "network error", moon: false });
        emit3("mg-error", { error: "network error" });
      });
    };
    const poll2 = (taskId, lineId) => {
      const startedAt = Date.now();
      const SLOW_AT = 20 * 60 * 1e3, SLOW_MS = 20 * 1e3;
      const STALE_AT = 90 * 60 * 1e3, STALE_MS = 3 * 60 * 1e3;
      const CEILING = 6 * 60 * 60 * 1e3;
      let timer2 = null;
      const schedule2 = (fn, ms) => {
        const i = pollTimers.current.indexOf(timer2);
        if (i >= 0) pollTimers.current.splice(i, 1);
        timer2 = setTimeout(fn, ms);
        pollTimers.current.push(timer2);
      };
      const label = (ms) => ms < 36e5 ? Math.round(ms / 6e4) + "m" : Math.round(ms / 36e4) / 10 + "h";
      const short = String(taskId).slice(-6);
      const pause = () => {
        updateLine(lineId, {
          kind: "plain",
          text: "Paused auto-checking after " + label(CEILING) + " with no result \u2014 check pixai.art, or reopen this shot to check again (task " + short + ")"
        });
        emit3("mg-paused", { task_id: taskId });
      };
      const tick = () => {
        fetch("/api/task-status?task_id=" + encodeURIComponent(taskId)).then((r) => r.json()).then((d) => {
          if (!connected.current) return;
          const elapsed = Date.now() - startedAt;
          if (d.phase === "done") {
            updateLine(lineId, { kind: "result", mediaIds: d.media_ids || [], cost: d.paid_credit });
            emit3("mg-result", { media_ids: d.media_ids || [], is_video: !!d.is_video, duration: d.duration, paid_credit: d.paid_credit });
          } else if (d.phase === "failed") {
            const msg = friendlyGenErr2(d.error || "task " + (d.status || "failed"));
            updateLine(lineId, { kind: "error", text: msg, moon: false });
            emit3("mg-error", { error: msg });
          } else if (elapsed > CEILING) {
            pause();
          } else if (elapsed > STALE_AT) {
            updateLine(lineId, { kind: "status", moon: true, amber: true, text: "Still going after " + label(elapsed) + " \u2014 unusual. Check pixai.art, or keep waiting (task " + short + ")" });
            emit3("mg-slow", { tier: "stale", elapsed, task_id: taskId });
            schedule2(tick, STALE_MS);
          } else if (elapsed > SLOW_AT) {
            updateLine(lineId, { kind: "status", moon: true, amber: true, text: "Taking longer than expected (" + label(elapsed) + ", task " + short + ")" });
            emit3("mg-slow", { tier: "slow", elapsed, task_id: taskId });
            schedule2(tick, SLOW_MS);
          } else {
            updateLine(lineId, { kind: "status", moon: true, text: "Rendering under the eclipse\u2026 (task " + short + ")" });
            schedule2(tick, 2e3);
          }
        }).catch(() => {
          if (!connected.current) return;
          const elapsed = Date.now() - startedAt;
          if (elapsed > CEILING) {
            pause();
            return;
          }
          schedule2(tick, elapsed > STALE_AT ? STALE_MS : elapsed > SLOW_AT ? SLOW_MS : 2e3);
        });
      };
      schedule2(tick, 2e3);
    };
    const renderError = (msg) => {
      pushLine({ kind: "error", text: msg });
      emit3("mg-error", { error: msg });
    };
    const setRefs = (refs) => {
      applySetRefs(st.current, refs);
      syncPlaceholder();
      rerender();
      debCost();
    };
    const prefill = (o) => {
      const r = applyPrefill(st.current, o);
      syncPlaceholder();
      if (r.setPrompt != null) promptSet(r.setPrompt);
      rerender();
      debCost();
    };
    const flushPromptEdit = () => {
      clearTimeout(chipTimer.current);
      chipify(true);
      if (!dirty.current) return null;
      dirty.current = false;
      return promptText();
    };
    const setBusy = (isBusy) => {
      if (st.current.rendering) return;
      st.current.hostBusy = !!isBusy;
      rerender();
    };
    useImperativeHandle(ref, () => {
      const node = rootRef.current;
      if (node && !node._mgWired) {
        node._mgWired = true;
        node.prefill = prefill;
        node.setRefs = setRefs;
        node.flushPromptEdit = flushPromptEdit;
        node.setBusy = setBusy;
        node.payload = payload;
        Object.defineProperty(node, "mode", { configurable: true, get: () => st.current.mode });
      }
      return node;
    }, []);
    const s = st.current;
    const allowedModes = MODEL_VMODES[s.model] || ["i2v", "flf", "r2v"];
    const maxDur = MODEL_MAXDUR[s.model] || 10;
    const chosenModel = MODELS.find((m) => m.value === s.model);
    const isR2v = s.mode === "r2v";
    const canGo = !s.hostBusy && !s.rendering;
    const SEG = [["i2v", "First Frame"], ["flf", "First & Last Frames"], ["r2v", "Multi-Reference"]];
    const slotBox = (item, i, bank, placeholder, tag) => /* @__PURE__ */ react_global_shim_default.createElement(
      "div",
      {
        key: bank + i,
        className: "mgd-slot" + (bank === "vid" ? " dashed" : "") + (item ? "" : ""),
        "data-nsfw": item && item.is_nsfw ? "1" : void 0,
        style: item && bank === "vid" ? { borderStyle: "solid" } : void 0,
        onClick: () => requestPick(bank, i),
        onMouseEnter: item ? (e) => showPreview(item.media_id, e.currentTarget) : void 0,
        onMouseLeave: item ? () => hidePreview() : void 0
      },
      item ? /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, /* @__PURE__ */ react_global_shim_default.createElement("img", { src: item.thumb, alt: "" }), bank === "vid" ? /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgd-vidbadge" }, "\u25B6") : null, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgd-slot-tag" }, tag), /* @__PURE__ */ react_global_shim_default.createElement(
        "button",
        {
          type: "button",
          className: "mgd-vs-x",
          onClick: (e) => {
            e.stopPropagation();
            hidePreview();
            const cur = st.current;
            if (bank === "vid") {
              cur.vidSlots.splice(i, 1);
              if (!cur.vidSlots.length) cur.vidSlots = [null];
            } else if (cur.mode === "r2v") {
              let arr = cur.imgSlots;
              arr.splice(i, 1);
              if (!arr.length) arr = [null];
              cur.imgSlots = arr;
            } else cur.slots[i] = null;
            rerender();
            debCost();
          }
        },
        "\xD7"
      )) : placeholder
    );
    const primArr = primary();
    const mainArr = s.mode === "flf" ? [primArr[0]] : primArr;
    let refN = 0;
    const primSlots = mainArr.map((item, i) => {
      let tag = "";
      if (item) {
        refN++;
        tag = s.mode === "flf" ? "start" : "@image" + refN;
      }
      const ph = s.mode === "flf" || s.mode === "i2v" ? "+ start" : "+ pick";
      return slotBox(item, i, "primary", ph, tag);
    });
    let vidN = 0;
    const vidArr = s.vidSlots.length ? s.vidSlots : [null];
    return /* @__PURE__ */ react_global_shim_default.createElement("div", { ref: setRoot, className: "gen-drawer" + (className ? " " + className : ""), style, "data-loom-ctx": loomCtx ? "" : void 0 }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-seg", role: "tablist" }, SEG.map(([v, lbl]) => allowedModes.indexOf(v) === -1 ? null : /* @__PURE__ */ react_global_shim_default.createElement("button", { key: v, type: "button", className: s.mode === v ? "on" : "", onClick: () => userSetMode(v) }, lbl))), s.modeNote ? /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-modenote" }, s.modeNote) : null, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-lbl mgd-slots-lbl" }, MODE_LBL[s.mode]), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-slots mgd-imgslots" }, primSlots, s.mode === "r2v" && primArr.length < 6 ? /* @__PURE__ */ react_global_shim_default.createElement("button", { type: "button", className: "mgd-slot-add", onClick: () => {
      st.current.imgSlots.push(null);
      rerender();
    } }, "+ add") : null), s.mode === "flf" ? /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-lbl" }, "End Frame ", /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgd-note" }, "(Optional)")), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-slots" }, slotBox(s.slots[1], 1, "primary", "+ end", "end"))) : null, isR2v ? /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-lbl" }, "Video references ", /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgd-note" }, "\xB7 up to 3 \xB7 2\u201315s each, 15s total")), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-slots" }, vidArr.map((item, i) => {
      let tag = "";
      if (item) {
        vidN++;
        tag = "@video" + vidN;
      }
      return slotBox(item, i, "vid", "+ video", tag);
    }), s.vidSlots.length < 3 ? /* @__PURE__ */ react_global_shim_default.createElement("button", { type: "button", className: "mgd-slot-add", onClick: () => {
      const cur = st.current;
      if (!cur.vidSlots.length) cur.vidSlots = [null, null];
      else cur.vidSlots.push(null);
      rerender();
    } }, "+ add") : null), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-lbl" }, "Audio reference ", /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgd-note" }, "\xB7 WAV \u226415MB")), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-audiorow" }, s.audSlot && s.audSlot.uploading ? /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgd-note" }, "Uploading ", s.audSlot.uploading, "\u2026") : s.audSlot ? /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgd-audiochip" }, "\u266A @audio1 \xB7 ", s.audSlot.filename, " ", /* @__PURE__ */ react_global_shim_default.createElement("button", { type: "button", onClick: () => {
      st.current.audSlot = null;
      rerender();
      debCost();
    } }, "\xD7")) : /* @__PURE__ */ react_global_shim_default.createElement("button", { type: "button", className: "mgd-audioadd", onClick: () => audFileRef.current && audFileRef.current.click() }, "+ Audio"))) : null, /* @__PURE__ */ react_global_shim_default.createElement(
      "input",
      {
        ref: audFileRef,
        type: "file",
        className: "mgd-audiofile",
        accept: "audio/*",
        style: { display: "none" },
        onChange: (e) => {
          const f = e.target.files[0];
          e.target.value = "";
          if (f) uploadAudio(f);
        }
      }
    ), /* @__PURE__ */ react_global_shim_default.createElement(
      "div",
      {
        ref: ceRef,
        className: "mgd-ce",
        contentEditable: true,
        suppressContentEditableWarning: true,
        "data-placeholder": MODE_PH[s.mode],
        onInput: onCeInput,
        onBlur: onCeBlur
      }
    ), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-lbl" }, "Negative prompt"), /* @__PURE__ */ react_global_shim_default.createElement(
      "textarea",
      {
        className: "mgd-neg",
        placeholder: "blurry, extra fingers, watermark",
        value: s.negative,
        onChange: (e) => {
          st.current.negative = e.target.value;
          rerender();
          debCost();
        }
      }
    ), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-row" }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "grow" }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-lbl" }, "Model"), /* @__PURE__ */ react_global_shim_default.createElement(
      "select",
      {
        className: "mgd-sel mgd-model",
        value: s.model,
        onChange: (e) => {
          st.current.model = e.target.value;
          applyModelGating2(true);
          debCost();
        }
      },
      MODELS.map((m) => /* @__PURE__ */ react_global_shim_default.createElement("option", { key: m.value, value: m.value }, m.label))
    ), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-caps mgd-modelcaps" }, (chosenModel ? chosenModel.caps : []).map((t) => /* @__PURE__ */ react_global_shim_default.createElement("span", { key: t, className: "mgd-cap hot" }, t)))), /* @__PURE__ */ react_global_shim_default.createElement("div", null, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-lbl" }, "Duration (s)"), /* @__PURE__ */ react_global_shim_default.createElement(
      "select",
      {
        className: "mgd-sel mgd-dur",
        value: String(s.duration),
        onChange: (e) => {
          st.current.duration = +e.target.value;
          rerender();
          debCost();
          emit3("mg-duration-commit", { duration: +e.target.value });
        }
      },
      [5, 6, 10, 15].map((d) => /* @__PURE__ */ react_global_shim_default.createElement("option", { key: d, value: d, disabled: d > maxDur, hidden: d > maxDur }, d))
    ))), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-row" }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-cam-wrap" }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-lbl" }, "Camera"), /* @__PURE__ */ react_global_shim_default.createElement("select", { className: "mgd-sel mgd-cam", value: s.camera, onChange: (e) => {
      st.current.camera = e.target.value;
      rerender();
    } }, /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "unset" }, "Unset"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "horizontal" }, "Side-to-side move"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "vertical-pan" }, "Vertical Pan"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "zoom" }, "Zoom in or out"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "pan" }, "Camera sweep"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "tilt" }, "Tilt up or down"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "roll" }, "Camera spin"))), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-quality-wrap" }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-lbl" }, "Basic / Professional"), /* @__PURE__ */ react_global_shim_default.createElement("select", { className: "mgd-sel mgd-quality", value: s.quality, onChange: (e) => {
      st.current.quality = e.target.value;
      rerender();
    } }, /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "basic" }, "Basic"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "professional" }, "Professional"))), /* @__PURE__ */ react_global_shim_default.createElement("div", null, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-lbl" }, "Channel"), /* @__PURE__ */ react_global_shim_default.createElement("select", { className: "mgd-sel mgd-channel", value: s.channel, onChange: (e) => {
      st.current.channel = e.target.value;
      rerender();
      debCost();
    } }, /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "normal" }, "Normal"), /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "enhanced" }, "Enhanced")), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-caps mgd-chancap" }, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgd-cap" + (s.channel === "enhanced" ? " crown" : "") }, CHANNEL_CAP[s.channel])))), /* @__PURE__ */ react_global_shim_default.createElement("label", { className: "mgd-check" }, /* @__PURE__ */ react_global_shim_default.createElement(
      "input",
      {
        type: "checkbox",
        className: "mgd-audio",
        checked: s.audioGen,
        onChange: (e) => {
          st.current.audioGen = e.target.checked;
          rerender();
          debCost();
          emit3("mg-audio-commit", { audioGen: e.target.checked, audioLanguage: st.current.audioLanguage });
        }
      }
    ), " ", "Generate audio ", /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgd-note" }, "(spoken lines in the prompt become voiceover)")), s.audioGen ? /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-lang-wrap", style: { marginTop: 4 } }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-lbl" }, "Audio language"), /* @__PURE__ */ react_global_shim_default.createElement(
      "select",
      {
        className: "mgd-sel mgd-lang",
        value: s.audioLanguage,
        onChange: (e) => {
          st.current.audioLanguage = e.target.value;
          rerender();
          debCost();
          emit3("mg-audio-commit", { audioGen: st.current.audioGen, audioLanguage: e.target.value });
        }
      },
      /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "english" }, "English"),
      /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "japanese" }, "Japanese"),
      /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "chinese" }, "Chinese"),
      /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "korean" }, "Korean"),
      /* @__PURE__ */ react_global_shim_default.createElement("option", { value: "none" }, "SE only (no dialogue)")
    )) : null, /* @__PURE__ */ react_global_shim_default.createElement(
      CostBadge_default,
      {
        ref: costRef,
        className: "mgd-cost",
        warn,
        cardLabel: "a video card",
        hint: "Pick a source image to see the cost."
      }
    ), /* @__PURE__ */ react_global_shim_default.createElement("button", { type: "button", className: "mgd-go", disabled: !canGo, onClick: doGenerate }, s.rendering ? "Rendering\u2026" : "Generate video"), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mgd-result" + (results.length ? " has" : "") }, results.map((l) => /* @__PURE__ */ react_global_shim_default.createElement("div", { key: l.id, className: "mgd-result-line" }, l.kind === "result" ? /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, /* @__PURE__ */ react_global_shim_default.createElement("div", { style: { color: "var(--emerald,#4fc99a)", fontSize: 12, marginBottom: 6 } }, "\u2713 Rendered \u2014 ", l.cost === 0 ? "free (card used)" : Number(l.cost || 0).toLocaleString() + " credits", ". Added to your gallery."), (l.mediaIds || []).map((mid) => /* @__PURE__ */ react_global_shim_default.createElement("a", { key: mid, href: "/next?image=" + encodeURIComponent(mid) }, /* @__PURE__ */ react_global_shim_default.createElement("img", { src: "/thumbs/" + encodeURIComponent(mid) + ".jpg", alt: "result", loading: "lazy" })))) : l.kind === "error" ? /* @__PURE__ */ react_global_shim_default.createElement("span", { style: { color: "var(--red,#f38ba8)", fontSize: 12 } }, l.text) : l.kind === "plain" ? /* @__PURE__ */ react_global_shim_default.createElement("span", { style: { color: "var(--subtext,#9a93ab)", fontSize: 12 } }, l.text) : /* @__PURE__ */ react_global_shim_default.createElement("span", { style: { color: l.amber ? "var(--amber,#f9d38c)" : "var(--subtext,#9a93ab)", fontSize: 12 } }, l.moon ? /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mgd-moon" }) : null, l.text)))), /* @__PURE__ */ react_global_shim_default.createElement("div", { ref: previewRef, className: "mgd-preview", "aria-hidden": "true" }));
  });
  var VideoDrawer_default = VideoDrawer;

  // ../gallery/src/notify/toastStore.js
  var seq = 0;
  var toasts = [];
  var subs = /* @__PURE__ */ new Set();
  function emit() {
    subs.forEach((fn) => fn(toasts));
  }
  function subscribe(fn) {
    subs.add(fn);
    fn(toasts);
    return () => subs.delete(fn);
  }
  function dismiss(id) {
    const t = toasts.find((x) => x.id === id);
    if (!t || t.out) return;
    t.out = true;
    toasts = toasts.slice();
    emit();
    setTimeout(() => {
      toasts = toasts.filter((x) => x.id !== id);
      emit();
    }, 340);
  }
  function show(o) {
    o = o || {};
    const kind = o.kind || "";
    const icon = o.icon || (kind === "ok" ? "\u2713" : kind === "err" ? "\u26A0" : kind === "unlock" ? "\u{1F3C6}" : "\u25C9");
    const id = ++seq;
    toasts = toasts.concat([{
      id,
      kind,
      icon,
      title: o.title || "",
      msg: o.msg || "",
      thumb: o.thumb || "",
      sticky: !!o.sticky,
      out: false
    }]);
    emit();
    const remove = () => dismiss(id);
    if (!o.sticky) setTimeout(remove, o.ttl || 5200);
    return remove;
  }

  // ../gallery/src/notify/jobsStore.js
  var LSK = "mg_jobs_open";
  var jobs = [];
  var open = false;
  var started = false;
  var timer = null;
  var seeded = false;
  var last = {};
  var subs2 = /* @__PURE__ */ new Set();
  function emit2() {
    subs2.forEach((fn) => fn({ jobs, open }));
  }
  function subscribe2(fn) {
    subs2.add(fn);
    fn({ jobs, open });
    return () => subs2.delete(fn);
  }
  function runningCount() {
    return jobs.filter((j) => (j.status || "running") === "running").length;
  }
  function readOpen() {
    try {
      return localStorage.getItem(LSK) === "1";
    } catch {
      return false;
    }
  }
  function setOpen(v) {
    try {
      localStorage.setItem(LSK, v ? "1" : "0");
    } catch {
    }
    open = !!v;
    emit2();
  }
  function openTray() {
    setOpen(true);
    refresh();
  }
  function closeTray() {
    setOpen(false);
  }
  var TERMINAL = { done: 1, failed: 1, done_with_errors: 1, stale: 1 };
  function toastTransitions(rows) {
    rows.forEach((j) => {
      const st = j.status || "running";
      const prev = last[j.job_id];
      if (seeded && !TERMINAL[prev] && TERMINAL[st]) {
        if (st === "done") {
          const mid = (j.media_ids || [])[0] || "";
          show({
            kind: "ok",
            title: (j.label || "Generation") + " \u2014 done",
            msg: "Added to your gallery.",
            thumb: mid ? "/thumbs/" + encodeURIComponent(mid) + ".jpg" : null
          });
        } else if (st === "done_with_errors") {
          show({
            kind: "err",
            sticky: true,
            title: (j.label || "Job") + " finished with errors",
            msg: j.error || "Some files failed \u2014 see the activity card."
          });
        } else if (st === "stale") {
          show({
            kind: "err",
            sticky: true,
            title: (j.label || "Job") + " \u2014 stalled",
            msg: j.error || "See the activity card."
          });
        } else {
          show({
            kind: "err",
            sticky: true,
            title: (j.label || "Job") + " failed",
            msg: j.error || "See the activity card."
          });
        }
      }
      last[j.job_id] = st;
    });
    seeded = true;
  }
  function refresh() {
    return fetch("/api/jobs").then((r) => r.json()).then((d) => {
      const rows = d && d.jobs || [];
      toastTransitions(rows);
      jobs = rows;
      emit2();
    }).catch(() => {
    });
  }
  function schedule() {
    if (timer) clearTimeout(timer);
    const busy = runningCount() > 0;
    timer = setTimeout(() => {
      if (document.hidden) {
        schedule();
        return;
      }
      refresh().then(schedule);
    }, busy ? 2500 : 7e3);
  }
  function dismiss2(id) {
    fetch("/api/jobs/dismiss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: id })
    }).then(() => {
      delete last[id];
      refresh();
    }).catch(() => {
    });
  }
  function clearFinished() {
    fetch("/api/jobs/dismiss", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ finished: true })
    }).then(refresh).catch(() => {
    });
  }
  function start() {
    if (started) return;
    started = true;
    open = readOpen();
    emit2();
    refresh().then(schedule);
  }

  // ../gallery/src/notify/jobs.js
  var seen = {};
  function register(id, label, count) {
    if (!id || seen[id]) return;
    seen[id] = true;
    fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: id, type: "generate", label: label || "Generation", status: "running", count })
    }).catch(() => {
    });
    refresh();
  }
  function track(id, label, cb, count) {
    if (!id || seen[id]) return;
    register(id, label, count);
    poll(id, cb);
  }
  var POLL_CEILING_MS = 6 * 60 * 60 * 1e3;
  function poll(id, cb, startedAt) {
    const t0 = startedAt || Date.now();
    function again(ms) {
      if (Date.now() - t0 > POLL_CEILING_MS) {
        if (cb) cb("stalled", {
          phase: "stalled",
          error: "Stopped checking after 6h \u2014 the task may still be running. Reload to resume watching, or check it on pixai.art."
        });
        refresh();
        return;
      }
      setTimeout(() => poll(id, cb, t0), ms);
    }
    fetch("/api/task-status?task_id=" + encodeURIComponent(id)).then((r) => r.json()).then((d) => {
      if (d.phase === "done") {
        if (cb) cb("done", d);
        refresh();
      } else if (d.phase === "failed") {
        if (cb) cb("failed", d);
        refresh();
      } else {
        if (cb) cb("running", d);
        again(3e3);
      }
    }).catch(() => again(4e3));
  }

  // ../gallery/src/notify/ach.js
  var data = null;
  function unleashed() {
    try {
      return localStorage.getItem("unleash") === "1";
    } catch {
      return false;
    }
  }
  function skinName(d, id) {
    const s = ((d || {}).skins || []).filter((x) => x.id === id)[0];
    return s ? s.name : id;
  }
  function applySkin(id) {
    if (id && id !== "moonglade") document.documentElement.setAttribute("data-skin", id);
    else document.documentElement.removeAttribute("data-skin");
    try {
      localStorage.setItem("skin", id || "moonglade");
    } catch {
    }
  }
  function syncSkin(d) {
    const srv = d.skin || "moonglade";
    let cur = null;
    try {
      cur = localStorage.getItem("skin");
    } catch {
    }
    if (srv !== cur) applySkin(srv);
  }
  function load(mark) {
    fetch("/api/achievements" + (mark ? "?mark=1" : "")).then((r) => r.json()).then((d) => {
      data = d;
      if (mark) toastNew(d);
      syncSkin(d);
    }).catch(() => {
    });
  }
  function toastNew(d) {
    const newly = (d.newly || []).map((id) => (d.achievements || []).filter((a) => a.id === id)[0]).filter(Boolean);
    if (newly.length > 3) {
      showToast({
        icon: "\u{1F3C6}",
        name: newly.length + " achievements unlocked",
        desc: "Your catalog just earned a stack of achievements. Open \u{1F3C6} to review them."
      });
      return;
    }
    newly.forEach((a) => celebrate(a));
  }
  var _q = [];
  var _playing = false;
  var _actx = null;
  var _sfx = {};
  function _chime(tier) {
    const key = tier || "common";
    if (_sfx[key] === 0) {
      _synth(tier);
      return;
    }
    try {
      const au = new Audio("/branding/sfx/ach_" + key + ".ogg");
      au.volume = 0.7;
      au.play().then(() => {
        _sfx[key] = 1;
      }).catch(() => {
        _sfx[key] = 0;
        _synth(tier);
      });
    } catch {
      _sfx[key] = 0;
      _synth(tier);
    }
  }
  function _synth(tier) {
    try {
      _actx = _actx || new (window.AudioContext || window.webkitAudioContext)();
      if (_actx.state === "suspended") _actx.resume();
    } catch {
      return;
    }
    const seq2 = {
      common: [523, 660],
      rare: [523, 660, 784],
      epic: [523, 660, 784, 988],
      legendary: [392, 523, 660, 784, 1047],
      feat: [392, 466, 622, 932]
    }[tier] || [660];
    const t = _actx.currentTime + 0.02;
    seq2.forEach((f, i) => {
      const o = _actx.createOscillator(), g = _actx.createGain();
      o.type = "triangle";
      o.frequency.value = f;
      o.connect(g);
      g.connect(_actx.destination);
      const s = t + i * 0.1;
      g.gain.setValueAtTime(1e-4, s);
      g.gain.linearRampToValueAtTime(0.15, s + 0.02);
      g.gain.exponentialRampToValueAtTime(1e-4, s + 0.5);
      o.start(s);
      o.stop(s + 0.55);
    });
    if (tier === "legendary" || tier === "feat") {
      const lo = _actx.createOscillator(), lg = _actx.createGain();
      lo.type = "sine";
      lo.frequency.value = tier === "feat" ? 78 : 98;
      lo.connect(lg);
      lg.connect(_actx.destination);
      lg.gain.setValueAtTime(1e-4, t);
      lg.gain.linearRampToValueAtTime(0.28, t + 0.02);
      lg.gain.exponentialRampToValueAtTime(1e-4, t + 1.2);
      lo.start(t);
      lo.stop(t + 1.3);
    }
  }
  function esc(s) {
    return (s == null ? "" : String(s)).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  }
  function _mkMoment(a, opts) {
    opts = opts || {};
    const tier = a.tier || "common";
    const m = document.createElement("div");
    m.className = "ach-m2";
    const stage = document.createElement("div");
    stage.className = "tstage";
    const tw = document.createElement("div");
    tw.className = "tw t-" + tier;
    const line = opts.line != null ? opts.line : unleashed() && a.roast_nsfw ? a.roast_nsfw : a.roast || a.desc || "";
    let rwd = "";
    if (a.skin) rwd = "Unlocks skin: " + skinName(data || { skins: [] }, a.skin);
    else if (a.banner_reward) rwd = "Unlocks a banner";
    const toastHTML = '<div class="toast"><div class="cap"></div><div class="tbody"><div class="u">' + esc(opts.eyebrow || "New Achievement") + '</div><div class="n">' + esc(a.name) + '</div><div class="r">' + esc(line) + "</div>" + (opts.pill === false ? "" : '<span class="tier-pill">' + esc(tier) + "</span>") + (a.points && opts.pill !== false ? '<span class="pts-pill">+' + (Number(a.points) || 0) + "</span>" : "") + (rwd ? '<span class="rwd"><i class="giftbox"></i>' + esc(rwd) + "</span>" : "") + '</div><div class="flash"></div></div>';
    tw.innerHTML = '<div class="mglow"></div>' + toastHTML;
    stage.appendChild(tw);
    m.appendChild(stage);
    const cap = tw.querySelector(".cap");
    if (opts.badge === false) {
      const e2 = document.createElement("div");
      e2.className = "badge emoji";
      e2.textContent = a.icon || "\u{1F3C6}";
      cap.appendChild(e2);
    } else {
      const b = document.createElement("img");
      b.className = "badge";
      b.onerror = function() {
        const e = document.createElement("div");
        e.className = "badge emoji";
        e.textContent = a.icon || "\u{1F3C6}";
        if (this.parentNode) this.parentNode.replaceChild(e, this);
      };
      b.src = "/branding/badges/" + encodeURIComponent(a.id) + ".png";
      cap.appendChild(b);
      const ring = document.createElement("div");
      ring.className = "ring";
      cap.appendChild(ring);
      if (tier === "legendary") {
        const halo = document.createElement("div");
        halo.className = "m2-halo";
        cap.appendChild(halo);
        const moteWrap = document.createElement("div");
        moteWrap.className = "m2-motewrap";
        [0, 72, 144, 216, 288].forEach((deg, i) => {
          const r = 50, rad = deg * Math.PI / 180;
          const x = 50 + r * Math.cos(rad), y = 50 + r * Math.sin(rad), sz = i % 2 ? 5 : 7;
          const mt = document.createElement("span");
          mt.className = "m2-mote";
          mt.style.left = x.toFixed(1) + "%";
          mt.style.top = y.toFixed(1) + "%";
          mt.style.width = sz + "px";
          mt.style.height = sz + "px";
          moteWrap.appendChild(mt);
        });
        cap.appendChild(moteWrap);
      } else if (tier === "feat") {
        const flame = document.createElement("div");
        flame.className = "m2-flameglow";
        cap.appendChild(flame);
        cap.appendChild(document.createElement("div")).className = "m2-runeA";
        cap.appendChild(document.createElement("div")).className = "m2-runeB";
        for (let wi = 0; wi < 8; wi++) {
          const sway = (wi % 2 ? 1 : -1) * (10 + wi * 3);
          const rot = (wi % 2 ? 1 : -1) * (8 + wi * 2);
          const sz = 10 + wi % 3 * 4;
          const wisp = document.createElement("div");
          wisp.className = "m2-wisp";
          wisp.style.left = 16 + wi * 9 + "%";
          wisp.style.width = sz + "px";
          wisp.style.height = sz + "px";
          wisp.style.setProperty("--sway", sway + "px");
          wisp.style.setProperty("--rot", rot + "deg");
          wisp.style.animationDuration = (1.1 + wi % 4 * 0.15).toFixed(2) + "s";
          wisp.style.animationDelay = (1.4 + wi * 0.12).toFixed(2) + "s";
          cap.appendChild(wisp);
        }
      }
    }
    if (opts.mascot !== false) {
      const mfall = tier === "feat" ? "legendary" : tier;
      const nel = document.createElement("img");
      nel.className = "mascot";
      const chain = [
        "/branding/mascots/ach/" + encodeURIComponent(a.id) + ".webp",
        "/branding/mascots/ach/" + encodeURIComponent(a.id) + ".png",
        "/branding/mascots/present_" + mfall + ".png"
      ];
      let ci = 0;
      nel.onerror = function() {
        ci++;
        if (ci < chain.length) this.src = chain[ci];
        else this.remove();
      };
      nel.onload = function() {
        try {
          _seatMascot(this);
        } catch {
        }
      };
      nel.src = chain[0];
      tw.insertBefore(nel, tw.querySelector(".toast"));
    }
    return { m, tw };
  }
  function _seatMascot(img) {
    const W = 48, H = 64, c = document.createElement("canvas");
    c.width = W;
    c.height = H;
    const x = c.getContext("2d");
    x.drawImage(img, 0, 0, W, H);
    const d = x.getImageData(0, 0, W, H).data;
    let top = -1, bot = -1, r, q;
    for (r = 0; r < H && top < 0; r++) {
      for (q = 3; q < W * 4; q += 16) {
        if (d[r * W * 4 + q] > 24) {
          top = r;
          break;
        }
      }
    }
    for (r = H - 1; r >= 0 && bot < 0; r--) {
      for (q = 3; q < W * 4; q += 16) {
        if (d[r * W * 4 + q] > 24) {
          bot = r;
          break;
        }
      }
    }
    if (top < 0 || bot <= top) return;
    const opFrac = (bot - top + 1) / H, topFrac = top / H;
    const BAND = 158, TARGET = 150;
    const h = Math.max(140, Math.min(260, TARGET / opFrac));
    img.style.height = h + "px";
    img.style.top = (BAND - h * topFrac - 0.75 * (h * opFrac)).toFixed(1) + "px";
  }
  function _fanfare(m, tier) {
    const glyphs = ["\u2726", "\u2727", "\u2B50"];
    let i, s, cn;
    for (i = 0; i < 46; i++) {
      s = document.createElement("div");
      s.className = "ee-star";
      s.textContent = glyphs[i % 3];
      s.style.left = Math.random() * 100 + "vw";
      s.style.color = tier === "feat" ? "var(--ruby)" : "var(--gold)";
      s.style.fontSize = 12 + Math.random() * 22 + "px";
      s.style.animationDuration = 2.4 + Math.random() * 2.4 + "s";
      s.style.animationDelay = Math.random() * 1.4 + "s";
      m.appendChild(s);
    }
    const cols = tier === "feat" ? ["#e0355e", "#8a93a2", "#a11238", "#d6d2e2", "#4a515c"] : ["#b692e6", "#d4af37", "#4fc99a", "#c4a6f0", "#ffffff"];
    for (i = 0; i < 84; i++) {
      cn = document.createElement("i");
      cn.className = "m2-conf";
      cn.style.background = cols[i % cols.length];
      cn.style.left = Math.random() * 100 + "vw";
      cn.style.animationDuration = 1.8 + Math.random() * 1.8 + "s";
      cn.style.animationDelay = 0.2 + Math.random() * 0.9 + "s";
      m.appendChild(cn);
    }
  }
  function _play(built, hold, after) {
    const m = built.m, tw = built.tw;
    document.body.appendChild(m);
    void m.offsetWidth;
    m.classList.add("go");
    tw.classList.add("go");
    const done = () => {
      if (m._d) return;
      m._d = true;
      m.classList.add("out");
      setTimeout(() => {
        if (m.parentNode) m.remove();
        if (after) after();
      }, 500);
    };
    m._t = setTimeout(done, hold);
    m.addEventListener("click", () => {
      clearTimeout(m._t);
      done();
    });
  }
  var HOLD = { common: 4200, rare: 4800, epic: 5400, legendary: 6400, feat: 6400 };
  function celebrate(a) {
    if (a) {
      _q.push(a);
      if (!_playing) _next();
    }
  }
  function _next() {
    if (!_q.length) {
      _playing = false;
      return;
    }
    _playing = true;
    const a = _q.shift(), tier = a.tier || "common";
    _chime(tier);
    const built = _mkMoment(a, {});
    if (tier === "legendary" || tier === "feat") _fanfare(built.m, tier);
    _play(built, HOLD[tier] || 4600, _next);
  }
  function showToast(a) {
    _play(_mkMoment(
      { name: a.name, tier: "legendary", icon: a.icon || "\u{1F3C6}", id: "" },
      { badge: false, mascot: false, pill: false, eyebrow: "Achievement Unlocked", line: a.desc || "" }
    ), 6500, null);
  }
  function check() {
    load(true);
  }
  function replay(a, opts) {
    if (!a || !a.id) return {};
    opts = opts || {};
    const tier = a.tier || "common";
    _chime(tier);
    const built = _mkMoment(a, { eyebrow: "Achievement \xB7 Replay", line: opts.line });
    if (tier === "legendary" || tier === "feat") _fanfare(built.m, tier);
    _play(built, HOLD[tier] || 4600, null);
    const rEl = built.tw.querySelector(".toast .tbody .r");
    return {
      setText(text) {
        if (rEl) rEl.textContent = text;
      },
      setGlitching(on) {
        if (rEl) rEl.classList.toggle("glitch", !!on);
      },
      setSettledNsfw(on) {
        if (rEl) rEl.classList.toggle("settled-nsfw", !!on);
      },
      dismiss() {
        if (built.m && built.m.parentNode) built.m.click();
      }
    };
  }

  // scripts/react-dom-global-shim.js
  var ReactDOM = window.ReactDOM;
  var createPortal = ReactDOM.createPortal;
  var flushSync = ReactDOM.flushSync;
  var createRoot = ReactDOM.createRoot;
  var hydrateRoot = ReactDOM.hydrateRoot;
  var render = ReactDOM.render;
  var unmountComponentAtNode = ReactDOM.unmountComponentAtNode;
  var findDOMNode = ReactDOM.findDOMNode;

  // ../gallery/src/notify/ToastHost.jsx
  function ToastHost() {
    const [toasts2, setToasts] = useState([]);
    useEffect(() => subscribe(setToasts), []);
    return createPortal(
      /* @__PURE__ */ react_global_shim_default.createElement("div", { id: "mg-toasts", "aria-live": "polite" }, toasts2.map((t) => /* @__PURE__ */ react_global_shim_default.createElement("div", { key: t.id, className: "mg-toast" + (t.kind ? " " + t.kind : "") + (t.out ? " out" : "") }, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mt-ic" }, t.icon), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mt-main" }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mt-title" }, t.title), t.msg ? /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "mt-msg" }, t.msg) : null), t.thumb ? /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "mt-thumb", style: { backgroundImage: "url('" + t.thumb.replace(/'/g, "%27") + "')" } }) : null, /* @__PURE__ */ react_global_shim_default.createElement("button", { className: "mt-x", "aria-label": "Dismiss", onClick: () => dismiss(t.id) }, "\xD7")))),
      document.body
    );
  }

  // ../gallery/src/notify/format.js
  function ago(ts) {
    const s = Math.max(0, Math.floor(Date.now() / 1e3 - (ts || 0)));
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + "m ago";
    if (s < 86400) return Math.floor(s / 3600) + "h ago";
    return Math.floor(s / 86400) + "d ago";
  }
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function pad2(n) {
    return (n < 10 ? "0" : "") + n;
  }
  function fmtClock(ts) {
    if (!ts) return "\u2014";
    const d = new Date(ts * 1e3);
    const h = d.getHours(), ap = h >= 12 ? "PM" : "AM", h12 = h % 12 || 12;
    return MONTHS[d.getMonth()] + " " + d.getDate() + ", " + h12 + ":" + pad2(d.getMinutes()) + " " + ap;
  }
  function fmtDuration(s) {
    s = Math.max(0, Math.floor(s || 0));
    if (s < 60) return s + "s";
    if (s < 3600) return Math.floor(s / 60) + "m " + s % 60 + "s";
    if (s < 86400) return Math.floor(s / 3600) + "h " + Math.floor(s % 3600 / 60) + "m";
    return Math.floor(s / 86400) + "d " + Math.floor(s % 86400 / 3600) + "h";
  }
  var KIND_LABEL = {
    cli: "Terminal",
    panel: "Control Panel",
    generate: "Generate",
    delete: "Delete",
    import: "Import"
  };
  function kindLabel(t) {
    return KIND_LABEL[t] || t || "Job";
  }
  var LABEL_ING = {
    Generated: "Generating",
    Edited: "Editing",
    Rendered: "Rendering",
    Fixed: "Fixing",
    Upscaled: "Upscaling",
    Imported: "Importing",
    Uploaded: "Uploading"
  };
  function labelFor(j, terminal) {
    const l = j.label || "Generation";
    return terminal ? l : LABEL_ING[l] || l;
  }
  function groupThousands(n) {
    const s = String(Math.round(Math.abs(n)));
    let grp = "", i = 0;
    for (let k = s.length - 1; k >= 0; k--) {
      grp = s.charAt(k) + grp;
      if (++i % 3 === 0 && k > 0) grp = "," + grp;
    }
    return grp;
  }

  // ../gallery/src/notify/ActivityTray.jsx
  function Row({ j, onDismiss, onOpenDetail }) {
    const st = j.status || "running";
    const queued = st === "running" && j.started === false;
    const fin = st === "done" || st === "failed" || st === "done_with_errors" || st === "stale";
    const mid = (j.media_ids || [])[0] || "";
    const pct = st === "running" && j.total ? Math.min(100, Math.round((j.done || 0) / j.total * 100)) : null;
    const showErr = (st === "failed" || st === "done_with_errors" || st === "stale") && j.error;
    const cls = st === "failed" ? " st-failed" : st === "done_with_errors" || st === "stale" ? " st-warn" : "";
    const icon = st === "done" ? /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jt-ok jt-glyph" }, "\u2713"), /* @__PURE__ */ react_global_shim_default.createElement("img", { className: "jt-nel", src: "/branding/mascots/trk_done.png", alt: "", onError: (e) => e.currentTarget.remove() })) : st === "done_with_errors" ? /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jt-warn jt-glyph" }, "\u26A0"), /* @__PURE__ */ react_global_shim_default.createElement("img", { className: "jt-nel", src: "/branding/mascots/trk_done.png", alt: "", onError: (e) => e.currentTarget.remove() })) : st === "failed" ? /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jt-err jt-glyph" }, "\u26A0"), /* @__PURE__ */ react_global_shim_default.createElement("img", { className: "jt-nel", src: "/branding/mascots/trk_fail.png", alt: "", onError: (e) => e.currentTarget.remove() })) : st === "stale" ? /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jt-warn jt-glyph" }, "?"), /* @__PURE__ */ react_global_shim_default.createElement("img", { className: "jt-nel", src: "/branding/mascots/trk_fail.png", alt: "", onError: (e) => e.currentTarget.remove() })) : /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jt-spin" + (queued ? " jt-queued" : "") }, /* @__PURE__ */ react_global_shim_default.createElement("img", { className: "jt-nel", src: "/branding/gen_nel.png", alt: "", onError: (e) => e.currentTarget.remove() }), /* @__PURE__ */ react_global_shim_default.createElement("i", { className: "gen-ring" }));
    const stopTracking = (e) => {
      e.stopPropagation();
      if (!fin && !window.confirm(
        "Stop tracking this job?\n\nThis does NOT cancel it on PixAI or touch your credits -- it only stops your local Job Tracker from watching it. If it was actually still generating, the finished image will still land in your library later; it just will not be tracked here anymore."
      )) return;
      onDismiss(j.job_id);
    };
    return /* @__PURE__ */ react_global_shim_default.createElement(
      "div",
      {
        className: "jt-item" + cls,
        tabIndex: 0,
        role: "button",
        "aria-haspopup": "true",
        onClick: (e) => onOpenDetail(j.job_id, e.currentTarget),
        onKeyDown: (e) => {
          if (e.key !== "Enter" && e.key !== " ") return;
          e.preventDefault();
          onOpenDetail(j.job_id, e.currentTarget);
        }
      },
      /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "jt-ic" }, icon),
      /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "jt-main" }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "jt-lab" }, labelFor(j, fin)), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "jt-sub" }, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jt-kind" }, kindLabel(j.type)), queued ? /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jt-phase", title: "PixAI has accepted this generation and no worker has picked it up yet \u2014 it has not started rendering." }, "queued") : null, queued && typeof j.eta_seconds === "number" && isFinite(j.eta_seconds) ? /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jt-eta", title: "The queue wait PixAI predicted for this model when the job was accepted. An estimate of the WAIT, not a countdown, and not progress \u2014 PixAI reports no progress on a running task." }, "est. ", fmtDuration(j.eta_seconds), " wait") : null, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jt-when" }, ago(j.ts))), pct != null ? /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "jt-bar" }, /* @__PURE__ */ react_global_shim_default.createElement("i", { style: { width: pct + "%" } })) : null, showErr ? /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "jt-errmsg" }, j.error) : null),
      st === "done" && mid ? /* @__PURE__ */ react_global_shim_default.createElement("a", { className: "jt-thumb", href: "/next?image=" + encodeURIComponent(mid), onClick: (e) => e.stopPropagation() }, /* @__PURE__ */ react_global_shim_default.createElement("img", { src: "/thumbs/" + encodeURIComponent(mid) + ".jpg", alt: "" })) : null,
      fin ? /* @__PURE__ */ react_global_shim_default.createElement("button", { className: "jt-x", title: "Dismiss", onClick: stopTracking }, "\xD7") : /* @__PURE__ */ react_global_shim_default.createElement("button", { className: "jt-x jt-forcex", title: "Stop tracking this job -- does not cancel it on PixAI", onClick: stopTracking }, "Stop tracking")
    );
  }
  function Detail({ job, anchor, onClose }) {
    const [, tick] = useState(0);
    const [copied, setCopied] = useState(false);
    const running = (job.status || "running") === "running";
    const startedAt = job.started_at || job.ts || 0;
    useEffect(() => {
      if (!running) return void 0;
      const t = setInterval(() => tick((n) => n + 1), 1e3);
      return () => clearInterval(t);
    }, [running]);
    useEffect(() => {
      const onDoc = (e) => {
        const inDetail = e.target.closest && e.target.closest("#jt-detail");
        const inTray = e.target.closest && e.target.closest("#jobs-tray");
        if (!inDetail && !inTray) onClose();
      };
      const onKey = (e) => {
        if (e.key === "Escape") onClose();
      };
      document.addEventListener("click", onDoc);
      document.addEventListener("keydown", onKey);
      return () => {
        document.removeEventListener("click", onDoc);
        document.removeEventListener("keydown", onKey);
      };
    }, [onClose]);
    const r = anchor.getBoundingClientRect();
    const w = 264, gap = 10;
    let x = r.right + gap;
    if (x + w > window.innerWidth - 8) x = Math.max(8, r.left - w - gap);
    const y = Math.max(8, Math.min(r.top, window.innerHeight - 140));
    const spent = (running ? Date.now() / 1e3 : job.ts || startedAt) - startedAt;
    const copy = () => {
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(job.job_id || "").catch(() => {
          });
        }
      } catch {
      }
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    };
    return /* @__PURE__ */ react_global_shim_default.createElement("div", { id: "jt-detail", className: "open", "aria-hidden": "false", style: { left: x, top: y } }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "jd-row" }, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jd-k" }, "Task ID"), /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jd-v jd-id" }, job.job_id || ""), /* @__PURE__ */ react_global_shim_default.createElement("button", { className: "jd-copy" + (copied ? " copied" : ""), title: "Copy task ID", onClick: copy }, copied ? "copied!" : "copy")), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "jd-row" }, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jd-k" }, "Time Sent"), /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jd-v" }, fmtClock(startedAt))), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "jd-row" }, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jd-k" }, "Time Spent"), /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jd-v" }, fmtDuration(spent), running ? " so far" : "")), typeof job.eta_seconds === "number" && isFinite(job.eta_seconds) ? /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "jd-row" }, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jd-k" }, "Est. wait"), /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jd-v" }, fmtDuration(job.eta_seconds), " (PixAI, when queued)")) : null, typeof job.paid_credit === "number" && isFinite(job.paid_credit) ? (
      // typeof+isFinite, not truthiness: a card-covered gen genuinely costs 0 and must render
      // "0 credits", while an unknown cost shows NO row at all.
      /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "jd-row" }, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jd-k" }, "Cost"), /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jd-v" }, groupThousands(job.paid_credit), " credits"))
    ) : null);
  }
  function ActivityTray() {
    const [state, setState] = useState({ jobs: [], open: false });
    const [detailId, setDetailId] = useState(null);
    const anchorRef = useRef(null);
    useEffect(() => subscribe2(setState), []);
    const closeDetail = useCallback(() => {
      setDetailId(null);
      anchorRef.current = null;
    }, []);
    const toggleDetail = useCallback((jid, anchorEl) => {
      setDetailId((cur) => {
        if (cur === jid) {
          anchorRef.current = null;
          return null;
        }
        anchorRef.current = anchorEl;
        return jid;
      });
    }, []);
    const { jobs: jobs2, open: open2 } = state;
    const running = runningCount();
    const detailJob = detailId ? jobs2.find((j) => j.job_id === detailId) : null;
    useEffect(() => {
      if (detailId && !detailJob) closeDetail();
    }, [detailId, detailJob, closeDetail]);
    return createPortal(
      /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, /* @__PURE__ */ react_global_shim_default.createElement(
        "div",
        {
          id: "jobs-fab",
          className: (open2 ? "" : "show") + (running > 0 ? " busy" : ""),
          title: "Activity",
          onClick: () => openTray()
        },
        /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jf-dot" }),
        /* @__PURE__ */ react_global_shim_default.createElement("span", { id: "jobs-fab-badge", className: "jf-badge" }, running || ""),
        /* @__PURE__ */ react_global_shim_default.createElement("span", null, "Activity")
      ), /* @__PURE__ */ react_global_shim_default.createElement("div", { id: "jobs-tray", className: open2 ? "open" : "", "aria-label": "Job activity" }, /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "jt-head" }, /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jt-title" }, "\u25C9 Activity", jobs2.length ? /* @__PURE__ */ react_global_shim_default.createElement("span", { className: "jt-count" }, jobs2.length) : null), /* @__PURE__ */ react_global_shim_default.createElement("button", { className: "jt-hbtn", title: "Clear finished", onClick: () => clearFinished() }, "clear"), /* @__PURE__ */ react_global_shim_default.createElement("button", { className: "jt-hbtn", title: "Collapse", onClick: () => {
        closeTray();
        closeDetail();
      } }, "\u2013")), /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "jt-body" }, !jobs2.length ? /* @__PURE__ */ react_global_shim_default.createElement("div", { className: "jt-empty" }, /* @__PURE__ */ react_global_shim_default.createElement("img", { className: "jt-empty-nel", src: "/branding/mascots/trk_empty.png", alt: "", onError: (e) => e.currentTarget.remove() }), /* @__PURE__ */ react_global_shim_default.createElement("div", null, "The archive is quiet.", /* @__PURE__ */ react_global_shim_default.createElement("br", null), "Generations and syncs will appear here.")) : jobs2.map((j) => /* @__PURE__ */ react_global_shim_default.createElement(Row, { key: j.job_id, j, onDismiss: dismiss2, onOpenDetail: toggleDetail })))), detailJob && anchorRef.current ? /* @__PURE__ */ react_global_shim_default.createElement(Detail, { job: detailJob, anchor: anchorRef.current, onClose: closeDetail }) : null),
      document.body
    );
  }

  // ../gallery/src/notify/index.jsx
  var installed = false;
  function installNotify() {
    if (installed) return;
    installed = true;
    window.Toast = { show };
    window.Jobs = { track, register };
    window.JobsCard = {
      open: openTray,
      close: closeTray,
      refresh,
      dismiss: dismiss2,
      clearFinished
    };
    window.Ach = { check, replay };
    start();
    check();
  }
  function NotifyRoot() {
    return /* @__PURE__ */ react_global_shim_default.createElement(react_global_shim_default.Fragment, null, /* @__PURE__ */ react_global_shim_default.createElement(ToastHost, null), /* @__PURE__ */ react_global_shim_default.createElement(ActivityTray, null));
  }

  // master-storyboard.jsx
  var { useState: useState2, useEffect: useEffect2, useRef: useRef2, useCallback: useCallback2, useMemo: useMemo2 } = React;
  installNotify();
  var LV_TINTS = [
    "linear-gradient(150deg, #33236d 0%, #1b1733 100%)",
    "linear-gradient(150deg, #3a3460 0%, #17142b 100%)",
    "linear-gradient(150deg, #643aac 0%, #241f5b 100%)",
    "linear-gradient(150deg, #2a4a58 0%, #171f38 100%)",
    "linear-gradient(150deg, #4a3a6e 0%, #1f1a36 100%)",
    "linear-gradient(150deg, #3a2b63 0%, #191338 100%)"
  ];
  var STYLES = `
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
  var FIX_COLORS = { face: "#b692e6", hand: "#4fc99a" };
  var FIX_MIN_PX = 6;
  var FIX_MAX_BOXES = 20;
  var scaleFixBoxes = (boxes, imgEl) => {
    const scale = imgEl && imgEl.clientWidth ? imgEl.naturalWidth / imgEl.clientWidth : 1;
    return boxes.map((b) => ({
      x: Math.round(b.x * scale),
      y: Math.round(b.y * scale),
      width: Math.round(b.w * scale),
      height: Math.round(b.h * scale),
      tag: b.tag
    }));
  };
  var uid = () => Math.random().toString(36).slice(2, 9);
  var fmt3 = (s) => {
    s = Math.max(0, Math.round(s || 0));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };
  var elapsedLabel = (ms) => ms < 36e5 ? Math.round(ms / 6e4) + "m" : Math.round(ms / 36e4) / 10 + "h";
  var emptyFrame = () => ({ thumbId: "", source: "", desc: "", tag: "" });
  function useLocalToggle(key, defaultVal) {
    const [val, setVal] = useState2(() => {
      try {
        const raw = window.localStorage.getItem(key);
        return raw === null ? defaultVal : raw === "1";
      } catch (e) {
        return defaultVal;
      }
    });
    useEffect2(() => {
      try {
        window.localStorage.setItem(key, val ? "1" : "0");
      } catch (e) {
      }
    }, [key, val]);
    return [val, setVal];
  }
  var MOBILE_UI_KEY = "mg_loom_mobile_ui";
  var hasStore = typeof window !== "undefined" && window.storage;
  var PKEY = "storyboard:v2:project";
  var PPRE = "storyboard:v2:proj:";
  var ACTIVE_KEY = "storyboard:v2:active";
  var TPRE = "storyboard:v2:thumb:";
  var _storeWarned = false;
  function storeFailed(op, k, e) {
    console.error("storage " + op + " failed for " + k, e);
    if (!_storeWarned && typeof window !== "undefined" && window.Toast) {
      _storeWarned = true;
      window.Toast.show({
        kind: "err",
        sticky: true,
        title: "Storyboard storage is failing",
        msg: "Your recent changes may not be saved. Check the server, then reload before editing further."
      });
    }
  }
  async function sGetX(k) {
    try {
      const r = await window.storage.get(k);
      return { value: r ? r.value : null, failed: false };
    } catch (e) {
      storeFailed("read", k, e);
      return { value: null, failed: true };
    }
  }
  async function sGet(k) {
    return (await sGetX(k)).value;
  }
  async function sSet(k, v) {
    try {
      await window.storage.set(k, v, false);
      return true;
    } catch (e) {
      storeFailed("write", k, e);
      return false;
    }
  }
  async function sList(p) {
    try {
      const r = await window.storage.list(p, false);
      if (!r) return [];
      return (r.keys || []).map((k) => typeof k === "string" ? k : k.key);
    } catch (e) {
      storeFailed("list", p, e);
      return [];
    }
  }
  async function sDel(k) {
    try {
      await window.storage.delete(k);
      return true;
    } catch (e) {
      storeFailed("delete", k, e);
      return false;
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
/* L536: Image tab field-parity additions -- a 2-up row (Size/Custom W\xD7H, Mode/Count) and a
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
    useEffect2(() => {
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
    const [open2, setOpen2] = useState2(false);
    useEffect2(() => {
      if (!open2) return;
      const onKey = (ev) => {
        if (ev.key === "Escape") setOpen2(false);
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [open2]);
    return /* @__PURE__ */ React.createElement("div", { className: "sb-projwrap" }, /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-projbtn",
        onClick: () => setOpen2((v) => !v),
        title: "Export or restore this project",
        "aria-label": "Export"
      },
      "Export \u25BE"
    ), open2 && /* @__PURE__ */ React.createElement("div", { className: "sb-projveil", onClick: () => setOpen2(false) }), open2 && /* @__PURE__ */ React.createElement("div", { className: "sb-projpop" }, /* @__PURE__ */ React.createElement("div", { className: "sb-projpoph" }, "Export"), /* @__PURE__ */ React.createElement("button", { className: "sb-exportitem", onClick: () => {
      exportAll();
      setOpen2(false);
    } }, "Shot list ", /* @__PURE__ */ React.createElement("small", null, ".txt")), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-exportitem",
        onClick: () => {
          exportJSON();
          setOpen2(false);
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
          setOpen2(false);
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
            setOpen2(false);
          }
        }
      )
    )));
  }
  function LoomV2({
    project,
    setCard,
    setAssets,
    entries,
    durOf: durOf2,
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
    genFixState,
    setGenFixState,
    genFix,
    projectApi,
    playSequence,
    exportCut,
    batching,
    batchGenerate,
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
    refreshEstimate,
    batchTally,
    // draftCard/draftTarget/draftAttachedInfo used to be LoomV2's own useState triple (a
    // Generate-drawer draft with no shot selected yet, keyed "__draft__" everywhere else in
    // this file already keys genState/genImgState/etc). LIFTED to App() (mobile-board-view
    // pass, 2026-08-03) so a still-in-progress draft survives toggling to Mobile view and back
    // -- before this, the draft lived only in LoomV2's own component state, so unmounting it
    // (which is exactly what picking Mobile view does) silently discarded whatever the owner
    // had half-typed into Generate. Every reference below is unchanged from when these were
    // local useState calls -- only the declaration moved, so LoomV2's own behavior is identical.
    mobileUI,
    setMobileUI,
    draftCard,
    setDraftCard,
    draftTarget,
    setDraftTarget,
    draftAttachedInfo,
    setDraftAttachedInfo
  }) {
    const [bannerOpen, setBannerOpen] = useState2(true);
    const [tab, setTab] = useState2("Video");
    const [acct, setAcct] = useState2(null);
    const [handoff, setHandoff] = useState2("");
    const [deepFocus, setDeepFocus] = useState2(null);
    const [dfPalFor, setDfPalFor] = useState2(null);
    const [pickerOpen, setPickerOpen] = useState2(false);
    const [pickerKind, setPickerKind] = useState2("base");
    const [leftTab, setLeftTab] = useState2("cast");
    const [leftCollapsed, setLeftCollapsed] = useState2(false);
    const [leftClosing, setLeftClosing] = useState2(false);
    const [density, setDensity] = useState2("detailed");
    const [rightCollapsed, setRightCollapsed] = useState2(false);
    const [rightClosing, setRightClosing] = useState2(false);
    const leftCloseTimer = useRef2(null);
    const rightCloseTimer = useRef2(null);
    const closeLeftPanel = () => {
      setLeftClosing(true);
      clearTimeout(leftCloseTimer.current);
      leftCloseTimer.current = setTimeout(() => {
        setLeftCollapsed(true);
        setLeftClosing(false);
      }, 340);
    };
    const closeRightPanel = () => {
      setRightClosing(true);
      clearTimeout(rightCloseTimer.current);
      rightCloseTimer.current = setTimeout(() => {
        setRightCollapsed(true);
        setRightClosing(false);
      }, 340);
    };
    const openLeftPanel = () => {
      clearTimeout(leftCloseTimer.current);
      setLeftClosing(false);
      setLeftCollapsed(false);
    };
    const openRightPanel = () => {
      clearTimeout(rightCloseTimer.current);
      setRightClosing(false);
      setRightCollapsed(false);
    };
    useEffect2(() => () => {
      clearTimeout(leftCloseTimer.current);
      clearTimeout(rightCloseTimer.current);
    }, []);
    const [tlState, setTlState] = useState2("slim");
    const [tlDragH, setTlDragH] = useState2(null);
    const [palFor, setPalFor] = useState2(null);
    const [dzHover, setDzHover] = useState2(false);
    const [overrideClearedFlash, setOverrideClearedFlash] = useState2(false);
    const tlDrag = useRef2({ dragging: false, startY: 0, startH: 0 });
    useEffect2(() => {
      const prevOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = prevOverflow;
      };
    }, []);
    useEffect2(() => {
      fetch("/api/account").then((r) => r.json()).then(setAcct).catch(() => {
      });
    }, []);
    useEffect2(() => {
      if (!deepFocus) return;
      const onKey = (ev) => {
        if (ev.key === "Escape") setDeepFocus(null);
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [deepFocus]);
    useEffect2(() => {
      if (!pickerOpen) return;
      const onKey = (ev) => {
        if (ev.key === "Escape") setPickerOpen(false);
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [pickerOpen]);
    const [pickerMounted, setPickerMounted] = useState2(false);
    useEffect2(() => {
      if (pickerOpen) setPickerMounted(true);
    }, [pickerOpen]);
    const imgModelSeqRef = useRef2(0);
    const loraRange = useMemo2(() => {
      const L = window.MG_LORA;
      const t = String(imgModel && imgModel.model_type || "").toUpperCase();
      if (!L) return [-2, 2];
      return L.ranges && L.ranges[t] || L.fallback || [-2, 2];
    }, [imgModel]);
    useEffect2(() => {
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
    const onBasePick = useCallback2((row) => {
      setPickerOpen(false);
      const m = { model_id: row.model_id, title: row.title, preview_url: row.preview_url || "" };
      setImgModel(m);
      setModelDefaults(null);
      const mySeq = ++imgModelSeqRef.current;
      fetch("/api/model-version?model_id=" + encodeURIComponent(m.model_id) + "&all=1").then((r) => r.json()).then((d) => {
        if (mySeq !== imgModelSeqRef.current) return;
        const versions = d && d.versions || [], v = versions[0] || {};
        setImgModel((cur) => cur ? {
          ...cur,
          version_id: v.version_id || "",
          model_type: v.model_type || "",
          sampling_method: v.sampling_method || "",
          capabilities: v.capabilities || [],
          compatibility: v.compatibility || {},
          restrictions: v.restrictions || {},
          versions
        } : cur);
        const has = v.negative_prompt || v.sampling_steps || v.cfg_scale;
        setModelDefaults(has ? { negative_prompt: v.negative_prompt || "", sampling_steps: v.sampling_steps || null, cfg_scale: v.cfg_scale || null } : null);
        if (has) {
          setImgAdv((cur) => ({
            ...cur,
            negative: v.negative_prompt || cur.negative,
            steps: v.sampling_steps || cur.steps,
            cfg: v.cfg_scale || cur.cfg
          }));
        }
      }).catch(() => {
      });
    }, [setImgModel, setImgAdv, setModelDefaults]);
    const pickVersion = useCallback2((vid) => {
      if (!imgModel || !imgModel.versions) return;
      const v = imgModel.versions.find((x) => x.version_id === vid);
      if (!v) return;
      setImgModel((cur) => ({
        ...cur,
        version_id: v.version_id || "",
        model_type: v.model_type || "",
        sampling_method: v.sampling_method || "",
        capabilities: v.capabilities || [],
        compatibility: v.compatibility || {},
        restrictions: v.restrictions || {}
      }));
      const has = v.negative_prompt || v.sampling_steps || v.cfg_scale;
      setModelDefaults(has ? { negative_prompt: v.negative_prompt || "", sampling_steps: v.sampling_steps || null, cfg_scale: v.cfg_scale || null } : null);
      if (has) {
        setImgAdv((a) => ({
          ...a,
          negative: v.negative_prompt || a.negative,
          steps: v.sampling_steps || a.steps,
          cfg: v.cfg_scale || a.cfg
        }));
      }
    }, [imgModel, setImgModel, setImgAdv, setModelDefaults]);
    const onLoraPick = useCallback2((model, selected) => {
      setImgLoras((cur) => {
        const i = cur.findIndex((l) => l.model_id === model.model_id);
        if (!selected) return i < 0 ? cur : cur.filter((l) => l.model_id !== model.model_id);
        if (i < 0) return [...cur, model];
        const next = cur.slice();
        next[i] = model;
        return next;
      });
    }, [setImgLoras]);
    const imgCostRef = useRef2(null);
    const editCostRef = useRef2(null);
    const refCostRef = useRef2(null);
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
    const activeRef = useRef2(null);
    const projectRef = useRef2(project);
    projectRef.current = project;
    const thumbsRef = useRef2(thumbs);
    thumbsRef.current = thumbs;
    const genDrawerRef = useRef2(null);
    const promptDirtyRef = useRef2(false);
    const genTargetRef = useRef2(null);
    const lastActiveIdRef = useRef2(null);
    const bindGenDrawer = useCallback2((el) => {
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
              const resolve = (thumbId, source) => thumbId ? thumbsRef.current[thumbId] : source && (source.startsWith("http") || source.startsWith("data:") || isCatalogMediaId(source)) ? source : null;
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
          const resolve = (thumbId, source) => thumbId ? thumbsRef.current[thumbId] : source && (source.startsWith("http") || source.startsWith("data:") || isCatalogMediaId(source)) ? source : null;
          const composed = already ? null : shotText(a, projectRef.current, resolve);
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
    const [editSub, setEditSub] = useState2("edit");
    const [fixTag, setFixTag] = useState2("face");
    const [fixBoxes, setFixBoxes] = useState2([]);
    const fixImgRef = useRef2(null);
    const fixCanvasRef = useRef2(null);
    const fixDragRef = useRef2(null);
    const [genFixPrice, setGenFixPrice] = useState2({});
    useEffect2(() => {
      setFixBoxes([]);
    }, [active && active.c.id, active && active.c.openFrame && active.c.openFrame.mediaId]);
    const fixPaint = useCallback2(() => {
      const cvs = fixCanvasRef.current, img = fixImgRef.current;
      if (!cvs || !img) return;
      const w = img.clientWidth, h = img.clientHeight;
      if (!w || !h) return;
      if (cvs.width !== w || cvs.height !== h) {
        cvs.width = w;
        cvs.height = h;
      }
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
    useEffect2(() => {
      fixPaint();
    }, [fixPaint]);
    useEffect2(() => {
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
        x: Math.min(d.ox, p.x),
        y: Math.min(d.oy, p.y),
        w: Math.abs(p.x - d.ox),
        h: Math.abs(p.y - d.oy)
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
              kind: "err",
              title: "That's the limit",
              msg: "A Fix carries at most " + FIX_MAX_BOXES + " boxes \u2014 the rest would be dropped server-side."
            });
          }
        } else {
          setFixBoxes((old) => old.concat([{ x: d.x, y: d.y, w: d.w, h: d.h, tag: fixTag }]));
        }
      }
      fixPaint();
    };
    useEffect2(() => {
      if (tab !== "Edit" || editSub !== "fixer" || !active) return;
      const id = active.c.id;
      const src = active.c.openFrame && active.c.openFrame.mediaId;
      if (!src || !fixBoxes.length) {
        setGenFixPrice((s) => ({ ...s, [id]: null }));
        return;
      }
      setGenFixPrice((s) => ({ ...s, [id]: { ...s[id] || {}, loading: true } }));
      let live = true;
      const t = setTimeout(() => {
        fetch("/api/price", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: "fix", source: src, boxes: scaleFixBoxes(fixBoxes, fixImgRef.current) })
        }).then((r) => r.json()).then((pr) => {
          if (live) setGenFixPrice((s) => ({ ...s, [id]: { loading: false, pr } }));
        }).catch(() => {
          if (live) setGenFixPrice((s) => ({ ...s, [id]: { loading: false, pr: null } }));
        });
      }, 250);
      return () => {
        live = false;
        clearTimeout(t);
      };
    }, [tab, editSub, active && active.c.id, active && active.c.openFrame && active.c.openFrame.mediaId, fixBoxes]);
    const AF = artFilters_default;
    const [fcOpen, setFcOpen] = useState2(false);
    const [fcActive, setFcActive] = useState2(null);
    const [fcStrength, setFcStrength] = useState2(1);
    const [fcAngle, setFcAngle] = useState2(180);
    const fcStageRef = useRef2(null);
    const fcImgRef = useRef2(null);
    const openFilterCompare = () => {
      if (!active) return;
      setFcActive(active.c.filter || null);
      setFcStrength(active.c.filterStrength != null ? active.c.filterStrength : 1);
      setFcAngle(active.c.filterAngle != null ? active.c.filterAngle : 180);
      setFcOpen(true);
    };
    const closeFilterCompare = () => setFcOpen(false);
    const fcClear = () => {
      setFcActive(null);
      patch((cc) => ({ ...cc, filter: null }));
    };
    const fcSave = () => {
      patch((cc) => ({ ...cc, filter: fcActive, filterStrength: fcStrength, filterAngle: fcAngle }));
      setFcOpen(false);
    };
    useEffect2(() => {
      if (!fcOpen || !AF || !fcStageRef.current) return;
      const host = fcStageRef.current;
      AF.clearPreview(host);
      if (fcActive) AF.applyPreview(host, fcActive, { strength: fcStrength, angle: fcAngle });
      return () => {
        AF.clearPreview(host);
      };
    }, [fcOpen, fcActive, fcStrength, fcAngle, AF]);
    const editSrcMid = active.c.openFrame && active.c.openFrame.mediaId;
    const refMids = (project.assets || []).filter((a) => a.kind === "image" && a.mediaId).map((a) => a.mediaId);
    const refMidsKey = refMids.join(",");
    useEffect2(() => {
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
    useEffect2(() => {
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
    useEffect2(() => {
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
    const imgSrc = (thumbId, source) => thumbId ? thumbs[thumbId] : source && (source.startsWith("http") || source.startsWith("data:") || isCatalogMediaId(source)) ? source : null;
    const asRef = (d) => ({ media_id: d, thumb: isCatalogMediaId(d) ? "/thumbs/" + d + ".jpg" : d });
    const modeSendsRefs = (m) => usesCloseFrame(m) && m !== "FLF";
    const modeSendsLine = (m) => m === "FLF" ? "First & Last sends the start & end frames only \u2014 cast & refs here are for continuity/notes, not references" : "I2V sends the opening frame only \u2014 cast here is for continuity/notes, not references";
    const liveTagText = (liveTag, pastBudget, mode) => liveTag || (pastBudget ? modeSendsRefs(mode) ? "not sent" : "not cited" : "\u2014");
    const liveTagTitle = (liveTag, pastBudget, mode, code) => {
      const framesOnly = mode === "FLF" ? "First & Last sends only the start/end frames" : "I2V sends only the opening frame";
      if (liveTag) {
        return modeSendsRefs(mode) ? `Live slot in ${code} \u2014 numbered by position; this is what the composed prompt and the generator actually send, not the stored tag on the left` : `${code}'s composed-prompt citation \u2014 numbered by position. ${framesOnly}, so this picture is NOT attached to the generation; the number is only what the prompt text cites`;
      }
      if (pastBudget) {
        return modeSendsRefs(mode) ? `Past the reference limit for ${code} (6 images minus attached frames) \u2014 not sent` : `Past the citation limit for ${code} (6 images minus attached frames) \u2014 left out of the composed prompt. ${framesOnly}; cast/ref pictures are not attached either way`;
      }
      return `No picture resolved on ${code} \u2014 nothing to number`;
    };
    useEffect2(() => {
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
        payload.images = [active.c.openFrame, active.c.closeFrame].map((f) => {
          const d = resolvedImage(f, imgSrc);
          return d ? asRef(d) : null;
        });
      } else if (nextMode === "r2v") {
        const sp = shotPayload(active, project, imgSrc);
        payload.images = sp.images.map(asRef);
        const vids = (sp.video_refs || []).map(asRef);
        if (active.c.connect === "extend" && weavePrevEntry && weavePrevEntry.c.resultMid) {
          vids.push({ media_id: weavePrevEntry.c.resultMid, thumb: "/thumbs/" + weavePrevEntry.c.resultMid + ".jpg" });
        }
        payload.video_refs = vids;
      }
      if (!promptDirtyRef.current) payload.prompt = shotText(active, project, imgSrc);
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
      (active.c.openFrame || {}).mediaId,
      (active.c.openFrame || {}).thumbId,
      (active.c.openFrame || {}).source,
      (active.c.closeFrame || {}).mediaId,
      (active.c.closeFrame || {}).thumbId,
      (active.c.closeFrame || {}).source,
      active.c.title,
      project.look,
      project.draft,
      tab,
      active.c.promptOverride,
      active.c.promptOverrideText
    ]);
    useEffect2(() => {
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
          /* @__PURE__ */ React.createElement("div", { className: "lv-cmeta" }, /* @__PURE__ */ React.createElement("span", { className: "lv-mode" }, e.c.mode), /* @__PURE__ */ React.createElement("span", { className: "lv-dur" }, durOf2(e.c), "s"), (() => {
            const miss = castMissingImages(e, project, imgSrc);
            const over = castPastBudget(e, project, imgSrc);
            return /* @__PURE__ */ React.createElement(React.Fragment, null, miss.length ? /* @__PURE__ */ React.createElement(
              "span",
              {
                className: "lv-st warn",
                title: `No picture on this shot for ${miss.join(", ")} \u2014 they are cast here but cannot be referenced, so they are left out of the prompt. Add an image to use them.`
              },
              miss.length === 1 ? `${miss[0]}: no image` : `${miss.length} cast: no image`
            ) : null, over.length ? (
              /* Same mode split as liveTagText/liveTagTitle (round 3): "not
                 sent" is a reference-slot claim and only R2V/V2V send
                 reference slots. On FLF/I2V the trim is real but it trims the
                 prompt's CITATION list, not a payload -- nothing cast-shaped
                 was going to be sent either way, and a chip asserting
                 send-ness there is the round-2 mode-blindness bug wearing a
                 different hat. */
              /* @__PURE__ */ React.createElement(
                "span",
                {
                  className: "lv-st oob",
                  title: modeSendsRefs(e.c.mode) ? `Past the reference limit \u2014 not sent. PixAI takes 6 reference images and attached frames claim theirs first, so ${over.join(", ")} ${over.length === 1 ? "does" : "do"} not fit this shot. Remove a frame or another reference to include ${over.length === 1 ? "them" : "them all"}.` : `Past the citation limit \u2014 not cited. The composed prompt numbers at most 6 pictures (frames first), so ${over.join(", ")} ${over.length === 1 ? "gets" : "get"} no @imageN here. In ${e.c.mode} only the frame${e.c.mode === "FLF" ? "s are" : " is"} sent either way.`
                },
                over.length === 1 ? `${over[0]}: past ref limit \u2014 ${modeSendsRefs(e.c.mode) ? "not sent" : "not cited"}` : `${over.length} cast past ref limit \u2014 ${modeSendsRefs(e.c.mode) ? "not sent" : "not cited"}`
              )
            ) : null);
          })(), linked && /* @__PURE__ */ React.createElement("span", { className: "lv-st linked", title: "Opening frame matches the previous shot's closing frame \u2014 continuous across the cut" }, "linked"), e.c.imported && /* @__PURE__ */ React.createElement("span", { className: "lv-st imported", title: "Imported from your gallery -- no PixAI task backs this clip, so re-roll has nothing to redo" }, "imported"), /* @__PURE__ */ React.createElement(
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
          /* @__PURE__ */ React.createElement("div", { className: "lv-crow", onClick: (ev) => ev.stopPropagation(), onDoubleClick: (ev) => ev.stopPropagation() }, /* @__PURE__ */ React.createElement("button", { className: "lv-ico xs", onClick: () => moveCard(act.id, e.ci, -1), title: "Move up" }, "\u2191"), /* @__PURE__ */ React.createElement("button", { className: "lv-ico xs", onClick: () => moveCard(act.id, e.ci, 1), title: "Move down" }, "\u2193"), /* @__PURE__ */ React.createElement("button", { className: "lv-ico xs", onClick: () => dupCard(act.id, e.c), title: "Duplicate" }, "\u29C9"), /* @__PURE__ */ React.createElement(
            "button",
            {
              className: "lv-ico xs danger",
              title: "Delete",
              onClick: () => {
                if (window.confirm(`Delete shot ${e.code}${e.c.title ? ` \u2014 "${e.c.title}"` : ""}? This can't be undone.`)) delCard(act.id, e.c);
              }
            },
            "\u2715"
          ), project.acts.length > 1 && /* @__PURE__ */ React.createElement(
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
    ) : /* @__PURE__ */ React.createElement("div", { className: "lv-tlpreviewbox lv-ph" }, sel ? "This shot hasn't rendered yet." : "Select a shot to preview it here.")), /* @__PURE__ */ React.createElement("div", { className: "lv-tlreelzone" }, /* @__PURE__ */ React.createElement("div", { className: "lv-reel" }, entries.map((x, i) => {
      const tint = LV_TINTS[(x.ai * 3 + x.ci) % LV_TINTS.length];
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          key: i,
          className: "lv-seg" + (x.c.id === selShot ? " sel" : ""),
          style: {
            width: `${durOf2(x.c) / scale * 100}%`,
            backgroundImage: `repeating-linear-gradient(90deg, rgba(0,0,0,.32) 0px, rgba(0,0,0,.32) 1px, transparent 1px, transparent 25px), ${tint}`,
            backgroundSize: "25px 100%, 25px 100%",
            backgroundRepeat: "repeat-x, repeat-x"
          },
          title: `${x.code} ${x.c.title || ""}`,
          onClick: () => setSelShot(x.c.id)
        },
        /* @__PURE__ */ React.createElement("span", { className: "lv-segcode" }, x.code, " \xB7 ", durOf2(x.c), "s"),
        /* @__PURE__ */ React.createElement("span", { className: "lv-segbar " + x.c.status })
      );
    }), /* @__PURE__ */ React.createElement("div", { className: "lv-target", style: { left: `${project.target / scale * 100}%` } })), /* @__PURE__ */ React.createElement("div", { className: "lv-tlinfo" }, sel ? /* @__PURE__ */ React.createElement("span", null, /* @__PURE__ */ React.createElement("b", null, sel.code), " \xB7 ", sel.c.title || "untitled", " \xB7 ", sel.c.mode, " \xB7 ", durOf2(sel.c), "s") : /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "click a shot to select it \u2014 the whole workspace binds to it")))), /* @__PURE__ */ React.createElement("div", { className: "lv-tlhandle", onPointerDown: tlPointerDown, onPointerMove: tlPointerMove, onPointerUp: tlPointerUp, onPointerCancel: tlPointerUp }, /* @__PURE__ */ React.createElement("div", { className: "lv-tlgrip" })));
    const GEN_ICONS = [["Image", "\u2726"], ["Edit", "\u270E"], ["Reference", "\u{1F5BC}"], ["Video", "\u{1F3AC}"]];
    let gen;
    {
      const gs = genState[active.c.id];
      const busy = gs && gs.phase && gs.phase !== "done" && gs.phase !== "error" && gs.phase !== "paused";
      const patch2 = (fn) => {
        if (sel) setCard(sel.a.id, sel.c.id, fn);
        else setDraftCard(fn);
      };
      const appendTo = (field, term) => patch2((c) => ({ ...c, [field]: c[field] ? c[field] + ", " + term : term }));
      const selIdx = sel ? entries.findIndex((e) => e.c.id === sel.c.id) : -1;
      const prevEntry = selIdx > 0 ? entries[selIdx - 1] : null;
      const patchFrame = (key, fp) => patch2((c) => ({ ...c, [key]: { ...c[key], ...fp } }));
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
            onClick: () => patch2((c) => setShotConnect(c, k))
          },
          CONNECT[k].label
        ))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Prompt"), /* @__PURE__ */ React.createElement("textarea", { className: "lv-ta", value: active.c.prompt || "", onChange: (ev) => {
          if (active.c.promptOverride) {
            setOverrideClearedFlash(true);
            setTimeout(() => setOverrideClearedFlash(false), 1600);
          }
          patch2((c) => ({ ...clearPromptOverride(c), prompt: ev.target.value }));
        } }), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Camera ", /* @__PURE__ */ React.createElement("button", { className: "lv-termsbtn", onClick: () => togglePal("camera") }, "+ terms")), /* @__PURE__ */ React.createElement("input", { className: "lv-in", value: active.c.camera || "", placeholder: "e.g. slow push in, shallow DoF", onChange: (ev) => patch2((c) => ({ ...c, camera: ev.target.value })) }), palFor === "camera" && /* @__PURE__ */ React.createElement("div", { className: "lv-termspal" }, Object.entries(CAM_PALETTE).map(([grp, items]) => /* @__PURE__ */ React.createElement("div", { key: grp, className: "lv-termsgrp" }, /* @__PURE__ */ React.createElement("div", { className: "lv-termsgrpt" }, grp), items.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-minichip", onClick: () => appendTo("camera", t) }, t))))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Lighting ", /* @__PURE__ */ React.createElement("button", { className: "lv-termsbtn", onClick: () => togglePal("lighting") }, "+ terms")), /* @__PURE__ */ React.createElement("input", { className: "lv-in", value: active.c.lighting || "", placeholder: "e.g. moonlit, soft haze", onChange: (ev) => patch2((c) => ({ ...c, lighting: ev.target.value })) }), palFor === "lighting" && /* @__PURE__ */ React.createElement("div", { className: "lv-termspal" }, LIGHTING_PALETTE.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-minichip", onClick: () => appendTo("lighting", t) }, t))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Transition in ", /* @__PURE__ */ React.createElement("button", { className: "lv-termsbtn", onClick: () => togglePal("transIn") }, "+ terms")), /* @__PURE__ */ React.createElement("input", { className: "lv-in", value: active.c.transIn || "", placeholder: "e.g. cut, dissolve", onChange: (ev) => patch2((c) => ({ ...c, transIn: ev.target.value })) }), palFor === "transIn" && /* @__PURE__ */ React.createElement("div", { className: "lv-termspal" }, TRANS_PALETTE.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-minichip", onClick: () => patch2((c) => ({ ...c, transIn: t })) }, t))), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Transition out ", /* @__PURE__ */ React.createElement("button", { className: "lv-termsbtn", onClick: () => togglePal("transOut") }, "+ terms")), /* @__PURE__ */ React.createElement("input", { className: "lv-in", value: active.c.transOut || "", placeholder: "e.g. cut, dissolve", onChange: (ev) => patch2((c) => ({ ...c, transOut: ev.target.value })) }), palFor === "transOut" && /* @__PURE__ */ React.createElement("div", { className: "lv-termspal" }, TRANS_PALETTE.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-minichip", onClick: () => patch2((c) => ({ ...c, transOut: t })) }, t))), /* @__PURE__ */ React.createElement("div", { className: "lv-refline" }, (active.c.cast || []).length, " cast \xB7 ", (active.c.refs || []).length, " refs ", /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "(toggle cast in the Cast & assets tab; add extra image/video/audio refs directly below)")), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", alignItems: "center", justifyContent: "space-between", margin: "10px 0 2px" } }, active.c.promptOverride ? /* @__PURE__ */ React.createElement("span", { className: "lv-dim lv-override-badge", title: "Hand-edited override -- Camera/Lighting/cast/notes above are NOT composed into it. Re-sync to go back to auto-compose." }, "\u270E override active \u2014 fields above not woven in") : /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "\u2193 woven into the form below"), /* @__PURE__ */ React.createElement("button", { className: "lv-mini2", onClick: () => {
          promptDirtyRef.current = false;
          const composed = shotText({ ...active, c: { ...active.c, promptOverride: false } }, project, imgSrc);
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
        tabBody = /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Model"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lv-selrow", onClick: () => {
          setPickerKind("base");
          setPickerOpen(true);
        } }, imgModel && imgModel.preview_url ? /* @__PURE__ */ React.createElement("img", { className: "lv-selthumb", src: imgModel.preview_url, alt: "" }) : null, /* @__PURE__ */ React.createElement("span", { className: "lv-selname" }, imgModel ? imgModel.title : "none \u2014 browse models"), /* @__PURE__ */ React.createElement("span", { className: "lv-dim lv-selhint" }, "\u2630 browse")), imgModel && (imgModel.sampling_method || (imgModel.capabilities || []).length > 0) && /* @__PURE__ */ React.createElement("div", { className: "lv-caps" }, imgModel.sampling_method ? /* @__PURE__ */ React.createElement("span", { className: "lv-cap method" }, imgModel.sampling_method) : null, (imgModel.capabilities || []).map((c) => /* @__PURE__ */ React.createElement("span", { key: c, className: "lv-cap" }, c))), imgModel && imgModel.versions && imgModel.versions.length > 1 && /* @__PURE__ */ React.createElement(
          "select",
          {
            className: "lv-in lv-versel",
            value: imgModel.version_id || "",
            onChange: (ev) => pickVersion(ev.target.value),
            title: "This model's published releases -- PixAI defaults to the latest; pick another to generate against it instead",
            "aria-label": "Model version"
          },
          imgModel.versions.map((v) => /* @__PURE__ */ React.createElement("option", { key: v.version_id, value: v.version_id }, v.label || v.version_id))
        ), imgLoras.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "lv-loras" }, imgLoras.map((l) => {
          const incompat = loraIncompat(imgModel && imgModel.model_type, l.lora_base_type);
          return /* @__PURE__ */ React.createElement("div", { key: l.model_id, className: "lv-lchip" + (l.failed || incompat ? " failed" : "") }, /* @__PURE__ */ React.createElement(
            "span",
            {
              className: "lv-lnm",
              title: incompat ? l.title + " \u2014 needs a different base architecture than the one selected; remove it or switch the base" : l.title
            },
            l.title,
            !l.version_id ? l.failed ? " \u26A0" : " \u23F3" : incompat ? " \u26A0" : ""
          ), /* @__PURE__ */ React.createElement("span", { className: "lv-lw" }, /* @__PURE__ */ React.createElement(
            "input",
            {
              type: "range",
              step: "0.1",
              min: loraRange[0],
              max: loraRange[1],
              value: l.weight,
              title: "Weight \u2014 " + loraRange[0] + " to " + loraRange[1] + " for this base model" + (loraRange[0] < 0 ? "; negative subtracts this LoRA's influence" : ""),
              onChange: (ev) => {
                const w = Math.max(
                  loraRange[0],
                  Math.min(loraRange[1], +ev.target.value || 0)
                );
                setImgLoras((cur) => cur.map((x) => x.model_id === l.model_id ? { ...x, weight: w } : x));
              }
            }
          ), /* @__PURE__ */ React.createElement("b", null, (+l.weight).toFixed(1))), /* @__PURE__ */ React.createElement(
            "button",
            {
              type: "button",
              className: "lv-lrm",
              title: "Remove",
              onClick: () => {
                setImgLoras((cur) => cur.filter((x) => x.model_id !== l.model_id));
              }
            },
            "\xD7"
          ), l.versions && l.versions.length > 1 && /* @__PURE__ */ React.createElement(
            "select",
            {
              className: "lv-lorver",
              value: l.version_id || "",
              title: "This LoRA's published releases \u2014 PixAI defaults to the latest; pick another to use it instead",
              onChange: (ev) => {
                const vid = ev.target.value;
                const v = l.versions.find((x) => x.version_id === vid);
                if (!v) return;
                setImgLoras((cur) => cur.map((x) => x.model_id === l.model_id ? {
                  ...x,
                  version_id: v.version_id || "",
                  lora_base_type: v.lora_base_model_type || "",
                  trigger_words: v.trigger_words || "",
                  failed: !v.version_id
                } : x));
              }
            },
            l.versions.map((v) => /* @__PURE__ */ React.createElement("option", { key: v.version_id, value: v.version_id }, v.label || v.version_id))
          ));
        })), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lv-chip lv-loratoggle", onClick: () => {
          setPickerKind("lora");
          setPickerOpen(true);
        } }, "+ add LoRA"), acct && acct.lora_cap != null && /* @__PURE__ */ React.createElement("span", { className: "lv-loracap" + (overLoraCap(imgLoras, acct.lora_cap) ? " over" : "") }, imgLoras.length, " / ", acct.lora_cap, " LoRAs"), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Image prompt"), /* @__PURE__ */ React.createElement(
          "textarea",
          {
            className: "lv-ta",
            value: active.c.imgPrompt || "",
            placeholder: "describe the reference still (subject, pose, composition, light)\u2026",
            onChange: (ev) => patch2((c) => ({ ...c, imgPrompt: ev.target.value }))
          }
        ), sel && /* @__PURE__ */ React.createElement("button", { className: "lv-mini2", onClick: () => patch2((c) => ({ ...c, imgPrompt: [c.title, c.prompt, c.openFrame && c.openFrame.desc || "", c.lighting || ""].filter(Boolean).join(", ") })) }, "\u21A7 seed from shot description"), (() => {
          const compat = imgModel && imgModel.compatibility || {};
          const restr = imgModel && imgModel.restrictions || {};
          const negOff = compat.negativePrompt === false;
          const stepsOff = compat.samplingSteps === false;
          const cfgOff = compat.cfgScale === false;
          const stepsB = restr.samplingSteps || {};
          const cfgB = restr.cfgScale || {};
          const offTitle = "This model doesn\u2019t use this setting";
          return /* @__PURE__ */ React.createElement("details", null, /* @__PURE__ */ React.createElement("summary", { style: { cursor: "pointer", color: "var(--subtext)", fontSize: 11 } }, "Advanced"), /* @__PURE__ */ React.createElement(
            "textarea",
            {
              className: "lv-ta" + (negOff ? " cap-off" : ""),
              style: { marginTop: 5 },
              value: imgAdv.negative,
              placeholder: "lowres, text, watermark\u2026",
              disabled: negOff,
              title: negOff ? offTitle : "",
              onChange: (ev) => setImgAdv((a) => ({ ...a, negative: ev.target.value }))
            }
          ), /* @__PURE__ */ React.createElement("div", { className: "lv-row2" }, /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab", style: { margin: "6px 0 3px" } }, "Steps"), /* @__PURE__ */ React.createElement(
            "input",
            {
              className: "lv-in" + (stepsOff ? " cap-off" : ""),
              type: "number",
              min: stepsB.min != null ? stepsB.min : 1,
              max: stepsB.max != null ? stepsB.max : 150,
              step: "1",
              value: imgAdv.steps,
              disabled: stepsOff,
              title: stepsOff ? offTitle : "",
              onChange: (ev) => setImgAdv((a) => ({ ...a, steps: +ev.target.value || 25 }))
            }
          )), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab", style: { margin: "6px 0 3px" } }, "CFG scale"), /* @__PURE__ */ React.createElement(
            "input",
            {
              className: "lv-in" + (cfgOff ? " cap-off" : ""),
              type: "number",
              min: cfgB.min != null ? cfgB.min : 1,
              max: cfgB.max != null ? cfgB.max : 30,
              step: "0.5",
              value: imgAdv.cfg,
              disabled: cfgOff,
              title: cfgOff ? offTitle : "",
              onChange: (ev) => setImgAdv((a) => ({ ...a, cfg: +ev.target.value || 7 }))
            }
          ))), modelDefaults && /* @__PURE__ */ React.createElement("div", { className: "lv-advnote" }, /* @__PURE__ */ React.createElement("span", null, "\u2713 using this model's tuned preset"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lv-mini2", style: { margin: 0 }, onClick: () => {
            setImgAdv((a) => ({
              ...a,
              negative: modelDefaults.negative_prompt || a.negative,
              steps: modelDefaults.sampling_steps || a.steps,
              cfg: modelDefaults.cfg_scale || a.cfg
            }));
          } }, "\u21B6 reset")));
        })(), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Aspect"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 5, flexWrap: "wrap" } }, [
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
        ), " Prompt helper"), /* @__PURE__ */ React.createElement(CostBadge_default, { ref: imgCostRef, hint: "Pick a model and write a prompt to see the cost.", cardLabel: "a card" }), /* @__PURE__ */ React.createElement(
          "button",
          {
            className: "lv-go",
            disabled: busyI || !imgModel || !(active.c.imgPrompt || "").trim() || anyLoraUnresolved(imgLoras) || imgLoras.some((l) => loraIncompat(imgModel && imgModel.model_type, l.lora_base_type)) || overLoraCap(imgLoras, acct && acct.lora_cap),
            onClick: () => genImage(active)
          },
          busyI ? gi.msg || "generating\u2026" : anyLoraUnresolved(imgLoras) ? "waiting on LoRA\u2026" : imgLoras.some((l) => loraIncompat(imgModel && imgModel.model_type, l.lora_base_type)) ? "incompatible LoRA \u2014 remove or switch base" : overLoraCap(imgLoras, acct && acct.lora_cap) ? "remove " + (imgLoras.length - acct.lora_cap) + " LoRA" + (imgLoras.length - acct.lora_cap === 1 ? "" : "s") + " to continue" : "\u2726 Generate reference image"
        ), gi.phase === "error" && /* @__PURE__ */ React.createElement("div", { className: "lv-gerr" }, gi.msg), gi.mid && /* @__PURE__ */ React.createElement("div", { className: "lv-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + gi.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lv-route" }, /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "route \u2192"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gi.routed === "open" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeImg(routeTarget, "open", active.c.id) }, "open frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gi.routed === "close" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeImg(routeTarget, "close", active.c.id) }, "close frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gi.routed === "cast" ? " on" : ""), onClick: () => routeImg(routeTarget || active, "cast", active.c.id) }, "cast")), gi.routed && /* @__PURE__ */ React.createElement("div", { className: "lv-ok2" }, "\u2713 sent to ", gi.routed, sel ? " \xB7 it now feeds this shot's video gen" : "")));
      } else if (tab === "Edit") {
        const ge = genEditState[active.c.id] || {};
        const busyE = ge.phase === "submitting" || ge.phase === "running";
        const src = active.c.openFrame && active.c.openFrame.mediaId;
        const gf = genFixState[active.c.id] || {};
        const busyF = gf.phase === "submitting" || gf.phase === "running";
        const fixPriceEntry = genFixPrice[active.c.id];
        tabBody = /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { className: "lv-tabs", style: { marginBottom: 9 } }, /* @__PURE__ */ React.createElement("span", { className: "lv-tab" + (editSub === "edit" ? " on" : ""), onClick: () => setEditSub("edit") }, "Edit"), /* @__PURE__ */ React.createElement("span", { className: "lv-tab" + (editSub === "fixer" ? " on" : ""), onClick: () => setEditSub("fixer") }, "Fixer"), /* @__PURE__ */ React.createElement("span", { className: "lv-tab" + (editSub === "enhance" ? " on" : ""), onClick: () => setEditSub("enhance") }, "Enhance")), editSub === "edit" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Source \u2014 ", sel ? "this shot's" : "the draft's", " open frame"), src ? /* @__PURE__ */ React.createElement("img", { className: "lv-editsrc", src: "/thumbs/" + src + ".jpg", alt: "source" }) : /* @__PURE__ */ React.createElement("div", { className: "lv-ph" }, "No open-frame image yet \u2014 ", sel ? /* @__PURE__ */ React.createElement(React.Fragment, null, "route one from the ", /* @__PURE__ */ React.createElement("b", null, "Image"), " tab, or ") : null, "pick it into the open frame above."), /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Edit instruction"), /* @__PURE__ */ React.createElement(
          "textarea",
          {
            className: "lv-ta",
            value: active.c.editPrompt || "",
            placeholder: "e.g. make it night, add rain, warmer key light\u2026",
            onChange: (ev) => patch2((c) => ({ ...c, editPrompt: ev.target.value }))
          }
        ), /* @__PURE__ */ React.createElement(CostBadge_default, { ref: editCostRef, hint: "Add a source image and instruction to see the cost.", cardLabel: "an Edit card" }), /* @__PURE__ */ React.createElement("button", { className: "lv-go", disabled: busyE || !src, onClick: () => genEdit(active) }, busyE ? ge.msg || "editing\u2026" : "\u2726 Edit the open frame"), ge.phase === "error" && /* @__PURE__ */ React.createElement("div", { className: "lv-gerr" }, ge.msg), ge.mid && /* @__PURE__ */ React.createElement("div", { className: "lv-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + ge.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lv-route" }, /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "route \u2192"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (ge.routed === "open" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeGen(genEditState, setGenEditState, routeTarget, "open", active.c.id) }, "open frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (ge.routed === "close" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeGen(genEditState, setGenEditState, routeTarget, "close", active.c.id) }, "close frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (ge.routed === "cast" ? " on" : ""), onClick: () => routeGen(genEditState, setGenEditState, routeTarget || active, "cast", active.c.id) }, "cast")), ge.routed && /* @__PURE__ */ React.createElement("div", { className: "lv-ok2" }, "\u2713 sent to ", ge.routed))), editSub === "fixer" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Source \u2014 ", sel ? "this shot's" : "the draft's", " open frame"), src ? /* @__PURE__ */ React.createElement("div", { className: "lv-fixwrap" }, /* @__PURE__ */ React.createElement("img", { ref: fixImgRef, src: "/full/" + encodeURIComponent(src), alt: "source", onLoad: fixPaint, draggable: false }), /* @__PURE__ */ React.createElement(
          "canvas",
          {
            ref: fixCanvasRef,
            onPointerDown: fixDown,
            onPointerMove: fixMove,
            onPointerUp: fixUp,
            onPointerLeave: fixUp
          }
        )) : /* @__PURE__ */ React.createElement("div", { className: "lv-ph" }, "No open-frame image yet \u2014 ", sel ? /* @__PURE__ */ React.createElement(React.Fragment, null, "route one from the ", /* @__PURE__ */ React.createElement("b", null, "Image"), " tab, or ") : null, "pick it into the open frame above."), src && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lv-tabs", style: { marginTop: 8 } }, /* @__PURE__ */ React.createElement("span", { className: "lv-tab" + (fixTag !== "hand" ? " on" : ""), onClick: () => setFixTag("face") }, "Face"), /* @__PURE__ */ React.createElement("span", { className: "lv-tab" + (fixTag === "hand" ? " on" : ""), onClick: () => setFixTag("hand") }, "Hand"), /* @__PURE__ */ React.createElement("button", { className: "lv-mini2", disabled: !fixBoxes.length, onClick: () => setFixBoxes([]) }, "Clear", fixBoxes.length ? " " + fixBoxes.length : "")), /* @__PURE__ */ React.createElement("div", { className: "lv-fixhint" }, "Drag a box over the hand or face on the source.")), /* @__PURE__ */ React.createElement("div", { className: "lv-fixwarn" }, "A fix can't be card-covered \u2014 it always spends, and always asks first."), /* @__PURE__ */ React.createElement("div", { className: "lv-dim", style: { padding: "4px 2px" } }, fixPriceEntry && fixPriceEntry.loading ? "checking\u2026" : fixPriceEntry && fixPriceEntry.pr && typeof fixPriceEntry.pr.cost === "number" ? "\u2248 " + Number(fixPriceEntry.pr.cost).toLocaleString() + " credits \u2014 never card-covered" : !src ? "Pick a source image first." : !fixBoxes.length ? "Drag at least one box to see the cost." : "Couldn't verify the cost \u2014 a Fix always spends credits."), /* @__PURE__ */ React.createElement(
          "button",
          {
            className: "lv-go",
            disabled: busyF || !src || !fixBoxes.length,
            onClick: () => genFix(active, scaleFixBoxes(fixBoxes, fixImgRef.current))
          },
          busyF ? gf.msg || "fixing\u2026" : "\u2726 Fix " + fixTag
        ), gf.phase === "error" && /* @__PURE__ */ React.createElement("div", { className: "lv-gerr" }, gf.msg), gf.mid && /* @__PURE__ */ React.createElement("div", { className: "lv-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + gf.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lv-route" }, /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "route \u2192"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gf.routed === "open" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeGen(genFixState, setGenFixState, routeTarget, "open", active.c.id) }, "open frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gf.routed === "close" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeGen(genFixState, setGenFixState, routeTarget, "close", active.c.id) }, "close frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gf.routed === "cast" ? " on" : ""), onClick: () => routeGen(genFixState, setGenFixState, routeTarget || active, "cast", active.c.id) }, "cast")), gf.routed && /* @__PURE__ */ React.createElement("div", { className: "lv-ok2" }, "\u2713 sent to ", gf.routed))), editSub === "enhance" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Art filters \xB7 free, no generation"), /* @__PURE__ */ React.createElement("button", { className: "lv-openfilters", onClick: openFilterCompare }, "\u25D0 Open filters"), /* @__PURE__ */ React.createElement("div", { className: "lv-dim", style: { padding: "6px 2px" } }, "Gradient overlays, not AI \u2014 applied right in the browser: ", /* @__PURE__ */ React.createElement("b", { style: { color: "var(--text)" } }, "no credits, no request, works offline"), ".")));
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
            onChange: (ev) => patch2((c) => ({ ...c, refPrompt: ev.target.value }))
          }
        ), /* @__PURE__ */ React.createElement(CostBadge_default, { ref: refCostRef, hint: "Add references and a prompt to see the cost.", cardLabel: "an Edit card" }), /* @__PURE__ */ React.createElement("button", { className: "lv-go", disabled: busyR || !refs.length, onClick: () => genRef(active) }, busyR ? gr.msg || "generating\u2026" : "\u2726 Generate from references"), gr.phase === "error" && /* @__PURE__ */ React.createElement("div", { className: "lv-gerr" }, gr.msg), gr.mid && /* @__PURE__ */ React.createElement("div", { className: "lv-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + gr.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lv-route" }, /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "route \u2192"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gr.routed === "open" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeGen(genRefState, setGenRefState, routeTarget, "open", active.c.id) }, "open frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gr.routed === "close" ? " on" : ""), disabled: !routeTarget, onClick: () => routeTarget && routeGen(genRefState, setGenRefState, routeTarget, "close", active.c.id) }, "close frame"), /* @__PURE__ */ React.createElement("button", { className: "lv-routebtn" + (gr.routed === "cast" ? " on" : ""), onClick: () => routeGen(genRefState, setGenRefState, routeTarget || active, "cast", active.c.id) }, "cast")), gr.routed && /* @__PURE__ */ React.createElement("div", { className: "lv-ok2" }, "\u2713 sent to ", gr.routed)));
      } else tabBody = /* @__PURE__ */ React.createElement("div", { className: "lv-ph" }, "The ", /* @__PURE__ */ React.createElement("b", null, tab), " tab renders the shot on PixAI.");
      gen = /* @__PURE__ */ React.createElement("div", { className: "lv-gen" }, /* @__PURE__ */ React.createElement("div", { className: "lv-genhead" }, sel ? /* @__PURE__ */ React.createElement(React.Fragment, null, "\u2699 ", sel.code, " \xB7 ", sel.c.title || "untitled") : /* @__PURE__ */ React.createElement(React.Fragment, null, "\u2728 Draft generation ", /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "\u2014 generate freely, then route or attach it to a shot")), sel && /* @__PURE__ */ React.createElement(
        "button",
        {
          className: "lv-unbind",
          onClick: () => setSelShot(null),
          title: "Unbind this shot and go back to draft generation"
        },
        "\u2715 unbind"
      )), !sel && /* @__PURE__ */ React.createElement("div", { className: "lv-drafttarget" }, /* @__PURE__ */ React.createElement("label", { className: "lv-lab" }, "Route results into a shot ", /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, "(cast doesn't need one)")), /* @__PURE__ */ React.createElement("select", { className: "lv-sel", value: draftTarget, onChange: (ev) => setDraftTarget(ev.target.value) }, /* @__PURE__ */ React.createElement("option", { value: "" }, "\u2014 choose a shot \u2014"), entries.map((e) => /* @__PURE__ */ React.createElement("option", { key: e.c.id, value: e.c.id }, e.code, " \xB7 ", e.c.title || "untitled")))), (tab === "Reference" || tab === "Video" || tab === "Edit") && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lv-fhlabel" }, "FRAME HANDOFF \u2014 ", tab === "Video" ? "drives this shot\u2019s motion" : tab === "Edit" ? "edit source" : "still composition"), /* @__PURE__ */ React.createElement("div", { className: "lv-framehandoff" }, /* @__PURE__ */ React.createElement(
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
      ))), acct && /* @__PURE__ */ React.createElement("div", { className: "lv-bal" }, "\u26A1 ", acct.credits == null ? "\u2014" : acct.credits, " credits \xB7 ", acct.cards || 0, " card", acct.cards === 1 ? "" : "s", acct.claim_credits ? /* @__PURE__ */ React.createElement("span", { className: "lv-balclaim" }, " \xB7 +", acct.claim_credits, " claimable") : null), tabBody, /* @__PURE__ */ React.createElement(VideoDrawer_default, { ref: bindGenDrawer, loomCtx: true, style: { display: tab === "Video" ? "" : "none" } }), videoTrailer, /* @__PURE__ */ React.createElement(
        "div",
        {
          className: "lv-mpick-veil" + (pickerOpen ? " open" : ""),
          onClick: (ev) => {
            if (ev.target === ev.currentTarget) setPickerOpen(false);
          }
        },
        /* @__PURE__ */ React.createElement("div", { className: "lv-mpick-panel", role: "dialog", "aria-label": "Models and LoRAs" }, /* @__PURE__ */ React.createElement("div", { className: "lv-mpick-head" }, /* @__PURE__ */ React.createElement("span", { className: "t" }, "Models & LoRAs"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "x", onClick: () => setPickerOpen(false), "aria-label": "Close" }, "\xD7")), /* @__PURE__ */ React.createElement("div", { className: "lv-mpick-seg" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: pickerKind === "base" ? "on" : "", onClick: () => setPickerKind("base") }, "Models"), /* @__PURE__ */ React.createElement("button", { type: "button", className: pickerKind === "lora" ? "on" : "", onClick: () => setPickerKind("lora") }, "LoRAs")), /* @__PURE__ */ React.createElement("div", { className: "lv-mpick-body" }, pickerMounted && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
          ModelPicker,
          {
            kind: "base",
            visible: pickerKind === "base",
            value: imgModel,
            onPick: onBasePick,
            style: { display: pickerKind === "base" ? "flex" : "none" }
          }
        ), /* @__PURE__ */ React.createElement(
          ModelPicker,
          {
            kind: "lora",
            multi: true,
            baseType: imgModel && imgModel.model_type || "",
            visible: pickerKind === "lora",
            selected: imgLoras,
            onToggle: onLoraPick,
            style: { display: pickerKind === "lora" ? "flex" : "none" }
          }
        ))))
      ));
    }
    const castList = /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lv-castrow-h" }, "Cast & assets", sel ? /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, " \u2014 bound to ", sel.code) : null), sel && (() => {
      if (!modeSendsRefs(sel.c.mode)) {
        return /* @__PURE__ */ React.createElement(
          "div",
          {
            className: "lv-refbudget",
            title: `${sel.c.mode === "FLF" ? "A First & Last generation attaches only the Start and End frames" : "An I2V generation attaches only the opening frame"}. The @imageN numbers below are the composed prompt's citation numbering, not attachments.`
          },
          modeSendsLine(sel.c.mode)
        );
      }
      const b = refBudget(sel, project, imgSrc);
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          className: "lv-refbudget",
          title: `PixAI accepts 6 reference images per generation. ${b.frames ? `${b.frames === 1 ? "1 slot is" : `${b.frames} slots are`} held by ${sel.code}'s attached frame${b.frames === 1 ? "" : "s"}, leaving ${b.budget} for cast & image refs.` : "No frames attached, so all 6 are free for cast & image refs."} Anything past that is not sent.`
        },
        /* @__PURE__ */ React.createElement("span", { className: b.used > b.budget ? "lv-refbudget-over" : void 0 }, b.used, " of ", b.budget, " reference slot", b.budget === 1 ? "" : "s", " used"),
        b.frames ? /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, " \xB7 ", b.frames, " of 6 held by attached frame", b.frames === 1 ? "" : "s") : null
      );
    })(), /* @__PURE__ */ React.createElement("details", { className: "lv-look", open: !!(project.look || "").trim() }, /* @__PURE__ */ React.createElement("summary", null, "\u{1F3A8} Project look", (project.look || "").trim() ? "" : /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, " \u2014 a style line added to every shot")), /* @__PURE__ */ React.createElement(
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
      const liveTag = sel && inShot && as.kind === "image" ? positionTag(sel, project, imgSrc, as.id) : null;
      const pastBudget = sel && inShot && as.kind === "image" && !liveTag && !!resolvedImage(as, imgSrc);
      return /* @__PURE__ */ React.createElement("div", { key: as.id, className: "lv-assetrow" + (pastBudget ? " oob" : "") }, as.kind !== "audio" && /* @__PURE__ */ React.createElement(
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
      ), sel && inShot && as.kind === "image" && /* @__PURE__ */ React.createElement(
        "span",
        {
          className: "lv-livetag" + (pastBudget ? " oob" : ""),
          title: liveTagTitle(liveTag, pastBudget, sel.c.mode, sel.code)
        },
        liveTagText(liveTag, pastBudget, sel.c.mode)
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
      const liveTag = inShot && as.kind === "image" ? positionTag(sel, project, imgSrc, as.id) : null;
      const pastBudget = inShot && as.kind === "image" && !liveTag && !!resolvedImage(as, imgSrc);
      return /* @__PURE__ */ React.createElement(
        "div",
        {
          key: as.id,
          className: "lv-simplecard " + (inShot ? "on " : "") + (pastBudget ? "oob " : "") + (!sel ? "nosel" : ""),
          title: sel ? `Toggle into ${sel.code}` : "Select a shot on the board to toggle its cast",
          onClick: () => sel && setCard(sel.a.id, sel.c.id, (c) => ({ ...c, cast: (c.cast || []).includes(as.id) ? c.cast.filter((x) => x !== as.id) : [...c.cast || [], as.id] }))
        },
        src ? /* @__PURE__ */ React.createElement("img", { src, alt: "" }) : /* @__PURE__ */ React.createElement("span", { className: "lv-castph" }),
        /* @__PURE__ */ React.createElement("b", null, as.name || as.kind),
        /* @__PURE__ */ React.createElement("span", { className: "lv-dim" }, as.tag),
        liveTag ? /* @__PURE__ */ React.createElement("span", { className: "lv-livetag", title: liveTagTitle(liveTag, pastBudget, sel.c.mode, sel.code) }, liveTag) : pastBudget ? /* @__PURE__ */ React.createElement("span", { className: "lv-livetag oob", title: liveTagTitle(liveTag, pastBudget, sel.c.mode, sel.code) }, liveTagText(liveTag, pastBudget, sel.c.mode)) : null
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
    return /* @__PURE__ */ React.createElement("div", { className: "lv-overlay" + (deepFocus ? " lv-overlay-df" : "") }, /* @__PURE__ */ React.createElement("style", null, V2_STYLES), bannerOpen ? /* @__PURE__ */ React.createElement("div", { className: "lv-banner" }, /* @__PURE__ */ React.createElement("div", { className: "lv-banner-art" }), /* @__PURE__ */ React.createElement(
      "img",
      {
        className: "lv-banner-img",
        src: "/branding/banner-loom.png",
        alt: "",
        onError: (e) => e.currentTarget.remove()
      }
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: "lv-banner-hide",
        title: "Hide banner",
        onClick: () => setBannerOpen(false)
      },
      "\u2304 Hide banner"
    )) : null, /* @__PURE__ */ React.createElement("div", { className: "lv-top" }, !bannerOpen && /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: "lv-banner-show",
        title: "Show banner",
        onClick: () => setBannerOpen(true)
      },
      "\u{1F5BC} Banner"
    ), /* @__PURE__ */ React.createElement("span", { className: "lv-eyebrow" }, "The Loom \xB7 V2"), /* @__PURE__ */ React.createElement("span", { className: "lv-note" }, "Click a shot \u2192 it binds to Generate."), /* @__PURE__ */ React.createElement(ProjectSwitcher, { api: projectApi }), /* @__PURE__ */ React.createElement(
      "label",
      {
        className: "lv-draft" + (project.draft ? " on" : ""),
        title: "Draft mode renders every shot at the cheaper 'basic' quality \u2014 block out the animatic, then turn Draft off and re-generate the keepers at pro quality"
      },
      /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: !!project.draft, onChange: (e) => setDraft(e.target.checked) }),
      "\u26A1 Draft"
    ), /* @__PURE__ */ React.createElement(
      "label",
      {
        className: "lv-draft" + (mobileUI ? " on" : ""),
        title: "Switch to a phone-sized board/reel view \u2014 desktop chrome (panels, drawers) hides; your project and any in-progress draft are unaffected"
      },
      /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: !!mobileUI, onChange: (e) => setMobileUI(e.target.checked) }),
      "\u{1F4F1} Mobile view"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        onClick: () => {
          const pending = genDrawerRef.current && genDrawerRef.current.flushPromptEdit ? genDrawerRef.current.flushPromptEdit() : null;
          let liveEntries = entries;
          if (pending != null && activeRef.current) {
            const a = activeRef.current;
            const already = !!a.c.promptOverride;
            const composed = already ? null : shotText(a, project, imgSrc);
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
      "\u21E9 Render"
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
    })(), timelineDrawer, /* @__PURE__ */ React.createElement("div", { className: "lv-shell" }, /* @__PURE__ */ React.createElement("div", { className: "lv-rail" }, /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "lv-railbtn" + (!leftCollapsed && leftTab === "cast" ? " on" : ""),
        title: "Cast & assets",
        onClick: () => {
          setLeftTab("cast");
          openLeftPanel();
        }
      },
      "\u{1F464}"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "lv-railbtn" + (!leftCollapsed && leftTab === "footage" ? " on" : ""),
        title: "Footage",
        onClick: () => {
          setLeftTab("footage");
          openLeftPanel();
        }
      },
      "\u{1F3AC}"
    )), (!leftCollapsed || leftClosing) && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lv-backdrop" + (leftClosing ? " closing" : ""), onClick: closeLeftPanel }), /* @__PURE__ */ React.createElement("div", { className: "lv-panel left" + (leftClosing ? " closing" : "") + (leftTab === "cast" && density === "detailed" ? " wide" : "") }, /* @__PURE__ */ React.createElement("div", { className: "lv-sidehead" }, /* @__PURE__ */ React.createElement("div", { className: "lv-tabs lv-sidetabs" }, /* @__PURE__ */ React.createElement("span", { className: "lv-tab " + (leftTab === "cast" ? "on" : ""), onClick: () => setLeftTab("cast") }, "Cast & assets"), /* @__PURE__ */ React.createElement("span", { className: "lv-tab " + (leftTab === "footage" ? "on" : ""), onClick: () => setLeftTab("footage") }, "Footage")), /* @__PURE__ */ React.createElement("button", { className: "lv-col", onClick: closeLeftPanel, title: "collapse" }, "\u2039")), /* @__PURE__ */ React.createElement("div", { className: "lv-cast" }, leftTab === "cast" ? castList : footageList))), /* @__PURE__ */ React.createElement("div", { className: "lv-boardcol" }, board), (!rightCollapsed || rightClosing) && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lv-backdrop" + (rightClosing ? " closing" : ""), onClick: closeRightPanel }), /* @__PURE__ */ React.createElement("div", { className: "lv-panel right" + (rightClosing ? " closing" : "") }, /* @__PURE__ */ React.createElement("div", { className: "lv-sidehead" }, /* @__PURE__ */ React.createElement("button", { className: "lv-col", onClick: closeRightPanel, title: "collapse" }, "\u203A"), /* @__PURE__ */ React.createElement("div", { className: "lv-tabs lv-sidetabs" }, ["Image", "Edit", "Reference", "Video"].map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lv-tab " + (t === tab ? "on" : ""), onClick: () => setTab(t) }, t)))), gen)), /* @__PURE__ */ React.createElement("div", { className: "lv-rail" }, GEN_ICONS.map(([t, ic]) => /* @__PURE__ */ React.createElement(
      "button",
      {
        key: t,
        className: "lv-railbtn" + (!rightCollapsed && t === tab ? " on" : ""),
        title: t,
        onClick: () => {
          setTab(t);
          openRightPanel();
        }
      },
      ic
    )))), fcOpen && active && (() => {
      const c = active.c;
      const fcSrc = frameSrc(c.openFrame);
      const fcGroups = AF ? AF.groups() : [];
      const activeRec = fcActive && AF ? AF.get(fcActive) || {} : null;
      const activeName = activeRec ? activeRec.name || fcActive : null;
      return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lv-fc-veil", onClick: closeFilterCompare }), /* @__PURE__ */ React.createElement("div", { className: "lv-fc-host" }, /* @__PURE__ */ React.createElement("div", { className: "lv-fc-card" }, /* @__PURE__ */ React.createElement("div", { className: "lv-fc-head" }, /* @__PURE__ */ React.createElement("div", { className: "lv-fc-title" }, "\u25D0 Art filters"), /* @__PURE__ */ React.createElement("span", { className: "lv-dim", style: { flex: "1 1 auto" } }), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lv-col", onClick: closeFilterCompare, title: "Close" }, "\u2715")), !AF ? /* @__PURE__ */ React.createElement("div", { className: "lv-ph" }, "The art-filter library did not load on this page.") : /* @__PURE__ */ React.createElement("div", { className: "lv-fc-grid" }, /* @__PURE__ */ React.createElement("div", { className: "lv-fc-previewcol" }, /* @__PURE__ */ React.createElement("div", { className: "lv-fc-previewbox" }, fcSrc ? /* @__PURE__ */ React.createElement("img", { className: "lv-fc-img", src: fcSrc, alt: "original" }) : /* @__PURE__ */ React.createElement("div", { className: "lv-ph" }, "No open-frame image yet")), /* @__PURE__ */ React.createElement("div", { className: "lv-dim", style: { textAlign: "center", paddingTop: 6 } }, "Original")), /* @__PURE__ */ React.createElement("div", { className: "lv-fc-previewcol" }, /* @__PURE__ */ React.createElement("div", { className: "lv-fc-previewbox" }, /* @__PURE__ */ React.createElement("div", { className: "lv-fc-stage", ref: fcStageRef }, fcSrc ? /* @__PURE__ */ React.createElement("img", { ref: fcImgRef, className: "lv-fc-img", src: fcSrc, alt: "preview" }) : /* @__PURE__ */ React.createElement("div", { className: "lv-ph" }, "No open-frame image yet"))), /* @__PURE__ */ React.createElement("div", { className: "lv-dim", style: { textAlign: "center", paddingTop: 6 } }, "Preview \xB7 ", /* @__PURE__ */ React.createElement("b", { style: { color: "var(--text)" } }, activeName || "no filter"))), /* @__PURE__ */ React.createElement("div", { className: "lv-fc-side" }, fcGroups.map((g) => /* @__PURE__ */ React.createElement("div", { key: g.source }, /* @__PURE__ */ React.createElement("div", { className: "lv-fc-grouplabel" }, g.label), /* @__PURE__ */ React.createElement("div", { className: "lv-fc-swatchgrid" }, g.ids.map((id) => {
        const rec = AF.get(id) || {};
        return /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            key: id,
            className: "lv-fc-tile" + (fcActive === id ? " on" : ""),
            onClick: () => setFcActive((cur) => cur === id ? null : id),
            title: (rec.name || id) + " \xB7 free, applied in your browser" + (rec.note ? " \u2014 " + rec.note : "")
          },
          /* @__PURE__ */ React.createElement(
            "div",
            {
              className: "lv-fc-swatch",
              ref: (el) => {
                if (el && !el._mgafPainted) {
                  AF.renderSwatch(el, id);
                  el._mgafPainted = true;
                }
              }
            }
          ),
          /* @__PURE__ */ React.createElement("div", { className: "lv-fc-name" }, (rec.name || id).replace("Filter ", ""))
        );
      })))), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { className: "lv-lab", style: { margin: "4px 0" } }, "Strength ", /* @__PURE__ */ React.createElement("b", { style: { color: "var(--text)" } }, Number(fcStrength).toFixed(2))), /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "range",
          min: "0",
          max: "1",
          step: "0.05",
          className: "lv-fc-range",
          value: fcStrength,
          onChange: (ev) => setFcStrength(parseFloat(ev.target.value))
        }
      )), /* @__PURE__ */ React.createElement("div", null, /* @__PURE__ */ React.createElement("div", { className: "lv-lab", style: { margin: "4px 0" } }, "Angle ", /* @__PURE__ */ React.createElement("b", { style: { color: "var(--text)" } }, fcAngle, "\xB0")), /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "range",
          min: "0",
          max: "360",
          step: "1",
          className: "lv-fc-range",
          value: fcAngle,
          onChange: (ev) => setFcAngle(parseInt(ev.target.value, 10))
        }
      )), /* @__PURE__ */ React.createElement("div", { className: "lv-fc-btnrow" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "lv-mini2", onClick: fcClear }, "No filter"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lv-go", style: { padding: "9px 0" }, onClick: fcSave }, "Save")), /* @__PURE__ */ React.createElement("div", { className: "lv-dim", style: { textAlign: "center" } }, activeName || "No filter", " \xB7 nothing sent, nothing spent"))))));
    })(), deepFocus && (() => {
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
        const refLiveTag = r.kind === "image" ? positionTag(live, project, imgSrc, r.id) : null;
        const refPastBudget = r.kind === "image" && !refLiveTag && !!resolvedImage(r, imgSrc);
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
        )) : /* @__PURE__ */ React.createElement("div", { className: "sb-refprev" }, r.kind === "video" ? "\u{1F39E}" : "\u266A"), /* @__PURE__ */ React.createElement("div", { className: "sb-refbody" }, /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 7, alignItems: "center", flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("input", { className: "sb-tagin sb-mono", value: r.tag, onChange: (e) => setRef(live.a.id, c.id, r.id, { tag: e.target.value }) }), r.kind === "image" && /* @__PURE__ */ React.createElement(
          "span",
          {
            className: "lv-livetag" + (refPastBudget ? " oob" : ""),
            title: liveTagTitle(refLiveTag, refPastBudget, c.mode, live.code)
          },
          liveTagText(refLiveTag, refPastBudget, c.mode)
        ), /* @__PURE__ */ React.createElement("span", { className: "sb-hint" }, r.kind), /* @__PURE__ */ React.createElement("button", { className: "sb-ico", style: { marginLeft: "auto" }, onClick: () => delRef(live.a.id, c.id, r) }, "\u2715")), /* @__PURE__ */ React.createElement("input", { className: "sb-in", placeholder: "what to use it for (motion / camera / mood\u2026)", value: r.role, onChange: (e) => setRef(live.a.id, c.id, r.id, { role: e.target.value }) }), /* @__PURE__ */ React.createElement("input", { className: "sb-in", placeholder: "file name or URL", value: r.source, onChange: (e) => setRef(live.a.id, c.id, r.id, { source: e.target.value }) })));
      }), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 7, flexWrap: "wrap" } }, /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm ghost", onClick: () => addRef(live.a.id, c, "image") }, "+ Image"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm ghost", onClick: () => addRef(live.a.id, c, "video") }, "+ Video"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm ghost", onClick: () => addRef(live.a.id, c, "audio") }, "+ Audio"))), /* @__PURE__ */ React.createElement("div", { className: "sb-field" }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Music / audio cue ", /* @__PURE__ */ React.createElement("button", { className: "sb-ico", style: { fontSize: 11 }, onClick: () => setDfPalFor(dfPalFor === "audio" ? null : "audio") }, "\uFF0Bterms")), /* @__PURE__ */ React.createElement("input", { className: "sb-in", value: c.audioCue, onChange: (ev) => dfPatch((cc) => ({ ...cc, audioCue: ev.target.value })), placeholder: "track, beat sync, room tone\u2026" }), dfPalFor === "audio" && /* @__PURE__ */ React.createElement("div", { className: "sb-pal" }, AUDIO_PALETTE.map((t) => /* @__PURE__ */ React.createElement("button", { key: t, className: "sb-pchip sb-mono", onClick: () => dfAppend("audioCue", t) }, t)))), /* @__PURE__ */ React.createElement("div", { className: "sb-field" }, /* @__PURE__ */ React.createElement("label", { className: "sb-lab" }, "Notes"), /* @__PURE__ */ React.createElement("textarea", { className: "sb-ta", value: c.notes, onChange: (ev) => dfPatch((cc) => ({ ...cc, notes: ev.target.value })), placeholder: "blocking, continuity reminders\u2026" })), /* @__PURE__ */ React.createElement("div", { className: "sb-toolbar" }, /* @__PURE__ */ React.createElement("button", { className: "sb-btn amber sm", onClick: () => copyShot(live) }, "Copy shot")), /* @__PURE__ */ React.createElement("button", { className: "lv-go", onClick: () => {
        setSelShot(c.id);
        setDeepFocus(null);
      } }, "Select in Generate \u2192")));
    })());
  }
  var LOOM_MOBILE_STYLES = `
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

/* ---- Cast & assets sheet (bottom sheet, opened from Shot Detail's \u{1F465} button) ---- */
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
   "Select in Generate \u2192" button, matching the locked design's genOpen full-screen page. ---- */
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

/* ---- Review & trim (fifth increment, 2026-08-03) -- opened from the board's own \u25B6 badge
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
  function LoomMobile({
    project,
    entries,
    thumbs,
    genState,
    selShot,
    setSelShot,
    addCard,
    addAct,
    setDraft,
    mobileUI,
    setMobileUI,
    // Second increment (2026-08-03): Shot Detail (Deep Focus's mobile equivalent), the
    // Cast & assets sheet, and the Frame picker all need to actually MUTATE the project and
    // reach the real gallery picker -- setCard/setAssets/addRef/setRef/delRef (useShotMutations),
    // storeThumb (useProjectStore), and openPick/copyShot (App() itself) are the same real
    // functions LoomV2 already uses for its own Deep Focus/Cast&Assets/FrameSlot; threaded
    // straight through, nothing new invented.
    setCard,
    setAssets,
    addRef,
    setRef,
    delRef,
    storeThumb,
    openPick,
    copyShot,
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
    moveCard,
    dupCard,
    delCard,
    // Not read by earlier increments' Generate-less screens -- lifted to App() (see LoomV2's own
    // prop-list comment) and threaded through here so a still-in-progress draft already
    // survives toggling between this view and LoomV2.
    draftCard,
    setDraftCard,
    draftTarget,
    setDraftTarget,
    draftAttachedInfo,
    setDraftAttachedInfo,
    // Third increment (2026-08-03): Generate. Real, unmodified functions from
    // useGenerationPipeline -- generateShot (real submit: its own price-check + confirm +
    // /api/loom/generate + pollShot registration, the SAME function batchGenerate's per-card
    // loop already calls), priceShot (the SAME read-only /api/price check confirmSpend/
    // batchGenerate already use for a preview), and useExistingVideo (attach an
    // already-rendered gallery video as the finished clip, no generation, no spend -- already
    // wired to LoomV2's own board). No new submit call, no new pricing math, no forked spend
    // path: this screen is a new VIEW onto the exact same pipeline LoomV2 already drives.
    generateShot,
    priceShot,
    useExistingVideo,
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
    // Fixer -- seventh increment (2026-08-03). Same real hook-level state/function shape as
    // genEditState/genEdit above (useGenerationPipeline): genFixState is a plain cardId->
    // {phase,msg,mid,routed} dict, genFix is the real confirm-gated submit through the real
    // /api/fix endpoint. Threaded through for the first time here -- desktop's LoomV2 has no
    // Fixer tab of its own (out of this increment's scope), so only LoomMobile receives it.
    genFixState,
    setGenFixState,
    genFix
  }) {
    useEffect2(() => {
      const prevOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
      return () => {
        document.body.style.overflow = prevOverflow;
      };
    }, []);
    const imgSrc = (thumbId, source) => thumbId ? thumbs[thumbId] : source && (source.startsWith("http") || source.startsWith("data:") || isCatalogMediaId(source)) ? source : null;
    const frameSrc = (f) => f && f.thumbId ? thumbs[f.thumbId] : f && f.mediaId ? "/thumbs/" + f.mediaId + ".jpg" : null;
    const cardThumb = (c) => frameSrc(c.openFrame) || (c.resultMid ? "/thumbs/" + c.resultMid + ".jpg" : null);
    const AF = artFilters_default;
    const statusOf = (c) => {
      const gs = genState[c.id];
      const paused = gs && gs.phase === "paused";
      return paused ? "paused" : gs && gs.phase && gs.phase !== "done" && gs.phase !== "error" ? "wip" : c.status;
    };
    const [dfOpen, setDfOpen] = useState2(false);
    const [dfHandoff, setDfHandoff] = useState2("");
    const [castSheetOpen, setCastSheetOpen] = useState2(false);
    const [castSheetTab, setCastSheetTab] = useState2("cast");
    const [castSheetClosing, setCastSheetClosing] = useState2(false);
    const castSheetCloseTimer = useRef2(null);
    const closeCastSheet = () => {
      setCastSheetClosing(true);
      clearTimeout(castSheetCloseTimer.current);
      castSheetCloseTimer.current = setTimeout(() => {
        setCastSheetOpen(false);
        setCastSheetClosing(false);
      }, 280);
    };
    const [actionsOpen, setActionsOpen] = useState2(false);
    const [actionsClosing, setActionsClosing] = useState2(false);
    const actionsCloseTimer = useRef2(null);
    const [reviewOpen, setReviewOpen] = useState2(false);
    const [reviewPlaying, setReviewPlaying] = useState2(false);
    const [reviewCropping, setReviewCropping] = useState2(false);
    const [reviewDur, setReviewDur] = useState2(0);
    const [reviewCur, setReviewCur] = useState2(0);
    const reviewVidRef = useRef2(null);
    const reviewTrimTrackRef = useRef2(null);
    const reviewTrimDragRef = useRef2(null);
    const reviewCropDragRef = useRef2(false);
    const reviewScrubDragRef = useRef2(false);
    const [genOpen, setGenOpen] = useState2(false);
    const [genPalFor, setGenPalFor] = useState2(null);
    const [genOverrideFlash, setGenOverrideFlash] = useState2(false);
    const [genSubmitting, setGenSubmitting] = useState2(false);
    const [genPrice, setGenPrice] = useState2({});
    const [genTab, setGenTab] = useState2("Video");
    const [acct, setAcct] = useState2(null);
    useEffect2(() => {
      fetch("/api/account").then((r) => r.json()).then(setAcct).catch(() => {
      });
    }, []);
    const [pickerOpen, setPickerOpen] = useState2(false);
    const [pickerKind, setPickerKind] = useState2("base");
    const [pickerMounted, setPickerMounted] = useState2(false);
    const [pickerClosing, setPickerClosing] = useState2(false);
    const pickerCloseTimer = useRef2(null);
    const closePicker = () => {
      setPickerClosing(true);
      clearTimeout(pickerCloseTimer.current);
      pickerCloseTimer.current = setTimeout(() => {
        setPickerOpen(false);
        setPickerClosing(false);
      }, 280);
    };
    useEffect2(() => {
      if (pickerOpen) setPickerMounted(true);
    }, [pickerOpen]);
    useEffect2(() => {
      if (!pickerOpen) return;
      const onKey = (ev) => {
        if (ev.key === "Escape") closePicker();
      };
      window.addEventListener("keydown", onKey);
      return () => window.removeEventListener("keydown", onKey);
    }, [pickerOpen]);
    const imgModelSeqRef = useRef2(0);
    const loraRange = useMemo2(() => {
      const L = window.MG_LORA;
      const t = String(imgModel && imgModel.model_type || "").toUpperCase();
      if (!L) return [-2, 2];
      return L.ranges && L.ranges[t] || L.fallback || [-2, 2];
    }, [imgModel]);
    useEffect2(() => {
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
    const onBasePick = useCallback2((row) => {
      closePicker();
      const m = { model_id: row.model_id, title: row.title, preview_url: row.preview_url || "" };
      setImgModel(m);
      setModelDefaults(null);
      const mySeq = ++imgModelSeqRef.current;
      fetch("/api/model-version?model_id=" + encodeURIComponent(m.model_id) + "&all=1").then((r) => r.json()).then((d) => {
        if (mySeq !== imgModelSeqRef.current) return;
        const versions = d && d.versions || [], v = versions[0] || {};
        setImgModel((cur) => cur ? {
          ...cur,
          version_id: v.version_id || "",
          model_type: v.model_type || "",
          sampling_method: v.sampling_method || "",
          capabilities: v.capabilities || [],
          compatibility: v.compatibility || {},
          restrictions: v.restrictions || {},
          versions
        } : cur);
        const has = v.negative_prompt || v.sampling_steps || v.cfg_scale;
        setModelDefaults(has ? { negative_prompt: v.negative_prompt || "", sampling_steps: v.sampling_steps || null, cfg_scale: v.cfg_scale || null } : null);
        if (has) {
          setImgAdv((cur) => ({
            ...cur,
            negative: v.negative_prompt || cur.negative,
            steps: v.sampling_steps || cur.steps,
            cfg: v.cfg_scale || cur.cfg
          }));
        }
      }).catch(() => {
      });
    }, [setImgModel, setImgAdv, setModelDefaults]);
    const pickVersion = useCallback2((vid) => {
      if (!imgModel || !imgModel.versions) return;
      const v = imgModel.versions.find((x) => x.version_id === vid);
      if (!v) return;
      setImgModel((cur) => ({
        ...cur,
        version_id: v.version_id || "",
        model_type: v.model_type || "",
        sampling_method: v.sampling_method || "",
        capabilities: v.capabilities || [],
        compatibility: v.compatibility || {},
        restrictions: v.restrictions || {}
      }));
      const has = v.negative_prompt || v.sampling_steps || v.cfg_scale;
      setModelDefaults(has ? { negative_prompt: v.negative_prompt || "", sampling_steps: v.sampling_steps || null, cfg_scale: v.cfg_scale || null } : null);
      if (has) {
        setImgAdv((a) => ({
          ...a,
          negative: v.negative_prompt || a.negative,
          steps: v.sampling_steps || a.steps,
          cfg: v.cfg_scale || a.cfg
        }));
      }
    }, [imgModel, setImgModel, setImgAdv, setModelDefaults]);
    const onLoraPick = useCallback2((model, selected) => {
      setImgLoras((cur) => {
        const i = cur.findIndex((l) => l.model_id === model.model_id);
        if (!selected) return i < 0 ? cur : cur.filter((l) => l.model_id !== model.model_id);
        if (i < 0) return [...cur, model];
        const next = cur.slice();
        next[i] = model;
        return next;
      });
    }, [setImgLoras]);
    const modeSendsRefs = (m) => usesCloseFrame(m) && m !== "FLF";
    const modeSendsLine = (m) => m === "FLF" ? "First & Last sends the start & end frames only \u2014 cast & refs here are for continuity/notes, not references" : "I2V sends the opening frame only \u2014 cast here is for continuity/notes, not references";
    const liveTagText = (liveTag, pastBudget, mode) => liveTag || (pastBudget ? modeSendsRefs(mode) ? "not sent" : "not cited" : "\u2014");
    const liveTagTitle = (liveTag, pastBudget, mode, code) => {
      const framesOnly = mode === "FLF" ? "First & Last sends only the start/end frames" : "I2V sends only the opening frame";
      if (liveTag) {
        return modeSendsRefs(mode) ? `Live slot in ${code} \u2014 numbered by position; this is what the composed prompt and the generator actually send` : `${code}'s composed-prompt citation \u2014 numbered by position. ${framesOnly}, so this picture is not attached to the generation`;
      }
      if (pastBudget) {
        return modeSendsRefs(mode) ? `Past the reference limit for ${code} (6 images minus attached frames) \u2014 not sent` : `Past the citation limit for ${code} \u2014 left out of the composed prompt. ${framesOnly} either way`;
      }
      return `No picture resolved on ${code} \u2014 nothing to number`;
    };
    const total = entries.reduce((s, x) => s + durOf(x.c), 0);
    const tickFrac = total > 0 ? Math.min(1, (project.target || 0) / total) : 0;
    const selIdx = entries.findIndex((x) => x.c.id === selShot);
    let selFrac = null;
    if (selIdx >= 0 && total > 0) {
      let cum = 0;
      for (let i = 0; i < selIdx; i++) cum += durOf(entries[i].c) || 1;
      selFrac = (cum + (durOf(entries[selIdx].c) || 1) / 2) / total;
    }
    const [scrubbing, setScrubbing] = useState2(false);
    const [scrubFrac, setScrubFrac] = useState2(0);
    const [scrubIdx, setScrubIdx] = useState2(null);
    const fracAt = (e) => {
      const r = e.currentTarget.getBoundingClientRect();
      return r.width ? Math.max(0, Math.min(0.9999, (e.clientX - r.left) / r.width)) : 0;
    };
    const idxAtFrac = (frac) => {
      if (!entries.length || !total) return null;
      const t = frac * total;
      let cum = 0;
      for (let i = 0; i < entries.length; i++) {
        cum += durOf(entries[i].c) || 1;
        if (t < cum) return i;
      }
      return entries.length - 1;
    };
    const scrubTo = (e) => {
      const frac = fracAt(e);
      setScrubbing(true);
      setScrubFrac(frac);
      setScrubIdx(idxAtFrac(frac));
    };
    const onReelDown = (e) => {
      if (!entries.length) return;
      try {
        e.currentTarget.setPointerCapture(e.pointerId);
      } catch (err) {
      }
      scrubTo(e);
    };
    const onReelMove = (e) => {
      if (scrubbing) scrubTo(e);
    };
    const onReelUp = () => {
      setScrubbing(false);
      if (scrubIdx != null && entries[scrubIdx]) setSelShot(entries[scrubIdx].c.id);
    };
    const onReelLeave = () => setScrubbing(false);
    const handleFrac = scrubbing ? scrubFrac : selFrac;
    const scrubEntry = scrubIdx != null ? entries[scrubIdx] : null;
    const posStyle = (frac) => ({ left: `calc(16px + (100% - 32px) * ${frac})` });
    const dfLive = dfOpen ? entries.find((x) => x.c.id === selShot) : null;
    if (dfOpen && !dfLive) {
      setDfOpen(false);
    }
    const dfSelIdx = dfLive ? entries.findIndex((x) => x.c.id === dfLive.c.id) : -1;
    const dfPrevEntry = dfSelIdx > 0 ? entries[dfSelIdx - 1] : null;
    const dfPatch = (fn) => dfLive && setCard(dfLive.a.id, dfLive.c.id, fn);
    const dfPatchFrame = (key, fp) => dfPatch((cc) => ({ ...cc, [key]: { ...cc[key], ...fp } }));
    const dfInheritPrev = () => {
      if (!dfPrevEntry) return;
      const rmid = dfPrevEntry.c.resultMid;
      if (rmid) {
        setDfHandoff("wip");
        fetch("/api/loom/handoff", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_media_id: rmid, trim_out: dfPrevEntry.c.trimOut })
        }).then((r) => r.json()).then((d) => {
          if (d.error || !d.frame_media_id) {
            setDfHandoff("err");
            return;
          }
          setDfHandoff("");
          dfPatchFrame("openFrame", {
            mediaId: d.frame_media_id,
            thumbId: "",
            source: "",
            desc: "handed off from " + (dfPrevEntry.code || "prev shot")
          });
        }).catch(() => setDfHandoff("err"));
      } else {
        dfPatchFrame("openFrame", { ...dfPrevEntry.c.closeFrame });
      }
    };
    const dfPickFootage = (mid, code) => {
      if (!dfLive) return;
      const tag = nextTag(dfLive.c.refs.filter((r) => r.kind === "video"), "@video");
      const newRef = { ...buildNewRef("video", uid()), tag, source: String(mid), role: "footage from " + code };
      setCard(dfLive.a.id, dfLive.c.id, (c) => ({ ...c, refs: [...c.refs, newRef] }));
    };
    const castBudget = dfLive ? refBudget(dfLive, project, imgSrc) : null;
    const finishedShots = entries.filter((e) => e.c.resultMid);
    const reviewLive = reviewOpen ? entries.find((x) => x.c.id === selShot) : null;
    if (reviewOpen && !reviewLive) {
      setReviewOpen(false);
    }
    const reviewPatch = (fn) => reviewLive && setCard(reviewLive.a.id, reviewLive.c.id, fn);
    const closeReview = () => {
      setReviewOpen(false);
      setReviewPlaying(false);
      setReviewCropping(false);
    };
    const actionsLive = actionsOpen ? entries.find((x) => x.c.id === selShot) : null;
    if (actionsOpen && !actionsLive) {
      setActionsOpen(false);
    }
    const closeActions = () => {
      setActionsClosing(true);
      clearTimeout(actionsCloseTimer.current);
      actionsCloseTimer.current = setTimeout(() => {
        setActionsOpen(false);
        setActionsClosing(false);
      }, 280);
    };
    const genTogglePal = (which) => setGenPalFor((p) => p === which ? null : which);
    const genAppendTo = (field, term) => dfPatch((cc) => ({ ...cc, [field]: cc[field] ? cc[field] + ", " + term : term }));
    useEffect2(() => {
      if (!genOpen || !dfLive) return;
      const id = dfLive.c.id;
      const payload = shotPayload(dfLive, project, imgSrc);
      if (!payload.hasInput) {
        setGenPrice((s) => ({ ...s, [id]: { loading: false, pr: null, noInput: true } }));
        return;
      }
      setGenPrice((s) => ({ ...s, [id]: { ...s[id] || {}, loading: true, noInput: false } }));
      let live = true;
      const t = setTimeout(() => {
        priceShot(dfLive).then((pr) => {
          if (live) setGenPrice((s) => ({ ...s, [id]: { loading: false, pr, noInput: false } }));
        });
      }, 300);
      return () => {
        live = false;
        clearTimeout(t);
      };
    }, [
      genOpen,
      dfLive && dfLive.c.id,
      dfLive && dfLive.c.mode,
      dfLive && dfLive.c.duration,
      dfLive && dfLive.c.connect,
      dfLive && dfLive.c.audioGen,
      dfLive && dfLive.c.audioLanguage,
      dfLive && dfLive.c.prompt,
      dfLive && dfLive.c.promptOverride,
      dfLive && dfLive.c.promptOverrideText,
      dfLive && JSON.stringify(dfLive.c.cast),
      dfLive && JSON.stringify(dfLive.c.refs),
      project.draft,
      project.assets,
      dfLive && (dfLive.c.openFrame || {}).mediaId,
      dfLive && (dfLive.c.openFrame || {}).thumbId,
      dfLive && (dfLive.c.openFrame || {}).source,
      dfLive && (dfLive.c.closeFrame || {}).mediaId,
      dfLive && (dfLive.c.closeFrame || {}).thumbId,
      dfLive && (dfLive.c.closeFrame || {}).source
    ]);
    const genSubmit = async () => {
      if (!dfLive || genSubmitting) return;
      setGenSubmitting(true);
      let r;
      try {
        r = await generateShot(dfLive);
      } finally {
        setGenSubmitting(false);
      }
      if (r && r.ok) {
        setGenOpen(false);
        setDfOpen(false);
      }
    };
    const editSrcMid = dfLive && dfLive.c.openFrame && dfLive.c.openFrame.mediaId;
    const refMids = (project.assets || []).filter((a) => a.kind === "image" && a.mediaId).map((a) => a.mediaId);
    const refMidsKey = refMids.join(",");
    const [imgPrice, setImgPrice] = useState2({});
    const [editPrice, setEditPrice] = useState2({});
    const [refPrice, setRefPrice] = useState2({});
    useEffect2(() => {
      if (!genOpen || genTab !== "Image" || !dfLive) return;
      const id = dfLive.c.id;
      const prompt = (dfLive.c.imgPrompt || "").trim();
      if (!imgModel || !prompt || anyLoraUnresolved(imgLoras)) {
        setImgPrice((s) => ({ ...s, [id]: null }));
        return;
      }
      setImgPrice((s) => ({ ...s, [id]: { ...s[id] || {}, loading: true } }));
      let live = true;
      const t = setTimeout(() => {
        fetch("/api/price", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(buildImgGenBody(imgModel, imgLoras, imgAdv, prompt))
        }).then((r) => r.json()).then((pr) => {
          if (live) setImgPrice((s) => ({ ...s, [id]: { loading: false, pr } }));
        }).catch(() => {
          if (live) setImgPrice((s) => ({ ...s, [id]: { loading: false, pr: null } }));
        });
      }, 250);
      return () => {
        live = false;
        clearTimeout(t);
      };
    }, [genOpen, genTab, dfLive && dfLive.c.id, dfLive && dfLive.c.imgPrompt, imgModel, imgLoras, imgAdv]);
    useEffect2(() => {
      if (!genOpen || genTab !== "Edit" || !dfLive) return;
      const id = dfLive.c.id;
      const instruction = (dfLive.c.editPrompt || "").trim();
      if (!editSrcMid || !instruction) {
        setEditPrice((s) => ({ ...s, [id]: null }));
        return;
      }
      setEditPrice((s) => ({ ...s, [id]: { ...s[id] || {}, loading: true } }));
      let live = true;
      const t = setTimeout(() => {
        fetch("/api/price", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: "edit", source: editSrcMid, instruction, edit_model: "edit-pro" })
        }).then((r) => r.json()).then((pr) => {
          if (live) setEditPrice((s) => ({ ...s, [id]: { loading: false, pr } }));
        }).catch(() => {
          if (live) setEditPrice((s) => ({ ...s, [id]: { loading: false, pr: null } }));
        });
      }, 250);
      return () => {
        live = false;
        clearTimeout(t);
      };
    }, [genOpen, genTab, dfLive && dfLive.c.id, dfLive && dfLive.c.editPrompt, editSrcMid]);
    useEffect2(() => {
      if (!genOpen || genTab !== "Reference" || !dfLive) return;
      const id = dfLive.c.id;
      const prompt = (dfLive.c.refPrompt || "").trim();
      if (!refMids.length || !prompt) {
        setRefPrice((s) => ({ ...s, [id]: null }));
        return;
      }
      setRefPrice((s) => ({ ...s, [id]: { ...s[id] || {}, loading: true } }));
      let live = true;
      const t = setTimeout(() => {
        fetch("/api/price", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: "edit", source: refMids[0], sources: refMids, instruction: prompt, edit_model: "reference-pro" })
        }).then((r) => r.json()).then((pr) => {
          if (live) setRefPrice((s) => ({ ...s, [id]: { loading: false, pr } }));
        }).catch(() => {
          if (live) setRefPrice((s) => ({ ...s, [id]: { loading: false, pr: null } }));
        });
      }, 250);
      return () => {
        live = false;
        clearTimeout(t);
      };
    }, [genOpen, genTab, dfLive && dfLive.c.id, dfLive && dfLive.c.refPrompt, refMidsKey]);
    const priceLine = (priceState, id, noInputMsg) => {
      const p = priceState[id];
      if (!p) return noInputMsg;
      if (p.loading) return "checking\u2026";
      const tally = p.pr ? tallyPrices([p.pr]) : null;
      return tally ? formatCostEstimate(tally) : "\u2014";
    };
    const priceTitle = (priceState, id) => {
      const p = priceState[id];
      const tally = p && p.pr ? tallyPrices([p.pr]) : null;
      return tally ? costTooltip(tally) : "";
    };
    const [editSub, setEditSub] = useState2("edit");
    const [fixTag, setFixTag] = useState2("face");
    const [fixBoxes, setFixBoxes] = useState2([]);
    const fixImgRef = useRef2(null);
    const fixCanvasRef = useRef2(null);
    const fixDragRef = useRef2(null);
    const [genFixPrice, setGenFixPrice] = useState2({});
    useEffect2(() => {
      setFixBoxes([]);
    }, [dfLive && dfLive.c.id, dfLive && dfLive.c.openFrame && dfLive.c.openFrame.mediaId]);
    const fixPaint = useCallback2(() => {
      const cvs = fixCanvasRef.current, img = fixImgRef.current;
      if (!cvs || !img) return;
      const w = img.clientWidth, h = img.clientHeight;
      if (!w || !h) return;
      if (cvs.width !== w || cvs.height !== h) {
        cvs.width = w;
        cvs.height = h;
      }
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
    useEffect2(() => {
      fixPaint();
    }, [fixPaint]);
    useEffect2(() => {
      const onResize = () => fixPaint();
      window.addEventListener("resize", onResize);
      return () => window.removeEventListener("resize", onResize);
    }, [fixPaint]);
    const fixRel = (e) => {
      const r = fixCanvasRef.current.getBoundingClientRect();
      return { x: e.clientX - r.left, y: e.clientY - r.top };
    };
    const fixDown = (e) => {
      if (e.button !== 0 || !(dfLive && dfLive.c.openFrame && dfLive.c.openFrame.mediaId)) return;
      const p = fixRel(e);
      fixDragRef.current = { x: p.x, y: p.y, w: 0, h: 0, ox: p.x, oy: p.y };
      try {
        e.currentTarget.setPointerCapture(e.pointerId);
      } catch (err) {
      }
      e.preventDefault();
    };
    const fixMove = (e) => {
      if (!fixDragRef.current) return;
      const p = fixRel(e);
      const d = fixDragRef.current;
      fixDragRef.current = {
        ...d,
        x: Math.min(d.ox, p.x),
        y: Math.min(d.oy, p.y),
        w: Math.abs(p.x - d.ox),
        h: Math.abs(p.y - d.oy)
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
              kind: "err",
              title: "That's the limit",
              msg: "A Fix carries at most " + FIX_MAX_BOXES + " boxes \u2014 the rest would be dropped server-side."
            });
          }
        } else {
          setFixBoxes((old) => old.concat([{ x: d.x, y: d.y, w: d.w, h: d.h, tag: fixTag }]));
        }
      }
      fixPaint();
    };
    useEffect2(() => {
      if (!genOpen || genTab !== "Edit" || editSub !== "fixer" || !dfLive) return;
      const id = dfLive.c.id;
      const src = dfLive.c.openFrame && dfLive.c.openFrame.mediaId;
      if (!src || !fixBoxes.length) {
        setGenFixPrice((s) => ({ ...s, [id]: null }));
        return;
      }
      setGenFixPrice((s) => ({ ...s, [id]: { ...s[id] || {}, loading: true } }));
      let live = true;
      const t = setTimeout(() => {
        fetch("/api/price", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: "fix", source: src, boxes: scaleFixBoxes(fixBoxes, fixImgRef.current) })
        }).then((r) => r.json()).then((pr) => {
          if (live) setGenFixPrice((s) => ({ ...s, [id]: { loading: false, pr } }));
        }).catch(() => {
          if (live) setGenFixPrice((s) => ({ ...s, [id]: { loading: false, pr: null } }));
        });
      }, 250);
      return () => {
        live = false;
        clearTimeout(t);
      };
    }, [genOpen, genTab, editSub, dfLive && dfLive.c.id, dfLive && dfLive.c.openFrame && dfLive.c.openFrame.mediaId, fixBoxes]);
    const [fcOpen, setFcOpen] = useState2(false);
    const [fcActive, setFcActive] = useState2(null);
    const [fcStrength, setFcStrength] = useState2(1);
    const [fcAngle, setFcAngle] = useState2(180);
    const fcStageRef = useRef2(null);
    const fcImgRef = useRef2(null);
    const openFilterCompare = () => {
      if (!dfLive) return;
      setFcActive(dfLive.c.filter || null);
      setFcStrength(dfLive.c.filterStrength != null ? dfLive.c.filterStrength : 1);
      setFcAngle(dfLive.c.filterAngle != null ? dfLive.c.filterAngle : 180);
      setFcOpen(true);
    };
    const closeFilterCompare = () => setFcOpen(false);
    const fcClear = () => {
      setFcActive(null);
      dfPatch((cc) => ({ ...cc, filter: null }));
    };
    const fcSave = () => {
      dfPatch((cc) => ({ ...cc, filter: fcActive, filterStrength: fcStrength, filterAngle: fcAngle }));
      setFcOpen(false);
    };
    useEffect2(() => {
      if (!fcOpen || !AF || !fcStageRef.current) return;
      const host = fcStageRef.current;
      AF.clearPreview(host);
      if (fcActive) AF.applyPreview(host, fcActive, { strength: fcStrength, angle: fcAngle });
      return () => {
        AF.clearPreview(host);
      };
    }, [fcOpen, fcActive, fcStrength, fcAngle, AF]);
    return /* @__PURE__ */ React.createElement("div", { className: "lm-root" }, /* @__PURE__ */ React.createElement("style", null, LOOM_MOBILE_STYLES), /* @__PURE__ */ React.createElement("div", { className: "lm-top" }, /* @__PURE__ */ React.createElement("a", { className: "lm-back", href: "/" }, "\u2190 Gallery"), /* @__PURE__ */ React.createElement("span", { className: "lm-fill" }), /* @__PURE__ */ React.createElement("span", { className: "lm-title" }, "\u25AA The Loom"), /* @__PURE__ */ React.createElement("span", { className: "lm-fill" }), /* @__PURE__ */ React.createElement(
      "label",
      {
        className: "lm-chip" + (project.draft ? " on" : ""),
        title: "Draft mode renders every shot at the cheaper 'basic' quality \u2014 block out the animatic, then turn Draft off and re-generate the keepers at pro quality"
      },
      /* @__PURE__ */ React.createElement("input", { type: "checkbox", checked: !!project.draft, onChange: (e) => setDraft(e.target.checked) }),
      "\u26A1 Draft"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: "lm-chip",
        onClick: () => setMobileUI(false),
        title: "Switch back to the full desktop-style Loom"
      },
      "\u{1F5A5} Desktop"
    )), /* @__PURE__ */ React.createElement("div", { className: "lm-reelwrap" }, /* @__PURE__ */ React.createElement(
      "div",
      {
        className: "lm-reelbar",
        onPointerDown: onReelDown,
        onPointerMove: onReelMove,
        onPointerUp: onReelUp,
        onPointerLeave: onReelLeave
      },
      entries.map((x) => /* @__PURE__ */ React.createElement(
        "div",
        {
          key: x.c.id,
          className: "lm-seg " + statusOf(x.c) + (x.c.id === selShot ? " sel" : ""),
          style: { flex: `${durOf(x.c) || 1} 1 0` }
        }
      ))
    ), total > 0 && /* @__PURE__ */ React.createElement("div", { className: "lm-tick", style: posStyle(tickFrac) }), scrubbing && /* @__PURE__ */ React.createElement("div", { className: "lm-scrubline", style: posStyle(scrubFrac) }), handleFrac != null && /* @__PURE__ */ React.createElement("div", { className: "lm-handle", style: posStyle(handleFrac) }), scrubbing && scrubEntry && /* @__PURE__ */ React.createElement("div", { className: "lm-preview", style: { left: `clamp(8px, calc(${(scrubFrac * 100).toFixed(3)}% - 86px), calc(100% - 8px - 172px))` } }, /* @__PURE__ */ React.createElement("div", { className: "lm-prevthumb", style: cardThumb(scrubEntry.c) ? { backgroundImage: `url(${cardThumb(scrubEntry.c)})` } : void 0 }), /* @__PURE__ */ React.createElement("div", { className: "lm-prevcol" }, /* @__PURE__ */ React.createElement("div", { className: "lm-prevcode" }, scrubEntry.code), /* @__PURE__ */ React.createElement("div", { className: "lm-prevtitle" }, scrubEntry.c.title || "untitled"), /* @__PURE__ */ React.createElement("div", { className: "lm-prevmeta" }, scrubEntry.c.mode, " \xB7 ", durOf(scrubEntry.c), "s")))), /* @__PURE__ */ React.createElement("div", { className: "lm-body" }, project.acts.map((act, ai) => {
      const items = entries.filter((e) => e.ai === ai);
      return /* @__PURE__ */ React.createElement("div", { key: act.id }, /* @__PURE__ */ React.createElement("div", { className: "lm-acthead" }, /* @__PURE__ */ React.createElement("span", { className: "lm-actname" }, act.name), /* @__PURE__ */ React.createElement("span", { className: "lm-actcount" }, items.length, " shot", items.length === 1 ? "" : "s"), /* @__PURE__ */ React.createElement("span", { className: "lm-fill" }), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-addshot", onClick: () => addCard(act.id) }, "+ Shot")), items.map((e) => {
        const st = statusOf(e.c);
        const gs = genState[e.c.id];
        const miss = castMissingImages(e, project, imgSrc);
        const thumb = cardThumb(e.c);
        const canReview = st === "done" && !!e.c.resultMid;
        return /* @__PURE__ */ React.createElement("div", { key: e.c.id, className: "lm-cardrow" }, /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            className: "lm-card" + (e.c.id === selShot ? " sel" : ""),
            onClick: () => {
              setSelShot(e.c.id);
              setDfOpen(true);
            },
            title: "Open this shot \u2014 it binds to Generate"
          },
          /* @__PURE__ */ React.createElement("div", { className: "lm-thumb", style: thumb ? { backgroundImage: `url(${thumb})` } : void 0 }, !thumb && e.c.mode),
          /* @__PURE__ */ React.createElement("div", { className: "lm-textcol" }, /* @__PURE__ */ React.createElement("div", { className: "lm-titlerow" }, /* @__PURE__ */ React.createElement("span", { className: "lm-code" }, e.code), /* @__PURE__ */ React.createElement("span", { className: "lm-cardtitle" }, e.c.title || "untitled")), /* @__PURE__ */ React.createElement("div", { className: "lm-pillrow" }, /* @__PURE__ */ React.createElement("span", { className: "lm-modepill" }, e.c.mode), /* @__PURE__ */ React.createElement("span", { className: "lm-durpill" }, durOf(e.c), "s"), /* @__PURE__ */ React.createElement("span", { className: "lm-stpill " + st }, gs && gs.msg ? gs.msg : st), miss.length > 0 && /* @__PURE__ */ React.createElement("span", { className: "lm-warn", title: `No picture on this shot for ${miss.join(", ")} \u2014 they are cast here but cannot be referenced, so they are left out of the prompt.` }, "\u26A0 ", miss.length === 1 ? `${miss[0]}: no image` : `${miss.length} cast: no image`)))
        ), canReview && /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            className: "lm-reviewbadge",
            title: "Review & trim this shot's rendered clip",
            onClick: (ev) => {
              ev.stopPropagation();
              setSelShot(e.c.id);
              setReviewOpen(true);
              setReviewCropping(false);
              setReviewPlaying(false);
              setReviewDur(0);
              setReviewCur(0);
            }
          },
          "\u25B6"
        ), /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            className: "lm-kebab",
            title: "More actions for this shot",
            onClick: (ev) => {
              ev.stopPropagation();
              setSelShot(e.c.id);
              setActionsOpen(true);
            }
          },
          "\u22EE"
        ));
      }), !items.length && /* @__PURE__ */ React.createElement("div", { className: "lm-empty" }, "No shots yet \u2014 tap + Shot."));
    }), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-addact", onClick: addAct }, "+ New act"), !project.acts.length && /* @__PURE__ */ React.createElement("div", { className: "lm-empty" }, "No acts yet \u2014 add one below.")), actionsOpen && actionsLive && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lm-scrim" + (actionsClosing ? " closing" : ""), onClick: closeActions }), /* @__PURE__ */ React.createElement("div", { className: "lm-sheet" + (actionsClosing ? " closing" : "") }, /* @__PURE__ */ React.createElement("div", { className: "lm-sheethandle" }), /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: "lm-actionrow",
        onClick: () => {
          moveCard(actionsLive.a.id, actionsLive.ci, -1);
          closeActions();
        }
      },
      "\u2191 Move up"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: "lm-actionrow",
        onClick: () => {
          moveCard(actionsLive.a.id, actionsLive.ci, 1);
          closeActions();
        }
      },
      "\u2193 Move down"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: "lm-actionrow",
        onClick: () => {
          dupCard(actionsLive.a.id, actionsLive.c);
          closeActions();
        }
      },
      "\u29C9 Duplicate"
    ), /* @__PURE__ */ React.createElement(
      "button",
      {
        type: "button",
        className: "lm-actionrow danger",
        onClick: () => {
          if (!window.confirm(`Delete shot ${actionsLive.code}${actionsLive.c.title ? ` \u2014 "${actionsLive.c.title}"` : ""}? This can't be undone.`)) return;
          delCard(actionsLive.a.id, actionsLive.c);
          closeActions();
        }
      },
      "\u{1F5D1} Delete"
    ), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-sheetclose", onClick: closeActions }, "Cancel"))), dfOpen && dfLive && (() => {
      const c = dfLive.c;
      return /* @__PURE__ */ React.createElement("div", { className: "lm-df" }, /* @__PURE__ */ React.createElement("div", { className: "lm-df-top" }, /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          className: "lm-df-st lm-stpill " + statusOf(c),
          title: `Status: ${statusOf(c)} \u2014 tap to cycle`,
          onClick: () => dfPatch((cc) => ({ ...cc, status: cc.status === "todo" ? "wip" : cc.status === "wip" ? "done" : "todo" }))
        },
        statusOf(c)
      ), /* @__PURE__ */ React.createElement("span", { className: "lm-code" }, dfLive.code), /* @__PURE__ */ React.createElement(
        "input",
        {
          className: "lm-df-title",
          value: c.title || "",
          placeholder: "untitled",
          onChange: (ev) => dfPatch((cc) => ({ ...cc, title: ev.target.value }))
        }
      ), /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          className: "lm-df-cast",
          onClick: () => setCastSheetOpen(true),
          title: "Cast & assets bound to this shot"
        },
        "\u{1F465} ",
        (c.cast || []).length
      ), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-df-close", title: "Close", onClick: () => setDfOpen(false) }, "\u2715")), /* @__PURE__ */ React.createElement("div", { className: "lm-df-body" }, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Mode"), /* @__PURE__ */ React.createElement("div", { className: "lm-modechips" }, MODES.map((m) => /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          key: m,
          className: "lm-modechip" + (m === c.mode ? " on" : ""),
          onClick: () => dfPatch((cc) => setShotMode(cc, m))
        },
        m
      ))), /* @__PURE__ */ React.createElement("div", { className: "lm-row2" }, /* @__PURE__ */ React.createElement("div", { className: "lm-col" }, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Duration (s)"), /* @__PURE__ */ React.createElement(
        "input",
        {
          className: "lm-in",
          type: "number",
          min: "1",
          value: c.duration,
          onChange: (ev) => dfPatch((cc) => ({ ...cc, duration: Number(ev.target.value) || 1 }))
        }
      )), /* @__PURE__ */ React.createElement("div", { className: "lm-col" }, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Discreet"), /* @__PURE__ */ React.createElement("label", { className: "lm-check" }, /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "checkbox",
          checked: !!c.discreet,
          onChange: (ev) => dfPatch((cc) => ({ ...cc, discreet: ev.target.checked }))
        }
      ), "blur previews"))), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Prompt"), /* @__PURE__ */ React.createElement(
        "textarea",
        {
          className: "lm-ta",
          value: c.prompt || "",
          placeholder: "what happens in this shot",
          onChange: (ev) => dfPatch((cc) => ({ ...clearPromptOverride(cc), prompt: ev.target.value }))
        }
      ), /* @__PURE__ */ React.createElement("div", { className: "lm-hint" }, "the shot's base prompt \u2014 Camera, Lighting and cast are woven in on top when it generates"), /* @__PURE__ */ React.createElement("div", { className: "lm-frow" }, /* @__PURE__ */ React.createElement("div", { className: "lm-fcol" }, /* @__PURE__ */ React.createElement(
        FrameSlot,
        {
          which: "open",
          frame: c.openFrame,
          liveTag: positionTag(dfLive, project, imgSrc, "openFrame"),
          discreet: c.discreet,
          framePrev: frameSrc,
          storeThumb,
          openPick,
          onPatch: (p) => dfPatchFrame("openFrame", p),
          extraBtn: dfPrevEntry ? /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-inheritbtn", onClick: dfInheritPrev, disabled: dfHandoff === "wip" }, dfHandoff === "wip" ? "\u2702 splicing\u2026" : dfHandoff === "err" ? "\u2702 splice failed \u2014 retry" : dfPrevEntry.c.resultMid ? `\u2702 splice ${dfPrevEntry.code}'s last frame` : `\u21B3 inherit ${dfPrevEntry.code} close`) : null
        }
      )), /* @__PURE__ */ React.createElement("div", { className: "lm-fcol" }, /* @__PURE__ */ React.createElement(
        FrameSlot,
        {
          which: "close",
          frame: c.closeFrame,
          liveTag: positionTag(dfLive, project, imgSrc, "closeFrame"),
          discreet: c.discreet,
          framePrev: frameSrc,
          storeThumb,
          openPick,
          onPatch: (p) => dfPatchFrame("closeFrame", p)
        }
      ))), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab", style: { marginTop: 16 } }, "Other references & @tags"), c.refs.map((r) => {
        const preview = r.thumbId ? thumbs[r.thumbId] : r.kind === "image" && r.source.startsWith("http") ? r.source : null;
        const refLiveTag = r.kind === "image" ? positionTag(dfLive, project, imgSrc, r.id) : null;
        const refPastBudget = r.kind === "image" && !refLiveTag && !!resolvedImage(r, imgSrc);
        return /* @__PURE__ */ React.createElement("div", { className: "lm-refrow", key: r.id }, r.kind === "image" ? /* @__PURE__ */ React.createElement("label", { className: "lm-refprev", title: "Attach image" }, preview ? /* @__PURE__ */ React.createElement("img", { src: preview, alt: r.tag }) : "\uFF0B", /* @__PURE__ */ React.createElement(
          "input",
          {
            type: "file",
            accept: "image/*",
            style: { display: "none" },
            onChange: async (e) => {
              const f = e.target.files[0];
              if (!f) return;
              const id = await storeThumb(f);
              setRef(dfLive.a.id, c.id, r.id, { thumbId: id, source: r.source || f.name });
            }
          }
        )) : /* @__PURE__ */ React.createElement("div", { className: "lm-refprev" }, r.kind === "video" ? "\u{1F39E}" : "\u266A"), /* @__PURE__ */ React.createElement("div", { className: "lm-refbody" }, /* @__PURE__ */ React.createElement("div", { className: "lm-reftoprow" }, /* @__PURE__ */ React.createElement("input", { className: "lm-reftag", value: r.tag, onChange: (e) => setRef(dfLive.a.id, c.id, r.id, { tag: e.target.value }) }), r.kind === "image" && /* @__PURE__ */ React.createElement(
          "span",
          {
            className: "lm-castlive" + (refPastBudget ? " oob" : ""),
            title: liveTagTitle(refLiveTag, refPastBudget, c.mode, dfLive.code)
          },
          liveTagText(refLiveTag, refPastBudget, c.mode)
        ), /* @__PURE__ */ React.createElement("span", { className: "lm-refkind" }, r.kind), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-refx", onClick: () => delRef(dfLive.a.id, c.id, r) }, "\u2715")), /* @__PURE__ */ React.createElement(
          "input",
          {
            className: "lm-in",
            placeholder: "what to use it for (motion / camera / mood\u2026)",
            value: r.role,
            onChange: (e) => setRef(dfLive.a.id, c.id, r.id, { role: e.target.value })
          }
        ), /* @__PURE__ */ React.createElement(
          "input",
          {
            className: "lm-in",
            placeholder: "file name or URL",
            value: r.source,
            onChange: (e) => setRef(dfLive.a.id, c.id, r.id, { source: e.target.value })
          }
        )));
      }), /* @__PURE__ */ React.createElement("div", { className: "lm-addrefrow" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-addrefbtn", onClick: () => addRef(dfLive.a.id, c, "image") }, "+ Image"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-addrefbtn", onClick: () => addRef(dfLive.a.id, c, "video") }, "+ Video"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-addrefbtn", onClick: () => addRef(dfLive.a.id, c, "audio") }, "+ Audio")), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Music / audio cue"), /* @__PURE__ */ React.createElement(
        "input",
        {
          className: "lm-in",
          value: c.audioCue,
          placeholder: "track, beat sync, room tone\u2026",
          onChange: (ev) => dfPatch((cc) => ({ ...cc, audioCue: ev.target.value }))
        }
      ), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Notes"), /* @__PURE__ */ React.createElement(
        "textarea",
        {
          className: "lm-ta",
          value: c.notes,
          placeholder: "blocking, continuity reminders\u2026",
          onChange: (ev) => dfPatch((cc) => ({ ...cc, notes: ev.target.value }))
        }
      ), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-copybtn", onClick: () => copyShot(dfLive) }, "Copy shot"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-genbtn", onClick: () => setGenOpen(true) }, "Select in Generate \u2192")), castSheetOpen && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lm-scrim" + (castSheetClosing ? " closing" : ""), onClick: closeCastSheet }), /* @__PURE__ */ React.createElement("div", { className: "lm-sheet" + (castSheetClosing ? " closing" : "") }, /* @__PURE__ */ React.createElement("div", { className: "lm-sheethandle" }), /* @__PURE__ */ React.createElement("div", { className: "lm-tabsrow" }, /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          className: "lm-tabbtn" + (castSheetTab === "cast" ? " on" : ""),
          onClick: () => setCastSheetTab("cast")
        },
        "Cast & assets"
      ), /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          className: "lm-tabbtn" + (castSheetTab === "footage" ? " on" : ""),
          onClick: () => setCastSheetTab("footage")
        },
        "Footage"
      )), castSheetTab === "cast" ? /* @__PURE__ */ React.createElement(React.Fragment, null, !modeSendsRefs(c.mode) ? /* @__PURE__ */ React.createElement("div", { className: "lm-i2vnote" }, modeSendsLine(c.mode)) : castBudget ? /* @__PURE__ */ React.createElement("div", { className: "lm-budget" }, /* @__PURE__ */ React.createElement("span", { className: castBudget.used > castBudget.budget ? "lm-budget-over" : void 0 }, castBudget.used, " of ", castBudget.budget, " reference slot", castBudget.budget === 1 ? "" : "s", " used"), castBudget.frames ? /* @__PURE__ */ React.createElement("span", null, " \xB7 ", castBudget.frames, " of 6 held by attached frame", castBudget.frames === 1 ? "" : "s") : null) : null, (project.assets || []).map((as) => {
        const inShot = (c.cast || []).includes(as.id);
        const src = frameSrc(as);
        const missing = as.kind === "image" && !resolvedImage(as, imgSrc);
        const liveTag = inShot && as.kind === "image" ? positionTag(dfLive, project, imgSrc, as.id) : null;
        const pastBudget = inShot && as.kind === "image" && !liveTag && !!resolvedImage(as, imgSrc);
        return /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            key: as.id,
            className: "lm-castrow",
            onClick: () => dfPatch((cc) => ({ ...cc, cast: (cc.cast || []).includes(as.id) ? cc.cast.filter((x) => x !== as.id) : [...cc.cast || [], as.id] }))
          },
          /* @__PURE__ */ React.createElement("span", { className: "lm-castbox" + (inShot ? " on" : "") }),
          /* @__PURE__ */ React.createElement("div", { className: "lm-castthumb", style: src ? { backgroundImage: `url(${src})` } : void 0 }, !src && (as.kind === "audio" ? "\u266A" : as.kind === "video" ? "\u{1F39E}" : "\u{1F5BC}")),
          /* @__PURE__ */ React.createElement("div", { className: "lm-castcol" }, /* @__PURE__ */ React.createElement("div", { className: "lm-castname" }, as.name || as.kind), /* @__PURE__ */ React.createElement("div", { className: "lm-casttag" }, as.tag)),
          missing && /* @__PURE__ */ React.createElement("span", { className: "lm-castmissing" }, "missing"),
          liveTag || pastBudget ? /* @__PURE__ */ React.createElement("span", { className: "lm-castlive" + (pastBudget ? " oob" : "") }, liveTagText(liveTag, pastBudget, c.mode)) : null,
          !!as.lock && /* @__PURE__ */ React.createElement("span", { className: "lm-castlock", title: "Lock appearance" }, "\u{1F512}")
        );
      }), !(project.assets || []).length && /* @__PURE__ */ React.createElement("div", { className: "lm-empty" }, "No cast yet."), /* @__PURE__ */ React.createElement("div", { className: "lm-castaddrow" }, /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          className: "lm-addrefbtn",
          onClick: () => setAssets((a) => [...a, { id: uid(), name: "New reference", kind: "image", tag: nextTag(a, "@image"), thumbId: "", source: "", lock: false }])
        },
        "+ Image ref"
      ), /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          className: "lm-addrefbtn",
          onClick: () => setAssets((a) => [...a, { id: uid(), name: "New audio", kind: "audio", tag: nextTag(a, "@audio"), thumbId: "", source: "", lock: false }])
        },
        "+ Audio ref"
      ))) : finishedShots.length ? /* @__PURE__ */ React.createElement("div", { className: "lm-footagegrid" }, finishedShots.map((e) => /* @__PURE__ */ React.createElement("div", { key: e.c.id, className: "lm-fclip", onClick: () => {
        dfPickFootage(e.c.resultMid, e.code);
        closeCastSheet();
      } }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + e.c.resultMid + ".jpg", alt: "" }), /* @__PURE__ */ React.createElement("div", { className: "lm-fclipmeta" }, /* @__PURE__ */ React.createElement("b", null, e.code), /* @__PURE__ */ React.createElement("span", null, durOf(e.c), "s"))))) : /* @__PURE__ */ React.createElement("div", { className: "lm-empty" }, "no rendered shots yet"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-sheetclose", onClick: closeCastSheet }, "Done"))));
    })(), genOpen && dfLive && (() => {
      const c = dfLive.c;
      const gp = genPrice[c.id] || {};
      const tally = gp.pr ? tallyPrices([gp.pr]) : null;
      const costText = gp.noInput ? "attach a frame or cast image first" : gp.loading ? "checking\u2026" : tally ? formatCostEstimate(tally) : "\u2014";
      const costTitle = tally ? costTooltip(tally) : "";
      const gsSelf = genState[c.id];
      const genBusy = !!(gsSelf && gsSelf.phase && gsSelf.phase !== "done" && gsSelf.phase !== "error" && gsSelf.phase !== "paused");
      const showClose = usesCloseFrame(c.mode);
      return /* @__PURE__ */ React.createElement("div", { className: "lm-gen" }, /* @__PURE__ */ React.createElement("div", { className: "lm-gen-top" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-gen-back", onClick: () => setGenOpen(false) }, "\u2039 ", dfLive.code), /* @__PURE__ */ React.createElement("span", { className: "lm-gen-title" }, c.title || "untitled"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-df-close", title: "Close", onClick: () => {
        setGenOpen(false);
        setDfOpen(false);
      } }, "\u2715")), /* @__PURE__ */ React.createElement("div", { className: "lm-tabsrow", style: { margin: "0 16px 8px" } }, ["Image", "Edit", "Reference", "Video"].map((t) => /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          key: t,
          className: "lm-tabbtn" + (genTab === t ? " on" : ""),
          onClick: () => setGenTab(t)
        },
        t
      ))), acct && /* @__PURE__ */ React.createElement("div", { className: "lm-bal", style: { margin: "0 16px 8px" } }, "\u26A1 ", acct.credits == null ? "\u2014" : acct.credits, " credits \xB7 ", acct.cards || 0, " card", acct.cards === 1 ? "" : "s", acct.claim_credits ? /* @__PURE__ */ React.createElement("span", { style: { color: "var(--gold)" } }, " \xB7 +", acct.claim_credits, " claimable") : null), /* @__PURE__ */ React.createElement("div", { className: "lm-gen-body" }, genTab === "Image" && (() => {
        const gi = genImgState[c.id] || {};
        const busyI = gi.phase === "submitting" || gi.phase === "running";
        const compat = imgModel && imgModel.compatibility || {};
        const restr = imgModel && imgModel.restrictions || {};
        const negOff = compat.negativePrompt === false;
        const stepsOff = compat.samplingSteps === false;
        const cfgOff = compat.cfgScale === false;
        const stepsB = restr.samplingSteps || {};
        const cfgB = restr.cfgScale || {};
        const offTitle = "This model doesn\u2019t use this setting";
        return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Model"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-selrow", onClick: () => {
          setPickerKind("base");
          setPickerOpen(true);
        } }, imgModel && imgModel.preview_url ? /* @__PURE__ */ React.createElement("img", { className: "lm-selthumb", src: imgModel.preview_url, alt: "" }) : null, /* @__PURE__ */ React.createElement("span", { className: "lm-selname" }, imgModel ? imgModel.title : "none \u2014 browse models"), /* @__PURE__ */ React.createElement("span", { className: "lm-selhint" }, "\u2630 browse")), imgModel && (imgModel.sampling_method || (imgModel.capabilities || []).length > 0) && /* @__PURE__ */ React.createElement("div", { className: "lm-caps" }, imgModel.sampling_method ? /* @__PURE__ */ React.createElement("span", { className: "lm-cap method" }, imgModel.sampling_method) : null, (imgModel.capabilities || []).map((cp) => /* @__PURE__ */ React.createElement("span", { key: cp, className: "lm-cap" }, cp))), imgModel && imgModel.versions && imgModel.versions.length > 1 && /* @__PURE__ */ React.createElement(
          "select",
          {
            className: "lm-gensel",
            value: imgModel.version_id || "",
            onChange: (ev) => pickVersion(ev.target.value),
            title: "This model's published releases -- PixAI defaults to the latest; pick another to generate against it instead",
            "aria-label": "Model version"
          },
          imgModel.versions.map((v) => /* @__PURE__ */ React.createElement("option", { key: v.version_id, value: v.version_id }, v.label || v.version_id))
        ), imgLoras.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "lm-loras" }, imgLoras.map((l) => {
          const incompat = loraIncompat(imgModel && imgModel.model_type, l.lora_base_type);
          return /* @__PURE__ */ React.createElement("div", { key: l.model_id, className: "lm-lchip" + (l.failed || incompat ? " failed" : "") }, /* @__PURE__ */ React.createElement("span", { className: "lm-lnm", title: incompat ? l.title + " \u2014 needs a different base architecture than the one selected; remove it or switch the base" : l.title }, l.title, !l.version_id ? l.failed ? " \u26A0" : " \u23F3" : incompat ? " \u26A0" : ""), /* @__PURE__ */ React.createElement("span", { className: "lm-lw" }, /* @__PURE__ */ React.createElement(
            "input",
            {
              type: "range",
              step: "0.1",
              min: loraRange[0],
              max: loraRange[1],
              value: l.weight,
              title: "Weight \u2014 " + loraRange[0] + " to " + loraRange[1] + " for this base model",
              onChange: (ev) => {
                const w = Math.max(loraRange[0], Math.min(loraRange[1], +ev.target.value || 0));
                setImgLoras((cur) => cur.map((x) => x.model_id === l.model_id ? { ...x, weight: w } : x));
              }
            }
          ), /* @__PURE__ */ React.createElement("b", null, (+l.weight).toFixed(1))), /* @__PURE__ */ React.createElement(
            "button",
            {
              type: "button",
              className: "lm-lrm",
              title: "Remove",
              onClick: () => {
                setImgLoras((cur) => cur.filter((x) => x.model_id !== l.model_id));
              }
            },
            "\xD7"
          ), l.versions && l.versions.length > 1 && /* @__PURE__ */ React.createElement(
            "select",
            {
              className: "lm-lorver",
              value: l.version_id || "",
              onChange: (ev) => {
                const vid = ev.target.value;
                const v = l.versions.find((x) => x.version_id === vid);
                if (!v) return;
                setImgLoras((cur) => cur.map((x) => x.model_id === l.model_id ? {
                  ...x,
                  version_id: v.version_id || "",
                  lora_base_type: v.lora_base_model_type || "",
                  trigger_words: v.trigger_words || "",
                  failed: !v.version_id
                } : x));
              }
            },
            l.versions.map((v) => /* @__PURE__ */ React.createElement("option", { key: v.version_id, value: v.version_id }, v.label || v.version_id))
          ));
        })), /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            className: "lm-addrefbtn",
            style: { marginTop: 6 },
            onClick: () => {
              setPickerKind("lora");
              setPickerOpen(true);
            }
          },
          "+ add LoRA"
        ), acct && acct.lora_cap != null && /* @__PURE__ */ React.createElement("span", { className: "lm-hint", style: { marginLeft: 8 } }, imgLoras.length, " / ", acct.lora_cap, " LoRAs"), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab", style: { marginTop: 12 } }, "Image prompt"), /* @__PURE__ */ React.createElement(
          "textarea",
          {
            className: "lm-ta",
            value: c.imgPrompt || "",
            placeholder: "describe the reference still (subject, pose, composition, light)\u2026",
            onChange: (ev) => dfPatch((cc) => ({ ...cc, imgPrompt: ev.target.value }))
          }
        ), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-mini2-btn", onClick: () => dfPatch((cc) => ({ ...cc, imgPrompt: [cc.title, cc.prompt, cc.openFrame && cc.openFrame.desc || "", cc.lighting || ""].filter(Boolean).join(", ") })) }, "\u21A7 seed from shot description"), /* @__PURE__ */ React.createElement("details", { style: { marginTop: 10 } }, /* @__PURE__ */ React.createElement("summary", { className: "lm-hint", style: { cursor: "pointer" } }, "Advanced"), /* @__PURE__ */ React.createElement(
          "textarea",
          {
            className: "lm-ta",
            style: { marginTop: 6 },
            value: imgAdv.negative,
            placeholder: "lowres, text, watermark\u2026",
            disabled: negOff,
            title: negOff ? offTitle : "",
            onChange: (ev) => setImgAdv((a) => ({ ...a, negative: ev.target.value }))
          }
        ), /* @__PURE__ */ React.createElement("div", { className: "lm-row2" }, /* @__PURE__ */ React.createElement("div", { className: "lm-col" }, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Steps"), /* @__PURE__ */ React.createElement(
          "input",
          {
            className: "lm-in",
            type: "number",
            min: stepsB.min != null ? stepsB.min : 1,
            max: stepsB.max != null ? stepsB.max : 150,
            step: "1",
            value: imgAdv.steps,
            disabled: stepsOff,
            title: stepsOff ? offTitle : "",
            onChange: (ev) => setImgAdv((a) => ({ ...a, steps: +ev.target.value || 25 }))
          }
        )), /* @__PURE__ */ React.createElement("div", { className: "lm-col" }, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "CFG scale"), /* @__PURE__ */ React.createElement(
          "input",
          {
            className: "lm-in",
            type: "number",
            min: cfgB.min != null ? cfgB.min : 1,
            max: cfgB.max != null ? cfgB.max : 30,
            step: "0.5",
            value: imgAdv.cfg,
            disabled: cfgOff,
            title: cfgOff ? offTitle : "",
            onChange: (ev) => setImgAdv((a) => ({ ...a, cfg: +ev.target.value || 7 }))
          }
        ))), modelDefaults && /* @__PURE__ */ React.createElement("div", { className: "lm-hint", style: { display: "flex", justifyContent: "space-between" } }, /* @__PURE__ */ React.createElement("span", null, "\u2713 using this model's tuned preset"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-mini2-btn", onClick: () => setImgAdv((a) => ({
          ...a,
          negative: modelDefaults.negative_prompt || a.negative,
          steps: modelDefaults.sampling_steps || a.steps,
          cfg: modelDefaults.cfg_scale || a.cfg
        })) }, "\u21B6 reset"))), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab", style: { marginTop: 12 } }, "Aspect"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 5, flexWrap: "wrap" } }, [
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
            type: "button",
            key: label,
            className: "lm-modechip" + (imgAdv.aspectW === rw && imgAdv.aspectH === rh ? " on" : ""),
            style: { flex: "0 0 auto", padding: "6px 10px" },
            onClick: () => setImgAdv((a) => ({ ...a, aspectW: rw, aspectH: rh }))
          },
          label
        ))), /* @__PURE__ */ React.createElement("div", { className: "lm-row2" }, /* @__PURE__ */ React.createElement("div", { className: "lm-col" }, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Size \xB7 long edge"), /* @__PURE__ */ React.createElement(
          "select",
          {
            className: "lm-gensel",
            style: { marginTop: 0 },
            value: imgAdv.size,
            onChange: (ev) => setImgAdv((a) => ({ ...a, size: +ev.target.value }))
          },
          /* @__PURE__ */ React.createElement("option", { value: "768" }, "S \xB7 768"),
          /* @__PURE__ */ React.createElement("option", { value: "1024" }, "M \xB7 1024"),
          /* @__PURE__ */ React.createElement("option", { value: "1536" }, "L \xB7 1536"),
          /* @__PURE__ */ React.createElement("option", { value: "2048" }, "XL \xB7 2048")
        )), /* @__PURE__ */ React.createElement("div", { className: "lm-col" }, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Custom W\xD7H"), /* @__PURE__ */ React.createElement("div", { style: { display: "flex", gap: 5, alignItems: "center" } }, /* @__PURE__ */ React.createElement(
          "input",
          {
            className: "lm-in",
            type: "number",
            min: "64",
            max: "4096",
            step: "8",
            placeholder: "W",
            value: imgAdv.customW,
            onChange: (ev) => setImgAdv((a) => ({ ...a, customW: ev.target.value }))
          }
        ), /* @__PURE__ */ React.createElement("span", { className: "lm-hint" }, "\xD7"), /* @__PURE__ */ React.createElement(
          "input",
          {
            className: "lm-in",
            type: "number",
            min: "64",
            max: "4096",
            step: "8",
            placeholder: "H",
            value: imgAdv.customH,
            onChange: (ev) => setImgAdv((a) => ({ ...a, customH: ev.target.value }))
          }
        )))), /* @__PURE__ */ React.createElement("div", { className: "lm-hint" }, (() => {
          const d = resolveGenDims(imgAdv);
          return "\u2192 " + d.w + " \xD7 " + d.h + (d.custom ? " \xB7 custom" : " px");
        })()), /* @__PURE__ */ React.createElement("div", { className: "lm-row2" }, /* @__PURE__ */ React.createElement("div", { className: "lm-col" }, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Mode"), /* @__PURE__ */ React.createElement(
          "select",
          {
            className: "lm-gensel",
            style: { marginTop: 0 },
            value: imgAdv.mode,
            onChange: (ev) => setImgAdv((a) => ({ ...a, mode: ev.target.value }))
          },
          /* @__PURE__ */ React.createElement("option", { value: "auto" }, "Auto"),
          /* @__PURE__ */ React.createElement("option", { value: "lite" }, "Lite"),
          /* @__PURE__ */ React.createElement("option", { value: "standard" }, "Standard"),
          /* @__PURE__ */ React.createElement("option", { value: "pro" }, "Pro"),
          /* @__PURE__ */ React.createElement("option", { value: "ultra" }, "Ultra")
        )), /* @__PURE__ */ React.createElement("div", { className: "lm-col" }, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Count"), /* @__PURE__ */ React.createElement(
          "select",
          {
            className: "lm-gensel",
            style: { marginTop: 0 },
            value: imgAdv.count,
            onChange: (ev) => setImgAdv((a) => ({ ...a, count: +ev.target.value }))
          },
          /* @__PURE__ */ React.createElement("option", { value: "1" }, "1"),
          /* @__PURE__ */ React.createElement("option", { value: "2" }, "2"),
          /* @__PURE__ */ React.createElement("option", { value: "3" }, "3"),
          /* @__PURE__ */ React.createElement("option", { value: "4" }, "4")
        ))), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Seed \xB7 blank = random"), /* @__PURE__ */ React.createElement(
          "input",
          {
            className: "lm-in",
            type: "number",
            placeholder: "random",
            value: imgAdv.seed,
            onChange: (ev) => setImgAdv((a) => ({ ...a, seed: ev.target.value }))
          }
        ), /* @__PURE__ */ React.createElement("label", { className: "lm-check", title: "This IS the site's Turbo tier (priority=1000): a faster runner. Costs more credits when paid, but a matching free card covers it." }, /* @__PURE__ */ React.createElement(
          "input",
          {
            type: "checkbox",
            checked: imgAdv.highPriority,
            onChange: (ev) => setImgAdv((a) => ({ ...a, highPriority: ev.target.checked }))
          }
        ), " High priority \xB7 Turbo (faster)"), /* @__PURE__ */ React.createElement("label", { className: "lm-check" }, /* @__PURE__ */ React.createElement(
          "input",
          {
            type: "checkbox",
            checked: imgAdv.promptHelper,
            onChange: (ev) => setImgAdv((a) => ({ ...a, promptHelper: ev.target.checked }))
          }
        ), " Prompt helper"), /* @__PURE__ */ React.createElement("div", { className: "lm-gencost" }, /* @__PURE__ */ React.createElement("span", { className: "lm-gencosttext", title: priceTitle(imgPrice, c.id) }, priceLine(imgPrice, c.id, "Pick a model and write a prompt to see the cost."))), /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            className: "lm-genbtn",
            disabled: busyI || !imgModel || !(c.imgPrompt || "").trim() || anyLoraUnresolved(imgLoras) || imgLoras.some((l) => loraIncompat(imgModel && imgModel.model_type, l.lora_base_type)) || overLoraCap(imgLoras, acct && acct.lora_cap),
            onClick: () => genImage(dfLive)
          },
          busyI ? gi.msg || "generating\u2026" : anyLoraUnresolved(imgLoras) ? "waiting on LoRA\u2026" : imgLoras.some((l) => loraIncompat(imgModel && imgModel.model_type, l.lora_base_type)) ? "incompatible LoRA \u2014 remove or switch base" : overLoraCap(imgLoras, acct && acct.lora_cap) ? "remove " + (imgLoras.length - acct.lora_cap) + " LoRA" + (imgLoras.length - acct.lora_cap === 1 ? "" : "s") + " to continue" : "\u2726 Generate reference image"
        ), gi.phase === "error" && /* @__PURE__ */ React.createElement("div", { className: "lm-gerr" }, gi.msg), gi.mid && /* @__PURE__ */ React.createElement("div", { className: "lm-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + gi.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lm-route" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-routebtn" + (gi.routed === "open" ? " on" : ""), onClick: () => routeImg(dfLive, "open", c.id) }, "open frame"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-routebtn" + (gi.routed === "close" ? " on" : ""), onClick: () => routeImg(dfLive, "close", c.id) }, "close frame"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-routebtn" + (gi.routed === "cast" ? " on" : ""), onClick: () => routeImg(dfLive, "cast", c.id) }, "cast")), gi.routed && /* @__PURE__ */ React.createElement("div", { className: "lm-ok2" }, "\u2713 sent to ", gi.routed, " \u2014 it now feeds this shot's video gen")));
      })(), genTab === "Edit" && (() => {
        const ge = genEditState[c.id] || {};
        const busyE = ge.phase === "submitting" || ge.phase === "running";
        const src = c.openFrame && c.openFrame.mediaId;
        const gf = genFixState[c.id] || {};
        const busyF = gf.phase === "submitting" || gf.phase === "running";
        return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lm-tabsrow", style: { marginBottom: 10 } }, /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            className: "lm-tabbtn" + (editSub === "edit" ? " on" : ""),
            onClick: () => setEditSub("edit")
          },
          "Edit"
        ), /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            className: "lm-tabbtn" + (editSub === "fixer" ? " on" : ""),
            onClick: () => setEditSub("fixer")
          },
          "Fixer"
        ), /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            className: "lm-tabbtn" + (editSub === "enhance" ? " on" : ""),
            onClick: () => setEditSub("enhance")
          },
          "Enhance"
        )), editSub === "edit" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Source \u2014 this shot's open frame"), src ? /* @__PURE__ */ React.createElement("div", { className: "lm-genframe", style: { height: 120, maxWidth: 220 } }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + src + ".jpg", alt: "source" })) : /* @__PURE__ */ React.createElement("div", { className: "lm-empty" }, "No open-frame image yet \u2014 route one from the ", /* @__PURE__ */ React.createElement("b", null, "Image"), " tab, or pick it into the open frame on Shot Detail."), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab", style: { marginTop: 12 } }, "Edit instruction"), /* @__PURE__ */ React.createElement(
          "textarea",
          {
            className: "lm-ta",
            value: c.editPrompt || "",
            placeholder: "e.g. make it night, add rain, warmer key light\u2026",
            onChange: (ev) => dfPatch((cc) => ({ ...cc, editPrompt: ev.target.value }))
          }
        ), /* @__PURE__ */ React.createElement("div", { className: "lm-gencost" }, /* @__PURE__ */ React.createElement("span", { className: "lm-gencosttext", title: priceTitle(editPrice, c.id) }, priceLine(editPrice, c.id, "Add a source image and instruction to see the cost."))), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-genbtn", disabled: busyE || !src, onClick: () => genEdit(dfLive) }, busyE ? ge.msg || "editing\u2026" : "\u2726 Edit the open frame"), ge.phase === "error" && /* @__PURE__ */ React.createElement("div", { className: "lm-gerr" }, ge.msg), ge.mid && /* @__PURE__ */ React.createElement("div", { className: "lm-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + ge.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lm-route" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-routebtn" + (ge.routed === "open" ? " on" : ""), onClick: () => routeGen(genEditState, setGenEditState, dfLive, "open", c.id) }, "open frame"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-routebtn" + (ge.routed === "close" ? " on" : ""), onClick: () => routeGen(genEditState, setGenEditState, dfLive, "close", c.id) }, "close frame"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-routebtn" + (ge.routed === "cast" ? " on" : ""), onClick: () => routeGen(genEditState, setGenEditState, dfLive, "cast", c.id) }, "cast")), ge.routed && /* @__PURE__ */ React.createElement("div", { className: "lm-ok2" }, "\u2713 sent to ", ge.routed))), editSub === "fixer" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Source \u2014 this shot's open frame"), src ? /* @__PURE__ */ React.createElement("div", { className: "lm-fixwrap" }, /* @__PURE__ */ React.createElement(
          "img",
          {
            ref: fixImgRef,
            src: "/thumbs/" + src + ".jpg",
            alt: "source",
            draggable: false,
            onLoad: fixPaint
          }
        ), /* @__PURE__ */ React.createElement(
          "canvas",
          {
            ref: fixCanvasRef,
            onPointerDown: fixDown,
            onPointerMove: fixMove,
            onPointerUp: fixUp,
            onPointerLeave: fixUp
          }
        )) : /* @__PURE__ */ React.createElement("div", { className: "lm-empty" }, "No open-frame image yet \u2014 route one from the ", /* @__PURE__ */ React.createElement("b", null, "Image"), " tab, or pick it into the open frame on Shot Detail."), src && /* @__PURE__ */ React.createElement("div", { className: "lm-fixhint" }, "Drag a box over the hand or face on the source."), /* @__PURE__ */ React.createElement("div", { className: "lm-modechips" }, ["face", "hand"].map((t) => /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            key: t,
            className: "lm-modechip" + (fixTag === t ? " on" : ""),
            style: fixTag === t ? { borderColor: FIX_COLORS[t], color: FIX_COLORS[t] } : null,
            onClick: () => setFixTag(t)
          },
          t === "face" ? "Face" : "Hand"
        ))), fixBoxes.length > 0 && /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            className: "lm-addrefbtn",
            style: { marginTop: 8 },
            onClick: () => setFixBoxes([])
          },
          "Clear ",
          fixBoxes.length,
          " box",
          fixBoxes.length === 1 ? "" : "es"
        ), /* @__PURE__ */ React.createElement("div", { className: "lm-fixwarn" }, "A fix can't be card-covered \u2014 it always spends, and always asks first."), /* @__PURE__ */ React.createElement("div", { className: "lm-gencost" }, /* @__PURE__ */ React.createElement("span", { className: "lm-gencosttext", title: priceTitle(genFixPrice, c.id) }, priceLine(genFixPrice, c.id, "Drag a box over a hand or face to see the cost."))), /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            className: "lm-genbtn",
            disabled: busyF || !src || !fixBoxes.length,
            title: !src ? "This shot has no open-frame image yet" : !fixBoxes.length ? "Drag at least one box" : "Submit the repair \u2014 always spends",
            onClick: () => genFix(dfLive, scaleFixBoxes(fixBoxes, fixImgRef.current))
          },
          busyF ? gf.msg || "fixing\u2026" : "\u2726 Fix " + fixTag
        ), gf.phase === "error" && /* @__PURE__ */ React.createElement("div", { className: "lm-gerr" }, gf.msg), gf.mid && /* @__PURE__ */ React.createElement("div", { className: "lm-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + gf.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lm-route" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-routebtn" + (gf.routed === "open" ? " on" : ""), onClick: () => routeGen(genFixState, setGenFixState, dfLive, "open", c.id) }, "open frame"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-routebtn" + (gf.routed === "close" ? " on" : ""), onClick: () => routeGen(genFixState, setGenFixState, dfLive, "close", c.id) }, "close frame"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-routebtn" + (gf.routed === "cast" ? " on" : ""), onClick: () => routeGen(genFixState, setGenFixState, dfLive, "cast", c.id) }, "cast")), gf.routed && /* @__PURE__ */ React.createElement("div", { className: "lm-ok2" }, "\u2713 sent to ", gf.routed))), editSub === "enhance" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Art filters \xB7 free, no generation"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-openfiltersbtn", onClick: openFilterCompare }, "\u25C9 Open filters"), /* @__PURE__ */ React.createElement("div", { className: "lm-hint", style: { marginTop: 8 } }, "Gradient overlays, not AI \u2014 applied right in the browser: no credits, no request, works offline.")));
      })(), genTab === "Reference" && (() => {
        const gr = genRefState[c.id] || {};
        const busyR = gr.phase === "submitting" || gr.phase === "running";
        const refs = (project.assets || []).filter((a) => a.kind === "image" && a.mediaId);
        return /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lm-frow" }, /* @__PURE__ */ React.createElement("div", { className: "lm-fcol" }, /* @__PURE__ */ React.createElement(
          FrameSlot,
          {
            which: "open",
            frame: c.openFrame,
            liveTag: positionTag(dfLive, project, imgSrc, "openFrame"),
            discreet: c.discreet,
            framePrev: frameSrc,
            storeThumb,
            openPick,
            onPatch: (p) => dfPatchFrame("openFrame", p),
            extraBtn: dfPrevEntry ? /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-inheritbtn", onClick: dfInheritPrev, disabled: dfHandoff === "wip" }, dfHandoff === "wip" ? "\u2702 splicing\u2026" : dfHandoff === "err" ? "\u2702 splice failed \u2014 retry" : dfPrevEntry.c.resultMid ? `\u2702 splice ${dfPrevEntry.code}'s last frame` : `\u21B3 inherit ${dfPrevEntry.code} close`) : null
          }
        )), /* @__PURE__ */ React.createElement("div", { className: "lm-fcol" }, /* @__PURE__ */ React.createElement(
          FrameSlot,
          {
            which: "close",
            frame: c.closeFrame,
            liveTag: positionTag(dfLive, project, imgSrc, "closeFrame"),
            discreet: c.discreet,
            framePrev: frameSrc,
            storeThumb,
            openPick,
            onPatch: (p) => dfPatchFrame("closeFrame", p)
          }
        ))), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "References \u2014 cast @image members (", refs.length, ")"), refs.length ? /* @__PURE__ */ React.createElement("div", { className: "lm-refstrip" }, refs.map((a) => /* @__PURE__ */ React.createElement("img", { key: a.id, src: "/thumbs/" + a.mediaId + ".jpg", title: a.tag, alt: "" }))) : /* @__PURE__ */ React.createElement("div", { className: "lm-empty" }, "No cast @image references with a gallery image yet \u2014 add some via the Cast & assets sheet."), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab", style: { marginTop: 12 } }, "Prompt"), /* @__PURE__ */ React.createElement(
          "textarea",
          {
            className: "lm-ta",
            value: c.refPrompt || "",
            placeholder: "compose a new still from the references\u2026",
            onChange: (ev) => dfPatch((cc) => ({ ...cc, refPrompt: ev.target.value }))
          }
        ), /* @__PURE__ */ React.createElement("div", { className: "lm-gencost" }, /* @__PURE__ */ React.createElement("span", { className: "lm-gencosttext", title: priceTitle(refPrice, c.id) }, priceLine(refPrice, c.id, "Add references and a prompt to see the cost."))), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-genbtn", disabled: busyR || !refs.length, onClick: () => genRef(dfLive) }, busyR ? gr.msg || "generating\u2026" : "\u2726 Generate from references"), gr.phase === "error" && /* @__PURE__ */ React.createElement("div", { className: "lm-gerr" }, gr.msg), gr.mid && /* @__PURE__ */ React.createElement("div", { className: "lm-imgresult" }, /* @__PURE__ */ React.createElement("img", { src: "/thumbs/" + gr.mid + ".jpg", alt: "result" }), /* @__PURE__ */ React.createElement("div", { className: "lm-route" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-routebtn" + (gr.routed === "open" ? " on" : ""), onClick: () => routeGen(genRefState, setGenRefState, dfLive, "open", c.id) }, "open frame"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-routebtn" + (gr.routed === "close" ? " on" : ""), onClick: () => routeGen(genRefState, setGenRefState, dfLive, "close", c.id) }, "close frame"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-routebtn" + (gr.routed === "cast" ? " on" : ""), onClick: () => routeGen(genRefState, setGenRefState, dfLive, "cast", c.id) }, "cast")), gr.routed && /* @__PURE__ */ React.createElement("div", { className: "lm-ok2" }, "\u2713 sent to ", gr.routed)));
      })(), genTab === "Video" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Mode"), /* @__PURE__ */ React.createElement("div", { className: "lm-modechips" }, MODES.map((m) => /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          key: m,
          className: "lm-modechip" + (m === c.mode ? " on" : ""),
          onClick: () => dfPatch((cc) => setShotMode(cc, m))
        },
        m
      ))), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Continuity"), /* @__PURE__ */ React.createElement("div", { className: "lm-modechips" }, Object.keys(CONNECT).map((k) => /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          key: k,
          className: "lm-modechip" + (k === (c.connect || "new") ? " on" : ""),
          title: CONNECT[k].hint,
          onClick: () => dfPatch((cc) => setShotConnect(cc, k))
        },
        CONNECT[k].label
      ))), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Prompt"), /* @__PURE__ */ React.createElement(
        "textarea",
        {
          className: "lm-ta",
          value: c.prompt || "",
          placeholder: "Describe the motion\u2026",
          onChange: (ev) => {
            if (c.promptOverride) {
              setGenOverrideFlash(true);
              setTimeout(() => setGenOverrideFlash(false), 1600);
            }
            dfPatch((cc) => ({ ...clearPromptOverride(cc), prompt: ev.target.value }));
          }
        }
      ), /* @__PURE__ */ React.createElement("div", { className: "lm-hint" }, "motion only \u2014 camera, lighting and cast weave in on top"), c.promptOverride && /* @__PURE__ */ React.createElement("div", { className: "lm-genoverride" }, "\u270E override active \u2014 Camera/Lighting/cast not woven in"), genOverrideFlash && /* @__PURE__ */ React.createElement("div", { className: "lm-genflash" }, "override cleared \u2014 back to auto-compose"), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab", style: { marginTop: 12 } }, "Camera ", /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-gentermbtn", onClick: () => genTogglePal("camera") }, "+ terms")), /* @__PURE__ */ React.createElement(
        "input",
        {
          className: "lm-in",
          value: c.camera || "",
          placeholder: "e.g. slow push in, shallow DoF",
          onChange: (ev) => dfPatch((cc) => ({ ...cc, camera: ev.target.value }))
        }
      ), genPalFor === "camera" && /* @__PURE__ */ React.createElement("div", { className: "lm-gentermpal" }, Object.entries(CAM_PALETTE).map(([grp, items]) => /* @__PURE__ */ React.createElement("div", { key: grp, className: "lm-gentermgrp" }, /* @__PURE__ */ React.createElement("div", { className: "lm-gentermgrpt" }, grp), items.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lm-genchip", onClick: () => genAppendTo("camera", t) }, t))))), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Lighting ", /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-gentermbtn", onClick: () => genTogglePal("lighting") }, "+ terms")), /* @__PURE__ */ React.createElement(
        "input",
        {
          className: "lm-in",
          value: c.lighting || "",
          placeholder: "e.g. moonlit, soft haze",
          onChange: (ev) => dfPatch((cc) => ({ ...cc, lighting: ev.target.value }))
        }
      ), genPalFor === "lighting" && /* @__PURE__ */ React.createElement("div", { className: "lm-gentermpal" }, LIGHTING_PALETTE.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lm-genchip", onClick: () => genAppendTo("lighting", t) }, t))), /* @__PURE__ */ React.createElement("div", { className: "lm-row2" }, /* @__PURE__ */ React.createElement("div", { className: "lm-col" }, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Transition in ", /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-gentermbtn", onClick: () => genTogglePal("transIn") }, "+ terms")), /* @__PURE__ */ React.createElement(
        "input",
        {
          className: "lm-in",
          value: c.transIn || "",
          placeholder: "cut, dissolve",
          onChange: (ev) => dfPatch((cc) => ({ ...cc, transIn: ev.target.value }))
        }
      ), genPalFor === "transIn" && /* @__PURE__ */ React.createElement("div", { className: "lm-gentermpal" }, TRANS_PALETTE.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lm-genchip", onClick: () => dfPatch((cc) => ({ ...cc, transIn: t })) }, t)))), /* @__PURE__ */ React.createElement("div", { className: "lm-col" }, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Transition out ", /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-gentermbtn", onClick: () => genTogglePal("transOut") }, "+ terms")), /* @__PURE__ */ React.createElement(
        "input",
        {
          className: "lm-in",
          value: c.transOut || "",
          placeholder: "cut, dissolve",
          onChange: (ev) => dfPatch((cc) => ({ ...cc, transOut: ev.target.value }))
        }
      ), genPalFor === "transOut" && /* @__PURE__ */ React.createElement("div", { className: "lm-gentermpal" }, TRANS_PALETTE.map((t) => /* @__PURE__ */ React.createElement("span", { key: t, className: "lm-genchip", onClick: () => dfPatch((cc) => ({ ...cc, transOut: t })) }, t))))), /* @__PURE__ */ React.createElement("div", { className: "lm-genrefline" }, (c.cast || []).length, " cast \xB7 ", (c.refs || []).length, " refs", !modeSendsRefs(c.mode) && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("br", null), modeSendsLine(c.mode))), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab", style: { marginTop: 12 } }, showClose ? "Start / end frame" : "Start frame"), /* @__PURE__ */ React.createElement("div", { className: "lm-genframerow" }, /* @__PURE__ */ React.createElement("div", { className: "lm-genframecol" }, /* @__PURE__ */ React.createElement("div", { className: "lm-genframe" }, frameSrc(c.openFrame) ? /* @__PURE__ */ React.createElement("img", { src: frameSrc(c.openFrame), alt: "opening frame" }) : "no frame", /* @__PURE__ */ React.createElement("span", { className: "lm-genframetag" }, positionTag(dfLive, project, imgSrc, "openFrame") || "\u2014"))), showClose && /* @__PURE__ */ React.createElement("div", { className: "lm-genframecol" }, /* @__PURE__ */ React.createElement("div", { className: "lm-genframe" }, frameSrc(c.closeFrame) ? /* @__PURE__ */ React.createElement("img", { src: frameSrc(c.closeFrame), alt: "closing frame" }) : "no frame", /* @__PURE__ */ React.createElement("span", { className: "lm-genframetag" }, positionTag(dfLive, project, imgSrc, "closeFrame") || "\u2014")))), /* @__PURE__ */ React.createElement("div", { className: "lm-hint" }, "frames are attached on Shot Detail \u2014 this is a preview only"), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab", style: { marginTop: 12 } }, "What will be sent"), /* @__PURE__ */ React.createElement("div", { className: "lm-genpreview" }, shotText(dfLive, project, imgSrc)), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab", style: { marginTop: 12 } }, "Model"), /* @__PURE__ */ React.createElement("div", { className: "lm-genmodelrow" }, /* @__PURE__ */ React.createElement("span", { className: "lm-genmodelthumb" }), "PixAI Motion v2"), /* @__PURE__ */ React.createElement("div", { className: "lm-gencaps" }, ["15s", "multi-ref", "audio", "end-frame"].map((cap) => /* @__PURE__ */ React.createElement("span", { key: cap, className: "lm-gencap" }, cap))), /* @__PURE__ */ React.createElement("div", { className: "lm-row2" }, /* @__PURE__ */ React.createElement("div", { className: "lm-col" }, /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Channel"), /* @__PURE__ */ React.createElement(
        "select",
        {
          className: "lm-gensel",
          value: c.isPrivate ? "enhanced" : "normal",
          onChange: (ev) => dfPatch((cc) => ({ ...cc, isPrivate: ev.target.value === "enhanced" }))
        },
        /* @__PURE__ */ React.createElement("option", { value: "normal" }, "Normal"),
        /* @__PURE__ */ React.createElement("option", { value: "enhanced" }, "\u{1F451} Enhanced")
      )), /* @__PURE__ */ React.createElement("div", { className: "lm-col" }, /* @__PURE__ */ React.createElement("div", { className: "lm-hint", style: { marginTop: 22 } }, "Please keep creations SFW"))), /* @__PURE__ */ React.createElement("label", { className: "lm-check", style: { marginTop: 6 } }, /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "checkbox",
          checked: !!c.audioGen,
          onChange: (ev) => dfPatch((cc) => ({ ...cc, audioGen: ev.target.checked }))
        }
      ), "Generate audio (spoken lines become voiceover)"), c.audioGen && /* @__PURE__ */ React.createElement(
        "select",
        {
          className: "lm-gensel",
          value: c.audioLanguage || "english",
          onChange: (ev) => dfPatch((cc) => ({ ...cc, audioLanguage: ev.target.value }))
        },
        /* @__PURE__ */ React.createElement("option", { value: "english" }, "English"),
        /* @__PURE__ */ React.createElement("option", { value: "japanese" }, "Japanese"),
        /* @__PURE__ */ React.createElement("option", { value: "chinese" }, "Chinese"),
        /* @__PURE__ */ React.createElement("option", { value: "korean" }, "Korean"),
        /* @__PURE__ */ React.createElement("option", { value: "none" }, "SE only (no dialogue)")
      ), /* @__PURE__ */ React.createElement("div", { className: "lm-gencost" }, /* @__PURE__ */ React.createElement("span", { className: "lm-gencosttext", title: costTitle }, costText), /* @__PURE__ */ React.createElement("span", { className: "lm-hint" }, "uploads are free \xB7 one job at a time")), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-genbtn", disabled: genBusy || genSubmitting || gp.noInput, onClick: genSubmit }, genBusy ? "already rendering\u2026" : genSubmitting ? "submitting\u2026" : "Generate video"), /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          className: "lm-genexisting",
          disabled: genBusy,
          onClick: () => useExistingVideo(dfLive)
        },
        "Use an existing video instead"
      ))), pickerMounted && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement(
        "div",
        {
          className: "lm-scrim" + (pickerClosing ? " closing" : ""),
          style: { display: pickerOpen || pickerClosing ? "block" : "none" },
          onClick: closePicker
        }
      ), /* @__PURE__ */ React.createElement(
        "div",
        {
          className: "lm-pick-sheet" + (pickerClosing ? " closing" : ""),
          style: { display: pickerOpen || pickerClosing ? "flex" : "none" }
        },
        /* @__PURE__ */ React.createElement("div", { className: "lm-sheethandle" }),
        /* @__PURE__ */ React.createElement("div", { className: "lm-pick-head" }, /* @__PURE__ */ React.createElement("span", { className: "lm-pick-t" }, "Models & LoRAs"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-df-close", onClick: closePicker, "aria-label": "Close" }, "\u2715")),
        /* @__PURE__ */ React.createElement("div", { className: "lm-tabsrow" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-tabbtn" + (pickerKind === "base" ? " on" : ""), onClick: () => setPickerKind("base") }, "Models"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-tabbtn" + (pickerKind === "lora" ? " on" : ""), onClick: () => setPickerKind("lora") }, "LoRAs")),
        /* @__PURE__ */ React.createElement("div", { className: "lm-pick-body" }, /* @__PURE__ */ React.createElement(
          ModelPicker,
          {
            kind: "base",
            visible: pickerKind === "base",
            value: imgModel,
            onPick: onBasePick,
            style: { display: pickerKind === "base" ? "flex" : "none" }
          }
        ), /* @__PURE__ */ React.createElement(
          ModelPicker,
          {
            kind: "lora",
            multi: true,
            baseType: imgModel && imgModel.model_type || "",
            visible: pickerKind === "lora",
            selected: imgLoras,
            onToggle: onLoraPick,
            style: { display: pickerKind === "lora" ? "flex" : "none" }
          }
        ))
      )));
    })(), reviewOpen && reviewLive && (() => {
      const c = reviewLive.c;
      const dur = reviewDur || durOf(c) || 0;
      const trimIn = c.trimIn || 0;
      const trimOut = c.trimOut != null ? c.trimOut : dur;
      const pctOf = (s) => dur ? Math.max(0, Math.min(100, s / dur * 100)) : 0;
      const fmtT = (s) => (s || 0).toFixed(1) + "s";
      const crop = c.crop || { x: 0.35, y: 0.35, w: 0.3, h: 0.3 };
      const trimFrac = (e) => {
        const r = reviewTrimTrackRef.current.getBoundingClientRect();
        return r.width ? Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) : 0;
      };
      const trimInStart = (e) => {
        try {
          e.currentTarget.setPointerCapture(e.pointerId);
        } catch (err) {
        }
        reviewTrimDragRef.current = "in";
        trimInMove(e);
      };
      const trimInMove = (e) => {
        if (reviewTrimDragRef.current !== "in" || !dur) return;
        const outFrac = trimOut / dur;
        const newFrac = Math.max(0, Math.min(trimFrac(e), outFrac - 0.05));
        const t = newFrac * dur;
        reviewPatch((cc) => ({ ...cc, trimIn: t }));
        const v = reviewVidRef.current;
        if (v) v.currentTime = t;
        setReviewCur(t);
      };
      const trimInEnd = () => {
        reviewTrimDragRef.current = null;
      };
      const trimOutStart = (e) => {
        try {
          e.currentTarget.setPointerCapture(e.pointerId);
        } catch (err) {
        }
        reviewTrimDragRef.current = "out";
        trimOutMove(e);
      };
      const trimOutMove = (e) => {
        if (reviewTrimDragRef.current !== "out" || !dur) return;
        const inFrac = trimIn / dur;
        const newFrac = Math.min(1, Math.max(trimFrac(e), inFrac + 0.05));
        const t = newFrac * dur;
        reviewPatch((cc) => ({ ...cc, trimOut: t }));
        const v = reviewVidRef.current;
        if (v) v.currentTime = t;
        setReviewCur(t);
      };
      const trimOutEnd = () => {
        reviewTrimDragRef.current = null;
      };
      const scrubFrac2 = (e) => {
        const r = e.currentTarget.getBoundingClientRect();
        return r.width ? Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) : 0;
      };
      const scrubTo2 = (e) => {
        if (!dur) return;
        const t = scrubFrac2(e) * dur;
        const v = reviewVidRef.current;
        if (v) v.currentTime = t;
        setReviewCur(t);
      };
      const scrubStart = (e) => {
        try {
          e.currentTarget.setPointerCapture(e.pointerId);
        } catch (err) {
        }
        reviewScrubDragRef.current = true;
        scrubTo2(e);
      };
      const scrubMove = (e) => {
        if (reviewScrubDragRef.current) scrubTo2(e);
      };
      const scrubEnd = () => {
        reviewScrubDragRef.current = false;
      };
      const cropFrac = (e) => {
        const r = e.currentTarget.parentElement.getBoundingClientRect();
        const x = e.clientX - r.left, y = e.clientY - r.top;
        return { x: Math.max(0, Math.min(1, x / r.width)), y: Math.max(0, Math.min(1, y / r.height)) };
      };
      const cropDragStart = (e) => {
        try {
          e.currentTarget.setPointerCapture(e.pointerId);
        } catch (err) {
        }
        reviewCropDragRef.current = true;
      };
      const cropDragMove = (e) => {
        if (!reviewCropDragRef.current) return;
        const f = cropFrac(e);
        reviewPatch((cc) => ({ ...cc, crop: {
          x: Math.max(0, Math.min(f.x - 0.15, 0.68)),
          y: Math.max(0, Math.min(f.y - 0.15, 0.68)),
          w: 0.3,
          h: 0.3
        } }));
      };
      const cropDragEnd = () => {
        reviewCropDragRef.current = false;
      };
      const togglePlay = () => {
        const v = reviewVidRef.current;
        if (!v) return;
        if (reviewPlaying) {
          v.pause();
          setReviewPlaying(false);
          return;
        }
        if (v.currentTime < trimIn || v.currentTime >= trimOut) v.currentTime = trimIn;
        v.play().catch(() => {
        });
        setReviewPlaying(true);
      };
      const onReviewTimeUpdate = (e) => {
        const cur = e.currentTarget.currentTime;
        setReviewCur(cur);
        if (reviewPlaying && trimOut > trimIn && cur >= trimOut - 0.02) {
          e.currentTarget.currentTime = trimIn;
        }
      };
      const nudge = (delta) => {
        const v = reviewVidRef.current;
        if (!v || !dur) return;
        if (reviewPlaying) {
          v.pause();
          setReviewPlaying(false);
        }
        const t = Math.max(0, Math.min(dur, v.currentTime + delta));
        v.currentTime = t;
        setReviewCur(t);
      };
      const doSplit = () => {
        const v = reviewVidRef.current;
        if (!v) return;
        const t = v.currentTime;
        if (t > trimIn + 0.15 && t < trimOut - 0.15) {
          splitShot(reviewLive, t);
          closeReview();
        } else alert("Move the playhead to where you want the cut first (not at either edge).");
      };
      return /* @__PURE__ */ React.createElement("div", { className: "lm-review" }, /* @__PURE__ */ React.createElement("div", { className: "lm-gen-top" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-gen-back", onClick: closeReview }, "\u2039 ", reviewLive.code), /* @__PURE__ */ React.createElement("span", { className: "lm-gen-title" }, "Review & trim"), /* @__PURE__ */ React.createElement("span", { className: "lm-fill" }), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-df-close", title: "Close", onClick: closeReview }, "\u2715")), /* @__PURE__ */ React.createElement("div", { className: "lm-df-body" }, /* @__PURE__ */ React.createElement("div", { className: "lm-review-previewwrap" }, /* @__PURE__ */ React.createElement(
        "video",
        {
          key: c.id,
          ref: reviewVidRef,
          className: "lm-review-video",
          src: "/video-file/" + c.resultMid,
          playsInline: true,
          preload: "metadata",
          onLoadedMetadata: (ev) => setReviewDur(ev.currentTarget.duration || 0),
          onTimeUpdate: onReviewTimeUpdate,
          onEnded: () => setReviewPlaying(false)
        }
      ), reviewCropping && /* @__PURE__ */ React.createElement(
        "div",
        {
          className: "lm-review-croprect",
          style: { left: crop.x * 100 + "%", top: crop.y * 100 + "%", width: crop.w * 100 + "%", height: crop.h * 100 + "%" },
          onPointerDown: cropDragStart,
          onPointerMove: cropDragMove,
          onPointerUp: cropDragEnd
        },
        /* @__PURE__ */ React.createElement("div", { className: "lm-review-crophandle" })
      ), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-review-playbtn", onClick: togglePlay }, reviewPlaying ? "\u23F8" : "\u25B6")), /* @__PURE__ */ React.createElement("div", { className: "lm-review-transport" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-review-transportbtn", onClick: () => nudge(-0.25) }, "\u23EA"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-review-transportbtn", onClick: togglePlay }, reviewPlaying ? "\u23F8" : "\u25B6"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-review-transportbtn", onClick: () => nudge(0.25) }, "\u23E9")), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Scrub"), /* @__PURE__ */ React.createElement(
        "div",
        {
          className: "lm-review-scrubtrack",
          onPointerDown: scrubStart,
          onPointerMove: scrubMove,
          onPointerUp: scrubEnd
        },
        /* @__PURE__ */ React.createElement("div", { className: "lm-review-scrubfill", style: { width: pctOf(reviewCur) + "%" } }),
        /* @__PURE__ */ React.createElement("div", { className: "lm-review-scrubhandle", style: { left: pctOf(reviewCur) + "%" } })
      ), /* @__PURE__ */ React.createElement("span", { className: "lm-microlab" }, "Trim ", /* @__PURE__ */ React.createElement("span", { className: "lm-hint", style: { display: "inline", padding: 0 } }, "drag the in/out handles")), /* @__PURE__ */ React.createElement("div", { className: "lm-review-trimtrack", ref: reviewTrimTrackRef }, /* @__PURE__ */ React.createElement("div", { className: "lm-review-trimrange", style: { left: pctOf(trimIn) + "%", right: 100 - pctOf(trimOut) + "%" } }), /* @__PURE__ */ React.createElement(
        "div",
        {
          className: "lm-review-trimhandle",
          style: { left: pctOf(trimIn) + "%" },
          onPointerDown: trimInStart,
          onPointerMove: trimInMove,
          onPointerUp: trimInEnd
        }
      ), /* @__PURE__ */ React.createElement(
        "div",
        {
          className: "lm-review-trimhandle",
          style: { left: pctOf(trimOut) + "%" },
          onPointerDown: trimOutStart,
          onPointerMove: trimOutMove,
          onPointerUp: trimOutEnd
        }
      )), /* @__PURE__ */ React.createElement("div", { className: "lm-review-trimreadout" }, fmtT(trimIn), " \u2192 ", fmtT(trimOut)), /* @__PURE__ */ React.createElement("div", { className: "lm-review-actionsrow" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-addrefbtn", style: { whiteSpace: "nowrap" }, onClick: doSplit }, "\u2702 Split at playhead"), /* @__PURE__ */ React.createElement(
        "button",
        {
          type: "button",
          className: "lm-review-cropbtn" + (reviewCropping ? " on" : ""),
          onClick: () => setReviewCropping((v) => !v)
        },
        "\u26F6 ",
        reviewCropping ? "Done" : "Crop"
      ))));
    })(), fcOpen && dfLive && (() => {
      const c = dfLive.c;
      const fcSrc = frameSrc(c.openFrame);
      const fcGroups = AF ? AF.groups() : [];
      const activeRec = fcActive && AF ? AF.get(fcActive) || {} : null;
      const activeName = activeRec ? activeRec.name || fcActive : null;
      return /* @__PURE__ */ React.createElement("div", { className: "lm-fc", key: c.id }, /* @__PURE__ */ React.createElement("div", { className: "lm-gen-top" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-gen-back", onClick: closeFilterCompare }, "\u2039 ", dfLive.code), /* @__PURE__ */ React.createElement("span", { className: "lm-gen-title" }, "Art filters"), /* @__PURE__ */ React.createElement("span", { className: "lm-fill" }), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-df-close", title: "Close", onClick: closeFilterCompare }, "\u2715")), /* @__PURE__ */ React.createElement("div", { className: "lm-df-body" }, !AF ? /* @__PURE__ */ React.createElement("div", { className: "lm-empty" }, "The art-filter library did not load on this page.") : /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "lm-fc-previewrow" }, /* @__PURE__ */ React.createElement("div", { className: "lm-fc-previewcol" }, /* @__PURE__ */ React.createElement("div", { className: "lm-fc-previewbox" }, fcSrc ? /* @__PURE__ */ React.createElement("img", { className: "lm-fc-img", src: fcSrc, alt: "original" }) : /* @__PURE__ */ React.createElement("div", { className: "lm-empty" }, "No open-frame image yet")), /* @__PURE__ */ React.createElement("div", { className: "lm-fc-previewcap" }, "Original")), /* @__PURE__ */ React.createElement("div", { className: "lm-fc-previewcol" }, /* @__PURE__ */ React.createElement("div", { className: "lm-fc-previewbox" }, /* @__PURE__ */ React.createElement("div", { className: "lm-fc-stage", ref: fcStageRef }, fcSrc ? /* @__PURE__ */ React.createElement("img", { ref: fcImgRef, className: "lm-fc-img", src: fcSrc, alt: "preview" }) : /* @__PURE__ */ React.createElement("div", { className: "lm-empty" }, "No open-frame image yet"))), /* @__PURE__ */ React.createElement("div", { className: "lm-fc-previewcap" }, "Preview \xB7 ", /* @__PURE__ */ React.createElement("b", null, activeName || "no filter")))), fcGroups.map((g) => /* @__PURE__ */ React.createElement("div", { key: g.source }, /* @__PURE__ */ React.createElement("div", { className: "lm-fc-grouplabel" }, g.label), /* @__PURE__ */ React.createElement("div", { className: "lm-fc-grid" }, g.ids.map((id) => {
        const rec = AF.get(id) || {};
        return /* @__PURE__ */ React.createElement(
          "button",
          {
            type: "button",
            key: id,
            className: "lm-fc-tile" + (fcActive === id ? " on" : ""),
            onClick: () => setFcActive((cur) => cur === id ? null : id),
            title: (rec.name || id) + " \xB7 free, applied in your browser" + (rec.note ? " \u2014 " + rec.note : "")
          },
          /* @__PURE__ */ React.createElement(
            "div",
            {
              className: "lm-fc-swatch",
              ref: (el) => {
                if (el && !el._mgafPainted) {
                  AF.renderSwatch(el, id);
                  el._mgafPainted = true;
                }
              }
            }
          ),
          /* @__PURE__ */ React.createElement("div", { className: "lm-fc-name" }, (rec.name || id).replace("Filter ", ""))
        );
      })))), /* @__PURE__ */ React.createElement("div", { className: "lm-fc-sliderwrap" }, /* @__PURE__ */ React.createElement("div", { className: "lm-fc-sliderlab" }, "Strength \u2014 ", Number(fcStrength).toFixed(2)), /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "range",
          min: "0",
          max: "1",
          step: "0.05",
          className: "lm-fc-range",
          value: fcStrength,
          onChange: (ev) => setFcStrength(parseFloat(ev.target.value))
        }
      )), /* @__PURE__ */ React.createElement("div", { className: "lm-fc-sliderwrap" }, /* @__PURE__ */ React.createElement("div", { className: "lm-fc-sliderlab" }, "Angle \u2014 ", fcAngle, "\xB0"), /* @__PURE__ */ React.createElement(
        "input",
        {
          type: "range",
          min: "0",
          max: "360",
          step: "1",
          className: "lm-fc-range",
          value: fcAngle,
          onChange: (ev) => setFcAngle(parseInt(ev.target.value, 10))
        }
      )), /* @__PURE__ */ React.createElement("div", { className: "lm-fc-btnrow" }, /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-fc-btn", onClick: fcClear }, "No filter"), /* @__PURE__ */ React.createElement("button", { type: "button", className: "lm-fc-btn primary", onClick: fcSave }, "Save")), /* @__PURE__ */ React.createElement("div", { className: "lm-fc-spendnote" }, activeName || "No filter", " \xB7 nothing sent, nothing spent"))));
    })());
  }
  function useProjectStore(setSelShot) {
    const [project, setProject] = useState2(null);
    const [thumbs, setThumbs] = useState2({});
    const [busy, setBusy] = useState2(false);
    const [activeId, setActiveId] = useState2(null);
    const [projList, setProjList] = useState2([]);
    const [projMenu, setProjMenu] = useState2(false);
    const saveTimer = useRef2(null);
    const castImported = useRef2(false);
    const readProjList = useCallback2(async () => {
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
    const flushSave = useCallback2(async (id, p) => {
      if (hasStore && id && p) await sSet(PPRE + id, JSON.stringify(p));
    }, []);
    useEffect2(() => {
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
    const openProject = useCallback2(async (id) => {
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
    const newProject = useCallback2(async () => {
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
    const duplicateProject = useCallback2(async () => {
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
    const deleteProject = useCallback2(async (id) => {
      const list = await readProjList();
      if (list.length <= 1) {
        window.alert("This is your only storyboard \u2014 make another before deleting this one.");
        return;
      }
      const tgt = list.find((x) => x.id === id);
      if (!window.confirm(`Delete "${tgt && tgt.name || "this storyboard"}"? This can't be undone.`)) return;
      if (id === activeId) {
        let next = null, p = null, anyReadFailed = false;
        for (const cand of list) {
          if (cand.id === id) continue;
          try {
            const got = await sGetX(PPRE + cand.id);
            if (got.failed) {
              anyReadFailed = true;
              continue;
            }
            if (got.value) {
              p = JSON.parse(got.value);
              next = cand;
              break;
            }
          } catch {
            anyReadFailed = true;
          }
        }
        if (!p) {
          window.alert(anyReadFailed ? "Couldn't read your other storyboards, so nothing was deleted. Check the server and try again." : "Couldn't open another storyboard, so nothing was deleted. Try again.");
          return;
        }
        clearTimeout(saveTimer.current);
        await sDel(PPRE + id);
        await sSet(ACTIVE_KEY, next.id);
        setActiveId(next.id);
        setProject(p);
        setSelShot(null);
      } else {
        await sDel(PPRE + id);
      }
      await readProjList();
      setProjMenu(false);
    }, [activeId, readProjList, setSelShot]);
    const projectApi = { activeId, projList, projMenu, setProjMenu, readProjList, openProject, newProject, duplicateProject, deleteProject };
    useEffect2(() => {
      if (!project || castImported.current) return;
      castImported.current = true;
      const ids = parseCastIdsFromSearch(location.search).filter(isCatalogMediaId);
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
    useEffect2(() => {
      if (!project || !hasStore || !activeId) return;
      setBusy(true);
      clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(async () => {
        await sSet(PPRE + activeId, JSON.stringify(project));
        setBusy(false);
      }, 600);
      return () => clearTimeout(saveTimer.current);
    }, [project, activeId]);
    const storeThumb = useCallback2(async (file) => {
      const data2 = await fileToThumb(file);
      const id = uid();
      setThumbs((t) => ({ ...t, [id]: data2 }));
      if (hasStore) await sSet(TPRE + id, data2);
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
    const [open2, setOpen2] = useState2({});
    const setCard = useCallback2((aId, cId, fn) => setProject((p) => patchCard(p, aId, cId, fn)), [setProject]);
    const setAct = useCallback2((aId, patch2) => setProject((p) => patchAct(p, aId, patch2)), [setProject]);
    const setAssets = useCallback2((fn) => setProject((p) => patchAssets(p, fn)), [setProject]);
    const setCardStatus = (cardId, patch2) => setProject((p) => patchCardById(p, cardId, patch2));
    const addCard = (aId) => {
      const c = newCard();
      setProject((p) => appendCardToAct(p, aId, c));
      setOpen2((o) => ({ ...o, [c.id]: true }));
    };
    const importFootage = (mediaId, duration) => {
      const c = newCard(importedFootagePatch(mediaId, duration));
      setProject((p) => landInFirstAct(p, c, uid()));
      fetch("/api/loom/import-frames", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_media_id: mediaId })
      }).then((r) => r.json()).then((d) => {
        if (!d || d.error) return;
        const patch2 = importedFramesPatch(d.first_media_id, d.last_media_id);
        if (Object.keys(patch2).length) setCardStatus(c.id, patch2);
      }).catch(() => {
      });
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
    const setRef = (aId, cId, rId, patch2) => setProject((p) => patchRef(p, aId, cId, rId, patch2));
    const delRef = (aId, cId, ref) => setProject((p) => removeRef(p, aId, cId, ref.id));
    const splitShot = (entry, t) => setProject((p) => splitCardAt(p, entry.a.id, entry.c.id, t, uid()));
    return {
      open: open2,
      setOpen: setOpen2,
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
  function useGenerationPipeline({ project, thumbs, setCard, setCardStatus, setAssets, openPick, activeId, mobileUI }) {
    const [genState, setGenState] = useState2({});
    const resumedRef = useRef2({});
    const [genImgState, setGenImgState] = useState2({});
    const [imgModel, setImgModel] = useState2(null);
    const [imgLoras, setImgLoras] = useState2([]);
    const [imgAdv, setImgAdv] = useState2(() => ({
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
    const [modelDefaults, setModelDefaults] = useState2(null);
    const [genEditState, setGenEditState] = useState2({});
    const [genRefState, setGenRefState] = useState2({});
    const [genFixState, setGenFixState] = useState2({});
    const [batching, setBatching] = useState2(false);
    const [batchTally, setBatchTally] = useState2(null);
    const setBatchOutcome = (cardId, outcome) => setBatchTally((prev) => prev && prev.ids.has(cardId) ? { ...prev, outcomes: { ...prev.outcomes, [cardId]: outcome } } : prev);
    const imgSrc = (thumbId, source) => thumbId ? thumbs[thumbId] : source && (source.startsWith("http") || source.startsWith("data:") || isCatalogMediaId(source)) ? source : null;
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
          setCardStatus(c.id, { status: "error", pendingTaskId: null, genStartedAt: null });
          return { ok: false, reason: "submit-failed" };
        }
        const startedAt = Date.now();
        setCardStatus(c.id, { pendingTaskId: d.task_id, genStartedAt: startedAt });
        pollShot(c.id, d.task_id, startedAt);
        if (window.Jobs && window.Jobs.register) window.Jobs.register(d.task_id, entry.code + " \xB7 " + (c.title || "untitled"));
        return { ok: true, taskId: d.task_id };
      } catch {
        setGenState((s) => ({ ...s, [c.id]: { phase: "error", msg: "network error" } }));
        setCardStatus(c.id, { status: "error", pendingTaskId: null, genStartedAt: null });
        return { ok: false, reason: "network" };
      }
    };
    const POLL_SLOW_AT_MS = 20 * 60 * 1e3;
    const POLL_SLOW_MS = 20 * 1e3;
    const POLL_STALE_AT_MS = 90 * 60 * 1e3;
    const POLL_STALE_MS = 3 * 60 * 1e3;
    const POLL_CEILING_MS2 = 6 * 60 * 60 * 1e3;
    const pollShot = (cardId, tid, existingStartedAt) => {
      setGenState((s) => ({ ...s, [cardId]: { phase: "running", msg: "Rendering\u2026 (task " + String(tid).slice(-6) + ")" } }));
      const startedAt = existingStartedAt || Date.now();
      const pause = () => {
        setGenState((s) => ({ ...s, [cardId]: {
          phase: "paused",
          msg: "Paused auto-checking after " + elapsedLabel(POLL_CEILING_MS2) + " with no result \u2014 click to check again, or check the task on pixai.art (task " + String(tid).slice(-6) + ")"
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
        } else if (elapsed > POLL_CEILING_MS2) {
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
        if (elapsed > POLL_CEILING_MS2) {
          pause();
          return;
        }
        setTimeout(tick, elapsed > POLL_STALE_AT_MS ? POLL_STALE_MS : elapsed > POLL_SLOW_AT_MS ? POLL_SLOW_MS : 5e3);
      });
      setTimeout(tick, 2500);
    };
    useEffect2(() => {
      if (!project) return;
      (project.acts || []).forEach((a) => (a.cards || []).forEach((c) => {
        if (c.status === "wip" && c.pendingTaskId && !resumedRef.current[c.pendingTaskId]) {
          resumedRef.current[c.pendingTaskId] = true;
          pollShot(c.id, c.pendingTaskId, c.genStartedAt);
        }
      }));
    }, [activeId, mobileUI]);
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
        if (cls.phase === "done") {
          setState((s) => ({ ...s, [cardId]: { phase: "done", msg: "Done", mid: cls.mid } }));
          if (window.JobsCard && window.JobsCard.refresh) window.JobsCard.refresh();
        } else if (cls.phase === "failed") {
          setState((s) => ({ ...s, [cardId]: { phase: "error", msg: cls.msg } }));
          if (window.JobsCard && window.JobsCard.refresh) window.JobsCard.refresh();
        } else again(4e3);
      }).catch(() => again(5e3));
      const again = (ms) => {
        if (Date.now() - startedAt > POLL_CEILING_MS2) {
          setState((s) => ({ ...s, [cardId]: {
            phase: "error",
            msg: "Stopped checking after " + elapsedLabel(POLL_CEILING_MS2) + " \u2014 the task may still be running; check it on pixai.art (task " + String(tid).slice(-6) + ")"
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
        if (window.Jobs && window.Jobs.register) window.Jobs.register(d.task_id, "Image \xB7 " + entry.code + " \xB7 " + (c.title || "untitled"));
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
    const runGen = async (setState, cardId, endpoint, body, priceBody, label, jobLabel) => {
      if (priceBody && !await confirmSpend(priceBody, label)) return;
      setState((s) => ({ ...s, [cardId]: { phase: "submitting", msg: "Submitting\u2026" } }));
      const poll2 = (tid) => pollTaskWithCeiling(tid, setState, cardId);
      try {
        const r = await fetch(endpoint, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        const d = await r.json();
        if (d.error || !d.task_id) {
          setState((s) => ({ ...s, [cardId]: { phase: "error", msg: d.error ? friendlyGenErr(d.error) : "submit failed" } }));
          return;
        }
        if (window.Jobs && window.Jobs.register) window.Jobs.register(d.task_id, jobLabel);
        setState((s) => ({ ...s, [cardId]: { phase: "running", msg: "Generating\u2026" } }));
        poll2(d.task_id);
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
        `Edit the open frame of ${c.title || "this shot"}?`,
        "Edit \xB7 " + entry.code + " \xB7 " + (c.title || "untitled")
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
        `Generate a still for ${c.title || "this shot"} from ${refs.length} reference${refs.length === 1 ? "" : "s"}?`,
        // The reference COUNT is the one fact this path is about (and the one its own confirm
        // already surfaces), so it rides in the row rather than being lost to "Reference".
        "Reference \xD7" + refs.length + " \xB7 " + entry.code + " \xB7 " + (c.title || "untitled")
      );
    };
    const genFix = async (entry, scaledBoxes) => {
      const c = entry.c;
      const src = c.openFrame && c.openFrame.mediaId;
      if (!src) {
        setGenFixState((s) => ({ ...s, [c.id]: { phase: "error", msg: "the open frame needs a gallery image first (route one from the Image tab, or pick it into the frame)" } }));
        return;
      }
      if (!scaledBoxes || !scaledBoxes.length) {
        setGenFixState((s) => ({ ...s, [c.id]: { phase: "error", msg: "drag a box over a hand or face first" } }));
        return;
      }
      let pr = null;
      try {
        const r = await fetch("/api/price", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: "fix", source: src, boxes: scaledBoxes })
        });
        pr = await r.json();
      } catch {
        pr = null;
      }
      const priced = pr && typeof pr.cost === "number" ? pr.cost : null;
      const quote = priced == null ? "The price could not be verified, and a Fix ALWAYS spends credits (no free card can ever cover it)." : "This will spend " + Number(priced).toLocaleString() + " credits \u2014 a Fix is never covered by a free card.";
      if (!window.confirm(
        "Repair " + scaledBoxes.length + " area" + (scaledBoxes.length === 1 ? "" : "s") + "?\n\n" + quote
      )) return;
      runGen(
        setGenFixState,
        c.id,
        "/api/fix",
        { source: src, boxes: scaledBoxes },
        null,
        "",
        "Fix \xB7 " + entry.code + " \xB7 " + (c.title || "untitled")
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
    const [priceCache, setPriceCache] = useState2({});
    const priceInFlightRef = useRef2({});
    const ensurePriced = useCallback2((entry, force) => {
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
    const { notDone, notDoneFp } = useMemo2(() => {
      const boardEntries = project ? flat(project) : [];
      const nd = boardEntries.filter((e) => e.c.status !== "done");
      const fp = nd.map((e) => e.c.id + ":" + priceFingerprint(shotPayload2(e))).join("|");
      return { notDone: nd, notDoneFp: fp };
    }, [project]);
    const priceDebounceRef = useRef2(null);
    useEffect2(() => {
      clearTimeout(priceDebounceRef.current);
      priceDebounceRef.current = setTimeout(() => notDone.forEach((e) => ensurePriced(e)), PRICE_DEBOUNCE_MS);
      return () => clearTimeout(priceDebounceRef.current);
    }, [notDoneFp]);
    const refreshEstimate = useCallback2(() => notDone.forEach((e) => ensurePriced(e, true)), [notDone, ensurePriced]);
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
      genFixState,
      setGenFixState,
      batching,
      batchTally,
      // priceShot exposed (mobile-generate-screen pass, 2026-08-03): the SAME read-only
      // /api/price check generateShot/confirmSpend/batchGenerate already use internally --
      // Loom Mobile's own Generate screen needs a per-shot cost PREVIEW to show before the
      // owner ever taps the real submit button, and this is that exact function, not a new
      // fetch/pricing implementation. It was already defined here; only its exposure is new.
      generateShot,
      pollShot,
      useExistingVideo,
      genImage,
      routeImg,
      genEdit,
      genRef,
      genFix,
      routeGen,
      batchGenerate,
      costEstimate,
      refreshEstimate,
      priceShot
    };
  }
  function useExportPipeline(project, thumbs) {
    const [seq2, setSeq] = useState2(null);
    const [exp, setExp] = useState2(null);
    const exportPoll = useRef2(null);
    const download = (text, name, type) => {
      const url = URL.createObjectURL(new Blob([text], { type }));
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1e3);
    };
    const exportAll = () => download(
      buildShotListText(project, fmt3, actLetter, shotText),
      `${project.name.replace(/\s+/g, "_")}_shotlist.txt`,
      "text/plain"
    );
    const exportJSON = () => download(JSON.stringify({ project, thumbs }, null, 2), `${project.name.replace(/\s+/g, "_")}_backup.json`, "application/json");
    const [bundling, setBundling] = useState2(false);
    const [bundleMissing, setBundleMissing] = useState2(null);
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
        const report = bundleMissingReport(project, r.headers.get("X-Bundle-Missing-Count"), r.headers.get("X-Bundle-Missing"));
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `${project.name.replace(/\s+/g, "_")}_bundle.zip`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1e3);
        if (report.total) setBundleMissing(report);
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
      seq: seq2,
      exp,
      playSequence,
      exportCut,
      cancelExport,
      closeExport,
      closeSequence,
      exportAll,
      exportJSON,
      exportBundle,
      bundling,
      bundleMissing,
      closeBundleMissing: () => setBundleMissing(null)
    };
  }
  function App() {
    const [selShot, setSelShot] = useState2(null);
    const [mobileUI, setMobileUI] = useLocalToggle(MOBILE_UI_KEY, false);
    const [draftCard, setDraftCard] = useState2(() => ({
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
    const [draftTarget, setDraftTarget] = useState2("");
    const [draftAttachedInfo, setDraftAttachedInfo] = useState2(null);
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
      open: open2,
      setOpen: setOpen2,
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
    const [pickCb, setPickCb] = useState2(null);
    const [pickKind, setPickKind] = useState2("image");
    const [pickAllowType, setPickAllowType] = useState2(false);
    const [importOpen, setImportOpen] = useState2(false);
    const [showHelp, setShowHelp] = useState2(false);
    const [showGuide, setShowGuide] = useState2(() => {
      try {
        return !localStorage.getItem("loom_guide_seen");
      } catch (e) {
        return true;
      }
    });
    const [showCast, setShowCast] = useState2(true);
    const openPick = useCallback2((cb, kind, allowType) => {
      setPickKind(kind || "image");
      setPickAllowType(!!allowType);
      setPickCb(() => cb);
    }, []);
    const onGalleryPick = (m) => {
      const cb = pickCb;
      setPickCb(null);
      if (cb) cb(m.media_id, m.thumb, m.is_video, m.duration, m.is_nsfw);
    };
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
      // genFixState/setGenFixState/genFix -- seventh increment (2026-08-03), the real Fixer
      // submit path (useGenerationPipeline's own genFix). Only LoomMobile receives it below --
      // desktop's LoomV2 has no Fixer tab (out of this increment's scope).
      genFixState,
      setGenFixState,
      batching,
      batchTally,
      // generateShot/priceShot newly destructured here (mobile-generate-screen pass,
      // 2026-08-03) -- both already existed on the hook's return value, generateShot simply
      // had no consumer above batchGenerate's own internal call until Loom Mobile's Generate
      // screen needed the exact same real per-shot submit + price-preview functions LoomV2's
      // batch path already uses. Nothing about either function changes; only who else gets a
      // reference to them.
      generateShot,
      priceShot,
      pollShot,
      useExistingVideo,
      genImage,
      routeImg,
      genEdit,
      genRef,
      genFix,
      routeGen,
      batchGenerate,
      costEstimate,
      refreshEstimate
    } = useGenerationPipeline({ project, thumbs, setCard, setCardStatus, setAssets, openPick, activeId, mobileUI });
    const onVideoSubmit = useCallback2((cardId, detail) => {
      setGenState((s) => ({ ...s, [cardId]: { phase: "running", msg: "Rendering\u2026 (task " + String(detail.task_id).slice(-6) + ")" } }));
      setCardStatus(cardId, { status: "wip", pendingTaskId: detail.task_id, genStartedAt: Date.now() });
      if (window.Jobs && window.Jobs.register) window.Jobs.register(detail.task_id, "Rendered");
    }, [setGenState, setCardStatus]);
    const onVideoResult = useCallback2((cardId, detail) => {
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
    const onVideoError = useCallback2((cardId, detail) => {
      setGenState((s) => ({ ...s, [cardId]: { phase: "error", msg: detail.error } }));
      setCardStatus(cardId, { status: "error", pendingTaskId: null, genStartedAt: null });
    }, [setGenState, setCardStatus]);
    const onVideoSlow = useCallback2((cardId, detail) => {
      setGenState((s) => ({ ...s, [cardId]: {
        phase: detail.tier,
        msg: detail.tier === "stale" ? "Still going after " + elapsedLabel(detail.elapsed) + " \u2014 unusual. Check pixai.art, or keep waiting (task " + String(detail.task_id).slice(-6) + ")" : "Taking longer than expected (" + elapsedLabel(detail.elapsed) + ", task " + String(detail.task_id).slice(-6) + ")"
      } }));
    }, [setGenState]);
    const onVideoPaused = useCallback2((cardId, detail) => {
      setGenState((s) => ({ ...s, [cardId]: {
        phase: "paused",
        msg: "Paused auto-checking with no result \u2014 click to check again, or check pixai.art (task " + String(detail.task_id).slice(-6) + ")"
      } }));
    }, [setGenState]);
    useEffect2(() => {
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
      setGenFixState(clearDraft);
    }, [activeId]);
    const {
      seq: seq2,
      exp,
      playSequence,
      exportCut,
      cancelExport,
      closeExport,
      closeSequence,
      exportAll,
      exportJSON,
      exportBundle,
      bundling,
      bundleMissing,
      closeBundleMissing
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
    return /* @__PURE__ */ React.createElement("div", { className: "sb-root" }, /* @__PURE__ */ React.createElement("style", null, STYLES), /* @__PURE__ */ React.createElement(NotifyRoot, null), mobileUI ? /* @__PURE__ */ React.createElement(V2Boundary, null, /* @__PURE__ */ React.createElement(
      LoomMobile,
      {
        project,
        entries,
        thumbs,
        genState,
        selShot,
        setSelShot,
        addCard,
        addAct,
        setDraft,
        setCard,
        setAssets,
        addRef,
        setRef,
        delRef,
        storeThumb,
        openPick,
        copyShot,
        splitShot,
        moveCard,
        dupCard,
        delCard,
        mobileUI,
        setMobileUI,
        draftCard,
        setDraftCard,
        draftTarget,
        setDraftTarget,
        draftAttachedInfo,
        setDraftAttachedInfo,
        generateShot,
        priceShot,
        useExistingVideo,
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
        genFixState,
        setGenFixState,
        genFix
      }
    )) : /* @__PURE__ */ React.createElement(V2Boundary, null, /* @__PURE__ */ React.createElement(
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
        genFixState,
        setGenFixState,
        genFix,
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
        refreshEstimate,
        mobileUI,
        setMobileUI,
        draftCard,
        setDraftCard,
        draftTarget,
        setDraftTarget,
        draftAttachedInfo,
        setDraftAttachedInfo
      }
    )), seq2 && /* @__PURE__ */ React.createElement(SequencePlayer, { clips: seq2, onClose: closeSequence }), exp && /* @__PURE__ */ React.createElement("div", { className: "sb-seq", onClick: (e) => {
      if (e.target === e.currentTarget && exp.status !== "running") closeExport();
    } }, /* @__PURE__ */ React.createElement("div", { className: "sb-export-box" }, /* @__PURE__ */ React.createElement("div", { className: "sb-pick-head" }, /* @__PURE__ */ React.createElement("span", { className: "sb-pick-t" }, "Export the cut"), exp.status !== "running" && /* @__PURE__ */ React.createElement("button", { className: "sb-pick-x", onClick: closeExport }, "\xD7")), exp.status === "running" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "sb-exp-bar" }, /* @__PURE__ */ React.createElement("i", { style: { width: (exp.progress || 0) + "%" } })), /* @__PURE__ */ React.createElement("div", { className: "sb-exp-txt" }, "Rendering\u2026 ", exp.progress || 0, "% \xB7 ", Math.round(exp.elapsed || 0), "s of cut"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", style: { alignSelf: "center" }, onClick: cancelExport }, "\u25A0 Stop")), exp.status === "done" && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "sb-exp-txt", style: { color: "var(--green)" } }, "\u2713 Cut rendered."), exp.warning && /* @__PURE__ */ React.createElement("div", { className: "sb-exp-txt", style: { color: "var(--amber)" } }, "\u26A0 ", exp.warning), /* @__PURE__ */ React.createElement("a", { className: "sb-btn amber", href: "/api/loom/export-file", style: { alignSelf: "center", textDecoration: "none" } }, "\u21E9 Download mp4"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", style: { alignSelf: "center" }, onClick: closeExport }, "Close")), (exp.status === "failed" || exp.status === "cancelled") && /* @__PURE__ */ React.createElement(React.Fragment, null, /* @__PURE__ */ React.createElement("div", { className: "sb-exp-txt", style: { color: exp.status === "failed" ? "var(--coral)" : "var(--ink2)" } }, exp.status === "failed" ? "\u26A0 " + (exp.error || "export failed") : "\u25A0 Export stopped."), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", style: { alignSelf: "center" }, onClick: closeExport }, "Close")))), bundleMissing && /* @__PURE__ */ React.createElement("div", { className: "sb-seq", onClick: (e) => {
      if (e.target === e.currentTarget) closeBundleMissing();
    } }, /* @__PURE__ */ React.createElement("div", { className: "sb-export-box" }, /* @__PURE__ */ React.createElement("div", { className: "sb-pick-head" }, /* @__PURE__ */ React.createElement("span", { className: "sb-pick-t" }, "Bundle exported, ", bundleMissing.total, " file(s) left out"), /* @__PURE__ */ React.createElement("button", { className: "sb-pick-x", style: { marginLeft: "auto" }, onClick: closeBundleMissing }, "\xD7")), /* @__PURE__ */ React.createElement("div", { className: "sb-exp-txt", style: { color: "var(--coral)" } }, "\u26A0 No file on disk for these references \u2014 everything else exported normally."), bundleMissing.rows.length > 0 && /* @__PURE__ */ React.createElement("div", { className: "sb-miss-list" }, bundleMissing.rows.map((row) => /* @__PURE__ */ React.createElement("div", { className: "sb-miss-row", key: row.mid }, row.where.length ? row.where.map((w, i) => /* @__PURE__ */ React.createElement("b", { key: i }, w)) : /* @__PURE__ */ React.createElement("i", null, "not referenced by any shot or cast entry in this project"), /* @__PURE__ */ React.createElement("span", { className: "sb-miss-id" }, row.mid)))), bundleMissing.hidden > 0 && /* @__PURE__ */ React.createElement("div", { className: "sb-exp-txt", style: { color: "var(--ink2)", fontSize: "12px" } }, bundleMissing.rows.length ? `+${bundleMissing.hidden} more, not listed here.` : `The server sent no id list.`, "The complete list, with the shot each id came from, is inside the zip:", /* @__PURE__ */ React.createElement("b", null, "project.json"), " \u2192 ", /* @__PURE__ */ React.createElement("b", null, "missing_media"), "."), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", style: { alignSelf: "center" }, onClick: closeBundleMissing }, "Close"))), pickCb && /* @__PURE__ */ React.createElement(
      GalleryPicker,
      {
        defaultType: pickKind,
        showType: pickAllowType,
        sheet: mobileUI,
        onPick: onGalleryPick,
        onClose: () => setPickCb(null)
      }
    ), importOpen && /* @__PURE__ */ React.createElement(ImportCollection, { onClose: () => setImportOpen(false), onImport: importCollection }));
  }
  function ShotPreview({ mid, trimIn, trimOut, onTrim, onSplit, crop, onCrop }) {
    const vidRef = useRef2(null), trackRef = useRef2(null);
    const [dur, setDur] = useState2(0);
    const [range, setRange] = useState2({ in: trimIn || 0, out: trimOut });
    const [playing, setPlaying] = useState2(false);
    const [soundOn, setSoundOn] = useState2(false);
    const [cropping, setCropping] = useState2(false);
    const rangeRef = useRef2(range);
    rangeRef.current = range;
    const durRef = useRef2(0);
    durRef.current = dur;
    const dragRef = useRef2(null);
    useEffect2(() => {
      setRange({ in: trimIn || 0, out: trimOut });
    }, [trimIn, trimOut]);
    useEffect2(() => {
      const v = vidRef.current;
      if (v) v.muted = !(soundOn && playing);
    }, [soundOn, playing]);
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
    const cropRef = useRef2(null);
    const [cropDraft, setCropDraft] = useState2(null);
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
    ), /* @__PURE__ */ React.createElement("div", { className: "sb-shotprev-ctrls" }, /* @__PURE__ */ React.createElement("button", { onClick: () => seek(-0.25), title: "Rewind (step back)" }, "\u23EA"), /* @__PURE__ */ React.createElement("button", { onClick: () => seek(0.25), title: "Fast-forward (step ahead)" }, "\u23E9"), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: soundOn ? "on" : "",
        onClick: () => setSoundOn((v) => !v),
        "aria-pressed": soundOn,
        title: soundOn ? "Sound on while playing (scrubbing stays silent)" : "Play this shot with sound"
      },
      soundOn ? "\u{1F50A}" : "\u{1F507}"
    ), onSplit && /* @__PURE__ */ React.createElement("button", { onClick: doSplit, title: "Split this shot in two at the playhead" }, "\u2702 Split"), onCrop && /* @__PURE__ */ React.createElement(
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
    const vRef = useRef2(null);
    const [i, setI] = useState2(0);
    const [muted, setMuted] = useState2(true);
    const clip = clips[i];
    useEffect2(() => {
      const v = vRef.current;
      if (v) v.muted = muted;
    }, [muted, i]);
    useEffect2(() => {
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
    useEffect2(() => {
      const esc2 = (e) => {
        if (e.key === "Escape") onClose();
      };
      window.addEventListener("keydown", esc2);
      return () => window.removeEventListener("keydown", esc2);
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
    ), /* @__PURE__ */ React.createElement("div", { className: "sb-seq-bar" }, /* @__PURE__ */ React.createElement("span", null, "Shot ", i + 1, "/", clips.length, clip.code ? " \xB7 " + clip.code : "", clip.title ? " \u2014 " + clip.title : ""), /* @__PURE__ */ React.createElement(
      "button",
      {
        className: "sb-btn ghost sm",
        onClick: () => setMuted(!muted),
        title: muted ? "Unmute \u2014 the rendered mp4 has audio" : "Mute",
        "aria-pressed": !muted
      },
      muted ? "\u{1F507} muted" : "\u{1F50A} sound"
    ), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", onClick: () => setI(Math.max(0, i - 1)), disabled: i === 0 }, "\u25C0 prev"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn ghost sm", onClick: () => {
      if (i < clips.length - 1) setI(i + 1);
      else onClose();
    } }, "next \u25B6"), /* @__PURE__ */ React.createElement("button", { className: "sb-btn sm", onClick: onClose }, "\u2715 close"))));
  }
  function ImportCollection({ onImport, onClose }) {
    const [colls, setColls] = useState2([]);
    const [sel, setSel] = useState2("");
    const [total, setTotal] = useState2(0);
    const CAP = 48;
    useEffect2(() => {
      fetch("/api/collections").then((r) => r.json()).then((d) => setColls(d.collections || [])).catch(() => {
      });
    }, []);
    useEffect2(() => {
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
