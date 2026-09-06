import { test, describe, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { setMaxListeners } from "node:events";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE COMMUNITY READ-ONLY SURFACE (scoped 2026-09-04, built 2026-09-06).

   Two halves, tested two ways -- the same split loom/test/gallery-stands-still.test.js
   uses, and for the same reason: there is no React test renderer here.

     1. THE BLOW-UP NOTE is a pure module, so it is DRIVEN for real (fake localStorage, a
        real EventTarget for `window`), exactly as mg-update-announce.test.js drives the
        release announcement it is modelled on. Its two promises are worth holding:
        one note per SWEEP surviving a reload, and announce-only -- it can no more open a
        screen than updateStore can install a release. That second one is the owner's
        "the library stands still" policy (2026-09-05), which a note about engagement is
        exactly the kind of thing that erodes.

     2. THE FOUR SURFACES are structure guards over the source. What they pin is not
        cosmetic: each of these numbers was ALREADY being fetched and thrown away before
        this branch (followers/following on every /api/account call, comment counts on
        every My Art card, views on twelve of them), so a regression here looks like
        nothing failing -- it looks like the data quietly not reaching a pixel again. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Line endings normalized on read, as everywhere in this suite: the repo stores LF
// (.gitattributes `* text=auto`) while Windows checks out CRLF.
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src", p), "utf8")
  .replace(/\r\n/g, "\n");

// ---------------------------------------------------------------------------
// 1. The blow-up note, driven
// ---------------------------------------------------------------------------

const bag = new Map();
let blocked = false;
globalThis.localStorage = {
  getItem: (k) => {
    if (blocked) throw new Error("SecurityError: storage is blocked");
    return bag.has(k) ? bag.get(k) : null;
  },
  setItem: (k, v) => {
    if (blocked) throw new Error("SecurityError: storage is blocked");
    bag.set(k, String(v));
  },
  removeItem: (k) => bag.delete(k),
};
globalThis.window = globalThis.window || new EventTarget();
setMaxListeners(64, globalThis.window);

const storeURL = new URL("../../gallery/src/notify/spikeStore.js", import.meta.url).href;
let tab = 0;
const newTab = () => import(storeURL + "?tab=" + (++tab));   // a fresh instance IS a fresh tab
const toasts = await import("../../gallery/src/notify/toastStore.js");

let note, spikeMessage;
let mark = 0;
const since = () => toasts.getToasts().slice(mark);

/* One spiking work, shaped exactly like published_spikes()' rows. */
const hit = (o) => ({
  media_id: "m1", artwork_id: "aw1", title: "Moonwell", views: 1401, gained: 400,
  window_hours: 24, rate_per_hour: 16.67, baseline_per_hour: 0.67, multiple: 24.9,
  ...(o || {}),
});
const sweep = (at, spikes) => ({ views_at: at, spikes });

describe("the blow-up note", () => {
  beforeEach(async () => {
    bag.clear();
    blocked = false;
    ({ note, spikeMessage } = await newTab());
    mark = toasts.getToasts().length;
  });

  test("a sweep that found a spike announces once, naming the work", () => {
    assert.equal(note(sweep("2026-09-06T00:00:00Z", [hit()])), true);
    const shown = since();
    assert.equal(shown.length, 1);
    assert.match(shown[0].title, /Moonwell/);
    assert.match(shown[0].msg, /\+400 views/);
    assert.match(shown[0].msg, /24\.9×/);
    // Sticky, for updateStore's own reason: a sweep can finish with nobody at the keyboard.
    assert.equal(shown[0].sticky, true);
  });

  test("the SAME sweep read again is not news", () => {
    note(sweep("2026-09-06T00:00:00Z", [hit()]));
    for (let i = 0; i < 5; i++) note(sweep("2026-09-06T00:00:00Z", [hit()]));
    assert.equal(since().length, 1);
  });

  test("a LATER sweep is news again", () => {
    note(sweep("2026-09-06T00:00:00Z", [hit()]));
    assert.equal(note(sweep("2026-09-07T00:00:00Z", [hit({ title: "Emerald Dream" })])), true);
    assert.equal(since().length, 2);
    assert.match(since()[1].title, /Emerald Dream/);
  });

  test("a library with no spikes says nothing at all", () => {
    assert.equal(note(sweep("2026-09-06T00:00:00Z", [])), false);
    assert.equal(since().length, 0);
  });

  test("a library that was never swept says nothing", () => {
    // THE NO-ANNOUNCE BASELINE, from this side of the wire. The server-side rule already
    // returns no spikes for a first sweep (nothing to compare against); this is the
    // client refusing to invent one from a payload with no sweep stamp.
    assert.equal(note({ views_at: "", spikes: [hit()] }), false);
    assert.equal(note({}), false);
    assert.equal(since().length, 0);
  });

  test("a reload cannot re-announce the same sweep", async () => {
    note(sweep("2026-09-06T00:00:00Z", [hit()]));
    assert.equal(since().length, 1);
    ({ note } = await newTab());                 // a reload: fresh memory, same storage
    assert.equal(note(sweep("2026-09-06T00:00:00Z", [hit()])), false);
    assert.equal(since().length, 1);
  });

  test("storage blocked: at most one note per tab, never a repeat every read", async () => {
    // updateStore's own hard-won lesson. A guarded read that swallows the throw answers
    // "" -- which reads as "never announced" -- so the memory mark has to be the layer
    // that actually holds the promise.
    ({ note } = await newTab());
    blocked = true;
    assert.equal(note(sweep("2026-09-06T00:00:00Z", [hit()])), true);
    for (let i = 0; i < 5; i++) note(sweep("2026-09-06T00:00:00Z", [hit()]));
    assert.equal(since().length, 1);
  });

  test("a sibling tab's announcement stops this one repeating it", async () => {
    ({ note } = await newTab());
    const ev = new Event("storage");
    ev.key = "mg_spike_announced";
    ev.newValue = "2026-09-06T00:00:00Z";
    globalThis.window.dispatchEvent(ev);
    assert.equal(note(sweep("2026-09-06T00:00:00Z", [hit()])), false);
    assert.equal(since().length, 0);
  });

  test("the sentence names ONE work and counts the rest -- it is not a feed", () => {
    const one = spikeMessage([hit()]);
    assert.doesNotMatch(one.msg, /more picking up/);
    const many = spikeMessage([hit(), hit({ title: "B" }), hit({ title: "C" })]);
    assert.match(many.title, /Moonwell/);
    assert.doesNotMatch(many.msg, /\bB\b|\bC\b/);        // the others are counted, not listed
    assert.match(many.msg, /2 more picking up/);
    assert.equal(spikeMessage([]), null);
  });

  test("an untitled work still gets a sentence, never an empty name", () => {
    assert.match(spikeMessage([hit({ title: "" })]).title, /One of your works/);
  });
});

describe("the note ANNOUNCES and does nothing else", () => {
  const store = src("notify/spikeStore.js");

  test("it never navigates, opens an overlay, or moves the library", () => {
    // THE LIBRARY STANDS STILL (owner, 2026-09-05): nothing moves the owner's view except
    // his own hands. An engagement notice is precisely the feature that grows a "jump to
    // it" reflex, so the route into one is walked here rather than trusted.
    //
    // Matched against CODE, with comments stripped first -- an earlier form of this test
    // failed on the word "reload" inside a sentence explaining what localStorage survives,
    // which is prose about the mechanism, not a call into it.
    const code = store.replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/[^\n]*/g, "");
    for (const forbidden of ["window.location", "location.href", "location.assign",
      "location.reload", "pushState", "replaceState", "scrollTo", "scrollIntoView",
      "onOverlay", "setOverlay", "openPost", "dispatchEvent"]) {
      assert.ok(!code.includes(forbidden),
        "spikeStore must not reach for " + forbidden + " -- it announces, it does not move");
    }
  });

  test("its only outward calls are the toast and one local read", () => {
    assert.match(store, /import \{ show as toastShow \} from "\.\/toastStore\.js"/);
    // One GET, and it is the panel's own route -- which is a local catalog read now, not
    // a PixAI call. Nothing here POSTs: this whole surface is read-only by scope.
    assert.equal((store.match(/apiGet\(/g) || []).length, 1);
    assert.ok(!store.includes("apiPost"));
  });

  test("it fires once per boot, from the same place the update receipt does", () => {
    const index = src("notify/index.jsx");
    assert.match(index, /import \{ checkSpikes \} from "\.\/spikeStore\.js"/);
    assert.match(index, /checkSpikes\(\);/);
  });
});

// ---------------------------------------------------------------------------
// 2. The four surfaces
// ---------------------------------------------------------------------------

describe("followers and following reach BOTH surfaces the owner asked for", () => {
  const bar = src("components/SeparatorBar.jsx");
  const acct = src("components/AccountSubOverlay.jsx");

  test("the chip beside the credits chip renders both numbers", () => {
    assert.match(bar, /account\.followers/);
    assert.match(bar, /account\.following/);
    assert.match(bar, /FOLLOWERS/);
    assert.match(bar, /FOLLOWING/);
  });

  test("it borrows the credits chip's own classes rather than inventing a chip", () => {
    assert.match(bar, /"mgx-cred mgx-social"/);
    assert.match(bar, /mgx-credval/);
    assert.match(bar, /mgx-creddiv/);
  });

  test("it is a reading, not a control -- a span, never a button", () => {
    // Following somebody is a WRITE to PixAI, which the scope's out-of-scope list rules
    // out. A control that cannot do anything is worse than no control.
    const chip = bar.slice(bar.indexOf("mgx-cred mgx-social"));
    const close = chip.slice(0, chip.indexOf("</span>"));
    assert.ok(!close.includes("onClick"), "the social chip must not be clickable");
    assert.ok(!close.includes("<button"), "the social chip must not be a button");
  });

  test("null is shown as nothing, never as a confident zero", () => {
    // "Nobody follows you" and "we could not ask PixAI" are different sentences.
    assert.match(bar, /account\.followers != null && account\.following != null/);
    assert.match(acct, /acct\.followers == null \? "—"/);
    assert.match(acct, /acct\.following == null \? "—"/);
  });

  test("the account popup puts them in the balance strip it already had", () => {
    const strip = acct.slice(acct.indexOf("acct-balance"), acct.indexOf("acct-tabs"));
    assert.match(strip, /acct-kick">followers</);
    assert.match(strip, /acct-kick">following</);
    assert.match(strip, /acct-midnum/);      // the strip's own idiom, no new class
  });
});

describe("My Art draws the numbers it was already fetching", () => {
  const desktop = src("components/MyArtOverlay.jsx");
  const mobile = src("components/MyArtMobile.jsx");
  const css = readFileSync(
    path.resolve(__dirname, "../../gallery/src/styles/myart-contests.css"), "utf8");

  for (const [name, shell] of [["desktop", desktop], ["mobile", mobile]]) {
    test(name + ": the comment badge sits beside the likes badge", () => {
      // It was fetched for every card and summed into the COMMENTS stat, and never once
      // reached a card (MyArtOverlay drew likes only). Same glyph the app uses for a
      // comment count everywhere else.
      assert.match(shell, /💬 \{fmt\(it\.comments\)\}/);
      assert.match(shell, /commentCol\(it\.comments\)/);
    });

    test(name + ": every published card gets its view count and bar, not a top twelve", () => {
      assert.match(shell, /it\.public && it\.views != null/);
      assert.match(shell, /\{fmt\(it\.views\)\} views/);
      assert.match(shell, /className="mgma-barwrap"/);
      assert.match(shell, /className="mgma-bar"/);
      assert.match(shell, /gridMaxViews/);
      // The bar's own rule, from the design it comes from: this work's share of the best
      // one on screen, floored at 2% so a real number is never an invisible sliver.
      assert.match(shell, /Math\.max\(2, \(it\.views \/ gridMaxViews\) \* 100\)/);
    });

    test(name + ": a never-swept work is not painted as a zero", () => {
      // null means --sync-artworks has not read this yet. Drawing it as 0 with an empty
      // bar would be the app asserting something it does not know.
      assert.match(shell, /views == null \? -1/);
    });

    test(name + ": the library can be sorted by views", () => {
      assert.match(shell, /\["viewed", "Most viewed"\]/);
      assert.match(shell, /sort === "viewed"/);
    });
  }

  test("the bar is the DESIGNED bar, restored -- not a second one drawn to a new spec", () => {
    // .mgma-barwrap/.mgma-bar are the Frontend Gallery DC's own ranked-list bar (shipped
    // in cecdd91f). Stage 2A replaced that list with the card grid and left the CSS
    // orphaned; this is the same 4px track and accent fill, re-homed onto the card.
    assert.match(css, /\.mgma-barwrap \{ height: 4px;/);
    assert.match(css, /\.mgma-bar \{ height: 100%;.*background: var\(--accent\)/);
    // The only NEW rule is the layout row that holds it.
    assert.match(css, /\.mgma2-fviews \{ display: flex;/);
  });

  test("the stat row reports a lifetime total, and says so when it is partial", () => {
    const hook = src("hooks/useMyArt.js");
    assert.match(hook, /TOTAL VIEWS/);
    assert.ok(!hook.includes("views_top"), "views_top was the twelve-row subtotal; it is gone");
    // A partly-swept library must not pass a subtotal off as a total -- the same job the
    // old "(TOP 12)" label was doing, kept.
    assert.match(hook, /VIEWS \(" \+ swept \+ " OF "/);
    assert.match(mobile, /"VIEWS \(" \+ \(t\.views_rows \|\| 0\)/);
  });

  test("nothing on this surface fetches views live any more", () => {
    // The lag saga: twelve GraphQL calls fired on every open of this panel. Both shells
    // read /api/your-art, which is a catalog read now.
    assert.ok(!desktop.includes("/api/artwork-views"));
    assert.ok(!mobile.includes("/api/artwork-views"));
  });
});
