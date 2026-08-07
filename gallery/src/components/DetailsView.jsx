import React, { useEffect, useRef, useState } from "react";
import Stars from "./Stars.jsx";
import useImageDetails from "../hooks/useImageDetails.js";
import SimilarModal from "./SimilarModal.jsx";

/* Motion: the reveal choreography locked 2026-07-30 (docs/DECISIONS.md, artifact
   477b4655 "The Reveal -- Motion Detail"). The headline LEADS on its own, sliding
   in from the right, before anything else in the record starts; the rest (kicker,
   the gold rule drawing itself under the title with a glint riding its tip, the
   quiet fact list, tags, the rating) fills in downward at one steady cascade; the
   action strip is the closing beat, popping up from below with a real
   overshoot-and-settle bounce -- deliberately not a right-slide like the
   headline's, so the two entrance vectors stay distinct. PACE is the "slowed just
   a nudge" adjustment the owner asked for on top of the locked timings -- a global
   stretch, not a re-time. The one bold move (the clicked image morphing into this
   frame) is handled separately, natively, by the browser's View Transition on the
   shared `vt-reveal` name -- see App.jsx's openDetails and Lightbox.jsx's stage.
   Skips straight to the settled state under prefers-reduced-motion. */
const EASE = "cubic-bezier(.2,.8,.3,1)";
const PACE = 1.15;
const P = (ms) => Math.round(ms * PACE);

function playReveal(root) {
  if (!root) return;
  const q = (sel) => root.querySelector(sel);
  const qa = (sel) => root.querySelectorAll(sel);
  const reduced = typeof window !== "undefined" && window.matchMedia &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if (reduced) {
    qa(".p-kicker, .p-title, .p-fact, .p-tag, .p-footer")
      .forEach((n) => { n.style.opacity = 1; n.style.transform = "none"; });
    const rule = q(".p-rule");
    if (rule) rule.style.clipPath = "inset(0 0% 0 0)";
    return;
  }

  const play = (el, kf, opts) =>
    el && el.animate(kf, Object.assign({ easing: EASE, fill: "forwards" }, opts));

  // the headline leads, alone, before anything else in the record
  play(q(".p-title"), [
    { opacity: 0, transform: "translateX(46px)" },
    { opacity: 1, transform: "translateX(0)" },
  ], { duration: P(400), delay: P(260) });

  // then the rest fills in downward at one steady rhythm
  const SHIFT = P(300);

  play(q(".p-kicker"), [
    { opacity: 0, transform: "translateY(6px)" },
    { opacity: 1, transform: "translateY(0)" },
  ], { duration: P(240), delay: P(300) + SHIFT });

  const rule = q(".p-rule"), glint = q(".p-glint"), track = q(".p-rule-track");
  const trackW = track ? track.getBoundingClientRect().width : 0;
  const ruleAnim = play(rule, [
    { clipPath: "inset(0 100% 0 0)" },
    { clipPath: "inset(0 0% 0 0)" },
  ], { duration: P(320), delay: P(520) + SHIFT, easing: "ease-out" });
  play(glint, [
    { opacity: 0, transform: "translateX(-20px)" },
    { opacity: 1, transform: "translateX(" + trackW * 0.15 + "px)", offset: 0.12 },
    { opacity: 1, transform: "translateX(" + trackW * 0.85 + "px)", offset: 0.82 },
    { opacity: 0, transform: "translateX(" + trackW + "px)" },
  ], { duration: P(320), delay: P(520) + SHIFT, easing: "ease-out" });
  if (ruleAnim) {
    ruleAnim.onfinish = () => play(track, [
      { filter: "drop-shadow(0 0 0px transparent)" },
      { filter: "drop-shadow(0 0 6px rgba(212,175,55,.85))", offset: 0.5 },
      { filter: "drop-shadow(0 0 0px transparent)" },
    ], { duration: P(260), easing: "ease-out" });
  }

  // the record, stamped in one piece at a time (prompt block rides along as item 0)
  const facts = qa(".p-fact");
  facts.forEach((li, i) => play(li, [
    { opacity: 0, transform: "translateY(8px)" },
    { opacity: 1, transform: "translateY(0)" },
  ], { duration: P(240), delay: P(560) + SHIFT + i * P(40) }));
  const lastFactDelay = P(560) + SHIFT + Math.max(0, facts.length - 1) * P(40) + P(130);

  const tags = qa(".p-tag");
  tags.forEach((t, i) => play(t, [
    { opacity: 0, transform: "scale(.85)" },
    { opacity: 1, transform: "scale(1)" },
  ], { duration: P(200), delay: lastFactDelay + i * P(28) }));
  const tagsDoneDelay = lastFactDelay + Math.max(0, tags.length - 1) * P(28) + P(200);

  // the closing beat: pops up from below and bounces into place
  play(q(".p-footer"), [
    { opacity: 0, transform: "translateY(30px) scale(.97)" },
    { opacity: 1, transform: "translateY(-7px) scale(1.01)", offset: 0.55 },
    { opacity: 1, transform: "translateY(2px) scale(.997)", offset: 0.8 },
    { opacity: 1, transform: "translateY(0) scale(1)" },
  ], { duration: P(440), delay: tagsDoneDelay + P(140), easing: "ease-out" });
}

