// The new gallery's OWN data surface -- /api/next/* (purpose-built, not the old
// picker routes). Every call is same-origin; the front-door session cookie rides
// along automatically.

export async function fetchLibrary(params = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  }
  const r = await fetch("/api/next/library?" + qs.toString());
  if (!r.ok) throw new Error("library fetch failed: " + r.status);
  return r.json();
}

// Classic form-POST routes (collection add/remove, deletes, replace). They answer
// with a redirect back to the classic page; fetch follows it harmlessly -- what
// matters is the mutation, and the pilot refreshes its own grid afterwards.
export async function postForm(action, fields, idList) {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields || {})) fd.append(k, v);
  for (const mid of idList || []) fd.append("media_ids", mid);
  const r = await fetch(action, { method: "POST", body: fd });
  return r.ok;
}

// JSON POST to an /api/ route. Fail-soft to {error} (never throws) so callers can branch
// on d.error uniformly. Replaces the classic redirect-answering form routes with their
// JSON twins for the desktop grid actions (2026-08-07).
export async function postJSON(url, body) {
  try {
    const r = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    return await r.json();
  } catch (e) {
    return { error: String((e && e.message) || e) };
  }
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
  try {
    const r = await fetch("/api/delete-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ media_ids: idList }),
    });
    if (!r.ok) return null;
    const d = await r.json();
    return d && d.totals ? d : null;
  } catch {
    return null;
  }
}

export async function fetchCollections() {
  try {
    const r = await fetch("/api/collections");
    if (!r.ok) return null;
    const d = await r.json();
    return d && d.collections ? d.collections : null;
  } catch {
    return null;
  }
}

// Which of these ids are videos? The pilot usually knows from its own items, but a
// selection can outlive a filter change -- ids the grid no longer holds are resolved
// through the same meta route the classic uses (same hole, same fix).
export async function resolveVideoIds(idList, known) {
  const vids = new Set();
  const unseen = [];
  for (const mid of idList) {
    if (known.has(mid)) { if (known.get(mid)) vids.add(mid); }
    else unseen.push(mid);
  }
  await Promise.all(unseen.map(async (mid) => {
    try {
      const r = await fetch("/api/image-meta/" + encodeURIComponent(mid));
      if (r.ok && (await r.json()).is_video) vids.add(mid);
    } catch { /* unanswerable id: send it, decide nothing new */ }
  }));
  return vids;
}

export async function rateImage(mediaId, rating) {
  const r = await fetch("/api/rate/" + mediaId, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rating }),
  });
  if (!r.ok) throw new Error("rate failed");
  return r.json();
}

// Saved views are server-side and account-scoped; each stores the CLASSIC
// gallery's query string, which the flyout parses back into pilot state --
// one store, both surfaces.
export async function fetchPresets() {
  try {
    const r = await fetch("/api/view-presets");
    if (!r.ok) return [];
    const d = await r.json();
    const p = (d && d.presets) || {};
    // the server stores {name: queryString}; normalize to [{name, query}]
    return Array.isArray(p) ? p : Object.entries(p).map(([name, query]) => ({ name, query }));
  } catch {
    return [];
  }
}

// The account chip (credits / cards / backup coverage) reuses the app-wide
// account API -- it is suite-level, not old-gallery-shaped.
export async function fetchAccount() {
  try {
    const r = await fetch("/api/account");
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}
