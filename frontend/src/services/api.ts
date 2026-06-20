import {
  Config,
  DashboardStats,
  DocumentData,
  DuplicatePair,
  ImagePdf,
  CleanupCandidate,
  MissingFile,
} from "./types";

const API_BASE = "/api";

async function fetcher<T>(endpoint: string): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`);
  if (!res.ok) {
    throw new Error(`API Error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

function buildQuery(params: Record<string, string | undefined>): string {
  const q = new URLSearchParams();
  for (const [key, val] of Object.entries(params)) {
    if (val) q.append(key, val);
  }
  const str = q.toString();
  return str ? `?${str}` : "";
}

export const api = {
  getConfig: () => fetcher<Config>("/config"),
  
  getStats: (folder?: string) => 
    fetcher<DashboardStats>(`/stats${buildQuery({ folder })}`),
    
  getDocuments: (folder?: string, status?: string, category?: string, search?: string) =>
    fetcher<DocumentData[]>(`/documents${buildQuery({ folder, status, category, search })}`),
    
  getDuplicates: (folder?: string) =>
    fetcher<DuplicatePair[]>(`/duplicates${buildQuery({ folder })}`),
    
  getImagePdfs: (folder?: string) =>
    fetcher<ImagePdf[]>(`/image-pdfs${buildQuery({ folder })}`),
    
  getCleanup: (folder?: string) =>
    fetcher<{ candidates: CleanupCandidate[]; missing: MissingFile[] }>(`/cleanup${buildQuery({ folder })}`),
    
  startScan: async (folder: string) => {
    const res = await fetch(`${API_BASE}/scan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ folder }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Failed to start scan");
    }
    return res.json();
  }
};
