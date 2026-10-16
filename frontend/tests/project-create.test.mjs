import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";
import { fileURLToPath } from "node:url";

/** 编译真实创建表单，替换浏览器挂载以验证提交结果及输入保留 */
async function application() {
  const output = await build({
    stdin: {
      contents: `export {default as Dialog} from "../src/resume_maker/plugin_packages/sys_resume/client/features/projects/CreateProjectDialog";
        export {begin} from "react";`,
      resolveDir: fileURLToPath(new URL("../", import.meta.url)),
    },
    bundle: true,
    format: "esm",
    jsx: "automatic",
    write: false,
    define: { document: '{"body":null}' },
    plugins: [
      {
        name: "project-form-fixtures",
        setup(builder) {
          builder.onResolve(
            { filter: /^(react|react\/jsx-runtime|react-dom|lucide-react)$/ },
            () => ({ path: "fixture", namespace: "fixture" }),
          );
          builder.onLoad({ filter: /.*/, namespace: "fixture" }, () => ({
            contents: `let values = [], index = 0;
              export function begin() { index = 0; }
              export function useState(initial) {
                const key = index++;
                if (!(key in values)) values[key] = initial;
                return [values[key], value => values[key] = value];
              }
              export function useRef(value) { return values[index++] ??= {current:value}; }
              export function useId() { return "synthetic"; }
              export function useEffect() {}
              export const createPortal = value => value;
              export const jsx = (type, props) => ({type, props}), jsxs = jsx;
              export const LoaderCircle = "loading", Plus = "plus";`,
          }));
        },
      },
    ],
  });
  return import(
    `data:text/javascript;base64,${Buffer.from(output.outputFiles[0].text).toString("base64")}#${crypto.randomUUID()}`
  );
}

/** 在实际表单树中查找输入、提交及错误控件 */
function find(tree, match) {
  if (!tree?.props) return null;
  if (match(tree)) return tree;
  for (const child of [tree.props.children].flat(Infinity)) {
    const found = find(child, match);
    if (found) return found;
  }
  return null;
}

/** 重新渲染真实表单，读取异步处理后的状态 */
function render(module, props) {
  module.begin();
  return module.Dialog(props);
}

test("连续提交共用一次创建请求，成功回传对应项目", async () => {
  const module = await application();
  let resolve,
    calls = 0,
    created;
  const props = {
    onClose: () => assert.fail("提交由成功回调决定后续导航"),
    onCreate: (name) => {
      calls++;
      assert.equal(name, "测试项目");
      return new Promise((done) => (resolve = done));
    },
    onCreated: (project) => (created = project),
  };
  let tree = render(module, props);
  find(tree, (node) => node.type === "input").props.onChange({
    target: { value: "  测试项目  " },
  });
  tree = render(module, props);
  const form = find(tree, (node) => node.type === "form");
  form.props.onSubmit({ preventDefault() {} });
  form.props.onSubmit({ preventDefault() {} });
  assert.equal(calls, 1);
  assert.equal(
    find(render(module, props), (node) => node.type === "input").props.disabled,
    true,
  );
  const project = { id: "new", head_revision: "r1" };
  resolve(project);
  await new Promise((done) => setImmediate(done));
  assert.equal(created, project);
});

test("创建失败保留名称、显示原因并允许重试，取消无需提交", async () => {
  const module = await application();
  let calls = 0,
    closed = 0;
  const props = {
    onClose: () => closed++,
    onCreate: async () => {
      calls++;
      throw new Error("合成失败");
    },
    onCreated: () => assert.fail("失败不能导航"),
  };
  let tree = render(module, props);
  find(tree, (node) => node.type === "input").props.onChange({
    target: { value: "保留名称" },
  });
  for (let attempt = 0; attempt < 2; attempt++) {
    tree = render(module, props);
    find(tree, (node) => node.type === "form").props.onSubmit({
      preventDefault() {},
    });
    await new Promise((done) => setImmediate(done));
    tree = render(module, props);
    assert.equal(
      find(tree, (node) => node.type === "input").props.value,
      "保留名称",
    );
    assert.equal(
      find(tree, (node) => node.props.role === "alert").props.children,
      "合成失败",
    );
  }
  find(
    tree,
    (node) => node.type === "button" && node.props.type === "button",
  ).props.onClick();
  assert.equal(calls, 2);
  assert.equal(closed, 1);
});
