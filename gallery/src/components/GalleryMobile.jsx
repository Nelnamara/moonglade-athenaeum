import React, { useEffect, useRef, useState } from "react";
import { ADV_DEFAULTS } from "../hooks/useLibrary.js";
import useSheet from "../hooks/useSheet.js";
import GalleryGridMobile from "./GalleryGridMobile.jsx";
import MobileSheet from "./MobileSheet.jsx";
import ActionsMenu from "./ActionsMenu.jsx";
import SimilarResults from "./SimilarResults.jsx";
import "../styles/gallery-mobile.css";

/* The Gallery tab (design spec: Moonglade Mobile.dc.html isGallery block, lines
   65-107 & 912-934) -- the one fully-real tab this increment ships. Every
   field the DC shows is wired to useLibrary()'s real state/load/applyAdvanced
   (lifted to AppMobile.jsx, passed down as props -- exactly how Grid.jsx/
   FiltersPanel.jsx read App.jsx's single useLibrary() instance on desktop, so
   filters/selection survive a Gallery <-> Create/Control tab switch instead of
   resetting on every remount): the search box, the media pills, the Sort sheet,
   the Advanced Search sheet's 8 fields (Collection/Sort/Model/LoRA/From/To/Min
   rating/Per page -- the DC's own `searchFields` list, no more, no fewer), and
   the Actions sheet's bulk actions (ActionsMenu.jsx mounted as-is per this
   increment's brief point 6 -- its own trigger button is auto-clicked once the
   sheet opens so the real dropdown appears without a redundant second tap, and
   the sheet auto-closes if a mutation empties the selection out from under it).

   ENTRY POINT (2026-08-03): a plain tap on a tile OUTSIDE select mode now
   opens the real full-screen viewer (LightboxMobile.jsx, wired by
   AppMobile.jsx via the onOpenLightbox prop) -- per Moonglade Mobile.dc.html's
   own tap(i) handler and issue #35; an earlier revision of this comment
   claimed tap->Details was the design and the owner corrected it. Image
   Details Mobile (ImageDetailsMobile.jsx) stays one tap away via the
   lightbox's "Details ›" pill (and select-mode taps still toggle selection,
   per the gesture layer below). See AppMobile.jsx's own header comment
   for the lbIndex/detailsFor wiring.

   CONTACT SHEET ENTRY POINT (2026-08-03): ActionsMenu's "▤ Print sheet" item
   now gets a real `onPrintSheet` prop -- closes this file's own Actions sheet
   and calls AppMobile.jsx's lifted onOpenContactSheet(selIds) in the same
   click (mirroring desktop App.jsx's `printSheet: () => openContactSheet
   (selIds)`), opening the real ContactSheetMobile.jsx full-screen destination
   instead of ActionsMenu's own desktop-shaped fallback (a bare window.open of
   the classic print page). See AppMobile.jsx's own header comment for the
   contactSheetTarget wiring.

   ◈ SIMILAR (2026-09-05): this tab is where the phone's Similar ANSWER lands,
   the same way the desktop's <main> is. AppMobile.jsx owns the id, the fetch and
   both dismiss paths (see its header comment); this renders the two halves the
   desktop renders -- the dismissible ◈ token in the search bar, and
   <SimilarResults> (the shared component, not a mobile fork) in the grid's
   place. The token wraps onto its own line inside .glm-bar rather than sitting
   in front of the field the way desktop's does: desktop's search slab grows to a
   430px basis to make room, and a 390px phone bar has none to give -- the field
   would be crushed to a few characters. Same token, same thumb, same ✕, one line
   lower. Nothing about the library's own state changes while it is up, so ✕ is
   the whole way back. */

const MEDIA_PILLS = [["", "All"], ["image", "Images"], ["video", "Videos"]];
const SORT_OPTS = [
  ["newest", "Newest first"], ["oldest", "Oldest first"],
  ["rating_desc", "Rating"], ["likes", "Most liked"],
];
const PER_PAGE_OPTS = [50, 100, 200];

/* useSheet moved to hooks/useSheet.js (2026-08-07) -- this file's private copy
   was the ONE correct implementation of the MobileSheet timer dance, promoted
   to shared so every other caller stops hand-rolling the racy version. */

