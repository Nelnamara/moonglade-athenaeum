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
        different about a 403 (components/FilterCompare.jsx -- the localhost-only import gate).
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
     gen/usePriceProbe.js  owns an AbortController + timeout, and must tell an ABORTED price
                           check (setPrice(null), the red "couldn't verify — may spend") apart
                           from an HTTP-200 {error} body (setPrice(d)) -- the distinction rule 1
                           deliberately collapses. It is the only /api/price caller.
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

async function request(path, init) {
  let r;
  try {
    r = await fetch(path, init);
  } catch (e) {
    return { error: "network error: " + (e && e.message ? e.message : "unreachable") };
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

export async function deletePreview(idList) {
  const d = await apiPost("/api/delete-preview", { media_ids: idList });
  return d && d.totals ? d : null;
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
