import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ModelPicker from "../components/ModelPicker.jsx";
import { askPicker, isPickerOpen } from "../components/PickerHost.jsx";
import { apiGet } from "../api.js";
import { requestPrice } from "../gen/priceRequest.js";
import useAccountPrefs from "../hooks/useAccountPrefs.js";
import { recipeMeta, recipesApi } from "./recipesApi.js";
import {
  CATEGORIES, DESCRIPTION_MAX, DRAFT_PREFIX, SHOWCASE_MAX, SHOWCASE_MIN, TEST_LIMIT, TEST_RATIOS, TIERS,
  TITLE_MAX, TRIGGER_MAX, VISIBILITIES, capsOf, categoryLabel, draftId, draftsFromPrefs, fmt, kindMenu,
  loraWeightRange, modelTypeLabel, neededLine, newDraft, promptLimit, stillNeeded, testPricePayload,
  tierDims, toServerDraft,
} from "./recipesCore.js";
import { Art } from "./RecipesOverlay.jsx";

/* THE RECIPE CREATOR (H decision 8 / §C2, K decisions 4 and 5): three steps, PixAI's pattern.

   1 · Model & category   the model preset from the dock (or the picture), "change" opens
                          the LoRA/model picker filtered live; one of the seven categories.
   2 · Ingredients & test every kind PixAI's schema has, with the model's live limits and the
                          kinds it doesn't take dimmed with why; the test prompt, frame and
                          batch; ✦ Test through the cost badge; the showcase (3-8, the first
                          is the cover).
   3 · Name & cover       title, description, cover, the live market card, who can use it,
                          and Publish (one confirm, for Public).

   NOTHING WRITES ON OPEN (DECISIONS 2026-09-28). The draft is the account's own prefs
   (recipes.draft.<id>), saved as it changes and kept on close; PixAI is written to only
   by Publish (or Save changes on an edit). ✦ TEST IS NOT WIRED: a PixAI test run needs the
   recipe saved and moved to "test" first (writes on open) and a submit shape nobody has
   captured, so the button stops at its cost badge and says so (BUILD-w2-recipes.md).

   `phone` draws one step per screen (K decision 6). */
