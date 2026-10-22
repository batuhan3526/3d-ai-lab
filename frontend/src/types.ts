export type Decal = {
  id: string;
  image: string; // data URL (yüklenen) VEYA sunucu URL'i (/api/projects/{id}/decals/x.png — FLUX motif)
  position: [number, number, number];
  rotation: [number, number, number];
  scale: number;
  spin?: number; // düzlem-içi dönüş (radyan), normal ekseni; vars. 0
  opacity?: number; // 0..1; vars. 1
  color?: string | null; // tint hex; yok/null = tint yok (beyaz=değişmez)
  depthFactor?: number; // projeksiyon kutusu derinliği (×meshRadius); vars. 0.30; düşük=kesik, yüksek=karşı yüzeye sızar
};

export type Customizations = {
  color: string;
  decals: Decal[];
  material?: string; // PBR malzeme preset anahtarı (mat/deri/kot/saten/parlak/metalik)
  measurements?: Measurements; // otomatik giydirme sonrası terzi ölçüleri (backend yazar; store.load() tutmaz)
};

// Terzi ölçüleri (POST /projects/{id}/fit sonrası customizations.measurements,
// ayrıca GET /projects/{id}/measurements). body_cm/ease_cm yalnız bedene karşılık gelen satırlarda.
export type MeasurementRow = {
  key: string; // chest | waist | hip | hem | length | sleeve_length | cuff
  label_tr: string;
  garment_cm: number;
  body_cm?: number;
  ease_cm?: number;
};
export type Measurements = {
  rows: MeasurementRow[];
  height_cm: number;
  cm_per_unit: number;
  mannequin_id: string;
  garment_type: string;
};

export type Project = {
  id: string;
  user_id: string;
  name: string;
  garment_type: string;
  template_id: string;
  customizations: Customizations;
  thumbnail_path: string | null;
  mesh_path: string | null;
  engine_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type Job = {
  state: "SUBMITTED" | "QUEUED" | "STARTED" | "PROGRESS" | "SUCCESS" | "FAILURE";
  stage?: string | null;
  percent?: number | null;
  project_id?: string | null;
  error?: string | null;
  decal_path?: string | null; // motif işi: üretilen şeffaf PNG (göreli yol)
};

export type TemplateItem = {
  id: string;
  name: string;
  glb: string;
  thumbnail: string;
  license: string;
  source: string;
};

export type GarmentGroup = {
  type: string;
  label: string;
  templates: TemplateItem[];
};

export type Manifest = { garments: GarmentGroup[] };

export type EngineParam = {
  key: string;
  label: string;
  type: "int" | "float" | "select" | "bool";
  default: number | boolean | null;
  min?: number;
  max?: number;
  step?: number;
  options?: number[];
  desc?: string;
};

export type EngineSpec = {
  id: string;
  label: string;
  description: string;
  capabilities: string[];
  kind: "text" | "image" | "edit";
  quality_presets: string[];
  vram_estimate_mb: number;
  license: string;
  params: EngineParam[];
  presets: Record<string, Record<string, number>>;
  gpus: number[];
  default_gpu?: number; // backend'in DEFAULT_GPU'su — GPU seçilmezse bu kullanılır (tek-GPU sözleşmesi)
  precisions: string[];
  device_modes: string[];
  recommended: string; // "" | "kalite" | "hız" — Önerilen rozet
  available?: boolean; // backend /engines: worker offline/ckpt yok ise false → listeden ele
  commercial_use?: boolean; // lisans ticari kullanıma izin veriyor mu
  cloud?: boolean; // bulut API motoru (id "cloud-" ile başlar; gpus=[], vram 0)
  requires_key?: string; // gereken env anahtarı adı (örn. "TRIPO_API_KEY")
  key_set?: boolean; // anahtar .env'de tanımlı mı (false → kilitli)
  price_note?: string; // örn. "~$0.20 / model"
};

export type Advanced = Record<string, number | boolean | undefined>;

export type GenerateParams = {
  prompt: string;
  garment_type: string;
  engine_id: string;
  gpu: number;
  quality: string;
  prompt_enhance: boolean;
  advanced: Advanced | null;
  precision?: string;
  device_mode?: string;
};

// Otomatik giydirme seçeneği: hazır/özel manken id'si YA DA ölçüler (backend uygun mankeni bulur/üretir).
export type DressOption = {
  mannequin_id?: string;
  body?: { gender: "female" | "male"; height_cm: number; chest_cm: number; waist_cm: number; hip_cm: number };
};

// Yalnız bu kıyafet türleri giydirilebilir (backend diğerlerinde 422 döner).
export const DRESSABLE_TYPES = ["tshirt", "shirt", "pants", "skirt"] as const;

export type GpuStatus = {
  family: string;
  gpu: number;
  online: boolean;
  loaded: string[];
  reserved_mb: number;
  allocated_mb: number;
};
