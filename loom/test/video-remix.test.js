import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  videoRemixFromRow, resolveEngine, NUMERIC_TO_NAME,
} from "../../gallery/src/gen/videoRemixCore.js";
import { applyPrefill, buildPayload, snapDuration } from "../../gallery/src/gen/videoDrawerCore.js";

/* "↺ Remix for videos" (SCOPE_2026-08-17 §2). videoRemixCore is the PURE (row, taskParams) ->
   prefill+notes mapping (§2.2 matrix, §2.4 disclosures); it and applyPrefill's new `camera` key
   run here directly. The host wiring the suite has no React harness for -- the reel's is_video
   guard, History routing video to the Video tab, the dispatcher, prefillVideoFromRun's epoch/busy
   discipline, the VideoDrawer ↺-from chip -- is pinned in the source, short and literal. */

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");

const REF = (id) => ({ media_id: id, thumb: "/thumbs/" + id + ".jpg" });

// A blank catalog row (only the columns videoRemixCore reads matter).
function row(init) {
  return Object.assign({
    video_model: "", model_id: "", video_mode: "", video_duration: "",
    source_media_id: "", negative_prompt: "", prompt_full: "", prompt_preview: "",
  }, init);
}
// A /api/video-task-params body.
function tp(init) {
  return Object.assign({
    kind: "i2v", video_model: "v4.0.1", duration: 5, quality: "professional", camera: "unset",
    audio: false, audio_language: "english", prompt_helper: false, negative: "", prompt: "",
    is_private: false, start: null, end: null, image_refs: [], video_refs: [], audio_refs: [],
  }, init);
}

describe("resolveEngine: name passes, numeric maps, unknown passes through", () => {
  test("a roster name is returned unchanged", () => {
    assert.equal(resolveEngine("v4.0.1"), "v4.0.1");
    assert.equal(resolveEngine("v2.7"), "v2.7");
  });
  test("a numeric modelId maps to the engine name (--sync-videos writes the number)", () => {
    assert.equal(resolveEngine("2003969750675682808"), "v4.0.1");
    assert.equal(resolveEngine("1961182207978260675"), "v3.2");
    assert.equal(NUMERIC_TO_NAME["1919508300549460046"], "v3.0");
  });
  test("blank -> '', and an unknown id passes through for the caller to disclose", () => {
    assert.equal(resolveEngine(""), "");
    assert.equal(resolveEngine(null), "");
    assert.equal(resolveEngine("v9.9-delisted"), "v9.9-delisted");
  });
});

describe("videoRemixFromRow: unrecoverable refs CLEAR the bank (no wrong-shot spend)", () => {
  // The money bug: Remix A (refs in library) fills the drawer; then Remix B, whose refs were
  // uploads (in_lib:false), must NOT inherit A's tiles into B's PAID payload. Every branch has
  // to emit its ref keys even when empty, so applyPrefill clears the matching bank.
  test("r2v with all-upload refs emits empty keys AND clears a drawer holding A's refs", () => {
    const { prefill, notes } = videoRemixFromRow(row({}), tp({
      kind: "r2v",
      image_refs: [{ media_id: "u1", in_lib: false }, { media_id: "u2", in_lib: false }],
      video_refs: [{ media_id: "uv", in_lib: false }],
      audio_refs: [{ media_id: "ua", in_lib: false }],
    }));
    assert.deepEqual(prefill.images, []);        // present + empty, not omitted
    assert.deepEqual(prefill.video_refs, []);
    assert.equal(prefill.audio_ref, null);
    assert.ok(notes.some((n) => /pick them again|pick it again/.test(n)));
    // end to end: a drawer still holding shot A's r2v picks must come out EMPTY after B's prefill
    const s = { mode: "r2v", slots: [null], imgSlots: [REF("A1"), REF("A2")], vidSlots: [REF("AV")],
                audSlot: { media_id: "AA", filename: "a" }, model: "v4.0.1", duration: 5,
                camera: "unset", quality: "professional", channel: "normal", audioGen: false,
                audioLanguage: "english", videoHelper: false, negative: "", modeNote: "" };
    applyPrefill(s, prefill);
    const payload = buildPayload(s, prefill.prompt || "");
    assert.deepEqual(payload.images, []);        // A's images gone
    assert.deepEqual(payload.video_refs, []);    // A's video ref gone
    assert.deepEqual(payload.audio_refs, []);    // A's audio ref gone
  });
  test("i2v with an upload start frame clears the start slot (empty list, never [null])", () => {
    const { prefill } = videoRemixFromRow(row({}), tp({
      kind: "i2v", start: { media_id: "u1", in_lib: false },
    }));
    assert.deepEqual(prefill.images, []);
    const s = { mode: "i2v", slots: [REF("A1")], imgSlots: [null], vidSlots: [], audSlot: null,
                model: "v4.0.1", duration: 5, camera: "unset", quality: "professional",
                channel: "normal", audioGen: false, audioLanguage: "english", videoHelper: false,
                negative: "", modeNote: "" };
    applyPrefill(s, prefill);
    assert.deepEqual(buildPayload(s, "").images, []);   // A's start frame gone
  });
});


