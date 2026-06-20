import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { ImagePdf } from "@/services/types";
import { invoke } from "@tauri-apps/api/core";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { FileText, FolderOpen } from "lucide-react";

export default function ImagePdfs({ folder }: { folder?: string }) {
  const [pdfs, setPdfs] = useState<ImagePdf[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getImagePdfs(folder).then(p => {
      setPdfs(p);
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

  if (loading) return <div className="p-8 text-muted-foreground">Loading image PDFs...</div>;

  return (
    <div className="h-full flex flex-col animate-in fade-in">
      <div className="p-6 pb-2 shrink-0">
        <h1 className="text-2xl font-bold tracking-tight mb-1">Image PDFs</h1>
        <p className="text-muted-foreground text-sm">
          These PDFs contain no extractable text. They are likely scanned documents that require OCR processing.
        </p>
      </div>

      <ScrollArea className="flex-1 p-6 pt-4">
        <div className="border border-border rounded-md bg-panel overflow-hidden max-w-5xl">
          <Table>
            <TableHeader className="bg-surface">
              <TableRow className="border-border">
                <TableHead>Filename</TableHead>
                <TableHead>Path</TableHead>
                <TableHead className="w-[100px]">Size</TableHead>
                <TableHead className="w-[200px] text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pdfs.map((pdf, idx) => (
                <TableRow key={idx} className="border-border hover:bg-surface/50">
                  <TableCell className="font-medium text-foreground">{pdf.filename}</TableCell>
                  <TableCell className="text-muted-foreground truncate max-w-md" title={pdf.file_path}>
                    {pdf.file_path}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{pdf.file_size_kb} KB</TableCell>
                  <TableCell className="text-right space-x-2">
                    <Button variant="ghost" size="sm" onClick={() => openFile(pdf.file_path)} title="Open File">
                      <FileText className="w-4 h-4" />
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => openFolder(pdf.file_path)} title="Open Folder">
                      <FolderOpen className="w-4 h-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              {pdfs.length === 0 && (
                <TableRow>
                  <TableCell colSpan={4} className="h-24 text-center text-muted-foreground">
                    No image-only PDFs found.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </div>
      </ScrollArea>
    </div>
  );
}
