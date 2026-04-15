import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "localhost",
    port: 3000,
    strictPort: true,
    open: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8001",
      },
      "/ws": {
        target: "ws://127.0.0.1:8001",
        ws: true,
        timeout: 120000,
      },
    },
  },
});
