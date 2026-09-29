import React from "react";

/* RecipeRow -- STUB. Lane w2-recipes replaces this file with the real recipe row (the chips'
   contents, the "+ Browse" picker, the misfit checks). Lane w2-gen (the Generate dock) only
   owns the props contract and the dock's state it reads and writes:

     <RecipeRow recipes={[{id, title, cover}]} onChange={(next) => ...} held={bool}
                loraCount={n} modelType={"MMDIT26B_MODEL" | ...} />

   recipes    the dock's recipe row, in order (useGenerate's `s.recipes`, persisted per account)
   onChange   replace the row (the dock sends the ids as `recipeIds` on the LoRA side only)
   held       the Context side holds recipes: dim the row, say "Held · not sent with context
              images" (Session H decision 1)
   loraCount  LoRAs on the LoRA side, for decision 3's "A recipe beside a LoRA can fight it"
   modelType  the applied version's architecture

   Until the recipes lane lands this draws the section and lets a chip be removed; it adds
   nothing and calls no recipe route. */
export default function RecipeRow({ recipes, onChange, held, loraCount, modelType }) {
  const list = Array.isArray(recipes) ? recipes : [];
  void modelType;
  return (
    <div className="rcp-row" data-stub="w2-recipes">
      <div className="rcp-head">
        <span className="rcp-lbl">RECIPES</span>
        <span className="sp" />
        <span className="rcp-count">{list.length} / 10</span>
      </div>
      <div className={"rcp-chips" + (held ? " held" : "")}>
        {list.map((r) => (
          <span className="rcp-chip" key={r.id}>
            {r.cover ? <img src={r.cover} alt="" /> : <i className="rcp-ph" />}
            <span className="rcp-name">{r.title || r.id}</span>
            <button type="button" className="rcp-x" aria-label={"Remove " + (r.title || r.id)}
              onClick={() => onChange(list.filter((x) => x.id !== r.id))}>×</button>
          </span>
        ))}
        <button type="button" className="rcp-browse" disabled
          title="The recipe picker arrives with the recipes build">+ Browse</button>
      </div>
      {held ? <div className="rcp-note">Held · not sent with context images</div>
        : list.length && loraCount ? <div className="rcp-note">A recipe beside a LoRA can fight it · you can still send</div>
          : null}
    </div>
  );
}
