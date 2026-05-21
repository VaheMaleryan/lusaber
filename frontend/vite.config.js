// Lusaber · Լուսաբեր — Vite config.
//
// `base` is set to "/lusaber/" so the assets resolve correctly when
// the production build is served from
// `https://vahemaleryan.github.io/lusaber/`. For an apex-domain
// deployment (e.g. lusaber.app), override with VITE_BASE_PATH=/.
//
// The frontend talks directly to the backend via the absolute URL
// configured by VITE_API_URL (see frontend/App.jsx). CORS is handled
// server-side in api/main.py.

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  base: process.env.VITE_BASE_PATH ?? "/lusaber/",
  root: ".",
  server: {
    port: 5173,
    host: "127.0.0.1",
    strictPort: false,
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
