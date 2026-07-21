import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  return {
    plugins: [react()],
    server: {
      proxy: {
        "/api": `http://127.0.0.1:${env.DA_BIND_PORT ?? "18000"}`,
      },
    },
    test: { environment: "jsdom", exclude: ["node_modules/**", "e2e/**"] },
  };
});
