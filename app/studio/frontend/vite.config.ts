import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `npm run dev` proxies the API to a running `cleansweep studio --no-browser`.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  build: { outDir: "dist", chunkSizeWarningLimit: 1500 },
  // css: the exported report inlines styles.css (a ?raw import, empty without it)
  test: { include: ["src/**/*.test.ts"], environment: "node", css: true },
});
