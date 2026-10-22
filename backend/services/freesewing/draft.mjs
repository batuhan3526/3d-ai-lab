#!/usr/bin/env node
/*
 * 3D Studio — FreeSewing kalıp CLI'ı.
 *
 * Kullanım:  echo '{"design":"teagan","measurements":{...mm},"options":{},"sa_mm":10}' | node draft.mjs
 *            node draft.mjs --list   → kurulu tasarımlar + gereken ölçüler (JSON)
 *
 * Girdi (stdin JSON):
 *   design        : FreeSewing tasarım adı (küçük harf, ör. "teagan")
 *   measurements  : FreeSewing ölçüleri (mm; shoulderSlope derece)
 *   options       : FreeSewing opsiyonları (pct opsiyonlar KESİR olarak: 0.12 = %12)
 *   sa_mm         : dikiş payı (mm)
 *   render_svg    : true ise FreeSewing'in kendi SVG çıktısı da döner (varsayılan true)
 *
 * Çıktı (stdout JSON):
 *   {ok:true, design, version, svg, logs:{error,warn},
 *    parts:[{name, cut:{materials, grain, cutOnFold}, seam:[[x,y]...], sa:[[x,y]...]|null,
 *            sa_all:[[[x,y]...]...] (tüm 'sa' sınıflı yolların polylineları), anchors:{pointName: seamIndex}}]}
 *   Koordinatlar FreeSewing yerel parça çerçevesindedir (mm, y AŞAĞI). Eğriler
 *   (kübik bezier) ~SAMPLE_MM aralıkla örneklenir. Seam poligonu üzerinde yatan
 *   adlandırılmış noktalar (cfHem, armhole, shoulder ...) poligona tam köşe olarak
 *   yerleştirilir ve `anchors`'ta indeksleri verilir → gateway dikiş kenarlarını
 *   bu indekslerden kurar. Katlama (cutOnFold) uçları `__fold0/__fold1` adıyla,
 *   kol başı ön/arka bölme noktası `__capSplit` adıyla eklenir.
 * Hata: {ok:false, error:"..."} + çıkış kodu 2.
 */
import { readFileSync } from 'node:fs'

const SAMPLE_MM = 3 // eğri örnekleme adımı (mm)
const ON_PATH_TOL = 0.15 // nokta poligon üzerinde sayılır (mm)
const SNAP_TOL = 0.02 // mevcut köşeye eşit sayılır (mm)

const DESIGNS = [
  'aaron',
  'bella',
  'hugo',
  'lily',
  'penelope',
  'sandy',
  'simon',
  'sven',
  'teagan',
  'titan',
  'waralee',
]

function fail(msg, code = 2) {
  process.stdout.write(JSON.stringify({ ok: false, error: String(msg) }))
  process.exit(code)
}

async function loadDesign(name) {
  if (!DESIGNS.includes(name)) throw new Error(`Bilinmeyen tasarım: ${name}`)
  const mod = await import(`@freesewing/${name}`)
  const cls = mod[name[0].toUpperCase() + name.slice(1)]
  if (!cls) throw new Error(`Tasarım sınıfı bulunamadı: ${name}`)
  return cls
}

// --- geometri ----------------------------------------------------------------
const P = (pt) => [pt.x, pt.y]
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1])

function bez(p0, c1, c2, p1, t) {
  const u = 1 - t
  return [
    u * u * u * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t * t * t * p1[0],
    u * u * u * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t * t * t * p1[1],
  ]
}

/** Path ops → örneklenmiş nokta listesi (kapalıysa ilk nokta sonda tekrarlanmaz). */
function samplePath(path) {
  let pts = []
  let drawn = false
  for (const op of path.ops) {
    if (op.type === 'move') {
      // Çizim başlamadan ardışık move'lar → yalnızca son başlangıç geçerli.
      if (!drawn) pts = [P(op.to)]
      else pts.push(P(op.to))
    } else if (op.type === 'line') {
      pts.push(P(op.to))
      drawn = true
    } else if (op.type === 'curve') {
      const p0 = pts[pts.length - 1]
      const c1 = P(op.cp1)
      const c2 = P(op.cp2)
      const p1 = P(op.to)
      const approx = dist(p0, c1) + dist(c1, c2) + dist(c2, p1)
      const n = Math.max(4, Math.ceil(approx / SAMPLE_MM))
      for (let i = 1; i <= n; i++) pts.push(bez(p0, c1, c2, p1, i / n))
      drawn = true
    }
    // 'close' → poligon zaten kapalı kabul edilir
  }
  // Ardışık tekrarları ve kapanış tekrarını temizle.
  const out = []
  for (const p of pts) {
    if (!out.length || dist(out[out.length - 1], p) > 1e-6) out.push(p)
  }
  if (out.length > 2 && dist(out[0], out[out.length - 1]) < 1e-6) out.pop()
  return out
}

