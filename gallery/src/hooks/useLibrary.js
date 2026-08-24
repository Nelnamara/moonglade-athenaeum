import { useCallback, useEffect, useRef, useState } from "react";
import { fetchLibrary } from "../api.js";

/* All of App.jsx's library browse/search/filter/sort/pagination state and logic,
   mechanically lifted out (2026-08-02) into its own hook -- media/shelf/perPage/
   query/applied/adv/flyOpen, items/total/page/pages/loading, load()/applyAdvanced/
   advCount/submitQuery/resetAll, and the selected Set + toggleSelected/selectMode.
   A byte-for-byte copy of that same logic, not a rewrite of it.

   UNLIKE useLogin.js/useSetupWizard.js -- which deliberately left their desktop
   originals (LoginPage.jsx/SetupWizard.jsx) as untouched standalone copies, because
   a sibling MOBILE surface needed the same logic without a second, drifting copy --
   App.jsx is different: this is the ONE place this state has ever lived, there is no
   sibling desktop-only copy to preserve. So App.jsx itself was refactored to CONSUME
   this hook rather than left holding its own second copy of the same state. */

export const ADV_DEFAULTS = {
  sort: "newest", ratingMin: 0, model: "", lora: "",
  dateFrom: "", dateTo: "", source: "", tag: "", publishedOnly: false,
  // Not a flyout field -- set only via the Details view's "View batch" link.
  batch: "",
  // #34 direction B: the "open a stack" drill-down. Not a flyout field either --
  // set only when a SERIES stack is opened (filterBySeries), the mirror of batch.
  // Resolves server-side to the series' member task_ids (?series=<sid>).
  series: "",
};

/* Serialize the CURRENT applied view (q + media + shelf + adv) into a query string.
   Two callers need it, and they disagree on ONE thing -- the date format:

   - dateStyle "library" (default): `from`/`to` as "YYYY-MM". This is what
     /api/next/library reads AND what Flyout's parsePresetQuery() reads back, so a
     saved-view preset round-trips through it losslessly.
   - dateStyle "export": `from_year`/`from_month` (+ `to_*`). The CSV route parses its
     filters through _filters_from_args(), whose date helper keys off `<prefix>_year`/
     `<prefix>_month` -- NOT `from`/`to`. Appending a library-format string to /export-csv
     would silently DROP the date filter. This split is the whole reason this is a shared
     helper and not an inline join. */
export function filterQueryString({ applied, media, shelf, adv, perPage }, dateStyle = "library") {
  const a = adv || {};
  const p = new URLSearchParams();
  const add = (k, v) => { if (v) p.set(k, String(v)); };
  add("q", (applied || "").trim());
  add("media", media);
  add("collection", shelf);
  if (a.sort && a.sort !== "newest") add("sort", a.sort);
  if (a.ratingMin) add("rating_min", a.ratingMin);
  add("model", a.model);
  add("lora", a.lora);
  add("source", a.source);
  add("tag", a.tag);
  if (a.publishedOnly) add("published", "1");
  // batch rides the EXPORT only, never a saved view: it's a transient Details "View batch"
  // drill-down, and parsePresetQuery neither restores nor clears it -- a saved view pinned
  // to a stale batch id would load the wrong/empty set, or leave a stale batch active. It
  // IS a real current filter worth exporting, though. (Found by the 2026-08-07 port review.)
  if (a.batch && dateStyle === "export") add("batch", a.batch);
  // series mirrors batch: a transient "open a stack" drill-down, worth exporting
  // (the CSV should match what the grid shows) but never persisted to a saved view.
  if (a.series && dateStyle === "export") add("series", a.series);
  // per_page is a VIEW setting, not a filter: parsePresetQuery restores it, but the CSV
  // export ignores it (it dumps every matching row), so it only rides the library style.
  if (perPage && dateStyle !== "export") add("per_page", perPage);
  const ym = (val, prefix) => {
    if (!val) return;
    if (dateStyle === "export") {
      const [y, m] = String(val).split("-");
      if (y) { p.set(prefix + "_year", y); if (m) p.set(prefix + "_month", m); }
    } else {
      p.set(prefix, val);   // "YYYY-MM", read verbatim by parsePresetQuery / next_library
    }
  };
  ym(a.dateFrom, "from");
  ym(a.dateTo, "to");
  return p.toString();
}

/* initialPage: the page the FIRST load lands on (App reads it from ?page=, via
   gen/urlState.js -- #31 "Where the Refit Broke" #7). Every later filter change
   still restarts from page 1, exactly as before. */
