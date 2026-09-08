import { test, describe } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "path";

/* Owner ruling 2026-09-07, verbatim: "I often have things going from the app and website, so
   the generations I start on the website I would like to see on the app with the usual
   spinner."

   The server side of that is a real Activity row for a pixai.art run, written off the live
   taskUpdated stream (moonglade_gallery.py's _website_job_seen; tests/test_watch.py). This
   file is the window's half, and the whole rule it has to encode is a NEGATIVE one: a website
   run must be INDISTINGUISHABLE from an app run in the Activity window except for one small
   source mark. Same row component, same queued/running/done branches, same Nel spinner, same
   thumbnail, same inline detail -- so what is pinned here is (1) the mark exists and is
   gated on the source the server actually writes, and (2) nothing about the row's existing
   states was forked to accommodate it.

   Source-text pins, the same technique the sibling notify tests use (mg-notify-queue-phase,
   mg-notify-label-tense): the component is React with no harness that can render it here, and
   the rules live in single expressions, so pinning the expression IS pinning the behaviour. */
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const row = readFileSync(
  path.join(__dirname, "../../gallery/src/notify/ActivityRow.jsx"), "utf8");
const css = readFileSync(
  path.join(__dirname, "../../gallery/src/styles/notify.css"), "utf8");
const server = readFileSync(
  path.join(__dirname, "../../moonglade_gallery.py"), "utf8");

describe("a website run is marked as one, and marked nowhere else", () => {
  test("the row shows a 'website' mark when the job's source is pixai", () => {
    assert.match(row, /\{j\.source === "pixai" \? \(\s*<span className="at-src"[^>]*>website<\/span>\s*\) : null\}/,
      "the source mark is gone, no longer gated on source 'pixai', or no longer says " +
      "'website' -- without it a website run and an app run are the same row, and the owner " +
      "cannot tell where a generation came from");
  });

  test("the mark is gated on the value the SERVER actually writes", () => {
    // The two halves of this feature are in different languages and different files, and the
    // string is the only thing joining them. A rename on either side would silently stop the
    // mark rendering with no test failing anywhere else.
    assert.match(server, /_WEBSITE_JOB_SOURCE = "pixai"/,
      "the server's website-run source value changed -- the row's `j.source === \"pixai\"` " +
      "gate now matches nothing, so the mark would never render again");
    // ...and the app's own rows keep the other value, or every dock run would wear the mark.
    assert.match(server, /source=body\.get\("source"\) or "web"/,
      "the app's own /api/jobs registrations no longer default to source 'web'");
  });

  test("it appears once, on the sub-line, beside the kind -- not as a second row state", () => {
    assert.equal(row.split("at-src").length, 2,
      "at-src appears more than once -- the mark must be the single guarded span, not a " +
      "modifier smeared over the row");
    const sub = row.match(/<div className="at-sub">[\s\S]*?<\/div>/);
    assert.ok(sub, "the .at-sub line is gone");
    assert.match(sub[0], /at-kind[\s\S]*at-src/,
      "the mark must sit on the existing sub-line after the kind label, where at-phase and " +
      "at-when already live -- not in the label, the icon slot or a new line of its own");
  });

  test("a job with no source, or the app's own, gets no mark at all", () => {
    // Encoded as strict equality against one value: panel / cli / delete / import jobs carry
    // no source field, and app generations carry "web". A truthiness or !== check would
    // brand one or both.
    assert.doesNotMatch(row, /j\.source \?/,
      "a truthiness check on j.source would mark every job that carries any source, " +
      "including the app's own 'web' rows");
    assert.doesNotMatch(row, /j\.source !== /,
      "an inverted check would mark every job that is NOT a website run -- the whole roster");
  });
});

