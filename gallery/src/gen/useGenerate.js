import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { apiGet, apiPost } from "../api.js";
import { buildPayload, clampLoras, GEN_DEFAULTS, goGate, modeAfterApply, toLoraSide, versionPatch } from "./genCore.js";
import {
  LAST_KEY, MODEL_GONE, NEG_KEY, PRESETS_KEY, QUICK_KEY, chipWeight, defaultsFromPrefs, deletePreset,
  entryFromRow, familyOf, favIds, lastNote, negativeOnSwitch, presetNote, presetsFromPrefs,
  quickChips, quickFromPrefs, recordSend, restorePatch, savePreset, snapshotFrom, snapshotOf,
  toggleDefault, toggleFav, baseHintOf, FAMILIES,
} from "./powerCore.js";
import {
  SEED_PROMPT, TSUBAKI3, contextMax, profileLocked, profileRows, renumberAfterRemove,
} from "./tsubakiCore.js";
import { GEN_PREFS_KEY, prefsFromState, stateFromPrefs } from "./genPrefs.js";
import { accountCsrf, accountPrefs } from "../hooks/useAccountPrefs.js";
import { insertTriggerWords, removeTriggerWords } from "./loraTriggers.js";
import { submitTask, useResultLines } from "./submitTask.js";
import usePriceProbe from "./usePriceProbe.js";
import { publishDockPrice, publishDockRequest } from "../recipes/recipesStore.js";
import {
  LISTS_KEY, listsFromPrefs, newRoll, parse, planJobs, runSeedOf, sendRoute,
} from "./templateCore.js";
import useRuns from "./useRuns.js";

/* The image-generation hook. Mirrors the classic Gen IIFE's timing contracts:
   - price: the shared price probe (gen/usePriceProbe.js) owns the 250ms debounce,
     the seq counter so a stale response never paints over a newer one (the
     classic's costSeq), the badge going to "checking" the moment a refresh is
     scheduled, and the payload-identity spend gate that used to live only in the
     video drawer (issue #15). `refreshPrice` keeps its name -- GenerateDrawer's
     Image-tab entry effect and CreateMobile's both prime the badge with it -- and
     now simply delegates to the probe;
   - version/LoRA resolve: seq-guarded the same way;
   - submit: a busyRef latch makes double-submit impossible independent of React
     scheduling, the button re-enables when the server ANSWERS, concurrent
     submissions each own a result line, and there is NO retry anywhere. */

