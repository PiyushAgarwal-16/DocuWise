import { useEffect, useState } from "react";
import { api } from "@/services/api";
import { KnowledgeProfile } from "@/services/types";
import { Loader2, Brain, Globe, Tag, Target, ArrowRight, AlignLeft } from "lucide-react";

export default function KnowledgePanel({ documentId }: { documentId: number }) {
  const [profile, setProfile] = useState<KnowledgeProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    if (!documentId) return;

    setLoading(true);
    setError(null);
    api.getKnowledge(documentId)
      .then((res) => {
        if (active) setProfile(res);
      })
      .catch((err) => {
        if (active) setError(err.message || "Failed to load knowledge");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => { active = false; };
  }, [documentId]);

  if (loading) return <div className="flex justify-center p-4"><Loader2 className="w-4 h-4 animate-spin text-muted-foreground" /></div>;
  if (error) return <div className="text-red-500 text-xs p-4 bg-red-500/10 rounded">{error}</div>;
  if (!profile) return <div className="text-xs text-muted-foreground p-4">No knowledge profile found.</div>;

  const parseJson = (str: string | null) => {
    try {
      return str ? JSON.parse(str) : [];
    } catch {
      return [];
    }
  };

  const concepts = parseJson(profile.concepts_json);
  const entities = parseJson(profile.entities_json);
  const domains = parseJson(profile.domains_json);
  const prerequisites = parseJson(profile.prerequisites_json);

  return (
    <div className="space-y-4">
      {(profile.doc_type || profile.difficulty) && (
        <div className="flex gap-2 flex-wrap">
          {profile.doc_type && (
            <div className="px-2 py-1 bg-purple-500/10 text-purple-400 rounded text-xs font-medium uppercase tracking-wider flex items-center gap-1.5">
              <Tag className="w-3 h-3" /> {profile.doc_type}
            </div>
          )}
          {profile.difficulty && (
            <div className="px-2 py-1 bg-red-500/10 text-red-400 rounded text-xs font-medium uppercase tracking-wider flex items-center gap-1.5">
              <Target className="w-3 h-3" /> {profile.difficulty}
            </div>
          )}
        </div>
      )}

      {concepts.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Brain className="w-3 h-3" /> Key Concepts
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {concepts.map((c: string) => (
              <span key={c} className="px-2 py-1 bg-surface border border-border rounded-md text-xs font-medium text-foreground">
                {c}
              </span>
            ))}
          </div>
        </div>
      )}

      {domains.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <Globe className="w-3 h-3" /> Domains
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {domains.map((d: string) => (
              <span key={d} className="px-2 py-1 bg-surface border border-border rounded-md text-xs font-medium text-foreground">
                {d}
              </span>
            ))}
          </div>
        </div>
      )}
      
      {entities.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <AlignLeft className="w-3 h-3" /> Entities
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {entities.map((e: any, i: number) => (
              <span key={i} className="px-2 py-1 bg-surface border border-border rounded-md text-xs font-medium text-foreground" title={e.type}>
                {e.name}
              </span>
            ))}
          </div>
        </div>
      )}

      {prerequisites.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-1.5">
            <ArrowRight className="w-3 h-3" /> Prerequisites
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {prerequisites.map((p: string) => (
              <span key={p} className="px-2 py-1 bg-surface border border-border rounded-md text-xs font-medium text-foreground">
                {p}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
