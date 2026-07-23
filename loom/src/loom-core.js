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

// Board-level continuity indicator built on frameLinked (2026-07-23 rebuild -- frameLinked
// itself had zero callers anywhere in V2; this is the first one). Is `entryId`'s OPENING
// frame already linked to the immediately-preceding shot's CLOSING frame? `entries` must be
// the project's full, flattened, cross-act shot list (flat(project)) -- continuity is a
// timeline concept, not an act-scoped one, the same convention the frame-handoff button's
// own "previous shot" lookup already follows (see prevEntry/weavePrevEntry in
// master-storyboard.jsx). The first shot in the project -- or an id entries doesn't contain
// at all -- has no predecessor to compare against, so it is never "linked".
//
// NOT the same concept as CONNECT/connectMeta's "Continuity" chip (setShotMode/setShotConnect
// in loom-mutations.js): that couples a single shot's own Mode to its connect field (how
// THIS shot's own video generation should behave). This checks actual frame images across
// a cut; that never does.
export const continuityLinked = (entries, entryId) => {
  const idx = (entries || []).findIndex((x) => x.c.id === entryId);
  if (idx <= 0) return false;
  return frameLinked(entries[idx - 1].c.closeFrame, entries[idx].c.openFrame);
};

// CONNECT[x] where x is a falsy/stale/legacy value throws. Every direct index
// now goes through this instead, falling back to "new scene" (the safest,
// most neutral default) rather than crashing shotText/export/render.
export const connectMeta = (connect) => CONNECT[connect] || CONNECT.new;

// ---------- board flattening + shot-text assembly ----------

export const flat = (p) => p.acts.flatMap((a, ai) => a.cards.map((c, ci) => ({ c, a, ai, ci, code: `${actLetter(ai)}·${String(ci + 1).padStart(2, "0")}` })));

// effectivePrompt: the prompt text a shot actually means, honoring a hand-edited override
// over the raw field. A card in "override" mode has promptOverride:true and
// promptOverrideText holding VERBATIM text the owner typed directly into the drawer's
// composed-prompt box (Camera/Lighting/cast/etc already folded in by hand, not re-composed).
export const effectivePrompt = (c) => (c.promptOverride ? (c.promptOverrideText || "") : (c.prompt || ""));

export const shotText = (entry, p) => {
  const { c, code, ai } = entry;
  // Hard early-return, never merged with the composition below -- a promptOverride is the
  // owner's own final word on this shot's text. Composing Camera/Lighting/cast INTO an
  // already-hand-edited override on every re-sync would duplicate that scaffolding deeper
  // into the text on each cycle (the override IS usually that same composed text with one
  // clause nudged, so it already contains its own Camera/Lighting/etc lines).
  if (c.promptOverride) return effectivePrompt(c);
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
  // Project "Look": a style paragraph applied to every shot so the whole film reads as
  // one visual world. Appended to each shot's own prompt (and its shot-list text, which
  // is the same string) -- the project-level analogue of the per-shot cast block.
  if (p.look) L.push("", `Look (consistent across the film): ${p.look}`);
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
  // Draft mode renders every shot at the cheaper "basic" quality for blocking out an
  // animatic; approve the cut, turn Draft off, and re-generate the keepers at pro. Carried
  // on the payload so BOTH the price preview and the actual submit see the same quality.
  return { mode: c.mode, prompt: shotText(entry, project), images: imgs.map((x) => x.d),
           video_refs: vids, duration: c.duration, quality: project.draft ? "basic" : "professional",
           generate_audio: !!c.audioGen, audio_language: c.audioLanguage || "english",
           hasInput: (imgs.length + vids.length) > 0 };
};

// ---------- cost-to-finish pricing (shared by the toolbar's standing estimate and
// batchGenerate's own price-confirm dialog) ----------

// The only shotPayload fields the server's price math actually reads (verified against
// pixai_gallery_backup.py's price_task/_PRICE_SCALARS/_PRICE_NESTED allowlist) -- prompt
// text, camera, lighting, notes, title never affect cost, so a fingerprint built from just
// these fields lets a cost-estimate cache skip re-pricing on every keystroke elsewhere.
export const PRICE_FIELDS = ["mode", "images", "video_refs", "duration", "quality", "generate_audio", "audio_language"];
export const priceFingerprint = (payload) => JSON.stringify(PRICE_FIELDS.map((k) => payload[k]));

// {free,paid,credits,unknown} over a list of /api/price responses (nulls = failed/unknown
// price checks, counted honestly rather than as a false "0 credits"). Shared verbatim by
// batchGenerate's confirm dialog and the toolbar's standing cost-to-finish pill so there is
// exactly one place this math lives.
export const tallyPrices = (prices) => {
  let free = 0, paid = 0, credits = 0, unknown = 0;
  prices.forEach((pr) => {
    if (pr && pr.free) free++;
    else if (pr && pr.cost != null) { paid++; credits += pr.cost; }
    else unknown++;
  });
  return { free, paid, credits, unknown };
};

// formatCostEstimate/costTooltip: pure string formatters for {free,paid,credits,unknown,pending}.
// Hard rule: a displayed "0 cr"/"free" must only ever mean a genuinely settled, zero-cost
// result -- never "not yet priced" or "failed to price". Priority order is exhaustive: every
// combination of the four settled buckets plus pending maps to exactly one branch below.
export const formatCostEstimate = ({ free = 0, paid = 0, credits = 0, unknown = 0, pending = 0 } = {}) => {
  const settledNone = free === 0 && paid === 0 && unknown === 0;
  const trail = pending > 0 ? " ⟳" : "";
  if (settledNone && pending > 0) return "…";
  if (credits > 0) return `≈${credits.toLocaleString()} cr${unknown ? ` (+${unknown} unk)` : ""}${trail}`;
  if (unknown > 0) return `${unknown} unpriced${trail}`;
  if (free > 0) return `🎫 free${trail}`;
  if (paid > 0) return `0 cr${trail}`;     // settled, genuinely zero-cost, not free-card-covered
  return "…" + trail;
};
export const costTooltip = ({ free = 0, paid = 0, credits = 0, unknown = 0, pending = 0 } = {}) =>
  `Cost to finish: ${free} free-card, ${paid} paid (≈${credits.toLocaleString()} credits), ` +
  `${unknown} unpriced${pending ? `, ${pending} still estimating` : ""}.`;

// ---------- duration / pricing math feeding the timeline reel ----------

// reel uses the ACTUAL generated length when a shot has rendered, else the planned duration
export const durOf = (c) => Number(c.actualDur || c.duration) || 0;

export const reelStats = (entries, target) => {
  const total = entries.reduce((s, x) => s + durOf(x.c), 0);
  const scale = Math.max(total, target) || 1;
  const over = total - target;
  return { total, scale, over };
};
