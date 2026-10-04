import React, { useEffect, useState } from "react";
import * as MODULE_ART from "../../art/goalTiles.js";
import { SHEEN_STOP_MS, goalArtName, resolveGoalArt } from "../../lib/goalTileCore.js";

/* The picture in a Basic goal tile (Session T, Goal Tile Art Handoff T1a / T2b; issue #61): one
   opaque square, background cover, rounded by the slot's radius, with no frame, scrim or tint
   over it. A computed background on a child of the tint square, never an <img>, so a picture that
   cannot load costs nothing but the fallback.

   The goal tint paints at once. While the picture loads, a lavender sheen crosses it (1.6 s
   loop, stopped at 3 s whatever happens); the picture then fades in over .42 s. If no source
   loads the square stays a flat tint: no glyph, no error text. Reduced motion: no sheen, no fade
   (train.css). Which picture wins (pack, then the app's own module, then the tint) is
   lib/goalTileCore.js's. Desktop (TrainBasic.jsx) and phone (TrainMobile.jsx) draw the same piece;
   the CSS sets the size: the picture area of the desktop's square tile (frame 01 of the handoff, the
   top 78 % of the tile) and 44 px on the phone row. The tint is one flat colour per goal. */

// Resolved once per name per page: the second goal tile of a name (a trip back to step 1, or the
// other screen) paints its picture on the first frame instead of probing and fading again.
const settled = new Map();      // name -> {from, src} | null

function loadImage(src) {
  return new Promise((resolve) => {
    const im = new Image();
    im.onload = () => resolve(true);
    im.onerror = () => resolve(false);
    im.src = src;
  });
}

export default function GoalTile({ goal }) {
  const name = goalArtName(goal.value);
  // Decided once, at mount: a tile that finds its picture already settled paints it at once and
  // never fades; a tile that has to ask fades the picture in when it lands.
  const [fresh] = useState(() => !settled.has(name));
  const [art, setArt] = useState(() => (settled.has(name) ? settled.get(name) : undefined));   // undefined = still asking
  const [sheen, setSheen] = useState(fresh);

  useEffect(() => {
    if (settled.has(name)) { setArt(settled.get(name)); setSheen(false); return undefined; }
    let live = true;
    const stop = setTimeout(() => { if (live) setSheen(false); }, SHEEN_STOP_MS);
    resolveGoalArt(name, loadImage, MODULE_ART).then((got) => {
      settled.set(name, got);
      if (!live) return;
      setArt(got);
      setSheen(false);
    });
    return () => { live = false; clearTimeout(stop); };
  }, [name]);

  return (
    <span className={"mgtr-goal-tint g-" + goal.value + (sheen && art === undefined ? " sheen" : "")}
      aria-hidden="true">
      {art ? (
        <span className={"mgtr-goal-pic" + (fresh ? "" : " still")}
          style={{ backgroundImage: 'url("' + art.src + '")' }} />
      ) : null}
    </span>
  );
}
