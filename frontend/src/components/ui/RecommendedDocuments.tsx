import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { invoke } from "@tauri-apps/api/core";
import { FileText, Sparkles, Loader2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "./card";

export default function RecommendedDocuments() {
  const [data, setData] = useState<{ reason: string, documents: any[] } | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    setLoading(true);
    api.getRecommended(4)
      .then((res) => {
        if (active) setData(res);
      })
      .catch((e) => console.error(e))
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, []);

  const openFile = async (path: string) => {
    try {
      await invoke("open_file", { path });
    } catch (e) {
      alert("Failed to open file: " + e);
    }
  };

  if (loading) return null;
  if (!data || data.documents.length === 0) return null;

  return (
    <Card className="bg-panel border-border lg:col-span-3 mt-8">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="w-5 h-5 text-yellow-500" />
          Recommended For You
        </CardTitle>
        <p className="text-sm text-muted-foreground">{data.reason}</p>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {data.documents.map((doc, idx) => (
            <div 
              key={doc.id || idx} 
              className="p-4 rounded-xl border border-border bg-card hover:border-primary/50 transition-colors cursor-pointer group flex flex-col"
              onClick={() => openFile(doc.file_path)}
              title="Click to open document"
            >
              <div className="font-semibold text-sm text-foreground truncate group-hover:text-primary transition-colors mb-2">
                {doc.filename}
              </div>
              <p className="text-xs text-muted-foreground line-clamp-3 mb-4 flex-1">
                {doc.summary || "No summary available."}
              </p>
              <div className="flex items-center gap-1.5 px-2 py-1 w-fit bg-surface border border-border/50 text-foreground rounded text-[10px] font-medium uppercase tracking-wider mt-auto">
                <FileText className="w-3 h-3" />
                {doc.category || "Uncategorized"}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
