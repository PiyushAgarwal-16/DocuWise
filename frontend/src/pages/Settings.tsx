import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { Config } from "@/services/types";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";

export default function Settings() {
  const [config, setConfig] = useState<Config | null>(null);

  useEffect(() => {
    api.getConfig().then(setConfig).catch(console.error);
  }, []);

  return (
    <div className="h-full flex flex-col animate-in fade-in">
      <div className="p-6 pb-2 shrink-0">
        <h1 className="text-2xl font-bold tracking-tight mb-1">Settings & Configuration</h1>
        <p className="text-muted-foreground text-sm">View current system configuration parameters.</p>
      </div>

      <ScrollArea className="flex-1 p-6 pt-4">
        <div className="space-y-6 max-w-3xl pb-8">
          <Card className="bg-panel border-border">
            <CardHeader>
              <CardTitle>AI Analysis Engine</CardTitle>
              <CardDescription>Current LLM provider configuration.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-4">
                <span className="text-sm font-medium">Active Provider:</span>
                <Badge variant="secondary" className="bg-primary/20 text-primary uppercase">
                  {config?.llm_provider || "Loading..."}
                </Badge>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-panel border-border">
            <CardHeader>
              <CardTitle>Document Scanning</CardTitle>
              <CardDescription>File types currently supported by the extraction pipeline.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {config?.supported_extensions.map(ext => (
                  <Badge key={ext} variant="outline" className="text-xs">{ext}</Badge>
                )) || <span className="text-sm text-muted-foreground">Loading...</span>}
              </div>
            </CardContent>
          </Card>

          <Card className="bg-panel border-border">
            <CardHeader>
              <CardTitle>OCR Engine</CardTitle>
              <CardDescription>Optical character recognition for scanned PDFs and images.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center gap-4">
                <span className="text-sm font-medium w-32">Status:</span>
                {config?.ocr_enabled ? (
                  config?.ocr_available ? (
                    <Badge className="bg-success/20 text-success uppercase">Enabled &amp; Ready</Badge>
                  ) : (
                    <Badge className="bg-warning/20 text-warning uppercase">Enabled (engine not installed)</Badge>
                  )
                ) : (
                  <Badge variant="secondary" className="bg-surface uppercase">Disabled</Badge>
                )}
              </div>
              <div className="flex items-center gap-4">
                <span className="text-sm font-medium w-32">Engine:</span>
                <Badge variant="outline" className="text-xs uppercase">
                  {config?.ocr_engine || "—"} {config?.ocr_version ? `(${config.ocr_version})` : ""}
                </Badge>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-sm font-medium w-32">Language:</span>
                <Badge variant="outline" className="text-xs uppercase">{config?.ocr_language || "—"}</Badge>
              </div>
              {config?.ocr_enabled && !config?.ocr_available && (
                <p className="text-xs text-muted-foreground pt-1">
                  Install the OCR backend to enable scanned-document text recognition:
                  <code className="ml-1 px-1.5 py-0.5 rounded bg-surface">pip install paddleocr paddlepaddle</code>
                </p>
              )}
            </CardContent>
          </Card>

          <Card className="bg-panel border-border">
            <CardHeader>
              <CardTitle>Content Cache</CardTitle>
              <CardDescription>Reuses OCR, analysis, and embeddings across identical document content.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex items-center gap-4">
                <span className="text-sm font-medium w-32">Status:</span>
                {config?.content_cache_enabled ? (
                  <Badge className="bg-success/20 text-success uppercase">Enabled</Badge>
                ) : (
                  <Badge variant="secondary" className="bg-surface uppercase">Disabled</Badge>
                )}
              </div>
            </CardContent>
          </Card>

          <Card className="bg-panel border-border">
            <CardHeader>
              <CardTitle>Taxonomy Categories</CardTitle>
              <CardDescription>Allowed categories for document classification.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {config?.categories.map(cat => (
                  <Badge key={cat} variant="secondary" className="bg-surface text-xs">{cat}</Badge>
                )) || <span className="text-sm text-muted-foreground">Loading...</span>}
              </div>
            </CardContent>
          </Card>
        </div>
      </ScrollArea>
    </div>
  );
}
