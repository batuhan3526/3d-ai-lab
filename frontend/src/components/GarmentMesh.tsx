import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Decal, useGLTF, useTexture } from "@react-three/drei";
import * as THREE from "three";
import { DecalGeometry } from "three/examples/jsm/geometries/DecalGeometry.js";
import { computeBoundsTree, disposeBoundsTree, acceleratedRaycast } from "three-mesh-bvh";
import { useDesign } from "../store/design";
import { useMetrics } from "../store/metrics";
import { startClothPreview } from "../lib/clothPreview";
import { useFabricCatalog } from "../store/fabrics";
import { fabricIdFromMaterial } from "../api/fabrics";
import type { Decal as DecalType } from "../types";

// Decal'ın yüzeye oturma oranı: DecalGeometry üçgenlerinin UV'sini NxN ızgaraya
// rasterize edip DOLU hücre oranı. Z-kutusu dışına taşan kıvrımlar atılınca o
// bölgelerde üçgen kalmaz → boş hücre = "kesik" delik. (UV-ALANI işe yaramaz:
// üst üste binen kıvrımlar ayak izini dolu gösterir; ızgara binme'yi tek sayar,
// gerçek delikleri boş bırakır.) Non-indexed geometri: her 3 vert = bir üçgen.
const COV_N = 40;
function uvCoverage(geom: THREE.BufferGeometry): number {
  const uv = geom.getAttribute("uv");
  if (!uv || uv.count < 3) return 1;
  const grid = new Uint8Array(COV_N * COV_N);
  for (let i = 0; i + 2 < uv.count; i += 3) {
    const ax = uv.getX(i), ay = uv.getY(i);
    const bx = uv.getX(i + 1), by = uv.getY(i + 1);
    const cx = uv.getX(i + 2), cy = uv.getY(i + 2);
    // UV bbox → ızgara hücre aralığı (UV [0,1] dışını yok say)
    let minX = Math.min(ax, bx, cx), maxX = Math.max(ax, bx, cx);
    let minY = Math.min(ay, by, cy), maxY = Math.max(ay, by, cy);
    const gx0 = Math.max(0, Math.floor(minX * COV_N)), gx1 = Math.min(COV_N - 1, Math.floor(maxX * COV_N));
    const gy0 = Math.max(0, Math.floor(minY * COV_N)), gy1 = Math.min(COV_N - 1, Math.floor(maxY * COV_N));
    const d = (bx - ax) * (cy - ay) - (cx - ax) * (by - ay);
    if (d === 0) continue;
    for (let gy = gy0; gy <= gy1; gy++) {
      const py = (gy + 0.5) / COV_N;
      for (let gx = gx0; gx <= gx1; gx++) {
        const px = (gx + 0.5) / COV_N;
        // baryzentrik nokta-içinde testi
        const u = ((bx - px) * (cy - py) - (cx - px) * (by - py)) / d;
        const v = ((cx - px) * (ay - py) - (ax - px) * (cy - py)) / d;
        if (u >= 0 && v >= 0 && u + v <= 1) grid[gy * COV_N + gx] = 1;
      }
    }
  }
  let filled = 0;
  for (let i = 0; i < grid.length; i++) filled += grid[i];
  return filled / grid.length;
}

// BVH: r3f, fırça modunda HER pointermove'da mesh'e raycast atar. BVH'siz bu
// O(üçgen) = 80k üçgende ~7ms/hareket → ana iş parçacığı kilitlenir, "kasma" +
// işaretlenen kırmızı bölge akıcı yenilenmez ("gözükmüyor" algısı). BVH ile
// raycast O(log n) ≈ 0.05ms. Prototype'a bir kez bağlanır (idempotent).
// three-mesh-bvh SÜRÜM ÇAKIŞMASI: drei transitif olarak 0.7.8 (computeBoundsTree
// → MeshBVH) getirirken uygulama 0.9.10 (→ GeometryBVH) kullanıyor. Her iki paket
// de global `declare module 'three'` ile BufferGeometry.prototype.computeBoundsTree'i
// FARKLI dönüş tipiyle augment ediyor; birleşen arayüz drei'nin imzasına çözülüyor →
// 0.9.10 fonksiyonunun ataması TS2322 veriyor. Modül-augmentation ile düzeltilemez:
// çakışan iki üçüncü-parti augment'tan birini kaldıramayız, dedupe için package.json'a
// da dokunamıyoruz. Bu yüzden tek atama noktasında dar bir cast (davranış aynı).
(THREE.BufferGeometry.prototype as unknown as {
  computeBoundsTree: typeof computeBoundsTree;
}).computeBoundsTree = computeBoundsTree;
THREE.BufferGeometry.prototype.disposeBoundsTree = disposeBoundsTree;
THREE.Mesh.prototype.raycast = acceleratedRaycast;

