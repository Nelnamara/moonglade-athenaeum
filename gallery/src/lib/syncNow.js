/* "Sync now" for the phone's pull to refresh (Session Q, Q6): the SAME whitelisted Panel job the
   Control tab's Maintenance section and the desktop Panel's "Sync now" button run -- POST
   /api/panel/run {action: "sync"} -- followed by the SAME status poll they read (GET
   /api/panel/status). Nothing new on the server, and nothing here can send a generation: the action
   is a key on the server's whitelist, never argv, and the whole job is a read of the owner's own PixAI
   history into the local catalog.

   Pure with its transport injected, so loom/test/phone-sync.test.js runs every ending -- done, joined,
   failed, timed out, refused -- with no network and no clock.

   Never throws and never retries: one start request, then a bounded poll. A start that the server
   refuses because a job is ALREADY running is not an error to the person who pulled -- the library is
   being synced, which is what they asked for -- so it joins that job and waits for it (state "busy"
   only when the wait ran out). One flaky status read is not the end of a running job: it is skipped and
   the poll goes on until the ceiling. */

export const SYNC_ACTION = "sync";
export const POLL_MS = 1500;
export const MAX_WAIT_MS = 5 * 60 * 1000;        // a pull waits at most this long, then hands over

const sleepReal = (ms) => new Promise((r) => setTimeout(r, ms));

/* The server's job-slot statuses: idle, running, done, done_with_errors, failed, cancelled. */
const OK_ENDINGS = new Set(["done", "done_with_errors", "idle"]);

/* api: {post(path, body) -> Promise<answer>, get(path) -> Promise<answer>} (the gallery's apiPost /
   apiGet, which already turn every failure into an {error} answer).
   Resolves {state: "done" | "failed" | "busy" | "timeout" | "error", joined, error?}. */
export async function syncNow(api, opts) {
  const o = opts || {};
  const action = o.action || SYNC_ACTION;
  const sleep = o.sleep || sleepReal;
  const now = o.now || (() => Date.now());
  const pollMs = o.pollMs || POLL_MS;
  const maxMs = o.maxMs || MAX_WAIT_MS;

  const started = await api.post("/api/panel/run", { action });
  let joined = false;
  if (started && started.error) {
    if (started.http_status === 409 && /already running/i.test(String(started.error))) joined = true;
    else return { state: "error", joined: false, error: String(started.error) };
  }

  const t0 = now();
  for (;;) {
    if (now() - t0 > maxMs) return { state: joined ? "busy" : "timeout", joined };
    await sleep(pollMs);
    const st = await api.get("/api/panel/status");
    if (!st || st.error || st.status === "running") continue;
    if (OK_ENDINGS.has(st.status)) return { state: "done", joined };
    if (st.status === "cancelled") return { state: "failed", joined, error: "it was stopped" };
    return { state: "failed", joined, error: "" };
  }
}
