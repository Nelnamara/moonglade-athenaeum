import React, { useEffect, useRef, useState } from "react";
import Icon from "../icons/Icons.jsx";
import { ADV_DEFAULTS } from "../hooks/useLibrary.js";
import useSheet from "../hooks/useSheet.js";
import GalleryGridMobile from "./GalleryGridMobile.jsx";
import ContinuousGridMobile from "./ContinuousGridMobile.jsx";
import { NudgeStrip } from "./InstallNudge.jsx";
import MobileSheet from "./MobileSheet.jsx";
import ActionsMenu from "./ActionsMenu.jsx";
import SimilarResults from "./SimilarResults.jsx";
import CurationSheetMobile from "./CurationSheetMobile.jsx";
import PullToRefresh from "./PullToRefresh.jsx";
import LayoutPagingSheet from "./LayoutPagingSheet.jsx";
import useDataSaver, { useFeedLayout, usePaging, usePagingHint } from "../hooks/usePhonePrefs.js";
import usePhoneLandscape from "../hooks/usePhoneLandscape.js";
import useScrollAnchor from "../hooks/useScrollAnchor.js";
import {
  KEY_LONG_PRESS_MS, RANGE_CARD_MS, allLoadedLabel, continuousDone, countLabel, endLabel, footerState, nearEnd,
  newSince, newSinceLabel, newestLabel, pageOffset, pagerInView, rangeCardText, rangeOf, showNewest, splitRange,
} from "../lib/phoneCore.js";
import { ASPECT_CHOICES, aspectError, aspectIn, parseAspect, withAspect } from "../curation/aspectCore.js";
import { canSaveSmart, checkTag } from "../curation/curationCore.js";
import "../styles/gallery-mobile.css";
import "../styles/curation-mobile.css";
import "../styles/phone-q.css";

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
   the whole way back.

   SESSION Q, THE PHONE (2026-09-29; Phone Handoff.dc.html), all additive:
     Q3  the Grid | Feed toggle in the pill row (saved per device -- hooks/usePhonePrefs.js); the
         feed itself is GalleryGridMobile's `layout="feed"`.
     Q5  the "N new since HH:MM" rule and the "↑ Newest" jump. The shell hands down the marker it read
         when it opened and whether this is the library's own front page; the count and the label are
         lib/phoneCore.js's, and the rule is only ever drawn there (page 1, newest first, unfiltered).
     Q6  pull to refresh: the whole tab body sits in <PullToRefresh>, and `onPullRefresh` -- the shell's
         "Sync now" plus a reload of the page in view -- is what a release past the line runs.
     Q7  `saver` (Data saver active) makes the grid draw 256 px thumbnails.
     Q4  landscape: the grid deals its pictures across 4 columns (3 under 700 px wide) and a turn of the
         phone keeps your place -- the picture at the top of the view is scrolled back to the same spot
         once the columns have re-flowed (hooks/useScrollAnchor.js). The rail, the side panels and the
         rest of the layout are CSS (styles/phone-landscape.css).

   SESSION U, PHONE PAGING (2026-10-03; Phone Paging and Nudge Handoff.dc.html), additive:
     U1  a long-press (500 ms) on either ▦ / ▭ key opens LayoutPagingSheet -- Layout and Paging (Pages |
         Continuous), per device -- while a tap on a key still only switches the layout. A hairline dot
         under the keys until the first long-press, so the gesture is found once.
     U2  Continuous (`continuous`): "N of M" in mono before the layout keys; no pager; a quiet footer
         instead -- the spinner line while the next page is in flight, the peach "Couldn't load more.
         Retry" after a failure (Retry is one request; nothing retries by itself), "That's all M." at the
         end. The next page is asked for (`onLoadMore`, the shell's) when the footer comes within 1.5
         screens of the bottom of the view, one request at a time; `more` is that request's state.
     U4  the stacked list is ContinuousGridMobile: at most five pages of 100 in the DOM, exact-height
         spacers for the rest. `reveal` is the shell's ask to bring a picture back into view after the
         viewer closes on it.
     U5  selection across pages (Session N's select mode, kept): ticks are kept by id. In select mode a
         second long-press selects every place between the last ticked tile and the pressed one, by
         absolute index in the filtered walk, loaded or not; when some are not loaded a card says
         "Selected N, including K not loaded yet." for 4 s and their ids are read (useLibrary.idsAt) --
         Actions waits for that read, so every confirm states the full count. Continuous's bar adds
         "All loaded (L)", and there a filter change clears the selection with a 10 s Undo.

   SESSION U, THE HOME SCREEN NUDGE (U6c): `nudge` is the shell's useInstallNudge. Once, after a sign-in,
   on a phone browser that can add the app to its Home Screen, its 36 px strip sits under the pill row
   and pushes the grid down; its tap opens the steps (the shell draws the iOS bubble), its ✕ waves it
   off for good on this phone. */

/* A long-press that moves further than this is a scroll or a drag, not a hold. */
const KEY_MOVE_CANCEL_PX = 10;

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
  query, setQuery, submitQuery, applied,
  adv, applyAdvanced,
  /* `pages` is renamed on the way in: in Continuous there is no pager, so the pager's own reads see 1. */
  items, total, page, pages: pageCount, loading, load,
  selectMode, setSelectMode, selected, setSelected, toggleSelected,
  onOpenDetails, onOpenLightbox, onOpenContactSheet,
  similar, similarState, similarSource, onSimilar, onClearSimilar,
  /* Session Q: the shell's marker (what "new since" measures from), whether the view is the library's
     own front page, and what a pull runs. */
  marker, frontPage, onPullRefresh,
  /* Session U: Continuous paging, the shell's next-page request and its state ({busy, failed}). */
  continuous = false, onLoadMore, more, reveal, idsAt, nudge,
  /* Session N: what curation hands this tab -- {smart, curate, saveSmart, composeView, strip}.
     smart is the saved searches ({name, query}) listed in the Collection field with the refresh
     mark; curate is the shell's useCurate (the bulk verbs and their undo toast); saveSmart and
     composeView are N1's "Save as smart collection"; strip is the bar over the grid while a
     smart collection is open or being edited. */
  curation,
}) {
  const { sheet, closing, open: openSheet, close: closeSheet } = useSheet();
  /* Session P (P6): a hand-picked collection's view offers its manual order as a sort (a smart
     collection's membership is live, so it does not). */
  const handShelf = !!shelf && (collections || []).indexOf(shelf) >= 0;
  const sortOpts = handShelf || adv.sort === "manual" ? SORT_OPTS.concat([["manual", "Manual order"]]) : SORT_OPTS;
  const hasCuration = !!curation;
  const [layout, setLayout] = useFeedLayout();
  const [paging, setPaging] = usePaging();
  const pages = continuous ? 1 : pageCount;
  const [hintSeen, markHintSeen] = usePagingHint();
  /* U1: the layout keys' long-press. A tap that outlasts KEY_LONG_PRESS_MS opens the sheet instead of
     switching, and the click the browser may still deliver after it is swallowed once. */
  const keyTimer = useRef(null);
  const keyLong = useRef(false);
  const keyStart = useRef(null);
  const cancelKey = () => { clearTimeout(keyTimer.current); keyTimer.current = null; keyStart.current = null; };
  useEffect(() => () => clearTimeout(keyTimer.current), []);
  const keyPress = {
    onPointerDown: (e) => {
      if (e.pointerType === "mouse" && e.button !== 0) return;
      cancelKey();
      keyLong.current = false;
      keyStart.current = { x: e.clientX, y: e.clientY };
      keyTimer.current = setTimeout(() => {
        keyTimer.current = null;
        keyLong.current = true;
        markHintSeen();
        openSheet("paging");
        if (navigator.vibrate) { try { navigator.vibrate(12); } catch { /* unsupported/blocked */ } }
      }, KEY_LONG_PRESS_MS);
    },
    onPointerMove: (e) => {
      const s = keyStart.current;
      if (s && (Math.abs(e.clientX - s.x) > KEY_MOVE_CANCEL_PX || Math.abs(e.clientY - s.y) > KEY_MOVE_CANCEL_PX)) cancelKey();
    },
    onPointerUp: cancelKey,
    onPointerLeave: cancelKey,
    onPointerCancel: cancelKey,
    onContextMenu: (e) => e.preventDefault(),
  };
  const tapKey = (v) => {
    if (keyLong.current) { keyLong.current = false; return; }
    setLayout(v);
  };
  const saver = useDataSaver().active;
  const rootRef = useRef(null);
  const { landscape, cols } = usePhoneLandscape();
  useScrollAnchor(rootRef, ".glm-body", (landscape ? "L" : "P") + cols);
  const ns = frontPage ? newSince(items, marker) : { count: 0, capped: false };
  const ruleText = newSinceLabel(ns.count, ns.capped, marker && marker.at);
  /* "↑ Newest" -- after one screen of scrolling, on the tab's own scroller (.glm-body). The state only
     changes when the threshold is crossed, so a scroll is not a render. It steps aside while the pager
     row is on screen (owner's walk, 2026-10-03: it sat on the pager and hid its middle). */
  const [jump, setJump] = useState(false);
  useEffect(() => {
    const host = rootRef.current && rootRef.current.closest(".glm-body");
    if (!host) return undefined;
    let on = false;
    const onScroll = () => {
      const pager = host.querySelector(".glm-pager, .glm-cfoot");
      const v = showNewest(host.scrollTop, host.clientHeight)
        && !pagerInView(pager && pager.getBoundingClientRect(), host.getBoundingClientRect());
      if (v !== on) { on = v; setJump(v); }
    };
    host.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    onScroll();
    return () => { host.removeEventListener("scroll", onScroll); window.removeEventListener("resize", onScroll); };
  }, []);
  const toNewest = () => {
    const host = rootRef.current && rootRef.current.closest(".glm-body");
    if (!host) return;
    const calm = typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    host.scrollTo({ top: 0, behavior: calm ? "auto" : "smooth" });
  };
  /* U2: the footer's state, and the trigger that asks for the next page. A scroll (and a page landing,
     which may leave the footer still in reach) checks once per frame whether the footer is within 1.5
     screens of the view; nothing asks while a page is in flight, after a failure (until Retry), at the
     end, or before the first page has landed. */
  const moreBusy = !!(more && more.busy);
  const moreFailed = !!(more && more.failed);
  const done = continuousDone(items.length, total);
  const foot = footerState({ busy: moreBusy, failed: moreFailed, done });
  const want = useRef(null);
  want.current = continuous && !similar && !loading && total != null && foot === "idle" ? onLoadMore : null;
  const checkMore = useRef(() => {});
  useEffect(() => {
    if (!continuous) return undefined;
    const host = rootRef.current && rootRef.current.closest(".glm-body");
    if (!host) return undefined;
    let raf = 0;
    const check = () => {
      raf = 0;
      const ask = want.current;
      const footEl = host.querySelector(".glm-cfoot");
      if (!ask || !footEl) return;
      if (nearEnd(footEl.getBoundingClientRect().top, host.getBoundingClientRect().bottom, host.clientHeight)) ask();
    };
    const onScroll = () => { if (!raf) raf = requestAnimationFrame(check); };
    checkMore.current = onScroll;
    host.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    onScroll();
    return () => {
      if (raf) cancelAnimationFrame(raf);
      checkMore.current = () => {};
      host.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [continuous]);
  useEffect(() => { checkMore.current(); }, [items.length, foot, loading, similar]);
  const count = continuous ? countLabel(items.length, total) : "";
  const [draft, setDraft] = useState(() => ({ ...adv, shelf, perPage }));
  const actionsHostRef = useRef(null);

  // Refreshed at open-time (below), then left alone until Apply/Clear commits --
  // same call Flyout.jsx's own draft makes (its `useEffect(() => setD(current),
  // [current])`), because within one open sheet nothing else mutates adv/shelf/
  // perPage out from under an in-progress edit.
  /* The Aspect chips (Session N7) are not a filter of their own: they are the search text's
     `ar:` token, read out of the field when the sheet opens and written back on Apply, so what
     the sheet shows and what the grid filters by cannot disagree. Only a CHANGED choice rewrites
     the text, so Apply never re-submits a half-typed search for nothing. */
  const openSearchSheet = () => { setDraft({ ...adv, shelf, perPage, aspect: aspectIn(query) }); openSheet("search"); };

  const applyDraft = () => {
    const patch = {
      sort: draft.sort, ratingMin: draft.ratingMin, model: draft.model, lora: draft.lora,
      dateFrom: draft.dateFrom, dateTo: draft.dateTo,
      shelf: draft.shelf, perPage: draft.perPage,
    };
    if ((draft.aspect || "") !== aspectIn(query)) patch.q = withAspect(query, draft.aspect || "");
    applyAdvanced(patch);
    closeSheet();
  };
  const arErr = aspectError(query);
  /* N1: save what the sheet shows -- the search field, the media pill, every filter here that
     has an operator -- as a smart collection. It stores the QUERY, never a list of pictures,
     and opens the new collection. The draft's own aspect and Collection choices are honoured
     (a smart collection open in the field is its own query, so it adds no collection: term). */
  const aspectChanged = (draft.aspect || "") !== aspectIn(query);
  const sheetQuery = curation ? curation.composeView(
    aspectChanged ? withAspect(query, draft.aspect || "") : query,
    { adv: { ...adv, ...draft }, shelf: draft.shelf }) : "";
  const canSaveThis = canSaveSmart(sheetQuery);
  const saveSmartFromSheet = async () => {
    if (!curation || !canSaveThis) return;
    const ok = await curation.saveSmart(sheetQuery);
    if (ok) closeSheet();
  };
  const clearDraft = () => {
    applyAdvanced({ ...ADV_DEFAULTS, shelf: "", perPage: 100 });
    closeSheet();
  };

  /* U5: the last ticked tile, at its absolute place in the walk (`offset` is the place of the loaded
     list's first picture: 0 for a stacked list). A range read that lands after the list changed adds
     nothing (`listToken`). */
  const anchor = useRef(null);
  const listToken = useRef(0);
  const offset = continuous ? 0 : pageOffset(page, perPage);
  const placeOf = (mid) => { const i = items.findIndex((it) => it.media_id === mid); return i < 0 ? -1 : offset + i; };
  const [card, setCard] = useState("");
  const [resolving, setResolving] = useState(0);
  useEffect(() => {
    if (!card) return undefined;
    const t = setTimeout(() => setCard(""), RANGE_CARD_MS);
    return () => clearTimeout(t);
  }, [card]);
  const addIds = (ids) => setSelected((old) => {
    const s = new Set(old);
    ids.forEach((m) => s.add(m));
    return s;
  });
  const selectRange = (mid) => {
    const b = placeOf(mid);
    const a = anchor.current;
    if (b < 0 || !a || a.at < 0) return false;
    const { lo, hi } = rangeOf(a.at, b);
    const part = splitRange(lo, hi, offset, items.length);
    if (part.to >= part.from) addIds(items.slice(part.from - offset, part.to - offset + 1).map((it) => it.media_id));
    anchor.current = { mid, at: b };
    if (!part.k) return true;
    setCard(rangeCardText(part.n, part.k));
    const gaps = part.to < part.from ? [[lo, hi]] : [[lo, part.from - 1], [part.to + 1, hi]].filter(([x, y]) => y >= x);
    const token = listToken.current;
    gaps.forEach(([x, y]) => {
      setResolving((r) => r + 1);
      idsAt(x, y).then((ids) => {
        if (token !== listToken.current) return;
        if (ids) addIds(ids);
        else if (curation) curation.curate.say("Couldn't read the pictures that are not loaded, so they are not selected.", null, "peach");
      }).finally(() => setResolving((r) => Math.max(0, r - 1)));
    });
    return true;
  };
  const tapToggle = (mid) => {
    if (!selected.has(mid)) anchor.current = { mid, at: placeOf(mid) };
    else if (anchor.current && anchor.current.mid === mid) anchor.current = null;
    toggleSelected(mid);
  };
  const clearSelection = () => { anchor.current = null; setSelected(new Set()); };
  const selectAllLoaded = () => addIds(items.map((it) => it.media_id));
  /* Continuous: a filter change starts a new list, and a selection is a promise about pictures you can
     still see, so it is cleared -- with a 10 s Undo that hands it back. (Pages keeps it, as shipped.) */
  const listKey = [applied, media, shelf, JSON.stringify(adv)].join("|");
  const seenKey = useRef(listKey);
  useEffect(() => {
    if (seenKey.current === listKey) return;
    seenKey.current = listKey;
    listToken.current += 1;
    anchor.current = null;
    if (!continuous || !selected.size || !curation) return;
    const prev = selected;
    setSelected(new Set());
    curation.curate.say("The filter changed, so the selection was cleared.", null, "", () => setSelected(prev));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [listKey]);

  const toggleSelectMode = () => { anchor.current = null; setSelectMode(!selectMode); setSelected(new Set()); };
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
  /* ...EXCEPT WHEN THE SHEET LEADS WITH THE CURATION BLOCK (Session N4). The dropdown is
     anchored to that trigger and opens over whatever is above it, which would sit on top of the
     stars, the marks and the tag field the sheet now opens with. Curation goes first, then the
     same trigger, one tap, for the rest of the list. */
  useEffect(() => {
    if (sheet !== "actions" || hasCuration) return;
    const t = setTimeout(() => {
      const btn = actionsHostRef.current && actionsHostRef.current.querySelector(".mgl-actbtn");
      if (btn) btn.click();
    }, 60);
    return () => clearTimeout(t);
  }, [sheet, hasCuration]);

  /* N4 on the phone: the stars, a tag and Keeper / Reject over the selection, from the top of
     the Actions sheet. Each goes through useCurate (an honest count, a 10 s Undo in the toast) and
     the sheet steps aside so the toast and the grid are what you see; the selection stays. */
  const bulk = curation ? {
    star: (n) => { curation.curate.apply(selIds, { rating: n }, true); closeSheet(); },
    tag: (raw) => {
      const chk = checkTag(raw, []);
      if (!chk.ok) { curation.curate.say(chk.error, null, "peach"); closeSheet(); return; }
      curation.curate.apply(selIds, { add_tag: chk.tag }, true);
      closeSheet();
    },
    keeper: () => { curation.curate.apply(selIds, { mark: "keeper" }, true); closeSheet(); },
    reject: () => { curation.curate.apply(selIds, { mark: "reject" }, true); closeSheet(); },
  } : null;

  const armSelect = (mid) => {
    // U5c: already selecting, with a tile ticked -- the second long-press selects the range
    if (selectMode && anchor.current && selectRange(mid)) {
      if (navigator.vibrate) { try { navigator.vibrate([8, 40, 8]); } catch { /* unsupported/blocked */ } }
      return;
    }
    setSelectMode(true);
    setSelected((old) => { const s = new Set(old); s.add(mid); return s; });
    anchor.current = { mid, at: placeOf(mid) };
    if (navigator.vibrate) { try { navigator.vibrate(12); } catch { /* unsupported/blocked */ } }
  };
  // #35 (owner: "That was NOT the design"): a plain tap opens the LIGHTBOX, matching
  // Moonglade Mobile.dc.html:988-990's own tap(i) -> Lightbox Mobile. Details stays one
  // tap away via the lightbox's "Details ›" pill (openDetailsFromLightbox). The
  // earlier tap->Details wiring was drift, not design.
  const tapView = (mid) => (onOpenLightbox || onOpenDetails)(mid);

  return (
    <div className="glm-tab glm-tab-gallery" ref={rootRef}>
      <PullToRefresh onRefresh={onPullRefresh} enabled={!similar && !selectMode && !!onPullRefresh}>
      <div className="glm-bar">
        <div className="glm-search">
          <span className="glm-search-icon" onClick={() => submitQuery()} title="Search"><Icon name="search" /></span>
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

      <div className={"glm-bar2" + (continuous ? " cont" : "")}>
        {MEDIA_PILLS.map(([v, label]) => (
          <button key={label} type="button" className={"glm-metal" + (media === v ? " on" : "")}
            onClick={() => applyAdvanced({ media: v })}>
            {label}
          </button>
        ))}
        {selectMode ? (
          /* U5: the same select bar; in Continuous it also offers "All loaded (L)" and travels as one group
             (display: contents in Pages, as shipped). Actions waits while a range's ids are being read. */
          <div className={"glm-bar2-end" + (continuous ? " cont" : "")}>
            <button type="button" className="glm-metal" onClick={clearSelection}>Clear</button>
            <span className="glm-selcount"><b>{selected.size}</b> selected</span>
            {continuous ? (
              <button type="button" className="glm-allloaded" onClick={selectAllLoaded}>{allLoadedLabel(items.length)}</button>
            ) : null}
            {selected.size > 0 && (
              <button type="button" className="glm-metal glm-pill-accent" disabled={resolving > 0} onClick={() => openSheet("actions")}>
                Actions
              </button>
            )}
          </div>
        ) : (
          /* U2: in Continuous the count, the layout keys and Sort travel as one group, the keys drawn as
             the page draws them there (▦ ▭, no words), and the group drops under the media pills when a
             narrow phone has no room for all of it on one line -- the row never scrolls sideways. In
             Pages the wrapper is display: contents and the row is exactly as shipped. */
          <div className={"glm-bar2-end" + (continuous ? " cont" : "")}>
            {/* Q3: the page's own ▦ Grid | ▭ Feed seg control. Saved per device. U1: a long-press on
                either key opens the Layout + Paging sheet; the dot under them shows until the first. */}
            {/* U2: "N of M" in mono before the layout keys, Continuous only. */}
            {count ? <span className="glm-pgcount">{count}</span> : null}
            <div className="glm-layout" role="group" aria-label="Layout" style={continuous ? undefined : { marginLeft: "auto" }}>
              <button type="button" className={layout === "grid" ? "on" : ""} aria-pressed={layout === "grid"}
                aria-label="Grid" {...keyPress} onClick={() => tapKey("grid")}>{"▦"}<span className="lbl"> Grid</span></button>
              <button type="button" className={layout === "feed" ? "on" : ""} aria-pressed={layout === "feed"}
                aria-label="Feed" {...keyPress} onClick={() => tapKey("feed")}>{"▭"}<span className="lbl"> Feed</span></button>
              {!hintSeen ? <span className="glm-layout-dot" aria-hidden="true" /> : null}
            </div>
            <button type="button" className="glm-metal" onClick={() => openSheet("sort")}>
              Sort ▾
            </button>
          </div>
        )}
      </div>

      {!similar && curation && curation.strip ? curation.strip : null}

      {nudge ? <NudgeStrip show={nudge.show} onOpen={nudge.open} onDismiss={nudge.dismiss} /> : null}

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
      ) : continuous ? (
        <ContinuousGridMobile
          items={items} loading={loading && !moreBusy} selectMode={selectMode} selected={selected}
          toggleSelected={tapToggle} onArmSelect={armSelect} onTapView={tapView}
          layout={layout} saver={saver} newCount={ns.count} newLabel={ruleText} cols={cols} reveal={reveal}
        />
      ) : (
        <GalleryGridMobile
          items={items} loading={loading} selectMode={selectMode} selected={selected}
          toggleSelected={tapToggle} onArmSelect={armSelect} onTapView={tapView}
          layout={layout} saver={saver} newCount={ns.count} newLabel={ruleText} cols={cols}
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

      {/* U2: Continuous's quiet footer, in the pager's place. */}
      {continuous && !similar ? (
        <div className="glm-cfoot" role="status" aria-live="polite">
          {foot === "loading" ? (
            <div className="glm-cfoot-line"><i className="glm-cfoot-spin" aria-hidden="true" /><span className="glm-cfoot-dim">loading…</span></div>
          ) : foot === "failed" ? (
            <button type="button" className="glm-cfoot-retry" onClick={() => onLoadMore && onLoadMore()}>
              Couldn't load more. Retry
            </button>
          ) : foot === "end" && items.length ? (
            <div className="glm-cfoot-line"><span className="glm-cfoot-dim">{endLabel(total)}</span></div>
          ) : null}
        </div>
      ) : null}

      {/* Q5: the jump rides the scroller once you are a screen down. It sits in a zero-height sticky
          wrapper so it floats over the list, above the tab bar, without a fixed layer of its own. */}
      {/* U5c: the range card, for 4 s, where the jump sits (and in its place while it is up). */}
      {card ? (
        <div className="glm-newest-wrap glm-rangecard-wrap">
          <div className="glm-rangecard" role="status">{card}</div>
        </div>
      ) : jump && !similar ? (
        <div className="glm-newest-wrap">
          <button type="button" className="glm-newest" onClick={toNewest}>{newestLabel(ns.count)}</button>
        </div>
      ) : null}
      </PullToRefresh>

      <MobileSheet open={sheet === "search"} closing={closing} onClose={closeSheet} title="ADVANCED SEARCH">
        <div className="glm-legend">
          <div className="glm-legend-cap">these already work — nothing tells you so</div>
          <div className="glm-legend-line"><code>night*</code> wildcard · <code>model:tsubaki</code> by model</div>
          <div className="glm-legend-line"><code>2038314167804392533</code> a task or media id</div>
          <div className="glm-legend-line"><code>keeper</code> · <code>-reject</code> your mark · <code>tag:pose-study</code> your tag · <code>★4+</code></div>
          <div className="glm-legend-line"><code>ar:tall</code> · <code>ar:3:2</code> shape · <code>type:loom</code> image, video or loom</div>
        </div>
        <div className="glm-field2">
          <label className="glm-field">
            <span>Collection</span>
            <select value={draft.shelf} onChange={(e) => setDraft((d) => ({ ...d, shelf: e.target.value }))}>
              <option value="">Any collection</option>
              {(collections || []).map((c) => <option key={c} value={c}>{c}</option>)}
              {/* Session N1: saved searches, marked with the refresh mark */}
              {((curation && curation.smart) || []).map((c) => <option key={"s:" + c.name} value={c.name}>{"\u27f3 " + c.name}</option>)}
            </select>
          </label>
          <label className="glm-field">
            <span>Sort</span>
            <select value={draft.sort} onChange={(e) => setDraft((d) => ({ ...d, sort: e.target.value }))}>
              {sortOpts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
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
          {/* Session N7: the shape, as chips, after Min rating. One tap picks it, the same tap
              lets it go; a ratio or a bound typed in the search field shows as "Custom". */}
          <div className="glm-field glm-field-wide">
            <span>Aspect</span>
            <div className="mgcm-aspect" role="group" aria-label="Aspect">
              {ASPECT_CHOICES.map((c) => (
                <button key={c.value} type="button" title={c.hint}
                  className={"mgcm-chip" + (draft.aspect === c.value ? " on" : "")} aria-pressed={draft.aspect === c.value}
                  onClick={() => setDraft((d) => ({ ...d, aspect: d.aspect === c.value ? "" : c.value }))}>{c.label}</button>
              ))}
              {draft.aspect && !ASPECT_CHOICES.some((c) => c.value === draft.aspect) && parseAspect(draft.aspect).ok ? (
                <button type="button" className="mgcm-chip on" aria-pressed="true"
                  onClick={() => setDraft((d) => ({ ...d, aspect: "" }))}>{"ar:" + draft.aspect}</button>
              ) : null}
            </div>
          </div>
          <label className="glm-field">
            <span>Per page</span>
            <select value={draft.perPage}
              onChange={(e) => setDraft((d) => ({ ...d, perPage: Number(e.target.value) }))}>
              {PER_PAGE_OPTS.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
        </div>
        <datalist id="glm-models">{(boot.models || []).map((m) => <option key={m} value={m} />)}</datalist>
        {arErr ? <div className="mgcm-arerr" role="alert">{arErr}</div> : null}
        {curation ? (
          <button type="button" className="mgcm-savesmart" disabled={!canSaveThis} onClick={saveSmartFromSheet}
            title={canSaveThis ? "Save this search as a live collection: it stores the search, never a list of pictures" : "Type a search or set a filter first"}>
            Save as smart collection {"\u27f3"}
          </button>
        ) : null}
        <div className="glm-sheet-actions">
          <button type="button" className="glm-metal glm-widebtn" onClick={clearDraft}>Clear</button>
          <button type="button" className="glm-primary" onClick={applyDraft}>Apply</button>
        </div>
      </MobileSheet>

      <LayoutPagingSheet open={sheet === "paging"} closing={closing} onClose={closeSheet}
        layout={layout} setLayout={setLayout} paging={paging} setPaging={setPaging} />

      <MobileSheet open={sheet === "sort"} closing={closing} onClose={closeSheet} title="SORT">
        <div className="glm-sheet-list">
          {sortOpts.map(([v, label]) => (
            <button key={v} type="button" className={"glm-metal glm-sheetopt" + (adv.sort === v ? " on" : "")}
              onClick={() => { applyAdvanced({ sort: v }); closeSheet(); }}>
              {label}
            </button>
          ))}
          {/* Session P (P6): while a hand-picked collection shows in its manual order, the way
              to change that order -- the Collections screen's order view. */}
          {handShelf && adv.sort === "manual" && curation && curation.onEditOrder ? (
            <button type="button" className="glm-metal glm-sheetopt"
              onClick={() => { closeSheet(); curation.onEditOrder(shelf); }}>{"⇅ Edit the order…"}</button>
          ) : null}
        </div>
      </MobileSheet>

      <MobileSheet open={sheet === "actions"} closing={closing} onClose={closeSheet}
        title={selected.size + " SELECTED"}>
        {bulk ? (
          <CurationSheetMobile count={selected.size} onStar={bulk.star} onTag={bulk.tag}
            onKeeper={bulk.keeper} onReject={bulk.reject} />
        ) : null}
        <div ref={actionsHostRef} className="glm-actions-host">
          <ActionsMenu
            ids={selIds}
            shelf={shelf}
            collection={shelf}
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
