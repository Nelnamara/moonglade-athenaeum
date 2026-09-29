import { apiGet, apiPost } from "../api.js";

/* The recipe surfaces' one door to /api/recipes/* (over api.js, the one request module).
   Reads answer {error} or the body; writes carry the CSRF token /api/recipes/meta hands
   out (explicit-token class, as api.js's header says every caller does it), with the
   page's boot token as the fallback. */

let _meta = null;
let _metaP = null;

function bootCsrf() {
  try { return (window.MG_BOOT && window.MG_BOOT.csrf) || ""; } catch { return ""; }
}

/** {categories, model_types, csrf, user_id, max_recipes} -- asked once per page. */
export function recipeMeta(force) {
  if (_meta && !force) return Promise.resolve(_meta);
  if (_metaP && !force) return _metaP;
  _metaP = apiGet("/api/recipes/meta").then((d) => {
    if (d && !d.error) _meta = d;
    _metaP = null;
    return d || {};
  });
  return _metaP;
}

async function write(path, body) {
  const m = await recipeMeta();
  const csrf = (m && m.csrf) || bootCsrf();
  return apiPost(path, { ...(body || {}), csrf });
}

export const recipesApi = {
  market: (q) => apiGet("/api/recipes/market", q),
  capability: (modelType, modelId) => apiGet("/api/recipes/capability", modelId ? { model_id: modelId } : { model_type: modelType }),
  batch: (ids) => apiGet("/api/recipes/batch", { ids: (ids || []).join(",") }),
  recent: (modelType) => apiGet("/api/recipes/recent", { limit: 30, model_type: modelType || "" }),
  mine: (cursor, sort) => apiGet("/api/recipes/mine", { cursor: cursor || "", sort: sort || "latest" }),
  styleCode: (code, versionId) => apiGet("/api/recipes/style-code", { code, version_id: versionId }),
  detail: (id) => apiGet("/api/recipes/" + encodeURIComponent(id)),
  artworks: (id, page) => apiGet("/api/recipes/" + encodeURIComponent(id) + "/artworks", { page: page || 1, page_size: 12 }),
  tasks: (id, usage) => apiGet("/api/recipes/" + encodeURIComponent(id) + "/tasks", { usage: usage || "" }),
  fromImage: (mediaId, check) => apiGet("/api/recipes/from-image", { media_id: mediaId, check: check ? 1 : "" }),
  sets: () => apiGet("/api/recipes/sets"),
  setsFor: (id) => apiGet("/api/recipes/sets/for/" + encodeURIComponent(id)),
  setItems: (sid) => apiGet("/api/recipes/sets/" + encodeURIComponent(sid) + "/items"),
  publish: (draft, recipeId) => write("/api/recipes/publish", { draft, recipe_id: recipeId || "" }),
  update: (recipeId, draft, version) => write("/api/recipes/update", { recipe_id: recipeId, draft, version }),
  transition: (recipeId, to) => write("/api/recipes/transition", { recipe_id: recipeId, to }),
  setCreate: (title) => write("/api/recipes/sets/create", { title }),
  setToggle: (setId, recipeId, on, itemId) => write("/api/recipes/sets/toggle", { set_id: setId, recipe_id: recipeId, on: !!on, item_id: itemId || "" }),
};
