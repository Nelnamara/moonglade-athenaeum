import { test, describe } from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_SAVER_MODE, PULL_HOLD, PULL_MAX, PULL_THRESHOLD, SAVER_THUMB,
  accessionStamp, backgroundReadAllowed, catalogNumber, connectionInfo, humanBytes, isFrontPage,
  makeMarker, needsFullTap, newSince, newSinceLabel, newestLabel, parseLayout, parseMarker,
  parseSaverMode, placardStrip, pullArmed, pullDistance, pullFraction, pullLabel, pullMayStart,
  saverActive, saverSub, showNewest, syncOutcomeText, taskIdsOf, thumbSrc, tsOf,
} from "../../gallery/src/lib/phoneCore.js";

/* Session Q, "The phone" (Phone Handoff.dc.html): the rules behind the placard, the reading feed, "new
   since", pull to refresh and Data saver, run as the page states them. */

describe("Q3 layout", () => {
  test("only an exact 'feed' is the feed; everything else is the grid the phone shipped with", () => {
    assert.equal(parseLayout("feed"), "feed");
    for (const v of ["grid", "", null, undefined, "FEED", "list", 3]) assert.equal(parseLayout(v), "grid");
  });
});

describe("Q7 Data saver: the mode", () => {
  test("Auto on metered is the default and an unknown stored value never becomes Off", () => {
    assert.equal(DEFAULT_SAVER_MODE, "auto");
    assert.equal(parseSaverMode(undefined), "auto");
    assert.equal(parseSaverMode("banana"), "auto");
    for (const m of ["off", "auto", "always"]) assert.equal(parseSaverMode(m), m);
  });

  test("Off never acts, Always always acts, whatever the connection says", () => {
    const cell = connectionInfo({ type: "cellular" });
    const wifi = connectionInfo({ type: "wifi" });
    for (const info of [cell, wifi, connectionInfo(null)]) {
      assert.equal(saverActive("off", info), false);
      assert.equal(saverActive("always", info), true);
    }
  });

  test("Auto acts only when the browser SAYS the connection is metered", () => {
    assert.equal(saverActive("auto", connectionInfo({ type: "cellular" })), true);
    assert.equal(saverActive("auto", connectionInfo({ type: "wifi" })), false);
    assert.equal(saverActive("auto", connectionInfo({ type: "ethernet" })), false);
    assert.equal(saverActive("auto", connectionInfo({ saveData: true })), true);   // the user's own request
  });

  test("Auto where the browser cannot tell stays OFF (iPhone Safari has no API at all) and says so", () => {
    const none = connectionInfo(null);
    assert.equal(none.known, false);
    assert.equal(saverActive("auto", none), false);
    // an API that only reports a speed class does not know what the connection costs either
    const speedOnly = connectionInfo({ effectiveType: "4g" });
    assert.equal(speedOnly.known, false);
    assert.equal(saverActive("auto", speedOnly), false);
    assert.equal(connectionInfo({ type: "unknown" }).known, false);
    assert.equal(connectionInfo({ type: "other" }).known, false);
    const line = saverSub("auto", none);
    assert.match(line, /can.t tell/);
    assert.match(line, /Always/);
  });

  test("the Control row's sub line names what it is doing", () => {
    assert.equal(saverSub("off", connectionInfo(null)), "Off");
    assert.equal(saverSub("always", connectionInfo(null)), "On · always");
    assert.equal(saverSub("auto", connectionInfo({ type: "cellular" })), "On · metered connection");
    assert.match(saverSub("auto", connectionInfo({ type: "wifi" })), /on Wi-Fi, so it.s off/);
    assert.match(saverSub("auto", connectionInfo({ saveData: true, type: "wifi" })), /asking to save data/);
  });
});

describe("Q7 Data saver: what it changes", () => {
  test("thumbnails go to the 256 tier only for the library's own /thumbs route, only when acting", () => {
    assert.equal(SAVER_THUMB, 256);
    assert.equal(thumbSrc("/thumbs/12.jpg", true), "/thumbs/12.jpg?s=256");
    assert.equal(thumbSrc("/thumbs/12.jpg", false), "/thumbs/12.jpg");            // saver off: byte-identical
    assert.equal(thumbSrc("/thumbs/12.jpg?v=3", true), "/thumbs/12.jpg?v=3&s=256");
    assert.equal(thumbSrc("/thumbs/12.jpg?s=32", true), "/thumbs/12.jpg?s=32");   // a size already named stays
    assert.equal(thumbSrc("https://elsewhere/x.jpg", true), "https://elsewhere/x.jpg");
    assert.equal(thumbSrc("/full/12", true), "/full/12");
    assert.equal(thumbSrc(undefined, true), undefined);
  });

  test("full size waits for a tap while acting, once per picture", () => {
    assert.equal(needsFullTap(true, {}, "1"), true);
    assert.equal(needsFullTap(true, { 1: true }, "1"), false);
    assert.equal(needsFullTap(true, { 1: true }, "2"), true);
    assert.equal(needsFullTap(false, {}, "1"), false);
  });

  test("background reads wait while the saver acts; a pull never asks (it has no such check)", () => {
    assert.equal(backgroundReadAllowed(true), false);
    assert.equal(backgroundReadAllowed(false), true);
  });

  test("the size line is honest: bytes to KB / MB, and nothing when unknown", () => {
    assert.equal(humanBytes(0), "");
    assert.equal(humanBytes(undefined), "");
    assert.equal(humanBytes(NaN), "");
    assert.equal(humanBytes(900), "900 B");
    assert.equal(humanBytes(6 * 1024), "6 KB");
    assert.equal(humanBytes(2.44 * 1024 * 1024), "2.4 MB");
    assert.equal(humanBytes(48 * 1024 * 1024), "48 MB");
  });
});

