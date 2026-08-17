import React, {
  forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState,
} from "react";
import { createPortal } from "react-dom";
import CostBadge from "./CostBadge.jsx";
import {
  MODELS, MODEL_VMODES, MODEL_MAXDUR, MODE_LBL, MODE_PH, CHANNEL_CAP, CAMERA_OPTS, AUDIO_LANGS,
  DEFAULT_MODEL, MODEL_CARD, SHOT_LABEL, modelCaps, modelMeta, bankView,
  friendlyGenErr, refItem, primaryBank, setPrimaryBank, buildPayload, hasAnyRef,
  priceKey, canSubmit, PRICE_FETCH_TIMEOUT_MS,
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
   the CostBadge in the footer is the SAME instance costRef drives (debCost/costNow untouched).
   Without `dock` (the Loom, mobile Video mode) everything renders inline exactly as before. */

let lineSeq = 0;

// The DC's TINTS (Frontend Gallery.dc.html 1648-1656): the engine card's thumb + the palette
// covers are tinted by roster index (videoThumbStyle 2901) -- the real roster carries no art.
const ENGINE_TINTS = [
  "linear-gradient(150deg, #33236d 0%, #1b1733 100%)",
  "linear-gradient(150deg, #3a3460 0%, #17142b 100%)",
  "linear-gradient(150deg, #643aac 0%, #241f5b 100%)",
  "linear-gradient(150deg, #2a4a58 0%, #171f38 100%)",
  "linear-gradient(150deg, #4a3a6e 0%, #1f1a36 100%)",
  "linear-gradient(150deg, #3a2b63 0%, #191338 100%)",
  "linear-gradient(150deg, #5a3a72 0%, #221a3e 100%)",
];

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
    // The price verdict's IDENTITY (videoDrawerCore.canSubmit reads exactly this shape): settled
    // = the badge shows the verdict for pricedKey; pricedKey = priceKey() of the payload that was
    // priced; pendingTimer = a debCost re-price is scheduled and not yet fired. Go is disabled
    // unless the payload it would submit has this same key -- state alone can't say that.
    // Seeded once below: the badge's initial idle hint IS the verdict for the initial empty form.
    price: null,
  });
  if (!st.current.price) st.current.price = { settled: true, pricedKey: priceKey(buildPayload(st.current, "")), pendingTimer: false };
  const [, force] = useState(0);
  const rerender = useCallback(() => force((n) => n + 1), []);

  const [results, setResults] = useState([]);   // concurrent result lines
  const [warn, setWarnState] = useState("");     // CostBadge caution clause (paid-state only)
  // The ↺-from chip (SCOPE_2026-08-17 §2): "prefilled from run #NNNN", the video mirror of the
  // dock's image chip (GenerateDrawer.reuseFrom). {tag, partial} | null -- `partial` is the amber
  // "recipe from the catalog only / camera unknown / …" disclosure (§2.4). Set imperatively by the
  // host's prefillVideoFromRun via node.setReuse; cleared on the user's × click and on submit
  // (a new render's recipe is no longer "from" the old run). Plain React state -- it is not a
  // spend-critical form field, so the st.current/rerender discipline the payload needs is overkill.
  const [reuse, setReuseChip] = useState(null);
  // The ENGINE palette (DC 1612-1640 + 2795-2804: 'Video engine' picker cards over the real
  // roster). {bottom} = its viewport anchor, measured off this drawer's top when it opens so it
  // floats just above the form in every host (dock / Loom / mobile) the way the DC's sits above
  // the dock's settings. null = closed. `palQuery` is its Search box.
  const [pal, setPal] = useState(null);
  const [palQuery, setPalQuery] = useState("");
  const setWarn = useCallback((w) => setWarnState(w), []);
  const ceRef = useRef(null);                    // the contenteditable prompt
  const previewRef = useRef(null);
  const audFileRef = useRef(null);
  const costRef = useRef(null);
  const rootRef = useRef(null);
  // liveNode retains the root node even AFTER React unmounts it (React nulls rootRef on unmount).
  // A /api/loom/generate submit that resolves after the drawer unmounts (e.g. the Loom's Mobile-
  // view toggle flipped mid-render) must still dispatch its spend-tracking mg-submit: the host
  // bound that listener with addEventListener directly on the node, and addEventListener listeners
  // fire on a detached node. That dispatch is what persists pendingTaskId so an already-charged
  // render is recoverable on reload -- the vanilla dispatched off its retained element for exactly
  // this reason; nulling on unmount turned a recoverable case into a silent ~210k-credit loss.
  const liveNode = useRef(null);
  const setRoot = useCallback((n) => { rootRef.current = n; if (n) liveNode.current = n; }, []);

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
    const n = liveNode.current;   // retained across unmount (see setRoot) so a post-unmount submit still fires
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

  // ---- the ENGINE palette (open / close / Escape) ------------------------------------------
  const openPalette = () => {
    const r = rootRef.current ? rootRef.current.getBoundingClientRect() : null;
    const vh = window.innerHeight || 800;
    // Sit just above the drawer (DC: above the dock's settings), clamped so the 46vh panel fits.
    let bottom = r ? Math.round(vh - r.top + 12) : 250;
    bottom = Math.max(14, Math.min(bottom, Math.round(vh * 0.54) - 14));
    setPalQuery("");
    setPal({ bottom });
  };
  const closePalette = useCallback(() => { setPal(null); setPalQuery(""); }, []);
  useEffect(() => {
    if (!pal) return undefined;
    // Capture-phase so this innermost layer takes Escape before a host's own window listener
    // (the dock's Esc chain collapses settings / closes the dock on the bubble phase).
    const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); closePalette(); } };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [pal, closePalette]);

  // ---- payload + live cost -------------------------------------------------------------------
  // payload/hasAnyRef/flfMissingStart are the PURE spend-gate predicates (videoDrawerCore.js); the
  // prompt text is the one DOM-sourced field, read from the contenteditable and passed in.
  const payload = () => buildPayload(st.current, promptText());
  const flfMissingStart = () => flfMissingStartOf(st.current);

  const debCost = (force) => {
    // SHORT-CIRCUIT when nothing that prices has changed: if the payload's price identity
    // equals the SETTLED key, the quote on the badge is still exactly right, so leave it (and
    // Go) alone. This is what makes a prompt/negative keystroke harmless -- those fields are
    // outside priceKey ("never prices"), yet their handlers call debCost, and before this every
    // typing pause blanked the badge, disabled Generate for 250ms+RTT, discarded any in-flight
    // quote, and re-POSTed /api/price (three PixAI calls) for a byte-identical payload (review
    // 2026-08-16). Fixing it HERE, at the mechanism, covers every non-pricing caller, present
    // and future, instead of auditing handlers one by one. Un-settled/pending states still
    // fall through so a genuine re-price is never suppressed.
    //
    // `force` bypasses the short-circuit for the ONE case where the payload is identical but the
    // verdict is stale anyway: right after a submit debited the tickets. Identity-by-payload
    // cannot see a balance change, so the post-submit re-price must not be swallowed here.
    const pr = st.current.price;
    if (!force && pr && pr.settled && pr.pricedKey != null && !pr.pendingTimer
        && pr.pricedKey === priceKey(buildPayload(st.current, ""))) {
      return;
    }
    // Blank the number FIRST, synchronously (mirrors useGenerate's refreshPrice): an old quote
    // next to new settings is the one thing worse than no quote. Before this, setChecking only
    // ran 250ms later inside costNow, so a settled FREE for 5s stayed on the badge -- and Go
    // stayed live -- for the debounce plus one RTT after the user picked 15s. Dropping the
    // verdict identity here (settled=false, pendingTimer=true) is what disables Go; bumping
    // costSeq drops any answer already in flight, since it was priced off the payload that just
    // stopped being true. Every debCost caller repaints, so canGo re-reads this on the next render.
    const cost = costRef.current;
    if (cost && cost.setChecking) cost.setChecking();
    st.current.price = { settled: false, pricedKey: null, pendingTimer: true };
    costSeq.current++;
    clearTimeout(costTimer.current);
    costTimer.current = setTimeout(costNow, 250);
    rerender();
  };
  // The HOST half of CostBadge's contract: owns the /api/price call, the 250ms debounce, and the
  // _costSeq stale-response guard; the badge owns every state's wording/colour. It is ALSO the
  // only writer of a settled price identity: every exit records priceKey(p) for the payload it
  // just judged (the idle hints are verdicts too -- "nothing to price" keeps Go live so its own
  // "Pick a source image first" error stays reachable; doGenerate refuses those before any spend).
  const costNow = () => {
    // The timer has FIRED: clear pendingTimer before anything can bail, or an early return
    // (no badge ref) leaves {pendingTimer:true} forever and canSubmit never passes (review).
    st.current.price = { settled: false, pricedKey: null, pendingTimer: false };
    const cost = costRef.current;
    if (!cost) return;
    const s = st.current, p = payload();
    const settle = (key) => { st.current.price = { settled: true, pricedKey: key, pendingTimer: false }; rerender(); };
    // Mode-dependent idle label is delivered through clear()'s one-shot hint override (the badge
    // has no setHint -- the idle state shows note||hint, and clear(h) sets that h).
    const idleHint = (s.mode === "r2v") ? "Pick at least one reference to see the cost." : "Pick a source image to see the cost.";
    if (!hasAnyRef(p)) { setWarn(""); cost.clear(idleHint); settle(priceKey(p)); return; }
    if (flfMissingStart()) { setWarn(""); cost.clear("Pick a Start Frame — the End Frame alone can’t drive First & Last."); settle(priceKey(p)); return; }
    // v4.0 full is ~2.5x Lite (14k/s -> 210k for a 15s clip). The badge shows `warn` only in the
    // `paid` state; the red (not amber) colour is re-asserted by gen-drawer.css's own override.
    setWarn(p.video_model === "v4.0" ? "V4.0 full — ~2.5× Lite" : "");
    cost.setChecking();
    const mine = ++costSeq.current;
    // The identity is recorded ONLY under the costSeq guard, off the SAME p that was priced. A
    // failed check settles too: the badge's red "couldn't verify — may spend" IS this payload's
    // verdict (same call the image drawer makes), whereas a verdict for a different payload is
    // exactly what canSubmit refuses.
    // BOUNDED: Go is hard-gated on this fetch settling, and a HUNG request (transport stall --
    // a LAN tablet dropping Wi-Fi mid-request) fires neither .then nor .catch, so settle()
    // never ran, canSubmit stayed false forever, and the badge sat on a muted "Checking cost…"
    // with no error and no way out short of changing a priced field (review 2026-08-16).
    // Before the identity gate a hung price left Go LIVE (fail-open); the gate made it
    // fail-silent-closed. An abort after PRICE_FETCH_TIMEOUT_MS rejects into the existing
    // .catch, which already paints the red "couldn't verify — may spend" and settles, so the
    // state machine reaches its documented error verdict and Go returns to its pre-gate,
    // fail-closed-but-live behaviour. The server's own PixAI calls carry timeouts (30s/60s),
    // so this only ever fires on a browser<->server stall.
    const ctrl = (typeof AbortController !== "undefined") ? new AbortController() : null;
    const abortTimer = ctrl ? setTimeout(() => ctrl.abort(), PRICE_FETCH_TIMEOUT_MS) : 0;
    fetch("/api/price", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(p), signal: ctrl ? ctrl.signal : undefined })
      .then((r) => r.json())
      .then((d) => { clearTimeout(abortTimer); if (mine === costSeq.current && costRef.current) { costRef.current.setPrice(d); settle(priceKey(p)); } })
      .catch(() => { clearTimeout(abortTimer); if (mine === costSeq.current && costRef.current) { costRef.current.setPrice(null); settle(priceKey(p)); } });
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
    // PAYLOAD IDENTITY gate (the button is already disabled on it via canGo; this is the click
    // that slips through a stale render). The quote on the badge must have been priced off THIS
    // payload -- a settled FREE for 5s must never carry a 15s submit, and a quality/camera change
    // must not ride a price it never saw. Never a silent drop: say so and re-price.
    if (!canSubmit(s.price, p)) {
      pushLine({ kind: "status", text: "Re-checking the cost… try again when the badge settles." });
      // Only kick a NEW re-price when nothing is already in flight for this payload. Calling
      // debCost() unconditionally here bumped costSeq (discarding a quote about to settle) and
      // restarted the debounce, so fast repeated clicks could keep the badge from ever settling
      // (review: refusal-path starvation). If a check is pending, just refuse and let it land.
      // A check is "in flight" when the debounce timer is pending or a fetch is out
      // (unsettled with no key). In both cases the answer for THIS payload is already
      // coming -- don't discard it. Otherwise (settled-but-stale key) re-price.
      const pr = s.price || {};
      const checkInFlight = !!pr.pendingTimer || (!pr.settled && pr.pricedKey == null);
      if (!checkInFlight) debCost();
      return;
    }
    const id = pushLine({ kind: "status", moon: true, text: "Submitting…" });
    setReuseChip(null);   // a new submission goes out -- the recipe is no longer "from" the old run
    st.current.rendering = true;
    rerender();
    const unlock = () => { st.current.rendering = false; rerender(); };
    fetch("/api/loom/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(p) })
      .then((r) => r.json())
      .then((d) => {
        unlock();   // the server answered -- free the button for the NEXT submission
        // A submit-time failure (server rejection or !task_id) must also emit mg-error, exactly as
        // the vanilla's _renderErrorInto did -- otherwise the Loom's onVideoError never runs and a
        // rejected shot shows no error badge on the board when the Video tab is collapsed. (No
        // credits are spent on a failed submit, so this is a status regression, not a spend one.)
        if (d.error || !d.task_id) {
          const msg = friendlyGenErr(d.error || "submit failed");
          updateLine(id, { kind: "error", text: msg, moon: false });
          emit("mg-error", { error: msg });
          return;
        }
        emit("mg-submit", { task_id: d.task_id, payload: p });
        updateLine(id, { kind: "status", moon: true, text: "Queued — running…" });
        // The submit just DEBITED tickets, so the settled verdict is stale even though the
        // payload is byte-identical -- identity-by-payload cannot see a balance change caused
        // by the drawer's own submit. Without this, a second click on the unchanged form passed
        // canSubmit on the same key and submitted under a FREE badge for a clip the server now
        // found SHORT and charged in full (review: post-submit stale FREE, the exact #15 shape).
        // FORCED: the payload is byte-identical to the settled key, so an unforced debCost would
        // short-circuit as "nothing changed" -- but the balance did.
        debCost(true);
        poll(d.task_id, id);
      })
      .catch(() => { unlock(); updateLine(id, { kind: "error", text: "network error", moon: false }); emit("mg-error", { error: "network error" }); });
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
  // Go is DISABLED (not awaited) until the badge's settled verdict is for the payload this form
  // would submit right now -- an await here would add PixAI RTTs after the click and land after
  // the rendering latch, a double-submit window. Prompt text is outside priceKey, so the payload
  // is keyed off the form state alone here (no DOM read in render).
  const canGo = !s.hostBusy && !s.rendering && canSubmit(s.price, buildPayload(s, ""));

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
    rerender(); debCost();
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

  // The engine palette's cards over the REAL roster (DC 2795-2804: name · shot modes · duration
  // cap · caps as the tooltip). No per-second rate: the price is CostBadge's to say.
  const palQ = palQuery.trim().toLowerCase();
  const palItems = MODELS.filter((m) => !palQ || m.label.toLowerCase().indexOf(palQ) >= 0);
  const engineIdx = Math.max(0, MODELS.findIndex((m) => m.value === s.model));

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
      onChange={(e) => { st.current.negative = e.target.value; rerender(); debCost(); }} />
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

  // The ENGINE palette (DC 1608-1640; items DC 2795-2804; paletteStyle 3701): a scrim + a
  // 720px card grid, PORTALED OUT of this drawer so no host's overflow/transform can clip or
  // re-anchor it (the dock's .mgdock is transformed + overflow:hidden). Target: the dock host
  // (.mgx-dock-host, display:contents -- the same place the dock's model flyout lives) so the
  // dock's outside-click closer still sees the click as INSIDE the dock; <body> elsewhere.
  const layerHost = (rootRef.current && rootRef.current.closest && rootRef.current.closest(".mgx-dock-host")) || document.body;
  const palette = pal ? createPortal(
    <>
      <div className="mgd-palscrim" onClick={closePalette} />
      <div className="mgd-pal" style={{ bottom: pal.bottom }} role="dialog" aria-label="Video engine">
        <div className="mgd-palhd">
          <div className="mgd-paltitle">Video engine</div>
          <div className="mgd-palsub">Shot type follows the engine — unsupported modes switch on pick</div>
          <div className="mgd-palsp" />
          <input className="mgd-palq" value={palQuery} placeholder="Search" autoFocus
            onChange={(e) => setPalQuery(e.target.value)} />
          <button type="button" className="mgd-palx" onClick={closePalette} title="Close">×</button>
        </div>
        <div className="mgd-palgrid">
          {palItems.map((m) => {
            const i = MODELS.indexOf(m);
            const modes = (MODEL_VMODES[m.value] || ["i2v", "flf", "r2v"]).map((x) => SHOT_LABEL[x]).join(" · ");
            return (
              <button key={m.value} type="button" className={"mgd-palitem" + (m.value === s.model ? " on" : "")}
                title={m.caps.join(" · ")}
                onClick={() => { st.current.model = m.value; applyModelGating(true); debCost(); closePalette(); }}>
                <div className="mgd-palcover" style={{ background: ENGINE_TINTS[i % ENGINE_TINTS.length] }}>
                  <span className="mgd-paloff">Official</span>
                </div>
                <div className="mgd-palbody">
                  <div className="mgd-palname">{m.label}</div>
                  <div className="mgd-palmeta"><span>{modes}</span><span>{(MODEL_MAXDUR[m.value] || 10)}s max</span></div>
                  <div className="mgd-palcost">{MODEL_CARD[m.value] === false ? "no card" : "card"}</div>
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </>, layerHost) : null;

  return (
    <div ref={setRoot} className={"gen-drawer" + (inDock ? " mgd-dock" : "") + (inDock && dock.expanded === false ? " mgd-collapsed" : "") + (className ? " " + className : "")} style={style} data-loom-ctx={loomCtx ? "" : undefined}>
      {/* The DC's expanded Video settings: three slabs (DC 1209-1210 grid; slab(i) 2876) --
          SHOT MODE + banks · ENGINE + chips + DURATION + CAMERA · MODE & CHANNEL + switches.
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
                    onClick={() => { st.current.audSlot = null; rerender(); debCost(); }}>
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
        </div>

        <div className="mgd-slab" style={{ animationDelay: "60ms" }}>
          <div className="mgd-sec">ENGINE</div>
          {/* DC 1380-1387 modelRowStyle: thumb · name + meta ('<maxDur>s max · V4.0 cards apply /
              never card-covered', from the REAL roster's caps) · browse -> the engine palette. */}
          <button type="button" className="mgd-engine" onClick={openPalette} title="Browse the video engines">
            <span className="mgd-engthumb" style={{ background: ENGINE_TINTS[engineIdx % ENGINE_TINTS.length] }} />
            <span className="mgd-engbody">
              <span className="mgd-engname">{chosenModel ? chosenModel.label : s.model}</span>
              <span className="mgd-engmeta">{modelMeta(s.model)}</span>
            </span>
            <span className="mgd-engbrowse">browse</span>
          </button>
          <div className="mgd-caps mgd-modelcaps">
            {modelCaps(s.model).map(([t, kind]) => <span key={t} className={"mgd-cap" + (kind ? " " + kind : "")}>{t}</span>)}
          </div>
          {/* DURATION (DC 1393-1401 + durationStops 2906-2911): the label with a live 'Ns'
              readout, then four segmented stops. A stop above the REAL engine cap
              (MODEL_MAXDUR -- the spend gate applyModelGating clamps to) stays visible but
              dimmed, not-allowed, titled, and its click is ignored -- never removed. */}
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
                  onClick={() => { if (!ok || d === st.current.duration) return; st.current.duration = d; rerender(); debCost(); emit("mg-duration-commit", { duration: d }); }}>{d}</button>
              );
            })}
          </div>
          {/* CAMERA (DC 1402-1412): below DURATION in this slab; in Multi-Reference the block
              keeps its space but goes invisible (cameraVis 2912) -- the payload already drops
              camera_movement for r2v. Camera and quality both ride the priced payload
              (i2vPro.cameraMovement / .mode), so each change re-prices like every other priced
              field -- without it a settled quote sat next to a payload it was never for, with
              no re-check pending at all. */}
          <div className={"mgd-cam-wrap" + (isR2v ? " hid" : "")} aria-hidden={isR2v || undefined}>
            <div className="mgd-sec">CAMERA</div>
            <select className="mgd-sel mgd-cam" value={s.camera} tabIndex={isR2v ? -1 : undefined} onChange={(e) => { st.current.camera = e.target.value; rerender(); debCost(); }}>
              {CAMERA_OPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
        </div>

        {/* MODE & CHANNEL (DC 1416-1441): Basic|Professional seg -> Normal|Enhanced seg ->
            plain caption -> the two pill switches -> (audio on) the bare language select. */}
        <div className="mgd-slab" style={{ animationDelay: "120ms" }}>
          <div className="mgd-sec">MODE &amp; CHANNEL</div>
          <div className="mgd-seg mgd-quality-wrap" role="radiogroup" aria-label="Mode">
            {[["basic", "Basic"], ["professional", "Professional"]].map(([v, l]) => (
              <button key={v} type="button" role="radio" aria-checked={s.quality === v} className={"mgd-quality" + (s.quality === v ? " on" : "")} onClick={() => { if (st.current.quality === v) return; st.current.quality = v; rerender(); debCost(); }}>{l}</button>
            ))}
          </div>
          <div className="mgd-seg" role="radiogroup" aria-label="Channel">
            {[["normal", "Normal"], ["enhanced", "Enhanced"]].map(([v, l]) => (
              <button key={v} type="button" role="radio" aria-checked={s.channel === v} className={"mgd-channel" + (s.channel === v ? " on" : "")} onClick={() => { if (st.current.channel === v) return; st.current.channel = v; rerender(); debCost(); }}>{l}</button>
            ))}
          </div>
          <div className="mgd-chancap">{CHANNEL_CAP[s.channel]}</div>
          <label className="mgd-sw" title="Spoken lines in the prompt become voiceover">
            <input type="checkbox" className="mgd-audio" checked={s.audioGen}
              onChange={(e) => { st.current.audioGen = e.target.checked; rerender(); debCost(); emit("mg-audio-commit", { audioGen: e.target.checked, audioLanguage: st.current.audioLanguage }); }} />
            <span className="mgd-swtrack"><i /></span>
            <span className="mgd-swlab">Generate audio</span>
          </label>
          <label className="mgd-sw" title="Off by default — the opposite of image gen">
            <input type="checkbox" className="mgd-helper" checked={s.videoHelper}
              onChange={(e) => { st.current.videoHelper = e.target.checked; rerender(); debCost(); }} />
            <span className="mgd-swtrack"><i /></span>
            <span className="mgd-swlab">Video prompt helper</span>
          </label>
          {s.audioGen ? (
            <select className="mgd-sel mgd-lang" value={s.audioLanguage} aria-label="Audio language"
              onChange={(e) => { st.current.audioLanguage = e.target.value; rerender(); debCost(); emit("mg-audio-commit", { audioGen: st.current.audioGen, audioLanguage: e.target.value }); }}>
              {AUDIO_LANGS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          ) : null}
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

      {/* Result / status lines. Not drawn in the DC (it routes runs into the RUNS reel, and the
          dock's reel does list these submits via Jobs.register) -- kept because this is the
          ONLY home for the drawer's own refusals and submit-time errors ('Pick a source image
          first.', 'Re-checking the cost…', a rejected submit), which never reach the reel. */}
      <div className={"mgd-result" + (results.length ? " has" : "")}>
        {results.map((l) => (
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

      <div ref={previewRef} className="mgd-preview" aria-hidden="true" />
      {palette}
    </div>
  );
});

export default VideoDrawer;
