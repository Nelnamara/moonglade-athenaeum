/* THE ENTRY ROAD'S TWO SENTENCES, in one place (2026-09-04, the mobile contest pass).

   Both of these were written once inside ContestConfirm.jsx, for the desktop confirm
   dialog. The phone's entry screen (ContestEntryMobile.jsx) is the SAME irreversible act
   and has to say the same things about it, so they are lifted here rather than copied --
   the same mechanical-lift precedent useContests.js set when the board's fetch had to
   serve two surfaces. ContestConfirm.jsx is refactored to consume this module; there is
   no second, drifting copy of either sentence.

   WHY THESE TWO IN PARTICULAR. They are the words a person reads immediately before an
   entry fires, and PixAI offers no way to withdraw one. A wrong word here is not a
   cosmetic bug -- it is a wrong statement on the last screen before an act that cannot be
   taken back. */

const NOT_ELIGIBLE = /not.?eligible/i;
const CLOSED = /closed|ended|expired/i;

/* An upstream refusal as a reader's sentence. The fallback is deliberately NOT "nothing
   was submitted": a read timeout after PixAI accepted the entry looks identical from
   here, and telling someone their entry did not land when it may have is how they enter
   twice. Same shape gen/submitTask.js uses for the same ambiguity on the spend path. */
export function classifyEntryError(msg) {
  const m = String(msg || "");
  if (NOT_ELIGIBLE.test(m)) {
    return { icon: "⚠", title: "Not eligible",
             copy: "PixAI refused this piece for this contest — usually because it was "
                 + "published before the contest opened. Nothing was submitted." };
  }
  if (CLOSED.test(m)) {
    return { icon: "🚫", title: "Contest closed",
             copy: "Entries are closed for this contest. Nothing was submitted." };
  }
  return { icon: "⚠", title: "Something went wrong on PixAI's side",
           copy: "The entry MAY still have been submitted — check My entries before "
               + "trying again. " + m };
}

/* THE COST LINE IS ONE SLOT WITH THREE HONEST FACES, and never a fourth. The server
   answers `spends_credits`: null means the fee is UNMEASURED -- the contest contract
   declares an INSUFFICIENT_CREDITS error and no entry has ever been fired to find out --
   so the slot says so in words. false is "Free"; a number is the mono-gold amount. A
   number invented here would be a lie on the last screen before an irreversible act. */
export function entryCostFace(spends) {
  if (spends === false) return { cls: "", text: "Free" };
  if (typeof spends === "number") {
    return { cls: "amount", text: "♦ " + Number(spends).toLocaleString() + " CR" };
  }
  return { cls: "unknown", text: "Entry fee unverified" };
}
