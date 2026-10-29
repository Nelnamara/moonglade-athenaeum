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
