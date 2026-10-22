import * as THREE from "three";

// Hafif "önizleme fiziği" (deneysel) — gerçek kumaş simülasyonu DEĞİL (o BATCH-H,
// Blender offline). Burada tamamen istemci-tarafı, GPU'suz bir kütle-yay ağı:
// kıyafet mesh'inin EN ÜST %10 Y vertex'i sabit (askı noktası), kalanı yerçekimi
// + komşuluk yayları + sönümle sarkar, üstüne çok hafif bir rüzgâr sinüsü eklenir.
// ÇARPIŞMA YOK. requestAnimationFrame döngüsü `geometry.attributes.position`ı
// yerinde günceller ve her karede normalleri yeniden hesaplar. FPS 2 sn boyunca
// 30'un altına düşerse otomatik durur (onAutoStop) — ağır mesh'lerde arayüzü kilitlemez.
//
// GarmentMesh'in geometrisi useGLTF cache'inden PAYLAŞILIR (clone(true) geometriyi
// klonlamaz). Bu yüzden başlangıçta dinlenme (rest) konumları saklanır ve stop()
// bunları GERİ YÜKLER — aksi halde cache kalıcı olarak bozulur (Compare görünümü vb).

export type ClothPreviewOptions = {
  /** Slider şiddeti 0..1 → yerçekimi + rüzgâr genliğini ölçekler. */
  intensity?: number;
  /**
   * Fizik kendini durdurunca çağrılır. reason ayırt eder:
   *  - "fps": rAF döngüsü 2 sn boyunca <30 FPS ölçtü (canlı düşük performans).
   *  - "dense": mesh >30k vertex, hiç başlatılmadı (çözünürlük düşürülmeli).
   * Reason ayrıca "drape:autostop" window olayıyla da yayılır (UI ayrımı için).
   */
  onAutoStop?: (reason?: "fps" | "dense") => void;
};

type Solver = {
  /** Bir zaman adımı entegre eder (dt saniye, time saniye — rüzgâr fazı için). */
  step: (dt: number, time: number) => void;
  /** Grup konumlarını paylaşılan position attribute'una geri yazar (+needsUpdate). */
  writeBack: () => void;
  /** Dinlenme konumlarını geri yükler (stop / restore). */
  restore: () => void;
  groupCount: number;
  springCount: number;
};

// Kaba ama kararlı parametreler. dt her zaman ≤ 1/30'a kısılır, k*dt² küçük kalır.
const SPRING_K = 28;       // yay sertliği
const DAMPING = 0.90;      // hız koruma (kare başına)
const GRAVITY = -3.2;      // yerçekimi ivmesi (yerel ölçek ~1)
const WIND = 0.55;         // rüzgâr genliği (şiddetle çarpılır)
const MAX_VEL = 6;         // hız patlamasını engelle (NaN/uçuş koruması)
const TOP_FRACTION = 0.10; // en üst %10 Y sabit (askı)
// SİLUET KORUMA: her grubu KENDİ dinlenme konumuna çeken bir yay. Bu olmadan kenar
// yayları + sabit yerçekimi mesh'i aşağı "eritir" (siluet çöker). REST_K yeterince
// güçlü → siluet korunur; yerçekimi şiddetle 0.35'e ölçeklenir → maksimum sarkma
// nazik bir "sallanma"ya iner (asla "erime" olmaz). 300 adım/şiddet 1 sonrası
// dinlenmeden maks sapma bbox yüksekliğinin %8'inin altında kalır (birim test).
const REST_K = 22;         // dinlenme-konumu çapası (siluet sertliği)
const GRAVITY_SCALE = 0.35; // erime yerine hafif sarkma için yerçekimini kıs
const NORMALS_EVERY = 3;   // her karede değil, 3 karede bir normalleri yeniden hesapla (FPS)
const MAX_PHYSICS_VERTS = 30000; // bunun üstünde fizik başlatılmaz (arayüzü kilitler)

/**
 * Mesh geometrisinden bir kütle-yay çözücü kurar. Vertex'ler konuma göre kaynaklanır
 * (UV seam kopmalarından bağımsız — GarmentMesh.buildAdjacency ile aynı gerekçe),
 * kenar paylaşan gruplar yayla bağlanır. Saf sayısal; requestAnimationFrame gerektirmez,
 * bu yüzden birim testinde (bir adım sonlu mu) doğrudan çağrılabilir.
 */