export default function useGenerate({ costRef, isMember }) {
  // Session M: a fresh roll per dock (the page's `roll`), the Random run seed while the seed
  // field is blank.
  const [s, setS] = useState(() => ({ ...GEN_DEFAULTS, roll: newRoll() }));
  const [busy, setBusy] = useState(false);
  const [results, openLine] = useResultLines();
  const verSeq = useRef(0);
  const busyRef = useRef(false);
  const restoringRef = useRef(false);   // a ↺ Last / preset restore is still settling (NOTES 5)
  const sRef = useRef(s);
  sRef.current = s;

  const set = useCallback((patch) => setS((old) => ({ ...old, ...patch })), []);

  /* The account's own store (/api/account/prefs), read here once for every reader below: the
     saved lists (Session M, NOTES 1), and the dock's power tools (NOTES 4-6: a default negative
     per base family, ↺ Last, Presets, the quick-pick chips -- gen/powerCore.js says exactly
     what each holds). The refs let the state updaters and the send callbacks read the CURRENT
     values without being rebuilt on every store change. */
  const prefStore = accountPrefs();
  const prefSnap = useSyncExternalStore(prefStore.subscribe, prefStore.getSnapshot, prefStore.getSnapshot);
  const negDefaults = useMemo(() => defaultsFromPrefs(prefSnap.prefs && prefSnap.prefs[NEG_KEY]), [prefSnap]);
  const presets = useMemo(() => presetsFromPrefs(prefSnap.prefs && prefSnap.prefs[PRESETS_KEY]), [prefSnap]);
  const last = useMemo(() => snapshotFrom(prefSnap.prefs && prefSnap.prefs[LAST_KEY]), [prefSnap]);
  const quick = useMemo(() => quickFromPrefs(prefSnap.prefs && prefSnap.prefs[QUICK_KEY]), [prefSnap]);
  const defaultsRef = useRef(negDefaults);
  defaultsRef.current = negDefaults;
  const presetsRef = useRef(presets);
  presetsRef.current = presets;
  const quickRef = useRef(quick);
  quickRef.current = quick;

  /* PixAI membership (true / false / null), from the host's /api/account read. It rides in the
     state because the size tiers, the custom-size limit and the Pro / Ultra rows are pure
     functions of it (tsubakiCore.tierLocked / profileLocked). */
  useEffect(() => {
    const v = isMember === true ? true : isMember === false ? false : null;
    setS((old) => (old.member === v ? old : { ...old, member: v }));
  }, [isMember]);

  /* The dock's settings, per account (the wave-1 store, /api/account/prefs, key gen.image):
     creativity, the size tier, the frame, Auto, the profile and the recipe row (gen/genPrefs.js
     says exactly which, and validates what comes back). Read once when the store is ready,
     written 500 ms after the last change. Never the prompt, the model or the images. */
  const prefsLoaded = useRef(false);
  useEffect(() => {
    const store = accountPrefs();
    const take = () => {
      const snap = store.getSnapshot();
      if (prefsLoaded.current || snap.status !== "ready") return;
      prefsLoaded.current = true;
      const patch = stateFromPrefs(snap.prefs && snap.prefs[GEN_PREFS_KEY]);
      if (Object.keys(patch).length) setS((old) => ({ ...old, ...patch }));
    };
    const off = store.subscribe(take);
    store.ensureLoaded().then(take);
    take();
    return off;
  }, []);
  const prefsTimer = useRef(0);
  const prefsLast = useRef("");
  const persistedKey = JSON.stringify(prefsFromState(s));
  useEffect(() => {
    if (!prefsLoaded.current) return undefined;
    // The first value after the load is the loaded one (or the defaults): nothing to write.
    if (!prefsLast.current) { prefsLast.current = persistedKey; return undefined; }
    if (prefsLast.current === persistedKey) return undefined;
    clearTimeout(prefsTimer.current);
    prefsTimer.current = setTimeout(() => {
      prefsLast.current = persistedKey;
      accountPrefs().set(GEN_PREFS_KEY, JSON.parse(persistedKey));
    }, 500);
    return () => clearTimeout(prefsTimer.current);
  }, [persistedKey]);

  /* ---- price preview: the SAME payload builder the submit uses ---- */
  const build = useCallback(() => {
    const p = buildPayload(s);
    // No model version = nothing to price: a plain clear() back to the badge's own
    // "Pick a model to see the cost." hint, exactly as this hook always did. That is
    // a verdict, not a gap -- goGate() is what refuses a submit in that state, and it
    // must stay reachable, so the gate below is never what silences it.
    return { payload: p, idle: p.version_id ? null : true };
  }, [s]);
  const probe = usePriceProbe({ build, costRef });
  const refreshPrice = probe.refresh;
  const priceOk = probe.canSubmit;   // the identity gate, ANDed into goGate at the buttons
  const priceAnswer = probe.response;

  // Lane w2-recipes' row and picker read the dock's request (the prompt budget, a candidate
  // recipe priced against it) and its last price answer (PixAI's own recipe refusal paints
  // the chip peach). One dock per page, so this hook is the one publisher.
  useEffect(() => {
    publishDockRequest(buildPayload(s), { modelTitle: (s.model && s.model.title) || "" });
  }, [s]);
  useEffect(() => { publishDockPrice(priceAnswer); }, [priceAnswer]);

  // Structural cost inputs only -- prompt/negative/seed text never refires,
  // matching the classic. steps IS structural (it changes the upscale pass too).
  // (All three text fields are in the probe's identity skip, so even a stray call
  // short-circuits -- this list is now an optimisation, not a correctness rule.)
  useEffect(() => { refreshPrice(); }, [
    s.model, s.loras, s.ref, s.refStrength, s.boosters,
    s.aspect, s.size, s.customW, s.customH, s.count, s.highPriority,
    s.mode, s.steps, s.unlimited, s.palette,
    s.inputs, s.ctx, s.auto, s.landscape, s.tier, s.creativity, s.recipes, s.member,
    // Session M: Matrix sends one image per cell, so switching the mode moves the payload's
    // count -- a structural input like the count itself.
    s.varMode,
  ]); // eslint-disable-line react-hooks/exhaustive-deps

  /* ---- model pick -> version resolve (seq-guarded) ---- */
  const applyFromVersion = (v) => versionPatch(v);

  /* Only patch a field the version actually carries -- the classic's
     applyModelDefaults ("only for fields the model has data for"). The first cut
     wiped a typed negative/steps/cfg to empty on any preset-less model. */
  const presetPatch = (v) => {
    const out = {};
    if (v.negative_prompt) out.negative = v.negative_prompt;
    if (v.sampling_steps != null && v.sampling_steps !== "") out.steps = String(v.sampling_steps);
    if (v.cfg_scale != null && v.cfg_scale !== "") out.cfg = String(v.cfg_scale);
    return out;
  };

  /* Returns the applied model shape ({model_id, version_id, versions, ...}) on
     success and null on failure or a verSeq drop. Callers historically ignore
     this; Remix (issue #4) keys on it -- state can't answer "did MY apply
     land, and which versions exist" in an async flow (React batches the setS,
     so an eager-updater read right after the await sees the PRE-apply state;
     that false-negatived the exact-version check on a live run, 2026-08-13). */
  const applyModelRow = useCallback(async (row, opts) => {
    const seq = ++verSeq.current;
    // A restore that cannot find its model (`keepOnFail`) puts the model that was there
    // back, instead of leaving the failed stub in its place.
    const prev = sRef.current.model;
    setS((old) => ({
      ...old,
      model: { model_id: row.model_id, title: row.title, thumb: row.preview_url || row.cover_url || "", version_id: "", resolving: true },
    }));
    try {
      const d = await apiGet("/api/model-version?model_id=" +
        encodeURIComponent(row.model_id) + "&all=1");
      if (seq !== verSeq.current) return null;
      const versions = d.versions || [];
      const latest = versions.find((v) => v.is_latest) || versions[0];
      if (!latest || !latest.version_id) throw new Error(d.error || "no versions");
      const model = {
        model_id: row.model_id, title: row.title,
        thumb: row.preview_url || row.cover_url || "",
        // Pony / Illustrious / Flux are what the model CARD says (the picker's base_model); the
        // family a default negative belongs to is read off this and the architecture (powerCore).
        base_hint: baseHintOf(row.base_model) || (FAMILIES.includes(row.base_hint) ? row.base_hint : ""),
        version_id: latest.version_id, model_type: latest.model_type || "",
        versions, ...applyFromVersion(latest),
      };
      setS((old) => {
        // NOTES 4: the family's default negative fills in when the family changes (or is the
        // session's first) and the field is empty or still the old default; an author preset,
        // applied below it, still wins.
        const fam = familyOf(model);
        const sw = negativeOnSwitch({ from: old.family, to: fam, negative: old.negative, defaults: defaultsRef.current });
        return {
          ...old, model, family: fam || old.family,
          // weights re-clamped to the NEW architecture, and an armed hires chip
          // disarmed when this version can't upscale (classic gateBooster).
          loras: clampLoras(old.loras, model.model_type),
          boosters: model.compat_upscale === false
            ? { ...old.boosters, hires: false } : old.boosters,
          // ...and a quality mode this version does not offer drops back to `auto`
          // (genCore.modeAfterApply). Dimming the bar only stops the next CLICK; a mode
          // carried in on a model switch would still be priced and still be submitted,
          // then silently re-run on the model's default tier -- the very divergence the
          // dimming closes (red team 2026-09-07).
          mode: rowSafeMode(modeAfterApply(old.mode, model.profiles), model, old.member),
          negative: sw.negative, note: sw.note,
          ...presetPatch(latest),
        };
      });
      return model;
    } catch {
      if (seq !== verSeq.current) return null;
      if (opts && opts.keepOnFail) {
        setS((old) => ({ ...old, model: prev }));
        return null;
      }
      setS((old) => ({
        ...old,
        model: { model_id: row.model_id, title: row.title, thumb: row.preview_url || row.cover_url || "", version_id: "", failed: true },
      }));
      if (window.Toast) window.Toast.show({ kind: "err", title: "Model lookup failed", msg: row.title });
      return null;
    }
  }, []);

  const pickVersion = useCallback((versionId) => {
    setS((old) => {
      const v = (old.model.versions || []).find((x) => x.version_id === versionId);
      if (!v) return old;
      const model = {
        ...old.model, version_id: v.version_id, model_type: v.model_type || "",
        ...applyFromVersion(v),
      };
      const fam = familyOf(model);
      const sw = negativeOnSwitch({ from: old.family, to: fam, negative: old.negative, defaults: defaultsRef.current });
      return {
        ...old, model, family: fam || old.family,
        loras: clampLoras(old.loras, model.model_type),
        boosters: model.compat_upscale === false
          ? { ...old.boosters, hires: false } : old.boosters,
        // Same reset as applyModelRow: picking another VERSION of the same model changes
        // the offered profile set too (Tsubaki.2 -> .3 is one model, two sets).
        mode: rowSafeMode(modeAfterApply(old.mode, model.profiles), model, old.member),
        negative: sw.negative, note: sw.note || old.note,
        ...presetPatch(v),
      };
    });
  }, []);

  /* ---- LoRA lifecycle ----
     The multi picker hands us the row itself plus its selected flag; it has
     ALREADY resolved version/architecture/trigger words, so this upserts from
     the row and only falls back to a fetch when a field is missing.
     trigger_words is a comma-separated STRING server-side, not an array.

     TRIGGER WORDS AUTO-INSERT (issue #45): picking a LoRA appends its activation
     tokens to the prompt, matching PixAI's own composer -- a LoRA attached without
     them is a silent no-op on a paid gen. The rule (formatting AND dedupe) lives in
     gen/loraTriggers.js so both composers and the manual "+words" button share ONE
     implementation; this is simply where the pick is observed. It has to happen in
     BOTH state writes below, because a picker row already carrying trigger_words and
     a row whose words only arrive with the /api/model-version resolve are two
     different moments and only one of them fires per pick.

     `opts.autoInsert === false` opts a caller out. Remix (GenerateDrawer's
     prefillRun) is the one caller that passes it: a remix RESTORES a recipe, and the
     prompt it just wrote is the one that actually rendered the artwork. Appending
     tokens the original run did not use would quietly change the recipe the owner is
     reading back before he pays for it. Picking a LoRA is a choice; restoring one is
     a reproduction. */
  const addLora = useCallback(async (row, opts) => {
    const autoInsert = !(opts && opts.autoInsert === false);
    let present = false;
    setS((old) => {
      present = old.loras.some((l) => l.model_id === row.model_id);
      if (present) return old;
      const words = typeof row.trigger_words === "string" ? row.trigger_words : "";
      return {
        ...old,
        prompt: autoInsert ? insertTriggerWords(old.prompt, words) : old.prompt,
        loras: old.loras.concat([{
          model_id: row.model_id, title: row.title, preview_url: row.preview_url,
          // Remix (issue #4) hands rows carrying the task's EXACT weight; the
          // picker's market rows have none and keep the 0.7 default. Honoring
          // it here (not via a follow-up setLora) is what keeps a two-versions-
          // of-one-LoRA task from cross-patching the wrong entry's weight
          // (adversarial review 2026-08-13, finding 1.1).
          version_id: row.version_id || "",
          weight: Number.isFinite(+row.weight) ? +row.weight : 0.7,
          lora_base_type: row.lora_base_model_type || row.model_type || "",
          trigger_words: words,
          versions: [],
        }]),
      };
    });
    if (present || row.version_id) return;   // the picker already resolved it
    try {
      const d = await apiGet("/api/model-version?model_id=" +
        encodeURIComponent(row.model_id) + "&all=1");
      const versions = d.versions || [];
      const latest = versions.find((v) => v.is_latest) || versions[0];
      if (!latest || !latest.version_id) throw new Error("unresolved");
      const words = typeof latest.trigger_words === "string" ? latest.trigger_words : "";
      setS((old) => ({
        ...old,
        // The words arrived late (the picker row had none to hand over) -- insert them
        // now, on the same dedupe rule, so a slow resolve is not a surface where the
        // feature quietly does not happen.
        prompt: autoInsert ? insertTriggerWords(old.prompt, words) : old.prompt,
        loras: old.loras.map((l) => l.model_id === row.model_id ? {
          ...l, version_id: latest.version_id,
          lora_base_type: latest.lora_base_model_type || "",
          trigger_words: words,
          versions,
        } : l),
      }));
    } catch {
      setS((old) => ({
        ...old,
        loras: old.loras.map((l) => l.model_id === row.model_id ? { ...l, failed: true } : l),
      }));
    }
  }, []);

  /* UN-PICKING a LoRA takes its trigger words back out again (owner, from live use
     2026-09-04: "Removing a Lora on pixai DOES remove words" -- the ruling on #45 is
     "matches PixAI behavior", and leaving dead activation tokens in the box does not).
     The rule is gen/loraTriggers.js's, the same matching the insert and the dedupe use;
     this is only where the un-pick is observed -- and it is the ONE place, so the desktop
     drawer's x, the mobile chip's x and either picker's un-toggle all get it, because
     every one of them calls this. keepWords is the union of the trigger words of the
     LoRAs that REMAIN: a token two LoRAs share is still arming the other one and must
     survive. */
  const removeLora = useCallback((modelId) => {
    setS((old) => {
      const gone = old.loras.find((l) => l.model_id === modelId);
      if (!gone) return old;
      const loras = old.loras.filter((l) => l.model_id !== modelId);
      return {
        ...old,
        prompt: removeTriggerWords(old.prompt, gone.trigger_words,
                                   loras.map((l) => l.trigger_words)),
        loras,
      };
    });
  }, []);

  const setLora = useCallback((modelId, patch) => {
    setS((old) => ({
      ...old,
      loras: old.loras.map((l) => (l.model_id === modelId ? { ...l, ...patch } : l)),
    }));
  }, []);

  /* ---- Session M: the template, its lists, the run road ----
     The account's saved lists (gen.lists) come from the shared account store; the dock
     expands the prompt only to DRAW it (the tint, the preview, "Send N"). The server
     re-expands everything itself. */
  const lists = useMemo(() => listsFromPrefs(prefSnap.prefs), [prefSnap]);
  const saveLists = useCallback((next) => prefStore.set(LISTS_KEY, next), [prefStore]);
  const parsed = useMemo(() => parse(s.prompt, lists), [s.prompt, lists]);
  const runSeed = runSeedOf(s.seed, s.roll);
  const plan = useMemo(() => planJobs(s.prompt, lists, s.varMode || "random",
    s.varMode === "matrix" ? 1 : Math.max(1, Math.min(4, Number(s.count) || 1)),
    runSeed == null ? 0 : runSeed), [s.prompt, lists, s.varMode, s.count, runSeed]);
  const route = sendRoute(plan, parsed.syntax);
  // A Random run needs a seed in range; the server refuses the same.
  const seedGate = plan && plan.mode === "random" && runSeed == null
    ? "A Random run's seed must be between 0 and 2,147,483,646 — or leave the seed blank" : null;
  const templateGate = parsed.error || (plan && plan.error) || seedGate || null;
  const longest = plan && !plan.error && parsed.vars.length
    ? Math.max(...plan.jobs.map((j) => j.prompt.length)) : null;
  // What was sent, captured when the send starts (the composer may change while it runs):
  // a send the server ACCEPTED becomes ↺ Last and moves the quick-pick recents.
  const sentRef = useRef(null);
  const noteSent = useCallback((sn) => {
    if (!sn) return;
    const store = accountPrefs();
    store.set(LAST_KEY, snapshotOf(sn, { withSeed: true }));
    store.set(QUICK_KEY, recordSend(quickRef.current, sn));
  }, []);
  const runs = useRuns({
    openLine,
    onSettled: (res) => {
      refreshPrice({ force: true });
      if (res && Array.isArray(res.jobs) && res.jobs.some((j) => j && (j.state === "sent" || j.task_id))) {
        noteSent(sentRef.current);
      }
    },
  });
  const runBody = useCallback(() => ({
    ...buildPayload(s), var_mode: s.varMode || "random",
    ...(runSeed != null ? { run_seed: runSeed } : {}),
  }), [s, runSeed]);
  // An open confirm describes the body it was quoted for; a change to the dock closes it
  // (the page closes it on any change), so Go can never send settings nobody looked at.
  const bodyKey = JSON.stringify(runBody());
  const cancelRun = runs.cancel;
  useEffect(() => { cancelRun(); }, [bodyKey, cancelRun]);

  /* ---- submit: NO retries, body-keyed errors, adjusted always recorded ---- */
  const generate = useCallback(async (loraCap) => {
    if (busyRef.current || runs.busyRef.current || restoringRef.current) return;   // latch, independent of render timing
    if (goGate(s, loraCap, priceAnswer, longest)) return;
    if (templateGate || route === "blocked") return;
    // PAYLOAD IDENTITY gate. The Generate buttons are already disabled on
    // g.canSubmit; this is the click that slips through a stale render (a keyboard
    // Enter needs no repaint to fire). The quote on the badge must have been priced
    // off THIS payload -- never a silent drop: re-price and let the button come back.
    if (!priceOk) { refreshPrice(); return; }
    // Session M (NOTES 2): more than one generation opens THE ONE confirm (the server's own
    // quote); one generation whose prompt uses the syntax goes to the run route, which
    // expands it and records its template. A plain single send is today's, unchanged.
    if (route === "confirm") { runs.openConfirm(runBody()); return; }
    if (route === "run") { sentRef.current = s; runs.sendSingle(runBody()); return; }
    busyRef.current = true;
    setBusy(true);
    const emit = openLine("Submitting…");
    // ONE shared submit path for every spend route -- see gen/submitTask.js for
    // the contract it enforces (no retry, body-keyed errors, adjusted on the
    // line, cb(phase, data) tracking).
    const taskId = await submitTask("/api/generate", buildPayload(s), { label: "Generated", emit });
    if (taskId) noteSent(s);
    busyRef.current = false;                   // the classic unlocks on ANSWER
    setBusy(false);
    // The submit just DEBITED credits or a card, so the settled verdict is stale even
    // though the payload is byte-identical -- identity-by-payload cannot see a balance
    // change caused by our own submit. FORCED, or the short-circuit would swallow it
    // as "nothing changed" -- but the balance did.
    refreshPrice({ force: true });
  }, [s, openLine, priceOk, priceAnswer, refreshPrice, runs, route, templateGate, longest, runBody, noteSent]);

  /* ---- the context slots (Session H decision 1) ----
     addContext appends (a picture already in a slot is not added twice, and the live max is
     the ceiling); removeContext drops slot k and renumbers the prompt's @image refs -- a ref to
     the removed slot turns into the peach "no image" chip (tsubakiCore.renumberAfterRemove). */
  const addContext = useCallback((img) => {
    if (!img || !img.media_id) return;
    setS((old) => {
      const ctx = old.ctx || [];
      if (ctx.some((c) => c.media_id === String(img.media_id))) return old;
      if (ctx.length >= contextMax(old.model)) return old;
      return { ...old, ctx: ctx.concat([{ media_id: String(img.media_id), thumb: img.thumb || "",
        w: Number(img.w) || 0, h: Number(img.h) || 0 }]) };
    });
  }, []);
  const removeContext = useCallback((k) => {
    setS((old) => {
      const ctx = old.ctx || [];
      if (k < 0 || k >= ctx.length) return old;
      return { ...old, ctx: ctx.filter((_, j) => j !== k), prompt: renumberAfterRemove(old.prompt, k) };
    });
  }, []);
  /* The measured size of a slot's picture, when the picker could not say (an upload). */
  const sizeContext = useCallback((mediaId, w, h) => {
    setS((old) => ({ ...old, ctx: (old.ctx || []).map((c) => (c.media_id === mediaId
      && !(c.w > 0 && c.h > 0) ? { ...c, w: Number(w) || 0, h: Number(h) || 0 } : c)) }));
  }, []);

  /* "Edit with Tsubaki" (decision 2): the Image tab on Tsubaki.3, the picture in context slot 1,
     the prompt seeded "Use @image1 ...". Prefill only -- nothing is spent until the owner
     presses Generate. Tsubaki.3 is applied only when it is not already the model, so an applied
     version (and its LoRAs, held on this side) is left as it is. */
  const tsubakiEdit = useCallback(async (img) => {
    if (!img || !img.media_id) return false;
    const cur = sRef.current.model;
    if (!cur || cur.model_id !== TSUBAKI3.model_id || !cur.version_id) {
      const model = await applyModelRow({ model_id: TSUBAKI3.model_id, title: TSUBAKI3.title, preview_url: "" });
      if (!model) return false;
    }
    setS((old) => ({
      ...old, inputs: "context", ctxWarned: true, auto: true, prompt: SEED_PROMPT,
      customW: "", customH: "",            // Auto sizes a Tsubaki edit (decision 1)
      ctx: [{ media_id: String(img.media_id), thumb: img.thumb || "/thumbs/" + img.media_id + ".jpg",
        w: Number(img.w) || 0, h: Number(img.h) || 0 }],
    }));
    return true;
  }, [applyModelRow]);

  /* A LoRA from outside the picker (Train a LoRA's "Use"): onto the LoRA side first, so it is
     sent rather than held behind context images (genCore.toLoraSide), then the picker's own
     addLora road, trigger words and all. A pick; nothing is generated. */
  const takeLora = useCallback((row) => {
    setS(toLoraSide);
    return addLora(row);
  }, [addLora]);

  /* ---- NOTES 4-6: the default negative, ↺ Last, Presets, the quick-pick chips ----
     Nothing here writes on open: the account store is written by a deliberate click (Save,
     ★, Set as default, a chip) or by a send the server accepted (noteSent above). */
  const [restoring, setRestoring] = useState(false);
  const restoreSeq = useRef(0);
  /* Fill the composer from a snapshot (↺ Last, a preset). It PREFILLS, never sends. The model
     is applied first (a snapshot's model that PixAI no longer lists leaves the current one in
     place and says so), then every field the snapshot holds, then its LoRAs at their weights --
     added the way a Remix restores them, WITHOUT trigger words (a restore reproduces; the
     prompt it wrote is the prompt that was used). The seed is only Last's. */
  const restoreComposer = useCallback(async (snap, { note, withSeed }) => {
    if (!snap) return;
    const my = ++restoreSeq.current;
    const live = () => restoreSeq.current === my;
    restoringRef.current = true;
    setRestoring(true);
    try {
      let modelGone = false;
      if (snap.model) {
        const cur = sRef.current.model;
        const same = !!(cur && cur.model_id === snap.model.model_id && cur.version_id);
        let applied = same ? cur : null;
        if (!same) {
          applied = await applyModelRow({ model_id: snap.model.model_id, title: snap.model.title,
            preview_url: snap.model.thumb, base_hint: snap.model.base_hint }, { keepOnFail: true });
          if (!live()) return;
          if (!applied) modelGone = true;
        }
        if (applied && snap.model.version_id && applied.version_id !== snap.model.version_id
            && (applied.versions || []).some((v) => v.version_id === snap.model.version_id)) {
          pickVersion(snap.model.version_id);
        }
      }
      setS((old) => ({
        ...old, ...restorePatch(snap, { withSeed }),
        loras: [],
        mode: rowSafeMode(modeAfterApply(snap.mode, old.model && old.model.profiles), old.model, old.member),
        note: modelGone ? note + " " + MODEL_GONE : note,
      }));
      for (const l of snap.loras) {
        await addLora({ model_id: l.model_id, title: l.title, preview_url: l.preview_url,
          version_id: l.version_id, weight: l.weight, lora_base_model_type: l.lora_base_type,
          trigger_words: l.trigger_words }, { autoInsert: false });
        if (!live()) return;
      }
    } finally {
      if (live()) { restoringRef.current = false; setRestoring(false); }
    }
  }, [applyModelRow, pickVersion, addLora]);
  const restoreLast = useCallback(() => restoreComposer(last, { note: lastNote(), withSeed: true }), [restoreComposer, last]);
  const restorePreset = useCallback((p) => restoreComposer(p, { note: presetNote(p.name), withSeed: false }), [restoreComposer]);
  const savePresetAs = useCallback(async (name) => {
    const r = savePreset(presetsRef.current, name, snapshotOf(sRef.current));
    if (r.error) return { error: r.error };
    const d = await accountPrefs().set(PRESETS_KEY, r.list);
    if (d && d.error) return { error: d.error };
    setS((old) => ({ ...old, note: "Saved preset “" + String(name).trim() + "”." }));
    return { ok: true };
  }, []);
  const removePreset = useCallback((name) => accountPrefs().set(PRESETS_KEY, deletePreset(presetsRef.current, name)), []);
  const toggleNegDefault = useCallback(() => {
    const cur = sRef.current;
    const r = toggleDefault({ family: cur.family, negative: cur.negative, defaults: defaultsRef.current });
    if (r.error) { setS((old) => ({ ...old, note: r.error })); return; }
    accountPrefs().set(NEG_KEY, r.defaults);
    setS((old) => ({ ...old, note: r.note }));
  }, []);
  const pickModelChip = useCallback((e) => applyModelRow({ model_id: e.id, title: e.title,
    preview_url: e.thumb, base_hint: e.hint }), [applyModelRow]);
  const toggleLoraChip = useCallback((e) => {
    if (sRef.current.loras.some((l) => String(l.model_id) === e.id)) { removeLora(e.id); return; }
    addLora({ model_id: e.id, title: e.title, preview_url: e.thumb, weight: chipWeight(quickRef.current, e.id),
      lora_base_model_type: e.base });
  }, [addLora, removeLora]);
  const toggleQuickFav = useCallback((kind, row) => {
    const e = entryFromRow(kind, row);
    if (e) accountPrefs().set(QUICK_KEY, toggleFav(quickRef.current, kind, e));
  }, []);
  const power = {
    family: s.family, defaults: negDefaults, presets, last, quick, note: s.note, restoring,
    restoreLast, restorePreset, savePresetAs, removePreset, toggleNegDefault,
    modelChips: quickChips(quick, "base", s), loraChips: quickChips(quick, "lora", s),
    pickModelChip, toggleLoraChip, toggleQuickFav,
    favModels: favIds(quick, "base"), favLoras: favIds(quick, "lora"),
    clearNote: () => setS((old) => (old.note ? { ...old, note: "" } : old)),
  };

  return { s, set, busy: busy || runs.busy, results, applyModelRow, pickVersion, power,
           addLora, takeLora, removeLora, setLora, generate, refreshPrice,
           addContext, removeContext, sizeContext, tsubakiEdit,
           canSubmit: priceOk, priceAnswer,
           // Session M: the template and the run road, for the dock and the phone
           run: { parsed, plan, route, templateGate, longest, lists, saveLists,
                  confirm: runs.confirm, go: () => { sentRef.current = sRef.current; return runs.go(); },
                  cancel: runs.cancel, busy: runs.busy,
                  last: runs.last, images: plan && !plan.error ? plan.images : 0,
                  // The Inspector's "preview · not sent yet" for a dock with no open
                  // confirm: /plan is read-only and writes nothing.
                  preview: () => apiPost("/api/generate/plan", { ...runBody(), csrf: accountCsrf() }) } };
}

/* T1a: a members-only profile row is never picked for an account PixAI reports as non-member,
   so a mode carried in from a member session drops back to `auto` when a version applies. */
function rowSafeMode(mode, model, member) {
  const rows = profileRows(model);
  const row = rows && rows.find((r) => String(r.name).toLowerCase() === String(mode || "").toLowerCase());
  return row && profileLocked(row, member) ? "auto" : mode;
}

