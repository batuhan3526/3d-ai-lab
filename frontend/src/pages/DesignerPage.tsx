import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { getProject, updateProject, meshUrl } from "../api/projects";
import { applyVariant } from "../api/variations";
import { getManifest } from "../api/templates";
import { assetUrl, api, projectFileUrl } from "../api/client";
import { ThreeCanvas } from "../components/ThreeCanvas";
import { ColorPicker } from "../components/ColorPicker";
import { DecalUploader } from "../components/DecalUploader";
import { ExportMenu } from "../components/ExportMenu";
import { uploadThumbnail } from "../api/projects";
import { retexture, retextureImage, refineHi3d, generateMotif, generateMotifBake, getJob, decalUrl, DEFAULT_MOTIF_ENGINE, type StyleSource, type PbrChannels } from "../api/generate";
import { listEngines } from "../api/engines";
import { generateTile } from "../api/generate";
import { DecalEditPanel } from "../components/DecalEditPanel";
import { StyleTransferPanel } from "../components/StyleTransferPanel";
import { useDesign } from "../store/design";
import { uuid } from "../lib/uuid";
import { recordTurntable, downloadBlob, convertTurntableToMp4 } from "../lib/recordTurntable";
import { ARModal } from "../components/ARModal";
import { PrintPrepModal } from "../components/PrintPrepModal";
import { SewingPatternModal } from "../components/SewingPatternModal";
import { useRegionMask } from "../hooks/useRegionMask";
import { VariationGallery, type GalleryBase } from "../components/VariationGallery";
import type { Variation, VariationKind } from "../api/variations";
import { VersionPanel } from "../components/VersionPanel";
import { CompareModal } from "../components/CompareModal";
import { LibraryModal } from "../components/LibraryModal";
import { ScenePanel, useViewFaces } from "../components/ScenePanel";
import { MetricsPanel } from "../components/MetricsPanel";
import type { EnvPreset } from "../components/ThreeCanvas";
import { duplicateProject } from "../api/projects";
import { restoreVersion, createVersion, type Version } from "../api/versions";
import * as THREE from "three";
import { useGLTF } from "@react-three/drei";
import { useT } from "../i18n";
import { FabricSelect } from "../components/FabricPresetPicker";
import { fabricIdFromMaterial } from "../api/fabrics";
import type { BodyInput } from "../api/mannequins";
import { BodyInputs, BODY_DEFAULTS, bodyValid } from "../components/BodyInputs";
import { MeasurementsTable } from "../components/MeasurementsTable";

// Blender kumaş simülasyonu (POST /projects/{id}/drape) arayüzü 2026-07-07'de
// kullanıcı kararıyla gizlendi (gövdesiz askı sim "giyilmiş" sonuç vermiyor).
// Kalıptan gerçek dikiş artık Atölye'de (/atelier → 3D'de dik). Bölüm kumaş
// seçiciyle (F4 fabric_id) hazır; tekrar açmak için bu bayrağı true yapın.
const SHOW_BLENDER_DRAPE = false;

type MannequinEntry = {
  id: string;
  label: string;
  file: string;
  pose: "T" | "A";
  license: string;
  source_url: string;
  available?: boolean;   // T6: GLB diskte var mı (backend canlı hesaplar) — false → seçilemez
};

