/* The open-a-Contests-overlay sync handshake, as a pure function.

   It lives outside useContests.js -- and imports nothing -- for one reason: the defect it
   exists to prevent is an ORDERING defect, and ordering is exactly what a hook cannot be
   tested for in this repo's harness (there is no React test renderer; the notify suite
   tests plain modules for the same reason). Extracted, it is a promise chain any node test
   can drive with two fakes.

   THE DEFECT (2026-09-03, found by adversarial review): the token was fetched in one
   effect that wrote a ref, and the POST fired from a sibling effect that read that ref on
   the same mount. Effects run in order but the fetch is async, so the ref was ALWAYS still
   empty -- every Contests open POSTed an empty CSRF token, the server refused it 400, and
   the on-open sweep never ran once. The only trace was an error line reachable solely from
   the empty-entries state, which is why it survived a full review wave.

   So: the token is AWAITED, and a missing token means "do not call" rather than "call and
   find out". */

export const NO_TOKEN = "no-token";
export const REFUSED = "refused";
export const SKIPPED = "skipped";
export const WATCH = "watch";

/**
 * @param {() => Promise<string>} getToken  resolves the CSRF token ("" when unavailable)
 * @param {(token: string) => Promise<object>} post  POSTs /api/contest/sync with it
 * @returns {Promise<{outcome: string, error?: string}>}
 */
export async function syncOnOpen(getToken, post) {
  const token = await getToken();
  if (!token) return { outcome: NO_TOKEN };
  const d = await post(token);
  // A refusal is NOT a completed sync. It used to fall through the same branch as success
  // and quietly report the sweep as done.
  if (!d || d.error) return { outcome: REFUSED, error: (d && d.error) || "" };
  if (d.skipped === "recent") return { outcome: SKIPPED };
  return { outcome: WATCH };
}
