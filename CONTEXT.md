# CONTEXT.md — the project's domain vocabulary

The words this codebase uses for its own ideas, defined once. Glossary only: no status, no
plans, no arguments. **Why** a thing was decided the way it was lives in
`../moonglade-internal/DECISIONS.md`; how it works lives in the code and in
`../moonglade-internal/architecture.md`.

---

**Price transport** — `gallery/src/gen/priceRequest.js`, the one place any part of the app
asks `POST /api/price`. `requestPrice(payload, {timeoutMs, signal})` resolves `{response}` for
any parsed body — an HTTP-200 `{error}` is an *answer*, not a failure — and `{failed}` for a
transport failure, an abort or the timeout. That distinction is the whole reason it is not the
request module: `api.js`'s one error rule flattens both into `{error}`, and the spend gate reads
the difference. One POST per call, never a retry. The gallery's probe and the Loom's `priceBody`
both ride it.

**Price probe** — the one module every cost line rides to find out what a generation would
cost: `gallery/src/gen/priceProbeCore.js` (pure) plus `gallery/src/gen/usePriceProbe.js`
(the React hook that owns the debounce, the sequence guard, the verdict and the teardown
abort; the request itself belongs to the price transport). A host supplies a payload builder
and a `CostBadge` ref; it supplies everything else.

**Price identity (`priceKey`)** — the fingerprint of a payload, computed over every field
except the ones that never price (prompt, negative, seed; Edit skips `instruction` instead).
Two payloads with the same price identity are the same job as far as cost is concerned.

**Verdict** — what the probe currently knows, as `{settled, pricedKey, pendingTimer}`.
*Scheduled*: a re-price is queued but has not fired, so whatever is on the badge is
known-stale. *Fired*: the timer went off and the answer is not back. *Settled*: a real
answer — a price, a free card, a failed check, or an idle hint — was reached for
`pricedKey`. A submit control is live only when a settled verdict's key matches the payload
the click would send.

**Fail-closed-but-live** — the rule for a price check that could not be verified. The badge
turns red and says generating may spend, the verdict settles anyway, and the button stays
pressable: the app refuses to *imply* free, and equally refuses to strand the user behind a
dead control with no message.

**Short-circuit** — a refresh that returns without doing anything because the payload's price
identity already equals the settled one. What makes typing in a prompt free: no badge blank,
no disabled button, no `/api/price` call.

**Forced re-price** — a refresh that ignores the short-circuit. Used where the payload is
byte-identical but the verdict is stale anyway: right after a submit debited credits or
tickets, and when a badge remounts idle on returning to a tab.

**Idle hint** — the badge's "nothing to price yet" label ("Pick a source image to see the
cost."). It is a verdict, not a gap: it settles, so the host's own pre-submit refusal
message stays reachable instead of the control going quietly dead.

**Free card (kaisuuken)** — PixAI's prepaid generation ticket. A matching card is attached
automatically at submit and the generation costs 0 credits. A video card is a *book* of
tickets and a clip spends one per 5 seconds; holding fewer tickets than a job needs attaches
no card at all and charges the full price ("short").

**CostBadge host contract** — `gallery/src/components/CostBadge.jsx` never fetches. The host
pushes state in through its imperative handle — `setPrice(response)`, `setChecking()`,
`clear(hint)` — and the badge owns every state's wording and colour, so a displayed "free"
or "0 credits" can only ever mean a settled zero-cost result.

**Submit road** — `gallery/src/gen/submitTask.js`, the one function every gallery surface POSTs
a spend route through (`/api/generate`, `/api/edit`, `/api/fix`, `/api/enhance`, `/api/scene`,
`/api/loom/generate`). It owns the no-retry rule, the HTTP-200 `{error}` read, the `adjusted`
disclosure, and registration: its `Jobs.track` call is what puts a generation in the Activity
tray, so no host has to remember to.

**Poll cadence** — the tier table in `gallery/src/notify/pollCadence.js`: a task is asked about
every 3s, then every 20s past 20 minutes (`slow`), every 3 minutes past 90 minutes (`stale`),
and at 6 hours this tab stops asking (`stalled` — a statement about the tab, never a verdict on
the task). `cadenceFor(elapsedMs)` returns `{ms, tier}`; the tier is announced once, on entry.

