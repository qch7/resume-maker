export interface DocumentImporter {
  id: string;
  owner: string;
  version: string;
  title: string;
  extensions: string[];
}

export interface ImportTrace {
  id: string;
  owner: string;
  version: string;
  source_sha256: string;
  format: string;
  pages: number | null;
}
