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

   THE REMOVAL RULE (corrected 2026-09-04). The first cut of this module asserted that
   removing a LoRA leaves its words in the prompt "because PixAI does not strip either."
   That was wrong, and it was wrong about the one thing this whole feature is measured
   against. The owner, from live use: "Removing a Lora on pixai DOES remove words." His
   observation is the standard here -- the ruling on #45 is "matches PixAI behavior," and
   an un-pick that leaves three dead activation tokens behind in the box does not.

   So `removeTriggerWords` takes them back out, on the SAME matching rule the insert and
   the dedupe use -- one rule in one module, never two that drift -- with two guards:

     · KEEP WORDS. A token belonging to a LoRA that is STILL picked survives. Two LoRAs
       can share an activation word; dropping one of them must not silently disarm the
       other. The caller passes the union of the remaining LoRAs' trigger_words and any
       token in it is skipped.
     · SEAM TIDY. Cutting a token out of the middle of a list leaves "a, , b" and cutting
       one off either end leaves a dangling ", ". Only the seams the cut actually made are
       normalised -- a comma-and-space run around a cut collapses to ", " between text and
       to nothing at an end -- so the user's own spacing everywhere else is untouched, and
       a prompt with none of the words comes back byte-identical.

   THE CAVEAT, HONESTLY: only EXACT token occurrences are removed. If the user reworded a
   token, reweighted it by hand, or wrote it into a sentence, that text is theirs and it
   stays. That is PixAI-shaped too, and the alternative -- guessing at what "looks like" a
   trigger word -- would delete the user's writing out from under them. The mirror of that
   honesty: an exact occurrence goes even if the USER typed it before ever picking the
   LoRA. Nothing records who typed which token, PixAI records no such thing either, and
   inventing provenance to guess at it would be a worse lie than the plain rule. So the
   round-trip guarantee is by CONTENT, not by byte: remove-then-re-add restores every
   token, in this module's own canonical order rather than the user's original one. The
   "+words" button remains the way back for words removed on purpose or by an un-pick. */

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

/* WHERE this exact token sits in the prompt -- every occurrence, as [start, end) index
   pairs into the ORIGINAL string. This is THE matching rule: the dedupe asks whether the
   list is empty, the removal cuts the ranges out. One implementation, so "already there"
   and "take it back out" can never disagree about what counts as a match.

   Substring search with a hand-rolled boundary check rather than a RegExp: the tokens are
   author-supplied text containing `<`, `>`, `:`, `(`, `)` and worse, so building a pattern
   from one would either throw or silently match the wrong thing. A boundary is required
   only on a side where the TOKEN itself ends in a word character -- "<lora:ErisV14:1>"
   opens and closes on punctuation and is matched wherever it appears. */
export function triggerOccurrences(prompt, token) {
  if (typeof prompt !== "string" || typeof token !== "string") return [];
  const t = token.trim().toLowerCase();
  if (!t) return [];
  const h = prompt.toLowerCase();
  const needHeadBoundary = isWordChar(t[0]);
  const needTailBoundary = isWordChar(t[t.length - 1]);
  const hits = [];
  let i = h.indexOf(t);
  while (i !== -1) {
    const before = i > 0 ? h[i - 1] : "";
    const after = h[i + t.length] || "";
    if ((!needHeadBoundary || !isWordChar(before)) &&
        (!needTailBoundary || !isWordChar(after))) hits.push([i, i + t.length]);
    i = h.indexOf(t, i + 1);
  }
  return hits;
}

/* Is this exact token already in the prompt? The predicate the insert is built on --
   the same match the removal cuts, asked as a yes/no. */
export function promptHasTrigger(prompt, token) {
  return triggerOccurrences(prompt, token).length > 0;
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

/* ---- removal ---- */

/* Every trigger token across one or more trigger_words strings, lower-cased, as a Set.
   Accepts a single string or an array of them, which is what the caller has to hand:
   `remainingLoras.map((l) => l.trigger_words)`. Non-strings contribute nothing. */
export function triggerWordSet(triggerWordsList) {
  const list = Array.isArray(triggerWordsList) ? triggerWordsList : [triggerWordsList];
  const set = new Set();
  for (const w of list) for (const t of splitTriggerWords(w)) set.add(t.toLowerCase());
  return set;
}

/* A separator character for seam purposes: the comma the list is built on, and whitespace.
   Nothing else -- a cut must never eat into the user's punctuation. */
function isSeamChar(c) {
  return c === "," || (!!c && /\s/.test(c));
}

/* The tokens of `triggerWords` that this prompt actually carries and that no still-picked
   LoRA also claims -- i.e. what removing this LoRA is entitled to delete. */
export function removableTriggerWords(prompt, triggerWords, keepWords) {
  const keep = triggerWordSet(keepWords);
  return splitTriggerWords(triggerWords)
    .filter((t) => !keep.has(t.toLowerCase()))
    .filter((t) => promptHasTrigger(prompt, t));
}

/* The prompt with this LoRA's trigger words taken back out -- the un-pick half of the ONE
   rule, matching on exactly what `insertTriggerWords` would have put in.

   `keepWords` is the union of the trigger words of the LoRAs still picked (a string or an
   array of them); a token in it survives, because it is still arming something.

   Returns the prompt UNCHANGED (same string, not a tidied copy) when there is nothing to
   cut -- the no-op path must not normalise a prompt the user is mid-sentence in, exactly
   as on the insert side. Round-trips with the insert: remove then re-add restores the
   text. Only EXACT occurrences go; reworded text is the user's and stays. */
export function removeTriggerWords(prompt, triggerWords, keepWords) {
  const base = typeof prompt === "string" ? prompt : "";
  const drop = removableTriggerWords(base, triggerWords, keepWords);
  if (!drop.length) return base;

  // Every occurrence of every removable token, sorted by position.
  const hits = [];
  for (const t of drop) for (const r of triggerOccurrences(base, t)) hits.push(r);
  hits.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  if (!hits.length) return base;

  // Merge overlaps AND runs separated only by seam characters, so "1stasc, 2ndasc" is one
  // cut with one seam to tidy rather than two whose repairs would tread on each other.
  const cuts = [hits[0].slice()];
  for (const [s, e] of hits.slice(1)) {
    const last = cuts[cuts.length - 1];
    const gap = s > last[1] ? base.slice(last[1], s) : "";
    if (s <= last[1] || [...gap].every(isSeamChar)) last[1] = Math.max(last[1], e);
    else cuts.push([s, e]);
  }

  // Cut, remembering where each seam landed in the OUTPUT.
  let out = "";
  const seams = [];
  let at = 0;
  for (const [s, e] of cuts) {
    out += base.slice(at, s);
    seams.push(out.length);
    at = e;
  }
  out += base.slice(at);

  // Tidy ONLY those seams, right-to-left so the earlier indices stay valid. The run of
  // commas and whitespace around a seam becomes ", " when there is text on both sides
  // (that is the list's own separator), a single space when the run held whitespace but no
  // comma, nothing when there was no run at all, and nothing when the cut left one side
  // empty -- which is what trims a dangling leading or trailing ", ".
  for (let i = seams.length - 1; i >= 0; i--) {
    let L = seams[i];
    let R = seams[i];
    while (L > 0 && isSeamChar(out[L - 1])) L--;
    while (R < out.length && isSeamChar(out[R])) R++;
    const run = out.slice(L, R);
    const joined = (L === 0 || R === out.length || !run) ? ""
      : (run.includes(",") ? ", " : " ");
    out = out.slice(0, L) + joined + out.slice(R);
  }
  return out;
}