describe("videoRemixFromRow: the full-task shapes (§2.2 matrix)", () => {
  test("i2v: every recipe field maps, the in-lib start frame restores, no notes", () => {
    const { prefill, notes } = videoRemixFromRow(row({ prompt_full: "catalog fallback" }), tp({
      kind: "i2v", video_model: "v4.0.1", duration: 5, quality: "professional", camera: "zoom",
      audio: true, audio_language: "japanese", prompt_helper: true, negative: "blurry",
      prompt: "a slow cinematic pan", is_private: true, start: { media_id: "f1", in_lib: true },
    }));
    assert.equal(prefill.mode, "i2v");
    assert.equal(prefill.video_model, "v4.0.1");
    assert.equal(prefill.duration, 5);
    assert.equal(prefill.quality, "professional");
    assert.equal(prefill.camera, "zoom");
    assert.equal(prefill.audio, true);
    assert.equal(prefill.audio_language, "japanese");
    assert.equal(prefill.prompt_helper, true);
    assert.equal(prefill.negative, "blurry");
    assert.equal(prefill.is_private, true);
    assert.equal(prefill.prompt, "a slow cinematic pan");   // task prompt wins over the row's
    assert.deepEqual(prefill.images, [REF("f1")]);
    assert.deepEqual(notes, []);
  });

  test("flf: positional [start, end]; a missing end is a null slot AND a disclosure", () => {
    const { prefill, notes } = videoRemixFromRow(row({}), tp({
      kind: "flf", start: { media_id: "s1", in_lib: true }, end: { media_id: "e1", in_lib: false },
    }));
    assert.equal(prefill.mode, "flf");
    assert.deepEqual(prefill.images, [REF("s1"), null]);
    assert.ok(notes.includes("end frame isn't in your library"));
  });

  test("r2v: in-lib refs restore, upload refs disclose; r2v carries no negative", () => {
    const { prefill, notes } = videoRemixFromRow(row({}), tp({
      kind: "r2v", camera: "", negative: "", prompt: "the druid from @image1 dances",
      image_refs: [{ media_id: "r1", in_lib: true }, { media_id: "r2", in_lib: false }],
    }));
    assert.equal(prefill.mode, "r2v");
    assert.deepEqual(prefill.images, [REF("r1")]);
    assert.ok(notes.includes("reference images were uploads — pick them again"));
    assert.ok(!("negative" in prefill) || prefill.negative === "");
  });

  test("blank engine on the task falls back to the row's engine", () => {
    const { prefill } = videoRemixFromRow(row({ video_model: "v3.2" }), tp({ video_model: "" }));
    assert.equal(prefill.video_model, "v3.2");
  });

  test("a numeric engine (row model_id) resolves to a name", () => {
    const { prefill } = videoRemixFromRow(
      row({ model_id: "2003968021137101826" }), tp({ video_model: "" }));
    assert.equal(prefill.video_model, "v4.0");
  });

  test("an engine no longer in the roster is disclosed, not swapped", () => {
    const { prefill, notes } = videoRemixFromRow(row({}), tp({ video_model: "v9.9-gone" }));
    assert.equal(prefill.video_model, "v9.9-gone");
    assert.ok(notes.includes("engine no longer in the roster"));
  });

  test("duration snaps to the roster grid and a too-long shot is flagged for the clamp", () => {
    const { prefill, notes } = videoRemixFromRow(row({}), tp({ video_model: "v3.2", duration: 15 }));
    assert.equal(prefill.duration, snapDuration(15));       // 15 -- videoRemixCore only snaps
    assert.ok(notes.includes("duration lowered to the engine's max"));  // v3.2 caps at 10
    const clean = videoRemixFromRow(row({}), tp({ video_model: "v4.0.1", duration: 15 }));
    assert.ok(!clean.notes.includes("duration lowered to the engine's max"));  // v4.0.1 allows 15
  });
});

