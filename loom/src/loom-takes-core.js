/* =========================================================================
   loom-takes-core.js — TAKES (P1) and RE-ANCHOR (P2), as pure reducers and views.

   Session P, lane w5-p. The design is moonglade-internal/design/notes/loom/BUILD-w5-p.md
   (sections 1-3, and its review findings F1-F17, N1); the page is Loom Handoff.dc.html.

   Same discipline as loom-core.js / loom-mutations.js: NO React, no DOM, no window, no
   fetch, no timers. Everything here is (card | project, facts) -> new value. Ids and
   timestamps are ARGUMENTS, never generated here. The never-auto-render test
   (loom/test/loom-no-auto-render.test.js) pins that this file names no render path at all:
   nothing in it can price, submit or upload, so no reducer here can start a render.

   ---- The data (all additive; an old card has none of these fields) ----------------------
     card.takes        [Take]      absent on every card saved before this build
     card.selectedTake n           the ★ take's number (a cache; the MIRROR decides, below)
     card.takeSeq      n           the highest take number ever issued (monotonic)
     card.deletedTakes [mid]       tombstones, so a two-tab merge never brings a delete back
     card.anchor       {shot, take, at, frame, via} | null
     card.anchorKept   {from, to, at} | null
     card.pendingSubmitId / pendingSettings / pendingAnchor / pendingBoard / pendingQuote
                                   the in-flight marker of one render, set BEFORE its POST
     card.supersededTasks [taskId] a paused render replaced by a newer one
     card.lastAttempt  {state, msg, at} | null   a failed / refused / unclear render

   ---- THE MIRROR RULE (review F9, F10) -----------------------------------------------------
   The card-level resultMid, actualDur, trimIn, trimOut, crop and imported ARE the selected
   take. They are authoritative: every existing reader (Play, the local cut, the bundle, the
   splice handoff, thumbs, review, the phone trims) keeps reading them unchanged, and every
   existing trim writer keeps writing them. A take's OWN stored trims matter only while it is
   not selected. selectedTakeView() overlays the card's fields onto takes[sel], so nothing
   ever reads a stale stored copy of the selected take.

   Which take is selected is read FROM the mirror: the take whose mid is card.resultMid.
   So a board an older build touched (it re-rolls by overwriting resultMid and never sees
   takes[]) still reads right here: the new resultMid, which no stored take holds, is shown
   as a derived take on top (source "legacy"), selected, and materialised by the next
   owner-triggered reducer. Nothing is dropped and the ledger still counts it.
   ========================================================================================= */

const own = (o, k) => Object.prototype.hasOwnProperty.call(o || {}, k);
const str = (v) => (v == null ? "" : String(v));
const num = (v) => { const n = Number(v); return Number.isFinite(n) ? n : null; };
// A length or a time that was never recorded is UNKNOWN (null), never 0: Number(null) and
// Number("") are both 0. A take whose clip length was not recorded (landTake stores dur null
// when the task reported none) read as a 0 s clip, so the continuity ribbon compared the
// outgoing shot's FIRST frame with the next shot's open -- a false "strong colour jump" on a
// true handoff (owner walk 2026-09-30).
const known = (v) => (v == null || v === "" ? null : num(v));

/* ---------- views: never write ---------- */

const storedTakes = (card) => (card && Array.isArray(card.takes) ? card.takes : null);
const maxN = (takes) => (takes || []).reduce((m, t) => Math.max(m, Number((t || {}).n) || 0), 0);

// The take derived from a card's mirror fields: take 1 of a legacy board, or the orphan a
// stale build left on top of a materialised one (F10).
const mirrorTake = (card, n) => {
  const t = {
    id: "t" + n, n, mid: str(card.resultMid), taskId: "", at: "",
    dur: known(card.actualDur), trimIn: Number(card.trimIn) || 0,
    trimOut: card.trimOut == null ? null : Number(card.trimOut),
    settings: null, anchor: null, imported: !!card.imported, source: "legacy",
  };
  if (card.crop) t.crop = card.crop;
  return t;
};

/** Every take of a card, in number order. A pure VIEW: an old board's single render is
 *  take 1 here, computed and never stored. */
export const takesOf = (card) => {
  if (!card) return [];
  const stored = storedTakes(card);
  const mid = str(card.resultMid);
  if (!stored) return mid ? [mirrorTake(card, 1)] : [];
  if (mid && !stored.some((t) => t && str(t.mid) === mid)) {
    const n = Math.max(maxN(stored), Number(card.takeSeq) || 0) + 1;
    return stored.concat([mirrorTake(card, n)]);
  }
  return stored;
};

/** The ★ take's number, or null when the shot has no render. Read from the mirror. */
export const selectedTakeOf = (card) => {
  const mid = str(card && card.resultMid);
  if (!mid) return null;
  const ts = takesOf(card);
  const pinned = ts.find((t) => t.n === card.selectedTake && str(t.mid) === mid);
  const hit = pinned || ts.find((t) => str(t.mid) === mid);
  return hit ? hit.n : null;
};

/** The highest number ever issued on the card. Never lowered by a delete. */
export const takeSeqOf = (card) => {
  if (!card) return 0;
  return Math.max(Number(card.takeSeq) || 0, maxN(takesOf(card)));
};

/** The selected take as every reader should see it: the stored take with the card's
 *  authoritative mirror fields laid over it (F9). null when unrendered. */
export const selectedTakeView = (card) => {
  const n = selectedTakeOf(card);
  if (n == null) return null;
  const t = takesOf(card).find((x) => x.n === n) || mirrorTake(card, n);
  const v = { ...t, mid: str(card.resultMid), dur: known(card.actualDur) != null ? known(card.actualDur) : t.dur,
    trimIn: Number(card.trimIn) || 0, trimOut: card.trimOut == null ? null : Number(card.trimOut),
    imported: !!card.imported };
  if (card.crop) v.crop = card.crop; else delete v.crop;
  return v;
};

