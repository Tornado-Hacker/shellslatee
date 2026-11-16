import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  base: "./",
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: "127.0.0.1",
    watch: { ignored: ["**/src-tauri/**"] },
    proxy: {
      "/api": { target: process.env.SHELLSLATEE_URL ?? "http://127.0.0.1:8677", changeOrigin: true },
      "/media": { target: process.env.SHELLSLATEE_URL ?? "http://127.0.0.1:8677", changeOrigin: true },
    },
  },
  build: {
    target: "es2022",
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
});
