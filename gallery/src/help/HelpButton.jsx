import React from "react";
import { openHelp } from "./helpStore.js";
import "../styles/help.css";

/* The "?" in a surface's header (Session I decision 2): opens Help on that surface's page
   (helpCore.SURFACE_PAGE), or on `slug` when one is given. The ? key does the same from
   anywhere outside a text field (helpStore). `className` adds a host's own sizing. */
export default function HelpButton({ surface, slug, className, title, plain }) {
  // `plain`: the host's own button face only (the phone hero's icon row), no round ? face.
  const cls = (plain ? "" : "mghelp-q") + (className ? (plain ? "" : " ") + className : "");
  return (
    <button type="button" className={cls}
      title={title || "Guide — how this screen works (?)"} aria-label="Open the guide"
      onClick={(e) => { e.stopPropagation(); openHelp({ surface, slug }); }}>
      ?
    </button>
  );
}
