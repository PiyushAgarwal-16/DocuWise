export interface Config {
  supported_extensions: string[];
  categories: string[];
  llm_provider: string;
}

export interface DashboardStats {
  total_documents: number;
  embedded: number;
  image_only: number;
  cleanup_candidates: number;
  missing: number;
  failed: number;
  duplicates: number;
  categories: { name: string; count: number }[];
  top_documents: { filename: string; category: string; importance: number }[];
}

export interface DocumentData {
  id: number;
  file_path: string;
  filename: string;
  extension: string;
  file_size_kb: number;
  word_count: number | null;
  md5_hash: string | null;
  summary: string | null;
  category: string | null;
  subject: string | null;
  tags: string[];
  importance_score: number | null;
  processing_status: string;
  analysis_source: string | null;
  deletion_candidate: boolean;
  deletion_reason: string | null;
  highlight: boolean;
  created_at: string;
  updated_at: string;
}

export interface DuplicatePair {
  file_a: { filename: string; file_path: string };
  file_b: { filename: string; file_path: string; file_size_kb: number };
  similarity_score: number;
  relationship_type: "duplicate" | "similar";
}

export interface ImagePdf {
  filename: string;
  file_path: string;
  file_size_kb: number;
}

export interface CleanupCandidate {
  filename: string;
  file_path: string;
  reason: string;
  importance_score: number;
}

export interface MissingFile {
  filename: string;
  file_path: string;
}

export interface ScanProgressEvent {
  type: "progress" | "complete" | "error" | "log";
  current?: number;
  total?: number;
  filename?: string;
  stage?: string;
  elapsed_seconds?: number;
  message?: string;
  result?: any;
  error?: string;
}