describe("everything else about the row is the app run's, unchanged", () => {
  test("a running website job draws the SAME Nel spinner an app run draws", () => {
    // There is exactly one spinner branch and it is reached by status alone -- it knows
    // nothing about source, which is what makes "the usual spinner" true rather than a
    // lookalike drawn for this case.
    assert.match(row,
      /<span className=\{"at-spin" \+ \(queued \? " at-queued" : ""\)\}>\s*<img className="at-nel" src="\/branding\/nel_spinner\.png"/,
      "the running icon is no longer the shared .at-spin Nel spinner");
    const spin = row.match(/<span className=\{"at-spin"[\s\S]*?<\/span>/)[0];
    assert.doesNotMatch(spin, /source/,
      "the spinner branch consults the job's source -- a website run would then render a " +
      "different spinner from an app run, which is precisely what the ruling forbids");
  });

  test("queued still means queued, for a website run as for any other", () => {
    // The server writes started:false for a `waiting` frame and started:true for `running`
    // (moonglade_gallery.py's _website_job_seen) exactly so this untouched guard applies.
    assert.match(row, /const queued = st === "running" && j\.started === false;/,
      "the queued gate changed -- a website run's waiting phase would stop reading as queued");
    assert.match(server, /_WEBSITE_QUEUED_STATUSES = \("waiting", "pending", "queued"\)/,
      "the server no longer maps a pre-dispatch status onto started:false, so a queued " +
      "website run would show as actively rendering");
  });

  test("the pictures still land in the row -- one thumbnail rule, for every source", () => {
    // "then done, with its pictures, once the mirror has landed them": the thumbnail comes
    // from media_ids, which the mirror receipt writes onto the website row through
    // _log_mirrored_media exactly as it does for an app run.
    assert.match(row, /const mid = \(j\.media_ids \|\| \[\]\)\[0\] \|\| "";/,
      "the thumbnail no longer comes from media_ids -- a mirrored website run would show " +
      "as done with nothing to look at");
    assert.match(row, /\{st === "done" && mid \? \(/,
      "the done-with-thumbnail branch is gone or has grown a source condition");
  });

  test("the icon, detail and dismiss branches never consult the source", () => {
    // One source reference in the whole component: the mark itself. Anything else means a
    // website run has started to behave differently somewhere.
    assert.equal((row.match(/j\.source/g) || []).length, 1,
      "j.source is read somewhere beyond the one mark -- a website run is diverging from an " +
      "app run in behaviour, not just in labelling");
  });
});

describe("the mark is styled as a source, not as a state", () => {
  test("it borrows the phase pill's quiet shape rather than inventing a look", () => {
    assert.match(css, /\.at-sub \.at-src\{/, "no style for the website source mark");
    const mark = css.match(/\.at-sub \.at-src\{[^}]*\}/)[0];
    assert.match(mark, /border-radius:999px/,
      "the mark should be the same quiet pill .at-phase already is -- no new visual language");
    assert.doesNotMatch(mark, /--peach|--red|--yellow/,
      "the mark uses a warning colour, so every website run would look like a problem: " + mark);
  });

  test("it rides the shared stylesheet, so both shells show it identically", () => {
    // gallery/src/styles/notify.css is in BOTH hosts' bundles; the phone reads the same store
    // and renders the same component. If the Loom shell ever restyles .at-* the two drift.
    const shell = server.match(
      /_LOOM_SHELL = r"""[\s\S]*?"""(?:\s*\+\s*[A-Za-z_]\w*\s*\+\s*r"""[\s\S]*?""")*/);
    assert.ok(shell, "could not extract _LOOM_SHELL from moonglade_gallery.py");
    assert.doesNotMatch(shell[0], /\.at-src/,
      "the Loom shell has started styling the source mark -- it would then render " +
      "differently on /loom than in the gallery");
  });
});

describe("the completion toast follows the app's own generate rule", () => {
  test("nothing in the toast path singles a website run out", () => {
    // "these are his own runs": a website run's row is type 'generate', so jobsStore's
    // existing non-terminal -> terminal transition toasts it exactly like a dock run. The
    // two type-based abstentions there are claim and update, and neither may grow a third.
    const store = readFileSync(
      path.join(__dirname, "../../gallery/src/notify/jobsStore.js"), "utf8");
    assert.doesNotMatch(store, /source/,
      "the toast path has started reading a job's source -- a website run must toast on the " +
      "same rule as any other generation the owner started");
    assert.match(store, /if \(j\.type === "claim"\)/);
    assert.match(store, /if \(j\.type === "update" && st === "done"\)/);
    assert.equal((store.match(/j\.type === /g) || []).length, 2,
      "a third type-based toast abstention appeared -- if it is 'generate' or a website run, " +
      "the owner's own runs just went silent");
  });
});
