import React, { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import useIsMobile from "../hooks/useIsMobile.js";
import { closeRecipes, getSnapshot, openRecipes, subscribe } from "./recipesStore.js";
import RecipesOverlay from "./RecipesOverlay.jsx";
import RecipeCreator from "./RecipeCreator.jsx";
import RecipesMobile from "./RecipesMobile.jsx";
import "../styles/recipes.css";

/* THE ONE MOUNT POINT for every recipe surface (App.jsx and AppMobile.jsx each render it
   once, beside PickerHost). It draws whatever recipesStore says is open -- the picker at
   either size, the creator, the phone's sheet / market / recipe screens -- in the overlay
   band at z 416/417: above the Lightbox (400), which ⁂ Make a recipe opens the creator
   from, and the shared overlay slab (410/411); under the gallery picker (490) the creator
   asks for pictures, and the command palette (460). The handoffs drew "z 300"; that was
   the band before the 2026-09-28 normalization put the Lightbox at 400 (overlays.css's
   ladder). Deferred unmount: enter .42 s, exit .35 s desktop / .28 s phone. */
export default function RecipesHost() {
  const snap = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  const mobile = useIsMobile();
  const [shown, setShown] = useState(null);     // the open state being drawn (kept while closing)
  const [closing, setClosing] = useState(false);
  const timer = useRef(0);
  const open = snap.open;

  useEffect(() => {
    clearTimeout(timer.current);
    if (open) { setShown(open); setClosing(false); return undefined; }
    if (!shown) return undefined;
    setClosing(true);
    timer.current = setTimeout(() => { setShown(null); setClosing(false); }, mobile ? 280 : 350);
    return () => clearTimeout(timer.current);
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const close = useCallback(() => closeRecipes(), []);
  const backToPicker = useCallback(() => openRecipes({ view: "picker", tab: "mine", phone: mobile, phoneScreen: "market" }), [mobile]);

  const cur = open || shown;
  if (!cur) return null;
  if (cur.view === "creator") {
    const phone = mobile || cur.phone;
    return (
      <div className={"rcp-cwrap" + (phone ? " rcp-cwrap-m" : "") + (closing ? " closing" : "")}>
        {!phone && <div className={"rcp-scrim" + (closing ? " closing" : "")} onClick={close} aria-hidden="true" />}
        <div className={phone ? "rcp-m" : "rcp-host"}>
          <RecipeCreator creator={cur.creator} phone={phone} onClose={close}
            onBack={cur.creator && cur.creator.fromImage ? null : backToPicker} />
        </div>
      </div>
    );
  }
  if (mobile || cur.phone) return <RecipesMobile open={cur} onClose={close} closing={closing} />;
  return <RecipesOverlay open={cur} onClose={close} closing={closing} />;
}
