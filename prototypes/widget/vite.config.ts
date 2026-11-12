import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Points at a clean synapse-sdk checkout (default /home/user/synapse-sdk). We never edit it.
const SDK = process.env.SYNAPSE_SDK ?? "/home/user/synapse-sdk";
const W = path.join(SDK, "packages/widget");
const here = __dirname;

export default defineConfig({
  root: here,
  plugins: [react()],
  resolve: {
    alias: [
      { find: "@widget", replacement: path.join(W, "src") },
      { find: /^@\//, replacement: path.join(W, "src") + "/" },
      { find: "@synapse/core-real", replacement: path.join(SDK, "packages/core/src/index") },
      { find: "@synapse/core", replacement: path.join(here, "core-mocked.ts") },
      { find: "vitest", replacement: path.join(here, "vitest-shim.ts") },
      { find: "react/jsx-runtime", replacement: path.join(W, "node_modules/preact/jsx-runtime") },
      { find: "react/jsx-dev-runtime", replacement: path.join(W, "node_modules/preact/jsx-runtime") },
      { find: "react-dom/client", replacement: path.join(W, "node_modules/preact/compat/client") },
      { find: "react-dom", replacement: path.join(W, "node_modules/preact/compat") },
      { find: /^react$/, replacement: path.join(W, "node_modules/preact/compat") },
      { find: /^preact$/, replacement: path.join(W, "node_modules/preact") },
    ],
  },
  esbuild: { jsx: "automatic", jsxImportSource: "preact" },
  server: { port: 5199, host: true, fs: { allow: [SDK, here] } },
  css: { postcss: W },
});
