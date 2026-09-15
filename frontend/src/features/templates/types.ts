export interface TemplateNode {
  id: string;
  parent: string;
  part: string;
  kind: "p" | "tbl" | "tr" | "image";
  text: string;
  can_insert: boolean;
  ancestors: string[];
}
export interface TemplateTrialPreview {
  id: string;
  pages: number | null;
  render_error: string | null;
}
export interface TextBinding {
  node: string;
  quote: string;
  target: string;
  occurrence: number;
}
export interface RepeatBinding {
  section: string;
  start: string;
  end: string;
  sample_start: string;
  sample_end: string;
  fields: TextBinding[];
}
export interface TemplatePlan {
  summary: string;
  fields: TextBinding[];
  repeats: RepeatBinding[];
  photos: string[];
  keep: string[];
  remove: string[];
  warnings: string[];
}
export interface MappingReview {
  ready: boolean;
  errors: string[];
  unresolved: TemplateNode[];
  issues?: { message: string; nodes: string[] }[];
  missing?: string[];
  notices?: string[];
}
export interface TemplateProgressData {
  id: string;
  status: "running" | "completed" | "failed" | "cancelled";
  activity: string;
  error: string | null;
  phase: string;
  round: number;
  elapsed_ms: number;
  cursor: number;
  events: { id: number; elapsed_ms: number; text: string }[];
  usage: {
    input_tokens?: number;
    cached_input_tokens?: number;
    output_tokens?: number;
  };
  metrics: {
    round: number;
    prompt_chars: number;
    images: number;
    resumed: boolean;
  }[];
  reused: boolean;
  from_library: boolean;
}
export interface TemplateAnalysis extends TemplateProgressData {
  file_name: string;
  inventory: { nodes: TemplateNode[]; warnings: string[]; notices?: string[] };
  plan: TemplatePlan | null;
  review: MappingReview | null;
  attempts?: number;
  repair_error?: string | null;
}
