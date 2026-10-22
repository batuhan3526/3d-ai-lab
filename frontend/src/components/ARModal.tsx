import { useEffect, useMemo, useState } from "react";
import { useT } from "../i18n";
import { qrToSvgPath } from "../lib/qr";
import {
  glbToUsdz,
  uploadArAsset,
  absoluteUrl,
  sceneViewerIntent,
  arLandingUrl,
  type ArAsset,
} from "../lib/arExport";

// Task E2: "📱 AR'da gör" modalı — sahne GLB'sini USDZ'e çevirir + yükler,
// sonra QR (LAN linki) + iOS Quick Look (rel=ar) + Android Scene Viewer linkleri
// gösterir. QR bağımlılıksız üreticiyle (lib/qr.ts) çizilir.

type Phase = "working" | "ready" | "error";

function QrSvg({ text, size = 180 }: { text: string; size?: number }) {
  // qr.ts modül-başına 1 birim path döner; viewBox dim=modül+kenar. SVG
  // ölçekleyerek net (piksel-hizalı) kod verir — harici bağımlılık yok.
  const { path, dim } = useMemo(() => qrToSvgPath(text), [text]);
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${dim} ${dim}`}
      shapeRendering="crispEdges"
      className="rounded-lg bg-white p-2"
      role="img"
      aria-label="QR"
    >
      <path d={path} fill="#000000" />
    </svg>
  );
}

export function ARModal({
  projectId,
  getGlb,
  onClose,
}: {
  projectId: string;
  getGlb: () => Promise<ArrayBuffer>;
  onClose: () => void;
}) {
  const { t } = useT();
  const [phase, setPhase] = useState<Phase>("working");
  const [asset, setAsset] = useState<ArAsset | null>(null);
  // "Tekrar dene" bu sayacı artırıp effect'i yeniden koşturur.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setPhase("working");
    (async () => {
      try {
        // 60 sn zaman-aşımı bekçisi: takılan hattı hataya çevirir (sonsuz spin yok).
        const timeout = new Promise<never>((_, reject) => {
          timer = setTimeout(
            () => reject(new Error("AR export timed out after 60s")),
            60_000,
          );
        });
        const build = (async () => {
          const glb = await getGlb();
          const usdz = await glbToUsdz(glb);
          return uploadArAsset(projectId, usdz);
        })();
        const result = await Promise.race([build, timeout]);
        if (!cancelled) {
          setAsset(result);
          setPhase("ready");
        }
      } catch (err) {
        console.error("AR export failed", err);
        if (!cancelled) setPhase("error");
      } finally {
        if (timer) clearTimeout(timer);
      }
    })();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [projectId, getGlb, attempt]);

  const absUsdz = asset ? absoluteUrl(asset.usdzUrl) : "";
  const absGlb = asset ? absoluteUrl(asset.glbUrl) : "";
  const sceneViewer = asset ? sceneViewerIntent(absGlb) : "";
  // QR artık .usdz'i değil UA-yönlendirmeli açılış sayfasını kodlar (R4):
  // Android telefon Scene Viewer'a, iPhone Quick Look'a gider.
  const landingUrl = arLandingUrl(projectId);

  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="w-full max-w-md rounded-2xl bg-zinc-900 border border-zinc-800 p-6 space-y-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2 className="font-medium text-zinc-100">{t("ar.title")}</h2>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-200 text-xl">×</button>
        </div>

        {phase === "working" && (
          <p className="text-sm text-zinc-400 py-8 text-center">{t("ar.preparing")}</p>
        )}

        {phase === "error" && (
          <div className="py-8 text-center space-y-4">
            <p className="text-sm text-red-400">{t("ar.error")}</p>
            <button
              onClick={() => setAttempt((n) => n + 1)}
              className="rounded-lg bg-zinc-800 hover:bg-zinc-700 px-4 py-2 text-sm text-zinc-100"
            >
              {t("ar.retry")}
            </button>
          </div>
        )}

        {phase === "ready" && asset && (
          <div className="space-y-5">
            <div className="flex flex-col items-center gap-2">
              {/* QR: telefon aynı LAN'dan tarayınca UA'ya göre AR açar (R4). */}
              <QrSvg text={landingUrl} />
              <p className="text-xs text-zinc-500 text-center">{t("ar.qrHint")}</p>
              <p className="text-[11px] text-zinc-600 text-center">{t("quality.arArcoreHint")}</p>
            </div>

            <div className="grid gap-2">
              {/* iOS: rel="ar" + içteki <img> Quick Look tetikler (Safari). */}
              <a
                rel="ar"
                href={absUsdz}
                className="flex items-center justify-center gap-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 px-4 py-2.5 text-sm text-zinc-100"
              >
                <img src="" alt="" width={0} height={0} style={{ display: "none" }} />
                {t("ar.openIos")}
              </a>
              {/* Android: Scene Viewer intent (GLB linki gömülü). */}
              <a
                href={sceneViewer}
                className="flex items-center justify-center gap-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 px-4 py-2.5 text-sm text-zinc-100"
              >
                {t("ar.openAndroid")}
              </a>
            </div>

            <p className="text-[11px] text-zinc-600 text-center break-all">{absUsdz}</p>
          </div>
        )}
      </div>
    </div>
  );
}
