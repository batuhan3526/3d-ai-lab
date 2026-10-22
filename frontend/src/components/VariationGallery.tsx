import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Canvas, useFrame } from "@react-three/fiber";
import { useGLTF, Html } from "@react-three/drei";
import * as THREE from "three";
import {
  batchGenerate, listVariations, addFavorite, removeFavorite, applyVariant,
  type VariationKind, type Variation,
} from "../api/variations";
import type { StyleSource } from "../api/generate";
import { decalUrl } from "../api/generate";
import { savePromptTemplate } from "./PromptLibrary";
import { useT } from "../i18n";

export type GalleryBase = {
  projectId: string;
  prompt: string;
  style?: StyleSource | null;
  gpu?: number;
  promptEnhance?: boolean;
  engineId?: string; // motif motoru (yoksa/"flux-motif" ise gönderilmez → yerel istek aynı)
};

const PRESETS = [4, 9, 20];

const isGlbResult = (p: string | null): boolean => !!p && p.toLowerCase().endsWith(".glb");

// F7: küçük 3D önizleme — variant GLB'sini yükle, orijine ortala + birim küpe
// ölçekle (GLB'lerin ölçeği bilinmediğinden) ve yavaşça Y ekseninde döndür.
// scene.clone(true) ile paylaşılan useGLTF cache'i kirletilmez.
function SpinModel({ src }: { src: string }) {
  const { scene } = useGLTF(src);
  const ref = useRef<THREE.Group>(null);
  const { object, scale } = useMemo(() => {
    const clone = scene.clone(true);
    const box = new THREE.Box3().setFromObject(clone);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z) || 1;
    clone.position.set(-center.x, -center.y, -center.z);
    return { object: clone, scale: 1.7 / maxDim };
  }, [scene]);
  useFrame((_, delta) => {
    if (ref.current) ref.current.rotation.y += delta * 0.5;
  });
  return (
    <group ref={ref} scale={scale}>
      <primitive object={object} />
    </group>
  );
}

// F7: .glb varyantı (drape/upscale/retopo) için gerçek kart — mini 3D önizleme +
// tür etiketi + belirgin "Projeye uygula" butonu.
function GlbVariantCard({
  v, kindLabel, applying, applied, failed, onApply, onFav, t,
}: {
  v: Variation;
  kindLabel: string;
  applying: boolean;
  applied: boolean;
  failed: boolean;
  onApply: () => void;
  onFav: () => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
}) {
  return (
    <div className="col-span-2 rounded-lg border-2 border-transparent bg-zinc-800 overflow-hidden flex flex-col">
      <div className="relative h-40 bg-zinc-900">
        {/* frameloop="always": küçük tuval, yavaş turntable için sürekli kare
            gerekir; her kartın ayrı WebGL renderer'ı var (modal içinde sorun değil). */}
        <Canvas dpr={[1, 1]} frameloop="always" camera={{ position: [0, 0, 2.6], fov: 40 }}>
          <ambientLight intensity={0.8} />
          <directionalLight position={[3, 4, 3]} intensity={1.1} />
          <Suspense
            fallback={<Html center><span className="text-xs text-zinc-400">3D</span></Html>}>
            <SpinModel src={decalUrl(v.project_id, v.result_path!)} />
          </Suspense>
        </Canvas>
        <button
          onClick={(e) => { e.stopPropagation(); onFav(); }}
          className="absolute top-1 right-1 text-lg leading-none">
          {v.favorite ? "⭐" : "☆"}
        </button>
      </div>
      <div className="p-2 flex flex-col gap-1.5 items-center text-center">
        <span className="text-[11px] text-zinc-400">{kindLabel}</span>
        <button
          onClick={(e) => { e.stopPropagation(); onApply(); }}
          disabled={applying}
          className="w-full rounded bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 px-3 py-2 text-sm font-medium">
          {applying
            ? t("quality.applying")
            : applied
              ? t("quality.applied")
              : failed
                ? t("quality.applyFailed")
                : t("quality.applyToProject")}
        </button>
      </div>
    </div>
  );
}

