/* THE PER-ACCOUNT PREFERENCES STORE -- the store half, and it imports NOTHING on purpose.

   Same split as swrStore.js / swrCache.js: what is worth pinning here is not React's
   behaviour but the store's -- one load shared by every subscriber, an optimistic write
   that shows at once, and a rollback that removes exactly the failed change and nothing
   else. Extracted, each of those is a plain assertion a node test can make with a fake
   transport and no renderer, DOM or fetch (loom/test/account-prefs-store.test.js).
   hooks/useAccountPrefs.js is the React-facing half: it builds the ONE store for the page
   on api.js's apiGet/apiPost and adds the hook.

   THE SERVER SIDE is GET/POST /api/account/prefs (moonglade_gallery.py, LOGIN tier,
   explicit-token CSRF): one flat {key: JSON value} document per signed-in account, keys
   lowercase dotted names ("guide.library", "seen.whatsnew"), a value capped at 64 KB of
   JSON and the document at 1 MB. The server is the authority on all of that; the key
   check below only saves a round trip for a key that can never be accepted.

   THE MODEL -- a confirmed base plus a pending overlay:
     base     the last document the SERVER sent (a load, or any write's answer -- every
              POST answers with the whole updated document)
     pending  the writes sent or queued but not yet answered, in order
     prefs    base with pending applied on top -- what every reader sees
   A write joins `pending` at once (the optimistic update) and leaves it when its answer
   arrives: on success `base` becomes the server's document, on failure nothing else
   changes -- so the failed change simply stops being applied. That IS the rollback, and it
   is correct even with several writes in flight to the same key: a later pending write
   stays applied, where "restore the old value" would have clobbered it.

   ONE QUEUE. The load and every write run one at a time, in call order, so each answer
   reflects every request before it and an older answer can never land on top of a newer
   one. The first write waits behind the load, which is also where the transport picks up
   the CSRF token it sends.

   WHAT COMES BACK IS READ-ONLY: `prefs` shares its values with `base` and the pending
   writes. Build a new value and set() it; never mutate one you read. */

export const PREF_KEY_RE = /^[a-z][a-z0-9_-]*(?:\.[a-z0-9][a-z0-9_-]*)*$/;
export const PREF_KEY_MAX = 64;

const _isPlainObject = (d) => !!d && typeof d === "object" && !Array.isArray(d);
const _has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

/** A plain sentence saying why `key` can never be a preference key, or "" if it can. */
export function prefKeyProblem(key) {
  if (typeof key !== "string" || !key) return "Preference keys must be non-empty strings.";
  if (key.length > PREF_KEY_MAX) return "Preference keys are at most " + PREF_KEY_MAX + " characters.";
  if (!PREF_KEY_RE.test(key)) {
    return "'" + key + "' is not a valid preference key: use lowercase dotted names like guide.library.";
  }
  return "";
}

/** `base` with each pending op applied in order. Never mutates `base`. */
export function applyOps(base, ops) {
  const out = { ...base };
  for (const op of ops) {
    for (const k of Object.keys(op.set)) out[k] = op.set[k];
    for (const k of op.unset) delete out[k];
  }
  return out;
}

/** prefs[key] when the key is present (a stored null included), else `fallback`. */
export function readPref(prefs, key, fallback) {
  return prefs && _has(prefs, key) ? prefs[key] : fallback;
}

/* `value` exactly as the server will store it (Dates become strings, a NaN inside an array
   becomes null), or undefined when it is not JSON at all -- a function, a symbol, a
   BigInt, a cycle, or undefined itself. Normalising first keeps the optimistic value equal
   to what the server echoes back, so the swap from overlay to base changes nothing. */
function _jsonValue(value) {
  let enc;
  try { enc = JSON.stringify(value); } catch { return undefined; }
  return enc === undefined ? undefined : JSON.parse(enc);
}

/* `load()` resolves to the GET answer ({prefs} or {error}); `save(patch)` sends
   {set, unset} and resolves to the POST answer ({prefs} or {error}). api.js's calls never
   throw, but a transport that does is treated as an {error} too. */
export function createPrefsStore({ load, save }) {
  let base = {};
  let pending = [];
  let status = "idle";          // idle | loading | ready | error
  let error = "";
  let loadRun = null;           // the queued/in-flight load, until it settles
  let queue = Promise.resolve();
  let snap = { status, error, prefs: base };
  const subs = new Set();

  function publish() {
    snap = { status, error, prefs: applyOps(base, pending) };
    for (const fn of [...subs]) {
      try { fn(); } catch { /* one bad subscriber must not starve the rest */ }
    }
  }

  function enqueue(job) {
    const run = queue.then(job);
    queue = run.then(() => undefined, () => undefined);
    return run;
  }

  /* Loads once for the page. Another call while the load is queued or in flight shares
     it; a call after it FAILED tries again; a call after it succeeded is a no-op. */
  function ensureLoaded() {
    if (status === "ready") return Promise.resolve(true);
    if (loadRun) return loadRun;
    status = "loading";
    error = "";
    publish();
    loadRun = enqueue(async () => {
      let d;
      try { d = await load(); } catch (e) { d = { error: "network error: " + ((e && e.message) || "unreachable") }; }
      loadRun = null;
      if (status === "ready") return true;      // a write's answer already brought the document
      if (d && !d.error && _isPlainObject(d.prefs)) {
        base = d.prefs;
        status = "ready";
        error = "";
      } else {
        status = "error";
        error = (d && d.error) || "could not load preferences";
      }
      publish();
      return status === "ready";
    });
    return loadRun;
  }

  function write(setObj, unsetList) {
    const op = { set: setObj, unset: unsetList };
    pending = [...pending, op];
    publish();
    ensureLoaded();
    return enqueue(async () => {
      let d;
      try { d = await save({ set: op.set, unset: op.unset }); } catch (e) { d = { error: "network error: " + ((e && e.message) || "unreachable") }; }
      pending = pending.filter((o) => o !== op);
      if (d && !d.error && _isPlainObject(d.prefs)) {
        base = d.prefs;
        status = "ready";               // a write's answer is the whole document
        error = "";
        publish();
        return { ok: true };
      }
      publish();                        // the failed op left the overlay: rolled back
      return { error: (d && d.error) || "could not save preferences" };
    });
  }

  /** Optimistically set one key; resolves to {ok: true} or {error}. */
  function set(key, value) {
    const problem = prefKeyProblem(key);
    if (problem) return Promise.resolve({ error: problem });
    const v = _jsonValue(value);
    if (v === undefined) {
      return Promise.resolve({ error: "The value for '" + key + "' is not plain JSON (use unset to remove a key)." });
    }
    return write({ [key]: v }, []);
  }

  /** Optimistically remove one key; resolves to {ok: true} or {error}. */
  function unset(key) {
    const problem = prefKeyProblem(key);
    if (problem) return Promise.resolve({ error: problem });
    return write({}, [key]);
  }

  return {
    ensureLoaded,
    set,
    unset,
    get: (key, fallback) => readPref(snap.prefs, key, fallback),
    getSnapshot: () => snap,
    subscribe(fn) {
      subs.add(fn);
      return () => { subs.delete(fn); };
    },
  };
}
