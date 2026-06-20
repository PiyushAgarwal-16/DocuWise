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

async function fetcher<T>(endpoint: string, retries = 20, delayMs = 3000): Promise<T> {
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(`${API_BASE}${endpoint}`);
      if (!res.ok) {
        if (res.status === 502 || res.status === 504 || res.status === 503) {
           throw new Error(`API Error: ${res.status} Bad Gateway`);
        }
        throw new Error(`API Error: ${res.status} ${res.statusText}`);
      }
      return await res.json();
    } catch (e: any) {
      // If it's a proxy error (502) or network error, wait and retry
      if (i < retries - 1 && (e.message.includes('Failed to fetch') || e.message.includes('Bad Gateway') || e.message.includes('504') || e.message.includes('503'))) {
        console.log(`Backend warming up, retrying ${endpoint} in ${delayMs}ms...`);
        await new Promise(r => setTimeout(r, delayMs));
        continue;
      }
      throw e;
    }
  }
  throw new Error(`Failed after ${retries} retries`);
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
  },

  stopScan: async () => {
    const res = await fetch(`${API_BASE}/scan/stop`, {
      method: "POST",
    });
    if (!res.ok) {
      throw new Error("Failed to stop scan");
    }
    return res.json();
  }
};
