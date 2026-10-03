import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { apiGet, apiPost, apiUpload } from "../../api.js";
import {
  CAPTION_MAX, GOALS, LONG_TRIGGER_ARCHS, MAX_IMAGES, MIN_IMAGES, acceptCostField, advancedGates,
  archTabs, basicFooterCost, countedItems, defaultBase, imageProblem, loraForDock, markRejected,
  mergeImages, reuseCandidate, roomLeft, triggerCheck,
} from "../../gen/trainCore.js";
import { LIBRARY } from "../../apiRoutes.js";

/* Train a LoRA, Session J (Training Handoff, 2026-09-28) -- the state and the calls behind BOTH
   the desktop overlay (TrainOverlay.jsx) and the phone screen (TrainMobile.jsx). The two draw
   the same flows differently; nothing here draws. The rules are gen/trainCore.js's; the server
   re-checks every one that touches money or the account (BUILD-w3-train.md).

   NOTHING WRITES ON OPEN (DECISIONS 2026-09-28). Opening the overlay, a wizard, a draft or the
   runs list only reads. Each write is a deliberate press: an upload, adding images to a draft,
   "Next · creates a draft", Describe, a description edit, Start, Retry, Publish.

   SPENDING. Every paid press is two calls, preview then confirm, and the confirm carries the
   NUMBER the user was shown (acceptCostField / the caption total / the start quote); the server
   refuses it if that is no longer the price. A double press is harmless: each paid call is
   guarded here by a busy flag, and on the server by a per-run lock and, for a Basic start or a
   retry, an on-disk guard. */

export const USE_LORA_EVENT = "mg-use-lora";

/* Advanced's focus view owns Escape (handoff 3c: "Esc returns to the grid"), the way the
   Control Panel owns its own ladder: while it is up, App.jsx's capture-phase overlay closer
   stands aside (it reads this), and the focus view's own listener takes the grid back. */
let escOwners = 0;
export function trainOwnsEscape() { return escOwners > 0; }
export function holdTrainEscape() {
  escOwners += 1;
  let held = true;
  return () => { if (held) { held = false; escOwners -= 1; } };
}

/* "Use" (handoff 5c): a trained LoRA into the Generate dock (desktop) or the Create tab
   (phone). The hosts listen; this only announces. */
export function useLoraInDock(row, archOf) {
  const detail = loraForDock(row, archOf);
  if (!detail) return;
  window.dispatchEvent(new CustomEvent(USE_LORA_EVENT, { detail }));
}

function bootCsrf() {
  try { return (window.MG_BOOT && window.MG_BOOT.csrf) || ""; } catch { return ""; }
}

/* The CSRF token every write carries: the page's own (MG_BOOT), or the one /api/account/prefs
   hands back when the page has none. */
export function useCsrf() {
  const [csrf, setCsrf] = useState(bootCsrf);
  useEffect(() => {
    if (csrf) return;
    apiGet("/api/account/prefs").then((d) => { if (d && d.csrf) setCsrf(d.csrf); });
  }, [csrf]);
  return csrf;
}

/* What every screen reads once: PixAI's training config (bases by architecture with the
   Recommended one, prices, Advanced's two bases, the goals, the estimate, the pause switch) and
   the member's free trainings. Read-only. */
export function useTrainSetup() {
  const [cfg, setCfg] = useState(null);
  const [quota, setQuota] = useState(null);
  useEffect(() => {
    let live = true;
    apiGet("/api/train/models").then((d) => { if (live) setCfg(d || {}); });
    apiGet("/api/train/quota").then((d) => {
      if (live) setQuota(typeof d.free_trainings === "number" ? d.free_trainings : 0);
    });
    return () => { live = false; };
  }, []);
  const tabs = useMemo(() => archTabs((cfg && cfg.groups) || []), [cfg]);
  const archOf = useCallback((versionId) => {
    for (const t of tabs) if (t.models.some((m) => m.version_id === versionId)) return t.arch;
    return "";
  }, [tabs]);
  return { cfg, tabs, quota, archOf, goals: (cfg && cfg.goals && cfg.goals.length) ? cfg.goals : GOALS,
    paused: !!(cfg && cfg.paused), resumesAt: (cfg && cfg.resumes_at) || "" };
}

