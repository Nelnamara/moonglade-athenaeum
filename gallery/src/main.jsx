import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import LoginPage from "./components/LoginPage.jsx";
import "./styles.css";

const boot = window.MG_BOOT || {};
// boot.authenticated is only ever false on /login's non-bootstrap render (see
// moonglade_gallery.py's login() route) -- App never mounts in that case, so
// none of its authenticated-only effects (fetchLibrary, fetchAccount, ...)
// can fire against a session that doesn't exist yet.
const view = boot.authenticated === false ? <LoginPage boot={boot} /> : <App boot={boot} />;
createRoot(document.getElementById("root")).render(view);
