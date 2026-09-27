import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  ASPECTS, GEN_DEFAULTS, UNLIMITED_BUSY, UNLIMITED_PRO, buildPayload, goGate, laneBusy,
  laneRefusesFrame, laneSizeOk, unlimitedBlock, unlimitedDaysText, unlimitedOffered,
  unlimitedPatch, unlimitedRules,
} from "../../gallery/src/gen/genCore.js";

/* Tsubaki.3 Unlimited Mode, the client half (SCOPE_2026-09-26_unlimited-mode C1-C5, §8
   amendments binding). The server's lane check, the entitlement and the spend choke are
   tests/test_tsubaki3_image_gate.py and tests/test_payload_road.py; the dock's rendering is
   tests/test_render_harness.py. This file pins the drawer's rules directly: when the payload
   carries the flag, what switching on forces, and why the switch or Generate is refused. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(path.resolve(__dirname, rel), "utf8").replace(/\r\n/g, "\n");
const at = (label) => ASPECTS.find(([l]) => l === label)[1];

// /api/model-version's meta for Tsubaki.3 with a held grant (moonglade_backup._attach_unlimited).
const T3 = {
  version_id: "2024383379556065549", model_id: "M-T3", title: "Tsubaki.3",
  size_rule: { step: 16, lo: 512, hi: 2496 },
  unlimited: {
    owned: true, expires_at: "2026-10-25T00:00:00Z", days_left: 29,
    size: { max_area: 1800 * 1800, max_side: 1792,
      ranges: [[512, 2496, 512, 2496], [512, 2200, 512, 2200], [512, 1800, 512, 1800]] },
  },
};
const FLASH = { version_id: "2050048243034896798", model_id: "M-F", size_rule: T3.size_rule,
  unlimited: null };
const draft = (patch) => ({ ...GEN_DEFAULTS, prompt: "a moonwell", model: T3, ...patch });

describe("C1 / §8.1 -- the payload carries the flag whenever the switch is on", () => {
  test("off: no key at all, so an ordinary payload is byte-identical to before", () => {
    assert.equal("unlimited" in buildPayload(draft()), false);
  });
  test("on: sent -- offered or not; only the user turns it off", () => {
    assert.equal(buildPayload(draft({ unlimited: true })).unlimited, true);
    // a model that does not offer the lane (Flash, a Remix onto an older version, a failed
    // status read): the flag still goes, and the server's refusal is what the badge shows
    assert.equal(buildPayload(draft({ unlimited: true, model: FLASH })).unlimited, true);
  });
  test("offered only on a live, owned status", () => {
    assert.equal(unlimitedOffered(T3), true);
    assert.equal(unlimitedOffered(FLASH), false);
    assert.equal(unlimitedOffered({ ...T3, unlimited: { ...T3.unlimited, owned: false } }), false);
    assert.equal(unlimitedOffered(null), false);
  });
  test("applying a version sets the offer and never touches the switch", () => {
    const src = read("../../gallery/src/gen/useGenerate.js");
    assert.match(src, /unlimited: v\.unlimited \|\| null/);
    assert.doesNotMatch(src, /unlimited: false/, "a model switch must not turn the lane off");
    assert.match(src, /s\.mode, s\.steps, s\.unlimited,/, "the switch must re-price");
  });
});

describe("C3 -- switching on forces what the lane runs on, visibly", () => {
  test("Pro, one picture, no High priority -- and off touches nothing else", () => {
    assert.deepEqual(unlimitedPatch(true),
      { unlimited: true, mode: "pro", count: 1, highPriority: false });
    assert.deepEqual(unlimitedPatch(false), { unlimited: false });
    const p = buildPayload(draft({ mode: "ultra", count: 4, highPriority: true,
      ...unlimitedPatch(true) }));
    assert.equal(p.mode, "pro");
    assert.equal(p.count, 1);
    assert.equal(p.high_priority, false);
    assert.equal(UNLIMITED_PRO, "Unlimited Mode runs on Pro");
  });
});

describe("C3 / §8.5 -- the disable reasons", () => {
  test("a reference picture refuses switching on", () => {
    assert.equal(unlimitedBlock(draft({ ref: { media_id: "M1" } })),
      "Remove the reference picture to use Unlimited Mode");
  });
  test("a size over the lane's limit refuses it, judged on the SNAPPED size", () => {
    assert.equal(unlimitedBlock(draft()), null, "1024 x 1024 fits");
    assert.equal(unlimitedBlock(draft({ size: 2048 })),
      "Pick a smaller size to use Unlimited Mode — up to 1792 × 1792");
    // 1800 x 1800 is the area's side, but it snaps to 1808 x 1808 on the 16 px grid
    assert.match(unlimitedBlock(draft({ customW: "1800", customH: "1800" })) || "",
      /up to 1792 × 1792/);
    assert.equal(unlimitedBlock(draft({ customW: "1792", customH: "1792" })), null);
    assert.equal(unlimitedBlock(draft({ size: 2048, aspect: at("16:9") })), null,
      "2048 x 1152 fits the area");
  });
  test("laneSizeOk: the area and inside a range; no limit known fails open", () => {
    const size = T3.unlimited.size;
    assert.equal(laneSizeOk(1792, 1792, size), true);
    assert.equal(laneSizeOk(1808, 1808, size), false);
    assert.equal(laneSizeOk(2496, 512, size), true);
    assert.equal(laneSizeOk(2512, 512, size), false, "outside every range");
    assert.equal(laneSizeOk(4096, 4096, null), true);
  });
  test("while on, Generate is refused with the same sentence; off it is not", () => {
    const ref = { ref: { media_id: "M1" } };
    assert.equal(goGate(draft({ ...ref, unlimited: true })),
      "Remove the reference picture to use Unlimited Mode");
    assert.equal(goGate(draft(ref)), null);
    assert.equal(goGate(draft({ unlimited: true })), null);
  });
  test("the size stops and aspect glyphs lock only what the lane would refuse", () => {
    const on = draft({ unlimited: true, size: 2048 });
    assert.equal(laneRefusesFrame(on, { aspect: at("1:1") }), true);
    assert.equal(laneRefusesFrame(on, { aspect: at("16:9") }), false);
    assert.equal(laneRefusesFrame(draft({ unlimited: true }), { size: 2048 }), true);
    assert.equal(laneRefusesFrame(draft({ unlimited: true }), { size: 1536 }), false);
    assert.equal(laneRefusesFrame(draft({ size: 2048 }), { size: 2048 }), false, "off: nothing");
    // custom W x H is cleared by a stop or glyph pick, so the judgement ignores it
    assert.equal(laneRefusesFrame(draft({ unlimited: true, customW: "2048", customH: "2048" }),
      { size: 1024 }), false);
  });
});

describe("C2 / C3b -- the row's words and one lane task at a time", () => {
  test("days left, PixAI's own count", () => {
    assert.equal(unlimitedDaysText(T3), "29 days left");
    assert.equal(unlimitedDaysText({ unlimited: { days_left: 1 } }), "1 day left");
    assert.equal(unlimitedDaysText({ unlimited: { days_left: 0 } }), "");
    assert.match(unlimitedRules(T3), /Pro mode/);
    assert.match(unlimitedRules(T3), /1792 × 1792/);
  });
  test("a waiting or running lane task on the run list holds Generate", () => {
    assert.equal(laneBusy([{ lane: "infinite", status: "running" }]), true);
    assert.equal(laneBusy([{ lane: "infinite", status: "stale" }]), true);
    assert.equal(laneBusy([{ lane: "infinite", status: "done" }]), false);
    assert.equal(laneBusy([{ status: "running" }]), false, "an ordinary run never holds it");
    assert.equal(laneBusy(null), false);
    assert.equal(UNLIMITED_BUSY, "An Unlimited Mode picture is still being made");
    const dock = read("../../gallery/src/components/GenerateDrawer.jsx");
    assert.match(dock, /s\.unlimited && laneBusy\(jobs\) \? UNLIMITED_BUSY/);
  });
});

describe("C5 / §8.7 -- the badge and the finished line know the lane", () => {
  const badge = read("../../gallery/src/components/CostBadge.jsx");
  test("keyed on the server's `unlimited`, and only on a free answer", () => {
    assert.match(badge, /const lane = state === "free" && d\.unlimited === true;/);
    assert.match(badge, /if \(lane\) \{\s*main = "Free";/);
  });
  test("the ∞ rides every form: bar, stack and chip", () => {
    const marks = badge.match(/m\.lane \? <span className="mgc-inf">∞<\/span> : null/g) || [];
    assert.equal(marks.length, 3, "one mark per form");
    assert.match(badge, /<span className="mgc-val">\{m\.val\}\{m\.lane \?/, "the chip's value");
    assert.match(badge, /data-lane=\{m\.lane \? "unlimited" : undefined\}/);
  });
  test("the onCost detail and the text say so too", () => {
    assert.match(badge, /unlimited: !!m\.lane,/);
    assert.match(badge, /const text = main \+ \(lane \? " ∞" : ""\)/);
  });
  test("the finished line reads free (Unlimited Mode), never free (card used)", () => {
    const submit = read("../../gallery/src/gen/submitTask.js");
    assert.match(submit,
      /paid === 0 \? \(payload\.unlimited \? "free \(Unlimited Mode\)" : "free \(card used\)"\)/);
  });
  test("the ∞ is the fixed green token (not the skin-tinted emerald), never a raw colour", () => {
    const css = read("../../gallery/src/styles/cost-badge.css");
    assert.match(css, /\.cost-badge \.mgc-inf \{[^}]*color: var\(--green\);/);
  });
});

describe("C2 / C4 -- both surfaces mount the row and the strip", () => {
  test("desktop dock and phone Create", () => {
    const dock = read("../../gallery/src/components/GenerateDrawer.jsx");
    const phone = read("../../gallery/src/components/CreateMobile.jsx");
    for (const [name, src, flag] of [["dock", dock, ""], ["phone", phone, " phone"]]) {
      assert.ok(src.includes("<UnlimitedRow s={s} set={set}" + flag + " />"), name + " row");
      assert.ok(src.includes("UnlimitedStrip s={s} set={set}" + flag + " />"), name + " strip");
    }
  });
  test("the lane's styles are tokens only", () => {
    const css = read("../../gallery/src/styles/unlimited.css").replace(/\/\*[\s\S]*?\*\//g, "");
    assert.doesNotMatch(css, /#[0-9a-f]{3,8}\b/i, "a raw hex colour");
    assert.doesNotMatch(css, /rgba?\(/i, "a raw rgb colour");
    assert.match(css, /var\(--green\)/);
    assert.doesNotMatch(css, /var\(--emerald\)/, "the lane is green in every skin, never the skin's emerald");
  });
});
