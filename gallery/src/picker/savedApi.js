import { useSyncExternalStore } from "react";
import { apiGet, apiPost } from "../api.js";
import { accountCsrf, accountPrefs } from "../hooks/useAccountPrefs.js";
import { createSavedStore } from "./savedCore.js";

/* The Saved tab's one door to /api/model-saved/* (Session S), over api.js. Reads answer {error}
   or the body. Writes carry the session's CSRF token the account store hands out
   (explicit-token class, as api.js's header says every caller does it); the server checks
   READ_ONLY first, sends once, and answers what its read-back found. */

async function write(path, body) {
  await accountPrefs().ensureLoaded();
  return apiPost(path, { ...(body || {}), csrf: accountCsrf() });
}

export const savedApi = {
  state: (modelId) => apiGet("/api/model-saved/state", { model_id: modelId }),
  save: (modelId) => write("/api/model-saved/save", { model_id: modelId }),
  tick: (setId, modelId, on, itemId) => write("/api/model-saved/tick",
    { set_id: setId, model_id: modelId, on: !!on, item_id: itemId || "" }),
  remove: (itemId) => write("/api/model-saved/remove", { item_id: itemId }),
  createSet: (title) => write("/api/model-saved/sets/create", { title }),
};

/* The page's one saved-state store, and the hook that re-renders a picker when it changes. */
export const savedStore = createSavedStore();

export function useSavedVersion() {
  return useSyncExternalStore(savedStore.subscribe, savedStore.version, savedStore.version);
}
