import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

/* THE CREDIT LEDGER'S KNOWN REASONS. AccountSubOverlay.jsx draws a reason chip plain when it
   is one the app knows, and "raw" otherwise. The list it checks against was written with
   spaces ("event gift") while the server sends PixAI's own type keys ("event_gift"), so every
   chip on the ledger was drawn raw. The list must be exactly the server's keys:
   moonglade_backup.CREDIT_LOG_REASONS, the one table of confirmed types. */

const here = path.dirname(fileURLToPath(import.meta.url));
const src = (p) => readFileSync(path.join(here, "..", "..", p), "utf8").replace(/\r\n/g, "\n");

test("the ledger's known reasons are the server's own type keys", () => {
  const py = src("moonglade_backup.py");
  const table = py.match(/CREDIT_LOG_REASONS = \{([^}]*)\}/);
  assert.ok(table, "moonglade_backup.CREDIT_LOG_REASONS is where it was");
  const serverKeys = [...table[1].matchAll(/"([a-z_]+)"\s*:/g)].map((m) => m[1]).sort();
  assert.ok(serverKeys.length > 0);

  const jsx = src("gallery/src/components/AccountSubOverlay.jsx");
  const list = jsx.match(/const KNOWN_REASONS = \[([^\]]*)\];/);
  assert.ok(list, "AccountSubOverlay.jsx still has its KNOWN_REASONS list");
  const clientKeys = [...list[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]).sort();
  assert.deepEqual(clientKeys, serverKeys);
});
