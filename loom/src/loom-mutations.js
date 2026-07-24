/* =========================================================================
   loom-mutations.js — pure, framework-agnostic project-tree mutators and
   response-shape helpers extracted out of master-storyboard.jsx's App()
   component (Phase 2, composed-hooks extraction pass, 2026-07-16).

   Every function here is a pure reducer: (project, ...args) -> new project
   (or another plain value), OR a pure classifier of a plain-object response.
   NO React import, no DOM/window/fetch access -- same discipline as
   ./loom-core.js, so this is safe to `node --test` directly
   (see loom/test/loom-mutations.test.js).

   Anything that needs an id generator (uid()) takes the id as an argument
   instead of generating it -- id generation is randomness, a side effect,
   and stays in the React hooks (useShotMutations / useProjectStore) that
   call these. Anything that needs user confirmation (window.confirm) also
   stays in the hooks; the pure functions here just do the tree edit once
   the caller has already decided to do it.

   Two consumers, both must keep working (mirrors loom-core.js's own
   contract, see that file's header comment):
     1. master-storyboard.jsx imports this as a real ES module; esbuild
        bundles it in (loom/scripts/build.mjs -> loom/dist/).
     2. The Flask /loom route (pixai_gallery.py, `loom()`) inlines this
        file's source ahead of the JSX for the in-browser Babel-standalone
        fallback path, stripping `export` the same way it already does for
        loom-core.js. Do not add anything here a classic (non-module)
        <script> couldn't also run.
   ========================================================================= */

// ---------- card / act / ref tree mutators ----------

// setCard(aId, cId, fn) core: apply fn to exactly one card in one act.
export const patchCard = (project, actId, cardId, fn) => ({
  ...project,
  acts: project.acts.map((a) => a.id !== actId ? a : {
    ...a, cards: a.cards.map((c) => c.id !== cardId ? c : fn(c)),
  }),
});

// setCardStatus(cardId, patch) core: patch a card by id, searching ALL acts
// (the caller doesn't know -- or care -- which act the card lives in).
export const patchCardById = (project, cardId, patch) => ({
  ...project,
  acts: project.acts.map((a) => ({
    ...a, cards: a.cards.map((c) => c.id !== cardId ? c : { ...c, ...patch }),
  })),
});

// Pure reducers for the prompt-override mechanism -- kept here (not inlined at each call
// site) so the shape can't drift between the several places that set/clear it (the drawer's
// commit listener, the toolbar's flush-before-batch, the native Prompt textarea, the
// re-sync button).
export const setPromptOverride = (c, text) => ({ ...c, promptOverride: true, promptOverrideText: text });
export const clearPromptOverride = (c) => ({ ...c, promptOverride: false, promptOverrideText: "" });

// The patch an already-rendered gallery video applies on top of a fresh blank card
// (newCard(), master-storyboard.jsx -- the one place a shot's other default fields are
// decided; deliberately NOT duplicated here) to become a REAL, placeable Finished-Shots
// entry instead of an empty one: pre-done, its resultMid already the picked media, no
// generation needed. `imported:true` is provenance -- no PixAI task backs this resultMid,
// unlike every other done card -- so re-roll/cost/debugging logic can tell the two apart
// (see generateShot's !hasInput branch in master-storyboard.jsx: an imported card has no
// cast/frames/refs, so hasInput is false by construction and a re-roll attempt safely
// no-ops with an explanatory message instead of silently discarding the footage or
// spending credits). `duration` comes from the SAME picker field useExistingVideo already
// trusts (catalog `video_duration`, or the /api/loom/video-duration probe fallback) --
// only written as actualDur when it resolves to a real positive number, so a blank/zero
// duration leaves newCard's own default (8s) standing rather than writing a lying zero.
export const importedFootagePatch = (mediaId, duration) => {
  const dur = Number(duration);
  return {
    status: "done", resultMid: mediaId, trimIn: 0, trimOut: null, imported: true,
    ...(dur > 0 ? { actualDur: dur } : {}),
  };
};

export const patchAct = (project, actId, patch) => ({
  ...project,
  acts: project.acts.map((a) => a.id !== actId ? a : { ...a, ...patch }),
});

export const patchAssets = (project, fn) => ({ ...project, assets: fn(project.assets || []) });

export const appendCardToAct = (project, actId, card) => ({
  ...project,
  acts: project.acts.map((a) => a.id !== actId ? a : { ...a, cards: [...a.cards, card] }),
});