/* The runs list (handoff 5c) and the pinned strip. `light` reads only what is running (the
   chooser and the Activity panel); the full list is Runs. Polls every 15 s while something is
   queued, training or being described -- PixAI's own page polls its list the same way -- and
   only while the host is mounted and the tab is visible. */
export function useTrainRuns({ light = false, enabled = true } = {}) {
  const [state, setState] = useState({ runs: [], running: [], errors: [], loaded: false });
  const busy = useRef(false);
  const again = useRef(false);
  const refresh = useCallback(() => {
    // A refresh asked for while one is in flight (a publish or retry landing mid-poll) runs
    // once more after it, so the list never keeps the answer from before the change.
    if (busy.current) { again.current = true; return Promise.resolve(); }
    busy.current = true;
    return apiGet("/api/train/runs" + (light ? "?running=1" : "")).then((d) => {
      busy.current = false;
      if (again.current) { again.current = false; setTimeout(() => refresh(), 0); }
      if (!d || d.error) {
        setState((s) => ({ ...s, loaded: true, errors: [d && d.error ? d.error : "no answer"] }));
        return;
      }
      setState({ runs: d.runs || [], running: d.running || [], errors: d.errors || [], loaded: true });
    });
  }, [light]);
  useEffect(() => { if (enabled) refresh(); }, [enabled, refresh]);
  const live = state.runs.some((r) => ["running", "waiting", "captioning"].includes(r.status))
    || state.running.length > 0;
  useEffect(() => {
    if (!enabled || !live) return undefined;
    const t = setInterval(() => {
      if (typeof document === "undefined" || document.visibilityState !== "hidden") refresh();
    }, 15000);
    return () => clearInterval(t);
  }, [enabled, live, refresh]);
  return { ...state, refresh };
}

/* The history pool (handoff 2a "From history": the shipped pool that pages on scroll, Grouped /
   All, search). Grouped pages by TASK through /api/train/recent-tasks (issue #56); All pages
   single pictures through /api/library. `loadMore` is what a sentinel calls. */
export function useHistoryPool({ mode = "all", q = "" } = {}) {
  const [items, setItems] = useState([]);
  const cursor = useRef(null);
  const page = useRef(0);
  const done = useRef(false);
  const busy = useRef(false);
  const gen = useRef(0);
  useEffect(() => {
    gen.current += 1;
    cursor.current = null; page.current = 0; done.current = false; busy.current = false;
    setItems([]);
  }, [mode, q]);
  const loadMore = useCallback(() => {
    if (busy.current || done.current) return;
    busy.current = true;
    const my = gen.current;
    if (mode === "grouped") {
      const c = cursor.current;
      apiGet("/api/train/recent-tasks", {
        limit: 18, before_at: c ? c.at : "", before_task: c ? c.task : "", q,
      }).then((d) => {
        if (my !== gen.current) return;
        busy.current = false;
        if (!d || d.error) return;
        cursor.current = d.next_before || null;
        if (!d.next_before) done.current = true;
        const incoming = (d.tasks || []).map((t) => ({
          key: "t:" + t.task_id, task_id: t.task_id, media_ids: t.media_ids, count: t.count,
          thumb: t.thumb }));
        setItems((old) => {
          const seen = new Set(old.map((x) => x.key));
          return old.concat(incoming.filter((x) => !seen.has(x.key) && seen.add(x.key)));
        });
      });
    } else {
      const next = page.current + 1;
      apiGet(LIBRARY, { page: next, page_size: 60, media: "image", sort: "newest", q })
        .then((d) => {
          if (my !== gen.current) return;
          busy.current = false;
          if (!d || d.error) return;
          page.current = next;
          if (next >= (Number(d.pages) || next)) done.current = true;
          const incoming = (d.items || []).filter((x) => x && x.media_id).map((x) => ({
            key: "m:" + x.media_id, media_id: String(x.media_id), thumb: x.thumb }));
          setItems((old) => {
            const seen = new Set(old.map((x) => x.key));
            return old.concat(incoming.filter((x) => !seen.has(x.key) && seen.add(x.key)));
          });
        });
    }
  }, [mode, q]);
  return { items, loadMore, exhausted: () => done.current };
}

