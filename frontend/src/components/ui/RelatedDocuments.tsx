import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { SearchResult } from "@/services/types";
import { Loader2, Link as LinkIcon, FileText } from "lucide-react";
import { invoke } from "@tauri-apps/api/core";

export default function RelatedDocuments({ documentId }: { documentId: number }) {
  const [docs, setDocs] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (!documentId) return;

    setLoading(true);
    setError(null);
    api.getRelated(documentId, 5)
      .then((res) => {
        if (active) setDocs(res.related || []);
      })
      .catch((err) => {
        if (active) setError(err.message || "Failed to load related documents");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => { active = false; };
  }, [documentId]);

  const openFile = async (path: string) => {
    try {
      await invoke("open_file", { path });
    } catch (e) {
      alert("Failed to open file: " + e);
    }
  };

  if (loading) return <div className="flex justify-center p-4"><Loader2 className="w-4 h-4 animate-spin text-muted-foreground" /></div>;
  if (error) return <div className="text-red-500 text-xs p-4 bg-red-500/10 rounded">{error}</div>;
  if (!docs || docs.length === 0) return <div className="text-xs text-muted-foreground p-4">No related documents found.</div>;

  return (
    <div className="space-y-3">
      <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
        <LinkIcon className="w-3 h-3" /> Related Documents
      </h4>
      <div className="space-y-2">
        {docs.map((doc) => (
          <div 
            key={doc.id} 
            className="p-3 bg-surface border border-border rounded-lg cursor-pointer hover:border-primary/50 transition-colors group"
            onClick={() => openFile(doc.file_path)}
            title="Double-click to open file"
          >
            <div className="font-medium text-sm text-foreground truncate group-hover:text-primary transition-colors">
              {doc.filename}
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[10px] text-muted-foreground font-medium uppercase tracking-wider flex items-center gap-1">
                <FileText className="w-3 h-3" />
                {doc.category || "Uncategorized"}
              </span>
              <span className="text-[10px] bg-background border border-border px-1.5 py-0.5 rounded font-medium text-muted-foreground">
                Match: {(doc.similarity_score * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
