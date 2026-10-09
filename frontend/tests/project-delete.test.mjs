import assert from "node:assert/strict";
import test from "node:test";
import {
  projectDeletionBlocker,
  projectDeletionIds,
} from "../src/features/projects/deletion.ts";

const projects = [
  { id: "parent" },
  { id: "child", parent_id: "parent" },
  { id: "grandchild", parent_id: "child" },
  { id: "other" },
];
const draft = { items: [] };

test("saved resumes block deletion of a project group even when the current draft removed it", () => {
  const ids = projectDeletionIds(projects, "parent");
  assert.deepEqual([...ids], ["parent", "child", "grandchild"]);
  const resumes = [
    {
      name: "其他简历",
      items: [{ project_id: "grandchild", highlight_ids: [] }],
    },
  ];
  assert.match(
    projectDeletionBlocker(ids, resumes, draft, []),
    /其他简历.*不能删除/,
  );
  assert.equal(
    projectDeletionBlocker(new Set(["other"]), resumes, draft, []),
    "",
  );
});

test("unsaved current resume references and queued or running jobs block deletion", () => {
  const ids = new Set(["child"]);
  assert.match(
    projectDeletionBlocker(ids, [], { items: [{ project_id: "child" }] }, []),
    /当前简历/,
  );
  for (const status of ["queued", "running"])
    assert.match(
      projectDeletionBlocker(ids, [], draft, [{ project_id: "child", status }]),
      /AI 任务/,
    );
  assert.equal(
    projectDeletionBlocker(ids, [], draft, [
      { project_id: "child", status: "completed" },
    ]),
    "",
  );
  assert.deepEqual(
    [...projectDeletionIds(projects, "child")],
    ["child", "grandchild"],
  );
});
