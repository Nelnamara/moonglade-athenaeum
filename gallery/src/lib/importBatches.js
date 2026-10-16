/* Web Import, sent in batches (#82).

   The import route used to take the first 1,000 uploaded files of ONE request and drop the rest
   without a word, and the page put every chosen file in one request, so a folder of 1,200 pictures
   imported 1,000 and reported success. The page now sends the files in batches well under that
   ceiling and adds the answers up; the route keeps its cap as a guard and counts what it did not
   take (`not_taken`), which the finished message prints.

   Two limits per request: a file count (far under the route's 1,000) and a byte total, so one
   request is never a multi-gigabyte upload that a phone connection drops. A single file bigger than
   the byte limit travels alone. Pure (the upload call is passed in), so loom/test/import-batches.test.js
   drives it without a server. */

export const IMPORT_BATCH_FILES = 200;
export const IMPORT_BATCH_BYTES = 256 * 1024 * 1024;

/* Split `files` into consecutive groups, none over `maxFiles` files or (except a lone oversized file)
   over `maxBytes` bytes. Order is kept: the first batch is the first files chosen. */
export function splitImportBatches(files, maxFiles = IMPORT_BATCH_FILES, maxBytes = IMPORT_BATCH_BYTES) {
  const batches = [];
  let cur = [];
  let bytes = 0;
  for (const f of files || []) {
    const size = Number(f && f.size) || 0;
    if (cur.length && (cur.length >= maxFiles || bytes + size > maxBytes)) {
      batches.push(cur);
      cur = [];
      bytes = 0;
    }
    cur.push(f);
    bytes += size;
  }
  if (cur.length) batches.push(cur);
  return batches;
}

/* Send `files` batch by batch through `upload(formData)` (api.js's apiUpload) and add the answers up.

   Success:  { ok: true, imported, skipped, notTaken, collection, sent }
   Failure:  { ok: false, error, imported, skipped, notTaken, sent }
   `sent` is how many files sat in batches the server answered for, so the caller can keep only the
   rest staged for a retry. A failure on the FIRST batch reads exactly as a one-request failure always
   did; a later one says how far it got, because the earlier batches are already in the library. */
export async function importInBatches(files, collection, upload, opts = {}) {
  const batches = splitImportBatches(files, opts.maxFiles, opts.maxBytes);
  const total = (files || []).length;
  const out = { imported: 0, skipped: 0, notTaken: 0, sent: 0, collection: null };
  const stopped = (error) => {
    const done = out.sent;
    const msg = done > 0
      ? "Stopped after " + done + " of " + total + " files (" + out.imported + " imported): " + error
      : error;
    return { ok: false, error: msg, imported: out.imported, skipped: out.skipped, notTaken: out.notTaken, sent: done };
  };
  for (const batch of batches) {
    const fd = new FormData();
    batch.forEach((f) => fd.append("files", f, f.name));
    if (collection) fd.append("collection", collection);
    let d;
    try {
      d = await upload(fd);
    } catch {
      return stopped("network error");
    }
    if (!d || d.error) return stopped((d && d.error) || "network error");
    out.imported += Number(d.imported) || 0;
    out.skipped += Number(d.skipped) || 0;
    out.notTaken += Number(d.not_taken) || 0;
    if (d.collection) out.collection = d.collection;
    out.sent += batch.length;
  }
  return { ok: true, ...out };
}

/* The finished message's tail for files the server left out: "" when none. One wording for the desktop
   overlay and the phone screen. */
export function notImportedNote(result) {
  const n = result && Number(result.notTaken);
  if (!n || n < 0) return "";
  return " · " + n + " not imported (over the server's per-request limit)";
}
