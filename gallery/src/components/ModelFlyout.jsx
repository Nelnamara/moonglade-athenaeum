import React from "react";
import ModelPicker from "./ModelPicker.jsx";

/* The model/LoRA browser: the base (single, market) and lora (multi, market) pickers the
   drawer and the Loom share. Since 2026-08-08 these are the React <ModelPicker> component
   (was the <mg-model-picker> custom element). Selection is CONTROLLED here: the host passes
   `value` (the chosen base row) and `selected` (the LoRA entries), so a LoRA chip removed by
   the host un-lights its card automatically -- no deselect() plumbing. Both pickers stay
   mounted and toggle display, so each keeps its own last search across a tab switch. */
export default function ModelFlyout({
  open, kind, setKind, baseType, value, selected, onBasePick, onLoraPick, onClose,
}) {
  return (
    <div className={"mfly" + (open ? " open" : "")} aria-hidden={!open}>
      <div className="mfly-head">
        <button className={"card" + (kind === "base" ? " on" : "")} onClick={() => setKind("base")}>Models</button>
        <button className={"card" + (kind === "lora" ? " on" : "")} onClick={() => setKind("lora")}>LoRAs</button>
        <span className="sp" />
        <button className="card" onClick={onClose} title="Esc">✕</button>
      </div>
      <div style={{ display: kind === "base" ? "" : "none" }}>
        <ModelPicker kind="base" market visible={open && kind === "base"}
          value={value} onPick={onBasePick} />
      </div>
      <div style={{ display: kind === "lora" ? "" : "none" }}>
        <ModelPicker kind="lora" multi market baseType={baseType} visible={open && kind === "lora"}
          selected={selected || []} onToggle={onLoraPick} />
      </div>
    </div>
  );
}
