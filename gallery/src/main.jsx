import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import LoginPage from "./components/LoginPage.jsx";
import SetupWizard from "./components/SetupWizard.jsx";
import "./styles.css";

const boot = window.MG_BOOT || {};
// boot.authenticated is only ever false on /login's non-bootstrap render (see
// moonglade_gallery.py's login() route) -- App never mounts in that case, so
// none of its authenticated-only effects (fetchLibrary, fetchAccount, ...)
// can fire against a session that doesn't exist yet.
//
// needs_key/catalog_empty (next_gallery()'s boot, same computation classic's index() has
// always made) are the first-run state: no PIXAI_API_KEY yet, or a key but zero synced
// media. SetupWizard owns that state instead of App -- an empty/keyless gallery has
// nothing for App's fetchLibrary/fetchAccount to usefully show anyway, and the DC's own
// wizard is a dedicated screen, not a banner bolted onto the real gallery.
let view;
if (boot.authenticated === false) {
  view = <LoginPage boot={boot} />;
} else if (boot.needs_key || boot.catalog_empty) {
  view = <SetupWizard boot={boot} />;
} else {
  view = <App boot={boot} />;
}
createRoot(document.getElementById("root")).render(view);
