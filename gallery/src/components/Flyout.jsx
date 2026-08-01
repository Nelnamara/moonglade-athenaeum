import React, { useEffect, useState } from "react";
import { fetchPresets } from "../api.js";

/* The Advanced flyout -- ANCHORED to the search slab (rendered inside .srch),
   never placed: the locked behavior from the design pass. Drafts locally,
   commits on Apply. Saved views are the server-side, account-scoped store the
   classic gallery writes; each preset holds the classic query string, parsed
   here back into pilot state -- one store, both surfaces. */

const SORTS = [
  ["newest", "Newest first"], ["oldest", "Oldest first"],
  ["rating_desc", "Rating ↓"], ["rating_asc", "Rating ↑"],
  ["model", "Model name"], ["pixels", "Resolution ↓"],
  ["aspect", "Aspect (wide→tall)"], ["aes_desc", "Aesthetic score ↓"],
  ["aes_asc", "Aesthetic score ↑"], ["likes", "Most liked"],
  ["width", "Width ↓"], ["height", "Height ↓"],
];

const SOURCES = [
  ["", "All"], ["online", "PixAI history"], ["api", "Generated"],
  ["local", "Imported"], ["deleted", "Deleted on PixAI"],
];

export function parsePresetQuery(qs) {
  const p = new URLSearchParams(qs.startsWith("?") ? qs.slice(1) : qs);
  const g = (k) => (p.get(k) || "").trim();
  return {
    q: g("q"), media: ["image", "video"].includes(g("media")) ? g("media") : "",
    shelf: g("collection"), sort: g("sort") || "newest",
    ratingMin: Number(g("rating_min")) || 0, model: g("model"), lora: g("lora"),
    dateFrom: g("from"), dateTo: g("to"), source: g("source"), tag: g("tag"),
    publishedOnly: g("published") === "1",
    perPage: [50, 100, 200].includes(Number(g("per_page"))) ? Number(g("per_page")) : null,
  };
}

function MonthPicker({ value, onChange, years, label }) {
  const [y, m] = (value || "").split("-");
  const set = (ny, nm) => onChange(ny ? ny + (nm ? "-" + nm : "") : "");
  return (
    <div className="flyrow">
      <label>{label}</label>
      <span className="flydate">
        <select value={y || ""} onChange={(e) => set(e.target.value, m || "")}>
          <option value="">Any year</option>
          {years.map((yy) => <option key={yy} value={yy}>{yy}</option>)}
        </select>
        <select value={m || ""} onChange={(e) => set(y || "", e.target.value)} disabled={!y}>
          <option value="">All</option>
          {Array.from({ length: 12 }, (_, i) => String(i + 1).padStart(2, "0")).map((mm) => (
            <option key={mm} value={mm}>{mm}</option>
          ))}
        </select>
      </span>
    </div>
  );
}

export default function Flyout({ boot, current, onApply, onClose }) {
  const [d, setD] = useState(current);          // draft
  const [presets, setPresets] = useState([]);
  useEffect(() => { setD(current); }, [current]);
  useEffect(() => { fetchPresets().then(setPresets); }, []);
  const set = (k) => (e) =>
    setD({ ...d, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  return (
    <div className="fly" role="dialog" aria-label="Advanced search">
      <div className="flyhd">ADVANCED SEARCH</div>
      <div className="flylegend">
        <p>these already work — nothing in the app tells you so</p>
        <div>
          <code>night*</code> <span>wildcard</span> · <code>model:tsubaki</code>{" "}
          <span>by model</span> · <code>2038314167804392533</code> <span>a task or media id</span>
        </div>
      </div>
      <div className="flygrid">
        <div className="flyrow"><label>Sort</label>
          <select value={d.sort} onChange={set("sort")}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <div className="flyrow"><label>Min rating</label>
          <select value={d.ratingMin} onChange={(e) => setD({ ...d, ratingMin: Number(e.target.value) })}>
            <option value={0}>Any</option>
            {[1, 2, 3, 4, 5].map((r) => (
              <option key={r} value={r}>{"★".repeat(r)}+</option>
            ))}
          </select>
        </div>
        <div className="flyrow"><label>Model</label>
          <input value={d.model} onChange={set("model")} list="fly-models"
            placeholder="All models — type to search" />
          <datalist id="fly-models">
            {(boot.models || []).map((m) => <option key={m} value={m} />)}
          </datalist>
        </div>
        <div className="flyrow"><label>LoRA</label>
          <input value={d.lora} onChange={set("lora")} placeholder="lora name…" />
        </div>
        <MonthPicker label="From" value={d.dateFrom} years={boot.years || []}
          onChange={(v) => setD({ ...d, dateFrom: v })} />
        <MonthPicker label="To" value={d.dateTo} years={boot.years || []}
          onChange={(v) => setD({ ...d, dateTo: v })} />
        <div className="flyrow"><label>Source</label>
          <select value={d.source} onChange={set("source")}>
            {SOURCES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </div>
        <div className="flyrow"><label>Tag / contest</label>
          <input value={d.tag} onChange={set("tag")} placeholder="published tag…" />
        </div>
        <div className="flyrow full">
          <label className="flycb">
            <input type="checkbox" checked={d.publishedOnly} onChange={set("publishedOnly")} />
            Published only
          </label>
        </div>
        <div className="flyrow"><label>Saved views</label>
          <select
            value=""
            onChange={(e) => {
              const p = presets.find((x) => x.name === e.target.value);
              if (p && p.query) onApply(parsePresetQuery(p.query));
            }}
          >
            <option value="">{presets.length ? "Saved views…" : "No saved views yet"}</option>
            {presets.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
        </div>
      </div>
      <div className="flyft">
        <button
          className="card"
          onClick={() =>
            onApply({ sort: "newest", ratingMin: 0, model: "", lora: "",
              dateFrom: "", dateTo: "", source: "", tag: "", publishedOnly: false })
          }
        >
          Clear
        </button>
        <span className="sp" />
        <button className="card apply" onClick={() => onApply(d)}>Apply</button>
        <button className="card" onClick={onClose} title="Esc">✕</button>
      </div>
    </div>
  );
}
