import type {
  ConversationProps,
  HonorLibraryProps,
  HonorEditorProps,
  TemplateAdapterProps,
  WorkflowProps,
  TemplatePickerProps,
} from "./slots";
import type { ComponentType } from "react";
import type { ClientExtensionPoints } from "./extensions";

export interface Slots {
  workbench: ComponentType;
  workspace: ComponentType;
  conversation: ComponentType<ConversationProps>;
  honors: ComponentType<HonorLibraryProps>;
  honorEditor: ComponentType<HonorEditorProps>;
  templates: ComponentType<TemplateAdapterProps>;
  templatePicker: ComponentType<TemplatePickerProps>;
  recruitment: ComponentType<{ active: boolean }>;
  workflow: ComponentType<WorkflowProps>;
}

export interface Page {
  id: string;
  title: string;
  order: number;
  component: ComponentType<{ active: boolean }>;
}

export interface WorkbenchPageProps {
  active: boolean;
  openSettings(section: string): void;
  settingsVersion: number;
}

export interface WorkbenchPage extends Omit<Page, "component"> {
  icon?: ComponentType<{ size?: number }>;
  component: ComponentType<WorkbenchPageProps>;
}

export interface Navigation {
  slot: "honors" | "templates" | "recruitment";
  title: string;
  order: number;
  icon: ComponentType<{ size?: number }>;
}

export interface SettingsPanelProps {
  active: boolean;
  run: (work: () => Promise<void>) => void;
  onChanged: () => Promise<void>;
  registerBeforeClose?: (guard: () => Promise<void>) => () => void;
}

export interface SettingsPage {
  id: string;
  title: string;
  order: number;
  component: ComponentType<SettingsPanelProps>;
  openFor?: string[];
  group?: "projects";
  icon?: ComponentType<{ size?: number }>;
}

export interface ClientContext {
  readonly id: string;
  readonly plugin: string;
  readonly scopeId: string;
  readonly config: Readonly<Record<string, unknown>>;
  readonly generation: number;
  provide<T>(name: string, value: T, version?: string): void;
  require<T>(name: string): T;
  remote<T = unknown>(
    service: string,
    method: string,
    payload: unknown,
    provider?: string,
  ): Promise<T>;
  remoteProviders(service: string): readonly string[];
  component<K extends keyof Slots>(key: K, value: Slots[K]): void;
  page(value: Page): void;
  workbenchPage(value: WorkbenchPage): void;
  navigation(value: Navigation): void;
  settingsPage(value: SettingsPage): void;
  contribute<K extends keyof ClientExtensionPoints>(
    point: K,
    id: string,
    value: ClientExtensionPoints[K],
    order?: number,
    version?: string,
  ): void;
  style(css: string): void;
  effect(dispose: () => void | Promise<void>): void;
  request<T = unknown>(method: string, payload: unknown): Promise<T>;
}

export interface ClientPlugin {
  activate(context: ClientContext): void | Promise<void>;
}
