import React, {
  forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState,
} from "react";
import { apiUpload } from "../api.js";
import { createPortal } from "react-dom";
import CostBadge from "./CostBadge.jsx";
import {
  MODELS, MODEL_VMODES, MODEL_MAXDUR, MODE_LBL, MODE_PH, CHANNEL_CAP, CAMERA_OPTS, AUDIO_LANGS,
  DEFAULT_MODEL, MODEL_CARD, SHOT_LABEL, modelCaps, modelMeta, bankView,
  friendlyGenErr, refItem, primaryBank, setPrimaryBank, buildPayload, hasAnyRef,
  applyMode as applyModeState,
  applyModelGating as gateModelState,
  applySetRefs as applySetRefsState,
  applyPrefill as applyPrefillState,
  flfMissingStart as flfMissingStartOf,
} from "../gen/videoDrawerCore.js";
import usePriceProbe from "../gen/usePriceProbe.js";
import { submitTask } from "../gen/submitTask.js";
import { CEILING_MS } from "../notify/pollCadence.js";
import { chipify as refChipify, promptText as refPromptText } from "../gen/refChips.js";
import "../styles/gen-drawer.css";

/* VideoDrawer -- the React port of static/mg-generate-drawer.js's <mg-generate-drawer> (no-vanilla
   campaign, component 7, the last one). The shared VIDEO generation form: 3 modes (i2v / first-
   last-frame / reference-to-video), 6 image + 3 video + 1 audio ref banks, the 7-model roster
   with capability gating, negative prompt, Channel, live cost (embedded React CostBadge), and
   submit. Mounted by the gallery's Generate dock (Video tab), mobile's Video mode, and the Loom's
   video drawer.

   SUBMIT RIDES THE ROAD (2026-08-23). This drawer no longer POSTs /api/loom/generate itself and
   no longer owns a poll loop: doGenerate() calls gen/submitTask.js like the three image routes
   do, and completion arrives through the Jobs engine's one poller. Two things were wrong with
   the old arrangement, and neither was visible from inside this file. (1) It never registered
   its own job -- it dispatched mg-submit and trusted the HOST to call Jobs.register. The desktop
   shell did; AppMobile did not, so a video started from the phone reached neither the Activity
   tray nor the server's orphan sweep. Registration now belongs to the road (submitTask ->
   Jobs.track -> register), which every surface rides, so no host can forget it. (2) Its poller
   carried a hand-copied duplicate of the Loom's tier thresholds under a "KEEP IN SYNC" comment;
   that table is now notify/pollCadence.js and there is exactly one gallery-side poller reading
   it. Still ONE poll loop per task -- this drawer's was REPLACED by the engine's, not joined to
   it. What stayed here is what is genuinely the drawer's: the refusal gates before any spend,
   the wording of every status tier, and all eleven DOM events.

   PORT SHAPE. The vanilla was an event-based CUSTOM ELEMENT driven imperatively (prefill()) by its
   hosts; this stays a DROP-IN for that contract, not a rewrite of it:
   - The ref resolves to the ROOT DOM NODE with prefill/setRefs/flushPromptEdit/setBusy/payload hung
     directly on it and a `mode` getter (see the useImperativeHandle below) -- so bindGenDrawer's
     el.addEventListener + el.prefill, App.jsx's document-level listeners, and every createElement
     call site keep working against a real node, exactly as they did against the custom element.
   - The 11 events stay BUBBLING, composed DOM CustomEvents dispatched off that node (emit()), NOT
     React callback props: mg-submit / mg-result / mg-error / mg-slow / mg-paused / mg-dirty /
     mg-prompt-commit / mg-mode-commit / mg-duration-commit / mg-audio-commit / mg-pick-request
     (the last carrying a respond() in its detail). Hosts catch them unchanged.
   - MUTABLE form state lives in ONE ref (`st`) with a forceUpdate tick, mirroring the vanilla's
     `this._*` fields exactly. This is deliberate over useState on the SPEND-critical prefill path:
     prefill()'s mode->slots->gating sequence reads state it just mutated, which React's batched
     async setState would make subtly wrong (a stale read here spends real credits on the wrong
     shot -- the exact class of bug the vanilla's comments catalogue). Refs + one render read give
     the vanilla's synchronous semantics with React doing the paint.
   - The contenteditable prompt (@image/@video/@audio chips) and the floating ref preview are
     managed IMPERATIVELY through refs; React renders their wrapper once and never touches their
     children (the classic contenteditable+React trap). The chipify/promptText logic is verbatim.
   - Concurrent result lines are React state, one per submission, patched by id -- PixAI runs
     tasks in parallel and a second submit must never overwrite the first one's live status.
     Each submission's tracking is the Jobs engine's, outside this component's lifecycle, so an
     in-flight ~210k-credit video render is not orphaned by a view closing (a host still defers
     unmount 360ms for the .mgd-closing exit; that is now animation, not spend safety).

   Props: `loomCtx` (hide the drawer's own Camera/quality -- the Loom owns equivalents) and
   `dock` (below). All other host communication is through the ref's methods and the bubbling
   DOM events above.

   DOCK MODE (`dock` prop, Generate dock only -- 2026-08-16 fidelity pass, Frontend
   Gallery.dc.html 1541-1591). The DC draws ONE composer footer at the dock level -- prompt
   box, NEGATIVE row (while expanded), cost stack + Generate -- shared by every tab. Rather
   than a second submit path in the dock, THIS component keeps owning its prompt, negative,
   CostBadge and Generate button and simply RENDERS them into the dock's footer slots via React
   portals: `dock = { topEl, promptEl, negativeEl, goEl, balance, expanded }`, each *El a DOM
   node the dock owns (null until mounted -- nothing renders for that slot until it exists; in
   dock mode the pieces never render inline, so the contenteditable prompt mounts exactly once
   and its imperative content survives tab switches); `expanded` is the dock's ▲ state -- the
   three settings slabs hide (CSS only) while it is false, as the DC's settings grid does
   (DC 1209). The Generate button in the footer is the
   SAME button: same `canGo` (price-identity gate), same doGenerate, same "Rendering…" latch;
   the CostBadge in the footer is the SAME instance costRef drives (the price probe untouched).
   Without `dock` (the Loom, mobile Video mode) everything renders inline exactly as before. */

let lineSeq = 0;

