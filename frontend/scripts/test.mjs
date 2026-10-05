/** 收集宿主和各插件自己的测试，删除插件目录后不留下测试入口引用 */
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";
import { frontend, pluginPackages } from "./plugin-packages.mjs";

const directories = [
  path.join(frontend, "tests"),
  ...pluginPackages().map((item) => path.join(item.directory, "tests")),
];
const files = directories
  .filter((directory) => fs.existsSync(directory))
  .flatMap((directory) =>
    fs
      .readdirSync(directory)
      .filter((name) => name.endsWith(".test.mjs"))
      .map((name) => path.join(directory, name)),
  );
const result = spawnSync(
  process.execPath,
  [
    "--experimental-strip-types",
    "--import",
    pathToFileURL(path.join(frontend, "scripts/register-sdk.mjs")).href,
    "--test",
    ...files,
  ],
  { stdio: "inherit" },
);
process.exitCode = result.status ?? 1;
