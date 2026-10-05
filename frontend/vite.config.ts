import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import fs from "node:fs";
import path from "node:path";

const shared = ["react", "jsx-runtime", "react-dom", "react-dom-client", "sdk"];
const imports = {
  react: "/shared/react.js",
  "react/jsx-runtime": "/shared/jsx-runtime.js",
  "react-dom": "/shared/react-dom.js",
  "react-dom/client": "/shared/react-dom-client.js",
  "@resume-maker/plugin-sdk": "/shared/sdk.js",
  "@resume-maker/plugin-sdk/": "/shared/sdk/",
};

export default defineConfig({
  resolve: {
    alias: [
      {
        find: /^@resume-maker\/plugin-sdk\/(.+)$/,
        replacement: path.resolve("src/plugins/shared/exports") + "/$1",
      },
    ],
  },
  plugins: [
    react(),
    {
      name: "plugin-shared-importmap",
      /** 预构建插件使用固定公开入口，实际依赖由同一构建图去重 */
      transformIndexHtml() {
        return [
          {
            tag: "script",
            attrs: { type: "importmap" },
            children: JSON.stringify({ imports }),
            injectTo: "head-prepend",
          },
        ];
      },
    },
  ],
  build: {
    rollupOptions: {
      input: {
        main: "index.html",
        ...Object.fromEntries(
          shared.map((name) => [
            `shared/${name}`,
            `src/plugins/shared/${name}.ts`,
          ]),
        ),
        ...Object.fromEntries(
          fs
            .readdirSync("src/plugins/shared/exports", { recursive: true })
            .map(String)
            .filter((name) => /\.tsx?$/.test(name))
            .map((name) => [
              `shared/sdk/${name.replaceAll("\\", "/").replace(/\.tsx?$/, "")}.js`,
              path.join("src/plugins/shared/exports", name),
            ]),
        ),
      },
      preserveEntrySignatures: "strict",
      output: {
        entryFileNames: (chunk) =>
          chunk.name.startsWith("shared/")
            ? chunk.name.endsWith(".js")
              ? "[name]"
              : "[name].js"
            : "assets/[name]-[hash].js",
        manualChunks: {
          "react-runtime": [
            "react",
            "react-dom",
            "react-dom/client",
            "react/jsx-runtime",
          ],
        },
      },
    },
  },
});
