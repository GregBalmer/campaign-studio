import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During UI development, run the Python app (python3 start.py) and `npm run dev`;
// API and image requests are forwarded to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/files": "http://127.0.0.1:8765",
    },
  },
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 800 },
});