export function createClothSolver(mesh: THREE.Mesh, opts: ClothPreviewOptions = {}): Solver {
  const intensity = Math.max(0, Math.min(1, opts.intensity ?? 0.5));
  const geom = mesh.geometry;
  const pos = geom.getAttribute("position") as THREE.BufferAttribute;
  const n = pos.count;

  // Dinlenme konumlarının düz kopyası (geri yükleme için).
  const rest = new Float32Array((pos.array as ArrayLike<number>).length);
  rest.set(pos.array as ArrayLike<number>);

  // Vertex'leri konuma göre kaynakla → grup.
  const groupOf = new Int32Array(n);
  const keyToGroup = new Map<string, number>();
  const groupMembers: number[][] = [];
  for (let i = 0; i < n; i++) {
    const x = pos.getX(i), y = pos.getY(i), z = pos.getZ(i);
    const k = `${x.toFixed(5)},${y.toFixed(5)},${z.toFixed(5)}`;
    let g = keyToGroup.get(k);
    if (g === undefined) { g = keyToGroup.size; keyToGroup.set(k, g); groupMembers.push([]); }
    groupOf[i] = g;
    groupMembers[g].push(i);
  }
  const G = keyToGroup.size;

  // Grup dinlenme konumları + çalışma durumu (mevcut + hız).
  const rx = new Float32Array(G), ry = new Float32Array(G), rz = new Float32Array(G);
  const cx = new Float32Array(G), cy = new Float32Array(G), cz = new Float32Array(G);
  const vx = new Float32Array(G), vy = new Float32Array(G), vz = new Float32Array(G);
  for (let g = 0; g < G; g++) {
    const rep = groupMembers[g][0];
    const x = pos.getX(rep), y = pos.getY(rep), z = pos.getZ(rep);
    rx[g] = cx[g] = x; ry[g] = cy[g] = y; rz[g] = cz[g] = z;
  }

  // En üst %10 Y sabit (askı noktaları).
  let minY = Infinity, maxY = -Infinity;
  for (let g = 0; g < G; g++) { if (ry[g] < minY) minY = ry[g]; if (ry[g] > maxY) maxY = ry[g]; }
  const span = maxY - minY;
  const pinThreshold = maxY - TOP_FRACTION * span;
  const fixed = new Uint8Array(G);
  for (let g = 0; g < G; g++) fixed[g] = ry[g] >= pinThreshold ? 1 : 0;

  // Yay kenarları: üçgen kenarlarından (index'li veya değil), grup çifti başına tek.
  const index = geom.getIndex();
  const triCount = (index ? index.count : n) / 3;
  const seen = new Set<number>();
  const sa: number[] = [], sb: number[] = [], sl: number[] = [];
  const addEdge = (ia: number, ib: number) => {
    let a = groupOf[ia], b = groupOf[ib];
    if (a === b) return;
    if (a > b) { const t = a; a = b; b = t; }
    const key = a * G + b;
    if (seen.has(key)) return;
    seen.add(key);
    const dx = rx[b] - rx[a], dy = ry[b] - ry[a], dz = rz[b] - rz[a];
    sa.push(a); sb.push(b); sl.push(Math.sqrt(dx * dx + dy * dy + dz * dz));
  };
  for (let t = 0; t < triCount; t++) {
    const i0 = index ? index.getX(t * 3) : t * 3;
    const i1 = index ? index.getX(t * 3 + 1) : t * 3 + 1;
    const i2 = index ? index.getX(t * 3 + 2) : t * 3 + 2;
    addEdge(i0, i1); addEdge(i1, i2); addEdge(i2, i0);
  }
  const S = sa.length;

  const fx = new Float32Array(G), fy = new Float32Array(G), fz = new Float32Array(G);
  const grav = GRAVITY * intensity * GRAVITY_SCALE; // erime değil hafif sarkma
  const wind = WIND * intensity;
  let writeCount = 0; // normalleri her NORMALS_EVERY yazımda bir yeniden hesapla

  const step = (dt: number, time: number) => {
    const h = Math.min(Math.max(dt, 1e-4), 1 / 30);
    fx.fill(0); fy.fill(0); fz.fill(0);
    // Dış kuvvetler: kısılmış yerçekimi + hafif rüzgâr sinüsü + dinlenme-konumu çapası.
    // Çapa (REST_K) siluet çökmesini engeller: kumaş "sallanır", "erimez".
    for (let g = 0; g < G; g++) {
      if (fixed[g]) continue;
      fy[g] += grav;
      fx[g] += wind * Math.sin(time * 2 + cy[g] * 3);
      fx[g] += REST_K * (rx[g] - cx[g]);
      fy[g] += REST_K * (ry[g] - cy[g]);
      fz[g] += REST_K * (rz[g] - cz[g]);
    }
    // Yay kuvvetleri (Hooke, dinlenme uzunluğuna doğru).
    for (let s = 0; s < S; s++) {
      const a = sa[s], b = sb[s];
      const dx = cx[b] - cx[a], dy = cy[b] - cy[a], dz = cz[b] - cz[a];
      const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
      if (dist < 1e-6) continue;
      const f = (SPRING_K * (dist - sl[s])) / dist;
      const px = f * dx, py = f * dy, pz = f * dz;
      if (!fixed[a]) { fx[a] += px; fy[a] += py; fz[a] += pz; }
      if (!fixed[b]) { fx[b] -= px; fy[b] -= py; fz[b] -= pz; }
    }
    // Yarı-örtük Euler + sönüm + hız kırpma (NaN/patlama koruması).
    for (let g = 0; g < G; g++) {
      if (fixed[g]) continue;
      let nvx = (vx[g] + fx[g] * h) * DAMPING;
      let nvy = (vy[g] + fy[g] * h) * DAMPING;
      let nvz = (vz[g] + fz[g] * h) * DAMPING;
      const vmag = Math.sqrt(nvx * nvx + nvy * nvy + nvz * nvz);
      if (vmag > MAX_VEL) { const s2 = MAX_VEL / vmag; nvx *= s2; nvy *= s2; nvz *= s2; }
      vx[g] = nvx; vy[g] = nvy; vz[g] = nvz;
      cx[g] += nvx * h; cy[g] += nvy * h; cz[g] += nvz * h;
    }
  };

  const writeBack = () => {
    const arr = pos.array as Float32Array;
    for (let g = 0; g < G; g++) {
      const members = groupMembers[g];
      for (let m = 0; m < members.length; m++) {
        const i = members[m];
        arr[i * 3] = cx[g]; arr[i * 3 + 1] = cy[g]; arr[i * 3 + 2] = cz[g];
      }
    }
    pos.needsUpdate = true;
    // PERFORMANS: computeVertexNormals() 48k vertex'te her karede FPS'i çökertir.
    // Görsel olarak aydınlatma 3 karede bir güncellenmesi fark edilmez → sadece
    // her NORMALS_EVERY yazımda bir hesapla. İlk yazım (writeCount 0) daima hesaplar.
    if (writeCount % NORMALS_EVERY === 0) geom.computeVertexNormals();
    writeCount++;
  };

  const restore = () => {
    (pos.array as Float32Array).set(rest);
    pos.needsUpdate = true;
    geom.computeVertexNormals();
  };

  return { step, writeBack, restore, groupCount: G, springCount: S };
}