// Land `card` in the project's FIRST act, creating one (named via nextActName, same
// as addAct's own convention) if the project doesn't have one yet -- so importing a
// gallery video as footage always has somewhere honest to go without inventing new
// "which act" UI. The owner repositions it afterward through that card's own existing
// "move to..." dropdown (moveCardToAct), exactly like any other shot. `newActId` is
// caller-supplied (id generation is a side effect that stays out of this pure layer,
// same contract as buildDuplicateCard's newCardId/newRefIds).
export const landInFirstAct = (project, card, newActId) => {
  const first = project.acts[0];
  const withAct = first ? project
    : appendAct(project, { id: newActId, name: nextActName(project), collapsed: false, cards: [] });
  return appendCardToAct(withAct, first ? first.id : newActId, card);
};

// Build the shape of a duplicated card (deep clone, fresh ids, reset render
// state) -- everything dupCard() did except id generation, which the caller
// supplies via `newCardId` / `newRefIds` (one per card.refs, same order).
export const buildDuplicateCard = (card, newCardId, newRefIds) => ({
  ...JSON.parse(JSON.stringify(card)),
  id: newCardId,
  refs: card.refs.map((r, i) => ({ ...r, id: (newRefIds && newRefIds[i]) || r.id })),
  // A duplicate is a fresh, unrendered shot -- it must not inherit the
  // original's generation result, or it silently shows "done" and Export
  // plays the SAME clip twice.
  resultMid: "", status: "todo", actualDur: null, trimIn: 0, trimOut: null,
});

// Insert `newCard` immediately after `origCardId` within one act.
export const insertCardAfter = (project, actId, origCardId, newCard) => ({
  ...project,
  acts: project.acts.map((a) => a.id !== actId ? a
    : { ...a, cards: a.cards.flatMap((x) => x.id === origCardId ? [x, newCard] : [x]) }),
});

export const removeCard = (project, actId, cardId) => ({
  ...project,
  acts: project.acts.map((a) => a.id !== actId ? a : { ...a, cards: a.cards.filter((c) => c.id !== cardId) }),
});

// Split one shot into two at playhead time `t`. Unlike buildDuplicateCard (which makes a
// FRESH, unrendered shot), both halves KEEP the same rendered clip (resultMid) and just
// divide the kept trim range at `t`: the left becomes [trimIn..t], the right [t..trimOut].
// Export then plays the two ranges of one clip back-to-back -- an actual cut. No-ops (returns
// the project unchanged) if `t` isn't strictly inside the kept range, so neither half is empty.
export const splitCardAt = (project, actId, cardId, t, newCardId) => {
  const act = project.acts.find((a) => a.id === actId);
  const card = act && act.cards.find((c) => c.id === cardId);
  if (!card) return project;
  const ti = card.trimIn || 0, to = card.trimOut;     // to == null means "to the clip's real end"
  if (!(t > ti + 0.1 && (to == null || t < to - 0.1))) return project;
  const right = { ...JSON.parse(JSON.stringify(card)), id: newCardId,
    title: card.title ? card.title + " (cont.)" : "cont.", trimIn: t, trimOut: to };
  const withLeft = patchCard(project, actId, cardId, (c) => ({ ...c, trimOut: t }));
  return insertCardAfter(withLeft, actId, cardId, right);
};

export const moveCardInAct = (project, actId, idx, dir) => ({
  ...project,
  acts: project.acts.map((a) => {
    if (a.id !== actId) return a;
    const j = idx + dir; if (j < 0 || j >= a.cards.length) return a;
    const cs = [...a.cards]; [cs[idx], cs[j]] = [cs[j], cs[idx]]; return { ...a, cards: cs };
  }),
});

export const moveCardToAct = (project, fromActId, card, toActId) => {
  if (fromActId === toActId) return project;
  return {
    ...project,
    acts: project.acts.map((a) => a.id === fromActId ? { ...a, cards: a.cards.filter((c) => c.id !== card.id) }
      : a.id === toActId ? { ...a, cards: [...a.cards, card] } : a),
  };
};

export const nextActName = (project) => `Act ${project.acts.length + 1}`;

export const appendAct = (project, act) => ({ ...project, acts: [...project.acts, act] });

export const removeAct = (project, actId) => ({ ...project, acts: project.acts.filter((a) => a.id !== actId) });

export const moveActInProject = (project, idx, dir) => {
  const j = idx + dir; if (j < 0 || j >= project.acts.length) return project;
  const as = [...project.acts]; [as[idx], as[j]] = [as[j], as[idx]]; return { ...project, acts: as };
};

