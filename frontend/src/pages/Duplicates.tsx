import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { DuplicatePair } from "@/services/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { invoke } from "@tauri-apps/api/core";
import { FileText, FolderOpen, Percent } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";

export default function Duplicates({ folder }: { folder?: string }) {
  const [pairs, setPairs] = useState<DuplicatePair[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getDuplicates(folder).then(p => {
      setPairs(p);
      setLoading(false);
    }).catch(e => {
      console.error(e);
      setLoading(false);
    });
  }, [folder]);

  const openFile = async (path: string) => {
    try { await invoke("open_file", { path }); } 
    catch (e) { alert("Failed to open file"); }
  };

  const openFolder = async (path: string) => {
    try { await invoke("open_folder", { path }); } 
    catch (e) { alert("Failed to open folder"); }
  };

  if (loading) return <div className="p-8 text-muted-foreground">Loading duplicates...</div>;
  if (pairs.length === 0) return <div className="p-8 text-muted-foreground flex flex-col items-center justify-center h-full"><p className="text-lg font-medium text-foreground">No Duplicates Found</p><p>Your documents are unique!</p></div>;

  return (
    <div className="h-full flex flex-col animate-in fade-in">
      <div className="p-6 pb-2 shrink-0">
        <h1 className="text-2xl font-bold tracking-tight mb-1">Duplicates & Similar Files</h1>
        <p className="text-muted-foreground text-sm">Review similar documents. Identical files are automatically flagged for cleanup.</p>
      </div>

      <ScrollArea className="flex-1 p-6 pt-4">
        <div className="space-y-6 max-w-4xl">
          {pairs.map((pair, idx) => {
            const isExact = pair.similarity_score > 0.99;
            return (
              <Card key={idx} className="bg-panel border-border overflow-hidden flex flex-col">
                <div className={`h-1.5 w-full ${isExact ? 'bg-destructive' : 'bg-warning'}`} />
                <CardHeader className="py-4 border-b border-border bg-surface/30">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm font-medium flex items-center gap-2">
                      <Percent className="w-4 h-4 text-muted-foreground" />
                      {Math.round(pair.similarity_score * 100)}% Match
                    </CardTitle>
                    {isExact && <span className="text-xs font-bold text-destructive uppercase tracking-wider bg-destructive/10 px-2 py-1 rounded">Exact Duplicate</span>}
                  </div>
                </CardHeader>
                <CardContent className="p-0 grid grid-cols-2 divide-x divide-border">
                  <FilePanel 
                    label="Original Document" 
                    file={pair.file_a} 
                    onOpen={() => openFile(pair.file_a.file_path)} 
                    onFolder={() => openFolder(pair.file_a.file_path)} 
                  />
                  <FilePanel 
                    label="Duplicate Document" 
                    file={pair.file_b} 
                    onOpen={() => openFile(pair.file_b.file_path)} 
                    onFolder={() => openFolder(pair.file_b.file_path)} 
                  />
                </CardContent>
              </Card>
            )
          })}
        </div>
      </ScrollArea>
    </div>
  );
}

function FilePanel({ label, file, onOpen, onFolder }: any) {
  return (
    <div className="p-5 space-y-4 flex flex-col">
      <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">{label}</span>
      <div className="flex-1">
        <p className="text-sm font-medium text-foreground break-words">{file.filename}</p>
        <p className="text-xs text-muted-foreground mt-1 truncate" title={file.file_path}>{file.file_path}</p>
        {file.file_size_kb && <p className="text-xs text-muted-foreground mt-1">{file.file_size_kb} KB</p>}
      </div>
      <div className="flex gap-2 pt-2">
        <Button variant="secondary" size="sm" className="flex-1 text-xs h-8 bg-surface hover:bg-surface/80" onClick={onOpen}>
          <FileText className="w-3.5 h-3.5 mr-2" /> Open
        </Button>
        <Button variant="secondary" size="sm" className="flex-1 text-xs h-8 bg-surface hover:bg-surface/80" onClick={onFolder}>
          <FolderOpen className="w-3.5 h-3.5 mr-2" /> Folder
        </Button>
      </div>
    </div>
  );
}
