/* CURATION'S PURE CORE (Session N, wave 5) -- everything about the personal layer, bulk
   curation, the rating hotkeys and the collections manager that can be decided without React
   or a DOM. Same split as palette/paletteCore.js and gen/genCore.js: the components paint what
   these return, and loom/test/curation-core.test.js pins them.

   WHAT THE LAYER IS. A picture's tags, its keeper|reject mark and its note live in the LOCAL
   catalog (the server's personal_meta table) and are never sent to PixAI. The rules below
   mirror the server's (moonglade_gallery.normalize_tag, the caps) so the client can say no
   before it asks; the server stays the authority, and every answer it gives (`after`) is what
   the screen shows. */

export const TAG_MAX_LEN = 32;     // characters in one tag
export const TAGS_MAX = 32;        // tags on one picture
export const NOTE_MAX = 500;       // characters in a note
export const UNDO_MS = 10000;      // how long a bulk change can be undone

/* ---- tags and notes ---- */

/* A tag in its stored form: lowercase, whitespace and underscores to hyphens, letters and
   digits and hyphens only, runs of hyphens folded, none at the ends. "Pose Study!" ->
   "pose-study". */
export function normalizeTag(raw) {
  return String(raw == null ? "" : raw)
    .trim().toLowerCase()
    .replace(/[\s_]+/g, "-")
    .replace(/[^\p{L}\p{N}-]/gu, "")
    .replace(/-{2,}/g, "-")
    .replace(/^-+|-+$/g, "");
}

/* Can `raw` be added to a picture that already holds `existing`? {ok, tag, dupe?, error?}.
   A tag it already has is fine and changes nothing (dupe), never an error. */
export function checkTag(raw, existing) {
  const tag = normalizeTag(raw);
  if (!tag) return { ok: false, error: "A tag needs a letter or a number in it." };
  if (tag.length > TAG_MAX_LEN) return { ok: false, error: "A tag is up to " + TAG_MAX_LEN + " characters." };
  const have = existing || [];
  if (have.indexOf(tag) >= 0) return { ok: true, tag, dupe: true };
  if (have.length >= TAGS_MAX) return { ok: false, error: "A picture holds at most " + TAGS_MAX + " tags." };
  return { ok: true, tag };
}

export function clampNote(s) {
  return String(s == null ? "" : s).slice(0, NOTE_MAX);
}

/* ---- words for what happened (the undo toast) ---- */

export function pictures(n) {
  return n + (n === 1 ? " picture" : " pictures");
}

/* The toast sentence for one bulk change. `changed` is what the SERVER reports really
   changed, never the size of the selection: rating a picture that already has that rating is
   a no-op and must not be counted (N4). `refused` counts pictures already at the tag cap. */
export function curateSummary(op, changed, refused) {
  const o = op || {};
  let text;
  if (!changed) {
    if ("rating" in o) text = o.rating ? "Nothing changed: they already have ★" + o.rating + "." : "Nothing changed: none of them had a rating.";
    else if ("add_tag" in o) text = "Nothing changed: already tagged “" + normalizeTag(o.add_tag) + "”.";
    else if ("mark" in o) text = o.mark === "keeper" ? "Nothing changed: they are already keepers."
      : o.mark === "reject" ? "Nothing changed: they are already rejects." : "Nothing changed: none of them was marked.";
    else text = "Nothing changed.";
  } else if ("rating" in o) {
    text = o.rating ? "Rated " + pictures(changed) + " ★" + o.rating : "Cleared the rating on " + pictures(changed);
  } else if ("add_tag" in o) {
    text = "Tagged " + pictures(changed) + " “" + normalizeTag(o.add_tag) + "”";
  } else if ("mark" in o) {
    text = o.mark === "keeper" ? "Marked " + changed + (changed === 1 ? " as a keeper" : " as keepers")
      : o.mark === "reject" ? "Marked " + changed + (changed === 1 ? " as a reject" : " as rejects")
      : "Cleared the mark on " + pictures(changed);
  } else if ("remove_tag" in o) {
    text = "Removed “" + normalizeTag(o.remove_tag) + "” from " + pictures(changed);
  } else {
    text = "Changed " + pictures(changed);
  }
  if (refused) text += " · " + refused + " already hold" + (refused === 1 ? "s" : "") + " " + TAGS_MAX + " tags";
  return text;
}

/* The toast for "+ collection": counts only the pictures that really joined (a picture already
   in the collection is not added twice), and says when that was none. `total` is what was
   asked. */
export function addedSummary(added, name, total) {
  if (!added) return "Nothing added: " + (total === 1 ? "it is" : "they are") + " already in “" + name + "”.";
  const already = total - added;
  return "Added " + added + " to “" + name + "”" + (already > 0 ? " · " + already + " already in it" : "");
}

/* Seconds left on the undo, for the toast's "Undo · 8s". Never negative. */
export function undoSecondsLeft(until, now) {
  return Math.max(0, Math.ceil((until - now) / 1000));
}

/* ---- keeping the loaded page honest ---- */

/* The page's cards after the server changed some pictures. `after` is the server's
   {media_id: {rating, mark, tags, note}} for the pictures that changed (curate_apply) or that
   were put back (curate_restore). Returns the SAME array when no card was touched, so an
   untouched page costs no render. */
export function applyAfter(items, after) {
  if (!after || !items || !items.length) return items;
  let touched = false;
  const next = items.map((it) => {
    const a = after[it.media_id];
    if (!a) return it;
    touched = true;
    return { ...it, rating: a.rating, mark: a.mark || "", tags: a.tags || [] };
  });
  return touched ? next : items;
}

/* ---- the rating hotkeys (N5) ---- */

