import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE UPDATE, ON THE PHONE (owner ruling 2026-09-07: "phone gets update").

   Nothing about updates showed on the Control tab before that day -- the apply flow was the
   desktop Panel's modal and only that, so a person holding the phone could be told a release
   was out and have nowhere to go with it. /api/update/apply was already @tier(LOGIN), so
   what shipped is a surface, not a policy change.

   A SOURCE GUARD, deliberately, and here is the honest limit of it: these two components
   need a DOM and a mounted React tree, which this repo's node test runner has no renderer
   for (tests/test_render_harness.py owns the real-browser half and does not drive the update
   modal). What a source guard CAN pin is the wiring that would silently rot -- that the
   phone reaches the shared card and the shared hook rather than growing a second apply path
   of its own, which is the one mistake with real consequences here. The three properties:

     1. THE TILE AND THE SCREEN EXIST, and the screen is the drill-in chrome the rest of this
        tab already uses (MobileScreen + useLayerHistory), not a third ad-hoc convention.
     2. ONE CARD, NOT TWO. UpdatePhases.jsx is imported by BOTH the desktop modal and the
        phone screen, so the phases, the meter and the refusal cannot drift apart.
     3. ONE APPLY PATH. The phone asks useControlPanel()'s applyUpdate, exactly as the
        desktop modal does; it never names the apply route itself. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(__dirname, "../../gallery/src");
const read = (p) => readFileSync(path.join(SRC, p), "utf8").replace(/\r\n/g, "\n");

describe("the phone's Control tab can apply an update", () => {
  const mobile = read("components/ControlMobile.jsx");

  test("it offers the update tile and drills into an update screen", () => {
    assert.ok(mobile.includes("Update available"), "the tile the banner's release earns");
    assert.ok(/setUpdScreen\(true\)/.test(mobile), "and the tile opens the screen");
    assert.ok(/<MobileScreen[^>]*open=\{updScreen\}/s.test(mobile),
      "the screen is MobileScreen's push chrome, the same one Branding drills into");
    assert.ok(mobile.includes("useLayerHistory(updScreen"),
      "so the phone's own Back closes it instead of leaving the app");
    assert.ok(mobile.includes("Update now"), "and the screen carries the confirm");
  });

  test("it applies through the shared hook, and never posts the apply itself", () => {
    assert.ok(/applyUpdate[,\s}]/.test(mobile), "applyUpdate comes off useControlPanel()");
    assert.ok(mobile.includes("onClick={applyUpdate}"), "and one button calls it");
    assert.ok(!mobile.includes("/api/update/apply"),
      "the phone must not name the apply route: the hook owns the POST, its confirm and its CSRF token");
    assert.ok(!/\bapiPost\b/.test(mobile), "nor POST anything of its own");
  });

  test("the reload and the receipt are the ones already shipped -- no second path", () => {
    assert.ok(!mobile.includes("location.reload"),
      "the hook reloads after a successful apply; a second reload here would be a second path");
    assert.ok(!mobile.includes("armReceipt") && !mobile.includes("claimReceipt"),
      "the receipt is armed by the hook and claimed once per boot by notify/index.jsx");
    const installer = read("notify/index.jsx");
    assert.ok(installer.includes("claimReceipt("),
      "and that boot path runs on the phone too, because NotifyRoot mounts on both shells");
  });

  test("the running card is ONE card, drawn by both surfaces", () => {
    const shared = "./UpdatePhases.jsx";
    assert.ok(mobile.includes(shared), "the phone screen draws the shared phases card");
    assert.ok(read("components/ControlPanelOverlay.jsx").includes(shared),
      "and so does the desktop modal -- same markup, same classes, no second drawing");
    const phases = read("components/UpdatePhases.jsx");
    assert.ok(phases.includes("mgcp-updphases") && phases.includes("mgcp-updmeter"),
      "with the Identity Chrome C2 classes it was lifted out with");
    assert.ok(!phases.includes("/api/update/apply") && !/\bapiPost\b/.test(phases),
      "the card draws an apply; it can never start one");
  });
});

describe("the banner reaches both surfaces", () => {
  test("the notify root mounts the strip beside the toasts", () => {
    const installer = read("notify/index.jsx");
    assert.ok(installer.includes("<BannerHost />") && installer.includes("<ToastHost />"),
      "one root, both body-level surfaces, so every shell gets them");
  });

  test("each shell answers the strip's Update button in its own terms", () => {
    assert.ok(read("App.jsx").includes('registerUpdateHost(() => setOverlay("panel"))'),
      "desktop: open the Control Panel");
    assert.ok(read("components/AppMobile.jsx").includes('registerUpdateHost(() => setTab("control"))'),
      "phone: go to the Control tab");
    for (const file of ["components/ControlPanelOverlay.jsx", "components/ControlMobile.jsx"]) {
      assert.ok(read(file).includes("takeOpenIntent()"),
        `${file} must pick the intent up on mount, since it is not mounted when the button is pressed`);
      assert.ok(read(file).includes("subscribeOpenIntent("),
        `${file} must also answer it when it is ALREADY mounted`);
    }
  });
});
