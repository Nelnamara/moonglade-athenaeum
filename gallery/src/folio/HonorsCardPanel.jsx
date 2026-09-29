import React, { useEffect, useRef, useState } from "react";
import { CARD_W, CARD_H } from "./honorsCardCore.js";
import { renderHonorsCard, canvasToBlob, saveBlob, copyBlob, shareBlob } from "./honorsCardBrowser.js";

/* THE HONORS CARD, on screen (Session O, O6). Draws the 1200 x 630 card on THIS device from the
   model the Folio hands it (folio/honorsCardCore.js honorsCardModel), shows it, and offers Save and
   Copy (desktop) or Share through the system share sheet (phone; Save stays as the fallback where a
   device cannot share files). Nothing is uploaded: the badge art is the app's own, the canvas is
   local, and Save / Copy / Share only ever hand the PNG to the browser or the device.

   Drawn when it opens and again when the model changes (a new earn while it is up), never on a
   timer. It writes nothing anywhere. */
export default function HonorsCardPanel({ model, markUrl, onClose, phone = false }) {
  const [url, setUrl] = useState("");
  const [note, setNote] = useState("");
  const blobRef = useRef(null);
  const key = JSON.stringify(model);

  useEffect(() => {
    let dead = false;
    let made = "";
    (async () => {
      try {
        const canvas = await renderHonorsCard(model, { markUrl });
        const blob = await canvasToBlob(canvas);
        if (dead || !blob) return;
        blobRef.current = blob;
        made = URL.createObjectURL(blob);
        setUrl((old) => { if (old) URL.revokeObjectURL(old); return made; });
      } catch { /* the preview stays empty; Save and Copy stay off */ }
    })();
    return () => { dead = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, markUrl]);
  useEffect(() => () => { setUrl((old) => { if (old) URL.revokeObjectURL(old); return ""; }); }, []);

  const flash = (t) => { setNote(t); setTimeout(() => setNote(""), 1600); };
  const onSave = () => { if (saveBlob(blobRef.current)) flash("Saved"); };
  const onCopy = async () => { flash((await copyBlob(blobRef.current)) ? "Copied ✓" : "Copy isn't available here — use Save"); };
  const onShare = async () => {
    const r = await shareBlob(blobRef.current, model);
    if (r === "unsupported") { if (saveBlob(blobRef.current)) flash("Saved — this device can't open its share sheet"); }
  };

  return (
    <div className={"mgfo-cardpanel" + (phone ? " phone" : "")} data-honors-card>
      <div className="mgfo-cardpanel-bar">
        <span className="mgfo-cardpanel-lab">HONORS CARD · {CARD_W} × {CARD_H} PNG · drawn on this device</span>
        {phone ? (
          <button type="button" className="mgfo-cardbtn" disabled={!url} onClick={onShare}>Share</button>
        ) : (
          <>
            <button type="button" className="mgfo-cardbtn" disabled={!url} onClick={onSave}>{"⇩"} Save PNG</button>
            <button type="button" className="mgfo-cardbtn ghost" disabled={!url} onClick={onCopy}>Copy image</button>
          </>
        )}
        {onClose && <button type="button" className="mgfo-cardpanel-x" onClick={onClose} aria-label="Close the card">{"✕"}</button>}
      </div>
      <div className="mgfo-cardpanel-stage" style={{ aspectRatio: CARD_W + " / " + CARD_H }}>
        {url ? <img src={url} alt={"The Honors card for " + model.name} draggable={false} />
          : <span className="mgfo-cardpanel-wait">drawing the card…</span>}
      </div>
      {phone && url && (
        <div className="mgfo-cardpanel-row">
          <button type="button" className="mgfo-cardbtn ghost" onClick={onSave}>Save PNG</button>
        </div>
      )}
      <div className="mgfo-cardpanel-foot">
        {note || (phone ? "Drawn on this device (1200 × 630). " : "")
          + "Spoiler-safe: feats appear only as “N found”, and sealed ones are never pictured. Nothing is uploaded."}
      </div>
    </div>
  );
}
