"""Resumen ejecutivo en Excel (mismo formato para recepciones y despachos).

Hojas:
  · Resumen: indicadores, datos generales, resumen por fecha de recepción (o por pallet en un despacho),
    resumen por vencimiento y gráfico de unidades por SKU.
  · Consolidado por SKU: una fila por SKU con lotes, vencimientos, cajas, unidades y estatus.
  · Detalle: una fila por SKU / lote / fecha (o por LPN en un despacho).
Las sumas del Resumen y del Consolidado son fórmulas sobre el Detalle (si alguien corrige el
Detalle a mano, todo se recalcula). Uso:
    reporte_recepcion(datos, ruta)   datos = rpc wms_reporte_recepcion (script 51)
    reporte_despacho(detalle, ruta)  detalle = rpc wms_despacho_detalle (script 50)
"""
import re
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

AZUL = "1F3A52"
AZUL_2 = "345470"
TEXTO = "1A2634"
GRIS_ETIQ = "556778"
FONDO_ETIQ = "EAF1F6"
FONDO_TOTAL = "DDE8F0"
BLANCO = "FFFFFF"
FMT_FECHA = 'dd"/"mm"/"yyyy'
FMT_FECHA_HORA = 'dd"/"mm"/"yyyy\\ hh:mm'
FMT_MILES = "#,##0"
FMT_PCT = "0.0%"

_fino = Side(style="thin", color="C9D6E2")
B_FINO = Border(left=_fino, right=_fino, top=_fino, bottom=_fino)
B_CAB = Border(left=_fino, right=_fino, top=Side(style="medium", color=AZUL), bottom=Side(style="medium", color=AZUL))
B_TOTAL = Border(left=_fino, right=_fino, top=Side(style="thin", color=AZUL), bottom=Side(style="double", color=AZUL))


# ----------------------------------------------------------------------------- utilidades

# ----------------------------------------------------------------------------------------------
# Nombre de archivo de los reportes de recepción: OC_<n°>_<PO>_<Proveedor>[_<contenedor>].<ext>
#   El PO se toma de la nota de la OC (ej. "SA20260821 (PO1084)"); si no viene, se omite.
# ----------------------------------------------------------------------------------------------
def extraer_po(*textos) -> str:
    for t in textos:
        m = re.search(r"\bPO\s*[-#:]?\s*(\d{2,})", str(t or ""), re.I)
        if m:
            return f"PO{m.group(1)}"
    return ""


def _parte_archivo(texto, largo=60) -> str:
    t = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", str(texto or ""))
    t = re.sub(r"\s+", " ", t).strip().strip(".").strip()
    return t[:largo].strip()


def nombre_reporte_recepcion(numero_oc=None, nota=None, proveedor=None, contenedor=None,
                             extension="xlsx", prefijo="") -> str:
    oc = re.sub(r"^OC[\s\-_#:]*", "", str(numero_oc or "").strip(), flags=re.I)
    if oc.upper() in ("", "S/OC", "S/N", "NONE", "LIBRE", "N/A"):
        oc = ""
    po = extraer_po(nota)
    if po and po.upper() == oc.upper():
        po = ""
    partes = [f"OC_{_parte_archivo(oc, 30)}" if oc else "SIN_OC", po, _parte_archivo(proveedor, 50),
              _parte_archivo(contenedor, 30)]
    return f"{prefijo}{'_'.join(p for p in partes if p)}.{extension}"


def nombre_reporte_desde_datos(datos: dict, extension="xlsx", prefijo="") -> str:
    """Nombre a partir de lo que devuelve wms_reporte_recepcion (agrega el contenedor si el reporte es de uno solo)."""
    datos = datos or {}
    return nombre_reporte_recepcion(
        datos.get("numero_oc"), " ".join(str(datos.get(k) or "") for k in ("codigo_asn", "nota_oc")),
        datos.get("proveedor"), datos.get("contenedor") if datos.get("solo_contenedor") else None,
        extension, prefijo)

