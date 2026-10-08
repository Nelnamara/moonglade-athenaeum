import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE RENDER LIFECYCLE, AS WIRED (Session P, Stage A1 -- BUILD-w5-p §1.2, §3.3-§3.5 and review
   F1, F3-F8, F12-F17). The pure reducers are unit-tested in loom-takes-core.test.js,
   loom-submit-lifecycle.test.js and loom-board-merge.test.js; this file pins that the app
   actually CALLS them, in the order the design requires, and that no path the owner did not
   click can reach a render. There is no React harness in this runner, so -- like
   loom-batch-generate-concurrency.test.js, submit-road-structure.test.js and the rest -- these
   are source-text checks, on code with its comments stripped (the comments here legitimately
   NAME the things they explain, which would otherwise trip the very guard they document). */

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (p) => readFileSync(path.join(here, "..", p), "utf8").replace(/\r\n/g, "\n");
const SRC = read("master-storyboard.jsx");
const DRAWER = read("../gallery/src/components/VideoDrawer.jsx");

// Comments out: block comments, whole comment lines, and trailing " // ..." after code (the
// leading whitespace keeps "https://" and a regex's "//" intact).
const codeOnly = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/\s\/\/\s.*$/gm, "");
const CODE = codeOnly(SRC);
const DCODE = codeOnly(DRAWER);

/** A hook-level `const NAME = ...` (2-space indent) through its own closing line. */
function hookFn(code, name) {
  const at = code.search(new RegExp("\\n  const " + name + " = "));
  assert.ok(at >= 0, "expected `const " + name + " = ` at hook level -- renamed? re-point this test, never drop it");
  const ends = ["\n  };", "\n  }, ["].map((e) => code.indexOf(e, at + 1)).filter((i) => i > at);
  assert.ok(ends.length, "could not find the end of " + name);
  return code.slice(at, Math.min(...ends));
}

/* ---- a small reachability walker over this file's hook-level functions ----
   Every `  const NAME = ` block is a node, bounded to its own statement (a one-line const ends
   with its line; a function ends at its own 2-space closing line). A node's edges are the other
   block names its CODE mentions, with string contents removed (a "done" phase string is not a
   call). A sink is a render entry point (by name) or a spend route (by literal, looked for in
   the unstripped text). Name collisions across components MERGE blocks, which can only make a
   path easier to find -- the walker errs toward failing. */
const SINK_NAMES = ["generateShot", "batchGenerate", "genSubmit", "genImage", "genImageRun", "genEdit",
  "genRef", "genFix", "runGen", "confirmSpend", "doGenerate", "submitTask", "sendImgRun"];
const SINK_ROUTES = ["/api/loom/generate", "/api/generate", "/api/edit", "/api/fix"];
const noStrings = (s) => s.replace(/`(?:[^`\\]|\\.)*`/g, "``").replace(/"(?:[^"\\\n]|\\.)*"/g, '""')
  .replace(/'(?:[^'\\\n]|\\.)*'/g, "''");
function bound(body) {
  const first = body.split("\n")[0];
  const flat = noStrings(first);
  const depth = [...flat].reduce((d, ch) => d + ("([{".includes(ch) ? 1 : ")]}".includes(ch) ? -1 : 0), 0);
  if (/;\s*$/.test(first) && depth === 0) return first;
  const ends = ["\n  };", "\n  }, [", "\n  );", "\n  }));"].map((e) => body.indexOf(e)).filter((i) => i >= 0);
  return ends.length ? body.slice(0, Math.min(...ends)) : body;
}
function blocksOf(code) {
  const parts = code.split(/^  const (\w+) = /m);
  const out = new Map();
  for (let i = 1; i < parts.length; i += 2) out.set(parts[i], (out.get(parts[i]) || "") + "\n" + bound(parts[i + 1]));
  return out;
}
function sinkIn(body) {
  const code = noStrings(body);
  for (const s of SINK_NAMES) if (new RegExp("\\b" + s + "\\b").test(code)) return s;
  for (const r of SINK_ROUTES) if (body.includes('"' + r + '"') || body.includes("'" + r + "'") || body.includes("`" + r)) return r;
  return null;
}
function reach(blocks, root) {
  assert.ok(blocks.has(root), "root missing -- renamed? " + root);
  const seen = new Map([[root, [root]]]);
  const queue = [root];
  while (queue.length) {
    const name = queue.shift();
    const body = blocks.get(name) || "";
    const hit = sinkIn(body);
    if (hit) return seen.get(name).concat([hit]).join(" -> ");
    for (const m of noStrings(body).matchAll(/\b[A-Za-z_$][\w$]*\b/g)) {
      const id = m[0];
      if (id !== name && blocks.has(id) && !seen.has(id)) { seen.set(id, seen.get(name).concat([id])); queue.push(id); }
    }
  }
  return null;
}
const BLOCKS = blocksOf(CODE);

