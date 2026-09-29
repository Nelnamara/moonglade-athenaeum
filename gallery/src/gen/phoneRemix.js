import { apiGet as defaultApiGet } from "../api.js";
import { planLoraRestore } from "./genCore.js";
import { escapeLiteral, newRoll } from "./templateCore.js";
import { videoRemixFromRow } from "./videoRemixCore.js";

/* Remix and Send to Video on the phone (Session Q, Q2; Phone Handoff.dc.html). They OPEN the Create
   tab already filled in and they NEVER SEND.

   WHAT THIS FILE MAY REACH, on purpose and pinned by loom/test/phone-handoff-structure.test.js:
   GET reads through apiGet (the picture's own record, its model's version, the task's LoRAs and video
   recipe) and the composer's setters (`g.set`, `g.applyModelRow`, `g.pickVersion`, `g.addLora`) and the
   video drawer's own `prefill` / `setReuse`. It imports no submit road, no price road, no run road, no
   apiPost, and it never calls `generate`, `run.go`, `refreshPrice` or the video drawer's payload. The
   composer's own cost badge quotes the new state afterwards, exactly as it does for any edit a person
   makes -- a quote is a read; a spend needs the person to press Generate.

   IT IS THE DESKTOP'S REMIX, FOR THE PHONE'S COMPOSER. components/GenerateDrawer.jsx's prefillFromRun /
   prefillVideoFromRun / the i2v request do the same for the dock, on the same useGenerate() state and
   the same drawer handle, through the same reads; the field mapping, the two-hop model resolve (a
   catalog row's model_id is the VERSION that rendered, not the base the picker applies), the LoRAs by
   exact version id and the disclosed notes are copied, not reinvented. The desktop dock keeps its own
   copy (its source is pinned by a dozen loom tests); one day both can call this.

   WHICH PROMPT. A picture that came out of a Generate power tools run (Session M) restores that run's
   TEMPLATE -- the details route's `run` block: the template, Random or Matrix, the count, the seed field
   as it was and the run seed -- so pressing Generate reproduces the run (and opens its confirm again when
   it is more than one). Any other picture -- an older run, PixAI's own site, a single plain send -- fills
   the RECORDED prompt with its braces and underscore pairs escaped, so it re-sends byte for byte instead
   of being read as variables. */

/* Retires an older flow when a newer one starts (two quick taps must not interleave). */
let flowSeq = 0;

export const REMIX_NOTE = "Remixed: model, LoRAs, size, steps and prompt are filled in. Nothing is sent.";
export const VIDEO_NOTE = "Sent from Details. Nothing is generated until you press Generate.";

export function isTemplateRun(run) {
  return !!(run && (run.var_mode === "random" || run.var_mode === "matrix"));
}

/* The composer fields a remix sets, and where the prompt came from. Pure. `rand` is injectable so the
   re-roll is testable; `roll` is the composer's current roll, kept when the run names none. */
export function remixPatch(row, run, opts) {
  const o = opts || {};
  const r = row || {};
  const fromRun = isTemplateRun(run);
  const rand = typeof o.rand === "function" ? o.rand : Math.random;
  const seed = fromRun
    ? (o.newSeed ? "" : (run.dock_seed || ""))
    : (o.newSeed ? String(Math.floor(rand() * 2147483647)) : (r.seed || ""));
  const patch = {
    prompt: fromRun ? (run.template || "") : escapeLiteral(r.prompt_full || r.prompt_preview || ""),
    negative: r.negative_prompt || "",
    customW: r.width ? String(r.width) : "",
    customH: r.height ? String(r.height) : "",
    steps: r.steps || "",
    cfg: r.cfg_scale || "",
    seed,
    loras: [],          // a remix REPLACES the composer's LoRAs on every path below
  };
  if (fromRun) {
    patch.varMode = run.var_mode;
    if (run.var_mode === "random" && run.count) patch.count = Number(run.count) || 1;
    patch.roll = o.newSeed ? newRoll(rand)
      : (run.run_seed != null ? Number(run.run_seed) : o.roll);
  }
  return { patch, source: fromRun ? "template" : "recorded" };
}

/* The video drawer's start-frame prefill: this picture as the first frame (an image-to-video shot).
   The same shape components/GenerateDrawer.jsx hands the drawer for its "To Video" request. */
export function startFramePrefill(mediaId) {
  const mid = String(mediaId || "");
  return { mode: "i2v", images: [{ media_id: mid, thumb: "/thumbs/" + encodeURIComponent(mid) + ".jpg" }] };
}

/* Send to Video: the picture becomes the start frame of the video drawer. Returns true when the
   drawer took it. Nothing is sent; the drawer prices and the person presses Generate. */
export function sendStartFrame(drawer, mediaId) {
  if (!mediaId || !drawer || typeof drawer.prefill !== "function") return false;
  drawer.prefill(startFramePrefill(mediaId));
  if (typeof drawer.setReuse === "function") drawer.setReuse(null);   // a start frame is not a recipe chip
  return true;
}

