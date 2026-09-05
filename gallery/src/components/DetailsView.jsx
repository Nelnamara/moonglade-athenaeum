import React, { useEffect, useRef, useState } from "react";
import Stars from "./Stars.jsx";
import useImageDetails from "../hooks/useImageDetails.js";
import useSimilar from "../hooks/useSimilar.js";
import UpscalePanel from "./UpscalePanel.jsx";
import useScrollLock from "../hooks/useScrollLock.js";
import { apiGet, rebuildPoster, fetchSeries } from "../api.js";
import { localDay, localDayTime } from "../gen/dates.js";
import { seriesSuffix } from "../gen/seriesName.js";

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
    qa(".p-kicker, .p-title, .p-fact, .p-tag, .p-actions")
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

  // the ledger, stamped in one row at a time (the More-details disclosure rides along
  // as the last "row"; the rows folded inside it are not part of the cascade)
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

  // the closing beat: the record's action groups pop up from below and bounce into
  // place, one after another (record, more) -- the same bounce, staggered. The file
  // actions under the hero are NOT part of this: the DC (Image Details.dc.html:56-60)
  // draws them unanimated in the picture column, and they live outside `root`.
  qa(".p-actions").forEach((g, i) => play(g, [
    { opacity: 0, transform: "translateY(30px) scale(.97)" },
    { opacity: 1, transform: "translateY(-7px) scale(1.01)", offset: 0.55 },
    { opacity: 1, transform: "translateY(2px) scale(.997)", offset: 0.8 },
    { opacity: 1, transform: "translateY(0) scale(1)" },
  ], { duration: P(440), delay: tagsDoneDelay + P(140) + i * P(90), easing: "ease-out" }));
}

/* One ledger row (Image Details.dc.html:91-98 + :326-339 row()): a right-aligned
   118px label, the value (mono / dim / warm faces as the DC's opts), and the ⧉ copy
   icon on the copyable ids. An empty value renders "—" -- the DC shows every one of
   its rows even when there is nothing in it (LoRAs). `quiet` rows are the ones folded
   under "More details": they skip the .p-fact reveal class, since the cascade only
   stamps what is on screen. */
function LedgerRow({ label, value, mono, dim, warm, copyKey, quiet, copied, copy }) {
  const text = value == null ? "" : String(value);
  const has = text.trim() !== "";
  const cls = "p-row" + (quiet ? "" : " p-fact") + (copyKey && copied === copyKey ? " copied" : "");
  const vcls = "p-row-v" + (mono ? " mono" : "") + (dim ? " dim" : "") + (warm ? " warm" : "");
  return (
    <div className={cls}>
      <span className="p-row-k">{label}</span>
      <span className={vcls}>{has ? text : "—"}</span>
      {copyKey && has ? (
        <button type="button" className="p-copy" title="Copy" aria-label={"Copy " + label}
          onClick={() => copy(text, copyKey)}>⧉</button>
      ) : null}
    </div>
  );
}

const MORE_KEY = "mg_details_more";

/* Reroll-run collapse for the SESSION strip (#34, review item 6). A dial-in
   marathon is mostly seed-only rerolls; drawn one-tile-per-task the frost-queen's
   173-task run would be 173 tiles. So a run of 2+ CONSECUTIVE reroll steps collapses
   into a single "…N rerolls…" chip and the strip renders ~a dozen items. Two steps
   are never swallowed: the CURRENT (lit) step -- if this very image's task is a reroll
   it still shows expanded -- and the LAST step (the series' latest state always reads
   as a real tile). A lone reroll (run of 1) shows normally too. Returns a flat list of
   {kind:"step", step} | {kind:"rerolls", count, from, to}, in order. */
function groupSeriesSteps(steps, currentTaskId) {
  const list = Array.isArray(steps) ? steps : [];
  const lastIdx = list.length - 1;
  const pinned = (i) => i === lastIdx || list[i].task_id === currentTaskId;
  const out = [];
  let i = 0;
  while (i < list.length) {
    if (list[i].reroll && !pinned(i)) {
      const run = [];
      while (i < list.length && list[i].reroll && !pinned(i)) { run.push(list[i]); i++; }
      if (run.length >= 2) {
        out.push({ kind: "rerolls", count: run.length, from: run[0].v, to: run[run.length - 1].v });
      } else {
        out.push({ kind: "step", step: run[0] });
      }
    } else {
      out.push({ kind: "step", step: list[i] });
      i++;
    }
  }
  return out;
}

