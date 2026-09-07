/* THE NUMBERS IN THE DELETE-FROM-PIXAI DIALOG (owner, 2026-09-07; corrected the same day).

   The live check made this dialog carry three quantities instead of one, and the first
   build let them contradict each other: the headline subtracted the images PixAI has
   already dropped ("4 files ... will be deleted"), the pre-existing clause underneath
   still counted the FULL batch membership ("You picked 2; the other 3 come with their
   batches" -- 2 + 3 = 5, not 4), and the sentence after that called the already-gone
   files "of them", i.e. among the four the headline had just promised were going.

   They are derived HERE, once, so the prose can be written against numbers that are known
   to reconcile rather than against three separate readings of `totals`:

     willDelete + alreadyGone === inBatches          (by construction, below)
     picked     + alongside   === inBatches          (the server's own arithmetic:
                                                      unselected = total_media + local_only
                                                      - len(sel_rows))

   `totals` itself is deliberately UNCHANGED in meaning on the server -- it is the whole
   blast radius, membership and all -- so this is the one place that turns it into what the
   dialog says.

   Defensive on every field: an older server answers /api/delete-preview without
   `already_gone` at all, and the dialog must still open and still be true. */

/**
 * @param {object} totals       the route's `totals` block
 * @param {number} alreadyGone  the route's top-level `already_gone`
 */
export function cloudDeleteCounts(totals, alreadyGone) {
  const t = totals || {};
  const n = (v) => {
    const x = Number(v);
    return Number.isFinite(x) && x > 0 ? Math.floor(x) : 0;
  };
  const inBatches = n(t.media);
  // Clamped to the membership: a count of "gone" larger than what is there would drive the
  // headline negative, and no answer from the server can make that a true sentence.
  const gone = Math.min(inBatches, n(alreadyGone));
  return {
    tasks: n(t.tasks),
    inBatches,                        // every file the button touches, gone ones included
    alreadyGone: gone,                // PixAI dropped these already; they stay in the backup
    willDelete: inBatches - gone,     // the headline
    picked: n(t.selected),            // what the owner actually selected
    alongside: n(t.unselected),       // siblings that come with the batch
    localOnly: n(t.local_only),       // imports with no PixAI task at all
  };
}

export default cloudDeleteCounts;
