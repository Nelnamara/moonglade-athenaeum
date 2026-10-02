/* THE HONORS CARD (Session O, O6): a 1200 x 630 picture of where the account stands, drawn on a
   canvas on THIS device. This file is the pure half -- what the card says (honorsCardModel) and
   how it is laid out (drawHonorsCard, which only makes calls on a 2D context it is handed) -- so
   loom/test/folio-honors-card.test.js can hold both with a fake context. The browser half
   (fetching the badge art, making the canvas, Save / Copy / Share) is honorsCardBrowser.js.

   WHAT IT SHOWS: the name and the mark, the points, the completion percentage (completionOf:
   ladders + milestones + masteries only), the feats as "N found", the Vigil, and the three
   rarest EARNED honors as their real badge art.

   FEATS LEAK NOTHING (Session G): the card is a thing people post, so it is the strictest
   surface of all. Feats reach it as one number and nothing else -- never a name, an id, a
   picture or a riddle; no found feat is among the three badges; an unfound feat is not in the
   payload at all. The three badges are chosen from honors that are earned AND not feat-like.
   The card carries nothing but the account's own name, its numbers and public badge art:
   nothing is uploaded anywhere. */

import { completionOf, isFeatLike } from "./completionistCore.js";

export const CARD_W = 1200;
export const CARD_H = 630;

const RANK = { common: 0, rare: 1, epic: 2, legendary: 3 };
const rank = (a) => (Object.prototype.hasOwnProperty.call(RANK, a.tier) ? RANK[a.tier] : -1);

/* The three rarest earned honors: by rarity (legendary first), then more points, then the one
   earned most recently, then the roster's own order. Feats of any kind are never candidates. */
export function rarestEarned(achievements, earnedAt, n = 3) {
  const list = Array.isArray(achievements) ? achievements : [];
  const at = earnedAt || {};
  const day = (a) => (typeof at[a.id] === "string" ? at[a.id] : "");
  return list
    .map((a, i) => ({ a, i }))
    .filter(({ a }) => a && a.earned && !isFeatLike(a) && rank(a) >= 0)
    .sort((x, y) => {
      if (rank(x.a) !== rank(y.a)) return rank(y.a) - rank(x.a);
      const px = Number(x.a.points) || 0, py = Number(y.a.points) || 0;
      if (px !== py) return py - px;
      const dx = day(x.a), dy = day(y.a);
      if (dx !== dy) return dx === "" ? 1 : dy === "" ? -1 : (dx < dy ? 1 : -1);
      return x.i - y.i;
    })
    .slice(0, n)
    .map(({ a }) => ({ id: a.id, name: String(a.name || ""), tier: a.tier }));
}

/* What the card says. `vigil` is the payload's {day, best} (or null). */
export function honorsCardModel({ user, achievements, earnedPoints, earnedAt, vigil, date } = {}) {
  const c = completionOf(achievements);
  const name = String(user || "").trim().slice(0, 40);
  const v = vigil && Number.isFinite(vigil.day) && vigil.day >= 1
    ? { day: vigil.day, best: Math.max(Number.isFinite(vigil.best) ? vigil.best : 0, vigil.day) } : null;
  return {
    name: name || "The Folio of Honors",
    points: Number.isFinite(Number(earnedPoints)) ? Math.max(0, Math.floor(Number(earnedPoints))) : 0,
    pct: c.pct,
    found: c.found,
    vigil: v,
    badges: rarestEarned(achievements, earnedAt, 3),
    date: String(date || ""),
  };
}

/* The line under the meter. Feats appear as "N found" and only once one has been found. */
export function standingLine(model) {
  const base = model.pct + "% complete";
  return model.found > 0
    ? base + "  ·  " + model.found.toLocaleString() + (model.found === 1 ? " feat found" : " feats found") : base;
}

export function vigilLine(model) {
  return model.vigil ? "Vigil  ·  day " + model.vigil.day + "  ·  best " + model.vigil.best : "";
}

/* A card's file name and share caption: the name and the numbers, nothing more. */
export const CARD_FILE = "honors-card.png";
export function shareText(model) {
  return model.name + " · " + model.points.toLocaleString() + " points · " + model.pct + "% of the Folio";
}

/* Wrap `text` into at most `maxLines` lines no wider than `maxW`, using the context's own
   measure; the last line is trimmed with an ellipsis when it still does not fit. */
export function wrapLines(ctx, text, maxW, maxLines) {
  const words = String(text || "").split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = "";
  for (const w of words) {
    const t = cur ? cur + " " + w : w;
    if (cur && ctx.measureText(t).width > maxW) { lines.push(cur); cur = w; } else cur = t;
  }
  if (cur) lines.push(cur);
  if (lines.length > maxLines) lines.length = maxLines;
  const last = lines.length - 1;
  if (last >= 0 && (ctx.measureText(lines[last]).width > maxW || words.join(" ").length > lines.join(" ").length)) {
    let s = lines[last];
    while (s.length > 1 && ctx.measureText(s + "…").width > maxW) s = s.slice(0, -1);
    lines[last] = s + "…";
  }
  return lines;
}