/* Read an upload's own size before it leaves the machine (PixAI's rule, the site's own check). */
function fileSize(file) {
  return new Promise((resolve) => {
    if (typeof createImageBitmap === "function") {
      createImageBitmap(file).then((b) => {
        const s = { w: b.width, h: b.height };
        if (b.close) b.close();
        resolve(s);
      }).catch(() => resolve({ w: 0, h: 0 }));
      return;
    }
    const url = URL.createObjectURL(file);
    const im = new Image();
    im.onload = () => { resolve({ w: im.naturalWidth, h: im.naturalHeight }); URL.revokeObjectURL(url); };
    im.onerror = () => { resolve({ w: 0, h: 0 }); URL.revokeObjectURL(url); };
    im.src = url;
  });
}

/* Upload pictures from the device to PixAI (free; the existing /api/upload road), each checked
   against PixAI's rule first -- a refused one never leaves, and comes back with its reason. */
export async function uploadTrainingFiles(files, rule, room) {
  const ok = [], rejected = [];
  for (const f of Array.from(files || [])) {
    if (ok.length >= room) { rejected.push({ name: f.name, reason: "no room left of 100" }); continue; }
    if (!/^image\/(png|jpeg|webp)$/.test(f.type || "")) {
      rejected.push({ name: f.name, reason: "not a PNG, JPG or WebP" });
      continue;
    }
    const { w, h } = await fileSize(f);
    const why = imageProblem(w, h, rule);
    if (why) { rejected.push({ name: f.name, reason: why }); continue; }
    const fd = new FormData();
    fd.append("file", f);
    const d = await apiUpload("/api/upload", fd);
    if (!d || d.error || !d.media_id) {
      rejected.push({ name: f.name, reason: (d && d.error) || "the upload failed" });
      continue;
    }
    ok.push({ media_id: String(d.media_id), thumb: URL.createObjectURL(f), source: "upload" });
  }
  return { ok, rejected };
}

/* ------------------------------------------------------------------------------------ Basic */

