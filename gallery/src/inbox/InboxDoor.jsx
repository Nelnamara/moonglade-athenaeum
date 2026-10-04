import React, { useEffect, useState } from "react";
import { badgeText } from "./inboxCore.js";
import { subscribe, start, loadFirst, registerContestOpener } from "./inboxStore.js";
import { KindTabs, InboxBody, MarkAllMenu } from "./InboxList.jsx";
import useHeaderDoor from "./useHeaderDoor.js";
import InboxIcon from "./InboxIcon.jsx";
import "../styles/inbox.css";

/* ✉ THE INBOX (owner's walk, 2026-10-04): the gift box's twin, one 8 px gap before it in the
   header's right group, drawn only when a PixAI account is linked. Until the walk the gift box
   was the inbox's one door; the owner ruled the gift box is for rewards, so the inbox has its own
   button. 30 x 30, radius 9, the owner's mailbox at the gift box's 22 px (InboxIcon.jsx: the pack's
   copy, else the app's own, else the ✉ glyph). Its lavender badge is
   PixAI's unread notifications (TASK never counts), "99+" past 99, nothing at 0 -- the gifts are
   the gift box's badge.

   The panel is Session R's (Inbox and Event Handoff §1-3) less everything gift- and event-related:
   "Inbox" and "N new", the kind tabs, the work cards, then everything else, and ⋯ Mark all read.
   OPENING IT WRITES NOTHING: one read of the first page. A contest row in it opens the Contests
   overlay. */

export default function InboxDoor({ onOpenContests }) {
  const [st, setSt] = useState(null);
  const [tab, setTab] = useState("all");
  const door = useHeaderDoor("inbox", () => { loadFirst(); });

  useEffect(() => subscribe(setSt), []);
  useEffect(() => { start(); }, []);
  useEffect(() => registerContestOpener(() => { door.close(); if (onOpenContests) onOpenContests(); }),
    [onOpenContests]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!st) return null;
  const badge = badgeText(st.unread);
  const unreadLoaded = st.items.filter((x) => x.unread).length;
  const newCount = st.unread != null ? st.unread : unreadLoaded;
  return (
    <div className="ib-wrap" ref={door.wrap}>
      <button type="button" className={"ib-door inbox" + (door.lifted ? " lift" : "")}
        title="PixAI inbox" aria-label={"Inbox" + (badge ? ", " + badge + " new" : "")}
        aria-haspopup="dialog" aria-expanded={door.lifted} onClick={door.toggle}>
        <InboxIcon />
        {badge ? <span className="ib-badge" aria-hidden="true">{badge}</span> : null}
      </button>
      {door.open ? (
        <div className={"ib-panel" + (door.closing ? " closing" : "")} role="dialog" aria-label="PixAI inbox">
          <div className="ib-head">
            <span className="ib-title">Inbox</span>
            <span className="ib-new">{newCount ? newCount + " new" : ""}</span>
            <span className="ib-sp" />
            <MarkAllMenu tab={tab} />
          </div>
          {st.allNotice ? <div className="ib-warn">{st.allNotice}</div> : null}
          <KindTabs tab={tab} onTab={setTab} />
          <InboxBody st={st} tab={tab} now={Date.now()} />
        </div>
      ) : null}
    </div>
  );
}