/* 0-5 with no chord: Ctrl/Alt/Meta belong to the browser and the palette. Returns the rating
   the key asks for, or null. */
export function ratingFromKey(e) {
  if (!e || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return null;
  return /^[0-5]$/.test(e.key) ? Number(e.key) : null;
}

/* Is focus somewhere a digit is text? Keys are ignored there. The selectors are the
   palette's own (hooks/useCommandPalette.js). */
export function isTypingTarget(el) {
  return !!(el && el.closest && el.closest("input, textarea, select, [contenteditable=''], [contenteditable='true']"));
}

/* Who a rating key acts on: the selection if there is one, otherwise the open Lightbox
   picture, otherwise the record that is open, otherwise the picture under the pointer.
   Returns {ids, from} with from = "selection" | "lightbox" | "details" | "hover" | "none". */
export function pickHotkeyTargets({ selected, lightboxId, detailsId, hoverId }) {
  const sel = selected ? Array.from(selected) : [];
  if (sel.length) return { ids: sel, from: "selection" };
  if (lightboxId) return { ids: [lightboxId], from: "lightbox" };
  if (detailsId) return { ids: [detailsId], from: "details" };
  if (hoverId) return { ids: [hoverId], from: "hover" };
  return { ids: [], from: "none" };
}

/* The gold flash's text: the stars just given, or the word for a cleared rating. */
export function flashText(rating) {
  return rating ? "★".repeat(rating) : "☆ cleared";
}

/* ---- collections: the list, the manager ---- */

/* The manager's Merge button and its note from what is ticked. `ticked` is the names in tick
   order and `all` the {name, kind} rows. Only hand-picked ones count; the FIRST hand-picked
   one ticked is the target. */
export function mergePlan(ticked, all) {
  const kind = new Map((all || []).map((c) => [c.name, c.kind]));
  const hand = (ticked || []).filter((n) => kind.get(n) === "hand");
  const can = hand.length > 1;
  return {
    hand,
    can,
    target: hand[0] || "",
    label: can ? "Merge " + hand.length + " into “" + hand[0] + "”" : "Merge",
    note: can ? "Duplicates removed; the others go away. Pictures are never deleted."
      : "Tick two or more hand-picked collections.",
  };
}

export function tickTitle(c) {
  return c.kind === "smart"
    ? "Smart collections can’t merge. Edit the query instead."
    : "Tick to merge";
}

/* The delete confirm's body: what goes, and how many pictures stay in the library. */
export function deleteBody(c) {
  const n = c.count || 0;
  return c.kind === "smart"
    ? "Only the saved query goes. The " + n + " matching " + (n === 1 ? "picture stays" : "pictures stay") + " in your library."
    : "The collection goes. Its " + n + " " + (n === 1 ? "picture stays" : "pictures stay") + " in your library.";
}

/* A rename, checked the way the server will: trimmed, not empty, and unique among ALL
   collections without regard to case (its own name excepted). {ok, name, unchanged?, error?} */
export function checkRename(newName, oldName, all) {
  const name = String(newName == null ? "" : newName).replace(/,/g, " ").replace(/\s+/g, " ").trim();
  if (!name) return { ok: false, name, error: "A collection needs a name." };
  if (name === oldName) return { ok: true, name, unchanged: true };
  const low = name.toLowerCase();
  if ((all || []).some((c) => c.name !== oldName && c.name.toLowerCase() === low)) {
    return { ok: false, name, error: "A collection called “" + name + "” already exists." };
  }
  return { ok: true, name };
}

/* Is the search field's text worth saving as a smart collection? */
export function canSaveSmart(query) {
  return String(query == null ? "" : query).trim() !== "";
}

/* THE SEARCH TO SAVE. The handoff saves "the search"; in this app a search is the field's text
   PLUS the chips and the Advanced flyout (model, minimum stars, media, source, dates, a hand-
   picked collection ...), and saving only the text would quietly drop whatever else was
   narrowing the view. So every filter that has a search operator is written out as one, and
   the saved query is the whole view. What has no operator (sort order, page size, a batch or a
   series drill-down) is not part of WHICH pictures match and is left out.

   The operators are the server's own (moonglade_gallery._SEARCH_OPS), each chosen to read the
   same rows as the control it stands for: `video:0` is the Images chip, `source:api` the Source
   chip, `created:>=2026-07` / `<=` the From / To months, `★N+` the minimum-stars chip. Two
   are looser than their control: `model:` and `lora:` match a substring where the chip matches
   the whole name. `collection` is the hand-picked collection being browsed ("" for none, and
   for a smart one, which is its own query). */
export function composeSmartQuery({ q, media, shelf, adv }) {
  const a = adv || {};
  const quote = (v) => {
    const t = String(v).replace(/"/g, "").trim();
    return /\s/.test(t) ? '"' + t + '"' : t;
  };
  const parts = [];
  if (q && String(q).trim()) parts.push(String(q).trim().replace(/\s+/g, " "));
  if (shelf) parts.push("collection:" + quote(shelf));
  if (media === "image") parts.push("video:0");
  else if (media === "video") parts.push("video:1");
  if (a.ratingMin) parts.push("★" + a.ratingMin + "+");
  if (a.model) parts.push("model:" + quote(a.model));
  if (a.lora) parts.push("lora:" + quote(a.lora));
  if (a.source) parts.push("source:" + a.source);
  if (a.tag) parts.push("art_tags:" + quote(a.tag));
  if (a.publishedOnly) parts.push("published:1");
  if (a.dateFrom) parts.push("created:>=" + a.dateFrom);
  if (a.dateTo) parts.push("created:<=" + a.dateTo);
  return parts.join(" ");
}

/* The line under the smart list: the query, marked live. */
export function smartQueryLine(query) {
  return "⟳ " + query;
}
