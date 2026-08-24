import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal, flushSync } from "react-dom";
import Banner from "./components/Banner.jsx";
import SeparatorBar from "./components/SeparatorBar.jsx";
import { LibraryBar } from "./components/FiltersPanel.jsx";
import Grid from "./components/Grid.jsx";
import GridContextMenu from "./components/GridContextMenu.jsx";
import SimilarModal from "./components/SimilarModal.jsx";
import Lightbox from "./components/Lightbox.jsx";
import DetailsView from "./components/DetailsView.jsx";
import HealthOverlay from "./components/HealthOverlay.jsx";
import DuplicateReviewOverlay from "./components/DuplicateReviewOverlay.jsx";
import MyArtOverlay from "./components/MyArtOverlay.jsx";
import PublishOverlay from "./components/PublishOverlay.jsx";
import TrainOverlay from "./components/TrainOverlay.jsx";
import ContestsOverlay from "./components/ContestsOverlay.jsx";
import ImportOverlay from "./components/ImportOverlay.jsx";
import ControlPanelOverlay from "./components/ControlPanelOverlay.jsx";
import ContactSheetOverlay from "./components/ContactSheetOverlay.jsx";
import FolioOverlay from "./components/FolioOverlay.jsx";
import AiToolsModal from "./components/AiToolsModal.jsx";
import GenerateDrawer from "./components/GenerateDrawer.jsx";
import PickerHost, { isPickerOpen } from "./components/PickerHost.jsx";
import ClaimModal from "./components/ClaimModal.jsx";
import useClaimModal from "./hooks/useClaimModal.js";
import "./styles/shell.css";
import {
  fetchAccount, fetchCollections,
  apiGet, apiPost, downloadZipForm, rateImage, resolveVideoIds, rebuildPoster,
} from "./api.js";
import useLibrary, { filterQueryString } from "./hooks/useLibrary.js";
import { buildUrl, readPage, readImage } from "./gen/urlState.js";

/* ============================ THE APP SHELL =================================
   Redesigned per the Frontend Gallery DC (design_handoff_moonglade_suite):

     sticky header  = Banner (hero/slim) + SeparatorBar (nav spine, toggles,
                      credits chip) — Banner.jsx / SeparatorBar.jsx / NavSpine.jsx
     main           = Grid or DetailsView (existing components, new spot)
     dock host      = GenerateDrawer wrapped in the dock-host contract: starts
                      CLOSED, Generate buttons are TRUE TOGGLES, outside-click
                      ignores [data-dock-toggle], deep links #image|#edit|#video
                      open it on that tab, close is DEFERRED 360ms (mgDockOut
                      window) — and the drawer itself is NEVER unmounted (the
                      shared video component owns poll timers for charged tasks).

   MOUNT POINTS left for the parallel workstreams:
   - LibraryBar refit: renders via Banner's `libraryBar` slot (Strip today) and
     `slimSlot` (empty today — the slim row's compact search goes there).
   - Overlays (My Art/Contests/Health/Publish/Train/Import + Folio): `overlay`
     state + openOverlay() below; render the overlay host where marked. Esc
     already closes the overlay BEFORE the dock (capture-phase handler).
   - GenerateDock refit: the .mgx-dock-host wrapper + open/closing classes are
     the motion hooks; toggleDock/openDock/closeDock are the host verbs; the
     separator bar's compact <CostBadge> is its (dormant) price chip.
   - Grid refit: receives `thumb` (SIZE slider) — also exposed as --thumb on
     <main>; shell.css maps it onto the existing .grid columns until then. */

