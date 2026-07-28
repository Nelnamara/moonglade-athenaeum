import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { isCatalogMediaId } from "../src/loom-core.js";
import { parseCastIdsFromSearch } from "../src/loom-mutations.js";

/* Owner-found, 2026-07-28, during the med-review inspection pass: selected two imported
   images plus a video in the gallery, sent them to the Loom cast, and the Loom opened with
   nothing in it.

   Two id families exist and the Loom knew one. A PixAI generation's media_id is all digits;
   an imported local file's is `local_<12 hex>` (moonglade_backup.local_media_id). EIGHT
   independent `/^\d+$/` tests -- in loom-core, loom-mutations, master-storyboard.jsx and
   mg-generate-drawer.js -- each decided on their own that a media_id is digits, so an
   imported picture was dropped by the cast import, then unresolvable as a cast picture,
   then unthumbnailable in the drawer preview. Same shape as this file's other findings:
   one fact, answered independently in several places, drifting when reality gained a case. */

describe("imported local media ids are first-class in the Loom", () => {
  test("isCatalogMediaId accepts both families and rejects what is neither", () => {
    assert.ok(isCatalogMediaId("747000000000000001"), "a PixAI id");
    assert.ok(isCatalogMediaId("local_a1b2c3d4e5f6"), "an imported file's content-addressed id");
    // Not ids: the two other things a `source` field legitimately holds, plus junk.
    assert.ok(!isCatalogMediaId("data:image/png;base64,AAAA"));
    assert.ok(!isCatalogMediaId("https://example.test/x.png"));
    assert.ok(!isCatalogMediaId("local_NOTHEX00000"), "the hex tail is load-bearing");
    assert.ok(!isCatalogMediaId("local_a1b2c3"), "12 hex digits, not fewer");
    assert.ok(!isCatalogMediaId(""));
    assert.ok(!isCatalogMediaId(null));
    assert.ok(!isCatalogMediaId(undefined));
  });

  test("the cast import keeps an imported id -- the owner's exact repro", () => {
    const ids = parseCastIdsFromSearch("?cast=747000000000000001,local_a1b2c3d4e5f6");
    assert.deepEqual(ids, ["747000000000000001", "local_a1b2c3d4e5f6"],
      "an imported picture sent to the cast must survive the URL parse -- dropping it is " +
      "why the Loom opened empty");
  });

  test("a cast of only imported pictures still arrives", () => {
    // The pure form of the bug: every selected id was local_, so the filter emptied the
    // list entirely and the import effect returned before adding anything.
    assert.equal(parseCastIdsFromSearch("?cast=local_aaaaaaaaaaaa,local_bbbbbbbbbbbb").length, 2);
  });

  test("the sanitiser still refuses anything that could escape a URL or a path", () => {
    const hostile = "?cast=" + [
      "../../etc/passwd", "a/b", "a%2Fb", "<script>", "a b", "'", '"', "a;b", "..",
    ].map(encodeURIComponent).join(",");
    assert.deepEqual(parseCastIdsFromSearch(hostile), [],
      "widening the id grammar must not widen what the URL parser will accept");
  });

  test("an over-long id is refused", () => {
    assert.deepEqual(parseCastIdsFromSearch("?cast=" + "9".repeat(65)), []);
  });
});
