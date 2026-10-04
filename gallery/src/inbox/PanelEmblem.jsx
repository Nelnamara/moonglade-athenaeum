import React, { useEffect, useState } from "react";
import { inboxIcon, settledInboxIcon } from "./InboxIcon.jsx";

/* Each panel's emblem (owner, 2026-10-04: "a larger version of the icon in the top right of each
   of their respective frames"): the door's own picture, large, at the right end of the panel's
   title row -- 48 px in the desktop panels, 40 px (`small`) at the end of the phone sheets' title
   rows. Contained, decorative (alt "", aria-hidden, no click). The same picture as each door: the
   inbox's mailbox through InboxIcon's once-a-page lookup (pack › module), the gift box's pack art.
   A picture that fails leaves no emblem at all -- no glyph stand-in at this size. */

export const GIFT_ART = "/branding/rewards/gift.png";

function Emblem({ src, small }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => { setFailed(false); }, [src]);
  if (!src || failed) return null;
  return (
    <img className={"ib-emblem" + (small ? " small" : "")} src={src} alt="" aria-hidden="true"
      draggable={false} onError={() => setFailed(true)} />
  );
}

export function InboxEmblem({ small }) {
  const [art, setArt] = useState(() => settledInboxIcon());
  useEffect(() => {
    let live = true;
    inboxIcon().then((got) => { if (live) setArt(got); });
    return () => { live = false; };
  }, []);
  return <Emblem src={art ? art.src : ""} small={small} />;
}

export function GiftEmblem({ small }) {
  return <Emblem src={GIFT_ART} small={small} />;
}