export default function RecipeCreator({ creator, onClose, onBack, phone }) {
  const prefs = useAccountPrefs();
  const [meta, setMeta] = useState(null);
  const [draft, setDraft] = useState(null);
  const [step, setStep] = useState(1);
  const [dirty, setDirty] = useState(false);
  const [cap, setCap] = useState(null);
  const [capErr, setCapErr] = useState("");
  const [picker, setPicker] = useState("");         // "model" | "lora:<index>" | ""
  const [kindOpen, setKindOpen] = useState(false);
  const [testMsg, setTestMsg] = useState("");
  const [price, setPrice] = useState(null);
  const [tests, setTests] = useState(0);
  const [frameOpen, setFrameOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(null);           // the recipe PixAI answered after a publish/save
  const [prefillNote, setPrefillNote] = useState("");
  const saveTimer = useRef(0);

  useEffect(() => { recipeMeta().then((m) => setMeta(m || {})); }, []);

  // ---- the draft: an existing one from prefs, or a new one (from the dock / a picture) ----
  useEffect(() => {
    if (draft || !prefs.ready) return;
    const c = creator || {};
    if (c.draftId) {
      const d = prefs.get(DRAFT_PREFIX + c.draftId, null);
      if (d) {
        setDraft(d);
        setStep(c.step || d.step || 1);
        return;
      }
    }
    const id = draftId(Date.now(), Math.random().toString(36).slice(2));
    const pre = c.prefill || {};
    if (pre.fromImage) {
      // K decision 4: ⁂ Make a recipe -- the picture's record prefills step 2. The category
      // is never guessed; step 2 opens with "Still needed: a category".
      const f = pre.fromImage;
      const d = newDraft({ id, now: Date.now(), from: {
        media_id: f.media_id, thumb: f.thumb, model_id: f.model_id, model_type: f.model_type,
        model_title: f.model_title, version_id: f.version_id, prompt: f.prompt, loras: f.loras } });
      setDraft(d); setStep(2); setDirty(true);
      if (f.unresolved) setPrefillNote(f.unresolved + " LoRA" + (f.unresolved > 1 ? "s" : "") + " from the picture couldn't be read");
      return;
    }
    setDraft(newDraft({ id, now: Date.now(), model: pre.model || {}, prompt: pre.prompt || "" }));
    setStep(1);
  }, [prefs.ready, creator, draft]); // eslint-disable-line react-hooks/exhaustive-deps

  // Save as it changes (debounced), once the user has changed something -- the prefs store
  // is the account's own; nothing here reaches PixAI.
  useEffect(() => {
    if (!draft || !dirty || done) return undefined;
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      prefs.set(DRAFT_PREFIX + draft.id, { ...draft, step, saved: Date.now() });
    }, 500);
    return () => clearTimeout(saveTimer.current);
  }, [draft, step, dirty, done]); // eslint-disable-line react-hooks/exhaustive-deps

  const change = useCallback((patch) => {
    setDirty(true);
    setDraft((d) => ({ ...d, ...(typeof patch === "function" ? patch(d) : patch) }));
  }, []);

  // ---- what the model takes (live) ------------------------------------------------------
  const modelKey = draft ? (draft.model.model_id || draft.model.model_type) : "";
  useEffect(() => {
    if (!draft || !modelKey) { setCap(null); return; }
    let live = true;
    setCap(null); setCapErr("");
    recipesApi.capability(draft.model.model_type, draft.model.model_id).then((d) => {
      if (!live) return;
      if (!d || d.error) { setCapErr((d && d.error) || "PixAI didn't say what this model takes"); setCap({ slots: [] }); return; }
      setCap(d);
    });
    return () => { live = false; };
  }, [modelKey]); // eslint-disable-line react-hooks/exhaustive-deps

  // A recipe already on PixAI: its test runs so far ("N / 100 tests").
  useEffect(() => {
    if (!draft || !draft.recipe_id) return;
    recipesApi.tasks(draft.recipe_id, "test").then((d) => { if (d && !d.error) setTests(d.total || 0); });
  }, [draft && draft.recipe_id]); // eslint-disable-line react-hooks/exhaustive-deps

  // ✦ Test's cost badge: the test shape priced with no card, so it can never read FREE.
  const testKey = draft ? JSON.stringify(testPricePayload(draft)) : "";
  useEffect(() => {
    if (!draft || step !== 2 || !draft.model.version_id) { setPrice(null); return undefined; }
    const ctl = typeof AbortController !== "undefined" ? new AbortController() : null;
    const t = setTimeout(() => {
      requestPrice({ ...testPricePayload(draft), no_card: true }, { signal: ctl ? ctl.signal : undefined })
        .then(({ response, failed }) => setPrice(failed ? { failed: true } : (response || null)));
    }, 400);
    return () => { clearTimeout(t); if (ctl) ctl.abort(); };
  }, [testKey, step]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- Escape: the innermost layer first --------------------------------------------------
  useEffect(() => {
    const onKey = (e) => {
      if (e.key !== "Escape" || isPickerOpen()) return;
      e.stopPropagation(); e.preventDefault();
      if (confirm) { setConfirm(false); return; }
      if (picker) { setPicker(""); return; }
      if (kindOpen || frameOpen) { setKindOpen(false); setFrameOpen(false); return; }
      onBack ? onBack() : onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [confirm, picker, kindOpen, frameOpen, onBack, onClose]);

  if (!draft) {
    return <Shell phone={phone} onClose={onClose} step={1}><div className="rcp-status">Opening the creator…</div></Shell>;
  }

  const need1 = stillNeeded(draft, 1);
  const need2 = stillNeeded(draft, 2);
  const need3 = stillNeeded(draft, 3);
  const needs = step === 1 ? need1 : step === 2 ? need2 : need3;
  const canNext = step === 1 ? !need1.length : step === 2 ? !need1.length && !need2.length : !need1.length && !need2.length && !need3.length;
  const wr = loraWeightRange(draft.model.model_type);
  const menu = kindMenu(draft, cap);
  const caps = capsOf(cap);
  const modelTitle = draft.model.title || modelTypeLabel(draft.model.model_type) || "this model";
  const otherPixaiDrafts = draftsFromPrefs(prefs.prefs).filter((d) => d.id !== draft.id && d.recipe_id && !d.editing);

  // ---- ingredients ------------------------------------------------------------------------
  const setIng = (i, patch) => change((d) => ({ ingredients: d.ingredients.map((g, j) => (j === i ? { ...g, ...patch } : g)) }));
  const moveIng = (i, by) => change((d) => {
    const a = [...d.ingredients]; const j = i + by;
    if (j < 0 || j >= a.length) return {};
    [a[i], a[j]] = [a[j], a[i]];
    return { ingredients: a };
  });
  const dropIng = (i) => change((d) => ({ ingredients: d.ingredients.filter((_, j) => j !== i) }));
  const addKind = (k) => {
    setKindOpen(false);
    if (k.off) return;
    const empty = {
      promptFragment: { type: "promptFragment", text: "" },
      lora: { type: "lora", loras: [] },
      baseImage: { type: "baseImage", image: null, strength: 0.6 },
      referenceImages: { type: "referenceImages", images: [] },
      contextImages: { type: "contextImages", images: [] },
      styleCode: { type: "styleCode", code: "" },
      referenceVideos: { type: "referenceVideos", videos: [] },
    }[k.type];
    const existing = draft.ingredients.findIndex((g) => g.type === k.type && k.type !== "promptFragment");
    if (existing >= 0) { if (k.type === "lora") setPicker("lora:" + existing); return; }
    change((d) => ({ ingredients: [...d.ingredients, empty] }));
    if (k.type === "lora") setPicker("lora:" + draft.ingredients.length);
  };
  const pickImage = (i, key, many) => {
    askPicker({ type: "image" }).then((m) => {
      if (!m || !m.media_id) return;
      change((d) => ({ ingredients: d.ingredients.map((g, j) => {
        if (j !== i) return g;
        if (!many) return { ...g, [key]: { media_id: String(m.media_id), thumb: m.thumb || "" } };
        const cur = g[key] || [];
        if (cur.some((x) => x.media_id === String(m.media_id))) return g;
        return { ...g, [key]: [...cur, { media_id: String(m.media_id), thumb: m.thumb || "" }] };
      }) }));
    });
  };
  const pickVideo = (i) => {
    askPicker({ type: "video" }).then((m) => {
      if (!m || !m.media_id) return;
      change((d) => ({ ingredients: d.ingredients.map((g, j) => (j !== i ? g
        : { ...g, videos: [...(g.videos || []), { media_id: String(m.media_id), thumb: m.thumb || "", duration: Number(m.duration) || 5 }] })) }));
    });
  };
  const loraToggle = (i) => (entry, on) => {
    change((d) => ({ ingredients: d.ingredients.map((g, j) => {
      if (j !== i) return g;
      const cur = g.loras || [];
      if (!on) return { ...g, loras: cur.filter((l) => l.model_id !== entry.model_id) };
      const row = { model_id: entry.model_id, title: entry.title, preview_url: entry.preview_url || "",
        version_id: entry.version_id || "", weight: entry.weight != null ? Number(entry.weight) : 0.7,
        trigger_words: String(entry.trigger_words || "").slice(0, TRIGGER_MAX), failed: !!entry.failed };
      const at = cur.findIndex((l) => l.model_id === entry.model_id);
      if (at >= 0) { const next = [...cur]; next[at] = { ...cur[at], ...row, weight: cur[at].weight }; return { ...g, loras: next }; }
      return { ...g, loras: [...cur, row] };
    }) }));
  };

  // ---- showcase ---------------------------------------------------------------------------
  const addShowcase = () => {
    if ((draft.showcase || []).length >= SHOWCASE_MAX) return;
    askPicker({ type: "image" }).then((m) => {
      if (!m || !m.media_id) return;
      change((d) => (d.showcase.some((s) => s.media_id === String(m.media_id)) ? {}
        : { showcase: [...d.showcase, { media_id: String(m.media_id), thumb: m.thumb || "" }] }));
    });
  };
  const dropShowcase = (mid) => change((d) => ({ showcase: d.showcase.filter((s) => s.media_id !== mid), cover: d.cover === mid ? "" : d.cover }));

  // ---- the model ----------------------------------------------------------------------------
  const pickModel = (row) => {
    setPicker("");
    apiGet("/api/model-version", { model_id: row.model_id }).then((v) => {
      const mt = (v && v.model_type) || row.model_type || "";
      const allowed = (meta && meta.model_types) || [];
      if (allowed.length && mt && !allowed.includes(mt)) { setErr(row.title + " doesn't take recipes (" + modelTypeLabel(mt) + ")."); return; }
      setErr("");
      change({ model: { model_id: String(row.model_id), model_type: mt, title: row.title || "", version_id: (v && v.version_id) || "" } });
    });
  };

  // ---- ✦ Test (not wired) --------------------------------------------------------------------
  const test = () => setTestMsg("Test runs aren't available yet: a PixAI test run has to save this recipe on PixAI first, and its request hasn't been captured, so the app won't send one. Pick showcase pictures from your history or the gallery.");

  // ---- publish --------------------------------------------------------------------------------
  const publish = () => {
    setBusy(true); setErr(""); setConfirm(false);
    const body = toServerDraft(draft);
    const road = draft.editing && draft.recipe_id
      ? recipesApi.update(draft.recipe_id, body, draft.version)
      : recipesApi.publish(body, draft.recipe_id);
    road.then((d) => {
      setBusy(false);
      if (!d || d.error) {
        if (d && d.recipe_id && d.recipe_id !== draft.recipe_id) change({ recipe_id: d.recipe_id });
        setErr((d && d.error) || "PixAI didn't answer");
        return;
      }
      const r = d.recipe || {};
      setDone(r);
      prefs.unset(DRAFT_PREFIX + draft.id);
    });
  };
  const publishClick = () => {
    if (!canNext || busy) return;
    if (draft.preset === "public" && !draft.editing) { setConfirm(true); return; }
    publish();
  };

  if (done) {
    const inReview = done.status === "test";
    return (
      <Shell phone={phone} onClose={onClose} step={3} title={draft.editing ? "Changes saved" : "Recipe published"}>
        <div className="rcp-done-card">
          <span className="rcp-done-art"><Art src={done.cover || (draft.showcase[0] && draft.showcase[0].thumb)} /></span>
          <div className="rcp-done-text">
            <b>{done.title || draft.title}</b>
            <span>{inReview ? "In review — PixAI reviews a recipe before it's listed; Mine shows it as “in review”."
              : done.status === "published" ? (draft.preset === "private" ? "Saved as private." : "Published.")
                : "PixAI says: " + (done.status || "saved")}</span>
          </div>
        </div>
        <div className="rcp-cfoot">
          <span className="rcp-flex" />
          {onBack && <button type="button" className="rcp-ghost" onClick={onBack}>Back to recipes</button>}
          <button type="button" className="rcp-primary" onClick={onClose}>Done</button>
        </div>
      </Shell>
    );
  }

  const stepName = ["Model & category", "Ingredients & test", "Name & cover"][step - 1];
  const t = draft.test || {};
  const dims = tierDims(t.ratio, t.tier);
  const plim = promptLimit(draft.model.model_type);
  const vis = VISIBILITIES;
  const primaryLabel = step < 3 ? "Next ›" : (draft.editing ? "Save changes" : draft.preset === "private" ? "Save as private" : "Publish");

  const body = (
    <>
      {step === 1 && (
        <div className="rcp-cbody">
          <div className="rcp-klabel"><span className="rcp-kicker">MODEL</span><span className="rcp-req">required</span></div>
          <div className={"rcp-modelcard" + (draft.model.model_id ? " on" : "")}>
            <span className="rcp-modelcard-ic" aria-hidden="true">⁂</span>
            <span className="rcp-modelcard-t"><b>{draft.model.title || (draft.model.model_type ? modelTypeLabel(draft.model.model_type) : "No model yet")}</b>
              <span>{modelTypeLabel(draft.model.model_type) || "—"}{creator && creator.prefill && creator.prefill.model && creator.prefill.model.model_id ? " · from the dock" : ""}</span></span>
            <button type="button" className="rcp-link" onClick={() => setPicker(picker === "model" ? "" : "model")}>{picker === "model" ? "close" : "change"}</button>
          </div>
          <div className="rcp-fine">"change" opens the model picker; only models that take recipes can be picked (read live).</div>
          {picker === "model" && (
            <div className="rcp-embed"><ModelPicker kind="base" market onPick={pickModel} style={{ height: phone ? "56dvh" : "340px" }} /></div>
          )}
          <div className="rcp-klabel"><span className="rcp-kicker">CATEGORY</span><span className="rcp-req">required</span><span className="rcp-flex" /><span className="rcp-fine">how people find it in the market</span></div>
          <div className="rcp-cats">
            {CATEGORIES.map(([k, label, hint]) => (
              <button key={k} type="button" className={"rcp-cat" + (draft.category === k ? " on" : "")} onClick={() => change({ category: k })} aria-pressed={draft.category === k}>
                <span className="rcp-radio" aria-hidden="true" />
                <span><b>{label}</b><span>{hint}</span></span>
              </button>
            ))}
          </div>
        </div>
      )}

      {step === 2 && (
        <div className="rcp-cbody">
          {need1.length > 0 && (
            <div className="rcp-peach rcp-fine">{neededLine(need1)} · <button type="button" className="rcp-link" onClick={() => setStep(1)}>pick it in step 1</button></div>
          )}
          {prefillNote && <div className="rcp-peach rcp-fine">{prefillNote}</div>}
          <div className="rcp-klabel"><span className="rcp-kicker">INGREDIENTS</span><span className="rcp-req">required</span></div>
          {capErr && <div className="rcp-peach rcp-fine">{capErr}</div>}
          {draft.ingredients.map((g, i) => (
            <Ingredient key={i} g={g} i={i} n={draft.ingredients.length} caps={caps} wr={wr} plim={plim}
              modelVersionId={draft.model.version_id}
              onSet={(p) => setIng(i, p)} onMove={(by) => moveIng(i, by)} onDrop={() => dropIng(i)}
              onPickImage={(key, many) => pickImage(i, key, many)} onPickVideo={() => pickVideo(i)}
              onLoraPicker={() => setPicker(picker === "lora:" + i ? "" : "lora:" + i)} pickerOpen={picker === "lora:" + i}
              loraPicker={picker === "lora:" + i ? (
                <div className="rcp-embed"><ModelPicker kind="lora" multi market baseType={draft.model.model_type}
                  selected={g.loras || []} onToggle={loraToggle(i)} style={{ height: phone ? "50dvh" : "300px" }} /></div>) : null} />
          ))}
          <div className="rcp-popwrap rcp-addwrap">
            <button type="button" className="rcp-dashed" onClick={() => setKindOpen((v) => !v)}>+ Add ingredient</button>
            {kindOpen && (
              <div className="rcp-kindmenu" role="menu">
                <div className="rcp-kicker">+ ADD INGREDIENT · {modelTitle.toUpperCase()} ALLOWS</div>
                {menu.map((k) => (
                  <button key={k.type} type="button" role="menuitem" className={"rcp-kindrow" + (k.off ? " off" : "")}
                    disabled={!!k.off} onClick={() => addKind(k)} title={k.off || ""}>
                    <span className="rcp-kindrow-t"><b>{k.name}</b><span>{k.off || k.src}</span></span>
                    <span className="rcp-mono">{k.text}</span>
                  </button>
                ))}
                <div className="rcp-fine">Kinds and limits are read per model. A kind the model doesn't take is listed dimmed with its reason.</div>
              </div>
            )}
          </div>

          <div className="rcp-klabel"><span className="rcp-kicker">TEST THIS RECIPE</span><span className="rcp-flex" /><span className="rcp-mono rcp-fine">{tests} / {TEST_LIMIT} tests</span></div>
          <div className="rcp-testbox">
            <textarea value={t.prompt || ""} maxLength={plim} rows={3} placeholder="A prompt to test it with"
              onChange={(e) => change((d) => ({ test: { ...d.test, prompt: e.target.value } }))} aria-label="Test prompt" />
            <div className="rcp-testmeta"><span>{creator && creator.prefill && creator.prefill.fromImage ? "the picture's own prompt" : "prompt from the dock"}</span><span className="rcp-mono">{fmt((t.prompt || "").length)} / {fmt(plim)}</span></div>
          </div>
          <div className="rcp-testrow">
            <div className="rcp-popwrap">
              <button type="button" className="rcp-framechip rcp-mono" onClick={() => setFrameOpen((v) => !v)}>{t.ratio} · {t.tier}</button>
              {frameOpen && (
                <div className="rcp-pop rcp-framepop" role="dialog" aria-label="Frame">
                  <div className="rcp-chipset">{TEST_RATIOS.map((r) => (
                    <button key={r} type="button" className={"rcp-pchip" + (t.ratio === r ? " on" : "")} onClick={() => change((d) => ({ test: { ...d.test, ratio: r } }))}>{r}</button>))}</div>
                  <div className="rcp-chipset">{Object.keys(TIERS).map((k) => (
                    <button key={k} type="button" className={"rcp-pchip" + (t.tier === k ? " on" : "")} onClick={() => change((d) => ({ test: { ...d.test, tier: k } }))}>{k}</button>))}</div>
                  <div className="rcp-mono rcp-fine">{dims.width} × {dims.height}</div>
                </div>
              )}
            </div>
            <span className="rcp-fine">the frame for the test</span>
            <span className="rcp-flex" />
            <span className="rcp-seg">
              {[4, 1].map((b) => (
                <button key={b} type="button" className={(Number(t.batch) === b ? "on" : "")} onClick={() => change((d) => ({ test: { ...d.test, batch: b } }))}>×{b}</button>
              ))}
            </span>
          </div>
          <div className="rcp-testcost">
            <span className="rcp-testcost-t">
              <span className="rcp-mono">{price && price.cost != null ? "≈ " + fmt(price.cost) + " credits" : price && price.failed ? "couldn't price it" : price && price.note ? price.note : "≈ — credits"}</span>
              <span className="rcp-mono rcp-fine">test run · batch ×{Number(t.batch) === 1 ? 1 : 4} · not Unlimited</span>
            </span>
            <button type="button" className="rcp-primary" onClick={test}>✦ Test</button>
          </div>
          {testMsg && <div className="rcp-peach rcp-fine">{testMsg}</div>}
          <div className="rcp-strip rcp-fine">Test results land here.</div>

          <div className="rcp-klabel"><span className="rcp-kicker">SHOWCASE</span><span className="rcp-req">required</span><span className="rcp-flex" />
            <button type="button" className="rcp-link rcp-fine" onClick={addShowcase}>from history or the gallery</button></div>
          <div className="rcp-showcase">
            {Array.from({ length: Math.max(SHOWCASE_MIN, Math.min(SHOWCASE_MAX, draft.showcase.length + 1)) }, (_, k) => {
              const s = draft.showcase[k];
              if (!s) return <button key={k} type="button" className="rcp-sc rcp-sc-empty" onClick={addShowcase} aria-label="Add a showcase picture" />;
              return (
                <span key={s.media_id} className={"rcp-sc" + (k === 0 ? " cover" : "")}>
                  <Art src={s.thumb || "/thumbs/" + s.media_id + ".jpg"} />
                  {k === 0 && <span className="rcp-sc-tag">cover</span>}
                  <button type="button" className="rcp-sc-x" onClick={() => dropShowcase(s.media_id)} aria-label="Remove">×</button>
                </span>
              );
            })}
            <span className="rcp-mono rcp-fine">{draft.showcase.length} / {SHOWCASE_MAX} · min {SHOWCASE_MIN}</span>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="rcp-cbody">
          <div className="rcp-namecover">
            <div className="rcp-namecol">
              <div className="rcp-klabel"><span className="rcp-kicker">TITLE</span><span className="rcp-req">required</span><span className="rcp-flex" /><span className="rcp-mono rcp-fine">{(draft.title || "").length} / {TITLE_MAX}</span></div>
              <input className="rcp-in" value={draft.title} maxLength={TITLE_MAX} onChange={(e) => change({ title: e.target.value })} aria-label="Title" />
              <div className="rcp-klabel"><span className="rcp-kicker">DESCRIPTION</span><span className="rcp-flex" /><span className="rcp-mono rcp-fine">{fmt((draft.description || "").length)} / {fmt(DESCRIPTION_MAX)}</span></div>
              <textarea className="rcp-in" rows={3} value={draft.description} maxLength={DESCRIPTION_MAX} placeholder="What it does, and when to reach for it"
                onChange={(e) => change({ description: e.target.value })} aria-label="Description" />
              <div className="rcp-kicker">COVER</div>
              <div className="rcp-covers">
                {draft.showcase.map((s, k) => {
                  const on = (draft.cover || (draft.showcase[0] && draft.showcase[0].media_id)) === s.media_id;
                  return (
                    <button key={s.media_id} type="button" className={"rcp-covpick" + (on ? " on" : "")} onClick={() => change({ cover: s.media_id })} aria-pressed={on} aria-label={"Cover " + (k + 1)}>
                      <Art src={s.thumb || "/thumbs/" + s.media_id + ".jpg"} />
                    </button>
                  );
                })}
                <button type="button" className="rcp-covpick rcp-covup" onClick={() => askPicker({ type: "image" }).then((m) => {
                  if (m && m.media_id) change((d) => ({ cover: String(m.media_id), coverThumb: m.thumb || "" }));
                })}>upload</button>
              </div>
            </div>
            <div className="rcp-previewcol">
              <div className="rcp-fine">In the market · cropped to 3:4</div>
              <div className="rcp-preview">
                <Art src={coverThumb(draft)} />
                {draft.category && <span className="rcp-badge rcp-badge-strong rcp-preview-badge">{categoryLabel(draft.category)}</span>}
                <span className="rcp-preview-foot"><b>{draft.title || "Untitled"}</b><span>you</span></span>
              </div>
            </div>
          </div>
          <div className="rcp-kicker">WHO CAN USE IT</div>
          <div className="rcp-vis">
            {vis.map((v) => (
              <button key={v.key} type="button" className={"rcp-visrow" + (draft.preset === v.key ? " on" : "") + (v.off ? " off" : "")}
                disabled={!!v.off} title={v.off || ""} onClick={() => change({ preset: v.key })} aria-pressed={draft.preset === v.key}>
                <span className="rcp-radio" aria-hidden="true" /><b>{v.name}</b><span>{v.off || v.desc}</span>
              </button>
            ))}
          </div>
          {!draft.editing && (
            <div className="rcp-fine rcp-onedraft">
              PixAI keeps one unfinished recipe per account: publishing starts a new one there, which replaces any unfinished recipe you began on pixai.art
              {otherPixaiDrafts.length ? " — and the one behind " + otherPixaiDrafts.map((d) => "“" + (d.title || "Untitled recipe") + "”").join(", ") + " in Mine" : ""}.
            </div>
          )}
        </div>
      )}
    </>
  );

  const next = () => {
    if (!canNext) return;
    if (step < 3) { setStep(step + 1); change({ step: step + 1 }); return; }
    publishClick();
  };
  const back = () => { if (step > 1) setStep(step - 1); else if (onBack) onBack(); else onClose(); };

  return (
    <Shell phone={phone} onClose={onClose} step={step} stepName={stepName} onBackTop={back}>
      {body}
      {err && <div className="rcp-peach rcp-fine rcp-cerr">{err}{draft.recipe_id && !draft.editing ? " (the recipe is on PixAI now; Publish again continues it)" : ""}</div>}
      <div className="rcp-cfoot">
        <span className="rcp-needed">{neededLine(needs)}</span>
        <button type="button" className="rcp-ghost" onClick={back}>{step === 1 ? "Cancel" : "Back"}</button>
        <button type="button" className="rcp-primary" disabled={!canNext || busy} onClick={next}>{busy ? "Saving…" : primaryLabel}</button>
      </div>
      {confirm && (
        <div className="rcp-confirm" role="dialog" aria-modal="true" aria-label="Publish to the market?">
          <div className="rcp-confirm-t">Publish to the market?</div>
          <div className="rcp-confirm-row">
            <div className="rcp-preview rcp-preview-sm">
              <Art src={coverThumb(draft)} />
              {draft.category && <span className="rcp-badge rcp-badge-strong rcp-preview-badge">{categoryLabel(draft.category)}</span>}
              <span className="rcp-preview-foot"><b>{draft.title}</b></span>
            </div>
            <div className="rcp-confirm-text">
              <b>What others will see</b>
              <span>The cover, title, description and showcase.</span>
              <span>What it adds: {kindsOf(draft)}.</span>
              <b>Not your prompt text or LoRA weights.</b>
            </div>
          </div>
          <div className="rcp-fine">PixAI reviews public recipes before they're listed; until then it reads "in review" in Mine. You can switch to Private later.</div>
          <div className="rcp-cfoot">
            <span className="rcp-flex" />
            <button type="button" className="rcp-ghost" onClick={() => setConfirm(false)}>Cancel</button>
            <button type="button" className="rcp-primary" onClick={publish}>Publish</button>
          </div>
        </div>
      )}
    </Shell>
  );
}

function coverThumb(d) {
  const id = d.cover || (d.showcase[0] && d.showcase[0].media_id) || "";
  const s = d.showcase.find((x) => x.media_id === id);
  if (s && s.thumb) return s.thumb;
  if (d.coverThumb && d.cover === id) return d.coverThumb;
  return id ? "/thumbs/" + id + ".jpg" : "";
}

function kindsOf(d) {
  const counts = {};
  for (const g of d.ingredients || []) {
    const n = g.type === "lora" ? (g.loras || []).length : (g.images || g.videos || [1]).length || 1;
    counts[g.type] = (counts[g.type] || 0) + n;
  }
  const label = { promptFragment: "Prompt", lora: "LoRA", baseImage: "Base image", referenceImages: "Reference", contextImages: "Context image", styleCode: "Style code", referenceVideos: "Video" };
  return Object.keys(counts).map((k) => label[k] + (["promptFragment", "styleCode", "baseImage"].includes(k) ? "" : " ×" + counts[k])).join(" · ") || "—";
}

function Shell({ phone, onClose, step, stepName, title, onBackTop, children }) {
  return (
    <div className={phone ? "rcp-creator rcp-creator-m" : "rcp-creator"} role="dialog" aria-modal="true" aria-label="Create a recipe" onClick={(e) => e.stopPropagation()}>
      <div className="rcp-chead">
        {phone && onBackTop && <button type="button" className="rcp-m-back" onClick={onBackTop} aria-label="Back">‹</button>}
        <div className="rcp-ctitle">{title || "Create a recipe"}</div>
        {!title && <span className="rcp-mono rcp-fine">step {step} / 3</span>}
        {stepName && !phone && <span className="rcp-cstep">{stepName}</span>}
        <button type="button" className="rcp-x" onClick={onClose} aria-label="Close">×</button>
      </div>
      {!title && <div className="rcp-bars">{[1, 2, 3].map((k) => <span key={k} className={k <= step ? "on" : ""} />)}</div>}
      {phone && stepName && <div className="rcp-cstep rcp-cstep-m">{stepName}</div>}
      {children}
    </div>
  );
}

const KIND_NAME = { promptFragment: "Prompt", lora: "LoRA", baseImage: "Base image", referenceImages: "Reference images", contextImages: "Context images", styleCode: "Style code", referenceVideos: "Reference videos" };

function Ingredient({ g, i, n, caps, wr, plim, modelVersionId, onSet, onMove, onDrop, onPickImage, onPickVideo, onLoraPicker, pickerOpen, loraPicker }) {
  const max = caps[g.type] || 0;
  const count = g.type === "lora" ? (g.loras || []).length : g.type === "referenceImages" || g.type === "contextImages" ? (g.images || []).length
    : g.type === "referenceVideos" ? (g.videos || []).length : 1;
  const [lookup, setLookup] = useState(null);
  const check = () => {
    const code = String(g.code || "").trim();
    if (!code) return;
    if (!modelVersionId) { setLookup({ error: "Pick a model first" }); return; }
    setLookup("busy");
    recipesApi.styleCode(code, modelVersionId).then((d) => setLookup(!d || d.error ? { error: (d && d.error) || "PixAI didn't answer" } : { recipe: d.recipe }));
  };
  return (
    <div className="rcp-ing">
      <div className="rcp-ing-head">
        <b>{KIND_NAME[g.type] || g.type}</b>
        {g.type !== "promptFragment" && g.type !== "styleCode" && g.type !== "baseImage" && <span className="rcp-mono rcp-fine">{count} / {max || "—"}</span>}
        <span className="rcp-flex" />
        <button type="button" className="rcp-iconbtn" onClick={() => onMove(-1)} disabled={i === 0} aria-label="Move up">↑</button>
        <button type="button" className="rcp-iconbtn" onClick={() => onMove(1)} disabled={i === n - 1} aria-label="Move down">↓</button>
        <button type="button" className="rcp-iconbtn" onClick={onDrop} aria-label="Remove">×</button>
      </div>
      {g.type === "promptFragment" && (
        <>
          <textarea className="rcp-in" rows={2} value={g.text} maxLength={plim} placeholder="Words this recipe adds to the prompt"
            onChange={(e) => onSet({ text: e.target.value })} aria-label="Prompt ingredient" />
          <div className="rcp-mono rcp-fine rcp-right">{fmt((g.text || "").length)} / {fmt(plim)}</div>
        </>
      )}
      {g.type === "lora" && (
        <>
          {(g.loras || []).map((l, k) => (
            <div key={l.model_id || l.version_id} className="rcp-lora">
              <span className="rcp-lora-thumb">{l.preview_url ? <img src={l.preview_url} alt="" /> : null}</span>
              <span className="rcp-lora-body">
                <span className="rcp-lora-top"><b>{l.title || l.version_id}</b>{l.failed && <span className="rcp-peach">couldn't read this LoRA</span>}<span className="rcp-flex" /><span className="rcp-mono rcp-mauve">{Number(l.weight).toFixed(2)}</span></span>
                <input type="range" min={wr.min} max={wr.max} step={0.05} value={Number(l.weight)} aria-label={"Weight of " + (l.title || "LoRA")}
                  onChange={(e) => onSet({ loras: g.loras.map((x, j) => (j === k ? { ...x, weight: Number(e.target.value) } : x)) })} />
                <span className="rcp-trig"><span className="rcp-fine">trigger words</span>
                  <input className="rcp-in rcp-mono" value={l.trigger_words || ""} maxLength={TRIGGER_MAX}
                    onChange={(e) => onSet({ loras: g.loras.map((x, j) => (j === k ? { ...x, trigger_words: e.target.value } : x)) })} aria-label="Trigger words" /></span>
              </span>
            </div>
          ))}
          <button type="button" className="rcp-link" onClick={onLoraPicker} disabled={max > 0 && count >= max}>
            {pickerOpen ? "Close the LoRA picker" : "+ Add LoRA · " + Math.max(0, max - count) + " slots left"}
          </button>
          {loraPicker}
        </>
      )}
      {g.type === "baseImage" && (
        <div className="rcp-imgrow">
          <button type="button" className="rcp-imgslot" onClick={() => onPickImage("image", false)}>
            {g.image ? <Art src={g.image.thumb || "/thumbs/" + g.image.media_id + ".jpg"} /> : <span>+ pick</span>}
          </button>
          <span className="rcp-lora-body">
            <span className="rcp-lora-top"><span className="rcp-fine">strength</span><span className="rcp-flex" /><span className="rcp-mono rcp-mauve">{Number(g.strength).toFixed(2)}</span></span>
            <input type="range" min={0} max={1} step={0.05} value={Number(g.strength)} onChange={(e) => onSet({ strength: Number(e.target.value) })} aria-label="Strength" />
            <span className="rcp-fine">history · the gallery · upload</span>
          </span>
        </div>
      )}
      {(g.type === "referenceImages" || g.type === "contextImages") && (
        <div className="rcp-imgrow">
          {(g.images || []).map((m, k) => (
            <span key={m.media_id} className="rcp-imgslot">
              <Art src={m.thumb || "/thumbs/" + m.media_id + ".jpg"} />
              <button type="button" className="rcp-sc-x" onClick={() => onSet({ images: g.images.filter((_, j) => j !== k) })} aria-label="Remove">×</button>
              {g.type === "contextImages" && (
                <select className="rcp-role" value={m.role || ""} aria-label="Role"
                  onChange={(e) => onSet({ images: g.images.map((x, j) => (j === k ? { ...x, role: e.target.value || undefined } : x)) })}>
                  <option value="">role</option><option value="character">character</option><option value="style">style</option>
                  <option value="pose">pose</option><option value="panel">panel</option>
                </select>
              )}
            </span>
          ))}
          {(!max || count < max) && <button type="button" className="rcp-imgslot rcp-imgadd" onClick={() => onPickImage("images", true)}>+</button>}
          <span className="rcp-fine">{g.type === "referenceImages" ? "history · the gallery · image Collections" : "history · the gallery · upload"}</span>
        </div>
      )}
      {g.type === "styleCode" && (
        <>
          <div className="rcp-code-row">
            <input className="rcp-in rcp-mono" value={g.code || ""} maxLength={100} placeholder="A legacy style code"
              onChange={(e) => { onSet({ code: e.target.value }); setLookup(null); }} aria-label="Style code" />
            <button type="button" className="rcp-ghost" onClick={check} disabled={lookup === "busy"}>Check</button>
          </div>
          {lookup && lookup !== "busy" && (
            <div className="rcp-fine">{lookup.recipe ? <>This code became <b>{lookup.recipe.title}</b>.</> : lookup.error ? <span className="rcp-peach">{lookup.error}</span> : "No recipe replaces this code."}</div>
          )}
        </>
      )}
      {g.type === "referenceVideos" && (
        <div className="rcp-imgrow">
          {(g.videos || []).map((v, k) => (
            <span key={v.media_id} className="rcp-imgslot">
              <Art src={v.thumb} />
              <button type="button" className="rcp-sc-x" onClick={() => onSet({ videos: g.videos.filter((_, j) => j !== k) })} aria-label="Remove">×</button>
            </span>
          ))}
          {(!max || count < max) && <button type="button" className="rcp-imgslot rcp-imgadd" onClick={onPickVideo}>+</button>}
        </div>
      )}
    </div>
  );
}
