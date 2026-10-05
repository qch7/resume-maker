import type { ComponentType } from "react";
import type { ClientDescriptor } from "../shared/lib/capabilities";
import type { WorkflowInput } from "./slots";
import type { DocumentPreviewer, PreviewInput } from "./documents";
import {
  activityPresentation,
  type ActivityInput,
  type ActivityPresenter,
} from "./activity.ts";

export type JsonValue =
  | null
  | boolean
  | number
  | string
  | JsonValue[]
  | { [key: string]: JsonValue };

export interface Command {
  title: string;
  shortcut?: string;
  run(context: { signal: AbortSignal }): void | Promise<void>;
}

export interface FieldEditorProps {
  value: JsonValue | undefined;
  onChange(value: JsonValue): void;
}

export interface FieldEditor {
  title: string;
  component: ComponentType<FieldEditorProps>;
}

export interface WorkflowStatus {
  done: boolean;
  text: string;
}

export interface WorkflowStep {
  title: string;
  state: string;
  command: string;
}

export interface ClientExtensionPoints {
  "documents.previewers": DocumentPreviewer;
  "activity.presenters": ActivityPresenter;
  commands: Command;
  "resume.field_editors": FieldEditor;
  "workflow.steps": WorkflowStep;
  "workflow.state_contributors": {
    evaluate(input: Readonly<WorkflowInput>): WorkflowStatus;
  };
}

export interface Extension<K extends keyof ClientExtensionPoints> {
  owner: string;
  id: string;
  version: "1.0.0";
  order: number;
  value: ClientExtensionPoints[K];
}

/** 校验插件返回的 JSON 值，拒绝隐式丢失、非有限数值和过大的草稿 */
export function jsonCopy<T>(value: T): T {
  const encoded = JSON.stringify(value, (_key, item) => {
    if (
      item === undefined ||
      typeof item === "function" ||
      typeof item === "symbol" ||
      (typeof item === "number" && !Number.isFinite(item))
    )
      throw new Error("插件资料必须是 JSON 值。");
    return item;
  });
  if (new TextEncoder().encode(encoded).length > 1024 * 1024)
    throw new Error("插件资料超过 1 MB，请使用资源引用。");
  return JSON.parse(encoded) as T;
}

/** 递归冻结独立资料副本，扩展状态计算不能修改工作区草稿 */
function freeze<T>(value: T): Readonly<T> {
  if (value && typeof value === "object") {
    for (const item of Object.values(value)) freeze(item);
    Object.freeze(value);
  }
  return value;
}

/** 使用明确修饰键避免接管输入字符和依赖安装顺序选择冲突命令 */
export function normalizeShortcut(value: string): string {
  const parts = value.toLowerCase().split("+");
  const key = parts.pop();
  const modifiers = new Set(parts);
  if (
    !key ||
    !/^[a-z0-9]$/.test(key) ||
    !modifiers.has("mod") ||
    modifiers.size !== parts.length ||
    parts.some((part) => !["mod", "shift", "alt"].includes(part))
  )
    throw new Error("快捷键应为 Mod+[Shift+][Alt+]字母或数字。");
  return [...parts.sort(), key].join("+");
}

