/* THE NARRATOR'S POKE, the page's half -- pure, and it imports NOTHING on purpose (so a node
   test can pin it without a renderer, a DOM or a network).

   The server owns the ladder: it keeps the count and the clocks, decides whether a poke
   counts and chooses the line (moonglade_narrator.py, POST /api/narrator/poke). What comes
   back is a line and nothing else, so this module has almost nothing to decide: it turns the
   answer into what the page paints, and it knows the words of NOTHING the narrator says
   (they arrive from the sealed pack). The only copy here is the plain wording of the
   choice's frame, used when the pack sends none of its own.

   The page cannot tell a poke that counted from one that did not, how far along it is, or
   which stage it is in -- there is nothing in the answer to tell it. That is the point. */

/* The choice the last poke ends on. The words are the pack's when it sends them; these are
   only what stands in when it does not. The two buttons are the Folio's own vocabulary:
   the ruby pill says "Unleash the AI", and "the filter" is what it switches off. */
export const CHOICE_DEFAULT = {
  title: "How do you want the narrator from now on?",
  keep: "Keep the filter",
  unleash: "Unleash her",
  foot: "You can change this any time in the Folio.",
};

/* The choice's four words: the pack's where it sent a non-empty string, else the default. */
export function choiceCopy(sent) {
  const out = { ...CHOICE_DEFAULT };
  if (sent && typeof sent === "object") {
    for (const k of Object.keys(CHOICE_DEFAULT)) {
      if (typeof sent[k] === "string" && sent[k].trim()) out[k] = sent[k].trim();
    }
  }
  return out;
}

/* The poke route's answer as what the page does with it.
     show   paint `line` as a toast (false for an error or an answer with no line: a refusal
            is a quiet no-op, exactly as every beacon caller has always treated one)
     final  the poke that ended the ladder AND earned the feat: `card` is that feat's id, and
            `clean` / `unleashed` are its two lines, `choice` the words for what comes next.
     A final with no id (a pack whose feat is not wired to the ladder) is just a line. */
export function pokeView(res) {
  const none = { show: false, line: "", final: false };
  if (!res || typeof res !== "object" || res.error) return none;
  const line = typeof res.line === "string" ? res.line : "";
  if (!line) return none;
  const f = res.final;
  if (f && typeof f === "object" && typeof f.id === "string" && f.id) {
    return {
      show: true, line, final: true, card: f.id,
      clean: typeof f.clean === "string" ? f.clean : line,
      unleashed: typeof f.unleashed === "string" ? f.unleashed : "",
      choice: choiceCopy(f.choice),
    };
  }
  return { show: true, line, final: false };
}

/* Which pick answers the choice: "Unleash" turns the account switch on, "Keep" writes it off
   explicitly (so the migration of an old browser value never reads the account as blank). */
export function choiceValue(pick) {
  return pick === "unleash";
}
