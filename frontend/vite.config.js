import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
// Dev server proxies the API (incl. the SSE stream at /api/events) to the FastAPI backend.
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        proxy: {
            "/api": {
                target: "http://localhost:8080",
                changeOrigin: true,
            },
        },
    },
    build: {
        outDir: "dist",
    },
});
