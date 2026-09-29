import { askPicker } from "../components/PickerHost.jsx";

/* Session H decision 1: "+ add" on a context slot -- history · gallery · upload through the
   one picker (PickerHost / GalleryPicker: the catalog, newest first, with its ＋ Upload). Resolves
   to {media_id, thumb, w, h, measure} or null. `measure` is a promise of {w, h} for a picture
   whose size the picker could not say (an upload's object URL, or a catalog row without a
   size): the dock's Auto frame reads @image1's own aspect. */
export async function pickContextImage() {
  const m = await askPicker({ type: "image" });
  if (!m || !m.media_id || m.is_video) return null;
  const w = Number(m.w) || 0, h = Number(m.h) || 0;
  const img = { media_id: String(m.media_id), thumb: m.thumb || "", w, h };
  // An upload's thumb is the file's own object URL (GalleryPicker's doUpload), the full picture.
  const uploaded = /^blob:/.test(String(m.thumb || ""));
  if (!(w > 0 && h > 0)) img.measure = measureImage(uploaded ? m.thumb : "/full/" + m.media_id);
  return img;
}

export function measureImage(src) {
  return new Promise((resolve) => {
    if (!src || typeof Image === "undefined") { resolve(null); return; }
    const im = new Image();
    im.onload = () => resolve(im.naturalWidth > 0 ? { w: im.naturalWidth, h: im.naturalHeight } : null);
    im.onerror = () => resolve(null);
    im.src = src;
  });
}
