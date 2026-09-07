/* THE ONE REQUEST MODULE (2026-08-23).

   Every /api/ call the gallery makes goes through apiGet / apiPost / apiUpload. Nothing
   else under gallery/src calls fetch, reads r.ok, or parses r.json() -- pinned by
   loom/test/request-module-structure.test.js, which allows exactly three named files to
   keep their own fetch (see EXEMPTIONS below).

   WHY THIS EXISTS. Forty-six files hand-rolled the same six lines, and postJSON had drifted
   into FOUR copies that disagreed about the one question that matters here:

     api.js                     ignored r.ok entirely -- the body was the whole answer
     hooks/useControlPanel.js   ignored r.ok, {error: String(e)} on a throw
     hooks/useDuplicateReview.js  !r.ok || d.error -> {error}, "network error: ..." on a throw
     components/ActionsMenu.jsx   the same again, hand-copied

   plus a private getJSON in AccountSubOverlay.jsx and 144 bare r.json() reads. So every
   caller re-decided whether the HTTP status or the body's {error} was authoritative -- in an
   app whose spend routes deliberately answer errors with HTTP 200 {"error": ...} (see
   gen/submitTask.js's contract). A caller that keys off r.ok reads a refusal as a success.

   THE ONE ERROR RULE, decided here and nowhere else:

     1. The BODY wins. A parsed {error: ...} is the answer, whatever the status was --
        including HTTP 200. The whole body comes back, so a route that returns
        {error, ...extras} keeps its extras.
     2. A non-2xx with no body error becomes {error: "<status> <statusText>"}. Either way a
        non-2xx answer carries `http_status`, for the one caller that must say something
        different about a 403 (components/Darkroom.jsx -- the localhost-only import gate;
        it inherited the check from FilterCompare.jsx, the overlay it replaced).
     3. A transport failure (offline, dropped Wi-Fi, a hung socket) becomes
        {error: "network error: <message>"} -- the wording two of the four copies already used.

   Nothing here ever throws and nothing here ever retries. A caller branches on d.error, once.

   CSRF IS NOT DONE HERE, deliberately. The token rides as a BODY FIELD, and the callers do
   not agree on where it comes from: boot.csrf (logout, duplicate review), summary.csrf (the
   Panel's user admin), a token fetched from /api/myart/items (publish, train), and LoginPage's
   own csrfRef, which the server ROTATES on every failed attempt. One of those is a moving
   value the module cannot see. So csrf stays explicit at each call site; apiPost only carries
   the body it is given.

   EXEMPTIONS -- three files keep their own fetch, each for a reason the one rule cannot serve:
     gen/priceRequest.js   the one price transport (the gallery's probe and the Loom both ride
                           it). It must tell an ABORTED or timed-out price check ({failed} --
                           the red "couldn't verify — may spend") apart from an HTTP-200
                           {error} body ({response}) -- the distinction rule 1 deliberately
                           collapses, and the spend gate reads it. It is the only
                           /api/price caller under gallery/src.
     gen/submitTask.js     the spend road. Its transport-failure line ("the task MAY still have
                           been submitted") is a different sentence from a body error, and that
                           difference is a spend-safety guarantee, not a message.
     notify/jobs.js        the /api/task-status poller: a rejected READ is its retry trigger
                           (again(4000)), which needs the rejection itself, not an {error} body.
   All three are pinned by their own structure tests. */

// ---- the seam -------------------------------------------------------------------------

function withParams(path, params) {
  if (!params) return path;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? path + (path.includes("?") ? "&" : "?") + s : path;
}

/* `timeoutMs` / `timeoutMessage` are OURS, not fetch's: they are lifted out of the init before
   it goes anywhere near the browser. A route with a wall-clock ceiling of its own passes the
   two so a server that goes silent still ends as an ordinary {error} answer the caller already
   branches on, in plain words, instead of a spinner with no end
   (/api/delete-preview is the one caller today). Nothing else changes: no timeoutMs, no
   AbortController, exactly the bare fetch every other call has always made. */
