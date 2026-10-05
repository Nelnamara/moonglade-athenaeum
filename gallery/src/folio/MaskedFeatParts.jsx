import React, { useState } from "react";
import "../styles/folio-masked.css";

/* The pieces of the masked-feats design (Session G) that the desktop Folio and the phone Folio
   share. Pixel source: design/handoff-2026-09-04/Masked Feats Handoff.dc.html; decisions in
   design/notes/masked-feats/NOTES.md. The logic that decides WHEN each shows is
   folio/maskedFeatsCore.js; this file only draws.

   What is drawn for a masked feat is the riddle and a silhouette -- the veil art
   (/branding/mystery/secret_feat.png) seen through the alpha mask the server cut from the
   next unfound feat's badge. Nothing else about that feat reaches this file: it is never given
   an id, a name, a count or the badge. */

export const CURTAIN_ART = "/branding/mystery/secret_banner_curtain.png";

/* The veil art seen through the mask. `maskUrl` is the server's own path (validated in
   maskedFeatsCore.veilState before it gets here), passed as a CSS custom property so the mask
   is one declaration in the stylesheet, with the -webkit- twin, not two inline styles. */
export function VeilFill({ maskUrl }) {
  return <div className="mgfm-fill" style={{ "--mgfm-mask": "url(" + maskUrl + ")" }} />;
}

/* Desktop: the one dashed veil card, after the earned feats. Not a button. */
export function VeilCard({ maskUrl, riddle, waiting }) {
  return (
    <div className={"mgfm-veil" + (waiting ? " waiting" : "")} data-veil="1">
      <div className="mgfm-well">
        <div className="mgfm-rim"><VeilFill maskUrl={maskUrl} /></div>
      </div>
      <div className="mgfm-veil-text">
        <div className="mgfm-cap">A RIDDLE · MORE WAIT, UNFOUND</div>
        <div className="mgfm-riddle">{riddle}</div>
      </div>
    </div>
  );
}

/* "Every secret found": the gold line that takes the veil's place, desktop card or phone strip. */
export function AllFound({ phone, waiting }) {
  return (
    <div className={"mgfm-all" + (phone ? " phone" : "") + (waiting ? " waiting" : "")}>
      <div className="mgfm-all-h">Every secret found</div>
      <div className="mgfm-all-s">Nel has nothing left to hide from you{phone ? "." : ". For now."}</div>
    </div>
  );
}

/* The glitch reveal's layers, laid over a well that already holds the earned feat's badge:
   the veil art until the snap, and two screen-blended copies of the badge (ruby, and the
   Loom's cyan) offset on 60 ms steps while it splits. `frame` is maskedFeatsCore.revealFrame.
   The copies use the still thumb (a CSS background cannot fall back from a missing webp, and
   the split is over before an animated badge would matter). Renders nothing once the reveal
   has settled on the badge. */
export function RevealLayers({ id, frame }) {
  if (!frame || (frame.art === "badge" && !frame.split && frame.coverOpacity === 0)) return null;
  const badge = "/badge-thumb/" + encodeURIComponent(id) + ".png";
  const copy = (hue, dx, dy) => ({
    backgroundImage: "url('" + badge + "')",
    opacity: frame.split ? 0.8 : 0,
    transform: frame.split ? "translate(" + dx + "px," + dy + "px)" : "none",
    filter: "sepia(1) saturate(6) hue-rotate(" + hue + "deg)",
  });
  const s = frame.split || { dx: 0, dy: 0 };
  return (
    <>
      <div className="mgfm-cover" style={{ opacity: frame.coverOpacity }} />
      <div className="mgfm-split" style={copy(-40, s.dx, s.dy)} />
      <div className="mgfm-split" style={copy(140, -s.dx, -s.dy)} />
    </>
  );
}

/* Phone: the veil banner. The curtain art at its native ratio, full width, under the FEATS
   header, the riddle and a 30 px silhouette on a scrim in its bottom band (NOTES decision 4).
   The art ships in the asset pack; a pack that does not carry it yet gets a CSS panel on the
   same scrim gradient, so the riddle and the silhouette still show. */
export function VeilBanner({ maskUrl, riddle, waiting }) {
  const [broken, setBroken] = useState(false);
  const text = (
    <>
      <div className="mgfm-bn-row">
        <div className="mgfm-bn-sil"><VeilFill maskUrl={maskUrl} /></div>
        <div className="mgfm-bn-cap">A RIDDLE</div>
      </div>
      <div className="mgfm-bn-riddle">{riddle}</div>
    </>
  );
  if (broken) {
    return (
      <div className={"mgfm-bn-panel" + (waiting ? " waiting" : "")} data-veil="1">
        <div className="mgfm-bn-text flow">{text}</div>
      </div>
    );
  }
  return (
    <div className={"mgfm-bn" + (waiting ? " waiting" : "")} data-veil="1">
      <img className="mgfm-bn-art" src={CURTAIN_ART} alt="" draggable={false}
        onError={() => setBroken(true)} />
      <div className="mgfm-bn-text">{text}</div>
    </div>
  );
}
