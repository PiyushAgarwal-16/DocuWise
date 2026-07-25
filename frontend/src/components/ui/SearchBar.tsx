import { useState, useEffect, useRef } from "react";
import { Search, Loader2 } from "lucide-react";
import { useNavigate, useLocation } from "react-router-dom";
import { api } from "@/services/api";

export default function SearchBar() {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Sync input with URL when navigating to search page
  useEffect(() => {
    if (location.pathname === "/search") {
      const q = new URLSearchParams(location.search).get("q");
      if (q && q !== query) setQuery(q);
    }
  }, [location]);

  useEffect(() => {
    const fetchSuggestions = async () => {
      if (query.trim().length < 2) {
        setSuggestions([]);
        return;
      }
      setLoading(true);
      try {
        const res = await api.suggest(5);
        // Basic frontend filtering of past searches
        const filtered = res.suggestions.filter(s => s.toLowerCase().includes(query.toLowerCase()));
        setSuggestions(filtered);
      } catch (e) {
        // ignore
      } finally {
        setLoading(false);
      }
    };

    const timer = setTimeout(fetchSuggestions, 300);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setShowSuggestions(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSearch = (searchQuery: string) => {
    if (!searchQuery.trim()) return;
    setShowSuggestions(false);
    navigate(`/search?q=${encodeURIComponent(searchQuery)}`);
  };

  return (
    <div className="relative w-full max-w-xl" ref={wrapperRef}>
      <div className="relative flex items-center">
        <Search className="absolute left-3 w-4 h-4 text-muted-foreground" />
        <input
          type="text"
          value={query}
          spellCheck={false}
          onChange={(e) => {
            setQuery(e.target.value);
            setShowSuggestions(true);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              handleSearch(query);
            }
          }}
          onFocus={() => setShowSuggestions(true)}
          placeholder="Search documents by content, concept, or domain..."
          className="w-full h-10 pl-9 pr-4 bg-background border border-border rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-primary focus:border-primary transition-all text-foreground placeholder:text-muted-foreground"
        />
        {loading && <Loader2 className="absolute right-3 w-4 h-4 text-muted-foreground animate-spin" />}
      </div>

      {showSuggestions && suggestions.length > 0 && (
        <div className="absolute top-full left-0 right-0 mt-1 bg-popover border border-border rounded-lg shadow-lg overflow-hidden z-50">
          <div className="py-1">
            {suggestions.map((suggestion, i) => (
              <button
                key={i}
                className="w-full text-left px-4 py-2 text-sm text-foreground hover:bg-primary/10 hover:text-primary transition-colors flex items-center gap-2"
                onClick={() => {
                  setQuery(suggestion);
                  handleSearch(suggestion);
                }}
              >
                <Search className="w-3 h-3 text-muted-foreground" />
                {suggestion}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