describe("Q1 the placard", () => {
  test("the catalog number is the media id's tail, four characters", () => {
    assert.equal(catalogNumber("2038314167804392533"), "2533");
    assert.equal(catalogNumber("local_ab12cd"), "12CD");
    assert.equal(catalogNumber("7"), "0007");
    assert.equal(catalogNumber(""), "");
    assert.equal(catalogNumber(null), "");
  });

  test("the stamp is the page's: ACC. year, month-day, number, then the day in words", () => {
    // a bare day carries no zone and is passed through, so this is stable in any time zone
    assert.equal(accessionStamp({ media_id: "4401", created_at: "2026-09-18" }), "ACC. 2026·0918·4401 · 18 SEP");
    assert.equal(accessionStamp({ media_id: "4401" }), "ACC. 4401");
    assert.equal(accessionStamp({ created_at: "2026-01-05" }), "ACC. 2026·0105 · 05 JAN");
    assert.equal(accessionStamp({}), "");
    assert.equal(accessionStamp(null), "");
  });

  test("the stamp reads the viewer's LOCAL day from a full timestamp", () => {
    const iso = "2026-09-18T06:30:00.000Z";
    const d = new Date(iso);
    const want = String(d.getMonth() + 1).padStart(2, "0") + String(d.getDate()).padStart(2, "0");
    const got = accessionStamp({ media_id: "9", created_at: iso });
    assert.ok(got.includes("·" + want + "·"), got);
  });

  test("the page's tasks are collected once, in order, skipping pictures with no task", () => {
    assert.deepEqual(taskIdsOf([{ task_id: "A" }, { task_id: "B" }, { task_id: "A" }, { task_id: "" }, {}]), ["A", "B"]);
    assert.deepEqual(taskIdsOf(null), []);
  });

  test("a batch draws its strip with the current one ringed; a lone picture says 'single image'", () => {
    const items = [{ media_id: "1" }, { media_id: "2" }, { media_id: "3" }];
    const sibs = [{ media_id: "1", thumb: "/t1" }, { media_id: "2", thumb: "/t2" }, { media_id: "9", thumb: "/t9" }];
    const s = placardStrip(items[1], sibs, items);
    assert.equal(s.single, false);
    assert.equal(s.line, "siblings · batch of 3");
    assert.deepEqual(s.tiles.map((t) => [t.media_id, t.index, t.current]),
      [["1", 0, false], ["2", 1, true], ["9", -1, false]]);       // 9 lives on another page: index -1
    for (const none of [undefined, null, [], [{ media_id: "1", thumb: "/t1" }]]) {
      const one = placardStrip(items[0], none, items);
      assert.equal(one.single, true);
      assert.equal(one.line, "single image");
      assert.deepEqual(one.tiles, []);
    }
  });
});

