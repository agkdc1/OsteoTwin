import { useState, useEffect, Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Grid, Environment } from '@react-three/drei';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import * as THREE from 'three';
import { Box, RotateCcw, Download, Layers } from 'lucide-react';
import { listMeshes, listExports, downloadStl } from '../lib/api';

function StlMesh({ url, color = '#e8e8e8' }: { url: string; color?: string }) {
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);

  useEffect(() => {
    const loader = new STLLoader();
    loader.load(url, (geo) => {
      geo.computeVertexNormals();
      geo.center();
      // Scale to reasonable size
      const box = new THREE.Box3().setFromBufferAttribute(geo.getAttribute('position') as THREE.BufferAttribute);
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

function Scene({ stlUrl }: { stlUrl: string | null }) {
  return (
    <>
      <ambientLight intensity={0.4} />
      <directionalLight position={[5, 5, 5]} intensity={0.8} />
      <directionalLight position={[-5, -3, 2]} intensity={0.3} />

      {stlUrl && (
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
      <OrbitControls makeDefault />
      <Environment preset="studio" />
    </>
  );
}

export function Viewer() {
  const [meshes, setMeshes] = useState<{ mesh_id: string; label: string }[]>([]);
  const [exports, setExports] = useState<{ filename: string; case_id: string }[]>([]);
  const [caseId] = useState('synth_wrist_001');
  const [selectedStl, setSelectedStl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    listMeshes().then(d => setMeshes(d.meshes || [])).catch(() => {});
    listExports(caseId).then(d => setExports(d.exports || [])).catch(() => {});
  }, [caseId]);

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
          <button
            onClick={() => setSelectedStl(null)}
            className="flex items-center gap-1 px-3 py-1.5 rounded text-sm"
            style={{ background: 'var(--bg-card)', border: '1px solid var(--border)' }}
          >
            <RotateCcw size={14} /> Reset
          </button>
        </div>
      </div>

      {/* 3D Canvas */}
      <div className="flex-1 rounded-lg overflow-hidden" style={{ background: '#1a1a2e', minHeight: '400px' }}>
        <Canvas camera={{ position: [8, 6, 8], fov: 50 }}>
          <Scene stlUrl={selectedStl} />
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
