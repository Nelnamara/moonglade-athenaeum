/* =========================================================================
   loom-cast-library.js — THE CAST LIBRARY (Session P, NOTES P7), as pure views and patches.

   The page (Loom Handoff.dc.html, section B, P7): "Today the prototype keeps one cast list
   for every storyboard. That list becomes the library, and each storyboard stores which
   members it uses (the tick). Unticking a member used by a shot asks first and names the
   shots. Editing an entry (its refs or 🔒) applies everywhere it's used; the row says 'in N
   storyboards'. ⧉ Duplicate copies the ticks."

   THE DATA (additive and lazy -- an old board loads unchanged, and an older build opening a
   board this build touched still sees a normal `assets` list):
     * The LIBRARY is one account-side value in the Loom KV store, key CASTLIB_KEY:
         {v: 1, members: [member]}   member = the asset shape (name, kind, tag, mediaId,
                                     thumbId, source, lock, ...) + a stable `libId`, no `id`.
       It is written only by an owner action, compare-and-swap (the caller's job).
     * A board's TICKS are its `project.assets` entries that carry a `libId`. The board keeps
       a FULL copy of each ticked member, so every existing reader (shotText, the cast tags,
       refBudget, the bundle, the drawer) and an older build keep working untouched.
     * A legacy asset (no libId), or one whose libId the library does not hold, is shown as a
       row belonging to this board only. It joins the library only when the owner acts on it
       (tick / untick / edit) -- never on open, never by a view.

   Same discipline as loom-core.js / loom-takes-core.js: NO React, no DOM, no window, no
   fetch, no timers. Ids are ARGUMENTS. Every view here returns a new value and never writes
   its inputs (loom/test/loom-cast-library.test.js pins a populated board byte-identical
   through each one); every patch touches only what it names. The never-auto-render test
   (loom/test/loom-no-auto-render.test.js) pins that this file reaches nothing.
   ========================================================================================= */
import { flat, nextTag } from "./loom-core.js";

/** The one library value per account (the Loom KV store is already per account). */
export const CASTLIB_KEY = "storyboard:v2:castlib";
export const CASTLIB_VERSION = 1;

/** What an edit of a member carries to every copy of it: its picture ("its refs") and its
 *  🔒. The name, tag and kind stay each storyboard's own (a tick can re-tag a member when its
 *  tag is taken on that board, so a tag is never a library-wide fact). */
export const MEMBER_SYNC_FIELDS = ["mediaId", "thumbId", "source", "lock"];

const str = (v) => (v == null ? "" : String(v));
const assetsOf = (project) => ((project && Array.isArray(project.assets)) ? project.assets : []);

export const emptyLibrary = () => ({ v: CASTLIB_VERSION, members: [] });

/**
 * parseLibrary(value) -> {v, members} | null
 * `value` is what the KV store holds (the JSON text), or null for a key that is not there
 * yet (-> an empty library). Anything else that will not read as a library is null: the
 * caller must treat it as UNREADABLE and never write over it.
 */
export const parseLibrary = (value) => {
  if (value == null) return emptyLibrary();
  let d = value;
  if (typeof value === "string") {
    try { d = JSON.parse(value); } catch (e) { return null; }
  }
  if (!d || typeof d !== "object" || !Array.isArray(d.members)) return null;
  return { ...d, v: Number(d.v) || CASTLIB_VERSION,
    members: d.members.filter((m) => m && typeof m === "object" && str(m.libId)) };
};

/** A member made from a board's asset: every field but the board-local id, plus its libId. */
export const memberFromAsset = (asset, libId) => {
  const m = { ...(asset || {}) };
  delete m.id;
  m.libId = str(libId);
  return m;
};

/** The board copy of a member: the member's fields, this board's asset id and tag. */
export const assetFromMember = (member, id, tag) => ({ ...(member || {}), id: str(id), tag: str(tag), libId: str(member && member.libId) });

const prefixOf = (kind) => (kind === "video" ? "@video" : kind === "audio" ? "@audio" : "@image");

/** The tag a member takes on a board: its own when no asset on the board has it, else the
 *  board's next free tag of its kind (the panel's own nextTag rule). */
export const tagOnBoard = (assets, member) => {
  const own = str(member && member.tag);
  if (own && !(assets || []).some((a) => a && str(a.tag) === own)) return own;
  return nextTag(assets || [], prefixOf(member && member.kind));
};

