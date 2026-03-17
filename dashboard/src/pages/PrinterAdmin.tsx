import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Printer, Plus, Trash2, Save, Palette, Check } from 'lucide-react';
import { authFetch } from '../lib/api';

// --- Types matching backend PrinterConfig / FilamentMapping ---

interface FilamentMapping {
  color_code: string;
  extruder_id: number;
  material_type: string;
  material_label: string | null;
  color_hex: string | null;
  notes: string | null;
}

interface PrinterConfig {
  printer_id: string;
  printer_name: string;
  num_extruders: number;
  build_volume_mm: { x: number; y: number; z: number };
  filament_mappings: FilamentMapping[];
  is_default: boolean;
  notes: string | null;
}

const MATERIALS = [
  'PLA', 'PETG', 'ABS', 'PC', 'TPU', 'Nylon', 'ASA', 'PVA', 'HIPS',
  'Resin_Standard', 'Resin_Tough',
];

const SEMANTIC_COLORS = [
  { code: 'White', hex: '#F5F0E1', role: 'Main Bone' },
  { code: 'Blue', hex: '#4A90D9', role: 'Fragment A' },
  { code: 'Green', hex: '#4CAF50', role: 'Fragment B' },
  { code: 'Red', hex: '#E53935', role: 'K-Wire Trajectory / Danger Zone' },
  { code: 'Yellow', hex: '#FDD835', role: 'Fragment C' },
  { code: 'Orange', hex: '#FF9800', role: 'Fragment D' },
  { code: 'Steel Blue', hex: '#5086C8', role: 'Hardware (Plates/Screws)' },
];

// Blank new printer
function emptyPrinter(): PrinterConfig {
  return {
    printer_id: '',
    printer_name: '',
    num_extruders: 2,
    build_volume_mm: { x: 250, y: 210, z: 210 },
    filament_mappings: [],
    is_default: false,
    notes: null,
  };
}

