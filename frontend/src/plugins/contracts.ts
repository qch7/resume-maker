import type {
  ConversationProps,
  ActivityProps,
  HonorLibraryProps,
  HonorEditorProps,
  TemplateAdapterProps,
  WorkflowProps,
  WordPreviewProps,
} from "./slots";
import type { ComponentType } from "react";
import type { ClientExtensionPoints } from "./extensions";

export interface Slots {
  workbench: ComponentType;
  workspace: ComponentType;
  conversation: ComponentType<ConversationProps>;
  activity: ComponentType<ActivityProps>;
  honors: ComponentType<HonorLibraryProps>;
  honorEditor: ComponentType<HonorEditorProps>;
  templates: ComponentType<TemplateAdapterProps>;
  recruitment: ComponentType<{ active: boolean }>;
  workflow: ComponentType<WorkflowProps>;
  wordPreview: ComponentType<WordPreviewProps>;
}

export interface Page {
  id: string;
  title: string;
  order: number;
  component: ComponentType<{ active: boolean }>;
}

export interface SettingsPanelProps {
  active: boolean;
  run: (work: () => Promise<void>) => void;
  onChanged: () => Promise<void>;
}

export interface SettingsPage {
  id: string;
  title: string;
  order: number;
  component: ComponentType<SettingsPanelProps>;
  openFor?: string[];
}

export interface ClientContext {
  readonly id: string;
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
