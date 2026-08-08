import React, { useCallback, useEffect, useRef, useState } from "react";
import "../styles/model-picker.css";

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
   re-reveal (each instance keeps its own last search), matching the element's contract. */

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
const BASE_TYPES = [
  ["", "All"], ["MMDIT26B_MODEL", "DiT.3"], ["MMDIT26A_MODEL", "DiT.2"], ["DIT7_MODEL", "DiT.1"],
  ["USER_DIT26A_MODEL", "Community DiT"], ["SDXL_MODEL", "SDXL"], ["SD_V1_MODEL", "SD 1.5"],
];
const SORTS = [["trending", "Trending"], ["liked", "Most Liked"], ["used", "Most Used"], ["newest", "Latest"]];

export default function ModelPicker({
  kind = "base", multi = false, market = false, baseType = "",
  value = null, selected = [], onPick, onToggle, visible = true,
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

  const seqRef = useRef(0);
  const cursorRef = useRef("");
  const hasMoreRef = useRef(false);
  const loadingMoreRef = useRef(false);
  const gridRef = useRef(null);
  const lastKeyRef = useRef(null);
  const previewTimerRef = useRef(null);
  const scrollRafRef = useRef(null);
  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  useEffect(() => {
    const t = setTimeout(() => setQDebounced(q), 250);
    return () => clearTimeout(t);
  }, [q]);

  // Shared by the fresh search and the load-more continuation so the two can never drift.
  const searchUrl = useCallback((cursor) => {
    let u = "/api/model-search?kind=" + encodeURIComponent(kind) + "&size=24&q=" + encodeURIComponent(qDebounced || "");
    if (market) {
      u += "&src=" + encodeURIComponent(src);
      if (src !== "bookmark") {
        u += "&sort=" + encodeURIComponent(sort) + "&category=" + encodeURIComponent(category) +
             "&posted=" + encodeURIComponent(posted) + "&source=" + encodeURIComponent(source) +
             "&license=" + encodeURIComponent(license);
        modelTypes.forEach((t) => { u += "&model_type=" + encodeURIComponent(t); });
      }
    }
    if (kind === "lora" && baseType) u += "&base_type=" + encodeURIComponent(baseType);
    if (cursor) u += "&cursor=" + encodeURIComponent(cursor);
    return u;
  }, [kind, qDebounced, market, src, sort, category, posted, source, license, modelTypes, baseType]);

  const doSearch = useCallback(() => {
    const mine = ++seqRef.current;
    cursorRef.current = ""; hasMoreRef.current = false;
    setDim(true);
    fetch(searchUrl()).then((r) => r.json()).then((d) => {
      if (mine !== seqRef.current) return;
      hasMoreRef.current = !!(d && d.has_more);
      cursorRef.current = (d && d.next_cursor) || "";
      setErr(d && d.error ? d.error : "");
      setRows((d && d.results) || []);
      setDim(false);
    }).catch(() => {
      if (mine !== seqRef.current) return;
      setErr("network error"); setRows([]); setDim(false);
    });
  }, [searchUrl]);

  const loadMore = useCallback(() => {
    if (!hasMoreRef.current || loadingMoreRef.current) return;
    const mine = seqRef.current;
    loadingMoreRef.current = true; setLoadingMore(true);
    fetch(searchUrl(cursorRef.current)).then((r) => r.json()).then((d) => {
      loadingMoreRef.current = false; setLoadingMore(false);
      if (mine !== seqRef.current) return;   // a fresh search superseded this continuation
      if (d && d.error) return;              // transient: leave hasMore/cursor, next scroll retries
      hasMoreRef.current = !!(d && d.has_more);
      cursorRef.current = (d && d.next_cursor) || "";
      setRows((old) => old.concat((d && d.results) || []));
    }).catch(() => { loadingMoreRef.current = false; setLoadingMore(false); });
  }, [searchUrl]);

  // browse-on-open + re-search on any filter change, but NOT on a plain re-reveal (ensureSearched
  // + _stale semantics): the search key is the fresh-list url; unchanged key => skip.
  useEffect(() => {
    if (!visible) return;
    const key = searchUrl();
    if (key === lastKeyRef.current) return;
    lastKeyRef.current = key;
    doSearch();
  }, [visible, searchUrl, doSearch]);

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
    fetch("/api/model-version?model_id=" + encodeURIComponent(m.model_id) + "&all=1")
      .then((r) => r.json()).then((d) => {
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
    clearTimeout(previewTimerRef.current);
    previewTimerRef.current = setTimeout(() => showPreview(m, anchorEl), 130);
  };
  const hidePreview = () => { clearTimeout(previewTimerRef.current); setPreview(null); };

  useEffect(() => () => { clearTimeout(previewTimerRef.current); if (scrollRafRef.current) cancelAnimationFrame(scrollRafRef.current); }, []);

  const filtersHidden = market && src === "bookmark";
  const p = preview && preview.m;

  return (
    <div className="model-picker">
      <input className="mg-q" type="text" placeholder="Search" aria-label="Search models"
        value={q} onChange={(e) => setQ(e.target.value)} />

      {market && (
        <>
          <div className="mg-mktsrc">
            {[["market", "Market"], ["bookmark", "Bookmarked"], ...(kind === "lora" ? [["mine", "Mine"]] : [])].map(([v, label]) => (
              <button type="button" key={v} className={src === v ? "on" : ""} data-src={v}
                onClick={() => setSrc(v)}>{label}</button>
            ))}
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

      {err ? <div className="mg-empty" style={{ display: "block" }}>⚠ {err}</div>
        : !rows.length ? <div className="mg-empty" style={{ display: "block" }}>No results — try another search.</div>
        : <div className="mg-empty" />}

      <div className="mg-grid" role="listbox" ref={gridRef} onScroll={onScroll}
        style={{ opacity: dim ? 0.45 : 1 }}>
        {rows.map((m) => {
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
            <div key={m.model_id} className={"mg-card" + (sel ? " sel" : "") + (incompat ? " incompat" : "")}
              data-mid={m.model_id} title={tip || undefined}
              onClick={clickable ? () => pick(m) : undefined}
              onMouseEnter={(e) => schedulePreview(m, e.currentTarget)}
              onMouseLeave={hidePreview}>
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
              </div>
            </div>
          );
        })}
      </div>

      <div className={"mg-loadmore" + (loadingMore ? " on" : "")} aria-hidden="true">loading more…</div>

      <div className={"mg-preview" + (p ? " open" : "")} aria-hidden={p ? "false" : "true"}
        style={p ? { left: preview.x, top: preview.y } : undefined}>
        {p && (
          <>
            {(p.cover_url || p.preview_url) && <img src={p.cover_url || p.preview_url} className={p.should_blur ? "blur" : undefined} alt="" />}
            <div className="mp-meta">
              <div className="mp-nm">{p.title}</div>
              <div className="mp-sub">
                <span>{tyShort(p.type)}</span>
                {p.ref_count ? <span>◈ {fmtCompact(p.ref_count)} uses</span> : null}
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
    </div>
  );
}
