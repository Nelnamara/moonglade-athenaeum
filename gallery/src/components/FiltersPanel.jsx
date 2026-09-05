import React, { useEffect, useRef, useState } from "react";
import Flyout from "./Flyout.jsx";
import ActionsMenu from "./ActionsMenu.jsx";
import "../styles/librarybar.css";

/* ============================================================================
   The LibraryBar (the Library Bar workstream's deliverable, DC drift §10):
   search field · ⚲ Filters collapse pill (active-count badge, tray on its OWN
   ROW ABOVE the bar) · Clear · Select · Actions — the bar itself never wraps.
   Prop-compatible with Strip.jsx's contract ON PURPOSE (App.jsx mounts it in
   the Banner libraryBar slot).

   HISTORY: until 2026-08-16 this file also carried the art-filters compare
   panel (ArtFiltersPanel) behind a props-keyed dispatcher, because the dock
   imported this module's default export for it. The dock fidelity pass lifted
   that panel into FilterCompare.jsx (rebuilt to the DC's overlay, 591-658) and
   the dispatcher went with it -- the default export is the LibraryBar now.
   ========================================================================== */

/* =============================== LIBRARY BAR ================================ */

/* Tray cycle-chips (DC filterChips). Values are the pilot's REAL filter values
   (Flyout.jsx's SOURCES/SORTS — mirrored here because Flyout doesn't export
   them and Flyout.jsx belongs to another workstream). The Sort chip cycles a
   short everyday subset; the full 12-option list stays in Advanced. Per the
   build map, perPage/shelf "either become tray chips or move into Advanced —
   flag for owner": they are tray chips here until the owner picks. */
const MEDIA_CYCLE = [["", "All"], ["image", "Images"], ["video", "Videos"]];
const SOURCE_CYCLE = [["", "All"], ["online", "PixAI history"], ["api", "Generated"],
  ["local", "Imported"], ["deleted", "Deleted on PixAI"]];
const SORT_CYCLE = ["newest", "oldest", "rating_desc", "aes_desc", "likes"];
const SORT_LABELS = {
  newest: "newest", oldest: "oldest", rating_desc: "highest rated",
  aes_desc: "aesthetic ↓", likes: "most liked",
};
const PER_CYCLE = [50, 100, 200];

/* The LAYOUT icon picker (drift §46) used to live here: its own full-width row at
   the head of this tray, four labelled glyph buttons. B1 of the 2026-09-04
   Gallery Chrome handoff shrank it to an inline strip of 28×28 glyph cells beside
   the SIZE control -- it is SeparatorBar.jsx's LAYOUT_CELLS now (all four layouts,
   Hero included since 2026-09-05), and this tray no longer takes
   `layout`/`setLayout` at all. */

function Chip({ label, active, onClick, title }) {
  return (
    <button type="button" className={"mgl-chip" + (active ? " on" : "")}
      onClick={onClick} title={title}>
      {label}
    </button>
  );
}

function cycleNext(list, cur) {
  const i = list.indexOf(cur);
  return list[(i + 1) % list.length]; // unknown value: (-1+1)=0 -> the baseline entry
}

/* The tray: its own full-width row ABOVE the search bar (DC filtersTrayStyle).
   Commits ride applyAdvanced — App.jsx's existing one-patch commit path — so
   every chip reuses the exact mechanism the Advanced flyout already commits
   through (media/shelf/perPage keys included). */
