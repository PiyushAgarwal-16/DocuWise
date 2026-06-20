import { useState } from "react";
import Sidebar from "./Sidebar";
import ScanOverlay from "../ScanOverlay";
import { api } from "@/services/api";

interface AppShellProps {
  children: React.ReactNode;
  folder?: string;
  setFolder: (folder: string) => void;
}

export default function AppShell({ children, folder, setFolder }: AppShellProps) {
  const [scanning, setScanning] = useState(false);

  const handleScan = async () => {
    if (!folder) return;
    try {
      await api.startScan(folder);
      setScanning(true);
    } catch (e: any) {
      alert("Failed to start scan: " + e.message);
    }
  };

  return (
    <div className="flex h-screen w-screen bg-background overflow-hidden text-foreground font-sans">
      <Sidebar 
        folder={folder} 
        setFolder={setFolder} 
        onScan={handleScan} 
        scanning={scanning} 
      />
      <main className="flex-1 relative h-screen overflow-hidden bg-background">
        {children}
        {scanning && (
          <div className="absolute inset-0 z-50 bg-background/95 backdrop-blur-sm">
            <ScanOverlay onComplete={() => setScanning(false)} />
          </div>
        )}
      </main>
    </div>
  );
}
