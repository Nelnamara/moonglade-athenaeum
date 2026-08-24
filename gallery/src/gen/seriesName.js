// The dial-in name suffix appended to a card stamp / Details head: " · v3 · 2/4".
//
// TWO independent facts, each shown only when known (#34):
//   - the SESSION version: which task this is within its dial-in series (v3 of the run).
//     Comes from /api/series' by_task; absent for the ~85% of images not in a multi-task
//     series -> no v part.
//   - the BATCH output: which output of its own task (2 of 4). Comes from the row's
//     batch_index/batch_size (#33), PixAI's own permanent numbering; blank on non-batch
//     outputs (edits, upscales, videos, imports) -> no k/N part.
// Either, both, or neither may show. A pure function so the card and Details share it and
// it is testable without a DOM.

// n/N -> 1-based "k/N" when the row carries a batch index+size; "" otherwise.
export function batchLabel(row) {
  const i = row && row.batch_index, s = row && row.batch_size;
  if (i === undefined || i === null || i === "" || !s) return "";
  const idx = parseInt(i, 10), size = parseInt(s, 10);
  if (!(size > 0) || !(idx >= 0) || idx >= size) return "";   // never a nonsense k/N
  return (idx + 1) + "/" + size;
}

// The full suffix for a grid card: reads the page's series-by-task map (may be empty).
export function seriesSuffix(row, seriesByTask) {
  const parts = [];
  const s = row && row.task_id && seriesByTask ? seriesByTask[row.task_id] : null;
  if (s && s.v) parts.push("v" + s.v);
  const b = batchLabel(row);
  if (b) parts.push(b);
  return parts.length ? " · " + parts.join(" · ") : "";
}
