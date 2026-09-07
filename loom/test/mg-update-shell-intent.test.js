import { test, describe, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE UPDATE BUTTON, PER SHELL (2026-09-07, later the same day the strip shipped).

   Two things were wrong with one press:

     1. THE WIZARD'S BUTTON WAS DEAD. The setup wizard mounts NotifyRoot, so it gets the
        strip, but it registers no update host and it IS "/" -- so requestUpdateOpen() fell
        through both branches and the button pressed nothing at all, with no feedback. The
        strip now asks the store what this shell can do and draws a reason in the button's
        place when the answer is "nothing".
     2. THE LOOM'S PRESS WAS LOST IN THE CROSSING. `pendingOpen` is memory and
        window.location.assign("/") is a full document load, so the gallery came back with
        the intent gone and the Control Panel shut. The intent is now written down for the
        crossing (sessionStorage, or a ?update=1 the boot strips when storage is blocked) and
        read back by whichever shell registers a host on the other side.

   Driven for real. bannerStore is a pure module, so a fake window is the whole stand-in, and
   a fresh import under a new query string is exactly what a document load is. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(__dirname, "../../gallery/src");
const bannerURL = new URL("../../gallery/src/notify/bannerStore.js", import.meta.url).href;
const read = (p) => readFileSync(path.join(SRC, p), "utf8").replace(/\r\n/g, "\n");

let assigned = [];
let replaced = [];
let sessionBag = new Map();
let sessionBlocked = false;

/* A window that behaves the way a browser's does for the handful of calls this module makes.
   `sessionBlocked` throws on the PROPERTY access, which is what a storage-blocked profile
   really does -- not "returns null". */
function boot(pathname, search) {
  assigned = [];
  replaced = [];
  const location = {
    pathname,
    search: search || "",
    hash: "",
    assign: (url) => assigned.push(url),
  };
  const store = {
    getItem: (k) => (sessionBag.has(k) ? sessionBag.get(k) : null),
    setItem: (k, v) => sessionBag.set(k, String(v)),
    removeItem: (k) => sessionBag.delete(k),
  };
  const win = {
    location,
    history: {
      replaceState: (a, b, url) => {
        replaced.push(url);
        const q = String(url).indexOf("?");
        location.search = q < 0 ? "" : String(url).slice(q);
      },
    },
  };
  Object.defineProperty(win, "sessionStorage", {
    get() {
      if (sessionBlocked) throw new Error("SecurityError: storage is blocked");
      return store;
    },
  });
  globalThis.window = win;
  return win;
}

let bootN = 0;
// A NEW module instance against the SAME fake storage: that is a page load, exactly.
const load = () => import(bannerURL + "?boot=" + ++bootN);

describe("what the strip may offer, shell by shell", () => {
  beforeEach(() => { sessionBag = new Map(); sessionBlocked = false; });

  test("the setup wizard gets the news and a reason, not a button that presses nothing", async () => {
    boot("/");                       // the wizard is served at the gallery's own front door
    const { updateAffordance, hasUpdateHost } = await load();
    assert.equal(hasUpdateHost(), false, "SetupWizard registers no update host");
    assert.deepEqual(updateAffordance(), { canOpen: false, why: "finish setup first" });
  });

  test("the Loom keeps its button, and says where the press goes", async () => {
    boot("/loom");
    const { updateAffordance } = await load();
    assert.deepEqual(updateAffordance(),
      { canOpen: true, why: "open the gallery to update" });
  });

  test("a shell that registered a host just gets the button", async () => {
    boot("/");
    const { updateAffordance, registerUpdateHost } = await load();
    const stop = registerUpdateHost(() => {});
    assert.deepEqual(updateAffordance(), { canOpen: true, why: "" });
    stop();
    assert.deepEqual(updateAffordance(), { canOpen: false, why: "finish setup first" },
      "and it goes back to the reason when that shell unmounts");
  });

  test("the strip watches for the host rather than deciding once", async () => {
    boot("/");
    const { subscribeUpdateHost, registerUpdateHost } = await load();
    const seen = [];
    const stop = subscribeUpdateHost((has) => seen.push(has));
    const drop = registerUpdateHost(() => {});
    drop();
    stop();
    assert.deepEqual(seen, [false, true, false],
      "the shells register in their own mount effect, which can land after the strip's");
  });

  /* The markup half. These two components need a DOM and a mounted React tree, which this
     repo's node runner has no renderer for -- so the DECISION is driven above for real and
     the drawing is pinned here, which is the piece that would rot silently. */
  test("the strip draws the reason in the button's place", () => {
    const host = read("notify/BannerHost.jsx");
    assert.ok(host.includes("updateAffordance()"),
      "the strip asks the store what this shell can do");
    assert.ok(/\{canOpen \?[\s\S]{0,200}className="mgub-go"/.test(host),
      "the Update button is drawn only when the press can reach a confirm surface");
    assert.ok(/\{why \?[\s\S]{0,120}className="mgub-why"/.test(host),
      "and the reason is drawn when there is one");
    assert.ok(host.includes("subscribeUpdateHost("),
      "and it re-reads that when a shell registers after the strip mounted");
    const css = readFileSync(path.join(SRC, "styles/notify.css"), "utf8");
    assert.ok(css.includes(".mgub-why{"), "the reason has a face in notify.css");
  });
});

describe("the press survives the crossing from the Loom", () => {
  beforeEach(() => { sessionBag = new Map(); sessionBlocked = false; });

  test("one press on the Loom lands on the gallery with the update surface opening", async () => {
    boot("/loom");
    const loom = await load();
    loom.requestUpdateOpen();
    assert.deepEqual(assigned, ["/"], "the Loom has no Control Panel, so the press crosses");
    assert.equal(sessionBag.size, 1, "and the intent is written down for the crossing");

    // ---- the document load: a new module instance, the same tab's storage ----
    boot("/");
    const gallery = await load();
    assert.equal(gallery.takeOpenIntent(), false, "memory really is gone across the load");
    const opened = [];
    gallery.registerUpdateHost(() => opened.push("panel"));
    assert.deepEqual(opened, ["panel"],
      "the shell that owns the Control Panel is asked to open it, once, on this boot");
    assert.equal(gallery.takeOpenIntent(), true,
      "and the surface it mounts reads the intent it was opened for");
    assert.equal(sessionBag.size, 0, "the note is consumed, not left for the next boot");
  });

  test("an ordinary boot opens nothing", async () => {
    boot("/");
    const gallery = await load();
    const opened = [];
    gallery.registerUpdateHost(() => opened.push("panel"));
    assert.deepEqual(opened, [], "no press, no panel");
    assert.equal(gallery.takeOpenIntent(), false);
  });

  test("with storage blocked the intent rides in the address bar, and is stripped on arrival", async () => {
    boot("/loom");
    sessionBlocked = true;
    const loom = await load();
    loom.requestUpdateOpen();
    assert.deepEqual(assigned, ["/?update=1"],
      "a storage-blocked browser must not silently lose the press");

    boot("/", "?update=1");
    sessionBlocked = true;
    const gallery = await load();
    const opened = [];
    gallery.registerUpdateHost(() => opened.push("panel"));
    assert.deepEqual(opened, ["panel"]);
    assert.equal(gallery.takeOpenIntent(), true);
    assert.deepEqual(replaced, ["/"],
      "and the query is taken out of the address bar, so a refresh does not re-open it");
  });

  test("the query is read once -- a second host on the same boot is not re-opened", async () => {
    boot("/", "?update=1");
    const gallery = await load();
    const opened = [];
    gallery.registerUpdateHost(() => opened.push("first"))();
    gallery.registerUpdateHost(() => opened.push("second"));
    assert.deepEqual(opened, ["first"]);
  });

  test("a press on a shell that owns the surface never touches storage or the address bar", async () => {
    boot("/");
    const gallery = await load();
    const opened = [];
    gallery.registerUpdateHost(() => opened.push("panel"));
    gallery.requestUpdateOpen();
    assert.deepEqual(opened, ["panel"]);
    assert.deepEqual(assigned, [], "no navigation: the surface is right here");
    assert.equal(sessionBag.size, 0, "and nothing is written down for a crossing that never happens");
  });

  test("the wizard's press cannot navigate to itself", async () => {
    boot("/");
    const wizard = await load();
    wizard.requestUpdateOpen();
    assert.deepEqual(assigned, [], "reloading the page that cannot help is not an answer");
    assert.equal(sessionBag.size, 0);
  });
});

describe("carrying the intent is still announce-only", () => {
  test("the store that writes the note can still not apply anything", () => {
    const src = read("notify/bannerStore.js");
    assert.ok(!src.includes("/api/update/apply"), "the banner store may not name the apply route");
    assert.ok(!/\bfetch\s*\(/.test(src), "nor call the network at all");
    assert.ok(src.includes("window.sessionStorage") && !/localStorage\s*[.[]/.test(src),
      "the crossing note is sessionStorage: this tab's navigation, not a per-browser memory");
  });
});