function DecalMesh({ decal, target, index, meshRadius }: { decal: DecalType; target: THREE.Mesh; index: number; meshRadius: number }) {
  const tex = useTexture(decal.image);
  const setDecalMetric = useMetrics((s) => s.setDecal);
  const decalRef = useRef<THREE.Mesh>(null);
  const depthFactor = decal.depthFactor ?? 1.0;
  const rotation = useMemo<[number, number, number]>(() => {
    const q = new THREE.Quaternion().setFromEuler(
      new THREE.Euler(decal.rotation[0], decal.rotation[1], decal.rotation[2]));
    if (decal.spin) {
      q.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), decal.spin));
    }
    const e = new THREE.Euler().setFromQuaternion(q);
    return [e.x, e.y, e.z];
  }, [decal.rotation, decal.spin]);
  // Decal scale'in 3. bileşeni = yüzey NORMALİ boyunca projeksiyon kutusu DERİNLİĞİ
  // (drei → DecalGeometry size.z; kutu ±size/2 kırpar). Sığ derinlik kırışık/eğri
  // yüzeyde decal'ı PARÇALAR: kutu dışına taşan üçgenler atılır → KAYBOLAN kısımlar
  // (döndürürken fark edildi: spin görüntü içeriğini kesik bölgelere taşır).
  // VARSAYILAN ARTIK TAM (depthFactor 1.0 → derinlik=yanal boy=tam küp): kutu folde
  // ulaşır, decal asla yanal kırpılmaz/kaybolmaz. Eskiden derinlik sığdı çünkü tam
  // derinlik karşı yüzeye sızıyordu — ama artık 90° back-face cull (aşağıda) o arka
  // sızmayı temizliyor. Yani: tam derinlik (kaybolma yok) + cull (arka-sızma yok).
  // depthFactor slider'ı yine azaltmaya izin verir (özel decal'da daha az bleed için).
  const scale = useMemo<[number, number, number]>(
    () => [decal.scale, decal.scale, Math.min(decal.scale, meshRadius * depthFactor)],
    [decal.scale, meshRadius, depthFactor],
  );
  // mesh prop'unu STABİLLE: drei'nin useLayoutEffect dep'i `mesh`. Her render'da
  // `{current:target}` yeni obje verirsek drei DecalGeometry'yi HER render'da yeniden
  // kurar (perf bug) + bizim grazing-cull'umuz (stabil dep, mount'ta 1 kez) silinir →
  // tıklayınca "bütünleşiyor" ama tutarsız. useMemo ile drei sadece target değişince kurar.
  const meshProp = useMemo(() => ({ current: target }), [target]);

  // Doku örnekleme ayarları — BEYAZ KENAR / KESİK GÖRÜNÜM fix'i:
  // - ClampToEdgeWrapping: kenar teksellerini tekrarlamak yerine sabitler → decal
  //   sınırında karşı-kenar sızması/hayalet çizgi yok.
  // - generateMipmaps + anisotropy 8: eğik/uzak yüzeyde kenar aliasing'i (kesik
  //   görünen dişli üçgen kenarları) yumuşar.
  // - SRGBColorSpace: yanlış renk uzayı dokuyu SOLDURUR/beyazlatır; PNG/JPG decal
  //   sRGB'dir, doğru işaretlenmeli.
  useLayoutEffect(() => {
    tex.wrapS = THREE.ClampToEdgeWrapping;
    tex.wrapT = THREE.ClampToEdgeWrapping;
    tex.anisotropy = 8;
    tex.generateMipmaps = true;
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.needsUpdate = true;
  }, [tex]);

  // Doku çözünürlüğü (yüklendiğinde) → metrik paneli
  useEffect(() => {
    const img = tex.image as { width?: number; height?: number } | undefined;
    if (img?.width) setDecalMetric(decal.id, { resW: img.width, resH: img.height ?? 0 });
  }, [tex, decal.id, setDecalMetric]);

  // Oturma oranı: mevcut derinlikteki projeksiyonu, kırpılmamış TAM-KÜP (z=yanal)
  // referansla kıyasla. seat = cov/covRef → 1=tam oturmuş, düşük=kesik. Referansa
  // oranlamak şart: eğri/kenar yüzeyde ayak izi hiçbir zaman tam kareyi doldurmaz,
  // mutlak değer hep ~%70 çıkar; oran ise "daha derin yapsam kazanır mıyım"ı ölçer.
  useEffect(() => {
    if (!target) return;
    const pos = new THREE.Vector3(decal.position[0], decal.position[1], decal.position[2]);
    const eul = new THREE.Euler(rotation[0], rotation[1], rotation[2]);
    const depth = Math.min(decal.scale, meshRadius * depthFactor);
    try {
      const cur = new DecalGeometry(target, pos, eul, new THREE.Vector3(decal.scale, decal.scale, depth));
      const ref = new DecalGeometry(target, pos, eul, new THREE.Vector3(decal.scale, decal.scale, decal.scale));
      const covRef = Math.max(uvCoverage(ref), 1e-3);
      const seat = Math.min(uvCoverage(cur) / covRef, 1);
      cur.dispose(); ref.dispose();
      setDecalMetric(decal.id, { coverage: seat });
    } catch { /* ölçüm başarısızsa rozet 'tam' kalsın */ }
  }, [decal.id, decal.scale, depthFactor, meshRadius, decal.position, rotation, target, setDecalMetric]);

  // REALİZM: arka-yüz cull. Gerçek bir baskı SÜREKLİ/bütün bir parçadır ve yüzeye
  // ARKADAN dolanmaz. Düzlemsel projeksiyon ise back-facing üçgenleri de doldurup
  // arka-dolanma/smear yapar. Normali projeksiyon yönünün TERSİNE bakan (>90°)
  // üçgenleri eleriz → imkânsız arka-dolanma gider, ön yüz BÜTÜN kalır (parçalanmaz).
  // Karar: bütünlük > agresif-cull. e2e ile tarandı: 65° esnemeyi
  // kaldırır AMA kıvrımda decal'ı PARÇALAR (gerçek dışı); 90° bütün bırakır, sadece
  // arka-yüz gider. Kalan hafif esneme kötü yerleşimde olur → decal'ı düz yere taşı.
  // drei useLayoutEffect'te geometriyi kurar; biz sonraki effect'te eleriz (her
  // rebuild'de userData.culled sıfırlanır → yeniden elenir; mesh prop stabil olduğu
  // için drei artık her render kurmaz, cull tutarlı).
  useEffect(() => {
    const g = decalRef.current?.geometry;
    if (!g) return;
    const posA = g.getAttribute("position"), norA = g.getAttribute("normal"), uvA = g.getAttribute("uv");
    if (!posA || !norA || !uvA || g.userData.culled) return;
    const minDot = Math.cos((90 * Math.PI) / 180); // 0 → sadece arka-yüz (n·projDir<0) elenir
    const projDir = new THREE.Vector3(0, 0, 1)
      .applyEuler(new THREE.Euler(rotation[0], rotation[1], rotation[2])).normalize();
    const kp: number[] = [], kn: number[] = [], ku: number[] = [];
    const n = new THREE.Vector3();
    for (let i = 0; i < posA.count; i += 3) {
      n.set(norA.getX(i) + norA.getX(i + 1) + norA.getX(i + 2),
            norA.getY(i) + norA.getY(i + 1) + norA.getY(i + 2),
            norA.getZ(i) + norA.getZ(i + 1) + norA.getZ(i + 2)).normalize();
      if (n.dot(projDir) < minDot) continue; // yatık/arkaya bakan → ele
      for (let k = 0; k < 3; k++) {
        kp.push(posA.getX(i + k), posA.getY(i + k), posA.getZ(i + k));
        kn.push(norA.getX(i + k), norA.getY(i + k), norA.getZ(i + k));
        ku.push(uvA.getX(i + k), uvA.getY(i + k));
      }
    }
    g.setAttribute("position", new THREE.Float32BufferAttribute(kp, 3));
    g.setAttribute("normal", new THREE.Float32BufferAttribute(kn, 3));
    g.setAttribute("uv", new THREE.Float32BufferAttribute(ku, 2));
    g.userData.culled = true;
  }, [decal.id, decal.scale, depthFactor, meshRadius, decal.position, rotation, target]);

  return (
    <Decal ref={decalRef} mesh={meshProp} position={decal.position} rotation={rotation} scale={scale}>
      <meshStandardMaterial map={tex} transparent opacity={decal.opacity ?? 1}
        color={decal.color ?? "#ffffff"}
        depthWrite={false}
        alphaTest={0.01}
        polygonOffset polygonOffsetFactor={-(index + 1) * 4} />
    </Decal>
  );
}