**Generation request** — the one object a web create carries: the exact `parameters` dict
PixAI will receive, plus the few facts a submit needs that the dict itself does not hold
(the free-card flag, a Fix's `mediaId` and boxes). `core.build_request()` is the only thing
that makes one; `core.price()` and `core.submit()` are the only things that read one.

**Payload road** — the single path a drawer payload travels from JSON to PixAI: build the
request once, then either quote it or spend it, both reading the same `parameters` object.
There is one road for every mode (image, edit, fix, video, enhance), and the mode dispatch
lives in exactly one place.

**Library scan** — the one walk of the library folder: `moonglade_gallery.py`'s LIBRARY SCAN
section, `scan_library()` for the whole tree and `files_for()` for a single media id. It owns
what a walk skips (the `.part` temp files, the thumbnail and quarantine folders), which file
extensions count (`kinds`), and how a path becomes a bucket and a media id. A caller asks for
its own `kinds`/`exclude` instead of keeping a private copy of the rules; the caller-specific
rules that are about *files* rather than the shape of the tree — the zero-byte rule above all
— stay at the caller, which is why the scan reports each file's `size` and decides nothing
with it.

**Bucket** — which top-level folder of the library a file sits in, as one word: `images` (the
flat folder), `batches` (legacy batch folders), `month` (a `YYYY-MM/` folder or
`unknown-date/`), or `other` (anything else). `bucket_of()` is the only thing that decides it.
Buckets are how a duplicate is spotted (the same media id in more than one bucket) and how the
keeper is chosen when one is — most-organized wins.
**Media tools** — the one seam every ffmpeg and ffprobe invocation passes through: the
delimited `media_tools` section of `moonglade_backup.py`. It answers "is the binary
installed" (once, cached, per binary), supplies the no-window flag and the timeout, and
returns a **tool result** instead of raising. Video thumbnails, the faststart remux, the
frame handoff, clip duration, audio detection and the Loom export are all callers of it,
not re-implementations.

**Tool result** — what one media-tool invocation did: `ok`, the exit code, the captured
`stdout`/`stderr`, and `missing`. A non-zero exit is an *answer* (ffmpeg's ordinary way of
refusing a file), not an error — what it means is the caller's to say.

**Missing (a media tool)** — the binary is not installed. A distinct road from "it ran and
failed", so a caller can degrade deliberately rather than by accident; it is what lets a
missing ffprobe cost the Loom export its audio track without costing it the file.

**Frame primitive** — `extract_last_frame()`: the one piece of code in the app that pulls a
still out of a clip. General, not last-frame-only — an explicit timestamp of `0.0` yields
the *first* frame, and a trim's out-point yields the frame the cut actually ends on. Nothing
else extracts frames.
**Route tier** — the permission level a web route requires, declared on the route itself as
`@tier(PUBLIC)`, `@tier(LOGIN)` or `@tier(LOCALHOST)` (a split route writes
`@tier(LOGIN, POST=LOCALHOST)`). *Public* is reachable with no session at all; *login* is any
signed-in session, local or LAN; *localhost* is a signed-in session whose request also came
from the serving machine's own loopback address. One `before_request` gate reads the
declaration off the endpoint and enforces all three, and an app whose routes do not all
declare one refuses to start.
**Catalog verb** — one named question the app asks of `catalog.db`, living beside the other
catalog helpers in `moonglade_gallery.py`'s CATALOG VERBS section: `task_media`, `lineage`,
`publish_state`, `history_page`, `delete_preview_rows` and the rest. A verb takes a `db_path`,
holds the SQL, and returns **plain data** — dicts, lists, ints, never a `sqlite3.Row` and never a
live connection. What the data becomes — a JSON payload, a `/thumbs/<id>.jpg` URL, a truncated
caption — is the caller's; a web route asks a verb and jsonifies the answer, and holds no SQL of
its own. `tests/test_catalog_verbs.py` walks `create_app`'s handlers and fails the suite over a
SELECT that reappears in one.

**The catalog road** — the two things opening `catalog.db` used to be at once, now separated.
`catalog(db_path)` is a context manager that opens a `sqlite3.Row` connection and closes it,
running no schema statements at all; `migrate(db_path)` runs the `_MIGRATIONS` list, idempotently,
and is memoized per process per resolved path. **Lazy safety** is the rule that survived the split:
the FIRST `catalog()` for a path in a process migrates it, so no entry point — the web app, the CLI,
the MCP server, the similarity index, a test on a fresh tmp database — has to remember to migrate,
and the ones that call `migrate()` explicitly do it to say so out loud rather than to make it work.

**Request module** — `gallery/src/api.js`, the one place under `gallery/src` where a `fetch`,
a body parse and an error decision live. `apiGet` / `apiPost` / `apiUpload` all answer
`data | {error}` and never throw, on ONE rule: the body's `{error}` is authoritative whatever
the HTTP status was (this app's spend routes refuse with HTTP 200 `{error}`), a non-2xx with
no body error becomes `{error: "<status> <statusText>"}`, and a transport failure becomes
`{error: "network error: …"}`. Three files keep their own `fetch` by name, each because its
contract needs a distinction that rule deliberately collapses.

**PixAI client** — `PixAIClient`, in the delimited `pixai_client` section of
`moonglade_backup.py`: the one seam every byte this app exchanges with PixAI leaves through.
Five verbs — `query` / `mutate` (the ad-hoc GraphQL POST), `persisted` (the persisted-hash
GET the personal-history operations ride), `rest_get` / `rest_post` (the oRPC `/v2` road) —
plus `for_create()`, which picks the browser-JWT mirror session over the API key when the
Mirror toggle is on, and the identity a caller can ask for (`user_id`, `auth_kind`,
`session`). `_make_session()` returns one; the five module-level primitives
(`gql`, `gql_adhoc`, `gql_mutate`, `_rest_get`, `_rest_post`) are thin delegates onto it, so
every function that still takes a `session` positionally keeps working. **`mutate` has no
`retries` parameter** — not defaulted to zero, absent — which is where the spend rule lives
now: a caller cannot ask for the value that pays twice.

**FakePixAI** — `tests/fake_pixai.py`, the second implementation of that same interface:
canned answers instead of a socket. It is keyed by GraphQL operation name (an anonymous
document by its first root field) and by REST path, it records every call, and it **refuses
anything nobody registered**, by name. That refusal is what makes the suite offline by
construction rather than by habit; it is an `AssertionError`, deliberately not a
`PixAIError`, so the app's many fail-soft handlers cannot swallow a missing registration into
a pretend empty answer. The `pixai` fixture installs one as what `_make_session()` — and so
the gallery's `_gen_session()` — hands out.