export function PrinterAdmin() {
  const qc = useQueryClient();
  const [editing, setEditing] = useState<PrinterConfig | null>(null);
  const [saved, setSaved] = useState(false);

  const { data: printers = [], isLoading } = useQuery<PrinterConfig[]>({
    queryKey: ['printers'],
    queryFn: async () => {
      const resp = await authFetch('/api/v1/admin/printer');
      return resp.json();
    },
  });

  const saveMutation = useMutation({
    mutationFn: async (config: PrinterConfig) => {
      const resp = await authFetch('/api/v1/admin/printer', {
        method: 'POST',
        body: JSON.stringify(config),
      });
      if (!resp.ok) throw new Error('Save failed');
      return resp.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['printers'] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      const resp = await authFetch(`/api/v1/admin/printer/${id}`, { method: 'DELETE' });
      if (!resp.ok) throw new Error('Delete failed');
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['printers'] });
      setEditing(null);
    },
  });

  // Auto-generate printer_id from name
  function handleNameChange(name: string) {
    if (!editing) return;
    const id = editing.printer_id || name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    setEditing({ ...editing, printer_name: name, printer_id: editing.printer_id ? editing.printer_id : id });
  }

  function addMapping() {
    if (!editing) return;
    const next: FilamentMapping = {
      color_code: SEMANTIC_COLORS[editing.filament_mappings.length % SEMANTIC_COLORS.length].code,
      extruder_id: editing.filament_mappings.length % editing.num_extruders,
      material_type: 'PLA',
      material_label: null,
      color_hex: null,
      notes: null,
    };
    setEditing({ ...editing, filament_mappings: [...editing.filament_mappings, next] });
  }

  function updateMapping(idx: number, patch: Partial<FilamentMapping>) {
    if (!editing) return;
    const mappings = [...editing.filament_mappings];
    mappings[idx] = { ...mappings[idx], ...patch };
    setEditing({ ...editing, filament_mappings: mappings });
  }

  function removeMapping(idx: number) {
    if (!editing) return;
    const mappings = editing.filament_mappings.filter((_, i) => i !== idx);
    setEditing({ ...editing, filament_mappings: mappings });
  }

  const inputStyle = {
    background: '#1a1a2e',
    borderColor: 'var(--border)',
    color: 'var(--text-primary)',
  };

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6" style={{ color: 'var(--accent)' }}>
        Printer Configuration
      </h1>

      {/* Printer list */}
      <div className="rounded-lg border p-6 mb-4" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Printer size={16} style={{ color: 'var(--accent)' }} />
            <h2 className="text-sm font-medium">Printer Profiles</h2>
          </div>
          <button
            onClick={() => setEditing(emptyPrinter())}
            className="flex items-center gap-1 px-3 py-1.5 rounded text-xs font-medium"
            style={{ background: '#1a73e8', color: 'white' }}
          >
            <Plus size={14} /> Add Printer
          </button>
        </div>

        {isLoading && <p className="text-sm" style={{ color: 'var(--text-muted)' }}>Loading...</p>}

        {printers.length === 0 && !isLoading && (
          <p className="text-sm" style={{ color: 'var(--text-muted)' }}>
            No printers configured. Click "Add Printer" to get started.
          </p>
        )}

        <div className="space-y-2">
          {printers.map(p => (
            <div
              key={p.printer_id}
              className="flex items-center justify-between p-3 rounded border cursor-pointer hover:bg-white/5 transition-colors"
              style={{ borderColor: 'var(--border)' }}
              onClick={() => setEditing({ ...p })}
            >
              <div>
                <span className="text-sm font-medium">{p.printer_name}</span>
                {p.is_default && (
                  <span className="ml-2 px-2 py-0.5 rounded text-[10px] font-medium"
                    style={{ background: '#1a73e8', color: 'white' }}>
                    DEFAULT
                  </span>
                )}
                <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                  {p.num_extruders} extruders &middot; {p.filament_mappings.length} color mappings &middot;
                  {p.build_volume_mm.x}&times;{p.build_volume_mm.y}&times;{p.build_volume_mm.z}mm
                </p>
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); deleteMutation.mutate(p.printer_id); }}
                className="p-1.5 rounded hover:bg-red-500/20 transition-colors"
                style={{ color: 'var(--text-muted)' }}
                title="Delete"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Editor */}
      {editing && (
        <div className="rounded-lg border p-6" style={{ background: 'var(--bg-card)', borderColor: 'var(--border)' }}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-medium">
              {editing.printer_id ? `Edit: ${editing.printer_name}` : 'New Printer Profile'}
            </h2>
            <div className="flex items-center gap-2">
              {saved && (
                <span className="flex items-center gap-1 text-xs text-green-400">
                  <Check size={12} /> Saved
                </span>
              )}
              <button
                onClick={() => saveMutation.mutate(editing)}
                className="flex items-center gap-1 px-3 py-1.5 rounded text-xs font-medium"
                style={{ background: '#1a73e8', color: 'white' }}
                disabled={saveMutation.isPending}
              >
                <Save size={14} /> {saveMutation.isPending ? 'Saving...' : 'Save'}
              </button>
              <button
                onClick={() => setEditing(null)}
                className="px-3 py-1.5 rounded text-xs border"
                style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}
              >
                Cancel
              </button>
            </div>
          </div>

          {/* Basic info */}
          <div className="grid grid-cols-2 gap-4 mb-6">
            <div>
              <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>Printer Name</label>
              <input
                value={editing.printer_name}
                onChange={e => handleNameChange(e.target.value)}
                placeholder="e.g. Prusa XL 5-Toolhead"
                className="w-full px-3 py-2 rounded border text-sm"
                style={inputStyle}
              />
            </div>
            <div>
              <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>Number of Extruders</label>
              <input
                type="number" min={1} max={16}
                value={editing.num_extruders}
                onChange={e => setEditing({ ...editing, num_extruders: parseInt(e.target.value) || 1 })}
                className="w-full px-3 py-2 rounded border text-sm"
                style={inputStyle}
              />
            </div>
            <div>
              <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>
                Build Volume (mm) — W &times; D &times; H
              </label>
              <div className="flex gap-2">
                {(['x', 'y', 'z'] as const).map(axis => (
                  <input
                    key={axis}
                    type="number" min={1}
                    value={editing.build_volume_mm[axis]}
                    onChange={e => setEditing({
                      ...editing,
                      build_volume_mm: { ...editing.build_volume_mm, [axis]: parseInt(e.target.value) || 0 },
                    })}
                    className="flex-1 px-3 py-2 rounded border text-sm"
                    style={inputStyle}
                    placeholder={axis.toUpperCase()}
                  />
                ))}
              </div>
            </div>
            <div className="flex items-end">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={editing.is_default}
                  onChange={e => setEditing({ ...editing, is_default: e.target.checked })}
                  className="rounded"
                />
                <span style={{ color: 'var(--text-muted)' }}>Set as default printer</span>
              </label>
            </div>
          </div>

          {/* Filament mappings */}
          <div className="mb-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2">
                <Palette size={14} style={{ color: 'var(--accent)' }} />
                <h3 className="text-xs font-medium" style={{ color: 'var(--text-muted)' }}>
                  Color → Extruder Mapping
                </h3>
              </div>
              <button
                onClick={addMapping}
                className="flex items-center gap-1 px-2 py-1 rounded text-xs border hover:bg-white/5 transition-colors"
                style={{ borderColor: 'var(--border)', color: 'var(--text-muted)' }}
              >
                <Plus size={12} /> Add Mapping
              </button>
            </div>

            {/* Header */}
            {editing.filament_mappings.length > 0 && (
              <div className="grid grid-cols-[1fr_80px_120px_1fr_40px] gap-2 mb-2 px-2 text-[10px] uppercase tracking-wider"
                style={{ color: 'var(--text-muted)' }}>
                <span>Semantic Color</span>
                <span>Extruder</span>
                <span>Material</span>
                <span>Label / Notes</span>
                <span></span>
              </div>
            )}

            {editing.filament_mappings.map((m, idx) => {
              const sc = SEMANTIC_COLORS.find(c => c.code === m.color_code);
              return (
                <div key={idx}
                  className="grid grid-cols-[1fr_80px_120px_1fr_40px] gap-2 items-center mb-2 p-2 rounded border"
                  style={{ borderColor: 'var(--border)' }}>

                  {/* Color selector */}
                  <div className="flex items-center gap-2">
                    <div className="w-4 h-4 rounded-full border"
                      style={{ background: sc?.hex || '#888', borderColor: 'var(--border)' }} />
                    <select
                      value={m.color_code}
                      onChange={e => updateMapping(idx, { color_code: e.target.value })}
                      className="flex-1 px-2 py-1.5 rounded border text-xs"
                      style={inputStyle}
                    >
                      {SEMANTIC_COLORS.map(c => (
                        <option key={c.code} value={c.code}>{c.code} — {c.role}</option>
                      ))}
                    </select>
                  </div>

                  {/* Extruder number */}
                  <select
                    value={m.extruder_id}
                    onChange={e => updateMapping(idx, { extruder_id: parseInt(e.target.value) })}
                    className="px-2 py-1.5 rounded border text-xs"
                    style={inputStyle}
                  >
                    {Array.from({ length: editing.num_extruders }, (_, i) => (
                      <option key={i} value={i}>T{i + 1}</option>
                    ))}
                  </select>

                  {/* Material */}
                  <select
                    value={m.material_type}
                    onChange={e => updateMapping(idx, { material_type: e.target.value })}
                    className="px-2 py-1.5 rounded border text-xs"
                    style={inputStyle}
                  >
                    {MATERIALS.map(mat => (
                      <option key={mat} value={mat}>{mat}</option>
                    ))}
                  </select>

                  {/* Label */}
                  <input
                    value={m.material_label || ''}
                    onChange={e => updateMapping(idx, { material_label: e.target.value || null })}
                    placeholder="e.g. Bone-Simulating PC"
                    className="px-2 py-1.5 rounded border text-xs"
                    style={inputStyle}
                  />

                  {/* Delete */}
                  <button
                    onClick={() => removeMapping(idx)}
                    className="p-1 rounded hover:bg-red-500/20 transition-colors"
                    style={{ color: 'var(--text-muted)' }}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              );
            })}

            {editing.filament_mappings.length === 0 && (
              <p className="text-xs px-2 py-4 text-center" style={{ color: 'var(--text-muted)' }}>
                No mappings yet. Add mappings to assign semantic colors to physical extruders.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
