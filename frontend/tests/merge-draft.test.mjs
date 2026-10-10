import { test } from "node:test";
import assert from "node:assert/strict";
import {
  acceptDraftConfirmation,
  equal,
  mergeDraft,
  restoreDraft,
} from "../src/shared/lib/mergeDraft.ts";
import {
  restoreSources,
  sourcePaths,
} from "../../src/resume_maker/plugin_packages/sys_resume/client/features/experiences/configurationDrafts.ts";

test("merge independent fields and keep same-field conflicts for review", () => {
  const base = { role: "原角色", period: "", notes: "" };
  const local = { ...base, role: "本页角色", notes: "本页备注" };
  const latest = { ...base, role: "服务器角色", period: "2026" };
  const before = structuredClone([base, local, latest]);
  const merged = mergeDraft(base, local, latest);
  assert.deepEqual(merged.value, {
    role: "本页角色",
    period: "2026",
    notes: "本页备注",
  });
  assert.deepEqual(merged.conflicts, ["role"]);
  assert.deepEqual([base, local, latest], before);
});

test("merge identified fields keeps additions, deletions and remote edits", () => {
  const base = [
    { id: "a", label: "A" },
    { id: "b", label: "B" },
  ];
  const local = [
    { id: "a", label: "A" },
    { id: "c", label: "C" },
  ];
  const latest = [
    { id: "a", label: "新 A" },
    { id: "b", label: "B" },
    { id: "d", label: "D" },
  ];
  const result = mergeDraft(base, local, latest);
  assert.deepEqual(result.value, [
    { id: "a", label: "新 A" },
    { id: "c", label: "C" },
    { id: "d", label: "D" },
  ]);
});

test("delete versus edit and conflicting order require review", () => {
  const base = [
    { id: "a", label: "A" },
    { id: "b", label: "B" },
    { id: "c", label: "C" },
  ];
  const removed = mergeDraft(base, base.slice(1), [
    { ...base[0], label: "更新 A" },
    ...base.slice(1),
  ]);
  assert.ok(removed.conflicts.includes(".a"));
  assert.deepEqual(removed.value, base.slice(1));
  const reordered = mergeDraft(
    base,
    [base[1], base[0], base[2]],
    [base[0], base[2], base[1]],
  );
  assert.ok(reordered.conflicts.includes(".顺序"));
  assert.deepEqual(
    reordered.value.map((item) => item.id),
    ["b", "a", "c"],
  );
});

test("legacy drafts cannot silently borrow the latest baseline", () => {
  const latest = { role: "服务器角色", period: "2026" };
  const cached = { ...latest, role: "旧角色" };
  assert.equal(restoreDraft(cached, latest).baseline, null);
  assert.deepEqual(restoreDraft(null, latest), {
    value: latest,
    baseline: latest,
  });
  const envelope = { value: cached, baseline: { role: "原角色", period: "" } };
  assert.equal(restoreDraft(envelope, latest), envelope);
  assert.equal(equal({ a: 1, b: null }, { b: null, a: 1 }), true);
  assert.equal(equal({}, { a: undefined }), false);
});

test("save confirmation preserves later input and adopts confirmed normalization", () => {
  const submitted = { name: "项目", paths: " path \n", role: "本次角色" };
  const current = { ...submitted, role: "后续角色" };
  const saved = { ...submitted, paths: "path" };
  const confirmed = acceptDraftConfirmation(current, submitted, saved);
  assert.deepEqual(confirmed.value, { ...saved, role: "后续角色" });
  assert.deepEqual(confirmed.baseline, saved);
  const reopened = restoreDraft(confirmed, saved);
  assert.equal(reopened.value.role, "后续角色");
  assert.equal(reopened.baseline.role, "本次角色");
});

test("source cache migration preserves text and requires explicit adoption", () => {
  const latest = { name: "项目", paths: "new" };
  const restored = restoreSources("old\n\n", latest);
  assert.equal(restored.value.paths, "old\n\n");
  assert.equal(restored.baseline, null);
  assert.deepEqual(sourcePaths(" first \n\nsecond "), ["first", "second"]);
});
