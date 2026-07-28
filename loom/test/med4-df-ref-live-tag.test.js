import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* DEEP FOCUS "OTHER REFERENCES" LIVE TAGS (2026-07-27, round 3).

   Round 2 gave the Cast & assets rows a READ-ONLY live positional tag beside the editable
   stored tag (positionTag() -- the number the composed prompt and the generator actually
   use) and left Deep Focus's Other-references rows showing ONLY the stale stored r.tag.
   A ref whose real position had shifted (a frame attached, a cast change) kept asserting
   a number nothing else uses. This pins the round-3 repair: ref rows get the same
   treatment, THROUGH THE SAME shared helpers (liveTagText/liveTagTitle), so the two row
   types cannot drift apart again.

   This runner has no jsdom (see mg-generate-drawer-concurrent.test.js's comment), so a
   React render can't be exercised; the pin is on the JSX source the same way
   med3-prefill-effect-frame-deps.test.js pins the dependency array. The helpers'
   BEHAVIOR (wording, mode families) is covered by med4-mode-aware-panel.test.js. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const jsx = readFileSync(path.join(__dirname, "../master-storyboard.jsx"), "utf8")
  .replace(/\r\n/g, "\n");   // working trees on this machine can be CRLF; every pattern below assumes LF

// The Other-references map: from its label to the add-ref buttons that close the block.
const m = jsx.match(/Other references &amp; @tags<\/label>([\s\S]*?)\+ Image<\/button>/);

describe("Deep Focus ref rows carry the live positional tag", () => {
  test("the Other references block is still recognizable", () => {
    assert.ok(m, "could not locate the Other references block in master-storyboard.jsx -- " +
      "if Deep Focus was restructured, update this pattern, don't delete the test");
  });

  test("image refs get a live positionTag beside the editable stored tag", () => {
    assert.match(m[1], /positionTag\(live, project, imgSrc, r\.id\)/,
      "ref rows must show the LIVE positional @imageN (what the composed prompt and " +
      "the r2v/v2v generator actually use) -- round 2 left them showing only the stale " +
      "stored r.tag");
    assert.match(m[1], /<input className="sb-tagin sb-mono" value=\{r\.tag\}/,
      "the EDITABLE stored-tag input must stay -- the live tag renders beside it, " +
      "never replaces it (it still drives ref identity/wording)");
  });

  test("the live tag wears the same styling family as the cast rows (.lv-livetag/.oob)", () => {
    assert.match(m[1], /"lv-livetag" \+ \(refPastBudget \? " oob" : ""\)/,
      "same .lv-livetag / past-budget .oob treatment the cast rows got in round 2 -- " +
      "a different styling family here is how the two row types drift");
  });

  test("wording comes from the SHARED helpers, so ref rows and cast rows cannot drift", () => {
    assert.match(m[1], /liveTagTitle\(refLiveTag, refPastBudget, c\.mode, live\.code\)/,
      "the tooltip must come from liveTagTitle -- the one wording source the cast rows " +
      "use (mode-aware: no send-ness claims on FLF/I2V)");
    assert.match(m[1], /liveTagText\(refLiveTag, refPastBudget, c\.mode\)/,
      "the label (live tag / 'not sent' / 'not cited' / dash) must come from " +
      "liveTagText, same as the cast rows");
  });

  test("video/audio refs are left alone -- their stored tag IS the live name", () => {
    assert.match(m[1], /r\.kind === "image" \? positionTag\(live, project, imgSrc, r\.id\) : null/,
      "@videoN/@audioN are their own namespaces, never renumbered by position " +
      "(shotText prints a video ref's stored tag verbatim -- see its video-ref " +
      "comment); a positional 'live' copy would be a second numbering system, the " +
      "exact corruption class loom-core.js exists to end");
  });
});
