export interface Config {
  supported_extensions: string[];
  categories: string[];
  llm_provider: string;
  ocr_enabled?: boolean;
  ocr_engine?: string;
  ocr_version?: string;
  ocr_language?: string;
  ocr_available?: boolean;
  content_cache_enabled?: boolean;
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
  // Phase 10 — extraction & cache intelligence
  native_documents?: number;
  hybrid_documents?: number;
  ocr_only_documents?: number;
  image_only_documents?: number;
  ocr_cache_hits?: number;
  content_cache_hits?: number;
  api_calls_saved?: number;
  embeddings_reused?: number;
  avg_ocr_time_ms?: number;
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
  // Phase 6 — extraction metadata
  extraction_method?: string | null;
  ocr_engine?: string | null;
  ocr_version?: string | null;
  ocr_confidence?: number | null;
  ocr_pages_processed?: number | null;
  ocr_pages_skipped?: number | null;
  ocr_processing_time_ms?: number | null;
  ocr_cached?: number | null;
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
  page?: number;
  elapsed_seconds?: number;
  message?: string;
  result?: any;
  error?: string;
}