def _fecha(v):
    """'DD-MM-YYYY', 'YYYY-MM-DD', date o datetime -> date (o el texto si no se puede)."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return s


def _n(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _txt_fecha(v):
    f = _fecha(v)
    return f.strftime("%d/%m/%Y") if isinstance(f, date) else (str(f) if f else "")


def _celda(ws, ref, valor=None, *, bold=False, size=10, color=TEXTO, fondo=None, fmt=None, h="left", borde=None, wrap=False):
    c = ws[ref]
    if valor is not None:
        c.value = valor
    c.font = Font(name="Calibri", bold=bold, size=size, color=color)
    if fondo:
        c.fill = PatternFill("solid", fgColor=fondo)
    if fmt:
        c.number_format = fmt
    c.alignment = Alignment(horizontal=h, vertical="center", wrap_text=wrap)
    if borde:
        c.border = borde
    return c


def _imprimir(ws, horizontal=True):
    ws.page_setup.orientation = "landscape" if horizontal else "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_LETTER
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_options.horizontalCentered = True
    ws.page_margins.left = ws.page_margins.right = 0.4


def _titulo(ws, ultima_col, titulo, subtitulo):
    ws.merge_cells(f"A1:{ultima_col}1")
    ws.merge_cells(f"A2:{ultima_col}2")
    _celda(ws, "A1", titulo, bold=True, size=15, color=BLANCO, fondo=AZUL)
    _celda(ws, "A2", subtitulo, size=10, color="DCE6F0", fondo=AZUL_2)
    for col in range(1, ws[f"{ultima_col}1"].column + 1):
        ws.cell(row=1, column=col).fill = PatternFill("solid", fgColor=AZUL)
        ws.cell(row=2, column=col).fill = PatternFill("solid", fgColor=AZUL_2)
    ws.row_dimensions[1].height = 30
    ws.row_dimensions[2].height = 20
    ws.sheet_view.showGridLines = False
    _imprimir(ws, horizontal=ultima_col != "H")


def _seccion(ws, fila, ultima_col, texto):
    ws.merge_cells(f"A{fila}:{ultima_col}{fila}")
    _celda(ws, f"A{fila}", texto, bold=True, size=11, color=AZUL)
    ws.row_dimensions[fila].height = 20


def _cabecera_tabla(ws, fila, titulos, col_ini=1):
    for i, t in enumerate(titulos):
        c = ws.cell(row=fila, column=col_ini + i, value=t)
        c.font = Font(name="Calibri", bold=True, size=10, color=BLANCO)
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = B_CAB
    ws.row_dimensions[fila].height = 30


def _fila(ws, fila, valores, formatos=None, col_ini=1, total=False):
    formatos = formatos or {}
    for i, v in enumerate(valores):
        c = ws.cell(row=fila, column=col_ini + i, value=v)
        fmt = formatos.get(i)
        c.font = Font(name="Calibri", bold=total or (i == 0), size=10, color=AZUL if total else TEXTO)
        c.fill = PatternFill("solid", fgColor=FONDO_TOTAL if total else BLANCO)
        c.border = B_TOTAL if total else B_FINO
        if fmt:
            c.number_format = fmt
        num = isinstance(v, (int, float)) or (isinstance(v, str) and v.startswith("="))
        c.alignment = Alignment(horizontal="right" if (num and fmt != FMT_FECHA) else "center" if fmt in (FMT_FECHA, FMT_FECHA_HORA) else "left",
                                vertical="center")


def _anchos(ws, anchos):
    for i, w in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _kpis(ws, fila, kpis):
    """4 indicadores de 2 columnas cada uno (A:B, C:D, E:F, G:H)."""
    for i, (etiqueta, valor, fmt) in enumerate(kpis[:4]):
        c1, c2 = get_column_letter(1 + i * 2), get_column_letter(2 + i * 2)
        ws.merge_cells(f"{c1}{fila}:{c2}{fila}")
        ws.merge_cells(f"{c1}{fila + 1}:{c2}{fila + 1}")
        _celda(ws, f"{c1}{fila}", etiqueta, bold=True, size=9, color=GRIS_ETIQ, fondo=FONDO_ETIQ, h="center", borde=B_FINO)
        _celda(ws, f"{c1}{fila + 1}", valor, bold=True, size=16, color=AZUL, fondo=BLANCO, fmt=fmt or FMT_MILES, h="center", borde=B_FINO)
        for col in (c1, c2):
            ws[f"{col}{fila}"].border = B_FINO
            ws[f"{col}{fila + 1}"].border = B_FINO
    ws.row_dimensions[fila + 1].height = 28


def _datos_generales(ws, fila, pares):
    """Pares (etiqueta, valor) en dos columnas: A:B etiqueta, C:D valor, E:F etiqueta, G:H valor."""
    for i in range(0, len(pares), 2):
        for j, (et, val) in enumerate(pares[i:i + 2]):
            ce, cv1, cv2 = (("A", "C", "D") if j == 0 else ("E", "G", "H"))
            ce2 = "B" if j == 0 else "F"
            ws.merge_cells(f"{ce}{fila}:{ce2}{fila}")
            ws.merge_cells(f"{cv1}{fila}:{cv2}{fila}")
            _celda(ws, f"{ce}{fila}", et, bold=True, color=TEXTO, fondo=FONDO_ETIQ, borde=B_FINO)
            fmt = FMT_FECHA if isinstance(val, date) and not isinstance(val, datetime) else (FMT_FECHA_HORA if isinstance(val, datetime) else "@")
            _celda(ws, f"{cv1}{fila}", val if val not in (None, "") else "—", fondo=BLANCO, fmt=fmt, borde=B_FINO)
            for col in (ce2, cv2):
                ws[f"{col}{fila}"].border = B_FINO
        fila += 1
    return fila


def _grafico_sku(ws_destino, ancla, ws_datos, col_cat, col_val, fila_ini, fila_fin, titulo, col_val2=None, titulo_2=None):
    if fila_fin < fila_ini:
        return
    g = BarChart()
    g.type = "bar"
    g.style = 10
    g.title = titulo
    g.y_axis.title = "Unidades"
    g.y_axis.numFmt = FMT_MILES
    g.y_axis.majorGridlines = None
    datos = Reference(ws_datos, min_col=col_val, min_row=fila_ini - 1, max_row=fila_fin)
    g.add_data(datos, titles_from_data=True)
    if col_val2:
        g.add_data(Reference(ws_datos, min_col=col_val2, min_row=fila_ini - 1, max_row=fila_fin), titles_from_data=True)
    g.set_categories(Reference(ws_datos, min_col=col_cat, min_row=fila_ini, max_row=fila_fin))
    g.series[0].graphicalProperties.solidFill = "2A78C2"
    g.series[0].graphicalProperties.line.noFill = True
    if col_val2 and len(g.series) > 1:
        g.series[1].graphicalProperties.solidFill = "B8C7D6"
        g.series[1].graphicalProperties.line.noFill = True
    g.gapWidth = 60
    g.height = max(7, 0.65 * (fila_fin - fila_ini + 1) + 3)
    g.width = 24
    if col_val2:
        g.legend.position = "b"
    else:
        g.legend = None
    ws_destino.add_chart(g, ancla)


# ----------------------------------------------------------------------------- recepción
def reporte_recepcion(datos: dict, ruta: str, emitido: datetime = None) -> str:
    emitido = emitido or datetime.now()
    lineas = list(datos.get("lineas") or [])
    oc_sku = {str(x.get("sku")).upper(): x for x in (datos.get("oc") or [])}
    numero_oc = datos.get("numero_oc")
    doc = f"OC {numero_oc}" if numero_oc else "RECEPCIÓN LIBRE"
    proveedor = datos.get("proveedor") or "—"
    contenedor = datos.get("contenedor") or "—"
    fechas = sorted({_fecha(l.get("fecha")) for l in lineas if isinstance(_fecha(l.get("fecha")), date)})
    fechas_txt = " y ".join(f.strftime("%d/%m/%Y") for f in fechas) if len(fechas) <= 3 else \
        f"{fechas[0]:%d/%m/%Y} al {fechas[-1]:%d/%m/%Y} ({len(fechas)} días)"

    # recibido por SKU y estatus contra la OC
    rec_sku = {}
    for l in lineas:
        s = str(l.get("sku")).upper()
        rec_sku[s] = rec_sku.get(s, 0) + _n(l.get("unidades"))

    solo_contenedor = bool(datos.get("solo_contenedor"))

    def estatus(sku):
        o = oc_sku.get(sku)
        if not numero_oc:
            return "SIN OC"
        if not o or not _n(o.get("unidades_oc")):
            return "FUERA DE OC"
        if solo_contenedor:
            # reporte de un contenedor: se compara contra su packing list (si se cargó), no contra toda la OC
            if datos.get("pl_contenedor"):
                dif = rec_sku.get(sku, 0) - _n(o.get("unidades_pl"))
                if not _n(o.get("unidades_pl")):
                    return "NO VIENE EN EL PL"
                return "OK vs PL" if dif == 0 else (f"SOBRANTE vs PL (+{dif})" if dif > 0 else f"FALTANTE vs PL ({dif})")
            return "RECIBIDO EN CONTENEDOR" if rec_sku.get(sku, 0) else "NO VINO EN ESTE CONTENEDOR"
        dif = rec_sku.get(sku, 0) - _n(o.get("unidades_oc"))
        return "OK (VALIDADA)" if dif == 0 else (f"SOBRANTE (+{dif})" if dif > 0 else f"PARCIAL ({dif})")

    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    wc = wb.create_sheet("Consolidado por SKU")
    wd = wb.create_sheet("Detalle Recepciones")

    # ---------------- Detalle ----------------
    cols_d = ["N°", "OC", "Proveedor", "Contenedor / Guía", "SKU", "Descripción", "Lote", "Vencimiento", "Fecha Recepción",
              "Pallets", "Cajas", "Unidades Recibidas", "Unid. / Caja", "Uni en OC", "Uni en PL", "Estatus OC",
              "Referencia / Nota", "Operadores"]
    _titulo(wd, "R", f"LUDIPEK WMS — DETALLE COMPLETO DE RECEPCIONES ({doc})",
            f"Proveedor: {proveedor} | Contenedor: {contenedor} | Bodega: {datos.get('bodega') or ''}")
    _cabecera_tabla(wd, 4, cols_d)
    ya_oc = set()
    f0 = 5
    for i, l in enumerate(lineas):
        r = f0 + i
        s = str(l.get("sku")).upper()
        o = oc_sku.get(s) or {}
        primera = s not in ya_oc
        ya_oc.add(s)
        fecha = _fecha(l.get("fecha"))
        _fila(wd, r, [i + 1, numero_oc or "SIN OC", proveedor, l.get("contenedor") or contenedor, s,
                      str(l.get("descripcion") or "")[:40], l.get("lote"), _fecha(l.get("vencimiento")), fecha,
                      _n(l.get("pallets")), _n(l.get("cajas")), _n(l.get("unidades")), f"=IF(K{r}>0,L{r}/K{r},0)",
                      (_n(o.get("unidades_oc")) if o.get("unidades_oc") is not None else "-") if primera else "",
                      (_n(o.get("unidades_pl")) if o.get("unidades_pl") is not None else "-") if primera else "",
                      estatus(s), f"{doc} (Recepción {_txt_fecha(fecha)})", l.get("operadores")],
             {7: FMT_FECHA, 8: FMT_FECHA, 9: FMT_MILES, 10: FMT_MILES, 11: FMT_MILES, 12: FMT_MILES, 13: FMT_MILES, 14: FMT_MILES})
    fin = f0 + max(len(lineas), 1) - 1
    rt = fin + 1
    _fila(wd, rt, ["", "", "", "", "TOTAL GENERAL", f'=COUNTA(E{f0}:E{fin})&" líneas registradas"', "", "", "",
                   f"=SUM(J{f0}:J{fin})", f"=SUM(K{f0}:K{fin})", f"=SUM(L{f0}:L{fin})", f"=IF(K{rt}>0,L{rt}/K{rt},0)",
                   "", "", "", "", ""], {9: FMT_MILES, 10: FMT_MILES, 11: FMT_MILES, 12: FMT_MILES}, total=True)
    _anchos(wd, [5, 9, 18, 18, 15, 34, 12, 13, 15, 9, 11, 16, 11, 11, 11, 18, 32, 22])
    wd.freeze_panes = "A5"
    wd.auto_filter.ref = f"A4:R{fin}"
    rng = lambda col: f"'Detalle Recepciones'!${col}${f0}:${col}${fin}"

    # ---------------- Consolidado por SKU ----------------
    if solo_contenedor:   # un contenedor: lo recibido + lo que trae su PL (no toda la OC)
        skus = sorted(rec_sku) + sorted(s for s in oc_sku if s not in rec_sku and datos.get("pl_contenedor")
                                        and _n(oc_sku[s].get("unidades_pl")))
    else:
        skus = sorted(rec_sku) + sorted(s for s in oc_sku if s not in rec_sku)
    cols_c = ["SKU", "Descripción", "Lote(s)", "Vencimiento(s)", "Primera Recepción", "Última Recepción", "N° Recepciones",
              "Unid. / Caja", "Total Cajas", "Total Unidades", "% del Total", "Uni en OC", "Uni en PL", "Diferencia vs OC",
              "Estatus OC"]
    _titulo(wc, "O", f"CONSOLIDADO POR SKU — {doc}",
            f"Agrupa todas las recepciones ({fechas_txt or 'sin recepciones'})")
    _cabecera_tabla(wc, 4, cols_c)
    c0 = 5
    for i, s in enumerate(skus):
        r = c0 + i
        ls = [l for l in lineas if str(l.get("sku")).upper() == s]
        fs = sorted(_fecha(l.get("fecha")) for l in ls if isinstance(_fecha(l.get("fecha")), date))
        vencs = sorted({_txt_fecha(l.get("vencimiento")) for l in ls if l.get("vencimiento")})
        o = oc_sku.get(s) or {}
        desc = (ls[0].get("descripcion") if ls else None) or o.get("descripcion") or ""
        _fila(wc, r, [s, str(desc)[:40], ", ".join(sorted({str(l.get("lote")) for l in ls})) or "SIN INGRESO",
                      vencs[0] if len(vencs) == 1 else (", ".join(vencs) or "—"),
                      fs[0] if fs else "—", fs[-1] if fs else "—",
                      f"=COUNTIF({rng('E')},A{r})", f"=IF(I{r}>0,J{r}/I{r},0)",
                      f"=SUMIF({rng('E')},A{r},{rng('K')})", f"=SUMIF({rng('E')},A{r},{rng('L')})",
                      f"=IF($J${c0 + len(skus)}>0,J{r}/$J${c0 + len(skus)},0)",
                      _n(o.get("unidades_oc")) if o.get("unidades_oc") is not None else "-",
                      _n(o.get("unidades_pl")) if o.get("unidades_pl") is not None else "-",
                      f"=IF(ISNUMBER(L{r}),J{r}-L{r},\"-\")", estatus(s)],
             {4: FMT_FECHA, 5: FMT_FECHA, 6: FMT_MILES, 7: FMT_MILES, 8: FMT_MILES, 9: FMT_MILES, 10: FMT_PCT,
              11: FMT_MILES, 12: FMT_MILES, 13: '+#,##0;-#,##0;0'})
    cfin = c0 + max(len(skus), 1) - 1
    ct = cfin + 1
    _fila(wc, ct, ["TOTAL", f'=COUNTA(A{c0}:A{cfin})&" SKUs"', "", "", "", "", f"=SUM(G{c0}:G{cfin})",
                   f"=IF(I{ct}>0,J{ct}/I{ct},0)", f"=SUM(I{c0}:I{cfin})", f"=SUM(J{c0}:J{cfin})", f"=SUM(K{c0}:K{cfin})",
                   f"=SUM(L{c0}:L{cfin})", f"=SUM(M{c0}:M{cfin})", f"=SUM(N{c0}:N{cfin})", ""],
         {6: FMT_MILES, 7: FMT_MILES, 8: FMT_MILES, 9: FMT_MILES, 10: FMT_PCT, 11: FMT_MILES, 12: FMT_MILES,
          13: '+#,##0;-#,##0;0'}, total=True)
    multi = [s for s in rec_sku if len({_fecha(l.get("fecha")) for l in lineas if str(l.get("sku")).upper() == s}) > 1]
    if multi:
        nota = ct + 2
        wc.merge_cells(f"A{nota}:O{nota}")
        _celda(wc, f"A{nota}", "* Recibidos en más de una fecha: " + ", ".join(multi[:12]), size=9, color=GRIS_ETIQ)
    _anchos(wc, [15, 34, 18, 16, 15, 15, 12, 11, 12, 14, 11, 11, 11, 14, 18])
    wc.freeze_panes = "A5"

    # ---------------- Resumen ----------------
    _titulo(ws, "H", f"RESUMEN EJECUTIVO DE RECEPCIÓN — {doc}" + (f" · CONTENEDOR {contenedor}" if solo_contenedor else ""),
            f"LUDIPEK WMS | Proveedor: {proveedor} | Contenedor / Guía: {contenedor} | Fecha de Emisión: {emitido:%d/%m/%Y}")
    _kpis(ws, 4, [("TOTAL UNIDADES RECIBIDAS", f"='Detalle Recepciones'!L{rt}", FMT_MILES),
                  ("TOTAL CAJAS RECIBIDAS", f"='Detalle Recepciones'!K{rt}", FMT_MILES),
                  ("SKUS ÚNICOS RECIBIDOS", len(rec_sku), FMT_MILES),
                  ("DÍAS DE RECEPCIÓN", len(fechas), FMT_MILES)])
    _seccion(ws, 7, "H", "1. DATOS GENERALES" + (" DE LA ORDEN DE COMPRA" if numero_oc else " DE LA RECEPCIÓN"))
    ok = all(estatus(s) in ("OK (VALIDADA)", "OK vs PL") for s in skus) if numero_oc and skus else False
    estado_ns = {"SI": "Sí", "PARCIAL": "Parcial", "NO": "No", "SIN_DATO": "Sin dato"}.get(datos.get("cargada_ns"), "—")
    fila = _datos_generales(ws, 8, [
        ("Orden de Compra:", numero_oc or "SIN OC (recepción libre)"), ("Contenedor / Guía:", contenedor),
        ("Proveedor:", proveedor), ("Estatus Conciliación:", ("SOLO ESTE CONTENEDOR" + (" · OK vs PL" if ok else (" · CON DIFERENCIAS vs PL" if datos.get("pl_contenedor") else " · sin PL cargado"))
                                   if solo_contenedor else ("OK (VALIDADA)" if ok else "CON DIFERENCIAS")) if numero_oc else "SIN OC"),
        ("Fechas de Recepción:", fechas_txt or "—"), ("Fecha Emisión:", emitido.replace(microsecond=0)),
        ("Pallets recibidos:", _n(datos.get("pallets"))), ("Recibida en NetSuite:", estado_ns),
        ("Nota de la OC:", str(datos.get("nota_oc") or "—")[:120]), ("SKUs en más de una fecha:", len(multi)),
    ])

    # 2. por fecha de recepción
    fila += 1
    _seccion(ws, fila, "H", "2. RESUMEN POR FECHA DE RECEPCIÓN")
    fila += 1
    _cabecera_tabla(ws, fila, ["Fecha Recepción", "Pallets", "Referencia / Nota", "Contenedor(es)", "Líneas", "Cajas",
                               "Unidades Rec.", "% Unidades"])
    fila += 1
    p0 = fila
    for f in fechas or [None]:
        ls = [l for l in lineas if _fecha(l.get("fecha")) == f]
        conts = sorted({str(l.get("contenedor")) for l in ls if l.get("contenedor")})
        _fila(ws, fila, [f if f else "—", f"=SUMIF({rng('I')},A{fila},{rng('J')})", f"{doc} (Recepción {_txt_fecha(f)})",
                         ", ".join(conts)[:40] or contenedor, f"=COUNTIF({rng('I')},A{fila})",
                         f"=SUMIF({rng('I')},A{fila},{rng('K')})", f"=SUMIF({rng('I')},A{fila},{rng('L')})",
                         f"=IF($G${p0 + max(len(fechas), 1)}>0,G{fila}/$G${p0 + max(len(fechas), 1)},0)"],
             {0: FMT_FECHA, 1: FMT_MILES, 4: FMT_MILES, 5: FMT_MILES, 6: FMT_MILES, 7: FMT_PCT})
        fila += 1
    _fila(ws, fila, ["TOTAL", f"=SUM(B{p0}:B{fila - 1})", "", "", f"=SUM(E{p0}:E{fila - 1})", f"=SUM(F{p0}:F{fila - 1})",
                     f"=SUM(G{p0}:G{fila - 1})", f"=SUM(H{p0}:H{fila - 1})"],
         {1: FMT_MILES, 4: FMT_MILES, 5: FMT_MILES, 6: FMT_MILES, 7: FMT_PCT}, total=True)

    # 3. por vencimiento
    fila += 2
    _seccion(ws, fila, "H", "3. RESUMEN POR FECHA DE VENCIMIENTO")
    fila += 1
    _cabecera_tabla(ws, fila, ["Fecha Vencimiento", "Descripción (SKUs)", "Lotes Incluidos", "SKUs Únicos", "Líneas", "Cajas",
                               "Unidades Rec.", "% Unidades"])
    fila += 1
    v0 = fila
    vencs = sorted({_fecha(l.get("vencimiento")) for l in lineas if l.get("vencimiento")},
                   key=lambda x: (not isinstance(x, date), str(x)))
    for v in vencs or [None]:
        ls = [l for l in lineas if _fecha(l.get("vencimiento")) == v]
        descs = sorted({str(l.get("descripcion") or l.get("sku"))[:22] for l in ls})
        _fila(ws, fila, [v if v else "—", ", ".join(descs[:3]) + (f" +{len(descs) - 3}" if len(descs) > 3 else ""),
                         ", ".join(sorted({str(l.get("lote")) for l in ls}))[:60], len({l.get("sku") for l in ls}),
                         f"=COUNTIF({rng('H')},A{fila})", f"=SUMIF({rng('H')},A{fila},{rng('K')})",
                         f"=SUMIF({rng('H')},A{fila},{rng('L')})",
                         f"=IF($G${v0 + max(len(vencs), 1)}>0,G{fila}/$G${v0 + max(len(vencs), 1)},0)"],
             {0: FMT_FECHA, 3: FMT_MILES, 4: FMT_MILES, 5: FMT_MILES, 6: FMT_MILES, 7: FMT_PCT})
        fila += 1
    _fila(ws, fila, ["TOTAL", "", "", f"=SUM(D{v0}:D{fila - 1})", f"=SUM(E{v0}:E{fila - 1})", f"=SUM(F{v0}:F{fila - 1})",
                     f"=SUM(G{v0}:G{fila - 1})", f"=SUM(H{v0}:H{fila - 1})"],
         {3: FMT_MILES, 4: FMT_MILES, 5: FMT_MILES, 6: FMT_MILES, 7: FMT_PCT}, total=True)

    # 4. gráfico
    fila += 2
    _seccion(ws, fila, "H", "4. DISTRIBUCIÓN DE UNIDADES RECIBIDAS POR SKU" + (" (contra la OC)" if oc_sku else ""))
    _grafico_sku(ws, f"A{fila + 1}", wc, 1, 10, c0, cfin, "Unidades recibidas por SKU",
                 col_val2=12 if oc_sku else None)
    _anchos(ws, [18, 26, 30, 30, 10, 13, 16, 13])
    wb.save(ruta)
    return ruta


# ----------------------------------------------------------------------------- despacho
def reporte_despacho(detalle: dict, ruta: str, emitido: datetime = None) -> str:
    emitido = emitido or datetime.now()
    cab = detalle.get("despacho") or {}
    skus = list(detalle.get("sku") or [])
    lpns = list(detalle.get("lpns") or [])
    tot = detalle.get("totales") or {}
    info = {str(s.get("sku")).upper(): s for s in skus}
    doc = f"DESPACHO {cab.get('numero')}"
    destino = cab.get("destino") or "—"
    contenedor = cab.get("contenedor") or "—"

    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    wc = wb.create_sheet("Consolidado por SKU")
    wd = wb.create_sheet("Detalle por LPN")

    # ---------------- Detalle ----------------
    cols_d = ["N°", "Despacho", "Destino", "Contenedor", "LPN", "Ubicación origen", "SKU", "Descripción", "Lote",
              "Vencimiento", "Fecha Escaneo", "Cajas", "Displays", "Unid. sueltas", "Unidades", "Unid. / Caja", "Peso neto kg",
              "Peso bruto pallet kg", "m³ pallet", "Escaneado por"]
    _titulo(wd, "T", f"LUDIPEK WMS — DETALLE DEL DESPACHO ({cab.get('numero')})",
            f"Destino: {destino} | Contenedor: {contenedor} | Referencia: {cab.get('referencia') or '—'}")
    _cabecera_tabla(wd, 4, cols_d)
    f0, i = 5, 0
    for l in sorted(lpns, key=lambda x: str(x.get("escaneado_en") or "")):
        for k_c, c in enumerate(l.get("contenido") or []):
            r = f0 + i
            s = str(c.get("sku")).upper()
            emp = c.get("empaque") or {}
            peso_un = (float(info.get(s, {}).get("peso_kg") or 0) / max(1, _n(info.get(s, {}).get("unidades")))) if info.get(s) else 0
            peso_linea = float(c["peso_kg"]) if c.get("peso_kg") is not None else round(_n(c.get("unidades")) * peso_un, 2)
            # peso bruto y m³ son del pallet completo: van solo en su primera línea (así las sumas no se duplican)
            bruto = float(l.get("peso_bruto_kg") or 0) if k_c == 0 and l.get("peso_bruto_kg") is not None else None
            m3 = float(l.get("m3")) if k_c == 0 and l.get("m3") is not None else None
            esc = l.get("escaneado_en")
            try:
                esc = datetime.fromisoformat(str(esc).replace("Z", "+00:00")).astimezone().replace(tzinfo=None) if esc else None
            except ValueError:
                esc = None
            _fila(wd, r, [i + 1, cab.get("numero"), destino, contenedor, l.get("lpn"), l.get("ubicacion"), s,
                          str(info.get(s, {}).get("descripcion") or "")[:40], c.get("lote"), _fecha(c.get("vencimiento")),
                          esc, _n(emp.get("cajas")), _n(emp.get("displays")), _n(emp.get("sueltas")), _n(c.get("unidades")),
                          _n(info.get(s, {}).get("multiplo_caja")) or "-", peso_linea, bruto, m3,
                          l.get("escaneado_por")],
                 {9: FMT_FECHA, 10: FMT_FECHA_HORA, 11: FMT_MILES, 12: FMT_MILES, 13: FMT_MILES, 14: FMT_MILES, 16: "#,##0.0",
                  17: "#,##0.0", 18: "0.000"})
            i += 1
    fin = f0 + max(i, 1) - 1
    rt = fin + 1
    _fila(wd, rt, ["", "", "", "", f'=SUMPRODUCT((E{f0}:E{fin}<>"")/COUNTIF(E{f0}:E{fin},E{f0}:E{fin}&""))', "",
                   "TOTAL GENERAL", f'=COUNTA(G{f0}:G{fin})&" líneas"', "", "", "", f"=SUM(L{f0}:L{fin})",
                   f"=SUM(M{f0}:M{fin})", f"=SUM(N{f0}:N{fin})", f"=SUM(O{f0}:O{fin})", "", f"=SUM(Q{f0}:Q{fin})",
                   f"=SUM(R{f0}:R{fin})", f"=SUM(S{f0}:S{fin})", ""],
         {4: FMT_MILES, 11: FMT_MILES, 12: FMT_MILES, 13: FMT_MILES, 14: FMT_MILES, 16: "#,##0.0", 17: "#,##0.0", 18: "0.00"},
         total=True)
    _anchos(wd, [5, 18, 10, 16, 16, 14, 15, 34, 12, 13, 17, 9, 10, 11, 12, 11, 12, 14, 11, 16])
    wd.freeze_panes = "A5"
    wd.auto_filter.ref = f"A4:T{fin}"
    rng = lambda col: f"'Detalle por LPN'!${col}${f0}:${col}${fin}"

    # ---------------- Consolidado ----------------
    cols_c = ["SKU", "Descripción", "Lote(s)", "Vencimiento(s)", "Pallets", "Pallets pedidos", "Cajas", "Displays",
              "Unid. sueltas", "Total Unidades", "Pedido UN", "Diferencia", "% Avance", "Peso neto kg", "Peso bruto kg", "m³",
              "Estatus"]
    _titulo(wc, "Q", f"CONSOLIDADO POR SKU — {doc}", f"Destino {destino} | contra el pedido cargado")
    _cabecera_tabla(wc, 4, cols_c)
    c0 = 5
    for j, s in enumerate(skus):
        r = c0 + j
        lotes = s.get("lotes") or []
        vencs = sorted({_txt_fecha(x.get("vencimiento")) for x in lotes})
        if not _n(tot.get("pedido_unidades")):
            est = "SIN PEDIDO CARGADO"
        elif not s.get("en_pedido"):
            est = "FUERA DEL PEDIDO"
        elif _n(s.get("falta")):
            est = f"FALTAN {_n(s.get('falta')):,}".replace(",", ".")
        elif _n(s.get("sobra")):
            est = f"SOBRAN {_n(s.get('sobra')):,}".replace(",", ".")
        else:
            est = "COMPLETO"
        pp = s.get("pedido_pallets")
        if pp is not None and s.get("en_pedido") and _n(s.get("pallets")) != round(float(pp)):
            est += f" · {_n(s.get('pallets'))} de {float(pp):g} pallets"
        _fila(wc, r, [s.get("sku"), str(s.get("descripcion") or "")[:40], ", ".join(str(x.get("lote")) for x in lotes) or "—",
                      vencs[0] if len(vencs) == 1 else (", ".join(vencs) or "—"), _n(s.get("pallets")),
                      float(pp) if pp is not None else "-",
                      f"=SUMIF({rng('G')},A{r},{rng('L')})", f"=SUMIF({rng('G')},A{r},{rng('M')})",
                      f"=SUMIF({rng('G')},A{r},{rng('N')})", f"=SUMIF({rng('G')},A{r},{rng('O')})",
                      _n(s.get("pedido_unidades")) if s.get("pedido_unidades") is not None else "-",
                      f"=IF(ISNUMBER(K{r}),J{r}-K{r},\"-\")", f"=IF(AND(ISNUMBER(K{r}),K{r}>0),J{r}/K{r},\"-\")",
                      f"=SUMIF({rng('G')},A{r},{rng('Q')})",
                      float(s.get("peso_bruto_kg") or 0), float(s.get("m3")) if s.get("m3") is not None else "-", est],
             {4: FMT_MILES, 5: "#,##0.##", 6: FMT_MILES, 7: FMT_MILES, 8: FMT_MILES, 9: FMT_MILES, 10: FMT_MILES,
              11: '+#,##0;-#,##0;0', 12: FMT_PCT, 13: "#,##0.0", 14: "#,##0.0", 15: "0.00"})
    cfin = c0 + max(len(skus), 1) - 1
    ct = cfin + 1
    _fila(wc, ct, ["TOTAL", f'=COUNTA(A{c0}:A{cfin})&" SKUs"', "", "", f"=SUM(E{c0}:E{cfin})", f"=SUM(F{c0}:F{cfin})",
                   f"=SUM(G{c0}:G{cfin})", f"=SUM(H{c0}:H{cfin})", f"=SUM(I{c0}:I{cfin})", f"=SUM(J{c0}:J{cfin})",
                   f"=SUM(K{c0}:K{cfin})", f"=J{ct}-K{ct}", f"=IF(K{ct}>0,J{ct}/K{ct},0)", f"=SUM(N{c0}:N{cfin})",
                   f"=SUM(O{c0}:O{cfin})", f"=SUM(P{c0}:P{cfin})", ""],
         {4: FMT_MILES, 5: "#,##0.##", 6: FMT_MILES, 7: FMT_MILES, 8: FMT_MILES, 9: FMT_MILES, 10: FMT_MILES,
          11: '+#,##0;-#,##0;0', 12: FMT_PCT, 13: "#,##0.0", 14: "#,##0.0", 15: "0.00"}, total=True)
    _anchos(wc, [15, 34, 18, 16, 9, 10, 10, 10, 11, 13, 12, 12, 10, 12, 12, 9, 26])
    wc.freeze_panes = "A5"

    # ---------------- Resumen ----------------
    _titulo(ws, "H", f"RESUMEN EJECUTIVO DE DESPACHO — {cab.get('numero')}",
            f"LUDIPEK WMS | Destino: {destino} | Contenedor: {contenedor} | Fecha de Emisión: {emitido:%d/%m/%Y}")
    _kpis(ws, 4, [("TOTAL UNIDADES DESPACHADAS", f"='Detalle por LPN'!O{rt}", FMT_MILES),
                  ("TOTAL CAJAS", f"='Detalle por LPN'!L{rt}", FMT_MILES),
                  ("PALLETS (LPN)", len(lpns), FMT_MILES),
                  ("AVANCE SOBRE PEDIDO", f"='Consolidado por SKU'!M{ct}", FMT_PCT)])
    _kpis(ws, 6, [("PESO NETO (KG)", f"='Detalle por LPN'!Q{rt}", "#,##0"),
                  ("PESO BRUTO (KG)", f"='Detalle por LPN'!R{rt}", "#,##0"),
                  ("VOLUMEN (M³)", f"='Detalle por LPN'!S{rt}", "#,##0.00"),
                  ("PALLETS PEDIDOS", float(tot.get("pedido_pallets")) if tot.get("pedido_pallets") is not None else "—", "#,##0.##")])
    medidas = (f"{float(tot['pallet_largo_m']):g} x {float(tot['pallet_ancho_m']):g} x {float(tot['pallet_alto_m']):g} m".replace(".", ",")
               if tot.get("pallet_alto_m") and tot.get("pallet_largo_m") and tot.get("pallet_ancho_m") else "Sin alto informado")
    _seccion(ws, 9, "H", "1. DATOS GENERALES DEL DESPACHO")
    fila = _datos_generales(ws, 10, [
        ("Despacho:", cab.get("numero")), ("Destino:", destino),
        ("Referencia / pedido:", cab.get("referencia")), ("Contenedor:", contenedor),
        ("Estado:", cab.get("estado")), ("Stock descontado:", "Sí" if cab.get("stock_descontado") else "No"),
        ("Pedido (unidades):", _n(tot.get("pedido_unidades"))), ("Pallets pedidos:", tot.get("pedido_pallets") or "—"),
        ("Displays:", _n(tot.get("displays"))), ("Medidas pallet (L x A x H):", medidas),
        ("Peso neto (kg):", f"{float(tot.get('peso_kg') or 0):,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")),
        ("Peso bruto (kg):", f"{float(tot.get('peso_bruto_kg') or 0):,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
         + f" (tara {float(tot.get('tara_pallet_kg') or 0):g} kg/pallet)"),
        ("Volumen (m³):", f"{float(tot['m3']):.2f}".replace(".", ",") if tot.get("m3") is not None else "Falta el alto de los pallets"),
        ("Creado:", f"{_txt_fecha(cab.get('creado_en'))} por {cab.get('creado_por') or ''}"),
        ("Cerrado:", f"{_txt_fecha(cab.get('cerrado_en'))} por {cab.get('cerrado_por') or ''}" if cab.get("cerrado_en") else "—"),
    ])

    # 2. por pallet
    fila += 1
    _seccion(ws, fila, "H", "2. RESUMEN POR PALLET (LPN)")
    fila += 1
    _cabecera_tabla(ws, fila, ["LPN", "Ubicación origen", "SKU(s)", "Lote(s)", "Cajas", "Unidades", "Peso bruto kg", "m³"])
    fila += 1
    p0 = fila
    for l in sorted(lpns, key=lambda x: str(x.get("escaneado_en") or "")) or [{}]:
        cont = l.get("contenido") or []
        _fila(ws, fila, [l.get("lpn") or "—", l.get("ubicacion") or "", ", ".join(sorted({str(c.get("sku")) for c in cont}))[:40],
                         ", ".join(sorted({str(c.get("lote")) for c in cont}))[:30],
                         f"=SUMIF({rng('E')},A{fila},{rng('L')})", f"=SUMIF({rng('E')},A{fila},{rng('O')})",
                         f"=SUMIF({rng('E')},A{fila},{rng('R')})", f"=SUMIF({rng('E')},A{fila},{rng('S')})"],
             {4: FMT_MILES, 5: FMT_MILES, 6: "#,##0.0", 7: "0.000"})
        fila += 1
    _fila(ws, fila, ["TOTAL", "", "", "", f"=SUM(E{p0}:E{fila - 1})", f"=SUM(F{p0}:F{fila - 1})", f"=SUM(G{p0}:G{fila - 1})",
                     f"=SUM(H{p0}:H{fila - 1})"], {4: FMT_MILES, 5: FMT_MILES, 6: "#,##0.0", 7: "0.00"}, total=True)

    # 3. por vencimiento
    fila += 2
    _seccion(ws, fila, "H", "3. RESUMEN POR FECHA DE VENCIMIENTO")
    fila += 1
    _cabecera_tabla(ws, fila, ["Fecha Vencimiento", "SKUs", "Lotes Incluidos", "Pallets", "Líneas", "Cajas", "Unidades",
                               "% Unidades"])
    fila += 1
    v0 = fila
    filas_v = {}
    for l in lpns:
        for c in l.get("contenido") or []:
            v = _fecha(c.get("vencimiento"))
            d = filas_v.setdefault(v, {"skus": set(), "lotes": set(), "lpns": set()})
            d["skus"].add(str(c.get("sku")))
            d["lotes"].add(str(c.get("lote")))
            d["lpns"].add(l.get("lpn"))
    vencs = sorted(filas_v, key=lambda x: (not isinstance(x, date), str(x)))
    for v in vencs or [None]:
        d = filas_v.get(v, {"skus": set(), "lotes": set(), "lpns": set()})
        _fila(ws, fila, [v if v else "—", ", ".join(sorted(d["skus"]))[:40], ", ".join(sorted(d["lotes"]))[:60], len(d["lpns"]),
                         f"=COUNTIF({rng('J')},A{fila})", f"=SUMIF({rng('J')},A{fila},{rng('L')})",
                         f"=SUMIF({rng('J')},A{fila},{rng('O')})",
                         f"=IF($G${v0 + max(len(vencs), 1)}>0,G{fila}/$G${v0 + max(len(vencs), 1)},0)"],
             {0: FMT_FECHA, 3: FMT_MILES, 4: FMT_MILES, 5: FMT_MILES, 6: FMT_MILES, 7: FMT_PCT})
        fila += 1
    _fila(ws, fila, ["TOTAL", "", "", f"=SUM(D{v0}:D{fila - 1})", f"=SUM(E{v0}:E{fila - 1})", f"=SUM(F{v0}:F{fila - 1})",
                     f"=SUM(G{v0}:G{fila - 1})", f"=SUM(H{v0}:H{fila - 1})"],
         {3: FMT_MILES, 4: FMT_MILES, 5: FMT_MILES, 6: FMT_MILES, 7: FMT_PCT}, total=True)

    fila += 2
    _seccion(ws, fila, "H", "4. UNIDADES DESPACHADAS POR SKU CONTRA EL PEDIDO")
    _grafico_sku(ws, f"A{fila + 1}", wc, 1, 10, c0, cfin, "Despachado vs pedido por SKU", col_val2=11)
    _anchos(ws, [18, 26, 30, 30, 10, 13, 16, 13])
    wb.save(ruta)
    return ruta
