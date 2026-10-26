import { test, describe, after } from "node:test";
import assert from "node:assert/strict";
// FIRST: mount.mjs installs the fake DOM before anything loads react-dom (its gotcha 1).
import { mountLoomV2, core, fetchLog, FEvent } from "../test-support/mount.mjs";

/* The mount helper proves itself here on the REAL <LoomV2> (loom/test-support/mount.mjs): a
   mount that runs effects, a drawer that appears when the right panel opens, a prefill spy, a
   dispatch that reaches the host's listeners, a re-render that keeps identity, and a fetch that
   never leaves the process. Every assertion holds on the file as it stands AND after the
   Generate drawer is made to refill on mount: this tests the harness, not the drawer's content. */

const shotProject = () => {
  const card = core.newCardShape("c1", { title: "Shot one", mode: "R2V", cast: ["a1"], duration: 5 });
  return { name: "T", target: 480, look: "", draft: false,
    assets: [{ id: "a1", name: "Her", kind: "image", tag: "@image1", thumbId: "T1", source: "", lock: true }],
    acts: [{ id: "act1", name: "Act 1", collapsed: false, cards: [card] }] };
};

const mounted = [];
const mount = async (o) => { const m = await mountLoomV2(o); mounted.push(m); return m; };
after(async () => { for (const m of mounted) await m.unmount(); });

