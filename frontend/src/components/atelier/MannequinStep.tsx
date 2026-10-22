import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useT } from "../../i18n";
import { assetUrl } from "../../api/client";
import { createCustomMannequin, deleteCustomMannequin, listMannequins, type MannequinEntry } from "../../api/mannequins";
import { BodyForm, BODY_DEFAULTS, toBody, type BodyDraft } from "./BodyForm";
import { GlbPreview } from "./GlbPreview";
import { ErrorBox, Section, btnDanger, btnPrimary, btnSecondary, friendlyError, inputCls } from "./common";

// Adım 4 — Manken (F3): 5 ölçüden kişiye özel manken üret → 3D önizleme +
// hedef/ölçülen değer tablosu; kayıtlı özel mankenler (önizle / sil).

function MeasuredTable({ m }: { m: MannequinEntry }) {
  const { t } = useT();
  if (!m.body || !m.measured) return null;
  const rows: { label: string; want: number; got: number }[] = [
    { label: t("atelier.body.height"), want: m.body.height_cm, got: m.measured.height_cm },
    { label: t("atelier.body.chest"), want: m.body.chest_cm, got: m.measured.chest_cm },
    { label: t("atelier.body.waist"), want: m.body.waist_cm, got: m.measured.waist_cm },
    { label: t("atelier.body.hip"), want: m.body.hip_cm, got: m.measured.hip_cm },
  ];
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-zinc-400 text-left">
          <th className="py-1.5 font-normal"></th>
          <th className="py-1.5 font-normal">{t("atelier.mq.wanted")}</th>
          <th className="py-1.5 font-normal">{t("atelier.mq.measured")}</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-zinc-800">
        {rows.map((r) => (
          <tr key={r.label}>
            <td className="py-2 text-zinc-300">{r.label}</td>
            <td className="py-2 text-zinc-100">{r.want.toFixed(1)} cm</td>
            <td className="py-2 text-zinc-100">{r.got.toFixed(1)} cm</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function MannequinStep() {
  const { t } = useT();
  const qc = useQueryClient();
  const listQ = useQuery({ queryKey: ["mannequins"], queryFn: listMannequins, retry: false });
  const [body, setBody] = useState<BodyDraft>(BODY_DEFAULTS.female);
  const [label, setLabel] = useState("");
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const customs = (listQ.data ?? []).filter((m) => m.custom);
  const preview = (listQ.data ?? []).find((m) => m.id === previewId) ?? null;

  const createMut = useMutation({
    mutationFn: async () => {
      setError(null);
      const b = toBody(body);
      if (!b) throw new Error(t("atelier.body.invalid"));
      return createCustomMannequin({ ...b, ...(label.trim() ? { label: label.trim() } : {}) });
    },
    onSuccess: async (m) => {
      // Listeyi yenile, sonra yeni mankeni önizle (liste gelmeden de önizleme
      // çalışsın diye dönüşü önbelleğe ekle).
      qc.setQueryData<MannequinEntry[]>(["mannequins"], (old) => [...(old ?? []).filter((x) => x.id !== m.id), m]);
      setPreviewId(m.id);
      setLabel("");
      await qc.invalidateQueries({ queryKey: ["mannequins"] });
    },
    onError: (e) => setError(friendlyError(e, t)),
  });

  const delMut = useMutation({
    mutationFn: (id: string) => deleteCustomMannequin(id),
    onSuccess: (_r, id) => {
      if (id === previewId) setPreviewId(null);
      qc.invalidateQueries({ queryKey: ["mannequins"] });
    },
  });

  return (
    <div className="space-y-5">
      <Section title={t("atelier.mq.title")} hint={t("atelier.mq.hint")}>
        <BodyForm value={body} onChange={setBody} />
        <label className="block space-y-1">
          <span className="text-sm text-zinc-300">{t("atelier.mq.label")}</span>
          <input value={label} onChange={(e) => setLabel(e.target.value)} maxLength={60}
            placeholder={t("atelier.mq.labelPlaceholder")} className={inputCls} />
        </label>
        <ErrorBox message={error} />
        <button type="button" disabled={createMut.isPending} onClick={() => createMut.mutate()} className={`${btnPrimary} w-full`}>
          {createMut.isPending ? t("atelier.mq.creating") : t("atelier.mq.create")}
        </button>
      </Section>

      {preview && (
        <Section title={preview.label}>
          <GlbPreview url={assetUrl(preview.file)} />
          <p className="text-xs text-zinc-500">{t("atelier.mq.previewHint")}</p>
          <MeasuredTable m={preview} />
        </Section>
      )}

      <Section title={t("atelier.mq.savedTitle")}>
        {listQ.isLoading && <p className="text-sm text-zinc-400">{t("common.loading")}</p>}
        <ErrorBox message={listQ.error ? friendlyError(listQ.error, t) : null} />
        <ErrorBox message={delMut.error ? friendlyError(delMut.error, t) : null} />
        {listQ.data && customs.length === 0 && <p className="text-sm text-zinc-500">{t("atelier.mq.savedEmpty")}</p>}
        <ul className="space-y-2">
          {customs.map((m) => (
            <li key={m.id}
              className={`flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 ${m.id === previewId
                ? "border-violet-500 bg-violet-950/30" : "border-zinc-800 bg-zinc-900"}`}>
              <span className="min-w-0 flex-1 text-base text-zinc-100">{m.label}</span>
              <button type="button" onClick={() => setPreviewId(m.id)} className={btnSecondary}>{t("atelier.mq.view")}</button>
              <button type="button" disabled={delMut.isPending}
                onClick={() => { if (window.confirm(t("atelier.mq.confirmDelete", { name: m.label }))) delMut.mutate(m.id); }}
                className={btnDanger}>
                {t("common.delete")}
              </button>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
