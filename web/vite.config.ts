import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteStaticCopy } from "vite-plugin-static-copy";

// Cesium's workers, widgets and imagery are copied next to the app and loaded
// from /cesium. Nothing is fetched from a CDN or from Cesium ion: the console
// must work on a network with no route to the internet.
const cesiumSource = "node_modules/cesium/Build/Cesium";

export default defineConfig({
  plugins: [
    react(),
    viteStaticCopy({
      targets: ["Workers", "ThirdParty", "Assets", "Widgets"].map((dir) => ({
        src: `${cesiumSource}/${dir}`,
        dest: "cesium",
        // Keep Workers/..., drop node_modules/cesium/Build/Cesium/.
        rename: { stripBase: 4 },
      })),
    }),
  ],
  define: {
    CESIUM_BASE_URL: JSON.stringify("/cesium"),
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: {
    chunkSizeWarningLimit: 6000,
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
  },
});