// Otomatik durma sinyalini iki kanaldan yayar: (1) onAutoStop callback'i (reason ile),
// (2) "drape:autostop" window CustomEvent'i (detail.reason). Callback GarmentMesh üzerinden
// store'daki drapeEnabled toggle'ını kapatır; window olayı ise DesignerPage'in reason'ı
// (fps vs dense) okuyup doğru uyarıyı göstermesini sağlar (mannequin:loaderror ile aynı köprü).
function signalAutoStop(opts: ClothPreviewOptions, reason: "fps" | "dense") {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new CustomEvent("drape:autostop", { detail: { reason } }));
  }
  opts.onAutoStop?.(reason);
}

/**
 * Gerçek zamanlı önizleme: çözücüyü kurar, rAF döngüsünde adımlar + geri yazar,
 * FPS'i 2 sn pencerede izler (30 altı → otomatik durdur). stop() döndürür:
 * döngüyü iptal eder ve mesh'i dinlenme haline geri yükler.
 */
export function startClothPreview(mesh: THREE.Mesh, opts: ClothPreviewOptions = {}): () => void {
  // ÇOK YOĞUN MESH KORUMASI: her karede kütle-yay çözümü + normal hesabı vertex
  // sayısıyla lineer büyür. 30k üstünde rAF döngüsü ana iş parçacığını kilitler
  // (arayüz donar). Hiç başlatma, hemen onAutoStop çağır → arayüz kullanıcıya
  // "mesh fizik için çok yoğun — görüntü çözünürlüğünü düşür" (drape.tooDense) der.
  const posAttr = mesh.geometry.getAttribute("position") as THREE.BufferAttribute | undefined;
  // Ham vertex sayısı YANILTICI: xatlas yeniden-UV'leme seam'lerde vertexleri
  // çoğaltır (20k yüzlü view'da 30k+ ham vertex — canlı vaka: "Düşük 20k"da bile
  // 'çok yoğun' uyarısı). Kare maliyeti KAYNAKLANMIŞ grup sayısıyla ölçeklenir:
  // çözücüyü kur (tek seferlik ~50ms) ve GRUP sayısına bak. Ham sayı yalnız
  // patolojik durumlara karşı geniş emniyet sınırı.
  if (posAttr && posAttr.count > 150_000) {
    signalAutoStop(opts, "dense");
    return () => {};
  }
  const solver = createClothSolver(mesh, opts);
  if (solver.groupCount > MAX_PHYSICS_VERTS) {
    solver.restore();
    signalAutoStop(opts, "dense");
    return () => {};
  }
  let raf = 0;
  let stopped = false;
  let last = performance.now();
  let windowStart = last;
  let frames = 0;

  const stop = () => {
    if (stopped) return;
    stopped = true;
    if (raf) cancelAnimationFrame(raf);
    solver.restore();
  };

  const loop = (now: number) => {
    if (stopped) return;
    const dt = (now - last) / 1000;
    last = now;
    solver.step(dt, now / 1000);
    solver.writeBack();
    frames++;
    const elapsed = now - windowStart;
    if (elapsed >= 2000) {
      const fps = (frames * 1000) / elapsed;
      frames = 0;
      windowStart = now;
      if (fps < 30) { signalAutoStop(opts, "fps"); stop(); return; }
    }
    raf = requestAnimationFrame(loop);
  };

  // Çözülecek yay yoksa (dejenere geometri) hiç başlama.
  if (solver.springCount === 0) return () => {};
  raf = requestAnimationFrame(loop);
  return stop;
}
