import { test } from "node:test";
import assert from "node:assert/strict";
import { appendPath } from "../src/shared/lib/paths.ts";

test("文件夹选择追加来源并保留中文、空格及原有顺序", /* 新文件夹不能覆盖已有项目来源。 */ () => {
  assert.equal(
    appendPath("D:\\项目一\nE:\\Project two", "F:\\新的 来源"),
    "D:\\项目一\nE:\\Project two\nF:\\新的 来源",
  );
  assert.equal(appendPath("", "D:\\项目"), "D:\\项目");
});

test("重复选择相同 Windows 文件夹不会增加重复行或改写原文", /* 路径大小写和末尾斜杠不产生重复来源。 */ () => {
  const original = "D:\\Project\\\nE:\\另一个项目\n";
  assert.equal(appendPath(original, "d:/project"), original);
  assert.equal(appendPath("D:\\\n", "d:/"), "D:\\\n");
});