export function FilterTray({ closing, media, shelf, perPage, adv, collections, models, commit, group, setGroup }) {
  const srcLabel = (SOURCE_CYCLE.find((s) => s[0] === (adv.source || "")) || SOURCE_CYCLE[0])[1];
  const mediaLabel = (MEDIA_CYCLE.find((m) => m[0] === (media || "")) || MEDIA_CYCLE[0])[1];
  const shelfOpts = [""].concat(collections || []);
  const stars = adv.ratingMin || 0;
  /* Model chip (DC filterChips lead with it). The DC cycles a 3-entry
     placeholder list; the real library has dozens of models, so cycling is
     unusable -- the chip opens an anchored list of the library's real models
     instead (owner-disclosed adaptation, 2026-08-01). Commits ride the same
     applyAdvanced path as the Advanced flyout's model field. */
  const [modelMenu, setModelMenu] = useState(null); // {x, y} anchor or null
  const modelBtn = useRef(null);
  useEffect(() => {
    if (!modelMenu) return;
    const onDown = (e) => {
      if (modelBtn.current && modelBtn.current.contains(e.target)) return;
      if (!e.target.closest || !e.target.closest(".mgl-menu")) setModelMenu(null);
    };
    const onKey = (e) => { if (e.key === "Escape") setModelMenu(null); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [modelMenu]);
  const openModelMenu = () => {
    const r = modelBtn.current.getBoundingClientRect();
    // y was clamped on x only, so a button low on the screen opened a menu whose tail ran
    // off the bottom with no way to reach it -- the exact defect #40 fixed for ActionsMenu.
    // .mgl-menu carries a viewport max-height and its own scroll, so flipping above the
    // trigger when there is more room up there always yields something that fits.
    const MENU_MAX = 320;
    const below = window.innerHeight - r.bottom - 18;
    const y = (below < Math.min(MENU_MAX, 180) && r.top > below)
      ? Math.max(10, r.top - Math.min(MENU_MAX, r.top - 18))
      : r.bottom + 8;
    setModelMenu({ x: Math.max(10, Math.min(r.left, window.innerWidth - 252)), y });
  };
  const modelLabel = adv.model ? (adv.model.length > 18 ? adv.model.slice(0, 17) + "…" : adv.model) : "any";
  return (
    <div className={"mgl-tray" + (closing ? " closing" : "")}>
      {/* #34 direction B: fold every session (a multi-task dial-in series, or a
          lone batch's siblings) into ONE cover card. It changes what the grid
          SHOWS, so it belongs with the filters even though the layout picker it
          used to sit beside has moved to the separator bar (B1).
          Reuses the tray Chip vocabulary; `active` lights the metal like any filter. */}
      {setGroup ? (
        <Chip label="Stack sessions" active={group === "series"}
          title="Fold each session -- dial-in series and batches -- into one cover card you can open"
          onClick={() => setGroup(group !== "series")} />
      ) : null}
      <span ref={modelBtn}>
        <Chip label={"Model · " + modelLabel} active={!!adv.model}
          title="Filter by the model that made it"
          onClick={() => (modelMenu ? setModelMenu(null) : openModelMenu())} />
      </span>
      {modelMenu && (
        <div className="mgl-menu" style={{ left: modelMenu.x, top: modelMenu.y, maxHeight: "50vh", overflowY: "auto" }}>
          <div className="mgl-item" onClick={() => { commit({ model: "" }); setModelMenu(null); }}>any</div>
          {(models || []).map((m) => (
            <div key={m} className="mgl-item" onClick={() => { commit({ model: m }); setModelMenu(null); }}>{m}</div>
          ))}
        </div>
      )}
      <Chip label={"Media · " + mediaLabel} active={media !== ""}
        title="Cycle: All → Images → Videos"
        onClick={() => commit({ media: cycleNext(MEDIA_CYCLE.map((m) => m[0]), media || "") })} />
      <Chip label={"Source · " + srcLabel} active={!!adv.source}
        title="Where each file came from"
        onClick={() => commit({ source: cycleNext(SOURCE_CYCLE.map((s) => s[0]), adv.source || "") })} />
      <Chip label={"Sort · " + (SORT_LABELS[adv.sort] || adv.sort)} active={adv.sort !== "newest"}
        title="Everyday sorts — the full list lives in Advanced (▾ on the search field)"
        onClick={() => commit({ sort: cycleNext(SORT_CYCLE, adv.sort) })} />
      <Chip label={"★ " + (stars >= 5 ? "5" : stars + "+")} active={stars > 0}
        title="Minimum rating"
        onClick={() => commit({ ratingMin: (stars + 1) % 6 })} />
      <Chip label={"Collection · " + (shelf || "any")} active={!!shelf}
        title="Cycle through your collections"
        onClick={() => commit({ shelf: cycleNext(shelfOpts, shelf || "") })} />
      <Chip label={"Page · " + perPage} active={perPage !== 100}
        title="Results per page"
        onClick={() => commit({ perPage: cycleNext(PER_CYCLE, perPage) })} />
    </div>
  );
}

/* The library bar (DC drift §10).

   INTERFACE. Sixteen of its props were one object taken apart: it is a view of the LIBRARY --
   filters, query, selection, the flyout -- so it takes `lib`, the useLibrary() return, whole.
   The rest is what the library does not own: `boot` (models, is_true_local), `actions` (App's
   verb table, which the Flyout and the actions menu both read), `collections`, and the two
   optional post-mutation hooks a mount may supply.

   B1 (2026-09-04) took the `layout`/`setLayout` pair back out again: the layout picker moved
   to the separator bar's SIZE group, so this bar no longer touches it.

   B2 (2026-09-04) added `similar`/`onClearSimilar`: when a ◈ door is open, the search slab
   wears the "◈ Similar to [thumb]" token in front of the field, and the match count sits
   beside the bar. The token is the ONE result state every ◈ in the app pushes into.

   Eight props went away entirely rather than being folded in, because nothing here ever read
   them: `account`, `blur`/`setBlur` and `onGenerate` were Strip.jsx swap-in compatibility that
   outlived the swap (the separator bar and banner own blur, credits and Generate); `setMedia`,
   `setPerPage` and `setShelf` were dead because every tray chip commits through applyAdvanced,
   not a setter; `selectedCount` was never read at all. Five of the eight sat behind
   eslint-disable no-unused-vars, which is how they survived this long.

   Strip's Import stub is dropped: the NavSpine carries Import (gated on boot.is_true_local). */
export function LibraryBar({
  lib, boot, actions, collections,
  onSendVideo, onMutated,
  group, setGroup,
  similar, onClearSimilar,
}) {
  const {
    media, perPage, shelf,
    query, setQuery, submitQuery, resetAll,
    selectMode, setSelectMode, selected, setSelected,
    adv, advCount, flyOpen, setFlyOpen, applyAdvanced,
  } = lib;
  // The two selection verbs the bar needs, off the same Set the grid toggles -- App used to
  // spell both out as props and hand down a fresh closure on every render.
  const selectedIds = [...selected];
  const clearSelection = () => setSelected(new Set());

  const [trayOpen, setTrayOpen] = useState(false);
  const [trayClosing, setTrayClosing] = useState(false);
  const trayTimer = useRef(null);
  const searchRef = useRef(null);

  /* the pill's active-count badge: tray-visible filters (media/shelf) plus
     everything advCount already tracks (source/sort/rating/model/…). perPage
     is pagination, not a filter — it never lights the badge. */
  const activeCount = advCount + (media ? 1 : 0) + (shelf ? 1 : 0);

  // DC toggleFilters: mgTrayOut .2s runs on a still-mounted row, THEN unmount
  const toggleTray = () => {
    if (trayOpen && !trayClosing) {
      setTrayClosing(true);
      clearTimeout(trayTimer.current);
      trayTimer.current = setTimeout(() => { setTrayOpen(false); setTrayClosing(false); }, 200);
    } else {
      clearTimeout(trayTimer.current);
      setTrayOpen(true);
      setTrayClosing(false);
    }
  };
  useEffect(() => () => clearTimeout(trayTimer.current), []);

  /* Advanced flyout closes on outside click and Escape (ported verbatim from
     Strip.jsx — owner QA 2026-07-30). Scoped to the search slab so a click on
     the caret itself is never treated as "outside". */
  useEffect(() => {
    if (!flyOpen) return;
    const onDown = (e) => {
      if (searchRef.current && !searchRef.current.contains(e.target)) setFlyOpen(false);
    };
    const onKey = (e) => { if (e.key === "Escape") setFlyOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [flyOpen, setFlyOpen]);

  /* DC's Clear, copy-true to its title ("Clear the current filter and
     selection"): filters + query + selection + select mode, one press. The
     pilot's separate Reset button folds into this — flagged for the owner. */
  const clearAll = () => {
    resetAll();
    clearSelection();
    setSelectMode(false);
  };

  const trayShown = trayOpen || trayClosing;

  return (
    <div className="mgl-wrap">
      {trayShown && (
        <FilterTray
          closing={trayClosing}
          media={media} shelf={shelf} perPage={perPage} adv={adv}
          collections={collections}
          models={boot.models || []}
          commit={applyAdvanced}
          group={group} setGroup={setGroup}
        />
      )}
      <div className="mgl-bar">
        <div className={"mgl-search" + (flyOpen ? " open" : "") + (similar ? " simon" : "")} ref={searchRef}>
          {/* B2 -- the ◈ token. Every Similar door in the app (tile hover, lightbox
              row, right-click, the Details strip) pushes THIS, and only this: the
              source picture's own thumb, the mark, and a ✕. It is a state badge on
              the library, not a query -- the field, the filters and the page the
              grid was on are all untouched underneath, which is what lets ✕/Esc
              restore the previous view exactly rather than re-running anything. */}
          {similar ? (
            <span className="mgl-simtok" title="Showing what looks like this picture">
              <img className="mgl-simtok-th" src={similar.thumb} alt="" loading="lazy" decoding="async" />
              <span className="mgl-simtok-lbl">◈ Similar to this</span>
              <button type="button" className="mgl-simtok-x" title="Back to the library (Esc)"
                aria-label="Clear the Similar view"
                onClick={onClearSimilar}>✕</button>
            </span>
          ) : null}
          <i className="mgl-sglyph" onClick={() => submitQuery()} title="Search">⌕</i>
          <input
            value={query}
            placeholder="search the library — night*, an id, model:tsubaki…"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submitQuery()}
          />
          <button
            type="button"
            className={"mgl-scaret" + (flyOpen ? " open" : "")}
            onClick={() => setFlyOpen(!flyOpen)}
            aria-expanded={flyOpen}
            title="Advanced search, operators and saved views"
          >
            ▾
          </button>
          {flyOpen && (
            <Flyout
              boot={boot}
              current={adv}
              onApply={applyAdvanced}
              onClose={() => setFlyOpen(false)}
              onPrintCollection={actions && actions.printCollection}
              onSaveView={actions && actions.saveView}
              onDeleteView={actions && actions.deleteView}
              buildViewQuery={actions && actions.buildViewQuery}
            />
          )}
        </div>

        {/* B2 -- the count beside the token, emerald, mono. It says by what: these
            are matches by likeness, not by the query in the field beside it. */}
        {similar ? (
          <span className="mgl-simcount">
            {similar.loading ? "finding lookalikes…"
              : similar.count + (similar.count === 1 ? " match" : " matches") + " · by likeness"}
          </span>
        ) : null}

        <button
          type="button"
          className={"mgl-pill mgl-filters"
            + (trayOpen && !trayClosing ? " open" : "")
            + (activeCount ? " lit" : "")}
          onClick={toggleTray}
          aria-expanded={trayOpen && !trayClosing}
          title="Show or hide the library filters"
        >
          <span>⚲ Filters{activeCount ? " · " + activeCount : ""}</span>
          <span className="mgl-caret8">{trayOpen && !trayClosing ? "◂" : "▸"}</span>
        </button>

        <button type="button" className="mgl-pill mgl-clear" onClick={clearAll}
          title="Clear the current filter and selection">
          Clear
        </button>

        <button
          type="button"
          className={"mgl-pill" + (selectMode ? " on" : "")}
          onClick={() => setSelectMode(!selectMode)}
          title="Select mode: click images to toggle them"
        >
          Select: {selectMode ? "ON" : "OFF"}
        </button>

        <ActionsMenu
          ids={selectedIds}
          shelf={shelf}
          isTrueLocal={boot.is_true_local}
          onSendCast={actions && actions.sendCast}
          onPrintSheet={actions && actions.printSheet}
          onDownloadZip={actions && actions.downloadZip}
          clearSelection={clearSelection}
          onSendVideo={onSendVideo}
          onMutated={onMutated}
        />
      </div>
    </div>
  );
}

/* ============================== DEFAULT EXPORT ==============================
   The LibraryBar. (This file used to also carry the art-filters compare panel and a
   props-keyed dispatcher for it; the 2026-08-16 dock fidelity pass lifted that panel
   into FilterCompare.jsx, rebuilt to the DC's overlay -- see that file.) */
export default LibraryBar;
