import flet as ft
from supabase import create_client, Client
from datetime import datetime
import asyncio
import os
import sys
import json
import inspect
import qrcode
from fpdf import FPDF
import pandas as pd
import sys
import plotly.graph_objects as go
import os
import hashlib
import hmac
import shutil
import urllib.parse

# Importaciones para el generador de etiquetas B2B (Cencosud)
from reportlab.pdfgen import canvas
from reportlab.lib.units import cm
from reportlab.graphics.barcode import code128

# Importaciones forzadas para compilar correctamente la app como .exe con PyInstaller
import reportlab.graphics.barcode.code93
import reportlab.graphics.barcode.code39
import reportlab.graphics.barcode.usps
import reportlab.graphics.barcode.usps4s
import reportlab.graphics.barcode.ecc200datamatrix

def obtener_ruta_recurso(relativo: str) -> str:
    """Obtiene la ruta absoluta del recurso, compatible con desarrollo y con PyInstaller (.exe)."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relativo)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# =====================================================================
# 1. CONEXIÓN ERP NETSUITE (LOCAL Y RENDER CLOUD)
# =====================================================================
RUTAS_ERP = [
    os.path.abspath("."),
    r"C:\WMS_Clean",
    r"C:\Scripts\Supabase",
]
for ruta in RUTAS_ERP:
    if os.path.exists(ruta) and ruta not in sys.path:
        sys.path.append(ruta)

NETSUITE_CONECTADO = False
ERROR_DETALLE_ERP = ""

try:
    from conexion_erp import consultar_netsuite
    NETSUITE_CONECTADO = True
    print("[INFO] Modulo 'conexion_erp' cargado correctamente.")
except Exception as err_erp:
    NETSUITE_CONECTADO = False
    ERROR_DETALLE_ERP = str(err_erp)
    print(f"[WARN] Detalle al importar 'conexion_erp': {ERROR_DETALLE_ERP}")

# =====================================================================
# 2. IA GOOGLE GEMINI Y SUPABASE (100% VARIABLES DE ENTORNO)
# =====================================================================
try:
    from google import genai
    from google.genai import types
    GEMINI_DISPONIBLE = True
except ImportError:
    GEMINI_DISPONIBLE = False

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_KEY en las variables de entorno (.env o Render).")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
ai_client = genai.Client(api_key=GEMINI_API_KEY) if (GEMINI_DISPONIBLE and GEMINI_API_KEY) else None


# =====================================================================
# 3. ADAPTADORES INTELIGENTES DE ESQUEMA
# =====================================================================
def obtener_val(diccionario: dict, posibles_claves: list, por_defecto=""):
    if not isinstance(diccionario, dict):
        return por_defecto
    for k in posibles_claves:
        if k in diccionario and diccionario[k] is not None:
            return diccionario[k]
    return por_defecto


def formatear_nombre_po(codigo_raw: str) -> str:
    txt = str(codigo_raw or "").strip()
    for prefijo in ("ASN-", "PO-", "OC-", "ASN ", "PO ", "OC "):
        if txt.upper().startswith(prefijo):
            txt = txt[len(prefijo):].strip()
    # Reemplazar barras o caracteres prohibidos en nombres de archivo de Windows
    for char_invalido in ("/", "\\", ":", "*", "?", '"', "<", ">", "|"):
        txt = txt.replace(char_invalido, "-")
    return txt or "LIBRE"


def obtener_nombre_po_cabecera(cabecera: dict) -> str:
    """Obtiene el código real de la PO ignorando placeholders como 'S/OC' o 'S/N'."""
    if not isinstance(cabecera, dict):
        return "LIBRE"
    num_oc = str(cabecera.get("numero_oc") or "").strip()
    cod_asn = str(cabecera.get("codigo_asn") or "").strip()

    # Si numero_oc tiene un valor real (distinto de S/OC o S/N), usarlo; si no, usar codigo_asn
    if num_oc and num_oc.upper() not in ("S/OC", "S/N", "NONE", "NULL", "-"):
        return formatear_nombre_po(num_oc)
    if cod_asn and cod_asn.upper() not in ("S/OC", "S/N", "NONE", "NULL", "-"):
        return formatear_nombre_po(cod_asn)
    return "LIBRE"


def extraer_estado_qa(lote_str: str) -> tuple[str, str]:
    raw = str(lote_str or "S/L").strip()
    if "|QA:" in raw:
        partes = raw.split("|QA:")
        return partes[0].strip(), partes[1].strip()
    return raw, "APROBADO"


def formatear_lote_con_qa(lote_limpio: str, estado_qa: str) -> str:
    lote_base = str(lote_limpio or "S/L").split("|QA:")[0].strip().upper()
    est = str(estado_qa or "APROBADO").strip().upper()
    if est == "APROBADO":
        return lote_base
    return f"{lote_base}|QA:{est}"


# =====================================================================
# 4. MOTOR DE REPORTES PDF (INDIVIDUAL Y MASIVO DE LPNs) Y EXCEL
# =====================================================================
def dibujar_pagina_lpn_15x10(pdf: FPDF, lpn: str, lineas_pallet: list):
    """Dibuja una etiqueta 15x10 cm dentro de un objeto FPDF (lectura a distancia y QR compacto sin QA)."""
    import qrcode
    os.makedirs("temp_qrs", exist_ok=True)
    qr_path = f"temp_qrs/{lpn}.png"
    qr_img = qrcode.make(lpn)
    qr_img.save(qr_path)

    pdf.add_page()
    pdf.set_text_color(0, 0, 0)
    pdf.set_draw_color(0, 0, 0)

    # Marco exterior grueso
    pdf.set_line_width(0.6)
    pdf.rect(1.5, 1.5, 147, 97)

    # --- ENCABEZADO: N° LPN GIGANTE ARRIBA + QR PEQUEÑO EN ESQUINA SUPERIOR DERECHA ---
    lpn_str = str(lpn or "S/LPN").strip().upper()
    tam_fuente_lpn = 48 if len(lpn_str) <= 12 else (40 if len(lpn_str) <= 15 else 32)
    pdf.set_font("Helvetica", "B", tam_fuente_lpn)
    pdf.set_xy(3, 4)
    pdf.cell(120, 18, txt=lpn_str, align="L")

    # Fecha de recepción compacta
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_xy(4, 21)
    pdf.cell(116, 5, txt=f"FECHA RECP: {datetime.now().strftime('%d-%m-%Y %H:%M')}", align="L")

    # QR pequeño en la esquina superior derecha (22x22 mm)
    pdf.image(qr_path, x=124, y=4, w=22)

    # Línea divisoria superior
    pdf.set_line_width(0.5)
    pdf.line(2, 28, 148, 28)

    if len(lineas_pallet) == 1:
        # CASO 1: SKU ÚNICO Y LOTE ÚNICO (TODO GIGANTE)
        item = lineas_pallet[0]
        sku_str = str(item.get("sku", "")).strip().upper()
        cajas_val = item.get("cajas", 0)
        mult_val = item.get("multiplo_aplicado", 1)
        sueltas_val = item.get("unidades_sueltas", 0)
        unid_totales = item.get("unidades_totales", 0)
        lote_val, _ = extraer_estado_qa(item.get("lote", "S/L"))

        # 1. SKU GIGANTE
        tam_sku = 42 if len(sku_str) <= 12 else 32
        pdf.set_font("Helvetica", "B", tam_sku)
        pdf.set_xy(3, 31)
        pdf.cell(144, 16, txt=f"SKU: {sku_str}", align="C")

        # 2. BLOQUES EXTRA GRANDES: CAJAS Y UNIDADES
        pdf.set_line_width(0.4)
        # Cajas
        pdf.rect(4, 49, 69, 24)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_xy(4, 50)
        pdf.cell(69, 5, txt="CAJAS", align="C")
        pdf.set_font("Helvetica", "B", 42)
        pdf.set_xy(4, 56)
        pdf.cell(69, 15, txt=f"{cajas_val}", align="C")

        # Unidades
        pdf.rect(77, 49, 69, 24)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_xy(77, 50)
        pdf.cell(69, 5, txt=f"TOTAL UNID (x{mult_val})", align="C")
        pdf.set_font("Helvetica", "B", 42)
        pdf.set_xy(77, 56)
        pdf.cell(69, 15, txt=f"{unid_totales}", align="C")

        # 3. LOTE GIGANTE
        tam_lote = 38 if len(str(lote_val)) <= 12 else 28
        pdf.set_font("Helvetica", "B", tam_lote)
        pdf.set_xy(4, 76)
        pdf.cell(142, 19, txt=f"LOTE: {lote_val}", border=1, align="C")

    else:
        # CASO 2: PALLET MIXTO (MULTI-LOTE O MULTI-SKU)
        skus_distintos = list(set([str(x.get("sku", "")).upper() for x in lineas_pallet]))
        total_cj = sum(int(x.get("cajas") or 0) for x in lineas_pallet)
        total_un = sum(int(x.get("unidades_totales") or 0) for x in lineas_pallet)

        if len(skus_distintos) == 1:
            # ES UN SOLO SKU, PERO MULTI-LOTE
            sku_unico = skus_distintos[0]
            pdf.set_font("Helvetica", "B", 38)
            pdf.set_xy(3, 30)
            pdf.cell(144, 14, txt=f"SKU: {sku_unico}", align="C")
            
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_xy(3, 45)
            pdf.cell(144, 6, txt=f"PALLET MULTI-LOTE | TOTAL: {total_cj} CJ / {total_un} UN", align="C")

            pdf.set_font("Helvetica", "B", 15)
            pdf.set_xy(4, 53)
            pdf.cell(52, 11, "LOTE", border=1, align="C")
            pdf.cell(32, 11, "VENC.", border=1, align="C")
            pdf.cell(26, 11, "CAJAS", border=1, align="C")
            pdf.cell(32, 11, "UNIDADES", border=1, align="C")

            y_offset = 64
            pdf.set_font("Helvetica", "B", 15)
            for item in lineas_pallet[:3]: # Máximo 3 lotes para fuente grande (H=11)
                lote_clean, _ = extraer_estado_qa(item.get("lote", "S/L"))
                venc = str(item.get("fecha_vencimiento_cl") or "S/F")
                pdf.set_xy(4, y_offset)
                pdf.cell(52, 11, lote_clean[:14], border=1, align="C")
                pdf.cell(32, 11, venc[:10], border=1, align="C")
                pdf.cell(26, 11, str(item.get("cajas", 0)), border=1, align="C")
                pdf.cell(32, 11, str(item.get("unidades_totales", 0)), border=1, align="C")
                y_offset += 11
        else:
            # SON DISTINTOS SKUs (PALLET MIXTO MULTI-SKU)
            pdf.set_font("Helvetica", "B", 20)
            pdf.set_xy(4, 30)
            pdf.cell(142, 8, txt=f"PALLET MIXTO MULTI-SKU", align="C")
            
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_xy(4, 38)
            pdf.cell(142, 6, txt=f"TOTALES PALLET: {total_cj} CAJAS / {total_un} UNIDADES", align="C")

            pdf.set_font("Helvetica", "B", 13)
            pdf.set_xy(4, 47)
            pdf.cell(46, 10, "SKU", border=1, align="C")
            pdf.cell(38, 10, "LOTE", border=1, align="C")
            pdf.cell(16, 10, "CJ", border=1, align="C")
            pdf.cell(18, 10, "UNID", border=1, align="C")
            pdf.cell(24, 10, "VENC.", border=1, align="C")

            y_offset = 57
            pdf.set_font("Helvetica", "B", 13)
            for item in lineas_pallet[:4]:
                lote_clean, _ = extraer_estado_qa(item.get("lote", "S/L"))
                venc = str(item.get("fecha_vencimiento_cl") or "S/F")
                pdf.set_xy(4, y_offset)
                pdf.cell(46, 10, str(item.get("sku", ""))[:16], border=1, align="L")
                pdf.cell(38, 10, lote_clean[:14], border=1, align="C")
                pdf.cell(16, 10, str(item.get("cajas", 0)), border=1, align="C")
                pdf.cell(18, 10, str(item.get("unidades_totales", 0)), border=1, align="C")
                pdf.cell(24, 10, venc[:10], border=1, align="C")
                y_offset += 10
def generar_pdf_recepcion_15x10(lpn: str, lineas_pallet: list):
    os.makedirs("reportes_recepcion", exist_ok=True)
    pdf = FPDF(orientation="L", unit="mm", format=(100, 150))
    pdf.set_auto_page_break(auto=False, margin=0)
    dibujar_pagina_lpn_15x10(pdf, lpn, lineas_pallet)

    nombre_archivo = os.path.join("reportes_recepcion", f"Etiqueta_{lpn}.pdf")
    pdf.output(nombre_archivo)
    if os.name == "nt":
        try:
            os.startfile(nombre_archivo)
        except Exception:
            pass
    return nombre_archivo


def generar_pdf_masivo_lpns_po(codigo_po: str, registros_recepcion: list) -> str:
    """Genera un único PDF multipágina con TODOS los LPNs de la PO listos para imprimir."""
    os.makedirs("reportes_recepcion", exist_ok=True)
    pdf = FPDF(orientation="L", unit="mm", format=(100, 150))
    pdf.set_auto_page_break(auto=False, margin=0)

    agrupado_lpn = {}
    for r in registros_recepcion:
        cod = str(r.get("lpn", "")).strip()
        if cod:
            agrupado_lpn.setdefault(cod, []).append(r)

    for cod_lpn in sorted(agrupado_lpn.keys()):
        dibujar_pagina_lpn_15x10(pdf, cod_lpn, agrupado_lpn[cod_lpn])

    po_limpia = formatear_nombre_po(codigo_po).replace("/", "-")
    nombre_archivo = os.path.join(
        "reportes_recepcion",
        f"Etiquetas_Masivas_{po_limpia}_{datetime.now().strftime('%H%M%S')}.pdf",
    )
    pdf.output(nombre_archivo)
    if os.name == "nt":
        try:
            os.startfile(nombre_archivo)
        except Exception:
            pass
    return nombre_archivo

def obtener_fecha_cierre_o_recepcion(cabecera_po: dict, recepciones_lpn: list) -> str:
    """Obtiene la fecha fija de cierre de la PO o la del último LPN recepcionado."""
    if isinstance(cabecera_po, dict):
        for col_f in ("fecha_cierre", "closed_at", "updated_at"):
            val_f = cabecera_po.get(col_f)
            if val_f and str(val_f).strip() not in ("None", ""):
                txt_f = str(val_f).strip()
                try:
                    dt_iso = datetime.fromisoformat(txt_f.replace("Z", "+00:00")).astimezone()
                    return dt_iso.strftime("%d-%m-%Y %H:%M:%S")
                except Exception:
                    return txt_f[:19]

    if recepciones_lpn:
        ultimo_lpn = recepciones_lpn[0]
        for col_r in ("created_at", "fecha_recepcion", "fecha_hora", "fecha_ingreso", "timestamp"):
            val_r = ultimo_lpn.get(col_r)
            if val_r and str(val_r).strip() not in ("None", ""):
                txt_r = str(val_r).strip()
                try:
                    dt_lpn = datetime.fromisoformat(txt_r.replace("Z", "+00:00")).astimezone()
                    return dt_lpn.strftime("%d-%m-%Y %H:%M:%S")
                except Exception:
                    return txt_r[:19]

    return datetime.now().strftime("%d-%m-%Y %H:%M:%S")


def generar_acta_recepcion_pdf(cabecera_po: dict, filas_conciliacion: list, recepciones_lpn: list) -> str:
    import os
    from fpdf import FPDF
    from datetime import datetime

    os.makedirs("reportes_recepcion", exist_ok=True)
    
    # Extraemos metadatos, incluyendo el nuevo CONTENEDOR
    codigo_po = str(cabecera_po.get("codigo_asn", "S/PO"))
    proveedor = str(cabecera_po.get("proveedor", "RECEPCION DIRECTA"))
    oc_raw = str(cabecera_po.get("numero_oc") or "").strip()
    oc_num = codigo_po if oc_raw.upper() in ("", "S/OC", "S/N", "NONE") else oc_raw
    estado_po = str(cabecera_po.get("estado", "EN_RECEPCION"))
    contenedor_guia = str(cabecera_po.get("contenedor_referencia") or "N/A")

    # Fechas
    try:
        from dependencias import obtener_fecha_cierre_o_recepcion
        fecha_cierre_str = obtener_fecha_cierre_o_recepcion(cabecera_po, recepciones_lpn)
    except:
        fecha_cierre_str = datetime.now().strftime("%d-%m-%Y %H:%M")

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # --- ENCABEZADO CON LOGO.PNG Y COLOR CORPORATIVO ---
    pdf.set_fill_color(15, 23, 42)
    pdf.rect(0, 0, 210, 26, style="F")

    try:
        from dependencias import obtener_ruta_recurso
        posibles_logos = [obtener_ruta_recurso("logo.png"), obtener_ruta_recurso(os.path.join("assets", "logo.png")), "logo.png", os.path.join("assets", "logo.png")]
    except:
        posibles_logos = ["logo.png", os.path.join("assets", "logo.png")]
        
    ruta_logo = next((p for p in posibles_logos if os.path.exists(p)), None)

    x_texto_header = 10
    if ruta_logo:
        try:
            pdf.image(ruta_logo, x=10, y=3, h=20)
            x_texto_header = 38
        except Exception as err_img:
            pass

    fecha_llegada = "EN PROCESO / NO REGISTRADA"
    if recepciones_lpn:
        primer_lpn = sorted(recepciones_lpn, key=lambda x: x.get("id", 0))[0]
        val_r = primer_lpn.get("created_at") or primer_lpn.get("fecha_recepcion") or primer_lpn.get("timestamp")
        if val_r and str(val_r).strip() not in ("None", ""):
            try:
                dt_llegada = datetime.fromisoformat(str(val_r).replace("Z", "+00:00"))
                fecha_llegada = dt_llegada.strftime("%d-%m-%Y %H:%M")
            except Exception:
                fecha_llegada = str(val_r)[:16]

    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_xy(x_texto_header, 5)
    pdf.cell(200 - x_texto_header, 6, txt=f"LUDIPEK WMS - ACTA DE RECEPCION DE CARGA (PO: {codigo_po})", align="L")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(x_texto_header, 13)
    pdf.cell(200 - x_texto_header, 5, txt=f"Llegada a Centro de Distribución (Inicio Descarga): {fecha_llegada}", align="L")
    pdf.set_xy(x_texto_header, 18)
    pdf.cell(200 - x_texto_header, 5, txt=f"Proceso y Cierre en Centro de Distribución: {fecha_cierre_str}", align="L")
    pdf.set_text_color(0, 0, 0)

    # --- DATOS DE CABECERA PO ---
    pdf.set_xy(10, 32)
    pdf.set_fill_color(241, 245, 249)
    pdf.rect(10, 32, 190, 22, style="F")
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(14, 35)
    pdf.cell(85, 6, txt=f"PO: {codigo_po}")
    pdf.cell(85, 6, txt=f"ORDEN DE COMPRA ERP: {oc_num}")
    pdf.set_xy(14, 43)
    pdf.cell(85, 6, txt=f"PROVEEDOR: {proveedor[:30]}")
    
    # MOSTRAR CONTENEDOR EN EL ACTA
    str_cont = f" | CONTENEDOR: {contenedor_guia}" if contenedor_guia != "N/A" else ""
    pdf.cell(85, 6, txt=f"ESTADO: {estado_po}{str_cont}")

    # --- 1. TABLA DE CONCILIACION VERTICAL POR SKU Y LOTE ---
    pdf.set_xy(10, 60)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(190, 7, txt="1. TABLA DE CONCILIACION POR LOTE Y SKU (PO / PACKING LIST VS RECEPCION FISICA)", ln=True)

    lotes_agrupados = {}
    skus_con_recepcion = set()
    
    for r in recepciones_lpn:
        s_r = str(r.get("sku", "")).strip().upper()
        if not s_r: continue
        try:
            from dependencias import extraer_estado_qa
            lote_limpio, _ = extraer_estado_qa(r.get("lote", "S/L"))
        except:
            lote_limpio = str(r.get("lote", "S/L")).split(" ")[0]
            
        venc_r = str(r.get("fecha_vencimiento_cl") or "S/F").strip()
        unid_r = int(r.get("unidades_totales", 0) or 0)

        skus_con_recepcion.add(s_r)
        clave = (s_r, lote_limpio)
        if clave not in lotes_agrupados:
            lotes_agrupados[clave] = {"unidades": 0, "vencimiento": venc_r}
        lotes_agrupados[clave]["unidades"] += unid_r
        if lotes_agrupados[clave]["vencimiento"] == "S/F" and venc_r != "S/F":
            lotes_agrupados[clave]["vencimiento"] = venc_r

    filas_verticales_pdf = []
    for (sku_k, lote_k), info_lote in sorted(lotes_agrupados.items(), key=lambda x: (x[0][0], x[0][1])):
        
        # Rescatamos la descripción desde el diccionario original de filas_conciliacion
        desc_rescate = "Ingreso Directo"
        unid_po = 0
        for f in filas_conciliacion:
            if str(f.get("sku", "")).strip().upper() == sku_k:
                desc_rescate = str(f.get("descripcion", ""))
                unid_po = int(f.get("unidades_esperadas", 0) or 0)
                break
                
        filas_verticales_pdf.append({
            "sku": sku_k,
            "descripcion": desc_rescate,
            "lote": lote_k,
            "vencimiento": info_lote["vencimiento"],
            "cantidad_lote": info_lote["unidades"],
            "unidades_po": unid_po,
        })

    for f in filas_conciliacion:
        s_key = str(f.get("sku", "")).strip().upper()
        if s_key and s_key not in skus_con_recepcion:
            filas_verticales_pdf.append({
                "sku": s_key,
                "descripcion": str(f.get("descripcion", "")),
                "lote": "SIN INGRESO",
                "vencimiento": "-",
                "cantidad_lote": 0,
                "unidades_po": int(f.get("unidades_esperadas", 0) or 0),
            })

    pdf.set_fill_color(226, 232, 240)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(28, 7, "SKU", border=1, fill=True)
    pdf.cell(74, 7, "DESCRIPCION", border=1, fill=True)
    pdf.cell(36, 7, "LOTE", border=1, align="C", fill=True)
    pdf.cell(26, 7, "VENCIMIENTO", border=1, align="C", fill=True)
    pdf.cell(26, 7, "CANT. LOTE", border=1, align="C", fill=True, ln=True)

    pdf.set_font("Helvetica", "", 8)
    total_general_unidades = 0
    for fv in filas_verticales_pdf:
        cant_l = fv["cantidad_lote"]
        total_general_unidades += cant_l
        pdf.cell(28, 6, str(fv["sku"])[:15], border=1)
        pdf.cell(74, 6, str(fv["descripcion"])[:40], border=1)
        pdf.cell(36, 6, str(fv["lote"])[:18], border=1, align="C")
        pdf.cell(26, 6, str(fv["vencimiento"])[:12], border=1, align="C")
        pdf.cell(26, 6, str(cant_l), border=1, align="C", ln=True)

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(241, 245, 249)
    pdf.cell(164, 6, "TOTAL UNIDADES FISICAS RECIBIDAS (SUMA POR LOTES)", border=1, align="R", fill=True)
    pdf.cell(26, 6, str(total_general_unidades), border=1, align="C", fill=True, ln=True)

    # --- FIRMAS AL FINAL (OMITIMOS LA TABLA DE LPNs) ---
    pdf.ln(16)
    y_firma = pdf.get_y()
    if y_firma > 250:
        pdf.add_page()
        y_firma = 40
    pdf.line(20, y_firma + 15, 85, y_firma + 15)
    pdf.line(125, y_firma + 15, 190, y_firma + 15)
    pdf.set_xy(20, y_firma + 17)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(65, 5, "RECEPCION BODEGA", align="C")
    pdf.set_xy(125, y_firma + 17)
    pdf.cell(65, 5, "ASEGURAMIENTO DE CALIDAD (QA)", align="C")

    codigo_po_limpio = codigo_po.replace("/", "-").replace(":", "").replace("\\", "").replace(" ", "_")
    proveedor_limpio = "".join(c for c in proveedor if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')[:30]
    
    archivo_salida = os.path.join(
        "reportes_recepcion",
        f"Acta_Recepcion_{codigo_po_limpio}_{proveedor_limpio}_{datetime.now().strftime('%d%m%Y_%H%M')}.pdf",
    )
    pdf.output(archivo_salida)
    
    if os.name == "nt":
        try:
            os.startfile(archivo_salida)
        except Exception:
            pass
    return archivo_salida

def generar_pdf_totem_rack(pasillo: str, columna: str, niveles: int = 5):
    os.makedirs("temp_qrs", exist_ok=True)
    os.makedirs("reportes_recepcion", exist_ok=True)
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False, margin=0)
    pdf.add_page()

    pdf.set_fill_color(15, 23, 42)
    pdf.rect(0, 0, 210, 22, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_xy(0, 6)
    pdf.cell(210, 10, txt=f"TOTEM DE UBICACIONES | PASILLO {pasillo} - COLUMNA {columna}", align="C")
    pdf.set_text_color(0, 0, 0)

    y_pos = 30
    for niv in range(niveles, 0, -1):
        cod_ubi = f"{pasillo.upper().strip()}-{columna.upper().strip()}-N{niv}"
        qr_path = f"temp_qrs/{cod_ubi}.png"
        qrcode.make(cod_ubi).save(qr_path)

        pdf.set_draw_color(180, 180, 180)
        pdf.rect(15, y_pos, 180, 46)
        pdf.image(qr_path, x=22, y=y_pos + 3, w=40)

        pdf.set_font("Helvetica", "B", 26)
        pdf.set_xy(70, y_pos + 8)
        pdf.cell(115, 14, txt=cod_ubi, align="L")

        tipo_nivel = "NIVEL PICKING / REAPRO" if niv == 1 else f"NIVEL RESERVA ALTURA {niv}"
        pdf.set_font("Helvetica", "", 11)
        pdf.set_xy(70, y_pos + 25)
        pdf.cell(115, 10, txt=f"{tipo_nivel} | Escanear QR con Terminal RF", align="L")
        y_pos += 50

    nombre_archivo = os.path.join("reportes_recepcion", f"Totem_{pasillo}_{columna}.pdf")
    pdf.output(nombre_archivo)
    if os.name == "nt":
        try:
            os.startfile(nombre_archivo)
        except Exception:
            pass
    return nombre_archivo


def generar_pdf_etiqueta_ubicacion_individual(codigo_ubicacion: str, zona: str = "RACK"):
    os.makedirs("temp_qrs", exist_ok=True)
    os.makedirs("reportes_recepcion", exist_ok=True)
    cod_limpio = codigo_ubicacion.strip().upper()
    qr_path = f"temp_qrs/UBI_{cod_limpio}.png"
    qrcode.make(cod_limpio).save(qr_path)

    pdf = FPDF(orientation="L", unit="mm", format=(100, 150))
    pdf.set_auto_page_break(auto=False, margin=0)
    pdf.add_page()

    pdf.set_fill_color(15, 23, 42)
    pdf.rect(0, 0, 150, 16, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_xy(0, 4)
    pdf.cell(150, 8, txt=f"LUDIPEK WMS - POSICION DE BODEGA ({zona})", align="C")
    pdf.set_text_color(0, 0, 0)

    pdf.set_font("Helvetica", "B", 36)
    pdf.set_xy(5, 32)
    pdf.cell(92, 20, txt=cod_limpio, align="C")

    pdf.set_font("Helvetica", "", 12)
    pdf.set_xy(5, 60)
    pdf.cell(92, 10, txt="UBICACION OFICIAL CERTIFICADA", align="C")

    pdf.image(qr_path, x=100, y=22, w=44)
    pdf.rect(0.5, 0.5, 149, 99)

    nombre_archivo = os.path.join("reportes_recepcion", f"Ubicacion_{cod_limpio}.pdf")
    pdf.output(nombre_archivo)
    if os.name == "nt":
        try:
            os.startfile(nombre_archivo)
        except Exception:
            pass
    return nombre_archivo


# =====================================================================
# 5. COMPONENTES VISUALES Y GRAFICOS BI NATIVOS
# =====================================================================
def generar_pdf_ubicaciones_vacias(lista_vacias: list):
    os.makedirs("reportes_inventario", exist_ok=True)
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    pdf.set_fill_color(15, 23, 42)
    pdf.rect(0, 0, 210, 22, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_xy(0, 6)
    pdf.cell(210, 10, txt=f"LUDIPEK WMS - REPORTE DE UBICACIONES Y ESPACIOS VACIOS", align="C")
    pdf.set_text_color(0, 0, 0)
    
    pdf.set_font("Helvetica", "", 10)
    pdf.set_xy(10, 26)
    pdf.cell(190, 6, txt=f"Fecha de Generación: {datetime.now().strftime('%d-%m-%Y %H:%M')}", align="R")
    
    pdf.set_xy(10, 35)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(226, 232, 240)
    pdf.cell(40, 8, "ZONA / PASILLO", border=1, fill=True, align="C")
    pdf.cell(60, 8, "CODIGO UBICACION", border=1, fill=True, align="C")
    pdf.cell(90, 8, "OBSERVACION DE INSPECCION", border=1, fill=True, align="C")
    pdf.ln(8)
    
    pdf.set_font("Helvetica", "", 10)
    for ubi in sorted(lista_vacias):
        zona = ubi.split("-")[0] if "-" in ubi else "S/Z"
        pdf.set_x(10)
        pdf.cell(40, 8, zona, border=1, align="C")
        pdf.cell(60, 8, ubi, border=1, align="C")
        pdf.cell(90, 8, "", border=1, align="L")
        pdf.ln(8)

    nombre_archivo = os.path.join("reportes_inventario", f"Ubicaciones_Vacias_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf")
    pdf.output(nombre_archivo)
    if os.name == "nt":
        try:
            os.startfile(nombre_archivo)
        except Exception:
            pass
    return nombre_archivo


def separador_vertical():
    return ft.Container(
        width=1,
        height=30,
        bgcolor=ft.Colors.BLUE_GREY_200,
        margin=ft.Margin.symmetric(horizontal=6),
    )


def campo_texto(label: str, width: int = None, expand=None, value: str = "", keyboard_type=None, on_change=None):
    return ft.TextField(
        label=label,
        width=width,
        expand=expand,
        value=value,
        dense=True,
        text_size=12,
        label_style=ft.TextStyle(size=11),
        content_padding=ft.Padding.symmetric(horizontal=12, vertical=10),
        keyboard_type=keyboard_type,
        on_change=on_change,
        border_radius=6,
    )


def campo_dropdown(label: str, width: int = None, expand=None, value: str = None, options: list = None):
    return ft.Dropdown(
        label=label,
        width=width,
        expand=expand,
        value=value,
        options=options or [],
        dense=True,
        text_size=12,
        label_style=ft.TextStyle(size=11),
        content_padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        border_radius=6,
    )


def crear_tarjeta(contenido, padding=14, expand_val=None, height_val=None, bgcolor_val=ft.Colors.WHITE, lista_registro=None):
    c = ft.Container(
        content=contenido,
        padding=padding,
        height=height_val,
        expand=expand_val,
        bgcolor=bgcolor_val,
        border_radius=8,
        border=ft.Border.all(1, "#E2E8F0"),
        shadow=ft.BoxShadow(
            spread_radius=0,
            blur_radius=8,
            color=ft.Colors.BLACK_12,
            offset=ft.Offset(0, 2),
        ),
    )
    if lista_registro is not None:
        lista_registro.append(c)
    return c


def crear_kpi_card(
    titulo: str,
    txt_valor_control: ft.Text,
    subtitulo: str,
    color_icono: str,
    bg_icono: str,
    icono,
    lista_registro=None,
):
    box_icono = ft.Container(
        content=ft.Icon(icono, color=color_icono, size=22),
        bgcolor=bg_icono,
        padding=10,
        border_radius=8,
    )
    card = ft.Container(
        expand=1,
        padding=12,
        bgcolor=ft.Colors.WHITE,
        border_radius=8,
        border=ft.Border.all(1, "#E2E8F0"),
        content=ft.Row(
            [
                box_icono,
                ft.Column(
                    [
                        ft.Text(titulo.upper(), size=10, color="#475569", weight=ft.FontWeight.BOLD),
                        txt_valor_control,
                        ft.Text(subtitulo, size=10, color="#64748B"),
                    ],
                    spacing=1,
                ),
            ],
            spacing=10,
        ),
    )
    if lista_registro is not None:
        lista_registro.append((card, box_icono, txt_valor_control))
    return card


def crear_badge_estado(texto: str, color_texto: str, color_fondo: str):
    return ft.Container(
        padding=ft.Padding.symmetric(horizontal=9, vertical=3),
        bgcolor=color_fondo,
        border_radius=4,
        content=ft.Text(texto.upper(), color=color_texto, size=10, weight=ft.FontWeight.BOLD),
    )


def boton_primario(texto: str, icono, evento, color="#1E3A8A", disabled=False, height_val=35):
    return ft.Button(
        content=ft.Text(texto, size=11, weight=ft.FontWeight.BOLD),
        icon=icono,
        bgcolor=color,
        color=ft.Colors.WHITE,
        on_click=evento,
        disabled=disabled,
        height=height_val,
        style=ft.ButtonStyle(
            padding=ft.Padding.symmetric(horizontal=12, vertical=6),
            shape=ft.RoundedRectangleBorder(radius=6),
        ),
    )


def envolver_tabla_scroll(tabla: ft.DataTable, altura_inicial: int):
    return ft.Container(
        height=altura_inicial,
        content=ft.Column(
            [ft.Row([tabla], scroll=ft.ScrollMode.AUTO)],
            scroll=ft.ScrollMode.AUTO,
        ),
    )


def barra_horizontal_bi(etiqueta: str, valor: float, max_val: float, sufijo: str, color_barra: str):
    pct = min(1.0, max(0.05, valor / max(0.1, max_val)))
    return ft.Column(
        [
            ft.Row(
                [
                    ft.Text(etiqueta, size=11, weight=ft.FontWeight.W_600, color="#1E293B"),
                    ft.Text(f"{valor:.1f} {sufijo}", size=11, weight=ft.FontWeight.BOLD, color=color_barra),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.ProgressBar(value=pct, height=8, color=color_barra, bgcolor="#E2E8F0", border_radius=4),
        ],
        spacing=3,
    )


def barra_apilada_turno(sector: str, manana_un: int, tarde_un: int, max_total: int):
    total = max(1, manana_un + tarde_un)
    ancho_total_pct = min(1.0, total / max(1, max_total))
    flex_m = max(1, int((manana_un / total) * 100))
    flex_t = max(1, 100 - flex_m)
    return ft.Column(
        [
            ft.Row(
                [
                    ft.Text(sector, size=11, weight=ft.FontWeight.BOLD, color="#0F172A"),
                    ft.Text(f"Mañana: {manana_un} UN  |  Tarde: {tarde_un} UN  (Total: {total})", size=10, color="#475569"),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Container(
                height=12,
                border_radius=4,
                bgcolor="#F1F5F9",
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                content=ft.Row(
                    [
                        ft.Container(expand=int(flex_m * ancho_total_pct), bgcolor="#1D4ED8", tooltip=f"Turno Mañana: {manana_un} UN"),
                        ft.Container(expand=int(flex_t * ancho_total_pct), bgcolor="#0D9488", tooltip=f"Turno Tarde: {tarde_un} UN"),
                        ft.Container(expand=max(0, int(100 * (1.0 - ancho_total_pct))), bgcolor="#E2E8F0"),
                    ],
                    spacing=0,
                ),
            ),
        ],
        spacing=3,
    )


# =====================================================================
# 6. APLICACION PRINCIPAL - TORRE DE CONTROL BI & WMS
# =====================================================================

def notificar_global(page, texto: str, color: str = "#1E3A8A"):
    import flet as ft
    page.show_dialog(
        ft.SnackBar(
            content=ft.Text(texto, color=ft.Colors.WHITE, weight=ft.FontWeight.W_600, size=12),
            bgcolor=color,
        )
    )
    page.update()

def mostrar_aviso_ingreso_modal_global(page, lpn_str: str, sku_str: str, unid_str: str, lote_str: str, qa_str: str):
    import flet as ft
    from datetime import datetime
    dialogo_ingreso = ft.AlertDialog(
        modal=False,
        title=ft.Row(
            [
                ft.Icon(ft.Icons.NOTIFICATIONS_ACTIVE_ROUNDED, color="#1E3A8A"),
                ft.Text("AVISO OFICIAL DE INGRESO EN ANDEN", size=15, weight=ft.FontWeight.BOLD),
            ],
            spacing=10,
        ),
        content=ft.Container(
            width=420,
            padding=12,
            bgcolor="#F8FAFC",
            border_radius=6,
            content=ft.Column(
                [
                    ft.Text(f"IDENTIFICADOR LPN: {lpn_str}", weight=ft.FontWeight.BOLD, size=14),
                    ft.Text(f"ARTICULO (SKU): {sku_str}", size=13),
                    ft.Text(f"CANTIDAD INGRESADA: {unid_str} UNIDADES", size=13, weight=ft.FontWeight.W_600),
                    ft.Text(f"LOTE REGISTRADO: {lote_str}", size=13),
                    ft.Text(f"DICTAMEN CALIDAD (QA): {qa_str}", size=13, weight=ft.FontWeight.BOLD),
                    ft.Text(f"TIMESTAMP: {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}", size=11, color="#64748B"),
                ],
                tight=True,
                spacing=6,
            ),
        ),
        actions=[ft.Button("CONFIRMAR LECTURA", on_click=lambda e: page.pop_dialog())],
    )
    page.show_dialog(dialogo_ingreso)
    page.update()

def reimprimir_desde_fila_global(page, lpn_cod: str):
    try:
        res = supabase.table("registro_recepcion").select("*").eq("lpn", lpn_cod).execute()
        if res.data:
            ruta = generar_pdf_recepcion_15x10(lpn_cod, res.data); descargar_o_abrir_archivo(page, ruta)
            notificar_global(page, f"Etiqueta LPN {lpn_cod} generada correctamente.", "#047857")
        else:
            notificar_global(page, f"No se encontró el LPN {lpn_cod}.", "#D97706")
    except Exception as ex:
        notificar_global(page, f"Error al generar documento para {lpn_cod}: {ex}", "#B91C1C")

def hash_password_seguro(password_plana: str) -> str:
    salt = os.getenv("WMS_PASSWORD_SALT", "ludipek_wms_salt_2026")
    return "sha256$" + hashlib.sha256(f"{salt}:{password_plana}".encode("utf-8")).hexdigest()


def verificar_password_seguro(password_ingresada: str, password_guardada: str) -> bool:
    if not password_ingresada or not password_guardada:
        return False
    guardada_str = str(password_guardada).strip()
    if guardada_str.startswith("sha256$"):
        return hmac.compare_digest(hash_password_seguro(password_ingresada.strip()), guardada_str)
    # Compatibilidad con usuarios actuales mientras migran a hash
    return hmac.compare_digest(password_ingresada.strip(), guardada_str)


def descargar_o_abrir_archivo(page: ft.Page, ruta_archivo: str):
    """Publica el archivo en assets/descargas/ y lo abre/descarga en el navegador web."""
    if not ruta_archivo or not os.path.exists(ruta_archivo):
        return
    try:
        carpeta_pub = os.path.join("assets", "descargas")
        os.makedirs(carpeta_pub, exist_ok=True)
        nombre_limpio = os.path.basename(ruta_archivo)
        destino_pub = os.path.join(carpeta_pub, nombre_limpio)
        if os.path.abspath(ruta_archivo) != os.path.abspath(destino_pub):
            shutil.copy2(ruta_archivo, destino_pub)
        if page is not None:
            page.launch_url(f"/descargas/{urllib.parse.quote(nombre_limpio)}")
    except Exception as ex_dl:
        print(f"[WARN] Error enviando archivo al navegador: {ex_dl}")
