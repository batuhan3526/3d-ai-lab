# Showcase: red "New Look" dress / Vitrin: kırmızı "New Look" elbise

[English](#english) · [Türkçe](#türkçe)

![Final dress](08-final-front.png)

---

## English

An end-to-end example built **only with this repository and locally running models**
(no cloud engines): concept image → 3D model → dressed on a mannequin → real sewing
patterns → cutting plan → pattern sewn in 3D. Every screenshot below comes from the
real app; nothing was retouched. Where something did not work well, it says so
([Honest notes](#honest-notes)).

**Design brief:** a 1950s Dior "New Look"-inspired red satin cocktail dress — fitted
sleeveless bodice, square/boat neckline, a narrow waist and a full circle skirt falling
below the knee.

**Machine:** WSL2 (Ubuntu 24.04), 2× RTX 3090 24 GB, 78 GB RAM. The two GPUs were used
in parallel; every step also runs on a single GPU, just one after another.

> **Licenses.** For this example the best local models were used regardless of license.
> FLUX.1-dev is **non-commercial**, Hunyuan3D-2.1 has territory/MAU restrictions,
> SAM 3D Objects uses Meta's SAM License. Check [`docs/LICENSES.md`](../../LICENSES.md)
> before using any of them in a product.

### 1. Start

![Dashboard](01-dashboard.png)

Dashboard with live system metrics (CPU, RAM, disk, both GPUs).

### 2. Concept image with FLUX.1-dev

![Final concept](03a-flux-concept-final.png)

![Five variations](03b-flux-variants.png)

Five variations from the motif generator (FLUX.1-dev). With the model already loaded each
image took **~65–70 s**; the first one took ~5 min because it included loading the model.
Both GPUs ran at the same time.

What we learned about the prompt: the phrase *"ghost mannequin"* made FLUX draw a dress
form stand **every time** (variations 1–3). Describing the garment as *"nothing inside it
and nothing holding it, hollow"* removed the stand (variations 4–5). Variation 5 won:
a clean silhouette, a visible circle skirt and an even background.

### 3. Pick an engine, photo → 3D

![Model catalog](02-model-catalog.png)

![Photo to 3D form](04-generate-photo-to-3d.png)

The concept image is uploaded on the "Design with a photo" screen, with **"Dress on
mannequin after generation"** turned on (female mannequin).

![Progress](05-progress.png)

### 4. Engine comparison

![TRELLIS vs Hunyuan3D-2.1](06-engine-comparison-trellis-vs-hunyuan.png)

The same image was sent to three engines:

| Engine | GPU | Time | Result |
|---|---|---|---|
| TRELLIS image→3D | 1 | 252 s | Average: dark streaks and gaps in the skirt, skirt too short |
| **Hunyuan3D-2.1 (PBR textured)** | 0 | ~460 s (shape + paint) | **Winner:** clean geometry, PBR texture, faithful color |
| SAM 3D Objects | 1 | 277 s | See below |

![SAM 3D candidate](06b-sam3d-candidate.png)

SAM 3D Objects (third candidate, added later) gives a good silhouette, but the texture
shifts toward a dark magenta (median texel RGB 92/5/43 vs. 155/0/15 in the concept)
and the mesh is sparse (16k vertices). Hunyuan3D-2.1 stayed the winner.

### 4b. Same dress, every local engine, on the mannequin

![The same concept image through every local engine, dressed automatically](14-engines-dressed.png)

The same concept image was sent to every installed image→3D engine with *dress on the
mannequin* switched on; nothing was adjusted by hand. One GPU, engines run one after
another.

| Engine | Time (GPU 1) | Result |
|---|---|---|
| **TRELLIS.2** (added later) | ~80 s (40 s shape + texture, 40 s export) | Cleanest shape; closed, believable back; arms out of the armholes. Some grey texture blotches on the bodice |
| Pixal3D (added later) | ~4 min (low-VRAM mode) | Follows the photo's perspective: skirt swept back, a small loose fragment |
| Hunyuan3D-2.1 textured | ~460 s (shape + paint) | The winner above: clean shape, PBR texture |
| Hunyuan3D-2.1 shape | 87 s | Same clean shape, no texture (white) |
| TRELLIS | 189 s | Good fit; the skirt has dark streaks and holes |
| SAM 3D Objects | 272 s | Good fit; colour drifts to magenta |
| Hi3DGen | 143 s | Shorter dress, crumpled straps, no texture |
| Stable Fast 3D | 190 s | Lumpy surface, skirt too wide at the back |
| TripoSR | 20 s | Fastest; low detail, blobby, closed neckline |

Every engine's dress now sits on the shoulders with the arms out of the armholes. Two
general fixes came out of this test (they help every garment, not just this dress):
TripoSR models were exported lying on their side (its axis was not converted to glTF's
Y-up), and with a very full skirt the arm search mistook the skirt around a hanging arm
for a sleeve and left the arm inside the dress (Stable Fast 3D). A sleeve now has to
start at the shoulder.

TRELLIS.2 and Pixal3D were added afterwards (both need access to Meta's gated DINOv3
encoder on Hugging Face). TRELLIS.2 keeps garments as open surfaces, which is the right
shape for clothing, and gave the best result here; its single-layer fabric is exported
double-sided so the viewer shows both faces. Pixal3D estimates the camera from the photo;
for studio product shots a narrow field of view (`fov` 0.2 in its advanced settings)
reduced the distortion and removed the loose fragment in a test.

### 5. Dressed on the mannequin

![Designer](07-designer-dressed.png)

![Front](08-final-front.png)

![Three-quarter](09-final-three-quarter.png)

Material: *Satin*. Color: white, because the color multiplies the texture and the red
comes from the texture itself. The mannequin is placed by the **automatic fit**, no
manual adjustment: straps on the shoulders, the dress's narrowest point at the waist,
the body inside the dress seen from the side, the arms come out of the armholes and
hang outside the skirt. Result: dress length **83 cm** (shoulder to hem), hem at the
knee, waist 66 cm, matching the brief.

### 5b. All angles

![360° turntable](views/turntable.gif)

![Six angles](views/00-grid.png)

| | | |
|---|---|---|
| ![Front](views/01-front.png) | ![Three-quarter left](views/02-three-quarter-left.png) | ![Side](views/03-side.png) |
| ![Back](views/04-back.png) | ![Three-quarter right](views/05-three-quarter-right.png) | ![High angle](views/06-high-angle.png) |

Same scene as above (Studio light, app background); the camera orbits in exact 10°
steps. The side view shows the fit: the bodice wraps the body, the dress does not
float in front of it, and the arms do not pass through the fabric. **The back is the weak side:** the model was made from a single front image, so
the engine had to invent the back. It came out as a large open back with a shapeless
ruffle-like lump on the skirt. It is left as is, not retouched.

### 6. Atelier: real sewing patterns

Body measurements: woman, height 165, chest 88, waist 66, hips 94 cm. The rest of the
measurements are estimated from these.

![Bodice pattern](10-atelier-bodice-pattern.png)

**Bodice** (FreeSewing *Bella* block): back ×2, front on the fold, sleeve ×2. It can be
downloaded as a printable PDF (A4, true scale, 10 cm test square) or SVG.

![Skirt options](11b-atelier-skirt-options.png)

![Circle skirt pattern](11-atelier-skirt-pattern.png)

**Circle skirt** (FreeSewing *Sandy*): length *Midi*, flare *half circle*, and the new
**"Sits at" → "Waist"** option, which matches the New Look's natural waist.

### 7. Lay on fabric

![150 cm too narrow](12a-atelier-fabric-150-too-narrow.png)

A midi half-circle skirt opens to **182 cm**, so it does not fit typical 150 cm satin.
The app says so instead of producing a broken plan.

![Cutting plan on 190 cm](12b-atelier-fabric-layout-190.png)

On 190 cm fabric: buy **91.6 cm**, utilization **75.3 %**.

### 8. Sew the pattern in 3D

![Sewn skirt on mannequin](13a-atelier-3d-sewn-skirt-fit.png)

The skirt pattern sewn on the mannequin with the silk preset, 160 frames (Blender cloth
simulation, CPU, ~70 s). The waist sits at the waist and the half-circle drapes outward.

![In the designer, red satin](13b-designer-red-satin-skirt.png)

Opened in the designer with the dress red (`#a50d1a`) and *Satin*.

![Before / after the fix](13c-sew-fit-before-after.png)

**Left:** the first attempt. **Right:** after the fix made while building this example.
The skirt used to slide down to the hips with a crumpled waist edge. Two causes:

1. Sandy cuts the waistband **halfway between waist and hips** by default
   (`waistbandPosition` 50 %: 74 cm on a 66 cm waist), but the simulator placed it at
   the waist. → New **"Sits at"** option (*Waist* / *Between waist and hips*). The
   skirt is now placed at the height where the body girth equals the skirt's waist.
2. The waist ring started as an ellipse with a 3 cm gap on an inflated body profile,
   which stretched it by 30–50 %. → The ring now follows the real body cross-section
   (convex hull = tape measure) with a 1 cm gap, and each ring is laid out by arc
   length, so circumferential stretch starts at 1.00 ± 1 %.

Edge stretch p95 went from **1.20 → 1.03**; seam gap p95 is 0.55 mm.

### Honest notes

- **The back of the dress is invented** (single front image): open back and a shapeless
  lump on the skirt, see [All angles](#5b-all-angles). Multi-view input (several photos or
  generated back/side views) would be the fix.
- **No "dress" garment type yet.** The dress was generated as *shirt*. Chest, waist and
  length are now correct (92 / 66 / 83 cm), but the straps are still reported as
  "sleeves" (sleeve length / cuff rows do not apply to this dress).
- **The automatic mannequin fit was rewritten** (2026-10-24). The old fit guessed
  landmarks (armpit, hem, fixed ease) and failed on this dress: the straps were taken
  for sleeves and the dress's waist for the armpit, so the dress sat high and in front
  of the body. The new fit searches scale and position so the body fits inside the
  fabric, ignoring the depth that single-image engines flatten. The arm pose avoids
  cutting through the fabric (out of the armholes, outside a full skirt; inside the
  sleeves for sleeved garments). Generated bodices are usually wider than the body, so
  with the arm hanging naturally its root still cut through the side of the bodice and
  the arm seemed to come out of the fabric rather than the armhole; below the armpit
  that fabric is now moved between the arm and the body, as it sits on a real person.
  Tight sleeves on sleeved garments (coats, jackets) can still touch the arm. It was checked on 70
  generated garments (t-shirts, shirts, hoodies, jackets, coats, five dresses, skirts,
  trousers, shorts); models that are not garments (a full human figure, a pile lying
  flat, a vase) are now rejected with a clear message.
- **The mannequin's chest is measured low** (70.9 cm body chest in the fit report vs 88 cm).
- **The waistband is not sewn in 3D.** The pattern has one, but it has no seam partner in
  the 3D sewing data, so it is skipped (the job report says so).
- **The skirt hem still curls inward slightly** in the simulation. It is much better
  after the fix, but not perfect.
- **A midi circle skirt needs 182 cm fabric.** In real life you would cut it in two
  panels with side seams; the app cannot split pieces yet.
- **The 3D sewn skirt and the AI-generated dress are separate projects.** The atelier
  sews the skirt only; the bodice block (Bella) has no 3D sewing yet.

### Reproduce

```bash
bash infra/scripts/start-linux.sh            # gateway, frontend, engine workers
# Concept:  Designer → Motif (FLUX.1-dev), describe the garment as "hollow, nothing holding it"
# 3D:       New design → Hunyuan3D-2.1 (PBR textured) → upload image → dress on mannequin
# Atelier:  Atelier → Circle skirt → Advanced: Length=Midi, Sits at=Waist → Create pattern
#           → Lay on fabric (190 cm) → Sew in 3D (Silk, Advanced: frames 160)
```

---

## Türkçe

Yalnızca bu repo ve **yerelde çalışan modellerle** (bulut motoru yok) baştan sona yapılmış
bir örnek: konsept görsel → 3D model → mankene giydirme → gerçek dikiş kalıpları → kesim
planı → kalıbın 3D'de dikilmesi. Aşağıdaki tüm ekran görüntüleri gerçek uygulamadan
alındı, rötuş yok. İyi çalışmayan yerler ayrıca yazıldı ([Dürüst notlar](#dürüst-notlar)).

**Tasarım:** 1950'lerin Dior "New Look" esintili kırmızı saten kokteyl elbisesi. Dar,
kolsuz korsaj, kare/kayık yaka, ince bel ve diz altına inen tam kloş etek.

**Makine:** WSL2 (Ubuntu 24.04), 2× RTX 3090 24 GB, 78 GB RAM. İki GPU paralel kullanıldı;
her adım tek GPU'da da çalışır, sadece sırayla.

> **Lisanslar.** Bu örnekte lisansa bakılmadan en iyi yerel modeller kullanıldı.
> FLUX.1-dev **ticari olmayan** lisanslıdır, Hunyuan3D-2.1'in bölge/kullanıcı sınırları
> var, SAM 3D Objects Meta'nın SAM lisansını kullanır. Bir üründe kullanmadan önce
> [`docs/LICENSES.md`](../../LICENSES.md) dosyasına bakın.

### 1. Başlangıç

![Panel](01-dashboard.png)

Canlı sistem metrikleriyle panel (CPU, RAM, disk, iki GPU).

### 2. FLUX.1-dev ile konsept görsel

![Son konsept](03a-flux-concept-final.png)

![Beş varyasyon](03b-flux-variants.png)

Motif üreticiyle (FLUX.1-dev) beş varyasyon üretildi. Model yüklüyken her görsel
**~65–70 sn** sürdü; ilki model yüklemesiyle birlikte ~5 dk. İki GPU aynı anda çalıştı.

Prompt dersi: *"ghost mannequin"* ifadesi FLUX'a **her seferinde** manken standı
çizdirdi (1–3. varyasyonlar). Kıyafeti *"nothing inside it and nothing holding it,
hollow"* diye tarif edince stand kayboldu (4–5). Kazanan 5. varyasyon: temiz siluet,
belirgin kloş etek, düz arka plan.

### 3. Motor seç, fotoğraftan 3D

![Model kataloğu](02-model-catalog.png)

![Fotoğrafla tasarla](04-generate-photo-to-3d.png)

Konsept görsel "Fotoğrafla tasarla" ekranında yüklendi; **"Üretimden sonra mankene
giydir"** açık (kadın manken).

![İlerleme](05-progress.png)

### 4. Motor karşılaştırması

![TRELLIS ve Hunyuan3D-2.1](06-engine-comparison-trellis-vs-hunyuan.png)

Aynı görsel üç motora gönderildi:

| Motor | GPU | Süre | Sonuç |
|---|---|---|---|
| TRELLIS foto→3D | 1 | 252 sn | Orta: etekte koyu çizgiler ve boşluklar, etek kısa |
| **Hunyuan3D-2.1 (PBR dokulu)** | 0 | ~460 sn (şekil + boya) | **Kazanan:** temiz geometri, PBR doku, renge sadık |
| SAM 3D Objects | 1 | 277 sn | Aşağıda |

![SAM 3D adayı](06b-sam3d-candidate.png)

SAM 3D Objects (sonradan eklenen üçüncü aday) silueti iyi çıkarıyor. Ama doku koyu
macentaya kayıyor (doku medyanı RGB 92/5/43, konseptte 155/0/15) ve mesh seyrek
(16 bin vertex). Kazanan yine Hunyuan3D-2.1.

### 4b. Aynı elbise, tüm yerel motorlar, mankende

![Aynı konsept görsel tüm yerel motorlardan, otomatik giydirilmiş](14-engines-dressed.png)

Aynı konsept görsel, *mankene giydir* açıkken kurulu tüm görselden 3D motorlarına
gönderildi; elle hiçbir ayar yapılmadı. Tek GPU, motorlar sırayla.

| Motor | Süre (GPU 1) | Sonuç |
|---|---|---|
| **TRELLIS.2** (sonradan eklendi) | ~80 sn (40 sn şekil + doku, 40 sn dışa aktarma) | En temiz şekil; sırt kapalı ve inandırıcı, kollar kol oyuğundan çıkıyor. Korsajda gri doku lekeleri var |
| Pixal3D (sonradan eklendi) | ~4 dk (düşük VRAM modu) | Fotoğrafın perspektifini izliyor: etek arkaya savrulmuş, küçük kopuk bir parça var |
| Hunyuan3D-2.1 dokulu | ~460 sn (şekil + boya) | Yukarıdaki kazanan: temiz şekil, PBR doku |
| Hunyuan3D-2.1 şekil | 87 sn | Aynı temiz şekil, dokusuz (beyaz) |
| TRELLIS | 189 sn | İyi oturuyor; etekte koyu çizgiler ve delikler |
| SAM 3D Objects | 272 sn | İyi oturuyor; renk macentaya kayıyor |
| Hi3DGen | 143 sn | Elbise kısa, askılar buruşuk, dokusuz |
| Stable Fast 3D | 190 sn | Yüzey topak topak, etek arkada fazla geniş |
| TripoSR | 20 sn | En hızlı; az detay, şişkin, yaka kapalı |

Artık her motorun elbisesi omuzlara oturuyor, kollar kol oyuğundan çıkıyor. Bu denemeden
iki genel düzeltme çıktı (yalnız bu elbiseye değil, tüm kıyafetlere yarıyor): TripoSR
modelleri yan yatık dışa aktarılıyordu (ekseni glTF'in Y-yukarı eksenine çevrilmemişti);
çok bol etekte kol araması, aşağı sarkan kolu saran eteği kolluk sanıp kolu elbisenin
içinde bırakıyordu (Stable Fast 3D). Artık kolluk omuzdan başlamak zorunda.

TRELLIS.2 ve Pixal3D sonradan eklendi (ikisi de Meta'nın Hugging Face'teki erişim izinli
DINOv3 kodlayıcısını ister). TRELLIS.2 kıyafeti açık yüzey olarak üretiyor, bu da kıyafet
için doğru şekil; burada en iyi sonucu verdi. Tek katman kumaşı çift taraflı dışa
aktarılıyor ki görüntüleyici iki yüzü de göstersin. Pixal3D kamerayı fotoğraftan tahmin
ediyor; stüdyo ürün fotoğraflarında dar görüş açısı (gelişmiş ayarlarda `fov` 0.2) bir
denemede bozulmayı azalttı ve kopuk parçayı kaldırdı.

### 5. Mankende

![Tasarımcı](07-designer-dressed.png)

![Önden](08-final-front.png)

![Üç çeyrek](09-final-three-quarter.png)

Malzeme: *Saten*. Renk: beyaz, çünkü renk dokuyla çarpılıyor ve kırmızı dokunun
kendisinden geliyor. Manken **otomatik oturtmayla** yerleşti, elle ayar yok: askılar
omuzda, elbisenin en dar yeri belde, yandan bakınca gövde elbisenin içinde; kollar kol
oyuğundan çıkıp eteğin dışından iniyor. Sonuç: elbise boyu **83 cm** (omuzdan etek ucuna),
etek ucu dizde, bel 66 cm; tasarıma uygun.

### 5b. Tüm açılar

![360° döner](views/turntable.gif)

![Altı açı](views/00-grid.png)

| | | |
|---|---|---|
| ![Ön](views/01-front.png) | ![Üç çeyrek sol](views/02-three-quarter-left.png) | ![Yan](views/03-side.png) |
| ![Arka](views/04-back.png) | ![Üç çeyrek sağ](views/05-three-quarter-right.png) | ![Üstten](views/06-high-angle.png) |

Yukarıdakiyle aynı sahne (Stüdyo ışığı, uygulamanın arka planı); kamera tam 10°'lik
adımlarla döndürüldü. Yandan görünüm oturmayı gösteriyor: korsaj gövdeyi sarıyor, elbise
gövdenin önünde durmuyor, kollar kumaşın içinden geçmiyor. **Zayıf taraf sırt:** model tek bir önden görselden üretildiği için
motor arkayı kendisi uydurmak zorunda kaldı. Sonuç: büyük bir açık sırt ve eteğin arkasında
fırfır benzeri şekilsiz bir kütle. Rötuşlanmadan bırakıldı.

### 6. Atölye: gerçek dikiş kalıbı

Ölçüler: kadın, boy 165, göğüs 88, bel 66, kalça 94 cm. Diğer ölçüler bunlardan tahmin
ediliyor.

![Korsaj kalıbı](10-atelier-bodice-pattern.png)

**Korsaj** (FreeSewing *Bella* temel kalıbı): arka ×2, ön kumaş katında, kol ×2.
Yazdırmaya hazır PDF (A4, gerçek boyut, 10 cm test karesi) ya da SVG olarak inebilir.

![Etek seçenekleri](11b-atelier-skirt-options.png)

![Kloş etek kalıbı](11-atelier-skirt-pattern.png)

**Kloş etek** (FreeSewing *Sandy*): boy *Midi*, bolluk *yarım daire* ve New Look'un doğal
beline uyan yeni **"Oturduğu yer" → "Belde"** seçeneği.

### 7. Kumaşa yerleştirme

![150 cm dar](12a-atelier-fabric-150-too-narrow.png)

Midi boy yarım kloş etek açıldığında **182 cm** genişliğe ulaşıyor; tipik 150 cm saten
ene sığmıyor. Uygulama bozuk bir plan çıkarmak yerine bunu söylüyor.

![190 cm kesim planı](12b-atelier-fabric-layout-190.png)

190 cm ende: **91,6 cm** kumaş alınmalı, verim **%75,3**.

### 8. Kalıbı 3D'de dik

![Mankende dikilmiş etek](13a-atelier-3d-sewn-skirt-fit.png)

Etek kalıbı mankene ipek hazır ayarıyla, 160 karede dikildi (Blender kumaş simülasyonu,
CPU, ~70 sn). Bel belde oturuyor, yarım kloş dışa doğru dökülüyor.

![Tasarımcı'da kırmızı saten](13b-designer-red-satin-skirt.png)

Tasarımcı'da elbisenin kırmızısı (`#a50d1a`) ve *Saten* ile açıldı.

![Düzeltme öncesi / sonrası](13c-sew-fit-before-after.png)

**Sol:** ilk deneme. **Sağ:** bu örnek hazırlanırken yapılan düzeltmeden sonra. Etek
eskiden kalçaya kayıyor, bel kenarı buruşuyordu. İki sebep vardı:

1. Sandy bel bandını varsayılan olarak **bel ile kalçanın ortasına göre** keser
   (`waistbandPosition` %50; 66 cm bele 74 cm), simülasyon ise eteği bele koyuyordu.
   → Yeni **"Oturduğu yer"** seçeneği (*Belde* / *Bel ile kalça arası*). Etek artık
   gövde çevresinin etek beline eşit olduğu yüksekliğe yerleştiriliyor.
2. Bel halkası genişletilmiş gövde profili üzerinde 3 cm boşlukla, elips olarak
   başlıyordu ve %30–50 geriliyordu. → Halka artık gövdenin gerçek kesitini (konveks zarf
   = mezura) 1 cm boşlukla izliyor ve her halka yay uzunluğuna göre dağıtılıyor;
   çevresel uzama 1,00 ± %1 ile başlıyor.

Kenar uzaması p95 **1,20 → 1,03**; dikiş boşluğu p95 0,55 mm.

### Dürüst notlar

- **Elbisenin sırtı uydurma** (tek önden görsel): açık sırt ve eteğin arkasında şekilsiz bir
  kütle, bkz. [Tüm açılar](#5b-tüm-açılar). Çözüm çoklu görünüm girdisi olur (birkaç fotoğraf
  ya da üretilmiş arka/yan görünümler).
- **Henüz "elbise" kıyafet türü yok.** Elbise *gömlek (shirt)* olarak üretildi. Göğüs, bel
  ve boy artık doğru (92 / 66 / 83 cm), ama askılar hâlâ "kol" diye ölçülüyor (kol boyu /
  kol ağzı satırları bu elbise için geçersiz).
- **Otomatik manken oturtması yeniden yazıldı** (2026-10-24). Eski kod işaret noktası
  tahmin ediyordu (koltuk altı, etek ucu, sabit bolluk) ve bu elbisede bozuluyordu: askılar
  kol, elbisenin beli koltuk altı sanıldığı için elbise yüksekte ve gövdenin önünde
  duruyordu. Yeni kod ölçek ve konumu, gövde kumaşın içine sığacak şekilde arıyor; tek
  görselden üretilen motorların basık bıraktığı derinliğe güvenmiyor. Kol pozu kumaşı
  kesmeyecek şekilde seçiliyor (kolsuzda kol oyuğundan çıkıp bol eteğin dışından iner,
  kolluda kolluğun içinde kalır). Üretilen korsajlar genelde gövdeden geniş olduğundan
  doğal duruşta kolun kökü korsajın yanını kesiyor, kol oyuktan değil kumaşın içinden
  çıkıyor gibi görünüyordu; koltuk altının altındaki o kumaş artık gerçek bedende olduğu
  gibi kol ile gövde arasına alınıyor. Kolluklu giysilerde (palto, ceket) dar kolluk
  hâlâ kola değebiliyor. 70 üretilmiş kıyafette
  denendi (tişört, gömlek, kapüşonlu, ceket, palto, beş elbise, etek, pantolon, şort);
  kıyafet olmayan modeller (tam insan figürü, yatık yığın, vazo) artık net bir mesajla
  reddediliyor.
- **Manken göğsü düşük ölçülüyor** (oturtma raporunda gövde göğsü 70,9 cm; gerçek 88 cm).
- **Bel bandı 3D'de dikilmiyor.** Kalıpta var ama 3D dikiş verisinde eşi yok, atlanıyor
  (iş raporu bunu yazıyor).
- **Etek ucu simülasyonda hâlâ biraz içe kıvrılıyor.** Düzeltmeden sonra çok daha iyi ama
  kusursuz değil.
- **Midi kloş etek 182 cm kumaş istiyor.** Gerçekte yan dikişli iki parça kesilir;
  uygulama parçaları henüz bölemiyor.
- **3D'de dikilen etek ile yapay zekâyla üretilen elbise ayrı projeler.** Atölye yalnızca
  eteği dikiyor; korsaj kalıbının (Bella) henüz 3D dikişi yok.

### Tekrar üretmek

```bash
bash infra/scripts/start-linux.sh            # gateway, frontend, motor worker'ları
# Konsept:  Tasarımcı → Motif (FLUX.1-dev), kıyafeti "hollow, nothing holding it" diye tarif et
# 3D:       Yeni tasarım → Hunyuan3D-2.1 (PBR dokulu) → görseli yükle → mankene giydir
# Atölye:   Atölye → Kloş etek → Gelişmiş: Boy=Midi, Oturduğu yer=Belde → Kalıbı oluştur
#           → Kumaşa yerleştir (190 cm) → 3D'de dik (İpek, Gelişmiş: kare 160)
```
