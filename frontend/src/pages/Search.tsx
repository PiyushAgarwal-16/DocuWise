import { useState, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { SearchResult } from "@/services/types";
import { api } from "@/services/api";
import { Loader2, FileText, Brain, Tag, Globe, Sparkles, Target, Activity } from "lucide-react";
import { invoke } from "@tauri-apps/api/core";

export default function Search() {
  const [searchParams] = useSearchParams();
  const query = searchParams.get("q") || "";
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [categoryFilter, setCategoryFilter] = useState<string | undefined>();
  const [categories, setCategories] = useState<string[]>([]);

  useEffect(() => {
    // Load config categories for filters
    api.getConfig().then((cfg) => setCategories(cfg.categories || [])).catch(() => {});
  }, []);

  useEffect(() => {
    if (!query) {
      setResults([]);
      return;
    }
    
    setLoading(true);
    setError(null);
    
    api.search(query, 50, categoryFilter)
      .then((res: any) => {
        setResults(res.results || []);
      })
      .catch((err) => {
        setError(err.message || "Search failed");
      })
      .finally(() => {
        setLoading(false);
      });
  }, [query, categoryFilter]);

  const handleResultClick = async (res: any, position: number) => {
    try {
      // Fire and forget logging
      api.logSearchClick(query, res.id, position).catch(console.error);
      
      // Open the file
      await invoke("open_file", { path: res.file_path });
    } catch (e) {
      alert("Failed to open file: " + e);
    }
  };

  return (
    <div className="flex h-full">
      {/* Sidebar Filters */}
      <div className="w-64 border-r border-border bg-card p-6 flex flex-col gap-6 shrink-0">
        <div>
          <h3 className="text-sm font-semibold text-foreground mb-3 uppercase tracking-wider">Category</h3>
          <div className="space-y-2">
            <label className="flex items-center gap-2 text-sm text-foreground cursor-pointer">
              <input
                type="radio"
                name="category"
                checked={!categoryFilter}
                onChange={() => setCategoryFilter(undefined)}
                className="accent-primary"
              />
              All Categories
            </label>
            {categories.map((cat) => (
              <label key={cat} className="flex items-center gap-2 text-sm text-foreground cursor-pointer">
                <input
                  type="radio"
                  name="category"
                  checked={categoryFilter === cat}
                  onChange={() => setCategoryFilter(cat)}
                  className="accent-primary"
                />
                {cat}
              </label>
            ))}
          </div>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 p-8 overflow-y-auto">
        {!query ? (
          <div className="h-full flex flex-col items-center justify-center text-muted-foreground">
            <Sparkles className="w-12 h-12 mb-4 opacity-50" />
            <p>Enter a query in the top bar to search documents.</p>
          </div>
        ) : loading ? (
          <div className="flex items-center justify-center h-64 text-muted-foreground gap-3">
            <Loader2 className="w-6 h-6 animate-spin" />
            <p>Searching document intelligence...</p>
          </div>
        ) : error ? (
          <div className="p-4 bg-red-500/10 text-red-500 rounded-lg border border-red-500/20">
            {error}
          </div>
        ) : (
          <div>
            <h2 className="text-xl font-semibold mb-6">
              Found {results.length} result{results.length !== 1 ? 's' : ''} for "{query}"
            </h2>
            <div className="space-y-4">
              {results.map((res: any, idx: number) => (
                <div 
                  key={res.id} 
                  className="p-4 rounded-xl border border-border bg-card hover:border-primary/50 transition-colors cursor-pointer"
                  onClick={() => handleResultClick(res, idx + 1)}
                  title="Click to open document"
                >
                  <div className="flex justify-between items-start mb-2">
                    <h3 className="font-semibold text-lg text-primary truncate max-w-xl">
                      {res.filename}
                    </h3>
                    <div className="flex flex-col items-end gap-1">
                      <div className="flex items-center gap-2 bg-background px-2 py-1 rounded border border-border text-xs font-medium">
                        <Sparkles className="w-3 h-3 text-yellow-500" />
                        Score: {(res.search_score * 100).toFixed(0)}
                      </div>
                    </div>
                  </div>
                  
                  {res.subject && (
                    <p className="text-sm font-medium text-foreground mb-2">{res.subject}</p>
                  )}
                  {res.summary && (
                    <p className="text-sm text-muted-foreground mb-4 line-clamp-2">{res.summary}</p>
                  )}
                  
                  {/* Knowledge Chips */}
                  <div className="flex flex-wrap items-center justify-between gap-2 mt-4 pt-4 border-t border-border/50">
                    <div className="flex flex-wrap gap-2">
                      <div className="flex items-center gap-1.5 px-2 py-1 bg-blue-500/10 text-blue-400 rounded text-[10px] font-medium uppercase tracking-wider">
                        <FileText className="w-3 h-3" />
                        {res.category || "Uncategorized"}
                      </div>
                      {res.doc_type && (
                        <div className="flex items-center gap-1.5 px-2 py-1 bg-purple-500/10 text-purple-400 rounded text-[10px] font-medium uppercase tracking-wider">
                          <Tag className="w-3 h-3" />
                          {res.doc_type}
                        </div>
                      )}
                      
                      {/* Top Concept */}
                      {(() => {
                        try {
                          const concepts = JSON.parse(res.concepts_json || "[]");
                          if (concepts.length > 0) {
                            return (
                              <div className="flex items-center gap-1.5 px-2 py-1 bg-amber-500/10 text-amber-500 rounded text-[10px] font-medium uppercase tracking-wider">
                                <Brain className="w-3 h-3" />
                                {concepts[0]}
                              </div>
                            );
                          }
                        } catch (e) {}
                        return null;
                      })()}

                      {/* Top Domain */}
                      {(() => {
                        try {
                          const domains = JSON.parse(res.domains_json || "[]");
                          if (domains.length > 0) {
                            return (
                              <div className="flex items-center gap-1.5 px-2 py-1 bg-green-500/10 text-green-500 rounded text-[10px] font-medium uppercase tracking-wider">
                                <Globe className="w-3 h-3" />
                                {domains[0]}
                              </div>
                            );
                          }
                        } catch (e) {}
                        return null;
                      })()}
                    </div>

                    {/* Signal Breakdown */}
                    {res.signals && (
                      <div className="flex items-center gap-2 text-[10px] text-muted-foreground bg-background px-2 py-1 rounded border border-border">
                        <Activity className="w-3 h-3" />
                        <span>Vector: {(res.signals.embedding * 100).toFixed(0)}</span>
                        <span>•</span>
                        <span>Concept: {(res.signals.concepts * 100).toFixed(0)}</span>
                        <span>•</span>
                        <span>Lexical: {((res.signals.summary + res.signals.tags + res.signals.filename) * 100).toFixed(0)}</span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
              
              {results.length === 0 && !loading && (
                <div className="text-center py-12 text-muted-foreground">
                  <p>No results found for "{query}". Try adjusting your filters or using different keywords.</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