export default function DesignerPage() {
  const { t } = useT();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const captureRef = useRef<(() => string) | null>(null);
  const exportRef = useRef<(() => Promise<ArrayBuffer>) | null>(null);
  const paneRef = useRef<HTMLDivElement>(null);   // 70% R3F pane (canvas lookup)
  const [recording, setRecording] = useState(false);
  const [videoMsg, setVideoMsg] = useState<string | null>(null);
  const [arOpen, setArOpen] = useState(false);   // Task E2: AR modalı açık mı
  const [printOpen, setPrintOpen] = useState(false);   // Task E3: baskı-hazırla modalı
  const [sewingOpen, setSewingOpen] = useState(false);   // Task BATCH-G: dikiş kalıbı modalı

  const projectQuery = useQuery({ queryKey: ["project", id], queryFn: () => getProject(id!) });
  const project = projectQuery.data;
  const { data: manifest } = useQuery({ queryKey: ["manifest"], queryFn: getManifest });

  // Geçersiz/silinmiş id (getProject 404/hata) -> dashboard'a dön.
  useEffect(() => {
    if (projectQuery.isError) navigate("/dashboard");
  }, [projectQuery.isError, navigate]);

  const load = useDesign((s) => s.load);
  const dirty = useDesign((s) => s.dirty);
  const markSaved = useDesign((s) => s.markSaved);
  const toCustomizations = useDesign((s) => s.toCustomizations);
  const undo = useDesign((s) => s.undo);
  const redo = useDesign((s) => s.redo);
  const canUndo = useDesign((s) => s.past.length > 0);
  const canRedo = useDesign((s) => s.future.length > 0);
  const storeLoad = useDesign((s) => s.load);
  const [compareVersion, setCompareVersion] = useState<Version | null>(null);
  const initialCustRef = useRef<string | null>(null);   // açılış customizations (auto snapshot)
  const autoSnapDoneRef = useRef(false);

  // Statik manken (Task D1): manifest + panel + hizalama modu. Manken state'i
  // design store'da tutulur ve mevcut save hattıyla (toCustomizations) kaydedilir.
  const mannequin = useDesign((s) => s.mannequin);
  const selectMannequin = useDesign((s) => s.selectMannequin);
  const setMannequinVisible = useDesign((s) => s.setMannequinVisible);
  const setMannequinOpacity = useDesign((s) => s.setMannequinOpacity);
  const resetMannequinTransform = useDesign((s) => s.resetMannequinTransform);
  const [aligning, setAligning] = useState(false);
  // F3: manken GLB yüklenemezse (dosya eksik/bozuk) panelde görünür amber uyarı.
  // Mannequin hata sınırı ThreeCanvas arası prop threading yerine window olayı
  // yayar (ThreeCanvas bu agent'ın dosya kümesinde değil); burada dinlenir.
  const [mannequinError, setMannequinError] = useState(false);

  // Hafif drape (Task D2): önizleme fiziği toggle + şiddet. Transient store durumu
  // (kaydedilmez). Çözücü GarmentMesh içinde store'dan okunur; FPS düşünce store'daki
  // drapeAutoStop() çağrılır → toggle kapanır + drapeAutoStopped uyarısı görünür.
  const drapeEnabled = useDesign((s) => s.drapeEnabled);
  const drapeIntensity = useDesign((s) => s.drapeIntensity);
  const drapeAutoStopped = useDesign((s) => s.drapeAutoStopped);
  const setDrapeEnabled = useDesign((s) => s.setDrapeEnabled);
  // Otomatik durma sebebi (fps vs dense). clothPreview "drape:autostop" window olayıyla
  // yayar; store'daki drapeAutoStopped (GarmentMesh üzerinden) yalnız "durdu"yu bilir,
  // sebebi bilmez. dense → yoğun-mesh yönlendirmesi, fps → genel performans uyarısı.
  const [drapeAutoStopReason, setDrapeAutoStopReason] = useState<"fps" | "dense" | null>(null);
  const setDrapeIntensity = useDesign((s) => s.setDrapeIntensity);
  // Blender drape (SHOW_BLENDER_DRAPE): kumaş seçimi — boşsa malzeme paneli kumaş
  // hazır ayarı, o da yoksa sunucu varsayılanı (denim = eski davranış).
  const designMaterial = useDesign((s) => s.material);
  const [drapeFabric, setDrapeFabric] = useState<string | null>(null);
  const [drapeSimBusy, setDrapeSimBusy] = useState(false);
  const [drapeSimMsg, setDrapeSimMsg] = useState<string | null>(null);
  const [fitBusy, setFitBusy] = useState(false);
  const [fitMsg, setFitMsg] = useState<string | null>(null);
  // "Ölçülerimle giydir": katlanır mini form (backend bu ölçüde mankeni bulur/üretir).
  const [bodyDressOpen, setBodyDressOpen] = useState(false);
  const [dressBody, setDressBody] = useState<BodyInput>(BODY_DEFAULTS.female);
  // C Real-ESRGAN doku netleştirme: mesh dokusunu upscale et → yeni varyant.
  const [upscaleBusy, setUpscaleBusy] = useState(false);
  const [upscaleMsg, setUpscaleMsg] = useState<string | null>(null);
  const { data: mannequins = [] } = useQuery({
    queryKey: ["mannequins"],
    queryFn: () => api<MannequinEntry[]>("/templates/mannequins"),
  });

  const [pendingImage, setPendingImage] = useState<string | null>(null);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [env, setEnv] = useState<EnvPreset>("city");
  const [autoRotate, setAutoRotate] = useState(false);
  // F1: turntable dönüş hızı (bir tam tur için saniye). Kayıt süresi = tur × bu değer.
  const [turnSeconds, setTurnSeconds] = useState(12);
  const [canvasReady, setCanvasReady] = useState(false);
  const [retexturePrompt, setRetexturePrompt] = useState("");
  const addDecal = useDesign((s) => s.addDecal);

  const selectedId = useDesign((s) => s.selectedId);
  const decalsList = useDesign((s) => s.decals);
  const updateDecal = useDesign((s) => s.updateDecal);
  const [moveMode, setMoveMode] = useState(false);
  const [tiling, setTiling] = useState<{ repeat: number } | null>(null);

  // Tiling/taşıma kaynağı: seçili decal'in sunucu motifi (data-uri yüklemeler tiling'e uygun değil)
  const selDecal = decalsList.find((d) => d.id === selectedId) ?? null;
  const selMotif = (() => {
    const img = selDecal?.image ?? "";
    const m = img.match(/\/projects\/([^/]+)\/(decals\/.+)$/);
    return m ? { projectId: m[1], rel: m[2], url: img } : null;
  })();

  // F5 v2: bölge işaretleme (3D fırça → UV maske → sadece o bölgeyi yeniden dokula)
  const [paintMode, setPaintMode] = useState(false);
  const [brush, setBrush] = useState(0.05); // fırça yarıçapı / model bounding-sphere yarıçapı oranı
  const [styleSource, setStyleSource] = useState<StyleSource | null>(null); // stil transferi kaynağı
  // Motif motoru: yerel flux-motif (varsayılan) + bulut "motif" motorları (anahtarsızsa kilitli).
  const [motifEngine, setMotifEngine] = useState<string>(DEFAULT_MOTIF_ENGINE);
  const { data: allEngines = [] } = useQuery({ queryKey: ["engines"], queryFn: listEngines, retry: 1 });
  const motifEngines = allEngines
    // /generate/motif yalnız flux-motif + bulut motif motorlarını kabul eder (ör. meshflow-guided değil).
    .filter((e) => (e.capabilities ?? []).includes("motif") && (e.id === DEFAULT_MOTIF_ENGINE || e.cloud))
    .sort((a, b) => (a.id === DEFAULT_MOTIF_ENGINE ? -1 : b.id === DEFAULT_MOTIF_ENGINE ? 1 : 0));
  const motifEngineSpec = motifEngines.find((e) => e.id === motifEngine);
  const [gallery, setGallery] = useState<{ kind: VariationKind; base: GalleryBase; pose: ReturnType<typeof computePose>; groupId?: string } | null>(null);
  const { paintTriangles, clear, hasMask, preview, maskTexture } = useRegionMask(1024);
  // BATCH-F: PBR kanal fırçası. Albedo = mevcut bölge maskesi (motif/retexture).
  // Roughness/Metallic ayrı UV-uzayı canvas katmanları (0-1 değer slider'ı).
  const roughMask = useRegionMask(1024);
  const metalMask = useRegionMask(1024);
  const [pbrChannel, setPbrChannel] = useState<"albedo" | "roughness" | "metallic">("albedo");
  const [roughValue, setRoughValue] = useState(0.5);
  const [metalValue, setMetalValue] = useState(0.5);

  // Aktif kanala göre fırça hedefi (Albedo → bölge maskesi, R/M → kanal katmanı).
  const activePaint = useCallback(
    (tris: number[][], center: [number, number, number], radius: number, hitUv?: [number, number]) => {
      if (pbrChannel === "roughness") roughMask.paintTriangles(tris, center, radius, hitUv);
      else if (pbrChannel === "metallic") metalMask.paintTriangles(tris, center, radius, hitUv);
      else paintTriangles(tris, center, radius, hitUv);
    },
    [pbrChannel, roughMask.paintTriangles, metalMask.paintTriangles, paintTriangles],
  );
  const activeMaskTexture =
    pbrChannel === "roughness" ? roughMask.maskTexture
      : pbrChannel === "metallic" ? metalMask.maskTexture
        : maskTexture;

  // Kanal katmanını (beyaz=boyalı) → gri=değer + alpha=maske dataURL'ine kodla
  // (worker gri değeri kanal değerine, alpha'yı boyalı maskeye çevirir). Boyanmamışsa undefined.
  const encodeChannel = useCallback(
    (mask: typeof roughMask, value: number): string | undefined => {
      if (!mask.hasMask) return undefined;
      const canvas = mask.maskTexture.image as HTMLCanvasElement;
      const S = canvas.width;
      const src = canvas.getContext("2d")!.getImageData(0, 0, S, S);
      const out = document.createElement("canvas");
      out.width = S; out.height = S;
      const octx = out.getContext("2d")!;
      const dst = octx.createImageData(S, S);
      const g = Math.round(Math.min(1, Math.max(0, value)) * 255);
      for (let i = 0; i < src.data.length; i += 4) {
        if (src.data[i] > 127) { // boyalı texel (beyaz)
          dst.data[i] = dst.data[i + 1] = dst.data[i + 2] = g;
          dst.data[i + 3] = 255;
        } // boyanmamış: alpha 0 (şeffaf) kalır
      }
      octx.putImageData(dst, 0, 0);
      return out.toDataURL("image/png");
    },
    [],
  );

  const retextureMut = useMutation({
    mutationFn: () => retexture(id!, retexturePrompt, true),
    onSuccess: (r) => navigate(`/progress/${r.job_id}?project=${r.project_id}`),
  });

  const [imageTexFile, setImageTexFile] = useState<File | null>(null);
  const imageTexMut = useMutation({
    mutationFn: () => retextureImage(id!, imageTexFile),
    onSuccess: (r) => navigate(`/progress/${r.job_id}?project=${r.project_id}`),
  });

  const hi3dMut = useMutation({
    mutationFn: () => refineHi3d(id!),
    onSuccess: (r) => navigate(`/progress/${r.job_id}?project=${r.project_id}`),
  });

  // Motif decal: fırça her dokunduğunda DÜNYA noktası+normali biriktir → merkez/uzanım hesapla.
  const marks = useRef<{ pts: number[][]; normals: number[][] }>({ pts: [], normals: [] });
  const handleMark = (point: [number, number, number], normal: [number, number, number]) => {
    marks.current.pts.push(point);
    marks.current.normals.push(normal);
  };
  const clearMarks = () => { clear(); roughMask.clear(); metalMask.clear(); marks.current = { pts: [], normals: [] }; };

  // İşaretli darbelerden poz: merkez (centroid), normal (ortalama), ölçek (uzanım çapı).
  // Hem decal (motif ekle) hem bake (dokuya işle) aynı pozu kullanır → ekranda gördüğün yer.
  function computePose(): { center: [number, number, number]; normal: [number, number, number]; scale: number } | null {
    const { pts, normals } = marks.current;
    if (!pts.length) return null;
    const c: [number, number, number] = [0, 0, 0];
    pts.forEach((p) => { c[0] += p[0]; c[1] += p[1]; c[2] += p[2]; });
    c[0] /= pts.length; c[1] /= pts.length; c[2] /= pts.length;
    const n = new THREE.Vector3();
    normals.forEach((nn) => n.add(new THREE.Vector3(nn[0], nn[1], nn[2])));
    if (n.lengthSq() < 1e-6) n.set(0, 0, 1); else n.normalize();
    let r = 0;
    pts.forEach((p) => { const d = Math.hypot(p[0] - c[0], p[1] - c[1], p[2] - c[2]); if (d > r) r = d; });
    return { center: c, normal: [n.x, n.y, n.z], scale: Math.max(r * 2, 0.08) };
  }

  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  // Motif EKLE (çıkartma/decal): FLUX motif → şeffaf PNG → işaretli yere decal. Inline poll, sayfada kalır.
  const motifMut = useMutation({
    mutationFn: async () => {
      const pose = computePose();
      if (!pose) throw new Error(t("designer.markFirst"));
      const { job_id } = await generateMotif(id!, retexturePrompt, true, styleSource, undefined, motifEngine);
      let job = await getJob(job_id);
      for (let i = 0; i < 600 && job.state !== "SUCCESS" && job.state !== "FAILURE"; i++) {
        await sleep(1500); job = await getJob(job_id);
      }
      if (job.state !== "SUCCESS" || !job.decal_path) throw new Error(job.error || t("designer.motifFailed"));
      return { relPath: job.decal_path, pose };
    },
    onSuccess: ({ relPath, pose }) => {
      const q = new THREE.Quaternion().setFromUnitVectors(
        new THREE.Vector3(0, 0, 1), new THREE.Vector3(...pose.normal));
      const e = new THREE.Euler().setFromQuaternion(q);
      addDecal({
        id: uuid(),
        image: decalUrl(id!, relPath),
        position: pose.center,
        rotation: [e.x, e.y, e.z],
        scale: pose.scale,
      });
      clearMarks();
      setPaintMode(false);
    },
  });

  // Varyasyon galerisi: pozu şimdi yakala (işaretler galeri açıkken değişmesin), galeriyi aç.
  function openVariationGallery() {
    const pose = computePose();
    if (!pose) return;
    const useStyle = !!styleSource;
    setGallery({
      kind: useStyle ? "style" : "motif",
      base: {
        projectId: id!,
        prompt: retexturePrompt,
        style: useStyle ? styleSource : null,
        engineId: motifEngine,
      },
      pose,
    });
  }

  // Galeride seçilen varyasyonu decal olarak işaretli yere uygula (motifMut.onSuccess ile aynı poz mantığı).
  function applyVariation(v: Variation) {
    // 3D varyant (drape/upscale .glb) decal olarak eklenmez; galeri içindeki
    // "Projeye uygula" butonu onu doğrudan mesh.glb üzerine yazar.
    if (!gallery?.pose || !v.result_path || v.result_path.toLowerCase().endsWith(".glb")) return;
    const pose = gallery.pose;
    const q = new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 0, 1), new THREE.Vector3(...pose.normal));
    const e = new THREE.Euler().setFromQuaternion(q);
    addDecal({
      id: uuid(),
      image: decalUrl(v.project_id, v.result_path),
      position: pose.center,
      rotation: [e.x, e.y, e.z],
      scale: pose.scale,
    });
    clearMarks();
    setPaintMode(false);
  }

  // F7: drape/upscale işini enqueue et → job'ı poll et → SUCCESS'te sonuç
  // varyasyonunu galeride aç (kullanıcı "hiçbir şey olmadı" görmesin). İş
  // sürerken buton busy kalır; SUCCESS'te galeri + hazır mesajı, FAILURE'da hata.
  // Mankene giydir: (kaydedilmemiş değişiklik varsa önce kaydet) → otomatik hiza + kol
  // pozu + oturtma işi → sonucu uygula (mesh yedeklenir) → projeyi + pozlu mankeni yükle.
  // opts: seçili manken (mannequin_id) YA DA ölçüler (body). Sonuç (pozlu manken + ölçüler)
  // backend'de customizations'a yazılır; getProject + setQueryData ile terzi tablosu da tazelenir.
  async function runDress(opts: { mannequin_id?: string; body?: BodyInput }) {
    if (!opts.mannequin_id && !opts.body) return;
    setFitBusy(true);
    setFitMsg(t("quality.jobRunning"));
    try {
      if (dirty) { await updateProject(id!, { customizations: toCustomizations() }); markSaved(); }
      const res = await api<{ job_id: string; variation_id: string }>(`/projects/${id}/fit`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(opts),
      });
      let job = await getJob(res.job_id);
      for (let i = 0; i < 400 && job.state !== "SUCCESS" && job.state !== "FAILURE"; i++) {
        await sleep(1500); job = await getJob(res.job_id);
      }
      if (job.state !== "SUCCESS") {
        setFitMsg(job.error ? `${t("mannequin.fitFailed")}: ${job.error}` : t("mannequin.fitFailed"));
        return;
      }
      await applyVariant(res.variation_id);
      if (glbUrl) useGLTF.clear(glbUrl);
      const fresh = await getProject(id!);
      qc.setQueryData(["project", id], fresh);
      load(fresh.customizations);
      // Ölçüden giydirmede backend yeni özel manken üretmiş olabilir → listeyi tazele.
      if (opts.body) qc.invalidateQueries({ queryKey: ["mannequins"] });
      setFitMsg(t("mannequin.fitReady"));
    } catch (err) {
      setFitMsg(err instanceof Error && err.message ? `${t("mannequin.fitFailed")}: ${err.message}` : t("mannequin.fitFailed"));
    } finally {
      setFitBusy(false);
    }
  }

  async function runJobToGallery(
    endpoint: string, body: Record<string, unknown>, kind: VariationKind,
    setBusy: (b: boolean) => void, setMsg: (m: string | null) => void,
    readyMsg: string, failMsg: string,
  ) {
    setBusy(true);
    setMsg(t("quality.jobRunning"));
    try {
      const res = await api<{ job_id: string; group_id: string; project_id: string }>(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      let job = await getJob(res.job_id);
      for (let i = 0; i < 600 && job.state !== "SUCCESS" && job.state !== "FAILURE"; i++) {
        await sleep(1500); job = await getJob(res.job_id);
      }
      if (job.state === "SUCCESS") {
        setMsg(readyMsg);
        setGallery({ kind, base: { projectId: id!, prompt: "" }, pose: null, groupId: res.group_id });
      } else {
        // Gerçek worker hatasını göster (ör. "mesh'te baseColorTexture yok — doku
        // netleştirilemez"); genel failMsg tek başına kullanıcıya sebebi söylemiyordu.
        setMsg(job.error ? `${failMsg}: ${job.error}` : failMsg);
      }
    } catch (err) {
      setMsg(err instanceof Error && err.message ? `${failMsg}: ${err.message}` : failMsg);
    } finally {
      setBusy(false);
    }
  }

  // Dokuya İŞLE (bake): FLUX motif → UV texture'a 3B projeksiyonla pişir → YENİ proje
  // (decal değil, kumaşa gömülü, dışa aktarımda kalıcı). retexture gibi progress sayfasına gider.
  const bakeMut = useMutation({
    mutationFn: async () => {
      const pose = computePose();
      if (!pose) throw new Error(t("designer.markFirst"));
      // BATCH-F: boyanmış PBR kanallarını ekle (yoksa channels=null → bugünkü davranış).
      const channels: PbrChannels = {
        roughness: encodeChannel(roughMask, roughValue),
        metallic: encodeChannel(metalMask, metalValue),
      };
      const hasPbr = !!(channels.roughness || channels.metallic);
      return generateMotifBake(id!, retexturePrompt, pose.center, pose.normal, pose.scale,
        true, styleSource, hasPbr ? channels : null, undefined, motifEngine);
    },
    onSuccess: (r) => navigate(`/progress/${r.job_id}?project=${r.project_id}`),
  });

  function handleMovePick(point: [number, number, number], normal: [number, number, number]) {
    if (!selectedId) { setMoveMode(false); return; }
    const q = new THREE.Quaternion().setFromUnitVectors(
      new THREE.Vector3(0, 0, 1), new THREE.Vector3(...normal));
    const e = new THREE.Euler().setFromQuaternion(q);
    updateDecal(selectedId, { position: point, rotation: [e.x, e.y, e.z] });
    setMoveMode(false);
  }

  const tileMut = useMutation({
    mutationFn: () => {
      if (!selMotif) throw new Error(t("designer.selectMotifForTiling"));
      return generateTile(selMotif.projectId, selMotif.rel, tiling?.repeat ?? 3, "#ffffff");
    },
    onSuccess: (r) => navigate(`/progress/${r.job_id}?project=${r.project_id}`),
  });

  function handlePick(point: [number, number, number], _normal: [number, number, number]) {
    if (!pendingImage) return;
    addDecal({
      id: uuid(),
      image: pendingImage,
      position: point,
      rotation: [0, 0, 0],
      scale: 0.25,
    });
    setPendingImage(null);
  }

  // Sadece proje id'si DEĞİŞTİĞİNDE store'a yükle. Kaydetme sonrası refetch'te
  // tekrar load() çağrılması seçimi (selectedId) ve aktif düzenlemeyi sıfırlıyordu
  // (decal düzenleme paneli çöküyordu); store kayıttan sonra zaten doğruluk kaynağı.
  const loadedRef = useRef<string | null>(null);
  useEffect(() => {
    if (project && loadedRef.current !== project.id) {
      loadedRef.current = project.id;
      load(project.customizations);
      initialCustRef.current = JSON.stringify(project.customizations);
      autoSnapDoneRef.current = false;
    }
  }, [project, load]);

  const save = useMutation({
    mutationFn: async () => {
      await updateProject(id!, { customizations: toCustomizations() });
      if (captureRef.current) {
        const png = await (await fetch(captureRef.current())).blob();
        await uploadThumbnail(id!, png);
      }
    },
    onSuccess: () => { markSaved(); qc.invalidateQueries({ queryKey: ["project", id] }); },
  });

  const dupMut = useMutation({
    mutationFn: () => duplicateProject(id!),
    onSuccess: (p) => navigate(`/design/${p.id}`),
  });
  async function handleRestore(v: Version) {
    // geri dönüş öncesi otomatik snapshot (best-effort)
    try { await createVersion(id!, t("designer.versionBeforeRestore"), toCustomizations(), true); } catch { /* yoksay */ }
    const fresh = await restoreVersion(id!, v.id).catch(() => v);
    storeLoad(fresh.customizations);
  }

  // Auto-save: dirty + son kayıt hata vermemişse 2sn debounce
  // Hata durumunda auto-save loop kapatılır; "Kaydet" butonu manuel retry içindir.
  useEffect(() => {
    if (!dirty || save.isError || save.isPending) return;
    const t = setTimeout(() => save.mutate(), 2000);
    return () => clearTimeout(t);
  }, [dirty, save.isError, save.isPending]); // eslint-disable-line react-hooks/exhaustive-deps

  // İlk değişiklikte "açılış hâli" otomatik snapshot (kullanıcı bozarsa geri dönebilsin).
  useEffect(() => {
    if (dirty && !autoSnapDoneRef.current && initialCustRef.current && id) {
      autoSnapDoneRef.current = true;
      createVersion(id, t("designer.versionOpening"), JSON.parse(initialCustRef.current), true).catch(() => {});
    }
  }, [dirty, id]);

  // F3: manken yükleme-hatası köprüsü. Seçim değişince uyarıyı sıfırla; seçili
  // mankenin GLB'si eksik/bozuksa Mannequin hata sınırı window olayı yayar.
  const mannequinId = mannequin?.id;
  useEffect(() => {
    setMannequinError(false);
    if (!mannequinId) return;
    const onErr = () => setMannequinError(true);
    window.addEventListener("mannequin:loaderror", onErr);
    return () => window.removeEventListener("mannequin:loaderror", onErr);
  }, [mannequinId]);

  // Drape otomatik durma sebebini yakala (clothPreview → window olayı). Store yalnız
  // drapeAutoStopped bayrağını çevirir; reason'ı burada tutup panelde ayırt ediyoruz.
  useEffect(() => {
    const onAutoStop = (e: Event) => {
      const reason = (e as CustomEvent<{ reason?: "fps" | "dense" }>).detail?.reason;
      setDrapeAutoStopReason(reason === "dense" ? "dense" : "fps");
    };
    window.addEventListener("drape:autostop", onAutoStop);
    return () => window.removeEventListener("drape:autostop", onAutoStop);
  }, []);

  // Klavye undo/redo (Ctrl/Cmd+Z, Shift+Z = redo, Ctrl/Cmd+Y = redo).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault(); e.shiftKey ? redo() : undo();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
        e.preventDefault(); redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);

  // Task E1: turntable video kaydı (client-side MediaRecorder). Kayıt sırasında
  // turntable kapalıysa geçici olarak açılır, bittiğinde eski haline döner.
  const handleRecordTurntable = async () => {
    const canvas = paneRef.current?.querySelector("canvas");
    if (!canvas || recording) return;
    const wasRotating = autoRotate;
    if (!wasRotating) setAutoRotate(true);
    setRecording(true);
    setVideoMsg(null);
    try {
      // F1: canlı sahnenin hızıyla birebir aynı secondsPerTurn geçilir; böylece
      // kayıt süresi (tur × turnSeconds) tam olarak 1 tam turu yakalar.
      const webm = await recordTurntable(canvas as HTMLCanvasElement,
        { turns: 1, fps: 30, secondsPerTurn: turnSeconds });
      // Task A: mp4 tercih edilir (her yerde oynar); sunucuda ffmpeg yoksa
      // (422) sessizce webm indirmesine düşülür.
      setVideoMsg(t("quality.videoConverting"));
      try {
        const mp4 = await convertTurntableToMp4(webm);
        downloadBlob(mp4, "turntable.mp4");
        setVideoMsg(t("quality.videoMp4Ready"));
      } catch (convErr) {
        console.warn("mp4 convert unavailable, falling back to webm", convErr);
        downloadBlob(webm, "turntable.webm");
        setVideoMsg(t("quality.videoWebmFallback"));
      }
    } catch (err) {
      console.error("turntable record failed", err);
      setVideoMsg(t("quality.videoRecordFailed"));
    } finally {
      setRecording(false);
      if (!wasRotating) setAutoRotate(false);
    }
  };

  const viewFaces = useViewFaces((s) => s.faces); // F6: görüntüleme çözünürlüğü
  const glbUrl = (() => {
    if (!project) return null;
    if (project.mesh_path) return meshUrl(project.id, viewFaces);
    if (!manifest) return null;
    const group = manifest.garments.find((g) => g.type === project.garment_type);
    const tpl = group?.templates.find((t) => t.id === project.template_id);
    return tpl ? assetUrl(tpl.glb) : null;
  })();

  if (!project) return <div className="p-8 text-zinc-500">{t("designer.loading")}</div>;

  return (
    <div className="h-screen flex flex-col">
      <header className="flex items-center justify-between px-4 py-3 border-b border-zinc-800">
        <button onClick={() => navigate("/dashboard")} className="text-zinc-400">← {t("designer.back")}</button>
        <span className="font-medium">{project.name}
          {project.engine_id && <span className="ml-2 text-xs text-zinc-500">· {project.engine_id}</span>}
        </span>
        <div className="flex items-center gap-3">
          <span className={`text-xs ${save.isError ? "text-red-400" : "text-zinc-500"}`}>
            {save.isPending ? t("designer.saving") : save.isError ? t("designer.saveFailed") : dirty ? t("designer.unsaved") : t("designer.saved")}
          </span>
          <button onClick={undo} disabled={!canUndo}
            className="disabled:opacity-30 rounded-lg px-2 py-1.5 text-sm bg-zinc-800 hover:bg-zinc-700" title={t("designer.undoTitle")}>↶</button>
          <button onClick={redo} disabled={!canRedo}
            className="disabled:opacity-30 rounded-lg px-2 py-1.5 text-sm bg-zinc-800 hover:bg-zinc-700" title={t("designer.redoTitle")}>↷</button>
          <button onClick={() => dupMut.mutate()} disabled={dupMut.isPending}
            className="rounded-lg px-3 py-1.5 text-sm bg-zinc-800 hover:bg-zinc-700">{t("designer.duplicate")}</button>
          <button onClick={() => save.mutate()} disabled={save.isPending}
            className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg px-4 py-1.5 text-sm">
            {save.isPending ? t("designer.savingButton") : t("designer.saveButton")}
          </button>
          {canvasReady && (
            <ExportMenu project={project}
              getGlb={() => exportRef.current!()}
              getPng={() => captureRef.current!()} />
          )}
        </div>
      </header>
      <div className="flex flex-1 overflow-hidden">
        <div ref={paneRef} className="w-[70%] bg-zinc-950">
          {glbUrl && (
            <ThreeCanvas url={glbUrl} captureRef={captureRef} exportRef={exportRef}
              mannequinUrl={(() => {
                // F3: assetUrl() /api ön-eki + /template-assets/ ekler → Vite proxy'si
                // isteği gateway'e iletir. Ham "/template-assets/..." proxy'lenmiyordu
                // (index.html dönüyordu → GLTF loader patlıyordu, hata sessizce yutuluyordu).
                if (mannequin?.posed) return projectFileUrl(id!, "variations", mannequin.posed);
                const entry = mannequin && mannequins.find((m) => m.id === mannequin.id);
                return entry ? assetUrl(entry.file) : null;
              })()}
              mannequinAlign={aligning}
              onReady={() => setCanvasReady(true)}
              onPick={pendingImage ? handlePick : moveMode ? handleMovePick : undefined}
              selectedId={selectedId}
              tilePreview={tiling && selMotif ? { url: selMotif.url, repeat: tiling.repeat } : null}
              paintMode={paintMode}
              onPaintTris={paintMode ? activePaint : undefined}
              onMark={paintMode && pbrChannel === "albedo" ? handleMark : undefined}
              brush={brush}
              maskTexture={activeMaskTexture}
              envPreset={env} turntableSecondsPerTurn={autoRotate ? turnSeconds : 0} />
          )}
        </div>
        <aside className="w-[30%] border-l border-zinc-800 p-5 overflow-y-auto space-y-6">
          <ColorPicker />
          <DecalUploader pendingImage={pendingImage} setPendingImage={setPendingImage} />
          <button onClick={() => setLibraryOpen(true)}
            className="w-full bg-zinc-800 hover:bg-zinc-700 rounded-lg px-3 py-2 text-sm">
            {t("designer.addFromLibrary")}
          </button>
          <DecalEditPanel onMove={() => setMoveMode(true)} />
          {moveMode && <p className="text-xs text-amber-400">{t("designer.moveModeHint")}</p>}
          <ScenePanel env={env} setEnv={setEnv} autoRotate={autoRotate} setAutoRotate={setAutoRotate}
            turnSeconds={turnSeconds} setTurnSeconds={setTurnSeconds} />
          {/* Task E1: turntable video kaydı — turntable kontrolünün hemen yanında. */}
          <button onClick={handleRecordTurntable} disabled={recording || !canvasReady}
            title={t("exporting.recordTurntableHint")}
            className="w-full rounded-lg px-3 py-2 text-sm bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50">
            {recording ? t("exporting.recording") : t("exporting.recordTurntable")}
          </button>
          {videoMsg && <p className="text-[11px] text-zinc-400">{videoMsg}</p>}
          {/* Task E2: AR'da gör (USDZ + Scene Viewer + QR). */}
          <button onClick={() => setArOpen(true)} disabled={!canvasReady}
            title={t("ar.buttonHint")}
            className="w-full rounded-lg px-3 py-2 text-sm bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50">
            {t("ar.button")}
          </button>
          {/* Task E3: 3D baskıya hazırla — yalnız üretilmiş mesh varken anlamlı
              (trimesh sunucu tarafında proje mesh.glb'sini işler). */}
          {project.mesh_path && (
            <button onClick={() => setPrintOpen(true)}
              title={t("print.buttonHint")}
              className="w-full rounded-lg px-3 py-2 text-sm bg-zinc-800 hover:bg-zinc-700">
              {t("print.button")}
            </button>
          )}
          {/* Task BATCH-G: dikiş kalıbı (xatlas unfold → SVG/PDF) — yalnız üretilmiş
              mesh varken anlamlı (sunucu proje mesh.glb'sini açar). Deneysel. */}
          {project.mesh_path && (
            <button onClick={() => setSewingOpen(true)}
              title={t("sewing.buttonHint")}
              className="w-full rounded-lg px-3 py-2 text-sm bg-zinc-800 hover:bg-zinc-700">
              {t("sewing.button")}
            </button>
          )}

          {/* Statik manken (Task D1): seç / aç-kapa / opaklık / hizala. GLB'ler
              indirilmemişse (boş manifest) uyarı gösterir — kırılmaz. */}
          <div className="space-y-2 border-t border-zinc-800 pt-3">
            <h3 className="text-sm text-zinc-400">{t("mannequin.title")}</h3>
            {mannequins.length === 0 ? (
              <div className="rounded-lg bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-[11px] text-amber-200 space-y-1">
                <p>{t("mannequin.notDownloaded")}</p>
                <code className="block bg-black/40 rounded px-2 py-1 text-amber-100 break-all">
                  {t("mannequin.downloadCmd")}
                </code>
              </div>
            ) : (
              <>
                <div className="flex flex-wrap gap-1">
                  <button onClick={() => selectMannequin(null)}
                    className={`rounded px-2 py-1 text-xs ${!mannequin ? "bg-violet-600" : "bg-zinc-800 hover:bg-zinc-700"}`}>
                    {t("mannequin.none")}
                  </button>
                  {mannequins.map((m) => {
                    // T6: GLB diskte yoksa (available===false) buton devre dışı +
                    // "yakında" tooltip'i. Backend canlı hesapladığından dosya
                    // düşünce refetch'te otomatik açılır (seçilebilir olur).
                    const unavailable = m.available === false;
                    return (
                      <button key={m.id}
                        onClick={() => { if (!unavailable) selectMannequin(m.id); }}
                        disabled={unavailable}
                        title={unavailable
                          ? t("mannequin.unavailable")
                          : `${t(`mannequin.pose_${m.pose}`)} · ${m.license}`}
                        className={`rounded px-2 py-1 text-xs ${unavailable
                          ? "bg-zinc-800 opacity-40 cursor-not-allowed"
                          : mannequin?.id === m.id ? "bg-violet-600" : "bg-zinc-800 hover:bg-zinc-700"}`}>
                        {m.label}
                      </button>
                    );
                  })}
                </div>
                {mannequin && (
                  <>
                    <label className="flex items-center justify-between text-sm text-zinc-300">
                      <span>{t("mannequin.show")}</span>
                      <button onClick={() => setMannequinVisible(!mannequin.visible)}
                        className={`rounded-lg px-3 py-1 text-xs ${mannequin.visible ? "bg-emerald-600" : "bg-zinc-700"}`}>
                        {mannequin.visible ? t("scene.on") : t("scene.off")}
                      </button>
                    </label>
                    <label className="block text-xs text-zinc-400">
                      {t("mannequin.opacity")} ({Math.round(mannequin.opacity * 100)}%)
                      <input type="range" min={0.1} max={1} step={0.05} value={mannequin.opacity}
                        onChange={(e) => setMannequinOpacity(parseFloat(e.target.value))}
                        className="w-full" />
                    </label>
                    <div className="flex items-center gap-2">
                      <button onClick={() => setAligning((v) => !v)}
                        disabled={!mannequin.visible}
                        className={`flex-1 rounded-lg px-3 py-1 text-xs disabled:opacity-40 ${aligning ? "bg-emerald-600" : "bg-zinc-700 hover:bg-zinc-600"}`}>
                        {aligning ? t("mannequin.alignOn") : t("mannequin.align")}
                      </button>
                      <button onClick={resetMannequinTransform}
                        className="rounded-lg px-3 py-1 text-xs bg-zinc-800 hover:bg-zinc-700">
                        {t("mannequin.reset")}
                      </button>
                    </div>
                    {aligning && <p className="text-[11px] text-amber-400">{t("mannequin.alignHint")}</p>}
                    {mannequin?.fitted && !aligning && (
                      <p className="text-[11px] text-zinc-500">{t("mannequin.autoFitHint")}</p>
                    )}
                    {/* Mankene oturt: bedenin içinde kalan kumaşı (göğüs/kalça taşması) beden
                        yüzeyinin dışına iter → galeride varyant; "Projeye uygula" ile kalıcı. */}
                    <button
                      onClick={() => runDress({ mannequin_id: mannequin.id })}
                      disabled={fitBusy || aligning}
                      title={t("mannequin.fitHint")}
                      className="w-full rounded-lg px-3 py-1.5 text-xs bg-violet-700 hover:bg-violet-600 disabled:opacity-40">
                      {fitBusy ? t("common.loading") : t("mannequin.fitRun")}
                    </button>
                  </>
                )}
                {mannequin && mannequinError && (
                  <p className="text-[11px] text-amber-400">{t("mannequin.loadError")}</p>
                )}
                {/* Ölçülerimle giydir: seçili manken gerekmez (backend ölçüden bulur/üretir). */}
                <button onClick={() => setBodyDressOpen((v) => !v)}
                  className="text-xs text-violet-400 hover:text-violet-300">
                  {bodyDressOpen ? "▾ " : "▸ "}{t("mannequin.bodyDressOpen")}
                </button>
                {bodyDressOpen && (
                  <div className="space-y-2 rounded-lg bg-zinc-900 p-2">
                    <BodyInputs compact value={dressBody} onChange={setDressBody} />
                    {!bodyValid(dressBody) && <p className="text-[11px] text-amber-400">{t("body.invalid")}</p>}
                    <button
                      onClick={() => runDress({ body: dressBody })}
                      disabled={fitBusy || aligning || !bodyValid(dressBody)}
                      title={t("mannequin.bodyDressHint")}
                      className="w-full rounded-lg px-3 py-1.5 text-xs bg-violet-700 hover:bg-violet-600 disabled:opacity-40">
                      {fitBusy ? t("common.loading") : t("mannequin.bodyDressRun")}
                    </button>
                  </div>
                )}
                {fitMsg && <p className="text-[11px] text-zinc-400">{fitMsg}</p>}
              </>
            )}
            {/* Terzi ölçüleri: store.load() bilinmeyen anahtarları atar → react-query proje verisinden okunur. */}
            {project.customizations?.measurements?.rows?.length ? (
              <MeasurementsTable
                m={project.customizations.measurements}
                mannequinLabel={mannequins.find((x) => x.id === project.customizations.measurements!.mannequin_id)?.label}
                fileBase={project.name} />
            ) : null}
          </div>

          {/* Hafif drape (Task D2): önizleme fiziği — üst %10 sabit, gerisi
              yerçekimi+yayla sarkar. Çarpışma YOK (o BATCH-H). FPS düşerse otomatik kapanır. */}
          <div className="space-y-2 border-t border-zinc-800 pt-3">
            <label className="flex items-center justify-between text-sm text-zinc-300">
              <span>{t("drape.title")}</span>
              <button onClick={() => { setDrapeAutoStopReason(null); setDrapeEnabled(!drapeEnabled); }}
                className={`rounded-lg px-3 py-1 text-xs ${drapeEnabled ? "bg-emerald-600" : "bg-zinc-700"}`}>
                {drapeEnabled ? t("scene.on") : t("scene.off")}
              </button>
            </label>
            <p className="text-[11px] text-zinc-500">{t("drape.hint")}</p>
            {drapeEnabled && (
              <label className="block text-xs text-zinc-400">
                {t("drape.intensity")} ({Math.round(drapeIntensity * 100)}%)
                <input type="range" min={0.1} max={1} step={0.05} value={drapeIntensity}
                  onChange={(e) => setDrapeIntensity(parseFloat(e.target.value))}
                  className="w-full" />
              </label>
            )}
            {drapeAutoStopped && (
              <p className="text-[11px] text-amber-400">
                {drapeAutoStopReason === "dense" ? t("drape.autoStoppedDense") : t("drape.autoStopped")}
              </p>
            )}
          </div>

          {SHOW_BLENDER_DRAPE && (
            <div className="space-y-2 border-t border-zinc-800 pt-3">
              <span className="text-sm text-zinc-300">{t("drape.simTitle")}</span>
              <p className="text-[11px] text-zinc-500">{t("drape.simHint")}</p>
              <FabricSelect value={drapeFabric ?? fabricIdFromMaterial(designMaterial)} onChange={setDrapeFabric} />
              <button
                onClick={() => runJobToGallery(
                  `/projects/${id}/drape`,
                  {
                    mannequin_id: mannequin?.id ?? null, frames: 40,
                    fabric_id: drapeFabric ?? fabricIdFromMaterial(designMaterial),
                  },
                  "drape", setDrapeSimBusy, setDrapeSimMsg,
                  t("quality.drapeReady"), t("drape.simFailed"),
                )}
                disabled={drapeSimBusy}
                className="w-full rounded-lg px-3 py-1 text-xs bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40">
                {drapeSimBusy ? t("common.loading") : t("drape.simRun")}
              </button>
              {drapeSimMsg && <p className="text-[11px] text-zinc-400">{drapeSimMsg}</p>}
            </div>
          )}

          {/* Blender kumaş simülasyonu ARAYÜZDEN GİZLENDİ (kullanıcı kararı,
              2026-07-07): gövdesiz askı simülasyonu "giyilmiş" sonuç veremiyor —
              beklentiyi karşılamıyor. Backend (POST /projects/{id}/drape, clothsim
              worker, varyant akışı) duruyor; manken-collider'lı gerçek giydirme
              (faz-2) gelince bu bölüm geri açılabilir. */}

          {/* C Real-ESRGAN doku netleştirme: mesh dokusunu upscale et → yeni varyant
              (galeride görünür). Kaynak mesh/DB değişmez; ağırlık yoksa job FAILURE. */}
          <div className="space-y-2 border-t border-zinc-800 pt-3">
            <p className="text-sm text-zinc-300">{t("quality.upscaleTitle")}</p>
            <p className="text-[11px] text-zinc-500">{t("quality.upscaleHint")}</p>
            <button
              onClick={() => runJobToGallery(
                `/projects/${id}/upscale-texture`,
                { scale: 4 },
                "upscale", setUpscaleBusy, setUpscaleMsg,
                t("quality.upscaleReady"), t("quality.upscaleFailed"),
              )}
              disabled={upscaleBusy}
              className="w-full rounded-lg px-3 py-1 text-xs bg-zinc-800 hover:bg-zinc-700 disabled:opacity-40">
              {upscaleBusy ? t("common.loading") : t("quality.upscaleRun")}
            </button>
            {upscaleMsg && <p className="text-[11px] text-zinc-400">{upscaleMsg}</p>}
          </div>

          <MetricsPanel />
          <VersionPanel projectId={id!} onRestore={handleRestore} onCompare={(v) => setCompareVersion(v)} />

          {selMotif && (
            <div className="border-t border-zinc-800 pt-3 space-y-2">
              <label className="flex items-center justify-between text-sm text-zinc-300">
                <span>{t("designer.tileAll")}</span>
                <button onClick={() => setTiling((t) => (t ? null : { repeat: 3 }))}
                  className={`rounded-lg px-3 py-1 text-xs ${tiling ? "bg-emerald-600" : "bg-zinc-700"}`}>
                  {tiling ? t("designer.previewOn") : t("designer.preview")}
                </button>
              </label>
              {tiling && (
                <>
                  <label className="block text-xs text-zinc-400">{t("designer.frequency", { n: tiling.repeat })}
                    <input type="range" min={1} max={10} step={1} value={tiling.repeat}
                      onChange={(e) => setTiling({ repeat: parseInt(e.target.value, 10) })} className="w-full" />
                  </label>
                  <button disabled={tileMut.isPending} onClick={() => tileMut.mutate()}
                    className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg px-4 py-2 text-sm w-full font-medium">
                    {tileMut.isPending ? t("designer.sending") : t("designer.tileBake")}
                  </button>
                </>
              )}
            </div>
          )}
          {project.mesh_path && (
            <div className="space-y-3">
              <p className="text-sm font-medium text-zinc-300">{t("designer.retextureTitle")}</p>
              <textarea
                value={retexturePrompt}
                onChange={(e) => setRetexturePrompt(e.target.value)}
                placeholder={t("designer.retexturePlaceholder")}
                className="bg-zinc-800 rounded-lg px-3 py-2 w-full h-20 text-sm resize-none"
              />
              <button
                disabled={!retexturePrompt.trim() || retextureMut.isPending}
                onClick={() => retextureMut.mutate()}
                className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg px-4 py-1.5 text-sm w-full"
              >
                {retextureMut.isPending ? t("designer.sending") : t("designer.retextureAll")}
              </button>

              <div className="border-t border-zinc-800 pt-3 space-y-2">
                <p className="text-sm font-medium text-zinc-300">{t("designer.imageTexTitle")}</p>
                <p className="text-xs text-zinc-500">{t("designer.imageTexHint")}</p>
                <label className="block text-xs text-zinc-400">
                  {t("designer.imageTexPick")}
                  <input type="file" accept="image/*" data-testid="imagetex-file"
                    onChange={(e) => setImageTexFile(e.target.files?.[0] ?? null)}
                    className="mt-1 block w-full text-xs file:mr-2 file:rounded file:border-0 file:bg-zinc-700 file:px-2 file:py-1 file:text-zinc-200" />
                </label>
                <button
                  disabled={imageTexMut.isPending}
                  onClick={() => imageTexMut.mutate()}
                  data-testid="imagetex-go"
                  className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg px-4 py-1.5 text-sm w-full"
                >
                  {imageTexMut.isPending ? t("designer.sending") : t("designer.imageTexGo")}
                </button>
              </div>

              <div className="border-t border-zinc-800 pt-3 space-y-2">
                <p className="text-sm font-medium text-zinc-300">{t("designer.hi3dTitle")}</p>
                <p className="text-xs text-zinc-500">
                  {t("designer.hi3dHint")}{" "}
                  {/* Hi3D Open License §7: ticari kullanımda bağlantılı atıf zorunlu */}
                  <a href="https://www.hi3d.ai/" target="_blank" rel="noreferrer" className="underline">Powered by Hi3D 1.0</a>
                </p>
                <button
                  disabled={hi3dMut.isPending}
                  onClick={() => hi3dMut.mutate()}
                  data-testid="hi3d-go"
                  className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg px-4 py-1.5 text-sm w-full"
                >
                  {hi3dMut.isPending ? t("designer.sending") : t("designer.hi3dGo")}
                </button>
              </div>

              {/* F5 v2: bölge işaretleme */}
              <div className="border-t border-zinc-800 pt-3 space-y-2">
                <label className="flex items-center justify-between text-sm text-zinc-300">
                  <span>{t("designer.regionOnly")}</span>
                  <button
                    onClick={() => setPaintMode((v) => !v)}
                    className={`rounded-lg px-3 py-1 text-xs ${paintMode ? "bg-emerald-600" : "bg-zinc-700"}`}
                  >
                    {paintMode ? t("designer.markOn") : t("designer.markToggle")}
                  </button>
                </label>
                {paintMode && (
                  <>
                    <p className="text-xs text-zinc-500">
                      {t("designer.paintHelp1")}<b>{t("designer.paintHelpBold")}</b>{t("designer.paintHelp2")}
                    </p>
                    <label className="block text-xs text-zinc-400">
                      {t("designer.brushSize")}
                      <input type="range" min={0.02} max={0.15} step={0.01} value={brush}
                        onChange={(e) => setBrush(parseFloat(e.target.value))}
                        className="w-full" />
                    </label>
                    {/* BATCH-F: PBR kanal seçici (Albedo | Roughness | Metallic). */}
                    <div className="space-y-1.5">
                      <div className="flex items-center gap-1 text-xs">
                        <span className="text-zinc-400 mr-1">{t("pbr.channel")}:</span>
                        {(["albedo", "roughness", "metallic"] as const).map((ch) => (
                          <button key={ch} onClick={() => setPbrChannel(ch)}
                            title={t(`pbr.${ch}Title`)}
                            className={`rounded px-2 py-1 ${pbrChannel === ch ? "bg-sky-600" : "bg-zinc-700 hover:bg-zinc-600"}`}>
                            {t(`pbr.${ch}`)}
                          </button>
                        ))}
                      </div>
                      {/* Kanalların ne işe yaradığını tek satırda açıkla (kullanıcılar
                          Albedo/Roughness/Metallic'i karıştırıyordu). */}
                      <p className="text-[11px] text-zinc-500">{t("pbr.channelHint")}</p>
                      {pbrChannel !== "albedo" && (
                        <label className="block text-xs text-zinc-400">
                          {t("pbr.value")}: {(pbrChannel === "roughness" ? roughValue : metalValue).toFixed(2)}
                          <input type="range" min={0} max={1} step={0.05}
                            value={pbrChannel === "roughness" ? roughValue : metalValue}
                            onChange={(e) => {
                              const v = parseFloat(e.target.value);
                              pbrChannel === "roughness" ? setRoughValue(v) : setMetalValue(v);
                            }}
                            className="w-full" />
                        </label>
                      )}
                      <p className="text-[11px] text-zinc-500">{t("pbr.hint")}</p>
                      {(roughMask.hasMask || metalMask.hasMask) && (
                        <p className="text-[11px] text-emerald-400">
                          {roughMask.hasMask && `✅ ${t("pbr.roughnessPainted")}`}
                          {roughMask.hasMask && metalMask.hasMask && " · "}
                          {metalMask.hasMask && `✅ ${t("pbr.metallicPainted")}`}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {preview && (
                        <img src={preview} alt={t("designer.maskAlt")}
                          className="w-16 h-16 rounded border border-zinc-700 bg-black object-cover" />
                      )}
                      <button onClick={clearMarks}
                        className="bg-zinc-700 hover:bg-zinc-600 rounded-lg px-3 py-1.5 text-xs">
                        {t("designer.clear")}
                      </button>
                    </div>
                    {/* Stil transferi: kaynak = stil görselinden seçilen bölge (prompt yerine). */}
                    <div className="border-t border-zinc-800 pt-2">
                      <StyleTransferPanel style={styleSource} setStyle={setStyleSource} />
                    </div>

                    {/* Aşağıdaki 3 buton iki şart ister; eksikse kullanıcıya göster + boyama
                        kaydolunca ✓ ile anında geri bildirim (kırmızı işaret zor görülürse). */}
                    {(!hasMask || !(retexturePrompt.trim() || styleSource)) && (
                      <div className="rounded-lg bg-amber-500/10 border border-amber-500/30 px-3 py-2 text-[11px] text-amber-200 space-y-0.5">
                        <p className="font-medium text-amber-300">{t("designer.enableButtonsTitle")}</p>
                        <p>{hasMask ? "✅" : "⬜"} ① {t("designer.paintRegion")}</p>
                        <p>{(retexturePrompt.trim() || styleSource) ? "✅" : "⬜"} ② {t("designer.promptOrStyleA")} <b>{t("designer.or")}</b> {t("designer.promptOrStyleB")}</p>
                      </div>
                    )}

                    {/* Motif motoru seçici: yerel FLUX + bulut motif motorları. */}
                    {motifEngines.length > 1 && (
                      <div className="space-y-1">
                        <label className="flex items-center gap-2 text-xs text-zinc-400">
                          <span className="whitespace-nowrap">{t("designer.motifEngine")}</span>
                          <select value={motifEngine} onChange={(e) => setMotifEngine(e.target.value)}
                            className="bg-zinc-800 rounded-lg px-2 py-1 text-xs w-full">
                            {motifEngines.map((e) => {
                              const locked = !!e.cloud && !e.key_set;
                              return (
                                <option key={e.id} value={e.id} disabled={locked}>
                                  {locked
                                    ? t("designer.motifEngineLocked", { label: e.label, key: e.requires_key ?? "API_KEY" })
                                    : (e.cloud ? "☁ " : "") + e.label}
                                </option>
                              );
                            })}
                          </select>
                        </label>
                        {motifEngineSpec?.cloud && (
                          <p className="text-[11px] text-sky-300">
                            {t("designer.motifCloudNote", { price: motifEngineSpec.price_note || "?" })}
                          </p>
                        )}
                      </div>
                    )}

                    {/* Kaynak: yukarıdaki prompt YA DA stil görseli. İki çıktı yolu: */}
                    <button
                      disabled={!(retexturePrompt.trim() || styleSource) || !hasMask || motifMut.isPending}
                      onClick={() => motifMut.mutate()}
                      className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg px-4 py-2 text-sm w-full font-medium"
                    >
                      {motifMut.isPending ? t("designer.generatingDecal") : t("designer.addDecal")}
                    </button>
                    <button
                      disabled={!(retexturePrompt.trim() || styleSource) || !hasMask}
                      onClick={openVariationGallery}
                      className="bg-fuchsia-600 hover:bg-fuchsia-500 disabled:opacity-50 rounded-lg px-4 py-2 text-sm w-full font-medium"
                    >
                      {t("designer.genVariations")}
                    </button>
                    <button
                      disabled={!(retexturePrompt.trim() || styleSource) || !hasMask || bakeMut.isPending}
                      onClick={() => bakeMut.mutate()}
                      className="bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 rounded-lg px-4 py-2 text-sm w-full font-medium"
                    >
                      {bakeMut.isPending ? t("designer.sending") : t("designer.bakeTexture")}
                    </button>
                    <p className="text-[11px] text-zinc-500">
                      {t("designer.sourceHint1")}<b>{t("designer.or")}</b>{t("designer.sourceHint2")}
                    </p>
                  </>
                )}
              </div>
              {(retextureMut.isError || imageTexMut.isError || hi3dMut.isError || bakeMut.isError || motifMut.isError) && (
                <p className="text-red-400 text-xs">{t("designer.error")}</p>
              )}
            </div>
          )}
        </aside>
      </div>
      {gallery && (
        <VariationGallery
          kind={gallery.kind}
          base={gallery.base}
          initialGroupId={gallery.groupId}
          onSelect={applyVariation}
          onClose={() => setGallery(null)}
          // T4: 3D varyant uygulanınca mesh.glb değişir ama URL aynı kalır; eski
          // mesh'in drei önbelleğini boşalt → invalidation sonrası taze mesh yüklenir.
          onApplied={() => { if (glbUrl) useGLTF.clear(glbUrl); }}
        />
      )}
      {compareVersion && glbUrl && (
        <CompareModal glbUrl={glbUrl} version={compareVersion} onClose={() => setCompareVersion(null)} />
      )}
      {libraryOpen && (
        <LibraryModal
          onSelect={(v) => setPendingImage(decalUrl(v.project_id, v.result_path!))}
          onClose={() => setLibraryOpen(false)}
        />
      )}
      {arOpen && id && (
        <ARModal projectId={id} getGlb={() => exportRef.current!()} onClose={() => setArOpen(false)} />
      )}
      {printOpen && id && (
        <PrintPrepModal projectId={id} onClose={() => setPrintOpen(false)} />
      )}
      {sewingOpen && id && (
        <SewingPatternModal projectId={id} onClose={() => setSewingOpen(false)} />
      )}
    </div>
  );
}
