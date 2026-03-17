import { useState, useEffect, useRef, useCallback, Suspense } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls, TransformControls, Grid, Environment } from '@react-three/drei';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import * as THREE from 'three';
import { Box, RotateCcw, Download, Layers, Move, RotateCw } from 'lucide-react';
import { listMeshes, listExports, downloadStl, authFetch } from '../lib/api';
import {
  computeTranslationDelta,
  computeRotationDelta,
  buildDragAction,
  type FragmentRef,
  type ThreePosition,
  type ThreeEuler,
} from '../lib/coordinateMapper';

// --- Types ---

interface FragmentMeshData {
  fragment_id: string;
  color_code: string;
  color_hex: string;
  volume_mm3: number;
  url: string;
}

// --- Fragment mesh component with selection support ---

function FragmentMesh({
  data,
  isSelected,
  onSelect,
  meshRef,
}: {
  data: FragmentMeshData;
  isSelected: boolean;
  onSelect: () => void;
  meshRef: React.RefObject<THREE.Mesh | null>;
}) {
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);

  useEffect(() => {
    const loader = new STLLoader();
    loader.load(data.url, (geo) => {
      geo.computeVertexNormals();
      geo.center();
      const box = new THREE.Box3().setFromBufferAttribute(
        geo.getAttribute('position') as THREE.BufferAttribute,
      );
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z);
      if (maxDim > 0) {
        const scale = 5 / maxDim;
        geo.scale(scale, scale, scale);
      }
      setGeometry(geo);
    });
  }, [data.url]);

  if (!geometry) return null;

  return (
    <mesh
      ref={meshRef}
      geometry={geometry}
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
      }}
    >
      <meshStandardMaterial
        color={data.color_hex}
        roughness={0.4}
        metalness={0.1}
        emissive={isSelected ? data.color_hex : '#000000'}
        emissiveIntensity={isSelected ? 0.15 : 0}
      />
    </mesh>
  );
}

// --- Single STL fallback (no manipulation) ---

function StlMesh({ url, color = '#e8e8e8' }: { url: string; color?: string }) {
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);

  useEffect(() => {
    const loader = new STLLoader();
    loader.load(url, (geo) => {
      geo.computeVertexNormals();
      geo.center();
      const box = new THREE.Box3().setFromBufferAttribute(
        geo.getAttribute('position') as THREE.BufferAttribute,
      );
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z);
      if (maxDim > 0) {
        const scale = 5 / maxDim;
        geo.scale(scale, scale, scale);
      }
      setGeometry(geo);
    });
  }, [url]);

  if (!geometry) return null;

  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial color={color} roughness={0.4} metalness={0.1} />
    </mesh>
  );
}

// --- Transform gizmo that wraps selected fragment ---

function FragmentTransformGizmo({
  meshRef,
  mode,
  orbitRef,
  onDragEnd,
}: {
  meshRef: React.RefObject<THREE.Mesh | null>;
  mode: 'translate' | 'rotate';
  orbitRef: React.RefObject<any>;
  onDragEnd: (pos: ThreePosition, euler: ThreeEuler) => void;
}) {
  const transformRef = useRef<any>(null);

  useEffect(() => {
    const controls = transformRef.current;
    if (!controls) return;

    const onDragStart = () => {
      if (orbitRef.current) orbitRef.current.enabled = false;
    };
    const onDragEndEvt = () => {
      if (orbitRef.current) orbitRef.current.enabled = true;
      const obj = controls.object;
      if (obj) {
        onDragEnd(
          { x: obj.position.x, y: obj.position.y, z: obj.position.z },
          { x: obj.rotation.x, y: obj.rotation.y, z: obj.rotation.z, order: obj.rotation.order },
        );
      }
    };

    controls.addEventListener('dragging-changed', (event: { value: boolean }) => {
      if (event.value) onDragStart();
      else onDragEndEvt();
    });

    return () => {
      controls.removeEventListener('dragging-changed', onDragStart);
      controls.removeEventListener('dragging-changed', onDragEndEvt);
    };
  }, [onDragEnd, orbitRef]);

  if (!meshRef.current) return null;

  return (
    <TransformControls
      ref={transformRef}
      object={meshRef.current}
      mode={mode}
      size={0.6}
    />
  );
}

// --- Main 3D Scene ---

