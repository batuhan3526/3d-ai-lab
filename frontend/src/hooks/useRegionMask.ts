import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

/** F5 v2: UV-uzayı bölge maskesi (beyaz = yeniden boya). Konvansiyon:
 * pixel = (u·S, v·S), flip YOK (InTeX hizalama testiyle doğrulandı).
 * Fırça 3B uzayda çalışır: GarmentMesh yarıçap içindeki üçgenleri bulur,
 * burada UV üçgenleri olarak doldurulur. (Eski UV-disk yaklaşımı xatlas UV
 * adalarında ada sınırından taşıp alakasız bölgeleri boyuyordu.)
 * Aynı canvas, mesh üzerinde işaretlenen yeri göstermek için CanvasTexture
 * olarak da dışa verilir (flipY=false — çizim konvansiyonuyla aynı). */
export function useRegionMask(size = 1024) {
  const [hasMask, setHasMask] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);

  const { canvas, maskTexture } = useMemo(() => {
    const c = document.createElement("canvas");
    c.width = size;
    c.height = size;
    // willReadFrequently: fırça her harekette getImageData/putImageData yapar;
    // bu bayrak olmadan Canvas2D GPU'ya gidip her okumada stall ediyor (~saniyeler).
    const ctx = c.getContext("2d", { willReadFrequently: true })!;
    ctx.fillStyle = "black";
    ctx.fillRect(0, 0, size, size);
    const t = new THREE.CanvasTexture(c);
    t.flipY = false;
    return { canvas: c, maskTexture: t };
  }, [size]);

  useEffect(() => () => maskTexture.dispose(), [maskTexture]);

  const getCanvas = useCallback(() => canvas, [canvas]);

  // Önizleme (küçük thumbnail) trailing-throttle: toDataURL 1024² canvas'ta
  // GPU ReadPixels-stall yapar; her fırça hareketinde çağrılırsa boyama kasar.
  // Son darbeden ~180ms sonra bir kez üret → maske doğru, stall yok.
  const previewTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const schedulePreview = useCallback(() => {
    if (previewTimer.current) clearTimeout(previewTimer.current);
    previewTimer.current = setTimeout(() => {
      setPreview(canvas.toDataURL("image/png"));
    }, 180);
  }, [canvas]);
  useEffect(() => () => { if (previewTimer.current) clearTimeout(previewTimer.current); }, []);

  /** Texel-hassas fırça: her üçgenin UV bbox'ındaki texel'ler için barisentrik
   * koordinatla 3B konum bulunur, fırça küresinin GERÇEKTEN içindeyse boyanır.
   * Canvas fill/stroke KULLANILMAZ: AA ve kontur, UV'de komşu (3B'de alakasız)
   * chart'lara taşıp InTeX'in oraları da boyamasına yol açıyordu; üçgen-bütünü
   * doldurmak da daireyi taşırıyordu. tris elemanı: [u0,v0,u1,v1,u2,v2, x0..z2]. */
  const paintTriangles = useCallback(
    (tris: number[][], center: [number, number, number], radius: number,
     hitUv?: [number, number]) => {
      if (!tris.length) return;
      const c = getCanvas();
      const ctx = c.getContext("2d")!;
      let minX = size, minY = size, maxX = 0, maxY = 0;
      for (const t of tris)
        for (let k = 0; k < 3; k++) {
          const x = t[k * 2] * size, y = t[k * 2 + 1] * size;
          if (x < minX) minX = x; if (x > maxX) maxX = x;
          if (y < minY) minY = y; if (y > maxY) maxY = y;
        }
      minX = Math.max(0, Math.floor(minX)); minY = Math.max(0, Math.floor(minY));
      maxX = Math.min(size - 1, Math.ceil(maxX)); maxY = Math.min(size - 1, Math.ceil(maxY));
      if (maxX < minX || maxY < minY) return;
      const bw = maxX - minX + 1, bh = maxY - minY + 1;
      const img = ctx.getImageData(minX, minY, bw, bh);
      const data = img.data;
      const r2 = radius * radius;
      const [cx, cy, cz] = center;
      let painted = false;
      const setPx = (px: number, py: number) => {
        const i = ((py - minY) * bw + (px - minX)) * 4;
        data[i] = data[i + 1] = data[i + 2] = 255; data[i + 3] = 255;
        painted = true;
      };
      for (const t of tris) {
        const ax = t[0] * size, ay = t[1] * size, bx = t[2] * size, by = t[3] * size,
              qx = t[4] * size, qy = t[5] * size;
        const den = (by - qy) * (ax - qx) + (qx - bx) * (ay - qy);
        if (Math.abs(den) < 1e-12) continue; // UV'de dejenere üçgen
        const tx0 = Math.max(minX, Math.floor(Math.min(ax, bx, qx)));
        const tx1 = Math.min(maxX, Math.ceil(Math.max(ax, bx, qx)));
        const ty0 = Math.max(minY, Math.floor(Math.min(ay, by, qy)));
        const ty1 = Math.min(maxY, Math.ceil(Math.max(ay, by, qy)));
        for (let py = ty0; py <= ty1; py++)
          for (let px = tx0; px <= tx1; px++) {
            const sx = px + 0.5, sy = py + 0.5;
            const w0 = ((by - qy) * (sx - qx) + (qx - bx) * (sy - qy)) / den;
            const w1 = ((qy - ay) * (sx - qx) + (ax - qx) * (sy - qy)) / den;
            const w2 = 1 - w0 - w1;
            if (w0 < -1e-3 || w1 < -1e-3 || w2 < -1e-3) continue; // üçgen dışı
            const dx = w0 * t[6] + w1 * t[9] + w2 * t[12] - cx;
            const dy = w0 * t[7] + w1 * t[10] + w2 * t[13] - cy;
            const dz = w0 * t[8] + w1 * t[11] + w2 * t[14] - cz;
            if (dx * dx + dy * dy + dz * dz > r2) continue; // daire dışı
            setPx(px, py);
          }
      }
      // çok küçük fırça/texel uyumsuzluğunda en az isabet texel'i boyansın
      if (!painted && hitUv) {
        const px = Math.min(size - 1, Math.max(0, Math.floor(hitUv[0] * size)));
        const py = Math.min(size - 1, Math.max(0, Math.floor(hitUv[1] * size)));
        if (px >= minX && px <= maxX && py >= minY && py <= maxY) setPx(px, py);
        else { ctx.fillStyle = "white"; ctx.fillRect(px, py, 1, 1); painted = true; }
      }
      if (!painted) return;
      ctx.putImageData(img, minX, minY);
      maskTexture.needsUpdate = true;
      setHasMask(true);
      schedulePreview();
    },
    [getCanvas, maskTexture, size, schedulePreview],
  );

  const clear = useCallback(() => {
    if (previewTimer.current) clearTimeout(previewTimer.current); // bekleyen önizleme bayat dönmesin
    const c = getCanvas();
    const ctx = c.getContext("2d")!;
    ctx.fillStyle = "black";
    ctx.fillRect(0, 0, size, size);
    maskTexture.needsUpdate = true;
    setHasMask(false);
    setPreview(null);
  }, [getCanvas, maskTexture, size]);

  const toBlob = useCallback(
    () =>
      new Promise<Blob>((resolve, reject) => {
        getCanvas().toBlob((b) => (b ? resolve(b) : reject(new Error("maske blob hatası"))), "image/png");
      }),
    [getCanvas],
  );

  return { paintTriangles, clear, toBlob, hasMask, preview, maskTexture };
}
