import React, {
  forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState,
} from "react";
import CostBadge from "./CostBadge.jsx";
import {
  MODELS, MODEL_VMODES, MODEL_MAXDUR, MODE_LBL, MODE_PH, CHANNEL_CAP,
  friendlyGenErr, refItem, primaryBank, setPrimaryBank, buildPayload, hasAnyRef,
  applyMode as applyModeState,
  applyModelGating as gateModelState,
  applySetRefs as applySetRefsState,
  applyPrefill as applyPrefillState,
  flfMissingStart as flfMissingStartOf,
} from "../gen/videoDrawerCore.js";
import "../styles/gen-drawer.css";

/* VideoDrawer -- the React port of static/mg-generate-drawer.js's <mg-generate-drawer> (no-vanilla
   campaign, component 7, the last one). The shared VIDEO generation form: 3 modes (i2v / first-
   last-frame / reference-to-video), 6 image + 3 video + 1 audio ref banks, the 7-model roster
   with capability gating, negative prompt, Channel, live cost (embedded React CostBadge), submit,
   and its own concurrent poll loops. Mounted by the gallery's Generate dock (Video tab), mobile's
   Video mode, and the Loom's video drawer.

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
   - Concurrent result lines are React state; each submission's poll loop is an imperative
     setTimeout chain tracked in a ref and swept on unmount -- but a host defers unmount 360ms
     (the .mgd-closing exit), and the poll checks a "connected" ref, so an in-flight ~210k-credit
     video render is never orphaned by a view closing.

   Only prop: `loomCtx` (hide the drawer's own Camera/quality -- the Loom owns equivalents). All
   host communication is through the ref's methods and the bubbling DOM events above. */

let lineSeq = 0;