function Scene({
  stlUrl,
  fragments,
  selectedId,
  onSelect,
  transformMode,
  onDragEnd,
}: {
  stlUrl: string | null;
  fragments: FragmentMeshData[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  transformMode: 'translate' | 'rotate';
  onDragEnd: (fragmentId: string, pos: ThreePosition, euler: ThreeEuler) => void;
}) {
  const orbitRef = useRef<any>(null);
  const meshRefs = useRef<Record<string, React.RefObject<THREE.Mesh | null>>>({});

  // Ensure refs exist for all fragments
  for (const f of fragments) {
    if (!meshRefs.current[f.fragment_id]) {
      meshRefs.current[f.fragment_id] = { current: null };
    }
  }

  const selectedMeshRef = selectedId ? meshRefs.current[selectedId] : null;

  const handleDragEnd = useCallback(
    (pos: ThreePosition, euler: ThreeEuler) => {
      if (selectedId) onDragEnd(selectedId, pos, euler);
    },
    [selectedId, onDragEnd],
  );

  return (
    <>
      <ambientLight intensity={0.4} />
      <directionalLight position={[5, 5, 5]} intensity={0.8} />
      <directionalLight position={[-5, -3, 2]} intensity={0.3} />

      {/* Fragment meshes with manipulation */}
      {fragments.map((f) => (
        <Suspense key={f.fragment_id} fallback={null}>
          <FragmentMesh
            data={f}
            isSelected={f.fragment_id === selectedId}
            onSelect={() => onSelect(f.fragment_id)}
            meshRef={meshRefs.current[f.fragment_id]}
          />
        </Suspense>
      ))}

      {/* Transform gizmo on selected fragment */}
      {selectedMeshRef && selectedMeshRef.current && (
        <FragmentTransformGizmo
          meshRef={selectedMeshRef}
          mode={transformMode}
          orbitRef={orbitRef}
          onDragEnd={handleDragEnd}
        />
      )}

      {/* Fallback single STL view */}
      {stlUrl && fragments.length === 0 && (
        <Suspense fallback={null}>
          <StlMesh url={stlUrl} color="#d4c4a8" />
        </Suspense>
      )}

      <Grid
        position={[0, -3, 0]}
        args={[20, 20]}
        cellSize={1}
        cellColor="#333"
        sectionSize={5}
        sectionColor="#555"
        fadeDistance={30}
      />
      <OrbitControls ref={orbitRef} makeDefault />
      <Environment preset="studio" />
    </>
  );
}

// --- Main Viewer Page ---

export function Viewer() {
  const [meshes, setMeshes] = useState<{ mesh_id: string; label: string }[]>([]);
  const [exports, setExports] = useState<{ filename: string; case_id: string }[]>([]);
  const [fragments, setFragments] = useState<FragmentMeshData[]>([]);
  const [caseId] = useState('synth_wrist_001');
  const [selectedStl, setSelectedStl] = useState<string | null>(null);
  const [selectedFragment, setSelectedFragment] = useState<string | null>(null);
  const [transformMode, setTransformMode] = useState<'translate' | 'rotate'>('translate');
  const [loading, setLoading] = useState(false);
  const [lastAction, setLastAction] = useState<string | null>(null);

  // Track pre-drag state per fragment
  const preDragState = useRef<Record<string, { pos: ThreePosition; euler: ThreeEuler }>>({});

  useEffect(() => {
    listMeshes().then(d => setMeshes(d.meshes || [])).catch(() => {});
    listExports(caseId).then(d => setExports(d.exports || [])).catch(() => {});
  }, [caseId]);

  // Store pre-drag state when a fragment is selected
  const handleSelect = useCallback((id: string | null) => {
    setSelectedFragment(id);
  }, []);

  // Handle drag completion — compute delta, build SurgicalAction, POST to backend
  const handleDragEnd = useCallback(
    async (fragmentId: string, pos: ThreePosition, euler: ThreeEuler) => {
      const prev = preDragState.current[fragmentId] || { pos: { x: 0, y: 0, z: 0 }, euler: { x: 0, y: 0, z: 0, order: 'XYZ' } };

      const transDelta = computeTranslationDelta(prev.pos, pos);
      const rotDelta = computeRotationDelta(prev.euler, euler);

      // Update stored state
      preDragState.current[fragmentId] = { pos, euler };

      // Find fragment metadata
      const frag = fragments.find(f => f.fragment_id === fragmentId);
      if (!frag) return;

      const fragRef: FragmentRef = {
        fragment_id: frag.fragment_id,
        color_code: frag.color_code,
        volume_mm3: frag.volume_mm3,
      };

      const action = buildDragAction(fragRef, transDelta, rotDelta, caseId);

      // Skip if no meaningful movement
      if (action.action_type === 'translate'
        && Math.abs(transDelta.x) < 0.01
        && Math.abs(transDelta.y) < 0.01
        && Math.abs(transDelta.z) < 0.01) {
        return;
      }

      setLastAction(action.clinical_intent);

      // POST to sync endpoint
      try {
        await authFetch('/api/v1/simulation/sync-ui-action', {
          method: 'POST',
          body: JSON.stringify(action),
        });
      } catch (err) {
        console.error('Failed to sync UI action:', err);
      }
    },
    [fragments, caseId],
  );

  const handleDownload = async (filename: string) => {
    try {
      setLoading(true);
      const blob = await downloadStl(caseId, filename);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert('Download failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-full flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold" style={{ color: 'var(--accent)' }}>
          <Box size={24} className="inline mr-2" />
          3D Viewer
        </h1>
        <div className="flex gap-2">
          {/* Transform mode toggle */}
          <button
            onClick={() => setTransformMode('translate')}
            className="flex items-center gap-1 px-3 py-1.5 rounded text-sm"
            style={{
              background: transformMode === 'translate' ? '#1a73e8' : 'var(--bg-card)',
              color: transformMode === 'translate' ? 'white' : 'var(--text-muted)',
              border: '1px solid var(--border)',
            }}
          >
            <Move size={14} /> Translate
          </button>
          <button
            onClick={() => setTransformMode('rotate')}
            className="flex items-center gap-1 px-3 py-1.5 rounded text-sm"
            style={{
              background: transformMode === 'rotate' ? '#1a73e8' : 'var(--bg-card)',
              color: transformMode === 'rotate' ? 'white' : 'var(--text-muted)',
              border: '1px solid var(--border)',
            }}
          >
            <RotateCw size={14} /> Rotate
          </button>
          <button
            onClick={() => {
              setSelectedStl(null);
              setSelectedFragment(null);
            }}
            className="flex items-center gap-1 px-3 py-1.5 rounded text-sm"
            style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}
          >
            <RotateCcw size={14} /> Reset
          </button>
        </div>
      </div>

      {/* Last action feedback */}
      {lastAction && (
        <div className="px-3 py-2 rounded text-xs" style={{ background: '#1a73e8/10', border: '1px solid #1a73e8', color: 'var(--accent)' }}>
          {lastAction}
        </div>
      )}

      {/* 3D Canvas */}
      <div className="flex-1 rounded-lg overflow-hidden" style={{ background: '#1a1a2e', minHeight: '400px' }}>
        <Canvas
          camera={{ position: [8, 6, 8], fov: 50 }}
          onPointerMissed={() => setSelectedFragment(null)}
        >
          <Scene
            stlUrl={selectedStl}
            fragments={fragments}
            selectedId={selectedFragment}
            onSelect={handleSelect}
            transformMode={transformMode}
            onDragEnd={handleDragEnd}
          />
        </Canvas>
      </div>

      {/* Mesh & Export List */}
      <div className="grid grid-cols-2 gap-4">
        {/* Loaded Meshes */}
        <div className="rounded-lg p-4" style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}>
          <h3 className="font-medium mb-2 flex items-center gap-2">
            <Layers size={16} style={{ color: 'var(--accent)' }} />
            Loaded Meshes
          </h3>
          {meshes.length === 0 ? (
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>No meshes loaded. Use the API to load meshes.</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {meshes.map(m => (
                <li key={m.mesh_id} className="flex items-center gap-2 p-1.5 rounded hover:bg-white/5">
                  <span className="w-2 h-2 rounded-full" style={{ background: 'var(--success)' }} />
                  <span className="font-mono">{m.mesh_id}</span>
                  <span style={{ color: 'var(--text-muted)' }}>{m.label}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* STL Exports */}
        <div className="rounded-lg p-4" style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}>
          <h3 className="font-medium mb-2 flex items-center gap-2">
            <Download size={16} style={{ color: 'var(--success)' }} />
            STL Exports
          </h3>
          {exports.length === 0 ? (
            <p className="text-sm" style={{ color: 'var(--text-muted)' }}>No exports yet. Generate via POST /api/v1/export/stl</p>
          ) : (
            <ul className="space-y-1 text-sm">
              {exports.map(e => (
                <li key={e.filename} className="flex items-center justify-between p-1.5 rounded hover:bg-white/5">
                  <span className="font-mono">{e.filename}</span>
                  <button
                    onClick={() => handleDownload(e.filename)}
                    disabled={loading}
                    className="px-2 py-0.5 rounded text-xs"
                    style={{ background: '#2e7d32', color: 'white' }}
                  >
                    Download
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
