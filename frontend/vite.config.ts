import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `npm run build` writes straight into the backend, which serves the UI at
// http://127.0.0.1:8000 -- so running ClipForge needs no Node.js at all.
// `npm run dev` (hot reload) proxies API calls to that same backend.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../backend/app/static",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
