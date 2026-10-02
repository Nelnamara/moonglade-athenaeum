/* Contest wins, VERIFIED (Session L, item L3) -- the words and states the surfaces draw,
   as a pure module (no React, no fetch, no clock of its own) so node can test every state.

   What the server tells the rows (GET /api/contest/mine, per contest):
     won        true only when PixAI's own winners list carried an entry of this account with an
                integer tier rank (verified). The old author-only flag is `unverified_legacy`.
     wins[]     {artwork_id, tier, prize_amount, label ("Tier 2, 200,000 credits"), how, receipt_url}
     check      {state: none|pending|settled|expired, last_at, next_at, until, decided}  (epoch s)

   WORDING RULE: a placement is a TIER plus the prize, never a numbered place. PixAI's `rank` is
   the prize tier (1, 2 or 3, shared by every winner in that tier), so "2ND PLACE" would be a
   claim about a position nobody has. Peach marks a refused or failed check; never ruby. */

const nf = (n) => Number(n || 0).toLocaleString("en-US");

/** "Tier 2, 200,000 credits" -- or "Tier 2" when the prize is unknown. */
export function tierLabel(tier, prize) {
  const t = Number(tier) || 0;
  const base = t > 0 ? "Tier " + t : "Tier";
  const p = Number(prize) || 0;
  return p > 0 ? base + ", " + nf(p) + " credits" : base;
}

/** The pill on a won row: "TIER 2". */
export const tierPill = (tier) => ((Number(tier) || 0) > 0 ? "TIER " + Number(tier) : "TIER");

/** The best (lowest-numbered) verified win of a row, or null. */
export function bestWin(row) {
  const w = (row && row.wins) || [];
  if (!w.length) return null;
  return w.slice().sort((a, b) => (a.tier || 99) - (b.tier || 99))[0];
}

/** Local YYYY-MM-DD of an epoch-seconds instant ("" when there is none). */
export function dayOfTs(ts) {
  const n = Number(ts) || 0;
  if (n <= 0) return "";
  const d = new Date(n * 1000);
  const pad = (x) => String(x).padStart(2, "0");
  return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
}

const resultMs = (row) => {
  const t = Date.parse(String((row && row.result_at) || ""));
  return Number.isNaN(t) ? null : t;
};

/** Has the contest's result time passed? */
export function isDecided(row, now) {
  const t = resultMs(row);
  return t !== null && t <= (now == null ? Date.now() : now);
}

/** The status pill of a My-entries row: {cls, text, sub}. Derived, never stored.
    running -> awaiting results -> (verified win | checking | not placed). A contest is only
    "not placed" once the daily check has actually finished with a decided list; before that
    the row says the app is still checking, because an empty list is undecided, not lost. */
export function rowStatus(row, now) {
  const r = row || {};
  if (r.active) return { cls: "", text: "RUNNING", sub: "" };
  if (!isDecided(r, now)) return { cls: "awaiting", text: "AWAITING RESULTS", sub: "" };
  const w = bestWin(r);
  if (r.won && w) return { cls: "won", text: "🏆 " + tierPill(w.tier), sub: tierLabel(w.tier, w.prize_amount) };
  const st = (r.check && r.check.state) || "none";
  if (st === "settled") return { cls: "quiet", text: "NOT PLACED", sub: "" };
  if (st === "expired") {
    return r.check && r.check.decided
      ? { cls: "quiet", text: "NOT PLACED", sub: "" }
      : { cls: "quiet", text: "NO RESULT FOUND", sub: "" };
  }
  return { cls: "awaiting", text: "CHECKING RESULTS", sub: "" };
}

/** The state line under the Check row: {tone, text}.
    tone: "ok" (verified) | "quiet" (not verified yet). Nothing here is ever "lost". */
export function stateLine(row, now) {
  const r = row || {};
  const w = bestWin(r);
  if (r.won && w) return { tone: "ok", text: "Verified · " + tierLabel(w.tier, w.prize_amount) };
  const c = r.check || {};
  const st = c.state || "none";
  if (st === "pending") {
    const until = dayOfTs(c.until);
    return { tone: "quiet", text: "Not verified yet · the app re-checks daily" + (until ? " until " + until : "") };
  }
  if (st === "settled") {
    return { tone: "quiet", text: "Not verified · the app has finished checking this contest" };
  }
  if (st === "expired") {
    return { tone: "quiet", text: "Not verified yet · the daily checks for this contest are over. Paste your link and press Check." };
  }
  return { tone: "quiet", text: "Not verified yet · the app checks daily once the results are out" };
}

/** What a Check answer looks like on screen: {tone, text, receipt}.
    verified -> "ok"; undecided (results not out) -> "quiet"; every refusal or failure -> "warn"
    (peach). The server's own sentence is the text. */
export function outcomeView(resp) {
  const d = resp || {};
  if (d.error) return { tone: "warn", text: String(d.error), receipt: "" };
  if (d.verified) {
    const w = (d.wins || [])[0];
    return {
      tone: "ok",
      text: "Verified" + (w ? " · " + (w.label || tierLabel(w.tier, w.prize_amount)) : ""),
      receipt: d.receipt_url || "",
    };
  }
  if (d.state === "undecided") return { tone: "quiet", text: String(d.message || ""), receipt: "" };
  return { tone: "warn", text: String(d.message || "That check did not verify a win."), receipt: "" };
}

/** The contests the picker offers: the ones this library has entries in, the unverified first
    (that is what the fallback is for), each with its title. */
export function contestOptions(rows) {
  return (rows || [])
    .map((r) => ({
      id: String(r.contest_id || ""),
      title: r.title || r.slug || String(r.contest_id || ""),
      won: !!r.won,
    }))
    .filter((o) => o.id)
    .sort((a, b) => (a.won === b.won ? a.title.localeCompare(b.title) : a.won ? 1 : -1));
}

/** The contest the picker starts on: the first whose results are out and that has no verified
    win (the one the fallback is most likely for), else the first there is. */
export function defaultContestId(rows, now) {
  const list = rows || [];
  const hit = list.find((r) => !r.active && isDecided(r, now) && !r.won) || list[0];
  return hit ? String(hit.contest_id || "") : "";
}

/** May the Check button fire? The pasted link is required (it is what gets kept as the
    receipt), and never twice at once. */
export function canCheck(url, busy) {
  if (busy) return false;
  return String(url || "").trim().length > 0;
}