export function useBasicTraining(setup, csrf) {
  const [goal, setGoal] = useState("");
  const [items, setItems] = useState([]);
  const [rejects, setRejects] = useState([]);
  const [datasets, setDatasets] = useState(null);
  const [imported, setImported] = useState([]);       // the sets imported whole, by task id
  const [name, setName] = useState("");
  const [trigger, setTrigger] = useState("");
  const [tab, setTab] = useState(null);
  const [base, setBase] = useState("");
  const [ask, setAsk] = useState(null);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(null);
  const [maybe, setMaybe] = useState(false);

  // The pre-selected base: the server's default (Tsubaki.3, Recommended -- 6a).
  useEffect(() => {
    if (!setup.cfg || base) return;
    const d = defaultBase(setup.cfg.groups || [], setup.cfg.default_version_id || "");
    setTab(d.tab);
    setBase(d.base);
  }, [setup.cfg]);   // eslint-disable-line react-hooks/exhaustive-deps

  const tabs = setup.tabs;
  const curTab = tab !== null ? tabs[tab] : null;
  const pickTab = (i) => {
    setTab(i);
    const t = tabs[i];
    setBase(t && t.models.length ? t.models[0].version_id : "");
  };
  const baseName = useMemo(() => {
    for (const t of tabs) for (const m of t.models) if (m.version_id === base) return m.title;
    return "";
  }, [tabs, base]);
  const needsLong = curTab ? LONG_TRIGGER_ARCHS.includes(curTab.arch) : false;
  const trig = triggerCheck(trigger, needsLong);
  const importedSets = (datasets || []).filter((d) => imported.includes(d.task_id));
  const counted = countedItems(items);
  const reuseId = reuseCandidate(items, importedSets);
  const footer = basicFooterCost({ quota: setup.quota || 0, tab: curTab, reuse: !!reuseId });

  // A quote is for ONE form: any change takes the confirm down with its tick (the shipped rule).
  useEffect(() => { setAsk(null); setAccepted(false); }, [base, tab, items, trigger, name, goal]);

  const dsAsked = useRef(false);
  const loadDatasets = useCallback(() => {
    if (dsAsked.current) return;
    dsAsked.current = true;
    apiGet("/api/train/datasets").then((d) => setDatasets((d && d.datasets) || []));
  }, []);

  const itemsRef = useRef(items);
  itemsRef.current = items;
  const addImages = (incoming, source) => {
    const res = mergeImages(itemsRef.current, incoming, source);
    itemsRef.current = res.items;
    setItems(res.items);
    return res;
  };
  const removeImage = (mid) => {
    setItems((cur) => cur.filter((x) => x.media_id !== mid));
  };
  const importSets = (sets) => {
    const add = [];
    for (const d of sets) for (const m of d.media_ids) add.push({ media_id: m, thumb: "/api/train/thumb/" + m });
    addImages(add, "dataset");
    setImported((cur) => cur.concat(sets.map((d) => d.task_id).filter((t) => !cur.includes(t))));
  };
  /* Importing a set offers its old name, trigger and category (handoff 2a) -- only into empty
     fields, never over what was typed. */
  const takeDetails = (d) => {
    if (!name.trim() && d.title) setName(d.title);
    if (!trigger.trim() && d.trigger_words) setTrigger(d.trigger_words);
    if (!goal && d.category && GOALS.some((g) => g.value === d.category)) setGoal(d.category);
  };
  const upload = async (files) => {
    setErr("");
    const room = roomLeft(itemsRef.current);
    const { ok, rejected } = await uploadTrainingFiles(files, setup.cfg && setup.cfg.image_constraints, room);
    if (ok.length) addImages(ok, "upload");
    if (rejected.length) setRejects((r) => r.concat(rejected));
  };

  const enough = counted.length >= MIN_IMAGES;
  const ready = !!goal && enough && !!name.trim() && trig.ok && !!base && !setup.paused;

  const body = () => ({
    base_model_id: base, media_ids: counted.map((x) => x.media_id), title: name,
    trigger_words: trigger, category: goal, dataset_task_id: reuseId, csrf,
  });

  const preview = async () => {
    if (busy) return;
    setBusy(true); setErr(""); setMaybe(false);
    const p = await apiPost("/api/train/submit", body());
    setBusy(false);
    if (p.error) {
      // PixAI's image rule refused some pictures: they stay in the grid, peach, with the
      // reason, and stop counting (handoff 2a). Nothing was sent anywhere.
      if (Array.isArray(p.rejected_images) && p.rejected_images.length) {
        const next = markRejected(itemsRef.current, p.rejected_images);
        itemsRef.current = next;
        setItems(next);
        setErr("PixAI won't train on " + p.rejected_images.length + " of these pictures; they're marked in the grid and left out. Take them out or add others, then start again.");
        return;
      }
      setErr(p.error);
      return;
    }
    setAsk(p); setAccepted(false);
  };
  const confirm = async () => {
    if (busy || !ask) return;
    setBusy(true); setErr("");
    const r = await apiPost("/api/train/submit", { ...body(), confirm: true, ...acceptCostField(ask, accepted) });
    setBusy(false);
    if (r.error) {
      setErr(r.error);
      if (r.maybe_started) { setMaybe(true); setAsk(null); }
      return;
    }
    setDone(r); setAsk(null);
  };

  return {
    goal, setGoal, items, counted, addImages, removeImage, rejects, clearRejects: () => setRejects([]),
    datasets, loadDatasets, importSets, imported, takeDetails, upload,
    name, setName, trigger, setTrigger, trig, tabs, tab, pickTab, base, setBase, baseName,
    reuseId, footer, enough, ready, ask, setAsk, accepted, setAccepted, busy, err, setErr,
    done, maybe, preview, confirm,
  };
}