/** A take by number, through selectedTakeView when it is the selected one. */
export const takeView = (card, n) => {
  if (n === selectedTakeOf(card)) return selectedTakeView(card);
  return takesOf(card).find((t) => t.n === n) || null;
};

/** In flight = a render was clicked and has not resolved (the lock). A "wip" card with no
 *  marker at all (a pre-P crash between the status write and the task id) is not: nothing
 *  is known to be out, and the owner's next deliberate Render is the way out of it. */
export const inFlight = (card) => !!(card && (card.pendingSubmitId || card.pendingTaskId));

/** The Go gate (BUILD §3.3 step 1, the busy gate, the phone's Generate): may a NEW render of
 *  this card start? No while a send's answer is outstanding or unclear; no while a task is
 *  being polled -- unless that poll has PAUSED at its ceiling (`paused`, the tab's own view),
 *  the one carve-out: beginRender then supersedes the paused task. */
export const goBlocked = (card, paused) => {
  if (!inFlight(card)) return false;
  if (card.pendingSubmitId && !card.pendingTaskId) return true;
  return !paused;
};

/** A send whose answer never came (or came back "may have started"): the card keeps its lock
 *  and shows the peach way-out (↻ Check / release) until submit-status or the owner settles it. */
export const sendUnclear = (card) => !!(card && card.pendingSubmitId && !card.pendingTaskId
  && card.lastAttempt && card.lastAttempt.state === "unclear");

/** The pictures of a shot payload the server's render route cannot send (open call 4, review
 *  F16): anything that is neither a catalog id (digits) nor a data: thumbnail -- an imported
 *  `local_` picture above all. Mirrors the server's own test, so the client refuses exactly
 *  what the server would, BEFORE a price is asked or a confirm shown. */
const unsendableIn = (list, dataOk) => (Array.isArray(list) ? list : [])
  .map((x) => str(x).trim())
  .filter((s) => s && !/^\d+$/.test(s) && !(dataOk && s.startsWith("data:")));
export const unsendableImages = (payload) => unsendableIn(payload && payload.images, true);

/** Spend review S6: the same rule for the shot's reference VIDEOS and AUDIO. The server sends
 *  only catalog ids (digits) for those -- a `local_` video was silently dropped, so the render
 *  was priced and charged without the reference the card showed. A data: value is no escape
 *  there (only pictures are uploaded on the way). Every render path refuses on this list. */
export const unsendableRefs = (payload) => {
  const p = payload || {};
  return unsendableIn(p.images, true).concat(unsendableIn(p.video_refs, false), unsendableIn(p.audio_refs, false));
};
/** What the card calls the first unsendable reference: "picture", "video", "audio" or "". */
export const unsendableKind = (payload) => {
  const p = payload || {};
  if (unsendableIn(p.images, true).length) return "picture";
  if (unsendableIn(p.video_refs, false).length) return "video";
  if (unsendableIn(p.audio_refs, false).length) return "audio";
  return "";
};

/** The card on a board waiting for this submit id (the drawer's mg-submit / mg-error), or null. */
export const cardForSubmit = (project, submitId) => {
  const sid = str(submitId);
  if (!sid) return null;
  for (const a of ((project || {}).acts || [])) {
    for (const c of ((a || {}).cards || [])) if (c && str(c.pendingSubmitId) === sid) return c;
  }
  return null;
};

/** The card on a board that owns this task: the one polling it, or one that superseded it
 *  (so a paused render's late clip still lands there, without ★). Never "the selected shot". */
export const cardForTask = (project, taskId) => {
  const tid = str(taskId);
  if (!tid) return null;
  let sup = null;
  for (const a of ((project || {}).acts || [])) {
    for (const c of ((a || {}).cards || [])) {
      if (!c) continue;
      if (str(c.pendingTaskId) === tid) return c;
      if (!sup && (c.supersededTasks || []).some((x) => str(x) === tid)) sup = c;
    }
  }
  return sup;
};

/** Generate all / the cost-to-finish estimate: which shots still need a render (F14).
 *  A shot with a ★ take is finished even when its last retake failed. */
export const needsRender = (card) => !!card && selectedTakeOf(card) == null && !inFlight(card)
  // Conservative for a batch: a "wip" card with no marker may have been sent before a crash.
  // A batch never guesses; the owner's own Render click on that card is the way out.
  && card.status !== "wip";

/** The media ids whose charge this card owns (BUILD §1.6): every take that is not imported,
 *  plus every superseded attempt, deduped. `imported` counts the borrowed clips named in
 *  the ledger's tooltip. A legacy imported card derives exactly today's answer: its one
 *  (imported) take is excluded and counted, and nothing else is billed. */
export const spendMidsOf = (card) => {
  const out = [];
  let imported = 0;
  if (!card) return { mids: out, imported };
  const seen = new Set();
  const add = (m) => { const k = str(m); if (k && !seen.has(k)) { seen.add(k); out.push(k); } };
  takesOf(card).forEach((t) => { if (t.imported) { if (t.mid) imported += 1; } else add(t.mid); });
  if (card.imported && !takesOf(card).some((t) => !t.imported)) return { mids: out, imported };
  (card.attempts || []).forEach((a) => { if (a && a.media_id) add(a.media_id); });
  return { mids: out, imported };
};

/* ---------- materialising: only inside a reducer the owner triggered ---------- */

/** The card with takes / selectedTake / takeSeq written out. The selected take's stored
 *  copy is refreshed from the mirror, so it is right the moment it stops being selected. */
