import { ThreeCanvas } from "./ThreeCanvas";
import type { Version } from "../api/versions";
import { useT } from "../i18n";

export function CompareModal({
  glbUrl, version, onClose,
}: {
  glbUrl: string;
  version: Version;
  onClose: () => void;
}) {
  const { t } = useT();
  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex flex-col" onClick={onClose}>
      <div className="flex items-center justify-between px-5 py-3 text-zinc-200" onClick={(e) => e.stopPropagation()}>
        <span className="font-medium">{t("compare.title")}</span>
        <button onClick={onClose} className="text-zinc-400 hover:text-zinc-200 text-xl">×</button>
      </div>
      <div className="flex-1 flex gap-2 px-3 pb-3 overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="flex-1 flex flex-col bg-zinc-950 rounded-lg overflow-hidden">
          <div className="text-center text-xs text-zinc-400 py-1">{t("compare.versionLabel", { name: version.name })}</div>
          <div className="flex-1">
            <ThreeCanvas url={glbUrl}
              colorOverride={version.customizations.color}
              decalsOverride={version.customizations.decals} />
          </div>
        </div>
        <div className="flex-1 flex flex-col bg-zinc-950 rounded-lg overflow-hidden">
          <div className="text-center text-xs text-zinc-400 py-1">{t("compare.current")}</div>
          <div className="flex-1">
            <ThreeCanvas url={glbUrl} />
          </div>
        </div>
      </div>
    </div>
  );
}
