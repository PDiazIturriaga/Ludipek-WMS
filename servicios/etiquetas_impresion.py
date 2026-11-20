"""Generadores de etiquetas y reportes del Centro de Impresión.

Reemplaza las aplicaciones aparte:
  · app_lpn.py       -> generar_pdf_lpn()       (etiqueta 100 x 200 mm, QR + código grande)
  · app_cencosud.py  -> procesar_oc_cencosud(), generar_pdf_etiquetas_cencosud(),
                        generar_excel_tabla()  (etiquetas 15 x 10 cm por empaque, packing list,
                        imprimible para el conductor)
Los correlativos ya no se guardan en archivos locales: los entrega Supabase (script 27).
"""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd

# IMPORTACIONES FORZADAS PARA PYINSTALLER (reportlab carga los códigos de barra de forma dinámica)
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.graphics.barcode import code128
import reportlab.graphics.barcode.code93  # noqa: F401
import reportlab.graphics.barcode.code39  # noqa: F401
import reportlab.graphics.barcode.usps  # noqa: F401
import reportlab.graphics.barcode.usps4s  # noqa: F401
import reportlab.graphics.barcode.ecc200datamatrix  # noqa: F401
import reportlab.graphics.barcode.qr  # noqa: F401

PREFIJO_LPN = "LPN-"

# Datos fijos de la etiqueta Cencosud (iguales a la aplicación anterior)
CENCOSUD_RAZON_SOCIAL = "IMPORTADORA SOUTHERNKING LTDA"
CENCOSUD_RUT = "76661486-8"
CENCOSUD_SECCION = "38"


# =====================================================================
# ETIQUETAS LPN (100 x 200 mm vertical)
# =====================================================================
def generar_pdf_lpn(desde: int, hasta: int, bodega: str, ruta_salida: str) -> int:
    """Una página por LPN desde..hasta. Mismo diseño de app_lpn.py (100 x 200 mm), con la bodega
    en el encabezado. Usa reportlab (QR incluido) para no depender de otras librerías."""
    from reportlab.lib.units import mm
    from reportlab.graphics.barcode import qr
    from reportlab.graphics.shapes import Drawing
    from reportlab.graphics import renderPDF

    alto_pag = 200 * mm
    c = canvas.Canvas(ruta_salida, pagesize=(100 * mm, alto_pag))
    fecha = datetime.now().strftime("%d/%m/%Y")
    nombre_bodega = "BODEGA CONCEPCION" if "CONCEP" in str(bodega).upper() else "BODEGA SANTIAGO"

    def y(top_mm: float) -> float:          # coordenada "desde arriba" como en la app anterior
        return alto_pag - top_mm * mm

    n = 0
    for numero in range(int(desde), int(hasta) + 1):
        codigo = f"{PREFIJO_LPN}{numero}"
        # Encabezado corporativo (rect 5,5 90x15)
        c.setFillColorRGB(30 / 255, 30 / 255, 30 / 255)
        c.rect(5 * mm, y(20), 90 * mm, 15 * mm, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("Helvetica-Bold", 11)
        c.drawCentredString(50 * mm, y(12), "LUDIPEK - CONTROL DE PALLETS")
        c.setFont("Helvetica-Bold", 8)
        c.drawCentredString(50 * mm, y(17.5), nombre_bodega)
        # QR 70 x 70 mm en (15, 35)
        widget = qr.QrCodeWidget(codigo)
        x0, y0, x1, y1 = widget.getBounds()
        ancho = 70 * mm
        d = Drawing(ancho, ancho, transform=[ancho / (x1 - x0), 0, 0, ancho / (y1 - y0), 0, 0])
        d.add(widget)
        renderPDF.draw(d, c, 15 * mm, y(105))
        # Código visible
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 40 if len(codigo) <= 10 else 34)
        c.drawCentredString(50 * mm, y(132), codigo)
        # Línea separadora y fecha
        c.setStrokeColorRGB(180 / 255, 180 / 255, 180 / 255)
        c.line(20 * mm, y(160), 80 * mm, y(160))
        c.setFont("Helvetica-Oblique", 11)
        c.drawCentredString(50 * mm, y(177), f"Impreso: {fecha}")
        c.showPage()
        n += 1
    c.save()
    return n


