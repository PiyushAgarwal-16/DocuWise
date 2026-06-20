import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ScanProgressEvent } from "@/services/types";
import { Zap } from "lucide-react";

interface ScanOverlayProps {
  onComplete: () => void;
}

export default function ScanOverlay({ onComplete }: ScanOverlayProps) {
  const [progress, setProgress] = useState<ScanProgressEvent | null>(null);

  useEffect(() => {
    const source = new EventSource("http://127.0.0.1:8765/api/scan/progress");
    
    source.onmessage = (e) => {
      try {
        const data: ScanProgressEvent = JSON.parse(e.data);
        setProgress(data);
        
        if (data.type === "complete" || data.type === "error") {
          source.close();
          if (data.type === "error") {
            alert("Scan failed: " + data.error);
          }
          // Slight delay to show 100% before closing
          setTimeout(() => onComplete(), 1000);
        }
      } catch (err) {
        console.error("Failed to parse SSE", err);
      }
    };

    source.onerror = (err) => {
      console.error("SSE Error", err);
      source.close();
      onComplete();
    };

    return () => source.close();
  }, [onComplete]);

  const current = progress?.current || 0;
  const total = progress?.total || 1;
  const pct = Math.round((current / total) * 100) || 0;
  
  const elapsed = progress?.elapsed_seconds || 0;
  const rate = elapsed > 0 ? (current / elapsed) * 60 : 0;
  const remaining = total - current;
  const eta = rate > 0 ? remaining / (rate / 60) : 0;

  const formatTime = (secs: number) => {
    if (!isFinite(secs) || secs < 0) return "—";
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  };

  return (
    <div className="flex items-center justify-center h-full w-full p-8">
      <Card className="w-full max-w-2xl bg-panel border-border shadow-2xl p-10 flex flex-col items-center animate-in fade-in zoom-in duration-300">
        <div className="w-16 h-16 bg-primary/20 rounded-full flex items-center justify-center mb-6">
          <Zap className="w-8 h-8 text-primary animate-pulse" />
        </div>
        
        <h2 className="text-2xl font-bold text-foreground mb-2">
          {progress?.type === "complete" ? "Scan Complete ✓" : "Processing Documents"}
        </h2>
        
        <p className="text-muted-foreground text-sm mb-8 text-center max-w-md h-5 truncate">
          {progress?.stage ? (
             <span className="font-semibold text-primary mr-2">{progress.stage}</span>
          ) : "Initializing..."}
          {progress?.filename && (
            <span className="text-foreground">{progress.filename.split(/[\\/]/).pop()}</span>
          )}
        </p>

        <div className="w-full space-y-2 mb-8">
          <div className="flex justify-between text-xs font-medium text-muted-foreground">
            <span>{current} of {total} files</span>
            <span>{pct}%</span>
          </div>
          <Progress value={pct} className="h-3" />
        </div>

        <div className="grid grid-cols-4 gap-4 w-full">
          <MetricBox label="Progress" value={`${current}/${total}`} />
          <MetricBox label="Elapsed" value={formatTime(elapsed)} />
          <MetricBox label="ETA" value={formatTime(eta)} />
          <MetricBox label="Speed" value={`${Math.round(rate)}/min`} />
        </div>
      </Card>
    </div>
  );
}

function MetricBox({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-surface rounded-lg p-4 flex flex-col items-center justify-center border border-border/50">
      <span className="text-xl font-bold text-foreground mb-1">{value}</span>
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</span>
    </div>
  );
}
