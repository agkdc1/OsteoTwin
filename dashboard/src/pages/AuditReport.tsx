import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { ShieldAlert, ShieldCheck, AlertTriangle, Info, Send, RotateCcw } from 'lucide-react';
import { authFetch } from '../lib/api';

interface AuditFinding {
  finding_id: string;
  severity: 'critical' | 'warning' | 'info' | 'approved';
  category: string;
  plan_ref: string;
  description: string;
  textbook_reference: string | null;
  interrogation: string | null;
  resolved: boolean;
  surgeon_resolution: string | null;
}

interface AuditReportData {
  report_id: string;
  case_id: string;
  audit_round: number;
  findings: AuditFinding[];
  has_critical: boolean;
  is_approved: boolean;
  verdict_summary: string;
}

const SEVERITY_CONFIG = {
  critical: { icon: ShieldAlert, color: '#ef4444', bg: '#ef4444/10', label: 'CRITICAL' },
  warning: { icon: AlertTriangle, color: '#f59e0b', bg: '#f59e0b/10', label: 'WARNING' },
  info: { icon: Info, color: '#3b82f6', bg: '#3b82f6/10', label: 'INFO' },
  approved: { icon: ShieldCheck, color: '#22c55e', bg: '#22c55e/10', label: 'APPROVED' },
};

