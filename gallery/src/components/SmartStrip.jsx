import React from "react";
import Icon from "../icons/Icons.jsx";
import { smartQueryLine } from "../curation/curationCore.js";
import "../styles/curation.css";

/* THE STRIP OVER THE GRID (Session N, N1). Three states, one row:

   OPEN. A smart collection is open: its name and its saved query, marked live, with the
   refresh -- opening a smart collection is running its query, and Refresh runs it again (a
   rating or a mark made since has moved pictures in or out). Edit query hands the query to
   the search field.

   EDITING. The page's prose ("open the collection, change the search, and Save over it") gets
   its own state, because nothing else says you are changing a saved search. Save over
   replaces the query, Save as new keeps the old one, Cancel drops the edit.

   DRAFT. A search is applied and no collection is open: the row offers "Save as smart
   collection". The page draws that button beside the search field; the shipped library bar has
   no width to spare for it (measured at 1280: it pushed the layout strip over the help chip),
   so it sits on the row directly under the bar and appears once there is a search to save. */
export default function SmartStrip({ name, query, editing, draft, canSave, onRefresh, onEdit, onSaveOver, onSaveNew, onSaveDraft, onCancel }) {
  if (editing) {
    return (
      <div className="mgcu-strip" role="status">
        <span className="mgcu-strip-name"><Icon name="collection" /> Editing {"“"}{editing}{"”"}</span>
        <span className="mgcu-strip-q">Change the search, then save it over the collection.</span>
        <button type="button" className="mgcu-btn primary" disabled={!canSave} onClick={onSaveOver}>Save over {"“"}{editing}{"”"}</button>
        <button type="button" className="mgcu-btn" disabled={!canSave} onClick={onSaveNew}>Save as new</button>
        <button type="button" className="mgcu-btn" onClick={onCancel}>Cancel</button>
      </div>
    );
  }
  if (name) {
    return (
      <div className="mgcu-strip">
        <span className="mgcu-strip-name"><Icon name="collection" /> {name} {"⟳"}</span>
        <code className="mgcu-strip-q">{smartQueryLine(query)}</code>
        <button type="button" className="mgcu-btn" title="Run the saved query again" onClick={onRefresh}>{"⟳"} Refresh</button>
        <button type="button" className="mgcu-btn" title="Change the saved search" onClick={onEdit}>Edit query</button>
      </div>
    );
  }
  return (
    <div className="mgcu-strip">
      <code className="mgcu-strip-q"><Icon name="search" /> {draft}</code>
      <button type="button" className="mgcu-btn primary" title="Save this search as a live collection: it stores the search, never a list of pictures"
        onClick={onSaveDraft}>Save as smart collection {"⟳"}</button>
    </div>
  );
}
