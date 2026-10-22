import { useT } from "../i18n";

export function DecalUploader({
  pendingImage, setPendingImage,
}: {
  pendingImage: string | null;
  setPendingImage: (img: string | null) => void;
}) {
  const { t } = useT();
  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => setPendingImage(reader.result as string);
    reader.readAsDataURL(file);
  }

  // Decal listesi/silme artık DecalEditPanel'de (tek yerde yönetim); burada sadece yükleme.
  return (
    <div>
      <h3 className="text-sm text-zinc-400 mb-2">{t("decal.uploadTitle")}</h3>
      <label className="block bg-zinc-800 hover:bg-zinc-700 rounded-lg px-3 py-2 text-sm text-center cursor-pointer">
        {t("decal.uploadButton")}
        <input type="file" accept="image/*" className="hidden" onChange={onFile} />
      </label>
      {pendingImage && (
        <p className="text-xs text-violet-400 mt-2">
          {t("decal.placeHint")} <button
            onClick={() => setPendingImage(null)} className="underline">{t("decal.cancelPlace")}</button>
        </p>
      )}
    </div>
  );
}
