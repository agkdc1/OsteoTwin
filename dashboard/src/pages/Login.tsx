import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { login } from '../lib/api';

export function Login() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(username, password);

      // Also prompt for SIM API key if not set
      if (!localStorage.getItem('osteotwin_sim_key')) {
        const simKey = prompt('Enter Simulation Server API Key (SIM_API_KEY):');
        if (simKey) localStorage.setItem('osteotwin_sim_key', simKey);
      }

      navigate('/');
    } catch (err: any) {
      setError(err.message);
    }
    setLoading(false);
  }

  return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="w-96 rounded-lg border p-8"
        style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
        <h1 className="text-2xl font-bold mb-1" style={{ color: 'var(--accent)' }}>OsteoTwin</h1>
        <p className="text-sm mb-6" style={{ color: 'var(--text-muted)' }}>Command Center Login</p>

        <form onSubmit={handleSubmit} className="space-y-4">
          <input
            type="text" value={username} onChange={e => setUsername(e.target.value)}
            placeholder="Username" required
            className="w-full px-3 py-2 rounded border text-sm"
            style={{ background: '#1a1a2e', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
          />
          <input
            type="password" value={password} onChange={e => setPassword(e.target.value)}
            placeholder="Password" required
            className="w-full px-3 py-2 rounded border text-sm"
            style={{ background: '#1a1a2e', borderColor: 'var(--border)', color: 'var(--text-primary)' }}
          />
          {error && <p className="text-sm" style={{ color: 'var(--danger)' }}>{error}</p>}
          <button
            type="submit" disabled={loading}
            className="w-full py-2 rounded text-sm font-medium transition-colors"
            style={{ background: '#1a73e8', color: 'white' }}
          >
            {loading ? 'Logging in...' : 'Login'}
          </button>
        </form>
      </div>
    </div>
  );
}
