/* =========================================================================
   loom-core.js — pure, framework-agnostic logic extracted out of
   master-storyboard.jsx (Phase 1 tooling pass, 2026-07-16).

   NO React import, no DOM/window access, no `fetch` -- everything here is
   deterministic given its arguments, so it is safe to `node --test` directly
   (see loom/test/loom-core.test.js).

   Two consumers, both must keep working:
     1. master-storyboard.jsx imports this as a real ES module and esbuild
        bundles the two together (loom/scripts/build.mjs -> loom/dist/).
     2. The Flask /loom route (pixai_gallery.py, `loom()`) ALSO inlines this
        file's source ahead of the JSX for the in-browser Babel-standalone
        fallback path -- stripping the `export` keywords the same way it
        already strips `export default function App()`. That keeps the
        Babel-standalone path behaviorally identical to the esbuild path
        without a build step, so do not add anything here a classic
        (non-module) <script> couldn't also run: no top-level await, no
        import.meta, no imports of anything but this file itself.
   ========================================================================= */

// ---------- continuity / connection-method metadata ----------

export const CONNECT = {
  new:    { label: "New scene",     hint: "intentional break — fresh look/place" },
  cut:    { label: "Cut (in edit)", hint: "hard/match cut joined in your editor — rhyme the frames" },
  flf:    { label: "First→Last",    hint: "land on an exact end frame; prompt the motion between" },
  extend: { label: "Extend prev",   hint: "feed previous clip as @video1; continue seamlessly" },
};

export const CONTINUITY_PHRASE = "Smooth, continuous, seamless — no hard cut.";

// ---------- small pure formatter shotText/flat depend on ----------

export const actLetter = (i) => (i < 26 ? String.fromCharCode(65 + i) : `A${i}`);

/* ---------- shared helpers (Phase 0, 2026-07-16) ----------
   These replace ~7 independently-reimplemented copies of the same two ideas
   (tag numbering, frame-identity comparison) that had silently drifted into
   3 different algorithms and caused real collisions. One implementation now,
   called from classic, V2, and every mutator. */

// Highest existing "<prefix>N" tag number among items' `.tag` fields (anchored
// regex-max — the one call site, V2's cast-add, that already had this right).
export const maxTagNum = (items, prefix) => {
  const re = new RegExp("^" + prefix + "(\\d+)$");
  return (items || []).reduce((mx, x) => { const m = re.exec(x.tag || ""); return m ? Math.max(mx, +m[1]) : mx; }, 0);
};
// The next free "<prefix>N" tag for a single add. For a BATCH add, call
// maxTagNum once and increment locally instead (see importCollection/cast-import).
export const nextTag = (items, prefix) => prefix + (maxTagNum(items, prefix) + 1);

// Two frames are "linked" (continuous) if they share EITHER identity field —
// mediaId (gallery-picked / generated-in-Loom frames) or thumbId (locally
// uploaded ones). The old check only looked at thumbId, so it was blind to
// exactly the frames "↳ inherit close" produces (it copies mediaId and clears
// thumbId), guaranteeing a false "needs link" warning on the tool's own
// recommended workflow.
export const frameLinked = (a, b) => !!a && !!b && (
  (!!a.mediaId && !!b.mediaId && a.mediaId === b.mediaId) ||
  (!!a.thumbId && !!b.thumbId && a.thumbId === b.thumbId)
);

// CONNECT[x] where x is a falsy/stale/legacy value throws. Every direct index
// now goes through this instead, falling back to "new scene" (the safest,
// most neutral default) rather than crashing shotText/export/render.
export const connectMeta = (connect) => CONNECT[connect] || CONNECT.new;

// ---------- board flattening + shot-text assembly ----------

export const flat = (p) => p.acts.flatMap((a, ai) => a.cards.map((c, ci) => ({ c, a, ai, ci, code: `${actLetter(ai)}·${String(ci + 1).padStart(2, "0")}` })));