describe("Q5 new since", () => {
  const at = (id, iso) => ({ media_id: id, created_at: iso });
  const page = [at("5", "2026-09-28T20:00:00Z"), at("4", "2026-09-28T19:00:00Z"), at("3", "2026-09-28T18:00:00Z"),
    at("2", "2026-09-28T17:00:00Z"), at("1", "2026-09-28T16:00:00Z")];

  test("the marker is the newest picture, when it was, and the clock time the visit ended", () => {
    const m = makeMarker(page, 1234);
    assert.deepEqual(m, { id: "5", ts: Date.parse("2026-09-28T20:00:00Z"), at: 1234 });
    assert.equal(makeMarker([], 1), null);
    assert.equal(makeMarker(null, 1), null);
  });

  test("a stored marker parses, and garbage is no marker at all", () => {
    assert.deepEqual(parseMarker(JSON.stringify({ id: "5", ts: 7, at: 9 })), { id: "5", ts: 7, at: 9 });
    for (const bad of [null, "", "{", "[]", "{}", JSON.stringify({ ts: 1 }), 5, undefined]) assert.equal(parseMarker(bad), null);
  });

  test("the count is how many pictures sit above the marker picture", () => {
    assert.deepEqual(newSince(page, { id: "3", ts: 0, at: 1 }), { count: 2, capped: false });
    assert.deepEqual(newSince(page, { id: "5", ts: 0, at: 1 }), { count: 0, capped: false });   // nothing new: no rule
  });

  test("first visit (no marker) has nothing to be new since", () => {
    assert.deepEqual(newSince(page, null), { count: 0, capped: false });
    assert.deepEqual(newSince([], { id: "3", ts: 1, at: 1 }), { count: 0, capped: false });
  });

  test("a marker picture that is gone falls back to the timestamp; all-new is capped", () => {
    const gone = { id: "77", ts: Date.parse("2026-09-28T17:30:00Z"), at: 1 };
    assert.deepEqual(newSince(page, gone), { count: 3, capped: false });          // 5, 4, 3 are newer
    const old = { id: "77", ts: Date.parse("2026-09-01T00:00:00Z"), at: 1 };
    assert.deepEqual(newSince(page, old), { count: 5, capped: true });            // more than a page: "5+"
    assert.deepEqual(newSince(page, { id: "77", ts: 0, at: 1 }), { count: 0, capped: false });
  });

  test("the rule reads 'N new since HH:MM' and is empty at zero", () => {
    const t = new Date(2026, 8, 28, 21, 40).getTime();
    assert.equal(newSinceLabel(5, false, t), "5 new since 21:40");
    assert.equal(newSinceLabel(100, true, t), "100+ new since 21:40");
    assert.equal(newSinceLabel(0, false, t), "");
    assert.equal(newSinceLabel(3, false, 0), "3 new");
    assert.equal(tsOf("nope"), 0);
  });

  test("the rule belongs to the library's front page and nowhere else", () => {
    const front = { page: 1, advCount: 0, applied: "", media: "", shelf: "", similar: false, loaded: true };
    assert.equal(isFrontPage(front), true);
    assert.equal(isFrontPage({ ...front, page: 2 }), false);
    assert.equal(isFrontPage({ ...front, advCount: 1 }), false);         // a sort, a model, a date...
    assert.equal(isFrontPage({ ...front, applied: "moon" }), false);
    assert.equal(isFrontPage({ ...front, applied: "   " }), true);
    assert.equal(isFrontPage({ ...front, media: "video" }), false);
    assert.equal(isFrontPage({ ...front, shelf: "Keepers" }), false);
    assert.equal(isFrontPage({ ...front, similar: true }), false);
    assert.equal(isFrontPage({ ...front, loaded: false }), false);        // nothing has loaded yet
  });

  test("'↑ Newest' appears after ONE screen of scrolling, and carries the count", () => {
    assert.equal(showNewest(0, 600), false);
    assert.equal(showNewest(600, 600), false);
    assert.equal(showNewest(601, 600), true);
    assert.equal(showNewest(561, 0), true);        // no measured height: the page's own 560 stands in
    assert.equal(newestLabel(0), "↑ Newest");
    assert.equal(newestLabel(5), "↑ Newest · 5 new");
  });
});

describe("Q6 pull to refresh", () => {
  test("the numbers are the page's: release past 72, the page follows at 0.6 up to 90, rests at 44", () => {
    assert.equal(PULL_THRESHOLD, 72);
    assert.equal(PULL_MAX, 90);
    assert.equal(PULL_HOLD, 44);
    assert.equal(pullDistance(100), 60);
    assert.equal(pullDistance(1000), 90);
    assert.equal(pullDistance(-40), 0);
    assert.equal(pullDistance(0), 0);
    assert.equal(pullDistance("x"), 0);
  });

  test("the moon fills with a TRUE fraction of the distance to the line, and no more than full", () => {
    assert.equal(pullFraction(0), 0);
    assert.equal(pullFraction(36), 0.5);
    assert.equal(pullFraction(72), 1);
    assert.equal(pullFraction(90), 1);
    assert.equal(pullFraction(-3), 0);
    assert.equal(pullFraction(NaN), 0);
    // strictly linear below the line: no easing that would make the moon lie about the distance
    for (let px = 0; px <= 72; px += 6) assert.equal(pullFraction(px), px / 72);
  });

  test("release arms at 72 and not a pixel before", () => {
    assert.equal(pullArmed(71.9), false);
    assert.equal(pullArmed(72), true);
    assert.equal(pullArmed(90), true);
    assert.equal(pullArmed(0), false);
  });

  test("a pull starts only at the very top and never while one is running", () => {
    assert.equal(pullMayStart(0, false), true);
    assert.equal(pullMayStart(1, false), false);
    assert.equal(pullMayStart(300, false), false);
    assert.equal(pullMayStart(0, true), false);
  });

  test("the label follows the state the page names", () => {
    assert.equal(pullLabel({ syncing: false, px: 10 }), "pull to refresh");
    assert.equal(pullLabel({ syncing: false, px: 72 }), "release to sync");
    assert.equal(pullLabel({ syncing: true, px: 0 }), "syncing with PixAI…");
  });

  test("how a sync ended, in words", () => {
    assert.equal(syncOutcomeText({ state: "done" }), "");
    assert.equal(syncOutcomeText(null), "");
    assert.match(syncOutcomeText({ state: "busy" }), /already running/);
    assert.match(syncOutcomeText({ state: "timeout" }), /Still syncing/);
    assert.match(syncOutcomeText({ state: "failed", error: "it was stopped" }), /didn.t finish: it was stopped/);
    assert.equal(syncOutcomeText({ state: "error", error: "a job is already running" }), "a job is already running");
    assert.match(syncOutcomeText({ state: "error" }), /didn.t start/);
  });
});
