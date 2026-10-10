import assert from "node:assert/strict";
import test from "node:test";
import { build } from "esbuild";
import { fileURLToPath } from "node:url";

/** 保留实际偏好恢复和保存代码，以合成后端规则及工作区存储验证启动行为 */
async function application() {
  const result = await build({
    entryPoints: [
      fileURLToPath(
        new URL(
          "../src/shared/hooks/useActivityPreferences.ts",
          import.meta.url,
        ),
      ),
    ],
    bundle: true,
    format: "esm",
    platform: "browser",
    write: false,
    plugins: [
      {
        name: "activity-fixtures",
        setup(builder) {
          builder.onResolve(
            { filter: /^react$|\/lib\/(api|storage)$/ },
            (args) => ({
              path: args.path,
              namespace: "fixture",
            }),
          );
          builder.onLoad({ filter: /.*/, namespace: "fixture" }, (args) => ({
            contents:
              args.path === "react"
                ? "export function useSyncExternalStore(_subscribe, current) { return current(); }"
                : args.path.endsWith("/api")
                  ? `export async function api(path) {
                    if (path !== "/activity/defaults") throw new Error(path);
                    return {hidden_rules: globalThis.activityFixture.defaults};
                  }`
                  : `export function loadLocal(_key, fallback) { return globalThis.activityFixture.saved ?? fallback; }
                  export const storage = {setItem(_key, value) { globalThis.activityFixture.saved = JSON.parse(value); }};`,
            loader: "js",
          }));
        },
      },
    ],
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString("base64")}`
  );
}

test("默认规则来自后端，界面保存默认后继续继承文件变化", async () => {
  globalThis.activityFixture = {
    defaults: ["POST /api/plugins/windows", "workspace.state"],
    saved: {
      hiddenRules: "/api/obsolete",
      hidePolling: false,
      detailWidth: 520,
    },
  };
  try {
    const app = await application();
    await app.initializeActivityPreferences();
    let state = app.useActivityPreferences();
    assert.equal(
      state.preferences.hiddenRules,
      globalThis.activityFixture.defaults.join("\n"),
    );
    assert.equal(state.preferences.hidePolling, false);
    assert.equal(state.preferences.showStarts, false);
    assert.equal(state.preferences.detailWidth, 520);
    state.setPreferences((current) => ({
      ...current,
      detailWidth: 600,
      showStarts: true,
    }));
    assert.equal(globalThis.activityFixture.saved.rulesOverride, undefined);
    assert.equal(globalThis.activityFixture.saved.hiddenRules, undefined);
    globalThis.activityFixture.defaults = ["/api/changed"];
    await app.initializeActivityPreferences();
    state = app.useActivityPreferences();
    assert.equal(state.preferences.hiddenRules, "/api/changed");
    assert.equal(state.preferences.showStarts, true);
    state.setPreferences((current) => ({ ...current, hiddenRules: "" }));
    await app.initializeActivityPreferences();
    assert.equal(app.useActivityPreferences().preferences.hiddenRules, "");
    state = app.useActivityPreferences();
    state.setPreferences((current) => ({
      ...current,
      hiddenRules: state.defaultRules,
    }));
    await app.initializeActivityPreferences();
    assert.equal(
      app.useActivityPreferences().preferences.hiddenRules,
      "/api/changed",
    );
  } finally {
    delete globalThis.activityFixture;
  }
});
