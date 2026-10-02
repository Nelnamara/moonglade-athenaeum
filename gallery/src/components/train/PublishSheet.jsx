import React from "react";
import { publishTicks } from "../../gen/trainCore.js";

/* Publish (Training Handoff 4a): one sheet, each permanent consequence ticked. Private | Public;
   ◎ Join LoRA rebates (gold, public only, dims and switches off on Private); under "THIS CAN'T
   BE UNDONE" the consequences as ruby 44 px tick rows -- private one, public two -- and Publish
   (lavender) stays off until every row is ticked. Switching visibility clears the ticks. A
   private LoRA made public later opens the same sheet with Public fixed and one tick.

   Hue law (handoff): the lost options are ruby, rebates gold (credits), Publish lavender
   (publishing isn't destructive; only the lost options are). The ticks are sent as the keys
   the server checks, so nothing publishes without them. `pub` is usePublish(); `body` renders
   the inside only, for the phone's bottom sheet. */
export default function PublishSheet({ pub, body = false }) {
  const t = pub.target;
  if (!t) return null;
  const later = t.mode === "make-public";
  const ticks = later ? [{ key: "no_private", text: "It can't go back to private" }] : publishTicks(pub.vis);
  const all = ticks.every((x) => pub.ticks[x.key]);
  const inner = (
    <>
      <div className="mgtr-pub-title">{later ? "Make " : "Publish "}{t.row.title}{later ? " public" : ""}</div>
      <div className="mgtr-pub-seg" role="radiogroup" aria-label="Who can use it">
        {[["private", "Private", "Only you can use it"], ["public", "Public", "In the model market"]].map(([v, n, d]) => (
          <button type="button" key={v} role="radio" aria-checked={pub.vis === v}
            disabled={later && v === "private"}
            className={"mgtr-pub-opt" + (pub.vis === v ? " on" : "")} onClick={() => pub.pickVis(v)}>
            <span className="n">{n}</span><span className="d">{d}</span>
          </button>
        ))}
      </div>
      {pub.rebateOffer && (
        <button type="button" className={"mgtr-pub-rebate" + (pub.vis === "public" ? "" : " off")}
          role="switch" aria-checked={pub.vis === "public" && pub.rebate}
          disabled={pub.vis !== "public"} onClick={() => pub.setRebate(!pub.rebate)}>
          <span className="t">
            <span className="n">◎ Join LoRA rebates</span>
            <span className="d">Earn up to 5% in credits when others use it · public only · joining can't be undone</span>
          </span>
          <span className={"mgtr-switch" + (pub.vis === "public" && pub.rebate ? " on" : "")}><span /></span>
        </button>
      )}
      <div className="mgtr-pub-warn">THIS CAN'T BE UNDONE</div>
      {ticks.map((x) => {
        const on = !!pub.ticks[x.key];
        return (
          <button type="button" key={x.key} role="checkbox" aria-checked={on}
            className={"mgtr-pub-tick" + (on ? " on" : "")}
            onClick={() => pub.setTicks((cur) => ({ ...cur, [x.key]: !cur[x.key] }))}>
            <span className="box">{on ? "✓" : ""}</span><span>{x.text}</span>
          </button>
        );
      })}
      {pub.err && <div className="mgtr-err">⚠ {pub.err}</div>}
      <div className="mgtr-pub-foot">
        <button type="button" className="mgtr-ghost" onClick={pub.close} disabled={pub.busy}>Cancel</button>
        <button type="button" className="mgtr-go" disabled={!all || pub.busy}
          onClick={() => pub.submit(ticks.map((x) => x.key))}>
          {pub.busy ? "publishing…" : later ? "Make it public" : pub.vis === "public" ? "Publish publicly" : "Publish privately"}
        </button>
      </div>
    </>
  );
  if (body) return <div className="mgtr-pub phone">{inner}</div>;
  return (
    <div className="mgtr-layer">
      <div className="mgtr-layer-scrim" onClick={pub.close} />
      <div className="mgtr-pub" role="dialog" aria-label="Publish">{inner}</div>
    </div>
  );
}
