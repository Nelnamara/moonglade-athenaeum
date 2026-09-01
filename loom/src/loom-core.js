/* =========================================================================
   loom-core.js — pure, framework-agnostic logic extracted out of
   master-storyboard.jsx (Phase 1 tooling pass, 2026-07-16).

   NO React import, no DOM/window access, no `fetch` -- everything here is
   deterministic given its arguments, so it is safe to `node --test` directly
   (see loom/test/loom-core.test.js).

   Two consumers, both must keep working:
     1. master-storyboard.jsx imports this as a real ES module and esbuild
        bundles the two together (loom/scripts/build.mjs -> loom/dist/).
     2. The Flask /loom route (moonglade_gallery.py, `loom()`) ALSO inlines this
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

// The number a tag CLAIMS in the "@imageN" namespace, or 0 for "claims nothing at all"
// (empty, "hero", "ref3", "@video2"). Anchored on purpose, and deliberately the SAME reading
// maxTagNum uses above: for a while shotImageRefs()'s slot ordering and pickTarget()'s tag
// arithmetic ran two different parsers over one namespace -- an anchored `^@image(\d+)$` for
// the max, an unanchored `(\d+)` for the sort -- so an owner-typed "ref3" was worth nothing to
// one and slot 3 to the other, and a freshly picked reference landed in a different slot than
// the drawer had just reported picking. Zero is safe as the "no claim" answer because live
// positions are 1-based, so it can never be mistaken for one.
const imageClaim = (tag) => { const m = /^@image(\d+)$/.exec(tag || ""); return m ? +m[1] : 0; };

// Is `s` a catalog media_id -- i.e. something /thumbs/<id>.jpg will actually serve?
//
// TWO id families, and the Loom knew only one. A PixAI generation's media_id is all digits;
// an imported local file's is `local_<12 hex>` (moonglade_backup.local_media_id, content-
// addressed since the path-hash collision fix). Both get a thumbnail written to the same
// place and both are served by the same /thumbs/<media_id>.jpg route -- but eight separate
// `/^\d+$/` tests across this file, loom-mutations.js, master-storyboard.jsx and
// mg-generate-drawer.js each independently decided a media_id was digits, so every imported
// picture was invisible to the Loom: dropped by the gallery's "Send to cast" import, then
// unresolvable as a cast picture, then unthumbnailable in the drawer's preview. The owner
// found it the honest way -- selected two imported images plus a video, sent them to the
// cast, and the Loom opened empty (2026-07-28).
//
// Deliberately NOT the same question as parseCastIdsFromSearch()'s filter, which is a URL
// *sanitiser* and stays a character allowlist: a sanitiser that also encodes the id grammar
// has to be edited every time a third id family appears, which is how this one rotted.
export const isCatalogMediaId = (s) => /^(?:\d+|local_[0-9a-f]{12})$/.test(String(s == null ? "" : s));

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

// ---------- shot-level "what image is this" list (single source of truth for BOTH the
// composed prompt's @imageN citations AND the Multi-Reference drawer's own image bank) ----
//
// the 2026-07-21 audit's owner-filed "Loom shot-card reference sending bugs out past 2
// images" row traced the corruption to two DIFFERENT, un-synced numbering systems that both
// happen to use the same "@imageN" syntax:
//   1. A project-GLOBAL tag on each cast asset (assigned once, in cast-add order -- see
//      nextTag/maxTagNum above -- e.g. a cast member added 4th is "@image4" forever, project-
//      wide, regardless of which shots actually use them).
//   2. The Multi-Reference drawer's OWN per-shot numbering (the React <VideoDrawer>'s refMap(),
//      gallery/src/components/VideoDrawer.jsx), which has zero concept of a global tag namespace -- it always
//      labels whatever lands in its image bank "@image1", "@image2", ... purely by ARRAY
//      POSITION, in the exact order shotPayload()/buildShotPayload() hands it (see that
//      function's own prefill-effect comment in master-storyboard.jsx).
// These only agree when a shot happens to use every cast member from @image1 up with no gaps.
// The moment a shot uses a LATER-numbered cast member (e.g. a 4th-added "Greg" = @image4)
// without also using every earlier one, shotText() used to cite Greg's real, stable @image4 --
// but the drawer's image bank, fed the SAME image tag-less and re-numbered by position, calls
// that same picture something else entirely (e.g. @image1 or @image2). Once anything forces
// the drawer to round-trip the composed prompt through its own chip/reference system (opening
// the "Pick from your gallery" picker steals DOM focus off the drawer's prompt box, and its
// blur handler synchronously re-chipifies), a real "@imageN" citation can get silently
// reinterpreted against the WRONG picture, or a mismatched round-trip freezes the (now wrong)
// text as a hand-edited override. shotImageRefs()/positionTag() are the single place that
// numbers a shot's own images -- shotText() and shotPayload() both go through them now, so
// whatever @imageN the composed prompt names for a picture is, by construction, the exact same
// @imageN the drawer's own Image References panel shows for that same picture.
//
// The ONE image-resolution rule every consumer shares: a durable gallery mediaId wins, else
// whatever the injected imgSrc lookup can make of a local thumbId/source pair. Extracted
// (2026-07-27, closing-frame pass) because castMissingImages()/castPastBudget() below need
// to ask "does this entity HAVE a picture" separately from "did it WIN a slot" -- two
// questions PixAI's 6-slot cap makes genuinely different -- and a second hand-rolled copy
// of this expression is exactly the silent-drift failure this file's header catalogs.
export const resolvedImage = (x, resolve) => (x && (x.mediaId || resolve(x.thumbId, x.source))) || null;

// CLOSING-FRAME PARTICIPATION (2026-07-27 -- the FIFTH manifestation of this file's
// un-synced-@imageN-numbering bug class; the FRAME RESERVATION and REF ORDER comments below
// are the third and fourth). The closing frame used to join the numbering only for
// `c.mode === "FLF"`, a leftover from when FLF was the only mode whose generation was
// thought to consume an end frame. But the server treats R2V and V2V identically at submit
// (both resolve to the same build_shot_video_params path -- see CHANGELOG; the owner
// confirms end-frame reference works on V4.0), and R2V's payload is built from
// buildShotPayload() -> shotImageRefs(), so an R2V shot with both frames attached produced
// every symptom in the owner's filing at once: the card's Closing Frame read "--"
// (positionTag() had no item to number), cast counted from @image2 instead of @image3, and
// the closing frame never reached the generator at all -- silently absent from
// payload.images on a paid render. The mode list is a named, exported predicate so no other
// surface ever re-derives it ad hoc and drifts (the two-numbering-systems corruption above
// started exactly that way). I2V stays out: its generation consumes only the opening frame,
// and closeFrame's mode-INDEPENDENT roles (continuityLinked(), the "inherit close" handoff)
// read c.closeFrame directly, never this list.
//
// A frame still only enters `items` when it RESOLVES to an image -- no placeholders. Round 1
// of this fix was refuted in adversarial review for "reserving" @image2 while the closing
// slot was still EMPTY: that put two entities on screen claiming one @imageN (the empty
// slot's hold-tag vs a live cast member's tag), this bug class's founding sin re-introduced
// on purpose. An empty frame claims NOTHING; cast numbers shift up the moment a frame is
// attached, and that is correct -- do not reintroduce reserved-empty entries here.
export const CLOSE_FRAME_MODES = ["FLF", "R2V", "V2V"];
export const usesCloseFrame = (mode) => CLOSE_FRAME_MODES.includes(mode);

// `imgSrc(thumbId, source)` is injected rather than closed-over so this stays pure: in
// master-storyboard.jsx it resolves against the component's `thumbs` state; here (and in
// tests) callers pass whatever lookup they like.
export const shotImageRefs = (entry, project, imgSrc) => {
  const c = entry.c;
  const items = [];
  (project.assets || []).filter((as) => as.kind === "image" && c.cast.includes(as.id))
    .forEach((as) => { const d = resolvedImage(as, imgSrc); if (d) items.push({ tag: as.tag, d, kind: "cast", id: as.id }); });
  // Untagged open/close frames need DISTINCT fallback tags -- both defaulting to the
  // same literal meant an FLF shot with two untagged frames silently sent duplicate
  // @image9 tags, and the model only ever saw one of the two images. No code READS those two
  // literals: they are invented for one render pass, never written back to the frame (whose
  // own .tag stays empty), the ordering below ignores them (frames rank by KIND), and every
  // citation the composed prompt emits comes from positionTag()'s live position. pickTarget()
  // counting them as numbers the shot had claimed is what stamped "@image10" on a 3-image
  // shot -- see its own comment.
  [["@image8", "openFrame", c.openFrame], ["@image9", "closeFrame", usesCloseFrame(c.mode) ? c.closeFrame : null]].forEach(([fallbackTag, key, f]) => {
    if (!f) return; const d = resolvedImage(f, imgSrc); if (d) items.push({ tag: f.tag || fallbackTag, d, kind: "frame", id: key }); });
  (c.refs || []).filter((r) => r.kind === "image").forEach((r) => {
    const d = resolvedImage(r, imgSrc); if (d) items.push({ tag: r.tag, d, kind: "ref", id: r.id }); });
  // FRAME RESERVATION (2026-07-23, "frame/cast @imageN slot collision" -- the THIRD
  // manifestation of this file's un-synced-numbering bug class; follow-up to commit 2e714fd
  // and commit c7aaff2). Opening/Closing Frame now ALWAYS sort ahead of cast/refs, by KIND,
  // regardless of whatever their own raw .tag field says. A frame's .tag is independently
  // owner-editable (master-storyboard.jsx's FrameSlot tag input) and can carry any text,
  // including one that happens to collide with a cast member's real, stable project-global
  // tag (e.g. both claiming "@image1"). Sorting by raw tag text let whichever entry got
  // pushed into `items` first -- always a cast asset, by construction above -- silently win
  // the disputed slot, bumping the frame to a DIFFERENT number than the one its own UI
  // statically displayed (the owner's report: a cast member "usurped" the frame's slot).
  // Frame identity now wins the first slot(s) by construction instead: Opening Frame is
  // always @image1 and Closing Frame (FLF only) is always @image2, whenever each resolves to
  // an actual image, because they are structurally load-bearing for FLF/i2v generation itself
  // (not flavor, like a cast portrait or an extra reference) and the UI already presents them
  // first, above "Other references & @tags". Cast/refs fill in from @image3 on. Two frame
  // items never compete with each other on tag text either (both get sortNum 0) -- their
  // relative order is Open-before-Close by construction (the push order above), never by
  // whatever stale text either one's .tag holds. See positionTag()'s callers (shotText's
  // frame-description lines, FrameSlot's own live-tag display) -- none of them may trust a
  // frame's raw .tag as anything but a fallback for when it has no resolvable image at all.
  // REF ORDER (2026-07-27, M35 -- the FOURTH manifestation, and the reason the third's
  // "rank by KIND, never by raw tag text" rule now extends one tier down). A shot-level ref's
  // .tag is free text too (Deep Focus's per-ref tag input), and addRef() numbers a new one
  // only against the CARD's own refs -- so a shot holding cast "@image3" and a first ref
  // "@image1" sorted the ref ahead of the cast member, while every surface that shows the two
  // lists shows cast first ("Keep consistent:" above "Other references:" in shotText(), Cast
  // & assets above Other references in Deep Focus). Refs now take their own rank behind cast
  // and keep c.refs array order among themselves -- the same order shotText() prints them in,
  // so that block's citations read 1, 2, 3 down the page instead of jumping.
  // The load-bearing consequence is pickTarget(): once slot order no longer depends on the
  // appended ref's own tag, that tag is free to BE the ref's real position -- which is what
  // the drawer, the prompt and the owner all read it as -- instead of a number inflated past
  // everything else in the shot purely to win a sort. Cast keeps sorting by its own claim
  // (a project-global number, assigned in cast-add order); a cast tag that claims nothing in
  // the @imageN namespace sorts to the back of the cast tier rather than silently borrowing
  // whatever digits happen to be in it.
  const kindRank = (it) => (it.kind === "frame" ? 0 : it.kind === "cast" ? 1 : 2);
  const sortNum = (it) => (it.kind === "cast" ? (imageClaim(it.tag) || Number.MAX_SAFE_INTEGER) : 0);
  items.sort((a, b) => kindRank(a) - kindRank(b) || sortNum(a) - sortNum(b));
  // PixAI's real cap: a generation takes at most 6 image refs. Reserving frames first means
  // a shot that has to drop something under this cap always drops a lower-priority cast/ref,
  // never a structurally load-bearing frame -- the same "keep the highest-priority N, leave
  // the rest out" truncation moonglade_gallery.py's bulkSendVideo()/Gen.addVideoRefs() already
  // apply to the gallery's own bulk-send-to-video path (same real 6-image limit, trimmed
  // before ever reaching submit). shotPayload() is what actually builds the /api/loom/
  // generate body (both batchGenerate's direct call and the drawer's own prefill route
  // through it), so capping here guarantees the real submit never exceeds it either way.
  return items.slice(0, 6);
};

// No-op resolver for shotText() callers that have no live `thumbs` state to close over (the
// shot-list export, copyShot, the several "did the hand-edit actually change anything"
// comparisons) -- trusts only mediaId, the same thing shotPayload's own imgSrc contract
// already means for an asset/ref with no gallery media_id yet. Keeps shotText() callable as
// shotText(entry, project) everywhere it already is today (every master-storyboard.jsx call
// site but the live drawer-prefill one, and every test in loom-core.test.js).
const noImgSrc = () => null;

// This shot's OWN "@imageN" for one cast asset or c.refs entry, numbered purely by POSITION
// within shotImageRefs()'s sorted list -- see that function's own comment for why this must
// replace a raw, project-global .tag anywhere the text is going to reach the Multi-Reference
// drawer. Returns null when `id` has no resolvable image in THIS shot (nothing for the drawer
// to number at all); callers fall back to the entity's own stored .tag in that case, exactly
// matching prior behavior for a not-yet-resolvable reference.
export const positionTag = (entry, project, imgSrc, id) => {
  const items = shotImageRefs(entry, project, imgSrc);
  const idx = items.findIndex((it) => it.id === id);
  return idx < 0 ? null : "@image" + (idx + 1);
};

// Multi-Reference drawer pick-persistence plan (the 2026-07-21 audit "reference picker
// corruption" row, requirement 2: adding a 3rd/4th reference via the picker must actually
// work). A pick used to ONLY ever update the drawer's own private, in-memory bank -- nothing
// host-side ever recorded it, so it was silently discarded the next time ANY host-tracked
// field changed and the prefill effect rebuilt the drawer's bank fresh from shotPayload()
// (that is why "the Image References panel never advances past its original entries").
// Given the drawer reports a completed pick at its own bank SLOT INDEX, this decides what the
// host must durably do with it: replace whichever entity (cast asset / shot ref / open-close
// frame) ALREADY supplies that slot's current picture (never assume slot index == that
// entity's array index -- see shotImageRefs()'s own comment), or append a brand-new
// shot-level reference, tagged past every tag this shot already uses so it reliably sorts to
// the final slot, when the slot is past everything the shot currently supplies. Pure/
// testable -- master-storyboard.jsx's mg-pick-request listener is the only caller, and just
// carries out whichever plan this returns.
export const pickTarget = (entry, project, imgSrc, slot) => {
  const items = shotImageRefs(entry, project, imgSrc);
  const existing = items[slot];
  if (existing) return { type: "replace", kind: existing.kind, id: existing.id };
  const c = entry.c;
  // The appended ref is stored with the "@imageN" of the slot it actually LANDS IN. N starts
  // at items.length + 1 because REF ORDER (see shotImageRefs) puts a newly appended c.refs
  // entry last by construction, so that is the position positionTag() and the drawer's own
  // bank will both report for it the instant the pick is written -- stored tag and live
  // citation agree by arithmetic, not by luck.
  //
  // This used to be nextTag(items, "@image"): one past the highest number anything in the
  // shot happened to hold, which existed only to win the old tag-text sort and produced
  // numbers with no relation to the shot at all. An FLF shot with two untagged frames (whose
  // "@image8"/"@image9" are shotImageRefs()'s own invention for one render pass, stored
  // nowhere) plus one "@image1" cast member -- 3 real images -- stamped its 4th picked
  // reference "@image10", on a bank PixAI caps at 6. Filtering the invented 8/9 back out was
  // not enough and made it worse: the max then landed on "@image2", a number this shot really
  // does use (the Closing Frame), so the moment that ref dropped out of the live numbering
  // shotText() cited a picture that IS in the prompt but is not the one the ref means -- the
  // exact misdirection this file's header says positionTag() exists to prevent.
  //
  // The bump loop is the one thing raw position cannot give up: two entities on one card must
  // never DISPLAY the same @imageN. `claims` is every tag this shot's own entities hold,
  // including the ones shotImageRefs() cannot see -- a ref added with "+ reference" that has
  // no picture yet is absent from `items` and still shows its tag in Deep Focus, and a cast
  // member's tag is project-global. (pickVideoTarget() below has guarded exactly this for the
  // video bank since it was written; the image side never did.) The loop only ever moves N UP,
  // so the stored tag is never below the ref's real position and can never steal a slot number
  // something else is already showing.
  const claims = new Set([
    ...(project.assets || []).filter((as) => (c.cast || []).includes(as.id)).map((as) => as.tag),
    (c.openFrame || {}).tag, (c.closeFrame || {}).tag,
    ...(c.refs || []).filter((r) => r.kind === "image").map((r) => r.tag),
  ].map(imageClaim).filter(Boolean));
  let n = items.length + 1;
  while (claims.has(n)) n++;
  return { type: "append", tag: "@image" + n };
};

// ---------- r2v video-reference bank pick persistence (parallel to pickTarget() above) ---
// The Multi-Reference drawer's SEPARATE video-reference bank (the React <VideoDrawer>'s
// vidSlots, requested with bank:"vid") has the exact same "a pick only ever lands in the
// drawer's own private slots" gap pickTarget() closes for the image bank -- but it can't
// reuse shotImageRefs()/pickTarget() as-is: video refs carry their media id in c.refs' own
// .source field as a numeric STRING (see shotPayload()'s `vids` computation below), never
// .mediaId the way cast/frames/image-refs do, and there's no cast/frame equivalent to fold
// in -- a video ref only ever comes from c.refs itself. Small enough to stay its own pair of
// functions rather than bending shotImageRefs()'s shape to fit.
export const shotVideoRefs = (entry) => (entry.c.refs || []).filter((r) => r.kind === "video" && isCatalogMediaId(r.source));

export const pickVideoTarget = (entry, slot) => {
  const items = shotVideoRefs(entry);
  const existing = items[slot];
  if (existing) return { type: "replace", id: existing.id };
  // Tag uniqueness is scoped to EVERY video-kind ref on the card (matching addRef()'s own
  // nextTag(card.refs.filter(kind), pre) convention in master-storyboard.jsx), not just the
  // resolvable ones shotVideoRefs() above returns for slot alignment -- an owner-typed video
  // ref with no source yet (Deep Focus's "file name or URL" field starts empty) still holds
  // its tag, and a newly-appended ref must never collide with it.
  const allVideoRefs = (entry.c.refs || []).filter((r) => r.kind === "video");
  return { type: "append", tag: nextTag(allVideoRefs, "@video") };
};

// Names of cast members this shot lists but has no picture for AT ALL. shotText() leaves
// them OUT of the prompt (citing an @imageN with nothing behind it is worse than saying
// nothing), so this is what stops that being silent: the board card shows it, where it can
// be fixed. Deliberately NOT put in the prompt itself -- that text is sent to PixAI, and "no
// reference image attached" is noise in a generation request.
//
// "Has no picture" is asked with resolvedImage(), NOT positionTag() (which this used to
// trust): once the closing frame joined the numbering for R2V/V2V (usesCloseFrame above), a
// 6th cast member on a two-frame shot loses its slot to PixAI's 6-image cap while holding a
// perfectly good picture. positionTag() returns null for BOTH "no picture" and "capped", so
// reading it here reported the capped case as "no image" -- telling the owner to fix a
// picture that was never broken (this exact misfire is one of the findings that refuted
// round 1 of the closing-frame fix). castPastBudget() below is the capped half's honest
// report. The `kind === "image"` test keeps the old answer for a video/audio cast member --
// never image-referenceable, still reported here, exactly as before.
export const castMissingImages = (entry, p, imgSrc) => {
  const resolve = imgSrc || noImgSrc;
  return (p.assets || [])
    .filter((as) => (entry.c.cast || []).includes(as.id))
    .filter((as) => !(as.kind === "image" && resolvedImage(as, resolve)))
    .map((as) => as.name || "(unnamed)");
};

// Names of cast members that HAVE a picture and are still not sent: they lost the 6-slot
// contest (frames first, then cast, then refs -- shotImageRefs()'s own ordering). Asked via
// positionTag() ON PURPOSE: a resolvable entity positionTag() cannot number is, by
// construction, one the slice(0, 6) trimmed -- the cap's own signal, from the SAME ordering
// that actually trims. Do not re-derive the ordering a second way here; two implementations
// of one ordering is the two-numbering-systems corruption this whole file exists to end.
// The board card renders this as "past the reference limit -- not sent" (drop a reference
// or a frame to fit), a different repair from castMissingImages' "attach a picture".
export const castPastBudget = (entry, p, imgSrc) => {
  const resolve = imgSrc || noImgSrc;
  return (p.assets || [])
    .filter((as) => (entry.c.cast || []).includes(as.id))
    .filter((as) => as.kind === "image" && resolvedImage(as, resolve) && !positionTag(entry, p, resolve, as.id))
    .map((as) => as.name || "(unnamed)");
};

// The Cast & assets panel's live reference-slot arithmetic (owner decision, 2026-07-27):
// PixAI takes 6 reference images per generation, and an attached frame claims its slot only
// when it actually RESOLVES to an image (no reserved-empty entries -- see usesCloseFrame's
// comment for the refuted round-1 alternative), so the cast/ref budget is 6 minus attached
// frames: 4 with both frames, 5 with one, 6 with none. `frames` is counted off
// shotImageRefs()'s own items rather than by re-testing the frame fields, so this can never
// disagree with the list that actually ships; frames can never themselves be trimmed (they
// sort first and there are at most two). `used` counts every in-cast image asset and image
// ref that resolves to a picture, deliberately UNCAPPED -- used > budget is exactly the
// "something below is not being sent" state the panel must not hide (shotImageRefs slices
// to 6, so the overflow would otherwise vanish without a trace).
export const refBudget = (entry, p, imgSrc) => {
  const resolve = imgSrc || noImgSrc;
  const c = entry.c;
  const frames = shotImageRefs(entry, p, resolve).filter((it) => it.kind === "frame").length;
  const used =
    (p.assets || []).filter((as) => as.kind === "image" && (c.cast || []).includes(as.id) && resolvedImage(as, resolve)).length +
    (c.refs || []).filter((r) => r.kind === "image" && resolvedImage(r, resolve)).length;
  return { used, budget: 6 - frames, frames };
};

export const shotText = (entry, p, imgSrc) => {
  const { c, code, ai } = entry;
  // Hard early-return, never merged with the composition below -- a promptOverride is the
  // owner's own final word on this shot's text. Composing Camera/Lighting/cast INTO an
  // already-hand-edited override on every re-sync would duplicate that scaffolding deeper
  // into the text on each cycle (the override IS usually that same composed text with one
  // clause nudged, so it already contains its own Camera/Lighting/etc lines).
  if (c.promptOverride) return effectivePrompt(c);
  const resolve = imgSrc || noImgSrc;
  const idx = flat(p).findIndex((x) => x.c.id === c.id);
  const prev = idx > 0 ? flat(p)[idx - 1] : null;
  const L = [`[${code} — "${c.title || "untitled"}"]  (${c.mode}, ~${c.duration}s, ${connectMeta(c.connect).label})`, ""];
  if (c.connect === "extend" && prev) L.push(`Continue seamlessly from the previous clip ${prev.code} (upload it as @video1).`);
  // Gated on MODE, not connect. shotImageRefs() -- the function that actually reserves the
  // frame slots -- used to decide by `c.mode === "FLF"` too, so gating the DESCRIPTIONS on
  // `c.connect` meant the two disagreed: a shot set to FLF mode had both frames attached and
  // sent, with nothing in the prompt saying what they were, and the reverse case described
  // frames that no slot had been reserved for. The descriptions earn their place -- telling
  // the model what the opening and closing images are is what makes the motion between them
  // land.
  //
  // DELIBERATELY NARROWER than usesCloseFrame() (2026-07-27): the closing frame now joins
  // the NUMBERING for R2V/V2V as well, but these description lines stay FLF-only. Round 1
  // of that fix widened this gate to match and was refuted for it: with frames routinely
  // undescribed on R2V shots it emitted "Opening frame @image1: —" noise on every one, and
  // the `|| c.openFrame.tag` fallbacks below re-opened the raw-.tag wrong-picture citations
  // M35 deleted. How a composed R2V prompt should talk about its frames is a real question
  // deliberately left unanswered for now -- widen this only with an actual answer, not to
  // make the two gates look symmetrical.
  if (c.mode === "FLF") {
    // positionTag(), not the frame's own raw .tag -- see shotImageRefs()'s frame-reservation
    // comment. A frame's raw .tag is free text the owner can edit in FrameSlot's UI and can
    // drift from its actual, guaranteed slot (e.g. it still reads "@image2" from before the
    // shot's cast composition changed, while the frame is now really reserved @image1).
    // positionTag() is always the live, structurally-guaranteed number -- falls back to the
    // raw tag only when the frame has no resolvable image in THIS shot at all (nothing live
    // to number, matching every other fallback in this function).
    const openTag = positionTag(entry, p, resolve, "openFrame") || c.openFrame.tag;
    const closeTag = positionTag(entry, p, resolve, "closeFrame") || c.closeFrame.tag;
    if (c.openFrame.desc || openTag) L.push(`Opening frame ${openTag || "(first image)"}: ${c.openFrame.desc || "—"}`);
    if (c.closeFrame.desc || closeTag) L.push(`Closing frame ${closeTag || "(last image)"}: ${c.closeFrame.desc || "—"}`);
  }
  L.push("", c.prompt || "(prompt tbd)");
  if (c.connect === "extend" || c.connect === "flf") L.push(CONTINUITY_PHRASE);
  // Project "Look": a style paragraph applied to every shot so the whole film reads as
  // one visual world. Appended to each shot's own prompt (and its shot-list text, which
  // is the same string) -- the project-level analogue of the per-shot cast block.
  if (p.look) L.push("", `Look (consistent across the film): ${p.look}`);
  // Only cast/refs this shot actually HAS a picture for. positionTag() returns the live,
  // structurally-guaranteed @imageN a picture occupies in THIS shot; nothing means the shot
  // carries no image for them, and the old `|| as.tag` fallback then cited their project-
  // GLOBAL tag instead -- "Greg — reference @image4" when no @image4 is attached and the
  // drawer, which numbers purely by position, calls something else that. That is exactly the
  // two-numbering-systems corruption the long comment above shotImageRefs() describes, and
  // the fallback quietly re-opened it. A miscast shot is not silently swallowed: the board
  // card flags a cast member with no picture (see castMissingImages), which is where it can
  // be seen and fixed, rather than in text that gets sent to PixAI.
  const usedCast = (p.assets || []).filter((as) => c.cast.includes(as.id))
    .map((as) => ({ as, tag: positionTag(entry, p, resolve, as.id) }))
    .filter((x) => x.tag);
  if (usedCast.length) { L.push("", "Keep consistent:"); usedCast.forEach(({ as, tag }) => {
    L.push(`  ${as.name} — ${as.lock ? "maintain exact appearance from " : "reference "}${tag}`);
  }); }
  // An IMAGE ref with no live position is left out entirely -- citing an "@imageN" this shot
  // does not number is either noise the model drops or, worse, an instruction pointing at a
  // different picture (see castMissingImages above for the same rule applied to cast, and
  // shotImageRefs()'s header for why a raw .tag cannot be trusted as a fallback).
  //
  // A VIDEO ref is not the same case and must not be filtered with it. positionTag() only ever
  // numbers shotImageRefs(), which is images by definition, so it returns null for EVERY video
  // ref -- filtering on it alone silently dropped "@video1" out of every composed prompt that
  // had one. "@videoN" is its own namespace, assigned by pickVideoTarget() over the card's own
  // video refs and never renumbered by position, so the stored tag is not a fallback there: it
  // is the only name that ref has, and it is always correct.
  const usedRefs = (c.refs || [])
    .map((r) => ({ r, tag: positionTag(entry, p, resolve, r.id) || (r.kind === "image" ? null : r.tag) }))
    .filter((x) => x.tag);
  if (usedRefs.length) { L.push("", "Other references:"); usedRefs.forEach(({ r, tag }) => {
    L.push(`  ${tag} — ${r.role || "(role tbd)"}${r.source ? `  [${r.source}]` : ""}`);
  }); }
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
  const imgs = shotImageRefs(entry, project, imgSrc);   // already capped at 6 -- see its own comment
  // PixAI's real cap: at most 3 @video refs on a reference-video generation -- the video-side
  // twin of shotImageRefs()'s own 6-image cap (see that function's comment for the precedent
  // this mirrors). Nothing currently stops a shot from accumulating more than 3 video-kind
  // c.refs entries over its editing history; capping here, at the one place that builds the
  // actual /api/loom/generate body, guarantees the real submit never exceeds it regardless of
  // which surface (batchGenerate's direct call or the drawer's own prefill) triggered it.
  const vids = (c.refs || []).filter((r) => r.kind === "video" && isCatalogMediaId(r.source)).map((r) => r.source).slice(0, 3);
  // Draft mode renders every shot at the cheaper "basic" quality for blocking out an
  // animatic; approve the cut, turn Draft off, and re-generate the keepers at pro. Carried
  // on the payload so BOTH the price preview and the actual submit see the same quality.
  return { mode: c.mode, prompt: shotText(entry, project, imgSrc), images: imgs.map((x) => x.d),
           video_refs: vids, duration: c.duration, quality: project.draft ? "basic" : "professional",
           generate_audio: !!c.audioGen, audio_language: c.audioLanguage || "english",
           // The Channel (Normal/Private) -- the SAME real field mg-generate-drawer's own
           // channel select has always submitted (is_private: enhanced), and the server's
           // shared build_shot_video_params has accepted on this route all along; the Loom
           // client just never sent it (2026-08-06, owner correction -- an earlier audit
           // wrongly recorded "no channel field exists in the real backend contract").
           // Absent/false = Normal, matching the drawer's own default.
           is_private: !!c.isPrivate,
           hasInput: (imgs.length + vids.length) > 0 };
};

// ---------- cost-to-finish pricing (shared by the toolbar's standing estimate and
// batchGenerate's own price-confirm dialog) ----------

// The only shotPayload fields the server's price math actually reads (verified against
// moonglade_backup.py's price_task/_PRICE_SCALARS/_PRICE_NESTED allowlist) -- prompt
// text, camera, lighting, notes, title never affect cost, so a fingerprint built from just
// these fields lets a cost-estimate cache skip re-pricing on every keystroke elsewhere.
export const PRICE_FIELDS = ["mode", "images", "video_refs", "duration", "quality", "generate_audio", "audio_language"];
export const priceFingerprint = (payload) => JSON.stringify(PRICE_FIELDS.map((k) => payload[k]));

// ---- multi-ticket free cards (issue #15) ----
// /api/price's `free` is the server's card_covers() verdict for ONE job priced alone: a
// card matched AND the tickets held cover that job's consumeAmount. Two honesty problems
// remain on the client side, both handled here so every Loom surface reads one answer:
//  (a) SHORT: a card matched but held < needed (`card_short`, with `cards_held` /
//      `cards_needed` / `card_name` alongside). OWNER RULING: the app still spends -- the
//      site does the same -- but nothing is attached and the FULL price is charged, so the
//      confirm must say exactly that and never read as partial application.
//  (b) POOL: each shot is priced independently against the SAME ticket pool, so a batch of
//      three 15s shots (3 tickets each) against 5 held prices as three "free" shots when
//      only the first is really funded. tallyPrices below spends the pool per template in
//      submission order and reclassifies the overflow as paid at full price -- so a "will
//      spend" shot is called out BEFORE the confirm, not discovered on the invoice.

// True when the price result is the SHORT case: matched, not covered. `card_short` is the
// server's own flag; the held/needed comparison is only a fallback for a response that
// carries the counts but predates the flag, and it can never widen coverage -- `free`
// (the server's card_covers) is checked first and stays authoritative.
export const priceIsShort = (pr) => {
  if (!pr || pr.free) return false;          // the server's card_covers verdict is authoritative
  if (pr.card_short === true) return true;
  const held = cardHeld(pr);
  return held != null && held < cardNeed(pr);
};

// The one honest sentence for the SHORT case -- the client twin of moonglade_backup.py's
// card_short_note(): nothing is attached, the FULL price is charged. `subject` names the
// job in the caller's own words ("this 15s shot", "this").
export const shortSpendLine = (pr, subject = "this") => {
  const need = Math.max(1, Number(pr && pr.cards_needed) || 1);
  const heldN = cardHeld(pr);
  const name = (pr && pr.card_name) ? `${pr.card_name} ` : "";
  const tail = (pr && pr.cost != null)
    ? `It will spend the full ~${Number(pr.cost).toLocaleString()} credits.`
    : "It will spend the full credit price.";
  // UNKNOWN balance (server: balance_unknown / cards_held null) is NOT "not enough" -- that
  // asserts a fact nobody read. Say the balance couldn't be read; the outcome (no card,
  // full price) is the same, the reason is honest.
  if (heldN == null || (pr && pr.balance_unknown)) {
    return `Couldn't read how many free ${name}tickets you hold (${subject} needs ${need}), so no card will be attached. ${tail}`;
  }
  return `You hold ${heldN} of the ${need} free ${name}cards ${subject} needs — not enough, so no card is used. ${tail}`;
};

// Null-safe ticket-count parsers -- ONE definition of "tickets held/needed" for every Loom
// reader (priceIsShort, shortSpendLine, the tally). `Number(null)` is 0, which is a REAL
// balance, so a bare Number() turned "unknown" into "zero held" and booked server-FREE shots
// as paid (review 2026-08-16). null/undefined/'' -> null (unknown); junk -> null.
export const cardHeld = (pr) => {
  const v = pr && pr.cards_held;
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};
export const cardNeed = (pr) => {
  const n = Number(pr && pr.cards_needed);
  return Number.isFinite(n) && n >= 1 ? n : 1;
};

// Template key a free result draws its tickets from: the server's card_template when it
// sends one, else the card's display name. Null = the response predates both fields (or is
// not free), so the pool cannot be tracked and the server's own verdict stands.
const cardPoolKey = (pr) => (pr && (pr.card_template || pr.card_name)) || null;

// {free,paid,credits,unknown,overflow,pools} over a list of /api/price responses IN
// SUBMISSION ORDER (nulls = failed/unknown price checks, counted honestly rather than as a
// false "0 credits"). Template-aware: a shot the server priced free is only counted free
// while its template's held tickets still fund it; once the pool runs dry the rest of that
// template's shots are `overflow` -- counted as PAID at their full price, because that is
// what the site charges when the card comes up short at submit time. `pools` is
// {key: {name, held, needed}} for the confirm dialog to explain the shortfall.
export const tallyPricesDetailed = (prices) => {
  let free = 0, paid = 0, credits = 0, unknown = 0, overflow = 0;
  const pools = {};
  const overflowIndexes = [];
  // Pool balance = the MIN cards_held seen for that template across the list, fail-closed.
  // Results are priced at different times (the standing cost-to-finish pill mixes cached
  // entries; a generate in between lowers the real balance), and the old code fixed `held`
  // from the FIRST result and ignored every later reading -- so a stale-high first read
  // let later shots count as free that the pool could no longer fund. Pre-pass so order
  // of arrival can't decide the answer.
  prices.forEach((pr) => {
    if (!(pr && pr.free)) return;
    const key = cardPoolKey(pr), held = cardHeld(pr);
    if (!key || held == null) return;
    const pool = pools[key] || (pools[key] = { name: pr.card_name || key, held, needed: 0, left: held });
    if (held < pool.held) { pool.held = held; pool.left = held; }
  });
  prices.forEach((pr, i) => {
    if (pr && pr.free) {
      const key = cardPoolKey(pr);
      const need = cardNeed(pr);
      const held = cardHeld(pr);
      // Only a KNOWN balance can be drained. An unknown one (cards_held null -- the server
      // still said free, e.g. a 1-ticket job on an unread balance) is not a zero balance:
      // Number(null) is 0 and used to book these server-FREE shots as overflow/paid.
      if (key && held != null) {
        const pool = pools[key];
        pool.needed += need;
        if (pool.left >= need) { pool.left -= need; free++; return; }
        // Pool exhausted: the site attaches nothing and charges full price for this one.
        // NOTE this drains only the template the server chose when pricing this shot ALONE;
        // if a second template also covers, the submit path (which re-runs coverage live)
        // may still cover it -- so callers word overflow as an upper bound, not a certainty.
        overflow++;
        overflowIndexes.push(i);
        if (pr.cost != null) { paid++; credits += pr.cost; } else unknown++;
        return;
      }
      free++;                       // no pool info to track against -- the server's verdict stands
    }
    else if (pr && pr.cost != null) { paid++; credits += pr.cost; }
    else unknown++;
  });
  Object.values(pools).forEach((p) => { delete p.left; });
  return { free, paid, credits, unknown, overflow, pools, overflowIndexes };
};

// {free,paid,credits,unknown} -- the four-bucket shape every existing caller consumes
// (batchGenerate's dialog, the toolbar's standing cost-to-finish pill, the per-shot
// previews). Same pool-aware math as tallyPricesDetailed, minus the explanatory fields, so
// there is exactly one place this math lives.
export const tallyPrices = (prices) => {
  const { free, paid, credits, unknown } = tallyPricesDetailed(prices);
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

// ---------- full-bundle export: naming what did NOT travel (M24) ----------
//
// /api/loom/export-bundle zips the project plus every media file it references and answers
// with two headers: X-Bundle-Missing-Count (the true total, authoritative) and
// X-Bundle-Missing (the ids themselves, comma-separated and deliberately LENGTH-CAPPED -- a
// header that grows with the project is how a bundle downloads fine on the machine that built
// it and is rejected by a proxy on the next one, so the server truncates with a trailing
// "+N more" and keeps the complete, labelled list inside the zip's project.json). The client
// used to read the count alone and say "2 referenced file(s) couldn't be found on disk", which
// is the whole of M24: a number, and no way to tell WHICH shot lost a file short of unzipping
// the bundle and reading project.json by hand.
//
// The header carries ids, not places, and it has to stay small for the reason above. So the
// act/shot labels are re-derived HERE, from the project the client just posted -- it holds the
// whole thing in memory, so nothing needs to ride in the header to name a shot. That makes
// this walk a second implementation of the server's `_loom_collect_media_ids`, and it must
// stay faithful to it (same four sources, same "A·01 Title (openFrame)" shape): the same file
// gets named in two places the owner will compare -- this report and the zip's own
// missing_media manifest -- and one file with two different names is its own bug report.

export const mediaRefIndex = (project) => {
  const ids = {};
  const note = (mid, where) => { const k = String(mid); (ids[k] = ids[k] || []).push(where); };
  ((project || {}).acts || []).forEach((act, ai) => {
    (act.cards || []).forEach((c, ci) => {
      const title = (c.title || "").trim();
      const code = `${actLetter(ai)}·${String(ci + 1).padStart(2, "0")}${title ? ` ${title}` : ""}`;
      if (c.resultMid) note(c.resultMid, `${code} (shot result)`);
      ["openFrame", "closeFrame"].forEach((slot) => {
        const f = c[slot] || {};
        if (f.mediaId) note(f.mediaId, `${code} (${slot})`);
      });
    });
  });
  ((project || {}).assets || []).forEach((a) => {
    if (a.mediaId) note(a.mediaId, `cast/asset ${a.name || a.tag || a.id || "?"}`);
  });
  return ids;
};

// {total, rows:[{mid, where:[label,...]}], hidden} for the export-bundle response headers.
// `hidden` is derived from the COUNT header rather than from the "+N more" marker, because the
// count is the one value the server calls authoritative and the list is best-effort. That is
// also what covers the list header being absent altogether -- an older gallery, or a project
// whose every missing id was dropped by the server's ASCII sanitiser -- where rows comes back
// empty, hidden equals total, and the dialog degrades to the count-plus-a-pointer-to-the-zip
// rather than to a wrong or empty claim. A row whose id the walk above cannot place keeps an
// empty `where`; it is shown as a bare id, never guessed at.
export const bundleMissingReport = (project, countHeader, listHeader) => {
  const total = Math.max(0, parseInt(countHeader || "0", 10) || 0);
  const index = mediaRefIndex(project);
  const rows = String(listHeader || "").split(",").map((s) => s.trim())
    .filter((s) => s && !/^\+\d+ more$/.test(s))
    .map((mid) => ({ mid, where: index[mid] || [] }));
  return { total, rows, hidden: Math.max(0, total - rows.length) };
};