function TilePreview({ root, url, repeat }: { root: THREE.Object3D; url: string; repeat: number }) {
  const tex = useTexture(url);
  useEffect(() => {
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    tex.repeat.set(repeat, repeat);
    tex.needsUpdate = true;
    const saved: [THREE.MeshStandardMaterial, THREE.Texture | null][] = [];
    root.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      const mat = m.material as THREE.MeshStandardMaterial;
      if (!mat.isMeshStandardMaterial) return;
      saved.push([mat, mat.map]);
      mat.map = tex;
      mat.needsUpdate = true;
    });
    return () => { saved.forEach(([mat, old]) => { mat.map = old; mat.needsUpdate = true; }); };
  }, [root, tex, repeat]);
  return null;
}

// PBR malzeme presetleri (kumaş hissi): roughness/metalness.
const MATERIAL_PRESETS: Record<string, { roughness: number; metalness: number }> = {
  mat: { roughness: 0.9, metalness: 0.0 },
  deri: { roughness: 0.5, metalness: 0.1 },
  kot: { roughness: 0.85, metalness: 0.0 },
  saten: { roughness: 0.25, metalness: 0.1 },
  parlak: { roughness: 0.1, metalness: 0.2 },
  metalik: { roughness: 0.3, metalness: 0.9 },
};

