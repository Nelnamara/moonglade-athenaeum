import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* EVERY MARK SIZES FROM ONE HERO NUMBER (marks ruling 2026-08-31, built 2026-09-07).

   The ruling is three words long -- "Hero 96, Slim 56, All scales from Hero" -- and the
   stylesheets did not keep it. Hero and slim were literals in shell.css, the animation
   engine re-typed both of them in mark-anims.css to derive its em base, and the three OTHER
   surfaces that render a mark carried three unrelated literals: login 88, login-mobile 66,
   gallery-mobile 50. Nothing tied any of them to the hero, so "all scales from hero" was a
   fact about one afternoon rather than a rule -- change the hero and four other marks stay
   where they were, silently out of proportion.

   So: two tokens, --mark-hero and --mark-slim, on shell.css's :root; every site derives.
   This file is the guard that nobody types a mark size again. It reads the ratios out of
   the stylesheets and checks each one still lands on the pixel it landed on before the
   refactor -- so the change is provably a no-op TODAY, and provably proportional tomorrow.

   The hero/slim numbers themselves are asserted in mark-anim-containment.test.js, which
   also reads them from the token; nothing here duplicates that. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Line endings normalized on read: the repo stores LF, Windows checks out CRLF.
const src = (p) => readFileSync(path.resolve(__dirname, "../../gallery/src/styles", p), "utf8")
  .replace(/\r\n/g, "\n");
const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, " ");

const shell = stripComments(src("shell.css"));
const anims = stripComments(src("mark-anims.css"));
const login = stripComments(src("login.css"));
const loginM = stripComments(src("login-mobile.css"));
const galleryM = stripComments(src("gallery-mobile.css"));

/** A `--mark-*` token's px value off shell.css's `:root`. */
function token(name) {
  const root = shell.match(/(?:^|\n):root\s*\{([^}]*)\}/);
  assert.ok(root, "shell.css no longer has a bare `:root` block");
  const v = root[1].match(new RegExp("--" + name + ":\\s*(\\d+(?:\\.\\d+)?)px"));
  assert.ok(v, "shell.css's :root no longer declares --" + name + " as a px length");
  return parseFloat(v[1]);
}

/** The body of the FIRST rule whose selector is exactly `sel`. */
function rule(css, sel, where) {
  const re = new RegExp("(?:^|[\\n{};])\\s*" + sel.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") +
                        "\\s*\\{([^}]*)\\}");
  const m = css.match(re);
  assert.ok(m, where + " no longer has a `" + sel + "` rule");
  return m[1].replace(/\s+/g, " ").trim();
}

/** `calc(var(--mark-hero) * <num> / <den>)` -> the px it resolves to. */
function ratioPx(body, prop, where) {
  const m = body.match(new RegExp(
    prop + ":\\s*calc\\(\\s*var\\(\\s*--mark-hero\\s*\\)\\s*\\*\\s*(\\d+(?:\\.\\d+)?)\\s*\\/\\s*(\\d+(?:\\.\\d+)?)\\s*\\)"));
  assert.ok(m, where + "'s `" + prop + "` is not calc(var(--mark-hero) * <ratio>) -- a mark " +
    "size typed as a literal is exactly what the token exists to stop");
  return token("mark-hero") * (parseFloat(m[1]) / parseFloat(m[2]));
}

describe("the hero and slim sizes live in one place", () => {
  test("shell.css declares both tokens", () => {
    assert.equal(token("mark-hero"), 96);
    assert.equal(token("mark-slim"), 56);
  });

  test(".mgx-mark and the slim override take their box from the tokens", () => {
    const hero = rule(shell, ".mgx-mark", "shell.css");
    assert.match(hero, /width:\s*var\(\s*--mark-hero\s*\)/);
    assert.match(hero, /height:\s*var\(\s*--mark-hero\s*\)/);
    const slim = rule(shell, ".mgx-bnr.slim .mgx-mark", "shell.css");
    assert.match(slim, /width:\s*var\(\s*--mark-slim\s*\)/);
    assert.match(slim, /height:\s*var\(\s*--mark-slim\s*\)/);
  });

  test("the animation engine's em base reads the tokens instead of re-typing them", () => {
    // A quarter of the rendered mark: every em offset in mark-anims.css is a fraction of
    // the mark itself, so this MUST be the same number the box is.
    assert.match(rule(anims, ".mgx-mark", "mark-anims.css"),
      /font-size:\s*calc\(\s*var\(\s*--mark-hero\s*\)\s*\*\s*var\(--anim-scale\)\s*\/\s*4\s*\)/);
    assert.match(rule(anims, ".mgx-bnr.slim .mgx-mark", "mark-anims.css"),
      /font-size:\s*calc\(\s*var\(\s*--mark-slim\s*\)\s*\*\s*var\(--anim-scale\)\s*\/\s*4\s*\)/);
  });

  test("no mark rule states 96px or 56px again", () => {
    for (const [css, where] of [[shell, "shell.css"], [anims, "mark-anims.css"]]) {
      for (const sel of [".mgx-mark", ".mgx-bnr.slim .mgx-mark"]) {
        const body = rule(css, sel, where);
        assert.doesNotMatch(body, /\b(?:96|56)px\b/,
          where + "'s `" + sel + "` types a mark size again: " + body);
      }
    }
  });
});

