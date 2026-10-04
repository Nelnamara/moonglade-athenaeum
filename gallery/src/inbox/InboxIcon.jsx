import React, { useEffect, useState } from "react";
import { inbox_icon } from "../art/inboxIcon.js";
import { resolveInboxIcon } from "./inboxCore.js";

/* The ✉ Inbox button's mailbox (owner's art, 2026-10-04), drawn the way the gift box draws
   gift.png: at 22 px in the header's 30 px button, and at 18 px (`small`) in the phone's Menu row.
   A computed background, never an <img> hole.

   Which picture (the goal tiles' precedence, lib/goalTileCore.js): the pack's rewards/inbox.png
   (pack v7 carries it) › the app's own module copy (art/inboxIcon.js, tools/art/build_inbox_icon.py)
   › today's ✉ glyph when neither loads. Resolved ONCE a page and kept: the second icon -- the Menu
   reopened, the header redrawn -- paints at once and asks nothing. While the one ask is out the slot
   stays empty rather than flashing the glyph. */

let settled;            // undefined = not asked yet; null = no picture (the glyph); {from, src}
let asking = null;

function loadImage(src) {
  return new Promise((resolve) => {
    const im = new Image();
    im.onload = () => resolve(true);
    im.onerror = () => resolve(false);
    im.src = src;
  });
}

/* What the lookup settled on, without waiting: undefined (still asking), null or {from, src}. */
export function settledInboxIcon() { return settled; }

export function inboxIcon() {
  if (settled !== undefined) return Promise.resolve(settled);
  if (!asking) asking = resolveInboxIcon(loadImage, inbox_icon).then((got) => { settled = got; return got; });
  return asking;
}

export default function InboxIcon({ small }) {
  const [art, setArt] = useState(settled);
  useEffect(() => {
    if (settled !== undefined) { setArt(settled); return undefined; }
    let live = true;
    inboxIcon().then((got) => { if (live) setArt(got); });
    return () => { live = false; };
  }, []);
  const cls = small ? " small" : "";
  if (art === null) return <span className={"ib-inboxglyph" + cls} aria-hidden="true">✉</span>;
  return (
    <span className={"ib-inboxic" + cls} aria-hidden="true"
      style={art ? { backgroundImage: 'url("' + art.src + '")' } : undefined} />
  );
}