export const withTakes = (card) => {
  const ts = takesOf(card);
  const sel = selectedTakeOf(card);
  const seq = takeSeqOf(card);
  const takes = ts.map((t) => {
    if (t.n !== sel) return t;
    const v = selectedTakeView(card);
    const out = { ...t, mid: v.mid, dur: v.dur, trimIn: v.trimIn, trimOut: v.trimOut, imported: v.imported };
    if (v.crop) out.crop = v.crop; else delete out.crop;
    return out;
  });
  const next = { ...card, takes, takeSeq: seq };
  if (sel == null) delete next.selectedTake; else next.selectedTake = sel;
  return next;
};

// Copy take `t` onto the card's mirror fields (it becomes the ★ one).
const mirrorOnto = (card, t) => {
  const next = { ...card, resultMid: str(t.mid), actualDur: t.dur == null ? null : t.dur,
    trimIn: Number(t.trimIn) || 0, trimOut: t.trimOut == null ? null : t.trimOut,
    imported: !!t.imported, selectedTake: t.n };
  if (t.crop) next.crop = t.crop; else delete next.crop;
  return next;
};

const PENDING = ["pendingTaskId", "pendingSubmitId", "pendingSettings", "pendingAnchor",
  "pendingBoard", "pendingQuote", "genStartedAt"];
const clearPending = (card) => {
  const next = { ...card };
  PENDING.forEach((k) => { if (own(next, k)) next[k] = null; });
  return next;
};
const withoutSuperseded = (card, taskId) => {
  const s = (card.supersededTasks || []).filter((x) => str(x) !== str(taskId));
  const next = { ...card };
  if (s.length) next.supersededTasks = s; else delete next.supersededTasks;
  return next;
};
const settledStatus = (card) => (selectedTakeOf(card) != null ? "done" : "error");
// A clip that becomes a take again is no longer deleted (spend review S2): its tombstone goes,
// or the next two-tab merge would read it as a delete and drop the take.
const untomb = (card, mid) => {
  const t = card.deletedTakes;
  if (!Array.isArray(t) || !t.some((x) => str(x) === str(mid))) return card;
  const rest = t.filter((x) => str(x) !== str(mid));
  const next = { ...card };
  if (rest.length) next.deletedTakes = rest; else delete next.deletedTakes;
  return next;
};

/* ---------- a render lands (F1, F4) ---------- */

/**
 * landTake(card, {mid, taskId, dur, at, board}) -> {card, outcome}
 *   outcome "landed"     appended and selected (the render this card is waiting for)
 *           "unselected" appended without ★ (a superseded, paused render finishing late)
 *           "repeat"     that clip is already a take; a late second report changes nothing
 *           "not-owned"  this card is not waiting for that task (a copy, another board, a
 *                        render the owner released); the clip stays in the library
 *           "invalid"    no media id
 * Only this and attachTake move ★ to a new clip. A late repeat of an OLD task never touches
 * the markers of a render that is in flight now (F1): markers clear only for the pending
 * task itself.
 */
export const landTake = (card, rep) => {
  const r = rep || {};
  const mid = str(r.mid), taskId = str(r.taskId);
  if (!card || !mid) return { card, outcome: "invalid" };
  const pend = str(card.pendingTaskId);
  const isPending = !!taskId && taskId === pend;
  // A landing names the board it was submitted from; a card that recorded a different one is
  // a copy of the shot, never its owner (F4).
  if (isPending && card.pendingBoard && r.board && str(card.pendingBoard) !== str(r.board)) {
    return { card, outcome: "not-owned" };
  }
  const superseded = !!taskId && (card.supersededTasks || []).some((x) => str(x) === taskId);
  const existing = takesOf(card).find((t) => str(t.mid) === mid);
  if (existing) {
    if (!isPending) {
      if (superseded) return { card: withoutSuperseded(card, taskId), outcome: "repeat" };
      return { card, outcome: "repeat" };
    }
    // The clip it is waiting for is already a take (another path landed it first): select
    // it and clear this render's own markers.
    let c = withTakes(card);
    const sel = selectedTakeOf(c);
    if (existing.n !== sel) c = selectTake(c, existing.n);
    c = clearPending(c);
    return { card: { ...c, status: "done", lastAttempt: null }, outcome: "repeat" };
  }
  if (!isPending && !superseded) return { card, outcome: "not-owned" };
  const c0 = withTakes(card);
  const n = takeSeqOf(c0) + 1;
  const take = {
    id: "t" + n, n, mid, taskId, at: str(r.at), dur: num(r.dur) > 0 ? num(r.dur) : null,
    trimIn: 0, trimOut: null,
    settings: isPending ? (card.pendingSettings || null) : null,
    anchor: isPending ? (card.pendingAnchor || null) : null,
    imported: false, source: "render",
  };
  if (isPending && card.pendingQuote) take.quoted = card.pendingQuote;
  const withTake = untomb({ ...c0, takes: c0.takes.concat([take]), takeSeq: n }, mid);
  if (!isPending) return { card: withoutSuperseded(withTake, taskId), outcome: "unselected" };
  const c1 = clearPending(mirrorOnto(withTake, take));
  return { card: { ...c1, status: "done", lastAttempt: null }, outcome: "landed" };
};

/**
 * attachTake(card, {mid, dur, imported, settings, at}) -> {card, outcome}
 * The two landings with no task id: the routed draft result ("attach to A·0n", a real
 * render made on this board) and "Use an existing video" (borrowed footage, imported:true).
 * A render still out for this shot is never cancelled by it (F1): its task moves to
 * supersededTasks, so its clip lands later as a take WITHOUT taking ★. While a render's
 * send is unclear there is no task to move, so the attach is refused ("unclear").
 */
