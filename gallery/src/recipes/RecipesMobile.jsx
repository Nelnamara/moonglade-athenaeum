import React, { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { recipeMeta, recipesApi } from "./recipesApi.js";
import {
  addToDock, cacheCards, cachedCard, getSnapshot, openCreator, removeFromDock, subscribe, updateOpen,
} from "./recipesStore.js";
import {
  CATEGORIES, MAX_RECIPES, SORTS, addRecipe, authorName, categoryLabel, compact, filterChips, fmt, hasRecipe,
  kindLabel, marketQuery, misfitOf, modelTypeLabel, removeRecipe,
} from "./recipesCore.js";
import RecipeSetsMenu from "./RecipeSetsMenu.jsx";
import { Art } from "./RecipesOverlay.jsx";

/* THE PHONE'S RECIPES (K decision 6; H §E): the tab bar stays ⛰ Gallery · ✦ Create ·
   ⚙ Control. Create's Recipes row opens

     1 · the sheet (84% tall): Recommended · Sets · History, a 3-column grid of square
         tiles; a tap adds the recipe (misfits dim with their tag); "See the market ›";
     2 · the market, pushed full screen: Market · Sets · Mine · Filters, a 2-column grid of
         3:4 cards; a tap opens the recipe, a long-press saves it to a set; "+ Create";
     3 · a recipe: cover, stats, what it adds, description, made with it, and a sticky
         "+ Use in Create" that adds the chip and pops back to Create.

   320 px floor, 44 px targets, chips 32 px tall inside 44 px rows. */
export default function RecipesMobile({ open, onClose, closing }) {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const dock = snap.dock;
  const screen = open.phoneScreen || "sheet";
  const go = (s, extra) => updateOpen({ phoneScreen: s, ...(extra || {}) });
  const payload = (snap.request && snap.request.payload) || null;
  const ctx = {
    modelType: dock.modelType || "", modelTitle: dock.modelTitle || "",
    promptLen: payload && typeof payload.prompt === "string" ? payload.prompt.length : null,
    recipes: dock.recipes || [], refusals: {},
  };
  const fitOf = (c) => (c ? misfitOf(c, ctx) : null);
  const [note, setNote] = useState("");
  const toggle = (c) => {
    setNote("");
    if (hasRecipe(dock.recipes, c.id)) { removeFromDock(c.id, removeRecipe); return true; }
    const mf = fitOf(c);
    if (mf) { setNote("“" + c.title + "” " + mf.why + "."); return false; }
    const why = addToDock(c, addRecipe);
    if (why) { setNote(why); return false; }
    return true;
  };

  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape") return;
      e.stopPropagation(); e.preventDefault();
      if (screen === "recipe") go(open.from || "market");
      else if (screen === "market") go("sheet");
      else onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className={"rcp-m" + (closing ? " closing" : "")}>
      {screen === "sheet" && (
        <>
          <div className="rcp-m-scrim" onClick={onClose} aria-hidden="true" />
          <Sheet dock={dock} fitOf={fitOf} toggle={toggle} note={note} onClose={onClose}
            onMarket={() => go("market")} onOpen={(id) => go("recipe", { pageId: id, from: "sheet" })} />
        </>
      )}
      {screen === "market" && (
        <Market dock={dock} fitOf={fitOf} onBack={() => go("sheet")}
          onOpen={(id) => go("recipe", { pageId: id, from: "market" })}
          onCreate={() => openCreator({ prefill: {
            model: payload ? { model_id: payload.model_id || "", version_id: payload.version_id || "", model_type: dock.modelType || "", title: dock.modelTitle || "" } : { model_type: dock.modelType || "" },
            prompt: payload && typeof payload.prompt === "string" ? payload.prompt : "" } }, { phone: true })} />
      )}
      {screen === "recipe" && (
        <RecipeScreen id={open.pageId} fitOf={fitOf} inDock={hasRecipe(dock.recipes, open.pageId)} note={note}
          onBack={() => go(open.from || "market")}
          onUse={(c) => { if (hasRecipe(dock.recipes, c.id) || toggle(c)) onClose(); }} />
      )}
    </div>
  );
}

function useLongPress(onLong) {
  const t = useRef(0);
  const fired = useRef(false);
  return {
    onTouchStart: (e) => { fired.current = false; clearTimeout(t.current); t.current = setTimeout(() => { fired.current = true; onLong(e); }, 500); },
    onTouchEnd: () => clearTimeout(t.current),
    onTouchMove: () => clearTimeout(t.current),
    onContextMenu: (e) => { e.preventDefault(); fired.current = true; onLong(e); },
    wasLong: () => fired.current,
  };
}

