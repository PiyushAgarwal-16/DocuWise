import { HashRouter as Router, Routes, Route, Navigate } from "react-router-dom";
import AppShell from "./components/layout/AppShell";
import Dashboard from "./pages/Dashboard";
import Documents from "./pages/Documents";
import Duplicates from "./pages/Duplicates";
import ImagePdfs from "./pages/ImagePdfs";
import Cleanup from "./pages/Cleanup";
import Settings from "./pages/Settings";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { useState } from "react";

function App() {
  const [folder, setFolder] = useState<string | undefined>(undefined);

  return (
    <Router>
      <AppShell folder={folder} setFolder={setFolder}>
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<Navigate to="/dashboard" replace />} />
            <Route path="/dashboard" element={<Dashboard folder={folder} />} />
            <Route path="/documents" element={<Documents folder={folder} />} />
            <Route path="/duplicates" element={<Duplicates folder={folder} />} />
            <Route path="/image-pdfs" element={<ImagePdfs folder={folder} />} />
            <Route path="/cleanup" element={<Cleanup folder={folder} />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </ErrorBoundary>
      </AppShell>
    </Router>
  );
}

export default App;
