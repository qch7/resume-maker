import type { ComponentType } from "react";

export interface PreviewInput {
  format: string;
  input: string | null;
}

export interface DocumentPreviewProps extends PreviewInput {
  templateId: string | null;
  zoom: number;
  hidden: boolean;
  run(work: () => Promise<void>): void;
}

export interface DocumentPreviewer {
  title: string;
  formats: readonly string[];
  component: ComponentType<DocumentPreviewProps>;
  availability?(input: Readonly<PreviewInput>): {
    available: boolean;
    reason: string;
  };
}
