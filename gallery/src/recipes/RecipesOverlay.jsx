import React, { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { requestPrice } from "../gen/priceRequest.js";
import useAccountPrefs from "../hooks/useAccountPrefs.js";
import { recipeMeta, recipesApi } from "./recipesApi.js";
import {
  addToDock, cacheCards, cachedCard, getSnapshot, openCreator, removeFromDock, subscribe, updateOpen,
} from "./recipesStore.js";
import {
  CATEGORIES, DRAFT_PREFIX, MAX_RECIPES, SORTS, TABS, addRecipe, authorName, categoryLabel, compact,
  draftFromRecipe, draftId, draftsFromPrefs, filterChips, fmt, hasRecipe, kindLabel, kindsText,
  marketQuery, misfitOf, modelTypeLabel, promptAddLine, removeRecipe, savedAgo, shelfLine, statusAction,
  statusPill,
} from "./recipesCore.js";
import RecipeSetsMenu from "./RecipeSetsMenu.jsx";

/* THE RECIPES PICKER, desktop -- one overlay, two sizes (K decision 1, H decision 3).

   compact  H §C: 780 px, a 4-up grid of square live-sample tiles (uses count, ✓ when in
            the dock), a 210 px detail pane with the prompt-length line and + Add, and the
            footer's count + Done.
   market   K §A: inset 24 px, 3:4 cards auto-filling from 150 px (category, ↗ uses,
            🔒 Followers; title, author, ♡), the 300 px pane with "what it adds", Open page
            and + Use in dock; filters as × chips; a recipe's page replaces grid and pane.
   ⤢ / ⤡ switch sizes; tab, search, filters and selection carry across (they live here, and
   only the size class changes). The last size is remembered per account.

   Tabs: Market · Sets · Mine · History. Misfits follow T2b everywhere a recipe can be
   added: the model (the card's own field, no call), the card's usability, the prompt
   budget, and -- on hover or focus, when the dock published its request -- PixAI's own
   verdict from the one price transport with the candidate added. A misfit's art dims to .42, its
   reason tag stays opaque, and + Add is off. The price and any refusal are always the
   dock's; nothing here spends. */

const PAGE_SIZE = 24;

function Art({ src, alt }) {
  const [bad, setBad] = useState(false);
  if (!src || bad) return <span className="rcp-art rcp-art-empty" aria-hidden="true">⁂</span>;
  return <img className="rcp-art" src={src} alt={alt || ""} loading="lazy" onError={() => setBad(true)} />;
}

function useDebounced(v, ms) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

export default function RecipesOverlay({ open, onClose, closing }) {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const dock = snap.dock;
  const payload = (snap.request && snap.request.payload) || null;
  const prefs = useAccountPrefs();
  const size = (open.size || prefs.get("recipes.picker-size", "compact")) === "market" ? "market" : "compact";

  const [meta, setMeta] = useState(null);
  const [tab, setTab] = useState(open.tab || "market");
  const [q, setQ] = useState("");
  const qd = useDebounced(q, 300);
  const [sort, setSort] = useState("trending");
  const [category, setCategory] = useState("");
  const [modelType, setModelType] = useState(dock.modelType || "");
  const [pop, setPop] = useState("");               // "sort" | "filters" | ""
  const [codeOpen, setCodeOpen] = useState(false);
  const [selId, setSelId] = useState(open.selectedId || "");
  const [pageId, setPageId] = useState(open.pageId || "");
  const [items, setItems] = useState([]);
  const [pageNo, setPageNo] = useState(1);
  const [totalPage, setTotalPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [refusals, setRefusals] = useState({});
  const [note, setNote] = useState("");             // a refusal on + Add ("Up to 10 …")
  const [menu, setMenu] = useState(null);           // {id, rect} -- Save to a recipe set
  const [inSet, setInSet] = useState({});           // recipe id -> in any set (⊕ -> ✓)
  const seq = useRef(0);
  const fitSeen = useRef(new Map());
  const hoverTimer = useRef(0);

  useEffect(() => { recipeMeta().then((m) => setMeta(m || {})); }, []);
  // A new open() (the row's chip, the palette) may name a recipe or a tab.
  useEffect(() => {
    if (open.selectedId) setSelId(open.selectedId);
    if (open.pageId !== undefined) setPageId(open.pageId || "");
    if (open.tab) setTab(open.tab);
  }, [open.selectedId, open.pageId, open.tab]);

  const setSize = (s) => {
    updateOpen({ size: s });
    prefs.set("recipes.picker-size", s);
  };

  // ---- loading the grid -----------------------------------------------------------------
  const load = useCallback((more) => {
    const my = ++seq.current;
    const p = more ? pageNo + 1 : 1;
    setLoading(true);
    setErr("");
    let pr;
    if (tab === "market") pr = recipesApi.market(marketQuery({ sort, category, modelType, q: qd, page: p }));
    else if (tab === "history") pr = recipesApi.recent(modelType);
    else pr = Promise.resolve({ items: [] });
    pr.then((d) => {
      if (my !== seq.current) return;
      setLoading(false);
      if (!d || d.error) { setErr((d && d.error) || "PixAI didn't answer"); if (!more) setItems([]); return; }
      cacheCards(d.items || []);
      setItems((cur) => (more ? [...cur, ...(d.items || [])] : (d.items || [])));
      setPageNo(d.page || p);
      setTotalPage(d.total_page || 0);
    });
  }, [tab, sort, category, modelType, qd, pageNo]);

  useEffect(() => { if (tab === "market" || tab === "history") load(false); },
    [tab, sort, category, modelType, qd]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- fit ------------------------------------------------------------------------------
  const ctx = useMemo(() => ({
    modelType: dock.modelType || "", modelTitle: dock.modelTitle || "",
    promptLen: payload && typeof payload.prompt === "string" ? payload.prompt.length : null,
    recipes: dock.recipes || [], refusals,
  }), [dock.modelType, dock.modelTitle, dock.recipes, payload, refusals]);
  const fitOf = useCallback((card) => (card ? misfitOf(card, ctx) : null), [ctx]);

  /* T2b's price check: on hover or focus, the dock's own request with this recipe added,
     through the one price transport. Asked once per (recipe, request); PixAI's refusal
     naming this recipe marks it. Nothing is asked without a published request. */
  const checkFit = useCallback((card) => {
    if (!payload || !card || !card.id || fitOf(card) || hasRecipe(dock.recipes, card.id)) return;
    const ids = (dock.recipes || []).map((r) => String(r.id));
    const body = { ...payload, recipeIds: [...ids, String(card.id)] };
    const key = card.id + "|" + JSON.stringify(payload);
    if (fitSeen.current.has(key)) return;
    fitSeen.current.set(key, true);
    requestPrice(body).then(({ response, failed }) => {
      if (failed || !response) { fitSeen.current.delete(key); return; }
      const re = response.recipe_error;
      if (re && (re.recipe_ids || []).map(String).includes(String(card.id))) {
        setRefusals((r) => ({ ...r, [String(card.id)]: re }));
      }
    });
  }, [payload, dock.recipes, fitOf]);
  const hoverIn = (card) => { clearTimeout(hoverTimer.current); hoverTimer.current = setTimeout(() => checkFit(card), 250); };
  const hoverOut = () => clearTimeout(hoverTimer.current);
  useEffect(() => () => clearTimeout(hoverTimer.current), []);

  // ---- the dock -------------------------------------------------------------------------
  const inDock = (id) => hasRecipe(dock.recipes, id);
  const toggleDock = (card) => {
    setNote("");
    if (inDock(card.id)) { removeFromDock(card.id, removeRecipe); return; }
    const mf = fitOf(card);
    if (mf) { setNote("“" + card.title + "” " + mf.why + "."); return; }
    const why = addToDock(card, addRecipe);
    if (why) setNote(why);
  };

  const sel = selId ? (items.find((c) => String(c.id) === String(selId)) || cachedCard(selId)) : null;

  // ---- keys: Escape closes the innermost layer ------------------------------------------
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      e.stopPropagation(); e.preventDefault();
      if (menu) { setMenu(null); return; }
      if (pop) { setPop(""); return; }
      if (codeOpen) { setCodeOpen(false); return; }
      if (pageId) { setPageId(""); return; }
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [menu, pop, codeOpen, pageId, onClose]);

  const openMenu = (e, card) => {
    e.stopPropagation();
    const r = e.currentTarget.getBoundingClientRect();
    setMenu({ id: String(card.id), title: card.title, rect: { left: r.left, top: r.bottom + 6, right: r.right } });
  };

  const chips = filterChips({ category, modelType });
  const models = (meta && meta.model_types) || ["MMDIT26B_MODEL", "MMDIT26A_MODEL", "SDXL_MODEL"];
  const cats = (meta && meta.categories) || CATEGORIES.map((c) => c[0]);
  const picked = (dock.recipes || []).length;

  const create = () => {
    openCreator({
      prefill: {
        model: payload ? { model_id: payload.model_id || "", version_id: payload.version_id || "",
          model_type: dock.modelType || "", title: dock.modelTitle || "" } : { model_type: dock.modelType || "" },
        prompt: payload && typeof payload.prompt === "string" ? payload.prompt : "",
      },
    });
  };

  return (
    <>
      <div className={"rcp-scrim" + (closing ? " closing" : "")} onClick={onClose} aria-hidden="true" />
      <div className={"rcp-host" + (closing ? " closing" : "")}>
        <div className={"rcp-slab " + (size === "market" ? "rcp-mkt" : "rcp-compact")} role="dialog" aria-modal="true" aria-label="Recipes"
          onClick={() => { setPop(""); }}>
          <div className="rcp-head">
            <div className="rcp-title">{size === "market" ? "⁂ Recipes" : "Recipes"}</div>
            <label className="rcp-search">
              <span aria-hidden="true">⌕</span>
              <input value={q} onChange={(e) => { setQ(e.target.value); if (tab !== "market") setTab("market"); }}
                placeholder="Search recipes" aria-label="Search recipes" />
            </label>
            {size === "market" && (
              <>
                <div className="rcp-popwrap">
                  <button type="button" className="rcp-btn" onClick={(e) => { e.stopPropagation(); setPop(pop === "sort" ? "" : "sort"); }}
                    disabled={!!q.trim()} title={q.trim() ? "A search lists newest first" : ""}>
                    ↗ {(SORTS.find((s) => s[0] === sort) || SORTS[0])[1]} ▾
                  </button>
                  {pop === "sort" && <SortPop sort={sort} onPick={(s) => { setSort(s); setPop(""); }} />}
                </div>
                <div className="rcp-popwrap">
                  <button type="button" className={"rcp-btn" + (chips.length ? " on" : "")}
                    onClick={(e) => { e.stopPropagation(); setPop(pop === "filters" ? "" : "filters"); }}>
                    Filters{chips.length ? " · " + chips.length : ""} ▾
                  </button>
                  {pop === "filters" && (
                    <FiltersPop cats={cats} models={models} category={category} modelType={modelType}
                      onCategory={setCategory} onModel={setModelType} />
                  )}
                </div>
              </>
            )}
            <button type="button" className={"rcp-btn" + (codeOpen ? " on" : "")} onClick={() => setCodeOpen((v) => !v)}>Style code</button>
            <button type="button" className="rcp-btn rcp-btn-strong" onClick={create}>+ Create</button>
            <button type="button" className="rcp-btn rcp-size" title={size === "market" ? "Back to the compact picker" : "Open the market"}
              onClick={() => setSize(size === "market" ? "compact" : "market")}>{size === "market" ? "⤡" : "⤢ Market"}</button>
            <button type="button" className="rcp-x" onClick={onClose} aria-label="Close">×</button>
          </div>

          {codeOpen && <StyleCodeRow payload={payload} onAdd={toggleDock} inDock={inDock} fitOf={fitOf} />}

          {pageId ? (
            <RecipePage id={pageId} ctx={ctx} fitOf={fitOf} inDock={inDock} onBack={() => setPageId("")}
              onToggle={toggleDock} note={note} onMenu={openMenu} inSet={inSet} />
          ) : (
            <div className="rcp-body">
              <div className="rcp-main">
                <div className="rcp-tabs">
                  {TABS.map(([k, label]) => (
                    <button key={k} type="button" className={"rcp-tab" + (tab === k ? " on" : "")} onClick={() => setTab(k)}>
                      {size === "compact" ? label.toUpperCase() : label}
                    </button>
                  ))}
                  <span className="rcp-flex" />
                  {size === "compact" && tab === "market" && !q.trim() && (
                    <div className="rcp-popwrap">
                      <button type="button" className="rcp-sortlink" onClick={(e) => { e.stopPropagation(); setPop(pop === "sort" ? "" : "sort"); }}>
                        {(SORTS.find((s) => s[0] === sort) || SORTS[0])[1]} ▾
                      </button>
                      {pop === "sort" && <SortPop sort={sort} onPick={(s) => { setSort(s); setPop(""); }} right />}
                    </div>
                  )}
                  {tab === "market" && chips.map((c) => (
                    <button key={c.key} type="button" className="rcp-fchip"
                      onClick={() => (c.key === "category" ? setCategory("") : setModelType(""))}>{c.text} ×</button>
                  ))}
                </div>
                {tab === "mine" ? (
                  <MineTab prefs={prefs} onOpenPage={(id) => { setSelId(id); setPageId(id); }} />
                ) : tab === "sets" ? (
                  <SetsTab size={size} fitOf={fitOf} selId={selId} onSelect={setSelId} inDock={inDock}
                    onMenu={openMenu} inSet={inSet} hoverIn={hoverIn} hoverOut={hoverOut} />
                ) : (
                  <Grid size={size} items={items} loading={loading} err={err} selId={selId} onSelect={setSelId}
                    fitOf={fitOf} inDock={inDock} onMenu={openMenu} inSet={inSet} hoverIn={hoverIn} hoverOut={hoverOut}
                    more={tab === "market" && pageNo < Math.min(totalPage, 20)} onMore={() => load(true)}
                    empty={tab === "history" ? "No recipes used yet." : "No recipes match."} />
                )}
              </div>
              {tab !== "mine" && <Pane size={size} card={sel} ctx={ctx} fitOf={fitOf} inDock={inDock} onToggle={toggleDock}
                onPage={(id) => setPageId(id)} onMenu={openMenu} inSet={inSet} picked={picked} note={note}
                onSwitchModel={() => setNote("Switch the model in the Generate dock, then come back.")} />}
            </div>
          )}

          {size === "compact" && !pageId && (
            <div className="rcp-foot">
              <span>Up to {MAX_RECIPES} recipes · {picked} picked · art is PixAI's live sample</span>
              <button type="button" className="rcp-done" onClick={onClose}>Done</button>
            </div>
          )}
        </div>
        {menu && (
          <RecipeSetsMenu recipeId={menu.id} title={menu.title} rect={menu.rect}
            onClose={() => setMenu(null)}
            onChanged={(id, any) => setInSet((m) => ({ ...m, [id]: any }))} />
        )}
      </div>
    </>
  );
}

function SortPop({ sort, onPick, right }) {
  return (
    <div className={"rcp-pop" + (right ? " right" : "")} onClick={(e) => e.stopPropagation()} role="menu">
      {SORTS.map(([k, l]) => (
        <button key={k} type="button" role="menuitemradio" aria-checked={sort === k}
          className={"rcp-popitem" + (sort === k ? " on" : "")} onClick={() => onPick(k)}>{l}</button>
      ))}
    </div>
  );
}

function FiltersPop({ cats, models, category, modelType, onCategory, onModel }) {
  return (
    <div className="rcp-pop rcp-filters" onClick={(e) => e.stopPropagation()}>
      <div className="rcp-kicker">CATEGORY</div>
      <div className="rcp-chipset">
        <button type="button" className={"rcp-pchip" + (!category ? " on" : "")} onClick={() => onCategory("")}>All</button>
        {cats.map((c) => (
          <button key={c} type="button" className={"rcp-pchip" + (category === c ? " on" : "")} onClick={() => onCategory(c)}>{categoryLabel(c)}</button>
        ))}
      </div>
      <div className="rcp-kicker">MODEL</div>
      <div className="rcp-chipset">
        <button type="button" className={"rcp-pchip" + (!modelType ? " on" : "")} onClick={() => onModel("")}>All</button>
        {models.map((m) => (
          <button key={m} type="button" className={"rcp-pchip" + (modelType === m ? " on" : "")} onClick={() => onModel(m)}>{modelTypeLabel(m)}</button>
        ))}
      </div>
    </div>
  );
}

/* H §C's inline lookup: a legacy style code -> the recipe that replaced it. */
function StyleCodeRow({ payload, onAdd, inDock, fitOf }) {
  const [code, setCode] = useState("");
  const [state, setState] = useState(null);   // null | "busy" | {recipe} | {none} | {error}
  const vid = payload && payload.version_id;
  const find = () => {
    if (!code.trim()) return;
    if (!vid) { setState({ error: "Pick a model in the Generate dock first — a code is looked up for one model." }); return; }
    setState("busy");
    recipesApi.styleCode(code.trim(), vid).then((d) => {
      if (!d || d.error) setState({ error: (d && d.error) || "PixAI didn't answer" });
      else if (!d.recipe) setState({ none: true });
      else { cacheCards([d.recipe]); setState({ recipe: d.recipe }); }
    });
  };
  const r = state && state.recipe;
  const mf = r ? fitOf(r) : null;
  return (
    <div className="rcp-code">
      <div className="rcp-code-help">Style codes are from before Recipes. Paste one to find the recipe that replaced it.</div>
      <div className="rcp-code-row">
        <input className="rcp-code-in" value={code} onChange={(e) => setCode(e.target.value)} maxLength={100}
          onKeyDown={(e) => { if (e.key === "Enter") find(); }} placeholder="Style code" aria-label="Style code" />
        <button type="button" className="rcp-primary" onClick={find} disabled={state === "busy"}>Find recipe</button>
      </div>
      {state && state !== "busy" && (
        <div className="rcp-code-out">
          {r ? (
            <>
              <span className="rcp-code-thumb"><Art src={r.cover} /></span>
              <span>Found: <b>{r.title}</b></span>
              {mf ? <span className="rcp-peach">{mf.why}</span>
                : <button type="button" className="rcp-link" onClick={() => onAdd(r)}>{inDock(r.id) ? "✓ Added" : "+ Add"}</button>}
            </>
          ) : state.none ? <span className="rcp-muted">No recipe replaces this code</span>
            : <span className="rcp-peach">{state.error}</span>}
        </div>
      )}
    </div>
  );
}

function Grid({ size, items, loading, err, selId, onSelect, fitOf, inDock, onMenu, inSet, hoverIn, hoverOut, more, onMore, empty }) {
  return (
    <div className="rcp-scroll">
      <div className={size === "market" ? "rcp-cards" : "rcp-tiles"}>
        {items.map((c) => (size === "market"
          ? <Card key={c.id} c={c} sel={String(selId) === String(c.id)} misfit={fitOf(c)} inDock={inDock(c.id)}
              onSelect={onSelect} onMenu={onMenu} saved={inSet[String(c.id)]} hoverIn={hoverIn} hoverOut={hoverOut} />
          : <Tile key={c.id} c={c} sel={String(selId) === String(c.id)} misfit={fitOf(c)} inDock={inDock(c.id)}
              onSelect={onSelect} hoverIn={hoverIn} hoverOut={hoverOut} />))}
      </div>
      {loading && <div className="rcp-status">Reading PixAI's market…</div>}
      {!loading && err && <div className="rcp-status rcp-peach">{err}</div>}
      {!loading && !err && !items.length && <div className="rcp-status">{empty}</div>}
      {!loading && more && <button type="button" className="rcp-more" onClick={onMore}>More</button>}
    </div>
  );
}

function Tile({ c, sel, misfit, inDock, onSelect, hoverIn, hoverOut }) {
  return (
    <button type="button" className={"rcp-tile" + (sel ? " sel" : "") + (misfit ? " misfit" : "")}
      onClick={() => onSelect(String(c.id))} onMouseEnter={() => hoverIn(c)} onMouseLeave={hoverOut}
      onFocus={() => hoverIn(c)} onBlur={hoverOut} title={c.title}>
      <span className="rcp-tile-art">
        <Art src={c.cover} />
        <span className="rcp-uses">{compact(c.uses)}</span>
        {inDock && <span className="rcp-tick" aria-label="in the dock">✓</span>}
        {misfit && <span className="rcp-misfit-tag rcp-misfit-foot">{misfit.tag}</span>}
      </span>
      <span className="rcp-tile-name">{c.title}</span>
    </button>
  );
}

function Card({ c, sel, misfit, inDock, onSelect, onMenu, saved, hoverIn, hoverOut }) {
  return (
    <div className={"rcp-card" + (sel ? " sel" : "") + (misfit ? " misfit" : "")} role="button" tabIndex={0}
      onClick={() => onSelect(String(c.id))} onKeyDown={(e) => { if (e.key === "Enter") onSelect(String(c.id)); }}
      onMouseEnter={() => hoverIn(c)} onMouseLeave={hoverOut} onFocus={() => hoverIn(c)} onBlur={hoverOut}>
      <span className="rcp-card-art"><Art src={c.cover} alt={c.title} /></span>
      <span className="rcp-badges">
        {c.category && <span className="rcp-badge rcp-badge-strong">{categoryLabel(c.category)}</span>}
        <span className="rcp-badge">↗ {compact(c.uses)}</span>
        {c.followers_only && <span className="rcp-badge rcp-badge-mauve">🔒 Followers</span>}
      </span>
      <button type="button" className={"rcp-save" + (saved ? " on" : "")} onClick={(e) => onMenu(e, c)}
        aria-label={saved ? "In a recipe set" : "Save to a recipe set"} title="Save to a recipe set">{saved ? "✓" : "⊕"}</button>
      {inDock && <span className="rcp-tick rcp-tick-card" aria-label="in the dock">✓</span>}
      {misfit && <span className="rcp-misfit-tag rcp-misfit-mid">{misfit.tag}</span>}
      <span className="rcp-card-foot">
        <span className="rcp-card-title">{c.title}</span>
        <span className="rcp-card-by"><span>{authorName(c)}</span><span>♡ {compact(c.likes)}</span></span>
      </span>
    </div>
  );
}

function Pane({ size, card, ctx, fitOf, inDock, onToggle, onPage, onMenu, inSet, picked, note, onSwitchModel }) {
  if (!card) {
    return (
      <aside className={"rcp-pane " + (size === "market" ? "rcp-pane-mkt" : "rcp-pane-compact")}>
        <div className="rcp-pane-empty">Pick a recipe to see what it adds.</div>
        {size === "market" && <div className="rcp-pane-count">{picked} / {MAX_RECIPES} in the dock</div>}
      </aside>
    );
  }
  const mf = fitOf(card);
  const on = inDock(card.id);
  const saved = inSet[String(card.id)] || card.in_set;
  if (size === "compact") {
    return (
      <aside className="rcp-pane rcp-pane-compact">
        <span className="rcp-pane-sq"><Art src={card.cover} alt={card.title} /></span>
        <div className="rcp-pane-title">{card.title}</div>
        <div className="rcp-pane-by">{authorName(card)}</div>
        <div className="rcp-pane-kv first"><span>CATEGORY</span><b>{categoryLabel(card.category) || "—"}</b></div>
        <div className="rcp-pane-kv"><span>MODEL</span><b>{card.model_title || modelTypeLabel(card.model_type) || "—"}</b></div>
        <div className="rcp-pane-len">Adds to the prompt: <span className="rcp-mono">{promptAddLine(card, ctx)}</span></div>
        {mf && <div className="rcp-peach rcp-pane-why">{mf.why}. <span className="rcp-lav">{mf.fix}</span></div>}
        {note && !mf && <div className="rcp-peach rcp-pane-why">{note}</div>}
        <button type="button" className={"rcp-add" + (on ? " on" : "")} disabled={!!mf && !on} onClick={() => onToggle(card)}>
          {on ? "✓ Added · Remove" : "+ Add"}
        </button>
      </aside>
    );
  }
  return (
    <aside className="rcp-pane rcp-pane-mkt">
      <span className="rcp-pane-cover">
        <Art src={card.cover} alt={card.title} />
        <button type="button" className="rcp-pane-save" onClick={(e) => onMenu(e, card)}>{saved ? "✓ In a set" : "⊕ Save to…"}</button>
      </span>
      <div className="rcp-pane-title">{card.title}</div>
      <div className="rcp-pane-by">{authorName(card)} · {categoryLabel(card.category) || "—"} · {card.model_title || modelTypeLabel(card.model_type)}</div>
      <div className="rcp-pane-stats rcp-mono"><span>♡ {compact(card.likes)}</span><span>↗ {compact(card.uses)}</span><span>▦ {compact(card.artworks)}</span></div>
      <div className="rcp-kicker">WHAT IT ADDS</div>
      <div className="rcp-kinds">{(card.kinds || []).map((k) => <span key={k.type} className="rcp-kind">{kindLabel(k)}</span>)}</div>
      <div className="rcp-pane-fine">Kinds only; a published recipe never shows its prompt text.</div>
      {mf && (
        <div className="rcp-peach rcp-pane-why">{mf.why}.{" "}
          {mf.group === "model" ? <button type="button" className="rcp-link" onClick={onSwitchModel}>Switch the dock's model</button>
            : <span className="rcp-lav">{mf.fix}</span>}
        </div>
      )}
      {note && !mf && <div className="rcp-peach rcp-pane-why">{note}</div>}
      <div className="rcp-pane-acts">
        <button type="button" className="rcp-ghost" onClick={() => onPage(String(card.id))}>Open page</button>
        <button type="button" className={"rcp-add" + (on ? " on" : "")} disabled={!!mf && !on} onClick={() => onToggle(card)}>
          {on ? "✓ In the dock" : "+ Use in dock"}
        </button>
      </div>
      <div className="rcp-pane-count">{picked} / {MAX_RECIPES} in the dock</div>
    </aside>
  );
}

/* K §B: a recipe's page, inside the same overlay -- carousel, description, what it adds,
   "made with it", and the Use panel (the price and any refusal stay the dock's). */
function RecipePage({ id, fitOf, inDock, onBack, onToggle, note, onMenu, inSet }) {
  const [card, setCard] = useState(cachedCard(id));
  const [err, setErr] = useState("");
  const [art, setArt] = useState(null);
  useEffect(() => {
    let live = true;
    recipesApi.detail(id).then((d) => {
      if (!live) return;
      if (!d || d.error || !d.recipe) { setErr((d && d.error) || "PixAI didn't answer"); return; }
      cacheCards([d.recipe]); setCard(d.recipe);
    });
    recipesApi.artworks(id).then((d) => { if (live) setArt(d && !d.error ? (d.items || []) : []); });
    return () => { live = false; };
  }, [id]);
  if (!card) return <div className="rcp-page"><button type="button" className="rcp-back" onClick={onBack}>‹ Market</button><div className="rcp-status">{err || "Reading the recipe…"}</div></div>;
  const mf = fitOf(card);
  const on = inDock(card.id);
  const shots = (card.showcases && card.showcases.length ? card.showcases.map((s) => s.url) : [card.cover]).filter(Boolean);
  const pub = card.published_at ? new Date(card.published_at) : null;
  const saved = inSet[String(card.id)] || card.in_set;
  return (
    <div className="rcp-page">
      <div className="rcp-page-main">
        <div className="rcp-page-head">
          <button type="button" className="rcp-back" onClick={onBack}>‹ Market</button>
          <div className="rcp-page-title">{card.title}</div>
          <button type="button" className="rcp-ghost-sm" onClick={(e) => onMenu(e, card)}>{saved ? "✓ In a set" : "⊕ Save to…"}</button>
          <span className="rcp-ghost-sm rcp-static">♡ {fmt(card.likes)}</span>
        </div>
        <div className="rcp-page-meta">
          {authorName(card)} · {categoryLabel(card.category) || "—"} · {card.model_title || modelTypeLabel(card.model_type)}
          {pub && !isNaN(pub) ? " · published " + pub.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : ""}
          {" · ↗ " + compact(card.uses) + " uses · ▦ " + compact(card.artworks) + " artworks"}
        </div>
        <div className="rcp-carousel">
          <span className="rcp-car-big"><Art src={shots[0]} alt={card.title} /></span>
          <span className="rcp-car-col">
            <span className="rcp-car-small"><Art src={shots[1] || shots[0]} /></span>
            <span className="rcp-car-small"><Art src={shots[2] || shots[0]} /></span>
          </span>
        </div>
        {card.description ? <div className="rcp-page-desc">{card.description}</div> : null}
        <div className="rcp-kicker">MADE WITH IT</div>
        <div className="rcp-made">
          {art === null ? <span className="rcp-muted">Reading…</span>
            : art.length ? art.map((a) => (
              <span key={a.id || a.media_id} className={"rcp-made-cell" + (a.blur ? " blur" : "")} title={a.title || a.author}><Art src={a.thumb} /></span>
            )) : <span className="rcp-muted">No published artworks yet.</span>}
        </div>
      </div>
      <aside className="rcp-use">
        <div className="rcp-use-title">Use this recipe</div>
        <div className="rcp-kicker">RECIPE DETAILS</div>
        <div className="rcp-kinds">{(card.kinds || []).map((k) => <span key={k.type} className="rcp-kind">{kindLabel(k)}</span>)}</div>
        <div className="rcp-use-note">Adds to the dock's current request. The price and any refusal show on the dock's Generate button, not here.</div>
        {mf && <div className="rcp-peach rcp-pane-why">{mf.why}. <span className="rcp-lav">{mf.fix}</span></div>}
        {note && !mf && <div className="rcp-peach rcp-pane-why">{note}</div>}
        <button type="button" className={"rcp-add rcp-add-big" + (on ? " on" : "")} disabled={!!mf && !on} onClick={() => onToggle(card)}>
          {on ? "✓ In the dock · Remove" : "+ Use in dock"}
        </button>
      </aside>
    </div>
  );
}

/* K decision 3: the drafts shelf (the app's own drafts) above the account's recipes. */
function MineTab({ prefs, onOpenPage }) {
  const [rows, setRows] = useState(null);
  const [err, setErr] = useState("");
  const [archived, setArchived] = useState(false);
  const [confirm, setConfirm] = useState("");     // a draft id awaiting its one delete ask
  const [busy, setBusy] = useState("");
  const [dots, setDots] = useState("");
  const [msg, setMsg] = useState("");
  const [sort, setSort] = useState("latest");
  const drafts = draftsFromPrefs(prefs.prefs);
  const now = Date.now();
  const reload = useCallback(() => {
    recipesApi.mine("", sort).then((d) => {
      if (!d || d.error) { setErr((d && d.error) || "PixAI didn't answer"); setRows([]); return; }
      cacheCards(d.items || []); setRows(d.items || []); setErr("");
    });
  }, [sort]);
  useEffect(() => { reload(); }, [reload]);
  const list = (rows || []).filter((r) => archived || r.status !== "archived");
  const act = (r) => {
    setMsg("");
    if (r.status === "published") {
      setBusy(r.id);
      recipesApi.detail(r.id).then((d) => {
        setBusy("");
        if (!d || d.error || !d.recipe) { setMsg((d && d.error) || "PixAI didn't answer"); return; }
        if (!d.recipe.slots) { setMsg("PixAI didn't send this recipe's ingredients, so it can't be edited here."); return; }
        const id = draftId(Date.now(), Math.random().toString(36).slice(2));
        const draft = draftFromRecipe(d.recipe, { id, now: Date.now() });
        prefs.set(DRAFT_PREFIX + id, draft).then(() => openCreator({ draftId: id, step: 1 }));
      });
    } else if (r.status === "archived") {
      setBusy(r.id);
      recipesApi.transition(r.id, "published").then((d) => { setBusy(""); if (d && d.error) setMsg(d.error); reload(); });
    } else onOpenPage(String(r.id));
  };
  const archive = (r) => {
    setDots(""); setBusy(r.id);
    recipesApi.transition(r.id, "archived").then((d) => { setBusy(""); if (d && d.error) setMsg(d.error); reload(); });
  };
  return (
    <div className="rcp-scroll rcp-mine">
      {drafts.length > 0 && (
        <>
          <div className="rcp-kicker">UNFINISHED · {drafts.length}</div>
          {drafts.map((d) => (
            <div key={d.id} className="rcp-shelf">
              <span className="rcp-shelf-thumb"><Art src={(d.showcase && d.showcase[0] && (d.showcase[0].thumb || "")) || ""} /></span>
              <span className="rcp-shelf-text">
                <b>{d.title || (d.editing ? "Editing a recipe" : "Untitled recipe")}</b>
                <span className="rcp-peach">{shelfLine(d)}</span>
                <span className="rcp-muted">{savedAgo(d.saved, now)} · {d.preset === "private" ? "private" : d.preset === "follow_to_use" ? "followers" : "public"}{d.recipe_id ? " · on PixAI" : ""}</span>
              </span>
              {confirm === d.id ? (
                <span className="rcp-ruby-ask">
                  <span>Delete this draft?</span>
                  <button type="button" className="rcp-ruby" onClick={() => { prefs.unset(DRAFT_PREFIX + d.id); setConfirm(""); }}>Delete</button>
                  <button type="button" className="rcp-ghost-sm" onClick={() => setConfirm("")}>Keep</button>
                </span>
              ) : (
                <>
                  <button type="button" className="rcp-link-muted" onClick={() => setConfirm(d.id)}>Delete</button>
                  <button type="button" className="rcp-primary" onClick={() => openCreator({ draftId: d.id })}>Continue</button>
                </>
              )}
            </div>
          ))}
        </>
      )}
      <div className="rcp-mine-head">
        <span className="rcp-kicker">YOUR RECIPES · {rows ? list.length : "…"}</span>
        <select className="rcp-minesort" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Sort your recipes">
          <option value="latest">Newest</option><option value="oldest">Oldest</option>
          <option value="most-liked">Most liked</option><option value="most-used">Most used</option>
        </select>
        <span className="rcp-muted">·</span>
        <label className="rcp-muted rcp-archtoggle"><input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} /> show archived</label>
      </div>
      {msg && <div className="rcp-peach rcp-status-inline">{msg}</div>}
      {err && <div className="rcp-status rcp-peach">{err}</div>}
      {rows && !err && !list.length && <div className="rcp-status">No recipes of yours{archived ? "" : " (archived ones are behind the toggle)"}.</div>}
      {list.map((r) => {
        const [label, tone] = statusPill(r.status);
        return (
          <div key={r.id} className="rcp-mine-row">
            <span className="rcp-shelf-thumb"><Art src={r.cover} /></span>
            <span className="rcp-shelf-text">
              <b>{r.title}</b>
              <span className="rcp-muted">{categoryLabel(r.category)} · {r.model_title || modelTypeLabel(r.model_type)} · {r.preset_type === "follow_to_use" ? "Followers" : r.preset_type === "private" ? "Private" : r.preset_type === "unlisted" ? "Unlisted" : "Public"}{r.status === "test" ? " · in review" : " · ↗ " + fmt(r.uses) + " uses"}</span>
            </span>
            <span className={"rcp-pill rcp-pill-" + tone}>{label}</span>
            <button type="button" className="rcp-link rcp-mine-act" disabled={busy === r.id} onClick={() => act(r)}>{busy === r.id ? "…" : statusAction(r.status)}</button>
            <span className="rcp-popwrap">
              <button type="button" className="rcp-dots" aria-label="More" onClick={() => setDots(dots === r.id ? "" : r.id)}>⋯</button>
              {dots === r.id && (
                <div className="rcp-pop right" role="menu">
                  {r.status === "published" && <button type="button" className="rcp-popitem" onClick={() => archive(r)}>Archive</button>}
                  <button type="button" className="rcp-popitem" onClick={() => { setDots(""); onOpenPage(String(r.id)); }}>Open page</button>
                </div>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* K decision 7: the Sets tab -- PixAI's collections of recipes, as rows; one opens as a grid. */
function SetsTab({ size, fitOf, selId, onSelect, inDock, onMenu, inSet, hoverIn, hoverOut }) {
  const [sets, setSets] = useState(null);
  const [err, setErr] = useState("");
  const [openSet, setOpenSet] = useState(null);
  const [items, setItems] = useState(null);
  useEffect(() => {
    recipesApi.sets().then((d) => {
      if (!d || d.error) { setErr((d && d.error) || "PixAI didn't answer"); setSets([]); return; }
      setSets(d.sets || []);
    });
  }, []);
  useEffect(() => {
    if (!openSet) return;
    setItems(null);
    recipesApi.setItems(openSet.id).then((d) => {
      if (!d || d.error) { setItems([]); setErr((d && d.error) || ""); return; }
      cacheCards(d.items || []); setItems(d.items || []);
    });
  }, [openSet]);
  if (openSet) {
    return (
      <div className="rcp-setview">
        <div className="rcp-sethead"><button type="button" className="rcp-back" onClick={() => setOpenSet(null)}>‹ Sets</button><b>{openSet.title}</b><span className="rcp-mono rcp-muted">{openSet.count}</span></div>
        <Grid size={size} items={items || []} loading={items === null} err="" selId={selId} onSelect={onSelect}
          fitOf={fitOf} inDock={inDock} onMenu={onMenu} inSet={inSet} hoverIn={hoverIn} hoverOut={hoverOut}
          more={false} onMore={() => {}} empty="This set is empty." />
      </div>
    );
  }
  return (
    <div className="rcp-scroll">
      {err && <div className="rcp-status rcp-peach">{err}</div>}
      {sets === null && <div className="rcp-status">Reading your sets…</div>}
      {sets && !sets.length && !err && <div className="rcp-status">No recipe sets yet. ⊕ on any recipe saves it to one.</div>}
      {(sets || []).map((s) => (
        <button key={s.id} type="button" className="rcp-setrow" onClick={() => setOpenSet(s)}>
          <span className="rcp-setstrip">{[0, 1, 2, 3].map((i) => <span key={i} className="rcp-setcov"><Art src={s.covers[i]} /></span>)}</span>
          <span className="rcp-setname">{s.title}</span>
          <span className="rcp-mono rcp-muted">{s.count}</span>
        </button>
      ))}
    </div>
  );
}

export { Art, kindsText };
