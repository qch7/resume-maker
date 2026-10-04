/// <reference types="vite/client" />
import { createElement, type ComponentType } from "react";
import { api } from "../shared/lib/api";
import { setCapabilities, type Capabilities } from "../shared/lib/capabilities";
import type {
  ClientContext,
  ClientPlugin,
  Page,
  SettingsPage,
  Slots,
} from "./contracts";
import { IsolatedPage } from "./IsolatedPage";
import { createClientServices, remoteProvider } from "./services";

const builtins = import.meta.glob<ClientPlugin>([
  "../features/**/plugin.ts",
  "../app/plugin.ts",
]);
const components = new Map<keyof Slots, ComponentType<never>>();
const pages = new Map<string, Page>();
const settingsPages = new Map<string, SettingsPage>();
const scopes = new Map<string, (() => void | Promise<void>)[]>();
const services = createClientServices();
export const clientFailures = new Map<string, string>();

/** 未选装的插槽保持空白，不挂载隐藏组件或发起后台请求 */
function Empty() {
  return null;
}

/** 按公开插槽类型读取组件，所有者由启动清单确定 */
export function pluginComponent<K extends keyof Slots>(key: K): Slots[K] {
  return (components.get(key) ?? Empty) as Slots[K];
}

/** 外部页面按稳定标识排序，工作台不需要知道页面实现 */
export function pluginPages() {
  return [...pages.values()].sort(
    (left, right) =>
      left.order - right.order || left.id.localeCompare(right.id),
  );
}

/** 设置页由能力所有者贡献，未安装插件不导入页面和状态 */
export function pluginSettingsPages() {
  return [...settingsPages.values()].sort(
    (left, right) =>
      left.order - right.order || left.id.localeCompare(right.id),
  );
}

/** 失败和卸载均逆序等待所有资源真正释放 */
export async function disposePlugin(id: string) {
  const effects = scopes.get(id) ?? [];
  const failed: typeof effects = [];
  for (const dispose of [...effects].reverse()) {
    try {
      await dispose();
    } catch {
      failed.unshift(dispose);
    }
  }
  if (failed.length) {
    scopes.set(id, failed);
    throw new Error(`插件 ${id} 仍有未释放资源。`);
  }
  scopes.delete(id);
}

/** 验证 Host 协议后装载已选择的入口，外部代码限定到宿主发布的版本路径 */
export async function initializePlugins() {
  for (const id of [...scopes.keys()].reverse()) await disposePlugin(id);
  clientFailures.clear();
  const value = await api<Capabilities>("/capabilities");
  setCapabilities(value);
  for (const item of value.client) {
    const effects: (() => void | Promise<void>)[] = [];
    scopes.set(item.id, effects);
    const context: ClientContext = {
      id: item.id,
      generation: value.generation,
      /** 注册能力随所属插件释放，客户端实现不会进入其他执行域 */
      provide(name, service, version = "1.0.0") {
        effects.push(services.provide(item, name, service, version));
      },
      /** 依赖已经由宿主验证版本和基数，客户端再核验实际激活结果 */
      require(name) {
        return services.require(item, name);
      },
      /** 远端依赖仅通过已选择提供方的 JSON RPC 消费 */
      remote(service, method, payload, provider) {
        const owner = remoteProvider(item, service, provider);
        return api(
          `/plugins/rpc/${encodeURIComponent(owner)}/${encodeURIComponent(method)}`,
          "POST",
          { generation: value.generation, payload },
        );
      },
      /** 集合消费者从已绑定的远端提供方中选择目标 */
      remoteProviders(service) {
        const binding = item.bindings?.remote[service];
        if (!binding) throw new Error(`未声明远端依赖 ${service}`);
        return Object.freeze([...binding.owners]);
      },
      /** 只向本插件声明的内置插槽注册组件 */
      component(key, component) {
        if (!item.entry.entry.startsWith("builtin:"))
          throw new Error("外部插件须使用自己的页面标识，不能覆盖系统插槽。");
        if (components.has(key)) throw new Error(`客户端插槽重复：${key}`);
        components.set(key, component as ComponentType<never>);
        effects.push(() => {
          components.delete(key);
        });
      },
      /** 外部页面使用插件命名空间避免覆盖其他贡献 */
      page(page) {
        if (!page.id.startsWith(item.id + "/") || pages.has(page.id))
          throw new Error("页面标识须属于当前插件且不能重复。");
        pages.set(page.id, page);
        effects.push(() => {
          pages.delete(page.id);
        });
      },
      /** 设置页面使用相同的命名空间和撤销规则 */
      settingsPage(page) {
        if (!page.id.startsWith(item.id + "/") || settingsPages.has(page.id))
          throw new Error("设置页标识须属于当前插件且不能重复。");
        settingsPages.set(page.id, page);
        effects.push(() => {
          settingsPages.delete(page.id);
        });
      },
      /** 插件样式随作用域卸载，资源不会常驻最小工作台 */
      style(css) {
        const node = document.createElement("style");
        node.dataset.plugin = item.id;
        node.textContent = css;
        document.head.append(node);
        effects.push(() => node.remove());
      },
      /** 订阅和样式等外部资源随作用域统一回收 */
      effect(dispose) {
        effects.push(dispose);
      },
      /** 插件只能调用自身命名空间的已声明远程操作 */
      request(method, payload) {
        if (!/^[a-zA-Z][a-zA-Z0-9_.-]{0,100}$/.test(method))
          throw new Error("远程操作标识无效。");
        return api(
          `/plugins/rpc/${encodeURIComponent(item.id)}/${method}`,
          "POST",
          {
            generation: value.generation,
            payload,
          },
        );
      },
    };
    try {
      for (const name of Object.keys(item.bindings?.client ?? {}))
        services.require(item, name);
      if (item.entry.mode === "isolated-client") {
        context.page({
          id: item.id + "/main",
          title: item.id,
          order: 100,
          component: () =>
            createElement(IsolatedPage, {
              id: item.id,
              entry: item.entry.entry,
              generation: value.generation,
            }),
        });
        continue;
      }
      if (item.entry.mode !== "trusted-client")
        throw new Error("未知客户端信任模式。");
      let module: ClientPlugin;
      if (item.entry.entry.startsWith("builtin:")) {
        const key = "../" + item.entry.entry.slice("builtin:".length);
        if (!builtins[key]) throw new Error(`安装包缺少入口：${key}`);
        module = await builtins[key]();
      } else {
        const url = new URL(item.entry.entry, location.origin);
        if (
          url.origin !== location.origin ||
          !url.pathname.startsWith("/plugin-assets/")
        )
          throw new Error("插件资源路径未通过验证。");
        module = (await import(/* @vite-ignore */ url.href)) as ClientPlugin;
      }
      if (typeof module.activate !== "function")
        throw new Error("客户端入口缺少 activate。");
      await module.activate(context);
      services.validate(item);
    } catch (error) {
      await disposePlugin(item.id);
      const message = error instanceof Error ? error.message : String(error);
      clientFailures.set(item.id, message);
      if (item.id.startsWith("sys.")) throw error;
    }
  }
}