/* The Details view -- "the layer deeper" (owner, 2026-07-30). Classic's
   /image/<media_id> page, ported: the full metadata, the whole action bar,
   edit-prompt, both delete paths, focus mode. A real view (App.jsx gives it a
   bookmarkable /next?image=<mid> URL via the History API), not a modal bolted
   onto the lightbox -- matching classic's genuinely separate page.

   Design pass (locked, docs/DECISIONS.md "Direction C"): a museum-placard
   composition -- the art framed beside a record, one confident headline, actions
   demoted to a footer strip. Direction C's own entry (restored in full in
   docs/DECISIONS.md after going missing from the live file for a while -- it was
   never actually lost, a prior session just mis-cited which prune removed it) is
   a motion/composition decision, not a field-hiding one: it never called for a
   "Full record" disclosure hiding specific fields, and neither classic
   (moonglade_gallery.py's DETAIL_HTML) nor the current Image Details.dc.html hide
   anything -- both show every field flat. The disclosure toggle that used to live
   here was a later implementer's own invention, corrected 2026-08-04 (owner: "We
   are not displaying metrics in details?"). All fields are flat and always
   visible again, per-row copy icons matching Image Details.dc.html:95-97's own
   row.copyable pattern instead of the footer-only copy buttons that stood in for
   them. Nothing here drops capability: every field and every action from the
   original port is still reachable, just organized by how often it's actually
   wanted.

   Data comes from /api/next/detail/<mid>, which mirrors classic's detail()
   route: the full catalog row, plus prev_id/next_id computed under the CURRENT
   filter/sort (advParams, the same shape /api/next/library takes). Unlike
   classic, file-existence isn't precomputed server-side -- the <img>/<video>
   onError below gets the same "not found" message for free. */