describe("mountLoomV2: the real <LoomV2> under the fake DOM", () => {
  test("mounts with its effects running; the right panel starts collapsed, so there is no drawer node", async () => {
    const m = await mount({ project: shotProject(), selShot: "c1", thumbs: { T1: "data:image/jpeg;base64,AAAA" } });
    assert.ok(m.container.querySelectorAll(".lv-railbtn").length > 0, "the rail rendered");
    assert.equal(m.node, null, "the drawer is not mounted while the panel is collapsed");
    // The mount's two own reads ran (an effect ran) and were answered by the stub.
    const gets = fetchLog.calls.filter((c) => c.method === "GET").map((c) => c.path);
    assert.ok(gets.includes("/api/account"), "GET /api/account");
    assert.ok(gets.includes("/api/account/prefs"), "GET /api/account/prefs");
  });

  test("openPanel gives the drawer node with the host API hung on it", async () => {
    const m = await mount({ project: shotProject(), selShot: "c1" });
    const node = await m.openPanel();
    assert.ok(node, "the drawer node exists once the panel is open");
    assert.equal(m.node, node, "m.node is the same node");
    for (const fn of ["prefill", "payload", "flushPromptEdit", "setBusy", "setRefs"]) {
      assert.equal(typeof node[fn], "function", "node." + fn);
    }
    assert.equal(typeof node.mode, "string");
    await assert.rejects(() => m.openPanel("No such tab"), /no rail button titled/);
  });

  test("prefillCalls records each node.prefill(o) as a copy, per mount", async () => {
    const a = await mount({ project: shotProject(), selShot: "c1" });
    const node = await a.openPanel();
    const before = a.prefillCalls.length;
    const o = { mode: "flf", duration: 8, video_model: "v4.0.1", images: [], video_refs: [], audio_ref: null };
    node.prefill(o);
    assert.equal(a.prefillCalls.length, before + 1);
    const last = a.prefillCalls[a.prefillCalls.length - 1];
    assert.notEqual(last, o, "a copy, not the host's own object");
    assert.equal(last.mode, "flf");
    assert.equal(last.duration, 8);
    assert.equal(last.video_model, "v4.0.1");
    const b = await mount({ project: shotProject(), selShot: "c1" });
    const bNode = await b.openPanel();
    const bBefore = b.prefillCalls.length;
    const aBefore = a.prefillCalls.length;
    bNode.prefill({ mode: "i2v", images: [], video_refs: [], audio_ref: null });
    assert.equal(b.prefillCalls.length, bBefore + 1, "b's call lands in b's list");
    assert.equal(a.prefillCalls.length, aBefore, "and not in a's");
  });

  test("dispatch fires a bubbling event from the drawer node and the host's listeners hear it", async () => {
    const m = await mount({ project: shotProject(), selShot: "c1" });
    await assert.rejects(() => m.dispatch("mg-x", {}), /right panel is collapsed/);
    const node = await m.openPanel();
    const heard = [];
    node.addEventListener("mg-probe", (e) => heard.push({ detail: e.detail, bubbles: e.bubbles, target: e.target }));
    const docHeard = [];
    const onDoc = (e) => docHeard.push(e.detail);
    document.addEventListener("mg-probe", onDoc);
    try {
      const ev = await m.dispatch("mg-probe", { model: "tbkv1.0.1", duration: 12 });
      assert.ok(ev instanceof FEvent);
      assert.deepEqual(heard.map((x) => x.detail), [{ model: "tbkv1.0.1", duration: 12 }]);
      assert.equal(heard[0].target, node);
      assert.deepEqual(docHeard, [{ model: "tbkv1.0.1", duration: 12 }], "it bubbles to the document");
    } finally { document.removeEventListener("mg-probe", onDoc); }
  });

  test("collapse unmounts the drawer and a reopen mounts a NEW node", async () => {
    const m = await mount({ project: shotProject(), selShot: "c1" });
    const first = await m.openPanel();
    await m.collapse();
    assert.equal(m.node, null, "no drawer while collapsed");
    const second = await m.openPanel();
    assert.ok(second);
    assert.notEqual(second, first, "a reopen builds a fresh drawer node");
    await assert.rejects(() => m.collapse().then(() => m.collapse()), /not open/);
  });

  test("rerender merges over the earlier props and keeps project / entries / draft identity", async () => {
    const project = shotProject();
    const m = await mount({ project, selShot: "c1" });
    const p0 = m.props();
    assert.equal(p0.project, project);
    await m.rerender({ thumbs: { T1: "data:image/jpeg;base64,AAAA" } });
    const p1 = m.props();
    assert.notEqual(p1, p0);
    assert.equal(p1.project, project, "a thumbs delivery leaves the project object alone");
    assert.equal(p1.project.assets, project.assets);
    assert.equal(p1.entries, p0.entries, "entries are memoised by project identity");
    assert.equal(p1.draftCard, p0.draftCard, "one draft card per mount");
    assert.equal(p1.selShot, "c1", "earlier overrides persist");
    assert.deepEqual(Object.keys(p1.thumbs), ["T1"]);
    // A new project object is a new entries list; undefined drops the override back to the recipe.
    const edited = { ...project, acts: project.acts.map((a) => ({ ...a, cards: a.cards.map((c) => ({ ...c, title: "Renamed" })) })) };
    await m.rerender({ project: edited });
    assert.notEqual(m.props().entries, p1.entries);
    assert.equal(m.props().entries[0].c.title, "Renamed");
    await m.rerender({ selShot: undefined });
    assert.equal(m.props().selShot, null, "dropped override falls back to the recipe default");
  });

  test("every LoomV2 prop is supplied (the names come from the source's signature)", async () => {
    const m = await mount({});
    const props = m.props();
    assert.ok(Object.keys(props).length >= 80);
    for (const k of ["project", "entries", "thumbs", "selShot", "setCard", "projectApi", "draftCard", "costEstimate", "spend"]) {
      assert.ok(k in props, k);
    }
    assert.equal(typeof props.setCard, "function");
  });

  test("unmount removes the container's content and is idempotent", async () => {
    const m = await mount({ project: shotProject(), selShot: "c1" });
    await m.openPanel();
    await m.unmount();
    assert.equal(m.container.childNodes.length, 0);
    assert.equal(m.container.parentNode, null);
    await m.unmount();
    await assert.rejects(() => m.rerender({}), /already unmounted/);
  });

  test("nothing left the process: every request is the stub's, and no spend route was touched", () => {
    for (const c of fetchLog.calls) {
      assert.ok(c.path.startsWith("/api/"), "relative own-origin call: " + c.url);
    }
    const writes = fetchLog.calls.filter((c) => c.method !== "GET").map((c) => c.path);
    assert.deepEqual(writes.filter((p) => p !== "/api/price"), [], "only the price probe may POST here");
    for (const c of fetchLog.stray) assert.ok(fetchLog.calls.includes(c), "a stray call is also in the log");
  });
});
