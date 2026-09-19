import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";

// The application and the API answer on one origin (decision D16): the session cookie is
// HttpOnly and SameSite=Lax, so a browser would not send it cross-origin. In development this
// proxy is what makes the browser see a single origin; in production the API serves the build.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.API_URL ?? "http://127.0.0.1:8000",
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    manifest: true,
    rollupOptions: {
      output: {
        // React changes far less often than our own code, so it gets its own chunk and stays
        // in the browser's cache across deploys. antd is deliberately *not* listed: naming a
        // package here pulls all of it in, which defeats tree-shaking and cost 150 KB.
        manualChunks: {
          react: ["react", "react-dom", "react-router-dom"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}"],
    // A worker per core exhausts this machine's memory long before it runs out of work, and
    // jsdom workers are not cheap. One is the floor so `--maxWorkers=2` on the command line
    // never conflicts with a higher floor taken from the core count.
    minWorkers: 1,
    maxWorkers: 2,
  },
});
