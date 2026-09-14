import type { Experience, ProjectDetail, Revision } from "../../shared/types";
export interface EditorProps {
  detail: ProjectDetail;
  revisionId: string;
  included: string[];
  usedRevision?: Revision;
  hasLocalChanges: boolean;
  run: (work: () => Promise<void>) => void;
  onSave: () => Promise<void>;
  onRefresh: () => void;
  onDirty: () => void;
  onRevision: (id: string) => void;
  onUseVersion: () => void;
  onAsk: (scope: string) => Promise<void>;
  onToggle: (id: string) => void;
  onPreview: (revisionId: string, content: Experience) => void;
}
