/* THE LoRA TRIGGER-WORD RULE -- one rule, both composers (issue #45).

   A LoRA attached WITHOUT its activation tokens is a silent no-op on a paid generation
   (private/GENERATOR_SURFACE.md, "LoRA TRIGGER WORDS": `latestVersion.extra.triggerWords`
   holds the tokens the weights were trained against; empty extra = no triggers). PixAI's
   own composer appends them to the prompt the moment you pick the LoRA -- the owner's
   words on the 2026-08-29 surface walk: "does not auto insert - Desktop needs auto insert
   too... I have to click to add lora text which is dumb". Until now the desktop drawer
   offered a manual "+words" button and mobile offered nothing at all.

   This module is the rule, extracted and IMPORTLESS for the same reason gen/queueWait.js
   is: GenerateDrawer.jsx and CreateMobile.jsx are JSX and the node suite cannot import
   them, so the decision of WHAT text lands in the prompt is testable only outside the
   components. Both surfaces, the automatic insert and the manual re-insert button, call
   `insertTriggerWords` -- there is exactly ONE formatting rule here, never two that drift.

   THE SHAPE OF THE DATA. `trigger_words` is a comma-separated STRING server-side, never an
   array (useGenerate.js coerces anything else to ""). Real banked values:
       'Fairy Knight Tristan' -> "1stasc, 2ndasc, 3rdasc"
       'Eris (Adult)'         -> "Eris_Adult, <lora:ErisV14:1>"
   so a token may be a multi-word phrase, may carry underscores, and may be PixAI's
   `<lora:name:weight>` weight syntax -- which is why the containment test below cannot be
   a naive `\b` regex (`\b` does not exist beside `<` or `>`) and cannot be an unescaped
   RegExp (`<lora:ErisV14:1>` is not a valid pattern's worth of literal characters).

   THE FORMATTING RULE is the desktop "+words" button's, preserved to the character so the
   automatic insert and a later manual click produce identical text:
     · the prompt is trimmed and any trailing comma (plus its whitespace) dropped;
     · a ", " joins it to the words;
     · an EMPTY prompt takes the words alone, with no leading separator;
     · the words themselves are joined with ", ".

   THE DEDUPE RULE (the design call issue #45 asked for): a token already present in the
   prompt is not appended again. Matching is case-insensitive and boundary-aware, so
   "1stasc" already in the prompt blocks a second copy but the prompt word "1stascension"
   does NOT -- while "<lora:ErisV14:1>", whose ends are punctuation, needs no boundary on
   the side that has none. Duplicates WITHIN one trigger_words string collapse too.

   WHAT THIS DELIBERATELY DOES NOT DO: removing a LoRA does not strip its words back out.
   PixAI does not strip either, and by then the prompt is the user's -- they may have
   reworded around the tokens, reordered them, or reweighted them by hand. Silently
   deleting text from a box the user has been typing in is the one failure mode worse than
   an extra token, so the removal path leaves the prompt exactly as it stands and the
   "+words" button remains the way back for words that WERE deleted on purpose. */

/* Characters that make up a "word" for boundary purposes. Kept as an explicit class
   rather than \w so the intent is readable at the call site: letters, digits, underscore. */
function isWordChar(c) {
  return !!c && /[a-z0-9_]/.test(c);
}

/* The tokens inside a trigger_words string: comma-separated, trimmed, blanks dropped,
   and de-duplicated against each other case-insensitively (first spelling wins, so the
   author's own capitalisation is what reaches the prompt). Anything that is not a
   non-empty string yields [] -- a LoRA with no triggers is the common case, not an error. */
export function splitTriggerWords(triggerWords) {
  if (typeof triggerWords !== "string" || !triggerWords.trim()) return [];
  const out = [];
  const seen = new Set();
  for (const raw of triggerWords.split(",")) {
    const t = raw.trim();
    if (!t) continue;
    const k = t.toLowerCase();
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(t);
  }
  return out;
}

/* Is this exact token already in the prompt?

   Substring search with a hand-rolled boundary check rather than a RegExp: the tokens are
   author-supplied text containing `<`, `>`, `:`, `(`, `)` and worse, so building a pattern
   from one would either throw or silently match the wrong thing. A boundary is required
   only on a side where the TOKEN itself ends in a word character -- "<lora:ErisV14:1>"
   opens and closes on punctuation and is matched wherever it appears. */
export function promptHasTrigger(prompt, token) {
  if (typeof prompt !== "string" || typeof token !== "string") return false;
  const t = token.trim().toLowerCase();
  if (!t) return false;
  const h = prompt.toLowerCase();
  const needHeadBoundary = isWordChar(t[0]);
  const needTailBoundary = isWordChar(t[t.length - 1]);
  let i = h.indexOf(t);
  while (i !== -1) {
    const before = i > 0 ? h[i - 1] : "";
    const after = h[i + t.length] || "";
    if ((!needHeadBoundary || !isWordChar(before)) &&
        (!needTailBoundary || !isWordChar(after))) return true;
    i = h.indexOf(t, i + 1);
  }
  return false;
}

/* The tokens this LoRA needs that the prompt does not already carry, in the author's own
   order. Empty array = nothing to do, which is what makes the insert idempotent. */
export function missingTriggerWords(prompt, triggerWords) {
  return splitTriggerWords(triggerWords).filter((t) => !promptHasTrigger(prompt, t));
}

/* The prompt with this LoRA's missing trigger words appended -- the ONE formatting rule.

   Returns the prompt UNCHANGED (same string, not a trimmed copy) when there is nothing to
   add. That matters: this runs on every LoRA pick, including LoRAs with no triggers at
   all, and trimming a prompt the user is mid-sentence in would eat the space they just
   typed. Idempotent by construction -- a second call finds every token present. */
export function insertTriggerWords(prompt, triggerWords) {
  const base = typeof prompt === "string" ? prompt : "";
  const add = missingTriggerWords(base, triggerWords);
  if (!add.length) return base;
  const head = base.trim().replace(/,\s*$/, "");
  return (head ? head + ", " : "") + add.join(", ");
}