export default function DetailsView({
  mediaId, onClose, onNavigate, onRate, onEdit, onDeleted,
  onFilterByModel, onFilterByBatch, advParams,
  items, onOpenLightbox,
}) {
  const [focusMode, setFocusMode] = useState(
    () => (typeof localStorage !== "undefined" && localStorage.getItem("gallery_focus") === "1")
  );
  const [mediaOk, setMediaOk] = useState(true);
  // Image Details.dc.html:127-139's SIMILAR section -- entirely absent on desktop before
  // this (mobile already has it working with real /api/similar data). Reusing the exact
  // real SimilarModal.jsx already proven by Lightbox.jsx's own "✧ Similar" button, not a
  // rebuilt strip -- fits Direction C's own "actions demoted to a footer strip" idiom.
  const [similarOpen, setSimilarOpen] = useState(false);
  const recordRef = useRef(null);

  const {
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
  } = useImageDetails({ mediaId, advParams, onRate, onDeleted });

  // this component's OWN local reset on navigate (mediaOk isn't shared with the
  // mobile surface -- see useImageDetails.js for what is).
  useEffect(() => {
    setMediaOk(true);
  }, [mediaId]);

  useEffect(() => {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem("gallery_focus", focusMode ? "1" : "");
  }, [focusMode]);

  useEffect(() => {
    const onKey = (e) => {
      if (document.activeElement && /^(input|textarea)$/i.test(document.activeElement.tagName)) return;
      if (e.key === "Escape" || e.key === "ArrowUp") onClose();
      else if (e.key === "ArrowRight" && row && state.data.next_id) onNavigate(state.data.next_id);
      else if (e.key === "ArrowLeft" && row && state.data.prev_id) onNavigate(state.data.prev_id);
      else if (e.key === "f" || e.key === "F") setFocusMode((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [row, state.data, onClose, onNavigate]);

  // the reveal: fires once per newly-loaded image, never on an in-place
  // update (rating, focus toggle) -- keyed on the media id itself, not on
  // `row`/`state`, whose object identity changes on every optimistic setState.
  useEffect(() => {
    if (!row || focusMode) return;
    playReveal(recordRef.current);
  }, [row && row.media_id, focusMode]); // eslint-disable-line react-hooks/exhaustive-deps

  // Image Details.dc.html:39-43 -- the header's ⛶ Lightbox link + "N of M" index label,
  // both missing before this. Same real computation ImageDetailsMobile.jsx's own
  // indexLabel already uses -- position within the currently-loaded grid `items`.
  const detailIdx = row && items ? items.findIndex((it) => it.media_id === row.media_id) : -1;
  const indexLabel = detailIdx >= 0 && items ? (detailIdx + 1) + " of " + items.length : "";

  const navHref = (mid) => "/next?image=" + encodeURIComponent(mid || "");
  const navClick = (mid) => (e) => {
    if (!mid) { e.preventDefault(); return; }
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
    e.preventDefault();
    onNavigate(mid);
  };

  if (state.loading) return <div className="detail-wrap"><div className="gd-note">Loading…</div></div>;
  if (state.error || !row) {
    return (
      <div className="detail-wrap">
        <div className="detail-nav"><a className="back-link" href="/next" onClick={navClick(null)}>&larr; Back to gallery</a></div>
        <div className="gd-note">{state.error || "Image not found."}</div>
      </div>
    );
  }

  // headline/hasPromptBlock/tagList/collectionList/wide/nsfw now come from
  // useImageDetails() above -- see that hook for the exact same derivation
  // (byte-for-byte lifted, including the headline-is-never-a-prompt rule and
  // the wide-aspect-ratio placard-stacks-instead rule).

  return (
    <div className={"detail-wrap" + (focusMode ? " focus-mode" : "")}>
      <div className="detail-nav">
        <a className="back-link" href="/next" onClick={navClick(null)}>&larr; Back to gallery</a>
        {onOpenLightbox ? (
          <button type="button" className="nav-arrow" title="Full-screen viewer"
            onClick={() => onOpenLightbox(row.media_id)}>&#9974;</button>
        ) : null}
        {indexLabel ? <span className="detail-index">{indexLabel}</span> : null}
        <span className="sp" />
        {state.data.prev_id
          ? <a className="nav-arrow" href={navHref(state.data.prev_id)} onClick={navClick(state.data.prev_id)}>&lsaquo; Prev</a>
          : <span className="nav-disabled">&lsaquo; Prev</span>}
        {state.data.next_id
          ? <a className="nav-arrow" href={navHref(state.data.next_id)} onClick={navClick(state.data.next_id)}>Next &rsaquo;</a>
          : <span className="nav-disabled">Next &rsaquo;</span>}
        <button className="focus-btn" onClick={() => setFocusMode((v) => !v)}>{focusMode ? "Details" : "Focus"}</button>
      </div>

      <div className={"placard" + (wide ? " placard-wide" : "")}>
        <div className="placard-frame" style={{ viewTransitionName: "vt-reveal" }}>
          {!mediaOk ? (
            <div className="gd-note">{row.is_video === "1" ? "Video file not found on disk." : "Image file not found on disk."}</div>
          ) : row.is_video === "1" ? (
            <video controls autoPlay loop playsInline preload="metadata"
              poster={"/thumbs/" + encodeURIComponent(row.poster_media_id || row.media_id) + ".jpg"}
              onError={() => setMediaOk(false)}>
              <source src={"/video-file/" + encodeURIComponent(row.media_id)} />
            </video>
          ) : (
            <a href={"/full/" + encodeURIComponent(row.media_id)} target="_blank" rel="noreferrer">
              <img src={"/full/" + encodeURIComponent(row.media_id)} alt="" decoding="async" onError={() => setMediaOk(false)} />
            </a>
          )}
        </div>

        {!focusMode && (
          <aside className="placard-record" ref={recordRef}>
            <p className="p-kicker">
              {(row.model_name || row.model_id || "—").toUpperCase()}
              {row.model_name ? <button className="gd-mini" onClick={() => onFilterByModel(row.model_name)}>find more</button> : null}
            </p>

            <div className="p-title-wrap">
              <h2 className="p-title">{headline}</h2>
              <div className="p-rule-track">
                <span className="p-rule" />
                <span className="p-glint" />
              </div>
            </div>

            {/* the vitals: same summary the Lightbox already shows compactly
                (rating, dimensions, date) -- kept up top here too, ahead of
                the prompt block, instead of buried below a wall of text. */}
            <div className="p-vitals p-fact">
              <Stars mediaId={row.media_id} rating={row.rating} onRate={handleRate} />
              <span className="rating-label">{row.rating ? row.rating + " / 5" : "unrated"}</span>
              <span className="p-vsep">·</span>
              <span>{row.width}×{row.height}</span>
              <span className="p-vsep">·</span>
              <span>{(row.created_at || "").slice(0, 10)}</span>
            </div>

            {hasPromptBlock ? (
              <div className="p-fact p-prompts">
                {row.prompt_full ? <p><b>Prompt</b> {row.prompt_full}</p> : null}
                {row.natural_prompt ? <p><b>Natural</b> {row.natural_prompt}</p> : null}
                {row.negative_prompt ? <p><b>Negative</b> {row.negative_prompt}</p> : null}
              </div>
            ) : (
              <div className="p-fact p-prompts"><p>{row.prompt_preview || "—"}</p></div>
            )}

            <ul className="p-facts">
              {row.loras ? <li className="p-fact"><span>LoRA</span><b>{row.loras}</b></li> : null}
              <li className={"p-fact" + (copied === "seed" ? " copied" : "")}>
                <span>Seed</span><b className="mono">{row.seed || "—"}</b>
                {row.seed ? <button type="button" className="p-copy" title="Copy" aria-label="Copy Seed"
                  onClick={() => copy(row.seed, "seed")}>⧉</button> : null}
              </li>
              {row.is_published === "1" ? (
                <li className="p-fact">
                  <span>Engagement</span>
                  <b>{views != null ? "👁 " + Number(views).toLocaleString() + " · " : ""}
                    ♥ {row.liked_count || 0} · 💬 {row.comment_count || 0}
                    {row.aes_score ? " · aesthetic " + row.aes_score : ""}</b>
                </li>
              ) : null}
              {nsfw ? <li className="p-fact"><span>Content</span><b>{nsfw}</b></li> : null}
              {/* Steps/Sampler/CFG Scale/Clip Skip/Task ID/Media ID/Filename below used to
                  sit behind a "Full record" toggle -- restored flat and always-visible,
                  matching classic and Image Details.dc.html:376-386 exactly (2026-08-04
                  correction, see this file's own header comment). */}
              <li className="p-fact"><span>Steps</span><b>{row.steps || "—"}</b></li>
              <li className="p-fact"><span>Sampler</span><b>{row.sampler || "—"}</b></li>
              <li className="p-fact"><span>CFG Scale</span><b>{row.cfg_scale || "—"}</b></li>
              {row.clip_skip ? <li className="p-fact"><span>Clip Skip</span><b>{row.clip_skip}</b></li> : null}
              <li className={"p-fact" + (copied === "task" ? " copied" : "")}>
                <span>Task ID</span><b className="mono dim">{row.task_id}</b>
                {row.task_id ? <button type="button" className="p-copy" title="Copy" aria-label="Copy Task ID"
                  onClick={() => copy(row.task_id, "task")}>⧉</button> : null}
              </li>
              <li className={"p-fact" + (copied === "mid" ? " copied" : "")}>
                <span>Media ID</span><b className="mono dim">{row.media_id}</b>
                <button type="button" className="p-copy" title="Copy" aria-label="Copy Media ID"
                  onClick={() => copy(row.media_id, "mid")}>⧉</button>
              </li>
              <li className={"p-fact" + (copied === "fname" ? " copied" : "")}>
                <span>Filename</span><b className="mono dim">{row.filename}</b>
                {row.filename ? <button type="button" className="p-copy" title="Copy" aria-label="Copy Filename"
                  onClick={() => copy(row.filename, "fname")}>⧉</button> : null}
              </li>
            </ul>

            {(tagList.length || collectionList.length) ? (
              <div className="p-tags">
                {tagList.map((t) => <span key={"t" + t} className="p-tag">{t}</span>)}
                {collectionList.map((c) => <span key={"c" + c} className="p-tag p-tag-shelf">{c}</span>)}
              </div>
            ) : null}

            <div className="p-footer">
              <a className="btn" href={"/full/" + encodeURIComponent(row.media_id) + "?dl=1"}>⬇ Download</a>
              <a className="btn" href={"/full/" + encodeURIComponent(row.media_id)} target="_blank" rel="noreferrer">Open Full Size</a>
              {row.url ? <a className="btn" href={row.url} target="_blank" rel="noreferrer">Open on PixAI</a> : null}
              <button className="btn" onClick={() => copy(promptText, "prompt")}>{copied === "prompt" ? "Copied!" : "Copy Prompt"}</button>
              {/* Seed/Task ID/Media ID/Filename each have their own per-row ⧉ copy icon
                  now (Image Details.dc.html:95-97's row.copyable pattern) -- removed from
                  here 2026-08-04 to avoid duplicating the same action in two places. */}
              <button className="btn" onClick={() => window.print()}>🖨 Print</button>
              <button className="btn" onClick={() => setSimilarOpen(true)}>✧ Similar</button>
              {row.is_video !== "1" && (
                <>
                  <a className="btn" href={"/contact-sheet?ids=" + encodeURIComponent(row.media_id) + "&format=photo"} target="_blank" rel="noreferrer">4×6 photo</a>
                  <a className="btn" href={"/contact-sheet?ids=" + encodeURIComponent(row.media_id) + "&format=strip"} target="_blank" rel="noreferrer">Photo strip</a>
                </>
              )}
              <button className="btn" disabled={suggestBusy} onClick={runSuggest}>{suggestBusy ? "Reading…" : "✎ Suggest prompt"}</button>
              <button className="btn" onClick={() => { onClose(); onEdit(row.media_id); }}>✧ Edit this</button>
              <button className={"btn" + (upscaleOpen ? " btn-primary" : "")} onClick={toggleUpscale}>⇱ Upscale</button>
              {row.batch ? <button className="btn" onClick={() => onFilterByBatch(row.batch)}>View Batch</button> : null}
              <button className="btn" onClick={() => setEditingPrompt((v) => !v)}>Edit Prompt</button>
              <button className="btn btn-danger" disabled={busy} onClick={deleteLocal}>Delete locally</button>
              {state.data.can_delete_cloud && row.task_id ? (
                <button className="btn btn-danger" disabled={busy} onClick={deleteCloud}>Delete from PixAI</button>
              ) : null}
            </div>
          </aside>
        )}
      </div>

      {/* Unconditional mount -- see useImageDetails.js's header comment
          (correction 1): the custom element's own [open]/no-attribute CSS is
          what shows/hides it, not conditional React mounting. Mounting this
          only when upscaleOpen is true left the mount effect (which runs
          once, right after the first commit while upscaleOpen was still
          false) with nothing to attach to, so the panel never actually
          opened -- fixed here to match Lightbox.jsx's own, already-working
          unconditional host div. */}
      <div ref={upHost} />

      {!focusMode && suggestions && (
        <div id="suggest-box">
          {suggestErr ? <span style={{ color: "var(--overlay0)" }}>{suggestErr}</span> : (
            <>
              <div className="suggest-hd">Suggested prompt(s) · click to copy</div>
              {suggestions.map((t, i) => (
                <div key={i} className={"suggest-line" + (copied === "s" + i ? " done" : "")}
                  onClick={() => copy(t, "s" + i)}>
                  {t}
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {!focusMode && editingPrompt && (
        <div id="prompt-editor">
          <textarea rows={5} value={promptText} onChange={(e) => setPromptText(e.target.value)} />
          <div className="gd-row" style={{ marginTop: 8 }}>
            <button className="btn btn-primary" onClick={savePrompt}>Save</button>
            <button className="btn" onClick={() => setEditingPrompt(false)}>Cancel</button>
            <span id="save-status">{saveStatus}</span>
          </div>
        </div>
      )}

      {similarOpen && (
        <SimilarModal mediaId={row.media_id} onClose={() => setSimilarOpen(false)}
          onOpenDetails={(mid) => { setSimilarOpen(false); onNavigate(mid); }} />
      )}
    </div>
  );
}
