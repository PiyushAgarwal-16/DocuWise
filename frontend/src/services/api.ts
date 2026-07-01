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

async function fetcher<T>(endpoint: string, retries = 40, delayMs = 1000): Promise<T> {
  let lastError: unknown;
  for (let i = 0; i < retries; i++) {
    try {
      const res = await fetch(`${API_BASE}${endpoint}`);
      if (res.ok) return await res.json();

      // 4xx = genuine client error, fail immediately (no point retrying).
      if (res.status < 500) {
        const body = await res.text().catch(() => "");
        throw new Error(`API Error ${res.status}: ${body || res.statusText}`);
      }

      // 5xx = backend not ready yet or proxy could not reach it
      // (Vite returns 503 while the Python server is still booting). Retryable.
      lastError = new Error(`API Error ${res.status} ${res.statusText}`);
    } catch (e: any) {
      // A thrown 4xx above is non-retryable; surface it right away.
      if (e instanceof Error && /^API Error 4/.test(e.message)) throw e;
      // Otherwise it's a network failure (backend down / proxy reset) — retry.
      lastError = e;
    }

    if (i < retries - 1) {
      console.log(`Backend warming up, retrying ${endpoint} (${i + 1}/${retries})...`);
      await new Promise(r => setTimeout(r, delayMs));
    }
  }
  throw lastError ?? new Error(`Failed to reach backend for ${endpoint}`);
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
