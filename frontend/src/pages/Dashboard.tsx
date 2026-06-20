import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { DashboardStats } from "@/services/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Files, CheckCircle2, Copy, Image as ImageIcon, Trash2, AlertTriangle } from "lucide-react";

export default function Dashboard({ folder }: { folder?: string }) {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getStats(folder).then(s => {
      setStats(s);
      setLoading(false);
    }).catch(e => {
      console.error(e);
      setLoading(false);
    });
  }, [folder]);

  if (loading) return (
    <div className="flex flex-col items-center justify-center h-full p-8 text-muted-foreground animate-pulse">
      <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin mb-4"></div>
      <p className="text-lg font-medium">Connecting to AI Engine...</p>
      <p className="text-sm">Please wait, starting local models may take 10-20 seconds.</p>
    </div>
  );
  if (!stats) return (
    <div className="h-full flex flex-col items-center justify-center p-8 text-center animate-in fade-in">
      <div className="w-16 h-16 bg-muted/50 rounded-full flex items-center justify-center mb-6">
        <svg className="w-8 h-8 text-muted-foreground" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
      </div>
      <h2 className="text-xl font-semibold mb-2">Service Unavailable</h2>
      <p className="text-muted-foreground max-w-md">
        DocuWise couldn't connect to the local processing engine. Ensure the backend models have successfully loaded and aren't blocked by your firewall.
      </p>
    </div>
  );

  return (
    <div className="h-full overflow-y-auto p-8 space-y-8 animate-in fade-in">
      <div>
        <h1 className="text-3xl font-bold tracking-tight mb-2">Overview</h1>
        <p className="text-muted-foreground">
          {folder ? `Analysis for ${folder}` : "Complete workspace overview"}
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <StatCard title="Total Docs" value={stats.total_documents} icon={Files} color="text-blue-500" />
        <StatCard title="Fully Processed" value={stats.embedded} icon={CheckCircle2} color="text-success" />
        <StatCard title="Duplicates" value={stats.duplicates} icon={Copy} color="text-warning" />
        <StatCard title="Image PDFs" value={stats.image_only} icon={ImageIcon} color="text-purple-500" />
        <StatCard title="Cleanup" value={stats.cleanup_candidates} icon={Trash2} color="text-destructive" />
        <StatCard title="Failed" value={stats.failed} icon={AlertTriangle} color="text-orange-500" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <Card className="lg:col-span-2 bg-panel border-border">
          <CardHeader>
            <CardTitle>Category Distribution</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {stats.categories.length === 0 ? (
              <p className="text-sm text-muted-foreground">No categories found yet.</p>
            ) : (
              stats.categories.map(c => (
                <div key={c.name} className="space-y-1">
                  <div className="flex justify-between text-sm">
                    <span className="font-medium">{c.name}</span>
                    <span className="text-muted-foreground">{c.count}</span>
                  </div>
                  <div className="h-2 w-full bg-surface rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-primary rounded-full transition-all duration-1000" 
                      style={{ width: `${Math.max(2, (c.count / stats.total_documents) * 100)}%` }}
                    />
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="bg-panel border-border">
          <CardHeader>
            <CardTitle>Important Documents</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {stats.top_documents.length === 0 ? (
               <p className="text-sm text-muted-foreground">No documents analyzed.</p>
            ) : (
              stats.top_documents.map((doc, i) => (
                <div key={i} className="flex items-center justify-between p-3 rounded-lg bg-surface border border-border/50">
                  <div className="overflow-hidden mr-4">
                    <p className="text-sm font-medium truncate" title={doc.filename}>{doc.filename}</p>
                    <p className="text-xs text-muted-foreground">{doc.category}</p>
                  </div>
                  <div className="flex-shrink-0 flex flex-col items-center justify-center w-10 h-10 rounded-md bg-background border border-border">
                    <span className="text-sm font-bold text-primary">{doc.importance}</span>
                  </div>
                </div>
              ))
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function StatCard({ title, value, icon: Icon, color }: any) {
  return (
    <Card className="bg-panel border-border">
      <CardContent className="p-6 flex flex-col items-center justify-center text-center space-y-2">
        <div className={`p-3 rounded-full bg-surface ${color}`}>
          <Icon className="w-5 h-5" />
        </div>
        <div className="space-y-1">
          <p className="text-2xl font-bold">{value}</p>
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{title}</p>
        </div>
      </CardContent>
    </Card>
  );
}
