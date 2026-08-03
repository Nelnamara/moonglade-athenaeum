import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import LoginPage from "./components/LoginPage.jsx";
import LoginPageMobile from "./components/LoginPageMobile.jsx";
import SetupWizard from "./components/SetupWizard.jsx";
import SetupWizardMobile from "./components/SetupWizardMobile.jsx";
import useIsMobile from "./hooks/useIsMobile.js";
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
//
// Root is a real component (not a plain `view` variable, unlike before
// 2026-08-02) because useIsMobile() needs a component to subscribe its
// matchMedia listener from -- it live-switches Login and SetupWizard between
// their desktop and mobile presentations on resize/orientation change, not
// just at first paint. App has no mobile build yet, so isMobile doesn't
// affect it.
function Root() {
  const isMobile = useIsMobile();
  if (boot.authenticated === false) {
    return isMobile ? <LoginPageMobile boot={boot} /> : <LoginPage boot={boot} />;
  }
  if (boot.needs_key || boot.catalog_empty) {
    return isMobile ? <SetupWizardMobile boot={boot} /> : <SetupWizard boot={boot} />;
  }
  return <App boot={boot} />;
}
createRoot(document.getElementById("root")).render(<Root />);
