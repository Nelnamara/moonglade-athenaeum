// The Image Details headline, per Image Details.dc.html: a QUOTED PROMPT EXCERPT of
// roughly 40 characters in the 30px italic serif -- "Night elf, long elven ears, lavender
// skin", "Moonwell reflections, wide establishing shot". A typed title wins outright; the
// filename NEVER appears here (it has its own ledger row). "Where the Refit Broke"
// (19 Aug 2026): an implementer overrode the design with `title || filename`, which shipped
// the raw, mid-word-clipped filename as the headline on 99.95% of the library.
//
// The DC's own samples skip the booru scaffolding: its first record's prompt opens
// "1girl, sitting on floor, white slime on face, looking at viewer, night elf, ..." and its
// headline is "Night elf, long elven ears, lavender skin" -- the first DESCRIPTIVE clauses.
// So: drop quality/scaffold tags, drop artist:/lora tokens and Loom shot markup, take
// clauses until ~40 chars -- always keeping the first descriptive clause (the subject).

const SCAFFOLD = new Set([
  "masterpiece", "best quality", "amazing quality", "high quality", "highres", "absurdres",
  "very awa", "newest", "1girl", "1boy", "2girls", "2boys", "solo", "looking at viewer",
  "detailed background", "ultra detailed", "highly detailed", "8k", "4k", "score_9",
  "score_8_up", "score_7_up", "rating_safe", "rating_explicit", "rating_questionable",
]);

function isScaffold(clause) {
  const c = clause.toLowerCase();
  if (SCAFFOLD.has(c)) return true;
  if (/^(artist|character|copyright|lora|source):/i.test(c)) return true;   // tag namespaces
  if (/^<[^>]*>$/.test(c)) return true;                                        // <lora:...:0.8>
  if (/^score_\d/.test(c) || /^rating_/.test(c)) return true;                  // pony scores
  if (/^\(?(masterpiece|best quality)/.test(c)) return true;
  return false;
}

// Split a prompt into clauses on commas (and newlines), after stripping Loom shot
// scaffolding -- "[A-01 — \"Establishing shot\"]", "(R2V, ~15s, First→Last)", "@image1",
// "Opening frame:" / "Closing frame:" labels -- none of which is description. Then strip
// weight syntax like "(word:1.2)" / "word:1.2" and inline <lora:...> tokens, trim, drop empties.
function clauses(prompt) {
  return String(prompt || "")
    .replace(/\[[^\]]*\]/g, " ")
    .replace(/\((?:R2V|I2V|FLF|T2V)[^)]*\)/gi, " ")
    .replace(/@image\d+/gi, " ")
    .replace(/\b(?:opening|closing|first|last)\s+frame\s*:?/gi, " ")
    .replace(/<[^>]*>/g, " ")
    .replace(/\b(?:character|copyright|lora|source):\s*/gi, " ")
    .split(/[,\n]/)
    .map((s) => s.replace(/^[\s(]+|[\s)]+$/g, "").replace(/:\d+(\.\d+)?$/, "").trim())
    .filter(Boolean);
}

function capFirst(s) {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s;
}

// -> the headline string (already quoted), or "" when there is nothing descriptive to say.
export function promptExcerpt(prompt, max = 44) {
  const parts = clauses(prompt).filter((c) => !isScaffold(c));
  if (!parts.length) return "";
  // The first descriptive clause is the subject -- it is ALWAYS kept, trimmed to the cap at
  // a word boundary with an ellipsis if it alone is too long. (Skipping it for being long
  // turned "An extreme low-angle shot looking up at an elven woman, standing majestically..."
  // into "Standing majestically...", losing the subject.)
  const first = parts[0];
  if (first.length > max) {
    const cut = first.slice(0, max).replace(/\s+\S*$/, "");
    return "“" + capFirst(cut || first.slice(0, max)) + "…”";
  }
  const out = [first];
  let len = first.length;
  for (const p of parts.slice(1)) {
    if (len + 2 + p.length > max) break;
    out.push(p);
    len += 2 + p.length;
  }
  return "“" + capFirst(out.join(", ")) + "”";
}

// The headline for a catalog row: typed title > prompt excerpt > "Untitled". Never the filename.
export function detailsHeadline(row) {
  if (!row) return "";
  const title = String(row.title || "").trim();
  if (title) return title;
  const ex = promptExcerpt(row.prompt_full || row.natural_prompt || row.prompt_preview || "");
  return ex || "Untitled";
}