// Kumaş hazır ayarlarının "sheen" (kumaş parlaması) değeri yalnız
// MeshPhysicalMaterial'de var. GLB'den gelen MeshStandardMaterial'i klonlarken
// fiziksel karşılığına çeviriyoruz: sheen/clearcoat/transmission = 0 iken görünüm
// standart malzemeyle aynıdır (ior 1.5 → aynı F0 = 0.04), haritalar/renk korunur.
// isMeshStandardMaterial fiziksel malzemede de true → mevcut kontroller değişmez.
function toPhysical(mat: THREE.Material): THREE.Material {
  const std = mat as THREE.MeshStandardMaterial;
  if (!std.isMeshStandardMaterial || (mat as THREE.MeshPhysicalMaterial).isMeshPhysicalMaterial) return mat;
  const phys = new THREE.MeshPhysicalMaterial();
  THREE.MeshStandardMaterial.prototype.copy.call(phys, std);
  // Standart copy() defines'ı {STANDARD} yapar; PHYSICAL olmadan sheen derlenmez.
  phys.defines = { STANDARD: "", PHYSICAL: "" };
  return phys;
}

const Z_AXIS = new THREE.Vector3(0, 0, 1);

// Üçgen başına komşu slotu: manifold'da 3 yeter; AI mesh'lerinde non-manifold
// kenarlar olabildiği için pay bırakıyoruz.
const ADJ_SLOTS = 6;

/** Üçgen komşuluğu (pozisyon kaynaklı, UV seam'lerinden BAĞIMSIZ): xatlas
 * unwrap UV seam'lerinde vertex'leri çoğaltır; index-tabanlı komşuluk seam'de
 * kopar. Vertex'ler konuma göre kaynaklanır, kenar paylaşan üçgenler bağlanır. */
