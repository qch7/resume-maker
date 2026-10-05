/** 独立构建每个客户端包，React 和公开 SDK 由宿主提供 */
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { build } from "vite";
import react from "@vitejs/plugin-react";
import { frontend, pluginPackages, repository } from "./plugin-packages.mjs";

/** 为所有构建产物登记摘要，宿主只发布这一索引内的文件 */
function artifactIndex(directory) {
  return Object.fromEntries(
    fs
      .readdirSync(directory, { recursive: true })
      .map((name) => String(name).replaceAll("\\", "/"))
      .filter((name) => fs.statSync(path.join(directory, name)).isFile())
      .sort()
      .map((name) => [
        name,
        crypto
          .createHash("sha256")
          .update(fs.readFileSync(path.join(directory, name)))
          .digest("hex"),
      ]),
  );
}

for (const item of pluginPackages()) {
  const source = item.metadata.resumeMaker.client;
  if (!source) continue;
  const entry = path.resolve(item.directory, source);
  if (!entry.startsWith(item.directory + path.sep) || !fs.existsSync(entry))
    throw new Error(`插件客户端入口无效：${item.manifest.id}`);
  const output = path.join(
    repository,
    ".local/plugin-builds",
    path.basename(item.directory),
  );
  await build({
    configFile: false,
    root: frontend,
    plugins: [react()],
    resolve: {
      alias: Object.fromEntries(
        Object.keys(
          JSON.parse(
            fs.readFileSync(path.join(frontend, "package.json"), "utf8"),
          ).dependencies,
        )
          .filter((name) => !["react", "react-dom"].includes(name))
          .map((name) => [name, path.join(frontend, "node_modules", name)]),
      ),
    },
    build: {
      outDir: output,
      emptyOutDir: true,
      rollupOptions: {
        input: entry,
        external: (name) =>
          [
            "react",
            "react/jsx-runtime",
            "react-dom",
            "react-dom/client",
          ].includes(name) ||
          name === "@resume-maker/plugin-sdk" ||
          name.startsWith("@resume-maker/plugin-sdk/"),
        preserveEntrySignatures: "strict",
        output: {
          entryFileNames: "plugin.js",
          chunkFileNames: "chunks/[name]-[hash].js",
          paths: (name) =>
            name.startsWith("@resume-maker/plugin-sdk/")
              ? "/shared/sdk/" +
                name.slice("@resume-maker/plugin-sdk/".length) +
                ".js"
              : name,
        },
      },
    },
  });
  fs.writeFileSync(
    path.join(output, "artifacts.json"),
    JSON.stringify(artifactIndex(output)) + "\n",
  );
}