/** The shots on this board that cast the asset `assetId`: [{id, code}], board order. */
export const shotsUsing = (project, assetId) => {
  if (!project || !Array.isArray(project.acts) || !assetId) return [];
  return flat(project).filter((e) => (e.c.cast || []).includes(assetId)).map((e) => ({ id: e.c.id, code: e.code }));
};

/** The libIds this board ticks (its assets that carry one), in board order. */
export const boardLibIds = (project) => assetsOf(project).map((a) => str(a && a.libId)).filter(Boolean);

/**
 * usageOf(others) -> Map(libId -> [{id, name}])
 * `others` = the account's OTHER boards as read: [{id, name, project}]. Read-only.
 */
export const usageOf = (others) => {
  const m = new Map();
  (others || []).forEach((b) => {
    const seen = new Set();
    boardLibIds(b && b.project).forEach((lid) => {
      if (seen.has(lid)) return;
      seen.add(lid);
      if (!m.has(lid)) m.set(lid, []);
      m.get(lid).push({ id: str(b.id), name: str((b.project && b.project.name) || b.name) });
    });
  });
  return m;
};

/**
 * libraryRows(lib, project, others) -> rows, the panel's list (a VIEW; writes nothing).
 *   Library members first, in library order; then this board's rows that are not (yet) in
 *   the library -- a legacy asset with no libId, or a copy whose libId the library lacks --
 *   in board order.
 * row = {key, libId, boardOnly, ticked, asset, member, name, kind, lock, tag, picture,
 *        usedBy: [{id, code}], boards: n | null}
 *   `boards` ("in N storyboards") counts this board (live) plus the other boards read; it is
 *   null while `others` is unknown (still reading). A board-only row is in exactly one.
 */
export const libraryRows = (lib, project, others) => {
  const assets = assetsOf(project);
  const members = (lib && Array.isArray(lib.members)) ? lib.members : [];
  const inLib = new Set(members.map((m) => str(m.libId)));
  const usage = others ? usageOf(others) : null;
  const rows = [];
  const pictureOf = (x) => ({ mediaId: str(x && x.mediaId), thumbId: str(x && x.thumbId), source: str(x && x.source) });
  members.forEach((m) => {
    const lid = str(m.libId);
    const copy = assets.find((a) => a && str(a.libId) === lid) || null;
    const src = copy || m;
    rows.push({
      key: "lib:" + lid, libId: lid, boardOnly: false, ticked: !!copy, asset: copy, member: m,
      name: str(src.name), kind: str(src.kind) || "image", lock: !!src.lock, tag: str(src.tag),
      picture: pictureOf(src), usedBy: copy ? shotsUsing(project, copy.id) : [],
      boards: usage ? (usage.get(lid) || []).length + (copy ? 1 : 0) : null,
    });
  });
  assets.forEach((a) => {
    if (!a) return;
    const lid = str(a.libId);
    if (lid && inLib.has(lid)) return;
    rows.push({
      key: "board:" + str(a.id), libId: lid || null, boardOnly: true, ticked: true, asset: a, member: null,
      name: str(a.name), kind: str(a.kind) || "image", lock: !!a.lock, tag: str(a.tag),
      picture: pictureOf(a), usedBy: shotsUsing(project, a.id), boards: 1,
    });
  });
  return rows;
};

/** The row's monospace meta line, in the page's words: "@tag · in N storyboards · A·02 A·03". */
export const rowMeta = (row) => {
  if (!row) return "";
  const where = row.boardOnly ? "this storyboard only"
    : row.boards == null ? "in … storyboards"
    : "in " + row.boards + " storyboard" + (row.boards === 1 ? "" : "s");
  const parts = [row.tag || "(no tag)", where];
  if (row.usedBy && row.usedBy.length) parts.push(row.usedBy.map((u) => u.code).join(" "));
  return parts.join(" · ");
};

/** The confirm an untick of a used member asks first (the page's own words). */
export const untickQuestion = (row) => (row && row.usedBy && row.usedBy.length
  ? (row.name || "This member") + " is used by " + row.usedBy.map((u) => u.code).join(", ") + ". Remove from this storyboard anyway?"
  : "");

/* ---------- patches: each touches only what it names ---------- */

/** Tick: copy a library member into this board with the new asset id `id`. Its tag is kept
 *  when free here, else the next free one. A member already ticked here is left alone. */
