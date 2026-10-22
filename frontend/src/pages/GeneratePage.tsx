import { useState, useEffect, useMemo } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { generateText, generateImage, generateMultiImage, matteImage, matteUrl, getJob, type GenerateOut } from "../api/generate";
import { listEngines } from "../api/engines";
import { PromptLibrary, savePromptTemplate, type PromptTemplate } from "../components/PromptLibrary";
import { useT } from "../i18n";
import { listMannequins, type BodyInput } from "../api/mannequins";
import { BodyInputs, BODY_DEFAULTS, bodyValid } from "../components/BodyInputs";
import type { Advanced, EngineParam, DressOption } from "../types";
import { DRESSABLE_TYPES } from "../types";

const TYPES = ["model", "tshirt", "shirt", "pants", "skirt", "hat", "boots"] as const;

const QUALITY_KEYS = new Set(["fast", "balanced", "quality"]);

// Manken seçicide "Ölçülerimden" (backend ölçüye uygun mankeni bulur/üretir).
const BODY_CHOICE = "__body";

// İlerleme sayfası: giydirme işi varsa ?dress=<id> ile ikinci aşama olarak izlenir.
const progressUrl = (r: GenerateOut) =>
  `/progress/${r.job_id}?project=${r.project_id}${r.dress_job_id ? `&dress=${encodeURIComponent(r.dress_job_id)}` : ""}`;