export const shotText = (entry, p) => {
  const { c, code, ai } = entry;
  const idx = flat(p).findIndex((x) => x.c.id === c.id);
  const prev = idx > 0 ? flat(p)[idx - 1] : null;
  const L = [`[${code} — "${c.title || "untitled"}"]  (${c.mode}, ~${c.duration}s, ${connectMeta(c.connect).label})`, ""];
  if (c.connect === "extend" && prev) L.push(`Continue seamlessly from the previous clip ${prev.code} (upload it as @video1).`);
  if (c.connect === "flf") {
    if (c.openFrame.desc || c.openFrame.tag) L.push(`Opening frame ${c.openFrame.tag || "(first image)"}: ${c.openFrame.desc || "—"}`);
    if (c.closeFrame.desc || c.closeFrame.tag) L.push(`Closing frame ${c.closeFrame.tag || "(last image)"}: ${c.closeFrame.desc || "—"}`);
  }
  L.push("", c.prompt || "(prompt tbd)");
  if (c.connect === "extend" || c.connect === "flf") L.push(CONTINUITY_PHRASE);
  const usedCast = (p.assets || []).filter((as) => c.cast.includes(as.id));
  if (usedCast.length) { L.push("", "Keep consistent:"); usedCast.forEach((as) =>
    L.push(`  ${as.name} — ${as.lock ? "maintain exact appearance from " : "reference "}${as.tag}`)); }
  if (c.refs.length) { L.push("", "Other references:"); c.refs.forEach((r) => L.push(`  ${r.tag} — ${r.role || "(role tbd)"}${r.source ? `  [${r.source}]` : ""}`)); }
  if (c.camera) L.push("", `Camera: ${c.camera}`);
  if (c.lighting) L.push(`Lighting/Mood: ${c.lighting}`);
  if (c.audioCue) L.push(`Audio: ${c.audioCue}`);
  if (c.transIn || c.transOut) L.push(`Edit transitions: in ${c.transIn || "—"} / out ${c.transOut || "—"}`);
  if (c.notes) L.push(`Notes: ${c.notes}`);
  return L.join("\n");
};

// ---------- Generate-shot payload (drives /api/loom/generate + /api/price) ----------
// `imgSrc(thumbId, source)` is injected rather than closed-over so this stays pure:
// in master-storyboard.jsx it resolves against the component's `thumbs` state; here
// (and in tests) callers pass whatever lookup they like.
export const shotPayload = (entry, project, imgSrc) => {
  const c = entry.c;
  const tagNum = (t) => { const m = /(\d+)/.exec(t || ""); return m ? +m[1] : 99; };
  const imgs = [];
  (project.assets || []).filter((as) => as.kind === "image" && c.cast.includes(as.id))
    .forEach((as) => { const d = as.mediaId || imgSrc(as.thumbId, as.source); if (d) imgs.push({ tag: as.tag, d }); });
  // Untagged open/close frames need DISTINCT fallback tags -- both defaulting to the
  // same literal meant an FLF shot with two untagged frames silently sent duplicate
  // @image9 tags, and the model only ever saw one of the two images.
  [["@image8", c.openFrame], ["@image9", c.mode === "FLF" ? c.closeFrame : null]].forEach(([fallbackTag, f]) => {
    if (!f) return; const d = f.mediaId || imgSrc(f.thumbId, f.source); if (d) imgs.push({ tag: f.tag || fallbackTag, d }); });
  (c.refs || []).filter((r) => r.kind === "image").forEach((r) => {
    const d = r.mediaId || imgSrc(r.thumbId, r.source); if (d) imgs.push({ tag: r.tag, d }); });
  const vids = (c.refs || []).filter((r) => r.kind === "video" && /^\d+$/.test(r.source || "")).map((r) => r.source);
  imgs.sort((a, b) => tagNum(a.tag) - tagNum(b.tag));
  return { mode: c.mode, prompt: shotText(entry, project), images: imgs.map((x) => x.d),
           video_refs: vids, duration: c.duration, hasInput: (imgs.length + vids.length) > 0 };
};

// ---------- duration / pricing math feeding the timeline reel ----------

// reel uses the ACTUAL generated length when a shot has rendered, else the planned duration
export const durOf = (c) => Number(c.actualDur || c.duration) || 0;

export const reelStats = (entries, target) => {
  const total = entries.reduce((s, x) => s + durOf(x.c), 0);
  const scale = Math.max(total, target) || 1;
  const over = total - target;
  return { total, scale, over };
};
