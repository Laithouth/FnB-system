import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend URL is injected at build/dev time via VITE_BACKEND_WS_URL (see
// .env.example). Defaults to the local dev backend on localhost.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
  },
});
