import React, { useEffect, useRef, useState } from "react";
import { badgeText } from "./inboxCore.js";
import {
  subscribe, start, loadFirst, loadEvents, loadGifts, registerContestOpener,
} from "./inboxStore.js";
import { KindTabs, InboxBody, MarkAllMenu } from "./InboxList.jsx";
import "../styles/inbox.css";

/* THE GIFT BOX (Session R, R1a; Inbox and Event Handoff §1, drift 123): the inbox's one door on
   the desktop, in the header's right group one 8 px gap before the credits chip, drawn only
   when a PixAI account is linked. 30 × 30, radius 9, the pack's rewards/gift.png at 22 px. Its
   lavender badge is PixAI's unread count (TASK never counts) plus pending gifts, "99+" past 99,
   nothing at 0. It lifts (a lavender ring) while its panel is open.

   The panel: 380 px under the button, right-aligned to the header, scrolling inside, z 300.
   Enter .42 s, exit .35 s with a deferred unmount (350 ms); Esc, an outside click or the button
   close it; reduced motion drops the translate. OPENING IT WRITES NOTHING: one read of the
   first page, plus the gifts and (cached an hour) the events. */

const CLOSE_MS = 350;

export default function GiftBox({ onOpenContests }) {
  const [st, setSt] = useState(null);
  const [open, setOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const [tab, setTab] = useState("all");
  const wrap = useRef(null);
  const timer = useRef(0);

  useEffect(() => subscribe(setSt), []);
  useEffect(() => { start(); }, []);
  useEffect(() => registerContestOpener(() => { close(); if (onOpenContests) onOpenContests(); }),
    [onOpenContests]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => clearTimeout(timer.current), []);

  const close = () => {
    clearTimeout(timer.current);
    setClosing(true);
    timer.current = setTimeout(() => { setOpen(false); setClosing(false); }, CLOSE_MS);
  };
  const toggle = () => {
    if (open && !closing) { close(); return; }
    clearTimeout(timer.current);
    setClosing(false);
    setOpen(true);
    loadFirst();
    loadGifts();
    loadEvents();
  };

  useEffect(() => {
    if (!open || closing) return undefined;
    const onDoc = (e) => { if (wrap.current && !wrap.current.contains(e.target)) close(); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open, closing]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!st) return null;
  const badge = badgeText(st.count);
  const unreadLoaded = st.items.filter((x) => x.unread).length;
  const newCount = st.count != null ? st.count : unreadLoaded;
  return (
    <div className="ib-wrap" ref={wrap}>
      <button type="button" className={"ib-door" + (open && !closing ? " lift" : "")}
        title="PixAI inbox" aria-label={"PixAI inbox" + (badge ? ", " + badge + " new" : "")}
        aria-haspopup="dialog" aria-expanded={open && !closing} onClick={toggle}>
        {badge ? <span className="ib-badge" aria-hidden="true">{badge}</span> : null}
      </button>
      {open ? (
        <div className={"ib-panel" + (closing ? " closing" : "")} role="dialog" aria-label="PixAI inbox">
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
