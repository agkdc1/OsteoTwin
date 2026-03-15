import { useQuery } from '@tanstack/react-query';
import { Activity, Cpu, Database, Zap, HardDrive, Brain } from 'lucide-react';
import { StatusCard } from '../components/StatusCard';
import { planHealth, simHealth, kgStatus } from '../lib/api';

export function Overview() {
  const plan = useQuery({ queryKey: ['planHealth'], queryFn: planHealth });
  const sim = useQuery({ queryKey: ['simHealth'], queryFn: simHealth });
  const kg = useQuery({ queryKey: ['kgStatus'], queryFn: kgStatus });

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6" style={{ color: 'var(--accent)' }}>
        Overview
      </h1>

      {/* Service Status */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <StatusCard
          title="Planning Server :8200"
          value={plan.data ? 'RUNNING' : 'DOWN'}
          status={plan.data ? 'ok' : 'error'}
          icon={Brain}
          subtitle="Auth, LLM Orchestrator, Debate"
        />
        <StatusCard
          title="Simulation Server :8300"
          value={sim.data ? 'RUNNING' : 'DOWN'}
          status={sim.data ? 'ok' : 'error'}
          icon={Cpu}
          subtitle="Collision, DICOM, Mesh Processing"
        />
        <StatusCard
          title="Knowledge Graph (Neo4j)"
          value={kg.data?.connected ? 'CONNECTED' : 'DISABLED'}
          status={kg.data?.connected ? 'ok' : 'warn'}
          icon={Database}
          subtitle={kg.data?.connected ? 'Anatomical Rule Engine active' : 'Set NEO4J_PASSWORD to enable'}
        />
      </div>

      {/* Hardware */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">
        <StatusCard
          title="Local GPU"
          value="RTX 3060 8GB"
          status="ok"
          icon={Zap}
          subtitle="Rigid body collision + TotalSegmentator inference"
        />
        <StatusCard
          title="System RAM"
          value="16 GB DDR4"
          status="neutral"
          icon={HardDrive}
          subtitle="Phase 1-2 sufficient, Phase 3+ needs upgrade"
        />
        <StatusCard
          title="GCP Spot Workers"
          value="DORMANT (size=0)"
          status="neutral"
          icon={Activity}
          subtitle="T4 GPU template ready, pending quota approval"
        />
      </div>

      {/* Quick Stats */}
      <div className="rounded-lg border p-6" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
        <h2 className="text-sm font-medium mb-4" style={{ color: 'var(--text-muted)' }}>Phase Status</h2>
        <div className="space-y-2 text-sm">
          {[
            { phase: 'Phase 0: Scaffolding', done: true },
            { phase: 'Phase 1: Rigid Body + Auth + LLM + UI', done: true },
            { phase: 'Phase 2: Segmentation + Implants + DICOM Pipeline', done: true },
            { phase: 'Cloud Infra: Pub/Sub + Checkpoint + Spot VM', done: true },
            { phase: 'Phase 3: STL 3D Print Export', done: true },
            { phase: 'Phase 4: E2E Integration (8/8 tests pass)', done: true },
            { phase: 'Phase 5: SOFA Soft-Tissue (GPU quota pending)', done: false },
          ].map(({ phase, done }) => (
            <div key={phase} className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full ${done ? 'bg-green-500' : 'bg-yellow-500'}`} />
              <span style={{ color: done ? 'var(--text-primary)' : 'var(--text-muted)' }}>{phase}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
