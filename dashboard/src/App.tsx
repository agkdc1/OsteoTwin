import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Sidebar } from './components/Sidebar';
import { Overview } from './pages/Overview';
import { ActiveCases } from './pages/ActiveCases';
import { Infrastructure } from './pages/Infrastructure';
import { Settings } from './pages/Settings';
import { Viewer } from './pages/Viewer';
import { VoiceConsole } from './pages/VoiceConsole';
import { getToken } from './lib/api';
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
  if (!getToken()) return <Navigate to="/login" replace />;
  return <Layout>{children}</Layout>;
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
          <Route path="/settings" element={<ProtectedRoute><Settings /></ProtectedRoute>} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