function Sheet({ dock, fitOf, toggle, note, onClose, onMarket, onOpen }) {
  const [chip, setChip] = useState("recommended");
  const [items, setItems] = useState(null);
  const [sets, setSets] = useState(null);
  const [setOpen, setSetOpen] = useState(null);
  useEffect(() => {
    setItems(null);
    if (chip === "recommended") {
      recipesApi.market(marketQuery({ sort: "trending", modelType: dock.modelType || "" })).then((d) => {
        if (d && !d.error) { cacheCards(d.items || []); setItems(d.items || []); } else setItems([]);
      });
    } else if (chip === "history") {
      recipesApi.recent(dock.modelType || "").then((d) => {
        if (d && !d.error) { cacheCards(d.items || []); setItems(d.items || []); } else setItems([]);
      });
    } else if (chip === "sets") {
      if (setOpen) {
        recipesApi.setItems(setOpen.id).then((d) => { if (d && !d.error) { cacheCards(d.items || []); setItems(d.items || []); } else setItems([]); });
      } else {
        recipesApi.sets().then((d) => setSets(d && !d.error ? (d.sets || []) : []));
        setItems([]);
      }
    }
  }, [chip, setOpen, dock.modelType]);
  const picked = (dock.recipes || []).length;
  return (
    <div className="rcp-m-sheet" role="dialog" aria-modal="true" aria-label="Add a recipe">
      <div className="rcp-m-grab" aria-hidden="true" />
      <div className="rcp-m-head"><div className="rcp-m-title">Add a recipe</div><span className="rcp-mono rcp-fine">{picked} / {MAX_RECIPES}</span>
        <button type="button" className="rcp-m-x" onClick={onClose} aria-label="Close">×</button></div>
      <div className="rcp-m-chips">
        {[["recommended", "Recommended"], ["sets", "Sets"], ["history", "History"]].map(([k, l]) => (
          <button key={k} type="button" className={"rcp-m-chip" + (chip === k ? " on" : "")} onClick={() => { setChip(k); setSetOpen(null); }}>{l}</button>
        ))}
      </div>
      {note && <div className="rcp-peach rcp-m-note">{note}</div>}
      <div className="rcp-m-scroll">
        {chip === "sets" && !setOpen ? (
          (sets || []).length ? sets.map((s) => (
            <button key={s.id} type="button" className="rcp-setrow" onClick={() => setSetOpen(s)}>
              <span className="rcp-setstrip">{[0, 1, 2].map((i) => <span key={i} className="rcp-setcov"><Art src={s.covers[i]} /></span>)}</span>
              <span className="rcp-setname">{s.title}</span><span className="rcp-mono rcp-muted">{s.count}</span>
            </button>
          )) : <div className="rcp-status">{sets === null ? "Reading your sets…" : "No recipe sets yet."}</div>
        ) : (
          <div className="rcp-m-grid3">
            {items === null ? <div className="rcp-status">Reading…</div> : !items.length ? <div className="rcp-status">Nothing here yet.</div>
              : items.map((c) => {
                const mf = fitOf(c);
                const on = hasRecipe(dock.recipes, c.id);
                return (
                  <button key={c.id} type="button" className={"rcp-m-tile" + (on ? " on" : "") + (mf ? " misfit" : "")}
                    onClick={() => toggle(c)} aria-pressed={on} aria-label={c.title + (mf ? ", " + mf.why : "")}>
                    <Art src={c.cover} />
                    {on && <span className="rcp-tick">✓</span>}
                    {mf && <span className="rcp-misfit-tag rcp-misfit-foot">{mf.tag}</span>}
                    <span className="rcp-m-tilename">{c.title}</span>
                  </button>
                );
              })}
          </div>
        )}
      </div>
      <button type="button" className="rcp-m-foot" onClick={onMarket}>See the market ›</button>
    </div>
  );
}

