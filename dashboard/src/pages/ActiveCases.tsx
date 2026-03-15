import { useState } from 'react';
import { FolderOpen, Upload, Play, FileDown } from 'lucide-react';

interface Case {
  id: string;
  title: string;
  aoCode: string;
  status: 'uploaded' | 'segmented' | 'simulating' | 'plan_ready';
  fragments: number;
  created: string;
}

const STATUS_COLORS = {
  uploaded: { bg: '#1a73e8', label: 'DICOM Uploaded' },
  segmented: { bg: '#e65100', label: 'Segmented' },
  simulating: { bg: '#ab47bc', label: 'Simulating' },
  plan_ready: { bg: '#2e7d32', label: 'Plan Ready' },
};

// Demo data — will be replaced with API calls
const DEMO_CASES: Case[] = [
  { id: 'synth_wrist_001', title: 'Distal Radius Fracture (Synthetic)', aoCode: '23-A2', status: 'plan_ready', fragments: 2, created: '2026-03-15' },
];

export function ActiveCases() {
  const [cases] = useState<Case[]>(DEMO_CASES);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold" style={{ color: 'var(--accent)' }}>Active Cases</h1>
        <button className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium"
          style={{ background: '#1a73e8', color: 'white' }}>
          <Upload size={16} /> New Case
        </button>
      </div>

      {/* Case List */}
      <div className="rounded-lg border overflow-hidden" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b" style={{ borderColor: 'var(--border)' }}>
              <th className="text-left p-3 font-medium" style={{ color: 'var(--text-muted)' }}>Case</th>
              <th className="text-left p-3 font-medium" style={{ color: 'var(--text-muted)' }}>AO Code</th>
              <th className="text-left p-3 font-medium" style={{ color: 'var(--text-muted)' }}>Status</th>
              <th className="text-left p-3 font-medium" style={{ color: 'var(--text-muted)' }}>Fragments</th>
              <th className="text-left p-3 font-medium" style={{ color: 'var(--text-muted)' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {cases.map(c => {
              const st = STATUS_COLORS[c.status];
              return (
                <tr key={c.id} className="border-b hover:bg-white/5 transition-colors"
                  style={{ borderColor: 'var(--border)' }}>
                  <td className="p-3">
                    <div className="flex items-center gap-2">
                      <FolderOpen size={16} style={{ color: 'var(--accent)' }} />
                      <div>
                        <div className="font-medium">{c.title}</div>
                        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{c.id}</div>
                      </div>
                    </div>
                  </td>
                  <td className="p-3 font-mono text-xs">{c.aoCode}</td>
                  <td className="p-3">
                    <span className="px-2 py-0.5 rounded-full text-xs font-semibold"
                      style={{ background: st.bg + '33', color: st.bg === '#2e7d32' ? '#a5d6a7' : 'white' }}>
                      {st.label}
                    </span>
                  </td>
                  <td className="p-3">{c.fragments}</td>
                  <td className="p-3 flex gap-2">
                    <button className="p-1 rounded hover:bg-white/10" title="View in 3D">
                      <Play size={14} style={{ color: 'var(--accent)' }} />
                    </button>
                    <button className="p-1 rounded hover:bg-white/10" title="Export STL">
                      <FileDown size={14} style={{ color: 'var(--success)' }} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