export default function GeneratePage() {
  const { t } = useT();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [prompt, setPrompt] = useState("");
  const [type, setType] = useState("model");
  const [engineId, setEngineId] = useState(searchParams.get("engine") || "trellis-text");
  // Katalogdan motorla gelindiyse seçim zaten yapıldı → bar yerine kompakt chip göster.
  const [showEngineSelect, setShowEngineSelect] = useState(!searchParams.get("engine"));
  // GPU: null = "backend varsayılanını izle" (tek-GPU sözleşmesi, DEFAULT_GPU).
  // useState(0) sabiti işleri worker'sız gpu0 kuyruğuna düşürüyordu (2026-07-12).
  const [gpu, setGpu] = useState<number | null>(null);
  const [quality, setQuality] = useState("balanced");
  const [enhance, setEnhance] = useState(true);
  const [showAdv, setShowAdv] = useState(false);
  const [adv, setAdv] = useState<Advanced>({});
  const [precision, setPrecision] = useState<string>("");
  const [deviceMode, setDeviceMode] = useState<string>("");
  const [files, setFiles] = useState<File[]>([]);
  // Tek mi çoklu mu foto modu — hem tek hem çoklu destekleyen motorlarda kullanıcı seçer.
  const [photoMode, setPhotoMode] = useState<"single" | "multi">("single");
  // C1 foto ön-kırpma: seçilen fotoğrafın arka planını BiRefNet ile temizle önizle.
  const [matteJob, setMatteJob] = useState<{ jobId: string; outUrl: string } | null>(null);
  const [matteApplied, setMatteApplied] = useState(false);
  // C2 prompt/seed şablon kütüphanesi: çekmece + "şablon uygulandığında bekleyen" akış.
  const [showLibrary, setShowLibrary] = useState(false);
  const [pendingTpl, setPendingTpl] = useState<PromptTemplate | null>(null);
  const [tplSaved, setTplSaved] = useState(false);
  // Üretimden sonra otomatik mankene giydir (varsayılan KAPALI → istek birebir eskisi gibi).
  // dressChoice: manken id'si (female-a/male-a/custom-*) ya da BODY_CHOICE (ölçülerimden).
  const [dressOn, setDressOn] = useState(false);
  const [dressChoice, setDressChoice] = useState<string>("female-a");
  const [dressBody, setDressBody] = useState<BodyInput>(BODY_DEFAULTS.female);

  const engines = useQuery({ queryKey: ["engines"], queryFn: listEngines, retry: 1 });
  const dressable = (DRESSABLE_TYPES as readonly string[]).includes(type);
  // Kayıtlı özel mankenler (custom-*) yalnız toggle açıkken çekilir.
  const mannequinsQ = useQuery({
    queryKey: ["mannequins", "list"], queryFn: listMannequins, enabled: dressOn && dressable,
  });
  const customMannequins = (mannequinsQ.data ?? []).filter((m) => m.custom && m.available !== false);
  // Gönderilecek dress seçeneği: kapalı / giydirilemez türde → null (alan hiç gönderilmez).
  const dressOpt: DressOption | null = dressOn && dressable
    ? (dressChoice === BODY_CHOICE ? { body: dressBody } : { mannequin_id: dressChoice })
    : null;
  const dressInvalid = !!dressOpt?.body && !bodyValid(dressOpt.body);
  const engine = (engines.data ?? []).find((m) => m.id === engineId);
  const kind = engine?.kind ?? "text";
  // Motor çoklu-foto desteklemiyorsa multi endpoint'e DÜŞME (önceden sessizce
  // trellis'e gidiyordu ve seçilen motor yok sayılıyordu).
  const supportsMulti = (engine?.capabilities ?? []).includes("multi-image-to-3d");
  const supportsSingle = (engine?.capabilities ?? []).includes("image-to-3d");
  const supportsBoth = supportsSingle && supportsMulti;
  // Etkin çoklu mod: ikisini de destekliyorsa kullanıcı seçimine, sadece çokluysa zorunlu çokluya bağlı.
  const useMulti = supportsMulti && (supportsBoth ? photoMode === "multi" : !supportsSingle);
  const enginesUnavailable = engines.isError || (engines.isSuccess && (engines.data?.length ?? 0) === 0);

  // Reset dynamic state when engine changes
  useEffect(() => {
    setAdv({});
    setPrecision("");
    setDeviceMode("");
    // Reset quality to first available preset for this engine, or keep "balanced"
    if (engine) {
      // Foto modu: motor tek-fotoyu destekliyorsa varsayılan tek; yalnız çokluysa çoklu.
      const caps = engine.capabilities ?? [];
      setPhotoMode(caps.includes("image-to-3d") ? "single" : "multi");
      const presets = engine.quality_presets ?? [];
      if (presets.length > 0 && !presets.includes(quality)) {
        setQuality(presets[0]);
      }
      // Elle seçilmiş GPU bu motorda yoksa backend varsayılanına dön (null).
      const gpus = engine.gpus ?? [];
      if (gpu !== null && !gpus.includes(gpu)) {
        setGpu(null);
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engineId]);

  // C2: şablon uygulanınca prompt+motor formda; params/seed'i motor-reset effect'i
  // adv'yi temizledikten SONRA yaz (bu effect sonra çalışır → değerler korunur).
  useEffect(() => {
    if (!pendingTpl) return;
    const merged: Advanced = { ...(pendingTpl.params ?? {}) } as Advanced;
    if (pendingTpl.seed != null && merged.seed === undefined) merged.seed = pendingTpl.seed;
    if (Object.keys(merged).length > 0) {
      setAdv(merged);
      setShowAdv(true);
    }
    setPendingTpl(null);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingTpl, engineId]);

  // Şablonu forma uygula: prompt + (varsa) motor hemen; params/seed pendingTpl effect'inde.
  const applyTemplate = (tpl: PromptTemplate) => {
    setPrompt(tpl.prompt);
    if (tpl.engine_id) setEngineId(tpl.engine_id);
    setPendingTpl(tpl);
  };

  // Mevcut prompt+motor+advanced+seed'i şablon olarak kaydet (başlık window.prompt ile).
  const saveTemplate = useMutation({
    mutationFn: () => {
      const title = window.prompt(t("quality.tplNamePrompt"), prompt.slice(0, 40).trim());
      if (title === null || !title.trim()) return Promise.reject(new Error("cancelled"));
      const params = Object.keys(adv).length ? (adv as Record<string, unknown>) : null;
      const seed = typeof adv.seed === "number" ? adv.seed : null;
      return savePromptTemplate({
        title: title.trim(), prompt, engine_id: engineId, params, seed,
      });
    },
    onSuccess: () => { setTplSaved(true); setTimeout(() => setTplSaved(false), 2500); },
  });

  const gen = useMutation({
    mutationFn: () => {
      const advPayload = showAdv && Object.keys(adv).length
        ? Object.fromEntries(Object.entries(adv).filter(([, v]) => v !== undefined)) as Advanced
        : null;
      return generateText({
        prompt,
        garment_type: type,
        engine_id: engineId,
        gpu: effGpu,
        quality,
        prompt_enhance: enhance,
        advanced: advPayload,
        ...(precision ? { precision } : {}),
        ...(deviceMode ? { device_mode: deviceMode } : {}),
      }, dressOpt);
    },
    onSuccess: (r) => navigate(progressUrl(r)),
  });

  const genImg = useMutation({
    mutationFn: () => {
      const fd = new FormData();
      fd.append("garment_type", type);
      fd.append("gpu", String(effGpu));
      fd.append("quality", quality);
      fd.append("engine_id", engineId);
      if (precision) fd.append("precision", precision);
      if (deviceMode) fd.append("device_mode", deviceMode);
      const advPayload = showAdv && Object.keys(adv).length
        ? Object.fromEntries(Object.entries(adv).filter(([, v]) => v !== undefined))
        : null;
      if (advPayload) fd.append("advanced", JSON.stringify(advPayload));
      if (useMulti) {
        files.forEach((f) => fd.append("files", f));
        return generateMultiImage(fd, dressOpt);
      }
      fd.append("file", files[0]);
      return generateImage(fd, dressOpt);
    },
    onSuccess: (r) => navigate(progressUrl(r)),
  });

  const busy = gen.isPending || genImg.isPending;

  // C1: arka plan temizleme işini başlat (yalnız tek-foto modunda ilk fotoğraf).
  const matte = useMutation({
    mutationFn: () => matteImage(files[0]),
    onSuccess: (r) => setMatteJob({ jobId: r.job_id, outUrl: r.out_url }),
  });

  // İş bitene kadar poll et (mevcut getJob; SUCCESS/FAILURE'da dur).
  const matteStatus = useQuery({
    queryKey: ["matte-job", matteJob?.jobId],
    queryFn: () => getJob(matteJob!.jobId),
    enabled: !!matteJob,
    refetchInterval: (q) => {
      const s = q.state.data?.state;
      return s === "SUCCESS" || s === "FAILURE" ? false : 1500;
    },
  });
  const matteReady = !!matteJob && matteStatus.data?.state === "SUCCESS";
  const matteFailed = (!!matteJob && matteStatus.data?.state === "FAILURE") || matte.isError;
  const matteWorking = matte.isPending || (!!matteJob && !matteReady && !matteFailed);

  // Orijinal foto önizlemesi (obje URL'i; dosya değişince temizlenir).
  const originalUrl = useMemo(
    () => (files[0] ? URL.createObjectURL(files[0]) : null),
    [files],
  );
  useEffect(() => () => { if (originalUrl) URL.revokeObjectURL(originalUrl); }, [originalUrl]);

  const resetMatte = () => { setMatteJob(null); setMatteApplied(false); matte.reset(); };

  // "Kırpılmışı kullan": token'sız serve edilen PNG'yi indir → File'a çevir → files[0] yap.
  const applyMatte = async () => {
    if (!matteJob) return;
    const resp = await fetch(matteUrl(matteJob.outUrl));
    if (!resp.ok) return;
    const blob = await resp.blob();
    const cropped = new File([blob], "matte.png", { type: "image/png" });
    setFiles([cropped]);
    setMatteApplied(true);
    setMatteJob(null);
  };

  const handleAdvChange = (param: EngineParam, value: string | boolean) => {
    setAdv((a) => {
      if (param.type === "bool") {
        return { ...a, [param.key]: value as boolean };
      }
      // int or float
      const strVal = value as string;
      if (strVal === "") {
        const next = { ...a };
        delete next[param.key];
        return next;
      }
      return { ...a, [param.key]: param.type === "int" ? parseInt(strVal, 10) : parseFloat(strVal) };
    });
  };

  const renderParamInput = (p: EngineParam) => {
    if (p.type === "bool") {
      return (
        <label key={p.key} className="flex items-center gap-2 col-span-2">
          <input
            type="checkbox"
            checked={adv[p.key] === true}
            onChange={(e) => handleAdvChange(p, e.target.checked)}
          />
          {p.label}
        </label>
      );
    }
    if (p.type === "select" && p.options) {
      return (
        <label key={p.key} className="flex flex-col gap-1">
          {p.label}
          <select
            value={adv[p.key] !== undefined ? String(adv[p.key]) : ""}
            onChange={(e) => {
              const v = e.target.value;
              if (v === "") {
                setAdv((a) => { const next = { ...a }; delete next[p.key]; return next; });
              } else {
                setAdv((a) => ({ ...a, [p.key]: p.type === "int" ? parseInt(v, 10) : parseFloat(v) }));
              }
            }}
            className={sel}
          >
            <option value="">—</option>
            {p.options.map((o) => (
              <option key={o} value={o}>{o}</option>
            ))}
          </select>
        </label>
      );
    }
    // int or float
    return (
      <label key={p.key} className="flex flex-col gap-1">
        {p.label}
        <input
          type="number"
          step={p.step ?? (p.type === "int" ? 1 : 0.1)}
          min={p.min}
          max={p.max}
          placeholder={p.default !== null && p.default !== undefined ? String(p.default) : ""}
          value={adv[p.key] !== undefined ? String(adv[p.key]) : ""}
          onChange={(e) => handleAdvChange(p, e.target.value)}
          className={sel}
        />
      </label>
    );
  };

  const sel = "bg-zinc-800 rounded-lg px-3 py-2 w-full";

  const gpuOptions = engine?.gpus ?? [0];
  // Etkin GPU: kullanıcı seçmediyse backend varsayılanı (DEFAULT_GPU) — tek-GPU sözleşmesi.
  const effGpu = gpu ?? engine?.default_gpu ?? gpuOptions[0] ?? 0;
  const qualityPresets = engine?.quality_presets ?? ["fast", "balanced", "quality"];
  // Bulut API motoru: GPU/hassasiyet/cihaz seçicileri anlamsız → gizle.
  const isCloud = !!engine?.cloud;
  const cloudLocked = isCloud && !engine?.key_set;
  const showPrecision = !isCloud && engine && engine.precisions && engine.precisions.length > 1;
  const showDeviceMode = !isCloud && engine && engine.device_modes && engine.device_modes.length > 1;
  const engineParams = engine?.params ?? [];

  return (
    <div className="max-w-xl mx-auto p-8 space-y-4">
      <h1 className="text-xl font-medium">{kind === "image" ? t("generate.titleImage") : t("generate.titleText")}</h1>

      {engines.isLoading && (
        <p className="text-zinc-500 text-sm">{t("generate.enginesLoading")}</p>
      )}
      {enginesUnavailable && (
        <div className="bg-amber-950/40 border border-amber-800 text-amber-200 text-sm rounded-lg px-3 py-2">
          {t("generate.enginesError")}
          <button onClick={() => engines.refetch()} className="ml-2 underline">{t("generate.retry")}</button>
        </div>
      )}

      <div className="flex items-center gap-2">
        <button type="button" onClick={() => setShowLibrary(true)}
          className="text-sm text-violet-400 hover:text-violet-300">
          📚 {t("quality.tplOpen")}
        </button>
        <button type="button" onClick={() => saveTemplate.mutate()}
          disabled={!prompt.trim() || saveTemplate.isPending}
          className="text-sm text-violet-400 hover:text-violet-300 disabled:opacity-40">
          💾 {t("quality.tplSave")}
        </button>
        {tplSaved && <span className="text-emerald-400 text-sm">{t("quality.tplSaved")}</span>}
      </div>

      {showLibrary && (
        <PromptLibrary onApply={applyTemplate} onClose={() => setShowLibrary(false)} />
      )}

      {!showEngineSelect && engine ? (
        // Katalogdan seçilip gelindi: yeniden seçim barı yerine kompakt chip.
        <div className="flex items-center gap-3 bg-zinc-900 border border-zinc-800 rounded-lg px-3 py-2">
          <span className="text-sm">{(engine.cloud ? "☁ " : "") + engine.label}</span>
          <button type="button" onClick={() => setShowEngineSelect(true)}
            className="ml-auto text-xs text-violet-400 hover:text-violet-300">
            {t("generate.changeEngine")}
          </button>
        </div>
      ) : (
        <select value={engineId} onChange={(e) => setEngineId(e.target.value)} className={sel}
          disabled={engines.isLoading || enginesUnavailable}>
          {engines.isLoading && <option value="">{t("generate.loadingOption")}</option>}
          {enginesUnavailable && <option value="trellis-text">{t("generate.engineFallbackOption")}</option>}
          {engines.data?.filter((m) => (m.kind === "text" || m.kind === "image")
              // Yerel motorlar: available=false → gizli. Bulut motorlar: anahtarsız da
              // görünür ama kilitli (disabled) — kullanıcı neyin eksik olduğunu görsün.
              && (m.available !== false || (m.cloud && !m.key_set)))
            .sort((a, b) => (b.recommended ? 1 : 0) - (a.recommended ? 1 : 0))
            .map((m) => {
              if (m.cloud && !m.key_set) {
                return (
                  <option key={m.id} value={m.id} disabled>
                    {t("generate.cloudLocked", { label: m.label, key: m.requires_key ?? "API_KEY" })}
                  </option>
                );
              }
              return (
                <option key={m.id} value={m.id}>
                  {(m.cloud ? "☁ " : "")
                    + (m.recommended ? t("generate.recommendedLabel", { rank: m.recommended, label: m.label }) : m.label)
                    + ((m.capabilities?.includes("multi-image-to-3d") && m.capabilities?.includes("image-to-3d"))
                        ? t("generate.capBoth")
                        : m.capabilities?.includes("multi-image-to-3d") ? t("generate.capMulti") : "")}
                </option>
              );
            })}
        </select>
      )}
      {isCloud && (
        <p className={`text-xs -mt-2 ${cloudLocked ? "text-amber-300" : "text-sky-300"}`}>
          {cloudLocked
            ? t("generate.cloudLockedNote", { key: engine?.requires_key ?? "API_KEY" })
            : t("generate.cloudNote", { price: engine?.price_note || "?" })}
        </p>
      )}

      <div className="flex gap-3">
        {qualityPresets.length > 1 && (
          <select value={quality} onChange={(e) => setQuality(e.target.value)} className={sel}>
            {qualityPresets.map((v) => (
              <option key={v} value={v}>{QUALITY_KEYS.has(v) ? t(`generate.quality.${v}`) : v}</option>
            ))}
          </select>
        )}
        {!isCloud && gpuOptions.length > 1 && (
          <select value={effGpu} onChange={(e) => setGpu(Number(e.target.value))} className={sel}>
            {gpuOptions.map((g) => (
              <option key={g} value={g}>GPU {g}{g === engine?.default_gpu ? " ★" : ""}</option>
            ))}
          </select>
        )}
      </div>

      {(showPrecision || showDeviceMode) && (
        <div className="flex gap-3">
          {showPrecision && (
            <label className="flex flex-col gap-1 flex-1 text-sm">
              {t("generate.precision")}
              <select value={precision} onChange={(e) => setPrecision(e.target.value)} className={sel}>
                <option value="">{t("generate.default")}</option>
                {engine.precisions.map((p) => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </label>
          )}
          {showDeviceMode && (
            <label className="flex flex-col gap-1 flex-1 text-sm">
              {t("generate.deviceMode")}
              <select value={deviceMode} onChange={(e) => setDeviceMode(e.target.value)} className={sel}>
                <option value="">{t("generate.default")}</option>
                {engine.device_modes.map((d) => (
                  <option key={d} value={d}>{d}</option>
                ))}
              </select>
            </label>
          )}
        </div>
      )}

      {kind === "image" ? (
        <>
          {/* Motorun foto yeteneği rozeti */}
          <div className="flex items-center gap-2 text-xs">
            <span className="text-zinc-400">{t("generate.thisEngine")}</span>
            {supportsSingle && <span className="px-2 py-0.5 rounded bg-zinc-700 text-zinc-200">{t("generate.badgeSingle")}</span>}
            {supportsMulti && <span className="px-2 py-0.5 rounded bg-violet-700 text-violet-100">{t("generate.badgeMulti")}</span>}
          </div>

          {/* Hem tek hem çoklu destekleyen motorlarda açık mod seçimi */}
          {supportsBoth && (
            <div className="flex gap-2">
              {(["single", "multi"] as const).map((mode) => (
                <button key={mode} type="button"
                  onClick={() => { setPhotoMode(mode); setFiles([]); resetMatte(); }}
                  className={`flex-1 rounded-lg px-3 py-2 text-sm border ${
                    photoMode === mode
                      ? "bg-violet-600 border-violet-500 text-white"
                      : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700"}`}>
                  {mode === "single" ? t("generate.modeSingle") : t("generate.modeMulti")}
                </button>
              ))}
            </div>
          )}

          <input type="file" accept="image/*" multiple={useMulti}
            onChange={(e) => { setFiles(Array.from(e.target.files ?? [])); resetMatte(); }} className={sel} />

          {/* C1: arka plan temizleme (yalnız tek-foto modu) */}
          {!useMulti && files.length > 0 && (
            <div className="bg-zinc-900 rounded-lg p-3 space-y-3">
              {!matteJob && !matteApplied && (
                <button type="button" onClick={() => matte.mutate()} disabled={matteWorking}
                  className="text-sm text-violet-400 disabled:opacity-50">
                  {matteWorking ? t("quality.matteProcessing") : t("quality.matteButton")}
                </button>
              )}
              {matteApplied && (
                <p className="text-emerald-400 text-sm">{t("quality.matteApplied")}</p>
              )}
              {matteWorking && (
                <p className="text-zinc-400 text-sm">{t("quality.matteProcessing")}</p>
              )}
              {matteFailed && (
                <p className="text-red-400 text-sm">{t("quality.matteError")}</p>
              )}
              {matteReady && matteJob && (
                <>
                  <div className="grid grid-cols-2 gap-2">
                    <figure className="space-y-1">
                      <figcaption className="text-xs text-zinc-400">{t("quality.matteOriginal")}</figcaption>
                      {originalUrl && <img src={originalUrl} alt="" className="w-full rounded bg-zinc-800" />}
                    </figure>
                    <figure className="space-y-1">
                      <figcaption className="text-xs text-zinc-400">{t("quality.matteResult")}</figcaption>
                      <img src={matteUrl(matteJob.outUrl)} alt=""
                        className="w-full rounded"
                        style={{ backgroundImage: "conic-gradient(#3f3f46 0 25%, #52525b 0 50%, #3f3f46 0 75%, #52525b 0)", backgroundSize: "16px 16px" }} />
                    </figure>
                  </div>
                  <div className="flex gap-2">
                    <button type="button" onClick={applyMatte}
                      className="flex-1 bg-violet-600 hover:bg-violet-500 rounded-lg px-3 py-1.5 text-sm">
                      {t("quality.matteUse")}
                    </button>
                    <button type="button" onClick={resetMatte}
                      className="flex-1 bg-zinc-700 hover:bg-zinc-600 rounded-lg px-3 py-1.5 text-sm">
                      {t("quality.matteCancel")}
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
          {engineId === "hunyuan-image" && (
            <p className="text-amber-400 text-sm">{t("generate.hunyuanNote")}</p>
          )}
          {useMulti ? (
            <p className="text-zinc-400 text-sm">{t("generate.multiAngleHint")}</p>
          ) : supportsBoth ? (
            <p className="text-zinc-400 text-sm">{t("generate.singleHintBoth")}</p>
          ) : (
            <p className="text-zinc-400 text-sm">{t("generate.singleHint")}</p>
          )}
        </>
      ) : (
        <>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={enhance} onChange={(e) => setEnhance(e.target.checked)} />
            {t("generate.smartPrompt")}
          </label>
          <textarea value={prompt} onChange={(e) => setPrompt(e.target.value)}
            placeholder={t("generate.promptPlaceholder")}
            className="bg-zinc-800 rounded-lg px-3 py-2 w-full h-28" />
        </>
      )}

      <button type="button" onClick={() => setShowAdv((s) => !s)}
        className="text-sm text-violet-400">
        {showAdv ? t("generate.advHide") : t("generate.advShow")}
      </button>
      {showAdv && (
        <div className="grid grid-cols-2 gap-2 text-sm bg-zinc-900 p-3 rounded-lg">
          {/* Nesne türü: prompt kalıbını yönlendirir; varsayılan jenerik "model".
              Ana akıştan Gelişmiş'e taşındı ("seçici gereksiz"). */}
          <label className="flex flex-col gap-1">
            {t("generate.typeLabel")}
            <select value={type} onChange={(e) => setType(e.target.value)} className={sel}>
              {TYPES.map((v) => <option key={v} value={v}>{t(`generate.type.${v}`)}</option>)}
            </select>
          </label>
          {engineParams.map((p) => renderParamInput(p))}
          {engineParams.length === 0 &&
            <p className="col-span-2 text-zinc-500 text-xs">{t("generate.noAdvParams")}</p>
          }
        </div>
      )}

      {/* Üretimden sonra otomatik giydir: yalnız giydirilebilir türlerde (tshirt/shirt/pants/skirt). */}
      {dressable && (
        <div className="bg-zinc-900 rounded-lg p-3 space-y-2 text-sm">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={dressOn} onChange={(e) => setDressOn(e.target.checked)} />
            {t("generate.dressToggle")}
          </label>
          {dressOn && (
            <>
              <div className="flex flex-wrap gap-1">
                {[
                  { id: "female-a", label: t("generate.dressFemale") },
                  { id: "male-a", label: t("generate.dressMale") },
                  ...customMannequins.map((m) => ({ id: m.id, label: m.label })),
                  { id: BODY_CHOICE, label: t("generate.dressFromBody") },
                ].map((o) => (
                  <button key={o.id} type="button" onClick={() => setDressChoice(o.id)}
                    className={`rounded-lg px-3 py-1 text-xs border ${
                      dressChoice === o.id
                        ? "bg-violet-600 border-violet-500 text-white"
                        : "bg-zinc-800 border-zinc-700 text-zinc-300 hover:bg-zinc-700"}`}>
                    {o.label}
                  </button>
                ))}
              </div>
              {dressChoice === BODY_CHOICE && (
                <BodyInputs value={dressBody} onChange={setDressBody} />
              )}
              {dressInvalid && <p className="text-amber-400 text-xs">{t("body.invalid")}</p>}
              <p className="text-zinc-500 text-xs">{t("generate.dressHint")}</p>
            </>
          )}
        </div>
      )}

      {kind === "image" ? (
        <button disabled={files.length === 0 || genImg.isPending || cloudLocked || dressInvalid} onClick={() => genImg.mutate()}
          className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg px-4 py-2 w-full">
          {genImg.isPending ? t("generate.submitting") : (useMulti && files.length >= 1 ? t("generate.createMulti", { n: files.length }) : t("generate.create"))}
        </button>
      ) : (
        <button disabled={!prompt.trim() || busy || cloudLocked || dressInvalid} onClick={() => gen.mutate()}
          className="bg-violet-600 hover:bg-violet-500 disabled:opacity-50 rounded-lg px-4 py-2 w-full">
          {gen.isPending ? t("generate.submitting") : t("generate.create")}
        </button>
      )}
      {gen.isError && <p className="text-red-400 text-sm">{t("generate.genError")}</p>}
      {genImg.isError && <p className="text-red-400 text-sm">{t("generate.genError")}</p>}
    </div>
  );
}
