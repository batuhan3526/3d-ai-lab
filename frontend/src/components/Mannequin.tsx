import { Component, Suspense, useEffect, useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import { useGLTF, TransformControls } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { useDesign } from "../store/design";

/**
 * Otomatik oturtma sezgiseli (S2) — SAF fonksiyon, birim testi edilebilir.
 *
 * Manken ham GLB ölçeğiyle origin'de doğuyordu; kullanıcı her şeyi gizmo ile
 * ayarlamak zorundaydı. Bunun yerine kıyafete göreli oturtuyoruz:
 *   - Ölçek: mankenBoyu = kıyafetBoyu * 2.2 olacak şekilde tek-tip ölçek.
 *     (bir tişört gövdenin ~%45'ini kaplar → tam boy ≈ kıyafet * 2.2)
 *   - Konum: manken merkez XZ = kıyafet merkez XZ; mankenin GÖĞSÜ (tabandan
 *     %62) kıyafet bbox merkez-Y'sine hizalanır.
 *
 * İki bbox da mankenin GRUP-ebeveyn karesinde (turntable-yerel) ifade edilir.
 * `mannequinBox` mankenin kendi içerik-yerel bbox'u (ölçek/konum uygulanmadan).
 * Grup rotasyonu 0 varsayıldığından: dünyaNoktası = yerelNokta * scale + position.
 *
 * @returns grup transform'u: tek-tip `scale` ve `position` [x,y,z].
 */
export function computeMannequinFit(
  garmentBox: THREE.Box3,
  mannequinBox: THREE.Box3,
): { scale: number; position: [number, number, number] } {
  const gSize = new THREE.Vector3();
  garmentBox.getSize(gSize);
  const gCenter = new THREE.Vector3();
  garmentBox.getCenter(gCenter);
  const mSize = new THREE.Vector3();
  mannequinBox.getSize(mSize);
  const mCenter = new THREE.Vector3();
  mannequinBox.getCenter(mCenter);

  const garmentHeight = Math.max(gSize.y, 1e-6);
  const mannequinHeight = Math.max(mSize.y, 1e-6);
  // Tişört gövdenin ~%45'ini kaplar → hedef tam boy = kıyafet * 2.2.
  const targetHeight = garmentHeight * 2.2;
  const scale = targetHeight / mannequinHeight;

  // Göğüs: ölçekli mankenin tabanından %62 yukarı (yerel koordinatta).
  const chestLocalY = mannequinBox.min.y + 0.62 * mSize.y;
  // dünyaGöğüsY = chestLocalY * scale + position.y  ==  gCenter.y
  //   → position.y = gCenter.y - chestLocalY * scale
  // XZ: mCenter * scale + position == gCenter  → position = gCenter - mCenter*scale
  const position: [number, number, number] = [
    gCenter.x - mCenter.x * scale,
    gCenter.y - chestLocalY * scale,
    gCenter.z - mCenter.z * scale,
  ];
  return { scale, position };
}

/**
 * Statik manken (Task D1). R3F içi bileşen — bir <Canvas> (ThreeCanvas) alt
 * ağacına monte edilir. Kıyafetin arkasına yarı saydam bir base-mesh koyar;
 * "Hizala" modunda TransformControls gizmo'su ile kıyafete hizalanır.
 *
 * Zarif düşüş: GLB indirilmemişse (dosya eksik/bozuk) useGLTF hata fırlatır →
 * içteki hata sınırı yakalar, 3B'de hiçbir şey render etmez AMA sessizce yutmak
 * yerine onError'ı çağırır + window olayı yayar → panel görünür amber uyarı gösterir.
 *
 * Kullanım (canvas içi):
 *   <Mannequin url={assetUrl(entry.file)} align={aligning} />
 */

/** GLB yüklenemezse (dosya eksik / bozuk) 3B'de null render eden, ama hatayı
 *  görünür kılmak için onError'ı çağıran + window olayı yayan hata sınırı. */
class MannequinErrorBoundary extends Component<{ children: ReactNode; onError?: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch() {
    // Sessiz null yerine: paneli haberdar et. onError doğrudan prop olarak
    // gelebilir; ayrıca ThreeCanvas arası prop threading olmadan da ulaşsın
    // diye window köprüsü (DesignerPage bunu dinler).
    this.props.onError?.();
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("mannequin:loaderror"));
    }
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

function MannequinModel({ url, align }: { url: string; align: boolean }) {
  const mannequin = useDesign((s) => s.mannequin);
  const updateTransform = useDesign((s) => s.updateMannequinTransform);
  const { scene } = useGLTF(url);
  const groupRef = useRef<THREE.Group>(null);

  // useGLTF cache'ini kirletmemek için klonla; manken decal/fırça hedefi olmasın
  // diye tüm mesh raycast'lerini kapat (gizmo kendi raycast'ini yapar).
  // Ayrıca mankenin içerik-yerel bbox'unu (grup transform'u UYGULANMADAN, root
  // henüz parent'sızken → yerel geometri AABB) auto-fit için burada hesapla.
  const { cloned, mannequinLocalBox } = useMemo(() => {
    const root = scene.clone(true);
    root.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      if (m.material) m.material = (m.material as THREE.Material).clone();
      m.raycast = () => null;
    });
    const box = new THREE.Box3().setFromObject(root);
    return { cloned: root, mannequinLocalBox: box };
  }, [scene]);

  // Opaklık senkronu (manken yarı saydam durur → altındaki kıyafet görünür).
  const opacity = mannequin?.opacity ?? 0.6;
  useEffect(() => {
    cloned.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh || !m.material) return;
      const mat = m.material as THREE.Material;
      mat.transparent = opacity < 1;
      mat.opacity = opacity;
      mat.depthWrite = opacity >= 1;
      mat.needsUpdate = true;
    });
  }, [cloned, opacity]);

  // Otomatik oturtma (S2). fitted değilken (yeni seçim / reset sonrası) her
  // karede dener; kıyafet mesh'i Suspense ile async yüklendiğinden bbox hazır
  // olana kadar sessizce bekler → hazır olunca hesaplar, store'a yazar, fitted=true.
  const fitted = mannequin?.fitted ?? false;
  const mannequinId = mannequin?.id;
  const attemptedRef = useRef(false);
  useEffect(() => {
    // fitted temizlenince (reset) veya farklı manken seçilince tekrar dene.
    if (!fitted) attemptedRef.current = false;
  }, [fitted, mannequinId]);
  useFrame(() => {
    // align modunda parent = TransformControls (gizmo mesh'leri bbox'u kirletir);
    // beklet → kullanıcı hizalamayı kapatınca (parent tekrar turntable) otur.
    if (align || fitted || attemptedRef.current) return;
    const g = groupRef.current;
    if (!g || !g.parent) return;
    // Kıyafet bbox'u: mankenin GRUP-ebeveyn (turntable-yerel) karesinde topla;
    // mankenin kendi alt-ağacını (g'nin torunları) hariç tut. Turntable dönmüş
    // olsa bile parent- inverse dünya rotasyonunu çıkarır → kararlı yerel kutu.
    const parentInv = new THREE.Matrix4().copy(g.parent.matrixWorld).invert();
    const garmentBox = new THREE.Box3();
    let found = false;
    g.parent.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh || !m.geometry) return;
      for (let p: THREE.Object3D | null = o; p; p = p.parent) if (p === g) return;
      const b = new THREE.Box3().setFromObject(m);
      if (b.isEmpty()) return;
      b.applyMatrix4(parentInv);
      garmentBox.union(b);
      found = true;
    });
    if (!found || garmentBox.isEmpty() || mannequinLocalBox.isEmpty()) return;
    const { scale, position } = computeMannequinFit(garmentBox, mannequinLocalBox);
    attemptedRef.current = true;
    updateTransform({ position, rotation: [0, 0, 0], scale }, true);
  });

  if (!mannequin || !mannequin.visible) return null;
  const { position, rotation, scale } = mannequin.transform;

  const body = (
    <group ref={groupRef} position={position} rotation={rotation} scale={scale}>
      <primitive object={cloned} />
    </group>
  );

  if (!align) return body;

  // Hizalama gizmo'su (decal gizmo deseni; snap yok). Sürükleme sırasında
  // TransformControls nesneyi doğrudan mutasyona uğratır → store'a yaz.
  return (
    <TransformControls
      mode="translate"
      onObjectChange={() => {
        const g = groupRef.current;
        if (!g) return;
        updateTransform({
          position: [g.position.x, g.position.y, g.position.z],
          rotation: [g.rotation.x, g.rotation.y, g.rotation.z],
          scale: g.scale.x,
        });
      }}
    >
      {body}
    </TransformControls>
  );
}

export function Mannequin({ url, align = false, onError }: { url: string | null; align?: boolean; onError?: () => void }) {
  const mannequin = useDesign((s) => s.mannequin);
  if (!mannequin || !mannequin.visible || !url) return null;
  // key={url}: manken değişince hata sınırını yeniden mount et → önceki başarısız
  // GLB'nin "failed" durumu yeni (geçerli) mankene taşınmasın.
  return (
    <MannequinErrorBoundary key={url} onError={onError}>
      <Suspense fallback={null}>
        <MannequinModel url={url} align={align} />
      </Suspense>
    </MannequinErrorBoundary>
  );
}