/** Path ops → move'larda bölünmüş polyline listesi (dikiş payı parçaları için). */
function samplePolylines(path) {
  const lines = []
  let cur = []
  for (const op of path.ops) {
    if (op.type === 'move') {
      if (cur.length > 1) lines.push(cur)
      cur = [P(op.to)]
    } else if (op.type === 'line') {
      cur.push(P(op.to))
    } else if (op.type === 'curve') {
      const p0 = cur[cur.length - 1]
      const c1 = P(op.cp1)
      const c2 = P(op.cp2)
      const p1 = P(op.to)
      const approx = dist(p0, c1) + dist(c1, c2) + dist(c2, p1)
      const n = Math.max(4, Math.ceil(approx / SAMPLE_MM))
      for (let i = 1; i <= n; i++) cur.push(bez(p0, c1, c2, p1, i / n))
    } else if (op.type === 'close' && cur.length > 1) {
      cur.push(cur[0])
    }
  }
  if (cur.length > 1) lines.push(cur)
  return lines
}

/** p noktasının poligon kenarlarına izdüşümü: {seg, t, d}. */
function projectOnPolygon(poly, p) {
  let best = { seg: -1, t: 0, d: Infinity }
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i]
    const b = poly[(i + 1) % poly.length]
    const dx = b[0] - a[0]
    const dy = b[1] - a[1]
    const l2 = dx * dx + dy * dy
    let t = l2 > 0 ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2 : 0
    t = Math.max(0, Math.min(1, t))
    const q = [a[0] + t * dx, a[1] + t * dy]
    const d = dist(q, p)
    if (d < best.d) best = { seg: i, t, d }
  }
  return best
}

/** Adlandırılmış noktaları poligona köşe olarak yerleştir; {ad: indeks} döner. */
function insertAnchors(poly, named) {
  // Önce hepsinin konumunu bul, sonra sırayla ekle (indeks kaymasını önlemek için
  // her eklemede yeniden izdüşüm yapılır — nokta sayısı küçük, maliyet önemsiz).
  const names = []
  for (const [name, p] of Object.entries(named)) {
    const pr = projectOnPolygon(poly, p)
    if (pr.d <= ON_PATH_TOL) names.push(name)
  }
  for (const name of names) {
    const p = named[name]
    // Var olan köşeye çok yakınsa ona otur.
    let snapped = false
    for (let i = 0; i < poly.length; i++) {
      if (dist(poly[i], p) <= SNAP_TOL) {
        snapped = true
        break
      }
    }
    if (snapped) continue
    const pr = projectOnPolygon(poly, p)
    poly.splice(pr.seg + 1, 0, [p[0], p[1]])
  }
  const anchors = {}
  for (const name of names) {
    const p = named[name]
    let bi = -1
    let bd = Infinity
    for (let i = 0; i < poly.length; i++) {
      const d = dist(poly[i], p)
      if (d < bd) {
        bd = d
        bi = i
      }
    }
    if (bi >= 0 && bd <= ON_PATH_TOL) anchors[name] = bi
  }
  return anchors
}

function round(poly) {
  return poly.map(([x, y]) => [Math.round(x * 1000) / 1000, Math.round(y * 1000) / 1000])
}

/**
 * Parçanın dış dikiş hattı: görünür `seam` yolu; gizliyse (ör. waralee cebi,
 * pantolon hattını miras alıp kendi hattını `frontPocketSeam` olarak çizer)
 * 'fabric' sınıflı (sa olmayan) görünür yolların en uzunu.
 */
function pickSeamPath(part) {
  const s = part.paths.seam
  if (s && s.ops?.length && !s.hidden) return s
  let best = null
  let bestLen = 0
  for (const path of Object.values(part.paths)) {
    if (path.hidden || !path.ops?.length) continue
    const cls = String(path.attributes?.get?.('class') || '').split(/\s+/)
    if (!cls.includes('fabric') || cls.includes('sa')) continue
    let len = 0
    try {
      len = path.length()
    } catch {
      len = 0
    }
    if (len > bestLen) {
      best = path
      bestLen = len
    }
  }
  return best || (s && s.ops?.length ? s : null)
}

// --- ana akış ----------------------------------------------------------------
async function listDesigns() {
  const out = []
  for (const name of DESIGNS) {
    const cls = await loadDesign(name)
    const cfg = new cls().getConfig()
    const opts = {}
    for (const [k, v] of Object.entries(cfg.options || {})) {
      if (v && typeof v === 'object') opts[k] = v
    }
    out.push({
      design: name,
      measurements: cfg.measurements || [],
      optionalMeasurements: cfg.optionalMeasurements || [],
      options: opts,
    })
  }
  return out
}