export const attachTake = (card, rep) => {
  const r = rep || {};
  const mid = str(r.mid);
  if (!card || !mid) return { card, outcome: "invalid" };
  if (card.pendingSubmitId && !card.pendingTaskId) return { card, outcome: "unclear" };
  let c = withTakes(card);
  if (c.pendingTaskId) {
    const s = (c.supersededTasks || []).concat([str(c.pendingTaskId)]);
    c = { ...c, supersededTasks: s };
  }
  c = clearPending(c);
  const existing = takesOf(c).find((t) => str(t.mid) === mid);
  if (existing) {
    c = untomb(selectTake(c, existing.n), mid);
    return { card: { ...c, status: "done", lastAttempt: null }, outcome: "selected" };
  }
  const n = takeSeqOf(c) + 1;
  const imported = !!r.imported;
  const take = {
    id: "t" + n, n, mid, taskId: "", at: str(r.at), dur: num(r.dur) > 0 ? num(r.dur) : null,
    trimIn: 0, trimOut: null, settings: imported ? null : (r.settings || null), anchor: null,
    imported, source: imported ? "attach" : "render",
  };
  const withTake = untomb({ ...c, takes: c.takes.concat([take]), takeSeq: n }, mid);
  // Selecting writes the outgoing take's trims back first, exactly like a ★ click.
  const sel = selectedTakeOf(c);
  let base = withTake;
  if (sel != null) base = writeBack(withTake, sel);
  return { card: { ...mirrorOnto(base, take), status: "done", lastAttempt: null }, outcome: "landed" };
};

/* ---------- ★ select / delete ---------- */

// The outgoing selected take keeps the trims and crop it was cut to (F9: they lived on the
// card while it was selected).
const writeBack = (card, n) => {
  const v = selectedTakeView(card);
  if (!v || v.n !== n) return card;
  const takes = (card.takes || []).map((t) => {
    if (t.n !== n) return t;
    const out = { ...t, dur: v.dur, trimIn: v.trimIn, trimOut: v.trimOut };
    if (v.crop) out.crop = v.crop; else delete out.crop;
    return out;
  });
  return { ...card, takes };
};

/** ★ select take n. Never renders, prices or uploads. Unknown n -> the card unchanged. */
export const selectTake = (card, n) => {
  if (!card) return card;
  const sel = selectedTakeOf(card);
  if (n === sel) return card;
  const c = withTakes(card);
  const t = c.takes.find((x) => x.n === n);
  if (!t) return card;
  const base = sel != null ? writeBack(c, sel) : c;
  const next = mirrorOnto(base, base.takes.find((x) => x.n === n));
  // A shot in flight stays "wip"; otherwise it is finished (it has a ★ take).
  return { ...next, status: inFlight(card) ? card.status : "done" };
};

/**
 * deleteTake(card, n, at) -> {card, refused?}
 * The ★ take cannot be deleted ("selected"). The clip file is never touched: it is an
 * ordinary library video. A billed take's mid moves to `attempts` so the ledger keeps the
 * money; every deleted mid is tombstoned so a two-tab merge cannot resurrect it (F6).
 * takeSeq is not lowered, so a later take never reuses the number.
 */
export const deleteTake = (card, n, at) => {
  if (!card) return { card, refused: "missing" };
  if (n === selectedTakeOf(card)) return { card, refused: "selected" };
  const c = withTakes(card);
  const t = c.takes.find((x) => x.n === n);
  if (!t) return { card, refused: "missing" };
  const mid = str(t.mid);
  const had = c.attempts || [];
  const attempts = (!t.imported && mid && !had.some((a) => a && str(a.media_id) === mid))
    ? had.concat([{ media_id: mid, at: str(at) }]) : had;
  const tomb = (c.deletedTakes || []).includes(mid) ? (c.deletedTakes || []) : (c.deletedTakes || []).concat([mid]);
  return { card: { ...c, takes: c.takes.filter((x) => x.n !== n), attempts, deletedTakes: tomb } };
};

/* ---------- the settings snapshot (by reference only) ---------- */

// Drop any `data:` string at any depth: a snapshot never carries picture bytes. thumbIds
// stay; the thumbs store already holds those pictures.
const scrub = (v) => {
  if (typeof v === "string") return v.startsWith("data:") ? "" : v;
  if (Array.isArray(v)) return v.map(scrub);
  if (v && typeof v === "object") {
    const o = {};
    Object.keys(v).forEach((k) => { o[k] = scrub(v[k]); });
    return o;
  }
  return v;
};
const frameRef = (f) => {
  const x = f || {};
  return { mediaId: str(x.mediaId), thumbId: str(x.thumbId), source: str(x.source), desc: str(x.desc), tag: str(x.tag) };
};

/** The card's generation fields at submit time. `sentPrompt` is the composed text that
 *  was actually sent; `quality` the payload's own. */
export const snapshotSettings = (card, project, sentPrompt, quality) => {
  const c = card || {};
  return scrub({
    mode: str(c.mode), duration: num(c.duration), quality: str(quality || ((project || {}).draft ? "basic" : "professional")),
    connect: str(c.connect), prompt: str(c.prompt), promptOverride: !!c.promptOverride,
    promptOverrideText: str(c.promptOverrideText), sentPrompt: str(sentPrompt),
    camera: str(c.camera), lighting: str(c.lighting), audioCue: str(c.audioCue),
    audioGen: !!c.audioGen, audioLanguage: str(c.audioLanguage || "english"), isPrivate: !!c.isPrivate,
    cast: (c.cast || []).slice(),
    refs: (c.refs || []).map((r) => ({ id: str(r.id), kind: str(r.kind), tag: str(r.tag), source: str(r.source),
      thumbId: str(r.thumbId), mediaId: str(r.mediaId) })),
    openFrame: frameRef(c.openFrame), closeFrame: frameRef(c.closeFrame),
    look: str((project || {}).look),
  });
};