export default function App({ boot }) {
  // ?page=N on first load (#31, "Where the Refit Broke" #7): the classic addressed
  // pages in the URL; the refit hardcoded page 1. Read once, handed to the hook.
  const [initialPage] = useState(() => readPage(window.location.search));
  /* ---- session stacking (#34 direction B): the "Stack sessions" toggle. When
     on, /api/next/library folds every task into ONE cover card (a multi-task
     dial-in series, or a lone batch's siblings). Persisted like `layout`
     (mg_gallery_group), default OFF so ungrouped mode is untouched for anyone who
     never opts in. Declared BEFORE useLibrary because the hook takes it -- flipping
     it re-fetches page 1 through load's dep on group. ---- */
  const [group, setGroupState] = useState(() =>
    localStorage.getItem("mg_gallery_group") === "series" ? "series" : "");
  const setGroup = (on) => {
    const v = on ? "series" : "";
    localStorage.setItem("mg_gallery_group", v);
    setGroupState(v);
  };
  /* The library state, kept whole as `lib` AND spread for this file's own use. The whole
     object is what surfaces built ON the library take (LibraryBar); the spread is what the
     shell reads directly. One source, two views of it -- not two copies. */
  const lib = useLibrary({ initialPage, group });
  const {
    // filters
    media, shelf, perPage, query, applied, adv, setAdv,
    // data
    items, setItems, total, page, pages, loading,
    // load + filter verbs
    load, applyAdvanced,
    // selection
    selectMode, selected, setSelected, toggleSelected,
  } = lib;
  const [account, setAccount] = useState(null);
  const refreshAccount = () => fetchAccount().then(setAccount);
  const claimModal = useClaimModal(account, refreshAccount);
  const [collections, setCollections] = useState(boot.collections || []);
  // ui -- blur shares the classic gallery's localStorage key on purpose: one
  // setting, both surfaces, exactly the classic semantics (all thumbs 16px,
  // flagged 28px, hover reveals).
  const [blur, setBlurState] = useState(
    () => localStorage.getItem("gallery_privacy_blur") === "1"
  );
  const setBlur = (v) => {
    localStorage.setItem("gallery_privacy_blur", v ? "1" : "");
    setBlurState(v);
  };
  const [lbIndex, setLbIndex] = useState(null);

  /* ---- banner hero/slim (the slim TOGGLE lives in the separator bar; this
     replaces the old scroll-collapse mechanism). Persisted: a manual state the
     owner picked should survive a reload. ---- */
  const [slim, setSlimState] = useState(
    () => localStorage.getItem("mg_banner_slim") === "1"
  );
  const setSlim = (v) => {
    localStorage.setItem("mg_banner_slim", v ? "1" : "");
    setSlimState(v);
  };

  /* ---- SIZE slider: thumb size for the grid; max = 4-across of the grid's
     real width (DC formula), measured live. Persists under mg_gallery_density
     (drift §48 — the Custom Slider density control); reads the legacy mg_thumb
     key as a fallback so a size saved before the rename survives. ---- */
  const [thumb, setThumbState] = useState(() => {
    const raw = localStorage.getItem("mg_gallery_density") || localStorage.getItem("mg_thumb");
    const v = parseInt(raw || "", 10);
    return isFinite(v) && v >= 152 ? v : 210;
  });
  const setThumb = (v) => {
    localStorage.setItem("mg_gallery_density", String(v));
    setThumbState(v);
  };

  /* ---- gallery layout (drift §46/§47): masonry (current) · grid · hero ·
     timeline. Persists in mg_gallery_layout, default masonry. Selecting only
     re-lays the SAME cards Grid already holds — no refetch. ---- */
  const [layout, setLayoutState] = useState(() => {
    const v = localStorage.getItem("mg_gallery_layout");
    return ["masonry", "grid", "hero", "timeline"].includes(v) ? v : "masonry";
  });
  const setLayout = (v) => {
    localStorage.setItem("mg_gallery_layout", v);
    setLayoutState(v);
  };
  const [thumbMax, setThumbMax] = useState(320);
  const mainRef = useRef(null);
  useEffect(() => {
    const el = mainRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      setThumbMax(Math.max(200, Math.floor((el.clientWidth - 36 - 33) / 4)));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Timeline's internal-scroll pane sizes off the LIVE sticky-chrome height, not a hardcoded
  // guess: the banner swings clamp(150px,22vw,300px) <-> slim 62px, and slim is OFF by default,
  // so a fixed 150px let the window scroll and slid the sticky band headers behind the banner
  // (gallery-build-review, major). Publish the header height as --mgx-chrome-h; grid.css sizes
  // the timeline pane to calc(100vh - var(--mgx-chrome-h)) so its sticky headers clear the chrome.
  const headerRef = useRef(null);
  useEffect(() => {
    const el = headerRef.current;
    if (!el) return;
    const apply = () => document.documentElement.style.setProperty("--mgx-chrome-h", el.offsetHeight + "px");
    apply();
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", apply);
      return () => window.removeEventListener("resize", apply);
    }
    const ro = new ResizeObserver(apply);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  /* ---- live-run signal for the banner spinner + activity cluster. Counted
     from the shared drawer's mg-submit/mg-result events (the only begin/end
     pair any producer emits today). The image path (useGenerate) has no begin
     event, so its runs don't tick this — the RunsReel workstream owns the
     richer signal and can replace this counter wholesale. ---- */
  const [running, setRunning] = useState({ count: 0, pct: null });

  /* ---- overlays (drift §16): six nav destinations open floating overlays.
     State + verb live here; the surfaces are the overlays workstream's. ---- */
  const [overlay, setOverlay] = useState(null);
  // Which image a cross-page "☁ Publish" click handed to the panel (Lightbox /
  // Details). Empty when Publish is opened from the nav -- the panel then starts
  // with its own picker instead of a pre-chosen image.
  const [publishFor, setPublishFor] = useState("");
  const openPublish = useCallback((mid) => { setPublishFor(mid || ""); setOverlay("publish"); }, []);
  const overlayRef = useRef(null);
  useEffect(() => { overlayRef.current = overlay; });
  const openOverlay = useCallback((key) => {
    setOverlay(key);
  }, []);
  // Contact Sheet's two entry points hand it different targets: the Actions
  // menu freezes the explicit selection (ids); the Advanced flyout prints the
  // current collection view (collectionName) -- the same ids-or-collection
  // contract /api/contact-sheet already takes. Neither reads live state after
  // opening, so what prints matches what was on screen when it was opened.
  const [contactSheetTarget, setContactSheetTarget] = useState({ ids: [], collectionName: "" });
  const openContactSheet = useCallback((ids, collectionName) => {
    setContactSheetTarget({ ids: ids || [], collectionName: collectionName || "" });
    setOverlay("contactsheet");
  }, []);
  // Bridge §4->§5 hand-off lives in requestScene (below, beside requestEdit/Video/Remix):
  // picking a scene in the AI Tools nav modal closes the modal and opens the gen drawer onto
  // that scene's generator, riding the same one-shot genRequest contract the other hand-offs use.
  // Esc closes the overlay FIRST (capture beats the drawer's own Esc ladder) --
  // EXCEPT where a layer on top owns its own Escape ladder: the Control Panel
  // closes its Users/Trash sub-overlay first and deliberately refuses while the
  // power modal is up, and an open gallery picker closes itself (its listener
  // lives in the web component's connectedCallback). Capture-closing over those
  // nuked the whole layer stack and made their handlers dead code. Found by the
  // 2026-08-07 branch review.
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape" || !overlayRef.current) return;
      if (overlayRef.current === "panel") return;   // panel runs its own ladder
      if (isPickerOpen()) return;                   // picker dismisses itself
      e.stopPropagation();
      setOverlay(null);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, []);

  /* ---- the Generate dock HOST (DC §6 host behavior; the drawer→dock reshell
     itself is the GenerateDock workstream). Starts CLOSED; open/close are a
     true toggle; close defers 360ms (the mgDockOut window) so exit motion has
     a mounted element to run on. The drawer under it hides, never unmounts. */
  const [dockOpen, setDockOpen] = useState(false);
  const [dockClosing, setDockClosing] = useState(false);
  const dockStateRef = useRef({ open: false, closing: false });
  useEffect(() => { dockStateRef.current = { open: dockOpen, closing: dockClosing }; });
  const dockTimer = useRef(null);
  const dockHostRef = useRef(null);
  const closeDock = useCallback(() => {
    setDockClosing(true);
    clearTimeout(dockTimer.current);
    dockTimer.current = setTimeout(() => {
      setDockOpen(false);
      setDockClosing(false);
    }, 360);
  }, []);
  const openDock = useCallback(() => {
    clearTimeout(dockTimer.current);
    setDockOpen(true);
    setDockClosing(false);
  }, []);
  const toggleDock = useCallback(() => {
    const st = dockStateRef.current;
    if (st.open && !st.closing) closeDock();
    else openDock();
  }, [closeDock, openDock]);

  /* Outside-click closes the dock — but never a click on a [data-dock-toggle]
     (the toggle buttons own their own open/close and must not race it), and
     never while the shared picker overlay is up (it renders OUTSIDE the dock
     host). Capture-phase mousedown, matching the DC. Today the drawer's own
     scrim (inside the host) swallows most page clicks; when the dock refit
     drops the scrim, this closer is already the contract. */
  useEffect(() => {
    const onDown = (ev) => {
      const st = dockStateRef.current;
      if (!st.open || st.closing) return;
      if (ev.target.closest && ev.target.closest("[data-dock-toggle]")) return;
      if (isPickerOpen()) return;
      const host = dockHostRef.current;
      if (host && !host.contains(ev.target)) closeDock();
    };
    window.addEventListener("mousedown", onDown, true);
    return () => window.removeEventListener("mousedown", onDown, true);
  }, [closeDock]);

  /* Deep links: #image | #edit | #video open the dock on that tab, then the
     hash is stripped (history.replaceState) so reloads don't re-trigger.
     #edit rides the drawer's one-shot request contract with an empty source
     (safe: the drawer skips the source hand-off for a falsy mid). #video rides the same
     contract -- the drawer now skips the i2v prefill for a midless request,
     so the deep link lands on the Video tab with clean slots
     in the shared video component — the GenerateDock retab owns fixing that. */
  useEffect(() => {
    const hash = (window.location.hash || "").replace("#", "");
    if (hash !== "image" && hash !== "edit" && hash !== "video") return;
    openDock();
    if (hash === "edit") setGenRequest({ tab: "edit", mid: "", nonce: Math.random() });
    else if (hash === "video") setGenRequest({ tab: "video", mid: "", nonce: Math.random() });
    try {
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    } catch { /* hash simply stays; harmless */ }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  /* The Details view -- "the layer deeper" (owner, 2026-07-30), a real
     bookmarkable URL via the History API rather than a modal-only state
     swap, matching classic's genuinely separate /image/<mid> page. Reads
     ?image= on first load so a shared/bookmarked link opens straight there;
     back/forward (popstate) stays in sync since pushState never fires it. */
  const [detailsFor, setDetailsFor] = useState(() => readImage(window.location.search));
  /* The ONE history writer (gen/urlState.js; #31 "Where the Refit Broke" #7).
     Every pushState/replaceState in the shell goes through here, so ?page= and
     ?image= can never overwrite each other: the builder patches only the keys it
     is handed and keeps the rest of the current query. closeDetails() used to
     push a bare "/" -- which threw the page the grid was on away the moment the
     owner closed a picture. A write that would not change the address is skipped
     (no duplicate history entries). */
  const setUrl = useCallback((patch, replace) => {
    const url = buildUrl(patch, window.location.search, window.location.pathname);
    if (url === window.location.pathname + window.location.search) return;
    try {
      if (replace) window.history.replaceState({}, "", url);
      else window.history.pushState({}, "", url);
    } catch { /* no History API (sandboxed frame): state still updates, only the address lags */ }
  }, []);
  /* The locked Direction C morph (docs/DECISIONS.md, artifact 477b4655): the
     image the owner was already looking at slides/resizes into the Details
     hero frame in place, via the native View Transitions API rather than a
     hand-rolled animation -- both ends carry the same view-transition-name
     ("vt-reveal": Lightbox.jsx's stage image, DetailsView.jsx's placard-frame).
     flushSync is required here -- without it React's own batching would defer
     the state update past the transition callback, and the browser would
     capture identical "before"/"after" snapshots. Feature-detected: browsers
     without support (pre-111 Firefox/Safari) just get the plain instant swap
     they already had. */
  const openDetails = (mid) => {
    const commit = () => {
      setLbIndex(null);
      setUrl({ image: mid });
      setDetailsFor(mid);
    };
    if (document.startViewTransition) document.startViewTransition(() => flushSync(commit));
    else commit();
  };
  const closeDetails = () => {
    setUrl({ image: null });   // keeps ?page=N -- the grid underneath is still on it
    setDetailsFor(null);
  };
  /* Back/forward re-read BOTH params: the image (as before) and the page -- a
     ?page= that differs from the grid's current page loads it. Refs, because the
     listener mounts once and load's identity follows the filters. */
  const pageRef = useRef(page);
  const loadRef = useRef(load);
  useEffect(() => { pageRef.current = page; loadRef.current = load; });
  useEffect(() => {
    const onPop = () => {
      setDetailsFor(readImage(window.location.search));
      const p = readPage(window.location.search);
      if (p !== pageRef.current) loadRef.current(p, true);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  /* And the address follows the grid the other way round: whenever the loaded
     page settles somewhere the URL doesn't say -- a filter/search/sort change or
     a finished generation resetting to 1, the Lightbox stepping across a page
     boundary -- mirror it with replaceState (no history entry; nobody navigated).
     The URL never claims a page the grid isn't showing. Waits for the first load
     to land (total != null) so a fresh ?page=3 visit isn't clobbered by the
     page-1 default while its request is still in flight. */
  useEffect(() => {
    if (loading || total == null) return;
    setUrl({ page }, true);
  }, [page, loading, total, setUrl]);
  /* A user page change is a real navigation: pushState, then load. */
  const goToPage = (p) => {
    setUrl({ page: p });
    load(p, true);
  };
  const filterByModel = (name) => {
    closeDetails();
    setAdv((old) => ({ ...old, model: name }));
  };
  const filterByBatch = (batch) => {
    closeDetails();
    setAdv((old) => ({ ...old, batch, series: "" }));
  };
  /* Open a SERIES stack (#34 direction B) -- the mirror of filterByBatch: set the
     `series` drill-down to the sid, which the backend resolves to the series'
     member task_ids (?series=<sid>). load() suppresses the grouping fold while a
     drill-down is active, so this lands on the series' members ungrouped; clearing
     the filter (or Clear) snaps back to the still-lit stacked grid. */
  const filterBySeries = (series) => {
    closeDetails();
    setAdv((old) => ({ ...old, series, batch: "" }));
  };

  /* Generation completions refresh the library + credits chip.
     THREE channels, because there are three producers:
     - mg-gen-done: our own image submit path (useGenerate);
     - mg-submit:   the SHARED video drawer accepting a task;
     - mg-result:   that drawer finishing, which is when credits actually moved.
     The same submit/result pair also ticks the shell's live-run counter.
     NO Jobs.register here (2026-08-23). This listener used to be what registered a
     video with the Job Tracker, which quietly made tracking a property of WHICH SHELL
     the drawer happened to be mounted in -- and AppMobile.jsx has no such listener, so
     a video started from the phone never reached /api/jobs, the Activity tray or the
     orphan sweep. The drawer now submits through gen/submitTask.js, whose Jobs.track
     registers on the way past; registration belongs to the submit road, not the shell. */
  useEffect(() => {
    const refresh = () => { load(1, true); fetchAccount().then(setAccount); };
    // mg-gen-done also nudges the Folio of Honors to check-and-celebrate any newly
    // earned achievement -- this is the only "a real action just completed" hook Ach
    // has outside a hard page load, so it belongs here alongside the grid/account
    // refresh. Guarded like window.Toast/window.Jobs elsewhere in this file.
    const onGenDone = () => { refresh(); if (window.Ach) window.Ach.check(); };
    const onSubmit = () => {
      setRunning((r) => ({ ...r, count: r.count + 1 }));
    };
    const onResult = () => {
      refresh();
      if (window.JobsCard) window.JobsCard.refresh();
      setRunning((r) => ({ ...r, count: Math.max(0, r.count - 1) }));
    };
    window.addEventListener("mg-gen-done", onGenDone);
    document.addEventListener("mg-submit", onSubmit);
    document.addEventListener("mg-result", onResult);
    return () => {
      window.removeEventListener("mg-gen-done", onGenDone);
      document.removeEventListener("mg-submit", onSubmit);
      document.removeEventListener("mg-result", onResult);
    };
  }); // eslint-disable-line react-hooks/exhaustive-deps

  /* Two thumbnail links live outside this component's own tree (the notify system's
     ActivityTray and the shared VideoDrawer, both portaled/deeply nested with no direct
     prop path to openDetails) and used to be bare <a href="/next?image=..."> anchors --
     a REAL full-page navigation on click, the one path in the app that never got the
     preventDefault+SPA-navigate treatment every other Details link already has. Found
     live (owner, 2026-08-09): a finished job's thumbnail took him to a blank page. Fixed
     at the source in both components (they now dispatch this event instead of navigating);
     this listener is what actually opens Details for it, same bus pattern as mg-submit/
     mg-result above. */
  useEffect(() => {
    const onOpenDetails = (e) => {
      const mid = e.detail && e.detail.mid;
      if (mid) openDetails(mid);
    };
    document.addEventListener("mg-open-details", onOpenDetails);
    return () => document.removeEventListener("mg-open-details", onOpenDetails);
  }, []);

  useEffect(() => { fetchAccount().then(setAccount); }, []);

  /* The Konami Code easter egg, ported from the classic BASE_HTML (its CSS/JS
     never shipped to /next -- owner QA: "the Konami code is broken"; it wasn't,
     it was simply absent). Same sequence, same beacon, same visuals; styles
     live in styles.css. Mounted once, globally. */
  useEffect(() => {
    const seq = [38, 38, 40, 40, 37, 39, 37, 39, 66, 65];
    let pos = 0, busy = false;
    const onKey = (e) => {
      pos = e.keyCode === seq[pos] ? pos + 1 : (e.keyCode === seq[0] ? 1 : 0);
      if (pos !== seq.length) return;
      pos = 0;
      if (busy) return;
      busy = true;
      // The ee_* assets are SEALED to The Konami Code (the unlock-split
      // enforcement, 2026-08-13) and this beacon is what earns it -- so the
      // visuals wait for the beacon to land, or the very first trigger races
      // its own unlock and the art 404s. Fail-soft on a beacon error: the
      // stars/toast still play (the img/audio just may not resolve).
      // Earn the feat, THEN read its now-unmasked flavor from /api/achievements. The
      // Konami punchline lives in the SEALED roster (the-konami-code's desc), not in this
      // public source, so a clone can't read the egg's payoff before finding it -- a
      // failed read answers {error}, and the sub-line falls back to its generic string.
      apiPost("/api/ach-event", { event: "konami" })
        .then(() => apiGet("/api/achievements"))
        .then((data) => {
        const glyphs = ["✦", "✧", "★", "✪", "✺"];
        const stars = [];
        for (let i = 0; i < 46; i++) {
          const s = document.createElement("div");
          s.className = "ee-star";
          s.textContent = glyphs[i % glyphs.length];
          s.style.left = Math.random() * 100 + "vw";
          s.style.fontSize = 13 + Math.random() * 24 + "px";
          s.style.animationDuration = 2.2 + Math.random() * 2.6 + "s";
          s.style.animationDelay = Math.random() * 1.8 + "s";
          document.body.appendChild(s);
          stars.push(s);
        }
        const scrim = document.createElement("div");
        scrim.className = "ee-scrim";
        document.body.appendChild(scrim);
        const nel = document.createElement("img");
        nel.className = "ee-nel";
        nel.src = "/branding/ee_nelstarfall.png";
        nel.onerror = () => nel.remove();
        document.body.appendChild(nel);
        // Built with DOM methods, not innerHTML. The greeting is a fixed literal; the
        // punchline is the SEALED roster's desc for the-konami-code, set via textContent
        // (so fetched data can never inject markup) -- it is not in this public source to spoil.
        const toast = document.createElement("div");
        toast.className = "ee-toast";
        toast.appendChild(document.createTextNode("✺ Elune-adore, Nelnamara ✺"));
        const sub = document.createElement("div");
        sub.style.cssText = "font-size:12.5px;color:var(--subtext);margin-top:7px;";
        const feat = data && (data.achievements || []).find((a) => a.id === "the-konami-code");
        sub.textContent = (feat && feat.desc) || "A hidden power stirs in the Athenaeum.";
        toast.appendChild(sub);
        document.body.appendChild(toast);
        let cast, loop;
        try { cast = new Audio("/branding/ee_starfall_cast.ogg"); cast.volume = 0.7; cast.play().catch(() => {}); } catch {}
        try { loop = new Audio("/branding/ee_starfall_loop.ogg"); loop.loop = true; loop.volume = 0.35; loop.play().catch(() => {}); } catch {}
        setTimeout(() => {
          document.querySelectorAll(".ee-star,.ee-toast,.ee-nel,.ee-scrim").forEach((n) => n.remove());
          try { loop && loop.pause(); } catch {}
          try { cast && cast.pause(); } catch {}
          busy = false;
        }, 7000);
      });
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  /* ---- bulk Actions: the classic flows, confirm texts verbatim ---- */
  const selIds = [...selected];
  const afterMutation = async () => {
    setSelected(new Set());
    load(1, true);
    const c = await fetchCollections();
    if (c) setCollections(c);
  };
  const actions = {
    addCollection: async () => {
      const name = window.prompt(
        "Add " + selIds.length + " image(s) to which collection? (a name; files are NOT moved)");
      if (name === null || !name.trim()) return;
      const d = await apiPost("/api/collection",
        { action: "add", collection: name.trim(), media_ids: selIds });
      if (d.error) { window.alert(d.error); return; }
      afterMutation();
    },
    removeCollection: async (name) => {
      if (!name) return;
      if (!window.confirm(
        "Remove " + selIds.length + " item(s) from the collection “" + name + "”?\n\n" +
        "Only the collection label is removed — no files are deleted and nothing leaves your PixAI account.")) return;
      const d = await apiPost("/api/collection",
        { action: "remove", collection: name, media_ids: selIds });
      if (d.error) { window.alert(d.error); return; }
      afterMutation();
    },
    sendCast: async () => {
      // cast is images -- videos are filtered out, unknown ids resolved like the classic
      const known = new Map(items.map((it) => [it.media_id, it.is_video]));
      const vids = await resolveVideoIds(selIds, known);
      const keep = selIds.filter((mid) => !vids.has(mid));
      if (!keep.length) return;
      setSelected(new Set()); // selection is consumed into the Loom cast
      window.location.href = "/loom?cast=" + encodeURIComponent(keep.join(","));
    },
    // Native React overlay + native print (window.print(), scoped by @media
    // print) -- NOT a hand-off to the classic /contact-sheet page. That route
    // stays for classic's own use only; the new front door never opens it.
    printSheet: () => openContactSheet(selIds),
    // Advanced flyout's "🖶 Contact sheet" -- prints the current collection
    // view rather than an explicit selection; falls back to /api/contact-
    // sheet's own "Recent" default when not viewing a collection.
    printCollection: () => openContactSheet(null, shelf),
    // Saved-views WRITE + filtered CSV export both serialize the view the FLYOUT shows.
    // The flyout drafts the advanced filters locally and only commits them on Apply, so
    // Save/Export must serialize the DRAFT adv (passed in), NOT App's committed `adv` --
    // otherwise setting a filter and hitting Save without Apply silently saves the old
    // state (2026-08-07 port review). q/media/shelf/perPage aren't drafted in the flyout,
    // so those come from App's applied state. `style`: "library" (round-trips via
    // parsePresetQuery) or "export" (from_year/from_month, what _filters_from_args reads).
    buildViewQuery: (draftAdv, style) =>
      filterQueryString({ applied, media, shelf, adv: draftAdv || adv, perPage }, style),
    saveView: (name, query) => apiPost("/api/view-presets", { name, query }),
    deleteView: (name) => apiPost("/api/view-presets", { delete: name }),
    downloadZip: () => downloadZipForm(selIds),
    replacePrompt: async () => {
      const find = window.prompt(
        "Find this text in the prompts of " + selIds.length + " selected image(s):");
      if (find === null || find === "") return;
      const repl = window.prompt('Replace "' + find + '" with: (leave blank to delete it)');
      if (repl === null) return;
      if (!window.confirm('Replace "' + find + '" with "' + repl + '" across ' +
        selIds.length + " prompt(s)? This edits catalog.db.")) return;
      const d = await apiPost("/api/replace-prompts",
        { find, replace: repl, media_ids: selIds });
      if (d.error) { window.alert(d.error); return; }
      afterMutation();
    },
    deleteLocal: async () => {
      if (!window.confirm(
        "Remove " + selIds.length + " image" + (selIds.length !== 1 ? "s" : "") +
        " from the local catalog? Files move to the _deleted/ folder (recoverable); the cloud task is untouched.")) return;
      const d = await apiPost("/api/delete-local", { media_ids: selIds });
      if (d.error) { window.alert(d.error); return; }
      afterMutation();
    },
    deleteCloud: async (ids) => {
      // The typed gate, unchanged: the preview makes the consequence visible,
      // it does not replace the guard.
      const typed = window.prompt("This permanently deletes from PixAI. Type DELETE to confirm:");
      if (typed !== "DELETE") { window.alert("Cancelled."); return; }
      const d = await apiPost("/api/delete-tasks", { media_ids: ids });
      if (d.error) { window.alert(d.error); return; }
      afterMutation();
    },
  };

  // Contest "☆ Shortlist" -- re-implements the classic contest-shortlist branch
  // (2026-08-02) on the React Contests overlay: stage the gallery's current
  // selection into a collection named for the contest. Reuses the exact same
  // /collection-add plumbing addCollection uses, just with the name pre-filled
  // from the contest's title + end date. No new backend (same as the classic
  // version -- zero new surface).
  const shortlistContest = async (contest) => {
    if (!selIds.length) {
      window.alert("Select one or more images in the gallery first (check the boxes), "
        + "then open Contests and click Shortlist.");
      return;
    }
    const ends = contest.end_at ? " (ends " + String(contest.end_at).slice(0, 10) + ")" : "";
    const suggested = "Contest: " + (contest.title || "(untitled)") + ends;
    const name = window.prompt("Add " + selIds.length + " image(s) to which collection?", suggested);
    if (name === null || !name.trim()) return;
    const d = await apiPost("/api/collection",
      { action: "add", collection: name.trim(), media_ids: selIds });
    if (d.error) { window.alert(d.error); return; }
    afterMutation();
  };

  const rate = async (mid, value) => {
    // optimistic; the server clamps 0-5 and answers the stored value
    setItems((old) => old.map((it) => (it.media_id === mid ? { ...it, rating: value } : it)));
    try {
      await rateImage(mid, value);
    } catch {
      /* a failed rate leaves the optimistic value; the next load corrects it */
    }
  };

  /* Lightbox "Edit"/"To Video" -> the dock, matching classic's
     lbEdit()/lbVideo() (close the lightbox, then open the dock already on
     the right tab with the source loaded). genRequest is a one-shot
     instruction: a fresh object (nonce included) every time, so asking for
     the SAME image twice in a row still re-fires the drawer's effect. */
  const [genRequest, setGenRequest] = useState(null);
  const requestEdit = (mid) => {
    setLbIndex(null);
    openDock();
    setGenRequest({ tab: "edit", mid, nonce: Math.random() });
  };
  const requestVideo = (mid, thumb) => {
    setLbIndex(null);
    openDock();
    setGenRequest({ tab: "video", mid, thumb, nonce: Math.random() });
  };
  /* Remix (issue #4): the picture's FULL recipe -- prompt/negative/size/steps/
     cfg/seed/model, and LoRAs by exact version id -- prefilled into the Image
     tab. Prefill only; generating stays a human click. */
  const requestRemix = (mid) => {
    setLbIndex(null);
    openDock();
    setGenRequest({ tab: "remix", mid, nonce: Math.random() });
  };
  /* Bridge §5: a scene picked in the "✦ AI Tools" nav modal -- close the modal, open the dock,
     and hand the drawer the picked scene so it lands on its scene generator. Same one-shot
     genRequest shape as the Edit/Video/Remix hand-offs (a fresh nonce re-fires for the same
     scene twice). */
  const requestScene = (scene) => {
    setOverlay(null);
    openDock();
    setGenRequest({ tab: "scene", scene, nonce: Math.random() });
  };

  // Grid right-click context menu (the 5 classic actions; owner picked all five).
  const [ctxMenu, setCtxMenu] = useState(null);     // {mid, thumb, x, y} | null
  const [similarFor, setSimilarFor] = useState(null); // media_id | null
  const openContextMenu = (mid, thumb, x, y, isVideo) => setCtxMenu({ mid, thumb, x, y, isVideo });
  const ctxActions = {
    onEdit: requestEdit,
    onVideo: requestVideo,
    onRemix: requestRemix,
    onSimilar: (mid) => setSimilarFor(mid),
    onCopyId: (mid) => { try { navigator.clipboard.writeText(String(mid)); } catch { /* no-op */ } },
    onDetails: openDetails,
    // #28: rebuild a video's poster straight from the grid (the menu gates this on
    // target.isVideo). Same route + toast as Image Details' "Rebuild poster" button.
    onRebuildPoster: (mid) => rebuildPoster(mid).then((d) => {
      if (window.Toast) window.Toast.show(d && d.ok
        ? { kind: "ok", title: "Poster rebuilt" }
        : { kind: "err", title: "Couldn't rebuild the poster", msg: (d && d.error) || "" });
    }),
  };
  /* ✧ Similar from the Lightbox's chip or Details' "see all N" NAVIGATES here: the viewer
     (and the record) close and the gallery's own lookalike set -- the same SimilarModal the
     grid's right-click "Find similar" opens, over the grid -- takes over. Lightbox.dc.html:354
     sends Similar to Frontend Gallery.dc.html and Image Details.dc.html:127-140 keeps only
     the inline 8-strip in the record; the refit had both stacking the modal on the open
     surface instead ("Where the Refit Broke" #6). */
  const showSimilar = (mid) => {
    setLbIndex(null);
    if (detailsFor) closeDetails();
    setSimilarFor(mid);
  };

  const dockActive = dockOpen && !dockClosing;

  /* Grid arrow-key navigation (#31, Refit #7) only while the grid is the top
     layer: no lightbox, no Details, no nav overlay, no dock, no context menu or
     Similar modal -- each of those owns (or must not lose) the arrow keys. */
  const gridKeys = lbIndex == null && !detailsFor && !overlay && !ctxMenu
    && !similarFor && !dockActive && !claimModal.open;

  /* BUG FIX 2026-08-04: this object was previously an inline literal at
     DetailsView's own JSX call site. A fresh object every render meant a
     new reference every time regardless of whether any value inside it
     actually changed -- and useImageDetails.js's fetch effect depends on
     `advParams` by reference ([mediaId, advParams]), so it re-fired on
     every single render: setState -> re-render -> new advParams object ->
     effect fires again -> setState -> ... An infinite loop, hammering
     GET /api/next/detail/<mid> continuously and never settling out of
     `loading`, which is what actually produced the reported stuck-
     Loading/rapid-flash bug (reproduced live: ~1000 identical requests in
     a few seconds). useMemo keyed on the real underlying values fixes it --
     the reference only changes when a value inside it actually does. */
  const detailsAdvParams = useMemo(() => ({
    q: applied, media, collection: shelf,
    sort: adv.sort !== "newest" ? adv.sort : "", rating_min: adv.ratingMin || "",
    model: adv.model, lora: adv.lora, from: adv.dateFrom, to: adv.dateTo,
    source: adv.source, tag: adv.tag, published: adv.publishedOnly ? "1" : "",
  }), [applied, media, shelf, adv.sort, adv.ratingMin, adv.model, adv.lora,
      adv.dateFrom, adv.dateTo, adv.source, adv.tag, adv.publishedOnly]);

  return (
    <div className="app">
      {/* Banner + separator ride together in one sticky band. The old
          collapsing-sticky mg-head is retired: hero/slim is now an explicit
          state, toggled from the separator bar. */}
      <header className="mgx-hdr" ref={headerRef}>
        <Banner
          boot={boot}
          slim={slim}
          running={running}
          dockOpen={dockActive}
          onToggleDock={toggleDock}
          onFolio={() => openOverlay("folio")}
          libraryBar={
            <LibraryBar
              lib={lib}
              boot={boot}
              actions={actions}
              collections={collections}
              layout={layout} setLayout={setLayout}
              group={group} setGroup={setGroup}
            />
          }
        />
        <SeparatorBar
          boot={boot} account={account}
          slim={slim} onToggleSlim={() => setSlim(!slim)}
          blur={blur} onToggleBlur={() => setBlur(!blur)}
          thumb={thumb} thumbMax={thumbMax} onThumb={setThumb}
          running={running}
          dockOpen={dockActive} onToggleDock={toggleDock}
          onOverlay={openOverlay}
          onClaim={claimModal.claim} claiming={claimModal.claiming}
        />
      </header>

      <main ref={mainRef} className="mgx-main" style={{ "--thumb": thumb + "px" }}>
        {detailsFor ? (
          /* PORTALED to document.body -- NOT rendered inline in <main>. .mgx-main is
             position:relative + z-index:1, which creates a stacking context that CAPS
             any child at layer 1 no matter its own z-index -- so .detail-wrap's fixed
             inset-0 z-40 takeover painted UNDER the sticky header's z-7 banner (the
             "details overridden by the banner" bug, owner-reported 2026-08-08; a DOM
             stacking-context walk found the trap). Same lesson/fix as
             ContactSheetOverlay's portal (docs/DECISIONS.md, 2026-08-02). */
          createPortal(
            <DetailsView
              mediaId={detailsFor} onClose={closeDetails} onNavigate={openDetails}
              onRate={rate} onEdit={requestEdit} onRemix={requestRemix} onVideo={requestVideo} onPublish={openPublish}
              onDeleted={() => { closeDetails(); load(1, true); }}
              onFilterByModel={filterByModel} onFilterByBatch={filterByBatch}
              advParams={detailsAdvParams}
              items={items}
              onOpenLightbox={(mid) => {
                const i = items.findIndex((it) => it.media_id === mid);
                if (i >= 0) setLbIndex(i);
              }}
              onSimilar={showSimilar}
              morph={lbIndex == null}
            />, document.body)
        ) : (
          <Grid
            items={items} total={total} loading={loading}
            page={page} pages={pages}
            goToPage={goToPage}
            keysEnabled={gridKeys}
            onOpenDetails={openDetails}
            blur={blur}
            thumb={thumb}
            layout={layout}
            selectMode={selectMode} selected={selected} toggleSelected={toggleSelected}
            openLightbox={setLbIndex}
            onRate={rate}
            onContextMenu={openContextMenu}
            onOpenSeries={filterBySeries}
            onOpenBatch={filterByBatch}
          />
        )}
      </main>

      {ctxMenu && (
        <GridContextMenu target={ctxMenu} actions={ctxActions} onClose={() => setCtxMenu(null)} />
      )}
      {similarFor && (
        <SimilarModal mediaId={similarFor} onClose={() => setSimilarFor(null)}
          onOpenDetails={(mid) => { setSimilarFor(null); openDetails(mid); }} />
      )}

      {/* the DC's veil: keeps the column bottom legible under the (future) dock */}
      <div className="mgx-veil" aria-hidden="true" />

      {lbIndex != null && (
        <Lightbox
          items={items} index={lbIndex} setIndex={setLbIndex}
          onClose={() => setLbIndex(null)}
          onRate={rate}
          page={page} pages={pages} loadPage={load}
          onEdit={requestEdit} onToVideo={requestVideo}
          onOpenDetails={openDetails}
          onPublish={openPublish}
          onSimilar={showSimilar}
        />
      )}

      {/* OVERLAY MOUNT POINT — the six designed nav overlays land here.
          Health/My Art/Contests/Publish/Train are live (Publish and Train since
          2026-08-06, on the real createArtworkFromTaskV2 / createTrainingTask
          pipelines); Import is still `soon`-dimmed in NavSpine until its own
          backend route exists (My
          Art and Contests already had real, working routes sitting unused --
          see docs/DECISIONS.md 2026-08-02). Scrim z 300, slab 301 (band per
          drift §3); Esc-first is handled by the capture listener above. The
          model/tag/LoRA click-throughs close the overlay and apply the filter
          through the same applyAdvanced path every filter control uses. */}
      {overlay === "health" && (
        <HealthOverlay
          onClose={() => setOverlay(null)}
          onModelFilter={(m) => { setOverlay(null); applyAdvanced({ model: m }); }}
          onTagFilter={(t) => { setOverlay(null); applyAdvanced({ tag: t }); }}
          onLoraFilter={(l) => { setOverlay(null); applyAdvanced({ lora: l }); }}
          onOpenDuplicates={() => setOverlay("duprev")}
        />
      )}
      {overlay === "duprev" && (
        <DuplicateReviewOverlay
          onClose={() => setOverlay(null)}
          onResolved={afterMutation}
          boot={boot}
        />
      )}
      {overlay === "myart" && (
        <MyArtOverlay
          onClose={() => setOverlay(null)}
          onOpenPost={(mid) => { setOverlay(null); openDetails(mid); }}
        />
      )}
      {overlay === "contests" && (
        <ContestsOverlay onClose={() => setOverlay(null)}
          onShortlist={shortlistContest} selectedCount={selected.size} />
      )}
      {overlay === "train" && (
        <TrainOverlay onClose={() => setOverlay(null)} />
      )}
      {overlay === "publish" && (
        <PublishOverlay
          mediaId={publishFor}
          onClose={() => { setOverlay(null); setPublishFor(""); }}
          onPublished={afterMutation}
        />
      )}
      {overlay === "import" && (
        <ImportOverlay
          onClose={() => setOverlay(null)}
          collections={collections}
          onImported={afterMutation}
        />
      )}
      {overlay === "panel" && (
        <ControlPanelOverlay onClose={() => setOverlay(null)} boot={boot} account={account} />
      )}
      {overlay === "contactsheet" && (
        <ContactSheetOverlay
          ids={contactSheetTarget.ids}
          collectionName={contactSheetTarget.collectionName}
          onClose={() => setOverlay(null)}
        />
      )}
      {overlay === "folio" && (
        <FolioOverlay onClose={() => setOverlay(null)} />
      )}
      {overlay === "aitools" && (
        <AiToolsModal open onClose={() => setOverlay(null)} onPick={requestScene} />
      )}

      {/* the Generate dock host: the wrapper carries the outside-click anchor
          and the open/closing motion classes for the GenerateDock refit; the
          drawer inside NEVER unmounts (shared video component owns poll
          timers for charged tasks). */}
      <div
        ref={dockHostRef}
        className={"mgx-dock-host" + (dockOpen ? " open" : "") + (dockClosing ? " closing" : "")}
      >
        <GenerateDrawer open={dockActive} onClose={closeDock} account={account}
          request={genRequest} />
      </div>
      <PickerHost />
      {claimModal.open && (
        <ClaimModal credits={claimModal.credits} exiting={claimModal.exiting}
          claiming={claimModal.claiming} error={claimModal.error}
          onClaim={claimModal.claim} onDismiss={claimModal.dismiss} />
      )}
    </div>
  );
}