describe("the walker is real (negative controls)", () => {
  test("on the real file it finds the paths that DO spend", () => {
    assert.equal(reach(BLOCKS, "genSubmit"), "genSubmit -> generateShot", "the phone's Generate reaches the render (as it must)");
    assert.match(reach(BLOCKS, "batchGenerate"), /^batchGenerate -> generateShot$/);
  });
  test("a root that reaches generateShot through a helper is caught", () => {
    const fake = blocksOf("\n  const onOpen = () => { helper(); };\n  const helper = () => { generateShot(entry); };\n");
    assert.equal(reach(fake, "onOpen"), "onOpen -> helper -> generateShot");
    const fake2 = blocksOf("\n  const onOpen = () => { poke(); };\n  const poke = () => fetch(\"/api/loom/generate\", {});\n");
    assert.match(reach(fake2, "onOpen"), /\/api\/loom\/generate$/);
  });
});

describe("generateShot follows BUILD-w5-p §3.3 in order", () => {
  const fn = hookFn(CODE, "generateShot");
  test("step 1: the synchronous latch (inflightRef + the card read from the store's ref) comes before the first await", () => {
    const latchCheck = fn.indexOf("inflightRef.current.has(cardId) || goBlocked(pre.c, pausedNow)");
    const latchSet = fn.indexOf("inflightRef.current.add(cardId);");
    const firstAwait = fn.search(/\bawait\b/);
    assert.ok(fn.indexOf("const pre = cardOn(cardId);") >= 0, "the latch must read the CURRENT card (cardOn -> projectRef), not entry.c");
    assert.ok(latchCheck >= 0 && latchSet > latchCheck, "check, then set");
    assert.ok(firstAwait > latchSet, "nothing may be awaited before the latch is set");
    assert.doesNotMatch(fn.slice(0, latchSet), /entry\.c\.(?!id\b)/, "the latch must not read the entry's closure");
  });
  test("step 2: ONE payload, built from the board re-read after the latch, is priced, sent and snapshotted", () => {
    const build = fn.indexOf("const p = buildShotPayload(fresh, proj, imgSrc);");
    assert.ok(build > fn.indexOf("inflightRef.current.add(cardId);"), "the payload is built after the latch, from the fresh entry");
    assert.match(fn, /const fresh = cardOn\(cardId\);/);
    assert.match(fn, /const ask = await askShotSpend\(p\);/, "the price is asked of the payload that is sent");
    assert.match(hookFn(CODE, "askShotSpend"), /const pr = await priceBody\(p\);/, "the ask prices the payload it is handed");
    assert.match(fn, /const settings = snapshotSettings\(c, proj, p\.prompt, p\.quality\);/);
    assert.doesNotMatch(fn, /shotPayload\(entry\)|priceShot\(entry\)/, "no second payload from the stale entry");
    const refuseLocal = fn.indexOf("unsendableRefs(p).length");
    assert.ok(refuseLocal > build && refuseLocal < fn.indexOf("await askShotSpend(p)"),
      "an imported (local_) picture, video or audio is refused BEFORE pricing (open call 4, spend review S6)");
    const fpCheck = fn.indexOf("priceFingerprint(p) !== opts.confirmedFp");
    assert.ok(fpCheck > build && fpCheck < fn.indexOf('fetch("/api/loom/generate"'),
      "a batch shot whose payload changed since the confirm is not sent (F12)");
  });
  test("step 3: beginRender, then the lock is SAVED (through the queue) before the POST; a failed save sends nothing", () => {
    const lock = fn.indexOf("beginRender(cc,");
    const flush = fn.indexOf("await saveBoardNow(boardId)");
    const post = fn.indexOf('fetch("/api/loom/generate"');
    assert.ok(lock > 0 && flush > lock && post > flush, "beginRender -> saved lock -> POST");
    const failBlock = fn.slice(flush, post);
    assert.match(failBlock, /if \(!saved\.ok\) \{/);
    assert.match(failBlock, /cancelRender\(cc, submitId, remoteCard \|\| before\)/, "a conflict takes THIS render's lock off the merged board");
    assert.match(failBlock, /return \{ ok: false, reason: "conflict" \};/);
    assert.match(failBlock, /cancelRender\(cc, submitId, before\)/, "a failed save rolls the lock back (F5)");
    assert.match(failBlock, /return \{ ok: false, reason: "save-failed" \};/);
  });
  test("step 4: ONE POST carrying loom_target, submit_id and expect_free (only when the confirmed quote was free)", () => {
    assert.equal((fn.match(/fetch\("\/api\/loom\/generate"/g) || []).length, 1);
    // Spend review S3: the body IS the priced payload `p` (every key but hasInput, pinned in
    // loom-core.test.js), never a re-listed subset that can drop a field such as is_private.
    assert.match(fn, /fetch\("\/api\/loom\/generate", \{ method: "POST", headers: \{ "Content-Type": "application\/json" \},\s*body: JSON\.stringify\(shotSendBody\(p, \{ boardId, cardId, submitId, expectFree \}\)\) \}\);/);
    assert.doesNotMatch(fn, /body: JSON\.stringify\(\{ mode: p\.mode/, "no hand-listed body");
    assert.match(hookFn(CODE, "askShotSpend"), /const expectFree = !!\(pr && pr\.free\);/,
      "a single render is sent expect_free exactly when its quote was free (F13)");
    assert.match(fn, /if \(!ask\.go\) return \{ ok: false, reason: "cancelled" \};\s*quote = ask\.quote;\s*expectFree = ask\.expectFree;/);
    assert.doesNotMatch(fn, /retry|setTimeout\([^)]*fetch/, "never re-posted");
  });
  test("step 5: after the answer is classified, an unclear send reads submit-status -- /api/loom/generate is never asked again", () => {
    const cls = fn.indexOf("const cls = classifySubmit({ threw, status, body });");
    assert.ok(cls > fn.indexOf('fetch("/api/loom/generate"'));
    const after = fn.slice(cls);
    assert.doesNotMatch(after, /\/api\/loom\/generate|generateShot\(|batchGenerate\(/);
    assert.match(after, /markUnclear\(cc, submitId, CHECKING_MSG, nowIso\(\)\)/);
    assert.match(after, /await checkSubmit\(cardId, submitId, boardId\)/);
    const check = hookFn(CODE, "checkSubmit");
    assert.match(check, /fetch\("\/api\/loom\/submit-status\?submit_id=" \+ encodeURIComponent\(submitId\)\)/);
    assert.equal(reach(BLOCKS, "checkSubmit"), null, "the check can never reach a render");
  });
  test("the latch lets go when the POST answers (the card's markers hold the lock after that)", () => {
    const post = fn.indexOf('fetch("/api/loom/generate"');
    const drop = fn.indexOf("inflightRef.current.delete(cardId);", post);
    assert.ok(drop > post && drop < fn.indexOf("const cls = classifySubmit("));
  });
  test("the only fetch of /api/loom/generate in the Loom is generateShot's", () => {
    assert.equal((CODE.match(/["'`]\/api\/loom\/generate["'`]/g) || []).length, 1);
    const at = CODE.indexOf('fetch("/api/loom/generate"');
    const g = CODE.indexOf("\n  const generateShot = async (entry, opts = {}) => {");
    assert.ok(g >= 0 && at > g && at < g + fn.length);
  });
});

describe("the unclear-send way-out, the resume and every landing cannot reach a render", () => {
  const ROOTS = ["checkSubmit", "recheckSubmit", "releaseSubmit", "adoptFromJournal", "resumeInterrupted",
    "pollShot", "useExistingVideo", "attachDraftVideo", "beginDrawerRender", "onVideoSubmit", "onVideoResult",
    "onVideoError", "onVideoSlow", "onVideoPaused", "loadBoards", "openProject", "newProject",
    "duplicateProject", "_adoptBackup", "persistBoard", "saveBoardNow", "splitShot"];
  for (const root of ROOTS) {
    test(root + " reaches no render entry point and no spend route", () => {
      assert.equal(reach(BLOCKS, root), null);
    });
  }
  test("the release is a POST to /api/loom/submit-abandon with the CSRF token, never a re-send", () => {
    const rel = hookFn(CODE, "releaseSubmit");
    assert.match(rel, /const csrf = await LOOM_RUN_DEPS\.csrf\(\);/);
    assert.match(rel, /fetch\("\/api\/loom\/submit-abandon", \{ method: "POST"[\s\S]*?body: JSON\.stringify\(\{ csrf, submit_id: submitId \}\)/);
    assert.match(rel, /abandonSubmit\(cc, submitId, nowIso\(\)\)/);
    assert.match(rel, /if \(status === 409 && d && d\.task_id\) \{ adoptFromJournal\(/, "a render the journal knows was SENT is adopted, not released");
  });
  test("resumeInterrupted is named, polls the task case and CHECKS the unclear case; the effect only calls it", () => {
    const res = hookFn(CODE, "resumeInterrupted");
    assert.match(res, /cardsToResume\(proj, resumedRef\.current\)\s*\.forEach\(\(c\) => pollShot\(c\.id, c\.taskId, c\.startedAt, boardId\)\);/);
    assert.match(res, /submitsToCheck\(proj, Object\.create\(null\)\)\s*\.filter\(\(c\) => !inflightRef\.current\.has\(c\.id\)\)\s*\.forEach\(\(c\) => checkSubmit\(c\.id, c\.submitId, boardId\)\);/,
      "a card whose POST this tab is still waiting on is not checked (spend review B1)");
    assert.match(CODE, /useEffect\(\(\) => \{ resumeInterrupted\(\); \}, \[activeId, mobileUI\]\);/);
  });
  test("a send this tab is still waiting on is SLOW, never unclear: no mark, no journal read, no release (spend review B1)", () => {
    // A slow PixAI, then a board switch or the Mobile toggle: the resume used to mark the card
    // unclear from submit-status "sending" and offer the release, which freed the shot for a
    // second paid render while the first POST was still inside core.submit.
    const check = hookFn(CODE, "checkSubmit");
    const guard = check.indexOf("if (inflightRef.current.has(cardId)) return { pending: true };");
    assert.ok(guard >= 0, "checkSubmit must refuse a card whose POST is pending in inflightRef");
    assert.ok(guard < check.indexOf("fetch(") && guard < check.indexOf("markUnclear("), "before the read and before any mark");
    const rel = hookFn(CODE, "releaseSubmit");
    const relGuard = rel.indexOf("if (inflightRef.current.has(cardId)) { holdCard(cardId, STILL_SENDING_MSG, \"checking\"); return; }");
    assert.ok(relGuard >= 0 && relGuard < rel.indexOf('fetch("/api/loom/submit-abandon"'), "the release refuses before it asks the server");
    assert.match(rel, /if \(status === 409 && d && d\.sending\) \{ holdCard\(cardId, STILL_SENDING_MSG, "unclear"\); return; \}/,
      "the server's own still-sending refusal keeps the lock and says so");
    assert.ok(rel.indexOf("d.sending") < rel.indexOf("Couldn't release this shot"));
  });
  test("pollShot registers its own task, so a later resume never starts a second poll of it (F4)", () => {
    const poll = hookFn(CODE, "pollShot");
    assert.match(poll, /if \(pollingRef\.current\.has\(key\)\) return;/);
    assert.match(poll, /resumedRef\.current\[key\] = true;/);
    const reg = poll.indexOf("resumedRef.current[key] = true;");
    assert.ok(reg >= 0 && reg < poll.indexOf("setTimeout(tick"), "registered before the first tick");
  });
});

describe("landings go through landTake / attachTake only (F1, F4, F14)", () => {
  test("no withResult( call and no genTargetRef remain in the Loom", () => {
    assert.doesNotMatch(CODE, /\bwithResult\(/);
    assert.doesNotMatch(CODE, /\bgenTargetRef\b/);
    assert.doesNotMatch(CODE, /\bsetCardResult\b/);
  });
  test("pollShot lands through landTake, only on the board the render was sent from", () => {
    const poll = hookFn(CODE, "pollShot");
    assert.match(poll, /const onBoard = \(\) => !boardId \|\| activeIdRef\.current === boardId;/);
    const done = poll.slice(poll.indexOf('cls.phase === "done"'), poll.indexOf('cls.phase === "failed"'));
    assert.match(done, /if \(!onBoard\(\)\) \{ leave\(\); return; \}/, "another board open: nothing is patched");
    assert.match(done, /patchCardNow\(cardId, \(cc\) => landTake\(cc, rep\)\.card\);/);
    assert.match(done, /board: boardId/);
    const failed = poll.slice(poll.indexOf('cls.phase === "failed"'), poll.indexOf("elapsed > POLL_CEILING_MS"));
    assert.match(failed, /failRender\(cc, \{ taskId: tid, state: "failed"/, "a failed retake keeps a ★ shot done (F14)");
  });
  test("the drawer's result lands by task id through landTake; the draft attach and Use an existing video through attachTake", () => {
    assert.match(hookFn(CODE, "onVideoResult"), /const card = cardForTask\(projectRef\.current, tid\);[\s\S]*landTake\(cc, rep\)\.card/);
    assert.match(hookFn(CODE, "attachDraftVideo"), /imported: false, settings: settings \|\| null/);
    assert.match(hookFn(CODE, "attachDraftVideo"), /attachTake\(cc, rep\)\.card/);
    const use = hookFn(CODE, "useExistingVideo");
    assert.match(use, /imported: true/);
    assert.match(use, /attachTake\(cc, rep\)\.card/);
    assert.match(use, /if \(out\.outcome === "unclear"\)/, "an unclear send refuses the attach");
  });
  test("nothing in the Loom writes takes / selectedTake / takeSeq except the pure reducers", () => {
    const WRITE = /(?<![\w.$])(takes|selectedTake|takeSeq)\s*:(?!:)|\.(takes|selectedTake|takeSeq)\s*=(?!=)|\[\s*["'](takes|selectedTake|takeSeq)["']\s*\]\s*=(?!=)/;
    for (const [name, code] of [["master-storyboard.jsx", CODE], ["VideoDrawer.jsx", DCODE],
      ["src/loom-core.js", codeOnly(read("src/loom-core.js"))], ["src/loom-store-core.js", codeOnly(read("src/loom-store-core.js"))],
      ["src/loom-run.js", codeOnly(read("src/loom-run.js"))], ["src/loom-url.js", codeOnly(read("src/loom-url.js"))]]) {
      assert.doesNotMatch(code, WRITE, name + " writes a take field itself");
    }
    // loom-mutations.js only ever CLEARS them, on a duplicate (a fresh, unrendered shot).
    const mut = codeOnly(read("src/loom-mutations.js"));
    const hits = mut.split("\n").filter((l) => WRITE.test(l));
    assert.deepEqual(hits.map((l) => l.trim()),
      ["takes: undefined, selectedTake: undefined, takeSeq: undefined, deletedTakes: undefined,"]);
  });
});

describe("the drawer's events are resolved by their ids, never by the selected shot (F7)", () => {
  const EVENTS = { "mg-submit": "onVideoSubmit", "mg-result": "onVideoResult", "mg-error": "onVideoError",
    "mg-slow": "onVideoSlow", "mg-paused": "onVideoPaused" };
  test("each render event's listener only hands its detail on", () => {
    for (const [evt, fn] of Object.entries(EVENTS)) {
      const re = new RegExp('el\\.addEventListener\\("' + evt + '", \\(e\\) => ' + fn + "\\(e\\.detail\\)\\);");
      assert.match(CODE, re, evt + " must call " + fn + "(e.detail) and nothing else");
    }
  });
  test("no render-event handler reads the selected shot (activeRef / genTargetRef / selShot)", () => {
    for (const fn of Object.values(EVENTS)) {
      assert.doesNotMatch(hookFn(CODE, fn), /\b(activeRef|genTargetRef|selShot)\b/, fn);
    }
    assert.match(hookFn(CODE, "onVideoSubmit"), /const card = cardForSubmit\(projectRef\.current, d\.submit_id\);/);
    assert.match(hookFn(CODE, "onVideoError"), /const card = cardForSubmit\(projectRef\.current, d\.submit_id\);/);
    assert.match(hookFn(CODE, "onVideoError"), /checkSubmit\(card\.id, d\.submit_id, activeIdRef\.current\)/, "an unclear drawer send is CHECKED, never re-sent");
  });
  test("the Go gate follows the shot's own markers (paused carve-out kept)", () => {
    assert.match(CODE, /const stillBusy = goBlocked\(active\.c, !!\(gs && gs\.phase === "paused"\)\);/);
  });
  test("beforeSend runs the latch and saves the lock before answering ok", () => {
    const b = hookFn(CODE, "beginDrawerRender");
    const latch = b.indexOf("inflightRef.current.has(cardId) || goBlocked(pre.c, pausedNow)");
    const add = b.indexOf("inflightRef.current.add(cardId);");
    const firstAwait = b.search(/\bawait\b/);
    assert.ok(latch >= 0 && add > latch && firstAwait > add, "the latch is set before anything is awaited");
    const lock = b.indexOf("beginRender(cc,");
    const flush = b.indexOf("const saved = await saveBoardNow(boardId);");
    const ok = b.indexOf("if (saved.ok) return { ok: true, expectFree: ask.expectFree };");
    assert.ok(lock > add && flush > lock && ok > flush, "ok only after the lock is saved");
    assert.match(b, /if \(activeIdRef\.current !== boardId\) return \{ refused:/);
    const refuse = b.indexOf("if (unsendableRefs(payload).length) {");
    assert.ok(refuse >= 0 && refuse < add, "the drawer's Go refuses an imported picture, video or audio before it locks (S6)");
  });
  test("beforeSend ASKS before any credit spend, the same fail-closed ask as generateShot (owner walk 2026-09-30)", () => {
    // The Video tab's Go spent 70,000 credits on the click: beforeSend locked and answered ok
    // with no ask. Now it asks through askShotSpend -- the one ask generateShot uses too -- of
    // the payload the drawer POSTs, after the latch and before the lock; a "no" takes the latch
    // off and sends nothing; the lock records the quote the owner said yes to.
    const b = hookFn(CODE, "beginDrawerRender");
    const add = b.indexOf("inflightRef.current.add(cardId);");
    const ask = b.indexOf("try { ask = await askShotSpend(payload); }");
    const lock = b.indexOf("beginRender(cc,");
    assert.ok(ask > add && lock > ask, "latch -> ask -> lock");
    assert.equal(b.search(/\bawait\b/), ask + "try { ask = ".length, "the ask is the first thing awaited, after the latch");
    assert.match(b, /catch \(e\) \{ inflightRef\.current\.delete\(cardId\); throw e; \}/,
      "an ask that throws still takes the latch off (review 2026-10-01, nit 2)");
    assert.match(b, /if \(!ask\.go\) \{ inflightRef\.current\.delete\(cardId\); return \{ cancelled: true \}; \}/,
      "a no releases the latch and answers cancelled");
    assert.match(b.slice(ask, lock), /if \(activeIdRef\.current !== boardId \|\| !cardOn\(cardId\)\) \{\s*inflightRef\.current\.delete\(cardId\);\s*return \{ refused:/,
      "the board or the shot changed during the ask: nothing is locked or sent");
    assert.match(b, /const quote = ask\.quote;/, "the lock records the quote that was confirmed, not the drawer's badge");
    // The draft (no shot) is asked the same way, and says what it confirmed.
    assert.match(b, /if \(cardId === "__draft__"\) return beginDraftRender\(submitId, payload\);/);
    const d = hookFn(CODE, "beginDraftRender");
    assert.match(d, /const ask = await askShotSpend\(payload\);\s*if \(!ask\.go\) return \{ cancelled: true \};/);
    const dRefuse = d.indexOf("if (unsendableRefs(payload).length) {");
    assert.ok(dRefuse >= 0 && dRefuse < d.indexOf("await askShotSpend("),
      "a draft with an imported reference is refused before it is priced or asked (S6; review 2026-10-01, nit 3)");
    assert.match(d, /return \{ ok: true, expectFree: ask\.expectFree \};/);
    // ONE ask, one wording: generateShot's and the drawer's Go both ride askShotSpend.
    assert.equal((CODE.match(/await askShotSpend\(/g) || []).length, 3, "generateShot, beginDrawerRender, beginDraftRender");
    assert.equal((CODE.match(/Couldn't verify this shot's cost or free-card coverage/g) || []).length, 1);
    assert.equal((CODE.match(/No free card covers this shot/g) || []).length, 1);
    assert.equal(reach(BLOCKS, "askShotSpend"), null, "the ask itself can never reach a render");
  });
});

describe("board storage: nothing writes on open; every board write is the compare-and-swap queue (§1.2, F5, F15)", () => {
  test("the only board writer is the save queue's writeBoard (base_rev); no sSet of a board key anywhere", () => {
    assert.doesNotMatch(CODE, /sSet\(\s*PPRE/);
    assert.equal((CODE.match(/window\.storage\.set\(/g) || []).length, 2, "sSet (pointer, thumbs) and writeBoard");
    assert.match(CODE, /const writeBoard = \(k, json, baseRev\) =>\s*window\.storage\.set\(k, json, false, baseRev !== undefined \? \{ base_rev: baseRev \} : undefined\);/);
    assert.equal((CODE.match(/makeSaveQueue\(/g) || []).length, 1, "ONE queue per page");
  });
  test("the autosave writes only when the board differs from what was last read or written", () => {
    const at = CODE.indexOf("if (!shouldSave(JSON.stringify(project), lastSavedRef.current[PPRE + activeId]))");
    const timer = CODE.indexOf("saveTimer.current = setTimeout(async () => { await saveBoardNow(id); setBusy(false); }, 600);");
    assert.ok(at >= 0 && timer > at);
    assert.match(hookFn(CODE, "showBoard"), /lastSavedRef\.current\[key\] = JSON\.stringify\(p\);/, "what was read is what 'saved' means");
    assert.match(hookFn(CODE, "persistBoard"), /if \(!shouldSave\(json, lastSavedRef\.current\[key\]\)\) return \{ ok: true, skipped: true \};/);
  });
  test("loadBoards: a failed list migrates and seeds nothing; a listed board that won't read is never written over", () => {
    const lb = hookFn(CODE, "loadBoards");
    const listFail = lb.indexOf('if (listed.failed) { setLoadError("list"); return; }');
    const firstWrite = lb.search(/queueRef\.current\.save\(|persistBoard\(|sSet\(/);
    assert.ok(listFail >= 0 && firstWrite > listFail);
    const mig = lb.slice(lb.indexOf("if (!keys.length) {"), lb.indexOf("const wantedBoard"));
    assert.match(mig, /if \(legacy\.failed\) \{ setLoadError\("legacy"\); return; \}/);
    assert.ok(mig.indexOf("legacy.failed") < mig.indexOf("queueRef.current.save("), "never seed over a legacy read that failed");
    const after = lb.slice(lb.indexOf("const wantedBoard"));
    assert.doesNotMatch(after, /queueRef\.current\.save\(|persistBoard\(|seedProject\(/, "past the migration nothing is written or seeded");
    assert.match(after, /const r = await readBoard\(id\);\s*if \(r\.p\) \{ opened = /, "unreadable boards are skipped for the next readable one");
    assert.match(after, /if \(!opened\) \{ setLoadError\("read"\); return; \}/);
    assert.match(CODE, /useEffect\(\(\) => \{ loadBoards\(\); \}, \[\]\);/);
  });
  test("App shows an honest failure state with a Reload, never the eternal loading line", () => {
    assert.match(CODE, /if \(!project && loadError\) \{/);
    assert.match(CODE, /Couldn't read your storyboards/);
    assert.match(CODE, /onClick=\{\(\) => window\.location\.reload\(\)\}/);
  });
  test("copies of a board never carry a render in flight (F4, F17)", () => {
    assert.match(hookFn(CODE, "duplicateProject"), /const p = stripInFlight\(\{ \.\.\.cur, name:/);
    assert.match(hookFn(CODE, "_adoptBackup"), /await createBoard\(stripInFlight\(d\.project\)\);/);
  });
  test("a save conflict merges (takes kept), shows it, and says what moved and what was undone (F6, #59)", () => {
    const m = hookFn(CODE, "mergeAfterConflict");
    assert.match(m, /const out = mergeBoards\(local, remote,\s*\{ resolvedSubmits: Array\.from\(resolvedRef\.current\), base: isBoard\(base\) \? base : null \}\);\s*const merged = out\.project;/);
    assert.match(m, /base = lastSavedRef\.current\[key\] \? JSON\.parse\(lastSavedRef\.current\[key\]\) : null/,
      "the merge is told what this tab last synced (red team 2026-10-01)");
    assert.match(m, /queueRef\.current\.save\(key, JSON\.stringify\(merged\), \{ baseRev: res\.rev \}\)/);
    assert.match(m, /This storyboard changed in another tab/);
    // The text is mergeNotice's (loom-board-merge.test.js pins it: "Your takes were kept; ..." first,
    // then a split undone, a shot or act deleted elsewhere, a shot kept in another act). A dropped
    // card is named as THIS tab knew it, so the codes come from the local board as well as the merged one.
    assert.match(m, /msg: mergeNotice\(out, \{ local: codesOf\(local\), merged: codesOf\(merged\) \}\)/);
    assert.doesNotMatch(m, /Your takes were kept; other edits from this tab were replaced\./, "one home for the copy");
  });
});

describe("batchGenerate sends only what was confirmed (F12, F13, F14, §3.4)", () => {
  const b = hookFn(CODE, "batchGenerate");
  test("todo is the current board's needsRender shots; each is held to its confirmed fingerprint and pool verdict", () => {
    assert.match(b, /const todo = board\.filter\(\(e\) => needsRender\(e\.c\)\);/);
    assert.match(b, /const fps = todo\.map\(\(e\) => priceFingerprint\(shotPayload\(e\)\)\);\s*const prices = await Promise\.all\(todo\.map\(\(e\) => priceShot\(e\)\)\);/);
    assert.match(b, /const covered = prices\.map\(\(pr, i\) => !!\(pr && pr\.free\) && !\(overflowIndexes \|\| \[\]\)\.includes\(i\)\);/,
      "only a shot the pool-aware tally counted COVERED goes out expect_free; an overflow shot was confirmed as paid");
  });
  test("a changed shot is skipped and named; a conflict / busy / unclear stops the rest; a refusal continues", () => {
    assert.match(b, /r\.reason === "changed"\) \{ changed\.push\(e\.code\);/);
    assert.match(b, /changed since you confirmed/);
    assert.match(b, /r\.reason === "conflict" \|\| r\.reason === "busy" \|\| r\.reason === "unclear"/);
    assert.match(b, /break;/);
  });
});

describe("the ✂ splice records its anchor; Split waits for a render in flight (§2.1, F11)", () => {
  test("both splice buttons patch through splicePatch with the source captured at the click", () => {
    // `took` is the handoff's own answer -- where it really cut (owner walk 2026-09-30: a frame
    // taken from E·01's end was recorded "at 0.0 s"), read through the one builder, tookOf(d)
    // (code review 2026-10-02: three hand-copied {at, end} builders).
    const n = (CODE.match(/splicePatch\(c{1,2}, \{ frameMid: d\.frame_media_id, src: src\.c, srcCode: src\.code, took: tookOf\(d\) \}\)/g) || []).length;
    assert.equal(n, 2, "desktop inheritPrev and the phone's dfInheritPrev");
    assert.match(hookFn(CODE, "reanchorShot"),
      /reanchorPatch\(c, \{ frameMid: String\(d\.frame_media_id\), src: src\.c, srcCode: src\.code, expect, took: tookOf\(d\) \}\)/,
      "Re-anchor records where its frame came from too");
    assert.equal((CODE.match(/took: /g) || []).length, 3, "every `took` goes through tookOf -- no hand-built copy");
    assert.doesNotMatch(CODE, /took: \{/, "no hand-built {at, end}");
    assert.match(hookFn(CODE, "reanchorShot"), /trim_out: cutPointOf\(src\.c\)/,
      "the re-anchor asks for the source's cut (null, not 0, when its length is unknown: the last frame)");
    assert.equal((CODE.match(/trim_out: src\.c\.trimOut/g) || []).length, 2, "the frame is cut where the source's ★ take is cut");
  });
  test("splitShot refuses while splitBlocked, with a plain message", () => {
    const s = hookFn(CODE, "splitShot");
    assert.match(s, /if \(splitBlocked\(cur \? cur\.c : entry\.c\)\) \{/);
    assert.match(s, /Can't split this shot yet/);
  });
});

describe("<VideoDrawer> in the Loom: target at the click, beforeSend before the POST (F7, F13)", () => {
  const i = DCODE.indexOf("const doGenerate = async () => {");
  const gen = DCODE.slice(i, DCODE.indexOf("\n  };", i));
  test("the target is captured at the click and a Loom Go without one sends nothing", () => {
    const cap = gen.indexOf("const target = loomCtx ? st.current.loomTarget : null;");
    const refuse = gen.indexOf("if (loomCtx && !(target && target.board_id && target.card_id)) {");
    assert.ok(cap >= 0 && refuse > cap);
    assert.match(gen.slice(refuse, refuse + 200), /return;/);
    assert.ok(cap < gen.search(/\bawait\b/), "captured before anything is awaited");
    const before = gen.indexOf("await host.beforeSend(");
    const capEnd = gen.indexOf("\n", cap);
    assert.equal(gen.indexOf("st.current.loomTarget", capEnd), -1, "the target is never re-read after the click");
    assert.ok(before > refuse);
  });
  test("beforeSend is awaited BEFORE submitTask, and a refusal (or no host) returns before it", () => {
    const before = gen.indexOf("await host.beforeSend(");
    const road = gen.indexOf('await submitTask("/api/loom/generate"');
    assert.ok(before >= 0 && road > before);
    const refusal = gen.slice(before, road);
    assert.match(refusal, /if \(!verdict \|\| verdict\.refused \|\| !verdict\.ok\) \{[\s\S]*?unlock\(\);\s*return;\s*\}/);
    assert.match(gen, /verdict = \(host && host\.beforeSend\) \? await host\.beforeSend\(\{ \.\.\.loomIds, payload: p,[\s\S]*?\}\) : null;/,
      "no host -> no verdict -> nothing sent");
  });
  test("the POST adds loom_target (not for a draft), submit_id and expect_free (settled verdict free); the gallery's request is unchanged", () => {
    assert.match(gen, /const sent = loomIds \? \{ \.\.\.p, submit_id: submitId,\s*\.\.\.\(target\.draft \? \{\} : \{ loom_target: \{ board_id: target\.board_id, card_id: target\.card_id \} \}\),\s*\.\.\.\(expectFree \? \{ expect_free: true \} : \{\}\) \} : p;/);
    assert.match(gen, /let expectFree = !!\(quoted && quoted\.free\);/);
    assert.match(gen, /await submitTask\("\/api\/loom\/generate", sent, /);
  });
  test("in the Loom, what is sent is what the host's ask confirmed; a no sends nothing and leaves no line", () => {
    const before = gen.indexOf("await host.beforeSend(");
    const road = gen.indexOf('await submitTask("/api/loom/generate"');
    const between = gen.slice(before, road);
    assert.match(between, /if \(verdict && verdict\.cancelled\) setResults\(\(rs\) => rs\.filter\(\(l\) => l\.id !== id\)\);/);
    assert.match(between, /if \(typeof verdict\.expectFree === "boolean"\) expectFree = verdict\.expectFree;/,
      "expect_free follows the quote the owner said yes to, not the badge's older verdict");
    assert.ok(gen.indexOf("const sent = ") > gen.indexOf("expectFree = verdict.expectFree"), "decided before the body is built");
  });
  test("every Loom event names its render; a submit with no answer says unclear", () => {
    assert.match(gen, /emit\("mg-submit", tag\(\{ task_id: tid, payload: p \}\)\);/);
    assert.match(gen, /emit\("mg-result", tag\(\{[^\n]*\}, true\)\);/);
    assert.match(gen, /emit\("mg-error", tag\(\{ error: msg \}, true\)\);/);
    assert.match(gen, /emit\("mg-slow", tag\(/);
    assert.match(gen, /emit\("mg-paused", tag\(/);
    assert.match(DCODE, /const unclear = !a \|\| !!a\.threw \|\| !b \|\| typeof b !== "object" \|\| !!b\.unclear;/);
  });
  test("the host hooks only store (they cannot reach doGenerate or submitTask)", () => {
    for (const name of ["setLoomTarget", "setHost", "setBusy", "prefill", "setRefs", "flushPromptEdit"]) {
      const at = DCODE.indexOf("\n  const " + name + " = ");
      assert.ok(at >= 0, name);
      const end = Math.min(...["\n  };", "\n  const "].map((e) => DCODE.indexOf(e, at + 1)).filter((x) => x > at));
      assert.doesNotMatch(DCODE.slice(at, end), /doGenerate|submitTask|beforeSend\(/, name);
    }
  });
});
