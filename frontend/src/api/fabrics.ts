import { api } from "./client";

// F4 kumaş hazır ayarları (GET /fabrics). `blender` = kumaş simülasyonu fizik
// değerleri (bilgi amaçlı; sunucu kendisi uygular), `pbr` = three.js görünümü.

export type FabricPbr = {
  base_color: string;
  roughness: number;
  metalness: number;
  sheen: number;
  sheen_roughness: number;
  sheen_color: string;
  normal_strength: number;
};

export type Fabric = {
  id: string;
  name_tr: string;
  name_en: string;
  desc_tr: string;
  blender: Record<string, number>;
  pbr: FabricPbr;
};

export type FabricList = { default: string; fabrics: Fabric[] };

export const listFabrics = () => api<FabricList>("/fabrics");

/** Kayıtlı malzeme değerinde kumaş hazır ayarı öneki: "fabric:<id>". */
export const FABRIC_MATERIAL_PREFIX = "fabric:";

export function fabricIdFromMaterial(material: string | null | undefined): string | null {
  return material && material.startsWith(FABRIC_MATERIAL_PREFIX)
    ? material.slice(FABRIC_MATERIAL_PREFIX.length) || null
    : null;
}
