import { create } from "zustand";
import { listFabrics, type Fabric } from "../api/fabrics";

// Kumaş kataloğu önbelleği (GET /fabrics). Zustand — React context'e bağlı değil,
// bu yüzden R3F <Canvas> içindeki GarmentMesh de okuyabilir. load() idempotent:
// bir kez çeker; hata olursa sessizce boş kalır (kumaş seçici kendi hatasını gösterir).
type FabricCatalogState = {
  fabrics: Fabric[] | null;
  defaultId: string | null;
  error: string | null;
  loading: boolean;
  load: () => Promise<void>;
};

export const useFabricCatalog = create<FabricCatalogState>((set, get) => ({
  fabrics: null,
  defaultId: null,
  error: null,
  loading: false,
  load: async () => {
    if (get().fabrics || get().loading) return;
    set({ loading: true, error: null });
    try {
      const res = await listFabrics();
      set({ fabrics: res.fabrics, defaultId: res.default, loading: false });
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e), loading: false });
    }
  },
}));
