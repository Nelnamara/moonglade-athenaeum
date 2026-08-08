import { useCallback, useEffect, useRef, useState } from "react";

/* useImageDetails -- DetailsView.jsx's fetch/state/derivation/action logic,
   mechanically lifted out (2026-08-03) into its own hook so a new mobile
   surface (ImageDetailsMobile.jsx) can consume the EXACT same /api/next/detail
   data shape, rating mirror, engagement fetch, copy/suggest/save/delete
   actions and Upscale mount -- never a second, drifting copy of any of it.
   Matches the useMyArt.js/useHealth.js/useImport.js/useContests.js precedent
   this session already set 4 times (see those files' own header comments):
   DetailsView.jsx -- the ONE place this state has ever lived -- is refactored
   to CONSUME this hook rather than left holding a second copy, and
   ImageDetailsMobile.jsx consumes the exact same hook, never a
   reimplementation of its own.

   A byte-for-byte lift of DetailsView.jsx's own state/effects/handlers, NOT a
   rewrite -- with two small, deliberate corrections made while moving it,
   both about the shared <mg-upscale-panel> mount (see inline comments below):

   1. THE HOST DIV BUG: DetailsView.jsx rendered `<div ref={upHost} />` only
      when `upscaleOpen` was true (`{!focusMode && upscaleOpen && <div
      ref={upHost} />}`), but the mount effect that creates the
      <mg-upscale-panel> element runs exactly ONCE, right after the FIRST
      commit -- which happens while upscaleOpen is still false, so the div
      doesn't exist yet, upHost.current is null, and the effect bails for
      good. Every later click just flips React state; the custom element is
      never created and the panel never opens. Lightbox.jsx (the other
      consumer of the identical mount pattern) never had this bug -- its own
      `<div ref={upHost} .../>` is unconditional, and the custom element's own
      CSS (`mg-upscale-panel{display:none}` / `[open]{display:block}`) is
      what actually hides it, not conditional React mounting. This hook
      follows Lightbox's proven shape: callers render the host div
      unconditionally.
   2. STALE-CONTENT-ON-NAVIGATE: Lightbox explicitly closes the upscale panel
      whenever the pictured media_id changes (`useEffect(() => closeUpscale(),
      [mid])` + an unmount cleanup) so the flyout never outlives the picture
      it was opened for. DetailsView.jsx's reset effect flipped `upscaleOpen`
      back to false on navigate but never told the actual custom element to
      close, so Prev/Next while Upscale was open left it visibly open, still
      bound to the OLD image, while the toggle button's own highlight had
      already reset. Folded in below to match Lightbox's real behavior. */