// addRef(aId, card, kind) core: the new-ref object, given a caller-supplied id.
// Mode ("I2V"/"R2V"/"V2V"/"FLF") and Continuity's "First->Last" chip (connect:"flf") both mean
// FLF, but only `mode` actually controls whether the close frame reaches the real generation --
// shotPayload (loom-core.js) and the server's build_shot_video_params both gate strictly on
// mode==="FLF" alone, with no fallback to connect. Left uncoupled, a shot could show Continuity
// "First->Last" (whose own hint promises "land on an exact end frame") with Mode left on I2V:
// both frames stay filled in on screen, generation submits and completes normally, and the close
// frame is silently dropped with no error anywhere -- confirmed in production, a real spent
// generation that silently used only the open frame. These two setters keep the fields coupled
// in both directions so that state can no longer be reached through the UI.
export const setShotMode = (c, mode) => ({
  ...c, mode, connect: (mode !== "FLF" && c.connect === "flf") ? "new" : c.connect,
});
export const setShotConnect = (c, connect) => ({
  ...c, connect, mode: connect === "flf" ? "FLF" : c.mode,
});

export const buildNewRef = (kind, id) => ({ id, kind, tag: "", role: "", source: "", thumbId: "" });

export const patchRef = (project, actId, cardId, refId, patch) =>
  patchCard(project, actId, cardId, (c) => ({ ...c, refs: c.refs.map((r) => r.id !== refId ? r : { ...r, ...patch }) }));

export const removeRef = (project, actId, cardId, refId) =>
  patchCard(project, actId, cardId, (c) => ({ ...c, refs: c.refs.filter((r) => r.id !== refId) }));

export const countShots = (project) => (project.acts || []).reduce((n, a) => n + ((a.cards || []).length), 0);

// ---------- misc pure parsing ----------

// Gallery -> cast handoff: /loom?cast=id1,id2 query-string parsing, split out
// of the effect so it's testable without a real `location` object.
export const parseCastIdsFromSearch = (search) =>
  (search || "").replace(/^\?/, "")
    .split("&").map((kv) => kv.split("=")).filter(([k]) => k === "cast")
    .flatMap(([, v]) => (v || "").split(","))
    .map((s) => decodeURIComponent(s).trim())
    .filter((s) => /^\d+$/.test(s));

// ---------- generation error / poll-response classification ----------

// Turn a raw gen error (esp. PixAI's GraphQL "insufficient balance") into a human message.
export function friendlyGenErr(raw) {
  const s = String(raw || "");
  if (/insufficient|INSUFFICIENT_BALANCE|40300010/i.test(s))
    return "Out of balance for this model — no free card matched and credits are 0. Claim your daily rewards, or pick a card-covered model.";
  if (/moderat|content.?policy|flagged|prohibit|sensitive|not.?allowed|violat/i.test(s))
    return "PixAI's content filter blocked this generation — that's decided on PixAI's side, not in the Loom.";
  return s || "generation failed";
}