function buildAdjacency(geom: THREE.BufferGeometry): Int32Array {
  const pos = geom.attributes.position;
  const index = geom.index;
  const triCount = (index ? index.count : pos.count) / 3;
  const groupOf = new Int32Array(pos.count);
  const groups = new Map<string, number>();
  for (let i = 0; i < pos.count; i++) {
    const k = `${pos.getX(i).toFixed(5)},${pos.getY(i).toFixed(5)},${pos.getZ(i).toFixed(5)}`;
    let g = groups.get(k);
    if (g === undefined) { g = groups.size; groups.set(k, g); }
    groupOf[i] = g;
  }
  const G = groups.size;
  const adj = new Int32Array(triCount * ADJ_SLOTS).fill(-1);
  const link = (t: number, o: number) => {
    for (let s = 0; s < ADJ_SLOTS; s++) {
      const v = adj[t * ADJ_SLOTS + s];
      if (v === o) return;
      if (v === -1) { adj[t * ADJ_SLOTS + s] = o; return; }
    }
  };
  // kenar -> son görülen üçgen; non-manifold kenarda zincirleme bağ yeterli
  const lastTriOnEdge = new Map<number, number>();
  for (let t = 0; t < triCount; t++) {
    for (let e = 0; e < 3; e++) {
      const i0 = index ? index.getX(t * 3 + e) : t * 3 + e;
      const i1 = index ? index.getX(t * 3 + ((e + 1) % 3)) : t * 3 + ((e + 1) % 3);
      let a = groupOf[i0], b = groupOf[i1];
      if (a === b) continue;
      if (a > b) { const tmp = a; a = b; b = tmp; }
      const k = a * G + b;
      const prev = lastTriOnEdge.get(k);
      if (prev !== undefined && prev !== t) { link(t, prev); link(prev, t); }
      lastTriOnEdge.set(k, t);
    }
  }
  return adj;
}

const adjacencyCache = new WeakMap<THREE.BufferGeometry, Int32Array>();

/** 3B fırça: hit üçgeninden komşuluk üzerinden BFS ile yayılır, yarıçap dışına
 * çıkınca durur. Böylece (1) UV adaları yüzünden alakasız bölge boyanmaz,
 * (2) kumaşın iç/arka duvarına "hava yoluyla" sıçranmaz — sadece mouse'un
 * bastığı yüzey tabakası boyanır. Dönen her eleman [u0,v0,u1,v1,u2,v2,
 * x0,y0,z0, x1,y1,z1, x2,y2,z2] — 3B köşeler, maske tarafında texel başına
 * "gerçekten daire içinde mi" testi için (lokal uzay). */
function collectBrushTriangles(
  mesh: THREE.Mesh,
  localPoint: THREE.Vector3,
  radiusLocal: number,
  hitFaceIndex: number,
): number[][] {
  const geom = mesh.geometry;
  const pos = geom.attributes.position;
  const uv = geom.attributes.uv;
  if (!pos || !uv || hitFaceIndex == null) return [];
  let adj = adjacencyCache.get(geom);
  if (!adj) { adj = buildAdjacency(geom); adjacencyCache.set(geom, adj); }
  const index = geom.index;
  const r2 = radiusLocal * radiusLocal;
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3();
  const triangle = new THREE.Triangle(), closest = new THREE.Vector3();
  const tris: number[][] = [];
  const visited = new Set<number>([hitFaceIndex]);
  const queue = [hitFaceIndex];
  while (queue.length) {
    const t = queue.pop()!;
    const i0 = index ? index.getX(t * 3) : t * 3;
    const i1 = index ? index.getX(t * 3 + 1) : t * 3 + 1;
    const i2 = index ? index.getX(t * 3 + 2) : t * 3 + 2;
    a.fromBufferAttribute(pos, i0);
    b.fromBufferAttribute(pos, i1);
    c.fromBufferAttribute(pos, i2);
    // GERÇEK üçgen-küre kesişimi (sadece köşe testi değil): köşeleri dışarıda
    // kalan büyük üçgenler boyanmıyor ve BFS yayılımını tıkıyordu → bölge
    // içinde boyasız çatlak şeritleri kalıyordu.
    triangle.set(a, b, c);
    triangle.closestPointToPoint(localPoint, closest);
    const inside = t === hitFaceIndex || closest.distanceToSquared(localPoint) < r2;
    if (!inside) continue; // yarıçap dışı: buradan yayılma da durur
    tris.push([
      uv.getX(i0), uv.getY(i0), uv.getX(i1), uv.getY(i1), uv.getX(i2), uv.getY(i2),
      a.x, a.y, a.z, b.x, b.y, b.z, c.x, c.y, c.z,
    ]);
    for (let s = 0; s < ADJ_SLOTS; s++) {
      const n = adj[t * ADJ_SLOTS + s];
      if (n >= 0 && !visited.has(n)) { visited.add(n); queue.push(n); }
    }
  }
  return tris;
}

