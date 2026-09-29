/* THE ar: OPERATOR, CLIENT HALF (Session N7) -- everything the screens decide about aspect
   searches without React or a DOM. The FILTERING is the server's (moonglade_gallery._aspect_clause):
   the library is paginated, so only the server can answer "every tall picture", and the page's
   client-side stand-in over 24 sample pictures could not. What lives here is what the screens
   need around it: which values are valid (so a typo is said, not silently searched as a word),
   the Aspect field's options and its round trip through the search text, the suggestions the
   search field offers while an `ar:` is being typed, and the small label a card draws for its
   own shape. loom/test/aspect-core.test.js pins all of it.

   The accepted values are the design page's (Curation Handoff, N7):
     ar:W:H       within 3 percent of W/H        ar:3:2  ar:9:16  ar:1.91:1
     ar:square    0.97 to 1.03
     ar:portrait  below 1     ar:landscape  above 1
     ar:tall      9:16 or taller     ar:wide  16:9 or wider
     ar:>N  ar:<N   the ratio itself             ar:>2  ar:<0.5 */

export const AR_ERROR = "ar: takes W:H, square, portrait, landscape, tall, wide, >N or <N.";

/* The Aspect field's choices, in the order the flyout and the phone's chip row show them. `value`
   is what follows `ar:`. The last of them has no value of its own: a shape typed as W:H. */
export const ASPECT_CHOICES = [
  { value: "square", label: "Square", hint: "0.97 to 1.03" },
  { value: "portrait", label: "Portrait", hint: "taller than wide" },
  { value: "landscape", label: "Landscape", hint: "wider than tall" },
  { value: "tall", label: "Tall", hint: "9:16 or taller" },
  { value: "wide", label: "Wide", hint: "16:9 or wider" },
];

/* The shapes worth a one-tap suggestion after `ar:` -- the same ones the generator offers. */
const COMMON_SHAPES = ["1:1", "3:4", "4:3", "2:3", "3:2", "9:16", "16:9", "5:4", "21:9"];

const NAMED = ["square", "portrait", "landscape", "tall", "wide"];
const WH = /^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/;
const CMP = /^([<>])(\d*\.?\d+)$/;

/* Is `value` (the text after `ar:`) one the server understands? {ok, kind, ...} or {ok:false}.
   Case-insensitive, like the server. A W:H with a zero side is not a shape. */
export function parseAspect(value) {
  const v = String(value == null ? "" : value).trim().toLowerCase();
  if (NAMED.indexOf(v) >= 0) return { ok: true, kind: v, value: v };
  let m = v.match(CMP);
  if (m) return { ok: true, kind: m[1] === ">" ? "gt" : "lt", n: Number(m[2]), value: v };
  m = v.match(WH);
  if (m && Number(m[1]) > 0 && Number(m[2]) > 0) {
    return { ok: true, kind: "ratio", w: Number(m[1]), h: Number(m[2]), value: v };
  }
  return { ok: false };
}

/* The whitespace-separated tokens of a search, keeping quoted runs whole (the server's own
   tokenizer, so a quoted phrase that mentions ar: is left alone). */
