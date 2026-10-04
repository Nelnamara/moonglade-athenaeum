import React, { useEffect, useState } from "react";
import { badgeText } from "./inboxCore.js";
import { subscribe, start, loadEvents, loadGifts } from "./inboxStore.js";
import { GiftBoxBody } from "./InboxList.jsx";
import useHeaderDoor from "./useHeaderDoor.js";
import { GiftEmblem } from "./PanelEmblem.jsx";
import "../styles/inbox.css";

/* 🎁 THE GIFT BOX (Session R, R1a; Inbox and Event Handoff §1, drift 123), for rewards only since
   the owner's walk (2026-10-04): "it was meant to redeem free cards etc." The inbox moved to its
   own ✉ button just before this one (InboxDoor.jsx). In the header's right group one 8 px gap
   before the credits chip, drawn only when a PixAI account is linked. 30 x 30, radius 9, the
   pack's rewards/gift.png at 22 px. Its lavender badge is the pending gifts only, "99+" past 99,
   nothing at 0. It lifts (a lavender ring) while its panel is open.

   The panel ("Gift box", the same 380 px under the button, z 300, the same open and close as the
   inbox's; its title row ends in the gift at 48 px) holds ON PIXAI NOW, the free cards about to
   expire, then the gifts -- the phone's Gift
   box sheet, the same body (InboxList.jsx GiftBoxBody). OPENING IT WRITES NOTHING: one read of
   the gifts and (cached an hour) the events. */

export default function GiftBox({ account }) {
  const [st, setSt] = useState(null);
  const door = useHeaderDoor("gifts", () => { loadGifts(); loadEvents(); });

  useEffect(() => subscribe(setSt), []);
  useEffect(() => { start(); }, []);

  if (!st) return null;
  const badge = badgeText(st.gifts);
  return (
    <div className="ib-wrap" ref={door.wrap}>
      <button type="button" className={"ib-door gift" + (door.lifted ? " lift" : "")}
        title="Gift box" aria-label={"Gift box" + (badge ? ", " + badge + " waiting" : "")}
        aria-haspopup="dialog" aria-expanded={door.lifted} onClick={door.toggle}>
        {badge ? <span className="ib-badge" aria-hidden="true">{badge}</span> : null}
      </button>
      {door.open ? (
        <div className={"ib-panel" + (door.closing ? " closing" : "")} role="dialog" aria-label="Gift box">
          <div className="ib-head">
            <span className="ib-headtext"><span className="ib-title">Gift box</span></span>
            <span className="ib-sp" />
            <GiftEmblem />
          </div>
          <GiftBoxBody st={st} account={account} now={Date.now()} />
        </div>
      ) : null}
    </div>
  );
}
