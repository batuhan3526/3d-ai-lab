// English strings for 3D Studio. Keys are "<area>.<purpose>" dot paths and must
// stay in sync with tr.ts (same key set). The seed below holds brand/common/login;
// the rest is composed from per-area part files under ./parts.
import { en as designer } from "./parts/designer";
import { en as generate } from "./parts/generate";
import { en as scene } from "./parts/scene";
import { en as metrics } from "./parts/metrics";
import { en as catalog } from "./parts/catalog";
import { en as panels } from "./parts/panels";
import { en as misc } from "./parts/misc";
import { en as users } from "./parts/users";
import { en as quality } from "./parts/quality";
import { en as mannequin } from "./parts/mannequin";
import { en as exporting } from "./parts/exporting";
import { en as pbr } from "./parts/pbr";
import { en as sewing } from "./parts/sewing";
import { en as outputs } from "./parts/outputs";
import { en as atelier } from "./parts/atelier";

const seed: Record<string, string> = {
  // Brand / common
  "brand.name": "3D Studio",
  "common.back": "Back",
  "common.cancel": "Cancel",
  "common.save": "Save",
  "common.close": "Close",
  "common.loading": "Loading…",
  "common.delete": "Delete",
  "common.retry": "Retry",

  // Login
  "login.title": "3D Studio",
  "login.tokenLabel": "Access key (token)",
  "login.tokenPlaceholder": "Bearer token",
  "login.submit": "Sign in",
};

export const en: Record<string, string> = {
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
