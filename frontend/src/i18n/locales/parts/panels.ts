// i18n keys for the "panels" area (decal./style./export./color./library.). tr and en identical key sets.
export const tr: Record<string, string> = {
  // decal. — DecalEditPanel
  "decal.listTitle": "Decal'ler",
  "decal.itemLabel": "Decal {n}",
  "decal.empty": "Henüz decal yok",
  "decal.scale": "Ölçek",
  "decal.rotate": "Döndür",
  "decal.opacity": "Saydamlık",
  "decal.color": "Renk",
  "decal.reset": "sıfırla",
  "decal.move": "Taşı",
  "decal.duplicate": "Çoğalt",
  "decal.delete": "Sil",
  "decal.layerDown": "Katman ↓",
  "decal.layerUp": "Katman ↑",
  "decal.selectHint": "Düzenlemek için bir decal seç.",
  // decal. — DecalUploader
  "decal.uploadTitle": "Logo / Desen",
  "decal.uploadButton": "Görsel yükle",
  "decal.placeHint": "Yerleştirme modu — modelin üzerine tıkla.",
  "decal.cancelPlace": "iptal",

  // style. — StyleTransferPanel
  "style.title": "🎨 Stil transferi",
  "style.uploading": "yükleniyor…",
  "style.imageLabel": "Stil görseli (referans)",
  "style.dragHint": "Bölgeyi sürükleyerek seç:",
  "style.previewAlt": "stil",
  "style.aiLabel": "AI ile temizle/uyarla (FLUX) — fotoğraf ışığını/perspektifini düzeltir",
  "style.selected": "✓ Stil seçildi — aşağıdaki Çıkartma/Doku butonlarıyla uygula.",
  "style.selectRegion": "Bir bölge seç (kutu).",

  // export. — ExportMenu
  "export.button": "Dışa Aktar ▾",
  "export.glb": "GLB indir",
  "export.stl": "STL — 3D yazıcı",
  "export.obj": "OBJ — Blender",
  "export.ply": "PLY — Blender",
  "export.png": "PNG indir",
  "export.zip": "ZIP paket",

  // color. — ColorPicker
  "color.title": "Renk",

  // library. — LibraryModal
  "library.title": "Motif Kütüphanesi",
  "library.all": "Tümü",
  "library.favorites": "⭐ Favoriler",
  "library.noFavorites": "Favori motif yok (galeride ⭐ ile ekle).",
  "library.empty": "Henüz kayıtlı motif yok.",
  "library.motifFallback": "motif",
  "library.footerHint": "Bir motife tıkla → modelin üzerine tıklayarak yerleştir.",

  // view. — R2 serbest görüntüleme çözünürlüğü seçici (ScenePanel)
  "view.resolution": "Görüntü çözünürlüğü",
  "view.low": "Düşük",
  "view.medium": "Orta",
  "view.high": "Yüksek",
  "view.facesUnit": "üçgen",
  "view.facesHint": "Serbest değer: 1.000 – 1.000.000 üçgen (yüksek = daha keskin, daha yavaş).",
};

export const en: Record<string, string> = {
  // decal. — DecalEditPanel
  "decal.listTitle": "Decals",
  "decal.itemLabel": "Decal {n}",
  "decal.empty": "No decals yet",
  "decal.scale": "Scale",
  "decal.rotate": "Rotate",
  "decal.opacity": "Opacity",
  "decal.color": "Color",
  "decal.reset": "reset",
  "decal.move": "Move",
  "decal.duplicate": "Duplicate",
  "decal.delete": "Delete",
  "decal.layerDown": "Layer ↓",
  "decal.layerUp": "Layer ↑",
  "decal.selectHint": "Select a decal to edit.",
  // decal. — DecalUploader
  "decal.uploadTitle": "Logo / Pattern",
  "decal.uploadButton": "Upload image",
  "decal.placeHint": "Placement mode — click on the model.",
  "decal.cancelPlace": "cancel",

  // style. — StyleTransferPanel
  "style.title": "🎨 Style transfer",
  "style.uploading": "uploading…",
  "style.imageLabel": "Style image (reference)",
  "style.dragHint": "Drag to select a region:",
  "style.previewAlt": "style",
  "style.aiLabel": "Clean up / adapt with AI (FLUX) — corrects photo lighting and perspective",
  "style.selected": "✓ Style selected — apply it with the Decal/Texture buttons below.",
  "style.selectRegion": "Select a region (box).",

  // export. — ExportMenu
  "export.button": "Export ▾",
  "export.glb": "Download GLB",
  "export.stl": "STL — 3D printer",
  "export.obj": "OBJ — Blender",
  "export.ply": "PLY — Blender",
  "export.png": "Download PNG",
  "export.zip": "ZIP package",

  // color. — ColorPicker
  "color.title": "Color",

  // library. — LibraryModal
  "library.title": "Motif Library",
  "library.all": "All",
  "library.favorites": "⭐ Favorites",
  "library.noFavorites": "No favorite motifs (add with ⭐ in the gallery).",
  "library.empty": "No saved motifs yet.",
  "library.motifFallback": "motif",
  "library.footerHint": "Click a motif → click on the model to place it.",

  // view. — R2 free viewer resolution selector (ScenePanel)
  "view.resolution": "View resolution",
  "view.low": "Low",
  "view.medium": "Medium",
  "view.high": "High",
  "view.facesUnit": "triangles",
  "view.facesHint": "Free value: 1,000 – 1,000,000 triangles (higher = sharper, slower).",
};