describe("videoRemixFromRow: catalog-only fallback (no readable task)", () => {
  test("null taskParams recovers engine + duration + prompt from the row, disclosed", () => {
    const { prefill, notes } = videoRemixFromRow(row({
      video_model: "v3.0.2", video_duration: "10", prompt_full: "a druid dances",
      negative_prompt: "blurry", source_media_id: "src9",
    }), null);
    assert.equal(prefill.video_model, "v3.0.2");
    assert.equal(prefill.mode, "i2v");                     // shot mode is not a catalog column
    assert.equal(prefill.duration, 10);
    assert.equal(prefill.prompt, "a druid dances");
    assert.equal(prefill.negative, "blurry");
    assert.deepEqual(prefill.images, [REF("src9")]);
    assert.ok(notes.includes("no task record — recipe from the catalog only"));
    assert.ok(notes.includes("camera / audio / channel unknown"));
  });

  test("an {error} body is treated as no task too", () => {
    const { notes } = videoRemixFromRow(row({ prompt_full: "x" }), { error: "couldn't read" });
    assert.ok(notes.includes("no task record — recipe from the catalog only"));
  });

  test("a numeric row engine still resolves in the catalog-only path", () => {
    const { prefill } = videoRemixFromRow(row({ model_id: "1961182207978260675" }), null);
    assert.equal(prefill.video_model, "v3.2");
  });
});

describe("the prefill drives applyPrefill end-to-end (spend-safe payload)", () => {
  function drawer() {
    return {
      mode: "i2v", slots: [null], imgSlots: [null], vidSlots: [], audSlot: null,
      model: "v4.0.1", duration: 5, camera: "unset", quality: "professional",
      channel: "normal", audioGen: false, audioLanguage: "english", videoHelper: false,
      negative: "", modeNote: "",
    };
  }
  test("an i2v remix lands the recipe in the payload the drawer would submit", () => {
    const { prefill } = videoRemixFromRow(row({}), tp({
      kind: "i2v", video_model: "v3.2", duration: 10, quality: "basic", camera: "pan",
      audio: true, prompt: "pan across", start: { media_id: "f1", in_lib: true },
    }));
    const s = drawer();
    const { setPrompt } = applyPrefill(s, prefill);
    const p = buildPayload(s, setPrompt || "");
    assert.equal(p.mode, "I2V");
    assert.equal(p.video_model, "v3.2");
    assert.equal(p.duration, 10);
    assert.equal(p.camera_movement, "pan");
    assert.deepEqual(p.images, ["f1"]);
    assert.equal(p.prompt, "pan across");
  });
  test("a 15s recipe on a 10-cap engine is CLAMPED by applyPrefill's gating (the note warned)", () => {
    const { prefill, notes } = videoRemixFromRow(row({}), tp({ video_model: "v3.2", duration: 15 }));
    assert.ok(notes.includes("duration lowered to the engine's max"));
    const s = drawer();
    applyPrefill(s, prefill);
    assert.equal(s.duration, 10, "applyModelGating clamps 15 -> the v3.2 max, exactly as disclosed");
  });
});

describe("applyPrefill accepts `camera`, and gating still runs LAST", () => {
  function drawer() {
    return {
      mode: "i2v", slots: [null], imgSlots: [null], vidSlots: [], audSlot: null,
      model: "v4.0.1", duration: 5, camera: "unset", quality: "professional",
      channel: "normal", audioGen: false, audioLanguage: "english", videoHelper: false,
      negative: "", modeNote: "",
    };
  }
  test("camera is written from the prefill object", () => {
    const s = drawer();
    applyPrefill(s, { camera: "roll" });
    assert.equal(s.camera, "roll");
  });
  test("camera survives a gating-driven mode switch + duration clamp (gating is last, camera untouched)", () => {
    const s = drawer();
    // v3.0.1 supports i2v only and caps at 10: prefilling r2v @ 15s with a camera must land
    // mode i2v, duration 10 (gating LAST), and keep the camera the prefill set.
    applyPrefill(s, { mode: "r2v", video_model: "v3.0.1", duration: 15, camera: "zoom" });
    assert.equal(s.model, "v3.0.1");
    assert.equal(s.mode, "i2v", "gating switched the unsupported r2v to i2v -- it ran after mode/refs");
    assert.equal(s.duration, 10, "gating clamped 15 -> the engine max");
    assert.equal(s.camera, "zoom", "camera was set before gating and gating never touches it");
  });
  test("source guard: `s.camera = o.camera` precedes applyModelGating(s), which stays the last mutation", () => {
    const core = src("gallery/src/gen/videoDrawerCore.js");
    const ap = core.slice(core.indexOf("export function applyPrefill"),
                          core.indexOf("export function buildPayload"));
    const cam = ap.indexOf("s.camera = o.camera;");
    const gate = ap.indexOf("applyModelGating(s);");
    const ret = ap.indexOf("return { setPrompt");
    assert.ok(cam >= 0 && gate >= 0 && ret >= 0, "camera set, gating call, and return all present");
    assert.ok(cam < gate, "camera must be applied BEFORE applyModelGating");
    assert.ok(gate < ret, "applyModelGating must be the last mutation before the return");
    assert.ok(ap.lastIndexOf("s.model =") < gate, "the engine is set before gating, never after");
  });
});

