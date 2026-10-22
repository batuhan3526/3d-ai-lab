import { Suspense, useRef } from "react";
import * as THREE from "three";
import { Canvas, useFrame } from "@react-three/fiber";
import { OrbitControls, Environment, ContactShadows, PerspectiveCamera } from "@react-three/drei";
import { GLTFExporter } from "three/examples/jsm/exporters/GLTFExporter.js";
import { GarmentMesh } from "./GarmentMesh";
import { Mannequin } from "./Mannequin";
import { useMetrics } from "../store/metrics";

// FPS + WebGL render istatistikleri → metrik store (sahneyi yeniden render etmez).
// gl.info.render her kareden sonra sıfırlanır; useFrame'de okumak son kareyi verir.
function MetricsReader() {
  const setScene = useMetrics((s) => s.setScene);
  const frames = useRef(0);
  const last = useRef(0);
  useFrame(({ gl, clock }) => {
    frames.current++;
    const t = clock.getElapsedTime();
    const dt = t - last.current;
    if (dt >= 0.5) {
      setScene({
        fps: Math.round(frames.current / dt),
        triangles: gl.info.render.triangles,
        drawCalls: gl.info.render.calls,
        textures: gl.info.memory.textures,
        geometries: gl.info.memory.geometries,
      });
      frames.current = 0;
      last.current = t;
    }
  });
  return null;
}

export type EnvPreset = "city" | "studio" | "sunset" | "dawn" | "night" | "warehouse" | "forest" | "apartment";

// Zaman-bazlı turntable: sahne içeriğini (mesh + manken + zemin gölgesi) Y
// ekseninde döndürür. useFrame'in delta'sı saniye cinsindendir, dolayısıyla
// dönüş hızı FPS'ten bağımsızdır — düşük FPS'te de tam bir tur `secondsPerTurn`
// saniyede tamamlanır (recordTurntable süresiyle birebir eşleşir).
function TurntableGroup({ secondsPerTurn, groupRef, children }: {
  secondsPerTurn?: number;
  /** Dışa-aktarma için grubu üst bileşene açar (yalnız içerik export edilir). */
  groupRef?: React.MutableRefObject<THREE.Group | null>;
  children: React.ReactNode;
}) {
  const internal = useRef<THREE.Group>(null);
  const ref = groupRef ?? internal;
  useFrame((_, delta) => {
    if (secondsPerTurn && secondsPerTurn > 0 && ref.current) {
      ref.current.rotation.y += ((2 * Math.PI) / secondsPerTurn) * delta;
    }
  });
  return <group ref={ref}>{children}</group>;
}

export function ThreeCanvas({ url, onPick, captureRef, exportRef, onReady, paintMode, onPaintTris, onMark, brush, maskTexture, selectedId, tilePreview, colorOverride, decalsOverride, envPreset = "city", turntableSecondsPerTurn = 0, mannequinUrl, mannequinAlign = false }: {
  url: string;
  colorOverride?: string;
  decalsOverride?: import("../types").Decal[];
  /** Verilmezse manken hiç render edilmez (CompareModal vb. temiz kalır). */
  mannequinUrl?: string | null;
  mannequinAlign?: boolean;
  envPreset?: EnvPreset;
  /** Bir tam tur için saniye; 0/undefined = turntable kapalı (zaman-bazlı, FPS'ten bağımsız). */
  turntableSecondsPerTurn?: number;
  onPick?: (p: [number, number, number], n: [number, number, number]) => void;
  captureRef?: React.MutableRefObject<(() => string) | null>;
  exportRef?: React.MutableRefObject<(() => Promise<ArrayBuffer>) | null>;
  onReady?: () => void;
  paintMode?: boolean;
  onPaintTris?: (tris: number[][], center: [number, number, number], radius: number,
    hitUv?: [number, number]) => void;
  onMark?: (point: [number, number, number], normal: [number, number, number]) => void;
  brush?: number;
  maskTexture?: import("three").Texture | null;
  selectedId?: string | null;
  tilePreview?: { url: string; repeat: number } | null;
}) {
  // Yalnız içerik grubunu (mesh + manken + zemin gölgesi) dışa aktarmak için ref.
  // Environment'ın PMREM/DataTexture'ı sahneye dahil edilirse GLTFExporter
  // "Invalid image type" fırlatır — bu yüzden tüm sahne yerine bu grubu export ederiz.
  const exportGroupRef = useRef<THREE.Group | null>(null);
  return (
    <Canvas
      gl={{ preserveDrawingBuffer: true }}
      onCreated={({ gl, scene, camera }) => {
        if (captureRef) captureRef.current = () => {
          gl.render(scene, camera);
          return gl.domElement.toDataURL("image/png");
        };
        if (exportRef) exportRef.current = () =>
          new Promise<ArrayBuffer>((resolve, reject) => {
            const target = exportGroupRef.current;
            if (!target) {
              reject(new Error("Export target not ready"));
              return;
            }
            // Turntable dönüşünü anlık sıfırla (dik yönlü snapshot), sonra geri al.
            const prevRotY = target.rotation.y;
            target.rotation.y = 0;
            const restore = () => { target.rotation.y = prevRotY; };
            new GLTFExporter().parse(
              target,
              (result) => { restore(); resolve(result as ArrayBuffer); },
              (err) => { restore(); reject(err); },
              { binary: true },
            );
          });
        if (import.meta.env.DEV) Object.assign(window as unknown as Record<string, unknown>, { __scene: scene, __THREE: THREE });
        onReady?.();
      }}
      shadows
    >
      <MetricsReader />
      <PerspectiveCamera makeDefault position={[0, 0.2, 2.2]} fov={35} />
      <ambientLight intensity={0.6} />
      <directionalLight position={[3, 5, 2]} intensity={1.2} castShadow />
      <Suspense fallback={null}>
        {/* Turntable: sahne içeriği döner; ışıklar/kamera/Environment SABİT kalır. */}
        <TurntableGroup secondsPerTurn={turntableSecondsPerTurn} groupRef={exportGroupRef}>
          <GarmentMesh url={url} onPick={onPick} paintMode={paintMode} onPaintTris={onPaintTris}
            onMark={onMark} brush={brush} maskTexture={maskTexture}
            selectedId={selectedId} tilePreview={tilePreview}
            colorOverride={colorOverride} decalsOverride={decalsOverride} />
          {mannequinUrl !== undefined && <Mannequin url={mannequinUrl} align={mannequinAlign} />}
        </TurntableGroup>
        {/* ContactShadows grubun DIŞINDA: render-target dokusu GLTFExporter'da
            "Invalid image type" fırlatır (canlı kanıt); gölgenin dönmesi de gerekmez. */}
        <ContactShadows position={[0, -0.8, 0]} opacity={0.4} scale={5} blur={2.5} />
        <Environment preset={envPreset} />
      </Suspense>
      {/* İşaretleme açıkken: SOL tık boyar, SAĞ tık döndürür (mod kapatmadan
          başka açıyı işaretle — işaretler kaybolmaz). Dokunmatik: tek parmak boya,
          iki parmak döndür/yakınlaş. Normal modda sol tık döndürür. */}
      <OrbitControls makeDefault enablePan={false} enableRotate
        minDistance={1} maxDistance={5}
        mouseButtons={paintMode
          ? { RIGHT: THREE.MOUSE.ROTATE }
          : { LEFT: THREE.MOUSE.ROTATE }}
        touches={paintMode
          ? { TWO: THREE.TOUCH.DOLLY_ROTATE }
          : { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN }} />
    </Canvas>
  );
}
