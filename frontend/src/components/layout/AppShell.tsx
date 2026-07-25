import { useState } from "react";
import Sidebar from "./Sidebar";
import ScanOverlay from "../ScanOverlay";
import { api } from "@/services/api";
import SearchBar from "../ui/SearchBar";

interface AppShellProps {
  children: React.ReactNode;
  folder?: string;
  setFolder: (folder: string) => void;
}

export default function AppShell({ children, folder, setFolder }: AppShellProps) {
  const [scanning, setScanning] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  const handleScan = async () => {
    if (!folder) return;
    try {
      await api.startScan(folder);
      setScanning(true);
    } catch (e: any) {
      alert("Failed to start scan: " + e.message);
    }
  };

  const handleScanComplete = () => {
    setScanning(false);
    // Incrementing this key will force all child routes (like Dashboard)
    // to unmount and remount, instantly refetching the latest stats!
    setRefreshKey(prev => prev + 1);
  };

  return (
    <div className="flex h-screen w-screen bg-background overflow-hidden text-foreground font-sans">
      <Sidebar 
        folder={folder} 
        setFolder={setFolder} 
        onScan={handleScan} 
        scanning={scanning} 
      />
      <main className="flex-1 relative flex flex-col h-screen overflow-hidden bg-background">
        {/* Top Header */}
        <header className="h-14 border-b border-border flex items-center px-6 bg-background/80 backdrop-blur-sm z-10 shrink-0">
          <div className="flex-1 max-w-3xl">
            <SearchBar />
          </div>
        </header>
        <div key={refreshKey} className="flex-1 overflow-auto w-full relative">
          {children}
        </div>
        {scanning && (
          <div className="absolute inset-0 z-50 bg-background/95 backdrop-blur-sm">
            <ScanOverlay onComplete={handleScanComplete} />
          </div>
        )}
      </main>
    </div>
  );
}
