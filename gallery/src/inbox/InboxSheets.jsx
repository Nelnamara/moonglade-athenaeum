import React, { useEffect, useState } from "react";
import { badgeText, expiringLines, expiryText, giftBoxMeta } from "./inboxCore.js";
import {
  subscribe, start, loadFirst, loadEvents, loadGifts, registerContestOpener,
} from "./inboxStore.js";
import { KindTabs, InboxBody, EventCards, GiftRows, MarkAllMenu } from "./InboxList.jsx";
import "../styles/inbox.css";

/* THE PHONE'S TWO DOORS (Session R + Y, RYPc; Inbox and Event Handoff §10, drift 132). The
   desktop has one door (the gift box); the phone keeps its 320 px header as shipped and puts
   the badge on its Menu door, with Inbox and Gift box as the Menu's first two rows, each opening
   a full-height sheet (exit 280 ms, MobileSheet's own). Same state, same rows, same writes as
   the desktop panel -- only the doors differ. */

export function useInbox() {
  const [st, setSt] = useState(null);
  useEffect(() => subscribe(setSt), []);
  useEffect(() => { start(); }, []);
  return st;
}

/* The Menu door's badge: a lavender count, nothing at 0 or unknown. */
export function MenuBadge({ st }) {
  const b = st ? badgeText(st.count) : "";
  return b ? <span className="ib-menubadge" aria-label={b + " new on PixAI"}>{b}</span> : null;
}

/* The Menu's first two rows: "✉ Inbox  N new ›" and "🎁 Gift box  <soonest expiry, peach> ›". */
export function MenuInboxRows({ st, account, onInbox, onGifts }) {
  const cardsBy = (account && account.cards_by ? account.cards_by : []).filter((c) => c.count > 0);
  const expiry = expiringLines(cardsBy, Date.now());
  const meta = giftBoxMeta(expiry, st ? st.gifts : 0);
  const n = st ? badgeText(st.count) : "";
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

/* Inbox: the kind tabs as a scrolling segment row, then the work cards and everything else. */
export function InboxSheetBody({ st, onOpenContests }) {
  const [tab, setTab] = useState("all");
  useEffect(() => { loadFirst(); loadGifts(); }, []);
  useEffect(() => registerContestOpener(onOpenContests), [onOpenContests]);
  if (!st) return null;
  return (
    <div className="ib-sheetbody">
      <div className="ib-head">
        <span className="ib-title">Inbox</span>
        <span className="ib-new">{st.count ? st.count + " new" : ""}</span>
        <span className="ib-sp" />
        <MarkAllMenu tab={tab} />
      </div>
      {st.allNotice ? <div className="ib-warn">{st.allNotice}</div> : null}
      <KindTabs tab={tab} onTab={setTab} phone />
      <InboxBody st={st} tab={tab} phone now={Date.now()} />
    </div>
  );
}

/* Gift box: ON PIXAI NOW (full width, stacked), the cards about to expire (the phone's answer
   to the chip's hover), then the gifts. */
export function GiftSheetBody({ st, account }) {
  useEffect(() => { loadEvents(); loadGifts(); }, []);
  if (!st) return null;
  const cardsBy = (account && account.cards_by ? account.cards_by : []).filter((c) => c.count > 0);
  const expiry = expiringLines(cardsBy, Date.now());
  return (
    <div className="ib-sheetbody">
      <div className="ib-scroll">
        <EventCards events={st.events} phone />
        {expiry.lines.map((l) => <div className="ib-expiry-line" key={l.kind + l.at}>{expiryText(l)}</div>)}
        <GiftRows data={st.giftData} error={st.giftError} claim={st.claim} claimLocked={st.claimLocked} readOnly={st.readOnly} />
      </div>
    </div>
  );
}
