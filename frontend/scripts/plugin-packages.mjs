/** 通用发现发行插件目录，构建和测试都不维护具体插件列表 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const frontend = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
export const repository = path.dirname(frontend);
export const packageRoot = path.join(
  repository,
  "src/resume_maker/plugin_packages",
);

/** 读取包声明，发现过程只读取 JSON */
export function pluginPackages() {
  return fs
    .readdirSync(packageRoot, { withFileTypes: true })
    .filter((item) => item.isDirectory())
    .map((item) => path.join(packageRoot, item.name))
    .filter((directory) => fs.existsSync(path.join(directory, "manifest.json")))
    .map((directory) => ({
      directory,
      manifest: JSON.parse(
        fs.readFileSync(path.join(directory, "manifest.json"), "utf8"),
      ),
      metadata: JSON.parse(
        fs.readFileSync(path.join(directory, "package.json"), "utf8"),
      ),
    }));
}
