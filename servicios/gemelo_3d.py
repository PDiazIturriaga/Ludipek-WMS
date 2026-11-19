"""Gemelo digital 3D de la bodega.

Genera una página HTML autónoma (sin librerías externas ni internet) que dibuja
los racks, niveles y pallets en 3D con un motor propio en Canvas:
rotar (arrastrar), mover (clic derecho o Shift + arrastrar), zoom (rueda),
buscar SKU / LPN / ubicación, colorear por zona, vencimiento o calidad y ver
el detalle de cada posición.
"""
import json
from datetime import datetime


def generar_html_gemelo(bodega: str, ubicaciones: list, stock: list, anden: list) -> str:
    """ubicaciones: códigos de bodega_ubicaciones. stock: ítems en racks/zonas. anden: LPN sin ubicar."""
    datos = {
        "bodega": bodega,
        "generado": datetime.now().strftime("%d-%m-%Y %H:%M"),
        "ubicaciones": sorted({str(u or "").strip().upper() for u in ubicaciones if u}),
        "stock": [
            {
                "u": str(x.get("ubicacion") or "").upper(),
                "lpn": str(x.get("lpn") or ""),
                "sku": str(x.get("sku") or ""),
                "d": str(x.get("descripcion") or "")[:70],
                "un": int(x.get("unidades") or 0),
                "cj": int(x.get("cajas") or 0),
                "lote": str(x.get("lote") or "S/L"),
                "v": str(x.get("vencimiento") or "S/F"),
                "qa": str(x.get("qa") or "APROBADO"),
            }
            for x in stock
        ],
        "anden": [
            {"lpn": str(x.get("lpn") or ""), "sku": str(x.get("sku") or ""), "un": int(x.get("unidades") or 0),
             "d": str(x.get("descripcion") or "")[:70]}
            for x in anden
        ],
    }
    return PLANTILLA.replace("__DATOS__", json.dumps(datos, ensure_ascii=False).replace("</", "<\\/"))