export default function useLibrary({ initialPage = 1, group = "" } = {}) {
  // filters
  const [media, setMedia] = useState("");
  const [shelf, setShelf] = useState("");
  const [perPage, setPerPage] = useState(100);
  const [query, setQuery] = useState("");
  const [applied, setApplied] = useState("");
  const [adv, setAdv] = useState(ADV_DEFAULTS);
  const [flyOpen, setFlyOpen] = useState(false);
  // data
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(null);
  const [page, setPage] = useState(1);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(false);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState(() => new Set());
  const reqSeq = useRef(0);

  const load = useCallback(
    async (p, replace) => {
      const seq = ++reqSeq.current;
      setLoading(true);
      try {
        const data = await fetchLibrary({
          q: applied, media, collection: shelf,
          page: p, page_size: perPage,
          sort: adv.sort !== "newest" ? adv.sort : "",
          rating_min: adv.ratingMin || "",
          model: adv.model, lora: adv.lora,
          from: adv.dateFrom, to: adv.dateTo,
          source: adv.source, tag: adv.tag,
          published: adv.publishedOnly ? "1" : "",
          batch: adv.batch,
          // #34 direction B: the series drill-down (?series=<sid>) always rides;
          // grouping (?group=series) rides ONLY when the toggle is on AND no
          // drill-down is active -- opening a stack (series OR batch) is exactly
          // the ungrouped members view, so a live drill-down suppresses the fold
          // (the backend ignores ?series while grouping anyway) and the "Stack
          // sessions" toggle can stay lit, ready to snap back when the filter clears.
          series: adv.series,
          group: (group === "series" && !adv.series && !adv.batch) ? "series" : "",
        });
        if (seq !== reqSeq.current) return; // a newer request superseded this one
        setItems((old) => (replace ? data.items : old.concat(data.items)));
        setTotal(data.total);
        setPage(data.page);
        setPages(data.pages);
        return data; // the lightbox's page-boundary step needs the fresh page synchronously
      } finally {
        if (seq === reqSeq.current) setLoading(false);
      }
    },
    // group joins the filter deps: flipping "Stack sessions" changes load's
    // identity, and the mount effect below re-fires on that -> a page-1 refetch,
    // exactly like changing media/sort/rating (the toggle re-groups from the top).
    [applied, media, shelf, perPage, adv, group]
  );

  // The flyout commits a patch: advanced fields always; q/media/shelf/perPage
  // only when a saved view carries them.
  const applyAdvanced = (patch) => {
    const next = {};
    for (const k of Object.keys(ADV_DEFAULTS)) if (k in patch) next[k] = patch[k];
    setAdv((old) => ({ ...old, ...next }));
    if ("q" in patch) { setQuery(patch.q); setApplied(patch.q); }
    if ("media" in patch) setMedia(patch.media);
    if ("shelf" in patch) setShelf(patch.shelf);
    if (patch.perPage) setPerPage(patch.perPage);
    setFlyOpen(false);
  };
  const advCount = Object.keys(ADV_DEFAULTS).filter(
    (k) => JSON.stringify(adv[k]) !== JSON.stringify(ADV_DEFAULTS[k])
  ).length;

  // any filter change restarts from page 1 -- except the mount's own load, which
  // honors the page the URL asked for. "Mount" is judged by load's identity, not a
  // consumed flag: StrictMode's dev double-invoke re-runs this effect with the SAME
  // load, and a flag would have sent the second run to page 1.
  const mountLoad = useRef(null);
  useEffect(() => {
    const first = mountLoad.current === null || mountLoad.current === load;
    mountLoad.current = load;
    load(first ? Math.max(1, initialPage | 0) : 1, true);
  }, [load]); // eslint-disable-line react-hooks/exhaustive-deps

  const submitQuery = (forced) => {
    setApplied(forced !== undefined ? forced : query);
  };

  // Reset must clear the ADVANCED filters too, or a min-rating/sort/date range
  // set from the flyout silently survives a Reset click (owner QA 2026-07-30).
  const resetAll = () => {
    setQuery(""); setMedia(""); setShelf(""); setAdv(ADV_DEFAULTS);
    setApplied("");
  };

  const toggleSelected = (mid) =>
    setSelected((old) => {
      const s = new Set(old);
      s.has(mid) ? s.delete(mid) : s.add(mid);
      return s;
    });

  return {
    media, setMedia, shelf, setShelf, perPage, setPerPage,
    query, setQuery, applied, setApplied, adv, setAdv, flyOpen, setFlyOpen,
    items, setItems, total, page, pages, loading,
    load, applyAdvanced, advCount, submitQuery, resetAll,
    selectMode, setSelectMode, selected, setSelected, toggleSelected,
  };
}
