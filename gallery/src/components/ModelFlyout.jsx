import React, { useEffect, useRef, useState } from "react";

/* The model/LoRA browser: the SAME two <mg-model-picker> mounts the classic
   drawer and the Loom use -- base (single, market) and lora (multi, market).

   TWO contracts the review caught the first cut breaking:
   1. A `multi` picker's mg-pick detail is {model, selected}, NOT the raw row --
      a deliberate shape difference. The single (base) picker sends the row.
   2. Listeners bind ONCE at mount, so they must call through refs that always
      point at the current handlers; a captured closure goes stale the moment
      state changes and silently breaks toggle-to-remove.
   The host must also call deselect() on every chip-removal path or the picker
   card stays lit (the exact bug that API exists for). */
export default function ModelFlyout({
  open, kind, setKind, baseType, onBasePick, onLoraPick, onClose, deselectRef,
}) {
  const baseHost = useRef(null);
  const loraHost = useRef(null);
  const [mounted, setMounted] = useState(false);
  // refs re-pointed every render -> the once-bound listeners never go stale
  const baseCb = useRef(onBasePick);
  const loraCb = useRef(onLoraPick);
  baseCb.current = onBasePick;
  loraCb.current = onLoraPick;

  useEffect(() => {
    if (!open || mounted) return;
    const base = document.createElement("mg-model-picker");
    base.setAttribute("kind", "base");
    base.setAttribute("market", "");
    base.addEventListener("mg-pick", (e) => baseCb.current(e.detail));
    baseHost.current.appendChild(base);

    const lora = document.createElement("mg-model-picker");
    lora.setAttribute("kind", "lora");
    lora.setAttribute("multi", "");
    lora.setAttribute("market", "");
    // multi contract: detail = {model, selected}
    lora.addEventListener("mg-pick", (e) => {
      const d = e.detail || {};
      loraCb.current(d.model, d.selected);
    });
    loraHost.current.appendChild(lora);

    if (deselectRef) deselectRef.current = (modelId) => lora.deselect && lora.deselect(modelId);
    setMounted(true);
  }, [open, mounted, deselectRef]);

  // keep the LoRA picker's architecture filter following the chosen base
  useEffect(() => {
    const lora = loraHost.current && loraHost.current.firstChild;
    if (lora) {
      if (baseType) lora.setAttribute("base-type", baseType);
      else lora.removeAttribute("base-type");
    }
  }, [baseType, mounted]);

  return (
    <div className={"mfly" + (open ? " open" : "")} aria-hidden={!open}>
      <div className="mfly-head">
        <button className={"card" + (kind === "base" ? " on" : "")} onClick={() => setKind("base")}>Models</button>
        <button className={"card" + (kind === "lora" ? " on" : "")} onClick={() => setKind("lora")}>LoRAs</button>
        <span className="sp" />
        <button className="card" onClick={onClose} title="Esc">✕</button>
      </div>
      <div ref={baseHost} style={{ display: kind === "base" ? "" : "none" }} />
      <div ref={loraHost} style={{ display: kind === "lora" ? "" : "none" }} />
    </div>
  );
}