/** "Reuse settings" for one take: its snapshot, patched back onto the card. A board edit
 *  only; the owner still presses Render. Legacy / attached takes have no snapshot. */
export const reuseSettingsPatch = (card, take) => {
  const s = take && take.settings;
  if (!card || !s) return card;
  const next = { ...card, mode: s.mode || card.mode, duration: s.duration != null ? s.duration : card.duration,
    connect: s.connect || card.connect, prompt: s.prompt, promptOverride: !!s.promptOverride,
    promptOverrideText: s.promptOverrideText || "", camera: s.camera, lighting: s.lighting,
    audioCue: s.audioCue, audioGen: !!s.audioGen, audioLanguage: s.audioLanguage || "english",
    isPrivate: !!s.isPrivate, cast: (s.cast || []).slice(),
    refs: (s.refs || []).map((r) => ({ role: "", ...r })),
    openFrame: { ...(card.openFrame || {}), ...s.openFrame },
    closeFrame: { ...(card.closeFrame || {}), ...s.closeFrame } };
  next.anchor = take.anchor ? { ...take.anchor } : null;
  next.anchorKept = null;
  return next;
};

/* ---------- the render lifecycle markers (BUILD §3.3) ---------- */

/**
 * beginRender(card, {submitId, settings, anchor, board, quote, startedAt}) -> card | null
 * The in-flight marker IS the lock. null = refused, the card is already in flight. A paused
 * render (status wip, its poll stopped at the ceiling) may be rendered again: its task
 * moves to supersededTasks and its late clip lands without ★.
 */
export const beginRender = (card, m, opts) => {
  if (!card) return null;
  const o = opts || {};
  // A send whose answer is still outstanding (or unclear) always refuses: only the owner's
  // "release" (F8) or the answer itself can clear it. Once the answer named a task
  // (adoptTask keeps the submit id beside it) the task rule below decides instead -- else a
  // render this build sent could never use the paused carve-out.
  if (card.pendingSubmitId && !card.pendingTaskId) return null;
  // A task still being polled refuses too, unless the poll has PAUSED at its ceiling.
  if (card.pendingTaskId && !o.pausedOk) return null;
  const x = m || {};
  const c = { ...card };
  if (c.pendingTaskId) c.supersededTasks = (c.supersededTasks || []).concat([str(c.pendingTaskId)]);
  return { ...c, status: "wip", pendingTaskId: null, pendingSubmitId: str(x.submitId),
    pendingSettings: x.settings || null, pendingAnchor: x.anchor || null,
    pendingBoard: x.board ? str(x.board) : null, pendingQuote: x.quote || null,
    genStartedAt: x.startedAt || null };
};

/** Undo beginRender when the lock could not be made durable (the flush failed, F5):
 *  `before` is the card as it was when the click began. */
export const cancelRender = (card, submitId, before) => {
  if (!card || str(card.pendingSubmitId) !== str(submitId)) return card;
  const b = before || {};
  const out = clearPending(card);
  ["status", "pendingTaskId", "genStartedAt", "supersededTasks"].forEach((k) => {
    if (own(b, k)) out[k] = b[k]; else delete out[k];
  });
  return out;
};

/** The server answered with a task id for this submit: the card waits for that task.
 *  A task for a submit this card is no longer waiting for is superseded, never dropped. */
export const adoptTask = (card, submitId, taskId) => {
  if (!card || !taskId) return card;
  if (str(card.pendingSubmitId) === str(submitId)) {
    return { ...card, pendingTaskId: str(taskId), status: "wip" };
  }
  const s = card.supersededTasks || [];
  if (s.includes(str(taskId)) || str(card.pendingTaskId) === str(taskId)) return card;
  return { ...card, supersededTasks: s.concat([str(taskId)]) };
};

/**
 * failRender(card, {submitId?, taskId?, state, msg, at}) -> card
 * A render that ended without a clip: "refused" (nothing was sent or PixAI refused it),
 * "failed" (the task failed), "abandoned" (the owner released an unclear send, F8).
 * Status describes the ★ take (F14): a shot that still has one stays "done" and the
 * failure is recorded in lastAttempt. A report for a render this card is not waiting for
 * only clears that task from supersededTasks.
 */
export const failRender = (card, rep) => {
  const r = rep || {};
  if (!card) return card;
  const matchTask = r.taskId && str(card.pendingTaskId) === str(r.taskId);
  const matchSubmit = r.submitId && str(card.pendingSubmitId) === str(r.submitId);
  if (!matchTask && !matchSubmit) {
    if (r.taskId && (card.supersededTasks || []).some((x) => str(x) === str(r.taskId))) {
      return withoutSuperseded(card, r.taskId);
    }
    return card;
  }
  const c = clearPending(card);
  return { ...c, status: settledStatus(c), lastAttempt: { state: str(r.state || "failed"), msg: str(r.msg), at: str(r.at) } };
};

/** An unclear send (no answer, or an answer that said the render may have started): the
 *  card keeps its lock and says so. Nothing is re-sent. */
export const markUnclear = (card, submitId, msg, at) => {
  if (!card || str(card.pendingSubmitId) !== str(submitId)) return card;
  return { ...card, status: "wip", lastAttempt: { state: "unclear", msg: str(msg), at: str(at) } };
};

/** Undo nothing, re-send nothing: the owner checked Activity and released this shot (F8). */
export const abandonSubmit = (card, submitId, at) =>
  failRender(card, { submitId, state: "abandoned", at,
    msg: "Released after you checked Activity. If that render was sent after all, its clip is in your library." });