function tokens(query) {
  return String(query == null ? "" : query).match(/[^\s"]*"[^"]*"[^\s"]*|\S+/g) || [];
}

const AR_TOKEN = /^(-?)(?:ar|aspect):(.*)$/i;

/* The first un-negated ar: token's value, or "" -- what the Aspect field shows. */
export function aspectIn(query) {
  for (const t of tokens(query)) {
    const m = t.match(AR_TOKEN);
    if (m && !m[1] && parseAspect(m[2]).ok) return m[2].toLowerCase();
  }
  return "";
}

/* The search text with its ar: token set to `value` ("" removes it). Only the plain ar:
   tokens go; `-ar:` (a negation the owner typed) and every other word stay where they are. */
export function withAspect(query, value) {
  const kept = tokens(query).filter((t) => {
    const m = t.match(AR_TOKEN);
    return !(m && !m[1]);
  });
  const v = String(value == null ? "" : value).trim().toLowerCase();
  if (v) kept.push("ar:" + v);
  return kept.join(" ");
}

/* A message when the search holds an ar: token no value of which the server would take (it
   would search it as a word and find nothing, which reads as "no such pictures"). "" if fine. */
export function aspectError(query) {
  for (const t of tokens(query)) {
    const m = t.match(AR_TOKEN);
    if (m && m[2] !== "" && !parseAspect(m[2]).ok) return AR_ERROR;
  }
  return "";
}

/* SUGGESTIONS while typing. Looks only at the LAST token: `ar:` or `-ar:` plus whatever is typed
   of the value, or a bare start of the word ("a", "ar") -- then the values that continue it.
   Each is {token, hint}, the token being the full text to put in that token's place. */
export function aspectSuggestions(query) {
  const q = String(query == null ? "" : query);
  if (!q || /\s$/.test(q)) return [];
  const last = tokens(q).pop() || "";
  const neg = last.startsWith("-") ? "-" : "";
  const body = neg ? last.slice(1) : last;
  const low = body.toLowerCase();
  let typed;
  if (low.startsWith("ar:")) typed = low.slice(3);
  else if (low.startsWith("aspect:")) return [];
  else if (low.length >= 2 && "ar:".startsWith(low)) typed = "";      // "ar" -> offer the values
  else return [];
  const all = ASPECT_CHOICES.map((c) => ({ value: c.value, hint: c.hint }))
    .concat(COMMON_SHAPES.map((s) => ({ value: s, hint: "within 3%" })));
  return all
    .filter((c) => c.value.startsWith(typed) && c.value !== typed)
    .slice(0, 8)
    .map((c) => ({ token: neg + "ar:" + c.value, hint: c.hint }));
}

/* Put a chosen suggestion in place of the last token. */
export function applySuggestion(query, token) {
  const q = String(query == null ? "" : query);
  const parts = tokens(q);
  parts.pop();
  parts.push(token);
  return parts.join(" ") + " ";
}

/* ---- the label on a card ---- */

/* The shapes a card names, with the ratio each stands for. The design page's list, plus the
   generator's newer shapes (5:4, 2:1, 21:9, 4:1) so a picture made at one is named for it. */
const KNOWN = [
  [1, "1:1"], [3 / 4, "3:4"], [4 / 3, "4:3"], [2 / 3, "2:3"], [3 / 2, "3:2"],
  [9 / 16, "9:16"], [16 / 9, "16:9"], [4 / 5, "4:5"], [5 / 4, "5:4"],
  [1 / 2, "1:2"], [2, "2:1"], [9 / 21, "9:21"], [21 / 9, "21:9"], [1 / 4, "1:4"], [4, "4:1"],
  [0.596, "3:5"], [1.91, "1.91:1"], [0.684, "9:13"],
];

/* The name of a picture's shape ("3:2"), the nearest known shape within 6 percent, else its
   ratio ("1.37:1"). "" when it has no size. */
export function ratioLabel(w, h) {
  const W = parseFloat(w), H = parseFloat(h);
  if (!(W > 0) || !(H > 0)) return "";
  const r = W / H;
  let best = KNOWN[0];
  for (const k of KNOWN) if (Math.abs(k[0] - r) < Math.abs(best[0] - r)) best = k;
  if (Math.abs(best[0] - r) / best[0] <= 0.06) return best[1];
  return r.toFixed(2) + ":1";
}

/* ---- the operator chips ---- */

/* The chip row under the search: one tap adds an operator to the search text, a second removes
   it. The design page's row, less its two sample-library chips (a tag and a 3:4 shape that only
   exist in its 24 stand-in pictures) and plus Loom renders. */
export const OPERATOR_CHIPS = ["ar:tall", "ar:wide", "ar:square", "★4+", "keeper", "-reject", "type:video", "type:loom"];

/* Is `token` in the search as a whole word? */
export function hasToken(query, token) {
  return tokens(query).some((t) => t.toLowerCase() === String(token).toLowerCase());
}

/* The search with `token` toggled. An ar: chip replaces any other ar: one (a picture has one
   shape), so tall and wide can never be asked for together and match nothing. */
export function toggleToken(query, token) {
  const t = String(token);
  if (hasToken(query, t)) return tokens(query).filter((x) => x.toLowerCase() !== t.toLowerCase()).join(" ");
  const m = t.match(/^ar:(.+)$/i);
  return (m ? withAspect(query, m[1]) : tokens(query).concat(t).join(" "));
}
