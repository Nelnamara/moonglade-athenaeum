import { apiGet } from "../api.js";
import { sendAchEvent } from "../notify/achNonce.js";
import { beginBespokeMoment, check as achCheck, endBespokeMoment, whenClear } from "../notify/ach.js";
import { playMoment, skipMoment } from "./momentStore.js";
import { installTouchCode } from "./touchCode.js";

/* The key-sequence cast: the starfall moment. Moved out of App.jsx on 2026-09-26 so every
   shell can install it -- the desktop gallery and the phone (which has no arrow keys, so it
   also takes the code's touch form, touchCode.js). Installed once per shell; returns the
   teardown. Since the celebration-videos build it is a
   CLIP MOMENT (moments/ClipMoment.jsx) -- the owner's clip with the keycaps, the cast
   flare, the star rain and the toast laid over it exactly as its locked Design Handoff page
   lays them -- and this handler is only its trigger. What it keeps from the 2026-09-10
   rebuild is the part that was never about pixels: the sequence, the beacon, and the
   order of things around them.

   It is a BESPOKE MOMENT. For its whole life -- from before the earning beacon goes out,
   through the clip, to its end -- it owns the screen, and notify/ach.js HOLDS any newly
   earned celebration until it releases (beginBespokeMoment/endBespokeMoment). That is what
   makes THIS earn's standard achievement toast play AFTER the starfall rather than over it:
   on a first earn the celebration is not merely delayed, it has not been built yet.

   And the other direction, which arming alone cannot cover: anything ALREADY on screen when
   the code is entered is a layer the moment would paint UNDER (.ach-m2 is z-index 520 and
   the parade's chips 519/521, against the moment's 515/516). So the cast does not start on
   the keypress -- it starts from ach.js's whenClear() hook, which runs it at once when that
   layer is EMPTY and otherwise the instant the last thing on it has left the DOM. The arm
   happens inside that callback, so the cast is never the thing waiting and nothing is ever
   the thing painted over.

   WHICH FEAT is the roster's to say: the moment plays for the achievement whose object
   carries `moment === "starfall"` -- present once the beacon has earned it -- and that
   object brings the clip's URL and the toast's sealed line with it (moment_clip,
   moment_copy). No id is named here. A roster that has no such flag yet (an older pack)
   still gets the moment, in its no-video fallback.

   The cast FIRES that toast itself (achCheck() below, once the moment is requested).
   Nothing in the app polls achievements -- check() runs once per boot and after a
   generation -- so without that call the standard toast for a fresh cast would not arrive
   until the next page load. Its answer carries the same feat with its `moment`, and ach.js
   hands it to the moment host: the host JOINS the starfall already playing
   (moments/momentStore.js), so the owner sees one starfall, then the toast.

   Every exit below -- the moment ending, a failed beacon, an unmount BEFORE the beacon
   lands as well as after, and a beacon that never answers at all -- runs release() exactly
   once; a missed release would wedge the engine and silently swallow every later
   achievement. That is why release lives beside teardown in the effect's scope rather than
   inside onKey: teardown only exists once the moment has been requested, and the
   arm-to-beacon window is real time during which an unmount would otherwise have nothing
   to call.

   And why the WALL CLOCK is the last of those paths rather than the cleanup: apiGet/apiPost
   make a bare fetch (gallery/src/api.js -- no AbortController unless a caller asks for
   timeoutMs, and a network failure RESOLVES with {error} rather than rejecting), so a
   request that simply never settles never rejects and never resolves. The .catch below
   cannot see it, and the effect cleanup is unmount -- which the root App does not do. That
   leaves a silent /api/ach-event holding the engine above zero for the rest of the session.
   ARM_CEILING_MS closes it in the only way a hung promise can be closed, by giving the arm
   a ceiling in real time; a chain that answers after it has expired finds `released` and
   plays nothing, so a moment cannot appear minutes later over a page that moved on. (The
   moment has a ceiling of its own for a clip that never loads -- see ClipMoment.) */
