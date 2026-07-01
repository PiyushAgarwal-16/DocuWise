import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { CleanupCandidate, MissingFile } from "@/services/types";
import { invoke } from "@tauri-apps/api/core";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Trash2, AlertTriangle, FileText, FolderOpen } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";

export default function Cleanup({ folder }: { folder?: string }) {
  const [candidates, setCandidates] = useState<CleanupCandidate[]>([]);
  const [missing, setMissing] = useState<MissingFile[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getCleanup(folder).then(res => {
      setCandidates(res.candidates);
      setMissing(res.missing);
      setLoading(false);
    }).catch(e => {
      console.error(e);
      setLoading(false);
    });
  }, [folder]);

  const openFile = async (path: string) => {
    try { await invoke("open_file", { path }); } catch (e) {}
  };

  const openFolder = async (path: string) => {
    try { await invoke("open_folder", { path }); } catch (e) {}
  };

  if (loading) return <div className="p-8 text-muted-foreground">Loading cleanup data...</div>;

  return (
    <div className="h-full flex flex-col animate-in fade-in">
      <div className="p-6 pb-2 shrink-0">
        <h1 className="text-2xl font-bold tracking-tight mb-1">System Cleanup</h1>
        <p className="text-muted-foreground text-sm">Review junk documents, exact duplicates, and missing files.</p>
      </div>

      <div className="flex-1 p-6 pt-4 flex flex-col min-h-0">
        <Tabs defaultValue="candidates" className="flex flex-col h-full">
          <TabsList className="bg-panel border border-border self-start">
            <TabsTrigger value="candidates" className="data-[state=active]:bg-destructive data-[state=active]:text-white">
              Deletion Candidates ({candidates.length})
            </TabsTrigger>
            <TabsTrigger value="missing" className="data-[state=active]:bg-warning data-[state=active]:text-warning-foreground">
              Missing Files ({missing.length})
            </TabsTrigger>
          </TabsList>
          
          <TabsContent value="candidates" className="flex-1 mt-4 min-h-0">
            <ScrollArea className="h-full pr-4">
              <div className="space-y-4 max-w-4xl pb-8">
                {candidates.length === 0 ? (
                  <div className="text-center p-8 text-muted-foreground border border-dashed border-border rounded-lg">
                    No deletion candidates found. Your system is clean!
                  </div>
                ) : (
                  candidates.map((c, idx) => (
                    <Card key={idx} className="bg-panel border-border shadow-sm">
                      <div className="flex justify-between items-start p-4">
                        <div className="space-y-2 flex-1 mr-4">
                          <div className="flex items-center gap-2">
                            <h3 className="font-semibold text-foreground text-sm">{c.filename}</h3>
                            <Badge variant="destructive" className="text-[10px] uppercase h-5 font-bold">
                              {c.importance_score}/10
                            </Badge>
                          </div>
                          <p className="text-xs text-muted-foreground truncate" title={c.file_path}>{c.file_path}</p>
                          <div className="bg-destructive/10 border border-destructive/20 rounded p-2 text-sm text-foreground flex items-start gap-2">
                            <Trash2 className="w-4 h-4 text-destructive shrink-0 mt-0.5" />
                            <span>{c.reason}</span>
                          </div>
                        </div>
                        <div className="flex flex-col gap-2 shrink-0">
                          <Button variant="secondary" size="sm" className="w-full justify-start text-xs h-8" onClick={() => openFile(c.file_path)}>
                            <FileText className="w-3.5 h-3.5 mr-2" /> Open
                          </Button>
                          <Button variant="secondary" size="sm" className="w-full justify-start text-xs h-8" onClick={() => openFolder(c.file_path)}>
                            <FolderOpen className="w-3.5 h-3.5 mr-2" /> Folder
                          </Button>
                        </div>
                      </div>
                    </Card>
                  ))
                )}
              </div>
            </ScrollArea>
          </TabsContent>

          <TabsContent value="missing" className="flex-1 mt-4 min-h-0">
            <ScrollArea className="h-full pr-4">
              <div className="space-y-4 max-w-4xl pb-8">
                {missing.length === 0 ? (
                  <div className="text-center p-8 text-muted-foreground border border-dashed border-border rounded-lg">
                    No missing files detected.
                  </div>
                ) : (
                  missing.map((m, idx) => (
                    <div key={idx} className="flex items-center justify-between p-4 bg-panel border border-border rounded-lg">
                      <div className="flex items-center gap-3">
                        <AlertTriangle className="w-5 h-5 text-warning" />
                        <div>
                          <p className="text-sm font-medium text-foreground">{m.filename}</p>
                          <p className="text-xs text-muted-foreground">{m.file_path}</p>
                        </div>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </ScrollArea>
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
