import React, { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Icon from "../icons/Icons.jsx";
import { apiGet } from "../api.js";
import useAccountPrefs from "../hooks/useAccountPrefs.js";
import { uniqueRows, appendRows, scrollParentOf, rowKey } from "../picker/mergeRows.js";
import {
  SavedRail, SavedChooser, SavedSetsSheet, SavedHead, SavedChips, GoneList, OldToggle,
} from "../picker/SavedTab.jsx";
import { KeepRow, KeepMenu, GoneMenu, SaveSplit, keepRect } from "../picker/KeepControls.jsx";
import { savedApi, savedStore, useSavedVersion } from "../picker/savedApi.js";
import {
  NARROW_PX, OLD_PREF, READ_ONLY_LINE, SAVED_BASES, SAVED_END_LINE, SAVED_NOTE, afterWrite, currentSet,
  isTransportError, mergeOld, savedEmptyLine, savedErrorLine, savedTabLabel,
} from "../picker/savedCore.js";
import "../styles/model-picker.css";
import "../styles/saved-tab.css";

/* Faithful React port of static/mg-model-picker.js (2026-08-08, the vanilla static/ -> React
   campaign): the model/LoRA picker (search + cover cards + hover preview), with the opt-in
   `multi` (LoRA multi-select), `market` (browse chrome), and `baseType` (LoRA compat) modes.
   Behaviour is 1:1 with the element -- a port, not a redesign.

   Selection is CONTROLLED by the host (the one deliberate React-idiom change): `value` (single)
   / `selected` (multi array) come down as props, so there is no internal selection state, no
   `deselect()` imperative method, and the old "un-picking a LoRA mid-resolve resurrects it" bug
   can't happen -- the resolve just checks the live `selected` before re-dispatching.
     single mode: onPick(row)
     multi mode:  onToggle(model, selected) -- fired on add (a pending entry, then again with
                  version_id/lora_base_type/trigger_words/versions resolved via /api/model-version)
                  and on remove (selected:false). Host upserts/removes by model_id.
   `visible` replaces the element's display:none + ensureSearched() dance: the search fires on
   first reveal and whenever the filters/query/baseType change while visible, but NOT on a plain
   re-reveal (each instance keeps its own last search), matching the element's contract.

   SAVED (Session S, Saved Tab Handoff; drift 134-139) replaced the frozen Bookmarked tab: PixAI's
   model collections, read live -- Saved (the reserved default) unless the rail or the "Saved ▾"
   chooser picked a named set -- paged through the same search route (src=saved), with the LoRA
   base chips and the search box as its filters. Nothing writes when it opens. `phone` says the
   host is the phone's Model/LoRA sheet (ModelFlyout passes it).

   KEEPING (S3b + S4c). Every card in the dock and on the phone sheet (the `market` mounts)
   carries [⊕ Save | ▾] (picker/KeepControls.jsx). The body is ONE write -- saveModel, below --
   whose answer is the server's read-back; ▾ (and ✓ Saved) opens "Keep this model". Session M's
   ☆ on the card is retired (drift 136): ★ Quick-pick is the menu's first row, and the card's
   small ★ only shows it. `favs` / `onFav` are that quick-pick list and its toggle, as before. */

// ---- formatters, verbatim from mg-model-picker.js ----
function fmt(n) { return (Number(n) || 0).toLocaleString(); }
function fmtCompact(n) {
  n = Number(n) || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, "") + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "K";
  return String(n);
}
function tyShort(t) {
  t = (t || "").toUpperCase();
  if (t.indexOf("LORA") >= 0) return "LoRA";
  if (t.indexOf("MMDIT") >= 0) return "MMDiT";
  if (t.indexOf("DIT") >= 0) return "DiT";
  if (t.indexOf("SDXL") >= 0) return "SDXL";
  if (t.indexOf("SD_V1") >= 0) return "SD1.5";
  if (t.indexOf("SD3") >= 0) return "SD3";
  if (t.indexOf("Z_IMAGE") >= 0) return "Z-Image";
  if (t.indexOf("CHAT") >= 0) return "Chat";
  return (t.split("_")[0] || "model").toLowerCase();
}
function baseLabel(cat) {
  cat = (cat || "").replace(/^uploaded-/, "").replace(/[-_]+/g, " ").trim();
  if (!cat) return "";
  if (/sdxl/i.test(cat)) return "SDXL";
  if (/sd3/i.test(cat)) return "SD3";
  if (/^sd ?v?1/i.test(cat)) return "SD1.5";
  if (/flux/i.test(cat)) return "Flux";
  if (/pony/i.test(cat)) return "Pony";
  if (/illustrious/i.test(cat)) return "Illustrious";
  return cat.replace(/\b\w/g, (c) => c.toUpperCase());
}
function archLabel(m, kind) {
  const b = baseLabel(m.base_model);
  if (b) return b;
  const t = m.lora_base_model_type || m.model_type || "";
  if (t) return tyShort(t);
  if (kind === "base" && m.type) return tyShort(m.type);
  return "";
}

