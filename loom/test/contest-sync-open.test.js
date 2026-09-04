import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  syncOnOpen, NO_TOKEN, REFUSED, SKIPPED, WATCH,
} from "../../gallery/src/hooks/contestSyncFlow.js";

/* The blocker this pins (adversarial review, 2026-09-03): the CSRF token was fetched in one
   effect and read from a ref by a sibling effect on the same mount, so the POST always went
   out with "" -- the server refused every Contests open with a 400 and the on-open sweep
   never ran. The ordering is the whole behaviour, so the ordering is what is asserted. */

const later = (v, ms = 5) => new Promise((r) => setTimeout(() => r(v), ms));

describe("the Contests-open sync handshake", () => {
  test("the POST waits for the token -- it never fires before one resolves", async () => {
    const order = [];
    const getToken = async () => { await later(null, 8); order.push("token"); return "T1"; };
    const post = async (tok) => { order.push("post:" + tok); return { started: true }; };
    const res = await syncOnOpen(getToken, post);
    assert.deepEqual(order, ["token", "post:T1"], "the token must resolve FIRST");
    assert.equal(res.outcome, WATCH);
  });

  test("an empty token means do not call at all", async () => {
    // The exact shape of the bug: a token that never arrives must not produce a POST the
    // server can only refuse.
    let posted = 0;
    const res = await syncOnOpen(async () => "", async () => { posted++; return {}; });
    assert.equal(posted, 0, "no POST may be made without a token");
    assert.equal(res.outcome, NO_TOKEN);
  });

  test("a token that arrives slowly still gets used", async () => {
    const res = await syncOnOpen(() => later("SLOW", 20), async (tok) => {
      assert.equal(tok, "SLOW");
      return { started: true };
    });
    assert.equal(res.outcome, WATCH);
  });

  test("a refusal is not a completed sync", async () => {
    const res = await syncOnOpen(async () => "T", async () => ({ error: "session expired" }));
    assert.equal(res.outcome, REFUSED);
    assert.equal(res.error, "session expired");
    const dead = await syncOnOpen(async () => "T", async () => null);
    assert.equal(dead.outcome, REFUSED);
  });

  test("a recent sweep is reported as skipped, not watched", async () => {
    const res = await syncOnOpen(async () => "T",
                                 async () => ({ started: false, skipped: "recent" }));
    assert.equal(res.outcome, SKIPPED);
  });

  test("a busy sweep is still watched -- somebody else's run is finishing", async () => {
    const res = await syncOnOpen(async () => "T",
                                 async () => ({ started: false, busy: true }));
    assert.equal(res.outcome, WATCH);
  });
});
