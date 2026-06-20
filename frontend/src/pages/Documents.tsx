import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { DocumentData } from "@/services/types";
import { invoke } from "@tauri-apps/api/core";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Search, FolderOpen, FileText } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ScrollArea } from "@/components/ui/scroll-area";

export default function Documents({ folder }: { folder?: string }) {
  const [docs, setDocs] = useState<DocumentData[]>([]);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<DocumentData | null>(null);

  useEffect(() => {
    loadDocs();
  }, [folder]);

  const loadDocs = async (query = "") => {
    try {
      const data = await api.getDocuments(folder, undefined, undefined, query);
      setDocs(data);
    } catch (e) {
      console.error(e);
    }
  };

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    loadDocs(search);
  };

  const openFile = async (path: string) => {
    try {
      await invoke("open_file", { path });
    } catch (e) {
      alert("Failed to open file: " + e);
    }
  };

  const openFolder = async (path: string) => {
    try {
      await invoke("open_folder", { path });
    } catch (e) {
      alert("Failed to open folder: " + e);
    }
  };

  return (
    <div className="flex h-full animate-in fade-in">
      <div className="flex-1 flex flex-col min-w-0 border-r border-border bg-background">
        <div className="p-4 border-b border-border flex items-center gap-4">
          <form onSubmit={handleSearch} className="flex-1 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input 
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by filename, subject, or summary..." 
              className="pl-9 bg-surface border-border focus-visible:ring-primary h-10 w-full max-w-md"
            />
          </form>
          <div className="text-sm text-muted-foreground font-medium">
            {docs.length} documents
          </div>
        </div>
        
        <ScrollArea className="flex-1">
          <Table>
            <TableHeader className="bg-panel sticky top-0 shadow-sm z-10">
              <TableRow className="border-border hover:bg-transparent">
                <TableHead className="w-[300px]">Filename</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Subject</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Imp.</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {docs.map((doc) => (
                <TableRow 
                  key={doc.id} 
                  className={`border-border cursor-pointer transition-colors ${selected?.id === doc.id ? 'bg-primary/10' : 'hover:bg-surface'}`}
                  onClick={() => setSelected(doc)}
                  onDoubleClick={() => openFile(doc.file_path)}
                >
                  <TableCell className="font-medium truncate max-w-[300px]" title={doc.filename}>
                    {doc.filename}
                  </TableCell>
                  <TableCell>{doc.category || "—"}</TableCell>
                  <TableCell className="truncate max-w-[200px]" title={doc.subject || ""}>{doc.subject || "—"}</TableCell>
                  <TableCell>
                    <StatusBadge status={doc.processing_status} />
                  </TableCell>
                  <TableCell className="text-right">{doc.importance_score || "—"}</TableCell>
                </TableRow>
              ))}
              {docs.length === 0 && (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={5} className="text-center py-10 text-muted-foreground">
                    No documents found.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </ScrollArea>
      </div>

      <div className="w-[350px] bg-panel flex flex-col h-full shrink-0">
        {selected ? (
          <ScrollArea className="flex-1">
            <div className="p-6 space-y-6">
              <div>
                <h3 className="text-lg font-semibold break-words leading-tight">{selected.filename}</h3>
                <p className="text-xs text-muted-foreground mt-1 truncate" title={selected.file_path}>
                  {selected.file_path}
                </p>
              </div>

              <div className="flex gap-2">
                <Button size="sm" className="flex-1 gap-2" onClick={() => openFile(selected.file_path)}>
                  <FileText className="w-4 h-4" /> Open File
                </Button>
                <Button size="sm" variant="secondary" className="flex-1 gap-2" onClick={() => openFolder(selected.file_path)}>
                  <FolderOpen className="w-4 h-4" /> Open Folder
                </Button>
              </div>

              <div className="space-y-4 pt-4 border-t border-border">
                <DetailRow label="Category" value={selected.category} />
                <DetailRow label="Subject" value={selected.subject} />
                <DetailRow label="Importance" value={selected.importance_score?.toString()} />
                <DetailRow label="File Size" value={selected.file_size_kb ? `${selected.file_size_kb} KB` : undefined} />
                <DetailRow label="Word Count" value={selected.word_count?.toString()} />
                
                <div className="space-y-1.5">
                  <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Summary</span>
                  <p className="text-sm text-foreground leading-relaxed">
                    {selected.summary || "No summary generated."}
                  </p>
                </div>

                {selected.tags && selected.tags.length > 0 && (
                  <div className="space-y-2">
                    <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Tags</span>
                    <div className="flex flex-wrap gap-1.5">
                      {selected.tags.map(tag => (
                        <Badge key={tag} variant="secondary" className="bg-surface hover:bg-surface text-xs font-normal">
                          {tag}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </ScrollArea>
        ) : (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground p-8 text-center">
            Select a document to view its details and actions.
          </div>
        )}
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  if (status === "embedded") return <Badge className="bg-success hover:bg-success/90">Fully Processed</Badge>;
  if (status === "image_only") return <Badge variant="secondary" className="bg-purple-500/20 text-purple-400 hover:bg-purple-500/30 border-purple-500/30">Image PDF</Badge>;
  if (status === "failed") return <Badge variant="destructive">Failed</Badge>;
  if (status === "missing") return <Badge variant="outline" className="text-muted-foreground border-muted-foreground/30">Missing</Badge>;
  return <Badge variant="secondary" className="bg-surface">{status}</Badge>;
}

function DetailRow({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">{label}</span>
      <span className="text-sm font-medium text-foreground">{value || "—"}</span>
    </div>
  );
}