const LORA_CATS = [
  ["", "All"], ["character", "Character"], ["animal", "Animal"], ["style", "Style"],
  ["realistic", "Realistic"], ["pose", "Pose"], ["clothing", "Clothing"],
  ["background", "Background"], ["detail", "Detail"], ["other", "Other"],
];
/* [chip key, label, tokens sent]. The key is the chip's own identity (and what the multi-select
   stores); the third column, when present, is the set of model_type tokens that chip SENDS.
   "Community DiT" sends a PAIR since 2026-09-26 (SCOPE_2026-09-26 G8): USER_DIT26A_MODEL is the
   2026-07-26 live measurement, USER_DIT26B_MODEL (a user-trained DiT.3) was read from PixAI's
   BUNDLE -- ModelFilter.helper groups them as `userdit26` and its one Community DiT option sends
   both. No new chip, no new label. Mirrors moonglade_backup.MODEL_TYPE_FILTERS. */
const BASE_TYPES = [
  ["", "All"], ["MMDIT26B_MODEL", "DiT.3"], ["MMDIT26A_MODEL", "DiT.2"], ["DIT7_MODEL", "DiT.1"],
  ["USER_DIT26A_MODEL", "Community DiT", ["USER_DIT26A_MODEL", "USER_DIT26B_MODEL"]],
  ["SDXL_MODEL", "SDXL"], ["SD_V1_MODEL", "SD 1.5"],
];
const typeTokens = (key) => {
  const row = BASE_TYPES.find((r) => r[0] === key);
  return (row && row[2]) || [key];
};
const SORTS = [["trending", "Trending"], ["liked", "Most Liked"], ["used", "Most Used"], ["newest", "Latest"]];

