export interface ConfigSchema {
  [key: string]: unknown;
  type?: string | string[];
  title?: string;
  description?: string;
  properties?: Record<string, ConfigSchema | boolean>;
  default?: unknown;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  multipleOf?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  readOnly?: boolean;
}

export interface ConfigField {
  path: string[];
  pointer: string;
  label: string;
  schema: ConfigSchema;
  kind: "string" | "integer" | "number" | "boolean" | "enum" | "json";
  nullable: boolean;
}

export type ConfigEdit =
  | { operation: "set"; path: string[]; value: unknown }
  | { operation: "reset"; path: string[] };

export interface FieldInput {
  text: string;
  nullValue?: boolean;
  error?: string;
}

export interface ConfigDraft {
  json?: string;
  fields: Record<string, FieldInput>;
  edits: ConfigEdit[];
}

/** 空草稿只记录用户明确修改的字段 */
export function emptyConfigDraft(): ConfigDraft {
  return { fields: {}, edits: [] };
}

/** 配置路径遵循 JSON Pointer 的转义规则 */
export function configPointer(path: string[]): string {
  return (
    "/" +
    path.map((key) => key.replaceAll("~", "~0").replaceAll("/", "~1")).join("/")
  );
}

/** 只遍历 JSON 自有属性，区分缺失、空值和空字符串 */
export function configValue(value: unknown, path: string[]): unknown {
  for (const key of path) {
    if (!value || typeof value !== "object" || !Object.hasOwn(value, key))
      return undefined;
    value = (value as Record<string, unknown>)[key];
  }
  return value;
}

/** 本地引用限定在声明的 schema 内，递归引用保留 JSON 编辑 */
function resolveSchema(
  value: ConfigSchema | boolean,
  root: ConfigSchema,
  depth = 0,
): ConfigSchema {
  if (typeof value === "boolean" || depth >= 20) return {};
  let schema = value;
  const seen = new Set<string>();
  while (typeof schema.$ref === "string") {
    const reference = schema.$ref;
    if (!reference.startsWith("#/") || seen.has(reference) || seen.size >= 20)
      return {};
    seen.add(reference);
    const target = configValue(
      root,
      reference
        .slice(2)
        .split("/")
        .map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~")),
    );
    if (!target || typeof target !== "object") return {};
    const { $ref: _reference, ...siblings } = schema;
    schema = { ...(target as ConfigSchema), ...siblings };
  }
  const union = schema.anyOf ?? schema.oneOf;
  if (Array.isArray(union) && union.length === 2) {
    const branches = union.map((branch) =>
      resolveSchema(branch as ConfigSchema, root, depth + 1),
    );
    const concrete = branches.filter((branch) => branch.type !== "null");
    if (
      concrete.length === 1 &&
      branches.some((branch) => branch.type === "null")
    ) {
      schema = {
        ...concrete[0],
        ...schema,
        type: [String(concrete[0].type), "null"],
      };
    }
  }
  return schema;
}

/** 根据对象属性生成独立控件，数组和复杂联合保留单项 JSON 编辑 */
export function configFields(schema: ConfigSchema): ConfigField[] {
  const result: ConfigField[] = [];
  /** 有限展开已声明的嵌套对象 */
  function walk(value: ConfigSchema, path: string[], labels: string[]) {
    for (const [key, declaration] of Object.entries(value.properties ?? {})) {
      if (declaration === false) continue;
      let child = resolveSchema(declaration, schema);
      if (Object.hasOwn(child, "const"))
        child = { ...child, enum: [child.const] };
      const childPath = [...path, key];
      const label = child.description || child.title || key;
      const types = Array.isArray(child.type) ? child.type : [child.type];
      const nullable = types.includes("null");
      if (child.properties && !nullable && childPath.length < 20) {
        walk(child, childPath, [...labels, label]);
        continue;
      }
      const concreteTypes = types.filter((item) => item !== "null");
      const type = concreteTypes.length === 1 ? concreteTypes[0] : undefined;
      const kind = child.enum?.length
        ? "enum"
        : ["string", "integer", "number", "boolean"].includes(type ?? "")
          ? (type as ConfigField["kind"])
          : "json";
      result.push({
        path: childPath,
        pointer: configPointer(childPath),
        label: [...labels, label].join(" / "),
        schema: child,
        kind,
        nullable: nullable || child.enum?.includes(null) === true,
      });
    }
  }
  walk(resolveSchema(schema, schema), [], []);
  return result;
}

/** 编辑器文本保留数字未完成输入，空值使用独立标志 */
export function configInput(field: ConfigField, value: unknown): FieldInput {
  return {
    text:
      value === undefined || (value === null && field.kind !== "enum")
        ? ""
        : field.kind === "string"
          ? String(value)
          : JSON.stringify(value, null, field.kind === "json" ? 2 : undefined),
    nullValue: value === null && field.kind !== "enum",
  };
}