const VideoDrawer = forwardRef(function VideoDrawer(props, ref) {
  // `style`/`className` pass through to the root so a host can position/hide the node exactly as
  // it did the custom element (the Loom mounts it once and toggles style.display by tab).
  const { loomCtx, style, className } = props;

  // ---- mutable form state (the vanilla's this._* fields), one ref + a forceUpdate ----------
  const st = useRef({
    mode: "i2v",
    slots: [null],       // i2v/flf primary bank ([0]=start, [1]=end for flf)
    imgSlots: [null],    // r2v image bank (max 6)
    vidSlots: [],        // r2v video bank (max 3)
    audSlot: null,       // {media_id, filename} | null
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
    hostBusy: false,
  });
  const [, force] = useState(0);
  const rerender = useCallback(() => force((n) => n + 1), []);

  const [results, setResults] = useState([]);   // concurrent result lines
  const [warn, setWarnState] = useState("");     // CostBadge caution clause (paid-state only)
  const setWarn = useCallback((w) => setWarnState(w), []);
  const ceRef = useRef(null);                    // the contenteditable prompt
  const previewRef = useRef(null);
  const audFileRef = useRef(null);
  const costRef = useRef(null);
  const rootRef = useRef(null);

  const costSeq = useRef(0);
  const costTimer = useRef(0);
  const chipTimer = useRef(0);
  const previewTimer = useRef(0);
  const dirty = useRef(false);
  const pollTimers = useRef([]);
  const connected = useRef(true);

  // The vanilla was event-based: it dispatched BUBBLING, composed CustomEvents from its own node,
  // and its hosts (the gallery's document-level listeners in App.jsx, the Loom's bindGenDrawer via
  // addEventListener) caught them. Preserved verbatim -- this stays a drop-in: emit() dispatches
  // the same events off the root node, so every existing listener keeps working with no rewrite.
  const emit = useCallback((name, detail) => {
    const n = rootRef.current;
    if (n) n.dispatchEvent(new CustomEvent(name, { bubbles: true, composed: true, detail: detail || {} }));
  }, []);
  useEffect(() => () => {
    connected.current = false;
    clearTimeout(costTimer.current); clearTimeout(chipTimer.current); clearTimeout(previewTimer.current);
    pollTimers.current.forEach((t) => clearTimeout(t));
    pollTimers.current = [];
  }, []);

  // ---- the primary (image) slot bank ---------------------------------------------------------
  // Thin wrappers over the PURE state layer in videoDrawerCore.js (which the loom node-tests hit
  // directly). The React side owns only the paint (ce placeholder, rerender) + pricing (debCost).
  const primary = () => primaryBank(st.current);
  const setPrimary = (arr) => setPrimaryBank(st.current, arr);
  const syncPlaceholder = () => { if (ceRef.current) ceRef.current.setAttribute("data-placeholder", MODE_PH[st.current.mode]); };

  const setMode = (m, userDriven) => {
    applyModeState(st.current, m, userDriven);
    syncPlaceholder();
    rerender();
    debCost();
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
  const makeChip = (tag, info) => {
    const c = document.createElement("span");
    c.className = "mgd-chip"; c.contentEditable = "false"; c.setAttribute("data-ref", tag);
    const lead = info && info.thumb ? '<img src="' + esc(info.thumb) + '" alt="">' : (info && info.kind === "audio" ? "♪ " : "");
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
    while ((tn = walker.nextNode())) nodes.push(tn);
    const re = /@(?:image|video|audio)\d+/g;
    nodes.forEach((node) => {
      const t = node.nodeValue, found = [];
      let m;
      re.lastIndex = 0;
      while ((m = re.exec(t)) !== null) {
        if (!map[m[0]]) continue;
        if (!final && m.index + m[0].length === t.length) continue;   // still typing at the end
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
        r.setStart(tail, tail.length); r.collapse(true);
        sel.removeAllRanges(); sel.addRange(r);
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
    if (ceRef.current) { ceRef.current.textContent = v || ""; chipify(true); }
    debCost();
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
    chipTimer.current = setTimeout(() => { chipify(false); debCost(); emitCommitIfDirty(); }, 300);
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
        rerender(); debCost();
      },
    });
  };
  const uploadAudio = (file) => {
    if (file.size > 15 * 1024 * 1024) { renderError("Audio file too large — PixAI allows up to 15MB."); return; }
    st.current.audSlot = { uploading: file.name };
    rerender();
    const fd = new FormData(); fd.append("file", file);
    fetch("/api/upload", { method: "POST", body: fd })
      .then((r) => r.json())
      .then((d) => {
        if (d.error || !d.media_id) { renderError(d.error || "audio upload failed"); st.current.audSlot = null; rerender(); return; }
        st.current.audSlot = { media_id: String(d.media_id), filename: file.name };
        rerender(); debCost();
      })
      .catch(() => { renderError("audio upload failed (network)"); st.current.audSlot = null; rerender(); });
  };

  // ---- payload + live cost -------------------------------------------------------------------
  // payload/hasAnyRef/flfMissingStart are the PURE spend-gate predicates (videoDrawerCore.js); the
  // prompt text is the one DOM-sourced field, read from the contenteditable and passed in.
  const payload = () => buildPayload(st.current, promptText());
  const flfMissingStart = () => flfMissingStartOf(st.current);

  const debCost = () => {
    clearTimeout(costTimer.current);
    costTimer.current = setTimeout(costNow, 250);
  };
  // The HOST half of CostBadge's contract: owns the /api/price call, the 250ms debounce, and the
  // _costSeq stale-response guard; the badge owns every state's wording/colour.
  const costNow = () => {
    const cost = costRef.current;
    if (!cost) return;
    const s = st.current, p = payload();
    // Mode-dependent idle label is delivered through clear()'s one-shot hint override (the badge
    // has no setHint -- the idle state shows note||hint, and clear(h) sets that h).
    const idleHint = (s.mode === "r2v") ? "Pick at least one reference to see the cost." : "Pick a source image to see the cost.";
    if (!hasAnyRef(p)) { setWarn(""); cost.clear(idleHint); return; }
    if (flfMissingStart()) { setWarn(""); cost.clear("Pick a Start Frame — the End Frame alone can’t drive First & Last."); return; }
    // v4.0 full is ~2.5x Lite (14k/s -> 210k for a 15s clip). The badge shows `warn` only in the
    // `paid` state; the red (not amber) colour is re-asserted by gen-drawer.css's own override.
    setWarn(p.video_model === "v4.0" ? "V4.0 full — ~2.5× Lite" : "");
    cost.setChecking();
    const mine = ++costSeq.current;
    fetch("/api/price", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(p) })
      .then((r) => r.json())
      .then((d) => { if (mine === costSeq.current && costRef.current) costRef.current.setPrice(d); })
      .catch(() => { if (mine === costSeq.current && costRef.current) costRef.current.setPrice(null); });
  };

  // ---- submit -> poll -> result (concurrent; each submission its own line + poll loop) --------
  const pushLine = (line) => {
    const id = ++lineSeq;
    setResults((rs) => rs.concat([{ id, ...line }]));
    return id;
  };
  const updateLine = (id, patch) => setResults((rs) => rs.map((l) => (l.id === id ? { ...l, ...patch } : l)));

  const doGenerate = () => {
    const s = st.current, p = payload();
    if (!hasAnyRef(p)) {
      pushLine({ kind: "error", text: (s.mode === "r2v" ? "Pick at least one reference first." : "Pick a source image first.") });
      return;
    }
    if (flfMissingStart()) {
      pushLine({ kind: "error", text: "Pick a Start Frame first — the End Frame alone can’t drive First & Last." });
      return;
    }
    const id = pushLine({ kind: "status", moon: true, text: "Submitting…" });
    st.current.rendering = true;
    rerender();
    const unlock = () => { st.current.rendering = false; rerender(); };
    fetch("/api/loom/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(p) })
      .then((r) => r.json())
      .then((d) => {
        unlock();   // the server answered -- free the button for the NEXT submission
        if (d.error || !d.task_id) { updateLine(id, { kind: "error", text: friendlyGenErr(d.error || "submit failed"), moon: false }); return; }
        emit("mg-submit", { task_id: d.task_id, payload: p });
        updateLine(id, { kind: "status", moon: true, text: "Queued — running…" });
        poll(d.task_id, id);
      })
      .catch(() => { unlock(); updateLine(id, { kind: "error", text: "network error", moon: false }); });
  };

  // Three thresholds mirror the Loom's own pollShot tiers (POLL_SLOW_AT_MS/STALE_AT/CEILING) --
  // KEEP IN SYNC. Elapsed time alone never ends a render in failure (softened 2026-07-18): it only
  // slows the cadence + escalates the message; only a real d.phase==='failed' renders an error. At
  // the 6h ceiling this session stops scheduling (protects against polling a wedged task forever)
  // but leaves the host's pendingTaskId untouched -- a reload gets a fresh budget.
  const poll = (taskId, lineId) => {
    const startedAt = Date.now();
    const SLOW_AT = 20 * 60 * 1000, SLOW_MS = 20 * 1000;
    const STALE_AT = 90 * 60 * 1000, STALE_MS = 3 * 60 * 1000;
    const CEILING = 6 * 60 * 60 * 1000;
    let timer = null;
    const schedule = (fn, ms) => {
      const i = pollTimers.current.indexOf(timer);
      if (i >= 0) pollTimers.current.splice(i, 1);
      timer = setTimeout(fn, ms);
      pollTimers.current.push(timer);
    };
    const label = (ms) => (ms < 3600000 ? (Math.round(ms / 60000) + "m") : ((Math.round(ms / 360000) / 10) + "h"));
    const short = String(taskId).slice(-6);
    const pause = () => {
      updateLine(lineId, {
        kind: "plain",
        text: "Paused auto-checking after " + label(CEILING) + " with no result — check pixai.art, or reopen this shot to check again (task " + short + ")",
      });
      emit("mg-paused", { task_id: taskId });
    };
    const tick = () => {
      fetch("/api/task-status?task_id=" + encodeURIComponent(taskId))
        .then((r) => r.json())
        .then((d) => {
          if (!connected.current) return;
          const elapsed = Date.now() - startedAt;
          if (d.phase === "done") {
            updateLine(lineId, { kind: "result", mediaIds: d.media_ids || [], cost: d.paid_credit });
            emit("mg-result", { media_ids: d.media_ids || [], is_video: !!d.is_video, duration: d.duration, paid_credit: d.paid_credit });
          } else if (d.phase === "failed") {
            const msg = friendlyGenErr(d.error || ("task " + (d.status || "failed")));
            updateLine(lineId, { kind: "error", text: msg, moon: false });
            emit("mg-error", { error: msg });
          } else if (elapsed > CEILING) {
            pause();
          } else if (elapsed > STALE_AT) {
            updateLine(lineId, { kind: "status", moon: true, amber: true, text: "Still going after " + label(elapsed) + " — unusual. Check pixai.art, or keep waiting (task " + short + ")" });
            emit("mg-slow", { tier: "stale", elapsed, task_id: taskId });
            schedule(tick, STALE_MS);
          } else if (elapsed > SLOW_AT) {
            updateLine(lineId, { kind: "status", moon: true, amber: true, text: "Taking longer than expected (" + label(elapsed) + ", task " + short + ")" });
            emit("mg-slow", { tier: "slow", elapsed, task_id: taskId });
            schedule(tick, SLOW_MS);
          } else {
            updateLine(lineId, { kind: "status", moon: true, text: "Rendering under the eclipse… (task " + short + ")" });
            schedule(tick, 2000);
          }
        })
        .catch(() => {
          if (!connected.current) return;
          const elapsed = Date.now() - startedAt;
          if (elapsed > CEILING) { pause(); return; }
          schedule(tick, elapsed > STALE_AT ? STALE_MS : elapsed > SLOW_AT ? SLOW_MS : 2000);
        });
    };
    schedule(tick, 2000);
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
    rerender(); debCost();
  };
  const prefill = (o) => {
    const r = applyPrefillState(st.current, o);
    syncPlaceholder();
    if (r.setPrompt != null) promptSet(r.setPrompt);
    rerender(); debCost();
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
  const canGo = !s.hostBusy && !s.rendering;

  const SEG = [["i2v", "First Frame"], ["flf", "First & Last Frames"], ["r2v", "Multi-Reference"]];

  const slotBox = (item, i, bank, placeholder, tag) => (
    <div
      key={bank + i} className={"mgd-slot" + (bank === "vid" ? " dashed" : "") + (item ? "" : "")}
      data-nsfw={item && item.is_nsfw ? "1" : undefined}
      style={item && bank === "vid" ? { borderStyle: "solid" } : undefined}
      onClick={() => requestPick(bank, i)}
      onMouseEnter={item ? (e) => showPreview(item.media_id, e.currentTarget) : undefined}
      onMouseLeave={item ? () => hidePreview() : undefined}
    >
      {item ? (
        <>
          <img src={item.thumb} alt="" />
          {bank === "vid" ? <span className="mgd-vidbadge">▶</span> : null}
          <span className="mgd-slot-tag">{tag}</span>
          <button
            type="button" className="mgd-vs-x"
            onClick={(e) => {
              e.stopPropagation(); hidePreview();
              const cur = st.current;
              if (bank === "vid") { cur.vidSlots.splice(i, 1); if (!cur.vidSlots.length) cur.vidSlots = [null]; }
              else if (cur.mode === "r2v") { let arr = cur.imgSlots; arr.splice(i, 1); if (!arr.length) arr = [null]; cur.imgSlots = arr; }
              else cur.slots[i] = null;
              rerender(); debCost();
            }}
          >×</button>
        </>
      ) : placeholder}
    </div>
  );

  // primary bank slots
  const primArr = primary();
  const mainArr = s.mode === "flf" ? [primArr[0]] : primArr;
  let refN = 0;
  const primSlots = mainArr.map((item, i) => {
    let tag = "";
    if (item) { refN++; tag = s.mode === "flf" ? "start" : "@image" + refN; }
    const ph = (s.mode === "flf" || s.mode === "i2v") ? "+ start" : "+ pick";
    return slotBox(item, i, "primary", ph, tag);
  });

  let vidN = 0;
  const vidArr = (s.vidSlots.length ? s.vidSlots : [null]);

  return (
    <div ref={rootRef} className={"gen-drawer" + (className ? " " + className : "")} style={style} data-loom-ctx={loomCtx ? "" : undefined}>
      <div className="mgd-seg" role="tablist">
        {SEG.map(([v, lbl]) => (
          allowedModes.indexOf(v) === -1 ? null : (
            <button key={v} type="button" className={s.mode === v ? "on" : ""} onClick={() => userSetMode(v)}>{lbl}</button>
          )
        ))}
      </div>
      {s.modeNote ? <div className="mgd-modenote">{s.modeNote}</div> : null}

      <div className="mgd-lbl mgd-slots-lbl">{MODE_LBL[s.mode]}</div>
      <div className="mgd-slots mgd-imgslots">
        {primSlots}
        {s.mode === "r2v" && primArr.length < 6 ? (
          <button type="button" className="mgd-slot-add" onClick={() => { st.current.imgSlots.push(null); rerender(); }}>+ add</button>
        ) : null}
      </div>

      {s.mode === "flf" ? (
        <>
          <div className="mgd-lbl">End Frame <span className="mgd-note">(Optional)</span></div>
          <div className="mgd-slots">{slotBox(s.slots[1], 1, "primary", "+ end", "end")}</div>
        </>
      ) : null}

      {isR2v ? (
        <>
          <div className="mgd-lbl">Video references <span className="mgd-note">· up to 3 · 2–15s each, 15s total</span></div>
          <div className="mgd-slots">
            {vidArr.map((item, i) => {
              let tag = "";
              if (item) { vidN++; tag = "@video" + vidN; }
              return slotBox(item, i, "vid", "+ video", tag);
            })}
            {s.vidSlots.length < 3 ? (
              <button type="button" className="mgd-slot-add" onClick={() => { st.current.vidSlots.push(null); rerender(); }}>+ add</button>
            ) : null}
          </div>
          <div className="mgd-lbl">Audio reference <span className="mgd-note">· WAV ≤15MB</span></div>
          <div className="mgd-audiorow">
            {s.audSlot && s.audSlot.uploading ? (
              <span className="mgd-note">Uploading {s.audSlot.uploading}…</span>
            ) : s.audSlot ? (
              <span className="mgd-audiochip">♪ @audio1 · {s.audSlot.filename} <button type="button" onClick={() => { st.current.audSlot = null; rerender(); debCost(); }}>×</button></span>
            ) : (
              <button type="button" className="mgd-audioadd" onClick={() => audFileRef.current && audFileRef.current.click()}>+ Audio</button>
            )}
          </div>
        </>
      ) : null}
      <input ref={audFileRef} type="file" className="mgd-audiofile" accept="audio/*" style={{ display: "none" }}
        onChange={(e) => { const f = e.target.files[0]; e.target.value = ""; if (f) uploadAudio(f); }} />

      {/* contenteditable prompt -- imperative content, React never touches its children */}
      <div ref={ceRef} className="mgd-ce" contentEditable suppressContentEditableWarning
        data-placeholder={MODE_PH[s.mode]} onInput={onCeInput} onBlur={onCeBlur} />

      <div className="mgd-lbl">Negative prompt</div>
      <textarea className="mgd-neg" placeholder="blurry, extra fingers, watermark" value={s.negative}
        onChange={(e) => { st.current.negative = e.target.value; rerender(); debCost(); }} />

      <div className="mgd-row">
        <div className="grow">
          <div className="mgd-lbl">Model</div>
          <select className="mgd-sel mgd-model" value={s.model}
            onChange={(e) => { st.current.model = e.target.value; applyModelGating(true); debCost(); }}>
            {MODELS.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
          <div className="mgd-caps mgd-modelcaps">
            {(chosenModel ? chosenModel.caps : []).map((t) => <span key={t} className="mgd-cap hot">{t}</span>)}
          </div>
        </div>
        <div>
          <div className="mgd-lbl">Duration (s)</div>
          <select className="mgd-sel mgd-dur" value={String(s.duration)}
            onChange={(e) => { st.current.duration = +e.target.value; rerender(); debCost(); emit("mg-duration-commit", { duration: +e.target.value }); }}>
            {[5, 6, 10, 15].map((d) => <option key={d} value={d} disabled={d > maxDur} hidden={d > maxDur}>{d}</option>)}
          </select>
        </div>
      </div>

      <div className="mgd-row">
        <div className="mgd-cam-wrap">
          <div className="mgd-lbl">Camera</div>
          <select className="mgd-sel mgd-cam" value={s.camera} onChange={(e) => { st.current.camera = e.target.value; rerender(); }}>
            <option value="unset">Unset</option>
            <option value="horizontal">Side-to-side move</option>
            <option value="vertical-pan">Vertical Pan</option>
            <option value="zoom">Zoom in or out</option>
            <option value="pan">Camera sweep</option>
            <option value="tilt">Tilt up or down</option>
            <option value="roll">Camera spin</option>
          </select>
        </div>
        <div className="mgd-quality-wrap">
          <div className="mgd-lbl">Basic / Professional</div>
          <select className="mgd-sel mgd-quality" value={s.quality} onChange={(e) => { st.current.quality = e.target.value; rerender(); }}>
            <option value="basic">Basic</option>
            <option value="professional">Professional</option>
          </select>
        </div>
        <div>
          <div className="mgd-lbl">Channel</div>
          <select className="mgd-sel mgd-channel" value={s.channel} onChange={(e) => { st.current.channel = e.target.value; rerender(); debCost(); }}>
            <option value="normal">Normal</option>
            <option value="enhanced">Enhanced</option>
          </select>
          <div className="mgd-caps mgd-chancap">
            <span className={"mgd-cap" + (s.channel === "enhanced" ? " crown" : "")}>{CHANNEL_CAP[s.channel]}</span>
          </div>
        </div>
      </div>

      <label className="mgd-check">
        <input type="checkbox" className="mgd-audio" checked={s.audioGen}
          onChange={(e) => { st.current.audioGen = e.target.checked; rerender(); debCost(); emit("mg-audio-commit", { audioGen: e.target.checked, audioLanguage: st.current.audioLanguage }); }} />
        {" "}Generate audio <span className="mgd-note">(spoken lines in the prompt become voiceover)</span>
      </label>
      {s.audioGen ? (
        <div className="mgd-lang-wrap" style={{ marginTop: 4 }}>
          <div className="mgd-lbl">Audio language</div>
          <select className="mgd-sel mgd-lang" value={s.audioLanguage}
            onChange={(e) => { st.current.audioLanguage = e.target.value; rerender(); debCost(); emit("mg-audio-commit", { audioGen: st.current.audioGen, audioLanguage: e.target.value }); }}>
            <option value="english">English</option>
            <option value="japanese">Japanese</option>
            <option value="chinese">Chinese</option>
            <option value="korean">Korean</option>
            <option value="none">SE only (no dialogue)</option>
          </select>
        </div>
      ) : null}

      <CostBadge ref={costRef} className="mgd-cost" warn={warn} cardLabel="a video card"
        hint="Pick a source image to see the cost." />

      <button type="button" className="mgd-go" disabled={!canGo} onClick={doGenerate}>
        {s.rendering ? "Rendering…" : "Generate video"}
      </button>

      <div className={"mgd-result" + (results.length ? " has" : "")}>
        {results.map((l) => (
          <div key={l.id} className="mgd-result-line">
            {l.kind === "result" ? (
              <>
                <div style={{ color: "var(--emerald,#4fc99a)", fontSize: 12, marginBottom: 6 }}>
                  ✓ Rendered — {l.cost === 0 ? "free (card used)" : (Number(l.cost || 0).toLocaleString() + " credits")}. Added to your gallery.
                </div>
                {(l.mediaIds || []).map((mid) => (
                  <a key={mid} href={"/next?image=" + encodeURIComponent(mid)}>
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

      <div ref={previewRef} className="mgd-preview" aria-hidden="true" />
    </div>
  );
});

export default VideoDrawer;
