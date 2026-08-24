import { useCallback, useEffect, useRef, useState } from "react";
import {
  EDIT_DEFAULTS, EDIT_PRICE_KEY_SKIP, buildEditPayload, editGate, switchEditModel,
} from "./editCore.js";
import { submitTask, useResultLines } from "./submitTask.js";
import usePriceProbe from "./usePriceProbe.js";

/* Create tab, Edit mode's own generation hook -- the mobile-shell counterpart
   to useGenerate.js, lifted for the IDENTICAL reason (see AppMobile.jsx's own
   header comment on why useGenerate/useLibrary/cmode are all instantiated
   THERE and spread into CreateMobile.jsx as props): CreateMobile.jsx only
   renders while AppMobile's outer tab === "create"
   ({tab === "create" && <CreateMobile .../>}), so any state kept locally
   inside it resets every time the bottom nav visits Gallery or Control and
   comes back. A half-typed instruction, a picked source image, a stack of
   reference thumbnails -- exactly the kind of draft useGenerate() already
   protects on the Image side -- would otherwise vanish on every accidental
   tab bounce. This hook is instantiated ONCE in AppMobile.jsx and its return
   value is spread into CreateMobile.jsx the same way `gen` already is.

   This is NOT useGenerate() reused for a second purpose: Edit's payload
   shape, its submit gate, and its defaults come from editCore.js
   (buildEditPayload / editGate / switchEditModel / EDIT_DEFAULTS) -- the
   SAME presentation-agnostic functions EditTab.jsx (desktop) calls.
   genCore.js's buildPayload/goGate are Image-only and do not apply to an
   edit_model/source/refs/instruction/preset payload at all.

   The price probe below is a DELIBERATE separate INSTANCE of the shared
   gen/usePriceProbe.js (its own debounce/seq/verdict, its own costRef supplied
   by the caller) -- ported verbatim from EditTab.jsx's own header comment on
   why: "sharing them with the image tab's is exactly what caused the classic's
   historical no-price-on-?edit= bug." AppMobile.jsx passes a second, dedicated
   costRef here, distinct from Image mode's. */
export default function useEditGenerate({ costRef }) {
  const [s, setS] = useState(EDIT_DEFAULTS);
  const [busy, setBusy] = useState(false);
  const [results, openLine] = useResultLines();
  const busyRef = useRef(false);

  const set = useCallback((patch) => setS((old) => ({ ...old, ...patch })), []);

  /* The SAME buildEditPayload the submit sends, so a quote can never describe a
     different edit than what goes out. Idle when there is no source: a plain
     clear() back to the badge's own hint, which is a verdict -- editGate() is
     what refuses the submit there, and it must stay reachable. */
  const build = useCallback(() => {
    const p = buildEditPayload(s);
    return { payload: p, idle: (s.source || "").trim() ? null : true };
  }, [s]);
  const probe = usePriceProbe({ build, costRef, skipKeys: EDIT_PRICE_KEY_SKIP });
  /* Exposed so the presentation layer's mount effect can prime the badge the
     instant its <CostBadge> exists -- identical contract to useGenerate.js's own
     refreshPrice(). */
  const refreshPrice = probe.refresh;
  const priceOk = probe.canSubmit;

  // Re-prices on ANY field change, matching EditTab.jsx's own effect deps
  // exactly. BEHAVIOUR CHANGE 2026-08-22: the instruction is in the probe's
  // identity skip (EDIT_PRICE_KEY_SKIP), so a keystroke now short-circuits
  // instead of blanking the badge and disabling ✦ Edit for 250ms + one RTT --
  // an edit's price cannot move on its text. The dep list is left broad because
  // the short-circuit makes the extra calls free.
  useEffect(() => { refreshPrice(); }, [s, refreshPrice]); // eslint-disable-line react-hooks/exhaustive-deps

  /* Switching model keeps the knobs the new model can take, corrects the rest
     (`clamp` names what changed -- desktop shows it inline, DC 1517-1519; here
     the mobile Advanced sheet simply reads the corrected values) and trims refs
     over the new cap -- editCore.js's own switchEditModel, same as desktop. */
  const chooseModel = useCallback((next) => {
    const { next: patched, notice } = switchEditModel(s, next);
    setS(patched);
    if (notice && window.Toast) window.Toast.show({ kind: "err", ...notice });
  }, [s]);

  const addRef = useCallback((media) => {
    if (!media || !media.media_id) return;
    setS((old) => ({ ...old, refs: old.refs.concat([{ media_id: media.media_id, thumb: media.thumb }]) }));
  }, []);
  const dropRef = useCallback((i) => {
    setS((old) => ({ ...old, refs: old.refs.filter((_, k) => k !== i) }));
  }, []);

  const gate = editGate(s);

  /* NO retry, body-keyed errors, real Jobs tracking -- submitTask.js's own
     contract, the SAME shared path /api/generate and /api/fix use. */
  const run = useCallback(async () => {
    if (busyRef.current || editGate(s)) return;
    // PAYLOAD IDENTITY gate -- the button is already disabled on it; this is the
    // click that slips through a stale render (a keyboard Enter needs no repaint).
    if (!priceOk) { refreshPrice(); return; }
    busyRef.current = true;
    setBusy(true);
    const emit = openLine("Submitting…");
    await submitTask("/api/edit", buildEditPayload(s), { label: "Edited", emit });
    busyRef.current = false;
    setBusy(false);
    // The submit DEBITED credits or a card; the payload is byte-identical, so only
    // a FORCED re-price gets past the short-circuit.
    refreshPrice({ force: true });
  }, [s, openLine, priceOk, refreshPrice]);

  return { s, set, busy, results, chooseModel, addRef, dropRef, run, refreshPrice, gate,
           canSubmit: priceOk };
}
