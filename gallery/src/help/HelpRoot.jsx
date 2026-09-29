import React, { useEffect } from "react";
import useIsMobile from "../hooks/useIsMobile.js";
import HelpOverlay from "./HelpOverlay.jsx";
import { AboutLayer, WhatsNewSheet } from "./AboutLayers.jsx";
import { startWhatsNew } from "./whatsNew.js";
import { registerHelpHost } from "./helpStore.js";

/* The guide's page-level layers, mounted ONCE per shell beside <NotifyRoot/>: the Help
   overlay (or the phone's sheet), the About modal and the what's-new sheet. Every door into
   them is a helpStore verb, so nothing else in the app has to know where they are drawn.

   `whatsNew` is set by the gallery's own shells only (main.jsx): the first sign-in after an
   update lands on the gallery, and that is where the post-update toast belongs. The Loom
   mounts this without it. */
export default function HelpRoot({ boot, whatsNew }) {
  const phone = useIsMobile();
  useEffect(() => registerHelpHost(), []);
  useEffect(() => { if (whatsNew) startWhatsNew(boot); }, [whatsNew]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <>
      <HelpOverlay phone={phone} />
      <AboutLayer phone={phone} />
      <WhatsNewSheet phone={phone} />
    </>
  );
}