export default function ModelPicker({
  kind = "base", multi = false, market = false, baseType = "",
  value = null, selected = [], onPick, onToggle, visible = true, style,
  favs = null, onFav = null, phone = false,
}) {
  const [q, setQ] = useState("");
  const [qDebounced, setQDebounced] = useState("");
  const [rows, setRows] = useState([]);
  const [err, setErr] = useState("");
  const [loadingMore, setLoadingMore] = useState(false);
  const [dim, setDim] = useState(false);      // grid opacity .45 during a fresh search
  // market filters
  const [src, setSrc] = useState("market");
  const [sort, setSort] = useState("trending");
  const [category, setCategory] = useState("");
  const [modelTypes, setModelTypes] = useState([]);
  const [source, setSource] = useState("");
  const [posted, setPosted] = useState("");
  const [license, setLicense] = useState("");
  const [preview, setPreview] = useState(null);   // {m, x, y}
  // Session S: the Saved tab
  const [setId, setSetId] = useState("");           // "" = Saved, the reserved default
  const [savedBase, setSavedBase] = useState("");   // the LoRA base chip ("" = All)
  const [savedSets, setSavedSets] = useState(null); // {sets, default_id, unavailable, read_only}
  const [setsErr, setSetsErr] = useState("");
  const [wide, setWide] = useState(false);          // picker >= NARROW_PX: the rail, not the chooser
  const [chooser, setChooser] = useState(false);
  const [gone, setGone] = useState(null);           // "K not available ▸": null = closed
  const [atEnd, setAtEnd] = useState(false);
  const [settled, setSettled] = useState(false);    // the latest fresh search has answered
  const [oldRows, setOldRows] = useState(null);     // S2c: old bookmarks Saved does not hold
  const [oldErr, setOldErr] = useState("");
  const prefs = useAccountPrefs();
  const showOld = prefs.get(OLD_PREF, true) !== false;
  // S3b + S4c: keeping a model
  const [readOnly, setReadOnly] = useState(false);  // READ_ONLY, as every search answers it
  const [keep, setKeep] = useState(null);           // the open menu: {m, rect} or {gone, rect}
  const [busyIds, setBusyIds] = useState([]);       // cards with a save in flight
  const [notes, setNotes] = useState({});           // model id -> {kind: ok|err, text}
  useSavedVersion();                                // re-render when any card's saved state moves

  const seqRef = useRef(0);
  const cursorRef = useRef("");
  const hasMoreRef = useRef(false);
  const loadingMoreRef = useRef(false);
  const gridRef = useRef(null);
  const sentinelRef = useRef(null);   // the end-of-list marker the IntersectionObserver watches
  const lastKeyRef = useRef(null);
  const previewTimerRef = useRef(null);
  const scrollRafRef = useRef(null);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const rootRef = useRef(null);
  const setsAskedRef = useRef(false);
  const oldAskedRef = useRef(false);
  const savedOn = market && src === "saved";
  const busyRef = useRef(new Set());
  const noteTimers = useRef({});
  const rowsRef = useRef([]);       // the rows as the last applySets left them (see there)
  const longRef = useRef({ t: 0, fired: false });   // the phone's long-press (S6a, Session K)
  const oldAsideRef = useRef(new Map());            // old bookmarks saved here, until unsaved again

  useEffect(() => {
    const t = setTimeout(() => setQDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  // Shared by the fresh search and the load-more continuation so the two can never drift.
  const searchUrl = useCallback((cursor) => {
    let u = "/api/model-search?kind=" + encodeURIComponent(kind) + "&size=24&q=" + encodeURIComponent(qDebounced || "");
    if (market) {
      u += "&src=" + encodeURIComponent(src);
      if (src === "saved") {
        if (setId) u += "&set=" + encodeURIComponent(setId);
        if (kind === "lora" && savedBase) u += "&base=" + encodeURIComponent(savedBase);
      } else {
        u += "&sort=" + encodeURIComponent(sort) + "&category=" + encodeURIComponent(category) +
             "&posted=" + encodeURIComponent(posted) + "&source=" + encodeURIComponent(source) +
             "&license=" + encodeURIComponent(license);
        // A chip may stand for more than one token (Community DiT -> both user-DiT enums).
        modelTypes.forEach((t) => typeTokens(t).forEach((tok) => {
          u += "&model_type=" + encodeURIComponent(tok);
        }));
      }
    }
    if (kind === "lora" && baseType) u += "&base_type=" + encodeURIComponent(baseType);
    if (cursor) u += "&cursor=" + encodeURIComponent(cursor);
    return u;
  }, [kind, qDebounced, market, src, sort, category, posted, source, license, modelTypes, baseType, setId, savedBase]);

  const doSearch = useCallback(() => {
    const mine = ++seqRef.current;
    cursorRef.current = ""; hasMoreRef.current = false;
    setDim(true); setSettled(false);
    apiGet(searchUrl()).then((d) => {
      if (mine !== seqRef.current) return;
      hasMoreRef.current = !!(d && d.has_more);
      cursorRef.current = (d && d.next_cursor) || "";
      setErr(d && d.error ? d.error : "");
      setRows(uniqueRows((d && d.results) || []));
      if (d && typeof d.read_only === "boolean") setReadOnly(d.read_only);
      setDim(false); setSettled(true); setAtEnd(!hasMoreRef.current);
    }).catch(() => {
      if (mine !== seqRef.current) return;
      setErr("network error"); setRows([]); setDim(false); setSettled(true);
    });
  }, [searchUrl]);

  const loadMore = useCallback(() => {
    if (!hasMoreRef.current || loadingMoreRef.current) return;
    const mine = seqRef.current;
    loadingMoreRef.current = true; setLoadingMore(true);
    apiGet(searchUrl(cursorRef.current)).then((d) => {
      loadingMoreRef.current = false; setLoadingMore(false);
      if (mine !== seqRef.current) return;   // a fresh search superseded this continuation
      if (d && d.error) return;              // transient: leave hasMore/cursor, next scroll retries
      hasMoreRef.current = !!(d && d.has_more);
      cursorRef.current = (d && d.next_cursor) || "";
      setAtEnd(!hasMoreRef.current);
      // One row per model (picker/mergeRows.js): the feeds repeat a model across pages, and a
      // repeated key leaves React a card it can never remove again -- the "always the SAME
      // LoRA" pile at the top of every later list (owner, 2026-09-07).
      setRows((old) => appendRows(old, (d && d.results) || []));
    }).catch(() => { loadingMoreRef.current = false; setLoadingMore(false); });
  }, [searchUrl]);

  // LOAD MORE, the way that survives the layout. The grid's own onScroll below only fires when
  // .mg-grid itself is the scroller -- and on the phone sheet and the desktop dock palette it is
  // NOT: the ancestor `.mfly > div:not(.mfly-head)` scrolls (styles.css / create-mobile.css /
  // dock.css all give it overflow-y:auto and min-height:0), so the grid never scrolled, the
  // handler never ran, and every list stopped dead at its first page of 24 (owner, 2026-09-07,
  // desktop and phone, every tab and sort). An IntersectionObserver on a 1px sentinel after the
  // grid sees the sentinel come into view through ANY clipping ancestor, so it does not care
  // which element scrolls. The root is that scrolling ancestor when there is one (the viewport
  // otherwise), because only then does the margin mean "this far before the END OF THE LIST":
  // with root:null the margin widens the viewport, but the pane's clip is applied first, so the
  // sentinel only ever intersected once it was physically on screen and every page cost a full
  // server round trip (0.6-0.9 s, measured) spent looking at the bottom of the list ("it does but
  // its slow" -- owner, 2026-09-07). 720px is about one page of cards: the next page is on its way
  // while the current one is still being read, which is what the vanilla picker felt like.
  useEffect(() => {
    if (!visible || typeof IntersectionObserver === "undefined") return;
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) loadMore();
    }, { root: scrollParentOf(el), rootMargin: "720px 0px", threshold: 0 });
    io.observe(el);
    return () => io.disconnect();
  }, [visible, loadMore, rows.length]);

  // browse-on-open + re-search on any filter change, but NOT on a plain re-reveal (ensureSearched
  // + _stale semantics): the search key is the fresh-list url; unchanged key => skip.
  useEffect(() => {
    if (!visible) return;
    const key = searchUrl();
    if (key === lastKeyRef.current) return;
    lastKeyRef.current = key;
    doSearch();
  }, [visible, searchUrl, doSearch]);

  // Saved's rail: read once, the first time Saved shows in this picker (a read only -- nothing
  // writes on open). Retry clears the error and asks again.
  const readSets = useCallback(() => {
    setsAskedRef.current = true;
    setSetsErr("");
    apiGet("/api/model-saved/sets", { kind }).then((d) => {
      if (!d || d.error) { setSetsErr((d && d.error) || "PixAI didn't answer"); return; }
      setSavedSets(d);
      if (typeof d.read_only === "boolean") setReadOnly(d.read_only);
    });
  }, [kind]);
  useEffect(() => {
    if (!visible || !market || src !== "saved" || setsAskedRef.current) return;
    readSets();
  }, [visible, market, src, readSets]);

  // S2c: the old bookmarks Saved does not hold -- read once, on Saved itself, while "Show old
  // bookmarks" is on. They are drawn after the live list's end (oldShown, below).
  const readOld = useCallback(() => {
    oldAskedRef.current = true;
    setOldErr("");
    apiGet("/api/model-saved/old", { kind }).then((d) => {
      if (!d || d.error) { setOldErr((d && d.error) || "PixAI didn't answer"); return; }
      setOldRows(d.rows || []);
    });
  }, [kind]);
  useEffect(() => {
    if (!visible || !(savedOn && !setId && showOld) || oldAskedRef.current) return;
    readOld();
  }, [visible, savedOn, setId, showOld, readOld]);

  // The rail shows only where the picker is at least NARROW_PX wide (the desktop dock); a
  // narrower picker, and the phone's sheet, fold it into the "Saved ▾" chooser.
  useEffect(() => {
    const el = rootRef.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const measure = () => setWide(!phone && el.clientWidth >= NARROW_PX);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [phone]);

  // Saved's own rows are saved (in Saved itself, or in the set on screen): tell every card.
  useEffect(() => {
    if (!savedOn || setId) return;
    const live = rows.filter((r) => r.item_id && !r.old);
    if (live.length) savedStore.setMany(live.map((r) => [r.model_id, { saved: true, item_id: r.item_id }]));
  }, [savedOn, setId, rows]);

  const note = (id, n) => {
    clearTimeout(noteTimers.current[id]);
    setNotes((o) => ({ ...o, [id]: n }));
    if (n && n.kind === "ok") {
      noteTimers.current[id] = setTimeout(() => setNotes((o) => ({ ...o, [id]: null })), 3200);
    }
  };
  useEffect(() => () => Object.values(noteTimers.current).forEach(clearTimeout), []);

  // A model's place in PixAI's sets just changed (a save's read-back, or the menu): every card
  // learns it, and the list on screen follows -- a model taken out of the set on screen leaves
  // it, a model put into it (an old bookmark saved, say) joins it at the top, untagged.
  // Decided against rowsRef, not the render's `rows`: a menu's handler can be a render behind,
  // and two answers in one tick must not move the count twice.
  rowsRef.current = rows;
  const applySets = (m, sets) => {
    const id = String(m.model_id);
    const list = sets || [];
    const def = list.find((x) => x.reserved);
    if (def) savedStore.set(id, { saved: !!def.contains, item_id: def.contains ? def.item_id || "" : "" });
    if (!savedOn) return;
    const viewId = setId || (savedSets && savedSets.default_id) || (def && def.id) || "";
    const here = list.find((x) => x.id === viewId);
    if (!here) return;
    const inList = rowsRef.current.some((r) => String(r.model_id) === id);
    const bump = (n) => setSavedSets((ss) => ss && { ...ss, sets: ss.sets.map((x) => (x.id === viewId ? { ...x, count: Math.max(0, x.count + n) } : x)) });
    if (!here.contains && inList) {
      rowsRef.current = rowsRef.current.filter((r) => String(r.model_id) !== id);
      setRows((old) => old.filter((r) => String(r.model_id) !== id));
      bump(-1);
      // an old bookmark saved here and now taken back out of Saved is old again
      const back = !setId && oldAsideRef.current.get(id);
      if (back) {
        oldAsideRef.current.delete(id);
        setOldRows((o) => (o || []).concat(back));
      }
    } else if (here.contains && !inList) {
      const row = { ...m, old: false, item_id: here.item_id || "" };
      rowsRef.current = [row, ...rowsRef.current];
      setRows((old) => [row, ...old.filter((r) => String(r.model_id) !== id)]);
      if (m.old) {
        oldAsideRef.current.set(id, m);
        setOldRows((o) => (o || []).filter((r) => String(r.model_id) !== id));
      }
      bump(1);
    }
  };

  // ⊕ Save: THE save write. One per tap and one in flight per card; READ_ONLY never sends (the
  // body is dimmed and says why). The server sends it once and answers its read-back, which
  // decides the card. An answer that never reached the page is read back, never re-sent.
  const saveModel = async (m) => {
    const id = String(m.model_id);
    if (readOnly || busyRef.current.has(id)) return;
    busyRef.current.add(id);
    setBusyIds([...busyRef.current]);
    note(id, null);
    const d0 = await savedApi.save(id);
    let d = d0;
    if (isTransportError(d0)) {
      const st = await savedApi.state(id);
      d = st && !st.error
        ? { contains: !!st.saved, item_id: st.item_id || "", sets: st.sets,
            error: st.saved ? "" : "The answer was lost on the way and PixAI doesn't show it saved, so it isn't confirmed." }
        : { error: "The answer was lost on the way, and the check failed too. Look on PixAI before trying again." };
    }
    busyRef.current.delete(id);
    setBusyIds([...busyRef.current]);
    if (d && typeof d.read_only === "boolean") setReadOnly(d.read_only);
    const next = afterWrite(savedStore.get(id), d, true);
    savedStore.set(id, { saved: next.saved, item_id: next.item_id });
    if (d && d.sets) applySets(m, d.sets);
    note(id, next.ok ? { kind: "ok", text: SAVED_NOTE } : { kind: "err", text: next.error });
  };
  const openKeep = (m, el) => { hidePreview(); setKeep({ m, rect: keepRect(el) }); };
  // The phone: a long-press on a card opens the same keep sheet ▾ does; the tap that ends it
  // does not also pick the model (pick() checks `fired`).
  const longPress = (m) => (phone && market ? {
    onTouchStart: () => {
      longRef.current.fired = false;
      clearTimeout(longRef.current.t);
      longRef.current.t = setTimeout(() => {
        longRef.current.fired = true;
        setKeep({ m, rect: null });
      }, 500);
    },
    onTouchEnd: () => clearTimeout(longRef.current.t),
    onTouchMove: () => clearTimeout(longRef.current.t),
    onContextMenu: (e) => e.preventDefault(),
  } : null);
  useEffect(() => () => clearTimeout(longRef.current.t), []);

  const pickSrc = (v) => {
    // Saved ▾ tapped while Saved is already on: the chooser (where the rail is folded)
    if (v === "saved" && src === "saved" && !wide) { setChooser((o) => !o); return; }
    setChooser(false); setGone(null);
    setSrc(v);
  };
  const pickSet = (s) => {
    setChooser(false); setGone(null);
    setSetId(s.reserved ? "" : s.id);
  };
  const retrySaved = () => {
    if (setsErr) readSets();
    if (err) doSearch();
  };
  const toggleGone = () => {
    if (gone) { setGone(null); return; }
    setGone({ items: null });
    apiGet("/api/model-saved/unavailable", { expect: (savedSets && savedSets.unavailable) || 0 })
      .then((d) => setGone((g) => (!g ? g : (!d || d.error)
        ? { error: (d && d.error) || "PixAI didn't answer" } : { items: d.items || [] })));
  };

  const onScroll = () => {
    if (scrollRafRef.current) return;
    scrollRafRef.current = requestAnimationFrame(() => {
      scrollRafRef.current = null;
      const g = gridRef.current;
      if (g && g.scrollHeight - g.scrollTop - g.clientHeight < 150) loadMore();
    });
  };

  const isSelected = useCallback((m) => (multi
    ? selected.some((e) => e.model_id === m.model_id)
    : !!(value && value.model_id === m.model_id)), [multi, selected, value]);

  const toggleMulti = (m) => {
    const cur = selectedRef.current;
    const at = cur.findIndex((e) => e.model_id === m.model_id);
    if (at >= 0) { onToggle && onToggle(cur[at], false); return; }
    // Push an incomplete entry immediately (host can render a pending chip), resolve in the
    // background, then dispatch again filled in. Never silently dropped (fail-open).
    const entry = {
      model_id: m.model_id, title: m.title, preview_url: m.preview_url,
      version_id: "", weight: 0.7, lora_base_type: "", trigger_words: "", failed: false,
    };
    onToggle && onToggle(entry, true);
    apiGet("/api/model-version?model_id=" + encodeURIComponent(m.model_id) + "&all=1")
      .then((d) => {
        // superseded-response guard: the entry's own identity is the token -- if the host
        // removed it while the resolve was in flight, don't put it back.
        if (!selectedRef.current.some((e) => e.model_id === m.model_id)) return;
        const versions = (d && d.versions) || [], v = versions[0] || {};
        onToggle && onToggle({
          ...entry, version_id: v.version_id || "", lora_base_type: v.lora_base_model_type || "",
          trigger_words: v.trigger_words || "", versions, failed: !v.version_id,
        }, true);
      }).catch(() => {
        if (!selectedRef.current.some((e) => e.model_id === m.model_id)) return;
        onToggle && onToggle({ ...entry, failed: true }, true);
      });
  };

  const pick = (m) => {
    if (longRef.current.fired) { longRef.current.fired = false; return; }
    hidePreview();
    if (multi) { toggleMulti(m); return; }
    onPick && onPick(m);
  };

  // ---- hover preview (130ms debounce, placed toward whichever side has room) ----
  const showPreview = (m, anchorEl) => {
    const r = anchorEl.getBoundingClientRect(), w = 300, gap = 12;
    let x = r.right + gap;
    if (x + w > window.innerWidth - 8) x = Math.max(8, r.left - w - gap);
    const y = Math.max(8, Math.min(r.top - 10, window.innerHeight - 380));
    setPreview({ m, x, y });
  };
  const schedulePreview = (m, anchorEl) => {
    // A touch screen has no hover: a tap fires mouseenter, nothing ever fires mouseleave, and the
    // preview card would stand over the sheet for good (owner, phone, 2026-09-07).
    if (typeof window !== "undefined" && window.matchMedia && window.matchMedia("(hover: none)").matches) return;
    clearTimeout(previewTimerRef.current);
    previewTimerRef.current = setTimeout(() => showPreview(m, anchorEl), 130);
  };
  const hidePreview = () => { clearTimeout(previewTimerRef.current); setPreview(null); };

  useEffect(() => () => { clearTimeout(previewTimerRef.current); if (scrollRafRef.current) cancelAnimationFrame(scrollRafRef.current); }, []);

  const filtersHidden = market && src === "saved";
  const p = preview && preview.m;

  // A keyword search under a base filter has TWO ways to come back empty -- nothing is called
  // that, or nothing called that is built for this base -- and "No results — try another
  // search." answers only the first, so the second reads as the search being broken (owner walk,
  // 2026-09-07). When a base filter is on, say so and offer both ways out. The label is
  // archLabel's own, fed a row carrying just the base type, so the sentence names the base in
  // exactly the words the cards' ⚠ badge and their "needs <arch>" line already use.
  const baseFilterLabel = kind === "lora" && baseType
    ? archLabel({ lora_base_model_type: baseType }, kind) : "";
  // Since 2026-09-07 a NAME search is not filtered by the base at all -- a match the picked base
  // cannot run shows greyed with what it needs -- so an empty result means nothing matched the
  // words. Browsing without a search term is still base-filtered, and its empty line says so.
  const emptyLine = (kind === "lora" && qDebounced)
    ? "No LoRAs match “" + qDebounced + "” — try other words."
    : (baseFilterLabel && !qDebounced
        ? "No LoRAs for " + baseFilterLabel + " here — pick another base or search by name."
        : "No results — try another search.");

  // ---- Saved (Session S) ----
  const cur = savedOn ? currentSet(savedSets && savedSets.sets, setId) : null;
  const curTitle = cur ? cur.title : "Saved";
  const railShown = savedOn && wide && !!savedSets && savedSets.sets.length > 0;
  // S2c: after the live list's end, the old bookmarks it does not hold, tagged "old"
  const oldAll = savedOn && !setId && showOld ? mergeOld(rows, oldRows) : [];
  const oldShown = savedOn && !setId && showOld && atEnd && !err
    ? mergeOld(rows, oldRows, { q: qDebounced, base: kind === "lora" ? savedBase : "" }) : [];
  const listRows = oldShown.length ? rows.concat(oldShown) : rows;
  const savedLine = !savedOn ? null
    : (err || setsErr) ? (
      <div className="mg-saved-line mg-saved-err">
        {savedErrorLine(curTitle)}{" "}
        <button type="button" className="mg-saved-retry" onClick={retrySaved}>Retry</button>
      </div>)
    : (settled && !rows.length && !oldShown.length) ? (
      <div className="mg-saved-line">
        {savedEmptyLine(kind, qDebounced, kind === "lora" && savedBase ? (SAVED_BASES.find((b) => b[0] === savedBase) || [])[1] : "")}
      </div>)
    : null;

  return (
    <div className={"model-picker" + (phone ? " phone" : "")} style={style} ref={rootRef}>
      <input className="mg-q" type="text" placeholder={savedOn ? "Search saved…" : "Search"} aria-label="Search models"
        value={q} onChange={(e) => setQ(e.target.value)} />

      {market && (
        <>
          <div className="mg-srcwrap">
            <div className="mg-mktsrc">
              {[["market", "Market"], ["saved", savedTabLabel(wide)], ...(kind === "lora" ? [["mine", "Mine"]] : [])].map(([v, label]) => (
                <button type="button" key={v} className={src === v ? "on" : ""} data-src={v}
                  aria-haspopup={v === "saved" && !wide ? "menu" : undefined}
                  onClick={() => pickSrc(v)}>{label}</button>
              ))}
            </div>
            {savedOn && chooser && !wide && savedSets ? (phone ? (
              <SavedSetsSheet sets={savedSets.sets} current={cur} onPick={pickSet} onClose={() => setChooser(false)} />
            ) : (
              <SavedChooser sets={savedSets.sets} current={cur} onPick={pickSet} />
            )) : null}
          </div>
          <div className="mg-mktfilters" style={filtersHidden ? { display: "none" } : undefined}>
            <div className="mg-mktsort">
              {SORTS.map(([v, label]) => (
                <button type="button" key={v} className={sort === v ? "on" : ""} data-sort={v}
                  onClick={() => setSort(v)}>{label}</button>
              ))}
            </div>
            {kind === "lora" ? (
              <div className="mg-mktcats">
                {LORA_CATS.map(([v, label]) => (
                  <button type="button" key={v || "all"} className={category === v ? "on" : ""} data-cat={v}
                    onClick={() => setCategory(v)}>{label}</button>
                ))}
              </div>
            ) : (
              <div className="mg-mktcats mg-mkttypes">
                {BASE_TYPES.map(([v, label]) => {
                  const on = v ? modelTypes.includes(v) : !modelTypes.length;
                  return (
                    <button type="button" key={v || "all"} className={on ? "on" : ""} data-mt={v}
                      onClick={() => setModelTypes((old) => (!v ? [] : old.includes(v) ? old.filter((x) => x !== v) : old.concat(v)))}>{label}</button>
                  );
                })}
              </div>
            )}
            <div className="mg-mktsel">
              <select className={"mg-posted" + (posted ? " on" : "")} aria-label="Posted at"
                value={posted} onChange={(e) => setPosted(e.target.value)}>
                <option value="">Any time</option>
                <option value="yesterday">Yesterday</option>
                <option value="7d">Past 7 days</option>
                <option value="30d">Past 30 days</option>
              </select>
              {kind === "lora" && (
                <select className={"mg-source" + (source ? " on" : "")} aria-label="Source"
                  value={source} onChange={(e) => setSource(e.target.value)}>
                  <option value="">Any source</option>
                  <option value="pixai">PixAI-trained</option>
                  <option value="external">External</option>
                </select>
              )}
              <select className={"mg-license" + (license ? " on" : "")} aria-label="License"
                value={license} onChange={(e) => setLicense(e.target.value)}>
                <option value="">Any licence</option>
                <option value="COMMERCIAL">Commercial use OK</option>
              </select>
            </div>
          </div>
        </>
      )}

      <div className={"mg-body" + (railShown ? " has-rail" : "")}>
        {railShown ? <SavedRail sets={savedSets.sets} current={cur} onPick={pickSet} /> : null}
        <div className="mg-body-main">
          {savedOn ? (
            <>
              <SavedHead title={curTitle} count={cur ? cur.count : 0} old={oldAll.length}
                gone={!setId && savedSets ? savedSets.unavailable : 0}
                goneOpen={!!gone} onGone={toggleGone} />
              {!setId ? (
                <GoneList state={gone} renderKeep={(it) => (
                  <SaveSplit saved busy={false} readOnly={readOnly}
                    onMenu={(el) => setKeep({ gone: it, rect: keepRect(el) })} />
                )} />
              ) : null}
              {kind === "lora" ? <SavedChips value={savedBase} onPick={setSavedBase} /> : null}
              {savedLine}
            </>
          ) : err ? <div className="mg-empty" style={{ display: "block" }}>⚠ {err}</div>
            : !rows.length ? <div className="mg-empty" style={{ display: "block" }}>{emptyLine}</div>
            : <div className="mg-empty" />}

          <div className="mg-grid" role="listbox" ref={gridRef} onScroll={onScroll}
            style={{ opacity: dim ? 0.45 : 1 }}>
            {listRows.map((m, i) => {
              const incompat = m.compat === "no";
              const arch = archLabel(m, kind);
              const sel = isSelected(m);
              let tip = m.description || m.title || "";
              if (incompat && arch) tip += (tip ? " " : "") + "Needs a " + arch + " base.";
              const cost = kind !== "lora" ? "" : incompat ? (arch ? "needs " + arch : "")
                : (() => {
                    const L = typeof window !== "undefined" ? window.MG_LORA : null;
                    if (!L) return "";
                    const r = (L.ranges && L.ranges[(baseType || "").toUpperCase()]) || L.fallback;
                    if (!r || r.length < 2 || !isFinite(r[0]) || !isFinite(r[1])) return "";
                    return "weight " + Number(r[0]).toFixed(2) + "–" + Number(r[1]).toFixed(2);
                  })();
              const clickable = !incompat || sel;   // an already-selected incompatible LoRA can still be removed
              return (
                <div key={rowKey(m) || "row-" + i} className={"mg-card" + (sel ? " sel" : "") + (incompat ? " incompat" : "")}
                  data-mid={m.model_id} title={tip || undefined}
                  onClick={clickable ? () => pick(m) : undefined}
                  onMouseEnter={(e) => schedulePreview(m, e.currentTarget)}
                  onMouseLeave={hidePreview} {...longPress(m)}>
                  <div className="mg-cov">
                    {m.preview_url && <img className={m.should_blur ? "blur" : undefined} loading="lazy" src={m.preview_url} alt="" />}
                    {m.official && <span className="mg-pill">Official</span>}
                    {incompat && arch && <span className="mg-ibadge">&#9888; {arch}</span>}
                  </div>
                  <div className="mg-meta">
                    <div className="mg-nm">{m.title}</div>
                    <div className="mg-sub">
                      {arch && <span>{arch}</span>}
                      <span>{fmtCompact(m.liked_count)} likes</span>
                    </div>
                    {cost && <div className="mg-costline">{cost}</div>}
                    {market ? (
                      <KeepRow m={m} quick={!!onFav && (favs || []).includes(String(m.model_id))}
                        saved={!m.old && !!(savedStore.get(m.model_id) || {}).saved}
                        busy={busyIds.includes(String(m.model_id))} readOnly={readOnly}
                        note={notes[String(m.model_id)]}
                        onSave={() => saveModel(m)} onMenu={(el) => openKeep(m, el)}
                        onBlocked={() => note(String(m.model_id), { kind: "err", text: READ_ONLY_LINE })} />
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>

          <div ref={sentinelRef} className="mg-sentinel" aria-hidden="true" />
          <div className={"mg-loadmore" + (loadingMore ? " on" : "")} aria-hidden="true">loading more…</div>
          {savedOn && atEnd && listRows.length > 0 && !loadingMore && !err
            ? <div className="mg-saved-end">{SAVED_END_LINE}</div> : null}
          {savedOn && !setId && oldErr && showOld ? (
            <div className="mg-saved-line mg-saved-err">
              Couldn't read the old bookmarks.{" "}
              <button type="button" className="mg-saved-retry" onClick={readOld}>Retry</button>
            </div>) : null}
          {savedOn && !setId && !err && (oldAll.length > 0 || !showOld)
            ? <OldToggle on={showOld} onToggle={() => prefs.set(OLD_PREF, !showOld)} /> : null}
        </div>
      </div>

      {keep && keep.m ? (
        <KeepMenu m={keep.m} kind={kind} rect={keep.rect} sheet={phone} readOnly={readOnly}
          quick={!!onFav && (favs || []).includes(String(keep.m.model_id))}
          onQuick={onFav ? () => onFav(keep.m) : null}
          onSets={(sets) => applySets(keep.m, sets)} onClose={() => setKeep(null)} />
      ) : null}
      {keep && keep.gone ? (
        <GoneMenu item={keep.gone} defaultId={savedSets && savedSets.default_id} rect={keep.rect} sheet={phone}
          readOnly={readOnly} onClose={() => setKeep(null)}
          onGone={(it) => {
            setGone((g) => (g && g.items ? { items: g.items.filter((x) => x.item_id !== it.item_id) } : g));
            setSavedSets((ss) => ss && { ...ss, unavailable: Math.max(0, (ss.unavailable || 0) - 1) });
          }} />
      ) : null}

      {/* PORTALED to <body> (owner walk 2026-09-29: hovering a card on the desktop showed
          nothing). The preview is position:fixed at viewport coordinates, but the dock's model
          palette (.mgx-dock-host .mfly, dock.css) carries transform: translateX(-50%) and
          overflow: hidden -- a transformed ancestor becomes the containing block for fixed
          descendants, so the card was placed relative to the palette and clipped by it. The
          same trap the video prompt's chip preview had (VideoDrawer's .mgd-preview). The
          wrapper keeps the .model-picker class so the preview's own rules (model-picker.css,
          `.model-picker .mg-preview`, z 500 over the palette's 335) still reach it;
          display:contents gives it no box of its own. */}
      {typeof document !== "undefined" ? createPortal(
        <div className="model-picker" style={{ display: "contents" }}>
          <div className={"mg-preview" + (p ? " open" : "")} aria-hidden={p ? "false" : "true"}
            style={p ? { left: preview.x, top: preview.y } : undefined}>
            {p && (
              <>
                {(p.cover_url || p.preview_url) && <img src={p.cover_url || p.preview_url} className={p.should_blur ? "blur" : undefined} alt="" />}
                <div className="mp-meta">
                  <div className="mp-nm">{p.title}</div>
                  <div className="mp-sub">
                    <span>{tyShort(p.type)}</span>
                    {p.ref_count ? <span><Icon name="uses" /> {fmtCompact(p.ref_count)} uses</span> : null}
                    <span>♥ {fmt(p.liked_count)}</span>
                    {p.comment_count ? <span>💬 {fmt(p.comment_count)}</span> : null}
                  </div>
                  {(baseLabel(p.base_model) || p.official) && (
                    <div className="mp-badges">
                      {baseLabel(p.base_model) && <span className="bdg base">{baseLabel(p.base_model)}</span>}
                      {p.official && <span className="bdg official" title="In-house / official model">✓ Official</span>}
                    </div>
                  )}
                  {p.description && <div className="mp-desc">{p.description}</div>}
                </div>
              </>
            )}
          </div>
        </div>, document.body) : null}
    </div>
  );
}
