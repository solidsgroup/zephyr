import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { chunkSizeWarningLimit: 1200 },
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000", "/healthz": "http://localhost:8000" },
  },
  test: { environment: "jsdom" },
});
