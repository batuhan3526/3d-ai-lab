import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { USDZExporter } from "three/examples/jsm/exporters/USDZExporter.js";
import { useAuth } from "../store/auth";

// Task E2: sahne mesh'ini (mevcut renk/decal'lerle GLB'e aktarılmış hâli)
// client-side USDZ'e çevirir → gateway'e yükler. iOS Quick Look USDZ'i, Android
// Scene Viewer GLB'yi kullanır (mesh public servisi), QR ise LAN host linkini.

/** GLB ikilisini USDZ ikilisine çevirir (iOS Quick Look / AR Quick Look formatı). */
export async function glbToUsdz(glb: ArrayBuffer): Promise<Blob> {
  const loader = new GLTFLoader();
  const gltf = await loader.parseAsync(glb, "");
  // USDZExporter tüm sahneyi paketler; kadraj için ambient ışık gerekmez
  // (Quick Look kendi aydınlatmasını uygular).
  const scene = new THREE.Scene();
  scene.add(gltf.scene);
  const exporter = new USDZExporter();
  const bytes = await exporter.parseAsync(scene);
  return new Blob([bytes as BlobPart], { type: "model/vnd.usd+zip" });
}

export interface ArAsset {
  usdzUrl: string; // gateway-göreli, ör. /projects/{id}/ar.usdz
  glbUrl: string; // gateway-göreli mesh servisi, Scene Viewer için
}

/** USDZ ikilisini `POST /projects/{id}/ar-asset`'e yükler; asset URL'lerini döner. */
export async function uploadArAsset(projectId: string, usdz: Blob): Promise<ArAsset> {
  const form = new FormData();
  form.append("file", usdz, "ar.usdz");
  const token = useAuth.getState().token;
  const resp = await fetch(`/api/projects/${projectId}/ar-asset`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!resp.ok) throw new Error(`AR yükleme başarısız: HTTP ${resp.status}`);
  const body = (await resp.json()) as { usdz_url: string; glb_url: string };
  return { usdzUrl: body.usdz_url, glbUrl: body.glb_url };
}

/** Gateway-göreli yolu, LAN cihazlarının açabileceği mutlak URL'e çevirir. */
export function absoluteUrl(gatewayRelPath: string): string {
  // Gateway route'ları `/api` proxy'si arkasında; frontend origin'i (LAN IP)
  // + /api önekiyle mutlaklaştır ki telefon aynı ağdan erişebilsin.
  const origin = window.location.origin;
  const path = gatewayRelPath.startsWith("/") ? gatewayRelPath : `/${gatewayRelPath}`;
  return `${origin}/api${path}`;
}

/** UA-yönlendirmeli AR açılış sayfasının mutlak URL'i — QR bunu kodlar (R4).
 *
 * Doğrudan .usdz'i kodlamak Android'de açılamayan bir dosya indiriyordu; bu
 * sayfa User-Agent'e göre iOS Quick Look ya da Android Scene Viewer'a yönlendirir.
 */
export function arLandingUrl(projectId: string): string {
  return absoluteUrl(`/projects/${projectId}/ar`);
}

/** Android Scene Viewer intent URL'i (GLB linki gömülü). */
export function sceneViewerIntent(absGlbUrl: string): string {
  const params = new URLSearchParams({ file: absGlbUrl, mode: "ar_preferred" });
  return (
    `intent://arvr.google.com/scene-viewer/1.0?${params.toString()}` +
    `#Intent;scheme=https;package=com.google.android.googlequicksearchbox;` +
    `action=android.intent.action.VIEW;` +
    `S.browser_fallback_url=${encodeURIComponent(absGlbUrl)};end;`
  );
}
