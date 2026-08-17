import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useGenerate from "../gen/useGenerate.js";
import {
  ASPECTS, MODES, SIZES, dims, goGate, loraIncompat, loraRange, loraStep,
  planLoraRestore,
} from "../gen/genCore.js";
import ModelFlyout from "./ModelFlyout.jsx";
import CostBadge from "./CostBadge.jsx";
import VideoDrawer from "./VideoDrawer.jsx";
import EditTab, { SourceSlab } from "./EditTab.jsx";
import FixTab from "./FixTab.jsx";
import { EDIT_DEFAULTS } from "../gen/editCore.js";
import { dockLayout } from "../gen/dockLayout.js";
import FilterCompare from "./FilterCompare.jsx";
import RunsReel, { isRunningJob } from "./RunsReel.jsx";
import HistoryStrip, { RunTip } from "./HistoryStrip.jsx";
import { askPicker, isPickerOpen } from "./PickerHost.jsx";
import "../styles/dock.css";

/* The Generate DOCK — the designed bottom-center glass reshell of the pilot's
   Generate drawer (design spec: Frontend Gallery.dc.html §§ dock 708–1224,
   README dock bullets, drift items 8 + 22).

   MACHINERY IS UNCHANGED. Image tab = React port riding the classic endpoints
   (useGenerate/genCore/submitTask); Edit/Fixer = EditTab/FixTab; Enhance =
   the art-filters compare panel; Video tab = the React <VideoDrawer> (the
   no-vanilla port of the shared video form, 2026-08-08). Every submit path, the
   CostBadge pricing, the request contract ({tab, mid, thumb, nonce}) and the
   videoPrefill hand-off all keep firing exactly as before — this file only
   re-shells the chrome around them.

   ONE FOOTER (fidelity pass 2026-08-16, DC 1541-1591 + handoff §2): the ▲ toggle,
   the composer box and the cost stack + Generate render at the DOCK level, on
   every tab. Video / Edit / Fixer do NOT get a second submit path: each keeps its
   own prompt, CostBadge and Generate button and PORTALS them into the footer's
   slots (their `dock` prop) -- same state, same gate, same handler, new place.

   THE DRAWER IS NEVER UNMOUNTED. It hides with CSS (the host's open/closing
   classes on .mgx-dock-host drive mgDockIn/mgDockOut), because VideoDrawer's
   unmount effect sweeps its poll timers -- unmounting on close would orphan an
   in-flight (already charged) video task from every surface, and a v4.0 15s
   render is ~210,000 credits. */

function VideoTab({ visible, prefillRequest, drawerRef, dock }) {
  const el = drawerRef;
  // The lightbox's "To Video" hand-off (classic's Gen.addVideoRefs): a single
  // image reference always prefills as i2v (first-frame), matching classic's
  // refs.length>1?'r2v':'i2v' for the one-image case. VideoDrawer's ref resolves
  // to its root DOM node with .prefill hung on it, so this call site is unchanged
  // from the vanilla custom element it replaced.
  useEffect(() => {
    if (!prefillRequest || !el.current || typeof el.current.prefill !== "function") return;
    el.current.prefill(prefillRequest);
  }, [prefillRequest]); // eslint-disable-line react-hooks/exhaustive-deps
  // `dock` = the footer slots (see the DOCK MODE note in VideoDrawer.jsx): the drawer's
  // own prompt / negative / CostBadge / Generate portal into the dock's shared footer.
  return (
    <div className={"mgdock-videohost" + (dock && dock.expanded === false ? " collapsed" : "")} style={{ display: visible ? "" : "none" }}>
      <VideoDrawer ref={el} dock={dock} />
    </div>
  );
}

/* The ▲ toggle -- ONE component, in the footer, on every tab (handoff 2026-08-16 §2:
   "▲ Expand gets one home"). Titles verbatim from the DC's expandTitle (3541);
   the metallic 38×38 face + rotating caret are expandBtnStyle/caretStyle (3542-3544). */
function ExpandToggle({ expanded, onToggle }) {
  return (
    <button type="button" className="mgdock-expand" onClick={onToggle}
      title={expanded ? "Collapse the settings" : "Open model, frame and tuning"}>
      <span className={"mgdock-caret" + (expanded ? " flip" : "")}>▲</span>
    </button>
  );
}

