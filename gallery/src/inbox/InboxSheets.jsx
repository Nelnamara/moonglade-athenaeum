import React, { useEffect, useState } from "react";
import { badgeText, expiringLines, giftBoxMeta } from "./inboxCore.js";
import {
  subscribe, start, loadFirst, loadEvents, loadGifts, registerContestOpener,
} from "./inboxStore.js";
import { KindTabs, InboxBody, GiftBoxBody, MarkAllMenu } from "./InboxList.jsx";
import "../styles/inbox.css";

/* THE PHONE'S TWO DOORS (Session R + Y, RYPc; Inbox and Event Handoff §10, drift 132). The
   phone keeps its 320 px header as shipped and puts the badge on its Menu door, with Inbox and
   Gift box as the Menu's first two rows, each opening a full-height sheet (exit 280 ms,
   MobileSheet's own). Since the owner's walk (2026-10-04) the desktop has the same two doors
   (✉ Inbox and 🎁 Gift box) and gifts live only in the Gift box. Same state, same rows, same
   writes as the desktop panels -- only the doors differ. */

export function useInbox() {
  const [st, setSt] = useState(null);
  useEffect(() => subscribe(setSt), []);
  useEffect(() => { start(); }, []);
  return st;
}

/* The Menu door's badge: a lavender count -- unread notifications plus pending gifts, the two
   rows behind it -- nothing at 0 or unknown. */
export function MenuBadge({ st }) {
  const b = st ? badgeText(st.count) : "";
  return b ? <span className="ib-menubadge" aria-label={b + " new on PixAI"}>{b}</span> : null;
}

/* The Menu's first two rows: "✉ Inbox  N new ›" (the unread notifications) and
   "🎁 Gift box  <soonest expiry, peach, else the pending gifts> ›". */
export function MenuInboxRows({ st, account, onInbox, onGifts }) {
  const cardsBy = (account && account.cards_by ? account.cards_by : []).filter((c) => c.count > 0);
  const expiry = expiringLines(cardsBy, Date.now());
  const meta = giftBoxMeta(expiry, st ? st.gifts : 0);
  const n = st ? badgeText(st.unread) : "";
  return (
    <>
      <button type="button" className="glm-menu-item" onClick={onInbox}>
        <span className="glm-menu-icon" aria-hidden="true">✉</span>Inbox
        <span className="ib-mrow-meta">{n ? n + " new ›" : "›"}</span>
      </button>
      <button type="button" className="glm-menu-item" onClick={onGifts}>
        <span className="glm-menu-icon" aria-hidden="true"><span className="ib-giftic small" /></span>Gift box
        <span className={"ib-mrow-meta" + (meta.peach ? " peach" : "")}>{meta.text ? meta.text + " ›" : "›"}</span>
      </button>
    </>
  );
}

/* Inbox: the kind tabs as a scrolling segment row (no Gifts tab), then the work cards and
   everything else. */
export function InboxSheetBody({ st, onOpenContests }) {
  const [tab, setTab] = useState("all");
  useEffect(() => { loadFirst(); }, []);
  useEffect(() => registerContestOpener(onOpenContests), [onOpenContests]);
  if (!st) return null;
  return (
    <div className="ib-sheetbody">
      <div className="ib-head">
        <span className="ib-title">Inbox</span>
        <span className="ib-new">{st.unread ? st.unread + " new" : ""}</span>
        <span className="ib-sp" />
        <MarkAllMenu tab={tab} />
      </div>
      {st.allNotice ? <div className="ib-warn">{st.allNotice}</div> : null}
      <KindTabs tab={tab} onTab={setTab} phone />
      <InboxBody st={st} tab={tab} now={Date.now()} />
    </div>
  );
}

/* Gift box: the desktop gift box's own body -- ON PIXAI NOW (full width, stacked), the cards
   about to expire (the phone's answer to the chip's hover), then the gifts. */
export function GiftSheetBody({ st, account }) {
  useEffect(() => { loadEvents(); loadGifts(); }, []);
  if (!st) return null;
  return (
    <div className="ib-sheetbody">
      <GiftBoxBody st={st} account={account} now={Date.now()} phone />
    </div>
  );
}
