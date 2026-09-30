import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import {
  githubSlug, parseInline, plainInline, parseWiki, classifyHref, glossaryMatchers,
  markGlossary, markPage, searchGuide, pageForSurface, visiblePages, whatsNewPlan,
  highlightsOf, toastSummary, spansText,
} from "../../gallery/src/help/helpCore.js";

/* The guide's pure core (gallery/src/help/helpCore.js): the wiki parser Help renders
   through, link classification, the Glossary underlines, the page search, the page each
   surface's "?" opens, and the what's-new plan. No DOM, no React -- the overlay only
   paints what these return. */

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const WIKI = path.resolve(__dirname, "../../wiki");

describe("heading anchors match GitHub's", () => {
  test("the anchors the wiki's own links use", () => {
    assert.equal(githubSlug("Free cards and videos"), "free-cards-and-videos");
    assert.equal(githubSlug("Runs itself — the living library"), "runs-itself--the-living-library");
    assert.equal(githubSlug("Safe · read-only or reversible"), "safe--read-only-or-reversible");
    assert.equal(githubSlug("The **Loom** & `cast`"), "the-loom--cast");
    assert.equal(githubSlug("🌙 Moonglade Athenaeum Wiki"), "-moonglade-athenaeum-wiki");
  });
  test("a repeated heading gets -1, -2", () => {
    const used = new Set();
    assert.deepEqual(["Notes", "Notes", "Notes"].map((t) => githubSlug(t, used)),
      ["notes", "notes-1", "notes-2"]);
  });
  test("every in-wiki #anchor link resolves to a heading on its page", () => {
    const pages = {};
    for (const f of readdirSync(WIKI).filter((n) => n.endsWith(".md") && !n.startsWith("_"))) {
      const blocks = parseWiki(readFileSync(path.join(WIKI, f), "utf8"));
      const anchors = new Set();
      const walk = (bs) => bs.forEach((b) => { if (b.type === "h") anchors.add(b.anchor); if (b.blocks) walk(b.blocks); });
      walk(blocks);
      pages[f.slice(0, -3)] = { anchors, src: readFileSync(path.join(WIKI, f), "utf8") };
    }
    const broken = [];
    for (const [slug, p] of Object.entries(pages)) {
      for (const m of p.src.matchAll(/\]\(([A-Za-z0-9_-]*)#([^)\s]+)\)/g)) {
        const target = m[1] || slug;
        if (!pages[target] || !pages[target].anchors.has(decodeURIComponent(m[2]))) {
          broken.push(slug + " -> " + target + "#" + m[2]);
        }
      }
    }
    assert.deepEqual(broken, [], "wiki links whose anchor names no heading");
  });
});

describe("inline markdown", () => {
  test("code is literal, a link's label may hold bold, emphasis nests", () => {
    assert.deepEqual(parseInline("use `--out **x**` now"), [
      { t: "text", v: "use " }, { t: "code", v: "--out **x**" }, { t: "text", v: " now" }]);
    assert.deepEqual(parseInline("**[Setup](Setup)** — go"), [
      { t: "b", c: [{ t: "a", href: "Setup", c: [{ t: "text", v: "Setup" }] }] },
      { t: "text", v: " — go" }]);
    assert.deepEqual(parseInline("an *aside* and _this_"), [
      { t: "text", v: "an " }, { t: "i", c: [{ t: "text", v: "aside" }] },
      { t: "text", v: " and " }, { t: "i", c: [{ t: "text", v: "this" }] }]);
  });
  test("snake_case and a lone asterisk stay text", () => {
    assert.equal(plainInline("view_presets and mg_thumb * 2"), "view_presets and mg_thumb * 2");
    assert.deepEqual(parseInline("view_presets"), [{ t: "text", v: "view_presets" }]);
  });
  test("a <script> in a page is text, never markup", () => {
    assert.deepEqual(parseInline("<script>x</script>"), [{ t: "text", v: "<script>x</script>" }]);
  });
});

describe("blocks", () => {
  test("headings, paragraphs, fences, rules", () => {
    const b = parseWiki("# Title\n\nOne line\nsame para.\n\n```\n# not a heading\n```\n\n---\n## Next\n");
    assert.deepEqual(b.map((x) => x.type), ["h", "p", "code", "hr", "h"]);
    assert.equal(b[0].anchor, "title");
    assert.equal(plainInline("One line same para."), "One line same para.");
    assert.equal(b[2].text, "# not a heading");
  });
  test("lists join their wrapped lines; a blank line between items keeps one list", () => {
    const b = parseWiki("- first item\n  wraps here\n- second\n\n- third\n\nafter\n");
    assert.equal(b[0].type, "ul");
    assert.equal(b[0].items.length, 3);
    assert.equal(b[0].items[0].map((s) => s.v).join(""), "first item wraps here");
    assert.equal(b[1].type, "p");
    const o = parseWiki("1. `--out` wins\n2. then config\n");
    assert.equal(o[0].type, "ol");
    assert.equal(o[0].start, 1);
    assert.equal(o[0].items.length, 2);
  });
  test("a table keeps its header, alignment and cells (escaped pipes stay in the cell)", () => {
    const b = parseWiki("| Flag | What |\n|---|:---:|\n| `--a` | one \\| two |\n| b | c |\n");
    assert.equal(b[0].type, "table");
    assert.deepEqual(b[0].align, ["", "center"]);
    assert.equal(b[0].rows.length, 2);
    assert.equal(b[0].rows[0][1][0].v, "one | two");
  });
  test("a block quote holds its own blocks", () => {
    const b = parseWiki("> **Note.** careful\n> - a\n> - b\n");
    assert.equal(b[0].type, "quote");
    assert.deepEqual(b[0].blocks.map((x) => x.type), ["p", "ul"]);
  });
  test("every shipped page parses to something readable", () => {
    for (const f of readdirSync(WIKI).filter((n) => n.endsWith(".md") && !n.startsWith("_"))) {
      const blocks = parseWiki(readFileSync(path.join(WIKI, f), "utf8"));
      assert.ok(blocks.length > 0, f);
      assert.equal(blocks.filter((x) => x.type === "h" && x.level === 1).length >= 1, true, f + " has a title");
    }
  });
});

describe("links", () => {
  const slugs = new Set(["Home", "Setup", "Generating"]);
  test("a wiki page opens in place, with its anchor", () => {
    assert.deepEqual(classifyHref("Generating#free-cards-and-videos", slugs),
      { kind: "page", slug: "Generating", anchor: "free-cards-and-videos" });
    assert.deepEqual(classifyHref("#modes", slugs), { kind: "anchor", anchor: "modes" });
    assert.deepEqual(classifyHref("https://github.com/Nelnamara/moonglade-athenaeum/wiki/Setup", slugs),
      { kind: "page", slug: "Setup", anchor: "" });
  });
  test("outside links are external; anything else is only text", () => {
    assert.deepEqual(classifyHref("https://pixai.art", slugs), { kind: "external", href: "https://pixai.art" });
    assert.equal(classifyHref("javascript:alert(1)", slugs).kind, "text");
    assert.equal(classifyHref("../blob/master/X.md", slugs).kind, "text");
    assert.equal(classifyHref("Nowhere", slugs).kind, "text");
  });
});

describe("the Glossary underlines", () => {
  const ms = glossaryMatchers([
    { term: "the dock", def: "the generate panel" },
    { term: "the Library", def: "the grid of your pictures" },
    { term: "toast", def: "a corner notice" },
    { term: "Live Mirror", def: "the readout" },
  ]);
  test("first use per page, plural allowed, 'the' is not underlined", () => {
    const used = new Set();
    const out = markGlossary(parseInline("Open the dock; toasts appear. The dock again."), ms, used);
    const terms = out.filter((s) => s.t === "term").map((s) => s.v);
    assert.deepEqual(terms, ["dock", "toasts"]);
  });
  test("a capitalised term is case-sensitive, so 'library' in a sentence is just a word", () => {
    const used = new Set();
    const out = markGlossary(parseInline("your library, then the Library."), ms, used);
    assert.deepEqual(out.filter((s) => s.t === "term").map((s) => s.v), ["Library"]);
  });
  test("never inside code or a link", () => {
    const used = new Set();
    const out = markGlossary(parseInline("`the dock` and [the dock](Generating)"), ms, used);
    assert.equal(out.filter((s) => s.t === "term").length, 0);
  });
  test("longest term first", () => {
    const used = new Set();
    const out = markGlossary(parseInline("Live Mirror is on"), ms, used);
    assert.equal(out.find((s) => s.t === "term").term, "Live Mirror");
  });
  test("headings are left alone, lists and tables are marked", () => {
    const blocks = markPage(parseWiki("## The dock\n\n- a toast\n\n| x |\n|---|\n| the dock |\n"), ms);
    assert.equal(blocks[0].type, "h");
    assert.ok(blocks[1].items[0].some((s) => s.t === "term"));
    assert.ok(blocks[2].rows[0][0].some((s) => s.t === "term"));
  });
});

describe("search", () => {
  const pages = [
    { slug: "Home", title: "Home", headings: [{ level: 2, text: "Guides" }] },
    { slug: "The-Loom", title: "The Loom", headings: [{ level: 2, text: "Continuity" }, { level: 2, text: "Shots" }] },
    { slug: "Generating", title: "Generating", headings: [{ level: 2, text: "Free cards and videos" }] },
  ];
  test("titles and headings, fuzzy, best first", () => {
    const hits = searchGuide(pages, "loom");
    assert.equal(hits[0].slug, "The-Loom");
    assert.equal(hits[0].heading, "");
    const h2 = searchGuide(pages, "cntnty");
    assert.deepEqual(h2.map((h) => [h.slug, h.heading]), [["The-Loom", "Continuity"]]);
    assert.deepEqual(searchGuide(pages, ""), []);
  });
});

describe("surfaces and the Branding rule", () => {
  test("each surface's ? opens its page; Branding opens the Control Panel's", () => {
    assert.equal(pageForSurface("loom"), "The-Loom");
    assert.equal(pageForSurface("dock"), "Generating");
    assert.equal(pageForSurface("branding"), "Control-Panel");
    assert.equal(pageForSurface("nowhere"), "Home");
  });
  test("a page or heading naming Branding stays out until the unlock", () => {
    const pages = [{ slug: "Branding", title: "Branding", headings: [] },
      { slug: "Control-Panel", title: "Control Panel", headings: [{ level: 2, text: "Branding" }, { level: 2, text: "Users" }] }];
    const locked = visiblePages(pages, false);
    assert.deepEqual(locked.map((p) => p.slug), ["Control-Panel"]);
    assert.deepEqual(locked[0].headings.map((h) => h.text), ["Users"]);
    assert.equal(visiblePages(pages, true).length, 2);
  });
});

describe("what's new", () => {
  test("once per version per account; minor opens the sheet, patch opens About", () => {
    assert.deepEqual(whatsNewPlan({ seen: "3.14", display: "3.15", kind: "minor", hasLibrary: true }),
      { show: true, mark: true, opens: "sheet" });
    assert.deepEqual(whatsNewPlan({ seen: "3.15", display: "3.15.1", kind: "patch", hasLibrary: true }),
      { show: true, mark: true, opens: "about" });
    assert.deepEqual(whatsNewPlan({ seen: "3.15", display: "3.15", kind: "minor", hasLibrary: true }),
      { show: false, mark: false });
  });
  test("a brand-new account is noted, not told it was updated", () => {
    assert.deepEqual(whatsNewPlan({ seen: undefined, display: "3.15", kind: "minor", hasLibrary: false }),
      { show: false, mark: true });
    assert.equal(whatsNewPlan({ seen: undefined, display: "3.15", kind: "minor", hasLibrary: true }).show, true);
  });
  test("highlights are the block's own first four, never its internal-notes section", () => {
    const items = [{ lead: "a", section: "" }, { lead: "u", section: "Under the hood" },
      { lead: "b", section: "" }, { lead: "c", section: "" }, { lead: "d", section: "" },
      { lead: "e", section: "" }];
    assert.deepEqual(highlightsOf(items).map((i) => i.lead), ["a", "b", "c", "d"]);
    assert.deepEqual(highlightsOf(items.slice(0, 3)).map((i) => i.lead), ["a", "b"]);
    assert.equal(toastSummary({ title: "Moving Pictures", items }), "Moving Pictures");
    assert.equal(toastSummary({ title: "", items }), "a");
  });
});

// Owner walk 2026-09-29: Help's "The Gallery" page opened with command-line lines.
describe("The Gallery page opens in plain words", () => {
  test("nothing but words before the first section; the commands have their own", () => {
    const blocks = parseWiki(readFileSync(path.join(WIKI, "Gallery.md"), "utf8"));
    assert.equal(blocks[0].type, "h");
    const firstSection = blocks.findIndex((b, i) => i > 0 && b.type === "h");
    assert.ok(firstSection > 1, "an introduction under the title");
    assert.ok(blocks.slice(1, firstSection).every((b) => b.type === "p"),
      "the introduction is paragraphs only, no command block");
    assert.match(blocks.slice(1, firstSection).map((b) => spansText(b.spans)).join(" "), /Serve Gallery\.pyw/);
    const term = blocks.findIndex((b) => b.type === "h" && b.anchor === "running-it-from-a-terminal");
    assert.equal(term, firstSection, "the terminal section follows the introduction");
    const next = blocks.findIndex((b, i) => i > term && b.type === "h");
    const code = blocks.slice(term + 1, next).filter((b) => b.type === "code");
    assert.equal(code.length, 1);
    assert.match(code[0].text, /python moonglade_gallery\.py --out pixai_backup/);
    assert.ok(!blocks.slice(0, term).some((b) => b.type === "code"));
  });
});

// Owner walk 2026-09-29: "No ? anywhere on screen" (the library's "?" was a faint ring on the
// banner art) and Help's back/forward arrows were near invisible.
describe("the library's ? and Help's arrows are visible", () => {
  const css = readFileSync(path.resolve(__dirname, "../../gallery/src/styles/help.css"), "utf8");
  const rule = (sel) => {
    const at = css.indexOf(sel + " {");
    assert.ok(at >= 0, "no rule " + sel);
    return css.slice(at, css.indexOf("}", at));
  };
  test("the ? wears a solid chip face with a white glyph, at a size that reads", () => {
    const face = rule(".mghelp-q.mgx-help, .mghelp-q.mgx-sephelp");
    assert.match(face, /background: linear-gradient\(/);
    assert.match(face, /color-mix\(in srgb, var\(--base\) 82%, transparent\)/);   // the solid ground
    assert.match(face, /color: #f2ecff/);
    assert.match(face, /border: 1px solid rgba\(255, 255, 255, \.26\)/);
    const w = Number(/width: (\d+)px/.exec(rule(".mghelp-q.mgx-help"))[1]);
    assert.ok(w >= 32, "the banner's ? is at least 32 px, got " + w);
  });
  test("back and forward are bordered buttons with a large glyph", () => {
    const nav = rule(".mghelp-nav button");
    assert.match(nav, /border: 1px solid var\(--surface1\)/);
    assert.match(nav, /background: var\(--surface0\)/);
    assert.match(nav, /color: var\(--text\)/);
    assert.ok(Number(/font: 600 (\d+)px/.exec(nav)[1]) >= 16);
  });
});