function Market({ dock, fitOf, onBack, onOpen, onCreate }) {
  const [tab, setTab] = useState("market");
  const [items, setItems] = useState(null);
  const [filters, setFilters] = useState(false);
  const [sort, setSort] = useState("trending");
  const [category, setCategory] = useState("");
  const [modelType, setModelType] = useState(dock.modelType || "");
  const [meta, setMeta] = useState(null);
  const [menu, setMenu] = useState(null);
  const [inSet, setInSet] = useState({});
  useEffect(() => { recipeMeta().then((m) => setMeta(m || {})); }, []);
  useEffect(() => {
    setItems(null);
    const done = (d, key) => { if (d && !d.error) { cacheCards(d[key] || []); setItems(d[key] || []); } else setItems([]); };
    if (tab === "market") recipesApi.market(marketQuery({ sort, category, modelType })).then((d) => done(d, "items"));
    else if (tab === "mine") recipesApi.mine().then((d) => done(d, "items"));
    else if (tab === "sets") recipesApi.sets().then((d) => setItems(d && !d.error ? (d.sets || []).map((s) => ({ ...s, isSet: true })) : []));
  }, [tab, sort, category, modelType]);
  const chips = filterChips({ category, modelType });
  const models = (meta && meta.model_types) || ["MMDIT26B_MODEL", "MMDIT26A_MODEL", "SDXL_MODEL"];
  return (
    <div className="rcp-m-screen" role="dialog" aria-modal="true" aria-label="Recipes">
      <div className="rcp-m-head"><button type="button" className="rcp-m-back" onClick={onBack} aria-label="Back">‹</button><div className="rcp-m-title">⁂ Recipes</div></div>
      <div className="rcp-m-chips">
        {[["market", "Market"], ["sets", "Sets"], ["mine", "Mine"]].map(([k, l]) => (
          <button key={k} type="button" className={"rcp-m-chip" + (tab === k ? " on" : "")} onClick={() => setTab(k)}>{l}</button>
        ))}
        <button type="button" className={"rcp-m-chip" + (chips.length ? " on" : "")} onClick={() => setFilters(true)}>Filters{chips.length ? " · " + chips.length : ""}</button>
      </div>
      <div className="rcp-m-scroll">
        <div className="rcp-m-grid2">
          {items === null ? <div className="rcp-status">Reading…</div> : !items.length ? <div className="rcp-status">Nothing here yet.</div>
            : items.map((c) => (c.isSet ? (
              <div key={c.id} className="rcp-m-setcard"><Art src={c.covers[0]} /><b>{c.title}</b><span className="rcp-mono">{c.count}</span></div>
            ) : <MCard key={c.id} c={c} mf={fitOf(c)} on={hasRecipe(dock.recipes, c.id)} saved={inSet[c.id]}
              onOpen={() => onOpen(String(c.id))} onLong={() => setMenu({ id: String(c.id), title: c.title })} />))}
        </div>
      </div>
      <button type="button" className="rcp-m-foot" onClick={onCreate}>+ Create</button>
      {filters && (
        <>
          <div className="rcp-m-scrim rcp-m-scrim-top" onClick={() => setFilters(false)} aria-hidden="true" />
          <div className="rcp-m-sheet rcp-m-sheet-short rcp-m-filters" role="dialog" aria-label="Sort and filters">
            <div className="rcp-m-grab" aria-hidden="true" />
            <div className="rcp-kicker">SORT</div>
            <div className="rcp-chipset">{SORTS.map(([k, l]) => <button key={k} type="button" className={"rcp-pchip" + (sort === k ? " on" : "")} onClick={() => setSort(k)}>{l}</button>)}</div>
            <div className="rcp-kicker">CATEGORY</div>
            <div className="rcp-chipset">
              <button type="button" className={"rcp-pchip" + (!category ? " on" : "")} onClick={() => setCategory("")}>All</button>
              {CATEGORIES.map(([k, l]) => <button key={k} type="button" className={"rcp-pchip" + (category === k ? " on" : "")} onClick={() => setCategory(k)}>{l}</button>)}
            </div>
            <div className="rcp-kicker">MODEL</div>
            <div className="rcp-chipset">
              <button type="button" className={"rcp-pchip" + (!modelType ? " on" : "")} onClick={() => setModelType("")}>All</button>
              {models.map((m) => <button key={m} type="button" className={"rcp-pchip" + (modelType === m ? " on" : "")} onClick={() => setModelType(m)}>{modelTypeLabel(m)}</button>)}
            </div>
            <button type="button" className="rcp-m-foot rcp-m-foot-solid" onClick={() => setFilters(false)}>Show recipes</button>
          </div>
        </>
      )}
      {menu && <RecipeSetsMenu sheet recipeId={menu.id} title={menu.title} onClose={() => setMenu(null)}
        onChanged={(id, any) => setInSet((m) => ({ ...m, [id]: any }))} />}
    </div>
  );
}