/** 每个窗口持有独立扩展表，贡献撤销后旧引用不能再执行命令 */
export function createClientExtensions(deactivateTimeoutMs = 5000) {
  const entries = new Map<string, Extension<keyof ClientExtensionPoints>>();
  const runs = new Map<
    string,
    { owner: string; controller: AbortController; done: Promise<void> }
  >();
  const draining = new Set<string>();

  /** 先同时发送取消，再等待实际收尾，超时不移除运行记录 */
  async function waitForCommands(
    active: Array<{ controller: AbortController; done: Promise<void> }>,
  ) {
    for (const run of active) run.controller.abort();
    if (!active.length) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        Promise.all(active.map((run) => run.done.catch(() => undefined))),
        new Promise<never>((_resolve, reject) => {
          timer = setTimeout(
            () => reject(new Error("命令未结束，暂不能卸载或确认插件切换。")),
            deactivateTimeoutMs,
          );
        }),
      ]);
    } finally {
      clearTimeout(timer);
    }
  }

  /** 切换前冻结受影响实例的新命令，保留注册供计划取消后继续使用 */
  async function drain(owners: readonly string[]) {
    for (const owner of owners) draining.add(owner);
    const selected = new Set(owners);
    await waitForCommands(
      [...runs.values()].filter((run) => selected.has(run.owner)),
    );
  }

  /** 宿主确认计划结束或取消后恢复当前代次的命令入口 */
  function resume(owners: readonly string[]) {
    for (const owner of owners) draining.delete(owner);
  }

  /** 只登记清单声明且属于本插件命名空间的已知版本贡献 */
  function contribute<K extends keyof ClientExtensionPoints>(
    descriptor: ClientDescriptor,
    point: K,
    id: string,
    value: ClientExtensionPoints[K],
    order = 100,
    version = "1.0.0",
  ) {
    const key = `${point}:${id}`;
    if (
      !id.startsWith(descriptor.id + "/") ||
      !/^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,150}$/.test(
        id.slice(descriptor.id.length + 1),
      ) ||
      !descriptor.contributes?.[point]?.includes(id) ||
      entries.has(key) ||
      version !== "1.0.0" ||
      !Number.isSafeInteger(order)
    )
      throw new Error(`未声明、重复或不兼容的客户端贡献：${point}/${id}`);
    validate(point, value);
    if (point === "commands") {
      const command = value as Command;
      const shortcut = command.shortcut && normalizeShortcut(command.shortcut);
      if (
        shortcut &&
        list("commands").some(
          (item) =>
            item.value.shortcut &&
            normalizeShortcut(item.value.shortcut) === shortcut,
        )
      )
        throw new Error(`快捷键冲突：${command.shortcut}`);
    }
    if (
      point === "resume.field_editors" &&
      list(point).some((item) => item.owner === descriptor.id)
    )
      throw new Error("每个插件命名空间只能登记一个资料编辑器。");
    entries.set(
      key,
      Object.freeze({
        owner: descriptor.id,
        id,
        version: "1.0.0",
        order,
        value: Object.freeze(
          point === "activity.presenters"
            ? {
                ...value,
                sources: Object.freeze([
                  ...(value as ActivityPresenter).sources,
                ]),
              }
            : point === "documents.previewers"
              ? {
                  ...value,
                  formats: Object.freeze([
                    ...(value as DocumentPreviewer).formats,
                  ]),
                }
              : { ...value },
        ) as ClientExtensionPoints[K],
      }),
    );
    return async () => {
      entries.delete(key);
      const active = point === "commands" && runs.get(id);
      if (active) {
        await waitForCommands([active]);
      }
    };
  }

  /** 返回稳定排序的只读快照，调用者不能修改注册表 */
  function list<K extends keyof ClientExtensionPoints>(
    point: K,
  ): readonly Extension<K>[] {
    return Object.freeze(
      [...entries.entries()]
        .filter(([key]) => key.startsWith(point + ":"))
        .map(([, item]) => item as Extension<K>)
        .sort((a, b) => a.order - b.order || a.id.localeCompare(b.id)),
    );
  }

  /** 命令执行固定注册记录，重复触发不产生并行副作用 */
  async function execute(id: string) {
    const item = entries.get(`commands:${id}`) as
      | Extension<"commands">
      | undefined;
    if (!item) throw new Error(`命令不可用：${id}`);
    if (draining.has(item.owner))
      throw new Error("插件正在排空命令，请等待切换完成。");
    if (runs.has(id)) throw new Error(`命令仍在执行：${item.value.title}`);
    const controller = new AbortController();
    const done = Promise.resolve().then(() => {
      controller.signal.throwIfAborted();
      return item.value.run({ signal: controller.signal });
    });
    runs.set(id, { owner: item.owner, controller, done });
    try {
      await done;
    } finally {
      runs.delete(id);
    }
  }

  /** 独立计算步骤状态，失败只影响当前贡献且不回显资料正文 */
  function workflow(input: WorkflowInput) {
    const snapshot = freeze(JSON.parse(JSON.stringify(input)) as WorkflowInput);
    const states = new Map<string, WorkflowStatus>();
    for (const item of list("workflow.state_contributors")) {
      try {
        const state = item.value.evaluate(snapshot);
        if (
          typeof state?.done !== "boolean" ||
          typeof state.text !== "string" ||
          state.text.length > 1000
        )
          throw new Error("步骤状态不符合契约");
        states.set(item.id, Object.freeze({ ...state }));
      } catch {
        states.set(item.id, {
          done: false,
          text: "步骤状态暂不可用，资料仍保留。",
        });
      }
    }
    return list("workflow.steps").map((item) => ({
      ...item,
      status: states.get(item.value.state) ?? {
        done: false,
        text: "步骤所需状态贡献不可用。",
      },
      available: entries.has(`commands:${item.value.command}`),
    }));
  }

  /** 展示后端已遮盖的事件副本，单个贡献失败保留原始记录和其他展示 */
  function activity(input: ActivityInput) {
    const snapshot = freeze(JSON.parse(JSON.stringify(input)) as ActivityInput);
    return list("activity.presenters")
      .filter((item) => item.value.sources.includes(input.source))
      .map((item) => {
        try {
          const result = item.value.present(snapshot);
          return result === null
            ? null
            : { id: item.id, ...activityPresentation(result), error: false };
        } catch {
          return {
            id: item.id,
            title: "扩展展示暂不可用",
            lines: [{ label: "贡献", text: item.id }],
            error: true,
          };
        }
      })
      .filter((item) => item !== null);
  }

  /** 检查当前输入的预览能力，失败只关闭本贡献且保留选择其他预览的入口 */
  function previewers(input: PreviewInput) {
    const snapshot = Object.freeze({ ...input });
    return list("documents.previewers")
      .filter((item) => item.value.formats.includes(input.format))
      .map((item) => {
        try {
          const status = item.value.availability?.(snapshot) ?? {
            available: true,
            reason: "",
          };
          if (
            typeof status.available !== "boolean" ||
            typeof status.reason !== "string" ||
            status.reason.length > 500
          )
            throw new Error("预览状态无效");
          return { ...item, ...status };
        } catch {
          return {
            ...item,
            available: false,
            reason: "预览器检查失败，资料仍保留。",
          };
        }
      });
  }

  return {
    contribute,
    list,
    execute,
    drain,
    resume,
    workflow,
    activity,
    previewers,
  };
}

