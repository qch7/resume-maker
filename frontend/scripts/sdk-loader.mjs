/** 逻辑测试解析与构建相同的公开 SDK 子入口，不安装源码别名包 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const exportsRoot = new URL("../src/plugins/shared/exports/", import.meta.url);

/** 在公开出口和相对源码之间补全 TypeScript 后缀，其他依赖使用 Node 默认解析 */
export function resolve(specifier, context, nextResolve) {
  let location;
  if (specifier === "@resume-maker/plugin-sdk")
    location = fileURLToPath(
      new URL("../src/plugins/shared/sdk.ts", import.meta.url),
    );
  else if (specifier.startsWith("@resume-maker/plugin-sdk/"))
    location = fileURLToPath(
      new URL(specifier.slice("@resume-maker/plugin-sdk/".length), exportsRoot),
    );
  else if (specifier.startsWith(".") && context.parentURL?.startsWith("file:"))
    location = fileURLToPath(new URL(specifier, context.parentURL));
  if (location) {
    for (const candidate of [
      location,
      location + ".ts",
      location + ".tsx",
      path.join(location, "index.ts"),
    ])
      if (fs.existsSync(candidate) && fs.statSync(candidate).isFile())
        return { url: pathToFileURL(candidate).href, shortCircuit: true };
  }
  return nextResolve(specifier, context);
}
