// PLY nokta-bulutu görüntüleyici (face4d kareleri, gaussian sample'ları).
// three/examples PLYLoader — yeni bağımlılık yok. >2M nokta altörneklenir (UI donmasın).
import { useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";
import { PLYLoader } from "three/examples/jsm/loaders/PLYLoader.js";
import { useT } from "../i18n";

const MAX_POINTS = 2_000_000;

function subsample(geo: THREE.BufferGeometry): THREE.BufferGeometry {
  const pos = geo.getAttribute("position");
  if (!pos || pos.count <= MAX_POINTS) return geo;
  const step = Math.ceil(pos.count / MAX_POINTS);
  const idx: number[] = [];
  for (let i = 0; i < pos.count; i += step) idx.push(i);
  const out = new THREE.BufferGeometry();
  for (const name of ["position", "color"] as const) {
    const attr = geo.getAttribute(name);
    if (!attr) continue;
    const arr = new Float32Array(idx.length * attr.itemSize);
    idx.forEach((src, dst) => {
      for (let c = 0; c < attr.itemSize; c++) arr[dst * attr.itemSize + c] = attr.getComponent(src, c);
    });
    out.setAttribute(name, new THREE.BufferAttribute(arr, attr.itemSize));
  }
  return out;
}

function Cloud({ url, pointSize }: { url: string; pointSize: number }) {
  const [geo, setGeo] = useState<THREE.BufferGeometry | null>(null);
  useEffect(() => {
    let live = true;
    new PLYLoader().load(url, (g) => {
      if (!live) { g.dispose(); return; }
      const s = subsample(g);
      if (s !== g) g.dispose();
      s.computeBoundingSphere();
      setGeo(s);
    });
    return () => { live = false; };
  }, [url]);
  const material = useMemo(() => new THREE.PointsMaterial({ size: pointSize, sizeAttenuation: true }), []);
  useEffect(() => {
    material.size = pointSize;
    material.vertexColors = !!geo?.getAttribute("color");
    material.color.set(geo?.getAttribute("color") ? "#ffffff" : "#a78bfa");
    material.needsUpdate = true;
  }, [material, pointSize, geo]);
  useEffect(() => () => { geo?.dispose(); material.dispose(); }, [geo, material]);
  if (!geo) return null;
  // Sahneyi bounding sphere merkezine oturt
  const c = geo.boundingSphere?.center ?? new THREE.Vector3();
  return <points geometry={geo} material={material} position={[-c.x, -c.y, -c.z]} />;
}

export default function PlyViewer({ url, onClose }: { url: string; onClose: () => void }) {
  const { t } = useT();
  const [size, setSize] = useState(0.01);
  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex flex-col p-4" data-testid="ply-viewer">
      <div className="flex items-center gap-4 mb-2 text-sm">
        <button onClick={onClose} className="bg-zinc-800 hover:bg-zinc-700 rounded px-3 py-1.5">{t("outputs.close")}</button>
        <label className="flex items-center gap-2 text-zinc-300">
          {t("outputs.pointSize")}
          <input type="range" min="0.001" max="0.05" step="0.001" value={size}
            onChange={(e) => setSize(Number(e.target.value))} />
        </label>
      </div>
      <div className="flex-1 rounded-xl overflow-hidden bg-zinc-950">
        <Canvas camera={{ position: [0, 0, 2.5], fov: 50 }} gl={{ preserveDrawingBuffer: true }}>
          <Cloud url={url} pointSize={size} />
          <OrbitControls makeDefault />
        </Canvas>
      </div>
    </div>
  );
}
