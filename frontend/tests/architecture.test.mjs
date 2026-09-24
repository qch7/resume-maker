import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { checkFile } from "../scripts/check-quality.mjs";

for (const [name, module, allowed] of [
  ["shared/example.ts", "../features/example", false],
  ["features/example.ts", "../app/example", false],
  ["features/example.ts", "../shared/example", true],
  ["app/example.ts", "../features/example", true],
]) {
  for (const source of [
    `import { value } from "${module}";`,
    `export { value } from "${module}";`,
    `export * from "${module}";`,
    `void import("${module}");`,
    `void import(\`${module}\`);`,
  ]) {
    test(`${name}: ${source}`, (t) => {
      const directory = fs.mkdtempSync(
        path.join(os.tmpdir(), "resume-architecture-"),
      );
      t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
      const file = path.join(directory, name);
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, source);
      const { errors } = checkFile(file, directory);
      assert.equal(errors.length, allowed ? 0 : 1);
      if (!allowed) assert.match(errors[0], /不允许反向依赖/);
    });
  }
}
