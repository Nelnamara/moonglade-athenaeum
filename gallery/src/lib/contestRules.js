/* ONE place that turns a contest rule into the line the detail screens print, so the
   desktop and phone details cannot drift apart again (#94).

   PixAI's contest rules are {type, <something>_ids: [...]}. Three kinds are known:
     required_model_ids  -> model_ids   (link: pixai.art/model/<id>)
     required_lora_ids   -> lora_ids    (link: pixai.art/model/<id>)
     required_recipe_ids -> recipe_ids  (link: pixai.art/recipes/<id>)
   Anything else is shown under its own humanized name with NO link: PixAI can add a
   kind tomorrow, and an unknown kind must never be counted as models (that is exactly
   how a recipe rule once read "0 required models"). */

const KNOWN = {
  required_model_ids: { kind: "model", key: "model_ids", base: "https://pixai.art/model/" },
  required_lora_ids: { kind: "LoRA", key: "lora_ids", base: "https://pixai.art/model/" },
  required_recipe_ids: { kind: "recipe", key: "recipe_ids", base: "https://pixai.art/recipes/" },
};

/* The line under the contest lists when PixAI's board is longer than the newest
   `limit` contests this app reads (/api/contests -> board). null when the board was
   read whole. `fmt` is the thousands formatter from hooks/useContests.js. */
export function ceilingNotice(board, fmt) {
  if (!board || !board.truncated) return null;
  const limit = Number(board.limit) || 0;
  const total = Number(board.total_count) || 0;
  if (total > 0) {
    return "The newest " + fmt(limit) + " of PixAI's " + fmt(total)
      + " contests are shown; older ones are not read.";
  }
  return "The oldest contests on PixAI's board are not shown: this app reads only the newest "
    + fmt(limit) + ".";
}

const asIds =(v) => (Array.isArray(v) ? v : []);

/* r = one rule object. Returns { kind, ids, href } where href is (id) => url | null. */
export function ruleLine(r) {
  const rule = r && typeof r === "object" ? r : {};
  const type = typeof rule.type === "string" ? rule.type : "";
  const known = Object.prototype.hasOwnProperty.call(KNOWN, type) ? KNOWN[type] : null;
  if (known) {
    return {
      kind: known.kind,
      ids: asIds(rule[known.key]),
      href: (id) => known.base + encodeURIComponent(String(id)),
    };
  }
  // Unknown kind: humanize the type the way the vote-type label does, take the first
  // array under a "*_ids" key, and build no link (no guess).
  const kind = type.replace(/^required_/, "").replace(/_ids$/, "").replace(/_/g, " ") || "item";
  const key = Object.keys(rule).find((k) => /_ids$/.test(k) && Array.isArray(rule[k]));
  return { kind, ids: key ? rule[key] : [], href: () => null };
}

/* THE CARD'S "HAVE YOU USED IT" LINE (2026-11-18). `statuses` is one contest's answer from
   /api/contests/qualify: per rule {kind, need, used, unknown} (moonglade/contest_qualify.py
   says what "used" can mean -- a picture in this library made with that model or LoRA, any
   version). An unknown is never written as "not used": a model whose versions could not be
   read says "couldn't check", and a recipe -- recipes are not recorded per picture -- says so.
   Returns the line, or null when the contest requires nothing. */
const plural = (kind, n) => (n === 1 ? kind : kind + "s");

export function qualifyLine(statuses) {
  const parts = [];
  for (const s of Array.isArray(statuses) ? statuses : []) {
    if (!s || typeof s !== "object") continue;
    const need = Number(s.need) || 0;
    const used = Number(s.used) || 0;
    const unknown = Number(s.unknown) || 0;
    const kind = typeof s.kind === "string" && s.kind ? s.kind : "item";
    if (need <= 0) continue;
    const label = "Required " + plural(kind, need) + ": ";
    if (kind === "recipe" || kind === "item") {
      parts.push(label + "not recorded here");
    } else if (used >= need) {
      parts.push(label + (need === 1 ? "used ✓" : "all " + need + " used ✓"));
    } else if (unknown > 0 && used === 0) {
      parts.push(label + "couldn't check");
    } else if (used === 0) {
      parts.push(label + "not used yet");
    } else {
      parts.push(label + used + " of " + need + " used" + (unknown ? ", " + unknown + " unchecked" : ""));
    }
  }
  return parts.length ? parts.join(" · ") : null;
}