/** 每种公开扩展点校验实际值，类型断言不能替代装载校验 */
function validate<K extends keyof ClientExtensionPoints>(
  point: K,
  value: ClientExtensionPoints[K],
) {
  if (!value || typeof value !== "object") throw new Error("客户端贡献无效。");
  if (point === "documents.previewers") {
    const previewer = value as DocumentPreviewer;
    if (
      typeof previewer.title !== "string" ||
      !previewer.title ||
      previewer.title.length > 100 ||
      typeof previewer.component !== "function" ||
      !Array.isArray(previewer.formats) ||
      !previewer.formats.length ||
      previewer.formats.length > 100 ||
      previewer.formats.some(
        (format) =>
          typeof format !== "string" || !format || format.length > 100,
      ) ||
      (previewer.availability !== undefined &&
        typeof previewer.availability !== "function")
    )
      throw new Error("预览贡献须包含名称、格式和组件。");
    return;
  }
  if (point === "activity.presenters") {
    const presenter = value as ActivityPresenter;
    if (
      typeof presenter.present !== "function" ||
      !Array.isArray(presenter.sources) ||
      !presenter.sources.length ||
      presenter.sources.length > 100 ||
      presenter.sources.some(
        (source) =>
          typeof source !== "string" || !source || source.length > 200,
      )
    )
      throw new Error("日志贡献必须声明来源和 present。");
    return;
  }
  if (point === "workflow.state_contributors") {
    if (
      typeof (value as ClientExtensionPoints["workflow.state_contributors"])
        .evaluate !== "function"
    )
      throw new Error("工作流状态贡献缺少 evaluate。");
    return;
  }
  const titled = value as Command | FieldEditor | WorkflowStep;
  if (
    typeof titled.title !== "string" ||
    !titled.title.trim() ||
    titled.title.length > 100
  )
    throw new Error("贡献标题须为 1 至 100 字符。");
  if (point === "commands") {
    if (typeof (value as Command).run !== "function")
      throw new Error("命令缺少 run。");
  } else if (point === "resume.field_editors") {
    if (typeof (value as FieldEditor).component !== "function")
      throw new Error("资料编辑器缺少组件。");
  } else if (point === "workflow.steps") {
    const step = value as WorkflowStep;
    if (
      ![step.state, step.command].every(
        (key) =>
          typeof key === "string" &&
          /^[a-z][a-z0-9._-]*\/[a-zA-Z0-9._/-]+$/.test(key),
      )
    )
      throw new Error("步骤必须引用有效的状态和命令贡献标识。");
  } else throw new Error(`未知客户端扩展点：${point}`);
}

export const clientExtensions = createClientExtensions();