async function request(path, init) {
  const { timeoutMs, timeoutMessage, ...rest } = init || {};
  let ctl = null, timer = 0;
  if (timeoutMs > 0 && typeof AbortController !== "undefined") {
    ctl = new AbortController();
    if (!rest.signal) rest.signal = ctl.signal;
    timer = setTimeout(() => ctl.abort(), timeoutMs);
  }
  let r;
  try {
    r = await fetch(path, rest);
  } catch (e) {
    if (ctl && ctl.signal.aborted) {
      return { error: timeoutMessage || "timed out waiting for the server", timed_out: true };
    }
    return { error: "network error: " + (e && e.message ? e.message : "unreachable") };
  } finally {
    if (timer) clearTimeout(timer);
  }
  let d = null;
  try { d = await r.json(); } catch { d = null; }   // an HTML error page, a 204, a cut stream
  // rule 1: the body wins, HTTP 200 included. `http_status` rides along on any non-2xx,
  // whichever rule produced the error, so the one caller that must say something different
  // about a 403 can still tell.
  if (d && d.error) return r.ok ? d : { ...d, http_status: r.status };
  if (!r.ok) return { error: r.status + " " + (r.statusText || "request failed"), http_status: r.status };
  return d === null ? {} : d;
}

/* GET an /api/ route. `params` is the optional querystring as an object (empty/null/undefined
   values are dropped); a path that already carries its own ?query is passed through untouched.
   `opts` is merged into the fetch init for the one caller that needs `cache: "no-store"`. */
export function apiGet(path, params, opts) {
  return request(withParams(path, params), opts);
}

/* JSON POST. `opts` is merged into the fetch init (after method/headers/body, so a caller
   could override them, but none does). */
export function apiPost(path, body, opts) {
  return request(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
    ...(opts || {}),
  });
}

/* Multipart POST -- the browser sets its own Content-Type boundary, so there are no headers
   to write here. Same answer shape as the other two. */
export function apiUpload(path, formData) {
  return request(path, { method: "POST", body: formData });
}

// ---- the gallery's OWN data surface ----------------------------------------------------
// /api/next/* (purpose-built, not the old picker routes). Every call is same-origin; the
// front-door session cookie rides along automatically.

export async function fetchLibrary(params = {}) {
  const d = await apiGet("/api/next/library", params);
  // The one caller (hooks/useLibrary.js) reads data.items/total/page/pages straight off this,
  // so an unusable answer must not arrive as a half-empty object.
  if (d.error) throw new Error("library fetch failed: " + d.error);
  return d;
}

/* Sibling Strip data for the card placard (#30): ONE page-batched POST, never per
   card (the per-card lineage fetch cost ~4.3s per 100-card page). Returns
   {by_task: {task_id: [{media_id, is_video, thumb}, ...]}} -- self INCLUDED, tasks
   with <2 members omitted by the server. Fail-soft: the strip is decoration, so a
   failure means no strips, never an error surface. */
export async function fetchSiblings(taskIds) {
  const d = await apiPost("/api/siblings", { task_ids: taskIds });
  return d && d.by_task && typeof d.by_task === "object" ? d : { by_task: {} };
}

// SESSION strip in Image Details (#34, direction C): is THIS image's task a step in a
// multi-task dial-in series, and if so, the whole series to draw task-by-task. Two
// reads, both fail-soft to null (the strip is decoration -- a failure, or a singleton,
// means no panel, never an error surface). First the membership POST: one task_id to
// /api/series, which answers by_task ONLY for a task that's in a multi-task series
// (singletons -- ~85% of the library -- come back absent => null, no second call). Then
// GET /api/series/<sid> for the ordered steps. Returns the series struct
// {sid,title,model,count_tasks,count_images,span,steps} or null.
// #34: the page-batched series lookup for the grid stamp -- one POST for the whole page,
// by_task holds only tasks in a multi-task series (singletons absent, cost nothing).
export async function fetchSeriesBatch(taskIds) {
  return apiPost("/api/series", { task_ids: taskIds });
}

