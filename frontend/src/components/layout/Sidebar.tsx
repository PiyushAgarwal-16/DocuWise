import { NavLink } from "react-router-dom";
import { 
  LayoutDashboard, 
  Files, 
  Copy, 
  Image as ImageIcon, 
  Trash2, 
  Settings,
  FolderOpen,
  Play
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { open } from '@tauri-apps/plugin-dialog';

interface SidebarProps {
  folder?: string;
  setFolder: (folder: string) => void;
  onScan: () => void;
  scanning: boolean;
}

const navItems = [
  { name: "Dashboard", path: "/dashboard", icon: LayoutDashboard },
  { name: "Documents", path: "/documents", icon: Files },
  { name: "Duplicates", path: "/duplicates", icon: Copy },
  { name: "Image PDFs", path: "/image-pdfs", icon: ImageIcon },
  { name: "Cleanup", path: "/cleanup", icon: Trash2 },
];

export default function Sidebar({ folder, setFolder, onScan, scanning }: SidebarProps) {
  
  const handleSelectFolder = async () => {
    const selected = await open({
      directory: true,
      multiple: false,
    });
    if (selected && typeof selected === "string") {
      setFolder(selected);
    }
  };

  return (
    <div className="w-64 bg-panel border-r border-border flex flex-col h-screen overflow-hidden">
      <div className="p-4 pt-6">
        <h1 className="text-xl font-bold text-foreground px-2">DocuWise</h1>
        <p className="text-[10px] text-muted-foreground uppercase tracking-wider px-2 mb-6">Document Intelligence</p>
        
        <nav className="space-y-1">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors",
                  isActive
                    ? "bg-primary/20 text-primary font-semibold"
                    : "text-muted-foreground hover:bg-surface hover:text-foreground"
                )
              }
            >
              <item.icon className="w-4 h-4" />
              {item.name}
            </NavLink>
          ))}
        </nav>
      </div>

      <div className="mt-auto p-4 space-y-4">
        <Button 
          className="w-full justify-start gap-2 h-11" 
          onClick={onScan}
          disabled={!folder || scanning}
        >
          <Play className="w-4 h-4" />
          {scanning ? "Scanning..." : "Start Scan"}
        </Button>

        <div className="pt-4 border-t border-border">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2">Current Folder</p>
          <div className="text-xs text-foreground truncate mb-3" title={folder || "None"}>
            {folder ? (
              <span className="flex items-center gap-2">
                <FolderOpen className="w-3 h-3 text-primary" />
                <span className="truncate">{folder.split(/[\\/]/).pop()}</span>
              </span>
            ) : "No folder selected"}
          </div>
          <Button variant="secondary" className="w-full text-xs h-9" onClick={handleSelectFolder}>
            Change Folder
          </Button>
        </div>

        <div className="pt-2">
          <NavLink
            to="/settings"
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary/20 text-primary"
                  : "text-muted-foreground hover:bg-surface hover:text-foreground"
              )
            }
          >
            <Settings className="w-4 h-4" />
            Settings
          </NavLink>
        </div>
      </div>
    </div>
  );
}
