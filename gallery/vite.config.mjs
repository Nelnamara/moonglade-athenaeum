import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "/next/assets/" so the production bundle's own asset references resolve
// through the Flask route that serves gallery/dist. Fixed output names (app.js /
// app.css) so the NEXT_PAGE template in moonglade_gallery.py never chases hashes.
export default defineConfig({
  plugins: [react()],
  base: "/next/assets/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      output: {
        entryFileNames: "app.js",
        chunkFileNames: "chunk-[name].js",
        assetFileNames: "app[extname]",
      },
    },
  },
  server: {
    port: 5199,
    // Dev mode runs against the REAL running server: hot reload with live data.
    proxy: {
      "/api": "http://127.0.0.1:5057",
      "/thumbs": "http://127.0.0.1:5057",
      "/img": "http://127.0.0.1:5057",
      "/full": "http://127.0.0.1:5057",
      "/video-file": "http://127.0.0.1:5057",
      "/branding": "http://127.0.0.1:5057",
    },
  },
});