function MCard({ c, mf, on, saved, onOpen, onLong }) {
  const lp = useLongPress(onLong);
  return (
    <button type="button" className={"rcp-m-card" + (mf ? " misfit" : "")} {...lp}
      onClick={() => { if (!lp.wasLong()) onOpen(); }} aria-label={c.title}>
      <span className="rcp-card-art"><Art src={c.cover} alt="" /></span>
      <span className="rcp-badges">
        {c.category && <span className="rcp-badge rcp-badge-strong">{categoryLabel(c.category)}</span>}
        <span className="rcp-badge">↗ {compact(c.uses)}</span>
        {c.followers_only && <span className="rcp-badge rcp-badge-mauve">🔒</span>}
      </span>
      {(on || saved) && <span className="rcp-tick rcp-tick-card">✓</span>}
      {mf && <span className="rcp-misfit-tag rcp-misfit-mid">{mf.tag}</span>}
      <span className="rcp-card-foot"><span className="rcp-card-title">{c.title}</span>
        <span className="rcp-card-by"><span>{authorName(c)}</span><span>♡ {compact(c.likes)}</span></span></span>
    </button>
  );
}

function RecipeScreen({ id, fitOf, inDock, note, onBack, onUse }) {
  const [card, setCard] = useState(cachedCard(id));
  const [art, setArt] = useState(null);
  const [menu, setMenu] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    let live = true;
    recipesApi.detail(id).then((d) => { if (live && d && !d.error && d.recipe) { cacheCards([d.recipe]); setCard(d.recipe); setSaved(!!d.recipe.in_set); } });
    recipesApi.artworks(id).then((d) => { if (live) setArt(d && !d.error ? (d.items || []) : []); });
    return () => { live = false; };
  }, [id]);
  const mf = card ? fitOf(card) : null;
  return (
    <div className="rcp-m-screen" role="dialog" aria-modal="true" aria-label={card ? card.title : "Recipe"}>
      <div className="rcp-m-head"><button type="button" className="rcp-m-back" onClick={onBack} aria-label="Back">‹</button><div className="rcp-m-title">{card ? card.title : "Recipe"}</div></div>
      {card && (
        <div className="rcp-m-chips">
          <button type="button" className={"rcp-m-chip" + (saved ? " on" : "")} onClick={() => setMenu(true)}>{saved ? "✓ In a set" : "⊕ Save to…"}</button>
          <span className="rcp-m-chip rcp-static">♡ {fmt(card.likes)}</span>
        </div>
      )}
      <div className="rcp-m-scroll rcp-m-recipe">
        {!card ? <div className="rcp-status">Reading the recipe…</div> : (
          <>
            <span className="rcp-m-cover"><Art src={card.cover} alt={card.title} /></span>
            <div className="rcp-pane-by">{authorName(card)} · {categoryLabel(card.category) || "—"} · {card.model_title || modelTypeLabel(card.model_type)}</div>
            <div className="rcp-pane-stats rcp-mono"><span>♡ {compact(card.likes)}</span><span>↗ {compact(card.uses)}</span><span>▦ {compact(card.artworks)}</span></div>
            <div className="rcp-kicker">WHAT IT ADDS</div>
            <div className="rcp-kinds">{(card.kinds || []).map((k) => <span key={k.type} className="rcp-kind">{kindLabel(k)}</span>)}</div>
            {card.description ? <div className="rcp-page-desc">{card.description}</div> : null}
            {mf && <div className="rcp-peach rcp-pane-why">{mf.why}. {mf.fix}</div>}
            {note && !mf && <div className="rcp-peach rcp-pane-why">{note}</div>}
            <div className="rcp-kicker">MADE WITH IT</div>
            <div className="rcp-m-grid3">
              {art === null ? <span className="rcp-muted">Reading…</span> : art.length ? art.map((a) => (
                <span key={a.id || a.media_id} className={"rcp-made-cell" + (a.blur ? " blur" : "")}><Art src={a.thumb} /></span>
              )) : <span className="rcp-muted">No published artworks yet.</span>}
            </div>
          </>
        )}
      </div>
      <button type="button" className="rcp-m-foot rcp-m-foot-solid" disabled={!card || (!!mf && !inDock)} onClick={() => card && onUse(card)}>
        {inDock ? "✓ In Create · back" : "+ Use in Create"}
      </button>
      {menu && card && <RecipeSetsMenu sheet recipeId={String(card.id)} title={card.title} onClose={() => setMenu(false)} onChanged={(_, any) => setSaved(any)} />}
    </div>
  );
}