/* The Details view -- "the layer deeper" (owner, 2026-07-30). Classic's
   /image/<media_id> page, ported: the full metadata, the whole action bar,
   edit-prompt, both delete paths, focus mode. A real view (App.jsx gives it a
   bookmarkable /?image=<mid> URL via the History API), not a modal bolted
   onto the lightbox -- matching classic's genuinely separate page.

   Rebuilt 2026-08-23 to the PIXEL source, design_handoff/design_handoff_moonglade_suite/
   Image Details.dc.html, after the owner's verdict on the previous build ("does not
   follow the design's layout. There should be NO page scrolling. The image stays static
   and the details pane scrolls if needed."). The structure is the DC's, line for line:

     shell (DC:36)       fixed inset-0, 100vh, overflow hidden, flex column -- the document
                         NEVER scrolls
     top bar (DC:38-46)  Back · divider · ⛶ Lightbox · spacer · N of M · Prev · Next (+ the
                         app's Focus toggle last, a shipped owner feature)
     body (DC:345)       grid, two EQUAL columns always (minmax(0,1fr) x2); F collapses the
                         second to 0px and fades the record
     picture (DC:50-71)  the frame sized by the DC's formula (width = min(100%, 72vh x AR),
                         aspect-ratio W/H, centred), then the FILE ACTIONS row, then the
                         stars row with dims · date
     record (DC:73-140)  the only scroller: head (kicker / headline / rule), tags, the
                         11-row ledger, the record actions, LINEAGE, ◈ SIMILAR

   Gone with this rebuild: the branch that stacked landscape images over the record
   (an earlier implementer's invention, not in the design), the record-column
   placement of the file actions, the vitals row at the top of the record, and the
   ever-growing flat fact list. What the app carries beyond the DC's eleven rows (the
   issue #18 generation surface, engagement, content scores) is NOT dropped: it folds
   under a collapsed "More details" disclosure directly below the ledger, remembered in
   localStorage (mg_details_more). Nothing lost its handler; the app's own extra actions
   keep their quiet More row at the end of the record.

   Data comes from /api/next/detail/<mid>, which mirrors classic's detail()
   route: the full catalog row, plus prev_id/next_id computed under the CURRENT
   filter/sort (advParams, the same shape /api/next/library takes). Unlike
   classic, file-existence isn't precomputed server-side -- the <img>/<video>
   onError below gets the same "not found" message for free. */