export function installStarfallTrigger() {
  const seq = [38, 38, 40, 40, 37, 39, 37, 39, 66, 65];
  const ARM_CEILING_MS = 20000;            // see the note above: the failsafe for a fetch that never settles
  let pos = 0, busy = false;
  let gone = false;                        // the effect has been torn down
  let teardown = null;                     // the requested moment's teardown, once it exists
  let pendingRelease = null;               // ...and its release, from the instant it is ARMED
  const startCast = () => {
    if (gone) return;                      // unmounted while the cast waited for a clear layer
    // ARMED BEFORE THE BEACON, not after the moment is requested: the beacon is what earns
    // the feat, and a check() -- this cast's own, below, or one a finishing generation
    // fires -- can land while this promise chain is still in the air.
    beginBespokeMoment();
    let released = false;
    let armT = 0;                          // the wall-clock ceiling on the arm-to-beacon window
    const release = () => {
      if (released) return;
      released = true;
      clearTimeout(armT);
      if (pendingRelease === release) pendingRelease = null;
      teardown = null;
      busy = false;
      endBespokeMoment();                  // the held celebration plays now
    };
    pendingRelease = release;              // reachable from the effect cleanup, moment or no moment
    // The only path that can end a hung fetch. Generous on purpose -- it is a failsafe, not
    // a timeout policy: a slow-but-alive beacon must still get its cast, so the ceiling sits
    // far past any answer a local server plausibly takes, and expiring costs nothing but the
    // moment for that press (the feat itself was earned server-side by the beacon, or was
    // not sent at all).
    armT = setTimeout(() => { if (!teardown) release(); }, ARM_CEILING_MS);
    // The clip and the fallback's tracks are served under this feat's own unlock (the
    // unlock-split enforcement, 2026-08-13) and this beacon is what records it -- so the
    // moment waits for the beacon to land, or the very first trigger races its own unlock
    // and the clip 404s. The /api/achievements read that follows is unmarked on purpose:
    // it only wants the now-unmasked feat (its clip and copy); marking is check()'s job,
    // and doing it twice would consume `newly` before the toast is built.
    // Through sendAchEvent since 2026-09-07: the beacon carries this page's nonce and
    // adopts the next one (notify/achNonce.js), which is what let the route go back to
    // LOGIN so a phone can reach this too.
    sendAchEvent("konami")
      .then(() => apiGet("/api/achievements"))
      .then((data) => {
      // Answered after the ceiling expired: the arm is long gone, the engine has been
      // released and another cast may even have played. Play nothing.
      if (released) return;
      const feat = ((data && data.achievements) || [])
        .find((a) => a && a.moment === "starfall" && a.earned);
      const ended = playMoment(feat || { moment: "starfall" });
      teardown = () => { skipMoment(); release(); };
      // MARK-AND-TOAST for the earn that just happened, fired from INSIDE the moment: the
      // celebration it builds is parked by the hold above, and release() is what lets it
      // play -- after the starfall has ended.
      achCheck();
      ended.then(release, release);
    })
      .catch(() => { if (teardown) teardown(); else release(); });
  };
  const fire = () => {
    if (busy) return;
    busy = true;
    // NOT startCast() directly: see the note above. whenClear runs it now if the
    // celebration layer is empty, and otherwise as soon as the moment on screen has torn
    // down -- `busy` is already true, so re-entering the code while one waits does nothing.
    whenClear(startCast);
  };
  const onKey = (e) => {
    pos = e.keyCode === seq[pos] ? pos + 1 : (e.keyCode === seq[0] ? 1 : 0);
    if (pos !== seq.length) return;
    pos = 0;
    fire();
  };
  document.addEventListener("keydown", onKey);
  const offTouch = installTouchCode(fire);   // the code's touch form (touchCode.js)
  return () => {
    gone = true;
    document.removeEventListener("keydown", onKey);
    offTouch();
    if (teardown) teardown();              // unmounted mid-moment: end it, release
    else if (pendingRelease) pendingRelease();   // armed, beacon still in the air: release
  };
}
