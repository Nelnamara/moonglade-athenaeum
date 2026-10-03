/* =========================================================================
   loom-frames-core.js — FRAMES SPLICED BEFORE 3.15.0 (GitHub #62), as pure views.

   3.15.0 writes a thumbnail when a splice uploads a frame, but a frame spliced earlier is a
   PixAI media id in no catalog with no thumbs/<id>.jpg, and /thumbs/<id>.jpg never fetches on
   a miss: the board card, Deep Focus and the drawer's frame box drew a broken picture. On
   opening a board the Loom posts the board's frame ids ONCE per session to
   POST /api/loom/frame-thumbs, which fills a missing thumbnail from PixAI (two reads, nothing
   that spends) and answers {have, fetched, gone}. A filled one is re-drawn with a cache-busting
   suffix; one PixAI could not give back is drawn as FRAME_GONE_TEXT instead of a broken image.

   The per-session answer is the "fix": {gone: Set of media ids, bust: {media id: stamp}}.
   Same discipline as loom-core.js: NO React, no DOM, no window, no fetch, no timers, and no
   imports (loom/test/loom-no-auto-render.test.js pins that). Reading a board writes nothing.
   ========================================================================================= */

/** The route's own cap (moonglade_gallery.LOOM_FRAME_THUMBS_MAX): ids are posted in chunks of it. */
export const FRAME_THUMBS_MAX = 60;

/** What a frame slot says when PixAI could not give the frame back (the owner's call, 2026-10-02). */
export const FRAME_GONE_TEXT = "Frame not on this machine. Splice again.";

const PIXAI_ID = /^\d{1,32}$/;

/** The media ids of the board's open and close frames that are PixAI ids, de-duplicated, in
 *  board order. Only frames drawn from /thumbs/<id>.jpg count: a frame whose picture the thumbs
 *  store holds (thumbId) never was broken, and an imported `local_` picture is not PixAI's.
 *  Cast, references, anchors and take snapshots are not frames on the board. */
export const collectFrameIds = (project) => {
  const out = [];
  const seen = new Set();
  const acts = project && Array.isArray(project.acts) ? project.acts : [];
  acts.forEach((a) => ((a && Array.isArray(a.cards)) ? a.cards : []).forEach((c) => {
    [c && c.openFrame, c && c.closeFrame].forEach((f) => {
      if (!f || f.thumbId) return;
      const id = String(f.mediaId == null ? "" : f.mediaId).trim();
      if (!PIXAI_ID.test(id) || seen.has(id)) return;
      seen.add(id);
      out.push(id);
    });
  }));
  return out;
};

/** No answer yet: every frame draws as it always did. */
export const emptyFrameFix = () => ({ gone: new Set(), bust: {} });

/** The fix with one route answer folded in (a new object; the old one is never touched). */
export const applyFrameThumbs = (fix, ans, stamp) => {
  const f = fix || emptyFrameFix();
  const a = ans || {};
  const gone = new Set(f.gone || []);
  (a.gone || []).forEach((id) => gone.add(String(id)));
  const bust = { ...(f.bust || {}) };
  (a.fetched || []).forEach((id) => { bust[String(id)] = stamp; });
  return { gone, bust };
};

/** Is this frame one PixAI could not give back? (A picture in the thumbs store never is.) */
export const frameGone = (f, fix) => !!(f && !f.thumbId && f.mediaId && fix && fix.gone && fix.gone.has(String(f.mediaId)));

/** What a frame slot draws: the thumbs store's picture, else the shared thumbnail (re-asked for
 *  once it was filled), else nothing -- and nothing for a frame that is gone, so the slot's
 *  placeholder draws (with FRAME_GONE_TEXT) instead of a broken image. */
export const frameThumbSrc = (f, thumbs, fix) => {
  if (f && f.thumbId) return (thumbs || {})[f.thumbId];
  if (!f || !f.mediaId) return null;
  if (frameGone(f, fix)) return null;
  const v = fix && fix.bust ? fix.bust[String(f.mediaId)] : undefined;
  return "/thumbs/" + f.mediaId + ".jpg" + (v != null ? "?v=" + v : "");
};
