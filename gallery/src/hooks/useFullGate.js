import { useCallback, useEffect, useState } from "react";
import { apiHeadSize } from "../api.js";
import { humanBytes } from "../lib/phoneCore.js";

/* "Tap to load full size" (Session Q, Q7): while Data saver acts, a still opens as its 256 px thumbnail
   and the full file waits for a tap. This hook is the gate's whole state, shared by the Lightbox and the
   record so the two cannot disagree about it.

     const { gated, size, load } = useFullGate(mediaId, active)

   `active` is "the saver acts AND this is a still" (a clip has no gate; it just does not autoplay).
   `gated` is true until the picture has been loaded once THIS SESSION -- the loaded set is module-level,
   so closing the viewer and opening the same picture again does not ask twice, and the browser's own
   cache already holds the file. `size` is "2.4 MB" from a HEAD (headers only; "" while unknown), read
   only for a picture that is waiting on the tap. `load` is the tap. Nothing here reaches the network for
   a picture that is not gated, and nothing writes anywhere: the loaded set lives in memory only. */

const LOADED = new Set();
const SIZES = new Map();          // media_id -> bytes (0 = unknown), so a revisit does not ask again

export default function useFullGate(mediaId, active) {
  const [, bump] = useState(0);
  const gated = !!active && !!mediaId && !LOADED.has(mediaId);
  useEffect(() => {
    if (!gated || SIZES.has(mediaId)) return undefined;
    let dead = false;
    apiHeadSize("/full/" + encodeURIComponent(mediaId)).then((n) => {
      SIZES.set(mediaId, n);
      if (!dead) bump((v) => v + 1);
    });
    return () => { dead = true; };
  }, [gated, mediaId]);
  const load = useCallback(() => { LOADED.add(mediaId); bump((v) => v + 1); }, [mediaId]);
  return { gated, size: humanBytes(SIZES.get(mediaId)), load };
}
