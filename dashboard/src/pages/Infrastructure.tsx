import { useQuery } from '@tanstack/react-query';
import { Activity, Cloud, HardDrive, Zap, MessageSquare, FolderArchive } from 'lucide-react';
import { StatusCard } from '../components/StatusCard';
import { planHealth, simHealth } from '../lib/api';

async function fetchPubSubStats() {
  // In production, this would call a backend endpoint that queries Pub/Sub admin API
  // For now, return placeholder data
  return {
    topic: 'simulation-tasks-topic',
    subscription: 'simulation-worker-sub',
    pendingMessages: 0,
    oldestUnackedAge: '0s',
  };
}

async function fetchGCSStats() {
  return {
    buckets: [
      { name: 'osteotwin-37f03c-data', purpose: 'Backups & worker code', region: 'us-west1' },
      { name: 'osteotwin-37f03c-dicom', purpose: 'Encrypted DICOM storage', region: 'asia-northeast1' },
      { name: 'osteotwin-37f03c-checkpoints', purpose: 'Simulation checkpoints', region: 'asia-northeast1' },
    ],
  };
}

export function Infrastructure() {
  const plan = useQuery({ queryKey: ['planHealth'], queryFn: planHealth });
  const sim = useQuery({ queryKey: ['simHealth'], queryFn: simHealth });
  const pubsub = useQuery({ queryKey: ['pubsub'], queryFn: fetchPubSubStats, refetchInterval: 30000 });
  const gcs = useQuery({ queryKey: ['gcs'], queryFn: fetchGCSStats });

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6" style={{ color: 'var(--accent)' }}>Infrastructure</h1>

      {/* Local Services */}
      <h2 className="text-sm font-medium mb-3 flex items-center gap-2" style={{ color: 'var(--text-muted)' }}>
        <HardDrive size={14} /> Local Services
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        <StatusCard
          title="Planning Server"
          value={plan.data ? 'RUNNING :8200' : 'DOWN'}
          status={plan.data ? 'ok' : 'error'}
          icon={Activity}
        />
        <StatusCard
          title="Simulation Server"
          value={sim.data ? 'RUNNING :8300' : 'DOWN'}
          status={sim.data ? 'ok' : 'error'}
          icon={Zap}
        />
        <StatusCard
          title="Local GPU"
          value="RTX 3060 8GB"
          status="ok"
          icon={Zap}
          subtitle="Driver 566.14 | CUDA available"
        />
      </div>

      {/* GCP Cloud */}
      <h2 className="text-sm font-medium mb-3 flex items-center gap-2" style={{ color: 'var(--text-muted)' }}>
        <Cloud size={14} /> GCP Cloud (osteotwin-37f03c)
      </h2>

      {/* Pub/Sub */}
      <div className="rounded-lg border p-4 mb-4" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
        <div className="flex items-center gap-2 mb-3">
          <MessageSquare size={16} style={{ color: 'var(--accent)' }} />
          <h3 className="text-sm font-medium">Pub/Sub Queue</h3>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <div style={{ color: 'var(--text-muted)' }}>Topic</div>
            <div className="font-mono text-xs">{pubsub.data?.topic}</div>
          </div>
          <div>
            <div style={{ color: 'var(--text-muted)' }}>Subscription</div>
            <div className="font-mono text-xs">{pubsub.data?.subscription}</div>
          </div>
          <div>
            <div style={{ color: 'var(--text-muted)' }}>Pending Messages</div>
            <div className="text-lg font-bold" style={{ color: pubsub.data?.pendingMessages ? 'var(--warning)' : 'var(--success)' }}>
              {pubsub.data?.pendingMessages ?? '—'}
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--text-muted)' }}>Oldest Unacked</div>
            <div>{pubsub.data?.oldestUnackedAge ?? '—'}</div>
          </div>
        </div>
      </div>

      {/* GCS Buckets */}
      <div className="rounded-lg border p-4 mb-4" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
        <div className="flex items-center gap-2 mb-3">
          <FolderArchive size={16} style={{ color: 'var(--accent)' }} />
          <h3 className="text-sm font-medium">Cloud Storage Buckets</h3>
        </div>
        <div className="space-y-2">
          {gcs.data?.buckets.map(b => (
            <div key={b.name} className="flex items-center justify-between text-sm py-1 border-b"
              style={{ borderColor: 'var(--border)' }}>
              <div>
                <span className="font-mono text-xs">{b.name}</span>
                <span className="ml-2" style={{ color: 'var(--text-muted)' }}>— {b.purpose}</span>
              </div>
              <span className="text-xs px-2 py-0.5 rounded" style={{ background: '#2a2a3a', color: 'var(--text-muted)' }}>
                {b.region}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Spot Workers */}
      <div className="rounded-lg border p-4" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
        <div className="flex items-center gap-2 mb-3">
          <Zap size={16} style={{ color: 'var(--warning)' }} />
          <h3 className="text-sm font-medium">Spot GPU Workers (MIG)</h3>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <div style={{ color: 'var(--text-muted)' }}>Target Size</div>
            <div className="text-lg font-bold">0</div>
          </div>
          <div>
            <div style={{ color: 'var(--text-muted)' }}>Running</div>
            <div className="text-lg font-bold" style={{ color: 'var(--success)' }}>0</div>
          </div>
          <div>
            <div style={{ color: 'var(--text-muted)' }}>Instance Type</div>
            <div className="font-mono text-xs">n1-standard-8</div>
          </div>
          <div>
            <div style={{ color: 'var(--text-muted)' }}>GPU Quota</div>
            <div>
              <span className="px-2 py-0.5 rounded-full text-xs font-semibold"
                style={{ background: '#e65100', color: '#ffcc02' }}>
                PENDING
              </span>
            </div>
          </div>
        </div>
        <p className="text-xs mt-3" style={{ color: 'var(--text-muted)' }}>
          GPU quota request pending (project &lt;48hrs old). Will retry after 2026-03-17.
          Estimated cost: ~$0.17/hr (T4 Spot).
        </p>
      </div>
    </div>
  );
}
