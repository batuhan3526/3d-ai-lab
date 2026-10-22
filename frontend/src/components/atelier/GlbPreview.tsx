import { Component, Suspense, useMemo, type ReactNode } from "react";
import * as THREE from "three";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, useGLTF } from "@react-three/drei";
import { useT } from "../../i18n";

// Bağımsız GLB önizleyici (Atölye manken adımı). Tasarımcı store'una (useDesign)
// bağlı Mannequin.tsx'ten farklı olarak tek başına çalışır: modeli klonlar,
// ayak tabanı y=0 ve 1.7 birim boya oturtur, ışık + yörünge kontrolü verir.
// Ortam HDR'ı (drei Environment) kullanılmaz → internetsiz LAN'da da çalışır.

const TARGET_H = 1.7;

class PreviewBoundary extends Component<{ children: ReactNode; fallback: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

function Model({ url }: { url: string }) {
  const { scene } = useGLTF(url);
  const { obj, scale, pos } = useMemo(() => {
    const root = scene.clone(true);
    const box = new THREE.Box3().setFromObject(root);
    const size = new THREE.Vector3(); box.getSize(size);
    const c = new THREE.Vector3(); box.getCenter(c);
    const s = TARGET_H / Math.max(size.y, 1e-6);
    return { obj: root, scale: s, pos: [-c.x * s, -box.min.y * s, -c.z * s] as [number, number, number] };
  }, [scene]);
  return (
    <group position={pos} scale={scale}>
      <primitive object={obj} />
    </group>
  );
}

export function GlbPreview({ url, heightClass = "h-[50vh] min-h-[320px]" }: { url: string; heightClass?: string }) {
  const { t } = useT();
  const fail = (
    <div className={`${heightClass} flex items-center justify-center rounded-xl bg-zinc-950 text-sm text-red-300 p-6 text-center`}>
      {t("atelier.preview.glbError")}
    </div>
  );
  return (
    <PreviewBoundary key={url} fallback={fail}>
      <div className={`${heightClass} rounded-xl overflow-hidden bg-gradient-to-b from-zinc-800 to-zinc-950`}>
        <Canvas camera={{ position: [0, 1.1, 3.2], fov: 40 }} dpr={[1, 2]}>
          <hemisphereLight args={["#ffffff", "#444444", 1.6]} />
          <ambientLight intensity={0.9} />
          <directionalLight position={[2, 4, 3]} intensity={2.2} />
          <directionalLight position={[0, 2, 4]} intensity={1.0} />
          <directionalLight position={[-3, 2, -2]} intensity={0.5} />
          <Suspense fallback={null}>
            <Model url={url} />
          </Suspense>
          <gridHelper args={[3, 12, "#555", "#333"]} />
          <OrbitControls target={[0, 0.85, 0]} enablePan={false} minDistance={1.2} maxDistance={7} />
        </Canvas>
      </div>
    </PreviewBoundary>
  );
}