export const tickMember = (project, member, id) => {
  if (!project || !member || !str(member.libId) || !id) return project;
  const assets = assetsOf(project);
  if (assets.some((a) => a && str(a.libId) === str(member.libId))) return project;
  return { ...project, assets: assets.concat([assetFromMember(member, id, tagOnBoard(assets, member))]) };
};

/** Untick: remove asset `assetId` from this board AND drop its id from the cast of the shots
 *  that used it, so nothing dangles. Every other card is the same object it was. */
export const untickAsset = (project, assetId) => {
  if (!project || !assetId) return project;
  const assets = assetsOf(project);
  if (!assets.some((a) => a && a.id === assetId)) return project;
  return { ...project,
    assets: assets.filter((a) => !(a && a.id === assetId)),
    acts: (project.acts || []).map((act) => {
      if (!(act.cards || []).some((c) => (c.cast || []).includes(assetId))) return act;
      return { ...act, cards: act.cards.map((c) => ((c.cast || []).includes(assetId)
        ? { ...c, cast: c.cast.filter((x) => x !== assetId) } : c)) };
    }) };
};

/** Give this board's asset `assetId` its library id (materialising a legacy row). */
export const withLibId = (project, assetId, libId) => {
  if (!project || !assetId || !libId) return project;
  const assets = assetsOf(project);
  if (!assets.some((a) => a && a.id === assetId)) return project;
  return { ...project, assets: assets.map((a) => (a && a.id === assetId ? { ...a, libId: str(libId) } : a)) };
};

/** Only the fields an edit may carry to every copy. */
export const syncPatch = (patch) => {
  const out = {};
  MEMBER_SYNC_FIELDS.forEach((k) => { if (patch && Object.prototype.hasOwnProperty.call(patch, k)) out[k] = patch[k]; });
  if ("lock" in out) out.lock = !!out.lock;
  return out;
};

/** Add a member to the library (a member already there by libId is left as it is). */
export const addMember = (lib, member) => {
  const base = lib || emptyLibrary();
  if (!member || !str(member.libId)) return base;
  if ((base.members || []).some((m) => str(m.libId) === str(member.libId))) return base;
  return { ...base, members: (base.members || []).concat([member]) };
};

/** Edit one library member (the sync fields only). */
export const editMember = (lib, libId, patch) => {
  const p = syncPatch(patch);
  if (!lib || !libId || !Object.keys(p).length) return lib;
  if (!(lib.members || []).some((m) => str(m.libId) === str(libId))) return lib;
  return { ...lib, members: lib.members.map((m) => (str(m.libId) === str(libId) ? { ...m, ...p } : m)) };
};

/** Patch a board's copy (or copies) of member `libId` -- and nothing else on the board. */
export const editCopies = (project, libId, patch) => {
  const p = syncPatch(patch);
  if (!project || !libId || !Object.keys(p).length) return project;
  const assets = assetsOf(project);
  if (!assets.some((a) => a && str(a.libId) === str(libId))) return project;
  return { ...project, assets: assets.map((a) => (a && str(a.libId) === str(libId) ? { ...a, ...p } : a)) };
};

/** Does board `project` tick member `libId`? */
export const ticks = (project, libId) => !!libId && assetsOf(project).some((a) => a && str(a.libId) === str(libId));

/**
 * handoffCast(ids, assets, idFor, libIdFor) -> {assets, members}
 * The gallery's cast hand-off (/loom?cast=): one @image member per picture, tags continuing
 * from the board's highest (today's rule), each ticked here AND a library member.
 */
export const handoffCast = (ids, assets, idFor, libIdFor) => {
  const out = [], members = [];
  const have = (assets || []).slice();
  (ids || []).forEach((mid) => {
    const a = { id: str(idFor()), name: "", kind: "image", tag: nextTag(have, "@image"), thumbId: "", source: "",
      mediaId: str(mid), lock: true, libId: str(libIdFor()) };
    have.push(a);
    out.push(a);
    members.push(memberFromAsset(a, a.libId));
  });
  return { assets: out, members };
};

/** "+ Add" in the library panel: a picked picture (or video) as a new member ticked here. */
export const newMemberAsset = ({ mediaId, isVideo } = {}, assets, id, libId) => ({
  id: str(id), name: "", kind: isVideo ? "video" : "image", tag: nextTag(assets || [], isVideo ? "@video" : "@image"),
  thumbId: "", source: "", mediaId: str(mediaId), lock: false, libId: str(libId),
});