/* --------------------------------------------------------------------------------- Advanced */

/* One advanced draft (handoff 3c, corrected by the 2026-09-28 capture: images are added on the
   Descriptions step, PixAI describes them first -- paid, the only way in -- and a description
   can be rewritten only after that, up to 1,000 characters). Both the desktop wizard
   (TrainAdvanced.jsx) and the phone's Advanced steps (TrainMobile.jsx) draw this.

   THE PAID PRESSES, each ONE deliberate confirm naming PixAI's own quoted number:
   - Describe: the draft's read (GET /api/train/advanced/<id>) carries PixAI's per-task
     describe quote (`caption_quote`: the count and the total); `describe()` sends exactly that
     total as accept_credit_cost. The server re-quotes and refuses a different number (409,
     nothing sent), and the fresh quote is read back for the next ask.
   - Start: "Next: parameters" asks the run's price (a preview; nothing is spent) and Start
     sends that number back. The server re-quotes the same way.
   Neither is ever retried here: a failed press shows its error and waits for another press. */
export function useAdvancedTraining(setup, csrf, initialDraftId) {
  const [draftId, setDraftId] = useState(initialDraftId || "");
  const [phase, setPhase] = useState(initialDraftId ? "descriptions" : "setup");
  const [name, setName] = useState("");
  const [trigger, setTrigger] = useState("");
  const [goal, setGoal] = useState("character");
  const [base, setBase] = useState("");
  const [detail, setDetail] = useState(null);
  const [edits, setEdits] = useState({});           // mid -> text not yet saved
  const [saving, setSaving] = useState(0);
  const [startAsk, setStartAsk] = useState(null);   // the start's quote (a preview)
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const [rejected, setRejected] = useState([]);
  const [started, setStarted] = useState(null);
  const [maybe, setMaybe] = useState(false);
  const [describeHeld, setDescribeHeld] = useState(false);  // a describe answered maybe_started

  const bases = (setup.cfg && setup.cfg.advanced_bases) || [];
  useEffect(() => {
    if (!base && bases.length) setBase(bases[0].version_id);
  }, [bases.length]);   // eslint-disable-line react-hooks/exhaustive-deps
  const trig = triggerCheck(trigger, true);      // both advanced bases are DiT.2 / DiT.3

  const load = useCallback(async (id) => {
    const tid = id || draftId;
    if (!tid) return null;
    const d = await apiGet("/api/train/advanced/" + encodeURIComponent(tid));
    if (d.error) { setErr(d.error); return null; }
    setDetail(d);
    return d;
  }, [draftId]);
  useEffect(() => { if (initialDraftId) load(initialDraftId); }, [initialDraftId]);   // eslint-disable-line react-hooks/exhaustive-deps

  const status = detail ? detail.task.status : "";
  // While PixAI describes, look again every 4 s (its own page polls every 3). A read.
  useEffect(() => {
    if (status !== "captioning") return undefined;
    const t = setInterval(() => { load(); }, 4000);
    return () => clearInterval(t);
  }, [status, load]);

  /* "Next · creates a draft": the one call that creates it, on the press, once. The button
     disables on press (busy) and a created draft is never created again from here. */
  const createDraft = async () => {
    if (busy) return;
    if (draftId) { setPhase("descriptions"); return; }
    setBusy("draft"); setErr("");
    const d = await apiPost("/api/train/advanced/draft", {
      base_model_id: base, title: name, trigger_words: trigger, category: goal, csrf });
    if (d.error) { setBusy(""); setErr(d.error); return; }
    setDraftId(d.id);
    setPhase("descriptions");
    await load(d.id);
    setBusy("");
  };

  const mediaIds = detail ? detail.task.media_ids : [];
  /* Adding or removing images replaces the draft's set on PixAI (free) -- a press, not an open. */
  const putMedia = async (ids) => {
    if (!draftId) return false;
    setBusy("media"); setErr(""); setRejected([]);
    const d = await apiPost("/api/train/advanced/" + draftId + "/media", { media_ids: ids, csrf });
    if (d.error) {
      setBusy("");
      setErr(d.error);
      if (d.rejected_ids) setRejected(d.rejected_ids);
      return false;
    }
    await load();
    setBusy("");
    return true;
  };
  const addImages = (incoming) => {
    const merged = mergeImages(mediaIds.map((m) => ({ media_id: m, source: "history" })), incoming, "history");
    if (merged.items.length === mediaIds.length) return Promise.resolve(false);
    return putMedia(merged.items.map((x) => x.media_id));
  };
  const removeImage = (mid) => putMedia(mediaIds.filter((m) => m !== mid));
  const upload = async (files) => {
    setErr("");
    const room = Math.max(0, MAX_IMAGES - mediaIds.length);
    const { ok, rejected: rj } = await uploadTrainingFiles(files, setup.cfg && setup.cfg.image_constraints, room);
    if (ok.length) await addImages(ok);
    if (rj.length) setErr(rj.map((r) => r.name + ": " + r.reason).join(" · "));
  };

  /* Descriptions. A save goes after a 900 ms pause in typing (and when the owner leaves the
     image), one at a time per draft, and Describe / Next / Start wait for them all (spend
     review, finding 9). Only a changed, non-empty text of 1-1,000 characters is sent. */
  const queue = useRef(Promise.resolve());
  const timers = useRef({});
  const pending = useRef(0);
  const editsRef = useRef(edits);
  editsRef.current = edits;
  const detailRef = useRef(detail);
  detailRef.current = detail;
  const saveNow = useCallback((mid, text) => {
    const t = String(text || "").trim();
    if (!t || t.length > CAPTION_MAX) return;
    const cur = detailRef.current && detailRef.current.captions && detailRef.current.captions[mid];
    if (cur && cur.text === t) {
      setEdits((e) => { if (e[mid] !== text) return e; const n = { ...e }; delete n[mid]; return n; });
      return;
    }
    pending.current += 1;
    setSaving(pending.current);
    queue.current = queue.current.then(async () => {
      const d = await apiPost("/api/train/advanced/" + draftId + "/captions/" + mid, { text: t, csrf });
      pending.current -= 1;
      setSaving(pending.current);
      if (d.error) { setErr(d.error); return; }
      setEdits((e) => { if (e[mid] !== text) return e; const n = { ...e }; delete n[mid]; return n; });
      setDetail((c0) => {
        if (!c0) return c0;
        const c = { ...(c0.captions || {}) };
        const old = c[mid] || {};
        c[mid] = { source: "user", text: t, machine_text: old.machine_text !== undefined ? old.machine_text : old.text };
        return { ...c0, captions: c };
      });
    });
  }, [draftId, csrf]);
  const editCaption = (mid, text) => {
    setEdits((e) => ({ ...e, [mid]: text }));
    clearTimeout(timers.current[mid]);
    timers.current[mid] = setTimeout(() => { delete timers.current[mid]; saveNow(mid, text); }, 900);
  };
  /* Leaving an image (the focus view moves, Esc, the grid) saves its edit now. */
  const saveOne = (mid) => {
    if (timers.current[mid] === undefined) return;
    clearTimeout(timers.current[mid]);
    delete timers.current[mid];
    if (editsRef.current[mid] !== undefined) saveNow(mid, editsRef.current[mid]);
  };
  const flush = async () => {
    for (const mid of Object.keys(timers.current)) saveOne(mid);
    await queue.current;
  };
  useEffect(() => () => { Object.values(timers.current).forEach(clearTimeout); }, []);
  const textOf = (mid) => {
    if (edits[mid] !== undefined) return edits[mid];
    const c = detail && detail.captions && detail.captions[mid];
    return c ? (c.text === null ? null : c.text) : undefined;
  };
  /* Apply a change to many descriptions at once (find/replace, +/- tag, restore automatic):
     each changed one is saved through the same one-at-a-time queue. Answers how many changed. */
  const applyAll = (mids, fn) => {
    let n = 0;
    const next = {};
    for (const mid of mids) {
      const cur = textOf(mid);
      if (typeof cur !== "string") continue;
      const out = fn(cur, mid);
      if (typeof out === "string" && out !== cur) { next[mid] = out; n += 1; }
    }
    if (!n) return 0;
    setEdits((e) => ({ ...e, ...next }));
    for (const [mid, t] of Object.entries(next)) {
      clearTimeout(timers.current[mid]);
      delete timers.current[mid];
      saveNow(mid, t);
    }
    return n;
  };
  const restoreAutomatic = (mids) => applyAll(mids, (cur, mid) => {
    const c = detail && detail.captions && detail.captions[mid];
    return c && typeof c.machine_text === "string" && c.machine_text ? c.machine_text : null;
  });

  const captions = (detail && detail.captions) || {};
  const quote = (detail && detail.caption_quote) || null;
  const gates = advancedGates({ mediaIds, captions, quote, saving, status, busy, held: describeHeld });

  /* Describe automatically (PAID; the only way in): ONE send, from the ask's own button
     ("Describe · price" -- the desktop's ask card, the phone's sheet; never the entry button
     that opens them), sending PixAI's own quote -- the number on that button -- as the
     acknowledged amount. */
  const describe = async () => {
    if (busy || !gates.describe || !quote) return;
    const total = quote.total_price;
    setBusy("describe"); setErr("");
    await flush();
    const d = await apiPost("/api/train/advanced/" + draftId + "/caption",
      { confirm: true, accept_credit_cost: total, csrf });
    if (d.error) setErr(d.error);
    // PixAI didn't answer clearly (or the server's guard says an earlier one may have gone
    // through): drop the ask -- the button stays off, and the answer's own words say to
    // check Runs. Never a second paid press on an unclear answer.
    if (d.maybe_started) setDescribeHeld(true);
    await load();
    setBusy("");
  };

  /* "Next: parameters": the saves first, then PixAI's price for the run (a free quote). */
  const toParameters = async () => {
    if (busy || !gates.next) return;
    setBusy("quote"); setErr(""); setStartAsk(null);
    await flush();
    const d = await apiPost("/api/train/advanced/" + draftId + "/submit", { csrf });
    setBusy("");
    if (d.error) { setErr(d.error); return; }
    setStartAsk(d);
    setPhase("parameters");
  };
  const refreshQuote = async () => {
    if (busy) return;
    setBusy("quote"); setErr("");
    const d = await apiPost("/api/train/advanced/" + draftId + "/submit", { csrf });
    setBusy("");
    if (d.error) { setErr(d.error); setStartAsk(null); return; }
    setStartAsk(d);
  };

  /* Start (PAID): ONE press, sending the quoted price on the button. */
  const start = async () => {
    if (busy || !startAsk || started) return;
    setBusy("start"); setErr(""); setMaybe(false);
    await flush();
    const d = await apiPost("/api/train/advanced/" + draftId + "/submit",
      { confirm: true, ...(startAsk.is_free ? {} : { accept_credit_cost: startAsk.price }), csrf });
    setBusy("");
    if (d.error) {
      setErr(d.error);
      if (d.maybe_started) { setMaybe(true); setStartAsk(null); }
      return;
    }
    setStarted(d);
  };

  return {
    draftId, phase, setPhase, name, setName, trigger, setTrigger, trig, goal, setGoal, base,
    setBase, bases, detail, status, load, createDraft, mediaIds, addImages, removeImage, upload,
    rejected, captions, quote, gates, edits, textOf, editCaption, saveOne, applyAll,
    restoreAutomatic, saving, flush, describe, toParameters, refreshQuote, startAsk, start,
    started, maybe, busy, err, setErr,
    enough: mediaIds.length >= MIN_IMAGES,
    allDescribed: mediaIds.length > 0 && gates.left === 0,
  };
}

