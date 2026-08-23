import React, { useEffect, useRef, useState } from "react";
import Stars from "./Stars.jsx";
import MobileSheet from "./MobileSheet.jsx";
import useImageDetails from "../hooks/useImageDetails.js";
import useSimilar from "../hooks/useSimilar.js";
import UpscalePanel from "./UpscalePanel.jsx";
import "../styles/gallery-mobile.css";
import "../styles/image-details-mobile.css";

/* Image Details Mobile -- design spec: "Image Details Mobile.dc.html"
   (design_handoff_moonglade_suite/), the mobile port of DetailsView.jsx ("the
   layer deeper", owner 2026-07-30). Reuses useImageDetails.js -- the EXACT
   same /api/next/detail/<mid> fetch, rating mirror, engagement fetch, copy/
   suggest/save/delete actions and shared <UpscalePanel> mount as
   DetailsView.jsx -- so there is ONE fetch, ONE set of action handlers, ONE
   Upscale mount contract for both surfaces, never a second drifting copy.

   MOUNT / ENTRY POINT: rendered by AppMobile.jsx as a fixed, full-viewport
   overlay (z above the hero AND the tab bar, not scoped to .glm-body) when a
   gallery tile is tapped outside select mode -- replacing the "Its own
   mobile pass (Lightbox Mobile) — coming next" toast GalleryMobile.jsx used
   to show on every tap. See AppMobile.jsx's own header comment for the
   openDetails/closeDetails wiring and GalleryMobile.jsx's tapView.

   WHY A DEDICATED FULL-SCREEN PRESENTATION, NOT MobileScreen.jsx: this
   design's own top bar carries a back link, an "open lightbox" glyph, an
   index label AND prev/next arrows -- a five-part header MobileScreen's
   fixed back-chevron+title contract (built for the Menu sheet's six plain
   destinations) doesn't fit without either dropping capability or fighting
   its chrome. DetailsView is also already a real top-level VIEW on desktop
   (App.jsx swaps it in for <main>, not an overlay atop it) -- giving mobile's
   equivalent the same "replaces the screen" status, rather than nesting it
   inside a generic push-screen built for menu destinations, matches that.
   No URL sync (unlike desktop's bookmarkable /next?image=<mid>): AppMobile.jsx
   has no URL-synced state ANYWHERE yet (tabs/sheets/screens are all plain
   state) -- adding history.pushState/popstate wiring here would be a first,
   separate architectural change, out of scope for porting this one screen.

   SCOPE, matched to the locked design file exactly (not desktop's larger
   action set -- "Install Design As Specified": the design package wins every
   visible question here, and every capability it omits is a deliberate mobile
   scope call, not a regression, since desktop keeps them all):
     - File-action chips: Download, Copy prompt, Upscale, Delete locally (all
       real). Desktop's Open Full Size / Open on PixAI / Print / 4x6-strip /
       Copy media id / Delete from PixAI are simply not in this design's chip
       row -- Media ID already has its own copy icon in the ledger below, and
       the rest don't appear at all, so they're not built here.
     - Record-action chips: Edit prompt (real, same inline-textarea +
       POST /edit-prompt/<mid> as desktop's "Edit Prompt"), Find similar
       (model) (real -- reads as "find more from the same model", wired to
       the same onFilterByModel desktop's kicker "find more" link uses; hidden
       when the model isn't known, matching desktop's own row.batch-gated
       "View Batch" precedent), View batch (real, same onFilterByBatch),
       Suggest prompt (real, same runSuggest). Send to Video is a DISCLOSED
       placeholder toast: AppMobile.jsx's Video mode (VideoMode.jsx) has no
       "load this image as the source frame" entry point at all yet (unlike
       desktop's requestVideo/genRequest one-shot contract) -- wiring a fake
       tab-switch with no actual frame loaded would be worse than an honest
       toast, matching this exact codebase's own established convention for
       an undone surface (the same message GalleryMobile.jsx's own tapView
       used before this build, and AppMobile.jsx's soonToast()).
     - SIMILAR box: REAL data (GET /api/similar/<mid>?k=48, the exact route
       SimilarModal.jsx already uses) -- not the design mock's placeholder
       PHOTOS array. First 8 render in the strip; "see all N" (a real count,
       not the mock's hardcoded "48") opens the full grid in a MobileSheet.
     - LINEAGE box: intentionally OMITTED. No backend anywhere tracks a
       source -> this -> upscaled -> clip generation chain, and the design
       mock's own lineage thumbnails are flat placeholder tint blocks with no
       real image behind them (confirmed in this build's design research).
       Rendering it would be inventing pixels for data that doesn't exist --
       exactly what GalleryGridMobile.jsx's own header comment already rules
       out for this codebase ("A tap surfaces an honest toast... not invented
       pixels"). Full record" disclosure toggle: not needed -- the ledger
       below already shows every field up front (matching the design's own
       always-expanded ledger), so there's no second "expand" step to build.
     - Focus mode / the reveal choreography's full state machine: desktop-only
       (confirmed by design research: mobile's own componentDidMount wires
       only ArrowLeft/ArrowRight nav + Escape-closes-Upscale, no F-key, no
       focus toggle). A lighter CSS-only entrance (frame scale-in, title
       inscribe, rule draw -- image-details-mobile.css) plays once per image
       via a `key={row.media_id}` remount, matching Lightbox.jsx's own
       `key={it.media_id}` convention for the identical purpose, rather than
       porting playReveal()'s Web Animations timeline verbatim.
     - Upscale panel body: the REAL shared <UpscalePanel> component (inline),
       not the design mock's bespoke inline-styled markup -- so a few details
       genuinely differ from the pixel mock (the custom animated upscaler
       dropdown, tooltip-based method hints) exactly the way Lightbox.jsx's own
       flyout already differs from any per-screen mock,
       because it is a REUSED shared component, not rebuilt per screen. */