export async function fetchSeries(taskId) {
  if (!taskId) return null;
  const m = await apiPost("/api/series", { task_ids: [taskId] });
  const hit = m && m.by_task && typeof m.by_task === "object" ? m.by_task[taskId] : null;
  if (!hit || !hit.sid) return null;
  const d = await apiGet("/api/series/" + encodeURIComponent(hit.sid));
  return d && Array.isArray(d.steps) && d.steps.length ? d : null;
}

/* B3 (Gallery Chrome Handoff, 2026-09-04): everything one series stack's MODAL needs,
   in one call -- the runs for its lineage rail and the pictures for its grid.

   Two existing routes, no new backend. GET /api/series/<sid> is the run list: the
   ordered steps {task_id, v, reroll, label, first_media_id, n}, each step being one
   RUN of the dial-in. GET /api/next/library?series=<sid> is the pictures: the same
   ?series= drill-down the retired custom-search takeover used to push into the
   library's own filters, asked for directly here instead -- so the modal reads the
   series without disturbing the library underneath it, which is what lets Esc go
   straight back to a gallery that never moved.

   THE MODAL SHOWS THE SERIES WHOLE -- it does not page, because a lineage rail that
   only knows about the first page would put wrong counts against its runs. So this
   walks the listing to the end. /api/next/library caps page_size at 200 server-side
   (asking for more is silently clamped, so this asks for exactly the cap), and a
   dial-in series runs to at most ~801 images -- PAGE_CAP of 5 covers that with room,
   and is a real ceiling rather than an unbounded loop: if a series ever exceeds it,
   `truncated` says so instead of the rail quietly under-counting.

   Fails soft to null, like fetchSeries: a 404 sid (a series dissolved by deletions)
   or an unreachable route means no modal, never an error surface. */
const SERIES_PAGE_SIZE = 200;   // /api/next/library's own server-side cap
const SERIES_PAGE_CAP = 5;      // 1000 images; the documented series maximum is ~801

/* ONE stack loader, two stack kinds (owner ruling, 2026-09-07: a batch card opens in
   the series modal, tagged BATCH, instead of taking the library over). The only thing
   that differs between them is WHICH pair of routes carries the stack:
     series -> /api/series/<sid>      + /api/next/library?series=<sid>
     batch  -> /api/batch/<task_id>   + /api/next/library?batch=<task_id>
   Everything else -- the walk to the end of the listing, the page cap, the truncated
   flag, the fail-soft null -- is shared, so the modal has one code path and a batch
   never touches /api/series/. */
async function fetchStack(metaRoute, listParam, id) {
  if (!id) return null;
  const meta = await apiGet(metaRoute + encodeURIComponent(id));
  if (!meta || meta.error || !Array.isArray(meta.steps) || !meta.steps.length) return null;
  const items = [];
  let total = null, pages = 1, truncated = false;
  for (let p = 1; p <= SERIES_PAGE_CAP; p++) {
    const lib = await apiGet("/api/next/library",
      { [listParam]: id, page: p, page_size: SERIES_PAGE_SIZE });
    if (!lib || lib.error || !Array.isArray(lib.items)) break;
    items.push(...lib.items);
    if (typeof lib.total === "number") total = lib.total;
    if (typeof lib.pages === "number") pages = lib.pages;
    if (p >= pages) break;
    if (p === SERIES_PAGE_CAP) truncated = true;
  }
  return { ...meta, items, total, truncated };
}

export async function fetchSeriesStack(sid) {
  return fetchStack("/api/series/", "series", sid);
}