/* Draw the card. `assets`:
     palette  {base, mantle, text, subtext, overlay0, surface0, gold, lavender}  (the active
              skin's colours, read from the page's tokens by the browser half)
     tiers    {common, rare, epic, legendary}  (each rarity's colour)
     mark     an image, or null
     images   {[badge id]: an image or null}  (a badge whose art did not load is drawn as its
              rarity's swatch, so a missing file never leaves a hole)
   Every call is on `ctx`; nothing else is touched. */
export function drawHonorsCard(ctx, model, assets) {
  const W = CARD_W, H = CARD_H;
  const p = assets.palette, tiers = assets.tiers || {}, images = assets.images || {};
  const SERIF = "Georgia, 'Times New Roman', serif";
  const SANS = "ui-sans-serif, system-ui, 'Segoe UI', sans-serif";
  const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

  const bg = ctx.createLinearGradient(0, 0, W, H);
  bg.addColorStop(0, p.surface0);
  bg.addColorStop(1, p.mantle);
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = p.gold;
  ctx.globalAlpha = 0.55;
  ctx.lineWidth = 3;
  ctx.strokeRect(24, 24, W - 48, H - 48);
  ctx.globalAlpha = 1;

  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";
  ctx.fillStyle = p.overlay0;
  ctx.font = "600 20px " + MONO;
  ctx.fillText("THE FOLIO OF HONORS", 80, 110);

  // the mark and the name
  let nameX = 80;
  if (assets.mark) {
    ctx.drawImage(assets.mark, 78, 128, 84, 84);
    nameX = 182;
  }
  ctx.fillStyle = p.text;
  ctx.font = "italic 72px " + SERIF;
  const nameLines = wrapLines(ctx, model.name, 560 - (nameX - 80), 1);
  ctx.fillText(nameLines[0] || "", nameX, 196);

  ctx.fillStyle = p.gold;
  ctx.font = "58px " + SERIF;
  ctx.fillText(model.points.toLocaleString() + " points", 80, 300);

  // the completion meter (a floored percentage: 100 means everything is done)
  ctx.fillStyle = p.surface0;
  ctx.fillRect(80, 340, 520, 16);
  ctx.fillStyle = p.gold;
  ctx.fillRect(80, 340, (520 * Math.max(0, Math.min(100, model.pct))) / 100, 16);

  ctx.fillStyle = p.subtext;
  ctx.font = "26px " + SANS;
  ctx.fillText(standingLine(model), 80, 400);

  const vig = vigilLine(model);
  if (vig) {
    // a small drawn crescent in place of an emoji, so the card looks the same on every device
    ctx.fillStyle = p.lavender;
    ctx.beginPath();
    ctx.moveTo(92, 428);
    ctx.arc(92, 438, 10, -Math.PI / 2, Math.PI / 2, true);
    ctx.quadraticCurveTo(87, 438, 92, 428);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = p.subtext;
    ctx.font = "26px " + SANS;
    ctx.fillText(vig, 116, 446);
  }

  // the three rarest earned honors, as their real badge art
  model.badges.forEach((b, i) => {
    const x = 740 + i * 140, y = 190, s = 116;
    const col = tiers[b.tier] || p.lavender;
    ctx.fillStyle = col;
    ctx.globalAlpha = 0.16;
    ctx.fillRect(x, y, s, s);
    ctx.globalAlpha = 1;
    const img = images[b.id];
    if (img) {
      ctx.drawImage(img, x, y, s, s);
    } else {
      ctx.fillStyle = col;
      ctx.globalAlpha = 0.9;
      ctx.fillRect(x, y, s, s);
      ctx.globalAlpha = 1;
    }
    ctx.strokeStyle = col;
    ctx.lineWidth = 3;
    ctx.strokeRect(x, y, s, s);
    ctx.fillStyle = p.text;
    ctx.font = "700 16px " + SANS;
    wrapLines(ctx, b.name, s + 8, 2).forEach((ln, k) => ctx.fillText(ln, x, y + s + 26 + k * 20));
    ctx.fillStyle = p.overlay0;
    ctx.font = "13px " + MONO;
    ctx.fillText(String(b.tier || "").toUpperCase(), x, y + s + 74);
  });

  ctx.fillStyle = p.overlay0;
  ctx.font = "18px " + SANS;
  ctx.fillText("moonglade" + (model.date ? " · " + model.date : ""), 80, 560);
}
