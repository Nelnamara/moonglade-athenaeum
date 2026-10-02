import React, { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import useIsMobile from "../hooks/useIsMobile.js";
import { recipesApi } from "./recipesApi.js";
import { bindDock, cacheCards, cachedCard, getSnapshot, openRecipes, subscribe } from "./recipesStore.js";
import { MAX_RECIPES, misfitOf, removeRecipe } from "./recipesCore.js";
import "../styles/recipes.css";

/* The dock's recipe row (H decision 3; H §A slab 1, §E phone; T2a/T2b chip states).

   THE CONTRACT lane w2-gen renders from the dock, exactly:
     <RecipeRow recipes={[{id, title, cover}]} onChange={(next) => …} held={bool}
                loraCount={n} modelType={…} />
   `next` is the whole new list. Its entries carry {id, title, cover} plus what the row
   needs to check fit without a call (model_type, model_title, prompt_len, usability,
   kinds) -- a dock that stores the entries as given keeps those; one that keeps only the
   three fields still works, and the row re-reads the rest (GET /api/recipes/batch).

   What it draws: the header ("RECIPES", "N / 10"), the chips (22 px thumb, name, ×), a
   dashed "+ Browse", and one line under them -- "A recipe beside a LoRA can fight it · you
   can still send" (warn, not refuse) or, when `held`, "Held · not sent with context
   images" with the chips at .38. A chip that doesn't fit turns peach with "!" and its
   reason on hover (T2a), from the model check (no call) or PixAI's own refusal on the
   dock's last price answer. Generate's refusal is the dock's (recipesCore.recipeGate). */
export default function RecipeRow({ recipes, onChange, held, loraCount, modelType }) {
  const mobile = useIsMobile();
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const list = useMemo(() => (Array.isArray(recipes) ? recipes : []), [recipes]);
  const [, setHydrated] = useState(0);

  // Publish the binding every render: the picker, the palette and the phone add through it.
  useEffect(() => {
    bindDock({ recipes: list, onChange, held: !!held, loraCount: Number(loraCount) || 0, modelType: modelType || "" });
  });
  // A row that is gone (the dock unmounted it) can take no more adds: the picker says so.
  useEffect(() => () => bindDock({ onChange: null }), []);

  // Chips restored with only {id, title, cover} (a reload) re-read their cards once.
  useEffect(() => {
    const missing = list.filter((r) => r && r.id && r.model_type === undefined && !cachedCard(r.id)).map((r) => String(r.id));
    if (!missing.length) return undefined;
    let live = true;
    recipesApi.batch(missing.slice(0, 20)).then((d) => {
      if (!live || !d || d.error) return;
      cacheCards(d.items || []);
      setHydrated((n) => n + 1);
    });
    return () => { live = false; };
  }, [list]);

  const request = snap.request || {};
  const payload = request.payload || null;
  const refusals = useMemo(() => {
    const out = {};
    const re = request.price && request.price.recipe_error;
    if (re) for (const id of re.recipe_ids || []) out[String(id)] = re;
    return out;
  }, [request.price]);
  const ctx = {
    modelType: modelType || "", modelTitle: (snap.dock && snap.dock.modelTitle) || "",
    promptLen: payload && typeof payload.prompt === "string" ? payload.prompt.length : null,
    recipes: list, refusals,
  };
  const chips = list.map((r) => {
    const card = { ...(cachedCard(r.id) || {}), ...r };
    return { card, misfit: held ? null : misfitOf(card, ctx) };
  });
  const remove = (id) => onChange && onChange(removeRecipe(list, id));
  const browse = () => openRecipes({ view: "picker", phone: mobile, phoneScreen: "sheet" });
  const openOne = (id) => openRecipes({ view: "picker", selectedId: String(id), phone: mobile, phoneScreen: mobile ? "recipe" : "sheet", pageId: mobile ? String(id) : "" });
  const warn = !held && list.length > 0 && (Number(loraCount) || 0) > 0;

  if (mobile) {
    return (
      <div className="rcp-row rcp-row-m">
        <div className={"rcp-row-m-body" + (held ? " held" : "")}>
          <div className="rcp-row-m-head">
            <span>Recipes · {list.length} / {MAX_RECIPES}</span>
            <button type="button" className="rcp-row-m-browse" onClick={browse}>browse ›</button>
          </div>
          <div className="rcp-row-m-thumbs">
            {chips.map(({ card, misfit }) => (
              <button key={card.id} type="button" className={"rcp-row-m-thumb" + (misfit ? " misfit" : "")}
                title={card.title + (misfit ? " — " + misfit.why : "")} onClick={() => openOne(card.id)}>
                {card.cover ? <img src={card.cover} alt="" /> : null}
                {misfit ? <span className="rcp-row-m-bang">!</span> : null}
              </button>
            ))}
            {list.length < MAX_RECIPES && (
              <button type="button" className="rcp-row-m-add" onClick={browse} aria-label="Add a recipe">+</button>
            )}
          </div>
        </div>
        {held ? <div className="rcp-row-note">Held · not sent with context images</div>
          : warn ? <div className="rcp-row-warn">A recipe beside a LoRA can fight it · you can still send</div> : null}
      </div>
    );
  }

  return (
    <div className="rcp-row">
      <div className="rcp-row-head">
        <span className="rcp-kicker">RECIPES</span>
        <span className="rcp-row-count">{list.length} / {MAX_RECIPES}</span>
      </div>
      <div className={"rcp-row-chips" + (held ? " held" : "")}>
        {chips.map(({ card, misfit }) => (
          <span key={card.id} className={"rcp-chip" + (misfit ? " misfit" : "")}>
            <button type="button" className="rcp-chip-open" onClick={() => openOne(card.id)}
              aria-label={"Open " + (card.title || "recipe")}>
              <span className="rcp-chip-thumb">{card.cover ? <img src={card.cover} alt="" /> : null}</span>
              <span className="rcp-chip-name">{card.title || "Recipe"}</span>
            </button>
            {misfit ? <span className="rcp-chip-bang" aria-hidden="true">!</span> : null}
            <button type="button" className="rcp-chip-x" onClick={() => remove(card.id)}
              aria-label={"Remove " + (card.title || "recipe")}>×</button>
            {misfit ? (
              <span className="rcp-chip-tip" role="tooltip">
                “{card.title}” {misfit.why}. <b>{misfit.fix}</b>
              </span>
            ) : null}
          </span>
        ))}
        {list.length < MAX_RECIPES && (
          <button type="button" className="rcp-row-browse" onClick={browse}>+ Browse</button>
        )}
      </div>
      {held ? <div className="rcp-row-note">Held · not sent with context images</div>
        : warn ? <div className="rcp-row-warn">A recipe beside a LoRA can fight it · you can still send</div> : null}
    </div>
  );
}
