/* Train a LoRA — the two small rules both train panels (TrainOverlay, TrainMobile) share with
   the server (SCOPE_2026-09-26 E7). Pure, so loom/test/train-core.test.js can hold them. */

/* PixAI's own trigger-word normalizer, in its order (the train page's he()): runs of CR/LF
   become ", ", any whitespace run one space, a run of commas with spaces between them one
   ", ", lowercase, then leading and trailing commas and whitespace stripped. The server's
   core.normalize_trigger_words is the same five steps, and its 256 / 30 limits are measured on
   this string's `length` (UTF-16 code units, as the site measures it) -- so the panel's counter
   shows normalizeTrigger(text).length, the number the server will actually check. */
export function normalizeTrigger(text) {
  return String(text ?? "")
    .replace(/[\r\n]+/g, ", ")
    .replace(/\s+/g, " ")
    .replace(/,\s*(?:,\s*)+/g, ", ")
    .toLowerCase()
    .replace(/^[,\s]+|[,\s]+$/g, "");
}

/* The confirm's `accept_credit_cost`: nothing for a run the preview called free; otherwise the
   AMOUNT the ticked box named (`true` only when the preview could not quote one). The server
   refuses a number that is no longer the run's price (409), so an acknowledgement is always for
   the price the user read -- never for a base picked after the quote. */
export function acceptCostField(ask, accepted) {
  if (!ask || ask.is_free) return {};
  if (!accepted) return { accept_credit_cost: false };
  return { accept_credit_cost: typeof ask.price === "number" ? ask.price : true };
}