export default function useImageDetails({ mediaId, advParams, onRate, onDeleted }) {
  const [state, setState] = useState({ loading: true, data: null, error: "" });
  const [promptText, setPromptText] = useState("");
  const [copied, setCopied] = useState("");
  const [views, setViews] = useState(null);
  const [suggestions, setSuggestions] = useState(null); // null=not asked, []=asked, [..]=results
  const [suggestBusy, setSuggestBusy] = useState(false);
  const [suggestErr, setSuggestErr] = useState("");
  const [editingPrompt, setEditingPrompt] = useState(false);
  const [saveStatus, setSaveStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [upscaleOpen, setUpscaleOpen] = useState(false);
  const upHost = useRef(null);
  const upEl = useRef(null);
  const seq = useRef(0);

  useEffect(() => {
    if (!mediaId) return;
    const mine = ++seq.current;
    setState({ loading: true, data: null, error: "" });
    setEditingPrompt(false); setSaveStatus(""); setCopied("");
    setViews(null); setSuggestions(null); setSuggestErr(""); setUpscaleOpen(false);
    // the panel must never outlive the picture it was opened for -- see
    // header comment, correction 2 (Lightbox.jsx's own closeUpscale-on-[mid]).
    if (upEl.current) upEl.current.close();
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(advParams || {})) if (v) qs.set(k, v);
    fetch("/api/next/detail/" + encodeURIComponent(mediaId) + "?" + qs.toString())
      .then((r) => r.json())
      .then((d) => {
        if (mine !== seq.current) return;
        if (d.error) { setState({ loading: false, data: null, error: d.error }); return; }
        setState({ loading: false, data: d, error: "" });
        setPromptText(d.row.prompt_full || d.row.prompt_preview || "");
      })
      .catch(() => { if (mine === seq.current) setState({ loading: false, data: null, error: "Network error." }); });
  }, [mediaId, advParams]);

  // closes the panel on unmount too (leaving Details entirely) -- Lightbox's
  // identical safeguard.
  useEffect(() => () => { if (upEl.current) upEl.current.close(); }, []);

  const row = state.data && state.data.row;

  /* Stars' visual state and the "N / 5" label both read row.rating, which
     lives in THIS hook's own fetched copy -- onRate (App.jsx's/AppMobile.jsx's
     rate()) only updates the grid's items array, so a click here posted
     correctly but the UI kept showing the stale pre-click value until this
     optimistic mirror was added. */
  const handleRate = (mid, value) => {
    setState((old) => (old.data ? { ...old, data: { ...old.data, row: { ...old.data.row, rating: value } } } : old));
    onRate(mid, value);
  };

  // live view count, published rows only -- classic's DOMContentLoaded engagement fetch
  useEffect(() => {
    if (!row || row.is_published !== "1" || !row.artwork_id) return;
    fetch("/api/artwork-views?id=" + encodeURIComponent(row.artwork_id))
      .then((r) => r.json())
      .then((d) => setViews(d && d.views != null ? d.views : null))
      .catch(() => setViews(null));
  }, [row]);

  // Mount once the real host div exists -- see header comment, correction 1.
  // Correction 1 fixed the div's own render condition (unconditional on
  // upscaleOpen), but ImageDetailsMobile.jsx (unlike Lightbox.jsx) still has
  // an early-return for state.loading/error before its main JSX -- so on a
  // real network fetch (never on a stubbed/instant one, which is exactly why
  // this survived one review pass) this effect's FIRST run lands while the
  // component is still rendering the loading branch, upHost.current is null,
  // the effect bails, and a `[]` deps array meant it never got a second try.
  // Depending on `row` re-fires once the loaded branch actually paints; the
  // firstChild guard still makes every run after the first a no-op.
  useEffect(() => {
    if (!upHost.current || upHost.current.firstChild) return;
    if (!window.customElements || !window.customElements.get("mg-upscale-panel")) return;
    const el = document.createElement("mg-upscale-panel");
    el.setAttribute("inline", "");
    upHost.current.appendChild(el);
    upEl.current = el;
  }, [row]);
  const toggleUpscale = () => {
    const willOpen = !upscaleOpen;
    setUpscaleOpen(willOpen);
    if (!upEl.current) return;
    if (willOpen) upEl.current.open(mediaId); else upEl.current.close();
  };

  const copy = useCallback((text, tag) => {
    navigator.clipboard.writeText(text || "").then(() => {
      setCopied(tag);
      setTimeout(() => setCopied((c) => (c === tag ? "" : c)), 1200);
    });
  }, []);

  const runSuggest = async () => {
    setSuggestBusy(true); setSuggestErr("");
    try {
      const d = await fetch("/api/suggest-prompt?media_id=" + encodeURIComponent(mediaId)).then((r) => r.json());
      const s = d.suggestions || [];
      if (d.error || !s.length) { setSuggestErr(d.error || "No suggestion returned."); setSuggestions([]); }
      else setSuggestions(s);
    } catch {
      setSuggestErr("Network error.");
      setSuggestions([]);
    } finally { setSuggestBusy(false); }
  };

  const savePrompt = async () => {
    setSaveStatus("Saving…");
    try {
      const d = await fetch("/api/edit-prompt/" + encodeURIComponent(mediaId), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: promptText }),
      }).then((r) => r.json());
      setSaveStatus(d && d.ok ? "Saved ✓" : "Error");
    } catch { setSaveStatus("Error"); }
  };

  const deleteLocal = async () => {
    if (!window.confirm(
      "Remove this image from your local library? The file moves to _deleted/ and is " +
      "recoverable, and PixAI still has it — a later sync brings it back.")) return;
    setBusy(true);
    try {
      // /api/delete-local (the JSON route the bulk actions already use), replacing the
      // classic form route /delete/<id> -- which redirect-answered and whose response
      // this caller never even read, so a failed delete looked identical to a success.
      // Now a real error surfaces and onDeleted only fires when something was deleted.
      // (Migration off classic leftovers, 2026-08-08; /delete/<id> dies with the cut.)
      const d = await fetch("/api/delete-local", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ media_ids: [mediaId] }),
      }).then((r) => r.json()).catch((e) => ({ error: String((e && e.message) || e) }));
      if (!d || d.error) { window.alert((d && d.error) || "Could not remove it."); return; }
      if (d.failed) { window.alert("The file could not be moved to the trash folder — nothing was deleted."); return; }
      onDeleted();
    } finally { setBusy(false); }
  };

  const deleteCloud = async () => {
    const sibs = state.data.siblings || 1;
    const what = sibs > 1
      ? "This deletes ONLY this image from PixAI.\n\nThe other " + (sibs - 1) +
        " image" + (sibs - 1 === 1 ? "" : "s") + " in its batch stay on your account."
      : "This deletes this image from PixAI. It is the only image its task made.";
    if (!window.confirm(what + "\n\nIt is also removed from your local library. This cannot be undone.")) return;
    const typed = window.prompt("This permanently deletes from PixAI. Type DELETE to confirm:");
    if (typed !== "DELETE") { window.alert("Cancelled."); return; }
    setBusy(true);
    try {
      const d = await fetch("/api/delete-image", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ media_id: mediaId, confirm: true }),
      }).then((r) => r.json());
      if (!d || d.error) { window.alert((d && d.error) || "Could not delete it."); return; }
      onDeleted();
    } finally { setBusy(false); }
  };

  // ---- derived (guarded: only meaningful once `row` exists; consumers keep
  // their own loading/error early-return before rendering these) ----
  const headline = row ? (row.title || row.filename || "Untitled") : "";
  const hasPromptBlock = !!(row && (row.prompt_full || row.natural_prompt || row.negative_prompt));
  const tagList = row && row.art_tags ? row.art_tags.split(",").map((t) => t.trim()).filter(Boolean) : [];
  const collectionList = row && row.collections ? row.collections.split(",").map((c) => c.trim()).filter(Boolean) : [];
  const wide = !!(row && row.width && row.height && row.width / row.height > 1.6);
  const nsfw = (() => {
    if (!row || !row.nsfw_scores) return null;
    try {
      const s = JSON.parse(row.nsfw_scores);
      const parts = Object.entries(s).filter(([, v]) => v >= 0.05).sort((a, b) => b[1] - a[1]);
      return parts.length ? parts.map(([k, v]) => k + " " + Math.round(v * 100) + "%").join(", ") : "clean";
    } catch { return null; }
  })();

  return {
    state, row,
    headline, hasPromptBlock, tagList, collectionList, wide, nsfw,
    promptText, setPromptText,
    copied, copy,
    editingPrompt, setEditingPrompt, saveStatus, savePrompt,
    suggestions, suggestBusy, suggestErr, runSuggest,
    views,
    busy, deleteLocal, deleteCloud,
    upscaleOpen, upHost, toggleUpscale,
    handleRate,
  };
}
