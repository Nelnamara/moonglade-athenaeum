import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import AppMobile from "./components/AppMobile.jsx";
import LoginPage from "./components/LoginPage.jsx";
import LoginPageMobile from "./components/LoginPageMobile.jsx";
import SetupWizard from "./components/SetupWizard.jsx";
import SetupWizardMobile from "./components/SetupWizardMobile.jsx";
import useIsMobile from "./hooks/useIsMobile.js";
import { installNotify, NotifyRoot } from "./notify/index.jsx";
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
// needs_assets (2026-08-10, docs/DECISIONS.md "The asset container, re-scoped from
// scratch") joins this condition for exactly the case the owner's own placement ruling
// named: an install PAST the wizard (real key, real synced catalog) that is still
// missing the container -- moved to a new machine, or an old checkout that predates the
// downloader entirely. Without this, such an install would silently render App with an
// undressed header/marks forever, since needs_key/catalog_empty are both already false
// by then and nothing else would ever route it back to the wizard. Found live 2026-08-10
// checking this exact scenario -- the wizard never mounted at all until this joined.
// A brand-new install still sees the SAME wizard either way (needs_key is already true),
// so this changes nothing for the common case, only closes the gap for the standalone one.
//
// Root is a real component (not a plain `view` variable, unlike before
// 2026-08-02) because useIsMobile() needs a component to subscribe its
// matchMedia listener from -- it live-switches every surface between its
// desktop and mobile presentations on resize/orientation change, not just at
// first paint (a live cross-breakpoint resize genuinely remounts whichever
// side wasn't showing, on every surface this file mounts -- nothing new here).
// AppMobile.jsx (2026-08-02 initial cut was Gallery-tab-only; Create tab landed
// 2026-08-03, Control tab landed 2026-08-03 too) now mounts real, fully wired
// Gallery/Create/Control tabs -- see its own header comment for the full
// "what's real" account (the only remaining sub-placeholders are inside
// Create: Edit's Fixer sub-tab). Adding it here does not change App.jsx's own
// behavior at all: App only ever mounts when isMobile is false, exactly as
// before this change.
// The notify system (toasts · Activity tray · achievement celebrations · the spend-critical
// Jobs poller) -- installed for every AUTHENTICATED render, matching the old shell rule that
// LOGIN_PAGE never loaded mg-notify.js. installNotify() publishes the window.Toast/Jobs/
// JobsCard/Ach compat surface and starts the background singletons; <NotifyRoot/> portals the
// visible UI to document.body. The engines live outside the React tree on purpose (a paid
// generation's poll loop must survive any view unmounting) -- see gallery/src/notify/.
if (boot.authenticated !== false) installNotify();

function Root() {
  const isMobile = useIsMobile();
  if (boot.authenticated === false) {
    return isMobile ? <LoginPageMobile boot={boot} /> : <LoginPage boot={boot} />;
  }
  if (boot.needs_key || boot.catalog_empty || boot.needs_assets) {
    return (
      <>
        {isMobile ? <SetupWizardMobile boot={boot} /> : <SetupWizard boot={boot} />}
        <NotifyRoot />
      </>
    );
  }
  return (
    <>
      {isMobile ? <AppMobile boot={boot} /> : <App boot={boot} />}
      <NotifyRoot />
    </>
  );
}
createRoot(document.getElementById("root")).render(<Root />);
