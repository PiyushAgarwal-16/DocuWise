import { useEffect, useState, useRef } from "react";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ScanProgressEvent } from "@/services/types";
import { Zap, Terminal, XCircle } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { api } from "@/services/api";

interface ScanOverlayProps {
  onComplete: () => void;
}

export default function ScanOverlay({ onComplete }: ScanOverlayProps) {
  const [stats, setStats] = useState({ current: 0, total: 1 });
  const [elapsed, setElapsed] = useState(0);
  const [currentFile, setCurrentFile] = useState<string>("");
  const [stage, setStage] = useState<string>("Initializing...");
  const [logs, setLogs] = useState<string[]>([]);
  const [status, setStatus] = useState<"processing" | "complete" | "error" | "stopping">("processing");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let interval: NodeJS.Timeout;
    if (status === "processing") {
      interval = setInterval(() => {
        setElapsed((prev) => prev + 1);
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [status]);

  useEffect(() => {
    const source = new EventSource("http://127.0.0.1:8765/api/scan/progress");
    
    source.onmessage = (e) => {
      try {
        const data: ScanProgressEvent = JSON.parse(e.data);
        
        if (data.type === "progress") {
          setStats({
            current: data.current || 0,
            total: data.total || 1
          });
          if (data.filename) setCurrentFile(data.filename.split(/[\\/]/).pop() || "");
          if (data.stage) setStage(data.stage);
        } 
        else if (data.type === "log") {
          if (data.stage) setStage(data.stage);
          if (data.message) {
            setLogs(prev => [...prev.slice(-49), data.message!]);
          }
        }
        else if (data.type === "complete" || data.type === "error") {
          setStatus(data.type);
          source.close();
          if (data.type === "error" && data.error !== "Scan stopped by user") {
            alert("Scan failed: " + data.error);
          }
          setTimeout(() => onComplete(), 1500);
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

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const handleStop = async () => {
    try {
      setStatus("stopping");
      setStage("Stopping engine gracefully...");
      await api.stopScan();
    } catch (e) {
      console.error(e);
    }
  };

  const { current, total } = stats;
  const pct = Math.round((current / total) * 100) || 0;
  
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
      <Card className="w-full max-w-3xl bg-panel border-border shadow-2xl p-10 flex flex-col items-center animate-in fade-in zoom-in duration-300 relative">
        {status === "processing" && (
          <Button 
            variant="ghost" 
            size="sm" 
            onClick={handleStop}
            className="absolute top-4 right-4 text-muted-foreground hover:text-destructive transition-colors"
          >
            <XCircle className="w-4 h-4 mr-2" />
            Stop Scan
          </Button>
        )}

        <div className="w-16 h-16 bg-primary/20 rounded-full flex items-center justify-center mb-6">
          <Zap className={`w-8 h-8 text-primary ${status === "processing" ? "animate-pulse" : ""}`} />
        </div>
        
        <h2 className="text-2xl font-bold text-foreground mb-2">
          {status === "complete" ? "Scan Complete ✓" : 
           status === "stopping" ? "Stopping Scan..." :
           status === "error" ? "Scan Stopped" : "Processing Documents"}
        </h2>
        
        <div className="text-center mb-8 h-12">
          <p className="text-muted-foreground text-sm font-medium">
            <span className="text-primary mr-2">{stage}</span>
            <span className="text-foreground">{currentFile}</span>
          </p>
        </div>

        <div className="w-full space-y-2 mb-8">
          <div className="flex justify-between text-xs font-medium text-muted-foreground">
            <span>{current} of {total} files</span>
            <span>{pct}%</span>
          </div>
          <Progress value={pct} className="h-3" />
        </div>

        <div className="grid grid-cols-4 gap-4 w-full mb-8">
          <MetricBox label="Progress" value={`${current}/${total}`} />
          <MetricBox label="Elapsed" value={formatTime(elapsed)} />
          <MetricBox label="ETA" value={status === "processing" ? formatTime(eta) : "—"} />
          <MetricBox label="Speed" value={status === "processing" ? `${Math.round(rate)}/min` : "—"} />
        </div>

        <div className="w-full bg-[#0a0a0c] border border-border/50 rounded-md p-3 h-40 flex flex-col">
          <div className="flex items-center gap-2 mb-2 px-1 text-xs font-medium text-muted-foreground uppercase tracking-wider">
            <Terminal className="w-3 h-3" /> Live Terminal Log
          </div>
          <div 
            ref={scrollRef}
            className="flex-1 overflow-y-auto font-mono text-[11px] text-muted-foreground/80 space-y-1.5 scroll-smooth"
          >
            {logs.length === 0 ? (
              <div className="text-muted-foreground/40 italic">Waiting for engine output...</div>
            ) : (
              logs.map((l, i) => (
                <div key={i} className="break-words">
                  <span className="text-primary/50 mr-2">{'>'}</span>{l}
                </div>
              ))
            )}
          </div>
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
