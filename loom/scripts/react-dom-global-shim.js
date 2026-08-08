/* esbuild alias target for the Loom bundle -- react-dom's turn of the same story as
   react-global-shim.js: ReactDOM is a runtime GLOBAL (loom/vendor/react-dom.production.min.js),
   so a shared component's `import ... from "react-dom"` (e.g. createPortal) resolves here to
   window.ReactDOM instead of bundling a second copy. Individual exports, same reason as the
   React shim (no `{...} = ReactDOM` destructure to collide with an injected preamble). */
const ReactDOM = window.ReactDOM;
export default ReactDOM;

export const createPortal = ReactDOM.createPortal;
export const flushSync = ReactDOM.flushSync;
export const createRoot = ReactDOM.createRoot;
export const hydrateRoot = ReactDOM.hydrateRoot;
export const render = ReactDOM.render;
export const unmountComponentAtNode = ReactDOM.unmountComponentAtNode;
export const findDOMNode = ReactDOM.findDOMNode;
