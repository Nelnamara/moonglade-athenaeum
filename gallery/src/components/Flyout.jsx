import React, { useEffect, useState } from "react";
import { fetchPresets } from "../api.js";
import { ASPECT_CHOICES, aspectIn, withAspect, parseAspect } from "../curation/aspectCore.js";

/* The Advanced flyout -- ANCHORED to the search slab (rendered inside .mgl-search,
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
    // Always reset batch: saved views never carry a batch drill-down, so loading ANY view
    // must clear an active one -- applyAdvanced only touches keys present in the patch, so
    // omitting batch here would leave a stale Details "View batch" filter stuck on.
    batch: "",
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

export default function Flyout({ boot, current, queryText = "", onApply, onClose, onPrintCollection,
    onSaveView, onDeleteView, buildViewQuery, manualSort }) {
  const [d, setD] = useState(current);          // draft
  /* The Aspect field (Session N7) is not a filter of its own: it is the search text's `ar:`
     token, read out of the field when the flyout opens and written back on Apply, so what the
     field shows and what the grid filters by cannot disagree. `aspect0` is what it held when
     opened -- the text is only rewritten when the choice actually changed, so Apply never
     re-submits a half-typed search for nothing. */
  const aspect0 = aspectIn(queryText);
  const [aspect, setAspect] = useState(aspect0);
  const [customAsp, setCustomAsp] = useState(!!aspect0 && !ASPECT_CHOICES.some((c) => c.value === aspect0));
  const aspectOk = !aspect || parseAspect(aspect).ok;
  const apply = () => {
    if (!aspectOk) return;
    onApply(aspect === aspect0 ? d : { ...d, q: withAspect(queryText, aspect) });
  };
  const [presets, setPresets] = useState([]);
  const [saveName, setSaveName] = useState("");
  const [saveMsg, setSaveMsg] = useState("");
  useEffect(() => { setD(current); }, [current]);
  useEffect(() => { fetchPresets().then(setPresets); }, []);
  const set = (k) => (e) =>
    setD({ ...d, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });

  // Saved-views WRITE: save the current APPLIED view (App builds the query — this UI just
  // names it) / delete one, then refetch the account-scoped list. Read side unchanged.
  const refreshPresets = () => fetchPresets().then(setPresets);
  const saveView = async () => {
    const name = saveName.trim();
    if (!name || !onSaveView || !buildViewQuery) return;
    if (presets.some((p) => p.name === name) &&
        !window.confirm('A saved view named "' + name + '" exists — overwrite it?')) return;
    // Serialize the DRAFT the flyout shows (d), not App's committed adv -- see App's actions.
    const res = await onSaveView(name, "?" + buildViewQuery(d, "library"))
      .catch(() => ({ error: "Network error — not saved." }));
    if (res && res.error) { setSaveMsg(res.error); return; }
    setSaveName(""); setSaveMsg(""); refreshPresets();
  };
  const exportHref = buildViewQuery ? "/export-csv?" + buildViewQuery(d, "export") : null;
  const deleteView = async (name) => {
    if (!onDeleteView) return;
    await onDeleteView(name).catch(() => {});
    refreshPresets();
  };

  return (
    <div className="fly" role="dialog" aria-label="Advanced search">
      <div className="flyhd">ADVANCED SEARCH</div>
      <div className="flylegend">
        <p>these already work — nothing in the app tells you so</p>
        <div>
          <code>night*</code> <span>wildcard</span> · <code>model:tsubaki</code>{" "}
          <span>by model</span> · <code>2038314167804392533</code> <span>a task or media id</span>
        </div>
        {/* Session N3: the personal layer's operators. A leading - negates any of them. */}
        <div>
          <code>keeper</code> · <code>reject</code> <span>your mark</span> ·{" "}
          <code>tag:pose-study</code> <span>your tag</span> · <code>note:&quot;hands&quot;</code>{" "}
          <span>your note</span> · <code>★4+</code> <span>stars</span> · <code>-reject</code>{" "}
          <span>leave one out</span>
        </div>
        {/* Session N6/N7: the shape and kind operators. */}
        <div>
          <code>ar:tall</code> · <code>ar:wide</code> · <code>ar:square</code> <span>shape</span> ·{" "}
          <code>ar:3:2</code> <span>a ratio, within 3%</span> · <code>ar:&gt;2</code>{" "}
          <span>wider than 2:1</span> · <code>type:loom</code> <span>image, video or loom</span>
        </div>
      </div>
      <div className="flygrid">
        <div className="flyrow"><label>Sort</label>
          <select value={d.sort} onChange={set("sort")}>
            {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            {/* Session P (P6): a hand-picked collection's own order -- offered only while the
                gallery is showing a hand-picked collection (a smart one's membership is live). */}
            {manualSort || d.sort === "manual" ? <option value="manual">Manual order</option> : null}
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
        <div className="flyrow"><label>Aspect</label>
          <span className="flyaspect">
            <select value={customAsp ? "__custom" : aspect} aria-label="Aspect"
              onChange={(e) => {
                const v = e.target.value;
                if (v === "__custom") { setCustomAsp(true); if (ASPECT_CHOICES.some((c) => c.value === aspect)) setAspect(""); }
                else { setCustomAsp(false); setAspect(v); }
              }}>
              <option value="">Any shape</option>
              {ASPECT_CHOICES.map((c) => <option key={c.value} value={c.value}>{c.label} ({c.hint})</option>)}
              <option value="__custom">A ratio or a bound…</option>
            </select>
            {customAsp && (
              <input value={aspect} onChange={(e) => setAspect(e.target.value.replace(/\s+/g, ""))}
                placeholder="3:2, >2, <0.5" aria-label="A ratio (W:H) or a bound (>N, <N)"
                aria-invalid={!aspectOk} />
            )}
          </span>
          {!aspectOk && <div className="flyaspect-err" role="alert">ar: takes W:H, &gt;N or &lt;N here.</div>}
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
        <div className="flyrow full flysaved">
          <label>Saved views</label>
          <div className="flysaved-body">
            {presets.length === 0 ? (
              <div className="flysaved-empty">No saved views yet.</div>
            ) : (
              <div className="flysaved-list">
                {presets.map((p) => (
                  <span className="flysaved-chip" key={p.name}>
                    <button type="button" className="flysaved-load" title="Load this view"
                      onClick={() => p.query && onApply(parsePresetQuery(p.query))}>{p.name}</button>
                    <button type="button" className="flysaved-del" title="Delete this saved view"
                      onClick={() => deleteView(p.name)}>×</button>
                  </span>
                ))}
              </div>
            )}
            <div className="flysaved-save">
              <input value={saveName} placeholder="Save the current view as…"
                onChange={(e) => { setSaveName(e.target.value); setSaveMsg(""); }}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); saveView(); } }} />
              <button type="button" className="card" disabled={!saveName.trim()} onClick={saveView}>Save</button>
            </div>
            {saveMsg && <div className="flysaved-msg">⚠ {saveMsg}</div>}
          </div>
        </div>
      </div>
      <div className="flyft">
        <button
          className="card"
          onClick={() =>
            onApply({ sort: "newest", ratingMin: 0, model: "", lora: "",
              dateFrom: "", dateTo: "", source: "", tag: "", publishedOnly: false,
              ...(aspect0 ? { q: withAspect(queryText, "") } : {}) })
          }
        >
          Clear
        </button>
        {onPrintCollection && (
          <button className="card" onClick={onPrintCollection}
            title="Print a contact sheet of the current view">
            ⎙ Contact sheet
          </button>
        )}
        {exportHref && (
          <a className="card" href={exportHref} download
            title="Download exactly this filtered view as CSV (the whole-catalog dump stays in the Control Panel)">
            ⬇ Export view
          </a>
        )}
        <span className="sp" />
        <button className="card apply" disabled={!aspectOk} onClick={apply}>Apply</button>
        <button className="card" onClick={onClose} title="Esc">✕</button>
      </div>
    </div>
  );
}
