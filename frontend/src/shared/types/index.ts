export interface Evidence {
  source: string;
  path: string;
  line_start: number;
  line_end: number;
  quote: string;
  status: "code" | "document" | "user" | "unverified";
}
export interface Highlight {
  id: string;
  title: string;
  text: string;
  evidence: Evidence[];
}
export interface Experience {
  title: string;
  period: string;
  role: string;
  stack: string[];
  description: string;
  highlights: Highlight[];
}
export type Meta = Omit<Experience, "highlights">;
export interface Profile {
  role: string;
  period: string;
  contribution: string;
  outcomes: string;
  notes: string;
}
export interface Project {
  id: string;
  parent_id?: string | null;
  name: string;
  roots: string[];
  profile: Profile;
  head_revision: string;
  updated_at: string;
  activity_at?: string;
}
export interface Revision {
  id: string;
  project_id: string;
  number: number;
  parent_id: string | null;
  snapshot_id: string | null;
  content: Experience;
  origin: string;
  note: string;
  created_at: string;
  branch_id: string;
  branch_name: string;
}
export interface Branch {
  id: string;
  project_id: string;
  name: string;
  head_revision: string;
  is_default: number;
  created_at: string;
  updated_at: string;
}
export interface Draft {
  field: string;
  value: unknown;
  version: number;
  base_revision: string;
  origin: string;
}
export interface Working {
  content: Experience;
  drafts: Draft[];
}
export interface Snapshot {
  id: string;
  fingerprint: string;
  created_at: string;
  manifest: {
    sources: {
      id: string;
      name: string;
      path: string;
      commit: string;
      branch: string;
      dirty: boolean;
    }[];
    files: { source: string; path: string; lines: number; redacted: boolean }[];
    omitted: { path: string; reason: string }[];
    total_bytes: number;
  };
}
export interface ProjectDetail {
  project: Project;
  branch: Branch;
  branches: Branch[];
  revisions: Revision[];
  working: Working;
  uncommitted?: UncommittedRevision[];
  snapshots: Snapshot[];
  revision_snapshot: Snapshot | null;
}
export interface UncommittedRevision {
  base_revision: string;
  content: Experience;
  updated_at: string;
}
export interface Conversation {
  id: string;
  project_id: string;
  title: string;
  input_draft: string;
  scope: string;
  provider_thread_id: string | null;
  updated_at: string;
}
export interface Message {
  id: string;
  role: string;
  text: string;
  job_id: string | null;
}
export interface Proposal {
  id: string;
  job_id: string;
  target: string;
  before: Experience | Highlight | null;
  after: Experience | Highlight;
  reason: string;
  status: string;
  base_revision: string;
}
export interface Job {
  id: string;
  project_id: string;
  conversation_id: string;
  kind: string;
  status: string;
  error: string | null;
  request?: { text: string; scope: string };
  result?: { questions: string[] };
}
export interface ConversationDetail {
  conversation: Conversation;
  messages: Message[];
  proposals: Proposal[];
  jobs: Job[];
}
export interface ResumeItem {
  project_id: string;
  revision_id: string;
  highlight_ids: string[];
}
export interface Resume {
  id: string;
  name: string;
  template_id: string | null;
  items: ResumeItem[];
  version: number;
  document: ResumeDocument | null;
}
export interface CustomInfoField {
  id: string;
  label: string;
  value: string;
  visible: boolean;
}
export interface PersonalInfo {
  name: string;
  job_title: string;
  gender: string;
  age: string;
  phone: string;
  email: string;
  gpa: string;
  location: string;
  website: string;
  photo: string;
  hidden_fields: PersonalField[];
  custom_fields: CustomInfoField[];
}
export type PersonalField = keyof Omit<
  PersonalInfo,
  "hidden_fields" | "custom_fields"
>;
export type SectionEntryField = "title" | "subtitle" | "period" | "details";
export interface SectionEntry {
  id: string;
  title: string;
  subtitle: string;
  period: string;
  details: string;
  visible: boolean;
  hidden_fields: SectionEntryField[];
  custom_fields: CustomInfoField[];
}
export interface ResumeSection {
  id: string;
  title: string;
  kind: "education" | "projects" | "text";
  parent_id: string | null;
  visible: boolean;
  entries: SectionEntry[];
}
export interface ResumeDocument {
  personal: PersonalInfo;
  sections: ResumeSection[];
}
export interface Template {
  id: string;
  name: string;
  kind: "adaptive" | "projects";
  created_at: string;
}
export interface State {
  branches: Branch[];
  projects: Project[];
  conversations: Conversation[];
  resumes: Resume[];
  templates: Template[];
  jobs: Job[];
}
export interface Export {
  id: string;
  resume_id: string;
  pages: number | null;
  render_error: string | null;
  created_at: string;
  manifest?: { resume: Resume };
}
export interface ProviderSettings {
  executable: string;
  model: string;
  profile: string;
  timeout_seconds: number;
}
export interface Inspection {
  paragraphs: { index: number; text: string; has_section: boolean }[];
  suggested_start: number | null;
  suggested_end: number | null;
  file_name: string;
}