/* useSimilar (the /api/similar data path) now lives in hooks/useSimilar.js, shared with
   the desktop DetailsView's inline strip -- same fetch, same seq guard, byte-for-byte. */
export default function ImageDetailsMobile({
  mediaId, onClose, onNavigate, onRate, onDeleted,
  onFilterByModel, onFilterByBatch, advParams, items,
  onOpenLightbox, onPublish,
}) {
  const [closing, setClosing] = useState(false);
  const [mediaOk, setMediaOk] = useState(true);
  const [simSheetOpen, setSimSheetOpen] = useState(false);
  const [simClosing, setSimClosing] = useState(false);
  const simTimer = useRef(null);

  const {
    state, row,
    headline, tagList, collectionList, nsfw,
    promptText, setPromptText,
    copied, copy,
    editingPrompt, setEditingPrompt, saveStatus, savePrompt,
    suggestions, suggestBusy, suggestErr, runSuggest,
    views,
    busy, deleteLocal,
    upscaleOpen, upEl, toggleUpscale,
    handleRate,
  } = useImageDetails({ mediaId, advParams, onRate, onDeleted });

  const similar = useSimilar(row ? row.media_id : null);

  // this component's OWN local resets on navigate (mediaOk/the see-all sheet
  // aren't shared with the desktop surface -- see useImageDetails.js for
  // what is).
  useEffect(() => { setMediaOk(true); setSimSheetOpen(false); }, [mediaId]);

  useEffect(() => () => clearTimeout(simTimer.current), []);
  const closeSimSheet = () => {
    setSimClosing(true);
    clearTimeout(simTimer.current);
    simTimer.current = setTimeout(() => { setSimSheetOpen(false); setSimClosing(false); }, 280);
  };

  // Plays the exit fade before the real unmount, same overlay law every other
  // big surface in this codebase follows (Lightbox.jsx's own close()).
  const close = () => {
    setClosing(true);
    setTimeout(onClose, 200);
  };

  // Design's own componentDidMount: ArrowLeft/ArrowRight walk prev/next;
  // Escape closes the Upscale sheet ONLY (no F-key, no focus-mode exit, no
  // "back to gallery" -- confirmed by design research, unlike desktop's
  // fuller Escape/ArrowUp/F ladder).
  useEffect(() => {
    const onKey = (e) => {
      if (document.activeElement && /^(input|textarea|select)$/i.test(document.activeElement.tagName)) return;
      if (upscaleOpen) {
        if (e.key === "Escape") toggleUpscale();
        return;
      }
      if (e.key === "ArrowRight" && row && state.data.next_id) onNavigate(state.data.next_id);
      else if (e.key === "ArrowLeft" && row && state.data.prev_id) onNavigate(state.data.prev_id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [row, state.data, onNavigate, upscaleOpen, toggleUpscale]);

  // Page-local position ("k of N loaded items"), matching Lightbox.jsx's own
  // "index+1 / items.length" convention -- real and honest, though scoped to
  // whichever page is currently loaded rather than a true global position
  // (Prev/Next itself still walks the REAL, full filtered set across page
  // boundaries via the server's prev_id/next_id, exactly like desktop).
  const idx = items ? items.findIndex((it) => it.media_id === mediaId) : -1;
  const indexLabel = idx >= 0 && items ? (idx + 1) + " of " + items.length : "";

  const toast = (title, msg) => { if (window.Toast) window.Toast.show({ title, msg }); };

  if (state.loading) {
    return (
      <div className={"idm-root" + (closing ? " closing" : "")}>
        <div className="idm-topbar">
          <button type="button" className="idm-back" onClick={close}>← Gallery</button>
        </div>
        <div className="idm-body"><div className="gd-note">Loading…</div></div>
      </div>
    );
  }
  if (state.error || !row) {
    return (
      <div className={"idm-root" + (closing ? " closing" : "")}>
        <div className="idm-topbar">
          <button type="button" className="idm-back" onClick={close}>← Gallery</button>
        </div>
        <div className="idm-body"><div className="gd-note">{state.error || "Image not found."}</div></div>
      </div>
    );
  }

  // The ledger, in the design's own fixed order -- stacked label-above-value
  // rows (mobile), not desktop's two-column fixed-label-width row.
  const ledgerRows = [
    // promptText (from useImageDetails) already resolves prompt_full ||
    // prompt_preview -- reusing it here (rather than a second, separately-
    // gated fallback) keeps this row and the "Copy prompt" chip always
    // showing/copying the exact same text.
    ["Full prompt", promptText || "—", {}],
    ["Natural", row.natural_prompt || "—", { dim: true }],
    ["Negative", row.negative_prompt || "—", { dim: true }],
    ["Model", row.model_name || row.model_id || "—", {}],
    ["LoRAs", row.loras || "—", {}],
    ["Seed", row.seed || "—", { mono: true, copy: true }],
    ["Steps · CFG", (row.steps || "—") + " · " + (row.cfg_scale || "—"), {}],
    ["Sampler", row.sampler || "—", {}],
    // Conditional, same as desktop's DetailsView.jsx -- clip_skip is genuinely
    // absent for most models, so no row at all beats a permanent "—".
    ...(row.clip_skip ? [["Clip Skip", row.clip_skip, {}]] : []),
    ["Task ID", row.task_id || "—", { mono: true, dim: true, copy: true }],
    ["Media ID", row.media_id, { mono: true, dim: true, copy: true }],
    ["Filename", row.filename || "—", { mono: true, dim: true, copy: true }],
  ];

  return (
    <div className={"idm-root" + (closing ? " closing" : "")} role="dialog" aria-modal="true" aria-label="Image details">
      <div className="idm-topbar">
        <button type="button" className="idm-back" onClick={close}>← Gallery</button>
        <button type="button" className="idm-lb" title="Full-screen viewer"
          onClick={() => onOpenLightbox(row.media_id)}>
          ⛶
        </button>
        <div className="idm-fill" />
        {indexLabel ? <span className="idm-index">{indexLabel}</span> : null}
        <button type="button" className="idm-navbtn" disabled={!state.data.prev_id}
          onClick={() => onNavigate(state.data.prev_id)} aria-label="Previous">‹</button>
        <button type="button" className="idm-navbtn" disabled={!state.data.next_id}
          onClick={() => onNavigate(state.data.next_id)} aria-label="Next">›</button>
      </div>

      <div className="idm-body">
        <div className="idm-frame" key={row.media_id}>
          {!mediaOk ? (
            <div className="gd-note">{row.is_video === "1" ? "Video file not found on disk." : "Image file not found on disk."}</div>
          ) : row.is_video === "1" ? (
            <video controls autoPlay loop playsInline preload="metadata"
              poster={"/thumbs/" + encodeURIComponent(row.poster_media_id || row.media_id) + ".jpg"}
              onError={() => setMediaOk(false)}>
              <source src={"/video-file/" + encodeURIComponent(row.media_id)} />
            </video>
          ) : (
            <img src={"/full/" + encodeURIComponent(row.media_id)} alt="" decoding="async" onError={() => setMediaOk(false)} />
          )}
        </div>

        <div className="idm-chiprow">
          <a className="idm-chip" href={"/full/" + encodeURIComponent(row.media_id) + "?dl=1"}>⬇ Download</a>
          {/* ☁ Publish -- real since 2026-08-07, same real pipeline as desktop's
              DetailsView.jsx. Already-published rows say so instead of offering it
              twice; this row is the full catalog row, artwork_id is right here. */}
          {(row.artwork_id || "").trim()
            ? <span className="idm-chip is-off" title="Already on your PixAI profile — manage it from My Art">☁ Published</span>
            : <button type="button" className="idm-chip" onClick={() => onPublish && onPublish(row.media_id)}>☁ Publish</button>}
          <button type="button" className="idm-chip" onClick={() => copy(promptText, "prompt")}>
            {copied === "prompt" ? "Copied!" : "⧉ Copy prompt"}
          </button>
          <button type="button" className={"idm-chip" + (upscaleOpen ? " on" : "")} onClick={toggleUpscale}>⇱ Upscale</button>
          <button type="button" className="idm-chip idm-chip-danger" disabled={busy} onClick={deleteLocal}>
            Delete locally
          </button>
        </div>

        <div className="idm-statrow">
          <Stars mediaId={row.media_id} rating={row.rating} onRate={handleRate} />
          <span className="idm-ratelbl">{row.rating ? row.rating + " / 5" : "unrated"}</span>
          <div className="idm-fill" />
          <span className="idm-dims">{row.width}×{row.height} · {(row.created_at || "").slice(0, 10)}</span>
        </div>

        <div className="idm-head">
          <p className="idm-kicker">{(row.model_name || row.model_id || "—")}</p>
          <h2 className="idm-title" key={"t" + row.media_id}>&#8220;{headline}&#8221;</h2>
          <div className="idm-rule"><span key={"r" + row.media_id} /></div>
        </div>

        {(tagList.length || collectionList.length) ? (
          <div className="idm-tags">
            {tagList.map((t) => <span key={"t" + t} className="idm-tag">{t}</span>)}
            {collectionList.map((c) => <span key={"c" + c} className="idm-tag idm-tag-shelf">{c}</span>)}
          </div>
        ) : null}

        <div className="idm-ledger">
          {ledgerRows.map(([label, value, opts]) => (
            <div key={label} className={"idm-row" + (copied === label ? " copied" : "")}>
              <div className="idm-row-label">{label}</div>
              <div className="idm-row-vwrap">
                <div className={"idm-row-val" + (opts.mono ? " mono" : "") + (opts.dim ? " dim" : "")}>{value}</div>
                {opts.copy ? (
                  <button type="button" className="idm-row-copy" onClick={() => copy(value, label)}
                    aria-label={"Copy " + label}>⧉</button>
                ) : null}
              </div>
            </div>
          ))}
          {row.is_published === "1" ? (
            <div className="idm-row">
              <div className="idm-row-label">Engagement</div>
              <div className="idm-row-vwrap">
                <div className="idm-row-val">
                  {views != null ? "👁 " + Number(views).toLocaleString() + " · " : ""}
                  ♥ {row.liked_count || 0} · 💬 {row.comment_count || 0}
                  {row.aes_score ? " · aesthetic " + row.aes_score : ""}
                </div>
              </div>
            </div>
          ) : null}
          {nsfw ? (
            <div className="idm-row">
              <div className="idm-row-label">Content</div>
              <div className="idm-row-vwrap"><div className="idm-row-val">{nsfw}</div></div>
            </div>
          ) : null}
        </div>

        <div className="idm-similar">
          <div className="idm-similar-head">
            <span className="idm-subhead">✧ SIMILAR</span>
            <span className="idm-dimtext">closest by eye</span>
            <div className="idm-fill" />
            {similar.images.length > 8 ? (
              <button type="button" className="idm-seeall" onClick={() => setSimSheetOpen(true)}>
                see all {similar.images.length}
              </button>
            ) : null}
          </div>
          {similar.loading ? (
            <div className="idm-simnote">Finding lookalikes…</div>
          ) : similar.images.length ? (
            <div className="idm-simstrip">
              {similar.images.slice(0, 8).map((it) => (
                <button key={it.media_id} type="button" className="idm-simtile" onClick={() => onNavigate(it.media_id)}>
                  <img src={it.thumb} alt="" loading="lazy" />
                  {it.is_video === "1" ? <span className="vbadge">▶</span> : null}
                </button>
              ))}
            </div>
          ) : (
            <div className="idm-simnote">{similar.error}</div>
          )}
        </div>

        <div className="idm-recrow">
          <button type="button" className="idm-chip" onClick={() => setEditingPrompt((v) => !v)}>Edit prompt</button>
          <button type="button" className="idm-chip"
            onClick={() => toast("Send to Video", "Its own mobile wiring — coming later.")}>
            Send to Video
          </button>
          {row.model_name ? (
            <button type="button" className="idm-chip" onClick={() => onFilterByModel(row.model_name)}>
              Find similar (model)
            </button>
          ) : null}
          {row.batch ? (
            <button type="button" className="idm-chip" onClick={() => onFilterByBatch(row.batch)}>View batch</button>
          ) : null}
          <button type="button" className="idm-chip" disabled={suggestBusy} onClick={runSuggest}>
            {suggestBusy ? "Reading…" : "Suggest prompt"}
          </button>
        </div>

        {suggestions && (
          <div className="idm-editor">
            {suggestErr ? <span style={{ color: "var(--overlay0)" }}>{suggestErr}</span> : (
              <>
                <div className="idm-row-label">Suggested prompt(s) · tap to copy</div>
                {suggestions.map((t, i) => (
                  <div key={i} className={"idm-suggest-line" + (copied === "s" + i ? " done" : "")}
                    onClick={() => copy(t, "s" + i)}>
                    {t}
                  </div>
                ))}
              </>
            )}
          </div>
        )}

        {editingPrompt && (
          <div className="idm-editor">
            <textarea rows={5} value={promptText} onChange={(e) => setPromptText(e.target.value)} />
            <div className="idm-editor-row">
              <button type="button" className="idm-chip" onClick={savePrompt}>Save</button>
              <button type="button" className="idm-chip" onClick={() => setEditingPrompt(false)}>Cancel</button>
              <span className="idm-savestatus">{saveStatus}</span>
            </div>
          </div>
        )}
      </div>

      {/* Upscale bottom sheet -- ALWAYS mounted (host div + wrapper both);
          only the "open" class toggles. See image-details-mobile.css's own
          header comment on this section for exactly why. */}
      <div className={"idm-sheet-scrim" + (upscaleOpen ? " open" : "")} onClick={toggleUpscale} aria-hidden={!upscaleOpen} />
      <div className={"idm-sheet-slab" + (upscaleOpen ? " open" : "")} role="dialog" aria-modal={upscaleOpen}
        aria-label="Upscale">
        <div className="idm-sheet-head">
          <span className="idm-sheet-title">⇱ Upscale</span>
          <button type="button" className="idm-sheet-x" onClick={toggleUpscale} aria-label="Close">×</button>
        </div>
        <UpscalePanel ref={upEl} inline />
      </div>

      {/* "see all N similar" -- the exact same fetched images, no second
          request. Its own compact 4-column grid (image-details-mobile.css's
          .idm-simgrid), not desktop's fixed-width .similar-modal (sized for a
          wide viewport, would overflow a 390px sheet). This one has no
          persistent-DOM requirement, so the shared MobileSheet.jsx chrome is
          reused as-is. */}
      <MobileSheet open={simSheetOpen} closing={simClosing} onClose={closeSimSheet} title="✧ SIMILAR">
        <div className="idm-simgrid">
          {similar.images.map((it) => (
            <button key={it.media_id} type="button" className="idm-simtile"
              onClick={() => { closeSimSheet(); onNavigate(it.media_id); }}>
              <img src={it.thumb} alt="" loading="lazy" />
              {it.is_video === "1" ? <span className="vbadge">▶</span> : null}
            </button>
          ))}
        </div>
      </MobileSheet>
    </div>
  );
}