describe("host wiring source guards (no React harness in this suite)", () => {
  const reel = src("gallery/src/components/RunsReel.jsx");
  const strip = src("gallery/src/components/HistoryStrip.jsx");
  const dock = src("gallery/src/components/GenerateDrawer.jsx");
  const vdraw = src("gallery/src/components/VideoDrawer.jsx");
  const ctx = src("gallery/src/components/GridContextMenu.jsx");
  const details = src("gallery/src/components/DetailsView.jsx");

  test("RunsReel is OPENED UP: a done video is clickable and routes by kind via prefillRun (§2.1 handled by routing, not exclusion)", () => {
    assert.match(reel, /const clickable = done;/);          // video no longer excluded
    assert.doesNotMatch(reel, /!j\.is_video/);              // the old wrong-tab guard is gone
    assert.match(reel, /onPrefill\(j\.job_id, c\.mid\)/);   // onPrefill IS prefillRun, the kind-routing dispatcher
  });

  test("HistoryStrip is OPENED UP: a done video tile is clickable and routes by kind", () => {
    assert.match(strip, /const clickable = done;/);
    assert.doesNotMatch(strip, /done && !c\.video/);
  });

  test("GridContextMenu offers Remix on every row (video included)", () => {
    assert.match(ctx, /\["↺", "Remix", \(\) => actions\.onRemix\(target\.mid\)\]/);
    assert.doesNotMatch(ctx, /target\.isVideo \? \[\] :/);
  });

  test("#28: the mousedown outside-close SKIPS clicks inside the menu (else every action no-ops)", () => {
    // The capture-phase window mousedown listener must not close+unmount the menu on a menu
    // item's OWN mousedown -- that fired before the item's onClick could run, so the WHOLE
    // menu was a silent no-op. It now guards on ref.current.contains(e.target).
    assert.ok(ctx.includes("const onDownOutside = (e) => { if (!(ref.current && ref.current.contains(e.target))) onClose(); };"));
    assert.ok(ctx.includes('window.addEventListener("mousedown", onDownOutside, true);'));
    // the old unconditional close-on-any-mousedown is gone
    assert.ok(!ctx.includes('window.addEventListener("mousedown", close, true);'));
  });

  test("#28 scope-add: a video row gets a 'Rebuild poster' item; App wires it + imports the helper", () => {
    assert.ok(ctx.includes('...(target.isVideo ? [["🖼", "Rebuild poster", () => actions.onRebuildPoster(target.mid)]] : [])'));
    const app = src("gallery/src/App.jsx");
    assert.ok(app.includes("onRebuildPoster: (mid) => rebuildPoster(mid)"));
    assert.ok(app.includes("resolveVideoIds, rebuildPoster,"));
  });

  test("DetailsView: Remix is no longer is_video-guarded, and ▶ Send to Video sends a video's source frame", () => {
    assert.match(details, /onVideo,/);                       // the new prop is destructured
    assert.match(details, />↺ Remix<\/button>/);
    // the Remix button is not wrapped in the old {row.is_video !== "1" && (...)} guard
    assert.doesNotMatch(details, /row\.is_video !== "1" && \(\s*<button className="btn" title="Load this picture/);
    assert.match(details, /▶ Send to Video/);
    assert.match(details, /row\.is_video === "1" \? \(row\.source_media_id \|\| ""\) : row\.media_id/);
  });

  test("the reel, History and the remix request all funnel through the kind-routing dispatcher", () => {
    assert.match(dock, /<HistoryStrip onPrefill=\{prefillRun\}/);
    assert.match(dock, /<RunsReel [^>]*onPrefill=\{prefillRun\}/);
    assert.match(dock, /if \(request\.mid\) prefillRun\("", request\.mid, \{ newSeed: !!request\.newSeed \}\);/);
    // the dispatcher routes by the row's kind
    const i = dock.indexOf("const prefillRun = useCallback(");
    const body = dock.slice(i, dock.indexOf("}, [prefillFromRun, prefillVideoFromRun]);", i));
    assert.match(body, /String\(d\.row\.is_video\) === "1"/);
    assert.match(body, /return prefillVideoFromRun\(/);
    assert.match(body, /return prefillFromRun\(idHint, mediaId, opts\);/);
  });

  // The command palette's "↻ Again — new seed" (R, and its On-this-image row). Owner
  // ruling 2026-08-31: Again SENDS TO REMIX and never submits -- so it must be the SAME
  // road as Remix with one field re-rolled, not a second prefill path that could drift
  // away from the recipe contract above. Both halves are pinned: the option rides the
  // dispatcher, and the ONLY thing it changes is the seed.
  test("↻ Again rides the shipped Remix road, re-rolling the seed and nothing else", () => {
    const app = src("gallery/src/App.jsx");
    assert.match(app, /setGenRequest\(\{ tab: "remix", mid, newSeed: true, nonce: Math\.random\(\) \}\)/);
    // no separate submit anywhere on the Again path -- prefill only, the human presses Generate
    assert.doesNotMatch(app, /requestAgain[\s\S]{0,400}?apiPost\(/);
    const i = dock.indexOf("const prefillFromRun = useCallback(");
    const body = dock.slice(i, dock.indexOf("}, [g]);", i));
    assert.match(body, /seed: opts && opts\.newSeed \? String\(Math\.floor\(Math\.random\(\)/);
    assert.match(body, /: \(row\.seed \|\| ""\)/, "without the option the row's own seed still wins");
    // prompt/negative/frame/steps/cfg are still the recipe's, untouched by the re-roll
    for (const f of [/prompt: row\.prompt_full/, /negative: row\.negative_prompt/,
                     /steps: row\.steps/, /cfg: row\.cfg_scale/]) assert.match(body, f);
  });

  test("prefillVideoFromRun mirrors the image path's epoch/busy discipline and lands on the Video tab", () => {
    const i = dock.indexOf("const prefillVideoFromRun = useCallback(");
    assert.ok(i >= 0, "prefillVideoFromRun exists");
    const body = dock.slice(i, dock.indexOf("}, [g]);", i));
    assert.match(body, /\+\+prefillSeq\.current/, "same epoch guard as prefillFromRun");
    assert.match(body, /prefillSeq\.current === my/);
    assert.match(body, /setPrefillBusy\(true\)/);
    assert.match(body, /setPrefillBusy\(false\)/);
    assert.match(body, /\/api\/video-task-params\//, "reads the video recipe route");
    assert.match(body, /videoRemixFromRow\(row, taskParams\)/, "maps through the pure core");
    assert.match(body, /setTab\("video"\)/);
    assert.match(body, /setExpanded\(true\)/);
    assert.match(body, /setHistoryOpen\(false\)/);
    assert.match(body, /el\.prefill\(prefill\)/);
    assert.match(body, /el\.setReuse\(/, "sets the video ↺-from chip");
    assert.match(body, /Remix is partial/, "the partial-recipe toast (§2.4)");
  });

  test("VideoDrawer: the ↺-from chip exists, is exposed via setReuse, and clears on submit", () => {
    assert.match(vdraw, /const \[reuse, setReuseChip\] = useState\(null\)/);
    assert.match(vdraw, /className=\{"mgdock-reusefrom" \+ \(reuse\.partial \? " warn" : ""\)\}/);
    assert.match(vdraw, /node\.setReuse = setReuse/);
    // cleared the moment a new submission goes out, like the image chip
    const dg = vdraw.slice(vdraw.indexOf("const doGenerate ="), vdraw.indexOf("const poll ="));
    assert.match(dg, /setReuseChip\(null\)/);
    const clear = dg.indexOf("setReuseChip(null)");
    const latch = dg.indexOf("st.current.rendering = true");
    assert.ok(clear >= 0 && latch >= 0 && clear < latch, "the chip clears as the submit commits");
  });
});