/* A BATCH stack: one task's outputs, in the same struct the modal already consumes
   (moonglade_gallery.py's api_batch_detail answers a one-run series). The pictures
   ride the EXISTING ?batch= library filter -- the one the retired View-batch takeover
   used to push into the grid's own filters -- asked for directly here instead, so the
   library underneath the modal is never disturbed. */
export async function fetchBatchStack(taskId) {
  return fetchStack("/api/batch/", "batch", taskId);
}

// ZIP download goes through a real form submit so the browser owns the download.
export function downloadZipForm(idList) {
  const f = document.createElement("form");
  f.method = "post";
  f.action = "/export-zip";
  for (const mid of idList) {
    const i = document.createElement("input");
    i.type = "hidden"; i.name = "media_ids"; i.value = mid;
    f.appendChild(i);
  }
  document.body.appendChild(f);
  f.submit();
  f.remove();
}

/* The blast-radius preview. It reads every selected task back from PixAI, so it is the one
   call in this module that can legitimately take seconds -- and the server bounds itself at
   DELETE_PREVIEW_LIVE_BUDGET_S (12s). This waits a little longer than that ceiling and then
   stops: 15s means an ordinary slow answer still arrives, and a server that has gone silent
   ends as a plain sentence rather than a dialog that never opens.

   Answers three ways, and the caller must tell them apart: the preview itself (it has
   `totals`), an {error} the caller can show, or null when the route answered something
   unusable. ActionsMenu falls back to the prose-only confirm on either of the last two. */
export const DELETE_PREVIEW_MS = 15000;

export async function deletePreview(idList) {
  const d = await apiPost("/api/delete-preview", { media_ids: idList }, {
    timeoutMs: DELETE_PREVIEW_MS,
    timeoutMessage: "PixAI did not answer in time, so the preview could not be built.",
  });
  if (d && d.totals) return d;
  return d && d.error ? { error: d.error } : null;
}

export async function fetchCollections() {
  const d = await apiGet("/api/collections");
  return d && d.collections ? d.collections : null;
}

/* Which of these ids are videos? The pilot usually knows from its own items, but a
   selection can outlive a filter change -- ids the grid no longer holds are resolved
   through the same meta route the classic uses (same hole, same fix). */
export async function resolveVideoIds(idList, known) {
  const vids = new Set();
  const unseen = [];
  for (const mid of idList) {
    if (known.has(mid)) { if (known.get(mid)) vids.add(mid); }
    else unseen.push(mid);
  }
  await Promise.all(unseen.map(async (mid) => {
    // an unanswerable id: send it, decide nothing new
    const d = await apiGet("/api/image-meta/" + encodeURIComponent(mid));
    if (d && d.is_video) vids.add(mid);
  }));
  return vids;
}

/* Regenerate one video's poster thumb from its file (e.g. a fade-in that was thumbnailed
   black). Returns {ok, thumb} -- thumb carries a cache-buster so the new frame shows at once. */
export async function rebuildPoster(mediaId) {
  return apiPost("/api/rebuild-poster/" + encodeURIComponent(mediaId), {});
}

export async function rateImage(mediaId, rating) {
  const d = await apiPost("/api/rate/" + mediaId, { rating });
  if (d.error) throw new Error("rate failed");   // both callers roll the star back on a throw
  return d;
}

/* Saved views are server-side and account-scoped; each stores the CLASSIC
   gallery's query string, which the flyout parses back into pilot state --
   one store, both surfaces. */
export async function fetchPresets() {
  const d = await apiGet("/api/view-presets");
  if (d.error) return [];
  const p = d.presets || {};
  // the server stores {name: queryString}; normalize to [{name, query}]
  return Array.isArray(p) ? p : Object.entries(p).map(([name, query]) => ({ name, query }));
}

/* The account chip (credits / cards / backup coverage) reuses the app-wide
   account API -- it is suite-level, not old-gallery-shaped. */
export async function fetchAccount() {
  const d = await apiGet("/api/account");
  return d.error ? null : d;
}
