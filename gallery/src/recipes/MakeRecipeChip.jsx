import React, { useEffect, useState } from "react";
import { recipesApi } from "./recipesApi.js";
import { openCreator } from "./recipesStore.js";

/* ⁂ Make a recipe (K decision 4) -- on the Lightbox's action row between ◈ Similar and
   ⇱ Upscale, and on Lightbox Mobile's. It shows only for a picture whose model takes
   recipes: one cached /features read per model version, answered by
   /api/recipes/from-image?check=1 and remembered here per picture for the page's life.
   A click reads the picture's record (model, LoRAs with weights and trigger words, prompt)
   and opens the creator on step 2 with the picture as showcase 1. The category is never
   guessed. Nothing is written anywhere by opening it. */
const _capable = new Map();   // media_id -> true | false

export default function MakeRecipeChip({ mediaId, isVideo, className, phone }) {
  const [ok, setOk] = useState(() => (mediaId ? _capable.get(String(mediaId)) : false));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  useEffect(() => {
    setErr("");
    if (!mediaId || isVideo) { setOk(false); return undefined; }
    const key = String(mediaId);
    if (_capable.has(key)) { setOk(_capable.get(key)); return undefined; }
    setOk(false);
    let live = true;
    const t = setTimeout(() => {
      recipesApi.fromImage(key, true).then((d) => {
        const yes = !!(d && !d.error && d.capable);
        if (d && !d.error) _capable.set(key, yes);
        if (live) setOk(yes);
      });
    }, 180);
    return () => { live = false; clearTimeout(t); };
  }, [mediaId, isVideo]);

  if (!ok) return null;
  const go = () => {
    if (busy) return;
    setBusy(true); setErr("");
    recipesApi.fromImage(String(mediaId), false).then((d) => {
      setBusy(false);
      if (!d || d.error || !d.capable) { setErr((d && (d.error || d.why)) || "Couldn't read this picture's record"); return; }
      openCreator({ prefill: { fromImage: d }, fromImage: true }, { phone: !!phone });
    });
  };
  return (
    <button type="button" className={className} onClick={go} disabled={busy}
      title={err || "Make a recipe from this picture's model, LoRAs and prompt"}>
      {busy ? "⁂ Reading…" : err ? "⁂ Couldn't read it" : "⁂ Make a recipe"}
    </button>
  );
}
