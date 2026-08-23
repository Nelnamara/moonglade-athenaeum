import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE STALE-FREE RACE (issue #15 follow-up, 2026-08-16), as wired into <VideoDrawer>.

   The gate itself -- priceKey / canSubmit / shouldShortCircuit and the verdict state machine --
   moved to gallery/src/gen/priceProbeCore.js on 2026-08-22 so all six cost lines ride it, and the
   sequences that used to spend against the wrong quote are driven there, against the shared
   module (loom/test/price-probe-core.test.js). The one-module/one-fetch structure is pinned in
   loom/test/price-probe-structure.test.js.

   What stays HERE is what is genuinely this drawer's: that its build() reports the two video idle
   cases as verdicts with the right words, that canGo reads the probe, that doGenerate refuses a
   stale click out loud instead of dropping it, that the post-submit re-price is FORCED, and that
   every handler writing a priced form field schedules one. There is no React harness in this
   runner, so source guards are the established pattern for a file in this position. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const src = readFileSync(path.join(__dirname, "../../gallery/src/components/VideoDrawer.jsx"), "utf8")
  .replace(/\r\n/g, "\n");

function fnBody(name, close) {
  // Accept any parameter list -- a signature change must not silently turn these guards into a
  // false pass/fail.
  const m = new RegExp("const " + name + " = (?:useCallback\\()?\\([^)]*\\) => \\{").exec(src);
  assert.ok(m, "expected to find " + name + "(...) in VideoDrawer.jsx");
  const i = m.index;
  const end = src.indexOf(close || "\n  };", i);   // component-level 2-space indent closes it
  assert.ok(end > i, "could not find the end of " + name);
  return src.slice(i, end);
}

describe("<VideoDrawer> rides the shared price probe", () => {
  test("the drawer keeps NO price machinery of its own any more", () => {
    // Every one of these was a hand-rolled copy of something the probe now owns. A reappearance
    // is a second debounce/seq/verdict living beside the shared one -- which is how the gate came
    // to exist in one of six hosts in the first place.
    ["costSeq", "costTimer", "st.current.price", "const debCost", "const costNow"].forEach((dead) => {
      assert.ok(!src.includes(dead), dead + " must be gone -- gen/usePriceProbe.js owns it now");
    });
    assert.match(src, /const probe = usePriceProbe\(\{ build, costRef \}\);/,
      "the drawer must instantiate the probe with its own build() and its own CostBadge ref");
    assert.match(src, /const reprice = probe\.refresh;/);
  });

  test("build() reports BOTH video idle cases as verdicts, with the mode-dependent wording", () => {
    // The idle hints are verdicts too: "nothing to price" settles, which keeps Go live so
    // doGenerate's own "Pick a source image first" line stays reachable. Leaving them unsettled
    // would kill the button with no message on screen (fail-silent-closed).
    const body = fnBody("build", "\n  }, []);");
    assert.match(body, /if \(!hasAnyRef\(p\)\)/, "no refs at all is the first idle case");
    assert.match(body, /st\.current\.mode === "r2v"/,
      "the no-refs hint is mode-dependent (Multi-Reference asks for a reference, not a source image)");
    assert.match(body, /Pick at least one reference to see the cost\./);
    assert.match(body, /Pick a source image to see the cost\./);
    assert.match(body, /if \(flfMissingStart\(\)\)/,
      "FLF with an End Frame but no Start Frame is a DIFFERENT generation -- one predicate for Go AND the badge");
    assert.match(body, /Pick a Start Frame — the End Frame alone can’t drive First & Last\./);
    assert.match(body, /return \{ payload: p \};/, "everything else is priceable");
  });

  test("canGo reads the probe's verdict, and the v4.0 caution still rides the badge", () => {
    assert.match(src, /const canGo = !s\.hostBusy && !s\.rendering && probe\.canSubmit;/);
    assert.match(src, /const warn = s\.model === "v4\.0" \? "V4\.0 full — ~2\.5× Lite" : "";/,
      "v4.0 full is ~2.5x Lite (210k for a 15s clip) -- the badge must still say so");
    assert.match(src, /<CostBadge ref=\{costRef\}[^\n]*warn=\{warn\}/);
  });

  test("doGenerate() gates the submit on the probe and never silently drops the click", () => {
    const body = fnBody("doGenerate");
    const gate = body.indexOf("probe.canSubmit");
    const submit = body.indexOf('fetch("/api/loom/generate"');
    assert.ok(gate >= 0, "doGenerate must consult probe.canSubmit");
    assert.ok(submit >= 0);
    assert.ok(gate < submit, "the identity gate must sit before the spend");
    const gateBlock = body.slice(gate, submit);
    assert.match(gateBlock, /pushLine\(/, "a refused click must say so (an error line), not vanish");
    assert.match(gateBlock, /reprice\(\)/, "a refused click must kick a re-price");
    // Refusal-path starvation: an unconditional re-price discarded a quote about to settle and
    // restarted the debounce, so fast repeated clicks kept the badge from ever settling.
    assert.match(gateBlock, /checkInFlight/, "a check already in flight must be allowed to land");
    assert.match(gateBlock, /if \(!checkInFlight\) reprice\(\);/);
    // the rendering latch is untouched: it is set only on the path that actually submits
    const latch = body.indexOf("st.current.rendering = true");
    assert.ok(latch > gate && latch < submit, "the busy latch stays between the gate and the submit");
  });

  test("doGenerate() re-prices (FORCED) right after a successful submit -- the balance changed, the payload did not", () => {
    // Review 2026-08-16, the most serious finding: nothing re-priced after the drawer's own submit
    // consumed the tickets, so a settled FREE for the unchanged payload passed the gate and a
    // second click submitted under a FREE badge for a clip the server now found SHORT and charged
    // in full -- the exact #15 shape the identity gate exists to stop.
    const body = fnBody("doGenerate");
    const submit = body.indexOf('emit("mg-submit"');
    const reprice = body.indexOf("reprice({ force: true })");
    assert.ok(submit >= 0, "the success path emits mg-submit");
    assert.ok(reprice >= 0, "the success path must force a re-price");
    assert.ok(reprice > submit, "the forced re-price sits in the SUCCESS branch after mg-submit");
  });

  test("Quality + Camera handlers re-price like every other priced field", () => {
    const cam = src.match(/className="mgd-sel mgd-cam"[^\n]*onChange=\{\(e\) => \{([^\n]*)\}\}/);
    // Quality is the DC's Basic|Professional segmented pair (2026-08-16 fidelity pass), so its
    // handler is the segment's onClick rather than a <select>'s onChange -- same guard.
    const qual = src.match(/className=\{"mgd-quality"[^\n]*onClick=\{\(\) => \{([^\n]*)\}\}/);
    assert.ok(cam && qual, "expected the Camera select and the Quality segment");
    assert.match(cam[1], /reprice\(\)/, "Camera onChange must re-price -- cameraMovement is priced");
    assert.match(qual[1], /reprice\(\)/, "Quality onClick must re-price -- i2vPro.mode is priced");
  });

  test("every handler that writes a priced form field schedules a re-price", () => {
    // Every `st.current.<field> = ` assignment inside a JSX onChange for a buildPayload input
    // must be followed by reprice() on the same line. imgSlots/vidSlots `.push(null)` adds an
    // EMPTY slot (payload unchanged) and is exempt by construction.
    // `negative` is NOT here on purpose: it is in the probe's identity skip ("never prices"), so
    // listing it as priced would contradict priceKey. Its handler may still re-price --
    // harmlessly, because the probe short-circuits on an unchanged settled key.
    const priced = ["model", "duration", "camera", "quality", "channel", "audioGen", "audioLanguage", "videoHelper", "audSlot"];
    const lines = src.split("\n").filter((l) => /onChange=|onClick=/.test(l));
    priced.forEach((f) => {
      lines.filter((l) => new RegExp("st\\.current\\." + f + " = ").test(l)).forEach((l) => {
        assert.match(l, /reprice\(\)/, "handler writing st.current." + f + " must re-price: " + l.trim());
      });
    });
  });
});
