import React from "react";
import MarkDust from "./MarkDust.jsx";
import "../styles/mark-anims.css";

/* THE MARK, ANIMATED — one renderer for the header's living mark, shared by the
   Control Panel's preview so the preview shows the REAL treatment rather than a
   second, drifting imitation of it (the old preview's own comment pointed at a
   component that no longer exists).

   This is the half of #24 that was missing: the Control Panel has always written a
   `mark_anim` pick and the server has always shipped it in MG_BOOT — and nothing
   read it. Every treatment lives in CSS keyed on `mark-anim-<id>`; this component's
   whole job is to put that class on the mark and hand the stylesheet its four
   settings as custom properties.

   Structure is the shipped header's, unchanged (tilt > img + sheen, then the halo) —
   the treatments were transcribed against it. Two treatments need real elements that
   CSS alone cannot conjure: twinkle's three constellation points (two pseudo-elements
   cannot be three stars) and moondust's canvas. Both render only for their own pick,
   so nothing else carries their weight. */

/* glow_angle -> the bloom's origin. 0 is the documented default and means CENTRED
   (a plain radial bloom); any other value is a compass bearing, 90 right, 180 down,
   270 left, 360 up. Screen coordinates put y the other way up from a compass, hence
   the minus. Kept in JS because CSS trig is not yet safe to rely on everywhere. */
function glowOrigin(angle) {
  const a = Number(angle) || 0;
  if (!a) return ["50%", "50%"];
  const rad = (a * Math.PI) / 180;
  const x = 50 + 34 * Math.sin(rad);
  const y = 50 - 34 * Math.cos(rad);
  return [x.toFixed(1) + "%", y.toFixed(1) + "%"];
}

export default function MarkAnimated({
  boot, anim, url, speed, scale, glowColor, glowAngle, size = 96, className = "",
}) {
  const b = boot || {};
  const markUrl = url || b.mark_url || "/branding/logo.png";
  const pick = String(anim || b.mark_anim || "classic");
  const spd = Number(speed != null ? speed : b.anim_speed);
  const scl = Number(scale != null ? scale : b.anim_scale);
  const colour = glowColor || b.glow_color || "#94e2d5";
  const [gx, gy] = glowOrigin(glowAngle != null ? glowAngle : b.glow_angle);

  const vars = {
    // The masked sweeps (shine/aurora/classic) mask themselves to the mark's own
    // silhouette, which needs its URL as a custom property -- a built stylesheet
    // cannot know it. Quoted + encoded: this string lands inside a CSS url().
    "--mark-url": 'url("' + encodeURI(markUrl) + '")',
    "--anim-speed": Number.isFinite(spd) && spd > 0 ? spd : 1,
    "--anim-scale": Number.isFinite(scl) && scl > 0 ? scl : 1,
    "--glow-color": colour,
    "--glow-x": gx,
    "--glow-y": gy,
  };

  return (
    <div className={"mgx-mark mark-anim-" + pick + (className ? " " + className : "")}
      style={vars}>
      {/* moondust paints BEHIND the art, so it renders before the tilt box */}
      {pick === "moondust" && (
        <MarkDust size={size} speed={Number.isFinite(spd) && spd > 0 ? spd : 1} />
      )}
      <div className="mgx-mark-tilt">
        <img src={markUrl} alt="" onError={(e) => e.currentTarget.remove()} />
        <div className="mgx-mark-sheenclip" aria-hidden="true">
          <div className="mgx-mark-sheen" />
        </div>
      </div>
      {/* The constellation. These are children 2-4 of .mgx-mark when moondust is not
          also mounted -- which it never is, one pick at a time -- and the CSS places
          each by nth-child, exactly as the board did. */}
      {pick === "twinkle" && (
        <>
          <i aria-hidden="true">✦</i>
          <i aria-hidden="true">✦</i>
          <i aria-hidden="true">✦</i>
        </>
      )}
      <div className="mgx-mark-halo" aria-hidden="true" />
    </div>
  );
}
