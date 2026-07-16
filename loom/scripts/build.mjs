#!/usr/bin/env node
/* Bundles master-storyboard.jsx (+ its ./src/loom-core.js import) into a real,
 * pre-transpiled dist bundle -- the NEW, additional delivery path described in
 * the Phase 1 tooling pass (2026-07-16). The existing in-browser Babel-standalone
 * path (pixai_gallery.py's `loom()` route) is untouched and remains the default;
 * this bundle is opt-in until proven trustworthy.
 *
 * React/ReactDOM are NOT bundled -- they're already loaded as globals by
 * loom/vendor/{react,react-dom}.production.min.js (see LOOM_PAGE in
 * pixai_gallery.py). master-storyboard.jsx's `import React, {...} from "react"`
 * line exists only for editor/IDE convenience; the Flask route strips it with a
 * regex before inlining the JSX for Babel, and this script mirrors that exact
 * transform (strip the import line, then prepend the same
 * `const { useState, ... } = React;` destructure the HTML template injects)
 * so the esbuild bundle and the Babel-standalone fallback see IDENTICAL input.
 * Keep the regex and the destructured hook list in sync with pixai_gallery.py's
 * LOOM_PAGE / loom() if either ever changes.
 */
import { readFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import * as esbuild from "esbuild";

const here = path.dirname(fileURLToPath(import.meta.url));
const loomDir = path.resolve(here, "..");
const entryPath = path.join(loomDir, "master-storyboard.jsx");
const outfile = path.join(loomDir, "dist", "master-storyboard.bundle.js");

const HOOK_PREAMBLE = "const { useState, useEffect, useRef, useCallback } = React;\n";

function loadEntrySource() {
  const raw = readFileSync(entryPath, "utf-8");
  // Mirrors pixai_gallery.py's loom(): `jsx = re.sub(r"(?m)^\s*import\s+React.*$", "", jsx)`
  const stripped = raw.replace(/^[ \t]*import\s+React.*$/m, "");
  return HOOK_PREAMBLE + stripped;
}

async function main() {
  mkdirSync(path.dirname(outfile), { recursive: true });
  const contents = loadEntrySource();

  const result = await esbuild.build({
    stdin: {
      contents,
      resolveDir: loomDir,        // so `import ... from "./src/loom-core.js"` resolves
      sourcefile: "master-storyboard.jsx",
      loader: "jsx",
    },
    bundle: true,
    platform: "browser",
    format: "iife",
    globalName: "LoomBundle",     // -> window.LoomBundle.default is the App component
    jsx: "transform",             // classic runtime: React.createElement(...), matches
                                   // the Babel-standalone path (data-presets="react")
    target: ["es2020"],
    outfile,
    logLevel: "info",
    metafile: true,
  });

  const bytes = readFileSync(outfile).length;
  console.log(`Built ${path.relative(loomDir, outfile)} (${bytes.toLocaleString()} bytes)`);
  if (result.warnings.length) {
    console.warn(`${result.warnings.length} esbuild warning(s) -- see above`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
