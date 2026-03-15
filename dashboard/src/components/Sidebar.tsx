import { NavLink } from 'react-router-dom';
import { LayoutDashboard, FolderOpen, Box, Volume2, Server, Settings, LogOut } from 'lucide-react';
import { clearToken, getUsername } from '../lib/api';

const navItems = [
  { to: '/', icon: LayoutDashboard, label: 'Overview' },
  { to: '/cases', icon: FolderOpen, label: 'Active Cases' },
  { to: '/viewer', icon: Box, label: '3D Viewer' },
  { to: '/voice', icon: Volume2, label: 'Voice Console' },
  { to: '/infra', icon: Server, label: 'Infrastructure' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

export function Sidebar() {
  return (
    <aside className="w-60 h-screen flex flex-col border-r"
      style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>

      {/* Logo */}
      <div className="p-5 border-b" style={{ borderColor: 'var(--border)' }}>
        <h1 className="text-lg font-bold" style={{ color: 'var(--accent)' }}>
          OsteoTwin
        </h1>
        <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
          Command Center
        </p>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-3 space-y-1">
        {navItems.map(({ to, icon: Icon, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded text-sm transition-colors ${
                isActive
                  ? 'bg-[#1a73e8]/20 text-[var(--accent)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-white/5'
              }`
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* User */}
      <div className="p-4 border-t flex items-center justify-between"
        style={{ borderColor: 'var(--border)' }}>
        <span className="text-sm" style={{ color: 'var(--text-muted)' }}>
          {getUsername()}
        </span>
        <button
          onClick={() => { clearToken(); window.location.href = '/login'; }}
          className="p-1 rounded hover:bg-white/10 transition-colors"
          style={{ color: 'var(--text-muted)' }}
          title="Logout"
        >
          <LogOut size={16} />
        </button>
      </div>
    </aside>
  );
}