describe("the marks' other three sites scale from the hero", () => {
  // Each ratio reproduces EXACTLY the pixel that site rendered before the refactor, so the
  // token sweep is a no-op on screen today and proportional from here on.
  const CASES = [
    ["login.css", login, ".lgn-mark", "height", 88],
    ["login-mobile.css", loginM, ".lgnm-mark", "height", 66],
    ["gallery-mobile.css", galleryM, ".glm-hero-mark", "width", 50],
    ["gallery-mobile.css", galleryM, ".glm-hero-mark", "height", 50],
  ];
  for (const [where, css, sel, prop, px] of CASES) {
    test(`${where} ${sel} ${prop} still resolves to ${px}px`, () => {
      assert.equal(ratioPx(rule(css, sel, where), prop, where + " " + sel), px);
    });
  }

  /* Every OTHER `mark`-named box in the styles folder that still states a px size. None of
     these render the brand mark at a display size: they are picker chips, swatches and a
     wizard's tick -- fixed-size controls whose job is to be a control, not a smaller copy
     of the mark. They are listed EXACTLY, so a genuinely new mark-rendering surface that
     types its own size lands here as an unexpected entry and has to be looked at (the
     ruling's sweep is "everywhere, not spot-fix"; the Setup Wizard and the Folio render no
     brand mark today, and if either grows one it needs a ratio, not a literal). */
  const KNOWN_FIXED_CHIPS = [
    "control-panel.css  button.mgcp-mark",              // the mark picker's 32px tile
    "control-panel.css  .mgcp-markprevbox",             // its 168px preview stage
    "control-panel.css  .mgcp-markbig, button.mgcp-markbig",  // the 46px chooser tile
    "control-panel.css  .mgcp-markbig-check",           // the 15px tick on it
    "control-panel.css  button.mgcp-idmark, .mgcp-idmark",    // the 34px identity chip
    "control-panel.css  .mgcp-skinsample-mark",         // a 42px skin swatch
    "myart-mobile.css  .myam-loramark",                 // a 30px LoRA badge (not the mark)
    "setup-wizard-mobile.css  .wzm-readymark",          // the wizard's 52px tick
    "setup-wizard.css  .wz-readymark",                  // the wizard's 64px tick
  ];

  test("no NEW stylesheet rule sizes a mark with a literal px", () => {
    const dir = path.resolve(__dirname, "../../gallery/src/styles");
    const found = [];
    for (const f of readdirSync(dir).filter((n) => n.endsWith(".css")).sort()) {
      const css = stripComments(readFileSync(path.join(dir, f), "utf8").replace(/\r\n/g, "\n"));
      const re = /([^{}]*mark[^{}]*)\{([^{}]*)\}/gi;
      let m;
      while ((m = re.exec(css))) {
        const sel = m[1].trim();
        if (!sel || sel.startsWith("@")) continue;
        if (/(?:^|[\s;])(?:width|height):\s*\d+(?:\.\d+)?px/.test(m[2])) {
          found.push(f + "  " + sel.replace(/\s+/g, " "));
        }
      }
    }
    assert.deepEqual(found.sort(), [...KNOWN_FIXED_CHIPS].sort(),
      "a `mark` rule states a px size that this list does not account for. If it renders " +
      "the BRAND mark, size it as calc(var(--mark-hero) * <ratio>); if it is a fixed-size " +
      "control like the picker chips, add it to KNOWN_FIXED_CHIPS with a note saying so.");
  });
});