// Classify a /api/task-status response the same way pollShot/pollImg/runGen's
// poll loop all did (previously three independently-hand-copied branches).
// {phase:"done", mid, [duration]} | {phase:"failed", msg} | {phase:"pending"}
export function classifyTaskStatus(d) {
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

// ---------- export / playback shape builders ----------

// exportAll()'s whole-board shot-list text, minus the actual file download.
export function buildShotListText(project, fmt, actLetter, shotText) {
  let out = `${project.name}\nRuntime target ${fmt(project.target)}\n`;
  if ((project.assets || []).length) {
    out += `\nCast & assets:\n`;
    project.assets.forEach((as) => { out += `  ${as.tag}  ${as.name} (${as.kind})${as.lock ? " · lock appearance" : ""}\n`; });
  }
  project.acts.forEach((a, ai) => {
    out += `\n${"=".repeat(48)}\n${a.name}\n${"=".repeat(48)}\n\n`;
    a.cards.forEach((c, ci) => {
      out += shotText({ c, code: `${actLetter(ai)}·${String(ci + 1).padStart(2, "0")}`, ai, ci }, project) + "\n\n";
    });
  });
  return out;
}

// playSequence()'s clip list: every finished shot, in board order, with its trim.
export const buildPlaySequence = (entries) =>
  entries.filter((e) => e.c.resultMid).map((e) => ({
    mid: e.c.resultMid, in: e.c.trimIn || 0, out: e.c.trimOut, title: e.c.title, code: e.code,
  }));

// exportCut()'s ffmpeg clip list + total runtime, from finished shots' actual
// (or planned) duration and trim.
export function buildExportClips(entries) {
  const clips = entries.filter((e) => e.c.resultMid).map((e) => {
    const dur = e.c.actualDur || e.c.duration || 8, cin = e.c.trimIn || 0;
    const cout = (e.c.trimOut != null ? e.c.trimOut : dur);
    const clip = { mid: e.c.resultMid, in: cin, out: e.c.trimOut, span: Math.max(0.1, cout - cin) };
    // A spatial crop (fractions of the frame) rides along so export applies it via ffmpeg's
    // crop filter. Only carried when it meaningfully crops -- a full-frame or tiny rect is dropped.
    const cr = e.c.crop;
    if (cr && cr.w > 0.05 && cr.h > 0.05 && (cr.w < 0.99 || cr.h < 0.99 || cr.x > 0.01 || cr.y > 0.01))
      clip.crop = { x: cr.x, y: cr.y, w: cr.w, h: cr.h };
    return clip;
  });
  const total = clips.reduce((s, c) => s + c.span, 0);
  return { clips, total };
}

// ---------- LoRA (D-11) ----------
// Ported from pixai_gallery.py's loraIncompat() -- same rule, same "fail open on
// unknown" contract, kept as a pure/tested function per this file's own header
// convention instead of a third hand-copy embedded in JSX. A LoRA runs on a base
// ONLY if its loraBaseModelType == the base's modelType (exact enum equality,
// case-insensitive); an unknown/empty type on either side never blocks a submit --
// this is advisory (disables Go / shows a warning), not a hard gate, per D-2: PixAI's
// own site already rejects a real mismatch and explains why.
export function loraIncompat(baseModelType, loraBaseType) {
  const b = (baseModelType || "").toUpperCase();
  const l = (loraBaseType || "").toUpperCase();
  if (!b || !l) return false;
  return b !== l;
}

// The Gallery drawer's payload() filter, ported: only LoRAs that actually resolved a
// version_id are ever sent -- one still pending/failed must not silently vanish from
// what the CALLER believes it sent, so this is filter-not-drop at the call site, paired
// with the UI staying gated (Generate disabled) while anyLoraUnresolved() is true.
export function resolveLoraPayload(loras) {
  return (loras || [])
    .filter((l) => l.version_id)
    .map((l) => ({ version_id: l.version_id, weight: l.weight }));
}

export function anyLoraUnresolved(loras) {
  return (loras || []).some((l) => !l.version_id);
}

// ---------- Image-tab generation dimensions + submit/price body (L536) ----------
// Ported from pixai_gallery.py's Gen.d8(): round to the nearest multiple of 8 and clamp to
// PixAI's real [64,4096] bounds -- the server's own _dim only floors to /8 and never clamps,
// so a client that skips this could ask for a size the server accepts but PixAI's own site
// never would.
export function snap8(n) {
  return Math.max(64, Math.min(4096, Math.round((Number(n) || 0) / 8) * 8));
}

// Ported from pixai_gallery.py's Gen.dims(), minus the DOM reads: custom W×H (both > 0)
// wins; otherwise an aspect-ratio pair scaled so the long edge equals `size`. Same shape,
// now unit-tested here instead of only ever exercised by hand in a browser.
export function resolveGenDims({ aspectW, aspectH, size, customW, customH } = {}) {
  const cw = Number(customW) || 0, ch = Number(customH) || 0;
  if (cw > 0 && ch > 0) return { w: snap8(cw), h: snap8(ch), custom: true };
  const rw = Number(aspectW) || 1, rh = Number(aspectH) || 1;
  const sz = Number(size) || 1024;
  const w = rw >= rh ? sz : (sz * rw / rh);
  const h = rw >= rh ? (sz * rh / rw) : sz;
  return { w: snap8(w), h: snap8(h), custom: false };
}

// The Image tab's full /api/generate (and /api/price preview) body -- ONE shape shared by
// the debounced cost badge and the real submit, so the badge can never show a price for
// different settings than what actually submits (see master-storyboard.jsx's imgCostRef
// effect and genImage()). `imgAdv` is the Advanced-section state L536 added for full
// PixAI field parity with pixai_gallery.py's own Generate tab -- this is the JS mirror of
// that tab's payload(), same field names/defaults, minus the DOM reads.
export function buildImgGenBody(imgModel, imgLoras, imgAdv, prompt) {
  const a = imgAdv || {};
  const dims = resolveGenDims({ aspectW: a.aspectW, aspectH: a.aspectH, size: a.size,
                                customW: a.customW, customH: a.customH });
  return {
    model_id: (imgModel && imgModel.model_id) || "",
    prompt: prompt || "",
    loras: resolveLoraPayload(imgLoras),
    negative: a.negative || "",
    width: dims.w, height: dims.h,
    mode: a.mode || "auto",
    steps: Number(a.steps) || 25,
    cfg: Number(a.cfg) || 7,
    count: Number(a.count) || 1,
    seed: String(a.seed || "").trim(),
    high_priority: !!a.highPriority,
    prompt_helper: !!a.promptHelper,
  };
}