export function GarmentMesh({ url, onPick, paintMode, onPaintTris, onMark, brush = 0.05, maskTexture, selectedId, tilePreview, colorOverride, decalsOverride }: {
  url: string;
  /** Karşılaştırma için store yerine sabit renk/decal göster (undefined → store). */
  colorOverride?: string;
  decalsOverride?: import("../types").Decal[];
  onPick?: (point: [number, number, number], normal: [number, number, number]) => void;
  paintMode?: boolean;
  /** tris: [u0,v0,u1,v1,u2,v2, x0..z2]; center+radius lokal uzayda fırça küresi;
   * hitUv: en az bir texel boyanmasını garantilemek için isabet UV'si */
  onPaintTris?: (tris: number[][], center: [number, number, number], radius: number,
    hitUv?: [number, number]) => void;
  /** Fırça her dokunduğunda DÜNYA-uzayı isabet noktası + yüzey normali. Motif
   * decal'i işaretli bölgenin merkez+normaline yerleştirmek için biriktirilir. */
  onMark?: (point: [number, number, number], normal: [number, number, number]) => void;
  /** Fırça yarıçapı, modelin bounding-sphere yarıçapına oran (0.02–0.15) */
  brush?: number;
  maskTexture?: THREE.Texture | null;
  selectedId?: string | null;
  tilePreview?: { url: string; repeat: number } | null;
}) {
  const { scene } = useGLTF(url);
  const storeColor = useDesign((s) => s.color);
  const storeDecals = useDesign((s) => s.decals);
  const storeMaterial = useDesign((s) => s.material);
  const color = colorOverride ?? storeColor;
  const decals = decalsOverride ?? storeDecals;
  const selectedDecal = decals.find((d) => d.id === selectedId) ?? null;

  // Materyalleri klonla (useGLTF cache'ini kirletmemek için) ve normal yoksa hesapla.
  // Prosedürel GLB'ler (ve bazı AI mesh'leri) NORMAL attribute'u içermeyebilir;
  // drei <Decal> -> DecalGeometry normal okur, yoksa "undefined.getX" ile patlar
  // ve WebGL context'i kaybeder (ekran kararır). Normal ayrıca doğru aydınlatma için şart.
  const cloned = useMemo(() => {
    const root = scene.clone(true);
    root.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      if (m.material) m.material = toPhysical((m.material as THREE.Material).clone());
      if (m.geometry && !m.geometry.attributes.normal) {
        m.geometry = m.geometry.clone();
        m.geometry.computeVertexNormals();
      }
      // BVH inşa et: fırça raycast'lerini O(log n)'e indirir (lag fix). Her
      // hareketteki raycast bunu kullanır; bir kez kurulur, geom ile yaşar.
      if (m.geometry && !m.geometry.boundsTree) m.geometry.computeBoundsTree();
    });
    return root;
  }, [scene]);

  // İlk recolor edilebilir mesh'i decal hedefi olarak bul.
  // useState (useRef değil) çünkü hedefin set edilmesi render tetiklemeli —
  // aksi halde kayıtlı decal'leri olan bir proje ilk yüklemede decal'siz çizilir.
  const [target, setTarget] = useState<THREE.Mesh | null>(null);
  // F4 kumaş hazır ayarı (material = "fabric:<id>"): PBR değerleri /fabrics
  // kataloğundan. Katalog gelene kadar "mat" presetiyle çizilir.
  const fabricId = fabricIdFromMaterial(storeMaterial);
  const fabric = useFabricCatalog((s) => (fabricId ? s.fabrics?.find((f) => f.id === fabricId) ?? null : null));
  const loadFabrics = useFabricCatalog((s) => s.load);
  useEffect(() => { if (fabricId) void loadFabrics(); }, [fabricId, loadFabrics]);
  useEffect(() => {
    const pbr = fabric
      ? { roughness: fabric.pbr.roughness, metalness: fabric.pbr.metalness }
      : MATERIAL_PRESETS[storeMaterial] ?? MATERIAL_PRESETS.mat;
    let first: THREE.Mesh | null = null;
    cloned.traverse((o) => {
      const m = o as THREE.Mesh;
      if (m.isMesh) {
        if (!first) first = m;
        const mat = m.material as THREE.MeshStandardMaterial;
        if (mat.color) mat.color.set(color);
        if (mat.isMeshStandardMaterial) {
          mat.roughness = pbr.roughness;
          mat.metalness = pbr.metalness;
          const phys = mat as THREE.MeshPhysicalMaterial;
          if (phys.isMeshPhysicalMaterial) {
            // Kumaş presetinde kumaş parlaması; diğer presetlerde kapalı (eski görünüm).
            phys.sheen = fabric?.pbr.sheen ?? 0;
            phys.sheenRoughness = fabric?.pbr.sheen_roughness ?? 1;
            phys.sheenColor.set(fabric?.pbr.sheen_color ?? "#000000");
          }
          mat.needsUpdate = true;
        }
      }
    });
    setTarget((prev) => prev ?? first);
  }, [cloned, color, storeMaterial, fabric]);

  // F5 v2: işaretlenen bölgeyi mesh üzerinde göster. Maske canvas'ı emissiveMap
  // olarak bindirilir — beyaz (işaretli) pikseller kırmızı parlar, kıyafetin
  // gerçek dokusuna/rengine dokunulmaz; mod kapanınca tamamen kaldırılır.
  useEffect(() => {
    const overlay = paintMode ? maskTexture ?? null : null;
    cloned.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      const mat = m.material as THREE.MeshStandardMaterial;
      if (!mat.isMeshStandardMaterial) return;
      mat.emissiveMap = overlay;
      mat.emissive.set(overlay ? "#ff0000" : "#000000");
      mat.emissiveIntensity = overlay ? 3.0 : 1.0; // gözle net görülsün (0.9 sönük kalıyordu)
      mat.needsUpdate = true; // emissiveMap null↔texture geçişi shader recompile ister
    });
  }, [cloned, paintMode, maskTexture]);

  const painting = useRef(false);

  // Hafif drape önizlemesi (Task D2): store'dan okunur (prop threading yok). enabled
  // iken hedef mesh'e kütle-yay çözücü bağlanır (startClothPreview rAF döngüsü + FPS
  // auto-stop). Temizlik/deps değişince stop() çağrılır → mesh dinlenme haline döner
  // (paylaşılan useGLTF cache'i bozulmaz). SADECE canlı görünümde: colorOverride set
  // ise (CompareModal karşılaştırma render'ı) drape uygulanmaz.
  const drapeEnabled = useDesign((s) => s.drapeEnabled);
  const drapeIntensity = useDesign((s) => s.drapeIntensity);
  const drapeAutoStop = useDesign((s) => s.drapeAutoStop);
  const isLiveView = colorOverride === undefined;
  useEffect(() => {
    if (!isLiveView || !drapeEnabled || !target) return;
    const stop = startClothPreview(target, {
      intensity: drapeIntensity,
      onAutoStop: () => drapeAutoStop(),
    });
    return stop;
  }, [isLiveView, drapeEnabled, drapeIntensity, target, drapeAutoStop]);

  // Fırça yarıçapını model boyutuna oranla (her mesh farklı ölçekte gelebilir)
  const meshRadius = useMemo(
    () => new THREE.Box3().setFromObject(cloned).getBoundingSphere(new THREE.Sphere()).radius || 1,
    [cloned],
  );

  // Mesh çözünürlüğü (vertex/üçgen) → metrik paneli
  const setScene = useMetrics((s) => s.setScene);
  useEffect(() => {
    let verts = 0, faces = 0;
    cloned.traverse((o) => {
      const m = o as THREE.Mesh;
      if (!m.isMesh) return;
      const pos = m.geometry.getAttribute("position");
      verts += pos ? pos.count : 0;
      const idx = m.geometry.getIndex();
      faces += idx ? idx.count / 3 : (pos ? pos.count / 3 : 0);
    });
    setScene({ meshVerts: verts, meshFaces: Math.round(faces) });
  }, [cloned, setScene]);

  // Mouse ucundaki daire imleç (yüzeye yapışır, raycast'e görünmez)
  const cursorRef = useRef<THREE.Group>(null);
  useEffect(() => {
    if (!paintMode && cursorRef.current) cursorRef.current.visible = false;
  }, [paintMode]);

  type PaintEvent = { point: THREE.Vector3; face?: THREE.Face | null; faceIndex?: number; object: THREE.Object3D; uv?: THREE.Vector2 };
  const updateCursor = (e: PaintEvent) => {
    const cur = cursorRef.current;
    if (!cur || !e.face) return;
    const nWorld = e.face.normal.clone().transformDirection(e.object.matrixWorld);
    cur.position.copy(e.point).addScaledVector(nWorld, 0.003);
    cur.quaternion.setFromUnitVectors(Z_AXIS, nWorld);
    cur.scale.setScalar(brush * meshRadius);
    cur.visible = true;
  };
  const paintFrom = (e: PaintEvent) => {
    if (!onPaintTris || !e.face || e.faceIndex == null) return;
    const mesh = e.object as THREE.Mesh;
    const local = mesh.worldToLocal(e.point.clone());
    const scale = mesh.getWorldScale(new THREE.Vector3()).x || 1;
    const r = (brush * meshRadius) / scale;
    const tris = collectBrushTriangles(mesh, local, r, e.faceIndex);
    if (tris.length) {
      onPaintTris(tris, [local.x, local.y, local.z], r,
        e.uv ? [e.uv.x, e.uv.y] : undefined);
    }
    // Motif decal için: DÜNYA-uzayı isabet noktası + yüzey normali (decal pozu
    // hedef mesh identity transform'da olduğundan dünya≈lokal — handlePick ile aynı).
    if (onMark && e.face) {
      const nWorld = e.face.normal.clone().transformDirection(mesh.matrixWorld);
      onMark([e.point.x, e.point.y, e.point.z], [nWorld.x, nWorld.y, nWorld.z]);
    }
  };

  return (
    <group
      onPointerDown={(e) => {
        // F5 v2 fırça modu: SOL tık 3B yarıçap içindeki üçgenleri boyar (orbit'i bloke et).
        // Sağ/orta tık boyamaz, propagation'ı durdurmaz → OrbitControls döndürür
        // (işaretleme açıkken mod kapatmadan başka açıyı görebilmek için).
        if (paintMode && onPaintTris && e.face) {
          if (e.button !== 0) return;
          e.stopPropagation();
          (e.target as Element).setPointerCapture?.(e.pointerId);
          painting.current = true;
          updateCursor(e);
          paintFrom(e);
          return;
        }
        if (!onPick || !e.face) return;
        e.stopPropagation();
        onPick(
          [e.point.x, e.point.y, e.point.z],
          [e.face.normal.x, e.face.normal.y, e.face.normal.z],
        );
      }}
      onPointerMove={(e) => {
        if (!paintMode) return;
        updateCursor(e); // basılı olmasa da imleç dairesi yüzeyi takip etsin
        if (onPaintTris && painting.current && e.face) {
          e.stopPropagation();
          paintFrom(e);
        }
      }}
      onPointerUp={() => { painting.current = false; }}
      onPointerLeave={() => {
        painting.current = false;
        if (cursorRef.current) cursorRef.current.visible = false;
      }}
    >
      <primitive object={cloned} />
      {/* DRAPE = ÇIKARTMALARI GİZLE: decal'ler ayrı düzlemsel projeksiyon mesh'leri;
          deforme olan vertex'leri TAKİP EDEMEZLER (dinlenme yüzeyine sabittirler).
          Drape sırasında görünür kalsalardı kumaştan kopuk yüzerlerdi → dürüst UX:
          drape açıkken tüm decal'ler + seçim halkası gizlenir, drape kapanınca
          (group visible=true) geri gelir. group identity transform → dünya konumu değişmez. */}
      {target && (
        <group visible={!(isLiveView && drapeEnabled)}>
          {decals.map((d, i) => <DecalMesh key={d.id} decal={d} target={target} index={i} meshRadius={meshRadius} />)}
          {selectedDecal && (
            <mesh position={selectedDecal.position} rotation={selectedDecal.rotation}
              raycast={() => null} renderOrder={1000}>
              <ringGeometry args={[Math.max(selectedDecal.scale * 0.55, 0.03),
                                   Math.max(selectedDecal.scale * 0.62, 0.04), 48]} />
              <meshBasicMaterial color="#22d3ee" transparent opacity={0.95}
                depthTest={false} side={THREE.DoubleSide} />
            </mesh>
          )}
        </group>
      )}
      {tilePreview && <TilePreview root={cloned} url={tilePreview.url} repeat={tilePreview.repeat} />}
      <group ref={cursorRef} visible={false} renderOrder={999}>
        <mesh raycast={() => null}>
          <ringGeometry args={[0.92, 1, 48]} />
          <meshBasicMaterial color="#ff2d2d" transparent opacity={0.9}
            depthTest={false} side={THREE.DoubleSide} />
        </mesh>
        <mesh raycast={() => null}>
          <circleGeometry args={[0.92, 48]} />
          <meshBasicMaterial color="#ff2d2d" transparent opacity={0.15}
            depthTest={false} side={THREE.DoubleSide} />
        </mesh>
      </group>
    </group>
  );
}