export function AuditReport() {
  const [caseId, setCaseId] = useState('');
  const [discussion, setDiscussion] = useState('');
  const [plans, setPlans] = useState('[\n  {"plan_id": "Plan A", "approach": "", "reduction_steps": []}\n]');
  const [report, setReport] = useState<AuditReportData | null>(null);
  const [resolutions, setResolutions] = useState<Record<string, string>>({});
  const [round, setRound] = useState(0);

  const runAudit = useMutation({
    mutationFn: async () => {
      const resp = await authFetch('/api/v1/audit/full', {
        method: 'POST',
        body: JSON.stringify({
          case_id: caseId || 'audit-' + Date.now(),
          discussion_log: discussion,
          draft_plans: JSON.parse(plans),
        }),
      });
      if (!resp.ok) throw new Error('Audit failed');
      return resp.json();
    },
    onSuccess: (data) => {
      setReport(data.report);
      setRound(data.report.audit_round);
      setCaseId(data.report.case_id);
    },
  });

  const submitResolutions = useMutation({
    mutationFn: async () => {
      // Submit resolutions
      const resList = Object.entries(resolutions)
        .filter(([_, v]) => v.trim())
        .map(([fid, res]) => ({ finding_id: fid, resolution: res }));

      await authFetch('/api/v1/audit/resolve', {
        method: 'POST',
        body: JSON.stringify({ case_id: caseId, resolutions: resList }),
      });

      // Re-run audit
      const resp = await authFetch('/api/v1/audit/run', {
        method: 'POST',
        body: JSON.stringify({ case_id: caseId }),
      });
      if (!resp.ok) throw new Error('Re-audit failed');
      return resp.json();
    },
    onSuccess: (data) => {
      setReport(data.report);
      setRound(data.round);
      setResolutions({});
    },
  });

  const inputStyle = {
    background: '#1a1a2e',
    borderColor: 'var(--border)',
    color: 'var(--text-primary)',
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6" style={{ color: 'var(--accent)' }}>
        Grand Surgical Audit
      </h1>

      {/* Input section */}
      {!report && (
        <div className="space-y-4 mb-6">
          <div className="rounded-lg border p-4" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
            <h2 className="text-sm font-medium mb-3">Case Input</h2>
            <div className="space-y-3">
              <div>
                <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>Case ID</label>
                <input value={caseId} onChange={e => setCaseId(e.target.value)}
                  placeholder="e.g., DR-2026-001" className="w-full px-3 py-2 rounded border text-sm" style={inputStyle} />
              </div>
              <div>
                <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>Pre-Op Discussion Log</label>
                <textarea value={discussion} onChange={e => setDiscussion(e.target.value)}
                  rows={6} placeholder="Paste the full pre-operative discussion..."
                  className="w-full px-3 py-2 rounded border text-sm font-mono" style={inputStyle} />
              </div>
              <div>
                <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>Draft Plans (JSON)</label>
                <textarea value={plans} onChange={e => setPlans(e.target.value)}
                  rows={4} className="w-full px-3 py-2 rounded border text-sm font-mono" style={inputStyle} />
              </div>
              <button onClick={() => runAudit.mutate()}
                disabled={runAudit.isPending}
                className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium"
                style={{ background: '#1a73e8', color: 'white' }}>
                <ShieldAlert size={14} />
                {runAudit.isPending ? 'Running Audit...' : 'Run Grand Surgical Audit'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Audit Report */}
      {report && (
        <div className="space-y-4">
          {/* Verdict banner */}
          <div className="rounded-lg border p-4" style={{
            background: report.is_approved ? '#22c55e10' : report.has_critical ? '#ef444410' : '#f59e0b10',
            borderColor: report.is_approved ? '#22c55e' : report.has_critical ? '#ef4444' : '#f59e0b',
          }}>
            <div className="flex items-center gap-2 mb-1">
              {report.is_approved
                ? <ShieldCheck size={20} style={{ color: '#22c55e' }} />
                : <ShieldAlert size={20} style={{ color: report.has_critical ? '#ef4444' : '#f59e0b' }} />}
              <span className="font-bold text-sm">
                {report.is_approved ? 'AUDIT PASSED' : `AUDIT ROUND ${round}`}
              </span>
            </div>
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>{report.verdict_summary}</p>
          </div>

          {/* Findings */}
          <div className="space-y-3">
            {report.findings.map(f => {
              const cfg = SEVERITY_CONFIG[f.severity];
              const Icon = cfg.icon;
              return (
                <div key={f.finding_id} className="rounded-lg border p-4" style={{
                  background: 'var(--bg-card)', borderColor: f.resolved ? '#22c55e40' : 'var(--border)',
                }}>
                  <div className="flex items-start gap-3">
                    <Icon size={18} style={{ color: cfg.color, flexShrink: 0, marginTop: 2 }} />
                    <div className="flex-1">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                          style={{ background: cfg.color, color: 'white' }}>
                          {cfg.label}
                        </span>
                        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                          {f.plan_ref} / {f.category}
                        </span>
                        {f.resolved && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded"
                            style={{ background: '#22c55e', color: 'white' }}>
                            RESOLVED
                          </span>
                        )}
                      </div>

                      <p className="text-sm mb-2">{f.description}</p>

                      {f.textbook_reference && (
                        <p className="text-xs mb-2 italic" style={{ color: 'var(--text-muted)' }}>
                          Ref: {f.textbook_reference}
                        </p>
                      )}

                      {/* Interrogation + Resolution input */}
                      {f.interrogation && !f.resolved && (
                        <div className="mt-2 p-3 rounded" style={{ background: '#1a1a2e' }}>
                          <p className="text-xs font-medium mb-2" style={{ color: cfg.color }}>
                            {f.interrogation}
                          </p>
                          <textarea
                            value={resolutions[f.finding_id] || ''}
                            onChange={e => setResolutions(prev => ({ ...prev, [f.finding_id]: e.target.value }))}
                            rows={2}
                            placeholder="Enter your clinical resolution..."
                            className="w-full px-2 py-1.5 rounded border text-xs"
                            style={inputStyle}
                          />
                        </div>
                      )}

                      {f.resolved && f.surgeon_resolution && (
                        <div className="mt-2 p-2 rounded text-xs" style={{ background: '#22c55e10' }}>
                          <span className="font-medium">Resolution: </span>{f.surgeon_resolution}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Action buttons */}
          <div className="flex gap-2">
            {!report.is_approved && report.has_critical && (
              <button onClick={() => submitResolutions.mutate()}
                disabled={submitResolutions.isPending || Object.values(resolutions).every(v => !v.trim())}
                className="flex items-center gap-2 px-4 py-2 rounded text-sm font-medium"
                style={{ background: '#1a73e8', color: 'white' }}>
                <Send size={14} />
                {submitResolutions.isPending ? 'Re-auditing...' : 'Submit Resolutions & Re-Audit'}
              </button>
            )}
            <button onClick={() => { setReport(null); setResolutions({}); setRound(0); }}
              className="flex items-center gap-1 px-3 py-2 rounded text-sm border"
              style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}>
              <RotateCcw size={14} /> New Audit
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