export default function GalleryMobile({
  boot, collections, refreshCollections,
  media, shelf, perPage,
  query, setQuery, submitQuery,
  adv, applyAdvanced,
  items, total, page, pages, loading, load,
  selectMode, setSelectMode, selected, setSelected, toggleSelected,
  onOpenDetails, onOpenLightbox, onOpenContactSheet,
  similar, similarState, similarSource, onSimilar, onClearSimilar,
}) {
  const { sheet, closing, open: openSheet, close: closeSheet } = useSheet();
  const [draft, setDraft] = useState(() => ({ ...adv, shelf, perPage }));
  const actionsHostRef = useRef(null);

  // Refreshed at open-time (below), then left alone until Apply/Clear commits --
  // same call Flyout.jsx's own draft makes (its `useEffect(() => setD(current),
  // [current])`), because within one open sheet nothing else mutates adv/shelf/
  // perPage out from under an in-progress edit.
  const openSearchSheet = () => { setDraft({ ...adv, shelf, perPage }); openSheet("search"); };

  const applyDraft = () => {
    applyAdvanced({
      sort: draft.sort, ratingMin: draft.ratingMin, model: draft.model, lora: draft.lora,
      dateFrom: draft.dateFrom, dateTo: draft.dateTo,
      shelf: draft.shelf, perPage: draft.perPage,
    });
    closeSheet();
  };
  const clearDraft = () => {
    applyAdvanced({ ...ADV_DEFAULTS, shelf: "", perPage: 100 });
    closeSheet();
  };

  const toggleSelectMode = () => { setSelectMode(!selectMode); setSelected(new Set()); };
  const selIds = [...selected];

  // The Actions sheet only ever opens with a selection; if a mutation (or the
  // "Clear" pill) empties it out while the sheet is up, follow it closed rather
  // than leave an empty "0 SELECTED" sheet stranded open.
  useEffect(() => {
    if (sheet === "actions" && selected.size === 0) closeSheet();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, sheet]);

  // ActionsMenu.jsx is mounted as-is (this increment's brief, point 6) -- its
  // own "Actions (N)" trigger button is auto-clicked the moment the sheet
  // mounts, so the real dropdown menu appears without a redundant second tap.
  // The trigger stays in the DOM (inside the sheet) as a fallback if the user
  // dismisses that dropdown and wants it back.
  useEffect(() => {
    if (sheet !== "actions") return;
    const t = setTimeout(() => {
      const btn = actionsHostRef.current && actionsHostRef.current.querySelector(".mgl-actbtn");
      if (btn) btn.click();
    }, 60);
    return () => clearTimeout(t);
  }, [sheet]);

  const armSelect = (mid) => {
    setSelectMode(true);
    setSelected((old) => { const s = new Set(old); s.add(mid); return s; });
    if (navigator.vibrate) { try { navigator.vibrate(12); } catch { /* unsupported/blocked */ } }
  };
  // #35 (owner: "That was NOT the design"): a plain tap opens the LIGHTBOX, matching
  // Moonglade Mobile.dc.html:988-990's own tap(i) -> Lightbox Mobile. Details stays one
  // tap away via the lightbox's "Details ›" pill (openDetailsFromLightbox). The
  // earlier tap->Details wiring was drift, not design.
  const tapView = (mid) => (onOpenLightbox || onOpenDetails)(mid);

  return (
    <div className="glm-tab glm-tab-gallery">
      <div className="glm-bar">
        <div className="glm-search">
          <span className="glm-search-icon" onClick={() => submitQuery()} title="Search">⚲</span>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") submitQuery(); }}
            placeholder="words, night* wildcard, an id…"
          />
          <button type="button" className="glm-search-adv" onClick={openSearchSheet}>Advanced</button>
        </div>
        <button type="button" className={"glm-metal" + (selectMode ? " on" : "")} onClick={toggleSelectMode}>
          {selectMode ? "Cancel" : "Select"}
        </button>
        {/* The ◈ token -- every phone door pushes THIS and only this: the source
            picture's own thumb, the mark, a ✕, and the match count beside it. It is a
            state badge on the library, not a query: the field above, the filters and
            the page are untouched underneath, which is what lets ✕ (or the Back
            gesture) restore the previous view exactly rather than re-running
            anything. */}
        {similar ? (
          <div className="glm-simrow">
            <span className="glm-simtok" title="Showing what looks like this picture">
              <img className="glm-simtok-th" src={similar.thumb} alt="" loading="lazy" decoding="async" />
              <span className="glm-simtok-lbl">◈ Similar to this</span>
              <button type="button" className="glm-simtok-x" title="Back to the library"
                aria-label="Clear the Similar view" onClick={onClearSimilar}>✕</button>
            </span>
            <span className="glm-simcount">
              {similar.loading ? "finding lookalikes…"
                : similar.count + (similar.count === 1 ? " match" : " matches") + " · by likeness"}
            </span>
          </div>
        ) : null}
      </div>

      <div className="glm-bar2">
        {MEDIA_PILLS.map(([v, label]) => (
          <button key={label} type="button" className={"glm-metal" + (media === v ? " on" : "")}
            onClick={() => applyAdvanced({ media: v })}>
            {label}
          </button>
        ))}
        {selectMode ? (
          <>
            <button type="button" className="glm-metal" onClick={() => setSelected(new Set())}>Clear</button>
            <span className="glm-selcount"><b>{selected.size}</b> selected</span>
            {selected.size > 0 && (
              <button type="button" className="glm-metal glm-pill-accent" onClick={() => openSheet("actions")}>
                Actions
              </button>
            )}
          </>
        ) : (
          <button type="button" className="glm-metal glm-pill-auto" onClick={() => openSheet("sort")}>
            Sort ▾
          </button>
        )}
      </div>

      {similar ? (
        /* The lookalikes take the GRID's place, in the same column, under the same
           bar -- which is now wearing the ◈ token. The library's own state is not
           touched while this is up, so clearing the token is the entire way back;
           nothing is re-fetched and nothing has moved. The pager goes with the grid:
           a lookalike set is one answer, not a paged library. */
        <SimilarResults
          source={similarSource}
          state={similarState}
          onOpenDetails={onOpenDetails}
          onSimilar={onSimilar}
          onClear={onClearSimilar}
        />
      ) : (
        <GalleryGridMobile
          items={items} loading={loading} selectMode={selectMode} selected={selected}
          toggleSelected={toggleSelected} onArmSelect={armSelect} onTapView={tapView}
        />
      )}

      {!similar && !loading && pages > 1 && (
        <nav className="glm-pager" aria-label="Pages">
          <button type="button" className="glm-metal" disabled={page <= 1} onClick={() => load(page - 1, true)}>
            ‹ Prev
          </button>
          <span className="glm-pager-info">
            Page {page} of {pages}
            {total != null ? <> · {Number(total).toLocaleString()} match{total === 1 ? "" : "es"}</> : null}
          </span>
          <button type="button" className="glm-metal" disabled={page >= pages} onClick={() => load(page + 1, true)}>
            Next ›
          </button>
        </nav>
      )}

      <MobileSheet open={sheet === "search"} closing={closing} onClose={closeSheet} title="ADVANCED SEARCH">
        <div className="glm-legend">
          <div className="glm-legend-cap">these already work — nothing tells you so</div>
          <div className="glm-legend-line"><code>night*</code> wildcard · <code>model:tsubaki</code> by model</div>
          <div className="glm-legend-line"><code>2038314167804392533</code> a task or media id</div>
        </div>
        <div className="glm-field2">
          <label className="glm-field">
            <span>Collection</span>
            <select value={draft.shelf} onChange={(e) => setDraft((d) => ({ ...d, shelf: e.target.value }))}>
              <option value="">Any collection</option>
              {(collections || []).map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </label>
          <label className="glm-field">
            <span>Sort</span>
            <select value={draft.sort} onChange={(e) => setDraft((d) => ({ ...d, sort: e.target.value }))}>
              {SORT_OPTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </label>
          <label className="glm-field">
            <span>Model</span>
            <input value={draft.model} list="glm-models"
              onChange={(e) => setDraft((d) => ({ ...d, model: e.target.value }))}
              placeholder="All models" />
          </label>
          <label className="glm-field">
            <span>LoRA</span>
            <input value={draft.lora} onChange={(e) => setDraft((d) => ({ ...d, lora: e.target.value }))}
              placeholder="lora name…" />
          </label>
          <label className="glm-field">
            <span>From</span>
            <input type="month" value={draft.dateFrom}
              onChange={(e) => setDraft((d) => ({ ...d, dateFrom: e.target.value }))} />
          </label>
          <label className="glm-field">
            <span>To</span>
            <input type="month" value={draft.dateTo}
              onChange={(e) => setDraft((d) => ({ ...d, dateTo: e.target.value }))} />
          </label>
          <label className="glm-field">
            <span>Min rating</span>
            <select value={draft.ratingMin}
              onChange={(e) => setDraft((d) => ({ ...d, ratingMin: Number(e.target.value) }))}>
              <option value={0}>Any</option>
              {[1, 2, 3, 4, 5].map((r) => <option key={r} value={r}>{"★".repeat(r)}+</option>)}
            </select>
          </label>
          <label className="glm-field">
            <span>Per page</span>
            <select value={draft.perPage}
              onChange={(e) => setDraft((d) => ({ ...d, perPage: Number(e.target.value) }))}>
              {PER_PAGE_OPTS.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>
        <datalist id="glm-models">{(boot.models || []).map((m) => <option key={m} value={m} />)}</datalist>
        <div className="glm-sheet-actions">
          <button type="button" className="glm-metal glm-widebtn" onClick={clearDraft}>Clear</button>
          <button type="button" className="glm-primary" onClick={applyDraft}>Apply</button>
        </div>
      </MobileSheet>

      <MobileSheet open={sheet === "sort"} closing={closing} onClose={closeSheet} title="SORT">
        <div className="glm-sheet-list">
          {SORT_OPTS.map(([v, label]) => (
            <button key={v} type="button" className={"glm-metal glm-sheetopt" + (adv.sort === v ? " on" : "")}
              onClick={() => { applyAdvanced({ sort: v }); closeSheet(); }}>
              {label}
            </button>
          ))}
        </div>
      </MobileSheet>

      <MobileSheet open={sheet === "actions"} closing={closing} onClose={closeSheet}
        title={selected.size + " SELECTED"}>
        <div ref={actionsHostRef} className="glm-actions-host">
          <ActionsMenu
            ids={selIds}
            shelf={shelf}
            isTrueLocal={boot.is_true_local}
            clearSelection={() => { setSelected(new Set()); closeSheet(); }}
            onMutated={refreshCollections}
            onPrintSheet={() => { closeSheet(); onOpenContactSheet(selIds); }}
          />
        </div>
      </MobileSheet>
    </div>
  );
}