/** Classify one POST /api/loom/generate outcome (BUILD §3.3 step 5, review F3).
 *  {threw} or an unreadable body is UNCLEAR; {unclear:true} or a 409 in state "sending" is
 *  UNCLEAR; a task id is ACCEPTED; any other JSON error is a definite REFUSAL. */
export const classifySubmit = ({ threw, status, body } = {}) => {
  if (threw || !body || typeof body !== "object") return { kind: "unclear" };
  if (body.task_id) return { kind: "accepted", taskId: str(body.task_id) };
  if (body.unclear || body.state === "sending" || body.state === "may_have_started") {
    return { kind: "unclear", error: str(body.error) };
  }
  if (status === 409 && body.task_id == null && /already rendering/i.test(str(body.error))) {
    return { kind: "busy", error: str(body.error), taskId: str(body.busy_task_id) };
  }
  return { kind: "refused", error: str(body.error || "submit failed") };
};

/** The submit-status answer as the card should take it. */
export const classifySubmitStatus = (body) => {
  const b = body || {};
  if (b.state === "submitted" && b.task_id) return { kind: "accepted", taskId: str(b.task_id) };
  if (b.state === "refused" || b.state === "not_sent" || b.state === "abandoned") return { kind: "refused", error: str(b.error) };
  return { kind: "unclear", state: str(b.state || "unknown") };
};

/** Cards whose send is unclear (wip, a submit id, no task yet): the resume checks them by
 *  GET /api/loom/submit-status, never by rendering. Deduped by submit id through `seen`. */
export const submitsToCheck = (project, seen) => {
  const s = seen || Object.create(null);
  const out = [];
  ((project || {}).acts || []).forEach((a) => ((a || {}).cards || []).forEach((c) => {
    if (!c || c.status !== "wip" || !c.pendingSubmitId || c.pendingTaskId) return;
    const k = "s:" + c.pendingSubmitId;
    if (own(s, k)) return;
    s[k] = true;
    out.push({ id: c.id, submitId: str(c.pendingSubmitId), board: c.pendingBoard || null });
  }));
  return out;
};

/* ---------- copies of a board never carry a render in flight (F4, F17) ---------- */

/** For duplicateProject, a restored backup or bundle, and any other copy of a board. A
 *  shot that was rendering in the original is settled in the copy: done when it has a ★
 *  take, error otherwise. Its render stays with the original storyboard. */
export const stripInFlight = (project) => {
  if (!project || !Array.isArray(project.acts)) return project;
  return { ...project, acts: project.acts.map((a) => ({ ...a, cards: (a.cards || []).map((c) => {
    if (!c) return c;
    const busy = inFlight(c) || c.status === "wip" || (c.supersededTasks || []).length;
    if (!busy) return c;
    const next = { ...c };
    PENDING.forEach((k) => { delete next[k]; });
    delete next.supersededTasks;
    if (next.status === "wip") {
      next.status = selectedTakeOf(next) != null ? "done" : "error";
      next.lastAttempt = { state: "copied", at: "",
        msg: "This shot was rendering when the storyboard was copied; that render belongs to the original." };
    }
    return next;
  }) })) };
};

/* ---------- RE-ANCHOR (P2) ---------- */

// Where the source's selected take is cut: the frame a handoff takes (trim-aware).
export const cutPointOf = (card) => {
  if (!card) return null;
  if (card.trimOut != null) return Number(card.trimOut);
  const d = num(card.actualDur);
  return d != null ? d : null;
};
const sameAt = (a, b) => (a == null || b == null) ? true : Math.abs(Number(a) - Number(b)) < 0.05;

/** The anchor a splice or a Re-anchor records: the source card's ID (never its code),
 *  its ★ take, the cut point the frame came from, and the frame's own media id. */
export const makeAnchor = (src, frameMid, via) => ({
  shot: str(src && src.id), take: selectedTakeOf(src), at: cutPointOf(src), frame: str(frameMid), via: via || "splice",
});

/**
 * anchorInfo(card, byId) -> {state, src?, from?, to?, reason?}
 *   "none"  no anchor, the source is gone or unrendered, or the open frame has since been
 *           replaced some other way (the anchor only describes the frame it recorded)
 *   "ok"    the source still uses the anchored take, cut at the same point
 *   "kept"  the owner pressed Keep for exactly this pair
 *   "stale" otherwise: peach, "⚠ anchor changed"
 * An UNRENDERED dependent is flagged too (open call 2): that is where a stale frame costs.
 */
export const anchorInfo = (card, byId) => {
  const a = card && card.anchor;
  if (!a || !a.shot) return { state: "none" };
  if (a.frame && str(((card.openFrame || {}).mediaId)) !== str(a.frame)) return { state: "none" };
  const src = byId && (typeof byId.get === "function" ? byId.get(a.shot) : byId[a.shot]);
  if (!src) return { state: "none" };
  const to = selectedTakeOf(src);
  if (to == null) return { state: "none" };
  const at = cutPointOf(src);
  const sameTake = to === a.take;
  const sameCut = sameAt(a.at, at);
  if (sameTake && sameCut) return { state: "ok", src, from: a.take, to };
  const k = card.anchorKept;
  if (k && k.from === a.take && k.to === to && sameAt(k.at, at)) return { state: "kept", src, from: a.take, to };
  return { state: "stale", src, from: a.take, to, reason: sameTake ? "cut" : "take", at, was: a.at };
};
export const anchorState = (card, byId) => anchorInfo(card, byId).state;