/** JSON 数值必须有限，避免序列化时把无穷值改成 null */
function finiteJson(value: unknown): boolean {
  if (typeof value === "number") return Number.isFinite(value);
  if (value && typeof value === "object")
    return Object.values(value).every(finiteJson);
  return true;
}

/** 整份配置必须是对象，所有数值保持 JSON 可表示 */
export function parseConfigJson(text: string): Record<string, unknown> {
  const value: unknown = JSON.parse(text);
  if (
    !value ||
    typeof value !== "object" ||
    Array.isArray(value) ||
    !finiteJson(value)
  )
    throw new Error("配置须为 JSON 对象，数值必须有限");
  return value as Record<string, unknown>;
}

/** 输入先检查明确的类型和范围，完整 schema 继续由服务端校验 */
export function parseConfigField(
  field: ConfigField,
  input: FieldInput,
): unknown {
  const { schema, kind } = field;
  if (input.nullValue) {
    if (!field.nullable) throw new Error("此项不接受空值");
    return null;
  }
  let value: unknown;
  if (kind === "string") value = input.text;
  else if (kind === "number" || kind === "integer") {
    if (
      !input.text.trim() ||
      !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(input.text.trim())
    )
      throw new Error("请输入数值");
    value = Number(input.text);
    if (!Number.isFinite(value)) throw new Error("请输入有限数值");
    if (kind === "integer" && !Number.isInteger(value))
      throw new Error("请输入整数");
  } else {
    try {
      value = JSON.parse(input.text);
    } catch {
      throw new Error(kind === "json" ? "请输入有效 JSON" : "请选择有效值");
    }
    if (!finiteJson(value)) throw new Error("请输入有限数值");
    if (kind === "boolean" && typeof value !== "boolean")
      throw new Error("请选择开关值");
    if (
      kind === "enum" &&
      !schema.enum?.some(
        (option) => JSON.stringify(option) === JSON.stringify(value),
      )
    )
      throw new Error("请选择列表中的值");
    if (kind === "json" && schema.type === "array" && !Array.isArray(value))
      throw new Error("此项须为 JSON 数组");
    if (
      kind === "json" &&
      schema.type === "object" &&
      (!value || typeof value !== "object" || Array.isArray(value))
    )
      throw new Error("此项须为 JSON 对象");
  }
  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum)
      throw new Error(`不得小于 ${schema.minimum}`);
    if (schema.maximum !== undefined && value > schema.maximum)
      throw new Error(`不得大于 ${schema.maximum}`);
    if (
      schema.exclusiveMinimum !== undefined &&
      value <= schema.exclusiveMinimum
    )
      throw new Error(`须大于 ${schema.exclusiveMinimum}`);
    if (
      schema.exclusiveMaximum !== undefined &&
      value >= schema.exclusiveMaximum
    )
      throw new Error(`须小于 ${schema.exclusiveMaximum}`);
    if (
      schema.multipleOf &&
      Math.abs(
        value / schema.multipleOf - Math.round(value / schema.multipleOf),
      ) > 1e-8
    )
      throw new Error(`须为 ${schema.multipleOf} 的倍数`);
  }
  if (typeof value === "string") {
    if (
      schema.format === "credential-ref" &&
      value &&
      !/^cred\.[a-f0-9]{32}$/.test(value)
    )
      throw new Error("请通过密码控件保存凭据，此项只接受宿主引用");
    const length = [...value].length;
    if (schema.minLength !== undefined && length < schema.minLength)
      throw new Error(`至少 ${schema.minLength} 个字符`);
    if (schema.maxLength !== undefined && length > schema.maxLength)
      throw new Error(`最多 ${schema.maxLength} 个字符`);
    if (schema.pattern) {
      let pattern: RegExp | undefined;
      try {
        pattern = new RegExp(schema.pattern);
      } catch {
        /* 服务端处理浏览器不支持的表达式 */
      }
      if (pattern && !pattern.test(value)) throw new Error("格式不符合要求");
    }
  }
  return value;
}

/** 父级操作覆盖子级草稿，同级的最后一次输入生效 */
function within(path: string[], ancestor: string[]): boolean {
  return (
    ancestor.length <= path.length &&
    ancestor.every((key, index) => path[index] === key)
  );
}

/** 清理被同一字段覆盖的后续操作，保留其他字段和祖先操作 */
function fieldOperation(draft: ConfigDraft, edit: ConfigEdit): ConfigDraft {
  return {
    ...draft,
    fields: Object.fromEntries(
      Object.entries(draft.fields).filter(
        ([pointer]) =>
          pointer !== configPointer(edit.path) &&
          !pointer.startsWith(configPointer(edit.path) + "/"),
      ),
    ),
    edits: [
      ...draft.edits.filter((previous) => !within(previous.path, edit.path)),
      edit,
    ],
  };
}

/** 有效字段提交 set，未完成输入留在本地并阻止预览 */
export function changeConfigField(
  draft: ConfigDraft,
  field: ConfigField,
  input: FieldInput,
): ConfigDraft {
  let next = draft;
  let error: string | undefined;
  try {
    next = fieldOperation(draft, {
      operation: "set",
      path: field.path,
      value: parseConfigField(field, input),
    });
  } catch (failure) {
    error = (failure as Error).message;
  }
  return {
    ...next,
    fields: { ...next.fields, [field.pointer]: { ...input, error } },
  };
}

