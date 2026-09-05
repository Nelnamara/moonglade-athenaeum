import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal, flushSync } from "react-dom";
import Banner from "./components/Banner.jsx";
import SeparatorBar from "./components/SeparatorBar.jsx";
import { LibraryBar } from "./components/FiltersPanel.jsx";
import Grid from "./components/Grid.jsx";
import GridContextMenu from "./components/GridContextMenu.jsx";
import SimilarResults from "./components/SimilarResults.jsx";
import SeriesModal from "./components/SeriesModal.jsx";
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
import { CommandPalette, ShortcutSheet, GPendingChip } from "./components/CommandPalette.jsx";
import useCommandPalette from "./hooks/useCommandPalette.js";
import { shortId } from "./palette/paletteCore.js";
import "./styles/shell.css";
import {
  fetchAccount, fetchCollections,
  apiGet, apiPost, downloadZipForm, rateImage, resolveVideoIds, rebuildPoster,
} from "./api.js";
import useLibrary, { filterQueryString } from "./hooks/useLibrary.js";
import useSimilar from "./hooks/useSimilar.js";
import { invalidate } from "./hooks/swrCache.js";
import { buildUrl, readPage, readImage, readSeries } from "./gen/urlState.js";

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
  const paletteUpRef = useRef(false);
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape" || !overlayRef.current) return;
      if (overlayRef.current === "panel") return;   // panel runs its own ladder
      if (isPickerOpen()) return;                   // picker dismisses itself
      if (paletteUpRef.current) return;             // the palette/cheat-sheet close FIRST
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
  /* useCallback from here down through openSeries: these are <Grid> props, and Grid is
     memoized (see its own foot-of-file note), so a fresh identity on every App render would
     defeat the memo before it did anything. Each closes over setUrl (itself useCallback'd)
     and setState functions only, so the dep lists are honest rather than pruned -- none of
     them can go stale. */
  const openDetails = useCallback((mid) => {
    const commit = () => {
      setLbIndex(null);
      setUrl({ image: mid });
      setDetailsFor(mid);
    };
    if (document.startViewTransition) document.startViewTransition(() => flushSync(commit));
    else commit();
  }, [setUrl]);
  const closeDetails = useCallback(() => {
    setUrl({ image: null });   // keeps ?page=N -- the grid underneath is still on it
    setDetailsFor(null);
  }, [setUrl]);
  /* Back/forward re-read BOTH params: the image (as before) and the page -- a
     ?page= that differs from the grid's current page loads it. Refs, because the
     listener mounts once and load's identity follows the filters. */
  const pageRef = useRef(page);
  const loadRef = useRef(load);
  useEffect(() => { pageRef.current = page; loadRef.current = load; });
  useEffect(() => {
    const onPop = () => {
      setDetailsFor(readImage(window.location.search));
      // B3: the open series stack is addressable too, so Back closes it (or reopens
      // the one the entry it landed on had up) exactly like it does for Details.
      setSeriesFor(readSeries(window.location.search));
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
  const goToPage = useCallback((p) => {
    setUrl({ page: p });
    load(p, true);
  }, [setUrl, load]);
  const filterByModel = useCallback((name) => {
    closeDetails();
    setAdv((old) => ({ ...old, model: name }));
  }, [closeDetails, setAdv]);
  const filterByBatch = useCallback((batch) => {
    closeDetails();
    setAdv((old) => ({ ...old, batch, series: "" }));
  }, [closeDetails, setAdv]);
  /* Open a SERIES stack -- a MODAL over the gallery (B3, Gallery Chrome Handoff,
     2026-09-04).

     It used to be the mirror of filterByBatch: push the sid into `adv.series` and
     let the whole library re-load as that series' members (#34 direction B's
     ?series= drill-down). That was a takeover -- the grid you were reading was
     replaced, and getting back meant finding Clear -- and the handoff retires it.
     The library is untouched now: same filters, same page, same scroll. The modal
     asks for the series itself (api.js's fetchSeriesStack) and Esc closes it, which
     is the whole of the way back.

     The address follows, so a stack is a place: ?series=<sid> alongside ?image= and
     ?page=. That sid has always been deterministic precisely so a bookmarked
     ?series= URL keeps resolving (moonglade_gallery.py, compute_series); until now
     nothing on this side ever read it back.

     `adv.series` itself is deliberately left in place and still rides every listing
     request -- the CSV export writes it, and it is the parameter this modal's own
     fetch uses. What went away is the one caller that SET it from a click. */
  const [seriesFor, setSeriesFor] = useState(() => readSeries(window.location.search));
  const openSeries = useCallback((sid) => {
    closeDetails();
    setLbIndex(null);
    setUrl({ series: sid });
    setSeriesFor(sid);
  }, [closeDetails, setUrl]);
  const closeSeries = useCallback(() => {
    setUrl({ series: null });
    setSeriesFor(null);
  }, [setUrl]);
  /* Opening a picture from inside the stack is ONE navigation, so it must leave ONE
     history entry. It used to be closeSeries() then openDetails(): two setUrl calls,
     two pushStates, and a middle entry -- the bare library with neither the stack nor
     the record -- that the owner never saw and that Back landed on. The address is
     written ONCE here, with both keys in the same patch (buildUrl takes a multi-key
     patch and only touches the keys it is handed); the two verbs then run for their
     STATE work, and their own setUrl calls fall through setUrl's already-matches
     guard because the address is by then exactly what they would have written. So
     Back from the record goes straight to the stack that was open. */
  const openDetailsFromSeries = useCallback((mid) => {
    setUrl({ series: null, image: mid });
    closeSeries();
    openDetails(mid);
  }, [setUrl, closeSeries, openDetails]);

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
    // [load], not the missing dep array it had. With no array at all this effect tore down
    // and re-added three global listeners on EVERY render of the shell -- an overlay
    // opening, a star being clicked -- purely to keep `load` fresh in the closure. `load`
    // is the only value here that ever changes identity (useLibrary's useCallback, keyed to
    // the filters); fetchAccount is a module import and setAccount/setRunning are setState
    // functions, all three permanently stable. So the listeners are now re-bound exactly
    // when the closure would otherwise go stale, which is the behaviour the missing array
    // was buying at the cost of doing it always.
  }, [load]);

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
  /* THE ONE MUTATION SEAM. Every bulk action here funnels through it, and so do the two
     overlays that change the library from outside this list (ImportOverlay's onImported,
     DuplicateReviewOverlay's onResolved). So it is also where the shared read cache
     (hooks/swrCache.js) is purged: the overlays paint from last-known data on reopen, and
     "last known" has to stop meaning "before the thing you just did". Five families, each
     because a mutation here really can change it -- My Art's totals, the per-image records,
     the achievement roster (collecting/deleting moves metrics), the Health walk, and the
     library pages themselves. A purge only DROPS cached reads; it fetches nothing. */
  const afterMutation = async () => {
    invalidate(["/api/your-art", "/api/myart/items", "/api/next/detail/",
                "/api/achievements", "/api/health", "/api/next/library"]);
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

  const rate = useCallback(async (mid, value) => {
    // optimistic; the server clamps 0-5 and answers the stored value
    setItems((old) => old.map((it) => (it.media_id === mid ? { ...it, rating: value } : it)));
    try {
      await rateImage(mid, value);
    } catch {
      /* a failed rate leaves the optimistic value; the next load corrects it */
    }
  }, [setItems]);

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
  /* "↻ Again — new seed" (the palette's R / its On-this-image row). Owner ruling,
     2026-08-31: SEND TO REMIX, NO INSTANT SPEND. This is the SAME shipped Remix path
     above -- the picture's full recipe prefilled into the composer -- with one field
     changed, a freshly rolled seed, so the next Generate is a different draw of the same
     idea. It opens the dock and stops there; the human presses Generate. Nothing in the
     palette ever submits a generation. */
  const requestAgain = (mid) => {
    setLbIndex(null);
    openDock();
    setGenRequest({ tab: "remix", mid, newSeed: true, nonce: Math.random() });
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
  const openContextMenu = useCallback(
    (mid, thumb, x, y, isVideo) => setCtxMenu({ mid, thumb, x, y, isVideo }), []);
  const ctxActions = {
    onEdit: requestEdit,
    onVideo: requestVideo,
    onRemix: requestRemix,
    // B2: the right-click row is a ◈ door like the other three, so it calls the SAME
    // verb rather than setting the state itself -- it used to be the one entry point
    // that skipped showSimilar's "close whatever is open first" step.
    onSimilar: (mid) => showSimilar(mid),
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
  /* ◈ SIMILAR, ONE SYSTEM (B2, Gallery Chrome Handoff, 2026-09-04).

     FOUR DOORS, ONE VERB. The ◈ on a hovered grid tile, the ◈ Similar chip in the
     lightbox's action row, the ◈ Find similar row in the right-click menu, and the
     ◈ door on the Details record's related strip all call THIS. There is no second
     similarity code path in the app, and the mark is the same everywhere so the four
     read as one control rather than four cousins.

     ONE RESULT STATE. It is not a modal any more. The viewer and the record close,
     the ◈ token appears in the library bar carrying the source picture's own thumb,
     and the lookalikes take the grid's place underneath it. No library STATE is
     touched -- not the query, not the filters, not the page -- so ✕ on the token or
     Escape restores the previous view EXACTLY. The one thing "never disturbed it"
     does not cover is the scroll offset, which the browser clamps against the
     shorter results document; that is saved and put back below, and the two
     together are what "exactly" means. (Lightbox.dc.html:354 sends Similar to the
     gallery and Image Details.dc.html:127-140 keeps only the inline strip in the
     record; the refit had both stacking a modal on the open surface -- "Where the
     Refit Broke" #6. B2 finishes that repair by removing the modal itself.)

     The fetch lives here rather than in the results component because two surfaces
     read it: the results grid, and the library bar's match count beside the token.

     useCallback with a dependency list of one STABLE callback, because since B2 this
     is also a <Grid> prop and Grid is memoized -- a fresh identity per render would
     defeat that memo before it did anything (the same reasoning openDetails and the
     filterBy* pair carry). The old body branched on `detailsFor` before closing the
     record, which would have put a changing value in the deps; closeDetails is safe
     to call with no record open (setUrl no-ops when the address is already right,
     setDetailsFor(null) on null is a no-op), so the branch was doing nothing the
     unconditional call doesn't. */
  /* "RESTORES THE PREVIOUS VIEW EXACTLY" INCLUDES WHERE YOU WERE ON THE PAGE.
     The results take the grid's place inside the SAME <main>, and a lookalike set
     (48 tiles at most, often far fewer) is shorter than the library page it
     replaces -- so the browser clamps the scroll offset to the shorter document
     the moment the swap commits, and the number is gone before any dismiss path
     can read it. Nothing about the library moved, but the place in it did. So the
     offset is saved on the way IN and put back on the way OUT.

     It is the WINDOW's offset, not <main>'s: .mgx-main sets position/z-index only
     (shell.css) -- the document is the scroller for masonry/grid/hero, which is
     why Grid's own page-flip calls window.scrollTo. A body-overflow scroll lock
     (useScrollLock, for a Details/lightbox layer above) leaves window.scrollY
     reading the library's real offset, so entering Similar from those surfaces
     saves the right number too.

     ONLY THE FIRST ENTRY SAVES. Chaining ◈ from inside the results re-anchors the
     set on a new picture without the library having moved, so a second save would
     overwrite the library position with the (clamped) similar-view one. The null
     sentinel is the "we are not in Similar" state; 0 is a real saved offset. */
  const libScrollRef = useRef(null);
  const showSimilar = useCallback((mid) => {
    if (libScrollRef.current === null) libScrollRef.current = window.scrollY || 0;
    setLbIndex(null);
    closeDetails();
    setSeriesFor(null);
    setSimilarFor(mid);
  }, [closeDetails]);
  /* The other half, on EVERY dismiss path -- the token's ✕, Escape, and the empty
     state's "Back to the library" all land here, because they all clear the one
     state. Layout effect: the grid is back in the DOM and measured, but the frame
     has not painted, so the library comes back already in place rather than
     visibly jumping. */
  useLayoutEffect(() => {
    if (similarFor) return;
    const y = libScrollRef.current;
    if (y === null) return;
    libScrollRef.current = null;
    window.scrollTo(0, y);
  }, [similarFor]);
  const similar = useSimilar(similarFor);
  const similarSource = useMemo(() => {
    if (!similarFor) return null;
    const row = items.find((it) => it.media_id === similarFor);
    return { media_id: similarFor, thumb: (row && row.thumb) || ("/thumbs/" + encodeURIComponent(similarFor) + ".jpg") };
  }, [similarFor, items]);
  const similarToken = useMemo(() => (similarFor ? {
    mid: similarFor,
    thumb: similarSource.thumb,
    loading: similar.loading,
    count: similar.images.length,
  } : null), [similarFor, similarSource, similar.loading, similar.images.length]);
  /* Escape dismisses the ◈ token, at the same rung the Details record and the
     lightbox sit on: the surface under the pointer goes away and the library is
     back. Capture phase, and only when Similar is the top thing up -- the grid
     context menu and the series modal own their own Escape, and a nav overlay or
     the palette is a layer ABOVE this one. */
  useEffect(() => {
    if (!similarFor) return undefined;
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      if (overlayRef.current || paletteUpRef.current || isPickerOpen()) return;
      e.stopPropagation();
      setSimilarFor(null);
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [similarFor]);

  const dockActive = dockOpen && !dockClosing;

  /* ======================= THE COMMAND PALETTE (Ctrl/⌘ K) =====================
     Locked source: ../moonglade-internal/design/command-palette/ -- BRIEF.md (taxonomy),
     Command Palette.dc.html frames A-H (pixels), NOTES.md (the 2026-08-31 rulings).

     THE ONE RULE that shapes everything below (DC frame H): a command calls the SAME app
     function the mouse UI calls. Every `run` here is a reference to a verb this file
     already owns -- openOverlay, setLayout, setGroup, openDock, applyAdvanced, the
     ctxActions table, openPublish, claimModal.claim, requestAgain. There is no second
     code path for anything, so the palette can never drift from what the buttons do.
     The corollary is the absent-never-disabled rule: a row that cannot act is simply not
     built (no focused image -> no On-this-image group and no R; nothing claimable -> no
     Claim row; no collections -> no collection rows). ------------------------------- */

  /* Which picture the contextual group acts on, in precedence order: the Details record
     that is open, the Lightbox page being viewed, else the last grid card the keyboard or
     a click put focus on. The grid's own focus is DOM focus (Grid.jsx focuses the <figure>
     itself), and it is lost the moment the palette's input takes over -- so the card
     reports its media_id up here on focus and this remembers it, which is also what keeps
     the accent ring meaningful under the scrim in frame D. Cleared when the row leaves the
     page, so a filter change can't leave the palette acting on something invisible. */
  const [gridFocus, setGridFocus] = useState(null);
  useEffect(() => {
    if (gridFocus && !items.some((it) => it.media_id === gridFocus)) setGridFocus(null);
  }, [items, gridFocus]);
  const focusItem = useMemo(() => {
    const find = (mid) => items.find((it) => it.media_id === mid) || null;
    // Details can outlive the page its row was on (a bookmarked ?image= opens straight
    // into it), so fall back to a minimal stand-in rather than losing the whole group.
    if (detailsFor) return find(detailsFor) || { media_id: detailsFor, filename: "", is_video: false, thumb: "" };
    if (lbIndex != null && items[lbIndex]) return items[lbIndex];
    if (gridFocus) return find(gridFocus);
    return null;
  }, [detailsFor, lbIndex, items, gridFocus]);

  /* "Go to → Library": back to the plain grid. Closes whatever is stacked on top of it and
     nothing else -- it is a navigation, not a Clear (the filters and the page it was on are
     exactly where the owner left them). */
  const goLibrary = useCallback(() => {
    setOverlay(null);
    setLbIndex(null);
    setSimilarFor(null);
    setSeriesFor(null);
    if (dockStateRef.current.open) closeDock();
    setUrl({ image: null, series: null });
    setDetailsFor(null);
  }, [closeDock, setUrl]);

  /* "Jump to Search" (/). The library bar's field lives two components down inside the
     banner's hero band -- and that band is DISPLAY:NONE in slim mode, so a bare focus()
     would silently do nothing there. Un-slim first, then focus on the commit that renders
     it: the nonce+effect pair is what guarantees the field exists by the time we reach for
     it, rather than a guessed rAF. The cross-tree query is the same reach GenerateDrawer
     already makes for .mgx-hdr / .mgx-sep -- there is no programmatic focus seam on the
     LibraryBar today, and adding a ref chain through Banner for one keystroke would be a
     wider change than the keystroke is worth. */
  const [focusSearchAt, setFocusSearchAt] = useState(0);
  useEffect(() => {
    if (!focusSearchAt) return;
    const el = document.querySelector(".mgl-search input");
    if (el) { el.focus(); el.select(); }
  }, [focusSearchAt]);
  const jumpToSearch = useCallback(() => {
    goLibrary();
    setSlim(false);
    setFocusSearchAt((n) => n + 1);
  }, [goLibrary]); // eslint-disable-line react-hooks/exhaustive-deps

  /* "Sync now" -- the Control Panel's own ↻ Sync now button, same route, same body
     (useControlPanel.runAction's sync case). Ruling, NOTES §2.2: while a job is already
     running the row STAYS and the refusal shows as the busy toast, in the server's own
     words (POST /api/panel/run answers 409 {"error": "a job is already running"}). */
  const syncNow = useCallback(async () => {
    const d = await apiPost("/api/panel/run", { action: "sync" });
    if (!window.Toast) return;
    if (d && d.error) {
      window.Toast.show({
        kind: d.http_status === 409 ? "" : "err",
        title: d.http_status === 409 ? "Already busy" : "Couldn't start the sync",
        msg: d.error,
      });
    } else {
      window.Toast.show({ kind: "ok", title: "Sync started", msg: "Progress rides the Control Panel's job console." });
    }
  }, []);

  /* THE TAXONOMY (BRIEF §2 + the NOTES §1 adds the owner cleared for the build). Group
     order is FIXED and never re-ranks (§8.4): Go to · Layout · Do · On this image · Help,
     with Recent folded in above by the hook when there is one. Glyphs are the app's own
     (§8.2, no new icon set); shortcut chips render only where a real global key exists
     (§8.3). Every id is stable, because Recent stores ids. */
  const claimable = account && Number(account.claim_credits) > 0 ? Number(account.claim_credits) : 0;
  // The Help row opens the sheet the hook owns, and the hook takes this very list -- so the
  // row reaches it through a ref rather than a circular dependency (the same render-time
  // ref hand-off useClaimModal.js uses for refreshAccount).
  const paletteRef = useRef(null);
  const commands = useMemo(() => {
    const list = [];
    const go = (id, icon, label, run, keys, hotkey) =>
      list.push({ id, group: "Go to", icon, label, run, keys: keys || [], hotkey });

    go("goto.library", "⌂", "Library", goLibrary, ["G", "L"], "g l");
    go("goto.loom", "▮", "Storyboard (the Loom)", () => { window.location.href = "/loom"; }, ["G", "S"], "g s");
    go("goto.panel", "⛭", "Control Panel", () => openOverlay("panel"), ["G", "C"], "g c");
    // The four nav destinations NOTES §1 flagged as missing, cleared to ship 2026-08-31 --
    // each trivially removable at branch review. Glyphs are the app's own destination
    // marks (AppMobile's MENU_ITEMS table; Folio's is the banner's).
    go("goto.contests", "🏅", "Contests", () => openOverlay("contests"));
    go("goto.myart", "📈", "My Art", () => openOverlay("myart"));
    go("goto.health", "♡", "Health", () => openOverlay("health"));
    go("goto.folio", "🏆", "Folio", () => openOverlay("folio"));
    // One row per collection from the LIVE list (already A-Z, case-insensitive, from
    // /api/collections via unique_collections). "Collection:" is matchable text like any
    // other label. No count sub: no route in this app reports a per-collection image
    // count, and inventing 40 count queries for a palette row is not a trade worth making.
    for (const name of collections || []) {
      list.push({
        id: "collection:" + name,
        group: "Go to",
        icon: "❖",
        label: "Collection: " + name,
        run: () => { goLibrary(); applyAdvanced({ shelf: name }); },
        keys: [],
      });
    }

    // The layout picker's own modes and its own exact glyphs, active one marked with the
    // emerald ✓. §8.2's ruling is "the layout picker's exact glyphs", so these follow the
    // picker wherever it lives -- and since B1 (2026-09-04) it is SeparatorBar's
    // LAYOUT_CELLS, whose marks are ▤ masonry · ▦ grid · ▣ hero · ≡ timeline. Masonry and
    // grid swapped against the old tray row's, timeline took a lighter mark, and Hero's
    // ▧ became ▣ when it got its own cell back (2026-09-05) -- the palette follows the
    // picker rather than keeping a second, private mark for the same layout.
    for (const [key, label, glyph] of [
      ["masonry", "Masonry", "▤"], ["grid", "Grid", "▦"],
      ["hero", "Hero", "▣"], ["timeline", "Timeline", "≡"],
    ]) {
      list.push({
        id: "layout." + key, group: "Layout", icon: glyph, label,
        right: layout === key ? "✓" : "", keys: [],
        run: () => { goLibrary(); setLayout(key); },
      });
    }
    list.push({
      id: "layout.stack", group: "Layout", icon: "⧉", label: "Toggle Stack sessions",
      right: group === "series" ? "On" : "", rightKind: "pill", keys: [],
      run: () => { goLibrary(); setGroup(group !== "series"); },
    });

    list.push({
      id: "do.generate", group: "Do", icon: "✦", label: "New generation",
      sub: "Generate dock", keys: ["N"], hotkey: "n", run: openDock,
    });
    list.push({
      id: "do.search", group: "Do", icon: "⌕", label: "Jump to Search",
      keys: ["/"], hotkey: "/", run: jumpToSearch,
    });
    list.push({ id: "do.sync", group: "Do", icon: "⟳", label: "Sync now", keys: [], run: syncNow });
    // Claimable credits: present ONLY while there are some, running the exact claim the
    // header pill runs (useClaimModal.claim -- POST /api/claim, then the account refetch
    // that drops claim_credits to 0 and takes this row away again).
    if (claimable) {
      list.push({
        id: "do.claim", group: "Do", icon: "◉",
        label: "Claim +" + claimable.toLocaleString() + " credits",
        keys: [], run: claimModal.claim,
      });
    }

    /* The contextual group -- present only while a picture is focused or open, absent
       otherwise (frame A is the absent case, D the present one). The header names its
       target in mono. The actions ARE the right-click set, reached through the same
       ctxActions table the menu itself calls, plus ☁ Publish (NOTES §1) through the same
       openPublish the Lightbox and Details chips use. */
    if (focusItem) {
      const mid = focusItem.media_id;
      const extra = focusItem.filename || shortId(mid);
      const img = (id, icon, label, run, extras) =>
        list.push({ id: "img." + id, group: "On this image", groupExtra: extra, icon, label, run, keys: [], ...(extras || {}) });
      img("again", "↻", "Again — new seed", () => requestAgain(mid), { keys: ["R"], hotkey: "r" });
      img("remix", "✱", "Remix", () => ctxActions.onRemix(mid));
      img("video", "▶", "Send to Video", () => ctxActions.onVideo(mid, focusItem.thumb));
      // ◈, matching every other Similar door since B2 (2026-09-04) -- the palette
      // mirrors the buttons, so it wears the buttons' mark.
      img("similar", "◈", "Find similar", () => showSimilar(mid));
      img("edit", "✎", "Edit", () => ctxActions.onEdit(mid));
      img("details", "ⓘ", "Open details", () => ctxActions.onDetails(mid));
      img("copyid", "⎘", "Copy id", () => ctxActions.onCopyId(mid), { sub: shortId(mid) });
      img("publish", "☁", "Publish", () => openPublish(mid));
    }

    list.push({
      id: "help.keys", group: "Help", icon: "?", label: "Show keyboard shortcuts",
      keys: ["?"], run: () => paletteRef.current && paletteRef.current.openSheet(),
    });
    return list;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collections, layout, group, claimable, focusItem, goLibrary, jumpToSearch, syncNow,
      openDock, openOverlay, applyAdvanced, openPublish]);

  const palette = useCommandPalette(commands);
  paletteRef.current = palette;
  // The Escape ladder guard App's own overlay closer reads (see that listener above).
  useEffect(() => { paletteUpRef.current = palette.open || palette.sheetOpen; });

  /* Grid arrow-key navigation (#31, Refit #7) only while the grid is the top
     layer: no lightbox, no Details, no nav overlay, no dock, no context menu, no
     Similar view, no series stack, no palette -- each of those owns (or must not
     lose) the arrow keys. Arrows drive the PALETTE while it is open and the GRID
     while it is closed (BRIEF §6); the palette's own input would already swallow
     them, this is the explicit half of the same rule. `similarFor` is in the list
     for a second reason since B2: the grid isn't even mounted then. */
  const gridKeys = lbIndex == null && !detailsFor && !overlay && !ctxMenu
    && !similarFor && !seriesFor && !dockActive && !claimModal.open
    && !palette.active && !palette.sheetActive;

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
          /* NOT memoized, deliberately (2026-09-04 perf pass). React.memo pays only where
             the props can be made referentially stable, and two of LibraryBar's cannot be
             without a wider refactor than this pass: `lib` is the whole useLibrary()
             return, a fresh object every render by construction, and `actions` is an object
             literal of closures over selIds/items/adv/applied. Wrapping it would add a
             comparison that can never pass -- strictly slower. Grid and GenerateDrawer,
             whose props ARE all stable, are the two that got the memo. */
          libraryBar={
            <LibraryBar
              lib={lib}
              boot={boot}
              actions={actions}
              collections={collections}
              group={group} setGroup={setGroup}
              similar={similarToken} onClearSimilar={() => setSimilarFor(null)}
            />
          }
        />
        <SeparatorBar
          boot={boot} account={account}
          slim={slim} onToggleSlim={() => setSlim(!slim)}
          blur={blur} onToggleBlur={() => setBlur(!blur)}
          thumb={thumb} thumbMax={thumbMax} onThumb={setThumb}
          layout={layout} setLayout={setLayout}
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
        ) : similarFor ? (
          /* B2: the lookalikes take the GRID's place, in the same column, under the
             same bar -- which is now wearing the ◈ token. The library's own state is
             not touched while this is up, so clearing the token is the entire way
             back; nothing is re-fetched and nothing has moved. */
          <SimilarResults
            source={similarSource}
            state={similar}
            onOpenDetails={openDetails}
            onSimilar={showSimilar}
            onClear={() => setSimilarFor(null)}
          />
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
            onFocusCard={setGridFocus}
            onSimilar={showSimilar}
            onOpenSeries={openSeries}
            onOpenBatch={filterByBatch}
          />
        )}
      </main>

      {ctxMenu && (
        <GridContextMenu target={ctxMenu} actions={ctxActions} onClose={() => setCtxMenu(null)} />
      )}
      {/* B3: a series stack, over the gallery. Opening a picture from inside it closes
          the modal first -- the record is the deeper view, not a third layer stacked on
          a second one -- and does it as ONE history entry (openDetailsFromSeries). */}
      {seriesFor && (
        <SeriesModal sid={seriesFor} onClose={closeSeries}
          onOpenDetails={openDetailsFromSeries} />
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
          onShortlist={shortlistContest} selectedCount={selected.size}
          /* the picker's empty state offers a way out: publishing something new is how
             you become eligible, so it hands the Publish flow over with no image picked
             (its own strip/browse chooses one). */
          onOpenPublish={() => { setPublishFor(""); setOverlay("publish"); }} />
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

      {/* The palette band, above everything the app can stack under it (z 460/461, the
          cheat-sheet's own scrim 470/471, the G… chip 462 — see command-palette.css and
          the ladder comment in overlays.css). Each surface is its own deferred-exit
          mount, exactly like the dock host and the toasts. */}
      <CommandPalette palette={palette} />
      <ShortcutSheet open={palette.sheetOpen} closing={palette.sheetClosing}
        onClose={palette.closeSheet} />
      <GPendingChip open={palette.pending} />
    </div>
  );
}
