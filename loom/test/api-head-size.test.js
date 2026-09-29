import { test, describe, afterEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { apiGet, apiHeadSize } from "../../gallery/src/api.js";

/* The phone's Data saver reads a served file's size with a HEAD (Session Q, Q7). It must ride the
   one request() seam in gallery/src/api.js -- one fetch, one place a response is read -- and the
   merged tree still holds request-module-structure's "exactly one request, exactly one body read". */

const here = path.dirname(fileURLToPath(import.meta.url));
const API = readFileSync(path.join(here, "..", "..", "gallery", "src", "api.js"), "utf8").replace(/\r\n/g, "\n");
const realFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = realFetch; });

function stub(answer) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push([url, init]);
    if (answer instanceof Error) throw answer;
    return answer;
  };
  return calls;
}
const resp = (ok, len, body) => ({
  ok, status: ok ? 200 : 404, statusText: ok ? "OK" : "Not Found",
  headers: { get: (h) => (String(h).toLowerCase() === "content-length" ? len : null) },
  json: async () => { if (body === undefined) throw new Error("a HEAD has no body"); return body; },
});

describe("apiHeadSize rides request()", () => {
  test("one HEAD fetch through the seam, its size from Content-Length, no body read", async () => {
    const calls = stub(resp(true, "2516582"));
    assert.equal(await apiHeadSize("/full/abc"), 2516582);
    assert.equal(calls.length, 1);
    assert.equal(calls[0][0], "/full/abc");
    assert.equal(calls[0][1].method, "HEAD");
  });

  test("fail-soft: a 404, a missing or zero Content-Length and a network error are all 0, never a throw", async () => {
    stub(resp(false, "99"));
    assert.equal(await apiHeadSize("/full/x"), 0);
    stub(resp(true, null));
    assert.equal(await apiHeadSize("/full/x"), 0);
    stub(resp(true, "0"));
    assert.equal(await apiHeadSize("/full/x"), 0);
    stub(new Error("offline"));
    assert.equal(await apiHeadSize("/full/x"), 0);
  });

  test("a GET is untouched: the body still wins, an error body is the answer", async () => {
    stub(resp(true, "5", { error: "nope", extra: 1 }));
    assert.deepEqual(await apiGet("/api/x"), { error: "nope", extra: 1 });
    stub(resp(true, "5", { ok: true }));
    assert.deepEqual(await apiGet("/api/x"), { ok: true });
  });

  test("the module keeps one fetch and one body read, and the HEAD branch sits before the read", () => {
    const code = API.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
    assert.equal((code.match(/\bfetch\(/g) || []).length, 1);
    assert.equal((code.match(/\br\.json\(\)/g) || []).length, 1);
    assert.ok(code.indexOf('rest.method === "HEAD"') < code.indexOf("r.json()"));
  });
});