const VideoDrawer = forwardRef(function VideoDrawer(props, ref) {
  // `style`/`className` pass through to the root so a host can position/hide the node exactly as
  // it did the custom element (the Loom mounts it once and toggles style.display by tab).
  const { loomCtx, style, className, dock } = props;
  const inDock = !!dock;

  // ---- mutable form state (the vanilla's this._* fields), one ref + a forceUpdate ----------
  const st = useRef({
    mode: "i2v",
    slots: [null],       // i2v/flf primary bank ([0]=start, [1]=end for flf)
    imgSlots: [null],    // r2v image bank (max 6)
    vidSlots: [],        // r2v video bank (max 3)
    audSlot: null,       // {media_id, filename} | null
    model: DEFAULT_MODEL,
    duration: 5,
    camera: "unset",
    quality: "professional",
    channel: "normal",
    audioGen: false,
    audioLanguage: "english",
    videoHelper: false,  // DC 1919: 'Video prompt helper' off by default (the opposite of image gen)
    negative: "",
    modeNote: "",
    rendering: false,
    hostBusy: false,
    // The price VERDICT no longer lives here: it is the shared probe's React state
    // (gen/usePriceProbe.js), which is also what repaints on every transition -- the
    // rerender() that used to sit beside each verdict write by hand.
  });
  const [, force] = useState(0);
  const rerender = useCallback(() => force((n) => n + 1), []);

  const [results, setResults] = useState([]);   // concurrent result lines
  // The ↺-from chip (SCOPE_2026-08-17 §2): "prefilled from run #NNNN", the video mirror of the
  // dock's image chip (GenerateDrawer.reuseFrom). {tag, partial} | null -- `partial` is the amber
  // "recipe from the catalog only / camera unknown / …" disclosure (§2.4). Set imperatively by the
  // host's prefillVideoFromRun via node.setReuse; cleared on the user's × click and on submit
  // (a new render's recipe is no longer "from" the old run). Plain React state -- it is not a
  // spend-critical form field, so the st.current/rerender discipline the payload needs is overkill.
  const [reuse, setReuseChip] = useState(null);
  const ceRef = useRef(null);                    // the contenteditable prompt
  const previewRef = useRef(null);
  const audFileRef = useRef(null);
  const costRef = useRef(null);
  const rootRef = useRef(null);
  // liveNode retains the root node even AFTER React unmounts it (React nulls rootRef on unmount).
  // A submit that resolves after the drawer unmounts (e.g. the Loom's Mobile-view toggle flipped
  // mid-render) must still dispatch its spend-tracking mg-submit: the host bound that listener
  // with addEventListener directly on the node, and addEventListener listeners fire on a detached
  // node. That dispatch is what persists pendingTaskId so an already-charged render is recoverable
  // on reload -- the vanilla dispatched off its retained element for exactly this reason; nulling
  // on unmount turned a recoverable case into a silent ~210k-credit loss. It matters for the LATER
  // phases too now that tracking outlives the component: mg-result / mg-error / mg-slow /
  // mg-paused all leave through this same retained node.
  const liveNode = useRef(null);
  const setRoot = useCallback((n) => { rootRef.current = n; if (n) liveNode.current = n; }, []);

  const chipTimer = useRef(0);
  const previewTimer = useRef(0);
  const dirty = useRef(false);

  // The vanilla was event-based: it dispatched BUBBLING, composed CustomEvents from its own node,
  // and its hosts (the gallery's document-level listeners in App.jsx, the Loom's bindGenDrawer via
  // addEventListener) caught them. Preserved verbatim -- this stays a drop-in: emit() dispatches
  // the same events off the root node, so every existing listener keeps working with no rewrite.
  const emit = useCallback((name, detail) => {
    const n = liveNode.current;   // retained across unmount (see setRoot) so a post-unmount submit still fires
    if (n) n.dispatchEvent(new CustomEvent(name, { bubbles: true, composed: true, detail: detail || {} }));
  }, []);
  // Only this drawer's own PAINT timers are swept on unmount. There is deliberately nothing
  // here about tracking a submitted task any more: the poll that watches a ~210k-credit render
  // is the Jobs engine's (notify/jobs.js), a module singleton outside every React lifecycle,
  // holding no reference to this component. It keeps ticking to a terminal phase whatever this
  // node does -- which is the property this drawer used to try to fake by deferring unmount.
  useEffect(() => () => {
    clearTimeout(chipTimer.current); clearTimeout(previewTimer.current);
  }, []);

  // ---- the primary (image) slot bank ---------------------------------------------------------
  // Thin wrappers over the PURE state layer in videoDrawerCore.js (which the loom node-tests hit
  // directly). The React side owns only the paint (ce placeholder, rerender) + pricing (the price probe).
  const primary = () => primaryBank(st.current);
  const setPrimary = (arr) => setPrimaryBank(st.current, arr);
  const syncPlaceholder = () => { if (ceRef.current) ceRef.current.setAttribute("data-placeholder", MODE_PH[st.current.mode]); };

  const setMode = (m, userDriven) => {
    applyModeState(st.current, m, userDriven);
    syncPlaceholder();
    rerender();
    reprice();
  };
  const userSetMode = (m) => { setMode(m, true); emit("mg-mode-commit", { vmode: m }); };

  // The Model <select>'s own change listener: gate to the model's supported modes/duration. Pure
  // gating (which may switch mode off an unsupported one) + the React paint. prefill()'s own
  // internal gating runs inside applyPrefillState, so it doesn't route through here.
  const applyModelGating = (userDriven) => {
    gateModelState(st.current, userDriven);
    syncPlaceholder();
    rerender();
  };

  // ---- @image/@video/@audio chips in the contenteditable prompt (imperative, verbatim) -------
  const refMap = () => {
    const s = st.current, map = {};
    let n = 0;
    primary().forEach((x) => { if (x && x.media_id) { n++; map["@image" + n] = { thumb: x.thumb, mid: x.media_id, kind: "image" }; } });
    if (s.mode === "r2v") {
      let vn = 0;
      s.vidSlots.forEach((x) => { if (x && x.media_id) { vn++; map["@video" + vn] = { thumb: x.thumb, mid: x.media_id, kind: "video" }; } });
      if (s.audSlot && s.audSlot.media_id) map["@audio1"] = { mid: s.audSlot.media_id, kind: "audio" };
    }
    return map;
  };
  const esc = (s2) => (s2 == null ? "" : String(s2)).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  // The chip DOM algorithm lives in gen/refChips.js (lifted 2026-08-25 -- the QA-caught nesting
  // bug is fixed THERE, once, and unit-testable). These wrappers keep every call site unchanged;
  // the hooks wire chip hover to this component's portaled floating preview.
  const chipHooks = { enter: (mid, el) => showPreview(mid, el), leave: () => hidePreview() };
  const chipify = (final) => refChipify(ceRef.current, refMap(), final, chipHooks);
  const promptText = () => refPromptText(ceRef.current);
  const promptSet = (v) => {
    if (ceRef.current) { ceRef.current.textContent = v || ""; chipify(true); }
    reprice();
    dirty.current = false;
  };
  const emitCommitIfDirty = () => {
    if (!dirty.current) return;
    dirty.current = false;
    emit("mg-prompt-commit", { text: promptText() });
  };
  const onCeInput = useCallback(() => {
    dirty.current = true;
    emit("mg-dirty", {});
    clearTimeout(chipTimer.current);
    chipTimer.current = setTimeout(() => { chipify(false); reprice(); emitCommitIfDirty(); }, 300);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const onCeBlur = useCallback(() => { chipify(true); emitCommitIfDirty(); },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    []);

  // ---- floating ref preview (imperative, verbatim) -------------------------------------------
  const showPreview = (mid, anchor) => {
    const p = previewRef.current, rootEl = rootRef.current;
    if (rootEl) {
      const entry = (rootEl.getAnimations ? rootEl.getAnimations() : [])
        .filter((a) => a.animationName === "mgdDockIn" && a.playState === "running")[0];
      if (entry) {
        entry.finished.then(() => { if (anchor.isConnected && anchor.matches(":hover")) showPreview(mid, anchor); }).catch(() => {});
        return;
      }
    }
    if (!p || !mid || !/^(?:\d+|local_[0-9a-f]{12})$/.test(mid)) return;
    clearTimeout(previewTimer.current);
    p.innerHTML = '<img src="/thumbs/' + esc(mid) + '.jpg" alt="">';
    p.classList.add("open"); p.setAttribute("aria-hidden", "false");
    const r = anchor.getBoundingClientRect(), w = 300, gap = 12;
    let x = r.right + gap;
    if (x + w > window.innerWidth - 8) x = Math.max(8, r.left - w - gap);
    const y = Math.max(8, Math.min(r.top - 10, window.innerHeight - 380));
    p.style.left = x + "px"; p.style.top = y + "px";
    requestAnimationFrame(() => p.classList.add("in"));
  };
  const hidePreview = () => {
    const p = previewRef.current;
    if (!p) return;
    p.classList.remove("in"); p.setAttribute("aria-hidden", "true");
    clearTimeout(previewTimer.current);
    previewTimer.current = setTimeout(() => p.classList.remove("open"), 180);
  };

  // ---- pick-request + audio upload -----------------------------------------------------------
  const requestPick = (bank, i) => {
    emit("mg-pick-request", {
      slot: i, bank, mode: st.current.mode, kind: (bank === "vid" ? "video" : "image"),
      respond: (media_id, thumb, is_nsfw) => {
        if (!media_id) return;
        const item = refItem({ media_id, thumb, is_nsfw });
        if (bank === "vid") { st.current.vidSlots[i] = item; }
        else { const arr = primary(); arr[i] = item; setPrimary(arr); }
        rerender(); reprice();
      },
    });
  };
  const uploadAudio = (file) => {
    if (file.size > 15 * 1024 * 1024) { renderError("Audio file too large — PixAI allows up to 15MB."); return; }
    st.current.audSlot = { uploading: file.name };
    rerender();
    const fd = new FormData(); fd.append("file", file);
    apiUpload("/api/upload", fd)
      .then((d) => {
        if (d.error || !d.media_id) { renderError(d.error || "audio upload failed"); st.current.audSlot = null; rerender(); return; }
        st.current.audSlot = { media_id: String(d.media_id), filename: file.name };
        rerender(); reprice();
      });
  };

  // ---- the ENGINE chip pick (§45 drift) ----------------------------------------------------
  // The inline chip grid replaced the retired model/LoRA flyout, but the PICK transition is
  // unchanged from what the flyout's onClick ran: set the model, gate it (applyModelGating
  // adjusts the shot mode to a supported one and clamps duration to the engine's cap), then
  // re-price. userDriven=true so a dropped shot mode explains itself (DC pickVideoModel note).
  const pickVideoModel = (v) => { st.current.model = v; applyModelGating(true); reprice(); };

  // ---- payload + live cost -------------------------------------------------------------------
  // payload/hasAnyRef/flfMissingStart are the PURE spend-gate predicates (videoDrawerCore.js); the
  // prompt text is the one DOM-sourced field, read from the contenteditable and passed in.
  const payload = () => buildPayload(st.current, promptText());
  const flfMissingStart = () => flfMissingStartOf(st.current);

  /* THE PRICE PROBE. Everything this drawer used to own by hand -- the 250ms debounce, the
     synchronous badge blank, the stale-answer sequence guard, the 25s abort, the settled-verdict
     identity and its short-circuit -- now lives in the shared module (gen/priceProbeCore.js +
     gen/usePriceProbe.js), where the other five cost lines ride the same gate. The long WHY
     comments this block carried moved with the mechanism; what stays here is what is genuinely
     this drawer's: which payload to price, and what "nothing to price" means for a video.

     build() is the whole host half now. The two idle cases are VERDICTS, not gaps -- "nothing to
     price" keeps Go live so doGenerate's own "Pick a source image first" error stays reachable,
     and doGenerate refuses both before any spend. */
  const build = useCallback(() => {
    const p = payload();
    // Mode-dependent idle label is delivered through clear()'s one-shot hint override (the badge
    // has no setHint -- the idle state shows note||hint, and clear(h) sets that h).
    if (!hasAnyRef(p)) {
      return { payload: p, idle: (st.current.mode === "r2v")
        ? "Pick at least one reference to see the cost."
        : "Pick a source image to see the cost." };
    }
    if (flfMissingStart()) {
      return { payload: p, idle: "Pick a Start Frame — the End Frame alone can’t drive First & Last." };
    }
    return { payload: p };
    // Every input it reads is a ref (st.current, the contenteditable), so the first closure
    // stays correct for the life of the drawer -- no dep list can track a ref mutation anyway.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const probe = usePriceProbe({ build, costRef });
  const reprice = probe.refresh;

  // ---- submit -> poll -> result (concurrent; each submission its own line + poll loop) --------
  const pushLine = (line) => {
    const id = ++lineSeq;
    setResults((rs) => rs.concat([{ id, ...line }]));
    return id;
  };
  const updateLine = (id, patch) => setResults((rs) => rs.map((l) => (l.id === id ? { ...l, ...patch } : l)));

  /* Elapsed, in the drawer's own words: "18m", then "1.4h". Used by the tier lines and by the
     6h paused line, which quotes the shared ceiling rather than a second copy of the number. */
  const elapsedLabel = (ms) => (ms < 3600000 ? (Math.round(ms / 60000) + "m") : ((Math.round(ms / 360000) / 10) + "h"));

  const doGenerate = async () => {
    const s = st.current, p = payload();
    if (!hasAnyRef(p)) {
      pushLine({ kind: "error", text: (s.mode === "r2v" ? "Pick at least one reference first." : "Pick a source image first.") });
      return;
    }
    if (flfMissingStart()) {
      pushLine({ kind: "error", text: "Pick a Start Frame first — the End Frame alone can’t drive First & Last." });
      return;
    }
    // PAYLOAD IDENTITY gate (the button is already disabled on it via canGo; this is the click
    // that slips through a stale render). The quote on the badge must have been priced off THIS
    // payload -- a settled FREE for 5s must never carry a 15s submit, and a quality/camera change
    // must not ride a price it never saw. Never a silent drop: say so and re-price.
    if (!probe.canSubmit) {
      // kind:"error", not "status": this is a REFUSAL (submit blocked), and the dock renders
      // only error lines -- as "status" it was silently dropped there (#27).
      pushLine({ kind: "error", text: "Re-checking the cost… try again when the badge settles." });
      // Only kick a NEW re-price when nothing is already in flight for this payload. Calling
      // reprice() unconditionally here bumped the sequence (discarding a quote about to settle)
      // and restarted the debounce, so fast repeated clicks could keep the badge from ever
      // settling (review: refusal-path starvation). If a check is pending, just refuse and let
      // it land. A check is "in flight" when the debounce timer is pending or a fetch is out
      // (unsettled with no key). In both cases the answer for THIS payload is already
      // coming -- don't discard it. Otherwise (settled-but-stale key) re-price.
      const pr = probe.verdict || {};
      const checkInFlight = !!pr.pendingTimer || (!pr.settled && pr.pricedKey == null);
      if (!checkInFlight) reprice();
      return;
    }
    const id = pushLine({ kind: "status", moon: true, text: "Submitting…" });
    setReuseChip(null);   // a new submission goes out -- the recipe is no longer "from" the old run
    st.current.rendering = true;
    rerender();
    const unlock = () => { st.current.rendering = false; rerender(); };

    const startedAt = Date.now();
    let taskId = null;
    let tier = "normal";     // the tracker's last reported tier; "running" lines paint from it
    let lastErr = "";        // whatever the road last said went wrong, for the mg-error detail
    const short = () => String(taskId || "").slice(-6);

    /* The EMIT ADAPTER: submitTask paints through {text, kind, media?} patches, this drawer
       paints result LINES -- so pushLine/updateLine become the adapter. "err" is a red line and
       is remembered (a submit-time rejection never reaches onPhase, so this is where the host's
       mg-error detail comes from); "ok" is a plain line, which is the terminal wording only on
       the no-tracker page (window.Jobs absent) -- on every real page onPhase repaints it as the
       thumbnail result line a line later. */
    const emitLine = (patch) => {
      if (patch.kind === "err") { lastErr = patch.text; updateLine(id, { kind: "error", text: patch.text, moon: false }); return; }
      if (patch.kind === "ok") { updateLine(id, { kind: "plain", text: patch.text, moon: false }); return; }
      updateLine(id, { kind: "status", moon: true, text: patch.text });
    };

    /* The tier lines the drawer used to compute from its own thresholds. The TABLE is gone from
       here (notify/pollCadence.js owns it, and the tracker reports which tier it is in) but the
       WORDING is still the drawer's, and so is the rule behind it: elapsed time alone never ends
       a render in failure -- a slower tier only escalates the message. Only a real
       phase==='failed' renders an error, and the 6h ceiling renders a grey PAUSED line, not a
       red one, because the task may well still be running. */
    const tierLine = (t, elapsed) => (t === "stale"
      ? { kind: "status", moon: true, amber: true, text: "Still going after " + elapsedLabel(elapsed) + " — unusual. Check pixai.art, or keep waiting (task " + short() + ")" }
      : { kind: "status", moon: true, amber: true, text: "Taking longer than expected (" + elapsedLabel(elapsed) + ", task " + short() + ")" });

    /* The host half: the drawer's DOM events, dispatched off the RETAINED node (see liveNode),
       so a phase landing after the drawer unmounts still reaches the Loom's listeners. */
    const onPhase = (phase, d) => {
      const elapsed = Date.now() - startedAt;
      if (phase === "done") {
        updateLine(id, { kind: "result", mediaIds: d.media_ids || [], cost: d.paid_credit });
        emit("mg-result", { media_ids: d.media_ids || [], is_video: !!d.is_video, duration: d.duration, paid_credit: d.paid_credit });
      } else if (phase === "failed") {
        // The drawer's own friendlyGenErr, not the road's: this string is what the Loom prints on
        // the shot card, and it is pinned in parity with loom-mutations.js's copy so a PixAI
        // content-filter refusal reads identically on both surfaces (mg-generate-drawer-parity).
        const msg = friendlyGenErr(d.error || ("task " + (d.status || "failed")));
        updateLine(id, { kind: "error", text: msg, moon: false });
        emit("mg-error", { error: msg });
      } else if (phase === "stalled") {
        updateLine(id, {
          kind: "plain",
          text: "Paused auto-checking after " + elapsedLabel(CEILING_MS) + " with no result — check pixai.art, or reopen this shot to check again (task " + short() + ")",
        });
        emit("mg-paused", { task_id: taskId });
      } else if (phase === "slow" || phase === "stale") {
        tier = phase;
        updateLine(id, tierLine(phase, elapsed));
        emit("mg-slow", { tier: phase, elapsed, task_id: taskId });
      } else {   // running -- every poll; the tier decides whether it is amber
        updateLine(id, tier === "normal"
          ? { kind: "status", moon: true, amber: false, text: "Rendering under the eclipse… (task " + short() + ")" }
          : tierLine(tier, elapsed));
      }
    };

    const tid = await submitTask("/api/loom/generate", p, { label: "Rendered", emit: emitLine, onPhase });
    unlock();   // the server answered (accepted or rejected) -- free the button for the NEXT submission
    // A submit-time failure (server rejection, no task_id, or no answer at all) must emit
    // mg-error, exactly as the vanilla's _renderErrorInto did -- otherwise the Loom's
    // onVideoError never runs and a rejected shot shows no error badge on the board when the
    // Video tab is collapsed. The road returns null for every one of those cases and has
    // already painted the line; this is the host half of the same event. (No credits are spent
    // on a failed submit, so this is a status regression, not a spend one.)
    if (!tid) { emit("mg-error", { error: lastErr || "submit failed" }); return; }
    taskId = tid;
    emit("mg-submit", { task_id: tid, payload: p });
    // The submit just DEBITED tickets, so the settled verdict is stale even though the
    // payload is byte-identical -- identity-by-payload cannot see a balance change caused
    // by the drawer's own submit. Without this, a second click on the unchanged form passed
    // canSubmit on the same key and submitted under a FREE badge for a clip the server now
    // found SHORT and charged in full (review: post-submit stale FREE, the exact #15 shape).
    // FORCED: the payload is byte-identical to the settled key, so an unforced re-price
    // would short-circuit as "nothing changed" -- but the balance did.
    reprice({ force: true });
  };

  const renderError = (msg) => { pushLine({ kind: "error", text: msg }); emit("mg-error", { error: msg }); };

  // ---- public host API (the imperative handle) -----------------------------------------------
  // setRefs/prefill delegate their whole spend-critical state transition to the pure layer, then
  // do the React-only parts: sync the ce placeholder to the (possibly mode-switched) drawer, set
  // the prompt (a contenteditable side effect the pure layer returns rather than does), repaint,
  // reprice.
  const setRefs = (refs) => {
    applySetRefsState(st.current, refs);
    syncPlaceholder();
    rerender(); reprice();
  };
  const prefill = (o) => {
    const r = applyPrefillState(st.current, o);
    syncPlaceholder();
    if (r.setPrompt != null) promptSet(r.setPrompt);
    rerender(); reprice();
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
  // Dock ★ Snippets -> this prompt: append a snippet after the existing text (the dock's own
  // comma rule for its image prompt), through promptSet so @image chips re-chipify and the
  // usual (short-circuiting) re-price runs. Prompt text never prices, so no verdict moves.
  const insertText = (t) => {
    const cur = promptText();
    promptSet((cur ? cur.replace(/,\s*$/, "") + ", " : "") + String(t || ""));
  };
  // The video ↺-from chip's setter, exposed to the dock's prefillVideoFromRun. Null clears it.
  const setReuse = (info) => setReuseChip(info || null);

  // The vanilla was a CUSTOM ELEMENT: hosts held the DOM node itself and called node.prefill(),
  // node.setRefs(), read node.mode, and node.addEventListener('mg-*'). To stay a drop-in, the ref
  // resolves to the ROOT DOM NODE with the public methods hung directly on it (and a `mode`
  // getter) -- so bindGenDrawer's el.addEventListener + el.prefill, and every createElement call
  // site, keep working against a real node instead of a plain handle object. The methods close
  // over refs + stable setters only (never render-scoped state), so first-mount capture is safe.
  useImperativeHandle(ref, () => {
    const node = rootRef.current;
    if (node && !node._mgWired) {
      node._mgWired = true;
      node.prefill = prefill;
      node.setRefs = setRefs;
      node.flushPromptEdit = flushPromptEdit;
      node.setBusy = setBusy;
      node.payload = payload;
      node.insertText = insertText;
      node.promptText = promptText;
      node.setReuse = setReuse;
      Object.defineProperty(node, "mode", { configurable: true, get: () => st.current.mode });
    }
    return node;
  }, []);

  // ---- render --------------------------------------------------------------------------------
  const s = st.current;
  const allowedModes = MODEL_VMODES[s.model] || ["i2v", "flf", "r2v"];
  const maxDur = MODEL_MAXDUR[s.model] || 10;
  const chosenModel = MODELS.find((m) => m.value === s.model);
  const isR2v = s.mode === "r2v";
  // Go is DISABLED (not awaited) until the probe's settled verdict is for the payload this form
  // would submit right now -- an await here would add PixAI RTTs after the click and land after
  // the rendering latch, a double-submit window.
  const canGo = !s.hostBusy && !s.rendering && probe.canSubmit;
  // v4.0 full is ~2.5x Lite (14k/s -> 210k for a 15s clip). The badge shows `warn` only in the
  // `paid` state -- which is only ever reached by a price settled for THIS model -- so deriving
  // it from the form is exactly as truthful as writing it at fire time was, with no second state
  // to keep in step. The red (not amber) colour is re-asserted by gen-drawer.css's own override.
  const warn = s.model === "v4.0" ? "V4.0 full — ~2.5× Lite" : "";

  // ---- SHOT MODE + the ref/frame banks (DC 1346-1376, getters 2842-2895) ----------------
  // ALL three segments always render; one the engine lacks is dimmed (opacity .35, not-allowed,
  // title '<label> needs the V4.0 pair'), never removed -- the DC's shotModes.
  const shotModes = ["i2v", "flf", "r2v"].map((v) => {
    const ok = allowedModes.indexOf(v) >= 0;
    return { v, ok, label: SHOT_LABEL[v], title: ok ? SHOT_LABEL[v] : SHOT_LABEL[v] + " needs the V4.0 pair" };
  });

  // Removing a pick is the click on the filled slot itself (DC slot.onClick filters it out; no
  // separate × control). Splices the r2v banks (re-seeding the [null] the state layer keeps),
  // nulls an i2v/flf frame in place. Every removal re-prices -- the pick was a priced input.
  const removeSlot = (bank, i) => {
    const cur = st.current;
    if (bank === "vid") { cur.vidSlots.splice(i, 1); if (!cur.vidSlots.length) cur.vidSlots = [null]; }
    else if (cur.mode === "r2v") { let arr = cur.imgSlots; arr.splice(i, 1); if (!arr.length) arr = [null]; cur.imgSlots = arr; }
    else cur.slots[i] = null;
    rerender(); reprice();
  };
  // One reference / frame slot: DC slotBox (54px, radius 9, dashed while empty, solid once
  // filled), the empty caption, and the '@imageN' / '@videoN' badge Multi-Reference alone carries.
  const slotBox = ({ key, item, bank, index, caption, badge, title }) => (
    <div key={key} className={"mgd-slot" + (item ? " filled" : "")} title={title}
      data-nsfw={item && item.is_nsfw ? "1" : undefined}
      onClick={() => (item ? removeSlot(bank, index) : requestPick(bank, index))}>
      {item ? <img src={item.thumb} alt="" /> : <div className="mgd-slotcap">{caption}</div>}
      {item && badge ? <div className="mgd-slot-tag">{badge}</div> : null}
    </div>
  );
  // The banks the current shot mode shows (DC videoBanks): Multi-Reference = Image references
  // (up to 6) + Video references (up to 3), each the filled picks plus ONE trailing empty slot
  // while under the cap; otherwise Start frame (+ End frame, optional, on First & Last).
  const banks = [];
  if (isR2v) {
    const iv = bankView(s.imgSlots, 6);
    const imgs = iv.filled.map(({ item, index }, n) => slotBox({ key: "img" + index, item, bank: "primary", index,
      badge: "@image" + (n + 1), title: "Image reference " + (n + 1) }));
    if (iv.nextIndex >= 0) imgs.push(slotBox({ key: "img+", item: null, bank: "primary", index: iv.nextIndex, caption: "+ image", title: "Pick from your gallery" }));
    banks.push({ label: MODE_LBL.r2v, note: "up to 6", slots: imgs });
    const vv = bankView(s.vidSlots, 3);
    const vids = vv.filled.map(({ item, index }, n) => slotBox({ key: "vid" + index, item, bank: "vid", index,
      badge: "@video" + (n + 1), title: "Video reference " + (n + 1) }));
    if (vv.nextIndex >= 0) vids.push(slotBox({ key: "vid+", item: null, bank: "vid", index: vv.nextIndex, caption: "+ video", title: "Pick from your gallery" }));
    banks.push({ label: "Video references", note: "up to 3", slots: vids });
  } else {
    banks.push({ label: MODE_LBL[s.mode], note: "", slots: [slotBox({ key: "start", item: s.slots[0], bank: "primary", index: 0,
      caption: "pick", title: s.slots[0] ? "Start frame" : "Pick from your gallery" })] });
    if (s.mode === "flf") banks.push({ label: "End frame", note: "optional", slots: [slotBox({ key: "end", item: s.slots[1], bank: "primary", index: 1,
      caption: "pick", title: s.slots[1] ? "End frame" : "Pick from your gallery" })] });
  }

  // ---- the pieces that live in the dock's footer in dock mode (inline otherwise) ----------
  // ONE definition each; only WHERE they mount differs. The prompt is the same contenteditable
  // (ceRef, chips, MODE_PH placeholder), the negative the same field, the badge the same
  // costRef instance, the button the same canGo/doGenerate. Dock-mode classes take the DC's
  // composer/footer skin (dock.css); the label is the DC's genLabel for this tab (3611).
  // The 'Rendering…' label swap is NOT drawn (the DC's generate() never relabels) -- kept
  // deliberately: it is the visible half of the submit lock (rendering latch, unlocked on the
  // server's answer), the double-submit guard on a ~210k-credit action.
  const promptField = (
    <div ref={ceRef} className={"mgd-ce" + (inDock ? " mgdock-prompt-ce" : "")} contentEditable suppressContentEditableWarning
      data-placeholder={MODE_PH[s.mode]} onInput={onCeInput} onBlur={onCeBlur} />
  );
  const negativeField = (
    <textarea className={inDock ? "mgdock-neg" : "mgd-neg"} rows={inDock ? 1 : undefined}
      placeholder="blurry, extra fingers, watermark" value={s.negative}
      onChange={(e) => { st.current.negative = e.target.value; rerender(); reprice(); }} />
  );
  const costLine = (
    <CostBadge ref={costRef} className="mgd-cost" warn={warn} cardLabel="a video card"
      hint="Pick a source image to see the cost."
      stack={inDock || undefined} balance={inDock ? dock.balance : undefined} />
  );
  const goButton = inDock ? (
    <button type="button" className={"mgdock-gen" + (canGo ? "" : " off")} disabled={!canGo} onClick={doGenerate}
      title={s.rendering ? "Rendering…" : canGo ? "Submit — this spends credits or a card"
        : "Waiting for the cost to settle for these settings"}>
      <span>{s.rendering ? "Rendering…" : "✦ Generate video"}</span>
    </button>
  ) : (
    <button type="button" className="mgd-go" disabled={!canGo} onClick={doGenerate}>
      {s.rendering ? "Rendering…" : "Generate video"}
    </button>
  );
  // The composer's top row on the Video tab (DC 1557-1562: pip · summary): the engine as the
  // pip, shot mode · duration as the summary. Read-only here -- the ENGINE controls stay in
  // the drawer body.
  const topRow = inDock ? (
    <>
      <span className="mgdock-modelchip static" title="Video engine — set in the video settings">
        <span className="mgdock-chipph" />
        <span>{chosenModel ? chosenModel.label : s.model}</span>
      </span>
      <span className="mgdock-frames">{SHOT_LABEL[s.mode] || s.mode} · {s.duration}s</span>
      {reuse && (
        <button type="button" className={"mgdock-reusefrom" + (reuse.partial ? " warn" : "")}
          onClick={() => setReuseChip(null)}
          title={reuse.partial
            ? "PARTIAL recipe from " + reuse.tag + ": " + reuse.partial + " — click to clear"
            : "Video recipe prefilled from run " + reuse.tag + " — click to clear"}>
          ↺ from {reuse.tag}{reuse.partial ? " ⚠" : ""} <span>&times;</span>
        </button>
      )}
    </>
  ) : null;

  return (
    <div ref={setRoot} className={"gen-drawer" + (inDock ? " mgd-dock" : "") + (inDock && dock.expanded === false ? " mgd-collapsed" : "") + (className ? " " + className : "")} style={style} data-loom-ctx={loomCtx ? "" : undefined}>
      {/* The DC's expanded Video settings: three slabs (DC 1209-1210 grid; slab(i) 2876),
          rebalanced by §45 -- SHOT MODE + banks + CAMERA · ENGINE chip grid (alone) ·
          MODE & CHANNEL + switches + DURATION.
          In dock mode they show only while the dock's ▲ settings are expanded (DC 1209 wraps
          the whole grid in `expanded`); `dock.expanded === false` hides the wrap with CSS --
          the drawer itself stays mounted (poll timers, portals, the prompt's imperative
          content all survive), and the result lines below keep showing. */}
      <div className="mgd-slabwrap">
      <div className="mgd-slabs">
        <div className="mgd-slab" style={{ animationDelay: "0ms" }}>
          <div className="mgd-sec">SHOT MODE</div>
          <div className="mgd-seg" role="tablist">
            {shotModes.map((sm) => (
              <button key={sm.v} type="button" role="tab" aria-selected={s.mode === sm.v} aria-disabled={!sm.ok}
                className={(s.mode === sm.v ? "on" : "") + (sm.ok ? "" : " off")} title={sm.title}
                onClick={() => { if (sm.ok) userSetMode(sm.v); }}>{sm.label}</button>
            ))}
          </div>
          {s.modeNote ? <div className="mgd-modenote">{s.modeNote}</div> : null}
          {banks.map((b) => (
            <div key={b.label} className="mgd-bank">
              <div className="mgd-bankhd">
                <div className="mgd-banklbl">{b.label}</div>
                {b.note ? <div className="mgd-banknote">{b.note}</div> : null}
              </div>
              <div className="mgd-slots">{b.slots}</div>
            </div>
          ))}
          {/* Audio reference (Multi-Reference only). NOT in the DC's videoBanks -- kept as a real
              PixAI capability this drawer already ships end to end (owner-locked "Video Tab — Full
              Parity Mockup v1", CHANGELOG 2026-07-18: 6 image + 3 video + 1 audio ref; uploads
              direct to /api/upload since audio is not catalogued; audio_refs ride the payload and
              the Loom's shot prefill carries audio_ref). Drawn as one more DC bank/slot. Owner to
              rule; drop this block + the audSlot plumbing together if ruled out. */}
          {isR2v ? (
            <div className="mgd-bank">
              <div className="mgd-bankhd">
                <div className="mgd-banklbl">Audio reference</div>
                <div className="mgd-banknote">WAV ≤15MB</div>
              </div>
              <div className="mgd-slots">
                {s.audSlot && s.audSlot.uploading ? (
                  <div className="mgd-slot" title={"Uploading " + s.audSlot.uploading}><div className="mgd-slotcap">uploading…</div></div>
                ) : s.audSlot ? (
                  <div className="mgd-slot filled audio" title={"Audio reference — " + s.audSlot.filename}
                    onClick={() => { st.current.audSlot = null; rerender(); reprice(); }}>
                    <div className="mgd-slotcap">♪</div>
                    <div className="mgd-slot-tag">@audio1</div>
                  </div>
                ) : (
                  <div className="mgd-slot" title="Upload a WAV (≤15MB)" onClick={() => audFileRef.current && audFileRef.current.click()}>
                    <div className="mgd-slotcap">+ audio</div>
                  </div>
                )}
              </div>
            </div>
          ) : null}
          <input ref={audFileRef} type="file" className="mgd-audiofile" accept="audio/*" style={{ display: "none" }}
            onChange={(e) => { const f = e.target.files[0]; e.target.value = ""; if (f) uploadAudio(f); }} />
          {/* CAMERA (§45 drift): moved to the foot of the left slab, under SHOT MODE + the ref
              banks (was in the ENGINE slab) -- DC 1419-1430. In Multi-Reference the block keeps
              its space but goes invisible (cameraVis: visibility:hidden) -- the payload already
              drops camera_movement for r2v. Camera rides the priced payload (i2vPro.cameraMovement),
              so each change re-prices like every other priced field. */}
          <div className={"mgd-cam-wrap" + (isR2v ? " hid" : "")} aria-hidden={isR2v || undefined}>
            <div className="mgd-sec">CAMERA</div>
            <select className="mgd-sel mgd-cam" value={s.camera} tabIndex={isR2v ? -1 : undefined} onChange={(e) => { st.current.camera = e.target.value; rerender(); reprice(); }}>
              {CAMERA_OPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
        </div>

        {/* ENGINE (§45 drift): the retired model/LoRA flyout is replaced by an inline 2-column
            chip grid of the 7 engines (DC 1433-1451; videoChips/videoModelMeta 2987-3001).
            Header = ENGINE label + the selected engine's label (single line, ellipsis). Each chip
            is a radio dot + the wrapping engine name; picking one runs pickVideoModel -> the same
            applyModelGating(true) + re-price the flyout ran (adjusts shot mode + clamps duration
            to the engine's caps). The meta row beneath is the selected engine's
            'Ns max · card/no card' line plus its capability chips. DURATION + CAMERA left this
            slab in the rebalance (§45): CAMERA under SHOT MODE, DURATION under MODE & CHANNEL. */}
        <div className="mgd-slab" style={{ animationDelay: "60ms" }}>
          <div className="mgd-enghd">
            <div className="mgd-sec">ENGINE</div>
            <div className="mgd-engcur">{chosenModel ? chosenModel.label : s.model}</div>
          </div>
          <div className="mgd-enggrid" role="radiogroup" aria-label="Video engine">
            {MODELS.map((m) => {
              const sel = m.value === s.model;
              const modes = (MODEL_VMODES[m.value] || ["i2v", "flf", "r2v"]).map((x) => SHOT_LABEL[x]).join(" / ");
              return (
                <div key={m.value} role="radio" aria-checked={sel}
                  className={"mgd-engchip" + (sel ? " sel" : "")}
                  title={m.label + " — " + modes + " · " + (MODEL_MAXDUR[m.value] || 10) + "s max · " + (MODEL_CARD[m.value] === false ? "no card" : "card")}
                  onClick={() => pickVideoModel(m.value)}>
                  <span className="mgd-engdot" />
                  <span className="mgd-englabel">{m.label}</span>
                </div>
              );
            })}
          </div>
          <div className="mgd-engmeta">
            <span>{modelMeta(s.model)}</span>
            {modelCaps(s.model).map(([t, kind]) => <span key={t} className={"mgd-cap" + (kind ? " " + kind : "")}>{t}</span>)}
          </div>
        </div>

        {/* MODE & CHANNEL (DC 1416-1441): Basic|Professional seg -> Normal|Enhanced seg ->
            plain caption -> the two pill switches -> (audio on) the bare language select. */}
        <div className="mgd-slab" style={{ animationDelay: "120ms" }}>
          <div className="mgd-sec">MODE &amp; CHANNEL</div>
          <div className="mgd-seg mgd-quality-wrap" role="radiogroup" aria-label="Mode">
            {[["basic", "Basic"], ["professional", "Professional"]].map(([v, l]) => (
              <button key={v} type="button" role="radio" aria-checked={s.quality === v} className={"mgd-quality" + (s.quality === v ? " on" : "")} onClick={() => { if (st.current.quality === v) return; st.current.quality = v; rerender(); reprice(); }}>{l}</button>
            ))}
          </div>
          <div className="mgd-seg" role="radiogroup" aria-label="Channel">
            {[["normal", "Normal"], ["enhanced", "Enhanced"]].map(([v, l]) => (
              <button key={v} type="button" role="radio" aria-checked={s.channel === v} className={"mgd-channel" + (s.channel === v ? " on" : "")} onClick={() => { if (st.current.channel === v) return; st.current.channel = v; rerender(); reprice(); }}>{l}</button>
            ))}
          </div>
          <div className="mgd-chancap">{CHANNEL_CAP[s.channel]}</div>
          <label className="mgd-sw" title="Spoken lines in the prompt become voiceover">
            <input type="checkbox" className="mgd-audio" checked={s.audioGen}
              onChange={(e) => { st.current.audioGen = e.target.checked; rerender(); reprice(); emit("mg-audio-commit", { audioGen: e.target.checked, audioLanguage: st.current.audioLanguage }); }} />
            <span className="mgd-swtrack"><i /></span>
            <span className="mgd-swlab">Generate audio</span>
          </label>
          <label className="mgd-sw" title="Off by default — the opposite of image gen">
            <input type="checkbox" className="mgd-helper" checked={s.videoHelper}
              onChange={(e) => { st.current.videoHelper = e.target.checked; rerender(); reprice(); }} />
            <span className="mgd-swtrack"><i /></span>
            <span className="mgd-swlab">Video prompt helper</span>
          </label>
          {s.audioGen ? (
            <select className="mgd-sel mgd-lang" value={s.audioLanguage} aria-label="Audio language"
              onChange={(e) => { st.current.audioLanguage = e.target.value; rerender(); reprice(); emit("mg-audio-commit", { audioGen: st.current.audioGen, audioLanguage: e.target.value }); }}>
              {AUDIO_LANGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          ) : null}
          {/* DURATION (§45 drift): moved to the foot of the right slab, under MODE & CHANNEL
              (was in the ENGINE slab) -- DC 1479-1487. Label + live 'Ns' readout, then four
              segmented stops. A stop above the REAL engine cap (MODEL_MAXDUR -- the spend gate
              applyModelGating clamps to) stays visible but dimmed, not-allowed, titled, and its
              click is ignored -- never removed. */}
          <div className="mgd-durhd">
            <div className="mgd-sec">DURATION</div>
            <div className="mgd-durval">{s.duration}s</div>
          </div>
          <div className="mgd-stops mgd-dur" role="radiogroup" aria-label="Duration">
            {[5, 6, 10, 15].map((d) => {
              const ok = d <= maxDur;
              return (
                <button key={d} type="button" role="radio" aria-checked={d === s.duration} aria-disabled={!ok}
                  className={"mgd-stop" + (d === s.duration ? " on" : "") + (ok ? "" : " off")}
                  title={d + " seconds" + (ok ? "" : " — not on this engine")}
                  onClick={() => { if (!ok || d === st.current.duration) return; st.current.duration = d; rerender(); reprice(); emit("mg-duration-commit", { duration: d }); }}>{d}</button>
              );
            })}
          </div>
        </div>
      </div>
      </div>

      {/* contenteditable prompt -- imperative content, React never touches its children.
          Dock mode: portaled into the dock composer's prompt slot (see promptField). */}
      {inDock ? (dock.promptEl ? createPortal(promptField, dock.promptEl) : null) : promptField}

      {inDock ? (dock.negativeEl ? createPortal(negativeField, dock.negativeEl) : null) : (
        <>
          <div className="mgd-lbl">Negative prompt</div>
          {negativeField}
        </>
      )}
      {inDock && dock.topEl ? createPortal(topRow, dock.topEl) : null}

      {/* cost + Generate: the dock footer's right column in dock mode (one badge, one button,
          one gate -- see the DOCK MODE note above); inline for every other host. */}
      {inDock ? (dock.goEl ? createPortal(<>{costLine}{goButton}</>, dock.goEl) : null) : (
        <>
          {costLine}
          {goButton}
        </>
      )}

      {/* Result / status lines. IN THE DOCK (the gallery's Generate dock) the redesign routes runs
          into the RUNS reel and completed videos into History -- mg-submit/mg-result feed the reel,
          the History strip and the banner -- so the drawer's own inline PROGRESS and result-media are
          redundant there and are suppressed; only its refusals / submit-time errors ('Pick a source
          image first.', a rejected submit), which never reach the reel, still show (owner 2026-08-18).
          The Loom and mobile Video mode render inline WITHOUT a reel, so they keep the full lines.
          Every mg-* event is emitted regardless above -- this only gates the inline RENDER. */}
      {(() => {
        const shown = inDock ? results.filter((l) => l.kind === "error") : results;
        return (
          <div className={"mgd-result" + (shown.length ? " has" : "")}>
            {shown.map((l) => (
              <div key={l.id} className="mgd-result-line">
                {l.kind === "result" ? (
                  <>
                    <div style={{ color: "var(--emerald,#4fc99a)", fontSize: 12, marginBottom: 6 }}>
                      ✓ Rendered — {l.cost === 0 ? "free (card used)" : (Number(l.cost || 0).toLocaleString() + " credits")}. Added to your gallery.
                    </div>
                    {(l.mediaIds || []).map((mid) => (
                      <a key={mid} href={"/?image=" + encodeURIComponent(mid)}
                        onClick={(e) => {
                          if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
                          e.preventDefault();
                          document.dispatchEvent(new CustomEvent("mg-open-details", { bubbles: true, composed: true, detail: { mid } }));
                        }}>
                        <img src={"/thumbs/" + encodeURIComponent(mid) + ".jpg"} alt="result" loading="lazy" />
                      </a>
                    ))}
                  </>
                ) : l.kind === "error" ? (
                  <span style={{ color: "var(--red,#f38ba8)", fontSize: 12 }}>{l.text}</span>
                ) : l.kind === "plain" ? (
                  <span style={{ color: "var(--subtext,#9a93ab)", fontSize: 12 }}>{l.text}</span>
                ) : (
                  <span style={{ color: l.amber ? "var(--amber,#f9d38c)" : "var(--subtext,#9a93ab)", fontSize: 12 }}>
                    {l.moon ? <span className="mgd-moon" /> : null}{l.text}
                  </span>
                )}
              </div>
            ))}
          </div>
        );
      })()}

      {/* Portaled to <body>: the drawer (and in dock mode, the dock) sits under ancestors with
          transforms/backdrop-filters, which hijack position:fixed and re-anchor it to themselves --
          the QA-caught "preview pops all over the place / off-screen". On body, fixed means the
          viewport again, in both drawer and dock modes. */}
      {createPortal(<div ref={previewRef} className="mgd-preview" aria-hidden="true" />, document.body)}
    </div>
  );
});

export default VideoDrawer;