/** 恢复操作保留为 reset，不用默认字面量替代继承语义 */
export function resetConfigField(
  draft: ConfigDraft,
  path: string[],
): ConfigDraft {
  if (!path.length) draft = emptyConfigDraft();
  return fieldOperation(draft, { operation: "reset", path });
}

/** 撤销尚未应用的同项恢复，其他改动继续保留 */
export function undoConfigReset(
  draft: ConfigDraft,
  path: string[],
): ConfigDraft {
  return {
    ...draft,
    edits: draft.edits.filter(
      (edit) =>
        edit.operation !== "reset" ||
        edit.path.length !== path.length ||
        !within(edit.path, path),
    ),
  };
}

/** 最新祖先操作决定字段是否正在等待继承值 */
export function configResetPending(
  draft: ConfigDraft,
  path: string[],
): boolean {
  return (
    draft.edits.filter((edit) => within(path, edit.path)).at(-1)?.operation ===
    "reset"
  );
}

/** 高级 JSON 编辑明确替换整份对象，撤销此前字段草稿 */
export function changeConfigJson(text: string): ConfigDraft {
  return { ...emptyConfigDraft(), json: text };
}

/** 草稿错误统一阻止计划提交，不丢弃用户尚未完成的输入 */
export function configDraftError(draft: ConfigDraft): string {
  if (draft.json !== undefined) {
    try {
      parseConfigJson(draft.json);
    } catch {
      return "JSON 配置无效";
    }
  }
  return Object.values(draft.fields).find((field) => field.error)?.error ?? "";
}

/** 字段编辑只发送 set 和 reset，高级 JSON 及新实例才发送整份对象 */
export function configRequest(
  items: { id: string; state: string; config?: Record<string, unknown> }[],
  drafts: Record<string, ConfigDraft>,
) {
  const configs: Record<string, Record<string, unknown>> = {};
  const config_edits: (ConfigEdit & { instance: string })[] = [];
  for (const item of items) {
    const draft = drafts[item.id] ?? emptyConfigDraft();
    const error = configDraftError(draft);
    if (error) throw new Error(`${item.id}：${error}`);
    if (draft.json !== undefined || item.state === "待应用")
      configs[item.id] =
        draft.json !== undefined
          ? parseConfigJson(draft.json)
          : (item.config ?? {});
    config_edits.push(
      ...draft.edits.map((edit) => ({ ...edit, instance: item.id })),
    );
  }
  return { configs, config_edits };
}

/** 复制对象路径时使用自有属性，未涉及的扩展资料保持原值 */
function setConfigValue(
  value: Record<string, unknown>,
  path: string[],
  replacement: unknown,
): Record<string, unknown> {
  const [key, ...rest] = path;
  if (!rest.length) return { ...value, [key]: replacement };
  const child =
    Object.hasOwn(value, key) &&
    value[key] &&
    typeof value[key] === "object" &&
    !Array.isArray(value[key])
      ? (value[key] as Record<string, unknown>)
      : {};
  return { ...value, [key]: setConfigValue(child, rest, replacement) };
}

/** 已知改动用于显示，继承值在计划预览后由服务端返回 */
export function draftConfigValue(
  base: Record<string, unknown>,
  draft: ConfigDraft,
): Record<string, unknown> {
  let value = base;
  if (draft.json !== undefined) {
    try {
      value = parseConfigJson(draft.json);
    } catch {
      return base;
    }
  }
  for (const edit of draft.edits)
    if (edit.operation === "set")
      value = setConfigValue(value, edit.path, edit.value);
  return value;
}

/** 来源名称使用简短中文，配置文件只显示其组合名称 */
export function configSource(source: string | undefined): string {
  if (source === "default" || !source) return "默认";
  if (source === "workspace") return "自定义";
  if (source === "startup") return "本次启动";
  if (source.startsWith("bundle:")) return "配置文件 · " + source.slice(7);
  return source;
}

/** 字段旁只保留简短的数值范围 */
export function configRange(schema: ConfigSchema): string {
  if (
    schema.minimum !== undefined &&
    schema.maximum !== undefined &&
    schema.exclusiveMinimum === undefined &&
    schema.exclusiveMaximum === undefined
  )
    return `${schema.minimum}–${schema.maximum}`;
  const lower =
    schema.exclusiveMinimum !== undefined
      ? `> ${schema.exclusiveMinimum}`
      : schema.minimum !== undefined
        ? `≥ ${schema.minimum}`
        : "";
  const upper =
    schema.exclusiveMaximum !== undefined
      ? `< ${schema.exclusiveMaximum}`
      : schema.maximum !== undefined
        ? `≤ ${schema.maximum}`
        : "";
  return [lower, upper].filter(Boolean).join(" · ");
}
