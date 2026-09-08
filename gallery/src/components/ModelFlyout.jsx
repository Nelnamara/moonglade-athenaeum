import React from "react";
import ModelPicker from "./ModelPicker.jsx";

/* The model/LoRA browser: the base (single, market) and lora (multi, market) pickers the
   drawer and the Loom share. Since 2026-08-08 these are the React <ModelPicker> component
   (was the <mg-model-picker> custom element). Selection is CONTROLLED here: the host passes
   `value` (the chosen base row) and `selected` (the LoRA entries), so a LoRA chip removed by
   the host un-lights its card automatically -- no deselect() plumbing. Both pickers stay
   mounted and toggle display, so each keeps its own last search across a tab switch.

   THE PHONE'S HEAD ENDS IN A DONE BUTTON (owner ruling, 2026-09-07: "Done button
   matches pixai"). A base pick closes the sheet by itself (CreateMobile's onBasePick),
   but a LoRA pick only TOGGLES -- multi-select is the whole point -- so the LoRA sheet
   never closed on its own and read as stuck. Desktop is untouched: it keeps the ✕ and
   its Esc, which the phone has no key for. `phone` is a PROP from the caller, not a
   media query in here -- CreateMobile is the phone mount and GenerateDrawer is the
   desktop one, so the two mounts already know which they are. */

/* The label, in one place. PixAI's own LoRA dialog ends its "Selected LoRAs" pane with
   one full-width button that reads "Confirm selection" (captured from the site, read-only,
   2026-09-07; moonglade-internal/probes/PROBE_2026-09-07_lora-picker-wording-and-refresh.md).
   The owner's ruling was "Done button matches pixai", so that is the word. */
export const LORA_SHEET_DONE_LABEL = "Confirm selection";

export default function ModelFlyout({
  open, kind, setKind, baseType, value, selected, onBasePick, onLoraPick, onClose,
  phone = false,
}) {
  return (
    <div className={"mfly" + (open ? " open" : "")} aria-hidden={!open}>
      <div className="mfly-head">
        <button className={"card" + (kind === "base" ? " on" : "")} onClick={() => setKind("base")}>Models</button>
        <button className={"card" + (kind === "lora" ? " on" : "")} onClick={() => setKind("lora")}>LoRAs</button>
        <span className="sp" />
        {phone ? (
          <button type="button" className="glm-primary mfly-done" onClick={onClose}>
            {LORA_SHEET_DONE_LABEL}
          </button>
        ) : (
          <button className="card" onClick={onClose} title="Esc">✕</button>
        )}
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
