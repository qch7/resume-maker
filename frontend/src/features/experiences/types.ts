import type { ProjectDetail, Revision } from "../../shared/types";
export interface EditorProps {
  detail: ProjectDetail;
  revisionId: string;
  included: string[];
  usedRevision?: Revision;
  hasLocalChanges: boolean;
  run: (work: () => Promise<void>) => void;
  onSave: (field: string) => Promise<void>;
  onRefresh: () => void;
  onDirty: () => void;
  onRevision: (id: string) => void;
  onUseVersion: () => void;
  onAsk: (scope: string) => Promise<void>;
  onToggle: (id: string) => void;
}
