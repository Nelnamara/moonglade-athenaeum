import React from "react";
import useContests, { isRunning } from "../hooks/useContests.js";
import ContestChooser from "./ContestChooser.jsx";
import "../styles/contest-mobile.css";

/* "Enter into a contest…" — the sheet body behind the phone's two image-side entry points
   (the lightbox's action row and Image Details' chip), which the handoff keeps alongside
   the board's own Enter bar.

   It exists as its own component for ONE reason: the hook. AppMobile mounts on every app
   boot, and calling useContests() up there would make every launch fetch the contest board
   whether or not anyone ever opens a contest. Mounted here, inside the sheet, the read
   happens the first time somebody actually asks to enter something -- and it rides the
   shared read cache, so the board the Contests screen already painted is reused.

   It picks nothing on its own, exactly as ContestChooser's own contract says: it hands a
   contest back and stops. The RUNNING filter is the server's own runtimeStatus, not client
   date math -- an ended contest cannot take an entry, so it is not offered.

   Eligibility of the SOURCE PICTURE is deliberately not judged here. A grid card carries
   no artwork_id and no published flag (see moonglade_gallery.py's `_card`), so this sheet
   genuinely cannot know whether the picture behind the tap can enter anything. The entry
   screen can -- it reads the published set -- and says so plainly when the source could
   not be pre-selected. Guessing here would mean either hiding contests that would have
   worked or a second fetch on every lightbox tap. */

export default function ContestChooserMobile({ onPick }) {
  const { d, err, contests } = useContests();
  const running = contests.filter(isRunning);

  if (err) return <div className="cmb-choosernote">couldn't load contests — {err}</div>;
  if (!d) return <div className="cmb-choosernote">loading live contests…</div>;

  return (
    <>
      <div className="cmb-choosernote">
        Pick a contest. The next screen picks the art and asks you to confirm — nothing
        enters from here.
      </div>
      <ContestChooser contests={running} onPick={onPick}
        empty="No contests are running right now." />
    </>
  );
}
