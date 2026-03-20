import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Sidebar } from './components/Sidebar';
import { Overview } from './pages/Overview';
import { ActiveCases } from './pages/ActiveCases';
import { Infrastructure } from './pages/Infrastructure';
import { Settings } from './pages/Settings';
import { Viewer } from './pages/Viewer';
import { VoiceConsole } from './pages/VoiceConsole';
import { PrinterAdmin } from './pages/PrinterAdmin';
import { AuditReport } from './pages/AuditReport';
import { getToken, cfLogin } from './lib/api';
import { Login } from './pages/Login';

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchInterval: 15000 } },
});

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 overflow-auto p-6">{children}</main>
    </div>
  );
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const [checking, setChecking] = useState(!getToken());

  useEffect(() => {
    if (!getToken()) {
      // Try Cloudflare Access auto-login before redirecting
      cfLogin().then((ok) => {
        if (!ok) setChecking(false);
        else window.location.reload();
      });
    }
  }, []);

  if (getToken()) return <Layout>{children}</Layout>;
  if (checking) return <div className="flex h-screen items-center justify-center">Authenticating...</div>;
  return <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<ProtectedRoute><Overview /></ProtectedRoute>} />
          <Route path="/cases" element={<ProtectedRoute><ActiveCases /></ProtectedRoute>} />
          <Route path="/viewer" element={<ProtectedRoute><Viewer /></ProtectedRoute>} />
          <Route path="/voice" element={<ProtectedRoute><VoiceConsole /></ProtectedRoute>} />
          <Route path="/infra" element={<ProtectedRoute><Infrastructure /></ProtectedRoute>} />
          <Route path="/admin/printer-config" element={<ProtectedRoute><PrinterAdmin /></ProtectedRoute>} />
          <Route path="/audit" element={<ProtectedRoute><AuditReport /></ProtectedRoute>} />
          <Route path="/settings" element={<ProtectedRoute><Settings /></ProtectedRoute>} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
