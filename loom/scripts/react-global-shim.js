/* esbuild alias target for the Loom bundle (2026-08-08, the vanilla static/ -> React
   campaign). React is a runtime GLOBAL here -- loaded by loom/vendor/react.production.min.js
   and never bundled -- but the shared React components master-storyboard.jsx now imports
   (GalleryPicker today, more as the campaign moves on) do a normal `import React, {...}
   from "react"` so the gallery's own Vite build can bundle them. build.mjs aliases "react"
   to this file for the Loom build ONLY, so those imports resolve to window.React instead of
   pulling a SECOND copy of React into the bundle (~90 KB bloat + a preamble collision).

   INDIVIDUAL exports on purpose (not `export const {...} = React`): a destructure here would
   put a second `{...} = React` in the bundle that collides with master-storyboard.jsx's own
   injected `var {...} = React` preamble, and esbuild would rename it (breaking the preamble
   staleness guard). Individual re-exports avoid that. */
const React = window.React;
export default React;

export const useState = React.useState;
export const useEffect = React.useEffect;
export const useLayoutEffect = React.useLayoutEffect;
export const useRef = React.useRef;
export const useCallback = React.useCallback;
export const useMemo = React.useMemo;
export const useReducer = React.useReducer;
export const useContext = React.useContext;
export const useImperativeHandle = React.useImperativeHandle;
export const useDebugValue = React.useDebugValue;
export const useId = React.useId;
export const useTransition = React.useTransition;
export const useDeferredValue = React.useDeferredValue;
export const useSyncExternalStore = React.useSyncExternalStore;
export const useInsertionEffect = React.useInsertionEffect;
export const createElement = React.createElement;
export const cloneElement = React.cloneElement;
export const createContext = React.createContext;
export const forwardRef = React.forwardRef;
export const memo = React.memo;
export const lazy = React.lazy;
export const Suspense = React.Suspense;
export const Fragment = React.Fragment;
export const StrictMode = React.StrictMode;
export const Children = React.Children;
export const isValidElement = React.isValidElement;
export const createRef = React.createRef;
export const Component = React.Component;
export const PureComponent = React.PureComponent;
