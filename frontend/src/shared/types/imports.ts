export interface DocumentImporter {
  id: string;
  owner: string;
  version: string;
  title: string;
  extensions: string[];
  limits?: {
    max_bytes: number;
    max_pages: number | null;
    max_image_pixels: number;
  };
}

export interface ImportTrace {
  id: string;
  owner: string;
  version: string;
  source_sha256: string;
  format: string;
  pages: number | null;
}
