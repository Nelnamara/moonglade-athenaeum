/* costBadgeCore -- the CostBadge's verdict on one /api/price response, as pure functions.

   components/CostBadge.jsx turns a parsed response into one of its honesty states with
   classify(); this is that rule, moved out of the component so it can be tested directly (a
   static render cannot push a price into the badge's handle). The badge is still the only
   caller, and still the one place the suite words a cost. No React, no DOM, no network. */

// The SHORT case (issue #15): the server matched a card but the account holds fewer tickets
// than this job costs -> nothing is attached, the FULL price is charged. The server's
// `card_short` flag (= matched and NOT card_covers) is THE verdict, and `free` (= card_covers)
// stays authoritative the other way: a response is never short when the server said free.
// This used to also re-derive held<needed as a "belt" that could override free:true -- but
// cards_held/cards_needed and card_short shipped in the same commit (no response ever carried
// the counts without the flag), and the belt made THIS badge disagree with the Loom's
// priceIsShort (which defers to free) on the identical response: two spend surfaces, two
// verdicts, one page (review 2026-08-16). One rule now, same as loom-core: server decides.
export function isShort(d) {
  if (!d || d.free) return false;
  return d.card_short === true;
}

// The badge's price-push branch logic, verbatim: resp === null/undefined means THE CHECK ITSELF
// FAILED (fetch threw, JSON unparseable) — the could-not-verify state on purpose. A host that
// wants "not priced yet" clears the badge instead. Conflating the two is the bug this exists to
// prevent.
export function classify(resp) {
  const d = (resp && typeof resp === "object") ? resp : null;
  if (!d) return { state: "error", note: "", msg: "", raw: null };
  if (d.error) return { state: "error", note: "", msg: String(d.error), raw: d };
  // `free` and `card_short` are mutually exclusive on the wire (free = card_covers, short =
  // matched-and-not-covered), and isShort() defers to free -- so a free response renders free
  // and a short one can never reach this branch. FREE while the submit charges was the exact
  // bug of issue #15; the guard is the server verdict, read once, the same way loom-core reads it.
  if (d.free && !isShort(d)) return { state: "free", note: "", msg: "", raw: d };
  // Checked BEFORE `note` so a response carrying both can never hide a real cost behind a hint.
  if (d.cost != null && isFinite(Number(d.cost))) return { state: "paid", note: "", msg: "", raw: d };
  if (d.note) return { state: "idle", note: String(d.note), msg: "", raw: d };
  // free:false, cost:null, no note, no error — nothing was priced. Honest answer is "we don't
  // know", NOT a neutral silence and certainly not "0 credits".
  return { state: "error", note: "", msg: "", raw: d };
}
