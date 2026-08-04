import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import Banner from "./components/Banner.jsx";
import SeparatorBar from "./components/SeparatorBar.jsx";
import { LibraryBar } from "./components/FiltersPanel.jsx";
import Grid from "./components/Grid.jsx";
import Lightbox from "./components/Lightbox.jsx";
import DetailsView from "./components/DetailsView.jsx";
import HealthOverlay from "./components/HealthOverlay.jsx";
import DuplicateReviewOverlay from "./components/DuplicateReviewOverlay.jsx";
import MyArtOverlay from "./components/MyArtOverlay.jsx";
import ContestsOverlay from "./components/ContestsOverlay.jsx";
import ImportOverlay from "./components/ImportOverlay.jsx";
import ControlPanelOverlay from "./components/ControlPanelOverlay.jsx";
import ContactSheetOverlay from "./components/ContactSheetOverlay.jsx";
import FolioOverlay from "./components/FolioOverlay.jsx";
import GenerateDrawer from "./components/GenerateDrawer.jsx";
import PickerHost, { isPickerOpen } from "./components/PickerHost.jsx";
import "./styles/shell.css";
import {
  fetchAccount, fetchCollections,
  postForm, downloadZipForm, resolveVideoIds,
} from "./api.js";
import useLibrary from "./hooks/useLibrary.js";

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
     separator bar's #mg-sep-cost <mg-cost-badge> is its price chip.
   - Grid refit: receives `thumb` (SIZE slider) — also exposed as --thumb on
     <main>; shell.css maps it onto the existing .grid columns until then. */

