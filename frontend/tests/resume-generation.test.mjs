import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import { newDocument } from "../src/shared/resume/document.ts";

/** 编译实际生成钩子，以受控网络验证重复点击、失败恢复及固定版本 */
async function application(draft) {
  const fixtures = {
    react: `let values = [], index = 0;
      export function begin() { index = 0; }
      export function useState(initial) {
        const key=index++;
        if (!(key in values)) values[key]=typeof initial === "function" ? initial() : initial;
        return [values[key], value => values[key]=typeof value === "function" ? value(values[key]) : value];
      }
      export function useRef(value) { return values[index++] ??= {current:value}; }
      export function useMemo(work) { index++; return work(); }
      export function useEffect() { index++; }`,
    services: `export const control={draft:${JSON.stringify(draft)},calls:[],waiting:[],fail:false};
      export const storage={getItem:()=>"resume",setItem(){},removeItem(){}};
      export const loadLocal=(key,fallback)=>key.startsWith("rm.resume.v2") ? control.draft : fallback;
      export async function api(path,method,body) {
        control.calls.push({path,method,body});
        if (path.includes("/exports")) {
          await new Promise(done=>control.waiting.push(done));
          if (control.fail) throw new Error("生成暂时失败");
          return {id:"result",resume_id:"resume",pages:1};
        }
        return {...control.draft,...body,version:body.version+1};
      }`,
  };
  const result = await build({
    stdin: {
      contents: `export {useResumeComposition} from "../src/resume_maker/plugin_packages/sys_resume/client/features/resumes/useResumeComposition";
        export * from "react"; export * from "fixture/services";`,
      resolveDir: fileURLToPath(new URL("../", import.meta.url)),
    },
    bundle: true,
    platform: "node",
    format: "esm",
    write: false,
    alias: {
      "@resume-maker/plugin-sdk": fileURLToPath(
        new URL("../src/plugins/shared/exports", import.meta.url),
      ),
    },
    plugins: [
      {
        name: "generation-fixtures",
        setup(builder) {
          builder.onResolve({ filter: /^react$/ }, () => ({
            path: "react",
            namespace: "fixture",
          }));
          builder.onResolve(
            {
              filter:
                /^(fixture\/services|@resume-maker\/plugin-sdk\/shared\/lib\/(api|storage))$/,
            },
            () => ({ path: "services", namespace: "fixture" }),
          );
          builder.onLoad(
            { filter: /.*/, namespace: "fixture" },
            ({ path }) => ({
              contents: fixtures[path],
            }),
          );
        },
      },
    ],
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString("base64")}#${crypto.randomUUID()}`
  );
}

/** 构造没有外部模型、个人信息的独立简历方案 */
function fixture() {
  return {
    id: "resume",
    name: "合成生成方案",
    template_id: null,
    version: 2,
    items: [],
    document: newDocument(),
  };
}

/** 运行实际钩子并读取生成期间状态 */
function harness(module, draft) {
  const notices = [];
  const options = {
    state: { resumes: [draft], honors: [] },
    activeProject: "",
    revisionId: "",
    revisionCache: {},
    workingPreviews: {},
    setRevisionCache() {},
    async reload() {},
    run() {},
    notify: (notice) => notices.push(notice),
  };
  /** 保留钩子引用，重新读取当前生成状态 */
  function render() {
    module.begin();
    return module.useResumeComposition(options);
  }
  return { render, notices, options };
}

/** 等待生成请求进入受控网络屏障 */
async function settle() {
  await new Promise((done) => setImmediate(done));
}

test("生成入口同时触发只保存及生成一次，使用保存后的版本并保持忙碌状态", async () => {
  const draft = fixture();
  const module = await application(draft);
  const { render, notices } = harness(module, draft);
  const initial = render();
  const first = initial.exportResume();
  await settle();
  assert.equal(render().exporting, true);
  await initial.exportResume();
  assert.equal(module.control.calls.length, 2);
  assert.equal(module.control.calls[0].body.version, 2);
  assert.equal(
    module.control.calls[1].path,
    "/resumes/resume/exports?version=3",
  );
  assert.equal(render().exporting, true);
  module.control.waiting.shift()();
  await first;
  assert.equal(render().exporting, false);
  assert.equal(render().exported.id, "result");
  assert.match(notices[0].text, /下载 Word、PDF/);
});

test("生成失败保留方案且释放入口，重试沿用新方案版本", async () => {
  const draft = fixture();
  const module = await application(draft);
  const { render } = harness(module, draft);
  module.control.fail = true;
  const first = render().exportResume();
  const rejected = assert.rejects(first, /生成暂时失败/);
  await settle();
  module.control.waiting.shift()();
  await rejected;
  assert.equal(render().exporting, false);
  assert.equal(render().draft.version, 3);
  assert.equal(render().exported, null);
  module.control.fail = false;
  const retry = render().exportResume();
  await settle();
  assert.equal(
    module.control.calls.at(-1).path,
    "/resumes/resume/exports?version=4",
  );
  module.control.waiting.shift()();
  await retry;
  assert.equal(render().exported.id, "result");
});

test("未采用的经历草稿阻止生成，固定引用保持原样", async () => {
  const draft = fixture();
  draft.items = [
    { project_id: "project", revision_id: "old", highlight_ids: [] },
  ];
  const module = await application(draft);
  const { render, options } = harness(module, draft);
  options.activeProject = "project";
  options.revisionId = "new";
  const content = { title: "合成项目", description: "正文", highlights: [] };
  options.revisionCache = {
    old: { id: "old", project_id: "project", content },
    new: { id: "new", project_id: "project", content },
  };
  await assert.rejects(render().exportResume(), /用于当前简历/);
  assert.equal(module.control.calls.length, 0);
  assert.equal(render().draft.items[0].revision_id, "old");
  assert.equal(render().exporting, false);
});
