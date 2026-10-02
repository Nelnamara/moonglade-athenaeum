import { accountPrefs } from "../hooks/useAccountPrefs.js";
import { show as toastShow } from "../notify/toastStore.js";
import { retireReceiptToast } from "../notify/updateStore.js";
import { celebrationsIdle } from "../notify/ach.js";
import { toastSummary, whatsNewPlan } from "./helpCore.js";
import { loadAbout } from "./helpData.js";
import { openAbout, openWhatsNew } from "./helpStore.js";

/* THE FIRST SIGN-IN AFTER AN UPDATE (Session I decision 3b/3c).

   Once per version per account (`seen.whatsnew` = the running version as the guide prints
   it: x.y, or x.y.z for a patch), the toast "Updated to x.y · <the release's title> ·
   What's new" joins the Activity layer -- AFTER any achievement toasts from the same
   sign-in, never before (it waits for notify/ach.js's celebration layer to go quiet). Its
   "What's new" opens the one-time sheet for a minor or major release and About for a
   patch. Dismissing it skips the sheet; About keeps the changelog reachable.

   The version is noted the moment the toast SHOWS, so a reload does not show it twice.
   A brand-new account (no pictures yet, and never an earlier version noted) is noted
   silently: it was not updated, it was just made. The setup wizard notes it too
   (markWhatsNewSeen), so an install onboarded on this version never hears it was updated
   to it.

   Run once per boot, from the gallery's own shells only (HelpRoot's `whatsNew` prop). */

const SEEN_KEY = "seen.whatsnew";
const POLL_MS = 500;
const QUIET_POLLS = 3;          // ~1.5 s of a quiet celebration layer before the toast
const GIVE_UP_MS = 5 * 60 * 1000;
const NEL = "/branding/mascots/gen_nel.png";

let started = false;

function whenCelebrationsSettle(fn) {
  const t0 = Date.now();
  let quiet = 0;
  const tick = () => {
    if (Date.now() - t0 > GIVE_UP_MS) return;
    let idle = true;
    try { idle = celebrationsIdle(); } catch { idle = true; }
    quiet = idle ? quiet + 1 : 0;
    if (quiet >= QUIET_POLLS) { fn(); return; }
    setTimeout(tick, POLL_MS);
  };
  setTimeout(tick, POLL_MS);
}

export function startWhatsNew(boot) {
  if (started) return;
  started = true;
  const store = accountPrefs();
  Promise.all([store.ensureLoaded(), loadAbout()]).then(([ok, about]) => {
    if (!ok || !about || about.error || !about.display_version) return;
    const stats = (boot && boot.stats) || {};
    const plan = whatsNewPlan({
      seen: store.get(SEEN_KEY, undefined),
      display: about.display_version,
      kind: about.kind,
      hasLibrary: (Number(stats.images) || 0) + (Number(stats.videos) || 0) > 0,
    });
    if (!plan.show) {
      if (plan.mark) store.set(SEEN_KEY, about.display_version);
      return;
    }
    whenCelebrationsSettle(() => {
      // Re-read at show time: another tab of the same account may have shown it already.
      if (store.get(SEEN_KEY, undefined) === about.display_version) return;
      store.set(SEEN_KEY, about.display_version);
      retireReceiptToast();
      toastShow({
        kind: "whatsnew",
        sticky: true,
        avatar: NEL,
        title: "Updated to",
        code: about.display_version,
        msg: toastSummary(about),
        action: {
          label: "What's new",
          run: () => (plan.opens === "sheet" ? openWhatsNew(about) : openAbout("")),
        },
      });
    });
  });
}

/* The setup wizard's half: an install onboarded on this version is not "updated" to it.
   Writes only when nothing is noted yet. */
export function markWhatsNewSeen() {
  const store = accountPrefs();
  Promise.all([store.ensureLoaded(), loadAbout()]).then(([ok, about]) => {
    if (!ok || !about || about.error || !about.display_version) return;
    if (store.get(SEEN_KEY, undefined) === undefined) store.set(SEEN_KEY, about.display_version);
  });
}