export default function GenerateDrawer({ open, onClose, account, request }) {
  const [tab, setTab] = useState("image");
  const [sub, setSub] = useState("edit");          // edit | fixer | enhance (DC 1917 / 2925 keys)
  const [expanded, setExpanded] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [promptFocus, setPromptFocus] = useState(false);
  const [snippetsOpen, setSnippetsOpen] = useState(false); // ★ Snippets chip row toggle
  /* THE EDIT TAB'S STATE LIVES HERE (dock fidelity stage 3, 2026-08-16): the DC's own
     model -- one component holds editRefs / editModel / resolution / … for all three
     sub-tabs (Frontend Gallery.dc.html 1917-1922) -- so the SOURCE slab (the picture
     being edited + its references, DC 1445-1468, NOT gated by `sub`) is ONE list that
     Edit, Fixer and Enhance all read. EditTab / FixTab take it as props and keep owning
     their pricing, gates and submit paths unchanged. `droppedNote` is the slab's inline
     amber line (DC 1465-1467), set by a model switch that trims references, cleared by
     removing a slot. */
  const [editS, setEditS] = useState(EDIT_DEFAULTS);
  const [droppedNote, setDroppedNote] = useState("");
  // The Edit hand-off (lightbox Edit, #edit deep link with a mid, the filters panel's
  // send): land on the Edit sub-tab with that picture as the source. Setting the shared
  // state directly re-applies even when the SAME image is sent twice after a clear (the
  // 2026-08-07 nonce dance is not needed any more -- there is no child effect to re-fire).
  // A hand-off also OPENS the settings, as the video prefill does (the DC's own prefill
  // precedent, 2321 `expanded: true`): the slot this just filled must be visible.
  const sendToEdit = (mid) => {
    if (!mid) return;
    setEditS((o) => ({ ...o, source: mid }));
    setTab("edit");
    setSub("edit");
    setExpanded(true);
  };
  const [videoPrefill, setVideoPrefill] = useState(null);
  const [flyOpen, setFlyOpen] = useState(false);
  const [flyKind, setFlyKind] = useState("base");
  const [filtersOpen, setFiltersOpen] = useState(false);
  // Lineage: "reusing settings from run #N" -- a LOCAL annotation only (no
  // backend concept exists for it), set at prefill time and cleared the moment
  // a new submission goes out. See prefillFromRun below + the composer chip.
  const [reuseFrom, setReuseFrom] = useState(null);   // {jobId, tag, partial}
  // The run tooltip (DC runTip 1936 / 2711-2723): ONE tooltip for the reel and History,
  // {x, y, lines} from the hovered tile's viewport rect. Rendered OUTSIDE the aside (below).
  const [runTip, setRunTip] = useState(null);
  // Prefill epoch + busy gate (adversarial review 2026-08-13, findings 1.3 +
  // 2.2): the epoch retires an older in-flight prefill wholesale the moment a
  // newer one starts (no chimera recipes), and the busy flag holds the
  // Generate button until the whole recipe -- LoRAs included -- has settled,
  // so an impatient click can't submit the recipe minus its LoRAs.
  const prefillSeq = useRef(0);
  const [prefillBusy, setPrefillBusy] = useState(false);
  const costRef = useRef(null);
  const drawerRef = useRef(null);
  const g = useGenerate({ costRef });
  const { s, set } = g;
  const loraCap = account && account.lora_cap != null ? account.lora_cap : null;
  const gate = goGate(s, loraCap);
  const balance = account && account.credits != null ? account.credits : null;

  /* ---- THE ONE FOOTER (Frontend Gallery.dc.html 1551-1591): expand · composer ·
     cost stack + Generate, rendered at the DOCK level, on every tab. The Image tab's
     pieces are this component's own (useGenerate state); Video / Edit / Fixer keep
     owning THEIR prompt, cost badge and submit gate and portal them into the slots
     below (VideoDrawer / EditTab / FixTab `dock` prop). The slots are React state
     (setState IS the ref callback -- stable identity, fires on mount/unmount only) so
     the tab components re-render once the slot node exists. Per-tab slot wrappers
     stay MOUNTED and hide by display, so a tab's portal content -- notably the video
     prompt's imperative contenteditable -- survives tab switches intact. ---- */
  const videoRef = useRef(null);                       // VideoDrawer's root node handle
  const [videoTopEl, setVideoTopEl] = useState(null);
  const [videoPromptEl, setVideoPromptEl] = useState(null);
  const [videoNegEl, setVideoNegEl] = useState(null);
  const [videoGoEl, setVideoGoEl] = useState(null);
  const [editTopEl, setEditTopEl] = useState(null);
  const [editPromptEl, setEditPromptEl] = useState(null);
  const [editGoEl, setEditGoEl] = useState(null);
  const [editResultsEl, setEditResultsEl] = useState(null); // Edit/Fix result lines, under the grid
  const editPromptApi = useRef(null);                  // { insert(t), read() } while EditTab is up

  /* Prompt snippets manager -- the real per-account store (/api/snippets), replacing the
     4 hardcoded demo chips. Ports classic's Snips popover: save-current / insert / delete
     with one-level Undo (deliberately NOT a confirm -- an undo taxes only the mistake,
     matching classic's own reasoning), server 200-cap. Lazy-loaded on first open; a write
     failure surfaces inline rather than the classic's window.Toast (no global dependency
     in React). */
  const [snips, setSnips] = useState(null);        // null = not loaded yet
  const [snipUndo, setSnipUndo] = useState(null);  // {text} of the last delete, one level
  const [snipErr, setSnipErr] = useState("");
  useEffect(() => {
    if (!snippetsOpen || snips !== null) return;
    let dead = false;
    fetch("/api/snippets").then((r) => r.json())
      .then((d) => { if (!dead) setSnips(Array.isArray(d.snippets) ? d.snippets : []); })
      .catch(() => { if (!dead) setSnips([]); });
    return () => { dead = true; };
  }, [snippetsOpen, snips]);
  const persistSnips = (list) => {
    setSnips(list); setSnipErr("");
    fetch("/api/snippets", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ snippets: list }) })
      .then((r) => r.json())
      .then((d) => { if (!d || d.error) setSnipErr((d && d.error) || "The server rejected the save."); })
      .catch(() => setSnipErr("Network error — not saved."));
  };
  const snipTrunc = (t) => (String(t).length > 44 ? String(t).slice(0, 44) + "…" : t);
  /* The composer (and so ★ Snippets) is shared by every tab now: read/insert against
     the ACTIVE tab's prompt -- the image draft here, the video drawer's contenteditable
     through its node handle, the Edit instruction through EditTab's registered api.
     Fixer/Enhance have no prompt, so the Snippets toggle is not offered there. */
  const readActivePrompt = () => {
    if (tab === "video") {
      const el = videoRef.current;
      return el && typeof el.promptText === "function" ? el.promptText() : "";
    }
    if (tab === "edit") return editPromptApi.current ? editPromptApi.current.read() : "";
    return s.prompt || "";
  };
  const saveCurrentSnip = () => {
    const v = readActivePrompt().trim();
    if (!v || (snips || []).includes(v)) return;
    persistSnips([v, ...(snips || [])].slice(0, 200));
  };
  const insertSnip = (sn) => {
    if (tab === "video") {
      const el = videoRef.current;
      if (el && typeof el.insertText === "function") el.insertText(sn);
      return;
    }
    if (tab === "edit") {
      if (editPromptApi.current) editPromptApi.current.insert(sn);
      return;
    }
    // trim FIRST (matches the +words button and classic), so stray leading/trailing
    // whitespace on the prompt never leaks a "text , snippet" stray space before the comma.
    set({ prompt: (s.prompt.trim() ? s.prompt.trim().replace(/,\s*$/, "") + ", " : "") + sn });
  };
  const snippetsAvail = tab === "image" || tab === "video" || (tab === "edit" && sub === "edit");
  const delSnip = (i) => {
    const list = snips || [];
    if (!list[i]) return;
    setSnipUndo({ text: list[i], index: i });   // remember WHERE, to restore in place
    persistSnips(list.filter((_, j) => j !== i));
  };
  const undoSnip = () => {
    if (!snipUndo) return;
    const list = snips || [];
    if (!list.includes(snipUndo.text)) {
      const next = list.slice();
      next.splice(Math.min(snipUndo.index, next.length), 0, snipUndo.text);
      persistSnips(next.slice(0, 200));
    }
    setSnipUndo(null);
  };

  /* ---- REAL runs data: GET /api/jobs, generate-type only. The reel, the
     header label and the peek pill all derive from this one list. Refreshed
     by the same three completion channels App.jsx listens on, plus a slow
     poll while the dock is open or anything is still running. ---- */
  const [jobs, setJobs] = useState([]);
  const fetchJobs = useCallback(() => {
    fetch("/api/jobs")
      .then((r) => r.json())
      .then((d) => setJobs(((d && d.jobs) || []).filter((j) => j.type === "generate")))
      .catch(() => {});
  }, []);
  useEffect(() => {
    fetchJobs();
    const onEvt = () => fetchJobs();
    window.addEventListener("mg-gen-done", onEvt);
    document.addEventListener("mg-submit", onEvt);
    document.addEventListener("mg-result", onEvt);
    return () => {
      window.removeEventListener("mg-gen-done", onEvt);
      document.removeEventListener("mg-submit", onEvt);
      document.removeEventListener("mg-result", onEvt);
    };
  }, [fetchJobs]);
  const runningCount = jobs.filter(isRunningJob).length;
  useEffect(() => {
    if (!open && !runningCount) return;
    const t = setInterval(fetchJobs, open ? 4000 : 8000);
    return () => clearInterval(t);
  }, [open, runningCount, fetchJobs]);

  /* ---- measurement (DC measureDock/fitReel: a layout contract, not
     decoration). The dock never rises above the separator bar EXCEPT when
     expanded or the prompt is long, when it may grow to 100vh-28.
     The height pass (owner calls 08-16d/e/f, drift §43): standard stays
     content-sized under the separator ceiling; the prompt's resting floor is
     6 rows (grows with the text to the room-driven cap, max 14; past that the
     textarea scrolls, never the panel); ▲ keeps the reel visible above the
     settings slabs (tiles tier to 84/104, reel-room measured against ▲'s own
     100vh-28 ceiling minus the ~330px slab chrome, auto-hide only under 60px);
     ▲ and History compose. ---- */
  const [metrics, setMetrics] = useState({ sepBottom: 260, vh: 800 });
  useEffect(() => {
    const measure = () => {
      const sep = document.querySelector(".mgx-sep");
      const sb = sep ? Math.round(sep.getBoundingClientRect().bottom) : 260;
      const vh = window.innerHeight;
      setMetrics((m) => (m.sepBottom === sb && m.vh === vh ? m : { sepBottom: sb, vh }));
    };
    measure();
    window.addEventListener("resize", measure);
    const hdr = document.querySelector(".mgx-hdr");
    let ro = null;
    if (hdr && typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(measure);
      ro.observe(hdr);
    }
    return () => {
      window.removeEventListener("resize", measure);
      if (ro) ro.disconnect();
    };
  }, [open]);

  // The arithmetic itself is gen/dockLayout.js (DC measureDock / fitReel / promptRows,
  // one pure function) so the tests run exactly what renders here.
  const { capH, reelH, reelVisible, promptMax, promptRows } = dockLayout({
    vh: metrics.vh, sepBottom: metrics.sepBottom, expanded, historyOpen,
    promptLen: (s.prompt || "").length, promptFocus,
  });

  /* Prime the cost chip on each Image-tab entry. The image <CostBadge> sits in the
     dock footer's right column under `tab === "image"`, so it mounts and unmounts
     with the tab; its ref is live at commit, and refreshPrice() re-prices the
     current draft whenever the tab is (re)entered — the badge starts idle on each
     remount, exactly as the old re-created element did. (Unchanged machinery; g
     intentionally out of the deps so this fires on entry, not every keystroke.) */
  useEffect(() => {
    if (open && tab === "image") g.refreshPrice();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tab]);

  /* External entry points into the drawer (the lightbox's Edit / To Video
     buttons and the #edit/#video deep links -- classic's Gen.openEdit()/
     Gen.addVideoRefs()). `request` is a one-shot object (a fresh nonce each
     time, set by the caller), so asking for the SAME image twice in a row
     still re-fires this effect. (Unchanged contract; Edit now also lands on
     the Edit sub-tab of the merged Edit tab.) */
  useEffect(() => {
    if (!request) return;
    if (request.tab === "edit") {
      // A midless request is the #edit deep link: land on the tab, touch nothing else.
      setTab("edit");
      setSub("edit");
      if (request.mid) sendToEdit(request.mid);
    } else if (request.tab === "video") {
      setTab("video");
      // A midless request is the #video deep link: land on the tab, prefill nothing.
      // A prefill also OPENS the settings (the DC's own prefill precedent, 2321 `expanded:
      // true`): the video slabs live behind ▲ now, and the frame this hand-off just
      // filled must be visible, not hidden behind a collapsed grid.
      if (request.mid) { setVideoPrefill({ mode: "i2v", images: [{ media_id: request.mid, thumb: request.thumb }] }); setExpanded(true); }
    } else if (request.tab === "remix") {
      // Remix (issue #4): the picture's FULL recipe into the Image tab -- the
      // same prefill the Runs reel's reuse click performs, reached from the
      // grid context menu / Details footer. prefillFromRun is deliberately NOT
      // in the dep array: its identity changes every render (it closes over
      // `g`), and [request] alone is the one-shot-nonce contract above.
      if (request.mid) prefillFromRun("", request.mid);
    }
  }, [request]);

  /* Filters and the model/LoRA flyout are floating overlays; letting both open
     at once would stack them. Opening either closes the other; closing the
     dock itself (the × button, outside-click via the host, or the Escape
     ladder below) closes both. */
  const closeDrawer = useCallback(() => {
    setFlyOpen(false);
    setFiltersOpen(false);
    setExpanded(false);
    onClose();
  }, [onClose]);
  const toggleFilters = useCallback(() => {
    setFlyOpen(false);
    setFiltersOpen((v) => !v);
  }, []);

  /* The HOST can close the dock without going through closeDrawer (its
     outside-click closer, the banner toggles). The floating overlays now live
     OUTSIDE the aside (see below), so they must fold when the dock does. */
  useEffect(() => {
    if (open) return;
    setFlyOpen(false);
    setFiltersOpen(false);
    setExpanded(false);
  }, [open]);

  /* Escape closes the TOPMOST layer only: picker → filters → flyout →
     collapse the settings → close History → the dock (the DC's Esc chain
     1977-1984, innermost first; ▲ and History compose, so each is its own step). */
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (isPickerOpen()) return;              // the picker handles its own Escape
      if (filtersOpen) { setFiltersOpen(false); return; }
      if (flyOpen) { setFlyOpen(false); return; }
      if (expanded) { setExpanded(false); return; }
      if (historyOpen) { setHistoryOpen(false); return; }
      closeDrawer();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, filtersOpen, flyOpen, expanded, historyOpen, closeDrawer]);

  const onBasePick = useCallback((row) => {
    setFlyOpen(false);                          // single-select closes, classic
    g.applyModelRow(row);
  }, [g]);

  /* REUSE: a done reel tile's real prefill (owner correction, 2026-08-02) --
     fetches the SAME /api/next/detail/<media_id> Details/Lightbox already call,
     and maps its row onto the real composer setters. Prefills only -- never
     submits; the user reviews/edits, then clicks Generate themselves.

     Fields mapped: model, prompt, negative, frame (customW/customH set directly
     from the row's real width/height -- an exact reproduction, more faithful
     than reverse-guessing which aspect/size stop it came from), steps, cfg, seed.

     MODEL is a two-hop resolve (2026-08-02, fixes a verify-flagged bug found
     live: reuse silently failed to restore the model on every click, old or
     new gens alike). The catalog's row.model_id is the VERSION PixAI actually
     rendered with, not the base model id applyModelRow expects (it calls
     /api/model-version?model_id=X to enumerate a BASE model's versions -- fed
     a version id, that returns nothing and the reuse silently keeps whatever
     model was already selected). /api/model-version?version_id=X does the
     reverse lookup first (core.resolve_model_base_id), THEN applyModelRow
     resolves that real base id server-side the same way a fresh market pick
     does -- never trusts a stale id either way. A run whose model can't be
     resolved (PixAI-side removal, an unconfigured MODEL_DETAIL_HASH) leaves
     the composer's model untouched rather than showing the old wrong-id
     failure toast for a case that isn't the user's mistake.

     LoRAs are restored by EXACT version id, never by name (Remix, issue #4,
     2026-08-13): /api/task-params reads the task's own parameters.lora --
     {loraVersionId: weight}, the only LoRA record PixAI stores -- and resolves
     each id to its base model server-side. The catalog's `loras` column stays
     what it always was, a display-only name string; fuzzy-matching it back
     would risk wiring a DIFFERENT LoRA into a paid submission on a name
     collision, which the spend-safety contract in gen/genCore.js forbids
     ("never let a substitution pass unremarked"). Consequences of that same
     contract here: LoRAs only load when their OWN model was restored (exact
     weights are only valid against the task's architecture); a second version
     of the same LoRA model, an unresolvable id, or a failed read is COUNTED
     and disclosed -- on the persistent chip, not just a toast; and the exact
     rendered model VERSION is re-picked after the base-model apply (the
     catalog's model_id IS that version id).

     model_id resolution runs FIRST and is awaited: applyModelRow can apply the
     newly-picked model's own preset (negative/steps/cfg) as a side effect, and
     the run's own real values must win over that preset, not be clobbered by
     it. */
  const prefillFromRun = useCallback(async (jobId, mediaId) => {
    if (!mediaId) return;
    const my = ++prefillSeq.current;
    const live = () => prefillSeq.current === my;   // stale flows stop applying, wholesale
    setPrefillBusy(true);
    const notes = [];
    try {
      let row;
      try {
        const r = await fetch("/api/next/detail/" + encodeURIComponent(mediaId));
        const d = await r.json();
        if (d.error || !d.row) {
          if (window.Toast) window.Toast.show({ kind: "err", title: "Couldn't load that run's settings", msg: d.error || "" });
          return;
        }
        row = d.row;
      } catch {
        if (window.Toast) window.Toast.show({ kind: "err", title: "Couldn't load that run's settings", msg: "Network error." });
        return;
      }
      if (!live()) return;
      let modelOk = false;
      if (row.model_id) {
        let baseId = "";
        try {
          const rv = await fetch("/api/model-version?version_id=" + encodeURIComponent(row.model_id));
          const dv = await rv.json();
          baseId = (dv && dv.model_id) || "";
        } catch { /* soft-fail: leave the composer's model untouched below */ }
        if (!live()) return;
        if (baseId) {
          const applied = await g.applyModelRow({ model_id: baseId, title: row.model_name || row.model_id, preview_url: "" });
          if (!live()) return;
          if (applied) {
            modelOk = true;
            // applyModelRow lands on the base's LATEST version; the catalog's
            // model_id is the version the task actually rendered with -- re-pick
            // it exactly, checking membership on the RETURNED versions list
            // (state can't be read this soon after an async apply -- a live run
            // false-warned off exactly that). A genuinely delisted version is a
            // DISCLOSED substitution.
            if ((applied.versions || []).some((v) => v.version_id === row.model_id)) {
              if (applied.version_id !== row.model_id) g.pickVersion(row.model_id);
            } else {
              notes.push("rendered version no longer listed — latest used");
            }
          }
        }
      }
      if (!modelOk) notes.push("model could not be restored — pick it manually");
      g.set({
        prompt: row.prompt_full || row.prompt_preview || "",
        negative: row.negative_prompt || "",
        customW: row.width ? String(row.width) : "",
        customH: row.height ? String(row.height) : "",
        steps: row.steps || "",
        cfg: row.cfg_scale || "",
        seed: row.seed || "",
        loras: [],          // the recipe REPLACES composer LoRA state on every path below
      });
      const hadLoras = !!(row.loras || "").trim();   // catalog display string: "did the task use any?"
      if (!row.task_id) {
        if (hadLoras) notes.push("no task record — LoRAs unknown");
      } else if (!modelOk) {
        // exact weights are only valid against the task's own architecture --
        // never wire them onto whatever model happened to be selected
        if (hadLoras) notes.push("LoRAs not loaded without the model");
      } else {
        try {
          const rt = await fetch("/api/task-params/" + encodeURIComponent(row.task_id));
          const dt = await rt.json();
          if (!live()) return;
          if (dt.error) {
            if (hadLoras) notes.push("LoRAs could not be restored");
          } else {
            // dedup/count/cross-check logic is the PURE planLoraRestore
            // (genCore.js) so the node harness can pin it -- see
            // loom/test/mg-remix-lora-plan.test.js
            const plan = planLoraRestore(dt, hadLoras);
            for (const lr of plan.rows) {
              await g.addLora(lr);          // exact version_id + weight ride the row itself
              if (!live()) return;
            }
            notes.push(...plan.notes);
          }
        } catch {
          if (hadLoras) notes.push("LoRAs could not be restored");
        }
      }
      setTab("image");
      // DC prefill 2321 `expanded: true, historyOpen: false`: a prefill from any tile
      // exits History INTO the expanded composer (DECISIONS 2551/2562).
      setExpanded(true);
      setHistoryOpen(false);
      // A reel click has a jobId; a Remix doesn't -- fall back to the row's own
      // task id so the chip still reads "↺ from #NNNN" either way. `partial`
      // rides the chip so an incomplete recipe stays visibly incomplete until
      // cleared -- a toast alone is not a receipt (genCore.js contract).
      const tagId = jobId || row.task_id || mediaId;
      const partial = notes.join("; ");
      setReuseFrom({ jobId: tagId, tag: "#" + String(tagId || "").slice(-4), partial });
      if (partial && window.Toast) {
        window.Toast.show({ kind: "info", title: "Remix is partial", msg: partial + " — review before generating." });
      }
    } finally {
      if (live()) setPrefillBusy(false);
    }
  }, [g]);

  /* multi picker contract: (model, selected). The picker owns its own highlight
     state, so honor its verdict instead of second-guessing from ours. */
  const onLoraPick = useCallback((model, selected) => {
    if (!model || !model.model_id) return;
    if (selected === false) g.removeLora(model.model_id);
    else g.addLora(model);
  }, [g]);

  const removeLora = (modelId) => {
    // Controlled selection: removing from state un-lights the picker card automatically.
    g.removeLora(modelId);
  };

  const pickRef = async () => {
    const m = await askPicker({ type: "image" });
    if (m) set({ ref: { media_id: m.media_id, thumb: m.thumb } });
  };

  const m = s.model;
  const restr = (m && m.restrictions) || {};
  const stepsR = restr.samplingSteps || {};
  const cfgR = restr.cfgScale || {};
  const [lo, hi] = loraRange(m ? m.model_type : "");

  const d = dims(s);
  const custom = !!(parseInt(s.customW, 10) > 0 && parseInt(s.customH, 10) > 0);
  // Frontend Gallery.dc.html:2893's own formula: "768×1024 · Auto · ×3" -- size, the
  // TUNING mode's display name, and the design's ×N count form (was "px" + "N images",
  // neither of which the design uses), with its no-model nudge prefix.
  const modeName = (MODES.find(([v]) => v === s.mode) || ["", s.mode])[1];
  const frameSummary = (m ? "" : "pick a model · ") + d.width + "×" + d.height + " · " + modeName
    + (s.count > 1 ? " · ×" + s.count : "");
  // DC 3573-3576: the slab's model row says 'none — browse models', the composer pip
  // 'browse models' (in lavender) while no model is picked. 'Resolving…' is the
  // build's own transient (a real async version resolve the DC has no equivalent for).
  const modelName = m ? (m.resolving ? "Resolving…" : m.title) : "none — browse models";
  const modelShort = m ? (m.resolving ? "Resolving…" : m.title) : "browse models";

  /* Composer focus ring (DC composerStyle 3548-3550: accent border + glow while the
     prompt has focus). One native focusin/focusout pair on the composer box covers the
     image textarea AND the portaled video/edit prompts alike -- React's synthetic focus
     events bubble through the React tree, and a portal's React parent is its tab
     component, not this box. */
  const composerRef = useRef(null);
  useEffect(() => {
    const node = composerRef.current;
    if (!node) return;
    const isPrompt = (t) => !!(t && t.matches && t.matches("textarea, [contenteditable]"));
    const onIn = (e) => { if (isPrompt(e.target)) setPromptFocus(true); };
    const onOut = (e) => { if (isPrompt(e.target)) setPromptFocus(false); };
    node.addEventListener("focusin", onIn);
    node.addEventListener("focusout", onOut);
    return () => {
      node.removeEventListener("focusin", onIn);
      node.removeEventListener("focusout", onOut);
    };
  }, []);

  // The footer slot contracts handed to the tab components (memoized so a render of this
  // component doesn't hand them a new object for no reason).
  // `expanded` rides along: the video settings slabs show only while ▲ is open, exactly as
  // the DC's settings grid does on every tab (DC 1209 `sc-if expanded`); the drawer hides
  // them with CSS and stays mounted (its poll timers / portals / prompt content survive).
  const videoDock = useMemo(() => ({
    topEl: videoTopEl, promptEl: videoPromptEl, negativeEl: videoNegEl, goEl: videoGoEl, balance, expanded,
  }), [videoTopEl, videoPromptEl, videoNegEl, videoGoEl, balance, expanded]);
  // `expanded` rides along for the Fixer too (its canvas re-measures when the grid re-opens).
  // `promptFocus` too: the portaled instruction grows a row while focused, the DC's
  // promptRows rule (3558-3559) that the image prompt above already follows.
  const editDock = useMemo(() => ({
    topEl: editTopEl, promptEl: editPromptEl, goEl: editGoEl, resultsEl: editResultsEl, balance,
    promptApi: editPromptApi, promptMax, promptFocus, expanded,
  }), [editTopEl, editPromptEl, editGoEl, editResultsEl, balance, promptMax, promptFocus, expanded]);

  /* The peek pill can only OPEN the dock through the host's own toggle verbs;
     the drawer has no openDock prop, so it forwards the click to a real
     [data-dock-toggle] launcher (Banner/SeparatorBar) — the same code path a
     user click takes, no second open mechanism invented. */
  const openViaToggle = () => {
    const els = document.querySelectorAll("[data-dock-toggle]");
    for (const el of els) {
      if (!el.classList.contains("mgdock-peek")) { el.click(); return; }
    }
  };

  // DC 3509-3512: the label reads "History" in History (over "Making"); the live
  // "N image(s) resolving" note wins over either mode's note while anything runs.
  const reelLabel = historyOpen ? "History" : (runningCount ? "Making" : "Runs");
  const reelNote = runningCount
    ? runningCount + (runningCount === 1 ? " image resolving — it sharpens as it lands" : " images resolving — they sharpen as they land")
    : (historyOpen ? "7 days · newest first · click any run to reuse its settings" : "today · click any run to reuse its settings");

  const stepsVal = s.steps === "" ? 25 : Number(s.steps);
  const cfgVal = s.cfg === "" ? 7 : Number(s.cfg);

  return (
    <>
      {/* PEEK PILL — shown only when the dock is fully closed AND runs live */}
      {!open && runningCount > 0 && (
        <div className="mgdock-peek" data-dock-toggle="1" onClick={openViaToggle}
          title="Still running — open the dock to watch them resolve">
          <span className="mgdock-eclipse"><span /></span>
          <div className="mgdock-peektxt">{runningCount} making</div>
        </div>
      )}

      {/* expanded scrim: click collapses the settings */}
      {open && expanded && (
        <div className="mgdock-scrim" title="Collapse the settings"
          onClick={() => setExpanded(false)} />
      )}

      {/* Stays MOUNTED always and animates via the HOST's open/closing classes
          (.mgx-dock-host drives mgDockIn/mgDockOut + the 360ms deferred
          unmount window). `inert` keeps the hidden dock out of tab order. */}
      <aside ref={drawerRef}
        className={"mgdock" + (expanded ? " expanded" : "")}
        role="dialog" aria-label="Generate"
        aria-hidden={!open} inert={open ? undefined : ""}
        style={{ maxHeight: Math.max(180, capH) + "px" }}>
        <div className="mgdock-glow" aria-hidden="true" />

        {/* ---- HEADER: runs label · note · tab strip · History · × ---- */}
        <div className="mgdock-head">
          <span className="mgdock-runslabel" style={reelVisible ? null : { display: "none" }}>{reelLabel}</span>
          <span className="mgdock-runsnote" style={reelVisible ? null : { display: "none" }}>{reelNote}</span>
          <span className="sp" />
          {/* The notice ("Pick a model first" …) -- handoff 2026-08-16 §2: no row of its
              own; inline beside the tab strip, rendered only while true. */}
          {tab === "image" && gate && (
            <span className="mgdock-notice" role="status">{gate}</span>
          )}
          <div className="mgdock-tabs">
            {/* titles per DC 2819: label + ' generation' */}
            {[["image", "Image", "Image generation"],
              ["edit", "Edit", "Edit generation"],
              ["video", "Video", "Video generation"]].map(([k, l, t]) => (
              <button key={k} type="button" title={t}
                className={"mgdock-tab" + (tab === k ? " on" : "")}
                onClick={() => setTab(k)}>{l}</button>
            ))}
          </div>
          {/* DC 3518 historyBtnStyle: History belongs to the reel -- hidden with it.
              No title (DC 1115 has none; the header note carries the copy). */}
          <button type="button" className={"mgdock-hist" + (historyOpen ? " on" : "")}
            style={reelVisible ? null : { display: "none" }}
            onClick={() => setHistoryOpen((v) => !v)}>
            {historyOpen ? "Hide history" : "History"}
          </button>
          <button type="button" className="mgdock-x" onClick={closeDrawer}
            title="Close the dock — runs keep going">×</button>
        </div>

        {/* ---- DOCK BODY: reel (or the 7-day History strip in its place -- the same
             slot, ABOVE the ▲ slabs, DC 1119-1207) · per-tab surface. Safety-valve
             scroll for short windows only — the composer footer never scrolls. ---- */}
        <div className="mgdock-body">
          {reelVisible && (historyOpen
            ? <HistoryStrip onPrefill={prefillFromRun} onTip={setRunTip} />
            : <RunsReel jobs={jobs} reelH={reelH} onPrefill={prefillFromRun} onTip={setRunTip} />)}

          {tab === "image" && expanded && (
            <div className="mgdock-slabs">
              {/* SLAB 1 — MODEL & LORAS */}
              <div className="mgdock-slab" style={{ animationDelay: "0ms" }}>
                <div className="mgdock-lbl">MODEL &amp; LORAS</div>
                <button type="button" className={"mgdock-modelrow" + (m ? "" : " empty")}
                  onClick={() => { setFiltersOpen(false); setFlyKind("base"); setFlyOpen(!flyOpen); }}
                  title="Browse the model catalog">
                  {m && m.thumb ? <img className="mgdock-modelthumb" src={m.thumb} alt="" /> : <span className="mgdock-modelthumb ph" />}
                  <span className="mgdock-modelname">{modelName}</span>
                  <span className="sp" />
                  <span className="mgdock-browse">browse</span>
                </button>
                {m && m.versions && m.versions.length > 1 && (
                  <select className="gd-sel" value={m.version_id}
                    onChange={(e) => g.pickVersion(e.target.value)}>
                    {m.versions.map((v) => (
                      <option key={v.version_id} value={v.version_id}>{v.label || v.version_id}</option>
                    ))}
                  </select>
                )}
                {m && m.preset && m.preset.sampler ? (
                  <div className="mgdock-presetnote">
                    {m.title} ships its author's preset — applied on pick · sampler {m.preset.sampler}
                  </div>
                ) : null}
                {s.loras.map((l) => {
                  const bad = loraIncompat(l, m);
                  return (
                    <div key={l.model_id} className={"gd-lora" + (bad || l.failed ? " bad" : "")}>
                      {l.preview_url ? <img src={l.preview_url} alt="" /> : null}
                      <span className="gd-lora-t" title={l.title}>{l.title}</span>
                      {l.failed ? <span className="gd-warn">failed</span> :
                        !l.version_id ? <span className="gd-note">resolving…</span> : null}
                      {bad ? <span className="gd-warn">wrong architecture</span> : null}
                      {l.trigger_words ? (
                        <button className="gd-mini" title={"Insert: " + l.trigger_words}
                          onClick={() => set({
                            prompt: (s.prompt.trim() ? s.prompt.trim().replace(/,\s*$/, "") + ", " : "")
                                    + String(l.trigger_words).replace(/,\s*$/, ""),
                          })}>
                          +words
                        </button>
                      ) : null}
                      <input type="range" min={lo} max={hi} step={loraStep()} value={l.weight}
                        onChange={(e) => g.setLora(l.model_id, { weight: e.target.value })} />
                      <b className="gd-w">{Number(l.weight).toFixed(2)}</b>
                      <button className="gd-mini" onClick={() => removeLora(l.model_id)}>&times;</button>
                    </div>
                  );
                })}
                <button type="button" className="mgdock-addlora"
                  onClick={() => { setFiltersOpen(false); setFlyKind("lora"); setFlyOpen(!flyOpen); }}>
                  + Add LoRA{loraCap != null ? ` ${s.loras.length} / ${loraCap}` : s.loras.length ? " " + s.loras.length : ""}
                </button>
                <div className="mgdock-refrow">
                  <button type="button" className={"mgdock-refslot" + (s.ref ? " filled" : "")}
                    onClick={pickRef} title="Pick from your gallery">
                    {s.ref ? <img src={s.ref.thumb} alt="" /> : "+ ref"}
                  </button>
                  {s.ref && (
                    <>
                      <span className="mgdock-lbl">STRENGTH</span>
                      <input type="range" min="0.1" max="1" step="0.05" value={s.refStrength}
                        onChange={(e) => set({ refStrength: e.target.value })} />
                      <b className="gd-w">{Number(s.refStrength).toFixed(2)}</b>
                      <button className="gd-mini" onClick={() => set({ ref: null })}>&times;</button>
                    </>
                  )}
                </div>
              </div>

              {/* SLAB 2 — FRAME */}
              <div className="mgdock-slab" style={{ animationDelay: "60ms" }}>
                <div className="mgdock-lbl">FRAME</div>
                <div className="mgdock-ratios">
                  {ASPECTS.map(([label, r]) => {
                    const on = !s.customW && !s.customH && Math.abs(s.aspect - r) < 0.001;
                    const gw = r >= 1 ? 19 : Math.max(6, Math.round(19 * r));
                    const gh = r >= 1 ? Math.max(6, Math.round(19 / r)) : 19;
                    return (
                      <button key={label} type="button"
                        className={"mgdock-ratio" + (on ? " on" : "")}
                        onClick={() => set({ aspect: r, customW: "", customH: "" })}
                        title={label}>
                        <i style={{ width: gw, height: gh }} />
                        <span>{label}</span>
                      </button>
                    );
                  })}
                </div>
                <div className="mgdock-lbl">SIZE · LONG EDGE</div>
                <div className="mgdock-stops">
                  {SIZES.map((n, i) => (
                    <button key={n} type="button"
                      className={"mgdock-stop" + (!custom && s.size === n ? " on" : "")}
                      onClick={() => set({ size: n, customW: "", customH: "" })}
                      title={n + "px"}>
                      {["S", "M", "L", "XL"][i] || n}
                    </button>
                  ))}
                </div>
                <div className="mgdock-customrow">
                  <input className={"mgdock-custom" + (custom ? " on" : "")} placeholder="W" value={s.customW}
                    onChange={(e) => set({ customW: e.target.value.replace(/\D/g, "") })} />
                  ×
                  <input className={"mgdock-custom" + (custom ? " on" : "")} placeholder="H" value={s.customH}
                    onChange={(e) => set({ customH: e.target.value.replace(/\D/g, "") })} />
                  <span className="mgdock-note-sm">overrides</span>
                </div>
                <div className="mgdock-dims">
                  → {d.width} × {d.height} px{custom ? <span className="mauve"> · custom wins</span> : null}
                </div>
                <div className="mgdock-lbl">COUNT</div>
                <div className="mgdock-stops">
                  {[1, 2, 3, 4].map((n) => (
                    <button key={n} type="button"
                      className={"mgdock-stop" + (s.count === n ? " on" : "")}
                      onClick={() => set({ count: n })}>{n}</button>
                  ))}
                </div>
              </div>

              {/* SLAB 3 — TUNING */}
              <div className="mgdock-slab" style={{ animationDelay: "120ms" }}>
                <div className="mgdock-lbl">TUNING · {(MODES.find(([v]) => v === s.mode) || ["", s.mode])[1]}</div>
                <div className="mgdock-modebars">
                  {MODES.map(([v, l], i) => (
                    <button key={v} type="button" title={l}
                      className={"mgdock-modebar" + (i <= MODES.findIndex(([x]) => x === s.mode) ? " on" : "")}
                      onClick={() => set({ mode: v })} />
                  ))}
                </div>
                <div className="mgdock-sliderrow">
                  <span className="mgdock-lbl">STEPS</span>
                  <input type="range"
                    min={stepsR.min != null ? stepsR.min : 1}
                    max={stepsR.max != null ? stepsR.max : 150}
                    step="1" value={stepsVal}
                    disabled={m && m.compat_steps === false}
                    title={m && m.compat_steps === false ? (m.title + " doesn't take STEPS") : "Sampling steps"}
                    onChange={(e) => set({ steps: e.target.value })} />
                  <input className="gd-num" value={s.steps} disabled={m && m.compat_steps === false}
                    placeholder={stepsR.min != null ? `${stepsR.min}–${stepsR.max}` : "25"}
                    onChange={(e) => set({ steps: e.target.value.replace(/\D/g, "") })}
                    onBlur={(e) => set({ steps: clampField(e.target.value, stepsR, 1, 150) })} />
                </div>
                <div className="mgdock-sliderrow">
                  <span className="mgdock-lbl">CFG</span>
                  <input type="range"
                    min={cfgR.min != null ? cfgR.min : 1}
                    max={cfgR.max != null ? cfgR.max : 30}
                    step="0.5" value={cfgVal}
                    disabled={m && m.compat_cfg === false}
                    title={m && m.compat_cfg === false ? (m.title + " doesn't take CFG") : "CFG scale"}
                    onChange={(e) => set({ cfg: e.target.value })} />
                  <input className="gd-num" value={s.cfg} disabled={m && m.compat_cfg === false}
                    placeholder={cfgR.min != null ? `${cfgR.min}–${cfgR.max}` : "auto"}
                    onChange={(e) => set({ cfg: e.target.value.replace(/[^\d.]/g, "") })}
                    onBlur={(e) => set({ cfg: clampField(e.target.value, cfgR, 1, 30) })} />
                </div>
                <div className="mgdock-sliderrow">
                  <span className="mgdock-lbl">SEED</span>
                  <input className="mgdock-seed" value={s.seed} placeholder="blank = random"
                    onChange={(e) => set({ seed: e.target.value.replace(/[^\d-]/g, "").replace(/(?!^)-/g, "") })} />
                </div>
                <div className="mgdock-chips">
                  <button type="button"
                    className={"mgdock-chip" + (s.boosters.face ? " on" : "")}
                    onClick={() => set({ boosters: { ...s.boosters, face: !s.boosters.face } })}>
                    Face Fix
                  </button>
                  <button type="button"
                    className={"mgdock-chip" + (s.boosters.quality ? " on" : "")}
                    title="Prefixes PixAI's Masterpiece quality tag"
                    onClick={() => set({ boosters: { ...s.boosters, quality: !s.boosters.quality } })}>
                    Quality Tag
                  </button>
                  <button type="button"
                    className={"mgdock-chip" + (s.boosters.hires ? " on" : "")}
                    disabled={m && m.compat_upscale === false}
                    title={m && m.compat_upscale === false
                      ? "This model's version does not support upscaling"
                      : "Enhance Details — PixAI's own 1.5× / 0.6 denoise pass"}
                    onClick={() => set({ boosters: { ...s.boosters, hires: !s.boosters.hires } })}>
                    Enhance Details
                  </button>
                </div>
                <label className="mgdock-sw" title="Faster queue · costs extra">
                  <input type="checkbox" checked={s.highPriority}
                    onChange={(e) => set({ highPriority: e.target.checked })} />
                  <span className="mgdock-swtrack"><i /></span>
                  <span className="mgdock-swlab">High priority</span>
                </label>
                <label className="mgdock-sw" title="PixAI's prompt helper (on by default, like the classic drawer)">
                  <input type="checkbox" checked={s.promptHelper}
                    onChange={(e) => set({ promptHelper: e.target.checked })} />
                  <span className="mgdock-swtrack"><i /></span>
                  <span className="mgdock-swlab">Prompt helper</span>
                </label>
              </div>
            </div>
          )}

          {tab === "image" && g.results.length > 0 && (
            <div className="gd-results mgdock-results">
              {g.results.map((r) => (
                <div key={r.id} className={"gd-res " + r.kind}>
                  {r.kind === "run" ? "⏳ " : r.kind === "ok" ? "✔ " : "✕ "}{r.text}
                  {r.media && r.media.map((mid) => (
                    <a key={mid} href={"/full/" + mid} target="_blank" rel="noreferrer">
                      <img src={"/thumbs/" + mid + ".jpg"} alt="" />
                    </a>
                  ))}
                </div>
              ))}
            </div>
          )}

          {/* ---- THE EDIT TAB (DC 1444-1541): the SAME expanded 3-slab grid as the
               image tab (DC 1209-1210 -> .mgdock-slabs), behind ▲ -- SOURCE · EDIT MODEL /
               REGION / ART FILTERS · QUALITY -- plus the shared footer below. Gated on
               `expanded` the way stage 2 gated the video slabs: the grid hides with CSS
               (.collapsed) and everything stays MOUNTED -- EditTab/FixTab keep their state
               and their footer portals (instruction / CostBadge / ✦ Edit·Fix) alive while
               collapsed, and a half-built edit survives a detour to Image/Video (their
               `visible` prop toggles a null return; the host hides by display). The
               result lines render OUTSIDE the grid so a submit from the collapsed footer
               can still answer. */}
          <div className="mgdock-edithost" style={{ display: tab === "edit" ? "" : "none" }}>
            <div className={"mgdock-slabs mgdock-editslabs" + (expanded ? "" : " collapsed")}>
              {/* SLAB 1 -- SOURCE, for every sub-tab (the sub-tab strip lives inside it) */}
              <SourceSlab s={editS} setS={setEditS} sub={sub} onSub={setSub}
                droppedNote={droppedNote} onDroppedNote={setDroppedNote} />
              {/* SLABS 2 + 3 -- Edit: EDIT MODEL + QUALITY (EditTab); Fixer: REGION (FixTab)
                  + the QUALITY shell; Enhance: ART FILTERS + the QUALITY shell */}
              <EditTab visible={tab === "edit" && sub === "edit"} s={editS} setS={setEditS}
                onDroppedNote={setDroppedNote} dock={editDock} />
              <FixTab visible={tab === "edit" && sub === "fixer"} dock={editDock}
                source={editS.source} />
              {tab === "edit" && sub === "enhance" && (
                /* slab 2 under Enhance -- DC 1471 + 2931 editSlabLabel 'ART FILTERS', then
                   DC 1509-1516 verbatim: a flex column (gap 9) holding the 9px sub-label
                   'ART FILTERS · free, no generation' (1511 -- lowercase kept, it is not the
                   slab heading), the ◉ Open filters button (1512, openFiltersBtnStyle 2947),
                   paragraph 1 (1513, 10px/1.55 subtext, <b> in var(--text)) and paragraph 2
                   (1514, 10px/1.55 overlay0, <b> in var(--subtext)).
                   PARAGRAPH 2's LAST CLAUSE IS REAL-DATA (owner ruling 2026-08-16): the DC
                   says 'Upscale and Hires on the Generate tab's Upscale row' -- this build
                   has no such row (DECISIONS 2026-07-25 'Upscale belongs on the image view,
                   not in the generate drawer': the Off/Upscale/Hires segment was removed;
                   Upscale is the lightbox's flyout / the details page's panel, hires is the
                   Generate tab's 'Enhance Details' booster), so the sentence names where
                   those really live. Everything before it is the DC's copy word for word. */
                <div className="mgdock-slab" style={{ animationDelay: "60ms" }}>
                  <div className="mgdock-lbl">ART FILTERS</div>
                  <div className="mgdock-enhancecol">
                    <div className="mgdock-enhancesub">ART FILTERS · free, no generation</div>
                    <button type="button" className="mgdock-openfilters" onClick={toggleFilters}>
                      ◉ Open filters
                    </button>
                    <div className="mgdock-enhancecopy">
                      PixAI's seven art filters are gradient overlays, not AI — so they are applied
                      right here in the browser: <b>no credits, no request, works offline</b>. Pick a
                      source image above, then open the panel to compare and save.
                    </div>
                    <div className="mgdock-enhancecopy2">
                      Still pixai.art only: their one-click ComfyUI workflows (background removal,
                      line art, sketch colouring, relight). Submitted with an API key those queue
                      and are cancelled unstarted about an hour later, so this app can't offer them.
                      But run one on their site and the result still lands in your library
                      automatically — only the submit button is missing, never the collecting. What
                      also works: <b>Upscale</b> from the lightbox or Image Details, and <b>Enhance
                      Details</b> (PixAI's hires pass) among the Generate tab's tuning chips (plain
                      generation settings, not workflows), and <b>Fix</b> on the Fixer sub-tab for
                      hands and faces.
                    </div>
                  </div>
                </div>
              )}
              {tab === "edit" && sub !== "edit" && (
                /* slab 3 under Fixer / Enhance -- the DC draws QUALITY here regardless of sub
                   (1522-1540: the EDIT model's Low/Medium/High + the image tab's switches --
                   content that is not tab-aware: the same editQuality state rides along
                   whichever sub-tab is up). REAL CAPABILITY (owner ruling 2026-08-16): a Fix
                   has no quality knob (/api/fix takes {source, boxes}, priced flat) and the art
                   filters have none (they composite at full resolution in the browser), so
                   showing the Edit model's segments here would offer a control that changes
                   nothing. The slab keeps the DC's heading and says so in the DC's own
                   no-knob line (1531-1533, 'Reference Pro has no quality knob — …' style). */
                <div className="mgdock-slab" style={{ animationDelay: "120ms" }}>
                  <div className="mgdock-lbl">QUALITY</div>
                  <div className="mgdock-editcopy">
                    {sub === "fixer"
                      ? "A Fix has no quality knob — PixAI repairs what is inside your boxes at one flat rate."
                      : "Art filters have no quality knob — they composite at the picture's full resolution, in your browser."}
                  </div>
                </div>
              )}
            </div>
            <div ref={setEditResultsEl} className="mgdock-editresults" />
          </div>

          <VideoTab visible={tab === "video"} prefillRequest={videoPrefill} drawerRef={videoRef} dock={videoDock} />
        </div>

        {/* ---- THE FOOTER (DC 1551-1591) -- at the DOCK level, AFTER the per-tab
             body, so it renders on EVERY tab: ▲ expand · the composer box · the
             cost stack + Generate. Image content is inline; Video / Edit / Fixer
             content arrives through the per-tab slots (portals, see the slot state
             above); Enhance's is inline too. genLabel per DC 3682-3684:
             '✦ Generate' / '✦ Generate video' / '✦ Edit' / '✦ Fix <kind>' /
             'Save to library'. ---- */}
        <div className="mgdock-foot">
          <ExpandToggle expanded={expanded} onToggle={() => setExpanded((v) => !v)} />

          <div ref={composerRef} className={"mgdock-composer" + (promptFocus ? " focus" : "")}
            style={{ "--mg-prompt-max": promptMax }}>
            {/* top row (DC 1557-1565): model pip · frame summary · spacer · ★ Snippets */}
            <div className="mgdock-composer-top">
              {tab === "image" && (
                <>
                  <button type="button" className={"mgdock-modelchip" + (m ? "" : " empty")}
                    onClick={() => { setFiltersOpen(false); setFlyKind("base"); setFlyOpen(!flyOpen); }}>
                    {m && m.thumb ? <img src={m.thumb} alt="" /> : <span className="mgdock-chipph" />}
                    <span>{modelShort}</span>
                  </button>
                  <span className="mgdock-frames">{frameSummary}</span>
                  {reuseFrom && (
                    <button type="button" className={"mgdock-reusefrom" + (reuseFrom.partial ? " warn" : "")}
                      onClick={() => setReuseFrom(null)}
                      title={reuseFrom.partial
                        ? "PARTIAL recipe from " + reuseFrom.tag + ": " + reuseFrom.partial + " — click to clear"
                        : "Prompt & core settings prefilled from run " + reuseFrom.tag + " — click to clear"}>
                      ↺ from {reuseFrom.tag}{reuseFrom.partial ? " ⚠" : ""} <span>&times;</span>
                    </button>
                  )}
                </>
              )}
              <div ref={setVideoTopEl} className="mgdock-slot" style={{ display: tab === "video" ? "contents" : "none" }} />
              <div ref={setEditTopEl} className="mgdock-slot" style={{ display: tab === "edit" && sub !== "enhance" ? "contents" : "none" }} />
              {tab === "edit" && sub === "enhance" && (
                <>
                  <span className="mgdock-modelchip static" title="Art filters — free, in your browser">
                    <span className="mgdock-chipph" /><span>Art filters</span>
                  </span>
                  <span className="mgdock-frames">free · composites in your browser</span>
                </>
              )}
              <span className="sp" />
              {/* DC 1564 -- the ★ Snippets toggle, right-aligned at the end of the row.
                  Only where there is a prompt to insert into (Fixer/Enhance have none). */}
              {snippetsAvail && (
                <button type="button" className={"mgdock-snipbtn" + (snippetsOpen ? " on" : "")}
                  onClick={() => setSnippetsOpen((v) => !v)}>★ Snippets</button>
              )}
            </div>

            {/* the prompt (DC 1566): the image draft here; the video contenteditable and
                the edit instruction portal into their slots; Fixer/Enhance carry a line
                of copy instead of an empty box */}
            {tab === "image" && (
              <textarea className="mgdock-prompt" rows={promptRows} value={s.prompt}
                placeholder="Describe your image…"
                onChange={(e) => set({ prompt: e.target.value })} />
            )}
            <div ref={setVideoPromptEl} className="mgdock-slot" style={{ display: tab === "video" ? "" : "none" }} />
            <div ref={setEditPromptEl} className="mgdock-slot" style={{ display: tab === "edit" && sub !== "enhance" ? "" : "none" }} />
            {tab === "edit" && sub === "enhance" && (
              <div className="mgdock-composer-msg">
                Filters need no prompt — open the panel, compare against the original, then save to your library.
              </div>
            )}

            {/* ★ Snippets open (DC 1567-1573): the WRAPPING chip row, mgSlab entrance.
                The real per-account store's affordances ride the same row: '+ save
                current' leads, a one-level Undo appears after a delete, each chip
                inserts on click and carries its own ×. */}
            {snippetsOpen && snippetsAvail && (
              <div className="mgdock-sniprow">
                <button type="button" className="mgdock-snip act"
                  disabled={tab === "image" && !s.prompt.trim()}
                  title="Save the current prompt as a snippet"
                  onClick={saveCurrentSnip}>+ save current</button>
                {snipUndo && (
                  <button type="button" className="mgdock-snip act" onClick={undoSnip}
                    title={"Restore “" + snipTrunc(snipUndo.text) + "”"}>↺ Undo delete</button>
                )}
                {snips === null ? (
                  <span className="mgdock-snipempty">loading…</span>
                ) : snips.length === 0 ? (
                  <span className="mgdock-snipempty">No saved snippets yet — build a prompt, then “+ save current”.</span>
                ) : (
                  snips.map((sn, i) => (
                    <span className="mgdock-snip" key={sn + " " + i}>
                      <button type="button" className="mgdock-snipins" title={"Insert: " + sn}
                        onClick={() => insertSnip(sn)}>{snipTrunc(sn)}</button>
                      <button type="button" className="mgdock-snipdel" title="Delete (Undo appears first in the row)"
                        onClick={() => delSnip(i)}>×</button>
                    </span>
                  ))
                )}
                {snipErr && <span className="mgdock-sniperr">⚠ {snipErr}</span>}
              </div>
            )}

            {/* NEGATIVE (DC 1574-1579): inside the composer, only while expanded. Image and
                Video only: the DC's composer is not tab-aware, but PixAI's instruct-edit
                params carry no negative prompt (editCore.js buildEditPayload) and the Fixer /
                art filters have no prompt at all -- real capability wins (owner ruling
                2026-08-16), so the Edit tab's composer never grows a NEGATIVE row. */}
            {expanded && (tab === "image" || tab === "video") && (
              <div className="mgdock-negrow">
                <span className="mgdock-lbl">NEGATIVE</span>
                {tab === "image" && (
                  <textarea className="mgdock-neg" rows={1} value={s.negative}
                    placeholder="lowres, text"
                    disabled={m && m.compat_neg === false}
                    onChange={(e) => set({ negative: e.target.value })} />
                )}
                <div ref={setVideoNegEl} className="mgdock-slot" style={{ display: tab === "video" ? "contents" : "none" }} />
              </div>
            )}
          </div>

          {/* right column (DC 1582-1590): the cost stack over the Generate button.
              CostBadge is THE cost renderer on every tab -- the DC's bare two-line
              stack is its `stack` presentation (count / balance are the host's own
              data; the card sentence stays the badge's). */}
          <div className="mgdock-gocol">
            {tab === "image" && (
              <>
                {/* idle here == no model (useGenerate clears the badge only when there is
                    no version_id to price), so the DC's nomodel sentence (3674) is the
                    idle hint -- via the badge's own hint API, never hand-written text */}
                <CostBadge ref={costRef} stack count={s.count} balance={balance}
                  hint="Pick a model to see the cost." />
                <button type="button" className={"mgdock-gen" + (gate || g.busy || prefillBusy ? " off" : "")}
                  disabled={!!gate || g.busy || prefillBusy}
                  title={prefillBusy ? "Restoring the recipe…"
                    : gate ? "Pick a model and write a prompt first" : "Submit — this spends credits or a card"}
                  onClick={() => { setReuseFrom(null); g.generate(loraCap); }}>
                  <span>&#10022; Generate</span>
                </button>
              </>
            )}
            <div ref={setVideoGoEl} className="mgdock-slot" style={{ display: tab === "video" ? "contents" : "none" }} />
            <div ref={setEditGoEl} className="mgdock-slot" style={{ display: tab === "edit" && sub !== "enhance" ? "contents" : "none" }} />
            {tab === "edit" && sub === "enhance" && (
              <>
                {/* DC 3673 costText for enhance: 'Free — art filters composite in your
                    browser.' -- NOT rendered as written: CostBadge is the one cost renderer
                    and its rule (inherited from loom-core's formatCostEstimate) is that a
                    displayed 'Free' / '0 credits' means ONLY a settled zero from the price
                    route; nothing was priced here (nothing is sent), so the badge stays in
                    its idle state with the DC's sentence minus the word. costSubLine (3680,
                    the balance) is the badge's own second line. Documented divergence. */}
                <CostBadge stack balance={balance} hint="Nothing to price — art filters composite in your browser." />
                {/* DC genLabel 'Save to library' (3683); genReady = editRefs.length > 0
                    (2874) -> gated on the shared source. Saving happens in the compare
                    overlay (it owns the chosen filter, its strength/angle and the POST), so
                    the footer action OPENS it -- never a second save path. The titles are
                    real copy: the DC's genTitle pair is image-gen wording (owner ruling). */}
                <button type="button" className={"mgdock-gen" + (editS.source ? "" : " off")}
                  disabled={!editS.source}
                  title={editS.source
                    ? "Compare and save in the art filters overlay — this opens it"
                    : "Pick a source image first"}
                  onClick={() => { setFlyOpen(false); setFiltersOpen(true); }}>
                  <span>Save to library</span>
                </button>
              </>
            )}
          </div>
        </div>
      </aside>

      {/* Floating overlays live OUTSIDE the aside: the dock's backdrop-filter
          makes it a containing block for fixed descendants, which would trap
          both panels inside its 22px-rounded clip. They stay inside the
          .mgx-dock-host wrapper, so the host's outside-click closer still
          counts them as "inside the dock". */}
      <ModelFlyout
        open={flyOpen} kind={flyKind} setKind={setFlyKind}
        baseType={m ? m.model_type : ""}
        value={m} selected={s.loras}
        onBasePick={onBasePick} onLoraPick={onLoraPick}
        onClose={() => setFlyOpen(false)}
      />
      {/* The art-filters compare overlay (DC 591-658): a full-viewport scrim + centred
          panel, so it no longer needs the dock's rect. It reads slab 1's SOURCE (DC 1513
          'Pick a source image above' -- the same editS.source Edit and the Fixer use; the
          overlay has no picker of its own). */}
      <FilterCompare open={filtersOpen} onClose={() => setFiltersOpen(false)}
        source={editS.source} onSendToEdit={sendToEdit} />
      {/* The run tooltip (DC 1594-1605): a SIBLING of the dock, never inside it -- the
          aside's transform: translateX(-50%) (+ the mgDockIn/Out transforms) would make
          it the containing block for position: fixed and re-anchor viewport coords into
          dock-local space. Same fragment as the flyout / compare overlay above. */}
      {open && <RunTip tip={runTip} />}
    </>
  );
}

/* Model-published restrictions REPLACE the field's default bounds (the classic's
   gateField); clamp on blur so a value the server would silently rewrite never
   reaches the payload unremarked. */
function clampField(raw, bounds, defMin, defMax) {
  if (raw === "") return "";
  const n = Number(raw);
  if (!isFinite(n)) return "";
  const min = bounds.min != null ? bounds.min : defMin;
  const max = bounds.max != null ? bounds.max : defMax;
  return String(Math.max(min, Math.min(max, n)));
}