/** The card's warning line, in the page's words. `codeOf(id)` names a shot. */
export const staleText = (info, codeOf) => {
  if (!info || info.state !== "stale") return "";
  const code = codeOf ? codeOf(info.src.id) : "the source shot";
  if (info.reason === "cut") {
    return `its open frame came from ${code} take ${info.from} at ${Number(info.was).toFixed(1)} s; ${code} is now cut at ${Number(info.at).toFixed(1)} s.`;
  }
  return `its open frame came from ${code} take ${info.from}; ${code} now uses take ${info.to}.`;
};

/** "Open frame updated. Render a new take to match it." -- after a Re-anchor, until a take
 *  rendered from that anchor is the selected one. */
export const needsNewTake = (card) => {
  const a = card && card.anchor;
  if (!a || a.via !== "reanchor") return false;
  if (a.frame && str(((card.openFrame || {}).mediaId)) !== str(a.frame)) return false;
  const v = selectedTakeView(card);
  if (!v) return true;
  const ta = v.anchor;
  return !(ta && str(ta.shot) === str(a.shot) && ta.take === a.take && str(ta.frame || "") === str(a.frame || ""));
};

/**
 * reanchorPatch(card, {frameMid, src, srcCode, expect}) -> card
 * Swaps the open frame to the source's current cut frame and records the new anchor.
 * Touches openFrame / anchor / anchorKept ONLY: status, takes and every pending marker are
 * left alone, so no render can follow from it. `expect` is the anchor the click saw; if the
 * card's anchor has moved since (a second click, a Keep), nothing is patched.
 */
export const reanchorPatch = (card, m) => {
  const x = m || {};
  if (!card || !x.frameMid || !x.src) return card;
  if (JSON.stringify(card.anchor || null) !== JSON.stringify(x.expect === undefined ? (card.anchor || null) : (x.expect || null))) return card;
  const anchor = makeAnchor(x.src, x.frameMid, "reanchor");
  const of = card.openFrame || {};
  return { ...card,
    openFrame: { ...of, mediaId: str(x.frameMid), thumbId: "", source: "",
      desc: "handed off from " + str(x.srcCode || "the previous shot") + " take " + anchor.take },
    anchor, anchorKept: null };
};

/** The splice button ("✂ splice A·01's last frame"): the same frame patch plus the anchor. */
export const splicePatch = (card, m) => {
  const x = m || {};
  if (!card || !x.frameMid) return card;
  const of = card.openFrame || {};
  return { ...card,
    openFrame: { ...of, mediaId: str(x.frameMid), thumbId: "", source: "",
      desc: "handed off from " + str(x.srcCode || "prev shot") },
    anchor: x.src && selectedTakeOf(x.src) != null ? makeAnchor(x.src, x.frameMid, "splice") : null,
    anchorKept: null };
};

/** Keep: accept this take pair (and this cut) only. A later change of the source warns again. */
export const keepAnchor = (card, src) => {
  if (!card || !card.anchor || !src) return card;
  const to = selectedTakeOf(src);
  if (to == null) return card;
  return { ...card, anchorKept: { from: card.anchor.take, to, at: cutPointOf(src) } };
};

/* ---------- board saves: the no-write-on-open rule and the two-tab merge ---------- */

/** The autosave writes only when the board text differs from what was last read or
 *  saved. Opening a board therefore writes nothing. */
export const shouldSave = (json, lastSavedJson) => typeof json === "string" && json !== lastSavedJson;

const cardsById = (project) => {
  const m = new Map();
  ((project || {}).acts || []).forEach((a, ai) => ((a || {}).cards || []).forEach((c) => { if (c && c.id) m.set(c.id, { c, a, ai }); }));
  return m;
};

/**
 * mergeBoards(local, remote, {resolvedSubmits, base}) -> {project, changed}
 * On a save conflict (another tab saved first). The REMOTE board wins for every field
 * except takes and in-flight markers:
 *  - a local take whose clip remote does not have, and that neither side deleted
 *    (remote.attempts, either side's deletedTakes), is appended with the next number;
 *    a side's tombstones and attempts never count against a clip that same side still
 *    holds as a take (spend review S2: a re-attached clip, an older build's re-roll);
 *  - ★ stays remote's unless remote has none;
 *  - a local pending marker is kept only when remote has no take for that task, has no
 *    render of its own in flight, and the submit is not known to be resolved (F6);
 *  - a card only local has is kept, in its act (or the first), only when it holds a clip that
 *    landed HERE: a take whose clip is on no card of the remote board and was not on that card
 *    in `base` (the board this tab last read or wrote). Without that check a shot the other tab
 *    DELETED came back (its old takes still read as "only here"), and a split made against a
 *    stale board kept its right half beside the other tab's untrimmed shot, so the footage
 *    played twice (red team 2026-10-01). A fresh render or imported clip on a card the other
 *    tab removed is still kept -- it is new footage, possibly paid for. With no `base` (never
 *    read) every local-only card with takes is kept, as before.
 * `changed` names every card whose ★ or take numbers now differ from this tab's view, so
 * the toast can say so.
 */