async function draft(req) {
  const name = String(req.design || '').toLowerCase()
  const cls = await loadDesign(name)
  const sa = Number.isFinite(req.sa_mm) ? Number(req.sa_mm) : 10
  const pattern = new cls({
    measurements: req.measurements || {},
    options: req.options || {},
    sa,
    units: 'metric',
    complete: true,
    paperless: false,
    locale: 'en',
  })
  pattern.draft()
  const logs = pattern.getLogs()
  const errors = [...(logs.pattern?.error || [])]
  for (const s of logs.sets || []) errors.push(...(s?.error || []))
  const warns = [...(logs.pattern?.warn || [])]
  for (const s of logs.sets || []) warns.push(...(s?.warn || []))

  const store = pattern.setStores[0]
  const cutlist = store.get('cutlist', {}) || {}
  const set = pattern.parts[0] || {}
  const parts = []
  for (const [pname, part] of Object.entries(set)) {
    if (part.hidden) continue
    const seamPath = pickSeamPath(part)
    if (!seamPath) continue
    const seam = samplePath(seamPath)
    if (seam.length < 3) continue
    const named = {}
    for (const [k, pt] of Object.entries(part.points)) {
      if (k.startsWith('_') || /Cp\d?$/.test(k) || /Cp\d/.test(k)) continue
      if (!pt || !Number.isFinite(pt.x) || !Number.isFinite(pt.y)) continue
      named[k] = P(pt)
    }
    const cut = cutlist[pname] || {}
    if (Array.isArray(cut.cutOnFold) && cut.cutOnFold.length === 2) {
      named.__fold0 = P(cut.cutOnFold[0])
      named.__fold1 = P(cut.cutOnFold[1])
    }
    // Kol başı (library.sleeve türevi): ön/arka kol oyuntusu uzunluk oranına göre böl.
    const capPath = part.paths.sleevecap
    if (capPath && capPath.ops?.length) {
      try {
        const fl = store.get('library.sleeve.frontArmholeLength', null)
        const bl = store.get('library.sleeve.backArmholeLength', null)
        const total = capPath.length()
        const frac = fl && bl ? fl / (fl + bl) : 0.5
        named.__capSplit = P(capPath.shiftAlong(total * frac))
        named.__capStart = P(capPath.start())
        named.__capEnd = P(capPath.end())
      } catch (e) {
        warns.push(`capSplit hesaplanamadı (${pname}): ${e}`)
      }
    }
    const anchors = insertAnchors(seam, named)
    let sap = null
    if (part.paths.sa && part.paths.sa.ops?.length) {
      const s = samplePath(part.paths.sa)
      if (s.length >= 3) sap = s
    }
    // Tüm görünür dikiş payı yolları (sa, hemSa, saConnect ...) — gateway kesim
    // çizgisini bunlardan kurar (FreeSewing bazı parçalarda payı birden çok yola böler).
    const saAll = []
    for (const path of Object.values(part.paths)) {
      if (path.hidden || !path.ops?.length) continue
      const cls = String(path.attributes?.get?.('class') || '')
      if (!/(^|\s)sa(\s|$)/.test(cls)) continue
      for (const pl of samplePolylines(path)) saAll.push(round(pl))
    }
    parts.push({
      name: pname,
      cut: {
        materials: cut.materials || {},
        grain: Number.isFinite(cut.grain) ? cut.grain : null,
        cutOnFold: Array.isArray(cut.cutOnFold) ? cut.cutOnFold.map(P) : null,
      },
      seam: round(seam),
      sa: sap ? round(sap) : null,
      sa_all: saAll,
      anchors,
    })
  }
  if (!parts.length) {
    const why = errors.length ? errors.join(' | ') : 'hiç parça çizilmedi'
    throw new Error(`Kalıp çizilemedi: ${why}`)
  }
  let svg = null
  if (req.render_svg !== false) {
    try {
      svg = pattern.render()
    } catch (e) {
      warns.push(`SVG render hatası: ${e}`)
    }
  }
  return {
    ok: true,
    design: name,
    version: '4.10.2',
    svg,
    parts,
    logs: { error: errors.map(String), warn: warns.map(String) },
  }
}

async function main() {
  if (process.argv.includes('--list')) {
    process.stdout.write(JSON.stringify({ ok: true, designs: await listDesigns() }))
    return
  }
  let req
  try {
    req = JSON.parse(readFileSync(0, 'utf-8') || '{}')
  } catch (e) {
    fail(`Geçersiz JSON girdi: ${e.message}`)
  }
  try {
    process.stdout.write(JSON.stringify(await draft(req)))
  } catch (e) {
    fail(e?.message || e)
  }
}

main()
