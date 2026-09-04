import { useEffect, useState } from "react";

/* The rotating header tagline -- the DC's "same rotating set as the gallery
   banner" note on Login.dc.html (its tagline mechanic is explicitly the same
   one Banner.jsx already had). Extracted here (2026-08-02) so Login can reuse
   it verbatim instead of a second copy drifting from the original. */
export const FLAVOURS =
  "a library against the Void|the archive remembers|what the moon keeps|every dream, kept|a light in the Nightmare|every spark, embraced|woven, not lost|the vigil never sleeps";

export default function useFlavour(flavours, buildStamp) {
  const lines = String(flavours || FLAVOURS).split("|").map((t) => t.trim()).filter(Boolean);
  const [i, setI] = useState(0);
  const [fading, setFading] = useState(false);
  const [version, setVersion] = useState(false);
  useEffect(() => {
    if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let swap;
    const id = setInterval(() => {
      setFading(true);
      swap = setTimeout(() => { setI((n) => n + 1); setFading(false); }, 500);
    }, 9000);
    return () => { clearInterval(id); clearTimeout(swap); };
  }, []);
  // click reveals the real build for 3s -- boot.build_stamp VERBATIM and nothing
  // else (version + short git sha; _build_stamp() in moonglade_gallery.py owns the
  // format). The "next · build " prefix retired with the /next codename (issue #51):
  // the reveal is the version, not a pilot name. (The DC hardcodes a version; the
  // real app has the true stamp in boot.)
  useEffect(() => {
    if (!version) return;
    const t = setTimeout(() => setVersion(false), 3000);
    return () => clearTimeout(t);
  }, [version]);
  return {
    text: version ? (buildStamp || "?") : lines[i % lines.length],
    fading,
    alt: i % 2 === 1,
    reveal: () => setVersion(true),
  };
}