export const mergeBoards = (local, remote, opts) => {
  if (!remote) return { project: local, changed: [] };
  if (!local) return { project: remote, changed: [] };
  const resolved = new Set(((opts || {}).resolvedSubmits || []).map(str));
  const loc = cardsById(local);
  const changed = [];
  const remIds = cardsById(remote);
  const merged = { ...remote, acts: (remote.acts || []).map((a) => ({ ...a, cards: (a.cards || []).map((rc) => {
    const hit = loc.get(rc.id);
    if (!hit) return rc;
    const lc = hit.c;
    const rTakes = takesOf(rc);
    const rMids = new Set(rTakes.map((t) => str(t.mid)));
    const lMids = new Set(takesOf(lc).map((t) => str(t.mid)));
    // What each side says is gone (spend review S2). A side's tombstones and ledger entries
    // never count against a clip that SAME side still holds as a take: it came back there
    // (re-attached after a delete), or it is a take an older build pushed into attempts on a
    // re-roll (F10) -- neither is a delete. So a take dies only by a delete the other side
    // made while not holding it itself, and remote.attempts is never a tombstone for a take
    // remote still has.
    const dead = new Set([
      ...[...(rc.attempts || []).map((x) => str(x && x.media_id)), ...(rc.deletedTakes || []).map(str)]
        .filter((m) => !rMids.has(m)),
      ...(lc.deletedTakes || []).map(str).filter((m) => !lMids.has(m)),
    ]);
    const extra = takesOf(lc).filter((t) => !rMids.has(str(t.mid)) && !dead.has(str(t.mid)));
    let out = rc;
    const renum = {};
    if (extra.length) {
      out = withTakes(rc);
      let n = takeSeqOf(out);
      const add = extra.map((t) => { n += 1; renum[t.n] = n; return { ...t, id: "t" + n, n }; });
      out = { ...out, takes: out.takes.concat(add), takeSeq: n };
      if (selectedTakeOf(rc) == null) {
        const lsel = selectedTakeOf(lc);
        const target = lsel != null && renum[lsel] != null ? renum[lsel] : null;
        if (target != null) {
          const t = out.takes.find((x) => x.n === target);
          const lv = selectedTakeView(lc);
          out = mirrorOnto(out, { ...t, trimIn: lv.trimIn, trimOut: lv.trimOut, crop: lv.crop, dur: lv.dur });
          if (out.status !== "wip") out = { ...out, status: "done" };
        }
      }
    }
    // Deletions made in either tab stick.
    if (dead.size && Array.isArray(out.takes)) {
      const sel = selectedTakeOf(out);
      const kept = out.takes.filter((t) => t.n === sel || !dead.has(str(t.mid)));
      if (kept.length !== out.takes.length) out = { ...out, takes: kept };
    }
    if ((lc.deletedTakes || []).length || (out.deletedTakes || []).length) {
      // The merged tombstones: both sides', minus any clip the merged card holds as a take
      // (a tombstone beside a live take would delete it at the next merge).
      const held = new Set(takesOf(out).map((t) => str(t.mid)));
      const tomb = Array.from(new Set([...(out.deletedTakes || []).map(str), ...(lc.deletedTakes || []).map(str)]))
        .filter((m) => !held.has(m));
      if (tomb.length) out = { ...out, deletedTakes: tomb };
      else if (own(out, "deletedTakes")) { out = { ...out }; delete out.deletedTakes; }
    }
    // In-flight markers.
    const lpTask = str(lc.pendingTaskId), lpSub = str(lc.pendingSubmitId);
    const remoteBusy = !!(rc.pendingTaskId || rc.pendingSubmitId);
    const taskLanded = lpTask && takesOf(out).some((t) => str(t.taskId) === lpTask);
    if ((lpTask || lpSub) && !remoteBusy && !taskLanded && !(lpSub && resolved.has(lpSub))) {
      PENDING.forEach((k) => { if (lc[k] != null) out = { ...out, [k]: lc[k] }; });
      out = { ...out, status: "wip" };
    }
    const lSup = lc.supersededTasks || [];
    if (lSup.length) {
      const sup = Array.from(new Set([...(out.supersededTasks || []), ...lSup]))
        .filter((tid) => !takesOf(out).some((t) => str(t.taskId) === str(tid)));
      if (sup.length) out = { ...out, supersededTasks: sup };
    }
    const lsel = selectedTakeOf(lc), osel = selectedTakeOf(out);
    const lview = lsel != null ? str(selectedTakeView(lc).mid) : "";
    const oview = osel != null ? str(selectedTakeView(out).mid) : "";
    if (lview !== oview || Object.keys(renum).length) changed.push({ id: rc.id, star: lview !== oview, renumbered: Object.keys(renum).length > 0 });
    return out;
  }) })) };
  // Cards only this tab has: kept when they hold a clip that landed here (a render must not
  // vanish); a deleted shot or a stale split half holds none and stays gone.
  const baseBoard = (opts || {}).base || null;
  const baseCards = baseBoard ? cardsById(baseBoard) : null;
  const remoteMids = new Set();
  remIds.forEach(({ c }) => takesOf(c).forEach((t) => remoteMids.add(str(t.mid))));
  const landedHere = (c) => {
    if (!baseCards) return true;
    const was = baseCards.get(c.id);
    const before = new Set(was ? takesOf(was.c).map((t) => str(t.mid)) : []);
    return takesOf(c).some((t) => { const m = str(t.mid); return m && !remoteMids.has(m) && !before.has(m); });
  };
  loc.forEach(({ c, a }) => {
    if (remIds.has(c.id) || !takesOf(c).length || !landedHere(c)) return;
    const act = merged.acts.find((x) => x.id === a.id) || merged.acts[0];
    if (!act) { merged.acts = [{ ...a, cards: [c] }]; changed.push({ id: c.id, kept: true }); return; }
    act.cards = act.cards.concat([c]);
    changed.push({ id: c.id, kept: true });
  });
  return { project: merged, changed };
};

/* ---------- split and duplicate (F11, §1.5) ---------- */

/** The fields a copied card must never carry (a duplicate is a fresh, unrendered shot). */
export const FRESH_CARD_CLEARS = ["takes", "selectedTake", "takeSeq", "deletedTakes", "supersededTasks",
  "pendingTaskId", "pendingSubmitId", "pendingSettings", "pendingAnchor", "pendingBoard", "pendingQuote",
  "genStartedAt", "lastAttempt", "crop"];