export default function DetailsView({
  mediaId, onClose, onNavigate, onRate, onEdit, onRemix, onVideo, onDeleted,
  onFilterByModel, onFilterByBatch, advParams,
  items, onOpenLightbox, onPublish, onSimilar,
  morph = true,
}) {
  useScrollLock();   // page never scrolls behind a full-screen panel (2026-08-06)
  const [focusMode, setFocusMode] = useState(
    () => (typeof localStorage !== "undefined" && localStorage.getItem("gallery_focus") === "1")
  );
  const [moreOpen, setMoreOpen] = useState(
    () => (typeof localStorage !== "undefined" && localStorage.getItem(MORE_KEY) === "1")
  );
  const [mediaOk, setMediaOk] = useState(true);
  const [posterBusy, setPosterBusy] = useState(false);
  const [posterSrc, setPosterSrc] = useState(null);   // set by Rebuild poster (cache-busted)
  // LINEAGE (Image Details.dc.html:108-123, 2026-08-06): where this image came from and
  // what came from it -- GET /api/lineage/<mid>, a pure catalog read (batch siblings via
  // task_id, derivation chain via source_media_id). Real data, fetched per image.
  const [lineage, setLineage] = useState(null);
  // SESSION (#34, direction C): the dial-in series this image's task is a step in.
  // null for a singleton (~85%) or any fetch miss -- the panel then renders nothing.
  const [series, setSeries] = useState(null);
  const seriesSeq = useRef(0);
  const recordRef = useRef(null);

  const {
    state, row,
    headline, tagList, collectionList, nsfw,
    promptText, setPromptText,
    copied, copy,
    editingPrompt, setEditingPrompt, saveStatus, savePrompt,
    suggestions, suggestBusy, suggestErr, runSuggest,
    views,
    busy, deleteLocal, deleteCloud,
    upEl,
    handleRate,
  } = useImageDetails({ mediaId, advParams, onRate, onDeleted });

  // ◈ SIMILAR (Image Details.dc.html:127-140): the same /api/similar data path the mobile
  // record's strip already uses (hooks/useSimilar.js). The first 8 render inline below;
  // "see all N" hands the full set to the gallery via onSimilar.
  const similar = useSimilar(row ? row.media_id : null);

  // this component's OWN local reset on navigate (mediaOk isn't shared with the
  // mobile surface -- see useImageDetails.js for what is).
  useEffect(() => {
    setMediaOk(true);
    setPosterSrc(null);   // a rebuilt poster belongs to ONE row; don't carry it to the next
  }, [mediaId]);

  useEffect(() => {
    if (!mediaId) { setLineage(null); return; }
    let dead = false;
    setLineage(null);
    apiGet("/api/lineage/" + encodeURIComponent(mediaId))
      .then((d) => { if (!dead) setLineage(d.error ? null : d); });
    return () => { dead = true; };
  }, [mediaId]);

  // SESSION membership + steps (#34): fetchSeries POSTs the one task_id to /api/series
  // and, only if it's in a multi-task series, GETs /api/series/<sid>. Keyed on the TASK
  // id -- siblings of one generation share it, and so share the series, so navigating
  // between them costs no refetch -- and stale-guarded with the Similar path's seq ref,
  // since a fresh async pair fires while the previous one may still be in flight.
  const seriesTaskId = row ? row.task_id : "";
  useEffect(() => {
    if (!seriesTaskId) { setSeries(null); return; }
    const mine = ++seriesSeq.current;
    setSeries(null);
    fetchSeries(seriesTaskId).then((d) => { if (mine === seriesSeq.current) setSeries(d); });
  }, [seriesTaskId]);

  useEffect(() => {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem("gallery_focus", focusMode ? "1" : "");
  }, [focusMode]);

  useEffect(() => {
    if (typeof localStorage === "undefined") return;
    localStorage.setItem(MORE_KEY, moreOpen ? "1" : "");
  }, [moreOpen]);

  // the Upscale float (Image Details.dc.html:143-189 -- a fixed panel over the page, the
  // Lightbox's own flyout language) is open: Esc closes IT and nothing else fires.
  const upscaleUp = () => !!(upEl.current && upEl.current.isOpen() && !upEl.current.isClosing());

  useEffect(() => {
    const onKey = (e) => {
      if (upscaleUp()) {
        if (e.key === "Escape") upEl.current.close();
        return;
      }
      if (document.activeElement && /^(input|textarea)$/i.test(document.activeElement.tagName)) return;
      if (e.key === "Escape" || e.key === "ArrowUp") onClose();
      else if (e.key === "ArrowRight" && row && state.data.next_id) onNavigate(state.data.next_id);
      else if (e.key === "ArrowLeft" && row && state.data.prev_id) onNavigate(state.data.prev_id);
      else if (e.key === "f" || e.key === "F") setFocusMode((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [row, state.data, onClose, onNavigate]); // eslint-disable-line react-hooks/exhaustive-deps

  // the reveal: fires once per newly-loaded image, never on an in-place
  // update (rating, More toggle) -- keyed on the media id itself, not on
  // `row`/`state`, whose object identity changes on every optimistic setState.
  // Replays when Focus lets the record back in (it was faded out, not unmounted).
  useEffect(() => {
    if (!row || focusMode) return;
    playReveal(recordRef.current);
  }, [row && row.media_id, focusMode]); // eslint-disable-line react-hooks/exhaustive-deps

  // Image Details.dc.html:39-43 -- the header's ⛶ Lightbox link + "N of M" index label.
  // Same real computation ImageDetailsMobile.jsx's own indexLabel already uses --
  // position within the currently-loaded grid `items`.
  const detailIdx = row && items ? items.findIndex((it) => it.media_id === row.media_id) : -1;
  const indexLabel = detailIdx >= 0 && items ? (detailIdx + 1) + " of " + items.length : "";

  const navHref = (mid) => "/?image=" + encodeURIComponent(mid || "");
  const navClick = (mid) => (e) => {
    // mid=null is the "Back to gallery" link: close the takeover. (This used to
    // preventDefault and then just RETURN -- a dead click; only Escape closed.
    // Found live 2026-08-08 while verifying the portal fix.)
    if (!mid) { e.preventDefault(); onClose(); return; }
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
    e.preventDefault();
    onNavigate(mid);
  };

  if (state.loading) return <div className="detail-wrap"><div className="gd-note">Loading…</div></div>;
  if (state.error || !row) {
    return (
      <div className="detail-wrap">
        <div className="detail-nav"><a className="back-link" href="/" onClick={navClick(null)}>&larr; Back to gallery</a></div>
        <div className="gd-note">{state.error || "Image not found."}</div>
      </div>
    );
  }

  // The frame's size is the DC's formula (frameStyle, Image Details.dc.html:357-358):
  // the inline size is the definite one -- min(100%, 72vh x AR) -- and aspect-ratio
  // derives the height, so it always stays inside the viewport budget with no
  // percentage height to resolve against. One custom property carries W / H for both
  // the calc() and the aspect-ratio (styles.css .placard-frame). A row with no
  // recorded size (some videos) gets no ratio: the media sizes the frame instead.
  const W = Number(row.width) || 0, H = Number(row.height) || 0;
  const hasDims = W > 0 && H > 0;
  const frameStyle = { viewTransitionName: morph ? "vt-reveal" : "none" };
  if (hasDims) frameStyle["--ar"] = W + " / " + H;
  const dims = hasDims ? W + "×" + H : "";
  const day = localDay(row.created_at);

  const stepsCfg = (row.steps || row.cfg_scale)
    ? (row.steps || "—") + " · " + (row.cfg_scale || "—")
    : "";
  const c = { copied, copy };

  // The full generation surface (issue #18) and the app's other extras, folded under
  // "More details": only the fields this row actually carries (older rows predate the
  // capture), and no disclosure at all when there is nothing to fold.
  const extra = [];
  const push = (label, value, opts) => { if (value != null && String(value).trim() !== "") extra.push({ label, value, ...(opts || {}) }); };
  push("Clip Skip", row.clip_skip);
  push("Mode", row.inference_profile);
  push("Quality Tag", row.quality_tag);
  push("Prompt Helper", row.prompt_helper);
  push("Control Nets", row.control_nets, { mono: true, dim: true });
  push("Priority", row.priority ? (row.priority === "1500" ? "turbo (1500)" : row.priority) : "");
  push("Render Time", row.render_seconds ? Math.round(parseFloat(row.render_seconds)) + "s" : "");
  push("Backend", row.backend, { mono: true, dim: true });
  push("Started", localDayTime(row.started_at), { mono: true, dim: true });
  push("Ended", localDayTime(row.ended_at), { mono: true, dim: true });
  push("Updated", localDayTime(row.updated_at), { mono: true, dim: true });
  push("Retries", row.retry_count && row.retry_count !== "0" ? row.retry_count : "");
  push("Moderation", row.moderation);
  push("Video Mode", row.video_mode);
  push("Video Model", row.video_model);
  if (row.is_published === "1") {
    push("Engagement",
      (views != null ? "👁 " + Number(views).toLocaleString() + " · " : "") +
      "♥ " + (row.liked_count || 0) + " · 💬 " + (row.comment_count || 0) +
      (row.aes_score ? " · aesthetic " + row.aes_score : ""));
  }
  push("Content", nsfw);

  return (
    <div className={"detail-wrap" + (focusMode ? " focus-mode" : "")}>
      {/* TOP BAR (Image Details.dc.html:38-46): Back · divider · ⛶ Lightbox · spacer ·
          N of M · ‹ Prev · Next › -- and the app's Focus toggle last (a shipped owner
          feature; the DC has the F key, not the button). */}
      <div className="detail-nav">
        <a className="back-link" href="/" onClick={navClick(null)}>&larr; Back to gallery</a>
        {onOpenLightbox ? (
          <>
            <span className="detail-div" aria-hidden="true" />
            <button type="button" className="detail-lb" title="Full-screen viewer"
              onClick={() => onOpenLightbox(row.media_id)}>&#9974; Lightbox</button>
          </>
        ) : null}
        <span className="sp" />
        {indexLabel ? <span className="detail-index">{indexLabel}</span> : null}
        {state.data.prev_id
          ? <a className="nav-arrow" title="Previous — ←" href={navHref(state.data.prev_id)} onClick={navClick(state.data.prev_id)}>&lsaquo; Prev</a>
          : <span className="nav-disabled">&lsaquo; Prev</span>}
        {state.data.next_id
          ? <a className="nav-arrow" title="Next — →" href={navHref(state.data.next_id)} onClick={navClick(state.data.next_id)}>Next &rsaquo;</a>
          : <span className="nav-disabled">Next &rsaquo;</span>}
        <button className="focus-btn" title="Focus mode — F" onClick={() => setFocusMode((v) => !v)}>{focusMode ? "Details" : "Focus"}</button>
      </div>

      {/* BODY GRID (Image Details.dc.html:345): two equal columns, always. */}
      <div className="placard">

        {/* PICTURE COLUMN (Image Details.dc.html:50-71): the frame, the file actions
            under it, the stars row under that -- centred vertically as a unit. */}
        <div className="placard-picture">
          {/* `morph` (App.jsx: the Lightbox is NOT mounted) gates the name: while the viewer
              sits on top of this record -- opened from the ⛶ link -- its stage image carries
              vt-reveal too, and the View Transitions spec SKIPS a transition whose old state
              has two elements under one name. Dropping the name here while the destination is
              mounted keeps exactly one per view, so the viewer's Details link still morphs
              back into this frame ("Where the Refit Broke" #6). */}
          <div className={"placard-frame" + (hasDims ? "" : " no-dims")} style={frameStyle}>
            {!mediaOk ? (
              <div className="placard-missing gd-note">{row.is_video === "1" ? "Video file not found on disk." : "Image file not found on disk."}</div>
            ) : row.is_video === "1" ? (
              <video controls autoPlay loop playsInline preload="metadata"
                poster={posterSrc || ("/thumbs/" + encodeURIComponent(row.poster_media_id || row.media_id) + ".jpg")}
                onError={() => setMediaOk(false)}>
                <source src={"/video-file/" + encodeURIComponent(row.media_id)} />
              </video>
            ) : (
              <a className="placard-media" href={"/full/" + encodeURIComponent(row.media_id)} target="_blank" rel="noreferrer">
                <img src={"/full/" + encodeURIComponent(row.media_id)} alt="" decoding="async" onError={() => setMediaOk(false)} />
              </a>
            )}
          </div>

          {/* FILE ACTIONS -- Image Details.dc.html:56-60 + :389-396 fileActions, drawn UNDER
              THE HERO in the picture column (the previous build had them in the record).
              Download is THE metal button (the DC's `metal` const = shell.css's shared
              .mgx-metal face); Delete locally is the red-outline danger chip. */}
          <div className="p-actions p-actions-primary">
            <a className="btn mgx-metal" title="Full-resolution file"
              href={"/full/" + encodeURIComponent(row.media_id) + "?dl=1"}>⬇ Download</a>
            {/* ☁ Publish -- cross-page hand-off (Image Details.dc.html:391), REAL since
                2026-08-06. Already-published rows say so instead of offering it twice;
                this row is the full catalog row, so artwork_id is right here. */}
            {(row.artwork_id || "").trim()
              ? <span className="btn is-off" title="Already on your PixAI profile — manage it from My Art">☁ Published</span>
              : <button className="btn" title="Publish this image to PixAI"
                  onClick={() => onPublish && onPublish(row.media_id)}>☁ Publish</button>}
            <button className="btn" title="Copy the full prompt"
              onClick={() => copy(promptText, "prompt")}>{copied === "prompt" ? "Copied!" : "⧉ Copy prompt"}</button>
            {/* ⇱ Upscale opens the float (Image Details.dc.html:393-394 / :143-189): the
                same fixed UpscalePanel the Lightbox uses, over the page -- never in flow,
                where it would have to squeeze the frame or scroll the document. The hook's
                close-on-navigate still governs it (useImageDetails.js, correction 2). */}
            <button className="btn" title="Upscale or Hires"
              onClick={() => upEl.current && upEl.current.open(row.media_id)}>⇱ Upscale</button>
            <button className="btn btn-danger" disabled={busy} title="Remove from your library only"
              onClick={deleteLocal}>Delete locally</button>
          </div>

          {/* STARS ROW -- Image Details.dc.html:61-70: the stars, the "N / 5" label, a
              spacer, then dims · date (the LOCAL day, gen/dates.js). */}
          <div className="p-stars-row">
            <Stars mediaId={row.media_id} rating={row.rating} onRate={handleRate} />
            <span className="rating-label">{row.rating ? row.rating + " / 5" : "unrated"}</span>
            <span className="sp" />
            <span className="p-stamp">{[dims, day].filter(Boolean).join(" · ")}</span>
          </div>
        </div>

        {/* RECORD COLUMN (Image Details.dc.html:73-140, recordColStyle): the ONLY thing
            that scrolls. Stays mounted under Focus (the DC fades it and collapses its
            column to 0px -- styles.css .focus-mode). */}
        <aside className="placard-record" ref={recordRef}>
          <div className="p-head">
            <p className="p-kicker">
              {(row.model_name || row.model_id || "—").toUpperCase()}
              {/* #34: · v3 · 2/4 -- dial-in version (from the loaded series steps) + batch
                  output (#33 row fields). Same pure helper as the card stamp. */}
              <span className="p-kicker-series">{seriesSuffix(row, (() => {
                const st = series && series.steps ? series.steps.find((s) => s.task_id === row.task_id) : null;
                return st ? { [row.task_id]: { v: st.v } } : {};
              })())}</span>
              {row.model_name ? <button className="gd-mini" onClick={() => onFilterByModel(row.model_name)}>find more</button> : null}
            </p>
            <h2 className="p-title">{headline}</h2>
            <div className="p-rule-track">
              <span className="p-rule" />
              <span className="p-glint" />
            </div>
          </div>

          {(tagList.length || collectionList.length) ? (
            <div className="p-tags">
              {tagList.map((t) => <span key={"t" + t} className="p-tag">{t}</span>)}
              {collectionList.map((c) => <span key={"c" + c} className="p-tag p-tag-shelf">{c}</span>)}
            </div>
          ) : null}

          {/* THE LEDGER -- Image Details.dc.html:90-100 + :375-387: exactly the DC's eleven
              rows, in the DC's order, with the DC's faces (mono / dim / warm) and its
              copyable ids. Every row renders, "—" when empty, as the DC shows its LoRAs. */}
          <div className="p-ledger">
            <LedgerRow label="Full prompt" value={row.prompt_full || row.prompt_preview} {...c} />
            <LedgerRow label="Natural" value={row.natural_prompt} dim {...c} />
            <LedgerRow label="Negative" value={row.negative_prompt} dim {...c} />
            <LedgerRow label="Model" value={row.model_name || row.model_id} warm {...c} />
            <LedgerRow label="LoRAs" value={row.loras} {...c} />
            <LedgerRow label="Seed" value={row.seed} mono copyKey="seed" {...c} />
            <LedgerRow label="Steps · CFG" value={stepsCfg} {...c} />
            <LedgerRow label="Sampler" value={row.sampler} {...c} />
            <LedgerRow label="Task ID" value={row.task_id} mono dim copyKey="task" {...c} />
            <LedgerRow label="Media ID" value={row.media_id} mono dim copyKey="mid" {...c} />
            <LedgerRow label="Filename" value={row.filename} mono dim copyKey="fname" {...c} />
          </div>

          {/* MORE DETAILS -- the full generation surface (issue #18) and the app's other
              extras the DC predates. Same row styling, folded closed by default so the
              record keeps the DC's shape; the open state is remembered (mg_details_more). */}
          {extra.length ? (
            <details className="p-more p-fact" open={moreOpen}
              onToggle={(e) => setMoreOpen(e.currentTarget.open)}>
              <summary className="p-more-sum">
                <span className="p-more-caret" aria-hidden="true">▸</span> More details
                <span className="p-more-n">{extra.length}</span>
              </summary>
              <div className="p-ledger">
                {extra.map((x) => (
                  <LedgerRow key={x.label} label={x.label} value={x.value} mono={x.mono} dim={x.dim} quiet {...c} />
                ))}
              </div>
            </details>
          ) : null}

          {/* RECORD ACTIONS -- Image Details.dc.html:102-106 + :397-403 recordActions, the
              second of the design's two groups, directly under the ledger.

              "Filter by model" was called "Find similar (model)" until B2 of the 2026-09-04
              Gallery Chrome handoff renamed it. It never did anything similar: it applies the
              model filter (onFilterByModel), exactly what the kicker's "find more" link
              applies, and it always has. Sharing the word "similar" with the ◈ strip below --
              which IS visual similarity -- made two unrelated controls read as a pair. The
              button does the same thing it always did, now under its own name. */}
          <div className="p-actions p-actions-record">
            <button className="btn" onClick={() => setEditingPrompt((v) => !v)}>✎ Edit prompt</button>
            {/* Send to Video: an image sends ITSELF as the first frame; a video sends its
                own SOURCE frame (source_media_id), never the clip -- a clip is not a valid
                i2v input. Hidden when a video has no recorded source frame (r2v shots). */}
            {(() => {
              const svid = row.is_video === "1" ? (row.source_media_id || "") : row.media_id;
              return svid ? (
                <button className="btn" title={row.is_video === "1"
                  ? "Send this video's source frame to the Video composer"
                  : "Send this picture to the Video composer as the first frame"}
                  onClick={() => { onClose(); onVideo && onVideo(svid, "/thumbs/" + encodeURIComponent(svid) + ".jpg"); }}>▶ Send to Video</button>
              ) : null;
            })()}
            {row.model_name ? <button className="btn" title="Every image from this model"
              onClick={() => onFilterByModel(row.model_name)}>Filter by model</button> : null}
            {/* task_id, not the batch COLUMN: --organize blanks `batch`, so the old gate hid the
                button (and its filter matched nothing) on every organized library. The server's
                batch filter now matches either column (issue #30). */}
            {row.task_id ? <button className="btn" title="The rest of this batch"
              onClick={() => onFilterByBatch(row.task_id)}>View batch</button> : null}
            <button className="btn" disabled={suggestBusy} title="Reverse a prompt out of this image"
              onClick={runSuggest}>{suggestBusy ? "Reading…" : "Suggest prompt"}</button>
          </div>

          {/* The prompt editor and the suggestions land right under the buttons that open
              them, INSIDE the scroller -- nothing outside the record may grow the page. */}
          {editingPrompt && (
            <div id="prompt-editor">
              <textarea rows={5} value={promptText} onChange={(e) => setPromptText(e.target.value)} />
              <div className="gd-row" style={{ marginTop: 8 }}>
                <button className="btn btn-primary" onClick={savePrompt}>Save</button>
                <button className="btn" onClick={() => setEditingPrompt(false)}>Cancel</button>
                <span id="save-status">{saveStatus}</span>
              </div>
            </div>
          )}

          {suggestions && (
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

          {/* LINEAGE (Image Details.dc.html:108-126) -- where this image came from and
              what came from it, REAL: batch siblings (same task_id) before "this",
              derivatives (edit/upscale/video, source_media_id) after. A linear strip
              like the DC draws it; siblings sit alongside "this" since they're from the
              same generation moment, not a chain. Hidden entirely when there's nothing
              to show (a lone original) -- no empty rail. */}
          {lineage && (lineage.parent || lineage.siblings.length || lineage.children.length) ? (
            <div className="p-lineage">
              <div className="p-lineage-head">
                <span className="k">LINEAGE</span>
                <span className="s">where this came from, and what came from it</span>
              </div>
              <div className="p-lineage-strip">
                {lineage.parent && (
                  <>
                    <button type="button" className="p-lin-chip" title={lineage.parent.title}
                      onClick={() => onNavigate(lineage.parent.media_id)}>
                      <img src={lineage.parent.thumb} alt="" />
                      <span className="cap">{lineage.parent.kind}</span>
                    </button>
                    <span className="p-lin-arrow">→</span>
                  </>
                )}
                {lineage.siblings.map((s) => (
                  <React.Fragment key={s.media_id}>
                    <button type="button" className="p-lin-chip" title={s.title}
                      onClick={() => onNavigate(s.media_id)}>
                      <img src={s.thumb} alt="" />
                      <span className="cap">batch</span>
                    </button>
                    <span className="p-lin-arrow">→</span>
                  </React.Fragment>
                ))}
                <div className="p-lin-chip this" title="This record">
                  <img src={"/thumbs/" + encodeURIComponent(row.media_id) + ".jpg"} alt="" />
                  <span className="cap">this</span>
                </div>
                {lineage.children.map((ch) => (
                  <React.Fragment key={ch.media_id}>
                    <span className="p-lin-arrow">→</span>
                    <button type="button" className="p-lin-chip" title={ch.title}
                      onClick={() => onNavigate(ch.media_id)}>
                      <img src={ch.thumb} alt="" />
                      <span className="cap">{ch.kind}</span>
                    </button>
                  </React.Fragment>
                ))}
              </div>
            </div>
          ) : null}

          {/* SESSION (#34, direction C) -- the dial-in series this image belongs to,
              task by task, drawn directly UNDER lineage as its sibling: LINEAGE is where
              this one image came from; SESSION is the whole sitting it's a step in. Only
              renders when the task is in a multi-task series (fetchSeries returns null for
              a singleton -- ~85% of the library -- so the panel, header included, never
              shows empty). The step whose task is THIS image's is lit with the sibling
              strip's lavender ring; consecutive seed-only rerolls collapse (groupSeriesSteps)
              so a 173-task marathon reads as ~a dozen tiles. Its own overflow-x scroller --
              the record column is the only thing that scrolls vertically. */}
          {series && series.steps && series.steps.length ? (
            <div className="p-session">
              <div className="p-session-head">
                <span className="k">⟲ SESSION</span>
                {series.title ? <span className="t" title={series.title}>{series.title}</span> : null}
                <span className="s">{series.count_tasks} tasks · {series.count_images} images</span>
              </div>
              <div className="p-session-strip">
                {groupSeriesSteps(series.steps, row.task_id).map((g, gi) => {
                  const key = g.kind === "rerolls" ? "r" + g.from + "-" + g.to : g.step.task_id;
                  return (
                    <React.Fragment key={key}>
                      {gi > 0 ? <span className="p-lin-arrow">→</span> : null}
                      {g.kind === "rerolls" ? (
                        <span className="p-ses-rerolls" title={g.count + " seed-only rerolls (v" + g.from + "–v" + g.to + ")"}>
                          …{g.count} rerolls…
                        </span>
                      ) : (
                        <button type="button"
                          className={"p-ses-step" + (g.step.task_id === row.task_id ? " this" : "")}
                          title={g.step.label}
                          onClick={() => onNavigate(g.step.first_media_id)}>
                          <span className="thumb">
                            <img src={"/thumbs/" + encodeURIComponent(g.step.first_media_id) + ".jpg"} alt="" loading="lazy" decoding="async" />
                            <span className="v">v{g.step.v}</span>
                          </span>
                          <span className="lab">{g.step.label}</span>
                        </button>
                      )}
                    </React.Fragment>
                  );
                })}
              </div>
            </div>
          ) : null}

          {/* ◈ SIMILAR (Image Details.dc.html:127-140) -- the eight closest by eye, INLINE
              in the record: the LINEAGE header idiom, a lavender door pushed right, then a
              horizontal strip of 78px tiles fading down the row as the DC draws them.
              Gated on the route's own availability signal (no CLIP index, empty index, no
              hits -> images: []): the whole section goes, header included -- never an empty
              rail, same as .p-lineage.

              B2 (2026-09-04): the mark is ◈, matching the tile hover door, the right-click
              row and the lightbox chip, and the door is ALWAYS offered when the strip
              renders rather than only past eight results. It used to read "see all N",
              which was only true when there were more than the eight shown; every door in
              the app now says the same thing -- ◈ Similar -- and pushes the same token into
              the library bar ("Where the Refit Broke" #6, finished). */}
          {similar.images.length ? (
            <div className="p-similar">
              <div className="p-similar-head">
                <span className="k">◈ SIMILAR</span>
                <span className="s">the closest by eye, not by model</span>
                <span className="sp" />
                {onSimilar ? (
                  <button type="button" className="p-seeall"
                    title={"The " + similar.images.length + " closest, in the library"}
                    onClick={() => onSimilar(row.media_id)}>
                    ◈ Similar
                  </button>
                ) : null}
              </div>
              <div className="p-similar-strip">
                {similar.images.slice(0, 8).map((it, k) => (
                  <button key={it.media_id} type="button" className="p-sim-tile"
                    style={{ "--sim-o": 0.9 - k * 0.06 }}
                    title={it.score != null ? "◈ " + it.score : "Open"}
                    onClick={() => onNavigate(it.media_id)}>
                    <img src={it.thumb} alt="" loading="lazy" decoding="async" />
                    {it.is_video === "1" ? <span className="vbadge">▶</span> : null}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {/* MORE -- the app's actions the DC never drew (it designs ten; the app
              carries more, each with real function). A quieter row, LAST, so the
              designed groups keep their shape; nothing here lost its handler.
              Delete from PixAI stays danger-styled and LAST (the irreversible one). */}
          <div className="p-actions p-actions-more">
            <a className="btn" href={"/full/" + encodeURIComponent(row.media_id)} target="_blank" rel="noreferrer">Open Full Size</a>
            {row.url ? <a className="btn" href={row.url} target="_blank" rel="noreferrer">Open on PixAI</a> : null}
            <button className="btn" onClick={() => window.print()}>🖨 Print</button>
            {row.is_video !== "1" && (
              <>
                <a className="btn" href={"/contact-sheet?ids=" + encodeURIComponent(row.media_id) + "&format=photo"} target="_blank" rel="noreferrer">4×6 photo</a>
                <a className="btn" href={"/contact-sheet?ids=" + encodeURIComponent(row.media_id) + "&format=strip"} target="_blank" rel="noreferrer">Photo strip</a>
              </>
            )}
            <button className="btn" onClick={() => { onClose(); onEdit(row.media_id); }}>✧ Edit this</button>
            {/* Remix (issue #4, extended to video by SCOPE_2026-08-17 §2): the full
                recipe into the Generate drawer -- an image's prompt/negative/size/
                steps/cfg/seed/model + LoRAs into the Image tab, a video's engine/
                duration/mode/camera/audio/prompt into the Video tab. Prefill only;
                the drawer routes by kind (GenerateDrawer.prefillRun). */}
            <button className="btn" title={row.is_video === "1"
              ? "Load this video's full recipe into the Video composer"
              : "Load this picture's full recipe into Generate"}
              onClick={() => { onClose(); onRemix && onRemix(row.media_id); }}>↺ Remix</button>
            {/* Rebuild poster (videos only): re-extract the thumbnail from the file. For a
                clip whose cached poster is wrong -- a fade-in that was thumbnailed black --
                without a full --rebuild-thumbs pass. (owner, 2026-08-22) */}
            {row.is_video === "1" ? (
              <button className="btn" disabled={posterBusy}
                title="Re-extract this video's thumbnail from the file"
                onClick={async () => {
                  setPosterBusy(true);
                  const d = await rebuildPoster(row.media_id);
                  setPosterBusy(false);
                  if (window.Toast) window.Toast.show(d && d.ok
                    ? { kind: "ok", title: "Poster rebuilt" }
                    : { kind: "err", title: "Couldn't rebuild the poster", msg: (d && d.error) || "" });
                  if (d && d.ok && d.thumb) setPosterSrc(d.thumb);
                }}>{posterBusy ? "Rebuilding…" : "🖼 Rebuild poster"}</button>
            ) : null}
            {state.data.can_delete_cloud && row.task_id ? (
              <button className="btn btn-danger" disabled={busy} onClick={deleteCloud}>Delete from PixAI</button>
            ) : null}
          </div>
        </aside>
      </div>

      {/* Unconditional render -- see useImageDetails.js's header comment
          (correction 1): <UpscalePanel>'s own .open CSS shows/hides it, not
          conditional React mounting. The hook drives upEl.current.close() on
          navigate/unmount; the ⇱ Upscale chip above calls .open(). NOT `inline`:
          the DC's Upscale is a fixed float over the page (Image Details.dc.html:
          143-146), the Lightbox's own flyout -- the in-flow mount had nowhere to
          go on a page that never scrolls. */}
      <UpscalePanel ref={upEl} />
    </div>
  );
}
