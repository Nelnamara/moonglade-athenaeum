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

export const patchAct = (project, actId, patch) => ({
  ...project,
  acts: project.acts.map((a) => a.id !== actId ? a : { ...a, ...patch }),
});

export const patchAssets = (project, fn) => ({ ...project, assets: fn(project.assets || []) });

export const appendCardToAct = (project, actId, card) => ({
  ...project,
  acts: project.acts.map((a) => a.id !== actId ? a : { ...a, cards: [...a.cards, card] }),
});

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
    return { mid: e.c.resultMid, in: cin, out: e.c.trimOut, span: Math.max(0.1, cout - cin) };
  });
  const total = clips.reduce((s, c) => s + c.span, 0);
  return { clips, total };
}
