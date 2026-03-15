import { useState } from 'react';
import { Key, Globe } from 'lucide-react';

export function Settings() {
  const [simKey, setSimKey] = useState(localStorage.getItem('osteotwin_sim_key') || '');

  function saveSimKey() {
    localStorage.setItem('osteotwin_sim_key', simKey);
    alert('Simulation API key saved');
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6" style={{ color: 'var(--accent)' }}>Settings</h1>

      {/* API Keys */}
      <div className="rounded-lg border p-6 mb-4" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
        <div className="flex items-center gap-2 mb-4">
          <Key size={16} style={{ color: 'var(--accent)' }} />
          <h2 className="text-sm font-medium">API Keys (Browser-side)</h2>
        </div>
        <div className="space-y-3">
          <div>
            <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>
              Simulation Server API Key (SIM_API_KEY)
            </label>
            <div className="flex gap-2">
              <input
                type="password" value={simKey} onChange={e => setSimKey(e.target.value)}
                placeholder="Paste SIM_API_KEY from .env"
                className="flex-1 px-3 py-2 rounded border text-sm"
                style={{ background: '#1a1a2e', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
              />
              <button onClick={saveSimKey}
                className="px-4 py-2 rounded text-sm font-medium"
                style={{ background: '#1a73e8', color: 'white' }}>
                Save
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Server URLs */}
      <div className="rounded-lg border p-6" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
        <div className="flex items-center gap-2 mb-4">
          <Globe size={16} style={{ color: 'var(--accent)' }} />
          <h2 className="text-sm font-medium">Server Configuration</h2>
        </div>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between py-1 border-b" style={{ borderColor: 'var(--border)' }}>
            <span style={{ color: 'var(--text-muted)' }}>Planning Server</span>
            <span className="font-mono">http://localhost:8200</span>
          </div>
          <div className="flex justify-between py-1 border-b" style={{ borderColor: 'var(--border)' }}>
            <span style={{ color: 'var(--text-muted)' }}>Simulation Server</span>
            <span className="font-mono">http://localhost:8300</span>
          </div>
          <div className="flex justify-between py-1 border-b" style={{ borderColor: 'var(--border)' }}>
            <span style={{ color: 'var(--text-muted)' }}>GCP Project</span>
            <span className="font-mono">osteotwin-37f03c</span>
          </div>
          <div className="flex justify-between py-1">
            <span style={{ color: 'var(--text-muted)' }}>Dashboard</span>
            <span className="font-mono">http://localhost:5173</span>
          </div>
        </div>
      </div>
    </div>
  );
}