# =====================================================================
# CENCOSUD B2B
# =====================================================================
def leer_oc_cencosud(ruta_archivo: str) -> pd.DataFrame:
    """Lee la OC descargada del B2B (.xls real, .xlsx o el .xls que en verdad es HTML)."""
    errores = []
    for kwargs in ({}, {"engine": "xlrd"}, {"engine": "calamine"}, {"engine": "openpyxl"}):
        try:
            return pd.read_excel(ruta_archivo, **kwargs)
        except Exception as ex:
            errores.append(str(ex))
    try:
        return pd.read_html(ruta_archivo, encoding="utf-8")[0]
    except Exception as ex:
        errores.append(str(ex))
    raise RuntimeError("No se pudo leer el archivo de la OC. Si es .xls, instale 'xlrd' (pip install xlrd). "
                       f"Detalle: {errores[0] if errores else ''}")


def _texto_codigo(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def procesar_oc_cencosud(df: pd.DataFrame, hu_inicial: int) -> dict:
    """Misma lógica de app_cencosud.py:
    · un HU por local de destino (ordenado por código de local),
    · una etiqueta por empaque, numeradas "bulto n de total" dentro de cada local,
    · packing list (Cantidad = empaques pedidos) e imprimible para el conductor.
    """
    if "Número de Orden" not in df.columns:
        raise RuntimeError("El archivo no parece una OC del B2B Cencosud (falta la columna 'Número de Orden').")
    df = df.dropna(subset=["Número de Orden"]).copy()
    if "Cód. Local Destino" in df.columns:
        df["Cód. Local Destino"] = df["Cód. Local Destino"].astype(str).str.strip()
        df = df.sort_values(by=["Cód. Local Destino"], kind="stable")

    totales_por_local = {}
    for _, row in df.iterrows():
        local_cod = str(row.get("Cód. Local Destino", "N/A")).strip()
        emp = pd.to_numeric(row.get("Empaques Pedidos", 0), errors="coerce")
        if not pd.isna(emp) and emp > 0:
            totales_por_local[local_cod] = totales_por_local.get(local_cod, 0) + int(emp)

    etiquetas, packing, imprimible = [], [], []
    hu_por_local, bulto_por_local = {}, {}
    hu_actual = int(hu_inicial)
    fecha_proceso = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    for _, row in df.iterrows():
        oc = _texto_codigo(row.get("Número de Orden", ""))
        local_cod = str(row.get("Cód. Local Destino", "N/A")).strip()
        local_nombre = str(row.get("Local Destino", "") or "").strip()
        desc = str(row.get("Descripción", "Sin Descripción") or "")
        ean = _texto_codigo(row.get("EAN13", row.get("Cód. Proveedor", "S/I")))
        cod_cen = _texto_codigo(row.get("Cód. Cencosud", ""))
        cod_prov = _texto_codigo(row.get("Cód. Proveedor", ""))

        fecha_val = row.get("Fecha Entrega", datetime.now())
        try:
            fecha_str = pd.to_datetime(str(fecha_val)[:10].strip(), dayfirst=True).strftime("%d/%m/%Y")
        except Exception:
            fecha_str = str(fecha_val)[:10].replace("-", "/")

        empaques = pd.to_numeric(row.get("Empaques Pedidos", 0), errors="coerce")
        unds = pd.to_numeric(row.get("Unidades por Empaque", 1), errors="coerce")
        if pd.isna(empaques) or empaques <= 0:
            continue
        if pd.isna(unds):
            unds = 1
        empaques, unds = int(empaques), int(unds)

        if local_cod not in hu_por_local:
            hu_por_local[local_cod] = str(hu_actual)
            hu_actual += 1
        hu = hu_por_local[local_cod]

        inicio = bulto_por_local.get(local_cod, 1)
        total_local = totales_por_local[local_cod]
        for i in range(empaques):
            etiquetas.append({"OC": oc, "HU": hu, "Local": local_cod, "Codigo": ean, "Descripcion": desc,
                              "Fecha_Entrega": fecha_str, "Bulto_Actual": inicio + i, "Bulto_Total": total_local})
        bulto_por_local[local_cod] = inicio + empaques

        packing.append({"Numero de OC": oc, "HU": hu, "Local de Destino": local_cod, "Cod. Producto": ean,
                        "Descripcion": desc, "Cantidad": empaques,
                        # para el formato oficial del B2B
                        "_cod_cencosud": cod_cen})
        imprimible.append({"Fecha Proceso": fecha_proceso, "Número de Orden": oc, "Fecha Entrega": fecha_str,
                           "HU": hu, "Cód. Local": local_cod, "Nombre Local": local_nombre, "Cód. Cencosud": cod_cen,
                           "Cód. Proveedor": cod_prov, "EAN13": ean, "Descripción": desc,
                           "Empaques Pedidos": empaques, "Unidades por Empaque": unds,
                           "Cantidad Total": empaques * unds})

    return {"etiquetas": etiquetas, "packing": packing, "imprimible": imprimible,
            "hu_usados": len(hu_por_local), "hu_desde": int(hu_inicial), "hu_hasta": hu_actual - 1,
            "oc": imprimible[0]["Número de Orden"] if imprimible else ""}


def generar_pdf_etiquetas_cencosud(etiquetas: list, ruta_salida: str) -> int:
    """Etiqueta de bulto 15 x 10 cm (idéntica a la aplicación anterior)."""
    ancho, alto = 15 * cm, 10 * cm
    c = canvas.Canvas(ruta_salida, pagesize=(ancho, alto))
    x_left, x_col1, x_fec_lbl, x_fec_val, x_right, x_mid = 0.5 * cm, 3.5 * cm, 7.0 * cm, 10.5 * cm, 14.5 * cm, 9.0 * cm
    y0, y1, y2, y3, y4, y5, y6 = 9.5 * cm, 8.5 * cm, 6.5 * cm, 5.5 * cm, 4.5 * cm, 1.2 * cm, 0.5 * cm

    for b in etiquetas:
        c.rect(x_left, y6, x_right - x_left, y0 - y6)
        c.line(x_left, y1, x_right, y1); c.line(x_left, y2, x_right, y2)
        c.line(x_left, y3, x_right, y3); c.line(x_left, y4, x_right, y4); c.line(x_left, y5, x_right, y5)
        c.line(x_col1, y1, x_col1, y6); c.line(x_fec_val, y1, x_fec_val, y2)
        c.line(x_fec_val, y1 - 1 * cm, x_right, y1 - 1 * cm)
        c.line(x_fec_lbl, y3, x_fec_lbl, y4); c.line(x_fec_val, y3, x_fec_val, y4)
        c.line(x_mid, y5, x_mid, y6)

        c.setFont("Helvetica", 14)
        c.drawCentredString((x_left + x_right) / 2, y1 + 0.35 * cm, "ETIQUETA DE BULTO")
        c.setFont("Helvetica", 11)
        c.drawCentredString((x_left + x_col1) / 2, y2 + 1.2 * cm, "LOCAL")
        c.drawCentredString((x_left + x_col1) / 2, y2 + 0.6 * cm, "DESTINO")

        c.setFillColorRGB(1, 1, 0)
        c.rect(x_col1, y2, x_fec_val - x_col1, y1 - y2, fill=1)
        c.setFillColorRGB(0, 0, 0)
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString((x_col1 + x_fec_val) / 2, y2 + 0.8 * cm, str(b["Local"]))

        c.setFont("Helvetica", 10)
        c.drawCentredString((x_fec_val + x_right) / 2, y1 - 0.7 * cm, "N° DE SECCION")
        c.drawCentredString((x_fec_val + x_right) / 2, y2 + 0.3 * cm, CENCOSUD_SECCION)

        c.drawCentredString((x_left + x_col1) / 2, y3 + 0.6 * cm, "Razón social")
        c.drawCentredString((x_left + x_col1) / 2, y3 + 0.2 * cm, "Proveedor")
        c.setFont("Helvetica", 12)
        c.drawCentredString((x_col1 + x_right) / 2, y3 + 0.35 * cm, CENCOSUD_RAZON_SOCIAL)

        c.setFont("Helvetica", 10)
        c.drawCentredString((x_left + x_col1) / 2, y4 + 0.35 * cm, "RUT")
        c.drawCentredString((x_col1 + x_fec_lbl) / 2, y4 + 0.35 * cm, CENCOSUD_RUT)
        c.drawCentredString((x_fec_lbl + x_fec_val) / 2, y4 + 0.6 * cm, "FECHA")
        c.drawCentredString((x_fec_lbl + x_fec_val) / 2, y4 + 0.2 * cm, "ENTREGA")
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString((x_fec_val + x_right) / 2, y4 + 0.35 * cm, str(b["Fecha_Entrega"]))

        c.setFont("Helvetica", 11)
        c.drawCentredString((x_left + x_col1) / 2, y5 + 1.65 * cm, "N° DE HU")
        hu_str = str(b["HU"])
        c.setFont("Helvetica-Bold", 14)
        c.drawCentredString((x_col1 + x_right) / 2, y5 + 0.3 * cm, hu_str)
        barcode = code128.Code128(hu_str, barHeight=2.2 * cm, barWidth=1.1)
        barcode.drawOn(c, x_col1 + ((x_right - x_col1) - barcode.width) / 2, y5 + 0.9 * cm)

        c.setFont("Helvetica", 10)
        c.drawCentredString((x_left + x_col1) / 2, y6 + 0.2 * cm, "BULTOS")
        c.setFont("Helvetica-Bold", 12)
        c.drawCentredString((x_col1 + x_mid) / 2, y6 + 0.15 * cm, str(b["Bulto_Actual"]))
        c.drawCentredString((x_mid + x_right) / 2, y6 + 0.15 * cm, str(b["Bulto_Total"]))
        c.showPage()
    c.save()
    return len(etiquetas)


def generar_excel_tabla(hojas: list, ruta_salida: str) -> None:
    """hojas = [(nombre_hoja, DataFrame), ...]. Tabla con estilo, códigos como texto y anchos como antes."""
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    wb = Workbook()
    wb.remove(wb.active)
    for i_hoja, (nombre, df) in enumerate(hojas):
        ws = wb.create_sheet(title=nombre[:31])
        cols = list(df.columns)
        ws.append(cols)
        for fila in df.itertuples(index=False):
            ws.append(["" if (isinstance(v, float) and pd.isna(v)) else v for v in fila])
        for j, col in enumerate(cols, start=1):
            letra = get_column_letter(j)
            es_codigo = col == "HU" or "Cód" in col or "Cod" in col or "EAN" in col or "OC" in col or "Orden" in col
            if col == "HU":
                ancho = 22
            elif "Descrip" in col:
                ancho = 45
            elif "Local" in col:
                ancho = 22
            elif es_codigo:
                ancho = 16
            else:
                ancho = 14
            ws.column_dimensions[letra].width = ancho
            if es_codigo:
                for celda in ws[letra][1:]:
                    celda.value = "" if celda.value is None else str(celda.value)
                    celda.number_format = "@"
        if len(df) > 0 and cols:
            ref = f"A1:{get_column_letter(len(cols))}{len(df) + 1}"
            tabla = Table(displayName=f"Tabla{i_hoja + 1}", ref=ref)
            tabla.tableStyleInfo = TableStyleInfo(name="TableStyleMedium9", showRowStripes=True)
            ws.add_table(tabla)
    wb.save(ruta_salida)


def reportes_cencosud(resultado: dict, numero_factura: str = "") -> dict:
    """DataFrames de los reportes: packing list (como antes), formato B2B oficial e imprimible conductor."""
    df_pack = pd.DataFrame(resultado["packing"])
    df_b2b = pd.DataFrame([{
        "Numero de OC": p["Numero de OC"], "Numero de Factura": numero_factura or "", "HU": p["HU"],
        "Local de Destino": p["Local de Destino"], "Cod. Producto": p["_cod_cencosud"], "Cantidad": p["Cantidad"],
        "Numero de Lote": "", "Fecha de Vencimiento": "", "Costo": "",
    } for p in resultado["packing"]])
    if "_cod_cencosud" in df_pack.columns:
        df_pack = df_pack.drop(columns=["_cod_cencosud"])
    df_imp = pd.DataFrame(resultado["imprimible"])
    df_conductor = df_imp.drop(columns=[c for c in ("Fecha Proceso", "EAN13", "Cantidad Total", "Unidades por Empaque")
                                        if c in df_imp.columns])
    return {"packing": df_pack, "b2b": df_b2b, "conductor": df_conductor, "historico": df_imp}


def etiquetas_desde_historico(filas: list, hu: str, seleccion: str | None = None) -> tuple[list, list]:
    """Reimpresión: arma las etiquetas de un HU guardado (todas o una). Devuelve (opciones, etiquetas)."""
    total = sum(int(f.get("empaques_pedidos") or 1) for f in filas)
    opciones, etiquetas = [], []
    inicio = 1
    for f in filas:
        ean = str(f.get("ean13") or f.get("cod_proveedor") or "S/I")
        emp = int(f.get("empaques_pedidos") or 1)
        for i in range(emp):
            actual = inicio + i
            texto = f"SKU: {ean} - Bulto {actual} de {total}"
            opciones.append(texto)
            if seleccion in (None, "TODOS") or seleccion == texto:
                etiquetas.append({"OC": str(f.get("numero_orden") or ""), "HU": hu, "Local": str(f.get("cod_local") or ""),
                                  "Codigo": ean, "Descripcion": str(f.get("descripcion") or ""),
                                  "Fecha_Entrega": str(f.get("fecha_entrega") or ""), "Bulto_Actual": actual,
                                  "Bulto_Total": total})
        inicio += emp
    return opciones, etiquetas


def resultado_desde_historico(filas: list) -> dict:
    """Reconstruye etiquetas y reportes de una OC ya procesada (para descargarla de nuevo)."""
    por_hu = {}
    for f in filas:
        por_hu.setdefault(str(f.get("hu")), []).append(f)
    etiquetas, packing, imprimible = [], [], []
    for hu in sorted(por_hu, key=lambda h: int(h) if str(h).isdigit() else 0):
        grupo = sorted(por_hu[hu], key=lambda f: int(f.get("id") or 0))
        etiquetas.extend(etiquetas_desde_historico(grupo, hu)[1])
        for f in grupo:
            packing.append({"Numero de OC": str(f.get("numero_orden") or ""), "HU": hu,
                            "Local de Destino": str(f.get("cod_local") or ""), "Cod. Producto": str(f.get("ean13") or ""),
                            "Descripcion": str(f.get("descripcion") or ""), "Cantidad": int(f.get("empaques_pedidos") or 0),
                            "_cod_cencosud": str(f.get("cod_cencosud") or "")})
            imprimible.append({"Fecha Proceso": str(f.get("fecha_proceso") or "")[:19], "Número de Orden": str(f.get("numero_orden") or ""),
                               "Fecha Entrega": str(f.get("fecha_entrega") or ""), "HU": hu,
                               "Cód. Local": str(f.get("cod_local") or ""), "Nombre Local": str(f.get("nombre_local") or ""),
                               "Cód. Cencosud": str(f.get("cod_cencosud") or ""), "Cód. Proveedor": str(f.get("cod_proveedor") or ""),
                               "EAN13": str(f.get("ean13") or ""), "Descripción": str(f.get("descripcion") or ""),
                               "Empaques Pedidos": int(f.get("empaques_pedidos") or 0),
                               "Unidades por Empaque": int(f.get("unidades_empaque") or 1),
                               "Cantidad Total": int(f.get("cantidad_total") or 0)})
    hus = [int(h) for h in por_hu if str(h).isdigit()]
    return {"etiquetas": etiquetas, "packing": packing, "imprimible": imprimible, "hu_usados": len(por_hu),
            "hu_desde": min(hus) if hus else 0, "hu_hasta": max(hus) if hus else 0,
            "oc": imprimible[0]["Número de Orden"] if imprimible else ""}