export default function App({ boot }) {
  const {
    // filters
    media, setMedia, shelf, setShelf, perPage, setPerPage,
    query, setQuery, applied, setApplied, adv, setAdv, flyOpen, setFlyOpen,
    // data
    items, setItems, total, page, pages, loading,
    // load + filter verbs
    load, applyAdvanced, advCount, submitQuery, resetAll,
    // selection
    selectMode, setSelectMode, selected, setSelected, toggleSelected,
  } = useLibrary();
  const [account, setAccount] = useState(null);
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
     real width (DC formula), measured live. ---- */
  const [thumb, setThumbState] = useState(() => {
    const v = parseInt(localStorage.getItem("mg_thumb") || "", 10);
    return isFinite(v) && v >= 152 ? v : 210;
  });
  const setThumb = (v) => {
    localStorage.setItem("mg_thumb", String(v));
    setThumbState(v);
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

  /* ---- live-run signal for the banner spinner + activity cluster. Counted
     from the shared drawer's mg-submit/mg-result events (the only begin/end
     pair any producer emits today). The image path (useGenerate) has no begin
     event, so its runs don't tick this — the RunsReel workstream owns the
     richer signal and can replace this counter wholesale. ---- */
  const [running, setRunning] = useState({ count: 0, pct: null });

  /* ---- overlays (drift §16): six nav destinations open floating overlays.
     State + verb live here; the surfaces are the overlays workstream's. ---- */
  const [overlay, setOverlay] = useState(null);
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
  // Esc closes the overlay FIRST (capture beats the drawer's own Esc ladder).
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape" || !overlayRef.current) return;
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
     (safe: EditTab ignores a falsy initialSource). #video rides the same
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
  const [detailsFor, setDetailsFor] = useState(
    () => new URLSearchParams(window.location.search).get("image") || null
  );
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
      window.history.pushState({}, "", "/next?image=" + encodeURIComponent(mid));
      setDetailsFor(mid);
    };
    if (document.startViewTransition) document.startViewTransition(() => flushSync(commit));
    else commit();
  };
  const closeDetails = () => {
    window.history.pushState({}, "", "/next");
    setDetailsFor(null);
  };
  useEffect(() => {
    const onPop = () => setDetailsFor(new URLSearchParams(window.location.search).get("image") || null);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const filterByModel = (name) => {
    closeDetails();
    setAdv((old) => ({ ...old, model: name }));
  };
  const filterByBatch = (batch) => {
    closeDetails();
    setAdv((old) => ({ ...old, batch }));
  };

  /* Generation completions refresh the library + credits chip.
     THREE channels, because there are three producers:
     - mg-gen-done: our own image submit path (useGenerate);
     - mg-submit:   the SHARED video drawer accepting a task -- it owns its own
                    poll, so it gets Jobs.register (never Jobs.track, which
                    would double-poll: the Loom's pinned contract);
     - mg-result:   that drawer finishing, which is when credits actually moved.
     The same submit/result pair also ticks the shell's live-run counter. */
  useEffect(() => {
    const refresh = () => { load(1, true); fetchAccount().then(setAccount); };
    // mg-gen-done also nudges the Folio of Honors to check-and-celebrate any newly
    // earned achievement -- this is the only "a real action just completed" hook Ach
    // has outside a hard page load, so it belongs here alongside the grid/account
    // refresh. Guarded like window.Toast/window.Jobs elsewhere in this file.
    const onGenDone = () => { refresh(); if (window.Ach) window.Ach.check(); };
    const onSubmit = (e) => {
      const id = e.detail && (e.detail.task_id || e.detail.taskId);
      if (id && window.Jobs) window.Jobs.register(id, "Rendered");
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
      fetch("/api/ach-event", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event: "konami" }),
      }).catch(() => {});
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
      // Built with DOM methods, not innerHTML -- both lines are fixed literals
      // (no interpolated data), but this way there is nothing to ever audit.
      const toast = document.createElement("div");
      toast.className = "ee-toast";
      toast.appendChild(document.createTextNode("✺ Elune-adore, Nelnamara ✺"));
      const sub = document.createElement("div");
      sub.style.cssText = "font-size:12.5px;color:var(--subtext);margin-top:7px;";
      sub.textContent = "The Athenaeum casts Starfall. Moonfire spam remains a lifestyle.";
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
      await postForm("/collection-add", { back: "/next", name: name.trim() }, selIds);
      afterMutation();
    },
    removeCollection: async (name) => {
      if (!name) return;
      if (!window.confirm(
        "Remove " + selIds.length + " item(s) from the collection “" + name + "”?\n\n" +
        "Only the collection label is removed — no files are deleted and nothing leaves your PixAI account.")) return;
      await postForm("/collection-remove", { back: "/next", name }, selIds);
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
    downloadZip: () => downloadZipForm(selIds),
    replacePrompt: async () => {
      const find = window.prompt(
        "Find this text in the prompts of " + selIds.length + " selected image(s):");
      if (find === null || find === "") return;
      const repl = window.prompt('Replace "' + find + '" with: (leave blank to delete it)');
      if (repl === null) return;
      if (!window.confirm('Replace "' + find + '" with "' + repl + '" across ' +
        selIds.length + " prompt(s)? This edits catalog.db.")) return;
      await postForm("/bulk-replace-prompt", { back: "/next", find, replace: repl }, selIds);
      afterMutation();
    },
    deleteLocal: async () => {
      if (!window.confirm(
        "Remove " + selIds.length + " image" + (selIds.length !== 1 ? "s" : "") +
        " from the local catalog? Files move to the _deleted/ folder (recoverable); the cloud task is untouched.")) return;
      await postForm("/delete-bulk", { back: "/next" }, selIds);
      afterMutation();
    },
    deleteCloud: async (ids) => {
      // The typed gate, unchanged: the preview makes the consequence visible,
      // it does not replace the guard.
      const typed = window.prompt("This permanently deletes from PixAI. Type DELETE to confirm:");
      if (typed !== "DELETE") { window.alert("Cancelled."); return; }
      await postForm("/delete-tasks-bulk", { back: "/next" }, ids);
      afterMutation();
    },
  };

  const rate = async (mid, value) => {
    // optimistic; the server clamps 0-5 and answers the stored value
    setItems((old) => old.map((it) => (it.media_id === mid ? { ...it, rating: value } : it)));
    try {
      const { rateImage } = await import("./api.js");
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

  const dockActive = dockOpen && !dockClosing;

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
      <header className="mgx-hdr">
        <Banner
          boot={boot}
          slim={slim}
          running={running}
          dockOpen={dockActive}
          onToggleDock={toggleDock}
          onFolio={() => openOverlay("folio")}
          libraryBar={
            <LibraryBar
              boot={boot} account={account}
              media={media} setMedia={setMedia}
              perPage={perPage} setPerPage={setPerPage}
              shelf={shelf} setShelf={setShelf}
              query={query} setQuery={setQuery} submitQuery={submitQuery} resetAll={resetAll}
              blur={blur} setBlur={setBlur}
              selectMode={selectMode} setSelectMode={setSelectMode}
              selectedCount={selected.size}
              selectedIds={selIds}
              clearSelection={() => setSelected(new Set())}
              collections={collections}
              actions={actions}
              adv={adv} advCount={advCount}
              flyOpen={flyOpen} setFlyOpen={setFlyOpen}
              applyAdvanced={applyAdvanced}
              onGenerate={openDock}
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
        />
      </header>

      <main ref={mainRef} className="mgx-main" style={{ "--thumb": thumb + "px" }}>
        {detailsFor ? (
          <DetailsView
            mediaId={detailsFor} onClose={closeDetails} onNavigate={openDetails}
            onRate={rate} onEdit={requestEdit}
            onDeleted={() => { closeDetails(); load(1, true); }}
            onFilterByModel={filterByModel} onFilterByBatch={filterByBatch}
            advParams={detailsAdvParams}
          />
        ) : (
          <Grid
            items={items} total={total} loading={loading}
            page={page} pages={pages}
            goToPage={(p) => load(p, true)}
            blur={blur}
            thumb={thumb}
            selectMode={selectMode} selected={selected} toggleSelected={toggleSelected}
            openLightbox={setLbIndex}
            onRate={rate}
          />
        )}
      </main>

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
        />
      )}

      {/* OVERLAY MOUNT POINT — the six designed nav overlays land here.
          Health/My Art/Contests are live; Publish/Train/Import are still
          `soon`-dimmed in NavSpine until their own backend routes exist (My
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
        <ContestsOverlay onClose={() => setOverlay(null)} />
      )}
      {overlay === "import" && (
        <ImportOverlay
          onClose={() => setOverlay(null)}
          collections={collections}
          onImported={afterMutation}
        />
      )}
      {overlay === "panel" && (
        <ControlPanelOverlay onClose={() => setOverlay(null)} boot={boot} />
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
    </div>
  );
}
