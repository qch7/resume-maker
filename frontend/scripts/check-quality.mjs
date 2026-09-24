/** 检查函数中文说明和前端依赖边界，供本机验证和 CI 共用 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../src",
);
const chinese = /[\u4e00-\u9fff]/;

/** 递归收集应用源码 */
function sourceFiles(directory) {
  const result = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) result.push(...sourceFiles(file));
    else if (/\.tsx?$/.test(file)) result.push(file);
  }
  return result;
}

/** 找到函数说明所在的声明，命名箭头函数的说明放在变量声明前 */
function documentationAnchor(node) {
  if (ts.isParenthesizedExpression(node.parent)) return node.parent;
  if (ts.isVariableDeclaration(node.parent)) return node.parent.parent.parent;
  if (
    ts.isCallExpression(node.parent) &&
    ts.isVariableDeclaration(node.parent.parent) &&
    node.parent.expression.getText() === "useCallback"
  )
    return node.parent.parent.parent.parent;
  return node;
}

/** 检查单个文件的函数说明、语法和从共享层反向依赖业务层的情况 */
export function checkFile(name, sourceRoot = root) {
  const source = fs.readFileSync(name, "utf8");
  const file = ts.createSourceFile(name, source, ts.ScriptTarget.Latest, true);
  const relative = path.relative(sourceRoot, name).replaceAll("\\", "/");
  const errors = [];
  let functions = 0;

  /** 检查具名函数的说明并校验全部导入 */
  function visit(node) {
    if (
      (ts.isFunctionDeclaration(node) ||
        ts.isFunctionExpression(node) ||
        ts.isArrowFunction(node) ||
        ts.isMethodDeclaration(node) ||
        ts.isConstructorDeclaration(node)) &&
      node.body
    ) {
      functions++;
      const anchor = documentationAnchor(node);
      const before = source.slice(0, anchor.getStart(file));
      const start = before.lastIndexOf("/*");
      const comment = before.slice(start);
      const needsDocumentation =
        node.name ||
        ts.isConstructorDeclaration(node) ||
        ts.isVariableStatement(anchor);
      if (
        needsDocumentation &&
        (start < 0 ||
          !comment.endsWith("*/" + comment.match(/\s*$/)[0]) ||
          !chinese.test(comment))
      ) {
        const line =
          file.getLineAndCharacterOfPosition(node.getStart(file)).line + 1;
        errors.push(`${relative}:${line} 缺少紧邻函数声明的中文说明`);
      }
    }
    const specifier =
      ts.isImportDeclaration(node) || ts.isExportDeclaration(node)
        ? node.moduleSpecifier
        : ts.isCallExpression(node) &&
            node.expression.kind === ts.SyntaxKind.ImportKeyword
          ? node.arguments[0]
          : undefined;
    if (specifier && ts.isStringLiteralLike(specifier)) {
      const module = specifier.text;
      if (module.startsWith(".")) {
        const target = path
          .relative(sourceRoot, path.resolve(path.dirname(name), module))
          .replaceAll("\\", "/");
        if (
          (relative.startsWith("shared/") &&
            /^(features|app)\//.test(target)) ||
          (relative.startsWith("features/") && target.startsWith("app/"))
        )
          errors.push(`${relative} 不允许反向依赖 ${target}`);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(file);
  return { errors, functions };
}

/** 执行完整源码检查，导入检查函数时不启动命令行流程 */
function main() {
  const errors = [];
  let functions = 0;
  for (const name of sourceFiles(root)) {
    const result = checkFile(name);
    errors.push(...result.errors);
    functions += result.functions;
  }
  if (errors.length) {
    console.error(errors.join("\n"));
    process.exitCode = 1;
  } else {
    console.log(
      `前端质量检查通过：已检查 ${functions} 个函数和回调，模块依赖方向有效。`,
    );
  }
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
)
  main();
