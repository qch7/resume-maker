import type {
  ConversationDetail,
  Job,
  ProjectDetail,
  Proposal,
  ResumeDocument,
  SectionEntry,
  Resume,
  Revision,
  Template,
  Export,
} from "../shared/types/index";
import type { Layout } from "../shared/lib/layout";
import type { Honor, HonorSource } from "../shared/types/honors";
export type GuideTarget =
  | "template-select"
  | "personal-basic"
  | "personal-education"
  | "personal-skills"
  | "projects"
  | "analysis"
  | "experience-save"
  | "experience-use"
  | "honor-recognize"
  | "honor-select"
  | "structure"
  | "composition-save"
  | "export";

export interface GuideAction {
  text: string;
  action: string;
  target: GuideTarget;
  projectId?: string;
}

export interface WorkflowInput {
  projectCount: number;
  detail: ProjectDetail | null;
  revisionId: string;
  edited?: boolean;
  draft: Resume;
  saved?: Resume;
  revisions: Record<string, Revision>;
  result: Export | null;
  exporting: boolean;
  analyzing: boolean;
  honors?: HonorSource[];
}

export interface WorkflowState extends GuideAction {
  done: boolean[];
  step: number;
  guides: GuideAction[];
  substeps: boolean[][];
}

export interface ConversationProps {
  inputHeight: number;
  onInputHeight: (value: number) => void;
  detail: ConversationDetail;
  project: ProjectDetail;
  activeJob?: Job;
  run: (work: () => Promise<void>) => void;
  onSend: (text: string, scope: string, kind?: string) => Promise<void>;
  onAdopt: (proposal: Proposal) => Promise<void>;
  onRefresh: () => void;
}

export interface TemplatePickerProps {
  templates: Template[];
  value: string;
  onChange(id: string): void;
  disabled?: boolean;
  placeholder?: string;
  guide?: string;
  label: string;
}

export interface HonorLibraryProps {
  active: boolean;
  document: ResumeDocument | null;
  resumeName: string;
  onAdd: (honors: Honor[], section: string) => void;
  onRemove: (id: string) => void;
  onSaved: (honor: Honor) => void;
}

export interface HonorEditorProps {
  honor: Honor | null;
  onClose: () => void;
  onSaved: (honor: Honor) => void;
  resumeEntry?: SectionEntry;
  onSaveEntry?: (entry: SectionEntry) => Promise<void>;
  draftScope?: string;
}

export interface TemplateAdapterProps {
  active: boolean;
  layout: Layout;
  onResize: (key: keyof Layout, value: number | boolean) => void;
  resume: Resume;
  revisions: Record<string, Revision>;
  previewSources: Record<string, Revision>;
  templates: Template[];
  onChanged: () => Promise<void>;
  onSelected: (id: string | null) => void;
}

export interface WorkflowProps {
  input: WorkflowInput;
  activeStep: number;
  onNavigate: (target: GuideTarget, projectId?: string) => void;
  collapsed: boolean;
  onToggle: () => void;
}

export interface WordPreviewProps {
  input: string | null;
  templateId: string | null;
  zoom: number;
  hidden: boolean;
  run: (work: () => Promise<void>) => void;
}