/* --------------------------------------------------------------------- Retry and Publish */

/* Retry a failed advanced run (PAID, a new run): PixAI's quote for it, then the confirm with
   that number. */
export function useRetry(csrf, onDone) {
  const [ask, setAsk] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [accepted, setAccepted] = useState(false);
  const preview = async (row) => {
    if (busy) return;
    setBusy(true); setErr(""); setAccepted(false);
    const d = await apiPost("/api/train/runs/" + row.id + "/retry", { csrf });
    setBusy(false);
    if (d.error) { setErr(d.error); return; }
    setAsk({ ...d, row });
  };
  const confirm = async () => {
    if (busy || !ask) return;
    setBusy(true); setErr("");
    const d = await apiPost("/api/train/runs/" + ask.row.id + "/retry",
      { confirm: true, ...(ask.is_free ? {} : { accept_credit_cost: accepted ? ask.price : false }), csrf });
    setBusy(false);
    if (d.error) { setErr(d.error); if (d.maybe_started) setAsk(null); if (onDone) onDone(); return; }
    setAsk(null);
    if (onDone) onDone(d);
  };
  return { ask, setAsk, busy, err, setErr, accepted, setAccepted, preview, confirm };
}

/* Publish a finished run, or make a private LoRA public later (IRREVERSIBLE; handoff 4a). The
   sheet's ticks travel as the `acknowledged` keys the server checks. */
