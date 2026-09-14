export interface TemplateNode {
  id: string;
  parent: string;
  part: string;
  kind: "p" | "tbl" | "tr" | "image";
  text: string;
  can_insert: boolean;
  ancestors: string[];
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
export interface TemplateAnalysis {
  id: string;
  file_name: string;
  status: "running" | "completed" | "failed" | "cancelled";
  activity: string;
  error: string | null;
  inventory: { nodes: TemplateNode[]; warnings: string[]; notices?: string[] };
  plan: TemplatePlan | null;
  review: MappingReview | null;
  attempts?: number;
  repair_error?: string | null;
}
