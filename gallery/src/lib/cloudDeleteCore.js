/* WHAT "DELETE FROM PIXAI" DOES WITH THE PREVIEW'S ANSWER (lifted out of ActionsMenu.jsx's
   askCloud, unchanged, so the decision can be driven by a test instead of read as text).

   The preview (api.js deletePreview) answers three ways: the preview itself (it has `totals`),
   an {error} -- the 15s timeout above the server's own 12s ceiling is the one that says so in
   words -- or null when the route answered something unusable. Only the first opens the
   blast-radius dialog. The other two are a failure, not an empty preview: they fall back to
   the prose-only confirm (verbatim from the classic flow) rather than a dead click, a silent
   skip or a dialog with nothing in it, and the reason -- when there is one -- is said out loud
   in that confirm. Nothing is deleted unless that confirm says yes; `deleteCloud` still asks
   for the typed DELETE itself.

   Pure apart from what it is handed: ActionsMenu passes the real deletePreview, its own dialog
   opener, window.confirm and its deleteCloud. */

/** The prose-only confirm shown when no preview could be built. `error` is the reason the
    preview gave, if any. */
export function previewFallbackText(count, error) {
  return "Delete " + count + " selected file(s) from your PixAI account AND locally?\n\n" +
    (error ? error + "\n\n" : "") +
    "The preview of exactly what that takes could not be loaded, so: this deletes the whole " +
    "TASK behind each selection (every image in the batch, including ones you did not " +
    "select), from the cloud AND your backup. It is IRREVERSIBLE.\n\n" +
    // No preview, no count: the published-artwork sentence's own "not checked" form.
    "Whether any of these are published on PixAI was not checked — deleting a task may remove its published artwork too.";
}

/** Ask for the preview of deleting `ids`, then open the dialog on a real preview, or fall back
    to the prose confirm and delete only on its yes. */
export async function askCloudDelete(ids, { deletePreview, openDialog, confirm, deleteCloud }) {
  const data = await deletePreview(ids);
  // `totals` is what makes it a preview: an {error} answer is a failure wearing an object.
  if (data && data.totals) { openDialog(data); return; }
  if (confirm(previewFallbackText(ids.length, data && data.error))) await deleteCloud(ids);
}
