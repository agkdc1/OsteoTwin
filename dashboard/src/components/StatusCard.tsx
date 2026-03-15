import type { LucideIcon } from 'lucide-react';

interface StatusCardProps {
  title: string;
  value: string;
  status: 'ok' | 'warn' | 'error' | 'neutral';
  icon: LucideIcon;
  subtitle?: string;
}

const statusColors = {
  ok: { bg: '#1b5e20', text: '#a5d6a7' },
  warn: { bg: '#e65100', text: '#ffcc02' },
  error: { bg: '#b71c1c', text: '#ef9a9a' },
  neutral: { bg: '#2a2a3a', text: '#9e9e9e' },
};

export function StatusCard({ title, value, status, icon: Icon, subtitle }: StatusCardProps) {
  const colors = statusColors[status];
  return (
    <div className="rounded-lg border p-4" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-medium" style={{ color: 'var(--text-muted)' }}>{title}</h3>
        <Icon size={18} style={{ color: 'var(--accent)' }} />
      </div>
      <div className="flex items-center gap-2">
        <span
          className="px-2 py-0.5 rounded-full text-xs font-semibold"
          style={{ background: colors.bg, color: colors.text }}
        >
          {value}
        </span>
      </div>
      {subtitle && (
        <p className="text-xs mt-2" style={{ color: 'var(--text-muted)' }}>{subtitle}</p>
      )}
    </div>
  );
}