PLANTILLA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gemelo digital 3D · LUDIPEK WMS</title>
<style>
  :root { --bg:#12171a; --panel:rgba(24,31,34,.92); --borde:#2f3b3f; --texto:#f1f5f9; --t2:#94a3b8; --t3:#64748b; --acento:#38bdf8; }
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; background:var(--bg); color:var(--texto); font:13px/1.4 "Segoe UI",Roboto,Arial,sans-serif; overflow:hidden; }
  canvas { position:fixed; inset:0; width:100%; height:100%; display:block; cursor:grab; }
  canvas.arrastrando { cursor:grabbing; }
  .panel { position:fixed; background:var(--panel); border:1px solid var(--borde); border-radius:12px; backdrop-filter:blur(6px); box-shadow:0 8px 30px rgba(0,0,0,.35); }
  #barra { top:14px; left:14px; right:14px; height:54px; display:flex; align-items:center; justify-content:space-between; padding:0 16px; }
  #barra h1 { font-size:16px; margin:0; font-weight:700; letter-spacing:.2px; }
  #barra .sub { color:var(--t2); font-size:12px; }
  .grupo { display:flex; gap:6px; align-items:center; flex-wrap:wrap; }
  button, .chip { background:transparent; color:var(--texto); border:1px solid var(--borde); border-radius:8px; padding:6px 11px; font:inherit; font-size:12px; cursor:pointer; }
  button:hover, .chip:hover { border-color:var(--acento); }
  .chip.on, button.on { background:rgba(56,189,248,.16); border-color:var(--acento); color:#e0f2fe; }
  #lateral { top:80px; left:14px; width:290px; max-height:calc(100% - 94px); overflow:auto; padding:14px; }
  #lateral h2 { font-size:11px; text-transform:uppercase; letter-spacing:.8px; color:var(--t3); margin:16px 0 8px; font-weight:600; }
  #lateral h2:first-child { margin-top:0; }
  .kpis { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
  .kpi { border:1px solid var(--borde); border-radius:10px; padding:8px 10px; }
  .kpi b { display:block; font-size:19px; font-weight:700; }
  .kpi span { color:var(--t2); font-size:11px; }
  input { width:100%; background:#1b2326; color:var(--texto); border:1px solid var(--borde); border-radius:8px; padding:8px 10px; font:inherit; }
  input:focus { outline:none; border-color:var(--acento); }
  .rack { display:flex; align-items:center; gap:8px; padding:5px 6px; border-radius:8px; cursor:pointer; }
  .rack:hover, .rack.on { background:rgba(56,189,248,.10); }
  .rack .l { width:24px; font-weight:700; }
  .rack .barra { flex:1; height:6px; border-radius:3px; background:#2a3538; overflow:hidden; }
  .rack .barra i { display:block; height:100%; background:var(--acento); }
  .rack .p { width:74px; text-align:right; color:var(--t2); font-size:11.5px; }
  #resultados { margin-top:6px; color:var(--t2); font-size:12px; }
  #resultados div { padding:4px 6px; border-radius:6px; cursor:pointer; color:var(--texto); }
  #resultados div:hover { background:rgba(56,189,248,.12); }
  #leyenda { left:318px; bottom:14px; padding:8px 12px; display:flex; gap:14px; flex-wrap:wrap; font-size:12px; color:var(--t2); }
  #leyenda i { display:inline-block; width:11px; height:11px; border-radius:3px; margin-right:5px; vertical-align:-1px; }
  #detalle { top:80px; right:14px; width:310px; padding:14px; display:none; max-height:calc(100% - 94px); overflow:auto; }
  #detalle h3 { margin:0 0 2px; font-size:17px; }
  #detalle .item { border-top:1px solid var(--borde); padding:9px 0; }
  #detalle .item:first-of-type { border-top:none; }
  #detalle .fila { display:flex; justify-content:space-between; gap:10px; font-size:12px; }
  #detalle .fila span:first-child { color:var(--t2); }
  #tip { position:fixed; pointer-events:none; background:rgba(15,20,22,.95); border:1px solid var(--borde); border-radius:8px; padding:7px 10px; font-size:12px; display:none; max-width:280px; z-index:5; }
  #ayuda { right:14px; bottom:14px; padding:8px 12px; color:var(--t2); font-size:11.5px; }
  .x { float:right; cursor:pointer; color:var(--t2); }
  @media (max-width: 820px) {
    #lateral { width:auto; right:14px; max-height:36%; }
    #leyenda { left:14px; bottom:54px; }
    #detalle { top:auto; bottom:14px; left:14px; right:14px; width:auto; max-height:45%; }
    #barra .sub { display:none; }
    #ayuda { display:none; }
  }
</style>
</head>
<body>
<canvas id="c"></canvas>
<div id="barra" class="panel">
  <div><h1>Gemelo digital · <span id="bod"></span></h1><div class="sub" id="gen"></div></div>
  <div class="grupo">
    <button data-vista="iso" class="on">3D</button>
    <button data-vista="planta">Planta</button>
    <button data-vista="frente">Frente</button>
    <button id="reset" title="Centrar">⟲</button>
  </div>
</div>
<div id="lateral" class="panel">
  <h2>Resumen</h2>
  <div class="kpis">
    <div class="kpi"><b id="k_ocup">–</b><span>Ocupación</span></div>
    <div class="kpi"><b id="k_pos">–</b><span>Posiciones</span></div>
    <div class="kpi"><b id="k_lpn">–</b><span>LPN en racks</span></div>
    <div class="kpi"><b id="k_and">–</b><span>LPN en andén</span></div>
  </div>
  <h2>Colorear por</h2>
  <div class="grupo" id="modos">
    <span class="chip on" data-modo="zona">Zona</span>
    <span class="chip" data-modo="venc">Vencimiento</span>
    <span class="chip" data-modo="qa">Calidad</span>
  </div>
  <h2>Buscar</h2>
  <input id="buscar" placeholder="SKU, LPN, lote o ubicación">
  <div id="resultados"></div>
  <h2>Racks y zonas</h2>
  <div id="racks"></div>
</div>
<div id="leyenda" class="panel"></div>
<div id="detalle" class="panel"></div>
<div id="ayuda" class="panel">Arrastre: girar · Clic derecho / Shift: mover · Rueda: zoom · Clic: detalle</div>
<div id="tip"></div>
<script>
const D = __DATOS__;
// ---------------------------------------------------------------- geometría
const W = 1.3, PROF = 1.1, H = 1.7, PASILLO = 3.3, PASO_Z = PROF + PASILLO;
const $ = s => document.querySelector(s);
document.getElementById('bod').textContent = D.bodega;
document.getElementById('gen').textContent = 'Actualizado ' + D.generado + ' · datos del WMS';

function parsear(cod) {
  if (/^(MK|ME|BE)-/.test(cod)) return null;   // arena: se dibuja como piso, no como rack
  const m = /^([A-Z]+)-?(\d{1,3})-(\d{1,2})/.exec(cod);
  if (!m) return null;
  return { rack: m[1], col: parseInt(m[2], 10), niv: parseInt(m[3], 10) };
}
function diasVence(v) {
  const m = /^(\d{2})[-\/](\d{2})[-\/](\d{4})/.exec(v || '');
  if (!m) return null;
  const f = new Date(+m[3], +m[2] - 1, +m[1]);
  return Math.round((f - new Date()) / 86400000);
}

// Posiciones: maestra de ubicaciones + cualquier ubicación con stock
const posiciones = new Map();      // "A-01-02" -> {rack,col,niv,items:[]}
const zonas = { 'ZONA-PICKING': [], 'ZONA-MERMA': [] };
function pos(cod) {
  if (!posiciones.has(cod)) { const p = parsear(cod); if (!p) return null; posiciones.set(cod, { cod, ...p, items: [] }); }
  return posiciones.get(cod);
}
// Zonas de arena: posiciones de piso con hasta 2 pallets apilados (MK/BE arena, ME mermas)
const CEL = 1.3;
const arenas = new Map();   // "MK-03-05" -> {cod, arena, fila, posn, items, x, z}
function posArena(cod) {
  const m = /^(MK|ME|BE)-(\d{2})-(\d{2})$/.exec(cod);
  if (!m) return null;
  if (!arenas.has(cod)) arenas.set(cod, { cod, arena: m[1], fila: +m[2], posn: +m[3], items: [], esArena: true });
  return arenas.get(cod);
}
D.ubicaciones.forEach(u => { if (!posArena(u)) pos(u); });
D.stock.forEach(it => {
  if (it.u.startsWith('ZONA-PICKING')) return zonas['ZONA-PICKING'].push(it);
  if (it.u.startsWith('ZONA-MERMA')) return zonas['ZONA-MERMA'].push(it);
  const a = posArena(it.u); if (a) return a.items.push(it);
  const p = pos(it.u); if (p) p.items.push(it);
});
const letras = [...new Set([...posiciones.values()].map(p => p.rack))].sort();
const infoRack = {};
letras.forEach((l, i) => {
  const ps = [...posiciones.values()].filter(p => p.rack === l);
  infoRack[l] = { idx: i, cols: Math.max(...ps.map(p => p.col)), nivs: Math.max(...ps.map(p => p.niv)),
                  total: ps.length, ocup: ps.filter(p => p.items.length).length };
});
const largoMax = Math.max(8, ...letras.map(l => infoRack[l].cols)) * W;
const anchoTotal = Math.max(1, letras.length) * PASO_Z;

// Ubicación de los bloques de arena en el site: Marketing detrás de los pasillos H a E
// (al fondo de los racks), sus mermas al lado, y Bodega E en otra sección.
const idxE = infoRack['E'] ? infoRack['E'].idx : Math.max(0, letras.length - 4);
const BLOQUES = {
  MK: { nom: 'Arena Marketing', x0: largoMax + 6, z0: idxE * PASO_Z },
  ME: { nom: 'Mermas arena', x0: largoMax + 6, z0: idxE * PASO_Z + 11 * CEL + 3 },
  BE: { nom: 'Arena Bodega E', x0: 0, z0: anchoTotal + 9 },
};
Object.values(BLOQUES).forEach(b => { b.pos = 0; b.ocup = 0; b.pallets = 0; b.x1 = b.x0; b.z1 = b.z0; });
arenas.forEach(a => {
  const b = BLOQUES[a.arena];
  a.x = b.x0 + (a.posn - 1) * CEL; a.z = b.z0 + (a.fila - 1) * CEL;
  b.pos++; if (a.items.length) b.ocup++;
  b.pallets += Math.min(2, new Set(a.items.map(i => i.lpn || i.sku)).size);
  b.x1 = Math.max(b.x1, a.x + CEL); b.z1 = Math.max(b.z1, a.z + CEL);
});
const hayArena = arenas.size > 0;
const MUNDO = { x0: -15, x1: largoMax + 4, z0: -4, z1: anchoTotal + 2 };
Object.values(BLOQUES).forEach(b => { if (b.pos) { MUNDO.x1 = Math.max(MUNDO.x1, b.x1 + 3); MUNDO.z1 = Math.max(MUNDO.z1, b.z1 + 3); } });

// ---------------------------------------------------------------- escena (cajas)
// caja: {x0,y0,z0,x1,y1,z1,color,tipo,rack,pos}
let cajas = [];
const AZUL = '#1d4ed8', NARANJA = '#ea580c', MADERA = '#a16207';
function construir() {
  cajas = [];
  etiquetasZona = [];
  letras.forEach(l => {
    const r = infoRack[l], z0 = r.idx * PASO_Z, alto = r.nivs * H + 0.25;
    if (filtroRack && filtroRack !== l) return;
    for (let c = 0; c <= r.cols; c++) {            // parantes
      const x = c * W;
      cajas.push({ x0: x - .04, x1: x + .04, y0: 0, y1: alto, z0: z0, z1: z0 + .08, color: AZUL, tipo: 'f', rack: l });
      cajas.push({ x0: x - .04, x1: x + .04, y0: 0, y1: alto, z0: z0 + PROF - .08, z1: z0 + PROF, color: AZUL, tipo: 'f', rack: l });
    }
    for (let n = 2; n <= r.nivs + 1; n++) {        // vigas
      const y = (n - 1) * H;
      cajas.push({ x0: 0, x1: r.cols * W, y0: y - .12, y1: y, z0: z0, z1: z0 + .07, color: NARANJA, tipo: 'f', rack: l });
      cajas.push({ x0: 0, x1: r.cols * W, y0: y - .12, y1: y, z0: z0 + PROF - .07, z1: z0 + PROF, color: NARANJA, tipo: 'f', rack: l });
    }
  });
  posiciones.forEach(p => {
    if (!p.items.length || (filtroRack && filtroRack !== p.rack)) return;
    const r = infoRack[p.rack], z0 = r.idx * PASO_Z, x0 = (p.col - 1) * W, y0 = (p.niv - 1) * H;
    cajas.push({ x0: x0 + .12, x1: x0 + W - .12, y0: y0, y1: y0 + .14, z0: z0 + .08, z1: z0 + PROF - .08, color: MADERA, tipo: 'b', pos: p });
    cajas.push({ x0: x0 + .16, x1: x0 + W - .16, y0: y0 + .14, y1: y0 + 1.25, z0: z0 + .1, z1: z0 + PROF - .1, color: colorPos(p), tipo: 'p', pos: p });
  });
  // Arena: baldosa de piso por posición y hasta 2 pallets apilados
  if (!filtroRack) {
    arenas.forEach(a => {
      const x = a.x, z = a.z;
      cajas.push({ x0: x + .05, x1: x + CEL - .05, y0: 0, y1: .03, z0: z + .05, z1: z + CEL - .05,
                   color: a.arena === 'ME' ? '#4a2a2a' : '#3b3428', tipo: 'f' });
      [...new Set(a.items.map(i => i.lpn || i.sku))].slice(0, 2).forEach((l, k) => {
        const y0 = k * 1.16;
        cajas.push({ x0: x + .1, x1: x + CEL - .1, y0, y1: y0 + .12, z0: z + .1, z1: z + CEL - .1, color: MADERA, tipo: 'b', pos: a });
        cajas.push({ x0: x + .14, x1: x + CEL - .14, y0: y0 + .12, y1: y0 + 1.12, z0: z + .14, z1: z + CEL - .14,
                     color: colorPos(a), tipo: 'p', pos: a });
      });
    });
    Object.values(BLOQUES).forEach(b => {
      if (b.pos) etiquetasZona.push({ txt: `${b.nom} · ${b.pallets} pallets · ${b.ocup}/${b.pos} posiciones`,
                                      x: (b.x0 + b.x1) / 2, y: 3.2, z: b.z0 - 0.8 });
    });
  }
  // Andén y zonas de piso (frente a los racks)
  const zonasPiso = [['ANDÉN', D.anden, '#f59e0b'], ['ZONA PICKING', zonas['ZONA-PICKING'], '#10b981'], ['ZONA MERMA', zonas['ZONA-MERMA'], '#ef4444']];
  let zOff = 0;
  zonasPiso.forEach(([nom, lista, col]) => {
    if (!lista.length || filtroRack) return;
    const n = Math.min(lista.length, 96), porFila = 8;
    for (let i = 0; i < n; i++) {
      const fx = -4.5 - (i % porFila) * 1.25, fz = zOff + Math.floor(i / porFila) * 1.25;
      cajas.push({ x0: fx - 1.05, x1: fx, y0: 0, y1: 1.0, z0: fz, z1: fz + 1.05, color: col, tipo: 'z',
                   zona: { nom, lista, color: col } });
    }
    etiquetasZona.push({ txt: `${nom} · ${lista.length} LPN`, x: -4.5 - porFila * 0.62, y: 1.6, z: zOff - 0.6 });
    zOff += Math.ceil(n / porFila) * 1.25 + 2.2;
  });
}
let etiquetasZona = [];

// ---------------------------------------------------------------- colores
let modo = 'zona', busqueda = '', filtroRack = null, seleccion = null;
function coincide(it) {
  if (!busqueda) return true;
  return (it.sku + ' ' + it.lpn + ' ' + it.lote + ' ' + it.u + ' ' + it.d).toUpperCase().includes(busqueda);
}
function colorPos(p) {
  if (busqueda && !p.items.some(coincide) && !p.cod.includes(busqueda)) return '#2b3437';
  if (busqueda) return '#38bdf8';
  const it = p.items[0];
  if (modo === 'zona') return p.esArena ? (p.arena === 'ME' ? '#ef4444' : '#d4a373') : (p.niv <= 1 ? '#10b981' : '#3b82f6');
  if (modo === 'qa') {
    const q = p.items.map(i => i.qa);
    return q.includes('RECHAZADO') ? '#ef4444' : q.includes('CUARENTENA') ? '#f59e0b' : '#22c55e';
  }
  const ds = p.items.map(i => diasVence(i.v)).filter(d => d !== null);
  if (!ds.length) return '#94a3b8';
  const d = Math.min(...ds);
  return d < 0 ? '#ef4444' : d <= 90 ? '#f59e0b' : d <= 180 ? '#facc15' : '#22c55e';
}
const LEYENDAS = {
  zona: [['#10b981', 'Picking (nivel 1)'], ['#3b82f6', 'Reserva (nivel 2+)'], ['#d4a373', 'Arena (piso)'], ['#ef4444', 'Mermas'], ['#f59e0b', 'Andén']],
  venc: [['#ef4444', 'Vencido'], ['#f59e0b', '≤ 90 días'], ['#facc15', '≤ 180 días'], ['#22c55e', '> 180 días'], ['#94a3b8', 'Sin fecha']],
  qa: [['#22c55e', 'Aprobado'], ['#f59e0b', 'Cuarentena'], ['#ef4444', 'Rechazado']],
};
function pintarLeyenda() {
  const l = busqueda ? [['#38bdf8', 'Coincide con la búsqueda'], ['#2b3437', 'Resto']] : LEYENDAS[modo];
  $('#leyenda').innerHTML = l.map(([c, t]) => `<span><i style="background:${c}"></i>${t}</span>`).join('');
}
function sombrear(hex, f) {
  const n = parseInt(hex.slice(1), 16);
  const r = Math.min(255, ((n >> 16) & 255) * f), g = Math.min(255, ((n >> 8) & 255) * f), b = Math.min(255, (n & 255) * f);
  return `rgb(${r | 0},${g | 0},${b | 0})`;
}

// ---------------------------------------------------------------- cámara
const cv = $('#c'), ctx = cv.getContext('2d');
let dpr = 1, ancho = 0, alto = 0;
const cam = { yaw: -0.72, pitch: 0.62, zoom: 18, px: 0, py: 0, cx: 0, cy: 0, cz: 0 };
// Encuadra una caja del mundo [x0,x1]x[y0,y1]x[z0,z1] en el área libre (a la derecha del panel)
function encuadrar(x0, x1, y0, y1, z0, z1) {
  cam.cx = (x0 + x1) / 2; cam.cy = (y0 + y1) / 2; cam.cz = (z0 + z1) / 2;
  prep(); const zg = cam.zoom, pxg = cam.px, pyg = cam.py;
  cam.zoom = 1; cam.px = 0; cam.py = 0;
  const pts = [];
  for (const x of [x0, x1]) for (const y of [y0, y1]) for (const z of [z0, z1]) pts.push(proyectar(x, y, z));
  const w = Math.max(...pts.map(p => p[0])) - Math.min(...pts.map(p => p[0]));
  const h = Math.max(...pts.map(p => p[1])) - Math.min(...pts.map(p => p[1]));
  const izq = innerWidth > 820 ? 320 : 0, arriba = 80, abajo = 60;
  const libreW = ancho - izq - 40, libreH = alto - arriba - abajo;
  cam.zoom = Math.max(2, Math.min(90, Math.min(libreW / Math.max(w, 1), libreH / Math.max(h, 1)) * 0.94));
  const mx = (Math.max(...pts.map(p => p[0])) + Math.min(...pts.map(p => p[0]))) / 2 - ancho / 2;
  const my = (Math.max(...pts.map(p => p[1])) + Math.min(...pts.map(p => p[1]))) / 2 - alto / 2;
  cam.px = izq / 2 - mx * cam.zoom; cam.py = (arriba - abajo) / 2 - my * cam.zoom;
}
function centrar() {
  if (filtroRack) {
    const r = infoRack[filtroRack];
    return encuadrar(-1.5, r.cols * W + 0.5, 0, r.nivs * H + 1, r.idx * PASO_Z - 0.5, r.idx * PASO_Z + PROF + 1);
  }
  const hayZonas = !!(D.anden.length || zonas['ZONA-PICKING'].length || zonas['ZONA-MERMA'].length);
  const nivMax = Math.max(1, ...letras.map(l => infoRack[l].nivs));
  encuadrar(hayZonas ? -15 : -1.5, MUNDO.x1 - 3.5, 0, nivMax * H + 1, -0.5, MUNDO.z1 - 2);
}
function redimensionar() {
  dpr = window.devicePixelRatio || 1; ancho = innerWidth; alto = innerHeight;
  cv.width = ancho * dpr; cv.height = alto * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
let cyw, syw, cp, sp;
function prep() { cyw = Math.cos(cam.yaw); syw = Math.sin(cam.yaw); cp = Math.cos(cam.pitch); sp = Math.sin(cam.pitch); }
function proyectar(x, y, z) {
  x -= cam.cx; y -= cam.cy; z -= cam.cz;
  const xr = x * cyw - z * syw, zr = x * syw + z * cyw;
  return [ancho / 2 + cam.px + xr * cam.zoom, alto / 2 + cam.py + (zr * sp - y * cp) * cam.zoom, zr * cp - y * sp];
}
// Caras: [índices de esquinas, normal]
const CARAS = [
  [[4, 5, 6, 7], [0, 1, 0]], [[0, 3, 2, 1], [0, -1, 0]],
  [[0, 1, 5, 4], [0, 0, -1]], [[3, 7, 6, 2], [0, 0, 1]],
  [[0, 4, 7, 3], [-1, 0, 0]], [[1, 2, 6, 5], [1, 0, 0]],
];
const LUZ = (() => { const v = [-0.45, 1, -0.35]; const n = Math.hypot(...v); return v.map(a => a / n); })();

// ---------------------------------------------------------------- dibujo
let dibujados = []; // [{poligonos, caja}] en orden de dibujo (para el puntero)
let pendiente = false;
function pedirDibujo() { if (!pendiente) { pendiente = true; requestAnimationFrame(dibujar); } }
function piso() {
  const M = MUNDO;
  const ext = [[M.x0, 0, M.z0], [M.x1, 0, M.z0], [M.x1, 0, M.z1], [M.x0, 0, M.z1]].map(p => proyectar(...p));
  ctx.fillStyle = '#1a2124'; ctx.beginPath(); ext.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath(); ctx.fill();
  ctx.strokeStyle = 'rgba(148,163,184,.07)'; ctx.lineWidth = 1;
  for (let x = M.x0; x <= M.x1; x += 2.6) { const a = proyectar(x, 0, M.z0), b = proyectar(x, 0, M.z1); ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke(); }
  for (let z = M.z0; z <= M.z1; z += 2.2) { const a = proyectar(M.x0, 0, z), b = proyectar(M.x1, 0, z); ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke(); }
  // líneas amarillas de pasillo
  ctx.strokeStyle = 'rgba(250,204,21,.35)'; ctx.lineWidth = 2;
  letras.forEach(l => {
    if (filtroRack && filtroRack !== l) return;
    const r = infoRack[l], z = r.idx * PASO_Z + PROF + 0.25;
    const a = proyectar(0, 0, z), b = proyectar(r.cols * W, 0, z);
    ctx.beginPath(); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); ctx.stroke();
  });
}
let ocupadas = [];
function etiqueta(txt, x, y, z, grande) {
  let [sx, sy] = proyectar(x, y, z);
  ctx.font = (grande ? '700 14px' : '600 11px') + ' Segoe UI, Arial';
  const w = ctx.measureText(txt).width + (grande ? 18 : 10), h = grande ? 24 : 18;
  const choca = () => ocupadas.some(r => sx - w / 2 < r[2] && sx + w / 2 > r[0] && sy - h / 2 < r[3] && sy + h / 2 > r[1]);
  for (let i = 0; i < 6 && choca(); i++) { if (!grande) return; sy -= h + 4; }
  if (choca()) return;
  ocupadas.push([sx - w / 2, sy - h / 2, sx + w / 2, sy + h / 2]);
  ctx.fillStyle = grande ? 'rgba(14,116,144,.92)' : 'rgba(15,20,22,.8)';
  ctx.beginPath(); ctx.roundRect(sx - w / 2, sy - h / 2, w, h, 6); ctx.fill();
  ctx.fillStyle = '#f1f5f9'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(txt, sx, sy + 1);
}
function dibujar() {
  pendiente = false; prep();
  ctx.clearRect(0, 0, ancho, alto);
  const g = ctx.createRadialGradient(ancho / 2, alto / 2, 50, ancho / 2, alto / 2, Math.max(ancho, alto));
  g.addColorStop(0, '#1b2326'); g.addColorStop(1, '#0d1113'); ctx.fillStyle = g; ctx.fillRect(0, 0, ancho, alto);
  piso();
  const lista = cajas.map(c => {
    const esq = [
      [c.x0, c.y0, c.z0], [c.x1, c.y0, c.z0], [c.x1, c.y0, c.z1], [c.x0, c.y0, c.z1],
      [c.x0, c.y1, c.z0], [c.x1, c.y1, c.z0], [c.x1, c.y1, c.z1], [c.x0, c.y1, c.z1],
    ].map(p => proyectar(...p));
    const prof = esq.reduce((a, p) => a + p[2], 0) / 8;
    return { c, esq, prof };
  }).sort((a, b) => b.prof - a.prof);
  dibujados = [];
  for (const { c, esq } of lista) {
    const polis = [];
    const resaltada = seleccion && c.pos && c.pos === seleccion;
    for (const [idx, n] of CARAS) {
      const nxr = n[0] * cyw - n[2] * syw, nzr = n[0] * syw + n[2] * cyw;
      if (nzr * cp - n[1] * sp >= 0) continue;
      const luz = 0.5 + 0.5 * Math.max(0, n[0] * LUZ[0] + n[1] * LUZ[1] + n[2] * LUZ[2]);
      const pts = idx.map(i => esq[i]);
      ctx.beginPath(); pts.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.closePath();
      ctx.fillStyle = sombrear(resaltada ? '#ffffff' : c.color, luz); ctx.fill();
      if (c.tipo !== 'f') { ctx.strokeStyle = 'rgba(0,0,0,.25)'; ctx.lineWidth = .6; ctx.stroke(); }
      polis.push(pts);
    }
    if (c.tipo !== 'f') dibujados.push({ polis, c });
  }
  ocupadas = [];
  letras.forEach(l => {
    if (filtroRack && filtroRack !== l) return;
    const r = infoRack[l];
    etiqueta('Rack ' + l, -0.9, r.nivs * H + 0.9, r.idx * PASO_Z + PROF / 2, true);
    if (filtroRack || cam.zoom > 30) for (let c = 1; c <= r.cols; c += (cam.zoom > 40 ? 1 : 5)) etiqueta(String(c).padStart(2, '0'), (c - 0.5) * W, -0.05, r.idx * PASO_Z + PROF + 0.6, false);
  });
  etiquetasZona.forEach(e => etiqueta(e.txt, e.x, e.y, e.z, false));
}
function dentro(pt, poli) {
  let d = false;
  for (let i = 0, j = poli.length - 1; i < poli.length; j = i++) {
    const [xi, yi] = poli[i], [xj, yj] = poli[j];
    if (((yi > pt[1]) !== (yj > pt[1])) && (pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi)) d = !d;
  }
  return d;
}
function tocar(x, y) {
  for (let i = dibujados.length - 1; i >= 0; i--) {
    if (dibujados[i].polis.some(p => dentro([x, y], p))) return dibujados[i].c;
  }
  return null;
}

// ---------------------------------------------------------------- interacción
let arr = null;
cv.addEventListener('contextmenu', e => e.preventDefault());
cv.addEventListener('pointerdown', e => {
  arr = { x: e.clientX, y: e.clientY, mover: e.button === 2 || e.shiftKey, movido: false };
  cv.setPointerCapture(e.pointerId); cv.classList.add('arrastrando');
});
cv.addEventListener('pointermove', e => {
  if (arr) {
    const dx = e.clientX - arr.x, dy = e.clientY - arr.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) arr.movido = true;
    if (arr.mover) { cam.px += dx; cam.py += dy; }
    else { cam.yaw += dx * 0.006; cam.pitch = Math.max(0.05, Math.min(1.5, cam.pitch + dy * 0.005)); }
    arr.x = e.clientX; arr.y = e.clientY; $('#tip').style.display = 'none'; pedirDibujo(); return;
  }
  const c = tocar(e.clientX, e.clientY), tip = $('#tip');
  if (!c) { tip.style.display = 'none'; return; }
  tip.innerHTML = resumenCaja(c);
  tip.style.display = 'block';
  tip.style.left = Math.min(e.clientX + 14, innerWidth - 290) + 'px';
  tip.style.top = Math.min(e.clientY + 14, innerHeight - 120) + 'px';
});
cv.addEventListener('pointerup', e => {
  cv.classList.remove('arrastrando');
  if (arr && !arr.movido) {
    const c = tocar(e.clientX, e.clientY);
    if (c && c.pos) mostrarDetalle(c.pos); else if (c && c.zona) mostrarZona(c.zona); else cerrarDetalle();
  }
  arr = null;
});
cv.addEventListener('wheel', e => {
  e.preventDefault();
  const f = Math.exp(-e.deltaY * 0.0012), z0 = cam.zoom;
  cam.zoom = Math.max(3, Math.min(120, cam.zoom * f));
  const k = cam.zoom / z0, mx = e.clientX - ancho / 2, my = e.clientY - alto / 2;
  cam.px = mx - (mx - cam.px) * k; cam.py = my - (my - cam.py) * k;
  pedirDibujo();
}, { passive: false });
function resumenCaja(c) {
  if (c.zona) return `<b>${c.zona.nom}</b><br>${c.zona.lista.length} LPN`;
  const p = c.pos, un = p.items.reduce((a, i) => a + i.un, 0);
  return `<b>${p.cod}</b> · ${p.esArena ? BLOQUES[p.arena].nom.toLowerCase() : 'nivel ' + p.niv}<br>${p.items.length > 1 ? p.items.length + ' LPN · ' : ''}${p.items[0].sku} · ${un.toLocaleString('es-CL')} UN<br><span style="color:#94a3b8">${p.items[0].d}</span>`;
}
function fila(a, b) { return `<div class="fila"><span>${a}</span><span>${b}</span></div>`; }
function mostrarDetalle(p) {
  seleccion = p; construir(); pedirDibujo();
  const el = $('#detalle');
  el.innerHTML = `<span class="x" onclick="cerrarDetalle()">✕</span><h3>${p.cod}</h3>
    <div style="color:#94a3b8;margin-bottom:8px">${p.esArena
      ? `${BLOQUES[p.arena].nom} · fila ${p.fila} · posición ${p.posn} · ${new Set(p.items.map(i => i.lpn || i.sku)).size} de 2 pallets`
      : `Rack ${p.rack} · columna ${p.col} · nivel ${p.niv} (${p.niv <= 1 ? 'picking' : 'reserva'})`}</div>` +
    p.items.map(i => {
      const d = diasVence(i.v);
      return `<div class="item"><b>${i.sku}</b><div style="color:#94a3b8;font-size:12px;margin-bottom:4px">${i.d}</div>` +
        fila('LPN', i.lpn) + fila('Unidades', i.un.toLocaleString('es-CL') + (i.cj ? ` (${i.cj} cajas)` : '')) +
        fila('Lote', i.lote) + fila('Vencimiento', i.v + (d === null ? '' : ` · ${d < 0 ? 'vencido' : d + ' días'}`)) +
        fila('Calidad', i.qa) + '</div>';
    }).join('');
  el.style.display = 'block';
}
function mostrarZona(z) {
  seleccion = null; construir(); pedirDibujo();
  const el = $('#detalle');
  el.innerHTML = `<span class="x" onclick="cerrarDetalle()">✕</span><h3>${z.nom}</h3><div style="color:#94a3b8;margin-bottom:8px">${z.lista.length} LPN</div>` +
    z.lista.slice(0, 150).map(i => `<div class="item">${fila(i.lpn, (i.un || 0).toLocaleString('es-CL') + ' UN')}<div style="font-size:12px">${i.sku} · <span style="color:#94a3b8">${i.d || ''}</span></div></div>`).join('');
  el.style.display = 'block';
}
function cerrarDetalle() { seleccion = null; $('#detalle').style.display = 'none'; construir(); pedirDibujo(); }
window.cerrarDetalle = cerrarDetalle;

document.querySelectorAll('[data-vista]').forEach(b => b.onclick = () => {
  document.querySelectorAll('[data-vista]').forEach(x => x.classList.remove('on')); b.classList.add('on');
  const v = b.dataset.vista;
  if (v === 'iso') { cam.yaw = -0.72; cam.pitch = 0.62; }
  if (v === 'planta') { cam.yaw = 0; cam.pitch = 1.5; }
  if (v === 'frente') { cam.yaw = 0; cam.pitch = 0.12; }
  centrar(); pedirDibujo();
});
$('#reset').onclick = () => { cam.yaw = -0.72; cam.pitch = 0.62; centrar(); pedirDibujo(); };
document.querySelectorAll('[data-modo]').forEach(b => b.onclick = () => {
  document.querySelectorAll('[data-modo]').forEach(x => x.classList.remove('on')); b.classList.add('on');
  modo = b.dataset.modo; construir(); pintarLeyenda(); pedirDibujo();
});
$('#buscar').oninput = e => {
  busqueda = e.target.value.trim().toUpperCase();
  const res = $('#resultados');
  if (!busqueda) { res.innerHTML = ''; } else {
    const hits = [...posiciones.values(), ...arenas.values()].filter(p => p.items.some(coincide) || p.cod.includes(busqueda));
    res.innerHTML = `${hits.length} posición(es)` + hits.slice(0, 12).map(p =>
      `<div data-cod="${p.cod}">${p.cod} · ${p.items[0] ? p.items[0].sku + ' · ' + p.items.reduce((a, i) => a + i.un, 0) + ' UN' : 'vacía'}</div>`).join('');
    res.querySelectorAll('[data-cod]').forEach(d => d.onclick = () => irA(posiciones.get(d.dataset.cod) || arenas.get(d.dataset.cod)));
  }
  construir(); pintarLeyenda(); pedirDibujo();
};
function irA(p) {
  if (p.esArena) {
    if (filtroRack) { filtroRack = null; pintarRacks(); construir(); }
    cam.cx = p.x + CEL / 2; cam.cy = 0.8; cam.cz = p.z + CEL / 2;
    cam.px = 120; cam.py = 0; cam.zoom = Math.max(cam.zoom, 42);
    return mostrarDetalle(p);
  }
  const r = infoRack[p.rack];
  if (filtroRack && filtroRack !== p.rack) { filtroRack = null; pintarRacks(); }
  cam.cx = (p.col - 0.5) * W; cam.cy = (p.niv - 0.5) * H; cam.cz = r.idx * PASO_Z + PROF / 2;
  cam.px = 120; cam.py = 0; cam.zoom = Math.max(cam.zoom, 42);
  mostrarDetalle(p);
}
function pintarRacks() {
  const el = $('#racks');
  el.innerHTML = `<div class="rack ${!filtroRack ? 'on' : ''}" data-r=""><span class="l">⌂</span><span style="flex:1">Toda la bodega</span></div>` +
    letras.map(l => {
      const r = infoRack[l], pc = r.total ? Math.round(r.ocup * 100 / r.total) : 0;
      return `<div class="rack ${filtroRack === l ? 'on' : ''}" data-r="${l}"><span class="l">${l}</span><span class="barra"><i style="width:${pc}%"></i></span><span class="p">${r.ocup}/${r.total} · ${pc}%</span></div>`;
    }).join('') +
    Object.entries(BLOQUES).filter(([k, b]) => b.pos).map(([k, b]) => {
      const pc = Math.round(b.ocup * 100 / b.pos);
      return `<div class="rack" title="${b.nom}"><span class="l" style="color:${k === 'ME' ? '#ef4444' : '#d4a373'}">${k}</span><span class="barra"><i style="width:${pc}%;background:${k === 'ME' ? '#ef4444' : '#d4a373'}"></i></span><span class="p">${b.ocup}/${b.pos} · ${pc}%</span></div>`;
    }).join('');
  el.querySelectorAll('[data-r]').forEach(d => d.onclick = () => {
    filtroRack = d.dataset.r || null; pintarRacks(); construir(); centrar();
    pedirDibujo();
  });
}
// ---------------------------------------------------------------- inicio
const total = posiciones.size, ocup = [...posiciones.values()].filter(p => p.items.length).length;
$('#k_ocup').textContent = total ? Math.round(ocup * 100 / total) + '%' : '–';
$('#k_pos').textContent = ocup + ' / ' + total;
$('#k_lpn').textContent = D.stock.filter(i => !i.u.startsWith('ZONA')).length.toLocaleString('es-CL');
$('#k_and').textContent = D.anden.length.toLocaleString('es-CL');
redimensionar(); centrar(); construir(); pintarRacks(); pintarLeyenda(); pedirDibujo();
addEventListener('resize', () => { redimensionar(); centrar(); pedirDibujo(); });
</script>
</body>
</html>
"""