/* Remix a STILL into the phone's composer. `g` is useGenerate()'s return. Resolves
   {ok, notes, source} -- ok false when the picture's record could not be read (nothing was touched).
   `deps.apiGet` is injectable for the tests. */
export async function remixImageInto(g, mediaId, opts, deps) {
  if (!mediaId || !g) return { ok: false, notes: [], source: "" };
  const get = (deps && deps.apiGet) || defaultApiGet;
  const my = ++flowSeq;
  const live = () => flowSeq === my;
  const notes = [];
  const d = await get("/api/next/detail/" + encodeURIComponent(mediaId));
  if (!live()) return { ok: false, notes, source: "" };
  if (!d || d.error || !d.row) {
    return { ok: false, notes, source: "", error: (d && d.error) || "" };
  }
  const row = d.row;

  // MODEL first, and awaited: applying a model applies its own preset (negative / steps / cfg) as a
  // side effect, and the run's own values must win over that preset, not be clobbered by it.
  let modelOk = false;
  if (row.model_id) {
    const dv = await get("/api/model-version?version_id=" + encodeURIComponent(row.model_id));
    const baseId = (dv && dv.model_id) || "";
    if (!live()) return { ok: false, notes, source: "" };
    if (baseId) {
      const applied = await g.applyModelRow({ model_id: baseId, title: row.model_name || row.model_id, preview_url: "" });
      if (!live()) return { ok: false, notes, source: "" };
      if (applied) {
        modelOk = true;
        // applyModelRow lands on the base's LATEST version; the catalog's model_id is the version the
        // task rendered with. Re-pick it exactly, checking the RETURNED versions list; a delisted one
        // is a DISCLOSED substitution.
        if ((applied.versions || []).some((v) => v.version_id === row.model_id)) {
          if (applied.version_id !== row.model_id) g.pickVersion(row.model_id);
        } else {
          notes.push("rendered version no longer listed — latest used");
        }
      }
    }
  }
  if (!modelOk) notes.push("model could not be restored — pick it manually");

  const { patch, source } = remixPatch(row, d.run, {
    newSeed: !!(opts && opts.newSeed), roll: g.s && g.s.roll,
  });
  g.set(patch);

  // LoRAs by EXACT version id, never by name (Remix, issue #4): only when their own model was restored,
  // and every miss counted and disclosed -- a substituted LoRA on a paid path is never silent.
  const hadLoras = !!String(row.loras || "").trim();
  if (!row.task_id) {
    if (hadLoras) notes.push("no task record — LoRAs unknown");
  } else if (!modelOk) {
    if (hadLoras) notes.push("LoRAs not loaded without the model");
  } else {
    const dt = await get("/api/task-params/" + encodeURIComponent(row.task_id));
    if (!live()) return { ok: false, notes, source };
    if (dt && dt.error) {
      if (hadLoras) notes.push("LoRAs could not be restored");
    } else {
      const plan = planLoraRestore(dt, hadLoras);
      for (const lr of plan.rows) {
        // autoInsert:false -- a remix REPRODUCES a recipe; appending trigger words the run did not use
        // would rewrite it under the person before they pay for it again (issue #45).
        await g.addLora(lr, { autoInsert: false });
        if (!live()) return { ok: false, notes, source };
      }
      notes.push(...plan.notes);
    }
  }
  const partial = notes.join("; ");
  g.set({ note: REMIX_NOTE + (partial ? " Partial: " + partial + "." : "") });
  return { ok: true, notes, source };
}

/* Remix a VIDEO into the video drawer: its recipe (shot kind, engine, duration, camera, audio...) from
   the catalog row and the task's own record, through the pure videoRemixFromRow. A task that cannot be
   read is not fatal -- the row alone fills what it can and says so. Resolves {ok, notes}. */
export async function remixVideoInto(drawer, mediaId, deps) {
  if (!mediaId || !drawer || typeof drawer.prefill !== "function") return { ok: false, notes: [] };
  const get = (deps && deps.apiGet) || defaultApiGet;
  const my = ++flowSeq;
  const live = () => flowSeq === my;
  const d = await get("/api/next/detail/" + encodeURIComponent(mediaId));
  if (!live()) return { ok: false, notes: [] };
  if (!d || d.error || !d.row) return { ok: false, notes: [], error: (d && d.error) || "" };
  const row = d.row;
  let taskParams = null;
  if (row.task_id) {
    const dt = await get("/api/video-task-params/" + encodeURIComponent(row.task_id));
    if (!live()) return { ok: false, notes: [] };
    if (dt && !dt.error) taskParams = dt;
  }
  const { prefill, notes } = videoRemixFromRow(row, taskParams);
  drawer.prefill(prefill);
  if (typeof drawer.setReuse === "function") {
    drawer.setReuse({ tag: "#" + String(row.task_id || mediaId).slice(-4), partial: notes.join("; ") });
  }
  return { ok: true, notes };
}
