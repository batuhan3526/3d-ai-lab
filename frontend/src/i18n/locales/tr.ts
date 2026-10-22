// Turkish strings for 3D Studio. Keys are "<area>.<purpose>" dot paths and must
// stay in sync with en.ts (same key set). The seed below holds brand/common/login;
// the rest is composed from per-area part files under ./parts.
import { tr as designer } from "./parts/designer";
import { tr as generate } from "./parts/generate";
import { tr as scene } from "./parts/scene";
import { tr as metrics } from "./parts/metrics";
import { tr as catalog } from "./parts/catalog";
import { tr as panels } from "./parts/panels";
import { tr as misc } from "./parts/misc";
import { tr as users } from "./parts/users";
import { tr as quality } from "./parts/quality";
import { tr as mannequin } from "./parts/mannequin";
import { tr as exporting } from "./parts/exporting";
import { tr as pbr } from "./parts/pbr";
import { tr as sewing } from "./parts/sewing";
import { tr as outputs } from "./parts/outputs";
import { tr as atelier } from "./parts/atelier";

const seed: Record<string, string> = {
  // Brand / common
  "brand.name": "3D Studio",
  "common.back": "Geri",
  "common.cancel": "İptal",
  "common.save": "Kaydet",
  "common.close": "Kapat",
  "common.loading": "Yükleniyor…",
  "common.delete": "Sil",
  "common.retry": "Tekrar dene",

  // Login
  "login.title": "3D Studio",
  "login.tokenLabel": "Erişim anahtarı (token)",
  "login.tokenPlaceholder": "Bearer token",
  "login.submit": "Giriş",
};

export const tr: Record<string, string> = {
  ...seed,
  ...designer,
  ...generate,
  ...scene,
  ...metrics,
  ...catalog,
  ...panels,
  ...misc,
  ...users,
  ...quality,
  ...mannequin,
  ...exporting,
  ...pbr,
  ...sewing,
  ...outputs,
  ...atelier,
};
