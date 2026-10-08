import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

import { CHOICE_DEFAULT, choiceCopy, pokeView, choiceValue } from "../../gallery/src/folio/pokeCore.js";
import { prefKeyProblem } from "../../gallery/src/hooks/accountPrefsStore.js";
import { UNLEASH_KEY } from "../../gallery/src/folio/unleashPref.js";

/* The narrator's poke, the page's half. The ladder itself is the SERVER's (tests/
   test_narrator_ladder.py, dev/tests/test_narrator_route.py); what this file pins is that the page
   holds none of it: it shows the line it is told, it cannot tell a counted poke from an
   uncounted one, and the choice at the end writes the account's switch. Every line here is
   invented -- nothing names a real one. */

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(here, "..", "..", "gallery", "src");
const src = (rel) => readFileSync(path.join(SRC, rel), "utf8").replace(/\r\n/g, "\n");
const codeOnly = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");

describe("what the page does with the route's answer", () => {
  test("a line is shown, whether or not it counted (the page cannot tell)", () => {
    const v = pokeView({ ok: true, line: "test line one" });
    assert.deepEqual(v, { show: true, line: "test line one", final: false });
    assert.deepEqual(Object.keys(v).sort(), ["final", "line", "show"],
      "nothing about the count, the stage or the clocks is in what the page derives");
  });

  test("an error, a bare object, junk and an empty line are all a quiet no-op", () => {
    for (const bad of [null, undefined, 5, "x", [], {}, { ok: true }, { ok: true, line: "" },
      { error: "stale page" }, { ok: true, line: 7 }, { error: "x", line: "test line" }]) {
      assert.equal(pokeView(bad).show, false, JSON.stringify(bad));
    }
  });

  test("the last poke carries the feat's id, its two lines and the choice's words", () => {
    const v = pokeView({
      ok: true, line: "test clean",
      final: { id: "test-feat", clean: "test clean", unleashed: "test unleashed",
        choice: { title: "test title", keep: "test keep" } },
    });
    assert.equal(v.final, true);
    assert.equal(v.card, "test-feat");
    assert.equal(v.clean, "test clean");
    assert.equal(v.unleashed, "test unleashed");
    assert.equal(v.choice.title, "test title");
    assert.equal(v.choice.keep, "test keep");
    assert.equal(v.choice.unleash, CHOICE_DEFAULT.unleash, "a word the pack did not send falls back");
  });

  test("a final with no feat behind it is just a line", () => {
    for (const final of [{}, { id: "" }, { id: 5 }, null, "x"]) {
      const v = pokeView({ ok: true, line: "test line", final });
      assert.deepEqual(v, { show: true, line: "test line", final: false });
    }
  });

  test("the choice's words are the pack's where it sent a real string, else plain defaults", () => {
    assert.deepEqual(choiceCopy(undefined), CHOICE_DEFAULT);
    assert.deepEqual(choiceCopy({ title: "  ", keep: 5, foot: "test foot" }),
      { ...CHOICE_DEFAULT, foot: "test foot" });
    assert.equal(choiceCopy({ unleash: " test go " }).unleash, "test go");
  });

  test("the default frame names no narrator line and is the app's own vocabulary", () => {
    assert.match(CHOICE_DEFAULT.keep, /filter/i);
    assert.match(CHOICE_DEFAULT.foot, /Folio/);
    for (const v of Object.values(CHOICE_DEFAULT)) assert.ok(v.length < 80);
  });

  test("Unleash turns the switch on and Keep is an explicit off", () => {
    assert.equal(choiceValue("unleash"), true);
    assert.equal(choiceValue("keep"), false);
    assert.equal(choiceValue(undefined), false);
    assert.equal(prefKeyProblem(UNLEASH_KEY), "");
  });
});

describe("the page holds none of the ladder", () => {
  const hook = codeOnly(src("hooks/useFolio.js"));
  const core = codeOnly(src("folio/pokeCore.js"));

  test("the poke goes to the server's route with the session token, one at a time", () => {
    assert.match(hook, /apiPost\("\/api\/narrator\/poke",\s*\{\s*csrf:\s*accountCsrf\(\)\s*\}\)/);
    assert.match(hook, /if \(pokingRef\.current\) return;/,
      "a click that fires twice must be one request, not a poke and a spam line");
    assert.doesNotMatch(hook, /sendAchEvent/, "the narrator is no longer a beacon event");
  });

  test("no line of the narrator's, no count, no clock in the page's poke code", () => {
    const body = hook.slice(hook.indexOf("function pokeNarrator()"), hook.indexOf("function close()"));
    assert.ok(body.length > 200, "could not find the poke code");
    for (const code of [body, core]) {
      assert.doesNotMatch(code, /\bPOKES\b/, "the public five-line list is gone");
      assert.doesNotMatch(code, /localStorage|sessionStorage|Date\.now|performance\.now|setTimeout/,
        "no clock and no memory of its own: the server keeps both");
      assert.doesNotMatch(code, /\.pokes\b|\.snapped\b|\.count\b|counted/,
        "the page is told a line, not a count");
    }
  });

  test("the last poke marks the feat seen, plays its celebration and asks the choice", () => {
    assert.match(hook, /apiGet\("\/api\/achievements\?mark=1"\)/,
      "marking it seen is what stops the ordinary earn toast following the celebration");
    assert.match(hook, /if \(card\) replayToast\(card\);\s*offerChoice\(v\.choice\);/);
    assert.match(hook, /actions: \[\s*\{ label: copy\.keep, run: \(\) => chooseUnleash\("keep"\) \},\s*\{ label: copy\.unleash, tone: "ruby", run: \(\) => chooseUnleash\("unleash"\) \},/);
  });

  test("Unleash re-runs the celebration already up through the existing glitch reveal", () => {
    const fn = hook.slice(hook.indexOf("function chooseUnleash("), hook.indexOf("function offerChoice("));
    assert.match(fn, /prefs\.set\(UNLEASH_KEY, on\)/);
    assert.match(fn, /rerunToast\(activeToastRef\.current, true\)/,
      "the same scramble toggleUnleash plays: one reveal, not a second implementation");
  });
});

describe("the choice toast", () => {
  const store = src("notify/toastStore.js");
  const host = src("notify/ToastHost.jsx");

  test("the toast store takes up to two actions and a foot, and leaves `action` alone", () => {
    assert.match(store, /actions: !o\.action && Array\.isArray\(o\.actions\)/);
    assert.match(store, /\.slice\(0, 2\)/);
    assert.match(store, /foot: o\.foot \? String\(o\.foot\) : ""/);
    assert.match(store, /action: o\.action && typeof o\.action\.run === "function"/);
  });

  test("every button dismisses the toast and then runs its own action", () => {
    assert.match(host, /onClick=\{\(\) => \{ dismiss\(t\.id\); try \{ a\.run\(\); \}/);
    assert.match(host, /className=\{"mt-act" \+ \(a\.tone \? " " \+ a\.tone : ""\)\}/);
  });

  test("the ruby button and the foot are drawn from the app's own tokens", () => {
    const css = src("styles/notify.css");
    assert.match(css, /\.mg-toast \.mt-act\.ruby\{border-color:var\(--red\);color:var\(--red\);\}/);
    assert.match(css, /\.mg-toast \.mt-foot\{[^}]*var\(--overlay0\)/);
  });
});
