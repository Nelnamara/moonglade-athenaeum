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
};

export default function useLibrary() {
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
    [applied, media, shelf, perPage, adv]
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

  // any filter change restarts from page 1
  useEffect(() => { load(1, true); }, [load]);

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