export function usePublish(csrf, onDone) {
  const [target, setTarget] = useState(null);     // {mode: "publish"|"make-public", row}
  const [vis, setVis] = useState("private");
  const [rebate, setRebate] = useState(false);
  const [ticks, setTicks] = useState({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [rebateOffer, setRebateOffer] = useState(true);
  const open = (mode, row) => {
    setTarget({ mode, row }); setErr(""); setTicks({});
    setVis(mode === "make-public" ? "public" : "private");
    setRebate(false);
    setRebateOffer(mode === "publish");
    if (mode === "make-public" && row.model_id) {
      apiGet("/api/train/models/" + row.model_id + "/rebates")
        .then((d) => setRebateOffer(!!(d && d.can_join)));
    }
  };
  const close = () => { if (!busy) setTarget(null); };
  const pickVis = (v) => {
    if (target && target.mode === "make-public") return;
    setVis(v); setTicks({});
    if (v !== "public") setRebate(false);
  };
  const submit = async (keys) => {
    if (busy || !target) return;
    setBusy(true); setErr("");
    const url = target.mode === "make-public"
      ? "/api/train/models/" + target.row.model_id + "/make-public"
      : "/api/train/runs/" + target.row.id + "/publish";
    const body = target.mode === "make-public"
      ? { rebate: rebate ? "join" : "decline", acknowledged: keys, csrf }
      : { visibility: vis, rebate: vis === "public" && rebate ? "join" : "decline", acknowledged: keys, csrf };
    const d = await apiPost(url, body);
    setBusy(false);
    if (d.error) { setErr(d.error); return; }
    setTarget(null);
    if (onDone) onDone(d);
  };
  return { target, open, close, vis, pickVis, rebate, setRebate, rebateOffer, ticks, setTicks,
    busy, err, submit };
}