export function VariationGallery({
  kind, base, onSelect, onClose, initialGroupId, onApplied,
}: {
  kind: VariationKind;
  base: GalleryBase;
  onSelect: (v: Variation) => void;
  onClose: () => void;
  // F7: drape/upscale gibi hazır bir varyasyon grubunu doğrudan göster (batch
  // üretmeden). Verilirse üstteki "üret" satırı gizlenir, grup hemen listelenir.
  initialGroupId?: string;
  // T4: 3D varyant projeye uygulandığında (mesh.glb değişti) çağrılır — Designer
  // eski mesh'in drei useGLTF önbelleğini boşaltır (GPU tamponları serbest kalsın).
  onApplied?: () => void;
}) {
  const { t } = useT();
  const qc = useQueryClient();
  const [count, setCount] = useState(9);
  const [groupId, setGroupId] = useState<string | null>(initialGroupId ?? null);
  const [selected, setSelected] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  // Batch üret/yeniden üret yalnız 2D motif/stil için anlamlı; drape/upscale
  // sonuçları offline worker'dan gelir (initialGroupId ile hazır listelenir).
  const canBatch = kind === "motif" || kind === "style";

  // F7: 3D varyant türünün kullanıcı-dostu etiketi.
  const kindLabel = (k: string): string =>
    k === "drape" ? t("quality.kindDrape")
      : k === "fit" ? t("mannequin.fitKind")
      : k === "upscale" ? t("quality.kindUpscale")
        : k === "retopo" ? t("quality.kindRetopo")
          : t("quality.apply3dVariant");

  // F7: 3D varyantı (drape/upscale .glb) projenin mesh.glb'sinin üzerine yaz.
  // Başarıda: proje/mesh sorgularını tazele, kullanıcıya mesh'in değiştiğini
  // söyleyen toast göster, sonra galeriyi kapat → Designer mesh'i görünür yeniler.
  const apply = useMutation({
    mutationFn: (id: string) => applyVariant(id),
    onSuccess: (r) => {
      // T4: sorgu geçersizleştirmeden ÖNCE eski mesh önbelleğini boşalt; mesh URL
      // aynı kaldığından (yalnız içerik değişir) drei cache temizlenmezse eski
      // GPU tamponları takılı kalır ve yeni mesh yüklenmez.
      onApplied?.();
      qc.invalidateQueries({ queryKey: ["project", r.project_id] });
      qc.invalidateQueries({ queryKey: ["project", base.projectId] });
      qc.invalidateQueries({ queryKey: ["mesh", r.project_id] });
      setToast(t("quality.applyReplacedToast"));
      window.setTimeout(() => onClose(), 1800);
    },
  });

  const run = useMutation({
    mutationFn: () =>
      batchGenerate({
        kind, project_id: base.projectId, count,
        prompt: base.prompt, style: base.style ?? null,
        // gpu verilmezse alanı hiç gönderme → gateway settings.default_gpu doldurur
        // (tek-GPU sözleşmesi; sabit 1 fallback'i sözleşmeyi deliyordu, 2026-07-12).
        ...(base.gpu !== undefined ? { gpu: base.gpu } : {}),
        prompt_enhance: base.promptEnhance ?? true,
        ...(base.engineId && base.engineId !== "flux-motif" ? { engine_id: base.engineId } : {}),
      }),
    onSuccess: (r) => { setGroupId(r.group_id); setSelected(null); },
  });

  // Akış: grup varken 1.5sn'de bir listele (SUBMITTED kaldıkça)
  const { data: variations = [] } = useQuery({
    queryKey: ["variations", groupId],
    queryFn: () => listVariations(groupId!),
    enabled: !!groupId,
    refetchInterval: (q) => {
      const rows = (q.state.data as Variation[] | undefined) ?? [];
      const pending = rows.length === 0 || rows.some((v) => v.status === "SUBMITTED");
      return pending ? 1500 : false;
    },
  });

  // T4: drei useGLTF her yüklenen URL'i süresiz cache'ler. Modal kapanınca/unmount'ta
  // yüklenmiş varyant .glb önizlemelerinin GPU tamponlarını boşalt (uzun oturumda
  // galeri açıp kapatmak RAM/VRAM şişiriyordu). Yüklenen URL'leri bir ref'te biriktir.
  const previewGlbUrls = useRef<Set<string>>(new Set());
  useEffect(() => {
    variations.forEach((v) => {
      if (v.status === "SUCCESS" && isGlbResult(v.result_path)) {
        previewGlbUrls.current.add(decalUrl(v.project_id, v.result_path!));
      }
    });
  }, [variations]);
  useEffect(() => () => {
    previewGlbUrls.current.forEach((u) => useGLTF.clear(u));
  }, []);

  const fav = useMutation({
    mutationFn: ({ id, on }: { id: string; on: boolean }) =>
      on ? addFavorite(id) : removeFavorite(id),
  });

  const picked = variations.find((v) => v.id === selected) ?? null;

  // C2: seçili varyasyonun seed+prompt'unu şablon kütüphanesine kaydet.
  const saveSeed = useMutation({
    mutationFn: () => {
      if (!picked) return Promise.reject(new Error("no selection"));
      const promptText = picked.prompt ?? base.prompt;
      const title = window.prompt(t("quality.tplNamePrompt"), promptText.slice(0, 40).trim());
      if (title === null || !title.trim()) return Promise.reject(new Error("cancelled"));
      return savePromptTemplate({
        title: title.trim(), prompt: promptText, seed: picked.seed,
      });
    },
  });

  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6"
         onClick={onClose}>
      <div className="bg-zinc-900 rounded-2xl w-full max-w-5xl max-h-[90vh] flex flex-col overflow-hidden"
           onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between px-5 py-3 border-b border-zinc-800">
          <span className="font-medium">{t("variation.title")} {variations.length ? `(${variations.length})` : ""}</span>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-200 text-xl">×</button>
        </header>

        {/* F7: uygulama başarısı toast'ı — mesh değişti + görünüm yenilenecek. */}
        {toast && (
          <div className="px-5 py-2 bg-emerald-700/30 border-b border-emerald-700/50 text-emerald-200 text-sm text-center">
            {toast}
          </div>
        )}

        {/* Adet seçici (yalnız 2D motif/stil batch üretimi için) */}
        {canBatch && (
          <div className="flex items-center gap-2 px-5 py-3 border-b border-zinc-800">
            <span className="text-sm text-zinc-400">{t("variation.count")}</span>
            {PRESETS.map((n) => (
              <button key={n} onClick={() => setCount(n)}
                className={`rounded px-3 py-1 text-sm ${count === n ? "bg-violet-600" : "bg-zinc-700"}`}>{n}</button>
            ))}
            <input type="number" min={1} max={20} value={count}
              onChange={(e) => setCount(Math.max(1, Math.min(20, parseInt(e.target.value || "1", 10))))}
              className="w-16 bg-zinc-800 rounded px-2 py-1 text-sm" />
            <button onClick={() => run.mutate()} disabled={run.isPending}
              className="ml-auto bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg px-4 py-1.5 text-sm">
              {run.isPending ? t("variation.starting") : groupId ? t("variation.regenerate") : t("variation.generate")}
            </button>
          </div>
        )}

        {/* Izgara */}
        <div className="flex-1 overflow-y-auto p-5">
          {canBatch && !groupId && <p className="text-zinc-500 text-sm">{t("variation.hint")}</p>}
          <div className="grid grid-cols-4 gap-3">
            {variations.map((v) =>
              v.status === "SUCCESS" && isGlbResult(v.result_path) ? (
                // F7: 3D varyant → gerçek kart (mini 3D önizleme + tür + Projeye uygula).
                <GlbVariantCard
                  key={v.id}
                  v={v}
                  t={t}
                  kindLabel={kindLabel(v.kind)}
                  applying={apply.variables === v.id && apply.isPending}
                  applied={apply.variables === v.id && apply.isSuccess}
                  failed={apply.variables === v.id && apply.isError}
                  onApply={() => {
                    if (window.confirm(t("quality.applyConfirm"))) apply.mutate(v.id);
                  }}
                  onFav={() => { fav.mutate({ id: v.id, on: !v.favorite }); v.favorite = !v.favorite; }}
                />
              ) : (
                <div key={v.id}
                  onClick={() => v.status === "SUCCESS" && setSelected(v.id)}
                  className={`relative aspect-square rounded-lg border-2 bg-zinc-800 flex items-center justify-center overflow-hidden cursor-pointer
                    ${selected === v.id ? "border-violet-500" : "border-transparent"}`}>
                  {v.status === "SUCCESS" && v.result_path ? (
                    <img src={decalUrl(v.project_id, v.result_path)} alt=""
                         className="w-full h-full object-contain" />
                  ) : v.status === "FAILURE" ? (
                    <span className="text-red-400 text-xs">{t("variation.error")}</span>
                  ) : (
                    <span className="text-zinc-500 text-xs animate-pulse">{t("variation.generating")}</span>
                  )}
                  {v.status === "SUCCESS" && (
                    <button
                      onClick={(e) => { e.stopPropagation(); fav.mutate({ id: v.id, on: !v.favorite }); v.favorite = !v.favorite; }}
                      className="absolute top-1 right-1 text-lg leading-none">
                      {v.favorite ? "⭐" : "☆"}
                    </button>
                  )}
                  {selected === v.id && <span className="absolute bottom-1 left-1 text-violet-400 text-sm">✓</span>}
                </div>
              )
            )}
          </div>
        </div>

        {/* Alt bar */}
        <footer className="flex items-center justify-end gap-3 px-5 py-3 border-t border-zinc-800">
          {picked && (
            <button onClick={() => saveSeed.mutate()} disabled={saveSeed.isPending}
              className="mr-auto text-sm text-violet-400 hover:text-violet-300 disabled:opacity-40">
              {saveSeed.isSuccess ? t("quality.tplSaved") : `💾 ${t("quality.tplSaveSeed")}`}
            </button>
          )}
          <button onClick={onClose} className="text-zinc-400 text-sm">{t("variation.cancel")}</button>
          <button disabled={!picked}
            onClick={() => { if (picked) { onSelect(picked); onClose(); } }}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg px-5 py-1.5 text-sm">
            {t("variation.continue")}
          </button>
        </footer>
      </div>
    </div>
  );
}
