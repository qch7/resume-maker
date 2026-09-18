import type {
  Experience,
  DefaultField,
  ProjectDetail,
  ProjectVisibility,
  Revision,
} from "../../shared/types";
export interface EditorProps {
  detail: ProjectDetail;
  definitions?: DefaultField[] | null;
  revisionId: string;
  included: string[];
  visibility: ProjectVisibility;
  onVisibility: (value: ProjectVisibility) => void;
  usedRevision?: Revision;
  hasLocalChanges: boolean;
  run: (work: () => Promise<void>) => void;
  onSave: () => Promise<void>;
  onDiscard: (versions: Record<string, number>) => Promise<void>;
  onRefresh: () => void;
  onRevision: (id: string) => void;
  onUseVersion: () => void;
  onAsk: (scope: string) => Promise<void>;
  onToggle: (id: string) => void;
  onPreview: (revisionId: string, content: Experience) => void;
}
